"""Skill Foundry v2 — Wave 12: the Anchor-side North-Star acceptance scorecard.

The frozen plan's Wave 12 proves the ANCHOR-SIDE North-Star journey
end-to-end on genuine data — create a skill, run/monitor it + see its
changes, browse the library + knowledge graph, edit its North Star, every
foundry skill auto-available/clickable in Anchor, all mutations journaled,
the safety envelope armed. This module is the machine-checkable half of
that proof (the other half is the end-to-end gate,
``tests/test_foundry_acceptance_w12.py``, which DRIVES the journey over the
real machinery): the North-Star DONE= clause REGISTRY (:data:`CLAUSES`) plus
LIVE probes (:func:`acceptance_report`) that verify each clause against the
real engine — the same accessors the GUI reads through, never a parallel
store — and the honest, explicit record of the ONE clause this build defers:

    THE SINGLE DECLARED-PENDING ITEM. The North Star's central sleep-loop
    clause ("run + review a test-gated sleep improvement that has turned
    over >=1x on genuine data") is delivered by the SEPARATE foundry-kernel
    build (FOUNDRY-KERNEL-PLAN.md) plus the final integration pass that
    registers the ``foundry.sleep_session`` op body behind the Wave-10 GUI
    seam. Until that op registers, the clause reports ``declared-pending``
    and :func:`open_item` names it explicitly — recorded for the
    integration step, never silently dropped. When the op body lands, the
    clause flips to ``wired-awaiting-integration-proof``: this module NEVER
    stamps it proven (turnover on genuine data is the integration pass's
    proof to make, not a status to fabricate here).

Every probe is READ-ONLY and exception-hardened — a broken artifact yields
an honest ``unproven`` clause with the problem named, never a crash — so
the scorecard renders on the /foundry page itself
(:func:`render_acceptance_panel`, embedded by
``foundry_gui.render_foundry_page``). This module holds no state, mutates
no file, and keeps no mirror: the Wave-9 anti-theater scan applies to it
verbatim and the Wave-12 gate runs that scan against this source.

Stdlib only (Anchor's no-dep rule) + the product seams ``paths`` /
``foundry_decisions`` / ``foundry_gui`` / ``foundry_gui_write`` /
``foundry_journal`` / ``foundry_map`` / ``foundry_map_gates`` /
``foundry_ops`` / ``foundry_autoload`` / ``foundry_safety`` /
``skill_runner``.
"""

import html as _html
from pathlib import Path

import paths as _paths
import foundry_autoload as _fa
import foundry_decisions as _fd
import foundry_gui as _fgui
import foundry_gui_write as _fgw
import foundry_journal as _fj
import foundry_map as _fm
import foundry_map_gates as _fmg
import foundry_ops as _fo
import foundry_safety as _fsafety
import skill_runner as _sr


# ── Constants ────────────────────────────────────────────────────────────────

#: Wave-1 anti-drift convention: the acceptance surface traces to the
#: North Star (the whole scorecard IS the DONE= contract made machine-real).
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                        _fd.NS_SLEEP_LOOP_TURNS_OVER)

#: Clause statuses. ``declared-pending`` is RESERVED for the split-deferred
#: sleep-loop clause (a recorded open item, not a failure); a clause whose
#: live probes fail is ``unproven`` (honest, never papered over); a wired
#: sleep seam is still only ``wired-awaiting-integration-proof`` — proven
#: is a stamp the integration pass earns on genuine data, never fabricated.
STATUS_PROVEN = "proven"
STATUS_UNPROVEN = "unproven"
STATUS_DECLARED_PENDING = "declared-pending"
STATUS_WIRED = "wired-awaiting-integration-proof"

#: The North-Star DONE= clause ids (the acceptance vocabulary).
CLAUSE_CREATE = "create-a-skill"
CLAUSE_RUN_MONITOR = "run-monitor-see-changes"
CLAUSE_LIBRARY_GRAPH = "browse-library-and-graph"
CLAUSE_EDIT_NORTH_STAR = "edit-north-star"
CLAUSE_CLICKABLE = "skills-clickable-in-anchor"
CLAUSE_JOURNALED = "mutations-journaled"
CLAUSE_SAFETY = "safety-envelope-armed"
CLAUSE_SLEEP_LOOP = "sleep-loop-turnover"

#: The declared sleep-session op interface (single-sourced from the Wave-10
#: seam — the acceptance scorecard targets the SAME interface the GUI does).
SLEEP_SESSION_OP = _fgw.SLEEP_SESSION_OP

