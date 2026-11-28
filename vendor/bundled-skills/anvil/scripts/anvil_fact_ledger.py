"""Deterministic Pillar-1 Fact Ledger for Unified Anvil Engine:
1. Hub + Paper-Output Provenance Atom Graph (`atom_id = sha256(rel_path)[:16]`), clustering
   repositories into 4..8 human-meaningful architectural modules without 41-card prefix fragmentation
   or 2-blob collapse.
2. Cross-Hierarchy Class Attribute / Subclass Override / Factory Dict / Math-Direction Index.
3. Optimizer `param_groups` (`weight_decay`) + Explicit Penalty Coverage Index (`0` false positives
   on uniformly regularized repos; catches unpenalized structural slopes when sibling parameters are penalized).
4. Kernel Numerical Precondition Facts (`logsumexp`, `slogdet`, `cholesky`, `softmax`, jitter/keepdim).
100% Python stdlib; zero target execution; zero host paths.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import stat
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules",
    ".venv", "venv", "env", ".anvil", ".anchor", "build", "dist", ".tox", ".eggs",
}
_ETL_TOKENS = {"etl", "clean", "ingest", "prep", "prepare", "convert", "raw", "scrape", "parse_raw"}
_SIM_TOKENS = {"sim", "simulate", "simulation", "synthetic", "monte_carlo", "dgp", "benchmark"}
_ESTIMATION_TOKENS = {"adapter", "select", "selection", "cv", "crossval", "train", "fit", "calibrate", "tune", "warm", "infer", "mcmc", "vi"}
_DIAG_TOKENS = {"plot", "fig", "figure", "diag", "diagnostic", "summary", "viz", "chart", "eval", "metric"}
_PENALTY_KEYWORDS = {"penalty", "reg", "regulariz", "l1", "l2", "ridge", "lasso", "weight_decay", "prior"}


def _is_link(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(int(getattr(st, "st_file_attributes", 0) or 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def compute_atom_id(rel_posix: str) -> str:
    norm = rel_posix.replace("\\", "/").strip("/")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _tokenize_ident(s: str) -> List[str]:
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s or "")
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+", s1) if t]


def _extract_str_constants(node: ast.AST) -> List[str]:
    vals: List[str] = []
    for ch in ast.walk(node):
        if isinstance(ch, ast.Constant) and isinstance(ch.value, str) and ch.value.strip():
            vals.append(ch.value.strip())
    return vals


def _scan_workflow_invocations(repo_root: Path, rel_py_set: Set[str]) -> Tuple[List[str], Dict[str, Set[str]]]:
    """Return ordered scripts invoked by `.sh`/`Makefile`/`.ps1` workflows and co-invocation groups."""
    ordered: List[str] = []
    co_groups: Dict[str, Set[str]] = {}
    by_name: Dict[str, List[str]] = {}
    for rp in rel_py_set:
        by_name.setdefault(Path(rp).name, []).append(rp)
    py_cmd_re = re.compile(r"(?:python3?|Rscript)\s+(?:-[A-Za-z0-9_]+\s+)*([A-Za-z0-9_./\\-]+\.(?:py|R))")
    for cur_r, dirs, files in os.walk(repo_root, followlinks=False):
        cur_p = Path(cur_r)
        dirs[:] = [d for d in sorted(dirs) if d not in _SKIP_DIRS and not d.startswith(".") and not _is_link(cur_p / d)]
        for fn in sorted(files):
            low = fn.lower()
            if not (low.endswith((".sh", ".bat", ".ps1")) or low == "makefile"):
                continue
            fp = cur_p / fn
            if _is_link(fp):
                continue
            try:
                with open(fp, "rb") as wfh:
                    txt = wfh.read(524_288).decode("utf-8", errors="replace")
            except OSError:
                continue
            wf_scripts: List[str] = []
            for ln in txt.splitlines():
                s_ln = ln.strip()
                if not s_ln or s_ln.startswith("#"):
                    continue
                for m in py_cmd_re.finditer(s_ln):
                    cand = re.sub(r"^(?:\./)+", "", m.group(1).replace("\\", "/"))
                    if ".." in Path(cand).parts:
                        continue
                    leaf_hits = by_name.get(Path(cand).name, [])
                    resolved_rel = cand if cand in rel_py_set else (leaf_hits[0] if len(leaf_hits) == 1 else "")
                    if resolved_rel:
                        if resolved_rel not in ordered:
                            ordered.append(resolved_rel)
                        if resolved_rel not in wf_scripts:
                            wf_scripts.append(resolved_rel)
            if wf_scripts:
                co_groups[fp.relative_to(repo_root).as_posix()] = set(wf_scripts)
    return ordered, co_groups


def _analyze_python_file(rel: str, src: str, rel_py_map: Dict[str, str]) -> Dict[str, Any]:
    atom_id = compute_atom_id(rel)
    info: Dict[str, Any] = {
        "file": rel,
        "atom_id": atom_id,
        "imports_local": [],
        "classes": [],
        "functions": [],
        "output_artifacts": [],
        "cli_flags": [],
        "factory_dicts": [],
        "optimizer_calls": [],
        "penalty_terms": [],
        "kernel_ops": [],
        "has_main_guard": False,
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(src, filename=rel)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return info

    cur_pkg_parts = list(Path(rel).parts[:-1])

    def _resolve_mod(mod_name: Optional[str], level: int) -> Optional[str]:
        base_parts = cur_pkg_parts[: max(0, len(cur_pkg_parts) - (level - 1))] if level > 0 else cur_pkg_parts
        mparts = [p for p in (mod_name or "").split(".") if p]
        cand_seq = ([*base_parts, *mparts], mparts) if base_parts else (mparts,)
        for cand_parts in cand_seq:
            if not cand_parts:
                continue
            c_py = "/".join(cand_parts) + ".py"
            c_init = "/".join(cand_parts) + "/__init__.py"
            if c_py in rel_py_map:
                return rel_py_map[c_py]
            if c_init in rel_py_map:
                return rel_py_map[c_init]
            leaf = cand_parts[-1] + ".py"
            if len(cand_parts) == 1 and leaf in rel_py_map:
                return rel_py_map[leaf]
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                hit = _resolve_mod(al.name, 0)
                if hit and hit != rel and hit not in info["imports_local"]:
                    info["imports_local"].append(hit)
        elif isinstance(node, ast.ImportFrom):
            hit = _resolve_mod(node.module, int(node.level or 0))
            if hit and hit != rel and hit not in info["imports_local"]:
                info["imports_local"].append(hit)
            for al in node.names:
                sub_hit = _resolve_mod(f"{node.module}.{al.name}" if node.module else al.name, int(node.level or 0))
                if sub_hit and sub_hit != rel and sub_hit not in info["imports_local"]:
                    info["imports_local"].append(sub_hit)
        elif isinstance(node, ast.If):
            try:
                cond_s = ast.unparse(node.test)
                if "__name__" in cond_s and "__main__" in cond_s:
                    info["has_main_guard"] = True
            except Exception:
                pass
        elif isinstance(node, ast.Call):
            fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            low_fn = fn_name.lower()
            if low_fn in {"to_csv", "to_latex", "to_excel", "to_parquet", "savefig", "write_text", "save", "dump"}:
                for sc in _extract_str_constants(node):
                    if any(ext in sc.lower() for ext in (".tex", ".csv", ".pdf", ".png", ".svg", ".pt", ".pth", ".npz", ".json", "table", "tab", "fig")):
                        if sc not in info["output_artifacts"]:
                            info["output_artifacts"].append(sc[:160])
            elif low_fn == "open" and len(node.args) >= 2:
                modes = _extract_str_constants(node.args[1])
                if any("w" in m or "a" in m for m in modes):
                    for sc in _extract_str_constants(node.args[0]):
                        if sc not in info["output_artifacts"]:
                            info["output_artifacts"].append(sc[:160])
            elif low_fn == "add_argument" and node.args:
                for sc in _extract_str_constants(node.args[0]):
                    if sc.startswith("-") and sc not in info["cli_flags"]:
                        info["cli_flags"].append(sc)
            elif fn_name in {"Adam", "AdamW", "SGD", "RMSprop", "LBFGS"}:
                wd_global = 0.0
                for kw in node.keywords:
                    if kw.arg == "weight_decay" and kw.value is not None:
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                            wd_global = float(kw.value.value)
                        elif not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                            wd_global = 1.0
                group_specs: List[Dict[str, Any]] = []
                if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    for elt in node.args[0].elts:
                        if isinstance(elt, ast.Dict):
                            g_params = ""
                            g_wd = wd_global
                            for k_n, v_n in zip(elt.keys, elt.values):
                                if isinstance(k_n, ast.Constant) and k_n.value == "params" and v_n is not None:
                                    g_params = ast.unparse(v_n)[:160]
                                elif isinstance(k_n, ast.Constant) and k_n.value == "weight_decay" and v_n is not None:
                                    if isinstance(v_n, ast.Constant) and isinstance(v_n.value, (int, float)):
                                        g_wd = float(v_n.value)
                                    elif not (isinstance(v_n, ast.Constant) and v_n.value is None):
                                        g_wd = 1.0
                            group_specs.append({"params_expr": g_params, "weight_decay": g_wd})
                info["optimizer_calls"].append({
                    "optimizer": fn_name,
                    "line": int(getattr(node, "lineno", 1)),
                    "global_weight_decay": wd_global,
                    "param_groups": group_specs,
                    "raw_args": ast.unparse(node.args[0])[:180] if node.args else "",
                })
            elif low_fn in {"logsumexp", "softmax", "log_softmax", "slogdet", "logdet", "cholesky", "solve", "triangular_solve", "clamp"}:
                has_keepdim = any(kw.arg == "keepdim" and isinstance(kw.value, ast.Constant) and bool(kw.value.value) for kw in node.keywords)
                info["kernel_ops"].append({
                    "op": low_fn,
                    "line": int(getattr(node, "lineno", 1)),
                    "keepdim": has_keepdim,
                    "expr": ast.unparse(node)[:160],
                })

    for st in tree.body:
        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Dict):
            keys_str = [k.value for k in st.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if keys_str and len(keys_str) == len(st.value.keys):
                vals_str = [ast.unparse(v)[:120] for v in st.value.values if v is not None]
                tname = st.targets[0].id if isinstance(st.targets[0], ast.Name) else ast.unparse(st.targets[0])[:60]
                info["factory_dicts"].append({
                    "symbol": f"{rel}:{tname}",
                    "line": int(getattr(st, "lineno", 1)),
                    "entries": dict(zip(keys_str, vals_str)),
                })
        elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pen_refs = _extract_penalty_exprs(st, f"{rel}:{st.name}")
            info["penalty_terms"].extend(pen_refs)
            fn_calls = sorted({(n.func.id if isinstance(n.func, ast.Name) else n.func.attr) for n in ast.walk(st) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))})
            fn_toks = set(_tokenize_ident(st.name))
            low_nm = st.name.lower()
            is_plumbing_fn = low_nm in {"_parse_args", "parse_args", "main", "smoke", "write_report", "load_comparisons", "predictive_table", "build_tables"} or low_nm.startswith(("format_", "validate_", "summarize_", "information_", "build_info", "build_standardized"))
            warm_call_hit = bool(set(fn_calls) & {"load_state_dict", "load_warm", "warm_start", "select_price_adapter", "select_adapter", "unstick_inner_layer", "pretrain"})
            warm_name_hit = ("warm" in fn_toks and "warmup" not in fn_toks) or "pretrain" in fn_toks or ("adapter" in fn_toks and bool(fn_toks & {"select", "selection", "fit", "train", "price", "unstick", "warm"}))
            info["functions"].append({
                "symbol_id": f"{rel}:{st.name}",
                "name": st.name,
                "start_line": int(getattr(st, "lineno", 1)),
                "end_line": int(getattr(st, "end_lineno", st.lineno) or st.lineno),
                "args": [a.arg for a in st.args.args],
                "has_loop": any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(st)),
                "calls": fn_calls[:25],
                "summary_sig": f"def {st.name}({', '.join(a.arg for a in st.args.args[:6])})",
                "mentions_warm_start": (not is_plumbing_fn) and (warm_call_hit or warm_name_hit),
            })
        elif isinstance(st, ast.ClassDef):
            bases = [ast.unparse(b) for b in st.bases]
            attrs: Dict[str, List[Dict[str, Any]]] = {}
            param_attrs: List[Dict[str, Any]] = []
            methods: List[Dict[str, Any]] = []
            for mst in st.body:
                if isinstance(mst, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_sid = f"{rel}:{st.name}.{mst.name}"
                    info["penalty_terms"].extend(_extract_penalty_exprs(mst, m_sid))
                    _collect_self_attrs(mst.body, mst.name, None, attrs, param_attrs)
                    has_seq_loop = any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(mst))
                    methods.append({
                        "symbol_id": m_sid,
                        "name": mst.name,
                        "start_line": int(getattr(mst, "lineno", 1)),
                        "end_line": int(getattr(mst, "end_lineno", mst.lineno) or mst.lineno),
                        "has_sequential_loop": has_seq_loop,
                        "calls_super": "super(" in ast.unparse(mst),
                    })
            info["classes"].append({
                "symbol_id": f"{rel}:{st.name}",
                "name": st.name,
                "bases": bases,
                "start_line": int(getattr(st, "lineno", 1)),
                "end_line": int(getattr(st, "end_lineno", st.lineno) or st.lineno),
                "self_attrs": attrs,
                "param_attrs": param_attrs,
                "methods": methods,
            })
    return info


def _collect_self_attrs(
    stmts: Sequence[ast.stmt],
    method_name: str,
    branch_cond: Optional[str],
    out_attrs: Dict[str, List[Dict[str, Any]]],
    param_attrs: List[Dict[str, Any]],
) -> None:
    for st in stmts:
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            val_node = st.value
            rhs = ast.unparse(val_node)[:180] if val_node is not None else ""
            for tg in targets:
                if isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id == "self":
                    rec = {
                        "attr": tg.attr,
                        "method": method_name,
                        "line": int(getattr(st, "lineno", 1)),
                        "end_line": int(getattr(st, "end_lineno", st.lineno) or st.lineno),
                        "rhs": rhs,
                        "branch": branch_cond,
                        "unconditional": branch_cond is None,
                    }
                    out_attrs.setdefault(tg.attr, []).append(rec)
                    if any(pk in rhs for pk in ("Parameter(", "Linear(", "Sequential(", "ModuleList(", "ParameterList(", "Embedding(", "zeros(", "randn(")):
                        param_attrs.append({"attr": tg.attr, "line": rec["line"], "rhs": rhs})
        elif isinstance(st, ast.If):
            cond_txt = ast.unparse(st.test)[:120]
            _collect_self_attrs(st.body, method_name, cond_txt if branch_cond is None else f"{branch_cond} and {cond_txt}", out_attrs, param_attrs)
            if st.orelse:
                else_c = f"not ({cond_txt})" if branch_cond is None else f"{branch_cond} and not ({cond_txt})"
                _collect_self_attrs(st.orelse, method_name, else_c, out_attrs, param_attrs)
        elif isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            _collect_self_attrs(st.body, method_name, branch_cond, out_attrs, param_attrs)
        elif isinstance(st, ast.Try):
            _collect_self_attrs(st.body, method_name, branch_cond, out_attrs, param_attrs)


def _extract_penalty_exprs(fn_node: ast.AST, owner_sid: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for st in ast.walk(fn_node):
        if isinstance(st, (ast.Assign, ast.AugAssign, ast.Return)):
            expr_txt = ast.unparse(st)
            low = expr_txt.lower()
            is_pen_lhs = isinstance(st, ast.Assign) and any(any(pk in t for t in _tokenize_ident(ast.unparse(tg))) for pk in _PENALTY_KEYWORDS for tg in st.targets)
            has_norm_pow = ("** 2" in expr_txt or "**2" in expr_txt or "norm(" in low or ".pow(2" in low or "abs(" in low) and ("self." in expr_txt or "weight" in low or "param" in low or is_pen_lhs)
            if is_pen_lhs or (has_norm_pow and any(pk in low for pk in ("loss", "pen", "reg", "l1", "l2", "prior", "lambda", "alpha", "wd"))):
                self_refs = re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)", expr_txt)
                hits.append({
                    "owner": owner_sid,
                    "line": int(getattr(st, "lineno", 1)),
                    "referenced_attrs": sorted(set(self_refs)),
                    "expr": expr_txt[:200],
                })
    return hits


def _detect_hierarchy_and_regularizer_anomalies(file_infos: List[Dict[str, Any]]) -> Dict[str, Any]:
    cls_by_short: Dict[str, List[Dict[str, Any]]] = {}
    cls_by_sid: Dict[str, Dict[str, Any]] = {}
    for fi in file_infos:
        for c in fi["classes"]:
            cls_by_sid[c["symbol_id"]] = c
            cls_by_short.setdefault(c["name"], []).append(c)

    attr_overrides: List[Dict[str, Any]] = []
    for c in cls_by_sid.values():
        for raw_b in c["bases"]:
            b_short = raw_b.split(".")[-1].strip()
            for base_c in cls_by_short.get(b_short, []):
                if base_c["symbol_id"] == c["symbol_id"]:
                    continue
                for attr_nm, sub_assigns in c["self_attrs"].items():
                    base_assigns = [a for a in base_c["self_attrs"].get(attr_nm, []) if a["method"] == "__init__"]
                    sub_init = [a for a in sub_assigns if a["method"] == "__init__"]
                    if base_assigns and sub_init:
                        b0 = base_assigns[0]
                        b_spans = [(int(ba["line"]), int(ba.get("end_line", ba["line"]))) for ba in base_assigns]
                        base_rhses = {ba["rhs"] for ba in base_assigns}
                        attr_overrides.append({
                            "attribute": f"self.{attr_nm}",
                            "base_class": base_c["symbol_id"],
                            "base_line": b0["line"],
                            "base_end_line": max(e for (_s, e) in b_spans),
                            "base_spans": b_spans,
                            "base_rhs": b0["rhs"],
                            "subclass": c["symbol_id"],
                            "subclass_lines": [s["line"] for s in sub_init],
                            "subclass_rhs": [s["rhs"] for s in sub_init],
                            "subclass_branches": [s["branch"] for s in sub_init if s["branch"]],
                            "base_allocation_overridden": all(s["rhs"] not in base_rhses for s in sub_init),
                        })

    unpenalized_params: List[Dict[str, Any]] = []
    penalties_by_file: Dict[str, List[Dict[str, Any]]] = {fi["file"]: fi["penalty_terms"] for fi in file_infos}
    opts_by_file: Dict[str, List[Dict[str, Any]]] = {fi["file"]: fi["optimizer_calls"] for fi in file_infos}
    for fi in file_infos:
        f_pens = penalties_by_file.get(fi["file"], [])
        f_opts = opts_by_file.get(fi["file"], [])
        has_uniform_wd = any(op["global_weight_decay"] > 0 and not op["param_groups"] for op in f_opts) and not any(op["param_groups"] for op in f_opts)
        if has_uniform_wd:
            continue
        penalized_attrs: Set[str] = {a for p in f_pens for a in p["referenced_attrs"]}
        zero_wd_exprs = [g["params_expr"] for op in f_opts for g in op["param_groups"] if g["weight_decay"] == 0.0]
        pos_wd_exprs = [g["params_expr"] for op in f_opts for g in op["param_groups"] if g["weight_decay"] > 0.0]
        for c in fi["classes"]:
            learnable = [pa for pa in c["param_attrs"] if any(pk in pa["rhs"] for pk in ("Parameter(", "Linear(", "Sequential("))]
            if len(learnable) < 2:
                continue
            cls_penalized = [
                pa for pa in learnable
                if pa["attr"] in penalized_attrs or any(re.search(rf"\b{re.escape(pa['attr'])}\b", pe) for pe in pos_wd_exprs)
            ]
            if not cls_penalized:
                continue
            for pa in learnable:
                if pa["attr"] not in penalized_attrs and not any(re.search(rf"\b{re.escape(pa['attr'])}\b", pe) for pe in pos_wd_exprs):
                    if any(tok in pa["attr"].lower() for tok in ("bias", "intercept", "norm", "bn", "ln")):
                        continue
                    unpenalized_params.append({
                        "class_symbol": c["symbol_id"],
                        "param_attr": f"self.{pa['attr']}",
                        "line": pa["line"],
                        "rhs": pa["rhs"],
                        "penalized_sibling_attrs": [f"self.{x['attr']}" for x in cls_penalized],
                        "zero_wd_groups": zero_wd_exprs[:4],
                    })
    return {"subclass_attribute_overrides": attr_overrides, "selective_unpenalized_parameters": unpenalized_params}


def cluster_repository_modules(
    repo_root: Path,
    prod_files: Sequence[Path],
    test_files: Sequence[Path],
    *,
    entrypoints: Optional[Sequence[str]] = None,
    workflow_targets_by_file: Optional[Dict[str, List[str]]] = None,
    paper_artifacts: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Partition repository files via Hub + Paper-Output Provenance Atom Graph into 4..8
    human-meaningful primary modules + Tests + at most 1 Legacy container (`0` 41-card explosion).
    """
    prod_files = list(prod_files)[:2000]
    test_files = list(test_files)[:2000]
    rel_prod = [fp.relative_to(repo_root).as_posix() for fp in prod_files]
    rel_test = [fp.relative_to(repo_root).as_posix() for fp in test_files]
    rel_py_set = set(rel_prod)
    leaf_counts: Dict[str, int] = {}
    for r in rel_prod:
        leaf_counts[Path(r).name] = leaf_counts.get(Path(r).name, 0) + 1
    by_leaf = {Path(r).name: r for r in rel_prod if leaf_counts.get(Path(r).name) == 1}
    rel_lookup = {**by_leaf, **{r: r for r in rel_prod}}

    file_infos: Dict[str, Dict[str, Any]] = {}
    imported_by_count: Dict[str, int] = {r: 0 for r in rel_prod}
    for fp, rel in zip(prod_files, rel_prod):
        src = ""
        if fp.suffix.lower() == ".py":
            try:
                with open(fp, "rb") as sfh:
                    src = sfh.read(2_097_152).decode("utf-8-sig", errors="replace")
            except OSError:
                src = ""
        try:
            fi = _analyze_python_file(rel, src, rel_lookup)
        except (RecursionError, MemoryError):
            fi = _analyze_python_file(rel, "", rel_lookup)
        file_infos[rel] = fi
    for rel, fi in file_infos.items():
        for imp_tgt in fi["imports_local"]:
            if imp_tgt in imported_by_count:
                imported_by_count[imp_tgt] += 1

    wf_ordered, _ = _scan_workflow_invocations(repo_root, rel_py_set)
    wf_targets = dict(workflow_targets_by_file or {})
    paper_art_stems = {Path(a).stem.lower() for a in (paper_artifacts or []) if a}
    ep_clean = {str(e).split(":", 1)[0].replace("\\", "/").strip("/") for e in (entrypoints or []) if str(e).strip()}

    provenance_eps: Set[str] = set(ep_clean) | set(wf_ordered) | set(wf_targets.keys())
    for rel, fi in file_infos.items():
        for out_a in fi["output_artifacts"]:
            out_stem = Path(out_a).stem.lower()
            if (paper_art_stems and out_stem in paper_art_stems) or any(k in out_a.lower() for k in ("table", "manuscript", "paper", "figure")):
                provenance_eps.add(rel)

    reached_closure: Set[str] = set()
    stack = list(provenance_eps) if provenance_eps else list(rel_prod)
    while stack:
        cur = stack.pop()
        if cur in reached_closure or cur not in file_infos:
            continue
        reached_closure.add(cur)
        for nxt in file_infos[cur]["imports_local"]:
            if nxt not in reached_closure:
                stack.append(nxt)

    reached_hubs = {r for r in reached_closure if imported_by_count.get(r, 0) >= 2}
    est_bridge_files: List[str] = [
        r for r in rel_prod
        if r not in reached_closure
        and (set(_tokenize_ident(Path(r).stem)) & _ESTIMATION_TOKENS)
        and not (set(_tokenize_ident(Path(r).stem)) & (_ETL_TOKENS | _SIM_TOKENS | {"sandbox", "legacy", "old", "deprecated", "scratch", "test"}))
        and len(set(file_infos[r]["imports_local"]) & reached_hubs) >= 2
    ][:8]
    reached_closure |= set(est_bridge_files)

    buckets: Dict[str, Dict[str, Any]] = {}

    def _put(slug: str, title: str, role: str, status: str, rel: str) -> None:
        b = buckets.setdefault(slug, {"slug": slug, "title": title, "role": role, "default_status": status, "files": []})
        if rel not in b["files"]:
            b["files"].append(rel)

    for rel in rel_prod:
        fi = file_infos[rel]
        toks = set(_tokenize_ident(Path(rel).stem)) | {pt.lower() for pt in Path(rel).parts[:-1]}
        in_deg = imported_by_count.get(rel, 0)
        is_reached = rel in reached_closure
        is_hub = in_deg >= 2 or (is_reached and in_deg >= 1 and bool(fi["classes"] or len(fi["functions"]) >= 2))

        if any(pt.lower() in {"archive", "old", "deprecated", "backup", "legacy", "scratch"} for pt in Path(rel).parts):
            _put("legacy_exploratory", "Unscoped Legacy & Exploratory Scripts", "unscoped_plumbing", "unscoped_plumbing", rel)
        elif (toks & _ETL_TOKENS) and rel not in wf_targets and not is_hub:
            _put("data_prep_etl", "Data Preparation & Feature Engineering", "data_etl", "unscoped_plumbing", rel)
        elif is_hub and any(c["param_attrs"] or c["methods"] for c in fi["classes"]) and not (toks & _ESTIMATION_TOKENS):
            _put("core_estimator", "Core Mathematical Estimator & Model Kernel", "core_estimator", "in_scope", rel)
        elif is_hub and (toks & _ESTIMATION_TOKENS or any(fn["mentions_warm_start"] for fn in fi["functions"])):
            _put("estimation_selection", "Model Selection, Warm-Start & Training Routines", "core_estimator", "in_scope", rel)
        elif is_hub:
            _put("shared_utilities", "Shared Inference & Data Utilities", "core_estimator", "in_scope", rel)
        elif rel in wf_targets or (rel in provenance_eps and not (toks & _SIM_TOKENS)):
            _put("table_replicators", "Primary Paper Table & Empirical Replicators", "table_replicators", "in_scope", rel)
        elif toks & _SIM_TOKENS:
            _put("monte_carlo_simulations", "Monte Carlo Synthetic DGP & Simulations", "simulation", "in_scope" if is_reached and not wf_targets else "available", rel)
        elif is_reached and (toks & _DIAG_TOKENS):
            _put("diagnostics_figures", "Diagnostics, Evaluation & Figure Generators", "table_replicators", "in_scope", rel)
        elif is_reached:
            _put("estimation_selection", "Model Selection, Warm-Start & Training Routines", "core_estimator", "in_scope", rel)
        else:
            _put("legacy_exploratory", "Unscoped Legacy & Exploratory Scripts", "unscoped_plumbing", "unscoped_plumbing", rel)

    if len(buckets.get("table_replicators", {}).get("files", [])) > 18:
        rep_files = list(buckets.pop("table_replicators")["files"])
        emp_f = [f for f in rep_files if not (set(_tokenize_ident(Path(f).stem)) & _DIAG_TOKENS)]
        fig_f = [f for f in rep_files if f not in emp_f]
        for f in emp_f:
            _put("table_replicators", "Primary Paper Table & Empirical Replicators", "table_replicators", "in_scope", f)
        for f in fig_f:
            _put("diagnostics_figures", "Diagnostics, Evaluation & Figure Generators", "table_replicators", "in_scope", f)

    for trel in rel_test:
        _put("tests_and_historical", "Unit Tests & Verification Suite", "tests_historical", "unscoped_plumbing", trel)

    anomalies = _detect_hierarchy_and_regularizer_anomalies(list(file_infos.values()))
    return {
        "buckets": buckets,
        "file_infos": file_infos,
        "imported_by_count": imported_by_count,
        "workflow_ordered_entrypoints": wf_ordered,
        "provenance_entrypoints": sorted(provenance_eps),
        "reached_files": sorted(reached_closure),
        "anomalies": anomalies,
    }


