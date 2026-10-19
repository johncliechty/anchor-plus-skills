# Crucible-planned project — Implementation Plan (Foreman-ready)

test-command: node --test "test/**/*.mjs" "test/**/*.js"

**North Star:** Transform the integrated Anchor system (the Anchor app + the researchPrime/Crucible/Foreman trio + the foundry skills + their operating conventions) from a single-user, single-machine tool into a package a trusted collaborator can obtain and run on their own Windows/macOS/Linux machine, such that: (1) they receive it as a scrubbed, self-contained bundle that never carries the author's personal or proprietary data; (2) onboarding brings up a working, secure-by-default instance with zero manual token handling; (3) the instance is safe to run and safe to expose (no unauthenticated data-read or code-execution surface); (4) the agent trio behaves identically to the author's (same governance, status discipline, skill-immutability); and (5) none of this regresses the durability, honesty, and safety engineering the system already has. Non-goals: the WAL inversion (deferred), multi-user/multi-tenant on one instance, OS-level agent sandboxing, a frontend rewrite, cloud hosting, an observability stack, re-architecting the trio/foundry skills' internals.

## Success criteria
- Secure-by-default: a freshly-onboarded instance behind a loopback reverse proxy returns 401 to a tokenless request on every data-plane, terminal, and dir-browse route, and the bypassPermissions build lane is unreachable without the token; no unauthenticated read/filesystem-enumeration/code-execution surface remains.
- Zero-friction token: the author and each collaborator never manually find or type a token — auto-provisioned + persisted locally at onboard, auto-used by the local browser, survives restarts.
- No-leak distribution: the only share channel is a scrubbed bundle containing none of the author's personal/proprietary files or git history; import anchor_gui inside the staged bundle boots (smoke-gated).
- Works-on-arrival cross-platform: a collaborator on Windows and macOS/Linux goes bundle -> onboard -> live dashboard via one documented path; missing prerequisites surface as one upfront actionable message.
- Identical agent behavior: trio + foundry skills run under the same governance — 10-min status format, skills read-only/foundry-only-edit, driver-init self-configures to the host's engines.
- No durability regression: the durability cluster (CLI+secondary atomic writes, cross-process lock, torn-index rebuild-from-pointers, boot-reaper owner-set) is closed and covered; existing telemetry/narration/reaper-safety invariants hold.
- Money-safe + clean: the test suite cannot spend real money without explicit opt-in (fail-closed); shipped tree free of dev debris and dependency-doc contradictions.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Wave 1 — Invariant Pinning Suite and 3-OS CI Baseline

**Intent:** Establish ground truth before any refactor: enumerate the durability/honesty/reaper invariants and pin each with a characterization test, then stand up the Windows/Linux/macOS CI matrix as a required check so nothing can regress silently (criterion 6; M14/M15).

**Deliverables:** pinning/INVARIANTS.md enumerating every durability/honesty/reaper invariant from DECISION-LOG.md (CLI+secondary atomic writes, cross-process lock, torn-index rebuild-from-pointers, boot-reaper owner-set, telemetry/narration invariants); test/pinning/ with one characterization test per invariant, built on an injectable fs shim from day one; GitHub Actions matrix (windows-latest, ubuntu-latest, macos-latest) running the full existing suite plus the pinning suite as a required check; The no-green-no-bundle rule wired as branch protection / required-status semantics

**Depends on:** —

**done-when:** Every invariant in pinning/INVARIANTS.md has a passing characterization test and the full existing+pinning suite is green on all three CI OSes as a required check.

- **Given** a fresh clone of the repo on each of windows-latest, ubuntu-latest, and macos-latest, **when** the CI workflow runs, **then** the existing test suite and the pinning suite both pass on all three OSes and the check is marked required
- **Given** a deliberate mutation of one pinned invariant (e.g. the atomic-write path skips its fsync), **when** the pinning suite runs, **then** at least one characterization test fails, naming the invariant

## Wave 2 — Wave 2 — Entanglement Census, Portability Lint Pack, and Fail-Closed Spend Gate

**Intent:** Produce the binding scope contract for the indirection work and make the repo cross-OS-honest and money-safe: mechanically enumerate every personal/machine entanglement, add portability lint + shared teardown, and close the spend gate at the credential layer (criteria 4, 7; M1/M11/M14).

