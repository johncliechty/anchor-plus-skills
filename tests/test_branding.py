"""Wave 9 — Ghost World Labs branding on the Home page.

Covers the Wave 9 contract (IMPLEMENTATION-PLAN lines 196-219):
  - The served home-page HTML (``generate_html``) includes the vendored GWL mark
    asset reference (``/vendor/brand/gwl-m-icon.svg``), the "Ghost World Labs"
    wordmark, and a "Powered by NextGen Nuclear" badge; the tab favicon
    ``<link rel="icon">`` is the Anchor icon (not the GWL ghost).
  - ``GET /vendor/brand/gwl-m-icon.svg`` over a port-0 server returns 200 with
    content-type ``image/svg+xml`` and the real SVG bytes; a ``../`` traversal
    attempt is blocked (404, does not escape the brand dir / serve paths.py).
  - Brace hygiene: 0 leaked ``{{`` / ``}}`` in the served home page; the module
    imports cleanly.

Hermetic: temp ANCHOR_DATA_DIR + reload, port-0 server for the route tests,
no live claude, no network.
"""
import importlib
import re
import socket
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
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


# ── Home-page lockup markup ──────────────────────────────────────────────────

def test_home_page_includes_gwl_lockup_and_badge(env):
    gui = env
    html = gui.generate_html(*gui.gather_all())
    # The vendored GWL brand mark asset is referenced (lockup img + favicon).
    assert "/vendor/brand/gwl-m-icon.svg" in html
    # The Ghost World Labs wordmark text is present.
    assert "Ghost World" in html and "Labs" in html
    # The NextGen Nuclear credit badge text is present.
    assert "Powered by NextGen Nuclear" in html


def test_favicon_link_points_at_anchor_icon(env):
    gui = env
    html = gui.generate_html(*gui.gather_all())
    # Tab icon is the Anchor, not the GWL ghost (lockup still uses the ghost).
    assert re.search(
        r'<link rel="icon" href="/anchor\.ico[^"]*" type="image/x-icon">',
        html,
    ), "favicon <link rel=icon> must point at the Anchor icon"
    assert not re.search(
        r'<link rel="icon" href="/vendor/brand/gwl-m-icon\.svg',
        html,
    )


def test_home_page_has_no_leaked_fstring_braces(env):
    gui = env
    html = gui.generate_html(*gui.gather_all())
    assert "{{" not in html and "}}" not in html


def test_module_imports(env):
    # The fixture already reloaded anchor_gui; a clean import is the assertion.
    import anchor_gui  # noqa: F401
    assert env is anchor_gui


# ── Traversal-safe brand static route ────────────────────────────────────────

def test_brand_route_serves_svg(env):
    gui = env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/vendor/brand/gwl-m-icon.svg", timeout=8
        ) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/svg+xml"
            body = resp.read()
        assert b"<svg" in body
        assert b"Ghost World" not in body  # sanity: it's the icon, raw SVG
        assert b"#22c55e" in body  # the brand green is in the vendored mark
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


@pytest.mark.parametrize(
    "evil",
    [
        "/vendor/brand/../../paths.py",
        "/vendor/brand/..%2f..%2fpaths.py",
        "/vendor/brand/../anchor_gui.py",
    ],
)
def test_brand_route_blocks_traversal(env, evil):
    gui = env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{evil}", timeout=8
            ) as resp:
                body = resp.read()
                # If it somehow returns 200, it MUST NOT have escaped the dir.
                assert b"import" not in body
                assert resp.status == 404
        except urllib.error.HTTPError as e:
            assert e.code == 404
            leaked = e.read()
            assert b"def " not in leaked and b"import " not in leaked
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


@pytest.mark.parametrize(
    "raw_path",
    [
        "/vendor/brand/../../paths.py",
        "/vendor/brand/..%2f..%2fpaths.py",
        "/vendor/brand/..\\..\\paths.py",
        "/vendor/brand/../anchor_gui.py",
    ],
)
def test_brand_route_blocks_raw_unnormalized_traversal(env, raw_path):
    """Send a LITERAL, un-normalized request line over a raw socket.

    ``urllib`` collapses ``../`` segments client-side, so the dotted path never
    reaches the server — that test would pass even if the server-side
    containment check were weakened. This bypasses normalization entirely: the
    server must itself reject the escape (non-200) and NEVER serve source bytes
    (no ``def ``, no ``import paths``, no ``ANCHOR_DATA_DIR``).
    """
    gui = env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(8)
        try:
            sock.connect(("127.0.0.1", port))
            request = (
                f"GET {raw_path} HTTP/1.1\r\n"
                "Host: 127.0.0.1\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            sock.sendall(request.encode("latin-1"))
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
            raw = b"".join(chunks)
        finally:
            sock.close()
        # Status line MUST be non-200 (404 for the blocked traversal).
        status_line = raw.split(b"\r\n", 1)[0]
        assert b" 200 " not in status_line, status_line
        assert b" 404 " in status_line, status_line
        # The body MUST NOT contain any source-code markers — paths.py /
        # anchor_gui.py is NEVER served, regardless of status.
        assert b"def " not in raw
        assert b"import paths" not in raw
        assert b"ANCHOR_DATA_DIR" not in raw
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_brand_asset_resolver_rejects_escape(env):
    gui = env
    # Direct unit check on the resolver containment logic.
    assert gui.brand_asset("gwl-m-icon.svg") is not None
    assert gui.brand_asset("../paths.py") is None
    assert gui.brand_asset("../../anchor_gui.py") is None
    assert gui.brand_asset("does-not-exist.svg") is None
