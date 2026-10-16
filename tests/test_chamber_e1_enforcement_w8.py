# W8 (steward-e1 W2) — E1 enforcement: the steward turn-completion hook on
# the W2-proven converse seam, the JOINT negative-path test, the telemetry
# half's zero-model-call proof, and the V5 drawn blocked-turn state.
#
# AUTH-ON: not-a-surface
#
# The law under test (the chamber plan's W8 row + V1/V5, re-executed):
#   * a steward turn structurally CANNOT close while a RATIFIED direct
#     question id lacks a typed answer-reference — the engine blocks the
#     close with the NAMED finding E1-TURN-CLOSE-BLOCKED, and the suite
#     exercises an IMPERATIVE in-bound form (no question mark), never only
#     a '?' form (V1);
#   * a missing, unsigned, or ALTERED F7 artifact fails CLOSED with a named
#     reason — an unenforceable bound never degrades to permissive (never
#     silently open) — while a turn is never BLOCKED against a bound John
#     has not signed (the F7 artifact's own law);
#   * the seam is enforced at BOTH legs: the engine leg
#     (engine/steward-conversation.mjs :: enforceTurnCompletion, exercised
#     here through a real node run over the sibling module — the JOINT
#     half) and the bridge-boundary leg (chamber_e1_hook.
#     enforce_bridge_result, wired in anchor_gui's converse route);
#   * TELEMETRY (the other half of E1): the ⏱ status table + campaign
#     footer inject from the RE-HOMED run_pulse emitter on the telemetry
#     clock with ZERO model involvement, asserted by a zero-model-call
#     trace. HONESTY NOTE: the ⏱-table clock injection has STOOD since the
#     chamber W7 run_pulse re-home — this wave PROVES it at its seam rather
#     than claiming to have built it; the campaign-footer clock leg is
#     landed BY this wave (static/project-window.js pulse poll);
#   * V5: the blocked-turn refusal is a DRAWN state (AG-BLOCKED-TURN),
#     batched with the ordered transcript-link row for John's ONE signature
#     (chamber/MOCKUP-AMENDMENT-GATE-W2.md); the C9 re-pin FOLLOWS the
#     signature — pre-signature the W1 pin must still hold and the new
#     state is never claimed drawn.
#
# Hermetic: no server, no network, no PTY, no model. The one subprocess is
# `node` running the SIBLING's own pure hook function with inline JSON — the
# same interpreter the orchestrator gate itself runs on.
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import chamber_dom_law as cdl  # noqa: E402
import chamber_e1_bound as e1b  # noqa: E402
import chamber_e1_hook as e1h  # noqa: E402
import chamber_enforcement as cenf  # noqa: E402
import chamber_mockup_diff as cmd  # noqa: E402
import chamber_pulse as cpulse  # noqa: E402
import chamber_rail as crail  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]
AMEND_W2 = ANCHOR / "chamber" / "MOCKUP-AMENDMENT-GATE-W2.md"

#: V1's imperative in-bound form of record — the verbatim T+15 trigger.
#: NO question mark: the bound is the ratified one, not "has a '?'".
IMPERATIVE_UTTERANCE = e1b.T15_TRIGGER_TEXT

QMARK_UTTERANCE = "Did you get the revised syllabus deck?"


# ── artifact fixtures: signed / forced-unsigned / altered copies ─────────────

def _artifact_text() -> str:
    return e1b.RATIFICATION_PATH.read_text(encoding="utf-8")


def _signed_copy(tmp_path, mutate=None) -> Path:
    """A SIGNED tmp copy of the committed F7 artifact (the W1 suite's own
    convention) — deterministic whether or not John has signed the real
    one by the time this runs."""
    text = _artifact_text()
    lines = text.splitlines()
    lines[0] = lines[0].replace(" — UNSIGNED", "")
    text = "\n".join(lines)
    text = re.sub(r"^\*\*Signed by:\*\*.*$",
                  "**Signed by:** John — 2026-08-12 (test copy)",
                  text, count=1, flags=re.MULTILINE)
    if mutate:
        text = mutate(text)
    p = tmp_path / "E1-BOUND-RATIFICATION.md"
    p.write_text(text, encoding="utf-8")
    return p


