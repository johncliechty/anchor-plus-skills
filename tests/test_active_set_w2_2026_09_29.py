"""W2 v2 of the active set (2026-09-29, his lock of MOCKUPS-goal-board.html): the goal board - one tile per goal in
bands Active · Tier 1 · 2 · 3, a drag ONE place act with undo; the goal's place - the goal revised (done_when), where
it stands, the pace, the workflow, the projects, the goal's own conversation (the one log tagged with the goal; a
scoped grammar; the live steward told which goal); the composer directly under the brief; the brief's lead."""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_campaign_page_2026_09_26 as base  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402

TODAY = date(2026, 9, 29)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ctx(steps=None, working=None, goal_turns=None):
    ctx = base._ctx()
    ctx["today"] = TODAY
    ctx["initiatives"] = hsp.campaign_initiatives(steps or w1._steps(), {
        "magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi", "href": "/project/p-magi"},
        "mba-lec": {"what": "Lectures 3 + 4", "state": "active", "pid": "p-mba", "date": "2026-10-10"}})
    ctx["working"] = working if working is not None else {"p-magi", "p-mba"}
    ctx["goal_turns"] = goal_turns or {}
    return ctx


def test_the_board_is_the_goals_in_tier_bands_then_seed_goals_then_the_boneyard():
    """PLAN v1.3 (his lock, 09-30): Tier 1 · Tier 2 · Seed goals (the tier-3 goals and the seeds) · the Boneyard (done or
    parked goals, folded). No Active band on this page; no order inside a tier."""
    steps = w1._steps() + [
        {"id": "old", "name": "An old goal", "status": "done", "tier": 1, "done_when": "it was done", "navigation": {"path": ["old"], "groups": [{"id": "old", "label": "An old goal", "order": 9, "parent_id": None}]}},
        {"id": "later", "name": "A later goal", "status": "proposed", "tier": 3, "done_when": "some day", "navigation": {"path": ["later"], "groups": [{"id": "later", "label": "A later goal", "order": 0, "parent_id": None}]}}]
    html = cpg.render_campaign_html(_ctx(steps))
    board = html[html.index('<div class="bands"'):html.index('id="viewCal"')]
    bands = re.findall(r'<section class="band[^"]*" data-band="([^"]+)"', board)
    assert bands == ["1", "2", "3", "bone"], "Tier 1, Tier 2, Seed goals, the boneyard - and no Active band"
    tiles = re.findall(r'<article class="gtile[^"]*" draggable="true" data-lane="([^"]+)" data-band="([^"]+)"', board)
    assert sorted(tiles) == sorted([("magi", "1"), ("mba", "1"), ("trusts", "1"), ("paper", "2"), ("later", "3")]), "the goals in their tiers; a tier-3 goal among the seed goals"
    assert 'draggable="false" data-lane="old" data-band="bone"' in board and 'id="boneFold" hidden' in board and "show (1)" in board, "a done goal in the boneyard, folded"
    assert '<section class="seedband" id="seedband"' in board[board.index('data-band="3"'):board.index('data-band="bone"')], "the seeds live in the Seed goals band"
    magi = board[board.index('data-lane="magi"'):board.index('data-lane="magi"') + 1200]
    assert 'data-open="magi"' in magi and "Artificial Magi done" in magi and "pace Dec 15" in magi and 'class="ilight working"' in magi
    assert 'class="gcock"><span class="gpc working" title="active">Chapter 2 scenes <i>&#9679;</i></span></div>' in magi
    trusts = board[board.index('data-lane="trusts"'):board.index('data-lane="trusts"') + 1200]
    assert "next Oct 8" in trusts and "&#9873; 1 part needs you" in trusts
    assert "5 goals &middot; Tier 1 3 &middot; Tier 2 1 &middot; seed goals 1 &middot; the boneyard 1" in html, "Tier 1 + Tier 2 + seed goals = the goals; the done goal is out; the seeds keep their own count in the fold"
    assert 'data-band="active"' not in html and 'class="itile' not in html
    text = re.sub(r"<[^>]+>", " ", html).lower()
    assert "initiative" not in text, "the word retires from this page; the seats and their words come with the High Seat (W2b/W2c)"
    cal = html[html.index('id="viewCal"'):]
    assert 'class="tn">Seed goals</span>' in cal and "No tier yet" not in cal and 'class="rnum"' not in cal and 'data-lane="old"' not in cal, "the calendar uses the board's buckets: no rank, no third tier, the done goal out"


