"""Full M1 rail (steward-chamber W7, C2/C9/C12).

The W6 vertical slice hardened into the FULL M1 rail, rendered ONLY from
manifest + projections:

* **Typed edges** (C2/F2) — each rail step's ``rides in:`` line derives from
  the validated sidecar manifest's ``edges`` (``{from, to, artifact_kind}``).
  A pre-manifest campaign with no derivable edges simply omits the line
  (R-EDGE-LINE: omission is a drawn variant, never invented UI).
* **Rulebook-derived per-step states** — the W1 provenance rulebook's rules,
  named in :data:`STATE_RULES`: ``proposed`` steps are excluded from the
  rail (R-PROPOSED-EXCLUDED), the ✔/▶/○ marker classes derive from the
  single-writer-maintained roadmap status plus the last-writer-wins run
  record (R-STEP-MARKER — the statuses themselves were produced by the
  engine's ``status_flip`` events through ``engine/roadmap.mjs``, the wired
  status_flip row of the wire-homing registry; the chamber only RENDERS
  them, never re-derives flips).
* **Done-step yields** — one line from the recorded step_yield projection
  with its report link; a done step with NO recorded yield renders the
  labeled drawn ``yield missing`` state (AG-YIELD-MISSING), never a
  fabrication (R-YIELD-LINE).
* **run_pulse re-homed** (C12) — the running step's ⏱ card seeds from the
  SAME data core the tiles consume (``chamber_pulse.step_slot_from_record``
  over the banked run record; the live poll rides the run_pulse endpoint) —
  wired, not reimplemented.
* **ETA medians** (C2) — ``chamber_eta``'s per-skill rolling medians with
  the n>=3 guard: campaign line, future-step suffixes, running-step est
  line, every estimate basis-labeled; zero history renders the DRAWN
  AG-ZERO-HISTORY-ETA presentation.

Bounded like the W6 open (the 200-read backstop is WHOLE-OPEN: capped
candidates + ETA history + the pulse seed all count), deterministic (two
views compare equal modulo the stopwatch), write-free, spawn-free.

The render is mockup-VERBATIM structure (C9): every element/class below is
copied from the signed mockups.html §M1 (+ the signed amendment states); the
hash-pinned DOM diff (``chamber_mockup_diff.verify_m1_render``) fails any
invention. Slot values are escaped; structure is never invented.

Stdlib only.
"""
from __future__ import annotations

import json
from pathlib import Path

import chamber_deliverable as cdeliv
import chamber_eta as ce
import chamber_manifest as cm
import chamber_open as copen
import chamber_pulse as cpulse
import chamber_reconcile as cr

SCHEMA = "anchor-chamber-seal-rail-v1"

#: The W1 provenance rulebook rules this renderer implements (the
#: "rulebook-derived per-step states" claim, grounded by name — see
#: chamber/provenance-table.json cells carrying these rule_ids).
RULE_PROPOSED_EXCLUDED = "R-PROPOSED-EXCLUDED"
RULE_STEP_MARKER = "R-STEP-MARKER"
RULE_PROGRESS_COUNT = "R-PROGRESS-COUNT"
RULE_YIELD_LINE = "R-YIELD-LINE"
RULE_EDGE_LINE = "R-EDGE-LINE"
RULE_STEP_ETA = "R-STEP-ETA"
RULE_CAMPAIGN_ETA = "R-CAMPAIGN-ETA"

#: R-STEP-MARKER: roadmap status -> the drawn fstep state class. The status
#: values are the single writer's own vocabulary (proposed|planned|active|
#: waiting|done|parked); 'proposed' never reaches this map (excluded above).
#: waiting/parked have NO signed drawn face of their own in the W1 batch —
#: they render the drawn base (pending) row; their cards are W10's.
STATE_RULES = {
    "done": "done",
    "active": "run",
    "planned": "",
    "waiting": "",
    "parked": "",
    None: "",
}


