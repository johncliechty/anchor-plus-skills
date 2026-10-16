"""foundry-v2 Wave 12 — Anchor-side North-Star acceptance proof (end-to-end).

Proves the Wave-12 done-when:
  (a) the END-TO-END Anchor-side acceptance test runs the North-Star journey
      over REAL machinery on genuine (rig-created, not canned) data — create
      a skill from the GUI verb (→ ``foundry.scaffold_skill`` through
      job_runner), run it through the generic runner (its OWN host, real
      subprocess) + monitor the op job + see its journaled changes, browse
      the library + knowledge graph (autoload registry + map.json v2 with
      verified lock pins), edit its North Star (propose → explicit confirm →
      apply, prior retained) — plus every foundry skill auto-available/
      clickable in Anchor, ALL mutations journaled, and the safety envelope
      ARMED (reaper to FREEZE via the Wave-11 sanctioned path);
  (b) the invariant/drift gates from ALL prior waves stay green, re-run
      LIVE here: the Wave-1 decision registry, the Wave-9 anti-theater scan
      (including against the NEW acceptance module), the Wave-10 2nd-surface
      honesty check, the Wave-11 fail-deadly re-check + native-built-in +
      concurrency budget, and the Wave-5/6 drift gates + supply-chain
      signing on a graph a REAL scaffold op just mutated;
  (c) the sleep-loop clause is the SINGLE declared-pending item — the
      acceptance report (``foundry_acceptance``) records it explicitly,
      targeting the ``foundry.sleep_session`` interface for the integration
      step (never silently dropped), it is the ONLY pending clause, and when
      the op body registers (what the foundry-kernel build + integration
      pass delivers) the item closes by WIRING — with the clause still never
      fabricated "proven" (turnover on genuine data is the integration
      pass's proof to make);
  plus: the /foundry page renders the acceptance scorecard strip (each
  clause + the open item) and the Anchor launch entry point still serves it.

Hermetic like tests/test_foundry_gui_write_w10.py + the Wave-11 reaper rig:
temp ANCHOR_DATA_DIR + temp skills root + temp map/lock/autoload + the
freshly-reloaded reaper stack; op hosts are this repo's own
``foundry_ops.py`` via ``sys.executable`` (deterministic local code — NEVER
real claude / real node / the real Skill Foundry / the worktree map /
:8777; no process is ever frozen or killed). Stdlib + pytest only.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

import foundry_acceptance as facc
import foundry_autoload as fa
import foundry_decisions as fd
import foundry_gui as fgui
import foundry_gui_write as fgw
import foundry_map as fm
import foundry_map_gates as fmg
import foundry_ops as fo
import job_runner as jr
import skill_runner as sr

_ROOT = Path(__file__).resolve().parents[1]

NOW = 5_000_000.0

NEW_TEXT = ("# North Star - accepted (w12)\n\n"
            "- the Anchor-side journey is real\n"
            "- DONE looks like genuine data, not a demo\n")


class FakeProbe:
    """A creation-time-only probe. Missing entry => the PID probes DEAD."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


# ── Fixture: the hermetic Wave-12 acceptance rig (w10 shape + w11 reloads) ───

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Temp data dir + freshly-reloaded reaper stack + skills root + seed
    map/lock + autoload home + the FULL control-plane dispatch."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    # No token configured → auth is disabled and the GATE is what is tested
    # (the reaper control-plane test file covers auth itself).
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    import freeze_state
    importlib.reload(freeze_state)
    import reaper_arming
    importlib.reload(reaper_arming)
    import foundry_safety
    importlib.reload(foundry_safety)
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (skills_root / "gandalf").mkdir()
    doc = {
        "schema": fm.MAP_SCHEMA_ID,
        "map_version": fm.MAP_VERSION,
        "skills": [
            {"ref": "skill:gandalf", "name": "gandalf",
             "source": (skills_root / "gandalf").as_posix(),
             "status": "5 - Production/Stable", "tier": "standard",
             "version": "1.2.0", "edges": []},
        ],
    }
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = tmp_path / "map.lock.json"
    fm.write_lockfile(doc, path=lock_path)
    autoload_home = tmp_path / "autoload"
    autoload_home.mkdir()
    dispatch = fo.build_full_control_dispatch(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path,
        autoload_home=autoload_home)
    return {"tmp": tmp_path, "data": data_dir, "skills_root": skills_root,
            "map": map_path, "lock": lock_path, "autoload": autoload_home,
            "seed_doc": doc, "dispatch": dispatch}


def _create(rig, name, **over):
    kwargs = dict(dispatch=rig["dispatch"], confirm=True,
                  skills_root=str(rig["skills_root"]),
                  map_path=str(rig["map"]), lock_path=str(rig["lock"]),
                  git=False)
    kwargs.update(over)
    return fgw.create_skill(name, **kwargs)


