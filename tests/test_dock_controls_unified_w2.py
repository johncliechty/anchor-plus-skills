"""Wave 2 gate — unified dock controls (× + 🪦).

crucible-improve-followup (2026-07-01), Wave 2.

The v12 bottom dock (`_render_layoutd_dock_html`) used to carry the pre-W6 control
shape — a `✕` close PLUS a text "Kill → Boneyard" button PLUS a redundant second
red `✕` v9 true-delete (`dockDelete`). This wave collapses it to exactly the two
lifecycle controls the W6 inline panel carries: `×` graceful close (keeps the
effort) + `🪦` Kill → Boneyard (the ONE destructive control). The redundant
second `✕` (dockDelete) is removed so the dock matches the panel.
"""
import importlib

import pytest


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "session_registry", "effort_history",
                "summarizer", "lanes", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


def _window(gui, tmp_path):
    import rnd_registry
    folder = tmp_path / "Proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Proj", str(folder), scaffold=False)["id"]
    return gui.render_project_window_html(pid)


def test_dock_has_exactly_close_and_headstone(gui_env, tmp_path):
    html = _window(gui_env, tmp_path)
    # graceful CLOSE (×) — keeps the effort.
    assert "id='dockClose'" in html
    assert "&#10005;" in html  # the × close glyph
    # the ONE destructive control: Kill → Boneyard as the headstone (🪦).
    assert "id='dockKill'" in html
    assert "&#129702;" in html  # 🪦 U+1FAA6
    assert "killbone" in html   # styled like the panel's Kill→Boneyard control


def test_dock_redundant_second_x_true_delete_removed(gui_env, tmp_path):
    html = _window(gui_env, tmp_path)
    # The redundant second ✕ (v9 dockDelete true-delete) is gone from the dock.
    assert "id='dockDelete'" not in html
    # ...and so is the old "Kill → Boneyard" TEXT button (now a headstone glyph).
    assert ">Kill &#8594; Boneyard</button>" not in html


def test_dock_mirrors_the_panel_control_scheme(gui_env, tmp_path):
    """The inline panel's scheme (× close + 🪦 kill) is the reference; the dock
    now uses the SAME headstone glyph for its single destructive control."""
    html = _window(gui_env, tmp_path)
    js = gui_env._PROJECT_WINDOW_JS
    # Panel reference: the killbone button carries the 🪦 headstone.
    assert "killBtn.textContent = '\U0001faa6'" in js or \
           "killBtn.textContent = '🪦'" in js
    # Dock now carries the same headstone (entity form).
    assert "&#129702;" in html


def test_dock_render_has_no_brace_leak(gui_env, tmp_path):
    """The Wave-2 render edit must not leak an unbalanced f-string brace."""
    html = _window(gui_env, tmp_path)
    assert html.count("{") == html.count("}"), \
        "brace imbalance in rendered window after the dock edit"
