# Ecgberht architecture sketch (working draft — pre-synthesis)

> ## ⛔ SUPERSEDED — 2026-07-25
> This sketch predates the E5 engine and the E9/E10 synthesis. It is kept as history only.
> **In particular, any “portfolio store” language here (`~/.anchor/ecgberht/portfolio-heartbeat.json`, `capacity.json`, `attention-rank.json`) is DEAD** — superseded by **OneLedgerTwoViewports**: the E5 engine is the sole store; portfolio may cache **strip-first projections only, with zero independent write authority** (Gandalf d-8 / annex A6).
> Do **not** import this file's language into Crucible/Foreman inputs. Live truth: `SKILL.md`, `research/e9-e10/RECOMMENDATION.md`, `research/e9-e10/MACHINE-CONTRACT-ANNEX.md`.

**Status:** SUPERSEDED (see banner) — was: session brainstorm + prior-art synthesis  
**Date:** 2026-07-23  
**Spelling:** Ecgberht only

---

## 1. Problem shape

John’s agent stack already has excellent **slice** tools (researchPrime → Crucible → Foreman; Gandalf; Jumper). What is missing is a durable **campaign owner**:

- Across sessions and context contractions, *which effort is live?*
- Across tools, *how much ceremony does this slice deserve?*
- Across projects, *what should attention go to today?*
- Across time, *what’s coming on the calendar and does prep exist?*

Today the seed answer is a **single markdown file** (`Family-Finances/ECGBERHT.md`). That works. Productizing it without recreating a expensive multi-agent swarm is the design problem.

---

## 2. Prior art (do not ignore)

### 2.1 Family-Finances pilot (behavioral gold)

Path: `<path>

- Clear is/is-not table vs trio  
- Tool-depth matrix (LITE / FULL / SPIKE / ops / advisory)  
- Effort roadmap E0–E6 with done-when and waiting-on  
- Current pointer table (last updated, active effort, phase, blockers)  
- Status-table addendum contract  
- Grasscatcher via deferred efforts + named parks  
- Rule: read first, update before contraction  

**Lesson:** ceremony is *chosen per effort*, not defaulted to FULL.

### 2.2 Agentic-Home / OpenClaw Ecgberht lineage

- `project-manager` skill — PM loop, `.pm/state.json`, what-now ranking, session logs, Oranges posture  
- `peek_pm_memory` — portfolio read without DB locks  
- `morning-briefer` — start-of-day  
- `FACTS-Ecgberht-IPC.md` — delegate writes; peek reads  
- `CRITIQUE-Alpha-b0v1-Ecgberht-2026-05-21.md` — **load-bearing critique:**  
  - Avoid default-gateway tax (double turn cost/latency)  
  - Avoid 1 + 9 PM + N specialist wallet explosion  
  - Prefer **skill-first**, agent-later  
  - HEARTBEAT over N× full memory sweeps  
  - Cognition “Don’t Build Multi-Agents” for overlapping siblings  

**Lesson:** portfolio Ecgberht should be a **skill + thin state**, not a permanent Opus router on every chat.

### 2.3 Anchor (target host, next-gen)

- Work dashboard + per-project open → second dashboard  
- Model prefs already global (`coding_family` / `review_family`)  
- Jobs/telemetry exist; Ecgberht should **read** run state, not replace job_runner  

**Lesson:** Ecgberht is a **control surface + memory**, not a second orchestration engine.

---

## 3. Recommended shape (v0 → v2)

### v0 — File steward (now / Family-Finances)

```
<project>/ECGBERHT.md          # SSOT campaign file
<project>/eN-*/                 # per-effort plan dirs (Crucible outputs)
```

Any session: read → act on Active effort only → update pointer.  
**Ship status:** live pilot.

### v1 — Foundry skill (project Ecgberht)

```
~/.claude/skills/ecgberht/   (or Skill Foundry install path)
  SKILL.md                   # protocol + is/is-not + compose rules
  bin/
    status.mjs               # parse project state → status block
    next.mjs                 # ranked next actions (local ranking)
    update-pointer.mjs       # structured patch of pointer fields
    depth-suggest.mjs        # heuristic LITE/FULL/SPIKE from signals
  schema/
    project-state.schema.json
  templates/
    ECGBERHT.md
```

**State dual-write (honest):** keep human-readable `ECGBERHT.md` as SSOT *or* generate MD from JSON — pick one direction in researchPrime (recommendation: **MD-primary with YAML front-matter or machine section**, so humans and agents both win).

**Commissions (never reimplements):**

| Need | Commission |
|------|------------|
| Research / best-in-class | researchPrime |
| Plan a slice | Crucible (depth from Ecgberht) |
| Build a frozen plan | Foreman |
| Deep critique | Gandalf |
| Divergent ideation | Jumper (rare; grasscatch most ideas) |
| Ops classify / finance math | domain skills |

### v2 — Portfolio Ecgberht + Anchor panels

```
~/.anchor/ecgberht/
  portfolio-heartbeat.json   # compact cross-project summary (≤ few KB)
  capacity.json              # subscription/token headroom (sources TBD)
  calendar-cache.json        # later
  attention-rank.json        # last computed ranking

