"""Bounded Seal-open read path + verbatim M1 slice render (steward-chamber W6).

This module IS the 2-second open: everything the painted vertical-slice M1
Seal needs, derived in ONE deterministic, bounded read pass over the W4/W5
projections — and nothing else. The C1 law it implements:

* **Zero model calls, zero spawns** — no subprocess import exists in this
  module; nothing here touches a network socket, a PTY, or a model CLI. The
  W6 CI trace + process-spawn audit assert this on the painted Seal on every
  chamber change.
* **Zero writes** — readers never write, never "repair", never rebuild
  inline. The FIRST open after a deploy (sidecar absent or schema-stale)
  paints the DRAWN degraded-rail state (AG-DEGRADED-RAIL, signed 2026-08-10)
  and SURFACES the W5 cold-open rebuild affordance; an inline rebuild on the
  open path is a test failure by plan.
* **Structural read-path fixes, before any cache** (the plan's words):

  - **Ledger tail-read from the last snapshot line.** ``roadmap.json`` is an
    event ledger that carries its own snapshot: ``roadmap_projection`` (the
    single writer maintains it to ``as_of``, the last event's instant). The
    open path takes step state FROM THE SNAPSHOT and scans ``roadmap_events``
    in REVERSE, stopping at the first event at-or-before ``as_of`` — so the
    events processed per open are the tail since the snapshot (normally
    zero), never a full-history replay. ``read_stats`` records the honest
    numbers so CI can prove the bound at months-scale.
  - **Run-record reads capped to active scaffold steps.** The open never
    reads every ``.anchor/commission-runs/*.json``: the projection store's
    events are the citation index — only records cited for ACTIVE (not-done)
    steps are read, under a HARD numeric backstop of
    :data:`RUN_RECORD_READ_CAP` (200) reads per open. Exceeding the cap is a
    REFUSAL into the drawn degraded-rail state — never an unbounded read.
  - **No cache.** Any cache would require an explicit John-classified
    rebuildable-cache decision (plan, W6). None is smuggled in here: every
    open derives from the sidecar + ledger bytes on disk.

The renderer (:func:`render_seal_slice_html`) is the thin VERBATIM-markup
shell: its DOM/class structure is copied from the SIGNED amended
``mockups.html`` (§M1 + the signed amendment states) and mechanically
DOM/class-diffed against that hash-pinned spec by the C9 kill gate
(``chamber_mockup_diff``), which co-lands with this first painted markup.
Slot values are HTML-escaped; structure is never invented.

Stdlib only.
"""
from __future__ import annotations

import html as _html
import json
import time
from pathlib import Path

import chamber_brownfield as cb
import chamber_manifest as cm
import chamber_projections as _cp
import chamber_reconcile as cr

SCHEMA = "anchor-chamber-seal-open-v1"

#: The hard numeric backstop on run-record file reads per open (plan, W6:
#: "a hard numeric backstop of 200 reads per open and a refusal path").
RUN_RECORD_READ_CAP = 200

#: The drawn degraded state every refusal maps to (signed W1 amendment batch).
DEGRADED_RAIL_STATE = cb.DEGRADED_RAIL_STATE          # "degraded-rail"
DEGRADED_AMENDMENT_REF = cb.DEGRADED_AMENDMENT_REF    # "AG-DEGRADED-RAIL"

# ── Named degraded reasons (never a shrug) ──────────────────────────────────
REASON_PROJECTIONS_MISSING = "projections-missing"
REASON_PROJECTIONS_UNREADABLE = "projections-unreadable"
REASON_PROJECTIONS_SCHEMA_STALE = "projections-schema-stale"
REASON_BRIEF_MISSING = "brief-missing"
REASON_BRIEF_UNREADABLE = "brief-unreadable"
REASON_BRIEF_SCHEMA_STALE = "brief-schema-stale"
REASON_MANIFEST_MISSING = "manifest-missing"
REASON_MANIFEST_UNREADABLE = "manifest-unreadable"
REASON_MANIFEST_SCHEMA_STALE = "manifest-schema-stale"
REASON_READ_CAP_EXCEEDED = "run-record-read-cap-exceeded"

