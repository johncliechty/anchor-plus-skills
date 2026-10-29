# 0052 — Stream Interruption When Emitting Monolithic Deck Builder Script

- **Date:** 2026-10-26
- **Skill:** `einstein`
- **Job:** `20261026-115413-169715` (`BA 815 Lecture 5 - Refinement 3`)
- **Symptom:** Coder completed `Two-Sample-Sampling-Distribution.html` (37.5 KB) and `lecture5_two_sample.R` (14.7 KB), read the 785-line `build_l5_ref2_deck.py`, and attempted to emit the entire 800+ line `build_l5_ref3_deck.py` in a single `write_file` tool call. The model stream timed out at step 76 (`Error: The stream was interrupted. Please continue the task you were working on.`), leaving the worker idle (`needs_inspection`).
- **Root Cause:** Emitting >45 KB of Python source in one `write_file` call is vulnerable to stream truncation/interruption.
- **Fix / Mitigation:** Stopped and recovered the job in-place (preserving the completed HTML widget and R script in the worktree) and instructed the coder to copy the existing donor builder (`shutil.copy`) and apply modular edits/patches rather than regenerating 800+ lines in a single tool call.
