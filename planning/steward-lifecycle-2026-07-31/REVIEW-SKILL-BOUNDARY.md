# REVIEW — SKILL BOUNDARY: is the 19-wave plan aimed at the wrong side?

**Date:** 2026-08-02 · **Trigger:** John's framing challenge ("I want a SKILL usable independent of Anchor — two skills, project-level and portfolio-coordinating — integrated INTO Anchor, not an Anchor feature that others can't use")
**Inputs read:** `C:\dev\Ecgberht\SKILL.md` (full) · `bin/ecgberht.mjs` · `scripts/high-seat-bridge.mjs` / `seal-chamber-bridge.mjs` / `port-seal-ui-to-anchor.mjs` · `engine/` (34 modules) + `engine/portfolio/` (32 modules) · `engine/seating.mjs` / `anchor-knowledge.mjs` / `job-lifecycle.mjs` / `portfolio/home.mjs` (code-level) · `IMPLEMENTATION-PLAN-v2.md` (all 19 waves, full) · `NORTH-STAR.md` v4 · `NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` · `C:\dev\Anchor\gandalf.py` (consumer precedent) · INTAKE/MASTER-PLAN-v2 scanned for boundary language (none exists — confirming the framing gap).

## VERDICT UP FRONT

**MERGE — with a mandatory North-Star amendment and five named seam corrections before Foreman runs.**

John's instinct that the steward already exists as a skill is **correct**. His fear that the plan builds the steward INTO Anchor is **mostly not borne out at the file level** — the plan's own BUILD CONTRACT declares the build root `C:\dev\Ecgberht` and makes the Ecgberht repo the primary repo for **12 of 19 waves**. The steward logic (spine, dossier, envelope, scaffolding authoring, Face compiler, elaboration, reflection emitters, rehydration pipeline, attention derivation, High Seat fold) all lands in the skill repo. What IS wrong is the **framing and four or five interface seams**: the North Star opens "A project **in Anchor**…", auth revalidation is specified as Anchor's `ANCHOR_TOKEN` at seams that live inside the skill engine, the status-truth channel is designed Anchor-outbox-only, the handback-file contract is specified as an Anchor executor deliverable rather than a skill-owned contract Anchor implements, and **no host-agnostic acceptance test exists anywhere in 19 waves**. Left as-is, the build would produce a skill that is 90% host-agnostic by accident and 10% Anchor-welded by specification — and nothing would ever prove the 90%. The fix is amendment, not demolition.

---

## A. WHAT ALREADY EXISTS

### A.1 Both of John's desired capabilities exist, at real maturity, in ONE skill

| Capability John wants | Where it lives today | Maturity | Standalone-usable now? |
|---|---|---|---|
| **Project-level steward** | `engine/`: `face-strip.mjs`, `roadmap.mjs` (append-only events + projection), `brief.mjs` (`assembleBriefPacket` Q1–Q12, zero model calls), `dispatch-table.mjs`, `heal.mjs`, `receipt-validate.mjs`, `seal-chamber.mjs`, `dialogue.mjs`, `job-lifecycle.mjs`, closed-verb CLI `bin/ecgberht.mjs` | E5 DONE (6 waves, 56 tests) + TW waves; live registered skill | **Largely yes** — `node bin/ecgberht.mjs status/next/brief/roadmap-*` runs from a bare terminal against a project folder. Gaps in A.3. |
| **Portfolio coordinator** | `engine/high-seat.mjs`, `rank.mjs` (strip-first, anti-starvation), `discovery.mjs` (A1, `--roots`/`ECGBERHT_STRIP_ROOTS`), `engine/portfolio/` — 32 modules, 19 waves GREEN, 671 tests, no-walk `query.mjs`, index home `~/.steward/portfolio` (`home.mjs`: STEWARD_HOME env else user profile — **zero Anchor dependence, deliberately**) | steward-tracking-2026-07 DONE | **Yes** — `status --roots a;b`, high-seat assembly, badge count all callable via CLI/bridge from any process. |

