#!/usr/bin/env python3
"""Anvil v4 Pillar 6 — Bounded 2-Seat Cross-Family Orchestrator <-> Validator
Reconciliation & Atomic Attestation Receipt (`scripts/anvil_v4_xval.py`).

Enforces hard ceilings (`max_concurrency <= 2`, `max_digest_bytes <= 32768`,
`timeout_sec <= 60.0`), zero per-file serial LLM spawns, `shell=False` argv
validation, scrubbed credential environment, process-tree kill on timeout,
data-only JSON schema parsing, and honest `DETERMINISTIC_FALLBACK` when offline.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from anvil_v4_process import (
    AnvilRefusalError,
    _parse_strict_json_bytes,
    atomic_locked_read_json,
    atomic_locked_write_json,
    build_process_map,
)
from anvil_v4_refactor import build_refactor_map
from anvil_v4_trace import (
    EXECUTION_POLICY,
    ISOLATION_BOUNDARY,
    _kill_process_tree,
    build_scrubbed_env,
)

XVAL_RECEIPT_SCHEMA = "anvil-v4-xval-receipt/v1"
XVAL_DIGEST_SCHEMA = "anvil-v4-xval-digest/v1"
SEAT_RECEIPT_SCHEMA = "anvil-v4-seat-receipt/v1"
HOST_KEYRING_SCHEMA = "anvil-v4-host-keyring/v1"

MAX_XVAL_CONCURRENCY = 2
MAX_XVAL_DIGEST_BYTES = 32_768
MAX_XVAL_TIMEOUT_SEC = 60.0

KNOWN_VENDOR_FAMILIES = frozenset({"claude", "chatgpt", "gemini", "grok"})
_TRUSTED_VENDOR_CLI_BINARIES: Dict[str, str] = {
    "claude": "claude",
    "codex": "chatgpt",
    "gemini": "gemini",
    "agy": "gemini",
    "grok": "grok",
}
_VENDOR_FAMILY_ALIASES: Dict[str, str] = {
    "claude": "claude",
    "anthropic": "claude",
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "codex": "chatgpt",
    "gpt": "chatgpt",
    "o1": "chatgpt",
    "o3": "chatgpt",
    "o4": "chatgpt",
    "gemini": "gemini",
    "google": "gemini",
    "agy": "gemini",
    "grok": "grok",
    "xai": "grok",
}


def _is_safe_claim_token(raw: str) -> bool:
    return bool(raw) and not any(ord(ch) < 32 or ch == "|" for ch in raw)


def _is_valid_hex_secret(raw: Any) -> bool:
    return (
        isinstance(raw, str)
        and len(raw) >= 64
        and len(raw) % 2 == 0
        and all(ch in "0123456789abcdefABCDEF" for ch in raw)
    )


def _is_untrusted_repo_path(candidate: Path, repo_root: Path) -> bool:
    """Return True if `candidate` (raw or symlink-resolved) resides inside `repo_root`."""
    root_res = repo_root.resolve()
    raw_abs = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
    try:
        cand_res = candidate.resolve()
    except OSError:
        return True
    for probe in (raw_abs, cand_res):
        if probe == root_res or probe.is_relative_to(root_res):
            return True
    return False


def _infer_model_vendor_family(model_id: str) -> str:
    tok = (model_id or "").strip().lower()
    if not tok:
        return ""
    matched: List[str] = []
    for part in [p for p in re.split(r"[^a-z0-9]+", tok) if p]:
        fam = _VENDOR_FAMILY_ALIASES.get(part, "")
        if fam and fam not in matched:
            matched.append(fam)
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "conflict"
    return ""


def compute_seat1_hmac(
    seat_secret_hex: str,
    served_family: str,
    served_model: str,
    repo_fingerprint: str,
) -> str:
    msg = f"anvil-v4-seat1|{served_family}|{served_model}|{repo_fingerprint}"
    return hmac.new(seat_secret_hex.strip().encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_seat2_hmac(
    seat_secret_hex: str,
    challenge_nonce: str,
    digest_sha256: str,
    reported_family: str,
    reported_model: str,
    verdict: str,
) -> str:
    msg = f"anvil-v4-seat2|{challenge_nonce}|{digest_sha256}|{reported_family}|{reported_model}|{verdict}"
    return hmac.new(seat_secret_hex.strip().encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_seat2_receipt_hmac(
    seat_secret_hex: str,
    served_family: str,
    served_model: str,
    repo_fingerprint: str,
    validator_argv_sha256: str,
) -> str:
    msg = f"anvil-v4-seat2-receipt|{served_family}|{served_model}|{repo_fingerprint}|{validator_argv_sha256}"
    return hmac.new(seat_secret_hex.strip().encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_vendor_family(raw: str) -> str:
    tok = (raw or "").strip().lower()
    if not tok:
        return ""
    if tok in _VENDOR_FAMILY_ALIASES:
        return _VENDOR_FAMILY_ALIASES[tok]
    for part in [p for p in re.split(r"[^a-z0-9]+", tok) if p]:
        if part in _VENDOR_FAMILY_ALIASES:
            return _VENDOR_FAMILY_ALIASES[part]
    return ""


def _infer_argv_vendor_families(cmd_argv: Sequence[str], orchestrator_family: str) -> List[str]:
    found: List[str] = []
    for tok in cmd_argv:
        raw_name = Path(tok).name.lower() if ("/" in tok or "\\" in tok) else tok.strip().lower()
        base = re.sub(r"\.(exe|py|mjs|js|ts|sh|bat|cmd|ps1)$", "", raw_name)
        if "same_family" in base or "same-family" in base:
            fam = orchestrator_family if orchestrator_family in KNOWN_VENDOR_FAMILIES else "same_family"
            if fam not in found:
                found.append(fam)
            continue
        for word in [w for w in re.split(r"[^a-z0-9]+", base) if w]:
            if word in _VENDOR_FAMILY_ALIASES:
                fam = _VENDOR_FAMILY_ALIASES[word]
                if fam not in found:
                    found.append(fam)
    return found


def _validate_validator_argv(raw_argv: Any) -> List[str]:
    """Validate an explicit cross-family validator `argv` list (`shell=False`, zero shells/eval flags)."""
    if isinstance(raw_argv, (str, bytes)) or not isinstance(raw_argv, (list, tuple)) or len(raw_argv) == 0:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            "Validator invocation requires a non-empty explicit argv list of strings.",
            cwe="CWE-78",
        )
    clean: List[str] = []
    for idx, tok in enumerate(raw_argv):
        if not isinstance(tok, str) or not tok.strip() or "\x00" in tok:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Invalid or empty validator argv[{idx}] token refused.",
                cwe="CWE-78",
            )
        clean.append(tok)

    bin_str = clean[0].strip()
    bin_p = Path(bin_str)
    low_name = bin_p.name.lower()
    suffix = bin_p.suffix.lower()
    stem = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", low_name)
    if stem in EXECUTION_POLICY["forbidden_shells"] or suffix in {".bat", ".cmd", ".ps1", ".sh"}:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            f"Shell or wrapper binary '{bin_str}' refused for validator execution.",
            cwe="CWE-78",
            details={"argv0": bin_str},
        )

    for tok in clean[1:]:
        low_t = tok.lower()
        if low_t in EXECUTION_POLICY["forbidden_inline_flags"] or low_t.startswith(
            ("-c=", "-e=", "--eval=", "--command=", "-command=")
        ):
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Inline code evaluation flag '{tok}' refused in validator argv.",
                cwe="CWE-78",
                details={"flag": tok},
            )
    return clean


def _resolve_validator_binary(cmd_argv: Sequence[str]) -> Optional[List[str]]:
    raw_bin = cmd_argv[0]
    bp = Path(raw_bin)
    if "/" in raw_bin or "\\" in raw_bin or bp.is_absolute():
        if bp.is_file():
            return [str(bp.resolve()), *cmd_argv[1:]]
        return None
    found = shutil.which(raw_bin)
    if found:
        return [found, *cmd_argv[1:]]
    return None


def _run_deterministic_seat2_checks(
    proc_map: Dict[str, Any],
    ref_map: Dict[str, Any],
    paper_map: Optional[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    findings: List[Dict[str, Any]] = []
    cons = ref_map.get("symbol_conservation") or {}
    if not cons.get("conserved", False) or (cons.get("unaccounted_symbols") or []):
        findings.append({
            "severity": "FAIL",
            "code": "SYMBOL_CONSERVATION_DRIFT",
            "detail": f"Unaccounted symbols detected: {cons.get('unaccounted_symbols')}",
        })

    for stg in (proc_map.get("l1_stages") or []) + (ref_map.get("target_stages") or []):
        if int(stg.get("width", 0)) <= 0 or int(stg.get("height", 0)) <= 0:
            findings.append({
                "severity": "FAIL",
                "code": "INVALID_STAGE_COORDINATES",
                "detail": f"Stage {stg.get('id')} missing positive steady dimensions.",
            })

    for unex in (ref_map.get("null_set") or {}).get("null_unexercised") or []:
        if not unex.get("protected_from_deletion", False):
            findings.append({
                "severity": "FAIL",
                "code": "UNEXERCISED_NOT_PROTECTED",
                "detail": f"Unexercised symbol {unex.get('id')} lacks protected_from_deletion=True.",
            })

    if isinstance(paper_map, dict):
        for eq in paper_map.get("equations") or []:
            mml = str(eq.get("mathml") or "")
            if "$" in mml or (mml and "<math" not in mml):
                findings.append({
                    "severity": "FAIL",
                    "code": "RAW_LATEX_IN_MATHML",
                    "detail": f"Equation {eq.get('id')} failed native MathML check.",
                })

    has_fail = any(f["severity"] == "FAIL" for f in findings)
    has_warn = any(f["severity"] == "WARN" for f in findings)
    verdict = "FAIL" if has_fail else ("WARN" if has_warn else "PASS")
    return verdict, findings


def _refuse_repo_local_validator_argv(
    configured_argv: Sequence[str],
    resolved_argv: Optional[Sequence[str]],
    repo_root: Path,
) -> None:
    """Refuse execution if any validator executable or script path resolves inside `repo_root` (`CWE-78`)."""
    tokens = list(configured_argv) + list(resolved_argv or [])
    for tok in tokens:
        cand_str = ""
        if tok.startswith("-"):
            if "=" in tok:
                cand_str = tok.split("=", 1)[1].strip()
        else:
            cand_str = tok.strip()
        if not cand_str:
            continue
        p = Path(cand_str)
        if p.is_absolute() or "/" in cand_str or "\\" in cand_str:
            if _is_untrusted_repo_path(p, repo_root):
                raise AnvilRefusalError(
                    "EXECUTION_POLICY_REFUSED",
                    "Audited repository path cannot execute as its own cross-family validator.",
                    cwe="CWE-78",
                    details={"token": cand_str},
                )
        elif p.suffix.lower() in {".py", ".js", ".mjs", ".cjs", ".ts", ".exe"} and (repo_root / cand_str).exists():
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                "Audited repository script cannot execute as its own cross-family validator.",
                cwe="CWE-78",
                details={"token": cand_str},
            )


def _load_host_keyring(
    keyring_path: Optional[Path],
    repo_root: Path,
) -> Optional[Dict[str, Dict[str, str]]]:
    """Load out-of-repo host HMAC-SHA256 seat keyring (`anvil-v4-host-keyring/v1`).
    Repository-local keyrings or keyrings reusing secrets across distinct vendor families are rejected.
    """
    if keyring_path is None:
        return None
    if _is_untrusted_repo_path(keyring_path, repo_root) or not keyring_path.is_file():
        return None
    try:
        doc = atomic_locked_read_json(keyring_path)
    except AnvilRefusalError:
        return None
    if not isinstance(doc, dict) or doc.get("schema") != HOST_KEYRING_SCHEMA:
        return None

    raw_orch = doc.get("orchestrator_seats")
    raw_val = doc.get("validator_seats")
    if not isinstance(raw_orch, dict) or not isinstance(raw_val, dict):
        return None

    orch_seats: Dict[str, str] = {}
    val_seats: Dict[str, str] = {}
    secret_owner_family: Dict[str, str] = {}

    for seat_map, target in ((raw_orch, orch_seats), (raw_val, val_seats)):
        for raw_fam, raw_sec in seat_map.items():
            if not isinstance(raw_fam, str):
                return None
            fam = raw_fam.strip().lower()
            if fam not in KNOWN_VENDOR_FAMILIES or not _is_valid_hex_secret(raw_sec):
                return None
            norm_sec = str(raw_sec).strip().lower()
            prev_fam = secret_owner_family.get(norm_sec)
            if prev_fam is not None and prev_fam != fam:
                return None
            secret_owner_family[norm_sec] = fam
            target[fam] = str(raw_sec).strip()

    if not orch_seats and not val_seats:
        return None
    return {"orchestrator_seats": orch_seats, "validator_seats": val_seats}


def _verify_orchestrator_seat_receipt(
    receipt_path: Optional[Path],
    repo_root: Path,
    repo_fingerprint: str,
    keyring: Optional[Dict[str, Dict[str, str]]],
) -> Tuple[bool, str, str]:
    """Verify out-of-repo HMAC-SHA256 Seat-1 provenance receipt bound to `repo_fingerprint`.
    Refuses repository-local files, unsigned receipts, and environment strings.
    """
    if keyring is None or receipt_path is None:
        return False, "unattested", ""
    if _is_untrusted_repo_path(receipt_path, repo_root) or not receipt_path.is_file():
        return False, "unattested", ""
    try:
        doc = atomic_locked_read_json(receipt_path)
    except AnvilRefusalError:
        return False, "unattested", ""
    if not isinstance(doc, dict) or doc.get("schema") != SEAT_RECEIPT_SCHEMA:
        return False, "unattested", ""
    if doc.get("seat") != "orchestrator":
        return False, "unattested", ""
    raw_fam = str(doc.get("served_family") or "").strip().lower()
    served_fam = raw_fam if raw_fam in KNOWN_VENDOR_FAMILIES else ""
    served_model = str(doc.get("served_model") or "").strip()
    rec_fp = str(doc.get("repo_fingerprint") or "").strip()
    rec_hmac = str(doc.get("hmac_sha256") or "").strip().lower()
    seat_secret = keyring["orchestrator_seats"].get(served_fam, "")
    if (
        not served_fam
        or not seat_secret
        or not _is_safe_claim_token(served_model)
        or _infer_model_vendor_family(served_model) != served_fam
        or not _is_safe_claim_token(repo_fingerprint)
        or not rec_hmac
        or not hmac.compare_digest(rec_fp, repo_fingerprint)
    ):
        return False, "unattested", ""
    expected_hmac = compute_seat1_hmac(seat_secret, served_fam, served_model, repo_fingerprint)
    if not hmac.compare_digest(rec_hmac, expected_hmac):
        return False, "unattested", ""
    return True, served_fam, served_model


def _verify_validator_seat_receipt(
    receipt_path: Optional[Path],
    repo_root: Path,
    repo_fingerprint: str,
    configured_argv: Sequence[str],
    reported_family: str,
    reported_model: str,
    keyring: Optional[Dict[str, Dict[str, str]]],
) -> Tuple[bool, str]:
    """Verify optional out-of-repo HMAC-SHA256 Seat-2 receipt bound to `repo_fingerprint` and `validator_argv_sha256`."""
    if keyring is None or receipt_path is None:
        return False, ""
    if _is_untrusted_repo_path(receipt_path, repo_root) or not receipt_path.is_file():
        return False, ""
    try:
        doc = atomic_locked_read_json(receipt_path)
    except AnvilRefusalError:
        return False, ""
    if not isinstance(doc, dict) or doc.get("schema") != SEAT_RECEIPT_SCHEMA:
        return False, ""
    raw_fam = str(doc.get("served_family") or "").strip().lower()
    rec_fam = raw_fam if raw_fam in KNOWN_VENDOR_FAMILIES else _normalize_vendor_family(raw_fam)
    if doc.get("seat") != "validator":
        return False, rec_fam
    rec_model = str(doc.get("served_model") or "").strip()
    rec_fp = str(doc.get("repo_fingerprint") or "").strip()
    rec_argv_sha = str(doc.get("validator_argv_sha256") or "").strip().lower()
    rec_hmac = str(doc.get("hmac_sha256") or "").strip().lower()
    seat_secret = keyring["validator_seats"].get(raw_fam, "") if raw_fam in KNOWN_VENDOR_FAMILIES else ""
    expected_argv_sha = hashlib.sha256(
        json.dumps(list(configured_argv), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        raw_fam not in KNOWN_VENDOR_FAMILIES
        or not seat_secret
        or raw_fam != reported_family
        or not _is_safe_claim_token(rec_model)
        or rec_model != reported_model
        or not _is_safe_claim_token(repo_fingerprint)
        or not rec_hmac
        or not hmac.compare_digest(rec_fp, repo_fingerprint)
        or not hmac.compare_digest(rec_argv_sha, expected_argv_sha)
    ):
        return False, rec_fam
    expected_hmac = compute_seat2_receipt_hmac(
        seat_secret, raw_fam, rec_model, repo_fingerprint, expected_argv_sha
    )
    return hmac.compare_digest(rec_hmac, expected_hmac), rec_fam


class _ValidatorServiceUnavailableError(Exception):
    """Raised when a configured validator CLI exits non-zero, cannot launch, or times out (offline/unavailable)."""


def _invoke_single_validator_shard(
    resolved_argv: List[str],
    shard_obj: Dict[str, Any],
    digest_sha256: str,
    max_digest_bytes: int,
    timeout_sec: float,
    shard_id: str,
    validator_seats: Dict[str, str],
) -> Dict[str, Any]:
    challenge_nonce = secrets.token_hex(16)
    bound_payload = {
        **shard_obj,
        "digest_sha256": digest_sha256,
        "challenge_nonce": challenge_nonce,
    }
    shard_payload_bytes = json.dumps(
        bound_payload,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(shard_payload_bytes) > max_digest_bytes:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Validator shard payload ({len(shard_payload_bytes)} bytes) exceeds max_digest_bytes={max_digest_bytes}.",
            details={
                "bound_name": "max_digest_bytes",
                "bound_limit": max_digest_bytes,
                "observed_value": len(shard_payload_bytes),
            },
        )

    scratch_dir = Path(tempfile.mkdtemp(prefix=f"anvil_xval_{shard_id}_"))
    try:
        scrubbed_env = build_scrubbed_env(scratch_dir / "_home")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                resolved_argv,
                cwd=str(scratch_dir),
                env=scrubbed_env,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=(os.name != "nt"),
                creationflags=creationflags,
            )
        except OSError as os_err:
            raise _ValidatorServiceUnavailableError(
                f"Validator CLI failed to start ({os_err}); falling back to deterministic verification."
            ) from os_err

        try:
            stdout_b, stderr_b = proc.communicate(input=shard_payload_bytes, timeout=float(timeout_sec))
        except subprocess.TimeoutExpired as tex:
            _kill_process_tree(proc)
            raise _ValidatorServiceUnavailableError(
                f"Validator shard '{shard_id}' timed out after {timeout_sec}s (process tree killed); falling back to deterministic verification."
            ) from tex
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000))

        if proc.returncode != 0:
            err_preview = stderr_b.decode("utf-8", errors="replace").strip()[:240]
            raise _ValidatorServiceUnavailableError(
                f"Validator CLI exited with status {proc.returncode}"
                + (f" ({err_preview})" if err_preview else "")
                + "; falling back to deterministic verification."
            )

        try:
            parsed = _parse_strict_json_bytes(stdout_b, max_bytes=1_048_576)
        except AnvilRefusalError as p_err:
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                "Malformed trace/validator payload — rejected fail-closed",
                cwe="CWE-502",
                details={
                    "status_kind": "dependency-returns-garbage",
                    "http_status": 502,
                    "parse_error": p_err.message,
                },
            ) from p_err

        verdict = parsed.get("verdict")
        family = parsed.get("family")
        findings = parsed.get("findings")
        if (
            verdict not in {"PASS", "WARN", "FAIL"}
            or not isinstance(family, str)
            or not family.strip()
            or not isinstance(findings, list)
        ):
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                "Malformed trace/validator payload — rejected fail-closed",
                cwe="CWE-502",
                details={
                    "status_kind": "dependency-returns-garbage",
                    "http_status": 502,
                    "reason": "Missing required validator schema keys {verdict, family, findings}.",
                },
            )

        raw_echo_nonce = parsed.get("echoed_nonce")
        raw_echo_digest = parsed.get("echoed_digest_sha256")
        raw_served_model = parsed.get("served_model")
        raw_att_hmac = parsed.get("attestation_hmac")
        served_model = raw_served_model.strip() if isinstance(raw_served_model, str) else ""
        att_hmac = raw_att_hmac.strip().lower() if isinstance(raw_att_hmac, str) else ""
        exact_family = family.strip().lower()
        challenge_verified = bool(
            isinstance(raw_echo_nonce, str)
            and hmac.compare_digest(raw_echo_nonce, challenge_nonce)
            and isinstance(raw_echo_digest, str)
            and hmac.compare_digest(raw_echo_digest, digest_sha256)
            and _is_safe_claim_token(served_model)
        )
        seat2_secret = validator_seats.get(exact_family, "") if exact_family in KNOWN_VENDOR_FAMILIES else ""
        hmac_verified = False
        if (
            challenge_verified
            and seat2_secret
            and att_hmac
            and _infer_model_vendor_family(served_model) == exact_family
        ):
            expected_mac = compute_seat2_hmac(
                seat2_secret,
                challenge_nonce,
                digest_sha256,
                exact_family,
                served_model,
                verdict,
            )
            hmac_verified = hmac.compare_digest(att_hmac, expected_mac)

        return {
            "shard_id": shard_id,
            "verdict": verdict,
            "family": family.strip(),
            "served_model": served_model,
            "challenge_verified": challenge_verified,
            "hmac_verified": hmac_verified,
            "findings": findings[:50],
            "elapsed_ms": elapsed_ms,
        }
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def run_xval_audit(
    repo_dir: str | Path,
    *,
    process_map: Optional[Dict[str, Any]] = None,
    refactor_map: Optional[Dict[str, Any]] = None,
    paper_map: Optional[Dict[str, Any]] = None,
    validator_argv: Optional[Sequence[str]] = None,
    attestation_keyring_path: Optional[str | Path] = None,
    orchestrator_receipt_path: Optional[str | Path] = None,
    validator_receipt_path: Optional[str | Path] = None,
    max_concurrency: int = 2,
    max_digest_bytes: int = MAX_XVAL_DIGEST_BYTES,
    timeout_sec: float = MAX_XVAL_TIMEOUT_SEC,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run bounded 2-Seat Orchestrator <-> Cross-Family Validator reconciliation (`<= 2`
    concurrent calls, `<= 32` KB claim digest, `60s` timeout) and persist atomic receipt.
    """
    if max_concurrency <= 0 or max_concurrency > MAX_XVAL_CONCURRENCY:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_concurrency ({max_concurrency}) must be within 1..{MAX_XVAL_CONCURRENCY}.",
            details={
                "bound_name": "max_concurrency",
                "bound_limit": MAX_XVAL_CONCURRENCY,
                "observed_value": max_concurrency,
            },
        )
    if max_digest_bytes <= 0 or max_digest_bytes > MAX_XVAL_DIGEST_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_digest_bytes ({max_digest_bytes}) must be within 1..{MAX_XVAL_DIGEST_BYTES}.",
            details={
                "bound_name": "max_digest_bytes",
                "bound_limit": MAX_XVAL_DIGEST_BYTES,
                "observed_value": max_digest_bytes,
            },
        )
    if timeout_sec <= 0 or timeout_sec > MAX_XVAL_TIMEOUT_SEC:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"timeout_sec ({timeout_sec}) must be within (0, {MAX_XVAL_TIMEOUT_SEC}].",
            details={
                "bound_name": "timeout_sec",
                "bound_limit": MAX_XVAL_TIMEOUT_SEC,
                "observed_value": timeout_sec,
            },
        )

    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    v4_dir = root / ".anvil" / "v4"
    proc_map = process_map
    if proc_map is None:
        pm_file = v4_dir / "process_map.json"
        proc_map = atomic_locked_read_json(pm_file) if pm_file.is_file() else build_process_map(root, persist=False)

    ref_map = refactor_map
    if ref_map is None:
        rm_file = v4_dir / "refactor_map.json"
        ref_map = atomic_locked_read_json(rm_file) if rm_file.is_file() else build_refactor_map(root, persist=False)

    pap_map = paper_map
    if pap_map is None and (v4_dir / "paper_map.json").is_file():
        pap_map = atomic_locked_read_json(v4_dir / "paper_map.json")

    current_repo_fp = str(proc_map.get("repo_fingerprint") or ref_map.get("repo_fingerprint") or "")
    keyring = _load_host_keyring(Path(attestation_keyring_path) if attestation_keyring_path else None, root)
    orchestrator_attested, orchestrator_family, orchestrator_model = _verify_orchestrator_seat_receipt(
        Path(orchestrator_receipt_path) if orchestrator_receipt_path else None,
        root,
        current_repo_fp,
        keyring,
    )
    det_verdict, det_findings = _run_deterministic_seat2_checks(proc_map, ref_map, pap_map)

    null_set = ref_map.get("null_set") or {}
    digest_obj: Dict[str, Any] = {
        "schema": XVAL_DIGEST_SCHEMA,
        "repo_fingerprint": current_repo_fp,
        "orchestrator_family": orchestrator_family,
        "stages": [
            {
                "id": s.get("id"),
                "kind": s.get("kind"),
                "verdict": s.get("verdict"),
                "symbols": (s.get("member_symbols") or [])[:16],
            }
            for s in (proc_map.get("l1_stages") or [])[:8]
        ],
        "target_stages": [
            {
                "id": ns.get("id"),
                "role": ns.get("role"),
                "symbol_count": ns.get("symbol_count", 0),
            }
            for ns in (ref_map.get("target_stages") or [])[:8]
        ],
        "symbol_conservation": ref_map.get("symbol_conservation") or {},
        "null_set_counts": {
            "null_proven": len(null_set.get("null_proven") or []),
            "null_unexercised": len(null_set.get("null_unexercised") or []),
            "null_redundant": len(null_set.get("null_redundant") or []),
        },
        "paper_claims": [
            {
                "id": eq.get("id"),
                "stamp": eq.get("verification_stamp") or eq.get("status"),
            }
            for eq in ((pap_map or {}).get("equations") or [])[:24]
        ],
        "deterministic_check_verdict": det_verdict,
    }
    digest_bytes = json.dumps(digest_obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(digest_bytes) > max_digest_bytes:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Batched claim digest ({len(digest_bytes)} bytes) exceeds max_digest_bytes={max_digest_bytes}.",
            details={
                "bound_name": "max_digest_bytes",
                "bound_limit": max_digest_bytes,
                "observed_value": len(digest_bytes),
            },
        )
    digest_sha256 = hashlib.sha256(digest_bytes).hexdigest()[:24]

    # Resolve optional validator argv from explicit arg or ANVIL_XVAL_VALIDATOR_ARGV_JSON
    configured_argv: Optional[List[str]] = None
    if validator_argv is not None:
        configured_argv = _validate_validator_argv(validator_argv)
    else:
        env_json = (os.environ.get("ANVIL_XVAL_VALIDATOR_ARGV_JSON") or "").strip()
        if env_json:
            try:
                raw_parsed = json.loads(env_json)
            except Exception as j_exc:
                raise AnvilRefusalError(
                    "MALFORMED_DATA_REFUSED",
                    f"ANVIL_XVAL_VALIDATOR_ARGV_JSON is not valid JSON: {j_exc}",
                    cwe="CWE-502",
                ) from j_exc
            if not isinstance(raw_parsed, list):
                raise AnvilRefusalError(
                    "EXECUTION_POLICY_REFUSED",
                    "ANVIL_XVAL_VALIDATOR_ARGV_JSON must be a JSON array of argv strings.",
                    cwe="CWE-78",
                )
            configured_argv = _validate_validator_argv(raw_parsed)

    offline_forced = (os.environ.get("ANVIL_XVAL_OFFLINE") or "").strip() == "1"
    resolved_cmd = _resolve_validator_binary(configured_argv) if (configured_argv and not offline_forced) else None
    if configured_argv:
        _refuse_repo_local_validator_argv(configured_argv, resolved_cmd, root)

    if resolved_cmd is None:
        fallback_reason = (
            "Forced offline via ANVIL_XVAL_OFFLINE=1."
            if offline_forced
            else (
                f"Configured validator binary '{configured_argv[0]}' not found on host."
                if configured_argv
                else "No external cross-family validator CLI configured; ran deterministic Seat-2 structural verification."
            )
        )
        receipt: Dict[str, Any] = {
            "ok": True,
            "schema": XVAL_RECEIPT_SCHEMA,
            "mode": "DETERMINISTIC_FALLBACK",
            "cross_family_attested": False,
            "orchestrator_family": orchestrator_family,
            "orchestrator_model": orchestrator_model,
            "validator_family": "deterministic_local_verifier",
            "verdict": det_verdict,
            "validator_calls_made": 0,
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": fallback_reason,
            "shards": [],
            "findings": det_findings,
        }
        if persist:
            atomic_locked_write_json(v4_dir / "xval_receipt.json", receipt)
        return receipt

    # Build <= 2 bounded batched shards (NEVER per-file serial spawns!)
    shard_specs: List[Tuple[str, Dict[str, Any]]] = []
    if max_concurrency >= 2:
        s1_obj = {**digest_obj, "shard": "S1_process_and_refactor"}
        s2_obj = {**digest_obj, "shard": "S2_paper_and_invariants"}
        probe_extra = 128  # reserve space for digest_sha256 + 128-bit challenge_nonce
        if (
            len(json.dumps(s1_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + probe_extra <= max_digest_bytes
            and len(json.dumps(s2_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + probe_extra <= max_digest_bytes
        ):
            shard_specs = [("shard_1", s1_obj), ("shard_2", s2_obj)]
        else:
            shard_specs = [("shard_1", digest_obj)]
    else:
        shard_specs = [("shard_1", digest_obj)]

    validator_seat_keys = dict(keyring["validator_seats"]) if keyring is not None else {}
    shard_results: List[Dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=min(MAX_XVAL_CONCURRENCY, max_concurrency, len(shard_specs))) as pool:
            futs = [
                pool.submit(
                    _invoke_single_validator_shard,
                    resolved_cmd,
                    s_obj,
                    digest_sha256,
                    max_digest_bytes,
                    timeout_sec,
                    sid,
                    validator_seat_keys,
                )
                for sid, s_obj in shard_specs
            ]
            for fut in futs:
                shard_results.append(fut.result())
    except _ValidatorServiceUnavailableError as unavail_err:
        fallback_receipt: Dict[str, Any] = {
            "ok": True,
            "schema": XVAL_RECEIPT_SCHEMA,
            "mode": "DETERMINISTIC_FALLBACK",
            "cross_family_attested": False,
            "orchestrator_family": orchestrator_family,
            "orchestrator_model": orchestrator_model,
            "validator_family": "deterministic_local_verifier",
            "verdict": det_verdict,
            "validator_calls_made": len(shard_specs),
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": str(unavail_err),
            "shards": [],
            "findings": det_findings,
        }
        if persist:
            atomic_locked_write_json(v4_dir / "xval_receipt.json", fallback_receipt)
        return fallback_receipt

    validator_families = list(dict.fromkeys(sr["family"] for sr in shard_results))
    lead_v_family = validator_families[0] if validator_families else ""
    exact_shard_families = [sr["family"].strip().lower() for sr in shard_results]
    all_known_single_family = bool(
        exact_shard_families
        and all(f in KNOWN_VENDOR_FAMILIES for f in exact_shard_families)
        and len(set(exact_shard_families)) == 1
    )
    canonical_v_family = exact_shard_families[0] if all_known_single_family else ""

    all_challenges_verified = bool(shard_results and all(sr["challenge_verified"] for sr in shard_results))
    all_hmacs_verified = bool(shard_results and all(sr["hmac_verified"] for sr in shard_results))
    shard_models = {sr["served_model"] for sr in shard_results if sr["served_model"]}
    single_served_model = next(iter(shard_models)) if (all_challenges_verified and len(shard_models) == 1) else ""

    raw_arg0 = (configured_argv[0] if configured_argv else "").strip()
    bin_p = Path(resolved_cmd[0])
    bin_stem = re.sub(r"\.exe$", "", bin_p.name.lower())
    bin_suffix = bin_p.suffix.lower()
    binary_vendor_family = (
        _TRUSTED_VENDOR_CLI_BINARIES.get(bin_stem, "")
        if (bin_suffix in {"", ".exe"} and "/" not in raw_arg0 and "\\" not in raw_arg0)
        else ""
    )

    val_receipt_ok = True
    val_receipt_family = ""
    if validator_receipt_path:
        val_receipt_ok, val_receipt_family = _verify_validator_seat_receipt(
            Path(validator_receipt_path),
            root,
            current_repo_fp,
            configured_argv or resolved_cmd,
            canonical_v_family,
            single_served_model,
            keyring,
        )

    inferred_argv_fams = _infer_argv_vendor_families(configured_argv or resolved_cmd, orchestrator_family)
    argv_conflict = bool(inferred_argv_fams and any(f != canonical_v_family for f in inferred_argv_fams))
    receipt_conflict = bool(val_receipt_family and val_receipt_family != canonical_v_family)
    binary_conflict = bool(binary_vendor_family and binary_vendor_family != canonical_v_family)

    validator_attested = bool(
        keyring is not None
        and all_known_single_family
        and all_challenges_verified
        and all_hmacs_verified
        and bool(single_served_model)
        and val_receipt_ok
        and not argv_conflict
        and not receipt_conflict
        and not binary_conflict
    )
    cross_family = bool(
        orchestrator_attested
        and validator_attested
        and canonical_v_family != orchestrator_family
    )
    if cross_family:
        receipt_mode = "CROSS_FAMILY_VALIDATED"
        attestation_reason = (
            f"Verified HMAC-attested cross-family validator ({canonical_v_family}/{single_served_model}) distinct from attested orchestrator ({orchestrator_family}/{orchestrator_model})."
        )
    else:
        norm_lead_fam = _normalize_vendor_family(lead_v_family)
        same_fam_signal = bool(
            orchestrator_attested
            and (
                norm_lead_fam == orchestrator_family
                or val_receipt_family == orchestrator_family
                or orchestrator_family in inferred_argv_fams
            )
        )
        receipt_mode = "SAME_FAMILY_UNATTESTED" if same_fam_signal else "UNATTESTED_VALIDATOR"
        if keyring is None:
            attestation_reason = (
                "No valid out-of-repo host HMAC keyring (--attestation-keyring) verified; repository-local and unsigned receipts are untrusted."
            )
        elif not orchestrator_attested:
            attestation_reason = (
                "No valid out-of-repo HMAC-signed Seat-1 orchestrator receipt verified for this repo_fingerprint."
            )
        elif not all_known_single_family:
            attestation_reason = "Validator reported an unrecognized or inconsistent vendor family."
        elif not all_challenges_verified or not single_served_model:
            attestation_reason = "Validator did not echo live cryptographic challenge_nonce, digest_sha256, and served_model."
        elif not all_hmacs_verified or not validator_attested:
            attestation_reason = "Validator reply lacked a valid per-call Seat-2 HMAC signature from the host keyring."
        else:
            attestation_reason = "Validator belongs to the same vendor family as orchestrator."

    merged_findings = list(det_findings)
    for sr in shard_results:
        merged_findings.extend(sr["findings"])

    verdicts = [det_verdict] + [sr["verdict"] for sr in shard_results]
    final_verdict = "FAIL" if "FAIL" in verdicts else ("WARN" if "WARN" in verdicts else "PASS")

    receipt = {
        "ok": True,
        "schema": XVAL_RECEIPT_SCHEMA,
        "mode": receipt_mode,
        "cross_family_attested": cross_family,
        "attestation_reason": attestation_reason,
        "orchestrator_family": orchestrator_family,
        "orchestrator_model": orchestrator_model,
        "validator_family": lead_v_family,
        "validator_model": single_served_model,
        "verdict": final_verdict,
        "validator_calls_made": len(shard_results),
        "max_concurrency_enforced": max_concurrency,
        "digest_bytes": len(digest_bytes),
        "digest_sha256": digest_sha256,
        "shards": shard_results,
        "findings": merged_findings,
    }
    if persist:
        atomic_locked_write_json(v4_dir / "xval_receipt.json", receipt)
    return receipt