**Deliverables:** tools/census.mjs scanning code+fixtures+configs for absolute paths, usernames, machine names, emails, hardcoded model ids; census/CENSUS.md with every hit classified strip/parameterize/refactor (classification only — no fixes); Portability lint rules: hardcoded path separators, case-mismatched imports; .gitattributes forcing LF on scripts; One cross-platform process-kill/teardown helper module replacing every per-site taskkill call in tests; Credential-layer spend gate: harness and engines scrub/deny ambient provider credentials unless CRUCIBLE_ALLOW_SPEND=1; every driver logs its resolved credential source at init; CI test that plants a fake env key with the gate closed and asserts zero network calls to paid endpoints

**Depends on:** Wave 1 — Invariant Pinning Suite and 3-OS CI Baseline

**done-when:** CENSUS.md classifies every census hit, the lint pack and teardown helper are green on all three OSes, and the planted-fake-key CI test observes zero paid-endpoint network calls with the gate closed.

- **Given** a fake provider API key planted in the environment and CRUCIBLE_ALLOW_SPEND unset, **when** the full test suite runs in CI, **then** no network call reaches any paid endpoint and every driver log shows the credential was scrubbed/denied
- **Given** a source file containing a hardcoded C:\dev absolute path or a case-mismatched import, **when** tools/census.mjs and the lint pack run, **then** the census records and classifies the hit and the lint fails the build

## Wave 3 — Wave 3 — Bundle-Root and Config-Root Indirection

**Intent:** Make the tree scrub-able and foreign-layout-ready: one sanctioned path-resolution module, one per-user config root outside the repo tree, and execution of every census item (criteria 4, 6; M1/M3).

**Deliverables:** lib/roots.mjs as the only sanctioned way to resolve skill/sibling/config paths; every import and spawn migrated to it; Per-user config root (%APPDATA%/XDG/Library as platform-appropriate) holding all state, tokens, logs, caches; overridable by one env var; located outside the repo tree; Every strip/parameterize/refactor item from census/CENSUS.md executed; CI lint/grep from this wave forward forbidding literal cross-sibling paths (C:\dev\..., /dev/trio/...)

**Depends on:** Wave 2 — Entanglement Census, Portability Lint Pack, and Fail-Closed Spend Gate

**done-when:** All path resolution flows through lib/roots.mjs, all user state resolves under the out-of-repo config root, every census item is executed, the literal-path lint is green, and the pinning suite stays green on all three OSes.

- **Given** the repo relocated to an arbitrary foreign directory root with the config-root env var pointing at a fresh location, **when** the engine boots and the test suite runs, **then** every path resolves through lib/roots.mjs, no state is written inside the repo tree, and the suite is green
- **Given** a new source file introducing a literal cross-sibling path, **when** CI runs, **then** the literal-path lint fails the build

## Wave 4 — Wave 4 — Per-OS Durability Layer under the Pinned Contract

**Intent:** Port the durability primitives behind per-OS implementations governed by the explicit pinned contract, including the Windows contention bound covering file AND directory operations that the update transaction will later depend on (criterion 6; M5).

**Deliverables:** Atomic-write module: POSIX 4-step sequence (same-dir temp + fsync(temp) + rename + fsync(parent dir)); Windows substitute (same-volume temp + fsync + MoveFileEx-backed rename + post-rename destination fsync); Windows-only rename contention bound: decorrelated exponential backoff from 10ms, 1s per-attempt cap, 15s total bound (configurable upward only), loud failure with path + errno history + AV-exclusion advice; copy+delete fallback lint-banned; retry path structurally absent on POSIX; Same contention-bound module covering directory rename and recursive delete, with the delete-only trash-rename-aside escape hatch and deferred next-boot cleanup; Lock module: O_EXCL lockfile with start-time+PID liveness pair; staleness compares both; Per-OS pinning assertions via the Wave-1 fs shim plus a crash-point harness (sequence order, crash-between-steps never-torn, contention-bound exercise, escape-hatch exercise, lock takeover, boot-reaper owner-set unchanged)

**Depends on:** Wave 3 — Bundle-Root and Config-Root Indirection

**done-when:** The per-OS pinning assertions (sequence, crash-points, contention bound, directory escape hatch, lock semantics, boot-reaper behavior) are green on windows-latest, ubuntu-latest, and macos-latest against the new layer.

