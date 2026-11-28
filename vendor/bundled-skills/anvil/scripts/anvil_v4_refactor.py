#!/usr/bin/env python3
"""Anvil v4 Pillar 2 & Pillar 5 — Pure-Core / Imperative-Shell Target Map,
100% Symbol Conservation across 3-Tier Null Set, Consented Data-Only Golden-Master
Stage-Boundary Equivalence Replay, and Untraced Wall-Clock Stage Profiler +
Precondition-Checked Literature Upgrades (`scripts/anvil_v4_refactor.py`).
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import io
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
import warnings
from types import FrameType, ModuleType
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from anvil_v4_process import (
    ALLOWLISTED_DATA_DIR_NAMES,
    ARCHIVE_OR_STAGING_DIRS,
    AnvilRefusalError,
    MAX_ALLOWLISTED_DATA_BYTES,
    MAX_SCOPE_BUNDLE_BYTES,
    SCOPE_MANIFEST_SCHEMA_VERSION,
    TRACE_SCHEMA,
    _build_repo_import_graph,
    _compute_import_closure,
    _extract_polyglot_units,
    _is_link_or_junction,
    _scan_contained_source_files,
    _strip_leading_dot_slash,
    atomic_locked_read_json,
    atomic_locked_write_json,
    bind_manuscript_equations_to_symbols,
    build_process_map,
    build_software_architecture_paper_map,
    build_symbol_call_graph,
    compute_scope_manifest,
    discover_paper_matched_scopes,
    load_validated_trace_json,
    resolve_active_pipeline_scope,
    resolve_contained_path,
    slice_call_graph,
)
from anvil_v4_trace import (
    ISOLATION_BOUNDARY,
    MAX_TIMEOUT_SEC,
    NON_VM_TRUST_WARNING,
    _build_unit_index,
    _kill_process_tree,
    _stage_isolated_worktree_copy,
    build_scrubbed_env,
    validate_execution_argv,
)

REFACTOR_MAP_SCHEMA = "anvil-v4-refactor-map/v1"
PROFILE_LIT_SCHEMA = "anvil-v4-profile-lit/v1"

MAX_GM_SNAPSHOT_ELEMENTS = 250_000
MAX_GM_SNAPSHOT_BYTES = 8_388_608
MAX_GM_DEPTH = 32

_IMPURE_CALL_NAMES: Set[str] = {
    "open", "print", "input", "write_text", "write_bytes", "read_text", "read_bytes",
    "mkdir", "unlink", "rmtree", "replace", "rename", "remove", "makedirs",
    "urlopen", "urlretrieve", "Popen", "run", "check_output", "check_call",
    "connect", "cursor", "execute", "executemany", "commit",
}

_IMPURE_MODULE_ROOTS: Set[str] = {
    "subprocess", "socket", "urllib", "requests", "http", "sqlite3", "shutil", "tempfile",
}

_MUTATING_CONTAINER_METHODS: Set[str] = {
    "append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse",
    "update", "setdefault", "popitem", "add", "discard", "intersection_update",
    "difference_update", "symmetric_difference_update", "appendleft", "extendleft",
    "popleft", "rotate", "fill", "put", "putmask", "resize", "zero_", "add_",
    "sub_", "mul_", "div_", "fill_", "clamp_", "copy_", "scatter_", "masked_fill_",
}

_IMMUTABLE_SCALAR_ANNOTATIONS: Set[str] = {
    "int", "float", "str", "bool", "bytes", "complex",
}


# ---------------------------------------------------------------------------
# 1. Normalized AST Structural Fingerprint & Static Purity / Reference Scanner
# ---------------------------------------------------------------------------

class _NormalizedBodyTransformer(ast.NodeTransformer):
    """Alpha-normalize local & parameter identifiers while preserving operators,
    constants, control flow, and external call/attribute names so genuine AST
    helper clones match deterministically.
    """

    def __init__(self, param_names: Sequence[str], assigned_locals: Sequence[str]) -> None:
        super().__init__()
        self._map: Dict[str, str] = {}
        for idx, pname in enumerate(param_names):
            self._map[pname] = f"_p{idx}"
        next_v = 0
        for lname in assigned_locals:
            if lname not in self._map:
                self._map[lname] = f"_v{next_v}"
                next_v += 1

    def visit_arg(self, node: ast.arg) -> ast.AST:
        mapped = self._map.get(node.arg, node.arg)
        return ast.arg(arg=mapped, annotation=None)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self._map:
            return ast.Name(id=self._map[node.id], ctx=node.ctx)
        return node


def _strip_docstring_stmts(body: List[ast.stmt]) -> List[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return list(body)


def _compute_normalized_body_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Tuple[str, int]:
    """Return `(sha256_prefix, effective_stmt_count)` for `node`'s normalized signature + decorators + body."""
    stmts = _strip_docstring_stmts(list(node.body))
    if not stmts:
        return "", 0
    if len(stmts) == 1 and isinstance(stmts[0], ast.Pass):
        return "", 0

    pos_params = [a.arg for a in (list(node.args.posonlyargs) + list(node.args.args))]
    kwonly_names = [a.arg for a in list(node.args.kwonlyargs)]
    params = list(pos_params) + list(kwonly_names)
    if node.args.vararg is not None:
        params.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        params.append(node.args.kwarg.arg)

    assigned: List[str] = []
    for st in stmts:
        for child in ast.walk(st):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store) and child.id not in assigned:
                assigned.append(child.id)

    import copy

    norm_mod = ast.Module(body=[ast.fix_missing_locations(s) for s in stmts], type_ignores=[])
    cloned_mod = copy.deepcopy(norm_mod)
    transformer = _NormalizedBodyTransformer(params, assigned)
    transformed = transformer.visit(cloned_mod)
    dumped_body = ast.dump(transformed, annotate_fields=True, include_attributes=False)
    dumped_defaults = "|".join(
        ast.dump(d, annotate_fields=True, include_attributes=False) for d in list(node.args.defaults)
    )
    dumped_kw_defaults = "|".join(
        ("NONE" if kd is None else ast.dump(kd, annotate_fields=True, include_attributes=False))
        for kd in list(node.args.kw_defaults)
    )
    dumped_decorators = "|".join(
        ast.dump(dec, annotate_fields=True, include_attributes=False) for dec in list(node.decorator_list)
    )
    sig = (
        f"async={isinstance(node, ast.AsyncFunctionDef)}"
        f"|posonly={len(node.args.posonlyargs)}|args={len(node.args.args)}"
        f"|kwonly={','.join(kwonly_names)}"
        f"|vararg={node.args.vararg is not None}|kwarg={node.args.kwarg is not None}"
        f"|defaults={dumped_defaults}|kw_defaults={dumped_kw_defaults}"
        f"|decorators={dumped_decorators}|body={dumped_body}"
    )
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:24], len(stmts)


def _is_fresh_container_expr(expr: Optional[ast.AST]) -> bool:
    if expr is None:
        return False
    if isinstance(expr, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mult) and (
        isinstance(expr.left, ast.List) or isinstance(expr.right, ast.List)
    ):
        return True
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id in {
            "list", "dict", "set", "bytearray", "Counter", "defaultdict", "deque", "OrderedDict",
        }:
            return True
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in {
            "copy", "deepcopy", "zeros", "ones", "empty", "full",
            "zeros_like", "ones_like", "empty_like", "full_like", "arange", "linspace", "clone",
        }:
            return True
    return False


def _expr_may_alias_external(expr: Optional[ast.AST], external_names: Set[str]) -> bool:
    if expr is None or _is_fresh_container_expr(expr):
        return False
    if isinstance(expr, (ast.Constant, ast.Tuple, ast.GeneratorExp, ast.JoinedStr)):
        return False
    if isinstance(expr, (ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare)):
        return False
    return any(isinstance(sub, ast.Name) and sub.id in external_names for sub in ast.walk(expr))


def _collect_own_scope_and_nested_defs(
    fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Tuple[List[ast.AST], List[ast.FunctionDef | ast.AsyncFunctionDef]]:
    own_nodes: List[ast.AST] = []
    nested_defs: List[ast.FunctionDef | ast.AsyncFunctionDef] = []
    stack: List[ast.AST] = list(reversed(fn_node.body))
    while stack:
        cur = stack.pop()
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested_defs.append(cur)
            continue
        if isinstance(cur, ast.ClassDef):
            for cstmt in cur.body:
                if isinstance(cstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_defs.append(cstmt)
            continue
        own_nodes.append(cur)
        children = list(ast.iter_child_nodes(cur))
        stack.extend(reversed(children))
    return own_nodes, nested_defs


def _inspect_python_function_purity_and_math(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Tuple[bool, bool, List[str]]:
    """Return `(is_pure, has_math_ops, io_sites)`."""
    is_pure = True
    has_math = False
    io_sites: List[str] = []

    all_args = (
        list(node.args.posonlyargs)
        + list(node.args.args)
        + list(node.args.kwonlyargs)
        + ([node.args.vararg] if node.args.vararg else [])
        + ([node.args.kwarg] if node.args.kwarg else [])
    )
    param_names: Set[str] = {a.arg for a in all_args}
    immutable_params: Set[str] = {
        a.arg
        for a in all_args
        if isinstance(a.annotation, ast.Name) and a.annotation.id in _IMMUTABLE_SCALAR_ANNOTATIONS
    }

    own_nodes, nested_defs = _collect_own_scope_and_nested_defs(node)
    fresh_candidates: Set[str] = set()
    disqualified_fresh: Set[str] = set(param_names)
    may_alias_external: Set[str] = set(param_names - immutable_params)
    alias_edges: List[Tuple[str, Optional[ast.AST]]] = []

    for child in own_nodes:
        if isinstance(child, (ast.Global, ast.Nonlocal)):
            disqualified_fresh.update(child.names)
            may_alias_external.update(child.names)
        elif isinstance(child, ast.Assign):
            if len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
                tname = child.targets[0].id
                if _is_fresh_container_expr(child.value):
                    fresh_candidates.add(tname)
                else:
                    disqualified_fresh.add(tname)
                    alias_edges.append((tname, child.value))
            else:
                for tgt in child.targets:
                    for sub in ast.walk(tgt):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                            disqualified_fresh.add(sub.id)
                            alias_edges.append((sub.id, child.value))
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            if isinstance(child.target, ast.Name):
                tname = child.target.id
                if _is_fresh_container_expr(child.value):
                    fresh_candidates.add(tname)
                else:
                    disqualified_fresh.add(tname)
                    alias_edges.append((tname, child.value))
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            for sub in ast.walk(child.target):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    disqualified_fresh.add(sub.id)
                    alias_edges.append((sub.id, child.iter))
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                if item.optional_vars is not None:
                    for sub in ast.walk(item.optional_vars):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                            disqualified_fresh.add(sub.id)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            disqualified_fresh.add(child.name)
        elif isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
            disqualified_fresh.add(child.target.id)
            alias_edges.append((child.target.id, child.value))

    changed = True
    while changed:
        changed = False
        for dst, rhs in alias_edges:
            if dst not in may_alias_external and _expr_may_alias_external(rhs, may_alias_external):
                may_alias_external.add(dst)
                changed = True

    fresh_locals = fresh_candidates - disqualified_fresh

    def _check_mutation_target(tgt: ast.AST) -> None:
        nonlocal is_pure
        if isinstance(tgt, (ast.Tuple, ast.List)):
            for elt in tgt.elts:
                _check_mutation_target(elt)
        elif isinstance(tgt, ast.Starred):
            _check_mutation_target(tgt.value)
        elif isinstance(tgt, ast.Attribute):
            is_pure = False
            io_sites.append(f"mutation:{tgt.attr}")
        elif isinstance(tgt, ast.Subscript):
            base = tgt.value
            while isinstance(base, ast.Subscript):
                base = base.value
            if not (isinstance(base, ast.Name) and base.id in fresh_locals):
                is_pure = False
                label = base.id if isinstance(base, ast.Name) else "subscript"
                io_sites.append(f"mutation:{label}[...]")

    for child in own_nodes:
        if isinstance(child, (ast.Global, ast.Nonlocal)):
            is_pure = False
            io_sites.append("global_or_nonlocal_mutation")
        elif isinstance(child, ast.Assign):
            for tgt in child.targets:
                _check_mutation_target(tgt)
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            _check_mutation_target(child.target)
        elif isinstance(child, ast.Delete):
            for tgt in child.targets:
                _check_mutation_target(tgt)
        elif isinstance(child, ast.AugAssign):
            if isinstance(child.target, ast.Name):
                if child.target.id in may_alias_external:
                    is_pure = False
                    io_sites.append(f"mutation:{child.target.id}")
            else:
                _check_mutation_target(child.target)
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            _check_mutation_target(child.target)
        elif isinstance(child, ast.BinOp) and isinstance(
            child.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.MatMult, ast.FloorDiv)
        ):
            has_math = True
        elif isinstance(child, ast.Attribute):
            if isinstance(child.value, ast.Name) and child.value.id == "os" and child.attr == "environ":
                is_pure = False
                io_sites.append("os.environ")
        elif isinstance(child, ast.Call):
            fn = child.func
            if isinstance(fn, ast.Name):
                if fn.id in _IMPURE_CALL_NAMES:
                    is_pure = False
                    io_sites.append(fn.id)
                elif fn.id in {"setattr", "delattr"}:
                    is_pure = False
                    io_sites.append(f"mutation:{fn.id}")
                if fn.id in {"sum", "abs", "min", "max", "round"}:
                    has_math = True
            elif isinstance(fn, ast.Attribute):
                attr = fn.attr
                root_id = fn.value.id if isinstance(fn.value, ast.Name) else ""
                if attr in _IMPURE_CALL_NAMES or root_id in _IMPURE_MODULE_ROOTS:
                    is_pure = False
                    io_sites.append(f"{root_id}.{attr}" if root_id else attr)
                elif attr in _MUTATING_CONTAINER_METHODS:
                    if not (isinstance(fn.value, ast.Name) and fn.value.id in fresh_locals):
                        is_pure = False
                        rlabel = fn.value.id if isinstance(fn.value, ast.Name) else "expr"
                        io_sites.append(f"mutation:{rlabel}.{attr}")
                if root_id in {"sys"} and attr in {"stdout", "stderr", "exit"}:
                    is_pure = False
                    io_sites.append(f"sys.{attr}")
                if root_id in {"math", "np", "numpy", "torch", "scipy", "linalg"} or attr in {
                    "exp", "log", "sqrt", "sin", "cos", "dot", "matmul", "inv", "solve", "cholesky", "mean", "var",
                }:
                    has_math = True

    for sub_def in nested_defs:
        sub_pure, sub_math, sub_sites = _inspect_python_function_purity_and_math(sub_def)
        if not sub_pure:
            is_pure = False
            io_sites.extend(sub_sites)
        if sub_math:
            has_math = True

    return is_pure, has_math, list(dict.fromkeys(io_sites))


def _is_main_guard_test(test_node: ast.AST) -> bool:
    if isinstance(test_node, ast.Compare) and len(test_node.ops) == 1 and isinstance(test_node.ops[0], ast.Eq):
        sides = [test_node.left, test_node.comparators[0]]
        has_dunder = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
        has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
        return has_dunder and has_main
    return False


def _collect_ast_referenced_names(node: ast.AST) -> Tuple[Set[str], Set[str]]:
    """Collect `(direct_identifier_refs, getattr_prefixes)` inside an AST subtree."""
    refs: Set[str] = set()
    getattr_prefixes: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            refs.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            refs.add(child.attr)
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name) and child.func.id == "getattr" and len(child.args) >= 2:
                arg1 = child.args[1]
                if isinstance(arg1, ast.Constant) and isinstance(arg1.value, str):
                    getattr_prefixes.add(arg1.value)
                elif isinstance(arg1, ast.JoinedStr):
                    for val_part in arg1.values:
                        if isinstance(val_part, ast.Constant) and isinstance(val_part.value, str) and val_part.value:
                            getattr_prefixes.add(val_part.value)
                            break
    return refs, getattr_prefixes


def _is_python_test_entrypoint(fn_name: str, cls_name: str, has_decorators: bool) -> bool:
    """Identify test-runner entrypoints and fixtures inside test modules."""
    if fn_name == "test" or fn_name.startswith("test_"):
        return True
    if cls_name.startswith("Test") and (
        fn_name.startswith("test")
        or fn_name in {"setUp", "tearDown", "setUpClass", "tearDownClass", "setup_method", "teardown_method"}
    ):
        return True
    if fn_name in {"setUpModule", "tearDownModule", "pytest_configure", "pytest_collection_modifyitems"}:
        return True
    return has_decorators


def _scan_repository_symbols_and_references(
    root: Path,
    proc_map: Dict[str, Any],
    trace_data: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Set[str], Set[str], Set[str], int, int]:
    """Scan all contained production AND test files (`excluded_symbols == 0`) and return:
    `(repo_symbols, prod_external_refs, test_refs, getattr_prefixes, prod_file_count, test_file_count)`.
    """
    prod_files, test_files = _scan_contained_source_files(root)
    scope_meta = proc_map.get("paper_matched_scopes") if isinstance(proc_map, dict) else None
    excl_sym_set: Set[str] = set()
    if isinstance(scope_meta, dict) and scope_meta.get("scoped") and scope_meta.get("active_files"):
        allowed_prod = set(scope_meta["active_files"])
        prod_files = [fp for fp in prod_files if fp.relative_to(root).as_posix() in allowed_prod]
        excl_sym_set = {
            str(s.get("symbol") if isinstance(s, dict) else s)
            for s in (scope_meta.get("excluded_shared_symbols") or [])
        }
    test_files_set: Set[Path] = set(test_files)
    target_files = sorted(prod_files + test_files)

    # Map symbol `(file, symbol)` -> stage_id `S1..Sk` from Wave 1 process_map
    sym_to_old_stage: Dict[Tuple[str, str], str] = {}
    file_default_stage: Dict[str, str] = {}
    l1_stages = list(proc_map.get("l1_stages") or [])
    fallback_last_stage = str(l1_stages[-1].get("id") or "S1") if l1_stages else "S1"
    for stg in l1_stages:
        sid = str(stg.get("id") or "S1")
        for msym in stg.get("member_symbols") or []:
            if ":" in msym:
                f_part, s_part = msym.split(":", 1)
                base_s = s_part.split("#", 1)[0]
                sym_to_old_stage[(f_part, base_s)] = sid
                file_default_stage.setdefault(f_part, sid)

    traced_line_hits: Dict[Tuple[str, int], int] = {}
    if trace_data is not None:
        for item in trace_data.get("executed_lines") or []:
            if isinstance(item, dict) and isinstance(item.get("file"), str) and isinstance(item.get("line"), int):
                traced_line_hits[(item["file"], int(item["line"]))] = int(item.get("hits", 1))

    repo_symbols: List[Dict[str, Any]] = []
    prod_refs: Set[str] = set()
    test_refs: Set[str] = set()
    getattr_prefixes: Set[str] = set()

    # Pre-scan class inheritance across repository so PyTorch nn.Module / Dataset subclasses
    # (including transitive local subclasses keyed by (file, class)) receive proper forward/__call__ lifecycle edges.
    raw_class_bases: Dict[Tuple[str, str], List[str]] = {}
    cls_files_by_name: Dict[str, List[str]] = {}
    parsed_py_trees: Dict[Path, Tuple[str, ast.Module]] = {}
    for fp in target_files:
        if fp.suffix != ".py":
            continue
        rel_posix = fp.relative_to(root).as_posix()
        text = fp.read_text(encoding="utf-8-sig", errors="replace")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text, filename=rel_posix)
        except SyntaxError as syn_exc:
            raise AnvilRefusalError(
                "SYNTAX_ERROR_REFUSED",
                f"Cannot guarantee 100% symbol conservation: Python source file '{rel_posix}' failed AST parsing at line {syn_exc.lineno}: {syn_exc.msg}",
                details={"file": rel_posix, "lineno": syn_exc.lineno},
            ) from syn_exc
        parsed_py_trees[fp] = (text, tree)
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                b_list: List[str] = []
                for b in stmt.bases:
                    if isinstance(b, ast.Name):
                        b_list.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        b_list.append(b.attr)
                    else:
                        try:
                            b_list.append(ast.unparse(b))
                        except Exception:
                            pass
                raw_class_bases.setdefault((rel_posix, stmt.name), []).extend(b_list)
                cls_files_by_name.setdefault(stmt.name, []).append(rel_posix)

    nn_module_pairs: Set[Tuple[str, str]] = {
        (rf, cname)
        for (rf, cname), bnames in raw_class_bases.items()
        if any(bn.endswith(("Module", "Dataset", "IterableDataset", "LightningModule", "PreTrainedModel")) for bn in bnames)
    }
    changed_nn = True
    while changed_nn:
        changed_nn = False
        for (rf, cname), bnames in raw_class_bases.items():
            if (rf, cname) in nn_module_pairs:
                continue
            for bn in bnames:
                btail = bn.split(".")[-1]
                same_f = (rf, btail) in nn_module_pairs
                uniq_cross = len(cls_files_by_name.get(btail, [])) == 1 and (cls_files_by_name[btail][0], btail) in nn_module_pairs
                if same_f or uniq_cross:
                    nn_module_pairs.add((rf, cname))
                    changed_nn = True
                    break

    nn_lifecycle_methods = {
        "forward", "__call__", "training_step", "validation_step",
        "test_step", "predict_step", "configure_optimizers", "__getitem__", "__len__", "__iter__",
    }

    for fp in target_files:
        is_test_fp = fp in test_files_set
        active_ref_sink = test_refs if is_test_fp else prod_refs
        file_main_guard_refs: Set[str] = set()
        file_dunder_all_exports: Set[str] = set()
        rel_posix = fp.relative_to(root).as_posix()
        if fp.suffix == ".py":
            text, tree = parsed_py_trees[fp]

            # Collect top-level non-def statements (dispatch tables, __main__, __all__)
            for stmt in tree.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in stmt.decorator_list:
                        d_refs, d_gp = _collect_ast_referenced_names(dec)
                        active_ref_sink.update(d_refs)
                        getattr_prefixes.update(d_gp)
                    continue
                if isinstance(stmt, ast.ClassDef):
                    for base in stmt.bases:
                        b_refs, _ = _collect_ast_referenced_names(base)
                        active_ref_sink.update(b_refs)
                    for dec in stmt.decorator_list:
                        cd_refs, cd_gp = _collect_ast_referenced_names(dec)
                        active_ref_sink.update(cd_refs)
                        getattr_prefixes.update(cd_gp)
                    for cstmt in stmt.body:
                        if isinstance(cstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for mdec in cstmt.decorator_list:
                                md_refs, md_gp = _collect_ast_referenced_names(mdec)
                                active_ref_sink.update(md_refs)
                                getattr_prefixes.update(md_gp)
                        else:
                            c_refs, c_gp = _collect_ast_referenced_names(cstmt)
                            active_ref_sink.update(c_refs)
                            getattr_prefixes.update(c_gp)
                    continue
                if isinstance(stmt, ast.If) and _is_main_guard_test(stmt.test):
                    mg_refs, mg_gp = _collect_ast_referenced_names(stmt)
                    file_main_guard_refs.update(mg_refs)
                    active_ref_sink.update(mg_refs)
                    getattr_prefixes.update(mg_gp)
                    continue
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "__all__" and isinstance(stmt.value, (ast.List, ast.Tuple, ast.Set)):
                            for elt in stmt.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    file_dunder_all_exports.add(elt.value)
                s_refs, s_gp = _collect_ast_referenced_names(stmt)
                active_ref_sink.update(s_refs)
                getattr_prefixes.update(s_gp)

            def _add_py_symbol(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str = "") -> None:
                qname = f"{cls_name}.{fn_node.name}" if cls_name else fn_node.name
                sym_id = f"{rel_posix}:{qname}"
                if excl_sym_set and (sym_id in excl_sym_set or f"{rel_posix}:{fn_node.name}" in excl_sym_set):
                    return
                s_ln = int(getattr(fn_node, "lineno", 1))
                e_ln = int(getattr(fn_node, "end_lineno", s_ln) or s_ln)
                is_pure, has_math, io_sites = _inspect_python_function_purity_and_math(fn_node)
                norm_fp, stmt_count = _compute_normalized_body_fingerprint(fn_node)

                # Collect outgoing references from inside this function body (excluding self-recursion)
                body_refs: Set[str] = set()
                for st in fn_node.body:
                    r_set, gp_set = _collect_ast_referenced_names(st)
                    body_refs.update(r_set)
                    getattr_prefixes.update(gp_set)
                body_refs.discard(fn_node.name)
                active_ref_sink.update(body_refs)

                has_loop = any(isinstance(c, (ast.For, ast.AsyncFor, ast.While)) for c in ast.walk(fn_node))
                doc = (ast.get_docstring(fn_node) or "").strip()
                name_tokens = set(re.findall(r"[a-z0-9]+", fn_node.name.lower()))
                doc_tokens = set(re.findall(r"[a-z0-9]+", doc.lower()))
                all_toks = name_tokens | doc_tokens
                ingest_kw = {"load", "loads", "read", "parse", "ingest", "fetch", "input", "init", "config"}
                emit_kw = {"write", "writes", "save", "emit", "render", "export", "report", "dump", "dumps", "serialize", "output"}

                if is_test_fp:
                    is_entry = (
                        _is_python_test_entrypoint(fn_node.name, cls_name, bool(fn_node.decorator_list))
                        or fn_node.name in file_main_guard_refs
                        or qname in file_dunder_all_exports
                        or fn_node.name in file_dunder_all_exports
                    )
                else:
                    is_entry = (
                        fn_node.name.startswith("main")
                        or fn_node.name in {"cli", "app", "run_pipeline", "__init__"}
                        or fn_node.name in file_main_guard_refs
                        or qname in file_dunder_all_exports
                        or fn_node.name in file_dunder_all_exports
                        or bool(fn_node.decorator_list)
                    )

                if is_test_fp and is_entry:
                    raw_kind = "emit"
                elif name_tokens & emit_kw or ((all_toks & emit_kw) and not (name_tokens & ingest_kw)):
                    raw_kind = "emit"
                elif name_tokens & ingest_kw or (all_toks & ingest_kw):
                    raw_kind = "ingest"
                elif has_loop:
                    raw_kind = "loop"
                else:
                    raw_kind = "compute"

                hits = sum(
                    cnt
                    for (hf, hln), cnt in traced_line_hits.items()
                    if hf == rel_posix and s_ln <= hln <= e_ln
                )
                default_sid = fallback_last_stage if is_test_fp else "S1"
                old_sid = sym_to_old_stage.get((rel_posix, qname)) or file_default_stage.get(rel_posix, default_sid)
                repo_symbols.append({
                    "id": sym_id,
                    "file": rel_posix,
                    "symbol": qname,
                    "short_name": fn_node.name,
                    "class_name": cls_name,
                    "language": "python",
                    "is_test_file": is_test_fp,
                    "start_line": s_ln,
                    "end_line": e_ln,
                    "is_pure": False if (is_test_fp and is_entry) else is_pure,
                    "has_math_ops": has_math,
                    "has_loop": has_loop,
                    "io_sites": io_sites,
                    "raw_kind": raw_kind,
                    "old_stage_id": old_sid,
                    "norm_fingerprint": norm_fp,
                    "stmt_count": stmt_count,
                    "traced_hits": hits,
                    "is_entrypoint": is_entry,
                    "outgoing_refs": sorted(body_refs),
                })

            for stmt in tree.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _add_py_symbol(stmt, "")
                elif isinstance(stmt, ast.ClassDef):
                    for cstmt in stmt.body:
                        if isinstance(cstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            _add_py_symbol(cstmt, stmt.name)
        else:
            text = fp.read_text(encoding="utf-8", errors="replace")
            units, has_top = _extract_polyglot_units(fp, rel_posix)
            if is_test_fp:
                test_refs.update(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text))
            seen_poly_ids: Set[str] = set()
            for u in units:
                sym_name = str(u["symbol"])
                short = str(u["short_name"])
                s_ln = int(u["start_line"])
                e_ln = int(u["end_line"])
                base_poly_id = f"{rel_posix}:{sym_name}"
                poly_id = base_poly_id if base_poly_id not in seen_poly_ids else f"{base_poly_id}:L{s_ln}"
                seen_poly_ids.add(poly_id)
                hits = sum(
                    cnt
                    for (hf, hln), cnt in traced_line_hits.items()
                    if hf == rel_posix and s_ln <= hln <= e_ln
                )
                for c in u.get("calls") or []:
                    if c != short:
                        active_ref_sink.add(c)
                default_sid = fallback_last_stage if is_test_fp else "S1"
                old_sid = sym_to_old_stage.get((rel_posix, sym_name)) or file_default_stage.get(rel_posix, default_sid)
                is_poly_entry = (
                    has_top
                    or short in {"main", "run", "app"}
                    or "export " in text
                    or (is_test_fp and (short == "test" or short.startswith("test")))
                )
                repo_symbols.append({
                    "id": poly_id,
                    "file": rel_posix,
                    "symbol": sym_name,
                    "short_name": short,
                    "class_name": "",
                    "language": fp.suffix.lstrip("."),
                    "is_test_file": is_test_fp,
                    "start_line": s_ln,
                    "end_line": e_ln,
                    "is_pure": False if (is_test_fp and is_poly_entry) else (u.get("kind") in ("compute", "loop")),
                    "has_math_ops": u.get("kind") in ("compute", "loop"),
                    "has_loop": bool(u.get("has_loop")),
                    "io_sites": [] if u.get("kind") in ("compute", "loop") else [str(u.get("kind"))],
                    "raw_kind": "emit" if (is_test_fp and is_poly_entry) else str(u.get("kind") or "compute"),
                    "old_stage_id": old_sid,
                    "norm_fingerprint": "",
                    "stmt_count": max(1, e_ln - s_ln),
                    "traced_hits": hits,
                    "is_entrypoint": is_poly_entry,
                    "outgoing_refs": list(u.get("calls") or []),
                })

    # Propagate PyTorch nn.Module / Dataset lifecycle reachability (`ClassName(...)` -> `ClassName.forward`)
    # iteratively so submodule chains (`OuterModule.__init__` -> `InnerModule` -> `InnerModule.forward`) resolve cleanly.
    progressed_lc = True
    while progressed_lc:
        progressed_lc = False
        for sym in repo_symbols:
            cls_nm = str(sym.get("class_name") or "")
            short_nm = str(sym.get("short_name") or "")
            q_nm = str(sym.get("symbol") or "")
            s_file = str(sym.get("file") or "")
            if (s_file, cls_nm) in nn_module_pairs and short_nm in nn_lifecycle_methods:
                if cls_nm in prod_refs and q_nm not in prod_refs:
                    prod_refs.add(q_nm)
                    if not sym.get("is_test_file"):
                        prod_refs.update(sym.get("outgoing_refs") or [])
                    progressed_lc = True
                elif cls_nm in test_refs and q_nm not in test_refs:
                    test_refs.add(q_nm)
                    progressed_lc = True

    return repo_symbols, prod_refs, test_refs, getattr_prefixes, len(prod_files), len(test_files)


# ---------------------------------------------------------------------------
# 2. Consented Data-Only Golden-Master Stage-Boundary Equivalence Helpers
# ---------------------------------------------------------------------------

def _charge_gm_budget(budget: Dict[str, int], *, elements: int = 0, nbytes: int = 0) -> None:
    """Enforce fail-closed Golden-Master snapshot element and byte budgets (never silently truncate)."""
    budget["elements"] = int(budget.get("elements", 0)) + max(0, int(elements))
    budget["bytes"] = int(budget.get("bytes", 0)) + max(0, int(nbytes))
    if budget["elements"] > MAX_GM_SNAPSHOT_ELEMENTS:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Golden-Master snapshot exceeded MAX_GM_SNAPSHOT_ELEMENTS ({budget['elements']} > {MAX_GM_SNAPSHOT_ELEMENTS}).",
            details={
                "bound_name": "max_gm_snapshot_elements",
                "bound_limit": MAX_GM_SNAPSHOT_ELEMENTS,
                "observed_value": budget["elements"],
            },
        )
    if budget["bytes"] > MAX_GM_SNAPSHOT_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Golden-Master snapshot exceeded MAX_GM_SNAPSHOT_BYTES ({budget['bytes']} > {MAX_GM_SNAPSHOT_BYTES}).",
            details={
                "bound_name": "max_gm_snapshot_bytes",
                "bound_limit": MAX_GM_SNAPSHOT_BYTES,
                "observed_value": budget["bytes"],
            },
        )


def _is_unserializable_runtime_handle(val: Any) -> bool:
    if isinstance(val, (ModuleType, io.IOBase)) or isinstance(val, type):
        return True
    if (
        inspect.isfunction(val)
        or inspect.ismethod(val)
        or inspect.isbuiltin(val)
        or inspect.iscode(val)
        or inspect.isframe(val)
        or inspect.isgenerator(val)
        or inspect.iscoroutine(val)
    ):
        return True
    return False


