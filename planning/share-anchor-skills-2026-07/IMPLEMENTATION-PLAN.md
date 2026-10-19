# Shareable Anchor + Skills â€” Implementation Plan (Foreman-ready)

test-command: python -m pytest -v tests/test_share_contracts_w1.py tests/test_share_roster_scrub_w2.py tests/test_share_sources_publish_w3.py tests/test_share_governance_w4.py tests/test_share_onboard_w5.py tests/test_share_feedback_w6.py tests/test_share_feedback_w7.py tests/test_share_topology_w8.py tests/test_share_ci_ship_gate_w9.py

**North Star:** LOCKED Shareable Anchor + Skills â€” see NORTH-STAR.md (by reference; full text not re-embedded).

## Success criteria
- Dual packages: Skills-only AND Anchor+Skills; never Anchor-only
- Dual audience: public consumer read-only + invited collaborator branch/PR
- No-leak scrubbed distro; tag-freeze vendoring after concurrent skill run
- Plain-English terminal onboard: base dir, prefs, AGENTS.md, subscription CLIs
- Desktop icon â†’ local browser dashboard (Anchor package); local-only v1
- Governance pack + Foundry journal hooks travel with skills
- Opt-in sanitized per-skill friction feedback + de-identified install key â†’ John pull for Foundry sleep
- Reuse share-distro/shareable GREEN machinery; no second distro stack

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 â€” W1 Contracts brownfield package matrix and capability schemas

**Intent:** Lock extension-only reuse of share-distro/shareable GREEN stack; encode package A/B coupling, capability matrix, readiness/SOURCES freeze contracts, and SUPERSEDES/REUSE so later waves cannot invent a second distro or Anchor-only ship (NS 1,7,8; R2/R10).

**Deliverables:** Path+claim inventory of GREEN modules (distro.py, vendor_skills.py, onboard.py, registrar, publish_distro, scrub/clean-scan, default-deny auth, doctor) with NS criterion to module gap map; SUPERSEDES-REUSE.md plus machine-checkable reuse markers for Foreman wave templates; JSON schemas and validators: package_matrix, capability_matrix, readiness stamp (ready|degraded + reason codes), SOURCES multi-repo pin, freeze-manifest with tag placeholders; Package matrix module: emit only Skills(A) or Anchor+Skills(B); hard-fail Anchor-only names; B requires skills subtree + skills_pin; Per-skill capability matrix data for Trio+Foundry roster (works-without-Anchor | degraded-without-Anchor | Anchor-required) with degraded labels for Skills-only stubs; Unit tests: schema validation, Anchor-only reject, B requires skills_pin, capability enum coverage

**Depends on:** â€”

**done-when:** Validators and package/capability matrices pass tests; Anchor-only artifact names hard-fail; every NS criterion maps to an existing GREEN module or one named extension point; freeze tag fields are placeholders only.

- **Given** A publish request names an Anchor-only artifact, **when** the package matrix validator runs, **then** it fails closed and no package is emitted
- **Given** package B is declared without skills_pin, **when** the freeze-manifest / package_matrix check runs, **then** validation fails with a skills_pin-required reason code
- **Given** Zombie Hunter and Anchor Doctor are in the capability matrix, **when** Skills-only roster is resolved, **then** Anchor-required surfaces are excluded or degraded-labeled and do not crash-on-missing-Anchor

## Wave 2 â€” W2 Roster expansion no-leak canary and dual scrub fixtures

**Intent:** Expand vendored skill roster via existing git-archive denylist scrub APIs and prove no-leak packaging with dual fixtures before any public tag (NS 1,3,8; R1/R3).

**Deliverables:** vendor_skills.py roster config extended from 4-skill baseline toward full declared suite (config-only; freeze archive/scrub APIs); Early canary path: one large Foundry skill + one Trio skill through git-archive, denylist, residual scrub, SOURCES stub; Expanded denylist + residual host-path/secret scrub rules; Dual CI fixtures: planted-leak must fail clean-scan; planted-legit skill-prose paths must pass; Bundle allowlist excluding author data dirs/secrets; stranger-tree assertion that author credentials are absent; Money-safe packaging tests: network deny default; mock archive fixtures only; no paid CLI spend

