"""Gandalf tier (regular vs Gandalf-Heavy) — STUB GATE (2026-07-07).

The tile now runs the CANONICAL Gandalf at a chosen tier — nothing reimplemented,
just made available: the tier pins the Claude reasoner seat to the SAME model the
trio's canonical regular/heavy runs use (heavy=claude-fable-5, standard=
claude-opus-4-8) via ANTHROPIC_MODEL on the Stage-A launch env (the seam the
fusion pass already uses), and forwards TRIO_TIER. This is the fix for the shallow
reads (Stage A previously ran on the CLI's default model) + the Heavy option.

Locked acceptance:
  - heavy → every dispatched Stage-A read carries ANTHROPIC_MODEL=claude-fable-5
    + TRIO_TIER=heavy; standard → claude-opus-4-8 + TRIO_TIER=standard;
  - default + invalid tier fall back to standard (Opus);
  - the run record + list_runs projection carry the tier;
  - the tile exposes a "Run Heavy" control wired to gandalfRun(pid,'heavy'), and
    the JS posts the tier.

Hermetic + fully stubbed: temp data dir, ANCHOR_RUNNER_CMD → stub draft,
ANCHOR_GANDALF_HOST_CMD → stub host. NEVER real claude / node / :8777.
"""
import importlib
import sys
import threading
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


@pytest.fixture
def gandalf(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    # A setx-pinned CLAUDE_MODEL must NOT beat the explicit tier choice.
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5")
    # The tier→model env is built BEFORE the mode branch, so it is identical for
    # both modes; assert it on the map-reduce path (draft+host stubs). The agentic
    # path's tier env is covered by test_gandalf_agentic::test_agentic_tier_env.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import gandalf
    yield importlib.reload(gandalf)


@pytest.fixture
def multi_project(tmp_path):
    folder = tmp_path / "proj"
    (folder / "src").mkdir(parents=True)
    (folder / "docs").mkdir()
    (folder / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (folder / "docs" / "x.md").write_text("# doc\n", encoding="utf-8")
    return folder, "pid-tier"


def _spy_launch_env(gandalf, monkeypatch):
    """Install a launch spy; return the list it appends each call's env kwarg to."""
    envs = []
    orig = gandalf._jr.launch

    def spy(*a, **k):
        envs.append(dict(k.get("env") or {}))
        return orig(*a, **k)

    monkeypatch.setattr(gandalf._jr, "launch", spy)
    return envs


# ── tier → the canonical Claude reasoner model on every Stage-A read ─────────

def test_heavy_tier_pins_fable5_reasoner(gandalf, multi_project, monkeypatch):
    folder, pid = multi_project
    envs = _spy_launch_env(gandalf, monkeypatch)
    out = gandalf.run_gandalf(str(folder), pid, tier="heavy")
    assert out["ok"] is True
    assert out["tier"] == "heavy"
    assert envs, "expected at least one dispatched Stage-A read"
    for e in envs:
        assert e.get("ANTHROPIC_MODEL") == "claude-fable-5", \
            "heavy must run the reasoner on Fable-5"
        assert e.get("TRIO_TIER") == "heavy"


def test_standard_tier_pins_opus_reasoner(gandalf, multi_project, monkeypatch):
    folder, pid = multi_project
    envs = _spy_launch_env(gandalf, monkeypatch)
    out = gandalf.run_gandalf(str(folder), pid, tier="standard")
    assert out["ok"] is True
    assert out["tier"] == "standard"
    for e in envs:
        assert e.get("ANTHROPIC_MODEL") == "claude-opus-4-8"
        assert e.get("TRIO_TIER") == "standard"


def test_default_and_invalid_tier_fall_back_to_standard(gandalf, multi_project,
                                                        monkeypatch):
    folder, pid = multi_project
    envs = _spy_launch_env(gandalf, monkeypatch)
    out = gandalf.run_gandalf(str(folder), pid)  # no tier → standard
    assert out["tier"] == "standard"
    assert all(e.get("ANTHROPIC_MODEL") == "claude-opus-4-8" for e in envs)

    envs2 = _spy_launch_env(gandalf, monkeypatch)
    out2 = gandalf.run_gandalf(str(folder), pid, tier="bogus")
    assert out2["tier"] == "standard"
    assert all(e.get("ANTHROPIC_MODEL") == "claude-opus-4-8" for e in envs2)


# ── the run record + projection carry the tier ──────────────────────────────

def test_list_runs_surfaces_tier(gandalf, multi_project):
    folder, pid = multi_project
    gandalf.run_gandalf(str(folder), pid, tier="heavy")
    runs = gandalf.list_runs(str(folder), pid)
    assert runs and runs[0]["tier"] == "heavy"
    # An older record without the field reads as "standard" (never crashes).
    assert gandalf._normalize_tier(None) == "standard"


# ── the tile + the trigger + the JS plumb the tier ──────────────────────────

@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for mod in ("rnd_registry", "gandalf"):
        importlib.reload(importlib.import_module(mod))
    import anchor_gui
    return importlib.reload(anchor_gui)


def test_tile_exposes_run_heavy_control(gui, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    # Empty-runs state → the honest empty tile carries BOTH Run and Run Heavy.
    html = gui._render_layoutd_gandalf_panel(str(folder), "pid-x")
    assert "gandalfRun('pid-x')" in html, "regular Run control missing"
    assert "gandalfRun('pid-x', 'heavy')" in html, "Run Heavy control missing"
    assert "Heavy" in html


def test_trigger_passes_tier_to_run(gui, tmp_path, monkeypatch):
    folder = tmp_path / "proj"
    folder.mkdir()
    seen = {}
    done = threading.Event()

    def fake_run(fp, pid, **kw):
        seen["tier"] = kw.get("tier")
        done.set()
        return {"ok": True}

    monkeypatch.setattr(gui._gandalf, "run_gandalf", fake_run)
    assert gui._trigger_gandalf(str(folder), "pid-x", manual=True, tier="heavy")
    assert done.wait(5), "the gandalf run thread never fired"
    assert seen["tier"] == "heavy"


def test_static_js_posts_tier():
    js = (Path(__file__).resolve().parent.parent
          / "static" / "project-window.js").read_text(encoding="utf-8")
    assert "function gandalfRun(pid, tier)" in js
    assert "tier: tier" in js
