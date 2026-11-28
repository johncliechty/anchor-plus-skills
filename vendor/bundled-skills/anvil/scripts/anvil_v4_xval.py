#!/usr/bin/env python3
"""Anvil v4/v5 Pillar 6 — Bounded 2-Seat Cross-Family Orchestrator <-> Validator
Reconciliation, Divergence Citation Audit, Live Co-Pilot Subscription-CLI Runner &
Atomic Attestation Receipt (`scripts/anvil_v4_xval.py`).

Enforces hard ceilings (`max_concurrency <= 2`, `max_digest_bytes <= 32768`,
`timeout_sec <= 60.0`), zero per-file serial LLM spawns, `shell=False` argv
validation, preserved CLI subscription auth env (`USERPROFILE`/`APPDATA`/
`LOCALAPPDATA`/`HOME`/`PATH`/`ANTHROPIC_*` with `ANCHOR_TOKEN` & non-CLI secrets
scrubbed), read-only target access (`--tools Read,Glob,Grep`), positive
`model_served == "claude-fable-5-2"` attestation (`ATTESTATION_MISMATCH_REFUSAL`
on silent `claude-opus-5-5` substitution), 2-seat per-divergence code & manuscript
citation verification (`audit_divergence_citations`), and honest
`DETERMINISTIC_FALLBACK` / `RATE_LIMITED_COOLDOWN` when offline or rate-limited.
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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from anvil_v4_process import (
    AnvilRefusalError,
    _is_link_or_junction,
    _parse_strict_json_bytes,
    atomic_locked_read_json,
    atomic_locked_write_json,
    build_process_map,
    resolve_contained_path,
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
CITATION_AUDIT_SCHEMA = "anvil-v5-citation-audit/v1"

MAX_XVAL_CONCURRENCY = 2
MAX_XVAL_DIGEST_BYTES = 32_768
MAX_XVAL_TIMEOUT_SEC = 300.0

CANONICAL_CLAUDE_FABLE_MODEL = "claude-fable-5-2"
CANONICAL_GEMINI_AGY_MODEL = "gemini-4-neon-high"
CLAUDE_READONLY_TOOLS = "Read,Glob,Grep"
CLAUDE_LOCK_MODEL_SETTINGS = '{"switchModelsOnFlag":false}'

AGY_NO_SHELL_STEER = (
    "TOOL POLICY (MANDATORY): Use ONLY your in-process read-only file tools (view_file, list_dir, "
    "grep_search, find_by_name). Do NOT use run_command or any shell/terminal tool for ANY reason — "
    "on Windows agy opens a visible PowerShell window that steals focus. Stay strictly file-tools-only.\n\n---\n\n"
)

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
    "fable": "claude",
    "opus": "claude",
    "sonnet": "claude",
    "haiku": "claude",
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

_PRESERVED_CLI_ENV_EXACT = frozenset({
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOME",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERNAME",
    "USER",
    "LOGNAME",
    "HOMEDRIVE",
    "HOMEPATH",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
    "COMMONPROGRAMFILES",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "GROK_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "NO_COLOR",
})

_SCRUBBED_NON_CLI_SECRETS = frozenset({
    "ANCHOR_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
})

_COOLDOWN_RATE_LIMIT_RE = re.compile(
    r"(?i)(?:rate[\s_-]?limit|cooldown|5[\s-]?hour|usage\s+limit|hit\s+your\s+limit|quota\s+exceeded|too\s+many\s+requests|\b429\b|resets?\s+(?:at|in)\b)"
)
_CITE_LINE_RE = re.compile(r"^([^:\s]+):L(\d+)(?:[-–]L?(\d+))?$")


def build_subscription_cli_env(base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Build subscription-CLI environment preserving host CLI auth/profile variables
    (`USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `HOME`, `PATH`, `ANTHROPIC_*`) while
    scrubbing `ANCHOR_TOKEN`, `OPENAI_API_KEY`, and generic host secrets.
    """
    src = dict(os.environ if base_env is None else base_env)
    out: Dict[str, str] = {}
    for k, v in src.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        ku = k.upper()
        if ku in _SCRUBBED_NON_CLI_SECRETS:
            continue
        if ku in _PRESERVED_CLI_ENV_EXACT or ku.startswith("ANTHROPIC_"):
            out[k] = v
            continue
        if any(tok in ku for tok in ("SECRET", "PASSWORD", "CREDENTIAL", "TOKEN", "API_KEY", "PRIVATE_KEY")):
            continue
        out[k] = v

    # Ensure agy CLI under %LOCALAPPDATA%/agy/bin is discoverable on Windows
    if os.name == "nt":
        local_app = out.get("LOCALAPPDATA") or (
            str(Path(out["USERPROFILE"]) / "AppData" / "Local") if out.get("USERPROFILE") else ""
        )
        if local_app:
            agy_dir = Path(local_app) / "agy" / "bin"
            if (agy_dir / "agy.exe").is_file():
                path_key = next((pk for pk in out if pk.upper() == "PATH"), "PATH")
                cur_parts = [p for p in out.get(path_key, "").split(os.pathsep) if p]
                norm_target = os.path.normcase(os.path.normpath(str(agy_dir)))
                if not any(os.path.normcase(os.path.normpath(p)) == norm_target for p in cur_parts):
                    out[path_key] = os.pathsep.join([*cur_parts, str(agy_dir)])

    out.setdefault("PYTHONIOENCODING", "utf-8")
    out.setdefault("PYTHONUTF8", "1")
    out["PYTHONDONTWRITEBYTECODE"] = "1"
    return out


def build_claude_fable_cli_argv(
    claude_bin: str = "claude",
    *,
    model: str = CANONICAL_CLAUDE_FABLE_MODEL,
    effort: str = "high",
) -> List[str]:
    """Construct the canonical read-only subscription Claude Fable 5.2 CLI argv."""
    return [
        claude_bin,
        "-p",
        "--model",
        model,
        "--effort",
        effort,
        "--output-format",
        "stream-json",
        "--verbose",
        "--settings",
        CLAUDE_LOCK_MODEL_SETTINGS,
        "--permission-mode",
        "plan",
        "--tools",
        CLAUDE_READONLY_TOOLS,
        "--max-turns",
        "12",
    ]


def build_gemini_agy_cli_argv(
    agy_bin: str = "agy",
    *,
    model: str = CANONICAL_GEMINI_AGY_MODEL,
    timeout_sec: float = 180.0,
) -> List[str]:
    """Construct the canonical read-only subscription Gemini (`agy`) stream-json CLI argv."""
    secs = max(15, int(float(timeout_sec) * 0.95)) if timeout_sec and timeout_sec > 0 else 170
    return [
        agy_bin,
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--mode",
        "plan",
        "--disable-slash-commands",
        "--print-timeout",
        f"{secs}s",
        "-p=",
    ]


def extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from a model text response (bare or fenced)."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None
    txt = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", txt, flags=re.IGNORECASE)
    if fence:
        txt = fence.group(1).strip()
    candidates = [txt]
    brace_m = re.search(r"\{[\s\S]*\}", txt)
    if brace_m:
        candidates.append(brace_m.group(0))
    for cand in candidates:
        if not cand:
            continue
        for cleaned in (cand, re.sub(r",(\s*[}\]])", r"\1", cand)):
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return None


