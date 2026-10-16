"""W3c (his word, 2026-10-01 13:1x): "When I open up the status button inside an expanded tile in the Cave of Wonders, it
looks like the material/content is dated/old." A cockpit with no live engine showed the summary PERSISTED by the
steward's last run, whole - its "Doing: steward mid-turn since 12:22" from a run that ended, its plan as it stood then
(for one cockpit, 4 September). ONE rule now for every status pane: the record as it is NOW, with the last run's
receipts and stamp carried beside it; a live engine composes fresh as before."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import steward_campaign as sc  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _status(at, lead, doing, journal, tests, todo):
    return {"at": at, "lead_line": lead, "plan": {}, "compact": {"facts": [
        {"label": "Summary", "value": "the summary"}, {"label": "Doing", "value": doing}, {"label": "Tests", "value": tests},
        {"label": "Blocker", "value": "none"}, {"label": "Procs", "value": "none"}, {"label": "Journal", "value": journal},
        {"label": "ETA", "value": "Unavailable \u2014 no current estimate"}, {"label": "To do", "value": todo}]}}


def _facts(d):
    return {f["label"]: f["value"] for f in d["compact"]["facts"]}


def test_a_parked_cockpit_s_status_is_the_record_now_with_the_last_run_s_receipts_carried(monkeypatch):
    fresh = _status("2026-10-01 13:15", "Next: Decide on the frozen three-branch verification.", "nothing running - waiting on you",
                    "Unavailable \u2014 no journal receipt for the current work and session", "Unavailable \u2014 no check receipt for the current work and session", "Decide on the frozen three-branch verification.")
    saved = _status("2026-09-04 19:39", "Next: Quiz 1 \u2014 design and ResearchPrime verification", "steward mid-turn since 12:22 (50 min) \u00b7 last status 13:02",
                    "0015-stalls-and-embedding-preview: Two stop mechanisms", "Passed \u2014 Source PDF identity (exit 0)", "Quiz 1 \u2014 design")
    saved["stale"] = True
    monkeypatch.setattr(sc, "compose_status", lambda d, st=None: dict(fresh, compact={"facts": [dict(f) for f in fresh["compact"]["facts"]]}))
    monkeypatch.setattr(sc, "read_last_status", lambda d: dict(saved))
    d = sc.status_for_pane("C:/x", None, live=False)
    f = _facts(d)
    assert d["lead_line"] == "Next: Decide on the frozen three-branch verification." and f["To do"] == "Decide on the frozen three-branch verification." and f["Summary"] == "the summary", "the record NOW, never the plan as it stood at the last run"
    assert f["Doing"] == "nothing running - waiting on you \u00b7 the last run 2026-09-04 19:39", "a run that ended is not 'mid-turn'"
    # Grok W3c (RC-3): nothing from the old summary is grafted into the fresh table - the last run is named once, by its date
    assert f["Journal"].startswith("Unavailable") and f["Tests"].startswith("Unavailable") and f["ETA"].startswith("Unavailable") and f["Procs"] == "none"
    assert d["last_run_at"] == "2026-09-04 19:39" and d["from_record"] is True and "carried" not in d and not d.get("stale") and d["at"] == "2026-10-01 13:15"
    # no persisted summary: the record now, plain
    monkeypatch.setattr(sc, "read_last_status", lambda d: None)
    d2 = sc.status_for_pane("C:/x", None, live=False)
    assert "last_run_at" not in d2 and d2["from_record"] is True and _facts(d2)["Doing"] == "nothing running - waiting on you"
    # a live engine: composed fresh from the map and its state, as before - the persisted summary never consulted
    calls = []
    monkeypatch.setattr(sc, "compose_status", lambda d, st=None: (calls.append(st), dict(fresh))[1])
    monkeypatch.setattr(sc, "read_last_status", lambda d: (_ for _ in ()).throw(AssertionError("read")))
    d3 = sc.status_for_pane("C:/x", {"busy": True}, live=True)
    assert calls == [{"busy": True}] and d3["lead_line"] == fresh["lead_line"] and "from_record" not in d3


def test_the_three_panes_share_the_one_rule():
    card = open(os.path.join(HERE, "steward_cockpit", "high_seat_card.py"), encoding="utf-8").read()
    assert "data = campaign.status_for_pane(cdir, eng.state() if eng is not None else None, live=eng is not None)" in card and "campaign.read_last_status(cdir) or campaign.compose_status(cdir, None)" not in card
    assert '" &middot; the record now; the last run %s" % esc(str(data.get("last_run_at"))[-16:])' in card and '" &middot; the record now; no run yet"' in card and "the record, not a live run" not in card
    routes = open(os.path.join(HERE, "steward_cockpit", "steward_routes.py"), encoding="utf-8").read()
    blk = routes.split('if verb == "status":')[1].split('if verb == "grass":')[0]
    assert "return campaign.status_for_pane(cdir, eng.state() if eng else None, live=eng is not None), 200" in blk and "read_last_status" not in blk, "the cockpit's status verb (the printable brief keeps its own last-status read)"
    gui = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert "data = _sc.status_for_pane(folder, eng.state() if eng is not None else None, live=eng is not None)" in gui
    assert not hasattr(sc, "CARRIED_FACTS")
    desk = open(os.path.join(HERE, "desk_page.py"), encoding="utf-8").read()
    assert '" &middot; the record now; the last run %s" % esc(s["last_run_at"])' in desk and '" &middot; the record now; no run yet" if s.get("lead") else ""' in desk and "the record, not a live run" not in desk and '"last_run_at": str(data.get("last_run_at") or "")[-16:]' in gui, "the Desk says the same, with no dead branch"
    shared = open(os.path.join(HERE, "steward_cockpit", "static", "shared.js"), encoding="utf-8").read()
    assert 'else if (stat.from_record) who.appendChild(el("span", "stale",' in shared and 'stat.last_run_at ? " · the record now; the last run " + String(stat.last_run_at).slice(-16) : " · the record now; no run yet"' in shared, "the cockpit's own header says the clause (Grok W3c)"
