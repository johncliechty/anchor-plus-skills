"""Compose-first directive-card TEMPLATE + the E4 template law
(steward-chamber W10, C3 — E4, wire-homing row ``compose_first``).

**The template render is NEW code; the COMPOSITION is not reimplemented.**
The fixed-slot directive card — ``stand`` / ``running``-and-doing-what /
one ``next_move`` / the ``goal_guard`` line / ``question`` LAST — fills
from:

* the RECONCILED state + PRECOMPUTED brief (``chamber_reconcile`` — the W5
  sidecar, last-writer-wins, zero model calls), and
* the WIRED composer contract (wire-homing registry row ``compose_first``:
  Ecgberht ``engine/steward-conversation.mjs :: buildStewardPrompt``'s
  COMPOSE-the-directive rule + ``parseStewardReply``'s
  ``commission_directive`` field). A parsed steward reply's composed
  directive fills the next-move slot VERBATIM; its ``asks[0]`` fills the
  question slot. This module NEVER composes narrative itself.

**The kill branch (C12, symmetric to W2's):** a composer output that cannot
fill the slots — ``wants_commission`` without a ``commission_directive``,
or a reply with no say/ask/directive at all — returns the NAMED
wire-homing HALT (:data:`KILL_BRANCH`): the wave stops and the row is
re-costed as a REWRITE by John; a silent local reimplementation of the
composition is exactly what this branch exists to make impossible.

**The E4 template law** (:func:`template_findings`): every directive/gate
card is PROSE with context + recommendation BEFORE the question and the
question as the LAST line; a bare option dialog or a clipped preview is a
NAMED failure. The CI fixture suite (tests/test_chamber_directive_w10.py)
drives this validator, and each fixture cites its row in the Stage-2
traceability matrix (``chamber/traceability-matrix.json``, owned here).

**The sweep override** (C5): while the died→sweep-card state machine holds
(``chamber_gates.overriding_next_move``), the state machine's sweep move
REPLACES any composed narrative next-move on the card — recorded on the
card, never silent.

Stdlib only; pure reads (the ONLY writes ``chamber_reconcile`` may do ride
its own sidecar contract). No model call, no spawn, no network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import chamber_reconcile as _cr

SCHEMA = "anchor-chamber-directive-card-v1"

ANCHOR_ROOT = Path(__file__).resolve().parent
TRACEABILITY_MATRIX_PATH = ANCHOR_ROOT / "chamber" / "traceability-matrix.json"
MATRIX_SCHEMA_VERSION = 1

#: The fixed template slots, in render order. QUESTION IS LAST — that is the
#: template contract, not a style preference (E4).
TEMPLATE_SLOTS = ("stand", "running", "next_move", "goal_guard", "question")

#: The template-owned default question (a FIXED string of the fixed-slot
#: template — not composed narrative) used when no steward ask is on file.
DEFAULT_QUESTION = "Proceed with this next move?"

#: The wire-homing kill branch for the compose_first row (C12): HALT +
#: re-cost as a rewrite — NEVER a silent reimplementation of composition.
KILL_BRANCH = {
    "halt": "wire-homing-kill-branch",
    "row": "compose_first",
    "action": "HALT + scoped wire-amendment to John re-costing the "
              "compose-first row (engine/steward-conversation.mjs :: "
              "buildStewardPrompt / parseStewardReply commission_directive) "
              "as a REWRITE — never a silent reimplementation (C12)",
}

ERROR_DEGRADED_BRIEF = "degraded-brief"

# ── E4 named findings ───────────────────────────────────────────────────────
E4_EMPTY_CARD = "E4-EMPTY-CARD"
E4_NO_QUESTION = "E4-NO-QUESTION"
E4_QUESTION_NOT_LAST = "E4-QUESTION-NOT-LAST"
E4_BARE_OPTION_DIALOG = "E4-BARE-OPTION-DIALOG"
E4_CLIPPED_PREVIEW = "E4-CLIPPED-PREVIEW"

#: A line that is an OPTION ROW, not prose: numbered/lettered choices,
#: checkboxes, bullet stubs, y/n toggles. A card made of these with no
#: surrounding prose is the outlawed bare option dialog.
_OPTION_ROW_RE = re.compile(
    r"^\s*(?:\(?\[?\d+[\)\].:]|\(?[a-dA-D][\).]\s|[-*•]\s|\[\s?\]|\[x\]"
    r"|y\s*/\s*n\b|yes\s*/\s*no\b|option\b)", re.IGNORECASE)

#: Minimum words for a line to count as PROSE context/recommendation.
_PROSE_MIN_WORDS = 4


# ═════════════════════════════════════════════════════════════════════════════
# The WIRED composer content (parseStewardReply contract) → slot fill
# ═════════════════════════════════════════════════════════════════════════════

def _kill(reason: str, missing=None) -> dict:
    out = {"ok": False, "reason": reason}
    out.update(KILL_BRANCH)
    if missing:
        out["missing"] = list(missing)
    return out


def composer_slot_fill(reply) -> dict:
    """Extract the card content the WIRED composer contract carries.

    ``reply`` is a parsed steward reply — either ``parseStewardReply``'s
    envelope (``{ok, reply: {...}}``) or the inner reply object. Returns
    ``{"ok": True, "next_move", "question", "say", "wants_commission"}``
    (fields None when the composer did not offer them), or the NAMED
    kill-branch HALT when the composer output cannot fill the slots.
    """
    if not isinstance(reply, dict):
        return _kill("reply-not-parsed",
                     missing=["say", "asks", "commission_directive"])
    inner = reply.get("reply") if isinstance(reply.get("reply"), dict) \
        else reply
    say = str(inner.get("say") or "").strip()
    asks = [str(a or "").strip() for a in (inner.get("asks") or [])
            if str(a or "").strip()]
    wants = inner.get("wants_commission") is True
    directive = str(inner.get("commission_directive") or "").strip()
    if wants and not directive:
        # The COMPOSE-the-directive rule went unfulfilled: the composer
        # signalled a commission but composed nothing. Kill branch — the
        # template never invents the directive in its place.
        return _kill("compose-the-directive-unfulfilled",
                     missing=["commission_directive"])
    if not (say or asks or directive):
        return _kill("composer-cannot-fill-slots",
                     missing=["say", "asks", "commission_directive"])
    return {
        "ok": True,
        "next_move": directive if (wants and directive) else None,
        "question": asks[0] if asks else None,
        "say": say or None,
        "wants_commission": wants,
    }


# ═════════════════════════════════════════════════════════════════════════════
# The fixed-slot card (filled from reconciled state + brief + wired composer)
# ═════════════════════════════════════════════════════════════════════════════

def compose_directive_card(folder=None, *, reply=None, brief=None) -> dict:
    """Fill the fixed-slot directive card.

    ``brief`` (a ``chamber_reconcile`` brief doc) may be injected for tests;
    otherwise it loads from the sidecar (cache first, else a non-persisting
    precompute — still zero model calls). ``reply`` is the parsed steward
    reply whose WIRED fields override the narrative slots. Returns the card
    (``ok: True``), the honest degraded refusal (``error:
    degraded-brief``), or the NAMED wire-homing kill-branch HALT.
    """
    if brief is None:
        if folder is None:
            raise ValueError("compose_directive_card needs folder or brief")
        brief = _cr.load_brief(folder)
        if not isinstance(brief, dict) or brief.get("error") \
                or "fields" not in brief:
            brief = _cr.precompute_brief(folder, persist=False)
    fields = brief.get("fields") or {}

    def _text(key):
        f = fields.get(key) or {}
        return (str(f.get("text")).strip()
                if f.get("text") not in (None, "") else None)

    slots = {
        "stand": _text("stand"),
        "running": _text("running"),
        "next_move": _text("next_move"),
        "goal_guard": _text("goal_guard"),
        "question": None,
    }
    sources = {
        "stand": (fields.get("stand") or {}).get("source"),
        "running": (fields.get("running") or {}).get("source"),
        "next_move": (fields.get("next_move") or {}).get("source"),
        "goal_guard": (fields.get("goal_guard") or {}).get("source"),
        "question": None,
    }

    steward_say = None
    if reply is not None:
        filled = composer_slot_fill(reply)
        if not filled.get("ok"):
            return filled  # the NAMED kill-branch HALT — never silent
        if filled.get("next_move"):
            slots["next_move"] = filled["next_move"]
            sources["next_move"] = ("steward-reply.commission_directive "
                                    "(WIRED composer, wire-homing row "
                                    "compose_first)")
        if filled.get("question"):
            slots["question"] = filled["question"]
            sources["question"] = "steward-reply.asks[0] (WIRED composer)"
        steward_say = filled.get("say")

    if not any(slots[k] for k in ("stand", "running", "next_move")):
        degraded = brief.get("degraded") or {
            "state": _cr.DEGRADED_BRIEF_STATE,
            "reason": "no-derivable-brief-basis"}
        return {"ok": False, "error": ERROR_DEGRADED_BRIEF,
                "degraded": degraded,
                "message": "no slot is derivable — the drawn degraded brief "
                           "paints instead of a synthesized card"}

    if not slots["question"]:
        slots["question"] = DEFAULT_QUESTION
        sources["question"] = "template default (fixed slot)"

    # The died→sweep-card state machine OVERRIDES any composed narrative
    # next-move (C5) — recorded on the card, never silent.
    override = None
    if folder is not None:
        try:
            import chamber_gates as _cg
            ov = _cg.overriding_next_move(folder)
        except Exception:
            ov = {"override": False}
        if ov.get("override"):
            override = {"by": "sweep-card-state-machine",
                        "finding": ov.get("finding"),
                        "state": ov.get("state"),
                        "session_id": ov.get("session_id"),
                        "overrode": slots["next_move"]}
            slots["next_move"] = ov.get("text")
            sources["next_move"] = "chamber_gates.overriding_next_move " \
                                   "(died→sweep state machine, C5)"
            slots["question"] = ov.get("question")
            sources["question"] = sources["next_move"]

    return {
        "ok": True,
        "schema": SCHEMA,
        "kind": "directive",
        "slots": slots,
        "sources": sources,
        "steward_say": steward_say,
        "override": override,
        "as_of": brief.get("as_of"),
    }


def card_text(card: dict) -> str:
    """Render the card as compose-first PROSE in fixed slot order — the
    question is the LAST line (E4). Plain text; the HTML path is the gate
    queue's escaped render, never this."""
    slots = (card or {}).get("slots") or {}
    lines = []
    if slots.get("stand"):
        lines.append("Where we stand: %s" % slots["stand"])
    if slots.get("running"):
        lines.append(str(slots["running"]))
    if (card or {}).get("steward_say"):
        lines.append(str(card["steward_say"]))
    if slots.get("next_move"):
        lines.append("The one next move: %s" % slots["next_move"])
    if slots.get("goal_guard"):
        lines.append("Goal guard: %s" % slots["goal_guard"])
    lines.append("")
    lines.append(str(slots.get("question") or DEFAULT_QUESTION))
    return "\n".join(lines)


