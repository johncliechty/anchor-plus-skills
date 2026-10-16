"""The conversation -> commission JOIN (steward run-loop W5, 2026-08-06).

commission_session.py is the one place the existing seams meet:
propose -> confirm -> managed session -> run loop -> run record -> ingest
bridge (report + raise) -> hand-back re-arm. These tests drive the join with
every external seam stubbed: the Node bridge via ANCHOR_ECGBERHT_BRIDGE_CMD
(fake_ecgberht_bridge.py — NEVER real Node / a seat call), the session via an
injected start_session_fn, and the PTY via injected read/write fns.

The laws under test are the effort's hard-won ones:
  - the steward NEVER answers the skill's question (write_fn sees only the
    work turn + Enter, nothing after ASKED)
  - a run that stopped is brought home: durable record + ingest call
  - hand-back re-arms WITHOUT sending anything, past the old question
  - a skill with no session lane is refused by name, never half-launched
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import commission_runner as cr
import commission_session as cs


# ── Harness ─────────────────────────────────────────────────────────────────

class InlineThread:
    """A 'thread' that runs the target synchronously on start().

    The watcher normally rides a daemon thread of the service; tests want the
    whole join to finish before asserting, so start() just calls the fn.
    """

    def __init__(self, fn):
        self._fn = fn
        self.daemon = True

    def start(self):
        self._fn()

    def is_alive(self):
        return False


def inline_thread_factory(fn):
    return InlineThread(fn)


class ScriptedPty:
    """read_fn/write_fn pair scripted like a real commissioned session."""

    def __init__(self, chunks, status="running"):
        # chunks: list of strings appended to the stream one poll at a time.
        self.chunks = list(chunks)
        self.stream = ""
        self.status = status
        self.writes = []

    def read_fn(self, session_id, cursor):
        if self.chunks:
            self.stream += self.chunks.pop(0)
        return {"text": self.stream[cursor:], "next": len(self.stream),
                "status": self.status}

    def write_fn(self, session_id, data):
        self.writes.append(data)


def fast_runner_kwargs():
    return {
        "poll_seconds": 0,
        "max_seconds": 30,
        "quiet_seconds": 5,
        "sleep_fn": lambda s: None,
    }


@pytest.fixture()
def bridge_env(tmp_path, monkeypatch):
    """Route commission_session's bridge at the python stub, recording calls."""
    stub = Path(__file__).resolve().parent / "fake_ecgberht_bridge.py"
    rec = tmp_path / "bridge-rec"
    monkeypatch.setenv("ANCHOR_ECGBERHT_BRIDGE_CMD",
                       f'"{sys.executable}" "{stub}"')
    monkeypatch.setenv("FAKE_BRIDGE_DIR", str(rec))
    return rec


def bridge_calls(rec_dir):
    f = Path(rec_dir) / "calls.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]


def fake_start_session(project_id, lane, backend="claude", label="",
                       seed_context=None, lean_worktree=True, **_kw):
    return {
        "session_id": "sess-t1",
        "pid": 4242,
        "proc_create_time": 123.456,
        "backend": backend,
        "command": ["claude"],
        "worktree_path": "C:/wt/sess-t1",
        "seed_context": seed_context,
        "lane": lane,
    }


PROPOSAL = {
    "kind": "commission_proposal",
    "requires_confirm": True,
    "proposal_id": "prop-1",
    "step_id": "s1",
    "skill": "Crucible",
    "step": {"name": "Order the syllabus decisions", "done_when": "locked"},
}


# ── Propose ─────────────────────────────────────────────────────────────────

def test_propose_crosses_the_bridge_on_stdin(tmp_path, bridge_env):
    out = cs.propose(str(tmp_path), step_id="s1")
    assert out["ok"] is True
    assert out["requires_confirm"] is True
    calls = bridge_calls(bridge_env)
    assert calls[0]["mode"] == "propose-active"
    assert calls[0]["payload"]["project"] == str(tmp_path)
    assert calls[0]["payload"]["step_id"] == "s1"


# ── The join: confirm -> launch -> drive -> record -> ingest ────────────────