def _unsigned_copy(tmp_path) -> Path:
    """A copy FORCED unsigned — deterministic regardless of the real
    artifact's state."""
    text = _artifact_text()
    lines = text.splitlines()
    if "UNSIGNED" not in lines[0]:
        lines[0] += " — UNSIGNED"
    text = "\n".join(lines)
    text = re.sub(r"^\*\*Signed by:\*\*.*$",
                  "**Signed by:** (awaiting John — E1 bound ratification, "
                  "F7)", text, count=1, flags=re.MULTILINE)
    p = tmp_path / "unsigned.md"
    p.write_text(text, encoding="utf-8")
    return p


def _refs_for(utterance) -> list:
    return [e1b.make_answer_reference(q["question_id"], "steward-reply",
                                      "Answered: yes — received in full.")
            for q in e1b.parse_direct_questions(utterance)]


# ═════════════════════════════════════════════════════════════════════════════
# The negative path (Python leg) — blocked close, named finding
# ═════════════════════════════════════════════════════════════════════════════

def test_blocked_close_on_the_imperative_in_bound_form(tmp_path):
    # V1: the in-bound form of record carries NO question mark.
    assert "?" not in IMPERATIVE_UTTERANCE
    verdict = e1h.evaluate_turn_close(
        IMPERATIVE_UTTERANCE, {"say": "The scan is going well."},
        artifact_path=_signed_copy(tmp_path))
    assert verdict["decision"] == e1h.DECISION_BLOCK
    assert verdict["enforced"] is True
    assert verdict["finding"] == e1h.FINDING_TURN_BLOCKED
    assert verdict["unanswered"], "the unanswered id is NAMED, never silent"
    assert verdict["unanswered"][0]["kind"] == e1b.KIND_IMPERATIVE_ASK
    assert verdict["unanswered"][0]["rule"] == "confirm-receipt"
    assert verdict["unanswered"][0]["text"] == IMPERATIVE_UTTERANCE


def test_blocked_close_on_a_terminal_qmark_form(tmp_path):
    verdict = e1h.evaluate_turn_close(
        QMARK_UTTERANCE, {"say": "Working on the syllabus."},
        artifact_path=_signed_copy(tmp_path))
    assert verdict["decision"] == e1h.DECISION_BLOCK
    assert verdict["finding"] == e1h.FINDING_TURN_BLOCKED


def test_close_allowed_when_every_id_carries_a_typed_reference(tmp_path):
    utterance = IMPERATIVE_UTTERANCE
    verdict = e1h.evaluate_turn_close(
        utterance, {"say": "Yes — I have all your comments.",
                    "answer_references": _refs_for(utterance)},
        artifact_path=_signed_copy(tmp_path))
    assert verdict["decision"] == e1h.DECISION_CLOSE
    assert verdict["enforced"] is True and verdict["finding"] is None
    assert verdict["answered"], "the discharging references ride the verdict"


def test_partial_answers_block_and_name_only_the_unanswered(tmp_path):
    utterance = "%s %s" % (QMARK_UTTERANCE, IMPERATIVE_UTTERANCE)
    questions = e1b.parse_direct_questions(utterance)
    assert len(questions) == 2
    ref = e1b.make_answer_reference(questions[0]["question_id"],
                                    "steward-reply", "Yes, got the deck.")
    verdict = e1h.evaluate_turn_close(
        utterance, {"say": "…", "answer_references": [ref]},
        artifact_path=_signed_copy(tmp_path))
    assert verdict["decision"] == e1h.DECISION_BLOCK
    named = [q["question_id"] for q in verdict["unanswered"]]
    assert named == [questions[1]["question_id"]]


