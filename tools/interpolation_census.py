"""Interpolation census for the C1 frontend extraction (W1).

Replaces hope with mechanical evidence before the extraction waves are sized:

* classifies EVERY ``{…}`` f-string interpolation inside ``generate_html`` and
  ``render_project_window_html`` (their full subtrees, nested row-builders
  included) as **data** / **flag** / **markup-emitting**, with counts;
* asserts ``_PROJECT_WINDOW_JS`` carries ZERO interpolations (it must stay a
  plain raw string — the moment someone turns it into an f-string the census
  fails loudly);
* derives the ACTUAL shrink number the extraction can claim (the merged line
  spans of the big static string blobs, not a narrated estimate);
* decides whether the C1 amendment must be raised NOW: markup-emitting
  interpolations above :data:`MARKUP_EMITTING_THRESHOLD` force an include
  layer (they cannot ride a JSON bootstrap), and a derived shrink below
  :data:`SHRINK_BAR_LINES` means the ≥7,000-line success bar needs amending.

Classification is PURELY SYNTACTIC (documented rules below), so the census is
deterministic for a given source — reviewable, re-runnable, and honest about
being a heuristic. Precedence: markup-emitting > flag > data.

* **markup-emitting** — the interpolated expression manufactures or carries
  HTML/JS structure: any string literal inside it contains ``<``; OR it calls
  a renderer (name starting ``render``/``_render`` or ending in a markup
  suffix like ``_html``/``_rows``/``_script``); OR it references a variable
  named with a markup suffix. These are the interpolations that cannot move
  to a static file + ``ANCHOR_BOOT`` JSON — each one needs a server-side
  include or a client-side template.
* **flag** — a conditional/boolean selection between plain literals (ternary
  ``IfExp``, ``Compare``/``BoolOp``, or a variable named with a flag suffix
  such as ``_class``/``_display``/``_js``): rides trivially through
  ``ANCHOR_BOOT`` as a boolean/string.
* **data** — everything else (escaped values, counts, ids, formatted
  numbers): rides through ``ANCHOR_BOOT`` as data.

Anchors come from :mod:`tools.anchors` — the census REFUSES to run over a
source whose structural anchors are stale/ambiguous (AnchorError propagates).

Stdlib only. CLI: ``python tools/interpolation_census.py [--write DIR]``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from tools.anchors import REPO_ROOT, locate_anchor_nodes

# The C1 success bar from the locked North Star: anchor_gui.py shrinks by
# ≥ 7,000 lines. The census derives the actual extractable-line number; a
# derivation below this bar raises the amendment NOW, not at W6.
SHRINK_BAR_LINES = 7000

# "The small threshold" for markup-emitting interpolations (plan W1): above
# this, per-fragment includes stop being a footnote and C1 needs the amended
# include-layer design up front.
MARKUP_EMITTING_THRESHOLD = 40

# A merged string-literal span must be at least this many lines to count as an
# extractable static blob. Scattered short f-string fragments (row builders)
# stay server-side and honestly do NOT count toward the shrink number.
BLOB_MIN_LINES = 20

CLASS_DATA = "data"
CLASS_FLAG = "flag"
CLASS_MARKUP = "markup-emitting"
CLASSES = (CLASS_DATA, CLASS_FLAG, CLASS_MARKUP)

# Syntactic markers (documented above; keep these lists reviewed, not clever).
MARKUP_NAME_SUFFIXES = (
    "_html", "_rows", "_row", "_card", "_cards", "_banner", "_btn",
    "_buttons", "_popover", "_badge", "_chip", "_chips", "_panel", "_tile",
    "_tiles", "_section", "_sections", "_svg", "_lockup", "_script",
    "_markup", "_attr",
)
MARKUP_NAME_PREFIXES = ("render", "_render")
FLAG_NAME_SUFFIXES = (
    "_class", "_display", "_js", "_flag", "_checked", "_disabled",
    "_selected", "_state", "_open",
)

# Default artifact directory for the checked-in gate artifacts.
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"
REPORT_JSON_NAME = "CENSUS-REPORT.json"
REPORT_MD_NAME = "CENSUS-REPORT.md"
AMENDMENT_NAME = "C1-AMENDMENT-REQUIRED.md"


class CensusError(RuntimeError):
    """The census hit a structural violation (e.g. an f-string
    ``_PROJECT_WINDOW_JS``) it must not paper over."""


def _name_of_callee(call):
    """Best-effort dotted-tail name of a Call's callee ('' when opaque)."""
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _matches_markup_name(name):
    low = name.lower()
    return low.startswith(MARKUP_NAME_PREFIXES) or low.endswith(
        MARKUP_NAME_SUFFIXES
    )


