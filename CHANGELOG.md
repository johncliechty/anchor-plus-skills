# Changelog

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