The skill is registered live: `C:\Users\john\.claude\skills\ecgberht` is a junction to `C:\dev\Ecgberht` (verified). It is a Foundry-convention peer that happens not to live under `C:\dev\Skill Foundry\skills\` — a governance/pointer-map note, not an architecture problem. John "thought I had a skill like that drafted or built" — **he does, built, twice over (E5 + the 671-test portfolio index), and it is BOTH of the skills he described, fused.**

### A.2 The Anchor couplings, complete inventory

| Coupling | File | Kind | Blocks standalone use? |
|---|---|---|---|
| "Seating (Anchor prefs only)" | `SKILL.md` §Seating + `engine/seating.mjs` | **Prose harder than code.** Code order: injected prefs → `CODING_FAMILY`/`REVIEW_FAMILY` env → `ANCHOR_PREFS_PATH`/`ANCHOR_DATA_DIR`/`~/.anchor/model_prefs.json` → historical defaults. No host-absolute literals. | **No** (env/defaults work) — but the SKILL.md heading DECLARES Anchor-only, which is exactly the framing John is objecting to. Fix the prose. |
| Anchor knowledge store | `engine/anchor-knowledge.mjs` | READ-ONLY evidence adapter; honest `no_anchor_root` when absent; `refuseAnchorStoreWrite` | **No** — degrades honestly. Correct shape for an optional host adapter. |
| Commission execution | `engine/job-lifecycle.mjs` (`ANCHOR_JOB_COMPOSE`) | `commission-confirm` creates a job **`queued`, composing Anchor `job_runner`** — the skill never spawns. With no Anchor, a confirmed commission queues forever with no honest refusal naming the missing host. | **YES — the one real functional gap.** The compose-only law is right; what is missing is a named executor SEAM (host-injected) + `no-executor-host` refusal state. |
| Bridges | `scripts/high-seat-bridge.mjs`, `seal-chamber-bridge.mjs` | Thin spawn adapters over engine surfaces, no baked paths, CLI-parity by design | **No** — these are the correct consumer pattern (same as `gandalf.py`). |
| Porting tool | `scripts/port-seal-ui-to-anchor.mjs` | Hardcodes `C:/dev/Anchor` — a one-shot install script | No (tooling, not engine). |
| Auth | — nothing in the engine today — | The **PLAN** introduces `ANCHOR_TOKEN` revalidation "at the confirm/debit seams" (Waves 8, 11), which are engine verbs | **Would become YES if built as written** — see B. |

### A.3 What the skill cannot do standalone today
1. Execute a confirmed commission (no executor seam — queues composing Anchor's runner).
2. Model-authored work (scaffold compile, Face compile, NL-polish) — fine in-session when a host agent runs the skill, but the new plan's compile paths must not assume Anchor's spawn plumbing.
3. Receive run-status truth (`status_flip` from live runs) — today the steward itself flips with receipts; the plan's only automated producer is Anchor's outbox/mediator.

## B. BOUNDARY AUDIT — all 19 waves

Classification key: **S** = SKILL-side (must work with no Anchor) · **A** = ANCHOR-side legitimate (host: process spawn/supervision, auth substrate, UI chrome, routes) · **W** = wrong-side (steward logic Anchor-welded as specified). Primary repo per the plan's own BUILD CONTRACT.

| Wave | Primary repo (plan) | Classification | Notes / offenders |
|---|---|---|---|
| 1 Ground truth I | Ecgberht | S + A, **W-risk** | Durability law, A3 fix, equivalence check = S. Auth substrate gate (mint `ANCHOR_TOKEN`, `paths.py`) = A, legitimate. **W-risk:** the suite makes the WHOLE auth-ON preflight a precondition of every Ecgberht test — the skill's own suite becomes unrunnable without Anchor's token machinery. Needs a split: skill suite green host-less; auth-ON preflight governs the Anchor-integration lane. |
| 2 Vertical slice | Ecgberht | **S** | Fixture-only; stub executor. Clean. |
| 3 Ground truth II | Ecgberht | S + A | Audits of both halves; A5 = S (portfolio index). Clean. |
| 4 BUILD-E executor | Anchor | **A** legitimate, **one W item** | Executor, boot reconcile, `kill_on_job_close=False`, `(pid, proc_create_time)` — all genuinely host work. **W:** the durable handback-FILE **CONTRACT** (path convention, marker semantics, S6 write discipline) is specified only as an Anchor deliverable. The contract belongs in the skill (schema + `receipt-validate` already are); Anchor's wrapper is one IMPLEMENTER. Otherwise no other host can ever hand back. |
| 5 Decisions/spikes | both | S + A | Cost model, skills table, G2/G3 = S; G5 halt inventory reads Anchor lanes = A evidence. Clean. |
| 6 Ledger spine | Ecgberht | **S** | Single writer, event-kind allow-list, `client_event_id` — pure steward law. Clean. |
| 7 Dossier + confirm journal | Ecgberht | **S** | Clean. |
| 8 Session envelope | Ecgberht | **S**, **one W item** | Envelope law = S. **W:** "AUTH REVALIDATION AT DEBIT: revoked/expired **token**" — if the engine's debit verb checks `ANCHOR_TOKEN`, Anchor's auth is welded into the skill. Must be an injected `authorize(seam, ctx)` host hook: Anchor supplies token enforcement; a bare host supplies its own (or an explicit local-trust authorizer). Same tests, relocated. |
| 9 Scaffolding authoring | Ecgberht | **S** | dialogue→`step_create`, batch confirm, hash-bound. Clean (compile execution must stay host-provided, not Anchor-spawned — currently unstated, fine as long as it stays unstated). |
| 10 Face compiler | Ecgberht | **S** | Clean. |
| 11 Commission proposal "in Anchor" | both | **S mislabeled**, **same W item as 8** | Title says "in Anchor"; deliverables are Ecgberht verbs + `resolveSeats` (`seating.mjs`) + table-bound selection = S; hand-off to Wave-4 executor = A. **W:** "AUTH REVALIDATION AT CONFIRM" — same authorizer-injection fix. Retitle: "Commission proposal — wired into Anchor". |
| 12 Progressive elaboration | Ecgberht | **S** | Clean. |
| 13 Session-state truth | Anchor | A legitimate, **one W item** | Leases, outbox, `(pid,create_time)` = A (host supervises processes). **W:** the spine's status-ingestion client is specified ONLY as "the Node mediator draining Anchor's outbox". The skill needs a named host-agnostic ingestion seam (`ingestStatusEvents(producer)`); the Anchor outbox/mediator is its first producer. Without this, criterion 8 is structurally Anchor-only forever. |
| 14 Handback validation + emitters | Ecgberht | **S** | `emitReflectionReceipt` / `proposeNextStageDeterministic`, zero-model, golden-pinned. Exactly right, exactly where it belongs. |
| 15 Rehydration + `openProjectPipeline` | Ecgberht | **S** | Clean — and note it is the skill's boot pipeline, callable by ANY host or the CLI. |
| 16 Attention contract | Ecgberht | **S** + A bridge | `deriveAttention`/`publishAttention` = S; anchor-contract ingest bridge = adapter, correct. Clean. |
| 17 High Seat + badge | Anchor | S fold + **A** surface | Fold/trap/`query.mjs` = S; badge endpoint + `static/high-seat.js` = A. Clean split. |
| 18 Chamber UI | Anchor | **A** | UI chrome over skill verbs/renderers. Legitimate. |
| 19 Kill gate | both | S + A, **one gap** | Proves everything under auth-ON in Anchor. **Gap (the biggest single finding): no wave, gate, or test anywhere proves the skill works with NO Anchor present.** The property John actually asked for is unasserted. |

**Quantification.** Wholly wrong-side waves: **0**. Waves needing seam/wording amendment: **5** (1, 4, 8, 11, 13) plus the Wave-19 gap. Waves untouched: **13**. Steward logic already skill-repo-resident: 12/19 primary-Ecgberht waves. The DAG, the durable-store map, the failure tables, the hardening law all survive intact. **This is a MERGE profile, not a re-plan profile.** Worst offenders verbatim: NS statement "A project **in Anchor** is stood up…"; Wave 8 "AUTH REVALIDATION AT DEBIT: a revoked/expired **token** at the debit seam refuses"; Wave 13 "the Python-side fsync'd outbox with the Node mediator as the spine's client (**the** single answer to INTAKE's 'who emits status_flip')"; Wave 4 owning the handback contract; SKILL.md "**Seating (Anchor prefs only)**".

## C. ONE SKILL OR TWO?

**Recommendation: ONE skill, TWO entry surfaces (altitudes). Do not split.**

- **John's own locked intent says one.** `NEXT-UX-AND-ANCHOR-ORCHESTRATION.md`: "Two altitudes of the **same** steward name"; "E9/E10 **extend** E5; they do not fork a second brain." The two-skills memory is best explained by the two ICONS/entries (seal vs high seat), which exist.
- **The single-source rule cuts against a split.** Splitting forces either duplicating Face/Strip/roadmap/receipt/durable-write primitives (forbidden) or extracting a third shared package that both pin — a new version-skew surface for zero user benefit.
- **The portfolio altitude is definitionally a consumer of project Strips/attention projections in the project altitude's exact schemas.** It has no independent utility without project-level data; the coupling is essential. (The reverse is false — the project steward is useful alone — which is why the ENTRY surfaces must be separately documented, not the code separated.)
- **Commission depth, seating, canaries, heal law are shared law.** Two skills = two places for the law to drift.
- **Install stays one junction**; verbs already separate the altitudes (`status`/`next` project-scoped vs `--roots` portfolio; seal-chamber vs high-seat surfaces).
- **Honest cost of ONE:** the SKILL.md must present both altitudes clearly (today the portfolio surface is under-documented in the skill description — fix in the same SKILL.md pass); the closed verb list carries both altitudes' verbs. **Honest cost of TWO:** shared-engine extraction (~weeks), double junctions/pins, drift risk, and a portfolio skill that cannot demo without its sibling. If a host someday needs separately-listed skills, a thin second SKILL.md alias pointing into the same engine can be added then — not now.

## D. MERGER OR RE-PLAN

**(i) MERGE.** Justification: zero wholly wrong-side waves; steward logic already lands in `C:\dev\Ecgberht` (build root, 12/19 waves, test runner); the locked invariants (E5 single ledger, single writer, `who` claimed-unauthenticated, subscription seats, auth-ON green, no adversarial loop) are all boundary-neutral and survive unchanged; the refuted items stay dead (the handback FILE remains the existing bundle/receipt made restart-safe — moving its contract SPEC into the skill changes ownership, not the channel; Wave 13 still binds to the existing `buildRoadmapProjection`). What must change: the NS statement + one added criterion (E), five wave amendments + one retitle (B), the SKILL.md seating prose, and regeneration of `wave-decomposition-v2.json` (T-EQUIV-01 forces the JSON to follow, which is exactly why amending BEFORE Foreman is cheap and after is churn). RE-SCOPE would be warranted only if steward logic had to move repos in bulk — it does not. RE-PLAN would be warranted only if the NS criteria themselves were host-wrong — they are host-flavored, not wrong: every one of the 13 criteria is either skill law (1–8, 10–12) or host proof (9, 13).

Salvageable under MERGE: **everything** — all 19 waves, the DAG, S1–S13, the T-* registry, all four lanes, both signed gate decisions and Descope D-1.

## E. NORTH STAR IMPACT — amendment draft (v5, for John to lock)

Conservative: one statement edit, one criterion annotation, one added criterion, one added non-goal. Nothing else in v4 is framing-forced.

1. **Statement, first sentence** — replace
   > "A project in Anchor is stood up, planned across MANY stages, and driven OVER TIME by talking to its steward."
   with
   > "A project is stood up, planned across MANY stages, and driven OVER TIME by talking to its steward — the **Ecgberht foundry skill**, a host-independent engine. **Anchor is the reference host**: it supplies execution (job_runner), auth, and the browser surfaces, consuming the skill exactly as it consumes Gandalf — never absorbing it."
2. **Criterion 9 annotation (auth):** "…passes with AUTH ON **at the host seams: the engine exposes an injected authorizer hook exercised by these tests; Anchor supplies token enforcement. The engine itself contains no ANCHOR_TOKEN logic.**"
3. **NEW criterion 14 (the host-agnostic test — the challenge's teeth):**
   > "14. HOST-INDEPENDENCE — the T-HOST-0 acceptance test (§F) passes on a box with no Anchor service, no ANCHOR_TOKEN, and no Anchor prefs: stand-up, scaffold propose/batch-confirm, roadmap, brief, deterministic reflection + next-stage proposal from a valid handback file, and portfolio status across roots all succeed from the bare CLI; a confirmed commission with no executor host refuses with the named state `no-executor-host` — never a silent queue."
4. **NEW non-goal:** "No steward logic (proposal/confirm rendering-decisions, reflection, attention derivation, roadmap/status law) implemented in Anchor Python — Anchor implements host contracts (executor, outbox producer, authorizer, UI) only."

## F. THE HOST-AGNOSTIC TEST — T-HOST-0, defined

**Setup:** fresh worktree of `C:\dev\Ecgberht` on a box/env with: no `anchor` service, `ANCHOR_TOKEN`/`ANCHOR_DATA_DIR`/`ANCHOR_PREFS_PATH` unset, no `~/.anchor/`, no `.anchor/` store in the target folder. A temp project folder + a second temp root for the portfolio leg.
**Script (one gate file, `gate/t-host-0.mjs`):** (1) `stand-up` → Face+Strip from templates; (2) scaffold propose → batch confirm (hash-bound, `who` claimed-unauthenticated) → steps in `roadmap_events`; (3) `status` / `brief` → zero-model packet, honest-unknowns for absent Anchor evidence (`anchor_store_present:false`, reason `no_anchor_root` — already the built behavior); (4) `commission-propose` → seats resolve from env families or report honest source `defaults` (never crash, never a hardcoded model id); (5) `commission-confirm` with no injected executor → **`no-executor-host` named refusal** (new state, Wave-11 amendment); (6) drop a valid handback FILE + marker per the (now skill-owned) contract → ingest → `emitReflectionReceipt` + `proposeNextStageDeterministic` byte-match goldens; (7) `status --roots` over both temp projects + high-seat assembly → rank, badge count, unknown-rows honesty.
**Missing today to pass:** (a) the executor seam + refusal state (job-lifecycle queues composing Anchor with no honest terminal refusal); (b) authorizer injection so no engine path demands a token; (c) SKILL.md seating prose (code already passes — env → defaults with honest `prefs_source`); (d) the handback-file contract published skill-side (Wave 4 amendment); (e) the suite-level decoupling so the Ecgberht test run does not require the Anchor auth preflight (Wave 1 amendment).

## G. RECOMMENDED PATH (ranked by consequence)

1. **John locks NS v5** (§E — statement, criterion-9 annotation, criterion 14, non-goal). Highest consequence: it is the anti-drift authority; everything else follows mechanically.
2. **Amend IMPLEMENTATION-PLAN-v2 (same document, ~5 waves) + regenerate `wave-decomposition-v2.json`:** W1 suite split (skill lane host-less; auth-ON lane governs Anchor integration); W4 handback CONTRACT moved to skill ownership (schema/contract file + tests in Ecgberht; Anchor wrapper implements it — no new channel, D-1/e-1 untouched); W8+W11 authorizer-injection wording (same negative tests, exercised through the hook; Anchor supplies the token authorizer); W11 retitle; W13 name the status-ingestion seam with the Anchor outbox/mediator as producer #1; W19 add T-HOST-0 as a done-when clause. Estimated delta: days of plan-editing, zero new architecture, DAG unchanged.
3. **SKILL.md pass (Ecgberht repo, small):** retitle §Seating → "Seating (host prefs; Anchor prefs are the reference source)"; document the two altitudes/entry surfaces explicitly; add the T-HOST-0 promise to Install.
4. **Foreman: WAIT** until 1–2 land. The plan's own T-EQUIV-01 makes the doc/JSON pair rigid — amending now is cheap; patching after waves 1–8 are built means re-running the equivalence chain and re-testing done-whens that changed underneath a live build. The wait is days, not weeks.
5. **Keep ONE skill, two entry surfaces** (§C). Optionally add the Foundry governance pointer-map entry for Ecgberht (it lives outside `Skill Foundry\skills\`) — bookkeeping, not blocking.
6. **Grasscatch (do NOT build now):** a generic in-session executor adapter (host agent runs commissioned skills directly from a bare terminal). T-HOST-0 deliberately requires only the honest refusal; the adapter is a later effort with its own scope decision.

**Decisions John must make:** (1) lock NS v5 as drafted (or edit); (2) confirm one-skill-two-surfaces; (3) confirm non-Anchor commission execution = honest refusal for this effort (adapter grasscatched); (4) authorize the plan amendment pass before Foreman.