def directive_gate_card(card: dict) -> dict:
    """The queue-ready gate card for a composed directive (enqueued via
    ``chamber_gates.enqueue_gate(kind='directive')``)."""
    return {"kind": "directive", "text": card_text(card),
            "slots": (card or {}).get("slots"),
            "override": (card or {}).get("override")}


# ═════════════════════════════════════════════════════════════════════════════
# The E4 template law (the CI fixture suite drives this validator)
# ═════════════════════════════════════════════════════════════════════════════

def _is_option_row(line: str) -> bool:
    return bool(_OPTION_ROW_RE.match(line))


def _is_prose(line: str) -> bool:
    return (not _is_option_row(line)
            and len(line.split()) >= _PROSE_MIN_WORDS)


def template_findings(text, *, require_question: bool = True) -> list:
    """Validate one rendered card against the E4 template law. Returns NAMED
    findings (empty == the card passes):

    * :data:`E4_EMPTY_CARD` — nothing rendered;
    * :data:`E4_NO_QUESTION` — the card does not END with a question;
    * :data:`E4_QUESTION_NOT_LAST` — a question line sits before other
      content (context + recommendation must PRECEDE the question);
    * :data:`E4_BARE_OPTION_DIALOG` — option rows with fewer than two prose
      lines of context/recommendation before the question;
    * :data:`E4_CLIPPED_PREVIEW` — a line ends in an ellipsis ('…'/'...'),
      i.e. the card shows a truncated preview instead of the composed prose.
    """
    findings = []
    lines = [ln.rstrip() for ln in str(text or "").splitlines()]
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return [{"finding": E4_EMPTY_CARD, "detail": "card rendered blank"}]

    for ln in nonempty:
        if ln.strip().endswith(("…", "...")):
            findings.append({"finding": E4_CLIPPED_PREVIEW,
                             "detail": "clipped line: %r" % ln.strip()[:120]})
            break

    last = nonempty[-1].strip()
    body = nonempty[:-1]
    if not last.endswith("?"):
        if require_question:
            findings.append({"finding": E4_NO_QUESTION,
                             "detail": "the last line is not a question: %r"
                                       % last[:120]})
        body = nonempty  # no terminal question: everything is body

    for ln in body:
        if ln.strip().endswith("?"):
            findings.append({"finding": E4_QUESTION_NOT_LAST,
                             "detail": "question before the end of the card: "
                                       "%r" % ln.strip()[:120]})
            break

    prose_before = sum(1 for ln in body if _is_prose(ln.strip()))
    if prose_before < 2:
        findings.append({
            "finding": E4_BARE_OPTION_DIALOG,
            "detail": "only %d prose line(s) precede the question — context "
                      "AND recommendation must come first; a bare option "
                      "dialog is outlawed" % prose_before})
    return findings


