"""Lean Durable Replication & Ramanujan Audit Job Runner for Anchor AI Cockpits (`anvil_replication_job.py`).

Enforces:
  - Authoritative two-phase `{scope_sha256, consent_token}` verification + 1-click HMAC isolated wheel install,
  - HMAC-signed `replication_audit_receipt.json`, `xval_receipt.json`, and `ramanujan_verdicts.json` (`0` forged
    green badges or `.queue-btn` nodes from pre-baked `.anvil/v4/` files),
  - Component-by-component `os.lstat` reparse refusal across `.anvil/v4/` and `DELIVERABLES.md` (`CWE-22`/`CWE-59`),
  - Pre/post source-repo SHA-256 baseline across install + scratch runs, and unmasked latest-job failure reporting.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from steward_cockpit import anvil_py_deps as _apd
from steward_cockpit import anvil_session as _as

REPLICATION_JOB_SCHEMA = "anvil-replication-job/v1"
REPLICATION_CONSENT_SCHEMA = "anvil-replication-consent/v1"
REPLICATION_RECEIPT_FILE_SCHEMA = "anvil-replication-audit-receipt/v2"
REPLICATION_QUEUED_REFACTOR_SCHEMA = "anvil-queued-refactorings/v1"

MAX_PAPER_SOURCE_BYTES = 8 * 1024 * 1024
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_HEX_RE = re.compile(r"^[0-9a-f]{16,128}$")
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

sign_gate_artifact = _apd.sign_gate_artifact
verify_gate_artifact = _apd.verify_gate_artifact

REPLICATION_FAILURE_STATE_TABLE: Dict[str, Dict[str, Any]] = {
    "dependency-missing": {"status_kind": "dependency-missing", "failure_state": "dependency-missing", "http_status": 503, "state": "PIPELINE_DEPENDENCY_MISSING", "badge": "PIPELINE_DEPENDENCY_MISSING", "unknown_state": False, "message": "PIPELINE_DEPENDENCY_MISSING: Required Python package or replication engine module unavailable"},
    "dependency-slow-or-killed": {"status_kind": "dependency-slow-or-killed", "failure_state": "dependency-slow-or-killed", "http_status": 504, "state": "TIMEOUT_OR_CANCELLED", "badge": "TIMEOUT_OR_CANCELLED", "unknown_state": False, "message": "Replication audit timed out or was cancelled (process tree terminated)"},
    "dependency-returns-garbage": {"status_kind": "dependency-returns-garbage", "failure_state": "dependency-returns-garbage", "http_status": 502, "state": "INVALID_RECEIPT_OUTPUT", "badge": "INVALID_RECEIPT_OUTPUT", "unknown_state": False, "message": "Invalid replication receipt, consent payload, or malformed table output"},
    "backing-store-unreadable": {"status_kind": "backing-store-unreadable", "failure_state": "backing-store-unreadable", "http_status": 500, "state": "UNKNOWN", "badge": "UNKNOWN", "unknown_state": True, "message": "UNKNOWN: Replication backing store unreadable or corrupted"},
    "empty-but-valid": {"status_kind": "empty-but-valid", "failure_state": "empty-but-valid", "http_status": 200, "state": "NOT_YET_RUN", "badge": "NOT_YET_RUN", "unknown_state": False, "message": "not yet run — confirm operator consent to execute paper table replication in isolated scratch"},
}

_ACTIVE_PROCS_LOCK: threading.Lock = globals().setdefault("_ACTIVE_PROCS_LOCK", threading.Lock())
_ACTIVE_PROCS: Dict[str, Any] = globals().setdefault("_ACTIVE_PROCS", {})
_CANCEL_FLAGS: Dict[str, threading.Event] = globals().setdefault("_CANCEL_FLAGS", {})
_LIVE_JOB_THREADS: Dict[str, threading.Thread] = globals().setdefault("_LIVE_JOB_THREADS", {})
_ACTIVE_SYNC_JOBS: set[str] = globals().setdefault("_ACTIVE_SYNC_JOBS", set())


def _refuse403(code: str, msg: str) -> Tuple[Dict[str, Any], int]:
    return ({"ok": False, "anvil_v6_enabled": True, "error_code": code, "http_status": 403, "message": msg, "error": code}, 403)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_replication_failure_response(
    row_key: str, *, http_status_override: Optional[int] = None, error_code: Optional[str] = None,
    detail: str = "", extra: Optional[Mapping[str, Any]] = None, anchor_root: Path | str | None = None,
) -> Tuple[Dict[str, Any], int]:
    row = dict(REPLICATION_FAILURE_STATE_TABLE.get(row_key, REPLICATION_FAILURE_STATE_TABLE["backing-store-unreadable"]))
    code = int(http_status_override if http_status_override is not None else row["http_status"])
    is_empty = row_key == "empty-but-valid" and code == 200
    payload: Dict[str, Any] = {
        "ok": is_empty, "anvil_v6_enabled": _as.is_anvil_v6_enabled(anchor_root), "status_kind": row["status_kind"],
        "failure_state": row["failure_state"], "http_status": code, "state": row["state"], "badge": row["badge"],
        "display_state": "NO_RECEIPT", "receipt_hmac_verified": False, "unknown_state": bool(row["unknown_state"]),
        "message": row["message"], "surface_state": {**row, "http_status": code},
    }
    if not is_empty:
        payload.update({"error_code": error_code or row["state"], "error": row["message"]})
    if detail:
        payload["detail"] = detail
    if extra:
        payload.update(dict(extra))
    return payload, code


_v4_subpath = _apd.checked_v4_subpath
_snapshot_source_repo_sha256 = _apd.snapshot_source_repo_sha256
_diff_source_snapshots = _apd.diff_source_snapshots
_resolve_contained_paper_file = _apd.resolve_contained_paper_file
_load_paper_sources_dict = _apd.load_paper_sources_dict


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    if _as._is_symlink_or_junction(path) or _as._is_symlink_or_junction(Path(f"{path}.lock")):
        raise PermissionError(f"Symlink or junction refused on {path.name}.")
    _as._atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _read_strict_json(path: Path, expected_schema: str) -> Optional[Dict[str, Any]]:
    if _as._is_symlink_or_junction(path):
        raise ValueError("Symlink or junction store file refused.")
    if not path.exists():
        return None
    if not path.is_file():
        raise OSError(f"{path.name} is not a regular file.")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != expected_schema:
        raise ValueError(f"Corrupt or mismatched schema in {path.name}")
    return doc


def _read_verified_receipt(cdir: Path, rec_path: Path, expected_scope_sha256: str) -> Optional[Dict[str, Any]]:
    doc = _read_strict_json(rec_path, REPLICATION_RECEIPT_FILE_SCHEMA)
    if doc is None:
        return None
    if not _apd.verify_replication_receipt(cdir, doc, ""):
        raise ValueError("Unsigned or forged replication_audit_receipt.json refused.")
    return doc if str(doc.get("scope_sha256") or "").lower() == expected_scope_sha256.lower() else None


def _resolve_locked_scope_context(raw_cdir: Path, analysis_id: Optional[str], anchor_root: Path | str | None) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Dict[str, Any], int]]]:
    if _as._is_symlink_or_junction(raw_cdir):
        return None, _refuse403("PATH_ESCAPE_REFUSED", "Symlink or junction refused on cockpit directory.")
    cdir = raw_cdir.resolve()
    if not _as.is_anvil_v6_enabled(anchor_root):
        return None, _as._build_v6_disabled_refusal()
    v4_mods = _as._load_anvil_v4_modules()
    if _as.anvil_engine is None or not v4_mods or "anvil_replication_audit" not in v4_mods:
        return None, build_replication_failure_response("dependency-missing", anchor_root=anchor_root)
    try:
        resolved_aid, store_root = _as.resolve_store_root(cdir, analysis_id, anchor_root=anchor_root)
    except _as.AnvilAnalysisRefusalError as a_err:
        return None, (a_err.payload, a_err.http_status)
    if not resolved_aid:
        return None, build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="SCOPE_NOT_LOCKED", anchor_root=anchor_root)
    try:
        drift_info = _as.check_locked_scope_drift(cdir, store_root, v4_mods["anvil_v4_process"])
    except _as.AnvilAnalysisRefusalError as d_err:
        return None, (build_replication_failure_response("backing-store-unreadable", detail=str(d_err), anchor_root=anchor_root) if d_err.http_status == 500 else (d_err.payload, d_err.http_status))
    if drift_info is None:
        return None, build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="SCOPE_NOT_LOCKED", anchor_root=anchor_root)
    if drift_info.get("drifted"):
        return None, ({"ok": False, "anvil_v6_enabled": True, "scope_drifted": True, "error_code": "SCOPE_DRIFTED_409", "status_kind": "scope-drifted", "failure_state": "scope-drifted", "http_status": 409, "badge": "409_SCOPE_DRIFTED", "locked_scope_sha256": drift_info.get("locked_scope_sha256", ""), "current_scope_sha256": drift_info.get("current_scope_sha256", ""), "message": _as.ANVIL_SCOPE_DRIFTED_MESSAGE, "error": _as.ANVIL_SCOPE_DRIFTED_MESSAGE}, 409)
    sm_path = store_root / ".anvil" / "scope_manifest.json"
    if _as._is_symlink_or_junction(store_root) or _as._is_symlink_or_junction(store_root / ".anvil") or _as._is_symlink_or_junction(sm_path):
        return None, _refuse403("PATH_ESCAPE_REFUSED", "Symlink or junction refused in scope_manifest path.")
    sm_doc = json.loads(sm_path.read_text(encoding="utf-8"))
    sw_dir, sw_spec = _as._resolve_scoping_v2_local_dir(cdir, sm_doc.get("software_spec") or ".")
    if store_root.resolve() != cdir.resolve() and sw_dir.resolve() != cdir.resolve() and store_root.resolve().is_relative_to(sw_dir.resolve()):
        return None, _refuse403("PATH_ESCAPE_REFUSED", "Analysis store_root cannot reside inside target software repo.")
    paper_spec = str(sm_doc.get("paper_spec") or "")
    paper_p = _as._resolve_scoping_v2_paper_path(cdir, sw_dir, paper_spec)[0] if paper_spec else None
    return {"analysis_id": resolved_aid, "store_root": store_root, "sw_dir": sw_dir, "sw_spec": sw_spec, "paper_path": paper_p, "paper_spec": paper_spec, "scope_sha256": str(sm_doc["scope_sha256"]), "scope_files": list(sm_doc.get("scope_files") or []), "entrypoints": list(sm_doc.get("entrypoints") or []), "manifest": sm_doc.get("manifest") or {}, "v4_mods": v4_mods}, None


def issue_replication_consent(cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    phase = str(body.get("phase") or "A").strip().upper()
    if phase not in {"A", "B"}:
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="INVALID_PHASE", anchor_root=anchor_root)

    cand_id = str(body.get("candidate_id") or "").strip() if phase == "B" else ""
    cand_diff = str(body.get("candidate_diff") or "")
    claimed_sha = str(body.get("diff_sha256") or "").strip().lower()
    diff_sha = ""
    if phase == "B":
        if not cand_id or not _SAFE_ID_RE.fullmatch(cand_id):
            return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="CANDIDATE_ID_REQUIRED_FOR_PHASE_B", anchor_root=anchor_root)
        if cand_diff.strip():
            diff_sha = hashlib.sha256(cand_diff.encode("utf-8")).hexdigest()
            if claimed_sha and claimed_sha != diff_sha:
                return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="DIFF_SHA256_MISMATCH", anchor_root=anchor_root)
        elif _HEX64_RE.fullmatch(claimed_sha):
            diff_sha = claimed_sha
        else:
            return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="DIFF_REQUIRED_FOR_PHASE_B", anchor_root=anchor_root)

    token, now_ts = secrets.token_hex(24), time.time()
    try:
        c_file = _v4_subpath(ctx["store_root"], "replication_consent.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    with _as.exclusive_file_lock(c_file):
        existing = {}
        with contextlib.suppress(Exception):
            if c_file.is_file():
                existing = _read_strict_json(c_file, REPLICATION_CONSENT_SCHEMA) or {}
        raw_map = existing.get("tokens") if isinstance(existing.get("tokens"), Mapping) else {}
        tokens_map: Dict[str, Any] = {}
        for k, v in raw_map.items():
            with contextlib.suppress(TypeError, ValueError):
                if isinstance(v, dict) and float(v.get("expires_at", 0)) > now_ts:
                    tokens_map[str(k)] = v
        tokens_map[token] = {"scope_sha256": ctx["scope_sha256"], "phase": phase, "diff_sha256": diff_sha, "candidate_id": cand_id, "issued_at": now_ts, "expires_at": now_ts + 3600.0}
        _write_json(c_file, {"schema": REPLICATION_CONSENT_SCHEMA, "tokens": tokens_map})
    return ({
        "ok": True, "anvil_v6_enabled": True, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"],
        "phase": phase, "candidate_id": cand_id, "diff_sha256": diff_sha, "consent_token": token,
        "pinned_interpreter": Path(sys.executable).name, "entrypoints": ctx["entrypoints"],
        "table_timeout_sec": 1800, "total_timeout_sec": 5400,
    }, 200)


def _strip_candidate_embedded_receipts(cands: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    if cands is None:
        return None
    allowed_k = {"id", "candidate_id", "table_id", "target_ref", "title", "where", "file", "summary", "wrong", "diff"}
    return [{str(k): v for k, v in item.items() if str(k) in allowed_k} for item in cands if isinstance(item, Mapping)]


def _sanitize_client_claims(claims: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    if claims is None:
        return None
    allowed_k = {"id", "table_id", "artifact_ref", "paper_summary", "caption", "title", "code_ref", "script", "source_file", "metrics", "proposed_rung", "ramanujan_note", "jump_fix_id"}
    return [{str(k): v for k, v in item.items() if str(k) in allowed_k} for item in claims if isinstance(item, Mapping)]


def _write_sf(cdir: Path, sf_file: Path, payload: Mapping[str, Any]) -> None:
    _write_json(sf_file, _apd.sign_gate_artifact(cdir, "repl-sf", payload))


def _write_job(cdir: Path, job_path: Path, payload: Mapping[str, Any]) -> None:
    _write_json(job_path, _apd.sign_gate_artifact(cdir, "repl-job", payload))


def _read_verified_job(cdir: Path, job_path: Path, expected_scope_sha256: str = "") -> Optional[Dict[str, Any]]:
    doc = _read_strict_json(job_path, REPLICATION_JOB_SCHEMA)
    if doc is None:
        return None
    if not _apd.verify_gate_artifact(cdir, "repl-job", doc, expected_scope_sha256=expected_scope_sha256):
        raise ValueError(f"Unsigned or forged {job_path.name} refused.")
    return doc


def _read_verified_sf_job_id(cdir: Path, sf_file: Path, scope_sha256: str) -> str:
    if not sf_file.is_file():
        return ""
    with contextlib.suppress(Exception):
        sf_doc = json.loads(sf_file.read_text(encoding="utf-8"))
        if _apd.verify_gate_artifact(cdir, "repl-sf", sf_doc, expected_scope_sha256=scope_sha256):
            return str(sf_doc.get("job_id") or "")
    return ""


def _is_singleflight_busy(cdir: Path, sf_doc: Any, scope_sha256: str) -> Tuple[bool, str]:
    if not _apd.verify_gate_artifact(cdir, "repl-sf", sf_doc, expected_scope_sha256=scope_sha256):
        return False, ""
    ex_jid = str(sf_doc.get("job_id") or "")
    if not ex_jid or str(sf_doc.get("status") or "") not in {"queued", "installing_deps", "running"}:
        return False, ex_jid
    with _ACTIVE_PROCS_LOCK:
        th_live, in_sync = _LIVE_JOB_THREADS.get(ex_jid), ex_jid in _ACTIVE_SYNC_JOBS
    try:
        dt = time.time() - float(sf_doc.get("heartbeat_ts", 0))
    except (TypeError, ValueError):
        dt = 9999.0
    return ((th_live is not None and th_live.is_alive()) or in_sync or (0.0 <= dt < 120.0 and sf_doc.get("pid") != os.getpid())), ex_jid


def start_replication_job(
    cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None, _trusted_test_seed: bool = False,
) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    for forbidden_k in ("argv", "cmd", "command", "shell", "interpreter", "python_path", "data_roots", "_trusted_test_seed"):
        if forbidden_k in body:
            return _refuse403("EXECUTION_POLICY_REFUSED", f"Client override '{forbidden_k}' is forbidden.")

    raw_tt = body.get("table_timeout_sec", 300.0)
    if isinstance(raw_tt, bool) or not isinstance(raw_tt, (int, float)):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", detail="table_timeout_sec must be numeric.", anchor_root=anchor_root)
    table_timeout = float(raw_tt)
    if not math.isfinite(table_timeout) or table_timeout <= 0.0 or table_timeout > 1800.0:
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="BOUND_EXCEEDED_REFUSAL", detail="table_timeout_sec must be in (0, 1800].", anchor_root=anchor_root)

    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir = raw_cdir.resolve()

    req_sha = str(body.get("scope_sha256") or "").strip().lower()
    raw_token = str(body.get("consent_token") or "").strip().lower()
    if not req_sha or req_sha != ctx["scope_sha256"] or not _TOKEN_HEX_RE.fullmatch(raw_token):
        return _refuse403("CONSENT_REQUIRED_REFUSED", "Valid {scope_sha256, consent_token} required.")

    store_root: Path = ctx["store_root"]
    try:
        sf_file, c_file = _v4_subpath(store_root, "replication_singleflight.json"), _v4_subpath(store_root, "replication_consent.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    raw_token_bytes = raw_token.encode("ascii")

    overrides = (
        (_sanitize_client_claims(body["claims"]) if (_trusted_test_seed is True and isinstance(body.get("claims"), list)) else None),
        _strip_candidate_embedded_receipts(body.get("refactor_candidates") if isinstance(body.get("refactor_candidates"), list) else None),
        (_apd.sign_gate_artifact(cdir, "xval-gate", {**dict(body["xval_receipt"]), "scope_sha256": ctx["scope_sha256"]}) if (_trusted_test_seed is True and isinstance(body.get("xval_receipt"), Mapping)) else None),
        (_apd.sign_gate_artifact(cdir, "ram-gate", {"verdicts": dict(body["ramanujan_verdicts"]), "scope_sha256": ctx["scope_sha256"]}) if (_trusted_test_seed is True and isinstance(body.get("ramanujan_verdicts"), Mapping)) else None),
    )

    with _as.exclusive_file_lock(sf_file):
        if sf_file.is_file():
            try:
                sf_doc = json.loads(sf_file.read_text(encoding="utf-8"))
            except Exception as exc:
                return build_replication_failure_response("backing-store-unreadable", detail=str(exc), anchor_root=anchor_root)
            is_busy, ex_jid = _is_singleflight_busy(cdir, sf_doc, ctx["scope_sha256"])
            if is_busy:
                return ({
                    "ok": False, "anvil_v6_enabled": True, "error_code": "REPLICATION_JOB_ALREADY_RUNNING",
                    "status_kind": "replication-job-running", "failure_state": "replication-job-running", "http_status": 409,
                    "scope_drifted": False, "job_id": ex_jid, "scope_sha256": ctx["scope_sha256"],
                    "message": f"409 Replication Audit job '{ex_jid}' is already running for this scope.", "error": "REPLICATION_JOB_ALREADY_RUNNING",
                }, 409)

        with _as.exclusive_file_lock(c_file):
            try:
                c_doc = _read_strict_json(c_file, REPLICATION_CONSENT_SCHEMA) or {}
            except Exception as exc:
                return build_replication_failure_response("backing-store-unreadable", detail=str(exc), anchor_root=anchor_root)

            tok_entry: Optional[Dict[str, Any]] = None
            rem_tokens: Dict[str, Any] = {}
            now_ts = time.time()
            raw_tok_map = c_doc.get("tokens")
            if not isinstance(raw_tok_map, Mapping) and raw_tok_map is not None:
                return build_replication_failure_response("backing-store-unreadable", detail="Malformed tokens map", anchor_root=anchor_root)
            for k, v in (raw_tok_map or {}).items():
                try:
                    exp_f = float(v.get("expires_at", 0)) if isinstance(v, dict) else 0.0
                except (TypeError, ValueError):
                    continue
                if not isinstance(v, dict) or exp_f < now_ts:
                    continue
                k_str = str(k).strip().lower()
                if _TOKEN_HEX_RE.fullmatch(k_str) and hmac.compare_digest(k_str.encode("ascii"), raw_token_bytes):
                    tok_entry = v
                else:
                    rem_tokens[str(k)] = v

            if not isinstance(tok_entry, dict) or tok_entry.get("scope_sha256") != ctx["scope_sha256"]:
                return _refuse403("CONSENT_REQUIRED_REFUSED", "Invalid, expired, or scope-mismatched consent_token refused.")

            auth_phase = str(tok_entry.get("phase") or "A").strip().upper()
            auth_cand_id = str(tok_entry.get("candidate_id") or "").strip()
            auth_diff_sha = str(tok_entry.get("diff_sha256") or "").strip().lower()

            if body.get("phase") is not None and str(body.get("phase")).strip() != "" and str(body["phase"]).strip().upper() != auth_phase:
                return _refuse403("CONSENT_SCOPE_MISMATCH", f"Request phase disagrees with consented phase '{auth_phase}'.")
            if body.get("candidate_id") is not None and str(body.get("candidate_id")).strip() != auth_cand_id:
                return _refuse403("CONSENT_SCOPE_MISMATCH", "Request candidate_id disagrees with consented token.")
            if body.get("diff_sha256") is not None and str(body.get("diff_sha256")).strip() != "" and str(body["diff_sha256"]).strip().lower() != auth_diff_sha:
                return _refuse403("CONSENT_SCOPE_MISMATCH", "Request diff_sha256 disagrees with consented token.")

            cand_diff = str(body.get("candidate_diff") or "")
            if auth_phase == "B":
                if not auth_cand_id or not _HEX64_RE.fullmatch(auth_diff_sha):
                    return _refuse403("CONSENT_SCOPE_MISMATCH", "Phase B consent token lacks bound candidate_id or 64-hex diff_sha256.")
                if not cand_diff.strip():
                    return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="DIFF_REQUIRED_FOR_PHASE_B", anchor_root=anchor_root)
                if hashlib.sha256(cand_diff.encode("utf-8")).hexdigest() != auth_diff_sha:
                    return _refuse403("CONSENT_SCOPE_MISMATCH", "candidate_diff SHA-256 disagrees with consented diff_sha256.")
            elif cand_diff.strip():
                return _refuse403("CONSENT_SCOPE_MISMATCH", "candidate_diff is forbidden on a Phase A consent token.")
            else:
                cand_diff = ""

            job_id, now_iso = f"repjob-{int(time.time() * 1000)}-{secrets.token_hex(4)}", _now_iso()
            _write_job(cdir, _v4_subpath(store_root, f"replication_jobs/{job_id}.json"), {
                "schema": REPLICATION_JOB_SCHEMA, "job_id": job_id, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"],
                "phase": auth_phase, "candidate_id": auth_cand_id, "diff_sha256": auth_diff_sha, "status": "running", "pid": os.getpid(),
                "created_at": now_iso, "updated_at": now_iso, "completed_steps": 0, "total_steps": max(1, len(ctx["entrypoints"])),
                "step_receipts": {}, "source_repo_diff": [], "error_code": "", "http_status": 200, "message": f"Running Phase {auth_phase} replication in isolated scratch…",
            })
            _write_sf(cdir, sf_file, {"job_id": job_id, "scope_sha256": ctx["scope_sha256"], "status": "running", "pid": os.getpid(), "heartbeat_ts": time.time()})
            _write_json(c_file, {"schema": REPLICATION_CONSENT_SCHEMA, "tokens": rem_tokens})

        cancel_ev, is_sync = threading.Event(), bool(body.get("sync", False))
        worker_fn = lambda: _run_job_worker(cdir, ctx, job_id, auth_phase, auth_cand_id, cand_diff, auth_diff_sha, table_timeout, cancel_ev, overrides)
        th = None if is_sync else threading.Thread(target=worker_fn, name=f"anvil-repl-{job_id}", daemon=True)
        with _ACTIVE_PROCS_LOCK:
            _CANCEL_FLAGS[job_id] = cancel_ev
            if is_sync:
                _ACTIVE_SYNC_JOBS.add(job_id)
            elif th is not None:
                _LIVE_JOB_THREADS[job_id] = th
                th.start()

    if is_sync:
        try:
            worker_fn()
        finally:
            with _ACTIVE_PROCS_LOCK:
                _ACTIVE_SYNC_JOBS.discard(job_id)
        return get_replication_state(cdir, analysis_id=ctx["analysis_id"], job_id=job_id, anchor_root=anchor_root)
    return ({"ok": True, "anvil_v6_enabled": True, "job_id": job_id, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], "phase": auth_phase, "status": "running", "recommended_poll_ms": 1000, "message": f"Started Phase {auth_phase} replication job {job_id}."}, 202)


def _evaluate_table_match_counts(audit_mod: Any, pub_tables: List[Dict[str, Any]], receipts_map: Mapping[str, Any]) -> Tuple[int, int, Dict[str, bool]]:
    total_c = matched_c = 0
    cell_state: Dict[str, bool] = {}
    for tab in pub_tables:
        tid, pub_m = str(tab.get("table_id") or ""), (tab.get("metrics") if isinstance(tab.get("metrics"), Mapping) else {})
        if not pub_m:
            continue
        rec = receipts_map.get(tid)
        if not isinstance(rec, Mapping):
            for mk in pub_m:
                total_c += 1
                cell_state[f"{tid}::{mk}"] = False
            continue
        rep_m = rec.get("metrics") if isinstance(rec.get("metrics"), Mapping) else {}
        if isinstance(rep_m.get(tid), Mapping):
            rep_m = dict(rep_m[tid])
        raw_ec = rec.get("exit_code", 1)
        rec_ec = int(raw_ec) if isinstance(raw_ec, (int, float)) and not isinstance(raw_ec, bool) else 1
        pub_decs = {str(c.get("metric_key")): c.get("decimals") for c in (tab.get("cells") or []) if isinstance(c, Mapping) and c.get("metric_key")}
        cmp_r = audit_mod.compare_metrics(
            pub_m, rep_m, published_decimals=pub_decs, exit_code=rec_ec, missing_dependency=str(rec.get("missing_module") or ""),
            runtime_error=str(rec.get("runtime_error") or ""), used_cached_baseline=bool(rec.get("used_cached_baseline")),
            has_unseeded_rng=bool(rec.get("has_unseeded_rng")), formula_mismatch=bool(rec.get("formula_mismatch")),
        )
        total_c += cmp_r["total_cells"]
        matched_c += cmp_r["matched_cells"]
        for c_item in cmp_r["cells"]:
            cell_state[f"{tid}::{c_item['metric_key']}"] = bool(c_item["matched"])
    return total_c, matched_c, cell_state


def _load_server_gate_artifacts(cdir: Path, store_root: Path, scope_sha256: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    xv_out: Optional[Dict[str, Any]] = None
    with contextlib.suppress(Exception):
        xv_p = _v4_subpath(store_root, "xval_receipt.json")
        if xv_p.is_file():
            xv_doc = json.loads(xv_p.read_text(encoding="utf-8"))
            if _apd.verify_gate_artifact(cdir, "xval-gate", xv_doc, expected_scope_sha256=scope_sha256):
                xv_out = xv_doc
    ram_out: Optional[Dict[str, Any]] = None
    with contextlib.suppress(Exception):
        ram_p = _v4_subpath(store_root, "ramanujan_verdicts.json")
        if ram_p.is_file():
            ram_doc = json.loads(ram_p.read_text(encoding="utf-8"))
            if _apd.verify_gate_artifact(cdir, "ram-gate", ram_doc, expected_scope_sha256=scope_sha256):
                ram_out = ram_doc
    return xv_out, ram_out


def _extract_verified_ram_map(cdir: Path, ram_envelope: Any, scope_sha256: str) -> Dict[str, Any]:
    if not _apd.verify_gate_artifact(cdir, "ram-gate", ram_envelope, expected_scope_sha256=scope_sha256):
        return {}
    verdicts = ram_envelope.get("verdicts") if isinstance(ram_envelope.get("verdicts"), Mapping) else {}
    return {str(k): dict(v) for k, v in verdicts.items() if isinstance(v, Mapping)}


def _run_job_worker(
    cdir: Path, ctx: Dict[str, Any], job_id: str, phase: str, cand_id: str, cand_diff: str, exp_diff_sha: str,
    table_timeout: float, cancel_ev: threading.Event, overrides: Tuple[Any, Any, Any, Any],
    *, initial_pre_snap: Optional[Dict[str, str]] = None,
) -> None:
    store_root, sw_dir, v4_mods = ctx["store_root"], ctx["sw_dir"], ctx["v4_mods"]
    v4_trace, v4_proc, audit_mod = v4_mods["anvil_v4_trace"], v4_mods["anvil_v4_process"], v4_mods["anvil_replication_audit"]
    scrub = lambda s: audit_mod.scrub_host_paths_and_secrets(s, repo_root=str(sw_dir), cockpit_root=str(cdir))

    step_receipts: Dict[str, Dict[str, Any]] = {}
    src_diff: List[str] = []
    final_status, final_http, final_err_code, final_msg = "completed", 200, "", "Replication & Ramanujan Audit completed."
    pre_snap: Optional[Dict[str, str]] = initial_pre_snap
    job_path: Optional[Path] = None
    sf_file: Optional[Path] = None

    def _on_spawn(proc: Any) -> None:
        with _ACTIVE_PROCS_LOCK:
            _ACTIVE_PROCS[job_id] = proc
        if cancel_ev.is_set():
            v4_trace._kill_process_tree(proc)

    try:
        job_path, sf_file = _v4_subpath(store_root, f"replication_jobs/{job_id}.json"), _v4_subpath(store_root, "replication_singleflight.json")
        _apd._ace._cache_hmac_key()
        if pre_snap is None:
            pre_snap = _snapshot_source_repo_sha256(sw_dir)
        pre_store_snap = _apd.snapshot_protected_anvil_stores(store_root, job_id, cdir=cdir)
        job_start = time.monotonic()
        manifest = ctx["manifest"]
        data_roots_set = sorted({str(d.get("root") or "") for d in (manifest.get("allowlisted_data_files") or []) if d.get("root")})
        eps = [str(e).split(":", 1)[0] for e in (ctx["entrypoints"] or []) if str(e).strip()]
        if not eps:
            py_scoped = [f for f in ctx["scope_files"] if str(f).endswith(".py") and Path(f).stem.startswith(("run_", "replicate", "table", "eval", "step", "main"))]
            eps = py_scoped[:8] or [f for f in ctx["scope_files"] if str(f).endswith(".py")][:1]

        scope_info = v4_proc.discover_paper_matched_scopes(sw_dir, ctx["paper_path"], allowed_root=cdir)
        ep_to_targets: Dict[str, List[str]] = {}
        for ws in scope_info.get("workflow_steps") or []:
            if ws.get("entrypoint"):
                ep_to_targets.setdefault(str(ws["entrypoint"]), []).extend(str(t) for t in (ws.get("manuscript_targets") or []))

        verified_extra_sps = _apd.read_verified_extra_site_packages(cdir, store_root)
        for idx, ep_rel in enumerate(eps, start=1):
            rem_total = v4_trace.MAX_REPLICATION_TOTAL_TIMEOUT_SEC - (time.monotonic() - job_start)
            if cancel_ev.is_set() or rem_total <= 0:
                final_status = "cancelled" if cancel_ev.is_set() else "failed"
                final_http, final_err_code = 504, ("REPLICATION_CANCELLED" if cancel_ev.is_set() else "REPLICATION_TOTAL_TIMEOUT")
                final_msg = REPLICATION_FAILURE_STATE_TABLE["dependency-slow-or-killed"]["message"]
                break
            raw_rec = v4_trace.run_replication_table_in_scratch(
                sw_dir, ["python", ep_rel], approve_run=True, timeout_sec=table_timeout, remaining_total_sec=rem_total,
                allowlisted_data_roots=data_roots_set, cockpit_root=cdir, verified_extra_site_packages=verified_extra_sps,
                candidate_diff=cand_diff if phase == "B" else "", candidate_diff_sha256=exp_diff_sha if phase == "B" else "",
                scope_sha256=ctx["scope_sha256"], on_proc_spawn=_on_spawn,
            )
            rec = dict(raw_rec)
            rec["pinned_interpreter"] = Path(sys.executable).name
            for k_sc in ("stdout_preview", "stderr_preview", "output_summary", "runtime_error"):
                if k_sc in rec and rec[k_sc] is not None:
                    rec[k_sc] = scrub(rec[k_sc])
            step_receipts[ep_rel] = rec
            for tgt in ep_to_targets.get(ep_rel, []):
                step_receipts.setdefault(tgt, rec)
            if isinstance(rec.get("metrics"), Mapping):
                for mk_k, mk_v in rec["metrics"].items():
                    if str(mk_k).startswith("tab:") and isinstance(mk_v, Mapping):
                        step_receipts.setdefault(str(mk_k), {**rec, "metrics": dict(mk_v)})
            if rec.get("missing_module"):
                final_status, final_http, final_err_code = "completed_with_missing_dep", 503, "PIPELINE_DEPENDENCY_MISSING"
                final_msg = scrub(f"PIPELINE_DEPENDENCY_MISSING: Missing package '{rec['missing_module']}'")

            with _as.exclusive_file_lock(sf_file):
                if _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"]) == job_id:
                    cur_sf = json.loads(sf_file.read_text(encoding="utf-8"))
                    if cur_sf.get("status") == "running":
                        _write_sf(cdir, sf_file, {**cur_sf, "heartbeat_ts": time.time()})
                with _as.exclusive_file_lock(job_path):
                    cur_j = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) or {}
                    if cur_j.get("status") == "running":
                        cur_j.update({"completed_steps": idx, "total_steps": len(eps), "step_receipts": step_receipts, "updated_at": _now_iso()})
                        _write_job(cdir, job_path, cur_j)

        if cancel_ev.is_set() and final_status != "cancelled":
            final_status, final_http, final_err_code = "cancelled", 504, "REPLICATION_CANCELLED"
            final_msg = REPLICATION_FAILURE_STATE_TABLE["dependency-slow-or-killed"]["message"]

        if pre_snap is not None:
            src_diff = _diff_source_snapshots(pre_snap, _snapshot_source_repo_sha256(sw_dir))
            if src_diff:
                final_status, final_http, final_err_code, final_msg = "failed", 500, "SOURCE_REPO_MUTATED_VIOLATION", scrub(f"Unexpected source-tree modification: {src_diff[:3]}")
        store_tamper = _diff_source_snapshots(pre_store_snap, _apd.snapshot_protected_anvil_stores(store_root, job_id, cdir=cdir))
        if store_tamper and not src_diff:
            src_diff = store_tamper
            final_status, final_http, final_err_code, final_msg = "failed", 500, "ANVIL_STORE_TAMPERED_VIOLATION", scrub(f"Unexpected Anvil store modification during scratch run: {store_tamper[:3]}")

        if final_status in {"completed", "completed_with_missing_dep"} and not src_diff and not cancel_ev.is_set():
            claims_ov, cands_ov, xval_ov, ram_ov = overrides
            paper_title, paper_sources = _load_paper_sources_dict(sw_dir, cdir, ctx["paper_path"], manifest)
            pub_tables = audit_mod.parse_published_tables(paper_sources)
            srv_xv, srv_ram_env = _load_server_gate_artifacts(cdir, store_root, ctx["scope_sha256"])

            rec_path = _v4_subpath(store_root, "replication_audit_receipt.json")
            with _as.exclusive_file_lock(rec_path):
                prev_rec: Dict[str, Any] = {}
                with contextlib.suppress(Exception):
                    if rec_path.is_file():
                        prev_rec = _read_verified_receipt(cdir, rec_path, ctx["scope_sha256"]) or {}
                if prev_rec.get("scope_sha256") != ctx["scope_sha256"]:
                    prev_rec = {}
                phase_a_map, phase_b_map = dict(prev_rec.get("phase_a_receipts") or {}), dict(prev_rec.get("phase_b_receipts") or {})
                st_claims = claims_ov if claims_ov is not None else list(prev_rec.get("claims") or [])
                st_cands = cands_ov if cands_ov is not None else list(prev_rec.get("refactor_candidates") or [])
                prev_xv = prev_rec.get("xval_receipt") if _apd.verify_gate_artifact(cdir, "xval-gate", prev_rec.get("xval_receipt"), ctx["scope_sha256"]) else None
                prev_ram_env = prev_rec.get("ramanujan_verdicts_signed") if _apd.verify_gate_artifact(cdir, "ram-gate", prev_rec.get("ramanujan_verdicts_signed"), ctx["scope_sha256"]) else None
                st_xval = xval_ov if xval_ov is not None else (prev_xv or srv_xv)
                st_ram_env = ram_ov if ram_ov is not None else (prev_ram_env or srv_ram_env)
                st_ram_map = _extract_verified_ram_map(cdir, st_ram_env, ctx["scope_sha256"])

                if phase == "A":
                    phase_a_map.update(step_receipts)
                elif phase == "B" and cand_id:
                    all_ok = bool(step_receipts) and all(int(r.get("exit_code", 1)) == 0 for r in step_receipts.values())
                    patched_any = any(bool(r.get("patched_files")) for r in step_receipts.values())
                    lead_r = next(iter(step_receipts.values()), {})
                    _, pa_matched, pa_cells = _evaluate_table_match_counts(audit_mod, pub_tables, phase_a_map)
                    pb_total, pb_matched, pb_cells = _evaluate_table_match_counts(audit_mod, pub_tables, step_receipts)
                    regressed_cells = sum(1 for ck, was_ok in pa_cells.items() if was_ok and not pb_cells.get(ck, False))
                    metrics_ok = all_ok and patched_any and pb_total > 0 and bool(phase_a_map) and pb_matched > 0 and pb_matched >= pa_matched and regressed_cells == 0 and not bool(lead_r.get("metric_degraded"))
                    phase_b_map[cand_id] = {
                        "scope_sha256": ctx["scope_sha256"], "candidate_id": cand_id, "diff_sha256": exp_diff_sha,
                        "exit_code": 0 if all_ok else int(lead_r.get("exit_code", 1)),
                        "patched_files_count": sum(len(r.get("patched_files") or []) for r in step_receipts.values()),
                        "matched_cells": pb_matched, "baseline_matched_cells": pa_matched,
                        "metric_improved_or_preserved": metrics_ok, "table_replay_passed": metrics_ok,
                        "regressions": regressed_cells + (0 if metrics_ok else 1), "step_receipts": step_receipts,
                    }

                report_bundle = audit_mod.build_replication_report_bundle(
                    scope_sha256=ctx["scope_sha256"], repo_name=sw_dir.name, paper_title=paper_title, published_tables=pub_tables,
                    phase_a_receipts=phase_a_map, claims=st_claims or None, refactor_candidates=st_cands or None,
                    xval_receipt=st_xval, ramanujan_verdicts=st_ram_map, phase_b_receipts=phase_b_map, repo_root=str(sw_dir), cockpit_root=str(cdir),
                    require_diff_bound_legs=True, trusted_claims_baseline=bool(st_claims),
                )
                if not cancel_ev.is_set():
                    with _as.exclusive_file_lock(job_path):
                        j_chk = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) if job_path.is_file() else None
                    if not (isinstance(j_chk, dict) and j_chk.get("status") == "cancelled"):
                        _write_json(rec_path, _apd.sign_replication_receipt(cdir, {
                            "schema": REPLICATION_RECEIPT_FILE_SCHEMA, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"],
                            "last_job_id": job_id, "updated_at": _now_iso(), "source_repo_diff": src_diff, "phase_a_receipts": phase_a_map,
                            "phase_b_receipts": phase_b_map, "claims": st_claims, "refactor_candidates": st_cands, "xval_receipt": st_xval,
                            "ramanujan_verdicts_signed": st_ram_env, "ramanujan_verdicts": st_ram_map, "report": report_bundle,
                        }))

            if not cancel_ev.is_set():
                idx_file = _as._analyses_index_file(cdir)
                if idx_file.is_file() and not _as._is_symlink_or_junction(idx_file):
                    with _as.exclusive_file_lock(idx_file):
                        idx_doc = _as._read_analyses_index(cdir)
                        if isinstance(idx_doc, dict):
                            for ent in idx_doc.get("analyses") or []:
                                if isinstance(ent, dict) and str(ent.get("analysis_id") or "") == ctx["analysis_id"]:
                                    ent["has_replication_report"] = True
                            _as._write_analyses_index(cdir, idx_doc)
    except PermissionError as p_exc:
        final_status, final_http, final_err_code, final_msg = "failed", 403, "PATH_ESCAPE_REFUSED", scrub(str(p_exc))
    except Exception as exc:
        ec = getattr(exc, "error_code", "")
        final_status = "failed"
        if ec == "REPLICATION_TIMEOUT_REFUSED" or isinstance(exc, TimeoutError):
            final_http, final_err_code, final_msg = 504, "REPLICATION_TIMEOUT_REFUSED", REPLICATION_FAILURE_STATE_TABLE["dependency-slow-or-killed"]["message"]
        elif ec in {"EXECUTION_POLICY_REFUSED", "PATH_ESCAPE_REFUSED"}:
            final_http, final_err_code, final_msg = 403, ec, scrub(str(exc))
        elif isinstance(exc, ValueError) and "BOUND_EXCEEDED_REFUSAL" in str(exc):
            final_http, final_err_code, final_msg = 413, "BOUND_EXCEEDED_REFUSAL", scrub(str(exc))
        else:
            final_http = 400 if ec in {"MALFORMED_DATA_REFUSED", "BOUND_EXCEEDED_REFUSAL"} else 502
            final_err_code, final_msg = ec or "INVALID_RECEIPT_OUTPUT", REPLICATION_FAILURE_STATE_TABLE["dependency-returns-garbage"]["message"]
    finally:
        with _ACTIVE_PROCS_LOCK:
            _ACTIVE_PROCS.pop(job_id, None)
        if cancel_ev.is_set():
            final_status, final_http, final_err_code = "cancelled", 504, "REPLICATION_CANCELLED"
            final_msg = REPLICATION_FAILURE_STATE_TABLE["dependency-slow-or-killed"]["message"]
        if sf_file is not None and job_path is not None:
            with contextlib.suppress(Exception):
                with _as.exclusive_file_lock(sf_file):
                    with _as.exclusive_file_lock(job_path):
                        fin_j = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) if job_path.is_file() else None
                        if isinstance(fin_j, dict) and fin_j.get("status") not in {"completed", "completed_with_missing_dep", "failed", "cancelled"}:
                            fin_j.update({"status": final_status, "http_status": final_http, "error_code": final_err_code, "message": scrub(final_msg), "source_repo_diff": src_diff, "step_receipts": step_receipts, "updated_at": _now_iso()})
                            _write_job(cdir, job_path, fin_j)
                        elif isinstance(fin_j, dict) and fin_j.get("status") == "cancelled":
                            final_status = "cancelled"
                    if _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"]) == job_id:
                        _write_sf(cdir, sf_file, {"job_id": job_id, "scope_sha256": ctx["scope_sha256"], "status": final_status, "pid": os.getpid(), "heartbeat_ts": time.time()})
        with _ACTIVE_PROCS_LOCK:
            _CANCEL_FLAGS.pop(job_id, None)
            _LIVE_JOB_THREADS.pop(job_id, None)


def cancel_replication_job(cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir, store_root = raw_cdir.resolve(), ctx["store_root"]
    try:
        sf_file = _v4_subpath(store_root, "replication_singleflight.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    target_jid = str(body.get("job_id") or "").strip() or _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"])
    if not target_jid or not re.fullmatch(r"[a-zA-Z0-9_-]{4,80}", target_jid):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="UNKNOWN_JOB_ID", anchor_root=anchor_root)
    try:
        job_path = _v4_subpath(store_root, f"replication_jobs/{target_jid}.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    if not job_path.is_file():
        with _as.exclusive_file_lock(sf_file):
            if _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"]) == target_jid:
                _write_sf(cdir, sf_file, {"job_id": target_jid, "scope_sha256": ctx["scope_sha256"], "status": "cancelled", "pid": os.getpid(), "heartbeat_ts": time.time()})
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=404, error_code="JOB_NOT_FOUND", anchor_root=anchor_root)

    with _ACTIVE_PROCS_LOCK:
        if target_jid in _CANCEL_FLAGS:
            _CANCEL_FLAGS[target_jid].set()
        proc = _ACTIVE_PROCS.get(target_jid)
    if proc is not None:
        ctx["v4_mods"]["anvil_v4_trace"]._kill_process_tree(proc)

    with _as.exclusive_file_lock(sf_file):
        with _as.exclusive_file_lock(job_path):
            try:
                jdoc = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) or {}
            except Exception as exc:
                return build_replication_failure_response("backing-store-unreadable", detail=str(exc), anchor_root=anchor_root)
            cur_st = str(jdoc.get("status") or "")
            if cur_st in {"completed", "completed_with_missing_dep", "failed"}:
                return ({"ok": False, "anvil_v6_enabled": True, "error_code": "JOB_ALREADY_TERMINAL", "http_status": 409, "job_id": target_jid, "status": cur_st, "message": f"Job '{target_jid}' already finished with status '{cur_st}'.", "error": "JOB_ALREADY_TERMINAL"}, 409)
            if cur_st != "cancelled":
                jdoc.update({"status": "cancelled", "http_status": 504, "error_code": "REPLICATION_CANCELLED", "message": REPLICATION_FAILURE_STATE_TABLE["dependency-slow-or-killed"]["message"], "updated_at": _now_iso()})
                _write_job(cdir, job_path, jdoc)
        if _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"]) == target_jid:
            _write_sf(cdir, sf_file, {"job_id": target_jid, "scope_sha256": ctx["scope_sha256"], "status": "cancelled", "pid": os.getpid(), "heartbeat_ts": time.time()})

    return build_replication_failure_response("dependency-slow-or-killed", error_code="REPLICATION_CANCELLED", extra={"job_id": target_jid, "cancelled": True, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"]}, anchor_root=anchor_root)


def get_replication_state(cockpit_dir: str | Path, *, analysis_id: Optional[str] = None, job_id: Optional[str] = None, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, analysis_id, anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir, store_root, sw_dir, audit_mod = raw_cdir.resolve(), ctx["store_root"], ctx["sw_dir"], ctx["v4_mods"]["anvil_replication_audit"]
    scrub = lambda s: audit_mod.scrub_host_paths_and_secrets(s, repo_root=str(sw_dir), cockpit_root=str(cdir))
    job_doc: Optional[Dict[str, Any]] = None
    eff_jid = str(job_id or "").strip()
    try:
        if not eff_jid:
            eff_jid = _read_verified_sf_job_id(cdir, _v4_subpath(store_root, "replication_singleflight.json"), ctx["scope_sha256"])
        if eff_jid:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{4,80}", eff_jid):
                return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
            jp = _v4_subpath(store_root, f"replication_jobs/{eff_jid}.json")
            if jp.exists():
                job_doc = _read_verified_job(cdir, jp, ctx["scope_sha256"])
        rec_path = _v4_subpath(store_root, "replication_audit_receipt.json")
        saved_rec = _read_verified_receipt(cdir, rec_path, ctx["scope_sha256"]) if rec_path.exists() else None
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", scrub(str(pe)))
    except Exception as exc:
        return build_replication_failure_response("backing-store-unreadable", detail=scrub(str(exc)), anchor_root=anchor_root)

    if job_doc and (job_doc.get("status") in {"cancelled", "failed"} or (saved_rec is None and int(job_doc.get("http_status") or 200) == 503)):
        j_http = int(job_doc.get("http_status") or 502)
        rk = "dependency-slow-or-killed" if j_http == 504 else ("dependency-missing" if j_http == 503 else ("backing-store-unreadable" if j_http == 500 else "dependency-returns-garbage"))
        dep_extra: Dict[str, Any] = {}
        if j_http == 503:
            rt_mods = [str(r.get("missing_module") or "") for r in ((job_doc.get("step_receipts") or {}).values()) if isinstance(r, Mapping) and r.get("missing_module")]
            miss_pkgs = _apd.discover_missing_scope_packages(sw_dir, cdir, store_root, ctx["scope_files"], rt_mods)
            if miss_pkgs:
                dep_extra = {"missing_packages": miss_pkgs, "dep_install_token": _apd.issue_one_click_dep_token(cdir, ctx["scope_sha256"], miss_pkgs, f"replication:{job_doc.get('phase') or 'A'}")}
        stale_extra = {"stale_report": saved_rec["report"]} if (saved_rec and isinstance(saved_rec.get("report"), dict)) else {}
        return build_replication_failure_response(rk, http_status_override=j_http, error_code=str(job_doc.get("error_code") or ""), detail=scrub(str(job_doc.get("message") or "")), extra={"job": job_doc, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], **stale_extra, **dep_extra}, anchor_root=anchor_root)

    sem_extra: Dict[str, Any] = {}
    if os.path.isdir(os.path.join(str(cdir), ".anvil", "comprehension", ctx["scope_sha256"])):
        with contextlib.suppress(Exception):
            from steward_cockpit import anvil_comprehension_engine as _ace
            sem_st_r, _ = _ace.get_comprehension_state(cdir, scope_sha256=ctx["scope_sha256"], analysis_id=ctx["analysis_id"])
            sem_extra["semantic_comprehension"] = sem_st_r

    is_active_job = bool(job_doc and job_doc.get("status") in {"installing_deps", "running"})
    if saved_rec and saved_rec.get("scope_sha256") == ctx["scope_sha256"] and isinstance(saved_rec.get("report"), dict):
        queued_ids: List[str] = []
        with contextlib.suppress(Exception):
            queued_file = _v4_subpath(store_root, "queued_refactorings.json")
            if queued_file.is_file():
                qdoc = _read_strict_json(queued_file, REPLICATION_QUEUED_REFACTOR_SCHEMA) or {}
                if _apd.verify_gate_artifact(cdir, "refactor-queue", qdoc, expected_scope_sha256=ctx["scope_sha256"]):
                    queued_ids = [str(x.get("candidate_id") or "") for x in (qdoc.get("items") or []) if isinstance(x, dict)]
        if job_doc and int(job_doc.get("http_status") or 200) == 503:
            rt_mods = [str(r.get("missing_module") or "") for r in ((job_doc.get("step_receipts") or {}).values()) if isinstance(r, Mapping) and r.get("missing_module")]
            miss_pkgs = _apd.discover_missing_scope_packages(sw_dir, cdir, store_root, ctx["scope_files"], rt_mods)
            dep_extra_s = {"missing_packages": miss_pkgs, "dep_install_token": _apd.issue_one_click_dep_token(cdir, ctx["scope_sha256"], miss_pkgs, f"replication:{job_doc.get('phase') or 'A'}")} if miss_pkgs else {}
            return build_replication_failure_response("dependency-missing", error_code="PIPELINE_DEPENDENCY_MISSING", extra={"analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], "job": job_doc, "report": saved_rec["report"], "queued_refactoring_ids": queued_ids, **dep_extra_s, **sem_extra}, anchor_root=anchor_root)
        return ({
            "ok": True, "anvil_v6_enabled": True, "status_kind": "healthy", "failure_state": "healthy", "http_status": 200,
            "state": "RUNNING" if is_active_job else "READY", "badge": "REPLICATION_RUNNING" if is_active_job else "REPLICATION_VERIFIED",
            "display_state": "NO_RECEIPT" if is_active_job else "VERIFIED_NUMERIC", "receipt_hmac_verified": not is_active_job,
            "unknown_state": False, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], "job": job_doc,
            "recommended_poll_ms": 1000 if is_active_job else 10000, "source_repo_diff": saved_rec.get("source_repo_diff", []),
            "queued_refactoring_ids": queued_ids, "report": saved_rec["report"], **sem_extra,
        }, 200)

    try:
        paper_title, paper_sources = _load_paper_sources_dict(sw_dir, cdir, ctx["paper_path"], ctx["manifest"])
    except PermissionError as p_exc:
        return _refuse403("PATH_ESCAPE_REFUSED", scrub(str(p_exc)))
    except ValueError as v_exc:
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=413, error_code="BOUND_EXCEEDED_REFUSAL", detail=scrub(str(v_exc)), anchor_root=anchor_root)

    not_run_report = audit_mod.build_replication_report_bundle(scope_sha256=ctx["scope_sha256"], repo_name=sw_dir.name, paper_title=paper_title, published_tables=audit_mod.parse_published_tables(paper_sources), phase_a_receipts={}, repo_root=str(sw_dir), cockpit_root=str(cdir))
    return build_replication_failure_response("empty-but-valid", extra={"analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], "job": job_doc, "recommended_poll_ms": 1000 if is_active_job else 12000, "queued_refactoring_ids": [], "report": not_run_report, **sem_extra}, anchor_root=anchor_root)


def approve_install_and_run_replication(cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    for forbidden_k in ("argv", "cmd", "command", "shell", "interpreter", "python_path", "data_roots"):
        if forbidden_k in body:
            return _refuse403("EXECUTION_POLICY_REFUSED", f"Client override '{forbidden_k}' is forbidden.")
    raw_tt = body.get("table_timeout_sec", 300.0)
    table_timeout = float(raw_tt) if isinstance(raw_tt, (int, float)) and not isinstance(raw_tt, bool) and 0.0 < float(raw_tt) <= 1800.0 else 300.0

    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir = raw_cdir.resolve()
    store_root: Path = ctx["store_root"]

    parsed_tok, tok_err = _apd.validate_dep_token_without_consuming(
        cdir, str(body.get("dep_install_token") or ""),
        expected_scope_sha256=ctx["scope_sha256"], requested_packages=body.get("packages") or [], expected_context_prefix="replication:",
    )
    if tok_err or parsed_tok is None:
        return _refuse403("CONSENT_REQUIRED_REFUSED", tok_err or "Valid dep_install_token required.")
    approved_pkgs: List[str] = list(parsed_tok["packages"])

    try:
        sf_file = _v4_subpath(store_root, "replication_singleflight.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))

    with _as.exclusive_file_lock(sf_file):
        if sf_file.is_file():
            try:
                is_busy, ex_jid = _is_singleflight_busy(cdir, json.loads(sf_file.read_text(encoding="utf-8")), ctx["scope_sha256"])
            except Exception as exc:
                return build_replication_failure_response("backing-store-unreadable", detail=str(exc), anchor_root=anchor_root)
            if is_busy:
                return ({"ok": False, "anvil_v6_enabled": True, "error_code": "REPLICATION_JOB_ALREADY_RUNNING", "status_kind": "replication-job-running", "http_status": 409, "job_id": ex_jid, "message": f"409 Replication Audit job '{ex_jid}' is already running."}, 409)

        try:
            nonce_err = _apd.consume_dep_token_nonce(store_root, str(parsed_tok["nonce"]))
        except PermissionError as pe:
            return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
        except Exception as exc:
            return build_replication_failure_response("backing-store-unreadable", detail=str(exc), anchor_root=anchor_root)
        if nonce_err:
            return _refuse403("CONSENT_REQUIRED_REFUSED", nonce_err)

        job_id, now_iso = f"repjob-{int(time.time() * 1000)}-{secrets.token_hex(4)}", _now_iso()
        job_path = _v4_subpath(store_root, f"replication_jobs/{job_id}.json")
        _write_job(cdir, job_path, {
            "schema": REPLICATION_JOB_SCHEMA, "job_id": job_id, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"],
            "phase": "A", "candidate_id": "", "diff_sha256": "", "status": "installing_deps", "installing_packages": approved_pkgs, "pid": os.getpid(),
            "created_at": now_iso, "updated_at": now_iso, "completed_steps": 0, "total_steps": max(1, len(ctx["entrypoints"])),
            "step_receipts": {}, "source_repo_diff": [], "error_code": "", "http_status": 200, "message": f"Installing approved Python packages ({', '.join(approved_pkgs)}) in isolated Anvil runtime…",
        })
        _write_sf(cdir, sf_file, {"job_id": job_id, "scope_sha256": ctx["scope_sha256"], "status": "installing_deps", "pid": os.getpid(), "heartbeat_ts": time.time()})
        cancel_ev, is_sync = threading.Event(), (bool(body.get("sync", False)) and _apd._in_pytest_runtime())

        def _hb() -> None:
            with _as.exclusive_file_lock(sf_file):
                if _read_verified_sf_job_id(cdir, sf_file, ctx["scope_sha256"]) == job_id:
                    cur_d = json.loads(sf_file.read_text(encoding="utf-8"))
                    _write_sf(cdir, sf_file, {**cur_d, "heartbeat_ts": time.time()})

        def _install_then_run() -> None:
            scrub = lambda s: ctx["v4_mods"]["anvil_replication_audit"].scrub_host_paths_and_secrets(s, repo_root=str(ctx["sw_dir"]), cockpit_root=str(cdir))
            pre_install_snap: Optional[Dict[str, str]] = None
            proceed_to_run = False
            try:
                pre_install_snap = _snapshot_source_repo_sha256(ctx["sw_dir"])
                _apd.install_approved_packages(raw_cdir, store_root, approved_pkgs, cancel_ev=cancel_ev, heartbeat_cb=_hb)
                with _as.exclusive_file_lock(sf_file):
                    with _as.exclusive_file_lock(job_path):
                        cur_j = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) or {}
                        if cur_j.get("status") == "cancelled" or cancel_ev.is_set():
                            return
                        cur_j.update({"status": "running", "message": "Running Phase A replication in isolated scratch…", "updated_at": _now_iso()})
                        _write_job(cdir, job_path, cur_j)
                    _write_sf(cdir, sf_file, {"job_id": job_id, "scope_sha256": ctx["scope_sha256"], "status": "running", "pid": os.getpid(), "heartbeat_ts": time.time()})
                proceed_to_run = True
            except Exception as inst_exc:
                is_to = isinstance(inst_exc, TimeoutError)
                st_end = "cancelled" if str(inst_exc) == "REPLICATION_CANCELLED" else "failed"
                hc, ec = (504 if is_to else 503), ("REPLICATION_CANCELLED" if st_end == "cancelled" else ("PIP_INSTALL_TIMEOUT" if is_to else "PIPELINE_DEPENDENCY_MISSING"))
                with contextlib.suppress(Exception):
                    with _as.exclusive_file_lock(sf_file):
                        with _as.exclusive_file_lock(job_path):
                            cur_j = _read_verified_job(cdir, job_path, ctx["scope_sha256"]) or {}
                            cur_j.update({"status": st_end, "http_status": hc, "error_code": ec, "message": scrub(str(inst_exc)), "updated_at": _now_iso()})
                            _write_job(cdir, job_path, cur_j)
                        _write_sf(cdir, sf_file, {"job_id": job_id, "scope_sha256": ctx["scope_sha256"], "status": st_end, "pid": os.getpid(), "heartbeat_ts": time.time()})
            finally:
                if not proceed_to_run:
                    with _ACTIVE_PROCS_LOCK:
                        _CANCEL_FLAGS.pop(job_id, None)
                        _LIVE_JOB_THREADS.pop(job_id, None)
            if proceed_to_run:
                _run_job_worker(cdir, ctx, job_id, "A", "", "", "", table_timeout, cancel_ev, (None, None, None, None), initial_pre_snap=pre_install_snap)

        th = None if is_sync else threading.Thread(target=_install_then_run, name=f"anvil-dep-repl-{job_id}", daemon=True)
        with _ACTIVE_PROCS_LOCK:
            _CANCEL_FLAGS[job_id] = cancel_ev
            if is_sync:
                _ACTIVE_SYNC_JOBS.add(job_id)
            elif th is not None:
                _LIVE_JOB_THREADS[job_id] = th
                th.start()

    if is_sync:
        try:
            _install_then_run()
        finally:
            with _ACTIVE_PROCS_LOCK:
                _ACTIVE_SYNC_JOBS.discard(job_id)
        return get_replication_state(cdir, analysis_id=ctx["analysis_id"], job_id=job_id, anchor_root=anchor_root)
    return ({"ok": True, "anvil_v6_enabled": True, "job_id": job_id, "analysis_id": ctx["analysis_id"], "scope_sha256": ctx["scope_sha256"], "installing_packages": approved_pkgs, "status": "installing_deps", "recommended_poll_ms": 1000, "message": f"Installing {', '.join(approved_pkgs)} and resuming replication job {job_id}."}, 202)


def queue_vetted_refactoring(cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    raw_cdir = Path(cockpit_dir)
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir = raw_cdir.resolve()
    if body.get("operator_consent") is not True:
        return _refuse403("CONSENT_REQUIRED_REFUSED", "Explicit operator_consent: true required.")
    raw_cand_id = str(body.get("candidate_id") or "").strip()
    norm_cand_id = re.sub(r"[^a-z0-9_-]+", "-", raw_cand_id.lower()).strip("-")
    try:
        rec_path = _v4_subpath(ctx["store_root"], "replication_audit_receipt.json")
        q_path = _v4_subpath(ctx["store_root"], "queued_refactorings.json")
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    if not rec_path.is_file():
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="REPLICATION_NOT_RUN", anchor_root=anchor_root)
    try:
        saved_rec = _read_verified_receipt(cdir, rec_path, ctx["scope_sha256"]) or {}
    except Exception:
        return _refuse403("UNAPPROVED_REFACTORING_REFUSED", "Unsigned or tampered replication receipt refused.")
    if saved_rec.get("scope_sha256") != ctx["scope_sha256"]:
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, error_code="REPLICATION_NOT_RUN", anchor_root=anchor_root)

    matched = next((fx for fx in (((saved_rec.get("report") or {}).get("approved_fixes")) or []) if str(fx.get("id") or "") in {raw_cand_id, norm_cand_id}), None)
    cand_id = str(matched.get("id") or norm_cand_id or raw_cand_id) if matched else raw_cand_id
    cand_dsha = str((matched or {}).get("diff_sha256") or "").strip().lower()
    pb_rec = (saved_rec.get("phase_b_receipts") or {}).get(cand_id) or (saved_rec.get("phase_b_receipts") or {}).get(raw_cand_id)
    xv_doc = saved_rec.get("xval_receipt")
    xv_ok = _apd.verify_gate_artifact(cdir, "xval-gate", xv_doc, expected_scope_sha256=ctx["scope_sha256"])
    xv_cmap = xv_doc.get("candidate_diff_sha256") if isinstance(xv_doc, Mapping) and isinstance(xv_doc.get("candidate_diff_sha256"), Mapping) else {}
    xv_dsha = str(xv_cmap.get(cand_id) or xv_cmap.get(raw_cand_id) or (xv_doc.get("diff_sha256") if isinstance(xv_doc, Mapping) else "") or "").strip().lower()
    ram_map = _extract_verified_ram_map(cdir, saved_rec.get("ramanujan_verdicts_signed"), ctx["scope_sha256"])
    ram_entry = ram_map.get(cand_id) or ram_map.get(raw_cand_id)
    ram_ok = isinstance(ram_entry, Mapping) and bool(cand_dsha) and str(ram_entry.get("diff_sha256") or "").strip().lower() == cand_dsha
    pb_ok = isinstance(pb_rec, Mapping) and pb_rec.get("table_replay_passed") is True and bool(cand_dsha) and str(pb_rec.get("diff_sha256") or "").strip().lower() == cand_dsha
    if matched is None or not (xv_ok and xv_dsha == cand_dsha and ram_ok and pb_ok):
        return _refuse403("UNAPPROVED_REFACTORING_REFUSED", f"Candidate '{cand_id}' has not passed all 3 diff-bound signed verification legs.")
    with _as.exclusive_file_lock(q_path):
        qdoc: Dict[str, Any] = {}
        with contextlib.suppress(Exception):
            if q_path.is_file():
                cand_q = _read_strict_json(q_path, REPLICATION_QUEUED_REFACTOR_SCHEMA) or {}
                if _apd.verify_gate_artifact(cdir, "refactor-queue", cand_q, expected_scope_sha256=ctx["scope_sha256"]):
                    qdoc = cand_q
        items = [x for x in (qdoc.get("items") or []) if isinstance(x, dict) and x.get("candidate_id") != cand_id]
        entry = {"candidate_id": cand_id, "scope_sha256": ctx["scope_sha256"], "title": matched["title"], "where": matched["where"], "diff_sha256": matched.get("diff_sha256", ""), "operator_note": str(body.get("operator_note") or "").strip()[:1024], "queued_at": _now_iso()}
        items.append(entry)
        _write_json(q_path, _apd.sign_gate_artifact(cdir, "refactor-queue", {"schema": REPLICATION_QUEUED_REFACTOR_SCHEMA, "scope_sha256": ctx["scope_sha256"], "items": items}))
    return ({"ok": True, "queued": entry, "queued_refactoring_ids": [str(x["candidate_id"]) for x in items], "message": f"Queued approved surgical refactoring '{matched['title']}' (0 source files edited)."}, 200)


def export_replication_deliverables(cockpit_dir: str | Path, body: Mapping[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not isinstance(body, Mapping):
        return build_replication_failure_response("dependency-returns-garbage", http_status_override=400, anchor_root=anchor_root)
    raw_cdir = Path(cockpit_dir)
    state_d, code = get_replication_state(raw_cdir, analysis_id=body.get("analysis_id"), anchor_root=anchor_root)
    if code != 200 and "report" not in state_d:
        return state_d, code
    ctx, err = _resolve_locked_scope_context(raw_cdir, body.get("analysis_id"), anchor_root)
    if err is not None or ctx is None:
        return err  # type: ignore[return-value]
    cdir = raw_cdir.resolve()
    report_md_path, deliv_md_path = cdir / "ANVIL-REPLICATION-REPORT.md", cdir / "DELIVERABLES.md"
    try:
        _apd.ensure_deliverables_not_reparse(raw_cdir, report_md_path, deliv_md_path)
    except PermissionError as pe:
        return _refuse403("PATH_ESCAPE_REFUSED", str(pe))
    md_text = ctx["v4_mods"]["anvil_replication_audit"].render_deliverables_markdown(state_d["report"], repo_root=str(ctx["sw_dir"]), cockpit_root=str(cdir))
    with _as.exclusive_file_lock(report_md_path):
        if _as._is_symlink_or_junction(report_md_path):
            return _refuse403("PATH_ESCAPE_REFUSED", "Symlink swap refused on ANVIL-REPLICATION-REPORT.md.")
        _as._atomic_write_text(report_md_path, md_text)
    bullet = f"- **Anvil Replication & Ramanujan Report (`#{ctx['scope_sha256'][:8]}`):** `ANVIL-REPLICATION-REPORT.md`\n"
    with _as.exclusive_file_lock(deliv_md_path):
        if _as._is_symlink_or_junction(deliv_md_path):
            return _refuse403("PATH_ESCAPE_REFUSED", "Symlink swap refused on DELIVERABLES.md.")
        cur_deliv = deliv_md_path.read_text(encoding="utf-8", errors="replace") if deliv_md_path.is_file() else "# Cockpit Deliverables\n\n"
        if "ANVIL-REPLICATION-REPORT.md" not in cur_deliv:
            cur_deliv = cur_deliv.rstrip() + "\n" + bullet
        _as._atomic_write_text(deliv_md_path, cur_deliv)
    return ({"ok": True, "report_file": "ANVIL-REPLICATION-REPORT.md", "deliverables_file": "DELIVERABLES.md", "markdown": md_text, "scope_sha256": ctx["scope_sha256"]}, 200)


_LOADED_MTIME_NS = Path(__file__).stat().st_mtime_ns
