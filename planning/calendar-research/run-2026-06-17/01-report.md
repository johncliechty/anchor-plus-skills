# Anchor Calendar — Best-in-Class OPTIONS Survey (researchPrime full report)

**Date:** 2026-06-17 · **Skill:** researchPrime · **Mode:** ENGINE (node, import-spike `go:true`, 28 trio symbols)
**Adversarial verification:** RAN — 4 fresh-context research lanes → 2 heterogeneous refuters (tasked to break the load-bearing picks) → 1 context-free Judge → convergence. The Node governor's import probe was GO; its in-process agent slots can't reach the live sub-agent host, so the adversarial *substance* ran through real context-isolated sub-agents. **`cross_model: false`.**
**ISOLATION:** orchestrator = approximated; the 4 lanes + 2 refuters + Judge = real (separate sub-agent contexts).
**Evidence ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED.

> **Relationship to the 2026-06-15 run.** That run validated the *backend* (poll-not-webhook · two REST clients · OAuth2-PKCE/DPAPI · the reconcile engine) and locked two decisions (`[calendar]` pip-extra; full two-way; Anchor-owns-only-its-calendar). The infra spike is OBSERVED. **This run does NOT re-litigate those** — it covers the four surfaces that run left thin, the ones your "a calendar *like Google/Outlook*" framing actually points at: the **UI widget**, the **event store + recurrence**, **sync prior-art to reuse vs reinvent**, and **buy-vs-build**. One of its findings *narrows* a locked decision — flagged for your call in §6.

---

## 1. Bottom line

A Google/Outlook-like calendar in Anchor is buildable with **off-the-shelf, permissively-licensed, vendorable parts** — you do not have to hand-build the calendar grid, and you should not hand-build the recurrence expander or buy a SaaS. Four picks, each survived an adversarial Judge:

1. **UI widget → vendor EventCalendar (vkurko)** — MIT, zero-dependency, ~35 KB truly-standalone bundle; FullCalendar is the documented fallback. *[Judge: MED]*
2. **Event store → canonical RFC-5545 `.ics`-per-series + a `meta.json` sidecar** that **must retain the raw provider JSON**; expand recurrence with the **permissively-licensed `allenporter/ical`** (NOT the LGPL `recurring-ical-events`). *[Judge: HIGH]*
3. **Sync engine → build TWO one-way pipes, not a symmetric three-way merge.** The locked safety rail makes the hard merge unnecessary. *[Judge: HIGH — this narrows the locked "full two-way" decision; see §6]*
4. **Buy-vs-build → BUILD (direct REST).** No SaaS or unified library fits a local-private app. *[Judge: HIGH]*

**Single most dangerous residual risk:** the hand-rolled **Microsoft Graph `recurrencePattern` ↔ RRULE translator** — it has no official converter and is provably *lossy* (Graph's `relativeMonthly`/`relativeYearly` with multiple `daysOfWeek` = "first day that satisfies", which has no clean RRULE form). Cheapest fix: a **1-day enumeration spike** that turns it into a closed fixture table of clean-cells vs sidecar-only cells *before* Crucible estimates the recurrence work.

---

## 2. Decision 1 — the calendar UI widget

**Recommendation: vendor `EventCalendar` (vkurko/calendar), MIT.** Documented fallback: FullCalendar v6.

| Candidate | License | Vendorable static, no-build? | Views | Drag-to-create (free?) | Recurrence | Health | Verdict |
|---|---|---|---|---|---|---|---|
| **EventCalendar (vkurko)** | MIT | ✅ **zero-dep ~35 KB standalone** (Svelte compiled away — needs nothing external) | month/week/day/list | ✅ free | ❌ none native → **pre-expand** | v5.7.1, active | **PICK** |
| **FullCalendar v6** | MIT (premium = Timeline/Resource/Print only) | ✅ `index.global.min.js` self-injects CSS, bundles core+interaction+daygrid+timegrid+list | month/week/day/list | ✅ **free** (`@fullcalendar/interaction`) | simple built-in free; full RRULE = **+2 files** (`@fullcalendar/rrule` MIT + `rrule.js` BSD-3 peer) | 20.5k★, Dec 2025 | **Fallback** |
| Schedule-X | mixed | ❌ standalone path is a **Preact app** (framework lock-in); v4 moved drag/resize to **PAID** | all | ❌ paid in v4 | partial | active | **Disqualified** |
| Toast UI Calendar | MIT | ✅ | month/week/day | ✅ | partial | **stale (no release since ~Aug 2022)** | **Disqualified (durability)** |
| Hand-rolled CSS grid | n/a | ✅ | month only (realistic) | own-build | own-build | — | month-only acceptable; **time-grid is a multi-week own-forever build** |

**Why EventCalendar over FullCalendar:** for a single-user, stdlib-purist app that vendors static files, a **zero-dependency single-file MIT bundle** is the cleanest fit and the lightest footprint. FullCalendar's headline advantage — free built-in recurrence — is **largely redundant here** because the event store expands recurrence on the backend anyway (Decision 2), and getting full RRULE in FullCalendar costs *two more* vendored files. **[Refuter A confirmed both bundles' license/standalone claims against primary repos.]**

