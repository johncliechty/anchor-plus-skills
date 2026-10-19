# Executive Summary — Anchor ⇄ Calendar Integration

**2026-06-15 · researchPrime · adversarial verification RAN (5 lanes → 2 refuters → context-free Judge) · cross_model:false**

**Your ask:** import Google + Outlook/M365 calendars into Anchor and push events back — full two-way, multi-provider.

**Verdict: buildable, with a clean forced architecture and two decisions that are yours.**

1. **POLL, don't webhook (forced, and it's fine).** A localhost-only service cannot receive Google/Microsoft push (both need a public HTTPS+CA-cert endpoint). The supported path — Google `syncToken` + Graph `/delta` polling on a background thread, hourly-ish — works from behind your loopback bind with no public surface. Keeps Anchor private. *[corroborated by 4 lanes + a hostile refuter]*

2. **Two native REST clients, no CalDAV.** Microsoft has no CalDAV → Graph is mandatory; Google Calendar API v3 for Google.

3. **DECISION A — OAuth: declare a `[calendar]` pip-extra (`msal`+`google-auth`), don't hand-roll.** Pure stdlib is *feasible* (~600–1200 LOC), but the Judge ruled (HIGH confidence) that security-critical OAuth token-lifecycle is a silent-failure liability for a one-maintainer app, and the `[terminal]=pywinpty` exception is the exact precedent — stdlib-only is Anchor's *distribution* rule, with a built-in scoped-extra escape hatch. **Your call to ratify.**

4. **DECISION B — Scope: phase it.** The markdown-line model is *lossy by construction* for real events (no RRULE/timezone/attendees), so round-tripping arbitrary events two-way would manufacture corruption/data-loss. Recommended order: **A) read-only pull+display → B) one-way push of Anchor's own deadlines → C) full two-way, deferred & earned by demand.** If you insist on full symmetric two-way over arbitrary events, the data model must move from markdown lines to a richer `.anchor/calendar/` event store first. **Your call.**

**Biggest danger + cheapest fix:** a sync bug silently deleting/duplicating *real* events in your calendars (irreversible). Fix = one config field: **Anchor reads all calendars but only ever writes to a dedicated "Anchor" calendar it owns** — never holds a delete handle on a human-created event.

**Resolved live today:** the `anchor` service runs as **`.\john`** (not LocalSystem) → DPAPI user-scope is correct and browser-consent works. (Corrects a stale memory note.)

**Watch-outs:** Google "Testing" mode revokes refresh tokens every 7 days → publish the OAuth app to "Production" (may stay unverified for personal use; calendar is a *sensitive*, not restricted, scope). Use an **installed/desktop** OAuth client (not "Web" — no embeddable secret).

**Next step:** Crucible-freeze a `planning/calendar-v1/` design for **Phase A+B** (extra ratified, Phase C deferred); precede the build with a ~50-line real-auth spike to upgrade feasibility from *corroborated* to *observed*.

**Honesty stamp:** all findings doc-corroborated, none code-OBSERVED (no live OAuth/API call executed). Riskiest unspiked claim: "Production-unverified holds a durable refresh token for the sensitive calendar scope" — verify with a >7-day token-survival test.