#: Who delivers the deferred clause, and at which step (the SPLIT NOTE of
#: the frozen plan, recorded in code so it can never be silently dropped).
SLEEP_DELIVERED_BY = ("the separate foundry-kernel build "
                      "(FOUNDRY-KERNEL-PLAN.md) + the final integration "
                      "pass that registers the foundry.sleep_session op "
                      "body behind the Wave-10 GUI seam")
INTEGRATION_STEP = "final-integration-pass"

#: The DONE= clause registry — one record per North-Star acceptance clause.
#: The sleep-loop record carries ``declared_pending`` + the op interface it
#: targets; every record carries its North-Star trace tags (Wave-1 rule).
CLAUSES = (
    {
        "clause": CLAUSE_CREATE,
        "title": "Create a skill from the GUI",
        "journey": "GUI 'Create a skill' -> foundry.scaffold_skill "
                   "(confirm-gated, headless via job_runner)",
        "traces_to_north_star": (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                                 _fd.NS_MANIFEST_RUNNER),
    },
    {
        "clause": CLAUSE_RUN_MONITOR,
        "title": "Run/monitor a skill + see its changes",
        "journey": "generic runner run -> job_runner monitor -> journaled "
                   "changes view (engine state, never a mirror)",
        "traces_to_north_star": (_fd.NS_MANIFEST_RUNNER,
                                 _fd.NS_HOST_ENFORCED_JOURNAL),
    },
    {
        "clause": CLAUSE_LIBRARY_GRAPH,
        "title": "Browse the library + knowledge graph",
        "journey": "autoload registry library + map.json v2 graph with the "
                   "lockfile pins, drift-gate-enforced",
        "traces_to_north_star": (_fd.NS_KNOWLEDGE_GRAPH,),
    },
    {
        "clause": CLAUSE_EDIT_NORTH_STAR,
        "title": "Edit a skill's North Star",
        "journey": "GUI propose -> explicit human confirm -> apply as a "
                   "branch commit with the prior version retained",
        "traces_to_north_star": (_fd.NS_GUI_DRIVES_REAL_MACHINERY,),
    },
    {
        "clause": CLAUSE_CLICKABLE,
        "title": "Every foundry skill auto-available/clickable in Anchor",
        "journey": "foundry.register_autoload regenerates the clickable set "
                   "from map.json v2 alone",
        "traces_to_north_star": (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                                 _fd.NS_KNOWLEDGE_GRAPH),
    },
    {
        "clause": CLAUSE_JOURNALED,
        "title": "All mutations journaled",
        "journey": "every control-plane op dispatches journal-enabled + "
                   "confirm-gated + write-scoped through the runner seam",
        "traces_to_north_star": (_fd.NS_HOST_ENFORCED_JOURNAL,),
    },
    {
        "clause": CLAUSE_SAFETY,
        "title": "Safety envelope armed",
        "journey": "reaper armed to FREEZE via the Wave-11 sanctioned path; "
                   "fail-deadly retired; per-host concurrency budget in the "
                   "runner; zombie-hunter stays native",
        "traces_to_north_star": (_fd.NS_SAFETY_ENVELOPE,),
    },
    {
        "clause": CLAUSE_SLEEP_LOOP,
        "title": "Run + review a test-gated sleep improvement "
                 "(turned over >=1x on genuine data)",
        "journey": "GUI 'Run sleep session -> review' -> "
                   "foundry.sleep_session",
        "traces_to_north_star": (_fd.NS_SLEEP_LOOP_TURNS_OVER,),
        "declared_pending": True,
        "op_interface": SLEEP_SESSION_OP,
        "delivered_by": SLEEP_DELIVERED_BY,
        "step": INTEGRATION_STEP,
    },
)


def clause_ids() -> list:
    """The DONE= clause ids, registry order."""
    return [rec["clause"] for rec in CLAUSES]


def clause_record(clause_id):
    """One registry record (a copy — the registry itself is never handed
    out mutable); ``None`` for an unknown id."""
    for rec in CLAUSES:
        if rec["clause"] == str(clause_id):
            return dict(rec)
    return None


# ── The single declared open item (the split-deferred sleep-loop clause) ─────

def open_item(dispatch=None):
    """The ONE explicit open item this build hands the integration step.

    While the ``foundry.sleep_session`` op body is not registered (checked
    through the SAME Wave-10 seam the GUI uses — a live ``dispatch`` table
    when given, else the headless-op registry), returns the recorded item:
    which clause, which op interface, why, who delivers it, at which step.
    Once the op body registers, returns ``None`` — the item is closed by
    wiring, not by editing this module."""
    st = _fgw.sleep_session_status(dispatch)
    if st.get("wired"):
        return None
    return {
        "clause": CLAUSE_SLEEP_LOOP,
        "op_interface": SLEEP_SESSION_OP,
        "reason": _fgw.SLEEP_PENDING_REASON,
        "delivered_by": SLEEP_DELIVERED_BY,
        "step": INTEGRATION_STEP,
    }


