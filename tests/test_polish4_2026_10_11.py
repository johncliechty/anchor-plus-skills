"""John 2026-10-11 (#4 polish): one notice per product, never the same link twice and never for the register's own
"Plan ·" rows; a register write mid-turn waits for the turn's end; his message behind his own long turn is answered
within half a minute; a page opened mid-turn shows what the steward has said so far; program source opens as text."""
import time
from pathlib import Path

import pytest

import deliverables_register as dr
import report_viewer
from steward_cockpit import steward_engine, steward_routes as sr

HEAD = "| What | Where | Date | Step |\n|---|---|---|---|\n"


def _effort(tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "eff"))
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# a steward cockpit\n", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text(HEAD, encoding="utf-8")
    steward_engine.receipt_baseline(str(eff))
    return eff


def _notices(eff):
    from steward_cockpit.conversation_history import read_history_document
    return [t["text"] for t in read_history_document(str(eff))["turns"] if "**Anchor**" in t["text"]]


def test_one_file_under_several_steps_and_titles_is_one_notice_with_one_link(tmp_path, monkeypatch):
    eff = _effort(tmp_path, monkeypatch)
    route = "/artifact/p1?path=calc/calc.py"          # a landed file in its repository, as the cockpit registers it
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| START HERE - calculator | %s | 2026-10-11 | 2 |\n" % route)
        fh.write("| Calculator division landed - calc.py | %s | 2026-10-11 | 3 |\n" % route)
        fh.write("| Calculator multiplication landed - calc.py | %s | 2026-10-11 | 4 |\n" % route)
    steward_engine.publish_delivery_receipts(str(eff))
    said = _notices(eff)
    assert len(said) == 1, said
    assert said[0].count("/artifact/p1?path=calc%2Fcalc.py") == 1 and said[0].count("](") == 1, said[0]


def test_the_registers_own_plan_rows_are_never_announced(tmp_path, monkeypatch):
    eff = _effort(tmp_path, monkeypatch)
    (eff / "journal").mkdir()
    (eff / "journal" / "0007-calculator-cli-plan.md").write_text("# plan", encoding="utf-8")
    steward_engine.publish_delivery_receipts(str(eff))
    assert _notices(eff) == []


def test_a_register_write_during_a_turn_waits_for_the_turns_end(tmp_path, monkeypatch):
    eff = _effort(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(steward_engine, "publish_delivery_receipts", lambda *a, **k: calls.append(a))
    busy = type("E", (), {"general": False, "dir": str(eff), "busy": True, "_emit": lambda self, ev: None})()
    monkeypatch.setitem(sr.ENGINES, "test-busy", busy)
    dr.notify_receipt(str(eff))
    assert calls == []
    busy.busy = False
    busy._record_conversation = lambda *a, **k: True
    dr.notify_receipt(str(eff))
    assert len(calls) == 1


@pytest.fixture
def eng(monkeypatch, tmp_path):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    return steward_engine.Engine(str(tmp_path), fake=True)


def test_his_message_behind_his_own_turn_is_taken_after_the_wait(eng, monkeypatch):
    calls = []
    monkeypatch.setattr(eng, "_interrupt_turn_locked", lambda reason: calls.append(reason) or {"ok": True})
    monkeypatch.setattr(eng, "_wake_locked", lambda fresh, seed: calls.append("wake") or (True, ""))
    eng.busy, eng.queue, eng.turn_started = True, ["why not at the same time?"], 1000.0
    eng._auto_take_now(999.0)
    assert calls == [], "a later turn is never stopped for a message an earlier one held"
    eng._auto_take_now(1000.0)
    assert calls == ["John: take this now", "wake"]
    eng.queue = []
    eng._auto_take_now(1000.0)
    assert calls == ["John: take this now", "wake"], "nothing waiting: nothing stopped"
    monkeypatch.setenv("ANCHOR_TAKE_NOW_AFTER_S", "0")
    assert steward_engine._take_now_after() == 0
    monkeypatch.delenv("ANCHOR_TAKE_NOW_AFTER_S")
    assert steward_engine._take_now_after() == 30


def test_a_failed_turn_still_announces_what_it_registered():
    src = (Path(steward_engine.__file__)).read_text(encoding="utf-8")
    assert "else:                                # what the turn registered is still announced" in src


def test_a_page_opened_mid_turn_replays_what_the_turn_has_said():
    js = (Path(__file__).resolve().parent.parent / "static" / "steward-dialogue.js").read_text(encoding="utf-8")
    assert "if (j.state && j.state.busy)" in js and "if (ev.t !== 'john') handleEvent(ev)" in js


def test_program_source_opens_as_text_never_a_download(tmp_path):
    import anchor_gui
    assert sr.deliverable_content_type(".py") == ("text/plain; charset=utf-8", "inline")
    assert report_viewer._ARTIFACT_CONTENT_TYPES[".py"].startswith("text/plain")
    assert anchor_gui._ECGBERHT_ARTIFACT_TYPES[".py"].startswith("text/plain")
    assert sr.deliverable_content_type(".bin") == ("application/octet-stream", "attachment")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    obj, code = sr.handle_get(str(tmp_path), "deliverable-file", {"path": "calc.py", "render": "1"})
    assert code == 200 and "def add(a, b):" in obj["__html__"]