def step_state_class(status, is_live: bool) -> str:
    """R-STEP-MARKER: the fstep state class for one rail step. A live run
    record on the step wins over any stale roadmap claim (last-writer-wins,
    E9) — the record is the writer of record for RUN state."""
    if is_live:
        return "run"
    return STATE_RULES.get(status, "")


# ── The full-rail view (chamber_open's bounded open + W7 enrichment) ────────

def _manifest_edges_by_target(manifest) -> dict:
    """``{to_step_id: [edge, ...]}`` from a validated manifest (else {})."""
    out: dict = {}
    if not isinstance(manifest, dict):
        return out
    edges = manifest.get("edges")
    if not isinstance(edges, list):
        return out
    for e in edges:
        if isinstance(e, dict) and e.get("to"):
            out.setdefault(str(e["to"]), []).append(e)
    return out


def _manifest_skills(manifest) -> dict:
    """``{step_id: skill}`` declared on the manifest (F2 — FS-SKILL's
    commission-time declaration; never a guess)."""
    out: dict = {}
    if not isinstance(manifest, dict):
        return out
    for s in manifest.get("steps") or []:
        if isinstance(s, dict) and s.get("id") and s.get("skill"):
            out[str(s["id"])] = s["skill"]
    return out


def seal_rail_view(folder, project_id=None) -> dict:
    """The FULL M1 view: ``chamber_open.seal_open_view`` (the bounded W6
    open — tail-read, capped run-record reads, degraded-rail refusals all
    unchanged) enriched with typed edges, rulebook states, the pulse step
    slot, and the guarded ETA rows. Read-only; deterministic.

    W9: when the manifest declares a deliverable, the view's deliverable
    carries the F3-bounded ``action`` — the SAFE projection of the
    chamber-local action registry's resolution (armed href / armed spawn
    verb / the labeled inert state with its named reason). ``project_id``
    (optional) lets an armed ``open-report`` action carry its internal
    ``/artifact/`` href; argv/cwd never ride the view."""
    view = copen.seal_open_view(folder)
    view["rail_schema"] = SCHEMA
    # SAFE by construction (it is the id already in the window's URL): lets
    # the runcard's transcript ▸ link target the traversal-safe /artifact
    # route (steward-e1 W2 — tile-retirement decision 1's ordered row).
    view["project_id"] = str(project_id) if project_id else None
    if view.get("degraded"):
        return view  # the drawn degraded paint carries no rail enrichment

    manifest = cm.load_manifest(folder)
    edges_by_target = _manifest_edges_by_target(manifest)
    manifest_skill = _manifest_skills(manifest)

    # R-PROPOSED-EXCLUDED: a still-proposed step is not on the rail.
    rail_steps = [s for s in view.get("steps") or []
                  if s.get("status") != "proposed"]

    # R-STEP-MARKER inputs + FS-SKILL fallback + R-EDGE-LINE lines.
    live = view.get("live_run") or {}
    for s in rail_steps:
        if not s.get("skill") and s.get("id") in manifest_skill:
            s["skill"] = manifest_skill[s["id"]]
        s["state_class"] = step_state_class(
            s.get("status"), bool(live) and live.get("step_id") == s.get("id"))
        incoming = edges_by_target.get(str(s.get("id") or ""))
        if incoming:
            s["rides_in"] = [e.get("artifact_kind") or e.get("from")
                             for e in incoming]

    # R-PROGRESS-COUNT: done / rail-included.
    done = sum(1 for s in rail_steps if s.get("status") == "done")
    view["steps"] = rail_steps
    view["progress"] = {"done": done, "total": len(rail_steps)}

    stats = view["read_stats"]
    reads_so_far = int(stats.get("run_record_reads") or 0)
    budget = max(0, copen.RUN_RECORD_READ_CAP - reads_so_far)

    # The pulse ⏱ seed: the live run's BANKED record through the run_pulse
    # data core (wire-homing row run_pulse — same scan the tiles serve).
    # ONE bounded file read; zero PTY touches on the open path.
    view["pulse_slot"] = None
    pulse_read = 0
    if live.get("session_id") and budget > 0:
        rec_path = (Path(folder) / cr.RUN_RECORDS_REL
                    / ("%s.json" % live["session_id"]))
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            pulse_read = 1
        except (ValueError, OSError):
            rec = None
        if isinstance(rec, dict):
            view["pulse_slot"] = cpulse.step_slot_from_record(rec)
        budget -= pulse_read

    # ETA medians over the project's own run records, inside the SAME open
    # read backstop (already-read rows reused; extra reads budgeted).
    collected = ce.collect_durations(
        folder, already_rows=view.pop("_run_rows", None), read_budget=budget)
    by_skill = collected["by_skill"]
    eta_steps: dict = {}
    for s in rail_steps:
        if s.get("status") != "done":
            eta_steps[s.get("id")] = ce.skill_eta(by_skill, s.get("skill"))
    view["eta"] = {
        "campaign": ce.campaign_eta(rail_steps, by_skill),
        "per_step": eta_steps,
        "rolling_window": ce.ROLLING_WINDOW,
        "min_runs": ce.MIN_RUNS,
    }
    stats["eta_run_record_reads"] = collected["extra_reads"]
    stats["eta_skipped_for_budget"] = collected["skipped_for_budget"]
    stats["pulse_record_read"] = pulse_read
    stats["run_record_reads"] = (reads_so_far + pulse_read
                                 + collected["extra_reads"])

    # W9 (F3): the declared deliverable's registry action — the SAFE
    # projection only (verb / label / relative path / named inert reason;
    # argv and cwd NEVER serialize into a view). Disk existence + the
    # validated manifest are the only sources (never model-remembered).
    dv = view.get("deliverable")
    if isinstance(dv, dict) and isinstance(manifest, dict):
        mdv = manifest.get("deliverable")
        if isinstance(mdv, dict) and mdv.get("declared"):
            dv["type"] = mdv.get("type")
            dv["action"] = cdeliv.public_action(
                cdeliv.resolve_action(folder, mdv, project_id=project_id))
    return view


