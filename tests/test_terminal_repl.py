"""Wave 7 — interactive terminal (stream-json REPL + SSE) acceptance.

Locks the v2 terminal substrate (MASTER-PLAN §E): a PERSISTENT interactive
session built on ``job_runner`` (NOT ConPTY), auto-seeded with the lane skill,
with user turns written onto the live process stdin (reusing — never forking —
the gate-adapter stdin mechanism), output streamed back over SSE, and an
exit→discover→confirm-adopt flow.

Hermetic: NO live ``claude``/``gemini`` — everything is driven through the mock
runner (``ANCHOR_RUNNER_CMD`` → tests/fake_claude.py). The SSE endpoint is bounded
+ heartbeated, so the test reads a finite set of events and the stream ends (it
never hangs on a live indefinite connection).
"""
import importlib
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import gate_adapter
    importlib.reload(gate_adapter)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import lanes
    importlib.reload(lanes)
    import rnd_terminal
    importlib.reload(rnd_terminal)
    yield {
        "jr": job_runner, "gate": gate_adapter, "rnd": rnd_registry,
        "eh": effort_history, "sessions": sessions, "lanes": lanes,
        "term": rnd_terminal,
    }
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


# ── start_terminal: persistent gated session seeded with the lane skill ──────

def test_start_terminal_starts_plan_lane_skill_with_open_stdin(stack, tmp_path):
    term, jr, gate, rnd = stack["term"], stack["jr"], stack["gate"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "pf", "P")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]
    # The plan lane skill is the crucible skill.
    assert rec["skill"] == "crucible"
    assert rec.get("terminal") is True
    # A terminal keeps stdin OPEN so turns can be sent (gated launch → PIPE).
    with jr._LIVE_LOCK:
        live = jr._LIVE.get(jid)
    assert live is not None and live.proc.stdin is not None
    # The gate adapter has the live stdin sink registered (reused, not forked).
    assert gate._get_stdin_sink(jid) is not None
    jr.wait(jid, timeout=30)


def test_each_lane_seeds_its_skill(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    for i, (lane, skill) in enumerate(
            (("research", "researchPrime"), ("plan", "crucible"),
             ("build", "foreman"))):
        proj = _mkproject(rnd, tmp_path / f"f{i}", lane)
        rec = term.start_terminal(proj["id"], lane, extra_args=["--lines", "1"])
        assert rec["skill"] == skill
        jr.wait(rec["job_id"], timeout=30)


# ── send_turn: the turn reaches the live process stdin ───────────────────────

def test_send_turn_writes_stream_json_user_text_to_stdin(stack, tmp_path):
    """Reuses the gated-stdin assertion pattern: a fake sink captures exactly the
    stream-json user TEXT turn send_turn writes (proving it reaches stdin)."""
    term, jr, gate, rnd = stack["term"], stack["jr"], stack["gate"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "pf", "P")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    class Cap:
        def __init__(self):
            self.writes = []

        def write(self, s):
            self.writes.append(s)

        def flush(self):
            pass

    cap = Cap()
    gate.register_stdin_sink(jid, cap)        # override the live pipe with a capture
    assert term.send_turn(jid, "do the next step") is True
    assert len(cap.writes) == 1
    env = json.loads(cap.writes[0])
    assert env["type"] == "user"
    assert env["message"]["role"] == "user"
    assert env["message"]["content"][0]["type"] == "text"
    assert env["message"]["content"][0]["text"] == "do the next step"
    jr.wait(jid, timeout=30)


def test_send_turn_refused_on_terminal_session(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "pf", "P")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)                   # let it exit (terminal)
    assert term.send_turn(jid, "too late") is False


# ── read_since: returns the stubbed assistant output incrementally ───────────

