"""Isolated Python Dependency Discovery, 1-Click HMAC Approval, Venv Installer & Signed Store Guards (`anvil_py_deps.py`).

100% Python stdlib; zero `urllib`/`http`/`socket`; zero `shell=True`; Win32 kill-on-close Job Objects;
wheel-only `--only-binary=:all:` pip installs (zero sdist `setup.py`/PEP-517 host build execution);
curated scientific PyPI allowlist on both runtime and AST-scanned imports; component-by-component
`os.lstat` reparse refusal; HMAC-signed `runtime_env.json`, replication receipts, and 3-leg gate artifacts.
"""
from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import hmac
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import warnings
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from steward_cockpit import anvil_comprehension_engine as _ace
from steward_cockpit import anvil_session as _as

RUNTIME_ENV_SCHEMA = "anvil-runtime-env/v1"
CONSUMED_DEP_NONCES_SCHEMA = "anvil-dep-install-nonces/v1"
MAX_INSTALL_PACKAGES = 24
MAX_AST_SCAN_FILE_BYTES = 2 * 1024 * 1024
PIP_INSTALL_TIMEOUT_SEC = 900.0
DEP_TOKEN_TTL_SEC = 3600

_SAFE_PKG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{24,64}$")
_SAFE_PROXY_TLS_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")

_INJECTED_PIP_INSTALLER: Optional[Callable[..., Path]] = globals().get("_INJECTED_PIP_INSTALLER")
_EXTRA_TEST_ALLOWED_PACKAGES: frozenset[str] = globals().get("_EXTRA_TEST_ALLOWED_PACKAGES", frozenset())

IMPORT_TO_PYPI: Dict[str, str] = {
    "attr": "attrs",
    "Bio": "biopython",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python-headless",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "faiss": "faiss-cpu",
    "fitz": "PyMuPDF",
    "git": "GitPython",
    "igraph": "python-igraph",
    "ot": "POT",
    "PIL": "Pillow",
    "pyro": "pyro-ppl",
    "sentence_transformers": "sentence-transformers",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "umap": "umap-learn",
    "yaml": "PyYAML",
    "z3": "z3-solver",
}

KNOWN_SCIENTIFIC_PYPI_PACKAGES: frozenset[str] = frozenset({
    "accelerate", "aiohttp", "albumentations", "altair", "anndata", "arch", "arviz", "astropy",
    "attrs", "ax-platform", "bambi", "beautifulsoup4", "biopython", "blackjax", "bokeh",
    "botorch", "bottleneck", "cachetools", "catboost", "causalml", "chex", "clarabel", "click",
    "cloudpickle", "cma", "cmdstanpy", "corner", "cupy", "cvxopt", "cvxpy", "cython", "dask",
    "datasets", "diffrax", "dill", "distrax", "doubleml", "dowhy", "duckdb", "econml", "ecos",
    "einops", "emcee", "equinox", "evaluate", "faiss-cpu", "fastparquet", "filelock", "flax",
    "formulaic", "fsspec", "gensim", "geopandas", "gitpython", "gmpy2", "gpytorch", "h5netcdf",
    "h5py", "hdbscan", "highspy", "holoviews", "httpx", "huggingface-hub", "hydra-core",
    "hypothesis", "imageio", "jax", "jaxlib", "jaxtyping", "jinja2", "joblib", "kornia",
    "lifelines", "lightgbm", "linearmodels", "llvmlite", "loguru", "lxml", "matplotlib",
    "mlflow", "more-itertools", "mpmath", "msgpack", "multiprocess", "netcdf4", "networkx",
    "nltk", "numba", "numexpr", "numpy", "numpyro", "omegaconf", "openpyxl",
    "opencv-python-headless", "opt-einsum", "optax", "optuna", "orjson", "ortools", "osqp",
    "packaging", "pandas", "pathos", "patsy", "peft", "pillow", "pingouin", "plotly", "polars",
    "pot", "prettytable", "prophet", "protobuf", "psutil", "pulp", "pyarrow", "pydantic",
    "pyfixest", "pymc", "pymupdf", "pynndescent", "pyproj", "pyreadstat", "pyro-ppl", "pytest",
    "pytensor", "python-dateutil", "python-docx", "python-dotenv", "python-igraph", "pytz",
    "pyyaml", "rasterio", "ray", "regex", "requests", "rich", "ruptures", "safetensors",
    "scanpy", "scikit-image", "scikit-learn", "scikit-survival", "scipy", "scs", "seaborn",
    "sentence-transformers", "sentencepiece", "shap", "shapely", "sktime", "spacy", "sqlalchemy",
    "statsmodels", "sympy", "tables", "tabulate", "tenacity", "tensorboard", "tiktoken", "timm",
    "tokenizers", "toml", "tomli", "toolz", "torch", "torchaudio", "torchmetrics", "torchvision",
    "tqdm", "transformers", "tsfresh", "typer", "umap-learn", "wandb", "xarray", "xgboost",
    "xlrd", "xlsxwriter", "z3-solver", "zarr",
})


