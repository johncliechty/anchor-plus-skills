"""codex-discipline-2026-09-15 Wave 1.2/1.3 — durable human-first ingress,
interruption, stderr tail (hermetic: fake engine, stub process, tmp state)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402
from steward_cockpit import codex_turn_bridge as ctb  # noqa: E402
import model_policy  # noqa: E402


class _Stdin:
    def __init__(self):
        self.written = []
    def write(self, s):
        self.written.append(s)
    def flush(self):
        pass
    def close(self):
        pass


class _FakeProc:
    def __init__(self):
        self.stdin = _Stdin()
        self.killed = False
    def poll(self):
        return None


@pytest.fixture
def engine(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="steward-ingress-")
    monkeypatch.setattr(eng, "STATE_FILE", Path(tmp) / "state.json")
    e = eng.Engine(tmp, fake=True)
    e.proc = _FakeProc()
    return e


def _sent_text(e, index=-1):
    return json.loads(e.proc.stdin.written[index])["message"]["content"][0]["text"]


# ── origin, resume prefix, durable submitted copy ─────────────────────────

def test_human_message_carries_resume_prefix_once_and_is_durable(engine):
    e = engine
    e._resume_prefix = eng.RESUME_BRIEF
    assert e._send_locked("what is next?", origin="human") is True
    text = _sent_text(e)
    assert text.startswith("(engine resume - not John)")
    assert "JOHN SAYS" in text and text.endswith("what is next?")
    assert e._turn_origin == "human"
    assert e._resume_prefix is None
    assert e._submitted and e._submitted["text"].endswith("what is next?")
    assert eng._read_state_entry(e.skey())["submitted"]["text"].endswith("what is next?")
    # a second human message gets no prefix
    e.busy = False
    e._send_locked("and then?", origin="human")
    assert not _sent_text(e).startswith("(engine resume")


def test_control_prompt_is_never_prefixed_and_never_durable(engine):
    e = engine
    e._resume_prefix = eng.RESUME_BRIEF
    assert e._send_locked(eng.STAND_UP, origin="control") is True
    assert not _sent_text(e).startswith("(engine resume")
    assert e._turn_origin == "control"
    assert e._submitted is None
    assert e._resume_prefix == eng.RESUME_BRIEF  # still waiting for his words


def test_origin_is_explicit_not_inferred_from_a_leading_paren(engine):
    e = engine
    e._resume_prefix = "(engine) context"
    e._send_locked("hi", origin="human")
    # would have been misclassified as control by the old startswith("(") rule
    assert e._turn_origin == "human"


# ── acknowledgement and reconciliation ────────────────────────────────────

def test_first_native_event_acknowledges_the_submitted_copy(engine):
    e = engine
    e._send_locked("hello", origin="human")
    assert e._submitted is not None
    e._handle({"type": "assistant", "message": {"role": "assistant", "content": []}}, e.proc)
    assert e._submitted is None
    assert eng._read_state_entry(e.skey()).get("submitted") is None


def test_error_before_submission_requeues_the_message(engine):
    e = engine
    e._send_locked("hello", origin="human")
    e._handle({"type": "result", "is_error": True, "replay_safe": True,
               "error": {"code": "transport_error", "message": "boom"}}, e.proc)
    assert e.queue[0].endswith("hello")
    assert e._submitted is None


def test_reconcile_always_requeues_with_the_repeat_marker(engine):
    e = engine
    e.cli = "claude"
    entry = {"submitted": {"text": "finish chapter 2", "at": time.time(), "session_id": "abc"}}
    e._reconcile_submitted_locked(entry)
    assert len(e.queue) == 1 and e.queue[0].endswith("finish chapter 2")
    assert e.queue[0].startswith("(possibly a repeat")
    assert eng._read_state_entry(e.skey())["pending_queue"] == e.queue


# ── interruption ──────────────────────────────────────────────────────────

def test_interrupt_records_uncertain_outcome_and_keeps_queue(engine, monkeypatch):
    e = engine
    killed = []
    monkeypatch.setattr(e, "_kill_tree", lambda proc: killed.append(proc))
    monkeypatch.setattr(e, "_journal_routing", lambda **ev: None)
    e._send_locked("(drive - not John) Continue.", origin="control")
    assert e.busy is True
    e.queue.append("his words")
    result = e.interrupt_turn("stopped by John")
    assert result == {"ok": True}
    assert killed and e.busy is False and e.proc is None
    assert e._interrupted["reason"] == "stopped by John" and e._interrupted["origin"] == "control"
    assert eng._read_state_entry(e.skey())["interrupted"]["origin"] == "control"
    assert "his words" in e.queue


def test_interrupt_is_a_no_op_without_a_running_turn(engine):
    assert engine.interrupt_turn("x")["ok"] is False


def test_human_message_ends_a_self_started_turn_and_goes_next(engine, monkeypatch):
    e = engine
    monkeypatch.setattr(e, "_kill_tree", lambda proc: None)
    monkeypatch.setattr(e, "_journal_routing", lambda **ev: None)
    monkeypatch.setattr(e, "_record_conversation", lambda who, text, **kw: True)
    woke = []
    monkeypatch.setattr(e, "_wake_locked", lambda fresh, seed: (woke.append((fresh, seed)) or (True, "awake")))
    e._send_locked("(drive - not John) Continue.", origin="control")
    result = e.say("actually, stop and summarize")
    assert result["ok"] is True and result.get("interrupted") is True
    assert e.queue and e.queue[0] == "actually, stop and summarize"
    assert woke == [(False, None)]
    assert e._interrupted["origin"] == "control"


def test_human_message_during_his_own_turn_just_queues(engine, monkeypatch):
    e = engine
    monkeypatch.setattr(e, "_record_conversation", lambda who, text, **kw: True)
    e._send_locked("first question", origin="human")
    result = e.say("second thought")
    assert result == {"ok": True, "queued": True}
    assert e.busy is True and e.queue == ["second thought"]


# ── stderr tail ───────────────────────────────────────────────────────────

def test_stderr_is_classified_never_forwarded():
    hint = ctb.classify_stderr([
        "ERROR login required: visit https://auth.openai.com/device?code=ABC token=sk-live-secret",
        "connection timed out after 30s",
    ])
    assert hint == {"kinds": ["auth", "network"], "lines": 2}
    assert "sk-live-secret" not in json.dumps(hint)
    assert ctb.classify_stderr(["something odd"]) == {"kinds": ["other"], "lines": 1}


def test_error_result_surfaces_the_diagnostics_kind_in_the_pane(engine):
    e = engine
    seen = []
    e._emit = lambda ev: seen.append(ev)
    e._send_locked("hello", origin="human")
    e._handle({"type": "result", "is_error": True, "replay_safe": False,
               "error": {"code": "transport_error", "message": "Codex exited 1"},
               "stderr_hint": {"kinds": ["auth"], "lines": 3}}, e.proc)
    texts = [ev.get("text", "") for ev in seen if ev.get("t") == "sys"]
    assert any("ended in an error: Codex exited 1 | native diagnostics: auth (3 lines, content withheld)" in t
               for t in texts)


# ── off-thread discovery ──────────────────────────────────────────────────

def test_cached_selection_reports_staleness(monkeypatch):
    model_policy._MEMORY.clear()
    catalog = [{"model": "gpt-6-astra", "efforts": ["high", "ultra"], "rank": 0, "upgrade": None, "evidence": "test"}]
    monkeypatch.setattr(model_policy, "discover", lambda family, env=None: (catalog, "codex"))
    monkeypatch.setattr(model_policy, "_cache_identity", lambda family, env: ("chatgpt", "test"))
    assert model_policy.cached_selection("chatgpt") is None
    fresh = model_policy.resolve("chatgpt", settings={"settings_revision": 8, "model_policy": model_policy.DEFAULT_POLICY})
    cached = model_policy.cached_selection("chatgpt", settings={"settings_revision": 8})
    assert cached["model"] == fresh["model"] == "gpt-6-astra" and cached["stale"] is False
    model_policy._MEMORY[("chatgpt", "test")]["discovered_at"] -= model_policy.CAPABILITY_TTL_SECONDS + 1
    assert model_policy.cached_selection("chatgpt")["stale"] is True
    model_policy._MEMORY.clear()


def test_current_selection_answers_from_a_stale_cache_and_refreshes_off_thread(engine, monkeypatch):
    e = engine
    e.cli = "chatgpt"
    e.model_selection = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra"}
    stale = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra", "stale": True}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: dict(stale))
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("must not probe on the request thread"))
    refreshed = []
    monkeypatch.setattr(e, "_refresh_catalog_async", lambda settings: refreshed.append(settings))
    target, selection = e._current_selection({"settings_revision": 8}, "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-6-astra")
    assert "stale" not in selection
    assert refreshed == [{"settings_revision": 8}]


# ── Grok R1 findings (2026-09-15) ─────────────────────────────────────────

def test_durable_copy_is_his_text_not_the_resume_wrapper(engine):
    """Grok R1 F1: the durability identity is his words, never the wrapper."""
    e = engine
    e._resume_prefix = eng.RESUME_BRIEF
    e._send_locked("finish chapter 2", origin="human")
    assert e._submitted["text"] == "finish chapter 2"
    e._reconcile_submitted_locked({"submitted": dict(e._submitted)})
    assert e.queue and e.queue[0].endswith("finish chapter 2") and e.queue[0].startswith("(possibly a repeat")

def test_ack_from_a_superseded_process_never_touches_the_newer_copy(engine):
    """Grok R1 F2/F6: the old reader passed the proc check, then say()
    interrupted, woke a new process and submitted a new message."""
    e = engine
    old = e.proc
    e._send_locked("first", origin="human")
    new = _FakeProc()
    e.proc = new
    e._submitted = {"text": "second", "at": time.time(), "family": "claude", "session_id": None}
    assert e._ack_submitted(old, {"type": "assistant", "message": {"content": []}}) is False
    assert e._submitted["text"] == "second"
    assert e._ack_submitted(new, {"type": "assistant", "message": {"content": []}}) is True
    assert e._submitted is None


def test_alive_idle_steward_behind_the_barrier_queues_instead_of_a_turn(engine, monkeypatch):
    """Grok R1 F3 (2): say() on an alive, idle steward used to start a turn."""
    from steward_cockpit import maintenance as mt
    e = engine
    monkeypatch.setattr(mt, "is_active", lambda: True)
    monkeypatch.setattr(e, "_record_conversation", lambda who, text, **kw: True)
    result = e.say("after the restart please")
    assert result == {"ok": True, "queued": True, "maintenance": True}
    assert e.queue == ["after the restart please"] and e.proc.stdin.written == []
    assert e._deliver_next_queued_locked() is False and e.queue == ["after the restart please"]
    assert e._wake_locked(False, None) == (False, "maintenance in progress")


def test_interrupt_then_wake_path_respects_the_barrier(engine, monkeypatch):
    """Grok R1 F3 (1): the interrupt -> _wake_locked path bypassed wake()'s guard."""
    from steward_cockpit import maintenance as mt
    e = engine
    monkeypatch.setattr(e, "_kill_tree", lambda proc: None)
    monkeypatch.setattr(e, "_journal_routing", lambda **ev: None)
    monkeypatch.setattr(e, "_record_conversation", lambda who, text, **kw: True)
    e._send_locked("(drive - not John) Continue.", origin="control")
    monkeypatch.setattr(mt, "is_active", lambda: True)
    result = e.say("stop that")
    assert result["ok"] is True and result.get("interrupted") is True
    assert e.proc is None and e.queue == ["stop that"]


