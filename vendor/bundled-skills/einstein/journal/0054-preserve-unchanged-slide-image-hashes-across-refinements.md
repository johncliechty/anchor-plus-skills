# 0054 — Preserve Unchanged Slide Image Hashes When Refining an Existing Deck

- **Date:** 2026-10-27
- **Skill:** einstein
- **Job:** 20261027-125532-5d8b74 (Stage: made → checked → review blocked (fail))

## Friction Observed
When building Lecture 5 - Refinement 4 (39 slides) from Lecture 5 - Refinement 3 (40 slides), the cross-family reviewer (claude-fable-5-1) blocked landing on two issues:
1. **Unintended Overwrite of Unchanged Summary Figures (MAJOR):** The modular figure script gen_figs_part5.py regenerated ig_36_summary1.png (Slide 36, requested in the brief) AND also ran older code blocks at the bottom of gen_figs_part5.py that overwrote ig_38_summary3.png (Slide 38) and ig_39_retrieval_check.png (Slide 39) with an earlier draft's wording.
2. **Runtime Patch Instead of Persistent SLIDES_SPEC Edit (MINOR):** The worker patched SLIDES_SPEC at runtime via a temporary script that was deleted before completion, leaving uild_l5_ref2_deck.py on disk with 40 entries while asserting len(SLIDES_SPEC) == 39.

## Lesson & Guardrail
1. When refining specific slides of an existing .pptx deck, extract the embedded PNG blobs from the prior accepted/current .pptx for all unchanged slides, and assert in --check (erify_l5_ref4.py) that sha256(slide_image_blob) matches the prior deck on every unchanged slide index.
2. Commit slide-list edits directly into SLIDES_SPEC in the persistent builder script rather than applying ephemeral runtime monkey-patches.

## Addendum (20261027-133432-3ae2e2 Package Version Sync & Question-Scope Guardrail)
- When revising a single question on an Answer Sheet and Instructor Answer Key that are re-bundled into a Student Package ZIP alongside earlier Illustrated Instructions/AI Companion files, always (1) update START HERE.txt inside the ZIP to reference the new Answer Sheet revision filename, (2) explicitly note on the Answer Sheet, START HERE.txt, and Instructor Answer Key that the simplified question format supersedes any show-your-work note in the unchanged companion documents, and (3) preserve all unrequested question answers (5b) verbatim from the prior revision.
