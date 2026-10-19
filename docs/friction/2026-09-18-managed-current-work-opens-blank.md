# Managed Current work opens a blank window, then nothing

John, MBA Teaching AI, 18 September 2026, durable turn 597bbef5-8068-4f01-a621-491ba4285620:

> Also, I am trying to open the AI suppleent course outline Rfiement 8 and the link does not open to anything. This has happened multiple time, please fix this as well as journal about it.

This is the same mechanism as `2026-09-14-01-managed-lecture-pdf-button-times-out-whi`. The Current work control for a managed product (`it.managed && it.presentation_id`) called `window.open("about:blank")`, then `POST /api/refinement-open` to record a view through the refinement CLI. On this campaign that write often exceeds the 20s timeout plus reconcile (~40s). The catch path then called `preview.close()`, so John saw nothing. A working named-file row or conversation PDF link is not that control.

Installed repair in `steward_cockpit/static/shared.js`: navigate to the already-hashed deliverable-file URL first. If viewing is not recorded, leave the document open and note that fact. Do not close the window.

Proof:

- Source order: `preview.location` is assigned before `await post`; `preview.close()` is gone from the managed handler.
- Isolated browser: `tests/test_cockpit_selected_b.py` still records a successful view, and a new test opens the file when `update` returns `dependency-slow-or-killed`.
- Live MBA steward/v1, 2026-09-18: Current work Refinement 10 (110306 bytes) and history Refinement 8 (36489 bytes) matched frozen hashes and survived reload. Receipts in the MBA campaign `.ecgberht/outline-open-20260918/`.

The slow view write itself is not sped up. Recording can still fail; the document must still open. Keep the September 14 record open until John confirms the click on his screen. No teaching slice was closed.