def test_an_invalid_reference_shape_never_discharges(tmp_path):
    utterance = IMPERATIVE_UTTERANCE
    qid = e1b.parse_direct_questions(utterance)[0]["question_id"]
    for bad in ({"question_id": qid, "answer_text": ""},          # empty
                {"question_id": "not-an-id", "answer_text": "x"},  # bad id
                "not-a-dict"):
        verdict = e1h.evaluate_turn_close(
            utterance, {"say": "…", "answer_references": [bad]},
            artifact_path=_signed_copy(tmp_path))
        assert verdict["decision"] == e1h.DECISION_BLOCK, bad


# ═════════════════════════════════════════════════════════════════════════════
# Fail CLOSED: missing / unsigned / altered artifact — named, never silent
# ═════════════════════════════════════════════════════════════════════════════

def test_missing_artifact_fails_closed_by_name(tmp_path):
    verdict = e1h.evaluate_turn_close(
        IMPERATIVE_UTTERANCE, {"say": "…"},
        artifact_path=tmp_path / "absent.md")
    assert verdict["decision"] == e1h.DECISION_UNENFORCEABLE
    assert verdict["enforced"] is False
    assert verdict["finding"] == e1h.FINDING_ARTIFACT_MISSING
    assert verdict["reason"], "never silently open — the reason is named"


def test_unsigned_artifact_fails_closed_without_blocking(tmp_path):
    verdict = e1h.evaluate_turn_close(
        IMPERATIVE_UTTERANCE, {"say": "…"},
        artifact_path=_unsigned_copy(tmp_path))
    assert verdict["decision"] == e1h.DECISION_UNENFORCEABLE
    assert verdict["finding"] == e1h.FINDING_UNRATIFIED
    # A turn is never blocked against a bound John has not signed.
    assert verdict["decision"] != e1h.DECISION_BLOCK


def test_altered_bound_version_fails_closed_by_name(tmp_path):
    p = _signed_copy(tmp_path, mutate=lambda t: t.replace(
        "**Bound version:** 1", "**Bound version:** 2", 1))
    verdict = e1h.evaluate_turn_close(IMPERATIVE_UTTERANCE, {"say": "…"},
                                      artifact_path=p)
    assert verdict["decision"] == e1h.DECISION_UNENFORCEABLE
    assert verdict["finding"] == e1h.FINDING_BOUND_VERSION_MISMATCH


def test_stripped_disposition_table_fails_closed_by_name(tmp_path):
    p = _signed_copy(tmp_path, mutate=lambda t: re.sub(
        r"(?m)^\|.*$", "", t))
    verdict = e1h.evaluate_turn_close(IMPERATIVE_UTTERANCE, {"say": "…"},
                                      artifact_path=p)
    assert verdict["decision"] == e1h.DECISION_UNENFORCEABLE
    assert verdict["finding"] == e1h.FINDING_ARTIFACT_ALTERED


def test_bound_payload_fails_closed_and_carries_the_questions(tmp_path):
    signed = e1h.bound_payload_for_turn(IMPERATIVE_UTTERANCE,
                                        artifact_path=_signed_copy(tmp_path))
    assert signed["enforceable"] is True and signed["signed"] is True
    assert [q["text"] for q in signed["questions"]] == [IMPERATIVE_UTTERANCE]
    unsigned = e1h.bound_payload_for_turn(
        IMPERATIVE_UTTERANCE, artifact_path=_unsigned_copy(tmp_path))
    assert unsigned["enforceable"] is False
    assert unsigned["finding"] == e1h.FINDING_UNRATIFIED
    assert unsigned["reason"], "fail closed is NAMED, never silent"


# ═════════════════════════════════════════════════════════════════════════════
# The bridge-boundary leg (chamber_e1_hook.enforce_bridge_result + wiring)
# ═════════════════════════════════════════════════════════════════════════════

