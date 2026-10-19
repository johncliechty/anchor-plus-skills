"""Wave 7 — Stage handoffs (hermetic).

Locks the v3 build→plan stage handoff (MASTER-PLAN §G, Implementation-Plan
Wave 7): when a BUILD session is launched, Anchor discovers the most-recent plan
set (newest planning session, seed_session override, or discovery.json
fallback), primes the session worktree with a HANDOFF reference file SURFACING
the plan doc paths (which already exist in the checkout — never copied), and
records the handoff structure-only in ``discovery.json``. It SURFACES + RECORDS;
it never auto-runs a skill (Wave-3 bare-PTY contract).

Hermetic: NO real claude/gemini and NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
TEMP git repo per test for the worktree, a tmp data dir + tmp worktree base. NO
worktree is ever created off the real ``C:\\dev\\Anchor`` repo.
"""
import importlib
import json
import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + a temp git repo + project."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    import paths
    importlib.reload(paths)
    import pty_manager
    importlib.reload(pty_manager)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_marker
    importlib.reload(anchor_marker)
    import session_registry
    importlib.reload(session_registry)
    import worktrees
    importlib.reload(worktrees)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import handoff
    importlib.reload(handoff)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    yield {
        "handoff": handoff, "ts": terminal_session, "eh": effort_history,
        "sessions": sessions, "marker": anchor_marker, "rnd": rnd_registry,
        "pty": pty_manager, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _add_plan_session(eh, repo, pid, plan_dir, created_at):
    """Record a discovered planning session (one parent dir = one session).

    Writes the actual plan files into the repo so the worktree checkout has
    them, and records discovered effort pointer-records so list_sessions groups
    them as ONE planning session.
    """
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log_rel = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n"),
                      (log_rel, "# Execution Log\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    specs = [
        (master_rel, "plan-doc", "Master Plan"),
        (impl_rel, "plan-doc", "Implementation Plan"),
        (log_rel, "plan-doc", "Execution Log"),
    ]
    for i, (rel, kind, title) in enumerate(specs):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid,
            skill="Crucible",
            extra={
                "source": eh.SOURCE_DISCOVERED,
                "kind": kind,
                "title": title,
                "artifact_path": rel,
                "status": "imported",
                "created_at": created_at + i * 0.001,
            },
        )
    return {"master_rel": master_rel, "impl_rel": impl_rel, "log_rel": log_rel}


# ── Most-recent-plan discovery ───────────────────────────────────────────────

def test_discover_returns_newest_plan_set(env):
    eh, repo, pid, ho = env["eh"], env["repo"], env["pid"], env["handoff"]
    older = _add_plan_session(eh, repo, pid, "planning/rnd-v1", created_at=1000.0)
    newer = _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    ps = ho.discover_recent_plan_set(repo, pid)
    assert ps is not None
    assert ps["plan_dir"] == "planning/rnd-v3"
    assert ps["master_plan_rel"] == newer["master_rel"]
    assert ps["impl_plan_rel"] == newer["impl_rel"]
    # The older set's docs are NOT what's returned.
    assert older["master_rel"] not in ps["doc_rels"]


def test_seed_session_overrides_to_specific_older_set(env):
    eh, repo, pid, ho = env["eh"], env["repo"], env["pid"], env["handoff"]
    sessions = env["sessions"]
    _add_plan_session(eh, repo, pid, "planning/rnd-v1", created_at=1000.0)
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    # Find the OLDER session's id (the rnd-v1 group).
    all_sessions = sessions.list_sessions(repo, pid, "planning")
    older_sid = None
    for s in all_sessions:
        if any("rnd-v1" in (m.get("artifact_path") or "")
               for m in s["member_files"]):
            older_sid = s["session_id"]
            break
    assert older_sid is not None

    ps = ho.discover_recent_plan_set(repo, pid, source_session_id=older_sid)
    assert ps is not None
    assert ps["plan_session_id"] == older_sid
    assert ps["plan_dir"] == "planning/rnd-v1"


