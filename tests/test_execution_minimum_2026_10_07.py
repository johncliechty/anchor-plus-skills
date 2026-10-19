"""The execution minimum set (PROPOSAL v1.1, 2026-10-07). Item 1: Next steps stable and complete, the narrow cockpit,
open at the newest message. Hermetic: a throwaway server on a free port with a temp data dir (never :8777)."""
import time

from playwright.sync_api import expect

from steward_cockpit import steward_campaign as sc
from tests.test_steward_refinement_browser import campaign_server, cockpit
from tests.test_cockpit_selected_b import open_surface


# ---------- item 1: every current product is its own row; the formats of one product are one row ----------

def test_format_tags_strip_every_spelling_the_registers_use():
    for raw, want in [("NYU Viva quick start - Refinement 1 MD", "NYU Viva quick start - Refinement 1"),
                      ("Quiz 1 - Bank - Draft 3 (PDF)", "Quiz 1 - Bank - Draft 3"),
                      ("Quiz 1 - Bank - Draft 3 (browser)", "Quiz 1 - Bank - Draft 3"),
                      ("Verification, Draft 1 (browser reading)", "Verification, Draft 1"),
                      ("Instructor Materials (TA download)", "Instructor Materials"),
                      ("Quiz-1-Viva-Guide-PDF", "Quiz-1-Viva-Guide"),
                      ("Teaching-Calendar-Report", "Teaching-Calendar-Report"),
                      ("Thermopdf", "Thermopdf")]:          # a word that merely ends in a format name keeps it
        assert sc._strip_format_tag(raw) == want, raw


