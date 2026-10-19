# Ecgberht — Family-Finances project butler

**Name:** Ecgberht (historical: King of Wessex, d. 839; also spelled Egbert / Ecgbert).  
**Role metaphor:** household steward / JARVIS — not the builder, not the planner-of-one-slice.  
**This file is the source of truth** for the *overall* arc of this project across sessions and context contractions.

---

## What Ecgberht is (and is not)

| Ecgberht **is** | Ecgberht **is not** |
|-----------------|---------------------|
| The long-horizon memory of *this* project | A coding agent that invents features mid-build |
| Owner of the multi-effort roadmap and next action | A replacement for Crucible or Foreman |
| Chooser of **tool depth** per effort (LITE / FULL / SPIKE-FIRST; standard vs heavy) | Itself a Crucible stage or Foreman wave |
| Keeper of done / doing / blocked / waiting-on-John | A second copy of wave-level EXECUTION-LOGs |
| The handoff that makes contraction *feel* continuous | Chat transcript or agent memory alone |

**Rule:** any session that touches Family-Finances long work **reads this file first** and **updates it before contracting or ending a meaningful stretch of work**. If Ecgberht is current, a new context window should not need to reinvent the workflow.

### Relationship to the trio

```
Ecgberht (this file)          ← which effort, why, tool depth, gates, data waits
    │
    ├─► Crucible (LITE|FULL|SPIKE)  ← plan one effort → Foreman-ready doc-trio
    ├─► Foreman (standard|heavy)    ← build that frozen plan wave-by-wave
    └─► Ops / data gates            ← import Jane’s files, classify, live tests with humans
```

Crucible/Foreman answer: *how do we safely plan and build this slice?*  
Ecgberht answers: *what slice is it, what comes after, what are we waiting on, and are we still pointed at the family’s real goal?*

### Status-update contract (10-minute cadence)

When a long run is active, chat updates use the **locked global status table** first (user-global AGENTS.md), then an **Ecgberht addendum**:

```
── Ecgberht ──
Project   Family-Finances · <one-line north-star of the whole arc>
Effort    <current effort id + name> · tool depth <LITE|FULL|SPIKE × Foreman tier>
Done      <bullets since last tick / this session>
Next      <immediate next action>
Waiting   <human/data blockers, or none>
Backlog   <next 1–2 efforts after this one>
```

Before context contraction or session end: update **Done / Next / Waiting / Last updated** below so the next window continues without reconstruction.

---

## Whole-project North Star (the concluding level)

> John and Jane can **trust the past**, **plan the next 12 months of cash** (routine spend, trips, and known obligations like helping Ben with the construction loan), **see whether free cash is tight enough to threaten retirement withdrawals**, **import and reconcile new data (including Jane’s Quicken exports) without fear**, and **clear uncategorized transactions by talking** (and later voice) instead of a Quicken-style detective slog — with every material plan decision written down.

**Out of scope for “done” of this arc (unless Ecgberht promotes them later):** multi-user cloud product, tax engine, automated bank login scraping as primary path, full replacement of Quicken for every historical edge case on day one.

**Already earned (do not re-litigate):** ledger hardening complete; month totals SSOT; import gates; dashboard correctness waves; residual API cache-drift fix shipped (`190da58`). Strong **ledger**; under-built **budgeter + classify loop**.

---

## Tool-depth judgment (how Ecgberht picks ceremony)

| Signal | Prefer |
|--------|--------|
| Clear goal, reversible, few modules, user needs usable result soon | **Crucible LITE → Foreman standard** |
| Unknown data shape / “will this import even work?” | **SPIKE-FIRST**, then re-band |
| New trust surface, false-liquidity risk, multi-phase platform | **Crucible FULL → Foreman standard/heavy** |
| Pure ops on existing tools (drop file, run import, report) | **No Crucible** — ops checklist under Ecgberht |
| Advisory cash-stress numbers without productizing | **financial-analyst** skill / conversational, not a build |

---

## Effort roadmap (ordered)

Status legend: `PENDING` · `READY` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `DEFERRED`

### E0 — Ecgberht standing up · DONE (this file)
- Establish this butler file and the arc below.
- **Done when:** sessions can resume from this file alone.

---

### E1 — Rolling cash planner MVP (integrated) · READY  
**Tool depth:** **Crucible LITE → Foreman standard** (first run of that pairing on this project)  
**Why first:** John’s stated priority — usable forward plan for trips, Ben cash drag, and “do we dip into retirement?” without waiting on the full trust platform.  
**Why LITE not FULL:** product is new but *bounded*; quant seeds already exist; mistakes are reversible if schema is upgrade-friendly; FULL draft already lives as later fuel (E4), not this contract.

