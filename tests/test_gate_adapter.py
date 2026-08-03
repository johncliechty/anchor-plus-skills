"""Wave 5 — gate adapter (in-session answers to AskUserQuestion gates).

AC1: the captured-transcript fixture's AskUserQuestion frame parses into a
     prompt-box record {question, options, tool_use_id} and the job state →
     awaiting-input.
AC2: an awaiting-input job with no attached client — a FRESH client reattaches,
     loads the pending question, submits the answer, and the job advances.
AC3: two concurrent answer POSTs for one tool_use_id → exactly ONE stdin text
     turn is written; the second is no-oped.

NO live ``claude`` is ever invoked. The single stdin write is modeled through a
fake stdin sink (a thread-safe in-memory writer); the job record itself comes
from the real ``job_runner`` driven by the deterministic ``fake_claude.py``.
"""
import importlib
import threading
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate_stream.jsonl"
FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


class FakeSink:
    """Thread-safe in-memory stdin sink — stands in for a process's stdin.

    Records every write so a test can assert EXACTLY ONE stdin turn was written
    under concurrency. Never touches a real process.
    """

    def __init__(self):
        self.writes = []
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self.writes.append(data)

    def flush(self):
        pass


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import gate_adapter
    importlib.reload(gate_adapter)
    yield gate_adapter
    job_runner._reset_live_table_for_tests()


def _launch_awaiting_job(gate_adapter):
    """Launch a fake job, register a fake sink, persist the fixture's gate.

    Returns (job_id, prompt, sink). The job is kept alive briefly via --sleep so
    it stays "running" while we answer the gate.
    """
    import job_runner
    rec = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.5"])
    job_id = rec["job_id"]
    sink = FakeSink()
    gate_adapter.register_stdin_sink(job_id, sink)
    prompt = gate_adapter.ingest_stream(job_id, FIXTURE.read_text(
        encoding="utf-8").splitlines())
    return job_id, prompt, sink


# ── AC1 ──────────────────────────────────────────────────────────────────────

def test_ac1_parse_fixture_produces_prompt_record(gate):
    records = gate.parse_stream(FIXTURE.read_text(encoding="utf-8").splitlines())
    assert len(records) == 1
    rec = records[0]
    # Mandated prompt-box shape: {question, options, tool_use_id}.
    assert rec["tool_use_id"] == "toolu_gate_01"
    assert rec["question"] == "Which datastore should the registry use?"
    assert [o["label"] for o in rec["options"]] == ["JSON files", "SQLite"]
    assert all("description" in o for o in rec["options"])
    assert rec["multiSelect"] is False


def test_ac1_ingest_sets_state_awaiting_input(gate):
    import job_runner
    rec = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "0.4"])
    job_id = rec["job_id"]
    prompt = gate.ingest_stream(job_id, FIXTURE.read_text(
        encoding="utf-8").splitlines())
    assert prompt["tool_use_id"] == "toolu_gate_01"

    persisted = job_runner.load_record(job_id)
    assert persisted["state"] == gate.STATE_AWAITING_INPUT
    assert persisted["pending_prompt"]["tool_use_id"] == "toolu_gate_01"
    assert persisted["gate_consumed"] is False
    job_runner.wait(job_id, timeout=30)


def test_ac1_non_gate_event_yields_nothing(gate):
    # An ordinary assistant text event is not a gate.
    assert gate.parse_event(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    ) == []
    # The init line carries the session_id but is not a gate.
    assert gate.session_id_from_stream(
        FIXTURE.read_text(encoding="utf-8").splitlines()) == "gate-session-7f3a"


# ── AC2 ──────────────────────────────────────────────────────────────────────

def test_ac2_fresh_client_reattaches_loads_and_answers(gate):
    job_id, prompt, sink = _launch_awaiting_job(gate)
    # Simulate "no attached client": forget the in-memory sink, as a fresh
    # process/client would have. The pending prompt is still persisted on disk.
    gate._drop_stdin_sink(job_id)

    # A FRESH client reattaches — it only knows the job_id, loads the pending
    # question from the persisted record (not from any in-memory state).
    loaded = gate.load_pending_prompt(job_id)
    assert loaded is not None
    assert loaded["question"] == "Which datastore should the registry use?"
    assert loaded["tool_use_id"] == "toolu_gate_01"

    # The reattaching client re-establishes the session sink, then answers.
    reattach_sink = FakeSink()
    gate.register_stdin_sink(job_id, reattach_sink)
    result = gate.answer(job_id, "JSON files")
    assert result.written is True

    # Exactly one stdin turn was written, and the job advanced off awaiting-input.
    assert len(reattach_sink.writes) == 1
    advanced = gate._jr.load_record(job_id)
    assert advanced["state"] != gate.STATE_AWAITING_INPUT
    assert advanced["gate_consumed"] is True
    # And the pending prompt no longer surfaces to a client.
    assert gate.load_pending_prompt(job_id) is None
    gate._jr.wait(job_id, timeout=30)