def test_discover_none_when_no_plan_set(env):
    repo, pid, ho = env["repo"], env["pid"], env["handoff"]
    assert ho.discover_recent_plan_set(repo, pid) is None


def test_discovery_json_fallback(env):
    """With no session efforts, fall back to discovery.json by_lane.planning."""
    repo, pid, ho, marker = (env["repo"], env["pid"], env["handoff"],
                             env["marker"])
    sidecar = marker.sidecar_path(repo, pid)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({
        "by_lane": {
            "planning": [
                {"rel": "planning/rnd-v2/MASTER-PLAN.md", "kind": "plan-doc",
                 "title": "MP", "mtime": 500.0},
                {"rel": "planning/rnd-v2/IMPLEMENTATION-PLAN.md",
                 "kind": "plan-doc", "title": "IP", "mtime": 510.0},
                {"rel": "planning/rnd-v1/MASTER-PLAN.md", "kind": "plan-doc",
                 "title": "old MP", "mtime": 100.0},
            ],
        },
    }), encoding="utf-8")
    ps = ho.discover_recent_plan_set(repo, pid)
    assert ps is not None
    # The newer (rnd-v2) group wins on mtime.
    assert ps["plan_dir"] == "planning/rnd-v2"
    assert ps["master_plan_rel"] == "planning/rnd-v2/MASTER-PLAN.md"
    assert ps["impl_plan_rel"] == "planning/rnd-v2/IMPLEMENTATION-PLAN.md"


# ── confirm → prime ──────────────────────────────────────────────────────────

def test_launch_build_primes_worktree_inside_worktree(env):
    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    ts, ho = env["ts"], env["handoff"]
    from pathlib import Path
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    rec = ts.start_session(pid, "build", backend="claude")
    wt = rec["worktree_path"]
    # No worktree off the build repo.
    assert str(env["wbase"]) in wt
    assert str(repo) not in wt

    plan_set = ho.discover_recent_plan_set(repo, pid)
    primed = ho.prime_worktree(wt, plan_set, project_id=pid)
    assert primed["ok"] is True

    hf = Path(primed["handoff_file"])
    # The HANDOFF file is INSIDE the worktree root.
    assert hf.exists()
    assert hf.parent == Path(wt)
    assert str(env["wbase"]) in str(hf)
    assert str(repo) not in str(hf)

    text = hf.read_text(encoding="utf-8")
    # It names the plan docs (surfaces paths; does not copy contents).
    assert "planning/rnd-v3/MASTER-PLAN.md" in text
    assert "planning/rnd-v3/IMPLEMENTATION-PLAN.md" in text
    # Bare-PTY contract: no skill is auto-seeded / run.
    assert "skill" not in text.lower() or "no skill" in text.lower()

    ts.kill(rec["session_id"])


def test_worktree_list_clean_after_session(env):
    """The build repo must list only its main tree (no leaked worktrees)."""
    eh, repo, pid, ts = env["eh"], env["repo"], env["pid"], env["ts"]
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)
    rec = ts.start_session(pid, "build", backend="claude")
    # While live, the worktree is under the managed base, not the repo tree.
    listing = _git(repo, "worktree", "list").stdout
    assert str(env["wbase"]).replace("\\", "/") in listing.replace("\\", "/") \
        or str(rec["worktree_path"]).replace("\\", "/") in listing.replace("\\", "/")
    ts.kill(rec["session_id"])
    # After kill the worktree is reaped → only the main tree remains.
    listing2 = _git(repo, "worktree", "list").stdout.strip().splitlines()
    assert len(listing2) == 1


def test_prime_no_plan_set_is_clean(env):
    ho = env["handoff"]
    out = ho.prime_worktree(str(env["wbase"]), None)
    assert out["ok"] is False
    assert out["reason"] == "no-plan-set"