**In scope (MVP):**
- Rolling ~12-month forward view seeded from history (estimate · as-of · simple ranges).
- Dated **events** (contractual / replacement / discretionary): trips, taxes/insurance-like items, **Ben construction-loan cash contribution** (amount/timing as John provides).
- **Talk-to-plan** via agent loop (propose → dry-run impact → confirm → log) — no in-app LLM required.
- Light decision log (DB-backed preferred if cheap; markdown acceptable if plan says so).
- Integrated into Family-Finances (CLI and/or thin dashboard surface) — not orphan scripts only.
- Working-copy `LEDGER_DB` discipline for any write path; live DB only with snapshot/tripwire.

**Out of scope for E1 (parked for E4 unless promoted):**
- Full free-to-spend / earmark false-liquidity platform, seed-gate provenance theater, month-close ritual, escrow migration, in-app chat UI, Monte Carlo.

**Reuse as spike evidence, not frozen design:** uncommitted `budget_forward.py`, thin `budget_events` DDL, trip stubs in `budget-decisions.md`, and the large `dashboard-plan/` FULL drafts (Grasscatcher for E4).

**Done when:** John can ask in chat for the next 12 months with known events, see month-by-month routine + event set-asides + honest uncertainty labels, add/change an event by conversation, and trust the result enough to discuss Ben + trips with Jane.

**Human inputs during E1:** rough Ben monthly/peak obligation; trip list refinements; income assumptions if free-cash headline is in LITE scope (else honest “spend-side only” caveat).

---

### E2 — Data intake: Jane’s Quicken + bank refresh · PENDING  
**Tool depth:** **SPIKE-FIRST** (short), then **ops + LITE tooling only if spike finds gaps**  
**Why this order:** E1 can seed from *current* ledger history; E2 refreshes ground truth and unlocks classify testing. Can **overlap late E1** once MVP shape is frozen (data drop does not require planner complete).

**In scope:**
- Receive Jane’s latest Quicken export(s) + any bank CSVs/PDFs.
- Snapshot live DB → working copy → import under existing gates.
- **Compare** Quicken vs ledger (coverage, date range, amount mismatches, category disagreement samples).
- Report: new rows, dups skipped, uncategorized count, open reconcile issues.
- Document drop-folder convention for Jane (so repeat is boring).

**Done when:** latest household data is in the ledger (or explicit gaps listed), Quicken comparison report exists, uncategorized pile size is known for E3.

**Waiting on John/Jane:** actual files in `downloads/` (or designated path).

---

### E3 — Automated + human-verified categorization · WAITING (promoted 2026-08-03)
**Tool depth:** **not yet callable** — `depth-suggest` refuses while the process contract is undefined. Expected **Crucible LITE → Foreman standard** once Gate 2 answers land. Voice stays deferred.
**Depends on:** E2 (or a partial batch) so there is a real uncategorized set to exercise. **Also blocked on Gate 2 process answers.**

> **Promotion note (2026-08-03):** John raised this from "speed-up" to a first-class goal — *accurate, human-verified* expense categorization, expedited. That reframes the done-when: not just "clear the pile faster" but "every category is either rule-derived or human-confirmed, with an auditable trail, and the auto hit-rate is measured and rising." A **measurement wave comes first** — we do not know today's auto-categorization hit-rate on fresh data, so we cannot claim an improvement.
>
> **Sibling step E3b — Budget refinement loop** (`roadmap.json`, status `proposed`): E1 seeds targets and E1's F4 *struck* baseline overrides, so "refine the budget month to month" has **no owner** in the current plan. E3b is where that ritual gets designed, or it gets folded into E4.

**In scope:**
- Conversational review of uncategorized / weak-category rows: show payee, amount, date, account, rule hits, web/merchant hints when useful.
- Propose category + optional new `rules/categorization.yaml` entries; confirm → apply on working copy.
- Batch “same merchant → same category” promotions.
- Measure: time-to-clear N transactions vs old Quicken ritual (qualitative OK).

**Out of scope for first E3:** full speech-to-text product, automatic web scrape without confirm, silent bulk reclassify of protected history.

**Done when:** John/Jane can clear a real uncategorized batch by talking, with rules improving so the pile shrinks next month.

---

### E4 — Budget platform trust layer (full planner maturity) · DEFERRED  
**Tool depth:** **Crucible FULL** (or resume/amend existing Stage 1/2 in `dashboard-plan/`) → **Foreman standard or heavy**  
**Depends on:** E1 proven in real use (so FULL builds on lived requirements, not only Shark-Tank theory).