def _snapshot_gm_value(
    val: Any,
    depth: int = 0,
    budget: Optional[Dict[str, int]] = None,
    seen_ids: Optional[Set[int]] = None,
) -> Any:
    """Convert a Python return value into a strictly JSON-safe, pickle-free,
    truncation-free data descriptor suitable for `rtol`/`atol` equivalence checking.

    Serializes 100% of elements/characters/keys/array entries up to explicit
    fail-closed budgets (`MAX_GM_SNAPSHOT_ELEMENTS`, `MAX_GM_SNAPSHOT_BYTES`,
    `MAX_GM_DEPTH`); raises `AnvilRefusalError("BOUND_EXCEEDED_REFUSAL", ...)`
    when a bound is exceeded and marks unserializable opaque objects with
    `"_unverifiable": True` so `_values_equivalent` fails closed.
    """
    active_budget = budget if budget is not None else {"elements": 0, "bytes": 0}
    active_seen = seen_ids if seen_ids is not None else set()

    if depth > MAX_GM_DEPTH:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Golden-Master snapshot exceeded MAX_GM_DEPTH ({depth} > {MAX_GM_DEPTH}).",
            details={
                "bound_name": "max_gm_depth",
                "bound_limit": MAX_GM_DEPTH,
                "observed_value": depth,
            },
        )

    t = type(val)
    if val is None or t is bool:
        _charge_gm_budget(active_budget, elements=1, nbytes=4)
        return val
    if t is int:
        _charge_gm_budget(active_budget, elements=1, nbytes=max(8, (val.bit_length() + 7) // 8))
        return int(val) if val.bit_length() <= 53 else {"_kind": "big_int", "str": str(val)}
    if t is float:
        _charge_gm_budget(active_budget, elements=1, nbytes=8)
        if math.isnan(val):
            return {"_nonfinite": "NaN"}
        if math.isinf(val):
            return {"_nonfinite": "+Infinity" if val > 0 else "-Infinity"}
        return float(val)
    if t is complex:
        _charge_gm_budget(active_budget, elements=1, nbytes=16)
        return {
            "_complex": [
                _snapshot_gm_value(val.real, depth + 1, active_budget, active_seen),
                _snapshot_gm_value(val.imag, depth + 1, active_budget, active_seen),
            ]
        }
    if t is str:
        enc_len = len(val.encode("utf-8", errors="replace"))
        _charge_gm_budget(active_budget, elements=1, nbytes=enc_len)
        return val
    if t in (bytes, bytearray, memoryview):
        raw_b = bytes(val)
        _charge_gm_budget(active_budget, elements=1, nbytes=len(raw_b) * 2 + 16)
        return {"_bytes": t.__name__, "len": len(raw_b), "hex": raw_b.hex()}
    if isinstance(val, Path):
        p_str = val.as_posix()
        _charge_gm_budget(active_budget, elements=1, nbytes=len(p_str))
        return {"_path": p_str}

    obj_id = id(val)
    if obj_id in active_seen:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            "Cyclic container encountered during Golden-Master snapshot.",
            details={"bound_name": "cyclic_reference", "bound_limit": MAX_GM_DEPTH, "observed_value": depth},
        )

    if t is list or isinstance(val, tuple):
        active_seen.add(obj_id)
        try:
            _charge_gm_budget(active_budget, elements=len(val), nbytes=32)
            items = [_snapshot_gm_value(x, depth + 1, active_budget, active_seen) for x in val]
            if isinstance(val, tuple) and hasattr(t, "_fields"):
                return {
                    "_seq": f"{t.__module__}.{t.__qualname__}",
                    "fields": [str(f) for f in getattr(t, "_fields", ())],
                    "len": len(val),
                    "items": items,
                }
            return {"_seq": t.__name__, "len": len(val), "items": items}
        finally:
            active_seen.discard(obj_id)

    if t in (set, frozenset):
        active_seen.add(obj_id)
        try:
            _charge_gm_budget(active_budget, elements=len(val), nbytes=32)
            snapped = [_snapshot_gm_value(x, depth + 1, active_budget, active_seen) for x in val]
            snapped_sorted = sorted(
                snapped,
                key=lambda s: f"{type(s).__name__}:{json.dumps(s, sort_keys=True, separators=(',', ':'))}",
            )
            return {"_set": t.__name__, "len": len(val), "items": snapped_sorted}
        finally:
            active_seen.discard(obj_id)

    if t is dict:
        active_seen.add(obj_id)
        try:
            _charge_gm_budget(active_budget, elements=len(val), nbytes=32)
            keyed_entries: List[Tuple[str, Any, Any]] = []
            for k, v in val.items():
                k_snap = _snapshot_gm_value(k, depth + 1, active_budget, active_seen)
                v_snap = _snapshot_gm_value(v, depth + 1, active_budget, active_seen)
                k_canon = (
                    f"{type(k).__module__}.{type(k).__qualname__}:"
                    f"{json.dumps(k_snap, sort_keys=True, separators=(',', ':'))}"
                )
                keyed_entries.append((k_canon, k_snap, v_snap))
            keyed_entries.sort(key=lambda row: row[0])
            return {
                "_dict": [[row[0], row[1], row[2]] for row in keyed_entries],
                "len": len(val),
            }
        finally:
            active_seen.discard(obj_id)

    mod_name = getattr(t, "__module__", "") or ""
    tname = getattr(t, "__name__", "") or ""
    if mod_name.startswith("numpy") and tname != "ndarray" and hasattr(val, "item"):
        try:
            return _snapshot_gm_value(val.item(), depth + 1, active_budget, active_seen)
        except AnvilRefusalError:
            raise
        except Exception:
            return {"_unverifiable": True, "kind": "numpy_scalar_opaque", "type": f"{mod_name}.{tname}"}

    if mod_name.startswith("numpy") and tname == "ndarray":
        active_seen.add(obj_id)
        try:
            shape = [int(d) for d in val.shape]
            size = int(val.size)
            dtype_str = str(val.dtype)
            _charge_gm_budget(active_budget, elements=max(1, size), nbytes=64 + size * 8)
            flat_vals: List[Any] = []
            flat_it = val.flat
            for i in range(size):
                elem = flat_it[i]
                py_el = elem.item() if hasattr(elem, "item") else elem
                flat_vals.append(_snapshot_gm_value(py_el, depth + 1, active_budget, active_seen))
            return {
                "_ndarray": True,
                "shape": shape,
                "dtype": dtype_str,
                "size": size,
                "values": flat_vals,
            }
        except AnvilRefusalError:
            raise
        except Exception:
            return {"_unverifiable": True, "kind": "ndarray_opaque", "type": f"{mod_name}.{tname}"}
        finally:
            active_seen.discard(obj_id)

    if mod_name.startswith("torch") and tname == "Tensor":
        active_seen.add(obj_id)
        try:
            det = val.detach().cpu().reshape(-1)
            numel = int(det.numel())
            shape = [int(d) for d in val.shape]
            dtype_str = str(val.dtype)
            _charge_gm_budget(active_budget, elements=max(1, numel), nbytes=64 + numel * 8)
            vals = [_snapshot_gm_value(det[i].item(), depth + 1, active_budget, active_seen) for i in range(numel)]
            return {
                "_tensor": True,
                "shape": shape,
                "dtype": dtype_str,
                "size": numel,
                "values": vals,
            }
        except AnvilRefusalError:
            raise
        except Exception:
            return {"_unverifiable": True, "kind": "tensor_opaque", "type": f"{mod_name}.{tname}"}
        finally:
            active_seen.discard(obj_id)

    if not _is_unserializable_runtime_handle(val):
        try:
            inst_dict = object.__getattribute__(val, "__dict__")
            if type(inst_dict) is dict:
                active_seen.add(obj_id)
                try:
                    _charge_gm_budget(active_budget, elements=1, nbytes=32)
                    return {
                        "_object": f"{mod_name}.{getattr(t, '__qualname__', tname)}",
                        "attrs": _snapshot_gm_value(dict(inst_dict), depth + 1, active_budget, active_seen),
                    }
                finally:
                    active_seen.discard(obj_id)
        except AnvilRefusalError:
            raise
        except Exception:
            pass

    _charge_gm_budget(active_budget, elements=1, nbytes=32)
    return {"_unverifiable": True, "kind": "opaque", "type": f"{mod_name}.{tname}"}


def _diff_gm_values(
    a: Any,
    b: Any,
    rtol: float = 1e-7,
    atol: float = 1e-9,
    path: str = "$",
) -> Optional[str]:
    """Return `None` if `a` and `b` are equivalent within `(rtol, atol)`, else a detailed diff string."""
    if (isinstance(a, dict) and a.get("_unverifiable")) or (isinstance(b, dict) and b.get("_unverifiable")):
        ta = a.get("type") if isinstance(a, dict) else type(a).__name__
        tb = b.get("type") if isinstance(b, dict) else type(b).__name__
        return f"{path}: unverifiable opaque value ({ta} vs {tb}) cannot prove stage-boundary equivalence"

    if type(a) is bool or type(b) is bool:
        if type(a) is not type(b) or a != b:
            return f"{path}: boolean mismatch ({a!r} vs {b!r})"
        return None

    if type(a) is int and type(b) is int:
        if a != b:
            return f"{path}: integer mismatch ({a} vs {b})"
        return None

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa = float(a)
        fb = float(b)
        if math.isnan(fa) or math.isnan(fb):
            if not (math.isnan(fa) and math.isnan(fb)):
                return f"{path}: non-finite NaN mismatch ({a!r} vs {b!r})"
            return None
        if math.isinf(fa) or math.isinf(fb):
            if fa != fb:
                return f"{path}: non-finite Infinity mismatch ({a!r} vs {b!r})"
            return None
        if not math.isclose(fa, fb, rel_tol=rtol, abs_tol=atol):
            return f"{path}: numeric mismatch ({a} vs {b}, rtol={rtol}, atol={atol})"
        return None

    if type(a) is not type(b):
        return f"{path}: type mismatch ({type(a).__name__} vs {type(b).__name__})"

    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return f"{path}: dict keys mismatch ({sorted(a.keys())} vs {sorted(b.keys())})"
        if "_dict" in a and "_dict" in b and isinstance(a["_dict"], list) and isinstance(b["_dict"], list):
            if a.get("len") != b.get("len") or len(a["_dict"]) != len(b["_dict"]):
                return f"{path}: dict length mismatch ({a.get('len')} vs {b.get('len')})"
            map_a = {row[0]: (row[1], row[2]) for row in a["_dict"] if isinstance(row, list) and len(row) == 3}
            map_b = {row[0]: (row[1], row[2]) for row in b["_dict"] if isinstance(row, list) and len(row) == 3}
            if len(map_a) == len(a["_dict"]) and len(map_b) == len(b["_dict"]):
                if set(map_a.keys()) != set(map_b.keys()):
                    diff_keys = sorted(set(map_a.keys()) ^ set(map_b.keys()))[:8]
                    return f"{path}: dict keys mismatch (divergent keys: {diff_keys})"
                for k_canon in sorted(map_a.keys()):
                    k_label, va = map_a[k_canon]
                    _, vb = map_b[k_canon]
                    diff = _diff_gm_values(va, vb, rtol, atol, f"{path}[{k_label!r}]")
                    if diff is not None:
                        return diff
                return None
        if ("_ndarray" in a or "_tensor" in a) and (a.get("shape") != b.get("shape") or a.get("dtype") != b.get("dtype")):
            return (
                f"{path}: array shape/dtype mismatch "
                f"(shape {a.get('shape')} dtype {a.get('dtype')} vs shape {b.get('shape')} dtype {b.get('dtype')})"
            )
        for k in sorted(a.keys()):
            diff = _diff_gm_values(a[k], b[k], rtol, atol, f"{path}.{k}")
            if diff is not None:
                return diff
        return None

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: sequence length mismatch ({len(a)} vs {len(b)})"
        for idx, (xa, xb) in enumerate(zip(a, b)):
            diff = _diff_gm_values(xa, xb, rtol, atol, f"{path}[{idx}]")
            if diff is not None:
                return diff
        return None

    if a != b:
        return f"{path}: value mismatch ({a!r} vs {b!r})"
    return None


def _values_equivalent(
    a: Any,
    b: Any,
    rtol: float = 1e-7,
    atol: float = 1e-9,
    path: str = "$",
) -> bool:
    """Return `True` iff snapshots/values `a` and `b` are equivalent within `(rtol, atol)`."""
    return _diff_gm_values(a, b, rtol=rtol, atol=atol, path=path) is None


def _compare_stdout_streams(base_out: str, cand_out: str, rtol: float, atol: float) -> Optional[str]:
    b_strip = base_out.strip()
    c_strip = cand_out.strip()
    if b_strip == c_strip:
        return None
    # Try strict JSON parse first if stdout is JSON
    if b_strip.startswith(("{", "[")) and c_strip.startswith(("{", "[")):
        try:
            bj = json.loads(b_strip)
            cj = json.loads(c_strip)
            return _diff_gm_values(bj, cj, rtol, atol, "stdout_json")
        except Exception:
            pass
    num_re = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
    b_lines = b_strip.splitlines()
    c_lines = c_strip.splitlines()
    if len(b_lines) != len(c_lines):
        return f"stdout line count mismatch ({len(b_lines)} vs {len(c_lines)})"
    for lno, (bl, cl) in enumerate(zip(b_lines, c_lines), start=1):
        if bl == cl:
            continue
        b_nums = [float(x) for x in num_re.findall(bl)]
        c_nums = [float(x) for x in num_re.findall(cl)]
        b_skeleton = num_re.sub("#", bl)
        c_skeleton = num_re.sub("#", cl)
        if b_skeleton != c_skeleton or len(b_nums) != len(c_nums):
            return f"stdout line {lno} text mismatch ({bl!r} vs {cl!r})"
        for idx, (bn, cn) in enumerate(zip(b_nums, c_nums)):
            if not math.isclose(bn, cn, rel_tol=rtol, abs_tol=atol):
                return f"stdout line {lno} token {idx} numeric mismatch ({bn} vs {cn})"
    return None


class _ScratchRefactorTransformer(ast.NodeTransformer):
    """Remove `null_proven` dead functions and redirect intra-module calls to
    `null_redundant` clones onto their `canonical_symbol` on a scratch worktree copy.
    """

    def __init__(
        self,
        rel_file: str,
        drop_qualnames: Set[str],
        same_file_redirects: Dict[str, str],
        cross_file_redirects: Dict[str, Tuple[str, str]],
    ) -> None:
        super().__init__()
        self.rel_file = rel_file
        self.drop_qualnames = drop_qualnames
        self.same_file_redirects = same_file_redirects
        self.cross_file_redirects = cross_file_redirects
        self._cls_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self._cls_stack.append(node.name)
        new_body: List[ast.stmt] = []
        for stmt in node.body:
            res = self.visit(stmt)
            if res is not None:
                new_body.append(res)
        self._cls_stack.pop()
        if not new_body:
            new_body = [ast.Pass()]
        node.body = new_body
        return node

    def _handle_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[ast.AST]:
        qname = f"{self._cls_stack[-1]}.{node.name}" if self._cls_stack else node.name
        if qname in self.drop_qualnames:
            return None
        if not self._cls_stack and qname in self.same_file_redirects:
            # Drop same-file duplicate helper definition; calls are rewritten to canonical
            return None
        if not self._cls_stack and qname in self.cross_file_redirects:
            mod_import, canon_fn = self.cross_file_redirects[qname]
            call_args: List[ast.expr] = [ast.Name(id=a.arg, ctx=ast.Load()) for a in node.args.args]
            call_kw = [
                ast.keyword(arg=a.arg, value=ast.Name(id=a.arg, ctx=ast.Load()))
                for a in node.args.kwonlyargs
            ]
            imp_stmt = ast.ImportFrom(module=mod_import, names=[ast.alias(name=canon_fn, asname="_canon_fn")], level=0)
            ret_stmt = ast.Return(value=ast.Call(func=ast.Name(id="_canon_fn", ctx=ast.Load()), args=call_args, keywords=call_kw))
            node.body = [imp_stmt, ret_stmt]
            return ast.fix_missing_locations(node)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Optional[ast.AST]:
        return self._handle_fn(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Optional[ast.AST]:
        return self._handle_fn(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self.same_file_redirects:
            node.func = ast.Name(id=self.same_file_redirects[node.func.id], ctx=ast.Load())
        return node


def _apply_null_set_prune_on_scratch(
    work_repo: Path,
    null_proven: List[Dict[str, Any]],
    null_redundant: List[Dict[str, Any]],
) -> List[str]:
    """Apply AST removal of `null_proven` and deduplication of `null_redundant` inside `work_repo`."""
    drops_by_file: Dict[str, Set[str]] = {}
    for item in null_proven:
        if item.get("language") == "python" and not item.get("is_test_file"):
            drops_by_file.setdefault(str(item["file"]), set()).add(str(item["symbol"]))

    same_redir_by_file: Dict[str, Dict[str, str]] = {}
    cross_redir_by_file: Dict[str, Dict[str, Tuple[str, str]]] = {}
    for item in null_redundant:
        if item.get("language") != "python":
            continue
        f_rel = str(item["file"])
        sym = str(item["symbol"])
        canon = str(item.get("canonical_symbol") or "")
        if ":" not in canon or "." in sym:
            continue
        c_file, c_sym = canon.split(":", 1)
        if "." in c_sym:
            continue
        if c_file == f_rel:
            same_redir_by_file.setdefault(f_rel, {})[sym] = c_sym
        else:
            mod_name = c_file[:-3].replace("/", ".") if c_file.endswith(".py") else c_file
            cross_redir_by_file.setdefault(f_rel, {})[sym] = (mod_name, c_sym)

    touched: List[str] = []
    target_files = sorted(set(drops_by_file.keys()) | set(same_redir_by_file.keys()) | set(cross_redir_by_file.keys()))
    for rel_f in target_files:
        fp = work_repo / rel_f
        if not fp.is_file():
            continue
        src = fp.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=rel_f)
        tx = _ScratchRefactorTransformer(
            rel_f,
            drops_by_file.get(rel_f, set()),
            same_redir_by_file.get(rel_f, {}),
            cross_redir_by_file.get(rel_f, {}),
        )
        new_tree = ast.fix_missing_locations(tx.visit(tree))
        if not new_tree.body:
            new_tree.body = [ast.Pass()]
        rewritten = ast.unparse(new_tree) + "\n"
        ast.parse(rewritten, filename=rel_f)
        fp.write_text(rewritten, encoding="utf-8")
        touched.append(rel_f)
    return touched


def _run_gm_worker(manifest_path: Path) -> int:
    """Child subprocess worker recording stage-boundary function return snapshots via `sys.setprofile`."""
    manifest = atomic_locked_read_json(manifest_path)
    work_repo = Path(manifest["work_repo"]).resolve()
    runner_kind = str(manifest["runner_kind"])
    target_rel_script = str(manifest.get("target_rel_script") or "")
    script_args = list(manifest.get("script_args") or [])
    pytest_args = list(manifest.get("pytest_args") or [])
    tracked_symbols: Dict[str, str] = dict(manifest.get("tracked_symbols") or {})
    redundant_wrappers: Set[str] = set(manifest.get("redundant_wrappers") or [])
    out_path = Path(manifest["worker_output"]).resolve()
    for sp in reversed(list(manifest.get("host_site_packages") or [])):
        if sp not in sys.path:
            sys.path.insert(0, sp)
    for sub_pkg in ("src", "Code", "code", "lib"):
        cand_pkg = work_repo / sub_pkg
        if cand_pkg.is_dir() and str(cand_pkg) not in sys.path:
            sys.path.insert(0, str(cand_pkg))
    if str(work_repo) not in sys.path:
        sys.path.insert(0, str(work_repo))

    snapshots: Dict[str, List[Any]] = {}
    worker_budget: Dict[str, int] = {"elements": 0, "bytes": 0}
    bound_abort: Optional[AnvilRefusalError] = None

    def _frame_sym_key(fr: FrameType) -> str:
        raw_co = fr.f_code.co_filename
        if not raw_co or raw_co.startswith("<"):
            return ""
        try:
            rp = Path(raw_co).resolve()
            if not rp.is_relative_to(work_repo):
                return ""
            rel_f = rp.relative_to(work_repo).as_posix()
        except OSError:
            return ""
        fn_n = fr.f_code.co_name
        if fn_n.startswith("<"):
            return ""
        self_o = fr.f_locals.get("self")
        cls_p = f"{type(self_o).__name__}." if self_o is not None else ""
        full_k = f"{rel_f}:{cls_p}{fn_n}"
        plain_k = f"{rel_f}:{fn_n}"
        return full_k if full_k in tracked_symbols else (plain_k if plain_k in tracked_symbols else full_k)

    def _profiler(frame: FrameType, event: str, arg: Any) -> None:
        nonlocal bound_abort
        if event != "return" or bound_abort is not None:
            return
        matched_key = _frame_sym_key(frame)
        if not matched_key or matched_key not in tracked_symbols:
            return
        if frame.f_back is not None and _frame_sym_key(frame.f_back) in redundant_wrappers:
            return
        canon_bucket_key = tracked_symbols[matched_key]
        bucket = snapshots.setdefault(canon_bucket_key, [])
        try:
            _charge_gm_budget(worker_budget, elements=1, nbytes=16)
            bucket.append(_snapshot_gm_value(arg, 0, worker_budget))
        except AnvilRefusalError as b_err:
            bound_abort = b_err
            raise

    rc = 0
    err_info: Optional[str] = None
    prev_argv = list(sys.argv)
    os.chdir(str(work_repo))
    sys.setprofile(_profiler)
    try:
        if runner_kind == "pytest":
            import pytest as _pt

            rc = int(_pt.main(pytest_args))
        else:
            script_abs = str((work_repo / target_rel_script).resolve())
            sys.argv = [target_rel_script, *script_args]
            runpy.run_path(script_abs, run_name="__main__")
    except AnvilRefusalError as b_err:
        if bound_abort is None:
            bound_abort = b_err
    except SystemExit as sexc:
        code = sexc.code
        rc = int(code) if isinstance(code, int) else (0 if code is None else 1)
    except Exception as exc:
        rc = 1
        err_info = f"{type(exc).__name__}: {exc}"
    finally:
        sys.setprofile(None)
        sys.argv = prev_argv

    if bound_abort is not None:
        atomic_locked_write_json(
            out_path,
            {
                "ok": False,
                "error_code": bound_abort.error_code,
                "message": bound_abort.message,
                "details": bound_abort.details,
            },
        )
        return 3

    atomic_locked_write_json(
        out_path,
        {
            "ok": True,
            "returncode": rc,
            "error": err_info,
            "snapshots": snapshots,
        },
    )
    return rc


def _execute_gm_pass_in_scratch(
    source_repo: Path,
    policy_info: Dict[str, Any],
    tracked_symbols: Dict[str, str],
    timeout_sec: float,
    prune_spec: Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = None,
    redundant_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    scratch_dir = Path(tempfile.mkdtemp(prefix="anvil_v4_gm_"))
    try:
        work_repo = _stage_isolated_worktree_copy(source_repo, scratch_dir)
        rewritten_files: List[str] = []
        if prune_spec is not None:
            rewritten_files = _apply_null_set_prune_on_scratch(work_repo, prune_spec[0], prune_spec[1])

        iso_home = scratch_dir / "_home_tmp"
        scrubbed_env = build_scrubbed_env(iso_home)
        runner_kind = str(policy_info["runner_kind"])
        target_rel = str(policy_info["target_rel_script"] or "")
        worker_out = scratch_dir / "_gm_out.json"
        host_site_packages = [
            str(Path(p).resolve())
            for p in sys.path
            if isinstance(p, str) and "site-packages" in p and Path(p).is_dir()
        ]

        if runner_kind in {"python", "pytest"}:
            manifest_path = scratch_dir / "_gm_manifest.json"
            wrapper_list = (
                list(redundant_ids)
                if redundant_ids is not None
                else [str(r["id"]) for r in (prune_spec[1] if prune_spec else [])]
            )
            atomic_locked_write_json(
                manifest_path,
                {
                    "work_repo": str(work_repo),
                    "runner_kind": runner_kind,
                    "target_rel_script": target_rel,
                    "script_args": policy_info["script_args"],
                    "pytest_args": policy_info["pytest_args"],
                    "tracked_symbols": tracked_symbols,
                    "redundant_wrappers": wrapper_list,
                    "worker_output": str(worker_out),
                    "host_site_packages": host_site_packages,
                },
            )
            spawn_argv = [sys.executable, str(Path(__file__).resolve()), "--_gm-manifest", str(manifest_path)]
        else:
            spawn_argv = [str(policy_info["resolved_binary"]), target_rel, *policy_info["script_args"]]

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
                "Golden-Master subprocess timed out and process tree was killed.",
                details={
                    "verdict": "TRACE_TIMEOUT_KILLED",
                    "tree_killed": True,
                    "http_status": 504,
                    "timeout_sec": float(timeout_sec),
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            ) from tex

        if len(stdout_b) > MAX_GM_SNAPSHOT_BYTES:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Golden-Master stdout exceeded MAX_GM_SNAPSHOT_BYTES ({len(stdout_b)} > {MAX_GM_SNAPSHOT_BYTES}).",
                details={
                    "bound_name": "max_gm_stdout_bytes",
                    "bound_limit": MAX_GM_SNAPSHOT_BYTES,
                    "observed_value": len(stdout_b),
                },
            )
        stdout_txt = stdout_b.decode("utf-8", errors="replace")
        stderr_txt = stderr_b.decode("utf-8", errors="replace")
        snaps: Dict[str, List[Any]] = {}
        rc = int(proc.returncode or 0)
        if runner_kind in {"python", "pytest"}:
            if not worker_out.is_file():
                raise AnvilRefusalError(
                    "MALFORMED_DATA_REFUSED",
                    "Golden-Master worker failed to produce validated JSON snapshot.",
                    cwe="CWE-502",
                    details={"http_status": 502, "stderr_preview": stderr_txt[:512]},
                )
            wdata = atomic_locked_read_json(worker_out)
            if wdata.get("ok") is False:
                raise AnvilRefusalError(
                    str(wdata.get("error_code") or "BOUND_EXCEEDED_REFUSAL"),
                    str(wdata.get("message") or "Golden-Master snapshot bound exceeded."),
                    details=dict(wdata.get("details") or {}),
                )
            snaps = dict(wdata.get("snapshots") or {})
            rc = int(wdata.get("returncode", rc))
        return {
            "returncode": rc,
            "stdout": stdout_txt,
            "stderr": stderr_txt,
            "snapshots": snaps,
            "rewritten_files": rewritten_files,
        }
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. `build_refactor_map` — N1..Nk Target Map + 100% Symbol Conservation
# ---------------------------------------------------------------------------

def build_refactor_map(
    repo_dir: str | Path,
    trace_data: Optional[Dict[str, Any]] = None,
    *,
    approve_run: bool = False,
    argv: Optional[Sequence[str]] = None,
    candidate_repo: Optional[str | Path] = None,
    rtol: float = 1e-7,
    atol: float = 1e-9,
    timeout_sec: float = 30.0,
    persist: bool = True,
    paper_path: Optional[str | Path] = None,
    pipeline_id: Optional[str] = None,
    process_map: Optional[Dict[str, Any]] = None,
    allowed_root: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Synthesize Functional Core / Imperative Shell `N1..Nk` target stages,
    enforce 100% symbol conservation across the 3-Tier Null Set, and optionally
    execute consented data-only Golden-Master stage-boundary equivalence replay.
    """
    has_exec_request = bool(argv and len(argv) > 0) or (candidate_repo is not None and str(candidate_repo).strip() != "")
    if has_exec_request and not approve_run:
        raise AnvilRefusalError(
            "CONSENT_REQUIRED_REFUSED",
            "Explicit --approve-run operator consent is required before executing Golden-Master equivalence replay.",
            details={
                "isolation_boundary": ISOLATION_BOUNDARY,
                "non_vm_trust_warning": NON_VM_TRUST_WARNING,
            },
        )

    if timeout_sec <= 0 or timeout_sec > MAX_TIMEOUT_SEC:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"timeout_sec ({timeout_sec}) must be within (0, {MAX_TIMEOUT_SEC}].",
            details={"bound_name": "timeout_sec", "bound_limit": MAX_TIMEOUT_SEC, "observed_value": timeout_sec},
        )
    if rtol < 0 or math.isnan(rtol) or math.isinf(rtol):
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"rtol ({rtol}) must be finite and >= 0.",
            details={"bound_name": "rtol", "bound_limit": 1.0, "observed_value": rtol},
        )
    if atol < 0 or math.isnan(atol) or math.isinf(atol):
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"atol ({atol}) must be finite and >= 0.",
            details={"bound_name": "atol", "bound_limit": 1.0, "observed_value": atol},
        )

    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    if trace_data is not None and (not isinstance(trace_data, dict) or trace_data.get("schema") != TRACE_SCHEMA):
        raise AnvilRefusalError(
            "MALFORMED_DATA_REFUSED",
            "Invalid trace_data supplied to build_refactor_map (expected 'anvil-v4-trace/v1').",
            cwe="CWE-502",
        )

    proc_map = process_map if isinstance(process_map, dict) else build_process_map(
        root,
        trace_data=trace_data,
        persist=False,
        paper_path=paper_path,
        pipeline_id=pipeline_id,
        allowed_root=allowed_root,
    )
    (
        repo_symbols,
        prod_refs,
        test_refs,
        getattr_prefixes,
        prod_file_count,
        test_file_count,
    ) = _scan_repository_symbols_and_references(root, proc_map, trace_data)

    # Identify static/dynamic reachability for every symbol first so canonical clone selection prefers active helpers
    reachability: Dict[str, Dict[str, bool]] = {}
    for sym in repo_symbols:
        short = str(sym["short_name"])
        qname = str(sym["symbol"])
        in_prod = (short in prod_refs) or (qname in prod_refs)
        in_tests = (short in test_refs) or (qname in test_refs)
        in_dyn = any(short == gp or (len(gp) >= 3 and short.startswith(gp)) for gp in getattr_prefixes)
        is_entry = bool(sym["is_entrypoint"])
        reachability[str(sym["id"])] = {
            "in_prod": in_prod,
            "in_tests": in_tests,
            "in_dyn": in_dyn,
            "is_entry": is_entry,
            "has_static_ref": bool(in_prod or in_tests or in_dyn or is_entry),
        }

    # Select canonical pure helper for each normalized AST body fingerprint (preferring production referenced helpers)
    canonical_by_fp: Dict[str, str] = {}
    clone_candidates = [
        s for s in repo_symbols
        if s["is_pure"]
        and not s["is_entrypoint"]
        and s["norm_fingerprint"]
        and int(s["stmt_count"]) >= 2
    ]
    for cand in sorted(
        clone_candidates,
        key=lambda s: (
            0 if not s.get("is_test_file") else 1,
            0 if (reachability[s["id"]]["has_static_ref"] or int(s["traced_hits"]) > 0) else 1,
            str(s["file"]),
            int(s["start_line"]),
        ),
    ):
        fp_hash = str(cand["norm_fingerprint"])
        if fp_hash not in canonical_by_fp:
            canonical_by_fp[fp_hash] = str(cand["id"])

    mapped_raw: List[Dict[str, Any]] = []
    null_proven: List[Dict[str, Any]] = []
    null_unexercised: List[Dict[str, Any]] = []
    null_redundant: List[Dict[str, Any]] = []

    for sym in repo_symbols:
        sid_key = str(sym["id"])
        reach = reachability[sid_key]
        fp_hash = str(sym["norm_fingerprint"])
        hits = int(sym["traced_hits"])
        is_test_sym = bool(sym.get("is_test_file"))

        if (
            sym["is_pure"]
            and not sym["is_entrypoint"]
            and fp_hash
            and int(sym["stmt_count"]) >= 2
            and canonical_by_fp.get(fp_hash) not in ("", sid_key)
        ):
            null_redundant.append({
                "id": sid_key,
                "file": sym["file"],
                "symbol": sym["symbol"],
                "old_stage_id": sym["old_stage_id"],
                "language": sym["language"],
                "is_test_file": is_test_sym,
                "start_line": sym["start_line"],
                "end_line": sym["end_line"],
                "canonical_symbol": canonical_by_fp[fp_hash],
                "norm_fingerprint": fp_hash,
                "disposition": "NULL_REDUNDANT",
                "reason": f"Normalized AST body is an exact duplicate clone of '{canonical_by_fp[fp_hash]}'.",
            })
        elif not reach["has_static_ref"] and hits == 0:
            null_proven.append({
                "id": sid_key,
                "file": sym["file"],
                "symbol": sym["symbol"],
                "old_stage_id": sym["old_stage_id"],
                "language": sym["language"],
                "is_test_file": is_test_sym,
                "start_line": sym["start_line"],
                "end_line": sym["end_line"],
                "disposition": "NULL_PROVEN",
                "safe_to_delete": True,
                "reason": "Zero static callers in prod/tests, zero dynamic getattr matches, and zero traced hits.",
            })
        elif trace_data is not None and hits == 0 and reach["has_static_ref"]:
            unex_reason = (
                "Test-suite entrypoint unexercised by current runtime trace; protected from deletion."
                if (is_test_sym and sym.get("is_entrypoint"))
                else "Zero hits in supplied runtime trace, but statically reachable (CLI/flag/branch/test handler) — protected from dead-code deletion."
            )
            null_unexercised.append({
                "id": sid_key,
                "file": sym["file"],
                "symbol": sym["symbol"],
                "old_stage_id": sym["old_stage_id"],
                "language": sym["language"],
                "is_test_file": is_test_sym,
                "start_line": sym["start_line"],
                "end_line": sym["end_line"],
                "disposition": "NULL_UNEXERCISED",
                "protected_from_deletion": True,
                "reachability": reach,
                "reason": unex_reason,
            })
        else:
            mapped_raw.append(sym)

    # Assign `mapped_raw` into clean Functional Core / Imperative Shell `N1..Nk` stages
    role_buckets: Dict[str, List[Dict[str, Any]]] = {
        "imperative_shell_ingest": [],
        "functional_core_loop": [],
        "functional_core_compute": [],
        "imperative_shell_emit": [],
    }
    for sym in mapped_raw:
        if sym["is_pure"]:
            if sym["raw_kind"] == "ingest":
                role_buckets["imperative_shell_ingest"].append(sym)
            elif sym["raw_kind"] == "emit":
                role_buckets["imperative_shell_emit"].append(sym)
            elif sym["has_loop"]:
                role_buckets["functional_core_loop"].append(sym)
            else:
                role_buckets["functional_core_compute"].append(sym)
        else:
            if sym["raw_kind"] == "emit":
                role_buckets["imperative_shell_emit"].append(sym)
            else:
                role_buckets["imperative_shell_ingest"].append(sym)

    role_titles = {
        "imperative_shell_ingest": ("Imperative Shell · Ingest & CLI Boundary", "imperative_shell"),
        "functional_core_loop": ("Functional Core · Pure Iterative Solver", "functional_core"),
        "functional_core_compute": ("Functional Core · Pure Compute Kernels", "functional_core"),
        "imperative_shell_emit": ("Imperative Shell · Output & Serialization", "imperative_shell"),
    }

    target_stages: List[Dict[str, Any]] = []
    mapped_to_new: List[Dict[str, Any]] = []
    for role_key in (
        "imperative_shell_ingest",
        "functional_core_loop",
        "functional_core_compute",
        "imperative_shell_emit",
    ):
        members = role_buckets[role_key]
        if not members:
            continue
        n_idx = len(target_stages) + 1
        nid = f"N{n_idx}"
        label_base, layer_kind = role_titles[role_key]
        member_ids: List[str] = []
        split_notes: List[Dict[str, str]] = []
        for m in members:
            member_ids.append(str(m["id"]))
            mixed_split = bool((not m["is_pure"]) and m["has_math_ops"])
            if mixed_split:
                split_notes.append({
                    "symbol": m["id"],
                    "action": "Extract embedded arithmetic expressions into Functional Core and retain I/O in Imperative Shell.",
                })
            mapped_to_new.append({
                "id": m["id"],
                "file": m["file"],
                "symbol": m["symbol"],
                "old_stage_id": m["old_stage_id"],
                "target_stage_id": nid,
                "target_role": role_key,
                "layer": layer_kind,
                "is_pure": bool(m["is_pure"]),
                "mixed_io_compute": mixed_split,
                "start_line": m["start_line"],
                "end_line": m["end_line"],
                "traced_hits": m["traced_hits"],
            })

        target_stages.append({
            "id": nid,
            "stage_index": n_idx,
            "role": role_key,
            "layer": layer_kind,
            "title": f"{nid} · {label_base}",
            "is_pure_core": layer_kind == "functional_core",
            "member_symbols": member_ids,
            "symbol_count": len(member_ids),
            "mixed_io_split_notes": split_notes,
            "x": 520,
            "y": 116 + (n_idx - 1) * 172,
            "width": 368,
            "height": 132,
        })

    # Verify strict 100% mathematical symbol conservation across BOTH production and test files
    all_ids = [str(s["id"]) for s in repo_symbols]
    all_id_set = set(all_ids)
    s_mapped = {str(x["id"]) for x in mapped_to_new}
    s_proven = {str(x["id"]) for x in null_proven}
    s_unex = {str(x["id"]) for x in null_unexercised}
    s_redun = {str(x["id"]) for x in null_redundant}
    union_ids = s_mapped | s_proven | s_unex | s_redun
    unaccounted = sorted(all_id_set - union_ids)
    total_symbols = len(all_id_set)
    sum_buckets = len(mapped_to_new) + len(null_proven) + len(null_unexercised) + len(null_redundant)
    disjoint_ok = (
        len(s_mapped & s_proven) == 0
        and len(s_mapped & s_unex) == 0
        and len(s_mapped & s_redun) == 0
        and len(s_proven & s_unex) == 0
        and len(s_proven & s_redun) == 0
        and len(s_unex & s_redun) == 0
    )
    if sum_buckets != total_symbols or unaccounted or not disjoint_ok:
        raise AnvilRefusalError(
            "SYMBOL_CONSERVATION_VIOLATED",
            "Symbol conservation invariant failed across mapped_to_new and 3-Tier Null Set.",
            details={"total_symbols": total_symbols, "sum_buckets": sum_buckets, "unaccounted": unaccounted},
        )

    # Build Old-to-New (`S1..Sk <-> N1..Nk` + Null Set) Crosswalk Edges
    edge_groups: Dict[Tuple[str, str, str], List[str]] = {}
    for item in mapped_to_new:
        edge_groups.setdefault((item["old_stage_id"], item["target_stage_id"], "stage_remap"), []).append(item["id"])
    for item in null_proven:
        edge_groups.setdefault((item["old_stage_id"], "NULL_PROVEN", "null_proven"), []).append(item["id"])
    for item in null_unexercised:
        edge_groups.setdefault((item["old_stage_id"], "NULL_UNEXERCISED", "null_unexercised"), []).append(item["id"])
    for item in null_redundant:
        edge_groups.setdefault((item["old_stage_id"], "NULL_REDUNDANT", "null_redundant"), []).append(item["id"])

    crosswalk_edges: List[Dict[str, Any]] = [
        {
            "id": f"XW-{src}-{dst}",
            "from_stage": src,
            "to_stage": dst,
            "kind": kind,
            "symbol_count": len(syms),
            "symbols": syms,
        }
        for (src, dst, kind), syms in sorted(edge_groups.items())
    ]

    # Optional Consented Golden-Master Stage-Boundary Equivalence Replay
    code_executed = False
    gm_report: Dict[str, Any] = {
        "ran": False,
        "equivalent": None,
        "rtol": rtol,
        "atol": atol,
        "mode": "static_ast_zero_execution",
    }
    if approve_run and argv and len(argv) > 0:
        policy_info = validate_execution_argv(root, argv)
        tracked_map = {str(m["id"]): str(m["id"]) for m in mapped_to_new}
        redundant_wrapper_ids: List[str] = []
        for r_item in null_redundant:
            canon_target = str(r_item.get("canonical_symbol") or "")
            if canon_target in tracked_map:
                r_id = str(r_item["id"])
                tracked_map[r_id] = canon_target
                redundant_wrapper_ids.append(r_id)
        code_executed = True
        base_run = _execute_gm_pass_in_scratch(root, policy_info, tracked_map, timeout_sec, prune_spec=None)
        has_cand_repo = candidate_repo is not None and bool(str(candidate_repo).strip())
        if has_cand_repo:
            cand_root = Path(str(candidate_repo)).resolve()
            if not cand_root.exists() or not cand_root.is_dir():
                raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Candidate repository directory does not exist.", cwe="CWE-22")
            cand_policy = validate_execution_argv(cand_root, argv)
            cand_run = _execute_gm_pass_in_scratch(
                cand_root,
                cand_policy,
                tracked_map,
                timeout_sec,
                prune_spec=None,
                redundant_ids=redundant_wrapper_ids,
            )
        else:
            cand_run = _execute_gm_pass_in_scratch(
                root, policy_info, tracked_map, timeout_sec, prune_spec=(null_proven, null_redundant)
            )

        divergences: List[str] = []
        if base_run["returncode"] != cand_run["returncode"]:
            divergences.append(f"returncode mismatch ({base_run['returncode']} vs {cand_run['returncode']})")
        out_diff = _compare_stdout_streams(base_run["stdout"], cand_run["stdout"], rtol, atol)
        if out_diff is not None:
            divergences.append(out_diff)

        base_snaps = base_run["snapshots"]
        cand_snaps = cand_run["snapshots"]
        shared_syms = sorted(set(base_snaps.keys()) & set(cand_snaps.keys()))
        if set(base_snaps.keys()) != set(cand_snaps.keys()):
            missing_s = sorted(set(base_snaps.keys()) ^ set(cand_snaps.keys()))
            divergences.append(f"stage-boundary symbol set mismatch: {missing_s}")
        for skey in shared_syms:
            s_diff = _diff_gm_values(base_snaps[skey], cand_snaps[skey], rtol, atol, skey)
            if s_diff is not None:
                divergences.append(s_diff)

        gm_report = {
            "ran": True,
            "equivalent": len(divergences) == 0,
            "rtol": rtol,
            "atol": atol,
            "mode": "candidate_repo_comparison" if has_cand_repo else "scratch_null_set_prune_replay",
            "validated_argv": policy_info["validated_argv"],
            "baseline_returncode": base_run["returncode"],
            "candidate_returncode": cand_run["returncode"],
            "checked_symbols": shared_syms,
            "rewritten_files": cand_run["rewritten_files"],
            "divergences": divergences,
        }
        if divergences:
            raise AnvilRefusalError(
                "EQUIVALENCE_DIVERGENCE_REFUSED",
                "Golden-Master stage-boundary equivalence check failed: behavior-divergent rewrite refused.",
                details={
                    "isolation_boundary": ISOLATION_BOUNDARY,
                    "golden_master": gm_report,
                },
            )

    result: Dict[str, Any] = {
        "ok": True,
        "schema": REFACTOR_MAP_SCHEMA,
        "isolation_boundary": ISOLATION_BOUNDARY if code_executed else "static_ast_zero_execution",
        "non_vm_trust_warning": NON_VM_TRUST_WARNING if code_executed else "",
        "code_executed": code_executed,
        "repo_fingerprint": proc_map.get("repo_fingerprint", ""),
        "old_stages": proc_map.get("l1_stages") or [],
        "target_stages": target_stages,
        "crosswalk_edges": crosswalk_edges,
        "symbol_conservation": {
            "total_symbols": total_symbols,
            "scanned_prod_files": prod_file_count,
            "scanned_test_files": test_file_count,
            "excluded_symbols": 0,
            "mapped_to_new_count": len(mapped_to_new),
            "null_proven_count": len(null_proven),
            "null_unexercised_count": len(null_unexercised),
            "null_redundant_count": len(null_redundant),
            "conserved": True,
            "disjoint": True,
            "unaccounted_symbols": [],
        },
        "mapped_to_new": mapped_to_new,
        "null_set": {
            "null_proven": null_proven,
            "null_unexercised": null_unexercised,
            "null_redundant": null_redundant,
        },
        "golden_master": gm_report,
    }
    if persist:
        atomic_locked_write_json(root / ".anvil" / "v4" / "refactor_map.json", result)
    return result


# ---------------------------------------------------------------------------
# 4. `run_profile_and_literature` — Untraced Stage Profiler & Literature Upgrades
# ---------------------------------------------------------------------------

def _run_untraced_profiler_worker(manifest_path: Path) -> int:
    """Execute target in isolated worktree with `sys.settrace() is None` and
    lightweight `sys.setprofile` + `time.perf_counter_ns()` wall-clock timing.
    """
    manifest = atomic_locked_read_json(manifest_path)
    work_repo = Path(manifest["work_repo"]).resolve()
    runner_kind = str(manifest["runner_kind"])
    target_rel_script = str(manifest.get("target_rel_script") or "")
    script_args = list(manifest.get("script_args") or [])
    pytest_args = list(manifest.get("pytest_args") or [])
    out_path = Path(manifest["worker_output"]).resolve()
    for sp in reversed(list(manifest.get("host_site_packages") or [])):
        if sp not in sys.path:
            sys.path.insert(0, sp)
    for sp in reversed(list(manifest.get("priority_site_packages") or [])):
        if sp in sys.path:
            sys.path.remove(sp)
        sys.path.insert(0, sp)
    for sub_pkg in ("src", "Code", "code", "lib"):
        cand_pkg = work_repo / sub_pkg
        if cand_pkg.is_dir() and str(cand_pkg) not in sys.path:
            sys.path.insert(0, str(cand_pkg))
    if str(work_repo) not in sys.path:
        sys.path.insert(0, str(work_repo))

    # Guarantee zero line-by-line tracer distortion
    sys.settrace(None)
    untraced_verified = sys.gettrace() is None

    call_stack: List[Tuple[str, int, int]] = []
    inclusive_ns: Dict[str, int] = {}
    exclusive_ns: Dict[str, int] = {}
    call_counts: Dict[str, int] = {}
    prof_co_cache: Dict[str, Optional[str]] = {}

    def _prof_hook(frame: FrameType, event: str, _arg: Any) -> None:
        if event not in ("call", "return"):
            return
        raw_co = frame.f_code.co_filename
        if not raw_co or raw_co.startswith("<"):
            return
        if raw_co in prof_co_cache:
            rel_f_opt = prof_co_cache[raw_co]
        else:
            rel_f_opt = None
            try:
                rp = Path(raw_co).resolve()
                if rp.is_relative_to(work_repo):
                    rel_f_opt = rp.relative_to(work_repo).as_posix()
            except OSError:
                rel_f_opt = None
            prof_co_cache[raw_co] = rel_f_opt
        if rel_f_opt is None:
            return
        rel_f = rel_f_opt
        fn_name = frame.f_code.co_name
        if fn_name == "<module>":
            return
        cls_prefix = ""
        self_obj = frame.f_locals.get("self")
        if self_obj is not None:
            cls_prefix = f"{type(self_obj).__name__}."
        sym_id = f"{rel_f}:{cls_prefix}{fn_name}"
        now_ns = time.perf_counter_ns()
        if event == "call":
            call_counts[sym_id] = call_counts.get(sym_id, 0) + 1
            call_stack.append((sym_id, now_ns, 0))
        elif event == "return" and call_stack:
            top_sym, start_ns, child_ns = call_stack.pop()
            elapsed = max(0, now_ns - start_ns)
            inclusive_ns[top_sym] = inclusive_ns.get(top_sym, 0) + elapsed
            exclusive_ns[top_sym] = exclusive_ns.get(top_sym, 0) + max(0, elapsed - child_ns)
            if call_stack:
                p_sym, p_start, p_child = call_stack[-1]
                call_stack[-1] = (p_sym, p_start, p_child + elapsed)

    rc = 0
    err_msg: Optional[str] = None
    prev_argv = list(sys.argv)
    os.chdir(str(work_repo))
    t0_ns = time.perf_counter_ns()
    sys.setprofile(_prof_hook)
    try:
        if runner_kind == "pytest":
            import pytest as _pt

            rc = int(_pt.main(pytest_args))
        else:
            sys.argv = [target_rel_script, *script_args]
            runpy.run_path(str((work_repo / target_rel_script).resolve()), run_name="__main__")
    except SystemExit as sexc:
        code = sexc.code
        rc = int(code) if isinstance(code, int) else (0 if code is None else 1)
    except Exception as exc:
        rc = 1
        err_msg = f"{type(exc).__name__}: {exc}"
    finally:
        sys.setprofile(None)
        sys.argv = prev_argv
    total_wall_ns = max(1, time.perf_counter_ns() - t0_ns)

    atomic_locked_write_json(
        out_path,
        {
            "ok": True,
            "returncode": rc,
            "error": err_msg,
            "untraced_verified": bool(untraced_verified and sys.gettrace() is None),
            "total_wall_ns": total_wall_ns,
            "inclusive_ns": inclusive_ns,
            "exclusive_ns": exclusive_ns,
            "call_counts": call_counts,
        },
    )
    return rc


def _analyze_io_and_literature_candidates(
    root: Path,
    sym_stage_map: Dict[str, str],
    exclusive_ns: Dict[str, int],
    call_counts: Dict[str, int],
    total_wall_ns: int,
    *,
    allowed_files: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Inspect AST + runtime profile to separate Imperative-Shell I/O fixes from
    precondition-checked Functional-Core algorithmic literature upgrades.
    """
    prod_files, test_files = _scan_contained_source_files(root)
    target_files = prod_files if prod_files else test_files
    if allowed_files is not None:
        norm_allowed = {
            os.path.normpath(_strip_leading_dot_slash(str(af).strip().replace("\\", "/")).lstrip("/")).replace("\\", "/")
            for af in allowed_files
            if str(af).strip()
        }
        target_files = [fp for fp in target_files if fp.relative_to(root).as_posix() in norm_allowed]

    io_fixes: List[Dict[str, Any]] = []
    accepted_upgrades: List[Dict[str, Any]] = []
    rejected_upgrades: List[Dict[str, Any]] = []

    for fp in target_files:
        if fp.suffix != ".py":
            continue
        rel_posix = fp.relative_to(root).as_posix()
        src = fp.read_text(encoding="utf-8-sig", errors="replace")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src, filename=rel_posix)
        except SyntaxError as syn_exc:
            raise AnvilRefusalError(
                "SYNTAX_ERROR_REFUSED",
                f"Cannot analyze literature/I-O preconditions: Python source file '{rel_posix}' failed AST parsing at line {syn_exc.lineno}: {syn_exc.msg}",
                details={"file": rel_posix, "lineno": syn_exc.lineno},
            ) from syn_exc

        fn_nodes: List[Tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        for st in tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_nodes.append((st.name, st))
            elif isinstance(st, ast.ClassDef):
                for cst in st.body:
                    if isinstance(cst, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn_nodes.append((f"{st.name}.{cst.name}", cst))

        for qname, fn_node in fn_nodes:
            sym_id = f"{rel_posix}:{qname}"
            fn_line = max(1, int(getattr(fn_node, "lineno", 1) or 1))
            sid = sym_stage_map.get(sym_id, "S1")
            is_pure, _has_math, io_sites = _inspect_python_function_purity_and_math(fn_node)
            exc_ns = int(exclusive_ns.get(sym_id, 0))
            calls_n = int(call_counts.get(sym_id, 0))
            share_pct = round(100.0 * exc_ns / max(1, total_wall_ns), 2)
            unparsed = ""
            try:
                unparsed = ast.unparse(fn_node)
            except Exception:
                unparsed = ""

            # 1. Detect Imperative-Shell I/O inside loops (deduplicating nested loops, ordered by source line)
            loops = [n for n in ast.walk(fn_node) if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
            io_call_by_id: Dict[int, Tuple[int, str]] = {}
            for lp in loops:
                for sub in ast.walk(lp):
                    if isinstance(sub, ast.Call):
                        cname = sub.func.id if isinstance(sub.func, ast.Name) else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")
                        if cname in {"open", "read_text", "write_text", "read_bytes", "write_bytes", "loads", "dumps", "glob", "rglob", "print"}:
                            c_lno = max(1, int(getattr(sub, "lineno", fn_line) or fn_line))
                            io_call_by_id[id(sub)] = (c_lno, cname)
            ordered_io_hits = sorted(io_call_by_id.values(), key=lambda pair: pair[0])
            loop_io_calls = [nm for _ln, nm in ordered_io_hits]
            first_io_line = ordered_io_hits[0][0] if ordered_io_hits else fn_line
            real_io_sites = [s for s in io_sites if not s.startswith("mutation:")]
            if loop_io_calls or (not is_pure and calls_n >= 5 and real_io_sites):
                io_fixes.append({
                    "symbol": sym_id,
                    "file": rel_posix,
                    "line": first_io_line,
                    "citation_loc": f"{rel_posix}:L{first_io_line}",
                    "stage_id": sid,
                    "category": "imperative_shell_io",
                    "io_operations": list(dict.fromkeys(loop_io_calls or real_io_sites)),
                    "call_count": calls_n,
                    "exclusive_wall_ms": round(exc_ns / 1e6, 3),
                    "share_pct": share_pct,
                    "recommendation": (
                        "Batch file/serialization I/O at the Imperative Shell boundary (single buffered read/write "
                        "outside the loop) and pass plain in-memory arrays/records into the Functional Core."
                    ),
                })

            # 2. Candidate A: Naive log(sum(exp(...))) -> Log-Sum-Exp Stabilization (checked per expression node)
            lse_node_lines: List[int] = []
            for sub in ast.walk(fn_node):
                if isinstance(sub, ast.Call):
                    cname = sub.func.id if isinstance(sub.func, ast.Name) else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")
                    if cname == "log" and sub.args:
                        sub_u = ast.unparse(sub) if hasattr(ast, "unparse") else ""
                        if "sum(" in sub_u and "exp(" in sub_u and not re.search(r"\b(?:logsumexp|log_softmax)\s*\(", sub_u):
                            lse_node_lines.append(max(1, int(getattr(sub, "lineno", fn_line) or fn_line)))
            already_stabilized_lse = bool(re.search(r"\b(?:logsumexp|log_softmax)\s*\(", unparsed))
            has_lse_pattern = bool(lse_node_lines) or (
                (not already_stabilized_lse)
                and bool("log(" in unparsed and "exp(" in unparsed and "sum(" in unparsed)
            )
            lse_cite_line = min(lse_node_lines) if lse_node_lines else fn_line
            if has_lse_pattern:
                if is_pure:
                    accepted_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": lse_cite_line,
                        "citation_loc": f"{rel_posix}:L{lse_cite_line}",
                        "stage_id": sid,
                        "pattern": "naive_log_sum_exp",
                        "upgrade_id": "logsumexp_max_shift",
                        "title": "Max-Shifted Log-Sum-Exp Stabilization",
                        "citation": "Blanchard, Higham & Higham (2021), IMA J. Numer. Anal. 41(4):2311-2330",
                        "preconditions_verified": [
                            "Function is side-effect-free (is_pure=True)",
                            "Operates on finite numeric iterable/tensor without interleaved I/O",
                        ],
                        "call_count": calls_n,
                        "exclusive_wall_ms": round(exc_ns / 1e6, 3),
                        "recommendation": "Subtract m = max(x) before exponentiation: m + log(sum(exp(x_i - m))) or scipy.special.logsumexp.",
                    })
                else:
                    rejected_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": lse_cite_line,
                        "citation_loc": f"{rel_posix}:L{lse_cite_line}",
                        "stage_id": sid,
                        "candidate_upgrade": "logsumexp_max_shift",
                        "reason": f"Precondition failed: function performs impure I/O ({io_sites}) interleaved with reduction.",
                    })

            # 3. Candidate B: Explicit matrix inverse `inv(...)` -> Linear Solve / Cholesky
            inv_lines = [
                max(1, int(getattr(sub, "lineno", fn_line) or fn_line))
                for sub in ast.walk(fn_node)
                if isinstance(sub, ast.Call)
                and (sub.func.id if isinstance(sub.func, ast.Name) else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")) == "inv"
            ]
            has_inv_call = bool(inv_lines) or bool(re.search(r"\b(?:linalg\.inv|np\.linalg\.inv|torch\.linalg\.inv|inv)\s*\(", unparsed))
            inv_cite_line = min(inv_lines) if inv_lines else fn_line
            if has_inv_call:
                has_rhs_solve = bool(re.search(r"inv\s*\([^)]+\)\s*@|\b(?:matmul|dot)\s*\(\s*[\w.]*inv\s*\(", unparsed))
                if is_pure and has_rhs_solve:
                    accepted_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": inv_cite_line,
                        "citation_loc": f"{rel_posix}:L{inv_cite_line}",
                        "stage_id": sid,
                        "pattern": "explicit_matrix_inverse_multiply",
                        "upgrade_id": "linear_solve_factorization",
                        "title": "Direct LU/QR Linear Solve over Explicit Matrix Inversion",
                        "citation": "Higham (2002), Accuracy and Stability of Numerical Algorithms (2nd ed., SIAM), Ch. 14",
                        "preconditions_verified": [
                            "Function is side-effect-free (is_pure=True)",
                            "Inverse result is immediately multiplied by a right-hand side vector/matrix (A^-1 @ b)",
                        ],
                        "call_count": calls_n,
                        "exclusive_wall_ms": round(exc_ns / 1e6, 3),
                        "recommendation": "Replace inv(A) @ b with np.linalg.solve(A, b) (or scipy.linalg.cho_solve when SPD is guaranteed).",
                    })
                else:
                    rejected_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": inv_cite_line,
                        "citation_loc": f"{rel_posix}:L{inv_cite_line}",
                        "stage_id": sid,
                        "candidate_upgrade": "linear_solve_or_cholesky",
                        "reason": (
                            "Precondition failed: explicit inverse is returned standalone without a right-hand side solve target (caller requires full precision/covariance matrix A^-1) or matrix lacks verified SPD guarantee."
                            if is_pure
                            else f"Precondition failed: function is impure ({io_sites})."
                        ),
                    })

            # 4. Candidate C: Two-pass / catastrophic-cancellation variance -> Welford / Chan Online Variance
            has_naive_var = bool(
                re.search(r"\*\*\s*2", unparsed)
                and ("mean" in unparsed or "/ len(" in unparsed or "/ n" in unparsed)
                and any(k in qname.lower() for k in ("var", "std", "moment", "stat"))
            )
            if has_naive_var:
                if is_pure:
                    accepted_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": fn_line,
                        "citation_loc": f"{rel_posix}:L{fn_line}",
                        "stage_id": sid,
                        "pattern": "two_pass_or_cancellation_variance",
                        "upgrade_id": "welford_chan_online_variance",
                        "title": "Welford / Chan Numerically Stable Single-Pass Variance",
                        "citation": "Welford (1962), Technometrics 4(3):419-420; Chan, Golub & LeVeque (1983), Amer. Statist. 37(3):242-247",
                        "preconditions_verified": ["Function is side-effect-free (is_pure=True)"],
                        "call_count": calls_n,
                        "exclusive_wall_ms": round(exc_ns / 1e6, 3),
                        "recommendation": "Accumulate running mean and M2 via Welford/Chan recurrence to eliminate catastrophic cancellation.",
                    })
                else:
                    rejected_upgrades.append({
                        "symbol": sym_id,
                        "file": rel_posix,
                        "line": fn_line,
                        "citation_loc": f"{rel_posix}:L{fn_line}",
                        "stage_id": sid,
                        "candidate_upgrade": "welford_chan_online_variance",
                        "reason": f"Precondition failed: function contains impure side effects ({io_sites}).",
                    })

            # 5. Candidate D: Loop accumulation -> Vectorized Reduction (reject when loop contains impure I/O!)
            if loops and loop_io_calls and any(isinstance(n, ast.AugAssign) for n in ast.walk(fn_node)):
                rejected_upgrades.append({
                    "symbol": sym_id,
                    "file": rel_posix,
                    "line": first_io_line,
                    "citation_loc": f"{rel_posix}:L{first_io_line}",
                    "stage_id": sid,
                    "candidate_upgrade": "vectorized_simd_reduction",
                    "reason": f"Precondition failed: loop body performs impure I/O ({list(dict.fromkeys(loop_io_calls))}) and cannot be fused into a pure vectorized kernel until shell I/O is extracted.",
                })

    for fp in target_files:
        if fp.suffix not in {".js", ".mjs", ".ts", ".r", ".R"}:
            continue
        rel_posix = fp.relative_to(root).as_posix()
        src_lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        units, _ = _extract_polyglot_units(fp, rel_posix)
        for u in units:
            sym_name = str(u.get("symbol") or "")
            sym_id = f"{rel_posix}:{sym_name}"
            sid = sym_stage_map.get(sym_id, "S1")
            s_ln = max(1, int(u.get("start_line") or 1))
            e_ln = min(len(src_lines), max(s_ln, int(u.get("end_line") or s_ln)))
            body_txt = "\n".join(src_lines[s_ln - 1 : e_ln])
            exc_ns = int(exclusive_ns.get(sym_id, 0))
            calls_n = int(call_counts.get(sym_id, 0))
            share_pct = round(100.0 * exc_ns / max(1, total_wall_ns), 2)
            io_matches = re.findall(
                r"\b(?:readFileSync|writeFileSync|appendFileSync|readFile|writeFile|readLines|writeLines|read\.csv|write\.csv|saveRDS|readRDS)\b",
                body_txt,
            )
            has_loop = bool(u.get("has_loop"))
            if io_matches and (has_loop or calls_n >= 5):
                io_fixes.append({
                    "symbol": sym_id,
                    "file": rel_posix,
                    "line": s_ln,
                    "citation_loc": f"{rel_posix}:L{s_ln}",
                    "stage_id": sid,
                    "category": "imperative_shell_io",
                    "io_operations": list(dict.fromkeys(io_matches)),
                    "call_count": calls_n,
                    "exclusive_wall_ms": round(exc_ns / 1e6, 3),
                    "share_pct": share_pct,
                    "recommendation": (
                        "Batch file/serialization I/O at the Imperative Shell boundary outside hot loops "
                        "and pass in-memory buffers/vectors into the Functional Core."
                    ),
                })

    return io_fixes, accepted_upgrades, rejected_upgrades


