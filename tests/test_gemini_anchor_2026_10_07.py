"""Gemini in Anchor (John 2026-10-07, "Get Gemini tested and working (fully) in Anchor"): the agy 1.3 model catalog,
launch contract, steward bridge and job adapter. Hermetic: no model is launched."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_policy as mp  # noqa: E402
from steward_cockpit import gemini_turn_bridge as gb  # noqa: E402
from steward_cockpit import steward_engine as se  # noqa: E402

AGY_MODELS = """Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)
gemini-3.8-flash-low\tGemini 3.8 Flash (Low)
gemini-3.1-pro-high\tGemini 3.1 Pro (High)
gemini-3.1-pro-low\tGemini 3.1 Pro (Low)
claude-opus-5-5-high\tClaude Opus 5.5 (High)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""
CONV = "839e3931-a668-499b-8105-c26e60d500b2"


def test_the_agy_catalog_keeps_gemini_only_and_selects_the_newest_at_its_highest_effort():
    rows = mp.normalize_catalog("gemini", {"models": mp.parse_agy_models(AGY_MODELS)})
    assert [r["model"] for r in rows] == ["gemini-3.8-flash", "gemini-3.1-pro"]
    assert rows[0]["efforts"] == ["high", "medium", "low"]
    chosen = mp.select_model("gemini", rows)
    assert (chosen["model"], chosen["effort"]) == ("gemini-3.1-pro", "high")
    assert mp.agy_model_id("gemini-3.8-flash", "high") == "gemini-3.8-flash-high"
    assert mp.agy_model_id("gemini-3.8-flash-high", "low") == "gemini-3.8-flash-high", "an id already carrying its effort is kept"
    assert mp.launch_args({"family": "gemini", "model": "gemini-3.8-flash", "effort": "high"}) == ["--model", "gemini-3.8-flash-high"]


def test_discovery_reads_agy_models():
    seen = []

    def runner(argv, env):
        seen.append(argv[1:])
        return AGY_MODELS
    rows, _ = mp.discover("gemini", env={**os.environ, "PATH": os.environ.get("PATH", "")}, runner=runner) \
        if mp.shutil.which("agy.exe" if os.name == "nt" else "agy") else (None, None)
    if rows is not None:
        assert seen == [["models"]]
        assert rows[0]["model"] == "gemini-3.8-flash"


def test_the_bridge_argv_sends_the_prompt_on_stdin_and_resumes_by_conversation():
    argv = gb.build_argv("agy", model="gemini-3.8-flash", effort="high", permission_mode="bypassPermissions",
                         conversation_id=None)
    assert argv[:5] == ["agy", "--input-format", "stream-json", "--output-format", "stream-json"]
    assert argv[argv.index("--model") + 1] == "gemini-3.8-flash-high"
    assert "--dangerously-skip-permissions" in argv and argv[-1] == "-p="
    resumed = gb.build_argv("agy", model="gemini-3.8-flash", effort="high", permission_mode="plan", conversation_id=CONV)
    assert resumed[resumed.index("--conversation") + 1] == CONV and resumed[resumed.index("--mode") + 1] == "plan"
    line = json.loads(gb.stdin_message("hello\n".encode("utf-8")))
    assert line == {"event": "user", "message": {"role": "user", "content": "hello"}}


def test_the_normalizer_turns_agy_events_into_the_engine_protocol():
    n = gb.GeminiNormalizer("gemini-3.8-flash", "high")
    init = n.accept({"event": "init", "conversation_id": CONV, "init": {"model": "gemini-3.8-flash-high"}})
    assert init[0]["type"] == "system" and init[0]["session_id"] == CONV and init[0]["provider"] == "gemini"
    assert init[0]["model_served"] == "gemini-3.8-flash-high" and init[0]["model_source"] == "cli-recorded"
    text = n.accept({"event": "step_update", "step_update": {"conversation_id": CONV, "step_index": 1,
                     "state": "ACTIVE", "step_type": "agent_response", "text_delta": "PO"}})
    assert text[0]["event"]["delta"] == {"type": "text_delta", "text": "PO"}
    tool = n.accept({"event": "step_update", "step_update": {"conversation_id": CONV, "step_index": 2, "state": "ACTIVE",
                     "step_type": "tool", "tool_name": "view_file",
                     "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": "C:/x/skills/gandalf/SKILL.md"}}}})
    block = tool[0]["message"]["content"][0]
    assert block["type"] == "tool_use" and block["name"] == "view_file" and block["input"]["skill"] == "gandalf"
    assert n.accept({"event": "step_update", "step_update": {"conversation_id": CONV, "step_index": 2, "state": "DONE",
                     "step_type": "tool", "tool_name": "view_file"}}) == [], "one tool event per step"
    n.accept({"event": "step_update", "step_update": {"conversation_id": CONV, "step_index": 3, "state": "ACTIVE",
              "step_type": "agent_response", "text_delta": "NG"}})
    assert n.accept({"event": "result", "result": {"conversation_id": CONV, "status": "SUCCESS", "response": "PONG",
                     "usage": {"input_tokens": 10, "output_tokens": 3, "thinking_tokens": 2, "cache_read_tokens": 4}}}) == []
    result = n.finish(0)
    assert result["is_error"] is False and result["result"] == "PONG" and result["session_id"] == CONV
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 4}


