"""Per-Cockpit Anvil Session Controller for Anchor AI Cockpits.

Provides each AI Cockpit (`cdir`) with its own persistent Anvil session stored in
`<cdir>/.anvil/session.json`. Many cockpits start with an empty Anvil session (`active: False`),
showing a clean launch screen until either John or the Cockpit's Steward launches Anvil to:
  1. Analyze & improve software (reachable within the Cockpit folder or cloned from a GitHub repo).
  2. Map a scientific/technical paper (pulled from arXiv/internet URL or local file in the Cockpit)
     to its software implementation with native MathML equations and empirical verification.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import html
import importlib
import io
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ANCHOR_ROOT = Path(__file__).resolve().parent.parent
_FOUNDRY_CANDIDATES: Tuple[Path, ...] = (
    _ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil" / "scripts",
    _ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil" / "scripts",
)


def _load_anvil_engine(candidates: Optional[Tuple[Path, ...]] = None) -> Any:
    """Load `anvil_engine` from Skill Foundry or bundled Anchor vendor fallback without writing `.pyc` files."""
    search = tuple(candidates) if candidates is not None else _FOUNDRY_CANDIDATES
    for cand in search:
        cand_file = cand / "anvil_engine.py"
        if cand.is_dir() and cand_file.is_file():
            cand_str = str(cand.resolve())
            sys.path[:] = [cand_str] + [p for p in sys.path if p != cand_str]
            prev_bc = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                sys.modules.pop("anvil_engine", None)
                return importlib.import_module("anvil_engine")
            except Exception:
                continue
            finally:
                sys.dont_write_bytecode = prev_bc
    return None


anvil_engine = _load_anvil_engine()

ALLOWED_LOCAL_ROOTS = (
    _ANCHOR_ROOT.parent.resolve(),
)

FORBIDDEN_DOT_PARTS = {
    ".git", ".claude", ".aws", ".ssh", ".gnupg", ".anchor",
    ".ecgberht", ".steward", ".env", ".netrc", ".npmrc", ".pypirc",
}
FORBIDDEN_SECRET_NAMES = {
    "credentials", "credentials.json", ".credentials.json",
    "id_rsa", "id_ed25519", "secrets.json", "token.json",
}

GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$",
    re.IGNORECASE,
)
ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|^arxiv:)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

_COCKPIT_LOCKS_GUARD = threading.Lock()
_COCKPIT_LOCKS: Dict[str, threading.Lock] = {}
_CANDIDATES_CACHE: Dict[str, Tuple[float, Dict[str, List[Dict[str, str]]]]] = {}


def _get_cockpit_lock(cdir: Path) -> threading.Lock:
    key = str(cdir.resolve()).lower()
    with _COCKPIT_LOCKS_GUARD:
        lock = _COCKPIT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _COCKPIT_LOCKS[key] = lock
        return lock


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _session_dir(cdir: Path) -> Path:
    return cdir / ".anvil"


def _session_file(cdir: Path) -> Path:
    return _session_dir(cdir) / "session.json"


def _cockpit_display_name(cdir: Path) -> str:
    generic_headings = {
        "ecgberht — face", "ecgberht - face", "ecgberht",
        "aladdin — face", "aladdin - face", "aladdin",
        "jarvis — face", "jarvis - face", "jarvis",
        "steward — face", "steward - face", "steward",
    }
    ecg = cdir / "ECGBERHT.md"
    if ecg.is_file():
        try:
            for line in ecg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("# "):
                    heading = line.strip()[2:].strip()
                    if heading and heading.lower() not in generic_headings:
                        return heading
                    break
        except Exception:
            pass
    rm = cdir / "roadmap.json"
    if rm.is_file():
        try:
            data = json.loads(rm.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and data.get("project"):
                proj = str(data["project"]).strip()
                if proj and proj.lower() not in generic_headings:
                    return proj
        except Exception:
            pass
    return cdir.name.replace("-", " ").replace("_", " ").strip() or "AI Cockpit"


def discover_cockpit_candidates(cdir: Path) -> Dict[str, List[Dict[str, str]]]:
    """Scan the cockpit directory for local software folders/files and local papers/docs (bounded & cached)."""
    key = str(cdir.resolve()).lower()
    now = time.monotonic()
    cached = _CANDIDATES_CACHE.get(key)
    if cached and (now - cached[0]) < 10.0:
        return cached[1]

    software: List[Dict[str, str]] = []
    papers: List[Dict[str, str]] = []
    if not cdir.is_dir():
        return {"software": software, "papers": papers}

    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".anvil", ".ecgberht", ".steward", "dist", "build",
    }
    code_exts = {".py", ".js", ".mjs", ".ts", ".r", ".jl", ".cpp", ".c"}
    paper_exts = {".pdf", ".md", ".tex", ".txt"}
    ignore_md = {
        "ecgberht.md", "deliverables.md", "strip.md", "history.md",
        "anvil-report.md", "readme.md",
    }

    top_code_count = 0
    total_walked = 0
    try:
        entries = sorted(cdir.iterdir(), key=lambda p: p.name.lower())
    except Exception:
        entries = []

    for entry in entries:
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        if entry.is_file():
            ext = entry.suffix.lower()
            if ext in code_exts:
                top_code_count += 1
                software.append({
                    "path": entry.name,
                    "label": f"{entry.name} (file in cockpit)",
                    "kind": "file",
                })
            elif ext in paper_exts and entry.name.lower() not in ignore_md:
                papers.append({
                    "path": entry.name,
                    "label": entry.name,
                    "kind": ext.lstrip("."),
                })
        elif entry.is_dir() and entry.name not in skip_dirs:
            sub_code = 0
            for root, dirs, files in os.walk(entry, followlinks=False):
                dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
                for f in files:
                    total_walked += 1
                    if total_walked > 250:
                        break
                    if f.startswith(".") or f.lower() in FORBIDDEN_SECRET_NAMES:
                        continue
                    fext = Path(f).suffix.lower()
                    rel = (Path(root) / f).relative_to(cdir).as_posix()
                    if fext in code_exts:
                        sub_code += 1
                    elif fext in paper_exts and f.lower() not in ignore_md and len(papers) < 20:
                        papers.append({
                            "path": rel,
                            "label": rel,
                            "kind": fext.lstrip("."),
                        })
                if sub_code > 60 or total_walked > 250:
                    break
            if sub_code > 0:
                software.insert(0, {
                    "path": entry.name,
                    "label": f"{entry.name}/ ({sub_code} code files)",
                    "kind": "dir",
                })

    if top_code_count > 0 or not software:
        software.insert(0, {
            "path": ".",
            "label": f"This Cockpit Folder ({cdir.name})" + (f" · {top_code_count} top-level code files" if top_code_count else ""),
            "kind": "cockpit_root",
        })

    if "anchor" in cdir.name.lower() or "anchor" in cdir.parent.name.lower():
        sc_dir = (_ANCHOR_ROOT / "steward_cockpit").resolve()
        if _ANCHOR_ROOT.is_dir():
            software.insert(0, {
                "path": str(_ANCHOR_ROOT.resolve()),
                "label": f"Anchor Root ({_ANCHOR_ROOT.resolve()}) · Repository Root",
                "kind": "dir",
            })
        if sc_dir.is_dir():
            software.insert(1, {
                "path": str(sc_dir),
                "label": f"Anchor steward_cockpit/ ({sc_dir}) · Cockpit Subsystem",
                "kind": "dir",
            })

    result = {
        "software": software[:16],
        "papers": papers[:16],
    }
    _CANDIDATES_CACHE[key] = (now, result)
    return result


def _validate_and_resolve_local_path(cdir: Path, spec: str) -> Path:
    """Strictly validate a local path spec against UNC/SMB leaks, dot-directories, secret files, and traversal."""
    raw = (spec or "").strip()
    if not raw or raw == ".":
        return cdir.resolve()
    if raw.startswith(("\\\\", "//", "\\\\?\\")):
        raise ValueError("Network/UNC paths are not permitted.")
    if re.match(r"^[A-Za-z]:(?![\\/])", raw):
        raise ValueError("Drive-relative paths are not permitted.")

    raw_parts = [p for p in re.split(r"[\\/]+", raw) if p]
    for part in raw_parts:
        low = part.lower()
        if part == "..":
            raise ValueError("Parent directory traversal ('..') is not permitted.")
        if low in FORBIDDEN_DOT_PARTS or low in FORBIDDEN_SECRET_NAMES:
            raise ValueError(f"Access to hidden or credential path '{part}' is not permitted.")
        if part.startswith(".") and part != ".":
            raise ValueError(f"Access to dot-path '{part}' is not permitted.")

    candidate = Path(raw)
    cdir_resolved = cdir.resolve()
    if not candidate.is_absolute():
        resolved = (cdir_resolved / candidate).resolve()
    else:
        resolved = candidate.resolve()

    if candidate.is_symlink() or resolved.is_symlink():
        raise ValueError("Symbolic links are not permitted as targets.")

    allowed = [cdir_resolved] + list(ALLOWED_LOCAL_ROOTS)
    within = any(resolved == root or root in resolved.parents for root in allowed)
    if not within:
        raise ValueError(f"Path '{spec}' is outside allowed workspace boundaries.")

    for part in resolved.parts:
        low = part.lower()
        if low in FORBIDDEN_DOT_PARTS or low in FORBIDDEN_SECRET_NAMES:
            raise ValueError(f"Access to restricted path component '{part}' is not permitted.")

    return resolved


def resolve_software_target(cdir: Path, target_spec: str, role: str = "primary") -> Dict[str, Any]:
    """Resolve either a local path (in cockpit or C:\\dev) or safely clone/update a GitHub repository."""
    spec = (target_spec or ".").strip()
    if not spec or spec == ".":
        return {
            "path": str(cdir.resolve()),
            "source_type": "cockpit_local",
            "label": f"{cdir.name} (cockpit root)",
            "spec": ".",
        }

    m = GITHUB_URL_RE.match(spec)
    if m:
        owner, repo = m.group(1), m.group(2)
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
        if owner.startswith("-") or repo.startswith("-") or ".." in owner or ".." in repo:
            raise ValueError("Invalid GitHub owner or repository name.")
        safe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{owner}__{repo}")
        repos_root = _session_dir(cdir) / "repos"
        repos_root.mkdir(parents=True, exist_ok=True)
        dest = (repos_root / safe_slug).resolve()
        https_url = f"https://github.com/{owner}/{repo}.git"
        git_env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
        if (dest / ".git").is_dir():
            proc = subprocess.run(
                [
                    "git", "-C", str(dest),
                    "-c", "core.symlinks=false",
                    "-c", "protocol.file.allow=never",
                    "pull", "--ff-only",
                ],
                capture_output=True,
                text=True,
                timeout=45,
                shell=False,
                env=git_env,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "git pull failed").strip()[:300]
                raise ValueError(f"Failed to update existing clone of https://github.com/{owner}/{repo}: {err}")
        else:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            tmp_dest = (repos_root / f".tmp_{safe_slug}_{os.getpid()}").resolve()
            if tmp_dest.exists():
                shutil.rmtree(tmp_dest, ignore_errors=True)
            try:
                proc = subprocess.run(
                    [
                        "git",
                        "-c", "core.symlinks=false",
                        "-c", "protocol.file.allow=never",
                        "clone", "--depth", "1", "--no-tags", "--",
                        https_url, str(tmp_dest),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    shell=False,
                    env=git_env,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "git clone failed").strip()[:300]
                    raise ValueError(f"Could not clone GitHub repository https://github.com/{owner}/{repo}: {err}")
                os.replace(str(tmp_dest), str(dest))
            finally:
                if tmp_dest.exists():
                    shutil.rmtree(tmp_dest, ignore_errors=True)

        return {
            "path": str(dest),
            "source_type": "github",
            "label": f"github.com/{owner}/{repo}",
            "url": f"https://github.com/{owner}/{repo}",
            "spec": spec,
        }

    candidate = _validate_and_resolve_local_path(cdir, spec)
    if not candidate.exists():
        raise ValueError(f"Software target '{spec}' does not exist at {candidate}.")

    try:
        rel_label = candidate.relative_to(cdir.resolve()).as_posix() or "."
    except ValueError:
        rel_label = str(candidate)

    return {
        "path": str(candidate),
        "source_type": "local",
        "label": rel_label,
        "spec": spec,
    }


def _validate_public_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// URLs are supported for internet paper fetching.")
    host = (parsed.hostname or "").strip().lower()
    if not host or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("Loopback/local URLs are not permitted for internet paper fetching.")
    try:
        infos = socket.getaddrinfo(host, None)
        if not infos:
            raise ValueError(f"Could not resolve host '{host}'.")
        for info in infos:
            ip_str = info[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                not ip_obj.is_global
                or ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                raise ValueError(f"Host '{host}' resolves to a non-public IP address ({ip_str}).")
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{host}': {exc}") from exc
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        full_new = urllib.parse.urljoin(req.full_url, newurl)
        _validate_public_url(full_new)
        hops = getattr(req, "_anvil_redirects", 0) + 1
        if hops > 3:
            raise ValueError("Too many HTTP redirects while fetching paper URL.")
        new_req = super().redirect_request(req, fp, code, msg, headers, full_new)
        if new_req is not None:
            setattr(new_req, "_anvil_redirects", hops)
        return new_req


def _safe_urlopen(url: str, max_bytes: int = 2_000_000, timeout: float = 12.0) -> Tuple[bytes, str]:
    _validate_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": "Anchor-Anvil/1.0"})
    t0 = time.monotonic()
    chunks: List[bytes] = []
    total = 0
    with opener.open(req, timeout=timeout) as resp:
        content_type = (resp.headers.get("Content-Type") or "").lower()
        while total < max_bytes:
            if (time.monotonic() - t0) > timeout:
                raise ValueError("Timed out reading remote paper content.")
            chunk = resp.read(min(65536, max_bytes - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks), content_type


def _extract_latex_title(tex_text: str) -> str:
    """Extract a clean human title from LaTeX `\\title{...}` if present."""
    no_comments = re.sub(r"(?<!\\)%[^\n]*", "", tex_text or "")
    m = re.search(r"\\title(?:\[[^\]]*\])?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", no_comments, flags=re.S)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.sub(r"\\[A-Za-z]+\s*", " ", raw)
    raw = re.sub(r"[{}]", " ", raw)
    return " ".join(raw.split()).strip()[:140]


def _pick_primary_tex_in_dir(bundle_dir: Path, candidates: Optional[List[Path]] = None) -> Optional[Path]:
    """Choose the root `.tex` file inside an extracted bundle or local paper directory."""
    tex_files = (
        [p for p in candidates if p.suffix.lower() == ".tex" and p.is_file()]
        if candidates is not None
        else [
            p
            for p in sorted(bundle_dir.rglob("*.tex"))
            if p.is_file() and not p.is_symlink()
        ]
    )
    if not tex_files:
        return None
    best_path = tex_files[0]
    best_score = -1
    for p in tex_files:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            txt = ""
        no_c = re.sub(r"(?<!\\)%[^\n]*", "", txt)
        score = 0
        if "\\documentclass" in no_c:
            score += 100
        if "\\begin{document}" in no_c:
            score += 50
        if p.stem.lower() in ("main", "paper", "ms", "article", "manuscript"):
            score += 25
        score += min(20, len(no_c) // 2000)
        if score > best_score:
            best_score = score
            best_path = p
    return best_path


def _safe_extract_arxiv_bundle(
    raw_bytes: bytes,
    dest_dir: Path,
    max_files: int = 120,
    max_total_bytes: int = 12_000_000,
) -> Optional[Path]:
    """Safely extract an arXiv `/e-print/<id>` tar/tar.gz or single-file .gz bundle into `dest_dir`.

    Enforces strict path-containment, blocks `..`, absolute/UNC/drive paths, symlinks, hardlinks,
    devices/FIFOs, secret/dot paths, and bounds file count and uncompressed bytes.
    """
    if not raw_bytes:
        return None
    if raw_bytes[:4] == b"%PDF":
        return None

    if dest_dir.is_symlink():
        raise ValueError("Extraction destination cannot be a symbolic link.")
    dest_resolved = dest_dir.resolve()
    if dest_resolved.exists():
        if dest_resolved.is_symlink():
            raise ValueError("Extraction destination cannot be a symbolic link.")
        shutil.rmtree(dest_resolved, ignore_errors=True)
    dest_resolved.mkdir(parents=True, exist_ok=True)

    extracted_files: List[Path] = []
    total_written = 0

    tf_obj: Optional[tarfile.TarFile] = None
    try:
        tf_obj = tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:*")
    except tarfile.TarError:
        tf_obj = None

    if tf_obj is not None:
        with tf_obj:
            member_count = 0
            while True:
                m = tf_obj.next()
                if m is None:
                    break
                member_count += 1
                if member_count > max_files:
                    raise ValueError(f"Archive exceeds maximum allowed file count ({max_files}).")
                raw_name = (m.name or "").strip()
                if m.issym() or m.islnk() or m.isdev() or m.isfifo():
                    raise ValueError(
                        f"Unsafe archive entry '{raw_name}': symbolic links, hard links, and special files are not permitted."
                    )
                if not raw_name:
                    continue
                if raw_name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw_name):
                    raise ValueError(f"Unsafe absolute or drive path in archive entry '{raw_name}'.")
                parts = [p for p in re.split(r"[\\/]+", raw_name) if p]
                clean_parts: List[str] = []
                for part in parts:
                    if part == ".":
                        continue
                    if part == "..":
                        raise ValueError(f"Parent directory traversal ('..') in archive entry '{raw_name}' is not permitted.")
                    low = part.lower()
                    if low in FORBIDDEN_DOT_PARTS or low in FORBIDDEN_SECRET_NAMES or part.startswith("."):
                        raise ValueError(f"Restricted path component '{part}' in archive entry '{raw_name}' is not permitted.")
                    clean_parts.append(part)
                if not clean_parts:
                    continue
                target_path = (dest_resolved / Path(*clean_parts)).resolve()
                if target_path != dest_resolved and dest_resolved not in target_path.parents:
                    raise ValueError(f"Archive entry '{raw_name}' escapes extraction root.")
                if m.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                if not m.isfile():
                    raise ValueError(f"Unsupported archive entry type for '{raw_name}'.")
                if m.size < 0 or (total_written + m.size) > max_total_bytes:
                    raise ValueError("Archive exceeds maximum uncompressed byte limit.")
                fobj = tf_obj.extractfile(m)
                if fobj is None:
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                chunks: List[bytes] = []
                with fobj:
                    while True:
                        chunk = fobj.read(65536)
                        if not chunk:
                            break
                        total_written += len(chunk)
                        if total_written > max_total_bytes:
                            raise ValueError("Archive exceeds maximum uncompressed byte limit.")
                        chunks.append(chunk)
                target_path.write_bytes(b"".join(chunks))
                extracted_files.append(target_path)
    elif raw_bytes[:2] == b"\x1f\x8b":
        chunks = []
        with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes), mode="rb") as gz:
            while True:
                chunk = gz.read(65536)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > max_total_bytes:
                    raise ValueError("Compressed e-print exceeds maximum uncompressed byte limit.")
                chunks.append(chunk)
        decomp = b"".join(chunks)
        if decomp[:4] == b"%PDF":
            return None
        decoded = decomp.decode("utf-8", errors="replace")
        if any(tok in decoded for tok in ("\\documentclass", "\\section", "\\begin{", "\\input{")):
            main_tex = dest_resolved / "main.tex"
            _atomic_write_text(main_tex, decoded)
            extracted_files.append(main_tex)
    else:
        decoded = raw_bytes.decode("utf-8", errors="replace")
        if any(tok in decoded for tok in ("\\documentclass", "\\section", "\\begin{document}")):
            main_tex = dest_resolved / "main.tex"
            _atomic_write_text(main_tex, decoded)
            extracted_files.append(main_tex)

    return _pick_primary_tex_in_dir(dest_resolved, extracted_files)


def resolve_paper_source(cdir: Path, paper_spec: str) -> Dict[str, Any]:
    """Resolve a paper from an arXiv ID/URL (`/e-print/<id>` TeX bundle first, Atom XML fallback), an HTTPS URL, or a local file/directory."""
    spec = (paper_spec or "").strip()
    if not spec:
        raise ValueError("Please provide a paper URL (e.g. arXiv link) or select a local paper file or TeX folder in this cockpit.")

    papers_dir = _session_dir(cdir) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    arxiv_match = ARXIV_ID_RE.search(spec)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", arxiv_id)
        eprint_url = f"https://arxiv.org/e-print/{urllib.parse.quote(arxiv_id)}"
        eprint_bytes: Optional[bytes] = None
        try:
            eprint_bytes, _ = _safe_urlopen(eprint_url, max_bytes=8_000_000, timeout=15.0)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            eprint_bytes = None

        if eprint_bytes:
            bundle_dir = papers_dir / f"arxiv_{safe_id}_src"
            primary_tex = _safe_extract_arxiv_bundle(eprint_bytes, bundle_dir)
            if primary_tex is not None and primary_tex.is_file():
                tex_text = primary_tex.read_text(encoding="utf-8", errors="replace")
                tex_title = _extract_latex_title(tex_text) or f"arXiv:{arxiv_id}"
                return {
                    "path": str(primary_tex),
                    "bundle_dir": str(bundle_dir),
                    "source_type": "arxiv_eprint",
                    "title": tex_title,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "text": tex_text,
                    "spec": spec,
                }

        api_url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
        xml_bytes, _ = _safe_urlopen(api_url, max_bytes=1_500_000, timeout=12.0)
        root = ET.fromstring(xml_bytes)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = root.find("a:entry", ns)
        title = f"arXiv:{arxiv_id}"
        summary = ""
        if entry is not None:
            t_el = entry.find("a:title", ns)
            s_el = entry.find("a:summary", ns)
            if t_el is not None and t_el.text:
                title = " ".join(t_el.text.split())
            if s_el is not None and s_el.text:
                summary = " ".join(s_el.text.split())
        dest = papers_dir / f"arxiv_{safe_id}.md"
        md_text = f"# {title}\n\nSource: https://arxiv.org/abs/{arxiv_id}\n\n## Abstract & Core Claims\n\n{summary}\n"
        _atomic_write_text(dest, md_text)
        return {
            "path": str(dest),
            "source_type": "arxiv",
            "title": title,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "text": md_text,
            "spec": spec,
        }

    if spec.lower().startswith(("http://", "https://")):
        raw_bytes, content_type = _safe_urlopen(spec, max_bytes=4_000_000, timeout=12.0)
        base_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(urllib.parse.urlparse(spec).path).stem or "paper")[:44]
        url_hash = hashlib.sha1(spec.encode("utf-8")).hexdigest()[:8]
        slug = f"{base_slug}_{url_hash}"
        if any(ext in spec.lower() for ext in (".tar.gz", ".tgz")) or "gzip" in content_type or "tar" in content_type:
            bundle_dir = papers_dir / f"{slug}_src"
            primary_tex = _safe_extract_arxiv_bundle(raw_bytes, bundle_dir)
            if primary_tex is not None and primary_tex.is_file():
                tex_text = primary_tex.read_text(encoding="utf-8", errors="replace")
                tex_title = _extract_latex_title(tex_text) or slug
                return {
                    "path": str(primary_tex),
                    "bundle_dir": str(bundle_dir),
                    "source_type": "url_bundle",
                    "title": tex_title[:110],
                    "url": spec,
                    "text": tex_text,
                    "spec": spec,
                }
        if "pdf" in content_type or spec.lower().endswith(".pdf"):
            dest = papers_dir / f"{slug}.pdf"
            dest.write_bytes(raw_bytes)
            text = _extract_text_from_file(dest)
        elif spec.lower().endswith(".tex"):
            text = raw_bytes.decode("utf-8", errors="replace")
            dest = papers_dir / f"{slug}.tex"
            _atomic_write_text(dest, text)
        else:
            raw_str = raw_bytes.decode("utf-8", errors="replace")
            if "<html" in raw_str.lower() or "<body" in raw_str.lower():
                title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_str, re.I | re.S)
                page_title = html.unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()) if title_m else spec
                stripped = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_str, flags=re.I | re.S)
                stripped = re.sub(r"<style\b[^>]*>.*?</style>", " ", stripped, flags=re.I | re.S)
                stripped = re.sub(r"<[^>]+>", "\n", stripped)
                lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
                text = f"# {page_title}\n\nSource: {spec}\n\n" + "\n".join(lines[:400])
            else:
                text = raw_str
            dest = papers_dir / f"{slug}.md"
            _atomic_write_text(dest, text)
        first_line = _extract_latex_title(text) or next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), slug)
        return {
            "path": str(dest),
            "source_type": "url",
            "title": first_line[:110],
            "url": spec,
            "text": text,
            "spec": spec,
        }

    candidate = _validate_and_resolve_local_path(cdir, spec)
    if candidate.is_dir():
        primary_tex = _pick_primary_tex_in_dir(candidate)
        if primary_tex is not None:
            tex_text = primary_tex.read_text(encoding="utf-8", errors="replace")
            title = _extract_latex_title(tex_text) or candidate.name
            return {
                "path": str(candidate),
                "primary_tex": str(primary_tex),
                "source_type": "local_dir",
                "title": title[:110],
                "url": "",
                "text": tex_text,
                "spec": spec,
            }
        md_files = [p for p in sorted(candidate.glob("*.md")) if p.is_file() and not p.is_symlink()]
        if md_files:
            md_text = md_files[0].read_text(encoding="utf-8", errors="replace")
            first_line = next((ln.lstrip("# ").strip() for ln in md_text.splitlines() if ln.strip()), candidate.name)
            return {
                "path": str(md_files[0]),
                "source_type": "local",
                "title": first_line[:110] or candidate.name,
                "url": "",
                "text": md_text,
                "spec": spec,
            }
        raise ValueError(f"Paper directory '{spec}' at {candidate} contains no .tex or .md manuscript files.")
    if not candidate.is_file():
        raise ValueError(f"Paper file '{spec}' was not found at {candidate}.")

    text = _extract_text_from_file(candidate)
    first_line = _extract_latex_title(text) or next((ln.lstrip("#% ").strip() for ln in text.splitlines() if ln.strip()), candidate.name)
    return {
        "path": str(candidate),
        "source_type": "local",
        "title": first_line[:110] or candidate.name,
        "url": "",
        "text": text,
        "spec": spec,
    }


def _extract_text_from_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            pypdf = importlib.import_module("pypdf")  # type: ignore
            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages[:25]]
            extracted = "\n\n".join(p for p in pages if p.strip())
            if extracted.strip():
                return extracted
        except Exception:
            pass
        try:
            fitz = importlib.import_module("fitz")  # type: ignore
            doc = fitz.open(str(path))
            pages = [doc[i].get_text("text") for i in range(min(25, len(doc)))]
            extracted = "\n\n".join(p for p in pages if p.strip())
            if extracted.strip():
                return extracted
        except Exception:
            pass
        return f"# {path.name}\n\nBinary PDF paper loaded from {path.name}."
    return path.read_text(encoding="utf-8", errors="replace")


LATEX_SYMBOLS = (
    (r"\varepsilon", "ε"),
    (r"\varphi", "φ"),
    (r"\epsilon", "ϵ"),
    (r"\alpha", "α"),
    (r"\beta", "β"),
    (r"\gamma", "γ"),
    (r"\delta", "δ"),
    (r"\zeta", "ζ"),
    (r"\eta", "η"),
    (r"\theta", "θ"),
    (r"\iota", "ι"),
    (r"\kappa", "κ"),
    (r"\lambda", "λ"),
    (r"\mu", "μ"),
    (r"\nu", "ν"),
    (r"\xi", "ξ"),
    (r"\pi", "π"),
    (r"\rho", "ρ"),
    (r"\sigma", "σ"),
    (r"\tau", "τ"),
    (r"\phi", "ϕ"),
    (r"\chi", "χ"),
    (r"\psi", "ψ"),
    (r"\omega", "ω"),
    (r"\Gamma", "Γ"),
    (r"\Delta", "Δ"),
    (r"\Theta", "Θ"),
    (r"\Lambda", "Λ"),
    (r"\Sigma", "Σ"),
    (r"\Phi", "Φ"),
    (r"\Psi", "Ψ"),
    (r"\Omega", "Ω"),
    (r"\infty", "∞"),
    (r"\partial", "∂"),
    (r"\nabla", "∇"),
    (r"\approx", "≈"),
    (r"\times", "×"),
    (r"\cdots", "⋯"),
    (r"\cdot", "⋅"),
    (r"\leq", "≤"),
    (r"\geq", "≥"),
    (r"\neq", "≠"),
    (r"\le", "≤"),
    (r"\ge", "≥"),
    (r"\in", "∈"),
)


def latex_to_mathml(expr: str, title_hint: str = "") -> str:
    """Convert a LaTeX or symbolic mathematical expression into strictly escaped native MathML (<math>).

    Never passes raw HTML tags through (preventing XSS) and guarantees zero raw LaTeX tokens remain.
    """
    raw = (expr or "").strip()
    if not raw:
        return ""

    # Strip any HTML/XML tags from input so attacker-supplied <img/script/math> tags never survive
    cleaned = re.sub(r"<[^>]*>", " ", raw)
    cleaned = cleaned.replace("<", " ≤ ").replace(">", " ≥ ")
    cleaned = cleaned.strip("$").strip()
    cleaned = re.sub(r"^\\\[|\\\]$", "", cleaned).strip()
    if not cleaned:
        return ""

    # Replace wrapper macros first
    cleaned = re.sub(r"\\(?:mathcal|mathbf|mathrm|text|hat|bar|tilde)\s*\{([^{}]+)\}", r"\1", cleaned)

    # Use private-use sentinel store for structured MathML blocks so user input is never split on '<...>'
    sentinels: Dict[str, str] = {}

    def _put_sentinel(mml_fragment: str) -> str:
        key = f"\ue000MML{len(sentinels)}\ue001"
        sentinels[key] = mml_fragment
        return key

    # 1. Handle \frac{num}{den}
    frac_pat = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    for _ in range(8):
        if not frac_pat.search(cleaned):
            break
        cleaned = frac_pat.sub(
            lambda m: _put_sentinel(
                f"<mfrac><mrow>{_simple_tokens_to_mml(m.group(1), sentinels)}</mrow>"
                f"<mrow>{_simple_tokens_to_mml(m.group(2), sentinels)}</mrow></mfrac>"
            ),
            cleaned,
        )

    # 2. Handle \sum_{sub}^{sup}
    sum_pat = re.compile(r"\\sum(?![A-Za-z])\s*(?:_\{([^{}]+)\}|_([A-Za-z0-9]))?\s*(?:\^\{([^{}]+)\}|\^([A-Za-z0-9]))?")
    if "\\sum" in cleaned:
        cleaned = sum_pat.sub(
            lambda m: _put_sentinel(
                f"<munderover><mo>∑</mo>"
                f"<mrow>{_simple_tokens_to_mml(m.group(1) or m.group(2) or 'i=1', sentinels)}</mrow>"
                f"<mrow>{_simple_tokens_to_mml(m.group(3) or m.group(4) or 'N', sentinels)}</mrow></munderover>"
            ),
            cleaned,
        )

    # 3. Handle \int_{sub}^{sup} (BEFORE \in replacement!)
    int_pat = re.compile(r"\\int(?![A-Za-z])\s*(?:_\{([^{}]+)\}|_([A-Za-z0-9]))?\s*(?:\^\{([^{}]+)\}|\^([A-Za-z0-9]))?")
    if "\\int" in cleaned:
        cleaned = int_pat.sub(
            lambda m: _put_sentinel(
                f"<msubsup><mo>∫</mo>"
                f"<mrow>{_simple_tokens_to_mml(m.group(1) or m.group(2) or '0', sentinels)}</mrow>"
                f"<mrow>{_simple_tokens_to_mml(m.group(3) or m.group(4) or 'T', sentinels)}</mrow></msubsup>"
            ),
            cleaned,
        )

    # 4. Replace LaTeX symbol commands longest-first with negative lookahead for letters
    for cmd, sym in sorted(LATEX_SYMBOLS, key=lambda kv: -len(kv[0])):
        cleaned = re.sub(re.escape(cmd) + r"(?![A-Za-z])", sym, cleaned)

    # Strip any remaining unknown backslash commands
    cleaned = re.sub(r"\\[A-Za-z]+", "", cleaned).replace("$$", "").replace("$", "")

    inner = _simple_tokens_to_mml(cleaned, sentinels)
    for k, v in sentinels.items():
        inner = inner.replace(k, v)

    if not inner:
        return ""
    return f"<math xmlns='http://www.w3.org/1998/Math/MathML' display='block'><mrow>{inner}</mrow></math>"


_IDENT_CHARS = r"A-Za-zα-ωΑ-Ωϵϕεφ"


def _simple_tokens_to_mml(text: str, sentinels: Dict[str, str]) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    for cmd, sym in sorted(LATEX_SYMBOLS, key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(cmd) + r"(?![A-Za-z])", sym, s)

    def _put_sub_sup(tag: str, base_tok: str, script_tok: str, script_tag: str) -> str:
        key = f"\ue000MML{len(sentinels)}\ue001"
        b_esc = html.escape(base_tok, quote=True)
        s_esc = html.escape(script_tok, quote=True)
        b_tag = "mn" if re.fullmatch(r"\d+(?:\.\d+)?", base_tok) else "mi"
        sentinels[key] = f"<{tag}><{b_tag}>{b_esc}</{b_tag}><{script_tag}>{s_esc}</{script_tag}></{tag}>"
        return key

    s = re.sub(
        rf"([{_IDENT_CHARS}])\s*_\s*\{{([^{{}}]+)\}}",
        lambda m: _put_sub_sup("msub", m.group(1), m.group(2), "mi"),
        s,
    )
    s = re.sub(
        rf"([{_IDENT_CHARS}])\s*_\s*([A-Za-z0-9]+)",
        lambda m: _put_sub_sup("msub", m.group(1), m.group(2), "mi"),
        s,
    )
    s = re.sub(
        rf"([{_IDENT_CHARS}0-9])\s*\^\s*\{{([^{{}}]+)\}}",
        lambda m: _put_sub_sup("msup", m.group(1), m.group(2), "mn"),
        s,
    )
    s = re.sub(
        rf"([{_IDENT_CHARS}0-9])\s*\^\s*([A-Za-z0-9]+)",
        lambda m: _put_sub_sup("msup", m.group(1), m.group(2), "mn"),
        s,
    )

    parts = re.split(r"(\ue000MML\d+\ue001)", s)
    out: List[str] = []
    for p in parts:
        if p in sentinels:
            out.append(sentinels[p])
        else:
            out.append(_plain_chars_to_mml(p))
    return "".join(out)


def _plain_chars_to_mml(s: str) -> str:
    tokens = re.findall(rf"[{_IDENT_CHARS}_]+|\d+(?:\.\d+)?|[=+*/()\[\]≤≥≠≈∈⋅⋯×∞∇∂,-]", s)
    out: List[str] = []
    for tok in tokens:
        esc_tok = html.escape(tok, quote=True)
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            out.append(f"<mn>{esc_tok}</mn>")
        elif re.fullmatch(rf"[{_IDENT_CHARS}_]+", tok):
            out.append(f"<mi>{esc_tok}</mi>")
        else:
            out.append(f"<mo>{esc_tok}</mo>")
    return "".join(out)


def _scan_non_python_buckets(repo: Path, start_idx: int = 1) -> List[Dict[str, Any]]:
    """Fallback/supplemental scanner for .js/.mjs/.ts/.R files when a repo contains non-Python modules."""
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".anvil", ".ecgberht"}
    exts = {".js", ".mjs", ".ts", ".r"}
    files: List[Path] = []
    if repo.is_file() and not repo.is_symlink() and repo.suffix.lower() in exts:
        files = [repo]
    elif repo.is_dir():
        for root, dirs, fnames in os.walk(repo, followlinks=False):
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
            for f in sorted(fnames):
                fp = Path(root) / f
                if not fp.is_symlink() and fp.suffix.lower() in exts:
                    files.append(fp)
                    if len(files) >= 25:
                        break
            if len(files) >= 25:
                break

    buckets: List[Dict[str, Any]] = []
    fn_re = re.compile(
        r"^(?:\s*export\s+)?(?:\s*async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"
        r"|^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
        r"|^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*<-\s*function\s*\(([^)]*)\)"
    )
    for offset, fpath in enumerate(files):
        rel = fpath.name if repo.is_file() else fpath.relative_to(repo).as_posix()
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        funcs: List[Dict[str, Any]] = []
        for lno, line in enumerate(lines, start=1):
            m = fn_re.search(line)
            if not m:
                continue
            name = m.group(1) or m.group(3) or m.group(5)
            raw_args = m.group(2) or m.group(4) or m.group(6) or ""
            args = [a.strip().split("=")[0].strip() for a in raw_args.split(",") if a.strip()][:5]
            end_lno = min(len(lines), lno + 25)
            snippet = "\n".join(lines[lno - 1:end_lno])
            stage = anvil_engine._classify_stage(name, "", snippet) if anvil_engine else "compute"
            ai_info = anvil_engine._detect_ai_interaction(name, "", snippet) if anvil_engine else None
            funcs.append({
                "name": name,
                "file": rel,
                "lineno": lno,
                "end_lineno": end_lno,
                "args": args,
                "summary": f"Executes {name}({', '.join(args)}) in {rel}.",
                "calls": [],
                "stage": stage,
                "ai_interaction": ai_info,
            })
        if not funcs:
            continue
        bid = f"block-{start_idx + offset}-{re.sub(r'[^a-z0-9]+', '-', Path(rel).stem.lower()).strip('-')}"
        stages = [fn["stage"] for fn in funcs]
        dominant = max(("ingest", "compute", "emit"), key=lambda s: stages.count(s))
        ai_seams = [fn["ai_interaction"] for fn in funcs if fn.get("ai_interaction")]
        buckets.append({
            "id": bid,
            "title": Path(rel).stem.replace("_", " ").replace("-", " ").title(),
            "file": rel,
            "summary": f"Module {rel} ({len(funcs)} functions)",
            "pipeline_stage": dominant,
            "ai_agent_touchpoints": ai_seams,
            "functions": funcs,
            "validated": False,
            "source_preview": "\n".join(lines[:75]),
            "total_lines": len(lines),
        })
    return buckets


def _build_inner_flow_diagram(block_title: str, steps: List[Dict[str, Any]], inner_edges: List[Dict[str, str]]) -> Dict[str, Any]:
    """Build a canonical FoundryFlowDiagram object for Mode 2 (Inner Process Map inside a single block)."""
    stage_col = {"ingest": 0, "compute": 1, "emit": 2}
    col_rows: Dict[int, List[int]] = {0: [], 1: [], 2: []}
    nodes_out: List[Dict[str, Any]] = []
    steps_out: List[Dict[str, Any]] = []

    for idx, st in enumerate(steps[:8]):
        stg = st.get("stage") or "compute"
        col = stage_col.get(stg, 1)
        row = len(col_rows[col])
        col_rows[col].append(row)
        has_ai = bool(st.get("ai_interaction"))
        shape = "model-call" if has_ai else ("human-gate" if st.get("is_entrypoint") else "program")
        fn_name = st["name"]
        short_fn = fn_name if len(fn_name) <= 24 else fn_name[:22] + "…"
        step_id = f"step-{idx + 1}-{re.sub(r'[^a-z0-9]+', '-', fn_name.lower()).strip('-')}"
        st["step_id"] = step_id
        steps_out.append({
            "id": step_id,
            "num": str(idx + 1),
            "title": f"{fn_name}({', '.join((st.get('args') or [])[:2])})",
            "shape": shape,
            "Summary": st.get("summary") or "",
            "reads": [st.get("file") or ""],
            "writes": [f"L{st.get('lineno', 1)}–{st.get('end_lineno', st.get('lineno', 1))} · {stg.upper()}"],
        })
        nodes_out.append({
            "id": step_id,
            "num": str(idx + 1),
            "label": short_fn,
            "caption": f"L{st.get('lineno', 1)} · {stg.upper()}",
            "shape": shape,
            "col": col,
            "row": row,
            "stage": stg,
        })

    bands_out = []
    for c, lbl, tone in (
        (0, "1. INGEST / ENTRYPOINTS", "ingest"),
        (1, "2. COMPUTE / CORE LOGIC", "compute"),
        (2, "3. EMIT / SERIALIZE", "emit"),
    ):
        rows = col_rows.get(c) or [0]
        bands_out.append({
            "index": c,
            "label": lbl,
            "tone": tone,
            "first_col": c,
            "last_col": c,
            "first_row": min(rows),
            "last_row": max(rows),
        })

    name_to_id = {st["name"]: st.get("step_id") for st in steps[:8] if st.get("step_id")}
    edges_out: List[Dict[str, str]] = []
    for e in inner_edges:
        fid = name_to_id.get(e["from"])
        tid = name_to_id.get(e["to"])
        if fid and tid and fid != tid:
            edges_out.append({"from": fid, "to": tid, "kind": "forward", "label": "calls"})
    if not edges_out and len(nodes_out) > 1:
        for i in range(len(nodes_out) - 1):
            edges_out.append({"from": nodes_out[i]["id"], "to": nodes_out[i + 1]["id"], "kind": "forward", "label": ""})

    return {
        "summary": f"Inner Function Flow Inside {block_title}",
        "steps": steps_out,
        "edges": edges_out,
        "diagram": {
            "col_width": 210,
            "row_height": 102,
            "node_width": 172,
            "node_height": 62,
            "bands": bands_out,
            "nodes": nodes_out,
        },
    }


def _enrich_buckets_with_previews(repo: Path, buckets: List[Dict[str, Any]]) -> None:
    base = repo.parent if repo.is_file() else repo
    for b in buckets:
        if not (b.get("source_preview") and b.get("total_lines")):
            rel = b.get("primary_file") or b.get("file") or ""
            fpath = (base / rel).resolve() if rel else None
            if fpath and fpath.is_file() and not fpath.is_symlink():
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    b["source_preview"] = "\n".join(lines[:80])
                    if not b.get("total_lines"):
                        b["total_lines"] = len(lines)
                except Exception:
                    b["source_preview"] = ""
        # Build inner_process_map for Mode 2 (Single-Block Drill-Down)
        funcs = b.get("functions") or []
        fn_by_short = {fn["name"].split(".")[-1]: fn["name"] for fn in funcs}
        inner_edges: List[Dict[str, str]] = []
        called_in_block: set[str] = set()
        for fn in funcs:
            for callee in fn.get("calls") or []:
                if callee in fn_by_short and fn_by_short[callee] != fn["name"]:
                    inner_edges.append({"from": fn["name"], "to": fn_by_short[callee]})
                    called_in_block.add(fn_by_short[callee])
        # Order inner steps: entrypoints (not called internally) first, then callees, preserving line order
        entrypoints = [fn for fn in funcs if fn["name"] not in called_in_block]
        internal_callees = [fn for fn in funcs if fn["name"] in called_in_block]
        ordered_fns = entrypoints + internal_callees
        steps_list = [
            {
                "step_num": idx + 1,
                "name": fn["name"],
                "file": fn.get("file") or b.get("primary_file") or b.get("file") or "",
                "lineno": fn.get("lineno", 1),
                "end_lineno": fn.get("end_lineno", fn.get("lineno", 1)),
                "stage": fn.get("stage", "compute"),
                "args": fn.get("args") or [],
                "summary": fn.get("summary") or "",
                "calls": fn.get("calls") or [],
                "ai_interaction": fn.get("ai_interaction"),
                "is_entrypoint": fn["name"] not in called_in_block,
            }
            for idx, fn in enumerate(ordered_fns[:12])
        ]
        b["inner_process_map"] = {
            "steps": steps_list,
            "edges": inner_edges,
            "flow_diagram": _build_inner_flow_diagram(b.get("title") or b["id"], steps_list, inner_edges),
        }


def _build_best_in_class_remap(
    sw_path: Path,
    cmp_path: Path,
    code_map: Dict[str, Any],
    orange_split: Dict[str, Any],
    remap: Dict[str, Any],
) -> Dict[str, Any]:
    """Synthesize the 3-column Old Monolithic Code -> New Best-in-Class Process Map -> Null Space model for Mode 3."""
    buckets = code_map.get("conceptual_buckets") or []
    module_buckets = code_map.get("module_buckets") or buckets
    pith_names = {p.get("name") for p in (orange_split.get("pith_and_seeds") or [])}
    juice_names = {j.get("name") for j in (orange_split.get("juice") or [])}
    target_stem = sw_path.stem if sw_path.is_file() else sw_path.name
    clean_stem = re.sub(r"[^a-z0-9_]+", "_", target_stem.lower()).strip("_") or "module"

    # Map each file to its parent Conceptual Architectural Bucket
    file_to_arch_bucket: Dict[str, Dict[str, Any]] = {}
    for ab in buckets:
        for mf in (ab.get("member_files") or [ab.get("file") or ""]):
            if mf:
                file_to_arch_bucket[mf] = ab

    # Build Old Monolithic Code cards from module_buckets (sorted by total_lines / function count so monoliths appear at top)
    old_monoliths: List[Dict[str, Any]] = []
    ingest_all: List[Dict[str, Any]] = []
    compute_all: List[Dict[str, Any]] = []
    emit_all: List[Dict[str, Any]] = []
    ai_all: List[Dict[str, Any]] = []

    sorted_modules = sorted(
        module_buckets,
        key=lambda b: (int(b.get("total_lines") or 0), len(b.get("functions") or [])),
        reverse=True,
    )

    for b in sorted_modules:
        funcs = b.get("functions") or []
        rel_file = b.get("file") or ""
        parent_arch = file_to_arch_bucket.get(rel_file) or (buckets[0] if buckets else b)
        b_ingest = [f for f in funcs if f["name"] not in pith_names and f.get("stage") == "ingest"]
        b_compute = [f for f in funcs if f["name"] not in pith_names and (f["name"] in juice_names or f.get("stage") == "compute")]
        b_emit = [f for f in funcs if f["name"] not in pith_names and f.get("stage") == "emit" and f["name"] not in juice_names]
        b_null = [f for f in funcs if f["name"] in pith_names]
        b_ai = [f for f in funcs if f.get("ai_interaction")]

        for f in b_ingest:
            ingest_all.append({**f, "source_block_id": parent_arch["id"], "source_file": rel_file})
        for f in b_compute:
            compute_all.append({**f, "source_block_id": parent_arch["id"], "source_file": rel_file})
        for f in b_emit:
            emit_all.append({**f, "source_block_id": parent_arch["id"], "source_file": rel_file})
        for f in b_ai:
            ai_all.append({**f, "source_block_id": parent_arch["id"], "source_file": rel_file})

        mapped_targets: List[Dict[str, str]] = []
        if b_ingest:
            mapped_targets.append({
                "target_id": "new-block-ingest",
                "label": f"Mapped to New Block 1: Get-Data ({len(b_ingest)} fn)",
                "kind": "mapped",
            })
        if b_compute:
            mapped_targets.append({
                "target_id": "new-block-compute",
                "label": f"Mapped to New Block 2: Do-Analysis · Essential Core ({len(b_compute)} fn)",
                "kind": "mapped",
            })
        if b_emit:
            mapped_targets.append({
                "target_id": "new-block-emit",
                "label": f"Mapped to New Block 3: Create-Output ({len(b_emit)} fn)",
                "kind": "mapped",
            })
        if b_null:
            mapped_targets.append({
                "target_id": "null-space",
                "label": f"Sent to ∅ Null Space ({len(b_null)} fn: {', '.join(f['name'] for f in b_null[:3])})",
                "kind": "null",
            })

        mixed_stages = sum(1 for grp in (b_ingest, b_compute, b_emit) if grp) > 1
        old_monoliths.append({
            "block_id": parent_arch["id"],
            "module_block_id": b["id"],
            "arch_bucket_title": parent_arch.get("title") or parent_arch["id"],
            "title": b.get("title") or b["id"],
            "file": rel_file,
            "total_lines": b.get("total_lines") or 0,
            "function_count": len(funcs),
            "mixed_concerns": mixed_stages,
            "summary": b.get("summary") or "",
            "counts": {
                "ingest": len(b_ingest),
                "compute": len(b_compute),
                "emit": len(b_emit),
                "null_space": len(b_null),
            },
            "sample_functions": [f["name"] for f in funcs[:6]],
            "mapped_targets": mapped_targets,
        })

    # Detect any existing extracted *_core.py blocks in module_buckets so we can link directly to them
    core_mod = next(
        (m for m in module_buckets if (m.get("file") or "").lower().endswith("_core.py")),
        next((m for m in module_buckets if "core" in (m.get("file") or "").lower()), None),
    )
    core_arch_bucket = (
        file_to_arch_bucket.get(core_mod["file"])
        if core_mod and core_mod.get("file") in file_to_arch_bucket
        else next((b for b in buckets if b.get("pipeline_stage") == "compute"), buckets[0] if buckets else None)
    )
    ingest_bucket = next((b for b in buckets if b.get("pipeline_stage") == "ingest"), buckets[0] if buckets else None)
    emit_bucket = next((b for b in buckets if b.get("pipeline_stage") == "emit"), buckets[-1] if buckets else None)

    core_file_name = Path(core_mod["file"]).name if core_mod else f"{clean_stem}_core.py"

    new_blocks: List[Dict[str, Any]] = [
        {
            "id": "new-block-ingest",
            "drill_block_id": ingest_bucket["id"] if ingest_bucket else "",
            "stage": "ingest",
            "stage_badge": "STAGE 1 · GET-DATA (INGEST)",
            "title": f"New Block 1 — {clean_stem}_ingest.py (Data & State Readers)",
            "file": f"{clean_stem}_ingest.py",
            "summary": (
                f"Consolidates {len(ingest_all)} Peel (Get-Data) functions across {len(old_monoliths)} modules into "
                "side-effect-isolated file/JSON/request readers with explicit schema validation."
            ),
            "function_count": len(ingest_all),
            "functions": [
                {
                    "name": f["name"],
                    "old_file": f["source_file"],
                    "lineno": f.get("lineno", 1),
                    "summary": f.get("summary", ""),
                    "stage": "ingest",
                }
                for f in ingest_all[:40]
            ],
            "ai_hook": None,
        },
        {
            "id": "new-block-compute",
            "drill_block_id": (core_arch_bucket or (buckets[0] if buckets else {})).get("id", ""),
            "stage": "compute",
            "stage_badge": "STAGE 2 · DO-ANALYSIS (ESSENTIAL CORE / JUICE)",
            "title": f"New Block 2 — {core_file_name} (Pure Essential Core · Differential Equivalence Gate)",
            "file": core_file_name,
            "summary": (
                f"Isolates {len(compute_all)} Essential Core (Juice) domain & analysis functions with zero "
                "disk/network/UI side effects so differential equivalence checks can run deterministically."
            ),
            "function_count": len(compute_all),
            "functions": [
                {
                    "name": f["name"],
                    "old_file": f["source_file"],
                    "lineno": f.get("lineno", 1),
                    "summary": f.get("summary", ""),
                    "stage": "compute",
                }
                for f in compute_all[:50]
            ],
            "ai_hook": (
                f"🤖 {len(ai_all)} AI Agent Seam(s) isolated behind typed dispatch/verdict contracts"
                if ai_all else None
            ),
        },
        {
            "id": "new-block-emit",
            "drill_block_id": emit_bucket["id"] if emit_bucket else "",
            "stage": "emit",
            "stage_badge": "STAGE 3 · CREATE-OUTPUT (EMIT & SERIALIZATION)",
            "title": f"New Block 3 — {clean_stem}_emit.py (Output & Route Renderers)",
            "file": f"{clean_stem}_emit.py",
            "summary": (
                f"Consolidates {len(emit_all)} Peel (Create-Output) formatters, HTML/JSON serializers, and "
                "atomic file writers that consume pure Essential Core dicts."
            ),
            "function_count": len(emit_all),
            "functions": [
                {
                    "name": f["name"],
                    "old_file": f["source_file"],
                    "lineno": f.get("lineno", 1),
                    "summary": f.get("summary", ""),
                    "stage": "emit",
                }
                for f in emit_all[:40]
            ],
            "ai_hook": None,
        },
    ]

    # Build Architectural Bucket Old -> New Best-in-Class Map cards + FoundryFlowDiagram for Mode 3
    architecture_blocks: List[Dict[str, Any]] = []
    for idx, ab in enumerate(buckets):
        ab_funcs = ab.get("functions") or []
        ab_ing = sum(1 for f in ab_funcs if f["name"] not in pith_names and f.get("stage") == "ingest")
        ab_cmp = sum(1 for f in ab_funcs if f["name"] not in pith_names and (f["name"] in juice_names or f.get("stage") == "compute"))
        ab_emt = sum(1 for f in ab_funcs if f["name"] not in pith_names and f.get("stage") == "emit" and f["name"] not in juice_names)
        ab_nul = sum(1 for f in ab_funcs if f["name"] in pith_names)
        architecture_blocks.append({
            "id": ab["id"],
            "num": idx + 1,
            "title": ab.get("title") or ab["id"],
            "member_files": ab.get("member_files") or [ab.get("file") or ""],
            "stage": ab.get("pipeline_stage") or "compute",
            "summary": ab.get("summary") or "",
            "counts": {"ingest": ab_ing, "compute": ab_cmp, "emit": ab_emt, "null_space": ab_nul},
        })

    ns_count = len((remap.get("null_space") or {}).get("items") or [])
    remap_flow_diagram = {
        "summary": "Old Monolithic Code → Best-in-Class 3-Stage Architecture (Get-Data → Essential Core → Create-Output) + Explicit ∅ Null Space Gate",
        "steps": [
            {
                "id": "old-monoliths",
                "num": "OLD",
                "title": f"Old Monolithic Modules ({len(old_monoliths)} files)",
                "shape": "program",
                "Summary": f"{sum(1 for m in old_monoliths if m['mixed_concerns'])} mixed-stage modules decomposed via CST/AST.",
                "reads": [m["file"] for m in old_monoliths[:4]],
                "writes": ["AST & CST Decomposition"],
            },
            {
                "id": "new-block-ingest",
                "num": "1",
                "title": f"Stage 1 · Get-Data Ingest ({len(ingest_all)} fn)",
                "shape": "program",
                "Summary": new_blocks[0]["summary"],
                "reads": ["HTTP / JSON / Cockpit Files"],
                "writes": ["Validated Input Dicts"],
            },
            {
                "id": "new-block-compute",
                "num": "2",
                "title": f"Stage 2 · Essential Core ({len(compute_all)} fn)",
                "shape": "model-call",
                "Summary": new_blocks[1]["summary"],
                "reads": ["Validated Input Dicts"],
                "writes": ["Pure Domain Decisions & Typed Contracts"],
            },
            {
                "id": "new-block-emit",
                "num": "3",
                "title": f"Stage 3 · Create-Output ({len(emit_all)} fn)",
                "shape": "program",
                "Summary": new_blocks[2]["summary"],
                "reads": ["Pure Domain Decisions"],
                "writes": ["HTML / JSON / Atomic Disk Writes"],
            },
            {
                "id": "null-space-gate",
                "num": "∅",
                "title": f"∅ Null Space Ledger ({ns_count} fn)",
                "shape": "human-gate",
                "Summary": "Explicit human sign-off required for every retired legacy/unreferenced function.",
                "reads": ["Pith & Seeds Candidates"],
                "writes": ["Signed-Off Null Space Receipt"],
            },
        ],
        "edges": [
            {"from": "old-monoliths", "to": "new-block-ingest", "kind": "forward", "label": f"{len(ingest_all)} Peel fn"},
            {"from": "new-block-ingest", "to": "new-block-compute", "kind": "forward", "label": "pure dicts"},
            {"from": "new-block-compute", "to": "new-block-emit", "kind": "forward", "label": f"{len(compute_all)} Core fn"},
            {"from": "old-monoliths", "to": "null-space-gate", "kind": "loop", "label": f"{ns_count} ∅ drops"},
        ],
        "diagram": {
            "col_width": 215,
            "row_height": 108,
            "node_width": 176,
            "node_height": 64,
            "bands": [
                {"index": 0, "label": "OLD MONOLITHIC CODE", "tone": "ingest", "first_col": 0, "last_col": 0, "first_row": 0, "last_row": 1},
                {"index": 1, "label": "STAGE 1 · GET-DATA", "tone": "ingest", "first_col": 1, "last_col": 1, "first_row": 0, "last_row": 1},
                {"index": 2, "label": "STAGE 2 · ESSENTIAL CORE", "tone": "compute", "first_col": 2, "last_col": 2, "first_row": 0, "last_row": 0},
                {"index": 3, "label": "STAGE 3 · CREATE-OUTPUT", "tone": "emit", "first_col": 3, "last_col": 3, "first_row": 0, "last_row": 0},
            ],
            "nodes": [
                {"id": "old-monoliths", "num": "OLD", "label": f"Old Monoliths ({len(old_monoliths)})", "caption": f"{sum(1 for m in old_monoliths if m['mixed_concerns'])} mixed files", "shape": "program", "col": 0, "row": 0, "stage": "ingest"},
                {"id": "new-block-ingest", "num": "1", "label": "Stage 1 · Get-Data", "caption": f"{len(ingest_all)} fn · INGEST", "shape": "program", "col": 1, "row": 0, "stage": "ingest"},
                {"id": "new-block-compute", "num": "2", "label": f"Stage 2 · {core_file_name}", "caption": f"{len(compute_all)} fn · CORE JUICE", "shape": "model-call", "col": 2, "row": 0, "stage": "compute"},
                {"id": "new-block-emit", "num": "3", "label": "Stage 3 · Create-Output", "caption": f"{len(emit_all)} fn · EMIT", "shape": "program", "col": 3, "row": 0, "stage": "emit"},
                {"id": "null-space-gate", "num": "∅", "label": "∅ Null Space Gate", "caption": f"{ns_count} fn · Sign-Off", "shape": "human-gate", "col": 1, "row": 1, "stage": "ingest"},
            ],
        },
    }

    return {
        "old_monoliths": old_monoliths,
        "new_blocks": new_blocks,
        "architecture_blocks": architecture_blocks,
        "flow_diagram": remap_flow_diagram,
        "totals": {
            "old_modules": len(old_monoliths),
            "mixed_modules": sum(1 for m in old_monoliths if m["mixed_concerns"]),
            "ingest_fns": len(ingest_all),
            "compute_fns": len(compute_all),
            "emit_fns": len(emit_all),
            "null_space_fns": ns_count,
        },
    }


def extract_paper_claims_and_align(
    repo: Path,
    buckets: List[Dict[str, Any]],
    paper_info: Dict[str, Any],
    code_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract sections, algorithms, and MathML equations from a paper and align to companion software."""
    text = str(paper_info.get("text") or "")
    paper_title = str(paper_info.get("title") or "Paper")
    paper_path_str = str(paper_info.get("path") or "").strip()

    # Check if paper_info is an explicit inline JSON {"claims": [...]} spec
    is_inline_json_claims = False
    raw_claims: List[Dict[str, str]] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("claims"), list):
            is_inline_json_claims = True
            for idx, item in enumerate(parsed["claims"]):
                raw_claims.append({
                    "id": str(item.get("id") or f"eq-{idx + 1}"),
                    "title": str(item.get("title") or f"Claim {idx + 1}"),
                    "expr": str(item.get("latex") or item.get("equation") or ""),
                    "context": str(item.get("description") or item.get("title") or ""),
                })
    except Exception:
        is_inline_json_claims = False

    # Delegate directly to anvil_engine.paper_to_code_map for rich sections[], algorithms[], and equations[]
    if not is_inline_json_claims and anvil_engine is not None and hasattr(anvil_engine, "paper_to_code_map") and paper_path_str:
        p_path = Path(paper_path_str)
        if p_path.exists():
            pmap = anvil_engine.paper_to_code_map(repo, p_path, code_map=code_map)
            pmap["paper_source_type"] = paper_info.get("source_type", pmap.get("paper_source_type", "local"))
            pmap["paper_url"] = paper_info.get("url", pmap.get("paper_url", ""))
            if paper_info.get("bundle_dir"):
                pmap["bundle_dir"] = paper_info["bundle_dir"]
            if paper_title and (not pmap.get("paper_title") or pmap.get("paper_title") == p_path.stem):
                pmap["paper_title"] = paper_title
            return pmap

    # Fallback for inline JSON claim specs or when anvil_engine is unavailable
    if not raw_claims:
        eq_blocks = re.findall(
            r"(?:\$\$(.+?)\$\$|\\begin\{equation\*?\}(.+?)\\end\{equation\*?\})",
            text,
            flags=re.S,
        )
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for idx, (m1, m2) in enumerate(eq_blocks[:10]):
            eq_str = " ".join((m1 or m2).split())
            raw_claims.append({
                "id": f"eq-{idx + 1}",
                "title": f"Equation {idx + 1} ({paper_title[:45]})",
                "expr": eq_str,
                "context": " ".join(lines[:12]),
            })

    all_funcs: List[Dict[str, Any]] = []
    for b in buckets:
        for fn in b.get("functions", []):
            all_funcs.append({
                **fn,
                "bucket_id": b["id"],
                "bucket_title": b["title"],
                "bucket_validated": bool(b.get("validated")),
            })

    def _toks(s: str) -> set[str]:
        return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) >= 3}

    mml_fn = getattr(anvil_engine, "latex_to_mathml", None) if anvil_engine is not None else None
    alignments: List[Dict[str, Any]] = []
    for c in raw_claims[:12]:
        claim_tokens = _toks(f"{c['title']} {c['context']} {c['expr']}")
        best_fn: Optional[Dict[str, Any]] = None
        best_score = 0.0
        best_overlap: List[str] = []
        for fn in all_funcs:
            fn_tokens = _toks(f"{fn['name']} {' '.join(fn.get('args', []))} {fn.get('summary', '')} {fn.get('file', '')}")
            common = sorted(claim_tokens & fn_tokens)
            if not common:
                continue
            score = len(common) * 2.0 + (1.0 if fn.get("stage") == "compute" else 0.0)
            if score > best_score:
                best_score = score
                best_fn = fn
                best_overlap = common[:5]

        mml = (mml_fn(c["expr"]) if mml_fn else latex_to_mathml(c["expr"])) if c.get("expr") else ""
        if best_fn is not None:
            status = "EXECUTED_PASS" if best_fn.get("bucket_validated") else "STATIC_ALIGNED"
            rationale = f"Matched on shared domain terms ({', '.join(best_overlap)}) in {best_fn['stage'].upper()} stage"
        else:
            status = "PAPER_ONLY_UNIMPLEMENTED"
            rationale = "No function shared domain terms with this claim"

        alignments.append({
            "claim_id": c["id"],
            "title": c["title"],
            "mathml": mml,
            "mapped_function": best_fn["name"] if best_fn else None,
            "mapped_file": best_fn["file"] if best_fn else None,
            "lineno": best_fn["lineno"] if best_fn else None,
            "bucket_id": best_fn.get("bucket_id") if best_fn else None,
            "match_rationale": rationale,
            "empirical_status": status,
        })

    return {
        "schema": "anvil-paper-map/v1",
        "paper_title": paper_title,
        "paper_source_type": paper_info.get("source_type", "local"),
        "paper_url": paper_info.get("url", ""),
        "paper_path": paper_path_str,
        "repo": str(repo),
        "claims_mapped": len(alignments),
        "native_mathml_enforced": True,
        "sections": [],
        "algorithms": [],
        "equations": [],
        "alignments": alignments,
    }


