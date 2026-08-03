"""v8 Wave 3 gate — Link GitHub + Option-A auto-push (the offsite layer).

North-Star contract (IMPLEMENTATION-PLAN Wave 3):

  (a) ``link_github(mode='create')`` THROUGH the ``ANCHOR_GH_CMD`` seam (→
      ``tests/stub_gh.py``, which prints a fake repo URL and NEVER hits the
      network) persists the remote on the project record + wires ``origin``.
  (b) ``link_github(mode='existing')`` does ``git remote add origin <url>`` —
      here the "remote" is a LOCAL BARE repo at a ``file://`` path, so a real
      push has NO network.
  (c) The auto-push opt-in persists; ``auto_push_if_opted`` pushes ONLY when the
      project is BOTH linked AND opted-in — a non-linked OR non-opted project
      NEVER pushes (asserted against the local bare remote's ref log).
  (d) The kill/finish path's ``_auto_push_on_finish`` lands a push in the local
      bare remote ONLY for a linked+opted project.
  (e) Manual ``push_now`` lands a push in the local bare remote.
  (f) gh-absent (the stub fails like an un-authed gh) degrades a ``create`` to
      ``{reason:'gh-unavailable', suggest:'paste-url'}`` (paste-only).
  (g) All FOUR new POST endpoints are token-gated (401 unauthed).
  (h) DOM: the "Link GitHub" control is present; after linked, the auto-push
      toggle + "Push now" appear; an UNLINKED project shows neither.
  (i) Real Playwright/Chromium: Link GitHub → Create-new → linked state appears;
      toggle auto-push on; Push now → no JS console errors. Screenshot saved.

Never :8777, never real data / real network — stub gh, a LOCAL bare remote, stub
PTY, temp data dir + worktree base, a throwaway temp git repo.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
STUB_GH = (Path(__file__).resolve().parent / "stub_gh.py").as_posix()
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


def _bare_url(path):
    """A ``file://`` URL git accepts on this platform for a local bare repo."""
    return Path(path).resolve().as_uri()


# ── env / fixtures (stub gh + stub PTY, temp data+worktree, hermetic repos) ──

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + worktree base + stub PTY + fake runner + the gh SEAM pointed
    at stub_gh.py + a temp git repo (the project) + a LOCAL BARE repo (the
    "remote"). Reloads the full stack against the isolated env. NEVER real
    network / real gh / real github.com / :8777 / real data."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    # The gh seam → the hermetic stub. NEVER the real gh / network.
    monkeypatch.setenv("ANCHOR_GH_CMD", f"python {STUB_GH}")
    monkeypatch.delenv("ANCHOR_GH_STUB_FAIL", raising=False)
    monkeypatch.delenv("ANCHOR_GH_STUB_REMOTE", raising=False)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "summarizer", "handoff", "gate_adapter", "terminal_session",
                "project_remote"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import terminal_session as ts
    import session_registry as reg
    import project_remote as remote
    import rnd_registry

    # The PROJECT repo (a real git work tree).
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    # A LOCAL BARE repo standing in for the GitHub remote (file:// → no network).
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)],
                   capture_output=True, text=True)

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {"gui": gui, "ts": ts, "reg": reg, "remote": remote,
              "rnd": rnd_registry, "data": data, "repo": repo, "bare": bare,
              "bare_url": _bare_url(bare), "pid": proj["id"]}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _bare_has_main(bare):
    """True iff the local bare remote now has a ``refs/heads/main`` (a push landed)."""
    r = subprocess.run(["git", "-C", str(bare), "rev-parse",
                        "--verify", "--quiet", "refs/heads/main"],
                       capture_output=True, text=True)
    return r.returncode == 0


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=_json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, _json.loads(r.read().decode("utf-8"))