def _in_pytest_runtime() -> bool:
    return "pytest" in sys.modules


def set_pip_installer_for_tests(
    fn: Optional[Callable[..., Path]],
    *,
    extra_allowed_packages: Sequence[str] = (),
) -> None:
    global _INJECTED_PIP_INSTALLER, _EXTRA_TEST_ALLOWED_PACKAGES
    _INJECTED_PIP_INSTALLER = fn
    _EXTRA_TEST_ALLOWED_PACKAGES = frozenset(str(x).strip().lower() for x in extra_allowed_packages if str(x).strip()) if fn is not None else frozenset()
    globals()["_INJECTED_PIP_INSTALLER"] = _INJECTED_PIP_INSTALLER
    globals()["_EXTRA_TEST_ALLOWED_PACKAGES"] = _EXTRA_TEST_ALLOWED_PACKAGES


def _allowed_pypi_packages() -> Set[str]:
    allowed = set(KNOWN_SCIENTIFIC_PYPI_PACKAGES)
    if _in_pytest_runtime() and _EXTRA_TEST_ALLOWED_PACKAGES:
        allowed.update(_EXTRA_TEST_ALLOWED_PACKAGES)
    return allowed


def is_valid_pypi_package_name(name: str) -> bool:
    s = str(name or "").strip()
    if not s or len(s) > 64 or s.startswith("-") or ".." in s:
        return False
    return _SAFE_PKG_RE.fullmatch(s) is not None and s.lower() in _allowed_pypi_packages()


def _anvil_py_env_root() -> Path:
    import paths as _paths
    base = Path(os.environ.get("ANCHOR_DATA_DIR") or getattr(_paths, "CODE_DIR", _as._ANCHOR_ROOT))
    if _ace._is_lstat_reparse(base):
        raise _ace.AnvilPathEscapeError("ANCHOR_DATA_DIR is a symlink or junction.")
    base_res = base.resolve()
    _ace._ensure_no_reparse_chain(base_res, (".anchor", "anvil_py_env"))
    return base_res / ".anchor" / "anvil_py_env"


def checked_v4_subpath(raw_store_root: Path, rel: str) -> Path:
    """Enforce component-by-component `os.lstat` reparse refusal on `<store_root>/.anvil/v4/<rel>` (and `.lock`)."""
    if _ace._is_lstat_reparse(raw_store_root):
        raise PermissionError("Symlink or junction refused on store_root.")
    clean_parts = [pt for pt in str(rel or "").replace("\\", "/").split("/") if pt and pt != "."]
    if not clean_parts or ".." in clean_parts:
        raise PermissionError(f"Invalid replication store subpath: {rel!r}")
    parent_parts = clean_parts[:-1]
    _ace._ensure_no_reparse_chain(raw_store_root, (".anvil", "v4", *parent_parts))
    leaf = raw_store_root.resolve() / ".anvil" / "v4" / Path(*clean_parts)
    if _ace._is_lstat_reparse(leaf) or _ace._is_lstat_reparse(Path(f"{leaf}.lock")):
        raise PermissionError(f"Symlink or junction refused on {leaf.name}.")
    return leaf


def ensure_deliverables_not_reparse(raw_cdir: Path, report_md: Path, deliv_md: Path) -> None:
    if _ace._is_lstat_reparse(raw_cdir):
        raise PermissionError("Symlink or junction refused on cockpit directory.")
    for p in (report_md, Path(f"{report_md}.lock"), deliv_md, Path(f"{deliv_md}.lock")):
        if _ace._is_lstat_reparse(p):
            raise PermissionError(f"Symlink or junction refused on deliverable file '{p.name}'.")


