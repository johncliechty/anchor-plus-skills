# Anchor ⇄ Calendar Integration — researchPrime Full Report

**Date:** 2026-06-15 · **Skill:** researchPrime · **Mode:** ENGINE-capable host (node v26.1.0, import-spike go:true, 28 trio symbols)
**Adversarial verification:** RAN — 5 fresh-context research lanes → 2 heterogeneous refuters (tasked to break the load-bearing claims) → 1 context-free Judge. (The Node governor's import probe was GO; its in-process agent slots cannot reach the live sub-agent host, so the adversarial *substance* was driven through real context-isolated sub-agents. `cross_model: false`.)
**ISOLATION:** orchestrator = approximated; the 5 lanes + 2 refuters + Judge = real (separate sub-agent contexts).
**Evidence ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED. See `evidence-ledger.jsonl`.
**Locked intent (John, 2026-06-15):** a calendar in Anchor that imports Google + Outlook/M365 calendars, pulls them in, and pushes events back — i.e. **full bidirectional, multi-provider sync.**

> **Provenance note:** This is a NEW effort. The two prior researchPrime runs on disk (`.anchor/projects/.../research/`, dated 2026-06-10 and 2026-06-11) are both *"Anchor Brownfield Orientation"* reports — neither concerned calendars. No prior calendar research artifact existed; this report is the first.

---

## 1. Bottom line (read this first)

**Your goal is buildable.** Multi-provider two-way calendar sync can be built into Anchor. But the validated evidence reshapes *how* it should be built on three points, two of which are decisions only you can make:

1. **Architecture is forced, and it's clean: POLL, don't webhook.** A localhost-only service physically cannot receive Google or Microsoft push notifications (both demand a public, CA-certified HTTPS endpoint). The supported, robust path is **periodic polling** — Google `events.list`+`syncToken`, Microsoft Graph `/delta` — which works perfectly from behind your loopback bind and needs no inbound port, no tunnel, no public surface. This *preserves* Anchor's local/private posture. **[CORROBORATED across 4 lanes incl. a hostile refuter]**

2. **CalDAV is a dead end; you need two native REST clients.** Microsoft has no CalDAV endpoint at all (only Graph). Google has CalDAV but its REST API is better. So the design is **Google Calendar API v3 + Microsoft Graph**, two thin stdlib HTTP clients. **[CORROBORATED]**

3. **Two genuine forks — your calls (see §2):** *(a)* hand-roll the OAuth layer in pure stdlib **vs.** declare a `[calendar]` pip-extra (the Judge ruled: declare the extra); *(b)* full symmetric two-way **vs.** phase it as pull + one-way-push first (the Judge ruled: phase it — but the scope is yours to lock).

**Most dangerous risk + its cheap fix:** a two-way sync bug that silently **deletes or duplicates real events** in your actual Google/Outlook calendars (irreversible, blast-radius *outside* Anchor). The Judge's de-risking step costs one config field: **Anchor reads from all your calendars but only ever writes to a dedicated "Anchor" calendar it owns** in each provider — so it never holds a delete/update handle on an event a human created.

---

## 2. The two decisions only you can make

### Decision A — How to do OAuth: hand-roll vs `[calendar]` extra
- **Technically, pure stdlib is feasible** (~600–1200 LOC: `urllib`+`http.server`+`ssl`+`secrets`+`hashlib` for OAuth2-PKCE and the two REST clients, `ctypes`→DPAPI for token-at-rest). One crack: local `id_token` *signature* verification is NOT pure-stdlib (no RSA verify in `hashlib`) — avoidable by simply not verifying the id_token locally (trust the TLS-protected token response). **[CORROBORATED]**
- **But the Judge ruled against hand-rolling.** Reason: the `[terminal]=pywinpty` exception is the *exact* precedent — "stdlib-only" is Anchor's **distribution/portability** rule, with a documented, scoped, lazily-imported, gracefully-degrading optional-extra escape hatch. Security-critical OAuth token-lifecycle (refresh rotation, `invalid_grant` recovery, clock-skew, the 7-day/90-day expiry interplay) is the *silent-failure* class — you'd find out two weeks after sync quietly died. `msal` is **Microsoft's own** library; `google-auth` is Google's. They inherit vendor security teams and absorb API drift for free. Still DPAPI-wrap the token cache; just let the libraries own the lifecycle.
- **Verdict (Judge, HIGH confidence): declare a `[calendar]` optional extra** (`msal` + `google-auth`), lazy-imported and gated exactly like `pywinpty`, degrading to "calendar unavailable" when absent. *This is the one place to relax the stdlib rule — and the codebase is already built to.* **→ your call to ratify.**

### Decision B — How much to build: full two-way vs phased
- You asked for full bidirectional sync. The red-team's strongest surviving point: **the markdown-line data model is lossy by construction.** A line like `— Due: 2026-04-15` cannot represent RRULE recurrence, EXDATE overrides, VTIMEZONE, or attendees. Round-tripping *arbitrary* Google/Outlook events through markdown-as-source-of-truth would **manufacture** the exact danger-zone failures (recurring-event corruption, deletion resurrection, data loss). **[CORROBORATED]**
- **Verdict (Judge, MED-HIGH): phase it.** Anchor can faithfully *own* the simple events it authors (deadlines/tasks), but should not try to be the *editor* of arbitrary inbound events. Build order:
  - **Phase A — read-only PULL + display** (Google then Microsoft): poll, render a live calendar in Anchor. Near-zero blast radius, fully reversible. Delivers most of your day-to-day "see my calendar" need.
  - **Phase B — one-way PUSH of Anchor-authored deadlines** into Anchor's own dedicated calendar in each provider. No echo-loop, no reconciliation — just upsert-by-`iCalUID`.
  - **Phase C — full symmetric two-way** over the Anchor-authored subset, with the full mapping-table + three-way-merge engine. **Earned by demand, not pre-committed.**
- **What's yours to decide:** whether Phase A+B satisfies you, OR full symmetric two-way over *arbitrary* events stays a hard requirement. **If it does**, the markdown-line model must be replaced by a richer event sidecar (an ICS/JSON event store under `.anchor/calendar/`) *before* two-way is safe — that data-model consequence is part of the choice.

---

## 3. How sync actually works (the validated mechanics)

**Pull (incremental, both providers):**
- **Google:** initial full `events.list` → store `nextSyncToken` (returned only on the *final* page — page to completion first); later calls pass `syncToken` for changes-only; **`410 GONE` → wipe local mirror + full resync** (a normal path, not an error). Deletions arrive as `status:"cancelled"`. Pull recurring series **un-expanded** (`singleEvents=false`) — sync the RRULE + overrides, never expanded instances. **[CORROBORATED]**
- **Microsoft Graph:** `GET /me/calendarView/delta` (or `/events/delta`) → follow `@odata.nextLink` to completion → persist `@odata.deltaLink`; reuse it next cycle. Deletions via `@removed`. Token loss → full resync (same as Google's 410). Guard against a known `calendarView/delta` infinite-`skipToken` loop (cap iterations / detect non-progress). **[CORROBORATED]**

**Cadence:** polling is the supported path; **5–15 min foreground / hourly background is the proven norm** (Morgen syncs hourly; Google's quota — 600 req/user/min — gives enormous headroom). Run polls on a **background daemon thread** (the exact pattern `anchor_gui._trigger_session_summary` already uses); the dashboard render reads only a cached `.anchor/calendar/state.json` — **never a synchronous network call on render**. **[OBSERVED, codebase]**

**Push / write-back (Phase B+):** Google `events.insert/patch/update/delete`; Graph `POST/PATCH/DELETE /me/events`. Cross-system identity = **`iCalUID`/`iCalUId`** (shared across calendars; distinct from the per-calendar `id`). Optimistic concurrency = **ETag + `If-Match`** (stale → `412`). Idempotent create on Graph via **`transactionId`**. **[CORROBORATED]**

**Two-way correctness (Phase C) — the hard part:** persist a **mapping table** (one row per local-item × provider): `{ical_uid, provider, remote_event_id, remote_etag, last_synced_state, local_content_hash, deleted_tombstone, provenance_marker}` + the per-provider sync token. Reconcile via a **three-way merge against the last-synced baseline** (the Unison / vdirsyncer model): compare each side to the baseline, not to each other, so you know *which* side changed. **Echo-loop suppression** = stamp Anchor's own writes (self-marker + record the returned ETag; ignore the next delta carrying it). **Tombstones** prevent deleted-event resurrection. **Recurring events** = map series by `iCalUID`, overrides by `RECURRENCE-ID`/`originalStartTime`; never rewrite a series `DTSTART` (it nukes all exceptions). **[CORROBORATED; vdirsyncer is the canonical open-source algorithm]**

**Top failure modes, ranked:** (1) echo/ping-pong loop, (2) recurring-event corruption, (3) duplicate creation from matching-by-name instead of mapping-row, (4) deleted-item resurrection, (5) stale-after-410, (6) clock-skew mis-resolution (never compare Google's `updated` vs Microsoft's vs local mtime as if globally comparable). **The "Anchor-owns-only-its-own-calendar" rule (§1) structurally eliminates #2 and #4 for real events.**

---

## 4. Auth & security (validated)

- **Flow:** OAuth 2.0 **Authorization Code + PKCE**, **installed/desktop client type** (NOT a "Web" client — a Web client expects a `client_secret` you can't safely embed, and would trip `distro.py`'s no-secrets scan). PKCE removes the need for a confidential secret for both providers. **[CORROBORATED]**
- **Redirect:** loopback `http://127.0.0.1:<ephemeral-port>/callback` (use `127.0.0.1`, not `localhost`; Google deprecated the old OOB flow). The transient catcher must NOT collide with 8777 (which binds `SO_EXCLUSIVEADDRUSE`). The existing `do_GET` if/elif dispatch can host the callback route; `webbrowser.open()` (already imported) pops the one-time consent. **[OBSERVED + CLAIMED]**
- **Google publishing trap:** in **"Testing"** mode, refresh tokens for the sensitive `calendar` scope are **revoked every 7 days**. Move the OAuth app to **"Production"** (may remain *unverified* for personal single-user use — the 100-new-user cap + "unverified app" consent warning are non-issues for one user). Production removes the 7-day cap. **Calendar is a *sensitive* (not restricted) scope** → lighter verification, no mandatory third-party security assessment. **[CORROBORATED]**
- **Microsoft:** refresh tokens **rotate** — you (or `msal`) must persist the new RT on every refresh. Personal MSA vs work/school tenant changes consent + token semantics and the `/common` vs `/consumers` authority choice; a Conditional-Access tenant can force unpredictable interactive re-auth. **[CORROBORATED]**
- **Token at rest:** DPAPI via `ctypes` `CryptProtectData` (no pywin32). **Service identity RESOLVED 2026-06-15: the `anchor` service runs as `.\john`** (`sc qc anchor` → `SERVICE_START_NAME : .\john`), NOT LocalSystem — so **DPAPI user-scope is the correct primitive** and the one-time browser consent can run in John's interactive session. (This corrects a stale "LocalSystem" note in the runtime-facts memory.) Caveat: DPAPI blobs are **user+machine bound** — a machine migration / profile-SID change makes stored tokens permanently undecryptable → silent re-auth required; document this. **[OBSERVED]**
- **Blast radius:** a DPAPI-wrapped blob under `.anchor/calendar/` is useless off John's account/machine; an attacker needs code-exec *as john*. This is **strictly better** than the surrounding tooling (the `claude`/`gemini` OAuth creds on this box are plaintext JSON). `.anchor/` is already excluded from every distro build. **[CORROBORATED]**

---

## 5. Where it plugs into Anchor

- **New modules (repo root, auto-first-party, pass the import scan):** `calendar_auth.py` (PKCE, loopback callback completion, DPAPI wrap/unwrap, refresh — or thin wrappers over `msal`/`google-auth` if Decision A = extra) and `calendar_sync.py` (REST clients + reconcile). Mirror read-only inspection into `anchor.py` (`cal status` / `cal pull`).
- **Storage:** add `paths.calendar_dir()` → `data_dir()/.anchor/calendar/`; store per-provider `<provider>.json` (DPAPI-wrapped refresh token + non-secret metadata + sync token) and `state.json` (the events cache the render path reads).
- **HTTP routes:** `do_GET` += `/api/calendar/connect` (mint verifier, open consent) and `/api/calendar/callback` (capture `?code=&state=`, finish PKCE); `do_POST` += token-authed `/api/calendar/refresh` / `/api/calendar/disconnect`.
- **Display:** the dashboard already renders a **hand-typed** `## Today's Calendar` block in DASHBOARD.md — the natural Phase-A target (replace hand-typed with a live, `WRITE_LOCK`-guarded, poll-generated block).
- **Testing:** mirror the established **fully-stubbed** healthcheck pattern — point a `urllib`/HTTP seam at a fake responder, walk PKCE→token-store(DPAPI round-trip)→PULL→reconcile, restore env + teardown; **never hit live Google/MS in tests.** Build it the trio way: a frozen `planning/calendar-v1/` design + Foreman wave plan, every wave stubbed-healthchecked and UI-signed-off (the v2–v7 standard).

---

## 6. Honest limits of this research (correlated blind spots)
- **All findings are doc-corroborated, not code-OBSERVED.** No live OAuth dance or API call was executed. A ~50-line spike (full loopback+PKCE against one real Google + one real M365 app registration, pure or library-based) would convert the load-bearing feasibility claims from CORROBORATED to OBSERVED — recommended before committing Phase A. The riskiest single claim to spike: **"Production-but-unverified keeps a durable refresh token for the sensitive calendar scope"** — verify with a real >7-day token-survival test.
- **Provider-doc-centric:** if Google/Microsoft recently tightened native-app/loopback or sensitive-scope policy and a fetched doc page lags reality, the doc and the blogs echoing it would be wrong in the same direction. The vendor-neutral RFC 8252 + a hostile refuter partially de-correlate this.
- **`iCalUId` per-recurring-instance semantics** on Microsoft Graph are version-inconsistent across MS's own docs — verify empirically before relying on it to dedupe individual instances; prefer `seriesMasterId` for instance identity.
- **MSA vs work/school** Microsoft account type was not observed for John — it materially changes refresh-token reliability; confirm which he'll connect.

---

## 7. Recommended next step
Take this to **Crucible** to freeze a `planning/calendar-v1/` design + implementation plan scoped to **Phase A (pull+display) + Phase B (one-way push to an Anchor-owned calendar)**, with Decision A ratified as the `[calendar]` extra and Phase C explicitly deferred — then **Foreman**-build it wave-by-wave (stubbed healthcheck + UI sign-off per wave). Precede the build with the 50-line auth spike to harden the feasibility claims.
