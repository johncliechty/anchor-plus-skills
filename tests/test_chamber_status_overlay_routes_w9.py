# W9 gate — the STATUS-overlay / deliverable-action surfaces this wave added:
# the three new route_table.py rows and the static/project-window.js overlay
# wiring that calls them.
#
# AUTH-ON: not-a-surface (pure table/asset assertions; no server booted)
#
# The wave's own words drive these tests:
#   * "STATUS overlay as drawn ... the same zero-spawn/zero-model bounded read
#     as seal_open" — GET /api/ecgberht/status_overlay is DECLARED in
#     route_table.py, token-authed (default-deny), migrated, and NEVER on the
#     reviewed open allowlist.
#   * The injection-clock deliverable read (GET .../deliverable_state) and the
#     ONE deliverable-action mutator (POST .../deliverable_action, F3) carry
#     the same declared posture, and every migrated handler name genuinely
#     resolves on anchor_gui (the strangler's lookup contract).
#   * static/project-window.js's overlay code calls ONLY endpoints the table
#     declares — the frontend can never invent an undeclared /api/ecgberht/*
#     route (frontend/backend contract, C10 lineage).
import re
import sys
from pathlib import Path

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import route_table as rt  # noqa: E402

PW_JS = ANCHOR / "static" / "project-window.js"

W9_ROUTES = [
    ("GET", "/api/ecgberht/status_overlay", "handle_ecgberht_status_overlay"),
    ("GET", "/api/ecgberht/deliverable_state",
     "handle_ecgberht_deliverable_state"),
    ("POST", "/api/ecgberht/deliverable_action",
     "handle_ecgberht_deliverable_action"),
]


def test_w9_overlay_routes_are_declared_token_authed_and_migrated():
    for method, pattern, handler in W9_ROUTES:
        row = rt.match(method, pattern)
        assert row is not None, "%s %s missing from route_table.py" \
            % (method, pattern)
        assert row.pattern == pattern
        assert row.auth == rt.AUTH_TOKEN, (
            "%s must be default-deny token-authed" % pattern)
        assert row.migrated is True
        assert row.handler == handler
        # Default-deny law: never on the reviewed open allowlist.
        assert (method, pattern) not in rt.open_route_keys()


def test_w9_migrated_handlers_resolve_on_anchor_gui():
    import anchor_gui  # noqa: E402  (heavy, but the lookup contract IS the test)
    for _method, pattern, handler in W9_ROUTES:
        fn = getattr(anchor_gui, handler, None)
        assert callable(fn), (
            "route_table.py declares %s -> %s but anchor_gui has no such "
            "handler" % (pattern, handler))


def test_project_window_js_overlay_calls_only_declared_endpoints():
    src = PW_JS.read_text(encoding="utf-8", errors="replace")
    # The W9 overlay wiring is present in static/project-window.js …
    assert "_ecgSealHrefAllowed" in src
    assert "_ecgSealApplyDeliverable" in src
    assert "/api/ecgberht/status_overlay" in src
    # … and every /api/ecgberht/* endpoint the frontend names is DECLARED in
    # the table for some method (the frontend cannot invent a route).
    declared_patterns = {r.pattern for r in rt.ROUTES}
    called = set(re.findall(r"/api/ecgberht/[a-z_]+", src))
    assert called, "the overlay wiring names no ecgberht endpoints — stale?"
    undeclared = {c for c in called
                  if not any(c == p or c.startswith(p)
                             for p in declared_patterns)}
    assert not undeclared, "frontend calls undeclared route(s): %s" \
        % sorted(undeclared)
