# Ship Anchor v1 — Implementation Plan (Foreman-ready)

test-command: python -m pytest -q

> branch `ship-anchor-v1` off master. Baseline = the current GREEN
> `pytest -q` count (capture at build start; **hold-or-grow, never regress**). Design: the frozen
> `MASTER-PLAN.md` in this folder. Delta on top of the GREEN `planning/share-distro-v1/` effort — REUSE
> distro.py / dist_manifest.txt / vendor_skills.py / onboard.py / enable_remote.ps1, never fork.

## Conventions (read before EVERY wave)
- **Python product code is stdlib-only** (lone lazy `pywinpty` in `pty_manager.py`). Vendored Node skills under
  `vendor/bundled-skills/**` are treated as vendored — the import/entropy scans already skip them; do NOT add
  third-party Python imports.
- **The gate host is Windows** → any cross-platform done-when MUST run on Windows via a **faked-platform /
  dependency-injected seam** (monkeypatch `sys.platform`; inject fake `subprocess`/`os`/`shutil`; stub
  `ANCHOR_SERVICE_CMD`/`ANCHOR_FOREGROUND_CMD`/`ANCHOR_TRIO_DIR`/`ANCHOR_FOUNDRY_DIR`). **`pytest.skip` is NOT
  acceptable as the sole coverage of a POSIX/npm/tailscale path** (the rnd-v12 vacuous-GREEN lesson).
- **Hermetic**: temp `HOME`/`ANCHOR_SKILLS_HOME`/data-dir + temp git **source** repos (mandatory in tests).
  **NEVER** bind `:8777`, spawn a real server, register a real service, run real `npm`/`gh`/`tailscale`, or hit
  the network.
- Every wave **adds a `tests/test_*` collection item** (hold/grow the baseline); a doc-only change still ships
  its own test. Each Done-when is an explicit **Given/When/Then** naming the asserted value.
- **No live packaging/exposure** (real zip hand-off, real Tailscale, real service) until John signs off. Order
  is load-bearing: W1→W2 (vendor+resolve) precede W3 (manifest/scan), which precedes W4/W5 (onboard),
  W6/W7 (discipline+remote), W8 (package).

## Wave 1 — `vendor_skills.py`: data-driven roster + multi-source vendoring
**Goal:** vendor the full 12-skill roster (not the fixed 4), each from its real source, clean.
**Changes:** replace the hard-coded skill list with a **roster map** (skill → source dir → mode:
`git-archive`|`copy`). Support (a) a whole-repo git source, (b) a **subdir of a git repo** (Skill Foundry
`skills/<name>` via `git archive HEAD -- <subpath>` or an equivalent subtree extraction), and (c) a **non-git
source** (denylist-filtered clean copy). Keep the existing denylist (`EXECUTION-LOG.md`, `DECISION-LOG.md`,
`CLAUDE_hist.md`, `journal/`, `*-checkpoint.json`, `.env*`, `node_modules/`, `runs/`, `*-out/`) + host-path/PII
scrub + per-skill `SOURCES.md` (archived commit or "copy@<mtime/hash>"). All source paths are injectable seams.
**Done-when:** Given temp fixtures — a git repo with a `skills/gandalf` subdir (committed source + a committed
`EXECUTION-LOG.md` + a committed file containing `C:\dev\x` and `jane@uni.edu` + a gitignored
`node_modules/x.js`), a git repo for the trio, and a **non-git** dir for agent-builder — When `vendor_all` runs
the roster, Then `vendor/bundled-skills/` contains every rostered skill with its SKILL.md, NO `.git/`, NO
`EXECUTION-LOG.md` (denylist), NO `node_modules/`, the host-path/email scrubbed, and a `SOURCES.md` per skill;
AND gandalf's `runtime/seam-pass.mjs` + `seam/*.mjs` are present.

