"""Mechanical extraction map for the home-dashboard C1 cut (W6a).

Mirrors the proven :mod:`tools.extract_project_window_js` idiom, one level up:
where W4 moved a single zero-interpolation raw string, the home dashboard's
``generate_html`` carries markup-emitting interpolations that must stay
server-rendered behind the W6a include-slot substrate. This module produces
the **machine-readable extraction map W6b executes** — it does NOT edit
``anchor_gui.py`` (W6a is mechanism-only).

Driven entirely by the W1 interpolation census (``tools.interpolation_census``
— stale anchors and an f-string ``_PROJECT_WINDOW_JS`` propagate their loud
failures), the map:

* inventories ``generate_html``'s (and the project window's) extractable
  JS/CSS blobs — the merged static string spans the extraction moves;
* maps EVERY census-classified markup-emitting interpolation to a NAMED slot
  and its source helper, partitioned by function, with a per-occurrence slot
  name (``<function>_L<lineno>_<k>``) that is unique and deterministic;
* proves completeness — the map accounts for ALL 48 markup interpolations the
  census/amendment found, with zero unclassified remainder
  (:func:`verify_map` raises :class:`ExtractionMapError` otherwise).

Each markup interpolation is one of exactly three census rules → a slot
``kind``:

* ``markup-named-var:<v>``  → ``named-var``     (helper = the ``<v>`` symbol)
* ``call-to-renderer:<f>``  → ``renderer-call`` (helper = the ``<f>`` callee)
* ``literal-contains-<``    → ``inline-literal``(helper = the unique slot name)

Repeated helpers (e.g. ``notes_html`` on three rows, ``project_card`` on four)
are grouped so W6b writes ONE helper per source symbol while every call-site
gets its own slot. The 48-count matches the amendment
(``C1-AMENDMENT-REQUIRED.md``); a census drift that changes it fails the gate
loudly rather than silently re-baselining.

Stdlib only (``json``, ``pathlib`` + the census). CLI:
``python tools/extract_dashboard.py [path] [--write DIR] [--check]``.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.interpolation_census import (
    CLASS_MARKUP,
    DEFAULT_ARTIFACT_DIR,
    run_census,
)

# The markup surfaces the home-dashboard extraction map covers. The project
# window is included so the map is the complete census-markup partition (the
# amendment's 48 span both render functions); W6b consumes the
# ``generate_html`` slice, W5 the project-window slice.
RENDER_FUNCTIONS = ("generate_html", "render_project_window_html")

# The amendment's ground-truth markup count (C1-AMENDMENT-REQUIRED.md). The map
# must account for exactly this many; a census that drifts off it fails loudly.
# 47 as of 2026-07-30: the v1.2 freelance layout/language pass (db70e86)
# removed one markup-emitting interpolation; re-pinned to census ground
# truth during the steward-livery hardening (was 48).
# 50 as of 2026-09-03: the r3 home — the steward's rail replaced the
# Views/Domains/Domain-balance nav (nav_items, balance_rows gone) and added
# the rail, the needs-attention rows, the Calendar/Email tiles and the
# Tasks-tile links (all *_html); John's look then folded the Steward pick
# into the model-prefs control (one interpolation, not two). Census ground
# truth: 50.
MARKUP_AMENDMENT_COUNT = 50

MAP_JSON_NAME = "EXTRACTION-MAP.json"
MAP_MD_NAME = "EXTRACTION-MAP.md"

KIND_NAMED_VAR = "named-var"
KIND_RENDERER = "renderer-call"
KIND_INLINE = "inline-literal"
KIND_UNCLASSIFIED = "unclassified"


class ExtractionMapError(RuntimeError):
    """The extraction map is not provably complete — an unclassified markup
    record, or an accounted-count that disagrees with the census total. Raised
    loudly so a drifted map never silently under-covers the extraction."""


def _classify_markup_rule(rule):
    """(kind, source-symbol|None) for a census markup rule string."""
    if rule.startswith("markup-named-var:"):
        return KIND_NAMED_VAR, rule.split(":", 1)[1]
    if rule.startswith("call-to-renderer:"):
        return KIND_RENDERER, rule.split(":", 1)[1]
    if rule == "literal-contains-<":
        return KIND_INLINE, None
    return KIND_UNCLASSIFIED, None


def build_extraction_map(source=None, path=None):
    """Build the extraction map from the census. Returns the map dict.

    Propagates :class:`tools.anchors.AnchorError` / the census
    ``CensusError`` (stale anchors, f-string ``_PROJECT_WINDOW_JS``). The map
    is verified complete before return (:func:`verify_map`).
    """
    census = run_census(source=source, path=path)

    slots = []
    helpers = {}
    per_line = {}
    by_function = {}
    for fname in RENDER_FUNCTIONS:
        fdata = census["functions"].get(fname)
        if fdata is None:
            continue
        n_markup = 0
        for rec in fdata["interpolations"]:
            if rec["class"] != CLASS_MARKUP:
                continue
            n_markup += 1
            kind, symbol = _classify_markup_rule(rec["rule"])
            key = (fname, rec["lineno"])
            k = per_line.get(key, 0)
            per_line[key] = k + 1
            slot = f"{fname}_L{rec['lineno']}_{k}"
            helper = symbol if symbol else slot
            slots.append({
                "slot": slot,
                "function": fname,
                "lineno": rec["lineno"],
                "rule": rec["rule"],
                "kind": kind,
                "helper": helper,
                "expr": rec["expr"],
            })
            hgroup = helpers.setdefault(
                helper, {"kind": kind, "occurrences": 0, "slots": []})
            hgroup["occurrences"] += 1
            hgroup["slots"].append(slot)
        by_function[fname] = n_markup

    blobs = {
        name: [list(s) for s in census["blob_spans"].get(name, [])]
        for name in RENDER_FUNCTIONS
    }

    unclassified = [s for s in slots if s["kind"] == KIND_UNCLASSIFIED]
    result = {
        "target": census["target"],
        "markup_emitting_total": census["totals"][CLASS_MARKUP],
        "amendment_count": MARKUP_AMENDMENT_COUNT,
        "accounted": len(slots),
        "unclassified": unclassified,
        "by_function": by_function,
        "blobs": blobs,
        "helpers": helpers,
        "slots": slots,
    }
    verify_map(result)
    return result


def verify_map(result):
    """Raise :class:`ExtractionMapError` unless the map is provably complete.

    Complete ⇔ zero unclassified markup records AND the accounted slot count
    equals both the census markup total and the number of grouped-helper
    occurrences (no double-count / drop). Returns ``result`` on success.
    """
    if result["unclassified"]:
        sites = ", ".join(
            f"{s['function']} L{s['lineno']}" for s in result["unclassified"])
        raise ExtractionMapError(
            f"extraction map has {len(result['unclassified'])} UNCLASSIFIED "
            f"markup interpolation(s) — no named helper derived for: {sites}"
        )
    total = result["markup_emitting_total"]
    if result["accounted"] != total:
        raise ExtractionMapError(
            f"extraction map accounts for {result['accounted']} markup "
            f"interpolation(s) but the census found {total} — the map does "
            f"not cover the full markup set."
        )
    grouped = sum(h["occurrences"] for h in result["helpers"].values())
    if grouped != total:
        raise ExtractionMapError(
            f"grouped-helper occurrences ({grouped}) disagree with the "
            f"census markup total ({total}) — a slot was dropped or "
            f"double-counted."
        )
    return result


# ── artifact writers ─────────────────────────────────────────────────────────

def render_map_md(result):
    """Render the extraction map as the human-readable gate artifact."""
    lines = [
        "# Home-dashboard extraction map — gate artifact (W6a)",
        "",
        "Mechanically generated by `tools/extract_dashboard.py` from the W1",
        "interpolation census — do not hand-edit; re-run the extractor (the",
        "W6a gate refreshes it). W6b executes this map; W6a does NOT modify",
        "`anchor_gui.py`.",
        "",
        f"- Markup-emitting interpolations accounted: "
        f"**{result['accounted']}** / census {result['markup_emitting_total']} "
        f"(amendment {result['amendment_count']})",
        f"- Unclassified remainder: **{len(result['unclassified'])}** "
        f"(must be 0)",
        f"- Distinct helpers: **{len(result['helpers'])}**",
        "",
        "| function | markup slots |",
        "|---|---|",
    ]
    for name in RENDER_FUNCTIONS:
        if name in result["by_function"]:
            lines.append(f"| `{name}` | {result['by_function'][name]} |")
    lines += ["", "## Extractable JS/CSS blobs (merged static spans)", ""]
    for name in RENDER_FUNCTIONS:
        for s, e in result["blobs"].get(name, []):
            lines.append(f"- `{name}`: lines {s}–{e} ({e - s + 1} lines)")
    lines += ["", "## Named helpers (source symbol → slot occurrences)", ""]
    for helper in sorted(result["helpers"]):
        h = result["helpers"][helper]
        lines.append(
            f"- `{helper}` [{h['kind']}] × {h['occurrences']}: "
            + ", ".join(f"`{s}`" for s in h["slots"])
        )
    lines += ["", "## Slots (one per markup interpolation)", ""]
    for s in result["slots"]:
        lines.append(
            f"- `{s['slot']}` ← `{s['helper']}` [{s['kind']}] "
            f"({s['function']} L{s['lineno']}): `{{{s['expr']}}}`"
        )
    lines.append("")
    return "\n".join(lines)


def write_map(result, out_dir=None):
    """Write the checked-in map artifacts (JSON + MD); returns the paths.

    Mechanical artifact, like the census reports: refreshed by the gate run,
    never hand-edited; an unchanged rewrite still rewrites (JSON is small).
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / MAP_JSON_NAME
    md_path = out / MAP_MD_NAME
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_map_md(result), encoding="utf-8")
    return [json_path, md_path]


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse
    import sys as _sys

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=None,
                    help="target source file (default: anchor_gui.py)")
    ap.add_argument("--write", metavar="DIR", default=None,
                    help="write the map artifacts into DIR "
                         f"(default: {DEFAULT_ARTIFACT_DIR})")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the map is not provably complete")
    args = ap.parse_args(argv)
    try:
        result = build_extraction_map(path=args.path)
    except ExtractionMapError as e:
        print(f"INCOMPLETE MAP: {e}", file=_sys.stderr)
        return 1
    if args.write is not None:
        for p in write_map(result, out_dir=args.write or None):
            print(f"wrote {p}")
    if args.check:
        print(f"OK: extraction map covers {result['accounted']}/"
              f"{result['markup_emitting_total']} markup interpolations")
        return 0
    print(render_map_md(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