**In scope (from existing MASTER / Stage-2 drafts, to be re-locked not blindly executed):**
- Free-to-spend after earmarks (no false liquidity).
- Seed gates, provenance, method-tagged ranges, decision-log integrity.
- Month-close retrospection; earmark backing vs liquid balances.
- Dashboard forward views with trust vocabulary.
- Absorb/replace E1 MVP schema cleanly (migration wave, not second brain).

**Done when:** the MVP planner is no longer “light”; it is the honest, gated planning surface of the ledger.

---

### E5 — Retirement & stress clarity (decision support) · PENDING  
**Tool depth:** mostly **ops + financial-analyst / conversational** on top of E1/E4 numbers; productize only if a permanent report is needed (then LITE)  
**Depends on:** usable forward cash (E1 minimum) + liquid/retirement balances visibility.

**In scope:**
- Scenario: baseline + Ben obligation + trips → months of stress → whether liquid cash covers without retirement draw.
- Explicit assumptions list (income, Ben amount, one-time vs monthly).
- Spouse-readable summary markdown.

**Done when:** John can answer “do we need retirement money for this plan?” with stated assumptions, not gut feel alone.

---

### E6 — Hygiene & production polish (standing) · PENDING  
**Tool depth:** ops / small LITE only  
- Scheduled DB snapshot task (admin elevation — known HALT).  
- Service restart so `/version` matches HEAD when needed.  
- Clear deferred NULL-category rows still open from earlier work.  
- Commit/clean prototype debris once E1 plan supersedes it.

---

## Current pointer (update every session)

> **Engine truth (new 2026-08-03):** the campaign now has a typed **Strip** (`strip.json`) and an
> append-only **Roadmap** (`roadmap.json`, 7 steps / 13 events). Face prose below is the human narrative;
> the Strip owns clocks and the Roadmap owns step status. Read them with
> `node bin/ecgberht.mjs status|roadmap-show --project C:/dev/Family-Finances` from the ecgberht skill dir.
> Previously this file was prose-only, so the engine reported the `face_prose_only` gap.