## Wave 2 — jumper ↔ gandalf sibling resolution (no jumper code change)
**Goal:** prove vendored jumper finds vendored gandalf once installed side-by-side.
**Changes:** ensure vendoring places jumper and gandalf as siblings under `vendor/bundled-skills/`; add a
resolution test. NO edit to jumper's source import.
**Done-when:** Given vendored jumper + gandalf installed as siblings into a temp `ANCHOR_SKILLS_HOME` (via the
onboard install path), When jumper's `../gandalf/runtime/seam-pass.mjs` is resolved from jumper's installed
location, Then the path exists AND the module exposes `applySeamPass` + `SCHEMA_VERSION === 'gandalf-advisor-1'`
+ `SeamPassInputError` (assert via a Node one-shot `import()` through a stubbed/available-node seam, else a
static path+export-symbol assertion when node is absent — NOT a bare skip).

## Wave 3 — manifest + distro clean-scan over the REAL expanded vendor tree
**Goal:** the expanded `vendor/bundled-skills/**` ships and all 4 scans pass over the actual output.
**Changes:** `dist_manifest.txt` allow-lists the expanded vendored tree + `AGENTS.md` + the onboard2 assets
(placeholders acceptable until W6/W7). Confirm `_is_vendored` covers the new skills (it matches the `vendor/`
prefix already — do NOT re-add). No new Python third-party imports.
**Done-when:** Given `vendor_all` (W1) run into a temp tree, When `build_distro` stages + runs all 4 scans, Then
it returns CLEAN (no `PersonalDataError`, no `third-party-import`, no high-entropy false-fail on vendored git
SHAs or `.mjs`); AND a seeded `C:\dev\secret\x` in a NON-vendored staged file still raises `PersonalDataError`
(the detector is live, not disabled by the roster growth).

## Wave 4 — `onboard.py`: install the expanded roster + node/pywinpty prereqs
**Goal:** a clean machine installs every rostered skill as siblings and reports/handles Node deps.
**Changes:** onboard installs ALL bundled skills (copy-default, refuse-don't-clobber, resumable, rollback —
unchanged guarantees, larger set); add a **node prereq report**; run **`npm install --omit=dev`** for any
installed skill whose `package.json` has a non-empty `dependencies`, gated on node present, best-effort + honest
skip; add **pywinpty handling** on Windows (offer/attempt `pip install pywinpty`, honest skip otherwise). All via
seams (`ANCHOR_NODE_CMD`/`ANCHOR_PIP_CMD` stubbed in tests).
**Done-when (temp `ANCHOR_SKILLS_HOME` + temp data dir; stubbed node/pip):** Given a fresh onboard over the
vendored roster, Then every rostered skill is installed as a sibling AND for a dep-bearing skill the stubbed
`ANCHOR_NODE_CMD` recorded an `npm install --omit=dev` in that skill dir; Given node absent, Then install still
completes with an honest "node missing — skipped npm for N skills" record (no crash, no skip-as-coverage);
Given a re-run, Then no-op (idempotent); Given an existing differently-sourced `<skills_home>/gandalf`, Then it
is refused-not-clobbered.

## Wave 5 — onboard preference prompts (auto-run + low-verbosity), opt-in only
**Goal:** the collaborator opts into auto-run and/or low-verbosity; nothing changes silently.
**Changes:** onboard asks two prompts (behind an injectable `ANCHOR_PROMPT_CMD`/answers seam for tests, and a
`--yes-auto-run`/`--low-verbosity`/`--no-prefs` non-interactive form). On opt-in it writes the matching Claude
Code config: **auto-run** → a settings.json permissions/mode change (allowlist or accept-mode) in the chosen
scope; **low-verbosity** → an output-style/instruction file. Decline = no-op. Reversible + idempotent.
**Done-when (temp HOME/config dir; injected answers — NO real prompt):** Given answers {auto-run: yes,
low-verbosity: no}, When onboard applies prefs, Then the settings.json shows the auto-run permission/mode AND no
low-verbosity artifact is written; Given both declined, Then NEITHER artifact is written (byte-for-byte no-op);
Given a re-run with the same answers, Then the config is unchanged (idempotent); AND a test asserts the written
auto-run config is a valid, minimal, documented-reversible change.