def _build_anvil_v2_report_section(session: Dict[str, Any], heading_prefix: str = "## 5.") -> List[str]:
    buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
    panel = session.get("beta_reader_panel") or {}
    wt = session.get("walkthrough_trace") or {}
    lines: List[str] = [
        "",
        f"{heading_prefix} Anvil v2 — 3-Level Progressive Abstraction, 5-Seat Software Beta-Reader Panel & Live Code Walkthrough",
        "",
        "### A. 3-Level Progressive Abstraction Map (Level 1 Summary → Level 2 Mechanics/MathML/Diff → Level 3 Code)",
        "",
        "| Block | Level 1 (Role & I/O) | Level 2 (Sub-Blocks · Formulas · Assumptions) | Level 3 (Exact Lines & Functions) |",
        "|---|---|---|---|",
    ]
    for b in buckets[:20]:
        l1 = b.get("level1_summary") or {}
        l2 = b.get("level2_mechanics") or {}
        l3 = b.get("level3_code") or {}
        sub_cnt = len(l2.get("sub_blocks") or [])
        eq_cnt = len(l2.get("formulas_mathml") or [])
        as_cnt = len(l2.get("assumptions") or [])
        lines.append(
            f"| **`{b.get('title')}`** (`{b.get('file')}`) | {l1.get('role') or b.get('summary') or ''} "
            f"| `{sub_cnt}` sub-blocks · `{eq_cnt}` MathML formula(s) · `{as_cnt}` explicit assumption(s) "
            f"| `{l3.get('file') or b.get('file')}` (`L{l3.get('start_line', 1)}–L{l3.get('end_line', 1)}` · `{len(b.get('functions') or [])}` fn) |"
        )

    seats = panel.get("seats") or []
    if seats:
        lines.extend([
            "",
            f"### B. 5-Seat Software Beta-Reader Panel (Verdict: `{panel.get('overall_status') or panel.get('overall_verdict') or 'PASS'}` · Score: `{panel.get('overall_score', 90)}/100`)",
            "",
            "| Seat | Specialist Role | Focus | Status | Score | Summary & Actionable Fix |",
            "|---|---|---|---|---|---|",
        ])
        for idx, s in enumerate(seats, 1):
            role_txt = s.get("title") or s.get("persona_name") or s.get("role") or f"Seat {idx}"
            focus_txt = s.get("focus") or s.get("lens") or ""
            status_txt = s.get("status") or s.get("verdict") or "PASS"
            score_txt = f"{s.get('score', 90)}/100"
            sum_txt = s.get("summary") or f"{s.get('key_finding', '')} Fix: {s.get('actionable_fix', '')}".strip()
            lines.append(
                f"| **Seat {idx}** | **{role_txt}** | {focus_txt} | `{status_txt}` | `{score_txt}` | {sum_txt} |"
            )

    steps = wt.get("steps") or []
    if steps:
        acc_cnt = (wt.get("counts") or {}).get("accurate", wt.get("accurate_steps", 0))
        tot_cnt = wt.get("total_steps", wt.get("step_count", len(steps)))
        lines.extend([
            "",
            f"### C. Live Code Walkthrough Trace (`{wt.get('language', 'python').upper()}` · `{acc_cnt}/{tot_cnt}` Steps Executed · Verdict: `{wt.get('overall_verdict', 'STATIC_ONLY')}`)",
            "",
            "| Step | Function | What Code Claims To Do | Concrete Input Data | Actual Runtime Calculation & Output | Accuracy Verdict |",
            "|---|---|---|---|---|---|",
        ])
        for st in steps[:20]:
            step_idx = st.get("step") or st.get("step_index") or 1
            fn_nm = st.get("function") or st.get("function_name") or "entrypoint"
            raw_inp = st.get("concrete_input") if st.get("concrete_input") is not None else st.get("input_snapshot", "")
            inp_s = (raw_inp if isinstance(raw_inp, str) else json.dumps(raw_inp, ensure_ascii=False))[:90]
            out_s = str(st.get("actual_output_summary") or st.get("actual_behavior") or "")[:120]
            note_s = str(st.get("calculation_note") or st.get("discrepancy_notes") or "")[:110]
            claim_s = str(st.get("claim") or st.get("claimed_behavior") or "").replace("|", "\\|")[:100]
            lines.append(
                f"| **{step_idx}/{st.get('total_steps', len(steps))}** | `{fn_nm}` (`{st.get('file')}:L{st.get('lineno', 1)}`) "
                f"| {claim_s} | `{inp_s}` | {out_s} ({note_s}) | **`{st.get('verdict', 'STATIC_ONLY')}`** |"
            )
    return lines