| Field | Value |
|-------|--------|
| **Last updated** | 2026-08-03 |
| **Active effort** | E1 — Rolling cash planner MVP (E3 promoted to first-class this session) |
| **Phase** | **Stage 2 awaiting implementation-plan approval** (LITE round-cap HALT; BEST-DRAFT packaged; locate-plan GREEN on root) |
| **Tool depth** | Crucible LITE → Foreman standard (on plan approval) |
| **Plan dir** | `e1-planner-lite/` |
| **Master Plan** | **APPROVED** — `MASTER-PLAN-APPROVED.md` |
| **Implementation Plan** | `e1-planner-lite/handoff/IMPLEMENTATION-PLAN.md` (from Stage-2 BEST-DRAFT; pytest -v gate fixed) |
| **Foreman config** | Root `foreman.config.json` points at E1 handoff (hygiene config backed up to `foreman.config.hygiene.json.bak`) |
| **Seat stamp** | coding=grok · review=grok · **cross_model:false** |
| **Blocker** | Human: approve Implementation Plan → Foreman; E2 waiting on data |
| **Do not start** | Foreman until John approves Implementation Plan |
| **Related (out of this project)** | Next-gen design under `C:\dev\Ecgberht\` (other session) |

### Session checklist (any agent)

1. Read this file (and `AGENTS.md` project rules).  
2. Confirm **Active effort** and **Phase**.  
3. Do only that effort’s next action unless John reorders.  
4. Before contraction / end: update **Last updated**, **Phase**, Done notes, Waiting.  
5. Long-run status: locked 10‑min table **plus** Ecgberht addendum.

### Just done
- Master Plan approved; Stage 2 LITE finished (~9 min): 7 waves · Shark r1 + revise · round-cap.
- Engine emit had broken `node --test` gate; **human package fix**: BEST-DRAFT → handoff with `pytest -v`; locate-plan **GREEN** (7 waves).
- Stage-2 ≥2-agree blocker (showable decision receipts) folded into W5/W6 of BEST-DRAFT.
- **2026-08-03:** Ecgberht stood up properly — Strip + append-only Roadmap created; live-DB/plan/test/git state scanned into Strip instruments; **E3 promoted** (John made verified auto-categorization a first-class goal) and **E3b budget-refinement loop** added as a new proposed step. `depth-suggest` returns **refuse** while `human_wait` is blocking — correct: commission nothing until John answers.

- **2026-08-04:** Process contract closed — all 13 questions answered → `E3-PROCESS-CONTRACT.md` (D1–D13). E3, E3b, E7 flipped to `planned` with receipts. Two findings came out of John's answers, not the plan: **Category Alignment is a joint product feature** (not a cleanup chore), and **D8 exposed a defect in approved E1 W2** (history seed averages one-off envelope spend into routine targets).

### Next concrete action
1. **John:** decide the **D8 / W2 amendment** (amend E1 now, or ship and fix in E3b) — then approve the Implementation Plan → commission Foreman standard on E1.
2. **John/Jane:** drop Quicken + Jun–Aug bank files → E2 ops run (unblocks E3's measurement wave).
3. **Then:** one Crucible LITE run planning **E3 + E3b together** off `E3-PROCESS-CONTRACT.md` (same loop from the user's side; must reuse the E1 W5 receipt spine, not a second decision log).
4. E7 sequenced after E1; E4 parked; E5–E6 planned.

---

## Artifact map (where other docs sit)

| Artifact | Role vs Ecgberht |
|----------|------------------|
| `ECGBERHT.md` (this file) | Overall arc + next action |
| `HANDOFF.md` | Legacy ledger ops handoff (aging; prefer Ecgberht for arc) |
| `HANDOFF-2026-07-17-budgeting-stage2-agy.md` | Historical budgeting handoff |
| `dashboard-plan/MASTER-PLAN.md` + `stage2/` | FULL planner design — **E4 fuel**, not E1 contract |
| `foreman-plan/` | Completed hardening — reference only |
| `budget_forward.py`, `budget-decisions.md` | E1 spike evidence |
| Per-effort `*-plan/` doc-trios | Created by each Crucible run; linked here when live |

---

## Open human items (global)

### Gate 1 — unblocks E1 build today
- [ ] **Approve the 7-wave E1 Implementation Plan** (`e1-planner-lite/handoff/IMPLEMENTATION-PLAN.md`) → Foreman standard
- [ ] Approve or amend this Ecgberht effort order (E3/E3b now promoted)

### Gate 2 + Gate 3 — ✅ CLOSED 2026-08-04
All 13 process questions answered → **`E3-PROCESS-CONTRACT.md` (D1–D13)**. That file is the Crucible Stage-0
intake for E3 + E3b; it records John's **decisions**, not proposals — Crucible plans against them and does not
re-litigate them. Headlines:

- **Tiered trust** (auto vs human-confirmed provenance) · **merchant-grouped** review · **weekly target, monthly floor**
- **Budget Category Alignment** — a joint John+Jane *product feature* (detect → offer at session → remember dismissals → on-demand), not an engineering cleanup
- **Split on demand**, never forced · **either spouse** verifies, stamped · **always changeable, always audited**
- **D8 routine vs envelope** — routine spend is history-seeded; trips/one-offs are forward-declared and must **not** be averaged into monthly targets
- Sustained-variance offers · **group-level** sessions · **ring-fenced event money** · "changes since last session" opener
- **New scope E7** — business reimbursement receivable tracker (Penn State + AXMRA)

### ⚠️ Gate 2b — one decision this opened (needs John)
- [ ] **D8 forces an E1 amendment.** W2's history seed has **no routine/envelope filter**, so past one-offs (the Christmas ski trip, past flights) would be averaged into monthly routine targets — the first seeded budget would be wrong in exactly the way John described. Fix is a `treatment` flag per category (`routine|envelope|excluded`) + a seed filter — one column, LITE-compatible. **Amend E1 W2, or ship E1 as-is and fix in E3b?**

### Gate 4 — data + numbers
- [ ] **Ben:** expected monthly and/or lump cash help (range is fine)
- [ ] **Jane:** latest Quicken export path / drop into `downloads/`
- [ ] Bank CSVs/PDFs for **Jun–Aug 2026** (newest ledger transaction is 2026-06-07 — ~2 months stale)
- [ ] Known 12-month events beyond the two trip stubs (insurance, tuition, taxes, replacements)
- [ ] Optional: cash/income **anchor** figure, so E1's tightness readout can show a residual instead of `N/A`

### Gate 5 — ops
- [ ] One elevated shell to install the `LedgerSnapshot` scheduled task (`foreman-plan/notes/W12-snapshot-task-HALT.md`)

---

*Ecgberht does not build. Ecgberht remembers the kingdom’s campaign order and keeps the stewards (Crucible, Foreman, ops) pointed at the right battle.*
