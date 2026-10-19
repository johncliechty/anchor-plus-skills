# Lane 2 — Event Store & Recurrence Layer (best-in-class options)

> Study: calendar event store for **Anchor** (single-user, stdlib-only Python; one approved
> optional `[calendar]` pip-extra for OAuth = `msal` + `google-auth`). The question for this lane:
> what should hold the **event store** and the **recurrence-expansion** layer so we can round-trip
> Google + Outlook (Microsoft Graph) events **without data loss**, and expand recurring events into
> concrete instances for a date-range calendar widget.
>
> Date: 2026-06-17. Evidence quality is tagged per load-bearing claim:
> **OBSERVED** (primary doc/repo/RFC read directly), **CORROBORATED** (multiple secondary agree),
> **CLAIMED** (single secondary), **UNVERIFIED**.

---

## TL;DR recommendation

- **On-disk store format:** **canonicalize to RFC 5545 iCalendar** (one `.ics` per event series in
  `.anchor/calendar/<account>/<icalUID>.ics`), **plus** a sidecar `meta.json` per series that
  preserves the raw provider fields RFC 5545 can't carry losslessly (Google `recurringEventId`,
  Graph `seriesMasterId`/`type`, ETag, provider event `id`, sync tokens, color, conferencing,
  custom extended properties). iCalendar is the **lossless interchange substrate both providers
  already speak**; the sidecar catches provider-proprietary metadata so sync is faithful.
- **Library split:**
  - In the `[calendar]` extra: **`icalendar`** (parse/serialize RFC 5545; BSD-2) **+
    `recurring-ical-events`** (expansion incl. EXDATE/RDATE/RECURRENCE-ID overrides; LGPL-3.0).
    Both pull in **`python-dateutil`** transitively, which is exactly the rrule engine we'd otherwise
    have to reinvent.
  - **Stdlib only** stays the default: `import` of the calendar libs is **lazy + degrades
    gracefully** (the established `pywinpty` precedent). With the extra absent, Anchor still parses
    its sidecar JSON and shows stored instances; only *fresh expansion of unbounded RRULEs* needs the extra.
- **Expansion:** use **`recurring-ical-events.of(calendar).between(start, stop)`** — it is the only
  surveyed option that wires RRULE **+ EXDATE + RDATE + RECURRENCE-ID per-instance overrides +
  timezones** together correctly out of the box. Do **not** hand-roll on bare `dateutil.rrule`.
- **Top correctness landmine:** **RECURRENCE-ID override identity.** A modified/cancelled single
  instance is a *separate* component that shares the series `UID` and points at the *original* start
  via `RECURRENCE-ID` (Google: `recurringEventId` + `originalStartTime`; Graph: `type:"exception"` +
  `seriesMasterId`). If you key events by `UID` alone, or expand the RRULE without subtracting/replacing
  the overrides, you will show ghost or duplicate occurrences. The store must key the *series* by
  `iCalUID` and the *instance* by `(iCalUID, original-start)`.

---

## Part A — Storage / parse / serialize candidates

| Option | What it does | License | Maint. health | stdlib vs 3rd-party | Correctness caveats |
|---|---|---|---|---|---|
| **Hand-rolled JSON model** | Bespoke dict/dataclass schema you design to hold UID, RRULE string(s), EXDATE/RDATE, tz, attendees, alarms | n/a (your code) | n/a | **stdlib only** (`json`) | You re-implement RFC 5545 field semantics by hand; easy to silently drop fields you didn't anticipate (the "data loss" failure mode the task forbids). No free interop. **No** recurrence engine. |
| **Store raw provider JSON** (Google Event resource / Graph event) | Persist exactly what the API returned | n/a | n/a | **stdlib only** | Faithful *per provider* but **two incompatible schemas**: Google emits RFC-5545 `recurrence[]` strings; **Graph emits a structured `recurrencePattern`+`recurrenceRange`, NOT an RRULE string** [OBSERVED]. You'd need a translator either way, and no off-the-shelf expander reads Graph's pattern. |
| **`icalendar`** (PyPI) | RFC 5545 parser **and** generator: read/inspect/modify/write `.ics`; full component/property model incl. RRULE, EXDATE, RDATE, VTIMEZONE, ATTENDEE, VALARM, UID | **BSD-2-Clause** [OBSERVED] | **Healthy.** v7.1.3 released **2026-06-15**; "Production/Stable"; 8 maintainers; Py 3.10–3.14 [OBSERVED] | **3rd-party**; depends on **`python-dateutil`** + `tzdata` [OBSERVED] | **Parses but does NOT expand** RRULE into instances — it models the property only [OBSERVED]. Pair with an expander. |
| **`ics.py`** (PyPI `ics`) | Higher-level "Pythonic" ICS read/write + a `Timeline` | (BSD-style) | Maintained but **pre-1.0**; recurrence is a long-open gap | **3rd-party** (uses `attrs`, etc.) | **No RRULE support.** Issue #14 "Support recurring events" is **OPEN since 2013-12-27, milestone v0.8, unresolved** [OBSERVED]. Docs state RRULE parsing/Timeline expansion is **not implemented** and *"most likely never"* full RFC 5545 [CORROBORATED]. **Disqualified for our recurrence need.** |
| **`ical` (allenporter)** / **`ical-library` (jorricks)** | Alt RFC-5545 stacks with built-in recurrence (both lean on dateutil) | varies (Apache/MIT-ish) | Active | **3rd-party** + dateutil | Viable but smaller ecosystems than `icalendar`+`recurring-ical-events`; less battle-tested against Google/Outlook quirks. Listed for completeness, not recommended over the pairing. |

