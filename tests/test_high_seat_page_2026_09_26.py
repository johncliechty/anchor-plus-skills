"""high_seat_page — the High Seat rendered from facts (W1b). Pure: a synthetic context, no server."""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402

TODAY = date(2026, 9, 26)


def _steps():
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    return [
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional",
         "done_when": "HMBA lectures 3-4 taught Oct 10",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 0, "parent_id": None}]}},
        {"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lectures-3-4", "name": "Lectures 3 + 4", "status": "proposed", "ref": "step:%s/lectures-3-4-revision" % mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lecture-99", "name": "A reference that does not exist", "status": "proposed", "ref": "step:%s/lecture-99" % mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "trusts", "name": "The trusts", "status": "proposed", "tier": 2, "area": "family",
         "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}},
        {"id": "hw", "name": "retool homework 2", "status": "planned", "due": "2026-10-27", "navigation": {"path": ["mba-teaching"]}},
    ]


def _resolved():
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    return {
        "mba-project": {"kind": "project", "pid": mba, "name": "MBA Teaching AI", "what": "", "state": "waiting on you: approve the Lecture 3 AI supplement", "date": "2026-10-10", "href": "/project/" + mba, "broken": False, "gap": ""},
        "lectures-3-4": {"kind": "step", "pid": mba, "name": "MBA Teaching AI", "what": "Lectures 3 + 4 revised, with AI supplements", "state": "waiting", "date": "2026-10-10", "href": "/project/" + mba, "broken": False, "gap": ""},
        "lecture-99": {"kind": "step", "name": "MBA Teaching AI", "what": "", "state": "", "date": "", "href": "", "broken": True, "gap": "no step 'lecture-99' in MBA Teaching AI"},
    }


def _ctx(campaign=True):
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    entries = [
        {"id": mba, "name": "MBA Teaching AI", "folder_path": "C:/x/mba", "blurb": "The course.", "group": "Teaching", "state": "active"},
        {"id": "9405abe0", "name": "Family <Trusts>", "folder_path": "C:/x/trusts", "blurb": "", "group": "Personal", "state": "active"},
        {"id": "quiet", "name": "Quiet one", "folder_path": "C:/x/q", "blurb": "", "group": "Ungrouped", "state": "active"},
    ]
    facts = {
        mba: {"id": mba, "name": "MBA Teaching AI", "href": "/project/" + mba, "needs_you": "approve the Lecture 3 AI supplement", "next": "Lecture 4", "why": "", "summary": None, "summary_age_s": None,
              "dated": [{"step_id": "lec", "name": "Lectures 3 + 4 revised", "due": "2026-10-10", "status": "waiting", "project_id": mba, "project_name": "MBA Teaching AI"},
                        {"step_id": "old", "name": "Block 1 quiz", "due": "2026-09-20", "status": "planned", "project_id": mba, "project_name": "MBA Teaching AI"}], "nearest_due": "2026-09-20", "has_record": True},
        "9405abe0": {"id": "9405abe0", "name": "Family <Trusts>", "href": "/project/9405abe0", "needs_you": "", "next": "Send the valuations", "why": "the package closes on them", "summary": None, "summary_age_s": None,
                     "dated": [{"step_id": "v", "name": "Valuations", "due": "2026-11-30", "status": "active", "project_id": "9405abe0", "project_name": "Family <Trusts>"}], "nearest_due": "2026-11-30", "has_record": True},
        "quiet": {"id": "quiet", "name": "Quiet one", "href": "/project/quiet", "needs_you": "", "next": "", "why": "", "summary": None, "summary_age_s": None, "dated": [], "nearest_due": "", "has_record": False},
    }
    rows = [{"rule": "needs-you", "rule_label": "the steward's record waits on you", "severity": "red", "text": "MBA Teaching AI is waiting on you", "why": "approve the Lecture 3 AI supplement", "href": "/project/" + mba, "kind": "project", "project_id": mba},
            {"rule": "due-soon", "rule_label": "due within five weeks", "severity": "amber", "text": "Lectures 3 + 4 revised", "why": "due Oct 10 · MBA Teaching AI", "href": "/project/" + mba, "kind": "step", "project_id": mba}]
    initiatives = hsp.campaign_initiatives(_steps(), _resolved()) if campaign else []
    return {"today": TODAY, "today_str": "Saturday, September 26, 2026", "week": "this week Sep 21–27", "week_short": "Sep 21–27",
            "brief_when": "18:30 · Saturday 26 September", "build": "test", "steward": {"key": "jarvis", "label": "Jarvis", "high_seat": "jarvis-high-seat-hat.jpg", "high_seat_name": "Tip of the Hat", "seal_name": "Server"},
            "prefs_html": "<span id='prefs-here'></span>", "entries": entries, "groups": {"Teaching": [entries[0]], "Personal": [entries[1]], "Ungrouped": [entries[2]]},
            "facts": facts, "rows": rows, "bullets": ["MBA Teaching AI is waiting on you — approve the Lecture 3 AI supplement.", "You can act from here."],
            "counts": {"open": 3, "running": 1, "need_you": 1, "folders": 3}, "live": [{"text": "a build session", "project_id": mba, "lane": "build"}],
            "parked": [], "tasks_open": 13, "campaign": {"pid": "df56", "name": "Campaign"} if campaign else None, "initiatives": initiatives, "seeds": 0,
            "capacity": [{"name": "ChatGPT", "state": "not measured yet", "note": "W4"}],
            "seed_rows": [{"id": "s3", "text": "An AI mechanics class with the group", "at": "2026-09-26"}] if campaign else [],
            "projects_html": '<div class="rnd-projects"><div class="rnd-folder-list"><div class="rnd-folder rnd-collapsed"><div class="rnd-folder-head">Teaching</div></div></div></div>'}


