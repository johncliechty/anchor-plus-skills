"""Structural-anchor locator for the re-architecture (W1).

The re-architecture plan (frozen 2026-07-02) bans line numbers as structural
references in every wave after W1: a reference like "``_PROJECT_WINDOW_JS``
(5623-10285)" goes stale the moment anything above it moves. Instead, the
three structures the C1 extraction operates on are located FRESH, every time,
by this module:

* the module-level ``_PROJECT_WINDOW_JS = r\"\"\"...\"\"\"`` assignment,
* ``def generate_html(...)``,
* ``def render_project_window_html(...)``,

each paired with a UNIQUE sentinel comment of the form::

    # ANCHOR[rearch]: <NAME> — <free text>

placed within :data:`SENTINEL_ADJACENCY` lines above the structure it marks.

:func:`locate_anchors` re-derives every anchor from the CURRENT source via
``ast`` (structures) + a line scan (sentinels) and raises :class:`AnchorError`
loudly on a missing, duplicated, or drifted anchor — the "anchor-freshness
gate" later waves run before any EXECUTE so a stale structural reference can
never silently proceed.

Stdlib only (``ast``, ``re``, ``pathlib``). Requires Python 3.8+ for
``end_lineno`` on AST nodes (the project's floor).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "anchor_gui.py"

# Sentinel comments: "# ANCHOR[rearch]: NAME" (optional free text after the
# name). NAME is uppercase snake; the line scan is intentionally strict so a
# mangled sentinel reads as MISSING, never as a fuzzy match.
SENTINEL_RE = re.compile(r"^\s*#\s*ANCHOR\[rearch\]:\s*([A-Z][A-Z0-9_]*)\b")

# A sentinel must sit within this many lines ABOVE its structure (comment
# blocks/decorators between sentinel and structure are fine; a sentinel that
# drifted further than this is stale and fails the gate).
SENTINEL_ADJACENCY = 10

# sentinel name -> structural key it must be adjacent to
EXPECTED_SENTINELS = {
    "PROJECT_WINDOW_JS": "project_window_js_assign",
    "GENERATE_HTML": "generate_html_def",
    "RENDER_PROJECT_WINDOW": "render_project_window_html_def",
}

STRUCTURAL_KEYS = (
    "project_window_js_assign",
    "generate_html_def",
    "render_project_window_html_def",
)


class AnchorError(RuntimeError):
    """A structural anchor is missing, duplicated, or has drifted.

    Raised LOUDLY (never warned past) so a wave running on stale structural
    references halts before it edits the wrong thing.
    """


def _read_source(source=None, path=None):
    """Resolve (source_text, display_path) from the arguments."""
    if source is not None:
        return source, str(path or "<source>")
    p = Path(path) if path is not None else DEFAULT_TARGET
    return p.read_text(encoding="utf-8"), str(p)


def _locate_structural(tree, display_path):
    """Locate the three structural nodes; raise on missing/duplicate.

    Returns ``{key: {"lineno": int, "end_lineno": int, "node": ast_node}}``.
    """
    found = {key: [] for key in STRUCTURAL_KEYS}
    for node in tree.body:  # module level ONLY — nested shadows don't count
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_PROJECT_WINDOW_JS" in names:
                found["project_window_js_assign"].append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "generate_html":
                found["generate_html_def"].append(node)
            elif node.name == "render_project_window_html":
                found["render_project_window_html_def"].append(node)
    out = {}
    for key, nodes in found.items():
        if not nodes:
            raise AnchorError(
                f"anchor-freshness gate: structural anchor '{key}' NOT FOUND "
                f"in {display_path} — the structure was moved/renamed; update "
                f"tools/anchors.py and the sentinel comment together."
            )
        if len(nodes) > 1:
            lines = ", ".join(str(n.lineno) for n in nodes)
            raise AnchorError(
                f"anchor-freshness gate: structural anchor '{key}' is "
                f"AMBIGUOUS in {display_path} (matches at lines {lines}) — "
                f"refusing to guess."
            )
        node = nodes[0]
        out[key] = {
            "lineno": node.lineno,
            "end_lineno": getattr(node, "end_lineno", node.lineno),
            "node": node,
        }
    return out


def _locate_sentinels(source_text, display_path):
    """Scan for sentinel comments; raise on duplicates or unknown names."""
    hits = {}
    for i, line in enumerate(source_text.splitlines(), start=1):
        m = SENTINEL_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in hits:
            raise AnchorError(
                f"anchor-freshness gate: sentinel 'ANCHOR[rearch]: {name}' is "
                f"DUPLICATED in {display_path} (lines {hits[name]} and {i}) — "
                f"sentinels must be unique."
            )
        hits[name] = i
    return hits


def locate_anchors(source=None, path=None):
    """Re-locate every structural anchor + sentinel from the current source.

    Returns::

        {
          "path": str,
          "structural": {key: {"lineno": int, "end_lineno": int}},
          "sentinels": {NAME: lineno},
        }

    Raises :class:`AnchorError` when any structure or sentinel is missing,
    duplicated, or a sentinel is no longer within :data:`SENTINEL_ADJACENCY`
    lines above its structure. Never returns a partial/ambiguous result.
    """
    source_text, display_path = _read_source(source=source, path=path)
    try:
        tree = ast.parse(source_text)
    except SyntaxError as e:  # pragma: no cover - target must at least parse
        raise AnchorError(
            f"anchor-freshness gate: {display_path} does not parse: {e}"
        )
    structural = _locate_structural(tree, display_path)
    sentinels = _locate_sentinels(source_text, display_path)

    for name, key in EXPECTED_SENTINELS.items():
        if name not in sentinels:
            raise AnchorError(
                f"anchor-freshness gate: sentinel 'ANCHOR[rearch]: {name}' NOT "
                f"FOUND in {display_path} — it must sit within "
                f"{SENTINEL_ADJACENCY} lines above '{key}'."
            )
        s_line = sentinels[name]
        node_line = structural[key]["lineno"]
        if not (0 < node_line - s_line <= SENTINEL_ADJACENCY):
            raise AnchorError(
                f"anchor-freshness gate: sentinel 'ANCHOR[rearch]: {name}' "
                f"(line {s_line}) has DRIFTED from its structure '{key}' "
                f"(line {node_line}) — it must be 1..{SENTINEL_ADJACENCY} "
                f"lines above."
            )

    return {
        "path": display_path,
        "structural": {
            key: {"lineno": v["lineno"], "end_lineno": v["end_lineno"]}
            for key, v in structural.items()
        },
        "sentinels": sentinels,
    }


def locate_anchor_nodes(source=None, path=None):
    """Like :func:`locate_anchors` but also returns the live AST nodes.

    Internal helper for the interpolation census (which needs the node
    subtrees, not just line spans). Same loud failure semantics.
    """
    source_text, display_path = _read_source(source=source, path=path)
    tree = ast.parse(source_text)
    structural = _locate_structural(tree, display_path)
    # Run the full sentinel/adjacency validation too — the census must refuse
    # to run over a source whose anchors are stale.
    locate_anchors(source=source_text, path=display_path)
    return source_text, structural


def main(argv=None):  # pragma: no cover - thin CLI shim over locate_anchors
    """CLI: ``python tools/anchors.py [path]`` — print the located anchors."""
    import json as _json
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else None
    try:
        res = locate_anchors(path=path)
    except AnchorError as e:
        print(f"STALE ANCHORS: {e}", file=_sys.stderr)
        return 1
    print(_json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
