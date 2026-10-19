"""Cockpit workflow Wave C (2026-09-20) — decisions John can answer once.

STUB GATE for PLAN.md v3 rows C1–C3 (Skill Foundry/planning/cockpit-workflow-2026-09-19):

- C1 one matcher, one record: parse_decision reads the decision shape (stake, recommendation, why,
  alternatives, the question) from the tail of a turn; has_recommendation IS the engine's check.
- C2 two wait authorities: a product review's wait is the ledger's; for a decision the ENGINE records
  John's answer and clears the strip's human_wait in the same turn.
- C3 answered means retired: the turn leaves the identity (the same question on the same work is the same
  question); the reshape re-ask keeps the decision's identity; an answered question asked again is never
  pinned and the steward is told once; a changed question names what it replaces.
"""
import json
from pathlib import Path

import pytest

from steward_cockpit import question_context as qc
from steward_cockpit import steward_engine as eng
from tests.test_usage_checkpoint_engine import cockpit  # noqa: F401  (the fake engine fixture)

SHAPED = ("The guide gates the build path and John has been away. I recommend keeping this version. "
          "It already passed the independent check. Alternatively we redo the intro, which costs a day. Keep it?")


def finish(engine, text):
    engine.turn_text = text
    engine._handle({"type": "result", "total_cost_usd": 0.0, "duration_ms": 1, "usage": {}}, engine.proc)


# ── C1 ────────────────────────────────────────────────────────────────────────

def test_the_one_parser_reads_the_decision_shape():
    d = qc.parse_decision(SHAPED)
    assert d["recommendation"] == "I recommend keeping this version."
    assert d["stake"] == ["The guide gates the build path and John has been away."]
    assert d["why"] == "It already passed the independent check."
    assert d["alternatives"] == []                                          # prose is not an alternative; bullets are
    bullets = "Context.\n**Recommendation:** ship v2.\nIt is the smaller change.\n- keep v1 (safer, later)\n- redo both (a week)\nShip?"
    d = qc.parse_decision(bullets)
    assert d["recommendation"] == "**Recommendation:** ship v2." and d["why"] == "It is the smaller change."
    assert d["alternatives"] == ["keep v1 (safer, later)", "redo both (a week)"]   # the bullet marker is not part of the alternative (Wave H: it becomes a Choose button)
    assert qc.parse_decision("Nothing decided here. What now?")["recommendation"] == ""


def test_has_recommendation_is_the_engine_check():
    assert eng._has_recommendation is qc.has_recommendation
    assert qc.has_recommendation("I lean toward the smaller cut. Which?")
    assert not qc.has_recommendation("Recommendation:\nProceed?")          # a bare marker is not a recommendation
    assert not qc.has_recommendation("I do not recommend making a choice yet.\nProceed?")
    assert not qc.has_recommendation("I recommend the blue one. " + ("working. " * 400) + "Now what?")   # the tail only


def test_the_record_carries_the_shape_and_keeps_its_origin_through_normalize():
    saved = qc.save_question_context("Keep it?", SHAPED, asked_at=1, source_ref="Cockpit conversation",
                                     scope={"step_id": "s2", "source_turn_id": "t1"})
    assert saved["stake"][0].startswith("The guide gates") and saved["why"].startswith("It already passed")
    later = qc.save_question_context("Keep it?", "other words", asked_at=2, source_ref="Cockpit conversation",
                                     scope={"step_id": "s2", "source_turn_id": "t2"})
    assert later["id"] == saved["id"]                                        # the turn leaves the identity
    assert qc.save_question_context("Keep it?", SHAPED, asked_at=2, source_ref="Cockpit conversation",
                                    scope={"step_id": "s3", "source_turn_id": "t1"})["id"] != saved["id"]
    reshaped = qc.save_question_context("Keep this version?", SHAPED, asked_at=2, source_ref="Cockpit conversation",
                                        scope={"step_id": "s2"}, origin_id=saved["id"])
    assert reshaped["id"] == saved["id"] and reshaped["origin_id"] == saved["id"]
    again = qc.normalize_question_context(json.loads(json.dumps(reshaped)))
    assert again["id"] == saved["id"] and again["stake"] == reshaped["stake"] and again["why"] == reshaped["why"]
    assert qc.save_question_context("Q?", "x", asked_at=1, origin_id="not-a-hash")["origin_id"] is None
    changed = qc.save_question_context("Ship v2?", SHAPED, asked_at=3, scope={"step_id": "s2"}, what_changed=saved["question"])
    assert qc.normalize_question_context(changed)["what_changed"] == "Keep it?"


# ── C3 ────────────────────────────────────────────────────────────────────────

def test_the_reshape_re_ask_keeps_the_decisions_identity(cockpit, monkeypatch):
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    sent = []
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: (sent.append(text), True)[1])
    finish(cockpit, "The guide is done. Keep it?")                     # no recommendation -> nudged once
    first = cockpit.state()["question_context"]
    assert first and cockpit._decision_nudged and any("without a recommendation" in t for t in sent)
    finish(cockpit, SHAPED)                                            # the re-ask in John's shape
    second = cockpit.state()["question_context"]
    assert second["question"] == "Keep it?" and second["recommendation"] == "I recommend keeping this version."
    assert second["id"] == first["id"] and second["origin_id"] == first["id"]      # the same decision
    assert len([t for t in sent if "without a recommendation" in t]) == 1