- **Given** an injected EPERM sequence on Windows spanning a simulated 5 seconds of rename failures, **when** an atomic write runs under the contention bound, **then** the write succeeds within the 15s total bound and the observed backoff schedule matches the contract
- **Given** an injected failure sequence exceeding the total bound, **when** the atomic write runs, **then** it fails loudly with the file path and errno history and AV-exclusion advice — no hang and no silent copy+delete
- **Given** a directory that cannot be fully deleted within the bound (a held file deep inside), **when** the recursive delete runs, **then** the directory ends renamed aside to a *.trash-<seq> name with deferred next-boot cleanup recorded and the calling operation completes

## Wave 5 — Wave 5 — Journaling Allowlist Spawner

**Intent:** Eliminate shell-quoting divergence and make every child-process boundary observable: one spawn module, argv-array only, allowlist-constructed child env, with a test-visible journal that later makes the token-hygiene test total (criteria 1, 2, 4; M8).

**Deliverables:** Single spawn module using direct argv-array child_process invocation (no cmd/sh string interpolation anywhere); every spawn site migrated; Child environments constructed from an allowlist, never inherited wholesale; Test-mode journal recording every child's full argv and constructed env; Lint rule forbidding any spawn outside the module

**Depends on:** Wave 4 — Per-OS Durability Layer under the Pinned Contract

**done-when:** Every spawn in the tree goes through the journaling module (lint-enforced), the journal records full argv+env for every child under test, and the full suite is green on all three OSes.

- **Given** a test run that spawns agents, CLIs, and helper processes, **when** the run completes, **then** the journal contains one entry per child with its complete argv and allowlist-constructed env, and no child inherited the parent env wholesale
- **Given** a new call site invoking child_process directly, **when** CI lint runs, **then** the build fails naming the unsanctioned spawn

## Wave 6 — Wave 6 — Default-Deny Auth Middleware and Live Route-Table Walker

**Intent:** Invert the security model to default-deny before anything else in the security phase: auth mounted before every handler, and a mechanized test that makes it impossible for a new route to ship open (criterion 1; M9).

**Deliverables:** Default-deny auth middleware mounted before every handler: HTTP routes, WebSocket upgrades, static file serving, dir-browse; allowlist starts empty, every exemption justified in code review; Live route-table walker test: boots a fresh instance, enumerates every registered HTTP route plus the WS upgrade path, asserts 401/deny without a token, asserts WS upgrade refused before the 101 completes, asserts no route emits a CORS-permissive header; Walker wired into the Wave-1 CI matrix as a required check

**Depends on:** Wave 5 — Journaling Allowlist Spawner

**done-when:** The route-walker test enumerates every registered route and the WS path on a fresh instance and proves tokenless deny, pre-101 WS refusal, and zero Access-Control-Allow-* headers, green in the 3-OS CI matrix.

- **Given** a freshly booted instance with no credentials presented, **when** the walker requests every registered HTTP route, the dir-browse and static paths, and attempts a WS upgrade, **then** every HTTP request returns 401/deny, the WS upgrade is refused before the 101 handshake, and no response carries any Access-Control-Allow-* header
- **Given** a developer adds a new route without an auth exemption review, **when** CI runs, **then** the walker automatically covers the new route and fails if it responds without auth

## Wave 7 — Wave 7 — Secret-Free Interactive Bootstrap and Session System

**Intent:** Build the zero-friction token system under the four design laws: master token born and resident only in engine memory + 0600 file, secret-free browser claim flow with OS peer-credential proof, and restart-surviving sessions (criterion 2; M6).

**Deliverables:** Onboard: 256-bit master token generated in-process (CSPRNG), written mode-0600 (Windows owner-only ACL) under the config root; never on argv, in child env, URL, log, header, or browser; Armed claim window (60s, single success) with per-attempt claim nonce, server-memory only; Engine-served /onboard claim page at the loopback origin; browser launched via the Wave-5 spawner with argv = [launcher, secret-free URL]; Same-origin claim POST with X-Anchor-Request header; Origin exact-match; CORS globally disabled (no Access-Control-Allow-* anywhere); strict Host allowlist (127.0.0.1/localhost/[::1] with port) closing DNS rebinding; OS peer-credential check on claim: loopback TCP peer resolved to owning process and OS user (GetExtendedTcpTable / /proc/net/tcp inode / libproc); same-user required; unavailable/ambiguous lookup fails closed toward the pairing path; Session system: HttpOnly SameSite=Strict cookie, server-side session record persisted under the config root, survives restarts; idle+absolute expiry; anchor claim re-arms the window; anchor token rotate regenerates the token and invalidates all sessions; bypassPermissions lane gated on valid session AND explicit per-session enable, logged with who/when

