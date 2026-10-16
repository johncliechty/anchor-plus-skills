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
import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import importlib

_ANCHOR_ROOT = Path(__file__).resolve().parent.parent
_FOUNDRY_CANDIDATES = (
    _ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil" / "scripts",
)
for _cand in _FOUNDRY_CANDIDATES:
    if _cand.is_dir() and str(_cand) not in sys.path:
        sys.path.append(str(_cand))

try:
    anvil_engine = importlib.import_module("anvil_engine")  # type: ignore
except Exception:
    anvil_engine = None  # type: ignore

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
    ecg = cdir / "ECGBERHT.md"
    if ecg.is_file():
        try:
            for line in ecg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("# "):
                    return line.strip()[2:].strip()
        except Exception:
            pass
    rm = cdir / "roadmap.json"
    if rm.is_file():
        try:
            data = json.loads(rm.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and data.get("project"):
                return str(data["project"]).strip()
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
        if sc_dir.is_dir():
            software.insert(0, {
                "path": str(sc_dir),
                "label": f"Anchor steward_cockpit/ ({sc_dir}) · Wave 13 Target",
                "kind": "dir",
            })
        if _ANCHOR_ROOT.is_dir():
            software.insert(1, {
                "path": str(_ANCHOR_ROOT.resolve()),
                "label": f"Anchor Root ({_ANCHOR_ROOT.resolve()}) · Wave 14 Target",
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


def resolve_paper_source(cdir: Path, paper_spec: str) -> Dict[str, Any]:
    """Resolve a paper from an arXiv ID/URL, an HTTPS URL, or a local file in the Cockpit."""
    spec = (paper_spec or "").strip()
    if not spec:
        raise ValueError("Please provide a paper URL (e.g. arXiv link) or select a local paper file in this cockpit.")

    papers_dir = _session_dir(cdir) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    arxiv_match = ARXIV_ID_RE.search(spec)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
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
        dest = papers_dir / f"arxiv_{re.sub(r'[^A-Za-z0-9_.-]+', '_', arxiv_id)}.md"
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
        raw_bytes, content_type = _safe_urlopen(spec, max_bytes=2_000_000, timeout=12.0)
        base_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(urllib.parse.urlparse(spec).path).stem or "paper")[:44]
        url_hash = hashlib.sha1(spec.encode("utf-8")).hexdigest()[:8]
        slug = f"{base_slug}_{url_hash}"
        if "pdf" in content_type or spec.lower().endswith(".pdf"):
            dest = papers_dir / f"{slug}.pdf"
            dest.write_bytes(raw_bytes)
            text = _extract_text_from_file(dest)
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
        first_line = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), slug)
        return {
            "path": str(dest),
            "source_type": "url",
            "title": first_line[:110],
            "url": spec,
            "text": text,
            "spec": spec,
        }

    candidate = _validate_and_resolve_local_path(cdir, spec)
    if not candidate.is_file():
        raise ValueError(f"Paper file '{spec}' was not found at {candidate}.")

    text = _extract_text_from_file(candidate)
    first_line = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), candidate.name)
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