**Honest caveat (the load-bearing trade-off):** EventCalendar renders **already-expanded occurrence instances** — it has no client-side recurrence safety net. So **100% of recurrence correctness lands on the backend expander** (Decision 2). If that expander is wrong, the calendar silently shows wrong/missing occurrences. FullCalendar's client-side RRULE engine would be a second line of defence — which is exactly why it stays the named fallback.

*Evidence:* EventCalendar zero-dep/MIT = **OBSERVED** (package.json + LICENSE). ~35 KB = **CLAIMED** (README, not re-measured). FullCalendar free interaction/CSS-self-inject = **OBSERVED** (fullcalendar.io/license, /docs/plugin-index, v6 upgrade notes). FullCalendar exact min KB = **UNVERIFIED**.

---

## 3. Decision 2 — event store + recurrence expansion

**Recommendation: canonicalize each event series to one RFC-5545 `.ics` + a `meta.json` sidecar; expand with `allenporter/ical` (permissive).**

- **On-disk model:** `.anchor/calendar/<account>/events/<icalUID>.ics` (one per series; RECURRENCE-ID overrides are sibling VEVENTs sharing the UID) **+ a `meta.json` sidecar** for everything iCalendar can't carry losslessly: provider `id`/`etag`, Google `recurringEventId`, **Graph `seriesMasterId`/`type`**, sync tokens, colorId, conferencing, extended props. Storing *only* raw provider JSON gives two divergent schemas no expander can read; canonical ICS is the common substrate (Google already emits RFC-5545 RRULE lines). **[CORROBORATED]**
- **The sidecar is load-bearing, NOT optional — it MUST retain the raw Graph JSON.** Microsoft Graph emits a *structured* `recurrencePattern`+`recurrenceRange`, not an RRULE string. Most patterns translate, but `relativeMonthly`/`relativeYearly` with **multiple `daysOfWeek`** mean "the first day that satisfies the pattern" — which has **no clean RRULE equivalent**. So Graph→RRULE is **provably lossy**, and the only lossless source of truth for those events is the retained raw JSON. **[Refuter A, OBSERVED against Graph docs]**
- **Expander: use `allenporter/ical` (Timeline), permissive license — NOT `recurring-ical-events` (LGPL-3.0).** The original lane called `recurring-ical-events` the only turnkey expander; the refuter found `allenporter/ical` does the same job (RRULE + RDATE + EXDATE + RECURRENCE-ID overrides + timezones) under a permissive license, avoiding gratuitous copyleft in a stdlib-purist private app. **Verify Timeline covers your full RRULE surface before locking** (MED). `dateutil.rrule` alone is insufficient (raw RRULE only — no VEVENT ingest, no EXDATE auto-apply, no per-instance overrides); `ics.py` is disqualified (no RRULE support, issue open since 2013).
- **`[calendar]` extra contents (recurrence layer):** `icalendar` (BSD-2; parse/serialize) + `allenporter/ical` (permissive; expand). Both pure-Python, lazy-imported behind the same seam as `msal`/`google-auth`, degrade to "calendar unavailable" when absent; the JSON sidecar stays stdlib-readable without the extra.
- **Correctness landmine:** RECURRENCE-ID override identity — a modified/cancelled instance is a *separate* component sharing the series UID, keyed to its *original* start. Key the series by `iCalUID`, the instance by `(iCalUID, original-start)`, or you render ghost/duplicate occurrences. **[CORROBORATED]**

