# Steward E1 — Implementation Plan (Foreman-ready)
# Two waves. Re-executes the E1 rows the chamber build never landed.
# The W3/W8/V1/V5 text in planning/steward-chamber-2026-08-09/IMPLEMENTATION-PLAN.md
# is NORMATIVE and unchanged — this plan re-executes those rows, it does not
# redefine them. Where the two disagree, the chamber plan wins and the
# disagreement is a plan defect to raise, not to resolve in code.

test-command: node scripts/run-all-tests.mjs

**North Star:** E1 becomes engine-enforced, honestly. A steward turn
structurally CANNOT close while a ratified direct question id lacks a typed
answer-reference, and the ⏱ table + footer inject on the telemetry clock with
zero model involvement. The bound the engine enforces is one **John has
ratified** — the design's whole point is that the machine enforces an agreed
line, not a line the machine invented. The acceptance oracle is
`chamber/E1-ENFORCEMENT-REPORT.md`'s mechanical instrument scan flipping to
all-present and staying re-runnable.

**Anti-goal (from the chamber plan, restated):** no engine-spine changes, no UI
beyond the amended locked mockup, no High Seat work, no new commission lanes.
Tiles retire only on signed rail+STATUS parity — untouched by this build.

---

## Wave 1 — E1 bound parser + V1 fixture set + F7 ratification artifact

**Intent:** Land the deterministic question-parse module and the artifact that
puts its bound in front of John for ratification. This is the W3 row, executed
whole. The parser is deterministic and model-free: given text, it emits
per-question ids. Nothing enforces anything yet — enforcement is Wave 2, and it
may only enforce a bound John has signed. Serves C4/E1.

