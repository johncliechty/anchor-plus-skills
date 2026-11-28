#!/usr/bin/env python3
"""Anvil v4 Pillar 1 & Durable Store — Canonical Path Containment, Cross-Process
Atomic File-Locked JSON Persistence, Paper-Matched Replication Scope Discovery,
and Zero-Execution Steady-Coordinate L0->L3 Dual-Channel Process Map
(`scripts/anvil_v4_process.py`).
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import warnings
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

if os.name == "nt":
    import msvcrt
else:
    import fcntl


PROCESS_MAP_SCHEMA = "anvil-v4-process-map/v1"
TRACE_SCHEMA = "anvil-v4-trace/v1"
ISOLATION_BOUNDARY_CONSENTED = "consented_local_subprocess"
MAX_TIMEOUT_SEC_DEFAULT = 300.0
NON_VM_TRUST_WARNING_DEFAULT = (
    "Consented local child subprocess isolation (isolated temp copy + argv policy "
    "+ scrubbed env); NOT an OS/VM sandbox against hostile untrusted malware."
)

SKIP_SCAN_DIRS: Set[str] = {
    ".git", ".anvil", ".foreman", ".crucible", ".anchor", ".ecgberht", ".steward",
    "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".hypothesis", "dist", "build", "vendor", "_archive",
}

INGEST_HINTS: Tuple[str, ...] = (
    "load", "read", "parse", "ingest", "fetch", "open", "scan", "extract", "input", "init", "setup", "config",
)
EMIT_HINTS: Tuple[str, ...] = (
    "write", "save", "emit", "render", "export", "report", "dump", "format", "serialize", "output", "publish",
)
LOOP_HINTS: Tuple[str, ...] = (
    "loop", "iterate", "train", "sweep", "evolve", "refine", "epoch", "step_loop", "converge",
)

HISTORICAL_CLUTTER_TOKENS: Tuple[str, ...] = (
    "old", "backup", "bak", "deprecated", "legacy", "unused", "obsolete",
    "prototype", "proto", "trial", "scratch", "abandoned", "archive", "archived",
    "tmp", "temp", "snapshots",
)

ARCHIVE_OR_STAGING_DIRS: Set[str] = {
    "old", "archive", "archived", "backup", "bak", "deprecated", "obsolete",
    "review-input", "code-job-outputs", "snapshots", ".hypothesis",
}

WORKFLOW_MANIFEST_NAMES: Tuple[str, ...] = (
    "workflow.sh", "run_all.sh", "replicate.sh", "replication.sh", "pipeline.sh", "run.sh",
    "Makefile", "makefile", "GNUmakefile", "Snakefile", "REPLICATION.md", "replication.md",
)

SCOPE_MANIFEST_SCHEMA_VERSION = "anvil-scope-manifest/v6.1"
SYMBOL_SLICE_SCHEMA = "anvil-symbol-slice/v6.1"
SYMBOL_CALL_GRAPH_SCHEMA = "anvil-call-graph/v6.1"
SOFTWARE_PAPER_MAP_SCHEMA = "anvil-software-paper-map/v6.1"
EQUATION_BINDING_SCHEMA = "anvil-equation-bindings/v6.1"
MAX_ALLOWLISTED_DATA_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_SCOPE_BUNDLE_BYTES = 8 * 1024 * 1024              # 8 MB
MAX_BUNDLE_BYTES = MAX_SCOPE_BUNDLE_BYTES
ALLOWLISTED_DATA_DIR_NAMES: Tuple[str, ...] = ("data", "Data", "datasets", "Datasets")
OPAQUE_MODULE_ID_RE = re.compile(r"^[a-z0-9_-]+$")


def _strip_leading_dot_slash(raw_path: str) -> str:
    """Remove leading './' prefixes without stripping dots from '.venv' or hidden directory names."""
    out = raw_path
    while out.startswith("./"):
        out = out[2:]
    return out


class AnvilRefusalError(Exception):
    """Structured fail-closed security, policy, containment, data, or bound refusal."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        cwe: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.cwe = cwe
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.cwe:
            out["cwe"] = self.cwe
        out.update(self.details)
        return out


# ---------------------------------------------------------------------------
# 1. Canonical Path Containment (CWE-22)
# ---------------------------------------------------------------------------

def _is_link_or_junction(p: Path) -> bool:
    if p.is_symlink():
        return True
    is_junc = getattr(p, "is_junction", None)
    if callable(is_junc):
        try:
            return bool(is_junc())
        except OSError:
            return False
    return False


def resolve_contained_path(
    repo_root: str | Path,
    candidate: str | Path,
    *,
    allow_root: bool = False,
    must_be_relative: bool = False,
) -> Path:
    """Resolve `candidate` strictly inside `repo_root`, rejecting `..` segments,
    unauthorized absolute/rooted paths, and escaping symlinks or NTFS junctions.
    """
    if candidate is None:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty candidate path refused.", cwe="CWE-22")
    raw_str = str(candidate).strip()
    if not raw_str or "\x00" in raw_str:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty or NUL-containing path refused.", cwe="CWE-22")

    root_resolved = Path(repo_root).resolve()
    norm_tokens = raw_str.replace("\\", "/").split("/")
    if ".." in norm_tokens or ".." in Path(raw_str).parts:
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Parent traversal ('..') refused for path '{raw_str}'.",
            cwe="CWE-22",
            details={"candidate": raw_str},
        )

    cand_path = Path(raw_str)
    has_root_prefix = raw_str.startswith(("/", "\\"))
    has_drive_rel = bool(cand_path.drive) and not cand_path.is_absolute()
    if has_drive_rel or (os.name == "nt" and has_root_prefix and not cand_path.is_absolute()):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Unauthorized rooted or drive-relative path '{raw_str}' refused.",
            cwe="CWE-22",
            details={"candidate": raw_str},
        )

    if cand_path.is_absolute():
        if must_be_relative:
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Unauthorized absolute path '{raw_str}' refused; relative repo path required.",
                cwe="CWE-22",
                details={"candidate": raw_str},
            )
        resolved_abs = cand_path.resolve()
        if not resolved_abs.is_relative_to(root_resolved):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Unauthorized absolute path '{raw_str}' escapes repository root.",
                cwe="CWE-22",
                details={"candidate": raw_str},
            )
        rel_parts = cand_path.relative_to(cand_path.anchor).parts
        try:
            sub_parts = cand_path.relative_to(root_resolved).parts
        except ValueError:
            sub_parts = ()
        cur = root_resolved
        for part in sub_parts:
            cur = cur / part
            if _is_link_or_junction(cur) or cur.exists():
                if not cur.resolve().is_relative_to(root_resolved):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink or junction escape refused at '{cur.name}'.",
                        cwe="CWE-22",
                        details={"candidate": raw_str},
                    )
        if not allow_root and resolved_abs == root_resolved:
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                "Candidate resolves to repository root rather than a contained member.",
                cwe="CWE-22",
            )
        _ = rel_parts
        return resolved_abs

    cur = root_resolved
    for part in cand_path.parts:
        if part in ("", "."):
            continue
        cur = cur / part
        if _is_link_or_junction(cur) or cur.exists():
            hop_target = cur.resolve()
            if not hop_target.is_relative_to(root_resolved):
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Symlink or junction '{raw_str}' resolves outside repository root.",
                    cwe="CWE-22",
                    details={"candidate": raw_str},
                )

    final_resolved = (root_resolved / cand_path).resolve()
    if not final_resolved.is_relative_to(root_resolved):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Resolved path '{raw_str}' escapes repository root.",
            cwe="CWE-22",
            details={"candidate": raw_str},
        )
    if not allow_root and final_resolved == root_resolved:
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Candidate resolves to repository root rather than a contained file.",
            cwe="CWE-22",
        )
    return final_resolved


# ---------------------------------------------------------------------------
# 2. Cross-Process Exclusive Lock + Atomic Write (temp + fsync + rename)
# ---------------------------------------------------------------------------

@contextmanager
def exclusive_file_lock(lock_path: str | Path, timeout_sec: float = 15.0) -> Iterator[None]:
    """Acquire a cross-process exclusive advisory lock (`msvcrt.locking` / `fcntl.flock`)."""
    lpath = Path(lock_path)
    lpath.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    deadline = time.monotonic() + max(0.05, float(timeout_sec))
    try:
        if os.fstat(fd).st_size == 0:
            try:
                os.write(fd, b"L")
            except OSError:
                pass
        while True:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AnvilRefusalError(
                        "LOCK_TIMEOUT_REFUSED",
                        f"Timed out acquiring exclusive lock '{lpath.name}' after {timeout_sec}s.",
                    )
                time.sleep(0.005 + (os.getpid() % 7) * 0.001)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def atomic_locked_write_json(
    target_path: str | Path,
    payload: Dict[str, Any],
    *,
    timeout_sec: float = 15.0,
) -> Path:
    """Serialize `payload` as strict RFC 8259 JSON via lock + temp + fsync + os.replace."""
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.with_name(f"{target.name}.lock")
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)

    with exclusive_file_lock(lock_file, timeout_sec=timeout_sec):
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(target.parent),
                prefix=f".{target.name}.tmp.{os.getpid()}.",
                suffix=".json",
                delete=False,
            ) as tf:
                tmp_path = Path(tf.name)
                tf.write(encoded)
                tf.write("\n")
                tf.flush()
                os.fsync(tf.fileno())
            for attempt in range(8):
                try:
                    os.replace(str(tmp_path), str(target))
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(0.005 * (attempt + 1))
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    return target


def _parse_strict_json_bytes(raw: bytes, *, max_bytes: int = 16_777_216) -> Dict[str, Any]:
    if len(raw) > max_bytes:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"JSON payload size ({len(raw)} bytes) exceeds max_bytes={max_bytes}.",
            details={"bound_name": "max_json_bytes", "bound_limit": max_bytes, "observed_value": len(raw)},
        )
    if not raw or raw.startswith((b"\x80", b"PK\x03\x04", b"\x00")):
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            "Malformed or binary/pickle payload rejected fail-closed (data-only JSON required).",
            cwe="CWE-502",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            f"Non-UTF8 binary payload rejected fail-closed: {exc}",
            cwe="CWE-502",
        ) from exc

    def _reject_nonfinite(constant: str) -> Any:
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            f"Non-standard JSON constant '{constant}' rejected fail-closed.",
            cwe="CWE-502",
        )

    try:
        parsed = json.loads(text, parse_constant=_reject_nonfinite)
    except AnvilRefusalError:
        raise
    except Exception as exc:
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            f"Invalid JSON payload rejected fail-closed: {exc}",
            cwe="CWE-502",
        ) from exc

    if not isinstance(parsed, dict):
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            "JSON root must be an object dictionary.",
            cwe="CWE-502",
        )
    return parsed


def atomic_locked_read_json(
    target_path: str | Path,
    *,
    timeout_sec: float = 15.0,
    max_bytes: int = 16_777_216,
) -> Dict[str, Any]:
    """Read and validate a JSON dictionary under the same cross-process file lock."""
    target = Path(target_path).resolve()
    lock_file = target.with_name(f"{target.name}.lock")
    with exclusive_file_lock(lock_file, timeout_sec=timeout_sec):
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise AnvilRefusalError(
                "BACKING_STORE_UNREADABLE",
                f"Session/trace store unreadable: {exc}",
            ) from exc
    return _parse_strict_json_bytes(raw, max_bytes=max_bytes)


def load_validated_trace_json(trace_path: str | Path, *, max_bytes: int = 16_777_216) -> Dict[str, Any]:
    """Load and schema-validate a runtime trace JSON file (rejecting pickle/corrupt data)."""
    p = Path(trace_path)
    if not p.is_file():
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            f"Trace file does not exist: {p.name}",
            cwe="CWE-502",
        )
    data = atomic_locked_read_json(p, max_bytes=max_bytes)
    if data.get("schema") != TRACE_SCHEMA or not isinstance(data.get("executed_lines"), list):
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            "Trace JSON failed schema validation (expected schema 'anvil-v4-trace/v1').",
            cwe="CWE-502",
        )
    return data


# ---------------------------------------------------------------------------
# 3. Paper-Anchored Replication Scope & Multi-Pipeline Discovery
# ---------------------------------------------------------------------------

def _parse_python_ast_quiet(text: str, filename: str) -> Optional[ast.Module]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.parse(text, filename=filename)
        except SyntaxError:
            return None


def _has_paper_or_workflow_anchor(repo_root: Path) -> bool:
    """Fast O(1) directory check so non-scientific JS/Python repos skip redundant scope walks."""
    if not repo_root.is_dir():
        return False
    probe_dirs = [
        repo_root,
        repo_root / "Code",
        repo_root / "scripts",
        repo_root / "replication",
        repo_root / "Manuscript",
        repo_root / "manuscript",
        repo_root / "paper",
        repo_root / "Paper",
        repo_root / "docs",
    ]
    for d in probe_dirs:
        if not d.is_dir() or _is_link_or_junction(d):
            continue
        try:
            for entry in os.scandir(d):
                nm = entry.name
                if nm in WORKFLOW_MANIFEST_NAMES or nm.lower().endswith(".tex"):
                    return True
        except OSError:
            continue
    return False

def _is_historical_clutter_path(rel_posix: str) -> bool:
    parts = [p.lower() for p in Path(rel_posix).parts]
    if any(p in ARCHIVE_OR_STAGING_DIRS for p in parts[:-1]):
        return True
    stem = Path(rel_posix).stem.lower()
    tokens = set(re.findall(r"[a-z0-9]+", "/".join(parts)))
    if tokens & set(HISTORICAL_CLUTTER_TOKENS):
        return True
    if re.search(r"(?:^|_)(?:v0|v1|try\d*|exp_old|archive|bak)(?:_|$)", stem):
        return True
    return False


def _strip_tex_comment_line(line: str) -> str:
    return re.sub(r"(?<!\\)((?:\\\\)*)%.*$", r"\1", line)


_LATEX_UNWRAP_COMMANDS: Set[str] = {
    "textbf", "textit", "emph", "textrm", "texttt", "textsc", "textsf", "text", "mbox",
    "mathrm", "mathbf", "mathcal", "mathsf", "mathtt", "boldsymbol", "bm", "underline",
    "hl", "uline", "num",
}
_LATEX_DROP_COMMANDS: Set[str] = {
    "label", "cite", "citep", "citet", "citealt", "ref", "eqref", "pageref", "footnote", "sym",
}


def _extract_balanced_brace_group(text: str, open_brace_idx: int) -> Tuple[str, int]:
    """Linear O(N) balanced-brace extractor (zero regex backtracking).
    Returns `(inner_content, index_after_closing_brace)`; if unclosed, returns `("", -1)`.
    """
    n = len(text)
    if open_brace_idx < 0 or open_brace_idx >= n or text[open_brace_idx] != "{":
        return "", -1
    depth = 1
    i = open_brace_idx + 1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : i], i + 1
        i += 1
    return "", -1


def _build_brace_match_map(text: str) -> Dict[int, int]:
    """Single-pass O(N) stack map from `open_brace_idx` -> `index_after_closing_brace`."""
    stack: List[int] = []
    matches: Dict[int, int] = {}
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            open_idx = stack.pop()
            matches[open_idx] = i + 1
        i += 1
    return matches


def strip_latex_nested_braces(text: str, *, max_depth: int = 2) -> str:
    """Linear-time O(N) LaTeX brace & formatting stripper supporting >=2 levels of nested braces
    and `{,}` thousands separators (e.g. `50{,}002` -> `50002`, `\\textbf{50{,}002}` -> `50002`)
    with zero regex catastrophic backtracking and O(N) stack matching on unclosed braces.
    """
    if not text:
        return ""
    s = re.sub(r"(?<=\d)\{,\}(?=\d)", "", text)
    passes = max(1, int(max_depth)) + 1
    for _ in range(passes):
        matches = _build_brace_match_map(s)
        out_chars: List[str] = []
        prev_non_ws = ""

        def _append_seg(seg: str) -> None:
            nonlocal prev_non_ws
            if not seg:
                return
            out_chars.append(seg)
            st_seg = seg.rstrip()
            if st_seg:
                prev_non_ws = st_seg[-1]

        i = 0
        n = len(s)
        changed = False
        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n and s[i + 1].isalpha():
                j = i + 1
                while j < n and s[j].isalpha():
                    j += 1
                cmd = s[i + 1 : j]
                k = j
                while k < n and s[k] in (" ", "\t"):
                    k += 1
                if k < n and s[k] == "*":
                    k += 1
                    while k < n and s[k] in (" ", "\t"):
                        k += 1
                if k < n and s[k] == "{":
                    if cmd == "multicolumn":
                        next_k1 = matches.get(k, -1)
                        if next_k1 > 0:
                            while next_k1 < n and s[next_k1] in (" ", "\t"):
                                next_k1 += 1
                            if next_k1 < n and s[next_k1] == "{":
                                next_k2 = matches.get(next_k1, -1)
                                if next_k2 > 0:
                                    while next_k2 < n and s[next_k2] in (" ", "\t"):
                                        next_k2 += 1
                                    if next_k2 < n and s[next_k2] == "{":
                                        end_mc = matches.get(next_k2, -1)
                                        if end_mc > 0:
                                            _append_seg(s[next_k2 + 1 : end_mc - 1])
                                            i = end_mc
                                            changed = True
                                            continue
                    elif cmd == "textcolor":
                        next_tc = matches.get(k, -1)
                        if next_tc > 0:
                            while next_tc < n and s[next_tc] in (" ", "\t"):
                                next_tc += 1
                            if next_tc < n and s[next_tc] == "{":
                                end_tc = matches.get(next_tc, -1)
                                if end_tc > 0:
                                    _append_seg(s[next_tc + 1 : end_tc - 1])
                                    i = end_tc
                                    changed = True
                                    continue
                    elif cmd in _LATEX_UNWRAP_COMMANDS:
                        end_idx = matches.get(k, -1)
                        if end_idx > 0:
                            _append_seg(s[k + 1 : end_idx - 1])
                            i = end_idx
                            changed = True
                            continue
                    elif cmd in _LATEX_DROP_COMMANDS:
                        end_idx = matches.get(k, -1)
                        if end_idx > 0:
                            i = end_idx
                            changed = True
                            continue
                _append_seg(s[i:j])
                i = j
                continue
            if ch == "{":
                if prev_non_ws not in ("\\", "^", "_"):
                    end_b = matches.get(i, -1)
                    if end_b > 0:
                        inner_b = s[i + 1 : end_b - 1]
                        if inner_b == ",":
                            _append_seg(",")
                        else:
                            _append_seg(inner_b)
                        i = end_b
                        changed = True
                        continue
            _append_seg(ch)
            i += 1
        s_next = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", "".join(out_chars)) if "{,}" in text else "".join(out_chars)
        s_next = re.sub(r"(?<=\d)\{,\}(?=\d)", "", s_next)
        s = s_next
        if not changed:
            break
    s = s.replace("\\_", "_").replace("\\,", " ").replace("~", " ")
    return re.sub(r"\s+", " ", s).strip()


_strip_latex_nested_braces = strip_latex_nested_braces


def extract_latex_table_numeric_cells(tex_text: str) -> List[str]:
    """Extract normalized numeric cells from LaTeX table rows (handling `50{,}002` and
    nested formatting such as `\\textbf{50{,}002}` or `\\emph{\\textbf{50{,}002}}` -> `'50002'`).
    """
    if not tex_text:
        return []
    found: List[str] = []
    seen: Set[str] = set()
    for raw_ln in tex_text.splitlines():
        clean_ln = _strip_tex_comment_line(raw_ln).strip()
        if not clean_ln or clean_ln.startswith(("\\toprule", "\\midrule", "\\bottomrule", "\\hline", "\\cline", "\\cmidrule")):
            continue
        row_body = re.sub(r"\\\\(?:\s*\[[^\]]*\])?\s*$", "", clean_ln)
        cells = row_body.split("&") if "&" in row_body else [row_body]
        for raw_cell in cells:
            c = strip_latex_nested_braces(raw_cell, max_depth=2)
            c = c.replace("$", "").strip()
            c = re.sub(r"\^\{?\*+\}?|\*+$", "", c).strip()
            if c.startswith("(") and c.endswith(")"):
                c = c[1:-1].strip()
            if "{,}" not in raw_cell:
                c = re.sub(r"(?<=\d),(?=\d{3}\b)", "", c)
            for m_num in re.finditer(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_])", c):
                tok = m_num.group(0).lstrip("+")
                if tok not in seen:
                    seen.add(tok)
                    found.append(tok)
    return found


def resolve_manuscript_path(
    repo_root: str | Path,
    paper_path: str | Path,
    *,
    allowed_root: Optional[str | Path] = None,
) -> Path:
    """Resolve `paper_path` inside `repo_root` OR a sibling manuscript folder inside the
    permitted workspace boundary (`allowed_root` if provided, else `repo_root.parent`),
    while rejecting `..` traversal outside the permitted boundary and rejecting symlinks/junctions.
    """
    if paper_path is None:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty manuscript path refused.", cwe="CWE-22", details={"http_status": 403})
    raw_str = str(paper_path).strip()
    if not raw_str or "\x00" in raw_str:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty or NUL-containing manuscript path refused.", cwe="CWE-22", details={"http_status": 403})

    repo_resolved = Path(repo_root).resolve()
    if _is_link_or_junction(Path(repo_root)):
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Symlink or junction repository root refused.", cwe="CWE-22", details={"http_status": 403})

    cand_obj = Path(raw_str)
    has_dotdot = ".." in cand_obj.parts
    if allowed_root is not None and str(allowed_root).strip():
        boundary_raw = Path(allowed_root)
        if _is_link_or_junction(boundary_raw):
            raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Symlink or junction allowed_root refused.", cwe="CWE-22", details={"http_status": 403})
        boundary = boundary_raw.resolve()
    elif cand_obj.is_absolute() and not has_dotdot and repo_resolved.parent != repo_resolved:
        # Trusted local sibling/sources manuscript path within at most 2 parent levels (cockpit/sources/<repo>)
        boundary = repo_resolved.parent
        probe_norm = Path(os.path.normpath(str(cand_obj)))
        for anc in (repo_resolved, *list(repo_resolved.parents)[:2]):
            if anc.parent == anc:
                break
            if probe_norm == anc or probe_norm.is_relative_to(anc):
                boundary = anc
                break
    else:
        # Default fail-closed boundary for relative paths (refuses '../x' unless allowed_root is explicit)
        boundary = repo_resolved
    has_root_prefix = raw_str.startswith(("/", "\\"))
    has_drive_rel = bool(cand_obj.drive) and not cand_obj.is_absolute()
    if has_drive_rel or (os.name == "nt" and has_root_prefix and not cand_obj.is_absolute()):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Unauthorized rooted or drive-relative manuscript path '{raw_str}' refused.",
            cwe="CWE-22",
            details={"candidate": raw_str, "http_status": 403},
        )

    unnorm_target = cand_obj if cand_obj.is_absolute() else (repo_resolved / cand_obj)
    # Check lexical normalization BEFORE symlink resolution so `../../outside` or symlink hops fail closed
    norm_lexical = Path(os.path.normpath(str(unnorm_target)))
    if not (norm_lexical == boundary or norm_lexical.is_relative_to(boundary)):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Manuscript path '{raw_str}' escapes permitted workspace boundary '{boundary.name}'.",
            cwe="CWE-22",
            details={"candidate": raw_str, "http_status": 403},
        )

    rel_from_boundary = norm_lexical.relative_to(boundary)
    cur = boundary
    for part in rel_from_boundary.parts:
        cur = cur / part
        if _is_link_or_junction(cur):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Symlink or junction manuscript component '{part}' refused.",
                cwe="CWE-22",
                details={"candidate": raw_str, "http_status": 403},
            )
        if cur.exists() and not cur.resolve().is_relative_to(boundary):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Manuscript component '{part}' resolves outside permitted workspace boundary.",
                cwe="CWE-22",
                details={"candidate": raw_str, "http_status": 403},
            )

    resolved_final = norm_lexical.resolve()
    if not (resolved_final == boundary or resolved_final.is_relative_to(boundary)):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Resolved manuscript path '{raw_str}' escapes permitted workspace boundary.",
            cwe="CWE-22",
            details={"candidate": raw_str, "http_status": 403},
        )
    return resolved_final


def _pick_main_tex_file(search_dir: Path) -> Optional[Path]:
    if not search_dir.is_dir():
        return None
    tex_files: List[Path] = []
    for cur_root, dirs, files in os.walk(search_dir, followlinks=False):
        dirs[:] = [
            d for d in sorted(dirs)
            if d not in SKIP_SCAN_DIRS and not d.startswith(".") and not d.startswith("_")
        ]
        for f in sorted(files):
            if f.lower().endswith(".tex"):
                fp = Path(cur_root) / f
                if not _is_link_or_junction(fp):
                    tex_files.append(fp)
    if not tex_files:
        return None
    non_archive_tex = [
        tf for tf in tex_files
        if not any(pt.lower() in ARCHIVE_OR_STAGING_DIRS for pt in tf.relative_to(search_dir).parts[:-1])
    ]
    active_tex_pool = non_archive_tex if non_archive_tex else tex_files
    scored: List[Tuple[int, int, Path]] = []
    for tf in active_tex_pool:
        try:
            txt = tf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sc = 0
        if "\\documentclass" in txt:
            sc += 50
        if "\\begin{document}" in txt:
            sc += 40
        if tf.stem.lower() in ("main", "paper", "ms", "manuscript", "article"):
            sc += 20
        if tf.parent == search_dir:
            sc += 10
        scored.append((sc, len(txt), tf))
    if not scored:
        return active_tex_pool[0]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def _extract_pdf_text_for_scope(pdf_path: Path) -> str:
    for mod_name in ("pypdf", "fitz"):
        try:
            mod = importlib.import_module(mod_name)
            if mod_name == "pypdf":
                reader = mod.PdfReader(str(pdf_path))
                txt = "\n".join((pg.extract_text() or "") for pg in reader.pages[:35])
            else:
                doc = mod.open(str(pdf_path))
                txt = "\n".join(doc[i].get_text("text") for i in range(min(35, len(doc))))
            if txt.strip():
                return txt
        except Exception:
            continue
    return ""


def _scan_manuscript_artifacts(paper_target: Optional[Path]) -> List[Dict[str, Any]]:
    """Inspect `.tex` tree (including `\\input{...}`), `.md`, or `.pdf` for referenced
    tables (`\\input{Tables/...}`, `\\label{tab:...}`), figures (`\\includegraphics{...}`),
    and section context.
    """
    if paper_target is None or not paper_target.exists():
        return []

    entry_file: Optional[Path] = None
    paper_root: Path
    if paper_target.is_dir():
        paper_root = paper_target.resolve()
        entry_file = _pick_main_tex_file(paper_root)
        if entry_file is None:
            entry_file = next(
                (
                    p for p in sorted(paper_root.rglob("*"))
                    if p.is_file() and not _is_link_or_junction(p) and p.suffix.lower() in (".md", ".pdf")
                ),
                None,
            )
    else:
        entry_file = paper_target.resolve()
        paper_root = entry_file.parent.resolve()

    if entry_file is None or not entry_file.is_file():
        return []

    artifacts: List[Dict[str, Any]] = []
    visited_tex: Set[Path] = set()

    inc_re = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
    gfx_re = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
    lbl_re = re.compile(r"\\label\s*\{((?:tab|fig|tbl|table|figure)[:_][^{}]+)\}", flags=re.I)
    sec_cmd_re = re.compile(r"\\(section|subsection|appendix)\*?\s*(\{)?")
    cap_cmd_re = re.compile(r"\\caption\*?\s*(?:\[[^\]]*\])?\s*\{")
    env_open_re = re.compile(r"\\begin\{(table\*?|figure\*?)\}", flags=re.I)
    env_close_re = re.compile(r"\\end\{(table\*?|figure\*?)\}", flags=re.I)

    def _resolve_tex_child(cur_dir: Path, raw_ref: str) -> Optional[Path]:
        clean = raw_ref.strip().strip('"').strip("'").replace("\\", "/")
        if not clean or clean.startswith("/") or ":" in clean or ".." in clean.split("/"):
            return None
        for base in (cur_dir, paper_root):
            for suf in ("", ".tex"):
                cand = (base / f"{clean}{suf}").resolve()
                if cand.is_file() and not _is_link_or_junction(cand) and cand.is_relative_to(paper_root):
                    return cand
        return None

    def _walk_tex(tf: Path, cur_section: str) -> str:
        real_tf = tf.resolve()
        if real_tf in visited_tex or not real_tf.is_file():
            return cur_section
        visited_tex.add(real_tf)
        try:
            lines = real_tf.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return cur_section

        active_sec = cur_section
        in_float_env = False
        cur_caption = ""
        cur_env_lines: List[str] = []
        pending_env_labels: List[Dict[str, Any]] = []

        for ln in lines:
            clean_ln = _strip_tex_comment_line(ln)
            if env_open_re.search(clean_ln):
                in_float_env = True
                cur_caption = ""
                cur_env_lines = [clean_ln]
                pending_env_labels = []
            elif in_float_env:
                cur_env_lines.append(clean_ln)

            for sm in sec_cmd_re.finditer(clean_ln):
                kind_kw = sm.group(1).lower()
                sec_title = ""
                if sm.group(2) == "{":
                    raw_sec, _ = _extract_balanced_brace_group(clean_ln, sm.end() - 1)
                    sec_title = strip_latex_nested_braces(raw_sec, max_depth=2)
                if kind_kw == "appendix" and not sec_title:
                    active_sec = "Appendix"
                elif sec_title:
                    active_sec = f"Appendix: {sec_title}" if "appendix" in active_sec.lower() and kind_kw != "section" else sec_title

            for cm_cap in cap_cmd_re.finditer(clean_ln):
                raw_cap, _ = _extract_balanced_brace_group(clean_ln, cm_cap.end() - 1)
                if raw_cap:
                    cur_caption = strip_latex_nested_braces(raw_cap, max_depth=2)
                    for pend in pending_env_labels:
                        if not pend.get("caption"):
                            pend["caption"] = cur_caption

            for gm in gfx_re.finditer(clean_ln):
                fig_ref = gm.group(1).strip().replace("\\", "/")
                if fig_ref:
                    artifacts.append({
                        "kind": "figure",
                        "ref": fig_ref,
                        "stem": Path(fig_ref).stem.lower(),
                        "section": active_sec,
                        "caption": cur_caption if in_float_env else "",
                        "numeric_cells": [],
                    })

            for lm in lbl_re.finditer(clean_ln):
                lbl_val = lm.group(1).strip()
                lbl_art: Dict[str, Any] = {
                    "kind": "table_label" if lbl_val.lower().startswith(("tab", "tbl")) else "figure_label",
                    "ref": lbl_val,
                    "stem": re.sub(r"^(?:tab|tbl|fig|table|figure)[:_]", "", lbl_val.lower()),
                    "section": active_sec,
                    "caption": cur_caption if in_float_env else "",
                    "numeric_cells": [],
                }
                artifacts.append(lbl_art)
                if in_float_env:
                    pending_env_labels.append(lbl_art)

            for im in inc_re.finditer(clean_ln):
                inc_ref = im.group(1).strip().replace("\\", "/")
                inc_low = inc_ref.lower()
                child_p = _resolve_tex_child(real_tf.parent, inc_ref)
                is_table_or_fig_path = any(
                    tok in inc_low
                    for tok in ("table", "tables/", "tab_", "tab/", "fig", "figures/", "output/", "results/")
                )
                child_has_tabular = False
                child_nums: List[str] = []
                if child_p is not None and child_p.is_file():
                    try:
                        child_full_txt = child_p.read_text(encoding="utf-8", errors="replace")
                        head_txt = child_full_txt[:3000]
                        child_has_tabular = ("\\begin{tabular" in head_txt) or ("\\toprule" in head_txt)
                        if child_has_tabular or is_table_or_fig_path:
                            child_nums = extract_latex_table_numeric_cells(child_full_txt)
                    except Exception:
                        child_has_tabular = False
                if is_table_or_fig_path or child_has_tabular:
                    artifacts.append({
                        "kind": "table",
                        "ref": inc_ref if inc_ref.endswith(".tex") else f"{inc_ref}.tex",
                        "stem": Path(inc_ref).stem.lower(),
                        "section": active_sec,
                        "caption": cur_caption if in_float_env else "",
                        "numeric_cells": child_nums,
                    })
                if child_p is not None:
                    active_sec = _walk_tex(child_p, active_sec)

            if in_float_env and env_close_re.search(clean_ln):
                env_nums = extract_latex_table_numeric_cells("\n".join(cur_env_lines))
                for pend in pending_env_labels:
                    if cur_caption and not pend.get("caption"):
                        pend["caption"] = cur_caption
                    if env_nums and not pend.get("numeric_cells"):
                        pend["numeric_cells"] = list(env_nums)
                in_float_env = False
                cur_caption = ""
                cur_env_lines = []
                pending_env_labels = []
        return active_sec

    ext = entry_file.suffix.lower()
    if ext == ".tex":
        _walk_tex(entry_file, "Main")
    else:
        raw_text = (
            _extract_pdf_text_for_scope(entry_file)
            if ext == ".pdf"
            else entry_file.read_text(encoding="utf-8", errors="replace")
        )
        cur_sec = "Main"
        md_sec_re = re.compile(r"^(#{1,3}|Section\s+\d+[:.]?)\s*(.+)$", flags=re.I)
        md_art_re = re.compile(
            r"\b((?:Tables?|Figures?|Output|Results)/[A-Za-z0-9_./-]+\.(?:tex|csv|pdf|png|svg|json))\b",
            flags=re.I,
        )
        for ln in raw_text.splitlines():
            s_ln = ln.strip()
            ms = md_sec_re.match(s_ln)
            if ms:
                cur_sec = ms.group(2).strip()
            for ma in md_art_re.finditer(s_ln):
                aref = ma.group(1).replace("\\", "/")
                artifacts.append({
                    "kind": "figure" if aref.lower().endswith((".pdf", ".png", ".svg")) else "table",
                    "ref": aref,
                    "stem": Path(aref).stem.lower(),
                    "section": cur_sec,
                })
            for lm in lbl_re.finditer(s_ln):
                lbl_val = lm.group(1).strip()
                artifacts.append({
                    "kind": "table_label" if lbl_val.lower().startswith(("tab", "tbl")) else "figure_label",
                    "ref": lbl_val,
                    "stem": re.sub(r"^(?:tab|tbl|fig|table|figure)[:_]", "", lbl_val.lower()),
                    "section": cur_sec,
                })

    dedup: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str]] = set()
    for art in artifacts:
        key = (art["kind"], art["ref"])
        if key not in seen_keys:
            seen_keys.add(key)
            dedup.append(art)
    return dedup


def _build_repo_import_graph(repo_root: Path, prod_files: Sequence[Path]) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Build deterministic intra-repository import adjacency list `adj[rel_file] -> [imported_rel_files]`
    plus raw source cache `source_by_rel[rel_file]`.
    """
    known_rels: Set[str] = set()
    stem_to_rels: Dict[str, List[str]] = {}
    source_by_rel: Dict[str, str] = {}
    top_code_roots: Set[str] = set()

    for fp in prod_files:
        rel = fp.relative_to(repo_root).as_posix()
        known_rels.add(rel)
        stem_to_rels.setdefault(fp.stem, []).append(rel)
        parts = Path(rel).parts
        if len(parts) > 1 and parts[0].lower() in ("code", "src", "python", "r", "scripts", "lib"):
            top_code_roots.add(parts[0])
        try:
            source_by_rel[rel] = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_by_rel[rel] = ""

    def _resolve_py_spec(mod_spec: str, level: int, importer_rel: str) -> List[str]:
        hits: List[str] = []
        imp_dir = Path(importer_rel).parent
        clean_spec = (mod_spec or "").strip(".")
        rel_sub = clean_spec.replace(".", "/") if clean_spec else ""

        search_bases: List[Path] = []
        if level >= 1:
            anc = imp_dir
            for _ in range(max(0, level - 1)):
                anc = anc.parent
            search_bases.append(anc)
        else:
            # 1. Repo root, 2. Importer's directory & ancestors up to repo root, 3. Common Code/src roots
            search_bases.append(Path("."))
            cur_anc = imp_dir
            while str(cur_anc) not in ("", "."):
                if cur_anc not in search_bases:
                    search_bases.append(cur_anc)
                cur_anc = cur_anc.parent
            for cr in sorted(top_code_roots):
                cp = Path(cr)
                if cp not in search_bases:
                    search_bases.append(cp)

        for base in search_bases:
            prefix = _strip_leading_dot_slash((base / rel_sub).as_posix()) if rel_sub else _strip_leading_dot_slash(base.as_posix())
            if not prefix or prefix == ".":
                continue
            for cand in (f"{prefix}.py", f"{prefix}/__init__.py"):
                if cand in known_rels and cand != importer_rel and cand not in hits:
                    hits.append(cand)

        if not hits and level == 0 and clean_spec and "." not in clean_spec:
            cands = [r for r in stem_to_rels.get(clean_spec, []) if r != importer_rel and not _is_historical_clutter_path(r)]
            if len(cands) == 1:
                hits.append(cands[0])
        return hits

    adj: Dict[str, List[str]] = {rel: [] for rel in sorted(known_rels)}
    for rel, text in source_by_rel.items():
        ext = Path(rel).suffix.lower()
        targets: List[str] = []
        if ext == ".py":
            tree = _parse_python_ast_quiet(text, filename=rel)
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            targets.extend(_resolve_py_spec(alias.name, 0, rel))
                    elif isinstance(node, ast.ImportFrom):
                        lvl = int(node.level or 0)
                        base_mod = node.module or ""
                        targets.extend(_resolve_py_spec(base_mod, lvl, rel))
                        for alias in node.names:
                            if alias.name and alias.name != "*":
                                sub_spec = f"{base_mod}.{alias.name}" if base_mod else alias.name
                                targets.extend(_resolve_py_spec(sub_spec, lvl, rel))
                    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                        s_lit = node.value.strip()
                        if 4 <= len(s_lit) <= 240:
                            if re.fullmatch(r"[A-Za-z0-9_./\\-]+\.(?:py|R|r)", s_lit):
                                norm_s = _strip_leading_dot_slash(s_lit.replace("\\", "/"))
                                cands_s = [norm_s, _strip_leading_dot_slash((Path(rel).parent / norm_s).as_posix())]
                                for cr in sorted(top_code_roots):
                                    cands_s.append(f"{cr}/{norm_s}")
                                    for kn_rel in known_rels:
                                        if kn_rel.startswith(f"{cr}/") and kn_rel.endswith(f"/{norm_s}") and not _is_historical_clutter_path(kn_rel):
                                            cands_s.append(kn_rel)
                                matched_s = [c for c in cands_s if c in known_rels and c != rel]
                                if matched_s:
                                    targets.extend(matched_s)
                                elif "/" not in norm_s:
                                    stem_hits = [
                                        r for r in stem_to_rels.get(Path(norm_s).stem, [])
                                        if r != rel and not _is_historical_clutter_path(r)
                                    ]
                                    if len(stem_hits) == 1:
                                        targets.append(stem_hits[0])
                            elif "import " in s_lit:
                                for m_in in re.finditer(r"(?:\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\b|\bimport\s+([A-Za-z_][A-Za-z0-9_.]*))", s_lit):
                                    mod_in = m_in.group(1) or m_in.group(2) or ""
                                    if mod_in:
                                        targets.extend(_resolve_py_spec(mod_in, 0, rel))
                    elif isinstance(node, ast.Call):
                        fn_im = node.func
                        is_imp_mod = (
                            (isinstance(fn_im, ast.Attribute) and fn_im.attr == "import_module")
                            or (isinstance(fn_im, ast.Name) and fn_im.id == "import_module")
                        )
                        if is_imp_mod and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            targets.extend(_resolve_py_spec(node.args[0].value.strip(), 0, rel))
        elif ext == ".r":
            for m in re.finditer(r"""\bsource\(\s*['"]([^'"]+)['"]""", text):
                raw_r = _strip_leading_dot_slash(m.group(1).strip().replace("\\", "/"))
                for cand in (raw_r, _strip_leading_dot_slash((Path(rel).parent / raw_r).as_posix())):
                    if cand in known_rels and cand != rel:
                        targets.append(cand)
        elif ext in (".js", ".mjs", ".ts"):
            for m in re.finditer(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", text):
                spec = m.group(1).strip()
                if spec.startswith("."):
                    norm = _strip_leading_dot_slash(os.path.normpath(str(Path(rel).parent / spec)).replace("\\", "/"))
                    for suf in ("", ".js", ".mjs", ".ts", "/index.js", "/index.mjs", "/index.ts"):
                        cand = f"{norm}{suf}"
                        if cand in known_rels and cand != rel:
                            targets.append(cand)
        adj[rel] = list(dict.fromkeys(targets))

    return adj, source_by_rel


def _compute_import_closure(entrypoints: Sequence[str], adj: Dict[str, List[str]]) -> List[str]:
    visited: Set[str] = set()
    queue: List[str] = [ep for ep in entrypoints if ep in adj]
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        for nxt in adj.get(cur, []):
            if nxt not in visited:
                queue.append(nxt)
    return sorted(visited)


def _classify_pipeline_bucket(
    entry_rel: str,
    context_hint: str,
    matched_targets: Sequence[str],
    matched_sections: Sequence[str],
) -> Tuple[str, str]:
    """Map a discovered replication entrypoint onto a coherent named pipeline `(id, title)`."""
    stem_low = Path(entry_rel).stem.lower()
    targets_low = " ".join(matched_targets).lower()
    sections_low = " ".join(matched_sections).lower()
    hint_low = context_hint.lower()

    primary_blob = re.sub(r"[^a-z0-9]+", " ", f"{stem_low} {targets_low} {hint_low}")
    full_blob = re.sub(r"[^a-z0-9]+", " ", f"{primary_blob} {sections_low}")
    stem_words = re.sub(r"[^a-z0-9]+", " ", stem_low)

    if stem_low.startswith(("check_", "verify_", "audit_", "run_verification", "validate_")):
        return ("verification_checks", "Robustness & Verification Checks")

    sim_re = re.compile(r"\b(?:sim|sims|simul|simulations?|monte|montecarlo|dgp|synthetic|recovery)\b")
    pol_re = re.compile(r"\b(?:policy|policies|target|targeting|uplift|counterfactuals?|welfare|aipw|cate|treatment)\b")
    ver_re = re.compile(r"\b(?:verif|verify|verification|robust|robustness|placebo|diag|diagnostics?|audit|sensitiv|identif)\b")
    pred_re = re.compile(
        r"\b(?:pred|predict|predictive|oos|cv|kfold|fit|table1|table2|tab1|tab2|tables|benchmark)\b"
    )
    prep_re = re.compile(r"\b(?:prepare data|data prepare|prep data|ingest raw)\b")

    if prep_re.search(primary_blob) and not (pred_re.search(stem_words) or pol_re.search(stem_words) or sim_re.search(stem_words)):
        return ("data_preparation", "Data Preparation & Respondent Covariates")
    if sim_re.search(primary_blob) or (not pol_re.search(primary_blob) and not pred_re.search(primary_blob) and sim_re.search(full_blob)):
        return ("simulations", "Monte Carlo Simulations & Recovery Figures")
    if pol_re.search(primary_blob) or (not pred_re.search(primary_blob) and pol_re.search(full_blob)):
        return ("policy_targeting", "Policy Targeting & Counterfactual Evaluation")
    if ver_re.search(primary_blob):
        return ("verification_checks", "Robustness & Verification Checks")
    if pred_re.search(primary_blob) or pred_re.search(full_blob):
        return ("predictive_tables", "Predictive & Model Fit Tables")

    clean_slug = re.sub(r"^(?:run_|make_|build_|gen_|script_)", "", stem_low)
    clean_slug = re.sub(r"[^a-z0-9]+", "_", clean_slug).strip("_") or "main_replication"
    pretty = clean_slug.replace("_", " ").title()
    return (clean_slug, f"{pretty} Replication Pipeline")


def _collect_manifest_search_bases(
    repo_root: Path,
    paper_path: Optional[Path] = None,
    *,
    allowed_root: Optional[Path] = None,
) -> List[Path]:
    """Collect candidate manifest directories at `repo_root`, upward from `paper_path` to `repo_root`,
    and in contained sibling manuscript folders when `paper_path` lives outside `repo_root`.
    """
    bases: List[Path] = []
    seen_b: Set[Path] = set()
    eff_boundary = (
        allowed_root.resolve()
        if allowed_root is not None
        else (repo_root if repo_root.parent == Path(repo_root.anchor) else repo_root.parent.resolve())
    )

    def _push_root(cand: Path, *, allow_sibling: bool = False) -> None:
        for sub in (cand, cand / "Code", cand / "scripts", cand / "replication"):
            if sub.is_dir() and not _is_link_or_junction(sub):
                res_s = sub.resolve()
                in_repo = res_s == repo_root or repo_root in res_s.parents
                in_sib = allow_sibling and (res_s == eff_boundary or eff_boundary in res_s.parents)
                if res_s not in seen_b and (in_repo or in_sib):
                    seen_b.add(res_s)
                    bases.append(res_s)

    if paper_path is not None and paper_path.exists() and not _is_link_or_junction(paper_path):
        cur_p = (paper_path if paper_path.is_dir() else paper_path.parent).resolve()
        if cur_p == repo_root or repo_root in cur_p.parents:
            while cur_p == repo_root or repo_root in cur_p.parents:
                if not any(pt.lower() in ARCHIVE_OR_STAGING_DIRS for pt in cur_p.relative_to(repo_root).parts):
                    _push_root(cur_p)
                if cur_p == repo_root:
                    break
                cur_p = cur_p.parent
        elif cur_p == eff_boundary or eff_boundary in cur_p.parents:
            _push_root(cur_p, allow_sibling=True)
            if cur_p.parent != eff_boundary and eff_boundary in cur_p.parent.parents:
                _push_root(cur_p.parent, allow_sibling=True)

    _push_root(repo_root)
    return bases


def _parse_workflow_manifests(
    repo_root: Path,
    known_rels: Set[str],
    stem_to_rels: Dict[str, List[str]],
    *,
    paper_path: Optional[Path] = None,
    allowed_root: Optional[Path] = None,
) -> Tuple[List[str], List[Dict[str, Any]], bool]:
    """Inspect executable manifests (`workflow.sh`, `Makefile`, `Snakefile`) first, falling back to
    `REPLICATION.md` / `README*.md` only when no executable manifest yields entrypoints.
    Searches both `repo_root` and the manuscript's nearest project root (`paper_path`).
    Supports shell variables (`C="$OUT/Code"`, `$PY`), step wrappers (`step <name> "$PY" ...`),
    and heredoc skipping.
    """
    exec_names = ("workflow.sh", "run_all.sh", "replicate.sh", "replication.sh", "pipeline.sh", "run.sh", "Makefile", "makefile", "GNUmakefile", "Snakefile")
    doc_names = ("REPLICATION.md", "replication.md")

    exec_manifests: List[Path] = []
    doc_manifests: List[Path] = []
    seen_m: Set[Path] = set()
    search_bases = _collect_manifest_search_bases(repo_root, paper_path, allowed_root=allowed_root)

    for name in exec_names:
        for base in search_bases:
            p = base / name
            if p.is_file() and not _is_link_or_junction(p) and p.resolve() not in seen_m:
                seen_m.add(p.resolve())
                exec_manifests.append(p)

    for name in doc_names:
        for base in search_bases:
            p = base / name
            if p.is_file() and not _is_link_or_junction(p) and p.resolve() not in seen_m:
                seen_m.add(p.resolve())
                doc_manifests.append(p)

    for base in search_bases:
        if base in (repo_root,) or (paper_path is not None and base == (paper_path if paper_path.is_dir() else paper_path.parent.parent)):
            for readme_p in sorted(base.glob("README*.md")):
                if readme_p.is_file() and not _is_link_or_junction(readme_p) and readme_p.resolve() not in seen_m:
                    seen_m.add(readme_p.resolve())
                    doc_manifests.append(readme_p)

    py_cmd_re = re.compile(
        r"""(?:^|[;&|]\s*|\$\(\s*|\s)(?:['"]?\$\{?(?:PY|PYTHON(?:3)?)(?:[:][^}]*)?\}?['"]?|python3?|uv\s+run\s+python3?)\s+(?:-[uO]\s+)*(-m\s+)?['"]?([A-Za-z0-9_./\\${}-]+)['"]?(.*)$"""
    )
    r_cmd_re = re.compile(
        r"""(?:^|[;&|]\s*|\s)(?:Rscript|R\s+CMD\s+BATCH(?:\s+--vanilla)?)\s+['"]?([A-Za-z0-9_./\\${}-]+\.[Rr])['"]?(.*)$"""
    )
    node_cmd_re = re.compile(
        r"""(?:^|[;&|]\s*|\s)node\s+['"]?([A-Za-z0-9_./\\${}-]+\.(?:m?js|ts))['"]?(.*)$"""
    )
    sh_sub_re = re.compile(
        r"""(?:^|[;&|]\s*|\s)(?:bash|sh)\s+['"]?([A-Za-z0-9_./\\-]+\.sh)['"]?"""
    )
    out_arg_re = re.compile(
        r"""([A-Za-z0-9_./\\${}-]+\.(?:tex|csv|pdf|png|svg|rds|pt|pth|json))""",
        flags=re.I,
    )
    heredoc_open_re = re.compile(r"""<<-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?""")
    var_assign_re = re.compile(r"""(?:^|;)\s*([A-Za-z_][A-Za-z0-9_]*)=['"]?([^'";]+)['"]?""")
    step_wrap_re = re.compile(r"""^step\s+['"]?([A-Za-z0-9_${}.-]+)['"]?\s+(.+)$""")

    def _expand_shell_vars(raw_s: str, sh_vars: Dict[str, str]) -> str:
        out_s = raw_s
        for _ in range(3):
            changed = False
            for vk, vv in sh_vars.items():
                for pat in (f"${{{vk}}}", f"${vk}"):
                    if pat in out_s:
                        out_s = out_s.replace(pat, vv)
                        changed = True
            if not changed:
                break
        # Strip any remaining leading $VAR/ or ${VAR}/ shell workspace prefixes (e.g. $OUT/Code/foo.py -> Code/foo.py)
        out_s = re.sub(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/)+", "", out_s.strip().strip('"').strip("'"))
        return out_s

    def _resolve_script_token(raw_tok: str, is_module: bool, manifest_dir: Path, sh_vars: Dict[str, str]) -> Optional[str]:
        clean = _strip_leading_dot_slash(_expand_shell_vars(raw_tok, sh_vars).replace("\\", "/"))
        if not clean or clean.startswith("-") or clean == "$0":
            return None
        cands: List[str] = []
        if is_module:
            mod_rel = clean.replace(".", "/")
            cands.extend([f"{mod_rel}.py", f"{mod_rel}/__init__.py"])
        else:
            cands.append(clean)
            if manifest_dir != repo_root:
                try:
                    sub_prefix = manifest_dir.relative_to(repo_root).as_posix()
                    cands.append(f"{sub_prefix}/{clean}")
                except ValueError:
                    pass
        for c in cands:
            if c in known_rels:
                return c
        if "/" in clean:
            parts = [pt for pt in clean.split("/") if pt and not pt.startswith("$")]
            for k in range(1, len(parts)):
                tail_cand = "/".join(parts[k:])
                if tail_cand in known_rels:
                    return tail_cand
        stem = Path(clean).stem
        if stem:
            matches = [r for r in stem_to_rels.get(stem, []) if not _is_historical_clutter_path(r)]
            if len(matches) == 1:
                return matches[0]
        return None

    def _scan_manifest_batch(batch: List[Path]) -> Tuple[List[str], List[Dict[str, Any]]]:
        manifests_used: List[str] = []
        invocations: List[Dict[str, Any]] = []
        queue_manifests = list(batch)
        local_seen = {p.resolve() for p in batch}
        while queue_manifests:
            mf = queue_manifests.pop(0)
            try:
                rel_mf = mf.relative_to(repo_root).as_posix()
            except ValueError:
                rel_mf = mf.name
            try:
                lines = mf.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            is_sh = mf.suffix.lower() == ".sh" or mf.name in exec_names
            sh_vars: Dict[str, str] = {}
            found_in_mf = False
            cur_header = ""
            heredoc_delim = ""
            i = 0
            while i < len(lines):
                raw_ln = lines[i]
                s_ln = raw_ln.strip()
                i += 1
                if heredoc_delim:
                    if s_ln == heredoc_delim:
                        heredoc_delim = ""
                    continue
                if not s_ln:
                    continue
                if s_ln.startswith("#"):
                    hdr = s_ln.lstrip("#").lstrip("- ").strip()
                    if hdr and not hdr.startswith("!"):
                        cur_header = hdr
                    continue
                if mf.name.lower().endswith("makefile") and re.match(r"^[A-Za-z0-9_.-]+\s*:", s_ln) and not raw_ln.startswith("\t"):
                    cur_header = s_ln.split(":", 1)[0].strip()
                    rest_after_colon = s_ln.split(":", 1)[1].strip()
                    if not rest_after_colon:
                        continue

                full_cmd = s_ln
                while full_cmd.endswith("\\") and i < len(lines):
                    full_cmd = full_cmd[:-1].rstrip() + " " + lines[i].strip()
                    i += 1

                if is_sh:
                    m_hd = heredoc_open_re.search(full_cmd)
                    if m_hd:
                        heredoc_delim = m_hd.group(1)

                    for m_va in var_assign_re.finditer(full_cmd):
                        v_k, v_v = m_va.group(1), m_va.group(2).strip()
                        if v_k not in ("PY", "PYTHON", "PYTHON3", "REPO", "OUT", "WORKERS"):
                            sh_vars[v_k] = _expand_shell_vars(v_v, sh_vars)

                step_label = ""
                m_step = step_wrap_re.match(full_cmd)
                if m_step:
                    step_label = m_step.group(1)
                    full_cmd = m_step.group(2).strip()

                if is_sh and re.match(r"^(?:echo|printf)\b", full_cmd):
                    continue

                m_sh = sh_sub_re.search(full_cmd)
                if m_sh:
                    sh_rel = _strip_leading_dot_slash(_expand_shell_vars(m_sh.group(1), sh_vars).replace("\\", "/"))
                    try:
                        sh_path = resolve_contained_path(repo_root, sh_rel, allow_root=False)
                        if sh_path.is_file() and sh_path.resolve() not in local_seen:
                            local_seen.add(sh_path.resolve())
                            queue_manifests.append(sh_path)
                    except AnvilRefusalError:
                        pass

                script_rel: Optional[str] = None
                tail_args = ""
                m_py = py_cmd_re.search(full_cmd)
                if m_py:
                    script_rel = _resolve_script_token(m_py.group(2), bool(m_py.group(1)), mf.parent, sh_vars)
                    tail_args = m_py.group(3) or ""
                if script_rel is None:
                    m_r = r_cmd_re.search(full_cmd)
                    if m_r:
                        script_rel = _resolve_script_token(m_r.group(1), False, mf.parent, sh_vars)
                        tail_args = m_r.group(2) or ""
                if script_rel is None:
                    m_nd = node_cmd_re.search(full_cmd)
                    if m_nd:
                        script_rel = _resolve_script_token(m_nd.group(1), False, mf.parent, sh_vars)
                        tail_args = m_nd.group(2) or ""

                if script_rel is not None:
                    found_in_mf = True
                    cmd_outputs = [
                        _expand_shell_vars(m.group(1), sh_vars).replace("\\", "/")
                        for m in out_arg_re.finditer(tail_args)
                    ]
                    eff_header = f"{cur_header} {step_label}".strip()
                    invocations.append({
                        "entrypoint": script_rel,
                        "manifest": rel_mf,
                        "header": eff_header,
                        "cmd_outputs": cmd_outputs,
                        "cmd_args": tail_args.strip(),
                    })

            if found_in_mf and rel_mf not in manifests_used:
                manifests_used.append(rel_mf)
        return manifests_used, invocations

    exec_used, exec_invs = _scan_manifest_batch(exec_manifests)
    if exec_invs:
        return exec_used, exec_invs, True
    doc_used, doc_invs = _scan_manifest_batch(doc_manifests)
    return doc_used, doc_invs, False


def _detect_excluded_shared_symbols(repo_root: Path, source_by_rel: Dict[str, str], active_files: Set[str]) -> List[str]:
    """Detect helper functions inside shared utility modules (e.g. `load_supplements_*` in `data_utils.py`)
    whose dataset slug is explicitly excluded by a repository scope contract (`PAPER_DATASETS`).
    """
    allowed_datasets: Set[str] = set()
    for rel, src in source_by_rel.items():
        if "scope" not in Path(rel).stem.lower() or not rel.endswith(".py"):
            continue
        tree = _parse_python_ast_quiet(src, filename=rel)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                lhs = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "PAPER_DATASETS" in lhs and isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            allowed_datasets.add(elt.value.strip().lower())
    if not allowed_datasets:
        return []

    generic_prefixes = {"panel", "choice", "raw", "synthetic", "minimal", "respondent", "upper", "text", "all", "cached", "conjoint", "warm", "bank", "q2", "original", "dataset"}
    excluded_syms: List[str] = []
    for rel in sorted(active_files):
        if not rel.endswith(".py"):
            continue
        src = source_by_rel.get(rel, "")
        tree = _parse_python_ast_quiet(src, filename=rel)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m_ld = re.match(r"^_?(?:load_([a-z0-9]+)_|([a-z0-9]+)_choice_ids$)", node.name.lower())
                if m_ld:
                    ds_tok = m_ld.group(1) or m_ld.group(2)
                    if ds_tok and ds_tok not in allowed_datasets and ds_tok not in generic_prefixes:
                        called_elsewhere = any(
                            re.search(rf"\b{re.escape(node.name)}\b", source_by_rel.get(other_rel, ""))
                            for other_rel in active_files
                            if other_rel != rel
                        )
                        if "data_utils" in Path(rel).stem.lower() or not called_elsewhere:
                            excluded_syms.append(f"{rel}:{node.name}")
    return excluded_syms


_ARTIFACT_CAPTION_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "from", "into", "over", "under", "table", "tables",
    "figure", "figures", "results", "result", "summary", "model", "models", "data",
    "panel", "using", "across", "main", "appendix", "section", "comparison", "estimates",
}


def _script_matches_manuscript_artifact(
    rel: str,
    src_low: str,
    art: Dict[str, Any],
    *,
    allow_caption_fallback: bool = False,
) -> bool:
    """Match a repository script `(rel, src_low)` against a manuscript table/figure artifact,
    supporting short/underscore `\\label{tab:sim_a}`, `\\label{tab:emp_1}`, `\\label{tab:t1}` ->
    `run_sim_a_benchmark.py` / `table_emp_1.py` / caption-stem overlap.
    """
    ref_low = str(art.get("ref") or "").lower()
    ref_base = Path(ref_low).name
    stem_low = str(art.get("stem") or "").lower()
    kind_low = str(art.get("kind") or "").lower()

    if ref_low and (ref_low in src_low or (len(ref_base) >= 5 and ref_base in src_low)):
        return True
    if len(stem_low) >= 4 and re.search(rf"""['"/\\_-]{re.escape(stem_low)}['"._-]""", src_low):
        return True

    if _is_historical_clutter_path(rel):
        return False

    file_stem = Path(rel).stem.lower()
    norm_file_stem = re.sub(r"[^a-z0-9]+", "_", file_stem).strip("_")
    padded_file = f"_{norm_file_stem}_" if norm_file_stem else ""
    norm_art_stem = re.sub(r"[^a-z0-9]+", "_", stem_low).strip("_")

    if norm_art_stem and len(norm_art_stem) >= 2 and f"_{norm_art_stem}_" in padded_file:
        return True

    # Compound stem matching across underscore omission (e.g. `tab:est_a` <-> `run_est_a_eval.py`, `tab:mod_b` <-> `run_mod_b_eval.py`)
    raw_ftoks = [t for t in norm_file_stem.split("_") if t]
    compact_art = norm_art_stem.replace("_", "")
    if len(compact_art) >= 4 and raw_ftoks:
        joined_spans = {
            "".join(raw_ftoks[idx : idx + span])
            for span in (2, 3)
            for idx in range(0, max(0, len(raw_ftoks) - span + 1))
        }
        if compact_art in joined_spans:
            return True

    m_short = re.fullmatch(r"([tf])(\d+[a-z]?)", norm_art_stem)
    if m_short and padded_file:
        if f"_{norm_art_stem}_" in padded_file:
            return True
        prefix_ch, num_part = m_short.group(1), m_short.group(2)
        if prefix_ch == "t" or kind_low.startswith("table"):
            for alias in (f"table_{num_part}", f"table{num_part}", f"tab_{num_part}", f"tab{num_part}"):
                if f"_{alias}_" in padded_file:
                    return True
        if prefix_ch == "f" or kind_low.startswith("figure"):
            for alias in (f"figure_{num_part}", f"figure{num_part}", f"fig_{num_part}", f"fig{num_part}"):
                if f"_{alias}_" in padded_file:
                    return True

    is_driver_like = (
        file_stem.startswith(("run_", "table_", "tab_", "make_", "build_", "fig_", "plot_", "bench_", "sim_"))
        or file_stem.endswith(("_benchmark", "_benchmarks", "_table", "_tables", "_figure", "_figures", "_runner", "_driver"))
    )
    if allow_caption_fallback and is_driver_like:
        caption_str = str(art.get("caption") or "").lower()
        art_tokens = {
            tok for tok in re.findall(r"[a-z0-9]+", f"{norm_art_stem} {caption_str}")
            if len(tok) >= 3 and tok not in _ARTIFACT_CAPTION_STOPWORDS
        }
        file_tokens = {
            tok for tok in norm_file_stem.split("_")
            if len(tok) >= 3 and tok not in _ARTIFACT_CAPTION_STOPWORDS and tok not in {"run", "make", "build", "benchmark", "benchmarks", "script", "runner", "driver"}
        }
        if len(art_tokens & file_tokens) >= 2:
            return True

    return False


def discover_paper_matched_scopes(
    repo: Path | str,
    paper_path: Optional[Path | str] = None,
    *,
    allowed_root: Optional[Path | str] = None,
    _precomputed_total_files: Optional[int] = None,
) -> Dict[str, Any]:
    """Discover exact replication code scopes matching a scientific paper's tables/figures
    and workflow manifests, compute transitive intra-repo import closures per pipeline, and
    quarantine unreachable historical trial scripts.
    """
    repo_p = Path(repo).resolve()
    if _is_link_or_junction(Path(repo)):
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Symlink or junction repository root refused.", cwe="CWE-22", details={"http_status": 403})
    if repo_p.is_file():
        resolved_single_p = ""
        if paper_path is not None and str(paper_path).strip():
            rp_cand = resolve_manuscript_path(repo_p.parent, paper_path, allowed_root=allowed_root)
            resolved_single_p = str(rp_cand) if rp_cand.exists() else ""
        return {
            "has_scope_anchor": False,
            "repo": str(repo_p),
            "paper_path": resolved_single_p,
            "workflow_manifests": [],
            "workflow_steps": [],
            "manuscript_artifacts": [],
            "pipelines": [],
            "available_pipelines": [],
            "paper_matched_files": [repo_p.name],
            "unreferenced_historical_files": [],
            "quarantined_historical_files": [],
            "quarantined_historical_count": 0,
            "excluded_shared_symbols": [],
            "total_repo_source_files": 1,
        }

    if paper_path is None and allowed_root is None and not _has_paper_or_workflow_anchor(repo_p):
        total_fast = (
            _precomputed_total_files
            if _precomputed_total_files is not None
            else len(_scan_contained_source_files(repo_p)[0])
        )
        return {
            "has_scope_anchor": False,
            "repo": str(repo_p),
            "paper_path": "",
            "workflow_manifests": [],
            "workflow_steps": [],
            "manuscript_artifacts": [],
            "pipelines": [],
            "available_pipelines": [],
            "available_pipeline_ids": [],
            "paper_matched_files": [],
            "unreferenced_historical_files": [],
            "quarantined_historical_files": [],
            "quarantined_historical_count": 0,
            "excluded_shared_symbols": [],
            "total_repo_source_files": total_fast,
        }

    prod_files, _ = _scan_contained_source_files(repo_p)
    all_prod_rels_unfiltered = [fp.relative_to(repo_p).as_posix() for fp in prod_files]

    resolved_paper: Optional[Path] = None
    if paper_path is not None and str(paper_path).strip():
        cand_paper = resolve_manuscript_path(repo_p, paper_path, allowed_root=allowed_root)
        if cand_paper.exists():
            resolved_paper = cand_paper
    else:
        resolved_paper = _pick_main_tex_file(repo_p)
        if resolved_paper is None and allowed_root is not None and str(allowed_root).strip():
            allowed_p = Path(allowed_root).resolve()
            if allowed_p.is_dir() and not _is_link_or_junction(Path(allowed_root)):
                resolved_paper = _pick_main_tex_file(allowed_p)

    # Umbrella sub-project scoping: when `resolved_paper` lives inside a self-contained sub-project
    # (e.g. `<umbrella>/<effort>/sources/<Project>/Manuscript/Main.tex`) and sibling sub-projects exist,
    # scope candidate active files to that sub-project and exclude archive/staging trees.
    umbrella_sub_prefix = ""
    if resolved_paper is not None and (resolved_paper == repo_p or repo_p in resolved_paper.parents):
        anc = resolved_paper if resolved_paper.is_dir() else resolved_paper.parent
        while anc != repo_p and repo_p in anc.parents:
            rel_anc = anc.relative_to(repo_p).as_posix()
            anc_prefix = f"{rel_anc}/"
            in_anc = [
                r for r in all_prod_rels_unfiltered
                if r.startswith(anc_prefix) and not any(pt.lower() in ARCHIVE_OR_STAGING_DIRS for pt in Path(r).parts[:-1])
            ]
            outside_anc = [
                r for r in all_prod_rels_unfiltered
                if not r.startswith(anc_prefix) and not any(pt.lower() in ARCHIVE_OR_STAGING_DIRS for pt in Path(r).parts[:-1])
            ]
            if len(in_anc) >= 2 and len(outside_anc) >= 2:
                umbrella_sub_prefix = anc_prefix
                break
            anc = anc.parent

    if umbrella_sub_prefix:
        prod_files = [
            fp for fp in prod_files
            if fp.relative_to(repo_p).as_posix().startswith(umbrella_sub_prefix)
            and not any(pt.lower() in ARCHIVE_OR_STAGING_DIRS for pt in fp.relative_to(repo_p).parts[:-1])
        ]

    all_prod_rels = [fp.relative_to(repo_p).as_posix() for fp in prod_files]
    known_rels = set(all_prod_rels)
    stem_to_rels: Dict[str, List[str]] = {}
    for rel in all_prod_rels:
        stem_to_rels.setdefault(Path(rel).stem, []).append(rel)

    manuscript_artifacts = _scan_manuscript_artifacts(resolved_paper)
    adj, source_by_rel = _build_repo_import_graph(repo_p, prod_files)
    eff_allowed_p = (
        Path(allowed_root).resolve()
        if (allowed_root is not None and str(allowed_root).strip() and not _is_link_or_junction(Path(allowed_root)))
        else None
    )
    workflow_manifests, wf_invocations, has_exec_manifest = _parse_workflow_manifests(
        repo_p, known_rels, stem_to_rels, paper_path=resolved_paper, allowed_root=eff_allowed_p
    )

    artifact_by_stem: Dict[str, Dict[str, Any]] = {}
    artifact_by_ref: Dict[str, Dict[str, Any]] = {}
    for art in manuscript_artifacts:
        if len(art["stem"]) >= 2:
            artifact_by_stem.setdefault(art["stem"], art)
        ref_k = str(art.get("ref") or "").strip().lower()
        if ref_k:
            artifact_by_ref.setdefault(ref_k, art)

    file_matched_artifacts: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in all_prod_rels}
    file_explicit_code_artifacts: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in all_prod_rels}
    if manuscript_artifacts:
        for rel, src_txt in source_by_rel.items():
            src_low = src_txt.lower()
            for art in manuscript_artifacts:
                ref_low_chk = str(art.get("ref") or "").lower()
                ref_base_chk = Path(ref_low_chk).name if ref_low_chk else ""
                stem_low_chk = str(art.get("stem") or "").lower()
                is_explicit_src_write = bool(
                    (ref_low_chk and (ref_low_chk in src_low or (len(ref_base_chk) >= 5 and ref_base_chk in src_low)))
                    or (len(stem_low_chk) >= 4 and re.search(rf"""['"/\\_-]{re.escape(stem_low_chk)}['"._-]""", src_low))
                )
                if is_explicit_src_write:
                    file_explicit_code_artifacts[rel].append(art)
                    file_matched_artifacts[rel].append(art)
                elif _script_matches_manuscript_artifact(rel, src_low, art, allow_caption_fallback=False):
                    file_matched_artifacts[rel].append(art)

    ep_records: Dict[str, Dict[str, Any]] = {}
    ep_order_map: Dict[str, int] = {}
    header_lbl_re = re.compile(r"\b((?:tab|tbl|fig|table|figure)[:_][A-Za-z0-9_.-]+)\b", re.IGNORECASE)
    for inv_idx, inv in enumerate(wf_invocations):
        ep = inv["entrypoint"]
        ep_order_map.setdefault(ep, inv_idx)
        rec = ep_records.setdefault(
            ep,
            {"entrypoint": ep, "manifests": [], "headers": [], "cmd_outputs": [], "cmd_args": [], "artifacts": [], "step_index": ep_order_map[ep]},
        )
        if inv["manifest"] not in rec["manifests"]:
            rec["manifests"].append(inv["manifest"])
        if inv["header"] and inv["header"] not in rec["headers"]:
            rec["headers"].append(inv["header"])
        cmd_arg_s = str(inv.get("cmd_args") or "").strip()
        if cmd_arg_s and cmd_arg_s not in rec["cmd_args"]:
            rec["cmd_args"].append(cmd_arg_s)
        for out_p in inv["cmd_outputs"]:
            if out_p not in rec["cmd_outputs"]:
                rec["cmd_outputs"].append(out_p)
            out_stem = Path(out_p).stem.lower()
            if out_stem in artifact_by_stem:
                rec["artifacts"].append(artifact_by_stem[out_stem])

    # Attribute workflow step header labels (e.g. `# Step 2: ... (tab:est_a, tab:est_b)`) cleanly to step entrypoints
    for ep, rec in ep_records.items():
        hdr_refs: List[Dict[str, Any]] = []
        for hdr in rec["headers"]:
            for m_hl in header_lbl_re.finditer(hdr):
                rk = m_hl.group(1).lower()
                if rk in artifact_by_ref and artifact_by_ref[rk] not in hdr_refs:
                    hdr_refs.append(artifact_by_ref[rk])
        if len(hdr_refs) == 1:
            if hdr_refs[0] not in rec["artifacts"]:
                rec["artifacts"].append(hdr_refs[0])
        elif len(hdr_refs) > 1:
            args_blob = " ".join(rec.get("cmd_args") or []).lower()
            ep_src_low = source_by_rel.get(ep, "").lower()
            specific_hdr: List[Dict[str, Any]] = []
            for h_art in hdr_refs:
                h_stem = str(h_art.get("stem") or "").lower()
                if _script_matches_manuscript_artifact(ep, ep_src_low, h_art, allow_caption_fallback=False) or (
                    len(h_stem) >= 2 and re.search(rf"(?<![a-z0-9]){re.escape(h_stem)}(?![a-z0-9])", args_blob)
                ):
                    specific_hdr.append(h_art)
            for chosen_art in (specific_hdr if specific_hdr else hdr_refs):
                if chosen_art not in rec["artifacts"]:
                    rec["artifacts"].append(chosen_art)

    # Caption fallback for still-unmatched artifacts (on manifest entrypoints when workflow manifest exists, else candidate drivers)
    if manuscript_artifacts:
        matched_refs_so_far = {
            str(a.get("ref") or "").lower()
            for arts in file_matched_artifacts.values()
            for a in arts
        } | {
            str(a.get("ref") or "").lower()
            for rec in ep_records.values()
            for a in rec["artifacts"]
        }
        unmatched_arts = [a for a in manuscript_artifacts if str(a.get("ref") or "").lower() not in matched_refs_so_far]
        if unmatched_arts:
            cap_pool = list(ep_records.keys()) if has_exec_manifest else list(source_by_rel.keys())
            for rel_c in cap_pool:
                src_low_c = source_by_rel.get(rel_c, "").lower()
                for u_art in unmatched_arts:
                    if _script_matches_manuscript_artifact(rel_c, src_low_c, u_art, allow_caption_fallback=True):
                        if rel_c in ep_records and u_art not in ep_records[rel_c]["artifacts"]:
                            ep_records[rel_c]["artifacts"].append(u_art)
                        elif not has_exec_manifest and u_art not in file_matched_artifacts[rel_c]:
                            file_matched_artifacts[rel_c].append(u_art)

    wf_closure_files = set(_compute_import_closure(list(ep_records.keys()), adj)) if ep_records else set()
    wf_covered_stems: Set[str] = set()
    for cf in wf_closure_files:
        for art in file_matched_artifacts.get(cf, []):
            wf_covered_stems.add(art["stem"])
    for rec in ep_records.values():
        for out_p in rec["cmd_outputs"]:
            wf_covered_stems.add(Path(out_p).stem.lower())

    non_hist_writers = [
        rel for rel, arts in file_matched_artifacts.items()
        if arts and not _is_historical_clutter_path(rel)
    ]
    candidate_writers = non_hist_writers or [rel for rel, arts in file_matched_artifacts.items() if arts]
    imported_by_any: Set[str] = {tgt for tgts in adj.values() for tgt in tgts}
    for rel in candidate_writers:
        if rel in ep_records:
            for fa in file_matched_artifacts[rel]:
                if fa not in ep_records[rel]["artifacts"]:
                    ep_records[rel]["artifacts"].append(fa)
        elif not has_exec_manifest and (rel not in imported_by_any or not ep_records):
            ep_order_map.setdefault(rel, len(ep_order_map))
            ep_records[rel] = {
                "entrypoint": rel,
                "manifests": [],
                "headers": [],
                "cmd_outputs": [],
                "cmd_args": [],
                "artifacts": list(file_matched_artifacts[rel]),
                "step_index": ep_order_map[rel],
            }

    ep_closures_map: Dict[str, List[str]] = {
        ep: _compute_import_closure([ep], adj) for ep in ep_records
    }
    cf_ep_count: Dict[str, int] = {}
    for ep, cfiles in ep_closures_map.items():
        for cf in cfiles:
            cf_ep_count[cf] = cf_ep_count.get(cf, 0) + 1

    workflow_steps_out: List[Dict[str, Any]] = []
    grouped_pipelines: Dict[str, Dict[str, Any]] = {}
    for ep, rec in sorted(ep_records.items(), key=lambda kv: (int(kv[1].get("step_index", 999)), kv[0])):
        closure_files = ep_closures_map[ep]
        all_arts = list(rec["artifacts"])
        for cf in closure_files:
            if cf == ep or not all_arts:
                for ca in file_matched_artifacts.get(cf, []):
                    if ca not in all_arts:
                        all_arts.append(ca)
        target_refs = list(dict.fromkeys(
            [a["ref"] for a in all_arts] + list(rec["cmd_outputs"])
        ))
        target_secs = list(dict.fromkeys(
            a["section"] for a in all_arts if a.get("section")
        ))
        header_str = " ".join(rec["headers"]).strip()
        pid, ptitle = _classify_pipeline_bucket(ep, header_str, target_refs, target_secs)
        step_title = (
            rec["headers"][0].strip()
            if rec["headers"] and len(rec["headers"][0].strip()) >= 4
            else ptitle
        )
        workflow_steps_out.append({
            "step_index": int(rec.get("step_index", len(workflow_steps_out))),
            "entrypoint": ep,
            "pipeline_id": pid,
            "title": step_title[:72],
            "pipeline_title": ptitle,
            "files": closure_files,
            "manuscript_targets": target_refs,
            "sections": target_secs,
            "manifests": list(rec["manifests"]),
        })

        p_entry = grouped_pipelines.setdefault(
            pid,
            {
                "id": pid,
                "pipeline_id": pid,
                "title": ptitle,
                "entrypoints": [],
                "files": set(),
                "manuscript_targets": [],
                "sections": [],
                "workflow_sources": [],
            },
        )
        if ep not in p_entry["entrypoints"]:
            p_entry["entrypoints"].append(ep)
        p_entry["files"].update(closure_files)
        for tr in target_refs:
            if tr not in p_entry["manuscript_targets"]:
                p_entry["manuscript_targets"].append(tr)
        for ts in target_secs:
            if ts not in p_entry["sections"]:
                p_entry["sections"].append(ts)
        for ms in rec["manifests"]:
            if ms not in p_entry["workflow_sources"]:
                p_entry["workflow_sources"].append(ms)

    order_priority = {
        "data_preparation": 0,
        "predictive_tables": 1,
        "policy_targeting": 2,
        "simulations": 3,
        "verification_checks": 4,
    }
    pipelines_out: List[Dict[str, Any]] = []
    for pid, pobj in sorted(grouped_pipelines.items(), key=lambda kv: (order_priority.get(kv[0], 10), kv[0])):
        sorted_files = sorted(pobj["files"])
        sorted_eps = list(dict.fromkeys(pobj["entrypoints"]))
        pipelines_out.append({
            "id": pid,
            "pipeline_id": pid,
            "title": pobj["title"],
            "entrypoints": sorted_eps,
            "files": sorted_files,
            "reachable_files": sorted_files,
            "file_count": len(sorted_files),
            "manuscript_targets": pobj["manuscript_targets"],
            "sections": pobj["sections"],
            "workflow_sources": pobj["workflow_sources"],
        })

    paper_matched_set: Set[str] = {f for p in pipelines_out for f in p["files"]}
    if umbrella_sub_prefix and not paper_matched_set and all_prod_rels:
        paper_matched_set = {
            r for r in all_prod_rels if not _is_historical_clutter_path(r)
        } or set(all_prod_rels)
        pipelines_out.append({
            "id": "subproject_replication",
            "pipeline_id": "subproject_replication",
            "title": "Subproject Replication Scope",
            "entrypoints": sorted(paper_matched_set)[:5],
            "files": sorted(paper_matched_set),
            "reachable_files": sorted(paper_matched_set),
            "file_count": len(paper_matched_set),
            "manuscript_targets": [a["ref"] for a in manuscript_artifacts],
            "sections": list(dict.fromkeys(a["section"] for a in manuscript_artifacts if a.get("section"))),
            "workflow_sources": workflow_manifests,
        })
    has_scope_anchor = len(pipelines_out) > 0
    if has_scope_anchor:
        paper_matched_files = sorted(paper_matched_set)
        full_known = set(all_prod_rels_unfiltered) if umbrella_sub_prefix else known_rels
        unreferenced_historical = sorted(full_known - paper_matched_set)
        excluded_shared = _detect_excluded_shared_symbols(repo_p, source_by_rel, paper_matched_set)
    else:
        paper_matched_files = []
        unreferenced_historical = []
        excluded_shared = []

    return {
        "has_scope_anchor": has_scope_anchor,
        "umbrella_scoped": bool(umbrella_sub_prefix),
        "repo": str(repo_p),
        "paper_path": str(resolved_paper) if resolved_paper else "",
        "workflow_manifests": workflow_manifests,
        "workflow_steps": workflow_steps_out,
        "manuscript_artifacts": manuscript_artifacts,
        "pipelines": pipelines_out,
        "available_pipelines": pipelines_out,
        "available_pipeline_ids": [p["id"] for p in pipelines_out],
        "paper_matched_files": paper_matched_files,
        "unreferenced_historical_files": unreferenced_historical,
        "quarantined_historical_files": unreferenced_historical,
        "quarantined_historical_count": len(unreferenced_historical),
        "excluded_shared_symbols": excluded_shared,
        "total_repo_source_files": len(all_prod_rels_unfiltered) if umbrella_sub_prefix else len(all_prod_rels),
    }


def resolve_active_pipeline_scope(
    scope_info: Dict[str, Any],
    pipeline_id: Optional[str] = None,
    *,
    auto_threshold: int = 15,
) -> Dict[str, Any]:
    """Resolve `paper_matched_scopes` metadata and active file filter for `map`,
    `process-map`, and `paper-map`.
    """
    pipelines = scope_info.get("pipelines") or []
    by_id = {p["id"]: p for p in pipelines}
    unreferenced = list(scope_info.get("unreferenced_historical_files") or [])
    excluded_shared = list(scope_info.get("excluded_shared_symbols") or [])
    total_files = int(scope_info.get("total_repo_source_files") or 0)
    req_pid = (pipeline_id or "").strip()

    active_files: Optional[List[str]] = None
    active_pipeline = "unscoped"
    scoped = False

    if req_pid and req_pid.lower() not in ("all", "all_paper_matched", "none"):
        if req_pid not in by_id:
            raise AnvilRefusalError(
                "INVALID_PIPELINE_SCOPE",
                f"Unknown pipeline_id '{req_pid}'. Available pipelines: {sorted(by_id.keys())}.",
                details={"requested_pipeline": req_pid, "available_pipelines": sorted(by_id.keys())},
            )
        active_files = list(by_id[req_pid]["files"])
        active_pipeline = req_pid
        scoped = True
    elif req_pid.lower() in ("all", "all_paper_matched") and scope_info.get("paper_matched_files"):
        active_files = list(scope_info["paper_matched_files"])
        active_pipeline = "all_paper_matched"
        scoped = True
    elif (
        scope_info.get("has_scope_anchor")
        and (
            bool(scope_info.get("workflow_manifests"))
            or bool(scope_info.get("umbrella_scoped"))
            or len(pipelines) >= 2
        )
        and (
            total_files > auto_threshold
            or bool(scope_info.get("umbrella_scoped"))
            or (bool(scope_info.get("workflow_manifests")) and len(unreferenced) > 0)
        )
        and (len(unreferenced) > 0 or bool(scope_info.get("workflow_manifests")))
        and scope_info.get("paper_matched_files")
    ):
        active_files = list(scope_info["paper_matched_files"])
        active_pipeline = "all_paper_matched"
        scoped = True

    return {
        "scoped": scoped,
        "active_pipeline": active_pipeline,
        "available_pipelines": [
            {
                "id": p["id"],
                "pipeline_id": p["id"],
                "title": p["title"],
                "entrypoints": p["entrypoints"],
                "files": p["files"],
                "file_count": p["file_count"],
                "manuscript_targets": p["manuscript_targets"],
                "sections": p.get("sections", []),
            }
            for p in pipelines
        ],
        "available_pipeline_ids": [p["id"] for p in pipelines],
        "workflow_steps": list(scope_info.get("workflow_steps") or []),
        "active_files": active_files or [],
        "paper_matched_files": list(scope_info.get("paper_matched_files") or []),
        "quarantined_historical_count": len(unreferenced),
        "quarantined_historical_files": unreferenced,
        "unreferenced_historical_files": unreferenced,
        "excluded_shared_symbols": excluded_shared,
        "total_repo_source_files": total_files,
        "workflow_manifests": list(scope_info.get("workflow_manifests") or []),
    }


# ---------------------------------------------------------------------------
# 4. Pure-Static AST Repository Scanner & L0->L1->L2->L3 Process Map Builder
# ---------------------------------------------------------------------------

def _scan_contained_source_files(repo_root: Path) -> Tuple[List[Path], List[Path]]:
    """Return `(prod_files, test_files)` sorted deterministically; fail closed on symlink escapes."""
    prod_files: List[Path] = []
    test_files: List[Path] = []
    supported_exts = {".py", ".js", ".mjs", ".ts", ".r", ".R"}

    for cur_root, dirs, files in os.walk(repo_root, followlinks=False):
        cur_path = Path(cur_root)
        kept_dirs: List[str] = []
        for d in sorted(dirs):
            if d in SKIP_SCAN_DIRS or d.startswith(".") or d.startswith("_"):
                continue
            dp = cur_path / d
            if _is_link_or_junction(dp):
                if not dp.resolve().is_relative_to(repo_root):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Directory symlink/junction '{d}' escapes repository root.",
                        cwe="CWE-22",
                        details={"http_status": 403},
                    )
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in sorted(files):
            if fname.startswith("."):
                continue
            fp = cur_path / fname
            if _is_link_or_junction(fp):
                if not fp.resolve().is_relative_to(repo_root):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"File symlink '{fname}' escapes repository root.",
                        cwe="CWE-22",
                        details={"http_status": 403},
                    )
                continue
            if fp.suffix not in supported_exts:
                continue
            rel = fp.relative_to(repo_root)
            low_parts = {pt.lower() for pt in rel.parts[:-1]}
            is_test = bool(low_parts & {"tests", "test"}) or fname.lower().startswith("test_") or fname.lower().endswith("_test.py")
            if is_test:
                test_files.append(fp)
            else:
                prod_files.append(fp)
    return prod_files, test_files


MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024

SIMULATION_HINTS = (
    "simulat", "dgp", "monte_carlo", "montecarlo", "synthetic", "draw_panel", "gen_data",
)
SIMULATION_DIR_TOKENS: Set[str] = {
    "simulation", "simulations", "dgp", "dgps", "synthetic", "monte_carlo", "montecarlo",
}
SIMULATION_STEM_PREFIXES: Tuple[str, ...] = (
    "simulat", "simul", "dgp", "monte", "synthetic",
)
EMIT_FILE_TOKENS: Set[str] = {
    "table", "tables", "tab1", "tab2", "tab3", "plot", "plots",
    "fig", "figs", "figure", "figures", "report", "reports",
    "export", "exports", "summarize", "summary", "render", "format",
}
EMIT_STEM_PREFIXES: Tuple[str, ...] = (
    "check_", "plot_", "fig_", "summarize_", "build_table", "make_table", "render_", "format_table",
)
INGEST_DIR_TOKENS: Set[str] = {"prep", "ingest", "etl", "preprocess"}
INGEST_FILE_TOKENS: Set[str] = {"prepare", "prep", "ingest", "extract", "reconstruct", "etl"}

_TORCH_NN_BUILTIN_LAYERS: Set[str] = {
    "Linear", "LazyLinear", "Bilinear", "Identity", "Sequential", "ModuleList", "ModuleDict",
    "Conv1d", "Conv2d", "Conv3d", "ConvTranspose1d", "ConvTranspose2d", "LSTM", "GRU", "RNN",
    "Transformer", "TransformerEncoder", "TransformerDecoder", "MultiheadAttention",
    "Embedding", "EmbeddingBag", "LayerNorm", "BatchNorm1d", "BatchNorm2d", "GroupNorm",
    "Dropout", "ReLU", "LeakyReLU", "GELU", "SiLU", "Tanh", "Sigmoid", "Softmax", "LogSoftmax",
}
_CTOR_WRAPPER_ATTRS: Set[str] = {
    "to", "cuda", "cpu", "eval", "train", "float", "double", "half", "bfloat16", "requires_grad_",
}
_AMBIGUOUS_BARE_HELPER_NAMES: Set[str] = {
    "main", "run", "cli", "app", "parse_args", "setup", "init", "__init__", "forward",
    "__call__", "fit", "train", "evaluate", "predict", "loss", "step", "load", "save",
    "load_data", "get_data", "build", "check", "verify", "plot", "summarize",
}


def _tokenize_stage_ident(raw: str) -> List[str]:
    de_camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", raw or ""))
    return re.findall(r"[a-z0-9]+", de_camel.lower())


def _token_matches_hint(tok: str, hint: str) -> bool:
    if tok == hint:
        return True
    if hint in ("config", "open", "init", "input", "scan", "save", "dump"):
        return tok in (hint, f"{hint}s", f"{hint}ed", f"{hint}ing", "initialize", "initialise")
    return len(hint) >= 4 and tok.startswith(hint)


def _unwrap_ctor_call(expr: Optional[ast.AST]) -> Optional[ast.Call]:
    cur = expr
    for _ in range(6):
        if not isinstance(cur, ast.Call):
            return None
        if isinstance(cur.func, ast.Attribute) and cur.func.attr in _CTOR_WRAPPER_ATTRS:
            cur = cur.func.value
            continue
        if (
            isinstance(cur.func, ast.Attribute)
            and cur.func.attr in ("compile", "DataParallel", "DistributedDataParallel")
            and cur.args
        ):
            cur = cur.args[0]
            continue
        return cur
    return cur if isinstance(cur, ast.Call) else None


def _collect_repo_nn_module_classes(files: Sequence[Path], root: Path) -> Set[str]:
    """Compute repository-wide PyTorch `nn.Module` / `Dataset` / `LightningModule` subclasses to a fixpoint."""
    raw_bases: Dict[str, List[str]] = {}
    for fp in files:
        if fp.suffix != ".py":
            continue
        try:
            txt = fp.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        rel = fp.relative_to(root).as_posix() if (fp == root or root in fp.parents) else fp.name
        tree = _parse_python_ast_quiet(txt, filename=rel)
        if tree is None:
            continue
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                b_list: List[str] = []
                for b in stmt.bases:
                    try:
                        b_list.append(ast.unparse(b))
                    except Exception:
                        if isinstance(b, ast.Name):
                            b_list.append(b.id)
                        elif isinstance(b, ast.Attribute):
                            b_list.append(b.attr)
                raw_bases.setdefault(stmt.name, []).extend(b_list)

    nn_classes: Set[str] = {
        cname
        for cname, blist in raw_bases.items()
        if any(
            b.endswith(("Module", "Dataset", "IterableDataset", "LightningModule", "PreTrainedModel"))
            for b in blist
        )
    }
    changed = True
    while changed:
        changed = False
        for cname, blist in raw_bases.items():
            if cname not in nn_classes and any(b.split(".")[-1] in nn_classes for b in blist):
                nn_classes.add(cname)
                changed = True
    return nn_classes


def get_l3_numbered_file(repo_dir: str | Path, rel_path: str) -> Dict[str, Any]:
    """Return Level-3 1-based line-numbered source for a contained repository file."""
    root = Path(repo_dir).resolve()
    fpath = resolve_contained_path(root, rel_path, allow_root=False, must_be_relative=True)
    if not fpath.is_file():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Source file not found: '{rel_path}'.", cwe="CWE-22")
    st_size = fpath.stat().st_size
    if st_size > MAX_SOURCE_FILE_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Source file '{rel_path}' exceeds 2 MB limit ({st_size} > {MAX_SOURCE_FILE_BYTES} bytes).",
            details={
                "bound_name": "max_source_file_bytes",
                "bound_limit": MAX_SOURCE_FILE_BYTES,
                "observed_value": st_size,
                "http_status": 413,
            },
        )
    raw_bytes = fpath.read_bytes()
    if len(raw_bytes) > MAX_SOURCE_FILE_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Source file '{rel_path}' exceeds 2 MB limit ({len(raw_bytes)} > {MAX_SOURCE_FILE_BYTES} bytes).",
            details={
                "bound_name": "max_source_file_bytes",
                "bound_limit": MAX_SOURCE_FILE_BYTES,
                "observed_value": len(raw_bytes),
                "http_status": 413,
            },
        )
    text = raw_bytes.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text[:-1].split("\n") if text.endswith("\n") else (text.split("\n") if text else [])
    rel_posix = fpath.relative_to(root).as_posix()
    return {
        "ok": True,
        "file": rel_posix,
        "start_line": 1,
        "end_line": len(lines),
        "total_lines": len(lines),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest()[:16],
        "content": text,
        "raw_source": text,
        "lines": [{"line": idx, "text": ln} for idx, ln in enumerate(lines, start=1)],
        "numbered_source": "\n".join(f"{idx:4d} | {ln}" for idx, ln in enumerate(lines, start=1)),
    }


def _classify_unit_kind(
    name: str,
    doc: str,
    has_loop: bool,
    calls: Sequence[str],
    rel_posix: str = "",
) -> str:
    low = f"{name} {doc}".lower()
    rel_low = str(rel_posix or "").lower()
    stem_low = Path(rel_low).stem
    name_tokens = set(_tokenize_stage_ident(name))
    tokens = set(_tokenize_stage_ident(low))
    stem_tokens = set(_tokenize_stage_ident(stem_low))
    dir_tokens = {tok for seg in Path(rel_low).parts[:-1] for tok in _tokenize_stage_ident(seg)}
    call_low = {c.lower() for c in calls}

    has_emit_unit_tok = bool(
        (name_tokens & EMIT_FILE_TOKENS)
        or any(_token_matches_hint(tok, eh) for tok in name_tokens for eh in ("plot", "figure", "table", "render", "format", "summarize"))
    )
    has_emit_file_tok = bool((stem_tokens & EMIT_FILE_TOKENS) or stem_low.startswith(EMIT_STEM_PREFIXES))
    is_ingest_file = bool(
        (dir_tokens & INGEST_DIR_TOKENS)
        or ((stem_tokens & INGEST_FILE_TOKENS) and "feature" not in stem_tokens)
    )
    is_sim_path = bool(
        (dir_tokens & SIMULATION_DIR_TOKENS)
        or any(tok.startswith(SIMULATION_STEM_PREFIXES) for tok in stem_tokens)
    )
    is_sim_unit = bool(
        any(tok.startswith(SIMULATION_STEM_PREFIXES) for tok in tokens)
        or any(h in low for h in ("draw_panel", "gen_data", "monte_carlo"))
    )
    if (is_sim_path or is_sim_unit) and not has_emit_unit_tok and not has_emit_file_tok and not is_ingest_file:
        return "simulation"
    if any(_token_matches_hint(tok, h) for tok in tokens for h in INGEST_HINTS):
        return "ingest"
    if has_emit_unit_tok or any(_token_matches_hint(tok, h) for tok in tokens for h in EMIT_HINTS):
        return "emit"
    if is_ingest_file and not has_loop:
        return "ingest"
    if has_loop or any(_token_matches_hint(tok, h) for tok in tokens for h in LOOP_HINTS):
        return "loop"
    if call_low & {"open", "loads", "read_text", "read_csv", "read_parquet"} and not (call_low & {"write_text", "dumps", "to_csv", "to_parquet"}):
        return "ingest"
    return "compute"


def _extract_python_units(
    fpath: Path,
    rel_posix: str,
    *,
    repo_nn_classes: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    text = fpath.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    tree = _parse_python_ast_quiet(text, filename=rel_posix)
    if tree is None:
        return [], False

    has_main_guard = False
    units: List[Dict[str, Any]] = []

    nn_module_classes: Set[str] = set(repo_nn_classes or ())
    local_cls_bases: Dict[str, List[str]] = {}
    for top_node in tree.body:
        if isinstance(top_node, ast.ClassDef):
            base_names: List[str] = []
            for b in top_node.bases:
                try:
                    base_names.append(ast.unparse(b))
                except Exception:
                    if isinstance(b, ast.Name):
                        base_names.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        base_names.append(b.attr)
            local_cls_bases[top_node.name] = base_names
            if any(
                bn.endswith(("Module", "Dataset", "IterableDataset", "LightningModule", "PreTrainedModel"))
                or bn.split(".")[-1] in nn_module_classes
                for bn in base_names
            ):
                nn_module_classes.add(top_node.name)

    changed_nn = True
    while changed_nn:
        changed_nn = False
        for cname, bnames in local_cls_bases.items():
            if cname not in nn_module_classes and any(bn.split(".")[-1] in nn_module_classes for bn in bnames):
                nn_module_classes.add(cname)
                changed_nn = True

    class_submodules: Dict[Tuple[str, str], str] = {}
    for top_node in tree.body:
        if isinstance(top_node, ast.ClassDef):
            for mnode in top_node.body:
                if isinstance(mnode, ast.FunctionDef) and mnode.name == "__init__":
                    for sub in ast.walk(mnode):
                        if not isinstance(sub, ast.Assign):
                            continue
                        ctor_call = _unwrap_ctor_call(sub.value)
                        if ctor_call is None:
                            continue
                        if not any(
                            isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"
                            for t in sub.targets
                        ):
                            continue
                        callee_nm = (
                            ctor_call.func.id
                            if isinstance(ctor_call.func, ast.Name)
                            else (ctor_call.func.attr if isinstance(ctor_call.func, ast.Attribute) else "")
                        )
                        is_nn_attr_ctor = (
                            callee_nm in nn_module_classes
                            or callee_nm in _TORCH_NN_BUILTIN_LAYERS
                            or (
                                isinstance(ctor_call.func, ast.Attribute)
                                and isinstance(ctor_call.func.value, ast.Name)
                                and ctor_call.func.value.id == "nn"
                            )
                        )
                        if callee_nm and is_nn_attr_ctor:
                            for t in sub.targets:
                                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                                    class_submodules[(top_node.name, t.attr)] = callee_nm

    def _visit_fn(node: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str = "") -> Dict[str, Any]:
        qname = f"{cls_name}.{node.name}" if cls_name else node.name
        doc = (ast.get_docstring(node) or "").strip()
        first_doc = doc.splitlines()[0].strip() if doc else ""
        args = [a.arg for a in (list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)) if a.arg not in ("self", "cls")]
        ret_ann = ""
        if node.returns is not None:
            try:
                ret_ann = ast.unparse(node.returns)
            except Exception:
                ret_ann = ""
        calls: List[str] = []
        outputs: List[str] = []
        loop_lines: List[int] = []
        blind_spots: List[Dict[str, Any]] = []
        local_nn_vars: Dict[str, str] = {}

        for child in ast.walk(node):
            if (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
            ):
                ctor_c = _unwrap_ctor_call(child.value)
                if ctor_c is not None:
                    cname = (
                        ctor_c.func.id
                        if isinstance(ctor_c.func, ast.Name)
                        else (ctor_c.func.attr if isinstance(ctor_c.func, ast.Attribute) else "")
                    )
                    if cname in nn_module_classes:
                        local_nn_vars[child.targets[0].id] = cname

        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                loop_lines.append(getattr(child, "lineno", node.lineno))
            elif isinstance(child, ast.Call):
                lno = getattr(child, "lineno", node.lineno)
                fn_expr = child.func
                if isinstance(fn_expr, ast.Name):
                    cid = fn_expr.id
                    calls.append(cid)
                    if cid in nn_module_classes:
                        calls.append(f"{cid}.forward")
                    elif cid in local_nn_vars:
                        calls.append(f"{local_nn_vars[cid]}.forward")
                    if cid in ("getattr", "__import__"):
                        snip = lines[lno - 1].strip()[:80] if 1 <= lno <= len(lines) else cid
                        blind_spots.append({
                            "kind": "getattr" if cid == "getattr" else "importlib",
                            "marker": "⋯?",
                            "file": rel_posix,
                            "symbol": qname,
                            "line": lno,
                            "expr": snip,
                        })
                elif isinstance(fn_expr, ast.Attribute):
                    calls.append(fn_expr.attr)
                    if (
                        cls_name
                        and isinstance(fn_expr.value, ast.Name)
                        and fn_expr.value.id == "self"
                        and (cls_name, fn_expr.attr) in class_submodules
                    ):
                        sub_cls = class_submodules[(cls_name, fn_expr.attr)]
                        if sub_cls in nn_module_classes:
                            calls.append(f"{sub_cls}.forward")
                    if fn_expr.attr == "import_module":
                        snip = lines[lno - 1].strip()[:80] if 1 <= lno <= len(lines) else "import_module"
                        blind_spots.append({
                            "kind": "importlib",
                            "marker": "⋯?",
                            "file": rel_posix,
                            "symbol": qname,
                            "line": lno,
                            "expr": snip,
                        })
                elif isinstance(fn_expr, ast.Subscript):
                    snip = lines[lno - 1].strip()[:80] if 1 <= lno <= len(lines) else "dynamic_dispatch"
                    blind_spots.append({
                        "kind": "dynamic_callback",
                        "marker": "⋯?",
                        "file": rel_posix,
                        "symbol": qname,
                        "line": lno,
                        "expr": snip,
                    })
            elif isinstance(child, ast.Return) and child.value is not None:
                try:
                    outputs.append(ast.unparse(child.value)[:48])
                except Exception:
                    pass

        uniq_calls = list(dict.fromkeys(c for c in calls if c != node.name))
        has_loop = len(loop_lines) > 0
        kind = _classify_unit_kind(node.name, first_doc, has_loop, uniq_calls, rel_posix=rel_posix)
        start_ln = int(getattr(node, "lineno", 1))
        end_ln = int(getattr(node, "end_lineno", start_ln))
        return {
            "id": f"{rel_posix}:{qname}",
            "file": rel_posix,
            "symbol": qname,
            "short_name": node.name,
            "class_name": cls_name,
            "is_nn_module": cls_name in nn_module_classes,
            "start_line": start_ln,
            "end_line": end_ln,
            "args": args,
            "return_type": ret_ann,
            "docstring": first_doc,
            "calls": uniq_calls,
            "has_loop": has_loop,
            "loop_lines": sorted(set(loop_lines)),
            "dynamic_blind_spots": blind_spots,
            "outputs": list(dict.fromkeys(outputs))[:3] or ([ret_ann] if ret_ann else [f"{node.name}_result"]),
            "kind": kind,
        }

    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.append(_visit_fn(item))
        elif isinstance(item, ast.ClassDef):
            for sub in item.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    units.append(_visit_fn(sub, cls_name=item.name))
        elif isinstance(item, ast.If):
            try:
                cond_txt = ast.unparse(item.test)
            except Exception:
                cond_txt = ""
            if "__name__" in cond_txt and "__main__" in cond_txt:
                has_main_guard = True

    if not units and lines:
        n = len(lines)
        b1 = max(1, n // 3)
        b2 = max(b1 + 1, (2 * n) // 3) if n >= 3 else n
        spans = [(1, b1, "ingest", "script_ingest"), (min(n, b1 + 1), b2, "compute", "script_compute"), (min(n, b2 + 1), n, "emit", "script_emit")]
        for s_ln, e_ln, knd, sym in spans:
            units.append({
                "id": f"{rel_posix}:{sym}",
                "file": rel_posix,
                "symbol": sym,
                "short_name": sym,
                "start_line": s_ln,
                "end_line": max(s_ln, e_ln),
                "args": ["argv"],
                "return_type": "",
                "docstring": f"Top-level {knd} block in {rel_posix}",
                "calls": [],
                "has_loop": any(isinstance(ch, (ast.For, ast.While)) for ch in ast.walk(tree)) if knd == "compute" else False,
                "loop_lines": [],
                "dynamic_blind_spots": [],
                "outputs": [f"{knd}_state"],
                "kind": knd,
            })
        has_main_guard = True

    return units, has_main_guard


_JS_FN_DECL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)"
)
_JS_FN_VAR_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:function\b\s*\(([^)]*)\)|\(([^)]*)\)\s*=>|([A-Za-z_$][A-Za-z0-9_$]*)\s*=>)"
)
_R_FN_DECL_RE = re.compile(
    r"^\s*([A-Za-z.][A-Za-z0-9._]*)\s*(?:<-|=)\s*function\s*\(([^)]*)\)"
)
_CALL_TOKEN_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
_NON_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "return", "function", "catch", "typeof", "await", "new", "repeat",
}
_DYN_EVAL_RE = re.compile(r"(?:\b" + "ev" + r"al\s*\(|\bnew\s+Function\b|\bimport\s*\(|\]\s*\()")


def _strip_line_comment(line: str, is_r: bool) -> str:
    idx = line.find("#" if is_r else "//")
    return line[:idx] if idx >= 0 else line


def _extract_polyglot_units(fpath: Path, rel_posix: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Extract deterministic function and top-level script units for JS/TS/R files (zero execution)."""
    text = fpath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return [], False

    is_r = fpath.suffix.lower() == ".r"
    units: List[Dict[str, Any]] = []
    n_lines = len(lines)
    idx = 0

    while idx < n_lines:
        raw_ln = lines[idx]
        clean_ln = _strip_line_comment(raw_ln, is_r)
        fn_name = ""
        raw_args = ""
        if is_r:
            m_r = _R_FN_DECL_RE.match(clean_ln)
            if m_r:
                fn_name = m_r.group(1)
                raw_args = m_r.group(2) or ""
        else:
            m_fn = _JS_FN_DECL_RE.match(clean_ln)
            if m_fn:
                fn_name = m_fn.group(1)
                raw_args = m_fn.group(2) or ""
            else:
                m_var = _JS_FN_VAR_RE.match(clean_ln)
                if m_var:
                    fn_name = m_var.group(1)
                    raw_args = m_var.group(2) or m_var.group(3) or m_var.group(4) or ""

        if not fn_name:
            idx += 1
            continue

        start_ln = idx + 1
        end_ln = start_ln
        brace_depth = 0
        saw_open = False
        for scan_i in range(idx, n_lines):
            scan_clean = _strip_line_comment(lines[scan_i], is_r)
            opens = scan_clean.count("{")
            closes = scan_clean.count("}")
            if opens > 0:
                saw_open = True
            brace_depth += opens - closes
            end_ln = scan_i + 1
            if saw_open and brace_depth <= 0:
                break
            if not saw_open and scan_i > idx:
                end_ln = start_ln
                break

        arg_list = [
            a.split("=")[0].split(":")[0].strip()
            for a in raw_args.split(",")
            if a.strip()
        ]
        calls: List[str] = []
        loop_lines: List[int] = []
        blind_spots: List[Dict[str, Any]] = []
        outputs: List[str] = []

        for body_i in range(start_ln - 1, end_ln):
            lno = body_i + 1
            b_clean = _strip_line_comment(lines[body_i], is_r)
            if re.search(r"\b(?:for|while|repeat)\b", b_clean):
                loop_lines.append(lno)
            for cm in _CALL_TOKEN_RE.finditer(b_clean):
                tok = cm.group(1)
                if tok not in _NON_CALL_KEYWORDS and tok != fn_name:
                    calls.append(tok)
            if _DYN_EVAL_RE.search(b_clean):
                blind_spots.append({
                    "kind": "dynamic_callback",
                    "marker": "⋯?",
                    "file": rel_posix,
                    "symbol": fn_name,
                    "line": lno,
                    "expr": b_clean.strip()[:80],
                })
            m_ret = re.search(r"\breturn\s+([^;]+)", b_clean)
            if m_ret:
                outputs.append(m_ret.group(1).strip()[:48])

        uniq_calls = list(dict.fromkeys(calls))
        has_loop = len(loop_lines) > 0
        kind = _classify_unit_kind(fn_name, "", has_loop, uniq_calls, rel_posix=rel_posix)
        units.append({
            "id": f"{rel_posix}:{fn_name}",
            "file": rel_posix,
            "symbol": fn_name,
            "short_name": fn_name,
            "start_line": start_ln,
            "end_line": max(start_ln, end_ln),
            "args": arg_list,
            "return_type": "",
            "docstring": "",
            "calls": uniq_calls,
            "has_loop": has_loop,
            "loop_lines": sorted(set(loop_lines)),
            "dynamic_blind_spots": blind_spots,
            "outputs": list(dict.fromkeys(outputs))[:3] or [f"{fn_name}_result"],
            "kind": kind,
        })
        idx = max(idx + 1, end_ln)

    has_top_entry = False
    if units:
        max_fn_end = max(int(u["end_line"]) for u in units)
        tail_exec = [
            (l_idx + 1, _strip_line_comment(lines[l_idx], is_r).strip())
            for l_idx in range(max_fn_end, n_lines)
        ]
        tail_non_empty = [(lno, txt) for lno, txt in tail_exec if txt and not txt.startswith(("/*", "*"))]
        if tail_non_empty:
            t_start = tail_non_empty[0][0]
            t_calls: List[str] = []
            t_loops: List[int] = []
            t_bs: List[Dict[str, Any]] = []
            for lno, txt in tail_non_empty:
                if re.search(r"\b(?:for|while|repeat)\b", txt):
                    t_loops.append(lno)
                for cm in _CALL_TOKEN_RE.finditer(txt):
                    tok = cm.group(1)
                    if tok not in _NON_CALL_KEYWORDS:
                        t_calls.append(tok)
                if _DYN_EVAL_RE.search(txt):
                    t_bs.append({
                        "kind": "dynamic_callback",
                        "marker": "⋯?",
                        "file": rel_posix,
                        "symbol": f"script_{fpath.stem}",
                        "line": lno,
                        "expr": txt[:80],
                    })
            sym = f"script_{fpath.stem}"
            units.append({
                "id": f"{rel_posix}:{sym}",
                "file": rel_posix,
                "symbol": sym,
                "short_name": sym,
                "start_line": t_start,
                "end_line": n_lines,
                "args": ["argv"],
                "return_type": "",
                "docstring": f"Top-level script entrypoint in {rel_posix}",
                "calls": list(dict.fromkeys(t_calls)),
                "has_loop": len(t_loops) > 0,
                "loop_lines": t_loops,
                "dynamic_blind_spots": t_bs,
                "outputs": ["script_state"],
                "kind": "emit",
            })
            has_top_entry = True
    else:
        b1 = max(1, n_lines // 3)
        b2 = max(b1 + 1, (2 * n_lines) // 3) if n_lines >= 3 else n_lines
        spans = [
            (1, b1, "ingest", "script_ingest"),
            (min(n_lines, b1 + 1), b2, "compute", "script_compute"),
            (min(n_lines, b2 + 1), n_lines, "emit", "script_emit"),
        ]
        for s_ln, e_ln, knd, sym in spans:
            units.append({
                "id": f"{rel_posix}:{sym}",
                "file": rel_posix,
                "symbol": sym,
                "short_name": sym,
                "start_line": s_ln,
                "end_line": max(s_ln, e_ln),
                "args": ["argv"],
                "return_type": "",
                "docstring": f"Top-level {knd} block in {rel_posix}",
                "calls": [],
                "has_loop": any(bool(re.search(r"\b(?:for|while|repeat)\b", _strip_line_comment(ln, is_r))) for ln in lines) if knd == "compute" else False,
                "loop_lines": [],
                "dynamic_blind_spots": [],
                "outputs": [f"{knd}_state"],
                "kind": knd,
            })
        has_top_entry = True

    return units, has_top_entry


_ARTIFACT_LITERAL_RE = re.compile(
    r"""['"]([^'"\n]{2,120}\.(?:csv|tsv|parquet|feather|rds|rda|npz|npy|pt|pth|pkl|json|jsonl|tex|pdf|png))['"]""",
    re.IGNORECASE,
)
_WORKFLOW_SCRIPT_TOKEN_RE = re.compile(
    r"""([A-Za-z0-9_./-]+\.(?:py|R|r|js|mjs|ts))\b"""
)


def _compute_topological_file_order(
    root: Optional[Path],
    files: Sequence[str],
    units: Sequence[Dict[str, Any]],
    *,
    paper_path: Optional[Path] = None,
) -> Tuple[Dict[str, int], List[Tuple[str, str, str]], Dict[str, int]]:
    """Derive repository-agnostic topological file rank + artifact edges + manifest step order from:
    1. Shell/Make/REPLICATION orchestration step order (`workflow.sh`, `*.sh`, `Makefile`, `REPLICATION.md`),
    2. File-artifact producer -> consumer edges (`write_csv`/`save` -> `read_csv`/`load`), and
    3. Static call/import dependency edges.
    """
    unique_files = list(dict.fromkeys(files))
    if root is None or not root.is_dir() or len(unique_files) <= 1:
        return ({f: idx for idx, f in enumerate(unique_files)}, [], {})

    known_set = set(unique_files)
    by_basename: Dict[str, List[str]] = {}
    stem_to_rels: Dict[str, List[str]] = {}
    for f in unique_files:
        by_basename.setdefault(Path(f).name, []).append(f)
        stem_to_rels.setdefault(Path(f).stem, []).append(f)

    # 1. Orchestration step order from workflow.sh / Makefile / REPLICATION.md (repo_root + paper_path project root)
    manifest_step: Dict[str, int] = {}
    step_counter = 0
    _, wf_invocations, _ = _parse_workflow_manifests(root, known_set, stem_to_rels, paper_path=paper_path)
    for inv in wf_invocations:
        ep_rel = str(inv.get("entrypoint") or "")
        if ep_rel in known_set and ep_rel not in manifest_step:
            manifest_step[ep_rel] = step_counter
            step_counter += 1

    if not manifest_step:
        manifest_candidates: List[Path] = []
        seen_mc: Set[Path] = set()
        for base in _collect_manifest_search_bases(root, paper_path):
            for cand_name in WORKFLOW_MANIFEST_NAMES:
                cp = base / cand_name
                if cp.is_file() and not _is_link_or_junction(cp) and cp.resolve() not in seen_mc:
                    seen_mc.add(cp.resolve())
                    manifest_candidates.append(cp)
        if not manifest_candidates:
            for sh_p in sorted(root.glob("*.sh"))[:4]:
                if sh_p.is_file() and not _is_link_or_junction(sh_p):
                    manifest_candidates.append(sh_p)

        for mp in manifest_candidates:
            try:
                m_txt = mp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for raw_ln in m_txt.splitlines():
                clean_ln = raw_ln.split("#", 1)[0].strip()
                if not clean_ln or re.match(r"^(?:echo|printf)\b", clean_ln):
                    continue
                for m_tok in _WORKFLOW_SCRIPT_TOKEN_RE.finditer(clean_ln):
                    cand_rel = _strip_leading_dot_slash(m_tok.group(1).replace("\\", "/")).lstrip("/")
                    matched_rel = cand_rel if cand_rel in known_set else None
                    if matched_rel is None:
                        b_matches = by_basename.get(Path(cand_rel).name) or []
                        if len(b_matches) == 1:
                            matched_rel = b_matches[0]
                    if matched_rel and matched_rel not in manifest_step:
                        manifest_step[matched_rel] = step_counter
                        step_counter += 1

    # Propagate manifest step order to child scripts directly orchestrated by manifest scripts (e.g. prepare_data.py -> prep/*.R/*.py)
    if manifest_step:
        expanded_steps: Dict[str, int] = {}
        ordered_eps = sorted(manifest_step.items(), key=lambda kv: kv[1])
        seq_idx = 0
        for ep_f, _orig_s in ordered_eps:
            if ep_f not in expanded_steps:
                expanded_steps[ep_f] = seq_idx
                seq_idx += 1
            ep_abs = root / ep_f
            if ep_abs.suffix == ".py" and ep_abs.is_file():
                try:
                    ep_src = ep_abs.read_text(encoding="utf-8-sig", errors="replace")
                except OSError:
                    ep_src = ""
                ep_tree = _parse_python_ast_quiet(ep_src, filename=ep_f)
                if ep_tree is not None and any(k in ep_src for k in ("subprocess", "Rscript", "sys.executable")):
                    for cnode in ast.walk(ep_tree):
                        if isinstance(cnode, ast.Constant) and isinstance(cnode.value, str):
                            slit = cnode.value.strip()
                            if re.fullmatch(r"[A-Za-z0-9_./\\-]+\.(?:py|R|r)", slit):
                                ns = _strip_leading_dot_slash(slit.replace("\\", "/"))
                                child_cands = [
                                    ns,
                                    _strip_leading_dot_slash((Path(ep_f).parent / ns).as_posix()),
                                    _strip_leading_dot_slash((Path(ep_f).parent / "prep" / ns).as_posix()),
                                ]
                                child_hit = next((c for c in child_cands if c in known_set and c != ep_f), None)
                                if child_hit is None and "/" not in ns:
                                    b_hits = by_basename.get(Path(ns).name) or []
                                    if len(b_hits) == 1 and b_hits[0] != ep_f:
                                        child_hit = b_hits[0]
                                if child_hit and child_hit not in manifest_step and child_hit not in expanded_steps:
                                    expanded_steps[child_hit] = seq_idx
                                    seq_idx += 1
        manifest_step = expanded_steps

    # 2. File-artifact producer -> consumer edges (keyed by normalized path, with unique-basename fallback)
    producers_by_artifact: Dict[str, List[str]] = {}
    consumers_by_artifact: Dict[str, List[str]] = {}
    write_hint_re = re.compile(
        r"(?<!\.)\b(?:write|write_csv|write_parquet|save|savez|savetxt|to_csv|to_parquet|to_pickle|to_json|"
        r"dump|savefig|ggsave|write_text|write_bytes|writeLines|saveRDS|fwrite|sink)\b|"
        r"(?<![.\w])cat\s*\(|open\([^)]*['\"][wa]['\"]",
        re.IGNORECASE,
    )
    read_hint_re = re.compile(
        r"(?<!\.)\b(?:read|load|loadtxt|from_csv|read_csv|read_parquet|read_json|read_pickle|read_excel|"
        r"read_rds|read_text|read_bytes|readLines|readRDS|fread)\b|"
        r"open\([^)]*['\"]r['\"]",
        re.IGNORECASE,
    )

    def _norm_art_path(raw_a: str) -> str:
        cleaned = _strip_leading_dot_slash(raw_a.strip().replace("\\", "/")).lstrip("/")
        return os.path.normpath(cleaned).replace("\\", "/").lower() if cleaned else ""

    for f_rel in unique_files:
        fp = root / f_rel
        try:
            txt = fp.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for ln in txt.splitlines():
            s_ln = ln.strip()
            if not s_ln or s_ln.startswith(("#", "//", "%")):
                continue
            art_hits = _ARTIFACT_LITERAL_RE.findall(s_ln)
            if not art_hits:
                continue
            is_w = bool(write_hint_re.search(s_ln))
            is_r = bool(read_hint_re.search(s_ln))
            for raw_art in art_hits:
                art_key = _norm_art_path(raw_art)
                if len(Path(art_key).name) < 4:
                    continue
                if is_w and not is_r:
                    producers_by_artifact.setdefault(art_key, []).append(f_rel)
                elif is_r and not is_w:
                    consumers_by_artifact.setdefault(art_key, []).append(f_rel)

    # Allow basename matching ONLY when that basename is unambiguous across all observed artifact paths
    all_art_keys = set(producers_by_artifact.keys()) | set(consumers_by_artifact.keys())
    art_keys_by_base: Dict[str, Set[str]] = {}
    for ak in all_art_keys:
        art_keys_by_base.setdefault(Path(ak).name, set()).add(ak)

    dag_adj: Dict[str, Set[str]] = {f: set() for f in unique_files}
    indegree: Dict[str, int] = {f: 0 for f in unique_files}
    artifact_edges: List[Tuple[str, str, str]] = []
    seen_art_edges: Set[Tuple[str, str, str]] = set()

    def _add_edge(u_f: str, v_f: str) -> bool:
        if u_f != v_f and v_f not in dag_adj[u_f]:
            # Avoid creating cycles against explicit workflow step order
            if u_f in manifest_step and v_f in manifest_step and manifest_step[u_f] > manifest_step[v_f]:
                return False
            # Avoid creating 2-cycles or transitive back-edges
            visit_q = [v_f]
            seen_v: Set[str] = set()
            while visit_q:
                cur_n = visit_q.pop()
                if cur_n == u_f:
                    return False
                if cur_n in seen_v:
                    continue
                seen_v.add(cur_n)
                visit_q.extend(dag_adj.get(cur_n, ()))
            dag_adj[u_f].add(v_f)
            indegree[v_f] += 1
            return True
        return False

    # Explicit workflow order edges between consecutive orchestrated scripts
    ordered_manifest_files = [f for f, _s in sorted(manifest_step.items(), key=lambda kv: kv[1])]
    for i in range(len(ordered_manifest_files) - 1):
        _add_edge(ordered_manifest_files[i], ordered_manifest_files[i + 1])

    for art_key, prods in sorted(producers_by_artifact.items()):
        c_list = list(consumers_by_artifact.get(art_key) or [])
        base_nm = Path(art_key).name
        sib_keys = art_keys_by_base.get(base_nm, set())
        # Link `<dir>/<file>` producer to `<file>` consumer only when basename has <=1 directory-qualified key
        dir_keys = [k for k in sib_keys if "/" in k]
        if not c_list and len(dir_keys) <= 1:
            for sk in sorted(sib_keys):
                if sk != art_key:
                    c_list.extend(consumers_by_artifact.get(sk) or [])
        for p_f in dict.fromkeys(prods):
            for c_f in dict.fromkeys(c_list):
                if p_f != c_f and _add_edge(p_f, c_f):
                    edge_tup = (p_f, c_f, art_key)
                    if edge_tup not in seen_art_edges:
                        seen_art_edges.add(edge_tup)
                        artifact_edges.append(edge_tup)

    # Static symbol call edges (unambiguous symbols only)
    sym_defs: Dict[str, List[str]] = {}
    for u in units:
        sym_defs.setdefault(str(u["symbol"]), []).append(str(u["file"]))
        if str(u["short_name"]) not in _AMBIGUOUS_BARE_HELPER_NAMES:
            sym_defs.setdefault(str(u["short_name"]), []).append(str(u["file"]))
    sym_to_unique_file: Dict[str, str] = {
        sym_k: f_owners[0]
        for sym_k, f_owners in sym_defs.items()
        if len(set(f_owners)) == 1
    }
    for u in units:
        src_f = str(u["file"])
        for cal in u.get("calls") or []:
            tgt_f = sym_to_unique_file.get(str(cal))
            if tgt_f and tgt_f != src_f:
                if u.get("kind") == "emit" and tgt_f not in manifest_step:
                    _add_edge(tgt_f, src_f)

    # Deterministic Kahn topological sort seeded by manifest_step then path (no arbitrary language bias)
    ready = sorted(
        [f for f in unique_files if indegree[f] == 0],
        key=lambda f: (manifest_step.get(f, 9999), f),
    )
    topo_order: List[str] = []
    while ready:
        cur = ready.pop(0)
        topo_order.append(cur)
        for nxt in sorted(dag_adj[cur]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda f: (manifest_step.get(f, 9999), f))

    if len(topo_order) < len(unique_files):
        rem = [f for f in unique_files if f not in set(topo_order)]
        rem.sort(key=lambda f: (manifest_step.get(f, 9999), f))
        topo_order.extend(rem)

    return ({f: idx for idx, f in enumerate(topo_order)}, artifact_edges, manifest_step)


def _dominant_file_stage_kind(f_rel: str, f_units: List[Dict[str, Any]]) -> str:
    kinds = [str(u.get("kind") or "compute") for u in f_units]
    rel_low = f_rel.lower()
    stem_low = Path(rel_low).stem
    stem_tokens = set(_tokenize_stage_ident(stem_low))
    dir_tokens = {tok for seg in Path(rel_low).parts[:-1] for tok in _tokenize_stage_ident(seg)}

    # 1. Data preparation / extraction / ingestion scripts take priority over simulation/compute folders
    if (
        (dir_tokens & INGEST_DIR_TOKENS)
        or ((stem_tokens & INGEST_FILE_TOKENS) and "feature" not in stem_tokens)
        or stem_low.startswith(("prepare_", "prep_", "extract_", "ingest_", "convert_", "reconstruct_", "data_util"))
    ):
        return "ingest"

    # 2. Table / figure / plot / report / consistency-check scripts classify as emit (even under Simulation/)
    if (stem_tokens & EMIT_FILE_TOKENS) or stem_low.startswith(EMIT_STEM_PREFIXES):
        return "emit"

    # 3. Monte Carlo / synthetic DGP / simulation study scripts
    is_sim_file = bool(
        (dir_tokens & SIMULATION_DIR_TOKENS)
        or any(tok.startswith(SIMULATION_STEM_PREFIXES) for tok in stem_tokens)
    )
    if is_sim_file or (kinds and kinds.count("simulation") * 2 >= len(kinds)):
        return "simulation"

    if all(str(u.get("symbol") or "").startswith("script_") for u in f_units):
        return _classify_unit_kind(
            Path(f_rel).stem,
            "",
            any(bool(u.get("has_loop")) for u in f_units),
            [],
            rel_posix=f_rel,
        )
    counts = {k: kinds.count(k) for k in set(kinds)}
    n = max(1, len(kinds))
    if counts.get("ingest", 0) * 2 >= n and counts.get("loop", 0) == 0:
        return "ingest"
    if counts.get("emit", 0) * 2 >= n and counts.get("loop", 0) == 0:
        return "emit"
    if counts.get("loop", 0) > 0:
        return "loop"
    return "compute"


def _select_merged_stage_kind(
    k_a: str,
    members_a: List[Dict[str, Any]],
    k_b: str,
    members_b: List[Dict[str, Any]],
    *,
    has_later_non_emit: bool = False,
) -> str:
    """Select member-weighted dominant stage kind when merging two adjacent topological groups."""
    if k_a == k_b:
        return k_a
    combined = members_a + members_b
    pair = {k_a, k_b}
    if "simulation" in pair and "ingest" not in pair and "emit" not in pair:
        sim_cnt = sum(1 for u in combined if u.get("kind") == "simulation") + (
            len(members_a) if k_a == "simulation" else len(members_b)
        )
        if sim_cnt >= max(1, len(combined) // 3):
            return "simulation"
    if pair <= {"compute", "loop"}:
        loop_cnt = sum(1 for u in combined if u.get("kind") == "loop" or u.get("has_loop"))
        comp_cnt = len(combined) - loop_cnt
        return "loop" if loop_cnt >= max(1, comp_cnt // 2) else "compute"
    if has_later_non_emit and "emit" in pair:
        return k_b if k_a == "emit" else k_a
    return k_a if len(members_a) >= len(members_b) else k_b


def _partition_into_macro_stages(
    units: List[Dict[str, Any]],
    *,
    root: Optional[Path] = None,
    paper_path: Optional[Path] = None,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Deterministically group AST units into 3-5 topological macro execution stages (`S1..Sk`)."""
    if not units:
        return []

    file_topo_rank, art_edges, manifest_step = _compute_topological_file_order(
        root, [str(u["file"]) for u in units], units, paper_path=paper_path
    )

    # When an explicit shell/Make workflow orchestrates >=2 repository scripts, partition
    # topologically along the workflow's execution order rather than scattering files by kind.
    if len(manifest_step) >= 2 and len(units) >= 3:
        units_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for u in units:
            units_by_file.setdefault(str(u["file"]), []).append(u)
        for f_list in units_by_file.values():
            f_list.sort(key=lambda u: int(u.get("start_line", 1)))

        file_kinds: Dict[str, str] = {
            f_rel: _dominant_file_stage_kind(f_rel, f_list)
            for f_rel, f_list in units_by_file.items()
        }

        # Build intra-repo import graph & unambiguous cross-file symbol resolution (never bare 'main'/'run')
        import_adj: Dict[str, List[str]] = {}
        if root is not None and root.is_dir():
            existing_fps = [root / f_rel for f_rel in sorted(units_by_file.keys()) if (root / f_rel).is_file()]
            if existing_fps:
                import_adj, _ = _build_repo_import_graph(root, existing_fps)

        defs_by_sym: Dict[str, Set[str]] = {}
        for f_rel, f_list in units_by_file.items():
            for u in f_list:
                defs_by_sym.setdefault(str(u["symbol"]), set()).add(f_rel)
                if str(u["short_name"]) not in _AMBIGUOUS_BARE_HELPER_NAMES:
                    defs_by_sym.setdefault(str(u["short_name"]), set()).add(f_rel)

        helper_msteps: Dict[str, List[int]] = {}
        for m_file, m_idx in manifest_step.items():
            m_imports = set(import_adj.get(m_file) or [])
            for imp_f in m_imports:
                if imp_f != m_file:
                    helper_msteps.setdefault(imp_f, []).append(m_idx)
            for u in units_by_file.get(m_file, []):
                for cal in u.get("calls") or []:
                    cal_s = str(cal)
                    if cal_s in _AMBIGUOUS_BARE_HELPER_NAMES:
                        continue
                    owners = defs_by_sym.get(cal_s) or set()
                    imp_owners = owners & m_imports
                    resolved_f: Optional[str] = None
                    if len(imp_owners) == 1:
                        resolved_f = next(iter(imp_owners))
                    elif len(owners) == 1:
                        cand_owner = next(iter(owners))
                        if cand_owner != m_file:
                            resolved_f = cand_owner
                    if resolved_f and resolved_f != m_file:
                        helper_msteps.setdefault(resolved_f, []).append(m_idx)

        # Propagate helper steps transitively 1 hop across library imports (e.g. trainer -> mixture_core -> neural_head)
        for lib_f, l_steps in list(helper_msteps.items()):
            min_ls = min(l_steps)
            for sub_imp in import_adj.get(lib_f) or []:
                if sub_imp not in manifest_step and sub_imp != lib_f:
                    helper_msteps.setdefault(sub_imp, []).append(min_ls)

        # Track non-ingest upstream producers (so root `ingest` scripts like `prep/*.R` stay in S1 Ingest)
        # and strict module/specific-artifact consumers (so terminal `emit` scripts like `summarize_*`, `check_*`, `plot_*` stay in final Emit).
        generic_art_stems = {"summary", "results", "metrics", "output", "config", "status", "report"}
        non_ingest_upstream_by_cons: Dict[str, Set[str]] = {}
        non_emit_consumers_by_prod: Dict[str, Set[str]] = {}
        for p_f, c_f, art_k in art_edges:
            if file_kinds.get(p_f) != "ingest":
                non_ingest_upstream_by_cons.setdefault(c_f, set()).add(p_f)
            if file_kinds.get(c_f) != "emit" and ("/" in art_k or Path(art_k).stem not in generic_art_stems):
                non_emit_consumers_by_prod.setdefault(p_f, set()).add(c_f)

        # True module-level imports (excluding subprocess string-literal script invocations)
        if root is not None and root.is_dir():
            known_unit_files = set(units_by_file.keys())
            stem_unit_map: Dict[str, List[str]] = {}
            for uf in known_unit_files:
                stem_unit_map.setdefault(Path(uf).stem, []).append(uf)
            for caller_f in sorted(known_unit_files):
                if file_kinds.get(caller_f) == "emit" or not caller_f.endswith(".py"):
                    continue
                fp_c = root / caller_f
                if not fp_c.is_file():
                    continue
                try:
                    c_tree = _parse_python_ast_quiet(fp_c.read_text(encoding="utf-8-sig", errors="replace"), filename=caller_f)
                except OSError:
                    c_tree = None
                if c_tree is None:
                    continue
                imp_mods: Set[str] = set()
                for n_imp in ast.walk(c_tree):
                    if isinstance(n_imp, ast.Import):
                        for al in n_imp.names:
                            imp_mods.add(al.name.split(".")[-1])
                    elif isinstance(n_imp, ast.ImportFrom) and n_imp.module:
                        imp_mods.add(n_imp.module.split(".")[-1])
                for m_st in imp_mods:
                    for cand_imp in stem_unit_map.get(m_st, ()):
                        if cand_imp != caller_f:
                            non_emit_consumers_by_prod.setdefault(cand_imp, set()).add(caller_f)

        max_m_step = max(manifest_step.values()) + 1
        min_non_ingest_step = min(
            (s + 1 for f, s in manifest_step.items() if file_kinds.get(f) != "ingest"),
            default=1,
        )

        def _effective_step(f_rel: str) -> Tuple[float, int, str]:
            fk = file_kinds[f_rel]
            is_root_ingest = (fk == "ingest") and not bool(non_ingest_upstream_by_cons.get(f_rel))
            explicit_emit_script = Path(f_rel.lower()).stem.startswith(EMIT_STEM_PREFIXES)
            is_terminal_emit = (fk == "emit") and (
                not bool(non_emit_consumers_by_prod.get(f_rel)) or explicit_emit_script
            )
            if is_root_ingest:
                ord_tie = float(manifest_step.get(f_rel, 50)) * 0.001
                return (ord_tie, file_topo_rank.get(f_rel, 9999), f_rel)
            if f_rel in manifest_step:
                raw_pos = float(manifest_step[f_rel]) + 1.0
                if is_terminal_emit:
                    return (float(max_m_step) + 1.0 + raw_pos * 0.01, file_topo_rank.get(f_rel, 9999), f_rel)
                return (raw_pos, file_topo_rank.get(f_rel, 9999), f_rel)
            if is_terminal_emit:
                return (float(max_m_step) + 2.0, file_topo_rank.get(f_rel, 9999), f_rel)
            ref_steps = [s + 1 for s in (helper_msteps.get(f_rel) or [])]
            if ref_steps:
                earliest = float(min(ref_steps))
                if fk == "ingest":
                    return (max(0.0, earliest - 0.25), file_topo_rank.get(f_rel, 9999), f_rel)
                floor_pos = float(min_non_ingest_step) - 0.15
                return (max(floor_pos, earliest - 0.15), file_topo_rank.get(f_rel, 9999), f_rel)
            if fk == "ingest":
                fallback_pos = 0.05
            elif fk == "simulation":
                fallback_pos = float(max_m_step) + 0.25
            else:
                fallback_pos = max(float(min_non_ingest_step), float(max_m_step) * 0.5)
            return (fallback_pos, file_topo_rank.get(f_rel, 9999), f_rel)

        topo_files = sorted(units_by_file.keys(), key=_effective_step)
        topo_groups: List[Tuple[str, List[Dict[str, Any]]]] = []
        for f_rel in topo_files:
            fk = file_kinds[f_rel]
            if topo_groups and topo_groups[-1][0] == fk:
                topo_groups[-1] = (fk, topo_groups[-1][1] + units_by_file[f_rel])
            else:
                topo_groups.append((fk, list(units_by_file[f_rel])))

        while len(topo_groups) < 3:
            idx = max(range(len(topo_groups)), key=lambda i: len(topo_groups[i][1]))
            knd, members = topo_groups[idx]
            if len(members) >= 2:
                mid = len(members) // 2
                topo_groups[idx:idx + 1] = [(knd, members[:mid]), (knd, members[mid:])]
            else:
                break

        def _is_forbidden_merge(k_a: str, k_b: str, pos_i: int, total_g: int) -> bool:
            pair = {k_a, k_b}
            if pair == {"ingest", "simulation"} or pair == {"ingest", "emit"}:
                return True
            if k_a == "emit" and k_b in ("compute", "loop", "simulation"):
                return True
            if pos_i == 0 and k_a == "ingest" and k_b != "ingest":
                return True
            if pos_i + 1 == total_g - 1 and k_b == "emit" and k_a != "emit":
                return True
            return False

        while len(topo_groups) > 5:
            merge_idx = -1
            n_grp = len(topo_groups)
            # Pass 1: identical adjacent kinds
            for cand_i in range(n_grp - 1):
                if topo_groups[cand_i][0] == topo_groups[cand_i + 1][0]:
                    merge_idx = cand_i
                    break
            # Pass 2: adjacent compute/loop stages (smallest combined size first)
            if merge_idx < 0:
                comp_loop_cands = [
                    cand_i
                    for cand_i in range(n_grp - 1)
                    if {topo_groups[cand_i][0], topo_groups[cand_i + 1][0]} <= {"compute", "loop"}
                ]
                if comp_loop_cands:
                    merge_idx = min(
                        comp_loop_cands,
                        key=lambda ci: len(topo_groups[ci][1]) + len(topo_groups[ci + 1][1]),
                    )
            # Pass 3: any non-forbidden middle pair excluding simulation if possible
            if merge_idx < 0:
                safe_no_sim = [
                    cand_i
                    for cand_i in range(n_grp - 1)
                    if not _is_forbidden_merge(topo_groups[cand_i][0], topo_groups[cand_i + 1][0], cand_i, n_grp)
                    and "simulation" not in (topo_groups[cand_i][0], topo_groups[cand_i + 1][0])
                ]
                if safe_no_sim:
                    merge_idx = min(
                        safe_no_sim,
                        key=lambda ci: len(topo_groups[ci][1]) + len(topo_groups[ci + 1][1]),
                    )
            # Pass 4: any non-forbidden middle pair (e.g. compute + simulation, never ingest + simulation or emit -> compute)
            if merge_idx < 0:
                safe_any = [
                    cand_i
                    for cand_i in range(n_grp - 1)
                    if not _is_forbidden_merge(topo_groups[cand_i][0], topo_groups[cand_i + 1][0], cand_i, n_grp)
                ]
                if safe_any:
                    merge_idx = min(
                        safe_any,
                        key=lambda ci: len(topo_groups[ci][1]) + len(topo_groups[ci + 1][1]),
                    )
            # Pass 5: fallback preserving pure S1 ingest and final emit when possible
            if merge_idx < 0:
                fallback_cands = [
                    ci for ci in range(n_grp - 1)
                    if {topo_groups[ci][0], topo_groups[ci + 1][0]} != {"ingest", "simulation"}
                    and not (topo_groups[ci][0] == "emit" and topo_groups[ci + 1][0] in ("compute", "loop", "simulation"))
                ]
                merge_idx = fallback_cands[0] if fallback_cands else max(0, n_grp - 2)

            k_left, m_left = topo_groups[merge_idx]
            k_right, m_right = topo_groups[merge_idx + 1]
            has_later_work = any(
                topo_groups[j][0] in ("compute", "loop", "simulation")
                for j in range(merge_idx + 2, n_grp)
            )
            keep_k = _select_merged_stage_kind(
                k_left, m_left, k_right, m_right, has_later_non_emit=has_later_work
            )
            topo_groups[merge_idx] = (keep_k, m_left + m_right)
            topo_groups.pop(merge_idx + 1)

        return topo_groups

    rank_map = {"ingest": 0, "simulation": 1, "loop": 2, "compute": 3, "emit": 4}
    ordered = sorted(
        units,
        key=lambda u: (
            rank_map.get(str(u["kind"]), 3),
            file_topo_rank.get(str(u["file"]), 9999),
            u["file"],
            u["start_line"],
        ),
    )

    if len(ordered) == 1:
        u = ordered[0]
        s, e = u["start_line"], u["end_line"]
        mid1 = s + max(0, (e - s) // 3)
        mid2 = s + max(0, (2 * (e - s)) // 3)
        u_in = {**u, "id": f"{u['id']}#ingest", "kind": "ingest", "end_line": mid1}
        u_co = {**u, "id": f"{u['id']}#compute", "kind": "loop" if u["has_loop"] else "compute", "start_line": mid1, "end_line": mid2}
        u_em = {**u, "id": f"{u['id']}#emit", "kind": "emit", "start_line": mid2}
        return [("ingest", [u_in]), (u_co["kind"], [u_co]), ("emit", [u_em])]

    if len(ordered) == 2:
        u0, u1 = ordered[0], ordered[1]
        mid = (u0["start_line"] + u0["end_line"]) // 2
        u0_a = {**u0, "id": f"{u0['id']}#setup", "kind": "ingest", "end_line": mid}
        u0_b = {**u0, "id": f"{u0['id']}#core", "start_line": mid}
        return [("ingest", [u0_a]), (u0_b["kind"], [u0_b]), ("emit" if u1["kind"] == "emit" else "compute", [u1])]

    by_kind: Dict[str, List[Dict[str, Any]]] = {"ingest": [], "simulation": [], "loop": [], "compute": [], "emit": []}
    for u in ordered:
        by_kind.setdefault(str(u["kind"]), []).append(u)

    groups: List[Tuple[str, List[Dict[str, Any]]]] = []
    if by_kind["ingest"]:
        groups.append(("ingest", by_kind["ingest"]))
    if by_kind["simulation"]:
        groups.append(("simulation", by_kind["simulation"]))
    if by_kind["loop"]:
        groups.append(("loop", by_kind["loop"]))
    if by_kind["compute"]:
        comp = by_kind["compute"]
        with_bs = [u for u in comp if u["dynamic_blind_spots"]]
        without_bs = [u for u in comp if not u["dynamic_blind_spots"]]
        rem_slots = 1 if by_kind["emit"] else 0
        if with_bs and without_bs and len(groups) + rem_slots <= 3:
            groups.append(("compute", with_bs))
            groups.append(("compute", without_bs))
        elif len(comp) >= 2 and (len(groups) + rem_slots < 3):
            half = len(comp) // 2
            groups.append(("compute", comp[:half]))
            groups.append(("compute", comp[half:]))
        else:
            groups.append(("compute", comp))
    if by_kind["emit"]:
        groups.append(("emit", by_kind["emit"]))

    while len(groups) < 3:
        idx = max(range(len(groups)), key=lambda i: len(groups[i][1]))
        knd, members = groups[idx]
        if len(members) >= 2:
            mid = len(members) // 2
            groups[idx:idx + 1] = [(knd, members[:mid]), (knd, members[mid:])]
        else:
            break

    while len(groups) > 5:
        # Preserve simulation and emit stages distinct when merging down to <=5 macro stages
        merge_idx = len(groups) - 2
        for cand_i in range(len(groups) - 1):
            if groups[cand_i][0] not in ("simulation", "ingest") and groups[cand_i + 1][0] != "emit":
                merge_idx = cand_i
                break
        groups[merge_idx] = (groups[merge_idx][0], groups[merge_idx][1] + groups[merge_idx + 1][1])
        groups.pop(merge_idx + 1)

    return groups


MAX_SCOPED_STAGE_UNITS = 35


def _partition_scoped_pipeline_stages(
    units: List[Dict[str, Any]],
    scope_summary: Dict[str, Any],
    *,
    root: Optional[Path] = None,
    paper_path: Optional[Path] = None,
) -> List[Tuple[str, List[Dict[str, Any]], str, str, List[str]]]:
    """Partition `units` into workflow/manuscript-pipeline-driven L1 macro stages
    `(kind, members, custom_title, pipeline_id, manuscript_targets)` when `scoped=True`,
    preventing >50-function generic 'Iterative Loop: ...' stage buckets.
    """
    if not units:
        return []

    units_by_file: Dict[str, List[Dict[str, Any]]] = {}
    for u in units:
        units_by_file.setdefault(str(u["file"]), []).append(u)
    for flist in units_by_file.values():
        flist.sort(key=lambda u: int(u.get("start_line", 1)))

    file_kinds: Dict[str, str] = {
        f_rel: _dominant_file_stage_kind(f_rel, flist)
        for f_rel, flist in units_by_file.items()
    }
    topo_rank, _, _ = _compute_topological_file_order(
        root, list(units_by_file.keys()), units, paper_path=paper_path
    )

    avail_pipes = list(scope_summary.get("available_pipelines") or [])
    active_pid = str(scope_summary.get("active_pipeline") or "")
    active_pipes = (
        [p for p in avail_pipes if p.get("id") == active_pid]
        if active_pid and active_pid not in ("all_paper_matched", "unscoped", "all")
        else avail_pipes
    )
    wf_steps = list(scope_summary.get("workflow_steps") or [])
    if active_pid and active_pid not in ("all_paper_matched", "unscoped", "all"):
        wf_steps = [ws for ws in wf_steps if ws.get("pipeline_id") == active_pid] or wf_steps

    ep_step_map: Dict[str, Dict[str, Any]] = {
        str(ws["entrypoint"]): ws for ws in wf_steps if ws.get("entrypoint")
    }
    pipes_for_file: Dict[str, List[Dict[str, Any]]] = {f_rel: [] for f_rel in units_by_file}
    for p in active_pipes:
        for pf in p.get("files") or []:
            if pf in pipes_for_file:
                pipes_for_file[pf].append(p)

    all_eps: Set[str] = {
        ep
        for p in active_pipes
        for ep in (p.get("entrypoints") or [])
    } | set(ep_step_map.keys())

    # Group files into ordered semantic buckets preserving workflow.sh step order when present:
    raw_buckets: Dict[Tuple[int, str], Dict[str, Any]] = {}
    pipe_min_wf_step: Dict[str, int] = {}
    for ws in wf_steps:
        wpid = str(ws.get("pipeline_id") or "")
        widx = int(ws.get("step_index", 99))
        if wpid and (wpid not in pipe_min_wf_step or widx < pipe_min_wf_step[wpid]):
            pipe_min_wf_step[wpid] = widx
    pipe_rank_map = {
        str(p["id"]): (2 + pipe_min_wf_step[str(p["id"])] if str(p["id"]) in pipe_min_wf_step else 20 + idx)
        for idx, p in enumerate(active_pipes)
    }

    for f_rel in sorted(units_by_file.keys(), key=lambda f: (topo_rank.get(f, 9999), f)):
        fk = file_kinds[f_rel]
        f_pipes = pipes_for_file.get(f_rel) or []
        is_ep = f_rel in all_eps

        if fk == "ingest" and not is_ep:
            bkey = (0, "data_preparation")
            btitle = "Data Preparation & Input Covariates"
            bkind = "ingest"
            btgts: List[str] = []
        elif not is_ep and len(f_pipes) >= 2:
            rel_parts_low = [pt.lower() for pt in Path(f_rel).parts[:-1]]
            stem_tok_set = set(_tokenize_stage_ident(Path(f_rel).stem.lower()))
            if any(k in rel_parts_low or k in stem_tok_set for k in ("data", "datasets", "dataset", "loader", "covariates")):
                bkey = (0, "data_preparation")
                btitle = "Data Preparation & Input Covariates"
                bkind = "ingest"
            elif any(k in rel_parts_low or k in stem_tok_set for k in ("inference", "vi", "mcmc", "nuts", "sampler", "train", "optim", "fit", "solver")):
                bkey = (1, "posterior_estimation")
                btitle = "Variational & Posterior Estimation"
                bkind = "compute"
            else:
                bkey = (1, "core_model_architecture")
                btitle = "Shared Model & Likelihood Architecture"
                bkind = "compute"
            btgts = []
        elif f_rel in ep_step_map and len(wf_steps) >= 2 and len(active_pipes) <= 2:
            ws = ep_step_map[f_rel]
            s_ord = 2 + int(ws.get("step_index", 0))
            ws_pid = str(ws.get("pipeline_id") or Path(f_rel).stem)
            ws_title = str(ws.get("title") or ws.get("pipeline_title") or Path(f_rel).stem.replace("_", " ").title())
            btgts = list(ws.get("manuscript_targets") or [])
            if btgts and not any(t.split("/")[-1] in ws_title for t in btgts[:1]):
                ws_title = f"{ws_title} ({Path(btgts[0]).name})"
            bkey = (s_ord, f"step_{f_rel}")
            btitle = ws_title
            bkind = "simulation" if ws_pid == "simulations" or fk == "simulation" else ("compute" if fk == "loop" else fk)
        elif f_pipes:
            lead_p = f_pipes[0]
            pid_s = str(lead_p["id"])
            p_ord = pipe_rank_map.get(pid_s, 10)
            p_title = str(lead_p.get("title") or pid_s.replace("_", " ").title())
            btgts = list(lead_p.get("manuscript_targets") or [])
            if btgts and len(btgts) <= 3:
                short_t = ", ".join(Path(t).name if "/" in t else t for t in btgts[:3])
                if short_t.lower() not in p_title.lower():
                    p_title = f"{p_title} ({short_t})"
            bkey = (p_ord, pid_s)
            btitle = p_title
            if pid_s == "simulations":
                bkind = "simulation"
            elif pid_s in ("predictive_tables", "verification_checks") and fk == "emit":
                bkind = "emit"
            elif fk == "simulation" and not is_ep:
                bkind = "compute"
            else:
                bkind = "compute" if fk == "loop" else fk
        elif fk == "simulation":
            bkey = (80, "simulations")
            btitle = "Monte Carlo Simulations & Synthetic DGP"
            bkind = "simulation"
            btgts = []
        elif fk == "emit" or f_rel.lower().endswith(".r"):
            bkey = (95, "output_tables_figures")
            btitle = "Table & Figure Output Rendering"
            bkind = "emit"
            btgts = []
        else:
            bkey = (50, f"module_{Path(f_rel).stem.lower()}")
            btitle = f"{Path(f_rel).stem.replace('_', ' ').title()} Estimation Stage"
            bkind = "compute"
            btgts = []

        entry = raw_buckets.setdefault(
            bkey,
            {
                "kind": bkind,
                "title": btitle,
                "pipeline_id": bkey[1],
                "targets": [],
                "files": [],
                "members": [],
            },
        )
        entry["files"].append(f_rel)
        entry["members"].extend(units_by_file[f_rel])
        for t in btgts:
            if t not in entry["targets"]:
                entry["targets"].append(t)

    ordered_entries = [v for _k, v in sorted(raw_buckets.items(), key=lambda kv: kv[0])]

    # Enforce strict <= MAX_SCOPED_STAGE_UNITS per stage so >50 functions NEVER collapse into one generic bucket!
    split_stages: List[Tuple[str, List[Dict[str, Any]], str, str, List[str]]] = []
    for ent in ordered_entries:
        members = ent["members"]
        base_title = str(ent["title"])
        bkind = str(ent["kind"])
        bpid = str(ent["pipeline_id"])
        btgts = list(ent["targets"])
        if len(members) <= MAX_SCOPED_STAGE_UNITS:
            split_stages.append((bkind, members, base_title, bpid, btgts))
            continue

        # Group by file first, then chunk oversized single files cleanly along class/function boundaries
        cur_chunk: List[Dict[str, Any]] = []
        cur_stems: List[str] = []

        def _flush_chunk(chunk_m: List[Dict[str, Any]], stems: List[str], part_num: int) -> None:
            if not chunk_m:
                return
            lead_mod = stems[0] if stems else Path(str(chunk_m[0]["file"])).stem
            lead_cls = next((str(m.get("class_name")) for m in chunk_m if m.get("class_name")), "")
            qualifier = lead_cls or lead_mod.replace("_", " ").title()
            sub_t = f"{base_title} · {qualifier}" if qualifier.lower() not in base_title.lower() else f"{base_title} (Part {part_num})"
            n_ch = len(chunk_m)
            sim_n = sum(1 for m in chunk_m if m.get("kind") == "simulation")
            ing_n = sum(1 for m in chunk_m if m.get("kind") == "ingest")
            emit_n = sum(1 for m in chunk_m if m.get("kind") == "emit")
            if bkind == "simulation" or (bkind not in ("ingest", "emit") and sim_n * 2 > n_ch):
                c_kind = "simulation"
            elif bkind == "ingest" or ing_n * 2 > n_ch:
                c_kind = "ingest"
            elif bkind == "emit" or emit_n * 2 > n_ch:
                c_kind = "emit"
            else:
                c_kind = bkind
            split_stages.append((c_kind, list(chunk_m), sub_t[:68], bpid, btgts))

        part_idx = 1
        for f_rel in ent["files"]:
            f_mems = units_by_file[f_rel]
            f_stem = Path(f_rel).stem
            if len(f_mems) > MAX_SCOPED_STAGE_UNITS:
                if cur_chunk:
                    _flush_chunk(cur_chunk, cur_stems, part_idx)
                    part_idx += 1
                    cur_chunk, cur_stems = [], []
                for start_i in range(0, len(f_mems), MAX_SCOPED_STAGE_UNITS):
                    slice_m = f_mems[start_i : start_i + MAX_SCOPED_STAGE_UNITS]
                    _flush_chunk(slice_m, [f_stem], part_idx)
                    part_idx += 1
            elif len(cur_chunk) + len(f_mems) > MAX_SCOPED_STAGE_UNITS and cur_chunk:
                _flush_chunk(cur_chunk, cur_stems, part_idx)
                part_idx += 1
                cur_chunk = list(f_mems)
                cur_stems = [f_stem]
            else:
                cur_chunk.extend(f_mems)
                if f_stem not in cur_stems:
                    cur_stems.append(f_stem)
        if cur_chunk:
            _flush_chunk(cur_chunk, cur_stems, part_idx)

    # Ensure >= 3 macro stages when >= 3 units exist
    phase_labels = ("Input & Setup", "Core Estimation", "Evaluation & Output")
    while len(split_stages) < 3 and any(len(s[1]) >= 2 for s in split_stages):
        idx = max(range(len(split_stages)), key=lambda i: len(split_stages[i][1]))
        knd, mems, ttl, pid_s, tgts = split_stages[idx]
        mid = len(mems) // 2
        left_k = "ingest" if idx == 0 and knd != "simulation" else knd
        right_k = "emit" if idx == len(split_stages) - 1 and knd != "simulation" else knd
        left_t = f"{ttl} · {phase_labels[0]}" if len(split_stages) == 1 else f"{ttl} · Setup"
        right_t = f"{ttl} · {phase_labels[1]}" if len(split_stages) == 1 else f"{ttl} · Execution"
        split_stages[idx : idx + 1] = [
            (left_k, mems[:mid], left_t[:68], pid_s, tgts),
            (right_k, mems[mid:], right_t[:68], pid_s, tgts),
        ]

    return split_stages


def _stage_short_title(stage_id: str, kind: str, members: List[Dict[str, Any]], custom_title: str = "") -> str:
    if custom_title.strip():
        clean_custom = re.sub(r"^S\d+\s*[·:-]?\s*", "", custom_title.strip())
        return f"{stage_id} · {clean_custom}"
    util_names = {"main", "cli", "sha256", "md5", "hash", "atomic", "mkdir", "log", "script_ingest", "script_compute", "script_emit"}
    chosen = next(
        (
            m for m in members
            if not str(m.get("symbol") or "").split(".")[-1].startswith("_")
            and str(m.get("short_name") or "").lower() not in util_names
            and not any(str(m.get("short_name") or "").lower().startswith(u + "_") for u in ("sha256", "atomic", "helper"))
        ),
        None,
    )
    raw_label = (
        chosen["short_name"]
        if chosen is not None
        else Path(str(members[0].get("file") or kind)).stem
    )
    lead = raw_label.replace("_", " ").replace("-", " ").strip().title()
    words = [w for w in lead.split() if w][:2]
    lead_short = " ".join(words) if words else kind.title()
    prefix_map = {
        "ingest": "Ingest",
        "simulation": "Simulation",
        "loop": "Iterative Loop",
        "compute": "Compute",
        "emit": "Emit",
    }
    tag = prefix_map.get(kind, "Stage")
    if tag.split()[0].lower() in lead_short.lower():
        return f"{stage_id} · {lead_short}"
    return f"{stage_id} · {tag}: {words[0] if words else 'Core'}"


# ---------------------------------------------------------------------------
# 4B. Anvil v6 Fixed-Scope Manifest, Pure-AST Symbol Slicer, Overwrite
#     Pruning, Scoped Equation Binding & Software Architecture Paper Map
# ---------------------------------------------------------------------------

_STDLIB_NON_REGISTRY_DECORATORS: Set[str] = {
    "staticmethod", "classmethod", "property", "dataclass", "abstractmethod",
    "lru_cache", "cache", "cached_property", "wraps", "overload", "final",
    "no_grad", "inference_mode", "contextmanager", "asynccontextmanager",
    "total_ordering",
}

_EQUATION_GENERIC_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "from", "into", "over", "under", "where",
    "given", "such", "that", "this", "each", "all", "sum", "prod", "frac",
    "left", "right", "begin", "end", "equation", "align", "aligned", "text",
    "mathrm", "mathbf", "mathcal", "mathbb", "boldsymbol", "operatorname",
    "sqrt", "exp", "log", "ln", "sin", "cos", "tan", "max", "min", "arg",
    "argmax", "argmin", "sup", "inf", "lim", "hat", "tilde", "bar", "vec",
    "dot", "ddot", "prime", "cdot", "times", "leq", "geq", "neq", "approx",
    "sim", "propto", "equiv", "quad", "qquad", "label", "tag", "nonumber",
    "self", "cls", "args", "kwargs", "none", "true", "false", "return",
    "val", "vals", "out", "res", "result", "tmp", "temp", "idx", "num",
    "arr", "vec", "mat", "obj", "item", "items", "data", "row", "rows",
}

_GREEK_TO_CODE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "alpha": ("alpha",),
    "beta": ("beta", "coef", "slope", "weights"),
    "gamma": ("gamma",),
    "delta": ("delta", "diff"),
    "epsilon": ("eps", "epsilon", "noise", "residual"),
    "varepsilon": ("eps", "epsilon", "noise", "residual"),
    "zeta": ("zeta",),
    "eta": ("eta", "step_size", "lr"),
    "theta": ("theta", "params", "param", "latent"),
    "vartheta": ("theta", "params"),
    "kappa": ("kappa",),
    "lambda": ("lam", "lambda", "lmbda", "penalty", "reg", "ridge", "weight_decay"),
    "mu": ("mu", "mean", "loc"),
    "nu": ("nu", "df"),
    "xi": ("xi",),
    "pi": ("pi", "gate", "gating", "mix", "mixing", "prior", "prob", "probs"),
    "rho": ("rho", "corr"),
    "sigma": ("sigma", "std", "scale", "var", "cov"),
    "tau": ("tau", "temp", "temperature"),
    "phi": ("phi", "variational", "flow"),
    "varphi": ("phi", "variational", "flow"),
    "chi": ("chi",),
    "psi": ("psi",),
    "omega": ("omega",),
}


def _compute_engine_content_sha256(engine_scripts_dir: Optional[str | Path] = None) -> str:
    """Compute a deterministic 64-hex SHA-256 digest over canonical Anvil engine scripts."""
    sdir = Path(engine_scripts_dir).resolve() if engine_scripts_dir is not None else Path(__file__).resolve().parent
    if not sdir.exists() or not sdir.is_dir() or _is_link_or_junction(Path(engine_scripts_dir) if engine_scripts_dir is not None else sdir):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Engine scripts directory does not exist or is a symlink/junction.",
            cwe="CWE-22",
            details={"http_status": 403},
        )
    py_files = sorted(
        p for p in sdir.iterdir()
        if p.is_file() and not _is_link_or_junction(p) and p.suffix.lower() == ".py"
    )
    if not py_files:
        raise AnvilRefusalError(
            "DEPENDENCY_MISSING",
            "No Python engine scripts found in engine_scripts_dir.",
            details={"http_status": 503},
        )
    h = hashlib.sha256()
    for fp in py_files:
        f_digest = hashlib.sha256(fp.read_bytes()).hexdigest()
        h.update(f"{fp.name}:{f_digest}\n".encode("utf-8"))
    return h.hexdigest()


def _validate_strict_contained_rel_file(
    root_resolved: Path,
    candidate: str | Path,
) -> Tuple[str, Path]:
    """Validate `candidate` as a relative path strictly inside `root_resolved` with zero `..`,
    zero absolute/rooted prefixes, and zero symlinks/junctions on any path hop.
    """
    resolved = resolve_contained_path(
        root_resolved,
        candidate,
        allow_root=False,
        must_be_relative=True,
    )
    raw_str = str(candidate).strip().replace("\\", "/")
    cur = root_resolved
    for part in Path(raw_str).parts:
        if part in ("", "."):
            continue
        cur = cur / part
        if _is_link_or_junction(cur):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Symlink or junction refused at '{part}' in '{raw_str}'.",
                cwe="CWE-22",
                details={"candidate": raw_str, "http_status": 403},
            )
    if _is_link_or_junction(resolved) or not resolved.is_file():
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Scoped file '{raw_str}' does not exist as a regular file inside repository root.",
            cwe="CWE-22",
            details={"candidate": raw_str, "http_status": 403},
        )
    return resolved.relative_to(root_resolved).as_posix(), resolved


def _hash_file_stream(fp: Path, *, max_remaining_bytes: Optional[int] = None) -> Tuple[str, int]:
    """Stream-hash `fp` in 1 MiB chunks without loading multi-hundred-MB files into memory."""
    h = hashlib.sha256()
    total = 0
    with fp.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_remaining_bytes is not None and total > max_remaining_bytes:
                raise AnvilRefusalError(
                    "BOUND_EXCEEDED_REFUSAL",
                    f"File '{fp.name}' exceeded remaining byte budget during stream read.",
                    details={"http_status": 413},
                )
            h.update(chunk)
    return h.hexdigest(), total


def _collect_allowlisted_data_manifest(
    repo_resolved: Path,
    cockpit_resolved: Optional[Path],
    data_roots: Optional[Sequence[str | Path]],
    eff_max_data_bytes: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Discover or validate contained allowlisted data directories (`data/`, `Data/`,
    `datasets/`, `Datasets/` under `repo_root` or `cockpit_root`), refuse escapes/symlinks,
    enforce `<= eff_max_data_bytes`, and return `(sorted_entries, total_bytes)`.
    """
    if eff_max_data_bytes <= 0:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_data_bytes ({eff_max_data_bytes}) must be positive.",
            details={
                "bound_name": "max_allowlisted_data_bytes",
                "bound_limit": eff_max_data_bytes,
                "observed_value": eff_max_data_bytes,
                "http_status": 413,
            },
        )

    permitted_bases: List[Tuple[str, Path]] = [("repo", repo_resolved)]
    if cockpit_resolved is not None and os.path.normcase(str(cockpit_resolved)) != os.path.normcase(str(repo_resolved)):
        permitted_bases.append(("cockpit", cockpit_resolved))

    allowlisted_set = set(ALLOWLISTED_DATA_DIR_NAMES)
    target_dirs: List[Tuple[str, str, Path]] = []
    seen_norm_dirs: Set[str] = set()

    if data_roots is not None:
        for raw_dr in data_roots:
            if raw_dr is None:
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty data_root entry refused.", cwe="CWE-22", details={"http_status": 403})
            raw_s = str(raw_dr).strip()
            if not raw_s or "\x00" in raw_s:
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty or NUL data_root refused.", cwe="CWE-22", details={"http_status": 403})
            norm_toks = raw_s.replace("\\", "/").split("/")
            if ".." in norm_toks or ".." in Path(raw_s).parts:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Parent traversal ('..') refused in data_root '{raw_s}'.",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            cand_p = Path(raw_s)
            has_root_prefix = raw_s.startswith(("/", "\\"))
            has_drive_rel = bool(cand_p.drive) and not cand_p.is_absolute()
            if has_drive_rel or (os.name == "nt" and has_root_prefix and not cand_p.is_absolute()) or cand_p.is_absolute():
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Unauthorized absolute or rooted data_root '{raw_s}' refused; contained relative allowlisted directory required.",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )

            prefix_tag = "repo"
            rel_expr = raw_s
            if ":" in raw_s and raw_s.split(":", 1)[0] in {"repo", "cockpit"}:
                prefix_tag, rel_expr = raw_s.split(":", 1)
            base_lookup = dict(permitted_bases)
            if prefix_tag not in base_lookup:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Data root '{raw_s}' references unavailable cockpit_root.",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            chosen_base = base_lookup[prefix_tag]
            rel_parts = [pt for pt in Path(rel_expr.replace("\\", "/")).parts if pt not in ("", ".")]
            if not rel_parts or rel_parts[0] not in allowlisted_set:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Data root '{raw_s}' is not an allowlisted directory ({', '.join(ALLOWLISTED_DATA_DIR_NAMES)}).",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            cur = chosen_base
            actual_parts: List[str] = []
            for pt in rel_parts:
                cur = cur / pt
                if _is_link_or_junction(cur):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink or junction data_root component '{pt}' refused.",
                        cwe="CWE-22",
                        details={"candidate": raw_s, "http_status": 403},
                    )
                if not cur.exists() or not cur.is_dir():
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Allowlisted data_root '{raw_s}' does not exist as a contained directory.",
                        cwe="CWE-22",
                        details={"candidate": raw_s, "http_status": 403},
                    )
                # Verify case-exact directory name on disk so Windows NTFS cannot alias `data` to `DATA_SECRET`
                try:
                    parent_entries = {e.name: e for e in os.scandir(cur.parent)}
                except OSError as exc:
                    raise AnvilRefusalError("BACKING_STORE_UNREADABLE", f"Cannot inspect data parent: {exc}") from exc
                if pt not in parent_entries:
                    # Case-insensitive match on Windows if exact case in allowlisted_set
                    matched_name = next((nm for nm in parent_entries if nm.lower() == pt.lower()), "")
                    if not matched_name or (len(actual_parts) == 0 and matched_name not in allowlisted_set):
                        raise AnvilRefusalError(
                            "PATH_ESCAPE_REFUSED",
                            f"Allowlisted data_root '{raw_s}' failed exact directory verification.",
                            cwe="CWE-22",
                            details={"candidate": raw_s, "http_status": 403},
                        )
                    actual_parts.append(matched_name)
                else:
                    actual_parts.append(pt)

            resolved_dp = cur.resolve()
            if not resolved_dp.is_relative_to(chosen_base):
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Data root '{raw_s}' escapes base directory.",
                    cwe="CWE-22",
                    details={"candidate": raw_s, "http_status": 403},
                )
            norm_k = os.path.normcase(str(resolved_dp))
            if norm_k not in seen_norm_dirs:
                seen_norm_dirs.add(norm_k)
                target_dirs.append((prefix_tag, "/".join(actual_parts), resolved_dp))
    else:
        for btag, bpath in permitted_bases:
            try:
                entries = sorted(os.scandir(bpath), key=lambda e: e.name)
            except OSError:
                continue
            for ent in entries:
                if ent.name not in allowlisted_set:
                    continue
                ep = Path(ent.path)
                if _is_link_or_junction(ep):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink or junction allowlisted data directory '{ent.name}' refused.",
                        cwe="CWE-22",
                        details={"candidate": ent.name, "http_status": 403},
                    )
                if not ep.is_dir():
                    continue
                resolved_dp = ep.resolve()
                if not resolved_dp.is_relative_to(bpath):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Allowlisted data directory '{ent.name}' escapes root.",
                        cwe="CWE-22",
                        details={"candidate": ent.name, "http_status": 403},
                    )
                norm_k = os.path.normcase(str(resolved_dp))
                if norm_k not in seen_norm_dirs:
                    seen_norm_dirs.add(norm_k)
                    target_dirs.append((btag, ent.name, resolved_dp))

    manifest_rows: List[Dict[str, Any]] = []
    total_bytes = 0
    for btag, rel_root_label, dpath in sorted(target_dirs, key=lambda item: (item[0], item[1])):
        for cur_root, dirs, files in os.walk(dpath, followlinks=False):
            cur_p = Path(cur_root)
            dirs.sort()
            kept_sub: List[str] = []
            for d in dirs:
                if d.startswith(".") or d == "__pycache__":
                    continue
                sub_dp = cur_p / d
                if _is_link_or_junction(sub_dp):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink or junction directory '{d}' inside allowlisted data root '{rel_root_label}' refused.",
                        cwe="CWE-22",
                        details={"candidate": f"{rel_root_label}/{d}", "http_status": 403},
                    )
                if not sub_dp.resolve().is_relative_to(dpath):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Subdirectory '{d}' escapes allowlisted data root '{rel_root_label}'.",
                        cwe="CWE-22",
                        details={"candidate": f"{rel_root_label}/{d}", "http_status": 403},
                    )
                kept_sub.append(d)
            dirs[:] = kept_sub

            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                fp = cur_p / fname
                if _is_link_or_junction(fp):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink or junction file '{fname}' inside allowlisted data root '{rel_root_label}' refused.",
                        cwe="CWE-22",
                        details={"candidate": f"{rel_root_label}/{fname}", "http_status": 403},
                    )
                resolved_fp = fp.resolve()
                if not resolved_fp.is_relative_to(dpath):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Data file '{fname}' escapes allowlisted data root '{rel_root_label}'.",
                        cwe="CWE-22",
                        details={"candidate": f"{rel_root_label}/{fname}", "http_status": 403},
                    )
                st = os.stat(resolved_fp, follow_symlinks=False)
                prospective = total_bytes + int(st.st_size)
                if prospective > eff_max_data_bytes:
                    raise AnvilRefusalError(
                        "BOUND_EXCEEDED_REFUSAL",
                        f"Allowlisted data roots total size ({prospective} bytes) exceeds 2 GB cap ({eff_max_data_bytes} bytes).",
                        details={
                            "bound_name": "max_allowlisted_data_bytes",
                            "bound_limit": eff_max_data_bytes,
                            "observed_value": prospective,
                            "offending_file": f"{rel_root_label}/{resolved_fp.relative_to(dpath).as_posix()}",
                            "http_status": 413,
                        },
                    )
                rem_budget = eff_max_data_bytes - total_bytes
                f_sha, actual_sz = _hash_file_stream(resolved_fp, max_remaining_bytes=rem_budget)
                total_bytes += actual_sz
                if total_bytes > eff_max_data_bytes:
                    raise AnvilRefusalError(
                        "BOUND_EXCEEDED_REFUSAL",
                        f"Allowlisted data roots total size ({total_bytes} bytes) exceeds 2 GB cap ({eff_max_data_bytes} bytes).",
                        details={
                            "bound_name": "max_allowlisted_data_bytes",
                            "bound_limit": eff_max_data_bytes,
                            "observed_value": total_bytes,
                            "http_status": 413,
                        },
                    )
                sub_rel = resolved_fp.relative_to(dpath).as_posix()
                manifest_rows.append({
                    "root": f"{btag}:{rel_root_label}",
                    "path": f"{rel_root_label}/{sub_rel}",
                    "sha256": f_sha,
                    "bytes": actual_sz,
                })

    manifest_rows.sort(key=lambda r: (r["root"], r["path"]))
    return manifest_rows, total_bytes


def _collect_paper_hash_entries(
    repo_resolved: Path,
    cockpit_resolved: Optional[Path],
    paper_paths: Optional[Sequence[str | Path] | str | Path],
) -> List[Dict[str, Any]]:
    """Resolve and content-hash companion manuscript files without embedding host paths."""
    if paper_paths is None:
        return []
    raw_items: Sequence[str | Path]
    if isinstance(paper_paths, (str, Path)):
        raw_s = str(paper_paths).strip()
        raw_items = [paper_paths] if raw_s else []
    else:
        raw_items = list(paper_paths)
    if not raw_items:
        return []

    eff_boundary = cockpit_resolved if cockpit_resolved is not None else repo_resolved
    collected_files: Dict[str, Path] = {}
    inc_re = re.compile(r"\\(?:input|include|subfile|bibliography|addbibresource)\s*\{([^{}]+)\}")

    def _rel_paper_key(fp: Path) -> str:
        if fp.is_relative_to(repo_resolved):
            return fp.relative_to(repo_resolved).as_posix()
        if cockpit_resolved is not None and fp.is_relative_to(cockpit_resolved):
            return f"cockpit:{fp.relative_to(cockpit_resolved).as_posix()}"
        return fp.name

    def _walk_tex_inputs(tex_fp: Path, tex_root: Path, seen_tex: Set[Path]) -> None:
        r_tf = tex_fp.resolve()
        if r_tf in seen_tex or not r_tf.is_file():
            return
        seen_tex.add(r_tf)
        collected_files[_rel_paper_key(r_tf)] = r_tf
        if r_tf.suffix.lower() != ".tex":
            return
        try:
            txt = r_tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for raw_ln in txt.splitlines():
            clean_ln = _strip_tex_comment_line(raw_ln)
            for m_inc in inc_re.finditer(clean_ln):
                is_bib = m_inc.group(0).lstrip("\\").startswith(("bibliography", "addbibresource"))
                raw_parts = [p.strip() for p in m_inc.group(1).split(",")] if is_bib else [m_inc.group(1)]
                for part_raw in raw_parts:
                    trimmed_ref = part_raw.strip().strip('"').strip("'")
                    if not trimmed_ref:
                        continue
                    if trimmed_ref.startswith(("\\\\", "//", "/", "\\")) or ":" in trimmed_ref:
                        raise AnvilRefusalError(
                            "PATH_ESCAPE_REFUSED",
                            f"Manuscript child '{trimmed_ref}' uses rooted, UNC, or drive-qualified path.",
                            cwe="CWE-22",
                            details={"candidate": trimmed_ref, "http_status": 403},
                        )
                    raw_ref = trimmed_ref.replace("\\", "/")
                    found_c: Optional[Path] = None
                    escaped_boundary = False
                    sufs = ("", ".bib") if is_bib else ("", ".tex")
                    for base_d in (r_tf.parent, tex_root):
                        for suf in sufs:
                            unnorm_c = base_d / f"{raw_ref}{suf}"
                            norm_c = Path(os.path.normpath(str(unnorm_c)))
                            if not (norm_c == eff_boundary or norm_c.is_relative_to(eff_boundary)):
                                escaped_boundary = True
                                continue
                            # Verify zero symlinks/junctions along relative hops from eff_boundary
                            cur_hop = eff_boundary
                            for hop_pt in norm_c.relative_to(eff_boundary).parts:
                                cur_hop = cur_hop / hop_pt
                                if _is_link_or_junction(cur_hop):
                                    raise AnvilRefusalError(
                                        "PATH_ESCAPE_REFUSED",
                                        f"Symlink/junction manuscript child '{raw_ref}' refused.",
                                        cwe="CWE-22",
                                        details={"candidate": raw_ref, "http_status": 403},
                                    )
                            if norm_c.is_file():
                                res_c = norm_c.resolve()
                                if not (res_c == eff_boundary or res_c.is_relative_to(eff_boundary)):
                                    raise AnvilRefusalError(
                                        "PATH_ESCAPE_REFUSED",
                                        f"Manuscript child '{raw_ref}' escapes workspace boundary.",
                                        cwe="CWE-22",
                                        details={"candidate": raw_ref, "http_status": 403},
                                    )
                                found_c = res_c
                                break
                        if found_c is not None:
                            _walk_tex_inputs(found_c, tex_root, seen_tex)
                            break
                    if found_c is None and escaped_boundary:
                        raise AnvilRefusalError(
                            "PATH_ESCAPE_REFUSED",
                            f"Manuscript child '{raw_ref}' escapes workspace boundary.",
                            cwe="CWE-22",
                            details={"candidate": raw_ref, "http_status": 403},
                        )

    for item in raw_items:
        resolved_p = resolve_manuscript_path(repo_resolved, item, allowed_root=eff_boundary)
        if not resolved_p.exists():
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Manuscript path '{item}' does not exist.",
                cwe="CWE-22",
                details={"candidate": str(item), "http_status": 400},
            )
        if resolved_p.is_dir():
            for cur_r, dirs, files in os.walk(resolved_p, followlinks=False):
                cur_rp = Path(cur_r)
                kept_d: List[str] = []
                for d in sorted(dirs):
                    if d in SKIP_SCAN_DIRS or d.startswith("."):
                        continue
                    dp = cur_rp / d
                    if _is_link_or_junction(dp):
                        raise AnvilRefusalError(
                            "PATH_ESCAPE_REFUSED",
                            f"Symlink or junction directory '{d}' inside manuscript folder refused.",
                            cwe="CWE-22",
                            details={"candidate": d, "http_status": 403},
                        )
                    kept_d.append(d)
                dirs[:] = kept_d
                for fn in sorted(files):
                    if fn.startswith("."):
                        continue
                    fp = cur_rp / fn
                    if _is_link_or_junction(fp):
                        raise AnvilRefusalError(
                            "PATH_ESCAPE_REFUSED",
                            f"Symlink or junction file '{fn}' inside manuscript folder refused.",
                            cwe="CWE-22",
                            details={"candidate": fn, "http_status": 403},
                        )
                    if fp.suffix.lower() in {".tex", ".bib", ".md", ".pdf", ".sty", ".cls"}:
                        rfp = fp.resolve()
                        collected_files[_rel_paper_key(rfp)] = rfp
        else:
            _walk_tex_inputs(resolved_p, resolved_p.parent, set())

    out_papers: List[Dict[str, Any]] = []
    for rel_k in sorted(collected_files.keys()):
        fp = collected_files[rel_k]
        raw_b = fp.read_bytes()
        out_papers.append({
            "path": rel_k,
            "sha256": hashlib.sha256(raw_b).hexdigest(),
            "bytes": len(raw_b),
        })
    return out_papers


def compute_scope_manifest(
    repo_root: str | Path,
    *,
    scope_files: Optional[Sequence[str | Path]] = None,
    selected_module_ids: Optional[Sequence[str]] = None,
    entrypoints: Optional[Sequence[str]] = None,
    paper_paths: Optional[Sequence[str | Path] | str | Path] = None,
    cockpit_root: Optional[str | Path] = None,
    data_roots: Optional[Sequence[str | Path]] = None,
    bundle_bytes: Optional[int] = None,
    max_data_bytes: Optional[int] = None,
    max_bundle_bytes: Optional[int] = None,
    engine_scripts_dir: Optional[str | Path] = None,
    schema_version: str = SCOPE_MANIFEST_SCHEMA_VERSION,
) -> Tuple[str, str]:
    """Compute a pure, mtime/re-checkout-invariant fixed-scope manifest `(canonical_json, scope_sha256)`
    where `scope_sha256` is a lowercase 64-hex SHA-256 digest over:
      - sorted repo-relative POSIX file paths + per-file content SHA-256 + byte count,
      - sorted opaque `selected_module_ids` (`^[a-z0-9_-]+$`),
      - sorted normalized `entrypoints`,
      - sorted companion manuscript/paper content SHA-256s,
      - sorted allowlisted data-root file manifest SHA-256s (`data/`, `Data/`, `datasets/`, `Datasets/`
        under `repo_root` or `cockpit_root`, `<= 2 GB` cap, symlinks/escapes refused),
      - `schema_version` (`"anvil-scope-manifest/v6.1"`), and
      - `engine_content_sha256` (content digest of canonical Anvil engine scripts).
    """
    if repo_root is None or not str(repo_root).strip() or "\x00" in str(repo_root):
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty or invalid repository root refused.", cwe="CWE-22", details={"http_status": 403})
    raw_repo = Path(repo_root)
    if ".." in raw_repo.parts or _is_link_or_junction(raw_repo) or not raw_repo.exists() or not raw_repo.is_dir():
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Repository root does not exist, contains '..', or is a symlink/junction.",
            cwe="CWE-22",
            details={"http_status": 403},
        )
    repo_resolved = raw_repo.resolve()

    cockpit_resolved: Optional[Path] = None
    if cockpit_root is not None and str(cockpit_root).strip():
        raw_ck = Path(cockpit_root)
        if "\x00" in str(cockpit_root) or ".." in raw_ck.parts or _is_link_or_junction(raw_ck) or not raw_ck.exists() or not raw_ck.is_dir():
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                "Cockpit root does not exist, contains '..', or is a symlink/junction.",
                cwe="CWE-22",
                details={"http_status": 403},
            )
        cockpit_resolved = raw_ck.resolve()

    raw_max_data = int(MAX_ALLOWLISTED_DATA_BYTES if max_data_bytes is None else max_data_bytes)
    raw_max_bundle = int(MAX_SCOPE_BUNDLE_BYTES if max_bundle_bytes is None else max_bundle_bytes)
    eff_max_data = min(int(MAX_ALLOWLISTED_DATA_BYTES), raw_max_data) if raw_max_data > 0 else raw_max_data
    eff_max_bundle = min(int(MAX_SCOPE_BUNDLE_BYTES), raw_max_bundle) if raw_max_bundle > 0 else raw_max_bundle
    if eff_max_bundle <= 0:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_bundle_bytes ({eff_max_bundle}) must be positive.",
            details={
                "bound_name": "max_scope_bundle_bytes",
                "bound_limit": eff_max_bundle,
                "observed_value": eff_max_bundle,
                "http_status": 413,
            },
        )
    if bundle_bytes is not None and int(bundle_bytes) > eff_max_bundle:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Bundle payload ({int(bundle_bytes)} bytes) exceeds 8 MB cap ({eff_max_bundle} bytes).",
            details={
                "bound_name": "max_scope_bundle_bytes",
                "bound_limit": eff_max_bundle,
                "observed_value": int(bundle_bytes),
                "http_status": 413,
            },
        )

    # 1. Validate & sort opaque module IDs
    norm_module_ids: List[str] = []
    if selected_module_ids is not None:
        seen_mids: Set[str] = set()
        for raw_mid in selected_module_ids:
            mid = str(raw_mid or "").strip()
            if not mid or "/" in mid or "\\" in mid or ".." in mid:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Module ID '{raw_mid}' contains path/traversal characters; opaque ID required.",
                    cwe="CWE-22",
                    details={"candidate": str(raw_mid), "http_status": 400},
                )
            if not OPAQUE_MODULE_ID_RE.fullmatch(mid):
                raise AnvilRefusalError(
                    "INVALID_MODULE_ID_REFUSED",
                    f"Module ID '{mid}' must match ^[a-z0-9_-]+$.",
                    details={"candidate": mid, "http_status": 400},
                )
            if mid not in seen_mids:
                seen_mids.add(mid)
                norm_module_ids.append(mid)
        norm_module_ids.sort()

    # 2. Validate & normalize entrypoints
    norm_entrypoints: List[str] = []
    if entrypoints is not None:
        seen_eps: Set[str] = set()
        for raw_ep in entrypoints:
            ep_s = str(raw_ep or "").strip()
            if not ep_s or "\x00" in ep_s:
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty entrypoint refused.", cwe="CWE-22", details={"http_status": 400})
            # Refuse Windows drive letters like `C:\foo.py` BEFORE splitting on `:` symbol separator
            if Path(ep_s).is_absolute() or (len(ep_s) >= 2 and ep_s[1] == ":" and ep_s[0].isalpha()):
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Absolute entrypoint path '{ep_s}' refused; repo-relative path required.",
                    cwe="CWE-22",
                    details={"candidate": ep_s, "http_status": 403},
                )
            file_part, sep, sym_part = ep_s.partition(":")
            rel_ep_file, _ = _validate_strict_contained_rel_file(repo_resolved, file_part)
            clean_sym = sym_part.strip()
            if sep and (not clean_sym or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", clean_sym)):
                raise AnvilRefusalError(
                    "MALFORMED_DATA_REFUSED",
                    f"Invalid symbol qualifier '{sym_part}' in entrypoint '{ep_s}'.",
                    details={"candidate": ep_s, "http_status": 400},
                )
            ep_norm = f"{rel_ep_file}:{clean_sym}" if (sep and clean_sym) else rel_ep_file
            if ep_norm not in seen_eps:
                seen_eps.add(ep_norm)
                norm_entrypoints.append(ep_norm)
        norm_entrypoints.sort()

    # 3. Resolve & hash scoped source files (enforcing <= 8 MB bundle cap)
    resolved_file_pairs: List[Tuple[str, Path]] = []
    seen_f_rels: Set[str] = set()
    if scope_files is not None:
        for sf in scope_files:
            rel_posix, abs_fp = _validate_strict_contained_rel_file(repo_resolved, sf)
            if rel_posix not in seen_f_rels:
                seen_f_rels.add(rel_posix)
                resolved_file_pairs.append((rel_posix, abs_fp))
    else:
        prod_fps, test_fps = _scan_contained_source_files(repo_resolved)
        for abs_fp in sorted(prod_fps + test_fps):
            rel_posix = abs_fp.relative_to(repo_resolved).as_posix()
            if rel_posix not in seen_f_rels:
                seen_f_rels.add(rel_posix)
                resolved_file_pairs.append((rel_posix, abs_fp))

    resolved_file_pairs.sort(key=lambda pair: pair[0])
    file_entries: List[Dict[str, Any]] = []
    total_source_bytes = 0
    for rel_posix, abs_fp in resolved_file_pairs:
        st_f = os.stat(abs_fp, follow_symlinks=False)
        if total_source_bytes + int(st_f.st_size) > eff_max_bundle:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Scoped source bundle size ({total_source_bytes + int(st_f.st_size)} bytes) exceeds 8 MB cap ({eff_max_bundle} bytes).",
                details={
                    "bound_name": "max_scope_bundle_bytes",
                    "bound_limit": eff_max_bundle,
                    "observed_value": total_source_bytes + int(st_f.st_size),
                    "offending_file": rel_posix,
                    "http_status": 413,
                },
            )
        raw_bytes = abs_fp.read_bytes()
        total_source_bytes += len(raw_bytes)
        if total_source_bytes > eff_max_bundle:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Scoped source bundle size ({total_source_bytes} bytes) exceeds 8 MB cap ({eff_max_bundle} bytes).",
                details={
                    "bound_name": "max_scope_bundle_bytes",
                    "bound_limit": eff_max_bundle,
                    "observed_value": total_source_bytes,
                    "offending_file": rel_posix,
                    "http_status": 413,
                },
            )
        file_entries.append({
            "path": rel_posix,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "bytes": len(raw_bytes),
        })

    # 4. Companion paper hashes + allowlisted data-root hashes + engine content hash
    paper_entries = _collect_paper_hash_entries(repo_resolved, cockpit_resolved, paper_paths)
    data_entries, total_data_bytes = _collect_allowlisted_data_manifest(
        repo_resolved, cockpit_resolved, data_roots, eff_max_data
    )
    engine_sha256 = _compute_engine_content_sha256(engine_scripts_dir)

    manifest_doc: Dict[str, Any] = {
        "schema_version": str(schema_version),
        "engine_content_sha256": engine_sha256,
        "selected_module_ids": norm_module_ids,
        "entrypoints": norm_entrypoints,
        "files": file_entries,
        "papers": paper_entries,
        "allowlisted_data_files": data_entries,
        "totals": {
            "file_count": len(file_entries),
            "source_bytes": total_source_bytes,
            "paper_count": len(paper_entries),
            "allowlisted_data_file_count": len(data_entries),
            "allowlisted_data_bytes": total_data_bytes,
        },
    }
    canonical_json = json.dumps(
        manifest_doc,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    canonical_bytes = canonical_json.encode("utf-8")
    if len(canonical_bytes) > eff_max_bundle:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Serialized scope manifest ({len(canonical_bytes)} bytes) exceeds 8 MB cap ({eff_max_bundle} bytes).",
            details={
                "bound_name": "max_scope_bundle_bytes",
                "bound_limit": eff_max_bundle,
                "observed_value": len(canonical_bytes),
                "http_status": 413,
            },
        )
    scope_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    return canonical_json, scope_sha256


def _extract_decorator_name(dec: ast.AST) -> str:
    cur = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(cur, ast.Name):
        return cur.id
    if isinstance(cur, ast.Attribute):
        return cur.attr
    return ""


def _scan_self_reads_and_escapes(
    node: ast.AST,
    known_methods: Set[str],
) -> Tuple[Set[str], bool]:
    """Inspect an AST node inside `__init__` for `(read_self_attrs, self_escaped)`.
    `self_escaped` is True if any `self.<method>(...)` call (known or inherited) is
    invoked or bare `self` is passed as an argument to another call.
    """
    _ = known_methods
    read_attrs: Set[str] = set()
    escaped = False
    attr_parents: Dict[int, ast.AST] = {}
    for parent in ast.walk(node):
        for ch in ast.iter_child_nodes(parent):
            attr_parents[id(ch)] = parent

    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == "self":
            if isinstance(sub.ctx, ast.Load):
                par = attr_parents.get(id(sub))
                if isinstance(par, ast.Call) and par.func is sub:
                    escaped = True
                    read_attrs.add(sub.attr)
                else:
                    read_attrs.add(sub.attr)
        elif isinstance(sub, ast.AugAssign):
            tgt = sub.target
            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                read_attrs.add(tgt.attr)
        elif isinstance(sub, ast.Name) and sub.id == "self" and isinstance(sub.ctx, ast.Load):
            par = attr_parents.get(id(sub))
            if not isinstance(par, ast.Attribute):
                escaped = True
    return read_attrs, escaped


_EARLY_EXIT_AST_TYPES: Tuple[type, ...] = tuple(
    t for t in (
        ast.Return,
        ast.Raise,
        ast.Yield,
        ast.YieldFrom,
        ast.Try,
        getattr(ast, "TryStar", None),
    )
    if t is not None
)


def _stmt_may_exit_early(stmt: ast.stmt) -> bool:
    """Return True if `stmt` can exit or branch out of `__init__` early (`return`, `raise`, `try`).
    Does not descend into nested function/class/lambda definitions.
    """
    stack: List[ast.AST] = [stmt]
    while stack:
        cur = stack.pop()
        if isinstance(cur, _EARLY_EXIT_AST_TYPES):
            return True
        for ch in ast.iter_child_nodes(cur):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.append(ch)
    return False


def _is_main_guard_if_stmt(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.If):
        return False
    try:
        unparsed = ast.unparse(stmt.test)
    except Exception:
        return False
    return "__name__" in unparsed and ("'__main__'" in unparsed or '"__main__"' in unparsed)


_DYNAMIC_TABLE_KEY = ("__anvil_dynamic_key__",)


def _extract_hashable_const_key(node: Optional[ast.AST]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, bytes)):
        return (type(node.value).__name__, node.value)
    if isinstance(node, ast.Tuple):
        parts: List[Any] = []
        for elt in node.elts:
            sub_k = _extract_hashable_const_key(elt)
            if sub_k == _DYNAMIC_TABLE_KEY:
                return _DYNAMIC_TABLE_KEY
            parts.append(sub_k)
        return ("tuple", tuple(parts))
    return _DYNAMIC_TABLE_KEY


def _is_super_init_stmt(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    fn = stmt.value.func
    return (
        isinstance(fn, ast.Attribute)
        and fn.attr == "__init__"
        and isinstance(fn.value, ast.Call)
        and isinstance(fn.value.func, ast.Name)
        and fn.value.func.id == "super"
    )


def _extract_unconditional_self_attr_write(stmt: ast.stmt) -> Optional[Tuple[str, ast.AST]]:
    """If `stmt` is a straight-line single-target `self.<attr> = <rhs>`, return `(attr, rhs)`."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        tgt = stmt.targets[0]
        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
            return tgt.attr, stmt.value
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        tgt = stmt.target
        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
            return tgt.attr, stmt.value
    return None


def build_symbol_call_graph(
    repo_root: str | Path,
    *,
    scope_files: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    """Build a pure-AST (zero-execution) repository symbol call graph supporting:
      - cross-module `import` / `from ... import ...`, function-local/conditional imports,
        `importlib.import_module`, and `__init__.py` re-export resolution,
      - sound constructor-attribute overwrite pruning (`self.<attr> = Dead()` unconditionally
        overwritten by `self.<attr> = Active()` with zero intervening read, escape, or early exit),
      - Rapid Type Analysis (RTA) virtual method & attribute dispatch across base and subclass
        overrides, callbacks, classes-as-values, decorators, `@property`, and dunder protocols,
      - dynamic dispatch discovery (`getattr`, `globals()[...]`, dict/list dispatch tables via
        subscript/`.get`/`.items`/`.values`/iteration/argument-passing, and `@register` decorators)
        preserved in `"uncertain"`.
    """
    raw_repo = Path(repo_root)
    if _is_link_or_junction(raw_repo) or not raw_repo.exists():
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Repository path does not exist or is a symlink/junction.",
            cwe="CWE-22",
            details={"http_status": 403},
        )
    if raw_repo.is_file():
        root = raw_repo.parent.resolve()
        py_files = [raw_repo.resolve()] if raw_repo.suffix.lower() == ".py" else []
    else:
        root = raw_repo.resolve()
        if scope_files is not None:
            py_files = []
            seen_sf: Set[str] = set()
            for sf in scope_files:
                rel_s, abs_p = _validate_strict_contained_rel_file(root, sf)
                if abs_p.suffix.lower() == ".py" and rel_s not in seen_sf:
                    seen_sf.add(rel_s)
                    py_files.append(abs_p)
        else:
            prod_fps, _ = _scan_contained_source_files(root)
            py_files = [fp for fp in prod_fps if fp.suffix.lower() == ".py"]

    adj_imports, source_by_rel = _build_repo_import_graph(root, py_files)
    known_rels: Set[str] = set(source_by_rel.keys())
    stem_to_rels: Dict[str, List[str]] = {}
    top_code_roots: Set[str] = set()
    for rel in sorted(known_rels):
        stem_to_rels.setdefault(Path(rel).stem, []).append(rel)
        pts = Path(rel).parts
        if len(pts) > 1 and pts[0].lower() in ("code", "src", "python", "scripts", "lib"):
            top_code_roots.add(pts[0])

    def _resolve_mod_candidates(mod_spec: str, level: int, importer_rel: str) -> List[str]:
        hits: List[str] = []
        imp_dir = Path(importer_rel).parent
        clean_spec = (mod_spec or "").strip(".")
        rel_sub = clean_spec.replace(".", "/") if clean_spec else ""
        bases: List[Path] = []
        if level >= 1:
            anc = imp_dir
            for _ in range(max(0, level - 1)):
                anc = anc.parent
            bases.append(anc)
        else:
            bases.append(Path("."))
            cur_a = imp_dir
            while str(cur_a) not in ("", "."):
                if cur_a not in bases:
                    bases.append(cur_a)
                cur_a = cur_a.parent
            for cr in sorted(top_code_roots):
                cp = Path(cr)
                if cp not in bases:
                    bases.append(cp)
        for b in bases:
            pref = _strip_leading_dot_slash((b / rel_sub).as_posix()) if rel_sub else _strip_leading_dot_slash(b.as_posix())
            if not pref or pref == ".":
                continue
            for cand in (f"{pref}.py", f"{pref}/__init__.py"):
                if cand in known_rels and cand != importer_rel and cand not in hits:
                    hits.append(cand)
        if not hits and level == 0 and clean_spec and "." not in clean_spec:
            cands = [r for r in stem_to_rels.get(clean_spec, []) if r != importer_rel and not _is_historical_clutter_path(r)]
            if len(cands) == 1:
                hits.append(cands[0])
        return hits

    trees_by_rel: Dict[str, ast.Module] = {}
    lines_by_rel: Dict[str, List[str]] = {}
    symbols: Dict[str, Dict[str, Any]] = {}
    file_defs: Dict[str, Dict[str, str]] = {r: {} for r in known_rels}
    class_methods: Dict[str, Dict[str, str]] = {}
    class_raw_bases: Dict[str, List[str]] = {}
    file_mod_imports: Dict[str, Dict[str, List[str]]] = {r: {} for r in known_rels}
    file_from_imports: Dict[str, Dict[str, List[Tuple[str, str]]]] = {r: {} for r in known_rels}
    file_star_imports: Dict[str, List[str]] = {r: [] for r in known_rels}
    decorated_registry_syms: Set[str] = set()
    property_method_names: Set[str] = set()

    def _add_mod_import(rel_f: str, alias_key: str, target_rel: str) -> None:
        lst = file_mod_imports[rel_f].setdefault(alias_key, [])
        if target_rel not in lst:
            lst.append(target_rel)
        imp_lst = adj_imports.setdefault(rel_f, [])
        if target_rel != rel_f and target_rel not in imp_lst:
            imp_lst.append(target_rel)

    def _add_from_import(rel_f: str, alias_key: str, target_rel: str, orig_nm: str) -> None:
        lst = file_from_imports[rel_f].setdefault(alias_key, [])
        pair = (target_rel, orig_nm)
        if pair not in lst:
            lst.append(pair)
        imp_lst = adj_imports.setdefault(rel_f, [])
        if target_rel != rel_f and target_rel not in imp_lst:
            imp_lst.append(target_rel)

    # Pass 1: Parse ASTs, collect symbol definitions, all imports (including lazy/conditional), and decorator registries
    for rel in sorted(known_rels):
        txt = source_by_rel[rel]
        lines_by_rel[rel] = txt.splitlines()
        tree = _parse_python_ast_quiet(txt, filename=rel)
        if tree is None:
            continue
        trees_by_rel[rel] = tree

        # Collect ALL import statements across module body, function bodies, and `if`/`try` guards
        for imp_node in ast.walk(tree):
            if isinstance(imp_node, ast.Import):
                for al in imp_node.names:
                    cands = _resolve_mod_candidates(al.name, 0, rel)
                    if cands:
                        if al.asname:
                            for cr_t in cands:
                                _add_mod_import(rel, al.asname, cr_t)
                        else:
                            local_nm = al.name.split(".")[0]
                            top_cands = _resolve_mod_candidates(local_nm, 0, rel)
                            lead_top = cands[0] if "." not in al.name else (top_cands[0] if top_cands else cands[0])
                            _add_mod_import(rel, local_nm, lead_top)
                            parts_sp = al.name.split(".")
                            for p_idx in range(2, len(parts_sp) + 1):
                                pref_sp = ".".join(parts_sp[:p_idx])
                                for cr_p in _resolve_mod_candidates(pref_sp, 0, rel):
                                    _add_mod_import(rel, pref_sp, cr_p)
            elif isinstance(imp_node, ast.ImportFrom):
                lvl = int(imp_node.level or 0)
                base_mod = imp_node.module or ""
                base_cands = _resolve_mod_candidates(base_mod, lvl, rel)
                for al in imp_node.names:
                    if al.name == "*":
                        for bc in base_cands:
                            if bc not in file_star_imports[rel]:
                                file_star_imports[rel].append(bc)
                            if bc != rel and bc not in adj_imports.setdefault(rel, []):
                                adj_imports[rel].append(bc)
                        continue
                    local_nm = al.asname or al.name
                    sub_spec = f"{base_mod}.{al.name}" if base_mod else al.name
                    sub_cands = _resolve_mod_candidates(sub_spec, lvl, rel)
                    if sub_cands and (not base_cands or sub_cands[0] != base_cands[0]):
                        for sc_t in sub_cands:
                            _add_mod_import(rel, local_nm, sc_t)
                        for bc_t in base_cands:
                            _add_from_import(rel, local_nm, bc_t, al.name)
                    elif base_cands:
                        for bc_t in base_cands:
                            _add_from_import(rel, local_nm, bc_t, al.name)
            elif isinstance(imp_node, ast.Assign):
                val_n = imp_node.value
                if isinstance(val_n, ast.Call):
                    fn_im = val_n.func
                    is_imp_m = (
                        (isinstance(fn_im, ast.Attribute) and fn_im.attr == "import_module")
                        or (isinstance(fn_im, ast.Name) and fn_im.id == "import_module")
                    )
                    if is_imp_m and val_n.args and isinstance(val_n.args[0], ast.Constant) and isinstance(val_n.args[0].value, str):
                        im_cands = _resolve_mod_candidates(val_n.args[0].value.strip(), 0, rel)
                        for tgt_n in imp_node.targets:
                            if isinstance(tgt_n, ast.Name):
                                for ic in im_cands:
                                    _add_mod_import(rel, tgt_n.id, ic)

        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sid = f"{rel}:{stmt.name}"
                s_ln = int(getattr(stmt, "lineno", 1))
                e_ln = int(getattr(stmt, "end_lineno", s_ln) or s_ln)
                decs = [_extract_decorator_name(d) for d in stmt.decorator_list]
                has_reg_dec = any(dn and dn not in _STDLIB_NON_REGISTRY_DECORATORS for dn in decs)
                if has_reg_dec:
                    decorated_registry_syms.add(sid)
                symbols[sid] = {
                    "id": sid,
                    "file": rel,
                    "symbol": stmt.name,
                    "short_name": stmt.name,
                    "class_name": "",
                    "kind": "function",
                    "start_line": s_ln,
                    "end_line": e_ln,
                    "docstring": (ast.get_docstring(stmt) or "").splitlines()[0].strip() if ast.get_docstring(stmt) else "",
                    "decorators": [d for d in decs if d],
                }
                file_defs[rel][stmt.name] = sid
            elif isinstance(stmt, ast.ClassDef):
                csid = f"{rel}:{stmt.name}"
                cs_ln = int(getattr(stmt, "lineno", 1))
                ce_ln = int(getattr(stmt, "end_lineno", cs_ln) or cs_ln)
                cdecs = [_extract_decorator_name(d) for d in stmt.decorator_list]
                if any(dn and dn not in _STDLIB_NON_REGISTRY_DECORATORS for dn in cdecs):
                    decorated_registry_syms.add(csid)
                b_raw: List[str] = []
                for b in stmt.bases:
                    try:
                        b_raw.append(ast.unparse(b))
                    except Exception:
                        if isinstance(b, ast.Name):
                            b_raw.append(b.id)
                        elif isinstance(b, ast.Attribute):
                            b_raw.append(b.attr)
                class_raw_bases[csid] = b_raw
                class_methods[csid] = {}
                symbols[csid] = {
                    "id": csid,
                    "file": rel,
                    "symbol": stmt.name,
                    "short_name": stmt.name,
                    "class_name": stmt.name,
                    "kind": "class",
                    "bases": b_raw,
                    "start_line": cs_ln,
                    "end_line": ce_ln,
                    "docstring": (ast.get_docstring(stmt) or "").splitlines()[0].strip() if ast.get_docstring(stmt) else "",
                    "decorators": [d for d in cdecs if d],
                }
                file_defs[rel][stmt.name] = csid
                for mstmt in stmt.body:
                    if isinstance(mstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qname = f"{stmt.name}.{mstmt.name}"
                        msid = f"{rel}:{qname}"
                        ms_ln = int(getattr(mstmt, "lineno", cs_ln))
                        me_ln = int(getattr(mstmt, "end_lineno", ms_ln) or ms_ln)
                        mdecs = [_extract_decorator_name(d) for d in mstmt.decorator_list]
                        if any(dn and dn not in _STDLIB_NON_REGISTRY_DECORATORS for dn in mdecs):
                            decorated_registry_syms.add(msid)
                        if any(dn in {"property", "cached_property"} for dn in mdecs):
                            property_method_names.add(mstmt.name)
                        symbols[msid] = {
                            "id": msid,
                            "file": rel,
                            "symbol": qname,
                            "short_name": mstmt.name,
                            "class_name": stmt.name,
                            "kind": "method",
                            "start_line": ms_ln,
                            "end_line": me_ln,
                            "docstring": (ast.get_docstring(mstmt) or "").splitlines()[0].strip() if ast.get_docstring(mstmt) else "",
                            "decorators": [d for d in mdecs if d],
                        }
                        class_methods[csid][mstmt.name] = msid

    # Resolve star imports & transitive `__init__.py` / re-export chains (up to 6 hops)
    def _resolve_name_in_file(rel: str, ident: str, _depth: int = 0) -> List[str]:
        if _depth > 6:
            return []
        hits: List[str] = []
        if ident in file_defs.get(rel, {}):
            hits.append(file_defs[rel][ident])
        for tgt_rel, orig_nm in file_from_imports.get(rel, {}).get(ident, ()):
            for sh in _resolve_name_in_file(tgt_rel, orig_nm, _depth + 1):
                if sh not in hits:
                    hits.append(sh)
        if not hits:
            for star_rel in file_star_imports.get(rel, ()):
                if not ident.startswith("_"):
                    for sth in _resolve_name_in_file(star_rel, ident, _depth + 1):
                        if sth not in hits:
                            hits.append(sth)
        return hits

    def _resolve_mod_alias_targets(rel: str, expr: ast.AST) -> List[str]:
        """Resolve a module alias (`hooks`) or dotted submodule expression (`pkg.hooks`) to target file rels."""
        if isinstance(expr, ast.Name):
            return list(file_mod_imports.get(rel, {}).get(expr.id, ()))
        if isinstance(expr, ast.Attribute):
            try:
                dotted = ast.unparse(expr)
            except Exception:
                dotted = ""
            if dotted and dotted in file_mod_imports.get(rel, {}):
                return list(file_mod_imports[rel][dotted])
            parent_mods = _resolve_mod_alias_targets(rel, expr.value)
            out_m: List[str] = []
            for pm in parent_mods:
                # Submodule imported inside `pm` or sibling submodule under `pm`'s package dir
                for sm in file_mod_imports.get(pm, {}).get(expr.attr, ()):
                    if sm not in out_m:
                        out_m.append(sm)
                if pm.endswith("/__init__.py") or pm == "__init__.py":
                    pkg_dir = Path(pm).parent
                    pref_s = _strip_leading_dot_slash((pkg_dir / expr.attr).as_posix())
                    for cand_m in (f"{pref_s}.py", f"{pref_s}/__init__.py"):
                        if cand_m in known_rels and cand_m not in out_m:
                            out_m.append(cand_m)
            return out_m
        return []

    def _resolve_expr_symbol_targets(rel: str, expr: ast.AST) -> List[str]:
        """Resolve `fn_name` or `mod.fn_name` or `pkg.sub.Cls` to canonical symbol IDs."""
        if isinstance(expr, ast.Name):
            return _resolve_name_in_file(rel, expr.id)
        if isinstance(expr, ast.Attribute):
            mod_targets = _resolve_mod_alias_targets(rel, expr.value)
            if mod_targets:
                out_hits: List[str] = []
                for tm in mod_targets:
                    for h in _resolve_name_in_file(tm, expr.attr):
                        if h not in out_hits:
                            out_hits.append(h)
                if out_hits:
                    return out_hits
            cls_cands = _resolve_expr_symbol_targets(rel, expr.value)
            out_m: List[str] = []
            for csid in cls_cands:
                if csid in class_methods and expr.attr in class_methods[csid]:
                    out_m.append(class_methods[csid][expr.attr])
            if out_m:
                return out_m
        return []

    # Resolve class inheritance bases (`class_bases[csid] -> [base_csid, ...]`)
    class_bases: Dict[str, List[str]] = {csid: [] for csid in class_methods}
    for csid, raw_b_list in class_raw_bases.items():
        c_rel = symbols[csid]["file"]
        for rb in raw_b_list:
            b_tail = rb.split(".")[-1]
            resolved_b = _resolve_name_in_file(c_rel, b_tail)
            if not resolved_b and "." in rb:
                mod_part = rb.rsplit(".", 1)[0]
                for b_mod in file_mod_imports.get(c_rel, {}).get(mod_part, ()):
                    for bh in _resolve_name_in_file(b_mod, b_tail):
                        if bh not in resolved_b:
                            resolved_b.append(bh)
            for b_sid in resolved_b:
                if b_sid in class_methods and b_sid != csid and b_sid not in class_bases[csid]:
                    class_bases[csid].append(b_sid)

    def _lookup_method_on_class_hierarchy(csid: str, method_name: str, _seen: Optional[Set[str]] = None) -> List[str]:
        seen = _seen if _seen is not None else set()
        if csid in seen:
            return []
        seen.add(csid)
        if method_name in class_methods.get(csid, {}):
            return [class_methods[csid][method_name]]
        hits: List[str] = []
        for b_sid in class_bases.get(csid, ()):
            for h in _lookup_method_on_class_hierarchy(b_sid, method_name, seen):
                if h not in hits:
                    hits.append(h)
        return hits

    def _all_known_method_names_for_class(csid: str) -> Set[str]:
        out: Set[str] = set()
        stack = [csid]
        visited: Set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            out.update(class_methods.get(cur, {}).keys())
            stack.extend(class_bases.get(cur, ()))
        return out

    # Pass 1.5: Collect module-level & class-level dispatch dicts/lists/tuples
    # (`SOLVERS = {"k": fn_a, ...}`, `MODELS = [A, B]`, `SOLVERS[k] = fn_b`, `class R: SOLVERS = {...}`)
    dispatch_table_entries: Dict[Tuple[str, str], Dict[Any, List[str]]] = {}

    def _collect_dispatch_from_stmts(rel_f: str, stmts_list: Sequence[ast.stmt], key_prefix: str = "") -> None:
        for stmt in stmts_list:
            if isinstance(stmt, ast.Assign):
                val = stmt.value
                t_names = [
                    f"{key_prefix}{t.id}"
                    for t in stmt.targets
                    if isinstance(t, ast.Name)
                ]
                if not key_prefix:
                    for t in stmt.targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                            t_names.append(f"__self__.{t.attr}")
                if t_names and isinstance(val, ast.Dict):
                    entries_map: Dict[Any, List[str]] = {}
                    for k_node, v_node in zip(val.keys, val.values):
                        if v_node is None:
                            continue
                        v_syms = _resolve_expr_symbol_targets(rel_f, v_node)
                        if not v_syms and isinstance(v_node, ast.Call):
                            v_syms = _resolve_expr_symbol_targets(rel_f, v_node.func)
                        if v_syms:
                            k_tok = _extract_hashable_const_key(k_node)
                            entries_map.setdefault(k_tok, []).extend(v_syms)
                    if entries_map:
                        for tn in t_names:
                            dispatch_table_entries[(rel_f, tn)] = entries_map
                elif t_names and isinstance(val, (ast.List, ast.Tuple, ast.Set)):
                    seq_syms: List[str] = []
                    for elt in val.elts:
                        seq_syms.extend(_resolve_expr_symbol_targets(rel_f, elt))
                    if seq_syms:
                        for tn in t_names:
                            dispatch_table_entries[(rel_f, tn)] = {_DYNAMIC_TABLE_KEY: list(dict.fromkeys(seq_syms))}
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
                        v_syms = _resolve_expr_symbol_targets(rel_f, val)
                        if v_syms:
                            k_tok = _extract_hashable_const_key(tgt.slice)
                            dispatch_table_entries.setdefault((rel_f, f"{key_prefix}{tgt.value.id}"), {}).setdefault(k_tok, []).extend(v_syms)
            elif isinstance(stmt, ast.ClassDef) and not key_prefix:
                _collect_dispatch_from_stmts(rel_f, stmt.body, key_prefix=f"{stmt.name}.")
                for mstmt in stmt.body:
                    if isinstance(mstmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and mstmt.name == "__init__":
                        for istmt in mstmt.body:
                            if isinstance(istmt, ast.Assign):
                                for itgt in istmt.targets:
                                    if isinstance(itgt, ast.Attribute) and isinstance(itgt.value, ast.Name) and itgt.value.id == "self":
                                        ival = istmt.value
                                        if isinstance(ival, ast.Dict):
                                            imap: Dict[Any, List[str]] = {}
                                            for k_n, v_n in zip(ival.keys, ival.values):
                                                if v_n is None:
                                                    continue
                                                vs = _resolve_expr_symbol_targets(rel_f, v_n)
                                                if vs:
                                                    imap.setdefault(_extract_hashable_const_key(k_n), []).extend(vs)
                                            if imap:
                                                dispatch_table_entries[(rel_f, f"{stmt.name}.{itgt.attr}")] = imap
                                        elif isinstance(ival, (ast.List, ast.Tuple, ast.Set)):
                                            ss = [s for elt in ival.elts for s in _resolve_expr_symbol_targets(rel_f, elt)]
                                            if ss:
                                                dispatch_table_entries[(rel_f, f"{stmt.name}.{itgt.attr}")] = {_DYNAMIC_TABLE_KEY: list(dict.fromkeys(ss))}

    for rel, tree in trees_by_rel.items():
        _collect_dispatch_from_stmts(rel, tree.body)

    def _merge_tbl_dicts(dicts: Sequence[Dict[Any, List[str]]]) -> Optional[Dict[Any, List[str]]]:
        if not dicts:
            return None
        merged: Dict[Any, List[str]] = {}
        for d in dicts:
            for k, vlist in d.items():
                dst = merged.setdefault(k, [])
                for v in vlist:
                    if v not in dst:
                        dst.append(v)
        return merged or None

    def _resolve_dispatch_table(rel: str, var_name: str, _depth: int = 0) -> Optional[Dict[Any, List[str]]]:
        if _depth > 5:
            return None
        found_dicts: List[Dict[Any, List[str]]] = []
        if (rel, var_name) in dispatch_table_entries:
            found_dicts.append(dispatch_table_entries[(rel, var_name)])
        for t_rel, orig_v in file_from_imports.get(rel, {}).get(var_name, ()):
            sub_t = _resolve_dispatch_table(t_rel, orig_v, _depth + 1)
            if sub_t is not None:
                found_dicts.append(sub_t)
        if not found_dicts:
            for star_rel in file_star_imports.get(rel, ()):
                sub_s = _resolve_dispatch_table(star_rel, var_name, _depth + 1)
                if sub_s is not None:
                    found_dicts.append(sub_s)
        return _merge_tbl_dicts(found_dicts)

    def _lookup_class_dispatch_table(csid: str, attr_name: str) -> Optional[Dict[Any, List[str]]]:
        found_dicts: List[Dict[Any, List[str]]] = []
        seen_c: Set[str] = set()
        stack = [csid]
        while stack:
            cur_c = stack.pop()
            if cur_c in seen_c or cur_c not in symbols:
                continue
            seen_c.add(cur_c)
            c_rel = symbols[cur_c]["file"]
            c_nm = symbols[cur_c]["symbol"]
            if (c_rel, f"{c_nm}.{attr_name}") in dispatch_table_entries:
                found_dicts.append(dispatch_table_entries[(c_rel, f"{c_nm}.{attr_name}")])
            stack.extend(class_bases.get(cur_c, ()))
        return _merge_tbl_dicts(found_dicts)

    def _resolve_dispatch_table_expr(rel: str, expr: ast.AST, cls_sid: str = "") -> Optional[Dict[Any, List[str]]]:
        if isinstance(expr, ast.Name):
            return _resolve_dispatch_table(rel, expr.id)
        if isinstance(expr, ast.Attribute):
            mod_targets = _resolve_mod_alias_targets(rel, expr.value)
            if mod_targets:
                dicts_m = [
                    t for tm in mod_targets
                    for t in [_resolve_dispatch_table(tm, expr.attr)]
                    if t is not None
                ]
                if dicts_m:
                    return _merge_tbl_dicts(dicts_m)
            if cls_sid and isinstance(expr.value, ast.Name) and expr.value.id == "self":
                return _lookup_class_dispatch_table(cls_sid, expr.attr)
            cls_targets = _resolve_expr_symbol_targets(rel, expr.value)
            dicts_c = [
                t for csid in cls_targets
                if csid in class_methods
                for t in [_lookup_class_dispatch_table(csid, expr.attr)]
                if t is not None
            ]
            if dicts_c:
                return _merge_tbl_dicts(dicts_c)
        return None

    # Pass 2: Analyze `__init__` constructor-attribute overwrites (sound wrt early exit, escapes & inheritance)
    shadowed_allocations: List[Dict[str, Any]] = []
    init_shadowed_stmt_ids: Dict[str, Set[int]] = {}
    init_exit_attr_callees: Dict[str, Dict[str, List[str]]] = {}
    init_exit_attr_stmt_ids: Dict[str, Dict[str, int]] = {}
    init_exit_attr_meta: Dict[str, Dict[str, Dict[str, Any]]] = {}
    sub_overwrites_super_attrs: Dict[str, Set[str]] = {}
    active_self_attr_classes: Dict[Tuple[str, str], Set[str]] = {}

    def _extract_stmt_callees(rel: str, expr: ast.AST) -> Tuple[List[str], Set[str]]:
        """Return `(direct_symbol_ids, instantiated_class_ids)` inside `expr`."""
        callees: List[str] = []
        inst_classes: Set[str] = set()
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Call):
                resolved = _resolve_expr_symbol_targets(rel, sub.func)
                for r_sid in resolved:
                    if r_sid not in callees:
                        callees.append(r_sid)
                    if symbols.get(r_sid, {}).get("kind") == "class":
                        inst_classes.add(r_sid)
                        for init_sid in _lookup_method_on_class_hierarchy(r_sid, "__init__"):
                            if init_sid not in callees:
                                callees.append(init_sid)
        return callees, inst_classes

    ordered_csids: List[str] = []
    visited_c: Set[str] = set()

    def _topo_cls(csid: str) -> None:
        if csid in visited_c:
            return
        visited_c.add(csid)
        for b_sid in class_bases.get(csid, ()):
            _topo_cls(b_sid)
        ordered_csids.append(csid)

    for csid in sorted(class_methods.keys()):
        _topo_cls(csid)

    for csid in ordered_csids:
        init_msid = class_methods[csid].get("__init__")
        if not init_msid:
            continue
        c_rel = symbols[csid]["file"]
        c_name = symbols[csid]["symbol"]
        tree = trees_by_rel.get(c_rel)
        if tree is None:
            continue
        cls_node = next((s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == c_name), None)
        if cls_node is None:
            continue
        init_node = next(
            (m for m in cls_node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == "__init__"),
            None,
        )
        if init_node is None:
            continue

        known_mnames = _all_known_method_names_for_class(csid) - {"__init__"}
        pending_writes: Dict[str, Dict[str, Any]] = {}
        shadowed_ids: Set[int] = set()
        super_overwritten_before_read: Set[str] = set()
        saw_super_init = False
        super_attrs_live_until_read: Set[str] = set()
        base_csid = class_bases[csid][0] if class_bases.get(csid) else ""
        base_init_msid = class_methods.get(base_csid, {}).get("__init__", "") if base_csid else ""

        body_stmts = _strip_docstring_stmts_local(init_node.body)
        for stmt in body_stmts:
            if _is_super_init_stmt(stmt):
                # Any `self.<attr>` written BEFORE `super().__init__()` might be read by `Base.__init__`
                pending_writes.clear()
                if base_init_msid:
                    saw_super_init = True
                    super_attrs_live_until_read = set(init_exit_attr_callees.get(base_init_msid, {}).keys())
                continue

            uncond = _extract_unconditional_self_attr_write(stmt)
            if uncond is not None:
                attr_nm, rhs_expr = uncond
                r_attrs, r_esc = _scan_self_reads_and_escapes(rhs_expr, known_mnames)
                if r_esc:
                    pending_writes.clear()
                    super_attrs_live_until_read.clear()
                else:
                    for ra in r_attrs:
                        pending_writes.pop(ra, None)
                        super_attrs_live_until_read.discard(ra)

                cur_callees, cur_inst = _extract_stmt_callees(c_rel, rhs_expr)
                lno = int(getattr(stmt, "lineno", init_node.lineno))
                try:
                    rhs_src = ast.unparse(rhs_expr)[:120]
                except Exception:
                    rhs_src = ""

                if attr_nm in pending_writes:
                    prev_w = pending_writes[attr_nm]
                    if prev_w["callees"]:
                        shadowed_ids.add(prev_w["stmt_obj_id"])
                        shadowed_allocations.append({
                            "file": c_rel,
                            "class_name": c_name,
                            "symbol": f"{c_name}.__init__",
                            "attribute": f"self.{attr_nm}",
                            "shadowed_line": prev_w["lineno"],
                            "overwritten_by_line": lno,
                            "shadowed_expr": prev_w["rhs_src"],
                            "active_expr": rhs_src,
                            "shadowed_symbols": list(prev_w["callees"]),
                            "active_symbols": list(cur_callees),
                            "kind": "intra_init_unconditional_overwrite",
                        })
                elif saw_super_init and attr_nm in super_attrs_live_until_read and base_init_msid:
                    super_overwritten_before_read.add(attr_nm)
                    super_attrs_live_until_read.discard(attr_nm)
                    b_meta = init_exit_attr_meta.get(base_init_msid, {}).get(attr_nm, {})
                    if b_meta.get("callees"):
                        shadowed_allocations.append({
                            "file": c_rel,
                            "class_name": c_name,
                            "symbol": f"{c_name}.__init__",
                            "inherited_from": symbols[base_csid]["id"],
                            "attribute": f"self.{attr_nm}",
                            "shadowed_line": b_meta.get("lineno", 1),
                            "overwritten_by_line": lno,
                            "shadowed_expr": b_meta.get("rhs_src", ""),
                            "active_expr": rhs_src,
                            "shadowed_symbols": list(b_meta.get("callees") or []),
                            "active_symbols": list(cur_callees),
                            "kind": "super_init_unconditional_overwrite",
                        })

                pending_writes[attr_nm] = {
                    "attr": attr_nm,
                    "stmt_obj_id": id(stmt),
                    "lineno": lno,
                    "rhs_src": rhs_src,
                    "callees": cur_callees,
                    "inst_classes": cur_inst,
                }
            else:
                r_attrs, r_esc = _scan_self_reads_and_escapes(stmt, known_mnames)
                if r_esc or _stmt_may_exit_early(stmt):
                    pending_writes.clear()
                    super_attrs_live_until_read.clear()
                else:
                    for ra in r_attrs:
                        pending_writes.pop(ra, None)
                        super_attrs_live_until_read.discard(ra)
                for sub_st in ast.walk(stmt):
                    if isinstance(sub_st, ast.Assign):
                        for t in sub_st.targets:
                            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                                _, sub_inst = _extract_stmt_callees(c_rel, sub_st.value)
                                if sub_inst:
                                    active_self_attr_classes.setdefault((csid, t.attr), set()).update(sub_inst)

        init_shadowed_stmt_ids[init_msid] = shadowed_ids
        if super_overwritten_before_read:
            sub_overwrites_super_attrs[init_msid] = super_overwritten_before_read
        exit_callees: Dict[str, List[str]] = {}
        exit_stmt_ids: Dict[str, int] = {}
        exit_meta: Dict[str, Dict[str, Any]] = {}
        for attr_nm, pw in pending_writes.items():
            if pw["inst_classes"]:
                active_self_attr_classes.setdefault((csid, attr_nm), set()).update(pw["inst_classes"])
            if pw["callees"]:
                exit_callees[attr_nm] = list(pw["callees"])
                exit_stmt_ids[attr_nm] = pw["stmt_obj_id"]
                exit_meta[attr_nm] = pw
        for stmt in body_stmts:
            if id(stmt) in shadowed_ids:
                continue
            uncond = _extract_unconditional_self_attr_write(stmt)
            if uncond is not None:
                a_nm, r_ex = uncond
                _, s_inst = _extract_stmt_callees(c_rel, r_ex)
                if s_inst:
                    active_self_attr_classes.setdefault((csid, a_nm), set()).update(s_inst)

        init_exit_attr_callees[init_msid] = exit_callees
        init_exit_attr_stmt_ids[init_msid] = exit_stmt_ids
        init_exit_attr_meta[init_msid] = exit_meta

    #Also collect `self.<attr> = Cls()` writes in non-`__init__` methods (e.g. `setup`/`fit`)
    for csid in ordered_csids:
        c_rel = symbols[csid]["file"]
        c_name = symbols[csid]["symbol"]
        tree = trees_by_rel.get(c_rel)
        if tree is None:
            continue
        cls_node = next((s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == c_name), None)
        if cls_node is None:
            continue
        for mstmt in cls_node.body:
            if isinstance(mstmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and mstmt.name != "__init__":
                for sub_st in ast.walk(mstmt):
                    if isinstance(sub_st, ast.Assign):
                        for t in sub_st.targets:
                            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                                _, sub_inst = _extract_stmt_callees(c_rel, sub_st.value)
                                if sub_inst:
                                    active_self_attr_classes.setdefault((csid, t.attr), set()).update(sub_inst)

    # Propagate inherited `active_self_attr_classes` down to subclasses unless unconditionally overwritten
    for csid in ordered_csids:
        init_msid = class_methods[csid].get("__init__", "")
        overwritten_super = sub_overwrites_super_attrs.get(init_msid, set())
        for b_sid in class_bases.get(csid, ()):
            for (owner_c, attr_nm), tgt_cset in list(active_self_attr_classes.items()):
                if owner_c == b_sid and attr_nm not in overwritten_super:
                    active_self_attr_classes.setdefault((csid, attr_nm), set()).update(tgt_cset)

    # Build subclass lookup `class_descendants[csid]` (including `csid` itself) for RTA virtual dispatch
    class_descendants: Dict[str, Set[str]] = {csid: {csid} for csid in class_methods}
    for csid in ordered_csids:
        stack_b = list(class_bases.get(csid, ()))
        seen_b: Set[str] = set()
        while stack_b:
            anc_c = stack_b.pop()
            if anc_c in seen_b:
                continue
            seen_b.add(anc_c)
            if anc_c in class_descendants:
                class_descendants[anc_c].add(csid)
            stack_b.extend(class_bases.get(anc_c, ()))

    # Pass 3: Analyze every function, method, decorator, and module top-level body
    direct_edges: Dict[str, List[str]] = {sid: [] for sid in symbols}
    conditional_super_edges: Dict[str, List[Tuple[str, Set[str]]]] = {}
    unresolved_method_calls: Dict[str, List[str]] = {sid: [] for sid in symbols}
    dynamic_edges: Dict[str, List[str]] = {sid: [] for sid in symbols}
    virtual_self_calls: Dict[str, List[Tuple[str, str]]] = {sid: [] for sid in symbols}
    virtual_self_attr_calls: Dict[str, List[Tuple[str, str, str]]] = {sid: [] for sid in symbols}
    virtual_self_getattr: Dict[str, List[Tuple[str, str]]] = {sid: [] for sid in symbols}
    unres_getattr_prefixes: Dict[str, List[str]] = {sid: [] for sid in symbols}
    dynamic_import_owners: Set[str] = set()
    dynamic_sites: List[Dict[str, Any]] = []
    file_entry_roots: Dict[str, Dict[str, Any]] = {}

    def _collect_non_runtime_type_node_ids(root_nodes: Sequence[ast.AST]) -> Set[int]:
        """Collect AST node IDs inside type annotations and `isinstance`/`issubclass`/`super` type args
        so type hints never count as runtime class instantiations.
        """
        ignored: Set[int] = set()

        def _mark_subtree(sub_root: Optional[ast.AST]) -> None:
            if sub_root is None:
                return
            for sub_n in ast.walk(sub_root):
                ignored.add(id(sub_n))

        for rn in root_nodes:
            for nd in ast.walk(rn):
                if isinstance(nd, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _mark_subtree(nd.returns)
                    for arg_n in (
                        list(nd.args.posonlyargs)
                        + list(nd.args.args)
                        + list(nd.args.kwonlyargs)
                        + ([nd.args.vararg] if nd.args.vararg else [])
                        + ([nd.args.kwarg] if nd.args.kwarg else [])
                    ):
                        _mark_subtree(arg_n.annotation)
                elif isinstance(nd, ast.AnnAssign):
                    _mark_subtree(nd.annotation)
                elif isinstance(nd, ast.Call) and isinstance(nd.func, ast.Name):
                    if nd.func.id in ("isinstance", "issubclass") and len(nd.args) >= 2:
                        _mark_subtree(nd.args[1])
                    elif nd.func.id == "super" and nd.args:
                        _mark_subtree(nd.args[0])
        return ignored

    def _walk_without_nested_class_defs(stmt_node: ast.AST) -> List[ast.AST]:
        out_n: List[ast.AST] = []
        stack_w: List[ast.AST] = [stmt_node]
        while stack_w:
            cur_n = stack_w.pop()
            out_n.append(cur_n)
            ch_list = list(ast.iter_child_nodes(cur_n))
            ch_list.reverse()
            for ch in ch_list:
                if isinstance(ch, ast.ClassDef):
                    continue
                stack_w.append(ch)
        return out_n

    def _analyze_ast_block(
        rel: str,
        owner_sid: str,
        stmts: Sequence[ast.stmt],
        *,
        cls_sid: str = "",
        skip_stmt_ids: Optional[Set[int]] = None,
        extra_exprs: Optional[Sequence[ast.expr]] = None,
    ) -> Tuple[List[str], List[str], List[str], List[Tuple[str, str]], List[Tuple[str, str, str]], List[Tuple[str, str]], List[str]]:
        stat_out: List[str] = []
        dyn_out: List[str] = []
        unres_methods: List[str] = []
        v_self_calls: List[Tuple[str, str]] = []
        v_self_attr_calls: List[Tuple[str, str, str]] = []
        v_self_getattr: List[Tuple[str, str]] = []
        u_getattr_prefs: List[str] = []
        local_var_classes: Dict[str, Set[str]] = {}
        file_lines = lines_by_rel.get(rel, [])

        eff_stmts: List[ast.stmt] = [ast.Expr(value=ex) for ex in (extra_exprs or ())]
        for st in stmts:
            if skip_stmt_ids and id(st) in skip_stmt_ids:
                continue
            eff_stmts.append(st)

        ignored_type_ids = _collect_non_runtime_type_node_ids(eff_stmts)

        # Flow-safe union of all classes assigned to any local/module variable across the block
        for st in eff_stmts:
            for sub_n in _walk_without_nested_class_defs(st):
                if isinstance(sub_n, ast.Assign):
                    _, v_inst = _extract_stmt_callees(rel, sub_n.value)
                    # Also handle `cls_var = SomeClass` where RHS is a class value
                    for rhs_sym in _resolve_expr_symbol_targets(rel, sub_n.value):
                        if symbols.get(rhs_sym, {}).get("kind") == "class":
                            v_inst.add(rhs_sym)
                    if v_inst:
                        for tgt_n in sub_n.targets:
                            if isinstance(tgt_n, ast.Name):
                                local_var_classes.setdefault(tgt_n.id, set()).update(v_inst)
                elif isinstance(sub_n, ast.AnnAssign) and sub_n.value is not None and isinstance(sub_n.target, ast.Name):
                    _, v_inst = _extract_stmt_callees(rel, sub_n.value)
                    if v_inst:
                        local_var_classes.setdefault(sub_n.target.id, set()).update(v_inst)

        def _add_stat(sid_v: str) -> None:
            if sid_v and sid_v not in stat_out:
                stat_out.append(sid_v)
            if symbols.get(sid_v, {}).get("kind") == "class":
                for init_s in _lookup_method_on_class_hierarchy(sid_v, "__init__"):
                    if init_s not in stat_out:
                        stat_out.append(init_s)

        def _add_dyn(sid_v: str) -> None:
            if sid_v and sid_v not in dyn_out:
                dyn_out.append(sid_v)

        def _add_unres(m_nm: str) -> None:
            if m_nm and m_nm not in unres_methods:
                unres_methods.append(m_nm)

        def _add_v_self(c_id: str, m_nm: str) -> None:
            pair = (c_id, m_nm)
            if c_id and m_nm and pair not in v_self_calls:
                v_self_calls.append(pair)

        def _add_v_self_attr(c_id: str, a_nm: str, m_nm: str) -> None:
            trip = (c_id, a_nm, m_nm)
            if c_id and a_nm and m_nm and trip not in v_self_attr_calls:
                v_self_attr_calls.append(trip)

        def _record_dunder_on_expr(target_expr: ast.AST, dunder_names: Sequence[str]) -> None:
            if cls_sid and isinstance(target_expr, ast.Name) and target_expr.id == "self":
                for dn in dunder_names:
                    _add_v_self(cls_sid, dn)
            elif isinstance(target_expr, ast.Name) and target_expr.id in local_var_classes:
                for lc_s in sorted(local_var_classes[target_expr.id]):
                    for dn in dunder_names:
                        for mh in _lookup_method_on_class_hierarchy(lc_s, dn):
                            _add_stat(mh)
            elif (
                cls_sid
                and isinstance(target_expr, ast.Attribute)
                and isinstance(target_expr.value, ast.Name)
                and target_expr.value.id == "self"
            ):
                for dn in dunder_names:
                    _add_v_self_attr(cls_sid, target_expr.attr, dn)
            else:
                for dn in dunder_names:
                    _add_unres(dn)

        for top_st in eff_stmts:
            if cls_sid and owner_sid.endswith(".__init__") and _is_super_init_stmt(top_st):
                base_c = class_bases[cls_sid][0] if class_bases.get(cls_sid) else ""
                base_init = class_methods.get(base_c, {}).get("__init__", "") if base_c else ""
                if base_init:
                    conditional_super_edges.setdefault(owner_sid, []).append(
                        (base_init, set(sub_overwrites_super_attrs.get(owner_sid, set())))
                    )
                    continue

            walk_nodes = _walk_without_nested_class_defs(top_st)
            parent_map: Dict[int, ast.AST] = {}
            call_func_ids: Set[int] = set()
            call_arg_ids: Set[int] = set()
            const_handled_tbl_expr_ids: Set[int] = set()
            tbl_method_attr_ids: Set[int] = set()

            for p_nd in walk_nodes:
                for ch_nd in ast.iter_child_nodes(p_nd):
                    parent_map[id(ch_nd)] = p_nd
                if isinstance(p_nd, ast.Call):
                    call_func_ids.add(id(p_nd.func))
                    for a_nd in p_nd.args:
                        call_arg_ids.add(id(a_nd))
                    for kw_nd in p_nd.keywords:
                        if kw_nd.value is not None:
                            call_arg_ids.add(id(kw_nd.value))

            # Pre-scan constant-key dispatch table lookups (`TBL[const_k]` & `TBL.get(const_k)`)
            # so only the matched entry is marked static while dynamic/iterated uses mark all entries uncertain
            for node in walk_nodes:
                if id(node) in ignored_type_ids:
                    continue
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                    tbl = _resolve_dispatch_table_expr(rel, node.value, cls_sid)
                    if tbl is not None:
                        const_k = _extract_hashable_const_key(node.slice)
                        if const_k != _DYNAMIC_TABLE_KEY and const_k in tbl:
                            const_handled_tbl_expr_ids.add(id(node.value))
                            for t_sid in tbl[const_k]:
                                _add_stat(t_sid)
                        else:
                            const_handled_tbl_expr_ids.add(id(node.value))
                            lno = int(getattr(node, "lineno", 1))
                            snip = file_lines[lno - 1].strip()[:96] if 1 <= lno <= len(file_lines) else "registry[...]"
                            dynamic_sites.append({
                                "kind": "registry_subscript",
                                "file": rel,
                                "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                                "line": lno,
                                "expr": snip,
                            })
                            for cand_list in tbl.values():
                                for c_sid in cand_list:
                                    _add_dyn(c_sid)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    fn_a = node.func
                    if fn_a.attr in ("get", "items", "values", "keys"):
                        tbl = _resolve_dispatch_table_expr(rel, fn_a.value, cls_sid)
                        if tbl is not None:
                            const_handled_tbl_expr_ids.add(id(fn_a.value))
                            tbl_method_attr_ids.add(id(fn_a))
                            if fn_a.attr == "get" and node.args:
                                k0 = _extract_hashable_const_key(node.args[0])
                                if k0 != _DYNAMIC_TABLE_KEY and k0 in tbl:
                                    for t_sid in tbl[k0]:
                                        _add_stat(t_sid)
                                    continue
                            lno = int(getattr(node, "lineno", 1))
                            snip = file_lines[lno - 1].strip()[:96] if 1 <= lno <= len(file_lines) else f"registry.{fn_a.attr}(...)"
                            dynamic_sites.append({
                                "kind": f"registry_{fn_a.attr}",
                                "file": rel,
                                "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                                "line": lno,
                                "expr": snip,
                            })
                            for cand_list in tbl.values():
                                for c_sid in cand_list:
                                    _add_dyn(c_sid)

            for node in walk_nodes:
                if id(node) in ignored_type_ids:
                    continue

                # Implicit dunder protocols (`for x in obj`, `[x for x in obj]`, `with obj:`, `x in obj`, `obj[k]`)
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    if _resolve_dispatch_table_expr(rel, node.iter, cls_sid) is None:
                        _record_dunder_on_expr(node.iter, ("__iter__", "__next__"))
                elif isinstance(node, ast.comprehension):
                    if _resolve_dispatch_table_expr(rel, node.iter, cls_sid) is None:
                        _record_dunder_on_expr(node.iter, ("__iter__", "__next__"))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for w_item in node.items:
                        _record_dunder_on_expr(w_item.context_expr, ("__enter__", "__exit__"))
                elif isinstance(node, ast.Compare):
                    for op_c, cmp_c in zip(node.ops, node.comparators):
                        if isinstance(op_c, (ast.In, ast.NotIn)):
                            _record_dunder_on_expr(cmp_c, ("__contains__",))
                elif isinstance(node, ast.Subscript):
                    if _resolve_dispatch_table_expr(rel, node.value, cls_sid) is None:
                        if isinstance(node.ctx, ast.Load):
                            _record_dunder_on_expr(node.value, ("__getitem__",))
                        elif isinstance(node.ctx, ast.Store):
                            _record_dunder_on_expr(node.value, ("__setitem__",))

                # Any remaining dispatch-table reference (iteration `for fn in MODELS`, passing `SOLVERS` as arg, etc.)
                if (
                    isinstance(node, (ast.Name, ast.Attribute))
                    and isinstance(getattr(node, "ctx", None), ast.Load)
                    and id(node) not in const_handled_tbl_expr_ids
                    and id(node) not in tbl_method_attr_ids
                ):
                    par_n = parent_map.get(id(node))
                    # Avoid double-counting `reg` when `reg.SOLVERS` is the actual table expression
                    if not (isinstance(par_n, ast.Attribute) and par_n.value is node):
                        tbl_ref = _resolve_dispatch_table_expr(rel, node, cls_sid)
                        if tbl_ref is not None:
                            lno_t = int(getattr(node, "lineno", 1))
                            snip_t = file_lines[lno_t - 1].strip()[:96] if 1 <= lno_t <= len(file_lines) else "registry_ref"
                            dynamic_sites.append({
                                "kind": "registry_reference",
                                "file": rel,
                                "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                                "line": lno_t,
                                "expr": snip_t,
                            })
                            for cand_list in tbl_ref.values():
                                for c_sid in cand_list:
                                    _add_dyn(c_sid)

                # Non-call value references: callbacks (`minimize(self.neg_loglik, x0)`, `pool.map(workers.run_rep, ...)`),
                # classes as values (`for cls in (Baseline, Proposed): cls()`), and `@property` reads (`self.scale`)
                if (
                    isinstance(node, (ast.Name, ast.Attribute))
                    and isinstance(getattr(node, "ctx", None), ast.Load)
                    and id(node) not in call_func_ids
                    and id(node) not in tbl_method_attr_ids
                ):
                    par_v = parent_map.get(id(node))
                    is_attr_prefix = isinstance(par_v, ast.Attribute) and par_v.value is node
                    if not is_attr_prefix:
                        val_targets = _resolve_expr_symbol_targets(rel, node)
                        if val_targets:
                            for r_sid in val_targets:
                                if r_sid != owner_sid:
                                    _add_stat(r_sid)
                        elif isinstance(node, ast.Attribute):
                            if cls_sid and isinstance(node.value, ast.Name) and node.value.id == "self":
                                _add_v_self(cls_sid, node.attr)
                            elif isinstance(node.value, ast.Name) and node.value.id in local_var_classes:
                                for lc_s in sorted(local_var_classes[node.value.id]):
                                    for mh in _lookup_method_on_class_hierarchy(lc_s, node.attr):
                                        _add_stat(mh)
                            elif node.attr in property_method_names or id(node) in call_arg_ids:
                                _add_unres(node.attr)

                if not isinstance(node, ast.Call):
                    continue

                lno = int(getattr(node, "lineno", 1))
                snip = file_lines[lno - 1].strip()[:96] if 1 <= lno <= len(file_lines) else ""
                fn = node.func

                # Builtin dunder triggers: `len(x)` -> `__len__`, `iter(x)`/`next(x)` -> `__iter__`/`__next__`
                if isinstance(fn, ast.Name) and node.args:
                    if fn.id == "len" and len(node.args) == 1:
                        _record_dunder_on_expr(node.args[0], ("__len__",))
                    elif fn.id in ("iter", "next"):
                        _record_dunder_on_expr(node.args[0], ("__iter__", "__next__"))

                # `importlib.import_module(...)`
                is_imp_call = (
                    (isinstance(fn, ast.Attribute) and fn.attr == "import_module")
                    or (isinstance(fn, ast.Name) and fn.id == "import_module")
                )
                if is_imp_call and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        for im_rel in _resolve_mod_candidates(a0.value.strip(), 0, rel):
                            if im_rel != rel and im_rel not in adj_imports.setdefault(rel, []):
                                adj_imports[rel].append(im_rel)
                    else:
                        dynamic_import_owners.add(owner_sid)
                        dynamic_sites.append({
                            "kind": "dynamic_import",
                            "file": rel,
                            "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                            "line": lno,
                            "expr": snip or "import_module(...)",
                        })

                # 1. `getattr(target, attr_expr, ...)`
                if isinstance(fn, ast.Name) and fn.id == "getattr" and len(node.args) >= 2:
                    tgt_arg, name_arg = node.args[0], node.args[1]
                    const_attr = name_arg.value if (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)) else None
                    prefix_hint = ""
                    if isinstance(name_arg, ast.JoinedStr):
                        for vp in name_arg.values:
                            if isinstance(vp, ast.Constant) and isinstance(vp.value, str) and vp.value:
                                prefix_hint = vp.value
                                break

                    target_mod_rels = _resolve_mod_alias_targets(rel, tgt_arg)
                    if (
                        not target_mod_rels
                        and isinstance(tgt_arg, ast.Subscript)
                        and isinstance(tgt_arg.value, ast.Attribute)
                        and tgt_arg.value.attr == "modules"
                    ):
                        target_mod_rels = [rel]

                    if const_attr:
                        if target_mod_rels:
                            for t_mod in target_mod_rels:
                                for g_sid in _resolve_name_in_file(t_mod, const_attr):
                                    _add_stat(g_sid)
                        elif cls_sid and isinstance(tgt_arg, ast.Name) and tgt_arg.id == "self":
                            _add_v_self(cls_sid, const_attr)
                        elif isinstance(tgt_arg, ast.Name) and tgt_arg.id in local_var_classes:
                            for lc_s in sorted(local_var_classes[tgt_arg.id]):
                                for mh in _lookup_method_on_class_hierarchy(lc_s, const_attr):
                                    _add_stat(mh)
                        else:
                            _add_unres(const_attr)
                    else:
                        dynamic_sites.append({
                            "kind": "getattr",
                            "file": rel,
                            "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                            "line": lno,
                            "expr": snip or "getattr(...)",
                        })
                        if target_mod_rels:
                            for target_mod_rel in target_mod_rels:
                                for def_nm, def_sid in file_defs.get(target_mod_rel, {}).items():
                                    if def_nm.startswith("_") and not prefix_hint:
                                        continue
                                    if prefix_hint and not def_nm.startswith(prefix_hint):
                                        continue
                                    _add_dyn(def_sid)
                                for imp_nm in file_from_imports.get(target_mod_rel, {}):
                                    if imp_nm.startswith("_") and not prefix_hint:
                                        continue
                                    if prefix_hint and not imp_nm.startswith(prefix_hint):
                                        continue
                                    for re_sid in _resolve_name_in_file(target_mod_rel, imp_nm):
                                        _add_dyn(re_sid)
                                for star_r in file_star_imports.get(target_mod_rel, ()):
                                    for s_nm, s_sid in file_defs.get(star_r, {}).items():
                                        if s_nm.startswith("_"):
                                            continue
                                        if prefix_hint and not s_nm.startswith(prefix_hint):
                                            continue
                                        _add_dyn(s_sid)
                        elif cls_sid and isinstance(tgt_arg, ast.Name) and tgt_arg.id == "self":
                            if (cls_sid, prefix_hint) not in v_self_getattr:
                                v_self_getattr.append((cls_sid, prefix_hint))
                        elif isinstance(tgt_arg, ast.Name) and tgt_arg.id in local_var_classes:
                            for lc_s in sorted(local_var_classes[tgt_arg.id]):
                                for desc_c in sorted(class_descendants.get(lc_s, {lc_s})):
                                    for m_nm in _all_known_method_names_for_class(desc_c):
                                        if m_nm.startswith("__"):
                                            continue
                                        if prefix_hint and not m_nm.startswith(prefix_hint):
                                            continue
                                        for m_sid in _lookup_method_on_class_hierarchy(desc_c, m_nm):
                                            _add_dyn(m_sid)
                        elif (
                            cls_sid
                            and isinstance(tgt_arg, ast.Attribute)
                            and isinstance(tgt_arg.value, ast.Name)
                            and tgt_arg.value.id == "self"
                        ):
                            for sc_s in sorted(active_self_attr_classes.get((cls_sid, tgt_arg.attr), set())):
                                for m_nm in _all_known_method_names_for_class(sc_s):
                                    if m_nm.startswith("__"):
                                        continue
                                    if prefix_hint and not m_nm.startswith(prefix_hint):
                                        continue
                                    for m_sid in _lookup_method_on_class_hierarchy(sc_s, m_nm):
                                        _add_dyn(m_sid)
                            if prefix_hint not in u_getattr_prefs:
                                u_getattr_prefs.append(prefix_hint)
                        else:
                            if prefix_hint not in u_getattr_prefs:
                                u_getattr_prefs.append(prefix_hint)
                            for s_id, s_meta in symbols.items():
                                snm = s_meta["short_name"]
                                if snm.startswith("_"):
                                    continue
                                if prefix_hint and not snm.startswith(prefix_hint):
                                    continue
                                if s_meta["file"] == rel or prefix_hint:
                                    _add_dyn(s_id)
                    continue

                # 2. `globals()[expr](...)`
                if (
                    isinstance(fn, ast.Subscript)
                    and isinstance(fn.value, ast.Call)
                    and isinstance(fn.value.func, ast.Name)
                    and fn.value.func.id == "globals"
                ):
                    sl = fn.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        for g_sid in _resolve_name_in_file(rel, sl.value):
                            _add_stat(g_sid)
                    else:
                        dynamic_sites.append({
                            "kind": "globals_subscript",
                            "file": rel,
                            "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                            "line": lno,
                            "expr": snip or "globals()[...]",
                        })
                        for def_nm, def_sid in file_defs.get(rel, {}).items():
                            if not def_nm.startswith("__"):
                                _add_dyn(def_sid)
                        for imp_nm in file_from_imports.get(rel, {}):
                            for re_sid in _resolve_name_in_file(rel, imp_nm):
                                _add_dyn(re_sid)
                    continue

                # 3. Dispatch table `.get(...)` handled in pre-scan
                if id(fn) in tbl_method_attr_ids:
                    continue

                # 3b. `super().<method>(...)`
                if (
                    cls_sid
                    and isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Call)
                    and isinstance(fn.value.func, ast.Name)
                    and fn.value.func.id == "super"
                ):
                    for b_sid in class_bases.get(cls_sid, ()):
                        for mh in _lookup_method_on_class_hierarchy(b_sid, fn.attr):
                            _add_stat(mh)
                    continue

                # 4. Direct function/class/module-qualified call (`foo()`, `mod.foo()`, `Cls()`)
                direct_targets = _resolve_expr_symbol_targets(rel, fn)
                if direct_targets:
                    for dt_sid in direct_targets:
                        _add_stat(dt_sid)
                    continue

                # 5. Instance / submodule callable or method calls
                if isinstance(fn, ast.Attribute):
                    # Case 5a: `self.<method>(...)` or `self.<attr>(...)` -> virtual dispatch across MRO + subclasses
                    if cls_sid and isinstance(fn.value, ast.Name) and fn.value.id == "self":
                        _add_v_self(cls_sid, fn.attr)
                        continue

                    # Case 5b: `self.<attr>.<method>(...)` -> virtual attribute dispatch across subclass overrides
                    if (
                        cls_sid
                        and isinstance(fn.value, ast.Attribute)
                        and isinstance(fn.value.value, ast.Name)
                        and fn.value.value.id == "self"
                    ):
                        _add_v_self_attr(cls_sid, fn.value.attr, fn.attr)
                        continue

                    # Case 5c: `local_var.<method>(...)` (flow-safe union of all classes assigned to `local_var`)
                    if isinstance(fn.value, ast.Name) and fn.value.id in local_var_classes:
                        for lc_sid in sorted(local_var_classes[fn.value.id]):
                            for mh in _lookup_method_on_class_hierarchy(lc_sid, fn.attr):
                                _add_stat(mh)
                        continue

                    # Case 5d: `Cls(...).<method>(...)`
                    ctor_inner = _unwrap_ctor_call(fn.value)
                    if ctor_inner is not None:
                        _, c_inst = _extract_stmt_callees(rel, ctor_inner)
                        if c_inst:
                            for ci_sid in sorted(c_inst):
                                for mh in _lookup_method_on_class_hierarchy(ci_sid, fn.attr):
                                    _add_stat(mh)
                            continue

                    # Case 5e: Unresolved receiver -> defer to RTA instantiated-class resolution
                    _add_unres(fn.attr)

                # 6. `local_var(x)` / `self(x)` where receiver holds an instance or class (`nn.Module` forward / `__call__`)
                elif isinstance(fn, ast.Name):
                    if cls_sid and fn.id == "self":
                        _add_v_self(cls_sid, "__call__")
                        _add_v_self(cls_sid, "forward")
                    elif fn.id in local_var_classes:
                        for lc_sid in sorted(local_var_classes[fn.id]):
                            for lc_m in ("__call__", "forward", "__init__"):
                                for mh in _lookup_method_on_class_hierarchy(lc_sid, lc_m):
                                    _add_stat(mh)
                    else:
                        # Unknown local callable variable (e.g. `for E in (Ols,): E()` or `def minimize(f, x0): f(x0)`)
                        pass

                # 7. Dynamic subscript call `handlers[k](...)` on unknown local dict/list
                elif isinstance(fn, ast.Subscript):
                    if _resolve_dispatch_table_expr(rel, fn.value, cls_sid) is None:
                        dynamic_sites.append({
                            "kind": "dynamic_subscript_call",
                            "file": rel,
                            "symbol": symbols.get(owner_sid, {}).get("symbol", "<module>"),
                            "line": lno,
                            "expr": snip or "subscript_call(...)",
                        })

        return stat_out, dyn_out, unres_methods, v_self_calls, v_self_attr_calls, v_self_getattr, u_getattr_prefs

    # Walk all files, functions, classes, methods, decorators, and top-level script blocks
    init_non_exit_edges: Dict[str, List[str]] = {}
    for rel, tree in sorted(trees_by_rel.items()):
        top_import_stmts: List[ast.stmt] = []
        top_main_stmts: List[ast.stmt] = []
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sid = f"{rel}:{stmt.name}"
                s_e, d_e, u_m, vs_c, vsa_c, vsg_c, ug_p = _analyze_ast_block(
                    rel, sid, stmt.body, extra_exprs=stmt.decorator_list
                )
                direct_edges[sid] = s_e
                dynamic_edges[sid] = d_e
                unresolved_method_calls[sid] = u_m
                virtual_self_calls[sid] = vs_c
                virtual_self_attr_calls[sid] = vsa_c
                virtual_self_getattr[sid] = vsg_c
                unres_getattr_prefixes[sid] = ug_p
            elif isinstance(stmt, ast.ClassDef):
                csid = f"{rel}:{stmt.name}"
                c_se, c_de, c_um, _, _, _, c_ugp = _analyze_ast_block(
                    rel, csid, [], extra_exprs=stmt.decorator_list
                )
                direct_edges[csid] = c_se
                dynamic_edges[csid] = c_de
                unresolved_method_calls[csid] = c_um
                unres_getattr_prefixes[csid] = c_ugp
                for mstmt in stmt.body:
                    if isinstance(mstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        msid = f"{rel}:{stmt.name}.{mstmt.name}"
                        skip_ids = init_shadowed_stmt_ids.get(msid, set())
                        s_e, d_e, u_m, vs_c, vsa_c, vsg_c, ug_p = _analyze_ast_block(
                            rel,
                            msid,
                            mstmt.body,
                            cls_sid=csid,
                            skip_stmt_ids=skip_ids,
                            extra_exprs=mstmt.decorator_list,
                        )
                        direct_edges[msid] = s_e
                        dynamic_edges[msid] = d_e
                        unresolved_method_calls[msid] = u_m
                        virtual_self_calls[msid] = vs_c
                        virtual_self_attr_calls[msid] = vsa_c
                        virtual_self_getattr[msid] = vsg_c
                        unres_getattr_prefixes[msid] = ug_p
                        if mstmt.name == "__init__" and msid in init_exit_attr_stmt_ids:
                            exit_sids = set(init_exit_attr_stmt_ids[msid].values()) | skip_ids
                            ne_s, _, _, _, _, _, _ = _analyze_ast_block(
                                rel,
                                msid,
                                mstmt.body,
                                cls_sid=csid,
                                skip_stmt_ids=exit_sids,
                                extra_exprs=mstmt.decorator_list,
                            )
                            init_non_exit_edges[msid] = ne_s
            elif not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                is_pure_dispatch_def = (
                    isinstance(stmt, ast.Assign)
                    and all(isinstance(t, ast.Name) and (rel, t.id) in dispatch_table_entries for t in stmt.targets)
                    and not any(isinstance(sub, ast.Call) for sub in ast.walk(stmt.value))
                )
                if not is_pure_dispatch_def:
                    if _is_main_guard_if_stmt(stmt):
                        top_main_stmts.append(stmt)
                    else:
                        top_import_stmts.append(stmt)

        imp_stat, imp_dyn, imp_unres, _, _, _, imp_ugp = _analyze_ast_block(rel, f"{rel}:<import>", top_import_stmts)
        all_top_stmts = top_import_stmts + top_main_stmts
        mod_stat, mod_dyn, mod_unres, _, _, _, mod_ugp = _analyze_ast_block(rel, f"{rel}:<module>", all_top_stmts)
        file_entry_roots[rel] = {
            "static_callees": mod_stat,
            "dynamic_callees": mod_dyn,
            "unresolved_methods": mod_unres,
            "unresolved_getattr_prefixes": mod_ugp,
            "import_static_callees": imp_stat,
            "import_dynamic_callees": imp_dyn,
            "import_unresolved_methods": imp_unres,
            "import_unresolved_getattr_prefixes": imp_ugp,
            "has_top_exec": bool(mod_stat or mod_dyn or mod_unres or imp_ugp or mod_ugp),
            "has_import_exec": bool(imp_stat or imp_dyn or imp_unres or imp_ugp),
        }

    return {
        "schema": SYMBOL_CALL_GRAPH_SCHEMA,
        "repo_root": str(root),
        "symbols": symbols,
        "file_defs": file_defs,
        "class_methods": class_methods,
        "class_bases": class_bases,
        "class_descendants": {k: sorted(v) for k, v in class_descendants.items()},
        "active_self_attr_classes": {f"{c}::{a}": sorted(vs) for (c, a), vs in active_self_attr_classes.items()},
        "direct_edges": direct_edges,
        "init_non_exit_edges": init_non_exit_edges,
        "init_exit_attr_callees": init_exit_attr_callees,
        "conditional_super_edges": conditional_super_edges,
        "unresolved_method_calls": unresolved_method_calls,
        "virtual_self_calls": virtual_self_calls,
        "virtual_self_attr_calls": virtual_self_attr_calls,
        "virtual_self_getattr": virtual_self_getattr,
        "unres_getattr_prefixes": unres_getattr_prefixes,
        "dynamic_import_owners": sorted(dynamic_import_owners),
        "dynamic_edges": dynamic_edges,
        "decorated_registry_syms": sorted(decorated_registry_syms),
        "dynamic_dispatch_sites": dynamic_sites,
        "shadowed_allocations": shadowed_allocations,
        "file_entry_roots": file_entry_roots,
        "import_graph": adj_imports,
    }


def _strip_docstring_stmts_local(body: Sequence[ast.stmt]) -> List[ast.stmt]:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return list(body[1:])
    return list(body)


def slice_call_graph(
    call_graph_or_repo: Dict[str, Any] | str | Path,
    entrypoints: Optional[Sequence[str]] = None,
    *,
    scope_files: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    """Pure-AST backward/forward symbol reachability slicer returning `{reached, unreached, uncertain}`
    plus detailed symbol badge records, `shadowed_allocations`, and `load_time_imported_files`.

    If caller passes explicit `entrypoints` and ANY entrypoint cannot be resolved, returns
    `ok=False` with `unresolved_entrypoints=[...]` (never silently returning `ok=True` with empty slice).
    """
    def _empty_cg_skeleton(syms: Dict[str, Dict[str, Any]], edges: Dict[str, List[str]], dyn: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
        return {
            "schema": SYMBOL_CALL_GRAPH_SCHEMA, "symbols": syms, "file_defs": {}, "class_methods": {},
            "class_bases": {}, "direct_edges": edges, "init_non_exit_edges": {}, "init_exit_attr_callees": {},
            "conditional_super_edges": {}, "unresolved_method_calls": {}, "dynamic_edges": dyn or {},
            "decorated_registry_syms": [], "dynamic_dispatch_sites": [], "shadowed_allocations": [],
            "file_entry_roots": {}, "import_graph": {},
        }

    if isinstance(call_graph_or_repo, (str, Path)):
        cg = build_symbol_call_graph(call_graph_or_repo, scope_files=scope_files)
    elif isinstance(call_graph_or_repo, dict) and call_graph_or_repo.get("schema") == SYMBOL_CALL_GRAPH_SCHEMA:
        cg = call_graph_or_repo
    elif isinstance(call_graph_or_repo, dict) and "l2_steps" in call_graph_or_repo and "repo_root" not in call_graph_or_repo:
        step_syms: Dict[str, Dict[str, Any]] = {}
        step_edges: Dict[str, List[str]] = {}
        for st in call_graph_or_repo.get("l2_steps") or []:
            cref = st.get("code_ref") or {}
            sid = f"{cref.get('file', '')}:{cref.get('symbol', '')}".strip(":")
            if sid:
                sym_s = str(cref.get("symbol") or "")
                step_syms[sid] = {
                    "id": sid, "file": str(cref.get("file") or ""), "symbol": sym_s,
                    "short_name": sym_s.split(".")[-1], "class_name": sym_s.split(".")[0] if "." in sym_s else "",
                    "kind": "function", "start_line": int(cref.get("start_line") or 1), "end_line": int(cref.get("end_line") or 1),
                }
                step_edges[sid] = []
        cg = _empty_cg_skeleton(step_syms, step_edges)
    elif isinstance(call_graph_or_repo, dict):
        raw_syms: Dict[str, Dict[str, Any]] = {}
        raw_edges: Dict[str, List[str]] = {}
        raw_dyn: Dict[str, List[str]] = {}
        for k, v in call_graph_or_repo.items():
            ks = str(k)
            f_p, _, s_p = ks.partition(":")
            eff_sym, eff_file = (s_p, f_p) if s_p else (f_p, "")
            raw_syms.setdefault(ks, {
                "id": ks, "file": eff_file, "symbol": eff_sym, "short_name": eff_sym.split(".")[-1],
                "class_name": eff_sym.split(".")[0] if "." in eff_sym else "", "kind": "function", "start_line": 1, "end_line": 1,
            })
            callees_l = [str(x) for x in (v.get("calls") or v.get("callees") or [])] if isinstance(v, dict) else ([str(x) for x in v] if isinstance(v, (list, tuple, set)) else [])
            unc_l = [str(x) for x in (v.get("uncertain") or v.get("dynamic") or [])] if isinstance(v, dict) else []
            raw_edges[ks], raw_dyn[ks] = callees_l, unc_l
            for tgt in callees_l + unc_l:
                tf_p, _, ts_p = tgt.partition(":")
                ts_eff = ts_p if ts_p else tf_p
                raw_syms.setdefault(tgt, {
                    "id": tgt, "file": tf_p if ts_p else "", "symbol": ts_eff, "short_name": ts_eff.split(".")[-1],
                    "class_name": "", "kind": "function", "start_line": 1, "end_line": 1,
                })
        cg = _empty_cg_skeleton(raw_syms, raw_edges, raw_dyn)
    else:
        raise AnvilRefusalError("MALFORMED_DATA_REFUSED", "Invalid call_graph_or_repo passed to slice_call_graph.")

    symbols: Dict[str, Dict[str, Any]] = cg["symbols"]
    class_methods: Dict[str, Dict[str, str]] = cg["class_methods"]
    class_bases: Dict[str, List[str]] = cg["class_bases"]
    raw_desc: Dict[str, List[str]] = cg.get("class_descendants") or {}
    class_descendants: Dict[str, Set[str]] = {c: set(raw_desc.get(c, [c])) for c in class_methods}
    raw_self_attrs: Dict[str, List[str]] = cg.get("active_self_attr_classes") or {}
    active_self_attr_classes: Dict[Tuple[str, str], Set[str]] = {}
    for comp_k, cls_list in raw_self_attrs.items():
        if "::" in comp_k:
            c_id, a_nm = comp_k.split("::", 1)
            active_self_attr_classes[(c_id, a_nm)] = set(cls_list)

    direct_edges: Dict[str, List[str]] = cg["direct_edges"]
    init_non_exit_edges: Dict[str, List[str]] = cg.get("init_non_exit_edges") or {}
    init_exit_attr_callees: Dict[str, Dict[str, List[str]]] = cg.get("init_exit_attr_callees") or {}
    conditional_super_edges: Dict[str, List[Tuple[str, Set[str]]]] = cg.get("conditional_super_edges") or {}
    unresolved_method_calls: Dict[str, List[str]] = cg.get("unresolved_method_calls") or {}
    virtual_self_calls: Dict[str, List[Tuple[str, str]]] = cg.get("virtual_self_calls") or {}
    virtual_self_attr_calls: Dict[str, List[Tuple[str, str, str]]] = cg.get("virtual_self_attr_calls") or {}
    virtual_self_getattr: Dict[str, List[Tuple[str, str]]] = cg.get("virtual_self_getattr") or {}
    unres_getattr_prefixes: Dict[str, List[str]] = cg.get("unres_getattr_prefixes") or {}
    dynamic_import_owners: Set[str] = set(cg.get("dynamic_import_owners") or [])
    dynamic_edges: Dict[str, List[str]] = cg.get("dynamic_edges") or {}
    decorated_registry_syms: Set[str] = set(cg.get("decorated_registry_syms") or [])
    file_entry_roots: Dict[str, Dict[str, Any]] = cg.get("file_entry_roots") or {}
    import_graph: Dict[str, List[str]] = cg.get("import_graph") or {}

    caller_supplied_eps = entrypoints is not None and len(list(entrypoints)) > 0
    raw_eps = list(entrypoints or [])
    if not raw_eps and cg.get("repo_root"):
        r_p = Path(str(cg["repo_root"]))
        if r_p.is_dir():
            disc = discover_paper_matched_scopes(r_p)
            for p_obj in disc.get("pipelines") or []:
                for ep_item in p_obj.get("entrypoints") or []:
                    if ep_item not in raw_eps:
                        raw_eps.append(ep_item)
        if not raw_eps:
            main_f = [f for f, meta in file_entry_roots.items() if meta.get("has_top_exec")]
            raw_eps = sorted(main_f) if main_f else sorted({m["file"] for m in symbols.values() if m.get("file")})

    reached: Set[str] = set()
    uncertain: Set[str] = set()
    seed_files: List[str] = []
    seed_unresolved_methods: Set[str] = set()
    seed_getattr_prefixes: List[str] = []
    normalized_eps: List[str] = []
    unresolved_entrypoints: List[str] = []

    by_short: Dict[str, List[str]] = {}
    by_file: Dict[str, List[str]] = {}
    for sid, smeta in symbols.items():
        by_short.setdefault(smeta["short_name"], []).append(sid)
        if smeta.get("file"):
            by_file.setdefault(smeta["file"], []).append(sid)

    for raw_ep in raw_eps:
        ep_str = _strip_leading_dot_slash(str(raw_ep or "").strip().replace("\\", "/"))
        if not ep_str:
            if caller_supplied_eps:
                unresolved_entrypoints.append(str(raw_ep))
            continue
        normalized_eps.append(ep_str)
        if ep_str in symbols:
            reached.add(ep_str)
            if symbols[ep_str].get("file"):
                seed_files.append(symbols[ep_str]["file"])
            continue
        if ":" in ep_str:
            f_part, s_part = ep_str.split(":", 1)
            f_norm = _strip_leading_dot_slash(f_part)
            cand_sid = f"{f_norm}:{s_part}"
            if cand_sid in symbols:
                if f_norm in import_graph or f_norm in by_file or f_norm in file_entry_roots:
                    seed_files.append(f_norm)
                reached.add(cand_sid)
                if symbols[cand_sid].get("kind") == "class":
                    for init_sid in class_methods.get(cand_sid, {}).values():
                        if init_sid.endswith(".__init__"):
                            reached.add(init_sid)
                continue
            unresolved_entrypoints.append(ep_str)
            continue

        matched_f = ep_str if (ep_str in file_entry_roots or ep_str in by_file or ep_str in import_graph) else ""
        if not matched_f:
            stem_cands = [f for f in set(list(by_file.keys()) + list(import_graph.keys()) + list(file_entry_roots.keys())) if Path(f).name == Path(ep_str).name]
            if len(stem_cands) == 1:
                matched_f = stem_cands[0]
        if matched_f:
            seed_files.append(matched_f)
            f_root = file_entry_roots.get(matched_f) or {}
            if f_root.get("has_top_exec"):
                reached.update(f_root.get("static_callees") or [])
                uncertain.update(f_root.get("dynamic_callees") or [])
                seed_unresolved_methods.update(f_root.get("unresolved_methods") or [])
                for gp in f_root.get("unresolved_getattr_prefixes") or []:
                    if gp not in seed_getattr_prefixes:
                        seed_getattr_prefixes.append(gp)
            else:
                for f_sid in by_file.get(matched_f, []):
                    sm = symbols[f_sid]
                    if sm["kind"] in ("function", "class") and not sm["short_name"].startswith("_"):
                        reached.add(f_sid)
                        if sm["kind"] == "class" and "__init__" in class_methods.get(f_sid, {}):
                            reached.add(class_methods[f_sid]["__init__"])
        elif ep_str in by_short:
            reached.update(by_short[ep_str])
            for m_sid in by_short[ep_str]:
                if symbols[m_sid].get("file"):
                    seed_files.append(symbols[m_sid]["file"])
        else:
            unresolved_entrypoints.append(ep_str)

    # Seed module-level import-time execution (`GRID = build_grid()`, `NODES = build_nodes(8)`)
    # across all entrypoint files AND their transitive import closure!
    seeded_import_files: Set[str] = set()

    def _seed_import_closure_roots(files_to_load: Sequence[str]) -> bool:
        added_any = False
        closure_f = (set(_compute_import_closure(list(files_to_load), import_graph)) if import_graph else set()) | set(files_to_load)
        for lf in sorted(closure_f):
            if not lf or lf in seeded_import_files:
                continue
            seeded_import_files.add(lf)
            f_meta = file_entry_roots.get(lf) or {}
            for st_c in f_meta.get("import_static_callees") or []:
                if st_c in symbols and st_c not in reached:
                    reached.add(st_c)
                    added_any = True
            for dy_c in f_meta.get("import_dynamic_callees") or []:
                if dy_c in symbols and dy_c not in reached and dy_c not in uncertain:
                    uncertain.add(dy_c)
                    added_any = True
            for um_c in f_meta.get("import_unresolved_methods") or []:
                if um_c not in seed_unresolved_methods:
                    seed_unresolved_methods.add(um_c)
                    added_any = True
            for gp_c in f_meta.get("import_unresolved_getattr_prefixes") or []:
                if gp_c not in seed_getattr_prefixes:
                    seed_getattr_prefixes.append(gp_c)
                    added_any = True
        return added_any

    if not (caller_supplied_eps and unresolved_entrypoints):
        _seed_import_closure_roots(seed_files)

    def _lookup_methods_h(csid: str, mname: str, _seen: Optional[Set[str]] = None) -> List[str]:
        """Resolve `mname` along MRO of `csid`, stopping along any base branch once overridden."""
        seen_c = _seen if _seen is not None else set()
        if csid in seen_c:
            return []
        seen_c.add(csid)
        if mname in class_methods.get(csid, {}):
            return [class_methods[csid][mname]]
        out: List[str] = []
        for b_sid in class_bases.get(csid, ()):
            for bh in _lookup_methods_h(b_sid, mname, seen_c):
                if bh not in out:
                    out.append(bh)
        return out

    # Fixpoint propagation for `reached` (with RTA virtual dispatch, subclass overrides, and `super().__init__` filtering)
    unshadowed_init_entries: Set[str] = {
        sid for sid in reached if sid.endswith(".__init__")
    }
    changed = not (caller_supplied_eps and unresolved_entrypoints)
    while changed:
        changed = False
        # Also ensure newly reached files have their module-level import-time top-level calls seeded
        cur_reached_files = [symbols[s]["file"] for s in reached if symbols.get(s, {}).get("file")]
        if cur_reached_files and _seed_import_closure_roots(cur_reached_files):
            changed = True

        instantiated_reached_classes: Set[str] = {
            sid for sid in reached if symbols.get(sid, {}).get("kind") == "class"
        }
        active_unres_m: Set[str] = set(seed_unresolved_methods)
        for r_sid in list(reached):
            s_kind = symbols.get(r_sid, {}).get("kind", "")
            if s_kind == "class":
                init_targets = _lookup_methods_h(r_sid, "__init__")
                if init_targets:
                    lead_init = init_targets[0]
                    if lead_init not in unshadowed_init_entries:
                        unshadowed_init_entries.add(lead_init)
                        changed = True
                    if lead_init not in reached:
                        reached.add(lead_init)
                        changed = True

            if (
                r_sid.endswith(".__init__")
                and r_sid not in unshadowed_init_entries
                and r_sid in init_non_exit_edges
            ):
                edges_to_follow = list(init_non_exit_edges[r_sid])
            else:
                edges_to_follow = list(direct_edges.get(r_sid) or [])

            for tgt in edges_to_follow:
                if tgt in symbols and tgt not in reached:
                    reached.add(tgt)
                    changed = True

            for base_init_sid, overwritten_attrs in conditional_super_edges.get(r_sid) or []:
                if base_init_sid in symbols and base_init_sid not in reached:
                    reached.add(base_init_sid)
                    changed = True
                for attr_k, attr_callees in (init_exit_attr_callees.get(base_init_sid) or {}).items():
                    if attr_k not in overwritten_attrs:
                        for ac in attr_callees:
                            if ac in symbols and ac not in reached:
                                reached.add(ac)
                                changed = True

            # Virtual `self.<method>` calls/callbacks/properties: resolve on instantiated subclasses of `enc_cls`!
            for enc_cls, m_attr in virtual_self_calls.get(r_sid) or []:
                inst_subs = sorted(class_descendants.get(enc_cls, {enc_cls}) & instantiated_reached_classes)
                candidate_receivers = inst_subs if inst_subs else [enc_cls]
                for recv_c in candidate_receivers:
                    m_hits = _lookup_methods_h(recv_c, m_attr)
                    if m_hits:
                        for mh in m_hits:
                            if mh in symbols and mh not in reached:
                                reached.add(mh)
                                changed = True
                    else:
                        for sc_sid in sorted(active_self_attr_classes.get((recv_c, m_attr), set())):
                            for lc_m in ("__call__", "forward"):
                                for mh in _lookup_methods_h(sc_sid, lc_m):
                                    if mh in symbols and mh not in reached:
                                        reached.add(mh)
                                        changed = True

            # Virtual `self.<attr>.<method>(...)` calls: honor subclass `self.<attr>` overrides!
            for enc_cls, a_nm, m_nm in virtual_self_attr_calls.get(r_sid) or []:
                inst_subs = sorted(class_descendants.get(enc_cls, {enc_cls}) & instantiated_reached_classes)
                candidate_receivers = inst_subs if inst_subs else [enc_cls]
                resolved_any_attr = False
                for recv_c in candidate_receivers:
                    attr_classes = active_self_attr_classes.get((recv_c, a_nm), set())
                    if attr_classes:
                        resolved_any_attr = True
                        for sc_sid in sorted(attr_classes):
                            for mh in _lookup_methods_h(sc_sid, m_nm):
                                if mh in symbols and mh not in reached:
                                    reached.add(mh)
                                    changed = True
                if not resolved_any_attr:
                    active_unres_m.add(m_nm)

            active_unres_m.update(unresolved_method_calls.get(r_sid) or [])
            for dyn_tgt in dynamic_edges.get(r_sid) or []:
                if dyn_tgt in symbols and dyn_tgt not in reached and dyn_tgt not in uncertain:
                    uncertain.add(dyn_tgt)
                    changed = True

        # Resolve unresolved `.method()` / dunder / property accesses over RTA-instantiated `reached` classes!
        for mname in active_unres_m:
            for inst_csid in instantiated_reached_classes:
                for m_sid in _lookup_methods_h(inst_csid, mname):
                    if m_sid not in reached:
                        reached.add(m_sid)
                        changed = True
            if mname in ("forward", "__call__"):
                for inst_csid in instantiated_reached_classes:
                    for lc_m in ("forward", "__call__"):
                        for m_sid in _lookup_methods_h(inst_csid, lc_m):
                            if m_sid not in reached:
                                reached.add(m_sid)
                                changed = True

    # Any non-stdlib registration-decorated function/class in loaded modules (or repo-wide if `importlib.import_module` is dynamic)
    has_dyn_import = bool((reached | uncertain) & dynamic_import_owners)
    load_time_files_set = set(_compute_import_closure(seed_files, import_graph)) | set(seed_files) | seeded_import_files
    if not (caller_supplied_eps and unresolved_entrypoints):
        for reg_sid in decorated_registry_syms:
            reg_file = symbols.get(reg_sid, {}).get("file") or ""
            in_scope_mod = (
                (not load_time_files_set)
                or (reg_file in load_time_files_set)
                or (has_dyn_import and not _is_historical_clutter_path(reg_file))
            )
            if in_scope_mod and reg_sid not in reached:
                uncertain.add(reg_sid)

    # Fixpoint propagation for `uncertain`
    uncertain -= reached
    changed_u = not (caller_supplied_eps and unresolved_entrypoints)
    while changed_u:
        changed_u = False
        all_active_syms = reached | uncertain
        instantiated_all_classes: Set[str] = {
            sid for sid in all_active_syms if symbols.get(sid, {}).get("kind") == "class"
        }
        instantiated_unc_classes: Set[str] = {
            sid for sid in uncertain if symbols.get(sid, {}).get("kind") == "class"
        }
        all_unres_for_unc: Set[str] = set(seed_unresolved_methods)
        active_getattr_prefs: List[str] = list(seed_getattr_prefixes)
        for a_sid in all_active_syms:
            all_unres_for_unc.update(unresolved_method_calls.get(a_sid) or [])
            for gp in unres_getattr_prefixes.get(a_sid) or []:
                if gp not in active_getattr_prefs:
                    active_getattr_prefs.append(gp)
            for enc_c, pref_h in virtual_self_getattr.get(a_sid) or []:
                cands_c = sorted(class_descendants.get(enc_c, {enc_c}) & instantiated_all_classes) or [enc_c]
                for rc in cands_c:
                    for m_nm, m_sid in class_methods.get(rc, {}).items():
                        if m_nm.startswith("__"):
                            continue
                        if pref_h and not m_nm.startswith(pref_h):
                            continue
                        if m_sid not in reached and m_sid not in uncertain:
                            uncertain.add(m_sid)
                            changed_u = True

        # Cross-file `getattr(instance, dyn_name)` over all RTA-instantiated classes!
        if active_getattr_prefs:
            for inst_c in sorted(instantiated_all_classes):
                cur_stack = [inst_c]
                seen_ic: Set[str] = set()
                while cur_stack:
                    cc = cur_stack.pop()
                    if cc in seen_ic:
                        continue
                    seen_ic.add(cc)
                    for m_nm, m_sid in class_methods.get(cc, {}).items():
                        if m_nm.startswith("__"):
                            continue
                        if any((not pf) or m_nm.startswith(pf) for pf in active_getattr_prefs):
                            if m_sid not in reached and m_sid not in uncertain:
                                uncertain.add(m_sid)
                                changed_u = True
                    cur_stack.extend(class_bases.get(cc, ()))

        for u_sid in list(uncertain):
            u_kind = symbols.get(u_sid, {}).get("kind", "")
            if u_kind == "class":
                for m_nm, m_sid in class_methods.get(u_sid, {}).items():
                    if (m_nm in ("__init__", "__call__", "forward") or not m_nm.startswith("_")) and m_sid not in reached and m_sid not in uncertain:
                        uncertain.add(m_sid)
                        changed_u = True
            for tgt in list(direct_edges.get(u_sid) or []) + list(dynamic_edges.get(u_sid) or []):
                if tgt in symbols and tgt not in reached and tgt not in uncertain:
                    uncertain.add(tgt)
                    changed_u = True
            for enc_cls, m_attr in virtual_self_calls.get(u_sid) or []:
                cands_u = sorted(class_descendants.get(enc_cls, {enc_cls}) & instantiated_all_classes) or [enc_cls]
                for recv_u in cands_u:
                    for mh in _lookup_methods_h(recv_u, m_attr):
                        if mh in symbols and mh not in reached and mh not in uncertain:
                            uncertain.add(mh)
                            changed_u = True
            for enc_cls, a_nm, m_nm in virtual_self_attr_calls.get(u_sid) or []:
                cands_u = sorted(class_descendants.get(enc_cls, {enc_cls}) & instantiated_all_classes) or [enc_cls]
                for recv_u in cands_u:
                    for sc_sid in sorted(active_self_attr_classes.get((recv_u, a_nm), set())):
                        for mh in _lookup_methods_h(sc_sid, m_nm):
                            if mh in symbols and mh not in reached and mh not in uncertain:
                                uncertain.add(mh)
                                changed_u = True

        for mname in all_unres_for_unc:
            for u_csid in instantiated_unc_classes:
                for m_sid in _lookup_methods_h(u_csid, mname):
                    if m_sid not in reached and m_sid not in uncertain:
                        uncertain.add(m_sid)
                        changed_u = True

    uncertain -= reached
    if caller_supplied_eps and unresolved_entrypoints:
        reached = set()
        uncertain = set()
    unreached: Set[str] = set(symbols.keys()) - reached - uncertain

    sorted_reached = sorted(reached)
    sorted_uncertain = sorted(uncertain)
    sorted_unreached = sorted(unreached)

    def _pack_sym(sid: str, badge: str) -> Dict[str, Any]:
        meta = dict(symbols[sid])
        meta["badge"] = badge
        meta["reachability_badge"] = badge
        return meta

    badges: Dict[str, str] = {}
    for sid in sorted_reached:
        badges[sid] = "reached"
    for sid in sorted_uncertain:
        badges[sid] = "uncertain"
    for sid in sorted_unreached:
        badges[sid] = "unreached"

    active_sym_files = {
        symbols[sid]["file"]
        for sid in (reached | uncertain)
        if symbols[sid].get("file")
    } | (set() if (caller_supplied_eps and unresolved_entrypoints) else set(seed_files))
    load_time_imported_files = sorted(
        (set(_compute_import_closure(sorted(active_sym_files), import_graph)) if (import_graph and active_sym_files) else set())
        | active_sym_files
    )

    is_ok = not (caller_supplied_eps and len(unresolved_entrypoints) > 0)
    out_slice: Dict[str, Any] = {
        "ok": is_ok,
        "schema": SYMBOL_SLICE_SCHEMA,
        "entrypoints": normalized_eps,
        "unresolved_entrypoints": unresolved_entrypoints,
        "reached": sorted_reached,
        "uncertain": sorted_uncertain,
        "unreached": sorted_unreached,
        "reached_symbols": [_pack_sym(sid, "reached") for sid in sorted_reached],
        "uncertain_symbols": [_pack_sym(sid, "uncertain") for sid in sorted_uncertain],
        "unreached_symbols": [_pack_sym(sid, "unreached") for sid in sorted_unreached],
        "badges": badges,
        "shadowed_allocations": list(cg.get("shadowed_allocations") or []),
        "dynamic_dispatch_sites": list(cg.get("dynamic_dispatch_sites") or []),
        "load_time_imported_files": [f for f in load_time_imported_files if f],
        "active_files": sorted(f for f in active_sym_files if f),
    }
    if not is_ok:
        out_slice["error_code"] = "ENTRYPOINT_UNRESOLVED_REFUSED"
        out_slice["message"] = f"Unresolved entrypoint(s): {', '.join(unresolved_entrypoints)}"
    return out_slice


def _extract_manuscript_equations_static(
    paper_target: Optional[Path],
    *,
    allowed_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Extract numbered/display LaTeX equations (`equation`, `align`, `eqnarray`, `\\[...\\]`, `$$...$$`)
    with section context and `\\label{...}` from `.tex`/`.md` files (zero execution).
    """
    if paper_target is None or not paper_target.exists():
        return []
    if paper_target.is_dir():
        entry_f = _pick_main_tex_file(paper_target.resolve())
        paper_root = paper_target.resolve()
    else:
        entry_f = paper_target.resolve()
        paper_root = entry_f.parent.resolve()
    if entry_f is None or not entry_f.is_file():
        return []

    eff_bound = allowed_root.resolve() if allowed_root is not None else paper_root
    import anvil_latex_mathml as _alm
    try:
        ms_bundle = _alm.resolve_manuscript_bundle(entry_f, allowed_root=eff_bound, strict_include_refusal=True)
    except _alm.AnvilLatexSecurityError as sec_exc:
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            str(sec_exc),
            cwe="CWE-22",
            details={"candidate": sec_exc.candidate, "http_status": 403},
        ) from sec_exc
    macro_tbl = ms_bundle.get("macros") or {}
    aux_lbls = ms_bundle.get("aux_labels") or {}

    visited_f: Set[Path] = set()
    equations: List[Dict[str, Any]] = []
    inc_re = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
    sec_re = re.compile(r"\\(section|subsection|appendix)\*?\s*(\{)?")
    env_open_re = re.compile(r"\\begin\{(equation\*?|align\*?|eqnarray\*?|gather\*?|multline\*?)\}")
    lbl_re = re.compile(r"\\label\s*\{([^{}]+)\}")

    def _pack_eq_record(eq_lbl: str, active_sec: str, rtf: Path, lno: int, clean_ltx: str, recent_prose: List[str]) -> Dict[str, Any]:
        mml = _alm.latex_to_mathml_safe(clean_ltx, macro_tbl, display_block=True)
        return {
            "id": f"eq-{len(equations) + 1}",
            "label": eq_lbl,
            "eq_number": str(aux_lbls.get(eq_lbl) or ""),
            "section": active_sec,
            "source_file": rtf.name,
            "line": lno,
            "raw_latex": clean_ltx,
            "expanded_latex": mml["expanded_latex"],
            "mathml": mml["mathml"],
            "mathml_mode": mml["mode"],
            "normalized_symbols": mml["normalized_symbols"],
            "context_prose": " ".join(recent_prose[-3:])[:240],
        }

    def _walk_eq_file(tf: Path, cur_sec: str) -> str:
        rtf = tf.resolve()
        if rtf in visited_f or not rtf.is_file():
            return cur_sec
        visited_f.add(rtf)
        try:
            lines = rtf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return cur_sec

        active_sec = cur_sec
        recent_prose: List[str] = []
        idx = 0
        n = len(lines)
        while idx < n:
            clean_ln = _strip_tex_comment_line(lines[idx])
            lno = idx + 1
            idx += 1

            for sm in sec_re.finditer(clean_ln):
                if sm.group(2) == "{":
                    raw_s, _ = _extract_balanced_brace_group(clean_ln, sm.end() - 1)
                    stitle = strip_latex_nested_braces(raw_s, max_depth=2)
                    if stitle:
                        active_sec = stitle
                        recent_prose = []

            for im in inc_re.finditer(clean_ln):
                raw_trim = im.group(1).strip().strip('"').strip("'")
                if not raw_trim:
                    continue
                if raw_trim.startswith(("\\\\", "//", "/", "\\")) or ":" in raw_trim:
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Manuscript child '{raw_trim}' uses rooted, UNC, or drive-qualified path.",
                        cwe="CWE-22",
                        details={"candidate": raw_trim, "http_status": 403},
                    )
                inc_raw = raw_trim.replace("\\", "/")
                for bd in (rtf.parent, paper_root):
                    found_c: Optional[Path] = None
                    for suf in ("", ".tex"):
                        norm_inc = Path(os.path.normpath(str(bd / f"{inc_raw}{suf}")))
                        if not (norm_inc == eff_bound or norm_inc.is_relative_to(eff_bound)):
                            continue
                        has_lnk = False
                        cur_h = eff_bound
                        for hp in norm_inc.relative_to(eff_bound).parts:
                            cur_h = cur_h / hp
                            if _is_link_or_junction(cur_h):
                                has_lnk = True
                                break
                        if not has_lnk and norm_inc.is_file() and norm_inc.resolve().is_relative_to(eff_bound):
                            found_c = norm_inc.resolve()
                            break
                    if found_c is not None:
                        active_sec = _walk_eq_file(found_c, active_sec)
                        break

            m_open = env_open_re.search(clean_ln)
            if m_open:
                env_name = m_open.group(1)
                close_pat = f"\\end{{{env_name}}}"
                buf = [clean_ln[m_open.end():]]
                while idx < n:
                    nxt = _strip_tex_comment_line(lines[idx])
                    idx += 1
                    if close_pat in nxt:
                        buf.append(nxt.split(close_pat, 1)[0])
                        break
                    buf.append(nxt)
                body_ltx = "\n".join(buf).strip()
                m_lbl = lbl_re.search(body_ltx)
                eq_lbl = m_lbl.group(1).strip() if m_lbl else f"eq:{len(equations) + 1}"
                clean_ltx = lbl_re.sub("", body_ltx).strip()
                if clean_ltx:
                    equations.append(_pack_eq_record(eq_lbl, active_sec, rtf, lno, clean_ltx, recent_prose))
                continue

            if "\\[" in clean_ln or "$$" in clean_ln:
                delim_open = "\\[" if "\\[" in clean_ln else "$$"
                delim_close = "\\]" if delim_open == "\\[" else "$$"
                after = clean_ln.split(delim_open, 1)[1]
                if delim_close in after:
                    body_ltx = after.split(delim_close, 1)[0].strip()
                else:
                    buf_d = [after]
                    while idx < n:
                        nxt_d = _strip_tex_comment_line(lines[idx])
                        idx += 1
                        if delim_close in nxt_d:
                            buf_d.append(nxt_d.split(delim_close, 1)[0])
                            break
                        buf_d.append(nxt_d)
                    body_ltx = "\n".join(buf_d).strip()
                m_lbl = lbl_re.search(body_ltx)
                eq_lbl = m_lbl.group(1).strip() if m_lbl else f"eq:{len(equations) + 1}"
                clean_ltx = lbl_re.sub("", body_ltx).strip()
                if clean_ltx:
                    equations.append(_pack_eq_record(eq_lbl, active_sec, rtf, lno, clean_ltx, recent_prose))
                continue

            stripped_prose = strip_latex_nested_braces(clean_ln, max_depth=1).strip()
            if stripped_prose and not stripped_prose.startswith("\\"):
                recent_prose.append(stripped_prose)
        return active_sec

    _walk_eq_file(entry_f, "Main")
    return equations


def _tokenize_equation_anchors(eq_obj: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    """Return `(distinctive_tokens, math_op_hints)` extracted from an equation + expanded macros + label + prose."""
    raw_ltx = f"{eq_obj.get('raw_latex') or ''} {eq_obj.get('expanded_latex') or ''}"
    lbl = re.sub(r"^(?:eq|eqn)[:_]", "", str(eq_obj.get("label") or "").lower())
    norm_s = " ".join(eq_obj.get("normalized_symbols") or [])
    ctx = f"{eq_obj.get('section', '')} {eq_obj.get('context_prose', '')} {norm_s}"

    raw_words = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", f"{raw_ltx} {lbl} {ctx}")
    toks: Set[str] = set()
    for w in raw_words:
        for sub in _tokenize_stage_ident(w):
            if len(sub) >= 2 and sub not in _EQUATION_GENERIC_STOPWORDS:
                toks.add(sub)
                if sub in _GREEK_TO_CODE_ALIASES:
                    toks.update(_GREEK_TO_CODE_ALIASES[sub])

    op_hints: Set[str] = set()
    low_ltx = raw_ltx.lower()
    if any(k in low_ltx for k in ("\\exp", "softmax", "logsumexp")):
        op_hints.update({"exp", "softmax", "logsumexp"})
    if any(k in low_ltx for k in ("\\log", "\\ln")):
        op_hints.update({"log", "logsumexp", "log_prob", "nll"})
    if "\\sum" in low_ltx:
        op_hints.add("sum")
    if any(k in low_ltx for k in ("\\det", "jacobian", "logdet", "slogdet", "cholesky")):
        op_hints.update({" slogdet", "logdet", "cholesky", "jacobian", "det"})
    if any(k in low_ltx for k in ("\\norm", "\\|", "^2")):
        op_hints.update({"norm", "pow", "square"})
    return toks, op_hints


def bind_manuscript_equations_to_symbols(
    repo_root: str | Path,
    paper_path: str | Path,
    *,
    entrypoints: Optional[Sequence[str]] = None,
    symbol_slice: Optional[Dict[str, Any]] = None,
    scope_files: Optional[Sequence[str | Path]] = None,
    allowed_root: Optional[str | Path] = None,
    scoped: bool = True,
) -> Dict[str, Any]:
    """Bind manuscript LaTeX equations strictly to active (`reached` + `uncertain`) symbols when
    `scoped=True` (or `symbol_slice`/`entrypoints` is supplied), excluding statically `unreached`
    symbols from active bindings, disclosing `unreached_symbols`, and flagging equations with no
    active match explicitly in `unbound_equations` (`status: "unbound"`).
    """
    repo_resolved = Path(repo_root).resolve()
    resolved_paper = resolve_manuscript_path(repo_resolved, paper_path, allowed_root=allowed_root)
    eff_bound = Path(allowed_root).resolve() if allowed_root is not None else resolved_paper.parent.resolve()
    equations = _extract_manuscript_equations_static(resolved_paper, allowed_root=eff_bound)

    active_slice = symbol_slice
    if active_slice is None and (scoped or entrypoints is not None):
        active_slice = slice_call_graph(repo_resolved, entrypoints=entrypoints, scope_files=scope_files)

    # Extract rich AST identifier/operator profiles per symbol (zero execution)
    prod_fps, _ = _scan_contained_source_files(repo_resolved)
    if scope_files is not None:
        allowed_rels = {_validate_strict_contained_rel_file(repo_resolved, sf)[0] for sf in scope_files}
        prod_fps = [fp for fp in prod_fps if fp.relative_to(repo_resolved).as_posix() in allowed_rels]

    sym_profiles: Dict[str, Dict[str, Any]] = {}
    for fp in prod_fps:
        if fp.suffix.lower() != ".py":
            continue
        rel = fp.relative_to(repo_resolved).as_posix()
        txt = fp.read_text(encoding="utf-8-sig", errors="replace")
        tree = _parse_python_ast_quiet(txt, filename=rel)
        if tree is None:
            continue

        def _profile_fn(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, cls_nm: str = "") -> None:
            qname = f"{cls_nm}.{fn_node.name}" if cls_nm else fn_node.name
            sid = f"{rel}:{qname}"
            ident_toks: Set[str] = set(_tokenize_stage_ident(qname)) | set(_tokenize_stage_ident(Path(rel).stem))
            doc_s = ast.get_docstring(fn_node) or ""
            for dw in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", doc_s):
                ident_toks.update(_tokenize_stage_ident(dw))
            op_toks: Set[str] = set()
            has_math_expr = False
            for ch in ast.walk(fn_node):
                if isinstance(ch, ast.arg):
                    ident_toks.update(_tokenize_stage_ident(ch.arg))
                elif isinstance(ch, ast.Name):
                    ident_toks.update(_tokenize_stage_ident(ch.id))
                elif isinstance(ch, ast.Attribute):
                    ident_toks.update(_tokenize_stage_ident(ch.attr))
                    op_toks.add(ch.attr.lower())
                elif isinstance(ch, ast.BinOp) and isinstance(ch.op, (ast.Mult, ast.Div, ast.Pow, ast.MatMult, ast.Sub, ast.Add)):
                    has_math_expr = True
                elif isinstance(ch, ast.Call):
                    cname = ch.func.id if isinstance(ch.func, ast.Name) else (ch.func.attr if isinstance(ch.func, ast.Attribute) else "")
                    if cname:
                        op_toks.add(cname.lower())
                        if cname.lower() in {"exp", "log", "logsumexp", "softmax", "sum", "mean", "matmul", "einsum", "solve", "cholesky", "slogdet", "norm"}:
                            has_math_expr = True
            ident_toks = {t for t in ident_toks if len(t) >= 2 and t not in _EQUATION_GENERIC_STOPWORDS}
            sym_profiles[sid] = {
                "id": sid,
                "file": rel,
                "symbol": qname,
                "short_name": fn_node.name,
                "class_name": cls_nm,
                "start_line": int(getattr(fn_node, "lineno", 1)),
                "end_line": int(getattr(fn_node, "end_lineno", 1) or 1),
                "ident_tokens": ident_toks,
                "op_tokens": op_toks,
                "has_math_expr": has_math_expr,
            }

        for st in tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _profile_fn(st, "")
            elif isinstance(st, ast.ClassDef):
                for mst in st.body:
                    if isinstance(mst, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _profile_fn(mst, st.name)

    badges = dict(active_slice.get("badges") or {}) if active_slice is not None else {}
    unreached_set = set(active_slice.get("unreached") or []) if active_slice is not None else set()
    shadowed_sym_set: Set[str] = set()
    if active_slice is not None:
        for sh in active_slice.get("shadowed_allocations") or []:
            for s_id in sh.get("shadowed_symbols") or []:
                shadowed_sym_set.add(str(s_id))
                # If a class was shadowed and not reached elsewhere, exclude all its methods too
                if s_id in unreached_set:
                    c_prefix = f"{s_id}."
                    for cand_k in sym_profiles:
                        if cand_k.startswith(c_prefix):
                            shadowed_sym_set.add(cand_k)

    def _score_eq_vs_profile(eq_toks: Set[str], eq_ops: Set[str], prof: Dict[str, Any]) -> Tuple[float, List[str]]:
        if prof["short_name"] == "__init__" and not prof["has_math_expr"]:
            return 0.0, []
        overlap = sorted(eq_toks & prof["ident_tokens"])
        if not overlap:
            return 0.0, []
        op_overlap = eq_ops & prof["op_tokens"]
        score = float(len(overlap)) * 2.0 + float(len(op_overlap)) * 1.5 + (1.0 if prof["has_math_expr"] else 0.0)
        return round(score, 3), overlap

    bound_equations: List[Dict[str, Any]] = []
    unbound_equations: List[Dict[str, Any]] = []
    all_equation_records: List[Dict[str, Any]] = []

    for eq in equations:
        eq_toks, eq_ops = _tokenize_equation_anchors(eq)
        active_matches: List[Dict[str, Any]] = []
        excluded_unreached_matches: List[Dict[str, Any]] = []

        for sid, prof in sym_profiles.items():
            sc, ov = _score_eq_vs_profile(eq_toks, eq_ops, prof)
            if sc < 2.5:
                continue
            badge = badges.get(sid, "reached" if active_slice is None else "unreached")
            cand_rec = {
                "symbol_id": sid,
                "file": prof["file"],
                "symbol": prof["symbol"],
                "start_line": prof["start_line"],
                "end_line": prof["end_line"],
                "score": sc,
                "matched_tokens": ov,
                "reachability_badge": badge,
            }
            if active_slice is not None and (sid in unreached_set or badge == "unreached" or (sid in shadowed_sym_set and badge != "reached")):
                excluded_unreached_matches.append(cand_rec)
            else:
                active_matches.append(cand_rec)

        active_matches.sort(key=lambda m: (-m["score"], 0 if m["reachability_badge"] == "reached" else 1, m["symbol_id"]))
        excluded_unreached_matches.sort(key=lambda m: (-m["score"], m["symbol_id"]))

        if active_matches:
            top = active_matches[0]
            rec = {
                **eq,
                "status": "bound",
                "bound_symbol": top["symbol_id"],
                "bound_file": top["file"],
                "bound_qualname": top["symbol"],
                "reachability_badge": top["reachability_badge"],
                "matched_symbols": active_matches[:5],
                "excluded_unreached_candidates": excluded_unreached_matches[:5],
            }
            bound_equations.append(rec)
            all_equation_records.append(rec)
        else:
            rec = {
                **eq,
                "status": "unbound",
                "bound_symbol": None,
                "bound_file": None,
                "bound_qualname": None,
                "reachability_badge": None,
                "matched_symbols": [],
                "excluded_unreached_candidates": excluded_unreached_matches[:5],
            }
            unbound_equations.append(rec)
            all_equation_records.append(rec)

    return {
        "ok": True,
        "schema": EQUATION_BINDING_SCHEMA,
        "paper_path": resolved_paper.name,
        "equations": all_equation_records,
        "bound_equations": bound_equations,
        "unbound_equations": unbound_equations,
        "reached_symbols": list(active_slice.get("reached_symbols") or []) if active_slice else [],
        "uncertain_symbols": list(active_slice.get("uncertain_symbols") or []) if active_slice else [],
        "unreached_symbols": list(active_slice.get("unreached_symbols") or []) if active_slice else [],
        "shadowed_allocations": list(active_slice.get("shadowed_allocations") or []) if active_slice else [],
    }


def _make_opaque_module_id(raw_slug: str, used_ids: Set[str]) -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "_", (raw_slug or "mod").lower()).strip("_-")
    if not clean:
        clean = "mod_cluster"
    if not clean.startswith("m_"):
        clean = f"m_{clean}"
    clean = clean[:48].rstrip("_-") or "m_cluster"
    cand = clean
    idx = 2
    while cand in used_ids:
        cand = f"{clean}_{idx}"
        idx += 1
    used_ids.add(cand)
    return cand


_SINGLE_REPO_SLICE_CACHE: Dict[Tuple[Any, ...], Tuple[List[Path], List[Path], Dict[str, Any], List[str], Dict[str, Any]]] = {}


def build_software_architecture_paper_map(
    repo_root: str | Path,
    *,
    paper_path: Optional[str | Path] = None,
    cockpit_root: Optional[str | Path] = None,
    sibling_repos: Optional[Sequence[str | Path]] = None,
    selected_module_ids: Optional[Sequence[str]] = None,
    saved_scope_module_ids: Optional[Sequence[str]] = None,
    entrypoints: Optional[Sequence[str]] = None,
    literature_overlays: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Partition `repo_root` (and optional `sibling_repos` in a multi-repo AI Cockpit) into
    clean, human-meaningful architectural modules with deterministic opaque module IDs
    (`^[a-z0-9_-]+$`), file lists, symbol reachability counts, `scope_status`
    (`in_scope`, `saved_scope`, `available`, `unscoped_plumbing`), local paper/table/section
    links, and optional `external_literature` slots (`claimed` / `not_requested`).
    """
    raw_repo = Path(repo_root)
    if _is_link_or_junction(raw_repo) or not raw_repo.exists() or not raw_repo.is_dir():
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            "Repository root does not exist or is a symlink/junction.",
            cwe="CWE-22",
            details={"http_status": 403},
        )
    repo_resolved = raw_repo.resolve()

    cockpit_resolved: Optional[Path] = None
    if cockpit_root is not None and str(cockpit_root).strip():
        raw_ck = Path(cockpit_root)
        if _is_link_or_junction(raw_ck) or not raw_ck.exists() or not raw_ck.is_dir():
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                "Cockpit root does not exist or is a symlink/junction.",
                cwe="CWE-22",
                details={"http_status": 403},
            )
        cockpit_resolved = raw_ck.resolve()

    eff_allowed = cockpit_resolved if cockpit_resolved is not None else repo_resolved
    resolved_paper: Optional[Path] = None
    if paper_path is not None and str(paper_path).strip():
        cand_pp = resolve_manuscript_path(repo_resolved, paper_path, allowed_root=eff_allowed)
        if cand_pp.exists():
            resolved_paper = cand_pp
    else:
        resolved_paper = _pick_main_tex_file(repo_resolved)
        if resolved_paper is None and cockpit_resolved is not None:
            resolved_paper = _pick_main_tex_file(cockpit_resolved)

    used_mod_ids: Set[str] = set()
    saved_id_set: Set[str] = {str(x).strip() for x in (saved_scope_module_ids or []) if str(x).strip()}
    explicit_sel_set: Optional[Set[str]] = (
        {str(x).strip() for x in selected_module_ids if str(x).strip()}
        if selected_module_ids is not None
        else None
    )
    lit_map = dict(literature_overlays or {})

    def _partition_single_repo(r_path: Path, *, is_primary: bool) -> Dict[str, Any]:
        prod_fps, test_fps = _scan_contained_source_files(r_path)
        files_sig = 0
        for _fp in prod_fps:
            try:
                _st = _fp.stat()
                files_sig ^= (hash(str(_fp.name)) ^ int(_st.st_mtime_ns) ^ (int(_st.st_size) << 7))
            except OSError:
                pass
        paper_sig = 0
        if is_primary and resolved_paper is not None and resolved_paper.is_file():
            try:
                _pst = resolved_paper.stat()
                paper_sig = int(_pst.st_mtime_ns) ^ (int(_pst.st_size) << 5)
            except OSError:
                paper_sig = -1
        cache_k = (
            os.path.normcase(str(r_path)),
            os.path.normcase(str(resolved_paper)) if (is_primary and resolved_paper is not None) else "",
            bool(is_primary),
            tuple(entrypoints or ()) if is_primary else (),
            len(prod_fps),
            files_sig,
            paper_sig,
        )
        cached_hit = _SINGLE_REPO_SLICE_CACHE.get(cache_k)
        if cached_hit is not None:
            _, _, scope_info, disc_eps, sym_slice = cached_hit
        else:
            scope_info = discover_paper_matched_scopes(
                r_path,
                resolved_paper if is_primary else None,
                allowed_root=eff_allowed if is_primary else None,
            )
            disc_eps = list(entrypoints or []) if is_primary else []
            if not disc_eps and is_primary:
                for ws in scope_info.get("workflow_steps") or []:
                    ep_s = str(ws.get("entrypoint") or "")
                    # Exclude pure raw-ETL prep scripts from default estimator/table slice entrypoints when table steps exist
                    if ep_s and ws.get("pipeline_id") != "data_preparation" and ep_s not in disc_eps:
                        disc_eps.append(ep_s)
                if not disc_eps:
                    for p_obj in scope_info.get("pipelines") or []:
                        for ep_s in p_obj.get("entrypoints") or []:
                            if ep_s not in disc_eps:
                                disc_eps.append(ep_s)

            sym_slice = slice_call_graph(r_path, entrypoints=disc_eps or None)
            if len(_SINGLE_REPO_SLICE_CACHE) >= 32:
                _SINGLE_REPO_SLICE_CACHE.clear()
            _SINGLE_REPO_SLICE_CACHE[cache_k] = (prod_fps, test_fps, scope_info, disc_eps, sym_slice)

        syms_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for grp_k in ("reached_symbols", "uncertain_symbols", "unreached_symbols"):
            for sm in sym_slice.get(grp_k) or []:
                if sm.get("file"):
                    syms_by_file.setdefault(str(sm["file"]), []).append(sm)

        ep_targets_by_file: Dict[str, List[str]] = {}
        ep_sections_by_file: Dict[str, List[str]] = {}
        ep_files_set: Set[str] = set(disc_eps)
        for ws in scope_info.get("workflow_steps") or []:
            ep_f = str(ws.get("entrypoint") or "")
            if ep_f:
                ep_files_set.add(ep_f)
                ep_targets_by_file.setdefault(ep_f, []).extend(ws.get("manuscript_targets") or [])
                ep_sections_by_file.setdefault(ep_f, []).extend(ws.get("sections") or [])
        for p_obj in scope_info.get("pipelines") or []:
            for ep_f in p_obj.get("entrypoints") or []:
                ep_files_set.add(ep_f)
                ep_targets_by_file.setdefault(ep_f, []).extend(p_obj.get("manuscript_targets") or [])
                ep_sections_by_file.setdefault(ep_f, []).extend(p_obj.get("sections") or [])

        import anvil_fact_ledger as _afl
        import anvil_latex_mathml as _alm
        paper_ms_bundle: Optional[Dict[str, Any]] = None
        if is_primary and resolved_paper is not None and resolved_paper.is_file():
            try:
                paper_ms_bundle = _alm.resolve_manuscript_bundle(resolved_paper, allowed_root=eff_allowed)
            except _alm.AnvilLatexSecurityError as sec_exc:
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    str(sec_exc),
                    cwe="CWE-22",
                    details={"candidate": sec_exc.candidate, "http_status": 403},
                ) from sec_exc

        # Classify each production file into semantic architectural buckets via Hub + Provenance Atom Graph
        buckets: Dict[str, Dict[str, Any]] = {}
        ledger_cluster: Optional[Dict[str, Any]] = None
        if is_primary:
            ledger_cluster = _afl.cluster_repository_modules(
                r_path,
                prod_fps,
                test_fps,
                entrypoints=disc_eps,
                workflow_targets_by_file=ep_targets_by_file,
                paper_artifacts=(paper_ms_bundle or {}).get("referenced_artifacts"),
            )
            buckets = ledger_cluster["buckets"]
            # Upgrade active estimator reachability using symbol_slice if a library had unreached symbols only
            for binfo in list(buckets.values()):
                if binfo["role"] == "core_estimator":
                    active_cnt = sum(
                        1
                        for mf in binfo["files"]
                        for s in syms_by_file.get(mf, [])
                        if s["badge"] in ("reached", "uncertain")
                    )
                    if active_cnt == 0 and disc_eps and binfo["slug"] != "core_estimator":
                        binfo["default_status"] = "available"
        else:
            for fp in prod_fps:
                rel = fp.relative_to(r_path).as_posix()
                pkg_slug = Path(rel).parts[0] if len(Path(rel).parts) > 1 else r_path.name
                b = buckets.setdefault(
                    f"{r_path.name}_{pkg_slug}",
                    {
                        "slug": f"{r_path.name}_{pkg_slug}",
                        "title": f"{r_path.name} · {pkg_slug.replace('_', ' ').title()}",
                        "role": "sibling_repo",
                        "default_status": "available",
                        "files": [],
                    },
                )
                if rel not in b["files"]:
                    b["files"].append(rel)
            for tfp in test_fps:
                t_rel = tfp.relative_to(r_path).as_posix()
                b = buckets.setdefault(
                    f"{r_path.name}_tests",
                    {
                        "slug": f"{r_path.name}_tests",
                        "title": f"{r_path.name} · Unit Tests",
                        "role": "sibling_repo",
                        "default_status": "available",
                        "files": [],
                    },
                )
                if t_rel not in b["files"]:
                    b["files"].append(t_rel)

        role_order = {
            "core_estimator": 0,
            "table_replicators": 1,
            "simulation": 2,
            "sibling_repo": 3,
            "data_etl": 4,
            "unscoped_plumbing": 5,
            "tests_historical": 6,
        }
        modules_out: List[Dict[str, Any]] = []
        for bkey, binfo in sorted(buckets.items(), key=lambda kv: (role_order.get(kv[1]["role"], 9), kv[0])):
            m_files = sorted(binfo["files"])
            mid = _make_opaque_module_id(binfo["slug"], used_mod_ids)

            tot_s = r_s = u_s = x_s = 0
            mod_targets: List[str] = []
            mod_sections: List[str] = []
            for mf in m_files:
                for sm in syms_by_file.get(mf, []):
                    tot_s += 1
                    if sm["badge"] == "reached":
                        r_s += 1
                    elif sm["badge"] == "uncertain":
                        u_s += 1
                    else:
                        x_s += 1
                for tg in ep_targets_by_file.get(mf, []):
                    if tg not in mod_targets:
                        mod_targets.append(tg)
                for sc in ep_sections_by_file.get(mf, []):
                    if sc not in mod_sections:
                        mod_sections.append(sc)

            if is_primary and resolved_paper is not None and binfo["role"] == "core_estimator" and not mod_sections:
                # Link core estimator to leading methodological sections in manuscript
                all_secs = list(dict.fromkeys(
                    str(a.get("section") or "") for a in (scope_info.get("manuscript_artifacts") or []) if a.get("section")
                ))
                mod_sections = all_secs[:2] if all_secs else ["Main"]

            if explicit_sel_set is not None:
                if mid in explicit_sel_set:
                    eff_status = "in_scope"
                elif mid in saved_id_set:
                    eff_status = "saved_scope"
                elif binfo["default_status"] == "unscoped_plumbing":
                    eff_status = "unscoped_plumbing"
                else:
                    eff_status = "available"
            else:
                if mid in saved_id_set and binfo["default_status"] != "in_scope":
                    eff_status = "saved_scope"
                else:
                    eff_status = binfo["default_status"]

            has_paper_link = bool(is_primary and resolved_paper is not None and (mod_targets or (binfo["role"] == "core_estimator" and r_s + u_s > 0)))
            if has_paper_link:
                paper_name = resolved_paper.name if resolved_paper is not None else "Manuscript"
                parts_desc: List[str] = []
                if mod_sections:
                    parts_desc.append(", ".join(mod_sections[:2]))
                if mod_targets:
                    parts_desc.append(", ".join(mod_targets[:4]))
                local_summary = f"{paper_name} · {' — '.join(parts_desc)}" if parts_desc else f"{paper_name} · Core Model"
            else:
                local_summary = "No local paper link (auxiliary, plumbing, or separate codebase)"

            if mid in lit_map and isinstance(lit_map[mid], dict):
                lit_slot = {
                    "status": "claimed",
                    "posture": "CLAIMED",
                    "verified": False,
                    "summary": str(lit_map[mid].get("summary") or ""),
                    "citations": list(lit_map[mid].get("citations") or []),
                }
            else:
                lit_slot = {
                    "status": "not_requested",
                    "posture": "not_requested",
                    "verified": False,
                    "summary": "",
                    "citations": [],
                }

            short_names = [Path(f).name for f in m_files[:3]]
            if len(m_files) > 3:
                short_names.append(f"+{len(m_files) - 3}")

            modules_out.append({
                "id": mid,
                "module_id": mid,
                "title": binfo["title"],
                "role": binfo["role"],
                "files": m_files,
                "atom_ids": [_afl.compute_atom_id(mf) for mf in m_files],
                "file_count": len(m_files),
                "files_short": ", ".join(short_names),
                "symbol_counts": {
                    "total": tot_s,
                    "reached": r_s,
                    "uncertain": u_s,
                    "unreached": x_s,
                },
                "scope_status": eff_status,
                "local_paper_links": {
                    "has_paper_link": has_paper_link,
                    "paper_file": resolved_paper.name if (has_paper_link and resolved_paper is not None) else "",
                    "sections": mod_sections,
                    "targets": mod_targets,
                    "tables": [t for t in mod_targets if str(t).lower().startswith(("tab", "tbl")) or "table" in str(t).lower()],
                    "figures": [t for t in mod_targets if str(t).lower().startswith("fig") or "fig" in str(t).lower()],
                    "summary": local_summary,
                },
                "external_literature": lit_slot,
            })

        return {
            "repo_name": r_path.name,
            "is_primary": is_primary,
            "total_files": len(prod_fps) + len(test_fps),
            "modules": modules_out,
            "symbol_slice": sym_slice if is_primary else None,
            "scope_info": scope_info if is_primary else None,
            "paper_bundle": paper_ms_bundle if is_primary else None,
            "ledger_anomalies": (ledger_cluster or {}).get("anomalies") if is_primary else None,
        }

    repos_out: List[Dict[str, Any]] = [_partition_single_repo(repo_resolved, is_primary=True)]
    if sibling_repos:
        for sib in sibling_repos:
            sib_p = Path(sib)
            if _is_link_or_junction(sib_p):
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Symlink sibling repo refused.", cwe="CWE-22", details={"http_status": 403})
            if sib_p.is_dir():
                sib_res = sib_p.resolve()
                if cockpit_resolved is not None and not sib_res.is_relative_to(cockpit_resolved):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Sibling repo escapes cockpit_root.", cwe="CWE-22", details={"http_status": 403})
                if os.path.normcase(str(sib_res)) != os.path.normcase(str(repo_resolved)):
                    repos_out.append(_partition_single_repo(sib_res, is_primary=False))

    primary_mods = repos_out[0]["modules"]
    primary_scope_info = repos_out[0].get("scope_info") or {}
    in_scope_mids = sorted(m["module_id"] for m in primary_mods if m["scope_status"] == "in_scope")
    in_scope_files = sorted({f for m in primary_mods if m["scope_status"] == "in_scope" for f in m["files"]})
    in_scope_set = set(in_scope_files)
    in_scope_eps: List[str] = []
    if entrypoints:
        for raw_ep in entrypoints:
            ep_str = str(raw_ep or "").strip()
            ep_f = ep_str.split(":", 1)[0].replace("\\", "/").strip("/")
            if ep_f in in_scope_set and ep_str not in in_scope_eps:
                in_scope_eps.append(ep_str)
    else:
        for ws in primary_scope_info.get("workflow_steps") or []:
            ep_f = str(ws.get("entrypoint") or "")
            if ep_f and ep_f in in_scope_set and ws.get("pipeline_id") != "data_preparation" and ep_f not in in_scope_eps:
                in_scope_eps.append(ep_f)

    manifest_json, scope_sha256 = compute_scope_manifest(
        repo_resolved,
        scope_files=in_scope_files,
        selected_module_ids=in_scope_mids,
        entrypoints=in_scope_eps or None,
        paper_paths=[resolved_paper] if resolved_paper is not None else None,
        cockpit_root=cockpit_resolved,
    )

    primary_paper_bundle = repos_out[0].get("paper_bundle") or {}
    primary_anomalies = repos_out[0].get("ledger_anomalies") or {}
    all_modules_flat = [m for r in repos_out for m in r["modules"]]
    for r_item in repos_out:
        r_item.pop("symbol_slice", None)
        r_item.pop("scope_info", None)
        r_item.pop("paper_bundle", None)
        r_item.pop("ledger_anomalies", None)

    bib_map = primary_paper_bundle.get("bibliography") or {}
    return {
        "ok": True,
        "schema": SOFTWARE_PAPER_MAP_SCHEMA,
        "repos": repos_out,
        "modules": all_modules_flat,
        "selected_module_ids": in_scope_mids,
        "in_scope_files": in_scope_files,
        "entrypoints": in_scope_eps,
        "scope_sha256": scope_sha256,
        "scope_manifest_json": manifest_json,
        "has_paper": resolved_paper is not None,
        "paper_file": resolved_paper.name if resolved_paper is not None else "",
        "manuscript_citations": {
            "count": len(bib_map),
            "entries": list(bib_map.values())[:80],
            "catalog_seeds": list(primary_paper_bundle.get("catalog_seeds") or []),
            "occurrences": list(primary_paper_bundle.get("citations") or [])[:120],
        },
        "fact_ledger_anomalies": primary_anomalies,
    }


def build_process_map(
    repo_dir: str | Path,
    trace_data: Optional[Dict[str, Any]] = None,
    persist: bool = True,
    *,
    paper_path: Optional[str | Path] = None,
    pipeline_id: Optional[str] = None,
    allowed_root: Optional[str | Path] = None,
    scoped: Optional[bool] = None,
    scope_files: Optional[Sequence[str]] = None,
    entrypoints: Optional[Sequence[str]] = None,
    slice_symbols: bool = False,
) -> Dict[str, Any]:
    """Build deterministic steady-coordinate L0->L1->L2->L3 Dual-Channel Process Map.
    Executes ZERO target code. When `trace_data` is supplied, upgrades witnessed edges to solid.
    Supports optional paper-matched replication scoping (`paper_path`, `pipeline_id`, `allowed_root`, `scoped`).
    """
    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir() or _is_link_or_junction(Path(repo_dir)):
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist or is a link.", cwe="CWE-22")

    if trace_data is not None:
        if not isinstance(trace_data, dict) or trace_data.get("schema") != TRACE_SCHEMA:
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                "Invalid trace_data object supplied to build_process_map (expected 'anvil-v4-trace/v1').",
                cwe="CWE-502",
            )

    prod_files, test_files = _scan_contained_source_files(root)
    all_source_files = prod_files if prod_files else test_files

    resolved_paper_opt: Optional[Path] = None
    if paper_path is not None and str(paper_path).strip():
        cand_pp = resolve_manuscript_path(root, paper_path, allowed_root=allowed_root)
        if cand_pp.exists():
            resolved_paper_opt = cand_pp

    scope_info = discover_paper_matched_scopes(
        root,
        paper_path if (paper_path is not None and str(paper_path).strip()) else None,
        allowed_root=allowed_root,
    )
    eff_pipeline_id = pipeline_id
    if scoped is True and not eff_pipeline_id and scope_info.get("paper_matched_files"):
        eff_pipeline_id = "all_paper_matched"
    elif scoped is False and not eff_pipeline_id:
        eff_pipeline_id = "none"
    scope_summary = resolve_active_pipeline_scope(scope_info, pipeline_id=eff_pipeline_id)
    if scoped is True and not scope_summary["scoped"] and (scope_info.get("pipelines") or scope_info.get("workflow_steps")):
        scope_summary["scoped"] = True
        if not scope_summary["active_files"]:
            scope_summary["active_files"] = [fp.relative_to(root).as_posix() for fp in all_source_files]
        if scope_summary["active_pipeline"] == "unscoped":
            scope_summary["active_pipeline"] = "all_paper_matched"
    excl_sym_set: Set[str] = set()
    if scope_files is not None:
        explicit_scope_set = {
            str(f).replace("\\", "/").strip("/")
            for f in scope_files
            if isinstance(f, (str, Path)) and str(f).strip()
        }
        scope_summary["scoped"] = True
        scope_summary["active_files"] = sorted(explicit_scope_set)
        all_source_files = [fp for fp in all_source_files if fp.relative_to(root).as_posix() in explicit_scope_set]
    elif scope_summary["scoped"]:
        allowed_set = set(scope_summary["active_files"])
        all_source_files = [fp for fp in all_source_files if fp.relative_to(root).as_posix() in allowed_set]
        excl_sym_set = {
            str(s.get("symbol") if isinstance(s, dict) else s)
            for s in (scope_summary.get("excluded_shared_symbols") or [])
        }

    repo_nn_classes = _collect_repo_nn_module_classes(all_source_files, root)
    hasher = hashlib.sha256()
    file_metas: List[Dict[str, Any]] = []
    all_units: List[Dict[str, Any]] = []
    main_files: List[str] = []

    for fp in all_source_files:
        rel_posix = fp.relative_to(root).as_posix()
        raw_bytes = fp.read_bytes()
        f_sha = hashlib.sha256(raw_bytes).hexdigest()[:16]
        hasher.update(f"{rel_posix}:{f_sha}\n".encode("utf-8"))
        src_lines = raw_bytes.decode("utf-8-sig", errors="replace").splitlines()
        line_cnt = len(src_lines)
        numbered_src = "\n".join(f"{lno:4d} | {ln}" for lno, ln in enumerate(src_lines[:500], start=1))
        file_metas.append({
            "file": rel_posix,
            "language": "python" if fp.suffix == ".py" else fp.suffix.lstrip("."),
            "total_lines": line_cnt,
            "sha256": f_sha,
            "numbered_source": numbered_src,
        })
        if fp.suffix == ".py":
            units, has_main = _extract_python_units(fp, rel_posix, repo_nn_classes=repo_nn_classes)
            if excl_sym_set:
                units = [
                    u for u in units
                    if f"{rel_posix}:{u['symbol']}" not in excl_sym_set
                    and f"{rel_posix}:{str(u['symbol']).split('.')[-1]}" not in excl_sym_set
                ]
            all_units.extend(units)
            if has_main or fp.stem.startswith(("run_", "main", "cli", "app")) or "pipeline" in fp.stem:
                main_files.append(rel_posix)
        elif fp.suffix in {".js", ".mjs", ".ts", ".r", ".R"}:
            units, has_main = _extract_polyglot_units(fp, rel_posix)
            all_units.extend(units)
            if has_main or fp.stem.startswith(("run", "main", "cli", "app", "index")) or "pipeline" in fp.stem:
                main_files.append(rel_posix)

    repo_fingerprint = hasher.hexdigest()[:24]

    computed_symbol_slice: Optional[Dict[str, Any]] = None
    computed_eq_bindings: Optional[Dict[str, Any]] = None
    slice_badges_map: Dict[str, str] = {}
    if scope_summary["scoped"] or entrypoints is not None or slice_symbols:
        eff_slice_eps: List[str] = list(entrypoints) if entrypoints is not None else []
        if not eff_slice_eps:
            for p_item in scope_summary.get("available_pipelines") or []:
                for ep_rel in p_item.get("entrypoints") or []:
                    if ep_rel not in eff_slice_eps:
                        eff_slice_eps.append(ep_rel)
        scoped_rel_filter = (
            [fp.relative_to(root).as_posix() for fp in all_source_files]
            if scope_summary["scoped"]
            else None
        )
        computed_symbol_slice = slice_call_graph(
            root,
            entrypoints=eff_slice_eps or None,
            scope_files=scoped_rel_filter,
        )
        slice_badges_map = dict(computed_symbol_slice.get("badges") or {})
        if slice_symbols:
            unreached_ids = set(computed_symbol_slice.get("unreached") or [])
            all_units = [
                u for u in all_units
                if str(u.get("id") or "") not in unreached_ids
            ]
        if resolved_paper_opt is not None:
            computed_eq_bindings = bind_manuscript_equations_to_symbols(
                root,
                resolved_paper_opt,
                symbol_slice=computed_symbol_slice,
                scope_files=scoped_rel_filter,
                allowed_root=allowed_root,
                scoped=True,
            )

    if not all_units:
        empty_res: Dict[str, Any] = {
            "ok": True,
            "schema": PROCESS_MAP_SCHEMA,
            "status_kind": "empty-but-valid",
            "message": "Repository parsed cleanly with 0 matched items",
            "isolation_boundary": "consented_local_subprocess" if trace_data else "static_ast_zero_execution",
            "code_executed_during_map": False,
            "repo_fingerprint": repo_fingerprint,
            "has_trace": bool(trace_data is not None),
            "paper_matched_scopes": scope_summary,
            "l0_scenarios": [],
            "l1_stages": [],
            "l2_steps": [],
            "l3_files": file_metas,
            "edges": [],
        }
        if persist:
            atomic_locked_write_json(root / ".anvil" / "v4" / "process_map.json", empty_res)
        return empty_res

    def _scenario_sort_key(item: Tuple[int, str]) -> Tuple[int, int]:
        orig_idx, rel_p = item
        stem_low = Path(rel_p).stem.lower()
        is_root = "/" not in rel_p
        score = 0
        if is_root and (stem_low.startswith(("run_scoped_test", "run_test", "smoke", "verify", "demo", "main", "pipeline", "app", "cli"))):
            score -= 15
        elif is_root:
            score -= 5
        try:
            src_txt = (root / rel_p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            src_txt = ""
        if "required=True" in src_txt or ("sys.argv[1]" in src_txt and "len(sys.argv)" not in src_txt):
            score += 50
        if any(tok in src_txt for tok in ("SentenceTransformer", "AutoModel", "KFold(", "StratifiedKFold(")):
            score += 25
        return (score, orig_idx)

    def _test_sort_key(item: Tuple[int, Path]) -> Tuple[int, int]:
        orig_idx, tf_p = item
        st_low = tf_p.stem.lower()
        if any(k in st_low for k in ("manuscript", "equation", "policy", "replication", "smoke", "e2e")):
            return (-10, orig_idx)
        return (0, orig_idx)

    ranked_tests = [tf_p for _i, tf_p in sorted(enumerate(test_files), key=_test_sort_key)]
    l0_scenarios: List[Dict[str, Any]] = []

    def _append_test_scenarios(limit: int = 2) -> None:
        for tf in ranked_tests[:limit]:
            if len(l0_scenarios) >= 5:
                break
            t_rel = tf.relative_to(root).as_posix()
            s_num = len(l0_scenarios) + 1
            l0_scenarios.append({
                "id": f"L0-{s_num}",
                "title": f"Test {tf.stem.replace('test_', '').replace('_', ' ').title()}"[:36],
                "entry_file": t_rel,
                "recommended_argv": ["pytest", "-q", t_rel],
                "takeaway": f"Regression verification suite in {t_rel}.",
                "x": 40 + (s_num - 1) * 252,
                "y": 24,
                "width": 232,
                "height": 54,
            })

    scoped_pipes = list(scope_summary.get("available_pipelines") or [])
    if scope_summary["scoped"] and scoped_pipes:
        act_p = str(scope_summary.get("active_pipeline") or "")
        l0_pipe_pool = (
            [p for p in scoped_pipes if p.get("id") == act_p]
            if act_p and act_p not in ("all_paper_matched", "unscoped", "all")
            else scoped_pipes
        )
        seen_l0_eps: Set[str] = set()
        for p in l0_pipe_pool:
            if len(l0_scenarios) >= 5:
                break
            eps_p = [e for e in (p.get("entrypoints") or p.get("files") or []) if e not in seen_l0_eps]
            if not eps_p:
                continue
            ep_rel = eps_p[0]
            seen_l0_eps.add(ep_rel)
            entry_ext = Path(ep_rel).suffix.lower()
            runner_bin = "node" if entry_ext in {".js", ".mjs", ".ts"} else ("Rscript" if entry_ext == ".r" else "python")
            s_num = len(l0_scenarios) + 1
            m_tgts = list(p.get("manuscript_targets") or [])
            tgt_note = f" -> {', '.join(m_tgts[:2])}" if m_tgts else ""
            l0_scenarios.append({
                "id": f"L0-{s_num}",
                "pipeline_id": p["id"],
                "title": str(p["title"])[:48],
                "entry_file": ep_rel,
                "recommended_argv": [runner_bin, ep_rel],
                "manuscript_targets": m_tgts,
                "takeaway": f"Workflow pipeline '{p['title']}' via {ep_rel}{tgt_note}.",
                "x": 40 + (s_num - 1) * 252,
                "y": 24,
                "width": 232,
                "height": 54,
            })
        if len(l0_scenarios) < 5:
            _append_test_scenarios(1)
    else:
        raw_candidates = list(dict.fromkeys(main_files or [all_units[0]["file"]]))
        ranked_pairs = sorted(enumerate(raw_candidates), key=_scenario_sort_key)
        scenario_files = [rel_p for _i, rel_p in ranked_pairs]
        best_main_score = _scenario_sort_key((0, scenario_files[0]))[0] if scenario_files else 99
        promote_tests_first = bool(ranked_tests and best_main_score >= 25)

        if promote_tests_first:
            _append_test_scenarios(2)

        for entry_rel in scenario_files[:3]:
            if len(l0_scenarios) >= 5:
                break
            entry_ext = Path(entry_rel).suffix.lower()
            runner_bin = "node" if entry_ext in {".js", ".mjs", ".ts"} else ("Rscript" if entry_ext == ".r" else "python")
            s_num = len(l0_scenarios) + 1
            l0_scenarios.append({
                "id": f"L0-{s_num}",
                "title": f"Run {Path(entry_rel).stem.replace('_', ' ').title()}"[:36],
                "entry_file": entry_rel,
                "recommended_argv": [runner_bin, entry_rel],
                "takeaway": f"Primary execution path entering via {entry_rel}.",
                "x": 40 + (s_num - 1) * 252,
                "y": 24,
                "width": 232,
                "height": 54,
            })
        if not promote_tests_first:
            _append_test_scenarios(2)

    stage_meta_list: List[Tuple[str, List[Dict[str, Any]], str, str, List[str]]] = []
    use_pipeline_stages = (
        (scope_summary["scoped"] or (scoped is not False and len(all_units) > 50 and scope_info.get("has_scope_anchor")))
        and bool(scope_summary.get("available_pipelines") or scope_summary.get("workflow_steps"))
    )
    if use_pipeline_stages:
        stage_meta_list = _partition_scoped_pipeline_stages(
            all_units,
            scope_summary,
            root=root,
            paper_path=resolved_paper_opt,
        )
    if not stage_meta_list:
        raw_grouped = _partition_into_macro_stages(
            all_units,
            root=root,
            paper_path=resolved_paper_opt,
        )
        stage_meta_list = [(k, m, "", "", []) for k, m in raw_grouped]

    sym_to_stage: Dict[str, Set[str]] = {}
    short_to_stage_set: Dict[str, Set[str]] = {}
    unit_to_stage: Dict[str, str] = {}
    for s_idx, (_knd, members, _ctitle, _cpid, _ctgts) in enumerate(stage_meta_list, start=1):
        sid = f"S{s_idx}"
        for u in members:
            unit_to_stage[u["id"]] = sid
            unit_to_stage.setdefault(str(u["id"]).split("#", 1)[0], sid)
            sym_to_stage.setdefault(str(u["symbol"]), set()).add(sid)
            if str(u["short_name"]) not in _AMBIGUOUS_BARE_HELPER_NAMES:
                short_to_stage_set.setdefault(str(u["short_name"]), set()).add(sid)
    short_to_stage: Dict[str, str] = {
        k: next(iter(v))
        for k, v in (list(sym_to_stage.items()) + list(short_to_stage_set.items()))
        if len(v) == 1
    }

    traced_line_hits: Dict[Tuple[str, int], int] = {}
    if trace_data:
        for item in trace_data.get("executed_lines") or []:
            if isinstance(item, dict) and isinstance(item.get("file"), str) and isinstance(item.get("line"), int):
                traced_line_hits[(item["file"], item["line"])] = int(item.get("hits", 1))
    traced_call_edges: Dict[Tuple[str, str], int] = {}
    if trace_data:
        for ce in trace_data.get("call_edges") or []:
            if isinstance(ce, dict):
                key = (str(ce.get("caller_symbol", "")), str(ce.get("callee_symbol", "")))
                traced_call_edges[key] = traced_call_edges.get(key, 0) + int(ce.get("count", 1))

    tripwires_all: List[Dict[str, Any]] = list(trace_data.get("tripwires") or []) if trace_data else []
    stage_timings: Dict[str, float] = dict(trace_data.get("stage_wall_sec") or {}) if trace_data else {}
    total_wall = max(1e-9, sum(float(v) for v in stage_timings.values())) if stage_timings else 0.0
    trace_verdicts: Dict[str, str] = dict(trace_data.get("stage_verdicts") or {}) if trace_data else {}
    drift_records: List[Dict[str, Any]] = list(trace_data.get("map_drift_edges") or []) if trace_data else []

    l1_stages: List[Dict[str, Any]] = []
    flat_l2_steps: List[Dict[str, Any]] = []
    file_stage_map: Dict[str, List[str]] = {}

    for s_idx, (kind, members, custom_title, stage_pid, stage_tgts) in enumerate(stage_meta_list, start=1):
        sid = f"S{s_idx}"
        stage_x = 56
        stage_y = 116 + (s_idx - 1) * 172
        stage_w = 368
        stage_h = 132

        stage_hits = 0
        stage_steps: List[Dict[str, Any]] = []
        stage_blind_spots: List[Dict[str, Any]] = []
        stage_inputs: List[str] = []
        stage_actions: List[str] = []
        stage_outputs: List[str] = []
        stage_files: List[str] = []

        for sub_idx, u in enumerate(members, start=1):
            step_id = f"{s_idx}.{sub_idx}"
            f_rel = u["file"]
            if f_rel not in stage_files:
                stage_files.append(f_rel)
            file_stage_map.setdefault(f_rel, [])
            if sid not in file_stage_map[f_rel]:
                file_stage_map[f_rel].append(sid)

            u_hits = sum(
                cnt for (f, ln), cnt in traced_line_hits.items()
                if f == f_rel and u["start_line"] <= ln <= u["end_line"]
            )
            stage_hits += u_hits
            loop_iters = max(
                (traced_line_hits.get((f_rel, lln), 0) for lln in u["loop_lines"]),
                default=0,
            )

            step_tw = [
                tw for tw in tripwires_all
                if tw.get("file") == f_rel and u["start_line"] <= int(tw.get("line", 0)) <= u["end_line"]
            ]
            fault_hotspot = step_tw[0] if step_tw else None

            resolved_bs: List[Dict[str, Any]] = []
            for bs_idx, bs in enumerate(u["dynamic_blind_spots"], start=1):
                matched_drift = [
                    d.get("callee_symbol", "")
                    for d in drift_records
                    if d.get("caller_file") == f_rel and u["start_line"] <= int(d.get("line", bs["line"])) <= u["end_line"]
                ]
                bs_entry = {
                    "id": f"BS-{sid}-{sub_idx}-{bs_idx}",
                    **bs,
                    "resolved_by_trace": len(matched_drift) > 0,
                    "traced_targets": list(dict.fromkeys(t for t in matched_drift if t)),
                }
                resolved_bs.append(bs_entry)
                stage_blind_spots.append(bs_entry)

            u_in = u["args"] or ["context"]
            u_act = u["docstring"] or f"Execute {u['symbol']}({', '.join(u_in[:3])})"
            u_out = u["outputs"]
            stage_inputs.extend(u_in)
            stage_actions.append(f"{u['symbol']}: {u_act}")
            stage_outputs.extend(u_out)

            ev = "traced" if u_hits > 0 else "static"
            step_obj = {
                "id": step_id,
                "stage_id": sid,
                "title": u["short_name"].replace("_", " ").title()[:32],
                "inputs": u_in,
                "what_enters": u_in,
                "action": u_act,
                "actions_run": [u_act],
                "outputs": u_out,
                "what_exits": u_out,
                "edge_evidence": ev,
                "edge_style": "solid" if ev == "traced" else "dashed",
                "hit_count": u_hits,
                "is_loop_back": bool(u["has_loop"]),
                "loop_iterations": loop_iters,
                "dynamic_blind_spots": resolved_bs,
                "fault_hotspot": fault_hotspot,
                "reachability_badge": slice_badges_map.get(u["id"], "reached"),
                "code_ref": {
                    "file": f_rel,
                    "symbol": u["symbol"],
                    "start_line": u["start_line"],
                    "end_line": u["end_line"],
                    "lines": [u["start_line"], u["end_line"]],
                },
                "x": 468,
                "y": stage_y + (sub_idx - 1) * 44,
                "width": 280,
                "height": 38,
            }
            stage_steps.append(step_obj)
            flat_l2_steps.append(step_obj)

        stage_tw = [tw for tw in tripwires_all if tw.get("stage_id") == sid] or [
            s["fault_hotspot"] for s in stage_steps if s["fault_hotspot"] is not None
        ]
        stage_drift = [
            d for d in drift_records
            if d.get("from_stage") == sid or d.get("to_stage") == sid
        ]
        w_sec = round(float(stage_timings.get(sid, 0.0)), 6)
        w_pct = round((100.0 * w_sec / total_wall), 2) if (trace_data and stage_timings) else 0.0

        if trace_data is None:
            verdict = "STATIC_ONLY"
        elif sid in trace_verdicts:
            verdict = trace_verdicts[sid]
        elif stage_tw:
            verdict = "CODE_VIOLATES_SPEC"
        elif stage_drift:
            verdict = "MAP_DRIFT"
        elif stage_hits == 0:
            verdict = "UNEXERCISED"
        else:
            verdict = "VERIFIED_TRACE"

        short_title = _stage_short_title(sid, kind, members, custom_title=custom_title)
        dedup_in = list(dict.fromkeys(stage_inputs))[:6]
        dedup_out = list(dict.fromkeys(stage_outputs))[:6]
        purpose = (
            members[0]["docstring"]
            if members[0]["docstring"]
            else f"{custom_title or kind.title()} stage executing {', '.join(m['short_name'] for m in members[:3])}."
        )
        min_ln = min((int(m.get("start_line", 1)) for m in members), default=1)
        max_ln = max((int(m.get("end_line", min_ln)) for m in members), default=min_ln)

        l1_stages.append({
            "id": sid,
            "stage_index": s_idx,
            "kind": kind,
            "pipeline_id": stage_pid,
            "manuscript_targets": stage_tgts,
            "title": short_title,
            "label": short_title,
            "member_files": stage_files,
            "purpose": purpose,
            "summary": purpose,
            "line_span": [min_ln, max_ln],
            "what_enters": dedup_in,
            "inputs": dedup_in,
            "actions_run": stage_actions[:5],
            "actions": stage_actions[:5],
            "what_exits": dedup_out,
            "outputs": dedup_out,
            "provenance": "traced" if stage_hits > 0 else "static_ast",
            "verdict": verdict,
            "wall_pct": w_pct,
            "wall_sec": w_sec,
            "hit_count": stage_hits,
            "traced_step_count": sum(1 for s in stage_steps if s["hit_count"] > 0),
            "total_step_count": len(stage_steps),
            "trace_coverage_pct": round(100.0 * sum(1 for s in stage_steps if s["hit_count"] > 0) / max(1, len(stage_steps)), 1),
            "has_loop": any(s["is_loop_back"] for s in stage_steps),
            "dynamic_blind_spots": stage_blind_spots,
            "tripwires": stage_tw,
            "files": stage_files,
            "member_symbols": [f"{m['file']}:{m['symbol']}" for m in members],
            "x": stage_x,
            "y": stage_y,
            "width": stage_w,
            "height": stage_h,
            "l2_steps": stage_steps,
            "sub_steps": stage_steps,
        })

    stage_by_id = {s["id"]: s for s in l1_stages}
    edges_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def _add_edge(src: str, dst: str, kind: str, via: str, evidence: str, count: int = 0) -> None:
        key = (src, dst, kind)
        s_box = stage_by_id[src]
        d_box = stage_by_id[dst]
        if key in edges_map:
            if evidence == "traced":
                edges_map[key]["evidence"] = "traced"
                edges_map[key]["style"] = "solid"
            edges_map[key]["call_count"] += count
            return
        pts = (
            [
                {"x": s_box["x"] + s_box["width"], "y": s_box["y"] + 40},
                {"x": s_box["x"] + s_box["width"] + 36, "y": s_box["y"] + 66},
                {"x": s_box["x"] + s_box["width"], "y": s_box["y"] + 92},
            ]
            if src == dst
            else [
                {"x": s_box["x"] + s_box["width"] // 2, "y": s_box["y"] + s_box["height"]},
                {"x": d_box["x"] + d_box["width"] // 2, "y": d_box["y"]},
            ]
        )
        edges_map[key] = {
            "id": f"E-{kind.upper()}-{src}-{dst}",
            "from": src,
            "to": dst,
            "kind": kind,
            "evidence": evidence,
            "style": "solid" if evidence == "traced" else "dashed",
            "call_count": count,
            "via": via,
            "points": pts,
        }

    for idx in range(len(l1_stages) - 1):
        s_cur = l1_stages[idx]
        s_nxt = l1_stages[idx + 1]
        both_hit = (s_cur["hit_count"] > 0 and s_nxt["hit_count"] > 0)
        _add_edge(s_cur["id"], s_nxt["id"], "forward", f"{s_cur['id']}->{s_nxt['id']}", "traced" if both_hit else "static", 1 if both_hit else 0)

    for u in all_units:
        src_sid = unit_to_stage.get(u["id"]) or (l1_stages[0]["id"] if l1_stages else "")
        if not src_sid:
            continue
        if u["has_loop"]:
            loop_iters = max((traced_line_hits.get((u["file"], ln), 0) for ln in u["loop_lines"]), default=0)
            _add_edge(src_sid, src_sid, "loop", f"{u['short_name']} loop", "traced" if loop_iters > 0 else "static", loop_iters)
        for callee in u["calls"]:
            dst_sid = short_to_stage.get(callee)
            if dst_sid and dst_sid != src_sid:
                c_cnt = traced_call_edges.get((u["short_name"], callee), 0)
                _add_edge(src_sid, dst_sid, "forward", f"{u['short_name']}->{callee}", "traced" if c_cnt > 0 else "static", c_cnt)

    for d in drift_records:
        f_sid = str(d.get("from_stage") or "")
        t_sid = str(d.get("to_stage") or f_sid)
        if f_sid in stage_by_id and t_sid in stage_by_id:
            _add_edge(
                f_sid,
                t_sid,
                "map_drift",
                f"{d.get('caller_symbol', '?')}->{d.get('callee_symbol', '?')}",
                "traced",
                int(d.get("count", 1)),
            )

    for fm in file_metas:
        fm["stage_ids"] = file_stage_map.get(fm["file"], [])

    result: Dict[str, Any] = {
        "ok": True,
        "schema": PROCESS_MAP_SCHEMA,
        "isolation_boundary": "consented_local_subprocess" if trace_data else "static_ast_zero_execution",
        "code_executed_during_map": False,
        "repo_fingerprint": repo_fingerprint,
        "has_trace": bool(trace_data is not None),
        "paper_matched_scopes": scope_summary,
        "l0_scenarios": l0_scenarios,
        "l1_stages": l1_stages,
        "l2_steps": flat_l2_steps,
        "l3_files": file_metas,
        "edges": list(edges_map.values()),
    }
    if computed_symbol_slice is not None:
        result["symbol_slice"] = computed_symbol_slice
        result["reached_symbols"] = computed_symbol_slice["reached_symbols"]
        result["uncertain_symbols"] = computed_symbol_slice["uncertain_symbols"]
        result["unreached_symbols"] = computed_symbol_slice["unreached_symbols"]
        result["shadowed_allocations"] = computed_symbol_slice["shadowed_allocations"]
    if computed_eq_bindings is not None:
        result["equation_bindings"] = computed_eq_bindings
        result["unbound_equations"] = computed_eq_bindings["unbound_equations"]
    if persist:
        atomic_locked_write_json(root / ".anvil" / "v4" / "process_map.json", result)
    return result


build_process_schematic = build_process_map


# ---------------------------------------------------------------------------
# 5. CLI Entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="Anvil v4 Pillar 1 — Paper-Matched Replication Scopes & Steady-Coordinate L0->L3 Process Map"
    )
    parser.add_argument(
        "cmd",
        nargs="?",
        default="process-map",
        choices=("process-map", "scopes"),
        help="Operation mode (default: process-map)",
    )
    parser.add_argument("--repo", required=True, help="Target repository directory")
    parser.add_argument("--paper", default="", help="Optional manuscript (.tex/.md/.pdf or directory)")
    parser.add_argument("--pipeline", default="", help="Optional paper-matched pipeline ID")
    parser.add_argument("--trace", default="", help="Optional validated runtime trace JSON")
    parser.add_argument("--no-persist", action="store_true", help="Do not write .anvil/v4/process_map.json")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    parser.add_argument("--output", default="", help="Optional atomic JSON output file path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.cmd == "scopes":
            res = discover_paper_matched_scopes(args.repo, args.paper or None)
        else:
            trace_obj = load_validated_trace_json(args.trace) if args.trace else None
            res = build_process_map(
                args.repo,
                trace_data=trace_obj,
                persist=not bool(args.no_persist),
                paper_path=args.paper or None,
                pipeline_id=args.pipeline or None,
            )
        if args.output:
            atomic_locked_write_json(args.output, res)
        if args.json or not args.output:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except AnvilRefusalError as err:
        print(json.dumps(err.to_dict(), indent=2, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