## Wave 6 — ship `AGENTS.md` operating discipline (10-min summaries + Status table + low-verbosity)
**Goal:** the collaborator's agent inherits the cadence + format + verbosity rule.
**Changes:** add a distro-root `AGENTS.md` carrying (1) the **10-minute-summary rule**, (2) the **exact locked
"Status table" format** (bordered field/value block: Effort/Doing/Status/Tests/Blocker/Procs + ETA + To do),
(3) the **low-verbosity / human-summary rule**. Keep CLAUDE.md/GEMINI.md as thin pointers. Manifest-allow-list
`AGENTS.md`.
**Done-when:** Given the exported tree, Then `AGENTS.md` is present + manifest-shipped; a test PARSES it and
asserts it contains the 10-minute cadence rule, the Status-table field labels (Effort/Doing/Status/Tests/
Blocker/Procs/ETA/To do) in order, and the low-verbosity rule; AND a no-PII scan over `AGENTS.md` is clean (no
`gwl-server`/`nssm`/`C:\dev`/author host strings).

## Wave 7 — onboard2: cross-platform Tailscale remote access (token-guarded)
**Goal:** expose the running service over Tailscale on Windows / macOS / Linux, never without auth.
**Changes:** formalize an **onboard2** flow. Windows: the existing `enable_remote.ps1` path (service env
`ANCHOR_TOKEN`/`ANCHOR_BIND` + Tailscale dependency + restart). POSIX: a `tailscale serve` path (macOS/Linux).
BOTH: a **hard guard that refuses to expose without a non-empty `ANCHOR_TOKEN`**. A repo-local `/onboard2`
skill + README section. All external calls behind an `ANCHOR_TAILSCALE_CMD` seam (stubbed).
**Done-when (platform + tailscale seams faked; NO real exposure):** Given `sys.platform` forced to each of
win32/darwin/linux with a stubbed `ANCHOR_TAILSCALE_CMD`, When onboard2 runs with a token set, Then it records
the correct per-OS enable argv (PowerShell service-env edit on win32; `tailscale serve` on darwin/linux) AND the
token is carried; Given NO `ANCHOR_TOKEN`, When onboard2 runs on ANY platform, Then it REFUSES (records zero
tailscale calls) with an honest "set a token first" message — no skip.

## Wave 8 — build → scrub → zip + clean-room onboard verify (PROJECT DONE)
**Goal:** one command yields a scrubbed zip; a clean-room onboard from it succeeds; regression walk added.
**Changes:** a `package_distro(dest_zip)` step: `build_distro` (clean-scan gate) → package the staged tree to a
zip/tarball. A `check_onboard_surface`-style hermetic regression that unpacks the archive into a temp dir and
runs onboard (stubbed service/node) over the FULL roster. `anchor.py` read-only mirror if applicable; README +
CLAUDE.md "Shareable distro v1" section updated (roster, zip delivery, onboard, onboard2).
**Done-when (`port=0`, stubbed seams, temp dirs; never `:8777`/network):** Given `vendor_all`→`package_distro`,
Then a zip is produced whose staged tree passes all 4 scans (a PII hit anywhere ABORTS before packaging AND
records zero zip output); Given the zip unpacked into a temp clean-room, When onboard runs, Then all 12 rostered
skills install as siblings + starter Anchor scaffolds + a token is minted OUTSIDE the tree; AND `pytest -q` is
green ≥ baseline incl. the new regression test; AND a test PARSES the README and asserts each referenced command
(`python onboard.py`, `/onboard`, `/onboard2`) maps to a real entrypoint AND the 12 skill names are listed.
