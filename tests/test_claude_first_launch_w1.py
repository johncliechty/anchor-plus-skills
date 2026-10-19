"""Wave 1 gate — settings-backed session launch defaults.

Originally "Claude-first" (crucible-improve-followup 2026-07-01). Retargeted
2026-07-21: interactive launch defaults come from durable settings
(``default_cli``, schema default ``grok``) — never hard-coded Gemini, and no
longer hard-coded Claude either. Gemini/Claude/Grok are all selectable via the
3-way engine toggle; launch payloads call ``_defaultCli()``.
"""
import importlib
import re
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the render stack against an isolated temp data dir so a rendered
    project window can be produced without touching real data or :8777."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "session_registry", "effort_history",
                "summarizer", "lanes", "terminal_session", "anchor_settings"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


# ── JS launch-default assertions (module-level _PROJECT_WINDOW_JS) ───────────

def test_newtermsession_defaults_via_settings(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "backend = backend || _defaultCli()" in js
    assert "backend = backend || 'gemini'" not in js
    assert "backend = backend || 'claude'" not in js


def test_neweffort_payload_uses_default_cli(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    # The effort_managed launch payload must request the settings default, never
    # a hard-coded gemini (or a hard-coded claude).
    assert "backend: _defaultCli()" in js
    assert "backend: 'gemini'" not in js
    assert "backend: 'claude'" not in js


def test_grass_workbench_default_engine_from_settings(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    # Grass engine init reads _defaultCli() / ANCHOR_DEFAULT_CLI, not a pinned
    # gemini (and no longer a pinned claude).
    assert "_defaultCli" in js
    assert "_grassEngine = 'gemini'" not in js
    # The 3-way cycle includes all three engines as SELECTABLE values.
    assert "'claude', 'gemini', 'grok', 'chatgpt'" in js or \
           "['claude', 'gemini', 'grok', 'chatgpt']" in js


def test_engine_toggle_highlight_defaults_via_settings(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "(s && s.backend) || _defaultCli()" in js
    assert "(s && s.backend) || 'gemini'" not in js
    assert "(s && s.backend) || 'claude'" not in js


def test_no_gemini_launch_default_or_fallback_remains(gui_env):
    """Policy guard: no launch payload / MANAGED fallback / default in the
    project-window JS still pins gemini. (The 3-way toggle button list keeps
    the literal 'gemini' as a SELECTABLE value — that is not a default and is
    matched narrowly here.)"""
    js = gui_env._PROJECT_WINDOW_JS
    assert "|| 'gemini'" not in js, "a gemini launch/fallback default remains"
    assert "backend: 'gemini'" not in js, "a launch payload still pins gemini"


def test_default_cli_helper_present(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "function _defaultCli()" in js
    assert "ANCHOR_DEFAULT_CLI" in js
    # Schema fallback when boot prefs are absent.
    assert "return 'grok'" in js or "|| 'grok'" in js


# ── Rendered project window (Layout-D — the REAL launch controls) ────────────

def test_layoutd_launch_controls_use_settings_default(gui_env, tmp_path):
    """The served project window launches via settings default_cli — no control
    hands a session to gemini by default. newEffort posts backend:_defaultCli();
    newGeneral() without an arg also resolves via _defaultCli()."""
    import rnd_registry
    folder = tmp_path / "Proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Proj", str(folder), scaffold=False)["id"]
    html = gui_env.render_project_window_html(pid)
    # The simple-workbench surface has one General launcher. Trio work is
    # commissioned through Steward, so retired manual lane launchers stay out.
    assert "newEffort('general')" in html
    assert "newEffort('research')" not in html
    assert "newEffort('plan')" not in html
    # ... and no launch control in the served window pins gemini.
    assert "newTermSession('research','gemini')" not in html
    assert "backend: 'gemini'" not in html
    assert "|| 'gemini'" not in html
    # Boot prefs (or globals) expose the settings default for the client.
    assert "ANCHOR_DEFAULT_CLI" in html or "default_cli" in html


# ── Client payloads for promote / continue request settings default ──────────

def test_promote_and_continue_payloads_request_default_cli(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    # promoteGrass + continueSession are NEW sessions; both must request the
    # settings default (not fall through to sticky last_engine, not pin gemini).
    assert re.search(r"idea_id: ideaId, lane: lane,\s*backend: _defaultCli\(\)", js), \
        "promoteGrass payload must request _defaultCli()"
    assert re.search(r"source_session: sessionId,\s*backend: _defaultCli\(\)", js), \
        "continueSession payload must request _defaultCli()"


# ── Regression: interactive default engine tracks settings ───────────────────

def test_backend_default_engine_tracks_settings(gui_env):
    import terminal_session
    import anchor_settings
    # Schema default is grok; DEFAULT_ENGINE mirrors it for import-time readers.
    assert terminal_session.DEFAULT_ENGINE == "grok"
    assert anchor_settings.get_default_cli() == "grok"
    assert "grok" in terminal_session.VALID_BACKENDS


def test_engine_toggle_is_three_way(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "◆ Claude" in js
    assert "✦ Gemini" in js
    assert "✦ Grok" in js


# ── Behavioral: sticky-last_engine LEAK is closed with explicit backend ──────
#
# promote / continue pass an explicit backend so sticky last_engine cannot
# silently re-route a NEW session. These tests set last_engine to gemini and
# prove an explicit backend still wins (using the settings default_cli value).

@pytest.fixture
def live_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "summarizer", "gate_adapter", "terminal_session",
                "anchor_settings"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    import rnd_registry
    proj = rnd_registry.add_project("Leak", str(repo), scaffold=False)
    yield {"pid": proj["id"], "repo": repo}
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_promote_honors_explicit_backend_after_gemini_toggle(live_env):
    import effort_history
    import terminal_session
    import anchor_settings
    pid = live_env["pid"]
    # Simulate a prior per-session Gemini toggle in this project.
    terminal_session.set_last_engine_for_project(pid, "gemini")
    assert terminal_session.last_engine_for_project(pid) == "gemini"
    idea = effort_history.add_idea(live_env["repo"], pid, "an idea to promote")
    idea_id = idea.get("job_id") or idea.get("idea_id") or idea.get("id")
    # Explicit backend (settings default_cli) must win over sticky last_engine.
    want = anchor_settings.get_default_cli()
    rec = effort_history.promote_grass_to_lane(pid, idea_id, "research",
                                               backend=want)
    assert rec.get("backend") == want, \
        "promote must honor explicit backend, not sticky gemini last_engine"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_continue_honors_explicit_backend_after_gemini_toggle(live_env):
    import terminal_session
    import anchor_settings
    pid = live_env["pid"]
    terminal_session.set_last_engine_for_project(pid, "gemini")
    want = anchor_settings.get_default_cli()
    rec = terminal_session.start_session(pid, "research", backend=want,
                                         seed_context="carry on")
    assert rec.get("backend") == want, \
        "continue must honor explicit backend, not sticky gemini last_engine"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_sticky_last_engine_still_leaks_without_explicit_backend(live_env):
    """Guard/witness: prove the LEAK is real at the source — start_session with
    NO backend DOES inherit the sticky gemini. This is exactly why the endpoints
    must pass an explicit backend (the fix), and documents the intentional v4
    'inherit last engine' semantics we deliberately did NOT change globally."""
    import terminal_session
    pid = live_env["pid"]
    terminal_session.set_last_engine_for_project(pid, "gemini")
    rec = terminal_session.start_session(pid, "research", seed_context="x")
    assert rec.get("backend") == "gemini", \
        "witness: no-backend start_session still inherits sticky last_engine"
