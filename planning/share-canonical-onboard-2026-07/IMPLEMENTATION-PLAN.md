test-command: python -m pytest tests/ -k share_ -v --tb=line

﻿test-command: python -m pytest tests/ -k share_ -v --tb=line

# Implementation Plan â€” Canonical SKILLS_ROOT + full A/B onboard

**Project:** Canonical skills root + guided Package A/B onboard  
**North Star:** LOCKED 2026-07-24 (`NORTH-STAR.md`)  
**Master Plan:** APPROVED 2026-07-24 + **Amendment A1 icons** (`MASTER-PLAN.md`)  
**Depth:** LITE  
**Stage-2 note:** Engine completed wave decompose (8) + Shark r1 (DRY, 0 â‰¥2-agree blockers) then stalled mid-challenge without emit. This plan is **synthesized for human lock** from the approved Master Plan, A1, decomposition, and round-1 findings (all agreement=1). **Not auto-approved** â€” John must lock before Foreman.

**Repo / working tree for Foreman:** `C:\dev\Anchor` (extend GREEN `share_*` / `onboard` / `vendor_skills`; no second distro stack).

**Default gate command (project):**  
`python -m pytest tests/ -k share_ -q --tb=line`

---

## Wave 1 — Skills-root registry + portfolio equality (BEFORE install)

**Done when:** Registry schema + equality oracle exist and **fail** false GREEN (Claude-compat-only Grok).

### Acceptance
- Given a skills-root/v1 doc missing required fields, when validated, then reject with clear problems.
- Given portfolio = vendor-pin ID set, when Grok adapter omits SKILLS_ROOT but Claude farm is full, then equality oracle **FAILS**.
- Given host-native extra skills (Grok bundled), when equality runs, then extras ignored and pin match still can PASS.
- Gemini promote **or** demote is recorded in code/docs (no half-registered).

### Work
1. Add/extend schema `share_schemas` + `skills_root.json` write via share_home_config/governance.
2. Implement `list_portfolio_ids_claude|grok|anchor` and equality oracle.
3. Adapter contract stubs: `resolve_skills_root`, `write_registry`, `register_host`, `resolve_skill_journal_dir`.
4. Pytest: round-trip registry; false-GREEN Grok-compat case; install_mode enum.

### Tests
`python -m pytest tests/test_share_skills_root_w0.py -q` (new) + existing share contracts if touched.

---

## Wave 2 — SKILLS_ROOT install + multi-host register + journal law

**Done when:** Product bytes once under SKILLS_ROOT; Claude is pointer-only; journals resolve under SKILLS_ROOT via named helper; hermetic simulated runs prove realpath.

### Acceptance
- Given recipient install, when skills land, then only `SKILLS_ROOT/<id>/` holds product bytes (no second full tree under `~/.claude/skills`).
- Given Claude adapter path, when inspected, then junction/symlink/pointer to SKILLS_ROOT (or documented non-copy load).
- Given `resolve_skill_journal_dir(id)`, when used by share_skill_journal, then path is `SKILLS_ROOT/id/journal`.
- Given simulated run via Claude, Grok, and Anchor entry points, when journal written, then `realpath(file)` is under `realpath(SKILLS_ROOT)`.
- Equality oracle PASSES after register for required hosts.

### Work
1. Extend `onboard.install_skills` / vendor path to target SKILLS_ROOT only.
2. Implement register_host for claude (pointer), grok (`[skills].paths`), gemini (per W0 decision), anchor (`ANCHOR_SKILLS_ROOT`).
3. Bind journal writers to `resolve_skill_journal_dir`.
4. Seal after copy; refuse dual-copy on re-onboard.
5. Pytest hermetic temp home.

### Tests
`python -m pytest tests/test_share_skills_root_w1.py tests/test_share_onboard_w5.py -q`

---

## Wave 3 — Interactive onboard CLI (sole cold-start)

**Done when:** `python -m share_onboard` runs guided dialogue; silent path never stamps ready; feedback step 8 default No.

### Dialogue order (lock)
1. Home picker (recommend `C:\dev`)  
2. Python detect / PATH fix links; hard fail if missing  
3. Package A|B auto-detect  
4. Permissions list  
5. Install + host register (W1)  
6. Governance AGENTS pointers  
7. Seat probe (claude/agy/grok)  
8. **Feedback consent** (exact FEEDBACK_CONSENT_COPY; **default No**; mint install_key only on Yes)  
9. If B â†’ hand to W4  
10. Readiness stamp + next steps  

### Acceptance
- Given zero coding seats, when onboard finishes, then readiness `not-ready` and non-zero exit.
- Given silent/non-interactive path without full dialogue, when complete, then **not** ready (fail closed).
- Given feedback No, when export attempted, then blocked; no install_key.
- Given feedback Yes, when export, then allowlist-only + install_key present; no full journal upload.
- Cold-start is `python -m share_onboard` (not `/onboard` skill).

### Work
1. Implement `python -m share_onboard` / onboard_cli on share_onboard.
2. Wire seat matrix and readiness stamps.
3. Feedback consent UX + tests for default-off and sanitizer.
4. Transcript-friendly print strings (plain ASCII preferred).

### Tests
`python -m pytest tests/test_share_onboard_w5.py tests/test_share_feedback_w6.py -q`

---

## Wave 4 — Package A end-to-end

