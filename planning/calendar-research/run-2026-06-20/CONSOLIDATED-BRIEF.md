# Anchor Calendar — Consolidated, Vetted, Crucible-Ready Brief

**Date:** 2026-06-20 · **Skill:** researchPrime · **Mode:** ENGINE (node, import-spike `go:true`, 28 trio symbols)
**Purpose:** Merge the two prior research runs (2026-06-15 + 2026-06-17) into ONE current-state source of truth, re-vet the load-bearing claims, and hand a clean package to Crucible. This brief **supersedes** the scattered prior docs for planning purposes; the originals are retained for provenance.
**Evidence ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED.
**Vet for this merge:** two context-isolated adversarial refuters (web-enabled, tasked to BREAK the picks) → context-free Judge synthesis. `cross_model: false`. See §7.

---

## 0. What this is, in one paragraph

Build a Google + Outlook/M365 calendar into Anchor that **shows all your calendars and pushes your Anchor-owned events back out** — local-private, no cloud, no public surface. The architecture is **forced and clean** (poll, don't webhook; two native REST clients; OAuth2-PKCE desktop flow; DPAPI token storage), the scope is **safe by construction** (Anchor only ever writes to one calendar it owns), and the build reduces to **two one-way pipes**, not a dangerous symmetric merge. Every load-bearing infra claim is **OBSERVED** (a live spike ran on this machine). The work is **build-ready**; the next step is Crucible, not more research.

---

## 1. Provenance — the two runs being merged

| Run | Scope it validated | Status |
|---|---|---|
| **2026-06-15** (`run-2026-06-15/`) | The **backend**: poll-not-webhook · two REST clients · OAuth2-PKCE/DPAPI · sync mechanics · failure modes. Locked Decisions A + B. Ran a live **infra spike** (`spike/`). | Backend validated; infra spike OBSERVED |
| **2026-06-17** (`run-2026-06-17/`) | The **four thin surfaces**: UI widget · event store + recurrence · sync prior-art (reuse vs build) · buy-vs-build. Produced the **scope-reduction** finding. | Component picks vetted; scope reduction **ratified by John 2026-06-17** |

The two runs are consistent except on one axis — scope — where the later run **narrowed** the earlier one and John ratified the narrowing. This merge encodes the ratified end-state (§3, Decision B).

---

## 2. LOCKED architecture (do not re-litigate in Crucible)

1. **Poll, don't webhook.** A localhost-only service cannot receive Google/Microsoft push (both require a public, CA-certified HTTPS endpoint). Periodic polling on a `threading.Thread(daemon=True)` (mirror `anchor_gui._trigger_session_summary`) is the supported path and *preserves* Anchor's private posture. Render reads cached `.anchor/calendar/state.json` ONLY — never a sync network call on render. Cadence: 5–15 min foreground / hourly background (Google quota 600 req/user/min = vast headroom). **[CORROBORATED ×4 lanes incl. hostile refuter]**
2. **Two native REST clients:** Google Calendar API v3 + Microsoft Graph. CalDAV is out (Microsoft has none). **[CORROBORATED]**
3. **Auth:** OAuth 2.0 Auth-Code **+ PKCE**, **installed/desktop client type** (NOT "Web" — its `client_secret` can't be safely embedded and would trip `distro.py`'s no-secrets scan). Loopback redirect `http://127.0.0.1:<ephemeral>/callback` (use `127.0.0.1`, never `localhost`; must NOT collide with 8777's `SO_EXCLUSIVEADDRUSE` bind). `webbrowser.open()` pops the one-time consent. **[OBSERVED — spike]**
4. **Change detection:** Google initial `events.list` → persist `nextSyncToken` (returned only on the FINAL page — page to completion); later calls pass `syncToken`; **`410 GONE` → wipe mirror + full resync (a NORMAL path)**. Microsoft **`GET /me/calendarView/delta`** (GA v1.0 — **not** the beta `/events/delta`) → follow `@odata.nextLink` → persist `@odata.deltaLink`; token loss → full resync; guard the known `calendarView/delta` infinite-`skipToken` loop. Pull recurring series **un-expanded** (`singleEvents=false`) — sync the RRULE + overrides, never expanded instances. **[CORROBORATED; delta-endpoint correction OBSERVED 2026-06-17]**
5. **Token at rest:** DPAPI via `ctypes` `CryptProtectData`, **user scope** — the `anchor` service runs as **`.\john`** (`sc qc anchor`, re-verified), so user-scope DPAPI is correct and browser consent works in John's interactive session. Document the user+machine-bound footgun (profile-SID/machine change → tokens undecryptable → silent re-auth). DPAPI blobs are strictly *better* than the surrounding plaintext `claude`/`gemini` creds. **[OBSERVED — spike]**

---

## 3. The decisions (both ratified — carried into Crucible as locked)

### Decision A — OAuth implementation: **`[calendar]` optional pip-extra** (ratified)
Use the vendors' own first-party libraries — **`msal`** (Microsoft) + **`google-auth`** (Google) — for the OAuth token lifecycle, declared as a **lazy, optional pip extra** exactly like `[terminal]=pywinpty`. Declared in `pyproject.toml` as `calendar=[...]` AND added to `distro.py`'s scoped import-allowlist (calendar module only). Degrades gracefully ("calendar unavailable") when absent. **Still DPAPI-wrap the token cache at rest.** Rationale: security-critical OAuth lifecycle (refresh rotation, `invalid_grant` recovery, clock-skew, expiry interplay) is the silent-failure class; the `[terminal]` exception is the exact precedent — stdlib-only is Anchor's *distribution* rule, with a built-in scoped escape hatch. **[Judge HIGH]**

### Decision B — Scope: **two one-way pipes, NOT a symmetric three-way merge** (ratified 2026-06-17)
The locked safety rail — *Anchor reads all calendars but only ever WRITES to one dedicated "Anchor"-owned calendar per provider* — gives **every event exactly one authoritative writer**. That collapses the hard symmetric merge into two pipes:
- **PUSH pipe:** Anchor-owned events → the dedicated Anchor calendar in each provider. Upsert by `iCalUID`; echo-suppress via self-marker + recorded ETag; idempotent create on Graph via `transactionId`.
- **PULL pipe:** ALL other calendars → Anchor, **read-only display**. ETag/sync-token change-detection only.

**No stored content baseline, no symmetric conflict resolution, no three-way merge engine in scope.** The richer `.anchor/calendar/` event store is still built (it holds recurrence faithfully + feeds display & the push pipe) but it is **no longer gating a dangerous merge**.

**TRIPWIRE — the symmetric merge returns ONLY when** a user is allowed to natively edit/delete, *inside Anchor*, an event that an external provider also mutates (two concurrent writers). Until that feature is explicitly chosen, two one-way pipes are correct and sufficient. The iCalUID-baseline three-way-merge engine (specced in `run-2026-06-15/03-agent-impl.md`) is **DEFERRED behind this tripwire.**

**SAFETY RAIL (non-negotiable):** Anchor never holds a delete/update handle on a human-created event. This structurally eliminates the two worst failure modes (recurring-event corruption + deleted-event resurrection) for real events.

---

## 4. Component picks (vetted; from the 2026-06-17 run)

| Surface | Pick | License | Goes in | Load-bearing caveat |
|---|---|---|---|---|
| **Calendar UI widget** | **EventCalendar (vkurko/calendar)** — vendored static; FullCalendar v6 = named fallback | MIT | `vendor/event-calendar/` (static, no build) | Renders **pre-expanded** occurrences only → backend owns 100% of recurrence correctness |
| **Event store** | **RFC-5545 `.ics`-per-series + `meta.json` sidecar** | n/a | `.anchor/calendar/<account>/events/<icalUID>.ics` + sidecar | Sidecar **MUST retain raw Graph JSON** (lossless source for Graph-only recurrence) |
| **Recurrence expander** | **`allenporter/ical` (Timeline API)** — NOT the LGPL `recurring-ical-events` ⚠️ **see §7b Correction 1** | Apache-2.0 (but native-wheel dep tree) | `[calendar]` extra | **VET FINDING:** `ical` drags in `pydantic` (compiled Rust `pydantic-core`) → would **fail the distro stdlib import scan**. Crucible must pick: accept inside the `[calendar]` extra+allowlist, OR switch to `icalendar`+`dateutil`+hand-rolled overrides |
| **Sync engine** | **Hand-roll TWO one-way pipes**; reference vdirsyncer `sync.py` (copy its empty-replica abort guard) | (own) | `calendar_sync.py` | Per Decision B |
| **Architecture** | **Direct REST** (no SaaS, no unified lib — none fits local-private) | — | — | Hosted aggregators all hold the token + need a public webhook = fatal |

**The single most dangerous residual risk:** the hand-rolled **Microsoft Graph `recurrencePattern` ↔ RRULE translator** — no official converter, and provably **lossy** (`relativeMonthly`/`relativeYearly` with multiple `daysOfWeek` = "first day that satisfies", which has no clean RRULE form → only the retained raw JSON is lossless). **Correctness landmine:** RECURRENCE-ID override identity — key the series by `iCalUID`, each instance by `(iCalUID, original-start)`, or you render ghost/duplicate occurrences.

---

## 5. Where it plugs into Anchor

- **New modules (repo root, first-party, pass the import scan):** `calendar_auth.py` (PKCE, loopback callback, DPAPI wrap/unwrap, refresh — thin wrappers over `msal`/`google-auth`) + `calendar_sync.py` (REST clients + the two pipes). `paths.calendar_dir()` → `data_dir()/.anchor/calendar/`.
- **HTTP routes:** `do_GET` += `/api/calendar/connect` (mint verifier, open consent) + `/api/calendar/callback` (capture `?code=&state=`, finish PKCE); `do_POST` += token-authed `/api/calendar/refresh` / `/api/calendar/disconnect`.
- **Display:** the dashboard already renders a hand-typed `## Today's Calendar` block in DASHBOARD.md — the natural pull-display target (replace hand-typed with a live, `WRITE_LOCK`-guarded, poll-generated block) + the vendored EventCalendar widget for month/week/day.
- **CLI mirror (read-only):** `anchor.py` += `cal status` / `cal pull`.
- **Testing (non-negotiable):** a **fully-stubbed `check_calendar_surface`** healthcheck (fake HTTP responder seam; walk PKCE → DPAPI round-trip → PULL → push → restore env/teardown) — **NEVER live Google/MS**, mirroring the v2–v11 standard. Every UI wave: DOM assertions + Playwright + screenshot + John's sign-off.

---

## 6. Suggested wave skeleton (Crucible refines in Stage 1)

1. **ICS+sidecar event store** + markdown-deadline → store mapping (+ `[calendar]` extra w/ `icalendar` + `allenporter/ical`; lazy/degrade like `pywinpty`; `distro.py` allowlist).
2. **Auth** (`[calendar]` + msal/google-auth, PKCE, DPAPI) — reuse the OBSERVED 2026-06-15 spike harness.
3. **PULL pipe + EventCalendar display** (vendor the widget; render month/week/day from expanded occurrences; render reads `state.json` cache only).
4. **PUSH pipe** to the Anchor-owned dedicated calendar (gated on the 8-day durable-refresh spike result).
5. **Recurrence hardening** (the Graph fixture table; override identity `(iCalUID, original-start)`).
6. **CLI mirror + fully-stubbed `check_calendar_surface` + distro scan + CLAUDE.md** (PROJECT DONE).

---

## 7. The VET — adversarial re-verification for this merge (2026-06-20)

Two context-isolated, web-enabled refuters were tasked to **break** the load-bearing claims against primary sources (vendor docs / RFCs / GitHub LICENSE files, fetched 2026-06-20), then synthesized by a context-free Judge. **ISOLATION: real** (separate sub-agent contexts). **`cross_model: false`.**

### 7a. CONFIRMED at primary sources (load-bearing claims that held)

| Claim | Verdict | Ladder | Primary source |
|---|---|---|---|
| Graph `/me/calendarView/delta` is GA v1.0; `/events/delta` is **beta-only** | **CONFIRMED** | OBSERVED | Graph v1.0 ref + beta comparison table |
| Google `events.list` + `syncToken` incremental sync is current (only legacy `updatedMin` is deprecated) | **CONFIRMED** | OBSERVED | Google sync guide |
| Desktop loopback (`127.0.0.1:<ephemeral>`) + PKCE still supported/recommended by both vendors (deprecation hit only mobile/Chrome/OOB) | **CONFIRMED** | OBSERVED | Google native-app doc + RFC 8252 §7.3/§8.1 + MS auth-code doc |
| Graph supports **PKCE S256** despite the `/common/v2.0` discovery doc omitting `code_challenge_methods_supported` | **CONFIRMED** | OBSERVED | MS auth-code-flow ref ("supports both `plain` and `S256`") |
| Google "Testing" mode revokes sensitive-scope refresh tokens at 7 days | **CONFIRMED** | OBSERVED | Google OAuth2 doc (verbatim) |
| Calendar is a **sensitive** (not restricted) scope → no mandatory CASA annual third-party assessment | **CONFIRMED** | CORROBORATED | Google OAuth scopes page (restricted = Gmail/Drive-class; Calendar not in it) |
| EventCalendar (vkurko): **MIT**, zero runtime deps, standalone build, M/W/D/list + free drag, **v5.7.1 released May 2026** (active) | **CONFIRMED** | OBSERVED | repo LICENSE + package.json (`dependencies: none`) |
| FullCalendar **v6** MIT fallback: free interaction, self-injecting CSS, full RRULE via `@fullcalendar/rrule` (MIT) + `rrule.js` (**BSD-3**) | **CONFIRMED** | OBSERVED | v6 rrule package.json |
| `allenporter/ical` is **Apache-2.0** (NOT LGPL); `recurring-ical-events` IS **LGPL-3.0-or-later** → the avoidance is justified | **CONFIRMED** | OBSERVED | both LICENSE files / PyPI metadata |
| vdirsyncer is **BSD-3**, reference-only — it has a CalDAV-based `google_calendar` storage and **NO Microsoft/Graph storage at all** (Graph-blind as a library) | **CONFIRMED (stronger than stated)** | OBSERVED | vdirsyncer config docs + LICENSE |
| Hosted aggregators (Nylas, Cronofy) hold the token, cache in their cloud, **require a public webhook** → fatal to local-private poll-only | **CONFIRMED** | OBSERVED | Nylas calendar-API page + Cronofy push-channel docs (`callback_url` must be "publicly reachable") |

### 7b. ⚠️ TWO MATERIAL CORRECTIONS (the vet's real yield — Crucible must resolve)

**CORRECTION 1 — the recurrence expander pick BREAKS a hard project invariant.** `allenporter/ical` is correctly Apache-2.0 (LGPL avoided) and pure-Python *in its own code* — **BUT its install pulls `pydantic>=2.10.4`, whose `pydantic-core` is a compiled Rust native wheel**, plus `python-dateutil` + `tzdata`. That is **not** stdlib-pure, and per Anchor's own `distro.py` import-scan rule (stdlib-only except the single declared `pywinpty` exception) **`ical` would fail the distro import scan.** The license analysis was right; the "fits a stdlib-purist app" conclusion was wrong. → **Crucible decision required.** Options:
  - **(a) Accept it inside the `[calendar]` optional extra + distro allowlist.** The extra is already the declared escape hatch and already adds non-stdlib `msal`/`google-auth`; pydantic/dateutil ride the same lazy-import seam and degrade to "calendar unavailable" when absent. The new thing is a *compiled native wheel* (stronger than pure-Python deps) — a judgment call, but consistent with the precedent.
  - **(b) Switch to a lighter expander:** `icalendar` (BSD, parse) + `dateutil.rrule` (pure-Python) + a hand-rolled EXDATE/RECURRENCE-ID override applier. Lighter footprint; costs ~the override logic `ical` would have given for free (the prior report flagged dateutil-alone as insufficient *without* that extra glue). Keeps the dep tree pure-Python.
  - The recommendation (mine): lean **(a)** — the `[calendar]` extra exists precisely to localize this, and re-implementing a correct RRULE+EXDATE+override expander by hand is exactly the silent-failure surface Decision A chose to avoid — but **this is John's/Crucible's call**, and the §8.1 recurrence spike should be run under whichever expander is chosen.

**CORRECTION 2 — the "Production-but-unverified keeps a durable refresh token" claim is UNVERIFIED, not CORROBORATED.** Google's primary OAuth doc states the 7-day revocation **only** for the *Testing* case; it does **not** affirmatively say an *unverified Production* app keeps long-lived refresh tokens. There is also a real **Testing-vs-Production tension**: staying in Testing dodges app verification but kills the token every 7 days (fatal to unattended background sync — the whole point of `syncToken`/`delta`); moving to Production removes the 7-day death but generally needs Google **app verification** for the sensitive scope (verification ≠ the CASA assessment you avoid by being non-restricted). → **The Testing-vs-Production posture must be decided BEFORE architecting the background sync**, and the §8.3 8-day durable-refresh spike is load-bearing — build the token store assuming you may have to handle 7-day expiry.

### 7c. Minor hardening (fold into Stage 1, no decision needed)
- **Pin FullCalendar to v6, not v7** — v7 adds a `temporal-polyfill` peer dep, breaking the "RRULE in 2 extra files" property. (Moot if EventCalendar is used, which is the pick.)
- **The vendored EventCalendar copy MUST ship its `LICENSE` file** — `package.json` carries no `license` field; the MIT grant lives only in the file.
- **"~35 KB" is the brotli-compressed figure** — the raw on-disk vendored `.js` is materially larger. Don't quote 35 KB as the shipped size.
- **`recurring-ical-events` LGPL-3.0 confirmed** — avoidance justified regardless of which expander wins Correction 1.

### 7d. Honest verification gap (do not over-claim)
- **"No maintained turnkey Python library two-way-syncs Google ↔ Graph" is UNVERIFIED this session** (one refuter's web search was unavailable; the other's earlier runs CORROBORATED it). State it as **"none found, search incomplete,"** not as observed fact. It does not change the BUILD verdict (no *local-private* turnkey could exist given the cloud/webhook finding in 7a), but the absence itself is not freshly confirmed today.

### 7e. Judge synthesis
The **architecture and the two ratified decisions stand** — every infra/transport/auth/scope/buy-vs-build claim survived primary-source attack. The vet's value is two corrections that land *inside* the component layer, both **flagged for Crucible, neither fatal:** the recurrence-expander dependency conflict (Correction 1, a real invariant break needing a pick) and the durable-refresh downgrade to UNVERIFIED (Correction 2, sharpening an already-known spike gate). The brief is **Crucible-ready** with these two items carried as explicit Stage-0/Stage-1 inputs.

---

## 8. What is still genuinely OPEN (the only real gaps)

These are **spike/account gates, not research gaps.** None blocks Crucible planning; the durable-refresh one gates the *write-back wave only*.

1. **Graph-recurrence enumeration spike (1 day, doable now without accounts).** Enumerate every Graph `recurrencePattern` variant (daily/weekly/absoluteMonthly/relativeMonthly/absoluteYearly/relativeYearly × single & multiple `daysOfWeek` × `index`) into a fixture table asserting clean-RRULE-round-trip OR explicit sidecar-only. The lossy-cell count gates the recurrence estimate and proves the sidecar is load-bearing.
2. **Real consent + events-list** against John's actual Google + M365 accounts (`spike/RUNBOOK.md`; needs John's app registrations + interactive browser consent).
3. **8-day durable-refresh proof** — the riskiest unspiked claim, now **UNVERIFIED** (§7b Correction 2): Google's primary doc states the 7-day revocation only for *Testing*, and does NOT affirm that *Production-unverified* keeps a durable refresh token. **Decide the Testing-vs-Production posture BEFORE architecting background sync** (Testing dodges verification but kills the token at 7 days; Production needs sensitive-scope app *verification*). Run `--refresh-check` >7 days after consent; build the token store to tolerate 7-day expiry. **Gates the write-back wave, NOT planning.**
4. **MSA vs work/school** — which Microsoft account type John connects (changes refresh-token reliability + `/common` vs `/consumers` authority).

---

## 9. Honest limits (correlated blind spots)

- **Infra is OBSERVED; everything above the infra is doc/repo-corroborated, not code-executed.** The bundle sizes (EventCalendar ~35 KB) and `allenporter/ical` RRULE-surface parity are the least-verified load-bearing items — closed by the §8.1 spike.
- **Vendor-doc-centric freshness:** the OAuth/API policy facts rest on Google/Microsoft docs; a just-shipped policy change lagging its doc page would mislead doc + echoing blogs in the same direction (partially de-correlated by RFC 8252 + the §7 refuters).
- **The Graph `recurrencePattern` enumeration is reasoned, not exhaustively tested** — exactly why §8.1 is the gating spike.

---

## 10. Recommended next step

**Advance to Crucible.** Freeze `planning/calendar-v1/` (MASTER-PLAN + IMPLEMENTATION-PLAN) from this brief + `run-2026-06-15/CRUCIBLE-PROMPT.md` + `run-2026-06-17/04-crucible-decision-addendum.md`. Both decisions are ratified and locked; the wave skeleton (§6) is the starting point. Optionally run the §8.1 Graph-recurrence spike first to harden the recurrence-wave estimate. The 8-day durable-refresh check (§8.3) runs in parallel with planning and only gates the write-back wave.
