# Master Plan (APPROVED) — Shareable Anchor + Skills

**North Star:** LOCKED — `NORTH-STAR.md` (by reference; do not re-paste full NS into plans)  
**Status:** APPROVED — John 2026-07-23 (human-lockable after Stage-1 Shark Tank)  
**Crucible depth:** FULL  
**Workspace:** `C:\dev\plans\2026-07-share-anchor-skills\`

## Success criteria
- Dual packages: Skills-only AND Anchor+Skills; never Anchor-only
- Dual audience: public consumer read-only + invited collaborator branch/PR
- No-leak scrubbed distro; tag-freeze vendoring after concurrent skill run
- Plain-English terminal onboard: base dir, prefs, AGENTS.md, subscription CLIs
- Desktop icon → local browser dashboard (Anchor package); local-only v1
- Governance pack + Foundry journal hooks travel with skills
- Opt-in sanitized per-skill friction feedback + de-identified install key → John pull for Foundry sleep
- Reuse share-distro/shareable GREEN machinery; no second distro stack

Phased master plan to ship dual packages (Skills-only A and Anchor+Skills B) from the existing share-distro/shareable stack: freeze-at-tag no-leak packaging, plain-English onboard with subscription seat probes and governance pack, dual-audience git topology, and opt-in fail-closed per-skill friction feedback with de-identified install keys. Near-term work seeds Stage-2 implementation against concrete extension points (distro.py, vendor_skills.py, onboard.py, registrars, scrub gates); execute/ship stays gated on concurrent skill-run merge + declared tags + John go-ahead. Foundry sleep, Tailscale, API-key-first seats, multi-tenant SaaS, and skill-internals rebuilds are out of v1 product scope and deferred by name.

## Phase 1 — P0 — Brownfield map, SUPERSEDES/REUSE, package & capability contracts

Serves NS criteria 1, 7, 8 and risks R2/R10: every later wave must extend one distro stack and hard-couple packages before any new product code. Inclusion test: if it does not prevent double-build or Anchor-only ship, it does not belong in P0.

**Near-term specifics:**
- Inventory and cite GREEN modules/waves in Anchor share-distro + anchor-shareable (distro.py, vendor_skills.py, onboard.py, registrar.py, publish_distro, scrub/clean-scan, default-deny auth, doctor/capability probe, skill integrity) with path+claim table; gap-proof map each North Star criterion (1–9) to existing module or explicit new extension point only.
- Write master SUPERSEDES + REUSE map: this product cut supersedes conflicting product decisions from share-distro delta, ship-anchor (Tailscale/onboard2, tidy-idy exclusion, 4-skill roster), and July topology *for this cut only*; Foreman wave templates require reuse-proof path or gap-proof ticket before new implementation; forbid second publish path.
- Define package matrix contract: emit only Skills (A) or Anchor+Skills (B); hard-block Anchor-only artifact names; B must contain full Skills subtree + declared skills_pin; dual version stamps for A/B and skills_pin in SOURCES.md + release notes.
- Author per-skill capability matrix (works-without-Anchor | degraded-without-Anchor | Anchor-required) covering Trio + Foundry roster (incl. Zombie Hunter, Tidy-Idy, Anchor Doctor as Anchor feature); Skills-only roster excludes/stubs Anchor-required surfaces with plain-English degraded labels, never crash-on-missing-Anchor.
- Freeze interface contracts Stage-2 will implement against: package_matrix schema, capability matrix schema, readiness stamp schema (ready | degraded + reason codes), SOURCES.md multi-repo pin schema, skill freeze tag placeholders (not live trees).
- Stage-1 architecture note enumerates *only* extension points on existing stack (roster config, denylist, onboard dialog steps, governance pack generator, feedback subsystem hooks)—no greenfield distro rewrite.
- Execute/ship gate design (plan-complete ≠ ship-allowed): vendor only after multi-repo agreed tags + clean-scan green + John go-ahead; amendment process if concurrent skill run breaks contracts.

**Deferred (explicitly):**
- Actual vendoring or publishing of live skill trees (sequencing gate until concurrent skill-update merges).
- Re-implementation of already-GREEN security/auth/scrub waves without gap-proof ticket.
- ship-anchor onboard2 / Tailscale / multi-machine remote access.
- Final freeze tag values (placeholders only until post-merge).
- Full public repo creation and collaborator invites (designed in P0; enacted later).

## Phase 2 — P1 — No-leak distro, roster canary, freeze-at-tag provenance

Serves NS criteria 1, 3, 8 and risks R1/R3/R10: safe packaging substrate and canary prove full-roster expansion before public tags. Inclusion test: must reduce leak/skill-drift risk or expand roster via frozen archive/scrub APIs.

**Near-term specifics:**
- Extend vendor_skills.py roster config from 4-skill baseline toward full declared suite via config-only changes; early canary: one large Foundry skill + one Trio skill through existing git-archive → denylist → residual scrub → SOURCES.md path; freeze archive/scrub APIs unless gap-proof redesign ticket.
- Expand denylist + residual host-path/secret scrub; add dual CI fixtures: planted-leak must fail clean-scan; planted-legit skill-prose paths must pass (no false-positive block of legitimate docs).
- SOURCES.md attestation fields: multi-repo skill freeze tags/commits, package matrix versions, scrub tool versions, ship-allowed stamp text (‘only after concurrent skill-run merge + John go-ahead’).
- CI blocks dirty-tree publish; publish pipeline asserts matrix (A or B only; B⊇A; skills_pin present); fail on Anchor-only names.
- Anchor+Skills release pins exact Skills tag/commit; document pin mismatch onboard behavior as degraded (implement print in P2).
- Bundle allowlist excludes author data dirs/secrets; first-run token mint remains local-only; stranger-install assertion design: no author credentials in scrubbed tree.
- Money-safe packaging tests: network deny default; no paid CLI spend; mock archive fixtures only in CI.
- Full-roster canary archive (scrub + clean-scan green) required before first public tag attempt (still gated by skill freeze).

**Deferred (explicitly):**
- Public release tags and mirror pushes (after skill freeze + captain checklist).
- Vendoring during concurrent skill-update run.
- macOS/Linux packaging parity beyond what share-distro already invested (honest best-effort later).
- Automated full-matrix publish bot hardening beyond dirty-tree + clean-scan gates (cadence/alert polish in P5).

## Phase 3 — P2 — Governance pack, journal hooks, consumer install model

Serves NS criteria 4–6 and risks R7/R9/R5: recipients inherit operating culture and journal layout without claiming Foundry sleep is live. Inclusion test: must install rules/hooks that make skills runnable the intended way.

**Near-term specifics:**
- Governance pack generator from John’s canonical AGENTS.md sources + host-personal denylist → version-stamped exportable AGENTS.md + thin CLAUDE.md/GEMINI.md pointers; golden fixture pack in CI (generated pack matches golden after denylist); stranger-machine install test proves no C:\Users\john (or author) paths.
- Ship in pack: Status-table 10-minute format, seating law (prefs → family → subscription CLI transport), skill immutability vs Foundry edit path, journal/run-capture expectations; label Foundry sleep as future-ready, not v1-complete.
- Install Foundry journal layout + minimal append API/hooks in vendored suite; mandatory fields at write time: skill_id, skill_version, outcome class, structural failure codes (schema-versioned semver); smoke: fake run writes a journal file; readiness may warn ‘journal contract unproven’ without claiming improvement loop live.
- Consumer skill install model: read-only-by-default or clear overlay; onboard one-screen paths: consumer vs collaborator vs Foundry-edit; updates = re-vendor from release, not edit-in-place.
- Skills immutability seal: post-onboard checksum/manifest of vendored skills; local edits flag degraded ‘forked’ status and disable feedback export until re-vendor.
- Machine-local home config: chosen home directory becomes base for projects/skills/Anchor; config points skills/future projects at that root without embedding author paths in shipped trees.
- Ready stamp machine-readable on disk: ready requires governance installed + ≥1 coding-family seat probe pass OR explicit user-accepted degraded stamp; Skills package refuses green ready without one of those.

**Deferred (explicitly):**
- Foundry sleep engine completion and automatic global improvement cycles.
- Live skill-side deep instrumentation beyond minimal append hooks.
- Heavy governance UX in Anchor GUI.
- OpenAI transport as coding family (slot reserved; reject sole-family OpenAI until ships).
- Full multi-host AGENTS.md sync orchestration beyond install-once pack.

## Phase 4 — P3 — Plain-English onboard: home, seats, desktop icon, consent, readiness

Serves NS criteria 2, 4, 5, 6, 9 and risks R5/R6/R8: works-on-arrival path with few choices and honest degraded stamps. Inclusion test: each step must onboard a recipient to usable Skills or local Anchor without leaks or silent clobber.

**Near-term specifics:**
- Scripted dialog tree: explain home directory (recommend C:\dev on Windows; user-overridable); permission gates before writing AGENTS.md/pointers, model prefs, skill links/copies, service registration; few choices; resumable state file; refuse-don’t-clobber tests against pre-seeded foreign skill dirs.
- Preflight collision scan on chosen home (foreign skills, OneDrive Desktop, existing Anchor data); offer alternate root; transactional onboard with rollback manifest; never delete foreign trees; multi-user = per-user home documented.
- One upfront actionable prereq list (Python/node/CLI tools as needed) before writes; missing items fail early with fix links.
- Subscription seat probes match production transports exactly: claude, agy-dispatch/agy path, grok.exe -p — session-visibility result, not PATH-only; post-login re-probe walkthrough; stamp cross_model honestly from prefs (same-family allowed); OpenAI seat labeled coming-soon disabled; validation rejects OpenAI as sole coding family until transport ships.
- Optional advanced API-key seat path documented as non-default explicit opt-in; never silent fallback when subscription probe fails.
- Feedback consent step on skills onboard: default no; plain-English what/not shared (sanitized friction only; install key is not a name; not full journal; not work content; residual tiny-cohort re-id risk stated honestly); store choice locally; reversible later with optional key wipe; decline leaves skills fully usable; no readiness gate on feedback opt-in.
- Onboard three-path diagram + one-line ‘local edits stay local’ for consumers; package README dual-audience lead: Download & use vs Invited to collaborate vs Optional friction sharing.
- Anchor package: prefer per-user local service + desktop shortcut/.url without admin; detect elevation need + non-admin fallback; icon opens default browser to local dashboard URL only; idempotent + permission-gated; no remote URL/tunnel in v1.
- OS honesty banner: Windows first-class; macOS/Linux best-effort where share-distro invested; skip icon with clear message; Windows-gated success criteria; support template cites scope.
- Pin mismatch print: if local skills diverge from declared B.skills_pin, stamp/print degraded.
- Mock/fake CLI probes in CI; live probe only behind explicit opt-in env; no recipient API keys in happy-path fixtures.

**Deferred (explicitly):**
- Tailscale / remote multi-machine access (ship-anchor onboard2).
- Cloud-hosted Anchor or multi-user single instance.
- Admin-required service as default (optional path only).
- Full macOS/Linux desktop icon parity claims.
- Interactive GUI onboard wizard (terminal is v1).
- Heavy feedback management UI beyond consent + local preference store.

## Phase 5 — P4 — Opt-in friction feedback: schema, sanitizer, key, transport, dogfood

Serves NS criterion 9 and risks R11–R14: controlled global improvement feed without telemetry of user work. Inclusion test: only friction that is fail-closed, per-skill, de-identified, and intake-separated from product write access.

**Near-term specifics:**
- Structured friction schema at journal-append time (not NLP over session blobs): skill_id + skill_version (from vendored SOURCES/skill manifest, not mtime), outcome class, structural failure codes, duration/complexity bands (coarse enums), OS class, model-family seats (not account ids), workaround as enum/coded categories + short bounded tokens only.
- Sanitizer produces subset export only when opted in; allowlist fields only; every string field runs PII/path/prompt/session-purpose detectors; hard-drop record on hit; fail closed if cannot prove clean—nothing sent; untagged records dropped.
- De-identified install key: high-entropy random UUID minted on opt-in only; never hash email/username/machine/path; rotate/wipe with continuity-break warning; residual-risk doc at opt-in.
- Local full journals always remain local; never retro-upload prior journals on later opt-in; opt-out stops new sends and may wipe key; local queue for offline/unreachable intake—send only while consent still valid; never send after mid-queue opt-out (optional encrypted-at-rest for queue).
- Transport: recipient-side push of sanitizer-proven JSON/NDJSON to John-owned private intake (repo subtree or dedicated inbox repo) via token-scoped bot or mail-like drop; John pull/review on schedule; no auto-merge to skill sources; separate credentials from product main; docs hard-line feedback ≠ code contribution.
- Intake storage hard-partitioned by skill_id folders/tags; schema validation at edge rejects unknown fields and free-text overflow; forbid cross-skill default rollup (R14 tests).
- Red-team suite: plant PII, absolute paths, secrets, session-purpose prose; assert drop/fail-closed; skills immutability seal blocks export from forked trees.
- Dogfood: opt-in among invited collaborators first with thinnest viable intake; measure export yield before public claim; if yield zero, kill channel cost honestly rather than build heavy UI.
- Schema-versioned journal + feedback contracts (semver); sanitizer and intake validate version; forward-compat rules so post-plan skill changes don’t silently break exports.

**Deferred (explicitly):**
- Foundry sleep consumption of the feed (feed ships; sleep consumes when ready).
- Heavy feedback analytics UI / dashboards for recipients.
- k-anonymity floor suppression beyond optional design note (implement only if dogfood shows re-id risk).
- Public marketing of feedback channel before dogfood yield measured.
- Any default-on telemetry or full journal sync.
- Open PR of sanitized reports into product main (forbidden).

## Phase 6 — P5 — Dual-audience topology, CONTRIBUTING, intake ops, release cadence

Serves NS criteria 2, 3, 9 and risks R4/R12: git-honest audiences and one-way mirrors without confusing feedback with code write access. Inclusion test: must make consumer vs collaborator vs feedback paths unambiguous and enforceable.

**Near-term specifics:**
- Topology implement design: private *-dev source of truth + one-way public mirrors/releases; public mirror writable only by bot identity; human hand-edits of public mirrors forbidden by process and access.
- Collaborator invite checklist: private repo invite, branch protection (no force-push, no direct main), CODEOWNERS, PR-only integrate; auto-close/misroute guidance for uninvited PRs.
- CONTRIBUTING + public README write policy: public consumers get issues/sanitized-feedback only; no open PRs into private upstream without invitation; backlog SLA honest (review when free); three-path diagram (use / sanitized-feedback / collaborate).
- Feedback intake path documented as separate John-controlled channel with pull-only review before any skill-source merge; never product-main write credentials on recipient machines.
- Mirror lag badge + release cadence checklist in public README; pin consumers to release artifacts not floating main; alert when private tag lacks public publish.
- Release captain checklist John signs: freeze tags present, clean-scan green, SOURCES.md complete, package matrix green, stranger install smoke, feedback sanitizer red-team green.
- Package-level README dual-audience lead with links to CONTRIBUTING and privacy/friction copy.

**Deferred (explicitly):**
- Accepting unsolicited public PRs into private upstream.
- SaaS multi-tenant hosting or John-operated cloud Anchor.
- Migrating John’s live personal projects into public packages.
- Full SLA-backed community support org.
- Automated sleep-driven skill PR generation from intake (Foundry maturity).

## Phase 7 — P6 — CI matrices, stranger E2E, execute gate, Stage-2 handoff

Serves NS criteria 1, 3, 6, 7, 8 and risk R1/R7: prove money-safe, no-leak, works-on-arrival paths and freeze the Foreman-ready implementation plan. Inclusion test: must be checkable proof before any real ship wave.

**Near-term specifics:**
- Skills-only CI smoke matrix runs without Anchor process; Anchor+Skills CI asserts B⊇A and Doctor/Zombie/Tidy surfaces present in B per capability matrix.
- Money-safe gate: mock CLI probes; network deny default; live probes behind opt-in env only; no paid spend; no recipient API keys in happy-path fixtures.
- Governance golden + clean-scan on governance artifact; dual scrub fixtures (leak fail / legit pass) required for publish job.
- Stranger-install E2E on clean Windows VM: scrubbed zip → onboard → seat probe → (B) local dashboard via desktop icon; assert no author secrets; readiness stamp present.
- Non-admin Windows matrix for service + desktop .url path.
- Bind Stage-2 implementation plan to interfaces + tag placeholders from P0; re-validation gate at execute: actual freeze tags must match SOURCES placeholders or plan amendment.
- Foreman wave text templates: reuse-proof section mandatory; security/Tailscale/onboard2 reimplementation forbidden without gap-proof ticket.
- Ship gate checklist artifact in plan workspace: concurrent skill-run merged + multi-repo tags + clean-scan + captain sign-off + John go-ahead.

**Deferred (explicitly):**
- Foreman execute waves against live skill trees before freeze (hard gate).
- Public first release until stranger E2E + red-team sanitizer green.
- macOS/Linux E2E as first-class pass criteria (best-effort notes only).
- Post-v1: Tailscale onboard2, OpenAI seat transport, Foundry sleep automation, multi-machine.
- Rebuilding skill internals (Crucible/Foreman/researchPrime/etc.)—out of effort forever for this plan.