def _matches_flag_name(name):
    return name.lower().endswith(FLAG_NAME_SUFFIXES)


def classify_expression(expr):
    """Classify one interpolated expression node → (class, rule).

    Mechanical, precedence markup > flag > data; the fired rule is returned
    so the report is auditable.
    """
    has_ifexp = False
    has_boolish = False
    flag_name = None
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "<" in node.value:
                return CLASS_MARKUP, "literal-contains-<"
        elif isinstance(node, ast.Call):
            callee = _name_of_callee(node)
            if callee and _matches_markup_name(callee):
                return CLASS_MARKUP, f"call-to-renderer:{callee}"
        elif isinstance(node, ast.Name):
            if _matches_markup_name(node.id):
                return CLASS_MARKUP, f"markup-named-var:{node.id}"
            if flag_name is None and _matches_flag_name(node.id):
                flag_name = node.id
        elif isinstance(node, ast.IfExp):
            has_ifexp = True
        elif isinstance(node, (ast.Compare, ast.BoolOp)):
            has_boolish = True
    if has_ifexp:
        return CLASS_FLAG, "ternary-selection"
    if has_boolish:
        return CLASS_FLAG, "boolean-expression"
    if flag_name is not None:
        return CLASS_FLAG, f"flag-named-var:{flag_name}"
    return CLASS_DATA, "default-data"


def _census_function(func_node, source_text):
    """Classify every FormattedValue in the function's full subtree."""
    records = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.FormattedValue):
            continue
        cls, rule = classify_expression(node.value)
        try:
            snippet = ast.get_source_segment(source_text, node.value) or ""
        except Exception:
            snippet = ""
        snippet = " ".join(snippet.split())
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        records.append({
            "function": func_node.name,
            "lineno": node.lineno,
            "class": cls,
            "rule": rule,
            "expr": snippet,
        })
    records.sort(key=lambda r: (r["lineno"], r["expr"]))
    return records


def _merged_blob_intervals(func_node):
    """Merged (start, end) line intervals of string literals ≥ BLOB_MIN_LINES.

    Collects every string-literal node (``JoinedStr`` f-strings and plain
    ``Constant`` strings) in the subtree, merges overlapping/contained
    intervals (a Constant inside a JoinedStr never double-counts), and keeps
    only merged blobs spanning at least :data:`BLOB_MIN_LINES` lines — the
    contiguous static blobs the extraction can actually move.
    """
    intervals = []
    for node in ast.walk(func_node):
        is_str = isinstance(node, ast.JoinedStr) or (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        if not is_str:
            continue
        end = getattr(node, "end_lineno", None)
        if end is None:  # pragma: no cover - 3.8+ always sets end_lineno
            continue
        intervals.append((node.lineno, end))
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        (s, e) for s, e in merged if (e - s + 1) >= BLOB_MIN_LINES
    ]


