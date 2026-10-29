---
name: agy-dispatch
description: Route token-heavy read/investigate/review/edit work to Gemini via the agy CLI (~5:1 Gemini:Claude spend) — the cross-family transport underpinning every skill's adversarial review. Real label model ids only (refuses phantoms, attests substitutions), auth expiry surfaced with a remedy, no-shell steer (no PowerShell popups). Use for "dispatch to Gemini", "agy", or before any long cross-family run (--selftest answers "is agy healthy?" in one command).
---

## North Star (LOCKED — John, 2026-08-25)

Be the BORING, HONEST transport: deliver a prompt to Gemini via the agy CLI and bring back the reply — with every failure mode SURFACED to the caller as a typed reason, and zero classes of silent degradation. (Full six refusal-criteria: NORTH-STAR.md in this folder. Sizing/tiers are the CALLER's job — deliberately.)


<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


# agy-dispatch — Claude drives Gemini (the agy workflow)

> A thin workflow for routing the token-heavy work to **Gemini via the `agy` CLI** so
> Claude stays a cheap orchestrator (~**5:1 Gemini:Claude** spend). Claude writes a SHORT
> prompt; Gemini reads/investigates/reviews/**edits** the project's files on its own tokens.
> The executable is `tools/agy-dispatch.mjs` (doc: `tools/AGY-DISPATCH.md`); this SKILL.md
> is the when/how. Validated live on Windows, 2026-06-29.

## When to use
Use whenever a task is heavy on reading or editing files and the *conclusion* is what you
need — code investigations, multi-file audits, code reviews/cross-verification, and
bulk/surgical edits (fixes, refactors, conflict resolution). Keep Claude for orchestration,
gating (run the tests/git yourself), and synthesis. Don't use it for a single quick lookup.

## How to run (always BACKGROUNDED from the Bash tool — never a visible PowerShell)
```
node tools/agy-dispatch.mjs --prompt-file <p> --target <projectDir> --out <reply.txt> \
     [--model "Gemini 3.1 Pro (High)"] [--readonly] [--timeout-min 25] [--label x]
```
- `--readonly` → investigations/reviews/judges (no edits possible).
- omit `--readonly` → edit posture (`--sandbox --add-dir <target>`; Gemini edits files).
- One-line JSON status → stdout; full model reply → `--out`. Read `--out` when it lands.
- **Keep concurrent agy runs to 2–3** (more caused an OOM crash, 2026-06-29).

## agy-review — the canonical 5:1 diff-review entry point (USE THIS, don't reinvent)
Before committing any non-trivial batch, have **Gemini review the diff on its own tokens**.
This is the automatic 5:1 loop — run it every batch, the same way, on any host:
```
# 1. Operator stages the diff (Gemini never shells; you run all git).
git -C <target> diff [--staged] > <scratch>/batch.diff

# 2. Write a SMALL review prompt that points at the diff file (do NOT paste the diff inline).
cat > <scratch>/review.txt <<'EOF'
Read batch.diff in this folder and the files it touches. This is one batch of a
mechanical migration. Report ONLY regressions: a dropped/loosened auth or token
check, a broken closure/binding, changed request/response behavior, a handler that
silently no-ops, or anything not behavior-preserving. If clean, say "CLEAN — no
regressions". Be specific: file:line + what breaks. Do not restyle or nitpick.
EOF

# 3. Dispatch READ-ONLY (backgrounded), then read the verdict.
node tools/agy-dispatch.mjs --prompt-file <scratch>/review.txt --target <target> \
     --out <scratch>/review-reply.txt --readonly --timeout-min 20 --label review-batchN
```
- **The test gate is ground truth, agy is the second pair of eyes.** Sequence per batch:
  Claude extracts → **operator runs the deterministic gate (tests/compile)** → agy-review the
  diff → fix anything flagged → **commit only when gate-green AND review-clean**.
- Tune the "report ONLY regressions" clause to the batch's real invariant (auth overlay
  intact, closure captured, route parity). Keep the prompt small; agy reads the diff itself.

## The rules that make it work (hard-won)
- **NEVER hand-roll `agy`** (no bare `agy -p …`, no ad-hoc gemini call, no prompt-pasting the
  diff): ALWAYS go through `tools/agy-dispatch.mjs` so the no-shell steer + timeout tree-kill +
  transcript polling apply. For any review/investigation/judge, ALWAYS pass `--readonly`.
- **Prompts stay small**: pass instructions only; let Gemini READ the project files itself
  (agy argv ceiling ~32KB → ENAMETOOLONG; stdin truncates ~4KB). For edits, pin explicit
  absolute paths under the target and verify nothing else changed afterward.
- **No-window fix (critical)**: agy spawns a *visible* PowerShell for every shell tool-call,
  which steals focus — no launch flag suppresses it. The dispatcher auto-prepends a no-shell
  STEER so Gemini stays on in-process file tools (read/list/grep/edit) and never shells out
  (verified 0 child shells). The human/Claude operator runs all shell/test/git/build. Escape
  with `--allow-shell` only if you accept the popups.
- **Verify, don't trust**: run the deterministic gate (tests/compile) yourself after an edit
  pass; cross-review risky output with a second `--readonly` agy run.

## Related — the TWO sanctioned agy transports (and only these two)
- `<path> Foundry\tools\agy-dispatch.mjs` (THIS skill) — the standalone one-shot CLI
  transport: ad-hoc dispatches, Anchor's `agy_job_adapter.mjs`, anything outside a trio engine.
- `<path> — the in-engine seam for trio/foundry engines: adds
  served-model ATTESTATION (substitution tripwire), tier-label resolution, and the fail-closed
  `makeGeminiCliSeam`. Engines use this, never the CLI wrapper.
Division of labor is deliberate; when the agy CONTRACT changes (argv shape, log lines,
transcript layout), update the DRIVER first — it is canonical — then mirror here. Do not add a
third transport. (A previous "Related" pointer named `agy-transcript.mjs`/`runAgyPrint` — those
are DEAD/nonexistent; this section replaces it.)
Related but NOT a transport: `tools/run-gemini-engine.ps1` — a launcher that runs a whole
Foreman/Crucible engine on the agy subscription; it rides the driver above, it is not a third
way to reach agy. (Reworded 2026-08-24 — the old "Also:" line contradicted "only these two.")
