# Zombie Hunter reliability + Doctor/health UX — Implementation Plan (Foreman-ready)

test-command: node --test "<path> Foundry/skills/zombie-hunter/test/*.test.js"

**North Star:** # North Star — Zombie Hunter reliability + Doctor/health UX

**Locked intent (2026-07-21 investigation → Crucible FULL, Grok seats via Anchor prefs):**  
Stop flagging legitimate AI sessions (especially VS Code) as zombies; make Freeze/Kill actually work; make Zombie Hunter and Anchor Doctor terminals fast and multi-engine (Claude / Gemini / Grok); make health banners actionable.

## Statement

Make Anchor’s Zombie Hunter a **trustworthy, fail-safe token-spend sentinel** that only marks a process as a reap candidate when spend and lack of supervision are **both positively established**, never when uncertain — and make Freeze/Kill, investigation terminals, and health-warning → Doctor diagnosis paths **instant, complete, and operator-usable**.

## Success criteria

1. **No false zombies for live interactive work.** Starting one or two Claude (or other engine) sessions in VS Code / Cursor / Windows Terminal / Anchor must **not** produce a “token-spending zombie” banner or red reap tile for those processes. Uncertain supervision or a broken sweep → **abstain** (never red).
2. **Tightened definition (code + skill contract).** Zombie ⇔ known AI engine image **and** confirmed paid-provider spend (not generic Google 443) **and** unsupervised by a robust interactive-host walk (incl. `code`, `code - insiders`, `cursor`, `openconsole`, `grok`, shells, Explorer) **and** not Anchor-owned. Idle / keyword-only matches stay hidden.
3. **Freeze and Kill work.** Freeze uses real process suspend (NtSuspendProcess or equivalent), reports true success/fail; Kill tree-kills and removes the row only on success. Broken SoftFreeze (`Thread.Suspend`) is gone.
4. **Radar loads immediately.** Page shell + last-known counts/tiles from cache paint in &lt;1s; full sweep runs in background; “Why?” / per-row detail is ready without waiting for a 10–20s blocking first paint. Sweep JSON is control-char safe (no silent sweepError).
5. **Investigate terminal: Claude + Gemini + Grok.** Engine toggle includes all three; session start is fast (slim seed); optional deep briefing for a selected candidate so the operator knows how to treat it.
6. **Doctor terminal: same engines, not forever to open.** Page is responsive without blocking on auto-session; engine choice available; optional one-click “diagnose” path with a short seed.
7. **Health banners are clickable.** Dashboard health (and reaper-health) banners open Doctor with the issue context and start a diagnostic terminal that investigates that message — not a static path to a markdown file.

## Non-goals

- Auto-arming the Python reaper kill ladder (`TIER_KILL`) or silent mass kills.
- Replacing the ownership-based Anchor reaper for registered sessions (keep it; align Node classifier with its fail-SAFE spirit).
- Building a new forensics product beyond what’s needed to treat a flagged process.
- Cross-model verification theater while both coding and review families are Grok (`cross_model: false` is honest).

## Risk taxonomy

| Risk | Mitigation |
|------|------------|
| False kill of user’s live session | Abstain on uncertainty; freeze before kill; confirm dialogs; supervised = KEEP |
| Freeze no-ops leave spend running | Replace SoftFreeze; assert suspend via probe |
| Sweep parse failures hide real zombies | JSON-safe enum; surface sweepError; never invent zombies on error |
| Slow terminals block diagnosis | Cache-first UI; slim seeds; start-on-demand |
| Scope creep into full system sentinel rewrite | Stay on definition + freeze/kill + UX paths from investigation |

## Code surfaces (brownfield)

