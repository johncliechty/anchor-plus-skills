"""Wave 5 — Grass Catchers content feeds.

Proves IMPLEMENTATION-PLAN.md "## Wave 5":
  - MANUAL ADD: add_idea() records a real (non-discovered) grass-lane card.
  - PROMOTE FROM INBOX: promote_inbox() reads the EXISTING INBOX.md (reusing the
    existing inbox parser, no new format) and copies a matching item into the
    project's Grass Catchers lane (copy-by-default — the inbox item is NOT
    removed).
  - Both POST endpoints (/api/rnd/add_idea, /api/rnd/promote_inbox) sit BEHIND
    the auth gate.

Hermetic: tmp ANCHOR_DATA_DIR, throwaway server on an OS-assigned free port,
NEVER port 8777 or the live service. Follows conftest (repo root importable).
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import anchor
    importlib.reload(anchor)
    import anchor_gui
    importlib.reload(anchor_gui)
    paths.ensure_data_dirs()
    return {"tmp": tmp_path, "paths": paths, "rnd": rnd_registry,
            "eh": effort_history, "anchor": anchor, "gui": anchor_gui}


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


# ── Backend: manual add ─────────────────────────────────────────────────────

def test_add_idea_creates_grass_card(env):
    eh, rnd = env["eh"], env["rnd"]
    folder = env["tmp"] / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    rec = eh.add_idea(folder, pid, "Try a Rust rewrite", notes="someday")
    # It lands in the grass lane as a real (non-discovered) idea card.
    grass = eh.list_efforts(folder, pid, "grass")
    assert len(grass) == 1
    assert grass[0]["title"] == "Try a Rust rewrite"
    assert grass[0]["kind"] == "idea"
    assert grass[0]["notes"] == "someday"
    assert not eh.is_discovered(grass[0])          # an Anchor-created idea, not discovered
    assert rec["job_id"].startswith("idea-")
    # Honesty: an idea carries no fabricated cost.
    assert "cost" not in grass[0] or not grass[0].get("cost")


def test_add_idea_appends_newest_first(env):
    eh, rnd = env["eh"], env["rnd"]
    folder = env["tmp"] / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    eh.add_idea(folder, pid, "first")
    eh.add_idea(folder, pid, "second")
    grass = eh.list_efforts(folder, pid, "grass")
    assert [g["title"] for g in grass] == ["second", "first"]   # newest-first


def test_add_idea_rejects_empty_text(env):
    eh, rnd = env["eh"], env["rnd"]
    folder = env["tmp"] / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    with pytest.raises(ValueError):
        eh.add_idea(folder, pid, "   ")


# ── Backend: promote from INBOX (copy-by-default) ───────────────────────────

def _write_inbox(tmp, lines):
    (tmp / "INBOX.md").write_text(
        "# Inbox\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def test_promote_inbox_creates_grass_card_from_inbox_item(env):
    eh, rnd, gui = env["eh"], env["rnd"], env["gui"]
    tmp = env["tmp"]
    folder = tmp / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    _write_inbox(tmp, [
        "- 2026-06-11: Look into MIT collaboration [academic]",
        "- 2026-06-10: Buy more coffee",
    ])

    inbox_items = gui.parse_inbox_from_md(gui.INBOX_MD)
    rec = eh.promote_inbox(folder, pid, "Look into MIT collaboration",
                           inbox_items=inbox_items)
    grass = eh.list_efforts(folder, pid, "grass")
    assert len(grass) == 1
    assert grass[0]["title"] == "Look into MIT collaboration"
    assert grass[0]["kind"] == "idea"
    assert grass[0]["promoted_from"] == "inbox"
    assert rec["job_id"].startswith("idea-")

    # COPY-BY-DEFAULT: the inbox item is NOT removed from INBOX.md.
    after = gui.INBOX_MD.read_text(encoding="utf-8")
    assert "Look into MIT collaboration" in after
    assert "Buy more coffee" in after


def test_promote_inbox_unknown_item_raises(env):
    eh, rnd, gui = env["eh"], env["rnd"], env["gui"]
    tmp = env["tmp"]
    folder = tmp / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    _write_inbox(tmp, ["- 2026-06-11: a real item"])
    inbox_items = gui.parse_inbox_from_md(gui.INBOX_MD)
    with pytest.raises(ValueError):
        eh.promote_inbox(folder, pid, "not in the inbox at all",
                         inbox_items=inbox_items)


def test_cli_mirror_add_idea_and_promote_inbox(env):
    """anchor.py mirrors delegate to effort_history (GUI + CLI never diverge)."""
    anchor, eh, rnd = env["anchor"], env["eh"], env["rnd"]
    tmp = env["tmp"]
    folder = tmp / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    anchor.add_idea(folder, pid, "cli idea")
    _write_inbox(tmp, ["- 2026-06-11: promote me via cli"])
    anchor.promote_inbox(folder, pid, "promote me via cli")
    titles = {g["title"] for g in eh.list_efforts(folder, pid, "grass")}
    assert titles == {"cli idea", "promote me via cli"}


# ── Endpoints: behind auth + functional ─────────────────────────────────────

def _serve(gui):
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t, f"http://127.0.0.1:{port}"


def test_grass_endpoints_are_auth_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("P", str(folder))["id"]
    (tmp_path / "INBOX.md").write_text(
        "# Inbox\n\n- 2026-06-11: promote this idea\n", encoding="utf-8")

    server, t, base = _serve(gui)
    try:
        # No token -> 401 (BEFORE any grass logic runs).
        for ep, payload in (
            ("/api/rnd/add_idea", {"project_id": pid, "text": "x"}),
            ("/api/rnd/promote_inbox", {"project_id": pid,
                                        "text": "promote this idea"}),
        ):
            code, _ = _post(base + ep, payload)
            assert code == 401, ep + " must require the token"

        # Correct token -> 200 + the mutation actually happened.
        code, data = _post(base + "/api/rnd/add_idea",
                           {"project_id": pid, "text": "added via api"},
                           token="tok-123")
        assert code == 200 and data.get("ok") is True
        assert data["effort"]["title"] == "added via api"

        code, data = _post(base + "/api/rnd/promote_inbox",
                           {"project_id": pid, "text": "promote this idea"},
                           token="tok-123")
        assert code == 200 and data.get("ok") is True
        assert data["effort"]["title"] == "promote this idea"

        grass = effort_history.list_efforts(folder, pid, "grass")
        titles = {g["title"] for g in grass}
        assert titles == {"added via api", "promote this idea"}
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_add_idea_unknown_project_is_clean_404(env):
    gui = env["gui"]
    server, t, base = _serve(gui)
    try:
        code, data = _post(base + "/api/rnd/add_idea",
                           {"project_id": "no-such", "text": "x"})
        assert code == 404
        assert data.get("ok") is False
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