---

## 4. Decision 3 — sync engine: reuse, reference, or hand-roll

**Recommendation: hand-roll, referencing vdirsyncer — but build TWO one-way pipes, not a symmetric three-way merge.**

- **No turnkey exists.** A PyPI/GitHub sweep found no maintained Python engine that two-way-syncs Google ↔ Graph. Closest: one-way mirrors (`gcal_sync`), transport clients (`gcsa`, `python-o365`), and the only real two-way Outlook↔Google tool, **OutlookGoogleCalendarSync** — which is C#/.NET, a standalone GUI, not importable. **[CORROBORATED, both lanes + refuter]**
- **vdirsyncer (BSD-3, active v0.20.0 Aug 2025) is the reference, not a reusable import** — and the spec's own framing needed a correction: vdirsyncer's core is a **two-way, state-based** reconcile storing an `(etag_A, etag_B)` status map (etags only); a three-way *content* merge is just an optional `conflict_resolution` add-on. Worth copying from its BSD `sync.py`: the ETag-as-dirty-signal pattern and its **`StorageEmpty` "a replica went empty ⇒ abort, don't propagate deletes" data-loss tripwire.** Anchor's "last-synced-baseline three-way" is properly the **Unison** model (Balasubramaniam & Pierce, *What is a File Synchronizer?*, MobiCom '98; Pierce & Vouillon, *What's in Unison?*, UPenn MS-CIS-03-36, 2004). Note: vdirsyncer's author has moved to a Rust successor (pimsync/vstorage). **[OBSERVED at primary sources]**
- **THE SCOPE REDUCTION (highest-value finding).** The locked safety rail — *Anchor only ever WRITES to a dedicated Anchor-owned calendar* — means **every event has exactly one authoritative writer**: Anchor-owned events flow **one way out** (Anchor → provider), all other calendars flow **one way in** (provider → Anchor, read-only display). With single-writer-per-event there is **no both-sides-dirty case**, so **no stored content baseline and no symmetric three-way merge are needed** — just two one-way pipes with ETag/sync-token change-detection on the pull side and echo-suppression (self-marker + recorded ETag) on the push side. **[Refuter B; Judge HIGH]**
- **Precise tripwire — when the full three-way merge becomes necessary:** *the moment a user is allowed to natively edit or delete, inside Anchor, an event that is also mutated by an external provider* — i.e. any event with two concurrent independent writers. Until then, two one-way pipes are correct and sufficient. (ETag/sync-token state for change detection is still required on the pull side — that is not the same thing as a merge baseline.)
- **Keep one CRDT lesson:** on the rare conflict you do hit, do **field-level** diffing, not whole-event last-writer-wins.

---

## 5. Decision 4 — buy vs build

**Recommendation: BUILD (direct REST). [Judge HIGH]**

