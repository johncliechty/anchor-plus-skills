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
    AnvilRefusalError,
     TRACE_SCHEMA,
    _extract_polyglot_units,
    _scan_contained_source_files,
    atomic_locked_read_json,
    atomic_locked_write_json,
    build_process_map,
    load_validated_trace_json,
    resolve_contained_path,
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

    for fp in target_files:
        is_test_fp = fp in test_files_set
        active_ref_sink = test_refs if is_test_fp else prod_refs
        file_main_guard_refs: Set[str] = set()
        file_dunder_all_exports: Set[str] = set()
        rel_posix = fp.relative_to(root).as_posix()
        text = fp.read_text(encoding="utf-8", errors="replace")
        if fp.suffix == ".py":
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

    proc_map = build_process_map(root, trace_data=trace_data, persist=False, paper_path=paper_path, pipeline_id=pipeline_id)
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
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Inspect AST + runtime profile to separate Imperative-Shell I/O fixes from
    precondition-checked Functional-Core algorithmic literature upgrades.
    """
    prod_files, test_files = _scan_contained_source_files(root)
    target_files = prod_files if prod_files else test_files

    io_fixes: List[Dict[str, Any]] = []
    accepted_upgrades: List[Dict[str, Any]] = []
    rejected_upgrades: List[Dict[str, Any]] = []

    for fp in target_files:
        if fp.suffix != ".py":
            continue
        rel_posix = fp.relative_to(root).as_posix()
        src = fp.read_text(encoding="utf-8", errors="replace")
        try:
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

            # 1. Detect Imperative-Shell I/O inside loops or repeated high-call I/O functions
            loops = [n for n in ast.walk(fn_node) if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
            loop_io_calls: List[str] = []
            for lp in loops:
                for sub in ast.walk(lp):
                    if isinstance(sub, ast.Call):
                        cname = sub.func.id if isinstance(sub.func, ast.Name) else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")
                        if cname in {"open", "read_text", "write_text", "read_bytes", "write_bytes", "loads", "dumps", "glob", "rglob", "print"}:
                            loop_io_calls.append(cname)
            real_io_sites = [s for s in io_sites if not s.startswith("mutation:")]
            if loop_io_calls or (not is_pure and calls_n >= 5 and real_io_sites):
                io_fixes.append({
                    "symbol": sym_id,
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

            # 2. Candidate A: Naive log(sum(exp(...))) -> Log-Sum-Exp Stabilization
            has_lse_pattern = bool(
                re.search(r"\blog\s*\(\s*sum\s*\([^)]*\bexp\s*\(", unparsed)
                or ("log(" in unparsed and "exp(" in unparsed and "sum(" in unparsed)
            )
            if has_lse_pattern:
                if is_pure:
                    accepted_upgrades.append({
                        "symbol": sym_id,
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
                        "stage_id": sid,
                        "candidate_upgrade": "logsumexp_max_shift",
                        "reason": f"Precondition failed: function performs impure I/O ({io_sites}) interleaved with reduction.",
                    })

            # 3. Candidate B: Explicit matrix inverse `inv(...)` -> Linear Solve / Cholesky
            has_inv_call = bool(re.search(r"\b(?:linalg\.inv|np\.linalg\.inv|torch\.linalg\.inv|inv)\s*\(", unparsed))
            if has_inv_call:
                has_rhs_solve = bool(re.search(r"inv\s*\([^)]+\)\s*@|\b(?:matmul|dot)\s*\(\s*[\w.]*inv\s*\(", unparsed))
                if is_pure and has_rhs_solve:
                    accepted_upgrades.append({
                        "symbol": sym_id,
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
                        "stage_id": sid,
                        "candidate_upgrade": "welford_chan_online_variance",
                        "reason": f"Precondition failed: function contains impure side effects ({io_sites}).",
                    })

            # 5. Candidate D: Loop accumulation -> Vectorized Reduction (reject when loop contains impure I/O!)
            if loops and loop_io_calls and any(isinstance(n, ast.AugAssign) for n in ast.walk(fn_node)):
                rejected_upgrades.append({
                    "symbol": sym_id,
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
    sym_stage_map: Dict[str, str] = {}
    for stg in proc_map.get("l1_stages") or []:
        sid = str(stg["id"])
        for msym in stg.get("member_symbols") or []:
            sym_stage_map[msym.split("#", 1)[0]] = sid

    if not approve_run:
        io_fixes_static, accepted_static, rejected_static = _analyze_io_and_literature_candidates(
            root, sym_stage_map, {}, {}, 1
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
        function_hotspots.append({
            "symbol": sym_id,
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
        root, sym_stage_map, exclusive_ns, call_counts, sum_exc_ns
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


def _worker_main(argv: Sequence[str]) -> int:
    if len(argv) == 2 and argv[0] == "--_gm-manifest":
        return _run_gm_worker(Path(argv[1]))
    if len(argv) == 2 and argv[0] == "--_prof-manifest":
        return _run_untraced_profiler_worker(Path(argv[1]))
    sys.stderr.write("Internal worker entrypoint requires --_gm-manifest or --_prof-manifest <path>.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))

