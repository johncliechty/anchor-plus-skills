# Dashboard v2 — scorecard + elegance cuts

Prototype: `_mockups/dashboard-v2/index.html`
Date: 2026-08-27 · Steward livery in proto: Jarvis (Tip of the Hat)

## What this is for
Open Anchor in the morning, see what needs you, act, and leave. Not a second copy of every list.

## Best-in-class (what the prototype is scored against)

| Surface | Best-in-class bar | Current live dashboard | This prototype |
|---|---|---|---|
| Left rail | One move, then waiting-on-you, then counts. F-pattern. | Brand + domain nav + balance bars + inbox. Tasks leak into the summary. | Steward owns the rail: the move, due today, waiting, project counts, workbench ongoing. |
| Tip of the Hat | Ranked. One raise. Green / amber / red. Feedback trains the ranker. Peek, then open. | Collapsed tile that dumps the overlay. No rank, no color, no “start here.” | Ranked rows. Raise block. Peek drawer. New project by talking. Calendar/email hints sit *inside* the hat, not as a second briefing. |
| Tasks | Counts on the tile. Archives inside. | Completed / Cancelled / Saved as header buttons. Duplicate Completed in the stats row. | `10 priority · 15 other · 43 done · 21 cancelled · 4 saved` on the tile. Archives live in the open tile. |
| Projects | Open / running / need-you. One list. | Stats-row “Active Projects” + R&D view + markdown P1/P2 cards + tile. | One tile. Counts on the face. R&D folders are the list. |
| Doctor | Symptom → diagnosis → fix → receipt, unprompted. | Banner says “click to diagnose.” Page waits for Diagnose. Full re-run is minutes. Fix rarely lands. | Banner or Doctor opens a run that already has the report. Probe-now, not 5 AM replay. Receipt in English. |
| Hunter | Every unsupervised model spend. Skills, efforts, workbench, commissions. | Session/PTY hunter. Skills and steward commissions are blind spots. Not safe to arm (2026-07-05 Gandalf). | Census of sessions + skills + efforts. Blind spots named. Still not armed. |
| Foundry | Live map of the skills that actually exist. | Separate GUI; drift vs updated skills is a known worry. | Skill cards from the current foundry set. Click → what it is, last sleep, map status. |
| Chrome | Identity + tools. Nothing twice. | GWL three times. 5:1 chip. Stats row. Inbox. Click-to-expand copy. | One brand lockup. Doctor / Hunter / Foundry sit with the date. Prefs: terminal, coding, review, steward. |

## Cuts (this pass)

Removed from the home surface:

- “Click to expand / Click to collapse”
- Completed / Cancelled / Saved header buttons (they belong in Tasks)
- Stats row: Active Projects / Open Tasks / Completed / In Inbox
- Claude-driver · Gemini-swarm 5:1 chip
- Inbox as a primary view (capture can live later inside Email or Hat)
- Domain-balance widget and domain nav
- Duplicate GWL masthead + footer
- R&D / R&D Archive as sibling views of the dashboard
- Doctor’s required “Diagnose” click when a health issue already exists
- Dual project lists (markdown cards + R&D folders)

Cost of the cuts: inbox-as-inbox and domain-filter views go away. Domain still tags each task/project; filter can return inside Tasks/Projects if you miss it.

## Holds (named, not built)

- Calendar OAuth (Google + two Outlook) — research already locked 2026-06-20; two one-way pipes. Prototype shows the tile only.
- Email pull (Gmail + two Outlook) — no research yet; tile is a shape, not a connector.
- Standalone app — research already locked: PWA + `msedge --app=` + Tailscale Serve for phone. Do after the surface is right.
- Collaborators on a project peek — shown as a slot, not a product.
- Steward as its own project — after this surface is the one you want.

## Ranking rule (Tip of the Hat, v0)

Deterministic, so you can argue with it:

1. Waiting on you (red)
2. Unsupervised spend or a live health failure (red)
3. Time-bound in the next 48h (calendar talk / travel / class)
4. Paused with a human on the other side (amber)
5. Running and owned (green) — visible, not raised
6. Quiet (dim)

“Not as important” demotes that row for 7 days and raises the next. That is the feedback loop. No hidden score.

## Doctor rule (v0)

A health issue is already a diagnosis on disk. Opening Doctor with a red banner:

1. Read the latest report (instant)
2. Probe the failing checks *now* (seconds, not a 5-minute full run)
3. If the 5 AM failure is gone → stamp resolved, clear the banner
4. If still failing and the fix is known and reversible (service down → restart) → do it, re-probe, write a receipt
5. If the fix is not known or not reversible → stop and say so

Never start a chat session named “Diagnose this” as the path to a fix.

## Hunter rule (v0)

A runner is anything a model is doing without you at the keyboard: PTY sessions, skill engines, steward commissions, workbench terminals, foundry sleep. The hunter’s job is to name unsupervised spend, not to kill by default. Arming stays off until every runner class is in the census.

## Needed-because (unrequested)

- Calendar + Email tiles on this prototype: you asked to put the tiles in now so the home shape is complete. Dropping them costs a later relayout.
- Phone CSS: you named iPhone/Android as the destination. A breakpoint now costs a page of CSS and saves a second desktop-only design. Connector work is *not* in this file.

## What researchPrime is *not* for (this turn)

Calendar architecture and “Anchor as an app” already have engine-backed briefs on disk. Re-running them would relitigate locked decisions. Ranking and the doctor loop are product rules; they get better from you clicking “not as important” and from the doctor receipt matching what you see, not from another evidence ledger.