def test_bridge_boundary_blocks_a_close_the_engine_leg_let_through(tmp_path):
    out = {"ok": True, "lane": "converse",
           "say": "The scan is 22 minutes in."}
    out = e1h.enforce_bridge_result(IMPERATIVE_UTTERANCE, out,
                                    artifact_path=_signed_copy(tmp_path))
    assert out["turn_blocked"] is True
    assert out["turn_close"]["decision"] == e1h.DECISION_BLOCK
    blocked = out["blocked"]
    assert blocked["finding"] == e1h.FINDING_TURN_BLOCKED
    assert blocked["held_say"] == "The scan is 22 minutes in."
    assert blocked["drawn_state"] == e1h.BLOCKED_TURN_STATE_ID
    assert 'msg steward blocked' in blocked["html"]


def test_bridge_boundary_never_blocks_under_an_unsigned_bound(tmp_path):
    out = {"ok": True, "lane": "converse", "say": "…"}
    out = e1h.enforce_bridge_result(IMPERATIVE_UTTERANCE, out,
                                    artifact_path=_unsigned_copy(tmp_path))
    assert not out.get("turn_blocked")
    # …but the verdict rides BY NAME — never silently open.
    assert out["turn_close"]["finding"] == e1h.FINDING_UNRATIFIED


def test_bridge_boundary_passes_through_acts_and_failures(tmp_path):
    act = {"ok": True, "lane": "act", "compiled": {"act": "park_that"}}
    assert "turn_close" not in e1h.enforce_bridge_result(
        IMPERATIVE_UTTERANCE, act, artifact_path=_signed_copy(tmp_path))
    fail = {"ok": False, "lane": "converse", "code": "CONVERSE_SEAT_UNREACHABLE"}
    assert "turn_close" not in e1h.enforce_bridge_result(
        IMPERATIVE_UTTERANCE, fail, artifact_path=_signed_copy(tmp_path))


def test_converse_routes_are_wired_to_the_hook():
    src = (ANCHOR / "anchor_gui.py").read_text(encoding="utf-8",
                                               errors="replace")
    converse = src[src.index("def handle_ecgberht_converse"):
                   src.index("def handle_ecgberht_high_seat_say")]
    assert '"--e1"' in converse and "_e1_bound_payload" in converse
    assert "_e1_enforce_turn_close" in converse
    high = src[src.index("def handle_ecgberht_high_seat_say"):
               src.index("def handle_ecgberht_envelope_confirm")]
    assert '"--e1"' in high and "_e1_enforce_turn_close" in high


# ═════════════════════════════════════════════════════════════════════════════
# The engine leg, JOINTLY — node runs the sibling's real hook function
# ═════════════════════════════════════════════════════════════════════════════

_NODE_DRIVER = """
import { pathToFileURL } from 'node:url';
const [modPath, casesJson] = process.argv.slice(-2);
const { enforceTurnCompletion } = await import(pathToFileURL(modPath).href);
const cases = JSON.parse(casesJson);
console.log(JSON.stringify(cases.map((c) =>
  enforceTurnCompletion(c.reply, c.e1))));
"""


