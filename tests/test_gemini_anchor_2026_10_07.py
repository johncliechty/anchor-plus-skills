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
    assert (chosen["model"], chosen["effort"]) == ("gemini-3.8-flash", "high")
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
