"""codex-discipline Wave 2 S1 (2026-09-17) — attribution: one honest seam, ids on every row.

STUB GATE for the first slice of John's fit contract ("everything should have an
ID that flows back up to the particular project in an AI cockpit so we know how
much is being spent"):

- ``usage_capture.ingest_usage``: a missing price stays ``None`` (never a priced
  $0); states are honest (measured / unpriced / unknown); write-once in the
  ledger AND in the per-project index (a replay repairs, never double counts).
- a delegated job with no project id is attributed to the registered project at
  or above the folder it ran in; a worktree cwd joins at the project folder; a
  job that died before any result is an ``unknown`` row (counted, never
  invisible); a bare launch never becomes an effort pointer record.
- a steward's finalized turn writes one ledger row carrying project_id,
  folder_path, effort_dir, the engine session and the provider's invocation id
  (or a cockpit turn id without a boot epoch); a duplicate final adds nothing;
  steward turns are ledger-only (cockpit state stays their figure).
- the rollup shows delegated jobs as a source of their own, joined by folder,
  with honest states, beside a total the dashboard already reads as the
  steward's figure (never folded in, so nothing is counted twice).
"""
import importlib
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
INVOCATION = "956f7cb6-404f-4cdb-8820-9d6ed2c7d189"
JOB_UUID = "6f5f2f1e-0d8e-4c7c-9a1b-2d3e4f5a6b7c"
OTHER_UUID = "7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))        # never the real sessions store
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    (tmp_path / "sidecars").mkdir(exist_ok=True)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "journal", "usage_ledger", "usage_index", "usage_capture",
                "job_runner", "rnd_registry", "session_registry", "sessions",
                "effort_history", "summarizer", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Attribution", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort)}


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# ── the seam ──────────────────────────────────────────────────────────────────

def test_ingest_usage_keeps_null_cost_derives_states_and_writes_once(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    pid = env["pid"]
    key = uc.turn_key(SESSION, "j1")
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j1",
                           tokens=120, cost_usd=None, project_id=pid,
                           folder_path=env["project"], effort_dir=env["effort"],
                           cli="chatgpt") == 1
    row = ul.ledger_entries(SESSION)[0]
    assert row["cost_usd"] is None
    assert row["usage_state"] == "unpriced"
    assert row["project_id"] == pid and row["effort_dir"] == env["effort"]
    assert row["engine_session_uuid"] == SESSION and row["source"] == "job"
    assert uc.usage_state_for(10, 0.5) == "measured"
    assert uc.usage_state_for(0, 0.42) == "measured"     # a recorded charge is never "unknown"
    assert uc.usage_state_for(10, 0.0) == "unpriced"
    assert uc.usage_state_for(10, None) == "unpriced"
    assert uc.usage_state_for(0, None) == "unknown"
    assert uc.usage_state_for(0, 0.0) == "unknown"
    # write-once: a replay with different figures adds nothing anywhere
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j1",
                           tokens=999, cost_usd=5.0, project_id=pid) == 0
    rows = ui.load_rows(pid)
    assert len(rows) == 1 and rows[0]["tokens"] == 120 and rows[0]["cost_usd"] is None
    assert rows[0]["native_id"] == "j1" and rows[0]["engine_session_uuid"] == SESSION
    assert _same(rows[0]["scope"], env["effort"]) and _same(rows[0]["folder_scope"], env["project"])
    assert len(ul.ledger_entries(SESSION)) == 1


def test_replay_repairs_a_missing_index_row_without_a_second_count(env):
    import usage_capture as uc
    import usage_index as ui
    pid = env["pid"]
    key = uc.turn_key(SESSION, "j2")
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j2",
                           tokens=5, cost_usd=0.1, project_id=pid) == 1
    ui.index_path(pid).unlink()
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j2",
                           tokens=5, cost_usd=0.1, project_id=pid) == 0
    assert len(ui.load_rows(pid)) == 1
    # a torn last line (crash mid-append) is skipped, and the next replay repairs it
    with open(ui.index_path(pid), "a", encoding="utf-8") as fh:
        fh.write('{"key": "torn"')
    assert len(ui.load_rows(pid)) == 1
    assert uc.ingest_usage(SESSION, uc.turn_key(SESSION, "j3"), source=uc.SOURCE_JOB,
                           native_id="j3", tokens=1, cost_usd=0.1, project_id=pid) == 1
    assert [r["native_id"] for r in ui.load_rows(pid)] == ["j2", "j3"]