# ── Anchor reference record ──────────────────────────────────────────────────

def test_record_handoff_appends_to_discovery_json(env):
    eh, repo, pid, ho, marker = (env["eh"], env["repo"], env["pid"],
                                 env["handoff"], env["marker"])
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)
    plan_set = ho.discover_recent_plan_set(repo, pid)

    out = ho.record_handoff(repo, pid, "build-sid-1", plan_set)
    assert out["ok"] is True
    assert out["count"] == 1

    sidecar = marker.sidecar_path(repo, pid)
    disc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "handoffs" in disc
    h = disc["handoffs"][0]
    assert h["build_session_id"] == "build-sid-1"
    assert h["plan_session_id"] == plan_set["plan_session_id"]
    assert "planning/rnd-v3/MASTER-PLAN.md" in h["doc_rels"]
    # Structure-only: NO file contents / secrets embedded.
    blob = json.dumps(disc)
    assert "# Master Plan" not in blob  # the actual file body never leaks


def test_record_handoff_idempotent_ish(env):
    eh, repo, pid, ho, marker = (env["eh"], env["repo"], env["pid"],
                                 env["handoff"], env["marker"])
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)
    plan_set = ho.discover_recent_plan_set(repo, pid)

    ho.record_handoff(repo, pid, "build-sid-1", plan_set)
    second = ho.record_handoff(repo, pid, "build-sid-1", plan_set)
    # Re-recording the SAME (build, plan) pair updates in place — no dup.
    assert second["count"] == 1

    # A DIFFERENT build session appends a new entry without corruption.
    third = ho.record_handoff(repo, pid, "build-sid-2", plan_set)
    assert third["count"] == 2
    sidecar = marker.sidecar_path(repo, pid)
    disc = json.loads(sidecar.read_text(encoding="utf-8"))  # still valid JSON
    assert len(disc["handoffs"]) == 2


# ── propose_handoff / endpoint shape ─────────────────────────────────────────

def test_propose_handoff_build_vs_nonbuild(env):
    eh, repo, pid, ho = env["eh"], env["repo"], env["pid"], env["handoff"]
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    prop = ho.propose_handoff(repo, pid, "build")
    assert prop["has_plan_set"] is True
    assert "plan_set" in prop
    assert "Execute on this plan set" in prop["message"]

    # Non-build lane → focused: no handoff.
    assert ho.propose_handoff(repo, pid, "research")["has_plan_set"] is False


def test_propose_handoff_no_plan_set(env):
    repo, pid, ho = env["repo"], env["pid"], env["handoff"]
    assert ho.propose_handoff(repo, pid, "build")["has_plan_set"] is False


# ── FIX 1 — handoff record SURVIVES a rescan (write_anchor_md) ────────────────

def test_handoff_survives_rescan(env):
    """BLOCKER regression: record_handoff appends ``handoffs`` to discovery.json,
    but write_anchor_md (a rescan / GET /project/<id> open) used to overwrite the
    sidecar wholesale with scan.to_dict(), DROPPING handoffs. After the fix, the
    handoffs record must SURVIVE a rescan AND a second no-op rescan."""
    eh, repo, pid, ho, marker = (env["eh"], env["repo"], env["pid"],
                                 env["handoff"], env["marker"])
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)
    plan_set = ho.discover_recent_plan_set(repo, pid)

    # Record the handoff (writes handoffs[] into discovery.json).
    out = ho.record_handoff(repo, pid, "build-sid-1", plan_set)
    assert out["ok"] is True
    sidecar = marker.sidecar_path(repo, pid)
    assert "handoffs" in json.loads(sidecar.read_text(encoding="utf-8"))

    # A rescan rewrites the sidecar — handoffs must NOT be dropped.
    marker.write_anchor_md(repo)
    disc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "handoffs" in disc, "rescan dropped the handoffs record (data loss)"
    assert disc["handoffs"][0]["build_session_id"] == "build-sid-1"
    # Scan-owned keys are still present (the merge kept the scan content too).
    assert "by_lane" in disc and "counts" in disc

    # A SECOND no-op rescan still preserves handoffs (no churn, no drop).
    marker.write_anchor_md(repo)
    disc2 = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "handoffs" in disc2
    assert disc2["handoffs"][0]["build_session_id"] == "build-sid-1"


