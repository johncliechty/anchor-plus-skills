# Changelog

## v1.2.7 — the cockpit gets quiet, the plan gets tidy, and work announces itself (2026-08-27)

Three days of the author using the deliverables surface and the steward
cockpit for real work, then three adversarial review rounds (one cross-family)
over every diff. Everything below was verified on his screen before release.

### The conversation is readable again
- **One activity line, not a line per tool call.** A long steward turn used to
  bury its own prose under dozens of dim tool lines. Now a single folding line
  counts the steps, names the current one, and ticks its elapsed time — so it
  doubles as the answer to "is it still running." Click it for the full list.
- **The state line stops lying.** It said "waiting on you" while commissioned
  background work ran. The engine now carries the attention flag, and the
  steward's contract orders that flag stamped the moment background work
  starts.

### The plan reads at a glance
Roadmap steps no longer auto-expand and no longer show filler. Each step's
deliverables appear as one blue sentence; click it for the detail, click the
link for the report. Register rows carry an optional Step column so a work
product sits under the step that produced it.

### The status pane is a status pane
Deliverables on top (folded, with the newest item named in the header),
**the status in the middle as the only section that grows**, files at the
bottom. Both side sections fold on a click and remember the choice.

### Work announces itself
- **Soft start**: opening a parked effort wakes the steward, so the dialog
  opens with where things stand and any question still waiting.
- **Project setup**: creating a project lands it immediately and its tile says
  "Setting up the project — reading what is here…" while the honest first read
  runs. A deferred read says so too, and points at the manual button.
- **Decision shape, enforced**: a decision put to the author with no
  recommendation is sent back once, visibly. The law was written all along —
  which is exactly why it drifted. A rule nothing checks is a rule that decays.

### Fixed
- Files produced were persisted but reloaded as an empty list, so every
  restart blanked the pane.
- Delivery receipts raised NameError into a swallowing catch for a full
  release: `channel_verified` never flipped while the call reported success.
- Registering a project fired an unannounced whole-tree read per click, with a
  per-project concurrency guard — so repeat clicks stacked model swarms until
  the machine stopped answering. One automatic read at a time now, machine-
  wide, off the request path, with an exact-duplicate guard.
- Deliverable links opened blank pages (they bypassed the page's auth
  plumbing); text artifacts now render in the report viewer, PDFs inline.

### Still open, by name
Foreman checkpoint supervision and Jumper's batched funnel arm on their next
runs. The steward M-batch (High Seat re-route, chamber cut) awaits the
author's acceptance pass. 21 project-window/steward tests remain red from the
cockpit cutover reconciliation — unchanged by this release, named here rather
than quietly carried.

## v1.2.6 — the deliverables surface actually opens (2026-08-26)

Hotfix on v1.2.5, driven by the author's first real day using the
deliverables surface: every repair below is verified on a live screen, and
the defect class that caused it — tests pinning one layer below the one the
page hits — now has dispatch-layer tests standing guard.

### Fixed
- **Register routing**: the verb "deliverables" was BOTH a project-level and
  an effort-level route; project routing won, so the register tile read the
  project root (always empty) and the legacy session-files tab was shadowed.
  The register is effort-level; the files view is its own verb.
- **Blank click-throughs**: register links were raw navigations that skipped
  the page's auth plumbing (no project id, no token → an empty page). Links
  are now built fully authed; text artifacts open in the rendered report
  viewer, PDFs inline, other binaries stream through the contained route.
- **Stale guard test**: `test_reaper_single_source` had been red since the
  July ship-prep refactor — it counted a call the refactor legitimately
  removed (the zombie-terminal brief now classifies straight through the
  shared snapshot, the stricter form of the same rule). The rule it guards
  was never broken; the counter is corrected and explained in place.
- **Honest state line**: the header said "awake — waiting on you" while a
  commissioned background run worked. The engine state now carries the
  attention flag and the header says so; the steward's standing brief orders
  the flag stamped the moment background work starts.

