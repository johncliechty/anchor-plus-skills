# 0053 — Shared-Axis Interactive Widgets Must Scale Histogram Bins by Minimum SE and Match Row Pixel Heights

- **Date:** 2026-10-26
- **Skill:** `einstein`
- **Job:** `20261026-135248-f2964a` (`Stage: made → checked → review blocked (fail)`)

## Friction Observed
When unifying the horizontal axis (`sharedMin..sharedMax`) across three stacked distribution rows in `Two-Sample-Sampling-Distribution.html`, the cross-family reviewer (`claude-fable-5-1`) blocked landing on five points:
1. **Density-Scale Caption Accuracy (`MAJOR`):** Row 1 (`Populations`) is normalized to its own population peak (`popPeak`) so wide population curves remain legible, whereas Rows 2 and 3 (`Sampling Distributions`) share `sePeak`. Claiming Row 3 is on the "same horizontal & density scale as Rows 1–2" over-claimed density equivalence with Row 1.
2. **Row Pixel Height Parity (`MINOR`):** Rows 2 and 3 shared `sePeak` in probability units, but Row 2 used `r2H = 92` while Row 3 used `r3H = 94` (a 2% pixel height discrepancy).
3. **Zero-Difference Label Collision on Wide Shared Axis (`MINOR`):** Unifying the horizontal axis compressed `|px0 - pxDiff|` below `95px` for default presets, hiding the `"0 (No Diff)"` text label.
4. **Histogram Bin Count on Wide Shared Axis (`MINOR`):** Keeping a fixed 90 bins across a wide shared domain (`-5..194` for Warehouse) left only 5–7 non-empty bins inside the narrower sampling distributions.
5. **LF Line-Ending Preservation (`MINOR`):** `Student-teaching-aids-Two-Sample.html` carries `-text` in `.gitattributes`, so writing CRLF caused a full-file diff against its LF index entry.

## Lesson & Guardrail
1. In multi-row teaching widgets with a shared domain `sharedMin..sharedMax`:
   - State accurately that all three rows share the **horizontal scale** (`sharedMin..sharedMax`) and Rows 2–3 share the **sampling-distribution density scale** (`sePeak`) with identical pixel height (`r2H = r3H = 92`).
   - Compute histogram bin counts dynamically from the narrowest standard error: `binsCount = Math.min(400, Math.max(90, Math.ceil((sharedMax - sharedMin) / (Math.min(se1, se2, seDiff) / 3))))`.
   - Always render the `"0 (No Diff)"` label, offsetting it vertically when `|px0 - pxDiff| < 95` instead of suppressing it.
   - Write all HTML deliverables with explicit `newline='\n'` (LF) so `-text` files in `.gitattributes` produce minimal diffs.

## Addendum (`20261026-140733-678173` Check Path Guardrail)
- External verification scripts passed to `--check` run with their working directory set to the job worktree (`<path><job-id>`). Never hardcode `REPO = r"<path> Teaching AI"` inside a `--check` script; always use `REPO = os.getcwd()` so the check inspects the worktree's output files rather than the main repository checkout. Recovered `20261026-140733-678173` in place via `steward_code_job.py recover`.

## Addendum 2 (`20261026-140733-678173` Adaptive Analytic Curve Sampling & Label Bounds Clamping)
- When a single horizontal range (`sharedMin..sharedMax`) spans both wide populations and narrow high-$n$ sampling distributions, analytic SVG curves (`makeCurvePath`) must also scale their step count with `sd` (`steps = Math.min(2400, Math.max(240, Math.ceil((xmax - xmin) / (sd / 10))))`) and explicitly include the exact peak coordinate `x = mu` so narrow curves never undersample their peak height.
- Zero-reference labels (`0 (No Diff)`) must clamp their horizontal placement inside `[padL, padL + plotW]` (flipping anchor side when near either plot edge) and use a `135 px` above-plot separation threshold against the `μ₁ − μ₂` header.