def _write_anvil_manifest(cdir: Path, session: Dict[str, Any]) -> Path:
    manifest_path = _session_dir(cdir) / "manifest.json"
    code_map = session.get("code_map") or {}
    buckets = code_map.get("conceptual_buckets") or []
    manifest = {
        "schema": "anvil-manifest/v2",
        "cockpit_dir": str(cdir),
        "cockpit_name": session.get("cockpit_name") or cdir.name,
        "updated_at": session.get("updated_at"),
        "software": session.get("software"),
        "conceptual_buckets": buckets,
        "process_map": code_map.get("process_map"),
        "orange_split": session.get("orange_split"),
        "remap": session.get("remap"),
        "paper_map": session.get("paper_map"),
        "beta_reader_panel": session.get("beta_reader_panel"),
        "walkthrough_trace": session.get("walkthrough_trace"),
    }
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
    return manifest_path


def _write_anvil_report(cdir: Path, session: Dict[str, Any]) -> Path:
    report_path = cdir / "ANVIL-REPORT.md"
    if report_path.is_file():
        try:
            existing_text = report_path.read_text(encoding="utf-8", errors="replace")
            if existing_text.lstrip().startswith("# Illustrated Anvil Architecture"):
                marker = "\n## 7. Anvil v2 —"
                base_text = existing_text.split(marker)[0].rstrip()
                v2_lines = _build_anvil_v2_report_section(session, heading_prefix="## 7.")
                _atomic_write_text(report_path, base_text + "\n" + "\n".join(v2_lines) + "\n")
                return report_path
        except Exception:
            pass

    sw = session.get("software") or {}
    orange = session.get("orange_split") or {}
    counts = orange.get("counts") or {}
    remap = session.get("remap") or {}
    paper = session.get("paper_map")
    buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []

    lines = [
        f"# Anvil Session Report — {session.get('cockpit_name') or cdir.name}",
        "",
        f"- **Updated:** `{session.get('updated_at')}`",
        f"- **Session Mode:** `{session.get('mode', 'code').upper()}`",
        f"- **Software Target:** `{sw.get('label') or sw.get('path') or '.'}` (`{sw.get('source_type', 'local')}`)",
    ]
    if paper:
        lines.append(f"- **Paper Target:** `{paper.get('paper_title')}` ({paper.get('claims_mapped', 0)} claims analyzed)")
    lines.extend([
        "",
        "## 1. Parable of the Oranges — Essential Core vs. Scaffolding",
        f"- **Essential Domain Logic (Juice / Do-Analysis):** {counts.get('juice_count', 0)} functions",
        f"- **Surface I/O Contracts (Peel / Get-Data & Create-Output):** {counts.get('peel_count', 0)} functions",
        f"- **Legacy Scaffolding / Null Space Candidates (Pith & Seeds):** {counts.get('pith_and_seeds_count', 0)} functions",
        f"- **One-Trip Recommendation:** {(orange.get('proactive_staff_work') or {}).get('one_trip_recommendation', '')}",
        "",
        "## 2. Conceptual & Process Map Blocks",
    ])
    for b in buckets[:20]:
        vmark = "✓ VALIDATED" if b.get("validated") else "○ Pending Probe"
        lines.append(
            f"- **`{b.get('title')}`** (`{b.get('file')}`) · Stage: `{b.get('pipeline_stage', 'compute').upper()}` · "
            f"{len(b.get('functions') or [])} functions · {vmark} — {b.get('validated_description') or b.get('summary')}"
        )

    if remap:
        ns = remap.get("null_space") or {}
        lines.extend([
            "",
            "## 3. Old → New Code Map & Explicit Null Space",
            f"- **Remap Verdict:** `{remap.get('verdict', 'PASS')}`",
            f"- **Mapped Functions:** {len(remap.get('old_to_new_mappings') or [])}",
            f"- **Null Space Items:** {ns.get('count', 0)} ({ns.get('unexplained_blockers', 0)} unexplained blockers)",
        ])

    if paper and paper.get("alignments"):
        lines.extend([
            "",
            "## 4. Paper ↔ Code Alignments (Native MathML)",
        ])
        for al in paper["alignments"]:
            lines.append(
                f"- **{al.get('claim_id')} — {al.get('title')}** → `{al.get('mapped_function') or 'unmapped'}` "
                f"(`{al.get('mapped_file') or ''}:{al.get('lineno') or ''}`) [{al.get('empirical_status')}]"
            )

    lines.extend(_build_anvil_v2_report_section(session, heading_prefix="## 5."))
    _atomic_write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def _project_session_summary(session: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact (<15 KB) status projection of an active Anvil session for `?summary=1`."""
    code_map = session.get("code_map") or {}
    buckets = code_map.get("conceptual_buckets") or []
    compact_buckets: List[Dict[str, Any]] = []
    for b in buckets[:10]:
        l1 = b.get("level1_summary") or {}
        mfiles = list(b.get("member_files") or [])
        compact_buckets.append({
            "id": b.get("id"),
            "title": b.get("title"),
            "file": b.get("file"),
            "primary_file": b.get("primary_file") or b.get("file"),
            "pipeline_stage": b.get("pipeline_stage", "compute"),
            "validated": bool(b.get("validated")),
            "static_syntax_ok": bool(b.get("static_syntax_ok")),
            "function_count": len(b.get("functions") or []),
            "member_file_count": len(mfiles) or 1,
            "member_files": mfiles[:8],
            "summary": str(b.get("summary") or "")[:160],
            "level1_summary": {
                "role": str(l1.get("role") or l1.get("purpose") or "")[:140],
                "pure_core_pct": l1.get("pure_core_pct", 0),
            },
        })
    paper = session.get("paper_map")
    compact_paper = None
    if isinstance(paper, dict):
        compact_paper = {
            "schema": paper.get("schema", "anvil-paper-map/v1"),
            "paper_title": str(paper.get("paper_title") or "")[:120],
            "paper_source_type": paper.get("paper_source_type"),
            "paper_url": paper.get("paper_url", ""),
            "claims_mapped": paper.get("claims_mapped", 0),
            "summary_counts": paper.get("summary_counts") or {
                "sections": len(paper.get("sections") or []),
                "algorithms": len(paper.get("algorithms") or []),
                "equations": len(paper.get("equations") or []),
            },
        }
    panel = session.get("beta_reader_panel") or {}
    wt = session.get("walkthrough_trace") or {}
    remap = session.get("remap") or {}
    ns = remap.get("null_space") or {}
    return {
        "schema": session.get("schema", "anvil-cockpit-session/v1"),
        "summary_only": True,
        "active": bool(session.get("active")),
        "cockpit_dir": session.get("cockpit_dir"),
        "cockpit_name": session.get("cockpit_name"),
        "mode": session.get("mode", "code"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "software": session.get("software"),
        "compare_software": session.get("compare_software"),
        "selected_block_id": session.get("selected_block_id", ""),
        "signed_off_drops": list(session.get("signed_off_drops") or [])[:25],
        "code_map": {
            "schema": code_map.get("schema", "anvil-map/v1"),
            "total_files": code_map.get("total_files", len(code_map.get("module_buckets") or buckets)),
            "total_functions": code_map.get("total_functions", sum(len(b.get("functions") or []) for b in buckets)),
            "languages": code_map.get("languages") or {},
            "conceptual_buckets": compact_buckets,
            "process_map_counts": {
                "nodes": len((code_map.get("process_map") or {}).get("nodes") or []),
                "edges": len((code_map.get("process_map") or {}).get("edges") or []),
            },
        },
        "orange_split": {
            "counts": (session.get("orange_split") or {}).get("counts") or {},
        },
        "remap": {
            "verdict": remap.get("verdict", "PASS"),
            "null_space": {
                "count": ns.get("count", 0),
                "unexplained_blockers": ns.get("unexplained_blockers", 0),
            },
        },
        "paper_map": compact_paper,
        "beta_reader_panel": {
            "overall_status": panel.get("overall_status") or panel.get("overall_verdict") or "PASS",
            "overall_score": panel.get("overall_score", 0),
            "seats": [
                {
                    "seat_id": s.get("seat_id"),
                    "title": s.get("title") or s.get("persona_name"),
                    "status": s.get("status") or s.get("verdict"),
                    "score": s.get("score"),
                }
                for s in (panel.get("seats") or [])[:5]
            ],
        },
        "walkthrough_trace": {
            "overall_verdict": wt.get("overall_verdict", "STATIC_ONLY"),
            "total_steps": wt.get("total_steps", len(wt.get("steps") or [])),
            "counts": wt.get("counts") or {},
        },
        "chat_history": [
            {
                "role": m.get("role"),
                "mode": m.get("mode"),
                "target": m.get("target"),
                "text": str(m.get("text") or "")[:240],
                "answer_mode": m.get("answer_mode", "static_ast"),
                "at": m.get("at"),
            }
            for m in (session.get("chat_history") or [])[-5:]
        ],
    }


def get_cockpit_file_source(cockpit_dir: str | Path, rel_file: str) -> Dict[str, Any]:
    """Serve on-demand Level-3 numbered source, symbol table, and callers/callees for one file inside the session software root."""
    raw = (rel_file or "").strip()
    if not raw:
        raise ValueError("Query parameter 'file' is required.")
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Absolute, UNC, or drive-prefixed file paths are not permitted.")
    parts = [p for p in re.split(r"[\\/]+", raw) if p]
    if not parts:
        raise ValueError("Invalid file path.")
    for part in parts:
        low = part.lower()
        if part == "..":
            raise ValueError("Parent directory traversal ('..') is not permitted.")
        if low in FORBIDDEN_DOT_PARTS or low in FORBIDDEN_SECRET_NAMES or (part.startswith(".") and part != "."):
            raise ValueError(f"Access to restricted path component '{part}' is not permitted.")

    cdir = Path(cockpit_dir).resolve()
    sfile = _session_file(cdir)
    session: Optional[Dict[str, Any]] = None
    if sfile.is_file():
        try:
            loaded = json.loads(sfile.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict) and loaded.get("active"):
                session = loaded
        except Exception:
            session = None

    sw_root = Path((session.get("software") or {}).get("path") or cdir).resolve() if session else cdir
    rel_clean = Path(*[p for p in parts if p != "."])
    if sw_root.is_file():
        if rel_clean.as_posix() != sw_root.name:
            raise ValueError(f"File '{raw}' is outside the bound single-file software target '{sw_root.name}'.")
        resolved_target = sw_root
        repo_for_lookup = sw_root.parent
    else:
        walk = sw_root
        for part in rel_clean.parts:
            walk = walk / part
            if walk.is_symlink():
                raise ValueError("Symbolic links are not permitted.")
        cand = walk
        resolved_target = cand.resolve()
        if resolved_target == sw_root or sw_root not in resolved_target.parents:
            raise ValueError(f"File '{raw}' escapes software root boundary.")
        if resolved_target.is_symlink():
            raise ValueError("Symbolic links are not permitted.")
        repo_for_lookup = sw_root

    for part in resolved_target.parts:
        low = part.lower()
        if low in FORBIDDEN_DOT_PARTS or low in FORBIDDEN_SECRET_NAMES:
            raise ValueError(f"Access to restricted path component '{part}' is not permitted.")
    if not resolved_target.is_file():
        raise ValueError(f"Source file '{rel_clean.as_posix()}' was not found.")
    st_target = os.stat(resolved_target, follow_symlinks=False)
    if getattr(st_target, "st_nlink", 1) > 1:
        raise ValueError("Hard-linked files are not permitted.")

    rel_posix = rel_clean.as_posix()
    if anvil_engine is not None and hasattr(anvil_engine, "get_file_level3_source"):
        payload = anvil_engine.get_file_level3_source(
            repo_for_lookup,
            rel_posix,
            code_map=(session.get("code_map") if session else None),
        )
        return {"ok": True, **payload}

    src_text = resolved_target.read_text(encoding="utf-8", errors="replace")
    src_lines = src_text.splitlines()
    numbered = "\n".join(f"{i:4d} | {ln}" for i, ln in enumerate(src_lines, start=1))
    return {
        "ok": True,
        "schema": "anvil-level3-source/v1",
        "file": rel_posix,
        "total_lines": len(src_lines),
        "raw_source": src_text,
        "numbered_source": numbered,
        "symbols": [],
    }


def get_session_status(cockpit_dir: str | Path, summary_only: bool = False) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    sfile = _session_file(cdir)
    session = None
    corrupt_error = None
    if sfile.is_file():
        try:
            loaded = json.loads(sfile.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict) and loaded.get("active"):
                session = loaded
                migrated = False
                disp_name = _cockpit_display_name(cdir)
                if session.get("cockpit_name") != disp_name:
                    session["cockpit_name"] = disp_name
                    migrated = True
                code_map = session.get("code_map") or {}
                buckets = code_map.get("conceptual_buckets") or []
                sw_path = Path((session.get("software") or {}).get("path") or cdir)
                if len(buckets) > 9 and anvil_engine is not None and hasattr(anvil_engine, "_cluster_into_architectural_buckets"):
                    code_map["module_buckets"] = buckets
                    buckets = anvil_engine._cluster_into_architectural_buckets(sw_path, buckets)
                    code_map["conceptual_buckets"] = buckets
                    if hasattr(anvil_engine, "_build_foundry_flow_diagram"):
                        code_map.setdefault("process_map", {})["flow_diagram"] = anvil_engine._build_foundry_flow_diagram(
                            buckets, (code_map.get("process_map") or {}).get("edges") or []
                        )
                    migrated = True
                elif buckets and not (code_map.get("process_map") or {}).get("flow_diagram") and anvil_engine is not None and hasattr(anvil_engine, "_build_foundry_flow_diagram"):
                    code_map.setdefault("process_map", {})["flow_diagram"] = anvil_engine._build_foundry_flow_diagram(
                        buckets, (code_map.get("process_map") or {}).get("edges") or []
                    )
                    migrated = True
                if buckets and (not buckets[0].get("inner_process_map") or not (buckets[0].get("inner_process_map") or {}).get("flow_diagram")):
                    _enrich_buckets_with_previews(sw_path, buckets)
                    migrated = True
                remap = session.get("remap")
                if isinstance(remap, dict) and (not remap.get("best_in_class_map") or not (remap.get("best_in_class_map") or {}).get("flow_diagram")):
                    cmp_path = Path((session.get("compare_software") or {}).get("path") or sw_path)
                    remap["best_in_class_map"] = _build_best_in_class_remap(
                        sw_path,
                        cmp_path,
                        code_map,
                        session.get("orange_split") or {},
                        remap,
                    )
                    migrated = True
                if anvil_engine is not None:
                    if buckets and (not buckets[0].get("level1_summary") or not buckets[0].get("level3_code")):
                        if hasattr(anvil_engine, "_enrich_progressive_levels"):
                            anvil_engine._enrich_progressive_levels(
                                sw_path,
                                buckets,
                                paper_map=session.get("paper_map"),
                                remap=remap,
                            )
                            migrated = True
                    if not session.get("beta_reader_panel") and hasattr(anvil_engine, "run_beta_reader_panel"):
                        session["beta_reader_panel"] = anvil_engine.run_beta_reader_panel(
                            sw_path,
                            code_map=code_map,
                            orange_split=session.get("orange_split"),
                            remap=remap,
                        )
                        migrated = True
                    if not session.get("walkthrough_trace") and hasattr(anvil_engine, "run_code_walkthrough"):
                        session["walkthrough_trace"] = anvil_engine.run_code_walkthrough(
                            sw_path,
                            code_map=code_map,
                            block_id=str(session.get("selected_block_id") or ""),
                        )
                        migrated = True
                    if not (_session_dir(cdir) / "manifest.json").is_file():
                        try:
                            _write_anvil_manifest(cdir, session)
                        except Exception:
                            pass
                if migrated:
                    try:
                        _atomic_write_text(sfile, json.dumps(session, indent=2))
                    except Exception:
                        pass
        except Exception as exc:
            corrupt_error = f"Session file {sfile.name} could not be parsed: {exc}"
    cands = discover_cockpit_candidates(cdir)
    if summary_only:
        cands = {
            "software": (cands.get("software") or [])[:6],
            "papers": (cands.get("papers") or [])[:6],
        }
    out: Dict[str, Any] = {
        "ok": True,
        "cockpit_dir": str(cdir),
        "cockpit_name": _cockpit_display_name(cdir),
        "active": bool(session),
        "summary_only": bool(summary_only),
        "session": (_project_session_summary(session) if (session and summary_only) else session),
        "candidates": cands,
    }
    if corrupt_error:
        out["warning"] = corrupt_error
    return out


get_cockpit_status = get_session_status


def start_cockpit_session(
    cockpit_dir: str | Path,
    mode: str = "code",
    software_spec: str = ".",
    compare_spec: str = "",
    paper_spec: str = "",
    signed_off_drops: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create or replace the active Per-Cockpit Anvil Session for `cockpit_dir` using a single AST scan."""
    if anvil_engine is None:
        raise ValueError("Anvil engine (skills/anvil/scripts/anvil_engine.py) is unavailable on this host.")

    cdir = Path(cockpit_dir).resolve()
    with _get_cockpit_lock(cdir):
        _session_dir(cdir).mkdir(parents=True, exist_ok=True)
        cockpit_name = _cockpit_display_name(cdir)

        # Preserve prior signed_off_drops and back up previous session before overwriting
        sfile = _session_file(cdir)
        prior_signed: List[str] = []
        if sfile.is_file():
            try:
                old_raw = sfile.read_text(encoding="utf-8", errors="replace")
                _atomic_write_text(_session_dir(cdir) / "session.prev.json", old_raw)
                old_obj = json.loads(old_raw)
                if isinstance(old_obj, dict) and isinstance(old_obj.get("signed_off_drops"), list):
                    prior_signed = list(old_obj["signed_off_drops"])
            except Exception:
                pass

        sw_info = resolve_software_target(cdir, software_spec or ".", role="primary")
        sw_path = Path(sw_info["path"])

        cmp_info = resolve_software_target(cdir, compare_spec, role="compare") if compare_spec.strip() else sw_info
        cmp_path = Path(cmp_info["path"])

        # Single full-repo AST scan for sw_path; reuse `code_map` across all downstream steps!
        try:
            code_map = anvil_engine.build_map(sw_path, _include_v2_enrichment=False)
        except TypeError:
            code_map = anvil_engine.build_map(sw_path)
        cmp_map = code_map if sw_path == cmp_path else None
        if cmp_map is None:
            try:
                cmp_map = anvil_engine.build_map(cmp_path, _include_v2_enrichment=False)
            except TypeError:
                cmp_map = anvil_engine.build_map(cmp_path)

        if not (code_map.get("conceptual_buckets") or []):
            extra_buckets = _scan_non_python_buckets(sw_path, start_idx=1)
            for eb in extra_buckets:
                code_map["conceptual_buckets"].append(eb)
                code_map["process_map"]["nodes"].append({
                    "id": eb["id"],
                    "title": eb["title"],
                    "file": eb["file"],
                    "stage": eb["pipeline_stage"],
                    "ai_agent_badge": eb["ai_agent_touchpoints"][0]["badge"] if eb["ai_agent_touchpoints"] else None,
                    "function_count": len(eb["functions"]),
                })

        _enrich_buckets_with_previews(sw_path, code_map.get("conceptual_buckets") or [])

        try:
            orange_split = anvil_engine.extract_orange_split(sw_path, code_map=code_map)
        except TypeError:
            orange_split = anvil_engine.extract_orange_split(sw_path)
        signed_list = list(signed_off_drops) if signed_off_drops is not None else prior_signed
        try:
            remap = anvil_engine.remap_code(
                sw_path,
                cmp_path,
                signed_off_drops=signed_list,
                old_map=code_map,
                new_map=cmp_map,
            )
        except TypeError:
            remap = anvil_engine.remap_code(sw_path, cmp_path, signed_off_drops=signed_list)

        if sw_path == cmp_path and not (remap.get("null_space") or {}).get("items"):
            pith_items = []
            for p in orange_split.get("pith_and_seeds") or []:
                fname = p["name"]
                short = fname.split(".")[-1]
                disp = (
                    "intentional_drop_signed_off"
                    if (fname in signed_list or short in signed_list)
                    else "accidental_omission_blocker"
                )
                pith_items.append({
                    "old_function": fname,
                    "old_file": p.get("file", ""),
                    "summary": p.get("summary", "Truly unreferenced candidate"),
                    "stage": p.get("stage", "compute"),
                    "disposition": disp,
                })
            blockers = [it for it in pith_items if it["disposition"] == "accidental_omission_blocker"]
            remap["null_space"] = {
                "count": len(pith_items),
                "unexplained_blockers": len(blockers),
                "items": pith_items,
            }
            stages_ok = all(
                v.get("status") == "PASS"
                for v in (remap.get("pipeline_validation") or {}).values()
            )
            remap["verdict"] = "PASS" if (not blockers and stages_ok) else "NEEDS_REVIEW"

        remap["best_in_class_map"] = _build_best_in_class_remap(sw_path, cmp_path, code_map, orange_split, remap)

        paper_map = None
        if mode == "paper" or paper_spec.strip():
            paper_info = resolve_paper_source(cdir, paper_spec)
            paper_map = extract_paper_claims_and_align(
                sw_path,
                code_map.get("conceptual_buckets") or [],
                paper_info,
                code_map=code_map,
            )

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        buckets = code_map.get("conceptual_buckets") or []
        if hasattr(anvil_engine, "_enrich_progressive_levels"):
            anvil_engine._enrich_progressive_levels(sw_path, buckets, paper_map=paper_map, remap=remap)
        beta_reader_panel = (
            anvil_engine.run_beta_reader_panel(sw_path, code_map=code_map, orange_split=orange_split, remap=remap)
            if hasattr(anvil_engine, "run_beta_reader_panel")
            else {}
        )
        if hasattr(anvil_engine, "run_code_walkthrough"):
            try:
                walkthrough_trace = anvil_engine.run_code_walkthrough(
                    sw_path,
                    code_map=code_map,
                    block_id=buckets[0]["id"] if buckets else "",
                )
            except TypeError:
                walkthrough_trace = anvil_engine.run_code_walkthrough(
                    sw_path,
                    block_id=buckets[0]["id"] if buckets else "",
                )
        else:
            walkthrough_trace = {}
        first_block = buckets[0]["title"] if buckets else sw_info["label"]
        total_fns = sum(len(b.get("functions") or []) for b in buckets)
        total_mods = len(code_map.get("module_buckets") or buckets)
        seating = _read_model_seating_info()

        paper_sentence = ""
        if isinstance(paper_map, dict):
            sc = paper_map.get("summary_counts") or {}
            sec_n = sc.get("sections", len(paper_map.get("sections") or []))
            alg_n = sc.get("algorithms", len(paper_map.get("algorithms") or []))
            eq_n = sc.get("equations", paper_map.get("claims_mapped", 0))
            paper_sentence = (
                f"Attached paper **{paper_map.get('paper_title')}** (`{sec_n}` sections, "
                f"`{alg_n}` algorithm(s), `{eq_n}` native MathML equations). "
            )

        greeting = (
            f"Mapped `{sw_info['label']}` (`{total_mods}` source files, `{total_fns}` functions) into "
            f"**{len(buckets)} clustered architectural module(s)** "
            f"(`{orange_split.get('counts', {}).get('juice_count', 0)}` Essential Core functions, "
            f"`{orange_split.get('counts', {}).get('peel_count', 0)}` I/O contracts, and "
            f"`{orange_split.get('counts', {}).get('pith_and_seeds_count', 0)}` truly unreferenced `∅ Null Space` candidates). "
            + paper_sentence
            + f"Coding seat: **{seating['coding_short']}**; cross-family review seat: **{seating['review_short']}**. "
            "Ask about any symbol, module, caller/callee edge, security finding, or paper equation/algorithm."
        )

        session: Dict[str, Any] = {
            "schema": "anvil-cockpit-session/v1",
            "active": True,
            "cockpit_dir": str(cdir),
            "cockpit_name": cockpit_name,
            "mode": "paper" if paper_map and mode == "paper" else "code",
            "created_at": now_iso,
            "updated_at": now_iso,
            "software": sw_info,
            "compare_software": cmp_info,
            "signed_off_drops": signed_list,
            "code_map": code_map,
            "orange_split": orange_split,
            "remap": remap,
            "paper_map": paper_map,
            "beta_reader_panel": beta_reader_panel,
            "walkthrough_trace": walkthrough_trace,
            "selected_block_id": buckets[0]["id"] if buckets else "",
            "chat_history": [
                {
                    "role": "anvil",
                    "mode": "paper-map" if paper_map else "map",
                    "target": first_block,
                    "text": greeting,
                    "answer_mode": "static_ast",
                    "at": now_iso,
                }
            ],
        }

        _atomic_write_text(sfile, json.dumps(session, indent=2))
        _write_anvil_manifest(cdir, session)
        _write_anvil_report(cdir, session)
        return get_session_status(cdir)


def _is_placeholder_model_label(label: str) -> bool:
    low = (label or "").strip().lower()
    return not low or any(tok in low for tok in ("-argon", "-fable-", "-sol"))


def _read_model_seating_info() -> Dict[str, str]:
    """Read real configured Anchor model seating from preferences, env, and in-memory CLI capabilities."""
    coding_fam = "gemini"
    review_fam = "claude"
    steward = "aladdin"
    explicit_coding_model = ""
    explicit_review_model = ""

    pref_candidates: List[Path] = []
    try:
        import paths as _paths
        pref_candidates.append(_paths.data_dir() / ".anchor" / "model_prefs.json")
    except Exception:
        pass
    try:
        pref_candidates.append(Path.home() / ".anchor" / "model_prefs.json")
    except Exception:
        pass

    for prefs_path in pref_candidates:
        try:
            if prefs_path.is_file():
                data = json.loads(prefs_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict):
                    coding_fam = str(data.get("coding_family") or data.get("default_cli") or coding_fam).lower()
                    review_fam = str(data.get("review_family") or review_fam).lower()
                    steward = str(data.get("steward_type") or steward).lower()
                    cm = str(data.get("coding_model") or "").strip()
                    rm = str(data.get("review_model") or "").strip()
                    if cm and not _is_placeholder_model_label(cm):
                        explicit_coding_model = cm
                    if rm and not _is_placeholder_model_label(rm):
                        explicit_review_model = rm
                break
        except Exception:
            continue

    frontier_defaults = {
        "gemini": "gemini · latest_supported · high",
        "claude": "claude · latest_supported · max",
        "chatgpt": "chatgpt · latest_supported · xhigh",
        "codex": "codex · latest_supported · xhigh",
        "grok": "grok · latest_supported · high",
    }

    # Consult live in-memory model_policy cache if already populated (zero subprocesses spawned)
    try:
        import model_policy as _mp
        mem = getattr(_mp, "_MEMORY", None)
        if isinstance(mem, dict):
            for entry in mem.values():
                if isinstance(entry, dict) and entry.get("family") and entry.get("model"):
                    fam_k = str(entry["family"]).lower()
                    mdl = str(entry["model"]).strip()
                    eff = str(entry.get("effort") or "high").strip()
                    if not _is_placeholder_model_label(mdl):
                        frontier_defaults[fam_k] = f"{mdl} · {eff}"
    except Exception:
        pass

    for env_key, fam_key in (
        ("GEMINI_MODEL", "gemini"),
        ("CLAUDE_MODEL", "claude"),
        ("TRIO_MODEL", coding_fam),
    ):
        env_val = (os.environ.get(env_key) or "").strip()
        if env_val and not _is_placeholder_model_label(env_val):
            frontier_defaults[fam_key] = env_val if "·" in env_val else f"{env_val} · high"

    cli_transports = {
        "gemini": "via `agy` subscription CLI",
        "claude": "via `claude.exe` subscription CLI",
        "chatgpt": "via `codex` subscription CLI",
        "codex": "via `codex` subscription CLI",
        "grok": "via `grok` subscription CLI",
    }
    coding_short = explicit_coding_model or frontier_defaults.get(coding_fam, f"{coding_fam} · latest_supported")
    review_short = explicit_review_model or frontier_defaults.get(review_fam, f"{review_fam} · latest_supported")
    coding_label = f"{coding_short} ({cli_transports.get(coding_fam, 'via subscription CLI')})"
    cross_ok = coding_fam != review_fam
    review_label = (
        f"{review_short} ({cli_transports.get(review_fam, 'via subscription CLI')}, "
        f"`cross_model: {str(cross_ok).lower()}`)"
    )
    coding_parts = [p.strip() for p in coding_short.split("·")]
    review_parts = [p.strip() for p in review_short.split("·")]
    return {
        "coding_family": coding_fam,
        "review_family": review_fam,
        "steward_type": steward.title(),
        "coding_short": coding_short,
        "review_short": review_short,
        "coding_model_id": coding_parts[0] if coding_parts else coding_fam,
        "coding_effort": coding_parts[-1] if len(coding_parts) > 1 else "high",
        "review_model_id": review_parts[0] if review_parts else review_fam,
        "review_effort": review_parts[-1] if len(review_parts) > 1 else "max",
        "coding_label": coding_label,
        "review_label": review_label,
    }


def _verify_all_buckets_in_place(session: Dict[str, Any], cdir: Path) -> Tuple[int, int]:
    """Check static syntax/bytecode and isolated runtime walkthrough per bucket honestly (`EXECUTED_PASS` vs `STATIC_ONLY`)."""
    buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
    sw_path = Path((session.get("software") or {}).get("path") or cdir)
    base_dir = sw_path.parent if sw_path.is_file() else sw_path
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    newly_probed = 0
    total_executed = 0

    for b in buckets:
        if b.get("validated"):
            total_executed += 1
            continue
        member_rel = list(b.get("member_files") or [])
        if not member_rel:
            single = b.get("primary_file") or b.get("file") or ""
            if single:
                member_rel = [single]
        compiled = 0
        passed = True
        notes: List[str] = []
        for rel_f in member_rel:
            tf = (base_dir / rel_f).resolve()
            if tf.is_file() and not tf.is_symlink() and tf.suffix.lower() == ".py":
                try:
                    src = tf.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=tf.name)
                    compile(tree, filename=tf.name, mode="exec")
                    compiled += 1
                except Exception as exc:
                    passed = False
                    notes.append(f"✗ Syntax error in {tf.name}: {exc}")

        executed_ok = False
        if passed and anvil_engine is not None and hasattr(anvil_engine, "run_code_walkthrough"):
            try:
                wt = anvil_engine.run_code_walkthrough(
                    sw_path,
                    code_map=session.get("code_map"),
                    block_id=str(b.get("id") or ""),
                )
                verdict = str(wt.get("overall_verdict") or "")
                if verdict == "EXECUTED_PASS" or bool(wt.get("accurate_execution")):
                    executed_ok = True
                    notes.append(f"✓ Isolated child-subprocess runtime walkthrough: EXECUTED_PASS.")
                elif verdict in ("DIVERGENCE", "MISMATCH"):
                    passed = False
                    notes.append(f"✗ Isolated runtime walkthrough reported {verdict}.")
            except Exception:
                pass

        if not passed:
            b["static_syntax_ok"] = False
            b["validated"] = False
            b["empirical_validation"] = {
                "ran": True,
                "status": "DIVERGENCE",
                "checked_at": now_iso,
                "stdout": "\n".join(notes) or "✗ Static or runtime check failed.",
            }
            newly_probed += 1
        elif executed_ok:
            if compiled > 0:
                notes.insert(0, f"✓ AST parse & bytecode compile passed across {compiled} Python module(s).")
            b["static_syntax_ok"] = True
            b["validated"] = True
            b["validated_description"] = b.get("validated_description") or b.get("summary")
            b["empirical_validation"] = {
                "ran": True,
                "status": "EXECUTED_PASS",
                "checked_at": now_iso,
                "stdout": "\n".join(notes),
            }
            newly_probed += 1
            total_executed += 1
        else:
            if compiled > 0:
                notes.append(
                    f"✓ Static AST parse & bytecode compile passed across {compiled} Python module(s) (no runtime test executed yet)."
                )
            else:
                notes.append("ℹ Static module scan complete; no runtime test executed yet.")
            b["static_syntax_ok"] = passed
            b["validated"] = False
            b["empirical_validation"] = {
                "ran": False,
                "status": "STATIC_ONLY",
                "checked_at": now_iso,
                "stdout": "\n".join(notes),
            }
            newly_probed += 1
    return newly_probed, total_executed


