# Spike verdict — cookie through the WS upgrade (rearch W3)

Recorded against the PRE-WRITTEN acceptance questions (frozen with W3). Refreshed mechanically by `tools/cookie_ws_spike.py record_verdict`; never hand-edited. Consumed by W9 (cookie navigation + the ?token= WS fallback decision).

## Acceptance questions (pre-written)

- **Q-COOKIE-DESKTOP** — Does a desktop browser send the auth cookie (Cookie header, value intact) on a same-origin WebSocket upgrade request?
- **Q-COOKIE-PWA** — Does the iPhone PWA over Tailscale Serve HTTPS send the auth cookie on the WebSocket upgrade against the real service? (LIVE-MANUAL leg — runbook below, run with John.)
- **Q-FALLBACK** — Is ?token= declared as the WS fallback if the Cookie header doesn't survive?

## Q-COOKIE-DESKTOP — desktop browser (mechanical leg)

**Verdict: YES** — Cookie header arrived on the upgrade with the auth value intact

Browser: chromium (same-origin ws:// against the loopback capture server).

## Q-COOKIE-PWA — iPhone PWA over Tailscale HTTPS (LIVE-MANUAL leg)

**NOT YET RUN** — this leg needs the REAL clients (the phone + the live service over Tailscale Serve HTTPS) and is executed with John. Until it runs, W9 must treat the PWA as UNPROVEN and keep the ?token= fallback on its WS transport.

Runbook:

1. On the phone: install/refresh the Anchor PWA over the Tailscale Serve HTTPS origin (see planning/anchor-as-app).
2. Set ANCHOR_TOKEN on the service; sign the PWA in so the auth cookie is set for the HTTPS origin.
3. Open a project window and start a terminal (a term_ws upgrade).
4. On the server: log the upgrade request's Cookie header (temporarily, via the term_ws handler) — record whether the cookie arrived with the upgrade.
5. Record the answer with: python tools/cookie_ws_spike.py --record-pwa yes|no

## Q-FALLBACK — the declared WS fallback

**DECLARED.** ?token= remains the WS/SSE fallback: W9 adopts cookie-auth on a transport ONLY where a spike leg proved the cookie survives; every unproven client/transport keeps the query token (the W2 status quo).