def test_a_goal_opens_into_its_place_with_the_goal_where_it_stands_the_workflow_the_projects_and_its_thread():
    turns = {"trusts": [{"you": True, "text": "add a part: call the trustee", "at": "10:50", "goal": "trusts"},
                        {"you": False, "text": "Added to The trusts and the holding company.", "at": "10:50", "goal": "trusts"}]}
    html = cpg.render_campaign_html(_ctx(goal_turns=turns), open_id="trusts")
    assert 'class="board" aria-label="The Chart Room" data-place="trusts"' in html, "?open= deep-links the place"
    place = html[html.index('id="place-trusts"'):html.index('id="place-paper"')]
    assert 'hidden' in place[:120], "rendered for every goal, shown by the page script"
    assert 'class="pname">The trusts and the holding company</span>' in place
    assert 'data-goal-text="trusts">The trusts and the holding company done</div>' in place, "the goal whole, to revise"
    assert "0 of 1 part done" in place and "1 waits on you &mdash; Send the Stanford package" in place and "the next deadline is <b>Oct 8</b>" in place and "no pace set" in place
    assert '<div class="k">Progress</div>' not in place, "the third copy of N of M is cut (Grok W2)"
    assert "nudge" not in place, "no promise W3 has not built"
    assert 'data-pace="trusts">set a pace</span>' in place and 'data-tiersel="trusts"' in place and "data-activate" not in place, "seats come with the High Seat (W2b/W2c), not here"
    assert 'data-act="date" data-part="trusts-pkg"' in place and 'data-act="add" data-lane="trusts"' in place, "the workflow carries the parts' acts as the tile's body did"
    assert 'data-thread="trusts"' in place and "add a part: call the trustee" in place and "Added to The trusts" in place
    assert 'class="gsay" data-goal="trusts"' in place and 'class="send gsend" data-goal="trusts"' in place
    assert "Brainstorm with the steward" in place and "The objective &middot; done when" in place and "The plan &middot; the parts in order" in place
    assert 'stamp: ""' in html or "stamp: " in html
    magi = html[html.index('id="place-magi"'):html.index('id="place-mba"')]
    assert 'href="/project/p-magi"' in magi and "Chapter 2 scenes" in magi and "Its components" in magi and '<span class="ck">cockpit</span>' in magi, "a project part is openable from the place, named for its kind"
    assert "the pace is <b>Dec 15</b>" in magi and "bench it" not in magi
    assert '<span class="ck">desk item</span> Send the Stanford package' in place
    assert "Nothing said about this goal yet" in magi
    assert 'class="istatus"' in magi, "the Status as the tile's body had it"


def test_the_composer_sits_under_the_brief_and_the_brief_leads_with_the_set():
    html = cpg.render_campaign_html(_ctx())
    panel = html[html.index('<aside class="panel"'):]
    assert panel.index('id="lookAhead"') < panel.index('class="exwrap') < panel.index('class="composer"'), "the look-ahead, the conversation, then the composer at its foot"
    assert 'id="brief"' not in panel and '<li class="lead">' not in panel, "his word 2026-10-03: the brief is gone from the Cave and the Star Chart; the look-ahead took its place"
    assert "make &hellip; active" not in panel and "bench" not in panel, "the placeholders do not teach verbs the page no longer offers"
    assert "above the board" not in panel   # the brief that named Seed goals is gone (2026-10-03)


def test_lint_a_drop_is_one_place_act_and_the_place_s_acts_are_the_record_s():
    js = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    drag = js[js.index("var dragId"):js.index("// the goal's place")]
    assert "act({ act: 'place', step: id, band: to, position: 0 })" in drag and drag.count("act({") == 1, "one drop, one act: the tier only"
    assert "data-band=\"active\"" not in drag and "#boneTog" in drag
    place = js[js.index("// the goal's place"):js.index("// ── the dialogue")]
    assert "act({ act: 'done_when', step: id, text: v })" in place and "act({ act: 'pace', step: id, when: inp.value || 'none' })" in place
    assert "data-activate" not in place and "data-bench" not in place
    conv = js[js.index("// ── the dialogue"):js.index("// the tools")]
    assert "window.StewardDialogue.init({" in conv and "receiptKey: 'campaign_receipt'" in conv, "W2c-2: the one dialogue mechanism, shared with the High Seat"
    dlg = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    assert "'/api/steward/events'" in dlg and "ev.t === 'delta'" in dlg and "ev.t === 'turn_end'" in dlg and "goal: goal || undefined" in dlg
    assert "EventSource" not in js and "pollThread" not in js and "EventSource" not in dlg, "one mechanism: the cockpit's event stream, long-polled"
    assert dlg.count("/api/steward/history") == 1 and "function catchUp" in dlg and "/api/steward/history" not in js, "the log is read once, only for a turn that ended before the page saw its words"
    assert "primeSeq().then(function () { if (!refused) pollLoop(); })" in dlg, "the poll starts with the open (W2b-3): the cockpit's own soft start, never a fresh session from a view; a refused poll stops (W2c-3)"
    assert "j.stamp !== BOOT_STAMP" in dlg and "location.reload" in dlg
    assert "window.prompt(" not in place and "window.prompt(" not in conv
    assert "openPlace(" in js and ".itile" not in js.replace("/* ", "").split("(function")[1]