def probe_block_in_session(
    cockpit_dir: str | Path,
    block_id: str,
    lock_description: str = "",
    test_cmd: str = "",
) -> Dict[str, Any]:
    """Run static AST/Ruff checks AND isolated child-subprocess runtime walkthrough on a block honestly."""
    cdir = Path(cockpit_dir).resolve()
    with _get_cockpit_lock(cdir):
        status = get_session_status(cdir)
        session = status.get("session")
        if not session:
            raise ValueError("No active Anvil session in this cockpit.")

        bid_clean = (block_id or "").strip()
        if not bid_clean:
            raise ValueError("block_id is required.")

        buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
        block = next(
            (
                b for b in buckets
                if b.get("id") == bid_clean
                or b.get("file") == bid_clean
                or b.get("primary_file") == bid_clean
                or bid_clean in (b.get("member_files") or [])
            ),
            None,
        )
        if not block:
            raise ValueError(f"Block '{bid_clean}' not found in active session.")

        sw_path = Path((session.get("software") or {}).get("path") or cdir)
        base_dir = sw_path.parent if sw_path.is_file() else sw_path
        member_rel_files = list(block.get("member_files") or [])
        if not member_rel_files:
            rel_single = block.get("primary_file") or block.get("file") or ""
            if rel_single:
                member_rel_files = [rel_single]

        py_targets: List[Path] = []
        non_py_targets: List[Path] = []
        for rel_f in member_rel_files:
            tf = (base_dir / rel_f).resolve()
            if tf.is_file() and not tf.is_symlink():
                if tf.suffix.lower() == ".py":
                    py_targets.append(tf)
                else:
                    non_py_targets.append(tf)

        probe_notes: List[str] = []
        static_ok = True
        if py_targets:
            compiled_count = 0
            for tf in py_targets:
                try:
                    src = tf.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=tf.name)
                    compile(tree, filename=tf.name, mode="exec")
                    compiled_count += 1
                except Exception as exc:
                    static_ok = False
                    probe_notes.append(f"✗ Syntax/compile error in {tf.name}: {exc}")
            if static_ok:
                probe_notes.append(
                    f"✓ Static AST parse & bytecode compile passed across {compiled_count} Python module(s) "
                    f"in '{block.get('title')}' ({len(block.get('functions') or [])} functions)."
                )
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "ruff", "check", "--select", "E9,F63,F7,F82"] + [str(p) for p in py_targets[:25]],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                )
                combined = (r.stdout + r.stderr).strip()
                if r.returncode == 0:
                    probe_notes.append("✓ Ruff static undefined-name & syntax gate: PASS (0 issues).")
                elif "No module named ruff" in combined:
                    probe_notes.append("ℹ Ruff not installed in Python environment; AST & bytecode compile passed.")
                else:
                    static_ok = False
                    probe_notes.append(f"✗ Ruff static check findings:\n{combined[:400]}")
            except Exception:
                pass
        elif non_py_targets:
            probe_notes.append(
                f"ℹ Polyglot module {block.get('file')} ({len(non_py_targets)} file(s)) — checking isolated runtime walkthrough."
            )
        else:
            static_ok = False
            probe_notes.append(f"✗ Source file {block.get('file')} not found.")

        ran_runtime = False
        runtime_ok = False
        explicit_cmd = (test_cmd or "").strip()
        if static_ok and explicit_cmd and anvil_engine is not None and hasattr(anvil_engine, "_safe_subprocess_run"):
            ran_runtime = True
            proc = anvil_engine._safe_subprocess_run(explicit_cmd, cwd=base_dir, timeout=30.0)
            if proc.returncode == 0:
                runtime_ok = True
                probe_notes.append(f"✓ Isolated child-subprocess test command exited 0 (EXECUTED_PASS).\n{(proc.stdout or '').strip()[:300]}".strip())
            else:
                runtime_ok = False
                static_ok = False
                err_out = (proc.stderr or proc.stdout or "").strip()[:300]
                probe_notes.append(f"✗ Isolated child-subprocess test command failed (exit={proc.returncode}): {err_out}".strip())
        elif static_ok and anvil_engine is not None and hasattr(anvil_engine, "run_code_walkthrough"):
            try:
                wt = anvil_engine.run_code_walkthrough(
                    sw_path,
                    code_map=session.get("code_map"),
                    block_id=str(block.get("id") or ""),
                )
                verdict = str(wt.get("overall_verdict") or "")
                if verdict == "EXECUTED_PASS" or bool(wt.get("accurate_execution")):
                    ran_runtime = True
                    runtime_ok = True
                    probe_notes.append("✓ Isolated child-subprocess walkthrough exited 0 (EXECUTED_PASS).")
                elif verdict in ("DIVERGENCE", "MISMATCH"):
                    ran_runtime = True
                    runtime_ok = False
                    static_ok = False
                    probe_notes.append(f"✗ Isolated child-subprocess walkthrough reported {verdict}.")
                else:
                    probe_notes.append("ℹ No runnable entrypoint/test executed for this module (STATIC_ONLY).")
            except Exception as exc:
                probe_notes.append(f"ℹ Runtime walkthrough skipped: {exc}")

        if not static_ok:
            emp_status = "DIVERGENCE"
            block["static_syntax_ok"] = False
            block["validated"] = False
        elif ran_runtime and runtime_ok:
            emp_status = "EXECUTED_PASS"
            block["static_syntax_ok"] = True
            block["validated"] = True
        else:
            emp_status = "STATIC_ONLY"
            block["static_syntax_ok"] = True
            block["validated"] = False

        empirical = {
            "ran": bool(ran_runtime),
            "status": emp_status,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stdout": "\n".join(probe_notes),
        }
        block["empirical_validation"] = empirical
        clean_desc = lock_description.strip()
        if clean_desc and not clean_desc.startswith("Empirical AST &"):
            block["validated_description"] = clean_desc
        elif block["validated"] and not block.get("validated_description"):
            block["validated_description"] = block.get("summary")

        # Update any paper alignments pointing to this block
        paper_map = session.get("paper_map")
        if isinstance(paper_map, dict):
            for al in paper_map.get("alignments") or []:
                if al.get("bucket_id") == block["id"] and al.get("mapped_function"):
                    al["empirical_status"] = "EXECUTED_PASS" if block["validated"] else "STATIC_ALIGNED"

        session["selected_block_id"] = block["id"]
        session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return {
            **get_session_status(cdir),
            "block": block,
            "empirical": empirical,
            "inspection": {
                "validated": bool(block.get("validated")),
                "empirical_validation": empirical,
            },
        }