_NODE_PROFILER_MJS = """import inspector from "node:inspector";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const workRepo = path.resolve(manifest.work_repo);
const targetRelScript = manifest.target_rel_script;
const targetAbsPath = path.resolve(workRepo, targetRelScript);
const unitIndex = manifest.unit_index || [];
const outPath = manifest.worker_output;

function urlToRepoRel(url) {
  if (!url || !url.startsWith("file://")) return null;
  let abs = "";
  try {
    abs = path.resolve(fileURLToPath(url));
  } catch {
    return null;
  }
  const relNative = path.relative(workRepo, abs);
  if (!relNative || relNative.startsWith("..") || path.isAbsolute(relNative)) return null;
  return relNative.split(path.sep).join("/");
}

function lookupUnit(relFile, line1Based, fnName) {
  if (fnName) {
    for (const u of unitIndex) {
      if (u.file === relFile && (u.symbol === fnName || u.short_name === fnName)) {
        return u;
      }
    }
  }
  let best = null;
  for (const u of unitIndex) {
    if (u.file === relFile && line1Based >= u.start_line && line1Based <= u.end_line) {
      if (!best || (u.end_line - u.start_line) < (best.end_line - best.start_line)) {
        best = u;
      }
    }
  }
  return best;
}

const session = new inspector.Session();
session.connect();
const post = (method, params = {}) =>
  new Promise((resolve, reject) => session.post(method, params, (err, res) => (err ? reject(err) : resolve(res))));

await post("Profiler.enable");
await post("Profiler.setSamplingInterval", { interval: 100 });
await post("Profiler.startPreciseCoverage", { callCount: true, detailed: true });
await post("Profiler.start");

process.argv = [process.execPath, targetAbsPath, ...(manifest.script_args || [])];
let rc = 0;
let errMsg = null;
const t0Ns = process.hrtime.bigint();
try {
  await import(pathToFileURL(targetAbsPath).href);
} catch (err) {
  rc = 1;
  errMsg = String((err && (err.stack || err.message)) || err).slice(0, 512);
}
const rawElapsedNs = process.hrtime.bigint() - t0Ns;
const totalWallNs = Number(rawElapsedNs > 1n ? rawElapsedNs : 1n);

const profRes = await post("Profiler.stop");
const covRes = await post("Profiler.takePreciseCoverage");
await post("Profiler.stopPreciseCoverage");
session.disconnect();
if (rc === 0 && typeof process.exitCode === "number" && process.exitCode !== 0) {
  rc = process.exitCode;
}

const callCounts = new Map();
const dynamicWork = new Map();

for (const scriptCov of covRes.result || []) {
  const rel = urlToRepoRel(scriptCov.url);
  if (!rel) continue;
  const sp = path.resolve(workRepo, rel);
  if (!fs.existsSync(sp)) continue;
  const src = fs.readFileSync(sp, "utf8");
  const charCount = new Int32Array(Math.max(1, src.length));
  const allRanges = [];

  const lineOffsets = [0];
  for (let i = 0; i < src.length; i++) {
    if (src.charCodeAt(i) === 10) lineOffsets.push(i + 1);
  }
  const offsetToLine1 = (off) => {
    let lo = 0;
    let hi = lineOffsets.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lineOffsets[mid] <= off) lo = mid + 1;
      else hi = mid - 1;
    }
    return Math.max(1, hi + 1);
  };

  const v8FnCallCount = new Map();
  for (const fn of scriptCov.functions || []) {
    const r0 = fn.ranges && fn.ranges[0];
    if (r0 && fn.functionName) {
      const cnt = Number(r0.count || 0);
      const fnLine1 = offsetToLine1(Math.max(0, Number(r0.startOffset || 0)));
      const u = lookupUnit(rel, fnLine1, fn.functionName);
      const symId = u ? `${u.file}:${u.symbol}` : `${rel}:${fn.functionName}`;
      v8FnCallCount.set(symId, (v8FnCallCount.get(symId) || 0) + cnt);
      if (cnt > 0) {
        callCounts.set(symId, (callCounts.get(symId) || 0) + cnt);
      }
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
        const u = lookupUnit(rel, lno, "");
        const symId = u ? `${u.file}:${u.symbol}` : `${rel}:script_${path.parse(rel).name}`;
        if (!v8FnCallCount.has(symId) || v8FnCallCount.get(symId) > 0) {
          dynamicWork.set(symId, (dynamicWork.get(symId) || 0) + maxHit);
          if (!callCounts.has(symId)) {
            callCounts.set(symId, 1);
          }
        }
      }
    }
    offset += rawLn.length + 1;
  }
}

const sampleExcNs = new Map();
const sampleIncNs = new Map();
const profile = (profRes && profRes.profile) || {};
const nodes = profile.nodes || [];
const nodeById = new Map();
const parentById = new Map();
for (const n of nodes) {
  nodeById.set(n.id, n);
  for (const ch of n.children || []) {
    parentById.set(ch, n.id);
  }
}

function nodeToSymId(node) {
  if (!node || !node.callFrame) return null;
  const cf = node.callFrame;
  const rel = urlToRepoRel(cf.url);
  if (!rel) return null;
  const line1 = Math.max(1, Number(cf.lineNumber || 0) + 1);
  const fnName = cf.functionName || "";
  const u = lookupUnit(rel, line1, fnName);
  if (u) return `${u.file}:${u.symbol}`;
  if (fnName) return `${rel}:${fnName}`;
  return `${rel}:script_${path.parse(rel).name}`;
}

const samples = profile.samples || [];
const timeDeltas = profile.timeDeltas || [];
if (samples.length > 0) {
  for (let i = 0; i < samples.length; i++) {
    const deltaNs = Math.max(1000, Number(timeDeltas[i] || 100) * 1000);
    let curId = samples[i];
    const repoChain = [];
    const seenOnStack = new Set();
    while (curId !== undefined && nodeById.has(curId)) {
      const nd = nodeById.get(curId);
      const sym = nodeToSymId(nd);
      if (sym) {
        repoChain.push(sym);
        seenOnStack.add(sym);
      }
      curId = parentById.get(curId);
    }
    if (repoChain.length > 0) {
      const leaf = repoChain[0];
      sampleExcNs.set(leaf, (sampleExcNs.get(leaf) || 0) + deltaNs);
      for (const s of seenOnStack) {
        sampleIncNs.set(s, (sampleIncNs.get(s) || 0) + deltaNs);
      }
      if (!callCounts.has(leaf)) callCounts.set(leaf, 1);
    }
  }
} else {
  for (const nd of nodes) {
    const hc = Number(nd.hitCount || 0);
    if (hc > 0) {
      const sym = nodeToSymId(nd);
      if (sym) {
        const dns = hc * 100000;
        sampleExcNs.set(sym, (sampleExcNs.get(sym) || 0) + dns);
        sampleIncNs.set(sym, (sampleIncNs.get(sym) || 0) + dns);
        if (!callCounts.has(sym)) callCounts.set(sym, 1);
      }
    }
  }
}

let sumSampledExc = 0;
for (const v of sampleExcNs.values()) sumSampledExc += v;
const unsampledNs = Math.max(0, totalWallNs - sumSampledExc);

let totalWorkWeight = 0;
for (const [symId, cnt] of callCounts.entries()) {
  if (cnt > 0) {
    const w = Math.max(1, dynamicWork.get(symId) || cnt);
    dynamicWork.set(symId, w);
    totalWorkWeight += w;
  }
}

const exclusiveNsObj = {};
const inclusiveNsObj = {};
const callCountsObj = {};
for (const [symId, cnt] of callCounts.entries()) {
  if (cnt <= 0) continue;
  const w = dynamicWork.get(symId) || 1;
  const propShare = totalWorkWeight > 0 ? Math.round((unsampledNs * w) / totalWorkWeight) : 0;
  const exc = Math.max(1, (sampleExcNs.get(symId) || 0) + propShare);
  const inc = Math.max(exc, sampleIncNs.get(symId) || 0);
  exclusiveNsObj[symId] = exc;
  inclusiveNsObj[symId] = inc;
  callCountsObj[symId] = cnt;
}

const effectiveTotalNs = Math.max(
  totalWallNs,
  Object.values(exclusiveNsObj).reduce((acc, v) => acc + v, 0),
  1
);

fs.writeFileSync(
  outPath,
  JSON.stringify(
    {
      ok: true,
      returncode: rc,
      error: errMsg,
      untraced_verified: true,
      total_wall_ns: effectiveTotalNs,
      inclusive_ns: inclusiveNsObj,
      exclusive_ns: exclusiveNsObj,
      call_counts: callCountsObj,
    },
    null,
    2
  ),
  "utf8"
);
"""