def run_census(source=None, path=None):
    """Run the full census. Returns the result dict (see report writers).

    Raises :class:`tools.anchors.AnchorError` on stale anchors and
    :class:`CensusError` if ``_PROJECT_WINDOW_JS`` is no longer a plain
    zero-interpolation string constant.
    """
    source_text, structural = locate_anchor_nodes(source=source, path=path)

    # ── _PROJECT_WINDOW_JS: must be a plain constant string (0 interpolations)
    js_assign = structural["project_window_js_assign"]["node"]
    js_value = js_assign.value
    if isinstance(js_value, ast.JoinedStr):
        n_interp = sum(
            1 for n in ast.walk(js_value)
            if isinstance(n, ast.FormattedValue)
        )
        raise CensusError(
            f"_PROJECT_WINDOW_JS is an f-string with {n_interp} "
            f"interpolation(s) — the census contract requires ZERO (plain raw "
            f"string). The C1 increment-1 verbatim move is no longer safe."
        )
    elif isinstance(js_value, ast.Constant) and isinstance(js_value.value, str):
        pass  # pre-extraction: a plain zero-interpolation raw string (still valid)
    elif isinstance(js_value, ast.Call):
        pass  # C1 (2026-07-05): EXTRACTED — the constant now loads its verbatim,
        # byte-identical body from static/ via ``read_text()``. This is the
        # terminal-OK extracted form; there is no in-source blob left to certify.
    else:
        raise CensusError(
            "_PROJECT_WINDOW_JS is neither a plain string constant nor an "
            "extraction read_text() load — the census cannot classify it."
        )
    js_span = (js_assign.lineno, js_assign.end_lineno)
    js_lines = js_span[1] - js_span[0] + 1

    # ── classify the two render surfaces
    functions = {}
    blob_spans = {"_PROJECT_WINDOW_JS": [js_span]}
    shrink = js_lines
    for key in ("generate_html_def", "render_project_window_html_def"):
        func_node = structural[key]["node"]
        records = _census_function(func_node, source_text)
        counts = {cls: 0 for cls in CLASSES}
        for r in records:
            counts[r["class"]] += 1
        blobs = _merged_blob_intervals(func_node)
        shrink += sum(e - s + 1 for s, e in blobs)
        blob_spans[func_node.name] = blobs
        functions[func_node.name] = {
            "total": len(records),
            "counts": counts,
            "interpolations": records,
        }

    markup_total = sum(
        f["counts"][CLASS_MARKUP] for f in functions.values()
    )
    flag_total = sum(f["counts"][CLASS_FLAG] for f in functions.values())
    data_total = sum(f["counts"][CLASS_DATA] for f in functions.values())

    # ── amendment decision (raised NOW, per the W1 deliverable)
    reasons = []
    if markup_total > MARKUP_EMITTING_THRESHOLD:
        reasons.append(
            f"markup-emitting interpolations = {markup_total} > threshold "
            f"{MARKUP_EMITTING_THRESHOLD}: C1 needs the include-layer design "
            f"amended in up front (they cannot ride the ANCHOR_BOOT JSON)."
        )
    if shrink < SHRINK_BAR_LINES:
        reasons.append(
            f"derived shrink = {shrink} lines < the locked ≥"
            f"{SHRINK_BAR_LINES}-line bar: the C1 success bar needs amending."
        )

    if path is not None:
        target = str(path)
    elif source is None:
        target = "anchor_gui.py"
    else:
        target = "<source>"
    return {
        "target": target,
        "project_window_js": {
            "interpolations": 0,
            "span": list(js_span),
            "lines": js_lines,
        },
        "functions": functions,
        "totals": {
            CLASS_DATA: data_total,
            CLASS_FLAG: flag_total,
            CLASS_MARKUP: markup_total,
            "all": data_total + flag_total + markup_total,
        },
        "blob_min_lines": BLOB_MIN_LINES,
        "blob_spans": {
            name: [list(s) for s in spans]
            for name, spans in blob_spans.items()
        },
        "derived_shrink_lines": shrink,
        "shrink_bar_lines": SHRINK_BAR_LINES,
        "markup_emitting_threshold": MARKUP_EMITTING_THRESHOLD,
        "amendment_required": bool(reasons),
        "amendment_reasons": reasons,
    }


# ── report writers ──────────────────────────────────────────────────────────