def _report(rig, dispatch=None):
    return facc.acceptance_report(
        home=rig["autoload"], map_path=rig["map"], lock_path=rig["lock"],
        root=rig["skills_root"], skills_root=rig["skills_root"],
        dispatch=dispatch if dispatch is not None else rig["dispatch"])


def _arm_to_freeze(monkeypatch):
    """Arm the reaper to FREEZE through the Wave-11 sanctioned path (the
    receipt-gated ladder; never a real process touched)."""
    import reaper
    import reaper_arming as arm
    import foundry_safety as fsafety
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    snap = reaper.build_snapshot(
        attached_pty_ids=set(), records=[], job_active=lambda _s: False,
        probe=FakeProbe({}), now=NOW)
    out = fsafety.arm_reaper_to_freeze("tok", snapshot=snap, now=NOW)
    assert out["ok"] is True, out
    assert out["fail_deadly"]["retired"] is True
    assert arm.persisted_tier() == arm.TIER_FREEZE


# ── (a) the end-to-end North-Star acceptance journey over real machinery ─────

def test_north_star_acceptance_journey_end_to_end(rig, monkeypatch):
    # BEFORE the journey the scorecard is already honest: the sleep-loop
    # clause is declared-pending — it never depends on rig state to appear.
    rep0 = _report(rig)
    assert facc.CLAUSE_SLEEP_LOOP in rep0["pending"]

    # 1 — CREATE a skill from the GUI verb → foundry.scaffold_skill runs
    # headlessly through job_runner and lands the skill on disk.
    res = _create(rig, "accept-w12", title="Accept W12")
    assert res["ok"] is True, res["reason"]
    assert res["output"]["skill"] == "accept-w12"
    assert res["job"] is not None and res["job"]["status"] == "done"
    create_job_id = res["job"]["job_id"]
    sd = rig["skills_root"] / "accept-w12"
    for rel in ("SKILL.md", "NORTH-STAR.md", "host.py", "manifest.json"):
        assert (sd / rel).is_file(), rel
    assert jr.load_record(create_job_id)["lane"] == fo.OPS_LANE

    # 2 — RUN the created skill through the generic runner (its OWN host,
    # a real subprocess — genuine data, not a canned fixture)...
    manifest = sr.load_skill_manifest(sd)
    d2 = sr.build_dispatch([manifest])
    run_res = sr.run_op(d2, "accept-w12", payload={"proof": "w12"})
    assert run_res["ok"] is True, run_res["reason"]
    assert run_res["output"]["verdict"] == "scaffold-template-ok"
    # ...and SEE ITS CHANGES via the host-enforced journal (Wave-2 seam).
    ch = fgui.changes_view(sd)
    assert ch["count"] == 1
    assert ch["entries"][0]["operation_kind"] == "run"

    # 3 — MONITOR the create op's job over job_runner state (never a mirror).
    mv = fgui.monitor_view(create_job_id)
    assert mv["ok"] is True and mv["lane"] == fo.OPS_LANE
    assert mv["status"] == jr.STATUS_DONE

    # 4 — EDIT ITS NORTH STAR: propose parks a reviewable diff, the explicit
    # confirm applies it, the prior version is retained.
    before = (sd / "NORTH-STAR.md").read_text(encoding="utf-8")
    res = fgw.north_star_propose("accept-w12", NEW_TEXT,
                                 dispatch=rig["dispatch"], confirm=True,
                                 skills_root=str(rig["skills_root"]))
    assert res["ok"] is True, res["reason"]
    assert res["output"]["applied"] is False
    pid = res["output"]["proposal_id"]
    res = fgw.north_star_apply("accept-w12", pid, dispatch=rig["dispatch"],
                               confirm=True,
                               skills_root=str(rig["skills_root"]), git=False)
    assert res["ok"] is True, res["reason"]
    assert res["output"]["applied"] is True
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == NEW_TEXT
    prior = res["output"]["prior_retained"]
    assert prior and (sd / prior).read_text(encoding="utf-8") == before

    # 5 — BROWSE LIBRARY + GRAPH: the sync makes every foundry skill
    # clickable in Anchor from map.json v2 alone.
    res = fgw.sync_autoload(dispatch=rig["dispatch"], confirm=True,
                            map_path=str(rig["map"]),
                            home=str(rig["autoload"]), root=str(rig["tmp"]))
    assert res["ok"] is True, res["reason"]
    assert res["output"]["count"] == 2
    assert fa.is_clickable("accept-w12", home=rig["autoload"]) is True
    assert fa.is_clickable("gandalf", home=rig["autoload"]) is True
    lib = fgui.library_view(home=rig["autoload"])
    assert {r["name"] for r in lib["skills"]} == {"gandalf", "accept-w12"}
    graph = fgui.graph_view(map_path=rig["map"], lock_path=rig["lock"])
    assert graph["ok"] is True and graph["lock"]["ok"] is True
    assert {n["name"] for n in graph["nodes"]} == {"gandalf", "accept-w12"}

    # 6 — ALL MUTATIONS JOURNALED: exactly the four dispatched ops (create ·
    # propose · apply · sync) as journal entries AND as ops-lane job records.
    entries = sorted((rig["data"] / "foundry_ops" / "journal").glob("*.md"))
    assert len(entries) == 4
    runs = fgui.runs_view(lane=fo.OPS_LANE)
    assert runs["ok"] is True and runs["total"] == 4

    # 7 — SAFETY ENVELOPE ARMED: reaper to FREEZE via the Wave-11 path.
    _arm_to_freeze(monkeypatch)

    # 8 — THE ACCEPTANCE REPORT over the same real machinery: everything
    # proven EXCEPT the single declared-pending sleep-loop clause.
    rep = _report(rig)
    assert rep["accepted"] is True, rep
    assert rep["unproven"] == []
    assert rep["pending"] == [facc.CLAUSE_SLEEP_LOOP]
    assert sorted(rep["proven"]) == sorted([
        facc.CLAUSE_CREATE, facc.CLAUSE_RUN_MONITOR,
        facc.CLAUSE_LIBRARY_GRAPH, facc.CLAUSE_EDIT_NORTH_STAR,
        facc.CLAUSE_CLICKABLE, facc.CLAUSE_JOURNALED, facc.CLAUSE_SAFETY])
    item = rep["open_item"]
    assert item["clause"] == facc.CLAUSE_SLEEP_LOOP
    assert item["op_interface"] == "foundry.sleep_session"
    assert item["reason"] == fgw.SLEEP_PENDING_REASON
    assert "integration" in item["delivered_by"]
    safety_row = [c for c in rep["clauses"]
                  if c["clause"] == facc.CLAUSE_SAFETY][0]
    assert safety_row["evidence"]["reaper_tier"] == "freeze"
    assert safety_row["evidence"]["fail_deadly_retired"] is True

    # 9 — the /foundry page (what the Anchor button serves) carries the
    # accepted scorecard, the created skill, and the single open item.
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert 'data-acceptance="north-star-scorecard"' in page
    assert 'data-accepted="true"' in page
    assert 'data-acceptance-open-item="foundry.sleep_session"' in page
    assert "accept-w12" in page


