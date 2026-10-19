# 2026-07-25 — Session stop/restart handoff quality (product-wide)

- **id**: 2026-07-25-restart-handoff-quality
- **surface**: Anchor product (all projects, all lanes; worst on general)
- **situation**: John resumes sessions after stop / worktree eviction and cannot get a human-facing picture of where work stood; agents dig through raw transcripts instead of a clean handoff.
- **context**: Live Family Trusts general-lane resume chain 2026-07-25; same RESTART/summarizer code path is global. Code: `terminal_session._write_restart_seed` (mechanical only), `summarizer.py` (transcript-seeded empty summaries), orientation intended to read RESTART first but content is thin.
- **observation**: RESTART is id/lane/engine/seed-line/doc-list only — no goal, status, decisions, next action. Board summaries often title-only or “no grounded claims.” Transcripts polluted by UI noise and dictation loops make archaeology worse. John asked this be journaled for an Anchor sleep improvement run.
- **outcome**: friction
- **severity**: high
- **acceptance**: human 20s summary on tile; RESTART/HANDOFF with goal/status/done/open/next/deliverables; resume orients in one read after eviction
- **full intake**: docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md
- **provenance**: genuine-user-report + code inspection