def test_campaign_initiatives_are_heading_steps_with_their_parts_in_tier_order():
    inits = hsp.campaign_initiatives(_steps(), _resolved())
    assert [i["name"] for i in inits] == ["MBA Teaching, Fall 2026", "The trusts"]
    assert [i["number"] for i in inits] == [1, 2] and inits[0]["tier"] == 1 and inits[1]["tier"] == 2
    mba = inits[0]
    assert [p["kind"] for p in mba["parts"]] == ["project", "step", "step", "task"]
    assert mba["parts"][1]["text"] == "Lectures 3 + 4 revised, with AI supplements" and mba["parts"][1]["date"] == "2026-10-10"
    assert mba["parts"][2]["broken"] and mba["parts"][2]["gap"].startswith("no step")
    assert mba["parts"][3]["text"] == "retool homework 2" and mba["parts"][3]["date"] == "2026-10-27"
    assert mba["next"]["kind"] == "project" and mba["needs"][0]["kind"] == "project"
    assert mba["next_deadline"] == "2026-10-10"


def test_the_ruler_buckets_dates_by_the_weeks_of_the_page():
    facts = list(_ctx()["facts"].values())
    weeks, buckets, beyond, overdue = hsp.ruler_markers(facts, TODAY)
    assert weeks[0]["label"] == "Sep 21–27" and weeks[0]["name"] == "this week"
    assert buckets[0] == []                                                                     # a date before this Monday is not this week's delivery
    assert [m["name"] for m in overdue] == ["Block 1 quiz"] and overdue[0]["overdue"]          # it is named overdue, with its real date
    assert [m["name"] for m in buckets[2]] == ["Lectures 3 + 4 revised"]                       # Oct 10 is week 3
    assert [m["name"] for m in beyond] == ["Valuations"]                                        # Nov 30 is beyond the ruler