_R_PROFILER_SCRIPT = r"""args <- commandArgs(trailingOnly = TRUE)
cfg <- readLines(args[1], warn = FALSE, encoding = "UTF-8")
target_rel <- cfg[1]
raw_out <- cfg[2]

prof_env <- new.env(parent = globalenv())
rprof_file <- tempfile(pattern = "anvil_rprof_", fileext = ".out")
sample_interval_sec <- 0.001
sample_ns <- sample_interval_sec * 1e9

rc <- 0L
err_msg <- ""
t0_all <- proc.time()[["elapsed"]]
rprof_active <- FALSE
tryCatch({
  tryCatch({
    utils::Rprof(filename = rprof_file, interval = sample_interval_sec, line.profiling = TRUE)
    rprof_active <- TRUE
  }, error = function(e) NULL)
  base::source(file = target_rel, local = prof_env, echo = FALSE, verbose = FALSE, keep.source = TRUE)
}, error = function(e) {
  rc <<- 1L
  err_msg <<- gsub("[\r\n\t]", " ", conditionMessage(e))
}, finally = {
  if (rprof_active) {
    tryCatch(utils::Rprof(NULL), error = function(e) NULL)
  }
})
total_ns <- max(1000, round((proc.time()[["elapsed"]] - t0_all) * 1e9))

fn_calls <- new.env(hash = TRUE, parent = emptyenv())
fn_inc_ns <- new.env(hash = TRUE, parent = emptyenv())
fn_exc_ns <- new.env(hash = TRUE, parent = emptyenv())
line_self_ns <- new.env(hash = TRUE, parent = emptyenv())
file_table <- new.env(hash = TRUE, parent = emptyenv())
wd_norm <- paste0(gsub("\\\\", "/", normalizePath(getwd(), winslash = "/", mustWork = FALSE)), "/")

norm_rel_path <- function(p) {
  clean_p <- gsub("\\\\", "/", p)
  abs_p <- gsub("\\\\", "/", normalizePath(clean_p, winslash = "/", mustWork = FALSE))
  if (startsWith(abs_p, wd_norm)) {
    return(substr(abs_p, nchar(wd_norm) + 1L, nchar(abs_p)))
  }
  clean_p
}

sample_ticks <- 0L
if (file.exists(rprof_file)) {
  prof_lines <- tryCatch(readLines(rprof_file, warn = FALSE, encoding = "UTF-8"), error = function(e) character(0))
  unlink(rprof_file)
  for (pln in prof_lines) {
    if (!nzchar(pln) || grepl("sample\\.interval=", pln)) next
    if (startsWith(pln, "#File ")) {
      m <- regexec("^#File ([0-9]+): (.*)$", pln)
      parts <- regmatches(pln, m)[[1L]]
      if (length(parts) >= 3L) {
        assign(parts[2L], norm_rel_path(parts[3L]), envir = file_table)
      }
      next
    }
    raw_toks <- regmatches(pln, gregexpr('"[^"]+"', pln))[[1L]]
    if (length(raw_toks) == 0L) next
    toks <- gsub('^"|"$', "", raw_toks)
    sample_ticks <- sample_ticks + 1L

    loc_hits <- toks[grepl("^[0-9]+#[0-9]+$", toks)]
    if (length(loc_hits) >= 1L) {
      sp <- strsplit(loc_hits[1L], "#", fixed = TRUE)[[1L]]
      f_idx <- sp[1L]
      ln_num <- as.integer(sp[2L])
      rel_f <- if (exists(f_idx, envir = file_table, inherits = FALSE)) get(f_idx, envir = file_table) else target_rel
      lkey <- paste(rel_f, ln_num, sep = "\t")
      prev_l <- if (exists(lkey, envir = line_self_ns, inherits = FALSE)) get(lkey, envir = line_self_ns) else 0
      assign(lkey, prev_l + sample_ns, envir = line_self_ns)
    }

    user_fns <- character(0)
    for (tk in toks) {
      if (grepl("^[0-9]+#[0-9]+$", tk) || tk == "source") next
      if (exists(tk, envir = prof_env, inherits = FALSE)) {
        val <- get(tk, envir = prof_env, inherits = FALSE)
        if (is.function(val)) user_fns <- c(user_fns, tk)
      }
    }
    if (length(user_fns) >= 1L) {
      self_fn <- paste(target_rel, user_fns[1L], sep = ":")
      prev_e <- if (exists(self_fn, envir = fn_exc_ns, inherits = FALSE)) get(self_fn, envir = fn_exc_ns) else 0
      assign(self_fn, prev_e + sample_ns, envir = fn_exc_ns)
      for (uf in unique(user_fns)) {
        fkey <- paste(target_rel, uf, sep = ":")
        prev_c <- if (exists(fkey, envir = fn_calls, inherits = FALSE)) get(fkey, envir = fn_calls) else 0L
        prev_i <- if (exists(fkey, envir = fn_inc_ns, inherits = FALSE)) get(fkey, envir = fn_inc_ns) else 0
        assign(fkey, prev_c + 1L, envir = fn_calls)
        assign(fkey, prev_i + sample_ns, envir = fn_inc_ns)
      }
    }
  }
}

expr_rows <- character(0)
for (lkey in ls(line_self_ns, all.names = TRUE)) {
  sp <- strsplit(lkey, "\t", fixed = TRUE)[[1L]]
  ns_val <- get(lkey, envir = line_self_ns)
  expr_rows <- c(expr_rows, paste("EXPR", sp[1L], sp[2L], sp[2L], sprintf("%.0f", ns_val), sep = "\t"))
}

if (sample_ticks == 0L) {
  src_lines <- tryCatch(readLines(target_rel, warn = FALSE, encoding = "UTF-8"), error = function(e) character(0))
  n_lines <- max(1L, length(src_lines))
  expr_rows <- c(expr_rows, paste("EXPR", target_rel, 1L, n_lines, sprintf("%.0f", total_ns), sep = "\t"))
}

out_lines <- c(paste("META", sprintf("%.0f", total_ns), rc, err_msg, sep = "\t"))
for (k in ls(fn_calls, all.names = TRUE)) {
  c_val <- get(k, envir = fn_calls)
  i_val <- get(k, envir = fn_inc_ns)
  e_val <- if (exists(k, envir = fn_exc_ns, inherits = FALSE)) get(k, envir = fn_exc_ns) else 1000
  out_lines <- c(out_lines, paste("FN", k, c_val, sprintf("%.0f", i_val), sprintf("%.0f", e_val), sep = "\t"))
}
out_lines <- c(out_lines, expr_rows)
writeLines(out_lines, con = raw_out, useBytes = TRUE)
"""


def _parse_r_profiler_output(
    raw_tsv: Path,
    unit_index: List[Dict[str, Any]],
    fallback_wall_ns: int,
    fallback_rc: int,
) -> Dict[str, Any]:
    rows = raw_tsv.read_text(encoding="utf-8", errors="replace").splitlines()
    total_wall_ns = max(1, fallback_wall_ns)
    rc = fallback_rc
    inclusive_ns: Dict[str, int] = {}
    exclusive_ns: Dict[str, int] = {}
    call_counts: Dict[str, int] = {}

    for row in rows:
        parts = row.split("\t")
        if not parts:
            continue
        if parts[0] == "META" and len(parts) >= 3:
            try:
                total_wall_ns = max(1, int(float(parts[1] or fallback_wall_ns)))
                rc = int(parts[2] or fallback_rc)
            except ValueError:
                pass
        elif parts[0] == "FN" and len(parts) >= 5:
            sym_key = parts[1]
            c_cnt = int(parts[2] or 0)
            inc_v = max(1, int(float(parts[3] or 1)))
            exc_v = max(1, int(float(parts[4] or 1)))
            if c_cnt > 0:
                call_counts[sym_key] = call_counts.get(sym_key, 0) + c_cnt
                inclusive_ns[sym_key] = inclusive_ns.get(sym_key, 0) + inc_v
                exclusive_ns[sym_key] = exclusive_ns.get(sym_key, 0) + exc_v
        elif parts[0] == "EXPR" and len(parts) >= 5:
            rel_f = parts[1]
            l1 = int(parts[2] or 1)
            l2 = int(parts[3] or l1)
            self_ns = max(1, int(float(parts[4] or 1)))
            matched_u: Optional[Dict[str, Any]] = None
            for u in unit_index:
                if u["file"] == rel_f and not (l2 < int(u["start_line"]) or l1 > int(u["end_line"])):
                    if matched_u is None or (int(u["end_line"]) - int(u["start_line"])) < (
                        int(matched_u["end_line"]) - int(matched_u["start_line"])
                    ):
                        matched_u = u
            if matched_u is not None:
                sym_key = f"{matched_u['file']}:{matched_u['symbol']}"
                exclusive_ns[sym_key] = exclusive_ns.get(sym_key, 0) + self_ns
                inclusive_ns[sym_key] = max(inclusive_ns.get(sym_key, 0) + self_ns, exclusive_ns[sym_key])
                call_counts[sym_key] = max(1, call_counts.get(sym_key, 0))

    total_wall_ns = max(total_wall_ns, sum(exclusive_ns.values()), 1)
    return {
        "untraced_verified": True,
        "total_wall_ns": total_wall_ns,
        "inclusive_ns": inclusive_ns,
        "exclusive_ns": exclusive_ns,
        "call_counts": call_counts,
        "returncode": rc,
    }