def test_no_drive_behind_the_barrier(engine, monkeypatch):
    from steward_cockpit import maintenance as mt
    e = engine
    e.drive = True
    monkeypatch.setattr(mt, "is_active", lambda: True)
    monkeypatch.setattr(e, "_send_locked", lambda *a, **k: pytest.fail("drive must not send"))
    e._maybe_drive_locked()


def test_cache_miss_after_restart_answers_from_last_selection(engine, monkeypatch):
    """Grok R1 F4: a fresh process has an empty catalog cache."""
    e = engine
    e.cli = "chatgpt"
    e.model_selection = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra"}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: None)
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("no probe on the request thread"))
    refreshed = []
    monkeypatch.setattr(e, "_refresh_catalog_async", lambda settings: refreshed.append(settings))
    target, selection = e._current_selection({"settings_revision": 8}, "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-6-astra") and refreshed


def test_dead_login_walks_the_ladder(engine, monkeypatch):
    """Grok R1 F5: a dead subscription login is a capacity loss, not a stale catalog."""
    e = engine
    e.cli = "chatgpt"
    e.model_selection = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra"}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: None)

    def dead(family, **_kw):
        raise model_policy.PolicyUnavailable(family, "CLI discovery exited 1; check subscription login", code="auth_required")
    # the async refresh is what discovers it; make it synchronous here
    monkeypatch.setattr(e, "_refresh_catalog_async", lambda settings: setattr(e, "_unavailable_family", "chatgpt"))
    seen = {}
    monkeypatch.setattr(e, "_select_available_policy",
                        lambda settings, target, excluded=(): seen.update(excluded=tuple(excluded)) or ("claude", {"family": "claude", "model": "best", "effort": "max"}))
    e._current_selection({"settings_revision": 8}, "chatgpt")   # marks the family unavailable
    target, _sel = e._current_selection({"settings_revision": 8}, "chatgpt")
    assert target == "claude" and seen["excluded"] == ("chatgpt",)
    # and discover() tags ONLY an auth-shaped failure (Grok R2 N1)
    monkeypatch.setattr(model_policy.shutil, "which", lambda *a, **k: "C:/fake/codex.exe")
    with pytest.raises(model_policy.PolicyUnavailable) as info:
        model_policy.discover("chatgpt", env={"PATH": ""}, runner=lambda argv, env: (_ for _ in ()).throw(RuntimeError("CLI discovery exited 1; subscription login required")))
    assert info.value.code == "auth_required"
    with pytest.raises(model_policy.PolicyUnavailable) as info:
        model_policy.discover("chatgpt", env={"PATH": ""}, runner=lambda argv, env: (_ for _ in ()).throw(RuntimeError("CLI discovery exited 1; transient or unknown failure")))
    assert info.value.code == "capability_unavailable"