def test_engine_leg_blocks_and_fails_closed_joint_with_the_python_bound(
        tmp_path):
    """THE JOINT NEGATIVE PATH: the question ids come from the committed
    PYTHON bound (never re-derived in JS); the ENGINE hook — the sibling's
    real steward-conversation.mjs, run under node — blocks the close on an
    unanswered id, closes on a valid typed reference, and fails CLOSED by
    name on an absent/unratified payload."""
    mod = cenf.ecgberht_root() / "engine" / "steward-conversation.mjs"
    assert mod.is_file(), "the sibling converse seam must exist (gate law)"
    e1_signed = e1h.bound_payload_for_turn(
        IMPERATIVE_UTTERANCE, artifact_path=_signed_copy(tmp_path))
    qid = e1_signed["questions"][0]["question_id"]
    cases = [
        {"e1": e1_signed, "reply": {"say": "…", "answer_references": []}},
        {"e1": e1_signed,
         "reply": {"say": "Yes — received in full.",
                   "answer_references": [
                       {"question_id": qid,
                        "answer_text": "Yes — all comments received."}]}},
        {"e1": None, "reply": {"say": "…"}},
        {"e1": e1h.bound_payload_for_turn(
            IMPERATIVE_UTTERANCE,
            artifact_path=_unsigned_copy(tmp_path)),
         "reply": {"say": "…"}},
    ]
    r = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_DRIVER,
         str(mod), json.dumps(cases)],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    blocked, closed, absent, unsigned = json.loads(
        r.stdout.strip().splitlines()[-1])
    assert blocked["decision"] == "block"
    assert blocked["finding"] == e1h.FINDING_TURN_BLOCKED
    assert [u["question_id"] for u in blocked["unanswered"]] == [qid]
    assert closed["decision"] == "close" and closed["finding"] is None
    assert absent["decision"] == "unenforceable"
    assert absent["finding"] == e1h.FINDING_ARTIFACT_MISSING
    assert unsigned["decision"] == "unenforceable"
    assert unsigned["finding"] == e1h.FINDING_UNRATIFIED


# ═════════════════════════════════════════════════════════════════════════════
# Telemetry — the other half of E1, proven with a zero-model-call trace
# ═════════════════════════════════════════════════════════════════════════════

def test_telemetry_injects_from_the_rehomed_emitter_zero_model_calls(
        monkeypatch):
    """The ⏱ table + campaign footer derive on the telemetry clock from the
    RE-HOMED run_pulse emitter with ZERO model involvement. The trace: every
    process-spawning seam is poisoned; the whole emitter path runs on
    injected record/cursor reads alone. (HONESTY: the ⏱-table clock
    injection has stood since chamber W7 — proven here at its seam; the
    footer clock leg lands with this wave.)"""
    def _boom(*a, **k):
        raise AssertionError(
            "a spawn/model seam was touched on the telemetry path")
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    rec = {"session_id": "s-1", "skill": "researchPrime", "step_id": "s2",
           "outcome": "running", "at": "2026-08-12T14:00:00Z",
           "transcript_tail": "noise noise\n⏱ 14:32 · wave 2/4 · 11 "
                              "sources\nnext: price orals at 102 students"}
    payload = cpulse.pulse_payload(
        "unused-folder", "s-1",
        load_record_fn=lambda folder, sid: rec,
        read_since_fn=lambda sid, cur: {"chunk": "", "cursor": cur},
        north_star_fn=lambda folder: None)
    assert payload["ok"] is True
    assert payload["latest_status"].startswith("⏱ 14:32")
    slot = cpulse.step_slot(payload)
    assert slot["state"] == cpulse.SLOT_STATUS
    assert slot["status_block"] == payload["latest_status"]
    # The banked-record consumer (the open paint) agrees by construction.
    seeded = cpulse.step_slot_from_record(rec)
    assert seeded["status_block"] == slot["status_block"]


def test_the_telemetry_clock_injects_table_and_footer_model_free():
    """The clock itself (static/project-window.js pulse poll): one
    setInterval reads ONLY the read-only pulse/deliverable projections and
    injects the ⏱ table + the campaign footer via textContent — no markup
    sink, no model route, on the clock."""
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    start = js.index("function _ecgSealStartPulsePoll")
    end = js.index("function _ecgSealOpenStatusOverlay")
    poll = js[start:end]
    assert "setInterval" in poll, "the telemetry clock"
    assert "tt.textContent = p.latest_status" in poll, "the ⏱ table leg"
    assert ".livestatus" in poll and "livedot" in poll, "the footer leg"
    assert "createTextNode" in poll
    assert "innerHTML" not in poll, "textContent-only on the clock (F5)"
    assert "/api/ecgberht/run_pulse" in poll
    assert "converse" not in poll, "zero model involvement on the clock"