**Raw-vs-canonical verdict:** canonicalize to iCalendar. Google's `recurrence` field already *is*
RFC 5545 RRULE/EXRULE/RDATE/EXDATE lines, with `DTSTART`/`DTEND` carried separately in `start`/`end`
[OBSERVED]. Graph is the outlier (structured pattern); converting Graph→RRULE on ingest gives you
ONE internal model both an expander and a re-serializer understand. Keep the raw provider blob in the
sidecar so nothing is lost on the round trip back.

---

## Part B — Recurrence EXPANSION candidates

> Python **stdlib has no RRULE expander** — `datetime`/`zoneinfo` give you tz math but nothing that
> reads `FREQ=WEEKLY;BYDAY=...`. An expander is unavoidable if we want a date-range view. [OBSERVED]

| Option | What it does | License | Maint. health | stdlib vs 3rd-party | Correctness caveats |
|---|---|---|---|---|---|
| **`dateutil.rrule` / `rruleset`** | `rrule` generates a datetime sequence from one RRULE; `rruleset` combines `rrule()/rdate()/exrule()/exdate()`; `rrulestr()` parses an `RRULE:`/`DTSTART:` string | dual **Apache-2.0 / BSD-3** (PSF-friendly) | Very healthy, ubiquitous | **3rd-party** (already a transitive dep of `icalendar`) | **Raw RRULE only.** It does **NOT** parse a full VEVENT, does **NOT** auto-ingest EXDATE/RDATE from an `.ics` (you call `.exdate()/.rdate()` with hand-built datetimes), and has **no concept of RECURRENCE-ID per-instance overrides** [OBSERVED]. Also a known footgun: tz-aware DTSTART + naive EXDATE → silently ignored exclusions. Using this alone = hand-rolling the hard 40%. |
| **`recurring-ical-events`** | Sits on top of `icalendar`: `recurring_ical_events.of(calendar).between(start, stop)` (and `.at(date)`) returns the **concrete occurrences**, correctly handling **RRULE + RDATE + EXDATE + RECURRENCE-ID modified/edited instances + deleted instances + DURATION + timezones (zoneinfo/pytz/X-WR-TIMEZONE) + all-day vs timed** | **LGPL-3.0** [OBSERVED] | **Active.** v3.8.2 released **2026-04-30**; 843 commits; 21 releases; issues triaged [OBSERVED] | **3rd-party**; depends on **`icalendar`** + **`python-dateutil`** (+ `x-wr-timezone`, `tzdata`) [OBSERVED] | This is the layer that *correctly* subtracts EXDATE and *substitutes* RECURRENCE-ID overrides — the thing dateutil makes you do by hand. **LGPL-3.0** note: it's a library used unmodified via its public API, so dynamic-linking/separate-module use is standard; for a single-user internal tool this is low-risk, but flag it for the license review. |

**Expansion verdict:** `recurring-ical-events` for the real work; it *uses* dateutil internally so we
get the proven rrule engine without owning the EXDATE/override wiring. Reserve bare `dateutil.rrule`
only for a hypothetical "preview an RRULE the user is typing" with no exceptions.