### Added
- **Soft start**: opening a parked effort page wakes the steward — the
  deterministic pickup (where we left off, the pending question) lands on
  first poll, then the model's short orientation. Guards: stored-session
  only, never workbench terminals, never a fresh effort, 60s cooldown.
- **Project-wide deliverables**: the cockpit's main list is the union of
  every effort's curated register — reports a human opens, never raw
  session files.
- **Per-step embedding**: register rows carry an optional Step column and
  the plan paints each work product under the roadmap step that produced it.

### Still open, by name
- Unchanged from v1.2.5: Foreman checkpoint supervision and Jumper's batched
  funnel arm on their next runs; steward M-batch awaits the author's
  acceptance pass; the true-VM install check remains staged.

## v1.2.5 — the steward moves in, and the work shows its receipts (2026-08-25)

The steward cockpit becomes the default project surface, deliverables get a
single register the whole system answers from, and the elegance-review
ratifications land across every vendored skill — then the whole batch is
hardened by three adversarial review passes over its own diffs (11 confirmed
defects, all fixed before this release).

### Steward cockpit cutover + deliverables surface
- The cockpit (`steward_cockpit/`) is now the default `/project/` page; the
  legacy chamber remains behind `?classic=1`. `BUILD_ID` counts the cockpit
  sources, so an open page self-reloads when they change.
- **One deliverables register**: an effort's `DELIVERABLES.md` drives a pinned
  package tile atop the status pane, goal-bar links, and the steward's own
  answer to "where is the thing you produced." Files serve through a
  realpath-contained route (escapes 404; html/svg served inert).
- Delivery receipts: status acks flow to `.ecgberht/delivery.json`
  (locked read-modify-write, coalesced acks) and flip `channel_verified` on
  first ack — a render leg the engine can prove, not assume.
- The pre-restart drain now parks the cockpit's own engines via the service
  (`POST /api/steward/drain-all`) and names each failure class — never a
  vacuous empty report.

### The elegance ratifications land in the vendored skills
- **Crucible** announces its band (auto-band with a loud FULL default) and
  writes the triage lock record; stage handoffs fail closed without it.
- **Foreman** gets a 45-minute call-timeout floor, delta-scan transparency,
  and a sibling-repo cleanliness preflight that survives paths with spaces.
- **Gandalf** never halts mid-run on budget: pre-flight cost consent, then
  floor-and-stamp (critical outranks major); refuter kills leave a kill_log.
- **Jumper** pings its cross-family gate through the named driver (no
  failover masking a dead channel) and stamps salvage on zero-survivor runs.
- **Legal-beagle / financial-analyst** emit deterministic gate receipts
  (hash + checks + timestamp) required in the deliverable footer; the
  financial chain is thin (one JSON seam, tie-out fail-closed).
- **Literature-review** pre-flights the seed before seat binding and falls
  back S2→OpenAlex with the fallback recorded.
- **researchPrime** mechanizes its field laws (halt-record on violation).
- Every SKILL.md carries its **North Star (LOCKED)** header — all nine
  ratified 2026-08-25.

### Still open, by name
- Foreman checkpoint supervision (Move 6) arms on its next real build run;
  Jumper's batched thinning funnel on its next run — both trigger-gated.
- Steward M-batch awaits the author's acceptance pass: High Seat re-route,
  chamber cut, cockpit-commissioned sentinel coverage.
- 4 pre-existing `test_cockpit_paradigm2` failures ride the cutover
  reconciliation; the true-VM install check (Part C) remains staged, with the
  clean-profile run as the current approximation.

## v1.2.4 — the elegance cycle: every skill sleeps, the engines stop lying about dead time (2026-08-15)

A portfolio-wide sleep cycle over all 14 bundled skills, commissioned as
"make these elegant, no rabbit holes, robust enough that scientists at any
frontier lab would want them."