def test_ac2_answer_by_tool_use_id(gate):
    # A reattaching client may answer using the tool_use_id it saw in the box.
    job_id, prompt, sink = _launch_awaiting_job(gate)
    result = gate.answer("toolu_gate_01", "SQLite")
    assert result.written is True
    assert result.job_id == job_id
    assert len(sink.writes) == 1
    gate._jr.wait(job_id, timeout=30)


# ── AC3 ──────────────────────────────────────────────────────────────────────

def test_ac3_concurrent_answers_write_exactly_once(gate):
    job_id, prompt, sink = _launch_awaiting_job(gate)

    barrier = threading.Barrier(8)
    results = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()  # maximize the race window
        r = gate.answer("toolu_gate_01", "JSON files")
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # EXACTLY ONE consumer wrote a stdin turn; all others no-oped.
    written = [r for r in results if r.written]
    assert len(written) == 1, f"expected exactly one writer, got {len(written)}"
    # And the fake sink saw EXACTLY ONE stdin text turn (the single-consumer
    # guarantee at the I/O boundary, not just the record).
    assert len(sink.writes) == 1
    # The no-ops report a benign reason, not a crash.
    for r in results:
        if not r.written:
            assert r.reason in ("already-consumed", "not-awaiting")
    gate._jr.wait(job_id, timeout=30)


def test_ac3_second_sequential_answer_is_noop(gate):
    job_id, prompt, sink = _launch_awaiting_job(gate)
    first = gate.answer(job_id, "JSON files")
    second = gate.answer(job_id, "SQLite")
    assert first.written is True
    assert second.written is False
    assert second.reason in ("already-consumed", "not-awaiting")
    assert len(sink.writes) == 1
    gate._jr.wait(job_id, timeout=30)


# ── GATE-1: answer-by-tool_use_id resolves to the fresh awaiting job ──────────

def test_gate1_shared_tool_use_id_resolves_to_awaiting_not_consumed(gate):
    """Two jobs ingest a gate sharing one tool_use_id; the first is already
    consumed (answered), the second is freshly awaiting. answer(tool_use_id, …)
    must resolve to and write the stdin turn for the AWAITING job — never the
    stale/consumed one — and the consumed job must NOT receive a second write."""
    import job_runner

    # Job A — older, gets answered first so its gate is consumed.
    rec_a = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.5"])
    job_a = rec_a["job_id"]
    sink_a = FakeSink()
    gate.register_stdin_sink(job_a, sink_a)
    gate.ingest_stream(job_a, FIXTURE.read_text(encoding="utf-8").splitlines())
    first = gate.answer(job_a, "SQLite")
    assert first.written is True
    assert len(sink_a.writes) == 1
    # After consuming, job A's gate no longer surfaces / matches by tool_use_id.
    assert gate.load_pending_prompt(job_a) is None

    # Job B — newer, freshly awaiting, SAME tool_use_id (toolu_gate_01).
    rec_b = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.5"])
    job_b = rec_b["job_id"]
    sink_b = FakeSink()
    gate.register_stdin_sink(job_b, sink_b)
    gate.ingest_stream(job_b, FIXTURE.read_text(encoding="utf-8").splitlines())

    # Answering by the shared tool_use_id must hit the AWAITING job (B), not A.
    result = gate.answer("toolu_gate_01", "JSON files")
    assert result.written is True
    assert result.job_id == job_b
    assert len(sink_b.writes) == 1
    # The already-consumed job A got NO second write.
    assert len(sink_a.writes) == 1

    # A repeat answer for the same tool_use_id now no-ops (B is consumed too).
    repeat = gate.answer("toolu_gate_01", "SQLite")
    assert repeat.written is False
    assert len(sink_b.writes) == 1

    gate._jr.wait(job_a, timeout=30)
    gate._jr.wait(job_b, timeout=30)


# ── GATE-2: terminal job never surfaces a stale prompt ────────────────────────

def test_gate2_terminal_job_hides_prompt_and_answer_noops(gate):
    """A job marked awaiting-input then cancelled → load_pending_prompt returns
    None (no stale prompt) and answer() no-ops gracefully (no stdin write)."""
    job_id, prompt, sink = _launch_awaiting_job(gate)
    # Sanity: while running + awaiting, the prompt surfaces.
    assert gate.load_pending_prompt(job_id) is not None

    # Cancel the job → runner status becomes terminal (cancelled), while the
    # gate state is still awaiting-input on the record.
    gate._jr.cancel(job_id)
    rec = gate._jr.load_record(job_id)
    assert rec["status"] in gate._jr.TERMINAL_STATUSES

    # GATE-2: the unanswerable prompt must NOT surface for the terminal job.
    assert gate.load_pending_prompt(job_id) is None

    # And answering it no-ops gracefully — no stdin turn written.
    result = gate.answer("toolu_gate_01", "JSON files")
    assert result.written is False
    assert len(sink.writes) == 0
    # Direct-by-job_id answer also no-ops (gate not answerable on a dead session).
    result2 = gate.answer(job_id, "JSON files")
    assert result2.written is False
    assert len(sink.writes) == 0
