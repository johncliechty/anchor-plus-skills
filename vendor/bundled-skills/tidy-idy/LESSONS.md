# LESSONS — tidy-idy

Promoted from real-run journals (created 2026-07-25 — the rightsize record's own TODO,
23 days late; sources: journal/0001, 0002, and the cross-filed crucible 0014/0015).

1. **A 1-reviewer wave makes ≥2-agree vacuous.** The 7-wave GUI build shipped
   `status:"done"` carrying 2 open MAJOR token/lock findings because the panel ran
   "1 reviewers · 0 agreed BLOCKER/MAJOR". Any wave touching the apply/token control
   plane requires ≥2 reviewers or an explicit per-finding human waiver. (journal 0002)
2. **Never claim a safety action that didn't happen.** The close button said "the
   project lock has been released" even when the dead token meant `/api/close` was
   never sent. Safety claims are confirmed-2xx-or-say-so. (journal 0002)
3. **Reopen instructions must be operator-true in every launch mode.** "Click Tidy-Idy
   in Anchor" was false for standalone CLI runs — Amendment-D's own scenario. (journal 0002)
4. **Single-use bootstrap + HTML 410 is the right UX for spent links** — raw JSON reads
   as breakage to operators; the 410 page + host-only reissue closed the recurring
   "panel looks broken" report. (journal 0001)
5. **Frictions must land in THIS journal.** The Stage-2 external kill and the
   mechanically-DRY round (3/3 Sharks, same 3 holes, normalizer under-count) sat only
   in Crucible's journal — the component's sleep loop never saw its own lessons.
   Cross-file at the component. (journal 0002)
