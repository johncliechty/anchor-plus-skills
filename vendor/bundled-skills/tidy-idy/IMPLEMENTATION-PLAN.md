# Tidy-Idy GUI polish — Implementation Plan (Foreman-ready)

test-command: node --test

**North Star:** # North Star — Tidy-Idy GUI polish  (LOCKED 2026-07-22)

## Statement
Make the **already-shipped** Tidy-Idy Triage Panel match the **locked Mockup A /
A2 Option 1 product design**: one canonical mockup set, a decision-first panel
(brand icon, primary before→after reorg trees, clean cards), durable operator
docs, and refresh-safe Apply UX — **without changing** Apply safety, finding
identity, Trash, or the thin-Anchor / standalone launch contracts.

## Success criteria (gate-able)
1. **One canonical mockup set.** Only Mockup A (triage) + A2 Option 1
   (before→after reorg) are presented as current design; B and C are archived
   or clearly labelled REJECTED; root-level duplicate HTML either removed or
   reduced to a one-line pointer to `plans/…/design/`.
2. **Live panel matches Mockup A layout intent.** Header uses the brand
   tidy-idy icon (not broom-only); verdict pills + decision-first sections
   remain; reorg tiles show **before→after trees as primary content** (not only
   under “Show evidence”); full paths / evidence stay available but secondary.
3. **Safety unchanged.** Existing panel-apply, GET-audit, token-in-memory,
   envelope honesty, and engine suites stay green; polish does not weaken
   consent-scope, no-clobber, or Apply authz.
4. **Refresh recovery.** F5 / reload either restores a safe remount path or
   clearly tells the human the token was single-use and how to re-open
   (never silently re-enables Apply without auth).
5. **Operator docs current.** SKILL.md describes CLI `tidy-idy <folder>` +
   Anchor button as thin caller + panel + Trash + reorg, matching code.
6. **Tests.** New/updated panel-render tests lock mockup-critical structure
   (icon presence, reorg primary trees, mockup archive pointers); full
   tidy-idy `node --test` suite remains green.

## Non-goals
- New finding classes, auto-apply, cross-project scan.
- Re-architecting Apply / launch / lock.
- Visual redesign beyond Mockup A / A2 Opt 1 (no new design exploration).
- Changing Anchor job_runner beyond what thin-caller already does.

## Risk taxonomy
- **R1 Safety regression** — treat as blocker; gate on existing apply/panel tests.
- **R2 Mockup drift** — only A + A2 Opt1; no resurrecting B/C as options.
- **R3 Token weakening** — refresh path must not put capability token on disk/URL.

