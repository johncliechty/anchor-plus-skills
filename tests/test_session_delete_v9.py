"""v9 Wave 1 — True session delete (keep documents; Option A).

DELETE is DISTINCT from the v8 KILL. KILL ends a *running* session: it reaps the
PTY, persists the produced docs into the main folder, removes the worktree, and
marks the registry record DONE — the record + its board tile PERSIST so the work
is resumable. DELETE *removes the session from Anchor entirely*:

  - the registry record is hard-deleted (``session_registry.remove_session``) →
    ``term_sessions`` / ``_gather_project_sessions`` / ``sessions.list_sessions``
    no longer surface it, so the tile STAYS gone across a reload (the v6 key bug
    for kills is moot for delete — the record is GONE);
  - the session's lane effort POINTER-RECORDS + index entries + cached summary
    are removed;
  - but the produced DOCUMENTS are KEPT on disk (Option A) — only the Anchor
    pointer-records / cache (which merely reference them) are dropped.

Plus: ``cleanup_ghost_sessions`` removes empty DONE records with no efforts; the
``term_delete`` endpoint is token-gated AND requires an explicit ``confirm``; the
panel's red ✕ delete control is present + DISTINCT from the 🗑 kill control.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, a temp git repo for the worktree, a tmp
data dir + tmp worktree base, the STUB summarizer runner. NEVER binds ``:8777``;
NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real push/gh/network.
"""
import importlib
import json
import re
import subprocess
import threading
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


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


# ── env / fixtures (stub PTY + temp git repo + project + STUB summarizer) ─────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + worktree base + stub PTY + STUB summarizer + a temp git repo
    + a registered project, proactive summaries ON so the kill path caches a real
    summary (so delete has a summary dir to remove). Full stack reloaded against
    the isolated env (worktrees off the TEMP repo, never C:\\dev)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The locked north star is durable resumable work")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import terminal_session
    import session_registry
    import sessions
    import summarizer
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "eh": effort_history, "sessions": sessions, "summ": summarizer,
        "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_build_docs(worktree_path, plan_dir="build/rnd-x"):
    """Stand in for what Foreman would write in the session's worktree."""
    wt = Path(worktree_path)
    north = f"{plan_dir}/NORTH-STAR.md"
    deliv = f"{plan_dir}/DELIVERABLE.md"
    log = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [
            (north, "# North Star\nThe locked north star is durable resumable work.\n"),
            (deliv, "# Deliverable\nThe widget service ships.\n"),
            (log, "# Execution Log\nWave 1 GREEN.\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"north": north, "deliv": deliv, "log": log}


def _make_killed_session(env, lane="build", plan_dir="build/rnd-x"):
    """Start → write docs → kill a session, returning (sid, docs). After this the
    docs are PERSISTED into the main folder, the session is DONE, and (proactive)
    a cached summary lands. This is the realistic "finished session" delete acts on."""
    ts, summ, repo, pid = env["ts"], env["summ"], env["repo"], env["pid"]
    sess = ts.start_session(pid, lane, backend="claude")
    sid = sess["session_id"]
    docs = _write_build_docs(sess["worktree_path"], plan_dir=plan_dir)
    out = ts.kill(sid)
    assert out["docs"]["ok"] is True
    # Force-cache a summary keyed to the managed id so delete has a dir to remove.
    durable = env["gui"]._resolve_finished_session(str(repo), pid, lane, sid)
    if durable is not None:
        summ.summarize_session(str(repo), pid, lane, durable, force=True)
    return sid, docs


def _js(html):
    return "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", html))


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    return b


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


# ════════════════════════════════════════════════════════════════════════════
# (1) BACKEND — delete clears record + efforts + summary; KEEPS the documents
# ════════════════════════════════════════════════════════════════════════════