def test_the_page_renders_from_facts_and_escapes_them():
    html = hsp.render_high_seat_html(_ctx())
    assert "<title>Tip of the Hat</title>" in html and hsp.tab_icon_link(_ctx()["steward"]["high_seat"], "test", anchor=False) in html   # the tab: the High Seat's picture and the seat's name
    assert "high-seat-page.css" in html and "high-seat-page.js" in html
    assert 'class="mh-stew"' in html and 'mh-pill' not in html and 'id="stewBlock"' not in html      # W2c-4: the AI Cockpit pill left the masthead on his word   # the steward at the very top, beside the AI Cockpit pill
    assert "this week Sep 21–27" in html and "id='prefs-here'" in html
    assert "Family &lt;Trusts&gt;" in html and "Family <Trusts>" not in html
    # the Campaign tile: the Tier 1 line, one tile with its parts and the broken reference named
    assert "<b>Tier 1:</b> MBA Teaching, Fall 2026" in html and 'href="/project/df56"' in html
    assert "broken reference: no step &#x27;lecture-99&#x27; in MBA Teaching AI" in html
    assert "<b>Tier 2:</b> 1" in html      # W2c: the thin goals line
    # the shelves (W2c, 2026-09-30): nothing is seated on this record, so both shelves are empty and say so; the project is a
    # row in its goal, the trusts project is in no goal (a chip on the Projects tile), the record-less one is a line there (his word, 2026-09-27 17:05)
    assert 'id="card-6765ece4b3bc43b0b0b0907b92b17280"' not in html and 'data-step="mba-project"' in html and "nothing active &mdash; pull an initiative" in html
    assert 'data-proj="9405abe0"' in html and 'id="card-9405abe0"' not in html and 'id="card-quiet"' not in html and 'id="shQuiet"' not in html
    assert "3 projects in 3 folders &middot; <b>1</b> with no steward record yet" in html
    # the ruler and the panel
    assert "Overdue, before this week:" in html and "Block 1 quiz" in html and "Tasks &middot; <span id=\"taskTotal\">13</span>" in html
    assert "what you are working on now, in your order" in html and 'id="shTerm"' in html and "Workbench" not in html   # the Workbench retired 2026-10-02
    assert "Later this week" not in html and "raised by:" not in html, "his word 2026-10-02: the dated deliveries are enough - no Today block"
    assert "Sample data" not in html


def test_the_page_boots_with_the_campaign_id_and_an_undo_on_its_receipt_line():
    html = hsp.render_high_seat_html(_ctx(campaign=True))
    assert 'window.ANCHOR_BOOT = {build_id: "test", campaign_pid: "df56", auth_required: false, logged_in: false, steward: "Jarvis", stamp: "", you: "John", health: ""}' in html and 'id="undoBtn" hidden' in html      # W2c-2: the steward's label and the stamp ride the boot
    assert 'campaign_pid: ""' in hsp.render_high_seat_html(_ctx(campaign=False))


def test_without_a_campaign_the_tile_says_so_honestly():
    html = hsp.render_high_seat_html(_ctx(campaign=False))
    assert "not stood up yet" in html and "Show Tier 1" not in html


def test_the_board_names_the_effort_a_card_reads_and_shelves_the_record_less_projects():
    ctx = _ctx(campaign=True)
    html = hsp.render_high_seat_html(ctx)
    assert 'class="mh-mark"' in html                                                  # the masthead mark carries its size class
    # a fact that reads an effort one folder down names it on the card and hands it to the card's parts
    e = {"id": "eff1", "name": "Skill Foundry", "blurb": "the foundry"}
    f = {"has_record": True, "effort": "steward-refinement", "next": "Fold the handback", "needs_you": ""}
    c = hsp._card(e, f, "")
    assert 'data-dir="steward-refinement"' in c and '<span class="t-eff">&middot; steward-refinement</span>' in c
    assert "touched" not in c                                                        # no age on the card (Grok R6: not a receipt, not the cockpit's clock)
    assert c.count('data-dir="steward-refinement"') == 5                            # the card and its four acts
    assert "reads the effort" not in c and "t-effort" not in c                     # no third naming of the effort (Grok R7): the suffix and the Status part say it
    assert '<span class="t-nm">Skill Foundry</span><span class="t-eff">&middot; steward-refinement</span>' in c   # two spans: the name gives way, the suffix stays whole
    q = hsp._card({"id": "q1", "name": "Quiet one", "blurb": "nothing yet"}, {"has_record": False}, "")
    assert 'class="tile quiet"' in q and "no steward record yet" in q and "Open cockpit" in q and "data-part=" not in q