def test_read_since_returns_stubbed_output(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "rf", "R")
    rec = term.start_terminal(proj["id"], "research",
                              extra_args=["--lines", "3", "--exit-code", "0"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)
    out = term.read_since(jid, 0)
    assert "fake-line 0" in out["lines"]
    assert out["status"] in jr.TERMINAL_STATUSES
    # The cursor advances: a second read from `next` returns nothing new.
    out2 = term.read_since(jid, out["next"])
    assert out2["lines"] == []


# ── SSE framing: parse a couple events from term_stream without hanging ──────

def _read_sse_events(url, max_events=6, timeout=15):
    """Read up to ``max_events`` SSE event frames from ``url``. Returns a list of
    (event, data_obj). Stops at a ``done`` event or when max_events is reached —
    the bounded/heartbeat endpoint guarantees the body ends, so this never hangs.
    """
    events = []
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        cur_event = None
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                cur_event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                payload = line[len("data: "):]
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    obj = payload
                events.append((cur_event, obj))
                if cur_event == "done" or len(events) >= max_events:
                    break
    return events


def test_term_stream_sse_well_formed_and_terminates(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    proj = _mkproject(rnd, tmp_path / "sf", "S")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "2", "--exit-code", "0"])
    jid = rec["job_id"]

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # Bounded fast loop so the stream ends quickly (testable without hanging).
        url = (f"http://127.0.0.1:{port}/api/rnd/term_stream?session={jid}"
               f"&poll=0.02&max_ticks=80&hb=3")
        events = _read_sse_events(url, max_events=20, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
        jr.wait(jid, timeout=30)

    names = [e for e, _ in events]
    # SSE framing is well-formed: every event parsed into (name, json-or-str).
    assert events, "no SSE events received"
    # The stubbed assistant output is delivered over the stream.
    out_lines = []
    for ev, obj in events:
        if ev == "output" and isinstance(obj, dict):
            out_lines.extend(obj.get("lines", []))
    assert any("fake-line" in str(x) for x in out_lines)
    # The stream TERMINATES cleanly with a done event (it did not hang).
    assert "done" in names


# ── exit → discover → adopt: produced files become a lane session ────────────

def test_exit_discover_adopt_creates_lane_session(stack, tmp_path):
    term, jr, rnd, sessions = (stack["term"], stack["jr"], stack["rnd"],
                               stack["sessions"])
    proj = _mkproject(rnd, tmp_path / "af", "A")
    pid = proj["id"]
    folder = proj["folder_path"]
    rec = term.start_terminal(pid, "plan", extra_args=["--lines", "1",
                                                       "--exit-code", "0"])
    jid = rec["job_id"]
    out_dir = Path(rec["output_dir"])
    jr.wait(jid, timeout=30)

    # Simulate the engine having produced fixture docs into the session output
    # dir (the mock runner does not write files). discover_produced compares
    # against the pre-run snapshot and proposes only the new files.
    (out_dir / "MASTER-PLAN.md").write_text("# Master Plan\nbody",
                                            encoding="utf-8")
    (out_dir / "IMPLEMENTATION-PLAN.md").write_text("# Impl\nbody",
                                                    encoding="utf-8")

    proposal = term.discover_produced(jid)
    assert proposal is not None and proposal["adoptable"] is True
    rels = sorted(p["rel"] for p in proposal["produced"])
    assert "MASTER-PLAN.md" in rels and "IMPLEMENTATION-PLAN.md" in rels

    # Confirm-adopt → the produced docs become ONE session in the plan lane.
    adopted = term.adopt_produced(jid)
    assert adopted is not None
    plan_sessions = sessions.list_sessions(folder, pid, "planning")
    assert plan_sessions, "no planning session after adopt"
    # The adopted session carries this terminal job_id as a member (run effort).
    found = None
    for s in plan_sessions:
        for m in s.get("member_files", []):
            if m.get("job_id") == jid:
                found = s
                break
    assert found is not None, "adopted run session not grouped under the job_id"
    assert found["provenance"] == "run"


def test_discover_produced_unknown_session_returns_none(stack):
    assert stack["term"].discover_produced("no-such-job") is None


# ── Wave 7 robustness fixes ──────────────────────────────────────────────────

# FIX-FILENAME-ESCAPE: a produced filename with HTML metacharacters round-trips
# escaped in the proposal (display fields) while rel_raw keeps the real path.
def test_discover_produced_escapes_html_metachars_in_proposal(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "esc", "E")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    out_dir = Path(rec["output_dir"])
    jr.wait(jid, timeout=30)
    # A filename containing HTML metacharacters that are ALSO legal on Windows
    # (& and ' are; <, >, " are not). This is enough to prove server-side
    # escaping: rel is escaped, rel_raw is the verbatim on-disk path.
    nasty = "a&b'c.md"
    (out_dir / nasty).write_text("# X\nbody", encoding="utf-8")
    proposal = term.discover_produced(jid)
    assert proposal is not None and proposal["adoptable"] is True
    rec0 = next(p for p in proposal["produced"] if p.get("rel_raw") == nasty)
    # Display rel is HTML-escaped; raw rel is the verbatim on-disk path.
    assert rec0["rel"] == "a&amp;b&#x27;c.md"
    assert "&" not in rec0["rel"].replace("&amp;", "").replace("&#x27;", "")
    assert rec0["rel_raw"] == nasty
    # Adopt resolves the REAL file path (rel_raw), not the escaped display string.
    adopted = term.adopt_produced(jid)
    assert adopted is not None
    member = None
    for m in adopted.get("member_files", []):
        if m.get("job_id") == jid:
            member = m
            break
    assert member is not None
    assert nasty in (member.get("produced_files") or [member.get("artifact_path")]) \
        or member.get("artifact_path") == nasty


# FIX-IDEMPOTENT-ADOPT: adopt_produced called TWICE on the same session yields
# exactly ONE effort/session (no duplicate).
def test_adopt_produced_twice_is_idempotent(stack, tmp_path):
    term, jr, rnd, sessions = (stack["term"], stack["jr"], stack["rnd"],
                               stack["sessions"])
    proj = _mkproject(rnd, tmp_path / "idem", "I")
    pid, folder = proj["id"], proj["folder_path"]
    rec = term.start_terminal(pid, "plan",
                              extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    out_dir = Path(rec["output_dir"])
    jr.wait(jid, timeout=30)
    (out_dir / "MASTER-PLAN.md").write_text("# MP\nbody", encoding="utf-8")

    first = term.adopt_produced(jid)
    assert first is not None
    second = term.adopt_produced(jid)        # adopt the SAME session again
    assert second is not None                # idempotent: still resolves the session

    plan_sessions = sessions.list_sessions(folder, pid, "planning")
    # Exactly ONE session carries this job_id as a member (no duplicate effort).
    matching = [s for s in plan_sessions
                if any(m.get("job_id") == jid
                       for m in s.get("member_files", []))]
    assert len(matching) == 1, (
        "expected exactly one session for the job_id, got %d" % len(matching))
    assert len(matching[0].get("member_files", [])) == 1, \
        "expected exactly one member effort after double-adopt"


# FIX-SEND-TURN-VALIDATION: empty/oversized/dead-stdin turns are rejected cleanly
# (clean False, nothing written, no crash).
def test_send_turn_empty_is_rejected_nothing_written(stack, tmp_path):
    term, jr, gate, rnd = stack["term"], stack["jr"], stack["gate"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "ev", "E")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    class Cap:
        def __init__(self):
            self.writes = []

        def write(self, s):
            self.writes.append(s)

        def flush(self):
            pass

    cap = Cap()
    gate.register_stdin_sink(jid, cap)
    assert term.send_turn(jid, "") is False
    assert term.send_turn(jid, "   \n\t ") is False
    assert cap.writes == [], "empty turn must not write anything to stdin"
    jr.wait(jid, timeout=30)


def test_send_turn_oversized_is_rejected(stack, tmp_path):
    term, jr, gate, rnd = stack["term"], stack["jr"], stack["gate"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "ov", "O")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    class Cap:
        def __init__(self):
            self.writes = []

        def write(self, s):
            self.writes.append(s)

        def flush(self):
            pass

    cap = Cap()
    gate.register_stdin_sink(jid, cap)
    huge = "x" * (term.MAX_TURN_CHARS + 1)
    assert term.send_turn(jid, huge) is False
    assert cap.writes == [], "oversized turn must not write anything to stdin"
    # A turn AT the cap still works (special chars too).
    ok_text = "ünïçødé " + ('y' * (term.MAX_TURN_CHARS - 20)) + " 'q\"\n"
    assert len(ok_text) <= term.MAX_TURN_CHARS
    assert term.send_turn(jid, ok_text) is True
    assert len(cap.writes) == 1
    jr.wait(jid, timeout=30)


def test_send_turn_after_exit_is_clean_false(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "ae", "A")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--exit-code", "0"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)                  # process has exited (terminal)
    # No crash; clean False because the session is terminal / stdin is gone.
    assert term.send_turn(jid, "after exit") is False


def test_send_turn_dead_stdin_is_clean_false(stack, tmp_path):
    """A live session whose stdin sink is closed returns False (no throw)."""
    term, jr, gate, rnd = stack["term"], stack["jr"], stack["gate"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "ds", "D")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    class DeadSink:
        closed = True

        def write(self, s):
            raise ValueError("I/O operation on closed file")

        def flush(self):
            pass

    gate.register_stdin_sink(jid, DeadSink())
    assert term.send_turn(jid, "to a dead pipe") is False
    jr.wait(jid, timeout=30)


# FIX-SSE-BROAD-EXCEPTION: read_since raising mid-stream → the SSE response ends
# with a terminal done/error frame (no hang), proven by monkeypatching read_since.
def test_term_stream_sse_ends_on_read_since_exception(stack, tmp_path,
                                                      monkeypatch):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    proj = _mkproject(rnd, tmp_path / "xf", "X")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "2.0"])
    jid = rec["job_id"]

    # Make the FIRST tick's read_since blow up with a generic exception. The
    # handler imports rnd_terminal as ``_term``; patch the symbol it calls.
    def boom(session_id, cursor=0):
        raise RuntimeError("synthetic read_since failure")

    monkeypatch.setattr(gui._term, "read_since", boom)

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/term_stream?session={jid}"
               f"&poll=0.02&max_ticks=80&hb=3")
        events = _read_sse_events(url, max_events=10, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
        try:
            jr.cancel(jid)
        except Exception:
            pass

    names = [e for e, _ in events]
    # The stream did NOT hang: it terminated with a done frame...
    assert "done" in names, "stream must emit a terminal done on read error"
    # ...and that done frame is error-flavored (status error / error flag).
    done_obj = next(obj for ev, obj in events if ev == "done")
    assert isinstance(done_obj, dict)
    assert done_obj.get("status") == "error" or done_obj.get("error") is True


# FIX-REAP/CANCEL: a started terminal can be cancelled via the cancel helper and
# the job status reflects it (fake_claude kept alive via --sleep).
def test_cancel_terminal_helper_kills_and_marks_cancelled(stack, tmp_path):
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    proj = _mkproject(rnd, tmp_path / "cf", "C")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "30.0"])
    jid = rec["job_id"]
    # Session is live (running) before cancel.
    assert jr.load_record(jid)["status"] == jr.STATUS_RUNNING
    out = term.cancel_terminal(jid)
    assert out is not None
    assert out.get("status") == jr.STATUS_CANCELLED
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED


def test_cancel_terminal_unknown_session_returns_none(stack):
    assert stack["term"].cancel_terminal("no-such-session") is None


def test_cancel_job_endpoint_cancels_terminal_session(stack, tmp_path):
    """The existing /api/rnd/cancel_job endpoint tree-kills a terminal session
    (the tab-close reap path lands here)."""
    term, jr, rnd = stack["term"], stack["jr"], stack["rnd"]
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    proj = _mkproject(rnd, tmp_path / "ce", "C")
    rec = term.start_terminal(proj["id"], "plan",
                              extra_args=["--lines", "1", "--sleep", "30.0"])
    jid = rec["job_id"]

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        body = json.dumps({"job_id": jid}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/cancel_job", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
    assert data.get("ok") is True
    assert data.get("status") == jr.STATUS_CANCELLED
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED
