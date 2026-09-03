"""Anchor durability (2026-07 review) — Waves 1 + 2.

Wave 1 — re-launchable job specs: an ``interrupted`` job must be re-launchable
in ONE call from its durable record: ``launch()`` persists a complete
``relaunch_spec`` on the job record (seam env seeds only — never the full
environment; ``project_id`` / ``folder_path`` carried per the approved
2026-07-02 amendment), and ``relaunch(job_id)`` starts an equivalent job from
disk state alone THROUGH ``launch_guarded()`` — the concurrency policy and
project-metadata propagation apply to a relaunch exactly as to a first launch —
linking the two records both ways. ``reconcile_on_startup()`` still only
RECONCILES — it never auto-relaunches.

Wave 2 — durable gate answers: answering a gate must not require the original
process's live stdin pipe. Marking a gate ALSO writes a durable
``<jobs_dir>/<job_id>.gate.json``; ``answer_gate()`` on a DEAD job records the
answer and returns ``{ok, deferred}`` instead of failing; ``relaunch()``
delivers a recorded answer exactly once (appended to the seed prompt) and
carries an unanswered question to the new job id; ``load_pending_prompt()``
prefers the durable gate file when the record path yields nothing post-restart.

Wave 3 — Gandalf in-progress boot reconcile: no perpetual "running" gandalf
row after a restart. ``gandalf.reconcile_dangling_runs()`` upserts every
``in_progress`` index row with no live run (not in ``_ACTIVE_RUNS``, no
RUNNING-alive session-registry record) to an honest terminal record
(``failed / interrupted-by-restart``); the server boot path wires it for every
registered project right after ``job_runner.reconcile_on_startup()``.

Hermetic: temp ``ANCHOR_DATA_DIR``, ``ANCHOR_RUNNER_CMD`` → the deterministic
``tests/fake_claude.py`` mock — never real claude / node / port 8777.
"""
import importlib
import json
import os
import sys
import threading
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Point the indirection at the deterministic mock — never live claude.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    yield job_runner
    job_runner._reset_live_table_for_tests()


# ── AC1: the record carries a complete relaunch_spec ─────────────────────────

def test_launch_persists_complete_relaunch_spec_field_by_field(runner, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outdir = tmp_path / "out"
    outdir.mkdir()
    rec = runner.launch(
        "research",
        cwd=str(proj),
        env={"FAKE_CLAUDE_LINES": "1", "SECRET_TOKEN": "hush"},
        backend="claude",
        prompt="seed prompt",
        output_dir=str(outdir),
        gated=False,
        permission_mode="plan",
    )
    runner.wait(rec["job_id"], timeout=30)

    persisted = runner.load_record(rec["job_id"])
    spec = persisted.get("relaunch_spec")
    # Complete, field by field, against the launch args — and ONLY the seam
    # env seed is kept (the secret never reaches the durable record).
    assert spec == {
        "lane": "research",
        "cwd": str(proj),
        "prompt": "seed prompt",
        "output_dir": str(outdir),
        "gated": False,
        "permission_mode": "plan",
        "backend": "claude",
        "expected_artifacts": [],
        "env_keys": {"FAKE_CLAUDE_LINES": "1"},
        # A direct (unguarded) launch has no policy context to persist.
        "project_id": None,
        "folder_path": None,
    }


def test_guarded_launch_spec_carries_project_metadata(runner, tmp_path):
    """A launch_guarded() job's spec carries the policy context (amendment)."""
    folder = tmp_path / "guardproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-1", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "1"},
        backend="claude", prompt="guarded seed",
    )
    runner.wait(rec["job_id"], timeout=30)

    spec = runner.load_record(rec["job_id"])["relaunch_spec"]
    assert spec["project_id"] == "proj-1"
    assert spec["folder_path"] == str(folder)
    assert spec["lane"] == "research"
    assert spec["prompt"] == "guarded seed"


def test_relaunch_spec_env_seed_keeps_only_runner_seam_vars(runner):
    seed = runner._relaunch_env_seed({
        "ANCHOR_RUNNER_CMD": "python fake.py",
        "STUB_THING": "1",
        "FAKE_CLAUDE_LINES": "2",
        "ANCHOR_GANDALF_HOST_CMD": "python host.py",
        "AWS_SECRET_ACCESS_KEY": "nope",
        "PATH": "C:/bin",
    })
    assert seed == {
        "ANCHOR_RUNNER_CMD": "python fake.py",
        "STUB_THING": "1",
        "FAKE_CLAUDE_LINES": "2",
        "ANCHOR_GANDALF_HOST_CMD": "python host.py",
    }


# ── AC2: relaunch() on an interrupted record runs to DONE with links ─────────

def test_relaunch_interrupted_runs_to_done_and_links_both_ways(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "4"},
                        prompt="carry on")
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    # Simulate a restart-orphaned job (the reconcile outcome).
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    out = runner.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    assert new_id != jid
    assert out["relaunch_of"] == jid

    final = runner.wait(new_id, timeout=30)
    assert final["status"] == runner.STATUS_DONE
    # The seam env seed drove the stub: the relaunched job replayed the spec.
    assert runner._lines_from_log(new_id) == [f"fake-line {i}" for i in range(4)]
    # Links persisted both ways on disk.
    assert runner.load_record(jid)["relaunched_as"] == new_id
    assert runner.load_record(new_id)["relaunch_of"] == jid


def test_relaunch_propagates_project_metadata_via_launch_guarded(runner, tmp_path):
    """Amendment: a relaunch re-drives launch_guarded with the spec's policy
    context, so the NEW record is stamped project_id/folder_path exactly like a
    first guarded launch (and its own spec carries them forward)."""
    folder = tmp_path / "metaproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-meta", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "2"}, prompt="carry meta")
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    out = runner.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    final = runner.wait(new_id, timeout=30)
    assert final["status"] == runner.STATUS_DONE
    # Project metadata propagated onto the new record (launch_guarded stamp)…
    new_rec = runner.load_record(new_id)
    assert new_rec["project_id"] == "proj-meta"
    assert new_rec["folder_path"] == str(folder)
    # …and into the new record's own spec, so a relaunch-of-a-relaunch works.
    assert new_rec["relaunch_spec"]["project_id"] == "proj-meta"
    assert new_rec["relaunch_spec"]["folder_path"] == str(folder)


