"""Package B dual gate — Wave 5 (canonical share onboard).

Frozen plan: ``planning/share-canonical-onboard-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 5 / MASTER-PLAN Amendment A1.

B_ready ⇔ HTTP local dashboard OK ∧ desktop shortcut with universal
``anchor.ico`` (IconLocation) ∧ shortcut URL == probed dashboard URL.

Hermetic: temp homes/desktops only; mock probe/shortcut/service; no network;
no paid CLI; no live :8777 requirement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_governance as gov  # noqa: E402
import share_home_config as home_cfg  # noqa: E402
import share_onboard as sob  # noqa: E402
import share_readiness as ready  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]
DASH = sob.DEFAULT_LOCAL_DASHBOARD_URL


def _make_bundle(root: Path, names=None) -> Path:
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in names or FAKE_SKILLS:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    return src


def _make_brand(root: Path) -> Path:
    brand = root / "vendor" / "brand"
    brand.mkdir(parents=True)
    (brand / sob.DEFAULT_SKILL_ICON_BASENAME).write_text(
        "<svg/>\n", encoding="utf-8"
    )
    for fname in (
        "crucible-icon.svg",
        "foreman-icon.svg",
        "gandalf-icon.jpg",
        "research-prime-icon.jpg",
    ):
        (brand / fname).write_bytes(b"icon")
    return brand


def _make_ico(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal non-empty bytes (not a real ICO; path existence is the contract).
    path.write_bytes(b"ICO\x00fake-anchor-icon")
    return path


def _branded_shortcut_fn(desktop_dir, url, icon_path=None, name=None, **_k):
    """Hermetic shortcut_fn: writes .lnk-contract with IconLocation=anchor.ico."""
    # Accept package_root / python_exe from production kwargs without failing.
    desk = Path(desktop_dir)
    desk.mkdir(parents=True, exist_ok=True)
    name = name or sob.DESKTOP_LNK_BASENAME
    path = desk / name
    ico = icon_path or str(desk / sob.ANCHOR_ICO_BASENAME)
    if icon_path and Path(icon_path).is_file():
        ico = str(Path(icon_path))
    elif not Path(ico).is_file():
        # ensure a local ico next to desktop for IconLocation
        local = desk / sob.ANCHOR_ICO_BASENAME
        if not local.is_file():
            _make_ico(local)
        ico = str(local)
    icon_loc = "%s,0" % ico
    path.write_text(
        "[AnchorDesktopShortcut]\nURL=%s\nIconLocation=%s\nFormat=lnk-contract\n"
        % (url, icon_loc),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "created": True,
        "skipped": False,
        "path": str(path),
        "url": url,
        "icon_location": icon_loc,
        "uses_anchor_ico": True,
        "branding_complete": True,
        "format": "lnk_contract",
        "elevation_required": False,
        "admin_required": False,
        "reason_codes": [],
    }


def _url_only_shortcut_fn(desktop_dir, url, icon_path=None, name=None, **_k):
    """Bare .url without anchor.ico — branding incomplete."""
    return sob.write_desktop_url_shortcut(
        desktop_dir=desktop_dir,
        url=url,
        platform_name="Windows",
    )


def _probe_ok(url):
    return True


def _probe_fail(url):
    return False


def _start_ok():
    return {"status": "registered", "started": True}


def _start_fg_fallback():
    return {"status": "foreground_fallback", "port": 9876}


def _start_fail():
    return {"status": "error", "error": "service unavailable"}


def _favicon_ok(url):
    return True


def _favicon_fail(url):
    return False


# ── Module surface ───────────────────────────────────────────────────────────

def test_package_b_module_surface_importable():
    assert callable(sob.run_package_b_onboard)
    assert callable(sob.complete_package_b_dual_gate)
    assert callable(sob.evaluate_package_b_dual_gate)
    assert callable(sob.probe_local_dashboard)
    assert callable(sob.check_favicon)
    assert callable(sob.check_skill_icons)
    assert callable(sob.write_desktop_lnk_shortcut)
    assert callable(sob.start_package_b_service)
    assert callable(sob.package_b_permissions)
    assert sob.hosts_for_package("B") == ["claude", "grok", "anchor"]
    perms = sob.package_b_permissions()
    assert perms["scaffold_anchor"] is True
    assert perms["register_service"] is True
    assert perms["desktop_shortcut"] is True


# ── Dual gate unit ───────────────────────────────────────────────────────────

def test_evaluate_b_ready_requires_probe_and_ico_and_url_match():
    url = DASH
    probe_ok = {"ok": True, "url": url, "reason_codes": []}
    desk_ok = {
        "created": True,
        "url": url,
        "uses_anchor_ico": True,
        "branding_complete": True,
        "format": "lnk",
        "icon_location": "anchor.ico,0",
    }
    gate = sob.evaluate_package_b_dual_gate(
        probe=probe_ok, desktop=desk_ok, dashboard_url=url
    )
    assert gate["b_ready"] is True
    assert gate["b_incomplete"] is False

    # probe fail
    gate2 = sob.evaluate_package_b_dual_gate(
        probe={"ok": False, "reason_codes": ["anchor_service_unavailable"]},
        desktop=desk_ok,
        dashboard_url=url,
    )
    assert gate2["b_ready"] is False
    assert "b_probe_failed" in gate2["reason_codes"] or (
        "anchor_service_unavailable" in gate2["reason_codes"]
    )

    # bare .url no ico
    desk_url = {
        "created": True,
        "url": url,
        "uses_anchor_ico": False,
        "branding_complete": False,
        "format": "url",
        "icon_location": None,
    }
    gate3 = sob.evaluate_package_b_dual_gate(
        probe=probe_ok, desktop=desk_url, dashboard_url=url
    )
    assert gate3["b_ready"] is False
    assert "b_branding_incomplete" in gate3["reason_codes"]

    # URL mismatch
    desk_bad_url = dict(desk_ok, url="http://localhost:9999")
    gate4 = sob.evaluate_package_b_dual_gate(
        probe=probe_ok, desktop=desk_bad_url, dashboard_url=url
    )
    assert gate4["b_ready"] is False
    assert "b_desktop_url_mismatch" in gate4["reason_codes"]


def test_foreground_fallback_alone_not_b_success():
    svc = sob.start_package_b_service(start_fn=_start_fg_fallback)
    assert svc["attempted"] is True
    assert svc["started"] is False
    assert svc["foreground_fallback"] is True
    assert "foreground_fallback_not_b_success" in svc["reason_codes"]

    gate = sob.evaluate_package_b_dual_gate(
        probe={"ok": False},
        desktop={
            "created": True,
            "url": DASH,
            "uses_anchor_ico": True,
            "branding_complete": True,
            "format": "lnk",
            "icon_location": "anchor.ico,0",
        },
        dashboard_url=DASH,
        service=svc,
    )
    assert gate["b_ready"] is False
    assert "foreground_fallback_not_b_success" in gate["reason_codes"]


# ── Success path ─────────────────────────────────────────────────────────────

def test_package_b_success_probe_ok_branded_shortcut(tmp_path):
    """Success: mock probe OK + shortcut with ico → B_ready true."""
    home = tmp_path / "home-b-ok"
    src = _make_bundle(tmp_path / "vendor-b-ok")
    brand = _make_brand(tmp_path / "brand-b-ok")
    desktop = tmp_path / "Desktop-b-ok"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        dashboard_url=DASH,
        probe_fn=_probe_ok,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_ok,
        favicon_get_fn=_favicon_ok,
        brand_dir=brand,
        dialogue_complete=True,
    )

    assert report["package_id"] == "B"
    assert report["b_ready"] is True
    assert report["package_b"]["b_ready"] is True
    assert report["package_b"]["b_incomplete"] is False
    assert report["ok"] is True
    assert report["readiness"]["status"] == "ready"
    assert report["exit_code"] == 0
    assert report["register_service_attempted"] is True
    assert report["anchor_service_started"] is True

    desk = report["package_b"]["desktop"]
    assert desk["created"] is True
    assert desk["uses_anchor_ico"] is True
    assert desk["branding_complete"] is True
    assert desk["url"] == DASH
    assert desk.get("icon_location_reported")
    assert "anchor.ico" in (desk.get("icon_location_reported") or "").lower()

    # Shortcut file on hermetic desktop
    paths = list(desktop.iterdir())
    assert any(p.suffix.lower() in (".lnk",) or "Anchor" in p.name for p in paths)

    # No author absolute path secrets in package_b report surface
    blob = json.dumps(report["package_b"], sort_keys=True)
    for bad in ("C:\\Users\\john", "C:/Users/john", "/Users/john", "C:\\dev\\Anchor"):
        assert bad not in blob
    assert "Users" not in blob or "Users" not in desk.get("path_reported", "")


# ── Fail: probe ──────────────────────────────────────────────────────────────

def test_package_b_probe_fail_not_ready(tmp_path):
    """Fail: probe fail → not B-complete / not-ready / non-zero exit."""
    home = tmp_path / "home-b-probe"
    src = _make_bundle(tmp_path / "vendor-b-probe")
    brand = _make_brand(tmp_path / "brand-b-probe")
    desktop = tmp_path / "Desktop-b-probe"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        dashboard_url=DASH,
        probe_fn=_probe_fail,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_ok,
        favicon_get_fn=_favicon_ok,
        brand_dir=brand,
        dialogue_complete=True,
    )

    assert report["b_ready"] is False
    assert report["package_b"]["b_incomplete"] is True
    assert report["ok"] is False
    assert report["readiness"]["status"] == "not-ready"
    assert report["exit_code"] != 0
    codes = report["package_b"]["reason_codes"]
    assert any(
        c in codes
        for c in ("b_probe_failed", "anchor_service_unavailable")
    )
    # Honest message — no silent success
    msg = (report["package_b"].get("message") or "").lower()
    assert "incomplete" in msg or "fail" in msg or "probe" in msg


def test_package_b_service_fail_and_probe_fail(tmp_path):
    home = tmp_path / "home-b-svc"
    src = _make_bundle(tmp_path / "vendor-b-svc")
    brand = _make_brand(tmp_path / "brand-b-svc")
    desktop = tmp_path / "Desktop-b-svc"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        probe_fn=_probe_fail,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_fail,
        favicon_get_fn=_favicon_fail,
        brand_dir=brand,
    )
    assert report["b_ready"] is False
    assert report["anchor_service_started"] is False
    assert report["exit_code"] != 0


def test_package_b_foreground_fallback_without_probe_not_ready(tmp_path):
    home = tmp_path / "home-b-fg"
    src = _make_bundle(tmp_path / "vendor-b-fg")
    brand = _make_brand(tmp_path / "brand-b-fg")
    desktop = tmp_path / "Desktop-b-fg"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        probe_fn=_probe_fail,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_fg_fallback,
        brand_dir=brand,
    )
    assert report["b_ready"] is False
    assert report["package_b"]["service"]["foreground_fallback"] is True
    assert report["anchor_service_started"] is False
    assert report["exit_code"] != 0


# ── Fail: branding ───────────────────────────────────────────────────────────

def test_package_b_probe_ok_no_ico_not_branding_complete(tmp_path):
    """Fail: probe OK but bare .url (no ico) → not B-complete for branding."""
    home = tmp_path / "home-b-brand"
    src = _make_bundle(tmp_path / "vendor-b-brand")
    brand = _make_brand(tmp_path / "brand-b-brand")
    desktop = tmp_path / "Desktop-b-brand"
    desktop.mkdir()

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        dashboard_url=DASH,
        probe_fn=_probe_ok,
        shortcut_fn=_url_only_shortcut_fn,
        start_service_fn=_start_ok,
        favicon_get_fn=_favicon_ok,
        brand_dir=brand,
    )

    assert report["b_ready"] is False
    assert report["package_b"]["b_incomplete"] is True
    assert "b_branding_incomplete" in report["package_b"]["reason_codes"]
    assert report["package_b"]["desktop"]["branding_complete"] is False
    assert report["readiness"]["status"] == "not-ready"
    assert report["exit_code"] != 0


# ── Package A never requires service ─────────────────────────────────────────

def test_package_a_path_never_requires_service(tmp_path):
    home = tmp_path / "home-a-nosvc"
    src = _make_bundle(tmp_path / "vendor-a-nosvc")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert report["package_id"] == "A"
    assert report["anchor_service_started"] is False
    assert report["register_service_attempted"] is False
    assert "b_ready" not in report
    assert report["readiness"]["status"] == "ready"
    assert report["exit_code"] == 0
    # A path does not call dual gate
    steps = {s["step"] for s in report.get("steps") or []}
    assert "package_b_dual_gate" not in steps


def test_package_a_via_share_onboard_still_skips_service(tmp_path):
    home = tmp_path / "home-a2"
    src = _make_bundle(tmp_path / "vendor-a2")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        permissions={
            "scaffold_anchor": True,
            "register_service": True,
            "desktop_shortcut": True,
        },
    )
    assert report["anchor_service_started"] is False
    assert report["register_service_attempted"] is False
    for step in report["steps"]:
        if step["step"] in ("scaffold_anchor", "desktop_shortcut"):
            assert step["result"].get("skipped") is True


# ── Interactive step 9 wires dual gate ───────────────────────────────────────

def test_interactive_package_b_step9_runs_dual_gate(tmp_path):
    home = tmp_path / "home-ix-b"
    src = _make_bundle(tmp_path / "vendor-ix-b")
    brand = _make_brand(tmp_path / "brand-ix-b")
    desktop = tmp_path / "Desktop-ix-b"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)
    lines = []

    def capture(*a, **k):
        lines.append(" ".join(str(x) for x in a))

    report = sob.run_interactive_onboard(
        home=home,
        package_id="B",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        skip_prompts=True,
        print_fn=capture,
        probe_fn=_probe_ok,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_ok,
        favicon_get_fn=_favicon_ok,
        brand_dir=brand,
        dashboard_url=DASH,
    )
    assert report["b_ready"] is True
    transcript = "\n".join(lines)
    assert "dual gate" in transcript.lower() or "B_ready" in transcript
    assert "Wave 4" not in transcript or "pending" not in transcript.lower()
    # No "still required" / pending wave handoff language
    assert "not completed in this wave" not in transcript


def test_interactive_package_b_probe_fail_honest(tmp_path):
    home = tmp_path / "home-ix-bfail"
    src = _make_bundle(tmp_path / "vendor-ix-bfail")
    brand = _make_brand(tmp_path / "brand-ix-bfail")
    desktop = tmp_path / "Desktop-ix-bfail"
    desktop.mkdir()
    lines = []

    def capture(*a, **k):
        lines.append(" ".join(str(x) for x in a))

    report = sob.run_interactive_onboard(
        home=home,
        package_id="B",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        skip_prompts=True,
        print_fn=capture,
        probe_fn=_probe_fail,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_fg_fallback,
        brand_dir=brand,
    )
    assert report["b_ready"] is False
    assert report["exit_code"] != 0
    transcript = "\n".join(lines).lower()
    assert "incomplete" in transcript or "b_ready: no" in transcript
    assert "foreground_fallback" in transcript or "not ready" in transcript


# ── Favicon + skill icons helpers ────────────────────────────────────────────

def test_check_favicon_injectable():
    ok = sob.check_favicon(DASH, get_fn=lambda u: True)
    assert ok["ok"] is True
    bad = sob.check_favicon(DASH, get_fn=lambda u: False)
    assert bad["ok"] is False


def test_check_skill_icons_with_default_fallback(tmp_path):
    brand = _make_brand(tmp_path / "brand-icons")
    result = sob.check_skill_icons(
        brand_dir=brand,
        portfolio=["crucible", "foreman", "gandalf", "researchPrime"],
    )
    assert result["ok"] is True
    assert result["default_fallback_documented"] is True
    for name in ("crucible", "foreman", "gandalf", "researchPrime"):
        assert result["resolved"][name]["ok"] is True


def test_probe_rejects_remote_url():
    r = sob.probe_local_dashboard("https://evil.example.com", probe_fn=lambda u: True)
    assert r["ok"] is False
    assert "non_local" in (r["reason_codes"][0] if r["reason_codes"] else "")


def test_no_author_secrets_in_b_outputs(tmp_path):
    home = tmp_path / "home-scrub"
    src = _make_bundle(tmp_path / "vendor-scrub")
    brand = _make_brand(tmp_path / "brand-scrub")
    desktop = tmp_path / "Desktop-scrub"
    desktop.mkdir()
    _make_ico(home / sob.ANCHOR_ICO_BASENAME)

    report = sob.run_package_b_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        desktop_dir=desktop,
        probe_fn=_probe_ok,
        shortcut_fn=_branded_shortcut_fn,
        start_service_fn=_start_ok,
        favicon_get_fn=_favicon_ok,
        brand_dir=brand,
    )
    # Dual-gate surface (package_b) must not leak author-machine path secrets.
    # (report["home"] is the hermetic tmp path — not asserted here.)
    pb = report.get("package_b") or {}
    text = json.dumps(pb, default=str)
    for secret in (
        "C:\\Users\\john",
        "C:/Users/john",
        "C:\\dev\\Anchor",
        "C:\\dev\\Skill Foundry",
        "John Liechty",
    ):
        assert secret not in text, "leaked %r in package_b" % secret
    # Report-facing path fields are basename / home-relative only.
    desk = pb.get("desktop") or {}
    for key in ("path_reported", "icon_location_reported"):
        val = desk.get(key) or ""
        assert "Users\\" not in val
        assert "Users/" not in val
        assert ":\\dev\\" not in val.lower()


def test_write_desktop_lnk_contract_without_powershell(tmp_path):
    """When ico present, write_desktop_lnk_shortcut brands without real COM."""
    desk = tmp_path / "Desk"
    desk.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    ico = _make_ico(home / sob.ANCHOR_ICO_BASENAME)
    result = sob.write_desktop_lnk_shortcut(
        desktop_dir=desk,
        url=DASH,
        icon_path=ico,
        platform_name="Windows",
        home=home,
        use_powershell=False,
    )
    assert result["created"] is True
    assert result["uses_anchor_ico"] is True
    assert result["branding_complete"] is True
    assert result["url"] == DASH
    assert Path(result["path"]).is_file()
    body = Path(result["path"]).read_text(encoding="utf-8")
    assert "IconLocation" in body
    assert "anchor.ico" in body.lower()
    assert DASH in body