def test_an_answered_question_asked_again_is_not_pinned_and_the_steward_is_told_once(cockpit, monkeypatch):
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    sent = []
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: (sent.append(text), True)[1])
    finish(cockpit, SHAPED)
    saved = cockpit.state()["question_context"]
    assert cockpit.say("Keep it", question_id=saved["id"])["ok"]
    assert cockpit.state()["question_context"] is None
    finish(cockpit, "Back to it. I recommend keeping this version. Keep it?")   # the same words, the same step
    assert cockpit.state()["question_context"] is None and cockpit.state()["open_question"] == ""
    told = [t for t in sent if "already answered this question" in t]
    assert len(told) == 1 and '"Keep it"' in told[0]
    finish(cockpit, "Once more. I recommend keeping this version. Keep it?")
    assert cockpit.state()["question_context"] is None                              # still retired
    assert len([t for t in sent if "already answered this question" in t]) == 1     # told once
    assert cockpit.question_history[-1]["reask_told_at"]
    finish(cockpit, "A new one. I recommend the short intro. Cut the intro?")       # a genuinely new question pins
    assert cockpit.state()["question_context"]["question"] == "Cut the intro?"
    assert cockpit.state()["decision_history"][-1]["answer"] == "Keep it"


def test_a_changed_question_while_one_is_open_names_what_it_replaces(cockpit, monkeypatch):
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: True)
    finish(cockpit, SHAPED)
    first = cockpit.state()["question_context"]
    finish(cockpit, "Thinking again. I recommend the short intro. Cut the intro instead?")
    second = cockpit.state()["question_context"]
    assert second["id"] != first["id"] and second["what_changed"] == "Keep it?"


# ── C2 ────────────────────────────────────────────────────────────────────────

def test_the_engine_records_the_answer_and_clears_the_wait(cockpit, monkeypatch):
    from steward_cockpit import steward_campaign as sc
    d = Path(cockpit.dir)
    (d / "ECGBERHT.md").write_text("## North star\n\nShip the guide.\n", encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "ecgberht-roadmap-v0", "roadmap_events": [],
        "roadmap_projection": [{"id": "s2", "name": "Guide", "status": "active"}]}), encoding="utf-8")
    strip = {"schema": "ecgberht-strip-v0", "phase": "slice", "active_effort": "Guide", "current_step_id": "s2",
             "next_recommended": "Keep the guide", "why_next": "it gates the build", "human_wait": "John: keep it or redo the intro",
             "receipts": []}
    (d / "strip.json").write_text(json.dumps(strip), encoding="utf-8")
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: True)
    assert sc.compose_status(str(d), {"busy": False})["plan"]["waiting_on_you"] == "John: keep it or redo the intro"
    finish(cockpit, SHAPED)
    saved = cockpit.state()["question_context"]
    assert cockpit.say("Keep it", question_id=saved["id"])["ok"]
    after = json.loads((d / "strip.json").read_text(encoding="utf-8"))
    assert after["human_wait"] == "" and after["next_recommended"] == "Keep the guide"        # one field cleared, the rest untouched
    assert cockpit.question_history[-1]["answer"] == "Keep it"
    st = sc.compose_status(str(d), {"busy": False})
    assert st["plan"]["waiting_on_you"] == "" and "waiting on you" not in st["lead_line"]     # answered: not a wait


def test_a_product_review_answer_leaves_the_strip_alone(cockpit, monkeypatch):
    d = Path(cockpit.dir)
    (d / "strip.json").write_text(json.dumps({"schema": "ecgberht-strip-v0", "human_wait": "review it", "receipts": []}), encoding="utf-8")
    request = {"id": "review-1", "step_id": "s2", "presentation_id": "p1", "purpose": "Review this guide", "source_message": "The guide."}
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "needs_you", "managed_refinement": True, "pending_request": request})
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: True)
    saved = cockpit.state()["pending_questions"][0]
    assert cockpit.say("Looks good", question_id=saved["id"])["ok"]
    assert json.loads((d / "strip.json").read_text(encoding="utf-8"))["human_wait"] == "review it"   # the ledger owns a review's wait


# ── the tile ──────────────────────────────────────────────────────────────────

def test_the_tile_is_four_lines_with_the_recommendation_as_the_first_button():
    js = Path(__file__).resolve().parents[1].joinpath("steward_cockpit", "static", "shared.js").read_text(encoding="utf-8")
    body = js.split("function fillQuestionPanel(host, q)")[1].split("function paintActionNeeded")[0]
    assert body.index('"Accept recommendation"') < body.index('el("details", "action-context")') < body.index('"question-source"')
    assert '"no recommendation given"' in body                                   # honest when the parser finds none
