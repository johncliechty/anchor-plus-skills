---
name: ecgberht
description: >
  Project and portfolio steward (JARVIS-class). Owns campaign memory (Face), typed
  attention heartbeat (Strip), tool-depth judgment via dispatch table, grasscatcher,
  and next-action ranking. Commissions researchPrime, Crucible, Foreman, Gandalf,
  Jumper — never reimplements them. Use when John asks "where is this project",
  "what next", "stand up Ecgberht", portfolio brief, heartbeat, soft-vet, or when
  opening a project that has ECGBERHT.md / needs campaign continuity.
icon: assets/icons/icon.jpg
# Project tile = royal steward seal (icon.jpg). Portfolio/main dashboard =
# assets/icons/ecgberht-portfolio-high-seat.jpg (empty high seat). See
# NEXT-UX-AND-ANCHOR-ORCHESTRATION.md for E9/E10 embed vision.
---

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

**Steward-local corollaries (sleep 2026-08-15).** (a) **Test the STEADY STATE,
never the first frame** — the chamber painted M1 then deleted it one fetch
later for twelve green waves; a surface gate asserts survival after the page
settles, not presence at first paint (0083). (b) **Multi-KB PTY writes are
chunked and paced** (Anchor 4d152d4: >512 chars ⇒ 256-char chunks @20ms) —
one-shot writes fuse characters and mangle the brief (0080). (c) **Status
delivery is engine-enforced or it did not happen** — timer-turn chat posts
can silently not render; the outbox/mediator path is the ONLY delivery of
record, and a decision gate must never wait on a channel that was not
verified once with John's ack (0081).
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
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


# Ecgberht — Foundry skill + deterministic engine

**Spelling:** **Ecgberht** only (never Expert as product name; Egbert/Ecgbert are historical asides only).

Ecgberht keeps durable campaign memory and cheap portfolio attention so a fresh session knows the north star, active effort, human wait, and best next action — commissioning slice tools without becoming them.

> **Humans:** this file is the agent/engine protocol. Templates live under `templates/`; schemas under `schema/`; fixtures under `fixtures/`; CLI under `bin/ecgberht.mjs`.

---

## Is / is not

| Ecgberht **is** | Ecgberht **is not** |
|-----------------|---------------------|
| Long-horizon campaign memory (Face) + typed heartbeat (Strip) | A coding agent inventing features mid-build |
| Owner of multi-effort roadmap + ranked next | Replacement for Crucible or Foreman |
| Chooser of tool depth via dispatch table | Itself a Crucible stage or Foreman wave loop |
| Soft-vet + grasscatcher with structured receipts | Shark Tank / full Oranges multi-path |
| Compose-only commission of foundry/trio skills | OpenClaw substrate or multi-agent harness |
| Subscription seats via Anchor model prefs | Hardcoded product model IDs or raw API-key seat paths |
| Portfolio strip-first rank (anti-N-full-read) | Default chat gateway tax on every turn |
| Steward of attention across projects | Replacement for Anchor job_runner |

