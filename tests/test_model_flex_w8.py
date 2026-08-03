"""Wave 8 STUB GATE — Model-flexible execution at the skill layer (Pillar C).

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md``
§Wave 8):

  - **#10 (locked decision)** Confirm ``DEFAULT_ENGINE=claude`` on Windows; detect
    ``agy-dispatch`` availability; surface the 5:1 split in the session UI;
    implement HONEST single-subscription fallback — both subs → Claude driver +
    skill-driven Gemini swarm; Claude-only → Claude everywhere, NEVER spawn
    agy/Gemini; Gemini-only → research + Gemini-runnable lanes, plan/build show an
    honest "requires Claude" state. The 5:1 fan-out lives in the SKILLS, not the
    ``job_runner``.

STUB GATE (verbatim from the plan): the engine-selection function, given a
Claude-only host profile, returns a plan that spawns NO gemini/agy process;
given a Gemini-only profile, plan/build resolve to a "requires Claude" status
(not a crash); given both, the default driver is Claude with Gemini available
for swarm.

Pure functions — no PTY, no subprocess, no server. Host-capability profiles are
constructed deterministically (explicit ``profile`` dict, or the
``ANCHOR_CLAUDE_AVAILABLE`` / ``ANCHOR_GEMINI_AVAILABLE`` env seams). Never
touches the live ``:8777`` service or real data.
"""
import importlib

import pytest


@pytest.fixture
def lanes(monkeypatch):
    # Clear the host-capability env seams so each test sets its own profile.
    monkeypatch.delenv("ANCHOR_CLAUDE_AVAILABLE", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_AVAILABLE", raising=False)
    import job_runner
    importlib.reload(job_runner)
    import lanes as _lanes
    importlib.reload(_lanes)
    return _lanes


BOTH = {"claude": True, "gemini": True}
CLAUDE_ONLY = {"claude": True, "gemini": False}
GEMINI_ONLY = {"claude": False, "gemini": True}
NEITHER = {"claude": False, "gemini": False}

TRIO_LANES = ("research", "plan", "build")


# ── DEFAULT_ENGINE = claude (confirm) ─────────────────────────────────────────

def test_default_engine_is_claude(lanes):
    assert lanes.DEFAULT_BACKEND == lanes.BACKEND_CLAUDE == "claude"


# ── STUB GATE #1: both subscriptions → Claude driver + Gemini swarm ──────────

def test_both_default_driver_is_claude_with_gemini_swarm(lanes):
    for lane in TRIO_LANES:
        plan = lanes.select_engine_plan(lane, profile=BOTH)
        assert plan["status"] == lanes.ENGINE_STATUS_OK
        assert plan["driver"] == "claude"          # Claude is the default driver
        assert plan["swarm"] == "gemini"           # Gemini available for the swarm
        assert plan["swarm_ratio"] == lanes.SWARM_RATIO == "5:1"
        assert plan["spawns_gemini"] is True       # the swarm is available


# ── STUB GATE #2: Claude-only → NO gemini/agy process spawned ────────────────

def test_claude_only_spawns_no_gemini_on_any_lane(lanes):
    for lane in TRIO_LANES + ("general",):
        plan = lanes.select_engine_plan(lane, profile=CLAUDE_ONLY)
        assert plan["status"] == lanes.ENGINE_STATUS_OK
        assert plan["driver"] == "claude"
        # The keystone honesty invariant: never cross-call to agy/Gemini.
        assert plan["spawns_gemini"] is False
        assert plan["swarm"] is None


# ── STUB GATE #3: Gemini-only → plan/build "requires Claude" (no crash) ──────

def test_gemini_only_plan_build_require_claude(lanes):
    for lane in ("plan", "build"):
        plan = lanes.select_engine_plan(lane, profile=GEMINI_ONLY)
        assert plan["status"] == lanes.ENGINE_STATUS_REQUIRES_CLAUDE
        assert plan["driver"] is None
        assert plan["spawns_gemini"] is False
        assert "requires Claude" in plan["reason"]


def test_gemini_only_research_runs_on_gemini(lanes):
    for lane in ("research", "general"):
        plan = lanes.select_engine_plan(lane, profile=GEMINI_ONLY)
        assert plan["status"] == lanes.ENGINE_STATUS_OK
        assert plan["driver"] == "gemini"
        assert plan["spawns_gemini"] is True


def test_neither_is_unavailable_not_a_crash(lanes):
    for lane in TRIO_LANES:
        plan = lanes.select_engine_plan(lane, profile=NEITHER)
        assert plan["status"] == lanes.ENGINE_STATUS_UNAVAILABLE
        assert plan["driver"] is None
        assert plan["spawns_gemini"] is False


# ── Host-capability detection via the env seams (agy-dispatch detection) ─────

def test_detect_host_profile_honors_env_overrides(lanes, monkeypatch):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "0")
    prof = lanes.detect_host_profile()
    assert prof["claude"] is True and prof["gemini"] is False
    assert prof.get("grok") is False

    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    prof = lanes.detect_host_profile()
    assert prof["claude"] is False and prof["gemini"] is True


def test_select_engine_plan_falls_back_to_detected_profile(lanes, monkeypatch):
    # No explicit profile → detect from the env seams (Gemini-only host here).
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    plan = lanes.select_engine_plan("build")
    assert plan["status"] == lanes.ENGINE_STATUS_REQUIRES_CLAUDE
    plan = lanes.select_engine_plan("research")
    assert plan["driver"] == "gemini" and plan["status"] == lanes.ENGINE_STATUS_OK


# ── UI: the session UI surfaces the split + the honest fallback states ────────

def _badge(monkeypatch, claude, gemini):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1" if claude else "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1" if gemini else "0")
    import lanes as _lanes
    importlib.reload(_lanes)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui.render_model_flex_badge()


def test_badge_both_shows_the_5to1_split(monkeypatch):
    html = _badge(monkeypatch, claude=True, gemini=True)
    assert "mflex-both" in html
    assert "5:1" in html
    assert "Claude driver" in html


def test_badge_claude_only_state(monkeypatch):
    html = _badge(monkeypatch, claude=True, gemini=False)
    assert "mflex-claude" in html
    assert "Claude only" in html


def test_badge_gemini_only_shows_requires_claude(monkeypatch):
    html = _badge(monkeypatch, claude=False, gemini=True)
    assert "mflex-gemini" in html
    assert "require Claude" in html or "requires Claude" in html


def test_project_window_header_carries_the_badge(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes as _lanes
    importlib.reload(_lanes)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    proj = rnd_registry.add_project("MFlex", str(folder))
    html = gui.render_project_window_html(proj["id"])
    assert "class='mflex mflex-both'" in html
    assert "5:1" in html
    # f-string integrity: no leaked doubled braces from the render.
    assert "{{" not in html and "}}" not in html