### ELEGANCE.md Part II ships — what elegance IS, and the Rabbit-Catcher
A researched, adversarially-vetted operational definition of elegance
(three evidence sweeps, 38 rung-marked ledger items; four live cross-family
governed rounds, new-blocker trajectory 3→1→1→0, stopped on the first
genuinely-dry round per the Elegance Law's own rule 5). With it: the
**Rabbit-Catcher** — a bounded per-element test battery (RC-1..7 + the RC-G
guard clause) the steering seat runs at plan approval and on new mid-run
elements. Needs must be INDEPENDENT of their proposer (no self-authored
justification records); malleability work is never cut as "unused
capability"; guards are judged by hazards, not recorded failures; verdicts
are KEEP / HOLD-with-expiry / CUT-logged. Every SKILL.md carries the
definition inline; `ELEGANCE.md` ships at the bundle root (emitted like
AGENTS.md — pointed-at rule files must ship).

### The engines stop blessing dead agents
- **Foreman**: an agent whose transport reports `ok:false` is now a loud
  `[taxonomy:agent-died]` HALT — never "execute complete". The recorded
  failure: a 20-minute, 60-tool-call execute SIGKILLed at the per-call cap
  with ZERO bytes written was blessed and advanced to a gate that would have
  gone GREEN on the previous wave's tree. `go.ps1` now exposes
  `-CallTimeoutMin` (the default 20 killed a healthy 43-minute wave).
- **Crucible**: the first genuinely-dry held round now goes to the USER (the
  convergence authority) instead of paying a second identical round — the
  engine now obeys the Elegance rule its own SKILL.md carries.
- **Steward**: `launch_failure` joins the closed run-outcome set — a session
  dead before its greeting, with nothing written, raises "fix the engine
  first", never "the session ended" (a blind relaunch bought the same death
  three times, ~80 minutes, zero product). Plus the READ-BEFORE-PLAN law:
  the steward opens its own campaign record before planning anything.
- **researchPrime**: the plan-gate CLI's TTY-only trap and the agy field laws
  (label-form models, fenced-JSON replies, absolute paths, `'yes'/'no'` enum)
  are documented where the operator reads them.

### The sleep cycle's own rails repaired
LESSONS.md created for 4 skills that had none; jumper's 24 journal entries get
their first promotions; gandalf's post-08-04 backlog promoted; NORTH-STAR.md
promoted from in-code charters for legal-beagle and financial-analyst (marked
as promotions — nothing newly authored); run-capture rails restored ×4;
journal ids now law: max(NNNN)+1 over the whole directory. Standing rules
promoted into foreman/crucible SKILL.md from ten journals. financial-analyst's
SKILL.md mojibake (24 sequences) repaired.

### Named cuts (per the law: shown, not silent)
The full stall-detection ladder (the enabling idle-watchdog exists but no
driver pumps heartbeats yet — turning it on would kill healthy long calls;
deferred with the prerequisite named), cross-repo dirty-sibling checks, and
the steward wall-clock ledger.

## v1.2.3 — the skills arrive with their run contract (2026-08-15)

The v1.2 line built cleanly and was never published. This release fixes what
the built bundle was quietly getting wrong, so the skills behave on a
collaborator's machine the way they behave on the author's.

### The bundle shipped its skills without their governance
Every vendored `SKILL.md` defers its run contract — the **LOCKED 10-minute
status-table format**, the Heavy-vs-regular tiers, the invocation discipline —
to `AGENTS.md`. Neither the author's user-global copy nor the Skill Foundry
copy is in the bundle. Worse, the no-personal-data scan rewrote the author's
absolute Skill Foundry path into a placeholder token in **ten staged files**:
the scrub protected the author's privacy and, in doing so, converted a
diagnosable absolute path into a string that resolves nowhere. The artifact
linked; the symbol was missing. Collaborators got skills whose most visible
behavior — reporting progress every ten minutes in a fixed format — was
undefined.

(This paragraph cannot quote the broken string itself: the new gate below
correctly refuses to ship any file containing it, and it caught this changelog
on the first build after it was written.)

- **`AGENTS.md` now ships**, emitted into the staged root at build time (source
  under `planning/`, which the manifest excludes — deliberately *not* at the
  author repo root, where an `AGENTS.md` would hijack the
  AGENTS.md-is-canonical convention). It carries the locked status table
  verbatim, the launch pattern that makes the cadence actually fire
  (background launch + armed wake-up), the tier definitions, and an honest
  note that seat assignment resolves from Anchor's registry — so **Package A**
  installs, which have no registry, are told to expect `cross_model:false`
  rather than silently getting single-family verification.
