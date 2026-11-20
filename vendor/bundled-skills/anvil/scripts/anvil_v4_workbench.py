#!/usr/bin/env python3
"""Anvil v4 Wave 3 — Production Loopback Workbench Server, 5-State Surface Contract,
Capability-Token + Nonce-CSP Security Gate, Atomic Session Store, and Standalone
HTML Exporter (`scripts/anvil_v4_workbench.py`).
"""
from __future__ import annotations

import ast
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

from anvil_v4_process import (
    AnvilRefusalError,
    _is_link_or_junction,
    _parse_strict_json_bytes,
    _scan_contained_source_files,
    atomic_locked_read_json,
    atomic_locked_write_json,
    build_process_map,
    exclusive_file_lock,
    load_validated_trace_json,
    resolve_contained_path,
)
from anvil_v4_refactor import (
    PROFILE_LIT_SCHEMA,
    build_refactor_map,
    run_profile_and_literature,
)
from anvil_v4_trace import (
    ISOLATION_BOUNDARY,
    NON_VM_TRUST_WARNING,
    run_consented_trace,
    validate_execution_argv,
)
from anvil_v4_xval import (
    XVAL_RECEIPT_SCHEMA,
    run_xval_audit,
)

WORKBENCH_BUNDLE_SCHEMA = "anvil-v4-workbench-bundle/v1"
WORKBENCH_SESSION_SCHEMA = "anvil-v4-workbench-session/v1"

RESERVED_ANCHOR_PORT = 8777
MAX_POST_BYTES = 262_144
MAX_SOURCE_BUNDLE_BYTES = 2_097_152

FIVE_VARIABLE_SCOPES: Tuple[str, ...] = (
    "function_locals",
    "closure_nonlocals",
    "instance_attrs",
    "module_globals",
    "stage_io_contracts",
)

SURFACE_FAILURE_TABLE: Dict[str, Dict[str, Any]] = {
    "dependency-missing": {
        "kind": "dependency-missing",
        "status_kind": "dependency-missing",
        "http_status": 503,
        "badge": "DEGRADED_STATIC",
        "message": "Required runtime/tracer unavailable — showing static AST map",
    },
    "dependency-slow-or-killed": {
        "kind": "dependency-slow-or-killed",
        "status_kind": "dependency-slow-or-killed",
        "http_status": 504,
        "badge": "TIMEOUT_PARTIAL",
        "message": "Trace subprocess timed out or was terminated — partial trace preserved",
    },
    "dependency-returns-garbage": {
        "kind": "dependency-returns-garbage",
        "status_kind": "dependency-returns-garbage",
        "http_status": 502,
        "badge": "REJECTED_GARBAGE",
        "message": "Malformed trace/validator payload — rejected fail-closed",
    },
    "backing-store-unreadable": {
        "kind": "backing-store-unreadable",
        "status_kind": "backing-store-unreadable",
        "http_status": 500,
        "badge": "UNKNOWN",
        "message": "Session/trace store unreadable (unknown state, not empty)",
    },
    "empty-but-valid": {
        "kind": "empty-but-valid",
        "status_kind": "empty-but-valid",
        "http_status": 200,
        "badge": "EMPTY",
        "message": "Repository parsed cleanly with 0 matched items",
    },
}

_PY_KEYWORDS: Set[str] = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "int", "float", "str", "bool", "dict", "list", "tuple", "set", "Optional",
    "Any", "Dict", "List", "Tuple", "Sequence", "Path", "len", "range", "max",
    "min", "sum", "abs", "round", "isinstance", "getattr", "setattr", "hasattr",
    "function", "const", "let", "var", "export", "default", "typeof", "new",
}


def _escape_json_for_html_script(payload: Dict[str, Any]) -> str:
    """Serialize `payload` as strict JSON with `</` and `<!--` escaped so inline
    `<script type="application/json">` breakout is impossible.
    """
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return raw.replace("</", "<\\/").replace("<!--", "<\\!--")


def _build_csp_header(csp_nonce: str) -> str:
    return (
        "default-src 'none'; "
        f"script-src 'self' 'nonce-{csp_nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'none'"
    )


def _format_sketch_summary(sketch: Any) -> Tuple[str, str, bool]:
    """Return `(type_shape_str, value_summary_str, has_nonfinite)` from a trace sketch."""
    if not isinstance(sketch, dict):
        s = str(sketch)[:80]
        nf = any(tok in s for tok in ("NaN", "+Infinity", "-Infinity"))
        return ("scalar", s, nf)
    kind = str(sketch.get("kind") or sketch.get("type") or "value")
    nfs = sketch.get("non_finite") or []
    has_nf = bool(nfs)
    if "non_finite_flag" in sketch and sketch["non_finite_flag"]:
        has_nf = True
    if kind in {"float", "int", "bool", "str", "NoneType", "scalar"}:
        val_s = str(sketch.get("value", sketch.get("preview", "")))
        if sketch.get("non_finite_value"):
            val_s = str(sketch["non_finite_value"])
            has_nf = True
        if any(tok in val_s for tok in ("NaN", "+Infinity", "-Infinity")):
            has_nf = True
        return (kind, val_s[:96], has_nf)
    if "shape" in sketch:
        shp = sketch.get("shape")
        shp_s = f"[{','.join(str(x) for x in shp)}]" if isinstance(shp, list) else str(shp)
        dtype_s = str(sketch.get("dtype") or kind)
        stats_parts: List[str] = []
        for k in ("min", "mean", "max", "head"):
            if k in sketch and sketch[k] is not None:
                stats_parts.append(f"{k}={sketch[k]}")
        if nfs:
            stats_parts.insert(0, f"non_finite={','.join(str(x) for x in nfs)}")
        val_s = ", ".join(stats_parts) if stats_parts else f"size={sketch.get('size', '?')}"
        return (f"{dtype_s}{shp_s}", val_s[:110], has_nf)
    if "len" in sketch:
        l_val = sketch.get("len", 0)
        sample = sketch.get("sample_keys") or sketch.get("head") or sketch.get("preview") or ""
        sample_s = json.dumps(sample, ensure_ascii=False)[:72] if sample != "" else ""
        val_s = f"len={l_val}" + (f" · {sample_s}" if sample_s else "")
        if nfs:
            val_s = f"non_finite={','.join(str(x) for x in nfs)} · {val_s}"
        return (f"{kind}[{l_val}]", val_s[:110], has_nf)
    compact = json.dumps(sketch, ensure_ascii=False)[:96]
    if any(tok in compact for tok in ("NaN", "+Infinity", "-Infinity")):
        has_nf = True
    return (kind, compact, has_nf)


def _raise_backing_store_unreadable(reason: str) -> None:
    row = SURFACE_FAILURE_TABLE["backing-store-unreadable"]
    raise AnvilRefusalError(
        "BACKING_STORE_UNREADABLE",
        row["message"],
        details={
            "status_kind": row["status_kind"],
            "http_status": row["http_status"],
            "badge": row["badge"],
            "reason": reason,
        },
    )


def _probe_v4_store_dir(root: Path) -> Path:
    v4_dir = root / ".anvil" / "v4"
    try:
        if _is_link_or_junction(v4_dir):
            _raise_backing_store_unreadable(".anvil/v4 is a symlink or junction")
        if v4_dir.exists():
            if not v4_dir.is_dir():
                _raise_backing_store_unreadable(".anvil/v4 exists as a non-directory file")
            _ = list(os.scandir(v4_dir))
    except AnvilRefusalError:
        raise
    except OSError as exc:
        _raise_backing_store_unreadable(f"Cannot inspect .anvil/v4 directory: {exc}")
    return v4_dir