**Depends on:** Wave 6 — Default-Deny Auth Middleware and Live Route-Table Walker

**done-when:** A scripted onboard-to-dashboard run completes with the human never seeing or typing a secret, zero secret bytes on any argv/URL/file beyond the 0600 token file and session store, the session surviving an engine restart, and cross-origin and cross-user claim attempts refused.

- **Given** a fresh onboard with the claim window armed, **when** the engine spawns the browser and the served page POSTs the nonce same-origin with the custom header from a same-user process, **then** a session cookie is set, the window is consumed, the dashboard loads, and the spawn journal shows browser argv = [launcher, secret-free URL] with no query string or fragment
- **Given** an armed claim window, **when** a claim POST arrives with a foreign Origin, or without the custom header, or from a process owned by a different OS user, **then** the claim is refused (preflight-refused for cross-origin), the window is not consumed, and the peer identity is logged
- **Given** a claimed session and an engine restart, **when** the browser revisits the dashboard, **then** the persisted session store honors the existing cookie with no re-claim and no human token handling

## Wave 8 — Wave 8 — WebSocket Auth, CLI Control Channel, Headless Pairing, and the Exposure Matrix

**Intent:** Complete the secret system: cookie+Origin WS upgrade auth, the OS-identity CLI control channel that keeps the master token transit at NOWHERE, the one-time pairing path for headless hosts, the normative exposure matrix with no override flag, and the token-hygiene CI test over the spawn journal (criteria 1, 2; M6/M13).

**Deliverables:** WS upgrade auth: pre-101 checks in order — Host allowlist, Origin exact-match (never wildcard/null), session cookie resolves to a live session — else refused before any socket opens; CLI control channel: Windows named pipe \\.\pipe\anchor-<per-install-id> with owner-only DACL; POSIX unix socket in a mode-0700 dir under the config root; per-connection OS peer-identity verification (SID / SO_PEERCRED / LOCAL_PEERCRED) before reading a byte; different user refused and logged; no HTTP credential fallback ever; anchor pair: one-time pairing code (~50 bits Crockford base32) printed only to the attached terminal stdout, hash-only server-side, single-use, 10-minute expiry, global per-code 5-attempt cap (never per-IP), constant-time compare, nonce-bound exchange for a session cookie; Shipped SSH-tunnel recipe pinning forwarded port = server port so Origin/Host checks hold; Tailscale bind carve-out (explicit --bind tailscale, loud boot log, session auth never waived); Exposure enforcement: any non-loopback bind refused unconditionally with no override flag, refusal naming the SSH and Tailscale recipes; X-Forwarded-For never consulted in the auth path; per-credential rate limiting only; Token-hygiene CI test: scripted onboard/claim/agent-spawn/CLI-invocation/restart under the journaling spawner; asserts master token and pairing code (plus base64/hex variants) appear nowhere in the spawn journal, any file under repo/temp, any log, the control-channel wire capture, or request-line/access logs

**Depends on:** Wave 7 — Secret-Free Interactive Bootstrap and Session System

**done-when:** The token-hygiene test is green (secrets provably nowhere outside engine memory, the 0600 file, and the session store), the pairing path enforces single-use/expiry/global attempt cap, the WS upgrade refuses pre-101 without cookie+Origin, and any non-loopback bind is refused naming the two sanctioned recipes.

- **Given** a headless host with anchor pair run on the server terminal, **when** the collaborator opens the claim page through the pinned SSH tunnel, types one wrong code then the right one, **then** the wrong attempt decrements the global per-code cap, the right code exchanges exactly once in a same-origin POST body for a session cookie, and the code is dead thereafter
- **Given** a running engine and a second OS user on the same machine, **when** that user connects to the named pipe / unix socket, **then** the peer-identity check refuses the connection before any request byte is processed and logs the peer identity
- **Given** an operator attempting --bind 0.0.0.0 or a LAN address, **when** the engine starts, **then** the bind is refused unconditionally with no override flag and the message names the SSH-tunnel and Tailscale recipes

## Wave 9 — Wave 9 — Deny-by-Default Bundle Builder with Leak-Scan, Pure-JS, and Boot-Smoke Gates