def test_steward_turns_are_ledger_only(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    pid = env["pid"]
    assert uc.ingest_usage(SESSION, uc.turn_key(SESSION, "t1"), source=uc.SOURCE_STEWARD_TURN,
                           native_id="t1", tokens=50, cost_usd=0.1, project_id=pid) == 1
    assert len(ul.ledger_entries(SESSION)) == 1
    assert ui.load_rows(pid) == []


def test_resolve_project_picks_the_nearest_registered_folder(env):
    import usage_capture as uc
    pid, folder = uc.resolve_project(env["effort"])
    assert pid == env["pid"] and _same(folder, env["project"])
    assert uc.resolve_project(env["project"])[0] == env["pid"]
    assert uc.resolve_project(str(Path(env["project"]).parent)) == (None, None)
    assert uc.resolve_project(None) == (None, None)
    assert uc.resolve_project(env["project"] + "-sibling") == (None, None)


# ── delegated jobs ────────────────────────────────────────────────────────────

def _job_rec(jid, **over):
    rec = {"job_id": jid, "lane": "research", "status": "running", "started_at": 1.0,
           "exit_code": None, "session_id": None, "backend": "claude", "cost": None}
    rec.update(over)
    return rec


def test_job_without_project_is_attributed_by_the_folder_it_ran_in(env):
    import effort_history as eh
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    jid = "job-bare-1"
    envelope = {"type": "result", "session_id": JOB_UUID, "total_cost_usd": 0.42,
                "duration_ms": 5000, "usage": {"input_tokens": 100, "output_tokens": 200}}
    jr._write_record(_job_rec(jid, cwd=env["effort"], metadata_only=True))
    jr._finalize(jid, 0, result_envelope=envelope)
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "job" and row["native_id"] == jid
    assert _same(row["folder_path"], env["project"]) and row["effort_dir"] == env["effort"]
    assert row["usage_state"] == "measured" and row["cost_usd"] == 0.42
    assert row["tokens"] == 300 and row["cli"] == "claude"
    assert row["engine_session_uuid"] == JOB_UUID
    assert row["recorded_at"].endswith("Z")           # the job's own finish time
    entry = ul.ledger_entries(JOB_UUID)[0]
    assert entry["project_id"] == env["pid"] and entry["usage"]["output_tokens"] == 200
    # a bare launch never becomes an effort pointer record (no fake effort on the board)
    for lane in eh.ROLLUP_LANES:
        assert eh.list_efforts(env["project"], env["pid"], lane) == []
    # a re-finalize (restart replay) counts nothing twice
    jr._finalize(jid, 0, result_envelope=envelope)
    assert len(ui.load_rows(env["pid"])) == 1 and len(ul.ledger_entries(JOB_UUID)) == 1


def test_worktree_job_joins_at_its_project_folder(env):
    """A guarded launch runs in a managed worktree outside the project folder;
    the row must still join the project's spend line (Grok R1 F2)."""
    import job_runner as jr
    import usage_index as ui
    from steward_cockpit import steward_routes
    worktree = str(Path(env["project"]).parent / "wt" / "session-1")
    Path(worktree).mkdir(parents=True)
    jr._write_record(_job_rec("job-wt", cwd=worktree, project_id=env["pid"],
                              folder_path=env["project"]))
    jr._finalize("job-wt", 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "total_cost_usd": 0.2,
        "usage": {"input_tokens": 10, "output_tokens": 10}})
    row = ui.load_rows(env["pid"])[0]
    assert _same(row["effort_dir"], env["project"]) and _same(row["folder_scope"], env["project"])
    r = steward_routes._usage_rollup(env["project"], estate={})
    assert r["jobs"]["count"] == 1 and r["jobs"]["reported_spend"] == 0.2


def test_subscription_job_is_unpriced_and_an_empty_envelope_is_unknown(env):
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    jr._write_record(_job_rec("job-sub", cwd=env["project"]))
    jr._finalize("job-sub", 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "cost_state": "subscription_covered",
        "billing_mode": "subscription", "usage": {"input_tokens": 10, "output_tokens": 5}})
    jr._write_record(_job_rec("job-empty", cwd=env["project"]))
    jr._finalize("job-empty", 0, result_envelope={
        "type": "result", "session_id": OTHER_UUID, "total_cost_usd": 0.0, "usage": {}})
    by_id = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert by_id["job-sub"]["cost_usd"] is None
    assert by_id["job-sub"]["usage_state"] == "unpriced" and by_id["job-sub"]["tokens"] == 15
    assert by_id["job-empty"]["usage_state"] == "unknown" and by_id["job-empty"]["tokens"] == 0
    assert len(ul.ledger_entries(OTHER_UUID)) == 1        # never dropped
    assert ul.ledger_entries(JOB_UUID)[0]["cost_usd"] is None   # never a priced $0


