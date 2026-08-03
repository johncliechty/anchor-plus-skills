"""Wave 4 STUB GATE — Resume UI + efforts list (Pillar A/B · UI).

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md``
§Wave 4):

  - **#6 UI** — give discovered effort cards a real "resume as session"
    affordance (today the tile only opens the on-disk artifact) that drives
    ``start_session`` with the W3 synthesized seed. Implemented as the
    ``resume-disc`` control → ``resumeDiscovered`` → ``continueSession`` →
    ``POST /api/rnd/continue_session`` → :func:`anchor_gui._build_continue_seed`
    (which SYNTHESIZES the warm seed from on-disk docs for a discovered effort,
    W3 #6) → ``terminal_session.start_session``.
  - **#3 render** — always show the latest effort per lane inline + a "previous
    efforts" expander when a lane (Layout-D zone) has >1 effort. The expander is
    the older-runs shelf, hooked by the stable ``prev-efforts`` class (present
    iff >1).

STUB GATE (verbatim from the plan): the project-window render includes a resume
control on a discovered card AND a "previous efforts" expander when a lane has >1
effort (assert on the HTML).

Hermetic: temp data dir, stub PTY backend, the fake runner — NEVER ``:8777`` /
real data / network / a live model. Read-only render path (no spawn).
"""
import importlib
import re
from pathlib import Path

import pytest

import brownfield_scan as bscan

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
    for mod in ("rnd_registry", "effort_history", "sessions",
                "brownfield_scan", "effort_view", "lanes"):
        importlib.reload(importlib.import_module(mod))
    import anchor_gui
    return importlib.reload(anchor_gui)


def _discovered_project(gui, root, dirs):
    """Register a brownfield project with one discovered planning doc per dir."""
    import rnd_registry as rnd
    import effort_history as eh
    for nm in dirs:
        (root / "planning" / nm).mkdir(parents=True, exist_ok=True)
        (root / "planning" / nm / "MASTER-PLAN.md").write_text(
            "# Master Plan\n## North Star\nDurable resumable work.\n",
            encoding="utf-8")
    pid = rnd.add_project("Brownfield", str(root), scaffold=False)["id"]
    eh.adopt_discovered(str(root), pid, bscan.scan(str(root)))
    return pid


# ── #6 UI — discovered card carries a "resume as session" control ────────────

def test_discovered_card_has_resume_control(gui, tmp_path):
    folder = tmp_path / "proj"
    pid = _discovered_project(gui, folder, ["rnd-x"])

    # The discovered planning session id (the source the resume control must pass).
    plan_sessions = gui._gather_project_sessions(str(folder), pid)["plan"]
    assert len(plan_sessions) == 1, "expected ONE discovered planning session"
    sv = plan_sessions[0]
    sid = sv["session_id"]
    assert sv["members"][0]["discovered"] is True

    html = gui.render_project_window_html(pid)

    # The resume CONTROL (button class — distinct from the `.resume-disc{` CSS
    # rule that is always present in the page's style block).
    assert "class='resume-disc'" in html, \
        "discovered card has no 'resume as session' control"
    # Visible affordance copy.
    assert "Resume as session" in html
    # The control drives the resume path with THIS discovered session id + lane,
    # so start_session is seeded with the W3 synthesized seed.
    expected = f"resumeDiscovered(event,'{sid}','plan')"
    assert expected in html, f"resume onclick missing/wrong: want {expected!r}"
    # The JS handler that delegates to continueSession (→ continue_session) exists.
    assert "function resumeDiscovered" in html
    assert "continueSession(sessionId, lane)" in html


def test_non_discovered_effort_has_no_resume_control(gui, tmp_path):
    """The resume control is DISCOVERED-only — a real (run) effort never gets it
    (those carry on via the panel's "Continue in a live session" button)."""
    import effort_history as eh
    import rnd_registry as rnd
    folder = tmp_path / "proj"
    (folder / "planning").mkdir(parents=True)
    (folder / "planning" / "seed.md").write_text("x", encoding="utf-8")
    pid = rnd.add_project("Run", str(folder), scaffold=False)["id"]
    # Two NON-discovered research efforts (a real recorded run, discovered=False).
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    eh.record_effort(folder, pid, "research", "r2", skill="researchPrime")

    html = gui.render_project_window_html(pid)

    # No discovered tile → NO resume control button anywhere on the page.
    assert "class='resume-disc'" not in html
    # The research tiles render (the guard didn't suppress real tiles).
    assert "data-lane=\"research\"" in html


# ── #3 render — "previous efforts" expander appears iff a lane has >1 effort ──

def test_prev_efforts_expander_present_when_lane_has_more_than_one(gui, tmp_path):
    folder = tmp_path / "proj"
    pid = _discovered_project(gui, folder, ["rnd-x", "rnd-y"])

    # The Plan/Build zone now holds TWO discovered planning efforts.
    assert len(gui._gather_project_sessions(str(folder), pid)["plan"]) == 2

    html = gui.render_project_window_html(pid)

    # The latest is the inline headline; the rest sit behind the "previous
    # efforts" expander (the older-runs shelf, hooked by `prev-efforts`).
    assert "prev-efforts" in html, \
        "no 'previous efforts' expander for a lane with >1 effort"
    assert "class='showall prev-efforts'" in html
    # Both the headline AND the shelf tile carry the resume control.
    assert html.count("class='resume-disc'") == 2


def test_prev_efforts_expander_absent_when_lane_has_one(gui, tmp_path):
    """A single-effort project shows the inline headline only — NO expander."""
    folder = tmp_path / "proj"
    pid = _discovered_project(gui, folder, ["rnd-x"])

    # Exactly one effort total (one discovered planning session, no research).
    sessions = gui._gather_project_sessions(str(folder), pid)
    assert len(sessions["plan"]) == 1
    assert len(sessions["research"]) == 0

    html = gui.render_project_window_html(pid)

    assert "prev-efforts" not in html, \
        "expander must be ABSENT when no lane has >1 effort"
    # …but the lone discovered headline still carries its resume control.
    assert "class='resume-disc'" in html