def _get(port, path):
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=20) as r:
        return r.status, _json.loads(r.read().decode("utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# (A) BACKEND — link (create via seam · existing via local bare) + persistence
# ════════════════════════════════════════════════════════════════════════════

def test_link_create_via_seam_persists_remote(env):
    """``create`` through the ANCHOR_GH_CMD seam (stub_gh prints a fake URL) wires
    origin + persists the remote on the project record. NO real github.com."""
    remote, repo, pid, rnd = env["remote"], env["repo"], env["pid"], env["rnd"]
    res = remote.link_github(str(repo), "create", "my-proj", project_id=pid)
    assert res["ok"] is True and res["linked"] is True
    assert res.get("private") is True, "default repos must be PRIVATE"
    assert res["remote_url"].startswith("https://github.com/")
    # Persisted on the record AND wired as origin locally.
    assert (rnd.get_project(pid).get("remote_url") or "") == res["remote_url"]
    got = _git(repo, "remote", "get-url", "origin")
    assert got.returncode == 0 and got.stdout.strip() == res["remote_url"]


def test_link_existing_local_bare_no_network(env):
    """``existing`` → git remote add origin <file:// bare>. No network at all."""
    remote, repo, pid, rnd = env["remote"], env["repo"], env["pid"], env["rnd"]
    res = remote.link_github(str(repo), "existing", env["bare_url"],
                             project_id=pid)
    assert res["ok"] is True and res["linked"] is True
    assert (rnd.get_project(pid).get("remote_url") or "") == env["bare_url"]
    got = _git(repo, "remote", "get-url", "origin")
    assert got.stdout.strip() == env["bare_url"]


def test_create_gh_unavailable_degrades_to_paste(env, monkeypatch):
    """When gh is unavailable (the stub exits non-zero like an un-authed gh), a
    ``create`` degrades cleanly to paste-only — never raises, never network."""
    remote, repo, pid = env["remote"], env["repo"], env["pid"]
    monkeypatch.setenv("ANCHOR_GH_STUB_FAIL", "1")
    res = remote.link_github(str(repo), "create", "x", project_id=pid)
    assert res["ok"] is False
    assert res["reason"] == "gh-unavailable"
    assert res.get("suggest") == "paste-url"


def test_auto_push_only_when_linked_and_opted(env):
    """auto_push_if_opted pushes ONLY when linked AND opted-in. A non-linked or
    non-opted project NEVER pushes (the local bare remote stays empty)."""
    remote, repo, pid, bare = (env["remote"], env["repo"], env["pid"],
                               env["bare"])
    # (1) Not linked, not opted → no push.
    assert remote.auto_push_if_opted(pid)["reason"] == "not-linked"
    assert not _bare_has_main(bare)

    # (2) Linked to the local bare, but NOT opted → still no push.
    remote.link_github(str(repo), "existing", env["bare_url"], project_id=pid)
    out = remote.auto_push_if_opted(pid)
    assert out["pushed"] is False and out["reason"] == "not-opted"
    assert not _bare_has_main(bare)

    # (3) Linked AND opted → the push lands in the local bare remote.
    remote.set_auto_push(pid, True)
    out2 = remote.auto_push_if_opted(pid)
    assert out2["ok"] is True and out2["pushed"] is True
    assert _bare_has_main(bare), "linked+opted push did not land in the bare remote"


def test_push_now_lands_in_local_bare(env):
    """Manual push_project lands a push in the local bare remote; an unlinked
    project returns no-remote (never raises)."""
    remote, repo, pid, bare = (env["remote"], env["repo"], env["pid"],
                               env["bare"])
    # Unlinked → honest no-remote.
    assert remote.push_project(str(repo), pid)["reason"] == "no-remote"
    assert not _bare_has_main(bare)
    # Linked → push lands.
    remote.link_github(str(repo), "existing", env["bare_url"], project_id=pid)
    out = remote.push_project(str(repo), pid)
    assert out["ok"] is True and out["pushed"] is True
    assert _bare_has_main(bare)


# ════════════════════════════════════════════════════════════════════════════
# (B) ENDPOINTS — the four POSTs + the read-only remote_status GET
# ════════════════════════════════════════════════════════════════════════════

def test_endpoint_link_create_then_status(env):
    """POST /api/rnd/link_github (create, via seam) → GET remote_status reflects
    linked=true with the fake URL."""
    gui, pid = env["gui"], env["pid"]
    srv, port, t = _free_server(gui)
    try:
        st0, d0 = _post(port, "/api/rnd/link_github",
                        {"project_id": pid, "mode": "create", "value": "proj"})
        assert st0 == 200 and d0["ok"] is True and d0["linked"] is True
        st1, d1 = _get(port, f"/api/rnd/remote_status?project_id={pid}")
        assert st1 == 200 and d1["ok"] is True
        assert d1["linked"] is True
        assert d1["remote_url"] == d0["remote_url"]
        assert d1["auto_push"] is False
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_endpoint_set_auto_push_persists(env):
    """POST /api/rnd/set_auto_push persists the opt-in (visible via remote_status)."""
    gui, pid = env["gui"], env["pid"]
    srv, port, t = _free_server(gui)
    try:
        _post(port, "/api/rnd/link_github",
              {"project_id": pid, "mode": "existing", "value": env["bare_url"]})
        sa, da = _post(port, "/api/rnd/set_auto_push",
                       {"project_id": pid, "enabled": True})
        assert sa == 200 and da["ok"] is True and da["auto_push"] is True
        _, d = _get(port, f"/api/rnd/remote_status?project_id={pid}")
        assert d["auto_push"] is True
        # Toggle back off.
        _post(port, "/api/rnd/set_auto_push",
              {"project_id": pid, "enabled": False})
        _, d2 = _get(port, f"/api/rnd/remote_status?project_id={pid}")
        assert d2["auto_push"] is False
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_endpoint_push_now_lands(env):
    """POST /api/rnd/push_now lands a push in the local bare remote when linked."""
    gui, pid, bare = env["gui"], env["pid"], env["bare"]
    srv, port, t = _free_server(gui)
    try:
        _post(port, "/api/rnd/link_github",
              {"project_id": pid, "mode": "existing", "value": env["bare_url"]})
        sp, dp = _post(port, "/api/rnd/push_now", {"project_id": pid})
        assert sp == 200 and dp["ok"] is True and dp["pushed"] is True
        assert _bare_has_main(bare)
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_auto_push_on_finish_via_kill_endpoint(env):
    """The kill path's _auto_push_on_finish lands a push ONLY for a linked+opted
    project: a started general session, linked + opted, killed via /api/rnd/
    term_kill → the push lands in the local bare remote."""
    gui, ts, pid, bare, remote = (env["gui"], env["ts"], env["pid"],
                                  env["bare"], env["remote"])
    remote.link_github(str(env["repo"]), "existing", env["bare_url"],
                       project_id=pid)
    remote.set_auto_push(pid, True)

    gen = ts.start_session(pid, "general", backend="claude")
    gsid = gen["session_id"]
    srv, port, t = _free_server(gui)
    try:
        sk, dk = _post(port, "/api/rnd/term_kill", {"session": gsid})
        assert sk == 200 and dk["ok"] is True
        assert _bare_has_main(bare), "auto-push-on-finish did not land a push"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_no_auto_push_on_finish_when_not_opted(env):
    """A linked but NON-opted project does NOT auto-push on kill (the local bare
    remote stays empty)."""
    gui, ts, pid, bare, remote = (env["gui"], env["ts"], env["pid"],
                                  env["bare"], env["remote"])
    remote.link_github(str(env["repo"]), "existing", env["bare_url"],
                       project_id=pid)
    # Deliberately NOT opted in.
    gen = ts.start_session(pid, "general", backend="claude")
    gsid = gen["session_id"]
    srv, port, t = _free_server(gui)
    try:
        sk, dk = _post(port, "/api/rnd/term_kill", {"session": gsid})
        assert sk == 200 and dk["ok"] is True
        assert not _bare_has_main(bare), "non-opted project must NOT auto-push"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


@pytest.mark.parametrize("path,payload", [
    ("/api/rnd/link_github", {"project_id": "x", "mode": "create"}),
    ("/api/rnd/set_auto_push", {"project_id": "x", "enabled": True}),
    ("/api/rnd/push_now", {"project_id": "x"}),
])
def test_endpoints_token_gated(env, monkeypatch, path, payload):
    """With ANCHOR_TOKEN set, each new mutating POST is 401 unauthed and 200/handled
    with the token. (link_github also covered; all three ride the do_POST gate.)"""
    gui = env["gui"]
    pid = env["pid"]
    payload = dict(payload, project_id=pid)
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    gui2 = importlib.reload(gui)
    srv, port, t = _free_server(gui2)
    try:
        # Unauthed → 401.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=20)
        assert ei.value.code == 401
        # Authed (header) → NOT a 401. The op may legitimately 200 (link/auto-push)
        # or 400 (push_now on an unlinked project) — only the 401 gate is asserted.
        authed = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "X-Anchor-Token": "sekret"}, method="POST")
        try:
            with urllib.request.urlopen(authed, timeout=20) as r:
                assert r.status != 401
        except urllib.error.HTTPError as he:
            assert he.code != 401, "authed POST was still rejected as unauthorized"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)


