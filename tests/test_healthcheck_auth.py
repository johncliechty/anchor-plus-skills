"""Wave 2 FIX W2-M1: the health check must be token-aware.

Proves at the function/unit level (no full healthcheck binary, no port 8777,
no live service, no `claude` shell-out) that:

- `anchor_healthcheck._post()` attaches the configured `ANCHOR_TOKEN` so a
  mutating POST succeeds (200) under the production D4 token posture.
- A deliberately tokenless mutating POST to the same throwaway server is
  rejected with 401 (the SETUP.md §6 unauth-rejection invariant).

Everything runs against a throwaway `anchor_gui` server bound to an
OS-assigned free port (port 0).
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import paths


def _raw_post(url, payload, token=None):
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


def test_healthcheck_post_is_token_aware(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "hc-tok")
    importlib.reload(paths)
    paths.ensure_data_dirs()

    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import anchor_healthcheck
    hc = importlib.reload(anchor_healthcheck)

    # Seed a task so /api/done has a real target.
    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] hc-task — Priority: 2 — [academic]\n",
        encoding="utf-8",
    )

    server = gui.make_server("127.0.0.1", 0)  # OS-assigned free port
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        # The healthcheck's own _post() must attach the token -> 200 + mutation.
        result = hc._post(base, "/api/done", {"text": "hc-task"})
        assert result.get("ok") is True
        assert "[x]" in gui.DASHBOARD_MD.read_text(encoding="utf-8")

        # A deliberately tokenless mutating POST must be rejected with 401.
        code, _ = _raw_post(base + "/api/done", {"text": "hc-task"})
        assert code == 401

        # Passing token=None explicitly through _post() also stays tokenless
        # (the unauth-probe path) and surfaces as an HTTPError 401.
        try:
            hc._post(base + "", "/api/done", {"text": "hc-task"}, token=None)
            raised = None
        except urllib.error.HTTPError as e:
            raised = e.code
        assert raised == 401
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_healthcheck_post_no_token_when_unset(monkeypatch, tmp_path):
    """With no token configured, _post() behaves as before (no header, 200)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    paths.ensure_data_dirs()

    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import anchor_healthcheck
    hc = importlib.reload(anchor_healthcheck)

    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] hc-task2 — Priority: 2 — [academic]\n",
        encoding="utf-8",
    )

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        result = hc._post(base, "/api/done", {"text": "hc-task2"})
        assert result.get("ok") is True
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
