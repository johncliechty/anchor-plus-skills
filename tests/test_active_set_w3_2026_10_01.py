"""W3 THE STEWARD STEPS IN (2026-10-01; PLAN v1.3.2 fits 8-9): ONE nudge at a speaking boundary, derived from the records
- a dated part near while he is elsewhere; an initiative that waits on him and is only on deck; a top goal starving; a
seed that reads like a goal; a free moment - in his words, with its reason, the fact it read and one-click acts; "not now"
a receipt in the Campaign's folder that silences that nudge until its fact changes, with undo; shown under the High
Seat's brief and in a goal's conversation; never a write but his click."""
import json
import os
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import nudges as N  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = date(2026, 10, 1)


def part(id, text, **k):
    p = {"id": id, "text": text, "target": "", "state": "", "date": "", "pid": "", "dir": "", "kind": "task", "status": "proposed", "done": False, "closed": False, "seat": "", "seat_order": None, "needs_you": False, "broken": False}
    p.update(k)
    return p


def goal(id, name, tier, parts, **k):
    g = {"id": id, "name": name, "tier": tier, "order": 0, "status": "proposed", "parts": parts}
    g.update(k)
    return g


def test_one_nudge_in_his_words_the_dated_thing_first_and_only_while_he_is_elsewhere():
    inits = [goal("trusts", "Family finances", 1, [part("mtg", "Trusts meeting with the attorney", date="2026-10-02"), part("pkg", "Stanford package", date="2026-10-08")]),
             goal("mba", "MBA Teaching", 1, [part("lec", "Lecture 3", kind="project", pid="p-mba", seat="active")])]
    n = N.derive(inits, {}, [], working={"p-mba"}, today=TODAY, campaign_pid="c1")
    assert n and n["kind"] == "dated" and n["text"] == "Excuse me: Trusts meeting with the attorney is due tomorrow (Family finances)."
    assert n["why"] == "the part's date on the Campaign record: 2026-10-02" and n["fact"] == "2026-10-02"
    assert [a["act"] for a in n["acts"]] == ["open"] and n["acts"][0]["href"] == "/project/c1?open=trusts"
    # the same date in the goal he is working in is the head's business, not a nudge
    inits2 = [goal("mba", "MBA Teaching", 1, [part("lec", "Lecture 3", kind="project", pid="p-mba", seat="active"), part("hw", "Homework due", date="2026-10-01")])]
    assert N.derive(inits2, {}, [], working=set(), today=TODAY) is None
    # a date beyond three days, an overdue one and a done part do not nudge
    inits3 = [goal("t", "T", 1, [part("a", "far", date="2026-10-06"), part("b", "past", date="2026-09-28"), part("c", "done", date="2026-10-01", done=True)])]
    assert N.derive(inits3, {}, [], working=set(), today=TODAY) is None
    assert N.when_words(date(2026, 10, 1), TODAY) == "today" and N.when_words(date(2026, 10, 3), TODAY) == "Sat, Oct 3"


