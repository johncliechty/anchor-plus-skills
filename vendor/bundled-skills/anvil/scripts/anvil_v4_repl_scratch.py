#!/usr/bin/env python3
"""Anvil v6 Isolated Scratch Table Replication Runner & Unified-Diff AST Sink Gate (`anvil_v4_repl_scratch.py`).

Extracted from `anvil_v4_trace.py` to keep tracer and scratch-replication modules compact and cohesive.
Enforces `sys.executable` interpreter pinning, priority `extra_site_packages` (`runtime_env.json`),
`<= 2 GB` allowlisted data staging, AST sink checks on Phase-B unified diffs, and explicit
`PIPELINE_DEPENDENCY_MISSING` classification.
"""
from __future__ import annotations

import ast
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from anvil_v4_process import (
    AnvilRefusalError,
    _is_link_or_junction,
    resolve_contained_path,
)

ISOLATION_BOUNDARY = "consented_local_subprocess"
MAX_REPLICATION_TABLE_TIMEOUT_SEC = 1800.0
MAX_REPLICATION_TOTAL_TIMEOUT_SEC = 5400.0
MAX_ALLOWLISTED_DATA_BYTES = 2 * 1024 * 1024 * 1024
REPLICATION_TABLE_RECEIPT_SCHEMA = "anvil-v6-replication-table-receipt/v1"

_FORBIDDEN_PATCH_IMPORTS: Set[str] = {
    "subprocess", "pickle", "marshal", "shelve", "socket", "urllib", "http", "ctypes",
}
_FORBIDDEN_PATCH_ATTRS: Set[str] = {
    "os.system", "os.popen", "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_output", "pickle.load", "pickle.loads", "torch.load", "shutil.rmtree",
}


def _check_python_ast_sinks_safe(py_source: str, rel_path: str) -> None:
    """Verify patched Python code in scratch introduces zero dangerous execution/deserialization/network sinks."""
    try:
        tree = ast.parse(py_source, filename=rel_path)
    except SyntaxError as sexc:
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            f"Candidate unified diff produced invalid Python syntax in '{rel_path}': {sexc}",
            details={"http_status": 400, "file": rel_path},
        ) from sexc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in _FORBIDDEN_PATCH_IMPORTS:
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Candidate patch imports forbidden sink module '{top}' in '{rel_path}'.",
                        cwe="CWE-94",
                        details={"http_status": 403, "sink": top},
                    )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            if top in _FORBIDDEN_PATCH_IMPORTS or (top == "os" and any(a.name in {"system", "popen"} for a in node.names)):
                raise AnvilRefusalError(
                    "EXECUTION_POLICY_REFUSED",
                    f"Candidate patch imports from forbidden sink module '{top}' in '{rel_path}'.",
                    cwe="CWE-94",
                    details={"http_status": 403, "sink": top},
                )
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in {"eval", "exec", "compile", "__import__", "system", "popen"}:
                raise AnvilRefusalError(
                    "EXECUTION_POLICY_REFUSED",
                    f"Candidate patch calls forbidden dynamic primitive '{fn.id}' in '{rel_path}'.",
                    cwe="CWE-94",
                    details={"http_status": 403, "sink": fn.id},
                )
            if isinstance(fn, ast.Attribute):
                base_id = fn.value.id if isinstance(fn.value, ast.Name) else ""
                qual = f"{base_id}.{fn.attr}" if base_id else fn.attr
                if qual in _FORBIDDEN_PATCH_ATTRS:
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Candidate patch invokes forbidden sink '{qual}' in '{rel_path}'.",
                        cwe="CWE-94",
                        details={"http_status": 403, "sink": qual},
                    )
            for kw in node.keywords:
                if kw.arg == "allow_pickle" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Candidate patch enables allow_pickle in '{rel_path}'.",
                        cwe="CWE-502",
                        details={"http_status": 403, "sink": "allow_pickle"},
                    )


