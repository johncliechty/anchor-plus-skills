# brownfield-discovery

*Lane: build · validated, cached summary*

**When run:** 2026-06-10

**What was asked:** brownfield-discovery

## Actions & files produced

- foreman.config

**Effort:** imported — no run metrics

## What was built & errors overcome

- **Wave structure** â€” Scoped to **7 waves**, with Wave 3 split into **3a** (render-honesty) and **3b** (file-route / status-line / home-panel).
- **Stdlib-only constraint** â€” Product code must stay Python-stdlib-only; `pytest` is a dev-only dependency.
- **Regression guard** â€” The pre-existing **236-test suite** must stay green, specifically `test_cost_rollup.py`'s 3/2/1 `effort_count` asserts and `test_rnd_project_window_kanban.py`'s `>v2<`/`>v1<` asserts.
- **Discovered-effort honesty** â€” Discovered efforts carry `source='discovered'`, are excluded from `effort_count`/cost, never fabricate cost/tokens/`session_id`, and are pruned on rescan when their artifact is gone.
- **Traversal-safe artifact route** â€” The new `GET /artifact/<pid>?path=` route must use the `report_viewer.katex_asset` `resolve()` + `relative_to()` containment pattern, with required negative tests (`../`, absolute, `.git`/`.anchor`, symlink-escape).
- **Write discipline** â€” All file writes (`Anchor.md`, sidecar, adopt records) go under `paths.WRITE_LOCK`.
- **Service isolation** â€” The build must never touch the live Anchor service / port 8777; tests use throwaway servers plus `ANCHOR_RUNNER_CMD` â†’ `tests/fake_claude.py`.

## Files

- [foreman.config](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2Fforeman.config.json)
