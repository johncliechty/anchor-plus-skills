# W1 (steward-e1 2026-08-12) — the E1 bound: deterministic question parse,
# the V1 fixture set, and the F7 ratification artifact. Re-executes the
# chamber W3 row the original build never landed (E1-ENFORCEMENT-REPORT).
#
# AUTH-ON: not-a-surface
#
# The law under test: the parse is deterministic and model-free (parse the
# same text twice -> identical per-question ids); every V1 fixture row is
# IN-BOUND (the bound fires) or KNOWN-MISS named in the F7 artifact — a row
# that is neither is a gate failure BY NAME, never a silent skip; and the
# bound is PREPARED but UNRATIFIED until John's signature exists ON DISK
# (fails closed, never permissive).
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import chamber_e1_bound as e1  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]

MIXED_TEXT = (
    "The syllabus deck is parked in the shared folder. "
    "Did you get my comments on slide twelve? "
    "confirm you got comments on the whole deck\n"
    "The rest reads fine, no rush on the appendix. "
    "Should I hold the send until Thursday?"
)


# ── Determinism (parse-twice -> identical ids) ──────────────────────────────

def test_parse_twice_yields_identical_ids():
    first = e1.parse_direct_questions(MIXED_TEXT)
    second = e1.parse_direct_questions(MIXED_TEXT)
    assert first, "the mixed fixture text carries direct questions"
    assert first == second, "the parse must be deterministic"
    assert [q["question_id"] for q in first] \
        == [q["question_id"] for q in second]
    for q in first:
        assert re.match(r"^q\d{2,}-[0-9a-f]{12}$", q["question_id"])
        assert q["kind"] in e1.QUESTION_KINDS


def test_terminal_qmark_sentences_and_only_those_emit_among_prose():
    qs = e1.parse_direct_questions(MIXED_TEXT)
    # Exactly three: two terminal-'?' sentences + the T+15 imperative.
    assert len(qs) == 3
    assert [q["kind"] for q in qs] == [e1.KIND_TERMINAL_QMARK,
                                       e1.KIND_IMPERATIVE_ASK,
                                       e1.KIND_TERMINAL_QMARK]
    assert qs[1]["text"] == e1.T15_TRIGGER_TEXT
    assert qs[1]["rule"] == "confirm-receipt"
    # Plain statements emit nothing at all.
    assert e1.parse_direct_questions(
        "The deck is parked in the shared folder. The rest reads fine.") \
        == []


def test_explicit_ask_affordance_emits_from_every_reply_shape():
    ask = "Should the orals rubric go out before the syllabus deck?"
    envelope = {"ok": True, "reply": {"say": "Deck reviewed.",
                                      "asks": [ask, "", None]}}
    inner = {"say": "Deck reviewed.", "asks": [ask]}
    bare = [ask]
    for shape in (envelope, inner, bare):
        qs = e1.questions_from_asks(shape)
        assert len(qs) == 1, "blank/None entries never mint a question"
        assert qs[0]["kind"] == e1.KIND_EXPLICIT_ASK
        assert qs[0]["text"] == ask
    assert e1.questions_from_asks({"say": "no asks"}) == []
    assert e1.questions_from_asks(None) == []


# ── The V1 fixture set against the committed bound ──────────────────────────

def _rows():
    return e1.load_fixtures()["rows"]


def test_every_in_bound_fixture_row_fires():
    in_bound = [r for r in _rows() if r["label"] == e1.LABEL_IN_BOUND]
    assert in_bound, "the V1 set carries IN-BOUND rows"
    for row in in_bound:
        assert e1.fixture_fires(row), \
            "IN-BOUND row %r must fire" % row["id"]


def test_the_named_t15_trigger_rides_the_set_verbatim_and_fires():
    row = next(r for r in _rows() if r["id"] == e1.T15_FIXTURE_ID)
    assert row["text"] == e1.T15_TRIGGER_TEXT, \
        "the reference journal's T+15 trigger is a NAMED, VERBATIM fixture"
    assert row["label"] == e1.LABEL_IN_BOUND
    fired = e1.fixture_fires(row)
    assert fired and fired[0]["rule"] == "confirm-receipt"


