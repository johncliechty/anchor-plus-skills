"""Grok as a third terminal backend peer (claude|gemini|grok).

Hermetic pure tests — no network, no real CLI spawn. Stubs ``shutil.which`` /
filesystem for path resolution.
"""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def stack(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # Keep host probes deterministic.
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_CHATGPT_AVAILABLE", "0")

    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import job_runner
    importlib.reload(job_runner)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import anchor_settings
    importlib.reload(anchor_settings)
    return {
        "reg": session_registry,
        "jr": job_runner,
        "lanes": lanes,
        "ts": terminal_session,
        "settings": anchor_settings,
        "home": home,
        "data": data,
    }


def test_valid_backends_include_grok(stack):
    reg = stack["reg"]
    ts = stack["ts"]
    jr = stack["jr"]
    lanes = stack["lanes"]
    assert reg.BACKEND_GROK == "grok"
    assert "grok" in reg.VALID_BACKENDS
    assert "grok" in ts.VALID_BACKENDS
    assert jr.BACKEND_GROK == "grok"
    assert lanes.BACKEND_GROK == "grok"
    # Jobs keep claude default; interactive default is settings (grok).
    assert jr.DEFAULT_BACKEND == "claude"
    assert stack["settings"].DEFAULTS["default_cli"] == "grok"


def test_resolve_engine_cmd_which(stack, monkeypatch):
    ts = stack["ts"]
    fake = str(stack["home"] / "bin" / "grok.exe")

    def _which(name):
        if name == "grok":
            return fake
        return None

    monkeypatch.delenv("ANCHOR_ENGINE_CMD", raising=False)
    monkeypatch.setattr("shutil.which", _which)
    assert ts._resolve_engine_cmd("grok") == fake


def test_resolve_engine_cmd_home_bin(stack, monkeypatch):
    ts = stack["ts"]
    grok_bin = stack["home"] / ".grok" / "bin"
    grok_bin.mkdir(parents=True)
    grok_exe = grok_bin / "grok.exe"
    grok_exe.write_text("", encoding="utf-8")

    monkeypatch.delenv("ANCHOR_ENGINE_CMD", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    resolved = ts._resolve_engine_cmd("grok")
    assert Path(resolved) == grok_exe


def test_resolve_engine_cmd_fallback_name(stack, monkeypatch):
    ts = stack["ts"]
    monkeypatch.delenv("ANCHOR_ENGINE_CMD", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert ts._resolve_engine_cmd("grok") == "grok"


def test_engine_launch_argv_grok_session_flag(stack):
    ts = stack["ts"]
    argv = ts._engine_launch_argv("grok", "grok", "abc-uuid-123")
    assert argv[0] == "grok"
    assert "-s" in argv
    assert "abc-uuid-123" in argv
    # Claude still gets --session-id; gemini gets no pin.
    claude_argv = ts._engine_launch_argv("claude", "claude", "u1")
    assert "--session-id" in claude_argv
    gem_argv = ts._engine_launch_argv("agy", "gemini", "u2")
    assert gem_argv == ["agy"]


def test_check_engine_allowed_grok_on_plan_build(stack):
    lanes = stack["lanes"]
    # Grok allowed everywhere Claude is — no raise on plan/build/research.
    for lane in ("research", "plan", "build", "general"):
        lanes.check_engine_allowed(lane, "grok")
    # Claude still always allowed.
    lanes.check_engine_allowed("build", "claude")
    # Gemini still restricted only by GEMINI_LANES (plan/build currently allowed
    # in GEMINI_LANES for toggle; if a lane is NOT in GEMINI_LANES it raises).
    # Use a lane outside GEMINI_LANES if any; otherwise just prove grok ≠ gemini
    # restriction path by ensuring grok never raises.
    assert "grok" not in getattr(lanes, "GEMINI_LANES", frozenset())


def test_check_engine_allowed_gemini_still_restricted(stack):
    lanes = stack["lanes"]
    # Invent a lane not in GEMINI_LANES to prove restriction still fires for gemini.
    with pytest.raises(lanes.EngineNotAllowedError):
        lanes.check_engine_allowed("not-a-gemini-lane", "gemini")


def test_detect_host_profile_includes_grok(stack):
    lanes = stack["lanes"]
    prof = lanes.detect_host_profile()
    assert "grok" in prof
    assert prof["grok"] is True  # forced via ANCHOR_GROK_AVAILABLE
    assert "claude" in prof and "gemini" in prof


def test_detect_host_profile_grok_probe(stack, monkeypatch):
    lanes = stack["lanes"]
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "")  # force real probe
    # Empty string → _env_override returns None → probe.
    monkeypatch.delenv("ANCHOR_GROK_AVAILABLE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    # No ~/.grok/bin/grok.exe
    prof = lanes.detect_host_profile({"PATH": "", "HOME": str(stack["home"]),
                                      "USERPROFILE": str(stack["home"])})
    assert prof["grok"] is False

    grok_bin = stack["home"] / ".grok" / "bin"
    grok_bin.mkdir(parents=True)
    (grok_bin / "grok.exe").write_text("", encoding="utf-8")
    prof2 = lanes.detect_host_profile({"PATH": "", "HOME": str(stack["home"]),
                                       "USERPROFILE": str(stack["home"])})
    assert prof2["grok"] is True


def test_last_engine_defaults_to_settings(stack):
    ts = stack["ts"]
    # No project pointer → settings default_cli (grok).
    assert ts.last_engine_for_project("no-such-project") == "grok"
    assert ts._default_engine() == "grok"


def test_unknown_backend_error_mentions_grok(stack):
    ts = stack["ts"]
    with pytest.raises(ts.TerminalSessionError) as ei:
        ts._check_engine_allowed("research", "not-an-engine")
    assert "grok" in str(ei.value)
