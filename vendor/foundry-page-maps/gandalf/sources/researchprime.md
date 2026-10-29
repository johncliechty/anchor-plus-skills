# researchPrime

**One sentence:** A careful research engine that checks claims against real evidence and tells you how solid each finding is — not just what sounds right.

## Use this when
- You need a serious investigation, not a quick web skim
- Stakes are high (a decision, a paper, a product bet) and “sounds plausible” is not enough
- You want an honest ladder of confidence: observed, corroborated, claimed, unverified, or refuted

## Do not use this when
- You only need a fast factual lookup or a short summary
- You’re looking for brainstorming or creative pivots (use Jumper)
- You need a build plan or code written (use Crucible → Foreman)

## What you get
- A structured research report at three levels (full, executive, agent-ready)
- Evidence weighted by how it was checked, with honesty stamps when checks didn’t fully run
- Multi-round adversarial review when the host can run the Node engine; a clearly labeled lighter pass otherwise

## What it is not
- Not a flattering “agree with the user” brief
- Not a code builder or product planner
- Not a guarantee of perfect truth — it reports what was verified and what wasn’t

## How to start (human)
1. Open researchPrime in Skill Foundry (or ask the agent for a deep research run).
2. State the question and what a wrong answer would cost you.
3. Approve the research plan when you’re shown it (edit or abort if needed).
4. Read the deliverable’s confidence labels before you act on any claim.

## Limits (honest)
- Full adversarial verification needs Node available; without it you still get a usable report, stamped that deep verification did not run
- It refuses to treat popularity as proof
- Long runs take real time; plan for progress updates, not instant answers

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file (trio monorepo: `C:\dev\trio\researchPrime\`). Load that only when running the skill — this card is for people.
