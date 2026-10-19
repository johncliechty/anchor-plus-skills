# rnd-v2

*Lane: build · validated, cached summary*

**When run:** 2026-06-11

**What was asked:** rnd-v2

## Actions & files produced

- Anchor R&D Surface v2 — Execution Log

**Effort:** imported — no run metrics

## What was built & errors overcome

- Wave 2 of the rnd-v2 build covered Folder-history unification + reconcile + deliverable pinning, marked GO on 2026-06-11.
- The EXECUTE step added sibling-store adoption via `effort_history.sibling_store_ids` / `adopt_sibling_sessions`.
- It added `rnd_registry.reconcile_folder(active_id, apply=False|True)` implementing preview-then-fold-then-hard-delete, run under WRITE_LOCK, and never touching the active id or different-folder ids.
- It introduced a new `deliverables.py` module with Anchor.md marker parsing and pinning, exposed through `POST /api/rnd/pin_deliverable`.
- Project ids are read from the registry by folder at runtime rather than hard-coded.
- New and extended tests were added: `tests/test_reconcile.py`, plus extensions to `tests/test_deliverables.py` and `tests/test_brownfield_adopt.py`.
- The orchestrator-run GATE passed with 312 passed, 1 skipped, and the live registry was left untouched (hermetic tests).
- Here is a grounded summary of this build session, drawn only from the provided anchors and member document (the *Anchor R&D Surface v2 â€” Execution Log*):
- **rnd-v2 â€” Wave 2: Folder-history unification + reconcile + deliverable pinning**
- **Wave 2 was approved (GO) on 2026-06-11** covering three areas: folder-history unification, folder reconcile, and deliverable pinning.
- **Sibling-store adoption was implemented** in `effort_history.py` via `sibling_store_ids` / `adopt_sibling_sessions`.
- **A reviewable folder-reconcile was added** as `rnd_registry.reconcile_folder(active_id, apply=False|True)` â€” a preview-then-fold-then-hard-delete flow, run entirely under `WRITE_LOCK`, that **never touches the active id or ids belonging to a different folder**.
- **A new `deliverables.py` module was added**, providing `Anchor.md` marker parsing and deliverable pinning, exposed over the new `POST /api/rnd/pin_deliverable` endpoint.
- **Ids are read from the registry by folder at runtime** rather than hard-coded.
- **Test coverage was added/extended**: a new `tests/test_reconcile.py`, plus extensions to `tests/test_deliverables.py` and `tests/test_brownfield_adopt.py`.
- **The orchestrator-run GATE passed: 312 passed, 1 skipped**, with the **live registry left untouched** (the tests are hermetic).

## Files

- [Anchor R&D Surface v2 — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v2%2FEXECUTION-LOG.md)
