# Ecgberht — next-gen steward (this campaign’s butler)

**Latest improvement review (2026-09-10):** [Steward refinement lifecycle review and plan](../Skill%20Foundry/planning/steward-refinement-2026-09-10/REVIEW-AND-PLAN.html), with editable source beside it. Cross-project journals and current-source probes support programmatic feedback/revision/acceptance, one current reading register and preserved North Star. Grok's findings are incorporated; journal 0114 holds provenance and review limits. This is a reviewed proposal awaiting John's design feedback, not a production change, accepted new goal or takeover of another active run. Future Crucible/Foreman improvements are separately journaled as 0102/0131 in their own skill journals.

**Name:** **Ecgberht** (King of Wessex, d. 839; also Egbert / Ecgbert).  
When John says “expert” (voice-to-text), he means **Ecgberht** — always.  
**Role metaphor:** household steward / JARVIS — not the builder, not the planner-of-one-slice.  
**This file is the source of truth** for the *overall* arc of **building the Foundry Ecgberht skill + engine** across sessions.

**Folder:** `<path>  
**Not in scope:** 48h shareable Anchor launch cut; Family-Finances day-to-day ops.

### Glossary (locked 2026-07-25 — John)

| Term | Means | Do **not** confuse with |
|------|--------|-------------------------|
| **Self-run** | Using Ecgberht (or any skill/product) on **itself** / our own campaigns to prove it works | Adversarial review |
| **Shark Tank** | Adversarial multi-reviewer ceremony (Crucible sharks, RP governed rounds, etc.) | Self-run |

Never say “dogfood” in operator-facing or campaign prose — use **self-run**. Keep **Shark Tank** only for adversarial runs.

---

## What Ecgberht is (and is not) *for this campaign*

| Ecgberht **is** | Ecgberht **is not** |
|-----------------|---------------------|
| Long-horizon memory of *this* design/build effort | A coding agent inventing features mid-build |
| Owner of multi-effort roadmap + next action | Replacement for Crucible or Foreman |
| Chooser of **tool depth** per effort | Itself a Crucible stage or Foreman wave |
| Keeper of done / doing / blocked / waiting-on-John | Chat transcript or agent memory alone |
| The handoff that survives context contraction | The OpenClaw / full agent harness product |

**Rule:** any session that works on next-gen Ecgberht **reads this file first** and **updates it before contracting or ending meaningful work**.

### Relationship to other tools

```
Ecgberht (this file)     ← which effort, why, tool depth, gates
    │
    ├─► Jumper           ← rare divergent architecture ideas
    ├─► researchPrime    ← best-in-class evidence + recommendation
    ├─► Gandalf          ← deep second read on the design package
    ├─► Crucible         ← plan one effort → Foreman-ready docs
    ├─► Foreman          ← build frozen plan
    └─► Anchor (later)   ← UI panels only; not the logic SSOT
