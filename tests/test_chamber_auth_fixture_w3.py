"""W3 — the scripted-login auth fixture produces a REAL authenticated session.

AUTH-ON: enforced

The steward chamber shipped broken twice because virtually every test ran
tokenless; this file is the fixture-of-record proof that the chamber build's
test harness runs with auth ON end-to-end:

* the scripted login walks the browser's own path — ``POST /api/auth/login``
  with the shared secret → the server mints the HttpOnly ``anchor_auth``
  cookie — and returns an :class:`chamber_enforcement.AuthedSession`;
* the minted cookie authenticates the data-plane GET surface under
  ``ANCHOR_AUTH_MODE=enforce`` (a REAL session, not a header spoof);
* the cookie ALONE never authorizes a mutation (the CSRF hardening the F6
  set depends on);
* a wrong token cannot log in, and the fixture fails LOUDLY rather than
  degrading to auth-off.

Hermetic: temp data dir, stub PTY, OS-assigned port (never :8777), no
network beyond loopback. ANCHOR_TOKEN is set by the harness for the server's
lifetime only.
"""
import json

import pytest

import chamber_enforcement as ce
from tests.chamber_harness import TEST_TOKEN, boot_server


@pytest.fixture
def authed_enforce(tmp_path):
    """An auth-ON server in enforce mode + the scripted-login session."""
    handle = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        session = ce.scripted_login(handle["base"], TEST_TOKEN)
        yield {"handle": handle, "session": session}
    finally:
        handle["stop"]()


def test_scripted_login_mints_the_servers_own_cookie(authed_enforce):
    """The session cookie came out of the server's Set-Cookie — and it is the
    HttpOnly auth cookie, name and value, not something the test invented."""
    session = authed_enforce["session"]
    name, _, value = session.cookie.partition("=")
    assert name == "anchor_auth", session.cookie
    assert value == TEST_TOKEN, (
        "the auth cookie must carry the shared secret the server minted")


def test_cookie_authenticates_the_data_plane_get_surface(authed_enforce):
    """Under enforce mode a cookieless data-plane GET is refused 401; the SAME
    GET with the scripted-login cookie is served. That asymmetry — same
    request, cookie is the difference — is what makes the session REAL."""
    session = authed_enforce["session"]

    status_bare, _, _ = ce.request(session.base, "GET", "/api/rnd/projects")
    assert status_bare == 401, (
        "enforce mode must refuse a cookieless data-plane GET (got %d)"
        % status_bare)

    status_cookie, _, body = session.get("/api/rnd/projects")
    assert status_cookie == 200, (
        "the scripted-login cookie must authenticate the data-plane GET "
        "(got %d %r)" % (status_cookie, body[:200]))
    json.loads(body.decode("utf-8"))  # a real JSON answer, not an error page


def test_authenticated_post_works_through_the_header(authed_enforce):
    """The session's POST path (X-Anchor-Token header) reaches its handler —
    the fixture yields a session that can actually DO things with auth on."""
    session = authed_enforce["session"]
    status, _, body = session.post("/api/heartbeat")
    assert status == 200, (status, body[:200])
    assert json.loads(body.decode("utf-8")).get("ok") is True


def test_cookie_alone_never_authorizes_a_mutation(authed_enforce):
    """A POST carrying ONLY the auth cookie (no token header/body) is refused.

    This is the CSRF hardening the F6 forged-request assertion leans on: the
    browser attaches cookies automatically, so the cookie must never be
    sufficient for a state change — the explicit token is."""
    session = authed_enforce["session"]
    status, _, body = session.post(
        "/api/heartbeat", send_token_header=False, send_cookie=True)
    assert status == 401, (
        "cookie-only POST must be refused 401 (got %d %r) — the cookie must "
        "never authorize a mutation" % (status, body[:200]))


def test_wrong_token_cannot_log_in_and_fixture_fails_loudly(tmp_path):
    """A bad secret is refused at login, and scripted_login raises rather
    than silently yielding an unauthenticated session."""
    handle = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        with pytest.raises(AssertionError):
            ce.scripted_login(handle["base"], "wrong-secret")
    finally:
        handle["stop"]()


def test_fixture_refuses_to_mint_a_session_on_an_auth_off_server(tmp_path):
    """On an auth-OFF server the login answers auth:disabled and issues no
    cookie — the fixture must REFUSE (raise), never hand back a session that
    silently degraded to the broken-twice condition."""
    handle = boot_server(tmp_path, token=None)
    try:
        with pytest.raises(AssertionError):
            ce.scripted_login(handle["base"], TEST_TOKEN)
    finally:
        handle["stop"]()
