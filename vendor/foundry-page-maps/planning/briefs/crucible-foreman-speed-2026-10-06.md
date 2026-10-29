# Seed — why Crucible and Foreman take so long (for this cockpit: Foundry page and knowledge maps)

**From:** John, 2026-10-06 evening: "This is a problem with crucible and foreman, they take a really long time. I am not sure why ... I do want to sort out crucible and foreman, but I will do it in the Skill Foundry review AI Cockpit effort."
**Status:** a seed, not a plan. John named this cockpit for it (2026-10-06): "It is Foundry Page and Knowlege Map AI Cockpit".

## Measured today (one Foreman run, a LANDING of finished work, single wave)

Anchor code job `20261006-180229-af04a0` (Setup and Mother Ship, provider assurance; the work was already built and approved):

| step | minutes |
|---|---|
| execute (copy 27 staged files in) | 4 |
| gate (93/93) | 1 |
| review, 2 x Grok in parallel | 13 |
| elegance catcher (ChatGPT) | ~10 -> keep 25, hold 2, cut 0 |
| elegance adversary (Grok xhigh) | 9+ and still running at 18:39, though with zero cuts it cannot change the outcome |

Overhead after the wave was already proven GREEN and approved: 20+ minutes. Full analysis: `C:/dev/trio/foreman/journal/0135-elegance-step-cost-on-a-landing-job.md`.

## Other time sinks seen the same day

- Execute seats that cannot do the job: ChatGPT (Codex sandbox) answered BLOCKED instead of running a `git checkout` whose git dir sat outside its sandbox; a whole run lost.
- Grok reviewers cancelled mid-review by an unanswerable tool ask (fixed today, trio `2feb9ed`: resume in-session), plus `max turns reached`.
- Foreman HALTs that cost a full re-run: session limit (`dff72f`), non-convergence MAX_ITERS (`a28de8`), vacuous-GREEN on a resume after a crash (`187472`).
- Foreman pre-flight: a dirty "sibling repo" (an accidental empty git repo at `C:/Users/example/AppData/Local`) refused to start.
- Seats re-investigate the repository at every step (each reviewer 20-60 tool calls; the elegance seats repeat the same reads).

## Questions for the cockpit

1. Where does the wall-clock go across the last N Crucible and Foreman runs? (phase-timings.jsonl has execute/gate/review; elegance is not timed — journal 0135 R3.)
2. Which steps are proportionate per job class (landing, single-wave fix, multi-wave build)? Journal 0110's owed single-wave fast path; 0135 R1/R2.
3. Per-seat time caps and supervision for every agentic call, not just execute/review/fix.
4. The same questions for Crucible's Shark-Tank rounds (not measured here).