# ── FIX 2 — end-to-end HTTP wiring (do_POST term_start → prime → record) ──────

def _free_loopback_server(gui):
    import threading
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def test_http_term_start_build_primes_and_records(env, monkeypatch):
    """Drive POST /api/rnd/term_start for a BUILD lane over a real port-0 server:
    the response carries handoff info, the worktree gets HANDOFF.md, and
    discovery.json gets the handoffs record — exercising the real do_POST path."""
    import importlib
    import json as _json
    import urllib.request as _urlreq
    from pathlib import Path

    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    ho, marker, ts = env["handoff"], env["marker"], env["ts"]
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    import anchor_gui
    importlib.reload(anchor_gui)

    server, port = _free_loopback_server(anchor_gui)
    sid = None
    try:
        payload = _json.dumps({"project_id": pid, "lane": "build",
                               "backend": "claude"}).encode("utf-8")
        req = _urlreq.Request(
            f"http://127.0.0.1:{port}/api/rnd/term_start", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with _urlreq.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        sid = data["session"]["session_id"]
        # Response carries handoff info.
        assert "handoff" in data
        assert data["handoff"]["plan_set"]["plan_dir"] == "planning/rnd-v3"
        assert data["handoff"]["recorded"] is True

        # The worktree got HANDOFF.md (off the managed base, not the build repo).
        wt = data["session"]["worktree_path"]
        assert str(env["wbase"]) in wt
        assert str(repo) not in wt
        hf = Path(wt) / ho.HANDOFF_FILENAME
        assert hf.exists()
        assert "planning/rnd-v3/MASTER-PLAN.md" in hf.read_text(encoding="utf-8")

        # discovery.json got the handoffs record.
        disc = _json.loads(
            marker.sidecar_path(repo, pid).read_text(encoding="utf-8"))
        assert "handoffs" in disc
        assert disc["handoffs"][0]["build_session_id"] == sid
    finally:
        if sid:
            try:
                ts.kill(sid)
            except Exception:
                pass
        server.shutdown()
        server.server_close()

    # No worktree leaked off the build repo.
    listing = _git(repo, "worktree", "list").stdout.strip().splitlines()
    assert len(listing) == 1


def test_http_handoff_proposal_endpoint(env):
    """GET /api/rnd/handoff_proposal: has_plan_set true when a plan is set; a
    traversal pid is rejected 400 (symmetric with the lane/seed guards)."""
    import importlib
    import json as _json
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    eh, repo, pid = env["eh"], env["repo"], env["pid"]
    _add_plan_session(eh, repo, pid, "planning/rnd-v3", created_at=2000.0)

    import anchor_gui
    importlib.reload(anchor_gui)
    server, port = _free_loopback_server(anchor_gui)
    try:
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{port}/api/rnd/handoff_proposal?"
               f"project_id={_q(pid)}&lane=build")
        with _urlreq.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["has_plan_set"] is True
        assert "plan_set" in data

        # Traversal pid → 400.
        url2 = (f"http://127.0.0.1:{port}/api/rnd/handoff_proposal?"
                f"project_id={_q('../../etc')}&lane=build")
        try:
            with _urlreq.urlopen(url2, timeout=10) as r:
                code, body = r.getcode(), _json.loads(r.read().decode("utf-8"))
        except _urlerr.HTTPError as e:
            code, body = e.code, _json.loads(e.read().decode("utf-8"))
        assert code == 400
        assert body["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