def sign_off_null_space_in_session(cockpit_dir: str | Path, function_name: str) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    with _get_cockpit_lock(cdir):
        status = get_session_status(cdir)
        session = status.get("session")
        if not session:
            raise ValueError("No active Anvil session in this cockpit.")

        fn = (function_name or "").strip()
        if not fn:
            raise ValueError("function_name is required.")
        signed = list(session.get("signed_off_drops") or [])
        if fn not in signed:
            signed.append(fn)
        session["signed_off_drops"] = signed

        ns = (session.get("remap") or {}).get("null_space") or {}
        for item in ns.get("items") or []:
            old_fn = item.get("old_function") or ""
            if old_fn == fn or old_fn.split(".")[-1] == fn:
                item["disposition"] = "intentional_drop_signed_off"
        blockers = [it for it in (ns.get("items") or []) if it.get("disposition") == "accidental_omission_blocker"]
        ns["unexplained_blockers"] = len(blockers)
        if session.get("remap"):
            session["remap"]["verdict"] = "PASS" if not blockers else "NEEDS_REVIEW"

        session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return get_session_status(cdir)


def attach_paper_to_session(cockpit_dir: str | Path, paper_spec: str) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    status = get_session_status(cdir)
    session = status.get("session")
    if not session:
        return start_cockpit_session(cdir, mode="paper", software_spec=".", paper_spec=paper_spec)

    with _get_cockpit_lock(cdir):
        sw_path = Path((session.get("software") or {}).get("path") or cdir)
        code_map = session.get("code_map") or {}
        buckets = code_map.get("conceptual_buckets") or []
        paper_info = resolve_paper_source(cdir, paper_spec)
        paper_map = extract_paper_claims_and_align(sw_path, buckets, paper_info, code_map=code_map)
        session["paper_map"] = paper_map
        session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return {**get_session_status(cdir), "paper_map": paper_map}