def test_a_failed_agy_turn_is_an_error_and_a_login_failure_says_so():
    n = gb.GeminiNormalizer("gemini-3.8-flash", "high")
    n.accept({"event": "result", "result": {"status": "ERROR", "error": "You are not logged into Antigravity."}})
    result = n.finish(1)
    assert result["is_error"] is True and result["error"]["code"] == "auth_required"


def test_a_resumed_turn_must_stay_in_its_conversation():
    n = gb.GeminiNormalizer("gemini-3.8-flash", "high", resume=CONV)
    try:
        n.accept({"event": "init", "conversation_id": "00000000-0000-0000-0000-000000000000", "init": {}})
    except gb.BridgeError:
        return
    raise AssertionError("an unexpected conversation must be refused")


def test_the_steward_engine_accepts_gemini_as_a_bridge_family():
    src = open(se.__file__, encoding="utf-8").read()
    assert '"gemini": "gemini_turn_bridge.py"' in src
    assert 'if family not in ("claude", "chatgpt", "grok", "gemini"):' in src
    assert 'if self.cli in ("chatgpt", "grok", "gemini"):' in src
    assert se.infer_subscription_cli("gemini") == "gemini"


def test_the_job_adapter_drives_agy_directly(tmp_path):
    adapter = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agy_job_adapter.mjs")
    probe = ("import('file:///" + adapter.replace("\\", "/") + "').then(m => console.log(JSON.stringify("
             "[m.agyArgs({model: 'gemini-3.8-flash-high', readonly: true}), m.flatten('a\\nb\\tc')])))")
    out = subprocess.run(["node", "-e", probe], capture_output=True, text=True, timeout=60)
    args, flat = json.loads(out.stdout)
    assert args == ["--input-format", "stream-json", "--output-format", "stream-json", "--model",
                    "gemini-3.8-flash-high", "--mode", "plan", "-p="]
    assert flat == "a b\tc"


def test_the_drained_restart_counts_steward_code_jobs_and_holds_new_ones(monkeypatch):
    """2026-10-07: the barrier restarted Anchor mid code job (only job_runner records counted)."""
    from steward_cockpit import code_jobs, maintenance, steward_routes
    monkeypatch.setattr(code_jobs, "_busy_read", lambda: {r"c:\dev\anchor": {"job": "J1", "cdir": "x"}})
    assert "code:J1" in steward_routes._running_job_ids()
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    out, code = steward_routes.handle_post("C:/nowhere", "code_job", {"action": "start", "repo": "r", "brief": "b"})
    assert code == 409 and "restart" in out["error"]


