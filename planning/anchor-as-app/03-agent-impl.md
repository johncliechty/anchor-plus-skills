# Making Anchor an "App" — Agent / Build-Implementation Spec

Concrete steps for a coding agent (Foreman/expert-coder) to implement the recommended **B1 (installable PWA) + B2 (`--app` shortcut)**. Scope: zero new runtime dependencies; honor stdlib-only, markdown-source-of-truth, and the 8777 single-instance guard. Evidence tags reference `evidence-ledger.jsonl`.

## Preconditions / anchors in the existing code
- Static-asset serving pattern + content-type map: `anchor_gui.py:716-742` (`brand_asset`, `_BRAND_CONTENT_TYPES` already maps `.png`). `[E7]`
- Existing icon routes to mirror: `/favicon.ico`, `/anchor.png`, `/anchor-touch.png` at `anchor_gui.py:8263-8295`; icon `<link>`s in `<head>` at `anchor_gui.py:6238-6241`. `[E7]`
- Brand source SVG: `vendor/brand/gwl-m-icon.svg`. `[E7]`
- Import-scan allowlist (do NOT add a runtime import; this stays empty of new entries for B1/B2): `distro.py:147-152`. `[E1]`
- Bind guard is bind-time and unaffected by new routes: `paths.py:298-335`, `anchor_gui.py:10018-10044`. `[E3]`

## Task 1 — Icon set (the gating prerequisite) `[F2, E8]`
Stdlib cannot rasterize SVG; produce PNGs **offline** and **commit the bytes** (this does not violate the import scan — committed bytes ≠ an `import`).
1. From `vendor/brand/gwl-m-icon.svg` generate, with any tool (PIL is in the dev env; or Inkscape/online), into `vendor/brand/`:
   - `icon-192.png` (192×192)
   - `icon-512.png` (512×512)
   - `icon-512-maskable.png` (512×512, with ~10% safe-zone padding; `purpose:"maskable"`)
2. Commit the three PNGs. Do **not** add a rasterizer to the runtime path. `create_shortcut.py`'s PIL use stays a build-only script (already off the import path).

## Task 2 — Serve the manifest `[E11, E12]`
1. Add a route `GET /manifest.webmanifest` returning `application/manifest+json` (mirror the `/anchor.png` static branch at `anchor_gui.py:8263-8295`; cache ~86400s). Body:
```json
{
  "id": "/?app=anchor",
  "name": "Anchor",
  "short_name": "Anchor",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#0f172a",
  "theme_color": "#0f172a",
  "icons": [
    { "src": "/vendor/brand/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/vendor/brand/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/vendor/brand/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```
   - Keep the colors aligned with the GWL palette already in use (`#0f172a` slate / `#22c55e` green).
   - Set `id` ONCE and never change it (changing `start_url` later without a stable `id` creates duplicate installs). `[E12]`
   - Ensure the `.png` icon routes resolve (they ride the existing `/vendor/brand/` traversal-safe route + `_BRAND_CONTENT_TYPES`). `[E7]`
2. Add to the dashboard `<head>` (near `anchor_gui.py:6238-6241`):
```html
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0f172a">
```

## Task 3 — Do NOT touch the service-worker cleanup `[F1, E6]`
Leave the SW-unregister/cache-clear JS at `anchor_gui.py:105-141` as-is. A manifest-only PWA needs no SW; installability does not require one. (Note for the future: that cleanup will delete any SW you add later — revisit only if offline caching is ever wanted.)

## Task 4 — B2 chromeless `--app` launcher `[E14, E4]`
Add a sibling launcher (don't break the existing browser-only ones). Either edit a copy of `AnchorDashboard.vbs` or add `AnchorApp.vbs`:
```vbscript
' AnchorApp.vbs — opens Anchor as a chromeless app window. Opens a URL only; never starts a server.
Set sh = CreateObject("WScript.Shell")
sh.Run "msedge.exe --app=http://localhost:8777", 1, False
```
- Keep it **browser-only** (no server spawn) — matches the documented launcher rule. `[E4]`
- Optionally have `pin_anchor_to_taskbar.vbs`/`create_shortcut.py` point a shortcut at this for a chromeless pinned launcher.
- Caveat to encode in a comment: `--app` is an unsupported flag (works today, no guarantee); window groups under Edge's identity. `[E14]`

## Task 5 — Verification (UI-wave standard applies if you touch render) `[E13]`
- **Manifest validity:** load `http://localhost:8777`, open Edge DevTools → Application → Manifest → assert no errors and that the install affordance appears. Missing 192/512 PNG silently suppresses install — check explicitly.
- **Install round-trip:** install via Edge, confirm a chromeless standalone window + Start-menu entry + own icon; confirm relaunch from Start works (same Edge profile — `[E13]`).
- **Remote check:** confirm B1 does NOT offer install over `http://PUTER:8777` (expected — non-secure origin) and that **B2 `--app`** opens a chromeless window there. `[E10]`
- **Invariant regression:** run `python distro.py` (or its import-scan entrypoint) and assert the third-party import scan still passes with no new entries; run the healthcheck. `[E1]`
- If `generate_html()` is modified, the project's UI-wave gate applies: rendered-DOM assertion + a real Playwright+Chromium check + a screenshot. (Playwright stays a DEV-only test dep.)

## Out of scope (do not implement unless explicitly asked)
- B3 pywebview / B6 pystray tray → would need a NEW `desktop` optional extra in `pyproject.toml` + a `distro.py` allowlist entry scoped to one new module (mirror the `pywinpty`/`terminal` pattern) + WebView2 detect-and-install. `[E15]`
- B4 PyInstaller `.exe`, B5 Electron/Tauri → explicitly not recommended for this deployment. `[E16, E17]`

## Definition of done
PWA installs on the host with the GWL icon and a chromeless window; `AnchorApp.vbs` opens the same chromeless window with no install step; `distro.py` import scan + healthcheck stay green; no new runtime dependency; no change to the 8777 guard or the markdown data model.