def _load_optional_trace_store(root: Path) -> Optional[Dict[str, Any]]:
    """Load `<root>/.anvil/v4/last_trace.json` if present, strictly distinguishing
    unreadable backing store (`BACKING_STORE_UNREADABLE` / 500) from corrupt trace
    payload (`MALFORMED_DATA_REFUSED` / 502), and NEVER silently treating either as empty.
    """
    v4_dir = _probe_v4_store_dir(root)
    trace_path = v4_dir / "last_trace.json"
    try:
        if _is_link_or_junction(trace_path):
            _raise_backing_store_unreadable("last_trace.json is a symlink or junction")
        exists = trace_path.exists()
    except AnvilRefusalError:
        raise
    except OSError as exc:
        _raise_backing_store_unreadable(f"Cannot stat last_trace.json: {exc}")
        return None

    if not exists:
        return None

    try:
        if not trace_path.is_file():
            _raise_backing_store_unreadable("last_trace.json is not a regular file")
        return load_validated_trace_json(trace_path)
    except AnvilRefusalError as err:
        if err.error_code in {"BACKING_STORE_UNREADABLE", "LOCK_TIMEOUT_REFUSED"}:
            _raise_backing_store_unreadable(err.message)
        if err.error_code == "MALFORMED_DATA_REFUSED":
            row = SURFACE_FAILURE_TABLE["dependency-returns-garbage"]
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                row["message"],
                cwe="CWE-502",
                details={
                    "status_kind": row["status_kind"],
                    "http_status": row["http_status"],
                    "badge": row["badge"],
                    "reason": err.message,
                },
            ) from err
        raise
    except OSError as exc:
        _raise_backing_store_unreadable(f"Cannot read last_trace.json: {exc}")
        return None


def _default_session_payload(process_map: Dict[str, Any]) -> Dict[str, Any]:
    stages = process_map.get("l1_stages") or []
    steps = process_map.get("l2_steps") or []
    l3_files = process_map.get("l3_files") or []
    preferred_step = next(
        (
            s for s in steps
            if isinstance(s.get("code_ref"), dict)
            and s["code_ref"].get("file")
            and not str(s["code_ref"]["file"]).endswith("__init__.py")
        ),
        steps[0] if steps else None,
    )
    first_stage = str(
        (preferred_step.get("stage_id") if isinstance(preferred_step, dict) else None)
        or (stages[0]["id"] if stages else "S1")
    )
    first_step = str(preferred_step["id"]) if isinstance(preferred_step, dict) else "1.1"
    first_file = (
        str(preferred_step["code_ref"]["file"])
        if (isinstance(preferred_step, dict) and isinstance(preferred_step.get("code_ref"), dict) and preferred_step["code_ref"].get("file"))
        else (str(l3_files[0]["file"]) if l3_files else "")
    )
    first_line = (
        int(preferred_step["code_ref"].get("start_line") or 1)
        if (isinstance(preferred_step, dict) and isinstance(preferred_step.get("code_ref"), dict))
        else 1
    )
    return {
        "schema": WORKBENCH_SESSION_SCHEMA,
        "pinned_watches": [],
        "breakpoints": [],
        "active_stage_id": first_stage,
        "active_step_id": first_step,
        "active_file": first_file,
        "active_line": first_line,
        "ide_open": False,
        "ide_theme": "light",
        "active_pipeline": "",
        "dialogue_turns": [],
    }


def _validate_and_normalize_session(raw: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("schema") != WORKBENCH_SESSION_SCHEMA:
        _raise_backing_store_unreadable("Invalid workbench_session.json schema")
    for list_key in ("pinned_watches", "breakpoints", "dialogue_turns"):
        if list_key in raw and not isinstance(raw[list_key], list):
            _raise_backing_store_unreadable(f"Corrupt session field '{list_key}' (expected list)")

    pins = [str(x).strip() for x in (raw.get("pinned_watches") or []) if isinstance(x, str) and x.strip()][:64]
    bps: List[Any] = []
    for bp in (raw.get("breakpoints") or [])[:128]:
        if isinstance(bp, int) and bp >= 1:
            bps.append(bp)
        elif isinstance(bp, str) and bp.strip():
            bps.append(bp.strip()[:160])
        elif isinstance(bp, dict) and isinstance(bp.get("file"), str) and isinstance(bp.get("line"), int):
            bps.append({"file": bp["file"][:160], "line": max(1, int(bp["line"]))})

    turns: List[Dict[str, Any]] = []
    for t in (raw.get("dialogue_turns") or [])[-80:]:
        if isinstance(t, dict) and isinstance(t.get("role"), str) and isinstance(t.get("text"), str):
            turns.append({
                "role": "assistant" if t["role"] == "assistant" else "user",
                "text": t["text"][:4096],
                "stage_id": str(t.get("stage_id") or ""),
                "ts": str(t.get("ts") or ""),
            })

    theme = str(raw.get("ide_theme") or defaults["ide_theme"]).lower()
    if theme not in {"light", "dark"}:
        theme = "light"

    return {
        "schema": WORKBENCH_SESSION_SCHEMA,
        "pinned_watches": list(dict.fromkeys(pins)),
        "breakpoints": bps,
        "active_stage_id": str(raw.get("active_stage_id") or defaults["active_stage_id"])[:32],
        "active_step_id": str(raw.get("active_step_id") or defaults["active_step_id"])[:32],
        "active_file": str(raw.get("active_file") if raw.get("active_file") is not None else defaults["active_file"])[:240],
        "active_line": max(1, int(raw.get("active_line") or defaults["active_line"])),
        "ide_open": bool(raw.get("ide_open", defaults["ide_open"])),
        "ide_theme": theme,
        "active_pipeline": str(raw.get("active_pipeline") or "")[:64],
        "dialogue_turns": turns,
    }


def _load_or_init_workbench_session(
    root: Path,
    process_map: Dict[str, Any],
    *,
    persist: bool = True,
) -> Dict[str, Any]:
    v4_dir = _probe_v4_store_dir(root)
    session_path = v4_dir / "workbench_session.json"
    defaults = _default_session_payload(process_map)

    try:
        if _is_link_or_junction(session_path):
            _raise_backing_store_unreadable("workbench_session.json is a symlink or junction")
        exists = session_path.exists()
    except AnvilRefusalError:
        raise
    except OSError as exc:
        _raise_backing_store_unreadable(f"Cannot stat workbench_session.json: {exc}")
        return defaults

    if exists:
        try:
            if not session_path.is_file():
                _raise_backing_store_unreadable("workbench_session.json is not a regular file")
            loaded = atomic_locked_read_json(session_path, max_bytes=4_194_304)
            return _validate_and_normalize_session(loaded, defaults)
        except AnvilRefusalError as err:
            _raise_backing_store_unreadable(err.message)
        except (OSError, ValueError, TypeError) as exc:
            _raise_backing_store_unreadable(f"Corrupt or unreadable workbench_session.json: {exc}")

    if persist:
        try:
            atomic_locked_write_json(session_path, defaults)
        except (AnvilRefusalError, OSError) as exc:
            _raise_backing_store_unreadable(f"Cannot initialize workbench_session.json: {exc}")
    return defaults


def _extract_watchable_tokens(text: str, ext: str) -> List[str]:
    tokens: List[str] = []
    seen: Set[str] = set()
    if ext == ".py":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                cand = ""
                if isinstance(node, ast.arg):
                    cand = node.arg
                elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Load)):
                    cand = node.id
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                    cand = node.attr
                if (
                    cand
                    and cand not in _PY_KEYWORDS
                    and not cand.startswith("__")
                    and cand not in seen
                    and len(cand) <= 48
                ):
                    seen.add(cand)
                    tokens.append(cand)
                if len(tokens) >= 80:
                    break
            return tokens
        except SyntaxError:
            pass

    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{1,47})\b", text):
        tok = m.group(1)
        if tok not in _PY_KEYWORDS and not tok.startswith("__") and tok not in seen:
            seen.add(tok)
            tokens.append(tok)
        if len(tokens) >= 80:
            break
    return tokens