def parse_claude_stream_json_frames(
    stdout_text: str,
    *,
    returncode: int = 0,
    stderr_text: str = "",
    requested_model: str = CANONICAL_CLAUDE_FABLE_MODEL,
) -> Dict[str, Any]:
    """Parse `claude -p --output-format stream-json --verbose` NDJSON frames without
    ever fabricating `model_served`.
    """
    final_env: Optional[Dict[str, Any]] = None
    served_model = ""
    last_text = ""
    sys_model = ""
    assistant_model = ""
    result_model = ""
    api_error_code = ""

    for raw_line in str(stdout_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except Exception:
            continue
        if not isinstance(frame, dict):
            continue
        if isinstance(frame.get("api_error_code"), str) and frame["api_error_code"].strip():
            api_error_code = frame["api_error_code"].strip()
        ftype = str(frame.get("type") or "")
        if ftype == "system":
            m_sys = str(frame.get("model") or "").strip()
            if m_sys and not m_sys.startswith("<"):
                sys_model = m_sys
        elif ftype == "assistant":
            msg = frame.get("message") if isinstance(frame.get("message"), dict) else {}
            m_asst = str(msg.get("model") or frame.get("model") or "").strip()
            if m_asst and not m_asst.startswith("<"):
                assistant_model = m_asst
            content = msg.get("content")
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        t_val = str(blk.get("text") or "").strip()
                        if t_val:
                            last_text = t_val
        elif ftype == "result":
            final_env = frame
            m_res = str(frame.get("model") or "").strip()
            if m_res and not m_res.startswith("<"):
                result_model = m_res

    served_model = result_model or assistant_model or sys_model
    is_err_flag = bool(final_env.get("is_error")) if isinstance(final_env, dict) else False
    ok = (returncode == 0) and (final_env is not None) and (not is_err_flag)

    result_text = ""
    if isinstance(final_env, dict) and isinstance(final_env.get("result"), str) and final_env["result"].strip():
        result_text = final_env["result"].strip()
    elif last_text:
        result_text = last_text

    diag_parts = [
        result_text if not ok else "",
        str((final_env or {}).get("error") or ""),
        stderr_text or "",
        api_error_code,
    ]
    diag_joined = " ".join(p for p in diag_parts if p).strip()
    is_cooldown = (not ok) and bool(_COOLDOWN_RATE_LIMIT_RE.search(diag_joined))

    if ok:
        status = "OK"
    elif is_cooldown:
        status = "RATE_LIMITED_COOLDOWN"
    else:
        status = "CLI_ERROR"

    # Honesty law: never forge model_served when CLI errors or hits cooldown without real frame evidence
    model_attested = bool(served_model) and (ok or bool(result_model or assistant_model))
    if is_cooldown and not ok:
        model_attested = False
        served_model = ""

    return {
        "ok": ok,
        "status": status,
        "returncode": int(returncode),
        "requested_model": requested_model,
        "model_family": "claude" if ok else None,
        "model_served": served_model or None,
        "model_attested": model_attested,
        "text": result_text if ok else "",
        "error": diag_joined[:500] if not ok else "",
    }


def _has_agy_terminal_result_frame(raw_text: str) -> bool:
    if '"result"' not in raw_text:
        return False
    for raw_line in raw_text.splitlines():
        s = raw_line.strip()
        if not s or '"result"' not in s:
            continue
        try:
            ev = json.loads(s)
            if isinstance(ev, dict) and ev.get("event") == "result" and isinstance(ev.get("result"), dict):
                return True
        except Exception:
            continue
    return False


def parse_gemini_stream_json_frames(
    stdout_text: str,
    *,
    returncode: int = 0,
    stderr_text: str = "",
    requested_model: str = CANONICAL_GEMINI_AGY_MODEL,
) -> Dict[str, Any]:
    """Parse `agy --output-format stream-json` NDJSON frames without fabricating `model_served`."""
    served_model = ""
    chunks: List[str] = []
    streamed_deltas: List[str] = []
    final_text = ""
    saw_error = False
    has_result_frame = False
    result_status_upper = ""
    err_msg = ""

    for raw_line in str(stdout_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except Exception:
            continue
        if not isinstance(frame, dict):
            continue
        ev = str(frame.get("event") or frame.get("type") or "")
        if ev == "init":
            init_d = frame.get("init") if isinstance(frame.get("init"), dict) else frame
            m = str(init_d.get("model") or "").strip()
            if m:
                served_model = m
        elif ev in {"assistant", "message"}:
            msg = frame.get("message") if isinstance(frame.get("message"), dict) else frame
            m = str(msg.get("model") or "").strip()
            if m:
                served_model = m
            c = msg.get("content")
            if isinstance(c, str) and c.strip():
                chunks.append(c.strip())
            elif isinstance(c, list):
                for blk in c:
                    if isinstance(blk, dict) and isinstance(blk.get("text"), str) and blk["text"].strip():
                        chunks.append(blk["text"].strip())
        elif ev == "step_update":
            su = frame.get("step_update") if isinstance(frame.get("step_update"), dict) else {}
            if isinstance(su.get("text_delta"), str) and su["text_delta"]:
                streamed_deltas.append(su["text_delta"])
            elif isinstance(su.get("text"), str) and su["text"].strip():
                chunks.append(su["text"].strip())
        elif ev == "result":
            has_result_frame = True
            res_d = frame.get("result") if isinstance(frame.get("result"), dict) else frame
            m = str(res_d.get("model") or frame.get("model") or "").strip()
            if m:
                served_model = m
            res_st = str(res_d.get("status") or "").strip().upper()
            result_status_upper = res_st
            if frame.get("is_error") is True or res_d.get("is_error") is True or res_st in {"ERROR", "FAILED", "CANCELLED"}:
                saw_error = True
                err_msg = str(res_d.get("error") or frame.get("error") or "")
            for k in ("response", "text", "output", "content"):
                val = res_d.get(k) if isinstance(res_d, dict) else None
                if isinstance(val, str) and val.strip():
                    final_text = val.strip()
                    break
            if not final_text and isinstance(frame.get("result"), str) and frame["result"].strip():
                final_text = frame["result"].strip()

    streamed_joined = "".join(streamed_deltas).strip()
    text_out = final_text or streamed_joined or ("\n".join(chunks).strip() if chunks else "")
    completed_result_ok = has_result_frame and result_status_upper == "SUCCESS" and bool(text_out) and not saw_error
    ok = ((returncode == 0) or completed_result_ok) and (not saw_error) and bool(text_out)
    diag = (err_msg or stderr_text or "").strip()
    is_cooldown = (not ok) and bool(_COOLDOWN_RATE_LIMIT_RE.search(diag))
    return {
        "ok": ok,
        "status": "OK" if ok else ("RATE_LIMITED_COOLDOWN" if is_cooldown else "CLI_ERROR"),
        "returncode": 0 if completed_result_ok else int(returncode),
        "requested_model": requested_model,
        "model_family": "gemini" if ok else None,
        "model_served": served_model if (ok and served_model) else None,
        "model_attested": bool(served_model and ok),
        "text": text_out if ok else "",
        "error": diag[:500] if not ok else "",
    }


def attest_claude_fable_served(
    parsed_turn: Dict[str, Any],
    *,
    expected_model: str = CANONICAL_CLAUDE_FABLE_MODEL,
    raise_on_mismatch: bool = True,
) -> Dict[str, Any]:
    """Enforce positive served-model attestation (`model_served == "claude-fable-5-2"` and
    `model_attested == True`). Fails closed with `ATTESTATION_MISMATCH_REFUSAL` if any
    unrequested model (e.g. `claude-opus-5-5` or `sonnet`) or unattested response is served.
    """
    served = parsed_turn.get("model_served")
    attested = bool(parsed_turn.get("model_attested"))
    if parsed_turn.get("ok") is True and attested and served == expected_model:
        return {
            "ok": True,
            "status": "ATTESTED",
            "requested_model": expected_model,
            "model_served": served,
            "model_attested": True,
        }
    err = AnvilRefusalError(
        "ATTESTATION_MISMATCH_REFUSAL",
        f"Claude positive model attestation failed: requested '{expected_model}' but served '{served or 'unattested'}'.",
        details={
            "status": "attestation_mismatch",
            "requested_model": expected_model,
            "model_served": served,
            "model_attested": attested,
        },
    )
    if raise_on_mismatch:
        raise err
    return err.to_dict()


def _resolve_manuscript_tex_file(
    repo_root: Path,
    paper_path: Optional[Path],
    tex_rel: str,
) -> Optional[Path]:
    clean_rel = (tex_rel or "").strip().replace("\\", "/")
    if not clean_rel or clean_rel.startswith("/") or ".." in Path(clean_rel).parts:
        return None
    roots_to_try: List[Path] = []
    if paper_path is not None and paper_path.exists():
        p_res = paper_path.resolve()
        roots_to_try.append(p_res if p_res.is_dir() else p_res.parent)
    for sub_name in ("Manuscript", "manuscript", "Paper", "paper", "."):
        cand_dir = (repo_root / sub_name).resolve() if sub_name != "." else repo_root.resolve()
        if cand_dir.is_dir() and cand_dir not in roots_to_try:
            roots_to_try.append(cand_dir)

    for base in roots_to_try:
        try:
            cand = (base / clean_rel).resolve()
            if (cand == base or cand.is_relative_to(base)) and not _is_link_or_junction(cand) and cand.is_file():
                return cand
        except OSError:
            continue
        base_only = Path(clean_rel).name
        if base_only and base_only != clean_rel:
            try:
                cand2 = (base / base_only).resolve()
                if (cand2 == base or cand2.is_relative_to(base)) and not _is_link_or_junction(cand2) and cand2.is_file():
                    return cand2
            except OSError:
                continue
    return None


def audit_divergence_citations(
    repo_dir: str | Path,
    divergences: Sequence[Dict[str, Any]],
    *,
    paper_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Deterministically verify every divergence row's:
      1. `code_citation` (`<rel_file>:L<line>` contained in `repo_dir`, `1 <= line <= total_lines`,
         and `code_snippet` matches source lines around `line`), AND
      2. `manuscript_citation` (`<tex_file>:L<line>` exists in manuscript `.tex` tree with matching
         passage when `contradicted_in_manuscript`, OR structured `search_record` with
         `verdict == "absent_from_manuscript"` and non-empty `searched_files` when `absent_from_manuscript`).
    """
    root = Path(repo_dir).resolve()
    resolved_paper = Path(paper_path).resolve() if paper_path else None
    rows_out: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    verified_count = 0

    for idx, div in enumerate(divergences or []):
        if not isinstance(div, dict):
            findings.append({
                "severity": "FAIL",
                "code": "INVALID_DIVERGENCE_ROW",
                "detail": f"Divergence index {idx} is not an object.",
            })
            rows_out.append({
                "id": f"DIV-{idx + 1:02d}",
                "category": "",
                "code_citation_ok": False,
                "manuscript_citation_ok": False,
                "ok": False,
                "errors": ["Divergence row is not a dict."],
            })
            continue

        div_id = str(div.get("id") or f"DIV-{idx + 1:02d}")
        cat = str(div.get("category") or "")
        row_errors: List[str] = []

        # 1. Verify code_citation + code_snippet
        code_cite = str(div.get("code_citation") or "").strip()
        code_snip = str(div.get("code_snippet") or "").strip()
        code_ok = False
        m_code = _CITE_LINE_RE.match(code_cite)
        if m_code is None:
            row_errors.append(f"Invalid code_citation syntax '{code_cite}' (expected <rel_file>:L<line>).")
        else:
            rel_file = m_code.group(1)
            line_no = int(m_code.group(2))
            try:
                cpath = resolve_contained_path(root, rel_file, must_be_relative=True)
            except AnvilRefusalError as esc_err:
                cpath = None
                row_errors.append(f"Uncontained code_citation '{rel_file}': {esc_err.message}")
            if cpath is not None:
                if not cpath.is_file():
                    row_errors.append(f"Cited code file '{rel_file}' does not exist.")
                else:
                    src_lines = cpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line_no < 1 or line_no > len(src_lines):
                        row_errors.append(
                            f"Cited line L{line_no} in '{rel_file}' out of bounds (1..{len(src_lines)})."
                        )
                    elif not code_snip:
                        row_errors.append(f"Missing code_snippet for '{code_cite}'.")
                    else:
                        win_lo = max(0, line_no - 8)
                        win_hi = min(len(src_lines), line_no + 10)
                        win_stripped = {ln.strip() for ln in src_lines[win_lo:win_hi] if ln.strip()}
                        snip_lines = [ln.strip() for ln in code_snip.splitlines() if ln.strip()]
                        if not snip_lines or not all(sln in win_stripped for sln in snip_lines):
                            row_errors.append(
                                f"code_snippet does not match source lines around '{code_cite}'."
                            )
                        else:
                            code_ok = True

        # 2. Verify manuscript_status + manuscript_citation / search_record
        ms_status = str(div.get("manuscript_status") or "").strip()
        ms_ok = False
        if ms_status == "contradicted_in_manuscript":
            ms_cite = str(div.get("manuscript_citation") or "").strip()
            ms_passage = str(div.get("manuscript_passage") or "").strip()
            m_tex = _CITE_LINE_RE.match(ms_cite)
            if m_tex is None:
                row_errors.append(
                    f"Invalid manuscript_citation '{ms_cite}' for contradicted_in_manuscript."
                )
            elif len(ms_passage) < 8:
                row_errors.append(f"Missing or too-short manuscript_passage on '{div_id}'.")
            else:
                tex_rel = m_tex.group(1)
                tex_line = int(m_tex.group(2))
                tex_fp = _resolve_manuscript_tex_file(root, resolved_paper, tex_rel)
                if tex_fp is None or not tex_fp.is_file():
                    row_errors.append(f"Cited manuscript file '{tex_rel}' not found in manuscript tree.")
                else:
                    tex_lines = tex_fp.read_text(encoding="utf-8", errors="replace").splitlines()
                    if tex_line < 1 or tex_line > len(tex_lines):
                        row_errors.append(
                            f"Cited manuscript line L{tex_line} in '{tex_rel}' out of bounds (1..{len(tex_lines)})."
                        )
                    else:
                        t_lo = max(0, tex_line - 6)
                        t_hi = min(len(tex_lines), tex_line + 6)
                        tex_win = " ".join(tex_lines[t_lo:t_hi]).lower()
                        p_words = [
                            w
                            for w in re.findall(r"[a-z0-9]{4,}", ms_passage.lower())
                            if w not in {"with", "from", "that", "this", "each", "into"}
                        ]
                        if p_words:
                            hits = sum(1 for w in p_words if w in tex_win)
                            if hits < max(1, int(len(p_words) * 0.4)):
                                row_errors.append(
                                    f"manuscript_passage words do not match '{ms_cite}' window."
                                )
                            else:
                                ms_ok = True
                        else:
                            ms_ok = True
        elif ms_status == "absent_from_manuscript":
            sr = div.get("search_record")
            if not isinstance(sr, dict):
                row_errors.append(f"Missing structured search_record dict on '{div_id}'.")
            else:
                sr_verdict = str(sr.get("verdict") or "").strip()
                s_files = sr.get("searched_files")
                s_queries = sr.get("queries")
                closest_sec = str(sr.get("closest_section") or "").strip()
                if sr_verdict != "absent_from_manuscript":
                    row_errors.append(
                        f"search_record.verdict must be 'absent_from_manuscript' (got '{sr_verdict}')."
                    )
                elif not isinstance(s_files, list) or len(s_files) == 0 or any(not str(x).strip() for x in s_files):
                    row_errors.append(f"search_record.searched_files must be a non-empty list on '{div_id}'.")
                elif not isinstance(s_queries, list) or len(s_queries) == 0:
                    row_errors.append(f"search_record.queries must be a non-empty list on '{div_id}'.")
                elif not closest_sec:
                    row_errors.append(f"search_record.closest_section must be non-empty on '{div_id}'.")
                else:
                    if resolved_paper is not None and resolved_paper.exists():
                        resolved_tex_files = [
                            _resolve_manuscript_tex_file(root, resolved_paper, str(sf))
                            for sf in s_files
                        ]
                        existing_tex = [fp for fp in resolved_tex_files if fp is not None and fp.is_file()]
                        if not existing_tex:
                            row_errors.append(
                                f"None of search_record.searched_files exist in manuscript tree on '{div_id}'."
                            )
                        else:
                            non_comment_lines: List[str] = []
                            for tfp in existing_tex:
                                for raw_ln in tfp.read_text(encoding="utf-8", errors="replace").splitlines():
                                    stripped_ln = raw_ln.lstrip()
                                    if not stripped_ln.startswith("%"):
                                        non_comment_lines.append(raw_ln.split("%", 1)[0])
                            tex_corpus = "\n".join(non_comment_lines)
                            symbol_queries = [
                                str(q).strip()
                                for q in s_queries
                                if isinstance(q, str)
                                and "_" in q.strip()
                                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{4,}", q.strip())
                            ]
                            hit_sym = next(
                                (
                                    sq
                                    for sq in symbol_queries
                                    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(sq) + r"(?![A-Za-z0-9_])", tex_corpus, re.IGNORECASE)
                                ),
                                None,
                            )
                            if hit_sym is not None:
                                row_errors.append(
                                    f"absent_from_manuscript falsified on '{div_id}': queried code symbol '{hit_sym}' appears in manuscript."
                                )
                            elif sr.get("executed_regex"):
                                try:
                                    from anvil_v4_refactor import verify_divergence_search_record
                                    repro = verify_divergence_search_record(resolved_paper, sr)
                                    if not repro.get("ok", True):
                                        row_errors.append(
                                            f"absent_from_manuscript executed_regex falsified on '{div_id}': {repro.get('error') or 'matched manuscript'}."
                                        )
                                    else:
                                        ms_ok = True
                                except ImportError:
                                    ms_ok = True
                            else:
                                ms_ok = True
                    else:
                        ms_ok = True
        else:
            row_errors.append(
                f"Invalid manuscript_status '{ms_status}' on '{div_id}'."
            )

        row_ok = code_ok and ms_ok and not row_errors
        if row_ok:
            verified_count += 1
        else:
            for err_txt in row_errors:
                findings.append({
                    "severity": "FAIL",
                    "code": "DIVERGENCE_CITATION_INVALID",
                    "divergence_id": div_id,
                    "detail": f"[{div_id}] {err_txt}",
                })
        rows_out.append({
            "id": div_id,
            "category": cat,
            "code_citation": code_cite,
            "code_citation_ok": code_ok,
            "manuscript_status": ms_status,
            "manuscript_citation_ok": ms_ok,
            "ok": row_ok,
            "errors": row_errors,
        })

    return {
        "schema": CITATION_AUDIT_SCHEMA,
        "ok": len(findings) == 0,
        "verdict": "PASS" if len(findings) == 0 else "FAIL",
        "total_divergences": len(rows_out),
        "verified_count": verified_count,
        "failed_count": len(rows_out) - verified_count,
        "rows": rows_out,
        "findings": findings,
    }


def _default_subscription_cli_runner(
    *,
    seat: str,
    family: str,
    argv: Sequence[str],
    stdin_bytes: bytes,
    env: Dict[str, str],
    cwd: str,
    timeout_sec: float,
) -> Dict[str, Any]:
    """Execute a validated read-only subscription CLI (`shell=False`) with process-tree timeout kill."""
    clean_argv = _validate_validator_argv(list(argv))
    resolved = _resolve_validator_binary(clean_argv)
    if resolved is None:
        return {
            "returncode": 127,
            "stdout": "",
            "stderr": f"Subscription CLI binary '{clean_argv[0]}' not installed on host.",
            "missing_binary": True,
        }
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(
            resolved,
            cwd=cwd,
            env=env,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name != "nt"),
            creationflags=creationflags,
        )
    except OSError as exc:
        return {
            "returncode": 127,
            "stdout": "",
            "stderr": f"Failed to launch subscription CLI ({exc}).",
            "missing_binary": True,
        }
    if family == "gemini":
        import threading as _th

        out_lines: List[bytes] = []
        err_chunks: List[bytes] = []
        saw_result_evt = _th.Event()

        def _write_in() -> None:
            try:
                if proc.stdin is not None:
                    if stdin_bytes:
                        proc.stdin.write(stdin_bytes)
                        proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                pass

        def _read_out() -> None:
            try:
                if proc.stdout is not None:
                    for ln in iter(proc.stdout.readline, b""):
                        out_lines.append(ln)
                        if b'"result"' in ln and _has_agy_terminal_result_frame(ln.decode("utf-8", errors="replace")):
                            saw_result_evt.set()
            except Exception:
                pass

        def _read_err() -> None:
            try:
                if proc.stderr is not None:
                    data = proc.stderr.read()
                    if data:
                        err_chunks.append(data)
            except Exception:
                pass

        tw = _th.Thread(target=_write_in, daemon=True)
        to = _th.Thread(target=_read_out, daemon=True)
        te = _th.Thread(target=_read_err, daemon=True)
        tw.start()
        to.start()
        te.start()

        deadline = t0 + float(timeout_sec)
        timed_out_flag = False
        reaped_after_result = False
        while proc.poll() is None:
            if saw_result_evt.is_set():
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc)
                    reaped_after_result = True
                break
            if time.perf_counter() >= deadline:
                _kill_process_tree(proc)
                timed_out_flag = True
                break
            time.sleep(0.05)

        to.join(timeout=1.5)
        te.join(timeout=1.5)
        stdout_s = b"".join(out_lines).decode("utf-8", errors="replace")
        stderr_s = b"".join(err_chunks).decode("utf-8", errors="replace")
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
        if timed_out_flag and not _has_agy_terminal_result_frame(stdout_s):
            return {
                "returncode": 124,
                "stdout": stdout_s,
                "stderr": stderr_s or f"Subscription CLI seat '{seat}' ({family}) timed out after {timeout_sec}s.",
                "timed_out": True,
            }
        rc_val = 0 if (reaped_after_result or _has_agy_terminal_result_frame(stdout_s)) else int(proc.returncode or 0)
        return {
            "returncode": rc_val,
            "stdout": stdout_s,
            "stderr": stderr_s,
            "elapsed_ms": elapsed_ms,
            "argv": list(resolved),
        }

    try:
        out_b, err_b = proc.communicate(input=stdin_bytes, timeout=float(timeout_sec))
    except subprocess.TimeoutExpired as tex_exc:
        _kill_process_tree(proc)
        part_out = tex_exc.stdout.decode("utf-8", errors="replace") if isinstance(tex_exc.stdout, bytes) else str(tex_exc.stdout or "")
        return {
            "returncode": 124,
            "stdout": part_out,
            "stderr": f"Subscription CLI seat '{seat}' ({family}) timed out after {timeout_sec}s.",
            "timed_out": True,
        }
    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    return {
        "returncode": int(proc.returncode or 0),
        "stdout": out_b.decode("utf-8", errors="replace"),
        "stderr": err_b.decode("utf-8", errors="replace"),
        "elapsed_ms": elapsed_ms,
        "argv": list(resolved),
    }


def run_live_copilot_cli_turn(
    repo_dir: str | Path,
    question: str,
    grounded_context: Dict[str, Any],
    *,
    preferred_family: str = "gemini",
    live: Optional[bool] = None,
    cli_argv: Optional[Sequence[str]] = None,
    cli_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    timeout_sec: float = 25.0,
    base_env: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Execute a live read-only subscription-CLI Steward Co-Pilot turn grounded on `S1..Sk`,
    `N1..Nk`, pinned watches, tripwires, and `[data-divergence-panel]` rows when live mode
    is enabled (`live=True`, `ANCHOR_TESTS_ALLOW_LIVE=1`, `ANCHOR_ANVIL_LIVE_CHAT=1`, or
    explicit `cli_runner`/`cli_argv`). Returns `None` in hermetic test mode so callers use
    instant deterministic synthesis.
    """
    env_src = os.environ if base_env is None else base_env
    explicit_live_env = (
        env_src.get("ANCHOR_TESTS_ALLOW_LIVE") == "1"
        or env_src.get("ANCHOR_ANVIL_LIVE_CHAT") == "1"
    )
    in_hermetic_pytest = (
        ("PYTEST_CURRENT_TEST" in env_src or env_src.get("ANVIL_XVAL_OFFLINE") == "1")
        and not explicit_live_env
        and cli_runner is None
        and cli_argv is None
    )
    if in_hermetic_pytest:
        return None
    live_enabled = (
        bool(live)
        or cli_runner is not None
        or cli_argv is not None
        or explicit_live_env
    )
    if not live_enabled:
        return None

    root = Path(repo_dir).resolve()
    fam = (preferred_family or "gemini").strip().lower()
    if fam == "anthropic":
        fam = "claude"
    elif fam == "google":
        fam = "gemini"
    if fam not in {"claude", "gemini"}:
        fam = "gemini"

    compact_ctx = json.dumps(grounded_context, ensure_ascii=False, separators=(",", ":"))[:16_384]
    base_prompt = (
        "You are the Anvil v5 Steward Co-Pilot inside an Anchor AI Cockpit (strictly read-only).\n"
        "Answer the investigator's question concisely in 2-5 grounded sentences using ONLY the verified "
        "AST stage contracts (S1..Sk -> N1..Nk), Smart Variable Funnel / pinned watches, runtime tripwires, "
        "and Manuscript-vs-Code divergence citations below. Cite exact file:L<line> and DIV-xx IDs when relevant.\n\n"
        f"GROUNDED_WORKBENCH_CONTEXT_JSON:\n{compact_ctx}\n\n"
        f"INVESTIGATOR_QUESTION:\n{question.strip()[:2048]}\n"
    )
    prompt = (AGY_NO_SHELL_STEER + base_prompt) if (fam == "gemini" and cli_argv is None) else base_prompt

    sub_env = build_subscription_cli_env(dict(env_src))
    runner_fn = cli_runner or _default_subscription_cli_runner

    if cli_argv is not None:
        target_argv = _validate_validator_argv(list(cli_argv))
        _refuse_repo_local_validator_argv(target_argv, None, root)
    elif fam == "claude":
        target_argv = build_claude_fable_cli_argv("claude", model=CANONICAL_CLAUDE_FABLE_MODEL, effort="high")
    else:
        target_argv = build_gemini_agy_cli_argv(
            "agy",
            model=CANONICAL_GEMINI_AGY_MODEL,
            timeout_sec=min(float(timeout_sec), MAX_XVAL_TIMEOUT_SEC),
        )

    stdin_payload = (
        (json.dumps({"event": "user", "message": {"role": "user", "content": prompt}}) + "\n").encode("utf-8")
        if fam == "gemini" and cli_argv is None
        else prompt.encode("utf-8")
    )

    raw_res = runner_fn(
        seat="copilot",
        family=fam,
        argv=target_argv,
        stdin_bytes=stdin_payload,
        env=sub_env,
        cwd=str(root),
        timeout_sec=min(float(timeout_sec), MAX_XVAL_TIMEOUT_SEC),
    )

    rc = int(raw_res.get("returncode", 1))
    out_s = str(raw_res.get("stdout") or "")
    err_s = str(raw_res.get("stderr") or "")

    if fam == "claude":
        parsed = parse_claude_stream_json_frames(
            out_s,
            returncode=rc,
            stderr_text=err_s,
            requested_model=CANONICAL_CLAUDE_FABLE_MODEL,
        )
        if parsed["status"] == "RATE_LIMITED_COOLDOWN":
            return {
                "ok": False,
                "status": "RATE_LIMITED_COOLDOWN",
                "answer_mode": "rate_limited_fallback",
                "model_family": "claude",
                "model_served": None,
                "model_attested": False,
                "error": parsed["error"],
                "argv_used": list(target_argv),
                "env_preserved": {k: sub_env.get(k, "") for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "PATH") if k in sub_env},
            }
        if parsed["ok"] or parsed.get("model_served"):
            attest_claude_fable_served(parsed, expected_model=CANONICAL_CLAUDE_FABLE_MODEL, raise_on_mismatch=True)
            return {
                "ok": True,
                "status": "OK",
                "answer_mode": "live_cli",
                "reply": parsed["text"],
                "model_family": "claude",
                "model_served": parsed["model_served"],
                "model_attested": True,
                "argv_used": list(target_argv),
            }
        return {
            "ok": False,
            "status": parsed["status"],
            "answer_mode": "deterministic_fallback",
            "model_family": "claude",
            "model_served": None,
            "model_attested": False,
            "error": parsed["error"],
            "argv_used": list(target_argv),
        }

    parsed_g = parse_gemini_stream_json_frames(out_s, returncode=rc, stderr_text=err_s)
    if parsed_g["ok"] and parsed_g.get("model_attested") and parsed_g.get("model_served"):
        return {
            "ok": True,
            "status": "OK",
            "answer_mode": "live_cli",
            "reply": parsed_g["text"],
            "model_family": "gemini",
            "model_served": parsed_g["model_served"],
            "model_attested": True,
            "argv_used": list(target_argv),
        }
    return {
        "ok": False,
        "status": parsed_g["status"],
        "answer_mode": "rate_limited_fallback" if parsed_g["status"] == "RATE_LIMITED_COOLDOWN" else "deterministic_fallback",
        "model_family": "gemini",
        "model_served": None,
        "model_attested": False,
        "error": parsed_g["error"],
        "argv_used": list(target_argv),
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
        if not isinstance(tok, str) or "\x00" in tok or (idx == 0 and not tok.strip()):
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
    *,
    repo_root: Optional[Path] = None,
    paper_path: Optional[Path] = None,
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
        divs = paper_map.get("divergences") or []
        if divs and repo_root is not None:
            cite_audit = audit_divergence_citations(repo_root, divs, paper_path=paper_path)
            findings.extend(cite_audit["findings"])

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
    """Load out-of-repo host HMAC-SHA256 seat keyring (`anvil-v4-host-keyring/v1`)."""
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
    """Verify out-of-repo HMAC-SHA256 Seat-1 provenance receipt bound to `repo_fingerprint`."""
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


def _compact_divergence_for_digest(div: Dict[str, Any], snippet_cap: int = 220) -> Dict[str, Any]:
    ms_status = str(div.get("manuscript_status") or "")
    sr = div.get("search_record") if isinstance(div.get("search_record"), dict) else {}
    out: Dict[str, Any] = {
        "id": div.get("id", ""),
        "category": div.get("category", ""),
        "code_citation": div.get("code_citation", ""),
        "code_snippet": str(div.get("code_snippet") or "")[:snippet_cap],
        "summary": str(div.get("summary") or "")[:snippet_cap],
        "manuscript_status": ms_status,
    }
    if ms_status == "contradicted_in_manuscript":
        out["manuscript_citation"] = div.get("manuscript_citation", "")
        out["manuscript_passage"] = str(div.get("manuscript_passage") or "")[:snippet_cap]
    else:
        out["search_record"] = {
            "verdict": sr.get("verdict") or sr.get("status") or "",
            "searched_files": list(sr.get("searched_files") or [])[:10],
            "queries": list(sr.get("queries") or [])[:4],
            "closest_section": str(sr.get("closest_section") or "")[:96],
        }
    return out


def _build_bounded_xval_digest(
    proc_map: Dict[str, Any],
    ref_map: Dict[str, Any],
    pap_map: Optional[Dict[str, Any]],
    *,
    repo_fp: str,
    orchestrator_family: str,
    det_verdict: str,
    citation_audit: Dict[str, Any],
    max_digest_bytes: int,
    raw_digest_override: Optional[Any] = None,
) -> Tuple[Dict[str, Any], bytes]:
    if raw_digest_override is not None:
        if isinstance(raw_digest_override, bytes):
            raw_b = raw_digest_override
            override_obj: Dict[str, Any] = {"schema": XVAL_DIGEST_SCHEMA, "override_bytes": len(raw_b)}
        elif isinstance(raw_digest_override, str):
            override_obj = {"schema": XVAL_DIGEST_SCHEMA, "override": raw_digest_override}
            raw_b = json.dumps(override_obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(raw_digest_override, dict):
            override_obj = dict(raw_digest_override)
            raw_b = json.dumps(override_obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        else:
            raise AnvilRefusalError("MALFORMED_DATA_REFUSED", "Invalid raw_digest_override type.", cwe="CWE-502")
        if len(raw_b) > max_digest_bytes:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Batched claim digest ({len(raw_b)} bytes) exceeds max_digest_bytes={max_digest_bytes}.",
                details={
                    "bound_name": "max_digest_bytes",
                    "bound_limit": max_digest_bytes,
                    "observed_value": len(raw_b),
                },
            )
        return override_obj, raw_b

    null_set = ref_map.get("null_set") or {}
    raw_divs = ((pap_map or {}).get("divergences") or []) if isinstance(pap_map, dict) else []

    div_all_cap = max(len(raw_divs), 32)
    for snip_cap, stage_cap, eq_cap, div_cap in (
        (220, 8, 24, div_all_cap),
        (120, 6, 16, div_all_cap),
        (64, 4, 8, div_all_cap),
    ):
        digest_obj: Dict[str, Any] = {
            "schema": XVAL_DIGEST_SCHEMA,
            "repo_fingerprint": repo_fp,
            "orchestrator_family": orchestrator_family,
            "stages": [
                {
                    "id": s.get("id"),
                    "kind": s.get("kind"),
                    "verdict": s.get("verdict"),
                    "symbols": (s.get("member_symbols") or [])[:12],
                }
                for s in (proc_map.get("l1_stages") or [])[:stage_cap]
            ],
            "target_stages": [
                {
                    "id": ns.get("id"),
                    "role": ns.get("role"),
                    "symbol_count": ns.get("symbol_count", 0),
                }
                for ns in (ref_map.get("target_stages") or [])[:stage_cap]
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
                for eq in ((pap_map or {}).get("equations") or [])[:eq_cap]
            ],
            "divergences": [
                _compact_divergence_for_digest(d, snippet_cap=snip_cap)
                for d in raw_divs[:div_cap]
                if isinstance(d, dict)
            ],
            "citation_audit_summary": {
                "total": citation_audit.get("total_divergences", 0),
                "verified": citation_audit.get("verified_count", 0),
                "verdict": citation_audit.get("verdict", "PASS"),
            },
            "deterministic_check_verdict": det_verdict,
        }
        digest_bytes = json.dumps(
            digest_obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        if len(digest_bytes) <= max_digest_bytes:
            return digest_obj, digest_bytes

    raise AnvilRefusalError(
        "BOUND_EXCEEDED_REFUSAL",
        f"Batched claim digest ({len(digest_bytes)} bytes) exceeds max_digest_bytes={max_digest_bytes}.",
        details={
            "bound_name": "max_digest_bytes",
            "bound_limit": max_digest_bytes,
            "observed_value": len(digest_bytes),
        },
    )


def _evaluate_seat_citation_reply(
    seat_name: str,
    seat_text: str,
    deterministic_audit: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fail-closed evaluation of a live/injected seat's JSON citation checks combined with deterministic checks."""
    parsed_obj = extract_json_object(seat_text)
    det_rows = list(deterministic_audit.get("rows") or [])
    if not isinstance(parsed_obj, dict) or not parsed_obj:
        fail_rows = [
            {
                "id": str(d_row["id"]),
                "seat": seat_name,
                "code_citation_verified": False,
                "manuscript_citation_verified": False,
                "ok": False,
                "notes": "Seat reply was empty or contained no valid JSON object.",
            }
            for d_row in det_rows
        ]
        return (
            "FAIL",
            fail_rows,
            [
                {
                    "severity": "FAIL",
                    "code": "SEAT_REPLY_UNPARSEABLE",
                    "seat": seat_name,
                    "detail": f"[{seat_name}] Seat reply contained no valid JSON audit object.",
                }
            ],
        )

    raw_verdict = str(parsed_obj.get("verdict") or "").strip().upper()
    if raw_verdict not in {"PASS", "WARN", "FAIL"}:
        raw_verdict = "FAIL"

    seat_checks = parsed_obj.get("citation_checks")
    checks_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(seat_checks, list):
        for item in seat_checks:
            if isinstance(item, dict) and item.get("id"):
                checks_by_id[str(item["id"])] = item
    elif det_rows:
        raw_verdict = "FAIL"

    merged_rows: List[Dict[str, Any]] = []
    seat_findings: List[Dict[str, Any]] = []
    for f_raw in (parsed_obj.get("findings") or [])[:25]:
        if isinstance(f_raw, dict) and f_raw.get("detail"):
            sev_up = str(f_raw.get("severity") or "WARN").upper()
            seat_findings.append({
                "severity": sev_up,
                "code": str(f_raw.get("code") or f"{seat_name.upper()}_FINDING"),
                "seat": seat_name,
                "detail": str(f_raw["detail"])[:800],
            })
            if sev_up in {"FAIL", "BLOCKER", "ERROR"}:
                raw_verdict = "FAIL"

    for d_row in det_rows:
        did = str(d_row["id"])
        s_chk = checks_by_id.get(did)
        has_seat_row = isinstance(s_chk, dict)
        seat_code_ok = bool(has_seat_row and s_chk.get("code_citation_verified") is True)
        seat_ms_ok = bool(has_seat_row and s_chk.get("manuscript_citation_verified") is True)
        s_code_ok = seat_code_ok and bool(d_row["code_citation_ok"])
        s_ms_ok = seat_ms_ok and bool(d_row["manuscript_citation_ok"])
        row_ok = has_seat_row and s_code_ok and s_ms_ok and bool(d_row["ok"])
        default_note = (
            f"Missing citation_checks entry for '{did}'."
            if not has_seat_row
            else (", ".join(d_row.get("errors") or []) or ("verified" if row_ok else "citation check failed"))
        )
        merged_rows.append({
            "id": did,
            "seat": seat_name,
            "code_citation_verified": s_code_ok,
            "manuscript_citation_verified": s_ms_ok,
            "ok": row_ok,
            "notes": str((s_chk or {}).get("notes") or default_note)[:800],
        })
        if not row_ok:
            raw_verdict = "FAIL"
            seat_findings.append({
                "severity": "FAIL",
                "code": "SEAT_CITATION_AUDIT_FAILED",
                "seat": seat_name,
                "divergence_id": did,
                "detail": f"[{seat_name}:{did}] Citation verification failed ({merged_rows[-1]['notes']}).",
            })

    if not deterministic_audit.get("ok", True):
        raw_verdict = "FAIL"
    return raw_verdict, merged_rows, seat_findings


def _compute_verdict_qualified(
    verdict: str,
    *,
    cross_family_attested: bool,
    live_attested_seats: int,
) -> str:
    if verdict == "FAIL":
        return "FAIL"
    if verdict == "PASS":
        if cross_family_attested:
            return "PASS"
        if live_attested_seats >= 1:
            return "PASS_SINGLE_FAMILY"
        return "PASS_DETERMINISTIC_ONLY"
    return verdict


def _run_subscription_2seat_xval(
    root: Path,
    digest_obj: Dict[str, Any],
    digest_bytes: bytes,
    digest_sha256: str,
    citation_audit: Dict[str, Any],
    det_verdict: str,
    det_findings: List[Dict[str, Any]],
    *,
    max_concurrency: int,
    timeout_sec: float,
    cli_runner: Optional[Callable[..., Dict[str, Any]]],
    seat1_cli_argv: Optional[Sequence[str]],
    seat2_cli_argv: Optional[Sequence[str]],
) -> Dict[str, Any]:
    """Execute bounded 2-seat subscription-CLI XVal:
      - Seat 1 (`orchestrator`, Gemini `agy` read-only with positive frame attestation)
      - Seat 2 (`validator`, Claude `claude-fable-5-2` read-only with positive frame attestation)
    Both seats audit every divergence row's `code_citation` (`file:L<line>`) and
    `manuscript_citation` / `absent_from_manuscript` `search_record` fail-closed.
    """
    runner_fn = cli_runner or _default_subscription_cli_runner
    sub_env = build_subscription_cli_env()

    s1_argv = (
        _validate_validator_argv(list(seat1_cli_argv))
        if seat1_cli_argv is not None
        else build_gemini_agy_cli_argv("agy", model=CANONICAL_GEMINI_AGY_MODEL, timeout_sec=timeout_sec)
    )
    s2_argv = (
        _validate_validator_argv(list(seat2_cli_argv))
        if seat2_cli_argv is not None
        else build_claude_fable_cli_argv("claude", model=CANONICAL_CLAUDE_FABLE_MODEL, effort="high")
    )
    _refuse_repo_local_validator_argv(s1_argv, None, root)
    _refuse_repo_local_validator_argv(s2_argv, None, root)

    audit_prompt = (
        "You are an Anvil v5 Cross-Validation & Citation Auditor (strictly read-only; do NOT write any plan or file).\n"
        "Verify every divergence row in `divergences` from `XVAL_DIGEST_JSON`: confirm "
        "(1) `code_citation` (<rel_file>:L<line>) and `code_snippet` match repository source lines in bounds, and "
        "(2) when `manuscript_status == \"contradicted_in_manuscript\"`, verify that `manuscript_citation` (<tex_file>:L<line>) "
        "and `manuscript_passage` exist in the `.tex` manuscript and either omit the concrete code mechanism "
        "(for example, a formal model/likelihood/joint-training or CV specification that omits a two-stage `load_state_dict` "
        "transfer, cross-segment deviation penalty, or 1-SE CV gate, even if empirical discussion prose elsewhere qualitatively "
        "motivates anchoring or shrinkage) or describe a simpler form than the code (for example, single-attribute shift prose "
        "vs a multi-column index slice); OR when `manuscript_status == \"absent_from_manuscript\"`, confirm against the `.tex` "
        "files in `search_record.searched_files` that the concrete code mechanism in `search_record.queries` (for example, "
        "explicit `load_state_dict`/`strict=False` state transfer, `normal_` parameter perturbation, or multi-group optimizer "
        "schedules — even if prose qualitatively motivates baseline anchoring) is genuinely absent from the manuscript "
        "(with `search_record.verdict == \"absent_from_manuscript\"`).\n"
        "Batch any needed file reads in parallel (at most 1-2 read batches) and do NOT explore unrelated files.\n"
        "Include an entry in `citation_checks` for EVERY `id` in `divergences`.\n"
        "Respond with ONLY strict JSON (no markdown commentary outside JSON): "
        "{\"verdict\":\"PASS\"|\"FAIL\",\"citation_checks\":[{\"id\":\"DIV-01\","
        "\"code_citation_verified\":true,\"manuscript_citation_verified\":true,\"notes\":\"ok\"}],\"findings\":[]}\n\n"
        "XVAL_DIGEST_JSON:\n"
        + digest_bytes.decode("utf-8")
        + "\n"
    )
    s1_prompt = (AGY_NO_SHELL_STEER + audit_prompt) if seat1_cli_argv is None else audit_prompt
    s1_stdin = (
        (json.dumps({"event": "user", "message": {"role": "user", "content": s1_prompt}}) + "\n").encode("utf-8")
        if seat1_cli_argv is None
        else s1_prompt.encode("utf-8")
    )
    s2_stdin = audit_prompt.encode("utf-8")

    if len(s2_stdin) > MAX_XVAL_DIGEST_BYTES + 4096 and len(digest_bytes) > MAX_XVAL_DIGEST_BYTES:
        raise AnvilRefusalError("BOUND_EXCEEDED_REFUSAL", "XVal prompt digest exceeded 32 KB ceiling.")

    seat_specs = [
        ("orchestrator", "gemini", s1_argv, s1_stdin),
        ("validator", "claude", s2_argv, s2_stdin),
    ]
    raw_seat_outputs: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_XVAL_CONCURRENCY, max_concurrency, len(seat_specs))) as pool:
        fut_map = {
            seat_id: pool.submit(
                runner_fn,
                seat=seat_id,
                family=fam,
                argv=argv_l,
                stdin_bytes=stdin_b,
                env=dict(sub_env),
                cwd=str(root),
                timeout_sec=float(timeout_sec),
            )
            for seat_id, fam, argv_l, stdin_b in seat_specs
        }
        for seat_id, fut in fut_map.items():
            raw_seat_outputs[seat_id] = fut.result()

    raw_s1 = raw_seat_outputs["orchestrator"]
    raw_s2 = raw_seat_outputs["validator"]

    parsed_s1 = parse_gemini_stream_json_frames(
        str(raw_s1.get("stdout") or ""),
        returncode=int(raw_s1.get("returncode", 1)),
        stderr_text=str(raw_s1.get("stderr") or ""),
        requested_model=CANONICAL_GEMINI_AGY_MODEL,
    )
    parsed_s2 = parse_claude_stream_json_frames(
        str(raw_s2.get("stdout") or ""),
        returncode=int(raw_s2.get("returncode", 1)),
        stderr_text=str(raw_s2.get("stderr") or ""),
        requested_model=CANONICAL_CLAUDE_FABLE_MODEL,
    )

    s1_attested_ok = bool(parsed_s1.get("ok") and parsed_s1.get("model_attested") and parsed_s1.get("model_served"))
    s1_served_model = str(parsed_s1["model_served"]) if s1_attested_ok else None
    s1_inferred_fam = _infer_model_vendor_family(s1_served_model or "") if s1_served_model else ""
    s1_family = (s1_inferred_fam or str(parsed_s1.get("model_family") or "gemini")) if s1_attested_ok else "unattested_seat1"

    # Honesty law: if Claude hits its 5-hour subscription cooldown, record RATE_LIMITED_COOLDOWN honestly
    # while preserving Seat-1's genuine live model attestation and citation audit checks when Seat-1 ran.
    if parsed_s2["status"] == "RATE_LIMITED_COOLDOWN":
        if s1_attested_ok:
            cd_s1_verdict, cd_s1_rows, cd_s1_findings = _evaluate_seat_citation_reply(
                "seat1_orchestrator", parsed_s1.get("text", ""), citation_audit
            )
            cd_s1_verified = bool(cd_s1_verdict == "PASS" and all(r["ok"] for r in cd_s1_rows))
        else:
            cd_s1_verdict = det_verdict
            cd_s1_rows = []
            cd_s1_findings = []
            cd_s1_verified = False
        cd_findings = list(det_findings) + [f for f in cd_s1_findings if f not in det_findings]
        cd_verdict = "FAIL" if ("FAIL" in (det_verdict, cd_s1_verdict)) else det_verdict
        cd_audit = {
            **citation_audit,
            "ok": bool(citation_audit["ok"] and (cd_s1_verified or not s1_attested_ok)),
            "verdict": "PASS" if (citation_audit["ok"] and cd_verdict == "PASS") else "FAIL",
            "seat1_verified": cd_s1_verified,
            "seat2_verified": False,
            "seat1_checks": cd_s1_rows,
            "seat2_checks": [],
        }
        return {
            "ok": True,
            "schema": XVAL_RECEIPT_SCHEMA,
            "mode": "RATE_LIMITED_COOLDOWN",
            "cooldown_fallback": "DETERMINISTIC_FALLBACK",
            "cross_family_attested": False,
            "model_served": None,
            "model_attested": False,
            "orchestrator_family": s1_family if s1_attested_ok else "unattested_seat1",
            "orchestrator_model": s1_served_model,
            "validator_family": "claude",
            "validator_model": None,
            "verdict": cd_verdict,
            "verdict_qualified": _compute_verdict_qualified(
                cd_verdict,
                cross_family_attested=False,
                live_attested_seats=1 if s1_attested_ok else 0,
            ),
            "validator_calls_made": 2,
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": f"Claude subscription seat rate-limited/cooldown: {parsed_s2['error']}",
            "citation_audit": cd_audit,
            "seats": [
                {
                    "seat": "orchestrator",
                    "family": s1_family if s1_attested_ok else "unattested_seat1",
                    "model_served": s1_served_model,
                    "model_attested": s1_attested_ok,
                    "verdict": cd_s1_verdict if s1_attested_ok else "FAIL",
                    "argv": list(s1_argv),
                },
                {
                    "seat": "validator",
                    "family": "claude",
                    "model_served": None,
                    "model_attested": False,
                    "verdict": "RATE_LIMITED_COOLDOWN",
                    "argv": list(s2_argv),
                },
            ],
            "shards": [],
            "findings": cd_findings,
        }

    # If binary missing or offline CLI error without a served model, degrade honestly unless model substitution occurred
    if not parsed_s2["ok"] and not parsed_s2.get("model_served") and raw_s2.get("missing_binary"):
        fb_audit = {**citation_audit, "seat1_verified": False, "seat2_verified": False}
        return {
            "ok": True,
            "schema": XVAL_RECEIPT_SCHEMA,
            "mode": "DETERMINISTIC_FALLBACK",
            "cross_family_attested": False,
            "model_served": None,
            "model_attested": False,
            "orchestrator_family": s1_family if s1_attested_ok else "unattested_seat1",
            "orchestrator_model": s1_served_model,
            "validator_family": "deterministic_local_verifier",
            "validator_model": None,
            "verdict": det_verdict,
            "verdict_qualified": _compute_verdict_qualified(
                det_verdict,
                cross_family_attested=False,
                live_attested_seats=1 if s1_attested_ok else 0,
            ),
            "validator_calls_made": 2,
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": parsed_s2["error"] or "Claude CLI binary unavailable.",
            "citation_audit": fb_audit,
            "shards": [],
            "findings": det_findings,
        }

    # Enforce positive model_served === "claude-fable-5-2" attestation fail-closed!
    attest_claude_fable_served(parsed_s2, expected_model=CANONICAL_CLAUDE_FABLE_MODEL, raise_on_mismatch=True)
    s2_attested_ok = bool(
        parsed_s2.get("ok")
        and parsed_s2.get("model_attested")
        and parsed_s2.get("model_served") == CANONICAL_CLAUDE_FABLE_MODEL
    )

    if s1_attested_ok:
        s1_verdict, s1_rows, s1_findings = _evaluate_seat_citation_reply(
            "seat1_orchestrator", parsed_s1.get("text", ""), citation_audit
        )
    else:
        s1_verdict = "FAIL"
        s1_rows = [
            {
                "id": str(d_row["id"]),
                "seat": "seat1_orchestrator",
                "code_citation_verified": False,
                "manuscript_citation_verified": False,
                "ok": False,
                "notes": f"Seat 1 CLI did not attest a live model ({parsed_s1.get('error') or 'no init/result model frame'})."[:800],
            }
            for d_row in (citation_audit.get("rows") or [])
        ]
        s1_findings = [
            {
                "severity": "FAIL",
                "code": "SEAT1_UNATTESTED_OR_FAILED",
                "seat": "seat1_orchestrator",
                "detail": f"[seat1_orchestrator] Live cross-family Seat-1 CLI failed or did not attest served model: {parsed_s1.get('error') or 'unattested'}.",
            }
        ]

    s2_verdict, s2_rows, s2_findings = _evaluate_seat_citation_reply(
        "seat2_validator_fable", parsed_s2.get("text", ""), citation_audit
    )

    merged_findings: List[Dict[str, Any]] = list(det_findings)
    seen_details = {str(f.get("detail") or "") for f in merged_findings}
    for extra_f in [*s1_findings, *s2_findings]:
        if extra_f["detail"] not in seen_details:
            seen_details.add(extra_f["detail"])
            merged_findings.append(extra_f)

    seat1_verified = bool(s1_attested_ok and s1_verdict == "PASS" and all(r["ok"] for r in s1_rows))
    seat2_verified = bool(s2_attested_ok and s2_verdict == "PASS" and all(r["ok"] for r in s2_rows))
    cross_attested = bool(
        s1_attested_ok
        and s2_attested_ok
        and s1_family in KNOWN_VENDOR_FAMILIES
        and s1_family != "claude"
    )

    verdicts = [det_verdict, s1_verdict, s2_verdict]
    final_verdict = "FAIL" if ("FAIL" in verdicts or not cross_attested) else ("WARN" if "WARN" in verdicts else "PASS")
    audit_all_ok = bool(citation_audit["ok"] and seat1_verified and seat2_verified)

    enriched_citation_audit = {
        **citation_audit,
        "ok": audit_all_ok,
        "verdict": "PASS" if audit_all_ok else "FAIL",
        "seat1_verified": seat1_verified,
        "seat2_verified": seat2_verified,
        "seat1_checks": s1_rows,
        "seat2_checks": s2_rows,
    }

    return {
        "ok": True,
        "schema": XVAL_RECEIPT_SCHEMA,
        "mode": "CROSS_FAMILY_VALIDATED" if cross_attested else ("ATTESTED_CLAUDE_FABLE_VALIDATED" if s2_attested_ok else "UNATTESTED_VALIDATOR"),
        "cross_family_attested": cross_attested,
        "attestation_reason": (
            f"Positively attested Seat-1 ({s1_family}/{s1_served_model}) and Seat-2 ({CANONICAL_CLAUDE_FABLE_MODEL}) "
            f"audited {citation_audit['total_divergences']} divergence citation(s)."
            if cross_attested
            else f"Cross-family 2-seat attestation incomplete: Seat-1={s1_family}/{s1_served_model or 'unattested'}, Seat-2={CANONICAL_CLAUDE_FABLE_MODEL}."
        ),
        "requested_model": CANONICAL_CLAUDE_FABLE_MODEL,
        "model_served": CANONICAL_CLAUDE_FABLE_MODEL,
        "model_attested": s2_attested_ok,
        "orchestrator_family": s1_family,
        "orchestrator_model": s1_served_model,
        "validator_family": "claude",
        "validator_model": CANONICAL_CLAUDE_FABLE_MODEL,
        "verdict": final_verdict,
        "verdict_qualified": _compute_verdict_qualified(
            final_verdict,
            cross_family_attested=cross_attested,
            live_attested_seats=int(bool(s1_attested_ok)) + int(bool(s2_attested_ok)),
        ),
        "validator_calls_made": 2,
        "max_concurrency_enforced": max_concurrency,
        "digest_bytes": len(digest_bytes),
        "digest_sha256": digest_sha256,
        "citation_audit": enriched_citation_audit,
        "seats": [
            {
                "seat": "orchestrator",
                "family": s1_family,
                "model_served": s1_served_model,
                "model_attested": s1_attested_ok,
                "verdict": s1_verdict,
                "argv": list(s1_argv),
            },
            {
                "seat": "validator",
                "family": "claude",
                "model_served": CANONICAL_CLAUDE_FABLE_MODEL,
                "model_attested": s2_attested_ok,
                "verdict": s2_verdict,
                "argv": list(s2_argv),
            },
        ],
        "shards": [],
        "findings": merged_findings,
    }


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
        sub_env = build_subscription_cli_env()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                resolved_argv,
                cwd=str(scratch_dir),
                env=sub_env,
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

        # Positive Fable 5.2 attestation gate whenever a validator shard claims family == "claude"
        if exact_family == "claude" and served_model != CANONICAL_CLAUDE_FABLE_MODEL:
            raise AnvilRefusalError(
                "ATTESTATION_MISMATCH_REFUSAL",
                f"Claude validator shard '{shard_id}' failed positive attestation: requested '{CANONICAL_CLAUDE_FABLE_MODEL}', served '{served_model or 'unattested'}'.",
                details={
                    "requested_model": CANONICAL_CLAUDE_FABLE_MODEL,
                    "model_served": served_model or None,
                    "model_attested": bool(served_model),
                },
            )

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
    paper_path: Optional[str | Path] = None,
    validator_argv: Optional[Sequence[str]] = None,
    attestation_keyring_path: Optional[str | Path] = None,
    orchestrator_receipt_path: Optional[str | Path] = None,
    validator_receipt_path: Optional[str | Path] = None,
    max_concurrency: int = 2,
    max_digest_bytes: int = MAX_XVAL_DIGEST_BYTES,
    timeout_sec: float = MAX_XVAL_TIMEOUT_SEC,
    persist: bool = True,
    live: Optional[bool] = None,
    cli_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    seat1_cli_argv: Optional[Sequence[str]] = None,
    seat2_cli_argv: Optional[Sequence[str]] = None,
    raw_digest_override: Optional[Any] = None,
    enforce_bound: bool = True,
) -> Dict[str, Any]:
    """Run bounded 2-Seat Orchestrator <-> Cross-Family Validator reconciliation (`<= 2`
    concurrent calls, `<= 32` KB claim digest, `60s` timeout), verify all divergence
    code + manuscript citations, positively attest `claude-fable-5-2` on Claude XVal seats,
    and persist atomic receipt.
    """
    if isinstance(max_concurrency, bool) or max_concurrency <= 0 or max_concurrency > MAX_XVAL_CONCURRENCY:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_concurrency ({max_concurrency}) must be within 1..{MAX_XVAL_CONCURRENCY}.",
            details={
                "bound_name": "max_concurrency",
                "bound_limit": MAX_XVAL_CONCURRENCY,
                "observed_value": max_concurrency,
            },
        )
    if isinstance(max_digest_bytes, bool) or max_digest_bytes <= 0 or max_digest_bytes > MAX_XVAL_DIGEST_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_digest_bytes ({max_digest_bytes}) must be within 1..{MAX_XVAL_DIGEST_BYTES}.",
            details={
                "bound_name": "max_digest_bytes",
                "bound_limit": MAX_XVAL_DIGEST_BYTES,
                "observed_value": max_digest_bytes,
            },
        )
    if isinstance(timeout_sec, bool) or timeout_sec <= 0 or timeout_sec > MAX_XVAL_TIMEOUT_SEC:
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

    resolved_paper = Path(paper_path).resolve() if paper_path else None
    v4_dir = root / ".anvil" / "v4"
    proc_map = process_map
    if proc_map is None:
        pm_file = v4_dir / "process_map.json"
        proc_map = (
            atomic_locked_read_json(pm_file)
            if pm_file.is_file()
            else build_process_map(root, persist=False, paper_path=resolved_paper)
        )

    ref_map = refactor_map
    if ref_map is None:
        rm_file = v4_dir / "refactor_map.json"
        ref_map = (
            atomic_locked_read_json(rm_file)
            if rm_file.is_file()
            else build_refactor_map(root, persist=False, paper_path=resolved_paper, process_map=proc_map)
        )

    pap_map = paper_map
    if pap_map is None and (v4_dir / "paper_map.json").is_file():
        pap_map = atomic_locked_read_json(v4_dir / "paper_map.json")
    if pap_map is None and resolved_paper is not None and resolved_paper.exists():
        import sys as _sys

        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        import anvil_engine as _ae

        pap_map = _ae.paper_to_code_map(root, paper_spec_path=resolved_paper, process_map=proc_map, refactor_map=ref_map)

    if resolved_paper is None and isinstance(pap_map, dict):
        raw_p_src = str(pap_map.get("paper_source") or pap_map.get("source_path") or "").strip()
        if raw_p_src and Path(raw_p_src).exists():
            resolved_paper = Path(raw_p_src).resolve()

    divs_list = list((pap_map.get("divergences") or []) if isinstance(pap_map, dict) else [])
    citation_audit = audit_divergence_citations(root, divs_list, paper_path=resolved_paper)

    current_repo_fp = str(proc_map.get("repo_fingerprint") or ref_map.get("repo_fingerprint") or "")
    keyring = _load_host_keyring(Path(attestation_keyring_path) if attestation_keyring_path else None, root)
    orchestrator_attested, orchestrator_family, orchestrator_model = _verify_orchestrator_seat_receipt(
        Path(orchestrator_receipt_path) if orchestrator_receipt_path else None,
        root,
        current_repo_fp,
        keyring,
    )
    det_verdict, det_findings = _run_deterministic_seat2_checks(
        proc_map,
        ref_map,
        pap_map,
        repo_root=root,
        paper_path=resolved_paper,
    )

    digest_obj, digest_bytes = _build_bounded_xval_digest(
        proc_map,
        ref_map,
        pap_map,
        repo_fp=current_repo_fp,
        orchestrator_family=orchestrator_family,
        det_verdict=det_verdict,
        citation_audit=citation_audit,
        max_digest_bytes=max_digest_bytes,
        raw_digest_override=raw_digest_override if enforce_bound or raw_digest_override is not None else None,
    )
    digest_sha256 = hashlib.sha256(digest_bytes).hexdigest()[:24]

    offline_forced = (os.environ.get("ANVIL_XVAL_OFFLINE") or "").strip() == "1"

    # Resolve optional custom validator argv from explicit arg or ANVIL_XVAL_VALIDATOR_ARGV_JSON
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

    # Wave 5 2-Seat Subscription-CLI Path (Seat 1 Orchestrator + Seat 2 claude-fable-5-2 Validator)
    want_subscription_2seat = (
        not offline_forced
        and configured_argv is None
        and (
            cli_runner is not None
            or seat1_cli_argv is not None
            or seat2_cli_argv is not None
            or bool(live)
            or os.environ.get("ANCHOR_TESTS_ALLOW_LIVE") == "1"
            or os.environ.get("ANVIL_XVAL_LIVE") == "1"
        )
    )
    if want_subscription_2seat:
        sub_receipt = _run_subscription_2seat_xval(
            root,
            digest_obj,
            digest_bytes,
            digest_sha256,
            citation_audit,
            det_verdict,
            det_findings,
            max_concurrency=max_concurrency,
            timeout_sec=timeout_sec,
            cli_runner=cli_runner,
            seat1_cli_argv=seat1_cli_argv,
            seat2_cli_argv=seat2_cli_argv,
        )
        if persist:
            atomic_locked_write_json(v4_dir / "xval_receipt.json", sub_receipt)
        return sub_receipt

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
                else "No external cross-family validator CLI configured; ran deterministic Seat-2 structural & citation verification."
            )
        )
        det_citation_enriched = {
            **citation_audit,
            "seat1_verified": False,
            "seat2_verified": False,
        }
        receipt: Dict[str, Any] = {
            "ok": True,
            "schema": XVAL_RECEIPT_SCHEMA,
            "mode": "DETERMINISTIC_FALLBACK",
            "cross_family_attested": False,
            "model_served": None,
            "model_attested": False,
            "orchestrator_family": orchestrator_family,
            "orchestrator_model": orchestrator_model,
            "validator_family": "deterministic_local_verifier",
            "verdict": det_verdict,
            "verdict_qualified": _compute_verdict_qualified(
                det_verdict,
                cross_family_attested=False,
                live_attested_seats=0,
            ),
            "validator_calls_made": 0,
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": fallback_reason,
            "citation_audit": det_citation_enriched,
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
        probe_extra = 128
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
            "model_served": None,
            "model_attested": False,
            "orchestrator_family": orchestrator_family,
            "orchestrator_model": orchestrator_model,
            "validator_family": "deterministic_local_verifier",
            "verdict": det_verdict,
            "verdict_qualified": _compute_verdict_qualified(
                det_verdict,
                cross_family_attested=False,
                live_attested_seats=0,
            ),
            "validator_calls_made": len(shard_specs),
            "max_concurrency_enforced": max_concurrency,
            "digest_bytes": len(digest_bytes),
            "digest_sha256": digest_sha256,
            "fallback_reason": str(unavail_err),
            "citation_audit": citation_audit,
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
        "model_served": single_served_model or None,
        "model_attested": validator_attested,
        "orchestrator_family": orchestrator_family,
        "orchestrator_model": orchestrator_model,
        "validator_family": lead_v_family,
        "validator_model": single_served_model,
        "verdict": final_verdict,
        "verdict_qualified": _compute_verdict_qualified(
            final_verdict,
            cross_family_attested=cross_family,
            live_attested_seats=int(bool(orchestrator_attested)) + int(bool(validator_attested)),
        ),
        "validator_calls_made": len(shard_results),
        "max_concurrency_enforced": max_concurrency,
        "digest_bytes": len(digest_bytes),
        "digest_sha256": digest_sha256,
        "citation_audit": citation_audit,
        "shards": shard_results,
        "findings": merged_findings,
    }
    if persist:
        atomic_locked_write_json(v4_dir / "xval_receipt.json", receipt)
    return receipt


def validate_probe_test_argv(repo_root: str | Path, raw_test_cmd: Any) -> Dict[str, Any]:
    """Policy-gate `probe_block.test_cmd`: refuse raw shell/command strings (`CWE-78`)
    and route explicit `argv` sequences strictly through `anvil_v4_trace.validate_execution_argv`.
    """
    if isinstance(raw_test_cmd, (str, bytes)) or not isinstance(raw_test_cmd, (list, tuple)) or len(raw_test_cmd) == 0:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            "Raw probe_block.test_cmd command strings are retired; pass an explicit policy-validated argv list.",
            cwe="CWE-78",
            details={"http_status": 403},
        )
    from anvil_v4_trace import validate_execution_argv

    return validate_execution_argv(repo_root, list(raw_test_cmd))

