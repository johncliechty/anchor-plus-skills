# Crucible + Foreman cf-slick — full breakdown (model sleep/build report)

**Date:** 2026-07-22  
**Ship:** `origin/main` @ `2474835` (on `7cca281`) · repo `johncliechty/trio`  
**Process model:** journal/log → cluster → North-Star gate → implement → unit tests → **Shark Tank** (not dogfood) → smoke → promote  

This document is the **template** for future Foundry sleep-cycle / skill-hardening runs.

---

## 0. Honest “world class” claim

| Claim | Reality |
|-------|---------|
| Log-driven hardening of C/F for hang, LITE, gate honesty | **Yes — shipped** |
| Real LITE / SPIKE / FULL ceremony (not labels only) | **Yes — Crucible; Foreman inherits** |
| Never need another improvement round | **No** — journals + sleep-loop remain |
| Best-in-class forever | **Strong step, not permanent guarantee** |

---

## 1. Crucible — structure by band

Depth locked at Stage-0 → `bin/band-profile.mjs` → Stage-1/2.

| Dimension | **LITE** | **SPIKE-FIRST** | **FULL** |
|-----------|----------|-----------------|----------|
| Purpose | Small/clear work | Mid / uncertain | Large / high stakes |
| Brainstorm | **1 call** single-pass | Full Oranges (map → premortem → ideate) | Full Oranges |
| Shark seats | **2 concurrent** | **3 concurrent** | **3 concurrent** |
| Round cap | **1** | **2** | **5** (effort-scoped resume) |
| Research upfront | Off | On | On |
| Spike probe | No | **Yes** (path exists or ≥40-char findings) | No |
| Human gates | NS lock, plan approve, PLAN-AMEND | Probe + plan + re-band | + human-lockable dry exit |
| Call budget hint | ~8 | ~18 | ~40 |

**Code:** `band-profile.mjs`, `stage1.mjs`, `stage2.mjs`, `shark-tank.mjs`, `stage0.mjs` (honest LITE copy), `launch-tidy.mjs` / `launch-zombie.mjs` → **must** `runStage1`.

**Parallel:** concurrent Sharks. **Serial:** brainstorm, plan write, synthesizer, user lock.

---

## 2. Foreman — structure by band

**Inherit only** — never re-triage. Depth from `triage.depth` / `triage_track` / `FOREMAN_DEPTH`.

| Dimension | **LITE** | **SPIKE-FIRST** | **FULL** |
|-----------|----------|-----------------|----------|
| Reviewers (default) | **1** (floor ≥1) | **2** | **2** |
| Mid-wave review | Lean | Lean mid | Lean mid; full panel terminal/fix |
| Execute/fix | Single-thread | Single-thread | Single-thread |
| Gate honesty | Explicit files; refuse `test/`; dual-root; under-gate HALT | Same | Same |

**Code:** `foreman-lib` preflight, `project-engine`, `locate-plan`, `run-live` band inherit, `lifecycle-launch`, `go.ps1` parent-owned.

**Parallel:** reviewer fan-out when full panel. **Serial:** code + gate.

---

## 3. Log problem → fix matrix

| Problem (journals) | Fix |
|--------------------|-----|
| C 0020–27 Stage-1 silent death / Hidden launch | Parent-owned launch; launchers use `runStage1`; lifecycle helper |
| C 0022 / 0003 LITE feels FULL | Real LITE ceremony collapse |
| C 0026 serial thrash | LITE 1-call brainstorm |
| C 0028 depth not plumbed | depth → profile end-to-end; launchers fixed |
| C 0019 / F 0046 thrash resume | Phase A kept (effort cap, human-lockable, prior-attempt) |
| F 0038–39 / 0047 `node --test test/` | Hard preflight refuse |
| F 0048 dual-root vacuous | Dual-root import HALT |
| F 0049 under-gated DONE | Hard HALT package suite > plan gate |

---

## 4. North Star impact

| Pillar | Result |
|--------|--------|
| User convergence / no auto-lock | **Preserved** |
| Frozen plan / no invent (Foreman) | **Strengthened** (refuse bad/under gates) |
| Orchestrator gate + real tests | **Strengthened** |
| ≥2-agree multi-Shark | **Preserved** (LITE uses 2, not 0) |
| Oranges / inclusion | **Preserved FULL/SPIKE**; LITE single-pass still NS-embedded |
| Single-thread code | **Unchanged** |

---

## 5. How to repeat (sleep-run model)

1. **Harvest journals** (genuine-execution only for corroboration).  
2. **Cluster** situations (≥2 contexts).  
3. **Map to North Star** — refuse changes that weaken pillars.  
4. **Implement smallest fix** with unit tests.  
5. **Shark Tank** (concurrent adversarial) — not dogfood as quality bar.  
6. **Smoke** only after Shark (band-appropriate live path).  
7. **Commit/push**; append human journal + run record.  
8. **Park residuals** in journal for next cycle (do not pretend zero debt).

See also: `Skill Foundry/planning/portfolio-program/SLEEP-SESSION-RUNBOOK.md` + this folder.
