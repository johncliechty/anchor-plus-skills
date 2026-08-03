"""W8 / SC5+SC6 — Multi-engine Investigate + Doctor shared start.

Named tests from IMPLEMENTATION-PLAN Wave 8:
  - test_investigate_three_engines_slim_start
  - test_doctor_shell_before_session
  - test_p6_requires_p5_start_plumbing

Hermetic: tmp ANCHOR_DATA_DIR, stub PTY, never touches live :8777 / real CLIs.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def w8env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    # Grok probe may be true on this host; force for determinism when needed.
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import session_registry
    importlib.reload(session_registry)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield {
        "gui": gui,
        "lanes": lanes,
        "termsess": terminal_session,
        "reg": session_registry,
        "data": tmp_path,
    }


def test_investigate_three_engines_slim_start(w8env):
    gui = w8env["gui"]
    toggle = gui._w8_engine_toggle(
        profile={"claude": True, "gemini": True, "grok": True},
        prefs={"default_cli": "claude"},
    )
    assert [e["id"] for e in toggle["engines"]] == ["claude", "gemini", "grok"]
    assert all(e["enabled"] and e["subscriptionCli"] for e in toggle["engines"])
    assert toggle["engines"][1]["transport"] == "agy"
    assert "grok" in toggle["engines"][2]["spawn"] or toggle["engines"][2]["transport"] == "grok-cli"

    # Dead toggle forbidden — unhealthy disabled with health.
    partial = gui._w8_engine_toggle(
        profile={"claude": True, "gemini": False, "grok": False})
    gem = next(e for e in partial["engines"] if e["id"] == "gemini")
    assert gem["enabled"] is False
    assert "unavailable" in gem["health"].lower()

    slim = gui._w8_build_investigate_slim_seed({
        "pid": 4242,
        "engineClass": "claude",
        "reasonCodes": ["SPEND_POSITIVE", "UNSUPERVISED", "ENGINE_POSITIVE"],
        "name": "claude.exe",
    }, {"classifierMode": "shadow", "freezeCapability": False, "freezeKillEnabled": False})
    assert slim["kind"] == "investigate_slim"
    assert slim["pid"] == 4242
    assert slim["class"] == "claude"
    assert "SPEND_POSITIVE" in slim["topReasonCodes"]
    assert slim["freezeStatus"]
    assert slim["killStatus"]
    assert slim["slim"] is True

    text = gui._w8_format_investigate_slim_seed_text(slim)
    assert "SLIM SEED" in text and "4242" in text

    for eng in ("claude", "gemini", "grok"):
        plan = gui._w8_shared_session_start_plan(
            surface="investigate",
            engine=eng,
            candidate={"pid": 4242, "engineClass": eng,
                       "reasonCodes": ["ENGINE_POSITIVE"]},
        )
        assert plan["shell"]["paintFirst"] is True
        assert plan["shell"]["paintBudgetMs"] <= 1000
        assert plan["shell"]["enginePicker"] is True
        assert len(plan["shell"]["engines"]) == 3
        assert plan["seedBeforeSession"] is True
        assert plan["session"]["async"] is True
        assert plan["session"]["cancelable"] is True
        assert plan["session"]["failureNonBlocking"] is True
        assert plan["session"]["autoStart"] is False
        assert plan["engine"] == eng
        assert plan["canStart"] is True
        assert "SLIM SEED" in plan["seedText"]


def test_doctor_shell_before_session(w8env):
    gui = w8env["gui"]
    plan = gui._w8_shared_session_start_plan(
        surface="doctor",
        engine="claude",
    )
    # Shell paints; session does NOT auto-start.
    assert plan["shell"]["paintFirst"] is True
    assert plan["shell"]["autoStartSession"] is False
    assert plan["session"]["autoStart"] is False
    assert plan["session"]["async"] is True
    assert plan["session"]["failureNonBlocking"] is True
    assert plan["shell"]["enginePicker"] is True
    assert plan["seed"]["kind"] == "doctor_short"

    # Page template must not auto-fetch session_start on load (shell-first).
    # render_doctor_page_html builds from stats; the template constant holds JS.
    # Locate the doctor page template on the module (inline string).
    src = Path(gui.__file__).read_text(encoding="utf-8", errors="replace")
    # Contract markers in the W8 doctor shell JS:
    assert "Shell-first (W8/SC6)" in src or "shell ready" in src.lower()
    assert "runDiagnose" in src
    # Must not auto-call session_start on page load without Diagnose click.
    # The only session_start fetch should be inside runDiagnose.
    assert "window.runDiagnose" in src or "runDiagnose = function" in src
    # Engine picker for three engines present.
    assert "pickDoctorEng('claude')" in src
    assert "pickDoctorEng('gemini')" in src
    assert "pickDoctorEng('grok')" in src

    short = gui._w8_build_doctor_short_seed({
        "issueId": "ZH_SWEEP_ERROR",
        "message": "sweep parse failed",
        "component": "radar",
        "lastError": "control char",
        "suggestedChecks": ["re-run sweep"],
    })
    assert short["issueId"] == "ZH_SWEEP_ERROR"
    assert short["short"] is True


def test_p6_requires_p5_start_plumbing(w8env):
    gui = w8env["gui"]
    p5 = gui._W8_P5_PLUMBING
    assert p5["id"] == "p5-shared-session-start"
    assert p5["version"] == "w8-p5-v1"
    required = set(p5["required"])
    for key in (
        "shared_session_start_helper",
        "shell_before_session",
        "engine_picker_three",
        "slim_seed",
        "async_cancelable_session",
        "failure_non_blocking",
        "first_prompt_budget",
        "doctor_shell_first",
    ):
        assert key in required
    assert p5["engines"] == ["claude", "gemini", "grok"]
    assert "investigate" in p5["surfaces"] and "doctor" in p5["surfaces"]

    # Shared helper exists and stamps P5 on every plan (P6 consumers check this).
    plan = gui._w8_shared_session_start_plan(
        surface="investigate",
        candidate={"pid": 1, "engineClass": "claude", "reasonCodes": ["ENGINE_POSITIVE"]},
    )
    assert plan["p5Plumbing"]["version"] == "w8-p5-v1"
    assert callable(gui._w8_shared_session_start_plan)
    assert callable(gui._w8_build_investigate_slim_seed)
    assert callable(gui.handle_zh_engines)
    assert plan["shell"]["autoStartSession"] is False