def test_confirm_and_launch_drives_to_asked_and_brings_it_home(tmp_path, bridge_env):
    pty = ScriptedPty([
        "\u2713 Crucible loaded \u2014 what would you like to do?",
        "",  # runner sends the work turn here
        "Reading the project\u2026 ",
        "Here are 8 ordered decisions. Which of the three revamp options "
        "do you want as the North Star? I will stop here until you decide.",
    ])

    out = cs.confirm_and_launch(
        str(tmp_path), PROPOSAL,
        project_id="proj-1",
        directive="Aim at the syllabus decisions first.",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True, out
    assert out["session_id"] == "sess-t1"
    assert out["lane"] == "plan"
    assert out["watching"] is True

    # The work turn went in as TYPE then ENTER, and NOTHING after the question
    # — the steward never answers on John's behalf.
    assert len(pty.writes) == 2
    assert pty.writes[0].startswith("Begin the commissioned work now")
    assert pty.writes[1] == "\r"

    # Durable run record: outcome asked, report from the ingest bridge.
    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "asked"
    assert rec["ran"] is True
    assert rec["skill"] == "Crucible"
    assert rec["watch_count"] == 1
    # The composed brief is durable on the record — the pulse tile reads it.
    assert rec["directive"] == "Aim at the syllabus decisions first."
    assert "North Star" in rec["transcript_tail"]
    assert rec["report"]["needs"] == "Which option?"
    assert rec["raised"] is True

    # The seam saw confirm THEN ingest-run, with the transcript riding stdin.
    modes = [c["mode"] for c in bridge_calls(bridge_env)]
    assert modes == ["confirm", "ingest-run"]
    ingest = bridge_calls(bridge_env)[1]["payload"]
    assert ingest["run"]["outcome"] == "asked"
    assert "North Star" in ingest["run"]["transcript"]
    assert ingest["run"]["session_id"] == "sess-t1"


def test_skill_without_a_session_lane_is_refused_by_name(tmp_path, bridge_env):
    # (2026-08-06 hardening) Gandalf/Jumper now commission via the general
    # lane; only a skill with NO path at all refuses.
    prop = {**PROPOSAL, "skill": "legal-beagle"}
    out = cs.confirm_and_launch(
        str(tmp_path), prop, project_id="p",
        start_session_fn=fake_start_session,
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is False
    assert out["error"] == "skill_has_no_session_lane"
    assert cs.load_run_record(str(tmp_path), "sess-t1") is None, \
        "a refused commission must not leave a run record"


def test_confirm_failure_stops_everything(tmp_path, bridge_env):
    (Path(bridge_env)).mkdir(parents=True, exist_ok=True)
    (Path(bridge_env) / "fail-confirm").write_text("x")
    out = cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is False
    assert cs.load_run_record(str(tmp_path), "sess-t1") is None


# ── Hand it back: watch-only re-arm ─────────────────────────────────────────

def test_rearm_watch_snaps_past_the_old_question_and_sees_produced(tmp_path, bridge_env):
    # First: a run that stopped at ASKED (record on disk).
    pty = ScriptedPty([
        "greeting", "", "Which option do you want? I will stop here until you answer.",
    ])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert cs.load_run_record(str(tmp_path), "sess-t1")["outcome"] == "asked"

    # John answered IN the session; new output continues the same stream.
    pty.chunks = [
        "",  # the snap read — cursor moves past everything already on screen
        "Good \u2014 locking option 2. Working\u2026 ",
        "Wrote MASTER-PLAN.md with 6 stages.",
    ]
    out = cs.rearm_watch(
        str(tmp_path), "p", "sess-t1",
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True

    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "produced"
    assert rec["watch_count"] == 2
    # The re-armed watch NEVER typed anything into the session.
    assert len(pty.writes) == 2, "watch-only must not write"

    # And the old question was NOT re-classified: the transcript the ingest saw
    # starts after the snap.
    ingest_payloads = [c["payload"] for c in bridge_calls(bridge_env)
                      if c["mode"] == "ingest-run"]
    assert "Which option do you want" not in ingest_payloads[-1]["run"]["transcript"]


def test_rearm_unknown_session_refused(tmp_path, bridge_env):
    out = cs.rearm_watch(str(tmp_path), "p", "nope")
    assert out["ok"] is False
    assert out["error"] == "unknown_run"


# ── watch_only in the runner itself ─────────────────────────────────────────

def test_runner_watch_only_never_writes_and_classifies_new_output_only():
    pty = ScriptedPty([
        "old question? I will stop here until you answer.",
        "new work \u2014 wrote handback.json",
    ])
    result = cr.run_commissioned_session(
        "s", "SHOULD NEVER BE SENT",
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        watch_only=True,
        poll_seconds=0, max_seconds=10, quiet_seconds=5,
        sleep_fn=lambda s: None,
    )
    assert pty.writes == []
    assert result["outcome"] == cr.RUN_PRODUCED
    assert "old question" not in result["transcript"]


def test_runner_watch_only_dead_session_is_died():
    def read_dead(sid, cursor):
        return {"text": "", "next": 0, "status": "dead"}
    result = cr.run_commissioned_session(
        "s", "x", read_fn=read_dead, write_fn=lambda *a: None,
        watch_only=True, poll_seconds=0, max_seconds=5,
        sleep_fn=lambda s: None,
    )
    assert result["outcome"] == cr.RUN_DIED


def test_runner_prelaunch_death_is_launch_failure_not_died():
    """0082: dead before the greeting, zero output, work turn never sent, seconds
    of life = the ENGINE failed at launch — a distinct loud outcome, because the
    cure ('fix the engine CLI/auth first') differs from died's ('see what the
    session was doing'). Three blind relaunch cycles burned ~80 min on W11."""
    def read_dead(sid, cursor):
        return {"text": "", "next": 0, "status": "dead"}
    result = cr.run_commissioned_session(
        "s", "x", read_fn=read_dead, write_fn=lambda *a: None,
        poll_seconds=0, max_seconds=5, sleep_fn=lambda s: None,
    )
    assert result["outcome"] == cr.RUN_LAUNCH_FAILURE
    assert result["sent_work_turn"] is False


def test_runner_death_after_output_stays_died():
    """A session that SAID something before dying is 'died', never launch_failure
    — the discriminator is zero transcript + unsent work turn, not just speed."""
    calls = {"n": 0}
    def read_then_die(sid, cursor):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"text": "✓ crucible loaded — what would you like to do?",
                    "next": 10, "status": "alive"}
        return {"text": "", "next": 10, "status": "dead"}
    result = cr.run_commissioned_session(
        "s", "do the work", read_fn=read_then_die, write_fn=lambda *a: None,
        poll_seconds=0, max_seconds=5, sleep_fn=lambda s: None,
    )
    assert result["outcome"] == cr.RUN_DIED


# ── Listings stay SAFE ──────────────────────────────────────────────────────

def test_list_runs_is_safe_and_newest_first(tmp_path, bridge_env):
    pty = ScriptedPty(["greeting", "", "asked? I will stop here until you answer."])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    rows = cs.list_runs(str(tmp_path))
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "sess-t1"
    assert row["outcome"] == "asked"
    assert "worktree_path" not in row
    assert "transcript_tail" not in row
    assert row["report"]["say"]


def test_ingest_bridge_failure_is_a_fact_john_gets(tmp_path, bridge_env):
    (Path(bridge_env)).mkdir(parents=True, exist_ok=True)
    (Path(bridge_env) / "fail-ingest-run").write_text("x")
    pty = ScriptedPty(["greeting", "", "asked? I will stop here until you answer."])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "asked"
    assert rec["ingest_error"] == "forced_failure"
    assert "could not read it back" in rec["report"]["say"]


# ── Hardening 2026-08-06: Gandalf/Jumper via the general lane ───────────────

def test_gandalf_commissions_through_general_lane_with_skill_loading_brief(tmp_path, bridge_env):
    """Gandalf has no dedicated lane; the general session's opening turn IS the
    brief, so the brief loads the skill by name. John's step 1 is a Gandalf
    read — without this his first Go refused."""
    captured = {}

    def start(project_id, lane, backend="claude", label="", seed_context=None,
              lean_worktree=True, **_kw):
        captured.update(lane=lane, seed=seed_context)
        return {"session_id": "sess-g1", "pid": 1, "proc_create_time": 1.0,
                "backend": backend, "worktree_path": "C:/wt/g1"}

    prop = {**PROPOSAL, "skill": "Gandalf"}
    pty = ScriptedPty(["Gandalf loaded \u2014 what would you like to do?", "",
                       "Read the drop. Wrote REPORT.md."])
    out = cs.confirm_and_launch(
        str(tmp_path), prop, project_id="p",
        start_session_fn=start,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True, out
    assert out["lane"] == "general"
    assert captured["lane"] == "general"
    assert captured["seed"].startswith("Load the Gandalf skill now")
    assert "COMMISSION BRIEF" in captured["seed"]


# ── Hardening 2026-08-06: campaign state banks itself ───────────────────────

def test_commit_campaign_state_banks_and_is_idempotent(tmp_path):
    (tmp_path / "roadmap.json").write_text("{}")
    eco = tmp_path / ".ecgberht"
    eco.mkdir()
    (eco / "conversation-log.json").write_text("{}")

    first = cs.commit_campaign_state(str(tmp_path), "test")
    # ensure_git_repo's bootstrap commit banks the first state.
    assert first["ok"] is True

    (tmp_path / "roadmap.json").write_text('{"changed": true}')
    second = cs.commit_campaign_state(str(tmp_path), "after change")
    assert second["ok"] is True
    assert second["committed"] is True

    third = cs.commit_campaign_state(str(tmp_path), "no change")
    assert third["ok"] is True
    assert third["committed"] is False
    assert third["reason"] == "nothing-new"


def test_commit_campaign_state_never_raises_on_a_hostile_folder(tmp_path):
    out = cs.commit_campaign_state(str(tmp_path / "does-not-exist"), "x")
    assert isinstance(out, dict)
    assert "ok" in out


# ── Auto-continue (John's standing autonomy rule, 2026-08-07) ───────────────

def _reflection_reply(needs_human):
    return {
        "ok": True,
        "report": {"say": "Run landed.", "produced": ["REPORT.md"], "needs": None},
        "reflection": {
            "impact": "The read reframed step 2.",
            "next": {
                "step_id": "s2", "skill": "researchPrime",
                "directive": "Investigate oral-exam rubrics at 100-student scale.",
                "why": "The rubric gap decides the grade book.",
                "needs_human": needs_human,
                "needs_human_why": None,
            },
            "oranges": [], "fed_steps": [],
        },
        "raised": False,
        "handback": {"ok": True, "ingested": False, "reason": "no_ingestable_handback"},
    }


def _produced_record_and_result():
    record = {"session_id": "sess-a1", "commission_id": "c1", "skill": "Gandalf",
              "step_id": "s1", "lane": "general", "project_id": "proj-1",
              "outcome": "running", "watch_count": 0}
    result = {"outcome": "produced", "ran": True, "elapsed_s": 60,
              "transcript": "verdict text", "transcript_chars": 12}
    return record, result


def test_auto_continue_launches_when_reflection_frees_it(tmp_path, bridge_env, monkeypatch):
    bridge_env.mkdir(parents=True, exist_ok=True)
    (bridge_env / "reply-ingest-run.json").write_text(
        json.dumps(_reflection_reply(needs_human=False)), encoding="utf-8")

    seen = {}

    def fake_confirm(folder, proposal, **kw):
        seen["proposal"] = proposal
        seen["kw"] = kw
        # Mirror the real confirm_and_launch: record_extra lands on the record
        # from birth (the watcher's in-memory copy must carry the chain).
        extra = kw.get("record_extra") or {}
        cs._atomic_write_json(cs._run_record_path(folder, "sess-a2"),
                              {"session_id": "sess-a2", "outcome": "running",
                               **extra})
        return {"ok": True, "session_id": "sess-a2",
                "skill": "researchPrime", "step_id": "s2"}

    monkeypatch.setattr(cs, "confirm_and_launch", fake_confirm)
    record, result = _produced_record_and_result()
    out = cs.finish_run(str(tmp_path), "proj-1", record, result)

    auto = out["record"]["auto_continue"]
    assert auto["launched"] is True, auto
    assert auto["session_id"] == "sess-a2"
    assert auto["auto_chain"] == 1
    # The hop proposed for the reflection's step and carried its directive,
    # confirmed by the standing rule — never a fabricated human click.
    assert seen["proposal"]["skill"] == "researchPrime"
    assert seen["kw"]["directive"].startswith("Investigate oral-exam")
    assert seen["kw"]["who"] == "john-standing-autonomy"
    # The chain depth is durable on the NEW record so the cap is real.
    new_rec = cs.load_run_record(str(tmp_path), "sess-a2")
    assert new_rec["auto_chain"] == 1
    assert new_rec["auto_from"] == "sess-a1"


def test_auto_continue_stops_at_the_chain_cap(tmp_path, bridge_env, monkeypatch):
    bridge_env.mkdir(parents=True, exist_ok=True)
    (bridge_env / "reply-ingest-run.json").write_text(
        json.dumps(_reflection_reply(needs_human=False)), encoding="utf-8")
    monkeypatch.setattr(cs, "confirm_and_launch",
                        lambda *a, **k: pytest.fail("cap must stop the hop"))
    record, result = _produced_record_and_result()
    record["auto_chain"] = cs.AUTO_CHAIN_CAP
    out = cs.finish_run(str(tmp_path), "proj-1", record, result)
    auto = out["record"]["auto_continue"]
    assert auto["launched"] is False
    assert auto["reason"] == "auto-chain-cap"


def test_auto_continue_defers_when_john_is_needed(tmp_path, bridge_env, monkeypatch):
    monkeypatch.setattr(cs, "confirm_and_launch",
                        lambda *a, **k: pytest.fail("needs_human must defer"))
    bridge_env.mkdir(parents=True, exist_ok=True)

    # needs_human true → no hop at all (the directive card asks John).
    (bridge_env / "reply-ingest-run.json").write_text(
        json.dumps(_reflection_reply(needs_human=True)), encoding="utf-8")
    record, result = _produced_record_and_result()
    out = cs.finish_run(str(tmp_path), "proj-1", record, result)
    assert out["record"]["auto_continue"] is None

    # needs_human false but the run did not end clean → back to John.
    (bridge_env / "reply-ingest-run.json").write_text(
        json.dumps(_reflection_reply(needs_human=False)), encoding="utf-8")
    record, result = _produced_record_and_result()
    record["session_id"] = "sess-a3"
    result["outcome"] = "asked"
    out = cs.finish_run(str(tmp_path), "proj-1", record, result)
    auto = out["record"]["auto_continue"]
    assert auto["launched"] is False
    assert auto["reason"] == "outcome-not-produced"


def test_auto_continue_never_repeats_the_same_move(tmp_path, bridge_env, monkeypatch):
    # (Shark round) A stuck model re-proposing the run that JUST finished is
    # the classic burn loop — an identical hop must go to John, never launch.
    reply = _reflection_reply(needs_human=False)
    reply["reflection"]["next"]["step_id"] = "s1"       # same step...
    reply["reflection"]["next"]["skill"] = "Gandalf"    # ...same skill as sess-a1
    bridge_env.mkdir(parents=True, exist_ok=True)
    (bridge_env / "reply-ingest-run.json").write_text(
        json.dumps(reply), encoding="utf-8")
    monkeypatch.setattr(cs, "confirm_and_launch",
                        lambda *a, **k: pytest.fail("same move must not relaunch"))
    record, result = _produced_record_and_result()
    out = cs.finish_run(str(tmp_path), "proj-1", record, result)
    auto = out["record"]["auto_continue"]
    assert auto["launched"] is False
    assert auto["reason"] == "same-move"


def test_watcher_exception_becomes_an_honest_died_run(tmp_path, bridge_env, monkeypatch):
    # (Shark round) A runner exception used to kill the watcher thread
    # silently, stranding the record "running" forever. Now it finishes as a
    # died run: record terminal, watcher_error carried, John raised.
    # (The runner classifies read-errors itself, so target the wrapper: the
    # runner CALL raising is the stranded-thread scenario.)
    def exploding_runner(*a, **k):
        raise RuntimeError("PTY vanished mid-read")

    monkeypatch.setattr(cs._cr, "run_commissioned_session", exploding_runner)
    out = cs.confirm_and_launch(
        str(tmp_path), PROPOSAL,
        project_id="proj-1",
        start_session_fn=fake_start_session,
        read_fn=lambda *a, **k: {"chunk": "", "cursor": 0, "status": "running"},
        write_fn=lambda *a, **k: None,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True, out
    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "died"
    assert "PTY vanished" in rec["watcher_error"]
    modes = [c["mode"] for c in bridge_calls(bridge_env)]
    assert "ingest-run" in modes, "the died run must still be brought home"