def snapshot_source_repo_sha256(sw_dir: Path) -> Dict[str, str]:
    snap: Dict[str, str] = {}
    skip_dirs = {".anvil", ".anchor", ".ecgberht", ".steward", ".git", "__pycache__", "node_modules", ".pytest_cache", ".venv", "venv"}

    def _hash_reg(fp: Path) -> str:
        st = fp.stat()
        if st.st_size > 64 * 1024 * 1024:
            return f"oversize:{st.st_size}:{st.st_mtime_ns}"
        h = hashlib.sha256()
        with fp.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest()

    for cur_r, dirs, files in os.walk(sw_dir, followlinks=False):
        cur_p = Path(cur_r)
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not _as._is_symlink_or_junction(cur_p / d))
        for fn in sorted(files):
            fp = cur_p / fn
            if not fn.endswith((".pyc", ".pyo")) and not _as._is_symlink_or_junction(fp) and fp.is_file():
                snap[fp.relative_to(sw_dir).as_posix()] = _hash_reg(fp)
    git_dir = sw_dir / ".git"
    if git_dir.is_dir() and not _as._is_symlink_or_junction(git_dir):
        if (git_dir / "config").is_file() and not _as._is_symlink_or_junction(git_dir / "config"):
            snap[".git/config"] = _hash_reg(git_dir / "config")
        hooks_dir = git_dir / "hooks"
        if hooks_dir.is_dir() and not _as._is_symlink_or_junction(hooks_dir):
            for hp in sorted(hooks_dir.iterdir()):
                if hp.is_file() and not _as._is_symlink_or_junction(hp):
                    snap[f".git/hooks/{hp.name}"] = _hash_reg(hp)
    return snap


def diff_source_snapshots(before: Mapping[str, str], after: Mapping[str, str]) -> List[str]:
    return [k for k in sorted(set(before.keys()) | set(after.keys())) if before.get(k) != after.get(k)]


def resolve_contained_paper_file(base_root: Path, rel_expr: str) -> Path:
    clean_s = str(rel_expr or "").strip()
    if not clean_s or "\x00" in clean_s or clean_s.startswith(("/", "\\")) or ":" in clean_s or Path(clean_s).is_absolute():
        raise PermissionError(f"Escaping or absolute manuscript path refused: {clean_s!r}")
    parts = [pt for pt in clean_s.replace("\\", "/").split("/") if pt and pt != "."]
    if not parts or ".." in parts or _as._is_symlink_or_junction(base_root):
        raise PermissionError(f"Traversal or symlinked root refused in manuscript path: {clean_s!r}")
    base_res = base_root.resolve()
    cur = base_res
    for pt in parts:
        cur = cur / pt
        if _as._is_symlink_or_junction(cur):
            raise PermissionError(f"Symlink or junction ancestor refused in manuscript path: {clean_s!r}")
    resolved = cur.resolve()
    if not resolved.is_relative_to(base_res):
        raise PermissionError(f"Manuscript path escapes base root: {clean_s!r}")
    return resolved


def load_paper_sources_dict(sw_dir: Path, cdir: Path, paper_p: Optional[Path], manifest: Mapping[str, Any], max_bytes: int = 8 * 1024 * 1024) -> Tuple[str, Dict[str, str]]:
    sources: Dict[str, str] = {}
    paper_title = sw_dir.name

    def _ingest_doc(fp: Path, key: str) -> None:
        nonlocal paper_title
        if fp.is_file() and fp.suffix.lower() in {".tex", ".md"}:
            st_sz = int(fp.stat().st_size)
            if st_sz > max_bytes:
                raise ValueError(f"BOUND_EXCEEDED_REFUSAL: Manuscript '{fp.name}' ({st_sz} B) exceeds 8 MiB cap.")
            txt = fp.read_text(encoding="utf-8", errors="replace")
            sources[key] = txt
            if fp.suffix.lower() == ".tex":
                paper_title = _as._extract_latex_title(txt) or paper_title

    for p_ent in manifest.get("papers") or []:
        rel_k = str(p_ent.get("path") or "").strip() if isinstance(p_ent, Mapping) else ""
        if rel_k:
            base_r, sub_rel = (cdir, rel_k[len("cockpit:"):]) if rel_k.startswith("cockpit:") else (sw_dir, rel_k)
            _ingest_doc(resolve_contained_paper_file(base_r, sub_rel), rel_k)

    if not sources and paper_p is not None:
        if _as._is_symlink_or_junction(paper_p):
            raise PermissionError("Symlinked companion paper refused.")
        p_res = paper_p.resolve()
        if not (p_res.is_relative_to(cdir.resolve()) or p_res.is_relative_to(sw_dir.resolve()) or any(p_res.is_relative_to(Path(ar).resolve()) for ar in _as.ALLOWED_LOCAL_ROOTS)):
            raise PermissionError("Companion paper escapes allowed workspace roots.")
        _ingest_doc(p_res, p_res.name)
    return paper_title, sources