def test_delete_clears_record_efforts_summary_keeps_docs(env):
    ts, eh, summ, reg, sessions, repo, pid = (
        env["ts"], env["eh"], env["summ"], env["reg"], env["sessions"],
        env["repo"], env["pid"])
    sid, docs = _make_killed_session(env, lane="build")

    # Pre-conditions: the session resolves everywhere, the docs exist on disk,
    # and there ARE session-tagged efforts + a cached summary.
    assert reg.get_session(sid) is not None
    tagged = eh.efforts_for_session_id(str(repo), pid, "build", sid)
    assert tagged, "expected session-tagged efforts before delete"
    assert (repo / docs["deliv"]).is_file()
    assert summ.load_cached(str(repo), pid, "build", sid) is not None
    sdir = eh.session_summary_dir(str(repo), pid, "build", sid)
    assert sdir.is_dir(), "expected a cached summary dir before delete"

    # DELETE.
    out = ts.delete_session(sid)
    assert out["ok"] is True
    assert out["deleted"] is True

    # Registry record gone.
    assert reg.get_session(sid) is None
    # Effort pointer-records + index entries gone (the join is now empty).
    assert eh.efforts_for_session_id(str(repo), pid, "build", sid) == []
    # Cached summary dir gone.
    assert not sdir.exists()
    assert summ.load_cached(str(repo), pid, "build", sid) is None
    # OPTION A: the produced DOCUMENTS still exist on disk.
    assert (repo / docs["deliv"]).is_file()
    assert (repo / docs["north"]).is_file()
    assert (repo / docs["log"]).is_file()


def test_delete_drops_from_listings_and_survives_reload(env):
    ts, gui, reg, sessions, repo, pid = (
        env["ts"], env["gui"], env["reg"], env["sessions"], env["repo"],
        env["pid"])
    sid, _docs = _make_killed_session(env, lane="research", plan_dir="research/r1")

    # Present in the board gather + sessions.list_sessions before delete.
    sess_before = sessions.list_sessions(str(repo), pid, "research")
    assert any(s.get("session_id") == sid for s in sess_before) or \
        any(sid in (e.get("session_id") or "")
            for s in sess_before for e in s.get("member_files", [])), \
        "session/efforts should be visible before delete"

    ts.delete_session(sid)

    # sessions.list_sessions no longer regroups it (its efforts are gone).
    sess_after = sessions.list_sessions(str(repo), pid, "research")
    for s in sess_after:
        assert s.get("session_id") != sid
        for e in s.get("member_files", []):
            assert (e.get("session_id") or "") != sid

    # _gather_project_sessions (board bridge) no longer surfaces it.
    gathered = gui._gather_project_sessions(str(repo), pid)
    for col_views in gathered.values():
        for v in col_views:
            assert v.get("session_id") != sid

    # Survives a reconcile (the registry record is truly gone, not just re-statused).
    reg.reconcile(live_session_ids=[])
    assert reg.get_session(sid) is None


def test_delete_is_idempotent(env):
    ts, reg = env["ts"], env["reg"]
    sid, _docs = _make_killed_session(env, lane="build")
    first = ts.delete_session(sid)
    assert first["deleted"] is True
    # Second delete: clean no-op (record already gone), never raises.
    second = ts.delete_session(sid)
    assert second["ok"] is True
    assert second["deleted"] is False
    assert reg.get_session(sid) is None


def test_delete_unknown_session_no_raise(env):
    ts = env["ts"]
    out = ts.delete_session("does-not-exist")
    assert out["ok"] is True
    assert out["deleted"] is False


def test_delete_live_session_kills_first(env):
    """A still-LIVE session can be deleted: it is killed (PTY reaped + worktree
    removed) first, THEN the record is dropped."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    wt = Path(sess["worktree_path"])
    assert wt.is_dir()
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    out = ts.delete_session(sid)
    assert out["ok"] is True
    assert out["deleted"] is True
    assert out["killed"] is True
    assert reg.get_session(sid) is None
    assert not wt.is_dir(), "live-session delete should reap the worktree"


def test_cleanup_ghost_sessions_removes_empty_done_record(env):
    """An empty DONE registry record with NO efforts is a ghost → cleanup removes
    it; a session WITH efforts and a RUNNING session are left alone."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    # A ghost: register a DONE record directly (no efforts ever tied to it).
    ghost = reg.register_session(pid, "build", status=reg.STATUS_DONE,
                                 label="ghost")["session_id"]
    # A real finished session WITH efforts.
    real, _docs = _make_killed_session(env, lane="build", plan_dir="build/keep")
    # A live running session.
    live = ts.start_session(pid, "research", backend="claude")["session_id"]

    out = ts.cleanup_ghost_sessions(pid)
    assert out["ok"] is True
    assert ghost in out["removed"]
    assert real not in out["removed"], "a session with efforts is NOT a ghost"
    assert live not in out["removed"], "a running session must never be swept"

    assert reg.get_session(ghost) is None
    assert reg.get_session(real) is not None
    assert reg.get_session(live) is not None


