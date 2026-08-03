"""reaper Wave 6 — close the swarm-job leak: teardown owns the PTY AND the jobs,
reference-counted.

Locks success criterion (4) of the zombie-hunter → safe-to-arm plan:

  - ``terminal_session.kill`` / ``delete_session`` tear down NOT ONLY the PTY but
    every ``job_runner`` job the session owns, via a TARGETED per-``job_id``
    cancel/reap walked off the session registry — never a full
    ``job_runner.list_records`` scan.
  - Ownership is REFERENCE-COUNTED: a job handed off to / shared with a LIVE
    successor in the chain (plan→build, a shared preview) survives the
    predecessor's kill, and the ownership transfer is recorded (the predecessor
    releases its claim; the successor stays the sole owner).
  - The registry record is kept HONEST: it is not marked terminal (hidden) while
    an owned job is still live — the owned jobs are confirmed reaped BEFORE the
    record is flipped DONE.
  - Two ownership sources both reap: an EXPLICIT claim (``owned_job_ids``) and the
    real orphan-swarm — a ``job_runner`` job whose ``SWARM_LANE`` session shares
    the dying session's worktree.

Hermetic: a temp ``ANCHOR_DATA_DIR`` (+ the fake runner for real, cancellable
child processes; + a temp worktree base + a temp git repo + stub PTY for the
kill() integration path) — never the live ``.anchor`` store, ``:8777``, real
data, network, or a live model. Stdlib + pytest only.
"""
import importlib
import os
import subprocess
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()

#: fake-runner flags that keep a launched job ALIVE (so it can be observed then
#: cancelled): emit one line, then sleep well past the test's lifetime.
_ALIVE_ARGS = ["--lines", "1", "--sleep", "60"]


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True)


def _pid_alive(pid) -> bool:
    """Cross-platform 'is this PID a live process?' (best-effort)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        try:
            import proc_probe
            return bool(proc_probe.is_alive(pid))
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _wait_pid_dead(pid, timeout=10.0) -> bool:
    """Poll until ``pid`` is no longer alive, bounded by ``timeout``."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


