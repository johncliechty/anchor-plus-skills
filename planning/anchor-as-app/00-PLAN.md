# researchPrime — Phase 1 PLAN (frozen)

**Question:** What is the best-in-class way to make **Anchor** — currently a stdlib-only Python `http.server` rendering a browser dashboard at `http://localhost:8777`, run as the NSSM Windows service `anchor` — into a first-class **"app"** (one-click launch, dedicated app window, Start/taskbar presence, ideally auto-start), **without breaking Anchor's locked invariants**?
**Skill:** researchPrime · **Mode:** ENGINE (Node GO) · **Sub-agent isolation:** real
**Date:** 2026-06-15

## AXIS (load-bearing win-condition)
A candidate wins if it delivers a genuine **app experience** (chromeless/native window, launches in one click, has a Start-menu/taskbar identity, optionally auto-starts) **while preserving ALL of Anchor's invariants**.

### What FALSIFIES a candidate (the kill criteria)
1. **Breaks stdlib-only core** — adds a *mandatory* native/third-party dependency to product code. (Only the already-declared `pywinpty` *optional* extra is tolerated; a new dep must be an opt-in extra, never core. `distro.py`'s import scan would reject it.)
2. **Breaks the data model** — stops the markdown files in `C:\dev\Anchor` from being the source of truth, or introduces a DB/binary store.
3. **Re-introduces the 8777 duplication bug** — spawns a second server / second supervisor (the rogue `Anchor-Server` pain). Must respect the single-instance `SO_EXCLUSIVEADDRUSE` guard and the "launchers only open the browser, never spawn a server" rule.
4. **Platform regression** — won't run on Windows 11 + Python 3.8+, or makes Anchor inaccessible from a plain CLI / other tools.

## Stakes VECTOR  →  tier
- **Impact:** medium (quality-of-life; Anchor already works as service + browser).
- **Reversibility:** high — every viable approach is an *additive launcher/entrypoint*; reverting = delete the launcher. Data untouched.
- **Blast radius:** low–medium — the ONE real hazard is server/port duplication on 8777.
- **Irreversibility:** none forcing a higher tier.
- **→ Governor tier: MEDIUM** (full Synthesizer + Judge + convergence; the 8777 blast-radius and "is this a real dep?" call justify > low).

## Candidate branches (no winner named)
- **B1 — Installable PWA** served by `anchor_gui.py` (add `manifest.webmanifest` + minimal service worker; Edge/Chrome "Install this site as an app"). Pure stdlib.
- **B2 — Chromeless browser-app shortcut** (`msedge --app=http://localhost:8777` / `chrome --app=`) via a `.lnk`/`.vbs`. Zero code.
- **B3 — pywebview** native window (Edge WebView2 host) pointing at the service or serving in-process; enables a system tray. New dependency.
- **B4 — Single-file `.exe`** via PyInstaller/Nuitka (bundle server; double-click launches + opens app window). Distribution to other machines.
- **B5 — Electron / Tauri** native shell over the web UI. Heaviest; Node/Rust toolchain.
- **B6 — System-tray launcher** (pystray/native) that opens/restarts the app window and reflects service health.
- **B7 — Enhance existing launchers** (`pin_anchor_to_taskbar.vbs`, `AnchorDashboard.vbs`) into a proper Start-menu app identity.

## Best-in-class baselines to beat
- "Web app in a native shell" heavyweight (VS Code / Slack / Notion = Electron).
- "Installable PWA" lightweight (Chrome/Edge PWA install → standalone window).
- "Local-first single-exe + tray" (Syncthing tray, calibre) for the cross-machine distributable.

## Oranges foresight receipt (required)
- **Dropped/de-prioritized branch:** **B5 (Electron/Tauri)** — pushed to "documented, NOT recommended."
- **Counterfactual cost of dropping it:** Electron/Tauri is the only branch that yields a fully self-contained, non-browser-dependent native shell. If John's real need is a polished offline distributable for *other* machines (no running service), a pure-browser approach (B1/B2) fails there. **Mitigation kept in scope:** **B4 (PyInstaller single-exe)** covers the "self-contained cross-machine artifact" need far more cheaply and within the stdlib ethos — so B5's loss is covered, not unhedged.

## Method (fresh execution will derive only from this plan)
1. **Local constraint audit** (fresh sub-agent, real isolation): nail the exact invariants + inventory existing launcher/distro/favicon assets and the single-instance guard.
2. **External best-in-class** (fresh sub-agent, web): 2026 state + tradeoffs of B1–B6 for a *local Python web app → Windows desktop app*; Windows/WebView2 specifics; gotchas.
3. **Phase-3 ENGINE adversarial loop** (tier=medium): heterogeneous reviewers ≥2-agree, context-free Judge, active Synthesizer, convergence-until-dry.

**PLAN FROZEN.**
