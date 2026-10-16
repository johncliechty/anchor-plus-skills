"""His word, 2026-10-03: "lock the Cave too", then "lock the dashboard and Doctor too". A page that shows the record
answers with the lock page when a token is required and the request has no valid credential and is not this machine's
own browser; a logged-in request (or no token configured) gets the page."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anchor_gui  # noqa: E402


class _H:
    _locked_page = anchor_gui.AnchorHandler._locked_page

    def __init__(self, local_cookie=None, token_ok=False):
        self._c, self._ok = local_cookie, token_ok

    def _local_login_cookie(self):
        return self._c

    def _term_token_ok(self):
        return self._ok


def test_no_login_gets_the_lock_page(monkeypatch):
    monkeypatch.setattr(anchor_gui._paths, "expected_token", lambda: "tok")
    html, cookie = _H()._locked_page()
    assert html and "Anchor is locked" in html and cookie is None


def test_a_logged_in_request_or_this_machines_browser_gets_the_page(monkeypatch):
    monkeypatch.setattr(anchor_gui._paths, "expected_token", lambda: "tok")
    assert _H(token_ok=True)._locked_page() == (None, None)
    assert _H(local_cookie="anchor_auth=x")._locked_page() == (None, "anchor_auth=x")


def test_no_token_configured_means_nothing_to_lock(monkeypatch):
    monkeypatch.setattr(anchor_gui._paths, "expected_token", lambda: "")
    assert _H()._locked_page() == (None, None)


def test_the_dashboard_and_the_doctor_routes_ask_first():
    src = open(anchor_gui.__file__, encoding="utf-8").read()
    dash = src[src.index('elif _path_only == "/" or _path_only == "/dashboard":'):][:400]
    doc = src[src.index('elif _path_only == "/doctor":'):][:900]
    assert "self._locked_page()" in dash and "self._locked_page()" in doc
