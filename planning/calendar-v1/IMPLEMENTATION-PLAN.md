# Anchor Calendar v1 — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-20. Frozen design: `MASTER-PLAN.md`.
> Build cwd = repo root `C:\dev\Anchor`. Suggested branch: `foreman/calendar-v1` (off master).
> North Star + falsifiers are in `MASTER-PLAN.md §1` — every wave serves them.

test-command: python -m pytest -q

## Conventions (read before any wave)

- **No live Google / Microsoft, ever, in any test or healthcheck.** All HTTP goes through a
  fake-responder seam (monkeypatch the `urllib`/client transport → `tests/fake_calendar_api.py`).
  No real OAuth dance, no real network, no real DPAPI key material in CI logic.
- **The `[calendar]` extra is opt-in + lazy + degrading.** `msal`, `google-auth`, `icalendar`,
  `allenporter/ical` (PyPI `ical`) are imported LAZILY inside the calendar modules only, exactly
  like `pywinpty` in `pty_manager.py`. With the extra absent, `import`-ing the calendar modules
  must succeed and surface a `CalendarUnavailable` ("calendar unavailable"), never a stack trace.
  `distro.py`'s import scan gets a NEW scoped allowlist entry for the calendar module(s) only;
  the core import path must stay stdlib-clean WITHOUT the extra (asserted in Wave 1).
- **Safety rail (falsifier a):** Anchor only ever issues create/update/delete against the
  dedicated Anchor-owned calendar it creates per provider. It NEVER holds a write/delete handle
  on any other calendar. Enforced in code (the push client refuses a non-Anchor calendar id) and
  tested negatively.
- **Render reads cache only (falsifier e):** the dashboard/calendar view reads
  `.anchor/calendar/state.json`; it never makes a sync network call on render.
