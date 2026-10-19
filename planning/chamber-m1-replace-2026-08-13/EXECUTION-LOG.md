# Execution log — make M1 survive, wire talk, delete v0 (Foreman)

Two waves. W1 stops the delete and wires the say box; W2 deletes v0 in both trees.
Then a human-eyes gate: John opens the steward and confirms it changed.

Plan revision 3 — the scope John corrected after rejecting the v0 parity map.
Seats: Fable 5 on execute/fix, Grok on review/judge (cross-family).

(Foreman appends per-wave entries here.)
- 2026-08-14T03:55:35.875Z — Wave 1/2 GREEN — Stop the delete, wire talk (gate exit 0 · tests 1146 pass 1146 fail 0 · iter 2; appended by orchestrator on GO)
- 2026-08-14T16:5x — Wave 2/2 GREEN — Delete v0, in both trees. **Finished BY
  HAND, not by the orchestrator**, and the record should say so plainly.
  W2's execute agent wrote the deletions between 22:41 and 22:44 on 08-13 and
  then died: last heartbeat 22:44, engine pid 44912 gone, no verdict, no
  commit — the third engine death on this two-wave build (21:21 external kill,
  22:22 external kill, 22:44 cause unknown). It left the tree in the one state
  the plan most wanted to avoid: v0 deleted in Anchor, v0 still DEMANDED by two
  Ecgberht canaries, and the replacement guard referenced twice in shipped
  comments but never created.
  Completed by hand on 08-14: the guard (tests/test_chamber_v0_is_gone_w2.py,
  11 rows, by-name AND by-tree, with negative proofs on both halves), the two
  w14 canaries retargeted onto M1's drawn state, w11's v0 render-order rows
  retired, and one genuine gate red fixed — test_self_service_token's steward
  POST list still named `speak`/`stand_up`, whose only call sites lived inside
  the deleted renderers; retargeted onto M1's mutating set (converse,
  refine_confirm, deliverable_action, high_seat_act), all four header-authed.
  GATE (ground truth, run twice — the first run is what caught the token-list
  red): anchor-pytest exit 0, 3210 passed / 13 skipped / 62 deselected;
  ecgberht-lane exit 0, 1146/1146. Human-eyes gate still OPEN: John has not
  yet opened the steward himself.