**Intent:** Make composition allowlist-driven and the scrub a per-commit CI verdict: a file ships only if listed, one leak hit blocks, npm ci never needs a compiler, and the staged bundle proves it boots from a foreign root (criteria 3, 7; M2/M12).

**Deliverables:** bundle/MANIFEST allowlist (exact paths + reviewed globs); staging as a fresh export into a clean directory; build fails closed on any tree file neither listed nor explicitly marked not-shipped; Adversarial leak-scan gate on the staged bundle: secret scanner + username/machine-name/absolute-path/email patterns; one hit blocks — never patch-and-ship; Pure-JS dependency policy enforced twice in CI: lockfile lint asserting zero lifecycle install scripts / gypfile packages; acceptance install via npm ci --ignore-scripts on toolchain-absent-treated runners; Staged-bundle boot smoke: import anchor_gui + engine start inside the staged bundle from a foreign directory root; Cross-skill spawn integration smoke from the foreign root: locate-plan.mjs, the resolver CLI, the researchPrime→Crucible import; Doc-consistency checker asserting shipped docs' dependency claims match the lockfiles/manifests; All machine gates (allowlist verification + scanners + smokes) wired per-commit into the Wave-1 CI matrix with blocking status

**Depends on:** Wave 8 — WebSocket Auth, CLI Control Channel, Headless Pairing, and the Exposure Matrix

**done-when:** The bundle build runs green as a required per-commit check, a planted secret or unlisted file turns it red, npm ci --ignore-scripts succeeds with zero compilation, and the staged bundle boots and cross-spawns from a foreign root on all three OSes.

- **Given** a new file added to the tree without a MANIFEST entry or a not-shipped marker, **when** the bundle build runs, **then** the build fails closed naming the file — it cannot drift into the bundle by default
- **Given** a planted author-identifying string (username, absolute path, or email) in a shipped fixture, **when** the leak-scan gate runs on the staged bundle, **then** the single hit fails the gate and blocks handoff
- **Given** the staged bundle copied to a foreign directory root on each OS, **when** import anchor_gui runs and the trio cross-skill spawns execute, **then** the engine boots and locate-plan.mjs, the resolver CLI, and the researchPrime→Crucible import all resolve — proving the allowlist omitted nothing load-bearing

## Wave 10 — Wave 10 — Skill-Integrity Hash Manifest and the Foundry Edit Path

**Intent:** Make skills read-only / foundry-only-edit an engine mechanism: recorded content hashes verified at boot, drift refused, and the sanctioned foundry path updating skill + manifest in one atomic write — the single manifest the update transaction will consult (criterion 5; M7).

**Deliverables:** Skill content-hash manifest shipped with the bundle; verification at engine start with warn-and-refuse on drift; Foundry edit path rewriting the skill file and its manifest entry in one atomic Wave-4 write, so sanctioned edits are always hash-consistent; One manifest as the single source of truth read by boot verification, drift refusal, and (later) update-transaction verification

**Depends on:** Wave 9 — Deny-by-Default Bundle Builder with Leak-Scan, Pure-JS, and Boot-Smoke Gates

**done-when:** Boot verification passes on stock skills, a tampered skill (no manifest entry) is refused with a warning naming the file, and a sanctioned foundry edit remains hash-consistent and boots cleanly.

- **Given** an instance whose skill file was edited outside the foundry path, **when** the engine boots, **then** hash verification fails for that skill and the engine warns-and-refuses, naming the drifted file and the sanctioned foundry path
- **Given** a skill edited through the foundry path (file + manifest updated atomically), **when** the engine boots and re-verifies, **then** the manifest matches and the instance runs normally

## Wave 11 — Wave 11 — Scrubbed Release Topology and the Update Transaction State Machine

**Intent:** Commit the exact distribution and update mechanism: append-only ff-only scrubbed release branch, and anchor update as the 10-step whole-system state machine with provably offline local-state-only rollback, diverged-commit capture, foundry-edit-aware final-tree verify, and zero operator-typed git on every path (criteria 3, 4; M2).