- **Token storage:** DPAPI user-scope via `ctypes` `CryptProtectData` (service runs as `.\john`).
  The token store tolerates 7-day expiry / `invalid_grant` by surfacing a re-auth state, never a
  silent stop (Shark finding #3).
- **UI verification (the v4 lesson)** for UI-changing waves (3): rendered-DOM assertions
  (positive + negative) + a real Playwright + Chromium interaction test + a screenshot + John's
  sign-off before the wave is GREEN. Playwright stays DEV-ONLY (`pytest.importorskip`), never
  imported by product code.
- **Spikes gate, they don't block planning:** the 8-day durable-refresh spike gates Wave 4
  shipping; the Graph-recurrence enumeration spike gates the Wave 5 estimate (run it first).
- **Baseline:** the current suite is GREEN (1232). Each wave holds or grows it.

---

## Wave 1 — Event store + `[calendar]` extra foundation

**Goal.** A faithful on-disk calendar event store and the declared optional dependency surface —
the substrate every later wave reads/writes — with the stdlib invariant provably intact.

**Changes.**
- `paths.calendar_dir()` → `data_dir()/.anchor/calendar/` (+ per-account subdirs); `.anchor/`
  already excluded from every distro build.
- New `calendar_store.py` (repo root, first-party): write/read an event series as RFC-5545
  `.ics` at `<account>/events/<icalUID>.ics` (one VEVENT per series; RECURRENCE-ID overrides are
  sibling VEVENTs sharing the UID, keyed `(iCalUID, original-start)`) + a `meta.json` sidecar
  retaining provider `id`/`etag`, Google `recurringEventId`, **Graph `seriesMasterId`/`type` +
  the raw Graph JSON** (lossless source for Graph-only recurrence), colorId, sync tokens.
  `state.json` projection (the flat, render-only occurrence cache) is written here too.
- Markdown-deadline → store mapping (Anchor-authored deadlines become Anchor-owned events).
- `pyproject.toml`: declare `calendar = ["msal", "google-auth", "icalendar", "ical"]`.
- `distro.py`: add the scoped calendar allowlist entry; keep the single `pywinpty` exception.

**Done-when.** A round-trip (write a recurring series with an override → read it back) is byte-
faithful incl. the raw-Graph-JSON sidecar; AND `distro.py`'s scan is green AND importing the core
app WITHOUT the `[calendar]` extra still succeeds (calendar modules surface `CalendarUnavailable`).

**Given/When/Then.**
- *Given* a series with an RRULE + one EXDATE + one RECURRENCE-ID override, *When* written then
  re-read via `calendar_store`, *Then* the `.ics` + sidecar reproduce all three faithfully and the
  override resolves by `(iCalUID, original-start)` (no ghost/duplicate occurrence).
- *Given* the `[calendar]` extra is NOT installed, *When* the core app imports + `calendar_store`
  is imported, *Then* the core import path is stdlib-clean (distro scan green) and the calendar
  module raises/exposes `CalendarUnavailable`, never an `ImportError` stack trace.

---

## Wave 2 — Auth (PKCE + loopback + DPAPI; msal/google-auth wrappers)

**Goal.** A connect-once-per-provider OAuth flow that yields a durable, DPAPI-protected token the
background poller can refresh unattended — Production-posture, 7-day-tolerant.

**Changes.**
- New `calendar_auth.py`: PKCE (S256) Auth-Code flow over thin wrappers on `msal` (Microsoft) +
  `google-auth`/`google-auth-oauthlib` (Google); installed/desktop client; loopback
  `http://127.0.0.1:<ephemeral>/callback` (never `localhost`, never 8777); `webbrowser.open()`
  consent; state-CSRF echo check. Persist the (rotated) refresh token DPAPI-wrapped in
  `.anchor/calendar/<provider>.json`. Assume PKCE-S256 for Microsoft regardless of its discovery
  doc (the OBSERVED spike quirk).
- Token-lifecycle: refresh on use; on `invalid_grant`/token-loss set a persisted
  `needs_reauth` flag (consumed by the UI in Wave 3) — never a silent failure.
- HTTP routes: `do_GET` += `/api/calendar/connect` (mint verifier, open consent) +
  `/api/calendar/callback` (capture `?code=&state=`, finish PKCE); `do_POST` (token-authed) +=
  `/api/calendar/refresh` / `/api/calendar/disconnect`.
- Reuse the OBSERVED 2026-06-15 spike harness (`run-2026-06-15/spike/pkce_loopback_spike.py`).

**Done-when.** Through the fake-auth seam: connect → token DPAPI-wrapped at rest (ciphertext ≠
plaintext) → a simulated refresh round-trips → a simulated `invalid_grant` sets `needs_reauth`
(no exception escapes to the poller).

**Given/When/Then.**
- *Given* a completed (faked) consent, *When* the callback finishes PKCE, *Then* a refresh token
  is stored DPAPI-wrapped and is NOT readable as plaintext on disk.
- *Given* a stored token the provider has revoked, *When* the poller refreshes, *Then* the cycle
  sets `needs_reauth` + records a poll-failure timestamp and exits cleanly (Shark finding #3).

---

## Wave 3 — PULL pipe + EventCalendar display

**Goal.** See ALL of John's calendars, live, in a real month/week/day view — incremental, resync-
safe, and free of self-echo.

**Changes.**
- New `calendar_sync.py` PULL pipe: Google `events.list`+`syncToken` (page to the final
  `nextSyncToken`; `singleEvents=false`; deletions = `status:cancelled`; `410`→full resync) +
  Graph `GET /me/calendarView/delta` (follow `@odata.nextLink`; persist `@odata.deltaLink`; guard
  the `skipToken` infinite loop; token-loss→full resync). Normalize into `calendar_store`; expand
  recurrence for display via `ical` Timeline → `state.json`.
- **Exclude the Anchor-owned calendar id from the inbound/display set** (Shark finding #1,
  BLOCKER): Anchor's own events render from local state, never from a pull of its own calendar —
  no double-render.
- Background `threading.Thread(daemon=True)` poller (mirror `_trigger_session_summary`); render
  reads `state.json` ONLY. Copy vdirsyncer's empty-replica "replica went empty ⇒ abort, don't
  wipe" guard.
- UI: vendor **EventCalendar (vkurko, MIT)** into `vendor/event-calendar/` (**ship its LICENSE
  file**); replace the hand-typed `## Today's Calendar` block with a live, `WRITE_LOCK`-guarded
  month/week/day view + a visible `needs_reauth` / last-sync banner.

**Done-when.** Through the fake-API seam: an initial pull + an incremental delta render correct
occurrences (incl. one recurring series) in the view; a `410`/token-loss triggers a clean full
resync; the Anchor-owned calendar never appears twice; a `needs_reauth` flag shows the re-auth
banner. UI verification pack passes + John signs off.

**Given/When/Then.**
- *Given* the Anchor-owned calendar exists and holds a pushed event, *When* the pull pipe runs,
  *Then* that event renders exactly once (from local state), never duplicated by an inbound pull.
- *Given* a recurring series with an override from the fake API, *When* pulled + expanded, *Then*
  the view shows the correct occurrences with the override applied and no ghost instance.
- *Given* a `410 GONE`, *When* the next pull runs, *Then* the local mirror is rebuilt by full
  resync without losing the Anchor-owned events (empty-replica guard holds).

---

## Wave 4 — PUSH pipe to the dedicated Anchor-owned calendar

**Goal.** Push John's Anchor-authored events OUT to a calendar Anchor owns in each provider —
idempotent, echo-free, and structurally incapable of touching a human event.

> **GATE:** ship only after the 8-day durable-refresh spike confirms the Production token survives
> (`run-2026-06-15/spike/RUNBOOK.md` step 5). The pipe can be BUILT + stub-tested before the spike
> resolves; it is not enabled against a real account until the spike is green.

**Changes.**
- `calendar_sync.py` PUSH pipe: ensure-exists the dedicated **"Anchor"** calendar per provider
  (create if absent; persist its id). Upsert Anchor-owned events by `iCalUID`
  (Google `events.insert/patch`; Graph `POST/PATCH /me/calendars/<anchorId>/events` with
  `transactionId` for idempotent create). Optimistic concurrency via ETag/`If-Match` (`412`→
  refetch). Echo-suppress: stamp a self-marker + record the returned ETag; the next inbound delta
  carrying our marker+etag is dropped.
- **Hard safety guard:** the push client asserts the target calendar id == the stored Anchor-owned
  id and REFUSES any other id (falsifier a) — tested negatively.

**Done-when.** Through the fake-API seam: an Anchor event upserts into the Anchor-owned calendar
(idempotent on re-run — no duplicate), the echo-suppressor drops the round-tripped delta, AND an
attempt to push to a non-Anchor calendar id is refused.

**Given/When/Then.**
- *Given* an Anchor-authored event, *When* push runs twice, *Then* exactly one remote event exists
  (idempotent by `iCalUID` + `transactionId`).
- *Given* a pushed event that returns in the next pull delta with our self-marker, *When* the pull
  processes it, *Then* it is echo-suppressed (no duplicate, no fight with local state).
- *Given* any calendar id ≠ the stored Anchor-owned id, *When* a write is attempted, *Then* the
  push client refuses (safety rail).

---

## Wave 5 — Recurrence hardening

**Goal.** Make the Graph `recurrencePattern` ↔ RRULE boundary correct-or-honest — clean RRULE
where possible, explicit sidecar-only fallback where Graph is lossy.

> **GATE:** run the 1-day Graph-recurrence enumeration spike FIRST; its lossy-cell count sizes
> this wave. The fixture table is the test corpus.

**Changes.**
- Enumerate every Graph `recurrencePattern` variant (daily / weekly / absoluteMonthly /
  relativeMonthly / absoluteYearly / relativeYearly × single & multiple `daysOfWeek` × `index`
  first/second/third/fourth/last) into `tests/fixtures/graph_recurrence/`. For each: assert a
  clean RRULE round-trip OR flag it **sidecar-only, not RRULE-expressible** and render from the
  retained raw Graph JSON.
- Override identity `(iCalUID, original-start)` correctness across both providers; never rewrite a
  series `DTSTART`.

**Done-when.** Every fixture variant either round-trips RRULE cleanly OR is explicitly served from
the sidecar (no silent wrong occurrence); the lossy-cell set is documented; override/cancellation
instances render correctly with no ghosts/duplicates.

**Given/When/Then.**
- *Given* a `relativeMonthly` pattern with multiple `daysOfWeek` (the known lossy cell), *When*
  expanded for display, *Then* occurrences come from the raw-JSON sidecar path and match Graph's
  "first day that satisfies" semantics — not a wrong RRULE guess.

---

## Wave 6 — Ship: CLI mirror + healthcheck + distro + docs (PROJECT DONE)

**Goal.** Make the surface inspectable, self-tested, distributable, and documented.

**Changes.**
- `anchor.py` read-only mirror: `cal status` (linked providers, last-sync, `needs_reauth`,
  counts) + `cal pull` (one foreground incremental pull) — honest-absent when unconfigured.
- `anchor_healthcheck.py` += `check_calendar_surface`, **fully stubbed** (fake-API seam + temp
  `ANCHOR_DATA_DIR` + no DPAPI key material): walk connect (faked) → DPAPI round-trip → store
  round-trip → PULL+expand → exclude-own-calendar → PUSH upsert+echo-suppress → safety-rail
  refusal → restore env/teardown. Never live Google/MS; never binds `:8777`.
- `distro.py` scan stays green (scoped `[calendar]` allowlist only; Playwright never in product
  code). Update `CLAUDE.md` (the calendar surface + the `[calendar]` extra + the safety rail).

**Done-when.** `cal status`/`cal pull` mirror the live data read-only; `check_calendar_surface`
runs fully stubbed and GREEN inside the existing healthcheck; `distro.py` scan green; `CLAUDE.md`
documents the surface. Full suite GREEN (≥ baseline).

**Given/When/Then.**
- *Given* a stubbed project with a connected (faked) provider, *When* `check_calendar_surface`
  runs, *Then* it walks the full connect→store→pull→push→safety-rail path, touches no real
  network and no `:8777`, and restores all env + temp dirs.

---

## Project DONE

The project is DONE when **Wave 6** is GREEN: all six waves' acceptance criteria met, the full
pytest suite green at or above baseline, `distro.py` clean, and `CLAUDE.md` updated. The 8-day
durable-refresh spike must be green before Wave 4 is enabled against a real account (it does not
block the build/merge of the stubbed pipe).
