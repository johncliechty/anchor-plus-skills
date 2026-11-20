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
    "prototype", "proto", "trial", "scratch", "abandoned", "archive", "tmp", "temp",
)

WORKFLOW_MANIFEST_NAMES: Tuple[str, ...] = (
    "workflow.sh", "run_all.sh", "replicate.sh", "replication.sh", "run.sh",
    "Makefile", "makefile", "GNUmakefile", "Snakefile", "REPLICATION.md", "replication.md",
)


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
    stem = Path(rel_posix).stem.lower()
    tokens = set(re.findall(r"[a-z0-9]+", "/".join(parts)))
    if tokens & set(HISTORICAL_CLUTTER_TOKENS):
        return True
    if re.search(r"(?:^|_)(?:v0|v1|try\d*|exp_old|archive|bak)(?:_|$)", stem):
        return True
    return False


def _strip_tex_comment_line(line: str) -> str:
    return re.sub(r"(?<!\\)%.*$", "", line)


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
    scored: List[Tuple[int, int, Path]] = []
    for tf in tex_files:
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
        return tex_files[0]
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
    try:
        raw = pdf_path.read_bytes()
        chunks = re.findall(rb"[\x20-\x7e]{6,}", raw)
        return "\n".join(c.decode("ascii", errors="ignore") for c in chunks[:500])
    except Exception:
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
    sec_re = re.compile(r"\\(section|subsection|appendix)\*?\s*(?:\{([^{}]*)\})?")

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
        for ln in lines:
            clean_ln = _strip_tex_comment_line(ln)
            for sm in sec_re.finditer(clean_ln):
                kind_kw = sm.group(1).lower()
                sec_title = (sm.group(2) or "").strip()
                if kind_kw == "appendix" and not sec_title:
                    active_sec = "Appendix"
                elif sec_title:
                    active_sec = f"Appendix: {sec_title}" if "appendix" in active_sec.lower() and kind_kw != "section" else sec_title

            for gm in gfx_re.finditer(clean_ln):
                fig_ref = gm.group(1).strip().replace("\\", "/")
                if fig_ref:
                    artifacts.append({
                        "kind": "figure",
                        "ref": fig_ref,
                        "stem": Path(fig_ref).stem.lower(),
                        "section": active_sec,
                    })

            for lm in lbl_re.finditer(clean_ln):
                lbl_val = lm.group(1).strip()
                artifacts.append({
                    "kind": "table_label" if lbl_val.lower().startswith(("tab", "tbl")) else "figure_label",
                    "ref": lbl_val,
                    "stem": re.sub(r"^(?:tab|tbl|fig|table|figure)[:_]", "", lbl_val.lower()),
                    "section": active_sec,
                })

            for im in inc_re.finditer(clean_ln):
                inc_ref = im.group(1).strip().replace("\\", "/")
                inc_low = inc_ref.lower()
                child_p = _resolve_tex_child(real_tf.parent, inc_ref)
                is_table_or_fig_path = any(
                    tok in inc_low
                    for tok in ("table", "tables/", "tab_", "tab/", "fig", "figures/", "output/", "results/")
                )
                child_has_tabular = False
                if child_p is not None and child_p.is_file():
                    try:
                        head_txt = child_p.read_text(encoding="utf-8", errors="replace")[:3000]
                        child_has_tabular = ("\\begin{tabular" in head_txt) or ("\\toprule" in head_txt)
                    except Exception:
                        child_has_tabular = False
                if is_table_or_fig_path or child_has_tabular:
                    artifacts.append({
                        "kind": "table",
                        "ref": inc_ref if inc_ref.endswith(".tex") else f"{inc_ref}.tex",
                        "stem": Path(inc_ref).stem.lower(),
                        "section": active_sec,
                    })
                if child_p is not None:
                    active_sec = _walk_tex(child_p, active_sec)
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
            prefix = (base / rel_sub).as_posix().lstrip("./") if rel_sub else base.as_posix().lstrip("./")
            if not prefix:
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
                                norm_s = s_lit.replace("\\", "/").lstrip("./")
                                cands_s = [norm_s, (Path(rel).parent / norm_s).as_posix().lstrip("./")]
                                for cr in sorted(top_code_roots):
                                    cands_s.append(f"{cr}/{norm_s}")
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
        elif ext == ".r":
            for m in re.finditer(r"""\bsource\(\s*['"]([^'"]+)['"]""", text):
                raw_r = m.group(1).strip().replace("\\", "/").lstrip("./")
                for cand in (raw_r, (Path(rel).parent / raw_r).as_posix().lstrip("./")):
                    if cand in known_rels and cand != rel:
                        targets.append(cand)
        elif ext in (".js", ".mjs", ".ts"):
            for m in re.finditer(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", text):
                spec = m.group(1).strip()
                if spec.startswith("."):
                    norm = os.path.normpath(str(Path(rel).parent / spec)).replace("\\", "/").lstrip("./")
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
        r"\b(?:pred|predict|predictive|oos|cv|kfold|fit|table1|table2|tab1|tab2|tables|benchmark|step2)\b"
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


def _parse_workflow_manifests(
    repo_root: Path,
    known_rels: Set[str],
    stem_to_rels: Dict[str, List[str]],
) -> Tuple[List[str], List[Dict[str, Any]], bool]:
    """Inspect executable manifests (`workflow.sh`, `Makefile`, `Snakefile`) first, falling back to
    `REPLICATION.md` / `README*.md` only when no executable manifest yields entrypoints.
    Supports shell variables (`C="$OUT/Code"`, `$PY`), step wrappers (`step <name> "$PY" ...`),
    and heredoc skipping.
    """
    exec_names = ("workflow.sh", "run_all.sh", "replicate.sh", "replication.sh", "run.sh", "Makefile", "makefile", "GNUmakefile", "Snakefile")
    doc_names = ("REPLICATION.md", "replication.md")

    exec_manifests: List[Path] = []
    doc_manifests: List[Path] = []
    seen_m: Set[Path] = set()

    for name in exec_names:
        for base in (repo_root, repo_root / "Code", repo_root / "scripts", repo_root / "replication"):
            p = base / name
            if p.is_file() and not _is_link_or_junction(p) and p.resolve() not in seen_m:
                seen_m.add(p.resolve())
                exec_manifests.append(p)

    for name in doc_names:
        for base in (repo_root, repo_root / "Code", repo_root / "scripts", repo_root / "replication"):
            p = base / name
            if p.is_file() and not _is_link_or_junction(p) and p.resolve() not in seen_m:
                seen_m.add(p.resolve())
                doc_manifests.append(p)

    for readme_p in sorted(repo_root.glob("README*.md")):
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
        clean = _expand_shell_vars(raw_tok, sh_vars).replace("\\", "/").lstrip("./")
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

                m_sh = sh_sub_re.search(full_cmd)
                if m_sh:
                    sh_rel = _expand_shell_vars(m_sh.group(1), sh_vars).replace("\\", "/").lstrip("./")
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


def discover_paper_matched_scopes(
    repo: Path | str,
    paper_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Discover exact replication code scopes matching a scientific paper's tables/figures
    and workflow manifests, compute transitive intra-repo import closures per pipeline, and
    quarantine unreachable historical trial scripts.
    """
    repo_p = Path(repo).resolve()
    if repo_p.is_file():
        return {
            "has_scope_anchor": False,
            "repo": str(repo_p),
            "paper_path": str(Path(paper_path).resolve()) if paper_path else "",
            "workflow_manifests": [],
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

    if paper_path is None and not _has_paper_or_workflow_anchor(repo_p):
        prod_files_fast, _ = _scan_contained_source_files(repo_p)
        return {
            "has_scope_anchor": False,
            "repo": str(repo_p),
            "paper_path": "",
            "workflow_manifests": [],
            "manuscript_artifacts": [],
            "pipelines": [],
            "available_pipelines": [],
            "available_pipeline_ids": [],
            "paper_matched_files": [],
            "unreferenced_historical_files": [],
            "quarantined_historical_files": [],
            "quarantined_historical_count": 0,
            "excluded_shared_symbols": [],
            "total_repo_source_files": len(prod_files_fast),
        }

    prod_files, _ = _scan_contained_source_files(repo_p)
    all_prod_rels = [fp.relative_to(repo_p).as_posix() for fp in prod_files]
    known_rels = set(all_prod_rels)
    stem_to_rels: Dict[str, List[str]] = {}
    for rel in all_prod_rels:
        stem_to_rels.setdefault(Path(rel).stem, []).append(rel)

    resolved_paper: Optional[Path] = None
    if paper_path is not None and str(paper_path).strip():
        cand_paper = Path(paper_path).resolve()
        if cand_paper.exists():
            resolved_paper = cand_paper
    else:
        resolved_paper = _pick_main_tex_file(repo_p)

    manuscript_artifacts = _scan_manuscript_artifacts(resolved_paper)
    adj, source_by_rel = _build_repo_import_graph(repo_p, prod_files)
    workflow_manifests, wf_invocations, has_exec_manifest = _parse_workflow_manifests(repo_p, known_rels, stem_to_rels)

    artifact_by_stem: Dict[str, Dict[str, Any]] = {}
    for art in manuscript_artifacts:
        if len(art["stem"]) >= 3:
            artifact_by_stem.setdefault(art["stem"], art)

    file_matched_artifacts: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in all_prod_rels}
    if manuscript_artifacts:
        for rel, src_txt in source_by_rel.items():
            src_low = src_txt.lower()
            for art in manuscript_artifacts:
                ref_low = art["ref"].lower()
                ref_base = Path(ref_low).name
                stem_low = art["stem"]
                matched = False
                if ref_low in src_low or (len(ref_base) >= 5 and ref_base in src_low):
                    matched = True
                elif len(stem_low) >= 5 and re.search(rf"""['"/\\_-]{re.escape(stem_low)}['"._]""", src_low):
                    matched = True
                if matched:
                    file_matched_artifacts[rel].append(art)

    ep_records: Dict[str, Dict[str, Any]] = {}
    for inv in wf_invocations:
        ep = inv["entrypoint"]
        rec = ep_records.setdefault(
            ep,
            {"entrypoint": ep, "manifests": [], "headers": [], "cmd_outputs": [], "artifacts": []},
        )
        if inv["manifest"] not in rec["manifests"]:
            rec["manifests"].append(inv["manifest"])
        if inv["header"] and inv["header"] not in rec["headers"]:
            rec["headers"].append(inv["header"])
        for out_p in inv["cmd_outputs"]:
            if out_p not in rec["cmd_outputs"]:
                rec["cmd_outputs"].append(out_p)
            out_stem = Path(out_p).stem.lower()
            if out_stem in artifact_by_stem:
                rec["artifacts"].append(artifact_by_stem[out_stem])

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
            ep_records[rel]["artifacts"].extend(file_matched_artifacts[rel])
        elif not has_exec_manifest and (rel not in imported_by_any or not ep_records):
            ep_records[rel] = {
                "entrypoint": rel,
                "manifests": [],
                "headers": [],
                "cmd_outputs": [],
                "artifacts": list(file_matched_artifacts[rel]),
            }

    grouped_pipelines: Dict[str, Dict[str, Any]] = {}
    for ep, rec in sorted(ep_records.items()):
        closure_files = _compute_import_closure([ep], adj)
        all_arts = list(rec["artifacts"])
        for cf in closure_files:
            all_arts.extend(file_matched_artifacts.get(cf, []))
        target_refs = list(dict.fromkeys(
            [a["ref"] for a in all_arts] + list(rec["cmd_outputs"])
        ))
        target_secs = list(dict.fromkeys(
            a["section"] for a in all_arts if a.get("section")
        ))
        header_str = " ".join(rec["headers"])
        pid, ptitle = _classify_pipeline_bucket(ep, header_str, target_refs, target_secs)

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
        sorted_eps = sorted(pobj["entrypoints"])
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
    has_scope_anchor = len(pipelines_out) > 0
    if has_scope_anchor:
        paper_matched_files = sorted(paper_matched_set)
        unreferenced_historical = sorted(known_rels - paper_matched_set)
        excluded_shared = _detect_excluded_shared_symbols(repo_p, source_by_rel, paper_matched_set)
    else:
        paper_matched_files = []
        unreferenced_historical = []
        excluded_shared = []

    return {
        "has_scope_anchor": has_scope_anchor,
        "repo": str(repo_p),
        "paper_path": str(resolved_paper) if resolved_paper else "",
        "workflow_manifests": workflow_manifests,
        "manuscript_artifacts": manuscript_artifacts,
        "pipelines": pipelines_out,
        "available_pipelines": pipelines_out,
        "available_pipeline_ids": [p["id"] for p in pipelines_out],
        "paper_matched_files": paper_matched_files,
        "unreferenced_historical_files": unreferenced_historical,
        "quarantined_historical_files": unreferenced_historical,
        "quarantined_historical_count": len(unreferenced_historical),
        "excluded_shared_symbols": excluded_shared,
        "total_repo_source_files": len(all_prod_rels),
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
        and bool(scope_info.get("workflow_manifests"))
        and total_files > auto_threshold
        and len(unreferenced) > 0
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


def get_l3_numbered_file(repo_dir: str | Path, rel_path: str) -> Dict[str, Any]:
    """Return Level-3 1-based line-numbered source for a contained repository file."""
    root = Path(repo_dir).resolve()
    fpath = resolve_contained_path(root, rel_path, allow_root=False)
    if not fpath.is_file():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Source file not found: '{rel_path}'.", cwe="CWE-22")
    text = fpath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    rel_posix = fpath.relative_to(root).as_posix()
    return {
        "ok": True,
        "file": rel_posix,
        "total_lines": len(lines),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "lines": [{"line": idx, "text": ln} for idx, ln in enumerate(lines, start=1)],
        "numbered_source": "\n".join(f"{idx:4d} | {ln}" for idx, ln in enumerate(lines, start=1)),
    }


def _classify_unit_kind(name: str, doc: str, has_loop: bool, calls: Sequence[str]) -> str:
    low = f"{name} {doc}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", low))
    call_low = {c.lower() for c in calls}
    if any(any(tok.startswith(h) for tok in tokens) for h in INGEST_HINTS):
        return "ingest"
    if any(any(tok.startswith(h) for tok in tokens) for h in EMIT_HINTS):
        return "emit"
    if has_loop or any(any(tok.startswith(h) for tok in tokens) for h in LOOP_HINTS):
        return "loop"
    if call_low & {"open", "loads", "read_text"} and not (call_low & {"write_text", "dumps"}):
        return "ingest"
    return "compute"


def _extract_python_units(fpath: Path, rel_posix: str) -> Tuple[List[Dict[str, Any]], bool]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tree = _parse_python_ast_quiet(text, filename=rel_posix)
    if tree is None:
        return [], False

    has_main_guard = False
    units: List[Dict[str, Any]] = []

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

        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                loop_lines.append(getattr(child, "lineno", node.lineno))
            elif isinstance(child, ast.Call):
                lno = getattr(child, "lineno", node.lineno)
                fn_expr = child.func
                if isinstance(fn_expr, ast.Name):
                    cid = fn_expr.id
                    calls.append(cid)
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
        kind = _classify_unit_kind(node.name, first_doc, has_loop, uniq_calls)
        start_ln = int(getattr(node, "lineno", 1))
        end_ln = int(getattr(node, "end_lineno", start_ln))
        return {
            "id": f"{rel_posix}:{qname}",
            "file": rel_posix,
            "symbol": qname,
            "short_name": node.name,
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
        kind = _classify_unit_kind(fn_name, "", has_loop, uniq_calls)
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


def _partition_into_macro_stages(units: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Deterministically group AST units into 3-5 macro execution stages (`S1..Sk`)."""
    if not units:
        return []

    rank_map = {"ingest": 0, "loop": 1, "compute": 2, "emit": 3}
    ordered = sorted(units, key=lambda u: (rank_map.get(u["kind"], 2), u["file"], u["start_line"]))

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

    by_kind: Dict[str, List[Dict[str, Any]]] = {"ingest": [], "loop": [], "compute": [], "emit": []}
    for u in ordered:
        by_kind.setdefault(u["kind"], []).append(u)

    groups: List[Tuple[str, List[Dict[str, Any]]]] = []
    if by_kind["ingest"]:
        groups.append(("ingest", by_kind["ingest"]))
    if by_kind["loop"]:
        groups.append(("loop", by_kind["loop"]))
    if by_kind["compute"]:
        comp = by_kind["compute"]
        with_bs = [u for u in comp if u["dynamic_blind_spots"]]
        without_bs = [u for u in comp if not u["dynamic_blind_spots"]]
        if with_bs and without_bs and len(groups) + (1 if by_kind["emit"] else 0) <= 3:
            groups.append(("compute", with_bs))
            groups.append(("compute", without_bs))
        elif len(comp) >= 2 and (len(groups) + (1 if by_kind["emit"] else 0) < 3):
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
        groups[-2] = (groups[-2][0], groups[-2][1] + groups[-1][1])
        groups.pop()

    return groups


def _stage_short_title(stage_id: str, kind: str, members: List[Dict[str, Any]]) -> str:
    lead = members[0]["short_name"].replace("_", " ").strip().title()
    words = [w for w in lead.split() if w][:3]
    lead_short = " ".join(words) if words else kind.title()
    prefix_map = {
        "ingest": "Ingest",
        "loop": "Iterative Loop",
        "compute": "Compute",
        "emit": "Emit",
    }
    tag = prefix_map.get(kind, "Stage")
    if tag.split()[0].lower() in lead_short.lower():
        return f"{stage_id} · {lead_short}"
    return f"{stage_id} · {tag}: {words[0] if words else 'Core'}"


def build_process_map(
    repo_dir: str | Path,
    trace_data: Optional[Dict[str, Any]] = None,
    persist: bool = True,
    *,
    paper_path: Optional[str | Path] = None,
    pipeline_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build deterministic steady-coordinate L0->L1->L2->L3 Dual-Channel Process Map.
    Executes ZERO target code. When `trace_data` is supplied, upgrades witnessed edges to solid.
    Supports optional paper-matched replication scoping (`paper_path`, `pipeline_id`).
    """
    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    if trace_data is not None:
        if not isinstance(trace_data, dict) or trace_data.get("schema") != TRACE_SCHEMA:
            raise AnvilRefusalError(
                "MALFORMED_DATA_REFUSED",
                "Invalid trace_data object supplied to build_process_map (expected 'anvil-v4-trace/v1').",
                cwe="CWE-502",
            )

    prod_files, test_files = _scan_contained_source_files(root)
    all_source_files = prod_files if prod_files else test_files

    scope_info = discover_paper_matched_scopes(root, Path(paper_path) if paper_path else None)
    scope_summary = resolve_active_pipeline_scope(scope_info, pipeline_id=pipeline_id)
    excl_sym_set: Set[str] = set()
    if scope_summary["scoped"]:
        allowed_set = set(scope_summary["active_files"])
        all_source_files = [fp for fp in all_source_files if fp.relative_to(root).as_posix() in allowed_set]
        excl_sym_set = {
            str(s.get("symbol") if isinstance(s, dict) else s)
            for s in (scope_summary.get("excluded_shared_symbols") or [])
        }

    hasher = hashlib.sha256()
    file_metas: List[Dict[str, Any]] = []
    all_units: List[Dict[str, Any]] = []
    main_files: List[str] = []

    for fp in all_source_files:
        rel_posix = fp.relative_to(root).as_posix()
        raw_bytes = fp.read_bytes()
        f_sha = hashlib.sha256(raw_bytes).hexdigest()[:16]
        hasher.update(f"{rel_posix}:{f_sha}\n".encode("utf-8"))
        src_lines = raw_bytes.decode("utf-8", errors="replace").splitlines()
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
            units, has_main = _extract_python_units(fp, rel_posix)
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
        if any(k in st_low for k in ("manuscript_equations", "step2_runner", "policy_budget", "replication")):
            return (-10, orig_idx)
        return (0, orig_idx)

    ranked_tests = [tf_p for _i, tf_p in sorted(enumerate(test_files), key=_test_sort_key)]
    l0_scenarios: List[Dict[str, Any]] = []
    raw_candidates = list(dict.fromkeys(main_files or [all_units[0]["file"]]))
    ranked_pairs = sorted(enumerate(raw_candidates), key=_scenario_sort_key)
    scenario_files = [rel_p for _i, rel_p in ranked_pairs]
    best_main_score = _scenario_sort_key((0, scenario_files[0]))[0] if scenario_files else 99
    promote_tests_first = bool(ranked_tests and best_main_score >= 25)

    def _append_test_scenarios(limit: int = 2) -> None:
        for tf in ranked_tests[:limit]:
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

    grouped = _partition_into_macro_stages(all_units)
    short_to_stage: Dict[str, str] = {}
    unit_to_stage: Dict[str, str] = {}
    for s_idx, (_knd, members) in enumerate(grouped, start=1):
        sid = f"S{s_idx}"
        for u in members:
            unit_to_stage[u["id"]] = sid
            unit_to_stage.setdefault(str(u["id"]).split("#", 1)[0], sid)
            short_to_stage.setdefault(u["short_name"], sid)

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

    for s_idx, (kind, members) in enumerate(grouped, start=1):
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

        short_title = _stage_short_title(sid, kind, members)
        dedup_in = list(dict.fromkeys(stage_inputs))[:6]
        dedup_out = list(dict.fromkeys(stage_outputs))[:6]
        purpose = (
            members[0]["docstring"]
            if members[0]["docstring"]
            else f"{kind.title()} stage executing {', '.join(m['short_name'] for m in members[:3])}."
        )

        l1_stages.append({
            "id": sid,
            "stage_index": s_idx,
            "kind": kind,
            "title": short_title,
            "label": short_title,
            "purpose": purpose,
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
    if persist:
        atomic_locked_write_json(root / ".anvil" / "v4" / "process_map.json", result)
    return result


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

