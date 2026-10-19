# W14 — Journal Parity Gate + Recovery & Replay Runbook (C3)

> Rearchitecture 2026-07, Wave 16 (W14). Closes C3's proof obligations: a
> quiescent classifying parity gate (tests + healthcheck), and the
> recover-by-construction tooling that is the operational answer when the gate
> reports a divergence.

## What C3 guarantees

Every **mutation of record** dual-writes: a schema-validated **journal** event
FIRST (`journal.emit` via the blessed `journaled`/`dual_write` wrappers), then
the **legacy store** write (`sessions.json`, a lane's `index.json`, …). Because
the journal is written first, the derived legacy layers are **recoverable-by-
construction**: anything they hold that the journal carries can be re-derived
from the journal.

## The parity gate — `parity.py`

`parity.classify_parity(project_id, folder_path=None, tail_window=0)` snapshots
the per-project journal + the legacy stores **under `paths.WRITE_LOCK`** (one
consistent instant), derives a **session view** and an **effort view** from
each, and classifies every divergence:

| Class | Meaning | Severity | Operator action |
|-------|---------|----------|-----------------|
| `journal-ahead` | in the journal, absent from the legacy store | **ok** (crash residue; journal-first) | `replay` — converge the store to the journal |
| `legacy-ahead` | in the legacy store, absent from the journal | **bug** | `investigate` — a store was mutated without its journal event (a completeness violation); NEVER auto-reconciled |
| `conflict` | in both, differing state | **bug** | `investigate` |

**Bounded tail window.** A journal-ahead row whose seq is within the last
`tail_window` seqs is a legitimate in-flight dual-write at the tip and is
tolerated. The quiescent gate (healthcheck + tests) runs at `tail_window=0`:
every dual-write has settled, so a clean project reports **zero divergence**.

**Scope (honest).** The effort-view parity + rebuild cover the **grass** lane
index and the **session** rows — the mutation classes whose W13 journal events
carry the record identity in their payload. Other effort lanes' `doc-persisted`
events are lane-granular only, so their `index.json` is recovered from the
surviving per-effort **pointer-records** instead (see below). The gate never
mis-flags a legitimately-journaled non-grass mutation as `legacy-ahead`.

## When the gate reports a divergence

### Step 1 — read the reconcile report (read-only, mutates nothing)

```
python -m tools.replay_journal <project_id> [--folder <path>]
```

It prints the classified divergences and a recommended `action` per row
(`replay` for journal-ahead, `investigate` for legacy-ahead/conflict), plus a
`replayable` / `investigate` split. Nothing is written.

### Step 2 — recover a lost/torn index or session rows (dry-run first)

```
python -m tools.rebuild_index <project_id> [--folder <path>]           # dry-run
python -m tools.rebuild_index <project_id> [--folder <path>] --apply   # write
```

- **grass `index.json`** is rebuilt **from the journal** (the ordered idea/job
  ids the add/promote events created, minus the deleted ones).
- the **other effort lanes' `index.json`** are rebuilt **from their surviving
  pointer-records** (`efforts/*.pointer.json`, ordered by `created_at`).
- **`sessions.json` rows** are re-materialized **from the journal** and MERGED
  into the global store — a missing row is added, a drifted lane/status is
  converged; other projects' rows and non-journal fields (`worktree_path`,
  `branch`, `created_at`) are untouched.

The dry-run prints exactly what it WOULD write. Every rebuild is **idempotent**
— re-running on a consistent store is a no-op.

### Step 3 — converge journal-ahead automatically (idempotent)

```
python -m tools.replay_journal <project_id> [--folder <path>] --apply
```

`replay` converges ONLY the recoverable **journal-ahead** class (via the
rebuild tool). It NEVER deletes or rewrites a `legacy-ahead`/`conflict` row —
those stay in the `investigate` bucket for a human, because the journal is the
one MISSING the event (a completeness bug, not a lost legacy write). Re-run the
reconcile report afterward to confirm the gate reads clean.

### Step 4 — a `legacy-ahead` / `conflict` (a BUG) needs a human

These mean a store was mutated with no paired journal event, or the two disagree
on state. Do **not** paper over it by mutating a store. Find the unpaired write
site (the W13 enforce tripwire, `journal.completeness_gate`, names it
mechanically), fix the instrumentation so the mutation journals, and only then
decide whether the store or the journal is authoritative for the affected row.

## The nightly proof

`anchor_healthcheck.check_journal_parity` runs the gate hermetically every night
(a temp folder + temp data dir; never `:8777` / real data): it drives a
journaled workload, asserts **zero divergence**, DELETES the grass index to
prove the loss is **classified**, then rebuilds from the journal to prove it is
**recovered** — zero divergence again. It joins the 20× nightly pipeline
alongside the W13 completeness-gate and perf-budget walks.
