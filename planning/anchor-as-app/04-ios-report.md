# Anchor as a Home-Screen App on iPhone / iPad — researchPrime Report

**Question:** Make Anchor a first-class home-screen app on **iPhone + iPad**, given it's a Python-stdlib server bound to `127.0.0.1:8777` on the Windows desktop (`PUTER`/`gwl-server`, in a Tailscale tailnet), without breaking Anchor's invariants. Extends the Windows pass (`01-report.md`).

**Skill:** researchPrime · **Date:** 2026-06-15 · ENGINE-capable host; Phase-3 = real fresh-context sub-agents (2 evidence + 1 adversarial verifier). `cross_model:false`. **ISOLATION:** main = approximated (derives from `00b-PLAN-mobile.md`); sub-agents = real.
**Ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED → `evidence-ledger-mobile.jsonl` (M#).

---

## TL;DR
Yes — achievable in 2026, and the architecture splits cleanly into **transport** (Tailscale) and **app skin** (manifest + Apple tags). The Windows PWA work is reused; iPhone/iPad add three things:

1. **HTTPS over the tailnet via `tailscale serve`** — the load-bearing piece. iOS needs a **secure context** for a real PWA, and `http://<Tailscale-IP>:8777` is **not** one. `tailscale serve` puts a real Let's Encrypt cert on `https://gwl-server.<tailnet>.ts.net` in front of the still-loopback Anchor. `[CORROBORATED | M4, M11]`
2. **Apple meta tags + a 180×180 opaque PNG icon** (most already half-present) → a clean standalone home-screen app. `[CORROBORATED | M6, M7]`
3. **Manual "Add to Home Screen"** via Safari's Share sheet (iOS has no install prompt, ever). `[CORROBORATED | M5]`

**But there is a hard prerequisite that is a SECURITY gate, not a nicety — read the next section before doing anything.**

---

## ⚠️ BLOCKER: exposing Anchor over Tailscale **requires `ANCHOR_TOKEN`**, and the startup guard will NOT enforce it behind Serve

This is the most important finding of the mobile pass, **VERIFIED** by an adversarial code audit. `[OBSERVED | M1]`

- Anchor decides "is a token required?" **solely** by whether `ANCHOR_TOKEN` is set. There is **no** request peer / remote-address / Origin / CSRF check anywhere. `auth_ok(None)` returns `True` when no token is configured. `[paths.py:120-142; anchor_gui.py:8913-8928]`
- The startup safety guard only **refuses a *direct* non-loopback bind** without a token (`resolve_bind_host`). `[anchor_gui.py:10076-10093]`
- `tailscale serve` runs on the same box and forwards to `127.0.0.1:8777`, so Anchor stays **loopback-bound** → the guard **does not fire** → if `ANCHOR_TOKEN` is unset (the default), **every mutating `POST /api/*` — including the build-lane launch that spawns `claude`/`gemini` in `bypassPermissions` (an RCE-class surface) — is reachable unauthenticated by *any device on the tailnet***. Read GETs are ungated by design; the terminal WS/SSE GETs check `?token=` but also pass when no token is set. `[OBSERVED | M1]`

**Mitigation (do BOTH):**
- **Operationally:** never run `tailscale serve` in front of Anchor without `ANCHOR_TOKEN` set in the *service's* environment. The documented `enable_remote.ps1` path is already safe (it sets the token + binds the Tailscale IP directly, which the guard backstops) — but the manual-Serve path bypasses that guard. `[OBSERVED | M2]`
- **Code (recommended hardening):** make auth **fail-closed** — require `ANCHOR_TOKEN` unless an explicit `ANCHOR_ALLOW_INSECURE_LOCAL=1` opt-in is set, so a reverse-proxied deployment can't silently run open. A peer-IP filter would NOT fix this (the proxied peer is always loopback); the durable fix is mandatory auth decoupled from bind interface. `[OBSERVED | M1]`

*Residual honesty:* whether the **live** service currently has `ANCHOR_TOKEN` set, and whether Serve is already wired, is runtime state not in the repo — verify on the host before exposing. `[M1, M12]`

---

## The second real caveat: live transports through Serve

Anchor's terminals use a hand-rolled WebSocket (`/api/rnd/term_ws`) with an **SSE-out + POST-in fallback** (`term_stream2`/`term_input2`) and SSE long-poll for logs (`/api/rnd/tail`). `tailscale serve` has an **open bug (#18827): WS connections drop every ~10–40s** (close 1001). `[CORROBORATED | M3]`
- The plain dashboard (GET `/`, POST `/api/*`) is request/response and works fine through Serve.
- For the live terminal/board on iPad, **prefer the SSE+POST fallback transport** and/or add a WS keepalive ping.
- Good news: the WS client JS is already proxy-correct — it builds `wss://` from `location.protocol`/`location.host`, so there's **no mixed-content risk** behind HTTPS. `[OBSERVED | M9]`

---

## The third caveat: the cockpit isn't responsive yet

- The **main dashboard** has a viewport meta + one `@media(max-width:768px)` rule (hides the sidebar, wraps stat cards) — usable-ish on a phone. `[OBSERVED | M10]`
- The **project/cockpit window** (`render_project_window_html`) has **no viewport meta and no media queries** — its 5-column Kanban renders at desktop width on a ~390px iPhone. The cockpit needs responsive work + `viewport-fit=cover` + `env(safe-area-inset-*)` padding for the notch before it's a good phone app. iPad (≥768px landscape) is far more usable as-is. `[OBSERVED | M10, M6]`

---

## iOS rough edges to set expectations (honest list) `[CORROBORATED | M5,M6,M8]`
1. **No install prompt** — manual Share → Add to Home Screen; show a one-time hint.
2. **HTTPS mandatory** for a real PWA/SW — `http://<Tailscale-IP>` is not a secure context; Serve is non-optional for the full experience.
3. **~7-day storage eviction + storage separate from the Safari tab** → "logged out on reopen." Anchor reads its token from `localStorage`, so plan a re-auth path; don't rely on a persisted token.
4. **Off-scope links open in Safari**, breaking the in-app feel — keep navigation within `scope`.
5. **Icon must be an opaque 180×180 PNG** via `apple-touch-icon` (you already ship `anchor-touch.png` at 180×180). `[OBSERVED | M7]`
6. **Safe-area** needs `viewport-fit=cover` + `env(safe-area-inset-*)` or content clips under the notch/Dynamic Island.
7. A **service worker is optional** (Anchor is online-only against the live server); not needed for a usable home-screen app, but available once Serve gives you HTTPS.

---

## Branch verdict (mobile)
- **M1 — Tailscale Serve (HTTPS, tailnet-private) + Add-to-Home-Screen + Apple tags → RECOMMENDED.** Reuses the Windows manifest work; backend stays loopback; real cert; private to the tailnet. Gated on `ANCHOR_TOKEN` (above). `[CORROBORATED | M4,M11]`
- **M2 — plain HTTP over the Tailscale IP (`enable_remote.ps1` direct bind) → token-safe but iOS-degraded** (non-secure origin: no SW, weaker standalone). Acceptable as a quick path; inferior to Serve for a real app. `[CORROBORATED | M4]`
- **M3 — native iOS wrapper (Capacitor/WKWebView) → NOT recommended.** App Store/sideload + signing friction, disproportionate for a single-user tailnet tool. `[plan M3]`
- **M4 — Apple meta-tag layer → REQUIRED complement** to M1 (not a standalone option). `[CORROBORATED | M6]`

## Convergence
The adversarial verifier **confirmed** the load-bearing security claim (VERIFIED, with one precision: terminal GETs are token-gated but still open when no token is set) and surfaced the safe `enable_remote.ps1` counter-path — no claim was refuted, the recommendation was sharpened (token is mandatory, not optional). All other findings are documented caveats, none a further blocker. Run is **dry**.

See `05-ios-agent-impl.md` for concrete build steps, and `02-executive.md` for the all-three-platform summary.
