# Skill Foundry v2 — Design (DESCRIPTION)

> Frozen design doc for the Foreman build. Derived from the locked North Star (`../NORTH-STAR.md`), the
> Crucible Master Plan (`../crucible/MASTER-PLAN-FINAL.md`), and the cross-family research
> (`../researchPrime-out/RESEARCH-REPORT.md`). The Implementation Plan (`IMPLEMENTATION-PLAN.md`) decomposes
> this into waves; this doc is the WHY + the invariants each wave is gated against.

## Objective (North Star, condensed)
Turn the Skill Foundry into a best-in-class, self-improving skill PLATFORM with its OWN GUI as the primary
operating surface, launched from an Anchor button, driving the REAL kernel/trio/skills (never theater). DONE =
from the Foundry GUI a user can create a skill, run/monitor it + see its changes, browse the library + graph,
edit a per-skill North Star, and run+review a **test-gated sleep improvement that has turned over ≥1× on
genuine (non-fixture) data** — and every foundry skill is auto-available/clickable inside Anchor.

## Architecture — the load-bearing decisions (settled, adversarially verified)
1. **One engine, many surfaces.** The Foundry GUI REUSES Anchor's real `job_runner`/session/artifact store as
   the single source of truth; it is a STATELESS client invoking the same API the headless path uses. No second
   platform, no parallel run/progress store. (Research C11/C12 — survived the Shark Tank unattacked.)
2. **Mutations are runs, not endpoints.** Every mutative Foundry operation (scaffold a skill, generate a
   manifest, edit a North Star, apply a sleep improvement) is a manifest-registered `mutate` op executed via
   the generic skill_runner through `job_runner` — confirm-token-gated and auto-journaled. (Clears the Stage-1
   Shark BLOCKER: the GUI needed write verbs Anchor's execution API lacks, without a bespoke backend.)
3. **Capture is a by-product.** Host-enforced journaling at the ONE generic skill_runner seam; honor-system
   capture is forbidden (it is the documented failure mode that starves the loop).
4. **The loop's integrity is its gate.** A sleep improvement promotes only through a grounded, held-out,
   independently-verified test with a FROZEN rollback-able baseline; the human is the promotion authority.
5. **Declarative catalog on the consumption path.** A manifest-driven skill_runner + `map.json` v2 that the
   REAL consumer reads, so a wrong/empty edge breaks a build loudly (not silent shelfware).

## Single-source invariant (explicit)
There is ONE canonical copy of each skill at `C:/dev/Skill Foundry/skills/<skill>`. Anchor and the generic
runner CONSUME skills via the env-pointed skill dir (`ANCHOR_GANDALF_SKILL_DIR`-style), embedding the skill's
`SKILL.md` and running the skill's OWN host — they NEVER fork, copy, or re-version a skill. The build
**generalizes Anchor's `gandalf.py` consumer ADAPTER** (the ~1,600-line integration glue) into one reusable
runner; it does not touch any skill's source, version, or behavior.

## The four open gaps (resolved in Wave 1 spikes, cited by later waves)
1. A NAMED OS-level isolation runtime for host-enforced skill permissions + its cost (language-level sandboxing
   is insufficient), reconciled with lazy/budgeted activation.
2. A test/lesson provenance model that escapes circular validation in the sleep gate.
3. How far process-telemetry must go beyond the outcome seam, and the droppable side-channel design.
4. The exact Anchor API/CLI surface the GUI drives — split into native READ/EXECUTE vs. the MUTATIVE verbs the
   control plane must supply.

## Invariants preserved by every wave (the gate set)
North-Star anti-drift · spec-truth grep gates · PRINCIPLE-D gate/advisory isolation · PLAN.md as status source
of truth · host-ENFORCED journaling (mutative ops included) · every mutation is a confirm-gated runner op,
never a GUI-side write · zombie-hunter native built-in + reaper safety envelope · single canonical copy per
skill (consume, never fork) · Claude writes code / Gemini verifies (3-Gemini review panel per wave, 5:1).

## Build root + ground-truth gate
Build root = `C:/dev/Anchor` (where the runner, journaling seam, control-plane ops, and GUI land). Project
gate = `python -m pytest -q` (Anchor's suite, 213 test files). Node-side components (the sleep kernel parser,
the GUI build) are exercised through Anchor pytest integration (subprocess) so the single Foreman gate covers
them; their own `node --test` unit suites run as part of the owning wave's work.