def test_the_deck_wait_the_starving_goal_the_seed_and_the_free_moment_in_their_order():
    deck = goal("mba", "MBA Teaching", 1, [part("hw", "retool homework 2", kind="project", pid="p-mba", seat="deck", seat_order=0, state="waiting on you: approve the plan", needs_you=True)])
    n = N.derive([deck], {}, [], working=set(), today=TODAY, campaign_pid="c1")
    assert n["kind"] == "deck_wait" and n["text"] == "retool homework 2 waits on you and is only on deck \u2014 make it active?" and n["why"] == "its record: needs you · approve the plan"
    assert n["acts"][0] == {"act": "seat", "step": "hw", "seat": "active", "label": "make it active"} and n["acts"][1]["href"] == "/project/p-mba"
    starving = goal("tech", "Technical papers", 2, [part("p1", "Paper 1", kind="project", pid="p-paper")])
    n2 = N.derive([starving], {}, [], working=set(), today=TODAY, strip_ages={"p-paper": 15}, campaign_pid="c1")
    assert n2["kind"] == "starving" and n2["text"] == "Technical papers is a Tier-2 goal untouched for 15 days \u2014 put one of its cockpits on deck?"
    assert n2["acts"][0] == {"act": "seat", "step": "p1", "seat": "deck", "label": "put Paper 1 on deck"} and n2["fact"] == "2", "the fact is the week, so a week later it may speak again"
    assert N.derive([starving], {}, [], working=set(), today=TODAY, strip_ages={"p-paper": 10}) is None, "a Tier-2 goal starves at two weeks"
    assert N.derive([goal("t1", "T1", 1, [part("p1", "P", kind="project", pid="p1")])], {}, [], working=set(), today=TODAY, goal_last_at={"t1": "2026-09-20"})["kind"] == "starving", "no strip age: the days since its last turn"
    seeds = [{"id": "s1", "text": "what about Rome?", "at": ""}, {"id": "s2", "text": "Teach an AI mechanics class for the MBA cohort by spring", "at": ""}]
    n3 = N.derive([], {}, seeds, working=set(), today=TODAY, campaign_pid="c1")
    assert n3["kind"] == "seed" and n3["text"].startswith("the seed \u2018Teach an AI mechanics class") and n3["acts"][0]["act"] == "promote" and n3["acts"][0]["seed"] == "s2" and n3["acts"][0]["tier"] == 2
    free = goal("g", "G", 1, [part("d1", "Deck thing", kind="project", pid="p-d", seat="deck", seat_order=0)])
    n4 = N.derive([free], {}, [], working=set(), today=TODAY)
    assert n4["kind"] == "free" and n4["text"] == "A free moment: Deck thing is on deck (G) \u2014 make it active?" and n4["acts"] == [{"act": "seat", "step": "d1", "seat": "active", "label": "make it active"}]
    # the order: a dated thing beats a deck wait beats starving beats a seed beats the free moment - ONE nudge
    everything = [goal("trusts", "Family finances", 1, [part("mtg", "Meeting", date="2026-10-02")]), deck, starving]
    assert N.derive(everything, {}, seeds, working=set(), today=TODAY, strip_ages={"p-paper": 15})["kind"] == "dated"


def test_grok_w3_fold_the_head_s_lead_yields_the_open_goal_has_no_link_the_quoted_cockpit_is_offered():
    deck = goal("mba", "MBA Teaching", 1, [part("hw", "retool homework 2", kind="project", pid="p-mba", seat="deck", seat_order=0, state="waiting on you: approve the plan", needs_you=True)])
    # the head's own sentence already leads with this part (its pid, or its name): the nudge yields - no second mechanism saying it (RC-3)
    assert N.derive([deck], {}, [], working=set(), today=TODAY, head_lead=("p-mba", "retool homework 2")) is None
    assert N.derive([deck], {}, [], working=set(), today=TODAY, head_lead=("", "retool homework 2")) is None
    assert N.derive([deck], {}, [], working=set(), today=TODAY, head_lead=("p-other", "something else"))["kind"] == "deck_wait"
    free = goal("g", "G", 1, [part("d1", "Deck thing", kind="project", pid="p-d", seat="deck", seat_order=0)])
    assert N.derive([free], {}, [], working=set(), today=TODAY, head_lead=("p-d", "")) is None, "the free moment yields to the head too"
    # inside the goal's own place the goal is open on screen: a dated nudge links the cockpit, never the goal
    dated = goal("trusts", "Family finances", 1, [part("mtg", "Trusts meeting", date="2026-10-02", pid="p-tr")])
    n = N.derive([dated], {}, [], working=set(), today=TODAY, scope_goal="trusts", campaign_pid="c1")
    assert n["kind"] == "dated" and n["acts"] == [{"act": "open", "href": "/project/p-tr", "label": "open the cockpit"}]
    assert [a["label"] for a in N.derive([dated], {}, [], working=set(), today=TODAY, campaign_pid="c1")["acts"]] == ["open the cockpit", "open the goal"], "from the brief, both"
    # the starving nudge offers the cockpit whose age it quoted when that one is unseated
    starving = goal("tech", "Technical papers", 2, [part("p1", "Paper 1", kind="project", pid="p-one"), part("p2", "Paper 2", kind="project", pid="p-two")])
    n2 = N.derive([starving], {}, [], working=set(), today=TODAY, strip_ages={"p-one": 3, "p-two": 20})
    assert "untouched for 20 days" in n2["text"] and n2["acts"][0] == {"act": "seat", "step": "p2", "seat": "deck", "label": "put Paper 2 on deck"}