def render_report_md(result):
    """Render the census result as the human-readable gate artifact."""
    lines = [
        "# C1 Interpolation Census — gate artifact (W1)",
        "",
        "Mechanically generated by `tools/interpolation_census.py` — do not",
        "hand-edit; re-run the census (the W1 gate test refreshes it).",
        "",
        f"- `_PROJECT_WINDOW_JS`: **0 interpolations** (plain raw string), "
        f"span {result['project_window_js']['span'][0]}–"
        f"{result['project_window_js']['span'][1]} "
        f"({result['project_window_js']['lines']} lines)",
        f"- Derived shrink number: **{result['derived_shrink_lines']} lines** "
        f"(bar: ≥{result['shrink_bar_lines']})",
        f"- Markup-emitting total: **{result['totals'][CLASS_MARKUP]}** "
        f"(threshold: {result['markup_emitting_threshold']})",
        f"- Amendment required NOW: "
        f"**{'YES' if result['amendment_required'] else 'no'}**",
        "",
        "| function | data | flag | markup-emitting | total |",
        "|---|---|---|---|---|",
    ]
    for name, f in sorted(result["functions"].items()):
        c = f["counts"]
        lines.append(
            f"| `{name}` | {c[CLASS_DATA]} | {c[CLASS_FLAG]} | "
            f"{c[CLASS_MARKUP]} | {f['total']} |"
        )
    t = result["totals"]
    lines.append(
        f"| **total** | {t[CLASS_DATA]} | {t[CLASS_FLAG]} | "
        f"{t[CLASS_MARKUP]} | {t['all']} |"
    )
    lines += [
        "",
        f"## Extractable blobs (merged string spans ≥ "
        f"{result['blob_min_lines']} lines)",
        "",
    ]
    for name, spans in sorted(result["blob_spans"].items()):
        for s, e in spans:
            lines.append(f"- `{name}`: lines {s}–{e} ({e - s + 1} lines)")
    if result["amendment_reasons"]:
        lines += ["", "## Amendment reasons", ""]
        lines += [f"- {r}" for r in result["amendment_reasons"]]
    lines += [
        "",
        "## Markup-emitting interpolations (each needs an include/template, "
        "not ANCHOR_BOOT)",
        "",
    ]
    for name, f in sorted(result["functions"].items()):
        for r in f["interpolations"]:
            if r["class"] == CLASS_MARKUP:
                lines.append(
                    f"- `{name}` L{r['lineno']} [{r['rule']}]: "
                    f"`{{{r['expr']}}}`"
                )
    lines.append("")
    return "\n".join(lines)


def render_amendment_md(result):
    """Render the C1 amendment proposal raised via the North-Star path."""
    lines = [
        "# C1 AMENDMENT REQUIRED — raised by the W1 interpolation census",
        "",
        "The W1 census found ground truth that forces a C1 amendment via the",
        "North-Star amendment path (John approves; never silent):",
        "",
    ]
    lines += [f"- {r}" for r in result["amendment_reasons"]]
    lines += [
        "",
        f"Census numbers: derived shrink = {result['derived_shrink_lines']} "
        f"lines (bar ≥{result['shrink_bar_lines']}); markup-emitting = "
        f"{result['totals'][CLASS_MARKUP]} "
        f"(threshold {result['markup_emitting_threshold']}).",
        "",
        "This file is generated by `tools/interpolation_census.py` and exists",
        "ONLY while the census says an amendment is required.",
        "",
    ]
    return "\n".join(lines)


def write_report(result, out_dir=None):
    """Write the checked-in gate artifacts; returns the paths written.

    Writes ``CENSUS-REPORT.json`` + ``CENSUS-REPORT.md`` always, and
    ``C1-AMENDMENT-REQUIRED.md`` iff the census requires the amendment
    (removing a stale one otherwise, so the artifact set can never lie).
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / REPORT_JSON_NAME
    md_path = out / REPORT_MD_NAME
    amend_path = out / AMENDMENT_NAME

    payload = dict(result)
    payload["functions"] = {
        name: {k: v for k, v in f.items()}
        for name, f in result["functions"].items()
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_report_md(result), encoding="utf-8")

    written = [json_path, md_path]
    if result["amendment_required"]:
        amend_path.write_text(render_amendment_md(result), encoding="utf-8")
        written.append(amend_path)
    elif amend_path.exists():
        amend_path.unlink()
    return written


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse
    import sys as _sys

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=None,
                    help="target source file (default: anchor_gui.py)")
    ap.add_argument("--write", metavar="DIR", default=None,
                    help="also write the gate artifacts into DIR "
                         f"(default artifact dir: {DEFAULT_ARTIFACT_DIR})")
    args = ap.parse_args(argv)
    result = run_census(path=args.path)
    if args.write is not None:
        for p in write_report(result, out_dir=args.write or None):
            print(f"wrote {p}")
    print(render_report_md(result))
    return 1 if result["amendment_required"] else 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