def _infer_setup_targets_from_chat(
    cdir: Path,
    question: str,
    candidates: Dict[str, List[Dict[str, str]]],
) -> Dict[str, Any]:
    """Inspect a natural-language Steward/Anvil dialogue message to locate local papers, URLs, or code targets."""
    q = (question or "").strip()
    q_low = q.lower()
    sw_cands = candidates.get("software") or [{"path": ".", "label": cdir.name}]
    paper_cands = candidates.get("papers") or []

    # 1. Check for explicit arXiv ID or URL in message
    matched_paper = ""
    arxiv_m = re.search(r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf|e-print)/)(\d{4}\.\d{4,5}(?:v\d+)?)", q, re.IGNORECASE)
    url_m = re.search(r"(https?://[^\s)\"'>]+)", q, re.IGNORECASE)
    if arxiv_m:
        matched_paper = f"arXiv:{arxiv_m.group(1)}"
    elif url_m and ("arxiv" in url_m.group(1).lower() or url_m.group(1).lower().endswith((".pdf", ".md", ".tex", ".html", ".tgz", ".tar.gz"))):
        matched_paper = url_m.group(1)

    # 2. Check for local paper filename or title match in message
    if not matched_paper and paper_cands:
        for pc in paper_cands:
            p_path = (pc.get("path") or "").strip()
            p_name = Path(p_path).name.lower() if p_path else ""
            p_stem = Path(p_path).stem.lower() if p_path else ""
            p_label = (pc.get("label") or "").lower()
            if (p_path and p_path.lower() in q_low) or (p_name and p_name in q_low) or (len(p_stem) >= 4 and p_stem in q_low):
                matched_paper = p_path
                break
            words = [w for w in re.split(r"[^a-z0-9]+", p_label) if len(w) >= 4 and w not in ("paper", "local", "file", "draft", "notes")]
            if words and any(w in q_low for w in words):
                matched_paper = p_path
                break
        if not matched_paper and any(kw in q_low for kw in ("paper", "loaded locally", "local file", "look for", "pull", "slides", "manuscript", "equation")):
            matched_paper = paper_cands[0].get("path") or ""

    # 3. Check for software path match in message
    matched_sw = sw_cands[0].get("path") or "."
    for sc in sw_cands:
        s_path = (sc.get("path") or "").strip()
        if not s_path or s_path == ".":
            continue
        s_name = Path(s_path).name.lower()
        if s_path.lower() in q_low or (s_name and s_name in q_low):
            matched_sw = s_path
            break

    wants_launch = any(
        kw in q_low
        for kw in (
            "set up", "setup", "launch", "start", "initialize", "init", "analyze", "map",
            "look for", "pull", "load", "loaded locally", "open", "run anvil", "paper",
            "essential core", "scaffolding", "codebase", "software", "solver", ".py", ".md", ".pdf", ".tex"
        )
    )
    return {
        "wants_launch": wants_launch,
        "software_spec": matched_sw,
        "paper_spec": matched_paper,
    }


