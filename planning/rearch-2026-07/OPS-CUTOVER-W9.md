# Auth enforce cutover — the C2 data-plane flip with teeth (rearch W9)

The W8 warn soak proved every would-401 consumer is accounted for. W9 turns the
gated data plane from *observed* to *enforced* and makes C2 **demonstrated, not
narrated**: after the flip a tokenless request to the LIVE `:8777` service must
return `401`.

This is the SECOND of the two-deploy sequence (`PROCESS-RAILS.md` §3 — the
auth-flip sequencing rule):

1. **W9 deploy A — the JS change (cookie navigation).** Ships the mechanism only
   (this wave's code): the browser primes an **HttpOnly auth cookie** at load
   (`POST /api/auth/login`) and the server authenticates page navigation +
   the `term_ws` upgrade off that cookie. Behavior is unchanged under
   `open`/`warn` — the cookie is simply *also* accepted. No route is flipped.
2. **W9 deploy B — the enforce flip (separate deploy).** Sets
   `ANCHOR_AUTH_MODE=enforce` on the live service. A tokenless data-plane
   request now gets a real `401`; the browser keeps working because the cookie
   carries it. **Never** in the same deploy as deploy A.

## The cookie navigation (deploy A — what shipped)

Per the cookie-through-WS spike (`SPIKE-COOKIE-WS-VERDICT.md`): the **desktop**
browser sends the auth cookie on the `term_ws` upgrade (proven), so page
navigation and the desktop terminal authenticate off the cookie — **no
shared-secret token rides in a page URL**. The **iPhone PWA** leg is UNPROVEN, so
`?token=` is retained as the declared WS/SSE fallback (the W2 status quo). That
is the only place a URL token survives.

Mechanism map:

- `paths.token_from_cookie` / `paths.build_auth_cookie` (`anchor_auth`;
  `HttpOnly; SameSite=Strict; Path=/`; `Secure` when `X-Forwarded-Proto=https`).
- `anchor_gui.handle_auth_login` / `handle_auth_logout` (migrated route rows
  `POST /api/auth/login` · `/api/auth/logout`, token-authed); the login handler
  Set-Cookies the caller's already-validated token. Mutating POSTs still require
  the explicit `X-Anchor-Token` header (never the cookie alone) — CSRF hardening.
- `AnchorHandler._term_token_ok` / `_presented_token` now also accept the cookie,
  so `_data_plane_gate` serves a cookie-bearing browser under `enforce`.
- Frontend `primeAuthCookie()` on `DOMContentLoaded` (dashboard) posts the token
  once to set the cookie before any page navigation.

The named hybrid state after deploy B is **`c2-enforced`** (`static · enforce ·
off · inline`) — `check_pillar_state` passes it, and the DAG requires
`frontend=static` for `auth=enforce` (cookie nav ships in the static assets).

## Running the cutover (deploy B — on the live `:8777`, with John)

> Ops step — performed by John on `PUTER` (elevated). The mechanism + the probe
> ship in this wave; the live flip is the ops action the merge checklist gates on.

1. Mint / confirm `ANCHOR_TOKEN` for the service (enforce only bites when a token
   is configured).
2. Set the NSSM `AppEnvironmentExtra` to include `ANCHOR_AUTH_MODE=enforce`
   (the named `c2-enforced` state). Confirm the frontend is already `static`
   (the DAG edge) and deploy A (cookie nav) is already live.
3. `nssm restart anchor` (elevated); confirm the new build via `GET /api/version`
   / `ANCHOR_BOOT` (no stale supervisor — `PROCESS-RAILS.md` §1).
4. **The tokenless-401 probe (the teeth):**
   `python tools/auth_cutover.py probe http://localhost:8777`
   — asserts a tokenless `GET /api/rnd/projects` returns **401**. Exit 0 = the
   flip took; non-zero = it did not (still open/warn) — investigate, do not
   record `enforced`.
5. Smoke the browser: sign in (token prompt), the dashboard loads, a project
   window opens, a terminal attaches — all via the cookie. Desktop first; the
   iPhone PWA over Tailscale keeps its `?token=` WS fallback until the PWA spike
   leg runs.
6. Record the outcome (never silent):
   `python -c "from tools import auth_cutover as a; a.record_cutover_outcome('enforced', detail='<observed>', probe=a.probe_tokenless_401('http://localhost:8777'))"`.

## Outcomes — the amendment path (a John-declines is recorded, never silent)

The cutover has exactly one recorded outcome (`OPS-CUTOVER-W9-OUTCOME.json`,
written by `tools/auth_cutover.record_cutover_outcome`):

| outcome | meaning |
|---|---|
| `pending` | not yet run (the checked-in default until the cutover) |
| `enforced` | live tokenless-401 observed — **C2 demonstrated** |
| `held` | a would-401 was unexplained in the soak — flip HELD (W8 review gate) |
| `declined` | **John declined the flip** — recorded via the North-Star amendment path |

A **`declined`** outcome MUST cite the North-Star amendment (`amendment_ref=…`);
`record_cutover_outcome('declined', …)` refuses to write without it. So a
decision to *not* enforce (e.g. keep `warn` indefinitely) lands as an explicit,
citable amendment in `IMPLEMENTATION-PLAN.md` — never a silent skip.

## Rollback

A rollback of the flip is a **flag change** (`ANCHOR_AUTH_MODE=warn` or unset)
+ `nssm restart anchor` — **never a code revert** (the pillar off-switch
discipline, `pillar_flags.py`). The cookie navigation code stays live in every
state (it is only *also-accepted* under `open`/`warn`).

## Cookie/auth healthcheck walk — entering the 20× pipeline

`anchor_healthcheck.check_cookie_auth_walk` is the stubbed, in-process
end-to-end cookie/enforce walk. Per `PROCESS-RAILS.md` §2 it ENTERS the 20×
nightly repetition pipeline (`anchor_healthcheck.run_soak_candidates`, run via
`python anchor_healthcheck.py --soak`) and is **NOT** joined to the 5AM run until
it has **20 consecutive green nights** (`soak_ready`) — the join is W18's job.