#: The explicit W5 cold-open rebuild affordance the degraded paint surfaces.
#: RELATIVE command form only — never a host-absolute path.
REBUILD_COMMAND = "python chamber_coldopen.py rebuild <project-folder>"
REBUILD_AFFORDANCE_LABEL = "Rebuild projections"


def rebuild_affordance() -> dict:
    """The machine-readable W5 rebuild affordance (surfaced, NEVER run, by
    the open path)."""
    return {
        "label": REBUILD_AFFORDANCE_LABEL,
        "command": REBUILD_COMMAND,
        "module": "chamber_coldopen",
        "verb": "rebuild",
        "law": "an inline rebuild on the open path is a test failure (C1 "
               "drawn-degraded-until-rebuilt); the rebuild is an explicit, "
               "separate act",
    }


# ── Structural fix 1: ledger tail-read from the last snapshot line ──────────

def read_ledger_tail(folder) -> dict:
    """ONE parse of ``roadmap.json``; state from the snapshot; a REVERSED
    event scan that stops at the snapshot line.

    Returns ``{present, unreadable, steps, as_of, tail_events, read_stats}``
    where ``read_stats`` carries the honest bound numbers:
    ``ledger_events_total`` (whatever history exists),
    ``ledger_events_scanned`` (tail + the one snapshot-line hit that stops
    the scan) and ``ledger_tail_count``. The open path NEVER replays the
    full event history into state — that is the W6 structural fix.
    """
    p = Path(folder) / "roadmap.json"
    stats = {"ledger_events_total": 0, "ledger_events_scanned": 0,
             "ledger_tail_count": 0}
    if not p.exists():
        return {"present": False, "unreadable": False, "steps": [],
                "as_of": None, "tail_events": [], "read_stats": stats}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("roadmap.json is not an object")
    except (ValueError, OSError):
        return {"present": True, "unreadable": True, "steps": [],
                "as_of": None, "tail_events": [], "read_stats": stats}

    steps = cb._projection_steps(doc)   # the snapshot IS the step state
    as_of = str(doc.get("as_of") or "")
    events = doc.get("roadmap_events")
    events = events if isinstance(events, list) else []
    stats["ledger_events_total"] = len(events)

    # Reverse scan: collect events strictly AFTER the snapshot instant; stop
    # the moment the snapshot line is reached. An event with no usable ``at``
    # is treated as covered by the snapshot (the writer stamps every event;
    # an unstamped one cannot be proven newer, and guessing would replay).
    tail = []
    scanned = 0
    for e in reversed(events):
        scanned += 1
        at = str(e.get("at") or "") if isinstance(e, dict) else ""
        if not as_of or not at or at <= as_of:
            break
        tail.append(e)
    tail.reverse()
    stats["ledger_events_scanned"] = scanned
    stats["ledger_tail_count"] = len(tail)
    return {"present": True, "unreadable": False, "steps": steps,
            "as_of": as_of or None, "tail_events": tail, "read_stats": stats}


# ── Structural fix 2: run-record reads capped to active scaffold steps ──────

def active_step_ids(steps: list) -> set:
    """The ACTIVE scaffold steps: everything not reconciled done."""
    return {s["id"] for s in steps if s.get("status") != "done"}