```

**Product we are building (researchPrime recommendation, locked intent):**  
Foundry **skill + deterministic engine** on Claude/Gemini/Grok **subscriptions** · Face + Strip dual-surface · portfolio strip ranking · compose trio — **not** OpenClaw harness (that is a **separate later product**).

### Status-update contract (MANDATORY)

Whenever an **Ecgberht-campaign long run** is active (Foreman, Crucible, Jumper, researchPrime, …):

1. Post the **locked global Status table** first (user-global AGENTS.md).  
2. **Always** append the **Ecgberht addendum block at the bottom** of that update — never omit it, never only put campaign context inside the Summary row.

```
── Ecgberht ──
Project   Ecgberht next-gen · Foundry skill+engine (steward, not harness)
Effort    <id + name> · tool depth <…>
Done      <since last tick>
Next      <immediate next>
Waiting   <human/blocker or none>
Backlog   <next 1–2 efforts>
```

Spelling in every block: **Ecgberht** (not “expert”).

---

## Whole-project North Star

> John has a **single, elegant steward capacity named Ecgberht**: for each project, durable campaign memory (what we’re aiming at, which effort is live, tool depth, grasscatcher, next action); across projects, honest attention ranking and later calendar/capacity hooks — implemented as a **Foundry skill with an engine** on existing **subscriptions**, commissioning research/plan/build/critique skills when needed, never becoming a permanent multi-agent harness or a second Crucible/Foreman.

**Out of scope for this arc (unless Ecgberht promotes later):**  
OpenClaw substrate · full agent harness product · calendar/email OAuth as first ship · launch-cut Anchor merge · per-project always-on PM agent swarm · default gateway on every chat.

### Grasscatcher ledger (W6 — deferred product scopes, receipt shape)

Permanent non-goals (not campaign soft-vet parking). Named with receipt shape so MVP cannot silently implement them as verbs/engine surfaces:

| Deferred | Why (receipt shape) | Later owner |
|----------|---------------------|-------------|
| OpenClaw harness product | Multi-agent substrate is a separate product | separate-harness-product |
| calendar/email OAuth | Connectors out of LITE MVP | connector-product |
| Anchor v1.0.x release edits | Public freeze tree must stay untouched | anchor-release-owners |
| default chat gateway | No gateway tax / personality product | chat-product |
| Family-Finances domain | Domain features live elsewhere | family-finances-project |
| Anchor 1.1 portfolio UI | UI is 1.1 / next-gen only | anchor-1.1 |
| launch-tree merge | Launch orchestration foresight, not MVP | launch-orchestration |

SSOT: `fixtures/grasscatcher-ledger.json` · engine: `engine/grasscatcher-ledger.mjs` · Strip labels in `strip.json`.

### Stage-2 freeze (W6)

LITE skill+engine MVP freeze set: locked file tree, schemas, fixture matrix, verb contracts, heal law, A1 discovery, non-goals. `fixtures/stage2-freeze.json` · `engine/stage2-freeze.mjs`.

**Already earned (do not re-litigate):**  
- Early example shape: Family-Finances `ECGBERHT.md` (read-only reference)  
- Vision + architecture sketch in this folder  
- Jumper survivor: Face + Strip (`ideation/JUMPER-SURVIVOR-face-strip.md`)  
- researchPrime complete: skill+engine recommendation (`research/RECOMMENDATION.md` + deliverables)  
- W1–W5 engine (skill pack, Face+Strip, verbs, dispatch, commission/seating)

---

## Tool-depth judgment

| Signal | Prefer |
|--------|--------|
| Bounded design pressure / second read | **Gandalf** (live if agy; else honest Tier-1) |
| Best-in-class evidence | **researchPrime** |
| Divergent architecture options | **Jumper** (rare) |
| Clear skill build, reversible schema | **Crucible LITE → Foreman standard** |
| Trust surface / multi-phase platform skill | **Crucible FULL → Foreman standard/heavy** |
| Pure docs/template ops | **No Crucible** — under Ecgberht |

---

## Effort roadmap (ordered)

Status: `PENDING` · `READY` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `DEFERRED`

### E0 — Campaign Ecgberht standing up · DONE
- This butler file + folder layout + spelling law.  
- **Done when:** sessions resume from this file alone.

### E1 — Divergent architecture (Jumper) · DONE
- Face + Strip survivor; friction journaled.  
- **Artifact:** `ideation/JUMPER-SURVIVOR-face-strip.md`

### E2 — Best-in-class research (researchPrime) · DONE
- Plan APPROVED (skill+engine; harness deferred; hierarchical shape only).  
- Deliverables under `research/` (executive, full, agent-implementation, recommendation).  
- **Done when:** John has a recommendation he can hand to planning/build — **met**.

### E3 — Deep second read (Gandalf) · DONE
- Tier-1 honesty-stamped read on design package (`drafts/e3-gandalf/`).

### E4 — Plan the Foundry skill (Crucible) · DONE
- LITE Stage 1–2 + MASTER-PLAN-LOCKED + IMPLEMENTATION-PLAN; Foreman handoff under `e4-skill-plan/`.

### E5 — Build skill + engine (Foreman) · DONE
- All **6 waves GREEN** · **56/56 tests** · status=DONE (2026-07-24).  
- Deliverables: `SKILL.md`, `bin/ecgberht.mjs`, `engine/*`, schemas, templates, fixtures, verification/canary packs.  
- **Out of scope (held):** Anchor merge into launch tree; E9/E10 UI.

### E6 — Anchor next-gen surfaces · DEFERRED
- Superseded/expanded by E9–E10 (see below).

### E7 — Calendar / email / capacity connectors · DEFERRED
- Feeds portfolio Ecgberht (E10); after E9/E10 design.

### E8 — Full agent harness product · DEFERRED (separate campaign)
- Only if still wanted; **not** smuggled into E4–E5.

### E9 — Project-dashboard Ecgberht (seal UI) · READY (wait John GO)
**Icon LOCKED:** `assets/icons/ecgberht-project-seal.jpg` (royal steward seal; full-bleed dark).  
**Intent:** Foundry skill on each project dashboard — one-click → Ecgberht dialogue: project goal, task list, skill routing (research/plan/build/general terminals), grasscatcher, depth dial.  
**Ceremony (when unparked):** Jumper FULL/Heavy → researchPrime FULL/Heavy → Gandalf Heavy → Crucible → Foreman on **Anchor-dev + skill**.  
**Spec vault:** `NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` §A.

### E10 — Portfolio / main-dashboard Ecgberht (high seat) · READY (wait John GO)
**Icon LOCKED:** `assets/icons/ecgberht-portfolio-high-seat.jpg` (empty high seat; full-bleed dark `#0f1117`).  
**Intent:** Main Anchor work dashboard button — orchestrate all projects’ Ecgberhts, master task list, subscription/token headroom (esp. Claude), jump/create projects, speak + floating terminal; calendar/email prep/triage when integrated.  
**Ceremony (when unparked):** same FULL/Heavy stack as E9; **never** public v1.0.x.  
**Spec vault:** `NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` §B.

---

## Current pointer (update every session)

| Field | Value |
|-------|--------|
| **Last updated** | 2026-08-30 |
| **Active effort** | **Conversational Kickoff Synthesis v0 — formal Foundry improvement** |
| **Phase** | John approved · ChatGPT Ultra controlling · Wave 1 canonical contract |
| **Icons LOCKED** | Project = **royal steward seal** · Portfolio = **empty high seat** |
| **UI binding** | Current `<path> prototype |
| **Blocker** | none |
| **Do not** | Replace the natural brainstorm · merge product structure with plan tags · merge/push before human feedback |

### Just done (2026-07-25, evening — vision correction)
- **John REJECTED v1 wireframes** (paradigm: briefing officer, not chief of staff). Directive captured verbatim-faithful in **`VISION-CORRECTION-2026-07-25.md`** (controlling; do not compact): steward **takes charge** — confirms goal, keeps **Campaign Roadmap**, executes steps in background, **summons one decision at a time** with Decision Packets; High Seat = ambient tiles + single raised attention + spoken resource balancing; conversation is the interface; **all house names stay**.  
- **Wireframes v2 DONE** — `mockups/e9-e10-wireframes.html` (Seal chamber · High Seat attention · Decision Packet · honest states); v1 kept at `…-v1-superseded.html` as the rejected negative example.  
- **v2.1 (John iteration, same evening):** LOCKED icons embedded (red-wax Seal + stone High Seat, data-URI); **seat switcher** in titlebars (claude/gemini/grok via Anchor prefs) with **seat-hop non-event law** (ledger = transition document, switch receipted; demoed in the chamber conversation); **Screen 0 added** — launch/embedding recommendation: docked overlays in Anchor-dev dashboards, one component two mounts, ⚑ badge only ambient signal (VISION-CORRECTION §6a/§6b).  
- **Annex RE-BASED** (banner): A1–A6 survive as substrate laws under the conversational layer; A8/W7 reframed → **Decision Packet engine**; new required ledger object: **Campaign Roadmap** (typed).  
- **`HANDOFF-GROK-CRUCIBLE.md` rev 2** — Stage 0 genuinely open; North Star draft in VISION-CORRECTION §6; open-vs-locked lists rewritten.  
- Earlier same day: external Fable review (`REVIEW-FABLE-2026-07-25.md`), annex criticals closed, `ARCHITECTURE-SKETCH.md` SUPERSEDED, W7 spec created. All still stand, as amended above.  

### Just done (2026-07-26 — Crucible)
- Stage 0 North Star APPROVED (take-charge).  
- Stage 1 Master Plan R2 APPROVED.  
- Stage 2 Implementation Plan APPROVED — `e9-e10-crucible/stage2/` Foreman handoff ready.  
- Seating for build: **Claude** coding · **Grok** review.  
- **Fable plan review (John-directed):** plan sound; ONE critical gap fixed — mockups were referenced but not mechanically enforced (the exact failure that burned two prior builds). Added **`stage2/MOCKUP-CONTRACT.md`** (element checklist + verbatim falsify quotes; MISSING = BLOCKER; waiver = John receipt only), wired into IMPLEMENTATION-PLAN gates, handoff checklist, and `foreman.config.json` (`ui_wave_law`). Standing rules journaled: campaign `journal/0030` · crucible `trio/crucible/journal/0079` · foreman `trio/foreman/journal/0090`.  

### Next concrete action
1. Land Wave 1's canonical kickoff proposal, confirmation, intent projection, and replay contract in Ecgberht.  
2. Run focused plus legacy gates, then obtain Claude Fable's independent verdict before touching Anchor.  
3. Add the thin current-cockpit pilot, harden it against refresh/restart, and get John's feedback before merge/push.

---

## Artifact map

| Artifact | Role |
|----------|------|
| `ECGBERHT.md` (this file) | Campaign SSOT + next action |
| `VISION.md` | Product vision |
| `ARCHITECTURE-SKETCH.md` | Early sketch (superseded in part by research) |
| `research/*` | researchPrime pack (E2) |
| `ideation/JUMPER-SURVIVOR-face-strip.md` | Jumper winner (E1) |
| `drafts/` | Gandalf drafts/reads (E3) |
| `journal/` | Session friction rollups |
| `NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` | **HOLD vault** — project + portfolio UX after E5 |
| `REVIEW-BRIEF-FOR-EXTERNAL-MODEL.md` | **Full effort summary** for another model to review |
| `VISION-CORRECTION-2026-07-25.md` | **CONTROLLING vision** — take-charge steward (do not compact) |
| `REVIEW-FABLE-2026-07-25.md` | External Fable review (B1 affirmed · Oranges Brief gap · Q1–Q10 answers) |
| `research/e9-e10/W7-BRIEF-SPEC.md` | W7 Oranges Brief engine-wave spec (Crucible intake) |
| `mockups/e9-e10-wireframes.html` | E9/E10 wireframes — 5 screens incl. degraded states (house names lead + plain subtitles) |
| `HANDOFF-GROK-CRUCIBLE.md` | Launch brief for the grok Crucible session (locked decisions, constraints, done-when) |
| `assets/icons/ecgberht-project-seal.jpg` | LOCKED project / skill icon |
| `assets/icons/ecgberht-portfolio-high-seat.jpg` | LOCKED main-dashboard icon |
| `research/e9-e10/` | E9/E10 RP + Gandalf + machine annex |


---

## Open human items

- [x] Choice A: park until Anchor launch v0 + skills out (2026-07-23)  
- [x] Unpark E4 after launch out (2026-07-24)  
- [x] Anchor-dev merged to include public v1.0.1 (release tree untouched)  
- [ ] Optional: amend North Star if skill naming/UX preference changes  
- [x] researchPrime summary shown in chat  
- [x] Handoff logged for session death / other session resume

---

*Ecgberht does not build. Ecgberht remembers the campaign order and keeps Jumper, researchPrime, Gandalf, Crucible, and Foreman aimed at the right battle.*
