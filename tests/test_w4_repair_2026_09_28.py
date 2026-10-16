"""W4 of the steward revision (2026-09-28): repair as a proposal. After he accepts a presentation the cockpit asks the
engine to PROPOSE the correction set (nothing changes); the card says "proposed: N corrections"; the Status part
shows the set in words with accept and dismiss; his word goes through one route to the engine's closed verb."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import high_seat_card as card  # noqa: E402
from steward_cockpit import repair  # noqa: E402
from steward_cockpit import steward_campaign as campaign  # noqa: E402

PID = "6765ece4b3bc43b0b0b0907b92b17280"
PROPOSAL = {"seq": 4, "kind": "repair_proposal", "at": "2026-09-28", "proposal_id": "repair-0123456789abcdef",
            "after": {"step_id": "lec3", "presentation_id": "p2", "seq": 3}, "count": 2, "requires_confirm": True,
            "corrections": [{"step_id": "lec4", "kind": "clear_wait", "fields": {"waiting_on": None}, "was": {"waiting_on": "Lecture 3 accepted"},
                             "why": "waited on Lecture 3 AI supplement, now accepted"},
                            {"step_id": "lec5", "kind": "second_look", "note": "needs a second look — its foundation changed",
                             "was": {"waiting_on": None}, "why": "its foundation Lecture 3 AI supplement changed"}]}


def _effort(tmp_path, events):
    d = tmp_path / "mba"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> Revise BA 815 for 2026.\n\n## Active effort\n\nLecture 3.\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"human_wait": "none", "current_step_id": "lec4", "next_recommended": "Lecture 4 supplement", "why_next": "it follows"}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": events, "roadmap_projection": [
        {"id": "lec3", "name": "Lecture 3 AI supplement", "status": "done"},
        {"id": "lec4", "name": "Lecture 4 AI supplement", "status": "active", "waiting_on": "Lecture 3 accepted"},
        {"id": "lec5", "name": "Lecture 5 AI supplement", "status": "planned"},
    ]}), encoding="utf-8")
    return d


def test_propose_and_resolve_ride_the_live_engines_update_verb(tmp_path, monkeypatch):
    d = _effort(tmp_path, [])
    seen = []

    def fake_run(args, **kw):
        seen.append(args)
        class R:
            stdout = json.dumps({"ok": True, "appended": True, "proposal_id": "repair-1", "count": 2, "message": "Proposed 2 corrections after lec3; nothing changes until his word."})
            stderr = ""
        return R()
    monkeypatch.setattr(repair.subprocess, "run", fake_run)
    from steward_cockpit import engine_cli
    monkeypatch.setattr(engine_cli, "resolve", lambda: ("node", "live.mjs"))
    out = repair.propose(str(d), "lec3", "p2", background=False)
    assert out["ok"] and out["proposal_id"] == "repair-1"
    assert seen[-1] == ["node", "live.mjs", "update", "--project", str(d), "--repair-propose", "--after-step", "lec3", "--after-presentation", "p2"]
    assert repair.propose(str(tmp_path / "nowhere"), "lec3", "p2", background=False) == {"ok": False, "error": "no_record"}
    assert repair.propose(str(d), "", "p2", background=False) == {"ok": False, "error": "no_record"}
    repair.resolve(str(d), "repair-1", "accepted", who="john")
    assert seen[-1] == ["node", "live.mjs", "update", "--project", str(d), "--repair-resolve", "repair-1", "--disposition", "accepted", "--who", "john"]
    assert repair.resolve(str(d), "repair-1", "maybe") == {"ok": False, "error": "bad_disposition"}
    assert repair.resolve(str(d), "", "accepted") == {"ok": False, "error": "no_record"}


def test_open_proposals_are_those_without_his_word():
    evs = [dict(PROPOSAL), {"kind": "repair_proposal", "proposal_id": "repair-2", "count": 1, "corrections": []},
           {"kind": "repair_resolve", "proposal_id": "repair-2", "disposition": "dismissed"}]
    assert [p["proposal_id"] for p in repair.open_proposals(evs)] == ["repair-0123456789abcdef"]
    assert repair.open_proposals(None) == []


def test_the_status_part_shows_the_set_in_words_with_accept_and_dismiss(tmp_path):
    d = _effort(tmp_path, [dict(PROPOSAL)])
    html = card.card_part(PID, "status", str(tmp_path), "MBA Teaching AI", "mba")["html"]
    assert 'class="cp-repair" data-proposal="repair-0123456789abcdef"' in html
    assert "Proposed after Lecture 3 AI supplement (p2): 2 corrections" in html and "nothing changes until your word" in html
    assert '<b>Lecture 4 AI supplement</b>: clear its wait ("Lecture 3 accepted")' in html
    assert "<b>Lecture 5 AI supplement</b>: needs a second look" in html
    assert 'data-disposition="accepted" data-proposal="repair-0123456789abcdef" data-pid="%s" data-dir="mba"' % PID in html
    assert 'data-disposition="dismissed"' in html
    # the map and the facts carry the same open set, so the tile's line and the part agree
    m = campaign.read_map(str(d))
    assert [p["proposal_id"] for p in m["repair_proposals"]] == ["repair-0123456789abcdef"] and m["repair_proposals"][0]["count"] == 2
    # once his word is on it, the part shows no set
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [dict(PROPOSAL), {"seq": 5, "kind": "repair_resolve", "proposal_id": "repair-0123456789abcdef", "disposition": "accepted"}],
                                               "roadmap_projection": json.loads((d / "roadmap.json").read_text(encoding="utf-8"))["roadmap_projection"]}), encoding="utf-8")
    again = card.card_part(PID, "status", str(tmp_path), "MBA Teaching AI", "mba")["html"]
    assert "cp-repair" not in again and "Open cockpit" in again


def test_the_tile_says_proposed_n_corrections_with_its_open(tmp_path):
    d = _effort(tmp_path, [dict(PROPOSAL)])
    import home_rows
    facts = home_rows.project_facts({"id": PID, "name": "MBA Teaching AI", "folder_path": str(d)})
    assert [p["proposal_id"] for p in facts["repair_proposals"]] == ["repair-0123456789abcdef"]
    import high_seat_page as hsp
    html = hsp._card({"id": PID, "name": "MBA Teaching AI", "folder_path": str(d), "blurb": ""}, facts, "")
    assert "proposed:</span>2 corrections" in html and 'data-part="status"' in html


def test_the_accept_route_proposes_the_set_after_the_acceptance_is_recorded(tmp_path, monkeypatch):
    d = _effort(tmp_path, [])
    (d / "drafts").mkdir()
    (d / "drafts" / "lec3.md").write_text("# draft 2\n", encoding="utf-8")
    h = hashlib.sha256((d / "drafts" / "lec3.md").read_bytes()).hexdigest()
    state = {"ok": True, "sequence": 7, "state": {"slices": {"lec3": {"presentations": [
        {"id": "p2", "members": [{"product_id": "lec3-doc", "revision_id": "r2", "hash": h, "path": "drafts/lec3.md"}]}]}}}}
    monkeypatch.setattr(campaign, "read_refinement", lambda cdir: state)
    from steward_cockpit import refinement_client, horizon
    calls = []
    monkeypatch.setattr(refinement_client, "update", lambda cdir, body: calls.append(("update", body["action"], body["step_id"])) or {"ok": True})
    monkeypatch.setattr(horizon, "refresh", lambda cdir, reason="", background=True: calls.append(("horizon", reason)))
    monkeypatch.setattr(repair, "propose", lambda cdir, sid, pres=None, background=True: calls.append(("propose", str(cdir), sid, pres, background)) or {"ok": True, "appended": True, "proposal_id": "repair-1", "count": 2})
    from steward_cockpit import steward_routes
    body = {"step_id": "lec3", "presentation_id": "p2", "product_id": "lec3-doc", "revision_id": "r2", "hash": h}
    out, code = steward_routes.handle_post(str(d), "refinement-accept", body)
    assert code == 200 and out["ok"]
    assert calls == [("update", "accept", "lec3"), ("propose", str(d), "lec3", "p2", False), ("horizon", "accepted")], "the acceptance, the proposal in the foreground, then the line (Grok W4)"
    assert out["repair_proposed"] == {"proposal_id": "repair-1", "count": 2}
    # a failed composition rides on the acceptance's answer; the acceptance stays a 200
    calls.clear()
    monkeypatch.setattr(repair, "propose", lambda cdir, sid, pres=None, background=True: {"ok": False, "error": "refinement_fold_failed", "message": "could not fold"})
    out, code = steward_routes.handle_post(str(d), "refinement-accept", body)
    assert code == 200 and out["ok"] and out["repair_error"] == "refinement_fold_failed" and "repair_proposed" not in out
    # a refused acceptance proposes nothing
    calls.clear()
    monkeypatch.setattr(refinement_client, "update", lambda cdir, body: {"ok": False, "error": "stale"})
    out, code = steward_routes.handle_post(str(d), "refinement-accept", body)
    assert code == 409 and calls == []


class _Handler:
    def __init__(self):
        self.sent = []

    def _send_json(self, payload, code=200):
        self.sent.append((payload, code))


def test_his_word_goes_through_one_route_to_the_engine(tmp_path, monkeypatch):
    d = _effort(tmp_path, [dict(PROPOSAL)])
    import anchor_gui
    import rnd_registry
    monkeypatch.setattr(rnd_registry, "get_project", lambda pid: {"id": PID, "name": "MBA Teaching AI", "folder_path": str(tmp_path)} if pid == PID else None)
    seen = []

    def fake_resolve(cdir, proposal_id, disposition, who="john"):
        seen.append((str(cdir), proposal_id, disposition, who))
        return {"ok": True, "resolved": True, "applied": ["lec4"], "skipped": [{"step_id": "lec5", "reason": "changed_since"}], "message": "Accepted: 1 correction applied, 1 skipped (moved since)."}
    monkeypatch.setattr(repair, "resolve", fake_resolve)
    h = _Handler()
    anchor_gui.handle_high_seat_repair(h, "/api/high-seat/repair", {"pid": PID, "dir": "mba", "proposal_id": "repair-0123456789abcdef", "disposition": "accepted"})
    payload, code = h.sent[-1]
    assert code == 200 and payload["ok"] and payload["receipt"].startswith("Accepted: 1 correction applied")
    assert payload["applied"] == ["lec4"] and payload["skipped"][0]["reason"] == "changed_since"
    assert payload["open"] == 1, "the record still lists the set until the engine's resolve is on disk (it is faked here)"
    assert seen == [(str(d), "repair-0123456789abcdef", "accepted", "john")]
    # a roadmap that cannot be read says nothing about what is open: the count is omitted, never 0 (Grok W4)
    from steward_cockpit import steward_campaign as _sc
    _orig_read = _sc._read_json
    monkeypatch.setattr(_sc, "_read_json", lambda p: (None, "unreadable (OSError)"))
    anchor_gui.handle_high_seat_repair(h, "/api/high-seat/repair", {"pid": PID, "dir": "mba", "proposal_id": "repair-0123456789abcdef", "disposition": "accepted"})
    payload, code = h.sent[-1]
    assert code == 200 and "open" not in payload
    monkeypatch.setattr(_sc, "_read_json", _orig_read)
    # the effort is resolved only through the cockpit's discovery: a path, a dot-name, an unknown project — refused
    for bad in ({"pid": PID, "dir": "..", "proposal_id": "x", "disposition": "accepted"},
                {"pid": PID, "dir": "mba/../mba", "proposal_id": "x", "disposition": "accepted"},
                {"pid": "nope", "dir": "mba", "proposal_id": "x", "disposition": "accepted"}):
        anchor_gui.handle_high_seat_repair(h, "/api/high-seat/repair", bad)
        assert h.sent[-1][1] == 404, bad
    assert len(seen) == 2, "two words reached the engine (the second with the roadmap unreadable); the refused ones none"
    # the engine's refusal is his answer, not a 200
    monkeypatch.setattr(repair, "resolve", lambda *a, **k: {"ok": False, "error": "proposal_resolved", "message": "Proposal x already has his word."})
    anchor_gui.handle_high_seat_repair(h, "/api/high-seat/repair", {"pid": PID, "dir": "mba", "proposal_id": "x", "disposition": "dismissed"})
    payload, code = h.sent[-1]
    assert code == 409 and payload["receipt"] == "Proposal x already has his word."