# ── Per-clause live probes (read-only; problems in, honest verdicts out) ─────

def _require_gui_op(problems, op, verbs) -> None:
    """A journey verb is real only if its op is DR-01-inventoried, runs
    HEADLESS (a registered ``foundry_ops`` CLI host), and the GUI write
    surface maps the verb to that op (one engine, many surfaces)."""
    if op not in _fd.MUTATIVE_VERBS:
        problems.append("op-not-in-dr01-inventory:%s" % op)
    if op not in _fo.OP_CLI_NAMES:
        problems.append("op-not-headless:%s" % op)
    for verb in verbs:
        if (verb, op) not in _fgw.IMPLEMENTED_VERBS:
            problems.append("gui-verb-not-wired:%s->%s" % (verb, op))


def _probe_create(problems, evidence) -> None:
    _require_gui_op(problems, _fo.OP_SCAFFOLD, ("create_skill",))
    evidence["op"] = _fo.OP_SCAFFOLD


def _probe_run_monitor(problems, evidence) -> None:
    runs = _fgui.runs_view(lane=_fo.OPS_LANE)
    if not runs.get("ok"):
        problems.append("runs-view-not-ok")
    evidence["ops_lane_runs"] = runs.get("total")
    for accessor in ("runs_view", "monitor_view", "changes_view"):
        if not callable(getattr(_fgui, accessor, None)):
            problems.append("read-surface-missing:%s" % accessor)
    theater = _fgui.anti_theater_check()
    if theater:
        problems.append(("anti-theater:"
                         + "; ".join(str(t) for t in theater))[:200])


def _probe_library_graph(problems, evidence, home, map_path, lock_path,
                         root) -> None:
    lib = _fgui.library_view(home=home)
    if not lib.get("ok"):
        problems.append("library:%s" % lib.get("reason"))
    elif not lib.get("registered"):
        problems.append("library-not-registered-yet")
    evidence["library_count"] = lib.get("count")
    graph = _fgui.graph_view(map_path=map_path, lock_path=lock_path)
    if not graph.get("ok"):
        problems.append("graph:%s" % graph.get("reason"))
        return
    evidence["nodes"] = len(graph.get("nodes") or ())
    evidence["edges"] = len(graph.get("edges") or ())
    lock = graph.get("lock") or {}
    if not lock.get("ok"):
        problems.append(("lock-drift:" + "; ".join(
            str(p) for p in lock.get("problems") or ()))[:200])
    # NS#4 is drift-gate-ENFORCED: the three Wave-6 gates must be green.
    mp = Path(map_path) if map_path else _fm.MAP_FILE
    lp = Path(lock_path) if lock_path else _fm.LOCK_FILE
    doc = _fm.load_map(mp)
    gates = _fmg.run_drift_gates(doc, lock_path=lp, root=root)
    evidence["drift_gates"] = [(g["gate"], bool(g["ok"]))
                               for g in gates["gates"]]
    if not gates.get("ok"):
        bad = [g["gate"] for g in gates["gates"] if not g["ok"]]
        problems.append("drift-gates-red:" + ",".join(bad))


def _probe_edit_north_star(problems, evidence) -> None:
    _require_gui_op(problems, _fo.OP_EDIT_NORTH_STAR,
                    ("north_star_propose", "north_star_apply"))
    evidence["op"] = _fo.OP_EDIT_NORTH_STAR


def _probe_clickable(problems, evidence, home, map_path) -> None:
    if _fo.OP_REGISTER_AUTOLOAD not in _fo.OP_CLI_NAMES:
        problems.append("op-not-headless:%s" % _fo.OP_REGISTER_AUTOLOAD)
    mp = Path(map_path) if map_path else _fm.MAP_FILE
    try:
        doc = _fm.load_map(mp)
    except (OSError, ValueError) as exc:
        problems.append("map-unreadable:%s" % exc)
        return
    bad = _fm.validate_map(doc)
    if bad:
        problems.append(("map-invalid:" + "; ".join(bad))[:200])
        return
    names = [str(s.get("name")) for s in doc["skills"]]
    # Resolve the registry home WITHOUT creating it (pure read).
    h = Path(home) if home else (_paths.data_dir() / _fa.AUTOLOAD_DIRNAME)
    try:
        regs = _fa.clickable_skills(h)
    except ValueError as exc:
        problems.append("registry-unreadable:%s" % exc)
        return
    reg_names = set(str(r.get("name")) for r in regs if isinstance(r, dict))
    missing = [n for n in names if n not in reg_names]
    evidence["map_skills"] = len(names)
    evidence["registered"] = len(reg_names)
    if missing:
        problems.append(("not-clickable-in-anchor:"
                         + ",".join(sorted(missing)))[:200])


