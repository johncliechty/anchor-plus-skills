# Saved Active and On deck placements disappear before rendering

Observed while fulfilling John's Campaign turn `1b7fce55-80ce-4e86-8799-29e2252e6b6a`: put Artificial Magi, AI Club and MBA Teaching in Active. The existing roadmap writer saved three seat=active components with seat_order 0, 1, 2. All project references resolve. The actual /high-seat page returned HTTP 200 and showed Active 0 both initially and after reload.

Root cause: steward_cockpit/steward_campaign.py read_map rebuilt the projected steps without seat or seat_order. The High Seat renderer received no placements. Reproduced with the production read_map -> resolve_parts -> campaign_initiatives -> seated chain. Browser caching is not the cause.

Correction: preserve the two fields in the existing reader. A focused regression reads a stored roadmap, resolves project references, renders both shelves, repeats the read, and asserts order and membership without modifying the roadmap. No new task store, write path or priority change.

Deployment remains separate from saved code. Preserve running sessions and unfinished work; do not restart the shared Anchor process during productive turns. After safe activation, verify the live page shows the exact three Active cards in John's order, inspect their cockpit targets and effort labels, reload/reopen, and confirm On deck remains empty until John chooses additions.

Campaign evidence and handling: C:/dev/Campaign/journal/0002-active-cockpits-2026-09-30.md. This is an agent-observed failure during authorized work; John did not have to report it.
