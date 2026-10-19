# researchPrime PLAN — Anchor Calendar: best-in-class OPTIONS survey

**Date:** 2026-06-17 · **Mode:** ENGINE (node, import-spike go:true, 28 trio symbols) · **ISOLATION:** orchestrator approximated; lanes + refuters + Judge = real sub-agent contexts.

## Relationship to the 2026-06-15 run
That run validated the **backend** (poll-not-webhook · 2 REST clients · OAuth2-PKCE/DPAPI · iCalUID three-way-merge engine) and locked two decisions (`[calendar]` pip-extra; full two-way; Anchor-owns-only-its-calendar). The infra spike is OBSERVED. **Those facts are treated as established and are NOT re-litigated.**

## AXIS (the load-bearing win-condition)
For a Crucible session that must produce a buildable plan for a **Google/Outlook-LIKE calendar inside Anchor**, pick the *specific components/options* to use — and reject the wrong ones — across four under-covered decision surfaces:
1. **The calendar UI widget** — what to render month/week/day/agenda views, drag-to-create, recurring display, with (a) a vendorable, dependency-light, permissively-licensed asset that fits Anchor's "stdlib-only Python + vendored JS" model (precedent: xterm.js, KaTeX, anchor-term).
2. **The event store + ICS/recurrence layer** — hand-rolled JSON vs a library; how RRULE/EXDATE/VTIMEZONE/attendees are stored and *expanded* for display.
3. **Sync-engine prior art to reuse, not reinvent** — vdirsyncer/Unison model, open-source two-way calendar sync, and whether any library already does the reconcile.
4. **Buy-vs-build alternative** — unified-calendar SaaS APIs (Nylas, Cronofy, etc.) as an architecture option, scored honestly against the local/private posture.

**FALSIFIES a candidate:** a widget that needs a build toolchain/npm runtime or a non-permissive license; an event model that can't round-trip recurrence; a "library" that doesn't actually exist or is unmaintained; a SaaS option that breaks the local-private/no-public-endpoint North Star.

## Stakes VECTOR
- **Impact:** medium-high (steers a real multi-wave build touching the user's real calendar data).
- **Reversibility:** the *research* is reversible; a wrong **vendored-widget** pick is moderately sticky (UI rewrite). Backend already de-risked.
- **Blast radius:** internal to Anchor (research only). → **Governor tier: MEDIUM** (Synthesizer + Judge fire; convergence-until-dry).

## Candidate branches (named, no winner yet)
- UI: FullCalendar · Toast UI Calendar · Schedule-X · EventCalendar (vkurko) · vanilla/hand-rolled grid.
- Store: hand-rolled JSON · `icalendar` · `ics.py`; expansion via `dateutil.rrule` · `recurring-ical-events`.
- Sync: reuse vdirsyncer algorithm (port) · hand-roll per 03-agent-impl spec · any maintained lib.
- Architecture: direct REST (locked) · unified SaaS (Nylas/Cronofy) as the rejected/​contingency arm.

## Oranges foresight receipt
- **Dropped branch:** re-validating the OAuth/poll/DPAPI backend. **Counterfactual cost:** ~0 — it was CORROBORATED + partially OBSERVED 2 days ago; re-running would burn budget and likely echo the same sources (correlated). Risk if wrong: low (2-day-old vendor facts rarely shift). Kept a *thin* 2026-freshness check inside Lane 4 instead.
- **Reordered:** UI-widget survey promoted to Lane 1 (it is the user's actual ask and the prior run's weakest spot).

## Phase-3 plan
4 fresh-context research lanes → 2 heterogeneous refuters (tasked to break the load-bearing picks: "the widget can be vendored asset-only" and "don't reinvent the reconcile") → 1 context-free Judge → engine-structured convergence. Honest stamp: cross_model:false (single-host sub-agents).