def test_remote_status_token_gated_get(env, monkeypatch):
    """The read-only remote_status GET gates via ?token= when a token is set."""
    gui, pid = env["gui"], env["pid"]
    monkeypatch.setenv("ANCHOR_TOKEN", "sekret")
    import paths
    importlib.reload(paths)
    gui2 = importlib.reload(gui)
    srv, port, t = _free_server(gui2)
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/rnd/remote_status?project_id={pid}",
                timeout=20)
        assert ei.value.code == 401
        st, d = _get(
            port,
            f"/api/rnd/remote_status?project_id={pid}&token=sekret")
        assert st == 200 and d["ok"] is True
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)


# ════════════════════════════════════════════════════════════════════════════
# (C) DOM — the Link GitHub control + linked/unlinked rendering (pos + neg)
# ════════════════════════════════════════════════════════════════════════════

class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


def test_dom_github_control_present(env):
    """The header renders the #ghRemote control host + the JS to populate it; the
    Link GitHub button is created by renderRemoteControls (asserted in the JS)."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    body = _strip(html)
    hosts = [a for tag, c, a in _parse(body) if a.get("id") == "ghRemote"]
    assert len(hosts) == 1, "the #ghRemote header control host is missing"
    # The JS wiring (in the script block, so assert against the full html).
    assert "renderRemoteControls" in html
    assert "/api/rnd/remote_status" in html
    assert "Link GitHub" in html
    assert "linkGithub" in html


def test_dom_autopush_and_pushnow_wired_in_js(env):
    """POSITIVE: the linked-state controls (auto-push toggle + Push now) and their
    endpoints are wired in the JS. NEGATIVE: they are NOT statically emitted into
    the unlinked header body (they only appear after renderRemoteControls finds a
    linked project)."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    # Positive — wired in the JS source.
    assert "toggleAutoPush" in html and "/api/rnd/set_auto_push" in html
    assert "pushNow" in html and "/api/rnd/push_now" in html
    # Negative — the unlinked SERVER-rendered body shows no Push-now button / no
    # auto-push checkbox (those are injected client-side only when linked).
    body = _strip(html)
    assert "ghPushNowBtn" not in body, "Push now must not render for an unlinked project"
    assert "ghAutoPush" not in body, "auto-push toggle must not render unlinked"


