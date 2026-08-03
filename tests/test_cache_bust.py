"""Self-healing cache-bust mechanism (build-version auto-reload).

Covers:
- The `/api/version` endpoint returns JSON `{"version": ...}` with a non-empty
  build id and a `no-store` cache header.
- `generate_html(...)` embeds the self-healing client JS: the build-id global,
  the `/api/version` fetch, the service-worker unregister call, and the
  `sessionStorage` loop-guard — with NO `{{`/`}}` f-string brace leak.
- Routing: `/?v=abc` serves the dashboard (200, contains the R&D tab) instead
  of 404; `/api/status` still 200; an unknown path still 404.

All integration checks boot a throwaway server on an OS-assigned free port
(127.0.0.1:0). Never touches port 8777 or the live `anchor` service.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import paths


def _reload_gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# ── Pure render checks (no network) ────────────────────────────────────

def test_generate_html_embeds_self_healing_js(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    html = gui.generate_html(*gui.gather_all())
    # Build-id global + value.
    assert "window.__ANCHOR_BUILD__" in html
    assert gui.BUILD_ID in html
    # Version fetch + endpoint.
    assert "/api/version" in html
    # Service-worker kill + Cache Storage clear.
    assert "serviceWorker" in html
    assert "getRegistrations" in html
    assert "caches" in html
    # Loop guard via sessionStorage.
    assert "sessionStorage" in html
    assert "anchor_reloaded_for" in html
    # No f-string brace leak anywhere in the served page.
    assert "{{" not in html
    assert "}}" not in html


def test_open_project_window_versionstamps_url(tmp_path, monkeypatch):
    """A project opened from the dashboard carries ``?v=<build id>`` so a project
    window left open across a DEPLOY no longer matches the new URL — the browser
    re-navigates (reloads) the named window instead of merely focusing the stale
    pre-deploy page. Guards the v4 'project window looked unchanged' regression."""
    gui = _reload_gui(tmp_path, monkeypatch)
    html = gui.generate_html(*gui.gather_all())
    assert "openProjectWindow" in html
    # The window.open URL is version-stamped with the live build id.
    assert (
        "'/project/' + encodeURIComponent(pid) + '?v=" + gui.BUILD_ID
    ) in html
    # The named target is retained (no duplicate windows per project).
    assert "'anchorproj_' + pid" in html
    # No f-string brace leak.
    assert "{{" not in html
    assert "}}" not in html


def test_build_id_non_empty(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    assert isinstance(gui.BUILD_ID, str)
    assert gui.BUILD_ID.strip() != ""


def test_project_window_embeds_self_healing_js(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    # cache_bust_script() is what the project window concatenates.
    js = gui.cache_bust_script()
    assert "window.__ANCHOR_BUILD__" in js
    assert gui.BUILD_ID in js
    assert "/api/version" in js
    assert "serviceWorker" in js
    assert "sessionStorage" in js


# ── Integration: throwaway server on an OS-assigned free port ──────────

def test_api_version_endpoint_and_routing(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    # Seed a dashboard file so gather_all/generate_html have real content.
    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] cb-task — Priority: 2 — [academic]\n",
        encoding="utf-8",
    )

    server = gui.make_server("127.0.0.1", 0)  # OS-assigned free port
    port = server.server_address[1]
    assert port != 8777  # never the live service port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        # /api/version -> 200 JSON with non-empty version + no-store header.
        code, raw, headers = _get(base + "/api/version")
        assert code == 200
        body = json.loads(raw)
        assert body.get("version")
        assert body["version"] == gui.BUILD_ID
        assert "no-store" in (headers.get("Cache-Control", "").lower())

        # /?v=abc -> dashboard (200, has the R&D tab), NOT 404.
        code, raw, _ = _get(base + "/?v=abc")
        assert code == 200
        page = raw.decode("utf-8")
        assert "showView('rnd')" in page
        assert "window.__ANCHOR_BUILD__" in page

        # Bare "/" still works.
        code, _, _ = _get(base + "/")
        assert code == 200

        # /api/status still routes (read endpoint, 200).
        code, raw, _ = _get(base + "/api/status")
        assert code == 200
        json.loads(raw)  # valid JSON

        # Unknown path still 404.
        code, _, _ = _get(base + "/definitely/not/a/route")
        assert code == 404
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