def test_not_now_is_a_receipt_until_the_fact_changes_with_undo(tmp_path):
    c = tmp_path / "Campaign"; c.mkdir()
    deck = goal("mba", "MBA Teaching", 1, [part("hw", "retool homework 2", kind="project", pid="p-mba", seat="deck", state="waiting on you: approve the plan", needs_you=True)])
    n = N.derive([deck], {}, [], working=set(), today=TODAY)
    r = N.dismiss(str(c), n["key"], n["fact"], n["text"])
    assert r["ok"] and (c / ".ecgberht" / "nudges.json").is_file()
    assert N.derive([deck], {}, [], working=set(), today=TODAY, dismissed=N.read_dismissed(str(c))) is None, "silenced"
    deck["parts"][0]["state"] = "waiting on you: sign the syllabus"
    again = N.derive([deck], {}, [], working=set(), today=TODAY, dismissed=N.read_dismissed(str(c)))
    assert again and again["key"] != n["key"], "the fact changed: a new nudge"
    assert N.undismiss(str(c), n["key"])["ok"] and n["key"] not in N.read_dismissed(str(c))
    assert N.dismiss(str(c), "../x")["ok"] is False and N.undismiss(str(c), "nope")["ok"] is False
    # through the page's act, with its undo
    assert "not_now" in acts.ACTS and "nudge_again" in acts.ACTS
    r2 = acts.act(str(c), {"act": "not_now", "key": n["key"], "fact": n["fact"], "text": n["text"]})
    assert r2["ok"] and r2["receipt"].startswith("not now") and r2["undo"] == {"act": "nudge_again", "key": n["key"]}
    assert n["key"] in N.read_dismissed(str(c))
    r3 = acts.act(str(c), r2["undo"])
    assert r3["ok"] and r3["undo"] == {"act": "not_now", "key": n["key"], "fact": n["fact"], "text": n["text"]} and n["key"] not in N.read_dismissed(str(c)), "the undo of the undo puts the receipt back whole (Grok W3)"


def test_the_nudge_sits_under_the_brief_and_in_the_goal_s_conversation_with_its_acts_and_its_fact():
    ctx = w2c._ctx()
    n = {"kind": "deck_wait", "key": "deck_wait:hw:abc123", "fact": "approve the plan", "text": "retool homework 2 waits on you and is only on deck \u2014 make it active?", "why": "its record: needs you · approve the plan",
         "acts": [{"act": "seat", "step": "hw", "seat": "active", "label": "make it active"}, {"act": "open", "href": "/project/p-mba", "label": "open"}]}
    ctx["nudge"] = n
    html = hsp.render_high_seat_html(ctx)
    # the brief is gone (2026-10-03): the nudge keeps its place at the top of the panel, in its own slot (Grok R1 F1)
    brief = html[html.index('<section class="nudgeslot" id="nudgeSlot"'):html.index("</section>", html.index('<section class="nudgeslot" id="nudgeSlot"'))]
    assert '<div class="nudge brief" data-nudge="deck_wait:hw:abc123" data-kind="deck_wait"><span class="nk">&#9873; the steward</span>' in brief and "make it active?</span>" in brief
    assert '<button class="mini" data-nudge-act="seat" data-step="hw" data-seat="active">make it active</button><a class="mini" href="/project/p-mba">open</a><button class="mini" data-nudge-act="not_now" data-key="deck_wait:hw:abc123" data-fact="approve the plan"' in brief
    assert '<span class="nwhy">read from its record: needs you · approve the plan</span>' in brief, "the receipt: the fact it read"
    assert html.index('id="nudgeSlot"') < html.index('id="dialogue"'), "at the top of the panel, above the conversation"
    ctx["nudge"] = None
    assert '<div class="nudge' not in hsp.render_high_seat_html(ctx), "no nudge, no line"
    cctx = w2._ctx()
    # one lane per item (2026-10-03): the goal's place shows a non-dated nudge; a dated one is the Cave's interrupt lane
    cctx["nudges"] = {"trusts": {"kind": "starving", "key": "starving:trusts:1", "fact": "1", "text": "The trusts is a Tier-1 goal untouched for 9 days — pick it up?", "why": "the days since its last turn: 9", "acts": [{"act": "open", "href": "/project/c1?open=trusts", "label": "open the goal"}]}}
    chtml = cpg.render_campaign_html(cctx, open_id="trusts")
    place = chtml[chtml.index('id="place-trusts"'):chtml.index("</article>", chtml.index('id="place-trusts"'))]
    assert '<div class="gconv"><div class="nudge goal" data-nudge="starving:trusts:1"' in place and "untouched for 9 days" in place and 'data-nudge-act="not_now"' in place, "the goal's conversation opens with its nudge"
    cctx["nudges"] = {"trusts": {"kind": "dated", "key": "dated:pkg:1", "fact": "2026-10-02", "text": "Excuse me: Stanford package is due tomorrow (The trusts).", "why": "x", "acts": []}}
    chtml = cpg.render_campaign_html(cctx, open_id="trusts")
    assert 'data-nudge="dated:pkg:1"' not in chtml, "a dated nudge is never painted in a goal's place"
    assert 'class="nudge' not in chtml[chtml.index('id="place-magi"'):chtml.index("</article>", chtml.index('id="place-magi"'))] if 'id="place-magi"' in chtml else True
    for f in ("high-seat-page.js", "campaign-page.js"):
        js = open(os.path.join(HERE, "static", f), encoding="utf-8").read()
        assert "var b = e.target.closest('[data-nudge-act]'); if (!b) return;" in js and "act({ act: 'not_now', key: b.getAttribute('data-key')" in js and "act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') })" in js and "act({ act: 'promote', seed: b.getAttribute('data-seed')" in js, f
        assert subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True).returncode == 0
    css = open(os.path.join(HERE, "static", "steward-dialogue.css"), encoding="utf-8").read()
    for s in (".nudge{", ".nudge .nk{", ".nudge .nacts .mini{", ".nudge .nwhy{", ".nudge.goal{"):
        assert s in css, s