**Depends on:** W1 Contracts brownfield package matrix and capability schemas

**done-when:** Canary archive for one Foundry + one Trio skill is scrub-green; planted-leak fixture fails clean-scan and planted-legit passes; roster config covers the declared suite expansion path without rewriting archive/scrub APIs.

- **Given** a fixture tree contains an absolute author host path and a secret-shaped token, **when** clean-scan runs on the scrubbed canary archive, **then** the scan fails and publish is blocked
- **Given** a fixture skill doc mentions a legitimate relative path in prose, **when** clean-scan runs, **then** the scan passes with no false-positive block
- **Given** canary vendoring is invoked with mock archive fixtures and network denied, **when** packaging tests execute in CI, **then** no network calls or paid CLI invocations occur and the canary completes green

## Wave 3 â€” W3 SOURCES provenance and package publish matrix gates

**Intent:** Stamp multi-repo freeze provenance and enforce A-or-B publish matrix with B contains A and dirty-tree blocks so skill drift and Anchor-only ships cannot reach release artifacts (NS 1,3,8; R1/R2/R3).

**Deliverables:** SOURCES.md writer with multi-repo skill freeze tags/commits, package matrix versions, scrub tool versions, ship-allowed stamp text gated on concurrent skill-run merge + John go-ahead; Publish pipeline asserts: A or B only; B contains full Skills subtree + skills_pin; Anchor-only names fail; dirty working tree blocks publish; Anchor+Skills release pins exact Skills tag/commit; pin-mismatch degraded reason code defined for onboard; Full-roster canary archive path (scrub + clean-scan) required before first public-tag attempt (still freeze-gated); verify_freeze_manifest CLI/module validating placeholders vs schema from W1; CI jobs: dirty-tree publish block, matrix assert, B_contains_A checksum equality when both packages built

**Depends on:** W2 Roster expansion no-leak canary and dual scrub fixtures

**done-when:** Publish path refuses dirty trees and Anchor-only names; B contains A and skills_pin are enforced in CI; SOURCES.md emits required attestation fields with freeze placeholders; full-roster canary scrub is green under mock fixtures.

- **Given** the working tree is dirty mid skill-run, **when** publish is invoked, **then** publish fails before any artifact is written
- **Given** both A and B artifacts are produced for the same skills_pin, **when** B_contains_A CI job runs, **then** skills subtree checksum in B equals A for that pin
- **Given** SOURCES.md is generated for a freeze-placeholder build, **when** verify_freeze_manifest runs, **then** schema validation passes and ship-allowed stamp remains false until go-ahead conditions are recorded

## Wave 4 â€” W4 Governance pack generator journal hooks and readiness stamp

**Intent:** Ship exportable operating rules and Foundry journal layout so recipients run skills the intended way without claiming Foundry sleep is live (NS 4-6; R5/R7/R9).

**Deliverables:** Governance pack generator from canonical AGENTS.md sources + host-personal denylist producing version-stamped AGENTS.md + thin CLAUDE.md/GEMINI.md pointers; Pack content: Status-table 10-minute format, seating law (prefs to family to subscription CLI), skill immutability vs Foundry edit path, journal expectations; Foundry sleep labeled future-ready; Golden fixture CI: generated pack matches golden after denylist; stranger-machine test asserts no author paths; Foundry journal layout + minimal append API/hooks with mandatory fields skill_id, skill_version, outcome class, structural failure codes (schema-versioned semver); Skills immutability seal: post-onboard checksum/manifest; local edits yield degraded forked status and block feedback export until re-vendor; Machine-local home config root for projects/skills/Anchor without author paths in shipped trees; Machine-readable readiness stamp: ready requires governance installed + at least one coding-family seat probe OR explicit user-accepted degraded; Skills refuse green ready otherwise; Smoke test: structured run appends a valid journal file; readiness may warn journal_contract_unproven

