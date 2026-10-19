# Agent / Implementation Handoff — Anchor ⇄ Calendar Integration

For a Crucible/Foreman build agent. All claims are doc-corroborated, not code-observed — run the spike (last section) first.

## Locked architecture (do not re-litigate)
- **Transport: POLLING only.** No webhooks (localhost can't receive Google/Graph push — needs public HTTPS+CA cert). Google `events.list`+`syncToken`; Graph `/me/calendarView/delta`. Handle `410 GONE` / token-loss → full resync as a NORMAL path. Poll on a `threading.Thread(daemon=True)` (mirror `anchor_gui._trigger_session_summary`); render reads cached `.anchor/calendar/state.json` ONLY — never a sync network call on render.
- **Two native REST clients:** Google Calendar API v3 + Microsoft Graph. CalDAV is out (MS has none).
- **Auth:** OAuth 2.0 Auth-Code + **PKCE**, **installed/desktop client type** (no embeddable secret; a "Web" client's secret would trip `distro.py`'s no-secrets scan). Loopback redirect `http://127.0.0.1:<ephemeral>/callback` — MUST NOT reuse 8777 (`SO_EXCLUSIVEADDRUSE`). `webbrowser.open()` for one-time consent.
- **OAuth lib decision (Judge, ratify with John):** declare a `[calendar]` optional extra (`msal` + `google-auth`), lazy-imported in the calendar module only, gated/declared like `pywinpty` in `pyproject.toml` + `distro.py`'s allowlist, degrade to "calendar unavailable" when absent. Still DPAPI-wrap the token cache.
- **Token at rest:** DPAPI `ctypes.windll.crypt32.CryptProtectData` (user scope — service runs as `.\john`, confirmed `sc qc anchor`). Document the user+machine-bound migration footgun (profile/machine change → re-auth).

## Build phases (Foreman waves)
- **Phase A — pull + display.** Google first, then Microsoft. One-time PKCE grant per provider → DPAPI-store refresh token in `.anchor/calendar/<provider>.json`. Background poll → normalize → cache `state.json` → regenerate the `## Today's Calendar` block in DASHBOARD.md under `WRITE_LOCK`. Read-only = near-zero blast radius.
- **Phase B — one-way push of Anchor-authored deadlines** into a **dedicated "Anchor" calendar Anchor creates in each provider** (the key safety rule — Anchor never writes to the user's primary calendar / never holds a delete handle on human events). Upsert by `iCalUID`; store returned ETag.
- **Phase C — full symmetric two-way (DEFERRED; earned by demand).** Only over the Anchor-authored subset. Requires the full mapping table + three-way-merge engine. If two-way over ARBITRARY events is required, FIRST replace the markdown-line model with a richer ICS/JSON event store under `.anchor/calendar/` (markdown can't represent RRULE/EXDATE/VTIMEZONE/attendees — lossy by construction).

## Two-way engine spec (Phase C)
Mapping table, one row per (local_item × provider): `{ical_uid, provider, calendar_id, remote_event_id, remote_etag, last_synced_state, local_content_hash, deleted_tombstone, provenance_marker}` + per-provider `sync_token`/`delta_link`, `last_sync_at`.
Per cycle: pull deltas (410→full resync) → **echo-suppress** (drop inbound events whose provenance_marker is ours AND etag == the one we recorded) → detect local changes (content hash vs baseline) → classify each pair via **three-way compare to last_synced_state** (Unison/vdirsyncer model): local-only→push, remote-only→apply(or surface, master-wins), both→CONFLICT(master-wins + surface remote value), neither→noop → handle deletions with tombstones (never resurrect) → recurring: map series by `iCalUID`, overrides by `RECURRENCE-ID`; never rewrite series `DTSTART` → write + record new ETag + stamp marker → persist tokens atomically. Idempotent: match by `ical_uid`+row before any create.
Top failure modes to test: echo loop, recurring corruption, duplicate-by-name-match, deleted resurrection, stale-after-410, cross-system clock-skew (never compare Google vs MS vs local timestamps directly).

## Provider gotchas (encode as tests)
- Google: `nextSyncToken` only on the FINAL page; pull recurring `singleEvents=false`; deletions = `status:cancelled`; **Production publishing status** (escape the 7-day Testing-mode RT revoke); calendar = sensitive scope.
- Graph: persist the ROTATED refresh token each refresh; guard the `calendarView/delta` infinite-skipToken loop; `transactionId` for idempotent create; confirm MSA vs work/school authority (`/common` vs `/consumers`); `@odata.etag`/`If-Match` → 412.

## Testing (non-negotiable)
Fully-stubbed `check_calendar_surface` healthcheck like v2–v7: a fake HTTP responder seam (monkeypatch `urllib`/the client), walk PKCE → DPAPI round-trip → PULL → reconcile → restore env/teardown. **NEVER live Google/MS.** Per-wave: stubbed healthcheck GREEN + (for UI) DOM assertions + Playwright + screenshot + sign-off.

## Modules / routes / CLI
- New: `calendar_auth.py`, `calendar_sync.py` (repo root). `paths.calendar_dir()`. CLI read-mirror in `anchor.py`: `cal status`, `cal pull`.
- `do_GET` += `/api/calendar/connect`, `/api/calendar/callback`. `do_POST` += token-authed `/api/calendar/refresh`, `/api/calendar/disconnect`.

## DO FIRST — de-risking spike (~50 LOC, before Phase A commit)
Run the full loopback+PKCE dance against ONE real Google + ONE real M365 app registration; fetch one page of events; leave the token 8 days and confirm it still refreshes (validates the Production-unverified durable-RT claim — the riskiest unspiked finding). Converts the feasibility claims from CORROBORATED → OBSERVED.
