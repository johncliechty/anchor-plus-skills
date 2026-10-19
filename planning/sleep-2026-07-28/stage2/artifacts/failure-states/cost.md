# Cost failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W13 — Phase 3: Cost surfacing from cost_state (never a fabricated dollar)
Surface: `cost`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (tile render / cost). Doctor-tile hygiene vocabulary
and index / rebuild / reconcile language are honesty theater on this tile and
must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081). **unmeasured** and
**measurement_failed** are also SEPARATE rows on this surface.

Every dollar figure derives from ``cost_state == measured`` via
``render_cost`` only. Unmeasured engines show a labelled unmeasured state —
never blank, never ``$0.00``. A failed measurement shows measurement_failed
rather than a number under a disclaimer. E2 is illegal for dollars.

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | pending | pending | cost aggregator absent (NO_AGGREGATOR) — tile render shows pending naming the aggregation wave it awaits; no dollar figure |
| dependency-slow-or-killed | timeout | timeout | cost rollup dependency slow or killed during tile render |
| dependency-returns-garbage | measurement_failed | measurement_failed | cost aggregation raised at read time, spot-check disagreement, or garbage payload — tile render shows measurement_failed; never a dollar figure under a disclaimer |
| dependency-returns-garbage | unmeasured | unmeasured | engine has no cost instrumentation — tile render / session chrome shows labelled unmeasured; never blank, never $0.00 |
| backing-store-unreadable | unknown | unknown | cost store unreadable or cost query failed — tile render shows unknown; never empty, never a dollar figure |
| empty-but-valid | empty | empty | cost scope legitimately empty — tile render: nothing was ever in scope (no cost events) |
| empty-but-valid | zero_measured | zero_measured | cost measured successfully over existing scope; total is $0.00 under cost_state == measured only |

## Surface × cost_state matrix (handler)

| surface | condition | rendered | dollar figure | notes |
|---------|-----------|----------|---------------|-------|
| session_chrome | engine uninstrumented | unmeasured | none | labelled unmeasured; never blank; never $0.00 |
| dashboard | aggregation raises at read time | measurement_failed | none | no E2 provisional dollars accepted by exit register |
| dashboard | cost_state == measured | $X.XX | yes (via render_cost only) | only path that may emit a dollar figure |
| any | cost_state == subscription_covered | (subscription) | none | label from enum, never from amount == 0 |
| any | cost_state == unmeasured | unmeasured | none | never (subscription), never $0.00 |
| any | cost_state == measurement_failed | measurement_failed | none | fail-closed mid-deploy / wrong figure |
| any | store unreadable | unknown | none | unknown ≠ empty |
| any | empty cost scope | empty | none | empty ≠ unknown |

## E2 ban (dollars)

* E2 is **illegal for dollars** — cost surfaces use measurement_failed (W2/W7/W13).
* Any attempt to sign E2 against a cost tile is refused by the exit register
  with the verbatim message that E2 does not apply to dollars.
* Fabricating a dollar figure under a "provisional" disclaimer is still
  fabricating dollars.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a zero, never a dollar).
* `dependency-returns-garbage` → **measurement_failed** and **unmeasured** as separate rows.
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* `$0.00` is a fact only under `cost_state == measured` via `render_cost`.
* Tile render is the surface action vocabulary (dashboard / workbench / session chrome).
* `zero_inference_lint` is a gate on this surface — no `cost == 0 → (subscription)`.