def test_a_drop_is_one_place_act_the_tier_only(tmp_path, monkeypatch):
    """His word (09-29 18:4x): no ranking inside a tier; and since W2b-2 the Active band is at the High Seat (the seats
    on components), so a drop on the board is the tier only."""
    d = w1._record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    r = acts.act(d, {"act": "place", "step": "paper", "band": "1"})
    assert r["ok"] and acts._step(d, "paper")["tier"] == 1 and r["undo"] == {"act": "place", "step": "paper", "band": "2", "position": 0}
    r = acts.act(d, r["undo"])
    assert r["ok"] and acts._step(d, "paper")["tier"] == 2
    r = acts.act(d, {"act": "place", "step": "trusts", "band": "3"})
    assert r["ok"] and acts._step(d, "trusts")["tier"] == 3, "Seed goals is tier 3"
    assert not acts.act(d, {"act": "place", "step": "trusts", "band": "3"})["ok"], "already in its tier: nothing to do (no order inside a tier)"
    assert not acts.act(d, {"act": "place", "step": "paper", "band": "active"})["ok"], "no Active band on the board: the seats live at the High Seat"
    assert not acts.act(d, {"act": "place", "step": "nope", "band": "1"})["ok"]


def test_the_goal_is_revised_as_its_done_when_with_undo(tmp_path, monkeypatch):
    d = w1._record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    r = acts.act(d, {"act": "done_when", "step": "magi", "text": "book one drafted by Dec 15; the stories follow"})
    assert r["ok"] and r["receipt"] == "Goal of Artificial Magi revised" and r["undo"] == {"act": "done_when", "step": "magi", "text": "Artificial Magi done"}
    assert acts._step(d, "magi")["done_when"] == "book one drafted by Dec 15; the stories follow"
    assert not acts.act(d, {"act": "done_when", "step": "magi", "text": "  "})["ok"]
    r = acts.act(d, r["undo"])
    assert r["ok"] and acts._step(d, "magi")["done_when"] == "Artificial Magi done"


def test_inside_a_goal_s_place_a_verb_needs_no_name(tmp_path, monkeypatch):
    d = w1._record(tmp_path)
    _fake_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": False, "campaign": False})
    r = say.say_campaign(d, "pace by Oct 10", today=TODAY, goal="trusts")
    assert r and r["ok"] and r["act"] == "campaign_pace" and acts._step(d, "trusts")["pace"] == "2026-10-10"
    r = say.say_campaign(d, "by Nov 30.", today=TODAY, goal="trusts")
    assert r and r["ok"] and acts._step(d, "trusts")["pace"] == "2026-11-30"
    r = say.say_campaign(d, "clear the pace", today=TODAY, goal="trusts")
    assert r and r["ok"] and not acts._step(d, "trusts").get("pace")
    r = say.say_campaign(d, "make it active", today=TODAY, goal="trusts")
    assert r and not r["ok"] and "a goal has no seat" in r["say"], "a goal has no seat (W2b-2): its components do"
    r = say.say_campaign(d, "bench it", today=TODAY, goal="trusts")
    assert r and not r["ok"] and "a goal has no seat" in r["say"]
    r = say.say_campaign(d, "tier 2", today=TODAY, goal="trusts")
    assert r and r["ok"] and r["act"] == "campaign_move_tier" and acts._step(d, "trusts")["tier"] == 2
    r = say.say_campaign(d, "goal: the estate plan executed; the company formed", today=TODAY, goal="trusts")
    assert r and r["ok"] and r["act"] == "campaign_done_when" and acts._step(d, "trusts")["done_when"] == "the estate plan executed; the company formed"
    assert say.say_campaign(d, "summarize where this goal stands", today=TODAY, goal="trusts") is None, "talk goes to the steward"
    assert say.say_campaign(d, "by the end of the world", today=TODAY, goal="trusts") is None, "not a date: the steward takes it"
    assert say.say_campaign(d, "make it active", today=TODAY, goal="no-such") is None, "no such goal: the general grammar"
    # the general grammar still works inside a place when another goal is named
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_activate", "args": {"initiative": "paper 1"}})
    r = say.say_campaign(d, "make paper 1 active", today=TODAY, goal="trusts")
    assert r and not r["ok"] and r["act"] == "campaign_activate" and "a goal has no seat" in r["say"], "the general grammar ran; a goal's whole name refuses and names its components (W2b-2)"


