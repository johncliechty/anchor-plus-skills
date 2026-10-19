# W11 — the two NEW mutators land WITH their enforcement: route rows
# declared token-authed + migrated, inventory rows present, and the F6
# assertion set proven RED-TO-GREEN (failing auth-off, green auth-on) in
# the LANDING wave — plus the frontend calls only declared endpoints
# (steward-chamber W11, C10/F6).
#
# AUTH-ON: enforced
#
# The auth-off leg boots the EXACT condition under which the chamber
# shipped broken twice (ANCHOR_TOKEN unset); the auth-on leg mints a real
# scripted-login session. The dispatch shim sits AFTER the production
# do_POST token middleware, so no real handler body ever executes.
import re
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_enforcement as ce  # noqa: E402
import route_table as rt  # noqa: E402
from tests.chamber_harness import TEST_TOKEN, boot_server  # noqa: E402

W11_ROUTES = [
    ("GET", "/api/ecgberht/refine_state", "handle_ecgberht_refine_state"),
    ("POST", "/api/ecgberht/refine_confirm", "handle_ecgberht_refine_confirm"),
    ("POST", "/api/ecgberht/rebrief", "handle_ecgberht_rebrief"),
]

W11_MUTATORS = [r for r in W11_ROUTES if r[0] == "POST"]


# ── declared, token-authed, migrated, registered ────────────────────────────

def test_w11_routes_are_declared_token_authed_and_migrated():
    for method, pattern, handler in W11_ROUTES:
        row = rt.match(method, pattern)
        assert row is not None, "%s %s missing from route_table.py" \
            % (method, pattern)
        assert row.auth == rt.AUTH_TOKEN, (
            "%s must be default-deny token-authed" % pattern)
        assert row.migrated is True
        assert row.handler == handler
        assert (method, pattern) not in rt.open_route_keys()


def test_w11_migrated_handlers_resolve_on_anchor_gui():
    import anchor_gui  # noqa: E402
    for _method, pattern, handler in W11_ROUTES:
        fn = getattr(anchor_gui, handler, None)
        assert callable(fn), (
            "route_table.py declares %s -> %s but anchor_gui has no such "
            "handler" % (pattern, handler))


def test_w11_mutators_have_living_inventory_rows():
    inv = ce.load_routes_inventory()
    rows = {r["pattern"]: r for r in inv["anchor_routes"]}
    for _method, pattern, _handler in W11_MUTATORS:
        assert pattern in rows, "%s has no routes-inventory row" % pattern
        assert rows[pattern]["auth"] == "token"
        assert "W11" in rows[pattern].get("landed_by", ""), (
            "%s must be recorded as landed by W11" % pattern)
    # And the diff guard stays green with the new rows (living registry).
    problems = ce.diff_guard_problems()
    assert not problems, "\n".join(problems)


# ── F6 RED: the assertion set FAILS on the auth-off server ──────────────────

def test_f6_red_the_new_mutators_are_reachable_tokenless_auth_off(tmp_path):
    srv = boot_server(tmp_path, token=None, shim_dispatch=True)
    try:
        for _method, pattern, _handler in W11_MUTATORS:
            with pytest.raises(AssertionError):
                ce.f6_assert_token_required(srv["base"], pattern)
    finally:
        srv["stop"]()


# ── F6 GREEN: the full set passes on the auth-ON server ─────────────────────

def test_f6_green_full_set_for_the_new_mutators_auth_on(tmp_path):
    srv = boot_server(tmp_path, token=TEST_TOKEN, shim_dispatch=True)
    try:
        session = ce.scripted_login(srv["base"], TEST_TOKEN)
        for _method, pattern, _handler in W11_MUTATORS:
            ce.f6_route_green(
                srv["base"],
                {"method": "POST", "pattern": pattern, "match": "exact"},
                TEST_TOKEN, cookie=session.cookie)
    finally:
        srv["stop"]()


def test_refine_state_read_is_401_before_substance_auth_on(tmp_path):
    srv = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        status, _, _ = ce.request(srv["base"], "GET",
                                  "/api/ecgberht/refine_state?project_id=x")
        assert status == 401, (
            "tokenless GET refine_state answered %d — the read surface must "
            "401 before substance under enforce" % status)
    finally:
        srv["stop"]()


# ── the frontend can only call declared endpoints ───────────────────────────

def test_project_window_js_refine_wiring_calls_only_declared_endpoints():
    src = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    assert "_ecgSealOpenRefineOverlay" in src
    assert "_ecgRefineConfirm" in src
    assert "/api/ecgberht/refine_state" in src
    assert "/api/ecgberht/refine_confirm" in src
    declared = {r.pattern for r in rt.ROUTES}
    called = set(re.findall(r"/api/ecgberht/[a-z_]+", src))
    undeclared = {c for c in called
                  if not any(c == p or c.startswith(p) for p in declared)}
    assert not undeclared, "frontend calls undeclared route(s): %s" \
        % sorted(undeclared)
