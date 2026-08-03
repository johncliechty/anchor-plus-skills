"""Wave 6 STUB GATE — Terminal controls unification (Pillar A/B, crucible-improve
#5/#13 + the W6 amendment).

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md``
§Wave 6):

  - **#5/#13** A session panel's controls become ``–`` minimize · ``×`` close =
    STOP the PTY + PRESERVE the worktree + KEEP the registry record (resumable via
    W3/W4) · one ``Kill→Boneyard`` (archive + reap). Remove the redundant ``🗑``
    ``.hardkill`` and ``✕`` ``.delete`` panel buttons; JS + CSS in lockstep.
  - **W6 amendment** — close must be WARM-resumable, not just worktree-preserving:
    ``close_session`` PERSISTS the produced docs to MAIN (like ``kill``) so they
    survive the boot reaper + feed the W3 resume seed, the ``/api/rnd/term_close``
    endpoint schedules the same background summary hook ``finish``/``kill`` use,
    and ``worktrees.reap_orphans`` KEEPS a ``STATUS_IDLE`` (parked) worktree.

STUB GATE (verbatim from the plan): after ``×`` the session's PTY is reaped BUT
the worktree + registry record persist (status reopenable), and a resume reopens
it via W3; the panel exposes exactly close-``×`` + ``Kill→Boneyard``; ``Kill→
Boneyard`` reaps + archives. PLUS the REAL ``_build_continue_seed`` (not a hand-fed
seed) yields a NON-EMPTY warm seed for the closed managed session; close persists
the docs to main (they survive a simulated reaper pass); and a ``STATUS_IDLE``
worktree is NOT removed by ``reap_orphans``.

Hermetic: temp data dir, stub PTY backend, the fake runner, a temp git repo —
NEVER ``:8777`` / real data / network / a live model.
"""
import importlib
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
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True)