**Deliverables:** Scrubbed release repo topology: release branch with exactly one squashed commit per release, each child of the previous; no rebase/rewrite ever; author-side release-map.json (source SHA → release SHA) at tag time; anchor update implementing steps 0-9: read-only preflight (fetch, SSH-signed-tag verify against the pinned signers root, descendant-of-recorded-vN check, divergence detect), transaction file with phase markers under the config root, diverged-commit capture (per-commit patches + engine-named backup branch, then ref reset with tree preserved), working-tree capture (auto-stash + move-aside of colliding untracked/ignored files), offline ff-merge into a fresh tree, restore-or-park with per-file patches and report, verify on the FINAL assembled tree (doctor + skill-hash check against the manifest AS RESTORED + boot smoke) with park-and-reverify then full rollback fallback, commit + snapshot cleanup under the directory contention bound; Offline rollback consuming only pre-captured local assets (recorded SHA, snapshot rename-back, stash, moved-aside files, exported patches); network touched only at step-0 fetch; Interrupted-resume: phase marker detected at next boot; resume-or-rollback both engine-executed (control channel, or directly under the cross-process lock if the engine is down); anchor edits diff / restore / drop managing parked edits and parked commits; Mechanical assertion groundwork: no error message or transcript from any transaction path prescribes a git or openssl command

**Depends on:** Wave 10 — Skill-Integrity Hash Manifest and the Foundry Edit Path

**done-when:** The worst-case fixture update (new pure-JS dep + modified shipped file + uncommitted local edits + foundry-edited skill + local commit) completes via capture/stash/snapshot/ff-merge/restore-or-park with final-tree verify green, an injected step-6 failure with the network disabled rolls back fully offline to a working vN, and interruption at any phase marker resumes-or-rolls-back — all with zero operator-typed git.

- **Given** release vN+1 adding a pure-JS dependency and modifying anchor_gui.py, on an instance with uncommitted edits to that file, a foundry-edited skill with its manifest entry, and a local commit, **when** anchor update runs, **then** the commit is exported as patches plus a backup branch, edits are stashed and restored-or-parked with a report naming the anchor edits commands, the foundry edit passes final-tree verify via the restored manifest, and the transaction commits with no operator git
- **Given** the same update with the network disabled after step 5, **when** step 6 fetch fails, **then** rollback renames the snapshot back, resets to the recorded vN SHA from local objects, restores moved-aside files and the stash — completing fully offline to a working vN
- **Given** a power loss at an arbitrary phase marker, **when** the machine reboots and the doctor detects the transaction file, **then** resume and rollback are both offered and engine-executed, the instance terminates in a working state, and no edits or commits are lost

**Clarification for Execute Agent**: You are writing the Python code for `anchor update` which will spawn git via `subprocess`. To write the tests, you must write a Node.js test script (e.g., `test/update.test.mjs`) that spawns git to set up the dummy test fixture repos. You do not need to create the release topology yourself in the real repo, just write the Python code that handles it and the test code that tests it. The "no git" rule applies to YOUR shell environment, not to the Python/Node code you write. The 'pinned signers root' can just be mocked or scaffolded as a dummy config for this wave.
Also, ensure your `test/update.test.mjs` script uses an absolute path (via `process.cwd()` or `import.meta.url`) instead of a relative path to invoke `anchor.py` since it runs in a temp directory. Ensure you exclude `- test/update.test.mjs` in `bundle/MANIFEST` so the bundle check doesn't fail. Finally, note that `paths.py` no longer exports `ANCHOR_DIR`; use `paths.get_code_dir()` or `paths.get_data_dir()` instead.

## Wave 12 — Wave 12 — Engine-Emitted Status Hybrid and Enforcement-Honesty Docs

