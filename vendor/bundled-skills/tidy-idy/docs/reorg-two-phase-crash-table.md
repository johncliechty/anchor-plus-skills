# Reorg two-phase apply — crash-at-every-step table

**Status:** REQUIRED design artifact, reviewed with the code (Wave 8). Every row
is instantiated by a named cell in the integration matrix
(`test/apply-reorg.test.mjs`). If a row here has no green test, the wave is not
done.

This table is the normative contract for `engine/apply/reorg.mjs`. It proves the
central safety claim: **a mixed-directory reorg apply resolves to exactly one of
two states — fully-applied or bit-identical — under a crash at ANY point. There
is no third state.**

## The state machine

A reorg move is partitioned per path into content classes and run through an
explicit, code-enforced state machine, every transition appended to the reorg
journal (`.tidy-idy/reorg/<runId>/journal.jsonl`) **fsync-before-act**:

```
apply:  PLANNED → PREFLIGHTED → FS_MOVING(k/n) → FS_DONE → COMMITTED
        → REF_ADVANCED → DONE
undo:   UNDO_PLANNED → REVERT_COMMITTED → MOVING_BACK(k/n) → UNDO_DONE
```

- **PLANNED** — the plan is durable: the fs move list, the git move list, the
  target ref, the parent HEAD. Nothing on disk has moved; no tree has been
  written.
- **PREFLIGHTED** — the git half has been compiled into a temp index and a tree
  object written (`write-tree`); the fs half has been preflighted
  (source-present / destination-free / ignorecase). Still **zero** working-tree
  writes: a tree object with no commit pointing at it is unreferenced and
  harmless.
- **FS_MOVING(k/n)** — the journaled fs move-set is running; `k` of `n`
  untracked/non-git files have been moved to their new paths, each with a
  `started`/`done` pair around the rename.
- **FS_DONE** — every fs move landed.
- **COMMITTED** — `commit-tree` produced commit `C` for the pre-computed tree;
  `C` and the target ref are journaled. `C` is **written but not yet
  referenced** — an unreachable object.
- **REF_ADVANCED** — the compare-and-swap `update-ref <ref> C <oldHead>`
  succeeded: `C` is now the branch tip. **This is the point the commit "lands."**
- **DONE** — the working tree has been realized (`checkout --no-overlay`) and the
  move is complete.

## The recovery rule (one state + one git fact)

On retry, `recoverReorgApply` reads the last durable journal state and asks **one
observable git question: is the journaled commit sha `C` at the journaled ref
(or reachable from it)?**

- **`C` is at/under the ref → the commit LANDED → ROLL FORWARD.** Complete any
  outstanding fs move (idempotently — a rename that already happened is
  reconciled from its `started` record and the on-disk fact), realize the working
  tree, seal `DONE`. Result: **fully-applied.**
- **No COMMITTED record, or `C` is NOT at the ref → the commit did NOT land →
  ROLL BACK.** Move every completed fs move back to its source (no-clobber
  guarded), leaving the tree **bit-identical**; nothing is committed (an
  unreferenced `C`, if any, is harmless and collectable).

Because the fs half runs **before** the commit, and the pivot is the single fact
"did the commit land", there is no reachable interleaving that leaves content
lost or duplicated.

## Crash-at-every-step table

`fs(k)` = k of n fs moves are on disk at their new path. `C?` = the commit object
may exist but is unreferenced.

| # | Last durable state | What a crash there leaves on disk / in git | `C` at ref? | Recovery decision | Terminal state | Named test |
|---|---|---|---|---|---|---|
| 1 | PLANNED | nothing moved; no tree, no commit | n/a | ROLL BACK (no-op) | bit-identical | `crash@PLANNED rolls back to bit-identical` |
| 2 | PREFLIGHTED | temp-index tree written (unreferenced); nothing on disk moved | n/a | ROLL BACK (no-op; tree object orphaned) | bit-identical | `crash@PREFLIGHTED rolls back to bit-identical` |
| 3 | FS_MOVING(k/n) | k fs files at new paths, n−k at old; no commit | no | ROLL BACK the k completed moves | bit-identical | `crash@FS_MOVING rolls completed fs moves back` |
| 4 | FS_MOVING(k/n), `done` record lost after rename | k+1 files physically moved but only k recorded | no | reconcile the torn move, then ROLL BACK all | bit-identical | `crash@FS_MOVING with torn journal reconciles then rolls back` |
| 5 | FS_DONE | all fs files at new paths; no commit | no | ROLL BACK all fs moves | bit-identical | `crash@FS_DONE rolls the whole fs half back` |
| 6 | COMMITTED (ref NOT advanced) | all fs files at new paths; `C` written, unreferenced | no | ROLL BACK all fs moves; `C` orphaned | bit-identical | `crash@COMMITTED before ref rolls back bit-identical` |
| 7 | COMMITTED then ref advanced, REF_ADVANCED record lost | all fs at new paths; `C` **is** the branch tip | yes | ROLL FORWARD: realize, seal DONE | fully-applied | `crash@COMMITTED after ref (record lost) rolls forward` |
| 8 | REF_ADVANCED (realization pending) | `C` is branch tip; working tree maybe not realized | yes | ROLL FORWARD: finish realization, seal DONE | fully-applied | `crash@REF_ADVANCED rolls forward to fully-applied` |
| 9 | REF_ADVANCED, one fs `done` record lost (defensive) | `C` is tip; one fs file still at old path | yes | ROLL FORWARD: complete the outstanding fs move | fully-applied | `crash after commit lands, fs incomplete, rolls forward` |
| 10 | DONE | fully applied | yes | none (already DONE) | fully-applied | `crash@DONE is a no-op` |

Rows 7 and 9 are the concrete forms of the acceptance criterion "killed after the
commit lands but before the fs move-set completes → rolls the fs half FORWARD to
fully-applied, no file lost and none duplicated." Rows 3–6 are "a kill BEFORE the
commit rolls completed fs moves back, tree bit-identical, nothing committed."

## Undo (of a completed apply)

Undo is one journaled unit with the same crash-resume discipline:

| Last undo state | Crash leaves | Recovery |
|---|---|---|
| UNDO_PLANNED | nothing reverted, nothing moved back | re-run undo from the top (idempotent) |
| REVERT_COMMITTED | revert commit on the branch; no fs move-back yet | resume the journaled move-back |
| MOVING_BACK(k/n) | k of n files back at their original paths | complete the remaining move-backs (no-clobber guarded; an occupied original refuses that one, restores the rest) |
| UNDO_DONE | fully undone | no-op |

Each move-back destination is guarded by the Wave-3 no-clobber invariant
(`checkPathAgainstExpectation({ expected: { exists: false } })`): a reoccupied or
edited original path REFUSES that one move-back rather than overwrite it, and the
rest still restore.

## Invariants asserted alongside every row

- **Approving a Move never changes a path's tracking class.** The fs half issues
  NO `git add`, NO index write, NO `.gitignore` write; an untracked file is
  untracked at its new path, asserted by the consent-scope porcelain-class diff
  (`result.consentScope.ok === true`, and `git status --porcelain=v2` class
  unchanged pre/post).
- **Case-colliding targets are refused** in both executors via the ignorecase
  probe (git `core.ignorecase`, or the platform default when there is no repo).
- **Every transition is fsync-before-act**, so a crash never yields an act with
  no record; it may yield a record with no act, which recovery reconciles.