def test_evicted_gemini_session_rolls_over_from_durable_history_and_replays_once(tmp_path, monkeypatch):
    """2026-11-18: when an older Gemini conversation UUID is evicted from Antigravity CLI's local cache,
    `agy --conversation <old>` emits a new UUID and triggers 'Gemini resumed an unexpected conversation'.
    The engine must archive the old pointer in `provider_sessions`, clear `session_id`, wake fresh with
    `.ecgberht/conversation-log.json` continuity, and replay the user's message at most once."""
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    effort = tmp_path / "Paper 1"
    ecg = effort / ".ecgberht"
    ecg.mkdir(parents=True)
    (ecg / "conversation-log.json").write_text(
        json.dumps({"turns": [{"role": "john", "text": "Bring Bell software into Anvil", "turn_id": "t1", "at": "2026-11-18T18:37:27+00:00"}]}),
        encoding="utf-8",
    )

    eng = se.Engine(str(effort), fake=False)
    eng.cli = "gemini"
    eng.session_id = CONV
    eng._turn_had_tools = False
    eng._turn_words = "Bring Bell software into Anvil"
    eng._last_submitted = "Bring Bell software into Anvil"
    se._update_state(eng.skey(), {"cli": "gemini", "session_id": CONV, "retain_native_on_resume_failure": True})

    killed = []
    wakes = []

    class _DummyProc:
        def poll(self):
            return None

    eng.proc = _DummyProc()
    monkeypatch.setattr(eng, "_kill_tree", lambda p: killed.append(p))
    monkeypatch.setattr(eng, "_journal_receipt", lambda *a, **kw: None)

    def _fake_wake(*, fresh=False, seed=None, **kw):
        wakes.append({"fresh": fresh, "seed": seed})
        return True, "awake"

    monkeypatch.setattr(eng, "_wake_locked", _fake_wake)

    assert eng._try_gemini_evicted_session_rollover("Gemini resumed an unexpected conversation") is True
    assert len(killed) == 1
    assert len(wakes) == 1
    assert wakes[0]["fresh"] is True
    assert ".ecgberht/conversation-log.json" in wakes[0]["seed"]
    assert "Bring Bell software into Anvil" in wakes[0]["seed"]

    saved = se._read_state_entry(eng.skey())
    assert saved["session_id"] is None
    assert any(r.get("session_id") == CONV and r.get("family") == "gemini" for r in (saved.get("provider_sessions") or []))

    # Never loops a second time on the same evicted UUID
    eng.session_id = CONV
    assert eng._try_gemini_evicted_session_rollover("Gemini resumed an unexpected conversation") is False

    # Universal across Codex, Grok, and Claude evicted/missing session errors as well
    for fam, sid, err_msg in (
        ("chatgpt", "22222222-2222-2222-2222-222222222222", "Codex resumed an unexpected thread"),
        ("grok", "33333333-3333-3333-3333-333333333333", "Grok emitted an unexpected session identity"),
        ("claude", "44444444-4444-4444-4444-444444444444", "No conversation found with session ID"),
    ):
        eng.cli = fam
        eng.session_id = sid
        eng.proc = _DummyProc()
        se._update_state(eng.skey(), {"cli": fam, "session_id": sid, "retain_native_on_resume_failure": True})
        assert eng._try_evicted_native_session_rollover(err_msg) is True
        st_fam = se._read_state_entry(eng.skey())
        assert st_fam["session_id"] is None
        assert any(r.get("family") == fam and r.get("session_id") == sid for r in (st_fam.get("provider_sessions") or []))


def test_proactive_reconcile_evicted_cockpit_sessions_preserves_history_and_skips_no_history(tmp_path, monkeypatch):
    fake_brain = tmp_path / "agy_home" / "brain"
    fake_conv = tmp_path / "agy_home" / "conversations"
    fake_brain.mkdir(parents=True)
    fake_conv.mkdir(parents=True)
    live_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    evicted_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    no_hist_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    (fake_brain / live_uuid).mkdir()
    monkeypatch.setenv("AGY_BRAIN_DIR", str(fake_brain))

    eff_live = tmp_path / "LiveCockpit"
    (eff_live / ".ecgberht").mkdir(parents=True)
    (eff_live / ".ecgberht" / "conversation-log.json").write_text(
        json.dumps({"turns": [{"role": "john", "text": "hello", "turn_id": "1", "at": "2026-11-18T18:00:00+00:00"}]}), encoding="utf-8"
    )
    eff_evicted = tmp_path / "EvictedCockpit"
    (eff_evicted / ".ecgberht").mkdir(parents=True)
    (eff_evicted / ".ecgberht" / "conversation-log.json").write_text(
        json.dumps({"turns": [{"role": "john", "text": "keep working", "turn_id": "2", "at": "2026-11-18T18:05:00+00:00"}]}), encoding="utf-8"
    )
    eff_no_hist = tmp_path / "NoHistoryCockpit"
    eff_no_hist.mkdir(parents=True)

    st_file = tmp_path / "steward-cockpit-state.json"
    st_file.write_text(
        json.dumps({
            str(eff_live): {"cli": "gemini", "session_id": live_uuid},
            str(eff_evicted): {"cli": "gemini", "session_id": evicted_uuid, "retain_native_on_resume_failure": True},
            str(eff_no_hist): {"cli": "gemini", "session_id": no_hist_uuid},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(se, "STATE_FILE", st_file)
    res = se.reconcile_evicted_cockpit_sessions(st_file)
    assert res["ok"] is True and res["repaired_count"] == 1
    assert res["skipped_no_history_count"] == 1
    after = json.loads(st_file.read_text(encoding="utf-8"))
    assert after[str(eff_live)]["session_id"] == live_uuid
    assert after[str(eff_evicted)]["session_id"] is None
    assert after[str(eff_evicted)]["provider_sessions"][0]["session_id"] == evicted_uuid
    assert after[str(eff_no_hist)]["session_id"] == no_hist_uuid


