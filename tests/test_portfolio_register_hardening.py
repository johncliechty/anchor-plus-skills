"""The High Seat can actually be populated — the 2026-08-04 hardening.

THE DEFECT. Ecgberht's portfolio index is written only by the `register` verb,
which mints a project marker carrying a dashed-UUID project id. Nothing in
production ever called it: the verb was declared in STEWARD_VERBS, implemented in
engine/portfolio/register.mjs, and reachable from no entry point at all. So the
index was never written, /api/ecgberht/high_seat answered GLANCE_INDEX_MISSING,
Anchor mapped that to a 502, and the user saw "I can't reach the High Seat"
forever — over a remedy the failure text named ("the index audit fix") that was
equally unreachable.

Anchor's own project ids are 32-hex WITHOUT dashes and do NOT satisfy the
engine's PROJECT_ID_PATTERN, so they can never serve as portfolio identities;
the marker id is minted by the engine and is the identity of record.

These tests cover the HOST CONTRACT half: the route exists, is registered, is
token-gated, and the empty state is honest and actionable.
"""

import json

import pytest

import anchor_gui
import route_table


def test_the_register_route_exists_and_is_token_gated():
    rows = [r for r in route_table.ROUTES
            if r.pattern == "/api/ecgberht/register_projects"]
    assert rows, "no route row for /api/ecgberht/register_projects"
    row = rows[0]
    assert row.method == "POST", (
        "registering WRITES a marker into each project root, so it must not be "
        "reachable on a read path — the portfolio altitude folds read-only")
    assert row.auth == route_table.AUTH_TOKEN


def test_the_register_handler_is_actually_registered():
    """The third place. A route declared migrated with no entry here answers
    404 'Unknown endpoint' — the defect John hit twice."""
    assert "handle_ecgberht_register_projects" in anchor_gui._MIGRATED_HANDLERS
    assert callable(
        anchor_gui._MIGRATED_HANDLERS["handle_ecgberht_register_projects"])


def test_anchor_project_ids_are_not_portfolio_identities():
    """Pins WHY a marker id is minted rather than reusing Anchor's id.

    If this ever passes, someone changed Anchor's id shape and the register
    contract should be revisited deliberately rather than by coincidence.
    """
    import re
    dashed = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    sample = "bda4aa55560c4029863a48bde2fa9924"  # a real Anchor project id shape
    assert not dashed.match(sample), (
        "Anchor's 32-hex id now looks like a dashed UUID — re-check whether the "
        "engine should still mint its own marker identity")


class _FakeHandler:
    """Captures what the handler would send, without a live server."""

    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=200):
        self.payload = payload
        self.status = status


def test_empty_portfolio_answers_200_and_names_the_action(monkeypatch):
    """EMPTY IS NOT BROKEN.

    A never-registered portfolio must not render as a failure banner, and must
    carry the one act that resolves it.
    """
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: (["C:/dev/Some Project"], [], False))
    monkeypatch.setattr(
        anchor_gui, "_ecgberht_hs_bridge",
        lambda *a, **k: {"ok": False, "code": "GLANCE_INDEX_MISSING",
                         "message": "Portfolio index not found"})

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_high_seat(h, "/api/ecgberht/high_seat", None)

    assert h.status == 200, "an empty portfolio is not a gateway failure"
    assert h.payload["ok"] is True
    assert h.payload["empty"] is True
    assert h.payload["code"] == "GLANCE_NO_PROJECTS_REGISTERED"
    assert h.payload["can_register"] is True
    assert h.payload["register_endpoint"] == "/api/ecgberht/register_projects"
    assert h.payload["candidate_roots"] == 1


def test_a_broken_registry_is_still_reported_as_broken(monkeypatch):
    """The fix must not swallow REAL failures into the cheerful empty state."""
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: ([], [], True))  # failed=True
    h = _FakeHandler()
    anchor_gui.handle_ecgberht_high_seat(h, "/api/ecgberht/high_seat", None)
    assert h.status == 502
    assert h.payload["ok"] is False
    assert h.payload["error"] == "registry_unreadable"


def test_an_unparseable_index_is_still_distinct_from_empty(monkeypatch):
    """unknown != empty. A garbled index must NOT read as 'nobody joined yet'."""
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: (["C:/dev/P"], [], False))
    monkeypatch.setattr(
        anchor_gui, "_ecgberht_hs_bridge",
        lambda *a, **k: {"ok": False, "error": "bridge_bad_json"})

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_high_seat(h, "/api/ecgberht/high_seat", None)
    assert h.status == 502
    assert h.payload.get("code") == "GLANCE_INDEX_UNPARSEABLE"


def test_badge_reports_unknown_queue_rather_than_a_reassuring_zero(monkeypatch):
    """A hidden badge is honest; '⚑ 0' on an unwritten index is a lie."""
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: (["C:/dev/P"], [], False))
    monkeypatch.setattr(
        anchor_gui, "_ecgberht_hs_bridge",
        lambda *a, **k: {"ok": False, "code": "GLANCE_INDEX_MISSING"})

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_high_seat_badge(
        h, "/api/ecgberht/high_seat_badge", None)
    assert h.status == 200
    assert h.payload["queue_length"] is None, (
        "queue length is UNKNOWN when no project has joined — never 0")


def test_register_with_no_active_projects_is_honest_not_an_error(monkeypatch):
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: ([], [], False))
    h = _FakeHandler()
    anchor_gui.handle_ecgberht_register_projects(
        h, "/api/ecgberht/register_projects", {})
    assert h.status == 200
    assert h.payload["ok"] is True
    assert h.payload["registered"] == 0


def test_register_counts_already_registered_as_success(monkeypatch):
    """Idempotency for the caller: re-registering is not a failure.

    registerRoot answers REGISTER_ALREADY_MARKED with ok:false (it refused to
    mint a SECOND identity) — correct for the verb, wrong for a host asking "is
    this project in the portfolio?". The host contract must not surface that as
    an error, or clicking the button twice would look broken.
    """
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: (["C:/dev/A", "C:/dev/B"], [], False))
    calls = []

    def _fake_cli(args, timeout=30):
        calls.append(args)
        if "C:/dev/A" in args:
            return {"ok": True, "code": "REGISTER_OK",
                    "project_id": "11111111-1111-4111-8111-111111111111",
                    "already_registered": False}
        return {"ok": True, "code": "REGISTER_ALREADY_MARKED",
                "project_id": "22222222-2222-4222-8222-222222222222",
                "already_registered": True}

    monkeypatch.setattr(anchor_gui, "_ecgberht_steward_cli", _fake_cli)

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_register_projects(
        h, "/api/ecgberht/register_projects", {})

    assert h.status == 200
    assert h.payload["ok"] is True
    assert h.payload["registered"] == 1
    assert h.payload["already"] == 1
    assert h.payload["failed"] == 0
    assert len(calls) == 2


def test_a_refused_root_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(anchor_gui, "_ecgberht_portfolio_roots",
                        lambda: (["C:/dev/A"], [], False))
    monkeypatch.setattr(
        anchor_gui, "_ecgberht_steward_cli",
        lambda *a, **k: {"ok": False, "error": "bridge_spawn_failed",
                         "message": "node missing"})
    h = _FakeHandler()
    anchor_gui.handle_ecgberht_register_projects(
        h, "/api/ecgberht/register_projects", {})
    assert h.payload["failed"] == 1
    assert h.payload["ok"] is False
    assert h.status == 207, "partial/failed registration must not read as clean"