# ════════════════════════════════════════════════════════════════════════════
# (D) REAL Playwright + Chromium interaction test (dev-only)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_playwright_link_github_flow(server):
    """End to end in a real browser:

      1. Load the project window — the "Link GitHub" button is present, Push-now
         is NOT (unlinked).
      2. Click Link GitHub → auto-accept the "Create" prompt + blank name → the
         seam (stub_gh) returns a fake URL → the linked label + auto-push toggle +
         "Push now" appear.
      3. Toggle auto-push on (persists via set_auto_push).
      4. Click "Push now" — no JS console errors.

    Uses the local bare remote so a push has NO network. Screenshot →
    _devtest/wave3_github.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid, repo, remote, bare_url = (bundle["pid"], bundle["repo"],
                                   bundle["remote"], bundle["bare_url"])
    # Wire origin to the LOCAL BARE remote up front so the Push-now click has a
    # network-free target (the UI "Create" link wires a github.com URL the stub
    # invents, which we then override to the bare remote for the push step).
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # Auto-answer the two prompts linkGithub() raises: pick "C" (create),
        # then a blank repo name (→ folder name).
        prompts = ["C", ""]
        pg.on("dialog", lambda d: d.accept(
            prompts.pop(0) if prompts else "") if d.type == "prompt"
            else d.accept())
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # 1) Unlinked: Link GitHub present, no Push-now yet.
        pg.wait_for_selector("#ghLinkBtn", timeout=8000)
        assert pg.eval_on_selector_all(
            "#ghPushNowBtn", "e=>e.length") == 0, "Push-now shown while unlinked"

        # 2) Click Link GitHub → Create → linked state appears.
        pg.click("#ghLinkBtn")
        pg.wait_for_selector("#ghPushNowBtn", timeout=8000)
        assert pg.eval_on_selector_all(
            "#ghLinkedLabel", "e=>e.length") == 1, "linked label did not appear"
        assert pg.eval_on_selector_all(
            "#ghAutoPush", "e=>e.length") == 1, "auto-push toggle did not appear"

        # 3) Toggle auto-push on.
        pg.check("#ghAutoPush")

        # 4) Re-point origin at the local bare remote so the Push-now click is
        #    network-free, then click Push now and assert no console errors.
        _git(repo, "remote", "set-url", "origin", bare_url)
        pg.click("#ghPushNowBtn")
        pg.wait_for_timeout(800)

        _DEVTEST.mkdir(exist_ok=True)
        pg.screenshot(path=str(_DEVTEST / "wave3_github.png"), full_page=True)
        assert not errors, f"JS console errors in the link flow: {errors}"
        b.close()
