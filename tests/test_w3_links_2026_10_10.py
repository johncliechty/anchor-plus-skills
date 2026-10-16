"""W3 of the night of 2026-10-10: links in a steward's reply open the right thing, or say exactly why not.
Acceptance: the registered PDF opens from the dialogue (and the card), not the HTML beside it. Each failure word is
earned: "not found" only for a confirmed missing file; "changed since it was registered" for other bytes; "unavailable
now" for anything outside, private or unknown. External links are exempt; an absolute Anchor URL opens relatively;
no credential is ever recorded; a correction never swaps in another product or revision (review r1)."""
import hashlib
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import link_check  # noqa: E402

PID = "p0001"


def _effort(tmp_path, monkeypatch):
    proj = tmp_path / "Proj"
    eff = proj / "Effort"
    (eff / "out").mkdir(parents=True)
    (eff / "r2").mkdir()
    (eff / "ECGBERHT.md").write_text("# x\n", encoding="utf-8")
    (eff / "out" / "report.pdf").write_bytes(b"%PDF-1.4 report")
    (eff / "out" / "report.html").write_text("<p>report</p>", encoding="utf-8")
    (eff / "r2" / "deck.pdf").write_bytes(b"%PDF-1.4 r2")
    (eff / "notes.md").write_text("# notes\n", encoding="utf-8")
    (eff / "Plan(v1).pdf").write_bytes(b"%PDF plan")
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n"
        "| Report (PDF) | `out/report.pdf` | 2026-10-10 | 1 |\n"
        "| Report (HTML) | `out/report.html` | 2026-10-10 | 1 |\n"
        "| Deck r2 | `r2/deck.pdf` | 2026-10-10 | 1 |\n", encoding="utf-8")
    monkeypatch.setattr(link_check, "_project_folder", lambda pid: str(proj) if pid == PID else None)
    import deliverables_register as dr
    monkeypatch.setattr(dr, "project_and_rel", lambda cdir: (PID, "Effort"))
    return proj, eff


def _file_url(rel, d="Effort", **extra):
    q = "pid=%s&dir=%s&path=%s" % (PID, quote(d, safe=""), quote(rel, safe=""))
    for k, v in extra.items():
        q += "&%s=%s" % (k, v)
    return "/api/steward/deliverable-file?" + q


