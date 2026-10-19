# Lane 4 — SaaS / Unified-API Buy-vs-Build Survey + 2026 Freshness Check

**Scope:** Anchor is a single-user, LOCAL/PRIVATE Python productivity app — runs as a localhost-only service on the user's own machine. Hard North-Star: **NO public inbound endpoint; data stays local/private.** The direct-REST architecture (Google Calendar API v3 + Microsoft Graph, called directly from the local box) is already chosen. This lane is the honest buy-vs-build alternative survey plus a freshness re-check of the locked direct-REST facts.

**Fetch date:** 2026-06-17. Primary sources (Google Identity/Workspace docs, Microsoft Learn) fetched and quoted below with their on-page last-updated dates.

---

## Part 1 — Unified-Calendar SaaS / Aggregation APIs as an Architecture Alternative

### The killer test for every option

For a local-private single-user app there are **two disqualifiers**, and most hosted services fail both:

1. **Does the user's calendar data transit / get cached in a THIRD-PARTY cloud?** A managed sync provider, by design, holds an OAuth refresh token and maintains a server-side cache/mirror of your calendar to power its delta feed and webhooks. That is the opposite of "data stays local."
2. **Does it need a PUBLIC inbound endpoint?** Most providers push changes to you via a **webhook callback** that they must be able to reach over the internet, and their OAuth setup expects a public HTTPS redirect URI. Anchor explicitly forbids a public inbound endpoint.

A purely **direct-REST** design fails neither: tokens live on the local box, the only network traffic is *outbound* HTTPS from Anchor to Google/Microsoft, and incremental sync is **poll-based** (`syncToken` / `deltaLink`) so **no inbound webhook is required**.

### Comparison table

