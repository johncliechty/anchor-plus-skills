# F7 — E1 bound ratification (NS amendment)

**Signed by:** John — 2026-08-13
**Prepared:** steward-e1 W1 (2026-08-12)
**Bound version:** 1
**Fixture set of record:** `tests/fixtures/chamber/e1-bound-fixtures.json` (schema v1, owner `chamber_e1_bound.py`)
**Gate code:** `chamber_e1_bound.py :: bound_problems / ratification_state` — the no-silent-out-of-bound gate and the fail-closed signature reader. Wave 2's turn-completion hook may enforce ONLY a bound this record carries SIGNED; unsigned or absent, the hook fails CLOSED by name (`E1-BOUND-UNRATIFIED` / `E1-F7-ARTIFACT-MISSING`).

## What is being ratified (context first)

E1's criterion reads: *a steward turn structurally CANNOT close while a
ratified direct question id lacks a typed answer-reference.* The machine can
only enforce that if "direct question" has an agreed, deterministic
definition — a line **you** have drawn, not a line the machine invented.
This record is that line. The chamber build never landed it (the W12 audit's
named plan defect); the steward-e1 build re-executes it, and this Wave-1
artifact puts the bound in front of you before Wave 2 wires any enforcement.

The reference failure this exists for: at T+15 in the Stage-2 reference
session you said, with no question mark, **"confirm you got comments on the
whole deck"** — and the steward walked away from it. That exact utterance
rides the fixture set as the named fixture `t15-confirm-whole-deck`, and
under the bound below it is IN-BOUND.

## The bound (v1) — deterministic, model-free, three legs

A **direct question** is any of:

1. **A terminal-'?' sentence.** Any sentence whose terminal punctuation run
   carries a `?` (trailing closing quotes/brackets ride along).
2. **An explicit ask.** Every non-empty entry of a steward reply's `asks[]`
   slot — the structured ask affordance the composer contract already
   carries.
3. **A committed imperative-ask form (the V1 amendment).** A sentence with
   NO question mark that, after stripping the committed leading fillers
   (okay/ok/hey/so/um/uh/and/also/now/please), anchors on one of these
   committed prefix rules:

| rule id | anchors on | example |
|---------|-----------|---------|
| confirm-receipt | `confirm …` | "confirm you got comments on the whole deck" |
| tell-me | `tell me …` | "tell me which sections still need the enrollment numbers" |
| let-me-know | `let me know …` | "let me know when the case packet is uploaded" |
| did-you | `did you …` | "did you get the revised syllabus deck" |
| can-you | `can / could / would / will you …` | "can you please pull the final grade distribution" |

Each detected question gets a deterministic per-question id (parse ordinal +
a content digest of the normalized sentence — identical on every re-run),
and is discharged only by a **typed answer-reference**
(`{schema_version, question_id, answered_in, answer_text}`, all fields
required and validated).

The bound is COMMITTED CODE (`chamber_e1_bound.py`), never tuned at
runtime. Widening it (new rules, new filler tokens) is a bound-v2 amendment
through a new F7 signature — never silent, and never by model judgment,
which E1's own criterion (zero model involvement) forbids.

**One deliberate over-capture, named:** any sentence leading with
`confirm …` is in bound, including task imperatives like "confirm the room
booking with the registrar" (fixture `overcapture-confirm-task`). The cost
of over-capture is an acknowledgment before the turn closes; the cost of
under-capture is the T+15 walk-away this build exists to end. v1 errs
toward capture.

## Fixture dispositions (every row resolved; none silent)

Every fixture row is IN-BOUND (the bound fires) or KNOWN-MISS (the bound
stays silent and the miss is put to you here). A row that is neither is a
**gate failure by name** (`E1-SILENT-OUT-OF-BOUND`) — enforced mechanically
by `chamber_e1_bound.bound_problems` in
`tests/test_chamber_e1_bound_w1.py`.

