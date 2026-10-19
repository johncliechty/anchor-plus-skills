
## Stage-1 triage — parked (out-of-scope; revisit if the North Star is amended)

- Weekly cost digest email/notification summarizing per-project measured spend and capture rate. — Reporting cadence/notification is a new surface; no criterion asks for push reporting — the rollup + dashboard stamp cover the honesty goal.
- Per-session cost BUDGETS with a warn/park threshold (auto-park a session that crosses N tokens). — Enforcement/limits is a different feature; the North Star is measurement honesty, not spend control. Park in Grasscatcher — it becomes cheap once the ledger exists.
- Cross-project cost analytics view (trend charts, per-lane spend over time, engine mix). — Analytics beyond the existing rollup window (lifetime/30d) traces to no criterion; the ledger makes it a later render-only feature.
- Export the usage ledger as CSV for external accounting. — No criterion mentions export; trivially buildable later off the append-only ledger.
- Retention policy for .anchor/ usage snapshots (compaction of old ledger lines into per-session totals after M months). — Premature: snapshot volume is tiny JSON; add compaction only if the store measurably grows. Grasscatcher with the receipt that FM-03 argues for MORE retention, not less, right now.
