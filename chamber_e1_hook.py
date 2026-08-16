"""The E1 steward TURN-COMPLETION HOOK (steward-e1 W2 — re-executes the
chamber W8 row): the Anchor side of the enforcement seam.

E1's criterion: *a steward turn structurally CANNOT close while a ratified
direct question id lacks a typed answer-reference.* The bound itself (the
deterministic question parse + the typed answer-reference schema + the F7
ratification reader) is OWNED by :mod:`chamber_e1_bound` — this module never
re-implements it. What lives here is the HOOK: the turn-close evaluation the
W2-proven converse seam enforces through, at BOTH legs of that seam:

* **the engine leg** — ``engine/steward-conversation.mjs ::
  enforceTurnCompletion`` (the Ecgberht sibling) blocks the close in-engine;
  the deterministic question ids it enforces are computed HERE
  (:func:`bound_payload_for_turn`) and ride the bridge as ``--e1`` — the
  bound is parsed once, in the committed Python owner, never re-derived by
  the JS side;
* **the bridge-boundary leg** — ``anchor_gui.handle_ecgberht_converse``
  re-evaluates the returned turn through :func:`enforce_bridge_result`, so a
  close initiated by a bridge-boundary caller is blocked identically (the
  chamber W2 seam-proof's own acceptance wording).

RATIFICATION HONESTY (the F7 law, verbatim from the artifact): enforcement
may switch on ONLY against a bound John has signed. A missing, unsigned, or
altered F7 artifact makes the hook fail CLOSED — the verdict carries the
NAMED finding (:data:`FINDING_ARTIFACT_MISSING` / :data:`FINDING_UNRATIFIED`
/ :data:`FINDING_BOUND_VERSION_MISMATCH` / :data:`FINDING_ARTIFACT_ALTERED`)
and is never a silent clean pass — while a steward turn is never BLOCKED
against a bound John has not signed ("an unenforceable bound never degrades
to permissive" AND "a steward turn is never blocked against a bound you have
not signed" — both hold, because fail-closed here binds the VERDICT, and the
blocking decision exists only under a signature).

THE DRAWN REFUSAL (V5): a blocked close renders the AG-BLOCKED-TURN state
(:func:`render_blocked_turn`) — the E1 refusal drawn DISTINCT from "are you
working", batched for John's one signature in
``chamber/MOCKUP-AMENDMENT-GATE-W2.md`` together with the ordered
transcript-link row (TILE-RETIREMENT-GATE decision 1). The C9 re-pin follows
that signature; it never precedes it.

Stdlib only. Read-only (the ratification/amendment reads are the only file
touches; no model, no network, no PTY, no spawn).
"""
from __future__ import annotations

import re
from html import escape as _esc
from pathlib import Path

import chamber_e1_bound as _bound

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"

SCHEMA_VERSION = 1

#: The W2 batched mockup-amendment gate record (V5 blocked-turn state + the
#: ordered transcript-link row — ONE signature). Read for its signed state;
#: absent reads UNSIGNED (fail closed, never a claimed signature).
AMENDMENT_GATE_W2_PATH = CHAMBER_DIR / "MOCKUP-AMENDMENT-GATE-W2.md"

#: Turn-close decisions.
DECISION_CLOSE = "close"                    # enforced pass — every id discharged
DECISION_BLOCK = "block"                    # structurally blocked, named finding
DECISION_UNENFORCEABLE = "unenforceable"    # fail CLOSED — named, never silent

#: Named findings (the gate vocabulary — a refusal is always attributable).
FINDING_TURN_BLOCKED = "E1-TURN-CLOSE-BLOCKED"
FINDING_UNRATIFIED = _bound.FINDING_UNRATIFIED
FINDING_ARTIFACT_MISSING = _bound.FINDING_ARTIFACT_MISSING
FINDING_BOUND_VERSION_MISMATCH = "E1-BOUND-VERSION-MISMATCH"
FINDING_ARTIFACT_ALTERED = "E1-F7-ARTIFACT-ALTERED"

#: The drawn V5 state id (the mockup amendment's AG row).
BLOCKED_TURN_STATE_ID = "AG-BLOCKED-TURN"

_SIGNED_LINE_RE = re.compile(r"^\*\*Signed by:\*\*\s*John\b", re.MULTILINE)
_UNSIGNED_MARK = "UNSIGNED"


# ═════════════════════════════════════════════════════════════════════════════
# The bound payload (Anchor computes; the engine seam enforces)
# ═════════════════════════════════════════════════════════════════════════════

def bound_payload_for_turn(utterance, artifact_path=None) -> dict:
    """The ``--e1`` payload one steward turn carries over the bridge: the
    F7 ratification state (fail closed) + the deterministic question ids the
    committed bound emits for John's utterance. The JS hook enforces ONLY
    what this payload says is enforceable — it never re-derives the bound.
    """
    ratification = _bound.ratification_state(artifact_path)
    enforceable, finding, reason = _enforceability(ratification)
    questions = _bound.parse_direct_questions(utterance)
    out = {
        "schema_version": SCHEMA_VERSION,
        "bound_version": _bound.BOUND_VERSION,
        "signed": bool(ratification.get("signed")),
        "enforceable": enforceable,
        "questions": questions,
    }
    if not enforceable:
        out["finding"] = finding
        out["reason"] = reason
    return out