def test_the_compact_card_says_one_line_and_puts_status_first_among_the_acts():
    """The compact card (John, 2026-09-27): the name, ONE line, the acts — Status first — and nothing else until it opens."""
    e = {"id": "p1", "name": "MBA Teaching AI", "blurb": "The course."}
    waiting = hsp._card(e, {"has_record": True, "effort": "", "next": "Lecture 4", "needs_you": "approve the Lecture 3 AI supplement"}, " need")
    acts = waiting[waiting.index('class="t-acts"'):waiting.index('class="t-body"')]
    assert re.findall(r'data-part="([a-z]+)"', acts) == ["status", "next", "deliverables", "plan"]      # W2e-2: the opened tile carries its dialogue itself; the acts are the details
    assert "statusbtn" not in waiting and 'class="t-go" href="/steward/v1?pid=p1&amp;dir="' in waiting
    # the one line is the wait; the description and the next step wait behind the open, before the acts
    assert waiting.index('class="t-line wait"') < waiting.index('class="t-more"') < waiting.index('class="t-next"') < waiting.index('class="t-acts"')
    assert "Needs you:</span>approve the Lecture 3 AI supplement" in waiting and "Next</span>Lecture 4" in waiting and "The course." in waiting
    assert "t-eff" not in waiting and '<span class="t-nm">MBA Teaching AI</span></h3>' in waiting   # a root record names no effort
    plain = hsp._card(e, {"has_record": True, "effort": "", "next": "", "needs_you": ""}, "")
    assert '<div class="t-line"><span class="k">Next</span>not stated</div>' in plain and "t-next" not in plain


def test_the_page_script_says_plainly_when_the_browser_is_not_logged_in():
    """A lint on the served script, not a pixel: the 401 sentence, the one-time token ask and the login POST are there,
    and the old Status button beside the name is gone."""
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "This browser is not logged in to Anchor, so the record cannot be read." in js
    assert "r.status === 401 || r.status === 403" in js and "'/api/auth/login'" in open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "steward-dialogue.js"), encoding="utf-8").read() and "loginBox({ receiptKey: 'highseat_receipt', onLogin:" in js and "askedOnce" in js, "the login POST lives in the dialogue module now (one script for both pages, Grok's read of W2e-3)"
    assert "statusbtn" not in js and "data-login" in js and "b.closest('.balloon')" in js   # a balloon re-reads after a paste (Grok R7)
    assert "'/api/version'" in js and "location.reload()" in js                    # a redeploy reloads the open page (the old home's watcher)
    assert js.count("fetch('/api/auth/login'") == 0 and open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "steward-dialogue.js"), encoding="utf-8").read().count("fetch('/api/auth/login'") == 1                                 # one login(): the hand-off and the paste share it (Grok R7)


def test_the_campaign_tile_shows_compact_initiatives_with_a_light_and_opens_to_a_status():
    """John, 2026-09-27: every initiative tile is its name, one line and a light — needs you · working · waiting · idle —
    on the home and the Campaign page; open, it shows what it showed before plus its Status."""
    inits = hsp.campaign_initiatives(_steps(), _resolved())
    mba, trusts = inits[0], inits[1]
    assert hsp.initiative_light(mba) == "needs" and hsp.initiative_line(mba) == ("&#9873; approve the Lecture 3 AI supplement", "wait")   # the action itself (Grok R8)
    assert hsp.initiative_light(trusts) == "idle" and hsp.initiative_line(trusts) == ("nothing open", "none")
    # a referenced project with something running lights the initiative "working" once nothing waits on him
    quiet = dict(mba, needs=[])
    assert hsp.initiative_light(quiet, working={"6765ece4b3bc43b0b0b0907b92b17280"}) == "working"
    assert hsp.initiative_light(quiet) == "waiting"                                   # its step part waits (on its own record, not on him)
    assert mba["parts"][0]["pid"] == "6765ece4b3bc43b0b0b0907b92b17280"               # the part carries its target's id for the light
    st = hsp.initiative_status_html(dict(mba, parts=[dict(mba["parts"][0], lead="Next: Lecture 3 — the interface lesson is final.")] + mba["parts"][1:]))
    assert "Status</span>" in st and "Next: Lecture 3" in st and "waiting on you" not in st and "parts" not in st   # the lead lines only (Grok R8)
    html = hsp.render_high_seat_html(_ctx(campaign=True))
    camp = html[html.index('<section class="camp'):html.index('id="shActive"')]
    assert 'class="camp" id="camp"' in camp and ">Expand<" in camp                 # closed by default; its head toggles it (13:15); W2c: the thin goals tile
    row = camp[camp.index('class="grow needs" data-g="mba-teaching"'):camp.index('data-g="trusts"')]
    assert '<span class="ilight needs"' in row and "needs you</span>" in row      # the goal's row carries the light
    assert 'data-seat="active" data-step="mba-project"' in row and "rides inside" in row, "W2c: the project drags out or takes a button; a step of a project rides inside its goal"
    assert "pt-legend" not in html and "ini-tile" not in html


