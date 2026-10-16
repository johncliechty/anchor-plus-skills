"""desk_page — the Desk view renders John's tasks from the Campaign record, grouped by when they are wanted, with
Calendar and Email honestly empty and the record's status beside them (W3b, High Seat); the retag act moves a part
between initiatives through the real engine on a temp record."""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desk_page as dp  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402

TODAY = date(2026, 9, 26)          # a Saturday; the week is Sep 21–27
MBA = "6765ece4b3bc43b0b0b0907b92b17280"


def _steps():
    return [
        {"id": "personal-admin", "name": "Personal admin", "status": "proposed", "tier": 3, "area": "personal",
         "navigation": {"path": ["personal-admin"], "groups": [{"id": "personal-admin", "label": "Personal admin", "order": 0, "parent_id": None}]}},
        {"id": "tax", "name": "pay the Delaware tax bill", "status": "planned", "due": "2026-10-03", "navigation": {"path": ["personal-admin"]}},
        {"id": "receipts", "name": "point the steward at the receipts folder", "status": "waiting", "waiting_on": "John", "navigation": {"path": ["personal-admin"]}},
        {"id": "lesson", "name": "the Deacons lesson", "status": "planned", "due": "2026-09-27", "navigation": {"path": ["personal-admin"]}},
        {"id": "passport", "name": "renew the passport", "status": "parked", "waiting_on": "January", "navigation": {"path": ["personal-admin"]}},
        {"id": "expenses", "name": "expenses for the trust", "status": "done", "due": "2026-09-20", "navigation": {"path": ["personal-admin"]}},
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 0, "parent_id": None}]}},
        {"id": "hw", "name": "retool homework 2", "status": "active", "due": "2026-10-27", "navigation": {"path": ["mba-teaching"]}},
        {"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + MBA, "navigation": {"path": ["mba-teaching"]}},
    ]


def _ctx(steps=None):
    inits = hsp.campaign_initiatives(steps if steps is not None else _steps(), {"mba-project": {"kind": "project", "name": "MBA Teaching AI", "what": "", "state": "waiting", "date": "2026-10-10", "href": "/project/" + MBA, "broken": False, "gap": ""}})
    return {"pid": "df56", "name": "Campaign", "today": TODAY, "today_str": "Saturday, September 26, 2026", "brief_when": "19:50 · Saturday 26 September",
            "build": "test", "steward": {"key": "jarvis", "label": "Jarvis", "high_seat": "jarvis-high-seat-hat.jpg", "seal": "jarvis-seal-salver.jpg", "high_seat_name": "Tip of the Hat", "seal_name": "Server"},
            "prefs_html": "<span id='prefs-here'></span>", "initiatives": inits, "seeds": [], "turns": [{"you": True, "text": "what needs me today?", "at": "19:40"}],
            "projects": [], "tick_allowed": False,
            "status": {"lead": "Next: the receipts folder — both expense piles wait on it.", "at": "2026-09-26 19:40", "facts": [("Summary", "6 tasks on the Desk"), ("Blocker", "")], "stale": False, "live": False, "last_run_at": "2026-09-26 19:40"},
            "capacity": [{"name": "ChatGPT", "state": "not measured yet", "note": "nothing is guessed"}]}


def test_the_tasks_are_grouped_by_when_they_are_wanted_with_their_initiative_chip():
    tasks = dp.desk_tasks(_ctx()["initiatives"])
    assert [t["id"] for t in tasks] == ["hw", "tax", "receipts", "lesson", "passport", "expenses"]     # tier order; the ref part left out
    admin = [t for t in tasks if t["admin"]]
    assert [t["id"] for t in admin] == ["tax", "receipts", "lesson", "passport", "expenses"]
    week_end = date(2026, 9, 27)
    g = {t["id"]: dp.group_of(t, TODAY, week_end) for t in tasks}
    assert g == {"hw": "today", "receipts": "today", "lesson": "week", "tax": "later", "passport": "parked", "expenses": "done"}
    html = dp.render_desk_html(_ctx())
    assert "<title>The Desk" in html and "desk-page.css" in html and "desk-page.js" in html
    assert 'id="tkCount">4 open &middot; 1 parked &middot; 1 done</span>' in html
    assert 'data-group="today"' in html and "This week &middot; Sep 21&ndash;Sep 27" in html and 'data-group="parked"' in html
    assert 'data-row="receipts" data-needs="1" data-dated="0" data-admin="1"' in html
    assert 'data-row="hw" data-needs="0" data-dated="1" data-admin="0"' in html
    assert '<select class="psel admin" data-retag="tax"' in html and '<option value="personal-admin" selected>admin</option>' in html
    assert 'class="rstate">parked until January</span>' in html and 'data-act="unpark" data-id="passport"' in html
    assert 'data-act="tick" data-id="tax" aria-label="Mark done" disabled title="a tick waits on your word' in html
    assert 'data-act="del" data-id="tax"' in html and 'data-act="unflag" data-id="receipts"' in html
    assert 'data-filter="needs"' in html and '&#9873; needs you<span class="n">1</span>' in html and 'admin<span class="n">5</span>' in html and 'dated<span class="n">4</span>' in html
    add = html[html.index('id="addProj">'):]
    assert '<option value="personal-admin" selected>admin</option>' in add[:400]     # admin is the add line's default, in priority order
    assert "<span id='prefs-here'></span>" in html and "MBA Teaching AI (the project)" not in html


