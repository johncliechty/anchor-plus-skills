"""reaper Wave 5 — status-model correctness + kill() persist-before-terminal
ordering.

Locks criteria (5) + (6) of the zombie-hunter → safe-to-arm plan:

  - ``STATUS_CANCELLED`` is strictly TERMINAL — a state-transition table rejects
    any transition OUT of it, so a cancelled session is never re-adopted / never
    reconciled to running / never resurrected, and it retains no worktree.
  - The overloaded ``STATUS_IDLE`` is split into ``STATUS_PARKED_WARM`` (keeps its
    worktree, resumable) and ``STATUS_REAPED_ORPHAN`` (no worktree). Worktree
    retention (``worktrees.reap_orphans`` / ``_is_parked_idle``) is keyed on the
    EXPLICIT state field.
  - Legacy ``STATUS_IDLE`` records migrate CONSERVATIVELY forward to
    ``PARKED_WARM`` (over-protect only) and arm the reaper dry-run for the first
    post-migration sweep.
  - ``terminal_session.kill()`` PERSISTS the produced docs to main and CONFIRMS
    them BEFORE the record is marked DONE/terminal — no doc-loss window.
  - ``is_parked_warm`` / ``_is_parked_idle`` fail SAFE: an ambiguous / unknown
    state (or a registry-lookup error) → parked/keep, NEVER reaped.

Hermetic: a temp ``ANCHOR_DATA_DIR`` (+ a temp worktree base + a temp git repo +
stub PTY + the fake runner for the kill/reap paths) — never the live ``.anchor``
store, ``:8777``, real data, network, or a live model. Stdlib + pytest only.
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


# ── Light fixture: registry + worktrees only (no git needed) ─────────────────

@pytest.fixture
def mod(tmp_path, monkeypatch):
    """Temp data dir + reloaded ``paths`` / ``session_registry`` / ``worktrees``.

    Enough for the transition-table, classifier, migration, and
    cancelled-reconcile tests — none of which touch a real process or git.
    """
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.delenv("ANCHOR_REAPER_DRYRUN", raising=False)
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    return session_registry, worktrees


# ── (1) STATUS_CANCELLED is strictly terminal — never resurrected ────────────

def test_can_transition_locks_cancelled_and_reaped_orphan(mod):
    sr, _ = mod
    # A locked terminal state can never leave (except the identity no-op).
    assert sr.can_transition(sr.STATUS_CANCELLED, sr.STATUS_CANCELLED) is True
    assert sr.can_transition(sr.STATUS_CANCELLED, sr.STATUS_RUNNING) is False
    assert sr.can_transition(sr.STATUS_CANCELLED, sr.STATUS_IDLE) is False
    assert sr.can_transition(sr.STATUS_CANCELLED, sr.STATUS_DONE) is False
    assert sr.can_transition(sr.STATUS_REAPED_ORPHAN, sr.STATUS_RUNNING) is False
    assert sr.can_transition(sr.STATUS_REAPED_ORPHAN,
                             sr.STATUS_REAPED_ORPHAN) is True
    # Non-terminal transitions stay permissive (the lifecycle is unchanged).
    assert sr.can_transition(sr.STATUS_RUNNING, sr.STATUS_IDLE) is True
    assert sr.can_transition(sr.STATUS_IDLE, sr.STATUS_RUNNING) is True
    assert sr.can_transition(sr.STATUS_DONE, sr.STATUS_RUNNING) is True


def test_update_session_rejects_transition_out_of_cancelled(mod):
    """A cancelled session is never re-adopted: an ``update_session`` that tries
    to flip it back to RUNNING (an adopt) is rejected; the status stays cancelled
    while any OTHER field in the same call still applies."""
    sr, _ = mod
    rec = sr.register_session("p1", "plan", status=sr.STATUS_CANCELLED)
    sid = rec["session_id"]
    assert rec["status"] == sr.STATUS_CANCELLED

    out = sr.update_session(sid, status=sr.STATUS_RUNNING, label="re-adopted")
    assert out["status"] == sr.STATUS_CANCELLED, "cancelled must never resurrect"
    assert out["label"] == "re-adopted", "a non-status field still applies"
    # Re-load from disk to prove the rejection is persisted, not just in-memory.
    assert sr.get_session(sid)["status"] == sr.STATUS_CANCELLED


def test_reconcile_never_resurrects_a_cancelled_session(mod):
    """reconcile only re-statuses RUNNING records; a cancelled one is untouched —
    never reconciled to running (or to any other state)."""
    sr, _ = mod
    c = sr.register_session("p1", "plan", status=sr.STATUS_CANCELLED)
    r = sr.register_session("p1", "build", status=sr.STATUS_RUNNING)
    # Nothing live → the running one is stale, the cancelled one is left alone.
    report = sr.reconcile(live_session_ids=set())
    assert c["session_id"] not in report["marked"]
    assert sr.get_session(c["session_id"])["status"] == sr.STATUS_CANCELLED
    # (sanity) the genuinely-stale running record WAS reconciled.
    assert r["session_id"] in report["marked"]


# ── (2) PARKED_WARM vs REAPED_ORPHAN drive worktree retention ────────────────

def test_is_parked_warm_classifier(mod):
    sr, _ = mod
    # Parked-warm / legacy idle → KEEP.
    assert sr.is_parked_warm(sr.STATUS_PARKED_WARM) is True
    assert sr.is_parked_warm(sr.STATUS_IDLE) is True
    assert sr.is_parked_warm({"status": sr.STATUS_PARKED_WARM}) is True
    # Reaped orphan / cancelled → NO worktree.
    assert sr.is_parked_warm(sr.STATUS_REAPED_ORPHAN) is False
    assert sr.is_parked_warm(sr.STATUS_CANCELLED) is False
    # Live / finished states are not "parked warm".
    assert sr.is_parked_warm(sr.STATUS_RUNNING) is False
    assert sr.is_parked_warm(sr.STATUS_DONE) is False
    assert sr.is_parked_warm(sr.STATUS_FAILED) is False


def test_is_parked_idle_keys_on_explicit_state(mod):
    """``worktrees._is_parked_idle`` reads the EXPLICIT split state, not a bare
    ``idle`` string."""
    sr, wt = mod
    parked = sr.register_session("p1", "plan", status=sr.STATUS_PARKED_WARM)
    orphan = sr.register_session("p1", "plan", status=sr.STATUS_REAPED_ORPHAN)
    legacy = sr.register_session("p1", "plan", status=sr.STATUS_IDLE)
    running = sr.register_session("p1", "plan", status=sr.STATUS_RUNNING)
    assert wt._is_parked_idle(parked["session_id"]) is True
    assert wt._is_parked_idle(legacy["session_id"]) is True
    assert wt._is_parked_idle(orphan["session_id"]) is False
    assert wt._is_parked_idle(running["session_id"]) is False


def test_is_parked_idle_absent_record_is_reapable_but_error_fails_safe(mod,
                                                                       monkeypatch):
    """A genuinely ABSENT record (no owner) stays reapable — the sweep's whole
    point — but a registry-lookup ERROR fails SAFE (keep, never reap)."""
    sr, wt = mod
    assert wt._is_parked_idle("no-such-session-id") is False

    def _boom(_sid):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(sr, "get_session", _boom)
    assert wt._is_parked_idle("anything") is True, \
        "a lookup error must fail SAFE to keep, never reap"


def test_ambiguous_status_fails_safe_to_keep(mod):
    """An ambiguous / UNRECOGNIZED state is classified parked/keep — never reaped."""
    sr, _ = mod
    assert sr.is_parked_warm("some-unknown-future-status") is True
    assert sr.is_parked_warm({"status": "weird"}) is True


# ── (3) Conservative legacy STATUS_IDLE → PARKED_WARM migration ──────────────

def test_migration_idle_to_parked_warm_over_protects_and_arms_dryrun(mod):
    sr, wt = mod
    a = sr.register_session("p1", "plan", status=sr.STATUS_IDLE)
    b = sr.register_session("p1", "build", status=sr.STATUS_IDLE)
    keep_running = sr.register_session("p1", "research", status=sr.STATUS_RUNNING)
    done = sr.register_session("p1", "plan", status=sr.STATUS_DONE)

    report = sr.migrate_idle_to_parked_warm()
    assert set(report["migrated"]) == {a["session_id"], b["session_id"]}
    assert report["applied"] is True
    # Only the idle records moved — over-protect only, never a downgrade.
    assert sr.get_session(a["session_id"])["status"] == sr.STATUS_PARKED_WARM
    assert sr.get_session(b["session_id"])["status"] == sr.STATUS_PARKED_WARM
    assert sr.get_session(keep_running["session_id"])["status"] == sr.STATUS_RUNNING
    assert sr.get_session(done["session_id"])["status"] == sr.STATUS_DONE
    # The first post-migration boot is armed to sweep report-only.
    assert wt.reaper_dryrun_active() is True

    # Idempotent — a second run finds nothing to migrate.
    again = sr.migrate_idle_to_parked_warm()
    assert again["migrated"] == []
    assert again["applied"] is False


# ── (2b) Real worktree retention + (6) kill persist-before-terminal ──────────

@pytest.fixture
def gitenv(tmp_path, monkeypatch):
    """Temp data dir + worktree base + stub PTY + fake runner + a temp git repo,
    with the terminal-session stack reloaded — for the reap_orphans retention +
    kill no-doc-loss ordering tests (both need real worktrees)."""
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
    monkeypatch.delenv("ANCHOR_REAPER_DRYRUN", raising=False)
    for name in ("paths", "job_runner", "pty_manager", "rnd_registry",
                 "effort_history", "sessions", "anchor_marker",
                 "session_registry", "worktrees", "lanes", "summarizer",
                 "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(name))
    import paths
    paths.ensure_data_dirs()
    import terminal_session, session_registry, worktrees, rnd_registry, pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {"ts": terminal_session, "reg": session_registry, "wt": worktrees,
           "rnd": rnd_registry, "pty": pty_manager, "repo": repo,
           "pid": proj["id"]}
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _start_plan_with_doc(gitenv, doc="MASTER-PLAN.md"):
    rec = gitenv["ts"].start_session(gitenv["pid"], "plan", backend="claude")
    sid = rec["session_id"]
    wt = Path(rec["worktree_path"])
    pdir = wt / "planning" / "rnd-w5"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / doc).write_text(
        "# Master Plan\n## North Star\nDurable resumable work.\n",
        encoding="utf-8")
    return rec, sid, wt


def test_reap_orphans_retention_follows_explicit_state(gitenv):
    """A PARKED_WARM worktree is KEPT; a REAPED_ORPHAN one is removed — retention
    is driven by the explicit split state, not the overloaded idle."""
    ts, reg, wt = gitenv["ts"], gitenv["reg"], gitenv["wt"]
    p = ts.start_session(gitenv["pid"], "plan", backend="claude")
    o = ts.start_session(gitenv["pid"], "research", backend="claude")
    p_sid, p_wt = p["session_id"], Path(p["worktree_path"])
    o_sid, o_wt = o["session_id"], Path(o["worktree_path"])
    reg.update_session(p_sid, status=reg.STATUS_PARKED_WARM)
    reg.update_session(o_sid, status=reg.STATUS_REAPED_ORPHAN)
    assert p_wt.exists() and o_wt.exists()

    report = wt.reap_orphans(active_session_ids=set(), project_id=gitenv["pid"])

    assert p_sid in report["kept"], "a PARKED_WARM worktree must be KEPT"
    assert p_wt.exists()
    assert o_sid in report["reaped"], "a REAPED_ORPHAN worktree must be removed"
    assert not o_wt.exists()


def test_kill_persists_docs_before_marking_terminal(gitenv, monkeypatch):
    """No doc loss on kill: the produced docs are persisted + confirmed in MAIN
    BEFORE the record is flipped to DONE/terminal. Proven by intercepting the
    DONE write and asserting the main doc already exists at that instant."""
    ts, reg, repo = gitenv["ts"], gitenv["reg"], gitenv["repo"]
    rec, sid, wt = _start_plan_with_doc(gitenv)
    main_doc = repo / "planning" / "rnd-w5" / "MASTER-PLAN.md"
    assert not main_doc.exists(), "precondition: doc not yet in main"

    seen = {"doc_present_when_marked_done": None, "done_write_count": 0}
    real_update = reg.update_session

    def _spy_update(session_id, **fields):
        if fields.get("status") == reg.STATUS_DONE:
            seen["done_write_count"] += 1
            seen["doc_present_when_marked_done"] = main_doc.exists()
        return real_update(session_id, **fields)

    # terminal_session calls session_registry.update_session as ``_reg.update_session``
    # (module attribute looked up at call time), so patching the module attr wins.
    monkeypatch.setattr(reg, "update_session", _spy_update)

    out = ts.kill(sid, project_id=gitenv["pid"])
    assert out["ok"] is True
    # The docs were persisted (kill's own report shows the produced doc).
    persisted = (out.get("docs") or {}).get("persisted") or []
    assert any("MASTER-PLAN.md" in p for p in persisted), \
        f"kill must persist the produced doc to main; got {persisted}"
    assert main_doc.exists(), "the doc must be copied into MAIN"
    # THE ordering invariant: at the moment kill marked the record DONE, the doc
    # was ALREADY in main — persist-before-terminal.
    assert seen["done_write_count"] >= 1, "kill must mark the record terminal"
    assert seen["doc_present_when_marked_done"] is True, \
        "docs must be persisted+confirmed BEFORE the record is marked DONE"
    # And the record IS terminal afterwards.
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE


def test_kill_of_cancelled_session_does_not_resurrect_to_done(gitenv):
    """Killing an already-CANCELLED session tears it down but the terminal-lock
    keeps it cancelled — the DONE write is rejected, never a resurrection."""
    ts, reg = gitenv["ts"], gitenv["reg"]
    rec, sid, wt = _start_plan_with_doc(gitenv)
    reg.update_session(sid, status=reg.STATUS_CANCELLED)
    ts.kill(sid, project_id=gitenv["pid"])
    assert reg.get_session(sid)["status"] == reg.STATUS_CANCELLED, \
        "a cancelled session must never be flipped to DONE by kill"
    assert not Path(rec["worktree_path"]).exists(), \
        "kill still reaps the worktree (cancelled retains none)"
