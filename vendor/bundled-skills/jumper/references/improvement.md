# Improvement protocol (reference) — how this skill gets better during "sleep"

> The authoritative sleep meta-recipe is built + TAP-gated by P0.D (wave 5). This stub
> ships in the per-skill skeleton so every skill repo documents the loop it participates
> in; wave 5 supplies the executable loop.

A "sleep" session improves this skill from its OWN journal WITHOUT drifting:

1. **Cluster** the append-only `journal/` entries by recurring situation.
2. **Distill** candidate lessons — but only those CROSS-CONTEXT corroborated (a lesson
   seen only by same-context repetition is NOT shipped; R5 provenance-distrust).
3. **North-Star gate** — reject any candidate that would advance a NORTH-STAR.md
   non-goal (NS3 anti-drift). Rejections are logged, not silently dropped.
4. **Eval gate** — run the frozen canary set; a candidate that REGRESSES any canary is
   blocked and the prior version retained (NS2 no-regression; versioned rollback).
5. **Promote** survivors into `LESSONS.md` / `SKILL.md` as a new version, recorded in
   `CHANGELOG.md`. Canary sets are versioned alongside (append-only; deletion = human call).

Net effect: the skill measurably improves from real use (NS1) while its LOCKED purpose
and non-goals stay fixed.