# ── (A) backend close / reap / warm-resume — needs a real git worktree ───────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir + temp worktree base + stub PTY + fake runner + a temp git
    repo, with the FULL resume stack (anchor_gui / summarizer / effort_view)
    reloaded so the real ``_build_continue_seed`` resolves against this project."""
    if not _have_git():
        pytest.skip("git not on PATH")
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "brownfield_scan", "effort_view",
                "deliverables", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import terminal_session, session_registry, worktrees, rnd_registry
    import summarizer

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)

    import pty_manager
    yield {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "wt": worktrees, "rnd": rnd_registry, "summ": summarizer,
        "pty": pty_manager, "repo": repo, "pid": proj["id"], "wbase": wbase,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _start_plan_with_doc(env, doc="MASTER-PLAN.md"):
    """Start a managed plan session and drop an UNTRACKED trio doc in its worktree
    (so capture_session_docs has real produced material to persist)."""
    rec = env["ts"].start_session(env["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    wt = Path(rec["worktree_path"])
    pdir = wt / "planning" / "rnd-w6"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / doc).write_text(
        "# Master Plan\n## North Star\nDurable resumable work.\n",
        encoding="utf-8")
    return rec, sid, wt


def test_close_stops_pty_keeps_worktree_and_record_idle(env):
    """`×` close: PTY reaped, worktree PRESERVED, registry record kept at
    STATUS_IDLE (parked/reopenable) — distinct from kill (which reaps both)."""
    ts, reg = env["ts"], env["reg"]
    rec, sid, wt = _start_plan_with_doc(env)
    assert wt.exists()
    assert sid in env["pty"].live_sessions()

    out = ts.close_session(sid)
    assert out["ok"] is True
    assert out["pty_killed"] is True
    # PTY gone, BUT the worktree + registry record persist (reopenable).
    assert sid not in env["pty"].live_sessions()
    assert wt.exists(), "close must PRESERVE the worktree"
    assert reg.get_session(sid) is not None, "close must KEEP the registry record"
    assert reg.get_session(sid)["status"] == reg.STATUS_IDLE
    # A park is NOT terminal — the record is reopenable, not DONE/FAILED.
    assert reg.get_session(sid)["status"] not in reg.TERMINAL_STATUSES


def test_close_persists_docs_to_main_surviving_a_reaper_pass(env):
    """close persists the produced docs into MAIN (like kill), so they survive
    even if the worktree is later reaped — the W3 resume seed reads MAIN, never
    the worktree."""
    ts = env["ts"]
    repo = env["repo"]
    rec, sid, wt = _start_plan_with_doc(env)

    out = ts.close_session(sid)
    persisted = (out.get("docs") or {}).get("persisted") or []
    assert any("MASTER-PLAN.md" in p for p in persisted), \
        f"close must persist the produced doc to main; got {persisted}"
    main_doc = repo / "planning" / "rnd-w6" / "MASTER-PLAN.md"
    assert main_doc.exists(), "the doc must be copied into the MAIN project"

    # Simulate a reaper pass that DOES remove this worktree — the MAIN doc must
    # survive (it was persisted out of the worktree before any reap).
    env["wt"].remove_worktree(sid, project_id=env["pid"])
    assert not Path(rec["worktree_path"]).exists()
    assert main_doc.exists(), "persisted doc must survive worktree removal"


def test_reap_orphans_keeps_idle_worktree(env):
    """The boot orphan-reaper KEEPS a STATUS_IDLE (parked) worktree even with no
    live PTY, while a non-parked worktree not in the active set is still reaped."""
    ts, wt = env["ts"], env["wt"]
    # a = closed → parked IDLE worktree (must be kept).
    _, a_sid, a_wt = _start_plan_with_doc(env)
    ts.close_session(a_sid)
    # b = a still-RUNNING session NOT in the active set (must be reaped).
    b = ts.start_session(env["pid"], "research", backend="claude")
    b_sid, b_wt = b["session_id"], Path(b["worktree_path"])
    assert a_wt.exists() and b_wt.exists()

    report = wt.reap_orphans(active_session_ids=set(), project_id=env["pid"])

    assert a_sid in report["kept"], "a STATUS_IDLE worktree must be KEPT"
    assert a_wt.exists(), "the parked worktree must survive the reap"
    assert b_sid in report["reaped"], "a non-parked orphan must still be reaped"
    assert not b_wt.exists()


def test_close_managed_session_resumes_warm(env):
    """The REAL `_build_continue_seed` (not a hand-fed seed_context) yields a
    NON-EMPTY warm seed for the closed managed session — the resume opens warm.

    Mirrors the production flow: close persists the docs (tagged with the managed
    session id), then the SAME summary hook the endpoint schedules keys a cached
    summary to that id; here that hook is run synchronously for determinism."""
    gui, summ = env["gui"], env["summ"]
    repo, pid = env["repo"], env["pid"]
    monkeypatch_claims = "Durable resumable work is the north star"

    rec, sid, wt = _start_plan_with_doc(env)
    out = env["ts"].close_session(sid)
    assert (out.get("docs") or {}).get("persisted"), "docs should be persisted"

    # Run the SAME summary chain the /api/rnd/term_close endpoint schedules: tie
    # the managed id to its persisted docs, then cache the validated summary keyed
    # to that id. (Synchronous here; a daemon thread in production.)
    import os
    os.environ["STUB_SUMMARIZER_CLAIMS"] = monkeypatch_claims
    try:
        session = gui._resolve_finished_session(str(repo), pid, "plan", sid)
        assert session is not None and session["session_id"] == sid
        summ.summarize_session(str(repo), pid, "plan", session)
    finally:
        os.environ.pop("STUB_SUMMARIZER_CLAIMS", None)

    # The cache is keyed to the MANAGED id, so the real resume seed is warm.
    assert summ.load_cached(str(repo), pid, "planning", sid) is not None
    seed = gui._build_continue_seed(str(repo), pid, "plan", sid)
    assert seed, "a closed managed session must resume with a NON-EMPTY warm seed"
    assert "plan" in seed.lower()


def test_close_unknown_session_is_clean(env):
    """close of an unknown id is tolerated (no crash) — the panel close then just
    tears down its DOM."""
    out = env["ts"].close_session("no-such-session")
    assert out["ok"] is False and out["reason"] == "unknown-session"


def test_close_does_not_unfinish_a_done_session(env):
    """A historical/non-live close must not 'un-finish' a DONE session — only a
    RUNNING record is re-statused to IDLE."""
    ts, reg = env["ts"], env["reg"]
    rec, sid, wt = _start_plan_with_doc(env)
    ts.kill(sid)  # now DONE (terminal)
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES
    ts.close_session(sid)
    # Still terminal — NOT flipped back to IDLE.
    assert reg.get_session(sid)["status"] in reg.TERMINAL_STATUSES


# ── (B) panel HTML/JS controls + CSS — pure render path (no git) ─────────────

@pytest.fixture
def gui(tmp_path, monkeypatch):
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
    return rnd.add_project("Controls", str(folder), scaffold=False)["id"]


def _slice_fn(js, name):
    start = js.index("function " + name + "(")
    nxt = js.find("\nfunction ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_panel_exposes_close_and_killboneyard(gui, tmp_path):
    """The panel header creates the close-`×` and the single `Kill → Boneyard`
    (`killbone`) control."""
    pid = _project(gui, tmp_path / "proj")
    html = gui.render_project_window_html(pid)
    body = _slice_fn(html, "openPanel")

    # close-× wired to the graceful closePanel.
    assert "closeBtn.className = 'panelbtn close'" in body
    assert "closePanel(sessionId)" in body
    # The ONE destructive control: Kill → Boneyard (killbone, better icon).
    assert "killBtn.className = 'panelbtn killbone'" in body
    assert "Boneyard" in body, "the Kill→Boneyard control must be labelled"
    # The button glyph is no longer the old 🗑 wastebasket.
    assert "killBtn.textContent = '\U0001f5d1'" not in body
    assert "killPanel(sessionId)" in body, "Kill→Boneyard must call killPanel"


def test_panel_has_no_hardkill_or_delete_button(gui, tmp_path):
    """The redundant 🗑 `.hardkill` and ✕ `.delete` PANEL buttons are gone."""
    pid = _project(gui, tmp_path / "proj")
    html = gui.render_project_window_html(pid)

    # The panel no longer builds a hardkill button or a delete button.
    assert "'panelbtn hardkill'" not in html, "the 🗑 hardkill button must be gone"
    assert "delBtn" not in html, "the ✕ delete panel button must be gone"


def test_close_panel_posts_term_close(gui, tmp_path):
    """closePanel is the GRACEFUL close — it POSTs /api/rnd/term_close (stop PTY,
    keep worktree+record), not a pure DOM teardown."""
    pid = _project(gui, tmp_path / "proj")
    html = gui.render_project_window_html(pid)
    body = _slice_fn(html, "closePanel")

    assert "/api/rnd/term_close" in body, \
        "closePanel must POST term_close (graceful stop, resumable)"
    assert "_closePanel(sessionId)" in body, "still tears down the panel DOM"


def test_panel_css_killbone_present_hardkill_removed(gui, tmp_path):
    """CSS in lockstep: `.panelbtn.killbone` is styled; `.panelbtn.hardkill` is
    removed; `.panelbtn.delete` is RETAINED as a re-add path (no rendered control
    uses it now — the followup W2 removed the dock's #dockDelete, × + 🪦 only)."""
    pid = _project(gui, tmp_path / "proj")
    html = gui.render_project_window_html(pid)

    assert ".panelbtn.killbone{" in html, "the Kill→Boneyard CSS rule is missing"
    assert ".panelbtn.hardkill{" not in html, "the hardkill CSS rule must be gone"
    # Retained (tested) so true-delete can be reinstated in one line if wanted.
    assert ".panelbtn.delete{" in html