# ═════════════════════════════════════════════════════════════════════════════
# The full-mount render (mockups.html §M1 verbatim structure; C9 pinned)
# ═════════════════════════════════════════════════════════════════════════════

_esc = copen._esc


def _skillch_html(step: dict, eta_row: dict | None) -> str:
    """The per-step skill chip, with the R-STEP-ETA suffix on future steps:
    ``· Crucible · est ~45m (median of 4 runs)`` at n>=3, the drawn
    AG-ZERO-HISTORY-ETA text below it, the drawn AG-STEP-NO-SKILL chip when
    no skill resolves (never a guessed skill)."""
    skill = step.get("skill")
    if not skill:
        return '<span class="skillch nosk">· no skill bound</span>'
    text = "· %s" % skill
    if eta_row is not None:
        if eta_row["state"] == ce.STATE_OK:
            text += " · est %s (%s)" % (ce.format_duration(eta_row["eta_s"]),
                                        eta_row["basis"])
        else:
            text += " · %s" % eta_row["label"]
    return '<span class="skillch">%s</span>' % _esc(text)


def _yield_html(step: dict) -> str:
    """R-YIELD-LINE: the done-step one-line yield with its report link, or
    the labeled drawn AG-YIELD-MISSING state — never a fabricated yield."""
    y = step.get("yield")
    if y and y.get("text"):
        link = y.get("report_link")
        # F5 link-scheme law (W9): only the fixed internal read routes render
        # as an anchor (copen._REPORT_LINK_PREFIXES — the code-owned mirror of
        # chamber_dom_law.INTERNAL_HREF_PREFIXES); anything else is inert text.
        if isinstance(link, str) and link.startswith(copen._REPORT_LINK_PREFIXES):
            inner = '%s · <a href="%s">report ▸</a>' \
                    % (_esc(y["text"]), _esc(link))
        else:
            inner = _esc(y["text"])
        return '<div class="yield">%s</div>' % inner
    return ('<div class="yield miss">yield missing — no reflection receipt '
            'was recorded for this step</div>')