def plan_run_record_reads(folder, steps: list, projection_events: list,
                          cap: int = RUN_RECORD_READ_CAP) -> dict:
    """Decide WHICH run-record files this open may read, bounded.

    Selection law (the plan's): reads are capped to the ACTIVE scaffold
    steps. The projection store's events are the citation index — a record
    is a candidate only when a projection event ties its session to an
    active step (commission_start carries the session→step bond; later
    events on the same session inherit it). When the store carries NO
    citations at all (a projectorless-but-not-degraded edge), the candidate
    set falls back to every present record — still under the hard backstop.

    ``refused`` is True when the candidate set exceeds ``cap``: the open
    then paints the drawn degraded-rail state and reads NOTHING (never an
    unbounded read, never a silent truncation that would paint a partial
    rail as whole).
    """
    root = Path(folder) / cr.RUN_RECORDS_REL
    files = sorted(root.glob("*.json")) if root.is_dir() else []
    present = len(files)

    active = active_step_ids(steps)
    step_of_session: dict = {}
    cited = False
    for e in projection_events:
        if not isinstance(e, dict):
            continue
        sid = e.get("session_id")
        if not sid:
            continue
        cited = True
        if e.get("step_id"):
            step_of_session.setdefault(str(sid), str(e["step_id"]))
    wanted = {sid for sid, step in step_of_session.items() if step in active}
    # A session the store cites without a step bond cannot be proven
    # inactive; it stays a candidate (honest inclusion, still capped).
    for e in projection_events:
        if isinstance(e, dict) and e.get("session_id") \
                and str(e["session_id"]) not in step_of_session:
            wanted.add(str(e["session_id"]))

    if cited:
        candidates = [f for f in files if f.stem in wanted]
    else:
        candidates = list(files)

    refused = len(candidates) > cap
    return {
        "candidates": [] if refused else candidates,
        "refused": refused,
        "stats": {
            "run_records_present": present,
            "run_record_candidates": len(candidates),
            "run_record_read_cap": cap,
            "run_record_reads": 0 if refused else len(candidates),
        },
    }


def _normalize_run_record(rec: dict, fallback_sid: str) -> dict:
    """The same record shape ``chamber_reconcile.read_run_records`` yields
    (kept field-for-field in sync — the capped open path must agree with the
    W5 reconciliation about what a record says)."""
    outcome = rec.get("outcome")
    return {
        "session_id": rec.get("session_id") or fallback_sid,
        "commission_id": rec.get("commission_id"),
        "step_id": rec.get("step_id"),
        "skill": rec.get("skill"),
        "lane": rec.get("lane"),
        "outcome": outcome,
        "at": rec.get("at") or "",
        "elapsed_s": (rec.get("elapsed_s")
                      if isinstance(rec.get("elapsed_s"), (int, float))
                      else None),
        "report_say": (cr._first_line((rec.get("report") or {}).get("say"))
                       if isinstance(rec.get("report"), dict) else ""),
        "terminal": outcome != cr.OUTCOME_LIVE,
        "has_reflection": isinstance(rec.get("reflection"), dict),
    }


def read_run_records_capped(candidates: list) -> list:
    """Read EXACTLY the planned candidate files (already bounded), ascending
    (at, session). Unreadable individual records are skipped — they cannot
    claim anything."""
    rows = []
    for f in candidates:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(rec, dict):
            rows.append(_normalize_run_record(rec, f.stem))
    rows.sort(key=lambda r: (r["at"], str(r["session_id"])))
    return rows


# ── The open-path view (one bounded pass; zero writes; zero spawns) ─────────

def _degraded_view(reasons: list, ledger: dict, stats: dict,
                   t0: float) -> dict:
    return {
        "schema": SCHEMA,
        "ok": True,
        "degraded": {
            "state": DEGRADED_RAIL_STATE,
            "amendment_ref": DEGRADED_AMENDMENT_REF,
            "reasons": reasons,
            "rebuild": rebuild_affordance(),
        },
        "steps": ledger["steps"],
        "goal": None,
        "brief": None,
        "progress": {"done": sum(1 for s in ledger["steps"]
                                 if s.get("status") == "done"),
                     "total": len(ledger["steps"])},
        "live_run": None,
        "deliverable": None,
        "read_stats": stats,
        "open_ms": (time.perf_counter() - t0) * 1000.0,
    }


