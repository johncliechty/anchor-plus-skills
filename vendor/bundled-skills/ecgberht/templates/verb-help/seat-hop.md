# Verb: seat-hop

**Closed list:** yes · **Primary:** seat-hop

Switch the steward seat (claude/gemini/grok) — a NON-EVENT with a receipt.

- `seat_hop` receipt carries who/when/from→to; the ledger is the transition document.
- Wired to Anchor prefs: the selected family persists as `default_cli` (subscription driver) + `seat_family`; the titlebar switcher calls this same path (CLI parity).
- No re-brief: the next turn continues from Face / Strip / Roadmap / cached packet — never from chat history (dialogue is ephemeral, no durable chat ledger).
- Seat names are families only, never product model IDs.

Usage: `node bin/ecgberht.mjs seat-hop --seat <claude|gemini|grok> --who <name> [--when <iso>]`

TW4. Module: `engine/seat-hop.mjs` · receipt schema: `schema/receipt.schema.json` (`seat_hop`).