def synthesize_deterministic_pass2(
    scope_sha256: str,
    epoch: int,
    scope_files: Sequence[str],
    entrypoints: Sequence[str],
    equations: Sequence[Dict[str, Any]],
    bound_eqs: Sequence[Dict[str, Any]],
    symbol_slice: Dict[str, Any],
    cluster_info: Dict[str, Any],
    *,
    slice_truncated: bool = False,
    pass2_schema: str = "anvil-comprehension-pass2/v1",
) -> Dict[str, Any]:
    """Deterministic AST + LaTeX + Fact-Ledger synthesis baseline (100% grounded, `CLAIMED`)."""
    file_infos = cluster_info.get("file_infos") or {}
    anomalies = cluster_info.get("anomalies") or {}
    overrides = list(anomalies.get("subclass_attribute_overrides") or [])
    unpenalized = list(anomalies.get("selective_unpenalized_parameters") or [])

    ingest_f = [f for f in scope_files if any(k in f.lower() for k in ("data", "util", "load", "prep", "feature"))]
    select_f = [f for f in scope_files if any(k in f.lower() for k in ("select", "adapter", "warm", "cv", "init", "config"))]
    kernel_f = [f for f in scope_files if f not in ingest_f and f not in select_f and bool((file_infos.get(f) or {}).get("classes"))]
    train_f = [f for f in scope_files if f not in ingest_f and f not in kernel_f and bool((file_infos.get(f) or {}).get("optimizer_calls") or (file_infos.get(f) or {}).get("functions"))]
    rep_f = [f for f in entrypoints if f in scope_files] or [f for f in scope_files if f not in kernel_f][:2]

    def _pick(cands: List[str], fb_idx: int) -> List[str]:
        return cands[:4] if cands else ([scope_files[min(fb_idx, len(scope_files) - 1)]] if scope_files else [])

    raw_stages = [
        ("Data & Covariate Conditioning", "Tensor assembly, scaling, and conditioning inputs", "ingest", _pick(ingest_f, 0)),
        ("Warm-Start & Architecture Setup", "Model initialization, hyperparameter/adapter setup, and hierarchy wiring", "prep", _pick(select_f or kernel_f, 0)),
        ("Core Mathematical Likelihood & Transform", "Forward density/choice kernel, Jacobian or log-sum-exp evaluation", "kernel", _pick(kernel_f or train_f, min(1, max(0, len(scope_files) - 1)))),
        ("Objective Regularization & Optimization", "Loss aggregation, parameter penalties, and gradient updates", "optimize", _pick(train_f or kernel_f, min(2, max(0, len(scope_files) - 1)))),
        ("Posterior / Counterfactual & Table Output", "Out-of-sample metrics, simulation draws, and manuscript table export", "output", _pick(rep_f, max(0, len(scope_files) - 1))),
    ]

    overridden_base_sids = {str(ov.get("base_class") or "") for ov in overrides if ov.get("base_allocation_overridden")}
    l1_stages: List[Dict[str, Any]] = []
    triptychs: List[Dict[str, Any]] = []
    story_diffs: List[Dict[str, Any]] = []
    for idx_s, (stitle, ssub, skind, sfiles) in enumerate(raw_stages, start=1):
        sid, nid = f"S{idx_s}", f"N{idx_s}"
        sfiles = [f for f in sfiles if f] or list(scope_files[:1])
        primary_f = sfiles[0] if sfiles else ""
        fi = file_infos.get(primary_f) or {}
        cls_units = sorted(fi.get("classes", []), key=lambda cu: 1 if str(cu.get("symbol_id") or "") in overridden_base_sids else 0)
        cand_units = [*cls_units, *fi.get("functions", [])] or [{"symbol_id": f"{primary_f}:<module>", "name": Path(primary_f or "step").stem, "start_line": 1, "end_line": 10}]
        syms, l2_steps = [], []
        for u_idx, unit in enumerate(cand_units[:4], start=1):
            u_sid = str(unit.get("symbol_id") or f"{primary_f}:{unit.get('name', 'step')}")
            u_sl, u_el = int(unit.get("start_line") or 1), int(unit.get("end_line") or unit.get("start_line") or 1)
            u_nm = str(unit.get("name") or Path(primary_f or "step").stem)
            syms.append(u_sid)
            ref_obj = {"kind": "code", "target": u_sid, "start_line": u_sl, "end_line": u_el, "token_hint": u_nm}
            l2_steps.append({
                "step_id": f"{sid}.{u_idx}", "title": u_nm.replace("_", " "), "symbol": u_sid, "file": primary_f,
                "start_line": u_sl, "end_line": u_el, "summary": f"Executes {u_nm} in {primary_f} (L{u_sl}-L{u_el}).",
                "math_tex": "", "wall_share_pct": "unmeasured", "rung": "CLAIMED", "evidence_refs": [ref_obj],
            })
        top_ref = l2_steps[0]["evidence_refs"][0]
        l1_stages.append({
            "stage_id": sid, "title": stitle, "subtitle": ssub, "kind": skind, "files": sfiles, "symbols": syms,
            "inputs": ["raw_tensors"] if idx_s == 1 else [f"S{idx_s - 1}_state"], "outputs": [f"{sid}_state"],
            "eq_labels": [], "refactor_target_id": nid, "wall_share_pct": "unmeasured",
            "l2_steps": l2_steps, "rung": "CLAIMED", "evidence_refs": [top_ref],
        })
        triptychs.append({
            "stage_id": sid, "chapter_title": f"{sid} · {stitle}",
            "why_needed": f"Establishes the {skind} contract required before downstream estimation.",
            "transform_mechanism": f"Implemented across {', '.join(Path(x).name for x in sfiles)} via {', '.join(s.split(':')[-1] for s in syms[:2])}.",
            "downstream_handoff": f"Passes structured state from {sid} into {'S' + str(idx_s + 1) if idx_s < len(raw_stages) else 'manuscript artifacts'}.",
            "math_tex": "", "rung": "CLAIMED", "evidence_refs": [top_ref],
        })
        story_diffs.append({
            "from_stage_id": sid, "to_node_id": "NULL" if skind == "output" and len(raw_stages) > 4 else nid,
            "today_title": f"{sid}: {stitle}", "today_detail": f"Interleaves computation and script state in {primary_f}.",
            "pure_core_title": f"{nid}: Pure {stitle}", "pure_core_detail": "Explicit immutable tensor inputs/outputs with I/O isolated at boundary.",
            "disposition": "isolate_io_shell" if skind in ("ingest", "output") else "extract_pure_core",
            "rung": "CLAIMED", "evidence_refs": [top_ref],
        })

    edges = [{"from": f"S{i}", "to": f"S{i + 1}", "label": f"S{i} → S{i + 1}", "kind": "forward", "witnessed": False} for i in range(1, len(l1_stages))]
    if len(l1_stages) >= 4:
        edges.append({"from": "S4", "to": "S3", "label": "gradient / epoch step", "kind": "feedback_loop", "witnessed": False})

    paper_rows, pass2a, pass2b, preconds, refactors = [], [], [], [], []
    for idx_e, eq in enumerate(bound_eqs[:14], start=1):
        c_file = str(eq.get("bound_file") or (scope_files[0] if scope_files else ""))
        c_sym = str(eq.get("bound_symbol") or f"{c_file}:<unbound>")
        m_top = (eq.get("matched_symbols") or [{}])[0]
        s_ln, e_ln = int(m_top.get("start_line") or 1), int(m_top.get("end_line") or m_top.get("start_line") or 1)
        eq_lbl = str(eq.get("label") or f"eq:{idx_e}")
        p_ref = {"kind": "paper", "target": eq_lbl, "eq_label": eq_lbl}
        c_ref = {"kind": "code", "target": c_sym, "start_line": s_ln, "end_line": e_ln, "token_hint": c_sym.split(".")[-1].split(":")[-1]}
        verdict = "STATIC_MATCH" if eq.get("status") == "bound" else "UNBOUND_IN_SLICE"
        paper_rows.append({
            "row_id": f"prow-{idx_e}", "stage_id": "S3", "eq_label": eq_lbl, "eq_number": str(eq.get("eq_number") or ""),
            "section": str(eq.get("section") or "Main"), "paper_tex": str(eq.get("expanded_latex") or eq.get("raw_latex") or "")[:1400],
            "mathml": str(eq.get("mathml") or ""), "mathml_mode": str(eq.get("mathml_mode") or "MATHML_CORE"),
            "code_symbol": c_sym, "code_file": c_file, "start_line": s_ln, "end_line": e_ln, "verdict": verdict,
            "rationale": f"Bound to active symbol {c_sym} (L{s_ln}-L{e_ln})." if verdict == "STATIC_MATCH" else "No active symbol in the locked entrypoint slice matched this manuscript equation.",
            "rung": "CLAIMED", "evidence_refs": [p_ref, c_ref] if verdict == "STATIC_MATCH" else [p_ref],
        })

    for ov_i, ov in enumerate(overrides[:6], start=1):
        if not ov.get("base_allocation_overridden"):
            continue
        sub_sid, base_sid = str(ov["subclass"]), str(ov["base_class"])
        sub_f, sub_cls = sub_sid.split(":", 1)
        _, base_cls = base_sid.split(":", 1)
        sub_ln, base_ln = int((ov.get("subclass_lines") or [1])[0]), int(ov.get("base_line") or 1)
        sub_rhs, base_rhs = str((ov.get("subclass_rhs") or [""])[0]), str(ov.get("base_rhs") or "")
        sub_ref = {"kind": "code", "target": sub_sid, "start_line": sub_ln, "end_line": sub_ln, "token_hint": str(ov["attribute"])}
        matched_eq = next(
            (
                eq_m for eq_m in bound_eqs
                if str(eq_m.get("bound_symbol") or "").startswith((sub_sid, base_sid))
                or any(str(ms.get("id") or ms.get("symbol_id") or "").startswith((sub_sid, base_sid)) for ms in (eq_m.get("matched_symbols") or []) if isinstance(ms, dict))
            ),
            None,
        )
        m_lbl = str(matched_eq.get("label") or "") if matched_eq else ""
        m_tex = str(matched_eq.get("expanded_latex") or matched_eq.get("raw_latex") or "")[:600] if matched_eq else ""
        ov_refs = [sub_ref, {"kind": "paper", "target": m_lbl, "eq_label": m_lbl}] if m_lbl else [sub_ref]
        pass2a.append({
            "finding_id": f"r2a-override-{ov_i}",
            "direction": "paper_to_code" if m_lbl else "subclass_override",
            "severity": "blocker", "verdict": "DIVERGENCE_SUSPECTED",
            "title": f"Subclass {sub_cls} overrides {ov['attribute']} ({base_rhs.split('(')[0]} → {sub_rhs.split('(')[0]})",
            "eq_label": m_lbl, "paper_tex": m_tex,
            "paper_claim": (
                f"Equation `{m_lbl}` binds to `{base_cls}` (L{base_ln}: `{base_rhs}`)."
                if m_lbl
                else f"No numbered manuscript equation lexically bound; base `{base_cls}` (L{base_ln}) allocates `{base_rhs}`."
            ),
            "code_symbol": sub_sid, "code_reality": f"Executed subclass `{sub_sid}` (L{sub_ln}) overrides `{ov['attribute']} = {sub_rhs}` (base L{base_ln} shadowed).",
            "impact": "Evaluating density vs sampling direction or Jacobian cost differs materially between base and subclass transforms.",
            "slice_truncated": slice_truncated, "rung": "CLAIMED", "evidence_refs": ov_refs,
        })
        if m_lbl:
            for prow in paper_rows:
                if prow.get("eq_label") == m_lbl:
                    prow["verdict"], prow["rationale"] = "DIVERGENCE_SUSPECTED", pass2a[-1]["code_reality"]
                    prow["evidence_refs"] = [*prow.get("evidence_refs", []), sub_ref]
        refactors.append({
            "refactor_id": f"ref-div-override-{ov_i}", "title": f"Reconcile {sub_cls} `{ov['attribute']}` parameterization vs manuscript formulation",
            "category": "paper_code_reconciliation", "direction": "needs_author_intent_decision", "target_file": sub_f, "target_symbol": sub_sid,
            "summary": f"Align manuscript equation prose or `{sub_sid}` (`{sub_rhs}`) once author confirms intended direction.",
            "wrong_side_warning": f"BLOCKED: Auto-rewriting `{sub_cls}` back to `{base_rhs.split('(')[0]}` without author confirmation risks inverting the intended estimator architecture.",
            "rung": "CLAIMED", "evidence_refs": [sub_ref],
        })

    for sf in scope_files:
        for fn in (file_infos.get(sf) or {}).get("functions") or []:
            if fn.get("mentions_warm_start"):
                pass2b.append({
                    "finding_id": f"r2b-warm-{len(pass2b) + 1}", "direction": "code_to_paper", "severity": "major", "verdict": "UNDOCUMENTED_CODE_BEHAVIOR",
                    "title": f"Executed warm-start / adapter selection routine `{fn['name']}` in `{Path(sf).name}`",
                    "eq_label": "", "paper_tex": "",
                    "paper_claim": "Manuscript estimation prose describes direct single-stage optimization unless warm-start selection is explicitly documented.",
                    "code_symbol": fn["symbol_id"], "code_reality": f"`{fn['symbol_id']}` (L{fn['start_line']}-L{fn['end_line']}) performs staged warm-start / adapter selection prior to final fit.",
                    "impact": "Staged initialization alters local-optima basin selection and effective regularization path during replication.",
                    "slice_truncated": slice_truncated, "rung": "CLAIMED",
                    "evidence_refs": [{"kind": "code", "target": fn["symbol_id"], "start_line": fn["start_line"], "end_line": fn["end_line"], "token_hint": fn["name"]}],
                })

    for up_i, up in enumerate(unpenalized[:6], start=1):
        c_sid = str(up["class_symbol"])
        c_f, p_ln = c_sid.split(":", 1)[0], int(up["line"])
        pass2b.append({
            "finding_id": f"r2b-unpen-{up_i}", "direction": "code_to_paper", "severity": "major", "verdict": "UNDOCUMENTED_CODE_BEHAVIOR",
            "title": f"Selective regularization omits `{up['param_attr']}` in `{c_sid.split(':')[-1]}`",
            "eq_label": "", "paper_tex": "",
            "paper_claim": f"Sibling parameter groups ({', '.join(up['penalized_sibling_attrs'][:3])}) carry explicit penalty / weight decay.",
            "code_symbol": c_sid, "code_reality": f"`{up['param_attr']}` at {c_f}:L{p_ln} (`{up['rhs'][:80]}`) is excluded from explicit penalty terms and positive `weight_decay` groups.",
            "impact": "Structural slope/parameter remains unshrunk relative to penalized parameters; verify whether omission is intentional identification theory or oversight.",
            "slice_truncated": slice_truncated, "rung": "CLAIMED",
            "evidence_refs": [{"kind": "code", "target": c_sid, "start_line": p_ln, "end_line": p_ln, "token_hint": str(up["param_attr"])}],
        })

    for sf in scope_files:
        for kop in ((file_infos.get(sf) or {}).get("kernel_ops") or [])[:4]:
            preconds.append({
                "finding_id": f"pre-{len(preconds) + 1}", "direction": "kernel_precondition", "severity": "info",
                "verdict": "STATIC_MATCH" if kop["op"] in ("logsumexp", "slogdet", "log_softmax") else "PRECONDITION_RISK",
                "title": f"Numerical reduction `{kop['op']}` in `{Path(sf).name}:L{kop['line']}`", "eq_label": "", "paper_tex": "",
                "paper_claim": "Log-space / Cholesky / determinant reductions require finite-scale conditioning and explicit axis preservation.",
                "code_symbol": f"{sf}:L{kop['line']}", "code_reality": f"Calls `{kop['expr']}` (`keepdim={kop['keepdim']}`).",
                "impact": "Verify broadcast dimensions and jitter floor under extreme parameter draws.",
                "slice_truncated": False, "rung": "CLAIMED",
                "evidence_refs": [{"kind": "code", "target": sf, "start_line": kop["line"], "end_line": kop["line"], "token_hint": kop["op"]}],
            })

    if l1_stages:
        st_k = l1_stages[min(2, len(l1_stages) - 1)]
        if st_k.get("files") and st_k.get("symbols"):
            refactors.append({
                "refactor_id": "ref-pure-core-1", "title": f"Extract pure functional kernel boundary for {st_k['title']}",
                "category": "pure_core_extraction", "direction": "preserve_behavior_pure_refactor",
                "target_file": st_k["files"][0], "target_symbol": st_k["symbols"][0],
                "summary": f"Decouple pure tensor math in `{st_k['symbols'][0]}` from file/CLI side effects while preserving bit-identical outputs.",
                "wrong_side_warning": "", "rung": "CLAIMED", "evidence_refs": st_k["evidence_refs"],
            })

    return {
        "schema": pass2_schema, "pass": "pass2_comprehension", "scope_sha256": scope_sha256,
        "epoch": epoch, "slice_truncated": slice_truncated,
        "l0_scenarios": [{"scenario_id": "primary_replication", "title": "Primary Paper Replication Flow", "entrypoint": entrypoints[0] if entrypoints else (scope_files[0] if scope_files else ""), "summary": f"End-to-end execution across {len(scope_files)} in-scope files.", "paper_targets": [], "stage_ids": [s["stage_id"] for s in l1_stages]}],
        "l1_stages": l1_stages, "edges": edges, "causal_triptych": triptychs, "story_diff_rows": story_diffs,
        "paper_aligned_rows": paper_rows,
        "null_set": {
            "tier1_dead": [str(s.get("id") or "") for s in (symbol_slice.get("unreached_symbols") or [])[:25] if s.get("id")],
            "tier2_plumbing": [f for f in scope_files if bool((file_infos.get(f) or {}).get("cli_flags"))],
            "tier3_io_harness": [f for f in scope_files if bool((file_infos.get(f) or {}).get("output_artifacts"))],
        },
        "ramanujan_audit": {"pass2a_paper_to_code": pass2a, "pass2b_code_to_paper": pass2b, "kernel_preconditions": preconds},
        "refactor_candidates": refactors,
    }