def test_known_miss_rows_stay_silent_and_are_named_in_the_artifact():
    artifact = e1.RATIFICATION_PATH.read_text(encoding="utf-8")
    dispositions = e1.artifact_dispositions(artifact)
    misses = [r for r in _rows() if r["label"] == e1.LABEL_KNOWN_MISS]
    assert misses, "the honest miss list is not empty at v1"
    for row in misses:
        assert not e1.fixture_fires(row), \
            "KNOWN-MISS row %r must not fire (else the miss list is stale)" \
            % row["id"]
        assert dispositions.get(row["id"]) == e1.LABEL_KNOWN_MISS, \
            "every miss is put to John BY NAME in the F7 artifact"


def test_bound_problems_green_on_the_committed_fixtures_and_artifact():
    assert e1.bound_problems() == []


def test_silent_out_of_bound_row_is_a_gate_failure_by_name():
    fixtures = e1.load_fixtures()
    fixtures["rows"] = list(fixtures["rows"]) + [
        # Neither IN-BOUND nor KNOWN-MISS: the forbidden third state.
        {"id": "rogue-unlabeled-row", "label": "MAYBE",
         "text": "did you get the thing"},
        # Labeled fine but absent from the artifact's disposition table.
        {"id": "rogue-unrecorded-row", "label": e1.LABEL_KNOWN_MISS,
         "text": "deck comments any good"},
    ]
    findings = e1.bound_problems(fixtures=fixtures)
    by_row = {(p["finding"], p["row"]) for p in findings}
    assert (e1.FINDING_SILENT_OUT_OF_BOUND, "rogue-unlabeled-row") in by_row
    assert (e1.FINDING_SILENT_OUT_OF_BOUND, "rogue-unrecorded-row") in by_row


def test_in_bound_row_the_bound_misses_is_named_not_smoothed():
    fixtures = e1.load_fixtures()
    fixtures["rows"] = list(fixtures["rows"]) + [
        {"id": "rogue-claimed-in-bound", "label": e1.LABEL_IN_BOUND,
         "text": "the appendix is fine as written"},
    ]
    findings = e1.bound_problems(fixtures=fixtures)
    assert any(p["finding"] == e1.FINDING_IN_BOUND_NOT_FIRING
               and p["row"] == "rogue-claimed-in-bound"
               for p in findings)


def test_artifact_may_not_claim_rows_the_set_does_not_carry():
    artifact = e1.RATIFICATION_PATH.read_text(encoding="utf-8")
    artifact += "\n| phantom-row | IN-BOUND | invented |\n"
    findings = e1.bound_problems(artifact_text=artifact)
    assert any(p["finding"] == e1.FINDING_ARTIFACT_UNKNOWN_ROW
               and p["row"] == "phantom-row"
               for p in findings)


# ── The typed answer-reference schema ───────────────────────────────────────

def test_answer_reference_round_trip_on_a_parsed_id():
    qid = e1.parse_direct_questions(e1.T15_TRIGGER_TEXT)[0]["question_id"]
    ref = e1.make_answer_reference(
        qid, "steward-turn:demo-7",
        "Yes — comments on all 40 slides received and filed.")
    assert e1.answer_reference_problems(ref) == []
    assert sorted(ref) == sorted(e1.ANSWER_REFERENCE_FIELDS)


def test_answer_reference_defects_are_each_named():
    assert e1.answer_reference_problems("not-a-dict") \
        == ["answer-reference is not a dict"]
    bad = {"schema_version": 99, "question_id": "not-an-id",
           "answered_in": "", "answer_text": "   "}
    problems = e1.answer_reference_problems(bad)
    joined = " | ".join(problems)
    assert "schema_version" in joined
    assert "question_id" in joined
    assert "answered_in" in joined
    assert "answer_text" in joined
    with pytest.raises(ValueError):
        e1.make_answer_reference("bogus", "", "")


# ── The F7 ratification artifact (prepared, complete, UNSIGNED) ─────────────