def test_job_that_died_before_any_result_is_counted_as_unknown(env):
    """No envelope, no engine session: the spawn is still known (Grok R1 F4)."""
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    jr._write_record(_job_rec("job-dead", cwd=env["effort"]))
    jr._finalize("job-dead", 1)
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1
    assert rows[0]["native_id"] == "job-dead" and rows[0]["usage_state"] == "unknown"
    assert rows[0]["engine_session_uuid"] is None and rows[0]["cost_usd"] is None
    assert not list(ul.ledger_dir().glob("*.json"))     # nothing to ledger without a session
    jr._finalize("job-dead", 1)                          # replay: still one row
    assert len(ui.load_rows(env["pid"])) == 1
    from steward_cockpit import steward_routes
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["jobs"]["count"] == 1 and r["jobs"]["unknown"] == 1


def test_job_outside_every_registered_project_stays_in_the_ledger_only(env):
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    outside = str(Path(env["project"]).parent / "elsewhere")
    Path(outside).mkdir()
    jr._write_record(_job_rec("job-out", cwd=outside))
    jr._finalize("job-out", 0, result_envelope={
        "type": "result", "session_id": OTHER_UUID, "total_cost_usd": 0.05,
        "usage": {"input_tokens": 1, "output_tokens": 1}})
    entry = ul.ledger_entries(OTHER_UUID)[0]
    assert entry["project_id"] is None and entry["effort_dir"] == outside
    assert ui.load_rows(env["pid"]) == []


# ── steward turns ─────────────────────────────────────────────────────────────