def seal_open_view(folder) -> dict:
    """Everything the painted vertical-slice Seal needs, in one bounded,
    deterministic read pass. Never writes, never spawns, never rebuilds."""
    t0 = time.perf_counter()
    folder = Path(folder)
    reasons: list = []

    # Sidecar leg 1: the projection store (missing/corrupt/stale → degraded).
    store = {"events": []}
    store_p = _cp.store_path(folder)
    if not store_p.exists():
        reasons.append(REASON_PROJECTIONS_MISSING)
    else:
        try:
            store = _cp.load_store(folder)
            if store.get("schema") != _cp.SCHEMA:
                reasons.append(REASON_PROJECTIONS_SCHEMA_STALE)
        except _cp.ProjectionStoreError:
            reasons.append(REASON_PROJECTIONS_UNREADABLE)

    # Sidecar leg 2: the precomputed brief (W5 — the steward's opening).
    brief = cr.load_brief(folder)
    if brief is None:
        reasons.append(REASON_BRIEF_MISSING)
    elif brief.get("error"):
        reasons.append(REASON_BRIEF_UNREADABLE)
    elif brief.get("schema") != cr.SCHEMA:
        reasons.append(REASON_BRIEF_SCHEMA_STALE)

    # Sidecar leg 3: the pipeline manifest (F2).
    manifest = cm.load_manifest(folder)
    if manifest is None:
        reasons.append(REASON_MANIFEST_MISSING)
    elif "_unparseable" in manifest:
        reasons.append(REASON_MANIFEST_UNREADABLE)
    elif manifest.get("schema_version") != cm.SCHEMA_VERSION:
        reasons.append(REASON_MANIFEST_SCHEMA_STALE)

    # The ledger tail-read (always; cheap; snapshot-first).
    ledger = read_ledger_tail(folder)
    stats = dict(ledger["read_stats"])

    if reasons:
        # Fresh deploy / stale sidecar: the DRAWN degraded paint. No
        # run-record reads on this path (bounded), no writes, no rebuild.
        stats.update({"run_records_present": None, "run_record_candidates": 0,
                      "run_record_read_cap": RUN_RECORD_READ_CAP,
                      "run_record_reads": 0})
        return _degraded_view(reasons, ledger, stats, t0)

    steps = ledger["steps"]
    if not steps and isinstance(manifest.get("steps"), list):
        # Ledger snapshot honestly empty — the validated manifest's steps
        # carry the rail skeleton (both are chamber-derived data).
        steps = [{"id": s.get("id"), "name": s.get("name") or s.get("id"),
                  "status": None, "skill": s.get("skill")}
                 for s in manifest["steps"] if isinstance(s, dict)]

    events = store.get("events") or []
    plan = plan_run_record_reads(folder, steps, events)
    stats.update(plan["stats"])
    if plan["refused"]:
        reasons = [REASON_READ_CAP_EXCEEDED]
        return _degraded_view(reasons, ledger, stats, t0)

    runs = read_run_records_capped(plan["candidates"])
    stats["run_record_reads"] = len(plan["candidates"])

    # Per-step enrichment from the projection events (latest wins per step).
    latest_yield: dict = {}
    latest_death_session: dict = {}
    step_of_session: dict = {}
    landing = None
    for e in events:
        kind = e.get("kind")
        sid = str(e.get("session_id") or "")
        if e.get("step_id") and sid:
            step_of_session.setdefault(sid, str(e["step_id"]))
        if kind == _cp.KIND_STEP_YIELD and e.get("step_id"):
            latest_yield[str(e["step_id"])] = e
        elif kind == _cp.KIND_RUN_DEATH and sid:
            latest_death_session[sid] = e
        elif kind == _cp.KIND_DELIVERABLE_LANDING:
            landing = e

    live = [r for r in runs if r["outcome"] == cr.OUTCOME_LIVE]
    live_run = None
    if live:
        r = live[-1]
        live_run = {"session_id": r["session_id"], "step_id": r["step_id"],
                    "skill": r["skill"], "at": r["at"]}

    step_rows = []
    for s in steps:
        row = dict(s)
        y = latest_yield.get(s["id"])
        if y is not None:
            row["yield"] = {"text": y.get("yield"),
                            "report_link": y.get("report_link")}
        if live_run and live_run["step_id"] == s["id"]:
            row["running"] = live_run
        step_rows.append(row)

    deliverable = None
    dv = manifest.get("deliverable")
    if isinstance(dv, dict) and dv.get("declared"):
        deliverable = {"declared": True,
                       "description": dv.get("description"),
                       "output_path": dv.get("output_path"),
                       "landed": bool(landing),
                       "landing": landing}

    fields = (brief or {}).get("fields") or {}
    goal = fields.get("goal_guard") or {}
    done = sum(1 for s in steps if s.get("status") == "done")

    return {
        "schema": SCHEMA,
        "ok": True,
        "degraded": None,
        "steps": step_rows,
        # The rows this open ALREADY read (W7's ETA medians reuse them so the
        # whole-open read backstop holds; the HTTP layer strips this key).
        "_run_rows": runs,
        "goal": goal,
        "brief": {
            "as_of": (brief or {}).get("as_of"),
            "pre_emission": (brief or {}).get("pre_emission"),
            "degraded": (brief or {}).get("degraded"),
            "stand": fields.get("stand"),
            "running": fields.get("running"),
            "next_move": fields.get("next_move"),
        },
        "progress": {"done": done, "total": len(steps)},
        "live_run": live_run,
        "deliverable": deliverable,
        "read_stats": stats,
        "open_ms": (time.perf_counter() - t0) * 1000.0,
    }