def test_review_acts_one_row_per_product_with_companions():
    items = [
        {"what": "Guide - Refinement 1 MD", "path": "q/Guide - Refinement 1.md", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 PDF", "path": "q/Guide - Refinement 1.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 HTML", "path": "q/Guide - Refinement 1.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Calendar (accepted).ics", "path": "q/Calendar (accepted).ics", "step": "s1", "date": "2026-10-07"},
        {"what": "Viva-Guide-PDF", "product_id": "Viva-Guide-PDF", "managed": True, "phase": "awaiting_review", "presentation_id": "viva-1",
         "path": "deliverables/Viva-Guide-PDF/a.pdf", "step": "s2"},
        {"what": "Viva-Guide-HTML", "product_id": "Viva-Guide-HTML", "managed": True, "phase": "awaiting_review", "presentation_id": "viva-1",
         "path": "deliverables/Viva-Guide-HTML/b.html", "step": "s2"},
        {"what": "Bank (PDF)", "managed": True, "phase": "awaiting_review", "path": "deliverables/Bank/c.pdf", "step": "s3"},
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    rows = [(a["act"], a["label"], a["path"], len(a.get("companions") or [])) for a in acts]
    assert rows == [
        ("Review", "Viva Guide", "deliverables/Viva-Guide-PDF/a.pdf", 1),       # reviews first; PDF is the face
        ("Review", "Bank", "deliverables/Bank/c.pdf", 0),
        ("Open", "Guide - Refinement 1", "q/Guide - Refinement 1.pdf", 2),       # three formats, one decision
        ("Open", "Calendar (accepted).ics", "q/Calendar (accepted).ics", 0),
    ]
    assert [c["path"] for c in acts[2]["companions"]] == ["q/Guide - Refinement 1.html", "q/Guide - Refinement 1.md"]
    assert acts[2]["companions"][0]["item"]["what"] == "Guide - Refinement 1 HTML"


def test_grouping_never_merges_different_products_or_versions():
    items = [
        {"what": "FOR REVIEW: Summary (PDF)", "path": "a/Summary.pdf", "step": "s1"},
        {"what": "FOR REVIEW: Summary (PDF)", "path": "b/Summary.pdf", "step": "s1"},          # another folder
        {"what": "Guide-PDF", "product_id": "Guide-PDF", "managed": True, "phase": "awaiting_review",
         "round": 2, "path": "deliverables/Guide-PDF/x.pdf", "step": "s1"},
        {"what": "Guide-HTML", "product_id": "Guide-HTML", "managed": True, "phase": "awaiting_review",
         "round": 1, "path": "deliverables/Guide-HTML/y.html", "step": "s1"},                  # an older round
        {"what": "Bank (PDF; held)", "path": "q/Bank.pdf", "step": "s1"},
        {"what": "Bank (browser; held)", "path": "q/Bank.html", "step": "s1"},
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    assert len(acts) == 5
    bank = [a for a in acts if a["label"].startswith("Bank")]
    assert len(bank) == 1 and bank[0]["label"] == "Bank (held)" and len(bank[0]["companions"]) == 1


def test_a_newer_unrelated_product_does_not_hide_an_older_pending_one():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    map_ = {"steps": [step]}                                              # the one pinned step is the focus
    items = [
        {"what": "Guide - Draft 1", "path": "g/Guide - Draft 1.pdf", "step": "s1", "date": "2026-10-05"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.pdf", "step": "s1", "date": "2026-10-06"},
        {"what": "Calendar", "path": "c/Calendar.pdf", "step": "s1", "date": "2026-10-07"},
    ]
    assert sc._focused_step(map_)[0] is step
    whats = {it["what"] for it in sc.current_review_items(map_, items)}
    assert whats == {"Guide - Draft 2", "Calendar"}


# ---------- browser: the cockpit as John sees it ----------

def _frame(page):
    return page.frame_locator('[data-fsframe]')


def test_next_steps_rows_are_not_rebuilt_by_the_clock(cockpit):
    """A row's node survives the 1 s busy-clock repaint (it used to be rebuilt every second: icons re-created,
    clicks that spanned a rebuild swallowed, focus lost)."""
    page, server = cockpit
    surface = open_surface(page)
    body = surface.locator('[data-delivmount] .blk.next .body')
    expect(body).to_have_count(1)
    body.evaluate("b => { b.__marker = 'kept'; Array.from(b.querySelectorAll('*')).forEach(n => n.__marker = 'kept'); }")
    time.sleep(3.2)
    survivors = body.evaluate("b => Array.from(b.querySelectorAll('*')).filter(n => n.__marker === 'kept').length")
    total = body.evaluate("b => b.querySelectorAll('*').length")
    assert total > 0 and survivors == total


def test_dialogue_follows_the_newest_until_john_scrolls_up(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    scroll = surface.locator('.scroll').first
    # content arriving with no scroll event of its own (a late render) keeps the newest in view
    scroll.evaluate("""s => { for (let i = 0; i < 40; i++) { const d = document.createElement('div');
        d.style.height = '60px'; d.textContent = 'line ' + i; s.appendChild(d); } }""")
    page.wait_for_timeout(300)
    gap = scroll.evaluate("s => s.scrollHeight - s.scrollTop - s.clientHeight")
    assert gap < 5, gap
    # John scrolls up - even a little: arriving content no longer moves him
    scroll.hover()
    page.mouse.wheel(0, -60)
    page.wait_for_timeout(300)
    top = scroll.evaluate("s => s.scrollTop")
    scroll.evaluate("""s => { const d = document.createElement('div'); d.style.height = '400px'; d.textContent = 'late';
        s.appendChild(d); }""")
    page.wait_for_timeout(300)
    assert abs(scroll.evaluate("s => s.scrollTop") - top) < 2


def test_narrow_cockpit_closes_rail_and_status_for_now_only(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    app = surface.locator('.app')
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    saved = surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')")
    page.set_viewport_size({"width": 900, "height": 1000})
    expect(app).not_to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    expect(app).to_have_class(__import__('re').compile(r'\brailhide\b'))
    # reopened while narrow, the status pane overlays the dialogue instead of squeezing it
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    assert surface.locator('.rightcol').evaluate("e => getComputedStyle(e).position") == "fixed"
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    page.set_viewport_size({"width": 1700, "height": 1050})
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))   # his wide layout comes back as it was
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved


# ---------- item 2: reading and links, made mechanical ----------

import report_viewer
import deliverables_register as dr
from steward_cockpit import steward_engine


def test_reader_renders_tables_and_links_that_survive_spaces_and_parentheses():
    md = "\n".join(["| Week | File |", "|---|:--:|",
                    "| 1 | [Calendar](BA 815/Calendar (accepted).ics) |", "",
                    "See [y](<My Doc.md>) and [bad](javascript:alert(1)) and [z](https://e.com/a_(b))"])
    out = report_viewer.markdown_to_html(md)
    assert "<table>" in out and "<th>Week</th>" in out and "<td>1</td>" in out
    assert 'href="BA%20815/Calendar%20(accepted).ics"' in out
    assert 'href="My%20Doc.md"' in out and 'href="https://e.com/a_(b)"' in out
    assert "javascript" not in out and ">bad<" not in out


def test_reading_target_is_one_encoded_url_per_kind(tmp_path):
    eff = tmp_path / "MBA Teaching AI"
    (eff / "q").mkdir(parents=True)
    for name in ("Guide (v1).md", "Guide (v1).pdf", "Deck.pptx", "Talk.pptx", "Talk.pdf", "Cal (accepted).ics"):
        (eff / "q" / name).write_text("x", encoding="utf-8")
    t = lambda p: dr.reading_target({"path": p}, pid="p 1", effort_rel="MBA Teaching AI", effort_dir=eff,
                                    registered={"q/talk.pptx", "q/talk.pdf"})
    md = t("q/Guide (v1).md")
    assert md["read"] == ("/api/steward/deliverable-file?pid=p%201&dir=MBA%20Teaching%20AI"
                          "&path=q%2FGuide%20%28v1%29.md&render=1")
    assert t("q/Guide (v1).pdf")["read"].endswith("Guide%20%28v1%29.pdf")
    deck = t("q/Deck.pptx")
    assert deck["read"] is None and deck["preparing"] and deck["download"].endswith("&download=1")
    assert t("q/Talk.pptx")["read"].endswith("path=q%2FTalk.pdf")          # its PDF companion is the reading copy
    assert t("q/Cal (accepted).ics")["download"]
    assert t("q/missing.md")["read"] is None                                # nothing on disk: no link


def _receipt_engine(tmp_path, monkeypatch, rows):
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# a steward cockpit\n", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n" + "".join(rows), encoding="utf-8")
    eng = steward_engine.Engine.__new__(steward_engine.Engine)
    eng.dir, eng.general, eng.turn_started = str(eff), False, 0.0
    said, emitted = [], []
    eng.skey = lambda: "test"
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: said.append((role, text, turn_id)) or True
    eng._emit = lambda ev: emitted.append(ev)
    monkeypatch.setattr(steward_engine, "_update_state", lambda key, patch: True)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "eff"))
    return eng, eff, said, emitted


def test_the_engine_announces_each_new_product_once_with_its_read_link(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")                                     # baseline: announces nothing
    assert said == []
    (eff / "Report (final).md").write_text("# r", encoding="utf-8")
    (eff / "Report (final).pdf").write_text("x", encoding="utf-8")
    (eff / "Deck.pptx").write_text("x", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Report (final) MD | `Report (final).md` | 2026-10-07 | 1 |\n"
                 "| Report (final) PDF | `Report (final).pdf` | 2026-10-07 | 1 |\n"
                 "| Deck | `Deck.pptx` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t1")
    lines = [text for _role, text, _tid in said]
    assert len(lines) == 2, lines                                           # the md+pdf pair is ONE product
    report = next(l for l in lines if "Report" in l)
    assert "ready to read: [Report (final)](/api/steward/deliverable-file?pid=p1&dir=eff&path=Report%20%28final%29.pdf)" in report
    assert "[MD](/api/steward/deliverable-file?pid=p1&dir=eff&path=Report%20%28final%29.md&render=1)" in report
    deck = next(l for l in lines if "Deck" in l)
    assert "preparing a reading copy: Deck" in deck and "ready" not in deck and "[Download](" in deck
    assert [e["t"] for e in emitted] == ["receipt", "receipt"]
    eng._publish_delivery_receipt("t2")                                     # nothing new: nothing said again
    assert len(said) == 2


def test_cockpit_links_survive_spaces_and_parentheses_and_markdown_opens_formatted(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    (server.campaign / "notes (draft).md").write_text("# Notes\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    links = surface.locator('.scroll').first.evaluate("""s => {
        const box = document.createElement('div'); s.appendChild(box);
        mdRender(box, 'Read [the notes](/api/steward/deliverable-file?pid=p&dir=d&path=notes (draft).md) and ' +
                      '[bare path](C:/x/y.md) and [web](https://e.com/a_(b))');
        return Array.from(box.querySelectorAll('a')).map(a => a.getAttribute('href'));
    }""")
    assert len(links) == 2, links                                   # a bare path never becomes a link
    from urllib.parse import urlsplit, parse_qs
    q = parse_qs(urlsplit(links[0]).query)
    assert q["path"] == ["notes (draft).md"] and q["render"] == ["1"]
    assert links[1] == "https://e.com/a_(b)"
    # the canonical reading URL renders the markdown formatted, with its table
    from urllib.parse import quote
    url = (f"{server.origin}/api/steward/deliverable-file?pid={quote(server.project_id, safe='')}"
           f"&dir={quote(server.campaign.name, safe='')}&path={quote('notes (draft).md', safe='')}&render=1")
    reader = page.context.new_page()
    reader.goto(url)
    expect(reader.locator("table th").first).to_have_text("A")
    expect(reader.locator("h1")).to_have_text("Notes")
    reader.close()


def test_a_document_only_named_in_the_reply_still_gets_its_read_link(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "x").mkdir()
    doc = eff / "x" / "Teaching Plan (v2).md"
    doc.write_text("# plan", encoding="utf-8")
    (eff / "ECGBERHT.md").write_text("record", encoding="utf-8")
    reply = "Done - it is at " + str(doc) + " and I updated ECGBERHT.md."
    eng._publish_delivery_receipt("t1", reply=reply, written=[str(doc), str(eff / "ECGBERHT.md"), str(eff / "x" / "other.md")])
    assert len(said) == 1, said
    assert "ready to read: [Teaching Plan (v2)](/api/steward/deliverable-file?pid=p1&dir=eff&path=x%2FTeaching%20Plan%20%28v2%29.md&render=1)" in said[0][1]


# ---------- item 1, review round 2: one identity rule ----------

def test_formats_pair_only_on_affirmative_evidence():
    items = [
        {"what": "Guide (PDF)", "path": "q/guide-v1.pdf", "step": "s1"},
        {"what": "Guide (HTML)", "path": "q/guide-v2.html", "step": "s1"},                     # another version
        {"what": "Plan-PDF", "product_id": "Plan-PDF", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-2", "path": "deliverables/Plan-PDF/a.pdf", "step": "s1"},
        {"what": "Plan-HTML", "product_id": "Plan-HTML", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-1", "path": "deliverables/Plan-HTML/b.html", "step": "s1"},      # an older presentation
        {"what": "Talk-PDF", "product_id": "Talk-PDF", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-9", "path": "deliverables/Talk-PDF/c.pdf", "step": "s1"},
        {"what": "Talk-HTML", "product_id": "Talk-HTML", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-9", "path": "deliverables/Talk-HTML/d.html", "step": "s1"},      # presented together
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    assert len(acts) == 5
    talk = next(a for a in acts if a["label"] == "Talk")
    assert [c["item"]["product_id"] for c in talk["companions"]] == ["Talk-HTML"]


def test_one_family_keeps_only_its_newest_version_even_on_one_day():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    items = [
        {"what": "Guide - Draft 1", "path": "g/Guide - Draft 1.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Summary", "path": "a/Summary.pdf", "step": "s1", "date": "2026-10-06"},
        {"what": "Summary", "path": "b/Summary.pdf", "step": "s1", "date": "2026-10-07"},       # another folder
        {"what": "Bank - Draft 1", "path": "Quiz - Draft 1/Bank - Draft 1.pdf", "step": "s1", "date": "2026-10-01"},
        {"what": "Bank - Draft 3", "path": "Quiz - Draft 3/Bank - Draft 3.pdf", "step": "s1", "date": "2026-10-04"},
    ]
    paths = sorted(it["path"] for it in sc.current_review_items({"steps": [step]}, items))
    assert paths == ["Quiz - Draft 3/Bank - Draft 3.pdf", "a/Summary.pdf", "b/Summary.pdf",
                     "g/Guide - Draft 2.html", "g/Guide - Draft 2.pdf"]


def _add_rows(campaign, rows):
    reg = campaign / "DELIVERABLES.md"
    text = reg.read_text(encoding="utf-8")
    anchor = "| Earlier note | `legacy.txt` | 2026-09-01 | foundation |\n"
    assert anchor in text
    reg.write_text(text.replace(anchor, anchor + "".join(rows)), encoding="utf-8")


def _refresh(page):
    with page.expect_response(lambda r: "/deliverables?" in r.url and r.request.method == "GET"):
        page.frame_locator('[data-fsframe]').locator('body').evaluate(
            "() => window.dispatchEvent(new Event('anchor-notebooks-changed'))")


def test_a_changed_row_never_moves_the_focused_row_beside_it(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    for name in ("alpha.md", "beta.md"):
        (server.campaign / name).write_text("# " + name, encoding="utf-8")
    _add_rows(server.campaign, ["| FOR REVIEW: Alpha | `alpha.md` | 2026-10-07 | foundation |\n",
                                "| FOR REVIEW: Beta | `beta.md` | 2026-10-07 | foundation |\n"])
    _refresh(page)
    tile = surface.locator('[data-delivmount] .blk.next')
    if 'folded' in (tile.get_attribute('class') or ''):
        tile.locator('> .who').click()
    beta = tile.locator('.navact a', has_text='Beta').first
    expect(beta).to_be_visible()
    beta.evaluate("a => { a.__mark = 'same'; a.focus(); }")
    reg = server.campaign / "DELIVERABLES.md"
    reg.write_text(reg.read_text(encoding="utf-8").replace("FOR REVIEW: Alpha |", "FOR REVIEW: Alpha revised |"),
                   encoding="utf-8")
    _refresh(page)
    expect(tile.locator('.navact a', has_text='Alpha revised')).to_be_visible()
    assert surface.locator('body').evaluate("() => document.activeElement && document.activeElement.__mark") == "same"


# ---------- item 2, review round 1 fixes ----------

def test_reading_target_refuses_what_the_route_would_refuse_and_binds_decks_to_their_pdf(tmp_path):
    import os as _os
    eff = tmp_path / "eff"
    eff.mkdir()
    (tmp_path / "outside.pdf").write_text("x", encoding="utf-8")
    t = lambda it: dr.reading_target(it, pid="p", effort_rel="eff", effort_dir=eff, registered={"talk.pptx", "talk.pdf"})
    assert t({"path": "../outside.pdf"})["read"] is None                     # outside the effort: no link
    assert t({"path": "x.md", "openable": False})["read"] is None
    (eff / "Talk.pdf").write_text("old slides", encoding="utf-8")
    (eff / "Talk.pptx").write_text("new deck", encoding="utf-8")
    _os.utime(eff / "Talk.pdf", (1_000_000, 1_000_000))                     # yesterday's PDF, today's deck
    assert t({"path": "Talk.pptx"})["preparing"] is True
    _os.utime(eff / "Talk.pdf", None)                                       # a PDF made after the deck
    assert t({"path": "Talk.pptx"})["read"].endswith("path=Talk.pdf")
    managed = {"path": "Talk.pptx", "managed": True, "hash": "h"}
    assert t(managed)["preparing"] is True                                  # a managed deck: only its ledger PDF
    assert "view=1" in t({**managed, "visual_companion": {"path": "c.pdf"}})["read"]


def test_route_targets_are_rebuilt_encoded():
    hostile = "/artifact/p1?path=notes)[Other](/report/p/lane)"
    url = dr.reading_target({"route": hostile}, pid="p1", effort_rel="")["read"]
    assert ")" not in url and "[" not in url and url.startswith("/artifact/p1?path=")
    md = dr.reading_target({"route": "/artifact/p1?path=reports/Plan.md"}, pid="p1", effort_rel="")["read"]
    assert md == "/artifact/p1?path=reports%2FPlan.md&render=1"
    assert dr.reading_target({"route": "https://evil.example/x"}, pid="p1", effort_rel="")["read"] is None


def test_reader_takes_angle_targets_whole_and_tables_without_outer_pipes():
    out = report_viewer.markdown_to_html("[Read](<https://example.com/a)b>)\n\nA | B\n--- | ---\n1 | 2\n")
    assert 'href="https://example.com/a)b"' in out
    assert "<th>A</th>" in out and "<td>2</td>" in out


def test_a_receipt_that_could_not_be_saved_is_retried_not_lost(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "R.pdf").write_text("x", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| R | `R.pdf` | 2026-10-07 | 1 |\n")
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: False      # the save fails
    eng._publish_delivery_receipt("t1")
    assert emitted == []
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: said.append((role, text, turn_id)) or True
    eng._publish_delivery_receipt("t2")                                               # retried, once
    eng._publish_delivery_receipt("t3")
    assert len(said) == 1 and "ready to read: [R]" in said[0][1]


def test_a_shell_made_document_named_by_its_full_path_gets_a_link(tmp_path, monkeypatch):
    import time as _t
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    eng.turn_started = _t.time() - 5
    (eff / "out dir").mkdir()
    doc = eff / "out dir" / "Week 3 Plan (draft).pdf"
    doc.write_text("x", encoding="utf-8")
    eng._publish_delivery_receipt("t1", reply="I rendered it to " + str(doc) + " for you.", written=[])
    assert len(said) == 1 and "path=out%20dir%2FWeek%203%20Plan%20%28draft%29.pdf" in said[0][1]


# ---------- item 1, review round 3 ----------

def test_version_tokens_alone_are_removed_and_versions_order_as_numbers():
    assert sc._family_key({"path": "g/Guide-v1-instructor.pdf"}) != sc._family_key({"path": "g/Guide-v1-student.pdf"})
    assert sc._family_key({"path": "g/Guide - Draft 1.pdf"}) == sc._family_key({"path": "g/Guide - Draft 3.pdf"})
    assert sc._version_rank({"path": "Guide-v1.10.pdf"}) > sc._version_rank({"path": "Guide-v1.9.pdf"})
    assert sc._version_rank({"path": "Guide-v1.2.4.pdf"}) > sc._version_rank({"path": "Guide-v1.2.3.pdf"})


def test_a_designated_product_brings_its_other_formats_and_nothing_else():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    items = [
        {"what": "START HERE: Guide", "path": "g/Guide.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide (browser)", "path": "g/Guide.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Chapter 1", "path": "c/ch1.docx", "step": "s1", "date": "2026-10-07"},   # undesignated: not current
    ]
    paths = sorted(it["path"] for it in sc.current_review_items({"steps": [step]}, items))
    assert paths == ["g/Guide.html", "g/Guide.pdf"]


# ---------- item 2, review round 2 ----------

def test_a_changed_announcement_never_collides_with_a_saved_one(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    ids = {}
    def record(role, text, turn_id=None, goal=None):
        if turn_id in ids and ids[turn_id] != text:
            raise AssertionError("turn_id_conflict")
        ids[turn_id] = text
        said.append((role, text, turn_id))
        return True
    eng._record_conversation = record
    eng._publish_delivery_receipt("t0")
    (eff / "Talk.pptx").write_text("deck", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Talk | `Talk.pptx` | 2026-10-07 | 1 |\n")
    real_write = steward_engine._write_seen
    monkeypatch.setattr(steward_engine, "_write_seen", lambda cdir, seen: False)    # crash before the checkpoint
    eng._publish_delivery_receipt("t1")
    monkeypatch.setattr(steward_engine, "_write_seen", real_write)
    (eff / "Talk.pdf").write_text("slides", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Talk (PDF) | `Talk.pdf` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t2")                                       # the retry now says "ready"
    texts = [t for _r, t, _i in said]
    assert "preparing a reading copy: Talk" in texts[0] and "ready to read: [Talk]" in texts[-1]
    assert len(set(i for _r, _t, i in said)) == len(said)


def test_a_writer_announces_with_no_steward_loaded(tmp_path, monkeypatch):
    from steward_cockpit.conversation_history import read_history_document
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "eff"))
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# a steward cockpit\n", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n|---|---|---|---|\n", encoding="utf-8")
    steward_engine.receipt_baseline(str(eff))
    (eff / "Notes.md").write_text("# n", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Notes | `Notes.md` | 2026-10-07 | 1 |\n")
    steward_engine.publish_delivery_receipts(str(eff))                        # what notify_receipt runs, no engine
    turns = read_history_document(str(eff))["turns"]
    assert any("ready to read: [Notes](/api/steward/deliverable-file?pid=p1&dir=eff&path=Notes.md&render=1)" in t["text"]
               for t in turns)
    steward_engine.publish_delivery_receipts(str(eff))
    assert len(read_history_document(str(eff))["turns"]) == len(turns)       # announced once


def test_an_unregistered_pdf_is_never_taken_for_a_deck_and_route_decks_wait(tmp_path):
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "Talk.pptx").write_text("deck", encoding="utf-8")
    (eff / "Talk.pdf").write_text("slides", encoding="utf-8")
    t = lambda reg: dr.reading_target({"path": "Talk.pptx"}, pid="p", effort_rel="eff", effort_dir=eff, registered=reg)
    assert t({"talk.pptx"})["preparing"] is True                              # the PDF is not declared
    assert t({"talk.pptx", "talk.pdf"})["read"].endswith("path=Talk.pdf")
    r = dr.reading_target({"route": "/artifact/p?path=slides/Talk.pptx"}, pid="p", effort_rel="")
    assert r["read"] is None and r["preparing"] and r["download"]


def test_a_history_entry_carries_its_own_revisions_companion():
    state = {"slices": {"s1": {
        "candidate": {"Deck": "r2"}, "round": 1, "phase": "awaiting_review",
        "revisions": {"r1": {"product_id": "Deck", "path": "a.pptx", "hash": "h1", "visual_companion": {"path": "a.pdf"}},
                      "r2": {"product_id": "Deck", "path": "b.pptx", "hash": "h2"}},
        "presentations": [{"id": "p0", "round": 0, "members": [{"product_id": "Deck", "revision_id": "r1", "path": "a.pptx", "hash": "h1"}]},
                          {"id": "p1", "round": 1, "members": [{"product_id": "Deck", "revision_id": "r2", "path": "b.pptx", "hash": "h2"}]}]}}}
    item = sc.refinement_items("x", state)[0]
    assert item["history"][0]["visual_companion"] == {"path": "a.pdf"} and not item["history"][1]["visual_companion"]


def test_a_backticked_name_with_brackets_keeps_them(tmp_path, monkeypatch):
    import time as _t
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    eng.turn_started = _t.time() - 5
    (eff / "(accepted).ics").write_text("BEGIN:VCALENDAR", encoding="utf-8")
    eng._publish_delivery_receipt("t1", reply="Made `(accepted).ics` for you.", written=[])
    assert len(said) == 1 and "%28accepted%29.ics" in said[0][1]


# ---------- item 1, review round 4 ----------

def test_a_superseded_format_never_returns_and_a_managed_designation_counts():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    items = [
        {"what": "CURRENT: Guide", "path": "g/Guide.html", "step": "s1", "date": "2026-10-07"},
        {"what": "SUPERSEDED: Guide", "path": "g/Guide.pdf", "step": "s1", "date": "2026-10-06"},
    ]
    assert [it["path"] for it in sc.current_review_items({"steps": [step]}, items)] == ["g/Guide.html"]
    managed = [{"what": "Plan-PDF", "product_id": "Plan-PDF", "managed": True, "phase": "awaiting_review",
                "path": "deliverables/Plan-PDF/a.pdf", "step": "s1", "date": "2026-10-07"},
               {"what": "Notes v1", "path": "n/Notes-v1.pdf", "step": "s1", "date": "2026-10-07"}]
    assert [it["path"] for it in sc.current_review_items({"steps": [step]}, managed)] == ["deliverables/Plan-PDF/a.pdf"]


# ---------- item 3: preservation, safe checks, the hold, the review gate ----------

import json as _json
import subprocess as _sp
import sys as _sys
import time as _time
from pathlib import Path as _P

from steward_cockpit import code_jobs


def _git_repo(root):
    root.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _sp.run(["git", "-C", str(root), *args], check=True)
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _sp.run(["git", "-C", str(root), "add", "-A"], check=True)
    _sp.run(["git", "-C", str(root), "commit", "-q", "-m", "start"], check=True)
    return root


class _Coder:
    """A fake coder engine: writes with its 'file tool' (recorded in .files) and optionally behind its back."""
    def __init__(self, wt, tool_writes=None, stray=None, error=""):
        self.wt, self.tool_writes, self.stray, self.error = wt, tool_writes or {"a.txt": "two\n"}, stray or {}, error
        self.written_ok, self.on_turn_done, self.code_job, self.policy_override = [], None, None, None
        self.cli = "claude"

    def wake(self, fresh=False, seed=None):
        for name, text in self.tool_writes.items():
            _P(self.wt, name).write_text(text, encoding="utf-8")
            self.written_ok.append(str(_P(self.wt, name)))
        for name, text in self.stray.items():                     # e.g. a script it ran rewrote strip.json
            _P(self.wt, name).parent.mkdir(parents=True, exist_ok=True)
            _P(self.wt, name).write_text(text, encoding="utf-8")
        self.on_turn_done({"text": "done", "error": self.error})
        return True, "awake"

    def stop(self):
        pass


PASS_CHECK = [_sys.executable, "-c", "pass"]   # W1a (2026-10-08): every landing needs an explicit passing check


def _job(tmp_path, monkeypatch, coder_kw=None, check=PASS_CHECK, coder_family="claude", repo_name="repo"):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": (coder_family, None))
    repo, cdir = _git_repo(tmp_path / repo_name), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt to two.", check,
                          engine_factory=lambda wt: _Coder(wt, **(coder_kw or {})))
    assert out["ok"], out
    for _ in range(300):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return repo, j
        _time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(str(cdir)))


def test_a_reviewed_job_lands_only_its_own_files(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch)
    assert job["landed"] is True and job["files"] == ["a.txt"] and job["review"]["family"] == "chatgpt"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n" and not job["kept_worktree"]


def test_a_planted_defect_the_reviewer_objects_to_is_not_landed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW_VERDICT", "FAIL")
    repo, job = _job(tmp_path, monkeypatch)
    assert job["landed"] is False and "did not pass it" in job["land_note"] and "planted defect" in job["land_note"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert _P(job["kept_worktree"], "a.txt").read_text(encoding="utf-8") == "two\n"     # the work is kept


def test_a_reviewer_that_throws_lands_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW_MODE", "crash")
    repo, job = _job(tmp_path, monkeypatch)
    assert job["landed"] is False and "the review failed" in job["land_note"] and _P(job["kept_worktree"]).is_dir()


def test_a_review_by_the_authors_family_or_of_another_tree_lands_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "claude")
    repo, job = _job(tmp_path, monkeypatch, coder_family="claude")
    assert job["landed"] is False and "author's own family" in job["land_note"]
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "chatgpt")
    monkeypatch.setenv("FAKE_REVIEW_TREE", "0" * 40)
    repo, job = _job(tmp_path / "second", monkeypatch)
    assert job["landed"] is False and "not the candidate" in job["land_note"]


def test_a_long_check_in_a_path_with_a_space_runs_whole(tmp_path, monkeypatch):
    pad = "x" * 600
    check = ('python -c "import sys; s=open(' + "'a.txt'" + ').read(); pad=' + "'" + pad + "'" + '; '
             'sys.exit(0 if s.strip() == ' + "'two'" + ' and len(pad) == 600 else 3)"')
    assert len(check) > 600
    repo, job = _job(tmp_path, monkeypatch, check=check, repo_name="repo with space")
    assert job["check_ok"] is True and job["landed"] is True, job["land_note"]
    assert job["check"] == check                                     # stored whole, never cut


def test_an_unexpected_change_blocks_landing_and_everything_is_kept(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch, coder_kw={"tool_writes": {"report.pdf": "%PDF-1.4"},
                                                      "stray": {"notes/other.txt": "x"}})
    # W1 (2026-10-09): a steward runtime record (strip.json) no longer refuses a job - any OTHER extra path still does
    assert job["landed"] is False and job["status"] == "done"
    assert job["unexpected"] == ["notes/other.txt"] and job["files"] == ["report.pdf"]
    kept = _P(job["kept_worktree"])
    assert (kept / "report.pdf").read_text(encoding="utf-8") == "%PDF-1.4" and (kept / "notes" / "other.txt").is_file()
    assert not (repo / "report.pdf").exists() and not (repo / "notes").exists()


def test_foreman_config_never_lands_even_when_the_coder_writes_it(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch, coder_kw={"tool_writes": {"a.txt": "two\n", "foreman.config.json": "{}"}})
    assert job["landed"] is False and "foreman.config.json" in job["unexpected"]
    assert not (repo / "foreman.config.json").exists()


def test_an_exhausted_family_is_not_called_again(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    code_jobs.mark_exhausted("chatgpt")
    assert "chatgpt" in code_jobs.exhausted_families()
    import anchor_settings
    monkeypatch.setattr(anchor_settings, "get_launch_settings",
                        lambda: {"coding_family": "chatgpt", "default_cli": "claude", "review_family": "grok",
                                 "settings_revision": "r"})
    assert code_jobs.choose_coder() == ("claude", None)              # the other family runs
    fam, why = code_jobs.choose_coder("chatgpt")
    assert fam is None and "usage limit" in why


def test_model_preferences_are_byte_identical_after_a_job(tmp_path, monkeypatch):
    import anchor_settings
    paths = [anchor_settings.settings_path(), anchor_settings.mirror_path()]
    before = [p.read_bytes() if p.is_file() else None for p in paths]
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change a.txt.", PASS_CHECK, engine_factory=lambda wt: _Coder(wt), coder="chatgpt")
    assert out["ok"] and out["coder"] == "chatgpt"
    for _ in range(300):
        if (code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}).get("status") in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert [p.read_bytes() if p.is_file() else None for p in paths] == before


def test_stop_records_who_stopped_it_and_keeps_the_worktree_as_it_is(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))

    class Slow(_Coder):
        def wake(self, fresh=False, seed=None):
            _P(self.wt, "a.txt").write_text("half\n", encoding="utf-8")
            return True, "awake"
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Long.", PASS_CHECK, engine_factory=lambda wt: Slow(wt))
    r = code_jobs.stop(str(cdir), actor="John")
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert r["ok"] and job["stopped_by"] == "John" and "stopped by John" in job["land_note"]
    assert _P(job["kept_worktree"], "a.txt").read_text(encoding="utf-8") == "half\n"


# ---------- item 2, review round 3 ----------

def test_the_first_write_to_a_never_seen_effort_is_announced_not_swallowed(tmp_path, monkeypatch):
    from steward_cockpit.conversation_history import read_history_document
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "eff"))
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# a steward cockpit\n", encoding="utf-8")
    (eff / "Plan.md").write_text("# p", encoding="utf-8")
    assert dr.register(eff, "Plan", "`Plan.md`")["written"]                # no baseline existed before this write
    turns = read_history_document(str(eff))["turns"]
    assert any("ready to read: [Plan]" in t["text"] for t in turns), turns   # saved before register() returned


def test_office_routes_read_in_the_preview_and_download_apart():
    r = dr.reading_target({"route": "/artifact/p?path=reports/Guide.docx"}, pid="p", effort_rel="")
    assert r["read"].endswith("&view=1") and r["download"].endswith("&download=1")


def test_a_deck_whose_pdf_arrives_later_is_announced_again_as_ready():
    deck = {"path": "deliverables/D/a.pptx", "hash": "h", "date": "2026-10-07", "what": "Deck", "managed": True}
    assert steward_engine._deliv_key(deck) != steward_engine._deliv_key({**deck, "visual_companion": {"path": "a.pdf"}})


# ---------- items 1+2 re-review ----------

def test_managed_work_in_progress_is_not_a_designation():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    items = [{"what": "Guide v3", "path": "g/Guide-v3.pdf", "step": "s1", "date": "2026-10-07"},
             {"what": "Plan-PDF", "product_id": "Plan-PDF", "managed": True, "phase": "revising",
              "path": "deliverables/Plan-PDF/a.pdf", "step": "s1", "date": "2026-10-07"}]
    assert "g/Guide-v3.pdf" in [it["path"] for it in sc.current_review_items({"steps": [step]}, items)]


def test_a_route_deck_reads_through_its_registered_pdf_route():
    reg = {dr._canonical_route("/artifact/p?path=slides/Talk.pdf").lower()}
    r = dr.reading_target({"route": "/artifact/p?path=slides/Talk.pptx"}, pid="p", effort_rel="", registered=reg)
    assert r["read"] is None and r["preparing"]   # final review: an unverifiable routed PDF is not the deck's copy (see the freshness test)


# ---------- items 5 and 6: the two runtime fixes; status says who, what next, and when ----------

def _campaign(tmp_path, steps=84):
    import json as _j
    c = tmp_path / "camp"
    (c / ".ecgberht").mkdir(parents=True)
    (c / "ECGBERHT.md").write_text("# Camp\n\n## North star\nShip it.\n", encoding="utf-8")
    proj = [{"id": "s%d" % i, "name": "Step %d" % i, "status": "planned"} for i in range(steps)]
    proj[0].update(status="active", navigation={"current": True})
    (c / "roadmap.json").write_text(_j.dumps({"roadmap_events": [], "roadmap_projection": proj}), encoding="utf-8")
    return c


def test_status_names_the_coder_its_phase_elapsed_and_a_clock_time_never_a_step_count(tmp_path):
    import json as _j, re as _re, time as _t
    c = _campaign(tmp_path)
    started = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - 600))
    (c / ".ecgberht" / "code-jobs.json").write_text(_j.dumps({"j1": {
        "id": "j1", "status": "running", "started": started, "brief": "Fix the tile", "worker": "coder",
        "coder_family": "chatgpt", "steward_dir": str(c)}}), encoding="utf-8")
    st = sc.compose_status(str(c), {})
    assert "coder" in st["who"] and "Fix the tile" in st["who"] and "Foreman" not in st["who"]
    assert _re.search(r"\b\d{2}:\d{2}\b", st["finish"]) and "Unavailable" not in st["finish"]
    facts = {f["label"]: f["value"] for f in st["compact"]["facts"]}
    assert "84" not in facts["Doing"] and "84" not in facts["Status"] and "min since" in facts["Status"]
    assert facts["Tests"] == "tests not run yet"


def test_a_job_kind_with_history_finishes_at_its_median(tmp_path):
    import json as _j, time as _t
    c = _campaign(tmp_path, steps=3)
    fmt = lambda t: _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(t))
    now = _t.time()
    jobs = {"old%d" % k: {"id": "old%d" % k, "status": "done", "worker": "coder", "steward_dir": str(c),
                          "started": fmt(now - 86400 - m * 60), "finished": fmt(now - 86400)} for k, m in enumerate((20, 30, 40))}
    jobs["j1"] = {"id": "j1", "status": "running", "started": fmt(now - 300), "brief": "x", "worker": "coder", "steward_dir": str(c)}
    (c / ".ecgberht" / "code-jobs.json").write_text(_j.dumps(jobs), encoding="utf-8")
    assert sc.typical_duration_s(str(c), "code_job", "coder") == 1800
    st = sc.compose_status(str(c), {})
    assert "estimate: a typical code job here takes 30 min" in st["finish"]


def test_an_idle_steward_and_a_long_turn_both_say_something_true(tmp_path):
    import time as _t
    c = _campaign(tmp_path, steps=3)
    idle = sc.compose_status(str(c), {})
    assert idle["who"].startswith("Nobody is working") and idle["next3"]
    busy = sc.compose_status(str(c), {"busy": True, "turn_started": _t.time() - 120, "activity": "Rewriting the calendar",
                                      "turn_origin": "human"})
    assert busy["who"] == "The steward is doing this — Rewriting the calendar"
    assert "provisional" in busy["finish"] or "estimate" in busy["finish"]


def test_a_restart_pause_older_than_his_message_is_history(tmp_path):
    import json as _j, time as _t
    c = _campaign(tmp_path, steps=3)
    stamp = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(_t.time() - 3600)) + "+00:00"
    (c / "strip.json").write_text(_j.dumps({"active_effort": "Teaching calendar - paused for restart", "as_of": stamp,
                                            "next_recommended": "Resume only after John confirms the restart is done"}),
                                  encoding="utf-8")
    assert sc.restart_pause_is_stale(str(c), {"human_accepted_at": _t.time()})
    assert not sc.restart_pause_is_stale(str(c), {"human_accepted_at": _t.time() - 7200})   # his message came first
    assert not sc.restart_pause_is_stale(str(c), {})                                         # boot clears nothing


def test_the_silent_path_says_received_at_durable_accept(tmp_path, monkeypatch):
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    said = []
    monkeypatch.setattr(eng, "_emit", lambda ev: said.append(ev))
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    monkeypatch.setattr(eng, "_send_locked", lambda text, origin="human", **kw: True)
    eng.busy = False
    assert eng.say("please fix the calendar")["ok"]
    assert {"t": "sys", "text": "Received."} in said
    said.clear()
    eng.busy = True
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    eng.say("and the quiz")
    assert {"t": "sys", "text": "Received."} not in said      # the queued path has its own receipt


# ---------- item 3, review round 1 ----------

def test_a_reviewer_of_any_family_that_actually_wrote_is_refused(tmp_path, monkeypatch):
    class FellBack(_Coder):
        def wake(self, fresh=False, seed=None):
            self.families_used = {"claude", "grok"}            # the engine fell back from Claude to Grok mid-job
            return super().wake(fresh, seed)
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "grok")
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: FellBack(wt))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir))[out["job"]]
        if job["status"] in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert job["authors"] == ["claude", "grok"] and job["landed"] is False and "author's own family (grok)" in job["land_note"]


def test_a_rename_lands_the_deletion_too(tmp_path, monkeypatch):
    class Renamer(_Coder):
        def wake(self, fresh=False, seed=None):
            _P(self.wt, "new.txt").write_text("one\n", encoding="utf-8")
            _P(self.wt, "a.txt").unlink()
            self.written_ok += [str(_P(self.wt, "new.txt")), str(_P(self.wt, "a.txt"))]   # a completed file_change
            self.on_turn_done({"text": "renamed", "error": ""})
            return True, "awake"
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "rename", PASS_CHECK, engine_factory=lambda wt: Renamer(wt))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir))[out["job"]]
        if job["status"] in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert job["landed"] is True, job["land_note"]
    assert (repo / "new.txt").is_file() and not (repo / "a.txt").exists()


def test_work_a_check_leaves_behind_keeps_the_worktree(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch, check='python -c "open(' + "'report.txt','w'" + ').write(' + "'x'" + ')"')
    # (ChatGPT item 3 round 2) a change the check made is unexpected: it blocks the landing, everything is kept
    assert job["landed"] is False and "report.txt" in job["land_note"] and "report.txt" in job["unexpected"]
    assert (_P(job["kept_worktree"]) / "report.txt").is_file()


def test_a_stop_during_review_means_no_landing(tmp_path, monkeypatch):
    real = code_jobs.run_review

    def review_then_stopped(job, tree, head, delta_from=""):
        code_jobs._transition(job["steward_dir"], job["id"], ("finishing",), finishing_at=0)
        assert code_jobs.stop(job["steward_dir"], actor="John")["ok"]  # explicit Stop; age cannot release a writer
        return real(job, tree, head, delta_from)
    monkeypatch.setattr(code_jobs, "run_review", review_then_stopped)
    repo, job = _job(tmp_path, monkeypatch)
    _time.sleep(1.0)                                          # the finishing thread has had its chance to land
    job = code_jobs.read_jobs(job["steward_dir"])[job["id"]]
    assert job.get("landed") is not True and job["stop_requested_by"] == "John"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n" and _P(job["kept_worktree"]).is_dir()


def test_a_failed_edit_never_enters_the_manifest():
    eng = steward_engine.Engine.__new__(steward_engine.Engine)
    eng.code_job, eng.proc, eng._submitted = {"repo": "r"}, object(), None
    eng.general, eng.fake, eng.busy, eng.in_tick = True, True, False, False
    eng.dir, eng.files, eng.cli = "C:/wt", [], "claude"
    eng.__dict__["_lock"] = __import__("threading").Lock()
    eng._emit = lambda ev: None
    eng._guard_turn = lambda block: False
    eng.last_output = 0
    edit = lambda i, path: {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": i, "name": "Edit", "input": {"file_path": path}}]}}
    result = lambda i, err: {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "is_error": err}]}}
    for ev in (edit("t1", "C:/wt/bad.py"), result("t1", True), edit("t2", "C:/wt/good.py"), result("t2", False)):
        try:
            eng._handle(ev, eng.proc)
        except Exception:
            pass
    assert eng.__dict__.get("written_ok") == ["C:/wt/good.py"]


def test_the_hold_refuses_a_relative_foreman_command_and_any_held_lane(monkeypatch, tmp_path):
    import job_runner
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    fdir = tmp_path / "trio" / "foreman"
    (fdir / "bin").mkdir(parents=True)
    for lane, cmd, cwd in (("general", ["node", "bin/run-live.mjs", "x"], fdir), ("build", ["node", "x.mjs"], tmp_path)):
        try:
            job_runner.launch(lane, cwd=str(cwd), command=cmd)
            raise AssertionError("not refused: %s" % lane)
        except ValueError as e:
            assert "foreman-code-job-only" in str(e)


def test_foreman_config_never_lands_in_any_case_or_folder():
    for p in ("FOREMAN.CONFIG.JSON", "sub/dir/foreman.config.json", "Foreman.Config.Json"):
        assert code_jobs.never_lands(p)
    assert not code_jobs.never_lands("foreman.config.json.bak")


def test_a_reviewer_out_of_quota_is_remembered_and_a_contradictory_pass_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW_MODE", "crash")
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "gemini")
    monkeypatch.setenv("FAKE_REVIEW_ERROR", "usage limit reached for this account")
    repo, job = _job(tmp_path, monkeypatch)
    assert job["landed"] is False and "gemini" in code_jobs.exhausted_families()
    monkeypatch.setenv("FAKE_REVIEW_MODE", "pass-with-major")
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "chatgpt")
    repo, job = _job(tmp_path / "two", monkeypatch)
    assert job["landed"] is False and "says PASS but lists a MAJOR" in job["land_note"]


def test_documents_enter_the_gate_too(tmp_path, monkeypatch):
    # W2 (2026-10-08): every job is reviewed by another family, documents included - a reviewer that fails keeps them
    monkeypatch.setenv("FAKE_REVIEW_MODE", "crash")
    repo, job = _job(tmp_path, monkeypatch, coder_kw={"tool_writes": {"notes.md": "# notes"}})
    assert job["landed"] is False and "the review failed" in job["land_note"] and not (repo / "notes.md").is_file()


def _guard_engine(tmp_path, monkeypatch, directory, code_job=None):
    eng = steward_engine.Engine(str(directory), fake=True)
    eng.fake, eng.busy, eng.code_job = False, True, code_job
    ended = []
    monkeypatch.setattr(eng, "_interrupt_turn_locked", lambda reason: ended.append(reason) or {"ok": True})
    monkeypatch.setattr(eng, "_wake_locked", lambda *a, **k: (True, ""))
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    return eng, ended


def test_a_coder_writes_only_inside_its_worktree(tmp_path, monkeypatch):
    repo, wt = tmp_path / "repo", tmp_path / "wt"
    repo.mkdir(); wt.mkdir()
    eng, ended = _guard_engine(tmp_path, monkeypatch, wt, {"repo": str(repo), "id": "j", "cdir": "c"})
    assert eng._guard_turn({"name": "Write", "input": {"file_path": str(wt / "ok.py")}}) is False
    assert eng._guard_turn({"name": "Edit", "input": {"file_path": str(repo / "live.py")}}) is True
    assert ended and "its own worktree" in ended[0]
    assert eng._guard_turn({"name": "Bash", "input": {"command": "echo x > %s/live.py" % str(repo).replace(chr(92), "/")}}) is True


def test_a_steward_never_edits_the_served_trees_code(tmp_path, monkeypatch):
    import os as _os
    served = _P(steward_engine.__file__).resolve().parents[1]
    eng, ended = _guard_engine(tmp_path, monkeypatch, tmp_path)
    assert eng._guard_turn({"name": "Edit", "input": {"file_path": str(served / "job_runner.py")}}) is True
    assert "code job" in ended[0]
    eng2, ended2 = _guard_engine(tmp_path, monkeypatch, tmp_path)
    assert eng2._guard_turn({"name": "Write", "input": {"file_path": str(served / "planning" / "x" / "NOTES.md")}}) is False


# ══════════ HARDENING on a disposable Anchor (Grok's 13, the integrated ones) ══════════
# A real server on a free port with a temp data dir and a campaign folder whose name has a space ("foundation
# campaign"), driven in a real browser. Never :8777, never a live campaign.

def _reg_rows(server, rows):
    _add_rows(server.campaign, rows)
    _refresh_page = None


def _open_next(surface):
    tile = surface.locator('[data-delivmount] .blk.next')
    if 'folded' in (tile.get_attribute('class') or ''):
        tile.locator('> .who').click()
    return tile


def test_hardening_1_jitter_a_skill_row_holds_still_and_its_icon_loads(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    (server.campaign / "ch2.pdf").write_text("%PDF-1.4", encoding="utf-8")
    icons = []
    page.on("response", lambda r: icons.append((r.url, r.status)) if "/vendor/brand/" in r.url else None)
    _add_rows(server.campaign, ["| FOR REVIEW: Chekhov Chapter 2 read | `ch2.pdf` | 2026-10-07 | foundation |\n"])
    _refresh(page)
    tile = _open_next(surface)
    row = tile.locator('.navact a', has_text='Chekhov Chapter 2').first
    expect(row).to_be_visible()
    row.evaluate("a => { a.__mark = 'kept'; a.focus(); }")
    xs = []
    for _ in range(20):                                       # 20 s here; the starred 2-minute check is on his screen
        xs.append(row.evaluate("a => Math.round(a.getBoundingClientRect().x)"))
        page.wait_for_timeout(1000)
    assert len(set(xs)) == 1, xs
    assert surface.locator('body').evaluate("() => document.activeElement && document.activeElement.__mark") == "kept"
    assert all(status == 200 for url, status in icons if "chekhov" in url.lower()), icons
    with page.context.expect_event("request", predicate=lambda r: "deliverable-file" in r.url and "ch2.pdf" in r.url):
        _refresh(page)                                         # a click as a poll lands still opens the item
        row.click()


def test_hardening_2_fraction_three_reviews_one_pair_no_history(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    for folder in ("a", "b", "c", "d"):
        (server.campaign / folder).mkdir()
    for name in ("a/Alpha.md", "b/Beta.md", "c/Gamma.md", "d/Deck.pptx", "d/Deck.pdf", "a/Old.md"):
        (server.campaign / name).write_text("# x", encoding="utf-8")
    _add_rows(server.campaign, [
        "| FOR REVIEW: Alpha | `a/Alpha.md` | 2026-10-07 | foundation |\n",
        "| FOR REVIEW: Beta | `b/Beta.md` | 2026-10-07 | foundation |\n",
        "| FOR REVIEW: Gamma | `c/Gamma.md` | 2026-10-07 | foundation |\n",
        "| FOR REVIEW: Deck (PDF) | `d/Deck.pdf` | 2026-10-07 | foundation |\n",
        "| FOR REVIEW: Deck (PowerPoint) | `d/Deck.pptx` | 2026-10-07 | foundation |\n",
        "| SUPERSEDED: Alpha first draft | `a/Old.md` | 2026-10-01 | foundation |\n"])
    for attempt in range(2):                                   # and again after a refresh: the same rows
        _refresh(page)
        tile = _open_next(surface)
        labels = tile.locator('.navact-open').all_inner_texts()
        joined = " | ".join(labels)
        assert sum(1 for w in ("Alpha", "Beta", "Gamma") if w in joined) == 3, joined
        assert joined.count("Deck") == 1 and "first draft" not in joined, joined


def test_hardening_3_and_4_the_dialogue_link_renders_and_a_deck_without_pdf_is_preparing(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    import deliverables_register as _dr
    (server.campaign / "x (draft)").mkdir()
    (server.campaign / "x (draft)" / "Calendar notes.md").write_text(
        "# Notes\n\n| Week | Topic |\n|---|---|\n| 1 | Intro |\n", encoding="utf-8")
    (server.campaign / "Talk.pptx").write_text("deck", encoding="utf-8")
    # a managed campaign refuses the legacy registrar (correctly); the steward's own edit of the register is the
    # writer here - the baseline first, the rows, then the writers' notification
    _dr.receipt_baseline(server.campaign)
    _add_rows(server.campaign, ["| Calendar notes | `x (draft)/Calendar notes.md` | 2026-10-07 | foundation |\n",
                                "| Talk | `Talk.pptx` | 2026-10-07 | foundation |\n"])
    _dr.notify_receipt(server.campaign)
    link = surface.locator('.scroll a', has_text='Calendar notes').last
    expect(link).to_be_visible(timeout=15000)                  # the engine put it in the dialogue - no model words
    href = link.get_attribute('href')
    assert "render=1" in href
    reader = page.context.new_page()
    reader.goto(server.origin + href if href.startswith("/") else href)
    expect(reader.locator("table td").first).to_have_text("1")
    reader.close()
    expect(surface.locator('.scroll', has_text='preparing a reading copy: Talk')).to_be_visible(timeout=15000)
    _refresh(page)
    deliv = surface.locator('[data-delivmount] .blk.deliv')
    expect(deliv.locator('.preparing', has_text='Talk')).to_have_count(1)   # the tile says preparing (no Open link)
    expect(deliv.locator('a', has_text='Talk')).to_have_count(0)


def test_hardening_11_a_restart_starts_nothing_by_itself(campaign_server):
    import json as _j
    import anchor_gui, job_runner, threading as _th
    from steward_cockpit import steward_routes as _sr
    camp = campaign_server.campaign
    roadmap = _j.loads((camp / "roadmap.json").read_text(encoding="utf-8"))
    before_files = sorted(p.name for p in camp.rglob("*") if p.is_file())
    pending = [a for a in sc.read_deliverables(str(camp))["acts"] if a["act"] == "Review"]
    engines_before = set(_sr.ENGINES)
    server = anchor_gui.make_server("127.0.0.1", 0)              # a second boot of the same disposable data
    worker = _th.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        __import__("time").sleep(3)
        assert not [r for r in job_runner.list_records() if r.get("status") == job_runner.STATUS_RUNNING]
        assert not (camp / ".ecgberht" / "code-jobs.json").exists()
        assert set(_sr.ENGINES) == engines_before, "the boot started no steward of its own"
        assert [a for a in sc.read_deliverables(str(camp))["acts"] if a["act"] == "Review"] == pending
        assert _j.loads((camp / "roadmap.json").read_text(encoding="utf-8")) == roadmap
        assert sorted(p.name for p in camp.rglob("*") if p.is_file()) == before_files
    finally:
        server.shutdown()
        server.server_close()


def test_hardening_12_the_served_status_says_who_and_when_never_unavailable(cockpit):
    import json as _j
    from urllib.parse import quote
    page, server = cockpit
    open_surface(page)
    url = "%s/api/steward/status?pid=%s&dir=%s" % (server.origin, quote(server.project_id, safe=""),
                                                    quote(server.campaign.name, safe=""))
    st = page.evaluate("u => fetch(u).then(r => r.json())", url)
    assert st.get("who") and "Unavailable" not in st.get("eta", "") and "no current estimate" not in st.get("eta", "")
    facts = {f["label"]: f["value"] for f in (st.get("compact") or {}).get("facts") or []}
    assert "/" not in facts.get("Status", "")                  # no "n/m done" step count on the current-task line


def test_hardening_13_the_patch_sends_nothing():
    import subprocess as _s
    diff = _s.run(["git", "-C", str(_P(__file__).resolve().parents[1]), "diff", "a3468d6", "94c7b04", "--",   # that night's patch, as installed 2026-10-08 (later nights add loopback-only probes)
                    "*.py", "*.mjs", "*.js",
                   ":(exclude)tests/*"],
                  capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    added = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    for word in ("smtplib", "sendmail", "send_mail", "gmail", "outlook", "requests.post", "urlopen(", "fetch('https", 'fetch("https'):
        assert word not in added, word


# ---------- item 3 round 2 + items 4-6 round 1 ----------

def test_an_ignored_output_a_check_makes_keeps_the_worktree(tmp_path, monkeypatch):
    def with_gitignore(root):
        r = _git_repo_orig(root)
        (r / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
        _sp.run(["git", "-C", str(r), "add", ".gitignore"], check=True)
        _sp.run(["git", "-C", str(r), "commit", "-q", "-m", "ignore pdfs"], check=True)
        return r
    monkeypatch.setitem(globals(), "_git_repo_orig", _git_repo)
    monkeypatch.setitem(globals(), "_git_repo", with_gitignore)
    repo, job = _job(tmp_path, monkeypatch, check='python -c "open(' + "'report.pdf','w'" + ').write(' + "'x'" + ')"')
    # round 4 (2026-10-12, MBA job 66e90d): an ignored file nobody declared is scratch - it never refuses the
    # deliverable, and it is never lost: it stays in the kept worktree, named
    assert job["landed"] is True and job["scratch_kept"] == ["report.pdf"], job["land_note"]
    assert (_P(job["kept_worktree"]) / "report.pdf").is_file()


def test_a_write_into_the_served_tree_during_the_job_blocks_landing(tmp_path, monkeypatch):
    class Sneaky(_Coder):
        def wake(self, fresh=False, seed=None):
            repo = _P(self.code_job["repo"])
            (repo / "live.py").write_text("changed behind the gate\n", encoding="utf-8")   # e.g. a shell write
            return super().wake(fresh, seed)
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: Sneaky(wt))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir))[out["job"]]
        if job["status"] in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert job["landed"] is False and "live.py" in job["land_note"] and job["served_tree_changed"] == ["live.py"]


def test_a_kept_pdf_is_copied_and_linked_in_the_dialogue(tmp_path, monkeypatch):
    from steward_cockpit.conversation_history import read_history_document
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "steward"))
    job = {"id": "j9", "kept_worktree": str(tmp_path / "wt"), "files": ["out/report.pdf", "app.py"]}
    (tmp_path / "wt" / "out").mkdir(parents=True)
    (tmp_path / "wt" / "out" / "report.pdf").write_text("%PDF", encoding="utf-8")
    (tmp_path / "wt" / "app.py").write_text("x", encoding="utf-8")
    cdir = tmp_path / "steward"
    cdir.mkdir()
    (cdir / "ECGBERHT.md").write_text("# a steward cockpit\n", encoding="utf-8")
    assert code_jobs.announce_kept(str(cdir), job) == ["report.pdf"]
    # registered through the existing registrar - so Deliverables, Next steps and the receipt all carry it
    assert "code-job-outputs/j9/out/report.pdf" in (cdir / "DELIVERABLES.md").read_text(encoding="utf-8")
    turns = read_history_document(str(cdir))["turns"]
    assert any("report.pdf" in t["text"] and "/api/steward/deliverable-file?" in t["text"] for t in turns), turns
    assert (cdir / "code-job-outputs" / "j9" / "out" / "report.pdf").is_file()


def test_html_content_is_a_document_but_an_app_page_is_not():
    assert code_jobs.is_document("reports/week3.html") and not code_jobs.is_document("static/app.html")
    assert not code_jobs.is_document("AGENTS.md") and not code_jobs.is_document("requirements.txt")


def test_status_never_treats_a_placeholder_as_a_forecast_or_a_stopped_job_as_running():
    assert sc.real_forecast("~35m to run end (pace estimate)") and not sc.real_forecast("ETA Unavailable")
    assert not sc.real_forecast("estimating (no completed wave yet)")
    job = {"id": "j", "title": "Fix", "status": "running", "native": {"stopped": True}, "started_epoch": None}
    who, phase, _s, _t, finish = sc.who_is_working("x", {}, [job], None)
    assert phase == "stopped" and "has stopped" in who and "Unavailable" not in finish


def test_skill_history_matches_by_the_script_it_ran():
    assert sc.skill_identity({"argv": ["node", "C:/dev/trio/gandalf/bin/run.mjs"]}) == "gandalf"
    assert sc.skill_identity({"argv": ["node", "C:/x/einstein/bin/run.mjs"], "label": "Update guide"}) == "einstein"


def test_the_code_rule_rides_in_every_mode(tmp_path):
    import json as _jj
    d = tmp_path / "effort"
    d.mkdir()
    (d / "roadmap.json").write_text(_jj.dumps({"roadmap_projection": [{"id": "a", "status": "active"}]}), encoding="utf-8")
    e = steward_engine.Engine(str(d), fake=True)
    assert e.effort_on() and "for a major coding effort wait for John's approval" in e._contract()
    assert "Do not invent a validator" in e._contract()


def test_a_stale_restart_wait_is_hidden_after_his_message(tmp_path):
    import json as _j, time as _t
    c = _campaign(tmp_path, steps=3)
    stamp = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(_t.time() - 3600)) + "+00:00"
    (c / "strip.json").write_text(_j.dumps({"active_effort": "Calendar - paused for restart", "as_of": stamp,
                                            "human_wait": "paused for restart - confirm the restart"}), encoding="utf-8")
    st = sc.compose_status(str(c), {"human_accepted_at": _t.time()})
    assert "restart" not in (st["plan"]["waiting_on_you"] or "")
    assert "restart" not in str(st["effort_line"].get("text") or "")


# ---------- item 3 round 3 + items 4-6 round 2 ----------

def test_a_file_already_dirty_in_the_repo_and_changed_again_is_seen(tmp_path, monkeypatch):
    class Sneaky(_Coder):
        def wake(self, fresh=False, seed=None):
            (_P(self.code_job["repo"]) / "app.py").write_text("changed again by the job\n", encoding="utf-8")
            return super().wake(fresh, seed)
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    (repo / "app.py").write_text("v1\n", encoding="utf-8")
    _sp.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    _sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "app"], check=True)
    (repo / "app.py").write_text("his own unstaged edit\n", encoding="utf-8")   # " M app.py" - a leading space
    assert code_jobs.porcelain_paths(str(repo)) == ["app.py"]
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: Sneaky(wt, tool_writes={"b.txt": "new\n"}))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir))[out["job"]]
        if job["status"] in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert job["landed"] is False and job["served_tree_changed"] == ["app.py"]


def test_a_source_write_is_reported_even_when_the_candidate_is_unchanged(tmp_path, monkeypatch):
    class OnlySource(_Coder):
        def wake(self, fresh=False, seed=None):
            (_P(self.code_job["repo"]) / "live.py").write_text("x\n", encoding="utf-8")
            self.on_turn_done({"text": "done", "error": ""})
            return True, "awake"
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: OnlySource(wt))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir))[out["job"]]
        if job["status"] in ("done", "failed"):
            break
        _time.sleep(0.1)
    assert job["served_tree_changed"] == ["live.py"] and "live.py" in job["land_note"]


def test_a_stop_never_overwrites_a_placement():
    import tempfile
    d = tempfile.mkdtemp()
    code_jobs._write_job(d, {"id": "j", "status": "finishing", "finishing_at": 0, "repo": d, "worktree": d,
                             "branch": "b", "started": "2026-10-07 00:00:00", "placed": True})
    r = code_jobs.stop(d, actor="John")
    assert r["ok"] is False and "already landed" in r["error"]


def test_a_failed_check_survives_an_unavailable_one_beside_it(tmp_path):
    who, _p, _s, tests, _f = sc.who_is_working(str(tmp_path), {"busy": True, "turn_started": 1.0, "activity": "x"},
                                               [], None, evidence_tests="Unavailable - checkA (missing); Failed - checkB (exit 1)")
    assert tests == "Failed - checkB (exit 1)"


def test_a_log_only_skill_never_takes_the_steps_start(tmp_path):
    look = {"skill": "Gandalf", "label": "Gandalf · reading", "final": False, "tests": ""}
    _w, _p, started, _t, finish = sc.who_is_working(str(tmp_path), {}, [], look, slice_started=1.0)
    assert started is None and "Unavailable" not in finish


def test_his_message_clears_a_stale_restart_attention_and_nothing_else(tmp_path, monkeypatch):
    from steward_cockpit import steward_campaign as camp
    camp.write_attention(str(tmp_path), "needs_you", "paused for restart - waiting for John")
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    eng._mark_human_accepted()
    assert camp.read_map(str(tmp_path))["attention"]["state"] == "quiet"
    camp.write_attention(str(tmp_path), "needs_you", "choose the quiz date")
    eng._mark_human_accepted()
    assert camp.read_map(str(tmp_path))["attention"]["state"] == "needs_you"   # an unrelated wait stays


def test_next_actions_come_only_from_text_bound_to_the_current_step(tmp_path):
    import json as _j
    c = _campaign(tmp_path, steps=3)
    (c / "strip.json").write_text(_j.dumps({"next_recommended": "Do the old thing; then another",
                                            "current_step_id": "s9"}), encoding="utf-8")      # bound to another step
    st = sc.compose_status(str(c), {})
    assert st["next3"] == ["Finish the current work, then wait for you."]


# ---------- items 4-6 round 3 ----------

def test_another_skills_log_never_speaks_for_this_job(tmp_path):
    import json as _j
    (tmp_path / ".ecgberht").mkdir()
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(_j.dumps({"k": {
        "status": "running", "started": "2026-10-07 10:00:00", "label": "ideas",
        "argv": ["node", "C:/dev/trio/jumper/bin/run.mjs"]}}), encoding="utf-8")
    look = {"skill": "Gandalf review", "tests": "passed", "status": "synthesis", "final": False}
    who, phase, _s, tests, _f = sc.who_is_working(str(tmp_path), {}, [], look)
    assert "jumper" in who and phase == "running" and tests == "tests not run yet"
    assert sc.canonical_skill("Gandalf review") == "gandalf"


def test_unbound_next_actions_need_both_stamps_after_the_step_began(tmp_path):
    import json as _j
    c = _campaign(tmp_path, steps=3)
    (c / "strip.json").write_text(_j.dumps({"next_recommended": "Publish old draft"}), encoding="utf-8")   # no stamp
    assert sc.compose_status(str(c), {})["next3"] == ["Finish the current work, then wait for you."]


# ---------- item 3 round 4 ----------

def test_restoring_his_uncommitted_edit_is_seen(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    (repo / "app.py").write_text("v1\n", encoding="utf-8")
    _sp.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    _sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "app"], check=True)
    (repo / "app.py").write_text("his uncommitted edit\n", encoding="utf-8")
    job = {"repo": str(repo), "repo_dirt": code_jobs.dirty_snapshot(str(repo))}
    _sp.run(["git", "-C", str(repo), "checkout", "--", "app.py"], check=True)       # a shell restored it
    assert code_jobs._served_tree_changes(job) == ["app.py"]


def test_a_stop_audits_the_source_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))

    class Slow(_Coder):
        def wake(self, fresh=False, seed=None):
            (_P(self.code_job["repo"]) / "live.py").write_text("x\n", encoding="utf-8")
            return True, "awake"
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: Slow(wt))
    r = code_jobs.stop(str(cdir), actor="John")
    assert r["served_tree_changed"] == ["live.py"]
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["served_tree_changed"] == ["live.py"]


# ---------- item 3 round 5 ----------

def test_a_stale_finishing_release_audits_the_source_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    repo, cdir = _git_repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    code_jobs._write_job(str(cdir), {"id": "j", "status": "finishing", "finishing_at": 0, "repo": str(repo),
                                     "worktree": str(tmp_path / "wt"), "branch": "b", "started": "2026-10-07 00:00:00",
                                     "repo_dirt": code_jobs.dirty_snapshot(str(repo))})
    (repo / "live.py").write_text("x\n", encoding="utf-8")
    r = code_jobs.stop(str(cdir), actor="John")
    assert r["ok"] and r["served_tree_changed"] == ["live.py"]
    assert code_jobs.read_jobs(str(cdir))["j"]["served_tree_changed"] == ["live.py"]


def test_ignored_only_outputs_are_the_kept_inventory(tmp_path, monkeypatch):
    def with_gitignore(root):
        r = _git_repo_orig(root)
        (r / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
        _sp.run(["git", "-C", str(r), "add", ".gitignore"], check=True)
        _sp.run(["git", "-C", str(r), "commit", "-q", "-m", "ignore"], check=True)
        return r
    monkeypatch.setitem(globals(), "_git_repo_orig", _git_repo)
    monkeypatch.setitem(globals(), "_git_repo", with_gitignore)
    repo, job = _job(tmp_path, monkeypatch, coder_kw={"tool_writes": {"report.pdf": "%PDF"}})
    assert job["landed"] is False and job["kept_worktree"] and any("report.pdf" in u for u in job["unexpected"])


# ---------- items 4-6 round 4 ----------

def test_a_newer_restart_hold_is_never_hidden(tmp_path):
    import time as _t
    from steward_cockpit import steward_campaign as camp
    camp.write_attention(str(tmp_path), "needs_you", "paused for restart")
    att = camp.read_map(str(tmp_path))["attention"]
    assert sc.restart_attention_is_stale(str(tmp_path), att, {"human_accepted_at": _t.time() + 5})
    assert not sc.restart_attention_is_stale(str(tmp_path), att, {"human_accepted_at": _t.time() - 3600})


def test_a_log_only_runs_start_is_its_first_table(tmp_path):
    import time as _t
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "_foreman-status.log"
    hm = _t.strftime("%H:%M", _t.localtime(_t.time() - 1800))
    log.write_text("[%s] Foreman build · x\nSummary  s\n" % hm, encoding="utf-8")
    began = sc.look_started(str(tmp_path), {"source": "logs/_foreman-status.log"})
    assert began and abs((_t.time() - 1800) - began) < 120


def test_a_bound_but_empty_strip_uses_the_steps_own_actions(tmp_path):
    import json as _j
    c = _campaign(tmp_path, steps=3)
    rm = _j.loads((c / "roadmap.json").read_text(encoding="utf-8"))
    rm["roadmap_projection"][0]["next_actions"] = ["Review draft", "Revise figures", "Send to Joe", "Archive"]
    (c / "roadmap.json").write_text(_j.dumps(rm), encoding="utf-8")
    (c / "strip.json").write_text(_j.dumps({"current_step_id": "s0"}), encoding="utf-8")
    assert sc.compose_status(str(c), {})["next3"] == ["Review draft", "Revise figures", "Send to Joe"]


def test_an_ordinary_project_folder_gets_no_receipt_files(tmp_path):
    # a Gandalf run registering its report in a plain project must not leave receipt state or a conversation there
    assert dr.register(tmp_path, "Gandalf read", "`gandalf/report.md`")["written"]
    assert not (tmp_path / ".ecgberht").exists()


# ---------- item 3 round 6 + items 4-6 round 5 ----------

def test_foremans_real_header_gives_the_runs_start_and_the_etas_time(tmp_path):
    import time as _t
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "_foreman-status.log"
    t0 = _t.localtime(_t.time() - 1800)
    hm, hms = _t.strftime("%H:%M", t0), _t.strftime("%H:%M:%S", t0)
    log.write_text("[%s] [%s] Foreman build · x\nSummary  s\nETA  ~35m to run end\n" % (hms, hm), encoding="utf-8")
    began = sc.look_started(str(tmp_path), {"source": "logs/_foreman-status.log"})
    assert began and abs((_t.time() - 1800) - began) < 120
    assert sc._last_table_time(log.read_text(encoding="utf-8")) == hm


def test_two_runs_of_one_skill_never_share_a_log(tmp_path):
    import json as _j, time as _t
    (tmp_path / ".ecgberht").mkdir()
    st = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - 60))
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(_j.dumps({
        k: {"status": "running", "started": st, "label": k, "argv": ["node", "C:/dev/trio/gandalf/bin/run.mjs"]}
        for k in ("A", "B")}), encoding="utf-8")
    (tmp_path / "g.log").write_text("x", encoding="utf-8")
    look = {"skill": "Gandalf review", "tests": "passed", "status": "synthesis", "source": "g.log", "final": False}
    _w, phase, _s, tests, _f = sc.who_is_working(str(tmp_path), {}, [], look)
    assert phase == "running" and tests == "tests not run yet"


# ---------- final whole-patch review ----------

def test_a_stewards_direct_write_to_served_code_is_reported(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "served")
    monkeypatch.setattr(steward_engine, "_SERVED", repo)
    before = steward_engine._served_code_snapshot()
    (repo / "job_runner.py").write_text("changed directly\n", encoding="utf-8")
    assert steward_engine._served_code_changes(before) == ["job_runner.py"]
    assert steward_engine._served_code_changes(steward_engine._served_code_snapshot()) == []


def test_a_receipt_saved_by_another_process_is_shown_live(tmp_path, monkeypatch):
    from steward_cockpit.conversation_history import append_turns
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    (tmp_path / "ECGBERHT.md").write_text("# c\n", encoding="utf-8")
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    shown = []
    eng._emit = lambda ev: shown.append(ev)
    eng._replay_saved_receipts()                                  # first look: the baseline
    append_turns(str(tmp_path), [{"role": "steward", "text": "**Anchor** · ready to read: [X](/a)", "turn_id": "receipt:abc"}])
    eng._replay_saved_receipts()
    eng._replay_saved_receipts()
    assert shown == [{"t": "receipt", "text": "**Anchor** · ready to read: [X](/a)"}]


def test_foundry_review_pages_get_a_reading_target():
    r = dr.reading_target({"route": "/foundry?skill=chekhov"}, pid="p", effort_rel="")
    assert r["read"] == "/foundry?skill=chekhov"


def test_a_routed_deck_never_reads_through_an_older_pdf(tmp_path, monkeypatch):
    import os as _os, rnd_registry
    (tmp_path / "slides").mkdir()
    (tmp_path / "slides" / "Talk.pdf").write_text("old", encoding="utf-8")
    (tmp_path / "slides" / "Talk.pptx").write_text("new deck", encoding="utf-8")
    _os.utime(tmp_path / "slides" / "Talk.pdf", (1_000_000, 1_000_000))
    monkeypatch.setattr(rnd_registry, "get_project", lambda pid: {"folder_path": str(tmp_path)})
    reg = {dr._canonical_route("/artifact/p?path=slides/Talk.pdf").lower()}
    r = dr.reading_target({"route": "/artifact/p?path=slides/Talk.pptx"}, pid="p", effort_rel="", registered=reg)
    assert r["read"] is None and r["preparing"]
    _os.utime(tmp_path / "slides" / "Talk.pdf", None)
    r = dr.reading_target({"route": "/artifact/p?path=slides/Talk.pptx"}, pid="p", effort_rel="", registered=reg)
    assert r["read"] == "/artifact/p?path=slides%2FTalk.pdf"


# ---------- final whole-patch review, round 2 ----------

def test_a_steward_commit_to_served_code_is_reported_but_a_landing_is_not(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "served")
    monkeypatch.setattr(steward_engine, "_SERVED", repo)
    before = steward_engine._served_code_snapshot()
    (repo / "job_runner.py").write_text("edited and committed\n", encoding="utf-8")
    _sp.run(["git", "-C", str(repo), "add", "job_runner.py"], check=True)
    _sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "direct"], check=True)
    assert steward_engine._served_code_changes(before) == ["job_runner.py"]
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    before = steward_engine._served_code_snapshot()
    (repo / "posing.py").write_text("x\n", encoding="utf-8")                    # an author NAME proves nothing
    _sp.run(["git", "-C", str(repo), "add", "posing.py"], check=True)
    _sp.run(["git", "-C", str(repo), "-c", "user.name=Anchor lander", "commit", "-q", "-m", "land"], check=True)
    assert steward_engine._served_code_changes(before) == ["posing.py"]
    before = steward_engine._served_code_snapshot()
    (repo / "landed.py").write_text("x\n", encoding="utf-8")
    _sp.run(["git", "-C", str(repo), "add", "landed.py"], check=True)
    _sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "a verified landing"], check=True)
    code_jobs.record_landed_commit(_sp.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                                           text=True).stdout.strip())
    assert steward_engine._served_code_changes(before) == []                    # its exact hash is on record
    before = steward_engine._served_code_snapshot()
    (repo / "steward_cockpit" / "static").mkdir(parents=True)
    (repo / "steward_cockpit" / "static" / "v1.html").write_text("<script>x</script>", encoding="utf-8")
    assert steward_engine._served_code_changes(before) == ["steward_cockpit/static/v1.html"]


def test_a_published_receipt_is_shown_once_even_when_replayed(tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "c"))
    (tmp_path / "ECGBERHT.md").write_text("# c\n", encoding="utf-8")
    (tmp_path / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n|---|---|---|---|\n", encoding="utf-8")
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    shown = []
    eng._emit = lambda ev: shown.append(ev)
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: (
        __import__("steward_cockpit.conversation_history", fromlist=["x"]).append_turns(
            str(tmp_path), [{"role": role, "text": text, "turn_id": turn_id}]) or True)
    eng._replay_saved_receipts()
    steward_engine.receipt_baseline(str(tmp_path))
    (tmp_path / "N.md").write_text("# n", encoding="utf-8")
    with open(tmp_path / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| N | `N.md` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t1")
    eng._replay_saved_receipts()
    assert len([e for e in shown if e.get("t") == "receipt"]) == 1


def test_another_runs_halt_never_reaches_a_running_skill_jobs_status(tmp_path):
    import json as _j, time as _t
    c = _campaign(tmp_path, steps=3)
    st = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - 60))
    (c / ".ecgberht" / "skill-jobs.json").write_text(_j.dumps({"B": {
        "status": "running", "started": st, "label": "B", "argv": ["node", "C:/dev/trio/gandalf/bin/run.mjs"]}}), encoding="utf-8")
    (c / "_gandalf-status.log").write_text("[10:00] Gandalf review · final\nBlocker  HALT: model session limit\n", encoding="utf-8")
    out = sc.compose_status(str(c), {})
    assert out["halt"] is None and "STOPPED" not in " ".join(out["now"])


# ---------- final whole-patch review, round 4 ----------

def test_an_interrupted_turn_still_reports_a_direct_code_change(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "served")
    monkeypatch.setattr(steward_engine, "_SERVED", repo)
    eng = steward_engine.Engine(str(tmp_path / "c"), fake=True)
    said = []
    eng._emit = lambda ev: said.append(ev)
    eng._served_snap = steward_engine._served_code_snapshot()
    (repo / "job_runner.py").write_text("x\n", encoding="utf-8")

    class Writer:                                   # the running steward process: killed and reaped, THEN audited
        killed = False
        def poll(self): return None if not Writer.killed else 0
        def wait(self, timeout=None): return 0
    eng.proc, eng.busy, eng._last_submitted = Writer(), True, "x"
    eng._turn_touched_served = True                 # the steward's own tool wrote there (2026-10-08: only then is it said)
    monkeypatch.setattr(eng, "_kill_tree", lambda p: setattr(Writer, "killed", True))
    monkeypatch.setattr(eng, "_journal_routing", lambda **k: None)
    monkeypatch.setattr(eng, "_hold_queue", lambda reason: None)
    eng._interrupt_turn_locked("Take this now")
    assert Writer.killed
    assert any("served code changed during this turn" in str(ev.get("text")) and "STANDS" in str(ev.get("text")) for ev in said) and eng._served_snap is None


def test_a_skill_job_never_shows_a_steps_check_as_its_own(tmp_path):
    import json as _j, time as _t
    (tmp_path / ".ecgberht").mkdir()
    st = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - 60))
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(_j.dumps({"G": {
        "status": "running", "started": st, "label": "G", "argv": ["node", "C:/dev/trio/gandalf/bin/run.mjs"]}}), encoding="utf-8")
    _w, _p, _s, tests, _f = sc.who_is_working(str(tmp_path), {}, [], None, evidence_tests="Passed - pytest (exit 0)")
    assert tests == "tests not run yet"


# ---------- final whole-patch review, round 5 ----------

def test_checking_out_an_older_commit_is_reported(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "served")
    monkeypatch.setattr(steward_engine, "_SERVED", repo)
    old = _sp.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (repo / "app.py").write_text("v2\n", encoding="utf-8")
    _sp.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    _sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "v2"], check=True)
    before = steward_engine._served_code_snapshot()
    _sp.run(["git", "-C", str(repo), "checkout", "-q", old], check=True)            # backwards
    assert steward_engine._served_code_changes(before) == ["app.py"]


# ---------- dual review consensus C1 + C2 ----------

def _job_in(tmp_path, monkeypatch, cdir_of, coder_cls=None, coder_kw=None):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", _json.dumps([_sys.executable, str(_P(__file__).with_name("fake_review.py"))]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    repo = _git_repo(tmp_path / "repo")
    cdir = cdir_of(repo)
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    out = code_jobs.start(str(cdir), str(repo), "x", PASS_CHECK, engine_factory=lambda wt: (coder_cls or _Coder)(wt, **(coder_kw or {})))
    for _ in range(300):
        job = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if job.get("status") in ("done", "failed"):
            return repo, cdir, job
        _time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(str(cdir)))


def test_a_cockpit_inside_the_repo_still_lands_its_job(tmp_path, monkeypatch):
    class Heartbeat(_Coder):                         # the cockpit's records change during the job, as they always do
        def wake(self, fresh=False, seed=None):
            cdir = _P(self.code_job["cdir"])
            (cdir / "strip.json").write_text("{}", encoding="utf-8")
            (cdir / ".ecgberht" / "attention.json").write_text("{}", encoding="utf-8")
            (_P(self.code_job["repo"]) / "README.md").write_text("John edits a note\n", encoding="utf-8")
            return super().wake(fresh, seed)
    repo, cdir, job = _job_in(tmp_path, monkeypatch, lambda r: r / "Setup and Mother Ship", Heartbeat)
    assert job["landed"] is True, job["land_note"]
    assert not job.get("served_tree_changed") and (repo / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (repo / "README.md").read_text(encoding="utf-8") == "John edits a note\n"      # his bytes kept


def test_a_root_cockpit_still_has_its_code_edits_detected(tmp_path, monkeypatch):
    class Sneaky(_Coder):
        def wake(self, fresh=False, seed=None):
            (_P(self.code_job["repo"]) / "live.py").write_text("x\n", encoding="utf-8")
            return super().wake(fresh, seed)
    repo, cdir, job = _job_in(tmp_path, monkeypatch, lambda r: r, Sneaky)
    assert job["landed"] is False and job["served_tree_changed"] == ["live.py"]


def test_a_code_commit_made_directly_in_the_source_is_caught(tmp_path, monkeypatch):
    class Committer(_Coder):
        def wake(self, fresh=False, seed=None):
            repo = self.code_job["repo"]
            (_P(repo) / "live.py").write_text("x\n", encoding="utf-8")
            _sp.run(["git", "-C", repo, "add", "live.py"], check=True)
            _sp.run(["git", "-C", repo, "commit", "-q", "-m", "direct"], check=True)
            return super().wake(fresh, seed)
    repo, cdir, job = _job_in(tmp_path, monkeypatch, lambda r: r.parent / "steward", Committer)
    assert job["landed"] is False and any(p.startswith("live.py (committed ") for p in job["served_tree_changed"])


# ---------- dual review consensus C3, C5, C6, C7, C9/C10 ----------

def test_grok_and_gemini_are_refused_as_coders_until_they_report_writes(monkeypatch):
    import anchor_settings
    monkeypatch.setattr(anchor_settings, "get_launch_settings",
                        lambda: {"coding_family": "grok", "default_cli": "gemini", "review_family": "chatgpt",
                                 "settings_revision": "r"})
    fam, why = code_jobs.choose_coder("grok")
    assert fam is None and "does not report which files it wrote" in why
    assert code_jobs.choose_coder("gemini") == ("gemini", None)
    assert code_jobs.choose_coder() == ("gemini", None)                      # the ladder skips grok, uses gemini


def test_served_foundry_html_is_code_not_a_document():
    assert not code_jobs.is_document("foundry-gui/dist/index.html") and code_jobs.is_app_file("foundry-gui/dist/index.html")


def test_a_stop_during_finishing_is_honoured_before_placement(tmp_path, monkeypatch):
    real = code_jobs.run_review

    def review_then_stop(job, tree, head, delta_from=""):
        rec = real(job, tree, head, delta_from)
        r = code_jobs.stop(job["steward_dir"], actor="John")             # a fresh finishing job: not stale
        assert r["ok"] and r.get("stop_requested")
        return rec
    monkeypatch.setattr(code_jobs, "run_review", review_then_stop)
    repo, job = _job(tmp_path, monkeypatch)
    assert job["landed"] is False and job["status"] == "stopped" and job["stopped_by"] == "John"
    assert job["check_ok"] is True and job["review"]["verdict"] == "PASS"
    assert _P(job["kept_worktree"]).is_dir()
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_the_hold_refuses_engines_not_folders_and_is_a_structured_refusal(monkeypatch, tmp_path):
    import job_runner, lanes
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    fdir = tmp_path / "trio" / "foreman"
    (fdir / "bin").mkdir(parents=True)
    try:
        job_runner.launch("build", cwd=str(tmp_path), prompt="x")
        raise AssertionError("not refused")
    except lanes.EngineNotAllowedError as e:                                  # the dashboard answers it as 400 JSON
        assert "foreman-code-job-only" in str(e)
    from steward_cockpit import code_jobs as _cj
    harmless = [_sys.executable, "-c", "pass"]
    assert not any(("/foreman/bin/" in str((fdir / a).resolve()).replace(chr(92), "/").lower()) for a in harmless[1:])


# ---------- dual review consensus C4 + C8 ----------

def test_an_older_pdf_never_reads_for_a_newer_deck(tmp_path, monkeypatch):
    import os as _os
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "Talk.pdf").write_text("old slides", encoding="utf-8")
    (tmp_path / "d" / "Talk.pptx").write_text("new deck", encoding="utf-8")
    _os.utime(tmp_path / "d" / "Talk.pdf", (1_000_000, 1_000_000))
    items = [{"what": "Talk (PDF)", "path": "d/Talk.pdf", "step": "s1"}, {"what": "Talk", "path": "d/Talk.pptx", "step": "s1"}]
    acts = [a for a in sc.review_acts({}, items, str(tmp_path)) if a["act"] != "Next"]
    assert len(acts) == 1 and acts[0]["path"] == "d/Talk.pptx" and not acts[0].get("companions")
    (tmp_path / "r").mkdir()
    eng, eff, said, emitted = _receipt_engine(tmp_path / "r", monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "Talk.pdf").write_text("old", encoding="utf-8")
    (eff / "Talk.pptx").write_text("new", encoding="utf-8")
    _os.utime(eff / "Talk.pdf", (1_000_000, 1_000_000))
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Talk (PDF) | `Talk.pdf` | 2026-10-07 | 1 |\n| Talk | `Talk.pptx` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t1")
    assert len(said) == 1 and "preparing a reading copy: Talk" in said[0][1] and "ready to read" not in said[0][1]


def test_follow_changes_only_on_his_scrolling(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    scroll = surface.locator('.scroll').first
    # a wheel on a pane with nothing to scroll leaves following on
    scroll.evaluate("s => { s.innerHTML = '<div>short</div>'; s._follow = true; }")
    scroll.hover()
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(200)
    assert scroll.evaluate("s => s._follow") is True
    # he scrolls up through long content; the content then shrinks (a layout clamp) - following stays off
    scroll.evaluate("""s => { for (let i = 0; i < 40; i++) { const d = document.createElement('div');
        d.style.height = '60px'; d.className = 'filler'; s.appendChild(d); } }""")
    page.wait_for_timeout(300)
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(1700)                                   # past his input window
    scroll.evaluate("s => s.querySelectorAll('.filler').forEach((d, i) => { if (i > 5) d.remove(); })")
    page.wait_for_timeout(300)
    assert scroll.evaluate("s => s._follow") is False


# ---------- dual review CONFIRM round ----------

def test_a_deck_registered_first_and_its_older_pdf_after_never_reads_ready(tmp_path, monkeypatch):
    import os as _os
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "Talk.pptx").write_text("new deck", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Talk | `Talk.pptx` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t1")                                        # the deck alone: preparing
    (eff / "Talk.pdf").write_text("old slides", encoding="utf-8")
    _os.utime(eff / "Talk.pdf", (1_000_000, 1_000_000))                       # older than the deck
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Talk (PDF) | `Talk.pdf` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t2")                                        # the old PDF arrives second
    assert all("ready to read" not in t for _r, t, _i in said), said
    assert "preparing a reading copy: Talk" in said[0][1]


def test_a_taller_window_never_rearms_follow_after_he_scrolled_away(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    scroll = surface.locator('.scroll').first
    scroll.evaluate("""s => { for (let i = 0; i < 40; i++) { const d = document.createElement('div');
        d.style.height = '60px'; s.appendChild(d); } }""")
    page.wait_for_timeout(300)
    scroll.hover()
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(1700)                                   # past his input window
    before = scroll.evaluate("s => s.clientHeight")
    page.set_viewport_size({"width": 1365, "height": 2600})       # the real window grows (ChatGPT confirm 3)
    page.wait_for_timeout(500)
    assert scroll.evaluate("s => s.clientHeight") > before         # the viewport really grew...
    assert scroll.evaluate("s => s.scrollHeight - s.scrollTop - s.clientHeight") < 4   # ...and clamped to the bottom
    assert scroll.evaluate("s => s._follow") is False              # a clamp is not his scroll: following stays off
