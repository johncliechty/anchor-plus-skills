#!/usr/bin/env python3
"""Anvil v4 Pillar 4 — Consented Local Subprocess Tracer, Execution Policy Gate,
Observer-Safe O(1) Variable Sketcher, Non-Finite Tripwire Detector, and Monotonic
5-Scope 4-Stage Smart Variable Funnel (`scripts/anvil_v4_trace.py`).

Trust boundary (`isolation_boundary: "consented_local_subprocess"`):
Requires explicit `--approve-run` operator consent, runs in an isolated temporary
worktree copy via an `EXECUTION_POLICY`-validated `argv` list (`shell=False`),
scrubbed credential environment, and bounded wall-clock timeout with process-tree
kill. Explicitly NOT an OS/VM sandbox against hostile untrusted malware.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
from types import FrameType, ModuleType
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from anvil_v4_process import (
    SKIP_SCAN_DIRS,
    TRACE_SCHEMA,
    AnvilRefusalError,
     _is_link_or_junction,
    atomic_locked_read_json,
    atomic_locked_write_json,
    build_process_map,
    resolve_contained_path,
)

ISOLATION_BOUNDARY = "consented_local_subprocess"
NON_VM_TRUST_WARNING = (
    "Consented local child subprocess isolation (isolated temp copy + argv policy "
    "+ scrubbed env); NOT an OS/VM sandbox against hostile untrusted malware."
)

DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_MAX_EVENTS = 50_000
DEFAULT_MAX_SKETCH_BYTES = 524_288
MAX_TIMEOUT_SEC = 300.0
MAX_REPLICATION_TABLE_TIMEOUT_SEC = 1800.0
MAX_REPLICATION_TOTAL_TIMEOUT_SEC = 5400.0
MAX_ALLOWLISTED_DATA_BYTES = 2 * 1024 * 1024 * 1024
ALLOWLISTED_DATA_DIR_NAMES: Tuple[str, ...] = ("data", "Data", "datasets", "Datasets")
REPLICATION_TABLE_RECEIPT_SCHEMA = "anvil-v6-replication-table-receipt/v1"
MAX_TRACE_EVENTS = 50_000
MAX_SKETCH_BYTES = 1_048_576

EXECUTION_POLICY: Dict[str, Any] = {
    "allowed_binaries": ("python", "python3", "pytest", "node", "rscript"),
    "forbidden_shells": (
        "cmd", "powershell", "pwsh", "sh", "bash", "zsh", "wsl", "csh", "ksh", "fish",
    ),
    "forbidden_inline_flags": (
        "-c", "-e", "--eval", "--command", "-command", "-encodedcommand", "-enc", "/c", "/k",
    ),
}

_SAFE_OS_ENV_KEYS: Tuple[str, ...] = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "PATH",
    "SYSTEMDRIVE",
    "LANG",
    "LC_ALL",
)

_SECRET_SUBSTRINGS: Tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "PRIVATE",
    "COOKIE",
    "SESSION",
)

_SECRET_PREFIXES: Tuple[str, ...] = (
    "ANCHOR_",
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "HF_",
    "GITHUB_",
    "GITLAB_",
)


# ---------------------------------------------------------------------------
# 1. Execution Policy & Canonical Argv Containment Gate (CWE-78 / CWE-22)
# ---------------------------------------------------------------------------

def _looks_like_path_token(tok: str, repo_root: Path) -> bool:
    if ".." in tok.replace("\\", "/").split("/"):
        return True
    if tok.startswith(("/", "\\")):
        return True
    if len(tok) >= 2 and tok[1] == ":":
        return True
    if "/" in tok or "\\" in tok:
        return True
    cand = repo_root / tok
    return _is_link_or_junction(cand) or cand.exists()


def validate_execution_argv(repo_root: str | Path, argv: Sequence[str]) -> Dict[str, Any]:
    """Validate `argv` strictly as an explicit list/tuple under `EXECUTION_POLICY`
    and verify every script/path target resolves inside `repo_root`.
    """
    if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)) or len(argv) == 0:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            "Execution requires a non-empty explicit argv list/tuple (command strings are refused).",
            cwe="CWE-78",
        )
    clean_argv: List[str] = []
    for idx, item in enumerate(argv):
        if not isinstance(item, str) or not item.strip() or "\x00" in item:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Invalid or empty argv[{idx}] element refused.",
                cwe="CWE-78",
            )
        clean_argv.append(item)

    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Target repository root must be an existing directory.",
            cwe="CWE-22",
        )

    raw_bin = clean_argv[0].strip()
    bin_path = Path(raw_bin)
    lower_name = bin_path.name.lower()
    suffix = bin_path.suffix.lower()
    base_stem = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", lower_name)

    if base_stem in EXECUTION_POLICY["forbidden_shells"] or suffix in {".bat", ".cmd", ".ps1", ".sh"}:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            f"Shell or wrapper binary '{raw_bin}' refused by EXECUTION_POLICY.",
            cwe="CWE-78",
            details={"argv0": raw_bin},
        )

    is_exact_sys_python = False
    if "/" in raw_bin or "\\" in raw_bin or bin_path.is_absolute():
        try:
            is_exact_sys_python = bin_path.resolve() == Path(sys.executable).resolve()
        except OSError:
            is_exact_sys_python = False
        if not is_exact_sys_python:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Arbitrary path binary '{raw_bin}' refused by EXECUTION_POLICY.",
                cwe="CWE-78",
                details={"argv0": raw_bin},
            )

    if is_exact_sys_python:
        canonical_tool = "python"
    elif base_stem in EXECUTION_POLICY["allowed_binaries"] and suffix in {"", ".exe"}:
        canonical_tool = "python" if base_stem in {"python", "python3"} else base_stem
    else:
        raise AnvilRefusalError(
            "EXECUTION_POLICY_REFUSED",
            f"Binary '{raw_bin}' is not in EXECUTION_POLICY allowed_binaries.",
            cwe="CWE-78",
            details={"argv0": raw_bin},
        )

    tail = clean_argv[1:]
    for idx, tok in enumerate(tail):
        low = tok.lower()
        if (
            low in EXECUTION_POLICY["forbidden_inline_flags"]
            or low.startswith(("-c=", "-e=", "--eval=", "--command=", "-command="))
            or (canonical_tool in {"python", "node", "rscript"} and tok.startswith(("-c", "-e")) and len(tok) > 2)
        ):
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Inline code evaluation flag '{tok}' refused by EXECUTION_POLICY.",
                cwe="CWE-78",
                details={"flag": tok},
            )
        if low in {"-i", "--interactive", "--inspect"}:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Interactive flag '{tok}' refused by EXECUTION_POLICY.",
                cwe="CWE-78",
                details={"flag": tok},
            )

    runner_kind = canonical_tool
    if canonical_tool == "python" and tail and tail[0] == "-m":
        if len(tail) >= 2 and tail[1] == "pytest":
            runner_kind = "pytest"
            tail = tail[2:]
        else:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                "Python '-m' module execution is refused unless invoking '-m pytest'.",
                cwe="CWE-78",
            )
    elif canonical_tool == "python" and any(t == "-m" or t.startswith("-m") for t in tail):
        # Allow '-m' ONLY if it appears after the target script as an app flag? Refuse before script!
        first_non_flag = next((i for i, t in enumerate(tail) if not t.startswith("-")), len(tail))
        if any(t == "-m" or t.startswith("-m") for t in tail[:first_non_flag]):
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                "Python '-m' flag before script is refused by EXECUTION_POLICY.",
                cwe="CWE-78",
            )

    target_rel_script = ""
    script_args: List[str] = []
    pytest_args: List[str] = []
    resolved_binary = sys.executable

    if runner_kind in {"python", "node", "rscript"}:
        if runner_kind in {"node", "rscript"}:
            found = shutil.which(canonical_tool)
            if not found:
                raise AnvilRefusalError(
                    "DEPENDENCY_MISSING",
                    "Required runtime/tracer unavailable — showing static AST map",
                    details={"status_kind": "dependency-missing", "http_status": 503, "runtime": canonical_tool},
                )
            resolved_binary = found

        safe_py_flags = {"-u", "-B", "-O", "-OO", "-s", "-E", "-I"}
        script_idx: Optional[int] = None
        for i, tok in enumerate(tail):
            if tok.startswith("-"):
                if runner_kind == "python" and tok not in safe_py_flags:
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Disallowed interpreter flag '{tok}' before script.",
                        cwe="CWE-78",
                    )
                if runner_kind in {"node", "rscript"}:
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Disallowed runtime flag '{tok}' before script.",
                        cwe="CWE-78",
                    )
            else:
                script_idx = i
                break

        if script_idx is None:
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Missing repository-contained target script for '{canonical_tool}'.",
                cwe="CWE-78",
            )

        raw_script = tail[script_idx]
        contained_script = resolve_contained_path(root, raw_script)
        if not contained_script.is_file():
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Target script '{raw_script}' does not exist inside repository.",
                cwe="CWE-78",
            )
        target_rel_script = contained_script.relative_to(root).as_posix()
        for extra in tail[script_idx + 1 :]:
            if _looks_like_path_token(extra, root):
                resolved_extra = resolve_contained_path(root, extra, allow_root=True)
                script_args.append(resolved_extra.relative_to(root).as_posix() if resolved_extra != root else ".")
            else:
                script_args.append(extra)
    else:
        # pytest runner
        if importlib.util.find_spec("pytest") is None:
            raise AnvilRefusalError(
                "DEPENDENCY_MISSING",
                "Required runtime/tracer unavailable — showing static AST map",
                details={"status_kind": "dependency-missing", "http_status": 503, "runtime": "pytest"},
            )
        skip_next = False
        allowed_pytest_value_flags = {"-k"}
        allowed_pytest_bool_flags = {"-q", "-v", "-vv", "-x", "-s", "--tb=short", "--tb=line", "--tb=no"}
        for i, tok in enumerate(tail):
            if skip_next:
                pytest_args.append(tok)
                skip_next = False
                continue
            if tok in allowed_pytest_value_flags:
                if i + 1 >= len(tail):
                    raise AnvilRefusalError("EXECUTION_POLICY_REFUSED", f"Missing argument after '{tok}'.", cwe="CWE-78")
                pytest_args.append(tok)
                skip_next = True
                continue
            if tok.startswith("--maxfail="):
                pytest_args.append(tok)
                continue
            if tok.startswith("-"):
                if tok not in allowed_pytest_bool_flags:
                    raise AnvilRefusalError(
                        "EXECUTION_POLICY_REFUSED",
                        f"Disallowed pytest flag '{tok}' refused by EXECUTION_POLICY.",
                        cwe="CWE-78",
                    )
                pytest_args.append(tok)
                continue
            file_part, sep, node_part = tok.partition("::")
            resolved_t = resolve_contained_path(root, file_part, allow_root=True)
            rel_t = "." if resolved_t == root else resolved_t.relative_to(root).as_posix()
            pytest_args.append(f"{rel_t}{sep}{node_part}" if sep else rel_t)

    return {
        "runner_kind": runner_kind,
        "resolved_binary": resolved_binary,
        "target_rel_script": target_rel_script,
        "script_args": script_args,
        "pytest_args": pytest_args,
        "validated_argv": list(clean_argv),
    }


# ---------------------------------------------------------------------------
# 2. Isolated Temp Copy, Scrubbed Env & Process-Tree Kill
# ---------------------------------------------------------------------------

def _is_sensitive_untracked_or_secret_file(rel_posix: str, fname: str) -> bool:
    """Return True for dotenv, private key, and credential files that must never be staged."""
    low = fname.lower()
    if low == ".env" or low.startswith(".env."):
        return True
    if low in {
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        ".secrets",
    }:
        return True
    if low.endswith((".pem", ".key", ".pfx", ".p12", ".kdbx")):
        return True
    if low.endswith((".json", ".yaml", ".yml", ".ini", ".cfg", ".toml")) and (
        "credential" in low or "secret" in low
    ):
        return True
    parts_low = [p.lower() for p in rel_posix.split("/") if p]
    if ".aws" in parts_low or ".ssh" in parts_low or ".gnupg" in parts_low:
        return True
    return False


def _copy_allowlisted_data_roots_into_scratch(
    repo_root: Path,
    work_repo: Path,
    allowlisted_data_roots: Sequence[str | Path],
    *,
    cockpit_root: Optional[Path] = None,
    max_data_bytes: int = MAX_ALLOWLISTED_DATA_BYTES,
) -> List[str]:
    """Copy (NEVER hardlink — leaving source file attributes/mtimes/inodes untouched)
    server-manifest allowlisted data subdirectories (`data/`, `Data/`, `datasets/`, `Datasets/`
    under `repo_root` or `cockpit_root`) into `work_repo`, enforcing `<= 2 GB` total cap
    and refusing `..`, absolute paths, non-allowlisted names, and symlinks/junctions.
    """
    eff_cap = min(int(MAX_ALLOWLISTED_DATA_BYTES), int(max_data_bytes))
    if eff_cap <= 0:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_data_bytes ({eff_cap}) must be positive.",
            details={
                "bound_name": "max_allowlisted_data_bytes",
                "bound_limit": eff_cap,
                "observed_value": eff_cap,
                "http_status": 413,
            },
        )
    repo_res = repo_root.resolve()
    ck_res: Optional[Path] = None
    if cockpit_root is not None and str(cockpit_root).strip():
        raw_ck = Path(cockpit_root)
        if _is_link_or_junction(raw_ck) or not raw_ck.exists() or not raw_ck.is_dir():
            raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Invalid or symlinked cockpit_root refused.", cwe="CWE-22", details={"http_status": 403})
        ck_res = raw_ck.resolve()

    allow_set = set(ALLOWLISTED_DATA_DIR_NAMES)
    bases: Dict[str, Path] = {"repo": repo_res}
    if ck_res is not None:
        bases["cockpit"] = ck_res

    target_dirs: List[Tuple[str, str, Path]] = []
    seen_dirs: Set[str] = set()

    if list(allowlisted_data_roots) == ["*"]:
        for btag, bpath in bases.items():
            try:
                entries = sorted(os.scandir(bpath), key=lambda e: e.name)
            except OSError:
                continue
            for ent in entries:
                if ent.name not in allow_set:
                    continue
                ep = Path(ent.path)
                if _is_link_or_junction(ep):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Symlink/junction data directory '{ent.name}' refused.", cwe="CWE-22", details={"http_status": 403})
                if ep.is_dir():
                    rdp = ep.resolve()
                    if not rdp.is_relative_to(bpath):
                        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Data directory '{ent.name}' escapes root.", cwe="CWE-22", details={"http_status": 403})
                    nk = os.path.normcase(str(rdp))
                    if nk not in seen_dirs:
                        seen_dirs.add(nk)
                        target_dirs.append((btag, ent.name, rdp))
    else:
        for raw_item in allowlisted_data_roots:
            raw_s = str(raw_item or "").strip()
            if not raw_s or "\x00" in raw_s:
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty allowlisted data root refused.", cwe="CWE-22", details={"http_status": 403})
            prefix_tag = "repo"
            rel_expr = raw_s
            if ":" in raw_s and raw_s.split(":", 1)[0] in {"repo", "cockpit"}:
                prefix_tag, rel_expr = raw_s.split(":", 1)
            if (
                rel_expr.startswith(("/", "\\"))
                or ":" in rel_expr
                or Path(rel_expr).is_absolute()
                or ".." in rel_expr.replace("\\", "/").split("/")
            ):
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Escaping or absolute data root '{raw_s}' refused.",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            if prefix_tag not in bases:
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Unavailable base '{prefix_tag}' for data root '{raw_s}'.", cwe="CWE-22", details={"http_status": 403})
            chosen_base = bases[prefix_tag]
            rel_parts = [pt for pt in rel_expr.replace("\\", "/").split("/") if pt and pt != "."]
            if not rel_parts or rel_parts[0] not in allow_set:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Data root '{raw_s}' is not in allowlisted directories ({', '.join(ALLOWLISTED_DATA_DIR_NAMES)}).",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            cur = chosen_base
            for pt in rel_parts:
                cur = cur / pt
                if _is_link_or_junction(cur):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Symlink/junction data component '{pt}' refused.", cwe="CWE-22", details={"http_status": 403})
                if not cur.exists() or not cur.is_dir():
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Allowlisted data root '{raw_s}' does not exist as directory.", cwe="CWE-22", details={"http_status": 403})
            rdp = cur.resolve()
            if not rdp.is_relative_to(chosen_base):
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Data root '{raw_s}' escapes base directory.", cwe="CWE-22", details={"http_status": 403})
            nk = os.path.normcase(str(rdp))
            if nk not in seen_dirs:
                seen_dirs.add(nk)
                target_dirs.append((prefix_tag, "/".join(rel_parts), rdp))

    total_bytes = 0
    staged_rels: List[str] = []
    copy_plan: List[Tuple[Path, Path, str]] = []

    for _btag, rel_prefix, dpath in target_dirs:
        for cur_r, dirs, files in os.walk(dpath, followlinks=False):
            cur_p = Path(cur_r)
            dirs.sort()
            kept_d: List[str] = []
            for d in dirs:
                if d.startswith(".") or d == "__pycache__":
                    continue
                sdp = cur_p / d
                if _is_link_or_junction(sdp):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Symlink/junction subdirectory '{d}' in data root refused.", cwe="CWE-22", details={"http_status": 403})
                if not sdp.resolve().is_relative_to(dpath):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Subdirectory '{d}' escapes data root.", cwe="CWE-22", details={"http_status": 403})
                kept_d.append(d)
            dirs[:] = kept_d

            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                fp = cur_p / fname
                if _is_link_or_junction(fp):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Symlink/junction data file '{fname}' refused.", cwe="CWE-22", details={"http_status": 403})
                rfp = fp.resolve()
                if not rfp.is_relative_to(dpath):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Data file '{fname}' escapes data root.", cwe="CWE-22", details={"http_status": 403})
                rel_in_root = rfp.relative_to(dpath).as_posix()
                dest_rel = f"{rel_prefix}/{rel_in_root}"
                if _is_sensitive_untracked_or_secret_file(dest_rel, fname):
                    continue
                st = os.stat(rfp, follow_symlinks=False)
                prospective = total_bytes + int(st.st_size)
                if prospective > eff_cap:
                    raise AnvilRefusalError(
                        "BOUND_EXCEEDED_REFUSAL",
                        f"Allowlisted data roots total size ({prospective} bytes) exceeds cap ({eff_cap} bytes).",
                        details={
                            "bound_name": "max_allowlisted_data_bytes",
                            "bound_limit": eff_cap,
                            "observed_value": prospective,
                            "http_status": 413,
                        },
                    )
                total_bytes = prospective
                dst_p = work_repo / Path(*dest_rel.split("/"))
                copy_plan.append((rfp, dst_p, dest_rel))

    for src_fp, dst_fp, dest_rel in copy_plan:
        dst_fp.parent.mkdir(parents=True, exist_ok=True)
        # Pure byte copy via open('rb') -> open('wb'): NEVER hardlinks and NEVER touches source file attributes/atime/mode
        with open(src_fp, "rb") as f_in, open(dst_fp, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
        staged_rels.append(dest_rel)

    return staged_rels


def _stage_isolated_worktree_copy(
    repo_root: Path,
    scratch_base: Path,
    *,
    allowlisted_data_roots: Optional[Sequence[str | Path]] = None,
    cockpit_root: Optional[Path] = None,
    max_data_bytes: int = MAX_ALLOWLISTED_DATA_BYTES,
) -> Path:
    """Copy tracked and non-gitignored repository files (in Git repos via
    `git ls-files -z --cached --others --exclude-standard`) or contained
    non-sensitive source files (in non-Git directories) into an isolated scratch worktree,
    plus optional manifest-allowlisted data roots by pure byte copy (`<= 2 GB` cap),
    skipping metadata/cache/secret files and refusing escaping symlinks or junctions.
    """
    work_repo = scratch_base / "worktree"
    work_repo.mkdir(parents=True, exist_ok=True)

    if (repo_root / ".git").exists():
        res = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            shell=False,
            capture_output=True,
            timeout=10.0,
            check=False,
        )
        if res.returncode != 0:
            raise AnvilRefusalError(
                "DEPENDENCY_MISSING",
                "Failed to enumerate git-tracked files for isolated worktree staging.",
                details={
                    "status_kind": "dependency-missing",
                    "http_status": 503,
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            )
        for raw_entry in res.stdout.split(b"\x00"):
            if not raw_entry:
                continue
            rel_posix = raw_entry.decode("utf-8", errors="replace").replace("\\", "/").lstrip("/")
            if not rel_posix:
                continue
            rel_parts = [p for p in rel_posix.split("/") if p]
            if any(part in SKIP_SCAN_DIRS for part in rel_parts):
                continue
            fname = rel_parts[-1]
            if _is_sensitive_untracked_or_secret_file(rel_posix, fname):
                continue
            resolve_contained_path(repo_root, rel_posix, must_be_relative=True)
            fp = repo_root / Path(*rel_parts)
            if _is_link_or_junction(fp):
                if not fp.resolve().is_relative_to(repo_root):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Tracked symlink '{rel_posix}' escapes repository root.",
                        cwe="CWE-22",
                    )
                continue
            if fp.is_file():
                dst = work_repo / Path(*rel_parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, dst)
        if allowlisted_data_roots is not None:
            _copy_allowlisted_data_roots_into_scratch(
                repo_root,
                work_repo,
                allowlisted_data_roots,
                cockpit_root=cockpit_root,
                max_data_bytes=max_data_bytes,
            )
        return work_repo

    allow_data_set = set(ALLOWLISTED_DATA_DIR_NAMES)
    for cur_root, dirs, files in os.walk(repo_root, followlinks=False):
        cur_path = Path(cur_root)
        rel_dir = cur_path.relative_to(repo_root)
        kept_dirs: List[str] = []
        for d in sorted(dirs):
            if d in SKIP_SCAN_DIRS:
                continue
            if allowlisted_data_roots is not None and rel_dir == Path(".") and d in allow_data_set:
                # Handled with strict <=2 GB cap + symlink refusal in _copy_allowlisted_data_roots_into_scratch
                continue
            dp = cur_path / d
            if _is_link_or_junction(dp):
                if not dp.resolve().is_relative_to(repo_root):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Directory symlink/junction '{d}' escapes repository root.",
                        cwe="CWE-22",
                    )
                continue
            kept_dirs.append(d)
            (work_repo / rel_dir / d).mkdir(parents=True, exist_ok=True)
        dirs[:] = kept_dirs

        for fname in sorted(files):
            rel_file_posix = (rel_dir / fname).as_posix()
            if _is_sensitive_untracked_or_secret_file(rel_file_posix, fname):
                continue
            fp = cur_path / fname
            if _is_link_or_junction(fp):
                if not fp.resolve().is_relative_to(repo_root):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"File symlink '{fname}' escapes repository root.",
                        cwe="CWE-22",
                    )
                continue
            if fp.is_file():
                dst = work_repo / rel_dir / fname
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, dst)

    if allowlisted_data_roots is not None:
        _copy_allowlisted_data_roots_into_scratch(
            repo_root,
            work_repo,
            allowlisted_data_roots,
            cockpit_root=cockpit_root,
            max_data_bytes=max_data_bytes,
        )
    return work_repo


def build_scrubbed_env(isolated_home_tmp: Path) -> Dict[str, str]:
    """Construct a minimal runtime environment stripped of `ANCHOR_TOKEN` and all
    cloud/API/secret credentials, redirecting HOME/USERPROFILE/TMP/TEMP to scratch.
    """
    isolated_home_tmp.mkdir(parents=True, exist_ok=True)
    scrubbed: Dict[str, str] = {}
    for key, val in os.environ.items():
        ukey = key.upper()
        if any(ukey.startswith(pref) for pref in _SECRET_PREFIXES):
            continue
        if any(sub in ukey for sub in _SECRET_SUBSTRINGS):
            continue
        if ukey in _SAFE_OS_ENV_KEYS:
            scrubbed[key] = val

    iso_str = str(isolated_home_tmp)
    scrubbed["HOME"] = iso_str
    scrubbed["USERPROFILE"] = iso_str
    scrubbed["TMP"] = iso_str
    scrubbed["TEMP"] = iso_str
    scrubbed["TMPDIR"] = iso_str
    scrubbed["PYTHONDONTWRITEBYTECODE"] = "1"
    scrubbed["PYTHONIOENCODING"] = "utf-8"
    scrubbed["PYTHONNOUSERSITE"] = "1"
    scrubbed["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return scrubbed


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Terminate `proc` and its entire descendant process tree cleanly (`shell=False`)."""
    pid = proc.pid
    if pid is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            import signal

            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 3. Observer-Safe O(1) Value Sketcher (Zero __repr__ / __str__ / @property)
