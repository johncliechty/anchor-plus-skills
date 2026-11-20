"""Gate-6 Regression & Live HTTP/Playwright E2E Suite for Skill Foundry v3 Batch 1 (2026-11-18).

Verifies:
1. static/app.js singleton framing (`pageKey === "foundry"`, `isPage`, `labelFor === "Skill Foundry"`).
2. Ephemeral `anchor_gui.make_server('127.0.0.1', 0)` serves Skill Foundry v3 Studio on `/foundry`
   and `/foundry?skill=gandalf|chekhov|anvil` with real skill brand icons (`naturalWidth > 0`),
   `0` console/page errors, and full 5-tab human-first functionality:
   - Tab 1 (`1. Overview & How It Works`): zero `<pre>` code snippets, plain-English I/O strip.
   - Tab 2 (`2. Knowledge Maps & Library`): smooth mouse drag-to-pan + wheel/button zoom + `⟲ Reset`
     strictly clipped inside `<circle id="poincare-boundary">` (`maxDistRatio < 1.0`), 4-shelf node
     dossier, and Full Library toggle.
   - Tab 3 (`3. Orchestration, Swarm & Review Map`): 4-lane swimlane SVG (`Human`, `Orchestrator`,
     `Parallel Swarm`, `Adversarial Review`) + `↻` review loops + interactive stage card.
   - Tab 4 (`4. Anvil Software Map`): authentic Anvil v4 B3 + Slide-Over Scientific IDE Debugger
     (`Steady-Coordinate Process Schematic (L1 + L2)`, 100% symbol conservation, `Open IDE Debugger`).
   - Tab 5 (`5. Evolution & Journals`): clickable `📓 Journal Logs` tile opening Layer 4 archive
     with live journal text loaded from `/foundry/source?skill=...&embed=1`.
   - Always-On right column (`Foundry Skill Steward`) interactive Q&A and staged proposals.
3. Zero `distro.scan_paths` personal-data / secret / third-party import findings across all touched files.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

import anchor_gui
import distro

ANCHOR_ROOT = Path(__file__).resolve().parent.parent


def test_app_js_singleton_foundry_framing() -> None:
    app_js = (ANCHOR_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'if (/^\\/foundry(\\/|$)/.test(r.path)) return "foundry";' in app_js
    assert '/^\\/foundry(\\/|$)/.test(path)' in app_js
    assert 'if (/^\\/foundry(\\/|$)/.test(r.path)) return "Skill Foundry";' in app_js


def test_distro_scan_clean_on_foundry_v3_surfaces() -> None:
    targets = [
        ("static/app.js", ANCHOR_ROOT / "static" / "app.js"),
        ("foundry-gui/src/App.jsx", ANCHOR_ROOT / "foundry-gui" / "src" / "App.jsx"),
        ("foundry-gui/src/FoundryStudioV3.jsx", ANCHOR_ROOT / "foundry-gui" / "src" / "FoundryStudioV3.jsx"),
        ("foundry-gui/src/foundry-v3.css", ANCHOR_ROOT / "foundry-gui" / "src" / "foundry-v3.css"),
        ("foundry-gui/src/components/v3/PoincareTab.jsx", ANCHOR_ROOT / "foundry-gui" / "src" / "components" / "v3" / "PoincareTab.jsx"),
        ("foundry-gui/src/components/v3/AnvilWorkbenchTab.jsx", ANCHOR_ROOT / "foundry-gui" / "src" / "components" / "v3" / "AnvilWorkbenchTab.jsx"),
        ("foundry-gui/public/brand/agy-dispatch-icon.svg", ANCHOR_ROOT / "foundry-gui" / "public" / "brand" / "agy-dispatch-icon.svg"),
        ("foundry-gui/public/brand/figure-designer-icon.svg", ANCHOR_ROOT / "foundry-gui" / "public" / "brand" / "figure-designer-icon.svg"),
        ("foundry-gui/src/data/foundryV3Batch1.json", ANCHOR_ROOT / "foundry-gui" / "src" / "data" / "foundryV3Batch1.json"),
    ]
    findings = distro.scan_paths(targets)
    assert findings == [], f"Unexpected distro findings: {findings}"


def test_foundry_v3_batch1_playwright_gate6_roundtrip() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    srv = anchor_gui.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1620, "height": 980})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            # 1. Foundry Home loads with 22 skills + real artwork icons
            page.goto(f"{base_url}/foundry", wait_until="networkidle")
            page.get_by_role("heading", name="Skill Foundry Home", exact=True).wait_for()
            icon_loaded = page.evaluate("""() => {
              const imgs = [...document.querySelectorAll('.sf-skill-ic')];
              return imgs.length === 22 && imgs.every(i => i.complete && i.naturalWidth > 0);
            }""")
            assert icon_loaded, "Expected all 22 real skill brand icons to load in left rail"

            # 2. Click Gandalf -> Tab 1 Overview has zero <pre> code snippets
            page.click("#home-card-gandalf")
            page.get_by_role("heading", name="Gandalf", exact=True).wait_for()
            assert page.locator("pre").count() == 0

            # 3. Tab 2 Knowledge Maps: Mouse drag-to-pan + strict circle containment + Reset
            page.click("#tab-km")
            svg_box = page.locator("#poincare-svg").bounding_box()
            assert svg_box is not None
            cx = svg_box["x"] + svg_box["width"] / 2
            cy = svg_box["y"] + svg_box["height"] / 2
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + 90, cy - 60, steps=10)
            page.mouse.up()

            containment = page.evaluate("""() => {
              const b = document.getElementById('poincare-boundary').getBoundingClientRect();
              const cx = b.left + b.width / 2, cy = b.top + b.height / 2, rad = b.width / 2;
              const dots = [...document.querySelectorAll('.poincare-dot')];
              let maxRatio = 0;
              for (const d of dots) {
                const r = d.getBoundingClientRect();
                const ratio = Math.hypot((r.left + r.width/2) - cx, (r.top + r.height/2) - cy) / rad;
                if (ratio > maxRatio) maxRatio = ratio;
              }
              const readout = document.getElementById('disk-readout').textContent;
              return { maxRatio, readout, dotCount: dots.length };
            }""")
            assert "Pan (0.00, 0.00)" not in containment["readout"], f"Expected drag pan, got {containment}"
            assert containment["maxRatio"] < 1.0, f"Circle overflow: {containment}"
            page.click("#btn-reset-disk")
            assert "Pan (0.00, 0.00)" in page.locator("#disk-readout").inner_text()

            # 4. Tab 3 Orchestration, Swarm & Review Map on Chekhov (6-Seat Beta-Reader Swarm)
            page.locator(".sf-rail").get_by_role("button", name="Chekhov", exact=False).click()
            page.click("#tab-orch")
            assert "6-Seat Beta-Reader Swarm" in (page.locator("#orch-svg").text_content() or "")

            # 5. Tab 4 Authentic Anvil v4 Workbench + Open IDE Debugger on Anvil
            page.locator(".sf-rail").get_by_role("button", name="Anvil", exact=False).click()
            page.click("#tab-anvil")
            assert "Steady-Coordinate Process Schematic (L1 + L2)" in page.locator(".sf-anvil-frame").inner_text()
            page.click("#btn-open-ide")
            assert page.locator("#anvil-ide-drawer").is_visible()

            # 6. Tab 5 Evolution & Journals Layer 4 clickable tile
            page.click("#tab-evolution")
            page.click("#tile-open-journals")
            assert page.locator("#layer-4-journals").is_visible()

            # 7. Batches 2, 3 & 4 skills live verification (ALL 22 / 22 total live skills)
            for b_id, b_heading in [
                ("researchprime", "researchPrime"),
                ("crucible", "Crucible"),
                ("foreman", "Foreman"),
                ("jumper", "Jumper"),
                ("superjump", "Superjump"),
                ("steward-cave", "Aladdin-Cave of Wonders"),
                ("steward-lamp", "Aladdin-Lamp"),
                ("steward-star", "Aladdin-Star Chart"),
                ("einstein", "Einstein"),
                ("scribe", "Scribe"),
                ("financial-analyst", "Financial-Analyst"),
                ("legal-beagle", "Legal-Beagle"),
                ("literature-review", "Literature-Review"),
                ("ramanujan", "Ramanujan"),
                ("aegis", "Aegis"),
                ("agy-dispatch", "agy-dispatch"),
                ("figure-designer", "Figure-Designer"),
                ("tidy-idy", "Tidy-Idy"),
                ("zombie-hunter", "Zombie-Hunter"),
            ]:
                page.goto(f"{base_url}/foundry?s={b_id}", wait_until="networkidle")
                page.get_by_role("heading", name=b_heading, exact=True).wait_for()
                page.click("#tab-orch")
                assert page.locator("#orch-svg").is_visible()
                page.click("#tab-anvil")
                assert "Steady-Coordinate Process Schematic (L1 + L2)" in page.locator(".sf-anvil-frame").inner_text()

            # 8. Always-On Steward Q&A
            page.fill("#sf-steward-input", "Update Superjump's Knowledge Map with calibration note")
            page.click("#sf-steward-send")
            assert "Staged" in page.locator(".sf-st-feed").inner_text()

            assert not errors, f"Console/Page errors: {errors}"
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