**Done when:** Hermetic Package A onboard: registry, pointers, equality, no Anchor service, honest hosts_registered.

### Acceptance
- Package A never starts Anchor service.
- hosts_registered lists only hosts actually registered.
- vendor/ship still denies journal/.
- Re-run idempotent; no dual Claude copy.

### Work
1. Package A path integration + readiness artifact.
2. AGENTS body + Claude/Grok thin pointers.
3. Regression tests for A-only.

### Tests
`python -m pytest tests/test_share_ -k "package_a or skills_root or onboard" -q`

---

## Wave 5 — Package B: service + desktop anchor.ico + favicon + skill icons

**Done when:** B dual gate + Amendment A1 branding acceptance.

### Acceptance (split gates)
1. **Service honesty:** start/probe fail â‡’ not-ready / B-incomplete / non-zero; never success on silent foreground_fallback alone.  
2. **B_ready â‡”** HTTP local dashboard OK **AND** desktop shortcut exists with **universal `anchor.ico`** (IconLocation via `create_shortcut.py` or same contract) **AND** shortcut URL == probed dashboard URL.  
3. **Favicon:** ship includes `anchor.ico`/`anchor.png`; GET `/favicon.ico` or `/anchor.ico` OK after service up.  
4. **Skill icons:** portfolio brand icons resolve in Foundry/dashboard skill lists (no broken images; default fallback allowed if documented).  
5. Bare `.url` without Anchor icon is **not** B-complete for branding.

### Work
1. B path: scaffold Anchor, token path-only, start service, HTTP probe.
2. Desktop: prefer `create_shortcut.py` / .lnk with IconLocation=anchor.ico (not bare .url-only).
3. Ensure favicon assets + routes in package.
4. Ensure vendor/brand + skill icons install with product/skills; Foundry list uses them.
5. Tests: success and failure branches for service; icon path assertions; favicon GET in hermetic or mock.

### Tests
`python -m pytest tests/test_share_ -k "package_b or desktop or shortcut or onboard" -q`

---

## Wave 6 — Docs + rights reserved

**Done when:** Email-ready install doc; no OSS license stamp; rights-reserved line.

### Acceptance
- Doc: clone/unzip â†’ `python -m share_onboard` cold-start; A vs B; feedback step; B icons/service.
- Explicit rights-reserved / not open-source.

### Work
1. USER-ONBOARD.md (or README section) in share planning / package.
2. No LICENSE file added.

### Tests
Doc presence checks in ship gate if applicable; light pytest for string markers optional.

---

## Wave 7 — Sandbox transcript gate

**Done when:** Golden A/B transcripts match user-visible dialogue; silent path cannot pass as ready.

### Acceptance
- Scripted stdin A and B transcripts include home, Python, permissions, feedback default No wording, readiness; B includes probe + desktop/icon or honest fail.
- CI/share_ci style drift check on user-visible strings.

### Work
1. Golden fixtures under tests or planning gate.
2. Wire into share_ci_ship_gate if present.

### Tests
`python -m pytest tests/test_share_ci_ship_gate_w9.py -q` (extend as needed)

---

## Wave 8 — Author machine index (optional / non-blocking)

**Done when:** Documented/scripted Grok paths + Anchor root point at Foundry+trio index on author host. Does not block recipient A/B GREEN.

### Work
1. Author skills_root index notes or small register script.
2. Optional later hub `C:\dev\skills` â€” deferred.

---

## Global constraints (every wave)

- Reuse: `share_onboard`, `share_home_config`, `share_governance`, `share_feedback`, `share_skill_journal`, `share_skill_seal`, `share_readiness`, `onboard.install_skills`, `vendor_skills`, `create_shortcut.py` â€” **extend only**.
- No open-source license stamp.
- No auto-merge of friction intake to skill main.
- No shipping journals in packages.
- Feedback: step 8, default off, not a readiness gate.
- Status tables / user strings: prefer plain ASCII.

---

## Shark r1 notes absorbed (agreement=1 â€” human-lockable, not formal â‰¥2 blockers)

- Equality scoped to **registered** hosts only; hosts_registered honesty (W0/W3).
- Cold-start path must be explicit for strangers (`python -m share_onboard`) (W2).
- Feedback allowlist/export paths tested (W2).
- Home picker vs SKILLS_ROOT layout clear (W1).
- Package A/B auto-detect explicit (W2).
- Journal NNNN + runs layout under skill dir (W1).
- B dual gate not over-read as A readiness (W3/W4).
- Gemini promote/demote decided in W0 (not left open).
- **A1 overrides demotion of skill icons:** brand/skill icons and anchor.ico **are** acceptance for this build (A1 locked with Master Plan).

---

## Foreman handoff fields

| Field | Value |
|-------|--------|
| outputDir / plan home | `C:\dev\plans\2026-07-skills-canonical-onboard` |
| code root | `C:\dev\Anchor` |
| DESCRIPTION | Canonical SKILLS_ROOT multi-host adapters + interactive Package A/B onboard with opt-in feedback and B service + anchor.ico desktop + favicon + skill icons |
| Waves | 0â€“6 required; 7 optional author |
| testCommand default | `python -m pytest tests/ -k share_ -q --tb=line` |

---

## Human gate

**Approve this Implementation Plan to start Foreman.**  
Or request edits. Stage-2 engine did not emit a second Shark-converged draft; this document is the lockable handoff artifact.