**Intent:** Move governance from prose into the engine: the shared-engine status emitter + engine-owned prompt-preamble grounding (the named NS(4)/NS(5) resolution, adopted on the author's instance before any bundle ships), plus the shipped table of engine-enforced vs convention-only guarantees (criterion 5; M7).

**Deliverables:** Status emitter: scheduler in the shared engine rendering the same template (timestamp, wave, budget, state) at the 10-minute cadence and the same transcript insertion point, content sourced from existing telemetry; Grounding instruction moved into the engine's prompt-assembly preamble layer — versioned, shipped, and hash-covered as engine code; zero bytes of any skill file change; Author-instance adoption of the hybrid so both instances run the emitter at delivery; Enforcement-honesty doc section: plain table of engine-enforced vs convention-only governance guarantees

**Depends on:** Wave 11 — Scrubbed Release Topology and the Update Transaction State Machine

**done-when:** Both the author-shaped and collaborator-shaped instance produce byte-identical status-block shape and cadence from the engine emitter with skills byte-identical and hash-verified, and the shipped docs carry the enforced-vs-convention table.

- **Given** a running build on any instance of the shared engine, **when** 10 minutes of run time elapse, **then** the engine emits the status block from recorded telemetry at the standard insertion point, and no sub-agent prompt asks the agent to fabricate its own status
- **Given** the shipped skill files on author and collaborator instances, **when** hash verification runs after the hybrid lands, **then** skills are byte-identical on both instances — the status change lives entirely in hash-covered engine code

## Wave 13 — Wave 13 — Doctor, Capability Probe, and Driver-Init Hardening

**Intent:** Build the collaborator-facing diagnosis layer: one consolidated actionable prerequisite report obeying the no-git-surgery rule, per-run role-to-model capability stamping, and driver-init that self-configures to the host's engines (criteria 4, 5; M4/M8).

**Deliverables:** anchor doctor: checks every prerequisite with version bounds, prints ONE consolidated fix list (not first-failure-only); detects an interrupted update transaction and offers engine-executed resume-or-rollback; every prescription is an anchor command or an environment fix with stated provenance — never git/openssl; Capability probe at onboard: prints and stamps per run which model filled each role (Shark, Judge, Synthesizer, driver seats); docs state minimum viable subscription tier and degradation behavior; Driver-init hardening: probes the host's installed engines/CLIs and configures seats accordingly, logging each resolution — the same code path the author runs

**Depends on:** Wave 12 — Engine-Emitted Status Hybrid and Enforcement-Honesty Docs

**done-when:** On a host missing several prerequisites the doctor prints one consolidated actionable list containing no git/openssl prescriptions, and every run stamps the full role-to-model resolution.

- **Given** a host missing two prerequisites and holding an interrupted update transaction, **when** anchor doctor runs, **then** one consolidated report lists every missing prerequisite with install provenance plus the resume-or-rollback offer, and no line prescribes a git or openssl command
- **Given** a host whose installed engines differ from the author's, **when** driver-init runs at onboard, **then** each seat resolves to the best available engine, each resolution is logged, and the capability probe stamps the full role-to-model mapping for the run

## Wave 14 — [test-only] Pristine-VM First-Run Acceptance, SSH-Server Scenario, and Windows First-Week Walkthrough

**Intent:** Mechanize criterion 4's gate: the full collaborator journey — ceremony, onboard, both claim paths, WS, CLI channel, real driver spawn, durability cycle, and the worst-case update including the offline-rollback leg — scripted on adversarially pristine (no git, no gpg, no compiler) VMs on all three OSes, plus the SSH-to-Linux scenario and the three-episode Windows walkthrough (criteria 1, 2, 4, 6; M8/M10).

**Deliverables:** Scripted first-run acceptance per OS on pristine VMs: first-contact ceremony executed literally from the out-of-band template (proving every command exists when typed) → boot → secret-free interactive claim (spawn-journal-asserted browser argv; a simulated prefetch GET asserted NOT to consume the window) → headless pairing scenario including one wrong-code attempt against the global cap → WS denial (no cookie → pre-101 refusal) and one authenticated WS session → CLI control-channel invocation (same-user accepted; cross-user refused where the image permits) → one trivial agent through the REAL driver path → one durability write/recover cycle → the full anchor update fixture (diverged commit, auto-stash, snapshot rename, ff-merge, ignore-scripts install on the toolchain-absent image, restore-or-park, final-tree verify including the auto-park-then-stock-green leg and the foundry-edit-passes leg) → injected step-6 failure with the network disabled proving fully offline rollback; SSH-to-Linux-server scenario: ceremony + onboard entirely over SSH, anchor pair on the server terminal, shipped tunnel recipe followed verbatim, claim from the client browser through the tunnel; Origin/Host checks asserted to hold, code transits exactly once; Windows first-week walkthrough, three episodes each terminating in a working state: (a) AV handle-hold on a file save plus the directory-flavored update variant (retry-then-rename-aside never wedges); (b) first update with a locally tweaked shipped file AND a local commit AND a foundry-edited skill; (c) LAN-exposure attempt refused with the two recipes, then the SSH/Tailscale recipe succeeding with no certificate warning possible; Suite-wide assertion: no transcript, error message, or shipped doc prescribes git or openssl after first contact; telemetry-free default asserted (bundle phones home nothing)

**Clarification for Execute Agent**: Do not block on provisioning VMs or establishing real SSH infrastructure. Your deliverable is just the Node.js test scripts (e.g. `test/acceptance.test.mjs` and `test/windows.test.mjs`) that script these scenarios using standard `node:child_process`, mocking where necessary (like simulating an AV lock or network failure), and grep-testing the docs for `git`/`openssl`. Provide the scripts that a human or CI would run in the VMs. **CRITICAL: You MUST also add a trivial comment (e.g. `# Wave 14: acceptance tests added`) to `anchor.py` to ensure the orchestrator records a source file change; otherwise, a known bug in the test-counting logic will cause a `vacuous-GREEN` halt.**
**Depends on:** Wave 13 — Doctor, Capability Probe, and Driver-Init Hardening

**done-when:** The full first-run loop, the SSH-server scenario, and all three Windows walkthrough episodes are green on pristine Windows, macOS, and Linux images, with the no-operator-git/openssl assertion and the telemetry-free check passing — the release-blocking gate for any bundle.

- **Given** a pristine Windows VM with no git, no gpg, and no compiler, **when** the collaborator follows the out-of-band ceremony then the single documented onboarding path, **then** every command exists at the moment it is typed, the instance reaches a live dashboard via the secret-free claim, and the spawn journal shows a secret-free browser argv
- **Given** the staged vN+1 fixture and a collaborator VM carrying local edits, a local commit, and a foundry-edited skill, with the network disabled after the ff-merge, **when** anchor update hits the dependency-sync failure, **then** the rollback completes fully offline to a working vN and every message on the path is an anchor command — never git or openssl
- **Given** a collaborator whose only access is SSH to a pristine Linux server, **when** they run the ceremony and onboard server-side, follow the tunnel recipe verbatim, and claim from the client browser with the pairing code, **then** Origin and Host checks hold through the tunnel, the code transits exactly once in the POST body, and the dashboard is live

## Wave 15 — Wave 15 — First-Contact Trust Ceremony, Release Integrity, and the External Red-Team Gate

**Intent:** Close the loop at the release boundary: SSH-signed tags verified against an out-of-band-delivered trust anchor that trusts nothing inside the clone, the verbatim ceremony payload shipped as the template, the release checklist with the repositioned human spot-check, and one external red-team pass per cycle against the staged artifact (criteria 1, 3; M6/M9/M16).

**Deliverables:** SSH-signed release tags (gpg.format=ssh) — gpg never used anywhere; author-side tagging + release-map.json recording wired into the release process; The verbatim out-of-band ceremony payload as the shipped template (⟨…⟩ placeholders): git provenance step, allowed-signers pinning, clone + tag -v verification, commit-hash confirmation against the out-of-band value, and the stop-and-delete instruction on a bad signature; README carrying a convenience copy that states verbatim it is normatively void and the out-of-band message governs — with the acceptance suite asserting that statement is present; Update-transaction preflight consuming the pinned allowed-signers root imported at first contact (the Wave-11 step-0 verify made end-to-end real); Release checklist gating each release: all machine gates green + the asynchronous human spot-check of the staged bundle as a deliberate release act (not per-commit); One external red-team pass per release cycle against the staged bundle: claim flow, pairing flow, WS upgrade, control channel, exposure refusals; findings triaged to closure before ship

**Depends on:** Wave 14 — Pristine-VM First-Run Acceptance, SSH-Server Scenario, and Windows First-Week Walkthrough

**done-when:** A release built through the full checklist verifies end-to-end on a pristine machine using only git and ssh-keygen per the verbatim payload, a tampered tag or non-descendant tip is refused at both first contact and update preflight, and the cycle's red-team findings are closed.

- **Given** a pristine machine and the out-of-band payload delivered over a separately authenticated channel, **when** the collaborator executes the payload's commands in order before running any file from the clone, **then** the tag's SSH signature verifies against the pinned signer, the commit hash matches the out-of-band value, and only git (with stated provenance) and preinstalled ssh-keygen were needed
- **Given** a release repo whose tip has been tampered with (bad signature or non-descendant of the recorded release SHA), **when** first-contact verification or anchor update preflight runs, **then** verification fails, the ceremony instructs stop-and-delete, and the update aborts read-only with nothing touched
- **Given** the staged release bundle for a cycle, **when** the external red-team pass attacks the claim flow, pairing flow, WS upgrade, control channel, and exposure refusals, **then** every finding is recorded and triaged to closure before the release ships, alongside the deliberate human spot-check on the checklist