def _enforceability(ratification) -> tuple:
    """``(enforceable, finding, reason)`` — the fail-closed reading of the
    F7 artifact. Missing / unsigned / version-altered / table-stripped each
    yield a NAMED finding; only a signed, version-matching artifact whose
    disposition table still parses is enforceable."""
    r = ratification if isinstance(ratification, dict) else {}
    if not r.get("prepared"):
        return (False, FINDING_ARTIFACT_MISSING,
                str(r.get("reason") or "the F7 ratification artifact is "
                    "absent — fail closed by name, never silently open"))
    if not r.get("signed"):
        return (False, FINDING_UNRATIFIED,
                str(r.get("reason") or "the E1 bound is prepared but NOT "
                    "ratified — enforcement fails closed until John's "
                    "signature is on disk"))
    if r.get("bound_version") != _bound.BOUND_VERSION:
        return (False, FINDING_BOUND_VERSION_MISMATCH,
                "the F7 artifact records bound version %r but the committed "
                "bound is v%d — the signature does not cover this bound "
                "(fail closed; a bound widens only through a NEW F7 "
                "signature)" % (r.get("bound_version"),
                                _bound.BOUND_VERSION))
    if not r.get("dispositions"):
        return (False, FINDING_ARTIFACT_ALTERED,
                "the F7 artifact carries a signature but its fixture "
                "disposition table is gone — the artifact was altered after "
                "preparation; fail closed, never permissive")
    return (True, None, None)


# ═════════════════════════════════════════════════════════════════════════════
# Typed answer-references (validated through the bound's own schema)
# ═════════════════════════════════════════════════════════════════════════════

def _collect_answer_references(result) -> list:
    """Every VALID typed answer-reference a converse result carries — at the
    top level or under its ``reply`` — validated through
    ``chamber_e1_bound.answer_reference_problems``. A seat-provided partial
    ``{question_id, answer_text}`` is completed with the machinery-owned
    fields (``schema_version`` / ``answered_in``); an entry that still fails
    validation is DROPPED (an invalid reference must never look answered)."""
    if not isinstance(result, dict):
        return []
    raw = result.get("answer_references")
    if raw is None and isinstance(result.get("reply"), dict):
        raw = result["reply"].get("answer_references")
    if raw is None and isinstance(result.get("blocked"), dict):
        raw = result["blocked"].get("answer_references")
    if raw is None and isinstance(result.get("turn_close"), dict):
        # The engine leg's verdict carries the references it VALIDATED
        # (turn_close.answered) — the bridge boundary re-validates their
        # typed shape + coverage here rather than trusting the claim.
        raw = result["turn_close"].get("answered")
    refs = []
    for entry in (raw if isinstance(raw, (list, tuple)) else []):
        if not isinstance(entry, dict):
            continue
        ref = {
            "schema_version": entry.get("schema_version",
                                        _bound.SCHEMA_VERSION),
            "question_id": str(entry.get("question_id") or "").strip(),
            "answered_in": str(entry.get("answered_in")
                               or "steward-reply").strip(),
            "answer_text": str(entry.get("answer_text") or "").strip(),
        }
        if not _bound.answer_reference_problems(ref):
            refs.append(ref)
    return refs


# ═════════════════════════════════════════════════════════════════════════════
# The turn-close evaluation (the hook itself)
# ═════════════════════════════════════════════════════════════════════════════

def evaluate_turn_close(utterance, result, ratification=None,
                        artifact_path=None) -> dict:
    """THE TURN-COMPLETION HOOK. Evaluate one steward turn's attempt to
    close: John's ``utterance`` parsed through the committed bound, the
    steward ``result``'s typed answer-references validated against it.

    Returns ``{decision, enforced, finding, reason, unanswered, answered}``:

    * ``unenforceable`` — the F7 artifact is missing/unsigned/altered. FAIL
      CLOSED: the verdict carries the named finding and is never a clean
      pass; the turn is NOT blocked (a turn is never blocked against a bound
      John has not signed).
    * ``block`` — the bound is ratified and an open question id lacks a
      valid typed answer-reference: the close is structurally refused with
      :data:`FINDING_TURN_BLOCKED` naming every unanswered id.
    * ``close`` — the bound is ratified and every open id is discharged.
    """
    if ratification is None:
        ratification = _bound.ratification_state(artifact_path)
    enforceable, finding, reason = _enforceability(ratification)
    if not enforceable:
        return {"decision": DECISION_UNENFORCEABLE, "enforced": False,
                "finding": finding, "reason": reason,
                "unanswered": [], "answered": []}
    questions = _bound.parse_direct_questions(utterance)
    refs = _collect_answer_references(result)
    answered_ids = {r["question_id"] for r in refs}
    unanswered = [{"question_id": q["question_id"], "text": q["text"],
                   "kind": q["kind"], "rule": q["rule"]}
                  for q in questions
                  if q["question_id"] not in answered_ids]
    if unanswered:
        return {"decision": DECISION_BLOCK, "enforced": True,
                "finding": FINDING_TURN_BLOCKED,
                "reason": "a ratified direct question id lacks a typed "
                          "answer-reference — the engine refuses to close "
                          "this turn (E1, per the F7-signed bound)",
                "unanswered": unanswered, "answered": refs}
    return {"decision": DECISION_CLOSE, "enforced": True,
            "finding": None, "reason": None,
            "unanswered": [], "answered": refs}


