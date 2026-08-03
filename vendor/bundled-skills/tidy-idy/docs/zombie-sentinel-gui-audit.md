# Zombie-Sentinel GUI server audit — safe-to-lift vs needs-redesign (Wave 6)

**Status:** written from the Sentinel's ACTUAL source, not from its docs.
**Sources read:** `<path> Foundry\skills\zombie-hunter\src\server.js` (395
lines) and `src\ipc.js` (78 lines), 2026-07-21.
**Why this exists:** the Triage Panel is the second local-loopback GUI server in
this portfolio. The first one already works and is proxied by an Anchor button,
so the honest question before writing a line of panel code was *what may be
lifted from it, and what must not be*. This document answers that per endpoint,
and every "needs-redesign" row names the tidy-idy invariant the Sentinel's
behaviour would break.

The short version: **the Sentinel's SHAPE is safe to lift and its AUTHORITY
MODEL is not.** That is not a criticism of the Sentinel — it is a different
threat model. The Sentinel's mutating operations (freeze / kill) are
*recoverable* and it is explicitly OBSERVE-ONLY by default. Tidy-Idy's mutating
operation writes a commit and moves files, so the same open control plane would
hand every local process on the box a delete button.

---

## 1. Per-endpoint verdicts

| Sentinel endpoint | What it does (source) | Verdict | Reasoning |
| --- | --- | --- | --- |
| `GET /` | `res.writeHead(200, text/html)` + `generateDashboard()` — a server-rendered page with an inline `<script>` holding the whole client | **SAFE TO LIFT (shape only)** | Server-rendered single page, no build step, no framework, no asset pipeline. Tidy-Idy's `engine/panel/render.mjs` uses the same shape. What is NOT lifted: the page is served from `/` unconditionally. Ours is served only as the response to a redeemed single-use bootstrap nonce, because ours carries a capability token in its body. |
| `GET /api/state` | returns the whole cached sweep: engines, ledger, incidents, `frozen` pid list | **SAFE TO LIFT (shape only)** | A single JSON read endpoint returning the server's whole view is exactly right, and it is genuinely side-effect-free. Ours is `GET /api/panel`. Divergence: ours is token-gated, because a run envelope carries file paths and finding evidence for a *private repository*; the Sentinel's state is machine-global process data the caller could get from `tasklist` anyway. |
| `POST /api/sweep` | `runSweep()` — forks a worker, mutates cached state | **NEEDS REDESIGN** | Unauthenticated mutation. Harmless there (a sweep is a read of the process table). Fatal here: the equivalent (`/api/rescan`) closes the panel and starts a new run holding the project lock, so it takes token + Origin check + run-ID match. |
| `POST /api/freeze` / `POST /api/unfreeze` | suspends/resumes arbitrary PIDs from the request body | **NEEDS REDESIGN** | No authentication, no origin check, and the target is fully attacker-chosen. Reversible and auto-resuming there. Our nearest analogue is `POST /api/restore`, whose target set is constrained to what a journal says this project's Trash holds — a caller cannot name an arbitrary path. |
| `POST /api/kill` | `taskkill /PID n /T /F` on caller-supplied pids | **NEEDS REDESIGN — the load-bearing row** | Any local process, and any web page the user has open (see §2 on CORS), can POST here and tree-kill processes. The Sentinel accepts that because a killed agent is re-launchable. `POST /api/apply` writes a commit and moves files, so it carries: a 256-bit in-memory-only capability token in a header, an Origin/Referer check, a run-ID match, full per-finding identity round-trip, and a one-Apply-per-run persisted state machine. |
| IPC named pipe (`\\.\pipe\zombie-hunter-ipc`) | `relaunch_sweep` command, no auth | **NOT LIFTED** | Tidy-Idy has no second control channel. One surface, one authority model. A second channel is a second place to get authorization wrong. |

## 2. Cross-cutting findings