## Parent
Amends `<path> (LOCKED 2026-07-20);
does not replace it.

## Pipeline
- Depth: **LITE** (user-confirmed 2026-07-22)
- Engines: `<path> `<path>
- Seats: Anchor model prefs (`coding_family` / `review_family`)


## Success criteria
- One canonical mockup set: only Mockup A + A2 Option 1 current; B/C rejected/archived; root dupes pointers or removed.
- Live panel matches Mockup A: brand icon; reorg before→after primary; decision-first cards.
- Safety unchanged: panel-apply, GET-audit, token-in-memory, suites green; deny-diff on apply/**.
- Refresh recovery without token weaken (REFRESH-TOKEN-CONTRACT + Option stamp).
- SKILL.md operator story matches v2 CLI + thin caller + panel + Trash + reorg.
- Tests: panel-render matrix + full node --test green.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W0 — Read-only inventory, baselines, and stage locks

**Intent:** Establish honest preconditions before any production edit: emission-path inventory, SC2 field-readiness GO/NO-GO, brand readiness, remount-cost inventory with SC4 Option stamp, full REFRESH-TOKEN-CONTRACT state machine, pre-edit full-suite baseline, R1 deny-diff ban freeze, SKILL mismatch list, and engine-gap HALT/escalate rules. Does not claim SC1–SC6 outcomes.

**Deliverables:** Emission-path inventory table (panel body, bootstrap/panel-server, status shells, thin-caller) marked in-scope vs non-goal; SC2 field-readiness binary stamp GO|NO-GO with documented before/after field shapes and tree placement from tiles.mjs/render.mjs; Brand asset readiness note (licensed in-repo mark or named acquisition path); SC4 remount-cost inventory and stamped Option 1 vs Option 2 product choice (never token on disk/URL/localStorage); REFRESH-TOKEN-CONTRACT.md full one-page state machine (states, per emission-path rows, mandatory tests); Timestamped pre-edit full node --test baseline (exit 0, zero skipped safety oracles) recorded under plan journal/baseline; Frozen R1 deny-diff allowlist/deny list + SC3 safety oracle file pin + mockup→assert matrix draft against real section ids; W5 SKILL↔--help↔thin-caller mismatch list; engine-gap journal with HALT/parent-NS escalate only

**Depends on:** —

**done-when:** Field-readiness GO|NO-GO stamped; baseline recorded green; emission table complete; REFRESH-TOKEN-CONTRACT complete with Option stamped (or explicit human-gate deferral only); brand readiness known; deny-diff ban frozen; W5 mismatch list written — no production panel HTML/CSS/asset edits.

- **Given** Production reorg findings are sampled read-only through tiles.mjs and render.mjs, **when** W0 evaluates whether every in-scope reorg path can project non-empty before→after trees from existing fields alone, **then** A binary GO or NO-GO stamp is recorded; NO-GO blocks W2/W3 projection and forbids hollow-tree or journal-deferral exits for SC2
- **Given** Bootstrap/F5 TOKEN embed sites, Cache-Control, re-GET, Close & release, and superseding-run behavior are inventoried, **when** Product copy for refresh recovery is chosen, **then** Option 1 (dead-Apply + re-open) or Option 2 (server-held in-memory remount only) is stamped in REFRESH-TOKEN-CONTRACT.md with per-path rows and mandatory tests; any disk/URL/localStorage token design is HALTed
- **Given** The tidy-idy skill root has not yet received W1+ production edits, **when** Full node --test is run and recorded, **then** Baseline shows exit 0 with zero skipped SC3 safety oracle files so later SC3 non-regression is falsifiable

## Wave 2 — W1 — Mockup hygiene (canonical design truth)

**Intent:** Serve SC1/R2 by locking one CURRENT mockup set (Mockup A triage + A2 Option 1) under plans/2026-07-tidy-idy-gui-polish/design/, archiving or REJECTED-labelling B/C and A2 Option 2, and disposing root duplicate HTML as delete or one-line pointer — with assertable hygiene checks.

**Deliverables:** Canonical CURRENT home: design/tidy-idy-mockup-A-triage.html + design/tidy-idy-mockup-A2-reorg.html (Option 1 only; Option 2 REJECTED); Parent/historical B/C and A2 Opt2 labelled REJECTED or moved to design/archive/; no second CURRENT source; Root tidy-idy-mockup-*.html deleted or reduced to one-line pointer; stub first screenful says REJECTED or POINTER if retained; Repo-wide reference rewrite to plans/2026-07-tidy-idy-gui-polish/design/ before any root delete; design/README + polish NORTH-STAR pointer to single CURRENT path (no new design exploration); SC1 assert/script: no unlabelled Option2/B/C as current; no second CURRENT surface; brand assets self-contained data-URI policy

**Depends on:** W0 — Read-only inventory, baselines, and stage locks

**done-when:** SC1 pointer/REJECTED checks pass and grep is clean of unlabelled B/C/Option2-as-current; only A + A2 Opt1 are CURRENT under the polish design/ path.

- **Given** Root-level and parent mockup HTML may still present B/C or A2 Option 2 as live options, **when** W1 completes hygiene and reference rewrite, **then** Only Mockup A + A2 Option 1 remain CURRENT; B/C and Option 2 are REJECTED/archived; root dupes are pointers or removed
- **Given** A retained root stub may still be bookmarked, **when** A human opens that stub, **then** The first screenful visibly states REJECTED or POINTER — not current design (folder placement alone is insufficient)

## Wave 3 — W2 — Brand mark (self-contained header) + same-wave SC2 brand asserts

**Intent:** Serve SC2 brand criterion (and SC3/SC6 non-regression): replace broom-only header with licensed self-contained tidy-idy mark via projection-only panel render, with same-wave structural asserts and deny-diff clean.

**Deliverables:** engine/panel/assets/ brand mark (compact SVG preferred) + license/source note aligned with Mockup A; Header brand inlined as data-URI from engine/panel/render.mjs; no file://, Anchor-absolute, or external URL; broom not primary mark; Stable data-testid/class hooks for header brand; size/CSP budget measured in tests; test/panel-render.test.mjs brand asserts same-wave (present, self-contained, not broom-only, size budget); Canonical mockups share self-contained brand data-URI policy; Deny-diff clean vs R1 ban; safety oracle subset not weakened

**Depends on:** W1 — Mockup hygiene (canonical design truth)

**done-when:** node --test test/panel-render.test.mjs green on brand asserts; header shows non-broom self-contained brand; deny-diff clean; no apply/identity/trash/lock/token-mint edits.

- **Given** W0 brand readiness is known and W1 canonical mockups exist, **when** Panel HTML is rendered for a triage session, **then** Header brand element is present as data-URI or same-origin skill asset, is not broom-only primary mark, and stays under the size budget assert
- **Given** R1 deny-diff allowlist is frozen, **when** W2 production diff is checked, **then** No denied paths (engine/apply/**, lock-authority, job_runner, identity mint, token-to-disk/URL/localStorage) are touched

## Wave 4 — W3 — Primary reorg trees, safety chips, path hierarchy, CSS polish + same-wave SC2 layout asserts

**Intent:** Serve SC2 layout intent under field-readiness GO: promote per-proposal before→after trees to primary card chrome, keep safety chips always visible, path hierarchy secondary, CSS within Mockup A/A2 Opt1 — same-wave matrix asserts, hollow-tree ban, deny-diff.

**Deliverables:** tiles.mjs/render.mjs: per-proposal before→after tree-diff as primary card content (not under details.evidence) using existing fields only; Primary short relative labels; absolute paths + raw evidence secondary disclosure only; Always-visible hit-count / referenceUnsafe / advisory vs override-only chrome with zero-hit vs non-zero-hit differential; CSS/layout polish for decision-first cards and verdict pills within Mockup A / A2 Opt1 only; Stable hooks for primary tree-diff, reference-scan chip, evidence details, verdict pills, decision sections; Same-wave panel-render matrix asserts with production-shaped non-empty tree fixtures; deny-diff + safety oracles green

**Depends on:** W2 — Brand mark (self-contained header) + same-wave SC2 brand asserts

**done-when:** Field-readiness GO precondition holds; panel-render layout matrix rows green (primary trees outside evidence, pills, decision-first order, secondary evidence, hit differentials); deny-diff clean; safety oracles green without assertion weakening; no set-level bulk reorg chrome.

- **Given** W0 stamped field-readiness GO and production-shaped reorg fixtures have non-empty before/after fields, **when** A reorg proposal tile is rendered, **then** Before→after tree-diff is primary card content and nodes are not descendants of details.evidence; full paths remain secondary only
- **Given** A reorg finding has non-zero reference hits and another has zero hits, **when** Both tiles render without expanding evidence, **then** Hit-count/referenceUnsafe/override-only chrome is visible and control-state differs (non-zero remains non-bulk-approvable / override-gated)
- **Given** Mockup Family Trusts multi-move sample is illustrative only, **when** Live panel reorg chrome is implemented, **then** No set-level bulk multi-move product chrome or new Approve reorg (N) is introduced

## Wave 5 — W4 — Panel-render structural contracts and production-shaped fixtures

**Intent:** Serve SC6 and deepen SC1–SC2 locks: full mockup→assert matrix, production-shaped fixtures (zero-hit and non-zero-hit reorgs with real field shapes), dual-surface shared panel body checks, full suite green with zero skipped safety oracles.

**Deliverables:** test/panel-render.test.mjs covers full mockup→assert matrix (brand, trees, pills, order, secondary evidence, SC1 archive/pointer); Production-shaped fixtures: non-zero-hit override-only reorg + zero-hit approvable move, both with non-empty projectable trees and control-state differentials; Dual-surface structural checks for shared panel body (standalone tidy-idy folder open + thin-caller) where in-scope; Optional critical-subtree snapshots only if selectors brittle — never loosen asserts solely to stay green; Full node --test from skill root; zero skipped SC3 safety oracle files; deny-diff clean

**Depends on:** W3 — Primary reorg trees, safety chips, path hierarchy, CSS polish + same-wave SC2 layout asserts

**done-when:** panel-render + full node --test green; SC1 hygiene asserts green; fixtures are production-shaped (not hollow/synthetic-only); safety oracles zero-skip and unweakened.

- **Given** W0 documented real engine→panel reorg field shapes, **when** Panel-render fixtures are loaded for zero-hit and non-zero-hit reorgs, **then** Both fixtures have non-empty projectable before/after trees and differential chrome asserts pass; synthetic-only HTML cannot be the sole SC2 proof
- **Given** Standalone and thin-caller share the panel body emission path marked in-scope in W0, **when** Structural matrix checks run on both surfaces, **then** Shared mockup-critical structure (icon, primary trees, decision-first order) holds on both; out-of-scope status shells remain unclaimed

## Wave 6 — W5 — Operator docs truth alignment (mandatory gate)

**Intent:** Serve SC5: SKILL.md operator story matches proven CLI tidy-idy folder + Anchor thin caller + panel + Trash + reorg; mandatory SKILL↔--help↔thin-caller truth checklist with no optional escape and no safety-story fiction.

**Deliverables:** SKILL.md run section rewritten to proven behaviors only (CLI, thin caller, panel, Trash, reorg) matching bin/ and launch/; Resolution of every W0 mismatch: required one-line surface fix or explicit not-implemented limitation matching code; Optional short operator/design note for canonical mockup path + A2 Opt1 stage lock; Scripted/checklist truth gate test or assert (SKILL ↔ bin --help ↔ thin-caller dry path) green in-wave; Docs do not claim parent-NS safety changes (no auto-apply, one-Apply-per-run, token rules)

**Depends on:** W4 — Panel-render structural contracts and production-shaped fixtures

**done-when:** SKILL↔--help↔thin-caller truth checklist green; no open mismatches from the W0 list; operator story matches code without silent fiction.

- **Given** W0 listed SKILL vs --help vs thin-caller claim mismatches, **when** W5 truth gate runs, **then** Every mismatch is fixed in surface docs/code or struck as not-implemented matching code — none left optional or fictional
- **Given** Parent NS forbids auto-apply and token weakening, **when** SKILL.md is updated for polish, **then** Docs still describe one-Apply-per-run, consent/token honesty, and thin-caller as already shipped — not as redesigned by polish

## Wave 7 — W6 — Refresh and Token micro-wave (SC4)

**Intent:** Serve SC4/R3 as an isolated safety-gated seam: implement only the W0-stamped Option from REFRESH-TOKEN-CONTRACT.md on every named in-scope emission path — honest dead-Apply or server-held remount, never silent re-enable, never token on disk/URL/localStorage — with contract tests + GET-audit + apply-plane + full suite + deny-diff.

**Deliverables:** Implementation of stamped Option only on contract-listed emission surfaces (banner, disabled Apply, re-open copy per path); Option 1: F5/re-GET yields no usable token; clear single-use banner; Apply controls disabled; re-open from CLI/Anchor — or Option 2 only if stamped: in-memory remount while same panel-server holds capability, expanded GET crawl; Refresh/token tests named in REFRESH-TOKEN-CONTRACT.md; dead-token apply-plane cases; panel-get-audit + token-in-memory remain green unweakened; No trees/icon/docs hygiene scope creep; no apply executor/identity/Trash/lock/job_runner edits; deny-diff clean; Full node --test green; hard HALT if token lands on disk, URL, or localStorage

**Depends on:** W5 — Operator docs truth alignment (mandatory gate)

**done-when:** Contract-named refresh/token tests, panel-get-audit, panel-apply-plane, and full node --test are green; every in-scope emission path shows post-F5 Apply-disabled + re-open instruction per stamped Option; deny-diff clean; no capability token on disk/URL/localStorage.

- **Given** REFRESH-TOKEN-CONTRACT.md is complete and Option 1 or 2 is stamped from W0 remount inventory, **when** Operator reloads (F5) a live triage panel tab, **then** Apply is not silently re-enabled; UX matches the stamped option (honest dead-Apply + re-open copy, or in-memory remount only while process still holds the token)
- **Given** W0 listed multiple in-scope emission paths for Apply chrome, **when** W6 implements refresh recovery, **then** Each named path is implemented and tested for post-F5 Apply-disabled + re-open instruction; out-of-scope shells do not imply live capability
- **Given** R3 forbids durable capability storage, **when** Refresh recovery code and tests are reviewed under deny-diff and GET-audit, **then** Token is never written to disk, URL query, or localStorage; GET-audit and token-in-memory coverage stay green without assertion weakening