Every hosted aggregator — **Nylas, Cronofy, CalendarBridge, Composio, Merge.dev, Recall.ai** — structurally **holds the OAuth token, caches the user's calendar in *its* cloud, and expects a public webhook callback**. All three are fatal to Anchor's local-private, poll-not-webhook North Star, and pricing is absurd for one user (Cronofy ~$819/mo; Nylas layers fees on top of otherwise-free first-party APIs). The only non-cloud option, **self-hosted Cal.com**, keeps data local but is the wrong product (a Calendly-style booking platform) and drags in Node + Next.js + Postgres — a flat violation of the stdlib-only rule. **No unified local *library* (vs hosted service) abstracts Google + Graph** — confirmed only per-provider clients exist, which strengthens "build." **The one exception:** a future pivot to a *hosted multi-tenant* Anchor (many users, cloud backend, SOC2/BAA offload) would favour Nylas/Cronofy — but that is the negation of the North Star.

**2026 freshness check (fetched 2026-06-17, primary docs) — all locked backend facts still valid, with one correction:**
- ✅ Google `events.list` + `syncToken` incremental sync — **current**, no deprecation (sync guide updated 2026-04-23).
- ⚠️ **Microsoft Graph delta — use `/me/calendarView/delta` (GA v1.0); `/events/delta` is BETA-only.** *(Corrects the 2026-06-15 handoff, which listed them as interchangeable.)*
- ✅ Google **Testing** mode revokes sensitive-scope refresh tokens at 7 days; **Production** (even unverified) does not — confirmed.
- ✅ Calendar is a **sensitive** (not restricted) Google scope — no annual third-party security assessment — confirmed.
- ✅ Desktop **loopback redirect + PKCE** still supported/recommended (deprecation is mobile/Chrome only; OOB long-dead) — native-app doc updated 2026-05-26. No 2025–26 desktop breaking change.

---

## 6. The one thing that is YOUR call (it narrows a locked decision)

The 2026-06-15 `DECISIONS.md` locked **"full bidirectional two-way, up front."** This run's strongest, Judge-HIGH finding is that **your own safety rail makes the *symmetric* part of that unnecessary** — two one-way pipes deliver the entire "see all my calendars + push my Anchor deadlines back" experience, faster and far safer, with the symmetric three-way merge deferred behind an explicit tripwire (native editing of dual-writer events). This is not a contradiction of your goal; it is the cheapest correct way to *reach* it. **Decision for you:** ratify the scope reduction (recommended), or keep symmetric two-way as a hard up-front requirement (which re-introduces the content baseline + the richer-store prerequisite as Wave 1, per the original DECISIONS.md).

---

## 7. Honest limits (correlated blind spots)
- **No code OBSERVED this run** — all picks are doc/repo-corroborated, not executed. The bundle sizes (EventCalendar ~35 KB, FullCalendar min KB) and `allenporter/ical` RRULE-surface parity are the least-verified load-bearing items; a half-day spike (vendor both bundles, render a week view from a stub `.ics`, run `allenporter/ical` over a recurrence fixture) would convert them to OBSERVED.
- **Vendor-doc-centric freshness:** the 5 OAuth facts rest on Google/Microsoft docs fetched today; if a doc page lags a just-shipped policy change, doc + echoing blogs would be wrong in the same direction (partially de-correlated by reading the RFC-level native-app guidance).
- **The Graph `recurrencePattern` enumeration is reasoned, not exhaustively tested** — which is exactly why §8 makes it the gating spike.

---

## 8. Recommended next step
1. **Ratify the §6 scope reduction** (two one-way pipes; defer symmetric merge behind the dual-writer tripwire). Optional but recommended.
2. **Run the 1-day Graph-recurrence spike** — enumerate every `recurrencePattern` variant (daily/weekly/absoluteMonthly/relativeMonthly/absoluteYearly/relativeYearly × single & multiple `daysOfWeek` × `index`) into a fixture table asserting clean-RRULE-round-trip OR explicit sidecar-only. Its lossy-cell count gates the recurrence estimate.
3. **Take it to Crucible** to fold these four picks into the existing `planning/calendar-research/run-2026-06-15/CRUCIBLE-PROMPT.md` and freeze `planning/calendar-v1/`. The component picks + the scope reduction are in `04-crucible-decision-addendum.md`.