def _apply_unified_diff_in_scratch(
    work_repo: Path,
    unified_diff: str,
    expected_diff_sha256: str = "",
) -> List[str]:
    """Verify `diff_sha256`, apply a contained unified diff inside `work_repo` ONLY, and enforce AST sink safety."""
    actual_sha = hashlib.sha256(unified_diff.encode("utf-8")).hexdigest()
    if expected_diff_sha256 and actual_sha != expected_diff_sha256.strip().lower():
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            "Candidate unified diff SHA-256 does not match consented diff_sha256.",
            details={"http_status": 400, "expected": expected_diff_sha256, "observed": actual_sha},
        )

    lines = unified_diff.splitlines()
    hunk_hdr_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
    touched_files: List[str] = []
    idx = 0
    while idx < len(lines):
        ln = lines[idx]
        if not ln.startswith("--- "):
            idx += 1
            continue
        if idx + 1 >= len(lines) or not lines[idx + 1].startswith("+++ "):
            raise AnvilRefusalError("MALFORMED_DATA_REFUSED", "Malformed unified diff header.", details={"http_status": 400})
        plus_target = lines[idx + 1][4:].strip().split("\t", 1)[0]
        if plus_target.startswith(("b/", "a/")):
            plus_target = plus_target[2:]
        target_fp = resolve_contained_path(work_repo, plus_target, must_be_relative=True)
        rel_posix = target_fp.relative_to(work_repo).as_posix()
        if not target_fp.is_file():
            raise AnvilRefusalError("MALFORMED_DATA_REFUSED", f"Diff target '{rel_posix}' not found in scratch worktree.", details={"http_status": 400})
        orig_lines = target_fp.read_text(encoding="utf-8").splitlines()
        out_lines: List[str] = []
        orig_pos = 0
        idx += 2
        applied_any = False
        while idx < len(lines) and not lines[idx].startswith("--- "):
            hm = hunk_hdr_re.match(lines[idx])
            if not hm:
                idx += 1
                continue
            applied_any = True
            start_old = max(0, int(hm.group(1)) - 1)
            if start_old < orig_pos or start_old > len(orig_lines):
                raise AnvilRefusalError("MALFORMED_DATA_REFUSED", f"Invalid hunk offset in '{rel_posix}'.", details={"http_status": 400})
            out_lines.extend(orig_lines[orig_pos:start_old])
            orig_pos = start_old
            idx += 1
            while idx < len(lines) and not lines[idx].startswith(("--- ", "@@ ")):
                hl = lines[idx]
                if hl.startswith("\\"):
                    idx += 1
                    continue
                if hl.startswith(" "):
                    exp_txt = hl[1:]
                    if orig_pos >= len(orig_lines) or orig_lines[orig_pos] != exp_txt:
                        raise AnvilRefusalError("MALFORMED_DATA_REFUSED", f"Diff context mismatch in '{rel_posix}'.", details={"http_status": 400})
                    out_lines.append(exp_txt)
                    orig_pos += 1
                elif hl.startswith("-"):
                    exp_txt = hl[1:]
                    if orig_pos >= len(orig_lines) or orig_lines[orig_pos] != exp_txt:
                        raise AnvilRefusalError("MALFORMED_DATA_REFUSED", f"Diff removal mismatch in '{rel_posix}'.", details={"http_status": 400})
                    orig_pos += 1
                elif hl.startswith("+"):
                    out_lines.append(hl[1:])
                else:
                    break
                idx += 1
        if not applied_any:
            raise AnvilRefusalError("MALFORMED_DATA_REFUSED", f"Diff for '{rel_posix}' contained zero hunks.", details={"http_status": 400})
        out_lines.extend(orig_lines[orig_pos:])
        new_src = "\n".join(out_lines) + "\n"
        if target_fp.suffix.lower() == ".py":
            _check_python_ast_sinks_safe(new_src, rel_posix)
        target_fp.write_text(new_src, encoding="utf-8")
        if rel_posix not in touched_files:
            touched_files.append(rel_posix)

    if not touched_files:
        raise AnvilRefusalError("MALFORMED_DATA_REFUSED", "Candidate unified diff modified zero files.", details={"http_status": 400})
    return touched_files