def _probe_journaled(problems, evidence, skills_root) -> None:
    manifests = _fo.full_control_plane_manifests(skills_root=skills_root)
    for m in manifests:
        sk = str(m.get("skill"))
        if not (m.get("journal") or {}).get("enabled"):
            problems.append("journal-disabled:%s" % sk)
        if m.get("op_kind") != "mutate":
            problems.append("op-not-mutate:%s" % sk)
        if not m.get("write_scope"):
            problems.append("no-write-scope:%s" % sk)
    evidence["ops"] = len(manifests)
    jdir = _fj.journal_dir(_fo.ops_home())
    entries = sorted(jdir.glob("*.md")) if jdir.is_dir() else []
    valid = 0
    for p in entries:
        parsed = _fj.parse_entry(
            p.read_text(encoding="utf-8", errors="replace"))
        if parsed and _fj.validate_entry(parsed) == []:
            valid += 1
        else:
            problems.append("journal-entry-invalid:%s" % p.name)
    evidence["journal_entries"] = len(entries)
    evidence["journal_valid"] = valid
    runs = _fgui.runs_view(lane=_fo.OPS_LANE)
    total = int(runs.get("total") or 0)
    evidence["ops_lane_runs"] = total
    if total > len(entries):
        problems.append("op-runs-exceed-journal-entries:%d>%d"
                        % (total, len(entries)))


def _probe_safety(problems, evidence, source) -> None:
    check = _fsafety.recheck_fail_deadly(source=source)
    evidence["fail_deadly_retired"] = bool(check.get("retired"))
    if not check.get("retired"):
        problems.append(("fail-deadly-not-retired:" + "; ".join(
            str(p) for p in check.get("problems") or ()))[:200])
    native = _fsafety.reaper_is_native_builtin()
    evidence["native_builtin"] = bool(native.get("native"))
    if not native.get("native"):
        problems.append(("reaper-not-native:" + "; ".join(
            str(p) for p in native.get("problems") or ()))[:200])
    budget = _sr.concurrency_budget()
    evidence["concurrency_budget"] = budget
    if budget < 1:
        problems.append("no-concurrency-budget")
    # Lazy: the reaper stack is reloaded by hermetic rigs; resolve it live.
    import reaper_arming as _arm
    tier = _arm.persisted_tier()
    evidence["reaper_tier"] = tier
    if tier not in (_arm.TIER_FREEZE, _arm.TIER_KILL):
        problems.append("reaper-not-armed:tier=%s" % tier)


def _sleep_clause_status(evidence, dispatch) -> str:
    st = _fgw.sleep_session_status(dispatch)
    evidence["op_interface"] = SLEEP_SESSION_OP
    evidence["seam_status"] = st.get("status")
    if not st.get("wired"):
        evidence["reason"] = st.get("reason")
        return STATUS_DECLARED_PENDING
    return STATUS_WIRED


# ── The report ───────────────────────────────────────────────────────────────