- Skill: `<path> Foundry\skills\zombie-hunter` (Node sentinel: `classify.js`, `spend.js`, `soft-freeze.js`, `server.js`, tests)
- Anchor: `<path> (`anchor_gui.py` zombie/doctor/health banner handlers, `proc_probe.py`, `zombie_hunter.py` / `reaper.py` only if needed for ownership parity)
- Optional skill SKILL.md contract sync for the tightened definition

## Depth / seating

- Crucible depth: **FULL** (user-confirmed)
- Tier: **regular** (not Heavy)
- Seats: **coding_family=grok**, **review_family=grok** → honest `cross_model: false`; transport `grok-cli` / `grok.exe -p`


## Success criteria
- Live VS Code / Cursor / WT / Anchor AI sessions are never red-flagged as token-spending zombies; uncertainty abstains.
- Zombie definition is tightened in code+tests: engine image + confirmed provider spend + unsupervised interactive-host walk + not Anchor-owned; generic Google 443 is not spend.
- Freeze uses real NtSuspendProcess (or equivalent) with honest success/fail; Kill tree-kills only on success; SoftFreeze Thread.Suspend is gone.
- Radar paints shell + cached verdicts immediately; full sweep background; control-char-safe process JSON; per-candidate Why/treat detail without blocking first paint.
- Zombie investigate terminal offers Claude, Gemini (agy), and Grok; start is fast with slim seed; selected-candidate deep brief available.
- Doctor page is responsive; engine picker Claude/Gemini/Grok; session start on demand or one-click diagnose, not multi-minute blank wait.
- Dashboard health (and reaper-health) banners are clickable and open Doctor with that issue seeded into a diagnostic terminal session.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 Dual-write dark and shadow-mode force (G0)

**Intent:** Establish fail-SAFE dark RED on every actionable surface and force classifierMode=shadow before any classifier rewrite can scare operators (OL4/OL5).

**Deliverables:** classifierMode forced to shadow with runtime refuse-armed-without-receipt scaffolding in zombie-hunter server/classify path; Dual-write dark switches on legacy Node radar RED tiles, dashboard zombie banners, and reaper-health zombie scare chrome (observe-only reason fields allowed); Tests: test_dual_write_legacy_and_new_red_dark_until_armed scaffolding, test_red_impossible_until_joint_release skeleton asserting no actionable RED under shadow

**Depends on:** —

**done-when:** All actionable RED surfaces (legacy radar, new classifier output, dashboard zombie banners, reaper-health scare) are non-actionable under forced shadow; Freeze/Kill remain disabled; dual-write dark tests green.

- **Given** classifierMode is shadow and no canaryReceipt exists, **when** a sweep would previously paint a red reap tile or zombie banner, **then** no actionable RED chrome appears on radar, dashboard, or reaper-health; only observe-only reason codes may show
- **Given** an operator or config attempts classifierMode=armed without a version-matched canaryReceipt, **when** the process starts or reloads mode, **then** mode is forced back to shadow and RED stays dark

## Wave 2 — W2 Host-walk geometry and closed engine leg (C1+C3, G1)

**Intent:** Implement the sole normative supervision host-walk and closed engine/support-ancestry legs so zombie definition cannot false-unsupervise interactive work (SC2 prep; never claims SC1).

**Deliverables:** Normative host-walk in classify.js: inputs {pid,ppid,imagePath,createTime}, D=32, system-root set R, stop rules to UNCERTAIN, ancestry-only SUPERVISED/UNSUPERVISED; Versioned host allowlist + shared normalize/exact-match algorithm + near-miss negatives; ban SUPERVISION_WEAK_ROOT; Closed engine allowlist (E1) + support-ancestry E2 with hop cap K=2 and list size ≤16; cmdline/signature corroborate-only; Golden fixtures for ORPHAN_DETACHED_SPENDER geometries (A)/(B)/(C) and supervised ancestor trees for code/cursor/WT/Anchor/shell/explorer; Tests: test_host_walk_supervised_ide_wt_anchor_shell_explorer, test_ambient_conhost_sibling_not_supervision, test_orphan_detached_spender_unsupervised, test_walk_truncation_uncertain, test_allowlist_match_normalize_near_miss, test_no_supervision_weak_root_symbol, test_engine_closed_allowlist, test_cmdline_alone_not_engine, test_engine_negative_wrappers_installers_ides, test_support_ancestry_cap_and_hop_limit, test_support_ancestry_generic_node_parent_not_engine

**Depends on:** W1 Dual-write dark and shadow-mode force (G0)

**done-when:** C1 host-walk and C3 engine/support-cap unit packs are green under forced shadow; uncertain never becomes unsupervised; G1 geometry+engine closed; no armed RED and no live SC1 claim.

- **Given** a candidate engine with VS Code (or Cursor/WT/Anchor/shell/explorer) as an ancestor on the parent chain, **when** the production host-walk runs, **then** supervision is SUPERVISED and the supervision leg fails closed to KEEP (not unsupervised)
- **Given** a candidate whose walk completes to system-root set R with zero allowlist hosts (ORPHAN_DETACHED_SPENDER geometry A or B), **when** the same production walk path runs, **then** supervision is UNSUPERVISED (not UNCERTAIN)
- **Given** missing parent, ppid cycle, createTime inversion, or depth truncation past D=32, **when** the walk evaluates supervision, **then** result is UNCERTAIN and the candidate abstains (never RED unsupervised)

## Wave 3 — W3 Ownership KEEP, reason catalog, and shadow quad skeleton (P1 exit)

**Intent:** Wire Anchor-owned KEEP, closed reason/issue catalogs, and the four-leg quad predicate skeleton under dual-write shadow so SC2 code shape is complete before spend/canary (G1 full exit).

**Deliverables:** Quad predicate skeleton in classify.js + SKILL.md contract seed: engine ∧ paid-spend ∧ unsupervised ∧ not Anchor-owned; any uncertain leg ⇒ abstain; Ownership badge fields; Anchor-registered KEEP; ownership IPC fail-closed stub (error/timeout ⇒ owned/KEEP); Versioned closed classifier reason codes and Doctor issue ID seed catalogs in server payloads; Fail-SAFE matrix: uncertain legs ⇒ no RED any surface under shadow; Tests: ownership KEEP/badge scaffolding, test_reason_issue_catalog_closed_versioned seed, residual dual-write dark asserts with new reason fields

**Depends on:** W2 Host-walk geometry and closed engine leg (C1+C3, G1)

**done-when:** P1/G1 exit: shadow forced, ownership KEEP + reason catalog + quad skeleton integrated; recorded-tree prep allowed; SC1 not claimed; Freeze/Kill still forbidden.

- **Given** a process that is Anchor-registered or ownership IPC times out, **when** classification runs, **then** candidate is KEEP / not RED and ownership reason codes surface (OWNERSHIP_IPC_FAIL_CLOSED on IPC fail)
- **Given** any leg returns UNCERTAIN, **when** the quad predicate evaluates, **then** verdict abstains with structured reason codes and no actionable RED on any dual-write surface

## Wave 4 — W4 Spend atlas fail-closed and joint quad gate (G2+G3)

**Intent:** Make paid-provider spend positive only on process-owned atlas-matched connections (never generic Google 443) and prove the joint four-leg fail-closed gate under dual-run shadow (SC2 joint).

**Deliverables:** spend.js provider atlas: process-owned sockets + SNI/hostname allowlist positives; port-443-alone negative; SPEND_ATLAS_STALE ⇒ no invented spend; Golden spend ± fixtures and dual-run shadow fields on classifier output; Joint gate: test_zombie_quad_gate_fail_closed integrating engine+spend+supervision+ownership; Atlas/allowlist version hash hooks for later re-shadow (test_atlas_bump_forces_reshadow scaffolding); test_unsupervised_spender_true_positive bound to production orphan geometry (A) or (B) on the same walk code path (OL1 positive-control prep)

**Depends on:** W3 Ownership KEEP, reason catalog, and shadow quad skeleton (P1 exit)

**done-when:** G2 and G3 green: spend atlas positives/negatives pass, joint quad fail-closed, dual-run shadow fields present; still no armed RED.

- **Given** a process with only generic Google 443 or unknown remote hosts, **when** spend evaluation runs, **then** spend leg is not positive (SPEND_NEGATIVE or SPEND_UNCERTAIN) and cannot alone produce RED
- **Given** engine-positive + atlas-matched paid spend + C1 unsupervised orphan + not Anchor-owned under shadow dual-run, **when** test_zombie_quad_gate_fail_closed and unsupervised spender TP run, **then** would-be-actionable-RED is emitted on the dual-run shadow path for the orphan only; interactive supervised shapes abstain/KEEP

## Wave 5 — W5 SC1 canary pack, residual attestation, and arm receipt (G4–G6)

**Intent:** Prove zero interactive false RED on recorded host trees plus live real-host canary (with OL1 orphan positive control), then write version-matched canaryReceipt so arming becomes eligible without enabling Freeze/Kill yet (SC1 full exit).

**Deliverables:** Recorded process-tree fixtures for VS Code, Cursor, Windows Terminal, Anchor (≥1 each) → test_sc1_recorded_host_trees_zero_red; Live canary harness: ≥1 real interactive engine under a real host (VS Code preferred) → test_sc1_interactive_zero_red on operator-visible banner+tile surfaces; OL1 positive control in sc1_canary_gate: dual-run would-be-actionable-RED for named ORPHAN_DETACHED_SPENDER on production walk path; Residual hosts: live zero-RED matrix or sc1_host_attestation.json (host class, reason, owner, expiry) → test_sc1_host_attestation_or_live_matrix; canaryReceipt writer matching {classifierVersion, hostAllowlistHash, engineAtlasHash, spendAtlasHash} + G5 evidence path; tests: test_runtime_arm_requires_version_matched_canary_receipt, test_shadow_to_armed_requires_sc1_canary, test_atlas_bump_forces_reshadow; OL3 path: operator-lab evidence bundle checklist and/or per-host-class arm eligibility metadata (no global arm required for later proven-class Freeze)

**Depends on:** W4 Spend atlas fail-closed and joint quad gate (G2+G3)

**done-when:** sc1_canary_gate green (recorded zero-RED ∧ live interactive zero-RED ∧ orphan positive control ∧ residual attestation or live matrix); canaryReceipt version-matched; SC1 owned; classifier arm-eligible only after operator arm — Freeze/Kill still not production-enabled.

- **Given** recorded trees for VS Code, Cursor, WT, and Anchor with live-engine-shaped children, **when** classifier dual-run evaluates under production code, **then** 0 RED tiles and 0 zombie banners for those interactive shapes
- **Given** a real interactive engine under a real listed host (VS Code preferred) on the operator machine, **when** live canary exercises banner and tile surfaces, **then** false RED count is 0 and residual unproven hosts are attested or live-proven before receipt write
- **Given** sc1_canary_gate green and hashes match current classifier/atlases/allowlist, **when** canaryReceipt is written and operator arms, **then** runtime accepts armed eligibility; missing/stale/mismatched receipt forces shadow + dark RED

## Wave 6 — W6 Real Freeze and identity-safe Kill sole boundary (SC3/G7)

**Intent:** Replace broken SoftFreeze with NtSuspendProcess-based Freeze and tree-Kill behind one server boundary, with honest success/fail and ownership fail-closed (SC3; OL2 spend postcondition reported, not sole hard HALT).

**Deliverables:** Delete SoftFreeze/Thread.Suspend process-freeze path; introduce freeze.js (or sole documented module) as only Freeze/Kill service boundary in server.js; Freeze: identity re-probe (pid+createTime+image) + NtSuspendProcess (or equivalent) + spend postcondition reported as STOPPED/CONTINUES/UNCERTAIN (OL2); honest success/fail chrome; freezeCapability probe under non-elevated operator envelope; Kill-without-freeze disabled until capability proven (OL3 per-host-class arm allowed for proven classes); Kill: authz + server-validated confirm every time; tree-kill; death verify; row remove only on success; Ownership IPC fail-closed + mid-flight registration race abort; GUI must call sole boundary (no direct proc_probe kill); Tests: test_no_thread_suspend_softfreeze, test_sole_freeze_kill_service_boundary, test_freeze_identity_reprobe_before_suspend, test_freeze_spend_postcondition (reported class), test_freeze_capability_operator_envelope, test_kill_without_freeze_disabled_until_capability, test_kill_authz_server_validated_confirm, test_kill_tree_identity, test_ownership_ipc_fail_closed, test_ownership_race_abort_destructive, test_anchor_owned_keep_no_node_kill

**Depends on:** W5 SC1 canary pack, residual attestation, and arm receipt (G4–G6)

**done-when:** SoftFreeze gone; Freeze succeeds only with identity re-probe + NtSuspend success and honest chrome (spend postcondition reported); Kill tree-kills and removes rows only on verified death; sole boundary + capability envelope green (G7); kill-without-freeze remains disabled until freezeCapability proven.

- **Given** a non-owned candidate with stable identity under freezeCapability-proven host class and armed/allowed mode, **when** Freeze is invoked via the sole server boundary, **then** identity re-probe passes, NtSuspendProcess is used (not Thread.Suspend), and UI reports true success or fail including spend postcondition class STOPPED/CONTINUES/UNCERTAIN
- **Given** freezeCapability is false or unproven on the host class, **when** Kill-without-freeze is requested, **then** request is refused; only freeze-then-kill path may proceed when capability is later proven
- **Given** a kill request without server-validated confirm or with ownership IPC failure / mid-window registration, **when** Kill is attempted, **then** action is refused or aborted; Anchor-owned sessions stay KEEP and are never Node-killed

## Wave 7 — W7 Cache-first radar, JSON-safe sweep, and Why payload (SC4)

**Intent:** Make radar shell paint in under 1s from cache (never actionable stale RED), run full sweep in background, and keep process JSON control-char safe (SC4/C5).

**Deliverables:** Cold path: shell+skeleton+no-cache ≤1000 ms; warm path: shell+last-known ≤1000 ms with staleness; full sweep background-only; No actionable cached RED (stale/non-actionable or suppressed); never freeze/kill from cache-only identity; JSON-safe enum for cmdline/image control chars; parse fail ⇒ sweepError + abstain, never invent RED; Server fields: sweepError, cacheAge, freezeCapability, atlasHealth, reason codes, classifierMode, canaryReceipt status; Why min payload from cache: reason codes, last verdict, cacheAge, freezeCapability if known; UI copy: Uncertain ≠ red; Freeze before Kill; ownership badge; shadow vs armed; Tests: test_cache_no_actionable_red, test_radar_cold_paint_under_1s, test_radar_warm_paint_under_1s, test_sweep_json_control_char_safe, test_why_min_payload_from_cache, test_cross_surface_no_red_on_abstain

**Depends on:** W6 Real Freeze and identity-safe Kill sole boundary (SC3/G7)

**done-when:** Cold and warm radar paint ≤1s; no actionable cached RED; control-char-safe sweep with sweepError abstain; Why min payload available without blocking first paint.

- **Given** a cold radar open with empty cache, **when** the page loads, **then** shell+skeleton paints within 1000 ms and full sweep continues in background without blocking first paint
- **Given** warm cache contains a previous RED-shaped verdict while classifier is shadow or sweepError occurs, **when** radar paints from cache, **then** no actionable RED is shown; sweepError or shadow forces abstain/non-actionable chrome
- **Given** process cmdline or image contains control characters, **when** sweep JSON is serialized and parsed, **then** payload is control-char safe or surfaces sweepError; zombies are never invented on parse failure

## Wave 8 — W8 Multi-engine Investigate and Doctor shared start (SC5+SC6)

**Intent:** Ship shell-first Investigate and Doctor terminals with Claude, Gemini(agy), and Grok, slim seeds, and async session start so diagnosis is not multi-minute blank wait (SC5/SC6/C7).

**Deliverables:** Shared session-start helper in Anchor GUI (anchor_gui.py): shell + engine picker + seed before session; session async/cancelable; failure non-blocking; Engine toggle: Claude, Gemini (agy), Grok (grok-cli / grok.exe -p); dead toggle forbidden; unhealthy engine disabled with health; Investigate slim seed: pid + class + top reason codes + freeze/kill status; optional deep-brief path for selected candidate; Doctor: shell first, no blocking auto-session; optional one-click diagnose with short seed; Numeric gates: shell ≤1s; first prompt ≤15s or disable engine; Tests: test_investigate_three_engines_slim_start, test_doctor_shell_before_session, test_p6_requires_p5_start_plumbing plumbing green

**Depends on:** W7 Cache-first radar, JSON-safe sweep, and Why payload (SC4)

**done-when:** Investigate and Doctor shells paint before session start with Claude/Gemini/Grok pickers; slim start proves three engines; first prompt ≤15s or engine disabled; no multi-minute blank wait.

- **Given** operator opens Investigate on a candidate with Claude, Gemini, and Grok available, **when** each engine slim start is selected, **then** shell paints first, session starts async with slim seed, and first prompt arrives within 15s or that engine is disabled with health
- **Given** operator opens Doctor without clicking diagnose, **when** the page loads, **then** shell and engine picker are usable immediately without blocking on an auto-started multi-minute session

## Wave 9 — W9 Clickable health and reaper-health banners to Doctor (SC7)

**Intent:** Make dashboard health and reaper-health banners open Doctor with 1:1 issue seed and async diagnose start instead of a static markdown path (SC7).

**Deliverables:** Banner click handlers open Doctor with seed fields 1:1: issueId, exact message, component, lastError, suggestedChecks; Async diagnose session start attempted with that payload when engine enabled; failure surfaces health and leaves UI usable; Closed versioned Doctor issue catalog seed reused/aligned with classifier reason codes where applicable; Not a markdown file path; Tests: test_health_banner_doctor_seed (1:1 fields + async start attempted), cross-surface fail-SAFE with dual-write rule

**Depends on:** W8 Multi-engine Investigate and Doctor shared start (SC5+SC6)

**done-when:** Health and reaper-health banners are clickable, seed Doctor 1:1 with banner payload, and attempt async diagnose start; UI stays usable on start failure.

- **Given** a dashboard health or reaper-health banner with a concrete issue payload, **when** the operator clicks the banner, **then** Doctor opens with issueId, message, component, lastError, and suggestedChecks matching the banner 1:1 (not a markdown path)
- **Given** an enabled engine on Doctor after banner navigation, **when** diagnose path runs, **then** async session start is attempted with the seeded payload; start failure shows health and does not freeze the page

## Wave 10 — W10 SKILL contract sync, ownership UI, and G0–G7 release suite (P7)

**Intent:** Lock SKILL.md↔server reason contracts, ownership UI parity, and the named E2E gate suite so release cannot drift from SC1–SC7 (P7).

**Operator runbook (checked in):** `OPERATOR-RUNBOOK.md` — freeze-then-kill, red vs abstain, Doctor vs Investigate, shadow vs armed, arm/disarm/re-shadow.

**Deliverables:** SKILL.md ↔ classify.js/server reason-code field map CI contract; drift HALT-worthy (test_skill_server_reason_code_contract); Ownership badge UI contract on radar; Freeze/Kill hidden when owned (test_ownership_badge_ui_contract); Cross-surface dual-write final asserts; abstain-rate / unsupervised-spend TP health fields; Operator runbook source checked into plan/skill docs: freeze-then-kill, red vs abstain, Doctor vs Investigate, shadow vs armed, arm/disarm/re-shadow; E2E release suite wiring all gates G0–G7 named tests including sc1_canary_gate and human SC1 sign-off checklist bound to same G5 evidence paths + receipt hash

**Depends on:** W9 Clickable health and reaper-health banners to Doctor (SC7)

**done-when:** SKILL/server reason contract CI green, ownership UI contract green, and the full G0–G7 named release suite passes with SC1 sign-off bound to canary evidence + receipt hash.

- **Given** SKILL.md reason/field map and server catalog diverge, **when** contract CI runs, **then** the suite fails closed (HALT-worthy) rather than silently shipping drift
- **Given** all prior wave gates are green and canaryReceipt hashes match, **when** the E2E G0–G7 release suite runs, **then** every named gate pack passes and human SC1 sign-off checklist references the same G5 pack paths and receipt hash