---

## Part C — RFC 5545 / 7986 facts that govern faithful round-trip

- **Mandatory on a VEVENT:** `UID` (REQUIRED, globally-unique, persistent) and `DTSTAMP` (REQUIRED);
  `DTSTART` is REQUIRED when no `METHOD` is present. Each MUST NOT repeat. [OBSERVED, RFC 5545 §3.6.1]
- **Recurrence set construction (the rule the store must honor):** the final occurrence set =
  all start DATE-TIMEs from `RRULE` **and** `RDATE`, **minus** every `EXDATE`; **EXDATE takes
  precedence** over inclusion. [OBSERVED, RFC 5545 §3.8.5.1/.2/.3]
- **Override identity (the landmine):** a modified or cancelled single occurrence is a **separate
  component that shares the series `UID`** and carries a **`RECURRENCE-ID`** equal to the
  *original* (unmodified) start of the instance it replaces. `RECURRENCE-ID` is OPTIONAL and singular.
  [OBSERVED, RFC 5545 §3.8.4.4 / §3.6.1]
- **iCalUID vs per-instance id (provider mapping):**
  - **Google:** all occurrences of a series **share one `iCalUID`** but have **different `id`s**;
    an instance points to its parent via **`recurringEventId`** and identifies itself via
    **`originalStartTime`** (stable even if the instance is moved); a cancelled instance is a normal
    event object with **`status:"cancelled"`** retaining those two fields; `recurrence[]` holds the
    RFC-5545 lines, and **`DTSTART`/`DTEND` live in `start`/`end`, not in `recurrence`**. [OBSERVED]
  - **Microsoft Graph:** event `type` ∈ {`singleInstance`,`occurrence`,`exception`,`seriesMaster`};
    the series is a `seriesMaster` carrying `recurrencePattern`+`recurrenceRange` (**structured, not an
    RRULE string**); a modified instance becomes `type:"exception"` linked by **`seriesMasterId`**.
    [OBSERVED] → **Graph must be translated to/from RRULE on the boundary.**
- **RFC 7986** adds `COLOR`, `IMAGE`, `CONFERENCE`, richer `NAME`, etc.; `icalendar`'s generic
  property model can hold these, but several map to provider-proprietary JSON (Google `colorId`,
  Graph `onlineMeeting`) → keep them in the **sidecar** to round-trip exactly. [CORROBORATED]

**Round-trip implication:** key the **series** by `iCalUID`; key an **instance/override** by
`(iCalUID, RECURRENCE-ID == original-start)`. Store the provider's own `id`/`etag`/`seriesMasterId`/
`recurringEventId` in the sidecar so Anchor can PATCH the right resource back without re-deriving it.

---

## Recommended store design (concrete)

```
.anchor/calendar/
  <account-id>/
    sync.json                     # provider sync tokens / deltaLink, last-sync ts
    events/
      <icalUID>.ics               # canonical RFC 5545 VCALENDAR: the series VEVENT
                                  #   + one extra VEVENT per RECURRENCE-ID override/cancellation
      <icalUID>.meta.json         # sidecar: provider id, etag, recurringEventId/seriesMasterId,
                                  #   colorId, onlineMeeting/conferencing, raw extended props,
                                  #   source provider, last-modified, deletion tombstone
```

