# Crucible-planned project — Implementation Plan (Foreman-ready)

test-command: node scripts/run-all-tests.mjs

**North Star:** # E4 North Star — Foundry skill `ecgberht` + engine (Crucible LITE)

**Effort:** Ecgberht next-gen E4  
**Depth:** LITE (locked 2026-07-24 — bounded skill+engine; promote FULL only if Sharks force it)  
**Project:** `<path>  
**Trio pin:** `<path> @ `77de811` (live skills junction; note local dirty `crucible/bin/stage1.mjs` if present)  
**Spelling:** **Ecgberht** only  

## Statement

John gets an installable **Foundry skill named Ecgberht** with a **small deterministic engine** that keeps project campaign memory (Face) and typed attention heartbeat (Strip), ranks “what next” cheaply across projects via strip projection, chooses tool depth via a dispatch table, and **commissions** researchPrime / Crucible / Foreman / Gandalf / Jumper — never reimplements them — all driven by existing **Claude / Gemini / Grok subscription** seats through Anchor model prefs, **without** becoming an OpenClaw-class agent harness and **without** writing into the frozen public Anchor **v1.0.x** tree (any future Anchor UI is **1.1 / next-gen only**).

## Success criteria

1. **Skill pack** — `ecgberht` SKILL.md + templates + schema installable like other Foundry skills (junction/onboard-friendly).  
2. **Engine verbs (closed list)** — at least: `status`, `next`, `update`/`heartbeat`, `depth-suggest`, `soft-vet`/`grasscatch`, `receipt-validate`; unit tests for write authority (Face human narrative vs Strip append-only instruments).  
3. **Face + Strip** — v0 may be single-file Face section + Strip fence/JSON; heal law documented; portfolio rank reads strips first (anti-N-full-read).  
4. **Dispatch table** — phase × uncertainty × human_wait × cost → LITE|FULL|SPIKE|commission|refuse; human override requires receipt reason.  
5. **Compose not reimplement** — no Shark Tank / wave loop inside Ecgberht; no OpenClaw dependency.  
6. **Subscription seating** — no hardcoded product IDs; Anchor prefs / trio drivers only.  
7. **Non-goals enforced in plan** — no v1.0 release edits; no calendar/email OAuth in this build; no default chat gateway tax; harness deferred to separate product.  

## Non-goals

- Editing `Anchor-release-v1.0` / public freeze tags  
- OpenClaw substrate or multi-agent wallets  
- Full calendar/email connectors  
- Replacing Anchor job_runner  
- In-app chat personality product  
- Family-Finances domain features  

## Risk taxonomy

