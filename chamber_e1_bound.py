"""The E1 bound (steward-e1 W1 — re-executes the chamber W3 row): the
deterministic, model-free direct-question parse, the typed
answer-reference schema those question ids are discharged by, and the F7
ratification reader Wave 2's turn-completion hook enforces through.

THE BOUND (v1) — three legs, all deterministic, zero model involvement:

* **Leg A — terminal-'?' sentences.** Any sentence whose terminal
  punctuation run carries a ``?`` (trailing closing quotes/brackets ride
  along) is a direct question.
* **Leg B — the explicit ask affordance.** Every non-empty entry of a
  steward reply's ``asks[]`` slot (the same shape
  ``chamber_directive.composer_slot_fill`` reads: the full envelope, the
  inner reply object, or a bare list) is a direct question.
* **Leg C — the committed imperative-ask rules (the V1 amendment).**
  Imperative request forms carrying NO question mark ("confirm you
  got…", "tell me…", "did you get…", "can you please…") anchor on the
  committed prefix rules below AFTER the committed leading-filler strip.
  The reference failure this leg exists for is the journal's verbatim
  T+15 trigger: ``confirm you got comments on the whole deck``.

The bound is COMMITTED, never tuned at runtime: it only widens through a
NEW F7 amendment (bound v2) John ratifies — never by NLU, which E1's own
criterion (zero model involvement) forbids. Every V1 fixture row is
either IN-BOUND (the bound fires) or a KNOWN-MISS named in the F7
artifact for John's signature; a row that is neither is a gate failure
by name (:data:`FINDING_SILENT_OUT_OF_BOUND`), enforced by
:func:`bound_problems`.

Determinism: :func:`parse_direct_questions` is pure text -> data — no
clock, no randomness, no model, no network, no PTY, no filesystem I/O —
so the same text yields the identical per-question id list on every run.

Ratification honesty: enforcement (the Wave-2 hook) may switch on ONLY
against a bound John has signed. :func:`ratification_state` fails
CLOSED — an absent or unsigned artifact is :data:`FINDING_UNRATIFIED` /
:data:`FINDING_ARTIFACT_MISSING`, never a permissive default. The
signature is recorded in the F7 artifact on disk, never in chat.

Stdlib only. Read-only (the parse path touches no file at all).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"

#: The F7 NS-amendment artifact recording the bound + John's signature.
RATIFICATION_PATH = CHAMBER_DIR / "E1-BOUND-RATIFICATION.md"

#: The V1 fixture set of record (every row IN-BOUND or KNOWN-MISS — no
#: third state; :func:`bound_problems` enforces that by name).
FIXTURES_PATH = (ANCHOR_ROOT / "tests" / "fixtures" / "chamber"
                 / "e1-bound-fixtures.json")

BOUND_VERSION = 1
SCHEMA_VERSION = 1
OWNER_FILE = "chamber_e1_bound.py"

LABEL_IN_BOUND = "IN-BOUND"
LABEL_KNOWN_MISS = "KNOWN-MISS"

KIND_TERMINAL_QMARK = "terminal-question-mark"
KIND_IMPERATIVE_ASK = "imperative-ask"
KIND_EXPLICIT_ASK = "explicit-ask"
QUESTION_KINDS = (KIND_TERMINAL_QMARK, KIND_IMPERATIVE_ASK,
                  KIND_EXPLICIT_ASK)

#: Named findings — a gate failure is always attributable.
FINDING_SILENT_OUT_OF_BOUND = "E1-SILENT-OUT-OF-BOUND"
FINDING_IN_BOUND_NOT_FIRING = "E1-IN-BOUND-NOT-FIRING"
FINDING_KNOWN_MISS_FIRES = "E1-KNOWN-MISS-ACTUALLY-FIRES"
FINDING_DISPOSITION_MISMATCH = "E1-ARTIFACT-DISPOSITION-MISMATCH"
FINDING_ARTIFACT_UNKNOWN_ROW = "E1-ARTIFACT-UNKNOWN-ROW"
FINDING_FIXTURES_MALFORMED = "E1-FIXTURES-MALFORMED"
FINDING_T15_FIXTURE_MISSING = "E1-NAMED-T15-FIXTURE-MISSING"
FINDING_ARTIFACT_MISSING = "E1-F7-ARTIFACT-MISSING"
FINDING_UNRATIFIED = "E1-BOUND-UNRATIFIED"

#: The reference journal's verbatim T+15 trigger (V1: a NAMED fixture —
#: the Stage-2 Fable-driver reference session's walked-away-from ask).
T15_FIXTURE_ID = "t15-confirm-whole-deck"
T15_TRIGGER_TEXT = "confirm you got comments on the whole deck"

#: Leading filler tokens dictation commonly prepends; stripped (with an
#: optional trailing comma) before the imperative rules anchor. Committed
#: — part of the bound, never tuned at runtime.
LEADING_FILLER = ("okay", "ok", "hey", "so", "um", "uh", "and", "also",
                  "now", "please")

#: The V1 imperative-ask prefix rules (bound v1), applied AFTER the
#: filler strip, each anchored at the start of the sentence. Committed —
#: the bound only widens through a NEW F7 amendment, never by tuning.
IMPERATIVE_ASK_RULES = (
    ("confirm-receipt", re.compile(r"^confirm\b")),
    ("tell-me", re.compile(r"^tell\s+me\b")),
    ("let-me-know", re.compile(r"^let\s+me\s+know\b")),
    ("did-you", re.compile(r"^did\s+you\b")),
    ("can-you", re.compile(r"^(?:can|could|would|will)\s+you\b")),
)

_FILLER_RE = re.compile(
    r"^(?:%s)\b,?\s+" % "|".join(sorted(LEADING_FILLER, key=len,
                                        reverse=True)))
_SEGMENT_RE = re.compile(r"[^.!?\n]*[.!?]+[\"'”’)\]]*"
                         r"|[^.!?\n]+")
_TERMINAL_QMARK_RE = re.compile(r"\?[\"'”’)\]]*$")
_QUESTION_ID_RE = re.compile(r"^q\d{2,}-[0-9a-f]{12}$")


# ═════════════════════════════════════════════════════════════════════════════
# The parse (legs A + C over text; leg B over the ask affordance)
# ═════════════════════════════════════════════════════════════════════════════

def split_sentences(text) -> list:
    """Deterministic sentence segmentation (stdlib; no model). A sentence
    is a maximal run without terminal punctuation plus its terminator run
    (trailing closing quotes/brackets ride along); newlines also split.
    Segments with no word character are dropped."""
    out = []
    for raw in _SEGMENT_RE.findall(str(text or "").replace("\r\n", "\n")):
        s = raw.strip()
        if s and re.search(r"\w", s):
            out.append(s)
    return out


def _imperative_rule(sentence: str):
    """The committed rule id that anchors this sentence, or None.
    Lowercase, strip leading punctuation/quotes, strip the committed
    leading-filler tokens, then try each committed prefix rule in order."""
    s = str(sentence or "").lower().strip()
    s = s.lstrip("\"'“”‘’([{ \t")
    while True:
        m = _FILLER_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    for rule_id, rx in IMPERATIVE_ASK_RULES:
        if rx.search(s):
            return rule_id
    return None


def question_id(ordinal, sentence) -> str:
    """Deterministic per-question id: the 1-based ordinal within its
    parse + a content digest of the whitespace/case-normalized sentence.
    Stable across runs by construction (no clock, no randomness)."""
    norm = " ".join(str(sentence or "").lower().split())
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
    return "q%02d-%s" % (int(ordinal), digest)


def parse_direct_questions(text) -> list:
    """THE E1 BOUND over free text (legs A + C): terminal-'?' sentences
    and the committed imperative-ask rules. Pure text -> data (zero
    model / network / PTY / filesystem I/O). Each question:
    ``{question_id, ordinal, kind, rule, text}`` — parse the same text
    twice and the id lists are identical."""
    questions = []
    for sentence in split_sentences(text):
        if _TERMINAL_QMARK_RE.search(sentence):
            kind, rule = KIND_TERMINAL_QMARK, None
        else:
            rule = _imperative_rule(sentence)
            if not rule:
                continue
            kind = KIND_IMPERATIVE_ASK
        ordinal = len(questions) + 1
        questions.append({
            "question_id": question_id(ordinal, sentence),
            "ordinal": ordinal,
            "kind": kind,
            "rule": rule,
            "text": sentence,
        })
    return questions


def questions_from_asks(reply_or_asks) -> list:
    """THE E1 BOUND over the explicit ask affordance (leg B): the steward
    reply's ``asks[]`` slot. Accepts the full ``{ok, reply: {...}}``
    envelope, the inner reply object, or a bare list of ask strings —
    the same shapes ``chamber_directive.composer_slot_fill`` reads."""
    if isinstance(reply_or_asks, (list, tuple)):
        asks = list(reply_or_asks)
    elif isinstance(reply_or_asks, dict):
        inner = reply_or_asks.get("reply") \
            if isinstance(reply_or_asks.get("reply"), dict) \
            else reply_or_asks
        asks = list(inner.get("asks") or [])
    else:
        asks = []
    questions = []
    for a in asks:
        s = str(a or "").strip()
        if not s:
            continue
        ordinal = len(questions) + 1
        questions.append({
            "question_id": question_id(ordinal, s),
            "ordinal": ordinal,
            "kind": KIND_EXPLICIT_ASK,
            "rule": None,
            "text": s,
        })
    return questions


# ═════════════════════════════════════════════════════════════════════════════
# The typed answer-reference (how a ratified question id is discharged)
# ═════════════════════════════════════════════════════════════════════════════

#: The typed answer-reference fields. Wave 2's turn-completion hook
#: refuses to close a turn while a ratified question id lacks one.
ANSWER_REFERENCE_FIELDS = ("schema_version", "question_id", "answered_in",
                           "answer_text")


def make_answer_reference(question_id_, answered_in, answer_text) -> dict:
    """Build a typed answer-reference for one question id. Raises
    ``ValueError`` naming every defect rather than minting an invalid
    reference (an unanswerable reference must never look answered)."""
    ref = {
        "schema_version": SCHEMA_VERSION,
        "question_id": str(question_id_ or "").strip(),
        "answered_in": str(answered_in or "").strip(),
        "answer_text": str(answer_text or "").strip(),
    }
    problems = answer_reference_problems(ref)
    if problems:
        raise ValueError("; ".join(problems))
    return ref


def answer_reference_problems(ref) -> list:
    """``[]`` == a valid typed answer-reference; each defect is NAMED."""
    if not isinstance(ref, dict):
        return ["answer-reference is not a dict"]
    problems = []
    if ref.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version must be %d (got %r)"
                        % (SCHEMA_VERSION, ref.get("schema_version")))
    qid = ref.get("question_id")
    if not (isinstance(qid, str) and _QUESTION_ID_RE.match(qid)):
        problems.append("question_id %r does not match the deterministic "
                        "id shape (qNN-<12 hex>)" % (qid,))
    for field in ("answered_in", "answer_text"):
        v = ref.get(field)
        if not (isinstance(v, str) and v.strip()):
            problems.append("%s must be a non-empty string" % field)
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The V1 fixture set + the no-silent-out-of-bound gate
# ═════════════════════════════════════════════════════════════════════════════

def load_fixtures(path=None) -> dict:
    p = Path(path) if path else FIXTURES_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def fixture_fires(row) -> list:
    """The questions the bound emits for one fixture row (its ``text``
    and/or its explicit-ask ``asks`` affordance)."""
    if not isinstance(row, dict):
        return []
    questions = list(parse_direct_questions(row.get("text") or ""))
    questions += questions_from_asks(row.get("asks") or [])
    return questions


_DISPOSITION_ROW_RE = re.compile(
    r"^\|\s*`?([A-Za-z0-9][A-Za-z0-9_-]*)`?\s*\|\s*"
    r"(IN-BOUND|KNOWN-MISS)\s*\|", re.MULTILINE)


def artifact_dispositions(text) -> dict:
    """The F7 artifact's disposition table as ``{fixture_id: label}``
    (mechanical regex over the committed markdown table rows)."""
    return {m.group(1): m.group(2)
            for m in _DISPOSITION_ROW_RE.finditer(str(text or ""))}


def bound_problems(fixtures=None, artifact_text=None) -> list:
    """THE no-silent-out-of-bound GATE (V1). ``[]`` == every fixture row
    is (a) labeled IN-BOUND and the bound fires, or (b) labeled
    KNOWN-MISS, the bound stays silent, and the F7 artifact names the row
    as a miss put to John — with the journal's verbatim T+15 trigger
    present as its NAMED fixture. Any other state is a NAMED problem:
    a row that is neither IN-BOUND nor KNOWN-MISS is a gate failure by
    name (:data:`FINDING_SILENT_OUT_OF_BOUND`), never a silent skip."""
    problems = []
    if fixtures is None:
        try:
            fixtures = load_fixtures()
        except (OSError, ValueError) as exc:
            return [{"finding": FINDING_FIXTURES_MALFORMED, "row": None,
                     "problem": "fixture set unreadable: %s" % exc}]
    if artifact_text is None:
        artifact_text = RATIFICATION_PATH.read_text(
            encoding="utf-8", errors="replace") \
            if RATIFICATION_PATH.is_file() else ""
    dispositions = artifact_dispositions(artifact_text)

    if fixtures.get("schema_version") != SCHEMA_VERSION:
        problems.append({"finding": FINDING_FIXTURES_MALFORMED, "row": None,
                         "problem": "fixture schema_version must be %d "
                                    "(got %r)" % (SCHEMA_VERSION,
                                                  fixtures.get(
                                                      "schema_version"))})
    if fixtures.get("owner_file") != OWNER_FILE:
        problems.append({"finding": FINDING_FIXTURES_MALFORMED, "row": None,
                         "problem": "fixture owner_file must be %r (got %r)"
                                    % (OWNER_FILE,
                                       fixtures.get("owner_file"))})
    rows = fixtures.get("rows") or []
    if not rows:
        problems.append({"finding": FINDING_FIXTURES_MALFORMED, "row": None,
                         "problem": "the fixture set carries no rows"})
    seen = set()
    for row in rows:
        rid = str((row or {}).get("id") or "").strip()
        if not rid:
            problems.append({"finding": FINDING_FIXTURES_MALFORMED,
                             "row": None,
                             "problem": "a fixture row carries no id"})
            continue
        if rid in seen:
            problems.append({"finding": FINDING_FIXTURES_MALFORMED,
                             "row": rid,
                             "problem": "duplicate fixture id"})
            continue
        seen.add(rid)
        label = row.get("label")
        fired = fixture_fires(row)
        if label not in (LABEL_IN_BOUND, LABEL_KNOWN_MISS):
            problems.append({"finding": FINDING_SILENT_OUT_OF_BOUND,
                             "row": rid,
                             "problem": "labeled %r — a row that is neither "
                                        "IN-BOUND nor KNOWN-MISS is a gate "
                                        "failure by name" % (label,)})
            continue
        if label == LABEL_IN_BOUND and not fired:
            problems.append({"finding": FINDING_IN_BOUND_NOT_FIRING,
                             "row": rid,
                             "problem": "labeled IN-BOUND but the bound "
                                        "does not fire on it"})
        if label == LABEL_KNOWN_MISS and fired:
            problems.append({"finding": FINDING_KNOWN_MISS_FIRES,
                             "row": rid,
                             "problem": "labeled KNOWN-MISS but the bound "
                                        "fires on it — the miss list is "
                                        "stale and must be re-prepared"})
        dispo = dispositions.get(rid)
        if dispo is None:
            problems.append({"finding": FINDING_SILENT_OUT_OF_BOUND,
                             "row": rid,
                             "problem": "no disposition row in the F7 "
                                        "artifact — an unrecorded row is "
                                        "silent out-of-bound"})
        elif dispo != label:
            problems.append({"finding": FINDING_DISPOSITION_MISMATCH,
                             "row": rid,
                             "problem": "fixture label %s disagrees with "
                                        "the F7 disposition %s"
                                        % (label, dispo)})
    for rid in sorted(set(dispositions) - seen):
        problems.append({"finding": FINDING_ARTIFACT_UNKNOWN_ROW,
                         "row": rid,
                         "problem": "the F7 artifact records a disposition "
                                    "for a row the fixture set does not "
                                    "carry"})
    t15 = next((r for r in rows
                if isinstance(r, dict) and r.get("id") == T15_FIXTURE_ID),
               None)
    if t15 is None or str(t15.get("text") or "").strip() != T15_TRIGGER_TEXT:
        problems.append({"finding": FINDING_T15_FIXTURE_MISSING,
                         "row": T15_FIXTURE_ID,
                         "problem": "the reference journal's verbatim T+15 "
                                    "trigger must ride the fixture set as "
                                    "the NAMED fixture %r with the exact "
                                    "text %r" % (T15_FIXTURE_ID,
                                                 T15_TRIGGER_TEXT)})
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The F7 ratification reader (fails CLOSED; the signature lives on disk)
# ═════════════════════════════════════════════════════════════════════════════

#: The signature line the artifact must carry once John signs — the same
#: committed convention chamber_retirement reads on the tile gate
#: ("**Signed by:** John …"), with the headline no longer UNSIGNED.
_SIGNED_LINE_RE = re.compile(r"^\*\*Signed by:\*\*\s*John\b", re.MULTILINE)
_UNSIGNED_MARK = "UNSIGNED"
_BOUND_VERSION_RE = re.compile(r"^\*\*Bound version:\*\*\s*(\d+)",
                               re.MULTILINE)


def ratification_state(path=None) -> dict:
    """The F7 artifact's honest state. Fails CLOSED: an absent artifact
    is :data:`FINDING_ARTIFACT_MISSING`; a present-but-unsigned one is
    :data:`FINDING_UNRATIFIED`. Enforcement (Wave 2's turn-completion
    hook) may switch on ONLY when this answers ``signed: True`` — an
    unenforceable bound never degrades to permissive."""
    p = Path(path) if path else RATIFICATION_PATH
    if not p.is_file():
        return {"prepared": False, "signed": False,
                "bound_version": None, "dispositions": {},
                "finding": FINDING_ARTIFACT_MISSING,
                "reason": "the F7 ratification artifact is absent: "
                          "chamber/%s" % p.name}
    text = p.read_text(encoding="utf-8", errors="replace")
    m = _BOUND_VERSION_RE.search(text)
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    signed = bool(_SIGNED_LINE_RE.search(text)) \
        and _UNSIGNED_MARK not in first_line
    out = {"prepared": True, "signed": signed,
           "bound_version": int(m.group(1)) if m else None,
           "dispositions": artifact_dispositions(text)}
    if not signed:
        out["finding"] = FINDING_UNRATIFIED
        out["reason"] = ("the E1 bound is PREPARED but NOT RATIFIED — "
                         "John's signature is recorded in the F7 artifact "
                         "on disk, not in chat; until it is, enforcement "
                         "must fail CLOSED")
    return out
