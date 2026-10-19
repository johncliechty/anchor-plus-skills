# Lane 1 — Best-in-class JavaScript Calendar UI Widgets

**Study:** best-in-class options for a Google/Outlook-LIKE calendar UI inside Anchor.
**Date:** 2026-06-17
**Hard constraints (Anchor):** stdlib-only Python server that emits HTML + serves **vendored** static JS/CSS (precedent: xterm.js, KaTeX, anchor-term). **NO npm/webpack/vite/Node at build time.** Any library must be droppable as a **prebuilt UMD/ESM/IIFE bundle** referenced by a plain `<script>`/`<link>` tag.

---

## Required feature set
Month + week + day + agenda/list views · click/drag to create · render recurring events · timezone-aware · event detail popovers.

---

## Candidate comparison table

| Library | Version (2026) | License | Free covers month/wk/day/list + drag-create? | Min. bundle (vendored) | Dependency footprint | Vendorable as static files? | Recurring events | Maintenance / health |
|---|---|---|---|---|---|---|---|---|
| **FullCalendar** (`fullcalendar` standard bundle) | **v6.1.20** (2025-12-23) | **MIT** for the standard bundle + non-premium plugins | **YES** — daygrid (month), timegrid (week/day), list, interaction (drag/select-to-create) are all MIT/free | One file `index.global.min.js` (incl. CSS); ~200–300 KB min class (size not pinned to a primary number — see note) | **Framework-free** in the global bundle (no React/Vue/jQuery). Optional rrule plugin pulls `rrule.js` | **YES, ideal** — `index.global.min.js` IIFE global; CSS embedded; no build step | Built-in simple recurrence (daily/weekly via `daysOfWeek`/`startRecur`) free; full RRULE via MIT `@fullcalendar/rrule` + `rrule.js` | **Healthy.** 20.5k★, MIT, last release 2025-12-23 |
| **Toast UI Calendar** (`@toast-ui/calendar`) | **v2.1.3** (core/wrappers ~Aug 2022) | **MIT** (NHN Cloud) | YES — month/week/day built in; drag-create supported | Standalone bundle + separate CSS; "IE11 bundle ~30% larger" (exact KB not published) | **Framework-free** plain-JS core (React/Vue are optional wrappers) | **YES** — plain-JS standalone via CDN/script tag | Not a first-class RRULE engine; you supply expanded instances | **STALE — biggest risk.** 12.7k★ but newest release ~Aug 2022; updates "slowed significantly." Open issues exist but no recent releases |
| **Schedule-X** (`@schedule-x/calendar`) | **v4.6.0** (2026) | **MIT** core; **drag-and-drop + resize moved to PREMIUM in v4**; interactive event modal is premium | Partial — month/week/day/list free, but **click/drag-to-create + resize are now PAID** | npm-first; CDN exists but **not self-contained** | **NOT framework-free in practice** — the CDN/UMD path requires loading **Preact 10.x + @preact/signals (multiple ordered script tags)** first. Core is built on Preact | Technically via CDN **but** must vendor the whole Preact runtime + signals in correct order — fragile, not a single drop-in | Free `@schedule-x/event-recurrence` plugin (partial iCal RRULE; BYDAY monthly/yearly can't drag-edit) | Newer/active. 2.4k★, MIT core, active commits (1,078 commits, 202 tags). v3 added Temporal API |
| **EventCalendar** (`vkurko/calendar`, `@event-calendar/build`) | **v5.7.1** | **MIT** (© 2021 vkurko) | **YES** — dayGrid month/week, timeGrid week/day, list (day/week/month/year), drag/resize/select | **~35 KB Brotli-compressed** (smallest serious option) | **Zero-dependency standalone bundle.** Authored in Svelte but **compiled away** — the build bundle needs no Svelte at runtime | **YES, excellent** — `@event-calendar/build` is an explicit zero-dep standalone for `<script>` via jsDelivr; no build step | **No native rrule** in README; you pre-expand instances (or wire rrule.js yourself) | Active single-maintainer; Svelte 5 work ongoing. Fewer stars than FullCalendar but maintained |
| **Hand-rolled CSS-grid calendar** | n/a | n/a (your code) | Month grid is easy; **week/day time-grid + drag-create + overlap layout + timezone + recurrence are substantial** | ~0 KB lib (your code) | Zero deps — fits Anchor's ethos perfectly | Trivially "vendorable" (it's your own JS/CSS) | You implement RRULE expansion yourself (or vendor rrule.js, MIT) | You own all maintenance |

