# Anchor Calendar v1 — MASTER PLAN

*Lane: planning · validated, cached summary*

**When run:** 2026-06-20

**What was asked:** Anchor Calendar v1 — MASTER PLAN

**North Star:** > **Anchor displays all of John's Google + Outlook/M365 calendars in a real calendar view, and pushes John's Anchor-owned events out to a dedicated Anchor-owned calendar in each provider — fully local and private (no cloud, no inbound/public network surface) — and it can NEVER corrupt, delete, or duplicate a human-created event in John's real calendars.** **Falsifiers (any one fails the objective):** - (a) any write path that can mutate a non-Anchor-owned event; - (b) any inbound/public network surface or webhook dependency; - (c) a sync bug that silently loses or duplicates events; - (d) a ca

## Actions & files produced

- Anchor Calendar v1 — MASTER PLAN
- Anchor Calendar v1 — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor Calendar v1 â€” MASTER PLAN â€” Session Summary
- **Goal / North Star (LOCKED 2026-06-20)**
- Anchor displays *all* of John's Google + Outlook/M365 calendars in a real calendar view, and pushes John's Anchor-owned events out to a **dedicated Anchor-owned calendar** in each provider.
- The system is **fully local and private** â€” no cloud, no inbound/public network surface.
- Hard safety invariant: it can **NEVER corrupt, delete, or duplicate** a human-created event in John's real calendars.
- **Falsifiers (any one fails the objective)**
- (a) Any write path that can mutate a non-Anchor-owned event.
- (b) Any inbound/public network surface or webhook dependency.
- (c) A sync bug that silently loses or duplicates events.
- **Resolved decisions (locked for this plan)**
- **A â€” OAuth implementation:** a `[calendar]` optional pip-extra (`msal` + `google-auth`), lazy-loaded and degrading like the existing `[terminal]`=`pywinpty` extra, added to `distro.py`'s scoped allowlist; credentials still **DPAPI-wrapped at rest**.
- **B â€” Sync scope:** **two one-way pipes** â€” push Anchor-owned events â†’ the dedicated Anchor calendar, and pull all other calendars **read-only**. Explicitly **no symmetric three-way merge** (deferred behind the dual-writer tripwire in Â§8).
- **C1 â€” Recurrence expander:** accept `allenporter/ical` inside the `[calendar]` extra + distro allowlist (John, 2026-06-20); this adds a compiled dependency (detail truncated in source).
- Anchor Calendar v1 â€” MASTER PLAN
- Anchor Calendar v1 â€” Implementation Plan (Foreman-ready)
- ## Anchor Calendar v1 â€” MASTER PLAN (planning trio summary)
- **Objective (North Star, LOCKED 2026-06-20)**
- Anchor displays *all* of John's Google + Outlook/M365 calendars in a real calendar view, and pushes Anchor-owned events out to a **dedicated Anchor-owned calendar** in each provider.
- (a) Any write path that can mutate a **non-Anchor-owned** event.
- (b) Any **inbound/public network surface or webhook** dependency.
- (c) A sync bug that **silently loses or duplicates** events.
- **A â€” OAuth implementation:** ship as a `[calendar]` **optional pip-extra** (`msal` + `google-auth`), lazy-loaded and degrading gracefully like the existing `[terminal]`=`pywinpty` extra, declared in `distro.py`'s scoped allowlist; credentials still **DPAPI-wrapped at rest**.
- **B â€” Sync scope:** **two one-way pipes** â€” push Anchor-owned events â†’ the dedicated Anchor calendar, and pull all other calendars **read-only**. **No symmetric three-way merge**; symmetric merge is **deferred** behind the dual-writer tripwire (Â§8).
- **C1 â€” Recurrence expander:** accept **`allenporter/ical`** inside the `[calendar]` extra and the distro allowlist (John, 2026-06-20); this adds a compiled *(detail truncated in the source anchor).*

## Files

- [Anchor Calendar v1 — MASTER PLAN](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcalendar-v1%2FMASTER-PLAN.md)
- [Anchor Calendar v1 — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcalendar-v1%2FIMPLEMENTATION-PLAN.md)
