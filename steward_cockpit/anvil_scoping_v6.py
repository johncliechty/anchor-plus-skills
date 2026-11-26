"""Reload-coherent Anvil v6 Scoping v2, `<1ms` Drift Check & Scholarly Literature Sketch (`anvil_scoping_v6.py`).
All shared exceptions/bounds resolve dynamically via `from . import anvil_session as _as` for reload coherence.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from . import anvil_session as _as

_SCOPE_MANIFEST_PLAN_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = globals().setdefault("_SCOPE_MANIFEST_PLAN_CACHE", {})
_SCOPE_MANIFEST_SHA_CACHE: Dict[Tuple[str, int, int], str] = globals().setdefault("_SCOPE_MANIFEST_SHA_CACHE", {})

_SCOPING_RESTORE_RE = re.compile(r"\b(?:restore\s+paper|paper-matched\s+default|reset\s+default|only\s+paper)\b", re.IGNORECASE)
_SCOPING_EXCLUDE_RE = re.compile(r"\b(?:drop|exclude|remove|quarantine|without)\b", re.IGNORECASE)
_SCOPING_INCLUDE_RE = re.compile(r"\b(?:include|add|enable|select|bring\s+in)\b", re.IGNORECASE)
_SKIP_SIBLING_DIRS = frozenset({
    "__pycache__", "node_modules", "vendor", "tests", "test", "code-job-outputs",
    "review", "review-input", "reports", "figures", "checks", "research", "journal", "notes", "tools", "logs", "backups", "archive", "planning",
})


def _refuse_garbage(code: str, msg: Optional[str] = None, *, http_status: int = 400, extra: Optional[Dict[str, Any]] = None) -> None:
    raise _as.AnvilAnalysisRefusalError(
        code,
        msg or _as.ANVIL_V5_FAILURE_STATE_TABLE["dependency-returns-garbage"]["message"],
        http_status=http_status,
        row_key="dependency-returns-garbage",
        extra=extra,
    )


def _lstat_is_link_or_reparse(st: os.stat_result) -> bool:
    return _as._lstat_is_link_or_reparse(st)


def validate_opaque_module_ids(raw_ids: Any, valid_ids_set: Optional[set[str]] = None) -> Optional[List[str]]:
    """Validate opaque `module_ids` (`^[a-z0-9_-]+$`) against server-computed architecture map IDs."""
    if raw_ids is None:
        return None
    if not isinstance(raw_ids, list):
        _refuse_garbage("MALFORMED_DATA_REFUSED")
    if len(raw_ids) > 128:
        _refuse_garbage(
            "BOUND_EXCEEDED_REFUSAL", "selected_module_ids exceeds 128-entry bound.",
            extra={"bound_name": "MAX_SELECTED_MODULES", "bound_limit": 128, "observed_value": len(raw_ids)},
        )
    cleaned: List[str] = []
    for item in raw_ids:
        if not isinstance(item, str) or not item.strip():
            _refuse_garbage("MALFORMED_DATA_REFUSED")
        s = item.strip()
        if "\x00" in s or ".." in s or s.startswith(("/", "\\")) or "\\" in s or ":" in s:
            _refuse_garbage("PATH_ESCAPE_REFUSED", f"Path traversal, UNC, or absolute path in module_ids refused: '{s[:64]}'", http_status=403)
        if "/" in s or "." in s or len(s) > 80 or not _as.OPAQUE_MODULE_ID_RE.fullmatch(s):
            _refuse_garbage("INVALID_MODULE_ID_REFUSED")
        if valid_ids_set is not None and s not in valid_ids_set:
            _refuse_garbage("UNKNOWN_MODULE_ID_REFUSED")
        if s not in cleaned:
            cleaned.append(s)
    return cleaned


def _walk_contained_rel_segments(base_res: Path, raw_s: str, *, label: str) -> Path:
    if "\x00" in raw_s or raw_s.startswith(("/", "\\")) or ":" in raw_s or Path(raw_s).is_absolute():
        _refuse_garbage("PATH_ESCAPE_REFUSED", f"Absolute, UNC, or drive-prefixed {label} path refused.", http_status=403)
    walk = base_res
    for part in (p for p in re.split(r"[\\/]+", raw_s) if p and p != "."):
        low = part.lower()
        if part == ".." or part.startswith(".") or low in _as.FORBIDDEN_DOT_PARTS or low in _as.FORBIDDEN_SECRET_NAMES:
            _refuse_garbage("PATH_ESCAPE_REFUSED", f"Disallowed or escaping {label} segment '{part}' refused.", http_status=403)
        walk = walk / part
        if _as._is_symlink_or_junction(walk):
            _refuse_garbage("PATH_ESCAPE_REFUSED", f"Symbolic link or junction {label} component '{part}' refused.", http_status=403)
    return walk


def resolve_scoping_v2_local_dir(cdir: Path, raw_spec: Optional[Any]) -> Tuple[Path, str]:
    if _as._is_symlink_or_junction(cdir) or not cdir.exists() or not cdir.is_dir():
        _refuse_garbage("PATH_ESCAPE_REFUSED", "Cockpit directory does not exist or is a symbolic link / junction.", http_status=403)
    cdir_res = cdir.resolve()
    if raw_spec is None:
        return cdir_res, "."
    if not isinstance(raw_spec, str):
        _refuse_garbage("MALFORMED_DATA_REFUSED")
    s = raw_spec.strip()
    if not s or s == ".":
        return cdir_res, "."
    walk = _walk_contained_rel_segments(cdir_res, s, label="software")
    resolved = walk.resolve()
    if _as._is_symlink_or_junction(resolved) or not resolved.is_relative_to(cdir_res):
        _refuse_garbage("PATH_ESCAPE_REFUSED", "Software target escapes cockpit workspace boundary.", http_status=403)
    if not resolved.exists() or not resolved.is_dir():
        _refuse_garbage("MALFORMED_DATA_REFUSED")
    return resolved, (resolved.relative_to(cdir_res).as_posix() or ".")


def resolve_scoping_v2_paper_path(cdir: Path, sw_dir: Path, raw_paper: Optional[Any]) -> Tuple[Optional[Path], str]:
    cdir_res = cdir.resolve()
    if raw_paper is None:
        auto_p = (_as._pick_primary_tex_in_dir(sw_dir) if sw_dir != cdir_res else None) or _as._pick_primary_tex_in_dir(cdir_res)
        if auto_p is not None and not _as._is_symlink_or_junction(auto_p) and auto_p.resolve().is_relative_to(cdir_res):
            return auto_p.resolve(), auto_p.resolve().relative_to(cdir_res).as_posix()
        return None, ""
    if not isinstance(raw_paper, str):
        _refuse_garbage("MALFORMED_DATA_REFUSED")
    s = raw_paper.strip()
    if not s:
        return None, ""
    walk = _walk_contained_rel_segments(cdir_res, s, label="manuscript")
    if not walk.exists() and sw_dir != cdir_res:
        alt_walk = _walk_contained_rel_segments(sw_dir, s, label="manuscript")
        if alt_walk.exists():
            walk = alt_walk
    resolved = walk.resolve()
    if _as._is_symlink_or_junction(resolved) or not resolved.is_relative_to(cdir_res):
        _refuse_garbage("PATH_ESCAPE_REFUSED", "Manuscript path escapes cockpit workspace boundary.", http_status=403)
    if not resolved.exists():
        _refuse_garbage("MALFORMED_DATA_REFUSED")
    if resolved.is_dir():
        picked = _as._pick_primary_tex_in_dir(resolved)
        if picked is None:
            _refuse_garbage("MALFORMED_DATA_REFUSED")
        resolved = picked.resolve()
    return resolved, resolved.relative_to(cdir_res).as_posix()


def check_locked_scope_drift(cdir: Path, store_root: Path, v4_proc: Any) -> Optional[Dict[str, Any]]:
    """Verify `<store_root>/.anvil/scope_manifest.json` against on-disk SHA-256 digests (`< 1 ms` warm fast path)."""
    sm_str = os.path.join(str(store_root), ".anvil", "scope_manifest.json")
    try:
        sm_st = os.lstat(sm_str)
    except FileNotFoundError:
        return None
    except OSError as os_exc:
        _as._raise_v5_backing_store_unreadable(f"Cannot stat scope_manifest.json: {os_exc}")
        return None

    if _lstat_is_link_or_reparse(sm_st):
        _refuse_garbage("PATH_ESCAPE_REFUSED", "Symbolic link or junction scope_manifest.json refused.", http_status=403)
    if not stat.S_ISREG(sm_st.st_mode):
        _as._raise_v5_backing_store_unreadable("scope_manifest.json is not a regular file")

    sm_stat_key = (sm_str, int(sm_st.st_mtime_ns), int(sm_st.st_size))
    with _as._SCOPE_DRIFT_MEMO_LOCK:
        cached_msha = _SCOPE_MANIFEST_SHA_CACHE.get(sm_stat_key)
        plan = _SCOPE_MANIFEST_PLAN_CACHE.get((cached_msha, str(cdir))) if cached_msha else None

    raw_bytes: Optional[bytes] = None
    if cached_msha is not None and plan is not None:
        manifest_sha256 = cached_msha
    else:
        try:
            with open(sm_str, "rb") as fh:
                raw_bytes = fh.read()
            manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        except Exception as exc:
            _as._raise_v5_backing_store_unreadable(f"Corrupt scope_manifest.json: {exc}")
            return None
        plan_key = (manifest_sha256, str(cdir))
        with _as._SCOPE_DRIFT_MEMO_LOCK:
            if len(_SCOPE_MANIFEST_SHA_CACHE) >= 128:
                _SCOPE_MANIFEST_SHA_CACHE.clear()
            _SCOPE_MANIFEST_SHA_CACHE[sm_stat_key] = manifest_sha256
            plan = _SCOPE_MANIFEST_PLAN_CACHE.get(plan_key)

    if plan is None:
        try:
            if raw_bytes is None:
                with open(sm_str, "rb") as fh:
                    raw_bytes = fh.read()
            sm_doc = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            _as._raise_v5_backing_store_unreadable(f"Corrupt scope_manifest.json: {exc}")
            return None
        if (
            not isinstance(sm_doc, dict)
            or sm_doc.get("schema") != _as.ANVIL_SCOPE_LOCK_SCHEMA
            or not isinstance(sm_doc.get("scope_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", sm_doc["scope_sha256"])
            or not isinstance(sm_doc.get("scope_files"), list)
            or not isinstance(sm_doc.get("selected_module_ids"), list)
        ):
            _as._raise_v5_backing_store_unreadable("Invalid schema in scope_manifest.json")
            return None

        locked_sha = str(sm_doc["scope_sha256"])
        scope_files = [str(f) for f in sm_doc["scope_files"] if isinstance(f, str) and f.strip()]
        sel_mids = [str(m) for m in sm_doc["selected_module_ids"] if isinstance(m, str) and m.strip()]
        entrypoints = [str(e) for e in (sm_doc.get("entrypoints") or []) if isinstance(e, str) and e.strip()]
        sw_spec = str(sm_doc.get("software_spec") or ".")
        paper_spec = str(sm_doc.get("paper_spec") or "")
        manifest_inner = sm_doc.get("manifest") if isinstance(sm_doc.get("manifest"), dict) else {}

        cdir_res = cdir.resolve()
        try:
            sw_dir, _ = resolve_scoping_v2_local_dir(cdir_res, sw_spec)
        except _as.AnvilAnalysisRefusalError as s_err:
            if s_err.http_status in (403, 500):
                raise
            return {"drifted": True, "locked_scope_sha256": locked_sha, "current_scope_sha256": "", "missing_files": [sw_spec], "selected_module_ids": sel_mids, "scope_files": scope_files}
        paper_p: Optional[Path] = None
        if paper_spec:
            try:
                paper_p, _ = resolve_scoping_v2_paper_path(cdir_res, sw_dir, paper_spec)
            except _as.AnvilAnalysisRefusalError as p_err:
                if p_err.http_status in (403, 500):
                    raise
                return {"drifted": True, "locked_scope_sha256": locked_sha, "current_scope_sha256": "", "missing_files": [paper_spec], "selected_module_ids": sel_mids, "scope_files": scope_files}

        sw_str, cdir_str = str(sw_dir), str(cdir_res)
        paper_specs = [
            (str(p_ent["path"]), os.path.normpath(os.path.join(cdir_str, str(p_ent["path"])[len("cockpit:"):])) if str(p_ent["path"]).startswith("cockpit:") else os.path.normpath(os.path.join(sw_str, str(p_ent["path"]))))
            for p_ent in (manifest_inner.get("papers") or []) if isinstance(p_ent, dict) and p_ent.get("path")
        ]
        data_file_specs = [
            (f"DF:{d_ent.get('root') or 'repo:data'}:{d_ent['path']}", str(d_ent["path"]), os.path.normpath(os.path.join(cdir_str if str(d_ent.get("root") or "").startswith("cockpit:") else sw_str, str(d_ent["path"]))))
            for d_ent in (manifest_inner.get("allowlisted_data_files") or []) if isinstance(d_ent, dict) and d_ent.get("path")
        ]
        plan = {
            "locked_sha": locked_sha, "scope_files": scope_files, "sel_mids": sel_mids, "entrypoints": entrypoints,
            "sw_dir": sw_dir, "cdir_res": cdir_res, "paper_p": paper_p,
            "file_specs": [(rel_f, os.path.normpath(os.path.join(sw_str, rel_f))) for rel_f in scope_files],
            "paper_specs": paper_specs,
            "data_dir_specs": [(f"DR:{btag}:{dname}", dname, os.path.join(bstr, dname)) for btag, bstr in (("repo", sw_str), ("cockpit", cdir_str)) for dname in ("data", "Data", "datasets", "Datasets")],
            "data_file_specs": data_file_specs,
        }
        with _as._SCOPE_DRIFT_MEMO_LOCK:
            if len(_SCOPE_MANIFEST_PLAN_CACHE) >= 256:
                _SCOPE_MANIFEST_PLAN_CACHE.clear()
            _SCOPE_MANIFEST_PLAN_CACHE[(manifest_sha256, str(cdir))] = plan

    locked_sha, scope_files, sel_mids = plan["locked_sha"], plan["scope_files"], plan["sel_mids"]
    stat_rows: List[Tuple[str, int, int]] = []
    missing_files: List[str] = []

    for rel_f, fp_str in plan["file_specs"]:
        try:
            st_f = os.lstat(fp_str)
        except FileNotFoundError:
            missing_files.append(rel_f)
            continue
        except OSError as os_exc:
            _as._raise_v5_backing_store_unreadable(f"Cannot verify in-scope file '{rel_f}': {os_exc}")
            return None
        if _lstat_is_link_or_reparse(st_f):
            _refuse_garbage("PATH_ESCAPE_REFUSED", f"In-scope file '{rel_f}' became a symlink or junction.", http_status=403)
        if not stat.S_ISREG(st_f.st_mode):
            _as._raise_v5_backing_store_unreadable(f"In-scope path '{rel_f}' is unreadable or not a regular file.")
        stat_rows.append((f"S:{rel_f}", int(st_f.st_mtime_ns), int(st_f.st_size)))

    if missing_files:
        return {"drifted": True, "locked_scope_sha256": locked_sha, "current_scope_sha256": "", "missing_files": missing_files, "selected_module_ids": sel_mids, "scope_files": scope_files}

    def _lstat_aux(tag_key: str, label: str, p_str: str, *, dir_only: bool = False) -> None:
        try:
            st_x = os.lstat(p_str)
        except FileNotFoundError:
            if not dir_only:
                stat_rows.append((tag_key, -1, -1))
            return
        except OSError as os_exc:
            _as._raise_v5_backing_store_unreadable(f"Cannot verify '{label}': {os_exc}")
            return
        if _lstat_is_link_or_reparse(st_x):
            _refuse_garbage("PATH_ESCAPE_REFUSED", f"'{label}' became a symlink.", http_status=403)
        if not dir_only or stat.S_ISDIR(st_x.st_mode):
            stat_rows.append((tag_key, int(st_x.st_mtime_ns), int(st_x.st_size)))

    for pk, pfp_str in plan["paper_specs"]:
        _lstat_aux(f"P:{pk}", pk, pfp_str)
    for dr_key, dname, dp_str in plan["data_dir_specs"]:
        _lstat_aux(dr_key, dname, dp_str, dir_only=True)
    for df_key, drel, dfp_str in plan["data_file_specs"]:
        _lstat_aux(df_key, drel, dfp_str)

    eng_sig = _as._V4_MODULES_MTIME_SIG or _as._compute_anvil_scripts_mtime_sig(Path(v4_proc.__file__).parent)
    memo_key = (manifest_sha256, tuple(stat_rows), eng_sig)
    with _as._SCOPE_DRIFT_MEMO_LOCK:
        memo_hit = _as._SCOPE_DRIFT_MEMO_CACHE.get(memo_key)
        if memo_hit is not None:
            return {
                "drifted": memo_hit["drifted"], "locked_scope_sha256": memo_hit["locked_scope_sha256"],
                "current_scope_sha256": memo_hit["current_scope_sha256"], "missing_files": list(memo_hit["missing_files"]),
                "selected_module_ids": list(memo_hit["selected_module_ids"]), "scope_files": list(memo_hit["scope_files"]),
            }

    try:
        _, cur_sha = v4_proc.compute_scope_manifest(
            plan["sw_dir"], scope_files=scope_files, selected_module_ids=sel_mids,
            entrypoints=plan["entrypoints"] or None, paper_paths=[plan["paper_p"]] if plan["paper_p"] is not None else None,
            cockpit_root=plan["cdir_res"],
        )
    except Exception as exc:
        err_c = getattr(exc, "error_code", "")
        if err_c == "PATH_ESCAPE_REFUSED":
            _refuse_garbage("PATH_ESCAPE_REFUSED", str(exc), http_status=403)
        if isinstance(exc, OSError) or err_c in {"BACKING_STORE_UNREADABLE", "LOCK_TIMEOUT_REFUSED"}:
            _as._raise_v5_backing_store_unreadable(f"Cannot verify locked scope manifest: {exc}")
        return {"drifted": True, "locked_scope_sha256": locked_sha, "current_scope_sha256": "", "missing_files": [], "selected_module_ids": sel_mids, "scope_files": scope_files}

    drift_res = {"drifted": cur_sha != locked_sha, "locked_scope_sha256": locked_sha, "current_scope_sha256": cur_sha, "missing_files": [], "selected_module_ids": sel_mids, "scope_files": scope_files}
    with _as._SCOPE_DRIFT_MEMO_LOCK:
        if len(_as._SCOPE_DRIFT_MEMO_CACHE) >= 256:
            _as._SCOPE_DRIFT_MEMO_CACHE.clear()
        _as._SCOPE_DRIFT_MEMO_CACHE[memo_key] = copy.deepcopy(drift_res)
    return drift_res


def enrich_analysis_entry_v6_metadata(
    cdir: Path, store_root: Path, entry: Dict[str, Any], v4_proc: Any, *,
    precomputed_drift: Optional[Dict[str, Any]] = None, has_precomputed_drift: bool = False,
) -> Dict[str, Any]:
    out_ent = dict(entry)
    rep_str = os.path.join(str(store_root), ".anvil", "v4", "replication_audit_receipt.json")
    try:
        rep_st = os.lstat(rep_str)
        out_ent["has_replication_report"] = bool(stat.S_ISREG(rep_st.st_mode) and not _lstat_is_link_or_reparse(rep_st))
    except OSError:
        out_ent["has_replication_report"] = False
    drift_info = precomputed_drift if has_precomputed_drift else check_locked_scope_drift(cdir, store_root, v4_proc)
    if drift_info is not None:
        out_ent.update({
            "scope_sha256": drift_info["locked_scope_sha256"],
            "current_scope_sha256": drift_info["current_scope_sha256"],
            "scope_drifted": bool(drift_info["drifted"]),
            "selected_module_ids": list(drift_info["selected_module_ids"]),
            "in_scope_file_count": len(drift_info["scope_files"]),
        })
        if drift_info["drifted"]:
            out_ent["validation_status"] = "409_SCOPE_DRIFTED"
    else:
        out_ent.setdefault("scope_sha256", "")
        out_ent.setdefault("scope_drifted", False)
        out_ent.setdefault("selected_module_ids", [])
    return out_ent


def read_optional_scoping_json(path: Path, expected_schema: str) -> Optional[Dict[str, Any]]:
    if _as._is_symlink_or_junction(path):
        _refuse_garbage("PATH_ESCAPE_REFUSED", f"Symbolic link or junction '{path.name}' refused.", http_status=403)
    if not path.exists():
        return None
    if not path.is_file():
        _as._raise_v5_backing_store_unreadable(f"{path.name} is not a regular file")
        return None
    try:
        _, raw_bytes = _as._stat_and_read_bytes_retry_win(path)
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        _as._raise_v5_backing_store_unreadable(f"Corrupt {path.name}: {exc}")
        return None
    if not isinstance(parsed, dict) or parsed.get("schema") != expected_schema:
        _as._raise_v5_backing_store_unreadable(f"Invalid schema in {path.name}")
        return None
    return parsed


def _discover_contained_sibling_code_dirs(cdir: Path, primary_dir: Path) -> List[Path]:
    out: List[Path] = []
    cdir_res = cdir.resolve()
    if not os.path.normcase(str(primary_dir)).startswith(os.path.normcase(str(cdir_res)) + os.sep):
        return out
    scan_roots = [cdir_res]
    if primary_dir.parent != cdir_res and primary_dir.parent.name.lower() in {"sources", "repos", "packages"}:
        scan_roots.insert(0, primary_dir.parent)
    try:
        for sroot in scan_roots:
            with os.scandir(sroot) as it:
                for ent in sorted(it, key=lambda e: e.name.lower()):
                    nm = ent.name
                    if nm.startswith((".", "_")) or nm.lower() in (_as.FORBIDDEN_DOT_PARTS | _SKIP_SIBLING_DIRS | {"sources", "repos", "packages"}):
                        continue
                    p = Path(ent.path)
                    if _as._is_symlink_or_junction(p) or not ent.is_dir(follow_symlinks=False):
                        continue
                    p_res = p.resolve()
                    norm_p, norm_prim = os.path.normcase(str(p_res)), os.path.normcase(str(primary_dir))
                    if norm_p == norm_prim or norm_prim.startswith(norm_p + os.sep) or p_res in out:
                        continue
                    has_py = False
                    for r_s, dirs_s, files_s in os.walk(p_res, followlinks=False):
                        rp_s = Path(r_s)
                        if rp_s.relative_to(p_res).parts and len(rp_s.relative_to(p_res).parts) > 4:
                            dirs_s[:] = []
                            continue
                        dirs_s[:] = [d for d in dirs_s if not d.startswith(".") and d.lower() not in _SKIP_SIBLING_DIRS and not _as._is_symlink_or_junction(rp_s / d)]
                        if any(fn.lower().endswith(".py") and not _as._is_symlink_or_junction(rp_s / fn) for fn in files_s):
                            has_py = True
                            break
                    if has_py:
                        out.append(p_res)
    except OSError:
        return []
    return out[:6]


def get_scoping_v2_state(
    cockpit_dir: str | Path, *, selected_module_ids: Optional[Any] = None, software_spec: Optional[Any] = None,
    paper_spec: Optional[Any] = None, analysis_id: Optional[Any] = None, anchor_root: Path | str | None = None, require_v6: bool = False,
) -> Tuple[Dict[str, Any], int]:
    cdir = Path(cockpit_dir).resolve()
    v6_on = _as.is_anvil_v6_enabled(anchor_root)
    if require_v6 and not v6_on:
        return _as._build_v6_disabled_refusal()
    multi_on = _as.is_multi_analysis_enabled(anchor_root)
    v4_mods = _as._load_anvil_v4_modules()
    if _as.anvil_engine is None or not v4_mods:
        return _as.build_v5_failure_response("dependency-missing", anchor_root=anchor_root)
    v4_proc = v4_mods["anvil_v4_process"]

    try:
        _as._check_anvil_containment_links(cdir)
        clean_aid = _as.validate_analysis_id(analysis_id, allow_none=True)
        prelim_sel = validate_opaque_module_ids(selected_module_ids, None) if selected_module_ids is not None else None
        persisted_scoping = read_optional_scoping_json(_as._scoping_state_file(cdir), _as.ANVIL_SCOPING_STATE_SCHEMA) or {}
        lit_cache = read_optional_scoping_json(_as._literature_cache_file(cdir), _as.ANVIL_LITERATURE_CACHE_SCHEMA) or {}
        lit_overlays = lit_cache.get("overlays") if isinstance(lit_cache.get("overlays"), dict) else {}

        analyses_resp, analyses_code = _as.list_cockpit_analyses(cdir, anchor_root=anchor_root)
        if analyses_code >= 400:
            return analyses_resp, analyses_code
        saved_scopes = list(analyses_resp.get("analyses") or [])
        saved_mod_union: List[str] = []
        target_saved: Optional[Dict[str, Any]] = None
        for sc in saved_scopes:
            if isinstance(sc, dict):
                if clean_aid and str(sc.get("analysis_id") or "") == clean_aid:
                    target_saved = sc
                for mid_s in sc.get("selected_module_ids") or []:
                    if mid_s not in saved_mod_union:
                        saved_mod_union.append(str(mid_s))

        cands = _as.discover_cockpit_candidates(cdir)
        eff_sw_raw = software_spec if software_spec is not None else (target_saved.get("software_spec") if target_saved else persisted_scoping.get("software_spec"))
        eff_pp_raw = paper_spec if paper_spec is not None else (target_saved.get("paper_spec") if target_saved and "paper_spec" in target_saved else persisted_scoping.get("paper_spec"))
        if eff_sw_raw is None:
            def_sw, def_pp = _as._default_scoping_targets(cdir, cands)
            eff_sw_raw = def_sw
            if eff_pp_raw is None and def_pp is not None:
                eff_pp_raw = def_pp
        sw_dir, norm_sw_spec = resolve_scoping_v2_local_dir(cdir, eff_sw_raw)
        paper_p, norm_paper_spec = resolve_scoping_v2_paper_path(cdir, sw_dir, eff_pp_raw)
        sibling_dirs = _discover_contained_sibling_code_dirs(cdir, sw_dir)

        # Single-pass architecture map when `prelim_sel` is passed directly
        arch_map = v4_proc.build_software_architecture_paper_map(
            sw_dir, paper_path=paper_p, sibling_repos=sibling_dirs,
            selected_module_ids=prelim_sel, saved_scope_module_ids=saved_mod_union,
            literature_overlays=lit_overlays, cockpit_root=cdir,
        )
        valid_ids = {str(m["module_id"]) for m in (arch_map.get("modules") or [])}
        if prelim_sel is not None:
            validate_opaque_module_ids(selected_module_ids, valid_ids)
        else:
            fallback_sel: Optional[List[str]] = None
            if target_saved and target_saved.get("selected_module_ids"):
                fallback_sel = [m for m in target_saved["selected_module_ids"] if m in valid_ids] or None
            elif isinstance(persisted_scoping.get("selected_module_ids"), list):
                fallback_sel = [m for m in persisted_scoping["selected_module_ids"] if isinstance(m, str) and m in valid_ids] or None
            if fallback_sel is not None and sorted(fallback_sel) != sorted(arch_map.get("selected_module_ids") or []):
                arch_map = v4_proc.build_software_architecture_paper_map(
                    sw_dir, paper_path=paper_p, sibling_repos=sibling_dirs,
                    selected_module_ids=fallback_sel, saved_scope_module_ids=saved_mod_union,
                    literature_overlays=lit_overlays, cockpit_root=cdir,
                )

        in_scope_mids = list(arch_map.get("selected_module_ids") or [])
        in_scope_files = list(arch_map.get("in_scope_files") or [])
        scope_sha256 = str(arch_map.get("scope_sha256") or "")
        manifest_parsed = json.loads(arch_map["scope_manifest_json"]) if arch_map.get("scope_manifest_json") else {}

        gandalf_on = bool(persisted_scoping.get("gandalf_enabled", True))
        dialogue_turns = list(persisted_scoping.get("dialogue_turns") or [])
        if not dialogue_turns:
            mod_cnt = len(arch_map.get("modules") or [])
            paper_lbl = arch_map.get("paper_file") or "no local manuscript"
            dialogue_turns = [{
                "role": "steward", "speaker": "Steward + Gandalf" if gandalf_on else "Steward",
                "text": (
                    f"Scanned `{sw_dir.name}` ({mod_cnt} architectural module group(s), manuscript: `{paper_lbl}`). "
                    f"Proposed fixed scope selects {len(in_scope_mids)} module(s) ({len(in_scope_files)} files) "
                    f"with manifest `{scope_sha256[:12]}…`. Toggle modules on the map or refine in plain English."
                ),
                "gandalf_note": "Unreferenced prototypes and raw ETL plumbing are quarantined outside the proposed estimator/table scope by default." if gandalf_on else "",
            }]

        is_empty = len(saved_scopes) == 0
        receipt_obj = {
            "scope_sha256": scope_sha256, "selected_module_ids": in_scope_mids, "in_scope_files": in_scope_files,
            "in_scope_file_count": len(in_scope_files), "entrypoints": list(manifest_parsed.get("entrypoints") or []),
            "paper_file": arch_map.get("paper_file") or "", "software_spec": norm_sw_spec, "paper_spec": norm_paper_spec,
            "drifted": bool(target_saved.get("scope_drifted")) if target_saved else False,
            "locked_scope_sha256": str(target_saved.get("scope_sha256") or "") if target_saved else "",
        }
        return ({
            "ok": True, "schema": _as.ANVIL_SCOPING_STATE_SCHEMA, "cockpit_dir": str(cdir), "cockpit_name": _as._cockpit_display_name(cdir),
            "anvil_v6_enabled": v6_on, "multi_analysis_enabled": multi_on,
            "status_kind": "empty-but-valid" if is_empty else "healthy", "failure_state": "empty-but-valid" if is_empty else "healthy",
            "http_status": 200, "state": "EMPTY" if is_empty else "READY", "badge": "EMPTY" if is_empty else "READY",
            "unknown_state": False, "message": _as.ANVIL_V6_EMPTY_MESSAGE if is_empty else f"{len(saved_scopes)} saved scope(s) ready",
            "active_analysis_id": analyses_resp.get("active_analysis_id"), "saved_scopes": saved_scopes, "analyses": saved_scopes,
            "software_map": arch_map, "receipt": receipt_obj, "scope_sha256": scope_sha256,
            "gandalf_enabled": gandalf_on, "dialogue_turns": dialogue_turns[-40:],
            "literature_sketch": {
                "has_sketch": bool(lit_overlays), "posture": "CLAIMED", "label": "CLAIMED / unverified",
                "verified": False, "updated_at": str(lit_cache.get("updated_at") or ""), "overlays": lit_overlays,
            },
            "seating": _as._read_model_seating_info(), "candidates": cands,
        }, 200)
    except _as.AnvilAnalysisRefusalError as a_err:
        return (a_err.payload, a_err.http_status)
    except v4_proc.AnvilRefusalError as v_err:
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=403 if v_err.error_code == "PATH_ESCAPE_REFUSED" else 400, error_code=v_err.error_code, detail=v_err.message, anchor_root=anchor_root)
    except TimeoutError as t_exc:
        return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(t_exc), anchor_root=anchor_root)


def _check_direction_bound(raw_str: Any, anchor_root: Path | str | None) -> Optional[Tuple[Dict[str, Any], int]]:
    if not isinstance(raw_str, str):
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)
    obs = len(raw_str.encode("utf-8"))
    cap = _as.MAX_DIRECTION_BYTES
    if obs > cap:
        msg = f"Direction exceeds {cap} bytes ({obs} bytes)."
        return ({
            "ok": False, "anvil_v6_enabled": _as.is_anvil_v6_enabled(anchor_root), "error_code": "BOUND_EXCEEDED_REFUSAL",
            "status_kind": "dependency-returns-garbage", "failure_state": "dependency-returns-garbage", "http_status": 413,
            "bound_name": "MAX_DIRECTION_BYTES", "bound_limit": cap, "observed_value": obs, "message": msg, "error": msg,
        }, 413)
    return None


def run_scoping_v2_turn(cockpit_dir: str | Path, body: Dict[str, Any], *, anchor_root: Path | str | None = None) -> Tuple[Dict[str, Any], int]:
    if not _as.is_anvil_v6_enabled(anchor_root):
        return _as._build_v6_disabled_refusal()
    if not isinstance(body, dict):
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)
    raw_msg = body.get("message") if "message" in body else body.get("direction", "")
    raw_msg = "" if raw_msg is None else raw_msg
    dir_err = _check_direction_bound(raw_msg, anchor_root)
    if dir_err is not None:
        return dir_err
    gandalf_raw = body.get("gandalf_enabled")
    if gandalf_raw is not None and not isinstance(gandalf_raw, bool):
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)

    cdir = Path(cockpit_dir).resolve()
    try:
        req_mids = body["module_ids"] if "module_ids" in body else body.get("selected_module_ids")
        base_state, base_code = get_scoping_v2_state(
            cdir, selected_module_ids=req_mids, software_spec=body.get("software_spec"),
            paper_spec=body.get("paper_spec"), analysis_id=body.get("analysis_id"), anchor_root=anchor_root, require_v6=True,
        )
        if base_code != 200:
            return base_state, base_code

        modules = list((base_state.get("software_map") or {}).get("modules") or [])
        prev_selected = list((base_state.get("receipt") or {}).get("selected_module_ids") or [])
        cur_selected = list(prev_selected)
        msg_clean = raw_msg.strip()
        msg_low = msg_clean.lower()

        if msg_clean:
            if _SCOPING_RESTORE_RE.search(msg_low):
                cur_selected = [str(m["module_id"]) for m in modules if m.get("role") in {"core_estimator", "table_replicators"}] or cur_selected
            else:
                wants_ex, wants_in = bool(_SCOPING_EXCLUDE_RE.search(msg_low)), bool(_SCOPING_INCLUDE_RE.search(msg_low))
                for m in modules:
                    mid = str(m["module_id"])
                    t_low, r_low = str(m.get("title") or "").lower(), str(m.get("role") or "").lower()
                    hit = (
                        bool(re.search(rf"\b{re.escape(mid)}\b", msg_low))
                        or (r_low == "simulation" and bool(re.search(r"\bsimulat\w*\b", msg_low)))
                        or (r_low == "data_etl" and bool(re.search(r"\b(?:etl|plumbing|prep)\b", msg_low)))
                        or (len(t_low) >= 6 and bool(re.search(rf"\b{re.escape(t_low)}\b", msg_low)))
                    )
                    if hit:
                        if wants_ex and mid in cur_selected and len(cur_selected) > 1:
                            cur_selected = [x for x in cur_selected if x != mid]
                        elif wants_in and mid not in cur_selected:
                            cur_selected.append(mid)

        if cur_selected != prev_selected:
            updated_state, upd_code = get_scoping_v2_state(
                cdir, selected_module_ids=cur_selected, software_spec=(base_state.get("receipt") or {}).get("software_spec"),
                paper_spec=(base_state.get("receipt") or {}).get("paper_spec"), analysis_id=body.get("analysis_id"),
                anchor_root=anchor_root, require_v6=True,
            )
            if upd_code != 200:
                return updated_state, upd_code
        else:
            updated_state = base_state

        state_file = _as._scoping_state_file(cdir)
        with _as.exclusive_file_lock(state_file):
            existing_doc = read_optional_scoping_json(state_file, _as.ANVIL_SCOPING_STATE_SCHEMA) or {}
            eff_gandalf = bool(gandalf_raw) if gandalf_raw is not None else bool(existing_doc.get("gandalf_enabled", True))
            turns = list(existing_doc.get("dialogue_turns") or updated_state.get("dialogue_turns") or [])
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            new_sha = str(updated_state.get("scope_sha256") or "")
            sel_ids_final = list((updated_state.get("receipt") or {}).get("selected_module_ids") or [])
            if msg_clean:
                turns.append({"role": "user", "speaker": "Operator", "text": msg_clean, "ts": now_iso})
                turns.append({
                    "role": "steward", "speaker": "Steward + Gandalf" if eff_gandalf else "Steward",
                    "text": f"Updated proposed scope to `{len(sel_ids_final)}` module(s) (`{', '.join(sel_ids_final) or 'none'}`) · receipt `sha256={new_sha[:16]}…`.",
                    "gandalf_note": "Gandalf check: verify every paper Table/Figure replicator you intend to audit remains in `In Proposed Scope` before locking." if eff_gandalf else "",
                    "ts": now_iso,
                })
            to_save = {
                "schema": _as.ANVIL_SCOPING_STATE_SCHEMA,
                "software_spec": (updated_state.get("receipt") or {}).get("software_spec", "."),
                "paper_spec": (updated_state.get("receipt") or {}).get("paper_spec", ""),
                "selected_module_ids": sel_ids_final, "gandalf_enabled": eff_gandalf,
                "direction": msg_clean if msg_clean else str(existing_doc.get("direction") or ""),
                "dialogue_turns": turns[-40:], "updated_at": now_iso,
            }
            _as._atomic_write_text(state_file, json.dumps(to_save, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

        updated_state["gandalf_enabled"] = eff_gandalf
        updated_state["dialogue_turns"] = to_save["dialogue_turns"]
        return updated_state, 200
    except _as.AnvilAnalysisRefusalError as a_err:
        return (a_err.payload, a_err.http_status)
    except TimeoutError as t_exc:
        return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(t_exc), anchor_root=anchor_root)


def lock_scope_v2(
    cockpit_dir: str | Path, body: Dict[str, Any], *, anchor_root: Path | str | None = None, max_bundle_bytes: Optional[int] = None,
) -> Tuple[Dict[str, Any], int]:
    if not _as.is_anvil_v6_enabled(anchor_root):
        return _as._build_v6_disabled_refusal()
    if not isinstance(body, dict):
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)
    if "max_bundle_bytes" in body:
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", detail="Client override of max_bundle_bytes is forbidden.", anchor_root=anchor_root)
    eff_bundle_cap = min(max(1024, int(max_bundle_bytes if max_bundle_bytes is not None else _as.MAX_SCOPE_BUNDLE_BYTES)), _as.MAX_SCOPE_BUNDLE_BYTES)

    raw_dir = "" if body.get("direction") is None else body.get("direction", "")
    dir_err = _check_direction_bound(raw_dir, anchor_root)
    if dir_err is not None:
        return dir_err

    cdir = Path(cockpit_dir).resolve()
    v4_mods = _as._load_anvil_v4_modules()
    if _as.anvil_engine is None or not v4_mods:
        return _as.build_v5_failure_response("dependency-missing", anchor_root=anchor_root)
    v4_proc = v4_mods["anvil_v4_process"]

    try:
        _as._check_anvil_containment_links(cdir)
        clean_aid = _as.validate_analysis_id(body.get("analysis_id"), allow_none=True)
        raw_mids = body["module_ids"] if "module_ids" in body else body.get("selected_module_ids")
        prelim_sel = validate_opaque_module_ids(raw_mids, None) if raw_mids is not None else None
        if prelim_sel is not None and len(prelim_sel) == 0:
            return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="EMPTY_MODULE_SELECTION_REFUSED", detail="Select at least one architectural module before locking scope.", anchor_root=anchor_root)

        persisted_sc = read_optional_scoping_json(_as._scoping_state_file(cdir), _as.ANVIL_SCOPING_STATE_SCHEMA) or {}
        existing_slot_meta: Dict[str, Any] = {}
        if clean_aid is not None and _as._analyses_index_file(cdir).is_file():
            idx_peek = _as._read_analyses_index(cdir) or {}
            existing_slot_meta = next((dict(e) for e in (idx_peek.get("analyses") or []) if isinstance(e, dict) and str(e.get("analysis_id") or "") == clean_aid), {})

        raw_sw_in = body["software_spec"] if ("software_spec" in body and body["software_spec"] is not None) else (body["software_target"] if ("software_target" in body and body["software_target"] is not None) else (existing_slot_meta.get("software_spec") or persisted_sc.get("software_spec")))
        raw_pp_in = body["paper_spec"] if ("paper_spec" in body and body["paper_spec"] is not None) else (body["paper_target"] if ("paper_target" in body and body["paper_target"] is not None) else (existing_slot_meta.get("paper_spec") if "paper_spec" in existing_slot_meta else persisted_sc.get("paper_spec")))

        sw_dir, norm_sw_spec = resolve_scoping_v2_local_dir(cdir, raw_sw_in)
        paper_p, norm_paper_spec = resolve_scoping_v2_paper_path(cdir, sw_dir, raw_pp_in)
        sibling_dirs = _discover_contained_sibling_code_dirs(cdir, sw_dir)

        arch_map = v4_proc.build_software_architecture_paper_map(
            sw_dir, paper_path=paper_p, sibling_repos=sibling_dirs, selected_module_ids=prelim_sel, cockpit_root=cdir,
        )
        valid_ids = {str(m["module_id"]) for m in (arch_map.get("modules") or [])}
        if raw_mids is not None:
            validate_opaque_module_ids(raw_mids, valid_ids)

        sel_mids = sorted(arch_map.get("selected_module_ids") or [])
        in_scope_files = sorted(arch_map.get("in_scope_files") or [])
        if not in_scope_files:
            return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="EMPTY_SCOPE_FILES_REFUSED", detail="Selected modules resolved to 0 contained source files.", anchor_root=anchor_root)

        total_src_bytes = 0
        for rel_f in in_scope_files:
            fp = sw_dir / rel_f
            if _as._is_symlink_or_junction(fp):
                _refuse_garbage("PATH_ESCAPE_REFUSED", f"Symlink or junction file '{rel_f}' refused.", http_status=403)
            if fp.is_file():
                total_src_bytes += int(fp.stat().st_size)
        if total_src_bytes > eff_bundle_cap:
            msg_b = f"In-scope source bundle ({total_src_bytes} bytes) exceeds {eff_bundle_cap} byte cap."
            return ({
                "ok": False, "anvil_v6_enabled": _as.is_anvil_v6_enabled(anchor_root), "error_code": "BOUND_EXCEEDED_REFUSAL",
                "status_kind": "dependency-returns-garbage", "failure_state": "dependency-returns-garbage", "http_status": 400,
                "bound_name": "MAX_SCOPE_BUNDLE_BYTES", "bound_limit": eff_bundle_cap, "observed_value": total_src_bytes,
                "message": msg_b, "error": msg_b,
            }, 400)

        locked_eps = list(arch_map.get("entrypoints") or [])
        manifest_json, scope_sha256 = v4_proc.compute_scope_manifest(
            sw_dir, scope_files=in_scope_files, selected_module_ids=sel_mids, entrypoints=locked_eps or None,
            paper_paths=[paper_p] if paper_p is not None else None, cockpit_root=cdir, max_bundle_bytes=eff_bundle_cap,
        )
        manifest_obj = json.loads(manifest_json)
        create_new = bool(body.get("create_new", False))
        raw_title = str(body.get("title") or "").strip()

        idx_file = _as._analyses_index_file(cdir)
        with _as.exclusive_file_lock(idx_file, timeout_sec=20.0):
            with _as._ANALYSES_INDEX_CACHE_LOCK:
                _as._ANALYSES_INDEX_CACHE.clear()
            idx_doc = _as._read_analyses_index(cdir)
            if idx_doc is None and _as._session_file(cdir).is_file():
                reg_res, reg_code = _as.register_legacy_analysis(cdir, anchor_root=anchor_root)
                if reg_code != 200:
                    return reg_res, reg_code
                idx_doc = _as._read_analyses_index(cdir)

            cur_entries = [dict(e) for e in ((idx_doc or {}).get("analyses") or []) if isinstance(e, dict)]
            live_entries = [e for e in cur_entries if not e.get("archived")]

            if clean_aid is None and not create_new:
                for ent in live_entries:
                    ent_store = _as._validate_index_entry_store(cdir, ent)
                    if (
                        str(ent.get("scope_sha256") or "") == scope_sha256
                        and sorted(ent.get("selected_module_ids") or []) == sel_mids
                        and str(ent.get("software_spec") or ".") == norm_sw_spec
                        and str(ent.get("paper_spec") or "") == norm_paper_spec
                        and (_as._session_dir(ent_store) / "scope_manifest.json").is_file()
                        and _as._session_file(ent_store).is_file()
                    ):
                        reused_aid = str(ent["analysis_id"])
                        upd_idx = dict(idx_doc or {"schema": _as.ANVIL_ANALYSES_INDEX_SCHEMA, "analyses": cur_entries})
                        upd_idx["active_analysis_id"] = reused_aid
                        upd_idx["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        _as._write_analyses_index(cdir, upd_idx)
                        st_payload, st_code = _as.get_v4_cockpit_state(cdir, analysis_id=reused_aid, anchor_root=anchor_root)
                        if st_code == 200:
                            st_payload.update({"idempotent_reuse": True, "scope_sha256": scope_sha256, "selected_module_ids": sel_mids})
                        return st_payload, st_code

            existing_ids = {str(e.get("analysis_id") or "") for e in cur_entries}
            if clean_aid is not None:
                eff_aid = clean_aid
                any_existing = next((e for e in cur_entries if str(e.get("analysis_id") or "") == eff_aid), None)
                if any_existing is not None and any_existing.get("archived"):
                    raise _as.AnvilAnalysisRefusalError("ARCHIVED_ANALYSIS_REFUSED", f"Analysis '{eff_aid}' is archived and cannot be overwritten.", http_status=409)
                matched_existing = any_existing
            else:
                matched_existing = None
                slug_base = re.sub(r"[^a-z0-9]+", "-", (raw_title or (paper_p.stem if paper_p else sw_dir.name)).lower()).strip("-")[:32] or "scope"
                seq = len(cur_entries) + 1
                eff_aid = f"scope-{seq}-{slug_base}-{scope_sha256[:8]}"[:64].rstrip("-")
                while eff_aid in existing_ids:
                    seq += 1
                    eff_aid = f"scope-{seq}-{slug_base}-{scope_sha256[:8]}"[:64].rstrip("-")

            max_slots = _as.MAX_COCKPIT_ANALYSES
            if matched_existing is None and len(live_entries) >= max_slots:
                raise _as.AnvilAnalysisRefusalError(
                    "BOUND_EXCEEDED_REFUSAL", f"Maximum of {max_slots} non-archived scopes per cockpit exceeded.",
                    http_status=400, extra={"bound_name": "MAX_COCKPIT_ANALYSES", "bound_limit": max_slots, "observed_value": len(live_entries)},
                )

            created_store_dir = False
            if matched_existing is not None:
                store_root = _as._validate_index_entry_store(cdir, matched_existing)
                store_rel = str(matched_existing.get("store") or f"analyses/{eff_aid}")
            else:
                cand_sub = _as._analyses_dir(cdir) / eff_aid
                if _as._is_symlink_or_junction(cand_sub):
                    _refuse_garbage("PATH_ESCAPE_REFUSED", f"Symlink or junction analysis directory '{eff_aid}' refused.", http_status=403)
                created_store_dir = not cand_sub.exists()
                store_rel, store_root = f"analyses/{eff_aid}", cand_sub.resolve()

            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            sm_dest = _as._session_dir(store_root) / "scope_manifest.json"
            prev_sm_text = sm_dest.read_text(encoding="utf-8") if sm_dest.is_file() else None
            _as._atomic_write_text(sm_dest, json.dumps({
                "schema": _as.ANVIL_SCOPE_LOCK_SCHEMA, "analysis_id": eff_aid, "scope_sha256": scope_sha256,
                "selected_module_ids": sel_mids, "scope_files": in_scope_files, "entrypoints": locked_eps,
                "software_spec": norm_sw_spec, "paper_spec": norm_paper_spec, "locked_at": now_iso, "manifest": manifest_obj,
            }, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

            eff_title = raw_title or (f"{sw_dir.name} · {paper_p.name} ({len(sel_mids)} mod)" if paper_p is not None else f"{sw_dir.name} ({len(sel_mids)} mod)")
            try:
                built_status = _as._populate_store_root_session(
                    cdir=cdir, store_root=store_root, analysis_id=eff_aid, title=eff_title[:120],
                    mode="paper" if paper_p is not None else "code", software_spec=norm_sw_spec, paper_spec=norm_paper_spec,
                    direction=raw_dir, materialize_replication_package=True, max_concurrency=2, persist_v5_cache=False,
                    scope_files=in_scope_files, entrypoints=locked_eps,
                )
                sess_ir = built_status.get("session") or _as._read_session_ir(_as._session_file(store_root))
                v4_bundle = _as._build_cockpit_v4_bundle(
                    cdir, sess_ir, store_root=store_root, analysis_id=eff_aid, persist_artifacts=True,
                    persist_disk_cache=True, max_cache_bytes=eff_bundle_cap, anchor_root=anchor_root,
                )
            except Exception as build_exc:
                if matched_existing is None and created_store_dir and store_root != cdir.resolve():
                    shutil.rmtree(store_root, ignore_errors=True)
                elif matched_existing is not None:
                    if prev_sm_text is not None:
                        with contextlib.suppress(Exception):
                            _as._atomic_write_text(sm_dest, prev_sm_text)
                    elif sm_dest.is_file():
                        with contextlib.suppress(OSError):
                            sm_dest.unlink()
                if isinstance(build_exc, _as.AnvilAnalysisRefusalError):
                    return (build_exc.payload, build_exc.http_status)
                raise

            new_entry = {
                "analysis_id": eff_aid, "title": eff_title[:120], "store": store_rel,
                "mode": "paper" if paper_p is not None else "code", "software_spec": norm_sw_spec, "paper_spec": norm_paper_spec,
                "active_pipeline": "", "selected_pipelines": [], "selected_module_ids": sel_mids,
                "scope_sha256": scope_sha256, "scope_drifted": False, "in_scope_file_count": len(in_scope_files),
                "has_replication_report": False, "materialize_replication_package": True, "max_concurrency": 2,
                "direction": raw_dir, "archived": False,
                "created_at": str(matched_existing.get("created_at") if matched_existing else now_iso), "updated_at": now_iso,
            }
            merged = [new_entry if str(ent.get("analysis_id") or "") == eff_aid else ent for ent in cur_entries]
            if not any(str(ent.get("analysis_id") or "") == eff_aid for ent in cur_entries):
                merged.append(new_entry)
            _as._write_analyses_index(cdir, {"schema": _as.ANVIL_ANALYSES_INDEX_SCHEMA, "active_analysis_id": eff_aid, "updated_at": now_iso, "analyses": merged})
            _as._SUMMARY_STATUS_CACHE.clear()

        analyses_out, _ = _as.list_cockpit_analyses(cdir, anchor_root=anchor_root)
        return ({
            "ok": True, "active": True, "idempotent_reuse": False, "cockpit_dir": str(cdir),
            "cockpit_name": _as._cockpit_display_name(cdir), "analysis_id": eff_aid, "active_analysis_id": eff_aid,
            "multi_analysis_enabled": True, "anvil_v6_enabled": _as.is_anvil_v6_enabled(anchor_root),
            "scope_sha256": scope_sha256, "scope_drifted": False, "selected_module_ids": sel_mids, "in_scope_files": in_scope_files,
            "analyses": analyses_out.get("analyses", []), "surface_state": v4_bundle["surface_state"],
            "status_kind": v4_bundle["status_kind"], "state": v4_bundle["badge"], "badge": v4_bundle["badge"],
            "message": v4_bundle["message"], "unknown_state": False, "v4_bundle": v4_bundle, "bundle": v4_bundle,
        }, 200)
    except _as.AnvilAnalysisRefusalError as a_err:
        return (a_err.payload, a_err.http_status)
    except v4_proc.AnvilRefusalError as v_err:
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=403 if v_err.error_code == "PATH_ESCAPE_REFUSED" else 400, error_code=v_err.error_code, detail=v_err.message, anchor_root=anchor_root)
    except TimeoutError as t_exc:
        return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(t_exc), anchor_root=anchor_root)


def validate_scholarly_https_url(url: Any) -> str:
    """Strict CWE-918 scholarly `https://` allowlist check BEFORE any DNS or socket call."""
    if not isinstance(url, str) or not url.strip() or "\r" in url or "\n" in url or "\x00" in url:
        raise _as.AnvilAnalysisRefusalError("SSRF_DOMAIN_REFUSED", "Scholarly URL must be a clean https:// string on the scholarly allowlist.", http_status=403, extra={"cwe": "CWE-918"})
    s = url.strip()
    parsed = urllib.parse.urlparse(s)
    if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
        raise _as.AnvilAnalysisRefusalError("SSRF_DOMAIN_REFUSED", f"Only credential-free https:// scholarly endpoints are permitted (refused scheme '{parsed.scheme}').", http_status=403, extra={"cwe": "CWE-918"})
    try:
        port_num = parsed.port
    except ValueError as p_exc:
        raise _as.AnvilAnalysisRefusalError("SSRF_DOMAIN_REFUSED", "Malformed port in scholarly URL.", http_status=403, extra={"cwe": "CWE-918"}) from p_exc
    if port_num not in (None, 443):
        raise _as.AnvilAnalysisRefusalError("SSRF_DOMAIN_REFUSED", f"Non-443 port ({port_num}) refused for scholarly fetch.", http_status=403, extra={"cwe": "CWE-918"})
    host = (parsed.hostname or "").strip().lower()
    if host not in _as.SCHOLARLY_HTTPS_ALLOWLIST:
        raise _as.AnvilAnalysisRefusalError("SSRF_DOMAIN_REFUSED", f"Host '{host}' is not in the scholarly HTTPS allowlist ({', '.join(_as.SCHOLARLY_HTTPS_ALLOWLIST)}).", http_status=403, extra={"cwe": "CWE-918", "host": host})
    return s


class _ScholarlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        validate_scholarly_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _scholarly_safe_urlopen(url: str, *, max_bytes: int = 262_144, timeout: float = 8.0) -> Tuple[bytes, str]:
    validate_scholarly_https_url(url)
    opener = urllib.request.build_opener(_ScholarlyRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": "Anchor-Anvil-Scholarly/1.0"})
    t0, total, chunks = time.monotonic(), 0, []
    with opener.open(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        while total < max_bytes:
            if (time.monotonic() - t0) > timeout:
                raise TimeoutError("Timed out reading scholarly response.")
            chunk = resp.read(min(32768, max_bytes - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks), ctype


def run_quick_literature_sketch(
    cockpit_dir: str | Path, body: Dict[str, Any], *, anchor_root: Path | str | None = None, scholarly_urlopen: Optional[Any] = None,
) -> Tuple[Dict[str, Any], int]:
    if not _as.is_anvil_v6_enabled(anchor_root):
        return _as._build_v6_disabled_refusal()
    if not isinstance(body, dict):
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)
    if "scholarly_urlopen" in body:
        return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=403, error_code="EXECUTION_POLICY_REFUSED", anchor_root=anchor_root)
    if body.get("operator_consent") is not True and body.get("operator_consent_confirmed") is not True:
        msg_c = "Explicit operator_consent: true from #btnRpToggle is required for Quick Literature Sketch."
        return ({"ok": False, "anvil_v6_enabled": True, "error_code": "CONSENT_REQUIRED_REFUSED", "http_status": 403, "message": msg_c, "error": msg_c}, 403)

    cdir = Path(cockpit_dir).resolve()
    try:
        raw_urls = body.get("scholarly_urls")
        validated_urls: List[str] = []
        if raw_urls is not None:
            if not isinstance(raw_urls, list) or len(raw_urls) > 4:
                return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=400, error_code="MALFORMED_DATA_REFUSED", anchor_root=anchor_root)
            validated_urls = [validate_scholarly_https_url(u) for u in raw_urls]
        elif "scholarly_url" in body and body["scholarly_url"] is not None:
            validated_urls.append(validate_scholarly_https_url(body["scholarly_url"]))

        base_state, base_code = get_scoping_v2_state(
            cdir, selected_module_ids=body.get("module_ids") if "module_ids" in body else body.get("selected_module_ids"),
            software_spec=body.get("software_spec"), paper_spec=body.get("paper_spec"), anchor_root=anchor_root, require_v6=True,
        )
        if base_code != 200:
            return base_state, base_code

        modules = list((base_state.get("software_map") or {}).get("modules") or [])
        target_mids = set((base_state.get("receipt") or {}).get("selected_module_ids") or []) or {str(m["module_id"]) for m in modules[:3]}
        fetched_titles: List[str] = []
        queried_url: Optional[str] = None
        model_calls_made = 0

        if callable(scholarly_urlopen) or (body.get("live") is True):
            if not validated_urls:
                q_terms = "+".join(re.sub(r"[^a-z0-9]+", "+", str(m.get("title") or "").lower()).strip("+") for m in modules if str(m["module_id"]) in target_mids)[:80] or "statistical+estimation"
                validated_urls = [f"https://api.openalex.org/works?search={q_terms}&per-page=3"]
            queried_url = validate_scholarly_https_url(validated_urls[0])
            model_calls_made = 1
            try:
                raw_b, _ = scholarly_urlopen(queried_url, timeout=8.0) if callable(scholarly_urlopen) else _scholarly_safe_urlopen(queried_url, max_bytes=262_144, timeout=8.0)
                doc_j = json.loads(raw_b.decode("utf-8", errors="strict"))
                if not isinstance(doc_j, dict):
                    raise ValueError("Scholarly endpoint returned non-object JSON.")
                fetched_titles = [str(item["title"])[:140] for item in (doc_j.get("results") or doc_j.get("data") or [])[:3] if isinstance(item, dict) and item.get("title")]
            except _as.AnvilAnalysisRefusalError:
                raise
            except (TimeoutError, socket.timeout) as t_err:
                return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(t_err), anchor_root=anchor_root)
            except urllib.error.URLError as u_err:
                if isinstance(getattr(u_err, "reason", None), (TimeoutError, socket.timeout)):
                    return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(u_err), anchor_root=anchor_root)
                return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=502, error_code="SCHOLARLY_FETCH_FAILED", detail=str(u_err), anchor_root=anchor_root)
            except Exception as f_err:
                return _as.build_v5_failure_response("dependency-returns-garbage", http_status_override=502, error_code="SCHOLARLY_FETCH_FAILED", detail=str(f_err), anchor_root=anchor_root)

        overlays: Dict[str, Dict[str, Any]] = {}
        for m in modules:
            mid = str(m["module_id"])
            if mid not in target_mids:
                continue
            m_title = str(m.get("title") or mid)
            cites = list(fetched_titles) if fetched_titles else [f"Methodological reference family for {m_title} (promote to researchPrime for verified bibliography)"]
            overlays[mid] = {
                "module_id": mid, "status": "claimed", "posture": "CLAIMED", "label": "CLAIMED / unverified",
                "verified": False, "summary": (f"[CLAIMED / unverified] Orientation sketch for {m_title}: " + "; ".join(cites[:2]))[:360],
                "citations": cites[:3],
            }

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _as._atomic_write_text(_as._literature_cache_file(cdir), json.dumps({
            "schema": _as.ANVIL_LITERATURE_CACHE_SCHEMA, "status": "claimed", "posture": "CLAIMED", "label": "CLAIMED / unverified",
            "verified": False, "model_calls": model_calls_made, "queried_url": queried_url, "updated_at": now_iso, "overlays": overlays,
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

        refreshed, ref_code = get_scoping_v2_state(
            cdir, selected_module_ids=sorted(target_mids), software_spec=(base_state.get("receipt") or {}).get("software_spec"),
            paper_spec=(base_state.get("receipt") or {}).get("paper_spec"), analysis_id=body.get("analysis_id"), anchor_root=anchor_root, require_v6=True,
        )
        if ref_code == 200:
            refreshed["literature_sketch_receipt"] = {"status": "claimed", "posture": "CLAIMED", "label": "CLAIMED / unverified", "verified": False, "model_calls": model_calls_made, "queried_url": queried_url}
        return refreshed, ref_code
    except _as.AnvilAnalysisRefusalError as a_err:
        return (a_err.payload, a_err.http_status)
    except TimeoutError as t_exc:
        return _as.build_v5_failure_response("dependency-slow-or-killed", detail=str(t_exc), anchor_root=anchor_root)


_LOADED_MTIME_NS = Path(__file__).stat().st_mtime_ns