@pytest.fixture
def cockpit(env, monkeypatch, tmp_path):
    import anchor_settings
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings",
                        lambda: {"default_cli": "chatgpt", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = "chatgpt"
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    return engine


def _result(**extra):
    return {"type": "result", "subtype": "success", "session_id": SESSION,
            "usage_invocation_id": INVOCATION,
            "usage": {"input_tokens": 150, "output_tokens": 30, "cached_input_tokens": 90},
            "token_status": "reported", "usage_source": "codex-turn-completed",
            "total_cost_usd": 0.25, "duration_ms": 2000, **extra}


def test_steward_turn_writes_one_attributed_ledger_row(env, cockpit):
    import usage_index as ui
    import usage_ledger as ul
    cockpit.turn_text = "Completed response."
    cockpit._handle(_result(), cockpit.proc)
    rows = [r for r in ul.ledger_entries(SESSION) if r.get("source") == "steward-turn"]
    assert len(rows) == 1
    row = rows[0]
    assert row["native_id"] == INVOCATION and row["project_id"] == env["pid"]
    assert _same(row["folder_path"], env["project"]) and row["effort_dir"] == env["effort"]
    assert row["cli"] == "chatgpt" and row["engine_session_uuid"] == SESSION
    assert row["tokens"] == 180 and row["cost_usd"] == 0.25
    assert row["usage_state"] == "measured" and row["duration_ms"] == 2000
    assert ui.load_rows(env["pid"]) == []          # the state sum stays the steward's figure
    cockpit.turn_text = "Completed response."
    cockpit._handle(_result(), cockpit.proc)      # a duplicate final adds nothing
    assert len(ul.ledger_entries(SESSION)) == 1


def test_unpriced_steward_turn_keeps_cost_null(env, cockpit):
    import usage_ledger as ul
    cockpit.turn_text = "Done."
    cockpit._handle(_result(total_cost_usd=None), cockpit.proc)
    row = ul.ledger_entries(SESSION)[0]
    assert row["cost_usd"] is None and row["usage_state"] == "unpriced"
    assert row["tokens"] == 180


def test_untracked_turn_keys_by_session_and_turn_without_a_boot_epoch(env, cockpit):
    """Claude/Grok results carry no invocation id: the row keys by the cockpit's
    cli:session:turn, which restores across a restart (Grok R1 F6)."""
    import usage_ledger as ul
    ev = _result()
    del ev["usage_invocation_id"]
    cockpit.epoch = 7                                    # a seventh boot of this cockpit
    cockpit.turn_text = "Done."
    cockpit._handle(ev, cockpit.proc)
    row = ul.ledger_entries(SESSION)[0]
    assert row["native_id"] == f"chatgpt:{SESSION}:1"   # cli:session:turn, no epoch
    assert "7" not in row["native_id"].split(":")[2:]


# ── the reader ────────────────────────────────────────────────────────────────

def test_rollup_shows_delegated_jobs_by_folder_beside_the_steward_total(env):
    import usage_capture as uc
    from steward_cockpit import steward_routes
    pid, project, effort = env["pid"], env["project"], env["effort"]
    other_effort = str(Path(project) / "planning" / "eff-2")
    uc.ingest_usage("a1", "k1", source="job", native_id="j1", tokens=1000, cost_usd=0.5,
                    project_id=pid, folder_path=project, effort_dir=effort, cli="claude",
                    duration_ms=4000)
    uc.ingest_usage("a2", "k2", source="job", native_id="j2", tokens=2000, cost_usd=None,
                    project_id=pid, folder_path=project, effort_dir=effort, cli="chatgpt")
    uc.ingest_usage("a3", "k3", source="job", native_id="j3", tokens=0, cost_usd=None,
                    project_id=pid, folder_path=project, effort_dir=other_effort, cli="chatgpt")
    r = steward_routes._usage_rollup(effort, estate={})
    jobs = r["jobs"]
    assert jobs["count"] == 2 and jobs["unknown"] == 0
    assert jobs["tokens"] == 3000 and jobs["reported_spend"] == 0.5
    assert jobs["unpriced_turns"] == 1 and jobs["secs"] == 4
    assert jobs["cost_status"] == "partial" and jobs["token_status"] == "reported"
    assert "$0.50" in jobs["cost_text"] and "ChatGPT subscription" in jobs["cost_text"]
    # the total is what the dashboard already reads as the steward's figure: jobs stay beside it
    assert r["total"]["tokens"] == 0 and r["total"]["reported_spend"] == 0
    whole = steward_routes._usage_rollup(project, estate={})
    assert whole["jobs"]["count"] == 3 and whole["jobs"]["unknown"] == 1
    assert whole["jobs"]["tokens"] == 3000 and whole["jobs"]["token_status"] == "partial"
    empty = steward_routes._usage_rollup(str(Path(project) / "planning" / "eff-3"), estate={})
    assert empty["jobs"]["count"] == 0 and empty["jobs"]["cost_status"] == "unavailable"


def test_rollup_without_any_index_shows_no_jobs(env):
    from steward_cockpit import steward_routes
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["jobs"]["count"] == 0 and r["jobs"]["unknown"] == 0
    assert r["total"]["tokens"] == 0 and r["total"]["cost_status"] == "unavailable"


def test_interrupted_jobs_are_counted_by_every_terminal_writer(env):
    """A dead running job marked interrupted by startup reconciliation or the
    liveness check is still a spawn: one unknown row, never invisible (Grok R2 F9)."""
    import job_runner as jr
    import usage_index as ui
    jr._write_record(_job_rec("job-dead-boot", cwd=env["project"], pid=999998,
                              proc_create_time=1.0))
    jr._write_record(_job_rec("job-dead-live", cwd=env["project"], pid=999997,
                              proc_create_time=1.0))
    jr.reconcile_on_startup()
    assert jr.load_record("job-dead-boot")["status"] == jr.STATUS_INTERRUPTED
    jr.liveness_check("job-dead-live")
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {"job-dead-boot", "job-dead-live"}
    assert all(r["usage_state"] == "unknown" and r["cost_usd"] is None for r in rows.values())
    jr.reconcile_on_startup()                            # replay: nothing new
    assert len(ui.load_rows(env["pid"])) == 2


def test_a_spawn_counted_before_its_result_is_upgraded_not_doubled(env):
    """The liveness check fires while the reader still drains (an unknown row),
    then finalize brings the envelope: one row, measured (Grok R3 F11)."""
    import job_runner as jr
    import usage_index as ui
    from steward_cockpit import steward_routes
    jr._write_record(_job_rec("job-race", cwd=env["effort"], pid=999996, proc_create_time=1.0))
    jr.liveness_check("job-race")                        # dead pid: interrupted, unknown row
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1 and rows[0]["usage_state"] == "unknown"
    jr._finalize("job-race", 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "total_cost_usd": 0.3,
        "usage": {"input_tokens": 5, "output_tokens": 5}})
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1
    assert rows[0]["usage_state"] == "measured" and rows[0]["cost_usd"] == 0.3
    assert rows[0]["engine_session_uuid"] == JOB_UUID
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["jobs"]["count"] == 1 and r["jobs"]["unknown"] == 0 and r["jobs"]["reported_spend"] == 0.3
    # and once known, a later unknown writer (a replayed reconcile) changes nothing
    jr.liveness_check("job-race")
    assert ui.load_rows(env["pid"])[0]["usage_state"] == "measured"