def run_profile_and_literature(
    repo_dir: str | Path,
    *,
    approve_run: bool = False,
    argv: Optional[Sequence[str]] = None,
    timeout_sec: float = 30.0,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run static AST I/O + precondition-checked literature analysis by default when
    approval and execution argv are omitted, or run a consented untraced
    (`sys.settrace() is None`) wall-clock stage profiler in an isolated scratch
    worktree when `--approve-run` and an explicit `-- <argv...>` are supplied.
    """
    if timeout_sec <= 0 or timeout_sec > MAX_TIMEOUT_SEC:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"timeout_sec ({timeout_sec}) must be within (0, {MAX_TIMEOUT_SEC}].",
            details={"bound_name": "timeout_sec", "bound_limit": MAX_TIMEOUT_SEC, "observed_value": timeout_sec},
        )

    clean_argv = [str(x) for x in (argv or []) if str(x).strip()]
    if not approve_run and len(clean_argv) > 0:
        raise AnvilRefusalError(
            "CONSENT_REQUIRED_REFUSED",
            "Explicit --approve-run operator consent is required when supplying an execution argv to profile-lit.",
            details={
                "isolation_boundary": ISOLATION_BOUNDARY,
                "non_vm_trust_warning": NON_VM_TRUST_WARNING,
            },
        )

    root = Path(repo_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository directory does not exist.", cwe="CWE-22")

    proc_map = build_process_map(root, persist=False)
    scope_meta = proc_map.get("paper_matched_scopes") if isinstance(proc_map, dict) else None
    scoped_allow: Optional[Set[str]] = None
    if isinstance(scope_meta, dict) and scope_meta.get("scoped") and scope_meta.get("active_files"):
        scoped_allow = set(scope_meta["active_files"])
    sym_stage_map: Dict[str, str] = {}
    sym_line_map: Dict[str, Tuple[str, int]] = {}
    for step in proc_map.get("l2_steps") or []:
        cref = step.get("code_ref") or {}
        cf = str(cref.get("file") or "")
        cs = str(cref.get("symbol") or "").split("#", 1)[0]
        if cf and cs:
            sym_line_map[f"{cf}:{cs}"] = (cf, max(1, int(cref.get("start_line") or 1)))
    for stg in proc_map.get("l1_stages") or []:
        sid = str(stg["id"])
        for msym in stg.get("member_symbols") or []:
            sym_stage_map[msym.split("#", 1)[0]] = sid

    if not approve_run:
        io_fixes_static, accepted_static, rejected_static = _analyze_io_and_literature_candidates(
            root, sym_stage_map, {}, {}, 1, allowed_files=scoped_allow
        )
        static_stage_hotspots = [
            {
                "stage_id": str(stg["id"]),
                "title": stg.get("title", str(stg["id"])),
                "call_count": 0,
                "wall_ns": 0,
                "wall_ms": 0.0,
                "share_pct": 0.0,
                "measured": False,
            }
            for stg in (proc_map.get("l1_stages") or [])
        ]
        static_doc: Dict[str, Any] = {
            "ok": True,
            "schema": PROFILE_LIT_SCHEMA,
            "profile_mode": "STATIC_AST_ONLY",
            "isolation_boundary": "static_ast_zero_execution",
            "code_executed": False,
            "approve_run": False,
            "untraced_execution": False,
            "validated_argv": [],
            "returncode": None,
            "total_wall_ms": 0.0,
            "stage_hotspots": static_stage_hotspots,
            "function_hotspots": [],
            "imperative_shell_io_fixes": io_fixes_static,
            "functional_core_kernel_upgrades": accepted_static,
            "rejected_kernel_upgrades": rejected_static,
            "stdout_preview": "",
        }
        if persist:
            atomic_locked_write_json(root / ".anvil" / "v4" / "profile_lit.json", static_doc)
        return static_doc

    policy_info = validate_execution_argv(root, clean_argv)
    runner_kind = str(policy_info["runner_kind"])
    resolved_binary = str(policy_info.get("resolved_binary") or "")
    if runner_kind in {"node", "rscript"} and (
        not resolved_binary or (not Path(resolved_binary).is_file() and shutil.which(resolved_binary) is None)
    ):
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

    unit_index = _build_unit_index(root, proc_map)

    scratch_dir = Path(tempfile.mkdtemp(prefix="anvil_v4_prof_"))
    try:
        work_repo = _stage_isolated_worktree_copy(root, scratch_dir)
        target_rel = str(policy_info["target_rel_script"] or "")
        if target_rel and not (work_repo / target_rel).is_file():
            raise AnvilRefusalError(
                "EXECUTION_POLICY_REFUSED",
                f"Target script '{target_rel}' is gitignored or excluded as sensitive and cannot be staged.",
                cwe="CWE-78",
            )
        iso_home = scratch_dir / "_home_tmp"
        scrubbed_env = build_scrubbed_env(iso_home)
        worker_out = scratch_dir / "_prof_out.json"
        r_raw_tsv = scratch_dir / "_r_prof_out.tsv"
        host_site_packages = [
            str(Path(p).resolve())
            for p in sys.path
            if isinstance(p, str) and "site-packages" in p and Path(p).is_dir()
        ]
        priority_site_packages: List[str] = []
        for anc in (root, root.parent, root.parent.parent):
            for vname in (".venv", "venv"):
                cand_win = anc / vname / "Lib" / "site-packages"
                if cand_win.is_dir():
                    c_res = str(cand_win.resolve())
                    if c_res not in priority_site_packages:
                        priority_site_packages.append(c_res)
                for cand_pos in (anc / vname / "lib").glob("python*/site-packages"):
                    if cand_pos.is_dir():
                        cp_res = str(cand_pos.resolve())
                        if cp_res not in priority_site_packages:
                            priority_site_packages.append(cp_res)
            hint_file = anc / ".anvil" / "runtime_env.json"
            if hint_file.is_file():
                try:
                    hint_doc = json.loads(hint_file.read_text(encoding="utf-8"))
                    for extra_sp in (hint_doc.get("extra_site_packages") or []):
                        if isinstance(extra_sp, str) and extra_sp and Path(extra_sp).is_dir():
                            ex_res = str(Path(extra_sp).resolve())
                            if ex_res not in priority_site_packages:
                                priority_site_packages.append(ex_res)
                except Exception:
                    pass

        manifest_path = scratch_dir / "_prof_manifest.json"
        atomic_locked_write_json(
            manifest_path,
            {
                "work_repo": str(work_repo),
                "runner_kind": runner_kind,
                "target_rel_script": target_rel,
                "script_args": policy_info["script_args"],
                "pytest_args": policy_info["pytest_args"],
                "unit_index": unit_index,
                "worker_output": str(worker_out),
                "priority_site_packages": priority_site_packages,
                "host_site_packages": host_site_packages,
            },
        )

        t_start_ns = time.perf_counter_ns()
        if runner_kind in {"python", "pytest"}:
            spawn_argv = [sys.executable, str(Path(__file__).resolve()), "--_prof-manifest", str(manifest_path)]
        elif runner_kind == "node":
            node_prof_mjs = scratch_dir / "_anvil_node_profiler.mjs"
            node_prof_mjs.write_text(_NODE_PROFILER_MJS, encoding="utf-8")
            spawn_argv = [resolved_binary, str(node_prof_mjs), str(manifest_path)]
        elif runner_kind == "rscript":
            r_prof_file = scratch_dir / "_anvil_r_profiler.R"
            r_cfg_file = scratch_dir / "_r_prof_cfg.txt"
            r_prof_file.write_text(_R_PROFILER_SCRIPT, encoding="utf-8")
            r_cfg_file.write_text(f"{target_rel}\n{r_raw_tsv}\n", encoding="utf-8")
            spawn_argv = [resolved_binary, "--vanilla", str(r_prof_file), str(r_cfg_file), *policy_info["script_args"]]
        else:
            spawn_argv = [resolved_binary, target_rel, *policy_info["script_args"]]

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
                "Profiler subprocess timed out and process tree was killed.",
                details={
                    "verdict": "TRACE_TIMEOUT_KILLED",
                    "tree_killed": True,
                    "http_status": 504,
                    "timeout_sec": float(timeout_sec),
                    "isolation_boundary": ISOLATION_BOUNDARY,
                },
            ) from tex
        outer_wall_ns = max(1, time.perf_counter_ns() - t_start_ns)

        if runner_kind in {"python", "pytest", "node"}:
            if not worker_out.is_file():
                raise AnvilRefusalError(
                    "MALFORMED_DATA_REFUSED",
                    "Profiler worker failed to emit validated JSON output.",
                    cwe="CWE-502",
                    details={"http_status": 502, "stderr_preview": stderr_b.decode("utf-8", errors="replace")[:512]},
                )
            wdata = atomic_locked_read_json(worker_out)
            untraced_ok = bool(wdata.get("untraced_verified", True))
            total_wall_ns = max(1, int(wdata.get("total_wall_ns") or outer_wall_ns))
            inclusive_ns = {str(k): int(v) for k, v in (wdata.get("inclusive_ns") or {}).items()}
            exclusive_ns = {str(k): int(v) for k, v in (wdata.get("exclusive_ns") or {}).items()}
            call_counts = {str(k): int(v) for k, v in (wdata.get("call_counts") or {}).items()}
            rc = int(wdata.get("returncode", proc.returncode or 0))
        elif runner_kind == "rscript":
            if not r_raw_tsv.is_file():
                raise AnvilRefusalError(
                    "MALFORMED_DATA_REFUSED",
                    "R profiler worker failed to emit validated timing output.",
                    cwe="CWE-502",
                    details={"http_status": 502, "stderr_preview": stderr_b.decode("utf-8", errors="replace")[:512]},
                )
            rdata = _parse_r_profiler_output(r_raw_tsv, unit_index, outer_wall_ns, int(proc.returncode or 0))
            untraced_ok = bool(rdata["untraced_verified"])
            total_wall_ns = int(rdata["total_wall_ns"])
            inclusive_ns = dict(rdata["inclusive_ns"])
            exclusive_ns = dict(rdata["exclusive_ns"])
            call_counts = dict(rdata["call_counts"])
            rc = int(rdata["returncode"])
        else:
            untraced_ok = True
            total_wall_ns = outer_wall_ns
            inclusive_ns = {}
            exclusive_ns = {}
            call_counts = {}
            rc = int(proc.returncode or 0)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    stage_exclusive_ns: Dict[str, int] = {str(s["id"]): 0 for s in (proc_map.get("l1_stages") or [])}
    stage_calls: Dict[str, int] = {str(s["id"]): 0 for s in (proc_map.get("l1_stages") or [])}
    function_hotspots: List[Dict[str, Any]] = []
    sum_exc_ns = max(1, sum(exclusive_ns.values()) or total_wall_ns)

    for sym_id, exc_val in sorted(exclusive_ns.items(), key=lambda kv: kv[1], reverse=True):
        sid = sym_stage_map.get(sym_id, "S1")
        stage_exclusive_ns[sid] = stage_exclusive_ns.get(sid, 0) + exc_val
        c_cnt = call_counts.get(sym_id, 0)
        stage_calls[sid] = stage_calls.get(sid, 0) + c_cnt
        mapped_loc = sym_line_map.get(sym_id)
        if mapped_loc is None:
            for u_ent in unit_index:
                if f"{u_ent.get('file')}:{u_ent.get('symbol')}" == sym_id or f"{u_ent.get('file')}:{u_ent.get('short_name')}" == sym_id:
                    mapped_loc = (str(u_ent["file"]), max(1, int(u_ent.get("start_line") or 1)))
                    break
        f_rel_h = mapped_loc[0] if mapped_loc else (sym_id.split(":", 1)[0] if ":" in sym_id else "")
        ln_h = mapped_loc[1] if mapped_loc else None
        function_hotspots.append({
            "symbol": sym_id,
            "file": f_rel_h,
            "line": ln_h,
            "citation_loc": f"{f_rel_h}:L{ln_h}" if (f_rel_h and ln_h is not None) else (f_rel_h or sym_id),
            "stage_id": sid,
            "call_count": c_cnt,
            "exclusive_wall_ns": exc_val,
            "exclusive_wall_ms": round(exc_val / 1e6, 4),
            "inclusive_wall_ms": round(inclusive_ns.get(sym_id, exc_val) / 1e6, 4),
            "share_pct": round(100.0 * exc_val / sum_exc_ns, 2),
        })

    stage_hotspots: List[Dict[str, Any]] = []
    for stg in proc_map.get("l1_stages") or []:
        sid = str(stg["id"])
        s_ns = stage_exclusive_ns.get(sid, 0)
        stage_hotspots.append({
            "stage_id": sid,
            "title": stg.get("title", sid),
            "call_count": stage_calls.get(sid, 0),
            "wall_ns": s_ns,
            "wall_ms": round(s_ns / 1e6, 4),
            "share_pct": round(100.0 * s_ns / sum_exc_ns, 2) if sum(stage_exclusive_ns.values()) > 0 else 0.0,
        })
    stage_hotspots.sort(key=lambda x: x["wall_ns"], reverse=True)

    io_fixes, accepted_upgrades, rejected_upgrades = _analyze_io_and_literature_candidates(
        root, sym_stage_map, exclusive_ns, call_counts, sum_exc_ns, allowed_files=scoped_allow
    )

    out_doc: Dict[str, Any] = {
        "ok": True,
        "schema": PROFILE_LIT_SCHEMA,
        "profile_mode": "CONSENTED_UNTRACED_RUNTIME",
        "isolation_boundary": ISOLATION_BOUNDARY,
        "non_vm_trust_warning": NON_VM_TRUST_WARNING,
        "code_executed": True,
        "approve_run": True,
        "untraced_execution": untraced_ok,
        "validated_argv": policy_info["validated_argv"],
        "returncode": rc,
        "total_wall_ms": round(total_wall_ns / 1e6, 4),
        "stage_hotspots": stage_hotspots,
        "function_hotspots": function_hotspots[:25],
        "imperative_shell_io_fixes": io_fixes,
        "functional_core_kernel_upgrades": accepted_upgrades,
        "rejected_kernel_upgrades": rejected_upgrades,
        "stdout_preview": stdout_b.decode("utf-8", errors="replace")[:2048],
    }
    if persist:
        atomic_locked_write_json(root / ".anvil" / "v4" / "profile_lit.json", out_doc)
    return out_doc


# ---------------------------------------------------------------------------
# 6. General AST-vs-TeX Manuscript-vs-Code Scientific Divergence Detector
# ---------------------------------------------------------------------------

DIVERGENCE_SCHEMA = "anvil-v5-manuscript-divergences/v1"

DIVERGENCE_CATEGORY_LABELS: Dict[str, str] = {
    "undocumented_warm_start_stage": "Multi-Stage Warm-Start Initialization",
    "post_fit_residual_perturbation": "Post-Fit / Pre-Epoch Parameter Perturbation",
    "multi_rate_optimizer_groups": "Multi-Rate Optimizer Parameter Groups",
    "per_group_weight_decay": "Per-Group Weight Decay / Differential L2 Shrinkage",
    "undocumented_penalty_or_shrinkage": "Undocumented Objective Penalty / Shrinkage",
    "covariate_subset_adapter": "Hardcoded Feature-Column Subset Adapter",
    "cv_selection_rule_divergence": "Cross-Validation Selection Rule Divergence",
}

_COMMON_GREEK_OR_MATH_WORDS: Set[str] = {
    "alpha", "beta", "gamma", "delta", "epsilon", "eps", "zeta", "eta", "theta",
    "kappa", "lam", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "phi", "psi", "omega",
}

_NEGATION_PREFIX_RE = re.compile(
    r"\b(?:not|no|never|without|neither|nor|omit(?:s|ted|ting)?|avoid(?:s|ed|ing)?|"
    r"exclude(?:s|d|ing)?|absent|unpenali[sz]ed|unregulari[sz]ed|do\s+not|does\s+not|did\s+not)\b",
    re.IGNORECASE,
)


def _is_archive_or_staging_rel(rel_posix: str) -> bool:
    parts = [p.lower() for p in Path(rel_posix).parts[:-1]]
    return any(p in ARCHIVE_OR_STAGING_DIRS for p in parts)


def _strip_tex_comment_line(line: str) -> str:
    return re.sub(r"(?<!\\)((?:\\\\)*)%.*$", r"\1", line)


def _extract_balanced_tex_brace(text: str, open_brace_idx: int) -> Tuple[str, int]:
    if open_brace_idx >= len(text) or text[open_brace_idx] != "{":
        return "", open_brace_idx
    depth = 1
    i = open_brace_idx + 1
    while i < len(text) and depth > 0:
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : i], i + 1
        i += 1
    return text[open_brace_idx + 1 :], len(text)


def _clean_tex_excerpt(raw: str) -> str:
    txt = re.sub(r"(?<=\d)\{,\}(?=\d)", "", raw or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    txt = txt.replace("$", "").replace("\\_", "_")
    for _ in range(3):
        txt = re.sub(r"\\(?:textbf|textit|emph|textrm|texttt|mathrm|mathbf|boldsymbol)\s*\{([^{}]*)\}", r"\1", txt)
    txt = re.sub(r"\\(?:label|cite|citep|citet|citealt)\s*\{[^{}]*\}", "", txt)
    txt = txt.replace("~", " ").replace("``", '"').replace("''", '"')
    cleaned = re.sub(r"\s+", " ", txt).strip()
    if len(cleaned) <= 280:
        return cleaned
    cut = cleaned[:277]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def _resolve_tex_child(cur_dir: Path, root_dir: Path, target: str) -> Optional[Path]:
    clean_t = target.strip().strip('"').strip("'").replace("\\", "/")
    if not clean_t or clean_t.startswith("/") or ":" in clean_t or ".." in clean_t.split("/"):
        return None
    for base in (cur_dir, root_dir):
        for suffix in ("", ".tex"):
            cand = (base / f"{clean_t}{suffix}").resolve()
            if cand.is_file() and not _is_link_or_junction(cand) and (cand == root_dir or root_dir in cand.parents):
                return cand
        rel_parent = Path(clean_t).parent
        sdir = (base / rel_parent).resolve()
        if sdir.is_dir() and (sdir == root_dir or root_dir in sdir.parents):
            want = {Path(clean_t).name.lower(), f"{Path(clean_t).name.lower()}.tex"}
            try:
                for ent in sorted(sdir.iterdir(), key=lambda p: p.name.lower()):
                    if ent.is_file() and not _is_link_or_junction(ent) and ent.name.lower() in want:
                        return ent.resolve()
            except OSError:
                pass
    return None


def _build_paragraphs_with_line_spans(prov_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group consecutive provenance lines within `(file, para_id)` into joined paragraph blocks
    while retaining character-offset spans mapped back to exact `(file, line)` records.
    """
    paragraphs: List[Dict[str, Any]] = []
    cur_key: Optional[Tuple[str, int]] = None
    cur_group: List[Dict[str, Any]] = []

    def _flush(group: List[Dict[str, Any]]) -> None:
        if not group:
            return
        norm_parts: List[str] = []
        spans: List[Tuple[int, int, Dict[str, Any]]] = []
        cursor = 0
        for pl in group:
            seg = re.sub(r"\s+", " ", str(pl.get("text") or "").replace("\\_", "_")).strip()
            if not seg:
                continue
            if norm_parts:
                norm_parts.append(" ")
                cursor += 1
            start_c = cursor
            norm_parts.append(seg)
            cursor += len(seg)
            spans.append((start_c, cursor, pl))
        if spans:
            joined = "".join(norm_parts)
            paragraphs.append({
                "file": str(group[0]["file"]),
                "section": str(group[0].get("section") or "Manuscript"),
                "text": joined,
                "spans": spans,
            })

    for pl in prov_lines:
        pkey = (str(pl["file"]), int(pl.get("para_id", 0)))
        if cur_key is not None and pkey != cur_key:
            _flush(cur_group)
            cur_group = []
        cur_key = pkey
        cur_group.append(pl)
    _flush(cur_group)
    return paragraphs


def _span_record_at_offset(para: Dict[str, Any], char_offset: int) -> Dict[str, Any]:
    spans = para.get("spans") or []
    for s_lo, s_hi, pl in spans:
        if s_lo <= char_offset < s_hi:
            return pl
    for s_lo, _s_hi, pl in reversed(spans):
        if char_offset >= s_lo:
            return pl
    return spans[0][2] if spans else {"file": para.get("file", ""), "line": 1, "text": para.get("text", ""), "section": para.get("section", "")}


def _extract_pdf_text_clean_only(pdf_path: Path) -> str:
    """Extract readable PDF text via pypdf or fitz; return '' if unavailable or unreadable (never raw %PDF bytes)."""
    for mod_name in ("pypdf", "fitz"):
        try:
            import importlib

            mod = importlib.import_module(mod_name)
            if mod_name == "pypdf":
                reader = mod.PdfReader(str(pdf_path))
                txt = "\n\n".join((pg.extract_text() or "") for pg in reader.pages[:35])
            else:
                doc = mod.open(str(pdf_path))
                txt = "\n\n".join(doc[i].get_text("text") for i in range(min(35, len(doc))))
            if txt.strip():
                return txt
        except Exception:
            continue
    return ""


def _load_manuscript_tree_for_divergence(paper_path: Optional[Path]) -> Dict[str, Any]:
    """Dispatch manuscript loading by extension (`.tex`, `.md`, `.pdf`) with exact line provenance,
    paragraph-joined prose offset spans, equation blocks, and section headings.
    """
    empty_base = {
        "has_paper": False,
        "status_kind": "no-manuscript",
        "entry_file": "",
        "files": [],
        "lines": [],
        "paragraphs": [],
        "equations": [],
        "sections": [],
    }
    if paper_path is None or not paper_path.exists():
        return dict(empty_base)

    entry = paper_path.resolve()
    if entry.is_dir():
        root_dir = entry
        all_tex = [
            p for p in entry.rglob("*.tex")
            if p.is_file() and not _is_link_or_junction(p)
        ]
        non_arch_tex = [p for p in all_tex if not _is_archive_or_staging_rel(p.relative_to(entry).as_posix())]
        tex_pool = non_arch_tex if non_arch_tex else all_tex
        if tex_pool:
            tex_cands = sorted(
                tex_pool,
                key=lambda p: (
                    0 if "\\documentclass" in p.read_text(encoding="utf-8", errors="replace") else 1,
                    0 if p.stem.lower() in ("main", "paper", "manuscript") else 1,
                    p.name.lower(),
                ),
            )
            entry = tex_cands[0]
        else:
            md_or_pdf = [
                p for p in sorted(entry.rglob("*"))
                if p.is_file()
                and not _is_link_or_junction(p)
                and p.suffix.lower() in (".md", ".markdown", ".pdf")
                and not _is_archive_or_staging_rel(p.relative_to(entry).as_posix())
            ]
            if not md_or_pdf:
                return dict(empty_base)
            entry = md_or_pdf[0]
    else:
        root_dir = entry.parent

    entry_rel = entry.relative_to(root_dir).as_posix() if (entry == root_dir or root_dir in entry.parents) else entry.name
    ext_low = entry.suffix.lower()
    try:
        head_bytes = entry.read_bytes()[:64]
    except OSError:
        return dict(empty_base)

    is_pdf_or_binary = (ext_low == ".pdf") or head_bytes.startswith(b"%PDF") or (b"\x00" in head_bytes)
    if is_pdf_or_binary:
        pdf_text = _extract_pdf_text_clean_only(entry) if (ext_low == ".pdf" or head_bytes.startswith(b"%PDF")) else ""
        if not pdf_text.strip():
            return {
                **empty_base,
                "has_paper": False,
                "status_kind": "manuscript-format-unsupported",
                "entry_file": entry_rel,
            }
        # Parse extracted PDF text as plain paragraphs without % comment stripping
        prov_lines_pdf: List[Dict[str, Any]] = []
        sections_pdf: List[Dict[str, Any]] = []
        cur_sec_pdf = "Main"
        para_id_pdf = 0
        sec_hdr_re = re.compile(r"^(?:Section\s+)?(\d+(?:\.\d+)*)\s+([A-Z][A-Za-z0-9 ,:;-]{3,80})$")
        for lno, raw_ln in enumerate(pdf_text.splitlines(), start=1):
            s_ln = raw_ln.strip()
            if not s_ln:
                para_id_pdf += 1
                continue
            m_sh = sec_hdr_re.match(s_ln)
            if m_sh:
                cur_sec_pdf = m_sh.group(2).strip()
                para_id_pdf += 1
                sections_pdf.append({"title": cur_sec_pdf, "file": entry_rel, "line": lno, "citation": f"{entry_rel}:L{lno}"})
            prov_lines_pdf.append({
                "file": entry_rel,
                "line": lno,
                "text": s_ln,
                "raw_text": raw_ln,
                "section": cur_sec_pdf,
                "parent_cite": "",
                "para_id": para_id_pdf,
            })
        return {
            "has_paper": len(prov_lines_pdf) > 0,
            "status_kind": "ok",
            "entry_file": entry_rel,
            "files": [entry_rel],
            "lines": prov_lines_pdf,
            "paragraphs": _build_paragraphs_with_line_spans(prov_lines_pdf),
            "equations": [],
            "sections": sections_pdf,
        }

    # Markdown manuscript dispatch (`.md` / `.markdown`: preserve `%`, `#` sections, `$$` math)
    if ext_low in (".md", ".markdown"):
        raw_md_lines = entry.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        prov_md: List[Dict[str, Any]] = []
        secs_md: List[Dict[str, Any]] = []
        eqs_md: List[Dict[str, Any]] = []
        cur_sec_md = "Main"
        para_id_md = 0
        md_sec_re = re.compile(r"^(#{1,4})\s+(.+)$")
        in_dd = False
        dd_buf: List[str] = []
        dd_meta: Dict[str, Any] = {}
        for lno, raw_ln in enumerate(raw_md_lines, start=1):
            s_ln = raw_ln.strip()
            if not s_ln:
                para_id_md += 1
                continue
            m_ms = md_sec_re.match(s_ln)
            if m_ms and not in_dd:
                cur_sec_md = m_ms.group(2).strip()
                para_id_md += 1
                secs_md.append({"title": cur_sec_md, "file": entry_rel, "line": lno, "citation": f"{entry_rel}:L{lno}"})
                continue
            prov_md.append({
                "file": entry_rel,
                "line": lno,
                "text": s_ln,
                "raw_text": raw_ln,
                "section": cur_sec_md,
                "parent_cite": "",
                "para_id": para_id_md,
            })
            if not in_dd and "$$" in s_ln:
                first_dd = s_ln.find("$$")
                rest_dd = s_ln[first_dd + 2 :]
                if "$$" in rest_dd:
                    eqs_md.append({
                        "file": entry_rel,
                        "line": lno,
                        "section": cur_sec_md,
                        "parent_cite": "",
                        "latex": rest_dd.split("$$", 1)[0].strip(),
                    })
                else:
                    in_dd = True
                    dd_buf = [rest_dd]
                    dd_meta = {"file": entry_rel, "line": lno, "section": cur_sec_md, "parent_cite": ""}
            elif in_dd:
                if "$$" in s_ln:
                    dd_buf.append(s_ln.split("$$", 1)[0])
                    in_dd = False
                    eqs_md.append({**dd_meta, "latex": " ".join(dd_buf).strip()})
                    dd_buf = []
                else:
                    dd_buf.append(s_ln)
        return {
            "has_paper": len(prov_md) > 0,
            "status_kind": "ok",
            "entry_file": entry_rel,
            "files": [entry_rel],
            "lines": prov_md,
            "paragraphs": _build_paragraphs_with_line_spans(prov_md),
            "equations": eqs_md,
            "sections": secs_md,
        }

    # LaTeX manuscript dispatch (`.tex` tree with preamble/comment/\end{document} handling + multi-hop \input chains)
    visited: Set[Path] = set()
    files_seen: List[str] = []
    prov_lines: List[Dict[str, Any]] = []
    inc_re = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
    sec_open_re = re.compile(r"\\(section|subsection|subsubsection)\*?\s*\{")

    cur_section = "Main"
    para_counter = 0
    sections: List[Dict[str, Any]] = []

    def _walk(tex_file: Path, parent_cite: str) -> None:
        nonlocal cur_section, para_counter
        real_f = tex_file.resolve()
        if real_f in visited or not real_f.is_file():
            return
        visited.add(real_f)
        try:
            rel_f = real_f.relative_to(root_dir).as_posix()
        except ValueError:
            rel_f = real_f.name
        if rel_f not in files_seen:
            files_seen.append(rel_f)
        raw_lines = real_f.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        cleaned_all = [_strip_tex_comment_line(rln) for rln in raw_lines]
        has_begin_doc = any("\\begin{document}" in cln for cln in cleaned_all)
        in_body = not has_begin_doc
        in_comment_env = False
        iffalse_depth = 0
        para_counter += 1

        for lno, (raw_ln, clean) in enumerate(zip(raw_lines, cleaned_all), start=1):
            s_clean = clean.strip()
            if not in_body:
                if "\\begin{document}" in clean:
                    in_body = True
                    after_bd = clean.split("\\begin{document}", 1)[1].strip()
                    if not after_bd:
                        continue
                    clean = after_bd
                    s_clean = clean
                else:
                    continue
            if "\\end{document}" in clean:
                before_ed = clean.split("\\end{document}", 1)[0].strip()
                if before_ed and not in_comment_env and iffalse_depth == 0:
                    prov_lines.append({
                        "file": rel_f,
                        "line": lno,
                        "text": before_ed,
                        "raw_text": raw_ln,
                        "section": cur_section,
                        "parent_cite": parent_cite,
                        "para_id": para_counter,
                    })
                break

            if in_comment_env:
                if "\\end{comment}" in s_clean:
                    in_comment_env = False
                    para_counter += 1
                continue
            if "\\begin{comment}" in s_clean:
                if "\\end{comment}" not in s_clean.split("\\begin{comment}", 1)[1]:
                    in_comment_env = True
                para_counter += 1
                continue
            if re.match(r"^\\iffalse\b", s_clean):
                iffalse_depth += 1
                continue
            if iffalse_depth > 0:
                if re.match(r"^\\if[A-Za-z]+", s_clean):
                    iffalse_depth += 1
                elif re.search(r"\\fi\b", s_clean):
                    iffalse_depth = max(0, iffalse_depth - 1)
                continue

            if not s_clean:
                para_counter += 1
                continue

            m_sec = sec_open_re.search(clean)
            if m_sec:
                sec_raw, _ = _extract_balanced_tex_brace(clean, m_sec.end() - 1)
                cur_section = _clean_tex_excerpt(sec_raw) or cur_section
                para_counter += 1
                sections.append({
                    "title": cur_section,
                    "file": rel_f,
                    "line": lno,
                    "citation": f"{rel_f}:L{lno}",
                })

            pos = 0
            had_inc = False
            for m_inc in inc_re.finditer(clean):
                had_inc = True
                pre = clean[pos : m_inc.start()].strip()
                if pre:
                    prov_lines.append({
                        "file": rel_f,
                        "line": lno,
                        "text": pre,
                        "raw_text": raw_ln,
                        "section": cur_section,
                        "parent_cite": parent_cite,
                        "para_id": para_counter,
                    })
                child = _resolve_tex_child(real_f.parent, root_dir, m_inc.group(1))
                if child is not None:
                    hop_cite = f"{parent_cite} -> {rel_f}:L{lno}" if parent_cite else f"{rel_f}:L{lno}"
                    _walk(child, hop_cite)
                pos = m_inc.end()
            if had_inc:
                tail = clean[pos:].strip()
                if tail:
                    prov_lines.append({
                        "file": rel_f,
                        "line": lno,
                        "text": tail,
                        "raw_text": raw_ln,
                        "section": cur_section,
                        "parent_cite": parent_cite,
                        "para_id": para_counter,
                    })
            else:
                prov_lines.append({
                    "file": rel_f,
                    "line": lno,
                    "text": clean,
                    "raw_text": raw_ln,
                    "section": cur_section,
                    "parent_cite": parent_cite,
                    "para_id": para_counter,
                })

    _walk(entry, "")

    # Extract displayed equation blocks with exact start line provenance (handling single-line \[...\] and ignoring \\[2pt])
    equations: List[Dict[str, Any]] = []
    eq_start_re = re.compile(
        r"\\begin\{(equation\*?|align\*?|alignat\*?|flalign\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}|(?<!\\)\\\[|\$\$"
    )
    in_eq = False
    closer_re: Optional[re.Pattern[str]] = None
    eq_buf: List[str] = []
    eq_meta: Dict[str, Any] = {}

    for pl in prov_lines:
        txt = str(pl["text"])
        if not in_eq:
            m_open = eq_start_re.search(txt)
            if not m_open:
                continue
            env_nm = m_open.group(1)
            tok_open = m_open.group(0)
            if env_nm:
                closer_re = re.compile(rf"\\end\{{{re.escape(env_nm)}\}}")
            elif tok_open == "$$":
                closer_re = re.compile(r"\$\$")
            else:
                closer_re = re.compile(r"(?<!\\)\\\]")
            eq_meta = {
                "file": pl["file"],
                "line": pl["line"],
                "section": pl["section"],
                "parent_cite": pl["parent_cite"],
            }
            after_open = txt[m_open.end() :]
            m_close_same = closer_re.search(after_open)
            if m_close_same:
                inner_eq = txt[m_open.start() : m_open.end() + m_close_same.end()]
                equations.append({**eq_meta, "latex": inner_eq})
                in_eq = False
                closer_re = None
                eq_buf = []
            else:
                in_eq = True
                eq_buf = [txt[m_open.start() :]]
        else:
            assert closer_re is not None
            m_close_nxt = closer_re.search(txt)
            if m_close_nxt:
                eq_buf.append(txt[: m_close_nxt.end()])
                equations.append({**eq_meta, "latex": " ".join(eq_buf)})
                in_eq = False
                closer_re = None
                eq_buf = []
            else:
                eq_buf.append(txt)

    return {
        "has_paper": len(prov_lines) > 0,
        "status_kind": "ok",
        "entry_file": entry_rel,
        "files": files_seen,
        "lines": prov_lines,
        "paragraphs": _build_paragraphs_with_line_spans(prov_lines),
        "equations": equations,
        "sections": sections,
    }


def _find_tex_line_match(
    ms: Dict[str, Any],
    patterns: Sequence[str],
    *,
    prefer_sections: Tuple[str, ...] = (),
) -> Optional[Dict[str, Any]]:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    candidates: List[Tuple[int, int, Dict[str, Any]]] = []
    paragraphs = ms.get("paragraphs") or []
    if paragraphs:
        for p_idx, para in enumerate(paragraphs):
            p_txt = str(para.get("text") or "")
            for r_idx, cre in enumerate(compiled):
                m = cre.search(p_txt)
                if m:
                    pl_rec = _span_record_at_offset(para, m.start())
                    sec_low = str(pl_rec.get("section") or para.get("section") or "").lower()
                    sec_bonus = 0 if (prefer_sections and any(ps in sec_low for ps in prefer_sections)) else 1
                    snippet_around = p_txt[max(0, m.start() - 40) : min(len(p_txt), m.end() + 180)]
                    candidates.append((
                        sec_bonus * 10 + r_idx,
                        p_idx,
                        {
                            **pl_rec,
                            "text": pl_rec.get("text") or snippet_around,
                            "matched_excerpt": snippet_around,
                            "line_idx": p_idx,
                        },
                    ))
                    break
    else:
        for idx, pl in enumerate(ms.get("lines") or []):
            txt = str(pl.get("text") or "").replace("\\_", "_")
            for r_idx, cre in enumerate(compiled):
                if cre.search(txt):
                    sec_low = str(pl.get("section") or "").lower()
                    sec_bonus = 0 if (prefer_sections and any(ps in sec_low for ps in prefer_sections)) else 1
                    candidates.append((sec_bonus * 10 + r_idx, idx, {**pl, "line_idx": idx}))
                    break
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _closest_estimation_section_label(ms: Dict[str, Any], category: str = "") -> str:
    secs = ms.get("sections") or []
    cat_kw_map: Dict[str, Tuple[str, ...]] = {
        "covariate_subset_adapter": ("model", "specif", "expert", "utility", "policy", "estimat"),
        "cv_selection_rule_divergence": ("empiric", "cross", "select", "estimat", "method", "simulat"),
        "undocumented_penalty_or_shrinkage": ("estimat", "model", "objective", "likelihood", "empiric", "method"),
    }
    kw_order = cat_kw_map.get(category, ("estimat", "method", "model", "empiric", "train", "optim", "algorithm"))
    for kw in kw_order:
        for s in secs:
            if kw in str(s.get("title") or "").lower():
                return f"{s['title']} ({s['citation']})"
    if secs:
        s0 = secs[0]
        return f"{s0['title']} ({s0['citation']})"
    entry_f = str(ms.get("entry_file") or "")
    return f"{entry_f}:L1" if entry_f else "L1"


def _has_unnegated_match_in_manuscript(ms: Dict[str, Any], pattern_str: str) -> bool:
    """Evaluate `pattern_str` across paragraph-joined prose blocks with 80-char clause negation checking."""
    if not pattern_str:
        return False
    cre = re.compile(pattern_str, re.IGNORECASE)
    paragraphs = ms.get("paragraphs")
    if paragraphs:
        for para in paragraphs:
            p_txt = str(para.get("text") or "")
            for clause in re.split(r"[.;!?]+", p_txt):
                for m in cre.finditer(clause):
                    prefix = clause[max(0, m.start() - 80) : m.start()]
                    if _NEGATION_PREFIX_RE.search(prefix):
                        continue
                    return True
        return False
    for pl in ms.get("lines") or []:
        line_txt = str(pl.get("text") or "").replace("\\_", "_")
        for clause in re.split(r"[.;!?]+", line_txt):
            for m in cre.finditer(clause):
                prefix = clause[max(0, m.start() - 80) : m.start()]
                if _NEGATION_PREFIX_RE.search(prefix):
                    continue
                return True
    return False


def verify_divergence_search_record(
    manuscript_or_path: str | Path | Dict[str, Any],
    search_record: Dict[str, Any],
) -> Dict[str, Any]:
    """Re-execute `search_record['executed_regex']` over the manuscript paragraphs to verify
    `absent_from_manuscript` / `contradicted_in_manuscript` provenance non-circularly.
    """
    ms = (
        manuscript_or_path
        if isinstance(manuscript_or_path, dict) and "lines" in manuscript_or_path
        else _load_manuscript_tree_for_divergence(Path(manuscript_or_path))
    )
    if not ms.get("has_paper"):
        return {
            "ok": False,
            "reproduced": False,
            "reason": ms.get("status_kind", "no-manuscript"),
        }
    rec_status = str((search_record or {}).get("status") or "")
    exec_re = str((search_record or {}).get("executed_regex") or "")
    if not exec_re:
        return {"ok": False, "reproduced": False, "reason": "missing_executed_regex"}
    doc_found = _has_unnegated_match_in_manuscript(ms, exec_re)
    if rec_status == "absent_from_manuscript":
        return {
            "ok": True,
            "reproduced": not doc_found,
            "status": rec_status,
            "executed_regex": exec_re,
            "unexpected_match_found": doc_found,
        }
    return {
        "ok": True,
        "reproduced": True,
        "status": rec_status,
        "executed_regex": exec_re,
        "documentation_match_found": doc_found,
    }


def _parse_python_ast_quiet(raw_src: str, filename: str = "<unknown>") -> Optional[ast.Module]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(raw_src, filename=filename)
    except SyntaxError:
        return None


def _extract_scalar_float(val: ast.AST) -> Optional[float]:
    if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)) and not isinstance(val.value, bool):
        return float(val.value)
    if (
        isinstance(val, ast.UnaryOp)
        and isinstance(val.op, ast.USub)
        and isinstance(val.operand, ast.Constant)
        and isinstance(val.operand.value, (int, float))
        and not isinstance(val.operand.value, bool)
    ):
        return -float(val.operand.value)
    return None


def _extract_module_numeric_constants(tree: ast.Module) -> Dict[str, Tuple[float, int]]:
    out: Dict[str, Tuple[float, int]] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        tgt = stmt.targets[0]
        lno = int(getattr(stmt, "lineno", 1))
        if isinstance(tgt, ast.Name):
            num = _extract_scalar_float(stmt.value)
            if num is not None:
                out[tgt.id] = (num, lno)
        elif isinstance(tgt, (ast.Tuple, ast.List)) and isinstance(stmt.value, (ast.Tuple, ast.List)):
            if len(tgt.elts) == len(stmt.value.elts):
                for t_el, v_el in zip(tgt.elts, stmt.value.elts):
                    if isinstance(t_el, ast.Name):
                        num = _extract_scalar_float(v_el)
                        if num is not None:
                            out[t_el.id] = (num, lno)
    return out


def _extract_module_index_collections(tree: ast.Module) -> Dict[str, Dict[str, Any]]:
    """Extract module-level integer column-index lists/tuples or dicts mapping keys -> integer index lists."""
    out: Dict[str, Dict[str, Any]] = {}

    def _int_list(node: ast.AST) -> Optional[List[int]]:
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            vals: List[int] = []
            for e in node.elts:
                if isinstance(e, ast.Constant) and isinstance(e.value, int) and not isinstance(e.value, bool):
                    vals.append(int(e.value))
                else:
                    return None
            return vals
        return None

    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name = stmt.targets[0].id
            lno = int(getattr(stmt, "lineno", 1))
            direct = _int_list(stmt.value)
            if direct is not None:
                out[name] = {"lineno": lno, "kind": "list", "max_cols": len(direct), "sample": repr(direct)}
            elif isinstance(stmt.value, ast.Dict) and stmt.value.values:
                sub_lists = [_int_list(v) for v in stmt.value.values if v is not None]
                if sub_lists and all(x is not None for x in sub_lists):
                    clean_subs = [x for x in sub_lists if x is not None]
                    max_len = max(len(x) for x in clean_subs)
                    out[name] = {
                        "lineno": lno,
                        "kind": "dict",
                        "max_cols": max_len,
                        "multi_col": max_len > 1,
                        "sample": ast.unparse(stmt.value)[:120] if hasattr(ast, "unparse") else name,
                    }
    return out