**THE READ-BEFORE-PLAN LAW (journal 0084 — owed since 2026-08-14).** Before the
steward plans, diagnoses, or proposes ANYTHING about a project, it OPENS ITS OWN
CAMPAIGN RECORD for that project: the roadmap, the latest reference-run pointer
(e.g. a `*-JOHN-RUN-POINTER.md` under the project's planning docs), and the most
recent journal entries. Code and git history tell you what the project IS;
only the campaign record tells you where the CAMPAIGN stands — 0084's steward
produced two inverted plans by diagnosing from code while its own record held
the answer. **`attention.json` is not campaign memory** — it is a single edge,
never the story. A plan whose provenance section cannot cite the campaign
record it read is planned from the wrong substrate; start over.

---

## Closed verb list

CLI: `node bin/ecgberht.mjs <verb> [args…]` (package bin: `ecgberht`).

| Verb | Aliases | Intent (bodies land in later waves) |
|------|---------|--------------------------------------|
| `status` | — | Pointer from Strip (+ Face if needed): active effort, human wait, next |
| `next` | — | N=1 or portfolio next; strip-first rank + why |
| `update` | `heartbeat` | Patch Face narrative; append Strip instruments/receipts |
| `depth-suggest` | — | Table-driven depth cell (LITE bias; override needs receipt) |
| `soft-vet` | `grasscatch` | Park idea with reason + grasscatch/receipt fields |
| `receipt-validate` | — | Validate structured receipt; monologue-only invalid |
| `roadmap-show` | — | Roadmap projection from append-only events; drift → reject + heal |
| `roadmap-propose` | — | Propose step → `step_create` event only (status `proposed`) |
| `roadmap-set` | — | Set fields / flip status (receipt required) / bind commission → events only |
| `brief` | — | Decision Packet (Q1–Q12 deterministic retrieval; Phase A zero model calls; `seen` receipt delta anchor; cached projection) |
| `commission-propose` | — | Steward proposes a commission for a Roadmap step (skill + depth defaults; requires confirm — not a mode picker) |
| `commission-confirm` | — | Confirm proposal → job `queued` composing Anchor job_runner; `commission_bind` + Strip append (M2 lifecycle `queued→running→done\|failed\|orphaned\|reaped`; abnormal exit → `commission_abnormal` receipt) |
| `seat-hop` | — | Switch seat (claude/gemini/grok) wired to Anchor prefs; `seat_hop` receipt who/when/from→to; non-event — next turn continues from Face/Strip/Roadmap/packet, no re-brief |

**Law:** unknown verb → structured refuse (`error: unknown_verb`). No open plugin dispatch. No daemon/listen loop.

**Dialogue — CONVERSATIONAL since 2026-08-04.** Talk is routed by `routeUtterance` (`engine/steward-conversation.mjs`), not by a regex table alone:

- **Control verbs stay deterministic.** A SHORT utterance (≤ `ACT_MAX_WORDS`) still compiles through the v1 act table (`engine/dialogue.mjs`) — carry on / park that / confirm commission / switch seat. A model never decides to spend or write. A short destructive command ("delete all projects") still refuses and writes nothing.
- **Everything else is a CONVERSATION.** Free-form speech goes to the steward's **seat model** with the Face, roadmap projection, active step and the open `scaffold_proposal` as context. It answers, asks what it needs, and — when it has enough — emits a typed proposal for review. He refines **by talking**; each re-proposal is a new hash-bound `scaffold_proposal`.
- **The destructive guard does NOT run on the converse lane.** "Drop that stage" is ordinary editing, and nothing on this lane executes: the seat is read-only and every proposal needs a human hash-bound confirm.

**E5 — AMENDED 2026-08-05 (John's decision).** The conversation is now KEPT, and is never authoritative.

| store | what it holds | authoritative for project state? |
|---|---|---|
| Strip receipts / roadmap events / Face | project **state** | **yes — these are the only ones** |
| `.ecgberht/conversation-log.json` (per project) | what was **said**, each turn tagged with the scaffolding version it produced | no |
| `~/.ecgberht/portfolio-ledger.json` | what the steward **did**, across all projects | no |

Why: the roadmap already records *what* the scaffolding was at each turn (every re-proposal is its own `scaffold_proposal` event), but not *why* it changed. Why the amendment is narrow: E5 existed to stop two sources of truth for project state drifting apart — that is still prevented. The transcript can never `mint_step`, `flip_status`, `authorize_spend` or `commission`; the portfolio ledger **refuses** any record carrying `status`/`goal`/`steps`/`next_action`; and **where they disagree with the ledger, the ledger wins.** Both are enforced structurally (`assertTranscriptNonAuthoritative`, `assertRecordsNoProjectState`) and by the amended second-task-DB canary, which now has red cases for an authoritative transcript and for one allowed to mint a step. The CLI's own `--resume` stays unused — model-side session state would be a memory nobody can audit.

**The High Seat shows both:** `bringItUp` carries the project's conversation summary (turns, scaffolding versions, recent exchanges); `assembleHighSeat` carries `steward_efforts` — activity per project, and which projects have gone quiet.

**Seat + spend.** `scripts/seat-call.mjs` owns the transport (engine law: nothing under `engine/` may spawn). The model is chosen by ROLE, never by name — `engine/seat-tiers.mjs` maps `frontier` (planning) and `conversational` (one tier below, talking) to CLI **aliases**, so new model releases are picked up with no code change; a test fails the build if a version number appears there. Talking turns get **no tools** (fast); only the planning turn reads the project. A **background allowance** opens itself on the first turn — no approval gate — capped at **$50 of MEASURED spend** with **unlimited turns**; reaching the cap stops the steward and offers to raise it.

**Proving it (the capture protocol).** The acceptance lane must enter at the surface a human touches, with **John's verbatim text** (`test/fixtures/ba815-appendix-a.txt`, vendored by `scripts/vendor-appendix-a.mjs`, drift-checked against the brief) — never a sentence the implementer chose:

| lane | door | seat |
|---|---|---|
| `test/wh4-conversational-steward.test.mjs` | bridge spawned with argv | recorded real reply, **bound to the prompt hash** (drift ⇒ fail) |
| `Anchor/tests/test_steward_goal_authon_2026_07_30.py` | real say box, Playwright, auth ON | recorded real reply, not prompt-bound (proves the surface is wired) |

Re-record with `node scripts/record-steward-fixture.mjs` (two live seat calls) whenever the prompt changes — a stale tape fails rather than passing. The lane also carries an **anti-vacuity test**: the deterministic fallback ALONE must NOT satisfy the criterion, so a green result cannot be produced without the seat doing the work.

Verb help templates: `templates/verb-help/<verb>.md`.

---

## Face + Strip write authority

| Surface | Role | Write authority |
|---------|------|-----------------|
| **Face** | Human narrative / cold-start constitution | May rewrite: north star, active effort, why-next, human-wait |
| **Strip** | Typed instrument heartbeat | Append-only instruments/receipts; reject silent in-place clock rewrite |

**Face fields only (no depth/grasscatch jargon on Face):** north star · active effort · why next · human wait.  
Markers: `schema/face-markers.json`. Template: `templates/ECGBERHT.md`.

**Strip locked fields (`ecgberht-strip-v0`):** phase · active_effort · human_wait · capacity `known|unknown` · negative_heartbeat · grasscatch · uncertainty_flags · tool_depth_cell · next_recommended · why_next.  
Schema: `schema/strip.schema.json`. Templates: `templates/strip.json`, `templates/strip-fence.md`.

### Heal law (enforced in engine helpers)

| Rule | Meaning |
|------|---------|
| Face wins narrative | Human north-star / why-stakes / active-effort prose may be rewritten on Face |
| Strip wins clocks | Instruments/receipts are **append-only**; silent in-place clock rewrite is **rejected** |
| Crisis = explicit re-sync | `healResync({ explicit: true, … })` only — ambient chat cannot dual-write |
| Silence = negative-heartbeat | Do not invent “all clear”; record `negative_heartbeat` |
| Chat cannot invent truth | Claims must ground in Face or Strip surfaces |
| Fence/schema drift | Repair Face fence text from Strip projection; **never** silently rewrite Strip history |

Engine modules: `engine/write-authority.mjs`, `engine/heal.mjs`, `engine/face-strip.mjs`.

### Campaign Roadmap (TW1 — engine truth)

The Roadmap is engine truth via append-only events + a derived projection. Face prose is **never** the only step list.

| Surface | Rule |
|---------|------|
| `roadmap_events[]` | Append-only history (`step_create` · `step_set` · `status_flip` · `commission_bind`); prior entries never rewritten |
| `roadmap_projection` | **Derived-only** step list (`id, name, status, done_when, waiting_on, commissioned_as`) rebuilt from the event fold; direct writes rejected |
| Status flip | Requires a receipt (`who`/`why`) on the `status_flip` event — flip without receipt = refuse write / reject on validate |
| Silent rewrite | Stored projection that disagrees with the event fold → structured reject (`roadmap_silent_rewrite`); **heal** rebuilds projection from events (events untouched) |
| Face-only prose | `roadmap-show` / `status` return an **empty projection + honest gap** (`face_prose_only`) — steps are never invented from prose |

**Single writer path (TW3 hook):** the only writer is `appendRoadmapEvent` (via `roadmap-propose` / `roadmap-set`). TW3 job lifecycle (commission propose/confirm; `queued → running → done | failed | orphaned | reaped`) must bind through this same writer — `commission_bind` to attach a step to a commissioned job, `status_flip` (with receipt) for step status changes. No dual-write, no second store, no UI-only state. Contract constant: `ROADMAP_SINGLE_WRITER`.

Statuses: `proposed | planned | active | waiting | done | parked`.  
Module: `engine/roadmap.mjs` · schema: `schema/roadmap.schema.json` · template: `templates/roadmap.json` · fixture: `fixtures/roadmap-minimal.json` · file: `roadmap.json` at project root.

### A1 discovery (no registry)

- Roots: CLI `--roots` and/or env `ECGBERHT_STRIP_ROOTS` (OS path separator).
- Per directory, first match wins: `strip.json`, else `ECGBERHT.md` Strip JSON fence.
- Scan: listed roots + **one level** of subdirs; ignore `node_modules` / `.git` / `vendor` / junk.
- Empty roots → structured empty result (not a crash).
- Module: `engine/discovery.mjs`.

### Strip-first rank

Portfolio `next`/`status` rank **Strip projections only**. Full Face only for top-k drill-in or heal.  
`capacity=unknown` → rank penalty + LITE-bias flag — **never silent green**.  
Anti-starvation: `negative_heartbeat`, `anti_starvation_age_days`. Module: `engine/rank.mjs`.

---

## Seating (Anchor prefs only)

- Resolve seats from Anchor model prefs: `coding_family` / `review_family` / `default_cli` (mirror: model prefs file under the Anchor data dir — never hardcode host home paths in engine logic).
- Map families to **subscription** drivers only (claude / gemini-cli|agy / grok-cli).
- Stamp `cross_model` honestly when same-family.
- **Forbidden:** hardcoded Claude/Gemini/Grok product model IDs in skill prose or engine; raw `XAI_API_KEY` HTTP path for production seats.
- Module: `engine/seating.mjs`.

### Commission adapters (compose-only)

| Skill | Role |
|-------|------|
| researchPrime | Evidence research |
| Crucible | Plan forge |
| Foreman | Wave build |
| Gandalf | Deep adversarial read |
| Jumper | Ideation tournament |

- Spawn/handback contracts only: pass depth cell, active effort, receipt envelope + resolved seats.
- **Zero** in-process Shark Tank or Foreman wave loop inside Ecgberht.
- Handback must carry structured fields (`active_effort`, `why_next`, `grasscatch_why`, `tool_depth_why`, `human_wait`, `uncertainty_flags`) or `receipt-validate` fails.
- Module: `engine/commission.mjs`. Boundary canaries: `runBoundaryCanaries`.

---

## Non-goals (enforced)

- No edits to Anchor-release-v1.0 / public freeze tags  
- No OpenClaw substrate or multi-agent wallets  
- No full calendar/email OAuth connectors in this build  
- No default chat gateway tax on every turn  
- No replacing Anchor job_runner  
- No in-app chat personality product  
- No Family-Finances domain features  
- Harness product (if ever) is a separate Grasscatcher-scope product — not this engine  

### Grasscatcher ledger (W6 — permanent scope deferrals)

Distinct from campaign `soft-vet` / `grasscatch` verb receipts. The ledger freezes product non-goals so MVP scope cannot silently expand. Each item carries receipt shape (`deferred`, `grasscatch_why`, `suggested_later_owner`, `handback_shape`) and is **not** an MVP verb or engine surface.

| Deferred | Suggested later owner |
|----------|----------------------|
| OpenClaw harness product | separate-harness-product |
| calendar/email OAuth | connector-product |
| Anchor v1.0.x release edits | anchor-release-owners |
| default chat gateway | chat-product |
| Family-Finances domain | family-finances-project |
| Anchor 1.1 portfolio UI | anchor-1.1 |
| launch-tree merge | launch-orchestration |

- Fixture: `fixtures/grasscatcher-ledger.json`  
- Module: `engine/grasscatcher-ledger.mjs`  
- Strip labels: `strip.json` → `grasscatch`  

### Stage-2 freeze set (W6)

Locked artifact set for Foreman without re-litigating architecture: file tree, schemas, fixture matrix, verb contracts, heal law, A1 discovery rules, non-goals. **Depth remains LITE** skill+engine MVP.

- Fixture: `fixtures/stage2-freeze.json`  
- Module: `engine/stage2-freeze.mjs`  
- Verification: `engine/verification-pack.mjs` + `engine/canary-pack.mjs`  

### Canary pack (W6)

| Canary | Rule |
|--------|------|
| openclaw | no dependency import/require paths |
| daemon | no createServer / listen loops |
| compose-only | five skill hooks only (researchPrime/Crucible/Foreman/Gandalf/Jumper) |
| spelling | **Ecgberht** only |
| Anchor v1.0 write | no write APIs targeting release-tree freeze prefixes |

---

## Install / junction (Skill Foundry peers)

1. This package root **is** the skill root: `SKILL.md`, `templates/`, `schema/`, `fixtures/`, `bin/`, `engine/`, `package.json`.
2. Seat like peer Foundry skills: junction or symlink the folder as `ecgberht` into the host skills directory used by your agent host.
3. Engine CLI: `node bin/ecgberht.mjs <verb>` or install package bin `ecgberht`.
4. Tests: `node scripts/run-all-tests.mjs` (or `npm test`).
5. **Trio pin** for compose compatibility: commit **`77de811`** (see frozen `IMPLEMENTATION-PLAN.md`). Prefer committed trio behavior if a local dirty stage1 file is present.

---

## Layout

```
SKILL.md                 # this protocol
package.json             # name ecgberht + bin
bin/ecgberht.mjs         # CLI
engine/                  # verbs, face-strip, roadmap, brief, anchor-knowledge (read-only), dispatch, seating, commission, grasscatcher-ledger, canary-pack, stage2-freeze, verification-pack
templates/ECGBERHT.md    # Face scaffold
templates/strip.json     # Strip JSON stub
templates/strip-fence.md # dual-section fence stub
templates/roadmap.json   # Roadmap stub (append-only events + derived projection)
templates/verb-help/     # closed-list help
schema/                  # face markers, strip, receipt, roadmap
fixtures/                # strip-minimal, dispatch-table-seed, grasscatcher-ledger, stage2-freeze, roadmap-minimal
test/                    # unit suite (w1–w6)
scripts/run-all-tests.mjs
```

### Dispatch table (W4)

- Dimensions: phase × uncertainty × human_wait × cost → `LITE` | `FULL` | `SPIKE` | `commission` | `refuse`
- Defaults bias **LITE**; SPIKE for unknown data shape; FULL only when a cell says so
- refuse when `human_wait` blocks or out-of-scope; `capacity=unknown` → LITE bias flag (never silent FULL green)
- Human override of table outcome requires structured receipt: who / when / why / from→to
- Module: `engine/dispatch-table.mjs` · fixture: `fixtures/dispatch-table-seed.json`

---

## When to use / when NOT to use

- **Use when:** resume a project campaign, rank what-next, soft-vet an idea, choose tool depth before commissioning a slice skill, stand up Face+Strip.
- **Do NOT use when:** you need an actual plan forge (Crucible), wave build (Foreman), deep adversarial read (Gandalf), ideation tournament (Jumper), or evidence research (researchPrime) — **commission** those; do not reimplement them here.
