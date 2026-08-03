"""Wave 2 (D4): token-auth middleware on mutating /api/* POSTs.

- The pure predicate `paths.auth_ok` is exercised directly.
- One integration POST against a throwaway server on an OS-assigned free port
  proves: no/bad token -> 401, correct token -> 200. Read endpoints stay open.

Never touches port 8777 or the live `anchor` service.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import paths


def test_auth_ok_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    assert paths.auth_ok(None) is True
    assert paths.auth_ok("anything") is True


def test_auth_ok_enforced_when_set(monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(paths)
    assert paths.auth_ok("s3cret") is True
    assert paths.auth_ok("wrong") is False
    assert paths.auth_ok(None) is False


def test_auth_ok_ignores_blank_token(monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "   ")
    importlib.reload(paths)
    # Blank == unset == disabled.
    assert paths.auth_ok(None) is True


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_resolve_bind_host_refuses_nonloopback_without_token(monkeypatch):
    """Exposing the server beyond loopback REQUIRES a token — else every mutating
    endpoint (incl. the bypassPermissions build lane) would be open."""
    import anchor_gui as g
    # Default loopback, no token needed.
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    assert g.resolve_bind_host() == "127.0.0.1"
    # Non-loopback WITHOUT a token -> refuse to start.
    monkeypatch.setenv("ANCHOR_BIND", "100.69.215.4")
    import pytest
    with pytest.raises(RuntimeError):
        g.resolve_bind_host()
    # Non-loopback WITH a token -> allowed.
    monkeypatch.setenv("ANCHOR_TOKEN", "tok")
    assert g.resolve_bind_host() == "100.69.215.4"


def test_ui_sends_token_and_never_embeds_it(monkeypatch):
    """The dashboard + project-window JS must send X-Anchor-Token on mutating
    POSTs (read from localStorage, settable via setAnchorToken), and the real
    token value must NEVER be embedded in the served HTML — GET is
    unauthenticated, so embedding would leak the secret to anyone who can reach
    the page. This is the client half of D4 (the server half is below)."""
    monkeypatch.setenv("ANCHOR_TOKEN", "supersecret-xyz")
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    dash = gui.generate_html([], [], [])
    pj = gui._PROJECT_WINDOW_JS
    for blob, name in ((dash, "dashboard"), (pj, "project-window")):
        assert "X-Anchor-Token" in blob, name + " must send the token header"
        assert "setAnchorToken" in blob, name + " must offer token entry"
        assert "localStorage" in blob, name + " must read the token client-side"
        # First-load auto-prompt: gated on ANCHOR_AUTH_REQUIRED + fires on load.
        assert "ANCHOR_AUTH_REQUIRED" in blob, name + " must gate the prompt on auth state"
        assert "DOMContentLoaded" in blob, name + " must prompt on first load"
    # When auth is ON, the dashboard embeds the bool TRUE so the page prompts.
    assert "ANCHOR_AUTH_REQUIRED = true" in dash
    # SECURITY: the configured token value is never written into the page.
    assert "supersecret-xyz" not in dash
    assert "supersecret-xyz" not in pj


def test_auth_flag_false_when_token_unset(monkeypatch):
    """Local (no ANCHOR_TOKEN) → the page must NOT prompt for a token."""
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    dash = gui.generate_html([], [], [])
    assert "ANCHOR_AUTH_REQUIRED = false" in dash


def test_rnd_mutating_posts_are_gated(monkeypatch, tmp_path):
    """The R&D mutating endpoints (launch_lane / answer_gate) must reject a
    no-token POST with 401 BEFORE any lane logic runs — so no claude/gemini
    subprocess is ever spawned by an unauthenticated caller."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-rnd")
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for ep, payload in (
            ("/api/rnd/launch_lane", {"project_id": "x", "lane": "research"}),
            ("/api/rnd/answer_gate", {"job_id": "x", "choice": "y"}),
        ):
            code, _ = _post(base + ep, payload)
            assert code == 401, ep + " must require the token"
        # With the right token, launch_lane reaches the handler and cleanly
        # refuses an unknown project (404) — proving auth passed without
        # launching a real lane.
        code, _ = _post(base + "/api/rnd/launch_lane",
                        {"project_id": "no-such", "lane": "research"},
                        token="tok-rnd")
        assert code in (404, 400), "authed launch of unknown project should be a clean refusal"
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_integration_mutating_post_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    # Seed a task so /api/done has something real to act on.
    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] integration-task — Priority: 2 — [academic]\n",
        encoding="utf-8",
    )

    server = gui.make_server("127.0.0.1", 0)  # OS-assigned free port
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        # No token -> 401
        code, _ = _post(base + "/api/done", {"text": "integration-task"})
        assert code == 401

        # Bad token -> 401
        code, _ = _post(base + "/api/done", {"text": "integration-task"}, token="nope")
        assert code == 401

        # GET read endpoint is NOT gated.
        with urllib.request.urlopen(base + "/api/status", timeout=5) as r:
            assert r.status == 200

        # Correct token -> 200 + the mutation actually happened.
        code, raw = _post(base + "/api/done", {"text": "integration-task"}, token="tok-123")
        assert code == 200
        body = json.loads(raw)
        assert body.get("ok") is True
        assert "[x]" in gui.DASHBOARD_MD.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
