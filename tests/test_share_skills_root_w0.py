"""Canonical SKILLS_ROOT registry + portfolio equality (W0 / Foreman wave 1).

Frozen plan: ``planning/share-canonical-onboard-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 1 (skills-root registry + portfolio equality BEFORE install).

Hermetic: temp homes only; no network; no paid CLI; no live host config edits.
Exercises ``share_skills_root`` + schema wiring in ``share_contracts``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_contracts as sc  # noqa: E402
import share_home_config as home_cfg  # noqa: E402
import share_skills_root as ssr  # noqa: E402
import vendor_skills as vendor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Small pin for hermetic equality (vendor full suite is large; pin is explicit).
PIN = ["researchPrime", "crucible", "foreman", "gandalf"]


def _plant_skills(root: Path, names) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")


def _write_registry(home: Path, *, skills_root, mode="copy", hosts=None, pin=None):
    doc = ssr.build_skills_root_doc(
        skills_root,
        install_mode=mode,
        hosts_registered=list(hosts or []),
        portfolio_manifest=list(pin if pin is not None else PIN),
    )
    return ssr.write_registry(doc, home=home)


# ── Module / schema surface ──────────────────────────────────────────────────

def test_w0_module_surface_importable():
    assert ssr.SKILLS_ROOT_SCHEMA == "skills-root/v1"
    assert ssr.INSTALL_MODES == ("junction", "copy")
    assert set(ssr.HOST_IDS) == {"claude", "grok", "gemini", "anchor"}
    assert callable(ssr.validate_skills_root_doc)
    assert callable(ssr.write_registry)
    assert callable(ssr.resolve_skills_root)
    assert callable(ssr.register_host)
    assert callable(ssr.resolve_skill_journal_dir)
    assert callable(ssr.list_portfolio_ids_claude)
    assert callable(ssr.list_portfolio_ids_grok)
    assert callable(ssr.list_portfolio_ids_anchor)
    assert callable(ssr.portfolio_equality_oracle)
    assert callable(ssr.vendor_portfolio_ids)
    # Gemini promote-or-demote recorded (no half-registered).
    assert ssr.GEMINI_HOST_POLICY in ("promoted", "demoted")
    assert isinstance(ssr.GEMINI_EQUALITY_PARTICIPANT, bool)
    if ssr.GEMINI_HOST_POLICY == "promoted":
        assert ssr.GEMINI_EQUALITY_PARTICIPANT is True
        assert "gemini" in ssr.EQUALITY_HOSTS
        assert callable(ssr.list_portfolio_ids_gemini)
    else:
        assert ssr.GEMINI_EQUALITY_PARTICIPANT is False
        assert "gemini" not in ssr.EQUALITY_HOSTS


def test_skills_root_schema_wired_in_share_contracts():
    assert "skills_root" in sc.SCHEMA_FILES
    path = sc.SCHEMA_FILES["skills_root"]
    assert path.is_file()
    doc = sc.load_schema("skills_root")
    assert doc["properties"]["schema"]["const"] == "skills-root/v1"
    assert set(doc["properties"]["install_mode"]["enum"]) == {"junction", "copy"}
    assert sc.SKILLS_ROOT_INSTALL_MODES == ("junction", "copy")
    assert sc.SKILLS_ROOT_HOSTS == ("claude", "grok", "gemini", "anchor")


def test_vendor_portfolio_matches_declared_skill_names():
    assert ssr.vendor_portfolio_ids() == vendor.declared_skill_names()
    assert "researchPrime" in ssr.vendor_portfolio_ids()
    # Host-natives must not be in the pin.
    for native in ("docx", "design", "pptx", "help", "check-work"):
        assert native not in ssr.vendor_portfolio_ids()


# ── Registry validation ──────────────────────────────────────────────────────

def test_missing_required_fields_rejected_with_clear_problems():
    problems = ssr.validate_skills_root_doc({})
    for key in (
        "schema",
        "skills_root",
        "install_mode",
        "hosts_registered",
        "portfolio_manifest",
    ):
        assert any(p == "missing-key:%s" % key for p in problems), problems
    # share_contracts delegate
    assert sc.validate_skills_root_doc({}) == problems


def test_install_mode_enum_rejects_unknown():
    doc = ssr.build_skills_root_doc(
        "/tmp/skills",
        install_mode="copy",
        hosts_registered=["claude"],
        portfolio_manifest=PIN,
    )
    assert ssr.validate_skills_root_doc(doc) == []
    doc["install_mode"] = "symlink-farm"
    problems = ssr.validate_skills_root_doc(doc)
    assert any("install_mode-out-of-enum" in p for p in problems)


def test_hosts_registered_enum_and_unknown_keys():
    doc = ssr.build_skills_root_doc(
        "/tmp/skills",
        install_mode="junction",
        hosts_registered=["claude", "not-a-host"],
        portfolio_manifest=PIN,
    )
    problems = ssr.validate_skills_root_doc(doc)
    assert any("hosts_registered-out-of-enum" in p for p in problems)
    doc2 = ssr.build_skills_root_doc(
        "/tmp/skills",
        install_mode="copy",
        hosts_registered=["claude"],
        portfolio_manifest=PIN,
    )
    doc2["extra_field"] = True
    problems2 = ssr.validate_skills_root_doc(doc2)
    assert any("unknown-key:extra_field" in p for p in problems2)


def test_empty_portfolio_and_empty_skills_root_rejected():
    doc = ssr.build_skills_root_doc(
        "",
        install_mode="copy",
        hosts_registered=[],
        portfolio_manifest=[],
    )
    problems = ssr.validate_skills_root_doc(doc)
    assert any("skills_root-empty" in p for p in problems)
    assert any("portfolio_manifest-empty" in p for p in problems)


# ── Round-trip registry write ────────────────────────────────────────────────

def test_registry_round_trip_under_governance(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = home / home_cfg.SKILLS_SUBDIR
    _plant_skills(skills, PIN)

    path = _write_registry(
        home,
        skills_root=skills,
        mode="copy",
        hosts=["claude", "grok", "anchor"],
        pin=PIN,
    )
    assert path == ssr.skills_root_registry_path(home)
    assert path.is_file()
    # Under governance seam
    assert path.parent == ssr.governance_dir(home)
    assert home_cfg.GOVERNANCE_SUBDIR in path.parts

    loaded = ssr.load_registry(home)
    assert loaded is not None
    assert loaded["schema"] == "skills-root/v1"
    assert loaded["install_mode"] == "copy"
    assert loaded["portfolio_manifest"] == PIN
    assert loaded["hosts_registered"] == ["claude", "grok", "anchor"]
    assert Path(loaded["skills_root"]) == skills

    # resolve_skills_root reads registry
    assert ssr.resolve_skills_root(home) == skills

    # journal resolve law
    jdir = ssr.resolve_skill_journal_dir("foreman", home=home)
    assert jdir == skills / "foreman" / "journal"


def test_registry_round_trip_junction_author_mode(tmp_path):
    home = tmp_path / "author"
    home.mkdir()
    # Author-shaped root (path only; no real Foundry required for W0).
    skills = home / "foundry-skills"
    _plant_skills(skills, PIN)
    path = _write_registry(
        home,
        skills_root=skills,
        mode="junction",
        hosts=["claude", "grok", "gemini", "anchor"],
        pin=PIN,
    )
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["install_mode"] == "junction"
    assert ssr.validate_skills_root_doc(loaded) == []


def test_write_registry_refuses_invalid(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(ssr.SkillsRootError) as ei:
        ssr.write_registry({"schema": "skills-root/v1"}, home=home)
    assert "missing-key" in str(ei.value) or "invalid" in str(ei.value).lower()


# ── Adapter contract stubs ───────────────────────────────────────────────────

def test_register_host_stub_records_adapter_state(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    _plant_skills(skills, PIN)
    _write_registry(home, skills_root=skills, hosts=[], pin=PIN)

    claude = ssr.register_host("claude", skills, "copy", home=home)
    assert claude["registered"] is True
    assert claude["mechanism"] == "pointer_junction"
    assert claude["pointer_only"] is True
    assert claude["dual_copy_forbidden"] is True

    grok = ssr.register_host(
        "grok", skills, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    assert grok["skills_paths_include_skills_root"] is True
    assert str(skills) in grok["skills_paths"]

    anchor = ssr.register_host("anchor", skills, "copy", home=home)
    assert anchor["env_var"] == "ANCHOR_SKILLS_ROOT"

    reg = ssr.load_registry(home)
    assert set(reg["hosts_registered"]) >= {"claude", "grok", "anchor"}

    # Documented contracts present for all hosts
    for host in ssr.HOST_IDS:
        assert host in ssr.HOST_ADAPTER_CONTRACTS
        assert "mechanism" in ssr.HOST_ADAPTER_CONTRACTS[host]
        assert "target_description" in ssr.HOST_ADAPTER_CONTRACTS[host]


def test_register_host_rejects_unknown_host_and_mode(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    skills.mkdir()
    with pytest.raises(ssr.SkillsRootError):
        ssr.register_host("openclaw", skills, "copy", home=home)
    with pytest.raises(ssr.SkillsRootError):
        ssr.register_host("claude", skills, "dual-copy", home=home)


# ── Equality oracle: false GREEN + host-natives ──────────────────────────────

def test_equality_fails_when_grok_omits_skills_root_claude_compat_only(tmp_path):
    """GWT: Claude farm full + Grok paths omit SKILLS_ROOT → equality FAILS."""
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    _plant_skills(skills, PIN)
    _write_registry(
        home,
        skills_root=skills,
        hosts=["claude", "grok", "anchor"],
        pin=PIN,
    )

    # Claude + Anchor properly registered to SKILLS_ROOT.
    ssr.register_host("claude", skills, "copy", home=home)
    ssr.register_host("anchor", skills, "copy", home=home)
    # Grok "registered" but only via Claude-compat (paths omit SKILLS_ROOT).
    ssr.register_host(
        "grok",
        skills,
        "copy",
        home=home,
        skills_paths_include_skills_root=False,
    )

    claude_ids = ssr.list_portfolio_ids_claude(home, portfolio=PIN)
    grok_ids = ssr.list_portfolio_ids_grok(home, portfolio=PIN)
    anchor_ids = ssr.list_portfolio_ids_anchor(home, portfolio=PIN)

    assert set(claude_ids) == set(PIN)
    assert set(anchor_ids) == set(PIN)
    # Grok must NOT inherit Claude farm via compat for portfolio listing.
    assert grok_ids == []

    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is False
    assert any("host-portfolio-mismatch:grok" in p for p in report["problems"])
    assert any("grok-claude-compat-only" in p for p in report["problems"])


def test_equality_passes_when_all_hosts_point_at_skills_root(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    _plant_skills(skills, PIN)
    _write_registry(
        home,
        skills_root=skills,
        hosts=[],
        pin=PIN,
    )
    for host in ("claude", "grok", "anchor"):
        kwargs = {}
        if host == "grok":
            kwargs["skills_paths_include_skills_root"] = True
        ssr.register_host(host, skills, "copy", home=home, **kwargs)

    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is True, report["problems"]
    assert set(report["portfolio"]) == set(PIN)
    for host in ("claude", "grok", "anchor"):
        assert set(report["host_ids"][host]) == set(PIN)


def test_host_native_extras_ignored_equality_can_pass(tmp_path):
    """GWT: Grok bundled natives present → ignored; pin match still PASS."""
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    _plant_skills(skills, PIN)

    # Plant host-native extras outside SKILLS_ROOT (Grok bundled style).
    bundled = home / ".grok" / "bundled" / "skills"
    _plant_skills(bundled, ["docx", "design", "pptx"])
    # And a thin local under a fake Claude home that is NOT in pin.
    thin = home / ".claude" / "skills"
    _plant_skills(thin, ["help", "check-work"])

    _write_registry(home, skills_root=skills, hosts=[], pin=PIN)
    ssr.register_host("claude", skills, "copy", home=home)
    ssr.register_host(
        "grok", skills, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    ssr.register_host("anchor", skills, "copy", home=home)

    # Record natives on adapter state (must still be ignored by list_*).
    state = ssr.load_adapter_state(home)
    state["hosts"]["grok"]["host_native_ids"] = ["docx", "design", "pptx"]
    ssr.write_adapter_state(state, home=home)

    grok_ids = ssr.list_portfolio_ids_grok(home, portfolio=PIN)
    assert "docx" not in grok_ids
    assert "design" not in grok_ids
    assert set(grok_ids) == set(PIN)

    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is True, report["problems"]


def test_equality_fails_when_required_host_missing_pin_id(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    # Plant only a subset of the pin.
    _plant_skills(skills, ["foreman", "gandalf"])
    _write_registry(home, skills_root=skills, hosts=[], pin=PIN)
    ssr.register_host("claude", skills, "copy", home=home)
    ssr.register_host(
        "grok", skills, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    ssr.register_host("anchor", skills, "copy", home=home)

    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is False
    assert any("host-portfolio-mismatch" in p for p in report["problems"])


# ── Gemini promote decision recorded ─────────────────────────────────────────

def test_gemini_promote_or_demote_recorded_no_half_registered():
    assert ssr.GEMINI_HOST_POLICY in ("promoted", "demoted")
    contract = ssr.HOST_ADAPTER_CONTRACTS["gemini"]
    assert contract.get("policy") == ssr.GEMINI_HOST_POLICY
    if ssr.GEMINI_HOST_POLICY == "promoted":
        assert ssr.GEMINI_EQUALITY_PARTICIPANT is True
        assert "gemini" in ssr.EQUALITY_HOSTS
        assert "first-class" in contract["target_description"].lower() or (
            "SKILLS_ROOT" in contract["target_description"]
        )
    else:
        assert ssr.GEMINI_EQUALITY_PARTICIPANT is False
        assert "gemini" not in ssr.EQUALITY_HOSTS


def test_gemini_promoted_participates_when_registered(tmp_path):
    if ssr.GEMINI_HOST_POLICY != "promoted":
        pytest.skip("gemini demoted in this build")
    home = tmp_path / "home"
    home.mkdir()
    skills = home / "skills"
    _plant_skills(skills, PIN)
    _write_registry(home, skills_root=skills, hosts=[], pin=PIN)
    for host in ("claude", "grok", "anchor", "gemini"):
        kwargs = {}
        if host == "grok":
            kwargs["skills_paths_include_skills_root"] = True
        ssr.register_host(host, skills, "copy", home=home, **kwargs)

    gemini_ids = ssr.list_portfolio_ids_gemini(home, portfolio=PIN)
    assert set(gemini_ids) == set(PIN)
    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is True, report["problems"]
    assert "gemini" in report["hosts_checked"]


# ── Portfolio ref form ───────────────────────────────────────────────────────

def test_portfolio_manifest_vendor_pin_ref():
    ids = ssr.normalize_portfolio_manifest("vendor_pin")
    assert ids == vendor.declared_skill_names()
    doc = ssr.build_skills_root_doc(
        "/tmp/skills",
        install_mode="copy",
        hosts_registered=["claude"],
        portfolio_manifest="vendor_pin",
    )
    assert ssr.validate_skills_root_doc(doc) == []
