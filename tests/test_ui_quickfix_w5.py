"""Wave 5 STUB GATE — UI quick-fixes: deliverables collapse + terminal width.

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md``
§Wave 5):

  - **#4** Wrap the deliverables output in ``<details>`` so deliverables start
    COLLAPSED. The diagnosis named ``render_deliverables_html``; the LIVE
    Layout-D right-column panel is ``_render_layoutd_deliverables_panel`` (it
    already used ``<details open>`` → started expanded). Both are made
    collapsed-by-default here (no ``open`` attribute).
  - **#8** ``width:100%`` on ``.panel .pin`` so the panel fills its column
    instead of shrink-wrapping to xterm's 80-col min-width under ``resize:both``,
    PLUS an explicit ``fit()`` (``_fitPanelTerminal``) on panel OPEN so a
    freshly-opened terminal spans the full column immediately — not only after a
    maximize→restore.

STUB GATE (verbatim from the plan): the deliverables HTML contains a
``<details>`` wrapper (collapsed by default); the panel CSS carries
``width:100%`` and the open path invokes ``fit()`` (assert on the emitted
HTML/JS).

Hermetic: temp data dir, stub PTY backend, the fake runner — NEVER ``:8777`` /
real data / network / a live model. Pure render path (no spawn).
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui(tmp_path, monkeypatch):
    """Reload the stack against a temp data dir + stub PTY/runner seams."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for mod in ("rnd_registry", "effort_history", "deliverables",
                "effort_view", "lanes"):
        importlib.reload(importlib.import_module(mod))
    import anchor_gui
    return importlib.reload(anchor_gui)


def _project(gui, folder):
    import rnd_registry as rnd
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project("QuickFix", str(folder), scaffold=False)["id"]


def _slice_fn(js, name):
    """Return the body text of a top-level ``function <name>(...)`` from the JS,
    up to the next top-level ``function`` declaration (good enough to scope an
    assertion to one function)."""
    start = js.index("function " + name + "(")
    nxt = js.find("\nfunction ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


# ── #4 — deliverables render COLLAPSED by default ───────────────────────────

def test_render_deliverables_html_wrapped_in_collapsed_details(gui, tmp_path):
    folder = tmp_path / "proj"
    pid = _project(gui, folder)

    html = gui.render_deliverables_html(pid, str(folder))

    # A <details> wrapper present…
    assert "<details" in html, "deliverables HTML has no <details> wrapper"
    # …with NO `open` attribute → COLLAPSED by default.
    assert "<details open" not in html, \
        "deliverables <details> must be collapsed (no `open`)"
    # The heading is now the always-visible <summary> disclosure.
    assert "<summary" in html and "Deliverables" in html


def test_live_deliverables_panel_collapsed_by_default(gui, tmp_path):
    """The LIVE Layout-D right-column panel (the one actually rendered) is the
    real target of the SIGN-OFF screenshot — it must start collapsed."""
    folder = tmp_path / "proj"
    pid = _project(gui, folder)

    panel = gui._render_layoutd_deliverables_panel(str(folder), pid)

    assert "<details" in panel and "deliv-details" in panel
    assert "<details open" not in panel, \
        "live deliverables panel must render COLLAPSED (no `open`)"


def test_full_window_render_has_collapsed_deliverables(gui, tmp_path):
    """End-to-end: the full project window emits the collapsed deliverables
    panel (no `<details open class='deliv-details'>`)."""
    folder = tmp_path / "proj"
    pid = _project(gui, folder)

    html = gui.render_project_window_html(pid)

    assert "deliverables-panel" in html
    assert "<details open class='deliv-details'>" not in html, \
        "deliverables panel must not render expanded in the full window"
    assert "<details class='deliv-details'>" in html


# ── #8 — panel fills its column (CSS width:100%) + fit() on open ────────────

def test_panel_pin_css_has_full_width(gui, tmp_path):
    folder = tmp_path / "proj"
    pid = _project(gui, folder)

    html = gui.render_project_window_html(pid)

    # The `.panel .pin` rule now carries width:100% (fills the column) while
    # keeping resize:both (still freely resizable).
    assert ".panel .pin{" in html, ".panel .pin CSS rule not found"
    assert "width:100%;resize:both" in html, \
        ".panel .pin must carry width:100% (so the terminal fills its column)"


def test_open_path_invokes_fit(gui, tmp_path):
    folder = tmp_path / "proj"
    pid = _project(gui, folder)

    html = gui.render_project_window_html(pid)

    # The OPEN path (openPanel) re-fits the terminal on open so it spans the
    # full column immediately, not only after maximize→restore.
    body = _slice_fn(html, "openPanel")
    # Gated on a live session (a historical/discovered tile has no live term).
    assert "if (isLive) {" in body
    assert "_fitPanelTerminalDeferred(sessionId)" in body, \
        "openPanel must invoke _fitPanelTerminalDeferred (fit on open)"
    # The deferred fitter waits for the browser to COMMIT layout (rAF-until the
    # host has a real non-zero width) rather than racing it with a fixed
    # setTimeout — that race left the terminal at ~1/3 column width on open and
    # only "fixed itself" on a later resize. Assert the rAF-based mechanism.
    dfit = _slice_fn(html, "_fitPanelTerminalDeferred")
    assert "requestAnimationFrame" in dfit, \
        "the open-fit must defer to requestAnimationFrame (wait for layout)"
    assert "clientWidth > 0" in dfit, \
        "the open-fit must wait until the host reports a real non-zero width"