def test_the_projects_tile_holds_the_old_dashboards_list_with_every_folder_closed(tmp_path, monkeypatch):
    """John, 2026-09-27: the Projects tile opens to the old dashboard's project list, same look, every folder closed.
    The page embeds the list it is handed; the list is the old renderer's, its folders collapsed, without the kebab."""
    html = hsp.render_high_seat_html(_ctx())
    tile = html[html.index('id="ptile"'):html.index('id="deskline"')]      # W2c: the Desk line follows the Projects tile
    assert 'class="rnd-folder rnd-collapsed"' in tile and 'class="prow"' not in tile and "fold-h" not in tile
    assert "&middot; 3 projects in 3 folders" in tile and "The registry as it stands" not in tile       # the head says the noun; no lecture (Grok R8b)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    import anchor_gui
    entries = [{"id": "p1", "name": "One", "folder_path": str(tmp_path), "group": "Teaching"}, {"id": "p2", "name": "Two", "folder_path": str(tmp_path), "group": "Teaching"}]
    out = anchor_gui._high_seat_projects_html({"Teaching": entries}, {})
    assert out.count('class="rnd-folder rnd-collapsed"') == 1 and out.count('class="rnd-row"') == 2
    assert 'onclick="openProjectWindow(' in out and 'onclick="rndToggleFolder(this)"' in out
    assert "rnd-kebab" not in out and "rnd-row-roll" not in out and "rnd-grave" not in out   # the old page's menu, rollup and boneyard button need its script
    assert "draggable" not in out and "rnd-grip" not in out and "drop here" not in out         # and its drag (Grok R8b: the renderer's own argument, no clip)
    full = anchor_gui._render_group_folders({"Teaching": entries}, {})
    assert "rnd-kebab" in full and 'draggable="true"' in full                                   # the old dashboard's own list is untouched
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "u25BE" in js and "rnd-collapsed" in js                                            # the folder arrow turns when it opens


def test_the_seeds_button_opens_a_panel_of_the_campaigns_seeds():
    """John, 2026-09-27: the Seeds button did nothing. It opens a panel: each seed with Make it an initiative (the
    steward's verb into the composer; Send is the word) and the way to the Campaign; no writer."""
    html = hsp.render_high_seat_html(_ctx(campaign=True))
    panel = html[html.index('id="seedPanel"'):html.index('id="nudgeSlot"')]
    assert 'aria-controls="seedPanel"' in html and "Seeds &middot; 1" in panel
    assert 'data-seed="s3"' in panel and "An AI mechanics class with the group" in panel and 'data-seed-text="An AI mechanics class with the group"' in panel
    assert 'href="/project/df56"' in panel and "asks both on the card" in panel
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "seedPanel.classList.toggle('open')" in js and "an initiative in tier 3" in js
    quiet = hsp.render_high_seat_html(_ctx(campaign=False))
    assert "The Campaign is not stood up yet" in quiet[quiet.index('id="seedPanel"'):]

