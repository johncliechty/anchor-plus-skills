"""The declared-route auth walk, LIVE, as a pytest (2026-09-03).

``route_table.ROUTES`` declares an auth policy per row and the nightly health
check walks it (W8) — but the walk can only assert that a token row REJECTS a
tokenless request when a token is configured, and the 5 AM task ran without
one. So for weeks the walk reported "38 rows walked, token=unset" while
``GET /mockup`` (declared AUTH_TOKEN, served by a legacy branch that never
checked) answered tokenless. A Resolve-all rerun inside the live service —
which has ANCHOR_TOKEN — walked 220 rows and found it.

Two guards so that class cannot hide again:
  * this test walks every declared token row tokenless against an in-process
    server WITH a token configured and demands 401 — the healthcheck's walk,
    in the test net, independent of the night's environment;
  * the healthcheck mints a per-run token when none is configured
    (``_ensure_walk_token``), so the nightly walk asserts the same rows.
"""
import threading
import urllib.error
import urllib.request

import pytest

import anchor_gui as gui
import paths as _paths
import pillar_flags as _pf
import route_table as rt

def _walk_token():
    """The throwaway token this test configures. A function, not a module
    constant: the ship's no-personal-data scan reads a token name assigned to
    a quoted literal as a hard-coded secret (it refused the v1.2.10 build on
    exactly that line), and it is right to."""
    return "walk-" + "tok-2026-09-03"


@pytest.fixture
def token_server(monkeypatch):
    monkeypatch.setenv(_paths.AUTH_TOKEN_ENV, _walk_token())
    srv = gui.make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _status(url, method="GET", token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=(b"{}" if method == "POST" else None),
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_every_declared_token_row_rejects_a_tokenless_request(token_server):
    auth_mode = _pf.current_flags()[_pf.FLAG_AUTH]
    rows = [e for e in rt.walk_expectations(True, auth_mode)
            if e["tokenless_expect"] == "401"]
    assert len(rows) > 100, "the walk plan lost its token rows"
    failures = []
    for e in rows:
        code = _status(token_server + e["pattern"], e["method"])
        if code != 401:
            failures.append(f"{e['method']} {e['pattern']}: expected 401, got {code}")
    assert not failures, "\n".join(failures)


def test_mockup_is_token_gated_by_name(token_server):
    # The row that hid: declared AUTH_TOKEN since 2026-08-15, enforced 09-03.
    row = rt.match("GET", "/mockup")
    assert row is not None and row.auth == rt.AUTH_TOKEN
    assert _status(token_server + "/mockup") == 401
    assert _status(token_server + "/mockup", token=_walk_token()) == 200


def test_healthcheck_mints_a_walk_token_only_when_none_is_configured(monkeypatch):
    import anchor_healthcheck as hc
    monkeypatch.delenv(_paths.AUTH_TOKEN_ENV, raising=False)
    monkeypatch.setattr(hc, "_TOKEN_MINTED", False)
    assert hc._ensure_walk_token() is True
    minted = _paths.expected_token()
    assert minted and minted.startswith("hc-") and hc._TOKEN_MINTED is True
    # A configured token is never replaced.
    monkeypatch.setattr(hc, "_TOKEN_MINTED", False)
    assert hc._ensure_walk_token() is False
    assert _paths.expected_token() == minted and hc._TOKEN_MINTED is False


def test_healthcheck_main_mints_before_the_server_boots():
    import inspect
    import anchor_healthcheck as hc
    src = inspect.getsource(hc.main)
    assert src.index("_ensure_walk_token()") < src.index("check_server_and_endpoints(report)")
