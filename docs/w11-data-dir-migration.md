# W11 (C6) — Data-Dir Migration + Git Hygiene — operator runbook

Move Anchor's runtime state OUT of the repo (`ANCHOR_DATA_DIR` → a folder outside
`C:\dev\Anchor`) as ONE scripted, rollback-able unit, then keep the repo provably
clean. Journals (W12+) are then born outside the repo by construction.

## What relocates vs what stays

The migration copies + rewrites the **runtime data** — the markdown files,
`rnd_registry.json`, `dashboard.html`, `.anchor/` (sessions, per-project stores,
worktrees), `rnd_jobs/`, `logs/`, `health_reports/`, `domains/`. A project's own
`folder_path` (its git repo) and its planning-doc paths **stay put** — only the
paths inside the relocated data subtrees are rewritten
(`tools/path_audit.RELOCATED_SEGMENTS`).

## Run the migration (elevated)

```powershell
powershell -ExecutionPolicy Bypass -File .\migrate_data_dir.ps1 -NewRoot C:\AnchorData
```

Sequence (`migrate_data_dir.ps1` → `tools/migrate_data_dir.py`):

1. `nssm stop anchor` — nothing writes mid-copy.
2. **copy → path-rewrite → verify → arm-reaper** (Python core). The old root is
   never mutated, so it is the rollback source.
3. `nssm set anchor AppEnvironmentExtra "ANCHOR_DATA_DIR=C:\AnchorData"`.
4. `nssm start anchor` — the **first post-move boot sweeps worktrees report-only**
   (`ANCHOR_REAPER_DRYRUN`/the armed `.reaper_dryrun` marker); live reaping
   re-arms only after a clean dry report, so a path-rewrite miss can never delete
   a legit worktree.
5. Healthcheck probe against `http://localhost:8777/`.
6. Old data stores flipped read-only for a ~1-week preservation window.

## Rollback

- **Core failure** (verify fails, copy error): the Python core removes the
  partial new root and exits non-zero; the wrapper restarts the service on the
  **old** data dir — no change shipped.
- **Healthcheck failure** post-cutover: the wrapper clears the NSSM
  `ANCHOR_DATA_DIR` override and restarts on the old dir.
- **Manual**: `nssm stop anchor; nssm set anchor AppEnvironmentExtra "";
  nssm start anchor` — the old (read-only-preserved) dir is intact.

## Audit / hygiene tools (inspection)

```powershell
python tools\path_audit.py C:\AnchorData C:\dev\Anchor C:\AnchorData     # audit (report-only)
python tools\path_audit.py C:\AnchorData C:\dev\Anchor C:\AnchorData --apply
python tools\git_hygiene.py                     # list tracked runtime artifacts
python tools\git_hygiene.py --apply             # git rm --cached them (content kept)
```

Git hygiene is committed as **its own commit** (`git rm --cached` the tracked
runtime artifacts + the `.gitignore` rules). Gate:
`tests/test_data_dir_migration_w11.py` proves a full healthcheck write cycle
leaves `git status --porcelain` empty with runtime writes landing outside the repo.
