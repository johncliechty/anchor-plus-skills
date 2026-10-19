# Anchor Friction Journaling — REQUIREMENT + DESIGN (John, 2026-07-26, for v1.1.1)

## John's ask (verbatim intent)
"As Anchor is used and there are friction points or problems or concerns the user
might have, they can tell Anchor they want to have a journaling effort happen. These
journaling efforts get logged, and this can be used as a basis for Anchor to have a
SLEEP CYCLE — to have somebody like Fable come in and clean things up."

## What exists today (verified 2026-07-26) — the gap is real
- `foundry_journal.py` — writes SKILL run journals into skill folders (host-enforced,
  machine skeletons; repointed to `journal/machine/` this session).
- `share_feedback.py` — opt-in, fail-closed EXPORT of per-SKILL journal friction
  (`EXPORT_OUTCOMES = friction|failed|refused|workaround`, allowlist fields, PII
  fail-closed, de-identified install key). Schema `share-skill-friction/v1`.
- `docs/friction/2026-07-25-*.md` — **HAND-WRITTEN by John.** No writer, no endpoint,
  no UI. This is exactly the manual labor the feature must replace.
- **NOTHING captures friction about ANCHOR ITSELF from the user, in the moment.**

## The design (v1.1.1 scope — deliberately small, honest, no model call required)

### Store
`C:\dev\Anchor\.anchor\friction\<YYYY-MM-DD>-<seq>-<slug>.json` + a rolling
`index.json`. One record per journaling effort. Stdlib only, append-only, never
destructive. (Anchor-level, NOT per-project — friction is usually about the tool.)

### Record shape (7 fields, mirroring the foundry journal discipline)
```
{ id, ts, source: "user"|"auto", severity: "friction"|"problem"|"concern",
  title, body,                       # what the user said, verbatim
  context: {                          # captured automatically, never typed
    project_id?, session_id?, lane?, route?, engine?,
    anchor_version, host, recent_errors[]   # last N errors.log lines
  },
  status: "open"|"triaged"|"resolved", resolution?: {...} }
```

### Capture surfaces (all thin)
1. **`POST /api/rnd/journal_friction`** — `{title, body, severity?, project_id?,
   session_id?}` → writes a record, auto-attaching context. Token-authed.
2. **In-session phrase capture** — when a user types something like
   "anchor: journal this" / "journal a friction" into a terminal, the session layer
   offers/creates the record with the last N lines of transcript as body seed.
   (v1.1.1 may ship the endpoint + UI button only; phrase capture is a fast follow —
   DO NOT claim it if not built.)
3. **`anchor.py journal "<title>" [--body …] [--severity …]`** — CLI mirror.

### Sleep-cycle read surface (what Fable consumes)
- **`GET /api/rnd/friction?status=open`** — SAFE projection, newest-first.
- **`anchor.py friction-report [--since N]`** — renders ONE markdown brief:
  clustered by area, each cluster with the records, the auto-context, and the
  suggested owner file(s). **This is the sleep-cycle intake doc** — the same role
  `docs/friction/2026-07-25-SLEEP-INTAKE-*.md` played by hand.
- Records are marked `triaged`/`resolved` with a pointer to the fixing commit, so the
  next sleep cycle sees only what's still open.

### Honesty rules (non-negotiable, mirroring the skills work)
- The record stores what the USER said verbatim; Anchor never rewrites it.
- Auto-context is FACTS ONLY (ids, route, version, recent error lines) — no model
  interpretation at capture time.
- A friction record is NEVER auto-resolved; only an explicit action closes it.
- Zero model calls on the capture path (capture must work when engines are down —
  the moment of friction is exactly when things are broken).

## Status
- [ ] BUILD (v1.1.1): store + `journal_friction` POST + `friction` GET + CLI
      `journal` / `friction-report` + a UI capture control + tests.
- [ ] Wire into the collaborator memo as the headline "tell us what hurt" mechanism.
- [ ] Fast-follow (v1.2): in-terminal phrase capture, auto-capture on repeated
      errors, and the automated sleep-cycle handoff to Fable.