def test_the_goal_s_thread_is_the_one_log_tagged_and_the_steward_s_answer_carries_the_tag(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine as se
    from steward_cockpit.conversation_history import read_history_document
    d = w1._record(tmp_path)
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    st = object.__new__(se.Engine)
    st.dir, st.fake, st.general, st.tid = d, False, False, None
    st._emit = lambda ev: None
    assert st._record_conversation("john", "add a part: call the trustee", goal="trusts")
    assert st._record_conversation("steward", "Added to The trusts and the holding company.", goal="trusts")
    assert st._record_conversation("john", "what does the Campaign say?")
    turns = read_history_document(d)["turns"]
    assert [t.get("goal") for t in turns] == ["trusts", "trusts", None] and turns[0]["turn_id"]
    # the words the model sees name the goal; his recorded words are his own; the tag for the answer is read from
    # the text that went to stdin for THAT turn (never a slot the next turn could wear - Grok W2)
    sent = se._scoped_text("pace by Oct 10", "trusts", "The trusts and the holding company")
    assert sent == "About the goal ‘The trusts and the holding company’ (the Campaign initiative trusts) — pace by Oct 10"
    assert se._goal_in(sent) == "trusts" and se._goal_in("what does the Campaign say?") is None and se._goal_in("") is None
    assert se._scoped_text("hello", None, "") == "hello"
    assert not hasattr(st, "_goal_scope")
    # a verb applied inside the place: his words and the writer's receipt land in the thread, marked as the writer's
    from steward_cockpit import steward_routes as sr0
    assert sr0.note_goal_receipt(d, "trusts", "pace by Oct 10", "The trusts and the holding company: the pace is now 2026-10-10")
    turns = read_history_document(d)["turns"]
    assert turns[-2]["goal"] == "trusts" and turns[-2]["via"] == "campaign_act" and turns[-1]["text"].endswith("2026-10-10")
    # the read of a goal's thread through the cockpit's history verb
    from steward_cockpit import steward_routes as sr
    out, code = sr.handle_get(d, "history", {"goal": "trusts"})
    assert code == 200 and [t["text"] for t in out["turns"]][:2] == ["add a part: call the trustee", "Added to The trusts and the holding company."] and len(out["turns"]) == 4


def _fake_engine(tmp_path, monkeypatch):
    """The engine faked: the roadmap-set flags and the spine's step_set fields mirrored into the stored projection."""
    monkeypatch.setattr(acts, "_cli", _fake_cli(tmp_path))

    def fake_spine(project, step_id, fields):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        for s in steps["roadmap_projection"]:
            if s["id"] == step_id:
                s.update(fields)
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(acts, "_spine_set", fake_spine)


def _fake_cli(tmp_path):
    def fake_cli(project, *args):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        sid = args[args.index("--step") + 1]
        for s in steps["roadmap_projection"]:
            if s["id"] == sid:
                if "--active" in args:
                    if args[args.index("--active") + 1] == "on": s["active"] = True
                    else: s.pop("active", None); s.pop("active_order", None)
                if "--active-order" in args: s["active_order"] = int(args[args.index("--active-order") + 1])
                if "--pace" in args:
                    v = args[args.index("--pace") + 1]
                    if v == "none": s.pop("pace", None)
                    else: s["pace"] = v
                if "--tier" in args: s["tier"] = int(args[args.index("--tier") + 1])
                if "--done-when" in args: s["done_when"] = args[args.index("--done-when") + 1]
                if "--navigation" in args: s["navigation"] = json.loads(args[args.index("--navigation") + 1])
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    return fake_cli