Anchor UI:
  /work                      # portfolio Ecgberht strip + project cards
  /project/:id               # project Ecgberht panel + run history
```

**Heartbeat rule (from prior critique):** each project Ecgberht updates a **small heartbeat blob** on pointer change; portfolio never opens 10 full campaign files unless drilled in.

---

## 4. Core loops

### 4.1 Session start (project)

1. Detect project root (Anchor project id / cwd / `ECGBERHT.md`).  
2. Render: North star one-liner · Active effort · Next · Waiting.  
3. If long run active → attach status cadence (existing global rule).  
4. Offer one recommended next action with **why**.

### 4.2 Idea intake (soft-vet)

```
idea → (keep in current effort | grasscatcher + reason | drop + reason)
```

Cap ceremony: no Shark Tank unless John asks or Ecgberht promotes to “needs Crucible.”

### 4.3 Tool-depth judgment

Signals (from pilot matrix):

- Reversible + bounded + need soon → LITE  
- Unknown data shape → SPIKE-FIRST  
- Trust surface / false-liquidity / multi-phase platform → FULL  
- Pure import/ops → checklist only  
- Advisory numbers → conversational / financial-analyst, not build  

### 4.4 Portfolio attention ranking (sketch)

Score candidates with:

- Blocker waiting on John (high if time-sensitive)  
- Live run needs attention (HALT / approval gate)  
- Calendar proximity (prep needed)  
- Stale pointer (no update > N days while ACTIVE)  
- Capacity risk (subscription low)  
- Strategic priority tags John sets  

Output: top 3 across portfolio with one-line why each — **suggestions, not auto-delegation** in v1.

---

## 5. Anchor integration (next-gen only)

| Surface | Behavior |
|---------|----------|
| Work dashboard | Portfolio Ecgberht: project tiles, attention list, capacity meter |
| Project open | Project Ecgberht: roadmap, grasscatcher, launch buttons for Crucible/Foreman **with depth pre-filled** |
| Job runner | Read-only status into Ecgberht pointer when runs start/halt |
| Calendars | Later: Google/Outlook connectors → prep cards |
| Email | Later: Gmail/Outlook signals → action proposals (confirm-before-mutate) |
| Token usage | Pull from known CLI/subscription telemetry; warn before cliff |

**Launch-cut boundary:** zero of this must ship in the 48-hour shareable Anchor; design docs live here under `<path>

---

## 6. Failure modes to design against

| Failure | Mitigation |
|---------|------------|
| Double-orchestrator (Ecgberht reimplements trio) | Hard is/is-not; commission-only |
| Cost tax on every chat | Skill-on-demand + heartbeat; not default Opus router |
| Stale campaign file | Session end checklist + optional Anchor prompt on project close |
| N× memory reads | Heartbeat registry |
| Scope creep into FULL always | Depth matrix + “promote later” grasscatcher |
| Silent multi-agent divergence | One active effort per project; no sibling builders without Foreman topology |
| Name drift (“expert”) | SKILL.md + canary string `Ecgberht` |

---

## 7. Open design questions (for researchPrime / Jumper / Gandalf)

1. **SSOT medium:** pure MD vs JSON+generated MD vs SQLite project db?  
2. **Portfolio store location:** `~/.anchor/ecgberht` vs Skill Foundry data vs OpenClaw agents?  
3. **When does soft-vet become Crucible?** threshold rules  
4. **Calendar/email:** first connector and threat model (tokens, privacy)  
5. **Capacity telemetry:** which CLIs expose usable remaining-quota signals?  
6. **How much of `project-manager` skill merges vs Ecgberht supersedes?**  
7. **JARVIS UX patterns** that transfer without sci-fi overpromise  

---

## 8. Immediate build path (after design pressure)

1. Freeze vision + architecture after researchPrime plan approval + Jumper survivors + Gandalf read.  
2. Scaffold Foundry skill skeleton (SKILL.md + schema + templates) under Skill Foundry — **not** launch Anchor tree.  
3. Back-port Family-Finances pilot to schema-compatible template without breaking E1.  
4. Anchor next-gen: read-only project panel that renders `ECGBERHT.md` / heartbeat.  
5. Portfolio heartbeat writer + morning brief composition.  
6. Calendar/email/capacity only after (4–5) are real.