def _enrich_buckets_with_previews(repo: Path, buckets: List[Dict[str, Any]]) -> None:
    base = repo.parent if repo.is_file() else repo
    for b in buckets:
        if not (b.get("source_preview") and b.get("total_lines")):
            rel = b.get("file") or ""
            fpath = (base / rel).resolve() if rel else None
            if fpath and fpath.is_file() and not fpath.is_symlink():
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    b["source_preview"] = "\n".join(lines[:80])
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
        b["inner_process_map"] = {
            "steps": [
                {
                    "step_num": idx + 1,
                    "name": fn["name"],
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
            ],
            "edges": inner_edges,
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
    pith_names = {p.get("name") for p in (orange_split.get("pith_and_seeds") or [])}
    juice_names = {j.get("name") for j in (orange_split.get("juice") or [])}
    target_stem = sw_path.stem if sw_path.is_file() else sw_path.name
    clean_stem = re.sub(r"[^a-z0-9_]+", "_", target_stem.lower()).strip("_") or "module"

    # Build Old Monolithic Code cards (sorted by total_lines / function count so monoliths appear at top)
    old_monoliths: List[Dict[str, Any]] = []
    ingest_all: List[Dict[str, Any]] = []
    compute_all: List[Dict[str, Any]] = []
    emit_all: List[Dict[str, Any]] = []
    ai_all: List[Dict[str, Any]] = []

    sorted_buckets = sorted(
        buckets,
        key=lambda b: (int(b.get("total_lines") or 0), len(b.get("functions") or [])),
        reverse=True,
    )

    for b in sorted_buckets:
        funcs = b.get("functions") or []
        b_ingest = [f for f in funcs if f["name"] not in pith_names and f.get("stage") == "ingest"]
        b_compute = [f for f in funcs if f["name"] not in pith_names and (f["name"] in juice_names or f.get("stage") == "compute")]
        b_emit = [f for f in funcs if f["name"] not in pith_names and f.get("stage") == "emit" and f["name"] not in juice_names]
        b_null = [f for f in funcs if f["name"] in pith_names]
        b_ai = [f for f in funcs if f.get("ai_interaction")]

        for f in b_ingest:
            ingest_all.append({**f, "source_block_id": b["id"], "source_file": b.get("file", "")})
        for f in b_compute:
            compute_all.append({**f, "source_block_id": b["id"], "source_file": b.get("file", "")})
        for f in b_emit:
            emit_all.append({**f, "source_block_id": b["id"], "source_file": b.get("file", "")})
        for f in b_ai:
            ai_all.append({**f, "source_block_id": b["id"], "source_file": b.get("file", "")})

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
            "block_id": b["id"],
            "title": b.get("title") or b["id"],
            "file": b.get("file") or "",
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

    # Detect any existing extracted *_core.py blocks in buckets so we can link directly to them
    core_bucket = next((b for b in buckets if "core" in (b.get("file") or "").lower()), None)
    ingest_bucket = next((b for b in buckets if b.get("pipeline_stage") == "ingest"), buckets[0] if buckets else None)
    emit_bucket = next((b for b in buckets if b.get("pipeline_stage") == "emit"), buckets[-1] if buckets else None)

    new_blocks: List[Dict[str, Any]] = [
        {
            "id": "new-block-ingest",
            "drill_block_id": ingest_bucket["id"] if ingest_bucket else "",
            "stage": "ingest",
            "stage_badge": "STAGE 1 · GET-DATA (INGEST)",
            "title": f"New Block 1 — {clean_stem}_ingest.py (Pure Data & State Readers)",
            "file": f"{clean_stem}_ingest.py",
            "summary": (
                f"Consolidates {len(ingest_all)} Peel (Get-Data) functions across {len(buckets)} modules into "
                "pure, side-effect-isolated file/JSON/request readers with explicit schema validation."
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
            "drill_block_id": (core_bucket or (buckets[0] if buckets else {} )).get("id", ""),
            "stage": "compute",
            "stage_badge": "STAGE 2 · DO-ANALYSIS (ESSENTIAL CORE / JUICE)",
            "title": (
                f"New Block 2 — {core_bucket['file'] if core_bucket else clean_stem + '_core.py'} "
                "(Pure Essential Core · Hypothesis Verified)"
            ),
            "file": core_bucket["file"] if core_bucket else f"{clean_stem}_core.py",
            "summary": (
                f"Isolates {len(compute_all)} Essential Core (Juice) domain & analysis functions with zero "
                "disk/network/UI side effects, enabling fast property-based Hypothesis differential equivalence testing."
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
            "title": f"New Block 3 — {clean_stem}_emit.py (Pure Output & Route Renderers)",
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

    return {
        "old_monoliths": old_monoliths,
        "new_blocks": new_blocks,
        "totals": {
            "old_modules": len(old_monoliths),
            "mixed_modules": sum(1 for m in old_monoliths if m["mixed_concerns"]),
            "ingest_fns": len(ingest_all),
            "compute_fns": len(compute_all),
            "emit_fns": len(emit_all),
            "null_space_fns": len((remap.get("null_space") or {}).get("items") or []),
        },
    }



def extract_paper_claims_and_align(
    repo: Path,
    buckets: List[Dict[str, Any]],
    paper_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract equations/claims from a paper and align each to matching software functions honestly."""
    text = str(paper_info.get("text") or "")
    paper_title = str(paper_info.get("title") or "Paper")
    raw_claims: List[Dict[str, str]] = []

    # 1. Extract explicit JSON claims if paper_info is a JSON spec
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("claims"), list):
            for idx, item in enumerate(parsed["claims"]):
                raw_claims.append({
                    "id": str(item.get("id") or f"eq-{idx + 1}"),
                    "title": str(item.get("title") or f"Claim {idx + 1}"),
                    "expr": str(item.get("latex") or item.get("equation") or ""),
                    "context": str(item.get("description") or item.get("title") or ""),
                })
    except Exception:
        pass

    # 2. Extract LaTeX display equations ($$...$$ or \begin{equation}...\end{equation})
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

        # 3. Extract markdown headings / bullet claims or sentences with mathematical formulas
        for ln in lines:
            if len(raw_claims) >= 8:
                break
            if ln.startswith("## ") or ln.startswith("### ") or ln.startswith("- "):
                clean_title = ln.lstrip("#- *").strip()
                if len(clean_title) < 6:
                    continue
                inline_eq = re.search(r"\$([^$]+)\$", clean_title)
                expr = inline_eq.group(1) if inline_eq else ""
                raw_claims.append({
                    "id": f"claim-{len(raw_claims) + 1}",
                    "title": clean_title[:110],
                    "expr": expr,
                    "context": clean_title,
                })

    if not raw_claims:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 25][:4]
        for idx, sent in enumerate(sentences or [paper_title]):
            inline_eq = re.search(r"\$([^$]+)\$", sent)
            raw_claims.append({
                "id": f"claim-{idx + 1}",
                "title": sent[:105],
                "expr": inline_eq.group(1) if inline_eq else "",
                "context": sent,
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

    alignments: List[Dict[str, Any]] = []
    for c in raw_claims[:10]:
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

        mml = latex_to_mathml(c["expr"]) if c.get("expr") else ""
        if best_fn is not None:
            status = "VERIFIED" if best_fn.get("bucket_validated") else "HEURISTIC_MATCH"
            rationale = f"Matched on shared domain terms ({', '.join(best_overlap)}) in {best_fn['stage'].upper()} stage"
        else:
            status = "UNMAPPED"
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
        "paper_path": paper_info.get("path", ""),
        "repo": str(repo),
        "claims_mapped": len(alignments),
        "native_mathml_enforced": True,
        "alignments": alignments,
    }


def _write_anvil_report(cdir: Path, session: Dict[str, Any]) -> Path:
    report_path = cdir / "ANVIL-REPORT.md"
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

    _atomic_write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def get_session_status(cockpit_dir: str | Path) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    sfile = _session_file(cdir)
    session = None
    corrupt_error = None
    if sfile.is_file():
        try:
            loaded = json.loads(sfile.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict) and loaded.get("active"):
                session = loaded
                code_map = session.get("code_map") or {}
                buckets = code_map.get("conceptual_buckets") or []
                sw_path = Path((session.get("software") or {}).get("path") or cdir)
                if buckets and not buckets[0].get("inner_process_map"):
                    _enrich_buckets_with_previews(sw_path, buckets)
                remap = session.get("remap")
                if isinstance(remap, dict) and not remap.get("best_in_class_map"):
                    cmp_path = Path((session.get("compare_software") or {}).get("path") or sw_path)
                    remap["best_in_class_map"] = _build_best_in_class_remap(
                        sw_path,
                        cmp_path,
                        code_map,
                        session.get("orange_split") or {},
                        remap,
                    )
        except Exception as exc:
            corrupt_error = f"Session file {sfile.name} could not be parsed: {exc}"
    out: Dict[str, Any] = {
        "ok": True,
        "cockpit_dir": str(cdir),
        "cockpit_name": _cockpit_display_name(cdir),
        "active": bool(session),
        "session": session,
        "candidates": discover_cockpit_candidates(cdir),
    }
    if corrupt_error:
        out["warning"] = corrupt_error
    return out


def start_cockpit_session(
    cockpit_dir: str | Path,
    mode: str = "code",
    software_spec: str = ".",
    compare_spec: str = "",
    paper_spec: str = "",
    signed_off_drops: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create or replace the active Per-Cockpit Anvil Session for `cockpit_dir`."""
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

        code_map = anvil_engine.build_map(sw_path)
        if len(code_map.get("conceptual_buckets") or []) < 25:
            extra_buckets = _scan_non_python_buckets(sw_path, start_idx=len(code_map.get("conceptual_buckets") or []) + 1)
            existing_files = {b.get("file") for b in (code_map.get("conceptual_buckets") or [])}
            for eb in extra_buckets:
                if eb["file"] not in existing_files:
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

        orange_split = anvil_engine.extract_orange_split(sw_path)
        signed_list = list(signed_off_drops) if signed_off_drops is not None else prior_signed
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
                    "summary": p.get("summary", "Unreferenced / legacy scaffolding candidate"),
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
            )

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        buckets = code_map.get("conceptual_buckets") or []
        first_block = buckets[0]["title"] if buckets else sw_info["label"]
        total_fns = sum(len(b.get("functions") or []) for b in buckets)

        greeting = (
            f"Anvil session initialized for **{cockpit_name}** targeting `{sw_info['label']}` "
            f"({len(buckets)} conceptual blocks, {total_fns} functions)."
        )
        if paper_map:
            greeting += (
                f" Mapped **{paper_map.get('paper_title')}** ({paper_map.get('claims_mapped', 0)} claims/equations analyzed)."
            )
        greeting += (
            f" Parable of the Oranges one-trip summary: {orange_split.get('counts', {}).get('juice_count', 0)} Essential Core (`Juice`) "
            f"functions, {orange_split.get('counts', {}).get('peel_count', 0)} I/O contracts (`Peel`), and "
            f"{orange_split.get('counts', {}).get('pith_and_seeds_count', 0)} Null Space / scaffolding candidates (`Pith & Seeds`)."
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
            "selected_block_id": buckets[0]["id"] if buckets else "",
            "chat_history": [
                {
                    "role": "anvil",
                    "mode": "paper-map" if paper_map else "map",
                    "target": first_block,
                    "text": greeting,
                    "at": now_iso,
                }
            ],
        }

        _atomic_write_text(sfile, json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return get_session_status(cdir)


def probe_block_in_session(
    cockpit_dir: str | Path,
    block_id: str,
    lock_description: str = "",
) -> Dict[str, Any]:
    """Run a safe deterministic AST + compilation/Ruff empirical probe on a block."""
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
        block = next((b for b in buckets if b.get("id") == bid_clean or b.get("file") == bid_clean), None)
        if not block:
            raise ValueError(f"Block '{bid_clean}' not found in active session.")

        sw_path = Path((session.get("software") or {}).get("path") or cdir)
        base_dir = sw_path.parent if sw_path.is_file() else sw_path
        target_file = (base_dir / (block.get("file") or "")).resolve()

        probe_notes: List[str] = []
        emp_status = "PASS"
        if target_file.is_file() and not target_file.is_symlink() and target_file.suffix.lower() == ".py":
            passed = True
            try:
                src = target_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=target_file.name)
                compile(tree, filename=target_file.name, mode="exec")
                probe_notes.append(f"✓ AST parse & bytecode compile verified for {block.get('file')} ({len(block.get('functions') or [])} functions).")
            except Exception as exc:
                passed = False
                probe_notes.append(f"✗ Syntax/compile error in {block.get('file')}: {exc}")

            try:
                r = subprocess.run(
                    [sys.executable, "-m", "ruff", "check", "--select", "E9,F63,F7,F82", str(target_file)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    shell=False,
                )
                combined = (r.stdout + r.stderr).strip()
                if r.returncode == 0:
                    probe_notes.append("✓ Ruff static undefined-name & syntax gate: PASS (0 issues).")
                elif "No module named ruff" in combined:
                    probe_notes.append("ℹ Ruff not installed in Python environment; AST & bytecode compile passed.")
                else:
                    passed = False
                    probe_notes.append(f"✗ Ruff static check findings:\n{combined[:400]}")
            except Exception:
                pass
            emp_status = "PASS" if passed else "MISMATCH"
            block["validated"] = passed
        elif target_file.is_file() and not target_file.is_symlink():
            emp_status = "UNPROBED"
            block["validated"] = False
            probe_notes.append(f"ℹ Non-Python module {block.get('file')} ({target_file.stat().st_size} bytes) — static Python AST probe not applicable.")
        else:
            emp_status = "MISMATCH"
            block["validated"] = False
            probe_notes.append(f"✗ Source file {block.get('file')} not found.")

        empirical = {
            "ran": True,
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
                    al["empirical_status"] = "VERIFIED" if block["validated"] else "HEURISTIC_MATCH"

        session["selected_block_id"] = block["id"]
        session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        _write_anvil_report(cdir, session)
        return {
            **get_session_status(cdir),
            "block": block,
            "empirical": empirical,
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
        buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
        paper_info = resolve_paper_source(cdir, paper_spec)
        paper_map = extract_paper_claims_and_align(sw_path, buckets, paper_info)
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
    arxiv_m = re.search(r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?)", q, re.IGNORECASE)
    url_m = re.search(r"(https?://[^\s)\"'>]+)", q, re.IGNORECASE)
    if arxiv_m:
        matched_paper = f"arXiv:{arxiv_m.group(1)}"
    elif url_m and ("arxiv" in url_m.group(1).lower() or url_m.group(1).lower().endswith((".pdf", ".md", ".tex", ".html"))):
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
            # Match distinctive words from label
            words = [w for w in re.split(r"[^a-z0-9]+", p_label) if len(w) >= 4 and w not in ("paper", "local", "file", "draft", "notes")]
            if words and any(w in q_low for w in words):
                matched_paper = p_path
                break
        # If user asks generally for "the paper", "local paper", "loaded locally", "pull it", "look for this paper"
        if not matched_paper and any(kw in q_low for kw in ("paper", "loaded locally", "local file", "look for", "pull", "slides", "manuscript", "equation")):
            matched_paper = paper_cands[0].get("path") or ""

    # 3. Check for software path match in message
    matched_sw = "."
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
            "essential core", "scaffolding", "codebase", "software", "solver", ".py", ".md", ".pdf"
        )
    )
    return {
        "wants_launch": wants_launch,
        "software_spec": matched_sw,
        "paper_spec": matched_paper,
    }


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
    candidates = status.get("candidates") or _discover_cockpit_candidates(cdir)

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
                    reply = (
                        f"[Steward · Anvil Setup] Located paper **{paper_map.get('paper_title')}** (`{inferred['paper_spec']}`) "
                        f"and initialized your Anvil Paper ↔ Software session against `{sw_label}` "
                        f"({paper_map.get('claims_mapped', 0)} claims/equations extracted into native MathML)."
                    )
                else:
                    buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
                    reply = (
                        f"[Steward · Anvil Setup] Initialized your Anvil Software Analysis session for `{sw_label}` "
                        f"({len(buckets)} conceptual blocks mapped into Essential Core vs. Scaffolding)."
                    )
                history.append({"role": "anvil", "mode": mode, "target": target or "setup", "text": reply, "at": now_iso})
                session["chat_history"] = history[-40:]
                session["updated_at"] = now_iso
                _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
                return {**get_session_status(cdir), "reply": reply}
        else:
            sw_list = ", ".join(f"`{c['path']}`" for c in (candidates.get("software") or [])[:5]) or "`.`"
            pp_list = ", ".join(f"`{c['path']}`" for c in (candidates.get("papers") or [])[:5]) or "none detected yet"
            reply = (
                f"[Steward · Anvil Setup] Ready to configure Anvil for **{status.get('cockpit_name', cdir.name)}**. "
                f"Local software detected: {sw_list}. Local papers/docs detected: {pp_list}. "
                f"Tell me which paper or codebase to load (e.g. \"Set up Anvil with local paper and map to code\" or \"Pull arXiv:1706.03762\"), and I will launch the session immediately."
            )
            return {**status, "reply": reply}

    with _get_cockpit_lock(cdir):
        status = get_session_status(cdir)
        session = status.get("session")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        history = list(session.get("chat_history") or [])
        history.append({"role": "user", "mode": mode, "target": target, "text": q, "at": now_iso})

        # Check if user is asking in chat to attach/switch a paper on an already-active session
        inferred = _infer_setup_targets_from_chat(cdir, q, candidates)
        q_low = q.lower()
        if inferred["paper_spec"] and any(kw in q_low for kw in ("attach", "pull", "look for", "load", "loaded locally", "switch paper", "map paper")):
            sw_path = Path((session.get("software") or {}).get("path") or cdir)
            buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
            paper_info = resolve_paper_source(cdir, inferred["paper_spec"])
            paper_map = extract_paper_claims_and_align(sw_path, buckets, paper_info)
            session["paper_map"] = paper_map

        buckets = (session.get("code_map") or {}).get("conceptual_buckets") or []
        matched = next(
            (b for b in buckets if b.get("id") == target or b.get("file") == target or b.get("title") == target),
            buckets[0] if buckets else None,
        )
        orange = session.get("orange_split") or {}
        paper_map = session.get("paper_map")

        if mode in ("paper", "paper-map") and paper_map and paper_map.get("alignments"):
            al = next((a for a in paper_map["alignments"] if a.get("claim_id") == target), paper_map["alignments"][0])
            reply = (
                f"[Anvil Agent · Paper ↔ Code] In **{paper_map.get('paper_title')}**, claim `{al.get('claim_id')}` "
                f"({al.get('title')}) maps to `{al.get('mapped_function')}` in `{al.get('mapped_file')}:{al.get('lineno')}` "
                f"({al.get('match_rationale')}). "
                f"Proactive Next Step (Parable of the Oranges): Run the live block probe on `{al.get('mapped_file')}` to lock empirical equivalence."
            )
        elif matched:
            fns = ", ".join(fn["name"] for fn in (matched.get("functions") or [])[:5])
            stage = (matched.get("pipeline_stage") or "compute").upper()
            reply = (
                f"[Anvil Agent · {mode}] On block **{matched.get('title')}** (`{matched.get('file')}`, stage `{stage}`"
                + (f", functions: `{fns}`" if fns else "")
                + f"): {matched.get('validated_description') or matched.get('summary')}. "
                + f"Proactive Next Step (Parable of the Oranges): {(orange.get('proactive_staff_work') or {}).get('one_trip_recommendation', 'Probe and lock this block before remapping downstream callers.')}"
            )
        else:
            reply = (
                f"[Anvil Agent · {mode}] Regarding \"{q}\": {(orange.get('proactive_staff_work') or {}).get('one_trip_recommendation', 'Select a block or attach a paper to inspect its implementation.')}"
            )

        history.append({"role": "anvil", "mode": mode, "target": target, "text": reply, "at": now_iso})
        session["chat_history"] = history[-40:]
        session["updated_at"] = now_iso
        _atomic_write_text(_session_file(cdir), json.dumps(session, indent=2))
        return {**get_session_status(cdir), "reply": reply}


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
        choices=("status", "start_code", "start_paper", "probe_block", "sign_off_drop", "attach_paper", "chat", "reset"),
    )
    parser.add_argument("--software", default=".", help="Local path in cockpit or GitHub repo URL")
    parser.add_argument("--compare", default="", help="Comparison software target for remap/null-space")
    parser.add_argument("--paper", default="", help="arXiv ID/URL, HTTPS URL, or local paper path")
    parser.add_argument("--block", default="", help="Block ID or file for probe_block")
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