**Deliverables:** E1 deterministic question parser (new chamber-local module,
stdlib only, zero model/network/PTY I/O) detecting terminal-'?' sentences AND
the explicit ask affordance, emitting deterministic per-question ids stable
across runs, with the typed answer-reference schema those ids are answered by;
V1 fixture set — imperative request forms carrying NO question mark ("confirm
you got…", "tell me…", "did you get…", "can you please…") plus realistic
garbled-dictation rows, WITH the reference journal's verbatim T+15 trigger
("confirm you got comments on the whole deck") as a NAMED fixture, each row
labeled IN-BOUND or KNOWN-MISS; F7 NS-amendment artifact recording the ratified
E1 bound — every fixture form resolved to IN-BOUND (parser fires) or an
explicitly John-signed KNOWN MISS, with **no silent out-of-bound row permitted**
(a row that is neither is a gate failure by name); parser test suite proving
determinism (parse-twice → identical ids), the full V1 fixture set, and the
honest miss list; new module registered in `dist_manifest.txt` in-wave.

**done-when:** The parser passes its full V1 fixture set with deterministic
per-question ids, every fixture form is resolved IN-BOUND or KNOWN-MISS with
zero silent out-of-bound rows, the F7 NS-amendment artifact is prepared and
complete, and the distro import-closure + ship family are green.

- **Given** fixture text containing terminal-'?' sentences and non-question prose, **when** the E1 bound parser runs, **then** per-question ids emit deterministically and identically on a second run
- **Given** the V1 imperative forms with no question mark, including the verbatim T+15 trigger "confirm you got comments on the whole deck", **when** the parser runs, **then** each is classified IN-BOUND or recorded as a KNOWN MISS in the F7 artifact — never silently out-of-bound
- **Given** the F7 artifact as prepared, **when** the wave closes, **then** every fixture form has a disposition and the artifact is ready for John's ratification signature

**HALT — JOHN GATE (F7 ratification).** This wave ends at John's ratification
HALT by design. Wave 2 may not enforce an unratified bound. Present the bound
as prose, one decision, recommendation before the question, never a clipped
dialog. The signature is recorded in the F7 artifact on disk — not in chat.

---

## Wave 2 — Turn-completion hook + joint negative-path test + the drawn blocked-turn state

**Depends on:** Wave 1 — E1 bound parser + V1 fixture set + F7 ratification artifact

**Intent:** Make the bound structural. The steward turn-completion hook wires
to the W2-proven converse seam and refuses to close a turn while a ratified
question id lacks a typed answer-reference, with a NAMED finding. The telemetry
half of E1 is verified rather than assumed. And the refusal gets a DRAWN state,
so the cure never looks like the disease. This is the W8 row plus V5. Serves
C4/E1/C9.

**Deliverables:** Steward turn-completion hook on the W2-proven converse seam
enforcing the **ratified** bound — a turn carrying an open question id with no
typed answer-reference is structurally blocked at close with a named finding
(the hook reads the F7-signed bound; an unsigned or absent artifact means the
hook fails CLOSED with a named reason, never silently open); Joint landing-wave
negative-path test — a turn attempts to close on an open question id, the engine
blocks, the named finding is asserted, and per V1 the suite exercises **at least
one imperative in-bound form** (not only a '?' form); Telemetry-injection
verification for the other half of the criterion — the ⏱ status table and
campaign footer inject from the re-homed emitter on the telemetry clock with
ZERO model involvement, asserted by a zero-model-call trace (this half may
already be standing from the chamber build; if so the wave PROVES it at its seam
and says so honestly — proving a standing behavior is not a defect, claiming to
have built it would be); V5 "blocked turn" drawn state — the E1 refusal state
joins the mockup's enumerated states, **batched into ONE amendment gate together
with the already-ORDERED transcript-link row from `chamber/TILE-RETIREMENT-GATE.md`
decision 1**, so John signs once; the C9 hash is re-pinned to the new
post-amendment markup and the DOM diff re-points to it; `chamber/E1-ENFORCEMENT-REPORT.md`
regenerated from the live scan showing all four legs PRESENT; auth-ON + F6
(token, POST-only, CSRF-refusal) shown RED-TO-GREEN for any new mutator with its
row landed in the living routes inventory before the surface merges; all new
modules in `dist_manifest.txt` in-wave.

**done-when:** The turn-completion hook blocks a close on an unanswered ratified
question with a named finding (joint negative-path test green, including an
imperative in-bound form), the hook fails CLOSED on a missing/unsigned bound,
the telemetry injection is proven at its seam with a zero-model-call trace, the
batched mockup amendment is signed and the C9 hash re-pinned with DOM diffs
green against it, and the regenerated E1 enforcement report shows four legs
present with the scan re-runnable.

- **Given** a steward turn ending while a direct question id from John lacks a typed answer-reference, **when** the turn attempts to close, **then** the engine structurally blocks the close with a named finding (E1 negative path, per the ratified F7 bound)
- **Given** an imperative in-bound form with no question mark as the open question, **when** the turn attempts to close, **then** it is blocked identically — the bound is the ratified one, not "has a question mark"
- **Given** a missing, altered, or unsigned F7 artifact, **when** the hook evaluates a turn close, **then** it fails CLOSED with a named reason — an unenforceable bound never degrades to permissive
- **Given** the telemetry clock ticking on a running step, **when** the ⏱ table and campaign footer update, **then** they update from the re-homed emitter with a zero-model-call trace proving no model involvement
- **Given** the blocked-turn refusal rendering, **when** it is DOM-diffed, **then** it matches the drawn post-amendment mockup state at the re-pinned C9 hash — the refusal is a distinct drawn state, never an ambiguous "are you working"

**HALT — JOHN GATE (batched mockup amendment).** The V5 blocked-turn state and
the ordered transcript-link row are presented together, drawn, for ONE
signature. The C9 re-pin follows the signature; it does not precede it.

---

## Standing rules for both waves

- **The instrument scan is the oracle, not the wave's own say-so.** A leg counts
  as landed when `chamber/E1-ENFORCEMENT-REPORT.md`'s mechanical scan finds it,
  re-runnably. This is the exact check that caught the original absence.
- **A cited test file that does not exist is a defect, not a rounding error.**
  The chamber build accumulated 5 ghost test files cited in reports but absent
  from the tree. Every test this plan cites must exist and run.
- **Vacuous-GREEN guard:** a wave whose new source has no test naming and
  exercising it is not GREEN. Write real tests, prove them green, then advance.
- **agent-launch-failure is a loud halt** (foreman journal 0082): an `ok:false`
  / 0-tools / sub-2s agent result must raise a named halt, never be blessed as
  an empty-but-complete step. W12 spun 80 minutes on this.
- **Hermetic, auth-ON, stdlib-only, manifest-in-wave** — per DESCRIPTION.md.
