# Anchor on iPhone / iPad — Agent / Build-Implementation Spec

Steps for a coding agent to make Anchor a home-screen app on iPhone/iPad over Tailscale, building on the Windows PWA work (`03-agent-impl.md`). Evidence tags → `evidence-ledger-mobile.jsonl` (M#). **Do Task 0 first — it is a security gate.**

## Task 0 — SECURITY GATE: mandatory auth behind any reverse proxy `[M1, M2]`
Before exposing Anchor over Tailscale Serve:
1. **Set `ANCHOR_TOKEN`** in the `anchor` NSSM service environment (a long random secret). Without it, every mutating endpoint — incl. the build lane — is open to the whole tailnet, because the startup bind guard only checks the *direct* bind host, not a same-box proxy. `[anchor_gui.py:10076-10093; paths.py:120-142]`
2. **Recommended code hardening (fail-closed):** add an env opt-in so Anchor refuses to serve mutating endpoints when no token is set *unless* `ANCHOR_ALLOW_INSECURE_LOCAL=1` is explicitly present. Implement in the `do_POST` auth middleware (`anchor_gui.py:8913-8928`) and/or `resolve_bind_host`. Do NOT rely on a peer-IP check — a proxied peer is always `127.0.0.1`.
3. Verify `enable_remote.ps1`'s pattern (token + direct Tailscale-IP bind) still works and document the Serve-path token requirement next to it. `[enable_remote.ps1:15-17]`

## Task 1 — Transport: Tailscale Serve HTTPS in front of loopback `[M4, M11, M12]`
(Host setup, not code — document in the plan/runbook.)
1. Keep Anchor loopback: `python anchor_gui.py --no-browser` on `127.0.0.1:8777` (already default). Backend must stay loopback-only behind Serve.
2. One-time: enable MagicDNS + HTTPS Certificates in the Tailscale admin console (tailnet `tailb49f65.ts.net`). `[M12]`
3. Persistent proxy: `tailscale serve --bg 8777` → `https://gwl-server.<tailnet>.ts.net`; verify `tailscale serve status`. Ensure it re-applies on reboot (`--bg` persists). **Use Serve, never Funnel.** `[M11]`
4. Install Tailscale on the iPhone/iPad, log into the same tailnet.

## Task 2 — App skin: manifest + Apple meta tags in `generate_html()` head `[M6, M7]`
Reuse the Windows manifest (Task 2 of `03-agent-impl.md`); add an opaque **180×180** PNG icon for iOS (rasterize the GWL mark; or reuse the existing `anchor-touch.png` 180×180). Add to the dashboard `<head>` near `anchor_gui.py:6236-6241` (double `{{ }}` in f-strings):
```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0f172a">
<link rel="apple-touch-icon" sizes="180x180" href="/anchor-touch.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Anchor">
```
Manifest (served per `03-agent-impl.md` Task 2) — iOS honors `name`/`short_name`/`scope`/`start_url`/`display`/`theme_color`/`icons`/`id`; include the 180 (iOS) alongside the 192/512 (desktop). Keep navigation within `scope` so off-scope links don't bounce to Safari. `[M6]`

## Task 3 — Live transports over Serve `[M3, M9]`
1. The WS client scheme is already proxy-correct (`wss:` when `https:`); no change needed for mixed-content. `[anchor_gui.py:5096-5098]`
2. Because of Tailscale Serve WS-drop bug #18827, for the iPad terminal/live board **prefer the SSE-out + POST-in fallback** (`term_stream2`/`term_input2`, `/api/rnd/tail`) and/or add an application-level **WS keepalive ping** every few seconds. Make the transport selectable or auto-fallback on early WS close. `[M3]`

## Task 4 — Responsive cockpit (the real UI work) `[M10]`
1. Add a **viewport meta** to `render_project_window_html`'s `<head>` (`anchor_gui.py:2619-2624`) — currently absent.
2. Add `@media` rules so the 5-column `.p2lanes` Kanban reflows to a single column / horizontal-scroll on ≤768px; the main dashboard's lone breakpoint at `anchor_gui.py:6693` is the pattern to extend.
3. Add `env(safe-area-inset-*)` padding (top/bottom) on the masthead and panels for the notch/home-indicator. iPad landscape (≥768px) is already usable; prioritize iPhone reflow.
4. **UI-wave gate applies** (the v4 lesson): rendered-DOM assertions + a real Playwright+Chromium check at iPhone viewport (e.g. 390×844) + a screenshot. Playwright stays a DEV-only test dep.

## Task 5 — Verification `[M5, M8]`
- On the iPad/iPhone: open `https://gwl-server.<tailnet>.ts.net` in Safari → Share → **Add to Home Screen**; confirm a standalone chromeless window + GWL icon + "Anchor" title.
- Confirm a **valid HTTPS cert** (no warning) and that a mutating action requires the token (Task 0).
- Confirm the live board/terminal works via the SSE fallback (not dropping every ~30s).
- Note the **re-auth** behavior: after ~7 days or storage pressure the app may be "logged out" — confirm the token can be re-entered cleanly (don't hard-depend on persisted `localStorage`). `[M8]`

## Definition of done
Anchor opens as a standalone home-screen app on iPhone+iPad over a valid HTTPS MagicDNS URL; `ANCHOR_TOKEN` is set (mutating endpoints authenticated); the live board works via SSE through Serve; the cockpit reflows at iPhone width with safe-area handling; no new Python runtime dependency; backend stays loopback; single-instance guard untouched; Funnel never used.
