# W1 — Wave-0 Closed-World Test Audit (v4 rollup + v8 persist)

> Every assertion in the existing v4-rollup and v8-persist suites classified
> **additive-compatible** vs **legitimately superseded**, so no wave improvises a
> rewrite later. Serves criteria (2), (3). Cited by the North Star amendment's
> honesty-contract clause and by W5 (Rollup Honesty).

## The closed-world seam

The whole audit rests on one seam: **`ANCHOR_SIDECAR_DIR` is UNSET in every legacy
fixture**, so the new usage-capture source is **OFF by default** for every existing
test. W2 makes this structural — the fail-closed sidecar-root resolver RAISES under
test/healthcheck mode unless `ANCHOR_SIDECAR_DIR` is explicitly set — so a legacy
test can never accidentally pick up a real or fake sidecar. Therefore, for the
overwhelming majority of assertions, the new cost path contributes nothing and the
test is **additive-compatible** (stays green, unmodified).

The honesty contract the legacy suites already pin — **discovered/imported efforts
contribute exactly 0**, run cost is summed only from RUN-provenance sessions
(`effort_history.project_effort_rollup`, `sessions.PROV_RUN`) — is PRESERVED and
EXTENDED (not weakened) by this plan: the new RUN cost record coexists with a
session's persisted `source=discovered` docs and is deduped by `session_id` (W5), so
the "discovered contributes 0" tests remain true.

## Additive-compatible (stay green, UNMODIFIED)

- **`tests/test_effort_rollup.py`** — `test_lifetime_sums_run_sessions`,
  `test_30d_excludes_old_records`, `test_30d_boundary_inclusive`,
  `test_imported_sessions_contribute_zero`, `test_empty_project_zero`,
  `test_folder_path_resolved_from_registry`: assert specific fields
  (`out["tokens"]`, `out["sessions"]`) by subscript over hand-built RUN/imported
  fixtures with no sidecar. The new source is off; the run-vs-imported honesty they
  pin is exactly what W5 extends. **Additive-compatible.**
- **`tests/test_cost_rollup.py`** — all five (`…result_envelope_captured…`,
  `…cost_stored_on_effort_and_rolled_up…`, the three auto-commit tests): exercise
  the one-shot `-p` RESULT-envelope cost path + per-effort git auto-commit. This is
  the SAME ledger sink W4 unifies the interactive path into, keyed by engine session
  UUID; the existing job-cost assertions keep holding (no sidecar in these
  fixtures). **Additive-compatible.**
- **`tests/test_doc_persistence_v8.py`** (all 7) and **`tests/test_no_loss_lifecycle_v8.py`**
  (all 6): about persisting trio docs to main before reap. Orthogonal to the cost
  source — persisted docs are `source=discovered` (contribute 0); the new RUN cost
  record is a SEPARATE effort deduped by `session_id`. No sidecar fires in these
  stub fixtures. **Additive-compatible.** (W5's dedup test is a NEW test that pins
  the coexistence; it does not modify these.)
- **`tests/test_cli_v8.py`** (all 14) and the non-rollup **`tests/test_cli_v4.py`**
  tests (`…doc_roles…`, `…deliverable_type…`, `…engine…`, `…unknown_project…`):
  inspect remote-link / persisted-docs / doc-roles / engine surfaces — no rollup
  shape dependency. **Additive-compatible.**

## Legitimately superseded (exactly TWO — exact-shape assertions)

These two assert the rollup return value by **exact set/dict equality**, so they
break the moment W5 surfaces the three honesty states (measured / unmeasured(reason)
/ capture-failed) or the capture-rate stamp on the rollup structure. They are the
ONLY assertions in scope that a faithful implementation of criteria (2)/(3) can
legitimately supersede:

1. **`tests/test_cli_v4.py::test_cli_rollup_shape_and_delegates`** — line 88:
   `assert set(roll.keys()) == {"tokens", "cost_usd", "wall_clock_ms", "sessions"}`.
   An exact key-set assertion; **SUPERSEDED** if the rollup dict gains honesty-state
   keys.
2. **`tests/test_effort_rollup.py::test_zero_when_no_run_metrics`** — line 150:
   `assert out == {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 0}`.
   Exact dict equality; **SUPERSEDED** if the dict grows keys. (Its underlying
   truth — discovered-only ⇒ zero measured cost — MUST still hold and be re-pinned
   in the updated assertion.)

### Preferred implementation path (keeps even these two green)

W5 should prefer surfacing the three-state model + capture-rate via a **sibling
structure** (a separate `rollup_honesty(...)` projection / added dashboard fields)
rather than mutating `project_effort_rollup`'s return dict in place. If that path is
taken, BOTH tests above stay green unmodified and the "superseded" count is **0**.
They are flagged here as the two to watch: only if W5 extends the core rollup dict
in place are they superseded — and then only by updating the exact-shape assertion
to the new shape while re-asserting the discovered-contributes-0 invariant, never by
deleting or weakening it. No other legacy assertion may be touched.
