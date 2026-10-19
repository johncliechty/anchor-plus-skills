-- W7 — Phase 2: cost_state enum + migration + dollar-fabrication ban
-- Additive nullable column + backfill existing rows to unmeasured
-- (never to measured-zero). Partial-migration / NULL / absent column
-- fail closed to measurement_failed at read time (anchor/cost/read_cost_state.py).
--
-- Paths are relative to the stage2 containment root. No absolute host paths.
-- Feature-flagged off for v1.1.x collaborators per shared-artifact ledger.

-- ---------------------------------------------------------------------------
-- 1. Schema: additive nullable cost_state on session / cost event rows
-- ---------------------------------------------------------------------------

-- Sessions (primary surface for per-session cost chrome).
ALTER TABLE sessions ADD COLUMN cost_state TEXT NULL;

-- Cost event ledger used by dashboard / workbench rollups (when present).
-- Safe no-op on engines that only carry sessions; apply only if table exists.
-- ALTER TABLE cost_events ADD COLUMN cost_state TEXT NULL;

-- Optional check constraint (SQLite 3.37+ / Postgres) — known tokens only.
-- Uncomment when the target dialect supports ADD CONSTRAINT on existing tables:
-- ALTER TABLE sessions ADD CONSTRAINT sessions_cost_state_known
--   CHECK (
--     cost_state IS NULL
--     OR cost_state IN (
--       'subscription_covered',
--       'measured',
--       'unmeasured',
--       'measurement_failed'
--     )
--   );

-- ---------------------------------------------------------------------------
-- 2. Backfill: existing rows → unmeasured (NOT measured-zero)
-- ---------------------------------------------------------------------------
-- Historical rows lack a proven measurement classification. Mapping them to
-- measured with amount 0 would fabricate a dollar fact. Map to unmeasured so
-- render_cost shows the labelled unmeasured state, never $0.00, never
-- (subscription).

UPDATE sessions
SET cost_state = 'unmeasured'
WHERE cost_state IS NULL;

-- UPDATE cost_events
-- SET cost_state = 'unmeasured'
-- WHERE cost_state IS NULL;

-- ---------------------------------------------------------------------------
-- 3. Notes for deployers
-- ---------------------------------------------------------------------------
-- * Mid-deploy (column not yet present on a replica): read_cost_state resolves
--   every affected row to measurement_failed — visible failure, no $ figure,
--   no (subscription).
-- * After this migration commits, remaining NULL values still fail closed to
--   measurement_failed at read time until backfill is complete.
-- * Do not backfill to 'measured' solely because cost = 0.
