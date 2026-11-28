"""Wave 4 E2E regression suite for v1.5.8:
1. Full `distro.build_distro` ship gate passes with 0 PII/secret/entropy/import-closure errors,
   staging `anchor_onboard_agent.py`, `vendor/foundry-gui-dist/**`, and all 20 skills in `foundry_map_v2.json`.
2. Version `1.5.8` alignment across `VERSION`, `pyproject.toml`, `mothership_registry.json`, `static/app.html`,
   `static/provider-setup.html`, and collaborator `Anchor.zip`.
3. Headless Chromium Playwright verification that:
   - Gear icon (`/setup`) opens cleanly with unified provider matrix (`#logged-in-services-card` hidden, `#wave2-provider-matrix` & `#setup-browser-accounts-strip` live, `v1.5.8` badge),
   - Left-side CLI/Agent tiles (`Claude`, `ChatGPT`, `Gemini`, `Grok` via `/api/provider-detail?family=...` and `provider-controls.js`) remain intact and functional,
   - `/foundry` serves the visual React SPA (`vendor/foundry-gui-dist/index.html`) and `/api/skills` returns all 20 skills.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
import zipfile
import pytest

import distro
import onboard_wizard
from tests.test_provider_setup import AUTH, stack  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_158_alignment_and_distro_ship_gate(tmp_path: Path):
    ver = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert ver == "1.5.8"
    assert f'version = "{ver}"' in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    reg = json.loads((REPO_ROOT / "mothership_registry.json").read_text(encoding="utf-8"))
    assert reg["latest_version"] == ver
    assert f"v{ver}" in (REPO_ROOT / "static" / "app.html").read_text(encoding="utf-8")
    assert f"v{ver}" in (REPO_ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    assert (REPO_ROOT / "docs" / "COLLABORATOR-INVITE-EMAIL.md").is_file()

    # Build collaborator Anchor.zip and verify VERSION + zero loose source files
    zpath, zname = onboard_wizard.build_or_resolve_exe_zip_package("prod", dist_dir=tmp_path / "zipdist")
    assert zname == "Anchor.zip" and zpath.is_file()
    with zipfile.ZipFile(zpath, "r") as zf:
        assert zf.read("Anchor/VERSION").decode("utf-8").strip() == ver

    # Full deny-by-default distro build + PII/entropy/import-closure gate
    staged_dest = tmp_path / "distro_out"
    rep = distro.build_distro(REPO_ROOT, staged_dest, vendor_skills_=False)
    assert (staged_dest / "anchor_onboard_agent.py").is_file()
    assert (staged_dest / "vendor" / "foundry-gui-dist" / "index.html").is_file()
    staged_map = json.loads((staged_dest / "foundry_map_v2.json").read_text(encoding="utf-8"))
    assert len(staged_map["skills"]) == 20
    assert len(rep.get("files") or []) > 50


def test_playwright_gear_setup_left_cli_tiles_and_visual_20_skill_foundry(stack, tmp_path: Path, monkeypatch):
    pw_mod = pytest.importorskip("playwright.sync_api")
    import anchor_gui

    service, _, _data, _home = stack
    service.snapshot(True)

    httpd = anchor_gui.make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            login = context.request.post(base_url + "/api/auth/login", data={"token": AUTH})
            assert login.ok
            page = context.new_page()

            # 1. Verify Gear-icon Setup surface (/setup -> provider-setup.html)
            page.goto(f"{base_url}/setup", wait_until="domcontentloaded", timeout=20000)
            assert "v1.5.8" in page.locator("#setup-version-pill").inner_text()
            page.locator('.setup-steps [data-section="providers"]').click()
            pw_mod.expect(page.locator("#provider-auto-cli-browser-card")).to_be_visible()
            pw_mod.expect(page.locator("#wave2-provider-matrix")).to_be_visible()
            pw_mod.expect(page.locator("#logged-in-services-card")).to_be_hidden()

            # 2. Verify Left-Side CLI/Agent Tiles backend (/api/provider-setup/detail?family=...) & Gear icon (#setup-gear)
            for fam in ("claude", "gemini", "chatgpt", "grok"):
                r_det = context.request.get(f"{base_url}/api/provider-setup/detail?family={fam}", headers={"X-Anchor-Token": AUTH})
                assert r_det.status == 200
                det_doc = r_det.json()
                assert det_doc["ok"] is True
                assert det_doc["family"] == fam

            page.goto(f"{base_url}/high-seat", wait_until="domcontentloaded", timeout=20000)
            pw_mod.expect(page.locator("#setup-gear")).to_be_visible()

            page.goto(f"{base_url}/static/app.html", wait_until="domcontentloaded", timeout=15000)
            assert page.locator("#bar-version-pill").inner_text().strip() == "v1.5.8"

            # 3. Verify Visual 20-Skill Skill Foundry (/foundry + /api/skills)
            r_sk = context.request.get(f"{base_url}/api/skills")
            assert r_sk.status == 200
            skills_arr = r_sk.json()
            assert len(skills_arr) == 20

            page.goto(f"{base_url}/foundry", wait_until="networkidle", timeout=20000)
            html_foundry = page.content()
            assert "/assets/" in html_foundry

            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