def acceptance_report(*, home=None, map_path=None, lock_path=None, root=None,
                      skills_root=None, dispatch=None, source=None) -> dict:
    """Probe every DONE= clause live → the honest acceptance report.

    Seams (all optional; live defaults): ``home`` the autoload registry
    home, ``map_path``/``lock_path`` the graph artifacts, ``root`` the
    foundry root for target-existence, ``skills_root`` the op-manifest
    root, ``dispatch`` the live op table the GUI drives (sleep-seam wiring
    check), ``source`` injected call-site source for the fail-deadly
    re-check. Returns ``{north_star, clauses, proven, unproven, pending,
    open_item, accepted}`` where ``accepted`` is True iff NO clause is
    unproven and the only pending item (if any) is the declared sleep-loop
    clause — everything proven EXCEPT the one recorded open item."""
    clauses = []
    for rec in CLAUSES:
        cid = rec["clause"]
        problems, evidence = [], {}
        status = None
        try:
            if cid == CLAUSE_SLEEP_LOOP:
                status = _sleep_clause_status(evidence, dispatch)
            elif cid == CLAUSE_CREATE:
                _probe_create(problems, evidence)
            elif cid == CLAUSE_RUN_MONITOR:
                _probe_run_monitor(problems, evidence)
            elif cid == CLAUSE_LIBRARY_GRAPH:
                _probe_library_graph(problems, evidence, home, map_path,
                                     lock_path, root)
            elif cid == CLAUSE_EDIT_NORTH_STAR:
                _probe_edit_north_star(problems, evidence)
            elif cid == CLAUSE_CLICKABLE:
                _probe_clickable(problems, evidence, home, map_path)
            elif cid == CLAUSE_JOURNALED:
                _probe_journaled(problems, evidence, skills_root)
            elif cid == CLAUSE_SAFETY:
                _probe_safety(problems, evidence, source)
        except Exception as exc:  # a broken artifact is a verdict, not a crash
            problems.append("probe-crashed:%r" % (exc,))
        if status is None:
            status = STATUS_PROVEN if not problems else STATUS_UNPROVEN
        row = dict(rec)
        row["status"] = status
        row["problems"] = problems
        row["evidence"] = evidence
        clauses.append(row)
    proven = [c["clause"] for c in clauses if c["status"] == STATUS_PROVEN]
    unproven = [c["clause"] for c in clauses
                if c["status"] == STATUS_UNPROVEN]
    pending = [c["clause"] for c in clauses
               if c["status"] == STATUS_DECLARED_PENDING]
    accepted = (not unproven
                and all(c == CLAUSE_SLEEP_LOOP for c in pending))
    return {
        "north_star": _fd.NORTH_STAR_DOC,
        "clauses": clauses,
        "proven": proven,
        "unproven": unproven,
        "pending": pending,
        "open_item": open_item(dispatch),
        "accepted": accepted,
    }


# ── The scorecard panel (rendered into the /foundry page) ────────────────────

_PANEL_CSS = """
  .accgrid { background:var(--panel); border:1px solid var(--line);
             padding:10px 14px; margin:8px 0 14px; }
  .accrow { font-size:12.5px; margin:3px 0; }
  .accsym { display:inline-block; width:16px; }
  .accstat { color:var(--dim,#8a93a6); font-size:11.5px; }
  .accprob { color:#c66; font-size:11.5px; }
  .accopen { margin-top:8px; font-size:12px; color:#c9a227; }
"""


def _esc(value) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


def _status_glyph(status) -> str:
    if status == STATUS_PROVEN:
        return "&#10003;"     # check mark
    if status == STATUS_DECLARED_PENDING:
        return "&#8987;"      # hourglass
    if status == STATUS_WIRED:
        return "&#9203;"      # hourglass, flowing
    return "&#10007;"         # cross mark


def render_acceptance_panel(*, home=None, map_path=None, lock_path=None,
                            root=None, skills_root=None, dispatch=None,
                            report=None) -> str:
    """The North-Star acceptance strip the /foundry page embeds — one row
    per DONE= clause with its LIVE probe verdict, and the single declared
    open item (the sleep-loop clause) named explicitly until the
    integration pass wires the op body. Pure read: rendering probes the
    engine's artifacts and persists nothing."""
    rep = report if isinstance(report, dict) else acceptance_report(
        home=home, map_path=map_path, lock_path=lock_path, root=root,
        skills_root=skills_root, dispatch=dispatch)
    out = ["<style>%s</style>" % _PANEL_CSS,
           "<h2>North-Star acceptance</h2>",
           '<div class="accgrid" data-acceptance="north-star-scorecard" '
           'data-accepted="%s">' % ("true" if rep.get("accepted")
                                    else "false")]
    for c in rep.get("clauses") or ():
        probs = "; ".join(str(p) for p in c.get("problems") or ())
        prob_html = (' <span class="accprob">%s</span>' % _esc(probs)
                     if probs else "")
        out.append(
            '<div class="accrow" data-clause="%s" data-status="%s">'
            '<span class="accsym">%s</span><b>%s</b> '
            '<span class="accstat">%s</span>%s</div>'
            % (_esc(c.get("clause")), _esc(c.get("status")),
               _status_glyph(c.get("status")), _esc(c.get("title")),
               _esc(c.get("status")), prob_html))
    item = rep.get("open_item")
    if item:
        out.append(
            '<div class="accopen" data-acceptance-open-item="%s">'
            'the single declared open item for the integration step: '
            '%s &mdash; %s (delivered by %s)</div>'
            % (_esc(item.get("op_interface")), _esc(item.get("op_interface")),
               _esc(item.get("reason")), _esc(item.get("delivered_by"))))
    out.append("</div>")
    out.append('<div class="src">every clause above is probed live against '
               'the engine&#39;s own artifacts; the sleep-loop clause stays '
               'the single declared open item until the foundry-kernel '
               'integration registers the op body</div>')
    return "\n".join(out)