**Depends on:** W3 SOURCES provenance and package publish matrix gates

**done-when:** Governance golden CI is green with no author paths; journal append writes schema-valid records; immutability seal detects local skill edits; readiness stamp encodes ready vs degraded reason codes and refuses false green ready.

- **Given** canonical AGENTS.md sources containing author host paths, **when** the governance pack generator runs with the host-personal denylist, **then** exported pack matches golden and contains no author absolute paths
- **Given** a structured skill run completes with mandatory journal fields, **when** the append hook is invoked, **then** a journal file is written with skill_id, skill_version, outcome class, and structural failure codes
- **Given** governance is installed but no coding-family seat has passed and user has not accepted degraded, **when** readiness is computed for Skills package, **then** stamp is not green ready and reason codes explain the missing seat conditions

## Wave 5 â€” W5 Plain-English onboard home prereqs seats desktop consent readiness

**Intent:** Deliver works-on-arrival terminal onboard for Skills and Anchor+Skills: few choices, permission-gated writes, real seat probes, local desktop shortcut, feedback consent default-off, honest degraded stamps (NS 2,4,5,6,9; R5/R6/R8).

**Deliverables:** Scripted dialog tree: home dir explain (recommend C:\\dev on Windows, overridable); permission gates before AGENTS.md/pointers, model prefs, skill links/copies, service registration; resumable state file; Preflight collision scan (foreign skills, OneDrive Desktop, existing Anchor data); alternate root offer; transactional onboard with rollback manifest; refuse-dont-clobber foreign skill dirs; One upfront actionable prereq list; fail early with fix links before writes; Subscription seat probes matching production transports: claude, agy-dispatch/agy, grok.exe -p (session-visibility, not PATH-only); post-login re-probe; cross_model stamped honestly; OpenAI coming-soon disabled; reject OpenAI as sole coding family; Optional advanced API-key seat path documented as non-default explicit opt-in; never silent fallback on subscription probe fail; Feedback consent step (default no) with plain-English what/not shared and residual re-id risk; local reversible preference + optional key wipe; decline leaves skills fully usable; not a readiness gate; Anchor package: per-user local service + desktop shortcut/.url without admin when possible; icon opens default browser to local dashboard URL only; OS honesty banner; pin-mismatch degraded print; Three-path consumer/collaborator/feedback copy in onboard + package README lead-in; CI: mock/fake CLI probes only; live probes behind opt-in env; no recipient API keys in happy-path fixtures

**Depends on:** W4 Governance pack generator journal hooks and readiness stamp

**done-when:** Idempotent onboard installs governance and skills into chosen home without clobbering foreign trees; mock seat probes stamp readiness ready or degraded correctly; feedback consent defaults off; Anchor package creates local-only desktop shortcut; money-safe mock probes pass in CI.

- **Given** a pre-seeded foreign skill directory exists under the chosen home, **when** onboard runs with refuse-dont-clobber policy, **then** foreign tree is left intact, onboard uses overlay or alternate path or aborts with a clear collision message, and rollback leaves no partial clobber
- **Given** mock claude seat probe reports session-visible and governance is installed, **when** readiness is written at end of skills onboard, **then** stamp is ready (or degraded only for unrelated reasons) and feedback opt-in is still false by default
- **Given** Anchor+Skills package onboard on Windows non-admin path, **when** desktop shortcut step runs, **then** a .url or equivalent opens the local dashboard URL only with no remote or tunnel URL and elevation is not required for the default path

## Wave 6 â€” W6 Opt-in friction schema sanitizer install key and local queue

**Intent:** Build fail-closed per-skill friction export with de-identified install key and local-only full journals so global improvement feed cannot leak session content (NS 9; R11/R13/R14).