def _spawn_scratch_in_job(spawn_argv: Sequence[str], cwd: Path, env: Dict[str, str]) -> Tuple[subprocess.Popen[bytes], int]:
    flags = (0x08000000 | 0x4) if os.name == "nt" else 0
    proc = subprocess.Popen(list(spawn_argv), cwd=str(cwd), env=env, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=(os.name != "nt"), creationflags=flags)
    if os.name != "nt":
        return proc, 0

    class _IO_CNT(ctypes.Structure):
        _fields_ = [("r_op", ctypes.c_ulonglong), ("w_op", ctypes.c_ulonglong), ("o_op", ctypes.c_ulonglong), ("r_tr", ctypes.c_ulonglong), ("w_tr", ctypes.c_ulonglong), ("o_tr", ctypes.c_ulonglong)]

    class _BASIC_LIM(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _EXT_LIM(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIM), ("IoInfo", _IO_CNT), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32, ntdll = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("ntdll", use_last_error=True)
    k32.CreateJobObjectW.argtypes, k32.CreateJobObjectW.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
    k32.SetInformationJobObject.argtypes, k32.SetInformationJobObject.restype = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes, k32.AssignProcessToJobObject.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
    k32.TerminateJobObject.argtypes, k32.TerminateJobObject.restype = [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL
    k32.CloseHandle.argtypes, k32.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    ntdll.NtResumeProcess.argtypes, ntdll.NtResumeProcess.restype = [wintypes.HANDLE], ctypes.c_long
    job_h = k32.CreateJobObjectW(None, None)
    info = _EXT_LIM()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (no BREAKAWAY_OK)
    if not job_h or not k32.SetInformationJobObject(job_h, 9, ctypes.byref(info), ctypes.sizeof(info)) or not k32.AssignProcessToJobObject(job_h, wintypes.HANDLE(int(proc._handle))):
        proc.kill()
        proc.communicate()
        if job_h:
            k32.CloseHandle(job_h)
        raise RuntimeError("Failed to bind scratch replication process to Win32 Kill-on-Close Job Object.")
    if ntdll.NtResumeProcess(wintypes.HANDLE(int(proc._handle))) < 0:
        k32.TerminateJobObject(job_h, 1)
        k32.CloseHandle(job_h)
        proc.kill()
        proc.communicate()
        raise RuntimeError("NtResumeProcess failed on scratch replication process.")
    return proc, int(job_h)


def _terminate_and_close_scratch_job(proc: subprocess.Popen[bytes], job_h: int) -> None:
    if os.name == "nt" and job_h:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.TerminateJobObject.argtypes, k32.CloseHandle.argtypes = [wintypes.HANDLE, wintypes.UINT], [wintypes.HANDLE]
        h = wintypes.HANDLE(int(job_h))
        k32.TerminateJobObject(h, 1)
        k32.CloseHandle(h)
    elif os.name != "nt" and proc.pid:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass


def discover_priority_and_host_site_packages(
    root: Path,
    cockpit_root: Optional[Path] = None,
    store_root: Optional[Path] = None,
    verified_extra_site_packages: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[str]]:
    _ = (root, cockpit_root, store_root)
    host_site_packages = [
        str(Path(p).resolve())
        for p in sys.path
        if isinstance(p, str) and not p.startswith(("//", "\\\\")) and "site-packages" in p and Path(p).is_dir()
    ]
    try:
        import site as _site_mod
        u_sp = _site_mod.getusersitepackages()
        if isinstance(u_sp, str) and u_sp and not u_sp.startswith(("//", "\\\\")) and Path(u_sp).is_dir():
            u_res = str(Path(u_sp).resolve())
            if u_res not in host_site_packages:
                host_site_packages.append(u_res)
    except Exception:
        pass
    priority_site_packages: List[str] = []
    for extra_sp in (verified_extra_site_packages or ()):
        if not isinstance(extra_sp, str):
            continue
        s_sp = extra_sp.strip()
        if not s_sp or s_sp.startswith(("//", "\\\\")):
            continue
        ep_obj = Path(s_sp)
        if ep_obj.is_absolute() and not _is_link_or_junction(ep_obj) and ep_obj.is_dir():
            ex_res = str(ep_obj.resolve())
            if ex_res not in priority_site_packages:
                priority_site_packages.append(ex_res)
    return priority_site_packages, host_site_packages


def execute_replication_table_in_scratch(
    repo_dir: str | Path,
    argv: Sequence[str],
    *,
    validate_argv_fn: Callable[..., Dict[str, Any]],
    stage_worktree_fn: Callable[..., Path],
    build_env_fn: Callable[[Path], Dict[str, str]],
    kill_tree_fn: Callable[[Any], None],
    approve_run: bool = False,
    timeout_sec: float = 300.0,
    remaining_total_sec: float = MAX_REPLICATION_TOTAL_TIMEOUT_SEC,
    allowlisted_data_roots: Optional[Sequence[str | Path]] = None,
    cockpit_root: Optional[str | Path] = None,
    verified_extra_site_packages: Optional[Sequence[str]] = None,
    max_data_bytes: int = MAX_ALLOWLISTED_DATA_BYTES,
    candidate_diff: str = "",
    candidate_diff_sha256: str = "",
    scope_sha256: str = "",
    on_proc_spawn: Optional[Any] = None,
) -> Dict[str, Any]:
    if not approve_run:
        raise AnvilRefusalError("CONSENT_REQUIRED_REFUSED", "Explicit operator consent is required before executing paper replication in scratch.", details={"http_status": 403, "isolation_boundary": ISOLATION_BOUNDARY})
    if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float)) or not math.isfinite(float(timeout_sec)):
        raise AnvilRefusalError("MALFORMED_DATA_REFUSED", "timeout_sec must be finite numeric.", details={"http_status": 400})
    if float(timeout_sec) <= 0.0 or float(timeout_sec) > MAX_REPLICATION_TABLE_TIMEOUT_SEC:
        raise AnvilRefusalError("BOUND_EXCEEDED_REFUSAL", f"Replication table timeout_sec ({timeout_sec}) must be within (0, {MAX_REPLICATION_TABLE_TIMEOUT_SEC}].", details={"bound_name": "MAX_REPLICATION_TABLE_TIMEOUT_SEC", "bound_limit": MAX_REPLICATION_TABLE_TIMEOUT_SEC, "observed_value": float(timeout_sec), "http_status": 400})
    if isinstance(remaining_total_sec, bool) or not isinstance(remaining_total_sec, (int, float)) or not math.isfinite(float(remaining_total_sec)) or float(remaining_total_sec) <= 0.0 or float(remaining_total_sec) > MAX_REPLICATION_TOTAL_TIMEOUT_SEC:
        raise AnvilRefusalError("BOUND_EXCEEDED_REFUSAL", f"Replication job remaining_total_sec ({remaining_total_sec}) must be within (0, {MAX_REPLICATION_TOTAL_TIMEOUT_SEC}].", details={"bound_name": "MAX_REPLICATION_TOTAL_TIMEOUT_SEC", "bound_limit": MAX_REPLICATION_TOTAL_TIMEOUT_SEC, "observed_value": remaining_total_sec, "http_status": 400})

    root = Path(repo_dir).resolve()
    if _is_link_or_junction(Path(repo_dir)) or not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist or is a link.", cwe="CWE-22", details={"http_status": 403})

    policy_info = validate_argv_fn(root, argv)
    if policy_info["runner_kind"] not in {"python", "pytest"}:
        raise AnvilRefusalError("EXECUTION_POLICY_REFUSED", f"Replication table runner pins strictly to Python sys.executable (refused '{policy_info['runner_kind']}').", cwe="CWE-78", details={"http_status": 403})

    ck_path = Path(cockpit_root).resolve() if (cockpit_root is not None and str(cockpit_root).strip()) else None
    eff_data_roots: Sequence[str | Path] = [] if allowlisted_data_roots is None else list(allowlisted_data_roots)

    scratch_dir = Path(tempfile.mkdtemp(prefix="anvil_v6_repl_"))
    try:
        work_repo = stage_worktree_fn(root, scratch_dir, allowlisted_data_roots=eff_data_roots, cockpit_root=ck_path, max_data_bytes=max_data_bytes)
        patched_files = _apply_unified_diff_in_scratch(work_repo, candidate_diff, candidate_diff_sha256) if candidate_diff else []
        target_rel = policy_info["target_rel_script"]
        if target_rel and not (work_repo / target_rel).is_file():
            raise AnvilRefusalError("EXECUTION_POLICY_REFUSED", f"Target replication script '{target_rel}' is missing or excluded as sensitive.", cwe="CWE-78", details={"http_status": 403})

        scrubbed_env = build_env_fn(scratch_dir / "_home_tmp")
        prio_sp, host_sp = discover_priority_and_host_site_packages(root, cockpit_root=ck_path, verified_extra_site_packages=verified_extra_site_packages)
        scrubbed_env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(p for p in [str(work_repo), *host_sp] if p))
        boot_py = scratch_dir / "_anvil_scratch_boot.py"
        boot_cfg = {
            "work_repo": str(work_repo),
            "host_sp": host_sp,
            "prio_sp": prio_sp,
            "runner_kind": policy_info["runner_kind"],
            "target_abs": str((work_repo / target_rel).resolve()) if target_rel else "",
            "target_rel": target_rel,
            "script_args": list(policy_info["script_args"]),
            "pytest_args": list(policy_info["pytest_args"]),
        }
        (scratch_dir / "_anvil_boot_cfg.json").write_text(json.dumps(boot_cfg), encoding="utf-8")
        boot_py.write_text(
            "import json, os, pathlib, runpy, site, sys\n"
            "cfg = json.loads(pathlib.Path(__file__).with_name('_anvil_boot_cfg.json').read_text(encoding='utf-8'))\n"
            "for _hp in cfg['host_sp']:\n"
            "    if _hp not in sys.path:\n"
            "        sys.path.append(_hp)\n"
            "for _sp in cfg['prio_sp']:\n"
            "    if os.path.isdir(_sp):\n"
            "        site.addsitedir(_sp)\n"
            "# Preserve script_dir, work_repo, then host site-packages ahead of isolated venv so host ABI extensions are never shadowed\n"
            "sdir = str(pathlib.Path(cfg['target_abs']).parent) if cfg['target_abs'] else cfg['work_repo']\n"
            "ordered_head = list(dict.fromkeys([sdir, cfg['work_repo'], *cfg['host_sp']]))\n"
            "tail = [p for p in sys.path if p not in ordered_head and p != str(pathlib.Path(__file__).parent)]\n"
            "sys.path[:] = [*ordered_head, *tail]\n"
            "os.chdir(cfg['work_repo'])\n"
            "if cfg['runner_kind'] == 'pytest':\n"
            "    import pytest\n"
            "    raise SystemExit(pytest.main(cfg['pytest_args']))\n"
            "sys.argv = [cfg['target_rel'], *cfg['script_args']]\n"
            "runpy.run_path(cfg['target_abs'], run_name='__main__')\n",
            encoding="utf-8",
        )
        spawn_argv = [sys.executable, "-B", str(boot_py)]
        eff_timeout = min(float(timeout_sec), float(remaining_total_sec))
        t0 = time.perf_counter()
        proc, job_h = _spawn_scratch_in_job(spawn_argv, work_repo, scrubbed_env)
        try:
            if callable(on_proc_spawn):
                on_proc_spawn(proc)
            try:
                stdout_b, stderr_b = proc.communicate(timeout=eff_timeout)
            except subprocess.TimeoutExpired as tex:
                _terminate_and_close_scratch_job(proc, job_h)
                job_h = 0
                kill_tree_fn(proc)
                try:
                    proc.wait(timeout=5.0)
                except Exception:
                    pass
                raise AnvilRefusalError("REPLICATION_TIMEOUT_REFUSED", f"Replication table timed out after {eff_timeout:.1f}s and process tree was terminated.", details={"status_kind": "dependency-slow-or-killed", "http_status": 504, "timeout_sec": eff_timeout, "tree_killed": True}) from tex
        finally:
            if job_h or os.name != "nt":
                _terminate_and_close_scratch_job(proc, job_h)
                job_h = 0

        elapsed_sec = round(time.perf_counter() - t0, 6)
        stdout_txt = (stdout_b or b"")[:262144].decode("utf-8", errors="replace")[:65536]
        stderr_txt = (stderr_b or b"")[:262144].decode("utf-8", errors="replace")[:65536]
        rc = int(proc.returncode or 0)

        missing_mod = ""
        combined_err = f"{stderr_txt}\n{stdout_txt}"
        m_mod = (
            re.search(r"ModuleNotFoundError:\s*No module named\s+['\"]([^'\"]+)['\"]", combined_err)
            or re.search(r"ImportError:\s*cannot import name\s+[^\n]+from\s+['\"]([^'\"]+)['\"]", combined_err)
            or re.search(r"ImportError:\s*No module named\s+([A-Za-z0-9_.-]+)", combined_err)
        )
        if rc != 0 and m_mod:
            missing_mod = m_mod.group(1).strip()

        parsed_metrics: Dict[str, Any] = {}
        used_cached = False
        has_unseeded = False
        for raw_ln in reversed(stdout_txt.splitlines()):
            s_ln = raw_ln.strip()
            if s_ln.startswith("ANVIL_METRICS_JSON:"):
                s_ln = s_ln[len("ANVIL_METRICS_JSON:"):].strip()
            if s_ln.startswith("{") and s_ln.endswith("}"):
                try:
                    cand_j = json.loads(s_ln)
                    if isinstance(cand_j, dict):
                        if isinstance(cand_j.get("metrics"), dict):
                            parsed_metrics = dict(cand_j["metrics"])
                            used_cached = bool(cand_j.get("used_cached_baseline", False))
                            has_unseeded = bool(cand_j.get("has_unseeded_rng", False))
                        else:
                            parsed_metrics = {k: v for k, v in cand_j.items() if isinstance(v, (int, float, dict)) and not isinstance(v, bool)}
                        if parsed_metrics:
                            break
                except Exception:
                    pass
        if not parsed_metrics:
            for m_kv in re.finditer(r"^\s*([A-Za-z][A-Za-z0-9_.-]{0,48})\s*[:=]\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$", stdout_txt, flags=re.M):
                try:
                    parsed_metrics[m_kv.group(1).lower()] = float(m_kv.group(2))
                except ValueError:
                    pass

        err_class = "PIPELINE_DEPENDENCY_MISSING" if (missing_mod or rc != 0) else ("CACHED_PRECOMPUTED_BASELINE" if used_cached else "EXECUTED_UNCOMPARED")
        summary_str = (
            f"PIPELINE_DEPENDENCY_MISSING ({missing_mod})"
            if missing_mod
            else (", ".join(f"{k}={v}" for k, v in list(parsed_metrics.items())[:3] if isinstance(v, (int, float))) or (f"exit={rc}" if rc != 0 else f"exit=0 ({elapsed_sec:.2f}s)"))
        )
        return {
            "ok": rc == 0, "schema": REPLICATION_TABLE_RECEIPT_SCHEMA, "isolation_boundary": ISOLATION_BOUNDARY,
            "pinned_interpreter": sys.executable, "validated_argv": policy_info["validated_argv"], "script": target_rel,
            "scope_sha256": str(scope_sha256 or "").strip().lower(), "patched_files": patched_files,
            "diff_sha256": hashlib.sha256(candidate_diff.encode("utf-8")).hexdigest() if candidate_diff else "",
            "exit_code": rc, "elapsed_sec": elapsed_sec, "missing_module": missing_mod, "error_class": err_class,
            "used_cached_baseline": used_cached, "has_unseeded_rng": has_unseeded, "metrics": parsed_metrics,
            "output_summary": summary_str, "stdout_preview": stdout_txt[:4096], "stderr_preview": stderr_txt[:4096],
        }
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
