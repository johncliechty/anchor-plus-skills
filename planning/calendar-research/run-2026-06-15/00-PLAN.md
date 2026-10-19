# researchPrime — PLAN (frozen) · Anchor two-way calendar integration

**Date:** 2026-06-15 · **Skill:** researchPrime · **Mode:** ENGINE (node v26.1.0; import spike go:true, 28 trio symbols)
**Requester intent (locked, John 2026-06-15):** "A calendar where you can import Google calendars and Outlook calendars, pull information directly into the Anchor calendar, and then push information and events back to the linked calendars." → **full bidirectional, multi-provider (Google + Microsoft/Outlook) sync**, surfaced in an in-Anchor calendar.

## AXIS (the load-bearing win-condition)
Produce a **buildable** design for bidirectional Google ⇄ Anchor ⇄ Microsoft-365 calendar sync that survives Anchor's hard constraints:
- **stdlib-only** Python (the ONLY sanctioned native dep is `pywinpty`, lazy, in `pty_manager.py`; `distro.py` import-scan refuses any other third-party import in product code),
- runs inside the persistent **NSSM `anchor` service** bound to **`localhost:8777`** (single-user, loopback only),
- **markdown files are the source of truth** (no DB),
- data written back to the user's REAL calendars (partially irreversible).

**What would FALSIFY a candidate:** if OAuth 2.0 + Google Calendar API v3 + Microsoft Graph write-back cannot be done acceptably without a third-party library AND the stdlib-only rule is treated as immovable, then "native REST two-way sync inside product code" is REFUTED and the honest answer is a constraint-exception decision (declare a 2nd optional extra) or a narrower scope. The crux is the **stdlib-only × OAuth/REST** collision — verify it, don't assume it.

## STAKES VECTOR → tier
- **Impact:** high — a new subsystem touching OAuth secrets, two external APIs, and the user's real calendar data.
- **Reversibility:** medium — code is removable, but a bad PUSH creates/edits/deletes real events in Google/Outlook (partially irreversible).
- **Blast radius:** medium — isolated subsystem, but holds refresh tokens and can mutate external state.
- Irreversibility (real write-back) forces tier ≥ medium. **Projected tier = HIGH** → Phase-3 fires Synthesizer + Judge + debate; convergence-until-dry.

## Candidate branches (no winner named)
- **B1 — Provider-native REST** (Google Calendar API v3 + Microsoft Graph) over stdlib `urllib`, OAuth2 loopback/PKCE, incremental pull via syncToken/delta, write-back via insert/update/delete.
- **B2 — CalDAV** (one protocol for many providers) — verify current Google CalDAV support and Outlook/M365 CalDAV deprecation status.
- **B3 — .ics import/export** (subscribe feeds + export file) — interop, but write-back-weak.
- **B4 — Third-party libraries** (google-api-python-client / msal / O365 / caldav / icalendar) — violates stdlib-only → forces an explicit constraint-exception decision (a 2nd `[calendar]` optional extra, like `[terminal]`).
- **B5 — External sync middleware/aggregator** (e.g., a hosted unified-calendar API) — offloads complexity but adds cost, privacy exposure, and a cloud dependency.

## Best-in-class baselines to beat
Mature multi-provider two-way sync tools (Morgen, Reclaim.ai, Akiflow, Vimcal, Thunderbird/Mozilla, Radicale/Baïkal, Nylas) — what protocol stack, sync algorithm (sync tokens vs delta vs webhooks vs polling), dedupe key (iCalUID), conflict strategy (ETag/If-Match, last-write-wins vs source-of-truth), and recurring-event handling do they actually use?

## Sub-questions (one lane each — fresh-context execution)
- **SQ1 — Constraint crux:** Is stdlib-only OAuth2 + Google/Graph REST feasible, or does two-way sync force a library exception? (token acquisition, PKCE public client, refresh, secure storage on a single-user Windows box).
- **SQ2 — Provider sync mechanics:** Google Calendar API v3 (syncToken incremental, watch/push webhooks vs polling, insert/patch/delete, iCalUID, ETag/If-Match) AND Microsoft Graph (calendarView delta, subscriptions, POST/PATCH/DELETE events, change-keys). CalDAV/.ics status per provider.
- **SQ3 — Two-way model & conflict resolution:** mapping Anchor tasks/deadlines ↔ calendar events, dedupe, deletions/tombstones, recurring-event expansion, and a concrete conflict-resolution strategy compatible with markdown-source-of-truth.
- **SQ4 — Reference architectures:** how best-in-class tools implement multi-provider two-way sync; the minimal viable architecture for a single-user LOCAL app; webhook delivery to a localhost service (the loopback/public-URL problem).
- **SQ5 — Anchor-fit, security & phased build:** OAuth client-secret handling in a local public client (PKCE), loopback redirect under the NSSM service, where this lands in the codebase (new module + `.anchor/` token store), failure modes, and a staged build recommendation (read-only pull first → write-back → full two-way).

## Oranges foresight receipt (required)
- **Dropped/reordered:** dropped **B3 (.ics feeds)** as a primary path — counterfactual cost: a subscribed `.ics` feed is one-way (no event write-back), so it structurally cannot satisfy "push events back" and would fail the AXIS; retained only as an import/interop detail. **Reordered B4 (library-exception decision) to the FRONT** of analysis because it is the gating constraint that determines whether B1/B2 are even legal in product code — every downstream branch inherits that decision.

PLAN FROZEN. Execution reads ONLY this plan (ISOLATION: real for sub-agents / approximated for the orchestrator).