# ── (c) the sleep-loop clause: the SINGLE declared-pending item ──────────────

def test_sleep_loop_is_the_single_declared_pending_item(rig):
    # The registry record targets the declared op interface, split-honestly.
    clause = facc.clause_record(facc.CLAUSE_SLEEP_LOOP)
    assert clause["declared_pending"] is True
    assert clause["op_interface"] == fgw.SLEEP_SESSION_OP
    assert clause["op_interface"] == "foundry.sleep_session"
    assert fd.NS_SLEEP_LOOP_TURNS_OVER in clause["traces_to_north_star"]
    # The op body is NOT in this build (the Wave-10 seam is the contract).
    assert fgw.SLEEP_SESSION_OP not in fo.OP_CLI_NAMES

    # The explicit open item: recorded for the integration step — which
    # clause, which interface, why, who delivers it. Never silently dropped.
    item = facc.open_item(rig["dispatch"])
    assert item is not None
    assert item["clause"] == facc.CLAUSE_SLEEP_LOOP
    assert item["op_interface"] == "foundry.sleep_session"
    assert item["reason"] == fgw.SLEEP_PENDING_REASON
    assert item["step"] == facc.INTEGRATION_STEP
    assert "FOUNDRY-KERNEL-PLAN" in item["delivered_by"]

    # It is the SINGLE pending clause on the report (pending is reserved
    # for the declared split deferral — a failing probe is 'unproven',
    # never 'pending', so nothing else can hide in this bucket).
    rep = _report(rig)
    assert rep["pending"] == [facc.CLAUSE_SLEEP_LOOP]
    assert rep["open_item"]["clause"] == facc.CLAUSE_SLEEP_LOOP
    sleep_row = [c for c in rep["clauses"]
                 if c["clause"] == facc.CLAUSE_SLEEP_LOOP][0]
    assert sleep_row["status"] == facc.STATUS_DECLARED_PENDING
    assert sleep_row["evidence"]["reason"] == fgw.SLEEP_PENDING_REASON

    # THE SEAM IS THE CONTRACT: register an op body for the interface (what
    # the foundry-kernel build + integration pass delivers) and the item
    # closes by WIRING — no edit to the acceptance module, and the clause
    # is still NEVER fabricated "proven" (that stamp belongs to the
    # integration pass's genuine-data proof).
    sdir = rig["tmp"] / "sleep-skill"
    sdir.mkdir()
    (sdir / "host.py").write_text(
        "import json\n"
        "print(json.dumps({'schema': 'sleep/v1', 'verdict': 'sleep-ok'}))\n",
        encoding="utf-8")
    m = {
        "skill": fgw.SLEEP_SESSION_OP,
        "skill_dir": str(sdir),
        "op_kind": "run",
        "host_cmd": [sys.executable, "{skill_dir}/host.py"],
        "output_contract": {"format": "json",
                            "required_keys": ["schema", "verdict"]},
        "panel": {"title": "Sleep Session"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    assert sr.validate_manifest(m) == []
    wired = sr.build_dispatch([m])
    assert facc.open_item(wired) is None
    rep2 = _report(rig, dispatch=wired)
    assert rep2["pending"] == []
    assert rep2["open_item"] is None
    row2 = [c for c in rep2["clauses"]
            if c["clause"] == facc.CLAUSE_SLEEP_LOOP][0]
    assert row2["status"] == facc.STATUS_WIRED
    assert row2["status"] != facc.STATUS_PROVEN


# ── (b) the invariant/drift gates from all prior waves stay green ────────────

def test_prior_wave_invariant_and_drift_gates_stay_green(rig):
    # Wave 1 — the decision registry validates (every record North-Star
    # traced, rationale-doc'd, machine-readable, wave-consumed).
    assert fd.validate_decisions() == []

    # Waves 9/10 — anti-theater + 2nd-surface honesty on the live modules.
    assert fgui.anti_theater_check() == []
    assert fgw.second_surface_honesty() == []
    # ...and the NEW acceptance module is held to the same standard: a pure
    # read surface — no mutation primitive, no parallel store.
    src = Path(facc.__file__).read_text(encoding="utf-8")
    assert fgui.anti_theater_check(source_text=src, module=facc) == []

    # Wave 11 — the safety invariants on the live tree.
    import foundry_safety as fsafety
    assert fsafety.recheck_fail_deadly()["retired"] is True
    assert fsafety.reaper_is_native_builtin()["native"] is True
    assert sr.concurrency_budget() >= 1

    # Waves 5/6 — the drift gates green on a graph a REAL scaffold op just
    # mutated (map + lock regenerated together by the engine, never by hand).
    res = _create(rig, "gates-w12")
    assert res["ok"] is True, res["reason"]
    doc = fm.load_map(rig["map"])
    gates = fmg.run_drift_gates(doc, lock_path=rig["lock"],
                                root=rig["skills_root"])
    assert gates["ok"] is True, gates
    assert [g["gate"] for g in gates["gates"]] == [
        fmg.GATE_SCHEMA, fmg.GATE_LOCK, fmg.GATE_TARGETS]

    # ...and the supply-chain gate: a signed lock verifies; a tampered lock
    # fails loudly.
    text = rig["lock"].read_text(encoding="utf-8")
    sig = fmg.sign_lock_text(text, key="w12-secret")
    assert fmg.gate_supply_chain(text, sig=sig, key="w12-secret")["ok"] is True
    tampered = text + "\n# tampered\n"
    assert fmg.gate_supply_chain(tampered, sig=sig,
                                 key="w12-secret")["ok"] is False


# ── the page wiring: the scorecard strip on /foundry, honest by default ──────

def test_acceptance_panel_wiring_on_the_foundry_page(rig):
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    # Every DONE= clause renders as a scorecard row.
    assert 'data-acceptance="north-star-scorecard"' in page
    for cid in facc.clause_ids():
        assert 'data-clause="%s"' % cid in page, cid
    # The single open item is on the page, targeting the declared interface.
    assert 'data-acceptance-open-item="foundry.sleep_session"' in page
    assert fgw.SLEEP_PENDING_REASON in page
    # An unarmed, unsynced rig renders the HONEST not-accepted state — the
    # scorecard never flatters.
    assert 'data-accepted="false"' in page

    # The embed goes through the acceptance module (one render path)...
    gsrc = (_ROOT / "foundry_gui.py").read_text(encoding="utf-8")
    assert "import foundry_acceptance as _facc" in gsrc
    assert "_facc.render_acceptance_panel(" in gsrc
    # ...and the Anchor launch entry point (Wave 9) still serves this page.
    src = (_ROOT / "anchor_gui.py").read_text(encoding="utf-8",
                                              errors="replace")
    assert '_path_only == "/foundry"' in src
    assert "window.open('/foundry','_blank')" in src