def _split_runner_argv(cmd_str: str) -> List[str]:
    parts = shlex.split(cmd_str, posix=(os.name != "nt"))
    if os.name == "nt":
        cleaned: List[str] = []
        for tok in parts:
            if len(tok) >= 2 and ((tok[0] == '"' and tok[-1] == '"') or (tok[0] == "'" and tok[-1] == "'")):
                tok = tok[1:-1]
            cleaned.append(tok)
        return cleaned
    return parts


def _try_live_cli_chat(question: str, grounded_facts: str) -> Optional[str]:
    """Optional live CLI synthesis when `ANCHOR_ANVIL_LIVE_CHAT=1` and `ANCHOR_RUNNER_CMD` is configured."""
    if os.environ.get("ANCHOR_ANVIL_LIVE_CHAT") != "1":
        return None
    runner_cmd = (os.environ.get("ANCHOR_RUNNER_CMD") or "").strip()
    if not runner_cmd:
        return None
    argv = _split_runner_argv(runner_cmd)
    if not argv:
        return None
    prompt = (
        "You are Anvil inside an Anchor AI Cockpit. Answer the user's question concisely and accurately "
        "using ONLY the verified AST, Null Space, Aegis, and Paper-to-Code facts below. Never invent file names, "
        "test counts, or model IDs.\n\n"
        f"VERIFIED SESSION FACTS:\n{grounded_facts}\n\nUSER QUESTION:\n{question}\n"
    )
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            shell=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return proc.stdout.strip()[:2400]
    except Exception:
        return None
    return None


def _synthesize_grounded_anvil_answer(
    session: Dict[str, Any],
    question: str,
    mode: str,
    target: str,
    seating: Dict[str, str],
) -> Tuple[str, str]:
    """Answer Anvil dialogue questions from real AST symbols, callers/callees, Null Space, Aegis, and Paper-Map facts."""
    q = (question or "").strip()
    q_low = q.lower()
    code_map = session.get("code_map") or {}
    buckets = code_map.get("conceptual_buckets") or []
    mod_buckets = code_map.get("module_buckets") or buckets
    orange = session.get("orange_split") or {}
    counts = orange.get("counts") or {}
    remap = session.get("remap") or {}
    ns_obj = remap.get("null_space") or {}
    ns_items = ns_obj.get("items") or []
    unaccounted = [it for it in ns_items if it.get("disposition") != "intentional_drop_signed_off"]
    paper_map = session.get("paper_map")
    panel = session.get("beta_reader_panel") or {}
    sw_label = (session.get("software") or {}).get("label") or "."

    executed_cnt = sum(1 for b in buckets if b.get("validated"))
    static_cnt = sum(1 for b in buckets if b.get("static_syntax_ok") and not b.get("validated"))
    total_fns = sum(len(b.get("functions") or []) for b in buckets)

    # Index all functions and callers across the repository
    all_fns: List[Dict[str, Any]] = []
    callers_of: Dict[str, List[str]] = {}
    for b in mod_buckets:
        b_file = b.get("file") or ""
        for fn in b.get("functions") or []:
            rec = {**fn, "file": fn.get("file") or b_file, "bucket_title": b.get("title") or b_file}
            all_fns.append(rec)
            caller_label = f"{rec['file']}:{fn['name']}"
            for callee in (fn.get("all_calls") or fn.get("calls") or []):
                short_c = str(callee).split(".")[-1]
                callers_of.setdefault(short_c, []).append(caller_label)

    # 1. Model / Seating / Session Status questions
    if any(kw in q_low for kw in ("who is", "what model", "which model", "skill and model", "coding seat", "review seat")):
        seat5 = next((s for s in (panel.get("seats") or []) if s.get("seat_id") == "security_boundary_auditor"), None)
        sec_note = (
            f"Seat 5 (`Defensive & Security Boundaries`) status is `{seat5.get('status') or seat5.get('verdict')}` (`{seat5.get('score')}/100`)."
            if seat5 else ""
        )
        base_reply = (
            f"Anvil is configured with **{seating['coding_short']}** in the coding seat (`{seating['coding_family']}` CLI) "
            f"and **{seating['review_short']}** in the cross-family review seat (`{seating['review_family']}` CLI). "
            f"For `{sw_label}`, AST indexing covers **{len(buckets)} clustered module(s)** (`{len(mod_buckets)}` files, `{total_fns}` functions: "
            f"`{counts.get('juice_count', 0)}` Essential Core, `{counts.get('peel_count', 0)}` I/O Peel, `{len(unaccounted)}` open `∅ Null Space` item(s); "
            f"`{executed_cnt}` module(s) `EXECUTED_PASS`, `{static_cnt}` `STATIC_ONLY`). {sec_note}"
        ).strip()
        live = _try_live_cli_chat(q, base_reply)
        return (live, "live_model") if live else (base_reply, "static_ast")

    # 2. Security / Aegis / Seat 5 questions
    if any(kw in q_low for kw in ("security", "aegis", "vulnerability", "cwe", "injection", "traversal", "seat 5", "beta reader")):
        seats = panel.get("seats") or []
        seat5 = next((s for s in seats if s.get("seat_id") == "security_boundary_auditor"), seats[-1] if seats else {})
        findings = [f for f in (seat5.get("aegis_findings") or []) if isinstance(f, dict)]
        if findings:
            f_preview = "; ".join(
                f"`{f.get('rule_id', 'AEG')}` in `{f.get('file', '?')}:L{f.get('line') or f.get('lineno', 1)}` ({str(f.get('title') or f.get('message') or '')[:80]})"
                for f in findings[:4]
            )
            base_reply = (
                f"Seat 5 (**Defensive & Security Boundaries · Aegis**) scored `{seat5.get('score', 0)}/100` "
                f"(`{seat5.get('status') or seat5.get('verdict', 'ACTION_REQUIRED')}`) with `{len(findings)}` finding(s): {f_preview}."
            )
        else:
            base_reply = (
                f"Seat 5 (**Defensive & Security Boundaries · Aegis**) scored `{seat5.get('score', 100)}/100` "
                f"(`{seat5.get('status') or seat5.get('verdict', 'PASS')}`) with `0` CWE taint/sink findings across `{sw_label}`. "
                f"Overall 5-Seat Beta-Reader score: `{panel.get('overall_score', 0)}/100`."
            )
        live = _try_live_cli_chat(q, base_reply)
        return (live, "live_model") if live else (base_reply, "static_ast")

    # 3. Null Space / Dead-Code / Unreferenced questions
    if any(kw in q_low for kw in ("null space", "dead code", "unreferenced", "unused", "pith")):
        test_only = orange.get("referenced_by_tests_only") or []
        if unaccounted:
            preview = ", ".join(
                f"`{it.get('old_function')}()` (`{it.get('old_file')}`)"
                for it in unaccounted[:6]
            )
            base_reply = (
                f"Full-repo AST + `tests/` reference indexing found **{len(unaccounted)} truly unreferenced function(s)** in `∅ Null Space`: "
                f"{preview}" + (f" (+{len(unaccounted) - 6} more)." if len(unaccounted) > 6 else ".")
                + (f" `{len(test_only)}` additional helper(s) are referenced by `tests/` only and excluded from dead-code flags." if test_only else "")
            )
        else:
            base_reply = (
                f"`∅ Null Space` has **0 truly unreferenced functions** remaining across `{sw_label}` "
                f"(Remap verdict: `{remap.get('verdict', 'PASS')}`"
                + (f"; `{len(test_only)}` function(s) referenced by `tests/` only" if test_only else "")
                + ")."
            )
        live = _try_live_cli_chat(q, base_reply)
        return (live, "live_model") if live else (base_reply, "static_ast")

    # 4. Paper / Equation / Algorithm / Section questions
    q_toks = {t for t in re.split(r"[^a-z0-9_]+", q_low) if len(t) >= 3}
    if isinstance(paper_map, dict) and (
        mode in ("paper", "paper-map")
        or any(kw in q_low for kw in ("equation", "algorithm", "section", "paper", "latex", "mathml", "elbo", "jacobian"))
    ):
        eqs = paper_map.get("equations") or []
        algs = paper_map.get("algorithms") or []
        secs = paper_map.get("sections") or []
        if "algorithm" in q_low and algs:
            alg = algs[0]
            steps = alg.get("steps") or []
            base_reply = (
                f"In **{paper_map.get('paper_title')}**, **{alg.get('title') or alg.get('id')}** (`{alg.get('source_file')}:L{alg.get('line_start', 1)}`, "
                f"`{len(steps)}` steps, status `{alg.get('status')}`) aligns primarily with `{alg.get('primary_function') or 'unmapped'}` "
                f"in module `{alg.get('matched_module') or 'unmapped'}`."
            )
            live = _try_live_cli_chat(q, base_reply)
            return (live, "live_model") if live else (base_reply, "static_ast")
        if eqs:
            best_eq = next((e for e in eqs if e.get("id") == target or e.get("label") == target), None)
            if best_eq is None:
                best_eq = max(
                    eqs,
                    key=lambda e: len(q_toks & {t for t in re.split(r"[^a-z0-9_]+", f"{e.get('id','')} {e.get('label','')} {e.get('raw_latex','')}".lower()) if len(t) >= 3}),
                )
            mfs = best_eq.get("matched_functions") or []
            top_fn = mfs[0] if mfs else {}
            base_reply = (
                f"In **{paper_map.get('paper_title')}** (`{len(secs)}` sections, `{len(algs)}` algorithm(s), `{len(eqs)}` equations), "
                f"equation `{best_eq.get('id')}` (`{best_eq.get('source_file')}:L{best_eq.get('line_start', 1)}`, status `{best_eq.get('status')}`) "
                + (
                    f"aligns with `{top_fn.get('qualname')}` (`{top_fn.get('file')}:L{top_fn.get('line_start', 1)}–L{top_fn.get('line_end', 1)}`, "
                    f"matched identifiers: `{', '.join((top_fn.get('matched_identifiers') or [])[:5]) or 'structural ops'}`)."
                    if top_fn else "has no static implementation match yet (`PAPER_ONLY_UNIMPLEMENTED`)."
                )
            )
            live = _try_live_cli_chat(q, base_reply)
            return (live, "live_model") if live else (base_reply, "static_ast")
        if paper_map.get("alignments"):
            al = next((a for a in paper_map["alignments"] if a.get("claim_id") == target), paper_map["alignments"][0])
            base_reply = (
                f"In **{paper_map.get('paper_title')}**, `{al.get('claim_id')}` (**{al.get('title')}**) maps to "
                f"`{al.get('mapped_function') or 'unmapped'}` (`{al.get('mapped_file') or ''}:{al.get('lineno') or ''}`, "
                f"status `{al.get('empirical_status')}`)."
            )
            live = _try_live_cli_chat(q, base_reply)
            return (live, "live_model") if live else (base_reply, "static_ast")

    # 5. Direct Symbol / Function lookup in AST
    best_fn: Optional[Dict[str, Any]] = None
    best_fn_score = 0
    for fn in all_fns:
        fn_name = str(fn.get("name") or "")
        short_fn = fn_name.split(".")[-1].lower()
        score = 0
        if short_fn and short_fn in q_low:
            score += 10 + len(short_fn)
        else:
            fn_toks = {t for t in re.split(r"[^a-z0-9_]+", f"{fn_name} {fn.get('summary','')} {fn.get('file','')}".lower()) if len(t) >= 3}
            score += len(q_toks & fn_toks) * 2
        if target and (fn.get("file") == target or fn_name == target):
            score += 4
        if score > best_fn_score:
            best_fn_score = score
            best_fn = fn

    if best_fn is not None and best_fn_score >= 4:
        short_nm = str(best_fn["name"]).split(".")[-1]
        callees = (best_fn.get("all_calls") or best_fn.get("calls") or [])[:6]
        callers = sorted(set(callers_of.get(short_nm, [])))[:5]
        base_reply = (
            f"`{best_fn['name']}({', '.join(best_fn.get('args') or [])})` in `{best_fn['file']}:L{best_fn.get('lineno', 1)}–L{best_fn.get('end_lineno', best_fn.get('lineno', 1))}` "
            f"(module **{best_fn.get('bucket_title')}**, stage `{str(best_fn.get('stage', 'compute')).upper()}`) — {best_fn.get('summary') or 'AST symbol'}. "
            f"Calls: {', '.join(f'`{c}`' for c in callees) if callees else 'none'}; "
            f"referenced by: {', '.join(f'`{c}`' for c in callers) if callers else 'top-level/external entrypoint'}."
        )
        live = _try_live_cli_chat(q, base_reply)
        return (live, "live_model") if live else (base_reply, "static_ast")

    # 6. Target Module / Bucket summary grounded in AST
    matched = next(
        (
            b for b in buckets
            if b.get("id") == target or b.get("file") == target or b.get("title") == target
            or (b.get("title") and b["title"].lower() in q_low)
        ),
        buckets[0] if buckets else None,
    )
    if matched:
        fns = ", ".join(f"`{fn['name']}()`" for fn in (matched.get("functions") or [])[:5])
        stage = (matched.get("pipeline_stage") or "compute").upper()
        member_files = matched.get("member_files") or ([matched.get("file")] if matched.get("file") else [])
        mods_preview = ", ".join(f"`{m}`" for m in member_files[:6])
        if len(member_files) > 6:
            mods_preview += f" (+{len(member_files) - 6} more)"
        v_state = (
            "EXECUTED_PASS (runtime verified)"
            if matched.get("validated")
            else ("STATIC_ONLY (AST parsed, not yet executed)" if matched.get("static_syntax_ok") else "STATIC_ONLY")
        )
        base_reply = (
            f"Module **{matched.get('title')}** (`{stage}`, status `{v_state}`) spans `{len(member_files)}` file(s) ({mods_preview}) "
            f"with `{len(matched.get('functions') or [])}` AST function(s) ({fns or 'none'}). "
            f"{matched.get('validated_description') or matched.get('summary') or ''}"
        ).strip()
        live = _try_live_cli_chat(q, base_reply)
        return (live, "live_model") if live else (base_reply, "static_ast")

    base_reply = (
        f"`{sw_label}` is indexed across `{len(buckets)}` architectural module(s) (`{total_fns}` functions; "
        f"`{executed_cnt}` `EXECUTED_PASS`, `{len(unaccounted)}` `∅ Null Space` items). Ask about any file, function, security check, or paper equation."
    )
    live = _try_live_cli_chat(q, base_reply)
    return (live, "live_model") if live else (base_reply, "static_ast")