# ═════════════════════════════════════════════════════════════════════════════
# The thin verbatim-markup shell (mockups.html §M1 subset; C9 hash-pinned)
# ═════════════════════════════════════════════════════════════════════════════
# Structure below is copied VERBATIM from the signed mockup (element-for-
# element, class-for-class); only slot VALUES vary and every value is escaped.
# The C9 differ (chamber_mockup_diff) compares this render's DOM/class tree
# against the hash-pinned mockup on every chamber change.

def _esc(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


#: F5 link-scheme law (steward-chamber W9): a yield's report link renders as
#: an anchor ONLY when it targets one of the fixed internal read routes;
#: anything else (javascript:, an agent-invented path) renders as inert
#: escaped text. Mirrors chamber_dom_law.INTERNAL_HREF_PREFIXES minus the
#: in-page "#" (chamber_dom_law is CI-only and never imported by product
#: code; tests/test_chamber_dom_law_w9.py pins the mirror in sync).
_REPORT_LINK_PREFIXES = ("/artifact/", "/report/", "/summary/")


def _first_not_done(steps: list) -> dict | None:
    for s in steps:
        if s.get("status") != "done":
            return s
    return None


def _skillch(step: dict) -> str:
    skill = step.get("skill")
    if skill:
        return '<span class="skillch">· %s</span>' % _esc(skill)
    # AG-STEP-NO-SKILL (signed): never a guessed skill.
    return '<span class="skillch nosk">· no skill bound</span>'


def _render_dbar(view: dict, steward: dict | None) -> str:
    stw = steward or {}
    name = stw.get("label") or "Ecgberht"
    glyph = stw.get("glyph") or "\U0001f9ff"  # the seal mark (persona-free)
    seat = stw.get("seat") or "claude"
    return (
        '<div class="dbar">'
        '<div class="seal">%s</div>'
        '<span class="ti">%s <small>· steward of this project</small></span>'
        '<span class="pill">seat: %s</span>'
        '<span class="sp"></span>'
        '<span class="stamp">everything receipted</span>'
        '<button class="btn" data-seal-close="1">×</button>'
        '</div>'
    ) % (_esc(glyph), _esc(name), _esc(seat))


def _render_progress(view: dict) -> str:
    prog = view.get("progress") or {}
    done, total = prog.get("done") or 0, prog.get("total") or 0
    pct = int(round(100.0 * done / total)) if total else 0
    live = view.get("live_run")
    if live:
        run_now = "▶ %s · %s" % (live.get("skill") or "a run",
                                 live.get("step_id") or "a step")
    else:
        nxt = _first_not_done(view.get("steps") or [])
        run_now = ("— idle · next: %s" % nxt.get("name")) if nxt \
            else "— idle · nothing queued"
    # ETA: the per-skill rolling-median module is W7. Until it lands the
    # drawn AG-ZERO-HISTORY-ETA presentation shows — never an extrapolation.
    return (
        '<div class="progress">'
        '<div class="bar"><b style="width:%d%%"></b></div>'
        '<span>%d/%d steps done</span>'
        '<span class="run-now">%s</span>'
        '<span class="eta nohist">campaign est — gathering history</span>'
        '</div>'
    ) % (pct, done, total, _esc(run_now))


def _render_goalbar(view: dict) -> str:
    goal = view.get("goal") or {}
    if goal.get("text"):
        return (
            '<div class="goalbar">'
            '<span class="lab">North star</span>'
            '<span class="txt">%s</span>'
            '<span class="sp" style="flex:1"></span>'
            '<button class="btn gold">Still the goal</button>'
            '<button class="btn">Refine it</button>'
            '</div>'
        ) % _esc(goal["text"])
    # AG-GOAL-UNREADABLE (signed): honest text + [Set the goal], never a
    # fabricated goal.
    return (
        '<div class="goalbar unread">'
        '<span class="lab">North star</span>'
        '<span class="txt">goal unreadable — this campaign&#x27;s goal card '
        'is missing or unparseable</span>'
        '<span class="sp" style="flex:1"></span>'
        '<button class="btn gold">Set the goal</button>'
        '</div>'
    )


def _render_fstep(step: dict) -> str:
    status = step.get("status")
    name = _esc(step.get("name") or step.get("id") or "a step")
    if step.get("running"):
        run = step["running"]
        started = run.get("at") or "unknown time"
        # The live ⏱ stream re-homes into this card in W7 (run_pulse row of
        # the wire-homing registry). Until then the drawn AG-PRE-EMISSION
        # runcard face carries the honest ledger facts only.
        ttable = "⏱ running · started %s\nlive status joins this card when " \
                 "the pulse re-homes — open the session panel for live " \
                 "output" % started
        return (
            '<div class="fstep run">'
            '<span class="dot">▶</span>'
            '<div class="nm">%s %s</div>'
            '<div class="runcard warm"><div class="ttable">%s</div></div>'
            '</div>'
        ) % (name, _skillch(step), _esc(ttable))
    if status == "done":
        y = step.get("yield")
        if y and y.get("text"):
            link = y.get("report_link")
            if isinstance(link, str) and link.startswith(_REPORT_LINK_PREFIXES):
                inner = '%s · <a href="%s">report ▸</a>' \
                        % (_esc(y["text"]), _esc(link))
            else:
                inner = _esc(y["text"])
            yield_div = '<div class="yield">%s</div>' % inner
        else:
            # AG-YIELD-MISSING (signed): labeled, never fabricated.
            yield_div = ('<div class="yield miss">yield missing — no '
                         'reflection receipt was recorded for this step</div>')
        return (
            '<div class="fstep done">'
            '<span class="dot">✔</span>'
            '<div class="nm">%s %s</div>'
            '%s'
            '</div>'
        ) % (name, _skillch(step), yield_div)
    return (
        '<div class="fstep">'
        '<span class="dot">○</span>'
        '<div class="nm">%s %s</div>'
        '</div>'
    ) % (name, _skillch(step))


def _render_deliv(view: dict) -> str:
    d = view.get("deliverable")
    if not d:
        return ""
    desc = d.get("description") or "declared deliverable"
    return (
        '<div class="deliv">'
        '<div class="lab">Deliverable</div>'
        '%s'
        '<div style="margin-top:6px;display:flex;gap:6px">'
        '<button class="btn gold">open ▸</button>'
        '<button class="btn">where it lands</button>'
        '</div>'
        '</div>'
    ) % _esc(desc)


def _render_flow(view: dict) -> str:
    steps_html = "".join(_render_fstep(s) for s in view.get("steps") or [])
    return (
        '<aside class="flow">'
        '<div style="display:flex;align-items:center;gap:8px;margin:0 0 10px">'
        '<h3 style="margin:0;flex:1">The flow</h3>'
        '<button class="btn gold" style="font-size:10px">Still the plan</button>'
        '<button class="btn" style="font-size:10px" '
        'data-refine-overlay="1">Refine the plan</button>'
        '</div>'
        '%s%s'
        '</aside>'
    ) % (steps_html, _render_deliv(view))


def _brief_prose(view: dict, steward_name: str) -> str:
    brief = view.get("brief") or {}
    lines = []
    for key in ("stand", "running", "next_move"):
        field = brief.get(key) or {}
        if field.get("text"):
            lines.append(str(field["text"]))
    if not lines:
        # The drawn degraded brief (AG-PRE-EMISSION-OPEN lineage, W5): honest
        # emptiness, never a synthesized narrative.
        lines = ["Nothing has been recorded for this campaign yet — no run, "
                 "no reflection, no roadmap step. Say the word and %s will "
                 "start it." % steward_name]
    return " ".join(lines)


def _render_convo(view: dict, steward: dict | None) -> str:
    stw = steward or {}
    name = stw.get("label") or "Ecgberht"
    live = view.get("live_run")
    if live:
        livestatus = (
            '<div class="livestatus"><span class="livedot">⏱</span> '
            '%s running on %s · since %s</div>'
        ) % (_esc(live.get("skill") or "a run"),
             _esc(live.get("step_id") or "a step"),
             _esc(live.get("at") or "unknown time"))
    else:
        nxt = _first_not_done(view.get("steps") or [])
        nxt_bit = (" · next: %s · say the word to start it"
                   % nxt.get("name")) if nxt else ""
        # AG-NO-RUNNING-STEP (signed): the quiet idle line.
        livestatus = ('<div class="livestatus idle">— idle · no step '
                      'running%s</div>') % _esc(nxt_bit)
    return (
        '<div class="convo">'
        '<div class="msgs">'
        '<div class="msg steward"><div class="who">%s</div>%s</div>'
        '</div>'
        '%s'
        # chamber-m1 W1: data-say-input / data-say-send are the delegation
        # hooks for the drawn say box — ATTRIBUTES ONLY. The C9 signature is
        # (tag, sorted-classes), so the signed mockup hash pin holds and no
        # amendment is needed.
        '<div class="saybox">'
        '<input data-say-input placeholder="Talk to %s — it answers in '
        'seconds, runs stay in the flow rail…" />'
        '<button class="btn gold" data-say-send>Say it</button>'
        '</div>'
        '</div>'
    ) % (_esc(name), _esc(_brief_prose(view, name)), livestatus, _esc(name))


def _render_degraded(view: dict, steward: dict | None) -> str:
    deg = view["degraded"]
    steps = view.get("steps") or []
    grey = []
    for s in steps:
        grey.append(
            '<div class="fstep" style="margin-top:8px;opacity:.6">'
            '<span class="dot">○</span>'
            '<div class="nm">%s %s</div>'
            '<div class="yield">detail returns when the rebuild lands — an '
            'inline rebuild on the open path is forbidden</div>'
            '</div>'
            % (_esc(s.get("name") or s.get("id") or "a step"), _skillch(s)))
    # AG-DEGRADED-RAIL (signed): drawn degraded rail + the explicit W5
    # rebuild affordance. Painted from the raw ledger; nothing fabricated.
    reasons = ", ".join(deg.get("reasons") or [])
    return (
        '%s'
        '<div class="degrail">'
        '<span class="lab">Degraded</span>'
        '<span>projections not built yet (%s) — painted from the raw ledger '
        'in &lt;2s, zero model calls</span>'
        '<span class="sp" style="flex:1"></span>'
        '<button class="btn gold" data-rebuild-command="%s">%s</button>'
        '</div>'
        '%s'
    ) % (_render_dbar(view, steward), _esc(reasons),
         _esc(deg["rebuild"]["command"]), _esc(deg["rebuild"]["label"]),
         "".join(grey))


def render_seal_slice_html(view: dict, steward: dict | None = None) -> str:
    """The painted vertical-slice M1 shell (W6): verbatim mockup structure
    over the :func:`seal_open_view` projections. Pure string render — no IO,
    no spawn, no model, no write."""
    if view.get("degraded"):
        body = _render_degraded(view, steward)
    else:
        body = (
            "%s%s%s"
            '<div class="chamber">%s%s</div>'
        ) % (_render_dbar(view, steward), _render_progress(view),
             _render_goalbar(view), _render_flow(view),
             _render_convo(view, steward))
    return '<div class="dock">%s</div>' % body