def test_relaunch_applies_concurrency_policy_same_lane_busy(runner, tmp_path):
    """Amendment: the same-lane serialization refuses a relaunch exactly as it
    would a first launch — as an honest string reason, never an exception."""
    folder = tmp_path / "busyproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-busy", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    # Occupy the (project, lane) slot with a live job.
    holder = runner.launch_guarded(
        "research", project_id="proj-busy", folder_path=folder,
        cwd=str(folder),
        env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    try:
        out = runner.relaunch(jid)
        assert out["ok"] is False
        assert out["reason"] == runner.REFUSED_SAME_LANE
        assert out["holder"] == holder["job_id"]
        # The refused relaunch minted nothing and linked nothing.
        assert "relaunched_as" not in runner.load_record(jid)
    finally:
        runner.cancel(holder["job_id"])


# ── AC3: honest refusals ─────────────────────────────────────────────────────

def test_relaunch_refuses_running_then_cancelled(runner):
    rec = runner.launch("research",
                        env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    jid = rec["job_id"]
    out = runner.relaunch(jid)
    assert out["ok"] is False
    assert isinstance(out["reason"], str)
    assert out["reason"].startswith(runner.RELAUNCH_REASON_NOT_INTERRUPTED)
    assert runner.STATUS_RUNNING in out["reason"]

    runner.cancel(jid)
    out = runner.relaunch(jid)
    assert out["ok"] is False
    assert runner.STATUS_CANCELLED in out["reason"]


def test_relaunch_refuses_done(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "1"})
    runner.wait(rec["job_id"], timeout=30)
    out = runner.relaunch(rec["job_id"])
    assert out["ok"] is False
    assert runner.STATUS_DONE in out["reason"]


def test_relaunch_refuses_unknown_id(runner):
    out = runner.relaunch("no-such-job")
    assert out == {"ok": False, "reason": runner.RELAUNCH_REASON_UNKNOWN}


def test_relaunch_refuses_legacy_record_without_spec(runner):
    runner._write_record({"job_id": "legacy-1",
                          "status": runner.STATUS_INTERRUPTED})
    out = runner.relaunch("legacy-1")
    assert out == {"ok": False, "reason": "no-relaunch-spec"}


# ── reconcile_on_startup: unchanged contract, no auto-relaunch ───────────────

def test_reconcile_returns_ids_and_never_auto_relaunches(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    # Rewind the record to "running" with the (now-dead) pid — the restart shape.
    runner._update_record(jid, status=runner.STATUS_RUNNING)

    changed = runner.reconcile_on_startup()
    assert changed == [jid]
    assert runner.load_record(jid)["status"] == runner.STATUS_INTERRUPTED
    # No auto-relaunch: no new job record appeared, and nothing links back.
    records = runner.list_records()
    assert len(records) == 1
    assert all("relaunch_of" not in r for r in records)


# ═════════════════════════════════════════════════════════════════════════════
# Wave 2 — durable gate answers
# ═════════════════════════════════════════════════════════════════════════════

W2_PROMPT = {
    "tool_use_id": "toolu_w2_gate_01",
    "question_index": 0,
    "question": "Which datastore should the registry use?",
    "header": "Store",
    "options": [
        {"label": "JSON files", "description": "Structured JSON"},
        {"label": "SQLite", "description": "Embedded DB"},
    ],
    "multiSelect": False,
}


class _Sink:
    """Thread-safe in-memory stdin sink standing in for a process's stdin."""

    def __init__(self):
        self.writes = []
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self.writes.append(data)

    def flush(self):
        pass


@pytest.fixture
def gatemods(tmp_path, monkeypatch):
    """(job_runner, gate_adapter) reloaded against a temp data dir + the mock."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import gate_adapter
    importlib.reload(gate_adapter)
    yield job_runner, gate_adapter
    job_runner._reset_live_table_for_tests()


# ── AC1: marking a gate writes the durable gate file; survives reload ────────

def test_mark_awaiting_writes_durable_gate_file(gatemods):
    jr, ga = gatemods
    rec = jr.launch("plan", env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)

    p = ga.gate_file_path(jid)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["job_id"] == jid
    assert data["prompt"] == W2_PROMPT
    assert data["answered"] is False
    assert isinstance(data["asked_at"], float)
    jr.wait(jid, timeout=30)


def test_pending_prompt_survives_module_reload_from_disk_state(gatemods):
    """Post-restart shape: the job reconciles to INTERRUPTED (which hides the
    record's prompt per GATE-2) and every in-memory table is gone — a fresh
    import reading ONLY disk state still finds the pending question via the
    durable gate file."""
    jr, ga = gatemods
    rec = jr.launch("plan", env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)
    jr.wait(jid, timeout=30)
    # The restart shape: record says running, process is gone → interrupted.
    jr._update_record(jid, status=jr.STATUS_RUNNING)
    assert jr.reconcile_on_startup() == [jid]
    assert jr.load_record(jid)["status"] == jr.STATUS_INTERRUPTED

    # Fresh import — clears the sink registry and any module-level state.
    import gate_adapter
    fresh = importlib.reload(gate_adapter)
    loaded = fresh.load_pending_prompt(jid)
    assert loaded is not None
    assert loaded["question"] == "Which datastore should the registry use?"
    assert loaded["tool_use_id"] == "toolu_w2_gate_01"


# ── AC2: answering a DEAD job defers; relaunch delivers exactly once ─────────

def test_answer_gate_dead_job_defers_and_persists(gatemods):
    jr, ga = gatemods
    rec = jr.launch("plan", prompt="build the thing",
                    env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)
    jr.wait(jid, timeout=30)
    jr._update_record(jid, status=jr.STATUS_INTERRUPTED)

    out = ga.answer_gate(jid, "JSON files")
    assert out["ok"] is True
    assert out["deferred"] is True

    gate = ga.load_gate_file(jid)
    assert gate["answered"] is True
    assert gate["answer"] == "JSON files"
    assert isinstance(gate["answered_at"], float)
    assert not gate.get("delivered_at")  # recorded, NOT yet delivered


def test_relaunch_delivers_recorded_answer_exactly_once(gatemods):
    jr, ga = gatemods
    rec = jr.launch("plan", prompt="build the thing",
                    env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)
    jr.wait(jid, timeout=30)
    jr._update_record(jid, status=jr.STATUS_INTERRUPTED)
    assert ga.answer_gate(jid, "JSON files")["deferred"] is True

    out = jr.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    assert jr.wait(new_id, timeout=30)["status"] == jr.STATUS_DONE

    # The stub runner's received prompt (persisted verbatim into the new
    # record's own relaunch_spec) carries the recovered answer as context.
    new_prompt = jr.load_record(new_id)["relaunch_spec"]["prompt"]
    assert new_prompt.startswith("build the thing")
    assert "Which datastore should the registry use?" in new_prompt
    assert "JSON files" in new_prompt
    # Delivered-once bookkeeping on the old job's gate file.
    gate = ga.load_gate_file(jid)
    assert gate.get("delivered_at")
    assert gate.get("delivered_to") == new_id

    # A SECOND relaunch of the same interrupted record must NOT re-deliver:
    # the seed prompt comes back unaugmented.
    again = jr.relaunch(jid)
    assert again["ok"] is True
    jr.wait(again["job_id"], timeout=30)
    assert (jr.load_record(again["job_id"])["relaunch_spec"]["prompt"]
            == "build the thing")


def test_relaunch_carries_unanswered_gate_file_to_new_job(gatemods):
    jr, ga = gatemods
    rec = jr.launch("plan", prompt="build the thing",
                    env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)
    jr.wait(jid, timeout=30)
    jr._update_record(jid, status=jr.STATUS_INTERRUPTED)

    # Unanswered → the interrupted job still renders its question (Wave-2
    # fallback: the record path is hidden by GATE-2, the gate file serves it).
    assert ga.load_pending_prompt(jid) == W2_PROMPT

    out = jr.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    jr.wait(new_id, timeout=30)

    # The gate file was CARRIED to the new job id, still unanswered…
    carried = ga.load_gate_file(new_id)
    assert carried is not None
    assert carried["job_id"] == new_id
    assert carried["prompt"] == W2_PROMPT
    assert carried["answered"] is False
    assert carried["carried_from"] == jid
    # …the old copy stops surfacing (stamped carried_to)…
    assert ga.load_gate_file(jid)["carried_to"] == new_id
    assert ga.load_pending_prompt(jid) is None
    # …and the seed prompt was NOT augmented (nothing was answered).
    assert jr.load_record(new_id)["relaunch_spec"]["prompt"] == "build the thing"


# ── AC3: the live path is unchanged (and mirrored into the gate file) ────────

def test_answer_gate_live_job_writes_single_stdin_turn(gatemods):
    jr, ga = gatemods
    rec = jr.launch("plan",
                    env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    jid = rec["job_id"]
    try:
        sink = _Sink()
        ga.register_stdin_sink(jid, sink)
        ga.mark_awaiting_input(jid, W2_PROMPT)

        out = ga.answer_gate(jid, "JSON files")
        assert out["ok"] is True
        assert out["deferred"] is False
        # Exactly ONE stdin turn — today's live path, unchanged.
        assert len(sink.writes) == 1
        assert "JSON files" in sink.writes[0]
        # The durable gate file mirrors the answer and marks it DELIVERED
        # (the live stdin write IS the delivery — a relaunch never re-delivers).
        gate = ga.load_gate_file(jid)
        assert gate["answered"] is True
        assert gate["answer"] == "JSON files"
        assert gate.get("delivered_at")
        # A second answer no-ops (single-consumer guarantee intact).
        assert ga.answer_gate(jid, "SQLite")["ok"] is False
        assert len(sink.writes) == 1
    finally:
        jr.cancel(jid)


def test_answer_gate_honest_refusals(gatemods):
    jr, ga = gatemods
    # Unknown job id (no record, no gate file).
    out = ga.answer_gate("no-such-job", "x")
    assert out == {"ok": False, "deferred": False, "reason": "unknown",
                   "job_id": "no-such-job"}

    # A CANCELLED job's gate is over — never deferred, honest terminal reason.
    rec = jr.launch("plan",
                    env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    jid = rec["job_id"]
    ga.mark_awaiting_input(jid, W2_PROMPT)
    jr.cancel(jid)
    out = ga.answer_gate(jid, "JSON files")
    assert out["ok"] is False
    assert out["deferred"] is False
    assert out["reason"] == f"terminal:{jr.STATUS_CANCELLED}"

    # An interrupted job WITHOUT any pending question refuses not-awaiting.
    rec2 = jr.launch("plan", env={"FAKE_CLAUDE_LINES": "1"})
    jid2 = rec2["job_id"]
    jr.wait(jid2, timeout=30)
    jr._update_record(jid2, status=jr.STATUS_INTERRUPTED)
    out2 = ga.answer_gate(jid2, "JSON files")
    assert out2["ok"] is False
    assert out2["reason"] == "not-awaiting"


# ═════════════════════════════════════════════════════════════════════════════
# Wave 3 — Gandalf in-progress boot reconcile
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gandalf_env(tmp_path, monkeypatch):
    """(gandalf, session_registry, project folder) against a temp data dir."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import gandalf
    importlib.reload(gandalf)
    proj = tmp_path / "proj"
    proj.mkdir()
    yield gandalf, session_registry, proj


def _plant_running_row(g, folder, pid, run_id):
    """Hand-plant the exact in-progress row ``run_gandalf`` writes up front."""
    g._append_index(str(folder), pid, {
        "schema_version": g.GANDALF_INDEX_SCHEMA_VERSION,
        "run_id": run_id, "ts": 1234.5, "ok": False, "verdict": "",
        "degraded": True, "cross_model": False,
        "report_rel": None, "exec_rel": None, "advisor_rel": None,
        "session_id": run_id, "status": "running", "in_progress": True,
    })


# ── AC1: a dangling in-progress row reconciles to failed/interrupted ─────────

def test_dangling_in_progress_row_reconciles_to_failed(gandalf_env):
    g, _sr, proj = gandalf_env
    _plant_running_row(g, proj, "proj-g", "run-111")

    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 1

    runs = g.list_runs(str(proj), "proj-g")
    assert len(runs) == 1
    row = runs[0]
    assert row["run_id"] == "run-111"
    assert row["status"] == "failed"
    assert row["reason"] == "interrupted-by-restart"
    assert row["in_progress"] is False
    assert row["ok"] is False
    # list_runs shows NO in_progress row anywhere.
    assert not any(r["in_progress"] for r in runs)
    # Idempotent: a second boot reconciles nothing.
    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 0


def test_reconcile_leaves_terminal_rows_alone_and_is_honest_on_absence(gandalf_env):
    g, _sr, proj = gandalf_env
    # No index at all → honest zero, never a raise.
    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 0
    # A terminal (done) row is not touched.
    g._append_index(str(proj), "proj-g", {
        "schema_version": g.GANDALF_INDEX_SCHEMA_VERSION,
        "run_id": "run-done", "ts": 1.0, "ok": True, "verdict": "fine",
        "degraded": False, "cross_model": False,
        "report_rel": "gandalf/run-done/report.md", "exec_rel": None,
        "advisor_rel": None, "session_id": "run-done", "status": "done",
        "in_progress": False,
    })
    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 0
    assert g.list_runs(str(proj), "proj-g")[0]["status"] == "done"


# ── AC2: a row whose run IS in _ACTIVE_RUNS is left untouched ─────────────────

def test_row_with_active_run_is_left_untouched(gandalf_env):
    g, _sr, proj = gandalf_env
    _plant_running_row(g, proj, "proj-g", "run-live")
    with g._ACTIVE_RUNS_LOCK:
        g._ACTIVE_RUNS["run-live"] = {
            "job_id": None, "job_ids": [], "proc": None, "cancelled": False,
            "folder": str(proj), "project_id": "proj-g",
            "index_recorded": False,
        }
    try:
        assert g.reconcile_dangling_runs(str(proj), "proj-g") == 0
        row = g.list_runs(str(proj), "proj-g")[0]
        assert row["status"] == "running"
        assert row["in_progress"] is True
        assert "reason" not in row
    finally:
        with g._ACTIVE_RUNS_LOCK:
            g._ACTIVE_RUNS.pop("run-live", None)


def test_row_with_running_alive_session_record_is_left_untouched(gandalf_env):
    """A RUNNING session-registry record whose PID is verifiably alive (this
    test process) counts as live — the row is NOT reconciled."""
    g, sr, proj = gandalf_env
    _plant_running_row(g, proj, "proj-g", "run-alive")
    sr.register_session(project_id="proj-g", lane="gandalf",
                        status=sr.STATUS_RUNNING, session_id="run-alive",
                        pid=os.getpid())
    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 0
    row = g.list_runs(str(proj), "proj-g")[0]
    assert row["in_progress"] is True
    assert row["status"] == "running"


def test_stale_running_session_record_does_not_block_reconcile(gandalf_env):
    """The restart shape: the prior instance's gandalf session record still says
    RUNNING but carries no live PID (run_gandalf registers without one) — the
    row reconciles, and the stale registry record goes terminal too."""
    g, sr, proj = gandalf_env
    _plant_running_row(g, proj, "proj-g", "run-stale")
    sr.register_session(project_id="proj-g", lane="gandalf",
                        status=sr.STATUS_RUNNING, session_id="run-stale")

    assert g.reconcile_dangling_runs(str(proj), "proj-g") == 1
    row = g.list_runs(str(proj), "proj-g")[0]
    assert row["status"] == "failed"
    assert row["reason"] == "interrupted-by-restart"
    assert sr.get_session("run-stale")["status"] == sr.STATUS_FAILED


# ── AC3: the boot wiring reconciles every registered project ─────────────────

@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """(anchor_gui, rnd_registry) reloaded against a temp, fully stubbed env."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")  # OFF in tests
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "summarizer", "report_viewer", "gandalf"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import rnd_registry
    yield gui, rnd_registry


def test_boot_wiring_reconciles_each_registered_project(gui_env, tmp_path,
                                                        monkeypatch):
    gui, rnd = gui_env
    f1 = tmp_path / "p1"
    f1.mkdir()
    f2 = tmp_path / "p2"
    f2.mkdir()
    a = rnd.add_project("P One", str(f1), scaffold=False)
    b = rnd.add_project("P Two", str(f2), scaffold=False)

    calls = []

    def spy(folder, pid):
        calls.append((str(folder), str(pid)))
        # __dashboard__ is folded in explicitly (not in the registry); count it 0
        # so the per-registered-project total stays 2.
        return 0 if str(pid) == "__dashboard__" else 1

    # The boot function goes through the module seam anchor_gui uses.
    monkeypatch.setattr(gui._gandalf, "reconcile_dangling_runs", spy)

    assert gui._reconcile_gandalf_boot_runs() == 2
    assert (a["folder_path"], a["id"]) in calls
    assert (b["folder_path"], b["id"]) in calls
    # The synthetic __dashboard__ project is ALSO reconciled — its dangling gandalf
    # rows would otherwise never boot-heal (it is not in the registry).
    assert any(pid == "__dashboard__" for _, pid in calls)


def test_boot_wiring_is_best_effort_per_project(gui_env, tmp_path, monkeypatch):
    """One project's reconcile blowing up must not stop the others (wrapped,
    logged — the boot path never dies on a bad project)."""
    gui, rnd = gui_env
    f1 = tmp_path / "p1"
    f1.mkdir()
    f2 = tmp_path / "p2"
    f2.mkdir()
    a = rnd.add_project("P One", str(f1), scaffold=False)
    b = rnd.add_project("P Two", str(f2), scaffold=False)

    seen = []

    def spy(folder, pid):
        seen.append(str(pid))
        if str(pid) == a["id"]:
            raise RuntimeError("boom")
        # The synthetic __dashboard__ project is folded in explicitly (it is not in
        # the registry, so its dangling gandalf rows would otherwise never
        # boot-reconcile). It contributes 0 here so the per-project count stays 3.
        if str(pid) == "__dashboard__":
            return 0
        return 3

    monkeypatch.setattr(gui._gandalf, "reconcile_dangling_runs", spy)

    assert gui._reconcile_gandalf_boot_runs() == 3
    assert set(seen) == {a["id"], b["id"], "__dashboard__"}