- **The 12 `SKILL.md` files were repointed** at the bundled copy (trio
  `eb7c34e`, Skill Foundry `12d643b`) with no absolute path left for the scrub
  to mangle.
- **`AUTONOMOUS-MODE.md` ships** — how to run the skills unattended, what each
  capability is for, what stays denied, and a plain no-warranty statement.
  It documents editing the collaborator's **own** user-level settings: a
  settings file arriving inside a cloned repo is restricted from granting
  itself permissions, and that restriction is correct.
- **`share_agent_rules.py` ships** — the one-command opt-in that makes the
  above real: `python share_agent_rules.py install --settings` writes the
  agent-level rules block into the collaborator's own `~/.claude/CLAUDE.md`
  and merges the autonomy profile into their own `settings.json` — fill-only
  (a value the user already set always wins), first-backup-wins
  (`settings.json.anchor-orig`), fully reversible (`remove`, `status`).
  Package A carries `AGENTS.md`/`AUTONOMOUS-MODE.md` too — without them the
  skills-only install would have re-created the dangling-pointer defect.

### New fail-closed gate: scrub residue
The PII scan rewrites author paths to `<path>`; where the reference had a file
target, that rewrite leaves a pointer to nothing — which is exactly how the
above shipped invisibly. The new gate audits the PII scan's own output.
Narrow by design: a general "does every referenced doc exist" check was
refuted cross-family (staged prose legitimately names unstaged files like
`DASHBOARD.md` and `MASTER-PLAN.md`, so its false-positive rate would get it
switched off). Measured against the real v1.2.2 tree: **10 hits, 1 distinct
pattern, 0 false positives**, and it fires when the defect is planted back.

### Two stamps that disagreed
- **`VERSION` said 1.2.2 while `pyproject.toml` said 1.1.3.** The G3 sandbox
  gate could not catch it because it hard-coded the literal `"1.1.3"` instead
  of asserting the two stamps *agree* — so it would have failed on every line
  after 1.1.3 for a reason unrelated to product health. De-pinned to the real
  invariant. Both stamps now read 1.2.3.
- **`doctor.py` called a correctly-built package broken.** Its
  `OPTIONAL_ABSENT` was a hand-maintained duplicate of the builder's
  `_OPTIONAL_FIRST_PARTY`, frozen at `{update_transaction, tools}`; the builder
  grew the steward-chamber declarations and doctor never did, so a good install
  printed *"Module 'chamber_mockup_diff' is MISSING — this install is
  INCOMPLETE"*. Doctor is the **first** thing the consumer `CLAUDE.md` tells a
  collaborator to run, so the one free deterministic check was telling every
  new user their install was broken. Same root cause as the v1.1.x
  two-builders incident: one list must win, and it is the one the fail-closed
  gate enforces. Found only because the acceptance suites had never been run
  against the v1.2 line.

### Evidence
Build from a clean worktree of committed HEAD: **B 1052 files / A 602, all
gates clean**. Stranger sandbox **10/10**. Pull dry run against a simulated
collaborator install **7/7** (1056 files). Distro/doctor/share suites **111
passed**. 13 new gates in `tests/test_share_v123.py`.

### The Ecgberht steward now ships — engine only
Anchor had been shipping the steward's **host contracts** (the `chamber_*`
modules) while the skill itself stayed on the author machine, so collaborators
got steward-shaped Anchor surface with nothing behind it. The bundle now
carries **14 skills**, not 13.

What does *not* ship is the point. The steward is a campaign-memory skill and
most of its ~970 files are the author's own portfolio record. The generic
denylist already dropped 487 (`planning` / `test` / `journal` / `.foreman`);
the remainder carry names too generic to deny globally — a future skill may
legitimately ship a `research/` or `drafts/` directory as product — so
`_is_denied` / `_apply_denylist` now take an optional skill name and apply
**scoped** denials. `ECGBERHT.md` at the steward's root is the author's
portfolio memory and is denied by name; per-project copies mint from
`templates/`, which ships. The steward's own `.ecgberht/attention.json` is
denied too: it is live author state, and a stranger's fresh install must not
open already showing someone else's pending "needs you".

