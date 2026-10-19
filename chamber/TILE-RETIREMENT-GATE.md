# W12 tile-retirement parity gate — UNSIGNED

**Signed by:** (awaiting John — rail+STATUS parity signature, C11)
**Prepared:** steward-chamber W12 (Phase-4 Close)
**Inventory of record:** `chamber/tile-affordance-inventory.json` (schema v1, owner `chamber_status_overlay.py`)
**Gate code:** `chamber_retirement.py :: retirement_allowed` — the ONE callable retirement must cross; it refuses by name while this record stands UNSIGNED.

## Law (from the plan, C11, restated)

The bottom run tiles are removed ONLY after this map resolves EVERY row to a
live rail/STATUS equivalent or a John-signed accepted loss, AND rail+STATUS
parity is SIGNED. No tile code is deleted before the signature. W12 lands
the gate and this record; **John's signature is recorded here** (and
`signed_by_john: true` in the inventory) when he rules — both must agree or
the gate fails closed.

## Row resolutions at the W12 audit

| Row | Kind | W12 state |
|-----|------|-----------|
| ambient-runs-line | equivalent | RESOLVED — live target marker `run-now` verified in `chamber_rail.py` |
| run-report-read | equivalent | RESOLVED — live target marker `report ▸` verified in `chamber_rail.py` |
| historical-runs | equivalent | RESOLVED — live target marker `class="fstep done"` verified in `chamber_rail.py` |
| full-transcript-log-link | proposed-equivalent | **PENDING JOHN** — see decision 1 below |
| open-live-session | equivalent | RESOLVED — live target marker `data-open-session` verified in `chamber_rail.py` |
| kill-control | equivalent | RESOLVED — `function killPanel` lives on the surviving session-panel surface |
| dismiss-finished-tile | proposed-loss | **PENDING JOHN** — see decision 3 below |
| rearm-watch | proposed-equivalent | **PENDING JOHN** — see decision 2 below; the W9 re-arm claim was audited and is NOT yet wired |

Every `equivalent` row's source AND target markers are re-verified
mechanically by `chamber_status_overlay.tile_affordance_problems` (re-run in
`tests/test_chamber_retirement_w12.py`); a vanished marker fails CI by row
name.

## The three decisions John rules on at signing

1. **full-transcript-log-link.** The transcript data is durable
   (`general/<session>-transcript.md`, served by the traversal-safe
   `/artifact` route) — only the one-click link would retire with the tile.
   The signed M1 mockup has no transcript link on the runcard links row, so
   surfacing one requires a mockup amendment through the W1 batched gate
   (C9). **Either** order that amendment (row becomes `equivalent`) **or**
   sign the absent link as an accepted loss (`john_ruling: accepted-loss`).
2. **rearm-watch.** Audited against the landed W10 queue: resolving a gate
   card does **not** invoke `commission_session.rearm_watch` — the tile's
   "Hand it back" / "Keep watching" control is still the only re-arm
   surface. **Either** keep that tile control standing (exclude it from
   retirement until a wired queue-card re-arm lands via amendment) **or**
   sign the lost one-click re-arm as an accepted loss.
3. **dismiss-finished-tile.** Presentation-only; the rail is state-derived
   (done steps fold into the flow; STATUS lists only what remains) and no
   data was ever destroyed by dismiss. Proposed accepted loss.

## Effect while unsigned

Retirement is REFUSED (`W12-TILE-RETIREMENT-UNSIGNED` /
`W12-TILE-ROWS-UNRESOLVED`), every tile source marker must remain present in
the tile code (checked in CI), and the bottom tiles keep rendering. Signing
records **Signed by:** John with the date on the first line block above,
flips `signed_by_john` in the inventory, and records a `john_ruling` on each
pending row — only then does `retirement_allowed` answer true.

## John's rulings (recorded as given, 2026-08-11)

| Decision | Ruling | Effect |
|---|---|---|
| 1. full-transcript-log-link | **AMENDMENT ORDERED** | Draw a transcript link onto the rail runcard's links row and route it through the W1 batched amendment gate; John re-signs and the new markup hash is re-pinned for C9. The row becomes `equivalent` ONLY when that lands — until then it still blocks retirement and the tile stands. Recorded in `chamber/tile-affordance-inventory.json` as `john_ruling: amendment-ordered`. |
| 2. rearm-watch | **TILE CONTROL KEPT** | Excluded from retirement. The audit disproved W9's equivalence claim (resolving a gate card does not invoke `commission_session.rearm_watch`), so the tile's 'Hand it back / Keep watching' control is the only re-arm surface and survives the sweep. It may retire only after a wired queue-card re-arm lands through the amendment gate and verifies at its seam. Recorded as `john_ruling: excluded-from-retirement`. |
| 3. dismiss-finished-tile | **DEFERRED — John inspects first** | John wants to see the chamber's project archive/put-away path in the live UI before signing this loss. Scope clarified at the signing: this row is ONLY the per-run `x` hide in the runs strip (an in-memory browser flag that does not survive a reload) — NOT project archival, which lives in `rnd_registry.py` (archive/retire/future/reactivate, RETAINED-not-deleted, C7) and is untouched by this plan. Recorded as `john_ruling: deferred-pending-inspection`. |

All three rows are now ruled or deferred, but decision 3 is DEFERRED rather than
signed, so the gate stays UNSIGNED and `chamber_retirement.retirement_allowed`
continues to refuse by name. No tile code has been deleted.

**Blocking John's inspection:** the live `anchor` service is running PRE-CHAMBER
code (probed 2026-08-11: `/api/ecgberht/status_overlay` -> 404 while
`/api/rnd/projects` -> 200). The chamber cannot be seen until the service is
restarted onto this branch's code, which needs an elevated restart John runs.