| Fixture id | Disposition | Why |
|------------|-------------|-----|
| `qmark-plain` | IN-BOUND | leg 1: canonical terminal-'?' question |
| `qmark-embedded-prose` | IN-BOUND | leg 1 inside prose; only the question sentence fires |
| `qmark-quoted-tail` | IN-BOUND | leg 1 with trailing quotes riding the terminator |
| `explicit-ask-affordance` | IN-BOUND | leg 2: the `asks[]` slot |
| `t15-confirm-whole-deck` | IN-BOUND | leg 3, confirm-receipt — the named T+15 trigger, verbatim |
| `imperative-tell-me` | IN-BOUND | leg 3, tell-me |
| `imperative-did-you-no-qmark` | IN-BOUND | leg 3, did-you (dictation dropped the '?') |
| `imperative-can-you-please` | IN-BOUND | leg 3, can-you |
| `imperative-let-me-know` | IN-BOUND | leg 3, let-me-know |
| `imperative-please-confirm-filler` | IN-BOUND | leg 3 after the committed filler strip |
| `garbled-inline-filler` | IN-BOUND | leg 3: inline garble does not move the anchor |
| `overcapture-confirm-task` | IN-BOUND | the deliberate v1 over-capture, named above |
| `garbled-split-confirm` | KNOWN-MISS | the anchor verb split in transcription ("com firm") |
| `garbled-mishear-confirm` | KNOWN-MISS | the anchor verb mis-heard away ("kind of firm") |
| `intonation-only-question` | KNOWN-MISS | rising-intonation question; only prosody carried the '?' |
| `midsentence-ask` | KNOWN-MISS | third-person ask buried mid-sentence ("did they") |
| `indirect-wondering` | KNOWN-MISS | indirect speech act ("i was wondering…") |

## The KNOWN MISSES, honestly (what your signature signs away)

Signing this record signs the five KNOWN-MISS rows above as **agreed
out-of-bound losses of the v1 bound**:

- **Garble that destroys the anchor** (`garbled-split-confirm`,
  `garbled-mishear-confirm`): once dictation splits or mis-hears the anchor
  verb, no deterministic prefix rule survives. Catching these would need
  fuzzy matching — a tuning surface the bound deliberately refuses.
- **Prosody-only questions** (`intonation-only-question`): a statement-shaped
  sentence asked with rising intonation. The '?' never reaches the text.
- **Mid-sentence / third-person asks** (`midsentence-ask`): scanning
  mid-sentence for interrogative fragments would over-fire on ordinary
  narration; the v1 rules anchor at sentence start, second person.
- **Indirect asks** (`indirect-wondering`): "i was wondering…" is a real ask
  in speech, but a `wondering` rule also fires on plain narration. Proposed
  as a miss at v1; orderable in-bound as a bound-v2 amendment if the loss
  bites in practice.

What still covers a missed ask: the steward's conventional one-question
discipline and your own follow-up — the same cover that exists today.
Every miss stays visible here by name; none is silent.

## Effect while unsigned

Enforcement does NOT switch on. `ratification_state` answers
`signed: False` with the named finding `E1-BOUND-UNRATIFIED`, and the
Wave-2 turn-completion hook must fail CLOSED on that answer — a steward
turn is never blocked against a bound you have not signed, and an
unenforceable bound never degrades to permissive. Wave 2 may not begin
enforcing before this signature exists.

## NS amendment (recorded by this signature)

On signing, the North Star's E1 term "ratified direct question id" is
formally defined as: *a question id emitted by the v1 bound above — the
committed three-leg parse in `chamber_e1_bound.py` — over a steward-turn
boundary, with the five named KNOWN-MISS forms agreed out-of-bound.* The
telemetry half of E1 (⏱ table + footer on the telemetry clock) is untouched
by this amendment.

## Recommendation, then the decision

**Recommendation:** ratify bound v1 as drawn. It captures the T+15 trigger
verbatim, all four V1-named imperative families, the explicit ask
affordance, and every terminal-'?' form — and its five misses are all forms
that no deterministic text rule can catch without either fuzzy matching or
model judgment, both of which the E1 criterion itself rules out. The bound
can only widen from here, and only through a signature you give.

**To sign:** replace the **Signed by:** line above with
`**Signed by:** John — <date>`, and delete `— UNSIGNED` from the first
line. The signature lives in this file on disk — not in chat.

Ratify E1 bound v1 as drawn above — signing the five KNOWN-MISS rows as
agreed out-of-bound losses?