---

## Per-claim evidence quality (OBSERVED / CORROBORATED / CLAIMED)

- FullCalendar v6.1.20 released 2025-12-23, 20.5k★, MIT — **OBSERVED** (GitHub repo page).
- FullCalendar standard `fullcalendar` bundle + non-premium plugins are **MIT**; premium = Timeline View, Vertical Resource View, Print Optimization only — **OBSERVED** (fullcalendar.io/license + /docs/premium). Premium "starts at $480/yr, 1–10 devs, perpetual fallback to last released version" — **OBSERVED** (fullcalendar.io/pricing).
- FullCalendar `index.global.min.js` is a single framework-free IIFE global bundling core+interaction+daygrid+timegrid+list+multimonth, CSS embedded, usable via plain `<script>`, **no build step** — **OBSERVED** (fullcalendar.io/docs/initialize-globals + bundle README).
- FullCalendar free recurrence (daily/weekly) built-in; full RRULE via MIT `@fullcalendar/rrule` requiring `rrule.js` peer dep — **OBSERVED** (docs/recurring-events) / **CORROBORATED** (npm + docs/rrule-plugin).
- FullCalendar exact minified KB of `index.global.min.js` — **CLAIMED/UNVERIFIED** (cdnjs lists v6.1.19 file but no size; ~200–300 KB is an estimate, not pinned to a primary number). **FLAG: load-bearing size claim not confirmed from a primary source.**
- Toast UI Calendar MIT, 12.7k★, plain-JS core (framework-free), newest release ~Aug 2022, updates slowed — **OBSERVED** (GitHub repo). Exact KB bundle size **not published / UNVERIFIED**.
- Schedule-X v4.6.0, MIT core, drag-and-drop+resize+interactive-modal moved to **PREMIUM** in v4 — **OBSERVED** (GitHub + schedule-x.dev). Free `event-recurrence` plugin with partial iCal support — **CORROBORATED** (schedule-x.dev/docs/.../recurrence via search; could not load installing-page directly — 404).
- **Schedule-X CDN/UMD requires loading Preact + @preact/signals as separate ordered script tags** (core is Preact-based) — **CORROBORATED** (search of schedule-x.dev/docs/calendar; **FLAG: not directly fetched from the official install page — secondary-rendered**). This is the decisive landmine and should be re-verified by opening https://schedule-x.dev/docs/calendar before final commitment.
- EventCalendar (vkurko) MIT (© 2021 vkurko), v5.7.1, **zero-dependency standalone bundle ~35 KB Brotli**, CDN `@event-calendar/build`, 14 view types incl. dayGrid/timeGrid/list — **OBSERVED** (LICENSE file + README raw). No native rrule mentioned — **OBSERVED** (absence in README) / **CLAIMED** for "expand yourself".

---

## Ranked recommendation (for THIS constraint set: vendorable static files, permissive license, framework-free, month/week/day, light)

### 🥇 #1 — FullCalendar (standard `fullcalendar` global bundle)
- **MIT** for everything Anchor needs: month (daygrid), week/day (timegrid), list/agenda, drag-and-select-to-create (interaction).
- Ships as a **single self-contained `index.global.min.js`** (CSS embedded) — the textbook vendored-static drop-in, identical pattern to Anchor's existing xterm.js/KaTeX vendoring. **No npm, no build, no framework.**
- Most mature, best-documented, healthiest project (20.5k★, release Dec 2025), best event-popover/timezone story.
- **The only paid-tier traps are Timeline/Resource/Print views — none of which Anchor's feature list requires.** Recurrence: free built-in covers simple cases; full RRULE adds MIT `@fullcalendar/rrule` + `rrule.js` (both MIT, both vendorable).
- **Caveat:** it's the heaviest of the serious options (size not pinned, but clearly larger than EventCalendar's 35 KB).