def test_ratification_artifact_is_prepared_complete_and_coherent():
    # W1 shipped this artifact UNSIGNED and halted for John; he ratified
    # bound v1 as drawn on 2026-08-13. Signed-ness is therefore JOHN'S
    # state, not an invariant of the file — asserting it stays False would
    # encode "never ratified" as a law. What IS invariant: the record is
    # prepared, carries the current bound version, disposes of EVERY
    # fixture row, and its signed/finding pair is coherent in BOTH
    # directions. The flip itself (and fail-closed on absent/half-signed)
    # is proven on temp copies by the next test.
    state = e1.ratification_state()
    assert state["prepared"] is True
    if state["signed"]:
        assert "finding" not in state, \
            "a signed record carries no unratified finding"
    else:
        assert state["finding"] == e1.FINDING_UNRATIFIED
    assert state["bound_version"] == e1.BOUND_VERSION
    # Every fixture row has a disposition — none silent.
    row_ids = {r["id"] for r in _rows()}
    assert set(state["dispositions"]) == row_ids


def _unsigned_base() -> str:
    """The committed artifact rewound to its UNSIGNED shape.

    The cases below used to be built by mutating the committed text on the
    assumption it was unsigned. John ratified bound v1 on 2026-08-13, so
    that assumption is now false and the fixtures it built were silently
    degenerate (every case came out signed). Deriving an explicit unsigned
    base makes all four cases hold whichever way the live record sits.
    """
    text = e1.RATIFICATION_PATH.read_text(encoding="utf-8")
    text = re.sub(r"^\*\*Signed by:\*\*.*$",
                  "**Signed by:** (awaiting John — E1 bound ratification, F7)",
                  text, count=1, flags=re.MULTILINE)
    head, nl, rest = text.partition("\n")
    if " — UNSIGNED" not in head:
        head += " — UNSIGNED"
    return head + nl + rest


def test_signature_flip_is_recognized_and_absence_fails_closed(tmp_path):
    base = _unsigned_base()
    # The UNSIGNED base itself fails closed by name.
    u = tmp_path / "unsigned.md"
    u.write_text(base, encoding="utf-8")
    ustate = e1.ratification_state(path=u)
    assert ustate["prepared"] is True and ustate["signed"] is False
    assert ustate["finding"] == e1.FINDING_UNRATIFIED
    # A fully signed record (signature line AND headline) is recognized.
    signed_text = base.replace(
        "**Signed by:** (awaiting John — E1 bound ratification, F7)",
        "**Signed by:** John — 2026-08-13").replace(" — UNSIGNED", "", 1)
    p = tmp_path / "E1-BOUND-RATIFICATION.md"
    p.write_text(signed_text, encoding="utf-8")
    state = e1.ratification_state(path=p)
    assert state["signed"] is True and "finding" not in state
    # A HALF-signed record (line signed, headline still UNSIGNED) is
    # unsigned — fails closed, mirroring the tile-gate convention.
    half = tmp_path / "half.md"
    half.write_text(base.replace(
        "**Signed by:** (awaiting John — E1 bound ratification, F7)",
        "**Signed by:** John — 2026-08-13"), encoding="utf-8")
    assert e1.ratification_state(path=half)["signed"] is False
    # An absent artifact is a NAMED refusal, never permissive.
    gone = e1.ratification_state(path=tmp_path / "absent.md")
    assert gone["prepared"] is False and gone["signed"] is False
    assert gone["finding"] == e1.FINDING_ARTIFACT_MISSING


# ── Purity + the instrument scan (the acceptance oracle) ────────────────────

def test_parser_module_is_stdlib_pure_and_path_clean():
    src = (ANCHOR / "chamber_e1_bound.py").read_text(encoding="utf-8")
    # The HTTP-surface token is assembled by concatenation so THIS file
    # (tagged not-a-surface) never carries it as a literal — the same
    # convention the w3 coverage-rule suite uses for its own fixtures.
    for forbidden in ("import socket", "urllib", "subprocess", "winpty",
                      "requests", "http." + "client"):
        assert forbidden not in src, \
            "the E1 bound is model-free and offline: %r" % forbidden
    assert "C:\\Users" not in src and "/Users/" not in src


def test_e1_instrument_scan_finds_the_wave1_legs():
    # The oracle that recorded the original absence must now find the W1
    # legs mechanically (the W2 legs are asserted by Wave 2, not here).
    import chamber_close_report as ccr
    scan = ccr.e1_instrument_scan()
    assert scan["bound_parser_landed"] is True
    assert scan["ratification_artifact_landed"] is True
    assert "E1-BOUND-RATIFICATION.md" in scan["ratification_artifact_files"]