Result: **257 files, not 970.** Verified by leak probe — no private project
names, no campaign record, no inherited runtime state.

Safe because cross-family review confirmed the engine reads none of it at
runtime: `rank.mjs` scores Strip projections only, `loadDispatchTable()` falls
back to `BUILTIN_CELLS`, `prior-art/` and `ideation/` have no engine or bin
load path, and `listJournalEntries()` is an optional per-project scan returning
`present:false`.

The sandbox harness gained the steward's source env — without it the suite
silently exercised a 13-skill bundle while the builder shipped 14, an
acceptance suite not testing what ships.

### Still open — carried forward honestly
- The ease count and tile retirement remain open by name from v1.2.1.
- The Gandalf read that drove this release ran its **synthesis seat on Opus 5,
  not Fable** (a tier-break against that skill's declared TOP tier). Its
  refuter seat was genuinely cross-family (Gemini 3.1 Pro High), and every
  material conclusion here was subsequently confirmed by execution — the
  builds, the suites, and the leak probe — rather than resting on model
  judgment.

## v1.2.2 — E1 engine-enforced (2026-08-13)

The steward can no longer walk away from a question you asked it.

v1.2.1 shipped with E1 as a stated criterion and no implementation — the
CHANGELOG said so plainly. This closes it. Two waves, both GREEN on the
orchestrator gate, both adversarially reviewed by **Grok** with zero agreed
blockers (the chamber build reviewed single-family; this is the first real
cross-family review on this project).

### What E1 now means in code
- **`chamber_e1_bound.py`** — the deterministic, model-free question parser.
  A direct question is a terminal-'?' sentence, an explicit `asks[]` entry,
  or one of five committed imperative prefixes with no question mark:
  `confirm …` · `tell me …` · `let me know …` · `did you …` ·
  `can/could/would/will you …` (leading fillers stripped first). Each
  question gets a deterministic id, discharged only by a typed
  answer-reference.
- **`chamber/E1-BOUND-RATIFICATION.md`** — bound v1, **ratified by John
  2026-08-13**. The bound is a line the user drew, not one the model
  inferred; E1's own "zero model involvement" clause requires that. Five
  KNOWN-MISS forms (garble that destroys the anchor verb, prosody-only
  questions, mid-sentence third-person asks, indirect "I was wondering…")
  are signed as agreed out-of-bound losses — named, never silent. Widening
  the bound requires a v2 signature; it can never widen itself.
- **`chamber_e1_hook.py`** + the Ecgberht engine leg
  (`enforceTurnCompletion`, `enforce_bridge_result`) — the turn-completion
  hook on the W2-proven converse seam. A turn carrying an unanswered
  ratified question id is structurally blocked with a named finding.
- **Fails CLOSED, always.** An absent, altered, version-mismatched or
  unsigned bound yields `E1-BOUND-UNRATIFIED` / `E1-F7-ARTIFACT-MISSING` and
  refuses to enforce. An unenforceable bound never degrades to permissive.
- **The refusal has a drawn face** (`AG-BLOCKED-TURN`), so a block never
  reads as a hung steward — the V5 law, "the cure must not look like the
  disease." Batched with the runcard transcript link into one signature;
  C9 re-pinned `4a7f7953…` → `fe77d058…`.

The W12 audit's E1 row moves **instrument-missing → reverified**. Test
counts grew rather than merely holding: engine 1135 → 1146, pytest
3173 → 3197.

### Still open — carried forward honestly
- **The ease count remains UNAVAILABLE by name.** Same missing-wave origin
  as E1, but a separate criterion (C8); no classifier of record exists, so
  the 5→0 re-score cannot run and `chamber/EASE-CLOSE-REPORT.md` refuses to
  invent one.
- **Tile retirement has still not executed.** The gate stays UNSIGNED and
  `dismiss-finished-tile` stays deferred; no tile code deleted. The
  transcript-link row is now resolved `equivalent`.
- **A Foreman defect found by this build.** An execute agent SIGKILLed at
  the per-call timeout, having written nothing, was logged
  `execute complete` and advanced to a gate that would have returned GREEN
  on an empty wave. The post-W12 guard only catches agents that die at
  launch (0 tools, sub-2s); the predicate that matters is `ok:false`. Not
  fixed here — Foreman is a separate tool.

## v1.2.1 — the steward chamber (2026-08-12)

The v1.2 line: a rebuild of how the steward talks to you inside a project.
Twelve waves, all GREEN on the orchestrator gate (1135/1135), merged at
`3dbc21c`. Planned by Crucible, built by Foreman, from the 4-stage steward
assessment in `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08`.

Numbering note: `v1.2.0` was already spent on an earlier line-close commit
(`120ddd0`, 2026-08-04), so the chamber release takes 1.2.1. A published
version number is never reused.

### The three defects this closes
- **D1 — status was fragmented across four surfaces.** There is now ONE flow
  surface: the M1 rail, with a STATUS overlay carrying the latest status table
  and the remaining steps with median ETAs.
- **D2 — talk turns took 60-160s.** The chamber renders DETERMINISTIC-FIRST:
  it opens in under 2 seconds from projections, and the model is called only
  when you actually speak. Enforced by a `<2s` CI budget at >=2x-real fixture
  sizes plus a zero-model-call network/process trace.
- **D3 — no declared pipeline.** Typed edges, a versioned manifest schema with
  a lint, artifact contracts, and a declared deliverable per effort.

### Enforcement that landed (engine-enforced, re-verified at its seam)
- **E2** — worktree sweep before re-commissioning, with the enqueue guard.
- **E3** — resurrection-regression diffs against the correction ledger.
- **E5** — serialized gate queue, head-only.
- **E6** — preference preload.
- **E7** — mid-flight re-brief per audited mode, no relaunch.
- **E9** — layered verification; collapsed-stage manifest-lint refusal.
- **F3** deliverable-run execution bounds (shell:false, code-owned verb
  allow-list, symlink/junction-resolved containment, labeled inert fallback),
  **F4** sweep containment, **F5** DOM injection law over a registered slot
  inventory with a growth rule, **F6** CSRF-class assertions on state-changing
  surfaces with a caller-class threat split.

### Known gaps — stated plainly, not buried
- **E1 is NOT engine-enforced.** A steward turn can still close on an
  unanswered direct question. W8 changed no chamber source: the bound parser,
  the F7 ratification artifact, the turn-completion hook and the joint
  negative-path test are all absent. Convention is the only cover. Full
  evidence in `chamber/E1-ENFORCEMENT-REPORT.md`. Being closed in the next
  release.
- **The ease count is UNAVAILABLE by name.** No classifier of record was ever
  registered, so the 5->0 same-ruler re-score cannot run.
  `chamber/EASE-CLOSE-REPORT.md` refuses to fabricate a number.
- **Tile retirement has NOT executed.** `chamber/TILE-RETIREMENT-GATE.md` is
  unsigned and `chamber_retirement.retirement_allowed` refuses by name, so the
  bottom run tiles all still render. No tile code was deleted.
- Five test files cited in wave reports do not exist in the tree. Named in
  `chamber/W12-AUDIT-REPORT.md` as plan defects.

## v1.1.3 — share-fix (2026-08-01)

The recovery release for the broken 1.1.x collaborator distribution
(`friction-intake-2026-07-30.md`). No new product features — this release
makes a stranger install actually work, honestly.

### Packaging (the root cause)
- `dist_manifest.txt` now lists the 13 runtime modules stranger installs never
  received: `proc_probe`, `reaper`, `reaper_arming`, `freeze_state`,
  `zombie_hunter`, `tidy_idy_runner`, `foundry_integrity`, `foundry_safety`,
  `foundry_skills`, `foundry_acceptance`, `verify_freeze_manifest`, plus
  `orientation` and `parity` (found by the new gate itself). Their absence is
  why boot reconcile died, `/api/rnd/orphan_check` spammed
  `ModuleNotFoundError`, and session bookkeeping ran degraded on every
  collaborator install.
- The entire cold-start surface USER-ONBOARD.md documents (`onboard.cmd` /
  `onboard.ps1` / `share_onboard` and the rest of the `share_*` closure, the
  launcher, `USER-ONBOARD.md` itself, `anchor.ico`, `VERSION`, this changelog)
  is now on the manifest — previously it only shipped because a side build
  script globbed it in past the manifest.
- `distro.py` is the ONE blessed builder, and it gained an **import-closure
  gate**: a build fails if any staged product file imports a first-party
  module that is not staged (lazy imports included — the exact class the old
  gates could not see). Declared optional absences: `update_transaction`,
  `tools/` (dev-only; the healthcheck's parity walk now skip-warns without it
  instead of false-redding the banner).
- The package now ships a THIN consumer `CLAUDE.md` (build-time emitted, never
  the author's) so agents debug cheaply instead of exploring blind.
- NOTE: shipping `reaper`/`reaper_arming`/`zombie_hunter` ships the
  process-reaping daemon; it is UNARMED by default (arming ladder + the
  `.anchor/reaper.disarmed` brake) and boot-reconcile is process-liveness-only.

### Install truthfulness
- Onboard installs the optional terminal extra (`pywinpty`) on Windows for
  Package B — real ConPTY terminals work without a manual `pip install`.
- The fake "service registered / foreground fallback port N" message is gone:
  there is no Windows service in the share path. `launch_anchor_dashboard.py`
  (and the desktop icon that targets it) now genuinely starts the server when
  it is down. After a reboot, run the launcher again.
- Skill registration for Claude now tries symlink → **directory junction**
  (works on stock Windows — no admin, no Developer Mode) → **full copy** as
  the last resort, and reports which mechanism was used. The old silent
  pointer-marker fallback — a folder Claude Code cannot read, reported as
  "registered" — is retired.
- Version stamps aligned: `VERSION` = `pyproject.toml` = this changelog. The
  previously-circulated "1.1.2" was a hand-stamp no repo state reproduces.

### Security defaults (shared installs)
- The launcher wires the onboard-minted `ANCHOR_TOKEN` into the server
  environment and hands it to the browser once (then it is stripped from the
  URL and carried by localStorage + the HttpOnly auth cookie). Mutating
  `/api/*` routes and the terminal/WS surface therefore require the token on
  every collaborator install by default.
- Background model summaries are OPT-IN on shared installs (the launcher sets
  `ANCHOR_PROACTIVE_SUMMARY=0`): Anchor never spends a collaborator's Claude
  subscription without an explicit action. Author-style installs (flag unset)
  keep proactive summaries on.
- Known residual (documented, accepted for 1.1.x): with the default
  `ANCHOR_AUTH_MODE=open`, read-only data-plane GETs stay unauthenticated on
  loopback. Full data-plane enforcement (`enforce` + the static frontend) is
  the v1.2 hardening track.

## 2026-07-30 — Steward usable with auth on · workbench tile collapsed

- **The steward can set a goal again.** Three independent faults made every
  steward act impossible on a token-authed dashboard: the POSTs sent the token
  as `?token=` (the POST middleware never reads the query → 401 → a re-prompt
  for a token the window already held); `handle_ecgberht_stand_up` was declared
  `migrated=True` but never registered in `_MIGRATED_HANDLERS` (→ 404 "Unknown
  endpoint"); and `do_POST` dispatched on the raw request line, so any POST
  carrying a query missed its exact route row. All three fixed and gated.
- **Two more dead endpoints found by the new route gate** — `GET
  /api/rnd/friction` and `POST /api/rnd/journal_friction` had the same missing
  registration and no legacy fallback. The friction journal's own read endpoint
  was one of them.
- **A 401 now retries instead of reloading in the project window** (home already
  did, since 2026-07-28) — a reload discarded the goal input / saybox draft on
  the first click after a token rotation.
- **Workbench tile opens COLLAPSED on project dashboards**, with a click-to-
  expand / click-to-collapse control on the tile summary.
- **Jarvis seal label is the "Server"** (was "Salver", which reads wrong at a
  glance). Image filenames unchanged.
- **Repaired two long-dead tests**: the fetch-wrapper contract tests asserted a
  `location.reload()` the product had deliberately dropped, and
  `test_token_hygiene_lifecycle` had never run a single secret-absence
  assertion. Both now assert the real contract (the hygiene scan is
  mutation-checked).
- **Standing rule added** (DECISION-LOG): auth-off green is not green — any wave
  touching a mutating endpoint must add an auth-ON case asserting the outcome.

## v1.0.0 — 2026-07-23

First shareable product release of Anchor + integrated Skill Foundry skills.

- Human skill cards (HUMAN.md) in Foundry GUI
- Zombie Hunter multi-engine burn ledger + Tailscale-safe reverse proxy
- Tidy-Idy triage panel with Grok investigator option
- Single-use bootstrap reissue: spent nonces never dump raw JSON; HTML 410 + host reissue path
- Spawn-cap census prune; default ANCHOR_SPAWN_CAP=32

## 2026-07-23 — Tidy-Idy bootstrap reissue (share-ready)

- **Spent bootstrap no longer dumps raw JSON.** Single-use SC4 nonces: Anchor re-click POSTs host-only /api/reissue-bootstrap when the panel is still live; otherwise marks status stale and starts a fresh pass.
- **Proxy:** on /bootstrap/ 410, attempt reissue + redirect, else HTML 410 page (never forward spent JSON body over Tailscale).
- **Never open panel_base alone** (that path is health JSON starting with {).

## 2026-07 — Rearchitecture

### W11 (C6) — Data-dir migration + git hygiene
- **Runtime state moves OUT of the repo as one rollback-able unit.** The scripted
  migration (`migrate_data_dir.ps1` → `tools/migrate_data_dir.py`) copies the data
  allowlist into the new `ANCHOR_DATA_DIR`, path-rewrites every repo-rooted
  absolute path to the new root, verifies zero remain, arms the reaper dry-run,
  and **rolls back** (removes the partial new root; old dir untouched) on any
  failure. The ops wrapper stops the service, points NSSM at the new dir, restarts,
  healthchecks, and preserves the old dir read-only for a week.
- **Path-audit tool** (`tools/path_audit.py`): scans every durable store
  (`rnd_registry.json` folder_path, `.anchor/sessions.json` worktree_path,
  `rnd_jobs/*.json` log_path/cwd, per-project `discovery.json` + job records) for
  repo-rooted absolute paths and emits/applies a rewrite map (atomic, idempotent).
- **`ANCHOR_REAPER_DRYRUN`** (`worktrees.py`): the first post-move boot sweeps
  worktrees report-only (env override OR the armed `.reaper_dryrun` marker) so a
  rewrite miss can never delete a legit parked/live worktree; live reaping re-arms
  only after a **clean** dry report.
- **Git hygiene** (`tools/git_hygiene.py` + `.gitignore`): un-tracks the tracked
  runtime artifacts (`git rm --cached`, content kept) so a full healthcheck cycle
  leaves `git status --porcelain` empty. Gate: `tests/test_data_dir_migration_w11.py`.

### W10 (C5) — Markdown-parser de-fork + dead-server deletion
- **Removed `anchor_server.py`** — the dead legacy Flask app (port 5000, retired
  "Anchor PSU" dual-folder layout, ignored `paths.py`, imported by nothing,
  never shipped; superseded by `anchor_gui.py`). Pre-deletion sweep results:
  `docs/anchor_server-predeletion-sweep.md`.
- Extracted the task/project/inbox/archived markdown parsers (and
  `serialize_task_line`) into the single shared module **`anchor_md.py`**,
  imported by both `anchor_gui.py` and `anchor.py`; the byte-identical twin
  parsers are de-forked to one source of truth. Golden-corpus gate:
  `tests/test_anchor_md_defork_w10.py` proves identical parses of the real
  markdown files pre/post de-fork.
