"""The STATUS overlay (steward-chamber W9, C2/C9/C11).

John's "most recent status update + what's left and how long", exactly as
drawn in the SIGNED ``mockups.html`` §overlays left frame — never a raw
terminal:

* **Latest status table** — the running step's captured ⏱/[HH:MM] block from
  the run_pulse data core (the W7 wire — ``chamber_pulse``), rendered in the
  drawn ``ttable``; a run with no emission yet gets the honest
  AG-PRE-EMISSION wording; an idle campaign says so. Never fabricated.
* **Remaining flow with median ETAs** — every not-done rail step with its
  ``chamber_eta`` row: the labeled basis at n>=3 (``est ~45m (median of 4
  runs)``), the DRAWN zero-history text below it (AG-ZERO-HISTORY-ETA) —
  never a one-record extrapolation; the campaign total line is
  ``chamber_eta.campaign_eta``'s own honestly-labeled text.
* **The ◇ deliverable row** — rides only when the manifest declares a
  deliverable: ``landed ✓`` when it landed, an honest duration-from-now
  phrase from the per-skill medians when estimable, the drawn gathering
  text otherwise (deterministic: durations, never the wall clock).

Structure is copied VERBATIM from the signed §overlays markup
(page > dock > dbar/ttable/rows) and DOM/class-diffed against the
hash-pinned spec by the C9 kill gate (``chamber_mockup_diff`` — the W9
extension of the W6/W7 diff). Slot values are escaped; structure is never
invented. Read-free pure render over the ``chamber_rail.seal_rail_view``
data (the bounded W6/W7 open) — no IO, no spawn, no model, no write.

This module is ALSO the OWNER FILE for
``chamber/tile-affordance-inventory.json`` — the C11 tile-affordance
functional inventory + parity map (every bottom run-tile capability →
a live rail/STATUS equivalent or a proposed accepted loss). The plan makes
STATUS incomplete without that map, so the overlay owns it:
:func:`load_tile_affordance_inventory` / :func:`tile_affordance_problems`
are its CI gate (living-registry law — a stale source marker, a dead
equivalent marker, or an undecided row each FAIL by name). W12 tile
retirement may only execute against this map once John SIGNS it
(``signed_by_john``); it lands here UNSIGNED. These owner functions are
CI-facing artifact reads — the overlay RENDER above stays read-free.

Stdlib only.
"""
from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path

import chamber_eta as ce

SCHEMA = "anchor-chamber-status-overlay-v1"

#: Drawn text pieces (mockups.html §overlays, left frame).
LATEST_LABEL = "⏱ Latest status update"
REMAINING_LABEL = "Remaining flow"

#: Honest no-data faces (never fabricated tables).
IDLE_TABLE_TEXT = ("— idle · no run in flight\nnothing is emitting status "
                   "right now")
WARMING_TABLE_TEXT = ("⏱ warming up — started %s\nno status emitted yet · "
                      "first ⏱ update lands within 10m")

_TIME_RE = re.compile(r"(?:\[|⏱\s*)(\d{2}:\d{2})")