def _build_files_source_map(
    root: Path,
    process_map: Dict[str, Any],
    trace_data: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    prod_files, test_files = _scan_contained_source_files(root)
    scope_meta = process_map.get("paper_matched_scopes") if isinstance(process_map, dict) else None
    if isinstance(scope_meta, dict) and scope_meta.get("scoped") and scope_meta.get("active_files"):
        allowed_prod = set(scope_meta["active_files"])
        prod_files = [fp for fp in prod_files if fp.relative_to(root).as_posix() in allowed_prod]
    all_files = list(prod_files) + list(test_files)

    file_stage_lookup: Dict[str, List[str]] = {}
    file_first_step: Dict[str, Tuple[str, int]] = {}
    for st in process_map.get("l1_stages") or []:
        sid = str(st.get("id") or "S1")
        for f_rel in st.get("files") or []:
            file_stage_lookup.setdefault(str(f_rel), [])
            if sid not in file_stage_lookup[str(f_rel)]:
                file_stage_lookup[str(f_rel)].append(sid)
        for step in st.get("l2_steps") or []:
            cref = step.get("code_ref") or {}
            cf = str(cref.get("file") or "")
            if cf and cf not in file_first_step:
                file_first_step[cf] = (str(step.get("id") or "1.1"), int(cref.get("start_line") or 1))

    line_hits: Dict[Tuple[str, int], int] = {}
    line_ghosts: Dict[Tuple[str, int], List[str]] = {}
    fault_lines: Set[Tuple[str, int]] = set()
    extra_watch_by_file: Dict[str, List[str]] = {}

    if trace_data:
        for el in trace_data.get("executed_lines") or []:
            if isinstance(el, dict) and isinstance(el.get("file"), str) and isinstance(el.get("line"), int):
                line_hits[(el["file"], int(el["line"]))] = int(el.get("hits", 1))
        for sc_name in FIVE_VARIABLE_SCOPES:
            for rec in (trace_data.get("scopes") or {}).get(sc_name) or []:
                if not isinstance(rec, dict):
                    continue
                rf = str(rec.get("file") or "")
                rln = int(rec.get("line") or 0)
                vname = str(rec.get("name") or "")
                if rf and vname:
                    extra_watch_by_file.setdefault(rf, []).append(vname)
                if rf and rln > 0 and vname:
                    _, val_s, has_nf = _format_sketch_summary(rec.get("sketch"))
                    note = f"{vname} = {val_s}"
                    bucket = line_ghosts.setdefault((rf, rln), [])
                    if len(bucket) < 3 and note not in bucket:
                        bucket.append(note)
                    if has_nf:
                        fault_lines.add((rf, rln))
        for tw in trace_data.get("tripwires") or []:
            if not isinstance(tw, dict):
                continue
            tf = str(tw.get("file") or "")
            tln = int(tw.get("line") or 0)
            tvar = str(tw.get("variable") or "value")
            tkind = str(tw.get("kind") or tw.get("non_finite") or "+Infinity")
            if tf and tln > 0:
                fault_lines.add((tf, tln))
                tw_note = f"TRIPWIRE {tvar} -> {tkind}"
                bucket = line_ghosts.setdefault((tf, tln), [])
                if tw_note not in bucket:
                    bucket.insert(0, tw_note)

    out_map: Dict[str, Dict[str, Any]] = {}
    used_bytes = 0
    for fp in all_files:
        rel_posix = fp.relative_to(root).as_posix()
        try:
            raw_bytes = fp.read_bytes()
        except OSError:
            continue
        if used_bytes + len(raw_bytes) > MAX_SOURCE_BUNDLE_BYTES:
            break
        used_bytes += len(raw_bytes)
        text = raw_bytes.decode("utf-8", errors="replace")
        raw_lines = text.splitlines()
        numbered_pairs = [[idx, ln] for idx, ln in enumerate(raw_lines, start=1)]
        numbered_source = "\n".join(f"{idx:4d} | {ln}" for idx, ln in numbered_pairs)

        wtoks = _extract_watchable_tokens(text, fp.suffix.lower())
        for xw in extra_watch_by_file.get(rel_posix, []):
            if xw not in wtoks:
                wtoks.insert(0, xw)

        step_id, default_ln = file_first_step.get(rel_posix, ("1.1", 1))
        file_fault_lns = sorted(ln for (ff, ln) in fault_lines if ff == rel_posix)
        file_hit_lns = sorted(ln for (hf, ln) in line_hits if hf == rel_posix)
        exec_line = file_fault_lns[0] if file_fault_lns else (file_hit_lns[0] if file_hit_lns else default_ln)

        ghost_dict: Dict[str, Dict[str, Any]] = {}
        for (gf, gln), notes in line_ghosts.items():
            if gf == rel_posix and notes:
                ghost_dict[str(gln)] = {
                    "text": " · ".join(notes[:2]),
                    "fault": (gf, gln) in fault_lines,
                    "hits": line_hits.get((gf, gln), 1),
                }

        sids = file_stage_lookup.get(rel_posix, ["S1"])
        out_map[rel_posix] = {
            "file": rel_posix,
            "stage_id": sids[0] if sids else "S1",
            "stage_ids": sids,
            "step_id": step_id,
            "total_lines": len(raw_lines),
            "exec_line": exec_line,
            "has_fault": bool(file_fault_lns),
            "fault_lines": file_fault_lns,
            "executed_lines": {str(ln): cnt for (hf, ln), cnt in line_hits.items() if hf == rel_posix},
            "watchable_tokens": wtoks[:96],
            "ghost_values": ghost_dict,
            "lines": numbered_pairs,
            "numbered_source": numbered_source,
        }
    return out_map


def _build_smart_funnel_catalog(
    process_map: Dict[str, Any],
    trace_data: Optional[Dict[str, Any]],
    files_source_map: Dict[str, Dict[str, Any]],
    pinned_watches: Sequence[str],
) -> Dict[str, Any]:
    pinned_set = set(pinned_watches or [])
    tripwire_keys: Set[Tuple[str, str]] = set()
    if trace_data:
        for tw in trace_data.get("tripwires") or []:
            if isinstance(tw, dict):
                tripwire_keys.add((str(tw.get("file") or ""), str(tw.get("variable") or "")))

    scopes_out: Dict[str, List[Dict[str, Any]]] = {sc: [] for sc in FIVE_VARIABLE_SCOPES}
    if trace_data and isinstance(trace_data.get("scopes"), dict):
        raw_scopes = trace_data["scopes"]
        for sc in FIVE_VARIABLE_SCOPES:
            for rec in raw_scopes.get(sc) or []:
                if not isinstance(rec, dict):
                    continue
                vname = str(rec.get("name") or "")
                rf = str(rec.get("file") or "")
                rln = int(rec.get("line") or 1)
                sid = str(rec.get("stage_id") or "S1")
                t_shp, val_s, has_nf = _format_sketch_summary(rec.get("sketch"))
                is_anom = has_nf or ((rf, vname) in tripwire_keys)
                is_pin = vname in pinned_set
                scopes_out[sc].append({
                    "key": str(rec.get("key") or f"{sc}:{rf}:{vname}"),
                    "scope": sc,
                    "stage_id": sid,
                    "file": rf,
                    "line": rln,
                    "file_line": f"{rf}:{rln}" if rf else f"line:{rln}",
                    "symbol": str(rec.get("symbol") or ""),
                    "name": vname,
                    "type_shape": t_shp,
                    "value": val_s,
                    "changed": True,
                    "anomaly": is_anom,
                    "pinned": is_pin,
                })
    else:
        # Static AST pre-consent catalog across the 5 scopes
        for st in process_map.get("l1_stages") or []:
            sid = str(st.get("id") or "S1")
            s_files = st.get("files") or []
            lead_f = str(s_files[0]) if s_files else ""
            for inp in (st.get("what_enters") or [])[:6]:
                nm = str(inp)
                scopes_out["stage_io_contracts"].append({
                    "key": f"stage_io_contracts:{sid}:in:{nm}",
                    "scope": "stage_io_contracts",
                    "stage_id": sid,
                    "file": lead_f,
                    "line": 1,
                    "file_line": f"{lead_f}:1" if lead_f else sid,
                    "symbol": sid,
                    "name": nm,
                    "type_shape": "stage_input",
                    "value": "Static AST contract (awaiting consented trace)",
                    "changed": False,
                    "anomaly": False,
                    "pinned": nm in pinned_set,
                })
            for step in st.get("l2_steps") or []:
                cref = step.get("code_ref") or {}
                sf = str(cref.get("file") or lead_f)
                sln = int(cref.get("start_line") or 1)
                sym = str(cref.get("symbol") or "")
                f_entry = files_source_map.get(sf) or {}
                for tok in (f_entry.get("watchable_tokens") or [])[:8]:
                    target_sc = "instance_attrs" if "." in sym else "function_locals"
                    scopes_out[target_sc].append({
                        "key": f"{target_sc}:{sf}:{sym}:{tok}",
                        "scope": target_sc,
                        "stage_id": sid,
                        "file": sf,
                        "line": sln,
                        "file_line": f"{sf}:{sln}" if sf else f"line:{sln}",
                        "symbol": sym,
                        "name": tok,
                        "type_shape": "ast_identifier",
                        "value": "Static AST symbol (run consented trace for live values)",
                        "changed": tok in (step.get("what_exits") or []),
                        "anomaly": False,
                        "pinned": tok in pinned_set,
                    })

    all_items = [it for sc in FIVE_VARIABLE_SCOPES for it in scopes_out[sc]]
    if trace_data and isinstance(trace_data.get("smart_variable_funnel"), dict):
        svf = dict(trace_data["smart_variable_funnel"])
        extra_pin_cnt = sum(1 for it in all_items if it["pinned"] and not it["anomaly"])
        all_cnt = max(int(svf.get("all_state", 0)), len(all_items))
        stg_cnt = min(all_cnt, max(int(svf.get("stage_scope", 0)), extra_pin_cnt))
        dlt_cnt = min(stg_cnt, max(int(svf.get("delta_mutated", 0)), extra_pin_cnt))
        anm_cnt = min(dlt_cnt, int(svf.get("anomalies_and_pinned_watches", 0)) + extra_pin_cnt)
        funnel_summary = {
            "all_state": all_cnt,
            "stage_scope": stg_cnt,
            "delta_mutated": dlt_cnt,
            "anomalies_and_pinned_watches": anm_cnt,
            "monotonic": (all_cnt >= stg_cnt >= dlt_cnt >= anm_cnt),
            "by_stage": svf.get("by_stage") or {},
        }
    else:
        all_cnt = len(all_items)
        first_sid = str((process_map.get("l1_stages") or [{"id": "S1"}])[0]["id"])
        stg_items = [it for it in all_items if it["stage_id"] == first_sid or it["pinned"]]
        dlt_items = [it for it in stg_items if it["changed"] or it["pinned"]]
        anm_items = [it for it in dlt_items if it["anomaly"] or it["pinned"]]
        funnel_summary = {
            "all_state": all_cnt,
            "stage_scope": len(stg_items),
            "delta_mutated": len(dlt_items),
            "anomalies_and_pinned_watches": len(anm_items),
            "monotonic": (all_cnt >= len(stg_items) >= len(dlt_items) >= len(anm_items)),
            "by_stage": {},
        }

    return {
        "scopes": scopes_out,
        "funnel": funnel_summary,
    }


def _load_or_build_profile_lit(root: Path, *, persist: bool = True) -> Dict[str, Any]:
    v4_dir = _probe_v4_store_dir(root)
    prof_path = v4_dir / "profile_lit.json"
    if prof_path.exists():
        try:
            loaded = atomic_locked_read_json(prof_path)
            if loaded.get("schema") == PROFILE_LIT_SCHEMA:
                return loaded
        except AnvilRefusalError as err:
            if err.error_code in {"BACKING_STORE_UNREADABLE", "LOCK_TIMEOUT_REFUSED"}:
                _raise_backing_store_unreadable(err.message)
            raise
    return run_profile_and_literature(root, approve_run=False, persist=persist)


def _load_or_build_xval(
    root: Path,
    process_map: Dict[str, Any],
    refactor_map: Dict[str, Any],
    paper_map: Dict[str, Any],
    *,
    persist: bool = True,
) -> Dict[str, Any]:
    v4_dir = _probe_v4_store_dir(root)
    xval_path = v4_dir / "xval_receipt.json"
    if xval_path.exists():
        try:
            loaded = atomic_locked_read_json(xval_path)
            if loaded.get("schema") == XVAL_RECEIPT_SCHEMA:
                return loaded
        except AnvilRefusalError as err:
            if err.error_code in {"BACKING_STORE_UNREADABLE", "LOCK_TIMEOUT_REFUSED"}:
                _raise_backing_store_unreadable(err.message)
            raise
    return run_xval_audit(
        root,
        process_map=process_map,
        refactor_map=refactor_map,
        paper_map=paper_map if paper_map.get("has_paper") else None,
        persist=persist,
    )


def _load_paper_map(
    root: Path,
    paper_path: Optional[str | Path],
    trace_data: Optional[Dict[str, Any]],
    *,
    pipeline_id: Optional[str] = None,
) -> Dict[str, Any]:
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import anvil_engine

    return anvil_engine.paper_to_code_map(
        root,
        paper_spec_path=paper_path,
        pipeline_id=pipeline_id,
        trace_data=trace_data,
        approve_run=False,
    )


def build_workbench_bundle(
    repo_dir: str | Path,
    paper_path: Optional[str | Path] = None,
    approve_run: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Assemble the unified Anvil v4 Workbench payload across all 6 pillars,
    session backing store, L3 source lines + ghost values, and surface state.
    """
    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    trace_data = _load_optional_trace_store(root)
    prelim_map = build_process_map(root, trace_data=trace_data, persist=False, paper_path=paper_path)
    session = _load_or_init_workbench_session(root, prelim_map, persist=persist)
    active_pipe = str(session.get("active_pipeline") or "").strip() or None
    if active_pipe:
        try:
            process_map = build_process_map(root, trace_data=trace_data, persist=persist, paper_path=paper_path, pipeline_id=active_pipe)
        except AnvilRefusalError:
            active_pipe = None
            process_map = prelim_map
            if persist:
                atomic_locked_write_json(root / ".anvil" / "v4" / "process_map.json", process_map)
    else:
        process_map = prelim_map
        if persist:
            atomic_locked_write_json(root / ".anvil" / "v4" / "process_map.json", process_map)
    refactor_map = build_refactor_map(root, trace_data=trace_data, persist=persist, paper_path=paper_path, pipeline_id=active_pipe)
    paper_map = _load_paper_map(root, paper_path, trace_data, pipeline_id=active_pipe)
    profile_lit = _load_or_build_profile_lit(root, persist=persist)
    xval_receipt = _load_or_build_xval(root, process_map, refactor_map, paper_map, persist=persist)
    files_source_map = _build_files_source_map(root, process_map, trace_data)
    variable_catalog = _build_smart_funnel_catalog(
        process_map,
        trace_data,
        files_source_map,
        session.get("pinned_watches") or [],
    )

    l0_list = process_map.get("l0_scenarios") or []
    if l0_list and isinstance(l0_list[0].get("recommended_argv"), list):
        rec_argv = [str(x) for x in l0_list[0]["recommended_argv"]]
    elif files_source_map:
        first_rel = next(iter(files_source_map.keys()))
        ext = Path(first_rel).suffix.lower()
        rbin = "node" if ext in {".js", ".mjs", ".ts"} else ("Rscript" if ext == ".r" else "python")
        rec_argv = [rbin, first_rel]
    else:
        rec_argv = ["pytest", "-q"]

    try:
        resolved_argv = list(validate_execution_argv(root, rec_argv)["validated_argv"])
    except Exception:
        resolved_argv = list(rec_argv)
    safe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", root.name)[:32] or "repo"
    isolated_temp_copy_path = f"$TMPDIR/anvil_v4_trace_{safe_slug}_<ephemeral_worktree>"

    if process_map.get("status_kind") == "empty-but-valid":
        row = SURFACE_FAILURE_TABLE["empty-but-valid"]
        surface_state: Dict[str, Any] = dict(row)
    else:
        surface_state = {
            "kind": "healthy",
            "status_kind": "healthy",
            "http_status": 200,
            "badge": "TRACED" if trace_data is not None else "STATIC_AST",
            "message": (
                "Consented runtime trace overlaid on steady-coordinate process map"
                if trace_data is not None
                else "Zero-execution static AST map ready (click Run Consented Trace to overlay live values)"
            ),
        }

    return {
        "ok": True,
        "schema": WORKBENCH_BUNDLE_SCHEMA,
        "repo_name": root.name,
        "repo_fingerprint": process_map.get("repo_fingerprint", ""),
        "isolation_boundary": ISOLATION_BOUNDARY if trace_data is not None else "static_ast_zero_execution",
        "non_vm_trust_warning": NON_VM_TRUST_WARNING,
        "cli_approve_run": bool(approve_run),
        "has_trace": bool(trace_data is not None),
        "has_paper": bool(paper_map.get("has_paper", False)),
        "recommended_argv": rec_argv,
        "resolved_argv": resolved_argv,
        "isolated_temp_copy_path": isolated_temp_copy_path,
        "surface_state": surface_state,
        "status_kind": surface_state["status_kind"],
        "badge": surface_state["badge"],
        "message": surface_state["message"],
        "process_map": process_map,
        "refactor_map": refactor_map,
        "paper_map": paper_map,
        "scientific_validation": paper_map.get("scientific_validation") if isinstance(paper_map, dict) else None,
        "profile_lit": profile_lit,
        "xval_receipt": xval_receipt,
        "trace_summary": (
            {
                "validated_argv": trace_data.get("validated_argv", []),
                "returncode": trace_data.get("returncode", 0),
                "elapsed_sec": trace_data.get("elapsed_sec", 0.0),
                "tripwires": trace_data.get("tripwires", []),
                "map_drift_edges": trace_data.get("map_drift_edges", []),
                "stage_verdicts": trace_data.get("stage_verdicts", {}),
                "stage_wall_sec": trace_data.get("stage_wall_sec", {}),
                "bounds": trace_data.get("bounds", {}),
                "uncaught_exception": trace_data.get("uncaught_exception"),
            }
            if trace_data is not None
            else None
        ),
        "variable_catalog": variable_catalog,
        "files_source_map": files_source_map,
        "session": session,
    }


def _synthesize_grounded_copilot_reply(
    root: Path,
    bundle: Dict[str, Any],
    question: str,
    active_stage_id: str,
    active_file: str,
    active_line: int,
    ide_open: bool,
) -> Dict[str, Any]:
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import anvil_engine

    proc_map = bundle.get("process_map") or {}
    ref_map = bundle.get("refactor_map") or {}
    pap_map = bundle.get("paper_map") or {}
    var_cat = bundle.get("variable_catalog") or {}
    funnel = var_cat.get("funnel") or {}
    session = bundle.get("session") or {}
    stages = proc_map.get("l1_stages") or []

    matched_stage = next((s for s in stages if s.get("id") == active_stage_id), stages[0] if stages else None)
    sid = str(matched_stage["id"]) if matched_stage else "S1"
    stitle = str(matched_stage.get("title") or sid) if matched_stage else "Empty Repository"
    sfiles = (matched_stage.get("files") or []) if matched_stage else []
    lead_file = active_file or (str(sfiles[0]) if sfiles else "")
    lead_line = max(1, int(active_line or 1))

    target_stages = ref_map.get("target_stages") or []
    mapped_n = [
        str(x.get("target_stage_id"))
        for x in (ref_map.get("mapped_to_new") or [])
        if x.get("old_stage_id") == sid and x.get("target_stage_id")
    ]
    n_ids = list(dict.fromkeys(mapped_n)) or ([str(target_stages[0]["id"])] if target_stages else ["N1"])

    try:
        base_chat = anvil_engine.anvil_chat(root, "inspect", lead_file or sid, question)
        base_note = str(base_chat.get("proactive_recommendation") or "")
    except Exception:
        base_note = ""

    trace_sum = bundle.get("trace_summary") or {}
    tripwires = trace_sum.get("tripwires") or []
    pins = session.get("pinned_watches") or []
    eqs = pap_map.get("equations") or []

    parts: List[str] = [
        f"[Steward Co-Pilot · {'IDE Debugger' if ide_open else '48/52 Workbench'}] "
        f"Stage `{sid}` ({stitle}) -> Refactor Target `{', '.join(n_ids)}`"
        + (f" at `{lead_file}:L{lead_line}`" if lead_file else "")
        + f" — Regarding \"{question.strip()}\":"
    ]
    if matched_stage:
        enters = ", ".join(str(x) for x in (matched_stage.get("what_enters") or [])[:4]) or "none"
        exits = ", ".join(str(x) for x in (matched_stage.get("what_exits") or [])[:4]) or "return"
        parts.append(
            f"Contract: enters `{enters}` -> exits `{exits}` (verdict `{matched_stage.get('verdict', 'STATIC_ONLY')}`)."
        )
    parts.append(
        f"Smart Funnel: `{funnel.get('all_state', 0)} -> {funnel.get('stage_scope', 0)} -> "
        f"{funnel.get('delta_mutated', 0)} -> {funnel.get('anomalies_and_pinned_watches', 0)}` "
        f"(pinned watches: `{', '.join(pins) if pins else 'none'}`)."
    )
    if tripwires:
        tw0 = tripwires[0]
        parts.append(
            f"Tripwire Alert: `{tw0.get('variable', 'val')}` hit `{tw0.get('kind', 'non-finite')}` "
            f"at `{tw0.get('file', lead_file)}:L{tw0.get('line', lead_line)}` in `{tw0.get('stage_id', sid)}`."
        )
    if pap_map.get("has_paper") and eqs:
        eq0 = eqs[0]
        parts.append(
            f"Paper Bridge: `{eq0.get('id', 'eq-1')}` stamped `{eq0.get('verification_stamp', 'STATIC_ALIGNED')}`."
        )
    if base_note:
        parts.append(base_note)

    return {
        "reply": " ".join(parts),
        "cited_stage_id": sid,
        "cited_target_stages": n_ids,
        "cited_file": lead_file,
        "cited_line": lead_line,
    }


def _map_refusal_to_surface_failure(err: AnvilRefusalError) -> Optional[Dict[str, Any]]:
    code_map = {
        "DEPENDENCY_MISSING": "dependency-missing",
        "TRACE_TIMEOUT_REFUSED": "dependency-slow-or-killed",
        "MALFORMED_DATA_REFUSED": "dependency-returns-garbage",
        "BACKING_STORE_UNREADABLE": "backing-store-unreadable",
        "LOCK_TIMEOUT_REFUSED": "backing-store-unreadable",
    }
    sk = str(err.details.get("status_kind") or code_map.get(err.error_code, ""))
    if sk in SURFACE_FAILURE_TABLE:
        return dict(SURFACE_FAILURE_TABLE[sk])
    return None


def _static_workbench_template_path() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "anvil_v4_workbench.html"


def _render_workbench_html_document(bootstrap_payload: Dict[str, Any], csp_nonce: str) -> str:
    tpl_path = _static_workbench_template_path()
    if not tpl_path.is_file():
        raise AnvilRefusalError(
            "DEPENDENCY_MISSING",
            f"Workbench HTML template missing at {tpl_path.name}.",
        )
    html_tpl = tpl_path.read_text(encoding="utf-8")
    escaped_json = _escape_json_for_html_script(bootstrap_payload)
    rendered = html_tpl.replace("__ANVIL_CSP_NONCE__", csp_nonce)
    rendered = rendered.replace("__ANVIL_BOOTSTRAP_JSON__", escaped_json)
    return rendered


def export_workbench_html(
    repo_dir: str | Path,
    out_html_path: str | Path,
    paper_path: Optional[str | Path] = None,
    approve_run: bool = False,
) -> Dict[str, Any]:
    """Export a standalone zero-CDN HTML workbench bundle atomically."""
    root = Path(repo_dir).resolve()
    bundle = build_workbench_bundle(root, paper_path=paper_path, approve_run=approve_run, persist=True)
    csp_nonce = secrets.token_hex(16)
    bootstrap = {
        "mode": "standalone",
        "capability_token": "",
        "cli_approve_run": bool(approve_run),
        "recommended_argv": bundle.get("recommended_argv", []),
        "non_vm_trust_warning": NON_VM_TRUST_WARNING,
        "surface_state": bundle.get("surface_state"),
        "bundle": bundle,
    }
    html_text = _render_workbench_html_document(bootstrap, csp_nonce)
    dest = Path(out_html_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_p: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(dest.parent),
            prefix=f".{dest.name}.tmp.{os.getpid()}.",
            suffix=".html",
            delete=False,
        ) as tf:
            tmp_p = Path(tf.name)
            tf.write(html_text)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(str(tmp_p), str(dest))
    finally:
        if tmp_p is not None and tmp_p.exists():
            try:
                tmp_p.unlink()
            except OSError:
                pass
    return {
        "ok": True,
        "mode": "standalone",
        "out_html": str(dest),
        "bytes_written": len(html_text.encode("utf-8")),
        "repo_fingerprint": bundle.get("repo_fingerprint", ""),
        "has_paper": bundle.get("has_paper", False),
        "has_trace": bundle.get("has_trace", False),
        "status_kind": bundle.get("status_kind", "healthy"),
    }


class AnvilWorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        server_address: Tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        repo_root: Path,
        paper_path: Optional[Path],
        approve_run: bool,
        fault_injection_mode: Optional[str] = None,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.repo_root = repo_root
        self.paper_path = paper_path
        self.approve_run = bool(approve_run)
        self.fault_injection_mode: Optional[str] = fault_injection_mode
        self.capability_token: str = secrets.token_urlsafe(32)
        self.csp_nonce: str = secrets.token_hex(16)
        self.state_lock = threading.RLock()
        self.last_good_bundle: Optional[Dict[str, Any]] = None


def _compute_server_state_response(server: AnvilWorkbenchHTTPServer) -> Tuple[int, Dict[str, Any]]:
    inj = server.fault_injection_mode
    if inj in SURFACE_FAILURE_TABLE:
        row = dict(SURFACE_FAILURE_TABLE[inj])
        if inj == "empty-but-valid":
            empty_bundle = {
                "ok": True,
                "schema": WORKBENCH_BUNDLE_SCHEMA,
                "repo_name": server.repo_root.name,
                "repo_fingerprint": "empty",
                "isolation_boundary": "static_ast_zero_execution",
                "non_vm_trust_warning": NON_VM_TRUST_WARNING,
                "cli_approve_run": server.approve_run,
                "has_trace": False,
                "has_paper": False,
                "recommended_argv": ["pytest", "-q"],
                "surface_state": row,
                "status_kind": row["status_kind"],
                "badge": row["badge"],
                "message": row["message"],
                "process_map": {
                    "ok": True,
                    "status_kind": "empty-but-valid",
                    "message": row["message"],
                    "l0_scenarios": [],
                    "l1_stages": [],
                    "l2_steps": [],
                    "l3_files": [],
                    "edges": [],
                },
                "refactor_map": {
                    "old_stages": [],
                    "target_stages": [],
                    "crosswalk_edges": [],
                    "symbol_conservation": {"total_symbols": 0, "conserved": True},
                    "null_set": {"null_proven": [], "null_unexercised": [], "null_redundant": []},
                },
                "paper_map": {"has_paper": False, "sections": [], "algorithms": [], "equations": []},
                "profile_lit": {
                    "stage_hotspots": [],
                    "imperative_shell_io_fixes": [],
                    "functional_core_kernel_upgrades": [],
                    "rejected_kernel_upgrades": [],
                },
                "xval_receipt": {"mode": "DETERMINISTIC_FALLBACK", "cross_family_attested": False, "verdict": "PASS", "findings": []},
                "trace_summary": None,
                "variable_catalog": {
                    "scopes": {sc: [] for sc in FIVE_VARIABLE_SCOPES},
                    "funnel": {"all_state": 0, "stage_scope": 0, "delta_mutated": 0, "anomalies_and_pinned_watches": 0, "monotonic": True},
                },
                "files_source_map": {},
                "session": _default_session_payload({"l1_stages": [], "l2_steps": [], "l3_files": []}),
            }
            return (200, empty_bundle)

        fallback_bundle: Optional[Dict[str, Any]] = None
        if inj in {"dependency-missing", "dependency-slow-or-killed"}:
            fallback_bundle = server.last_good_bundle
            if fallback_bundle is None:
                try:
                    fallback_bundle = build_workbench_bundle(
                        server.repo_root, paper_path=server.paper_path, approve_run=server.approve_run, persist=False
                    )
                except Exception:
                    fallback_bundle = None
        return (
            int(row["http_status"]),
            {
                "ok": False,
                "error_code": inj.upper().replace("-", "_"),
                "status_kind": row["status_kind"],
                "http_status": row["http_status"],
                "badge": row["badge"],
                "message": row["message"],
                "unknown_state": inj == "backing-store-unreadable",
                "surface_state": row,
                "bundle": fallback_bundle,
            },
        )

    try:
        bundle = build_workbench_bundle(
            server.repo_root,
            paper_path=server.paper_path,
            approve_run=server.approve_run,
            persist=True,
        )
        server.last_good_bundle = bundle
        return (200, bundle)
    except AnvilRefusalError as err:
        surf = _map_refusal_to_surface_failure(err)
        if surf is not None:
            preserved = server.last_good_bundle if surf["status_kind"] in {"dependency-missing", "dependency-slow-or-killed"} else None
            return (
                int(surf["http_status"]),
                {
                    "ok": False,
                    "error_code": err.error_code,
                    "status_kind": surf["status_kind"],
                    "http_status": surf["http_status"],
                    "badge": surf["badge"],
                    "message": surf["message"],
                    "unknown_state": surf["status_kind"] == "backing-store-unreadable",
                    "surface_state": surf,
                    "bundle": preserved,
                },
            )
        return (400, err.to_dict())


class _WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server: AnvilWorkbenchHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_security_headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Content-Security-Policy", _build_csp_header(self.server.csp_nonce))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(int(status_code))
        self._send_security_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html_text: str) -> None:
        body = html_text.encode("utf-8")
        self.send_response(int(status_code))
        self._send_security_headers("text/html; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _verify_capability_token(self) -> bool:
        provided = self.headers.get("X-Anvil-Capability", "")
        if not isinstance(provided, str) or not provided:
            return False
        return hmac.compare_digest(provided.encode("utf-8"), self.server.capability_token.encode("utf-8"))

    def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, Dict[str, Any]]]]:
        raw_cl = self.headers.get("Content-Length")
        if raw_cl is None:
            return None, (
                400,
                {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "Missing Content-Length header."},
            )
        try:
            cl = int(raw_cl)
        except ValueError:
            return None, (
                400,
                {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "Invalid Content-Length header."},
            )
        if cl < 0 or cl > MAX_POST_BYTES:
            return None, (
                413 if cl > MAX_POST_BYTES else 400,
                {
                    "ok": False,
                    "error_code": "BOUND_EXCEEDED_REFUSAL",
                    "message": f"Request body length ({cl}) exceeds MAX_POST_BYTES={MAX_POST_BYTES}.",
                    "bound_name": "max_post_bytes",
                    "bound_limit": MAX_POST_BYTES,
                    "observed_value": cl,
                },
            )
        raw_bytes = self.rfile.read(cl) if cl > 0 else b""
        try:
            parsed = _parse_strict_json_bytes(raw_bytes, max_bytes=MAX_POST_BYTES)
            return parsed, None
        except AnvilRefusalError as err:
            code = 413 if err.error_code == "BOUND_EXCEEDED_REFUSAL" else 400
            return None, (code, err.to_dict())

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if route in {"/", "/index.html"}:
            with self.server.state_lock:
                http_code, state_obj = _compute_server_state_response(self.server)
            is_healthy_or_empty = bool(state_obj.get("ok", False))
            active_bundle = state_obj if is_healthy_or_empty else state_obj.get("bundle")
            surf = state_obj.get("surface_state") or {
                "kind": state_obj.get("status_kind", "healthy"),
                "status_kind": state_obj.get("status_kind", "healthy"),
                "http_status": http_code,
                "badge": state_obj.get("badge", "UNKNOWN"),
                "message": state_obj.get("message", ""),
            }
            rec_argv = (
                active_bundle.get("recommended_argv", ["pytest", "-q"])
                if isinstance(active_bundle, dict)
                else ["pytest", "-q"]
            )
            bootstrap = {
                "mode": "live",
                "capability_token": self.server.capability_token,
                "cli_approve_run": self.server.approve_run,
                "recommended_argv": rec_argv,
                "non_vm_trust_warning": NON_VM_TRUST_WARNING,
                "surface_state": surf,
                "unknown_state": bool(state_obj.get("unknown_state", False)),
                "bundle": active_bundle,
            }
            html_doc = _render_workbench_html_document(bootstrap, self.server.csp_nonce)
            self._send_html(200, html_doc)
            return

        if route == "/api/anvil/v4/state":
            with self.server.state_lock:
                http_code, state_obj = _compute_server_state_response(self.server)
            self._send_json(http_code, state_obj)
            return

        if route == "/api/anvil/v4/source":
            qs = parse_qs(parsed_url.query, keep_blank_values=True)
            rel_list = qs.get("file") or []
            raw_rel = rel_list[0] if rel_list else ""
            try:
                resolved = resolve_contained_path(self.server.repo_root, raw_rel, must_be_relative=True)
            except AnvilRefusalError as err:
                self._send_json(403, err.to_dict())
                return
            if not resolved.is_file():
                self._send_json(
                    404,
                    {"ok": False, "error_code": "SOURCE_FILE_NOT_FOUND", "message": "Requested source file does not exist."},
                )
                return
            try:
                raw_b = resolved.read_bytes()
            except OSError as exc:
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error_code": "BACKING_STORE_UNREADABLE",
                        "message": f"Unable to read source file: {exc}",
                    },
                )
                return
            if len(raw_b) > MAX_SOURCE_BUNDLE_BYTES:
                self._send_json(
                    413,
                    {
                        "ok": False,
                        "error_code": "BOUND_EXCEEDED_REFUSAL",
                        "message": "Source file exceeds MAX_SOURCE_BUNDLE_BYTES.",
                    },
                )
                return
            rel_posix = resolved.relative_to(self.server.repo_root).as_posix()
            txt = raw_b.decode("utf-8", errors="replace")
            raw_lines = txt.splitlines()
            pairs = [[idx, ln] for idx, ln in enumerate(raw_lines, start=1)]
            numbered = "\n".join(f"{idx:4d} | {ln}" for idx, ln in pairs)
            self._send_json(
                200,
                {
                    "ok": True,
                    "file": rel_posix,
                    "total_lines": len(raw_lines),
                    "watchable_tokens": _extract_watchable_tokens(txt, resolved.suffix.lower()),
                    "lines": pairs,
                    "numbered_source": numbered,
                },
            )
            return

        self._send_json(404, {"ok": False, "error_code": "ROUTE_NOT_FOUND", "message": f"Unknown route '{route}'."})

    def do_POST(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if not self._verify_capability_token():
            try:
                cl_drain = int(self.headers.get("Content-Length") or 0)
                if 0 < cl_drain <= MAX_POST_BYTES:
                    _ = self.rfile.read(cl_drain)
            except Exception:
                pass
            self._send_json(
                403,
                {
                    "ok": False,
                    "error_code": "CAPABILITY_TOKEN_REFUSED",
                    "cwe": "CWE-352",
                    "message": "Missing or invalid X-Anvil-Capability token.",
                },
            )
            return

        body, err_resp = self._read_json_body()
        if err_resp is not None or body is None:
            status_c, payload = err_resp or (400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "Invalid JSON."})
            self._send_json(status_c, payload)
            return

        if route == "/api/anvil/v4/session":
            self._handle_post_session(body)
            return
        if route == "/api/anvil/v4/chat":
            self._handle_post_chat(body)
            return
        if route == "/api/anvil/v4/trace":
            self._handle_post_trace_or_profile(body, is_profile=False)
            return
        if route == "/api/anvil/v4/profile-lit":
            self._handle_post_trace_or_profile(body, is_profile=True)
            return

        self._send_json(404, {"ok": False, "error_code": "ROUTE_NOT_FOUND", "message": f"Unknown POST route '{route}'."})

    def _handle_post_session(self, body: Dict[str, Any]) -> None:
        if "pinned_watches" in body:
            pw = body["pinned_watches"]
            if not isinstance(pw, list) or any(not isinstance(x, str) for x in pw):
                self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'pinned_watches' must be a list of strings."})
                return
            if len(pw) > 64:
                self._send_json(400, {"ok": False, "error_code": "BOUND_EXCEEDED_REFUSAL", "message": "'pinned_watches' exceeds 64 items."})
                return
        if "breakpoints" in body:
            bps = body["breakpoints"]
            if not isinstance(bps, list):
                self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'breakpoints' must be a list."})
                return
            if len(bps) > 128:
                self._send_json(400, {"ok": False, "error_code": "BOUND_EXCEEDED_REFUSAL", "message": "'breakpoints' exceeds 128 items."})
                return
        if "active_line" in body:
            aln = body["active_line"]
            if isinstance(aln, bool) or not isinstance(aln, int) or aln < 1 or aln > 1_000_000:
                code = "BOUND_EXCEEDED_REFUSAL" if (isinstance(aln, int) and not isinstance(aln, bool)) else "MALFORMED_DATA_REFUSED"
                self._send_json(400, {"ok": False, "error_code": code, "message": "'active_line' must be an integer in 1..1000000."})
                return
        if "ide_open" in body and not isinstance(body["ide_open"], bool):
            self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'ide_open' must be a boolean."})
            return
        if "ide_theme" in body and body["ide_theme"] not in {"light", "dark"}:
            self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'ide_theme' must be 'light' or 'dark'."})
            return
        for str_key in ("active_stage_id", "active_step_id", "active_file", "active_pipeline"):
            if str_key in body and not isinstance(body[str_key], str):
                self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": f"'{str_key}' must be a string."})
                return

        with self.server.state_lock:
            try:
                proc_map = (
                    self.server.last_good_bundle["process_map"]
                    if (self.server.last_good_bundle and "process_map" in self.server.last_good_bundle)
                    else build_process_map(self.server.repo_root, persist=False)
                )
                current = _load_or_init_workbench_session(self.server.repo_root, proc_map, persist=True)
                merged = dict(current)
                for k in (
                    "pinned_watches",
                    "breakpoints",
                    "active_stage_id",
                    "active_step_id",
                    "active_file",
                    "active_line",
                    "ide_open",
                    "ide_theme",
                ):
                    if k in body:
                        merged[k] = body[k]
                normalized = _validate_and_normalize_session(merged, _default_session_payload(proc_map))
                session_path = self.server.repo_root / ".anvil" / "v4" / "workbench_session.json"
                atomic_locked_write_json(session_path, normalized)
                if self.server.last_good_bundle is not None:
                    self.server.last_good_bundle["session"] = normalized
                self._send_json(200, {"ok": True, "session": normalized})
            except AnvilRefusalError as err:
                surf = _map_refusal_to_surface_failure(err)
                if surf is not None:
                    self._send_json(int(surf["http_status"]), {**err.to_dict(), **surf})
                else:
                    self._send_json(400, err.to_dict())

    def _handle_post_chat(self, body: Dict[str, Any]) -> None:
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            self._send_json(
                400,
                {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "Non-empty 'question' string required."},
            )
            return
        if len(question) > 4096:
            self._send_json(
                400,
                {"ok": False, "error_code": "BOUND_EXCEEDED_REFUSAL", "message": "'question' exceeds 4096 characters."},
            )
            return
        if "active_line" in body and body["active_line"] is not None:
            aln = body["active_line"]
            if isinstance(aln, bool) or not isinstance(aln, int) or aln < 1 or aln > 1_000_000:
                self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'active_line' must be a valid integer."})
                return
        with self.server.state_lock:
            try:
                bundle = build_workbench_bundle(
                    self.server.repo_root,
                    paper_path=self.server.paper_path,
                    approve_run=self.server.approve_run,
                    persist=True,
                )
                self.server.last_good_bundle = bundle
                session = dict(bundle["session"])
                active_sid = str(body.get("active_stage_id") or session.get("active_stage_id") or "S1")
                active_file = str(body.get("active_file") if body.get("active_file") is not None else session.get("active_file", ""))
                active_line = max(1, int(body.get("active_line") or session.get("active_line") or 1))
                ide_open = bool(body.get("ide_open", session.get("ide_open", False)))

                chat_res = _synthesize_grounded_copilot_reply(
                    self.server.repo_root,
                    bundle,
                    question.strip()[:2048],
                    active_sid,
                    active_file,
                    active_line,
                    ide_open,
                )
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                turns = list(session.get("dialogue_turns") or [])
                turns.append({"role": "user", "text": question.strip()[:2048], "stage_id": active_sid, "ts": now_iso})
                turns.append({"role": "assistant", "text": chat_res["reply"], "stage_id": chat_res["cited_stage_id"], "ts": now_iso})
                session["dialogue_turns"] = turns[-80:]
                session["active_stage_id"] = active_sid
                if active_file:
                    session["active_file"] = active_file
                session["active_line"] = active_line
                session["ide_open"] = ide_open

                session_path = self.server.repo_root / ".anvil" / "v4" / "workbench_session.json"
                atomic_locked_write_json(session_path, session)
                bundle["session"] = session
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "reply": chat_res["reply"],
                        "cited_stage_id": chat_res["cited_stage_id"],
                        "cited_target_stages": chat_res["cited_target_stages"],
                        "cited_file": chat_res["cited_file"],
                        "cited_line": chat_res["cited_line"],
                        "dialogue_turns": session["dialogue_turns"],
                        "session": session,
                    },
                )
            except AnvilRefusalError as err:
                surf = _map_refusal_to_surface_failure(err)
                if surf is not None:
                    self._send_json(int(surf["http_status"]), {**err.to_dict(), **surf})
                else:
                    self._send_json(400, err.to_dict())

    def _handle_post_trace_or_profile(self, body: Dict[str, Any], *, is_profile: bool) -> None:
        if "cmd" in body or "command" in body or "shell" in body:
            self._send_json(
                403,
                {
                    "ok": False,
                    "error_code": "EXECUTION_POLICY_REFUSED",
                    "cwe": "CWE-78",
                    "message": "Shell command strings ('cmd'/'command') are strictly refused; pass an explicit 'argv' array.",
                },
            )
            return

        raw_argv = body.get("argv")
        if isinstance(raw_argv, (str, bytes)) or not isinstance(raw_argv, list) or len(raw_argv) == 0:
            self._send_json(
                403,
                {
                    "ok": False,
                    "error_code": "EXECUTION_POLICY_REFUSED",
                    "cwe": "CWE-78",
                    "message": "Execution requires a non-empty JSON 'argv' list of strings.",
                },
            )
            return

        if body.get("operator_consent_confirmed") is not True:
            self._send_json(
                403,
                {
                    "ok": False,
                    "error_code": "CONSENT_REQUIRED_REFUSED",
                    "message": "Explicit operator_consent_confirmed: true from UI consent gate is required.",
                    "isolation_boundary": ISOLATION_BOUNDARY,
                    "non_vm_trust_warning": NON_VM_TRUST_WARNING,
                },
            )
            return

        try:
            validate_execution_argv(self.server.repo_root, raw_argv)
        except AnvilRefusalError as pol_err:
            self._send_json(403, pol_err.to_dict())
            return

        raw_to = body.get("timeout_sec", 30.0)
        if isinstance(raw_to, bool) or not isinstance(raw_to, (int, float)):
            self._send_json(
                400,
                {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "'timeout_sec' must be numeric."},
            )
            return
        timeout_sec = float(raw_to)
        if timeout_sec <= 0.0 or timeout_sec > 300.0 or timeout_sec != timeout_sec:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error_code": "BOUND_EXCEEDED_REFUSAL",
                    "message": "'timeout_sec' must be within (0, 300.0].",
                    "bound_name": "timeout_sec",
                    "bound_limit": 300.0,
                    "observed_value": timeout_sec,
                },
            )
            return
        with self.server.state_lock:
            try:
                proc_map = build_process_map(self.server.repo_root, persist=False)
                session = _load_or_init_workbench_session(self.server.repo_root, proc_map, persist=True)
                if is_profile:
                    prof_doc = run_profile_and_literature(
                        self.server.repo_root,
                        approve_run=True,
                        argv=raw_argv,
                        timeout_sec=timeout_sec,
                        persist=True,
                    )
                    bundle = build_workbench_bundle(
                        self.server.repo_root,
                        paper_path=self.server.paper_path,
                        approve_run=self.server.approve_run,
                        persist=True,
                    )
                    self.server.last_good_bundle = bundle
                    self._send_json(200, {"ok": True, "profile_lit": prof_doc, "bundle": bundle})
                else:
                    trace_doc = run_consented_trace(
                        self.server.repo_root,
                        raw_argv,
                        approve_run=True,
                        timeout_sec=timeout_sec,
                        pinned_watches=session.get("pinned_watches") or [],
                        persist=True,
                    )
                    bundle = build_workbench_bundle(
                        self.server.repo_root,
                        paper_path=self.server.paper_path,
                        approve_run=self.server.approve_run,
                        persist=True,
                    )
                    self.server.last_good_bundle = bundle
                    self._send_json(200, {"ok": True, "trace_summary": bundle["trace_summary"], "trace_ok": trace_doc.get("ok", True), "bundle": bundle})
            except AnvilRefusalError as err:
                surf = _map_refusal_to_surface_failure(err)
                if surf is not None:
                    preserved = self.server.last_good_bundle
                    if preserved is None and surf["status_kind"] in {"dependency-missing", "dependency-slow-or-killed"}:
                        try:
                            preserved = build_workbench_bundle(
                                self.server.repo_root,
                                paper_path=self.server.paper_path,
                                approve_run=self.server.approve_run,
                                persist=False,
                            )
                        except Exception:
                            preserved = None
                    self._send_json(
                        int(surf["http_status"]),
                        {
                            **err.to_dict(),
                            "status_kind": surf["status_kind"],
                            "http_status": surf["http_status"],
                            "badge": surf["badge"],
                            "message": surf["message"],
                            "surface_state": surf,
                            "bundle": preserved,
                        },
                    )
                elif err.error_code in {"EXECUTION_POLICY_REFUSED", "PATH_ESCAPE_REFUSED", "CONSENT_REQUIRED_REFUSED"}:
                    self._send_json(403, err.to_dict())
                else:
                    self._send_json(400, err.to_dict())


def create_workbench_server(
    repo_dir: str | Path,
    paper_path: Optional[str | Path] = None,
    host: str = "127.0.0.1",
    port: int = 0,
    approve_run: bool = False,
    fault_injection_mode: Optional[str] = None,
) -> AnvilWorkbenchHTTPServer:
    """Create and bind a loopback-only Anvil v4 Workbench HTTP server (never port 8777)."""
    clean_host = (host or "").strip().lower()
    if clean_host not in {"127.0.0.1", "localhost"}:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            f"Non-loopback host '{host}' refused; Anvil v4 Workbench binds strictly to 127.0.0.1.",
            cwe="CWE-284",
            details={"requested_host": host},
        )
    bind_host = "127.0.0.1"

    if isinstance(port, bool) or not isinstance(port, int) or port < 0 or port > 65535:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Port ({port}) must be an integer within 0..65535.",
            details={"bound_name": "port", "bound_limit": 65535, "observed_value": port},
        )
    if port == RESERVED_ANCHOR_PORT:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            "Port 8777 is reserved for Anchor and cannot be bound by Anvil v4 Workbench.",
            details={"reserved_port": RESERVED_ANCHOR_PORT},
        )
    if fault_injection_mode is not None and fault_injection_mode not in SURFACE_FAILURE_TABLE:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            f"Unsupported fault_injection_mode '{fault_injection_mode}'.",
        )

    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    resolved_paper = Path(paper_path).resolve() if paper_path else None

    srv = AnvilWorkbenchHTTPServer(
        (bind_host, port),
        _WorkbenchRequestHandler,
        repo_root=root,
        paper_path=resolved_paper,
        approve_run=approve_run,
        fault_injection_mode=fault_injection_mode,
    )
    if int(srv.server_address[1]) == RESERVED_ANCHOR_PORT:
        # Hold the accidental 8777 socket briefly while allocating a distinct ephemeral port
        try:
            srv2 = AnvilWorkbenchHTTPServer(
                (bind_host, 0),
                _WorkbenchRequestHandler,
                repo_root=root,
                paper_path=resolved_paper,
                approve_run=approve_run,
                fault_injection_mode=fault_injection_mode,
            )
        finally:
            srv.server_close()
        srv = srv2
    return srv


def serve_workbench(
    repo_dir: str | Path,
    paper_path: Optional[str | Path] = None,
    host: str = "127.0.0.1",
    port: int = 0,
    approve_run: bool = False,
) -> int:
    """Bind the loopback server, emit JSON startup receipt, and serve until SIGINT/SIGTERM."""
    srv = create_workbench_server(
        repo_dir,
        paper_path=paper_path,
        host=host,
        port=port,
        approve_run=approve_run,
    )
    bound_port = int(srv.server_address[1])
    startup_receipt = {
        "ok": True,
        "mode": "live",
        "host": "127.0.0.1",
        "port": bound_port,
        "url": f"http://127.0.0.1:{bound_port}/",
        "repo": str(srv.repo_root),
        "isolation_boundary": ISOLATION_BOUNDARY if approve_run else "static_ast_zero_execution",
    }
    print(json.dumps(startup_receipt, ensure_ascii=False), flush=True)

    stop_event = threading.Event()

    def _handle_sig(_signum: int, _frame: Any) -> None:
        stop_event.set()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    prev_int = signal.getsignal(signal.SIGINT)
    prev_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        srv.server_close()
    return 0
