"""AST scan for in-method imports that SHADOW a module-level name (rearch W7).

The ``os``/``datetime`` shadowing class: a handler that does ``import os`` (or
``from datetime import datetime``) INSIDE a method rebinds a name that is already
bound at module scope. In the monolith this is where the do_GET/do_POST arms hid
their dependencies; migrating handlers to module-level functions structurally
eliminates the class (W8 drives the count to zero). This scan — modeled on
``distro.py``'s ``ast``-based import walk — is the mechanical detector.

A violation is: an ``Import`` / ``ImportFrom`` node whose enclosing scope is a
function (``def``/``async def``, at any nesting depth) and whose bound LOCAL name
collides with a name bound at MODULE level (a top-level import, assignment,
``def``, or ``class``). The bound local name is the alias when present, else the
imported top-level name.

Pure stdlib (``ast``), no third-party deps — importable by the gate test with no
side effects; also runnable as a CLI (``python -m tools.route_import_scan <file>``).
"""

from __future__ import annotations

import ast
import sys
from collections import namedtuple

Violation = namedtuple("Violation", "name lineno kind scope")


def _module_level_names(tree: ast.Module) -> set:
    """Names bound at MODULE scope (imports, assignments, defs, classes)."""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def _bound_local_names(node) -> list:
    """The local name(s) an import node binds, with each node's lineno."""
    out = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append((alias.asname or alias.name.split(".", 1)[0], "import"))
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            out.append((alias.asname or alias.name, "from-import"))
    return out


def scan_shadowing_imports(source_text: str, source_name: str = "<source>"):
    """Return the list of :class:`Violation`s in ``source_text``.

    Each violation is an in-function import whose bound local name shadows a
    module-level name. Unparseable source yields ``[]`` (a syntax error is a
    separate failure surfaced elsewhere).
    """
    try:
        tree = ast.parse(source_text, filename=source_name)
    except (SyntaxError, ValueError):
        return []

    module_names = _module_level_names(tree)
    violations = []

    # Attribute each in-function import to its INNERMOST enclosing function (the
    # scope where the name is actually rebound), not the outermost — a nested
    # helper's ``import os`` is reported against the helper, never its parent.
    # We record each import node exactly ONCE by pairing it with the nearest
    # ``def``/``async def`` on its ancestor chain (``None`` == module scope, which
    # is a legitimate top-level import, not a violation).
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # The imports whose NEAREST enclosing function is exactly ``node``: walk
        # this function's body but stop descending into a nested function (that
        # import belongs to the nested function's own pass over the tree).
        for child in _imports_directly_in(node):
            for local_name, kind in _bound_local_names(child):
                if local_name in module_names:
                    violations.append(Violation(
                        name=local_name, lineno=child.lineno,
                        kind=kind, scope=node.name))
    return violations


def _imports_directly_in(func):
    """Yield the Import/ImportFrom nodes whose innermost enclosing scope is ``func``.

    Descends ``func``'s body but does NOT cross into a nested ``def``/``async
    def``/``lambda`` (those imports belong to the nested scope) — so each import
    is attributed to exactly one function and counted once across the whole walk.
    """
    stack = list(getattr(func, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # A new function scope — its imports are attributed there, not here.
            continue
        stack.extend(ast.iter_child_nodes(node))


def scan_file(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return scan_shadowing_imports(fh.read(), source_name=path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m tools.route_import_scan <file.py> [<file.py> ...]")
        return 2
    total = 0
    for path in argv:
        vios = scan_file(path)
        total += len(vios)
        if vios:
            print(f"{path}: {len(vios)} shadowing in-method import(s):")
            for v in vios:
                print(f"  line {v.lineno}: {v.kind} '{v.name}' "
                      f"in {v.scope}() shadows a module-level name")
        else:
            print(f"{path}: clean (no shadowing in-method imports)")
    return 1 if total else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