| Sentinel behaviour (source) | Verdict | What tidy-idy does instead |
| --- | --- | --- |
| `sendJson` sets `Access-Control-Allow-Origin: *` plus `Access-Control-Allow-Methods: GET,POST,OPTIONS` on **every** response, including the mutating ones, and answers `OPTIONS` with 204 | **NEEDS REDESIGN** | This is the single most dangerous line in the file: it converts "localhost-only" into "any website you visit can kill your processes", because the browser will happily send the cross-origin POST and the wildcard tells it the response may be read. Tidy-Idy emits **no CORS headers at all** and *refuses* a POST whose `Origin` or `Referer` is not its own (`checkOrigin`, Amendment C.iii). |
| `server.listen(PORT, '127.0.0.1')` | **SAFE TO LIFT** | Loopback binding is correct and we do the same — `LOOPBACK = '127.0.0.1'`, never `0.0.0.0`, never a resolvable hostname. |
| Fixed port `48484` (`ZH_PORT`) | **NEEDS REDESIGN** | A predictable port is a discoverable one, and combined with no auth it is trivially findable by a hostile local process. Tidy-Idy defaults to `port: 0` (kernel-assigned) and the port is learned only from the launcher's own output. |
| No authentication anywhere | **NEEDS REDESIGN** | Per-run 256-bit CSPRNG token, minted in server memory at run completion, transported exactly once through a single-use bootstrap-nonce redemption, held in browser memory only, presented in a header. Never on disk, in a URL, in a query string, in a `Referer`, or in a log line. |
| Server lives forever (`setInterval(runSweep, 60_000)`, unref'd; no shutdown path) | **NEEDS REDESIGN** | A daemon is correct for a machine-wide sentinel and wrong for a per-run panel that holds a project lock. Ours exits — and releases the lock — on explicit close, on an idle timeout, and on a heartbeat gap (closed tab); a SIGKILL is covered by the stale-PID-aware lockfile. |
| Client-side `confirm()` before kill | **SAFE TO LIFT (as UX, never as a control)** | We use per-tile individual confirmation for quarantine and heuristic tiles — but as an *additional* gate on top of server-side refusal, never as the gate. A control-plane whose safety lives in the browser has no safety. |
| Dashboard reads state via `fetch(API + '/api/state')` and `location.reload()` | **SAFE TO LIFT** | Plain `fetch` + a server-rendered page, no framework. Ours keeps that, adding only the token header on every request. |
| No storage APIs used in the page | **SAFE TO LIFT — and it is now an invariant** | The Sentinel happens to use no `localStorage`/`sessionStorage`/cookie. For us that is a REQUIREMENT (the token lives in browser memory only) and it is asserted by a test that greps the rendered HTML. |

## 3. What was actually lifted

1. **Server-rendered single page, inline script, no build step.** Same shape,
   different content.
2. **One JSON endpoint returning the server's whole view**, with the page
   rendering from that same object — which is why `engine/panel/model.mjs` is a
   pure function that both the HTML renderer and `GET /api/panel` consume.
3. **Loopback binding.**
4. **`fetch`-based POST actions with immediate optimistic UI feedback.**

## 4. What was deliberately NOT lifted

1. Wildcard CORS (`Access-Control-Allow-Origin: *`) — replaced by an
   Origin/Referer *refusal*.
2. Unauthenticated mutating endpoints — replaced by header-carried capability
   token + full finding identity + a persisted one-Apply-per-run state machine.
3. A fixed, predictable port — replaced by a kernel-assigned one.
4. An immortal server — replaced by the three-exit lifecycle that releases the
   project lock.
5. A second control channel (the IPC named pipe) — not reproduced.

## 5. The GET audit this produced

The Sentinel's `/api/state` is side-effect-free by accident of how it was
written; nothing enforces it. For tidy-idy that property is enforced by an
exported route table (`GET_ENDPOINTS` in `engine/launch/panel-server.mjs`) that a
server-side test crawls: every GET must be side-effect-free and must contain no
token bytes, the already-redeemed bootstrap URL must refuse, and no sequence of
GETs may yield a credential that any Apply POST accepts. The route table is
exported precisely so the test enumerates the real thing rather than a
hand-maintained copy of it.