def detect_manuscript_code_divergences(
    repo_dir: str | Path,
    paper_path: Optional[str | Path],
    *,
    active_files: Optional[Sequence[str]] = None,
    scope_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Repository-agnostic AST-vs-TeX Manuscript-vs-Code Divergence Detector.

    Scans primary-pipeline Python ASTs against the companion `.tex` manuscript tree across
    6 general scientific estimation/modeling categories:
      1. `undocumented_warm_start_stage`
      2. `post_fit_residual_perturbation`
      3. `multi_rate_optimizer_groups`
      4. `undocumented_penalty_or_shrinkage`
      5. `covariate_subset_adapter`
      6. `cv_selection_rule_divergence`

    Suppresses mechanisms that ARE documented accurately in the manuscript equations/prose,
    and attaches mandatory `file:L<line>` code citations plus either the contradicting
    manuscript citation/passage or a structured `absent_from_manuscript` search record.
    """
    root = Path(repo_dir).resolve()
    base_dir = root if root.is_dir() else root.parent
    resolved_paper = Path(paper_path).resolve() if paper_path else None
    ms = _load_manuscript_tree_for_divergence(resolved_paper)

    if not ms["has_paper"] or not base_dir.is_dir():
        return {
            "ok": True,
            "schema": DIVERGENCE_SCHEMA,
            "has_paper": False,
            "status_kind": str(ms.get("status_kind") or "no-manuscript"),
            "entry_manuscript": str(ms.get("entry_file") or ""),
            "searched_tex_files": [],
            "scanned_files": [],
            "skipped_files": [],
            "exempted_dgp_functions": [],
            "scope_applied": False,
            "divergence_count": 0,
            "documented_non_divergence_count": 0,
            "documented_mechanisms": [],
            "divergences": [],
        }

    prod_files, _ = _scan_contained_source_files(base_dir)
    py_files = [fp for fp in prod_files if fp.suffix == ".py"]
    skipped_files: List[Dict[str, str]] = []
    scope_applied = False

    def _norm_scope_rel(raw_f: str) -> str:
        s = _strip_leading_dot_slash(str(raw_f).strip().replace("\\", "/")).lstrip("/")
        return os.path.normpath(s).replace("\\", "/") if s else ""

    # When scanning an umbrella workspace without explicit active_files, scope candidate code to the
    # manuscript's nearest ancestor sub-project containing non-archive Python source files.
    umbrella_subroot: Optional[Path] = None
    if active_files is None and resolved_paper is not None and (resolved_paper == base_dir or base_dir in resolved_paper.parents):
        cur_anc = resolved_paper if resolved_paper.is_dir() else resolved_paper.parent
        while cur_anc == base_dir or base_dir in cur_anc.parents:
            if cur_anc == base_dir:
                break
            rel_anc = cur_anc.relative_to(base_dir).as_posix()
            if not _is_archive_or_staging_rel(f"{rel_anc}/_probe.py"):
                sub_py = [
                    fp for fp in py_files
                    if (fp == cur_anc or cur_anc in fp.parents)
                    and not _is_archive_or_staging_rel(fp.relative_to(base_dir).as_posix())
                ]
                if sub_py:
                    umbrella_subroot = cur_anc
                    break
            cur_anc = cur_anc.parent

    if umbrella_subroot is not None:
        kept_umbrella: List[Path] = []
        for fp in py_files:
            if fp == umbrella_subroot or umbrella_subroot in fp.parents:
                kept_umbrella.append(fp)
            else:
                skipped_files.append({"file": fp.relative_to(base_dir).as_posix(), "reason": "outside_manuscript_subproject"})
        py_files = kept_umbrella
        scope_applied = True

    # Determine primary pipeline file priority from workflow manifests / scope_summary
    if scope_summary is None:
        try:
            scope_root_for_disc = umbrella_subroot if umbrella_subroot is not None else base_dir
            s_info = discover_paper_matched_scopes(scope_root_for_disc, resolved_paper)
            raw_ss = resolve_active_pipeline_scope(s_info)
            if umbrella_subroot is not None and umbrella_subroot != base_dir:
                sub_pref = umbrella_subroot.relative_to(base_dir).as_posix()
                raw_ss = {
                    **raw_ss,
                    "active_files": [f"{sub_pref}/{f}" for f in (raw_ss.get("active_files") or [])],
                    "available_pipelines": [
                        {
                            **p,
                            "entrypoints": [f"{sub_pref}/{e}" for e in (p.get("entrypoints") or [])],
                            "files": [f"{sub_pref}/{mf}" for mf in (p.get("files") or [])],
                        }
                        for p in (raw_ss.get("available_pipelines") or [])
                    ],
                }
            scope_summary = raw_ss
        except Exception:
            scope_summary = None

    explicit_scope_given = active_files is not None
    allowed_rels: Optional[Set[str]] = None
    if explicit_scope_given:
        allowed_rels = {_norm_scope_rel(f) for f in (active_files or []) if _norm_scope_rel(f)}
    elif isinstance(scope_summary, dict) and scope_summary.get("scoped") and scope_summary.get("active_files"):
        allowed_rels = {_norm_scope_rel(f) for f in scope_summary["active_files"] if _norm_scope_rel(f)}

    if explicit_scope_given:
        scope_applied = True
        py_files = [fp for fp in py_files if fp.relative_to(base_dir).as_posix() in (allowed_rels or set())]
    elif allowed_rels:
        scoped_py = [fp for fp in py_files if fp.relative_to(base_dir).as_posix() in allowed_rels]
        if scoped_py:
            scope_applied = True
            py_files = scoped_py

    # Exclude archive / staging / backup snapshot folders unless explicitly requested in allowed_rels
    filtered_non_archive: List[Path] = []
    for fp in py_files:
        rel_p = fp.relative_to(base_dir).as_posix()
        if _is_archive_or_staging_rel(rel_p) and not (allowed_rels and rel_p in allowed_rels):
            skipped_files.append({"file": rel_p, "reason": "archive_or_staging_excluded"})
            continue
        filtered_non_archive.append(fp)
    py_files = filtered_non_archive

    primary_priority: Dict[str, int] = {}
    if isinstance(scope_summary, dict):
        pipes = scope_summary.get("available_pipelines") or []
        for p_idx, p_obj in enumerate(pipes):
            pid_low = str(p_obj.get("id") or "").lower()
            is_aux_pipe = any(k in pid_low for k in ("prep", "check", "verify", "audit"))
            ep_base = (20 + p_idx) if is_aux_pipe else p_idx
            dep_base = (50 + p_idx) if is_aux_pipe else (30 + p_idx)
            for e_f in p_obj.get("entrypoints") or []:
                norm_ef = _norm_scope_rel(str(e_f))
                cur_p = primary_priority.get(norm_ef, 99)
                if ep_base < cur_p:
                    primary_priority[norm_ef] = ep_base
            for m_f in p_obj.get("files") or []:
                norm_mf = _norm_scope_rel(str(m_f))
                cur_p = primary_priority.get(norm_mf, 99)
                if dep_base < cur_p:
                    primary_priority[norm_mf] = dep_base

    py_files.sort(
        key=lambda fp: (
            primary_priority.get(fp.relative_to(base_dir).as_posix(), 99),
            len(fp.relative_to(base_dir).parts),
            fp.relative_to(base_dir).as_posix(),
        )
    )

    # Deduplicate byte-identical Python snapshots across staging/copy folders via SHA-256
    dedup_py_files: List[Path] = []
    seen_file_shas: Set[str] = set()
    for fp in py_files:
        rel_p = fp.relative_to(base_dir).as_posix()
        try:
            f_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        except OSError:
            continue
        if f_sha in seen_file_shas:
            skipped_files.append({"file": rel_p, "reason": "duplicate_sha256"})
            continue
        seen_file_shas.add(f_sha)
        dedup_py_files.append(fp)
    py_files = dedup_py_files

    entry_ms = str(ms.get("entry_file") or "")
    searched_tex_files = list(ms["files"])

    raw_candidates: List[Dict[str, Any]] = []
    documented_mechanisms: List[Dict[str, Any]] = []
    exempted_dgp_functions: List[str] = []

    _STAT_SIG_CONTEXT_RE = re.compile(
        r"\b(?:(?:significance|confidence|nominal|alpha)\s+level|\d+\s*%\s+level|(?:\d*\.\d+)\s+level|"
        r"p[\s-]?values?|statistically\s+significant|significance|confidence\s+interval|robust\s+at\s+the)\b",
        re.IGNORECASE,
    )
    _REG_CONTEXT_RE = re.compile(
        r"\b(?:penalt(?:y|ies)|penali[sz](?:e|ed|ing)|regulari[sz](?:e|ed|ing|ation)|"
        r"ridge|lasso|shrink(?:age|ing)|prior\s+variance|hyperparameter|weight\s+decay)\b",
        re.IGNORECASE,
    )

    def _has_unnegated_tex_match(pattern_str: str) -> bool:
        return _has_unnegated_match_in_manuscript(ms, pattern_str)

    def _is_penalty_documented_in_tex(c_name: str, val_str: str, sci_pat: str) -> bool:
        has_named_ident = bool(c_name and c_name != val_str and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c_name))
        if has_named_ident:
            ident_re = rf"(?<!\\)\b{re.escape(c_name)}\b"
            if c_name.lower() in _COMMON_GREEK_OR_MATH_WORDS:
                # Common math/Greek names (`alpha`, `gamma`, ...) require regularization context in the same paragraph
                cre_ident = re.compile(ident_re, re.IGNORECASE)
                for para in ms.get("paragraphs") or []:
                    p_txt = str(para.get("text") or "")
                    if cre_ident.search(p_txt) and _REG_CONTEXT_RE.search(p_txt):
                        for clause in re.split(r"[.;!?]+", p_txt):
                            for m_id in cre_ident.finditer(clause):
                                if not _NEGATION_PREFIX_RE.search(clause[max(0, m_id.start() - 80) : m_id.start()]):
                                    return True
            elif _has_unnegated_tex_match(ident_re):
                return True

        # Check displayed equations directly for explicit penalty constant or symbol + norm/quadratic/KL/variance structure
        eq_penalty_struct_re = re.compile(
            r"(?:\+|\-)\s*(?:\\[A-Za-z]+|[0-9]+(?:\.[0-9]+)?(?:\s*\\times\s*10\^\{?[+-]?\d+\}?)?)\s*"
            r"[^=]*(?:\\lVert|\\Vert|\\\|+|\^2|\^\{2\}|_2\^2|\\operatorname\{(?:KL|Var)\}|D_\{\\mathrm\{KL\}\})"
        )
        has_pen_eq = any(eq_penalty_struct_re.search(str(eq.get("latex") or "")) for eq in (ms.get("equations") or []))
        if not has_pen_eq:
            return False
        val_patterns: List[str] = []
        if val_str:
            val_patterns.append(rf"(?<![0-9.]){re.escape(val_str)}(?![0-9])")
        if sci_pat:
            val_patterns.append(sci_pat)
        if not val_patterns:
            return False
        comb_val_re = re.compile("|".join(val_patterns), re.IGNORECASE)
        for eq in ms.get("equations") or []:
            ltx = str(eq.get("latex") or "")
            if eq_penalty_struct_re.search(ltx) and comb_val_re.search(ltx):
                return True
        for para in ms.get("paragraphs") or []:
            p_txt = str(para.get("text") or "")
            if not comb_val_re.search(p_txt) or not _REG_CONTEXT_RE.search(p_txt):
                continue
            for m_v in comb_val_re.finditer(p_txt):
                clause_pre = p_txt[max(0, m_v.start() - 80) : m_v.start()]
                clause_around = p_txt[max(0, m_v.start() - 55) : min(len(p_txt), m_v.end() + 55)]
                if _NEGATION_PREFIX_RE.search(clause_pre):
                    continue
                if _STAT_SIG_CONTEXT_RE.search(clause_around):
                    continue
                return True
        return False

    # Pre-parse active Python ASTs once, compute transitive repo-wide nn.Module subclasses,
    # and propagate non-None call-site arguments to a fixpoint across helper calls.
    parsed_py_files: List[Tuple[Path, str, List[str], ast.Module]] = []
    repo_cls_bases: Dict[Tuple[str, str], List[str]] = {}
    repo_cls_files: Dict[str, List[str]] = {}
    for fp in py_files:
        rel_posix = fp.relative_to(base_dir).as_posix()
        raw_src = fp.read_text(encoding="utf-8-sig", errors="replace")
        tree = _parse_python_ast_quiet(raw_src, filename=rel_posix)
        if tree is None:
            continue
        parsed_py_files.append((fp, raw_src, raw_src.splitlines(), tree))
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                b_strs = [ast.unparse(b) if hasattr(ast, "unparse") else "" for b in stmt.bases]
                repo_cls_bases[(rel_posix, stmt.name)] = [bs for bs in b_strs if bs]
                repo_cls_files.setdefault(stmt.name, []).append(rel_posix)

    repo_nn_pairs: Set[Tuple[str, str]] = {
        (rf, cn)
        for (rf, cn), blist in repo_cls_bases.items()
        if any(bs.endswith(("Module", "LightningModule", "PreTrainedModel")) for bs in blist)
    }
    changed_repo_nn = True
    while changed_repo_nn:
        changed_repo_nn = False
        for (rf, cn), blist in repo_cls_bases.items():
            if (rf, cn) in repo_nn_pairs:
                continue
            for bs in blist:
                btail = bs.split(".")[-1]
                if (rf, btail) in repo_nn_pairs or any((of, btail) in repo_nn_pairs for of in repo_cls_files.get(btail, [])):
                    repo_nn_pairs.add((rf, cn))
                    changed_repo_nn = True
                    break

    active_non_none_kwargs: Dict[str, Set[str]] = {}
    active_max_non_none_pos_args: Dict[str, int] = {}
    for _prop_pass in range(3):
        changed_args = False
        for _fp, _raw_src, _src_lines, tree in parsed_py_files:
            for fn_outer in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                outer_non_self = [a.arg for a in fn_outer.args.args if a.arg not in ("self", "cls")]
                outer_raw_args = [a.arg for a in fn_outer.args.args]
                outer_n_defs = len(fn_outer.args.defaults or [])
                unresolved_none_params: Set[str] = set()
                if outer_n_defs > 0:
                    for p_a, d_v in zip(outer_raw_args[-outer_n_defs:], fn_outer.args.defaults):
                        if isinstance(d_v, ast.Constant) and d_v.value is None:
                            p_pos = outer_non_self.index(p_a) if p_a in outer_non_self else -1
                            has_kw = p_a in active_non_none_kwargs.get(fn_outer.name, set())
                            has_pos = p_pos >= 0 and active_max_non_none_pos_args.get(fn_outer.name, -1) >= p_pos
                            if not (has_kw or has_pos):
                                unresolved_none_params.add(p_a)
                for kw_a, kw_d in zip(fn_outer.args.kwonlyargs or [], fn_outer.args.kw_defaults or []):
                    if kw_d is not None and isinstance(kw_d, ast.Constant) and kw_d.value is None:
                        if kw_a.arg not in active_non_none_kwargs.get(fn_outer.name, set()):
                            unresolved_none_params.add(kw_a.arg)

                for call_n in ast.walk(fn_outer):
                    if not isinstance(call_n, ast.Call):
                        continue
                    callee_nm = (
                        call_n.func.attr
                        if isinstance(call_n.func, ast.Attribute)
                        else (call_n.func.id if isinstance(call_n.func, ast.Name) else "")
                    )
                    if not callee_nm:
                        continue
                    for kw_n in call_n.keywords:
                        if kw_n.arg is None:
                            continue
                        if isinstance(kw_n.value, ast.Constant) and kw_n.value.value is None:
                            continue
                        if (
                            isinstance(kw_n.value, ast.Subscript)
                            and isinstance(kw_n.value.value, ast.Name)
                            and kw_n.value.value.id in unresolved_none_params
                        ):
                            continue
                        val_names = {n.id for n in ast.walk(kw_n.value) if isinstance(n, ast.Name)}
                        if val_names and val_names.issubset(unresolved_none_params):
                            continue
                        kw_set = active_non_none_kwargs.setdefault(callee_nm, set())
                        if kw_n.arg not in kw_set:
                            kw_set.add(kw_n.arg)
                            changed_args = True
                    for pos_i, pos_a in enumerate(call_n.args):
                        if isinstance(pos_a, ast.Starred):
                            prev_max = active_max_non_none_pos_args.get(callee_nm, -1)
                            if 8 > prev_max:
                                active_max_non_none_pos_args[callee_nm] = 8
                                changed_args = True
                            continue
                        if isinstance(pos_a, ast.Constant) and pos_a.value is None:
                            continue
                        val_names = {n.id for n in ast.walk(pos_a) if isinstance(n, ast.Name)}
                        if val_names and val_names.issubset(unresolved_none_params):
                            continue
                        prev_max = active_max_non_none_pos_args.get(callee_nm, -1)
                        if pos_i > prev_max:
                            active_max_non_none_pos_args[callee_nm] = pos_i
                            changed_args = True
            # Also record module-top-level calls outside any def
            for top_stmt in tree.body:
                if isinstance(top_stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for call_n in ast.walk(top_stmt):
                    if not isinstance(call_n, ast.Call):
                        continue
                    callee_nm = (
                        call_n.func.attr
                        if isinstance(call_n.func, ast.Attribute)
                        else (call_n.func.id if isinstance(call_n.func, ast.Name) else "")
                    )
                    if not callee_nm:
                        continue
                    for kw_n in call_n.keywords:
                        if kw_n.arg and not (isinstance(kw_n.value, ast.Constant) and kw_n.value.value is None):
                            kw_set = active_non_none_kwargs.setdefault(callee_nm, set())
                            if kw_n.arg not in kw_set:
                                kw_set.add(kw_n.arg)
                                changed_args = True
                    for pos_i, pos_a in enumerate(call_n.args):
                        if not (isinstance(pos_a, ast.Constant) and pos_a.value is None):
                            prev_max = active_max_non_none_pos_args.get(callee_nm, -1)
                            if pos_i > prev_max:
                                active_max_non_none_pos_args[callee_nm] = pos_i
                                changed_args = True
        if not changed_args:
            break

    scanned_files: List[str] = []
    for fp, raw_src, src_lines, tree in parsed_py_files:
        rel_posix = fp.relative_to(base_dir).as_posix()
        scanned_files.append(rel_posix)
        stem_low = fp.stem.lower()
        stem_toks = set(re.findall(r"[a-z0-9]+", stem_low))
        is_pure_dgp_file = bool(stem_toks & {"dgp", "dgps", "planted"})
        is_diag_check_file = stem_low.startswith(("check_", "test_", "verify_"))
        file_prio = primary_priority.get(rel_posix, 99)
        total_ln = len(src_lines)

        mod_nums = _extract_module_numeric_constants(tree)
        mod_idx_cols = _extract_module_index_collections(tree)
        nn_module_classes: Set[str] = {cn for (rf, cn) in repo_nn_pairs if rf == rel_posix}

        fn_items: List[Tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        class_sub_mlp_attrs: Dict[str, Set[str]] = {}
        class_col_attrs: Dict[str, Dict[str, str]] = {}
        classes_with_zero_init: Set[str] = set()
        top_exec_stmts: List[ast.stmt] = []

        for idx_st, stmt in enumerate(tree.body):
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_items.append(("", stmt.name, stmt))
            elif isinstance(stmt, ast.ClassDef):
                mlp_attrs: Set[str] = set()
                col_attrs: Dict[str, str] = {}
                for cstmt in stmt.body:
                    if isinstance(cstmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn_items.append((stmt.name, f"{stmt.name}.{cstmt.name}", cstmt))
                        if any(
                            isinstance(n, ast.Call)
                            and (
                                (isinstance(n.func, ast.Attribute) and n.func.attr in ("zeros_", "constant_"))
                                or (isinstance(n.func, ast.Name) and n.func.id in ("zeros_", "constant_"))
                            )
                            for n in ast.walk(cstmt)
                        ):
                            classes_with_zero_init.add(stmt.name)
                        if cstmt.name == "__init__":
                            init_args = {a.arg for a in cstmt.args.args if a.arg != "self"}
                            for sub in ast.walk(cstmt):
                                if isinstance(sub, ast.Assign):
                                    for tgt in sub.targets:
                                        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                                            rhs_s = ast.unparse(sub.value) if hasattr(ast, "unparse") else ""
                                            if any(k in rhs_s for k in ("Sequential", "MLP", "_mlp", "ReLU", "Tanh", "Linear")):
                                                mlp_attrs.add(tgt.attr)
                                            if not any(
                                                k in rhs_s
                                                for k in ("Linear", "Parameter", "Sequential", "ModuleList", "zeros", "randn")
                                            ) and (
                                                isinstance(sub.value, (ast.List, ast.Tuple))
                                                or (
                                                    isinstance(sub.value, ast.Call)
                                                    and isinstance(sub.value.func, ast.Name)
                                                    and sub.value.func.id in ("list", "tuple")
                                                )
                                                or any(k in tgt.attr.lower() for k in ("cols", "indices", "subset", "idx"))
                                            ):
                                                col_attrs[tgt.attr] = rhs_s
                                                for ia in init_args:
                                                    if re.search(rf"\b{re.escape(ia)}\b", rhs_s):
                                                        col_attrs[tgt.attr] = ia
                class_sub_mlp_attrs[stmt.name] = mlp_attrs
                class_col_attrs[stmt.name] = col_attrs
            elif not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if idx_st == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    continue
                top_exec_stmts.append(stmt)

        # Include synthetic `<module>` item for top-level / `if __name__ == "__main__":` statements in script-style repos
        if top_exec_stmts:
            mod_s_ln = max(1, int(getattr(top_exec_stmts[0], "lineno", 1) or 1))
            mod_e_ln = max(
                mod_s_ln,
                max(int(getattr(s, "end_lineno", getattr(s, "lineno", mod_s_ln)) or mod_s_ln) for s in top_exec_stmts),
            )
            synth_mod_fn = ast.FunctionDef(
                name="<module>",
                args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
                body=top_exec_stmts,
                decorator_list=[],
                returns=None,
                lineno=mod_s_ln,
                end_lineno=mod_e_ln,
            )
            fn_items.append(("", "<module>", synth_mod_fn))

        def _snip(start_l: int, end_l: Optional[int] = None, max_l: Optional[int] = None) -> str:
            bound_hi = min(total_ln, int(max_l)) if max_l is not None else total_ln
            s = max(1, min(bound_hi, int(start_l)))
            e = max(s, min(bound_hi, int(end_l or (s + 2))))
            return "\n".join(src_lines[s - 1 : min(e, s + 3)]).strip()

        def _build_citation_fields(
            contradict_match: Optional[Dict[str, Any]],
            queries: List[str],
            *,
            executed_regex: str,
            category: str,
        ) -> Dict[str, Any]:
            cat_closest_sec = _closest_estimation_section_label(ms, category)
            if contradict_match is not None:
                m_file = str(contradict_match["file"])
                m_line = int(contradict_match["line"])
                m_cite = f"{m_file}:L{m_line}"
                root_cite = (
                    f"{contradict_match['parent_cite']} -> {m_cite}"
                    if contradict_match.get("parent_cite") and m_file != entry_ms
                    else m_cite
                )
                passage = _clean_tex_excerpt(str(contradict_match.get("matched_excerpt") or contradict_match["text"]))
                return {
                    "manuscript_status": "contradicted_in_manuscript",
                    "manuscript_entry": entry_ms,
                    "manuscript_file": m_file,
                    "manuscript_line": m_line,
                    "manuscript_citation": m_cite,
                    "manuscript_root_citation": root_cite,
                    "manuscript_passage": passage,
                    "search_record": {
                        "status": "contradicted_in_manuscript",
                        "verdict": "contradicted_in_manuscript",
                        "entry_manuscript": entry_ms,
                        "searched_files": searched_tex_files,
                        "queries": queries,
                        "executed_regex": executed_regex,
                        "search_scope": "paragraphs",
                        "negation_checked": True,
                        "closest_section": f"{contradict_match.get('section') or 'Manuscript'} ({m_cite})",
                        "matched_citation": m_cite,
                        "raw_source_line": str(contradict_match.get("raw_text") or contradict_match.get("text") or ""),
                    },
                }
            return {
                "manuscript_status": "absent_from_manuscript",
                "manuscript_entry": entry_ms,
                "manuscript_file": None,
                "manuscript_line": None,
                "manuscript_citation": None,
                "manuscript_root_citation": None,
                "manuscript_passage": None,
                "search_record": {
                    "status": "absent_from_manuscript",
                    "verdict": "absent_from_manuscript",
                    "entry_manuscript": entry_ms,
                    "searched_files": searched_tex_files,
                    "queries": queries,
                    "executed_regex": executed_regex,
                    "search_scope": "paragraphs",
                    "negation_checked": True,
                    "closest_section": cat_closest_sec,
                    "matched_citation": None,
                },
            }

        for cls_name, qname, fn_node in fn_items:
            fn_start = max(1, int(getattr(fn_node, "lineno", 1) or 1))
            fn_end = max(fn_start, int(getattr(fn_node, "end_lineno", fn_start) or fn_start))
            fn_unparsed = ast.unparse(fn_node) if hasattr(ast, "unparse") else ""
            fn_low_nm = fn_node.name.lower()
            is_init_or_reset = (
                fn_node.name in ("__init__", "reset_parameters", "init_weights", "_init_weights")
                or fn_low_nm.startswith(("init_", "_init_", "initialize_", "reset_"))
            )
            has_optim_in_fn = bool(re.search(r"\b(?:Adam|AdamW|SGD|RMSprop|Adagrad)\s*\(", fn_unparsed))
            is_dgp_unit = (
                (is_pure_dgp_file and not has_optim_in_fn)
                or (
                    fn_low_nm.startswith(("generate_", "simulate_", "draw_", "sample_dgp", "create_dgp", "planted_"))
                    and not has_optim_in_fn
                    and "load_state_dict" not in fn_unparsed
                )
            )
            if is_dgp_unit:
                exempted_dgp_functions.append(f"{rel_posix}:{qname}")

            # 1. Category: `undocumented_warm_start_stage`
            warm_call_ln: Optional[int] = None
            warm_detail = ""
            warm_has_strict_false = False
            if not is_init_or_reset and not is_dgp_unit:
                non_self_fn_args = [a.arg for a in fn_node.args.args if a.arg not in ("self", "cls")]
                raw_fn_args = [a.arg for a in fn_node.args.args]
                n_defs = len(fn_node.args.defaults or [])
                none_default_params: Dict[str, int] = {}
                if n_defs > 0:
                    for p_arg, d_val in zip(raw_fn_args[-n_defs:], fn_node.args.defaults):
                        if isinstance(d_val, ast.Constant) and d_val.value is None:
                            pos_idx = non_self_fn_args.index(p_arg) if p_arg in non_self_fn_args else -1
                            none_default_params[p_arg] = pos_idx
                for kw_a, kw_d in zip(fn_node.args.kwonlyargs or [], fn_node.args.kw_defaults or []):
                    if kw_d is not None and isinstance(kw_d, ast.Constant) and kw_d.value is None:
                        none_default_params[kw_a.arg] = -1

                fn_has_copy_in_no_grad = bool("no_grad" in fn_unparsed and ".copy_(" in fn_unparsed)
                fn_has_checkpoint_io = bool(re.search(r"\btorch\.load\s*\(|\bpickle\.load\s*\(|\bopen\s*\(", fn_unparsed))
                sorted_ws_calls = sorted(
                    [n for n in ast.walk(fn_node) if isinstance(n, ast.Call)],
                    key=lambda n: int(getattr(n, "lineno", fn_start)),
                )
                for sub in sorted_ws_calls:
                    cname = (
                        sub.func.attr
                        if isinstance(sub.func, ast.Attribute)
                        else (sub.func.id if isinstance(sub.func, ast.Name) else "")
                    )
                    call_txt = ast.unparse(sub) if hasattr(ast, "unparse") else ""
                    has_strict_false = any(
                        kw.arg == "strict" and isinstance(kw.value, ast.Constant) and kw.value.value is False
                        for kw in sub.keywords
                    )
                    arg_from_inmem_model = bool(
                        sub.args
                        and isinstance(sub.args[0], ast.Call)
                        and isinstance(sub.args[0].func, ast.Attribute)
                        and sub.args[0].func.attr == "state_dict"
                    )
                    if cname == "load_state_dict" and (
                        has_strict_false
                        or (arg_from_inmem_model and (not fn_has_checkpoint_io or has_optim_in_fn))
                    ):
                        root_param_nm = ""
                        if sub.args:
                            a0 = sub.args[0]
                            if isinstance(a0, ast.Name):
                                root_param_nm = a0.id
                            elif (
                                isinstance(a0, ast.Call)
                                and isinstance(a0.func, ast.Attribute)
                                and isinstance(a0.func.value, ast.Name)
                            ):
                                root_param_nm = a0.func.value.id
                        if root_param_nm and root_param_nm in none_default_params:
                            p_idx = none_default_params[root_param_nm]
                            passed_kw = root_param_nm in active_non_none_kwargs.get(fn_node.name, set())
                            passed_pos = p_idx >= 0 and active_max_non_none_pos_args.get(fn_node.name, -1) >= p_idx
                            if not (passed_kw or passed_pos):
                                continue
                        warm_call_ln = int(getattr(sub, "lineno", fn_start))
                        warm_detail = call_txt
                        warm_has_strict_false = has_strict_false
                        break
                    if fn_has_copy_in_no_grad and cname == "copy_" and isinstance(sub.func, ast.Attribute) and sub.args:
                        recv_s = ast.unparse(sub.func.value) if hasattr(ast, "unparse") else ""
                        src_s = ast.unparse(sub.args[0]) if hasattr(ast, "unparse") else ""
                        recv_root = recv_s.split(".", 1)[0].split("[", 1)[0].strip()
                        src_root = src_s.split(".", 1)[0].split("(", 1)[0].strip()
                        # Require cross-object parameter transfer (never self-projection / self-clamp `w.copy_(w.clamp(...))`)
                        if (
                            recv_root
                            and src_root
                            and recv_root != src_root
                            and recv_s not in src_s
                            and not src_s.startswith(("torch.zeros", "torch.ones", "torch.randn", "torch.empty"))
                        ):
                            warm_call_ln = int(getattr(sub, "lineno", fn_start))
                            warm_detail = call_txt
                            break
            if warm_call_ln is not None:
                queries_ws = [
                    "load_state_dict",
                    "strict=False",
                    "two-stage parameter transfer",
                    "two-stage initialization",
                ]
                doc_ws_re = r"\b(?:warm[\s-]?start(?:ed|ing|s)?|load_state_dict|two[\s-]?stage\s+initiali[sz]|pretrained\s+(?:baseline|anchor)\s+weights)\b"
                is_doc_ws = _has_unnegated_tex_match(doc_ws_re)
                if is_doc_ws:
                    documented_mechanisms.append({
                        "category": "undocumented_warm_start_stage",
                        "code_citation": f"{rel_posix}:L{warm_call_ln}",
                        "code_symbol": qname,
                    })
                else:
                    # Only flag `contradicted_in_manuscript` when prose explicitly claims random/cold/single-stage initialization
                    # ("trained jointly with" is silent on warm-start initialization -> `absent_from_manuscript`)
                    cm_ws = _find_tex_line_match(
                        ms,
                        [
                            r"\b(?:do\s+not\s+warm[\s-]?start|no\s+warm[\s-]?start|without\s+warm[\s-]?start)\b",
                            r"\b(?:initiali[sz]ed\s+randomly|random\s+initiali[sz]ation|trained\s+from\s+scratch)\b",
                            r"\b(?:estimated|trained)\s+jointly\s+in\s+a\s+single\s+stage\b",
                        ],
                        prefer_sections=("model", "estimat", "method", "empiric"),
                    )
                    has_zero_res_note = warm_has_strict_false and bool(classes_with_zero_init)
                    ws_end_ln = min(fn_end, warm_call_ln + 3)
                    ws_cite_str = f"{cm_ws['file']}:L{cm_ws['line']}" if cm_ws is not None else "the formal model specification"
                    raw_candidates.append({
                        "priority": file_prio,
                        "category": "undocumented_warm_start_stage",
                        "severity": "high",
                        "title": f"Multi-stage `load_state_dict` warm-start transfer in `{qname}`",
                        "summary": (
                            f"`{rel_posix}:L{warm_call_ln}` initializes model parameters via explicit two-stage `load_state_dict` transfer "
                            f"(`{warm_detail[:90]}`"
                            + (" with zero-initialized residual heads" if has_zero_res_note else "")
                            + (
                                f"), contradicting `{ws_cite_str}`."
                                if cm_ws is not None
                                else "), a concrete two-stage state-dict weight-transfer protocol absent from the manuscript (even where prose qualitatively mentions baseline anchoring)."
                            )
                        ),
                        "code_file": rel_posix,
                        "code_line": warm_call_ln,
                        "code_end_line": ws_end_ln,
                        "code_citation": f"{rel_posix}:L{warm_call_ln}",
                        "code_symbol": qname,
                        "code_snippet": _snip(warm_call_ln, ws_end_ln, max_l=fn_end),
                        **_build_citation_fields(cm_ws, queries_ws, executed_regex=doc_ws_re, category="undocumented_warm_start_stage"),
                    })

            # 2. Category: `post_fit_residual_perturbation` (100% AST-structural, zero identifier stem lists)
            perturb_ln: Optional[int] = None
            perturb_expr = ""
            if not is_init_or_reset and not is_dgp_unit:
                has_no_grad = "no_grad" in fn_unparsed
                has_zero_or_stall_guard = False
                for sub_g in ast.walk(fn_node):
                    if isinstance(sub_g, ast.Call):
                        g_nm = sub_g.func.attr if isinstance(sub_g.func, ast.Attribute) else (sub_g.func.id if isinstance(sub_g.func, ast.Name) else "")
                        if g_nm == "count_nonzero":
                            has_zero_or_stall_guard = True
                            break
                    elif isinstance(sub_g, ast.Compare) and sub_g.ops and sub_g.comparators:
                        # Exclude modulo loop-step guards (`ep % 10 == 0` or `step == 0`)
                        if isinstance(sub_g.left, ast.BinOp) and isinstance(sub_g.left.op, ast.Mod):
                            continue
                        if isinstance(sub_g.left, ast.Name) and sub_g.left.id.lower() in {"ep", "epoch", "step", "i", "idx", "it", "iter"}:
                            continue
                        cmp_txt = ast.unparse(sub_g) if hasattr(ast, "unparse") else ""
                        if re.search(r"\.(?:abs|norm)\s*\([^)]*\)\s*(?:<|<=|==)|count_nonzero|==\s*0(?:\.0)?\b", cmp_txt):
                            has_zero_or_stall_guard = True
                            break

                param_loop_vars: Set[str] = set()
                rand_vars: Set[str] = set()
                for sub in ast.walk(fn_node):
                    if isinstance(sub, ast.For):
                        iter_u = ast.unparse(sub.iter) if hasattr(ast, "unparse") else ""
                        if "parameters(" in iter_u or "named_parameters(" in iter_u:
                            for tn in ast.walk(sub.target):
                                if isinstance(tn, ast.Name):
                                    param_loop_vars.add(tn.id)
                    elif isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                        rhs_u = ast.unparse(sub.value) if hasattr(ast, "unparse") else ""
                        if re.search(r"\b(?:randn_like|randn|rand_like|normal|cauchy)\s*\(", rhs_u):
                            rand_vars.add(sub.targets[0].id)

                sorted_pt_nodes = sorted(
                    [n for n in ast.walk(fn_node) if isinstance(n, (ast.Call, ast.AugAssign))],
                    key=lambda n: int(getattr(n, "lineno", fn_start)),
                )
                for sub in sorted_pt_nodes:
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        cname = sub.func.attr
                        recv = sub.func.value
                        recv_u = ast.unparse(recv) if hasattr(ast, "unparse") else ""
                        if re.search(r"(?:^|\.)init$", recv_u):
                            continue
                        is_param_target = isinstance(recv, (ast.Attribute, ast.Subscript)) or (
                            isinstance(recv, ast.Name) and recv.id in param_loop_vars
                        )
                        if cname in ("normal_", "uniform_", "cauchy_") and is_param_target and (
                            has_no_grad and has_zero_or_stall_guard
                        ):
                            perturb_ln = int(getattr(sub, "lineno", fn_start))
                            perturb_expr = ast.unparse(sub)[:90] if hasattr(ast, "unparse") else cname
                            break
                        if cname in ("add_", "sub_") and is_param_target and sub.args:
                            arg_u = ast.unparse(sub.args[0]) if hasattr(ast, "unparse") else ""
                            uses_rand = bool(
                                re.search(r"\b(?:randn_like|randn|rand_like|normal|cauchy)\s*\(", arg_u)
                                or any(re.search(rf"\b{re.escape(rv)}\b", arg_u) for rv in rand_vars)
                            )
                            if uses_rand and (has_no_grad or has_zero_or_stall_guard):
                                perturb_ln = int(getattr(sub, "lineno", fn_start))
                                perturb_expr = ast.unparse(sub)[:90] if hasattr(ast, "unparse") else cname
                                break
                    elif isinstance(sub, ast.AugAssign) and isinstance(sub.op, (ast.Add, ast.Sub)):
                        is_aug_param = isinstance(sub.target, (ast.Attribute, ast.Subscript)) or (
                            isinstance(sub.target, ast.Name) and sub.target.id in param_loop_vars
                        )
                        if is_aug_param:
                            rhs_u = ast.unparse(sub.value) if hasattr(ast, "unparse") else ""
                            uses_rand = bool(
                                re.search(r"\b(?:randn_like|randn|rand_like|normal|cauchy)\s*\(", rhs_u)
                                or any(re.search(rf"\b{re.escape(rv)}\b", rhs_u) for rv in rand_vars)
                            )
                            if uses_rand and (has_no_grad or has_zero_or_stall_guard):
                                perturb_ln = int(getattr(sub, "lineno", fn_start))
                                perturb_expr = ast.unparse(sub)[:90] if hasattr(ast, "unparse") else "+="
                                break

            if perturb_ln is not None:
                queries_pt = [
                    "parameter perturbation",
                    "Gaussian parameter jitter",
                    "symmetry-breaking noise",
                    "zero-weight perturbation",
                    "Langevin / SGLD parameter noise",
                ]
                doc_pt_re = (
                    r"\b(?:parameter\s+perturbat|residual\s+perturbat|symmetry[\s-]?break(?:ing)?\s+noise|"
                    r"jitter(?:ing|ed)?\s+(?:zero|dead|residual|stalled)|re[\s-]?initiali[sz](?:e|ing)\s+zero|"
                    r"langevin|sgld|mcmc|metropolis|random[\s-]?walk\s+proposal|"
                    r"gaussian\s+(?:parameter\s+)?(?:noise|jitter|perturbat)|perturbed\s+with\s+(?:gaussian|normal|random)\s+noise)\b"
                )
                is_doc_pt = _has_unnegated_tex_match(doc_pt_re)
                if is_doc_pt:
                    documented_mechanisms.append({
                        "category": "post_fit_residual_perturbation",
                        "code_citation": f"{rel_posix}:L{perturb_ln}",
                        "code_symbol": qname,
                    })
                else:
                    cm_pt = _find_tex_line_match(
                        ms,
                        [
                            r"\b(?:no\s+parameter\s+noise|deterministic\s+gradient|exact\s+zero\s+weights\s+preserved)\b",
                        ],
                        prefer_sections=("estimat", "method", "model"),
                    )
                    snip_lo = max(fn_start, perturb_ln - 1)
                    snip_hi = min(fn_end, perturb_ln + 2)
                    raw_candidates.append({
                        "priority": file_prio,
                        "category": "post_fit_residual_perturbation",
                        "severity": "high",
                        "title": f"In-place stochastic parameter perturbation in `{qname}`",
                        "summary": (
                            f"`{rel_posix}:L{perturb_ln}` (`{qname}`) injects random noise (`{perturb_expr}`) into zero/stalled "
                            f"parameter tensors before or during fitting so gradients flow, a heuristic absent from the manuscript."
                        ),
                        "code_file": rel_posix,
                        "code_line": perturb_ln,
                        "code_end_line": snip_hi,
                        "code_citation": f"{rel_posix}:L{perturb_ln}",
                        "code_symbol": qname,
                        "code_snippet": _snip(snip_lo, snip_hi, max_l=fn_end),
                        **_build_citation_fields(cm_pt, queries_pt, executed_regex=doc_pt_re, category="post_fit_residual_perturbation"),
                    })

            # 3. Category: `multi_rate_optimizer_groups` vs `per_group_weight_decay`
            if not is_init_or_reset and not is_dgp_unit:
                local_group_lists: Dict[str, List[ast.Dict]] = {}
                for sub in ast.walk(fn_node):
                    if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                        if isinstance(sub.value, (ast.List, ast.Tuple)):
                            dicts_init = [e for e in sub.value.elts if isinstance(e, ast.Dict)]
                            local_group_lists[sub.targets[0].id] = dicts_init
                    elif (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "append"
                        and isinstance(sub.func.value, ast.Name)
                        and sub.args
                        and isinstance(sub.args[0], ast.Dict)
                    ):
                        local_group_lists.setdefault(sub.func.value.id, []).append(sub.args[0])

                sorted_calls = sorted(
                    [n for n in ast.walk(fn_node) if isinstance(n, ast.Call)],
                    key=lambda n: int(getattr(n, "lineno", 0)),
                )
                for sub in sorted_calls:
                    cname = (
                        sub.func.attr
                        if isinstance(sub.func, ast.Attribute)
                        else (sub.func.id if isinstance(sub.func, ast.Name) else "")
                    )
                    if cname in ("Adam", "AdamW", "SGD", "RMSprop", "Adagrad") and sub.args:
                        arg0 = sub.args[0]
                        dict_elts: List[ast.Dict] = []
                        is_var_groups = False
                        if isinstance(arg0, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Dict) for e in arg0.elts):
                            dict_elts = [e for e in arg0.elts if isinstance(e, ast.Dict)]
                        elif isinstance(arg0, ast.Name) and arg0.id in local_group_lists:
                            dict_elts = local_group_lists[arg0.id]
                            is_var_groups = True
                        if len(dict_elts) >= 2:
                            call_lr_kw = ""
                            call_lr_num: Optional[float] = None
                            call_wd_kw = ""
                            for ck in sub.keywords:
                                if ck.arg == "lr" and ck.value is not None:
                                    call_lr_kw = ast.unparse(ck.value) if hasattr(ast, "unparse") else "lr"
                                    call_lr_num = _extract_scalar_float(ck.value)
                                    if call_lr_kw in mod_nums:
                                        call_lr_num = mod_nums[call_lr_kw][0]
                                        call_lr_kw = f"{call_lr_kw}={call_lr_num:g}"
                                elif ck.arg == "weight_decay" and ck.value is not None:
                                    call_wd_kw = ast.unparse(ck.value) if hasattr(ast, "unparse") else "weight_decay"
                            lr_reprs: List[str] = []
                            wd_reprs: List[str] = []
                            resolved_lr_nums: Set[float] = set()
                            explicit_lr_exprs: Set[str] = set()
                            explicit_wd_set: Set[str] = set()
                            for d_node in dict_elts:
                                grp_lr = ""
                                grp_lr_num: Optional[float] = None
                                grp_wd = ""
                                for k_n, v_n in zip(d_node.keys, d_node.values):
                                    if isinstance(k_n, ast.Constant) and k_n.value == "lr" and v_n is not None:
                                        lr_s = ast.unparse(v_n) if hasattr(ast, "unparse") else ""
                                        grp_lr_num = _extract_scalar_float(v_n)
                                        if lr_s in mod_nums:
                                            grp_lr_num = mod_nums[lr_s][0]
                                            lr_s = f"{lr_s}={grp_lr_num:g}"
                                        grp_lr = lr_s
                                        explicit_lr_exprs.add(lr_s)
                                    elif isinstance(k_n, ast.Constant) and k_n.value == "weight_decay" and v_n is not None:
                                        wd_s = ast.unparse(v_n) if hasattr(ast, "unparse") else ""
                                        if wd_s in mod_nums:
                                            wd_s = f"{wd_s}={mod_nums[wd_s][0]:g}"
                                        grp_wd = wd_s
                                        explicit_wd_set.add(wd_s)
                                eff_lr_num = grp_lr_num if grp_lr_num is not None else call_lr_num
                                if eff_lr_num is not None:
                                    resolved_lr_nums.add(round(eff_lr_num, 12))
                                lr_reprs.append(grp_lr or call_lr_kw or "default")
                                wd_reprs.append(grp_wd or call_wd_kw or "0 (default)")

                            has_scaled_lr_expr = any(any(op_c in ex for op_c in ("*", "/")) for ex in explicit_lr_exprs)
                            is_provably_multi_rate = len(resolved_lr_nums) >= 2 or (
                                len(explicit_lr_exprs) >= 2 and (has_scaled_lr_expr or len(resolved_lr_nums) == 0)
                            )
                            has_distinct_wds = len(explicit_wd_set) >= 2 or len(set(wd_reprs)) >= 2

                            if is_provably_multi_rate or has_distinct_wds:
                                opt_ln = int(getattr(sub, "lineno", fn_start))
                                snip_start = max(fn_start, opt_ln - 2) if is_var_groups else opt_ln
                                opt_end_ln = min(fn_end, opt_ln + 4)
                                if is_provably_multi_rate:
                                    opt_cat = "multi_rate_optimizer_groups"
                                    queries_opt = [
                                        "optimizer parameter groups",
                                        "separate learning rates",
                                        "differential learning rates",
                                    ]
                                    doc_opt_re = (
                                        r"\b(?:parameter\s+groups?|separate\s+learning\s+rates?|per[\s-]?group\s+learning\s+rates?|"
                                        r"differential\s+learning\s+rates?|two\s+learning\s+rates?|distinct\s+learning\s+rates?)\b"
                                    )
                                    cm_patterns = [
                                        r"\bsingle(?:\s+uniform)?\s+learning\s+rate\b",
                                        r"\buniform\s+learning\s+rate\b",
                                        r"\blearning\s+rate\s+\$?\\eta\s*=",
                                    ]
                                    opt_title = f"Multi-rate `{cname}` parameter groups in `{qname}`"
                                else:
                                    opt_cat = "per_group_weight_decay"
                                    queries_opt = [
                                        "per-group weight decay",
                                        "differential L2 weight decay across parameter groups",
                                        "component-specific regularization",
                                    ]
                                    doc_opt_re = (
                                        r"\b(?:per[\s-]?group\s+weight\s+decay|differential\s+weight\s+decay|"
                                        r"separate\s+weight\s+decay|component[\s-]?specific\s+(?:weight\s+decay|l_?2|regulariz)|"
                                        r"parameter\s+groups?\s+with\s+(?:different|distinct|separate)\s+weight\s+decay)\b"
                                    )
                                    cm_patterns = [
                                        r"\buniform\s+weight\s+decay\b",
                                        r"\bsingle\s+weight\s+decay\b",
                                    ]
                                    opt_title = f"Per-group `{cname}` weight-decay schedule in `{qname}`"

                                if _has_unnegated_tex_match(doc_opt_re):
                                    documented_mechanisms.append({
                                        "category": opt_cat,
                                        "code_citation": f"{rel_posix}:L{opt_ln}",
                                        "code_symbol": qname,
                                    })
                                else:
                                    cm_opt = _find_tex_line_match(
                                        ms,
                                        cm_patterns,
                                        prefer_sections=("estimat", "empiric", "method"),
                                    )
                                    raw_candidates.append({
                                        "priority": file_prio,
                                        "category": opt_cat,
                                        "severity": "medium",
                                        "title": opt_title,
                                        "summary": (
                                            f"`{rel_posix}:L{opt_ln}` configures `{cname}` with {len(dict_elts)} parameter groups "
                                            f"(learning rates `{', '.join(lr_reprs)}`, weight decays `{', '.join(wd_reprs)}`) "
                                            f"not specified in the manuscript's estimation protocol."
                                        ),
                                        "code_file": rel_posix,
                                        "code_line": opt_ln,
                                        "code_end_line": opt_end_ln,
                                        "code_citation": f"{rel_posix}:L{opt_ln}",
                                        "code_symbol": qname,
                                        "code_snippet": _snip(snip_start, opt_end_ln, max_l=fn_end),
                                        **_build_citation_fields(cm_opt, queries_opt, executed_regex=doc_opt_re, category=opt_cat),
                                    })
                                break

            # 4. Category: `undocumented_penalty_or_shrinkage` (100% function-name & variable-name independent)
            if not is_init_or_reset and not is_dgp_unit and not is_diag_check_file:
                def _parse_mult_penalty(node: ast.AST, fallback_ln: int) -> Optional[Tuple[int, str, Optional[float], str]]:
                    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)):
                        return None
                    expr_s = ast.unparse(node) if hasattr(ast, "unparse") else ""
                    if not any(tok in expr_s for tok in ("** 2", "**2", "pow(", "norm(", "var(")):
                        return None
                    c_name = ""
                    c_val: Optional[float] = None
                    is_named_const = False
                    for factor in (node.left, node.right):
                        if isinstance(factor, ast.Name) and factor.id in mod_nums:
                            c_name = factor.id
                            c_val = mod_nums[factor.id][0]
                            is_named_const = True
                            break
                        sc = _extract_scalar_float(factor)
                        if sc is not None:
                            c_val = sc
                            c_name = f"{sc:g}"
                            break
                    # Exclude analytical Gaussian NLL `0.5 * z**2` / `0.5 * ((x - mu)/sigma)**2` when 0.5 is a bare literal
                    if (
                        not is_named_const
                        and c_val is not None
                        and abs(c_val - 0.5) < 1e-12
                        and not any(p in expr_s.lower() for p in ("pen", "reg", "shrink", "ridge", "lasso"))
                    ):
                        return None
                    if c_val is not None or any(
                        isinstance(n, ast.Name) and any(p in n.id.lower() for p in ("pen", "reg", "lam", "shrink", "ridge", "lasso"))
                        for n in ast.walk(node)
                    ):
                        return (int(getattr(node, "lineno", fallback_ln)), c_name or "penalty_weight", c_val, expr_s)
                    return None

                def _flatten_add_terms(expr: ast.AST) -> List[ast.AST]:
                    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                        return _flatten_add_terms(expr.left) + _flatten_add_terms(expr.right)
                    return [expr]

                # Track variables flowing into `.backward()` or `return <var>` structurally
                objective_sink_vars: Set[str] = set()
                for sub in ast.walk(fn_node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "backward"
                        and isinstance(sub.func.value, ast.Name)
                    ):
                        objective_sink_vars.add(sub.func.value.id)
                    elif isinstance(sub, ast.Return) and isinstance(sub.value, ast.Name):
                        objective_sink_vars.add(sub.value.id)

                local_pen_vars: Dict[str, Tuple[int, str, Optional[float], str]] = {}
                pen_hits: List[Tuple[int, str, Optional[float], str]] = []
                seen_pen_keys: Set[str] = set()

                for sub in ast.walk(fn_node):
                    stmt_ln = int(getattr(sub, "lineno", fn_start))
                    if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                        direct_p = _parse_mult_penalty(sub.value, stmt_ln)
                        if direct_p is not None:
                            local_pen_vars[sub.targets[0].id] = direct_p

                sorted_pen_stmts = sorted(
                    [n for n in ast.walk(fn_node) if isinstance(n, (ast.Assign, ast.AugAssign, ast.Return, ast.Call))],
                    key=lambda n: int(getattr(n, "lineno", fn_start)),
                )
                for sub in sorted_pen_stmts:
                    rhs_add: Optional[ast.AST] = None
                    stmt_ln = int(getattr(sub, "lineno", fn_start))
                    if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.BinOp) and isinstance(sub.value.op, ast.Add):
                        tgt0 = sub.targets[0]
                        lhs_s = ast.unparse(tgt0) if hasattr(ast, "unparse") else ""
                        if (isinstance(tgt0, ast.Name) and tgt0.id in objective_sink_vars) or any(
                            k in lhs_s.lower() for k in ("loss", "nll", "obj")
                        ):
                            rhs_add = sub.value
                    elif isinstance(sub, ast.AugAssign) and isinstance(sub.op, ast.Add):
                        lhs_s = ast.unparse(sub.target) if hasattr(ast, "unparse") else ""
                        if (isinstance(sub.target, ast.Name) and sub.target.id in objective_sink_vars) or any(
                            k in lhs_s.lower() for k in ("loss", "nll", "obj")
                        ):
                            rhs_add = sub.value
                    elif isinstance(sub, ast.Return) and isinstance(sub.value, ast.BinOp) and isinstance(sub.value.op, ast.Add):
                        rhs_add = sub.value
                    elif (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "backward"
                        and isinstance(sub.func.value, ast.BinOp)
                        and isinstance(sub.func.value.op, ast.Add)
                    ):
                        rhs_add = sub.func.value

                    if rhs_add is not None:
                        terms = _flatten_add_terms(rhs_add)
                        for t_node in terms:
                            cand_p = _parse_mult_penalty(t_node, stmt_ln)
                            if cand_p is None and isinstance(t_node, ast.Name) and t_node.id in local_pen_vars:
                                cand_p = local_pen_vars[t_node.id]
                            if cand_p is not None and cand_p[1] not in seen_pen_keys:
                                seen_pen_keys.add(cand_p[1])
                                pen_hits.append(cand_p)

                for p_ln, p_cname, p_cval, p_expr in pen_hits:
                    val_str = f"{p_cval:g}" if p_cval is not None else ""
                    sci_pat = ""
                    if p_cval is not None and p_cval > 0:
                        exp10 = math.log10(p_cval)
                        if abs(exp10 - round(exp10)) < 1e-9:
                            sci_pat = rf"10\^\{{?\s*{int(round(exp10))}\s*\}}?"
                    if _is_penalty_documented_in_tex(p_cname, val_str, sci_pat):
                        documented_mechanisms.append({
                            "category": "undocumented_penalty_or_shrinkage",
                            "code_citation": f"{rel_posix}:L{p_ln}",
                            "code_symbol": qname,
                            "constant": f"{p_cname}={val_str}" if val_str else p_cname,
                        })
                    else:
                        queries_pen = [
                            f"penalty constant {val_str}".strip(),
                            "regularization penalty term in objective equation",
                            "variance shrinkage objective",
                        ]
                        doc_pen_parts: List[str] = []
                        if p_cname and p_cname != val_str and p_cname.lower() not in _COMMON_GREEK_OR_MATH_WORDS:
                            doc_pen_parts.append(rf"(?<!\\)\b{re.escape(p_cname)}\b")
                        if val_str:
                            doc_pen_parts.append(rf"\b(?:penalt(?:y|ies)|regulari[sz]\w+|shrink(?:age|ing))\b[^.;!?]{{0,50}}(?<![0-9.]){re.escape(val_str)}(?![0-9])")
                        doc_pen_re = "|".join(doc_pen_parts) if doc_pen_parts else r"\bundocumented_objective_penalty\b"

                        # Prefer explicit unpenalized likelihood-maximization prose first, falling back to formal objective equation
                        cm_pen = _find_tex_line_match(
                            ms,
                            [
                                r"\b(?:estimat(?:ed|e)|train(?:ed)?)\s+by\s+maximizing\s+the\s+(?:marginal\s+|consumer[\s-]?level\s+|panel\s+)?(?:log[\s-]?)?likelihood\b",
                                r"\bmaximizing\s+the\s+(?:marginal\s+|consumer[\s-]?level\s+|panel\s+)?(?:log[\s-]?)?likelihood\b",
                                r"\bminimizing\s+(?:unregularized\s+)?cross[\s-]?entropy\b",
                            ],
                            prefer_sections=("empiric", "estimat", "model", "method"),
                        )
                        if cm_pen is None:
                            for eq_obj in ms["equations"]:
                                ltx = eq_obj["latex"]
                                if re.search(r"\\mathcal\{L\}|\\ell|\bNLL\b|\\log\s*\\left\(\s*\\sum|\\sum.*\\log", ltx):
                                    cm_pen = {
                                        "file": eq_obj["file"],
                                        "line": eq_obj["line"],
                                        "text": ltx,
                                        "section": eq_obj["section"],
                                        "parent_cite": eq_obj.get("parent_cite", ""),
                                    }
                                    break
                        c_desc = (
                            f"`{p_cname} = {val_str}`"
                            if (p_cname and val_str and p_cname != val_str)
                            else (f"`{val_str}`" if val_str else f"`{p_cname}`")
                        )
                        pen_end_ln = min(fn_end, p_ln + 3)
                        raw_candidates.append({
                            "priority": file_prio,
                            "category": "undocumented_penalty_or_shrinkage",
                            "severity": "high",
                            "title": f"Undocumented objective penalty / shrinkage term ({c_desc}) in `{qname}`",
                            "summary": (
                                f"`{rel_posix}:L{p_ln}` adds `{p_expr[:95]}` ({c_desc}) directly to the training objective, "
                                f"whereas the manuscript's objective specification omits this penalty term and constant."
                            ),
                            "code_file": rel_posix,
                            "code_line": p_ln,
                            "code_end_line": pen_end_ln,
                            "code_citation": f"{rel_posix}:L{p_ln}",
                            "code_symbol": qname,
                            "code_snippet": _snip(p_ln, pen_end_ln, max_l=fn_end),
                            **_build_citation_fields(cm_pen, queries_pen, executed_regex=doc_pen_re, category="undocumented_penalty_or_shrinkage"),
                        })

            # 5. Category: `covariate_subset_adapter` (100% AST-structural inside nn.Module: full-tensor primary + column-sliced secondary branch)
            sub_slice_ln: Optional[int] = None
            slice_expr = ""
            matched_col_const: Optional[Tuple[str, Dict[str, Any]]] = None
            uses_nonlinear_sub = False
            if cls_name and cls_name in nn_module_classes and not is_init_or_reset and not is_dgp_unit:
                non_self_args = [a.arg for a in fn_node.args.args if a.arg != "self"]
                feat_arg = non_self_args[0] if non_self_args else ""
                slice_node_ids: Set[int] = set()
                candidate_slice: Optional[Tuple[int, str, Optional[Tuple[str, Dict[str, Any]]]]] = None

                sorted_sub_nodes = sorted(
                    [n for n in ast.walk(fn_node) if isinstance(n, (ast.Subscript, ast.Call))],
                    key=lambda n: int(getattr(n, "lineno", fn_start)),
                )
                for sub in sorted_sub_nodes:
                    if isinstance(sub, ast.Subscript):
                        base_is_feat = isinstance(sub.value, ast.Name) and (not feat_arg or sub.value.id == feat_arg)
                        if not base_is_feat:
                            continue
                        sub_s = ast.unparse(sub) if hasattr(ast, "unparse") else ""
                        hit_col: Optional[Tuple[str, Dict[str, Any]]] = None
                        for col_k, col_meta in mod_idx_cols.items():
                            if re.search(rf"\b{re.escape(col_k)}\b", sub_s):
                                hit_col = (col_k, col_meta)
                                break
                        if hit_col is None and class_col_attrs.get(cls_name):
                            for attr_nm in class_col_attrs[cls_name]:
                                if f"self.{attr_nm}" in sub_s:
                                    if mod_idx_cols:
                                        first_k = next(iter(mod_idx_cols))
                                        hit_col = (first_k, mod_idx_cols[first_k])
                                    else:
                                        hit_col = (
                                            f"self.{attr_nm}",
                                            {"lineno": int(getattr(sub, "lineno", fn_start)), "max_cols": 1, "sample": sub_s},
                                        )
                                    break
                        sl_inner = getattr(sub.slice, "value", sub.slice)
                        if hit_col is None and isinstance(sl_inner, ast.Tuple) and len(sl_inner.elts) >= 2:
                            last_idx = getattr(sl_inner.elts[-1], "value", sl_inner.elts[-1])
                            if (
                                isinstance(last_idx, (ast.List, ast.Tuple))
                                and last_idx.elts
                                and all(
                                    isinstance(x, ast.Constant) and isinstance(x.value, int) and not isinstance(x.value, bool)
                                    for x in last_idx.elts
                                )
                            ):
                                ln_here = int(getattr(sub, "lineno", fn_start))
                                hit_col = (
                                    "column_subset",
                                    {
                                        "lineno": ln_here,
                                        "max_cols": len(last_idx.elts),
                                        "sample": ast.unparse(last_idx) if hasattr(ast, "unparse") else sub_s,
                                    },
                                )
                        if hit_col is not None:
                            slice_node_ids.add(id(sub))
                            slice_node_ids.add(id(sub.value))
                            if candidate_slice is None:
                                candidate_slice = (int(getattr(sub, "lineno", fn_start)), sub_s, hit_col)
                    elif (
                        isinstance(sub, ast.Call)
                        and (
                            (isinstance(sub.func, ast.Attribute) and sub.func.attr == "index_select")
                            or (isinstance(sub.func, ast.Name) and sub.func.id == "index_select")
                        )
                        and sub.args
                    ):
                        s_u = ast.unparse(sub) if hasattr(ast, "unparse") else "index_select"
                        if not feat_arg or any(isinstance(a, ast.Name) and a.id == feat_arg for a in sub.args[:2]):
                            ln_here = int(getattr(sub, "lineno", fn_start))
                            slice_node_ids.add(id(sub))
                            for a in sub.args[:1]:
                                slice_node_ids.add(id(a))
                            if candidate_slice is None:
                                candidate_slice = (
                                    ln_here,
                                    s_u,
                                    ("index_select", {"lineno": ln_here, "max_cols": 1, "sample": s_u}),
                                )

                # Verify primary branch also consumes full feature tensor `feat_arg` (not merely `.shape`/`.size()`)
                primary_uses_full_feat = False
                if candidate_slice is not None and feat_arg:
                    parent_map: Dict[int, ast.AST] = {}
                    for p_node in ast.walk(fn_node):
                        for ch_node in ast.iter_child_nodes(p_node):
                            parent_map[id(ch_node)] = p_node
                    for sub in ast.walk(fn_node):
                        if isinstance(sub, ast.Name) and sub.id == feat_arg and isinstance(sub.ctx, ast.Load):
                            if id(sub) in slice_node_ids:
                                continue
                            par = parent_map.get(id(sub))
                            if isinstance(par, ast.Attribute) and par.attr in ("shape", "ndim", "dtype", "device", "size"):
                                continue
                            if isinstance(par, ast.Call) and isinstance(par.func, ast.Name) and par.func.id == "len":
                                continue
                            primary_uses_full_feat = True
                            break

                if candidate_slice is not None and primary_uses_full_feat:
                    sub_slice_ln, slice_expr, matched_col_const = candidate_slice
                    slice_vars: Set[str] = set()
                    for sub in ast.walk(fn_node):
                        if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                            if slice_expr and slice_expr in (ast.unparse(sub.value) if hasattr(ast, "unparse") else ""):
                                slice_vars.add(sub.targets[0].id)
                    for m_attr in class_sub_mlp_attrs.get(cls_name, set()):
                        for sub in ast.walk(fn_node):
                            if (
                                isinstance(sub, ast.Call)
                                and isinstance(sub.func, ast.Attribute)
                                and isinstance(sub.func.value, ast.Name)
                                and sub.func.value.id == "self"
                                and sub.func.attr == m_attr
                            ):
                                args_u = " ".join(ast.unparse(a) for a in sub.args) if hasattr(ast, "unparse") else ""
                                if (slice_expr and slice_expr in args_u) or any(
                                    re.search(rf"\b{re.escape(sv)}\b", args_u) for sv in slice_vars
                                ):
                                    uses_nonlinear_sub = True

            if sub_slice_ln is not None:
                c_line = matched_col_const[1]["lineno"] if matched_col_const else sub_slice_ln
                c_name = matched_col_const[0] if matched_col_const else "subset_cols"
                max_cols = int(matched_col_const[1]["max_cols"]) if matched_col_const else 1
                sample_s = str(matched_col_const[1]["sample"]) if matched_col_const else slice_expr
                queries_sub = [
                    "column subset indices",
                    "feature-column index map",
                    "subvector index operator in formal model equation",
                ]
                doc_sub_re = r"\b(?:column\s+indices|specific\s+columns?\s*\[|feature\s+index\s+subset|hardcoded\s+column\s+subset)\b"
                eq_has_col_slice = any(
                    re.search(r"\\mathcal\{I\}|\[:,|\\text\{cols\}|_{[^}]*,\s*\[", str(eq.get("latex") or ""))
                    for eq in (ms.get("equations") or [])
                )
                is_doc_sub = bool(eq_has_col_slice and _has_unnegated_tex_match(doc_sub_re))
                if is_doc_sub:
                    documented_mechanisms.append({
                        "category": "covariate_subset_adapter",
                        "code_citation": f"{rel_posix}:L{sub_slice_ln}",
                        "code_symbol": qname,
                    })
                else:
                    shift_eq_obj = next(
                        (
                            eq_obj
                            for eq_obj in (ms.get("equations") or [])
                            if re.search(
                                r"(?:\\left\s*\(|\()[^=]*\+[^=]*(?:\\right\s*\)|\))\s*\^(?:\{\\top\}|\\top|T)",
                                str(eq_obj.get("latex") or ""),
                            )
                        ),
                        None,
                    )
                    cm_sub: Optional[Dict[str, Any]] = None
                    if shift_eq_obj is not None and max_cols > 1:
                        cm_sub = _find_tex_line_match(
                            ms,
                            [
                                r"\bnonzero\s+only\s+on\s+[a-z]+\b",
                                r"\bsingle\s+(?:scalar\s+)?(?:covariate|attribute|column)\b",
                            ],
                            prefer_sections=("model", "expert", "specif", "empiric"),
                        )
                    elif shift_eq_obj is None:
                        model_eqs = [
                            eq_obj
                            for eq_obj in (ms.get("equations") or [])
                            if any(sk in str(eq_obj.get("section") or "").lower() for sk in ("model", "specif", "expert", "mixture"))
                        ] or list(ms.get("equations") or [])
                        for pat_eq in (
                            r"P_\{[^}]+\}\s*=\s*\\sum",
                            r"\\exp\s*\(",
                            r"\\mathcal\{L\}|\\log\s*\\left\(\s*\\sum",
                        ):
                            for eq_obj in model_eqs:
                                if re.search(pat_eq, str(eq_obj.get("latex") or "")):
                                    cm_sub = {
                                        "file": eq_obj["file"],
                                        "line": eq_obj["line"],
                                        "text": eq_obj["latex"],
                                        "section": eq_obj["section"],
                                        "parent_cite": eq_obj.get("parent_cite", ""),
                                    }
                                    break
                            if cm_sub is not None:
                                break
                    cite_fields_sub = _build_citation_fields(
                        cm_sub, queries_sub, executed_regex=doc_sub_re, category="covariate_subset_adapter"
                    )
                    if cm_sub is None and shift_eq_obj is not None:
                        sh_cite = f"{shift_eq_obj['file']}:L{shift_eq_obj['line']}"
                        cite_fields_sub["search_record"]["closest_section"] = (
                            f"{shift_eq_obj.get('section') or 'Model Specification'} ({sh_cite})"
                        )
                    if cm_sub is not None and shift_eq_obj is not None and max_cols > 1:
                        m_eq_cite = f"{cm_sub['file']}:L{cm_sub['line']}"
                        sub_summary = (
                            f"`{rel_posix}:L{sub_slice_ln}` slices multi-column subset indices via `{slice_expr}` "
                            f"(`{c_name}` at `L{c_line}`: `{sample_s[:85]}`, up to {max_cols} columns"
                            + (" fed through a secondary sub-network" if uses_nonlinear_sub else "")
                            + f"), whereas `{m_eq_cite}` describes a single-attribute targeted shift rather than a {max_cols}-column vector slice."
                        )
                    elif cm_sub is not None:
                        m_eq_cite = f"{cm_sub['file']}:L{cm_sub['line']}"
                        sub_summary = (
                            f"`{rel_posix}:L{sub_slice_ln}` slices feature-column subset indices via `{slice_expr}` "
                            f"(`{c_name}` at `L{c_line}`: `{sample_s[:85]}`, up to {max_cols} column(s)"
                            + (" fed through a secondary sub-network" if uses_nonlinear_sub else "")
                            + f"), whereas the formal model specification equation (`{m_eq_cite}`) operates over the full covariate vector and omits this column-subset adapter."
                        )
                    else:
                        sub_summary = (
                            f"`{rel_posix}:L{sub_slice_ln}` slices hardcoded dataset-specific feature-column subset indices via `{slice_expr}` "
                            f"(`{c_name}` at `L{c_line}`: `{sample_s[:85]}`, up to {max_cols} column(s)"
                            + (" fed through a secondary sub-network" if uses_nonlinear_sub else "")
                            + "), a hardcoded column index mapping not documented in the manuscript."
                        )
                    sub_end_ln = min(fn_end, sub_slice_ln + 3)
                    raw_candidates.append({
                        "priority": file_prio,
                        "category": "covariate_subset_adapter",
                        "severity": "medium",
                        "title": f"Hardcoded feature-column subset adapter (`{c_name}`) in `{qname}`",
                        "summary": sub_summary,
                        "code_file": rel_posix,
                        "code_line": sub_slice_ln,
                        "code_end_line": sub_end_ln,
                        "code_citation": f"{rel_posix}:L{sub_slice_ln}",
                        "code_symbol": qname,
                        "code_snippet": _snip(sub_slice_ln, sub_end_ln, max_l=fn_end),
                        **cite_fields_sub,
                    })

            # 6. Category: `cv_selection_rule_divergence`
            if not is_init_or_reset and not is_dgp_unit and not is_diag_check_file:
                _se_ident_re = re.compile(
                    r"(?:^|[^A-Za-z0-9])(?:one_se|cv_se|val_se|se_vec|se_vals?|stderrs?|std_errs?)(?:[^A-Za-z0-9]|$)"
                )
                has_se_formula = bool(
                    re.search(r"\.std\s*\([^)]*\)\s*/\s*(?:np\.|math\.|torch\.)?sqrt\s*\(", fn_unparsed)
                    or re.search(r"\bsem\s*\(", fn_unparsed)
                    or _se_ident_re.search(fn_unparsed)
                )
                has_cv_sel_context = bool(
                    re.search(r"\b(?:folds?|cv|val|grid|chosen|select|best|anchor|passing|cutoff)\b", fn_unparsed, re.IGNORECASE)
                )
                if has_se_formula and has_cv_sel_context:
                    se_threshold_vars: Set[str] = set()
                    for sub_a in ast.walk(fn_node):
                        if (
                            isinstance(sub_a, ast.Assign)
                            and len(sub_a.targets) == 1
                            and isinstance(sub_a.targets[0], ast.Name)
                            and isinstance(sub_a.value, ast.BinOp)
                            and isinstance(sub_a.value.op, ast.Add)
                        ):
                            rhs_a = ast.unparse(sub_a.value) if hasattr(ast, "unparse") else ""
                            if _se_ident_re.search(rhs_a) or re.search(r"\bse\b|\.std\s*\(|sem\s*\(", rhs_a):
                                se_threshold_vars.add(sub_a.targets[0].id)
                    se_cmp_ln: Optional[int] = None
                    sorted_cmps = sorted(
                        [n for n in ast.walk(fn_node) if isinstance(n, ast.Compare)],
                        key=lambda n: int(getattr(n, "lineno", fn_start)),
                    )
                    for sub in sorted_cmps:
                        cmp_s = ast.unparse(sub) if hasattr(ast, "unparse") else ""
                        if (
                            re.search(r"\bse\b", cmp_s)
                            or _se_ident_re.search(cmp_s)
                            or any(re.search(rf"\b{re.escape(tv)}\b", cmp_s) for tv in se_threshold_vars)
                        ):
                            se_cmp_ln = int(getattr(sub, "lineno", fn_start))
                            break
                    if se_cmp_ln is not None:
                        queries_cv = [
                            "one-standard-error rule",
                            "1-SE cross-validation",
                            "standard error parsimony threshold",
                        ]
                        doc_cv_re = r"\b(?:1[\s-]?SE|one[\s-]?standard[\s-]?error|within\s+one\s+standard\s+error)\b"
                        is_doc_cv = _has_unnegated_tex_match(doc_cv_re)
                        if is_doc_cv:
                            documented_mechanisms.append({
                                "category": "cv_selection_rule_divergence",
                                "code_citation": f"{rel_posix}:L{se_cmp_ln}",
                                "code_symbol": qname,
                            })
                        else:
                            cm_cv = _find_tex_line_match(
                                ms,
                                [
                                    r"\blowest\s+validation\s+(?:log[\s-]?loss|loss|error)\b",
                                    r"\bminimum\s+(?:cross[\s-]?validated|validation)\s+(?:loss|error)\b",
                                    r"\bminimize\s+out[\s-]?of[\s-]?sample\s+cross[\s-]?validation\b",
                                    r"\bchosen\s+by\s+\d+[\s-]?fold\s+cross[\s-]?validation\b",
                                ],
                                prefer_sections=("empiric", "estimat", "simulat", "method"),
                            )
                            cv_end_ln = min(fn_end, se_cmp_ln + 2)
                            raw_candidates.append({
                                "priority": file_prio,
                                "category": "cv_selection_rule_divergence",
                                "severity": "high",
                                "title": f"1-SE cross-validation selection gate in `{qname}`",
                                "summary": (
                                    f"`{rel_posix}:L{se_cmp_ln}` requires cross-validation fold improvement to exceed one standard error "
                                    f"(`std / sqrt(K)`) before selecting the alternative specification, contradicting standard argmin validation loss selection."
                                ),
                                "code_file": rel_posix,
                                "code_line": se_cmp_ln,
                                "code_end_line": cv_end_ln,
                                "code_citation": f"{rel_posix}:L{se_cmp_ln}",
                                "code_symbol": qname,
                                "code_snippet": _snip(max(fn_start, se_cmp_ln - 1), cv_end_ln, max_l=fn_end),
                                **_build_citation_fields(cm_cv, queries_cv, executed_regex=doc_cv_re, category="cv_selection_rule_divergence"),
                            })

    # Order deterministically by pipeline priority, category, file, and line; deduplicate ONLY exact (category, file, line)
    cat_order = list(DIVERGENCE_CATEGORY_LABELS.keys())
    raw_candidates.sort(
        key=lambda c: (
            int(c.get("priority", 99)),
            cat_order.index(c["category"]) if c["category"] in cat_order else 99,
            str(c["code_file"]),
            int(c["code_line"]),
        )
    )

    selected: List[Dict[str, Any]] = []
    seen_exact_sites: Set[Tuple[str, str, int]] = set()
    for cand in raw_candidates:
        cat = str(cand["category"])
        site_key = (cat, str(cand["code_file"]), int(cand["code_line"]))
        if site_key in seen_exact_sites:
            continue
        seen_exact_sites.add(site_key)
        div_idx = len(selected) + 1
        row = {k: v for k, v in cand.items() if k != "priority"}
        row["id"] = f"DIV-{div_idx:02d}"
        row["category_label"] = DIVERGENCE_CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
        selected.append(row)

    return {
        "ok": True,
        "schema": DIVERGENCE_SCHEMA,
        "has_paper": True,
        "status_kind": "ok",
        "entry_manuscript": entry_ms,
        "searched_tex_files": searched_tex_files,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "exempted_dgp_functions": exempted_dgp_functions,
        "scope_applied": scope_applied,
        "divergence_count": len(selected),
        "contradicted_count": sum(1 for r in selected if r["manuscript_status"] == "contradicted_in_manuscript"),
        "absent_count": sum(1 for r in selected if r["manuscript_status"] == "absent_from_manuscript"),
        "documented_non_divergence_count": len(documented_mechanisms),
        "documented_mechanisms": documented_mechanisms,
        "divergences": selected,
    }


REPLICATION_PACKAGE_SCHEMA = "anvil-v5-replication-package/v1"
MAX_REPLICATION_PACKAGE_FILES = 500
MAX_REPLICATION_PACKAGE_BYTES = 64 * 1024 * 1024  # 67,108,864 bytes

_REPL_EXCLUDED_DIR_NAMES: Set[str] = {
    ".git", ".anvil", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    ".foreman", ".crucible", ".anchor", ".ecgberht", ".steward",
}
_REPL_EXCLUDED_BINARY_DATA_EXTS: Set[str] = {
    ".parquet", ".feather", ".h5", ".hdf5", ".pkl", ".pickle", ".pt", ".pth",
    ".ckpt", ".safetensors", ".npz", ".npy", ".rds", ".rda", ".rdata", ".dta",
    ".sav", ".sas7bdat", ".pyc", ".pyo", ".so", ".dll", ".exe", ".zip", ".tar",
    ".gz", ".bz2", ".xz", ".bundle", ".pfx", ".p12", ".pem", ".key",
}
_REPL_SECRET_CONFIG_EXTS: Set[str] = {
    "", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".txt", ".xml", ".properties", ".key", ".pem", ".pfx",
}
_REPL_SAFE_TOP_CONFIG_NAMES: Tuple[str, ...] = (
    "workflow.sh", "run_all.sh", "replicate.sh", "replication.sh", "pipeline.sh", "run.sh",
    "Makefile", "makefile", "GNUmakefile", "Snakefile",
    "pyproject.toml", "requirements.txt", "environment.yml", "DESCRIPTION",
    "README.md", "REPLICATION.md", "replication.md",
)


_REPL_CODE_SOURCE_EXTS: Set[str] = {
    ".py", ".r", ".jl", ".m", ".sh", ".bash", ".js", ".mjs", ".ts",
    ".c", ".cpp", ".cc", ".h", ".hpp", ".sql", ".tex", ".stan", ".bugs", ".jags",
}
_REPL_SECRET_STEM_RE = re.compile(
    r"(?:^|[_.-])(?:secrets?|credentials?|api[_-]?keys?|apikeys?|private[_-]?keys?|auth[_-]?tokens?|access[_-]?keys?|passwd|passwords?)(?:$|[_.-])",
    re.IGNORECASE,
)


def _classify_replication_exclusion(rel_posix: str) -> Optional[str]:
    """Return exclusion category (`'secret_or_env'`, `'raw_data_or_artifact'`, `'vcs_or_cache'`)
    if `rel_posix` must be excluded from a standalone replication package, else `None`.
    """
    parts = Path(rel_posix).parts
    if not parts:
        return "vcs_or_cache"
    low_dirs = [p.lower() for p in parts[:-1]]
    fname = parts[-1]
    fname_low = fname.lower()
    ext_low = Path(fname_low).suffix.lower()
    stem_low = Path(fname_low).stem.lower() if ext_low else fname_low

    for d in low_dirs:
        if d.startswith(".env"):
            return "secret_or_env"
        if d in _REPL_EXCLUDED_DIR_NAMES:
            return "vcs_or_cache"

    if (
        fname_low == ".env"
        or fname_low.startswith(".env.")
        or fname_low.endswith(".env")
        or fname_low in {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "token.json"}
        or ext_low in {".pem", ".key", ".pfx", ".p12"}
        or _REPL_SECRET_STEM_RE.search(stem_low) is not None
    ):
        return "secret_or_env"

    if ext_low in _REPL_EXCLUDED_BINARY_DATA_EXTS:
        return "raw_data_or_artifact"

    # Exclude raw data directories (`Data/`, `datasets/`, etc.) for non-code data artifacts while keeping source code (e.g. `src/data/loader.py`)
    if ext_low not in _REPL_CODE_SOURCE_EXTS:
        for d in low_dirs:
            if d in {"data", "raw_data", "rawdata", "datasets", "dataset"}:
                return "raw_data_or_artifact"

    return None


def _validate_contained_closure_source(repo_resolved: Path, candidate: str | Path) -> Tuple[str, Path]:
    """Validate `candidate` strictly inside `repo_resolved` with zero `..`, zero external absolute
    paths, and zero symlinks/junctions on any path hop (`PATH_ESCAPE_REFUSED` -> HTTP 403).
    """
    if candidate is None:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty closure file entry refused.", cwe="CWE-22", details={"http_status": 403})
    raw_s = str(candidate).strip()
    if not raw_s or "\x00" in raw_s:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Empty or NUL-containing closure path refused.", cwe="CWE-22", details={"http_status": 403})
    norm_tokens = raw_s.replace("\\", "/").split("/")
    if ".." in norm_tokens or ".." in Path(raw_s).parts:
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Parent traversal ('..') refused in closure path '{raw_s}'.",
            cwe="CWE-22",
            details={"candidate": raw_s, "http_status": 403},
        )
    cand_p = Path(raw_s)
    has_root_prefix = raw_s.startswith(("/", "\\"))
    has_drive_rel = bool(cand_p.drive) and not cand_p.is_absolute()
    if has_drive_rel or (os.name == "nt" and has_root_prefix and not cand_p.is_absolute()):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Drive-relative or rooted closure path '{raw_s}' refused.",
            cwe="CWE-22",
            details={"candidate": raw_s, "http_status": 403},
        )

    if cand_p.is_absolute():
        norm_lex = Path(os.path.normpath(str(cand_p)))
        if norm_lex == repo_resolved or not norm_lex.is_relative_to(repo_resolved):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Absolute closure path '{raw_s}' escapes repository root.",
                cwe="CWE-22",
                details={"candidate": raw_s, "http_status": 403},
            )
        rel_parts = norm_lex.relative_to(repo_resolved).parts
    else:
        rel_parts = tuple(pt for pt in cand_p.parts if pt not in ("", "."))
        if not rel_parts:
            raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Closure path resolves to repository root.", cwe="CWE-22", details={"http_status": 403})

    cur = repo_resolved
    for pt in rel_parts:
        cur = cur / pt
        if _is_link_or_junction(cur):
            raise AnvilRefusalError(
                "PATH_ESCAPE_REFUSED",
                f"Symlink or junction closure entry '{raw_s}' refused at '{pt}'.",
                cwe="CWE-22",
                details={"candidate": raw_s, "http_status": 403},
            )
    resolved_f = cur.resolve()
    if resolved_f == repo_resolved or not resolved_f.is_relative_to(repo_resolved):
        raise AnvilRefusalError(
            "PATH_ESCAPE_REFUSED",
            f"Resolved closure path '{raw_s}' escapes repository root.",
            cwe="CWE-22",
            details={"candidate": raw_s, "http_status": 403},
        )
    rel_posix = resolved_f.relative_to(repo_resolved).as_posix()
    return rel_posix, resolved_f


def materialize_replication_package(
    repo_root: str | Path,
    store_root: str | Path,
    *,
    closure_files: Optional[Sequence[str | Path]] = None,
    active_pipeline: Optional[str] = None,
    paper_map: Optional[Dict[str, Any]] = None,
    paper_path: Optional[str | Path] = None,
    session_meta: Optional[Dict[str, Any]] = None,
    allowed_root: Optional[str | Path] = None,
    entrypoints: Optional[Sequence[str]] = None,
    symbol_slice: Optional[Dict[str, Any]] = None,
    expand_load_time_imports: bool = True,
    max_files: int = MAX_REPLICATION_PACKAGE_FILES,
    max_bytes: int = MAX_REPLICATION_PACKAGE_BYTES,
) -> Dict[str, Any]:
    """Atomically materialize a standalone replication package (`closure_files` + deterministic
    `REPLICATION_MANIFEST.md`) into `<store_root>/.anvil/replication_package/` via temp-dir
    staging + rename swap with ZERO mutation to `repo_root`.

    - Excludes `.env`/secrets, `.git`/`.anvil`/`__pycache__`, raw `Data/` directories, and binary datasets.
    - Enforces `<= 500` files and `<= 64 MB` (`67,108,864` bytes) before/during staging (`BOUND_EXCEEDED_REFUSAL`, HTTP 400).
    - Rejects `..`, escaping absolute paths, and symlinks/junctions on source & destination (`PATH_ESCAPE_REFUSED`, HTTP 403).
    """
    from anvil_v4_process import exclusive_file_lock as _proc_lock

    if max_files <= 0 or max_files > MAX_REPLICATION_PACKAGE_FILES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_files ({max_files}) must be within 1..{MAX_REPLICATION_PACKAGE_FILES}.",
            details={"http_status": 400, "bound_name": "max_replication_package_files", "bound_limit": MAX_REPLICATION_PACKAGE_FILES, "observed_value": max_files},
        )
    if max_bytes <= 0 or max_bytes > MAX_REPLICATION_PACKAGE_BYTES:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"max_bytes ({max_bytes}) must be within 1..{MAX_REPLICATION_PACKAGE_BYTES}.",
            details={"http_status": 400, "bound_name": "max_replication_package_bytes", "bound_limit": MAX_REPLICATION_PACKAGE_BYTES, "observed_value": max_bytes},
        )

    raw_repo = Path(repo_root)
    raw_store = Path(store_root)
    if "\x00" in str(repo_root) or "\x00" in str(store_root) or ".." in raw_store.parts:
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Invalid traversal or NUL in repo_root/store_root.", cwe="CWE-22", details={"http_status": 403})
    if _is_link_or_junction(raw_repo) or not raw_repo.exists() or not raw_repo.is_dir():
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Repository root does not exist or is a symlink/junction.", cwe="CWE-22", details={"http_status": 403})
    if _is_link_or_junction(raw_store):
        raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Destination store_root is a symlink/junction.", cwe="CWE-22", details={"http_status": 403})

    repo_resolved = raw_repo.resolve()
    store_resolved = raw_store.resolve()
    anvil_dir = store_resolved / ".anvil"
    final_pkg_dir = anvil_dir / "replication_package"
    for chk_d in (anvil_dir, final_pkg_dir):
        if _is_link_or_junction(chk_d):
            raise AnvilRefusalError("PATH_ESCAPE_REFUSED", f"Symlink or junction refused at '{chk_d.name}'.", cwe="CWE-22", details={"http_status": 403})

    eff_paper_path: Optional[Path] = None
    if paper_path is not None and str(paper_path).strip():
        cand_pp = Path(paper_path)
        if not _is_link_or_junction(cand_pp) and cand_pp.exists():
            eff_paper_path = cand_pp.resolve()
    elif isinstance(paper_map, dict):
        pm_p = str((paper_map.get("paper_info") or {}).get("primary_tex") or paper_map.get("paper_path") or "").strip()
        if pm_p and not _is_link_or_junction(Path(pm_p)) and Path(pm_p).exists():
            eff_paper_path = Path(pm_p).resolve()

    eff_allowed_root: Optional[Path] = Path(allowed_root).resolve() if allowed_root is not None else None
    if eff_allowed_root is None and isinstance(session_meta, dict) and session_meta.get("cockpit_dir"):
        cand_cd = Path(str(session_meta["cockpit_dir"]))
        if cand_cd.exists() and not _is_link_or_junction(cand_cd):
            cd_res = cand_cd.resolve()
            if eff_paper_path is not None and (eff_paper_path == cd_res or cd_res in eff_paper_path.parents):
                eff_allowed_root = cd_res
            elif eff_paper_path is not None and cd_res.parent != Path(cd_res.anchor) and (eff_paper_path == cd_res.parent or cd_res.parent in eff_paper_path.parents):
                eff_allowed_root = cd_res.parent
    scope_info = discover_paper_matched_scopes(repo_resolved, eff_paper_path, allowed_root=eff_allowed_root)
    scope_summary = resolve_active_pipeline_scope(scope_info, pipeline_id=active_pipeline)

    candidate_pairs: List[Tuple[str, Path]] = []
    seen_rels: Set[str] = set()
    excluded_records: Dict[str, List[str]] = {
        "secret_or_env": [],
        "raw_data_or_artifact": [],
        "vcs_or_cache": [],
    }

    if closure_files is not None:
        if len(closure_files) > max_files:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Closure file count ({len(closure_files)}) exceeds limit of {max_files} files.",
                details={"http_status": 400, "bound_name": "max_replication_package_files", "bound_limit": max_files, "observed_value": len(closure_files)},
            )
        for raw_entry in closure_files:
            rel_p, abs_p = _validate_contained_closure_source(repo_resolved, raw_entry)
            excl_cat = _classify_replication_exclusion(rel_p)
            if excl_cat is not None:
                if rel_p not in excluded_records[excl_cat]:
                    excluded_records[excl_cat].append(rel_p)
                continue
            if not abs_p.is_file():
                raise AnvilRefusalError(
                    "PATH_ESCAPE_REFUSED",
                    f"Closure entry '{rel_p}' is not a regular file inside repository.",
                    cwe="CWE-22",
                    details={"candidate": rel_p, "http_status": 403},
                )
            if rel_p not in seen_rels:
                seen_rels.add(rel_p)
                candidate_pairs.append((rel_p, abs_p))
    else:
        raw_auto_rels: List[str] = []
        if scope_summary.get("scoped") and scope_summary.get("active_files"):
            raw_auto_rels.extend(scope_summary["active_files"])
        elif scope_info.get("paper_matched_files"):
            raw_auto_rels.extend(scope_info["paper_matched_files"])
        else:
            prod_fps, _ = _scan_contained_source_files(repo_resolved)
            raw_auto_rels.extend(fp.relative_to(repo_resolved).as_posix() for fp in prod_fps)

        for wf_mf in scope_info.get("workflow_manifests") or []:
            cand_wf = repo_resolved / wf_mf
            if not _is_link_or_junction(cand_wf) and cand_wf.is_file() and cand_wf.resolve().is_relative_to(repo_resolved):
                raw_auto_rels.append(cand_wf.resolve().relative_to(repo_resolved).as_posix())

        for cfg_name in _REPL_SAFE_TOP_CONFIG_NAMES:
            cand_cfg = repo_resolved / cfg_name
            if not _is_link_or_junction(cand_cfg) and cand_cfg.is_file() and cand_cfg.resolve().is_relative_to(repo_resolved):
                raw_auto_rels.append(cfg_name)

        for rel_c in sorted(dict.fromkeys(raw_auto_rels)):
            rel_p, abs_p = _validate_contained_closure_source(repo_resolved, rel_c)
            excl_cat = _classify_replication_exclusion(rel_p)
            if excl_cat is not None:
                if rel_p not in excluded_records[excl_cat]:
                    excluded_records[excl_cat].append(rel_p)
                continue
            if abs_p.is_file() and rel_p not in seen_rels:
                seen_rels.add(rel_p)
                candidate_pairs.append((rel_p, abs_p))

    # Also audit top-level / shallow repo entries so REPLICATION_MANIFEST.md summarizes excluded Data/ and secrets
    try:
        for cur_r, sub_dirs, sub_files in os.walk(repo_resolved, followlinks=False):
            cur_rp = Path(cur_r)
            kept_d: List[str] = []
            for d in sorted(sub_dirs):
                dp = cur_rp / d
                if _is_link_or_junction(dp):
                    continue
                rel_d = dp.relative_to(repo_resolved).as_posix()
                d_cat = _classify_replication_exclusion(f"{rel_d}/_probe")
                if d_cat is not None:
                    tag_d = f"{rel_d}/"
                    if d_cat != "vcs_or_cache" and tag_d not in excluded_records[d_cat] and len(excluded_records[d_cat]) < 64:
                        excluded_records[d_cat].append(tag_d)
                    continue
                kept_d.append(d)
            sub_dirs[:] = kept_d
            for fn in sorted(sub_files):
                fp = cur_rp / fn
                if _is_link_or_junction(fp):
                    continue
                rel_fn = fp.relative_to(repo_resolved).as_posix()
                f_cat = _classify_replication_exclusion(rel_fn)
                if f_cat is not None and f_cat != "vcs_or_cache":
                    if rel_fn not in excluded_records[f_cat] and len(excluded_records[f_cat]) < 64:
                        excluded_records[f_cat].append(rel_fn)
    except OSError:
        pass

    candidate_pairs.sort(key=lambda item: item[0])
    total_pkg_files = len(candidate_pairs) + 1  # includes REPLICATION_MANIFEST.md
    if total_pkg_files > max_files:
        raise AnvilRefusalError(
            "BOUND_EXCEEDED_REFUSAL",
            f"Replication package file count including manifest ({total_pkg_files}) exceeds limit of {max_files} files.",
            details={
                "http_status": 400,
                "bound_name": "max_replication_package_files",
                "bound_limit": max_files,
                "observed_value": total_pkg_files,
            },
        )

    # Pre-check stat sizes BEFORE staging
    prelim_bytes = 0
    for rel_p, abs_p in candidate_pairs:
        st = os.stat(abs_p, follow_symlinks=False)
        prelim_bytes += int(st.st_size)
        if prelim_bytes > max_bytes:
            raise AnvilRefusalError(
                "BOUND_EXCEEDED_REFUSAL",
                f"Replication package size ({prelim_bytes} bytes) exceeds 64 MB limit ({max_bytes} bytes).",
                details={
                    "http_status": 400,
                    "bound_name": "max_replication_package_bytes",
                    "bound_limit": max_bytes,
                    "observed_value": prelim_bytes,
                    "offending_file": rel_p,
                },
            )

    # Retain load-time-imported Python modules so `import sibling_mod` never crashes with ImportError
    # at runtime even when sibling functions inside `sibling_mod` are statically unreached!
    retained_load_time_imports: List[str] = []
    if expand_load_time_imports:
        py_seeds = [rel_p for rel_p, _ in candidate_pairs if rel_p.lower().endswith(".py")]
        if py_seeds:
            all_prod_fps, _ = _scan_contained_source_files(repo_resolved)
            if any(
                fp.relative_to(repo_resolved).as_posix() not in seen_rels
                for fp in all_prod_fps
                if fp.suffix.lower() == ".py"
            ):
                imp_adj, _ = _build_repo_import_graph(repo_resolved, all_prod_fps)
                imp_closure = _compute_import_closure(py_seeds, imp_adj)
                for imp_rel in imp_closure:
                    if imp_rel in seen_rels:
                        continue
                    excl_c = _classify_replication_exclusion(imp_rel)
                    if excl_c is not None:
                        if imp_rel not in excluded_records[excl_c]:
                            excluded_records[excl_c].append(imp_rel)
                        continue
                    imp_rel_norm, imp_abs = _validate_contained_closure_source(repo_resolved, imp_rel)
                    if imp_abs.is_file() and imp_rel_norm not in seen_rels:
                        st_imp = os.stat(imp_abs, follow_symlinks=False)
                        if len(candidate_pairs) + 2 > max_files:
                            raise AnvilRefusalError(
                                "BOUND_EXCEEDED_REFUSAL",
                                f"Replication package file count including load-time imports exceeds limit of {max_files} files.",
                                details={
                                    "http_status": 400,
                                    "bound_name": "max_replication_package_files",
                                    "bound_limit": max_files,
                                    "observed_value": len(candidate_pairs) + 2,
                                },
                            )
                        prelim_bytes += int(st_imp.st_size)
                        if prelim_bytes > max_bytes:
                            raise AnvilRefusalError(
                                "BOUND_EXCEEDED_REFUSAL",
                                f"Replication package size ({prelim_bytes} bytes) exceeds 64 MB limit ({max_bytes} bytes).",
                                details={
                                    "http_status": 400,
                                    "bound_name": "max_replication_package_bytes",
                                    "bound_limit": max_bytes,
                                    "observed_value": prelim_bytes,
                                    "offending_file": imp_rel_norm,
                                },
                            )
                        seen_rels.add(imp_rel_norm)
                        candidate_pairs.append((imp_rel_norm, imp_abs))
                        retained_load_time_imports.append(imp_rel_norm)
                if retained_load_time_imports:
                    candidate_pairs.sort(key=lambda item: item[0])

    # Compute symbol-level slice metadata for manifest disclosure when Python modules are small/bounded
    eff_symbol_slice: Optional[Dict[str, Any]] = symbol_slice
    if eff_symbol_slice is None:
        pkg_py_rels = [rel_p for rel_p, _ in candidate_pairs if rel_p.lower().endswith(".py")]
        if pkg_py_rels and len(pkg_py_rels) <= 160 and prelim_bytes <= 8 * 1024 * 1024:
            eff_eps_slice: List[str] = list(entrypoints) if entrypoints is not None else []
            if not eff_eps_slice:
                for p_it in scope_summary.get("available_pipelines") or []:
                    for ep_r in p_it.get("entrypoints") or []:
                        if ep_r in seen_rels and ep_r not in eff_eps_slice:
                            eff_eps_slice.append(ep_r)
            eff_symbol_slice = slice_call_graph(
                repo_resolved,
                entrypoints=eff_eps_slice or None,
                scope_files=pkg_py_rels,
            )

    lock_dir = Path(tempfile.gettempdir()) / "anchor_anvil_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_hash = hashlib.sha256(str(final_pkg_dir).lower().encode("utf-8")).hexdigest()[:24]
    lock_file = lock_dir / f"repl_pkg.{lock_hash}.lock"

    with _proc_lock(lock_file, timeout_sec=30.0):
        anvil_dir.mkdir(parents=True, exist_ok=True)
        # Crash recovery + stale staging sweep under the exclusive package lock:
        # 1) If a prior hard crash occurred between moving `replication_package` -> `.repl_pkg_old_*`
        #    and moving `.repl_pkg_tmp_*` -> `replication_package`, restore the newest `.repl_pkg_old_*`.
        # 2) Sweep any leftover `.repl_pkg_tmp_*` or `.repl_pkg_old_*` staging directories.
        try:
            stale_olds = sorted(
                [p for p in anvil_dir.iterdir() if p.name.startswith(".repl_pkg_old_") and not _is_link_or_junction(p)],
                key=lambda p: p.stat().st_mtime_ns,
                reverse=True,
            )
            if not final_pkg_dir.exists() and stale_olds:
                try:
                    os.replace(str(stale_olds[0]), str(final_pkg_dir))
                    stale_olds = stale_olds[1:]
                except OSError:
                    pass
            for stale_p in list(anvil_dir.iterdir()):
                if stale_p.name.startswith((".repl_pkg_tmp_", ".repl_pkg_old_")):
                    shutil.rmtree(stale_p, ignore_errors=True)
        except OSError:
            pass

        nonce = f"{time.time_ns()}_{os.urandom(4).hex()}"
        tmp_pkg_dir = anvil_dir / f".repl_pkg_tmp_{os.getpid()}_{nonce}"
        old_pkg_dir = anvil_dir / f".repl_pkg_old_{os.getpid()}_{nonce}"
        try:
            tmp_pkg_dir.mkdir(parents=True, exist_ok=False)
            manifest_rows: List[Dict[str, Any]] = []
            running_bytes = 0

            for rel_p, abs_p in candidate_pairs:
                if _is_link_or_junction(abs_p):
                    raise AnvilRefusalError(
                        "PATH_ESCAPE_REFUSED",
                        f"Symlink closure source '{rel_p}' refused during staging.",
                        cwe="CWE-22",
                        details={"candidate": rel_p, "http_status": 403},
                    )
                data = abs_p.read_bytes()
                running_bytes += len(data)
                if running_bytes > max_bytes:
                    raise AnvilRefusalError(
                        "BOUND_EXCEEDED_REFUSAL",
                        f"Replication package size ({running_bytes} bytes) exceeds 64 MB limit ({max_bytes} bytes).",
                        details={
                            "http_status": 400,
                            "bound_name": "max_replication_package_bytes",
                            "bound_limit": max_bytes,
                            "observed_value": running_bytes,
                        },
                    )
                f_sha = hashlib.sha256(data).hexdigest()
                dst_f = tmp_pkg_dir / Path(rel_p)
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                with dst_f.open("wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                manifest_rows.append({
                    "path": rel_p,
                    "sha256": f_sha,
                    "bytes": len(data),
                })

            eff_pipe_label = str(scope_summary.get("active_pipeline") or active_pipeline or "all_paper_matched")
            paper_title = ""
            if isinstance(paper_map, dict):
                paper_title = str(paper_map.get("paper_title") or "").strip()
            if not paper_title and isinstance(session_meta, dict):
                paper_title = str(session_meta.get("paper_title") or session_meta.get("title") or "").strip()

            entrypoints: List[str] = []
            for p_item in scope_summary.get("available_pipelines") or []:
                if eff_pipe_label in ("all_paper_matched", "unscoped", "") or p_item.get("id") == eff_pipe_label:
                    for ep in p_item.get("entrypoints") or []:
                        ext_e = Path(ep).suffix.lower()
                        cmd_bin = "Rscript" if ext_e == ".r" else ("node" if ext_e in {".js", ".mjs", ".ts"} else "python")
                        cmd_str = f"{cmd_bin} {ep}"
                        if cmd_str not in entrypoints:
                            entrypoints.append(cmd_str)
            if not entrypoints:
                for wf_rel in scope_info.get("workflow_manifests") or []:
                    if wf_rel in seen_rels:
                        entrypoints.append(f"bash {wf_rel}" if wf_rel.endswith(".sh") else f"make -f {wf_rel}")

            md_lines: List[str] = [
                f"# Standalone Replication Package Manifest — {repo_resolved.name}",
                "",
                f"- **Schema:** `{REPLICATION_PACKAGE_SCHEMA}`",
                f"- **Repository Label:** `{repo_resolved.name}`",
                f"- **Active Pipeline Scope:** `{eff_pipe_label}`",
                f"- **Exported Closure Files:** `{len(manifest_rows)}` (bound `<= {max_files}`)",
                f"- **Total Closure Size:** `{running_bytes}` bytes (bound `<= {max_bytes}` bytes / 64 MB)",
            ]
            if paper_title:
                md_lines.append(f"- **Companion Manuscript:** {paper_title}")
            md_lines.extend(["", "## 1. Replication Entrypoint Commands", ""])
            if entrypoints:
                for cmd_s in entrypoints:
                    md_lines.append(f"- `{cmd_s}`")
            else:
                md_lines.append("- Static closure package (no single CLI entrypoint script detected).")

            md_lines.extend([
                "",
                "## 2. Exported Closure Files & SHA-256 Digests",
                "",
                "| Relative Path | Bytes | SHA-256 |",
                "|---|---:|---|",
            ])
            for row in manifest_rows:
                md_lines.append(f"| `{row['path']}` | {row['bytes']} | `{row['sha256']}` |")

            md_lines.extend([
                "",
                "## 3. Excluded Secrets, Credentials & Raw Dataset Artifacts",
                "",
                f"- **Excluded Secret / Env Files (`{len(excluded_records['secret_or_env'])}`):** "
                + (", ".join(f"`{x}`" for x in sorted(excluded_records["secret_or_env"])[:20]) or "none present"),
                f"- **Excluded Raw Data / Binary Artifacts (`{len(excluded_records['raw_data_or_artifact'])}`):** "
                + (", ".join(f"`{x}`" for x in sorted(excluded_records["raw_data_or_artifact"])[:20]) or "none present"),
                "",
            ])
            if eff_symbol_slice is not None:
                md_lines.extend([
                    "## 4. Symbol-Level Call-Graph Slice Summary",
                    "",
                    f"- **Reached Symbols:** `{len(eff_symbol_slice.get('reached') or [])}`",
                    f"- **Uncertain Dynamic Symbols:** `{len(eff_symbol_slice.get('uncertain') or [])}`",
                    f"- **Disclosed Unreached Sibling Symbols:** `{len(eff_symbol_slice.get('unreached') or [])}`",
                    f"- **Load-Time Imported Files Retained:** `{len(eff_symbol_slice.get('load_time_imported_files') or [])}`",
                    "",
                ])
            manifest_md_bytes = ("\n".join(md_lines)).encode("utf-8")
            if running_bytes + len(manifest_md_bytes) > max_bytes:
                raise AnvilRefusalError(
                    "BOUND_EXCEEDED_REFUSAL",
                    f"Replication package size including manifest ({running_bytes + len(manifest_md_bytes)} bytes) exceeds 64 MB limit ({max_bytes} bytes).",
                    details={
                        "http_status": 400,
                        "bound_name": "max_replication_package_bytes",
                        "bound_limit": max_bytes,
                        "observed_value": running_bytes + len(manifest_md_bytes),
                    },
                )

            manifest_file_tmp = tmp_pkg_dir / "REPLICATION_MANIFEST.md"
            with manifest_file_tmp.open("wb") as mfh:
                mfh.write(manifest_md_bytes)
                mfh.flush()
                os.fsync(mfh.fileno())
            manifest_sha = hashlib.sha256(manifest_md_bytes).hexdigest()

            had_existing = final_pkg_dir.exists()
            if had_existing:
                if _is_link_or_junction(final_pkg_dir):
                    raise AnvilRefusalError("PATH_ESCAPE_REFUSED", "Destination replication_package is a symlink/junction.", cwe="CWE-22", details={"http_status": 403})
                os.replace(str(final_pkg_dir), str(old_pkg_dir))
            try:
                os.replace(str(tmp_pkg_dir), str(final_pkg_dir))
            except Exception:
                if had_existing and old_pkg_dir.exists() and not final_pkg_dir.exists():
                    try:
                        os.replace(str(old_pkg_dir), str(final_pkg_dir))
                    except OSError:
                        pass
                raise
            if old_pkg_dir.exists():
                shutil.rmtree(old_pkg_dir, ignore_errors=True)
        finally:
            if tmp_pkg_dir.exists():
                shutil.rmtree(tmp_pkg_dir, ignore_errors=True)
            if old_pkg_dir.exists():
                shutil.rmtree(old_pkg_dir, ignore_errors=True)

    return {
        "ok": True,
        "schema": REPLICATION_PACKAGE_SCHEMA,
        "materialized": True,
        "package_dir": str(final_pkg_dir),
        "manifest_path": str(final_pkg_dir / "REPLICATION_MANIFEST.md"),
        "manifest_rel_path": ".anvil/replication_package/REPLICATION_MANIFEST.md",
        "manifest_sha256": manifest_sha,
        "active_pipeline": eff_pipe_label,
        "file_count": len(manifest_rows),
        "total_bytes": running_bytes,
        "entrypoints": entrypoints,
        "files": manifest_rows,
        "excluded_counts": {
            "secrets": len(excluded_records["secret_or_env"]),
            "data": len(excluded_records["raw_data_or_artifact"]),
            "clutter": len(excluded_records["vcs_or_cache"]),
        },
        "excluded_summary": {
            "secret_or_env_count": len(excluded_records["secret_or_env"]),
            "raw_data_or_artifact_count": len(excluded_records["raw_data_or_artifact"]),
            "vcs_or_cache_count": len(excluded_records["vcs_or_cache"]),
            "secret_or_env": sorted(excluded_records["secret_or_env"])[:20],
            "raw_data_or_artifact": sorted(excluded_records["raw_data_or_artifact"])[:20],
        },
        "retained_load_time_imports": sorted(retained_load_time_imports),
        "symbol_slice": {
            "reached": list(eff_symbol_slice.get("reached") or []),
            "uncertain": list(eff_symbol_slice.get("uncertain") or []),
            "unreached": list(eff_symbol_slice.get("unreached") or []),
            "load_time_imported_files": list(eff_symbol_slice.get("load_time_imported_files") or []),
            "shadowed_allocations": list(eff_symbol_slice.get("shadowed_allocations") or []),
        } if eff_symbol_slice is not None else None,
    }


def _worker_main(argv: Sequence[str]) -> int:
    if len(argv) == 2 and argv[0] == "--_gm-manifest":
        return _run_gm_worker(Path(argv[1]))
    if len(argv) == 2 and argv[0] == "--_prof-manifest":
        return _run_untraced_profiler_worker(Path(argv[1]))
    sys.stderr.write("Internal worker entrypoint requires --_gm-manifest or --_prof-manifest <path>.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))