# ═════════════════════════════════════════════════════════════════════════════
# V5 — the drawn blocked-turn state + the batched amendment + C9 discipline
# ═════════════════════════════════════════════════════════════════════════════

def _drawn_blocked_fragment() -> str:
    text = AMEND_W2.read_text(encoding="utf-8")
    m = re.search(r"```html\n(<div class=\"astate\"><!-- AG-BLOCKED-TURN -->"
                  r".*?)```", text, re.DOTALL)
    assert m, "the W2 gate record draws AG-BLOCKED-TURN"
    return m.group(1)


def _sigs_edges(node):
    sigs, edges = set(), set()
    cmd._collect(node, sigs, edges)
    return sigs, edges


def _find_by_classes(nodes, classes):
    stack = list(nodes)
    while stack:
        n = stack.pop(0)
        if n["classes"] == classes:
            return n
        stack[0:0] = n["children"]
    return None


def test_amendment_gate_is_prepared_batched_and_signature_aware():
    st = e1h.amendment_gate_state()
    assert st["prepared"] is True, \
        "the batched W2 amendment record must exist"
    text = AMEND_W2.read_text(encoding="utf-8")
    assert "AG-BLOCKED-TURN" in text
    assert "AG-RUNCARD-TRANSCRIPT-LINK" in text
    assert "ONE signature" in text
    # E4 template law: prose + recommendation first, the question LAST.
    assert text.rstrip().endswith("?")
    # No absolute host paths in the record.
    assert "C:\\Users" not in text and "/Users/" not in text
    # Fail-closed reader: an absent record is never claimed signed.
    gone = e1h.amendment_gate_state(AMEND_W2.parent / "no-such-gate.md")
    assert gone == {"prepared": False, "signed": False,
                    "reason": gone["reason"]}


def test_blocked_render_matches_the_drawn_amendment_fragment():
    drawn = _find_by_classes(
        cmd.parse_dom(_drawn_blocked_fragment()),
        ("blocked", "msg", "steward"))
    assert drawn is not None
    rendered = e1h.render_blocked_turn(
        {"finding": "E1-TURN-CLOSE-BLOCKED",
         "unanswered": [{"question_id": "q01-63e8debfddfa",
                         "text": e1b.T15_TRIGGER_TEXT}]},
        steward_name="Jarvis")
    roots = cmd.parse_dom(rendered)
    assert len(roots) == 1
    assert _sigs_edges(roots[0]) == _sigs_edges(drawn), \
        "the live render IS the drawn state — structure never drifts"
    # F5: hostile content stays inert through every slot (the registered
    # dom-slot row drives the full payload set in the W9 suite).
    hostile = e1h.render_blocked_turn(
        {"finding": cdl.HOSTILE_PAYLOADS[0],
         "unanswered": [{"question_id": cdl.HOSTILE_PAYLOADS[1],
                         "text": cdl.HOSTILE_PAYLOADS[2]}]},
        steward_name=cdl.HOSTILE_PAYLOADS[3])
    assert cdl.dom_injection_problems(hostile) == []


