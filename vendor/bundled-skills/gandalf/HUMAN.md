# Gandalf

**One sentence:** A deep-think second opinion on any artifact or effort — what’s really going on, what’s wrong or missing, how it sits vs best-in-class, and what problems are coming.

## Use this when
- You want a rigorous read: “what am I missing?”
- Stakes are high and a polite rubber-stamp review is useless
- You need diagnosis + situating + foresight, not just a list of nits

## Do not use this when
- You need new ideas generated (use Jumper)
- You need multi-plan planning to convergence (use Crucible)
- You need claim verification research as the main product (use researchPrime)

## What you get
- An editorial executive report (HTML & Markdown via `--report-html` / `--report-md` or `runtime/render-report.mjs`) leading with a plain-English Bottom-Line Verdict and Ranked Diagnosis (or “this is sound” when it is)
- Situating against better-known reference solutions when warranted
- Forward-looking “coming problems” (premortem) and Recommended Elevations paired with explicit plain-English Falsification Tests
- Transparent **Ideas Tested & Rejected by Adversarial Review**, showing candidate proposals that were falsified and why
- Earned verification labels (*Cross-Family Verified*, *Single-Family Checked*, *Unverified Hypothesis*) with internal IDs and cryptographic audit digests tucked into a collapsed Provenance Appendix (`[1..N]`)

## Executive Human-Facing Report Standard
Human-facing Gandalf deliverables always lead with clear, jargon-free prose rendered deterministically from the graded `read.json` (zero post-grade model rewriting). Uncertainty caveats and single-family/degraded scope qualifications are stated plainly up front, rejected ideas remain visible with their concrete defeaters, and machine IDs (`d-1`, `e-2`), JSON keys, and commission hashes stay inside `read.json` and the collapsed **Verification & Machine Provenance Appendix**.

## What it is not
- Not a brainstorm generator
- Not a builder or planner
- Not free to claim “proven” without independent refutation work

## Variable Strength (`Gandalf` Standard Default vs. `Gandalf Heavy`) — What to Call When
- **Call `Gandalf` (default = `Standard` · one generalist model below frontier @ `medium` effort on both author and cross-family refuter)** when:
  - Doing routine plan/design/code sanity checks, draft memo reviews, or fast mid-effort "what am I missing?" reads where speed and lower token spend are right-sized
- **Call `Gandalf Heavy` (`⚡ Heavy` · frontier model @ full/max effort on both author and cross-family refuter — say `"Gandalf Heavy"`, pass `--tier heavy`, or toggle `⚡ Heavy` on your AI Cockpit)** when:
  - Making an irreversible architecture, product, or capital decision
  - Auditing a journal manuscript, grant proposal, legal/financial deliverable, or pre-launch system where missing a subtle flaw is costly

## How to start (human)
1. Point Gandalf at the document, plan, code, or effort in question.
2. Say what decision you’re trying to make (or what “good” looks like).
3. Prefer the deeper path for medium/high stakes; accept lighter stamps when stakes are low.
4. Act on grounded findings first; treat speculative ones as hypotheses.

## Limits (honest)
- Independent cross-check paths may be unavailable; then stamps stay conservative and say so
- It elevates insight, not flattery — operator preferences can be challenged
- Large whole-repo reads may need an explicit scale path

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