def _edge_html(step: dict) -> str:
    """R-EDGE-LINE: the typed-edge line from the manifest — what rides from
    upstream into this step's brief. Omitted when no edge is declared
    (omission is a drawn variant; nothing invented for pre-manifest
    campaigns)."""
    rides = step.get("rides_in")
    if not rides:
        return ""
    return '<div class="yield">rides in: %s</div>' \
        % _esc(" + ".join(str(r) for r in rides))


def _runcard_html(view: dict, step: dict, eta_row: dict | None) -> str:
    """The running step's ⏱ card — run_pulse re-homed into the rail.

    A captured ⏱/[HH:MM] block (from the run_pulse data core over the
    banked record) renders the REAL runcard with the status ▸ / session ▸
    links; no block yet renders the drawn AG-PRE-EMISSION-OPEN warm face.
    The est line is basis-labeled at n>=3 (R-STEP-ETA), absent below —
    never a one-record extrapolation.
    """
    slot = view.get("pulse_slot") or {}
    run = step.get("running") or {}
    eta_line = ""
    if eta_row is not None and eta_row["state"] == ce.STATE_OK:
        eta_line = "est %s left (%s)" % (
            ce.format_duration(eta_row["eta_s"]), eta_row["basis"])
    if slot.get("status_block"):
        ttable = slot["status_block"]
        if eta_line:
            ttable += "\n" + eta_line
        sid = slot.get("session_id") or run.get("session_id") or ""
        # transcript ▸ (steward-e1 W2 — the ORDERED tile-retirement decision-1
        # row, batched through the W2 amendment gate): the durable transcript
        # via the traversal-safe /artifact route. The href rides
        # data-deliv-href (validated at click against the F5 internal
        # prefixes; the token joins there). Omitted when the id is unknown —
        # omission is a drawn variant, never a broken link.
        transcript = ""
        if sid and view.get("project_id"):
            transcript = (
                '<a href="#" data-deliv-href="%s">transcript ▸</a>'
                % _esc("/artifact/%s?path=%s"
                       % (view["project_id"],
                          "general/%s-transcript.md" % sid)))
        return (
            '<div class="runcard" data-eta-line="%s">'
            '<div class="ttable">%s</div>'
            '<div class="links">'
            '<a href="#" data-status-overlay="1">status ▸</a>'
            '<a href="#" data-open-session="%s">session ▸</a>'
            '%s'
            '</div>'
            '</div>'
        ) % (_esc(eta_line), _esc(ttable), _esc(sid), transcript)
    started = run.get("at") or slot.get("started_at") or "unknown time"
    ttable = ("⏱ warming up — started %s\nno status emitted yet · first ⏱ "
              "update lands within 10m" % started)
    if eta_line:
        ttable += "\n" + eta_line
    return ('<div class="runcard warm"><div class="ttable">%s</div></div>'
            % _esc(ttable))