def chat_in_session(
    cockpit_dir: str | Path,
    question: str,
    mode: str = "map",
    target: str = "",
) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    q = (question or "").strip()
    if not q:
        raise ValueError("Question cannot be empty.")

    status = get_session_status(cdir)
    session = status.get("session")
    candidates = status.get("candidates") or discover_cockpit_candidates(cdir)

    # If no session is active yet, allow natural-language setup & discovery via Steward/Anvil dialogue
    if not session:
        inferred = _infer_setup_targets_from_chat(cdir, q, candidates)
        if inferred["wants_launch"] or inferred["paper_spec"] or inferred["software_spec"] != ".":
            launch_mode = "paper" if inferred["paper_spec"] else ("paper" if mode in ("paper", "paper-map") and inferred["paper_spec"] else "code")
            started = start_cockpit_session(
                cdir,
                mode=launch_mode,
                software_spec=inferred["software_spec"],
                paper_spec=inferred["paper_spec"],
            )
            with _get_cockpit_lock(cdir):
                session = (started.get("session") or {})
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                history = list(session.get("chat_history") or [])
                history.insert(0, {"role": "user", "mode": mode, "target": target or "setup", "text": q, "at": now_iso})
                sw_label = (session.get("software") or {}).get("label") or inferred["software_spec"]
                paper_map = session.get("paper_map")
                if paper_map:
                    sc = paper_map.get("summary_counts") or {}
                    reply = (
                        f"[Steward · Anvil Setup] Loaded paper **{paper_map.get('paper_title')}** (`{inferred['paper_spec']}`) "
                        f"and mapped it against `{sw_label}` "
                        f"(`{sc.get('sections', len(paper_map.get('sections') or []))}` sections, "
                        f"`{sc.get('algorithms', len(paper_map.get('algorithms') or []))}` algorithm(s), "
                        f"`{sc.get('equations', paper_map.get('claims_mapped', 0))}` native MathML equations)."
                    )
                else:
                    buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
                    reply = (
                        f"[Steward · Anvil Setup] Initialized Anvil Software Analysis session for `{sw_label}` "
                        f"(`{len(buckets)}` clustered architectural module(s) mapped across Essential Core, I/O Peel, and `∅ Null Space`)."
                    )
                history.append({
                    "role": "anvil",
                    "mode": mode,
                    "target": target or "setup",
                    "text": reply,
                    "answer_mode": "static_ast",
                    "at": now_iso,
                })
                session["chat_history"] = history[-40:]
                session["updated_at"] = now_iso
                _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
                return {**get_session_status(cdir), "reply": reply, "answer_mode": "static_ast"}
        else:
            sw_list = ", ".join(f"`{c['path']}`" for c in (candidates.get("software") or [])[:5]) or "`.`"
            pp_list = ", ".join(f"`{c['path']}`" for c in (candidates.get("papers") or [])[:5]) or "none detected yet"
            reply = (
                f"[Steward · Anvil Setup] Ready to configure Anvil for **{status.get('cockpit_name', cdir.name)}**. "
                f"Local software detected: {sw_list}. Local papers/docs detected: {pp_list}. "
                f"Tell me which paper or codebase to load (e.g. \"Set up Anvil with local paper and map to code\" or \"Pull arXiv:1706.03762\"), and I will launch the session immediately."
            )
            return {**status, "reply": reply, "answer_mode": "static_ast"}

    with _get_cockpit_lock(cdir):
        status = get_session_status(cdir)
        session = status.get("session")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        history = list(session.get("chat_history") or [])
        history.append({"role": "user", "mode": mode, "target": target, "text": q, "at": now_iso})

        inferred = _infer_setup_targets_from_chat(cdir, q, candidates)
        q_low = q.lower()
        if inferred["paper_spec"] and any(kw in q_low for kw in ("attach", "pull", "look for", "load", "loaded locally", "switch paper", "map paper")):
            sw_path = Path((session.get("software") or {}).get("path") or cdir)
            code_map = session.get("code_map") or {}
            buckets = code_map.get("conceptual_buckets") or []
            paper_info = resolve_paper_source(cdir, inferred["paper_spec"])
            paper_map = extract_paper_claims_and_align(sw_path, buckets, paper_info, code_map=code_map)
            session["paper_map"] = paper_map

        buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
        remap = session.get("remap") or {}
        ns_obj = remap.get("null_space") or {}
        ns_items = ns_obj.get("items") or []
        unaccounted = [it for it in ns_items if it.get("disposition") != "intentional_drop_signed_off"]
        seating = _read_model_seating_info()

        asks_verify = any(
            kw in q_low
            for kw in (
                "verfied", "verified", "verify", "probe all", "lock all", "run probe", "run checks",
            )
        )
        asks_sign_off = any(
            kw in q_low
            for kw in ("sign off", "approve drop", "approve null space", "clear null space")
        )

        answer_mode = "static_ast"
        if asks_verify:
            newly_probed, executed_total = _verify_all_buckets_in_place(session, cdir)
            static_ok_total = sum(1 for b in buckets if b.get("static_syntax_ok"))
            ns_tail = (
                f"`{len(unaccounted)}` truly unreferenced function(s) remain in `∅ Null Space`."
                if unaccounted
                else "`∅ Null Space` has `0` unexplained blockers."
            )
            reply = (
                f"Probed `{len(buckets)}` clustered architectural module(s) (`{newly_probed}` updated): "
                f"`{executed_total}/{len(buckets)}` reached `EXECUTED_PASS` via isolated child-subprocess walkthrough, "
                f"and `{static_ok_total}/{len(buckets)}` passed static AST/bytecode checks (`STATIC_ONLY` where no runtime test ran). {ns_tail}"
            )
        elif asks_sign_off:
            if unaccounted:
                signed_list = list(session.get("signed_off_drops") or [])
                for it in ns_items:
                    fn_name = it.get("old_function") or ""
                    if fn_name and fn_name not in signed_list:
                        signed_list.append(fn_name)
                    it["disposition"] = "intentional_drop_signed_off"
                session["signed_off_drops"] = signed_list
                ns_obj["unexplained_blockers"] = 0
                if session.get("remap"):
                    session["remap"]["verdict"] = "PASS"
            reply = (
                f"Signed off `{len(ns_items)}` `∅ Null Space` candidate(s); Old-to-New Remap verdict is now **`{remap.get('verdict', 'PASS')}`** with `0` unexplained blockers."
            )
        else:
            reply, answer_mode = _synthesize_grounded_anvil_answer(session, q, mode, target, seating)

        history.append({
            "role": "anvil",
            "mode": mode,
            "target": target,
            "text": reply,
            "answer_mode": answer_mode,
            "at": now_iso,
        })
        session["chat_history"] = history[-40:]
        session["updated_at"] = now_iso
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return {**get_session_status(cdir), "reply": reply, "answer_mode": answer_mode}


def apply_conversational_anvil_side_effects(cockpit_dir: str | Path, question: str) -> str:
    """When a user speaks in the real AI Cockpit dialogue while an Anvil session is active,
    apply any explicitly requested Anvil probe / Null Space sign-off in place and return a
    compact 1-line Anvil context note for the Steward Engine."""
    cdir = Path(cockpit_dir).resolve()
    sfile = _session_file(cdir)
    if not sfile.is_file():
        return ""
    q_low = (question or "").strip().lower()
    with _get_cockpit_lock(cdir):
        try:
            session = json.loads(sfile.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return ""
        if not isinstance(session, dict):
            return ""
        buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
        remap = session.get("remap") or {}
        ns_obj = remap.get("null_space") or {}
        ns_items = ns_obj.get("items") or []
        unaccounted = [it for it in ns_items if it.get("disposition") != "intentional_drop_signed_off"]
        changed = False

        if any(kw in q_low for kw in ("verify", "verified", "probe all", "lock all")):
            newly, _ = _verify_all_buckets_in_place(session, cdir)
            if newly > 0:
                changed = True
        if any(kw in q_low for kw in ("sign off", "approve drop", "approve null space", "clear null space")) and unaccounted:
            signed_list = list(session.get("signed_off_drops") or [])
            for it in ns_items:
                fn_name = it.get("old_function") or ""
                if fn_name and fn_name not in signed_list:
                    signed_list.append(fn_name)
                it["disposition"] = "intentional_drop_signed_off"
            session["signed_off_drops"] = signed_list
            ns_obj["unexplained_blockers"] = 0
            if session.get("remap"):
                session["remap"]["verdict"] = "PASS"
            unaccounted = []
            changed = True

        if changed:
            session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _atomic_write_text(sfile, json.dumps(session, indent=2))
            _write_anvil_report(cdir, session)

        executed_total = sum(1 for b in buckets if b.get("validated"))
        seating = _read_model_seating_info()
        return (
            f"\n(anvil workbench state: {executed_total}/{len(buckets)} architectural modules EXECUTED_PASS; "
            f"coding seat={seating['coding_short']}, review seat={seating['review_short']}; "
            f"Old-to-New map verdict={remap.get('verdict', 'PASS')}, unaccounted Null Space items={len(unaccounted)}. "
            f"Answer John's question naturally and conversationally in 2-4 plain sentences — never dump a standardized template.)"
        )



def walkthrough_in_session(cockpit_dir: str | Path, block_id: str = "") -> Dict[str, Any]:
    """Run a live step-by-step polyglot code walkthrough on a block or entire session."""
    if anvil_engine is None or not hasattr(anvil_engine, "run_code_walkthrough"):
        raise ValueError("Anvil v2 walkthrough engine is unavailable on this host.")
    cdir = Path(cockpit_dir).resolve()
    with _get_cockpit_lock(cdir):
        status = get_session_status(cdir)
        session = status.get("session")
        bid = (block_id or "").strip()
        if session:
            sw_path = Path((session.get("software") or {}).get("path") or cdir)
            buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
            if hasattr(anvil_engine, "_enrich_progressive_levels") and buckets:
                anvil_engine._enrich_progressive_levels(
                    sw_path,
                    buckets,
                    paper_map=session.get("paper_map"),
                    remap=session.get("remap"),
                )
            if hasattr(anvil_engine, "run_beta_reader_panel"):
                session["beta_reader_panel"] = anvil_engine.run_beta_reader_panel(
                    sw_path,
                    code_map=session.get("code_map"),
                    orange_split=session.get("orange_split"),
                    remap=session.get("remap"),
                )
            try:
                wt = anvil_engine.run_code_walkthrough(
                    sw_path,
                    code_map=session.get("code_map"),
                    block_id=bid,
                )
            except TypeError:
                wt = anvil_engine.run_code_walkthrough(sw_path, block_id=bid)
            session["walkthrough_trace"] = wt
            session["walkthrough"] = wt
            if bid:
                session["selected_block_id"] = bid
            session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
            _write_anvil_manifest(cdir, session)
            _write_anvil_report(cdir, session)
            return {
                **get_session_status(cdir),
                "walkthrough": wt,
            }
        else:
            wt = anvil_engine.run_code_walkthrough(cdir, block_id=bid)
            return {
                **status,
                "walkthrough": wt,
            }


def reset_cockpit_session(cockpit_dir: str | Path) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    with _get_cockpit_lock(cdir):
        sfile = _session_file(cdir)
        if sfile.is_file():
            prev = _session_dir(cdir) / "session.prev.json"
            try:
                _atomic_write_text(prev, sfile.read_text(encoding="utf-8", errors="replace"))
                sfile.unlink()
            except Exception:
                pass
        return get_session_status(cdir)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Per-Cockpit Anvil Session CLI for Cockpit Stewards")
    parser.add_argument("--cockpit", default=".", help="Path to the AI Cockpit folder")
    parser.add_argument(
        "--action",
        default="status",
        choices=("status", "start_code", "start_paper", "probe_block", "walkthrough", "sign_off_drop", "attach_paper", "chat", "reset"),
    )
    parser.add_argument("--software", default=".", help="Local path in cockpit or GitHub repo URL")
    parser.add_argument("--compare", default="", help="Comparison software target for remap/null-space")
    parser.add_argument("--paper", default="", help="arXiv ID/URL, HTTPS URL, or local paper path")
    parser.add_argument("--block", default="", help="Block ID or file for probe_block / walkthrough")
    parser.add_argument("--function", default="", help="Function name for sign_off_drop")
    parser.add_argument("--question", default="", help="Question for Anvil Agent chat")
    args = parser.parse_args(argv)

    cdir = Path(args.cockpit).resolve()
    if args.action == "status":
        res = get_session_status(cdir)
    elif args.action in ("start_code", "start_paper"):
        res = start_cockpit_session(
            cdir,
            mode="paper" if args.action == "start_paper" else "code",
            software_spec=args.software,
            compare_spec=args.compare,
            paper_spec=args.paper,
        )
    elif args.action == "probe_block":
        res = probe_block_in_session(cdir, args.block)
    elif args.action == "walkthrough":
        res = walkthrough_in_session(cdir, args.block)
    elif args.action == "sign_off_drop":
        res = sign_off_null_space_in_session(cdir, args.function)
    elif args.action == "attach_paper":
        res = attach_paper_to_session(cdir, args.paper)
    elif args.action == "chat":
        res = chat_in_session(cdir, args.question, target=args.block)
    else:
        res = reset_cockpit_session(cdir)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