def test_run_classifies_a_nonzero_exit_without_returning_stderr(monkeypatch):
    """Grok R2 N1: a 502 blip is not a dead login; a login failure is."""
    from types import SimpleNamespace
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr=fake_run.stderr)
    monkeypatch.setattr(model_policy.subprocess, "run", fake_run)
    fake_run.stderr = "error: 502 Bad Gateway from upstream https://api.openai.com/x"
    with pytest.raises(RuntimeError) as blip:
        model_policy._run(["codex", "debug", "models"], {})
    assert "transient or unknown failure" in str(blip.value) and "openai.com" not in str(blip.value)
    fake_run.stderr = "You are not logged in. Run `codex login` (token=abc)"
    with pytest.raises(RuntimeError) as dead:
        model_policy._run(["codex", "debug", "models"], {})
    assert "subscription login required" in str(dead.value) and "token=abc" not in str(dead.value)
    # Grok R3 P1: a transient body that merely NAMES the auth host is not a dead login
    fake_run.stderr = "upstream error 503 while contacting https://auth.openai.com/device?code=ABC"
    with pytest.raises(RuntimeError) as blip2:
        model_policy._run(["codex", "debug", "models"], {})
    assert "transient or unknown failure" in str(blip2.value)
    fake_run.stderr = "HTTP 401 Unauthorized"
    with pytest.raises(RuntimeError) as dead2:
        model_policy._run(["codex", "debug", "models"], {})
    assert "subscription login required" in str(dead2.value)