def _fstep_html(view: dict, step: dict) -> str:
    eta_row = (view.get("eta") or {}).get("per_step", {}).get(step.get("id"))
    cls = step.get("state_class")
    if cls is None:
        cls = step_state_class(step.get("status"), bool(step.get("running")))
    name = _esc(step.get("name") or step.get("id") or "a step")
    if cls == "run":
        body = _runcard_html(view, step, eta_row) if step.get("running") \
            else _edge_html(step)
        return (
            '<div class="fstep run">'
            '<span class="dot">▶</span>'
            '<div class="nm">%s %s</div>'
            '%s'
            '</div>'
        ) % (name, _skillch_html(step, None), body)
    if cls == "done":
        return (
            '<div class="fstep done">'
            '<span class="dot">✔</span>'
            '<div class="nm">%s %s</div>'
            '%s'
            '</div>'
        ) % (name, _skillch_html(step, None), _yield_html(step))
    return (
        '<div class="fstep">'
        '<span class="dot">○</span>'
        '<div class="nm">%s %s</div>'
        '%s'
        '</div>'
    ) % (name, _skillch_html(step, eta_row), _edge_html(step))


def _progress_html(view: dict) -> str:
    """The progress header with the R-CAMPAIGN-ETA line: labeled per-skill
    medians at full history, the drawn AG-ZERO-HISTORY-ETA text otherwise."""
    prog = view.get("progress") or {}
    done, total = prog.get("done") or 0, prog.get("total") or 0
    pct = int(round(100.0 * done / total)) if total else 0
    live = view.get("live_run")
    if live:
        run_now = "▶ %s · %s" % (live.get("skill") or "a run",
                                 live.get("step_id") or "a step")
    else:
        nxt = copen._first_not_done(view.get("steps") or [])
        run_now = ("— idle · next: %s" % nxt.get("name")) if nxt \
            else "— idle · nothing queued"
    camp = (view.get("eta") or {}).get("campaign") or {}
    if camp.get("state") == ce.STATE_OK:
        eta_span = '<span class="eta">%s</span>' % _esc(camp["label"])
    elif camp.get("state") == "idle":
        eta_span = '<span class="eta">%s</span>' % _esc(camp["label"])
    else:
        label = camp.get("label") or "campaign est — gathering history"
        eta_span = '<span class="eta nohist">%s</span>' % _esc(label)
    return (
        '<div class="progress">'
        '<div class="bar"><b style="width:%d%%"></b></div>'
        '<span>%d/%d steps done</span>'
        '<span class="run-now">%s</span>'
        '%s'
        '</div>'
    ) % (pct, done, total, _esc(run_now), eta_span)


def _flow_html(view: dict) -> str:
    steps_html = "".join(_fstep_html(view, s) for s in view.get("steps") or [])
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
    ) % (steps_html, cdeliv.render_deliv_box(view))


def render_seal_rail_html(view: dict, steward: dict | None = None) -> str:
    """The FULL painted M1 mount (W7): verbatim mockup structure over the
    :func:`seal_rail_view` data. Pure string render — no IO, no spawn, no
    model, no write. The degraded face and the chrome pieces the slice
    already carried (dbar / goalbar / convo) are REUSED from chamber_open —
    one source of truth per drawn element."""
    if view.get("degraded"):
        return ('<div class="dock">%s</div>'
                % copen._render_degraded(view, steward))
    body = (
        "%s%s%s"
        '<div class="chamber">%s%s</div>'
    ) % (copen._render_dbar(view, steward), _progress_html(view),
         copen._render_goalbar(view), _flow_html(view),
         copen._render_convo(view, steward))
    return '<div class="dock">%s</div>' % body


# ── The verbatim mockup CSS for the style-isolated mount ────────────────────

_CSS_CACHE: dict = {}


def mockup_css() -> str | None:
    """The signed mockup's ``<style>`` block, VERBATIM, for the shadow-root
    mount — served through the C9 hash pin (``chamber_mockup_diff``), memoized
    per process. ``None`` when the pin cannot verify (the mount then falls
    back to the page's scoped W6 stylesheet — honest degraded styling; the
    C9 CI diff is hard-failing in that state anyway)."""
    if "css" not in _CSS_CACHE:
        try:
            import chamber_mockup_diff as cmd
            _CSS_CACHE["css"] = cmd.mockup_style_text()
        except Exception:
            _CSS_CACHE["css"] = None
    return _CSS_CACHE["css"]