- **Write path (provider → disk):** normalize each provider event into a `VCALENDAR` via
  `icalendar` (translating Graph's `recurrencePattern`/`Range` → `RRULE`); store proprietary fields
  in `*.meta.json`. One file per *series* (overrides are sibling VEVENTs inside the same VCALENDAR,
  RFC-5545-correct).
- **Read/expand path (disk → widget):** load the `.ics` with `icalendar`, then
  `recurring_ical_events.of(cal).between(range_start, range_stop)` → concrete instances with
  EXDATE/override/tz already applied. Render those. **Cache nothing expanded** (cheap to recompute;
  avoids stale-instance bugs).
- **Write-back (Anchor edits → provider):** re-serialize the VCALENDAR; use the sidecar's provider
  `id`/`etag`/`seriesMasterId` to PATCH the correct resource and the correct *instance* for an
  override.
- **Degraded mode (extra absent):** read the sidecar JSON + display already-stored instances; surface
  a banner that fresh recurrence expansion needs `pip install .[calendar]`. Lazy import in a single
  `calendar_store.py` seam, mirroring the `pywinpty` pattern.

### Trade-offs (stated)

- **iCalendar-canonical vs raw-JSON:** canonical gives a single internal model + free expansion +
  faithful Google interop; cost is a Graph translator and a sidecar for proprietary fields. Raw-JSON
  avoids a translator on ingest but needs one per *consumer* (the expander can't read Graph), and
  gives you two divergent schemas to reconcile — worse for a "no data loss, both providers" goal.
- **`recurring-ical-events` (LGPL-3.0) in the extra:** the only turnkey correct expander, but LGPL.
  Used unmodified via its API in an optional, separately-installed extra of a single-user internal
  tool — low practical risk, but **flag for license sign-off**. If LGPL is unacceptable, fallback is
  `dateutil.rrule` + a hand-written EXDATE/RECURRENCE-ID layer (more code, more bug surface) or the
  Apache/MIT `ical`/`ical-library` stacks (less proven against provider quirks).
- **Two new deps in `[calendar]`:** `icalendar` + `recurring-ical-events` (and transitively
  `python-dateutil`, `tzdata`, `x-wr-timezone`). All pure-Python, no native build — consistent with
  the no-native-asset rule; only the *terminal* extra carries a native dep.

---

## Sources (primary first)

- icalendar PyPI (v7.1.3, BSD-2, dateutil dep, parses-not-expands) — https://pypi.org/project/icalendar/ **[OBSERVED]**
- recurring-ical-events PyPI (features: RRULE/RDATE/EXDATE/RECURRENCE-ID/deleted/DURATION/tz/all-day) — https://pypi.org/project/recurring-ical-events/ **[OBSERVED]**
- recurring-ical-events GitHub (LGPL-3.0, v3.8.2 2026-04-30, 843 commits) — https://github.com/niccokunzmann/python-recurring-ical-events **[OBSERVED]**
- ics.py issue #14 "Support recurring events" (open since 2013, milestone 0.8, unresolved) — https://github.com/ics-py/ics-py/issues/14 **[OBSERVED]**
- ics.py docs (no full RFC 5545 / no RRULE) — https://icspy.readthedocs.io/en/stable/misc.html **[CORROBORATED]**
- dateutil rrule docs (rrule/rruleset/rrulestr; raw RRULE only, manual exdate/rdate, no VEVENT/RECURRENCE-ID) — https://dateutil.readthedocs.io/en/stable/rrule.html **[OBSERVED via doc source + search]**
- RFC 5545 (UID/DTSTAMP required; EXDATE precedence; RECURRENCE-ID) — https://datatracker.ietf.org/doc/html/rfc5545 ; §3.6.1 — https://icalendar.org/iCalendar-RFC-5545/3-6-1-event-component.html **[OBSERVED]**
- Google Calendar API recurring events (recurrence[]=RFC5545 lines, shared iCalUID, recurringEventId, originalStartTime, status:cancelled, DTSTART/END in start/end) — https://developers.google.com/workspace/calendar/api/guides/recurringevents **[OBSERVED]**
- Microsoft Graph event types + recurrencePattern/recurrenceRange (structured, not RRULE; seriesMaster/occurrence/exception; seriesMasterId) — https://learn.microsoft.com/en-us/graph/api/resources/recurrencepattern , https://learn.microsoft.com/en-us/graph/api/resources/recurrencerange , https://learn.microsoft.com/en-us/graph/api/resources/event **[OBSERVED via search of primary docs]**
- iCal-library / ical (allenporter) as alt stacks — https://jorricks.github.io/iCal-library/ , https://pypi.org/project/ical/ **[CORROBORATED]**

### Evidence-quality flags
- **Graph `recurrencePattern` being structured (not an RRULE string)** is the single most
  consequential round-trip fact and is **OBSERVED** from Microsoft Learn primary docs (via search
  snippets of the primary pages; direct fetch was rate-limited — recommend a confirming fetch in a
  follow-up if treated as load-bearing for the Graph translator design).
- recurring-ical-events feature list is **OBSERVED** from its PyPI page; the per-feature behavior of
  RECURRENCE-ID substitution is corroborated by RFC 5545 §3.8.4.4 semantics.
- dateutil "no RECURRENCE-ID / no VEVENT auto-ingest" is **OBSERVED** from the rrule doc (it only
  documents rrule/rruleset/rrulestr; no VEVENT API exists).