| Risk | Mitigation |
|------|------------|
| Engine becomes mini-harness | Closed verb list + canary (no openclaw paths, no daemon) |
| Dual-surface thrash | v0 single-file dual-section allowed; heal law |
| Ceremony always FULL | Dispatch table + LITE bias |
| Collides with launch | Work only under `<path> + later Anchor-dev |
| Dirty trio stage1 | Stamp SHA; prefer committed behavior |

## Foresight (Oranges)

- **Real intent:** never lose the plot across projects — not prettier MD.  
- **Two steps ahead:** portfolio strip rank before Anchor UI; UI on 1.1 only.  
- **Receipt:** every soft-vet / depth / handback leaves structured fields.  
- **Grasscatcher:** connectors, harness product, launch-tree merge.  

## Depth lock

- **Process depth:** LITE  
- **Rationale:** researchPrime + Gandalf already did heavy thinking; MVP is skill+engine, reversible.  
- **Ceremony:** single-pass seed · Shark roundCap 1 · 2 sharks · user approval Stage 1 & 2.  

## Seat stamp

- Follow Anchor prefs at runtime (`coding_family` / `review_family`); stamp `cross_model` honestly.  


> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 Skill pack scaffold and engine skeleton

**Intent:** Installable Foundry skill surface under <path> with SKILL.md, templates, schemas, fixtures, and a minimal deterministic engine package/CLI stub so later waves fill real verbs without inventing layout (North Star criterion 1).

**Deliverables:** Skill root layout: SKILL.md (name ecgberht, is/is-not table, closed verb list, Face+Strip write-authority notes, Anchor-prefs seating, non-goals), templates/, schema/, fixtures/, bin/ — spelling Ecgberht only; Templates: ECGBERHT.md Face scaffold (north star, active effort, why-next, human-wait; no depth/grasscatch jargon on Face) + Strip fence/JSON stub aligned with campaign v0 strip.json (ecgberht-strip-v0 fields); Schema stubs: Face section markers, Strip JSON schema (phase, active_effort, human_wait, capacity known|unknown, negative_heartbeat, grasscatch, uncertainty_flags, tool_depth_cell, next_recommended/why_next), receipt schema stubs, dispatch-table fixture seed file, verb-help templates for closed list; Engine package skeleton: package.json, engine entrypoint, bin/ecgberht CLI stub that loads and refuses unknown verbs with structured error; trio pin note @77de811 + install/junction notes matching Skill Foundry peers; Unit tests: skill layout present, schemas/fixtures load as JSON, spelling Ecgberht, closed verb list documented, CLI stub refuses unknown verb

**Depends on:** —

**done-when:** Skill pack installs like peer Foundry skills and engine package runs a CLI stub that loads schemas/fixtures and refuses unknown verbs with structured error.

- **Given** A clean skill root under the Ecgberht project with package.json and bin entry, **when** The install surface is inspected and the CLI is invoked with an unknown verb, **then** SKILL.md, templates, schema, and fixtures are present with Ecgberht spelling, schemas parse, and the CLI returns a structured refuse error (not a crash or open plugin dispatch).
- **Given** The Face template and Strip schema stubs from the pack, **when** Fixtures are loaded in unit tests, **then** Face scaffold has human narrative fields only and Strip schema includes the locked ecgberht-strip-v0 instrument fields including capacity known|unknown.

## Wave 2 — W2 Face+Strip protocol, heal law, A1 discovery, and strip-first rank

**Intent:** Durable campaign memory and cheap portfolio attention: v0 dual-section Face+Strip with write authority and heal law, plus A1 discovery (CLI/env, no registry) and strip-first ranking that never N-full-reads Faces (North Star criterion 3 + A1).

**Deliverables:** v0 storage: single-file dual-section Face narrative + fenced/JSON Strip and/or project-root strip.json; N=1 cwd/--project path with zero registry; Write-authority module: Face may rewrite human narrative/north-star/why-stakes; Strip append-only instruments/receipts (reject silent in-place clock rewrite); Heal law documented in skill+schema notes and enforceable helpers: Face wins narrative; Strip wins append-only clocks; crisis = explicit re-sync; silence = negative-heartbeat; chat cannot invent truth; fence/schema drift repair without silent Strip rewrites; A1 discovery (first match wins): CLI --roots, env ECGBERHT_STRIP_ROOTS (OS path separator), find strip.json or ECGBERHT.md Strip fence; scan listed roots + one level of subdirs; ignore node_modules/.git/vendor/junk; empty roots → structured empty result; Strip-first rank: portfolio next/status ranks Strip projections only; full Face only for top-k drill-in or heal; unknown capacity floor (capacity=unknown → rank penalty + LITE bias flag, never silent green); anti-starvation fields negative_heartbeat and anti_starvation_age_days; Unit tests: env parse, CLI roots, find strip.json, find fence in Face, empty roots, Face rewrite allowed, Strip mutation rejected, rank never requires full Face load

**Depends on:** W1 Skill pack scaffold and engine skeleton

**done-when:** Engine can discover strips via CLI/env (no registry), parse Face+Strip with heal/write-authority rules, and rank portfolio next from Strip projections only under unit tests.

- **Given** ECGBERHT_STRIP_ROOTS or --roots pointing at parents with strip.json and/or ECGBERHT.md fences, plus junk dirs, **when** Discovery runs under the locked MVP scan depth, **then** Strips are found without reading every Face fully, junk dirs are skipped, and empty roots return a structured empty result not a crash.
- **Given** A Face narrative and an existing Strip instrument history, **when** A caller attempts Face narrative rewrite and an in-place Strip clock mutation, **then** Face rewrite succeeds; Strip in-place mutation is rejected; only append (or explicit heal re-sync) is allowed.
- **Given** Multiple project strips with capacity=unknown on one and known on others, **when** Portfolio rank runs strip-first, **then** Ranking uses Strip fields only (no full Face load), unknown capacity applies rank penalty and LITE-bias flag, and never silently greens.

## Wave 3 — W3 Closed engine verbs and write-authority enforcement

**Intent:** Fixed closed verb surface (status, next, update/heartbeat, depth-suggest stub, soft-vet/grasscatch, receipt-validate) with refuse-unknown and enforced Face vs Strip write paths so the engine cannot become an open harness (North Star criterion 2).

**Deliverables:** Verb dispatcher: closed list only; unknown verb → structured refuse (no plugin/open dispatch); status: pointer from Strip (+ Face only if needed for top-k display), active effort, human_wait, next_recommended; next: N=1 project path and portfolio path using strip-first rank + why; no full Face for portfolio rank; update/heartbeat: patch Face narrative fields where human-authoritative; append Strip instrument/receipt entries; never rewrite Strip history; soft-vet/grasscatch: park idea with reason; write grasscatch entry + receipt fields (what deferred, why, handback shape); receipt-validate: validate structured receipt schema; monologue-only invalid; depth-suggest verb entry that refuses free-form inflation pending W4 table (or returns table-not-ready structured cell); Canary unit tests: no openclaw path strings and no daemon/listen loop in engine entrypoints; Face rewrite vs Strip append-only; refuse-unknown; strip-first next path

**Depends on:** W2 Face+Strip protocol, heal law, A1 discovery, and strip-first rank

**done-when:** All closed verbs run against fixtures with write-authority enforcement, unknown verbs refuse with structure, and harness canaries (no openclaw, no daemon) pass.

- **Given** A project with Face+Strip fixtures and the closed verb CLI, **when** status and next are invoked for N=1 and for multi-root portfolio, **then** status reports active effort/human_wait/next_recommended from Strip-first data and portfolio next ranks without loading every Face.
- **Given** An update/heartbeat that changes Face narrative and appends a Strip receipt, plus a soft-vet with reason, **when** The verbs execute and Strip history is inspected, **then** Face narrative updates, Strip only gains append entries (including grasscatch receipt fields), and prior Strip clocks are not rewritten.
- **Given** An unknown verb name and engine source under canary scan, **when** The CLI is invoked and canaries run, **then** Unknown verb returns structured refuse; sources contain no openclaw dependency paths and no daemon/listen loop.

## Wave 4 — W4 Dispatch table, depth bias, and structured receipts

**Intent:** Table-driven depth selection with LITE bias and structured receipts for overrides, soft-vets, and handbacks so ceremony is not always FULL and deferred work never loses the plot (North Star criterion 4).

**Deliverables:** Deterministic dispatch table: phase × uncertainty × human_wait × cost → LITE|FULL|SPIKE|commission|refuse; Defaults bias LITE; SPIKE for unknown data shape; FULL only when cell says so; refuse when human_wait blocks or out-of-scope; depth-suggest reads Strip signals + table only; soft-vet fills cells and does not launch specialists; Human override of table outcome requires structured receipt reason (who/when/why/from→to); override without receipt fails receipt-validate; Receipt schema fields for soft-vet/grasscatch/depth/handback: deferred item, why, suggested later owner, uncertainty flags, tool_depth_why; Fixture matrix tests including capacity=unknown → LITE bias + flag

**Depends on:** W3 Closed engine verbs and write-authority enforcement

**done-when:** depth-suggest is fully table-driven with LITE bias, human overrides require validated receipt reasons, and representative matrix cells (including capacity=unknown) pass fixture tests.

- **Given** Strip signals with low uncertainty, no human_wait, and known capacity on a LITE-biased cell, **when** depth-suggest runs, **then** Outcome is LITE (or the explicit table cell) without free-form depth inflation.
- **Given** capacity=unknown and/or unknown data shape on the matrix, **when** depth-suggest and rank-adjacent flags are evaluated, **then** SPIKE or LITE-with-flag per table rules; never silent FULL green; receipt carries uncertainty/capacity flags.
- **Given** A human override from LITE to FULL without receipt fields vs with who/when/why/from→to, **when** receipt-validate runs on both, **then** Override without receipt fails validation; override with structured reason fields passes.

## Wave 5 — W5 Compose-only commission adapters and subscription seating

**Intent:** Commission researchPrime/Crucible/Foreman/Gandalf/Jumper via spawn/handback contracts only and seat models through Anchor prefs/trio subscription drivers—never reimplement Shark Tank/wave loops, never hardcode product IDs, never OpenClaw (North Star criteria 5–6).

**Deliverables:** Commission adapters for researchPrime, Crucible, Foreman, Gandalf, Jumper: pass depth cell, active effort, receipt envelope; zero in-process Shark Tank or Foreman wave loop; Handback contract: structured fields (active_effort, why_next, grasscatch_why, tool_depth_why, human_wait, uncertainty_flags) or fail receipt-validate; Seat resolution: load Anchor prefs (coding_family/review_family/default_cli from settings or ~/.anchor/model_prefs.json); map to subscription drivers only (claude / gemini-cli|agy / grok-cli); stamp cross_model honestly when same-family; Forbid hardcoded Claude/Gemini/Grok product model IDs in skill prose and engine; no XAI_API_KEY HTTP path for production seats; Boundary canaries: openclaw paths, daemon listen, Shark-tank reimplementation markers; work tree confined to <path> SKILL.md non-goals (no v1.0 release edits, no calendar/email OAuth, no chat gateway tax, harness=Grasscatcher product); Unit tests: prefs mock seating without product IDs; handback missing fields fails receipt-validate; adapters are compose hooks only

**Depends on:** W4 Dispatch table, depth bias, and structured receipts

**done-when:** Five compose-only commission adapters resolve seats from Anchor prefs with honest cross_model stamps, handbacks validate as structured receipts, and canaries forbid OpenClaw/daemon/hardcoded product IDs.

- **Given** Mock Anchor model prefs with coding_family and review_family set (including same-family case), **when** Seat resolution runs for a commission, **then** Drivers map to subscription CLIs only, cross_model is stamped true or false honestly, and no product model IDs or XAI_API_KEY HTTP seat path appear.
- **Given** A commission handback missing required structured fields vs a complete handback, **when** receipt-validate is applied, **then** Incomplete handback fails; complete handback with active_effort/why_next/human_wait/uncertainty and depth/grasscatch why fields passes.
- **Given** Engine and skill sources after adapters land, **when** Boundary canaries run, **then** No openclaw dependency paths, no daemon listen loop, no in-process Shark Tank/wave-loop reimplementation; only named compose hooks for the five skills.

## Wave 6 — W6 Verification pack, Grasscatcher ledger, and Stage-2 seed freeze

**Intent:** Close all success criteria with an enforceable test/canary pack and explicit Grasscatcher deferral ledger so MVP scope cannot silently expand and Foreman can execute without reopening architecture (all North Star criteria + non-goals).

**Deliverables:** Consolidated unit suite: write authority Face vs Strip; strip-first rank; A1 discovery; dispatch outcomes + LITE bias; override requires receipt; receipt-validate; refuse-unknown; seating prefs mock without product IDs; Canary pack: no openclaw paths; no daemon; compose-only hooks for five skills; spelling Ecgberht; no Anchor v1.0 release-tree write paths; Grasscatcher ledger (Face/Strip/docs + receipt shape): OpenClaw harness product; calendar/email OAuth; Anchor v1.0.x release edits; default chat gateway; Family-Finances domain; Anchor 1.1 portfolio UI; launch-tree merge; Stage-2-ready freeze set: locked file tree, schemas, fixture matrix, verb contracts, heal law, A1 discovery rules, non-goals — depth remains LITE skill+engine MVP

**Depends on:** W5 Compose-only commission adapters and subscription seating

**done-when:** Full verification and canary packs pass green, Grasscatcher deferrals are named with receipt shape, and the frozen artifact set is sufficient for Foreman implementation without re-litigating scope.

- **Given** The complete engine after W1–W5, **when** The consolidated unit suite and canary pack run, **then** All North Star behaviors under test pass (write authority, strip-first, dispatch LITE bias, receipts, refuse-unknown, prefs seating) and canaries report no openclaw/daemon/v1.0 write paths.
- **Given** The Grasscatcher ledger and Stage-2 freeze artifacts, **when** Scope is audited against the locked Master Plan non-goals, **then** Harness, OAuth connectors, Anchor v1.0 edits, chat gateway, Family-Finances domain, and 1.1 UI are listed as deferred with receipt shape—not implemented as MVP verbs or engine surfaces.