def test_c9_pin_discipline_the_repin_follows_the_signature():
    """UNSIGNED: the W1 pin still holds and the blocked state is NOT
    claimed drawn (the mockup is untouched pre-signature). SIGNED: the
    mockup carries the new states, the hash line was re-pinned (the
    hash-verified load succeeds against the NEW bytes), and the render
    DOM-diffs green against the post-amendment spec."""
    st = e1h.amendment_gate_state()
    # Hash-verified load: raises MockupPinError if mockups.html moved
    # without its gate-record re-pin — in EITHER signature state.
    mockup_text = cmd.load_signed_mockup()
    spec = cmd.spec_from_sections(
        mockup_text, (cmd.SECTION_M1, cmd.SECTION_AMENDMENTS))
    blocked_sig = ("div", ("blocked", "msg", "steward"))
    rendered = e1h.render_blocked_turn(
        {"finding": "E1-TURN-CLOSE-BLOCKED",
         "unanswered": [{"question_id": "q01-63e8debfddfa",
                         "text": e1b.T15_TRIGGER_TEXT}]})
    if st["signed"]:
        assert blocked_sig in spec["sigs"], \
            "signed ⇒ the drawn state joined the pinned mockup"
        assert cmd.diff_render(rendered, spec) == []
        assert "transcript ▸" in mockup_text
    else:
        assert blocked_sig not in spec["sigs"], \
            "pre-signature the mockup is untouched (re-pin FOLLOWS)"
        problems = cmd.diff_render(rendered, spec)
        assert problems, \
            "pre-signature the blocked state is honestly NOT mockup-drawn"


def test_the_talk_column_paints_the_blocked_state_textcontent_only():
    """The browser leg of V5: a turn_blocked converse response routes to the
    drawn blocked-turn painter (its OWN state, never an ambiguous silence),
    built with textContent-only DOM calls (F5)."""
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    assert "j.turn_blocked && j.blocked" in js, \
        "the converse response router carries the blocked branch"
    start = js.index("function _ecgRenderBlockedTurn")
    end = js.index("function _ecgConverse")
    painter = js[start:end]
    assert "turn blocked" in painter
    assert "bfind" in painter and "bqid" in painter and "bnote" in painter
    assert "innerHTML" not in painter, "textContent-only (F5)"
    assert "insertAdjacentHTML" not in painter


def test_runcard_carries_the_ordered_transcript_link_traversal_safe():
    view = {"pulse_slot": {"status_block": "⏱ 14:32 · wave 2/4",
                           "session_id": "sess-9"},
            "project_id": "proj-1", "eta": {}}
    step = {"id": "s2", "running": {"session_id": "sess-9"}}
    html_out = crail._runcard_html(view, step, None)
    assert "transcript ▸" in html_out
    assert "/artifact/proj-1?path=general/sess-9-transcript.md" in html_out
    assert cdl.dom_injection_problems(html_out) == []
    # The click-time validator allows exactly this prefix.
    assert cdl.href_allowed("/artifact/proj-1?path=general/x.md")
    # Omission is a drawn variant: no project id → no link, never broken.
    view_no_pid = dict(view, project_id=None)
    assert "transcript" not in crail._runcard_html(view_no_pid, step, None)


# ═════════════════════════════════════════════════════════════════════════════
# The acceptance oracle: all four legs present, scan re-runnable
# ═════════════════════════════════════════════════════════════════════════════

def test_e1_instrument_scan_finds_all_four_legs():
    import chamber_close_report as ccr
    scan = ccr.e1_instrument_scan()
    assert scan["bound_parser_landed"] is True
    assert scan["ratification_artifact_landed"] is True
    assert scan["turn_completion_hook_landed"] is True, \
        "the engine-seam probe finds the hook in steward-conversation.mjs"
    assert scan["w8_negative_path_test_landed"] is True
    assert "test_chamber_e1_enforcement_w8.py" \
        in scan["w8_negative_path_test_files"]
    assert scan["stack_complete"] is True
    # Re-runnable + deterministic: two builds agree byte-for-byte.
    assert ccr.build_e1_report() == ccr.build_e1_report()
    committed = ccr.E1_REPORT_PATH.read_text(encoding="utf-8")
    assert committed.count("| YES") >= 4, "all four legs read PRESENT"


def test_hook_module_is_stdlib_pure_and_path_clean():
    src = (ANCHOR / "chamber_e1_hook.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "urllib", "subprocess", "winpty",
                      "requests", "http." + "client"):
        assert forbidden not in src, \
            "the hook is model-free and offline: %r" % forbidden
    assert "C:\\Users" not in src and "/Users/" not in src