def test_the_contexts_derive_the_nudge_and_the_standing_text_says_the_law(capsys):
    src = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert 'return _nudges.derive(initiatives, facts, seed_rows, working, today=today, strip_ages=_strip_ages(everything),' in src and '"lights": lights, "nudge": nudge, "lane": lane,' in src
    # one lane per item (2026-10-03): the panel's nudge is every kind but dated; the dated one is the Cave's interrupt lane
    assert 'head_lead=((head or {}).get("pid") or "", (head or {}).get("part") or ""), kinds=kinds)' in src and 'nudge = _nudge_or_log("high-seat", lambda: _derive_nudge(_nudges_k.NOT_DATED))' in src
    assert 'lane = _nudge_or_log("high-seat-lane", lambda: _derive_nudge({"dated"}))' in src
    assert 'return {i["id"]: _nudges.derive(initiatives, {}, [], working, today=today, strip_ages=_ages, goal_last_at=_last, dismissed=_dis, scope_goal=i["id"]' in src and 'kinds=_nudges.NOT_DATED) for i in initiatives}' in src and 'nudges = _nudge_or_log("campaign", _derive_nudges) or {}' in src and '"guides": guides, "nudges": nudges,' in src
    assert "def _strip_ages(entries):" in src and "def _goal_last_at(campaign_dir):" in src
    # Grok W3 (RC-G): the guard logs the failure it exists for, and the page goes on without a nudge
    import anchor_gui as ag

    def boom():
        raise TypeError("'int' object is not iterable")
    assert ag._nudge_or_log("high-seat", boom) is None
    out = capsys.readouterr().out
    assert "NUDGE derive failed (high-seat): TypeError(" in out and "int" in out
    assert ag._nudge_or_log("campaign", lambda: {"g": None}) == {"g": None} and capsys.readouterr().out == ""
    skill = open(r"C:\dev\Ecgberht\SKILL.md", encoding="utf-8").read() if os.path.exists(r"C:\dev\Ecgberht\SKILL.md") else ""
    if skill:
        assert "9. **The nudges" in skill and "`.ecgberht/nudges.json`" in skill and "never twice for the same fact; never more than one at a boundary" in skill and "W3 of the\n     active set and are written here then" not in skill