| Provider | What it does | Pricing model | Routes data through 3rd-party CLOUD? | Self-hostable? | Public callback / inbound needed? | Verdict for local-private |
|---|---|---|---|---|---|---|
| **Direct REST (chosen)** | Anchor calls Google Calendar v3 + MS Graph itself | Free (just the APIs) | **No** — tokens + cache local | N/A (it IS local) | **No** — poll with syncToken/delta | ✅ The only option that meets the North-Star |
| **Nylas** | Unified email/calendar/contacts API; v3 | $10/mo Calendar-only incl. 5 connected accounts, then $1/acct/mo; Full Platform $15/mo + $2/acct ([pricing](https://www.nylas.com/pricing/)) | **Yes** — Nylas servers proxy + cache calendar data; hosts Virtual Calendars | No (SaaS) | Yes — webhooks + hosted OAuth | ❌ Violates local/private |
| **Cronofy** | Unified calendar sync/scheduling API; region-pinned data | Enterprise-grade; ~$819/mo "Emerging", ~$2,399/mo "Growth" ([plans](https://docs.cronofy.com/developers/plans-pricing/)) | **Yes** — "maintains a cache of the data"; region-selectable but still Cronofy's cloud | **No** — "not built for self-hosted" | Yes — push/webhooks | ❌ Violates local/private (and absurdly priced for 1 user) |
| **Google's own** (Calendar API v3) | Google's first-party REST API | Free | This IS Google — no extra 3rd party | N/A | No (poll) / optional push | ✅ = the direct-REST path itself (not a 3rd party) |
| **Microsoft Graph** | MS first-party REST API | Free | This IS Microsoft | N/A | No (poll) / optional push | ✅ = the direct-REST path itself |
| **CalendarBridge** | Consumer calendar sync + unified view product (B2C app, also has API) | Per-user subscription | **Yes** — its servers perform the sync | No | Yes | ❌ Consumer SaaS, not a local lib |
| **Recall.ai** | **Meeting-bot / recording** API (bots join Zoom/Meet/Teams; transcripts). Has a *calendar* add-on only to auto-schedule those bots | Usage-based (per bot-hour) | **Yes** | No | Yes | ❌ Wrong product category entirely — not a calendar-sync layer |
| **Schedule-X** | Open-source JS calendar **UI component** library; a separate hosted sync service exists | Component free (MIT); hosted sync is a paid SaaS | Hosted variant: **Yes** | UI: yes (it's a frontend lib, not a sync backend) | Hosted: yes | ❌ It's a calendar *widget*, not a Python sync backend. Irrelevant to a Python server. |
| **Composio** | Agent-tool/unified-integration platform; "Google Calendar toolkit" w/ managed OAuth + token refresh for AI agents | Per-action / tier pricing | **Yes** — managed auth + actions routed via Composio | No (SaaS) | Yes — hosted OAuth | ❌ Built for cloud AI agents; routes auth/data through Composio |
| **Merge.dev** | Unified API across HRIS/CRM/**Calendar**/etc. for B2B SaaS | B2B per-linked-account, sales-led | **Yes** — Merge proxies + normalizes via its cloud | No (SaaS) | Yes — webhooks + hosted Magic Link OAuth | ❌ Aimed at multi-tenant B2B SaaS; data through Merge |
| **Cal.com** | Open-source (AGPLv3) Calendly alternative; syncs Google/Outlook/CalDAV to prevent double-booking | Community self-host **free**; cloud tiers paid | **Self-host = No** (data on your infra); Cloud = Yes | **YES** — full self-host (Next.js + Postgres) | Self-host: OAuth callback is *your* server (could be localhost), but Google/MS still need a reachable redirect for verified prod | ⚠️ The ONLY self-hostable one — but heavyweight (Node/Next.js/Postgres) and is a *scheduling/booking* product, not a sync library. See note below. |

### The one self-hostable contender — Cal.com — judged honestly

Cal.com (AGPLv3, ~32K stars, TypeScript/Next.js + Postgres) is genuinely self-hostable, and self-hosting keeps booking data + calendar credentials on your own infrastructure. So it does NOT structurally violate the "data local" rule the way Nylas/Cronofy/Merge/Composio do.

**But it still loses for Anchor:**
- **Wrong shape.** Cal.com is a *booking/scheduling* platform (public booking pages, round-robin, routing forms), not a two-way personal-calendar **sync library** you embed in a Python server. Anchor wants to read/write the user's own events, not run a Calendly.
- **Massive dependency footprint.** It pulls in Node, Next.js, and Postgres — a flat violation of Anchor's stdlib-only / no-external-deps North-Star (the project guards this so hard it treats even `pywinpty` as a single declared exception). Standing up a Next.js+Postgres service next to a localhost Python app to avoid writing ~2 REST clients is a net complexity *increase*.
- **OAuth burden is the same.** You still register your own Google/MS OAuth client and still own the calendar scopes — Cal.com doesn't make the consent/verification problem go away; it just wraps it in a much bigger app.

### Blunt summary of who violates the posture

- **Route data through their cloud AND need a public callback (full disqualification):** Nylas, Cronofy, CalendarBridge, Composio, Merge.dev, Recall.ai, Schedule-X (hosted).
- **Could theoretically run local:** only **Cal.com (self-hosted)** — but it's a scheduling product with a heavy Node/Postgres stack, not a sync lib, so it's the wrong tool and a deps violation.
- **Not a 3rd party at all:** Google Calendar v3 and Microsoft Graph — these *are* the direct-REST endpoints Anchor already chose.

---

## Part 2 — 2026 Freshness Check on the Locked Direct-REST Facts

Prior research dated 2026-06-15. Re-verified against PRIMARY docs on 2026-06-17. Each fact below states the source, its on-page last-updated date, and evidence quality.

### (a) Google Calendar v3 `events.list` + `syncToken` incremental sync — STILL CURRENT ✅
- **Confirmed.** The official "Synchronize resources efficiently" guide presents `events.list` → `nextSyncToken` → incremental sync as the **current recommended** method. The *only* thing flagged "no longer recommended" is the legacy `modifiedSince`/`updatedMin` full-query approach — **not** sync tokens. On `410 GONE` you clear state and do a full resync.
- **Source:** https://developers.google.com/workspace/calendar/api/guides/sync — **page last updated 2026-04-23 UTC** (fetched 2026-06-17).
- **No deprecation or sunset date for sync tokens anywhere on the page.**
- **Evidence quality: OBSERVED (primary, current-dated).**

### (b) Microsoft Graph `/me/calendarView/delta` + `/events/delta` — CURRENT, with one nuance ✅⚠️
- **Confirmed with an important distinction:**
  - `/me/calendarView/delta` (bounded by startDateTime/endDateTime) is **GA in v1.0** — the doc's own examples use `https://graph.microsoft.com/v1.0/me/calendarView/delta`, with `@odata.nextLink`(`$skiptoken`) paging and a final `@odata.deltaLink`(`$deltatoken`) for the next round. This is the production path.
  - `/events/delta` (un-bounded, i.e. delta over a *calendar's events* without a fixed date window) is **beta-only**: the doc explicitly notes "getting incremental changes to events in a calendar not bound to a fixed start and end date range — is currently available only in the beta version."
  - **Implication for Anchor:** sync should use **`calendarView/delta` (v1.0, GA)** with a rolling date window, NOT `events/delta` (which is still beta). If the locked facts assumed v1.0 `events/delta`, that needs correcting — only `calendarView/delta` is GA.
- **Source:** https://learn.microsoft.com/en-us/graph/delta-query-events — **article ms.date 2024-11-07, updated_at 2025-08-06** (fetched 2026-06-17).
- **Known operational caveat (secondary, Microsoft Q&A):** intermittent reports of `calendarView/delta` looping (rotating `$skiptoken`, `@odata.deltaLink` never emitted). Not a deprecation; an implementation gotcha — sync code should cap pages / detect repeated payloads. *Evidence quality: CLAIMED (community Q&A, not a changelog).* 
- **Evidence quality for the GA/beta fact: OBSERVED (primary Microsoft Learn).**

### (c) Google OAuth "Testing" mode 7-day refresh-token revocation vs "Production" — STILL CURRENT ✅
- **Confirmed.** A project with the OAuth consent screen in **Testing** + External user type issues refresh tokens that **expire 7 days from consent** — *unless* the only scopes are a subset of `openid`/`email`/`profile`. Calendar scopes are NOT in that exempt subset, so a Testing-mode calendar integration loses its token weekly. Moving to **Production** (publishing status) removes the 7-day expiry — and you can publish to Production **even while unverified** (you just get the unverified-app warning screen and a 100-user cap for sensitive scopes; the token no longer auto-revokes at 7 days).
- **Source (primary):** https://developers.google.com/identity/protocols/oauth2 ("Using OAuth 2.0 to Access Google APIs") states the Testing-mode 7-day refresh-token expiry and the basic-scope exemption. Corroborated by https://support.google.com/cloud/answer/15549945 (Manage App Audience).
- **Evidence quality: OBSERVED/CORROBORATED (primary Google doc + primary support article).**
- **Action implication unchanged:** Anchor MUST publish its OAuth app to **Production** (verification not required for a single self-user, but Production status IS) or refresh tokens die every 7 days.

### (d) Calendar is a "sensitive" (NOT "restricted") Google scope — STILL CURRENT ✅
- **Confirmed.** Google's verification docs explicitly use **reading Google Calendar events as the canonical example of a *sensitive* scope.** `https://www.googleapis.com/auth/calendar` is **sensitive**, not restricted. This matters: **restricted** scopes (Gmail/Drive content) require an **annual third-party security assessment** when data flows through a server; **sensitive** scopes do not — they need only Google's OAuth verification (and that's only required to exceed the 100-user unverified cap, which a single-user app never hits).
- **Source:** https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification (sensitive) + https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification (restricted, with the annual-security-assessment requirement). Fetched 2026-06-17.
- **Evidence quality: OBSERVED (primary).**

### (e) 2025–2026 OAuth changes for installed/desktop apps, loopback redirects, PKCE — NO BREAKING CHANGE; loopback for desktop STILL SUPPORTED ✅
- **Confirmed — and this is the load-bearing fact for Anchor's no-public-endpoint posture:** the **loopback IP / localhost redirect flow is explicitly DEPRECATED for Android, Chrome-app, and iOS clients, but REMAINS supported and *recommended* for desktop apps** (macOS, Linux, Windows — not UWP). Anchor is a Windows desktop/localhost app, so it uses exactly the still-supported flow: register a **Desktop** OAuth client, redirect to `http://127.0.0.1:<port>`, capture the code on a transient local listener. **No public inbound endpoint is required for OAuth.**
- **PKCE:** "Recommended," not strictly required, for Google installed apps. Microsoft Entra supports/can-require PKCE for public-client (native/desktop) auth-code flow. Anchor should implement PKCE (it's free hardening and future-proof), but neither provider mandates it for a desktop client as of now.
- **OOB (`urn:ietf:wg:oauth:2.0:oob`) copy-paste flow** was deprecated/blocked back in 2022–2023 — Anchor must NOT use OOB; it uses **loopback** instead. This is an old change, not a 2025–2026 one, and it does not affect the loopback path.
- **No 2024–2026 change targeting desktop apps** appears on either provider's page.
- **Sources (primary):**
  - https://developers.google.com/identity/protocols/oauth2/native-app — **last updated 2026-05-26 UTC**: "Loopback IP address … Recommended usage: macOS, Linux, and Windows desktop … apps."
  - https://developers.google.com/identity/protocols/oauth2/resources/oob-migration (OOB deprecation, 2022–2023 dates).
  - https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow + https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows (auth-code+PKCE for public/native clients).
- **Evidence quality: OBSERVED (primary, current-dated 2026-05-26).**

---

## Part 3 — Verdict

### Does any SaaS / unified option beat direct-REST for THIS constraint set?

**No.** For a single-user, local-private app with a hard no-public-inbound-endpoint rule, every hosted/unified provider (Nylas, Cronofy, CalendarBridge, Composio, Merge.dev, Recall.ai, Schedule-X hosted) **structurally violates the North-Star**: each holds the OAuth token, mirrors/caches the user's calendar in *its* cloud, and expects a public webhook callback. They are built to solve a *multi-tenant B2B SaaS* problem (normalize N customers' calendars behind one API) — Anchor has exactly **one** account per provider and forbids the cloud hop. Their pricing also makes no sense for one user (Cronofy starts ~$819/mo; Nylas adds a monthly fee for what is otherwise free first-party API access).

The only non-cloud option, **self-hosted Cal.com**, keeps data local but is the **wrong product** (a booking platform, not a personal-calendar sync library) and drags in **Node + Next.js + Postgres**, violating Anchor's stdlib-only deps rule. Standing it up to avoid writing two thin REST clients is a complexity loss, not a win.

Direct-REST is *more* private, *cheaper* (free), and *simpler* in dependency terms (two stdlib HTTP clients), and the poll-based `syncToken`/`calendarView delta` model means **no inbound endpoint is ever needed** — the precise property the SaaS layer cannot provide.

### The one scenario where BUY would win

If Anchor ever pivoted from **single-user local** to a **hosted multi-tenant** product — many users' calendars, served from a cloud backend, needing normalized cross-provider data, push notifications, and offloaded OAuth/verification/compliance (SOC2/HIPAA/BAA) — then a unified provider (Nylas or Cronofy) **would** win: it amortizes per-provider OAuth quirks, delta-loop bugs, token-refresh, and compliance across all tenants, which is real recurring engineering you'd otherwise own. That scenario is the *negation* of Anchor's North-Star, so it does not apply today. (A weaker mid-case: if Anchor needed **meeting-bot recording**, Recall.ai is the right buy — but that's a different feature, not calendar sync.)

### Are the locked direct-REST facts still valid as of 2026?

**Yes — all five hold, with one clarification on the Microsoft delta endpoint.** See Part 2. The single correction worth flagging: use **`/me/calendarView/delta` (GA in v1.0)**, NOT `/events/delta` (still beta-only). Everything else (Google syncToken current; Testing-mode 7-day token revocation; calendar = sensitive not restricted; desktop loopback still supported, PKCE recommended) is confirmed against primary docs last updated April–May 2026.

---

## Sources (with URLs and evidence quality)

**Primary — Google (OBSERVED):**
- Synchronize resources efficiently (syncToken) — https://developers.google.com/workspace/calendar/api/guides/sync — *updated 2026-04-23*
- Using OAuth 2.0 to Access Google APIs (Testing 7-day token) — https://developers.google.com/identity/protocols/oauth2
- Manage App Audience (Testing vs Production) — https://support.google.com/cloud/answer/15549945
- Sensitive scope verification (calendar = sensitive) — https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- Restricted scope verification (contrast: annual security assessment) — https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- OAuth 2.0 for iOS & Desktop Apps (loopback recommended for desktop, PKCE recommended) — https://developers.google.com/identity/protocols/oauth2/native-app — *updated 2026-05-26*
- OOB flow migration (2022–2023 deprecation) — https://developers.google.com/identity/protocols/oauth2/resources/oob-migration
- Loopback migration (deprecated for mobile/Chrome, kept for desktop) — https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration

**Primary — Microsoft (OBSERVED):**
- Get incremental changes to events in a calendar view (calendarView/delta GA v1.0; events/delta beta-only) — https://learn.microsoft.com/en-us/graph/delta-query-events — *updated 2025-08-06*
- event: delta (v1.0 reference) — https://learn.microsoft.com/en-us/graph/api/event-delta?view=graph-rest-1.0
- Microsoft identity platform OAuth 2.0 auth-code flow (PKCE/public client) — https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
- MSAL authentication flows — https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows

**Secondary — SaaS vendor/pricing pages (CLAIMED — vendor self-reported):**
- Nylas pricing — https://www.nylas.com/pricing/
- Nylas 2025-07-20 pricing-changes release note — https://developer.nylas.com/docs/new/release-notes/2025-07-20-pricing-changes/
- Cronofy plans & pricing — https://docs.cronofy.com/developers/plans-pricing/
- Cronofy data management policy (cache + region) — https://docs.cronofy.com/policies/data-management/
- Cal.com self-host (AGPLv3, data on own infra) — https://github.com/calcom/cal.com ; https://ossalt.com/guides/self-host-cal-com-calendly-2026
- Composio Google Calendar toolkit — https://composio.dev/toolkits/googlecalendar
- Merge.dev unified calendar API — https://www.merge.dev/
- Recall.ai meeting-bot API (wrong category) — https://www.recall.ai/product/meeting-bot-api

**Secondary — operational caveat (CLAIMED, community):**
- calendarView/delta infinite-loop reports — https://learn.microsoft.com/en-us/answers/questions/5883982/ ; https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/3082

*Note: All SaaS pricing/data-handling claims are vendor-self-reported (CLAIMED tier) — not independently audited here. The five freshness facts are all OBSERVED/CORROBORATED from primary Google/Microsoft docs with on-page dates in April–May 2026.*