def _canonical_sha256(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sign_gate_artifact(cdir: Path, domain: str, doc: Mapping[str, Any]) -> Dict[str, Any]:
    body = {str(k): v for k, v in doc.items() if str(k) != "hmac"}
    body["proj_slug"] = _ace._project_slug(cdir.resolve())
    sig_input = {"proj_slug": body["proj_slug"], "body_sha256": _canonical_sha256(body)}
    return {**body, "hmac": _ace.sign_state_record(domain, sig_input)}


def verify_gate_artifact(cdir: Path, domain: str, doc: Any, expected_scope_sha256: str = "") -> bool:
    if not isinstance(doc, Mapping):
        return False
    raw_sig = str(doc.get("hmac") or "")
    if not _HEX64_RE.fullmatch(raw_sig):
        return False
    exp_slug = _ace._project_slug(cdir.resolve())
    if str(doc.get("proj_slug") or "") != exp_slug:
        return False
    if expected_scope_sha256 and doc.get("scope_sha256") and str(doc.get("scope_sha256")).lower() != expected_scope_sha256.lower():
        return False
    body = {str(k): v for k, v in doc.items() if str(k) != "hmac"}
    exp_sig = _ace.sign_state_record(domain, {"proj_slug": exp_slug, "body_sha256": _canonical_sha256(body)})
    return hmac.compare_digest(raw_sig, exp_sig)


def sign_replication_receipt(cdir: Path, receipt_doc: Mapping[str, Any]) -> Dict[str, Any]:
    return sign_gate_artifact(cdir, "repl-receipt", receipt_doc)


def verify_replication_receipt(cdir: Path, receipt_doc: Any, expected_scope_sha256: str) -> bool:
    return verify_gate_artifact(cdir, "repl-receipt", receipt_doc, expected_scope_sha256=expected_scope_sha256)


def _stdlib_names() -> Set[str]:
    names: Set[str] = set(sys.builtin_module_names)
    names.update(getattr(sys, "stdlib_module_names", frozenset()))
    names.update({"__future__", "typing_extensions"})
    return names


def _collect_local_repo_module_names(sw_dir: Path, cdir: Path) -> Set[str]:
    local: Set[str] = set()
    skip = {".git", ".anvil", ".anchor", ".steward", ".ecgberht", "__pycache__", "node_modules", ".venv", "venv"}
    for root_d in (sw_dir, cdir):
        if _ace._is_lstat_reparse(root_d) or not root_d.is_dir():
            continue
        for cur_r, dirs, files in os.walk(root_d, followlinks=False):
            cur_p = Path(cur_r)
            dirs[:] = [d for d in dirs if d not in skip and not _ace._is_lstat_reparse(cur_p / d)]
            for d in dirs:
                local.add(d)
            for fn in files:
                if fn.endswith(".py") and fn != "__init__.py":
                    local.add(Path(fn).stem)
            if root_d == cdir:
                break
    return local


def _collect_python_search_paths(sw_dir: Path, cdir: Path, store_root: Path) -> List[str]:
    paths_out: List[str] = []
    seen: Set[str] = set()

    def _add(cand: Path) -> None:
        if not _ace._is_lstat_reparse(cand) and cand.is_dir():
            r_str = str(cand.resolve())
            if r_str not in seen:
                seen.add(r_str)
                paths_out.append(r_str)

    # Only honor HMAC-verified runtime_env.json written by Anchor in cdir/store_root (never untrusted repo dirs)
    for trusted_anc in (store_root, cdir):
        if _ace._is_lstat_reparse(trusted_anc) or not trusted_anc.is_dir():
            continue
        hint_f = trusted_anc / ".anvil" / "runtime_env.json"
        if not _ace._is_lstat_reparse(hint_f) and hint_f.is_file():
            with contextlib.suppress(Exception):
                doc = json.loads(hint_f.read_text(encoding="utf-8"))
                if verify_gate_artifact(cdir, "runtime-env", doc):
                    for ex_sp in (doc.get("extra_site_packages") or []):
                        if isinstance(ex_sp, str) and ex_sp.strip():
                            _add(Path(ex_sp))

    for anc in (cdir, sw_dir):
        if _ace._is_lstat_reparse(anc) or not anc.is_dir():
            continue
        for vname in (".venv", "venv"):
            _add(anc / vname / "Lib" / "site-packages")
            lib_d = anc / vname / "lib"
            if not _ace._is_lstat_reparse(lib_d) and lib_d.is_dir():
                for pos_sp in lib_d.glob("python*/site-packages"):
                    _add(pos_sp)

    for p in sys.path:
        if isinstance(p, str) and p.strip():
            _add(Path(p))
    with contextlib.suppress(Exception):
        import site as _site_mod
        u_sp = _site_mod.getusersitepackages()
        if isinstance(u_sp, str) and u_sp.strip():
            _add(Path(u_sp))
    return paths_out


def _is_module_installed(top_mod: str, search_paths: Sequence[str], stdlib_set: Set[str]) -> bool:
    if not top_mod or top_mod in stdlib_set:
        return True
    with contextlib.suppress(Exception):
        return importlib.machinery.PathFinder.find_spec(top_mod, list(search_paths)) is not None
    return False


def _resolve_contained_py(sw_dir: Path, rel_path: str) -> Optional[Path]:
    s = str(rel_path or "").strip().replace("\\", "/")
    if not s or s.startswith("/") or ":" in s or "\x00" in s:
        return None
    parts = [pt for pt in s.split("/") if pt and pt != "."]
    if not parts or ".." in parts or not parts[-1].endswith(".py") or _ace._is_lstat_reparse(sw_dir):
        return None
    sw_res = sw_dir.resolve()
    cur = sw_res
    for pt in parts:
        cur = cur / pt
        if _ace._is_lstat_reparse(cur):
            return None
    try:
        st = os.lstat(cur)
    except OSError:
        return None
    if os.path.samestat(st, os.lstat(sw_res)) or st.st_size > MAX_AST_SCAN_FILE_BYTES:
        return None
    res = cur.resolve()
    return res if (res.is_relative_to(sw_res) and res.is_file()) else None


def _map_import_to_allowed_pypi(top_mod: str, allowed_set: Set[str]) -> str:
    if top_mod in IMPORT_TO_PYPI:
        cand = IMPORT_TO_PYPI[top_mod]
    elif top_mod.lower() in allowed_set:
        cand = top_mod
    elif top_mod.replace("_", "-").lower() in allowed_set:
        cand = top_mod.replace("_", "-")
    else:
        return ""
    return cand if (cand.lower() in allowed_set and _SAFE_PKG_RE.fullmatch(cand) is not None) else ""


def discover_missing_scope_packages(
    sw_dir: Path,
    cdir: Path,
    store_root: Path,
    scope_files: Sequence[str],
    runtime_missing_modules: Sequence[str],
) -> List[str]:
    """Combine runtime `ModuleNotFoundError` modules with AST-scanned imports, intersected strictly with allowlist."""
    importlib.invalidate_caches()
    stdlib_set = _stdlib_names()
    local_mods = _collect_local_repo_module_names(sw_dir, cdir)
    search_paths = _collect_python_search_paths(sw_dir, cdir, store_root)
    allowed_set = _allowed_pypi_packages()
    missing_pkgs: Set[str] = set()

    for raw_mod in runtime_missing_modules:
        top_mod = str(raw_mod or "").strip().split(".", 1)[0].strip()
        if not top_mod or top_mod in stdlib_set or top_mod in local_mods:
            continue
        cand_pkg = _map_import_to_allowed_pypi(top_mod, allowed_set)
        if cand_pkg and not _is_module_installed(top_mod, search_paths, stdlib_set):
            missing_pkgs.add(cand_pkg)

    for rel_f in scope_files:
        py_fp = _resolve_contained_py(sw_dir, rel_f)
        if py_fp is None:
            continue
        try:
            src = py_fp.read_text(encoding="utf-8", errors="replace")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            mod_names: List[str] = []
            if isinstance(node, ast.Import):
                mod_names = [a.name.split(".", 1)[0] for a in node.names if a.name]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mod_names = [node.module.split(".", 1)[0]]
            for top_mod in mod_names:
                if not top_mod or top_mod in stdlib_set or top_mod in local_mods:
                    continue
                cand_pkg = _map_import_to_allowed_pypi(top_mod, allowed_set)
                if cand_pkg and not _is_module_installed(top_mod, search_paths, stdlib_set):
                    missing_pkgs.add(cand_pkg)

    return sorted(missing_pkgs, key=lambda x: x.lower())[:MAX_INSTALL_PACKAGES]


def issue_one_click_dep_token(
    cdir: Path,
    scope_sha256: str,
    packages: Sequence[str],
    context_tag: str,
    *,
    trace_argv: Optional[Sequence[str]] = None,
) -> str:
    clean_pkgs = sorted({str(p).strip() for p in packages if is_valid_pypi_package_name(str(p).strip())}, key=str.lower)[:MAX_INSTALL_PACKAGES]
    if not clean_pkgs or not _HEX64_RE.fullmatch(str(scope_sha256 or "").strip().lower()):
        return ""
    doc: Dict[str, Any] = {
        "proj_slug": _ace._project_slug(cdir.resolve()),
        "scope_sha256": str(scope_sha256).strip().lower(),
        "packages": clean_pkgs,
        "context_tag": str(context_tag or "replication:A")[:48],
        "ts": int(time.time()),
        "nonce": secrets.token_hex(16),
    }
    if trace_argv is not None:
        doc["trace_argv"] = [str(x) for x in trace_argv][:32]
    sig = _ace.sign_state_record("dep-install", doc)
    raw_b64 = base64.urlsafe_b64encode(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{raw_b64}.{sig}"


def validate_dep_token_without_consuming(
    cdir: Path,
    raw_token: str,
    *,
    expected_scope_sha256: str,
    requested_packages: Sequence[str],
    expected_context_prefix: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    tok = str(raw_token or "").strip()
    if not tok or len(tok) > 4096 or "." not in tok:
        return None, "Invalid or missing dep_install_token."
    b64_part, sig_part = tok.rsplit(".", 1)
    if not _HEX64_RE.fullmatch(sig_part):
        return None, "Malformed dep_install_token signature."
    try:
        padded = b64_part + ("=" * ((4 - len(b64_part) % 4) % 4))
        doc = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None, "Malformed dep_install_token payload."
    if not isinstance(doc, dict):
        return None, "Invalid dep_install_token object."

    exp_sig = _ace.sign_state_record("dep-install", doc)
    if not hmac.compare_digest(sig_part, exp_sig):
        return None, "dep_install_token HMAC verification failed."

    ts_raw = doc.get("ts")
    if isinstance(ts_raw, bool) or not isinstance(ts_raw, int) or len(str(ts_raw)) > 12:
        return None, "Invalid dep_install_token timestamp."
    now_ts = int(time.time())
    if ts_raw > now_ts + 60 or (now_ts - ts_raw) > DEP_TOKEN_TTL_SEC:
        return None, "Expired dep_install_token — refresh state and click install again."

    if doc.get("proj_slug") != _ace._project_slug(cdir.resolve()):
        return None, "dep_install_token project mismatch."
    if str(doc.get("scope_sha256") or "") != str(expected_scope_sha256 or "").strip().lower():
        return None, "dep_install_token scope_sha256 mismatch."
    if not str(doc.get("context_tag") or "").startswith(expected_context_prefix):
        return None, "dep_install_token context mismatch."

    tok_pkgs = doc.get("packages")
    if not isinstance(tok_pkgs, list) or not tok_pkgs or len(tok_pkgs) > MAX_INSTALL_PACKAGES:
        return None, "dep_install_token has invalid package list."
    norm_tok_pkgs = sorted({str(p).strip() for p in tok_pkgs if is_valid_pypi_package_name(str(p).strip())}, key=str.lower)
    if len(norm_tok_pkgs) != len(tok_pkgs):
        return None, "dep_install_token contains unallowlisted or invalid package names."

    if not isinstance(requested_packages, (list, tuple)) or not requested_packages:
        return None, "Explicit non-empty packages list required."
    for rp in requested_packages:
        if not isinstance(rp, str) or not is_valid_pypi_package_name(rp.strip()):
            return None, f"Unallowlisted or unsafe package name refused: {rp!r}"
    norm_req_pkgs = sorted({rp.strip() for rp in requested_packages}, key=str.lower)
    if norm_req_pkgs != norm_tok_pkgs:
        return None, "Requested packages disagree with HMAC-approved missing package set."

    nonce = str(doc.get("nonce") or "")
    if not _NONCE_RE.fullmatch(nonce):
        return None, "Invalid dep_install_token nonce."
    return {"packages": norm_tok_pkgs, "nonce": nonce, "trace_argv": doc.get("trace_argv")}, None


def consume_dep_token_nonce(raw_store_root: Path, nonce: str) -> Optional[str]:
    nonce_file = checked_v4_subpath(raw_store_root, "consumed_dep_nonces.json")
    nonce_file.parent.mkdir(parents=True, exist_ok=True)
    now_ts = int(time.time())
    with _as.exclusive_file_lock(nonce_file):
        if _ace._is_lstat_reparse(nonce_file):
            raise PermissionError("Symlink swap refused on consumed_dep_nonces.json.")
        existing_nonces: Dict[str, int] = {}
        if nonce_file.is_file():
            with contextlib.suppress(Exception):
                ndoc = json.loads(nonce_file.read_text(encoding="utf-8"))
                if isinstance(ndoc, dict) and ndoc.get("schema") == CONSUMED_DEP_NONCES_SCHEMA:
                    existing_nonces = {
                        str(k): int(v) for k, v in (ndoc.get("nonces") or {}).items()
                        if isinstance(v, int) and not isinstance(v, bool) and (now_ts - v) <= DEP_TOKEN_TTL_SEC * 2
                    }
        if any(hmac.compare_digest(k, nonce) for k in existing_nonces):
            return "dep_install_token has already been used."
        existing_nonces[nonce] = now_ts
        _as._atomic_write_text(nonce_file, json.dumps({"schema": CONSUMED_DEP_NONCES_SCHEMA, "nonces": existing_nonces}, separators=(",", ":"), sort_keys=True))
    return None


def verify_and_consume_dep_token(
    cdir: Path,
    raw_store_root: Path,
    raw_token: str,
    *,
    expected_scope_sha256: str,
    requested_packages: Sequence[str],
    expected_context_prefix: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    parsed, err = validate_dep_token_without_consuming(
        cdir, raw_token, expected_scope_sha256=expected_scope_sha256,
        requested_packages=requested_packages, expected_context_prefix=expected_context_prefix,
    )
    if err or parsed is None:
        return None, err
    n_err = consume_dep_token_nonce(raw_store_root, str(parsed["nonce"]))
    if n_err:
        return None, n_err
    return parsed, None


def _run_managed_cmd(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_sec: float,
    cancel_ev: Optional[threading.Event],
    heartbeat_cb: Optional[Callable[[], None]] = None,
) -> Tuple[int, str, str]:
    proc, job_h = _ace.spawn_in_win32_job(argv, cwd=cwd, env=env, has_stdin=False)
    out_chunks: List[str] = []
    err_chunks: List[str] = []
    t_out = threading.Thread(target=lambda: out_chunks.append(proc.stdout.read() if proc.stdout else ""), daemon=True)
    t_err = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read() if proc.stderr else ""), daemon=True)
    t_out.start()
    t_err.start()
    deadline = time.monotonic() + timeout_sec
    last_hb = time.monotonic()
    killed_reason = ""
    try:
        while proc.poll() is None:
            if cancel_ev is not None and cancel_ev.is_set():
                killed_reason = "CANCELLED"
                break
            now_m = time.monotonic()
            if now_m >= deadline:
                killed_reason = "TIMEOUT"
                break
            if heartbeat_cb is not None and (now_m - last_hb) >= 5.0:
                last_hb = now_m
                with contextlib.suppress(Exception):
                    heartbeat_cb()
            time.sleep(0.15)
        if killed_reason:
            _ace.terminate_and_close_win32_job(job_h, terminate=True)
            job_h = 0
            with contextlib.suppress(Exception):
                proc.kill()
        t_out.join(timeout=5.0)
        t_err.join(timeout=5.0)
    finally:
        if job_h:
            _ace.close_win32_job(job_h)
    if killed_reason == "CANCELLED":
        raise TimeoutError("REPLICATION_CANCELLED")
    if killed_reason == "TIMEOUT":
        raise TimeoutError("PIP_INSTALL_TIMEOUT")
    return int(proc.returncode or 0), "".join(out_chunks)[:8192], "".join(err_chunks)[:8192]


def _persist_runtime_env_site_packages(cdir: Path, raw_target_root: Path, site_pkg_dir: Path) -> None:
    if _ace._is_lstat_reparse(raw_target_root):
        raise PermissionError("Symlink or junction refused on target runtime_env root.")
    _ace._ensure_no_reparse_chain(raw_target_root, (".anvil",))
    anvil_d = raw_target_root.resolve() / ".anvil"
    rt_file = anvil_d / "runtime_env.json"
    if _ace._is_lstat_reparse(rt_file) or _ace._is_lstat_reparse(Path(f"{rt_file}.lock")):
        raise PermissionError("Symlink or junction refused on runtime_env.json.")
    anvil_d.mkdir(parents=True, exist_ok=True)
    sp_str = str(site_pkg_dir.resolve())
    with _as.exclusive_file_lock(rt_file):
        if _ace._is_lstat_reparse(rt_file):
            raise PermissionError("Symlink swap refused on runtime_env.json.")
        cur_sps: List[str] = []
        if rt_file.is_file():
            with contextlib.suppress(Exception):
                doc = json.loads(rt_file.read_text(encoding="utf-8"))
                if verify_gate_artifact(cdir, "runtime-env", doc):
                    cur_sps = [str(x) for x in (doc.get("extra_site_packages") or []) if isinstance(x, str) and x.strip()]
        if sp_str not in cur_sps:
            cur_sps.insert(0, sp_str)
        signed = sign_gate_artifact(cdir, "runtime-env", {
            "schema": RUNTIME_ENV_SCHEMA,
            "extra_site_packages": cur_sps,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _as._atomic_write_text(rt_file, json.dumps(signed, separators=(",", ":"), sort_keys=True))


def install_approved_packages(
    raw_cdir: Path,
    raw_store_root: Path,
    packages: Sequence[str],
    *,
    cancel_ev: Optional[threading.Event] = None,
    heartbeat_cb: Optional[Callable[[], None]] = None,
) -> Path:
    clean_pkgs = [str(p).strip() for p in packages if is_valid_pypi_package_name(str(p).strip())]
    if not clean_pkgs or len(clean_pkgs) != len(packages):
        raise ValueError("Unallowlisted or invalid package specification refused.")

    inj = _INJECTED_PIP_INSTALLER if _in_pytest_runtime() else None
    if callable(inj):
        sp_dir = Path(inj(clean_pkgs, cancel_ev=cancel_ev)).resolve()
    else:
        venv_dir = _anvil_py_env_root()
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        env_lock = venv_dir.parent / "anvil_py_env.lock"
        if _ace._is_lstat_reparse(env_lock):
            raise PermissionError("Symlink refused on anvil_py_env.lock.")
        scratch_cwd = Path(tempfile.mkdtemp(prefix="anvil_pip_cwd_"))
        try:
            clean_env = _ace.build_minimal_cli_env()
            clean_env.update({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "PIP_CONFIG_FILE": os.devnull, "PYTHONUTF8": "1"})
            for pk in _SAFE_PROXY_TLS_ENV_KEYS:
                pv = os.environ.get(pk)
                if isinstance(pv, str) and pv.strip() and not any(c in pv for c in ("\x00", "\r", "\n")):
                    clean_env[pk] = pv.strip()
            with _as.exclusive_file_lock(env_lock):
                venv_py = (venv_dir / "Scripts" / "python.exe") if os.name == "nt" else (venv_dir / "bin" / "python")
                if not venv_py.is_file():
                    rc_v, _, err_v = _run_managed_cmd([sys.executable, "-E", "-m", "venv", str(venv_dir)], cwd=scratch_cwd, env=clean_env, timeout_sec=180.0, cancel_ev=cancel_ev, heartbeat_cb=heartbeat_cb)
                    if rc_v != 0 or not venv_py.is_file():
                        raise RuntimeError(f"Failed to initialize isolated Anvil venv (exit={rc_v}): {err_v[:300]}")
                pip_argv = [str(venv_py), "-E", "-s", "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--only-binary=:all:", "--", *clean_pkgs]
                rc_p, out_p, err_p = _run_managed_cmd(pip_argv, cwd=scratch_cwd, env=clean_env, timeout_sec=PIP_INSTALL_TIMEOUT_SEC, cancel_ev=cancel_ev, heartbeat_cb=heartbeat_cb)
                if rc_p != 0:
                    tail = (err_p or out_p).strip()[-400:]
                    raise RuntimeError(f"pip wheel install failed (exit={rc_p}): {tail}")
                if os.name == "nt":
                    sp_dir = (venv_dir / "Lib" / "site-packages").resolve()
                else:
                    found_sp = list((venv_dir / "lib").glob("python*/site-packages"))
                    if not found_sp:
                        raise RuntimeError("Isolated venv site-packages directory not found.")
                    sp_dir = found_sp[0].resolve()
        finally:
            shutil.rmtree(scratch_cwd, ignore_errors=True)

    _persist_runtime_env_site_packages(raw_cdir, raw_cdir, sp_dir)
    if raw_store_root.resolve() != raw_cdir.resolve():
        _persist_runtime_env_site_packages(raw_cdir, raw_store_root, sp_dir)
    importlib.invalidate_caches()
    return sp_dir


_LOADED_MTIME_NS = Path(__file__).stat().st_mtime_ns