# ── Lean fixture: registry + job_runner over the fake runner ─────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir + fake runner + reloaded registry/job_runner/terminal_session.

    Enough to launch real, cancellable child jobs and drive the reference-counted
    teardown directly — no git/worktree needed for the claim-based tests.
    """
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_REAPER_DRYRUN", raising=False)
    for name in ("paths", "job_runner", "pty_manager", "rnd_registry",
                 "effort_history", "sessions", "anchor_marker",
                 "session_registry", "worktrees", "lanes", "summarizer",
                 "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(name))
    import paths
    paths.ensure_data_dirs()
    import session_registry, job_runner, terminal_session
    launched = []

    def _launch(cwd=None):
        rec = job_runner.launch("swarm", cwd=(str(cwd) if cwd else None),
                                extra_args=list(_ALIVE_ARGS), backend="claude")
        launched.append(rec["job_id"])
        return rec

    yield {"reg": session_registry, "jr": job_runner, "ts": terminal_session,
           "launch": _launch, "tmp": tmp_path}

    # Reap any still-live job so the test never leaks a real child process.
    for jid in launched:
        try:
            job_runner.cancel(jid)
        except Exception:
            pass


def _register_session(reg, *, status=None, worktree_path="",
                      parent_session_id="", chain_id=None):
    status = status if status is not None else reg.STATUS_RUNNING
    return reg.register_session("p1", "plan", status=status,
                                worktree_path=worktree_path,
                                parent_session_id=parent_session_id,
                                chain_id=chain_id)


# ── (0) The storage seam: claim / release / reference count ──────────────────

def test_claim_and_release_and_claimants(env):
    reg = env["reg"]
    s = _register_session(reg)
    sid = s["session_id"]
    assert reg.owned_jobs(sid) == []

    assert reg.claim_job(sid, "jobA") is True
    assert reg.claim_job(sid, "jobA") is False, "claim is idempotent / de-duped"
    assert reg.claim_job(sid, "jobB") is True
    assert reg.owned_jobs(sid) == ["jobA", "jobB"]
    # Persisted across a re-load (not just in-memory).
    assert reg.get_session(sid)["owned_job_ids"] == ["jobA", "jobB"]

    # Reference count: who claims jobA?
    claimants = reg.job_claimants("jobA")
    assert [c["session_id"] for c in claimants] == [sid]
    assert reg.job_claimants("jobA", exclude=sid) == []

    assert reg.release_job(sid, "jobA") is True
    assert reg.release_job(sid, "jobA") is False, "release is idempotent"
    assert reg.owned_jobs(sid) == ["jobB"]
    assert reg.job_claimants("jobA") == []

    # Unknown session / empty ids are clean no-ops, never a crash.
    assert reg.claim_job("no-such-session", "j") is False
    assert reg.claim_job(sid, "") is False
    assert reg.owned_jobs("no-such-session") == []


# ── (1) kill/delete reap every OWNED job via targeted per-job_id cancel ───────

def test_teardown_reaps_all_explicitly_owned_jobs(env):
    """A session with in-flight jobs it owns: teardown cancels/reaps EVERY one via
    a targeted per-job_id cancel — the swarm-job leak is closed."""
    reg, jr, ts = env["reg"], env["jr"], env["ts"]
    s = _register_session(reg)
    sid = s["session_id"]

    j1 = env["launch"]()
    j2 = env["launch"]()
    for j in (j1, j2):
        assert jr.load_record(j["job_id"])["status"] == jr.STATUS_RUNNING
        assert _pid_alive(j["pid"]), "precondition: the job is a live process"
    reg.claim_job(sid, j1["job_id"])
    reg.claim_job(sid, j2["job_id"])

    out = ts._teardown_owned_jobs(sid, record=reg.get_session(sid))

    assert set(out["cancelled"]) == {j1["job_id"], j2["job_id"]}
    assert out["transferred"] == []
    assert out["all_reaped"] is True
    for j in (j1, j2):
        assert jr.load_record(j["job_id"])["status"] == jr.STATUS_CANCELLED, \
            "every owned job is marked terminal (cancelled)"
        assert _wait_pid_dead(j["pid"]), "the owned job's process is reaped"
    # The dying session's now-defunct claims were released.
    assert reg.owned_jobs(sid) == []


def test_teardown_reaps_worktree_shared_swarm_job(env):
    """The real orphan-swarm: a job_runner job whose SWARM_LANE session shares the
    dying session's worktree is owned + reaped — with NO explicit claim needed and
    NO full list_records scan."""
    reg, jr, ts = env["reg"], env["jr"], env["ts"]
    wt = str((env["tmp"] / "sess-wt"))
    Path(wt).mkdir(parents=True, exist_ok=True)
    s = _register_session(reg, worktree_path=wt)
    sid = s["session_id"]

    # A job launched with cwd == the session's worktree mints a SWARM_LANE session
    # record carrying worktree_path == cwd (job_runner._register_swarm_session).
    job = env["launch"](cwd=wt)
    jid = job["job_id"]
    swarm_rec = reg.get_session(jid)
    assert swarm_rec is not None and swarm_rec["lane"] == jr.SWARM_LANE
    assert swarm_rec["status"] == reg.STATUS_RUNNING

    # No explicit claim on the session — ownership is derived from the shared
    # worktree alone.
    assert reg.owned_jobs(sid) == []
    out = ts._teardown_owned_jobs(sid, record=reg.get_session(sid))

    assert jid in out["cancelled"]
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED
    assert _wait_pid_dead(job["pid"])


# ── (2) reference-counted survival: a live successor keeps the job ────────────

def test_handed_off_job_survives_when_a_live_successor_claims_it(env):
    """A job handed off to / shared with a LIVE successor in the chain survives the
    predecessor's kill, the reference count shows the live claimant, and the
    ownership transfer is recorded (predecessor releases, successor keeps)."""
    reg, jr, ts = env["reg"], env["jr"], env["ts"]
    pred = _register_session(reg)  # RUNNING predecessor
    p_sid = pred["session_id"]
    succ = _register_session(reg, parent_session_id=p_sid,
                             chain_id=pred["chain_id"])  # RUNNING successor
    s_sid = succ["session_id"]

    shared = env["launch"]()
    jid = shared["job_id"]
    # Both the predecessor and the live successor claim the shared job.
    reg.claim_job(p_sid, jid)
    reg.claim_job(s_sid, jid)

    out = ts._teardown_owned_jobs(p_sid, record=reg.get_session(p_sid))

    # The shared job SURVIVES — never cancelled.
    assert out["cancelled"] == []
    assert [t["job_id"] for t in out["transferred"]] == [jid]
    assert out["transferred"][0]["to"] == s_sid, "transfer recorded to successor"
    assert jr.load_record(jid)["status"] == jr.STATUS_RUNNING, \
        "a shared job with a live claimant must NOT be reaped"
    assert _pid_alive(shared["pid"]), "the shared job's process stays alive"
    # Ownership transfer: predecessor released its claim, successor still owns it.
    assert reg.owned_jobs(p_sid) == []
    assert reg.owned_jobs(s_sid) == [jid]


def test_job_reaped_when_the_only_other_claimant_is_dead(env):
    """Reference counting keys on a LIVE claimant: if the other claimant is
    terminal (not live), the job has no live owner and IS reaped."""
    reg, jr, ts = env["reg"], env["jr"], env["ts"]
    pred = _register_session(reg)
    p_sid = pred["session_id"]
    dead = _register_session(reg, status=reg.STATUS_DONE)  # terminal, not live
    d_sid = dead["session_id"]

    job = env["launch"]()
    jid = job["job_id"]
    reg.claim_job(p_sid, jid)
    reg.claim_job(d_sid, jid)  # a DEAD session's claim must not keep it alive

    out = ts._teardown_owned_jobs(p_sid, record=reg.get_session(p_sid))
    assert jid in out["cancelled"]
    assert out["transferred"] == []
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED
    assert _wait_pid_dead(job["pid"])


# ── (3) targeted, not a full list_records scan ───────────────────────────────

def test_teardown_never_scans_the_full_job_store(env, monkeypatch):
    """The teardown walks ownership off the SESSION registry, never a full
    ``job_runner.list_records`` scan (the plan's explicit prohibition)."""
    reg, jr, ts = env["reg"], env["jr"], env["ts"]
    s = _register_session(reg)
    sid = s["session_id"]
    j1 = env["launch"]()
    reg.claim_job(sid, j1["job_id"])

    calls = {"list_records": 0}
    real = jr.list_records

    def _spy():
        calls["list_records"] += 1
        return real()

    monkeypatch.setattr(jr, "list_records", _spy)
    ts._teardown_owned_jobs(sid, record=reg.get_session(sid))
    assert calls["list_records"] == 0, \
        "teardown must reap per-job_id, never scan the whole job store"
    assert jr.load_record(j1["job_id"])["status"] == jr.STATUS_CANCELLED


# ── (4) the record is kept honest: reaped BEFORE marked terminal (kill) ──────

@pytest.fixture
def gitenv(tmp_path, monkeypatch):
    """Full terminal-session stack over a temp git repo + stub PTY + fake runner —
    for the kill() integration path (real worktree + persist + reap)."""
    if not _have_git():
        pytest.skip("git not on PATH")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
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
    import terminal_session, session_registry, job_runner, rnd_registry, pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    launched = []

    def _launch(cwd):
        rec = job_runner.launch("swarm", cwd=str(cwd),
                                extra_args=list(_ALIVE_ARGS), backend="claude")
        launched.append(rec["job_id"])
        return rec

    yield {"ts": terminal_session, "reg": session_registry, "jr": job_runner,
           "rnd": rnd_registry, "pty": pty_manager, "repo": repo,
           "pid": proj["id"], "launch": _launch}

    for jid in launched:
        try:
            job_runner.cancel(jid)
        except Exception:
            pass
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def test_kill_reaps_owned_job_before_marking_record_terminal(gitenv, monkeypatch):
    """THE honesty invariant: at the instant kill() marks the session DONE, its
    owned job is ALREADY cancelled/terminal — the record is never hidden while an
    owned job is still live."""
    ts, reg, jr = gitenv["ts"], gitenv["reg"], gitenv["jr"]
    sess = ts.start_session(gitenv["pid"], "plan", backend="claude")
    sid = sess["session_id"]

    job = gitenv["launch"](cwd=sess["worktree_path"])
    jid = job["job_id"]
    reg.claim_job(sid, jid)
    assert jr.load_record(jid)["status"] == jr.STATUS_RUNNING
    assert _pid_alive(job["pid"])

    seen = {"job_terminal_when_marked_done": None, "done_write_count": 0}
    real_update = reg.update_session

    def _spy_update(session_id, **fields):
        if session_id == sid and fields.get("status") == reg.STATUS_DONE:
            seen["done_write_count"] += 1
            jr_rec = jr.load_record(jid) or {}
            seen["job_terminal_when_marked_done"] = (
                jr_rec.get("status") in jr.TERMINAL_STATUSES)
        return real_update(session_id, **fields)

    # terminal_session looks up update_session as the module attr at call time,
    # so patching the module attr is what the DONE write picks up.
    monkeypatch.setattr(reg, "update_session", _spy_update)
    out = ts.kill(sid, project_id=gitenv["pid"])

    assert out["ok"] is True
    assert jid in (out.get("jobs") or {}).get("cancelled", []), \
        "kill's report must show the owned job was cancelled"
    assert seen["done_write_count"] >= 1, "kill must mark the record terminal"
    assert seen["job_terminal_when_marked_done"] is True, \
        "owned jobs must be confirmed reaped BEFORE the record is marked DONE"
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED
    assert _wait_pid_dead(job["pid"])
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE


def test_delete_session_tears_down_owned_jobs(gitenv):
    """term_delete tears down the PTY AND every owned job (the leak is closed on
    the delete path too), then removes the record."""
    ts, reg, jr = gitenv["ts"], gitenv["reg"], gitenv["jr"]
    sess = ts.start_session(gitenv["pid"], "plan", backend="claude")
    sid = sess["session_id"]
    job = gitenv["launch"](cwd=sess["worktree_path"])
    jid = job["job_id"]
    reg.claim_job(sid, jid)

    out = ts.delete_session(sid, project_id=gitenv["pid"])
    assert out["ok"] is True
    assert reg.get_session(sid) is None, "the record is removed (stays gone)"
    assert jr.load_record(jid)["status"] == jr.STATUS_CANCELLED, \
        "delete reaps the owned job — no orphan swarm survives"
    assert _wait_pid_dead(job["pid"])