**Deliverables:** Structured friction schema at journal-append time (enums only): skill_id and skill_version from SOURCES/manifest, outcome class, structural failure codes, duration/complexity bands, OS class, model-family seats, workaround coded categories + short bounded tokens; Sanitizer: allowlist fields only; PII/path/prompt/session-purpose detectors on every string; hard-drop on hit; fail closed if not provably clean; untagged records dropped; De-identified install key: high-entropy random UUID minted only on opt-in; never hash email/username/machine/path; rotate/wipe with continuity-break warning; Local full journals always remain local; no retro-upload on later opt-in; opt-out stops new sends and may wipe key; Local offline queue: send only while consent valid; never send after mid-queue opt-out; optional encrypted-at-rest queue; Immutability seal gate: forked skill trees cannot export feedback; Schema-versioned journal and feedback contracts (semver) with forward-compat validation rules; Unit and red-team fixtures planting PII, absolute paths, secrets, session-purpose prose asserting drop/fail-closed

**Depends on:** W5 Plain-English onboard home prereqs seats desktop consent readiness

**done-when:** Sanitizer unit and red-team suites pass fail-closed; opt-in mints opaque install key; opt-out prevents further queue drain; forked trees block export; full local journals are never included in export payloads.

- **Given** user is opted in and a journal record contains an email and an absolute host path, **when** sanitizer builds an export, **then** the record is dropped and nothing is enqueued or sent for that record
- **Given** user declines feedback or later opts out with a non-empty local queue, **when** queue drain runs, **then** no records are transmitted and optional key wipe removes the install key
- **Given** vendored skills fail the immutability seal (local fork), **when** export is attempted while opted in, **then** export is blocked with a forked/degraded reason and no payload leaves the machine

## Wave 7 â€” W7 Feedback transport intake partition and dogfood harness

**Intent:** Deliver controlled John-owned intake transport separated from product write access, hard-partitioned per skill, with dogfood-ready thin path (NS 9; R11/R12/R14).

**Deliverables:** Recipient-side push of sanitizer-proven JSON/NDJSON to John-owned private intake (repo subtree or dedicated inbox) via token-scoped bot or mail-like drop; Credentials scoped only to intake path, never product main write; docs hard-line feedback is not code contribution; Intake storage hard-partitioned by skill_id folders/tags; edge schema validation rejects unknown fields and free-text overflow; forbid cross-skill default rollup; John pull/review workflow stubs with no auto-merge to skill sources; Dogfood harness for invited collaborators: thinnest viable intake, export-yield metrics, kill-channel-if-zero-yield note; Integration tests: per-skill partition, credential scope assert, no auto-merge path, R14 no cross-skill blob rollup

**Depends on:** W6 Opt-in friction schema sanitizer install key and local queue

**done-when:** Sanitizer-clean records land only under per-skill intake partitions using intake-scoped credentials; product-main credentials are absent from recipient config; edge validation rejects dirty payloads; dogfood harness can measure export yield without public marketing claims.

- **Given** two clean friction records for Crucible and Foreman from the same install key, **when** transport delivers them to intake, **then** they land in separate skill_id partitions and retain the same de-identified install key for pattern spotting
- **Given** a payload with unknown fields or free-text overflow, **when** intake edge validation runs, **then** the payload is rejected and not stored
- **Given** recipient machine config for feedback transport, **when** credentials are inspected by tests, **then** only intake-scoped tokens exist and product-main write credentials are absent

## Wave 8 â€” W8 Dual-audience topology CONTRIBUTING and release captain checklist

**Intent:** Make consumer vs collaborator vs sanitized-feedback paths git-honest and enforceable with one-way mirrors and a signed release captain gate (NS 2,3,9; R4/R12).