# ════════════════════════════════════════════════════════════════════════════
# (2) ENDPOINT — term_delete token-gated + confirm-required + deletes on confirm
# ════════════════════════════════════════════════════════════════════════════

def _post(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_term_delete_requires_token(env, monkeypatch):
    """With ANCHOR_TOKEN set, an unauthed term_delete is 401 (record untouched)."""
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(importlib.import_module("paths"))
    gui = importlib.reload(env["gui"])
    sid, _docs = _make_killed_session(env, lane="build")

    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/term_delete",
                           {"session": sid, "confirm": True})  # no token
        assert code == 401
        assert data.get("error") == "unauthorized"
        # The record is still there (the unauthed call did nothing).
        assert env["reg"].get_session(sid) is not None
        # With the token it succeeds.
        code, data = _post(port, "/api/rnd/term_delete",
                           {"session": sid, "confirm": True}, token="s3cret")
        assert code == 200 and data["ok"] is True and data["deleted"] is True
        assert env["reg"].get_session(sid) is None
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_term_delete_requires_confirm(env):
    """Without confirm:true the endpoint REFUSES (the record is untouched)."""
    gui = env["gui"]
    sid, _docs = _make_killed_session(env, lane="build")
    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/term_delete", {"session": sid})
        assert code == 400
        assert data.get("reason") == "confirm-required"
        assert env["reg"].get_session(sid) is not None  # untouched
        # confirm:false is also a refusal.
        code, data = _post(port, "/api/rnd/term_delete",
                           {"session": sid, "confirm": False})
        assert code == 400
        assert env["reg"].get_session(sid) is not None
        # confirm:true deletes.
        code, data = _post(port, "/api/rnd/term_delete",
                           {"session": sid, "confirm": True})
        assert code == 200 and data["deleted"] is True
        assert env["reg"].get_session(sid) is None
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_cleanup_endpoint_token_and_confirm(env, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "tok")
    importlib.reload(importlib.import_module("paths"))
    gui = importlib.reload(env["gui"])
    pid = env["pid"]
    ghost = env["reg"].register_session(pid, "build", status=env["reg"].STATUS_DONE,
                                        label="ghost")["session_id"]
    srv, port, t = _free_server(gui)
    try:
        # unauthed → 401
        code, _ = _post(port, "/api/rnd/cleanup_ghost_sessions",
                        {"project_id": pid, "confirm": True})
        assert code == 401
        # authed but no confirm → 400
        code, data = _post(port, "/api/rnd/cleanup_ghost_sessions",
                           {"project_id": pid}, token="tok")
        assert code == 400 and data.get("reason") == "confirm-required"
        # authed + confirm → removes the ghost
        code, data = _post(port, "/api/rnd/cleanup_ghost_sessions",
                           {"project_id": pid, "confirm": True}, token="tok")
        assert code == 200 and ghost in data["removed"]
        assert env["reg"].get_session(ghost) is None
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (3) DOM — the W6-unified panel scheme: a '×' CLOSE + a single '🪦' Kill ->
#     Boneyard. The old panel TRUE-delete (red ✕) / 🗑 hardkill controls are gone.
# ════════════════════════════════════════════════════════════════════════════

