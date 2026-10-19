# Making Anchor an "App" — researchPrime Report

**Question:** Best-in-class way to turn Anchor (a Python-stdlib `http.server` dashboard at `http://localhost:8777`, run as the NSSM service `anchor`) into a first-class desktop **app** — chromeless window, one-click launch, Start-menu/taskbar identity, optional auto-start — **without breaking Anchor's locked invariants**.

**Skill:** researchPrime · **Date:** 2026-06-15 · **For:** J.C. Liechty
**Mode:** ENGINE-capable host (Node v26.1.0; import-spike `go:true`, all trio modules crossed). **Honest stamp on Phase-3:** the adversarial loop was driven by the harness spawning **real fresh-context sub-agents** (true isolation) — two heterogeneous reviewers (G3, ≥2-agree) + an orchestrator-as-Judge — *not* by `engine.mjs` calling an in-process `agent` callback (the Node process cannot invoke this host's sub-agent tool). The Node governed-round / tally / independence modules were available; the reviews themselves were sub-agent-driven. `cross_model: false`.
**ISOLATION:** main thread = approximated (derives from the frozen `00-PLAN.md`); the two evidence agents + the two adversarial reviewers = **real** (separate sub-agent contexts).
**Evidence ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED > REFUTED. Every load-bearing claim tags into `evidence-ledger.jsonl` (E#/F#).

---

## TL;DR (the decision)

**Do the two free things, in this order; treat them as complementary, not either/or:**

1. **B1 — Installable PWA** (real desktop identity). Serve a `manifest.webmanifest` + add `<link rel="manifest">`; commit a 192/512 (+maskable) PNG icon set. **Zero new runtime dependencies, breaks no invariant.** Gives a chromeless standalone window with its own Start-menu/taskbar entry and icon. `[CORROBORATED | E11,E13]`
2. **B2 — `msedge --app=` shortcut** (zero-code immediate fallback + the remote/Tailscale path). A one-line edit to the existing `AnchorDashboard.vbs`. Opens a chromeless window with **no install gesture and no server change**. `[CORROBORATED | E14]`

**The single prerequisite** is a one-time, *offline* icon build: stdlib has no SVG rasterizer, so generate 192×192 + 512×512 (+ a 512 maskable) PNGs from `vendor/brand/gwl-m-icon.svg` with any tool (PIL is already in the dev env), then **commit them as static bytes**. The runtime stays stdlib-only because committed PNGs are just bytes served by the existing static-asset route — `distro.py`'s scan only flags `import` statements in product code. `[OBSERVED | F2, E8]`

**Optional upgrade (only if you want a true native window + system tray and accept ONE declared optional dependency, exactly like `pywinpty`):** **B3 pywebview (+ B6 pystray)** behind a new `desktop` extra in `pyproject.toml` + a `distro.py` allowlist entry. WebView2 ships with Win11. Document it; don't default to it. `[CORROBORATED | E15]`

**Not recommended:** **B4 PyInstaller** (solves "no Python on the box" — a problem this deployment doesn't have; adds AV/SmartScreen/code-signing overhead) and **B5 Electron/Tauri** (toolchain weight grossly disproportionate to wrapping a localhost dashboard; if Anchor ever becomes a signed, auto-updating, many-machine product, prefer Tauri over Electron). `[CORROBORATED | E16,E17]`

---

## Why B1 + B2 win against the AXIS

The win-condition (`00-PLAN.md`): a genuine app experience **without** tripping any kill-criterion. Scored against the four kill-criteria:

| Kill-criterion | B1 PWA | B2 `--app` | Evidence |
|---|---|---|---|
| Breaks stdlib-only core | **No** — manifest is a served string + committed PNG bytes; no new `import` | **No** — no code change at all | E1, F2(b), E8 |
| Breaks markdown source-of-truth | No — static, read-only | No | F-invariant check |
| Re-introduces 8777 duplication | No — request-time route; the `SO_EXCLUSIVEADDRUSE` guard is bind-time | No — opens a URL, never a server | E3, E4 |
| Platform / CLI regression | No — static JSON/PNG, curl-accessible | No | E1 |

Both clear every gate. Every heavier branch (B3/B5/B6) trips kill-criterion #1 (new runtime dependency) and must buy a declared exception to be admissible.

---

## The findings that survived adversarial review (read these — the synthesis was *oversold* before they were folded in)

The first-pass synthesis ("B1, zero deps, breaks nothing, B2 strictly dominated") **survived at its core but was wrong in its framing.** Two independent reviewers (local-code + external-tech) forced these corrections:

- **F2 (MAJOR) — "zero-dependency icons" was false.** No 192/512 PNG exists (only 256 + 180), and stdlib can't rasterize SVG. Real cost = a one-time offline build step producing committed PNGs. `[OBSERVED | F2, E8]`
- **F3 (MAJOR) — B1 is a *window onto the live service*, not a self-launching app.** Auto-start is the NSSM service's job (already solved, separate); a PWA on a down service just shows a connection error. Don't conflate "one-click open the window" with "the app starts itself." `[OBSERVED | F3, E9]`
- **F4 (MAJOR) — B2 is NOT strictly dominated.** It's a genuine **identity-vs-effort trade-off**: B2 is a one-line edit to the existing `.vbs`, needs no server change / no install gesture, and is scriptable; B1 wins only on *desktop identity*. Hence: ship both. `[OBSERVED | F4, E4]`
- **E10 caveat (the biggest real-world trap) — localhost-secure-context is same-machine only.** PWA install + service workers work over plain `http://localhost`, but **NOT** when Anchor is reached as `http://PUTER:8777` / `gwl-server` / a Tailscale IP — those are non-secure origins and will not install. **Implication:** on the host itself, B1 installs cleanly; for *remote* access over Tailscale, B1 won't install — **B2 `--app` is the remote path** (it opens a chromeless window against any URL, it just won't be an installed PWA, and a SW wouldn't run — which is fine, Anchor needs none). `[CORROBORATED | E10]`
- **E13 caveat — Edge PWA install is tied to the Edge profile that created it** (won't launch under a different profile; unsupported under FSLogix/roaming/RDS). Irrelevant for the single fixed `PUTER` desktop, but state it. `[CORROBORATED | E13]`
- **E12 caveat — the manifest field list is *recommended*, not an immutable minimum** (Chrome is relaxing criteria); keep the fields anyway, and set a stable `id` (it stops same-app reinstall, though not per-profile dupes). `[CORROBORATED | E12]`
- **F1 (UNFOUNDED) — the SW-cleanup JS does NOT block install.** A manifest-only PWA uses neither SW registrations nor Cache Storage, so the cleanup block at `anchor_gui.py:105-141` is harmless to it. One forward-looking note: that code *aggressively* nukes any SW on every load, so Anchor is **locked into the no-SW design** — fine today, but a future offline-caching PWA would require changing it. `[REFUTED | F1, E6]`

**Convergence (honest):** the medium-tier loop ran one substantive adversarial round that produced 8 amendments; the two independent reviewers **agreed on the core verdict** (viable + invariant-safe) and **did not conflict** with each other (no conflicting-origin pair → no debate gate fired). All findings are addressable caveats, **none a BLOCKER**. With every finding folded into the recommendation and no contested claim remaining, the run is **dry**. `[CORROBORATED | F5]`

---

## Full branch comparison

| Approach | New runtime dep | Native-window quality | Distribution | Effort | Invariant-safe? |
|---|---|---|---|---|---|
| **B1 Installable PWA** | **None** | Good — true standalone window + real Start-menu/taskbar identity | Click "Install" in Edge (preinstalled) | **Low** (+ one-time icon build) | ✅ Yes |
| **B2 `--app=` shortcut** | **None** | Fair — chromeless, but groups under Edge's identity | One-line edit to existing `.vbs` | **Lowest** | ✅ Yes |
| **B3 pywebview** | pywebview (+clr) | Excellent — real native window + JS↔Py bridge + tray-capable | Run via Python / freeze | Medium | ❌ needs declared extra |
| **B4 PyInstaller/Nuitka** | None at runtime (build tooling) | N/A (packaging only) | Single `.exe` / `--onedir`; **must sign** | Med–High | ⚠️ build-time only; AV/signing pain |
| **B5 Electron / Tauri** | Electron(~80–150MB) / Tauri(<10MB)+Rust | Best-in-class | Signed MSI/NSIS + auto-update | **High** | ❌ heavy toolchain |
| **B6 pystray tray** | pystray + Pillow | N/A (launcher; reflects the NSSM service, Syncthing-style) | Auto-start at login | Low–Med | ❌ needs declared extra |

`[CORROBORATED | E15,E16,E17]` · Approaches needing **no new dependency: B1 and B2.** B4 adds no *runtime* dep but a build toolchain + signing. B3/B5/B6 add runtime weight that needs a declared exception.

---

## Recommended sequencing

1. **Ship B1 + B2 together** (small PR). Get the desktop identity (B1) and the zero-friction/remote launcher (B2) at once. Icons are the gating task — do them first.
2. **Stop there unless a real need appears.** Anchor already auto-starts (NSSM) and is browser-reachable; B1+B2 close the "feels like an app" gap at zero dependency cost.
3. **If you later want a non-browser native window + a status tray** (Anchor open without Edge, tray reflecting `Get-Service anchor`): adopt **B3 + B6** behind a `desktop` optional extra — same pattern as the `pywinpty` `terminal` extra, with a `distro.py` allowlist entry scoped to one new module (e.g. `desktop_shell.py`). Detect-and-install WebView2 for robustness (E15 caveat).
4. **Only consider B5 (Tauri)** if Anchor is ever productized for distribution to many machines with auto-update — explicitly out of scope today.

---

## What this is NOT (honesty boundary)

- This does **not** make Anchor self-launch or run offline. The server lifecycle is, and stays, the NSSM service's responsibility (E9, F3).
- B1 install is **local-machine only**; remote/Tailscale access uses B2 (E10).
- "Best-in-class" here is scoped to *this* codebase's hard stdlib-only constraint — which is exactly why the heavyweight industry baseline (Electron) loses to a manifest file.

See `02-executive.md` (one-screen summary) and `03-agent-impl.md` (concrete build steps for a Foreman/coding agent).
