# Portfolio triage + band-thinning evaluation (2026-07-22)

**Context:** After cf-slick C/F ship. 2D triage package lives at `foundry/triage/`.  
**Axes:** tier `{Heavy, Standard}` × depth `{FULL, LITE, SPIKE-FIRST}` + lock before work.

## 1. Triage package status (NS-01)

| Layer | Status | Notes |
|-------|--------|-------|
| Shared core + vocab + lock | **Built** | `core.mjs`, `lock.mjs` |
| Mapping tables (11 skills) | **Built** | `mapping.mjs` knobs by depth |
| Crucible / Foreman / RP **wires** (package modules) | **Built** | Not proof every live entrypoint imports them |
| Generated prose blocks (8 skills) | **Built** | `generated/*.triage-block.md` |
| Live trio engines on disk (`<path> | **Partially wired** | C/F band profiles live; full `@foundry/triage` import path needs verification per call site |
| Expanded package suite | **Incomplete** | Foreman DONE under-gated historically; re-prove suite after gate alignment |
| All Foundry skills **runtime** lock | **Not done** | Entry-points exist; skills may not call them |

**Verdict:** Package is a **substrate**. Trio is **closest** to connected. Foundry skills mostly need **thin runtime hooks + SKILL ceremony thin**, not a second rubric.

---

## 2. Skill-by-skill evaluation

### A. Trio (engines) — scale ceremony like C/F

| Skill | Triage 2D | Band thin (LITE/SPIKE/FULL) | Recommendation |
|-------|-----------|----------------------------|----------------|
| **crucible** | Stage-0 recommend+lock; handoff emit | **Done (cf-slick)** | Keep; verify Stage-0 always passes `depth` into Stage-1; journal any bypass |
| **foreman** | Inherit only; LITE reviewers ≥1 | **Done (inherit + gate honesty)** | Keep; smoke live handoff from Crucible with `triage.depth` |
| **researchPrime** | Package wire: intake extension only; governance unchanged | Mapping has maxRounds / adjudication by depth; **live intake may not call wire** | **P0:** Wire intake → `researchprime-wire` + lock; **P0:** enforce LITE fewer rounds / skip adjudication; SPIKE = bounded recon then FULL/LITE; **Shark** on path after wire |

### B. Foundry engine-class skills — thin ceremony, wire triage

| Skill | Today | Thinning recommendation (not diluting) | Triage hook |
|-------|--------|----------------------------------------|-------------|
| **gandalf** | Heavy map-reduce + many seams; huge journal | **LITE:** single-shard or short context path, 1 refuter; **SPIKE:** scoped recon then full; **FULL:** current map-reduce + concurrent refuters | `entry-points` + `gandalfKnobs`; lock before score stamp; inject generated block into SKILL |
| **jumper** | Ideation + Gandalf compose | **LITE:** one SCAMPER pass + 1 kill-filter; **SPIKE:** problem-frame probe; **FULL:** full compose | Same entry-points; tier matches Gandalf seat family |
| **ramanujan** | Partner + optional certifier | **LITE:** direct answer + honesty labels only; **SPIKE:** formalize one claim; **FULL:** certifier arm when requested | Lock depth before certifier spend; knobs for certifier on/off |
| **tidy-idy** | Full engine + panel; polish in flight | **LITE:** scan+triage panel only, skip deep reorg swarm; **SPIKE:** sample folder probe; **FULL:** full dual-launch + adversarial review | Entry lock before apply; depth changes panel ceremony not safety floor |
| **zombie-hunter** | Safe-to-arm reaper + UX | **LITE:** read-only census + abstain; **SPIKE:** freeze-only probe; **FULL:** arm after evidence ladder | Never thin **abstain-by-default** safety; only thin UI/telemetry ceremony |
| **literature-review** | Snowball + PRISMA + RP | **LITE:** seed set + extract only; **SPIKE:** pilot snowball N papers; **FULL:** PRISMA + RP adversarial | Compose RP intake triage; depth → paper budget / rounds |

### C. Prose until engines exist (do not pretend runtime)

| Skill | Today | Recommendation |
|-------|--------|----------------|
| **legal-beagle** | Prose + citation-lint; `runtime_enforced:false` | Keep honest prose + generated triage block; **next major:** Legal engine (orchestrator / Shark / Judge / grounded sources) — NS-02 |
| **financial-analyst** | Python graph + Excel; prose triage | Keep library; thin **report ceremony** by depth later; **next major:** Financial engine (same architecture family as C/F); **icon refresh** (visual only) |

### D. Supporting (not NS-01 11)

| Skill | Note |
|-------|------|
| **agy-dispatch** | Transport — no triage thin; keep robust |
| **figure-designer** | Specialist — optional LITE one-shot vs FULL review pass |

---

## 3. Recommended program order (best-in-class portfolio)

| Phase | Work | Outcome |
|-------|------|---------|
| **0** | C/F cf-slick **shipped** | Band-honest engines |
| **1** | Verify/wire **live** Crucible+Foreman+RP to `@foundry/triage` | 2D lock real on trio |
| **2** | Band-thin + triage entry for **gandalf, jumper, ramanujan, tidy-idy, zombie-hunter, literature-review** (one skill per sleep cycle or small batch) | Foundry skills match LITE/SPIKE/FULL + 2D lock |
| **3** | **Legal engine** build (orchestrator + Shark + Judge + source integrity) | NS-02 |
| **4** | **Financial engine** build (same architecture; exact Decimal already strong) | NS-03 |
| **5** | Continuous sleep-loop from journals | No permanent “done forever” |

---

## 4. Thinning checklist (per skill)

For each skill in Phase 2:

1. Read **NORTH-STAR** / SKILL — list load-bearing vs ceremony.  
2. Define **LITE / SPIKE / FULL** profiles (mirror `band-profile` idea).  
3. Call **`@foundry/triage` recommend + lock** at intake (or inherit from handoff).  
4. Map knobs from `mapping.mjs` (or extend).  
5. Unit tests for inequality LITE < FULL on at least one knob.  
6. **Shark Tank** on the thinning (not dogfood).  
7. Journal + promote.

**Never thin:** safety floors (zombie abstain, tidy protect classes, legal citation rules, financial exactness).

---

## 5. Legal & Financial engine note

Build **after** Phase 1–2 so engines inherit:

- Orchestrator (top coding-family) steers  
- Workers produce grounded artifacts  
- Concurrent Sharks / reviewers  
- Judge + user convergence  
- 2D triage lock at intake  
- Journals  

Do **not** bolt a FULL C/F clone onto un-triaged portfolio chaos.