class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def test_dom_panel_controls_present_and_distinct(env):
    """Realigned to the W6-unified panel scheme. The session PANEL no longer
    carries a separate '.panelbtn.delete' TRUE-delete control — W6 collapsed the
    old redundant close/hardkill/delete trio into exactly two lifecycle controls:

      POSITIVE — a '×' graceful CLOSE ('.panelbtn.close' -> closePanel, POST
        term_close) and a single '🪦' Kill -> Boneyard ('.panelbtn.killbone' ->
        killPanel, POST term_kill) as the ONE destructive control.
      NEGATIVE — the panel builds NO '.panelbtn.delete' control (no delBtn / red
        ✕) and NO old 🗑 '.panelbtn.hardkill'. close and kill are distinct
        (distinct class, glyph, handler, endpoint)."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    js = _js(html)
    css = "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", html))

    # POSITIVE — the '×' graceful CLOSE control (closePanel -> POST term_close).
    assert "panelbtn close" in js, "no .panelbtn.close control created"
    assert "closePanel(sessionId)" in js, "close control not wired to closePanel"
    assert "/api/rnd/term_close" in js, "closePanel must POST term_close"
    assert "closeBtn.textContent = '×'" in js, "close glyph is not ×"

    # POSITIVE — the single '🪦' Kill -> Boneyard control (killPanel -> term_kill).
    assert "panelbtn killbone" in js, "no .panelbtn.killbone control created"
    assert "killPanel(sessionId)" in js, "kill control not wired to killPanel"
    assert "/api/rnd/term_kill" in js
    assert "killBtn.textContent = '🪦'" in js, "kill glyph is not the headstone 🪦"

    # NEGATIVE — the panel builds no TRUE-delete control (W6): no red-✕ delBtn and
    # no 'panelbtn delete', and no old 🗑 'panelbtn hardkill'. Close and kill are
    # not the same control (distinct glyph).
    assert "delBtn" not in js, "the panel TRUE-delete control (delBtn) must be gone"
    assert "'panelbtn delete'" not in js and '"panelbtn delete"' not in js
    assert "'panelbtn hardkill'" not in js and '"panelbtn hardkill"' not in js
    assert "killBtn.textContent = '×'" not in js
    assert "closeBtn.textContent = '🪦'" not in js
    # The CSS styles the killbone danger control distinctly.
    assert ".panelbtn.killbone" in css, "no distinct CSS for the kill control"


def test_dom_delete_is_confirm_gated(env):
    """deletePanel must be confirm()-gated (an irreversible removal)."""
    gui = env["gui"]
    js = _js(gui.render_project_window_html(env["pid"]))
    # The deletePanel body must guard on confirm(...) and bail (return) on cancel.
    m = re.search(r"async function deletePanel\([\s\S]*?\n\}", js)
    assert m, "deletePanel function not found"
    body = m.group(0)
    assert "confirm(" in body, "deletePanel is not confirm-gated"
    assert "return" in body.split("confirm(")[0] + body, "no early return on cancel"


# ════════════════════════════════════════════════════════════════════════════
# (4) RETIRED FEATURE — the bottom-dock TRUE-delete (#dockDelete) was REMOVED.
#
# The v9 dock second-✕ TRUE-delete control was removed from the UI by user
# decision: Kill -> Boneyard (#dockKill) reaps the session but PRESERVES the
# produced docs in the per-project Boneyard, so a separate hard-delete affordance
# is redundant. The former Playwright "delete tile → reload → stays gone" test
# exercised that now-removed control; it is retired here and replaced by a
# deterministic guard that #dockDelete stays gone and #dockKill (Kill -> Boneyard)
# is the single destructive dock control. (True-delete of a session is still
# reachable programmatically — the term_delete backend + endpoint remain covered
# by the section-(1)/(2) tests above.)
# ════════════════════════════════════════════════════════════════════════════

def test_dock_true_delete_removed_kill_to_boneyard_is_sole_destructive(env):
    """The bottom effort-dock now carries exactly two lifecycle controls, matching
    the W6-unified panel: a '×' graceful CLOSE (#dockClose) and the single '🪦'
    Kill -> Boneyard (#dockKill, .panelbtn.killbone) as the ONE destructive
    control. The v9 TRUE-delete (#dockDelete) was REMOVED — this guards that it
    stays gone."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])

    # POSITIVE — the dock's two lifecycle controls are present.
    assert "id='dockClose'" in html, "dock graceful-close (×) control missing"
    assert "id='dockKill'" in html, "dock Kill -> Boneyard control missing"
    assert "onclick='dockClose()'" in html
    assert "onclick='dockKill()'" in html
    # Kill -> Boneyard is the headstone killbone control (&#129702; == 🪦).
    assert "panelbtn killbone' id='dockKill'" in html, \
        "dock Kill control is not the .panelbtn.killbone headstone"
    assert "&#129702;" in html, "dock Kill glyph (headstone 🪦) missing"

    # NEGATIVE — the removed v9 TRUE-delete dock element must stay gone.
    assert "id='dockDelete'" not in html, \
        "the removed #dockDelete true-delete control reappeared"
