"""Locks the gated-lane stdin wiring (fix design C + D).

A GATED lane (plan/build) must launch with ``stdin=PIPE`` kept open, deliver the
INITIAL prompt as a stream-json user message on that pipe, and register the live
pipe with the gate adapter so an in-session answer writes into the SAME session.
A NON-gated lane (research) keeps the original ``stdin=DEVNULL`` contract.

Driven through the mock (``ANCHOR_RUNNER_CMD`` → fake_claude.py) so no live CLI
is invoked. The mock ignores stdin, so we assert on the Popen wiring + the
gate-adapter sink registration, not on the model's behavior.
"""
import importlib
import subprocess
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import gate_adapter
    importlib.reload(gate_adapter)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    yield job_runner, gate_adapter, rnd_registry, lanes
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _mkproject(rnd_registry, folder, name="P"):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def test_lane_gated_flag_mapping(stack):
    _, _, _, lanes = stack
    assert lanes.lane_gated_flag("research") is False
    assert lanes.lane_gated_flag("plan") == "plan"
    assert lanes.lane_gated_flag("build") == "build"


def test_build_extra_args_dead_flag_emitter_is_gone(stack):
    """The broken flag emitter must NOT exist anymore (root-cause guard)."""
    _, _, _, lanes = stack
    assert not hasattr(lanes, "build_extra_args")


def test_research_lane_uses_devnull_stdin_no_sink(stack, tmp_path):
    job_runner, gate_adapter, rnd_registry, lanes = stack
    proj = _mkproject(rnd_registry, tmp_path / "rf", "R")
    rec = lanes.launch_lane(proj["id"], "research",
                            extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    with job_runner._LIVE_LOCK:
        live = job_runner._LIVE.get(jid)
    # Non-gated → no stdin pipe (DEVNULL) → no gate sink registered by launch.
    if live is not None:
        assert live.proc.stdin is None
    with gate_adapter._SINKS_LOCK:
        assert jid not in gate_adapter._SINKS
    job_runner.wait(jid, timeout=30)


def test_gated_lane_opens_stdin_pipe_and_registers_sink(stack, tmp_path):
    job_runner, gate_adapter, rnd_registry, lanes = stack
    proj = _mkproject(rnd_registry, tmp_path / "pf", "P")
    rec = lanes.launch_lane(proj["id"], "plan",
                            extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]
    with job_runner._LIVE_LOCK:
        live = job_runner._LIVE.get(jid)
    assert live is not None
    # Gated → stdin is a real PIPE (writable), kept open for the answer.
    assert live.proc.stdin is not None
    # launch() registered the live pipe with the gate adapter so answer() can
    # write the continuation turn into the SAME session.
    sink = gate_adapter._get_stdin_sink(jid)
    assert sink is not None
    job_runner.wait(jid, timeout=30)


def test_gate_surfaces_from_live_stream_no_manual_ingest(stack, tmp_path):
    """PRODUCTION-PATH gate wiring (confirmed-blocker regression guard).

    Launch a GATED job whose runner emits a REAL AskUserQuestion stream-json
    frame, then assert ``load_pending_prompt`` returns that prompt WITHOUT any
    manual ``mark_awaiting_input`` / ``ingest_stream`` call. This is the exact
    gap the blocker described: the reader loop never fed the live stream into the
    gate adapter, so the gate was end-to-end dead in production while every prior
    test hand-injected the state and masked the absence. The reader loop now
    surfaces the first gate frame itself.
    """
    job_runner, gate_adapter, rnd_registry, lanes = stack
    rec = job_runner.launch(
        "plan",
        extra_args=["--lines", "1", "--gate", "--sleep", "1.0"],
        gated="plan",
    )
    jid = rec["job_id"]
    # Wait for the reader to drain the gate frame (the --sleep keeps the proc
    # alive a moment, but the gate line is emitted before the sleep). Poll the
    # PRODUCTION read path — NO manual mark_awaiting_input/ingest_stream.
    pending = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        pending = gate_adapter.load_pending_prompt(jid)
        if pending is not None:
            break
        time.sleep(0.05)
    assert pending is not None, (
        "gate never surfaced from the live stream via the production reader loop"
    )
    assert pending.get("tool_use_id") == "toolu_fake_gate_0001"
    assert pending.get("question") == "Which output format?"
    # The job record's gate state was flipped by the reader, not by the test.
    live_rec = job_runner.load_record(jid)
    assert live_rec.get("state") == gate_adapter.STATE_AWAITING_INPUT
    job_runner.wait(jid, timeout=30)


def test_research_lane_never_surfaces_gate_from_stream(stack, tmp_path):
    """A NON-gated (research) lane must NOT acquire gate state even if a frame
    appears in its stream — the reader only parses gates for gated jobs."""
    job_runner, gate_adapter, rnd_registry, lanes = stack
    rec = job_runner.launch(
        "research",
        extra_args=["--lines", "1", "--gate", "--exit-code", "0"],
        gated=False,
    )
    jid = rec["job_id"]
    job_runner.wait(jid, timeout=30)
    # Even though the stream carried an AskUserQuestion frame, a non-gated lane
    # never flips to awaiting-input (the reader skips gate parsing for it).
    assert gate_adapter.load_pending_prompt(jid) is None
    live_rec = job_runner.load_record(jid)
    assert live_rec.get("state") != gate_adapter.STATE_AWAITING_INPUT


def test_gate_answer_emits_stream_json_user_text_turn(stack, tmp_path):
    """answer() writes a stream-json-framed user TEXT turn (role:user, content
    text) — NOT a tool_result (fix design C)."""
    job_runner, gate_adapter, rnd_registry, lanes = stack
    import json

    rec = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.0"],
                            gated="plan")
    jid = rec["job_id"]

    # Capture what answer() writes via a fake sink (overrides the live pipe).
    class Cap:
        def __init__(self):
            self.writes = []

        def write(self, s):
            self.writes.append(s)

        def flush(self):
            pass

    cap = Cap()
    gate_adapter.register_stdin_sink(jid, cap)
    gate_adapter.mark_awaiting_input(jid, {"tool_use_id": "t1",
                                           "question": "Q", "options": []})
    res = gate_adapter.answer(jid, "JSON files")
    assert res.written is True
    assert len(cap.writes) == 1
    env = json.loads(cap.writes[0])
    assert env["type"] == "user"
    assert env["message"]["role"] == "user"
    # A user TEXT turn — content is a text block carrying the choice.
    block = env["message"]["content"][0]
    assert block["type"] == "text"
    assert block["text"] == "JSON files"
    # Definitely NOT a tool_result envelope.
    assert env["type"] != "tool_result"
    assert "tool_use_id" not in env
    job_runner.wait(jid, timeout=30)