**Deliverables:** Topology implementation assets: private *-dev source of truth + one-way public mirror/release process; bot-only public write; human hand-edit forbidden by access/process checks where automatable; Collaborator invite checklist automation/docs-as-code: branch protection (no force-push, no direct main), CODEOWNERS, PR-only integrate; uninvited PR misroute guidance; CONTRIBUTING + public README write policy with three-path diagram (use / sanitized-feedback / collaborate); honest backlog SLA; Feedback intake ops docs linked as separate channel from product write access; Mirror lag badge + release cadence checklist; pin consumers to release artifacts not floating main; alert hook when private tag lacks public publish; Release captain checklist (machine-checkable where possible): freeze tags, clean-scan green, SOURCES complete, package matrix green, stranger install smoke, sanitizer red-team green; Package-level README dual-audience lead with CONTRIBUTING and privacy/friction links; Tests/scripts verifying README/CONTRIBUTING required sections and captain checklist item presence

**Depends on:** W7 Feedback transport intake partition and dogfood harness

**done-when:** Topology scripts/checklists enforce private SoT + one-way public publish; CONTRIBUTING and package READMEs pass required-section tests for three-path write policy; captain checklist is complete and machine-checkable for freeze/clean-scan/matrix/smoke/red-team items.

- **Given** a private release tag exists without a matching public publish, **when** mirror lag / cadence check runs, **then** an alert or failed checklist item is raised and consumers remain pinned to last public release artifacts
- **Given** public README and CONTRIBUTING templates are generated, **when** required-section tests run, **then** consumer read-only policy, collaborator branch/PR path, and separate sanitized-feedback channel are all present and feedback is not described as code push to main
- **Given** captain checklist is evaluated before a would-be public release, **when** any of freeze tags, clean-scan, or sanitizer red-team is red, **then** checklist fails closed and release is not marked ship-allowed

## Wave 9 â€” W9 CI matrices stranger E2E and ship execute gate

**Intent:** Prove money-safe no-leak works-on-arrival paths end-to-end and freeze the execute/ship gate on skill freeze tags + John go-ahead before any live vendoring (NS 1,3,6,7,8; R1/R7).

**Deliverables:** Skills-only CI smoke matrix without Anchor process; day-1 path asserts governance + seat probe (mock) + one skill invoke readiness; Anchor+Skills CI asserts B contains A and Doctor/Zombie/Tidy surfaces present per capability matrix; Money-safe gate wired globally: mock CLI probes, network deny default, live probes only behind opt-in env, no paid spend, no recipient API keys in happy-path fixtures; Governance golden + clean-scan on governance artifact; dual scrub fixtures required for publish job; Stranger-install E2E harness (clean Windows path): scrubbed zip to onboard to seat probe to (B) local dashboard via desktop shortcut; assert no author secrets; readiness stamp present; Non-admin Windows matrix for service + desktop .url path; Execute re-validation gate: actual freeze tags must match SOURCES placeholders or plan amendment; verify_freeze_manifest green; Foreman wave text templates: reuse-proof section mandatory; forbid security/Tailscale/onboard2 reimplementation without gap-proof ticket; no skill-internals rebuild waves; Ship gate checklist artifact in plan workspace: concurrent skill-run merged + multi-repo tags + clean-scan + captain sign-off + John go-ahead

**Depends on:** W8 Dual-audience topology CONTRIBUTING and release captain checklist

**done-when:** Skills-only and Anchor+Skills CI matrices are green under money-safe defaults; stranger-install E2E and non-admin desktop path pass on Windows fixtures; ship/execute gate blocks until freeze tags match SOURCES and captain+John go-ahead are recorded; no live skill-tree ship without the gate.

- **Given** Skills-only CI matrix with network denied and mock seat probes, **when** the smoke job runs, **then** it completes without starting an Anchor process, without paid CLI spend, and writes a readiness stamp
- **Given** a scrubbed stranger zip for package B on a clean Windows fixture, **when** E2E onboard to seat probe to desktop shortcut path runs, **then** local dashboard URL is reachable via the shortcut, readiness stamp exists, and no author secrets appear in the installed tree
- **Given** freeze placeholders in SOURCES do not match actual multi-repo tags or go-ahead is missing, **when** execute/ship gate is evaluated, **then** the gate fails closed and Foreman is not allowed to vendor live skill trees
