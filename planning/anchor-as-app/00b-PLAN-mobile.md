# researchPrime — Phase 1 PLAN addendum: iPhone / iPad (frozen)

**Question:** How to make Anchor a first-class **home-screen app on iPhone + iPad**, given Anchor is a Python-stdlib server bound to `127.0.0.1:8777` on the Windows desktop (`PUTER`/`gwl-server`), run as the NSSM service — **without breaking Anchor's invariants** (stdlib-only core, markdown source-of-truth, loopback bind, 8777 single-instance guard)?
**Date:** 2026-06-15 · Mode: ENGINE-capable host · Sub-agent isolation: real. Extends `00-PLAN.md` (Windows pass).

## AXIS (mobile win-condition)
A candidate wins if an iPhone/iPad gets a real **home-screen app** (icon, standalone chromeless window, launch from the Home Screen) that **reaches the desktop's Anchor and works** (the live transports — WebSocket terminals + SSE — function), **while the Anchor server stays loopback-bound** (no new exposure) and **no new Python runtime dependency** is added.

### Kill-criteria (mobile)
1. Forces Anchor to bind beyond loopback / weakens the auth posture (token/exposure regression).
2. Requires a new mandatory Python runtime dependency (stdlib-only core).
3. Breaks the live transports (WS terminals / SSE) when reached from the phone.
4. Exposes Anchor to the **public internet** (Tailscale **Funnel**), not just the private tailnet.

## Stakes VECTOR → tier
- Impact: medium. Reversibility: high (Serve config + meta tags are additive/removable). Blast radius: **medium-high** — the real hazard is *exposure* (binding wide / Funnel / weak auth on the tailnet). Irreversibility: none.
- **→ tier MEDIUM**, but with a security-weighted lens on kill-criteria #1/#4.

## Candidate branches
- **M1 — Tailscale Serve (HTTPS, tailnet-private) + installable PWA / Add-to-Home-Screen.** Serve runs on the desktop, terminates TLS with a real MagicDNS cert, reverse-proxies `https://gwl-server.<tailnet>.ts.net` → `http://127.0.0.1:8777`. Anchor stays loopback. iPad/iPhone add to Home Screen over genuine HTTPS (secure context).
- **M2 — Plain Tailscale IP/MagicDNS over HTTP** (`http://gwl-server:8777`, Anchor bound to the Tailscale interface). No TLS → non-secure origin on iOS (no service worker, degraded PWA), and forces a non-loopback bind (trips kill-criterion #1). Documented as the inferior path.
- **M3 — Native iOS app / wrapper (Capacitor/WKWebView/Shortcut).** Heaviest; App Store / sideload friction; disproportionate.
- **M4 — Apple meta-tag layer** (`apple-mobile-web-app-capable`, `apple-touch-icon`, status-bar style) — not a transport; a required *complement* to M1 for a clean iOS standalone app.

## Best-in-class baselines
- "Self-hosted dashboard on iPhone via Tailscale Serve + PWA" (the Home Assistant / Syncthing / *arr-stack self-hoster pattern).
- Native-wrapped webview (Capacitor) as the heavyweight baseline to beat.

## Oranges foresight receipt
- **De-prioritized:** M3 (native wrapper). **Counterfactual cost:** loses App-Store-grade polish/offline; but for a single user's tailnet-private tool, a Home-Screen PWA over Tailscale Serve delivers the app feel at ~zero cost, and M3's distribution/signing burden is unjustified. Loss is covered by M1.

## Method (fresh execution derives only from this plan)
1. LOCAL: does Anchor behind a reverse proxy keep WS/SSE working; how does the loopback-vs-token auth classify a Serve-proxied (loopback peer) request; is the dashboard usable on a phone-width screen (viewport/responsive); existing apple-touch-icon.
2. WEB: iOS/iPadOS 2026 Add-to-Home-Screen / PWA reality (Safari manifest support, required Apple meta tags, standalone gotchas, icon specs); Tailscale Serve specifics (cert, MagicDNS, WebSocket proxying, Serve vs Funnel, ACLs).
3. Phase-3 adversarial: exposure/auth, WS-through-Serve, iOS standalone session/cookie loss, secure-context.

**PLAN ADDENDUM FROZEN.**