def test_the_brief_calendar_email_status_and_capacity_say_what_they_know():
    html = dp.render_desk_html(_ctx())
    bullets = dp.brief_bullets(_ctx())
    assert bullets[0].startswith("&#9873; <b>point the steward at the receipts folder</b> waits on your word")
    assert '<span class="n">4</span> open on the Desk: <span class="n">1</span> need your word, <span class="n">3</span> are admin' in bullets[1]
    assert "This week, Sep 21" in bullets[2] and "the Deacons lesson (Sep 27)" in bullets[2]
    assert "Inside ten days: the Deacons lesson" in bullets[3] and "pay the Delaware tax bill" in bullets[3]
    assert "3 dated tasks" in html and 'class="d today"' in html and '<div class="tmark">the Deacons lesson</div>' in html
    assert "The 1 mark shown is the Campaign&rsquo;s own dated task, not an event." in html
    assert 'data-label="October 2026"' in html and "&#9679; pay the Delaware tax bill" in html
    assert "0 messages" in html and "Connect an account" in html
    assert "Next: the receipts folder" in html and "<dt>Blocker</dt><dd><i>nothing recorded</i></dd>" in html and "the record now; the last run 2026-09-26 19:40" in html
    assert "not measured yet" in html and "what needs me today?" in html
    failed = _ctx(); failed["status"] = {"lead": "The status could not be read: OSError: boom", "at": "", "facts": [], "failed": True}
    h3 = dp.render_desk_html(failed)
    assert "The status could not be read: OSError: boom" in h3 and "read failed" in h3 and "the Desk still renders" in h3


def test_an_empty_record_says_so_and_a_missing_admin_initiative_is_named():
    empty = _ctx(steps=[])
    html = dp.render_desk_html(empty)
    assert "No initiative on the Campaign yet" in html and 'id="addText"' not in html
    assert "Nothing on the Desk waits on your word and nothing is dated." in html
    only_mba = _ctx(steps=[s for s in _steps() if s["id"] in ("mba-teaching", "hw")])
    html2 = dp.render_desk_html(only_mba)
    assert "<b>No admin initiative yet</b>" in html2 and '<option value="mba-teaching">MBA Teaching, Fall 2026</option>' in html2


def test_the_high_seat_desk_line_opens_the_desk_when_the_campaign_exists():
    ctx = {"campaign": {"pid": "df56", "name": "Campaign"}, "tasks_open": 13}
    assert 'href="/project/df56?view=desk" target="_blank"' in hsp._desk_line(ctx)
    assert "after the Campaign exists" in hsp._desk_line({"campaign": None, "tasks_open": 13})


# ── retag, on a temp record through the real engine ────────────────────────────────────────

ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")


@pytest.fixture
def record(tmp_path):
    if not ECG.is_file() or shutil.which("node") is None:
        pytest.skip("the engine CLI is not on this machine")
    d = tmp_path / "Campaign"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> the Campaign.\n", encoding="utf-8")

    def cli(*args):
        r = subprocess.run(["node", str(ECG), *args, "--project", str(d)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return json.loads(r.stdout)
    for sid, name, tier in (("admin", "Personal admin", 3), ("mba", "MBA Teaching", 1)):
        assert cli("roadmap-propose", "--step", sid, "--name", name, "--tier", str(tier))["ok"]
        assert acts._spine_set(d, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": 0, "parent_id": None}], "role": "primary"}})["ok"]
    assert cli("roadmap-propose", "--step", "tax", "--name", "pay the tax bill")["ok"]
    assert acts._spine_set(d, "tax", {"navigation": {"path": ["admin"]}})["ok"]
    return d


def test_retag_moves_a_task_between_initiatives_and_refuses_a_heading(record):
    r = acts.act(record, {"act": "retag", "step": "tax", "initiative": "mba"})
    assert r["ok"] and "moved to MBA Teaching" in r["receipt"] and r["undo"] == {"act": "retag", "step": "tax", "initiative": "admin"}
    assert acts._step(record, "tax")["navigation"]["path"] == ["mba"]
    assert acts.act(record, r["undo"])["ok"] and acts._step(record, "tax")["navigation"]["path"] == ["admin"]
    assert acts.act(record, {"act": "retag", "step": "tax", "initiative": "admin"})["ok"] is False        # already there
    assert acts.act(record, {"act": "retag", "step": "admin", "initiative": "mba"})["ok"] is False        # a heading is not a part
    assert acts.act(record, {"act": "retag", "step": "tax", "initiative": "nowhere"})["ok"] is False


def test_the_desk_puts_the_composer_right_below_the_brief():
    """John, 2026-09-27: the interaction with the steward stays in the middle, right below the Brief; the exchanges after."""
    html = dp.render_desk_html(_ctx())
    col = html[html.index('aria-label="The steward"'):html.index('aria-label="The steward"') + 6000]
    assert col.index('id="brief"') < col.index('class="composer"') < col.index('class="exwrap"')
    # the exchanges are INSIDE the column: the column's own </section> comes after them (a Playwright locator caught it outside once)
    from html.parser import HTMLParser
    class _Depth(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack = []; self.exwrap_inside = None
        def handle_starttag(self, tag, attrs):
            a = dict(attrs); self.stack.append(a.get("aria-label") or a.get("class") or tag)
            if a.get("class") == "exwrap":
                self.exwrap_inside = "The steward" in self.stack
        def handle_endtag(self, tag):
            if self.stack:
                self.stack.pop()
    d = _Depth(); d.feed(html)
    assert d.exwrap_inside is True