def test_engine_stderr_is_classified_not_forwarded(engine):
    e = engine
    seen = []
    e._emit = lambda ev: seen.append(ev)

    class _P:
        stderr = ["Traceback (most recent call last):\n", "  login required https://x/y?token=abc\n"]
        def poll(self):
            return 1
    p = _P()
    e.proc = p
    e._read_stderr(p)
    text = [ev["text"] for ev in seen if ev.get("t") == "sys"][-1]
    assert text.startswith("engine stderr: ") and "content withheld" in text and "token=abc" not in text
    assert "auth" in text and "panic" in text


def test_in_flight_tracked_between_first_event_and_result(engine):
    """0042: after _ack_submitted clears submitted, in_flight stays durable until result."""
    e = engine
    e._send_locked("launch the next wave", origin="human")
    assert e._submitted is not None and e._in_flight is None
    e._handle({"type": "assistant", "message": {"role": "assistant", "content": []}}, e.proc)
    assert e._submitted is None
    assert e._in_flight is not None and e._in_flight["text"].endswith("launch the next wave")
    assert eng._read_state_entry(e.skey())["in_flight"]["text"].endswith("launch the next wave")
    e._handle({"type": "result", "is_error": False, "result": "done"}, e.proc)
    assert e._in_flight is None
    assert eng._read_state_entry(e.skey()).get("in_flight") is None

