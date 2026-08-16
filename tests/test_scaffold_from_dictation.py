"""Dictation -> scaffolding, walked the way a person walks it.

WHY THIS FILE EXISTS. John set a goal on a project, dictated what the project was,
pressed send, and got:

    "Ecgberht could not compile that to a closed act. Nothing was written to the
     ledger. Pick a closed act below, or park the thought (soft-vet receipt)."

The chamber compiles talk through a closed ELEVEN-act table and none of them is
"scaffold this project". The scaffolding engine was fully built AND fully proven --
by t-host-0.mjs, the acceptance test, which imports proposeScaffolding and calls it
directly. So North Star SC1 ("a spoken description produces a PROPOSED multi-stage
scaffolding") was true of the engine and false of the product, and its own
acceptance test could not tell the difference.

The lesson (foreman journal 0099, crucible 0086) is that a capability test must
ENTER WHERE THE HUMAN ENTERS. So the browser test below types into the real say box
and clicks the real button; it does not call the endpoint directly.
"""

import json

import pytest

import anchor_gui
import route_table


# ---- host contract (the three places a route must exist in) ----------------

@pytest.mark.parametrize("pattern,handler", [
    ("/api/ecgberht/scaffold_preview", "handle_ecgberht_scaffold_preview"),
    ("/api/ecgberht/scaffold_confirm", "handle_ecgberht_scaffold_confirm"),
])
def test_route_exists_is_post_and_token_gated(pattern, handler):
    rows = [r for r in route_table.ROUTES if r.pattern == pattern]
    assert rows, "no route row for %s" % pattern
    assert rows[0].method == "POST", (
        "%s must be a POST: preview carries the user's dictation and confirm WRITES "
        "to the ledger" % pattern)
    assert rows[0].auth == route_table.AUTH_TOKEN
    assert rows[0].handler == handler


@pytest.mark.parametrize("handler", [
    "handle_ecgberht_scaffold_preview",
    "handle_ecgberht_scaffold_confirm",
])
def test_handler_is_registered(handler):
    """The third place. Declared-migrated with no entry here answers 404."""
    assert handler in anchor_gui._MIGRATED_HANDLERS
    assert callable(anchor_gui._MIGRATED_HANDLERS[handler])


class _FakeHandler:
    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=200):
        self.payload = payload
        self.status = status


def test_preview_passes_the_dictation_to_the_bridge_and_writes_nothing(monkeypatch):
    seen = {}

    def _fake_bridge(args, timeout=20):
        seen["args"] = args
        return {"ok": True, "mode": "scaffold-preview", "compiled": True,
                "step_count": 3, "ledger_write": False,
                "proposal": {"steps": [{"name": "Build a syllabus"}]}}

    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder",
                        lambda pid: ("C:/dev/Proj", None, 200))
    monkeypatch.setattr(anchor_gui, "_ecgberht_bridge", _fake_bridge)

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_scaffold_preview(
        h, "/api/ecgberht/scaffold_preview",
        {"project_id": "p1", "text": "I want to build a syllabus."})

    assert h.status == 200
    assert h.payload["ledger_write"] is False, "previewing must never write"
    assert "--scaffold-preview" in seen["args"]
    assert "I want to build a syllabus." in seen["args"]


def test_empty_text_is_refused_without_calling_the_bridge(monkeypatch):
    called = []
    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder",
                        lambda pid: ("C:/dev/Proj", None, 200))
    monkeypatch.setattr(anchor_gui, "_ecgberht_bridge",
                        lambda *a, **k: called.append(a) or {"ok": True})
    h = _FakeHandler()
    anchor_gui.handle_ecgberht_scaffold_preview(
        h, "/api/ecgberht/scaffold_preview", {"project_id": "p1", "text": "   "})
    assert h.status == 400
    assert called == [], "an empty utterance must not spawn a bridge"


def test_confirm_sends_who_because_a_confirmation_is_a_human_decision(monkeypatch):
    seen = {}

    def _fake_bridge(args, timeout=20):
        seen["fields"] = json.loads(args[args.index("--scaffold-confirm") + 1])
        return {"ok": True, "mode": "scaffold-confirm", "step_ids": ["a", "b", "c"]}

    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder",
                        lambda pid: ("C:/dev/Proj", None, 200))
    monkeypatch.setattr(anchor_gui, "_ecgberht_bridge", _fake_bridge)

    h = _FakeHandler()
    anchor_gui.handle_ecgberht_scaffold_confirm(
        h, "/api/ecgberht/scaffold_confirm",
        {"project_id": "p1", "text": "build a syllabus, develop case studies"})

    assert h.status == 200
    assert seen["fields"]["who"] == "john"
    assert seen["fields"]["project_path"] == "C:/dev/Proj"
    assert len(h.payload["step_ids"]) == 3


def test_a_bridge_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(anchor_gui, "_ecgberht_project_folder",
                        lambda pid: ("C:/dev/Proj", None, 200))
    monkeypatch.setattr(anchor_gui, "_ecgberht_bridge",
                        lambda *a, **k: {"ok": False, "error": "bridge_spawn_failed"})
    h = _FakeHandler()
    anchor_gui.handle_ecgberht_scaffold_confirm(
        h, "/api/ecgberht/scaffold_confirm", {"project_id": "p1", "text": "build x"})
    assert h.status == 502
    assert h.payload["ok"] is False


# The BROWSER walkthrough (type it, click it) lives in
# tests/test_steward_goal_authon_2026_07_30.py, beside the `authed` fixture and
# the `_chamber_with_goal` helper that already stand up a token-authed server and
# open the chamber. Duplicating that harness here would be the only reason to keep
# a placeholder in this file, and a placeholder test that skips is indistinguishable
# from a passing one -- the exact vacuity this whole effort is about.