# ---------------------------------------------------------------------------

def _is_non_data_value(val: Any) -> bool:
    t = type(val)
    if isinstance(val, ModuleType) or isinstance(val, type):
        return True
    if inspect.isfunction(val) or inspect.ismethod(val) or inspect.isbuiltin(val) or inspect.iscode(val):
        return True
    tname = getattr(t, "__name__", "")
    return tname in {"function", "builtin_function_or_method", "method", "module", "frame", "generator", "coroutine"}


def _unravel_index_o1(flat_idx: int, shape: Sequence[int]) -> Tuple[int, ...]:
    """Convert a 1D flat offset into N-D coordinates in O(ndim) without copying."""
    coords = [0] * len(shape)
    rem = flat_idx
    for dim_i in range(len(shape) - 1, -1, -1):
        dim_sz = shape[dim_i]
        coords[dim_i] = rem % dim_sz
        rem //= dim_sz
    return tuple(coords)


def _boundary_flat_indices(size: int) -> List[int]:
    """Return at most 8 boundary indices (flat[:4] and flat[-4:]) in strictly O(1)."""
    if size <= 0:
        return []
    if size <= 8:
        return list(range(size))
    return [0, 1, 2, 3, size - 4, size - 3, size - 2, size - 1]


def _scalar_or_shallow_preview(val: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Inspect a nested collection element 1 level deep without calling dunder hooks."""
    t = type(val)
    if val is None:
        return {"kind": "none", "value": None}, []
    if t is bool:
        return {"kind": "bool", "value": bool(val)}, []
    if t is int:
        if val.bit_length() <= 128:
            return {"kind": "int", "value": int(val)}, []
        return {"kind": "int_large", "bit_length": val.bit_length()}, []
    if t is float:
        if math.isnan(val):
            return {"kind": "float", "non_finite": "NaN"}, ["NaN"]
        if math.isinf(val):
            nf = "+Infinity" if val > 0 else "-Infinity"
            return {"kind": "float", "non_finite": nf}, [nf]
        return {"kind": "float", "value": round(float(val), 8)}, []
    if t is complex:
        c_nfs: List[str] = []
        for part in (val.real, val.imag):
            if math.isnan(part) and "NaN" not in c_nfs:
                c_nfs.append("NaN")
            elif math.isinf(part):
                tag = "+Infinity" if part > 0 else "-Infinity"
                if tag not in c_nfs:
                    c_nfs.append(tag)
        if c_nfs:
            return {"kind": "complex", "non_finite": c_nfs}, c_nfs
        return {"kind": "complex", "real": round(float(val.real), 8), "imag": round(float(val.imag), 8)}, []
    if t is str:
        return {"kind": "str", "length": len(val), "preview": val[:64]}, []
    if t in (bytes, bytearray):
        return {"kind": "bytes", "length": len(val)}, []
    return {"kind": "ref", "type": getattr(t, "__qualname__", getattr(t, "__name__", "object"))}, []


def sketch_value_safe(val: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Produce a strictly O(1) time-and-space structural descriptor of `val` plus an
    at-most-8-element boundary preview (`flat[:4]` / `flat[-4:]` or first <=8 entries)
    WITHOUT full-array scans and WITHOUT invoking custom `__repr__`, `__str__`,
    `@property`, or arbitrary iterators.
    """
    t = type(val)
    if val is None or t in (bool, int, float, complex):
        return _scalar_or_shallow_preview(val)

    if t is str:
        return {"kind": "str", "length": len(val), "preview": val[:4096]}, []

    if t in (bytes, bytearray):
        raw_b = bytes(val[:2048])
        return {"kind": "bytes", "length": len(val), "hex_prefix": raw_b[:64].hex(), "sample_len": len(raw_b)}, []

    nonfinites: List[str] = []

    if t in (list, tuple):
        seq = list.__getitem__(val, slice(0, 8)) if t is list else tuple.__getitem__(val, slice(0, 8))
        n = list.__len__(val) if t is list else tuple.__len__(val)
        sample_out: List[Dict[str, Any]] = []
        for idx, item in enumerate(seq):
            sk, nfs = _scalar_or_shallow_preview(item)
            if idx < 4:
                sample_out.append(sk)
            for nf in nfs:
                if nf not in nonfinites:
                    nonfinites.append(nf)
        return {"kind": t.__name__, "length": n, "sample": sample_out}, nonfinites

    if t in (set, frozenset):
        n = set.__len__(val) if t is set else frozenset.__len__(val)
        it = set.__iter__(val) if t is set else frozenset.__iter__(val)
        sample_out = []
        for idx in range(min(n, 8)):
            try:
                item = next(it)
            except StopIteration:
                break
            sk, nfs = _scalar_or_shallow_preview(item)
            if idx < 4:
                sample_out.append(sk)
            for nf in nfs:
                if nf not in nonfinites:
                    nonfinites.append(nf)
        return {"kind": t.__name__, "length": n, "sample": sample_out}, nonfinites

    if t is dict:
        n = dict.__len__(val)
        sample_pairs: List[Dict[str, Any]] = []
        for idx, (k, v) in enumerate(dict.items(val)):
            if idx >= 8:
                break
            k_label = k[:48] if type(k) is str else (k if type(k) in (int, bool) else type(k).__name__)
            v_sk, nfs = _scalar_or_shallow_preview(v)
            if idx < 4:
                sample_pairs.append({"key": k_label, "val": v_sk})
            for nf in nfs:
                if nf not in nonfinites:
                    nonfinites.append(nf)
        return {"kind": "dict", "length": n, "sample": sample_pairs}, nonfinites

    mod_name = getattr(t, "__module__", "") or ""
    type_name = getattr(t, "__name__", "") or ""

    if mod_name.startswith("numpy") and type_name == "ndarray":
        try:
            shape = [int(x) for x in val.shape]
            dtype_str = str(val.dtype)
            size = int(val.size)
            dkind = val.dtype.kind
            boundary_sample: List[Dict[str, Any]] = []
            for flat_idx in _boundary_flat_indices(size):
                elem = val.item() if len(shape) == 0 else val[_unravel_index_o1(flat_idx, shape)]
                py_elem = elem if dkind == "O" else elem.item()
                sk, nfs = _scalar_or_shallow_preview(py_elem)
                boundary_sample.append(sk)
                for nf in nfs:
                    if nf not in nonfinites:
                        nonfinites.append(nf)
            return {
                "kind": "ndarray",
                "shape": shape,
                "dtype": dtype_str,
                "size": size,
                "sample": boundary_sample,
            }, nonfinites
        except Exception:
            return {"kind": "ndarray", "type": "numpy.ndarray"}, nonfinites

    if mod_name.startswith("torch") and type_name == "Tensor":
        try:
            shape = [int(x) for x in val.shape]
            dtype_str = str(val.dtype)
            numel = int(val.numel())
            boundary_sample = []
            for flat_idx in _boundary_flat_indices(numel):
                py_elem = val.item() if len(shape) == 0 else val[_unravel_index_o1(flat_idx, shape)].item()
                sk, nfs = _scalar_or_shallow_preview(py_elem)
                boundary_sample.append(sk)
                for nf in nfs:
                    if nf not in nonfinites:
                        nonfinites.append(nf)
            return {
                "kind": "tensor",
                "shape": shape,
                "dtype": dtype_str,
                "size": numel,
                "sample": boundary_sample,
            }, nonfinites
        except Exception:
            return {"kind": "tensor", "type": "torch.Tensor"}, nonfinites

    # Arbitrary user class instance: inspect ONLY raw instance __dict__ via object.__getattribute__ (<= 8 entries)
    fields: List[str] = []
    try:
        inst_dict = object.__getattribute__(val, "__dict__")
        if type(inst_dict) is dict:
            for idx, (fk, fv) in enumerate(dict.items(inst_dict)):
                if idx >= 8:
                    break
                if type(fk) is str and len(fields) < 8:
                    fields.append(fk)
                _, nfs = _scalar_or_shallow_preview(fv)
                for nf in nfs:
                    if nf not in nonfinites:
                        nonfinites.append(nf)
    except Exception:
        pass

    return {
        "kind": "object",
        "type": getattr(t, "__qualname__", type_name or "object"),
        "fields": fields,
    }, nonfinites


def _scan_single_tensor_buffer_once(
    buf: Any,
    seen_tensor_states: Dict[Tuple[Any, ...], List[str]],
    *,
    force_rescan: bool = False,
) -> List[str]:
    """Run vectorized C-SIMD NaN/+/-Infinity detection once per newly produced or
    mutated floating-point NumPy/Torch buffer of ANY size (zero 100,000-element
    blind spot), skipping unchanged in-scope buffers in O(1).
    """
    t = type(buf)
    mod_name = getattr(t, "__module__", "") or ""
    type_name = getattr(t, "__name__", "") or ""

    if mod_name.startswith("numpy") and type_name == "ndarray":
        np_mod = sys.modules.get("numpy")
        if np_mod is None:
            return []
        try:
            size = int(buf.size)
            dkind = buf.dtype.kind
            if size <= 0 or dkind not in ("f", "c"):
                return []
            shape = tuple(int(x) for x in buf.shape)
            dtype_str = str(buf.dtype)
            data_ptr = int(buf.__array_interface__["data"][0])
            b_preview: List[Any] = []
            for flat_idx in _boundary_flat_indices(size):
                elem = buf.item() if len(shape) == 0 else buf[_unravel_index_o1(flat_idx, shape)].item()
                if type(elem) is float and math.isnan(elem):
                    b_preview.append("NaN")
                elif type(elem) is complex and (math.isnan(elem.real) or math.isnan(elem.imag)):
                    b_preview.append("cNaN")
                else:
                    b_preview.append(elem)
            state_key = ("ndarray", id(buf), data_ptr, shape, dtype_str, tuple(b_preview))
            if not force_rescan and state_key in seen_tensor_states:
                return list(seen_tensor_states[state_key])
            found: List[str] = []
            if bool(np_mod.isnan(buf).any()):
                found.append("NaN")
            if dkind == "c":
                if bool(np_mod.isposinf(buf.real).any()) or bool(np_mod.isposinf(buf.imag).any()):
                    found.append("+Infinity")
                if bool(np_mod.isneginf(buf.real).any()) or bool(np_mod.isneginf(buf.imag).any()):
                    found.append("-Infinity")
            else:
                if bool(np_mod.isposinf(buf).any()):
                    found.append("+Infinity")
                if bool(np_mod.isneginf(buf).any()):
                    found.append("-Infinity")
            seen_tensor_states[state_key] = found
            return list(found)
        except Exception:
            return []

    if mod_name.startswith("torch") and type_name == "Tensor":
        torch_mod = sys.modules.get("torch")
        if torch_mod is None:
            return []
        try:
            numel = int(buf.numel())
            is_fp = bool(buf.is_floating_point())
            is_cplx = bool(buf.is_complex()) if hasattr(buf, "is_complex") else False
            if numel <= 0 or not (is_fp or is_cplx):
                return []
            shape = tuple(int(x) for x in buf.shape)
            dtype_str = str(buf.dtype)
            data_ptr = int(buf.data_ptr())
            version = int(getattr(buf, "_version", 0))
            state_key = ("tensor", id(buf), data_ptr, shape, dtype_str, version)
            if not force_rescan and state_key in seen_tensor_states:
                return list(seen_tensor_states[state_key])
            found = []
            if bool(torch_mod.isnan(buf).any().item()):
                found.append("NaN")
            if is_cplx:
                if bool(torch_mod.isposinf(buf.real).any().item()) or bool(torch_mod.isposinf(buf.imag).any().item()):
                    found.append("+Infinity")
                if bool(torch_mod.isneginf(buf.real).any().item()) or bool(torch_mod.isneginf(buf.imag).any().item()):
                    found.append("-Infinity")
            else:
                if bool(torch_mod.isposinf(buf).any().item()):
                    found.append("+Infinity")
                if bool(torch_mod.isneginf(buf).any().item()):
                    found.append("-Infinity")
            seen_tensor_states[state_key] = found
            return list(found)
        except Exception:
            return []

    return []


def _scan_tensor_tripwires_once(
    val: Any,
    seen_tensor_states: Dict[Tuple[Any, ...], List[str]],
    *,
    force_rescan: bool = False,
) -> List[str]:
    """Amortized once-per-new/mutated-buffer C-SIMD non-finite tripwire pass with
    zero 100,000-element blind spot, decoupled from `sketch_value_safe` so value
    sketching remains strictly O(1).
    """
    direct = _scan_single_tensor_buffer_once(val, seen_tensor_states, force_rescan=force_rescan)
    if direct:
        return direct

    t = type(val)
    agg: List[str] = []
    if t in (list, tuple):
        seq = list.__getitem__(val, slice(0, 8)) if t is list else tuple.__getitem__(val, slice(0, 8))
        for item in seq:
            for nf in _scan_single_tensor_buffer_once(item, seen_tensor_states, force_rescan=force_rescan):
                if nf not in agg:
                    agg.append(nf)
    elif t is dict:
        for idx, (_, dv) in enumerate(dict.items(val)):
            if idx >= 8:
                break
            for nf in _scan_single_tensor_buffer_once(dv, seen_tensor_states, force_rescan=force_rescan):
                if nf not in agg:
                    agg.append(nf)
    return agg


# ---------------------------------------------------------------------------
# 4. Child Subprocess Python Tracer Worker (Zero eval / exec / pickle)
# ---------------------------------------------------------------------------

class _TraceBoundAbort(BaseException):
    """Internal control-flow abort raised when trace numeric bounds are exceeded."""

    def __init__(self, bound_name: str, bound_limit: int, observed_value: int) -> None:
        super().__init__(f"{bound_name} exceeded ({observed_value} > {bound_limit})")
        self.bound_name = bound_name
        self.bound_limit = bound_limit
        self.observed_value = observed_value


def _run_python_tracer_worker(manifest_path: Path) -> int:
    manifest = atomic_locked_read_json(manifest_path)
    work_repo = Path(manifest["work_repo"]).resolve()
    runner_kind = str(manifest["runner_kind"])
    target_rel_script = str(manifest.get("target_rel_script") or "")
    script_args = list(manifest.get("script_args") or [])
    pytest_args = list(manifest.get("pytest_args") or [])
    max_events = int(manifest.get("max_events") or DEFAULT_MAX_EVENTS)
    max_sketch_bytes = int(manifest.get("max_sketch_bytes") or DEFAULT_MAX_SKETCH_BYTES)
    pinned_watches = set(str(x) for x in (manifest.get("pinned_watches") or []) if str(x))
    out_file = Path(manifest["worker_output"]).resolve()
    unit_index: List[Dict[str, Any]] = list(manifest.get("unit_index") or [])
    stage_ids: List[str] = list(manifest.get("stage_ids") or [])

    # Lookup tables from static process map
    def _lookup_unit(rel_f: str, line_no: int) -> Optional[Dict[str, Any]]:
        for u in unit_index:
            if u["file"] == rel_f and u["start_line"] <= line_no <= u["end_line"]:
                return u
        return None

    line_hits: Dict[Tuple[str, int], int] = {}
    call_edges: Dict[Tuple[str, str, str, str], int] = {}
    drift_edges: Dict[Tuple[str, str, str, str, str, str, int], int] = {}
    tripwires: List[Dict[str, Any]] = []
    seen_tripwires: Set[Tuple[str, int, str, str]] = set()
    uncaught_stage_exceptions: Set[str] = set()
    stage_wall_ns: Dict[str, int] = {sid: 0 for sid in stage_ids}

    # 5-Scope state tracking
    all_scopes = (
        "function_locals",
        "closure_nonlocals",
        "instance_attrs",
        "module_globals",
        "stage_io_contracts",
    )
    scope_records: Dict[str, Dict[str, Dict[str, Any]]] = {sc: {} for sc in all_scopes}
    all_state_keys: Set[str] = set()
    stage_state_keys: Dict[str, Set[str]] = {sid: set() for sid in stage_ids}
    stage_mutated_keys: Dict[str, Set[str]] = {sid: set() for sid in stage_ids}
    stage_anomaly_keys: Dict[str, Set[str]] = {sid: set() for sid in stage_ids}
    var_first_digest: Dict[str, str] = {}

    state_counters = {"events": 0, "sketch_bytes": 0}
    active_stage_clock: List[Any] = [None, time.perf_counter_ns()]

    def _switch_stage_clock(new_sid: Optional[str]) -> None:
        now_ns = time.perf_counter_ns()
        prev_sid = active_stage_clock[0]
        if prev_sid and prev_sid in stage_wall_ns:
            stage_wall_ns[prev_sid] += max(0, now_ns - int(active_stage_clock[1]))
        active_stage_clock[0] = new_sid
        active_stage_clock[1] = now_ns

    co_rel_cache: Dict[str, Optional[str]] = {}

    def _rel_repo_file(frame: FrameType) -> Optional[str]:
        raw_co = frame.f_code.co_filename
        if not raw_co or raw_co.startswith("<"):
            return None
        if raw_co in co_rel_cache:
            return co_rel_cache[raw_co]
        res_rel: Optional[str] = None
        try:
            rp = Path(raw_co).resolve()
            if rp.is_relative_to(work_repo):
                res_rel = rp.relative_to(work_repo).as_posix()
        except OSError:
            res_rel = None
        co_rel_cache[raw_co] = res_rel
        return res_rel

    seen_tensor_states: Dict[Tuple[Any, ...], List[str]] = {}
    active_var_nfs: Dict[str, Set[str]] = {}
    frame_emitted_nfs: Dict[int, Set[str]] = {}
    last_frame_line: Dict[int, Tuple[str, int]] = {}
    file_lines_cache: Dict[str, List[str]] = {}

    def _get_source_line(rel_f: str, ln: int) -> str:
        lines = file_lines_cache.get(rel_f)
        if lines is None:
            try:
                lines = (work_repo / rel_f).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            file_lines_cache[rel_f] = lines
        return lines[ln - 1] if 1 <= ln <= len(lines) else ""

    def _record_variable(
        scope: str,
        sid: str,
        rel_f: str,
        line_no: int,
        symbol: str,
        var_name: str,
        val: Any,
        *,
        mark_contract_write: bool = False,
        force_tensor_rescan: bool = False,
    ) -> None:
        if _is_non_data_value(val):
            return
        sketch, nfs = sketch_value_safe(val)
        tensor_nfs = _scan_tensor_tripwires_once(val, seen_tensor_states, force_rescan=force_tensor_rescan)
        if tensor_nfs:
            nfs = list(nfs)
            for tnf in tensor_nfs:
                if tnf not in nfs:
                    nfs.append(tnf)
        encoded_sk = json.dumps(sketch, sort_keys=True, ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha1(encoded_sk.encode("utf-8")).hexdigest()[:16]
        vkey = f"{scope}:{rel_f}:{symbol}:{var_name}"

        prev_entry = scope_records[scope].get(vkey)
        prev_bytes = int(prev_entry["_bytes"]) if prev_entry else 0
        new_bytes = len(encoded_sk) + len(vkey) + 32
        state_counters["sketch_bytes"] += max(0, new_bytes - prev_bytes)
        if state_counters["sketch_bytes"] > max_sketch_bytes:
            sys.settrace(None)
            raise _TraceBoundAbort("max_sketch_bytes", max_sketch_bytes, state_counters["sketch_bytes"])

        scope_records[scope][vkey] = {
            "key": vkey,
            "scope": scope,
            "stage_id": sid,
            "file": rel_f,
            "line": line_no,
            "symbol": symbol,
            "name": var_name,
            "sketch": sketch,
            "_bytes": max(prev_bytes, new_bytes),
        }

        all_state_keys.add(vkey)
        if sid in stage_state_keys:
            stage_state_keys[sid].add(vkey)

        if vkey not in var_first_digest:
            var_first_digest[vkey] = digest
            if mark_contract_write and sid in stage_mutated_keys:
                stage_mutated_keys[sid].add(vkey)
        elif var_first_digest[vkey] != digest:
            var_first_digest[vkey] = digest
            if sid in stage_mutated_keys:
                stage_mutated_keys[sid].add(vkey)

        is_pinned = (var_name in pinned_watches) or (f"{symbol}.{var_name}" in pinned_watches) or (vkey in pinned_watches)
        prev_nfs = active_var_nfs.get(vkey, set())
        cur_nfs_set = set(nfs)
        active_var_nfs[vkey] = cur_nfs_set
        if nfs:
            for nf in nfs:
                if nf in prev_nfs:
                    continue
                tw_sig = (rel_f, line_no, var_name, nf)
                if tw_sig not in seen_tripwires:
                    seen_tripwires.add(tw_sig)
                    tripwires.append({
                        "stage_id": sid,
                        "file": rel_f,
                        "line": line_no,
                        "symbol": symbol,
                        "variable": var_name,
                        "scope": scope,
                        "kind": nf,
                    })
            if sid in stage_anomaly_keys:
                stage_anomaly_keys[sid].add(vkey)
                stage_mutated_keys[sid].add(vkey)
        elif is_pinned and sid in stage_anomaly_keys:
            stage_anomaly_keys[sid].add(vkey)
            stage_mutated_keys[sid].add(vkey)

    def _capture_frame_scopes(frame: FrameType, event: str, arg: Any, rel_f: str, unit: Optional[Dict[str, Any]]) -> None:
        sid = unit["stage_id"] if unit else (stage_ids[0] if stage_ids else "S1")
        symbol = unit["symbol"] if unit else frame.f_code.co_name
        line_no = int(frame.f_lineno)
        code_obj = frame.f_code
        free_and_cell = set(code_obj.co_freevars) | set(code_obj.co_cellvars)
        arg_names = set(code_obj.co_varnames[: code_obj.co_argcount])

        fid = id(frame)
        prev_info = last_frame_line.get(fid)
        prev_src = _get_source_line(prev_info[0], prev_info[1]) if prev_info else ""
        if event == "return":
            last_frame_line.pop(fid, None)
        else:
            last_frame_line[fid] = (rel_f, line_no)

        exec_line = (
            int(prev_info[1])
            if (event in ("line", "return") and prev_info is not None and prev_info[0] == rel_f)
            else line_no
        )
        exec_unit = _lookup_unit(rel_f, exec_line) if exec_line != line_no else unit
        exec_sid = exec_unit["stage_id"] if exec_unit else sid
        exec_sym = exec_unit["symbol"] if exec_unit else symbol

        f_locals = frame.f_locals
        if event == "call":
            frame_emitted_nfs[fid] = set()
            for aname in arg_names:
                if aname != "self" and aname in f_locals:
                    _record_variable(
                        "stage_io_contracts", sid, rel_f, line_no, symbol, aname, f_locals[aname], mark_contract_write=True
                    )

        tw_before = len(tripwires)
        for lname, lval in list(f_locals.items()):
            if not isinstance(lname, str) or lname.startswith("__"):
                continue
            if lname == "self":
                try:
                    inst_d = object.__getattribute__(lval, "__dict__")
                    if type(inst_d) is dict:
                        for ak, av in list(dict.items(inst_d))[:8]:
                            if type(ak) is str and not ak.startswith("__"):
                                force_attr = (event == "return") or bool(prev_src and ak in prev_src)
                                _record_variable(
                                    "instance_attrs",
                                    exec_sid,
                                    rel_f,
                                    exec_line,
                                    exec_sym,
                                    f"self.{ak}",
                                    av,
                                    mark_contract_write=True,
                                    force_tensor_rescan=force_attr,
                                )
                except Exception:
                    pass
                continue
            target_scope = "closure_nonlocals" if lname in free_and_cell else "function_locals"
            force_loc = (event == "return") or bool(prev_src and lname in prev_src)
            _record_variable(
                target_scope,
                exec_sid,
                rel_f,
                exec_line,
                exec_sym,
                lname,
                lval,
                mark_contract_write=(event == "line"),
                force_tensor_rescan=force_loc,
            )
        if len(tripwires) > tw_before:
            emitted_set = frame_emitted_nfs.setdefault(fid, set())
            for tw_item in tripwires[tw_before:]:
                emitted_set.add(str(tw_item["kind"]))

        if event in ("call", "return"):
            for gname, gval in list(frame.f_globals.items()):
                if not isinstance(gname, str) or gname.startswith("_"):
                    continue
                _record_variable(
                    "module_globals",
                    exec_sid if event == "return" else sid,
                    rel_f,
                    exec_line if event == "return" else line_no,
                    "<module>",
                    gname,
                    gval,
                    mark_contract_write=False,
                    force_tensor_rescan=(event == "return"),
                )

        if event == "return":
            emitted_in_frame = frame_emitted_nfs.pop(fid, set())
            if symbol != "<module>":
                ret_vkey = f"stage_io_contracts:{rel_f}:{symbol}:{symbol}.__return__"
                if emitted_in_frame:
                    active_var_nfs[ret_vkey] = set(emitted_in_frame)
                _record_variable(
                    "stage_io_contracts",
                    sid,
                    rel_f,
                    line_no,
                    symbol,
                    f"{symbol}.__return__",
                    arg,
                    mark_contract_write=True,
                    force_tensor_rescan=True,
                )

    def _tracer(frame: FrameType, event: str, arg: Any) -> Any:
        rel_f = _rel_repo_file(frame)
        if rel_f is None:
            return None

        line_no = int(frame.f_lineno)
        if event == "line" and max_events >= DEFAULT_MAX_EVENTS:
            prev_h = line_hits.get((rel_f, line_no), 0)
            if prev_h >= 64 and ((prev_h + 1) & 127) != 0:
                line_hits[(rel_f, line_no)] = prev_h + 1
                return _tracer

        state_counters["events"] += 1
        if state_counters["events"] > max_events:
            sys.settrace(None)
            raise _TraceBoundAbort("max_events", max_events, state_counters["events"])

        unit = _lookup_unit(rel_f, line_no)
        sid = unit["stage_id"] if unit else (stage_ids[0] if stage_ids else "S1")
        _switch_stage_clock(sid)

        is_mod_def_header = (
            frame.f_code.co_name == "<module>"
            and unit is not None
            and not str(unit.get("symbol", "")).startswith("script_")
        )

        if event == "line":
            if not is_mod_def_header:
                key = (rel_f, line_no)
                line_hits[key] = line_hits.get(key, 0) + 1
            _capture_frame_scopes(frame, event, arg, rel_f, unit)
        elif event == "call":
            if not is_mod_def_header:
                line_hits[(rel_f, line_no)] = line_hits.get((rel_f, line_no), 0) + 1
            caller = frame.f_back
            if caller is not None:
                c_rel = _rel_repo_file(caller)
                if c_rel is not None:
                    c_line = int(caller.f_lineno)
                    c_unit = _lookup_unit(c_rel, c_line)
                    c_short = c_unit["short_name"] if c_unit else caller.f_code.co_name
                    d_short = unit["short_name"] if unit else frame.f_code.co_name
                    if d_short != "<module>":
                        ce_key = (c_rel, c_short, rel_f, d_short)
                        call_edges[ce_key] = call_edges.get(ce_key, 0) + 1
                        static_callees = set(c_unit.get("static_calls") or []) if c_unit else set()
                        if c_unit and d_short not in static_callees and d_short != c_short:
                            f_stg = c_unit["stage_id"]
                            t_stg = unit["stage_id"] if unit else f_stg
                            dr_key = (f_stg, t_stg, c_rel, c_short, rel_f, d_short, c_line)
                            drift_edges[dr_key] = drift_edges.get(dr_key, 0) + 1
            _capture_frame_scopes(frame, event, arg, rel_f, unit)
        elif event == "return":
            _capture_frame_scopes(frame, event, arg, rel_f, unit)
        elif event == "exception":
            exc_type = arg[0] if isinstance(arg, tuple) and arg else None
            if exc_type is not None and issubclass(exc_type, Exception):
                # Track stage if exception escapes top frame later
                frame_tag = sid
                _ = frame_tag
        return _tracer

    for sub_pkg in ("src", "Code", "code", "lib"):
        cand_pkg = work_repo / sub_pkg
        if cand_pkg.is_dir() and str(cand_pkg) not in sys.path:
            sys.path.insert(0, str(cand_pkg))
    sys.path.insert(0, str(work_repo))
    for sp_dir in manifest.get("host_site_packages") or []:
        if isinstance(sp_dir, str) and sp_dir and sp_dir not in sys.path:
            sys.path.append(sp_dir)
    prio_sps = [sp for sp in (manifest.get("priority_site_packages") or []) if isinstance(sp, str) and sp]
    with contextlib.suppress(Exception):
        import site as _w_site
        for sp_dir in prio_sps:
            _w_site.addsitedir(sp_dir)
    for sp_dir in prio_sps:
        if sp_dir not in sys.path:
            sys.path.append(sp_dir)
    os.chdir(str(work_repo))
    target_exception: Optional[Dict[str, Any]] = None
    bound_abort: Optional[_TraceBoundAbort] = None

    t_start = time.perf_counter()
    sys.settrace(_tracer)
    try:
        if runner_kind == "python":
            script_abs = (work_repo / target_rel_script).resolve()
            sys.argv = [target_rel_script, *script_args]
            runpy.run_path(str(script_abs), run_name="__main__")
        else:
            import pytest as _pytest_mod

            exit_rc = int(_pytest_mod.main(pytest_args))
            if exit_rc not in (0, 5):
                target_exception = {"type": "PytestExit", "exit_code": exit_rc, "stage_id": active_stage_clock[0] or "S1"}
    except _TraceBoundAbort as b_err:
        bound_abort = b_err
    except SystemExit as sys_ex:
        code_val = sys_ex.code if isinstance(sys_ex.code, int) else (0 if sys_ex.code is None else 1)
        if code_val != 0:
            estg = active_stage_clock[0] or (stage_ids[0] if stage_ids else "S1")
            uncaught_stage_exceptions.add(estg)
            target_exception = {"type": "SystemExit", "code": code_val, "stage_id": estg}
    except Exception as exc:
        estg = active_stage_clock[0] or (stage_ids[0] if stage_ids else "S1")
        uncaught_stage_exceptions.add(estg)
        target_exception = {"type": type(exc).__qualname__, "stage_id": estg}
        if isinstance(exc, ImportError):
            m_name = str(getattr(exc, "name", "") or "").strip()
            if not m_name:
                m_re = re.search(r"No module named ['\"]([^'\"]+)['\"]", str(exc))
                m_name = m_re.group(1).strip() if m_re else ""
            if m_name:
                target_exception["missing_module"] = m_name
    finally:
        sys.settrace(None)
        _switch_stage_clock(None)
    elapsed_sec = round(time.perf_counter() - t_start, 6)

    if bound_abort is not None:
        atomic_locked_write_json(
            out_file,
            {
                "ok": False,
                "error_code": "BOUND_EXCEEDED_REFUSAL",
                "message": (
                    f"Runtime trace exceeded {bound_abort.bound_name}={bound_abort.bound_limit} "
                    f"(observed {bound_abort.observed_value})."
                ),
                "bound_name": bound_abort.bound_name,
                "bound_limit": bound_abort.bound_limit,
                "observed_value": bound_abort.observed_value,
            },
        )
        return 3

    # Build monotonic 4-Stage Smart Variable Funnel (global + per-stage)
    total_all_state = len(all_state_keys)
    union_stage_scope: Set[str] = set()
    union_delta_mutated: Set[str] = set()
    union_anomalies: Set[str] = set()
    funnel_by_stage: Dict[str, Dict[str, int]] = {}

    for sid in stage_ids:
        s_scope = set(stage_state_keys.get(sid) or set()) & all_state_keys
        s_anom = set(stage_anomaly_keys.get(sid) or set()) & s_scope
        s_delta = (set(stage_mutated_keys.get(sid) or set()) | s_anom) & s_scope
        union_stage_scope |= s_scope
        union_delta_mutated |= s_delta
        union_anomalies |= s_anom
        funnel_by_stage[sid] = {
            "all_state": total_all_state,
            "stage_scope": len(s_scope),
            "delta_mutated": len(s_delta),
            "anomalies_and_pinned_watches": len(s_anom),
        }

    global_stage_scope = len(union_stage_scope)
    global_anom = len(union_anomalies & union_stage_scope)
    global_delta = len((union_delta_mutated | union_anomalies) & union_stage_scope)

    clean_scopes: Dict[str, List[Dict[str, Any]]] = {}
    for sc in all_scopes:
        clean_scopes[sc] = [
            {k: v for k, v in rec.items() if k != "_bytes"}
            for rec in scope_records[sc].values()
        ]

    executed_lines_list = [
        {"file": f_rel, "line": ln, "hits": cnt}
        for (f_rel, ln), cnt in sorted(line_hits.items())
    ]
    call_edges_list = [
        {"caller_file": cf, "caller_symbol": cs, "callee_file": df, "callee_symbol": ds, "count": cnt}
        for (cf, cs, df, ds), cnt in sorted(call_edges.items())
    ]
    map_drift_list = [
        {
            "from_stage": fs,
            "to_stage": ts,
            "caller_file": cf,
            "caller_symbol": cs,
            "callee_file": df,
            "callee_symbol": ds,
            "line": ln,
            "count": cnt,
        }
        for (fs, ts, cf, cs, df, ds, ln), cnt in sorted(drift_edges.items())
    ]

    # Per-stage 3-way (+ VERIFIED_TRACE) verdicts
    stage_verdicts: Dict[str, str] = {}
    for u_stg in stage_ids:
        stg_units = [u for u in unit_index if u["stage_id"] == u_stg]
        stg_hits = sum(
            cnt
            for (f_rel, ln), cnt in line_hits.items()
            if any(u["file"] == f_rel and u["start_line"] <= ln <= u["end_line"] for u in stg_units)
        )
        has_tw = any(tw["stage_id"] == u_stg for tw in tripwires) or (u_stg in uncaught_stage_exceptions)
        has_drift = any(d["from_stage"] == u_stg or d["to_stage"] == u_stg for d in map_drift_list)
        if has_tw:
            stage_verdicts[u_stg] = "CODE_VIOLATES_SPEC"
        elif has_drift:
            stage_verdicts[u_stg] = "MAP_DRIFT"
        elif stg_hits == 0:
            stage_verdicts[u_stg] = "UNEXERCISED"
        else:
            stage_verdicts[u_stg] = "VERIFIED_TRACE"

    worker_res: Dict[str, Any] = {
        "ok": True,
        "elapsed_sec": elapsed_sec,
        "event_count": state_counters["events"],
        "sketch_bytes_used": state_counters["sketch_bytes"],
        "executed_lines": executed_lines_list,
        "call_edges": call_edges_list,
        "map_drift_edges": map_drift_list,
        "tripwires": tripwires,
        "stage_wall_sec": {sid: round(ns / 1e9, 6) for sid, ns in stage_wall_ns.items()},
        "stage_verdicts": stage_verdicts,
        "scopes": clean_scopes,
        "smart_variable_funnel": {
            "all_state": total_all_state,
            "stage_scope": global_stage_scope,
            "delta_mutated": global_delta,
            "anomalies_and_pinned_watches": global_anom,
            "monotonic": (total_all_state >= global_stage_scope >= global_delta >= global_anom),
            "by_stage": funnel_by_stage,
        },
        "uncaught_exception": target_exception,
    }
    atomic_locked_write_json(out_file, worker_res)
    return 0


# ---------------------------------------------------------------------------
# 5. Parent Consented Subprocess Coordinator (`run_consented_trace`)
# ---------------------------------------------------------------------------

_NODE_TRACER_MJS = """import inspector from "node:inspector";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const workRepo = path.resolve(manifest.work_repo);
const targetRelScript = manifest.target_rel_script;
const targetAbsPath = path.resolve(workRepo, targetRelScript);
const stageIds = manifest.stage_ids || ["S1"];
const unitIndex = manifest.unit_index || [];
const maxEvents = Number(manifest.max_events || 50000);
const maxSketchBytes = Number(manifest.max_sketch_bytes || 65536);
const pinnedSet = new Set(manifest.pinned_watches || []);

const preGlobals = new Map();
for (const k of Object.getOwnPropertyNames(globalThis)) {
  const d = Object.getOwnPropertyDescriptor(globalThis, k);
  if (d && Object.prototype.hasOwnProperty.call(d, "value")) preGlobals.set(k, d.value);
}

const session = new inspector.Session();
session.connect();
const post = (method, params = {}) =>
  new Promise((resolve, reject) => session.post(method, params, (err, res) => (err ? reject(err) : resolve(res))));

await post("Profiler.enable");
await post("Profiler.startPreciseCoverage", { callCount: true, detailed: true });

process.argv = [process.execPath, targetAbsPath, ...(manifest.script_args || [])];
let modNamespace = null;
let uncaughtException = null;
const t0 = performance.now();
try {
  modNamespace = await import(pathToFileURL(targetAbsPath).href);
} catch (err) {
  uncaughtException = {
    type: (err && err.name) || "Error",
    message: String((err && err.message) || err).slice(0, 240),
    stage_id: stageIds[0] || "S1",
  };
}
const elapsedSec = Number(((performance.now() - t0) / 1000).toFixed(6));

const cov = await post("Profiler.takePreciseCoverage");
await post("Profiler.stopPreciseCoverage");
session.disconnect();

const executedLines = [];
const lineHitMap = new Map();
const executedFns = new Map();
let eventCount = 0;

for (const scriptCov of cov.result || []) {
  if (!scriptCov.url || !scriptCov.url.startsWith("file://")) continue;
  let sp = "";
  try {
    sp = path.resolve(fileURLToPath(scriptCov.url));
  } catch {
    continue;
  }
  const relNative = path.relative(workRepo, sp);
  if (!relNative || relNative.startsWith("..") || path.isAbsolute(relNative)) continue;
  const rel = relNative.split(path.sep).join("/");
  if (!fs.existsSync(sp)) continue;
  const src = fs.readFileSync(sp, "utf8");
  const charCount = new Int32Array(src.length);
  const allRanges = [];
  for (const fn of scriptCov.functions || []) {
    if (fn.functionName && fn.ranges && fn.ranges.length > 0 && fn.ranges[0].count > 0) {
      executedFns.set(`${rel}::${fn.functionName}`, Number(fn.ranges[0].count));
    }
    for (const r of fn.ranges || []) {
      allRanges.push({
        start: Math.max(0, Number(r.startOffset || 0)),
        end: Math.min(src.length, Number(r.endOffset || 0)),
        count: Number(r.count || 0),
      });
    }
  }
  allRanges.sort((a, b) => (b.end - b.start) - (a.end - a.start));
  for (const r of allRanges) {
    for (let i = r.start; i < r.end; i++) charCount[i] = r.count;
  }
  const rawLines = src.split("\\n");
  let offset = 0;
  for (let idx = 0; idx < rawLines.length; idx++) {
    const rawLn = rawLines[idx];
    const cleanLn = rawLn.endsWith("\\r") ? rawLn.slice(0, -1) : rawLn;
    const trimmed = cleanLn.trim();
    const lno = idx + 1;
    if (trimmed && !trimmed.startsWith("//") && !trimmed.startsWith("/*") && !trimmed.startsWith("*")) {
      const firstWs = cleanLn.search(/\\S/);
      const startOff = offset + Math.max(0, firstWs);
      const endOff = offset + cleanLn.length;
      let maxHit = 0;
      for (let k = startOff; k < endOff; k++) {
        if (charCount[k] > maxHit) maxHit = charCount[k];
      }
      if (maxHit > 0) {
        executedLines.push({ file: rel, line: lno, hits: maxHit });
        lineHitMap.set(`${rel}:${lno}`, { hits: maxHit, text: cleanLn });
        eventCount += maxHit;
        if (eventCount > maxEvents) {
          fs.writeFileSync(
            manifest.worker_output,
            JSON.stringify({
              ok: false,
              error_code: "BOUND_EXCEEDED_REFUSAL",
              message: `Runtime trace exceeded max_events=${maxEvents} (observed ${eventCount}).`,
              bound_name: "max_events",
              bound_limit: maxEvents,
              observed_value: eventCount,
            }),
            "utf8"
          );
          process.exit(3);
        }
      }
    }
    offset += rawLn.length + 1;
  }
}

function lookupUnit(relFile, lineNo) {
  let best = null;
  for (const u of unitIndex) {
    if (u.file === relFile && lineNo >= u.start_line && lineNo <= u.end_line) {
      if (!best || (u.end_line - u.start_line) < (best.end_line - best.start_line)) best = u;
    }
  }
  return best;
}

if (uncaughtException && executedLines.length > 0) {
  const lastExec = executedLines[executedLines.length - 1];
  const u = lookupUnit(lastExec.file, lastExec.line);
  if (u) uncaughtException.stage_id = u.stage_id;
}

const callEdges = [];
for (const [fnKey, cnt] of executedFns.entries()) {
  const [calleeFile, calleeSym] = fnKey.split("::");
  for (const cu of unitIndex) {
    if ((cu.static_calls || []).includes(calleeSym)) {
      const callerExecuted = executedLines.some(
        (el) => el.file === cu.file && el.line >= cu.start_line && el.line <= cu.end_line
      );
      if (callerExecuted) {
        callEdges.push({
          caller_file: cu.file,
          caller_symbol: cu.short_name,
          callee_file: calleeFile,
          callee_symbol: calleeSym,
          count: cnt,
        });
      }
    }
  }
}

function sketchSafe(val) {
  const nfs = [];
  const checkNum = (n) => {
    if (Number.isNaN(n)) {
      if (!nfs.includes("NaN")) nfs.push("NaN");
    } else if (n === Infinity) {
      if (!nfs.includes("+Infinity")) nfs.push("+Infinity");
    } else if (n === -Infinity) {
      if (!nfs.includes("-Infinity")) nfs.push("-Infinity");
    }
  };
  if (val === null || val === undefined) return [{ kind: "null" }, nfs];
  const t = typeof val;
  if (t === "number") {
    checkNum(val);
    return [{ kind: "scalar", type: "number", finite: Number.isFinite(val), value: Number.isFinite(val) ? val : String(val) }, nfs];
  }
  if (t === "boolean" || t === "bigint") {
    return [{ kind: "scalar", type: t, value: String(val).slice(0, 64) }, nfs];
  }
  if (t === "string") {
    return [{ kind: "string", length: val.length, preview: val.slice(0, 64) }, nfs];
  }
  if (Array.isArray(val) || ArrayBuffer.isView(val)) {
    const len = Number(val.length || 0);
    const lim = Math.min(len, 4096);
    for (let i = 0; i < lim; i++) {
      const el = val[i];
      if (typeof el === "number") checkNum(el);
    }
    return [{ kind: "sequence", type: Array.isArray(val) ? "Array" : val.constructor.name, length: len }, nfs];
  }
  if (t === "object") {
    const descs = Object.getOwnPropertyDescriptors(val);
    const fields = [];
    for (const [k, d] of Object.entries(descs).slice(0, 16)) {
      fields.push(k);
      if (d && Object.prototype.hasOwnProperty.call(d, "value") && typeof d.value === "number") {
        checkNum(d.value);
      }
    }
    return [{ kind: "object", fields }, nfs];
  }
  return [{ kind: "other", type: t }, nfs];
}

const scopes = {
  function_locals: [],
  closure_nonlocals: [],
  instance_attrs: [],
  module_globals: [],
  stage_io_contracts: [],
};
const tripwires = [];
const allStateKeys = new Set();
const stageStateKeys = new Map(stageIds.map((s) => [s, new Set()]));
const stageMutatedKeys = new Map(stageIds.map((s) => [s, new Set()]));
const stageAnomalyKeys = new Map(stageIds.map((s) => [s, new Set()]));
let sketchBytesUsed = 0;

function recordBinding(scopeName, varName, val) {
  if (typeof val === "function") return;
  const [sketch, nfs] = sketchSafe(val);
  let matchedLine = executedLines.length > 0 ? executedLines[executedLines.length - 1].line : 1;
  let matchedFile = executedLines.length > 0 ? executedLines[executedLines.length - 1].file : targetRelScript;
  const esc = varName.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
  const assignRe = new RegExp(`\\\\b${esc}\\\\b`);
  for (const el of executedLines) {
    const info = lineHitMap.get(`${el.file}:${el.line}`);
    if (info && assignRe.test(info.text)) {
      matchedFile = el.file;
      matchedLine = el.line;
    }
  }
  const u = lookupUnit(matchedFile, matchedLine);
  const sid = u ? u.stage_id : (stageIds[0] || "S1");
  const sym = u ? u.symbol : "<module>";
  const vkey = `${scopeName}:${matchedFile}:${sym}:${varName}`;
  const encoded = JSON.stringify(sketch);
  sketchBytesUsed += encoded.length + vkey.length + 32;
  if (sketchBytesUsed > maxSketchBytes) {
    fs.writeFileSync(
      manifest.worker_output,
      JSON.stringify({
        ok: false,
        error_code: "BOUND_EXCEEDED_REFUSAL",
        message: `Runtime trace exceeded max_sketch_bytes=${maxSketchBytes} (observed ${sketchBytesUsed}).`,
        bound_name: "max_sketch_bytes",
        bound_limit: maxSketchBytes,
        observed_value: sketchBytesUsed,
      }),
      "utf8"
    );
    process.exit(3);
  }
  scopes[scopeName].push({
    key: vkey,
    scope: scopeName,
    stage_id: sid,
    file: matchedFile,
    line: matchedLine,
    symbol: sym,
    name: varName,
    sketch,
  });
  allStateKeys.add(vkey);
  if (!stageStateKeys.has(sid)) {
    stageStateKeys.set(sid, new Set());
    stageMutatedKeys.set(sid, new Set());
    stageAnomalyKeys.set(sid, new Set());
  }
  stageStateKeys.get(sid).add(vkey);
  stageMutatedKeys.get(sid).add(vkey);
  if (nfs.length > 0) {
    for (const nf of nfs) {
      tripwires.push({
        stage_id: sid,
        file: matchedFile,
        line: matchedLine,
        symbol: sym,
        variable: varName,
        scope: scopeName,
        kind: nf,
      });
    }
    stageAnomalyKeys.get(sid).add(vkey);
  } else if (pinnedSet.has(varName) || pinnedSet.has(vkey)) {
    stageAnomalyKeys.get(sid).add(vkey);
  }
}

for (const k of Object.getOwnPropertyNames(globalThis)) {
  if (k.startsWith("_")) continue;
  const d = Object.getOwnPropertyDescriptor(globalThis, k);
  if (!d || !Object.prototype.hasOwnProperty.call(d, "value")) continue;
  if (!preGlobals.has(k) || !Object.is(preGlobals.get(k), d.value)) {
    recordBinding("module_globals", k, d.value);
  }
}

if (modNamespace && typeof modNamespace === "object") {
  for (const k of Object.keys(modNamespace)) {
    if (k === "default") {
      const defVal = modNamespace.default;
      if (defVal && typeof defVal === "object" && !Array.isArray(defVal)) {
        const descs = Object.getOwnPropertyDescriptors(defVal);
        for (const [dk, dd] of Object.entries(descs)) {
          if (dd && Object.prototype.hasOwnProperty.call(dd, "value")) {
            recordBinding("stage_io_contracts", dk, dd.value);
          }
        }
      } else {
        recordBinding("stage_io_contracts", "default", defVal);
      }
    } else {
      recordBinding("stage_io_contracts", k, modNamespace[k]);
    }
  }
}

const totalHitsAll = Math.max(1, executedLines.reduce((acc, x) => acc + x.hits, 0));
const stageWallSec = {};
const stageVerdicts = {};
const funnelByStage = {};
let unionScope = new Set();
let unionDelta = new Set();
let unionAnom = new Set();

for (const sid of stageIds) {
  const stgUnits = unitIndex.filter((u) => u.stage_id === sid);
  const stgHits = executedLines
    .filter((el) => stgUnits.some((u) => u.file === el.file && el.line >= u.start_line && el.line <= u.end_line))
    .reduce((acc, x) => acc + x.hits, 0);
  stageWallSec[sid] = Number(((elapsedSec * stgHits) / totalHitsAll).toFixed(6));
  const hasTw = tripwires.some((tw) => tw.stage_id === sid) || (uncaughtException && uncaughtException.stage_id === sid);
  if (hasTw) stageVerdicts[sid] = "CODE_VIOLATES_SPEC";
  else if (stgHits === 0) stageVerdicts[sid] = "UNEXERCISED";
  else stageVerdicts[sid] = "VERIFIED_TRACE";

  const sScope = stageStateKeys.get(sid) || new Set();
  const sDelta = stageMutatedKeys.get(sid) || new Set();
  const sAnom = stageAnomalyKeys.get(sid) || new Set();
  for (const x of sScope) unionScope.add(x);
  for (const x of sDelta) unionDelta.add(x);
  for (const x of sAnom) unionAnom.add(x);
  funnelByStage[sid] = {
    all_state: allStateKeys.size,
    stage_scope: sScope.size,
    delta_mutated: sDelta.size,
    anomalies_and_pinned_watches: sAnom.size,
  };
}

const workerRes = {
  ok: true,
  elapsed_sec: elapsedSec,
  event_count: eventCount,
  sketch_bytes_used: sketchBytesUsed,
  executed_lines: executedLines,
  call_edges: callEdges,
  map_drift_edges: [],
  tripwires,
  stage_wall_sec: stageWallSec,
  stage_verdicts: stageVerdicts,
  scopes,
  smart_variable_funnel: {
    all_state: allStateKeys.size,
    stage_scope: unionScope.size,
    delta_mutated: unionDelta.size,
    anomalies_and_pinned_watches: unionAnom.size,
    monotonic: allStateKeys.size >= unionScope.size && unionScope.size >= unionDelta.size && unionDelta.size >= unionAnom.size,
    by_stage: funnelByStage,
  },
  uncaught_exception: uncaughtException,
};
fs.writeFileSync(manifest.worker_output, JSON.stringify(workerRes, null, 2), "utf8");
"""

_R_TRACER_SCRIPT = """args <- commandArgs(trailingOnly = TRUE)
cfg <- readLines(args[1], warn = FALSE, encoding = "UTF-8")
target_rel <- cfg[1]
raw_out <- cfg[2]
max_events <- as.integer(cfg[3])
trace_env <- new.env(parent = globalenv())
t0 <- proc.time()[["elapsed"]]
out_lines <- character(0)
err_msg <- ""
exprs <- tryCatch(parse(file = target_rel, keep.source = TRUE), error = function(e) {
  err_msg <<- conditionMessage(e)
  NULL
})
ev_count <- 0L
if (!is.null(exprs)) {
  srcrefs <- attr(exprs, "srcref")
  for (i in seq_along(exprs)) {
    sref <- if (!is.null(srcrefs) && length(srcrefs) >= i) srcrefs[[i]] else NULL
    l1 <- if (!is.null(sref)) as.integer(sref[1]) else i
    l2 <- if (!is.null(sref)) as.integer(sref[3]) else l1
    for (ln in seq.int(l1, l2)) {
      ev_count <- ev_count + 1L
      out_lines <- c(out_lines, paste("LINE", ln, sep = "\\t"))
    }
    if (ev_count > max_events) break
    ok <- tryCatch({
      do.call(base::"eval", list(exprs[[i]], envir = trace_env))
      TRUE
    }, error = function(e) {
      err_msg <<- conditionMessage(e)
      FALSE
    })
    if (!ok) break
  }
}
elapsed <- proc.time()[["elapsed"]] - t0
out_lines <- c(paste("META", sprintf("%.6f", elapsed), ev_count, gsub("[\\r\\n\\t]", " ", err_msg), sep = "\\t"), out_lines)
for (nm in ls(trace_env, all.names = FALSE)) {
  v <- get(nm, envir = trace_env)
  if (is.function(v)) next
  nf <- ""
  if (is.numeric(v)) {
    if (any(is.nan(v))) nf <- paste(c(nf, "NaN"), collapse = ",")
    if (any(is.infinite(v) & v > 0)) nf <- paste(c(nf, "+Infinity"), collapse = ",")
    if (any(is.infinite(v) & v < 0)) nf <- paste(c(nf, "-Infinity"), collapse = ",")
  }
  out_lines <- c(out_lines, paste("VAR", nm, typeof(v), length(v), gsub("^,+|,+$", "", nf), sep = "\\t"))
}
writeLines(out_lines, con = raw_out, useBytes = TRUE)
"""


def _finalize_r_worker_trace(
    raw_tsv: Path,
    worker_out: Path,
    target_rel_script: str,
    stage_ids: List[str],
    unit_index: List[Dict[str, Any]],
    max_events: int,
    max_sketch_bytes: int,
    pinned_watches: Sequence[str],
) -> None:
    if not raw_tsv.is_file():
        return
    rows = raw_tsv.read_text(encoding="utf-8", errors="replace").splitlines()
    elapsed_sec = 0.0
    ev_count = 0
    err_msg = ""
    line_hits: Dict[int, int] = {}
    var_rows: List[Tuple[str, str, int, List[str]]] = []
    for r in rows:
        parts = r.split("\t")
        if not parts:
            continue
        if parts[0] == "META" and len(parts) >= 4:
            elapsed_sec = float(parts[1] or 0.0)
            ev_count = int(parts[2] or 0)
            err_msg = parts[3].strip()
        elif parts[0] == "LINE" and len(parts) >= 2:
            ln = int(parts[1])
            line_hits[ln] = line_hits.get(ln, 0) + 1
        elif parts[0] == "VAR" and len(parts) >= 5:
            nfs = [x for x in parts[4].split(",") if x]
            var_rows.append((parts[1], parts[2], int(parts[3] or 0), nfs))

    if ev_count > max_events:
        atomic_locked_write_json(
            worker_out,
            {
                "ok": False,
                "error_code": "BOUND_EXCEEDED_REFUSAL",
                "message": f"Runtime trace exceeded max_events={max_events} (observed {ev_count}).",
                "bound_name": "max_events",
                "bound_limit": max_events,
                "observed_value": ev_count,
            },
        )
        return

    sids = stage_ids or ["S1"]
    executed_lines = [{"file": target_rel_script, "line": ln, "hits": cnt} for ln, cnt in sorted(line_hits.items())]
    last_ln = max(line_hits.keys()) if line_hits else 1

    def _unit_for_line(ln: int) -> Optional[Dict[str, Any]]:
        matches = [u for u in unit_index if u["file"] == target_rel_script and u["start_line"] <= ln <= u["end_line"]]
        return min(matches, key=lambda u: u["end_line"] - u["start_line"]) if matches else None

    u_last = _unit_for_line(last_ln)
    last_sid = u_last["stage_id"] if u_last else sids[0]
    uncaught_exc = {"type": "RError", "message": err_msg[:240], "stage_id": last_sid} if err_msg else None

    scopes: Dict[str, List[Dict[str, Any]]] = {
        "function_locals": [],
        "closure_nonlocals": [],
        "instance_attrs": [],
        "module_globals": [],
        "stage_io_contracts": [],
    }
    tripwires: List[Dict[str, Any]] = []
    all_keys: Set[str] = set()
    stg_scope: Dict[str, Set[str]] = {s: set() for s in sids}
    stg_delta: Dict[str, Set[str]] = {s: set() for s in sids}
    stg_anom: Dict[str, Set[str]] = {s: set() for s in sids}
    sketch_bytes = 0
    pinned_set = set(pinned_watches)

    for vname, vtype, vlen, nfs in var_rows:
        vkey = f"module_globals:{target_rel_script}:<module>:{vname}"
        sk = {"kind": "sequence" if vlen > 1 else "scalar", "type": vtype, "length": vlen}
        sketch_bytes += len(json.dumps(sk)) + len(vkey) + 32
        if sketch_bytes > max_sketch_bytes:
            atomic_locked_write_json(
                worker_out,
                {
                    "ok": False,
                    "error_code": "BOUND_EXCEEDED_REFUSAL",
                    "message": f"Runtime trace exceeded max_sketch_bytes={max_sketch_bytes} (observed {sketch_bytes}).",
                    "bound_name": "max_sketch_bytes",
                    "bound_limit": max_sketch_bytes,
                    "observed_value": sketch_bytes,
                },
            )
            return
        scopes["module_globals"].append({
            "key": vkey,
            "scope": "module_globals",
            "stage_id": last_sid,
            "file": target_rel_script,
            "line": last_ln,
            "symbol": "<module>",
            "name": vname,
            "sketch": sk,
        })
        all_keys.add(vkey)
        stg_scope.setdefault(last_sid, set()).add(vkey)
        stg_delta.setdefault(last_sid, set()).add(vkey)
        if nfs:
            for nf in nfs:
                tripwires.append({
                    "stage_id": last_sid,
                    "file": target_rel_script,
                    "line": last_ln,
                    "symbol": "<module>",
                    "variable": vname,
                    "scope": "module_globals",
                    "kind": nf,
                })
            stg_anom.setdefault(last_sid, set()).add(vkey)
        elif vname in pinned_set or vkey in pinned_set:
            stg_anom.setdefault(last_sid, set()).add(vkey)

    stage_verdicts: Dict[str, str] = {}
    stage_wall: Dict[str, float] = {}
    tot_hits = max(1, sum(line_hits.values()))
    funnel_by_stage: Dict[str, Dict[str, int]] = {}
    for sid in sids:
        su = [u for u in unit_index if u["stage_id"] == sid]
        shits = sum(cnt for ln, cnt in line_hits.items() if any(u["file"] == target_rel_script and u["start_line"] <= ln <= u["end_line"] for u in su))
        stage_wall[sid] = round((elapsed_sec * shits) / tot_hits, 6)
        has_tw = any(tw["stage_id"] == sid for tw in tripwires) or (uncaught_exc is not None and uncaught_exc["stage_id"] == sid)
        stage_verdicts[sid] = "CODE_VIOLATES_SPEC" if has_tw else ("UNEXERCISED" if shits == 0 else "VERIFIED_TRACE")
        funnel_by_stage[sid] = {
            "all_state": len(all_keys),
            "stage_scope": len(stg_scope.get(sid, set())),
            "delta_mutated": len(stg_delta.get(sid, set())),
            "anomalies_and_pinned_watches": len(stg_anom.get(sid, set())),
        }

    u_scope = set().union(*stg_scope.values()) if stg_scope else set()
    u_delta = set().union(*stg_delta.values()) if stg_delta else set()
    u_anom = set().union(*stg_anom.values()) if stg_anom else set()
    atomic_locked_write_json(
        worker_out,
        {
            "ok": True,
            "elapsed_sec": round(elapsed_sec, 6),
            "event_count": ev_count,
            "sketch_bytes_used": sketch_bytes,
            "executed_lines": executed_lines,
            "call_edges": [],
            "map_drift_edges": [],
            "tripwires": tripwires,
            "stage_wall_sec": stage_wall,
            "stage_verdicts": stage_verdicts,
            "scopes": scopes,
            "smart_variable_funnel": {
                "all_state": len(all_keys),
                "stage_scope": len(u_scope),
                "delta_mutated": len(u_delta),
                "anomalies_and_pinned_watches": len(u_anom),
                "monotonic": len(all_keys) >= len(u_scope) >= len(u_delta) >= len(u_anom),
                "by_stage": funnel_by_stage,
            },
            "uncaught_exception": uncaught_exc,
        },
    )


def _build_unit_index(repo_root: Path, static_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    from anvil_v4_process import _extract_polyglot_units, _extract_python_units

    raw_calls_map: Dict[Tuple[str, str], List[str]] = {}
    for fm in static_map.get("l3_files") or []:
        rel_f = str(fm.get("file") or "")
        fp = (repo_root / rel_f).resolve()
        if not fp.is_file():
            continue
        if rel_f.endswith(".py"):
            units, _ = _extract_python_units(fp, rel_f)
            for u in units:
                raw_calls_map[(rel_f, str(u["symbol"]))] = list(u.get("calls") or [])
        elif Path(rel_f).suffix in {".js", ".mjs", ".ts", ".r", ".R"}:
            units, _ = _extract_polyglot_units(fp, rel_f)
            for u in units:
                raw_calls_map[(rel_f, str(u["symbol"]))] = list(u.get("calls") or [])

    out: List[Dict[str, Any]] = []
    for step in static_map.get("l2_steps") or []:
        cref = step.get("code_ref") or {}
        rel_f = str(cref.get("file") or "")
        sym = str(cref.get("symbol") or "")
        short = sym.split(".")[-1] if sym else ""
        out.append({
            "step_id": str(step.get("id") or ""),
            "stage_id": str(step.get("stage_id") or "S1"),
            "file": rel_f,
            "symbol": sym,
            "short_name": short,
            "start_line": int(cref.get("start_line") or 1),
            "end_line": int(cref.get("end_line") or 1),
            "static_calls": raw_calls_map.get((rel_f, sym), []),
        })
    return out


def run_consented_trace(
    repo_dir: str | Path,
    argv: Sequence[str],
    *,
    approve_run: bool = False,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_sketch_bytes: int = DEFAULT_MAX_SKETCH_BYTES,
    pinned_watches: Optional[Sequence[str]] = None,
    output_path: Optional[str | Path] = None,
    persist: bool = True,
    paper_path: Optional[str | Path] = None,
    pipeline_id: Optional[str] = None,
    static_map: Optional[Dict[str, Any]] = None,
    cockpit_root: Optional[str | Path] = None,
    store_root: Optional[str | Path] = None,
    verified_extra_site_packages: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Execute a consented local child-subprocess trace inside an isolated temp
    worktree copy with `shell=False`, scrubbed credential env, and process-tree
    timeout termination.
    """
    if not approve_run:
        raise AnvilRefusalError(
            "CONSENT_REQUIRED_REFUSED",
            "Explicit --approve-run operator consent is required before executing local subprocess traces.",
            details={
                "isolation_boundary": ISOLATION_BOUNDARY,
                "non_vm_trust_warning": NON_VM_TRUST_WARNING,
            },
        )

    if max_events <= 0 or max_events > MAX_TRACE_EVENTS:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_events ({max_events}) must be within 1..{MAX_TRACE_EVENTS}.",
            details={
                "bound_name": "max_events",
                "bound_limit": MAX_TRACE_EVENTS,
                "observed_value": max_events,
            },
        )
    if max_sketch_bytes <= 0 or max_sketch_bytes > MAX_SKETCH_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_sketch_bytes ({max_sketch_bytes}) must be within 1..{MAX_SKETCH_BYTES}.",
            details={
                "bound_name": "max_sketch_bytes",
                "bound_limit": MAX_SKETCH_BYTES,
                "observed_value": max_sketch_bytes,
            },
        )
    if timeout_sec <= 0 or timeout_sec > MAX_TIMEOUT_SEC:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"timeout_sec ({timeout_sec}) must be within (0, {MAX_TIMEOUT_SEC}].",
            details={
                "bound_name": "timeout_sec",
                "bound_limit": MAX_TIMEOUT_SEC,
                "observed_value": timeout_sec,
            },
        )

    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    policy_info = validate_execution_argv(root, argv)
    runner_kind = policy_info["runner_kind"]
    resolved_binary = str(policy_info["resolved_binary"] or "")
    if runner_kind in {"node", "rscript"} and (not resolved_binary or not Path(resolved_binary).is_file()):
        raise AnvilRefusalError(
            "DEPENDENCY_MISSING",
            "Required runtime/tracer unavailable — showing static AST map",
            details={
                "status_kind": "dependency-missing",
                "http_status": 503,
                "runner_kind": runner_kind,
                "isolation_boundary": ISOLATION_BOUNDARY,
            },
        )

    if static_map is None:
        static_map = build_process_map(root, persist=False, paper_path=paper_path, pipeline_id=pipeline_id)
    stage_ids = [str(s["id"]) for s in (static_map.get("l1_stages") or [])]
    unit_index = _build_unit_index(root, static_map)

    scratch_dir = Path(tempfile.mkdtemp(prefix="anvil_v4_trace_"))
    try:
        work_repo = _stage_isolated_worktree_copy(root, scratch_dir)
        target_rel = policy_info["target_rel_script"]
        if target_rel and not (work_repo / target_rel).is_file():
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Target script '{target_rel}' is gitignored or excluded as sensitive and cannot be staged.",
                cwe="CWE-78",
            )
        if runner_kind == "pytest":
            for pt_arg in policy_info["pytest_args"]:
                if not pt_arg.startswith("-") and pt_arg != ".":
                    f_part = pt_arg.split("::", 1)[0]
                    if (root / f_part).is_file() and not (work_repo / f_part).is_file():
                        raise AnvilRefusalError(
                            "EXECUTION_POLICY_REFUSED",
                            f"Target test file '{f_part}' is gitignored or excluded as sensitive and cannot be staged.",
                            cwe="CWE-78",
                        )

        iso_home = scratch_dir / "_home_tmp"
        scrubbed_env = build_scrubbed_env(iso_home)
        worker_out = scratch_dir / "_worker_trace_out.json"
        r_raw_tsv = scratch_dir / "_r_raw_trace.tsv"

        ck_p = Path(cockpit_root).resolve() if (cockpit_root is not None and str(cockpit_root).strip()) else None
        st_p = Path(store_root).resolve() if (store_root is not None and str(store_root).strip()) else None
        priority_site_packages, host_site_packages = _discover_priority_and_host_site_packages(root, cockpit_root=ck_p, store_root=st_p, verified_extra_site_packages=verified_extra_site_packages)
        manifest_path = scratch_dir / "_worker_manifest.json"
        atomic_locked_write_json(
            manifest_path,
            {
                "work_repo": str(work_repo),
                "runner_kind": runner_kind,
                "target_rel_script": target_rel,
                "script_args": policy_info["script_args"],
                "pytest_args": policy_info["pytest_args"],
                "max_events": int(max_events),
                "max_sketch_bytes": int(max_sketch_bytes),
                "pinned_watches": list(pinned_watches or []),
                "worker_output": str(worker_out),
                "stage_ids": stage_ids,
                "unit_index": unit_index,
                "priority_site_packages": priority_site_packages,
                "host_site_packages": host_site_packages,
            },
        )
        if runner_kind == "node":
            tracer_mjs = scratch_dir / "_anvil_node_tracer.mjs"
            tracer_mjs.write_text(_NODE_TRACER_MJS, encoding="utf-8")
            spawn_argv = [resolved_binary, str(tracer_mjs), str(manifest_path)]
        elif runner_kind == "rscript":
            tracer_r = scratch_dir / "_anvil_r_tracer.R"
            r_cfg = scratch_dir / "_r_config.txt"
            tracer_r.write_text(_R_TRACER_SCRIPT, encoding="utf-8")
            r_cfg.write_text(f"{target_rel}\n{r_raw_tsv}\n{int(max_events)}\n", encoding="utf-8")
            spawn_argv = [resolved_binary, "--vanilla", str(tracer_r), str(r_cfg), *policy_info["script_args"]]
        else:
            spawn_argv = [sys.executable, str(Path(__file__).resolve()), "--_worker-manifest", str(manifest_path)]

        creationflags = (subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000) if os.name == "nt" else 0
        proc = subprocess.Popen(
            spawn_argv,
            cwd=str(work_repo),
            env=scrubbed_env,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name != "nt"),
            creationflags=creationflags,
        )
        try:
            stdout_b, stderr_b = proc.communicate(timeout=float(timeout_sec))
        except subprocess.TimeoutExpired as tex:
            _kill_process_tree(proc)
            raise AnvilRefusalError(
                "TRACE_TIMEOUT_REFUSED",
                "Trace subprocess timed out and process tree was killed (TRACE_TIMEOUT_KILLED) — partial trace preserved",
                details={
                    "verdict": "TRACE_TIMEOUT_KILLED",
                    "timeout_verdict": "TRACE_TIMEOUT_KILLED",
                    "tree_killed": True,
                    "status_kind": "dependency-slow-or-killed",
                    "http_status": 504,
                    "timeout_sec": float(timeout_sec),
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            ) from tex

        stdout_preview = stdout_b.decode("utf-8", errors="replace")[:4096]
        stderr_preview = stderr_b.decode("utf-8", errors="replace")[:4096]

        if runner_kind == "rscript" and r_raw_tsv.is_file():
            _finalize_r_worker_trace(
                r_raw_tsv,
                worker_out,
                target_rel,
                stage_ids,
                unit_index,
                int(max_events),
                int(max_sketch_bytes),
                list(pinned_watches or []),
            )

        if not worker_out.is_file():
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                "Malformed trace/validator payload — rejected fail-closed",
                cwe="CWE-502",
                details={
                    "status_kind": "dependency-returns-garbage",
                    "http_status": 502,
                    "returncode": proc.returncode,
                    "stderr_preview": stderr_preview[:512],
                },
            )
        worker_data = atomic_locked_read_json(worker_out)
        if not worker_data.get("ok", False):
            err_code = str(worker_data.get("error_code") or "BOUND_EXCEEDED_REFUSAL")
            err_msg = str(worker_data.get("message") or "Trace bound exceeded.")
            extra = {
                k: v
                for k, v in worker_data.items()
                if k not in {"ok", "error_code", "message"}
            }
            raise AnvilRefusalError(err_code, err_msg, details=extra)

        uncaught_exc = worker_data.get("uncaught_exception")
        if isinstance(uncaught_exc, dict) and uncaught_exc.get("missing_module"):
            miss_m = str(uncaught_exc["missing_module"]).strip()
            raise AnvilRefusalError(
                "PIPELINE_DEPENDENCY_MISSING",
                f"PIPELINE_DEPENDENCY_MISSING: Missing package '{miss_m}'",
                details={
                    "status_kind": "dependency-missing",
                    "http_status": 503,
                    "missing_module": miss_m,
                    "uncaught_exception": uncaught_exc,
                    "stderr_preview": stderr_preview[:512],
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            )
        exec_lines_out = list(worker_data.get("executed_lines") or [])
        if uncaught_exc is not None and len(exec_lines_out) == 0:
            raise AnvilRefusalError(
                "TARGET_EXECUTION_FAILED",
                f"Target execution failed before any repository line executed ({uncaught_exc}).",
                details={
                    "uncaught_exception": uncaught_exc,
                    "stderr_preview": stderr_preview[:512],
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            )
        effective_rc = int(proc.returncode or 0)
        if uncaught_exc is not None and effective_rc == 0:
            effective_rc = 1

        trace_doc: Dict[str, Any] = {
            "ok": True,
            "schema": TRACE_SCHEMA,
            "isolation_boundary": ISOLATION_BOUNDARY,
            "non_vm_trust_warning": NON_VM_TRUST_WARNING,
            "approve_run": True,
            "repo_fingerprint": static_map.get("repo_fingerprint", ""),
            "validated_argv": policy_info["validated_argv"],
            "runner_kind": runner_kind,
            "returncode": effective_rc,
            "elapsed_sec": worker_data["elapsed_sec"],
            "bounds": {
                "max_events": int(max_events),
                "max_sketch_bytes": int(max_sketch_bytes),
                "timeout_sec": float(timeout_sec),
                "observed_events": int(worker_data["event_count"]),
                "observed_sketch_bytes": int(worker_data["sketch_bytes_used"]),
            },
            "executed_lines": exec_lines_out,
            "call_edges": worker_data["call_edges"],
            "map_drift_edges": worker_data["map_drift_edges"],
            "tripwires": worker_data["tripwires"],
            "stage_wall_sec": worker_data["stage_wall_sec"],
            "stage_verdicts": worker_data["stage_verdicts"],
            "scopes": worker_data["scopes"],
            "smart_variable_funnel": worker_data["smart_variable_funnel"],
            "uncaught_exception": uncaught_exc,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
        }

        if persist or output_path is not None:
            dest = Path(output_path).resolve() if output_path else (root / ".anvil" / "v4" / "last_trace.json")
            atomic_locked_write_json(dest, trace_doc)

        return trace_doc
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


from anvil_v4_repl_scratch import (  # noqa: E402
    _apply_unified_diff_in_scratch,
    _check_python_ast_sinks_safe,
    discover_priority_and_host_site_packages as _discover_priority_and_host_site_packages,
    execute_replication_table_in_scratch,
)


def run_replication_table_in_scratch(repo_dir: str | Path, argv: Sequence[str], **kwargs: Any) -> Dict[str, Any]:
    return execute_replication_table_in_scratch(
        repo_dir,
        argv,
        validate_argv_fn=validate_execution_argv,
        stage_worktree_fn=_stage_isolated_worktree_copy,
        build_env_fn=build_scrubbed_env,
        kill_tree_fn=_kill_process_tree,
        **kwargs,
    )


def _worker_cli_entry(argv: Sequence[str]) -> int:
    if len(argv) == 2 and argv[0] == "--_worker-manifest":
        return _run_python_tracer_worker(Path(argv[1]))
    sys.stderr.write("Internal worker entrypoint requires --_worker-manifest <path>.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_worker_cli_entry(sys.argv[1:]))