def test_the_registered_pdf_wins_over_the_html_beside_it(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "Read [the report](%s) when you can." % _file_url("out/report.html")
    out, report = link_check.check_reply(text, str(eff))
    assert "report.pdf" in out and "report.html" not in out
    assert report and report[0]["verdict"] == "the registered PDF"
    assert "now opens the registered copy" in link_check.report_line(report)


def test_an_absolute_anchor_url_opens_relatively_and_others_stay_external(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = ("[notes](http://localhost:8777/artifact/%s/Effort/notes.md) [paper](https://arxiv.org/abs/1234.5678) "
            "[lookalike](https://puter.example.com/artifact/%s?path=Effort/notes.md) "
            "[other box](https://other-box.tail1234.ts.net/artifact/%s?path=Effort/notes.md)" % (PID, PID, PID))
    out, report = link_check.check_reply(text, str(eff), hosts={"localhost", "127.0.0.1", "puter"})
    assert "](/artifact/%s/Effort/notes.md)" % PID in out
    assert "https://puter.example.com/" in out and "https://other-box.tail1234.ts.net/" in out
    assert report == []


def test_a_tailnet_name_is_anchor_only_when_listed_whole(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    link = "[n](https://puter.tail1234.ts.net/artifact/%s/Effort/notes.md)" % PID
    out, _ = link_check.check_reply(link, str(eff), hosts={"localhost", "puter", "puter.tail1234.ts.net"})
    assert "](/artifact/%s/Effort/notes.md)" % PID in out
    other = "[n](https://puter.another-tailnet.ts.net/artifact/%s/Effort/notes.md)" % PID
    assert link_check.check_reply(other, str(eff), hosts={"localhost", "puter", "puter.tail1234.ts.net"})[0] == other


def test_no_credential_is_ever_recorded(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "[n](http://localhost:8777/artifact/%s?path=Effort/notes.md&token=SECRET) and [g](/artifact/%s?path=Effort/gone.md&token=SECRET)" % (PID, PID)
    out, report = link_check.check_reply(text, str(eff), hosts={"localhost"})
    assert "SECRET" not in out and "SECRET" not in link_check.report_line(report)


def test_a_missing_file_is_not_found_an_outside_one_unavailable_and_neither_is_guessed(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    text = "[gone](/artifact/%s?path=Effort/gone.md) and [escape](/artifact/%s?path=../secret.txt)" % (PID, PID)
    out, report = link_check.check_reply(text, str(eff))
    assert {r["label"]: r["verdict"] for r in report} == {"gone": "not found", "escape": "unavailable now"}
    assert out == text, "an uncorrectable link is left as written - never swapped for a guess"


def test_a_missing_revision_is_never_replaced_by_another(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "[deck r1](%s)" % _file_url("r1/deck.pdf")         # r1 is gone; r2/deck.pdf is registered
    out, report = link_check.check_reply(text, str(eff))
    assert out == text and report[0]["verdict"] == "not found" and report[0]["fixed_to"] is None


def test_other_bytes_say_changed_an_unknown_project_or_escaping_effort_is_unavailable(tmp_path, monkeypatch):
    proj, eff = _effort(tmp_path, monkeypatch)
    (proj.parent / "Outside").mkdir()
    (proj.parent / "Outside" / "secret.pdf").write_bytes(b"x")
    stale = hashlib.sha256(b"older bytes").hexdigest()
    text = "[old notes](%s) [lost](/artifact/nope?path=a.md) [esc](%s)" % (
        _file_url("notes.md", hash=stale), _file_url("secret.pdf", d="../Outside"))
    _out, report = link_check.check_reply(text, str(eff))
    verdicts = {r["label"]: r["verdict"] for r in report}
    assert verdicts == {"old notes": "changed since it was registered", "lost": "unavailable now", "esc": "unavailable now"}


def test_a_link_into_another_effort_or_the_project_root_is_never_repaired_to_this_efforts_file(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    for text in ("[the pdf](/artifact/%s?path=out/report.pdf)" % PID, "[the pdf](%s)" % _file_url("out/report.pdf", d="E1")):
        out, report = link_check.check_reply(text, str(eff))
        assert out == text and report and report[0]["fixed_to"] is None, (text, report)


def test_a_broken_link_to_this_efforts_registered_file_is_repaired_to_its_own_route(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "[the pdf](%s)" % _file_url("out/report.pdf", hash="0" * 64)   # stale hash: changed, never re-pointed
    out, report = link_check.check_reply(text, str(eff))
    assert out == text and report[0]["verdict"] == "changed since it was registered"


def test_first_value_query_semantics_and_one_decode(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    (eff / "a%20b.pdf").write_bytes(b"%PDF literal percent name")
    _out, report = link_check.check_reply(
        "[dup](/artifact/%s?path=Effort/missing.pdf&path=Effort/notes.md) [pct](/artifact/%s/Effort/a%%2520b.pdf)" % (PID, PID), str(eff))
    assert [(r["label"], r["verdict"]) for r in report] == [("dup", "not found")]


def test_a_token_in_a_label_and_a_bad_port_never_leak_or_undo_the_rest(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    url = "http://localhost:8777/artifact/%s?path=Effort/notes.md&token=SECRET" % PID
    text = "[%s](%s) and [bad](http://localhost:99999/x?token=SECRET2)" % (url, url)
    out, _ = link_check.check_reply(text, str(eff), hosts={"localhost"})
    assert "SECRET" not in out.replace("SECRET2", "") and "](/artifact/" in out


def test_links_are_found_as_the_renderer_finds_them(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "[plan](/artifact/%s/Effort/Plan(v1).pdf) and [spaced](</artifact/%s/Effort/no such.md>)" % (PID, PID)
    _out, report = link_check.check_reply(text, str(eff))
    assert [(r["label"], r["verdict"]) for r in report] == [("spaced", "not found")]


def test_report_links_are_checked_through_the_report_viewer(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    import report_viewer
    monkeypatch.setattr(report_viewer, "resolve_artifact", lambda f, p, lane, job=None: {"mode": "pdf" if job == "j1" else "missing"})
    _out, report = link_check.check_reply("[r](/report/%s/research/j1) [gone](/report/%s/research/j2)" % (PID, PID), str(eff))
    assert [(r["label"], r["verdict"]) for r in report] == [("gone", "not found")]


def test_a_reply_without_links_is_untouched_and_a_failure_inside_never_raises(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    assert link_check.check_reply("plain words only", str(eff)) == ("plain words only", [])
    monkeypatch.setattr(link_check, "_check_reply", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert link_check.check_reply("[x](/artifact/p?path=a)", str(eff)) == ("[x](/artifact/p?path=a)", [])


def test_the_engine_checks_links_before_recording_and_the_page_swaps_the_whole_turn():
    eng = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert eng.index("link_check.check_reply(txt, self.dir)") < eng.index('"steward", txt, turn_id=completed_turn_id')
    assert '"t": "reply_links"' in eng and "_publish_link_report(completed_turn_id, link_report)" in eng
    js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert 'ev.t === "reply_links"' in js and "turnReplyBlocks" in js


def test_the_card_reads_a_product_through_the_register(tmp_path, monkeypatch):
    proj, eff = _effort(tmp_path, monkeypatch)
    from steward_cockpit import high_seat_card as card
    monkeypatch.setattr(card, "_effort_dir_of", lambda pid, rel: (str(eff), {"out/report.pdf", "out/report.html"}))
    html = card._item_link({"what": "Report", "path": "out/report.pdf"}, PID, "Effort")
    assert "deliverable-file" in html and "report.pdf" in html
    missing = card._item_link({"what": "Gone", "path": "out/gone.pdf"}, PID, "Effort")
    assert "<a " not in missing, "a missing file gets no link"