def enforce_bridge_result(utterance, out, artifact_path=None) -> dict:
    """The BRIDGE-BOUNDARY leg of the seam: re-evaluate the bridge's
    converse result and structurally block the close when the engine leg
    did not (a close initiated by a bridge-boundary caller is blocked
    identically — the W2 seam-proof's own acceptance wording).

    Every converse-lane result gains a ``turn_close`` verdict (never
    silently open); a blocked one is rewritten into the drawn refusal
    payload the chamber paints (V5, :func:`render_blocked_turn`)."""
    if not isinstance(out, dict):
        return out
    if not out.get("ok") or out.get("lane") != "converse":
        return out
    verdict = evaluate_turn_close(utterance, out,
                                  artifact_path=artifact_path)
    out["turn_close"] = verdict
    if verdict["decision"] != DECISION_BLOCK:
        # An unenforceable bound rides the result BY NAME — the state is
        # loud, the turn proceeds (never blocked against an unsigned bound).
        return out
    blocked = out.get("blocked") if isinstance(out.get("blocked"), dict) \
        else {}
    blocked.setdefault("finding", verdict["finding"])
    blocked["unanswered"] = verdict["unanswered"]
    blocked.setdefault("message",
                       "The engine refused to close this turn: a direct "
                       "question from John still lacks a typed "
                       "answer-reference.")
    if not out.get("turn_blocked") and isinstance(out.get("say"), str):
        # The engine leg let this close through (an older bridge, or a
        # boundary caller that skipped it) — hold the reply here instead.
        blocked.setdefault("held_say", out.get("say"))
    blocked["drawn_state"] = BLOCKED_TURN_STATE_ID
    blocked["drawn_signed"] = amendment_gate_state().get("signed", False)
    blocked["html"] = render_blocked_turn(blocked)
    out["turn_blocked"] = True
    out["blocked"] = blocked
    out["say"] = blocked["message"]
    return out


# ═════════════════════════════════════════════════════════════════════════════
# V5 — the drawn blocked-turn state (AG-BLOCKED-TURN)
# ═════════════════════════════════════════════════════════════════════════════

def render_blocked_turn(blocked, steward_name="the steward") -> str:
    """The DRAWN E1 refusal state, exactly as batched for John's signature
    in ``chamber/MOCKUP-AMENDMENT-GATE-W2.md`` (AG-BLOCKED-TURN): a variant
    of the locked ``msg steward`` element carrying the named finding and
    every unanswered question — so the cure never looks like the disease
    ("are you working"). Every slot value is escaped; structure is never
    invented beyond the drawn fragment."""
    b = blocked if isinstance(blocked, dict) else {}
    finding = str(b.get("finding") or FINDING_TURN_BLOCKED)
    rows = []
    for q in (b.get("unanswered") or []):
        if not isinstance(q, dict):
            continue
        rows.append(
            '<div class="bq">“%s” <span class="bqid">%s</span></div>'
            % (_esc(str(q.get("text") or ""), quote=True),
               _esc(str(q.get("question_id") or ""), quote=True)))
    return (
        '<div class="msg steward blocked">'
        '<div class="who">⛔ %s — turn blocked</div>'
        '<div class="bfind">%s · a direct question from John lacks a typed '
        'answer-reference</div>'
        '%s'
        '<div class="bnote">The engine refused to close this turn — the E1 '
        'refusal state, drawn distinct from “are you working”.</div>'
        '</div>'
    ) % (_esc(str(steward_name), quote=True), _esc(finding, quote=True),
         "".join(rows))


def amendment_gate_state(path=None) -> dict:
    """The W2 batched mockup-amendment gate's honest state (the SAME signed
    convention the F7 and tile gates read). Fails closed: an absent record
    reads ``prepared: False, signed: False`` — the drawn state is never
    claimed signed before John's signature is on disk."""
    p = Path(path) if path else AMENDMENT_GATE_W2_PATH
    if not p.is_file():
        return {"prepared": False, "signed": False,
                "reason": "the W2 amendment gate record is absent: "
                          "chamber/%s" % p.name}
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    signed = bool(_SIGNED_LINE_RE.search(text)) \
        and _UNSIGNED_MARK not in first_line
    out = {"prepared": True, "signed": signed}
    if not signed:
        out["reason"] = ("the batched mockup amendment (V5 blocked-turn + "
                         "the ordered transcript-link row) is PREPARED but "
                         "awaits John's ONE signature; the C9 re-pin "
                         "follows the signature, never precedes it")
    return out