### 🥈 #2 — EventCalendar (vkurko/calendar, `@event-calendar/build`)
- **MIT**, **explicitly zero-dependency ~35 KB standalone bundle** — the *lightest* serious option and a clean single-file vendor drop-in. Covers month/week/day/list + drag/resize/select natively.
- Loses to FullCalendar only on: smaller ecosystem/community, **no native RRULE** (you pre-expand recurring instances or vendor rrule.js yourself), and less polished docs/popover affordances. If bundle weight is the dominant concern, this flips to #1.

### Why the others lost
- **Schedule-X** — *disqualifying landmine:* its standalone/CDN path is **not truly framework-free** — it's a Preact app and the vendored route forces loading Preact + @preact/signals as several ordered `<script>` tags (fragile, heavy, exactly the dependency entanglement Anchor avoids). Plus **v4 moved drag-and-drop & resize to the PAID tier**, so "click/drag to create" — a required feature — is no longer free. Two strikes against the constraint set.
- **Toast UI Calendar** — framework-free and MIT, but **effectively stale** (newest release ~Aug 2022, visibly slowed maintenance) and no first-class RRULE. Adopting a calendar that hasn't shipped in ~3.5 years is a long-term liability for a system meant to be durable.
- **Hand-rolled CSS-grid** — a month grid is genuinely cheap and Anchor-idiomatic, but a Google/Outlook-*like* surface needs a time-grid week/day view with event overlap layout, drag-to-create, timezone correctness, and recurrence — that is a multi-week build and ongoing maintenance burden that FullCalendar/EventCalendar give for free. Only justified if the calendar is month-only.

**Bottom line:** FullCalendar's MIT global bundle is the single best pick (covers every required feature free, vendors as one file, healthiest project); EventCalendar is the runner-up and the better choice if minimal bundle weight outranks ecosystem maturity. Both keep Anchor's "no build step, framework-free, permissive license" invariants intact. Schedule-X violates two of the four constraints (framework lock-in + paid drag-create); Toast UI's staleness is the dealbreaker.

---

## Sources (primary unless flagged)

- FullCalendar GitHub repo (version/stars/license/release date): https://github.com/fullcalendar/fullcalendar
- FullCalendar License (MIT scope statement): https://fullcalendar.io/license
- FullCalendar Premium plugins list: https://fullcalendar.io/docs/premium
- FullCalendar Pricing ($480 terms): https://fullcalendar.io/pricing
- FullCalendar global script-tag bundle: https://fullcalendar.io/docs/initialize-globals
- FullCalendar bundle plugin contents: https://github.com/fullcalendar/fullcalendar/tree/main/bundle
- FullCalendar recurring events (built-in vs rrule): https://fullcalendar.io/docs/recurring-events
- FullCalendar rrule plugin (MIT + rrule.js peer dep): https://fullcalendar.io/docs/rrule-plugin · https://www.npmjs.com/package/@fullcalendar/rrule
- FullCalendar cdnjs (latest 6.1.19 listed there): https://cdnjs.com/libraries/fullcalendar
- Toast UI Calendar GitHub (version/stars/license/activity): https://github.com/nhn/tui.calendar
- Toast UI Calendar npm: https://www.npmjs.com/package/@toast-ui/calendar
- Toast UI Calendar getting-started (framework options): https://github.com/nhn/tui.calendar/blob/main/docs/en/guide/getting-started.md
- Schedule-X GitHub (v4.6.0/MIT/stars/commits): https://github.com/schedule-x/schedule-x
- Schedule-X premium split (free vs paid): https://schedule-x.dev/premium
- Schedule-X recurrence plugin doc: https://schedule-x.dev/docs/calendar/plugins/recurrence
- Schedule-X getting-started / CDN+Preact ordering (SECONDARY-rendered via search — re-verify): https://schedule-x.dev/docs/calendar
- Schedule-X jsdelivr (v4.6.0): https://www.jsdelivr.com/package/npm/@schedule-x/calendar
- vkurko/calendar GitHub: https://github.com/vkurko/calendar
- vkurko LICENSE (MIT © 2021 vkurko): https://github.com/vkurko/calendar/blob/master/LICENSE
- vkurko README (v5.7.1, zero-dep 35 KB br, views): https://raw.githubusercontent.com/vkurko/calendar/master/README.md
- EventCalendar docs site: https://vkurko.github.io/calendar/