def _esc(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _block_time(block) -> str | None:
    """The HH:MM the status block itself carries (deterministic — parsed
    from the captured text, never the wall clock)."""
    if not block:
        return None
    m = _TIME_RE.search(str(block))
    return m.group(1) if m else None


# ═════════════════════════════════════════════════════════════════════════════
# The overlay view (pure shaping over the seal_rail_view data)
# ═════════════════════════════════════════════════════════════════════════════

def overlay_view(view: dict) -> dict:
    """Shape the STATUS overlay's data from a ``seal_rail_view`` result.
    Pure + deterministic: two calls over the same view compare equal."""
    live = view.get("live_run") or {}
    slot = view.get("pulse_slot") or {}
    steps = view.get("steps") or []
    eta = view.get("eta") or {}
    per_step = eta.get("per_step") or {}
    campaign = eta.get("campaign") or {}

    running_step = None
    for s in steps:
        if s.get("running") or (live and live.get("step_id") == s.get("id")):
            running_step = s
            break

    if slot.get("status_block"):
        table = slot["status_block"]
        table_state = "status"
    elif live:
        table = WARMING_TABLE_TEXT % (live.get("at") or "unknown time")
        table_state = "pre-emission"
    else:
        table = IDLE_TABLE_TEXT
        table_state = "idle"

    rows = []
    for s in steps:
        if s.get("status") == "done":
            continue
        is_running = running_step is not None and s is running_step
        eta_row = per_step.get(s.get("id"))
        rows.append({
            "marker": "▶" if is_running else "○",
            "name": s.get("name") or s.get("id") or "a step",
            "skill": s.get("skill"),
            "running": is_running,
            "eta": eta_row,
        })

    deliverable = None
    d = view.get("deliverable")
    if d:
        if d.get("landed") or (d.get("action") or {}).get("landed"):
            when = "landed ✓"
        elif campaign.get("state") == ce.STATE_OK:
            when = "≈ %s from now (%s)" % (
                ce.format_duration(campaign.get("total_s")),
                campaign.get("basis") or "per-skill medians")
        else:
            when = "est — gathering history"
        deliverable = {"when": when,
                       "description": d.get("description")}

    title_small = "· campaign"
    if running_step is not None:
        title_small = "· %s (%s)" % (
            running_step.get("name") or running_step.get("id") or "a step",
            running_step.get("skill") or "no skill bound")

    return {
        "schema": SCHEMA,
        "title_small": title_small,
        "table": table,
        "table_state": table_state,
        "table_time": _block_time(table if table_state == "status" else None),
        "remaining_label": campaign.get("label") or "",
        "rows": rows,
        "deliverable": deliverable,
        "degraded": bool(view.get("degraded")),
    }


# ═════════════════════════════════════════════════════════════════════════════
# The render (mockups.html §overlays left frame, verbatim structure)
# ═════════════════════════════════════════════════════════════════════════════

def _row_suffix(row: dict) -> str:
    """The grey suffix text for one remaining-flow row — the labeled ETA at
    n>=3, the DRAWN zero-history text below it, the drawn no-skill chip text
    when no skill resolves. Never an unlabeled number."""
    bits = []
    if row.get("running"):
        bits.append("finishing")
    skill = row.get("skill")
    bits.append(skill if skill else "no skill bound")
    eta_row = row.get("eta")
    if eta_row is not None:
        bits.append(eta_row["label"])
    return "· " + " · ".join(bits)


def render_status_overlay_html(view: dict) -> str:
    """The painted STATUS overlay: verbatim §overlays structure over
    :func:`overlay_view` data. Pure string render — no IO, no spawn, no
    model, no write; every slot value escaped."""
    ov = overlay_view(view)
    label = LATEST_LABEL
    if ov.get("table_time"):
        label += " · %s" % ov["table_time"]
    remaining = REMAINING_LABEL
    if ov.get("remaining_label"):
        remaining += " · %s" % ov["remaining_label"]

    rows_html = []
    for row in ov["rows"]:
        rows_html.append(
            '<div>%s %s <span style="color:var(--text-dim)">%s</span></div>'
            % (_esc(row["marker"]), _esc(row["name"]),
               _esc(_row_suffix(row))))
    d = ov.get("deliverable")
    if d:
        rows_html.append(
            '<div>◇ Deliverable lands <span style="color:var(--gold)">%s'
            '</span></div>' % _esc(d["when"]))

    return (
        '<div class="page" style="background:rgba(0,0,0,.25)">'
        '<div class="dock" style="max-width:520px;margin:8px auto">'
        '<div class="dbar">'
        '<span class="ti">Status <small>%s</small></span>'
        '<span class="sp"></span>'
        '<button class="btn" data-overlay-close="1">×</button>'
        '</div>'
        '<div style="padding:12px 16px">'
        '<div style="font-size:10px;letter-spacing:.09em;text-transform:'
        'uppercase;color:var(--run);margin-bottom:5px">%s</div>'
        '<div class="ttable" style="border:1px solid var(--run);'
        'border-radius:8px;padding:9px 11px;background:var(--surface2)">%s'
        '</div>'
        '<div style="font-size:10px;letter-spacing:.09em;text-transform:'
        'uppercase;color:var(--text-dim);margin:12px 0 5px">%s</div>'
        '<div style="font-size:12.5px;display:flex;flex-direction:column;'
        'gap:4px">%s</div>'
        '</div>'
        '</div>'
        '</div>'
    ) % (_esc(ov["title_small"]), _esc(label), _esc(ov["table"]),
         _esc(remaining), "".join(rows_html))


#: The drawn base signatures a painted STATUS overlay MUST contain (the
#: required direction — an empty dock can never diff green). Consumed by the
#: W9 CI diff via chamber_mockup_diff.missing_required.
REQUIRED_OVERLAY = (
    ("div", ("page",)), ("div", ("dock",)), ("div", ("dbar",)),
    ("span", ("ti",)), ("small", ()), ("span", ("sp",)),
    ("button", ("btn",)), ("div", ()), ("div", ("ttable",)),
)


# ═════════════════════════════════════════════════════════════════════════════
# C11 — the tile-affordance functional inventory + parity map (owner functions)
# ═════════════════════════════════════════════════════════════════════════════

_ANCHOR_ROOT = Path(__file__).resolve().parent

TILE_AFFORDANCE_INVENTORY_PATH = (
    _ANCHOR_ROOT / "chamber" / "tile-affordance-inventory.json")

TILE_INVENTORY_SCHEMA_VERSION = 1

#: The three honest resolutions a parity row may carry. ``equivalent`` names
#: a LIVE rail/STATUS (or surviving-surface) marker that must exist in code;
#: the two ``proposed-*`` kinds carry John's decision material for the W12
#: signing — a row with none of these is an undecided row, a named failure.
PARITY_KINDS = ("equivalent", "proposed-equivalent", "proposed-loss")


def load_tile_affordance_inventory(path=None) -> dict:
    p = Path(path) if path else TILE_AFFORDANCE_INVENTORY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _marker_present(root: Path, rel_file: str, marker: str) -> str | None:
    """None when ``marker`` exists in ``rel_file`` under ``root``; else the
    named problem string."""
    p = root / rel_file
    if not p.is_file():
        return "named file does not exist: %s" % rel_file
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "named file unreadable: %s (%s)" % (rel_file, exc)
    if marker not in text:
        return "marker %r no longer present in %s" % (marker, rel_file)
    return None


def tile_affordance_problems(inv: dict | None = None,
                             root: Path | None = None) -> list:
    """The parity map's CI gate (living-registry law). Empty == green.

    Mechanically: the artifact is versioned + owned + signature-tracked;
    every row grounds its tile affordance in a SOURCE marker that still
    exists in the tile code (a vanished marker = a stale row); every
    ``equivalent`` row grounds its claim in a TARGET marker that still
    exists in the live rail/STATUS (or surviving-surface) code; every
    ``proposed-*`` row carries non-empty decision material for John's W12
    signing. Never a write, never a spawn.
    """
    inv = inv if inv is not None else load_tile_affordance_inventory()
    root = Path(root) if root else _ANCHOR_ROOT
    problems: list = []
    if not isinstance(inv, dict):
        return ["tile-affordance inventory is not a JSON object"]
    if inv.get("schema_version") != TILE_INVENTORY_SCHEMA_VERSION:
        problems.append("schema_version missing or != %d"
                        % TILE_INVENTORY_SCHEMA_VERSION)
    if inv.get("owner_file") != "chamber_status_overlay.py":
        problems.append("owner_file must name chamber_status_overlay.py "
                        "(living-registry law)")
    if "signed_by_john" not in inv:
        problems.append("signed_by_john missing — W12 retirement is gated on "
                        "this signature field (C11)")
    if "W12" not in str(inv.get("signing_law") or ""):
        problems.append("signing_law must state the W12 signed-parity "
                        "retirement gate (C11)")
    rows = inv.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append("rows missing/empty — the map must cover the tile "
                        "affordances (log links, kill control, historical "
                        "runs, raw output)")
        return problems
    seen_ids: set = set()
    for i, row in enumerate(rows):
        rid = row.get("id") or ("rows[%d]" % i)
        if row.get("id") in seen_ids:
            problems.append("%s: duplicate row id" % rid)
        seen_ids.add(row.get("id"))
        for key in ("id", "affordance", "source_file", "source_marker"):
            if not row.get(key):
                problems.append("%s: missing %s" % (rid, key))
        if row.get("source_file") and row.get("source_marker"):
            bad = _marker_present(root, row["source_file"],
                                  row["source_marker"])
            if bad:
                problems.append("%s: stale source row — %s" % (rid, bad))
        parity = row.get("parity")
        if not isinstance(parity, dict) \
                or parity.get("kind") not in PARITY_KINDS:
            problems.append(
                "%s: parity.kind must be one of %s — an undecided row "
                "cannot land (C11)" % (rid, "/".join(PARITY_KINDS)))
            continue
        if parity["kind"] == "equivalent":
            if not parity.get("target_file") or not parity.get("target_marker"):
                problems.append("%s: an equivalent claim must name "
                                "target_file + target_marker" % rid)
            else:
                bad = _marker_present(root, parity["target_file"],
                                      parity["target_marker"])
                if bad:
                    problems.append("%s: dead equivalent claim — %s"
                                    % (rid, bad))
        else:
            if not str(parity.get("note") or "").strip():
                problems.append("%s: a %s row must carry its decision "
                                "material (non-empty note) for the W12 "
                                "signing" % (rid, parity["kind"]))
    return problems