# ═════════════════════════════════════════════════════════════════════════════
# The Stage-2 traceability matrix (owned artifact; fixtures cite its rows)
# ═════════════════════════════════════════════════════════════════════════════

def load_traceability_matrix(path: Path | None = None) -> dict:
    p = Path(path) if path else TRACEABILITY_MATRIX_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def matrix_row_ids(matrix: dict | None = None) -> set:
    m = matrix if matrix is not None else load_traceability_matrix()
    return {row.get("id") for row in m.get("rows", []) if row.get("id")}


def validate_traceability_matrix(matrix: dict) -> list:
    """Living-registry law: versioned, owned, and every row falsifiably
    formed (id + the journal moment + what it maps to)."""
    problems = []
    if not isinstance(matrix, dict):
        return ["traceability matrix is not a JSON object"]
    if matrix.get("schema_version") != MATRIX_SCHEMA_VERSION:
        problems.append("schema_version missing or != %d"
                        % MATRIX_SCHEMA_VERSION)
    if not matrix.get("owner_file"):
        problems.append("owner_file missing (living-registry law)")
    rows = matrix.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append("rows missing/empty")
        return problems
    seen = set()
    for i, row in enumerate(rows):
        for key in ("id", "moment", "maps_to", "wave"):
            if not row.get(key):
                problems.append("rows[%d] missing %r" % (i, key))
        rid = row.get("id")
        if rid in seen:
            problems.append("rows[%d] duplicate id %r" % (i, rid))
        seen.add(rid)
    return problems
