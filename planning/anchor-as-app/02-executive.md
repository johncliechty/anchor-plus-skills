# Making Anchor an "App" — Executive Summary

**Date:** 2026-06-15 · **researchPrime** · ENGINE-capable host; Phase-3 adversarial loop run via real fresh-context sub-agents; `cross_model:false`.
**Scope: all three targets — Windows 11 desktop, iPhone, iPad.** Windows: `01-report.md`. iPhone/iPad: `04-ios-report.md`. Evidence: `evidence-ledger.jsonl` + `evidence-ledger-mobile.jsonl`.

## Platform map (one line each)
- **Windows 11 (the `PUTER` desktop):** installable **PWA** + `msedge --app=` shortcut. Zero new deps. Gated only on a one-time icon build.
- **iPhone / iPad:** the SAME manifest + **Apple meta tags**, reached over **Tailscale Serve HTTPS** (`https://gwl-server.<tailnet>.ts.net`), then Safari **"Add to Home Screen."**
- **⚠️ Cross-cutting security gate (mobile):** exposing Anchor over Tailscale **requires `ANCHOR_TOKEN` to be set** — the startup guard does NOT enforce it behind a same-box reverse proxy, so without it the whole tailnet can hit mutating endpoints (incl. the build lane). See `04-ios-report.md`.

---
## Windows 11

## The answer
Anchor is *already* a web app served at `localhost:8777` by an auto-starting Windows service. Making it "an app" is a thin presentation layer, and the right move costs **zero new dependencies**:

1. **Installable PWA (B1)** — serve a `manifest.webmanifest`, add one `<link>`, commit a proper icon set → Edge's **"Install this site as an app"** gives a real chromeless window with its own Start-menu/taskbar identity. Breaks none of Anchor's invariants (stdlib-only, markdown source-of-truth, the 8777 single-instance guard).
2. **`msedge --app=` shortcut (B2)** — a one-line edit to the existing `AnchorDashboard.vbs` opens a chromeless window with no install step and no server change; it's also the **only path that works for remote/Tailscale access**.

**Ship both** — they're complementary: B1 = best desktop identity on the host; B2 = zero-friction + remote.

## The one real task
There is **no 192/512 PNG icon** in the repo and Python stdlib can't rasterize SVG. So the single prerequisite is a **one-time, offline** icon build from `vendor/brand/gwl-m-icon.svg` (PIL is already in the dev env), with the PNGs **committed as static bytes**. Runtime stays stdlib-only.

## Three honest caveats (don't skip)
- **B1 ≠ self-launching.** It's a *window onto the live service*; auto-start is the NSSM service's job (already done). A PWA on a stopped service shows a connection error.
- **B1 installs on `localhost` only.** Reached as `PUTER`/`gwl-server`/a Tailscale IP, it's a non-secure origin and won't install — use B2 there.
- **Edge PWA install is bound to the Edge profile that created it** (and unsupported on roaming/FSLogix profiles). Irrelevant for the single fixed `PUTER` desktop, but real.

## What we deliberately did NOT recommend
- **PyInstaller `.exe` (B4):** solves "no Python installed" — not this deployment's problem; adds antivirus/SmartScreen/code-signing overhead.
- **Electron/Tauri (B5):** 80–150 MB + a whole new toolchain to wrap a localhost dashboard — disproportionate. (If Anchor ever ships as a many-machine product with auto-update, revisit **Tauri**.)
- **pywebview + tray (B3+B6):** a genuine upgrade *only if* you want a non-browser native window + a service-status tray, and accept one declared optional dependency (the `pywinpty` pattern). Optional, not default.

## Bottom line
Two small, zero-dependency changes (PWA manifest + `--app` shortcut), gated only on a one-time icon build, turn Anchor into a real desktop app while honoring every invariant. Everything heavier is unjustified for a single-host tool already running as a service.

---
## iPhone / iPad (full detail: `04-ios-report.md`, build steps: `05-ios-agent-impl.md`)
**Reuses the Windows manifest work; adds three things:** (1) **Tailscale Serve** for real HTTPS on the tailnet — load-bearing, because `http://<Tailscale-IP>` is **not** a secure context on iOS so a plain-HTTP PWA is degraded; (2) **Apple meta tags** + the existing 180×180 `anchor-touch.png` icon; (3) manual **Add to Home Screen** (iOS has no install prompt, ever).

**Three caveats that gate "good":**
- **SECURITY (must fix first):** set **`ANCHOR_TOKEN`** before any Tailscale exposure — Anchor's auth keys off the token env var alone and the startup guard won't enforce it behind Serve (loopback bind). Verified by adversarial audit. Recommended: make auth fail-closed.
- **Live transports:** WebSockets through `tailscale serve` have a known drop-every-~30s bug — use Anchor's SSE+POST fallback (or a WS keepalive) for the iPad terminal/board. The plain dashboard is fine.
- **Responsive:** the main dashboard adapts (one breakpoint); the **project/cockpit window has no responsive CSS** and needs reflow + safe-area work to be good on an iPhone. iPad landscape is usable sooner.

**Not recommended for mobile:** a native iOS wrapper (Capacitor/WKWebView) — App Store/signing friction, disproportionate for a tailnet-private personal tool.
