# `fixtures/anchor-contract/` — the two-sided shared fixture set (W15)

These bytes are the Anchor contract, written down. They are **shared**: the same files are
consumed by this repository's engine-side test and are handed to the Anchor repository for
its side. Sharing the fixtures rather than describing the contract twice is the point — two
prose descriptions of a schema drift the first time either side ships, and neither side finds
out until an acknowledgement is silently ignored in production.

## The two facts this set keeps apart

`receipt written` and `receipt honored` are different facts.

- The **engine** writes a project file, fsyncs it, and appends a `commit-intent-v1` asking
  that those exact bytes be made durable somewhere that is not this disk. It has no way to
  know whether that happened, and it never invokes a durability tool of its own.
- **Anchor** honours an intent and hands back a `commit-ack-v1`. Until an ack arrives, the
  engine reports the receipt as *state not yet committed* — never as safe.

## What each side owes

| Side | Obligation | Proved by |
| --- | --- | --- |
| Anchor | acknowledge **every** intent in `intents/`, with an ack carrying that intent's exact `sha256` | the Anchor repository's own test, against these files |
| Engine | accept **every** ack in `acks/`, refuse **every** ack in `rejected-acks/` by its named code, and refuse `lineage-refused/` against a log that does not match | `test/w5x-anchor-contract.test.mjs` (green here) |
| Engine | invoke a durability tool zero times | `test/w5x-engine-git-free.test.mjs` (runs in the suite forever) |

## Layout

- `manifest.json` — the index both sides read. Schema `anchor-contract-fixtures-v1`.
- `intents/` — commit-intents Anchor **must** acknowledge. Each file carries the intent and
  the `sha256` of its canonical line, so Anchor never has to re-derive the hashing rule.
- `acks/` — acks the engine **must** accept. Each names the intent file it honours.
- `rejected-acks/` — acks the engine **must** refuse on their own bytes, each with the
  `commit-ack-v1` refusal code it must produce. A contract that only shows the happy path
  cannot tell a strict parser from a permissive one.
- `lineage-refused/` — acks that are perfectly well-formed and still must be refused, because
  they disagree with the log this engine holds. This is the case a schema check cannot catch
  and the one that matters most: an ack matched on `(project_id, intent_seq)` alone would
  mark the wrong receipt safe after a restore-from-backup.

## C7b is open

The engine's half of this contract is closeable in this repository and is closed. The other
half is not here. Every durability surface says so rather than rendering an unacknowledged
portfolio as though the contract were complete.
