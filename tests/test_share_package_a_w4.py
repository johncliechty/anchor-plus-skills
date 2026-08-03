"""Package A end-to-end — Wave 4 (canonical skills onboard).

Frozen plan: ``planning/share-canonical-onboard-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 4 — hermetic Package A onboard: registry, pointers, equality, no Anchor
service, honest hosts_registered; AGENTS body + Claude/Grok thin pointers;
vendor journal denylist regression; re-run idempotent / no dual Claude copy.

Hermetic: temp homes only; mock seats; no network; no paid CLI; no :8777.
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
import share_skills_root as ssr  # noqa: E402
import vendor_skills as vendor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]


def _make_bundle(root: Path, names=None) -> Path:
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in names or FAKE_SKILLS:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    return src


# ── Module surface (must import real Package A path) ─────────────────────────

def test_package_a_module_surface_importable():
    assert callable(sob.run_package_a_onboard)
    assert callable(sob.verify_package_a_acceptance)
    assert callable(sob.package_a_readiness_artifact)
    assert callable(sob.package_a_permissions)
    assert callable(sob.hosts_for_package)
    assert sob.hosts_for_package("A") == ["claude", "grok"]
    assert "anchor" not in sob.hosts_for_package("A")
    perms = sob.package_a_permissions()
    assert perms["scaffold_anchor"] is False
    assert perms["register_service"] is False
    assert perms["desktop_shortcut"] is False
    assert perms["install_skills"] is True


# ── Hermetic Package A E2E ───────────────────────────────────────────────────

def test_package_a_e2e_registry_pointers_equality_no_service(tmp_path):
    """Done when: registry, pointers, equality, no service, honest hosts."""
    home = tmp_path / "home-a"
    src = _make_bundle(tmp_path / "vendor-a")

    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        dialogue_complete=True,
    )

    assert report["package_id"] == "A"
    assert report["anchor_service_started"] is False
    assert report["register_service_attempted"] is False
    assert report["ok"] is True
    assert report["readiness"]["status"] == "ready"
    assert report["readiness"]["package_id"] == "A"

    # hosts_registered honesty: only hosts actually registered this run
    hosts = report["hosts_registered"]
    assert "claude" in hosts
    assert "grok" in hosts
    assert "anchor" not in hosts
    assert set(hosts) <= set(sob.hosts_for_package("A"))

    reg = ssr.load_registry(home)
    assert reg is not None
    assert reg["schema"] == "skills-root/v1"
    assert set(reg["hosts_registered"]) == set(hosts)
    assert "anchor" not in reg["hosts_registered"]

    skills_root = Path(reg["skills_root"])
    assert skills_root.is_dir()
    for name in FAKE_SKILLS:
        assert (skills_root / name / "SKILL.md").is_file()

    # Claude paths are pointers / not second product trees
    for name in FAKE_SKILLS:
        insp = ssr.inspect_claude_adapter(home, name, skills_root=skills_root)
        assert insp["dual_copy"] is False
        assert insp["pointer_only"] or insp["is_symlink"] or insp["is_pointer_marker"]

    proof = ssr.product_bytes_only_under_skills_root(
        home, skills_root=skills_root, portfolio=FAKE_SKILLS
    )
    assert proof["ok"] is True, proof["problems"]
    assert proof["claude_dual_copy_ids"] == []

    eq = ssr.portfolio_equality_oracle(home, portfolio=FAKE_SKILLS)
    assert eq["ok"] is True, eq["problems"]
    assert "claude" in eq["hosts_checked"]
    assert "grok" in eq["hosts_checked"]
    assert "anchor" not in eq["hosts_checked"]

    # No scaffold / desktop / service steps mutated
    for step in report["steps"]:
        if step["step"] == "scaffold_anchor":
            assert step["result"].get("skipped") is True
        if step["step"] == "desktop_shortcut":
            assert step["result"].get("skipped") is True

    # Acceptance helper agrees
    check = sob.verify_package_a_acceptance(home, report)
    assert check["ok"] is True, check["problems"]
    assert check["anchor_service_started"] is False


def test_package_a_agents_body_and_thin_host_pointers(tmp_path):
    """AGENTS body at governance/; Claude + Grok thin pointers only."""
    home = tmp_path / "home-agents"
    src = _make_bundle(tmp_path / "vendor-agents")

    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert report["ok"] is True

    gov_dir = home / home_cfg.GOVERNANCE_SUBDIR
    agents = gov_dir / "AGENTS.md"
    assert agents.is_file()
    body = agents.read_text(encoding="utf-8")
    assert gov.is_governance_installed(gov_dir)
    for marker in ("Status table", "10-minute", "UNIVERSAL SEATING LAW"):
        assert marker in body
    # Full body is substantial
    assert len(body) > 500

    # Governance pack also ships CLAUDE/GEMINI thin pointers in pack dir
    assert (gov_dir / "CLAUDE.md").is_file()

    # Host-native thin pointers (not full AGENTS body dual copy)
    claude_agents = home / ".claude" / "AGENTS.md"
    claude_md = home / ".claude" / "CLAUDE.md"
    grok_agents = home / ".grok" / "Agents.md"
    for path in (claude_agents, claude_md, grok_agents):
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert "pointer" in text.lower() or "AGENTS.md" in text
        assert len(text) < len(body) // 2
        # Must not embed the Status-table block wholesale
        assert text.count("Status table") <= 1


def test_package_a_readiness_artifact_on_disk(tmp_path):
    home = tmp_path / "home-ready"
    src = _make_bundle(tmp_path / "vendor-ready")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    stamp = sob.package_a_readiness_artifact(home)
    assert stamp is not None
    assert stamp["status"] == "ready"
    assert stamp["package_id"] == "A"
    assert stamp["governance_installed"] is True
    assert stamp["coding_seat_ok"] is True
    # feedback default off; not a readiness gate
    assert stamp["feedback_opt_in"] is False
    assert report["readiness"]["status"] == stamp["status"]

    path = home / home_cfg.GOVERNANCE_SUBDIR / ready.READINESS_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema"] == "share-readiness/v1"


def test_package_a_never_starts_anchor_service(tmp_path):
    """Package A must not start/register Anchor service (hard contract)."""
    home = tmp_path / "home-nosvc"
    src = _make_bundle(tmp_path / "vendor-nosvc")
    # Attempt to re-enable service perms — Package A must still refuse.
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        permissions={
            "scaffold_anchor": True,
            "register_service": True,
            "desktop_shortcut": True,
            "install_skills": True,
            "write_governance": True,
            "write_model_prefs": True,
        },
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert report["anchor_service_started"] is False
    assert report["register_service_attempted"] is False
    assert "anchor" not in (report.get("hosts_registered") or [])
    for step in report["steps"]:
        if step["step"] in ("scaffold_anchor", "desktop_shortcut"):
            assert step["result"].get("skipped") is True
    # No Anchor data dir scaffolded
    assert not (home / home_cfg.ANCHOR_SUBDIR).is_dir() or not any(
        (home / home_cfg.ANCHOR_SUBDIR).iterdir()
    )


def test_package_a_hosts_registered_honesty_no_untouched_hosts(tmp_path):
    """Falsify false GREEN: must not stamp hosts not actually registered."""
    home = tmp_path / "home-honest"
    src = _make_bundle(tmp_path / "vendor-honest")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        register_hosts_flag=False,
    )
    assert report["hosts_registered"] == []
    reg = ssr.load_registry(home)
    # Registry may exist from install with empty hosts_registered
    if reg is not None:
        assert reg["hosts_registered"] == [] or set(
            reg["hosts_registered"]
        ).issubset(set())

    # With register on, only successful hosts listed
    report2 = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        register_hosts_flag=True,
    )
    hosts = report2["hosts_registered"]
    adapter = ssr.load_adapter_state(home)
    for h in hosts:
        assert h in (adapter.get("hosts") or {})
        assert adapter["hosts"][h].get("registered") is True
    reg2 = ssr.load_registry(home)
    assert set(reg2["hosts_registered"]) == set(hosts)


def test_package_a_rerun_idempotent_no_dual_claude_copy(tmp_path):
    home = tmp_path / "home-idemp"
    src = _make_bundle(tmp_path / "vendor-idemp")
    r1 = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    r2 = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert r1["ok"] and r2["ok"]
    skipped = {
        x["name"] for x in (r2.get("skills") or {}).get("skipped") or []
    }
    assert skipped == set(FAKE_SKILLS) or skipped.issubset(set(FAKE_SKILLS))

    skills_root = ssr.resolve_skills_root(home)
    proof = ssr.product_bytes_only_under_skills_root(
        home, skills_root=skills_root, portfolio=FAKE_SKILLS
    )
    assert proof["ok"] is True, proof["problems"]
    assert proof["claude_dual_copy_ids"] == []

    # Claude farm still pointer-only after re-run
    for name in FAKE_SKILLS:
        insp = ssr.inspect_claude_adapter(home, name, skills_root=skills_root)
        assert insp["dual_copy"] is False


def test_package_a_refuses_re_onboard_when_dual_claude_copy(tmp_path):
    home = tmp_path / "home-dual"
    src = _make_bundle(tmp_path / "vendor-dual")
    sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    # Plant a full dual tree under Claude farm (not a pointer)
    dual = home / ".claude" / "skills" / "crucible"
    if dual.exists() or dual.is_symlink():
        if dual.is_symlink():
            dual.unlink()
        elif ssr._is_dir_junction(dual):
            # v1.1.3 chain: on a no-DevMode host the register lands a REAL
            # junction; rmtree refuses reparse points — rmdir removes the
            # junction itself without touching the target.
            import os as _os

            _os.rmdir(dual)
        else:
            import shutil

            shutil.rmtree(dual)
    dual.mkdir(parents=True)
    (dual / "SKILL.md").write_text("# DUAL COPY\n", encoding="utf-8")
    # No pointer marker → dual_copy
    insp = ssr.inspect_claude_adapter(
        home, "crucible", skills_root=ssr.resolve_skills_root(home)
    )
    assert insp["dual_copy"] is True

    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.run_package_a_onboard(
            home,
            skills_src=src,
            mock_seat_results={"claude": True},
            platform_name="Windows",
        )
    assert "dual" in ei.value.reason or "dual" in str(ei.value).lower()


def test_package_a_vendor_ship_still_denies_journal(tmp_path):
    """Regression: vendor/ship denylist still drops journal/ trees."""
    assert vendor._is_denied(Path("foreman") / "journal" / "runs" / "x.json")
    assert vendor._is_denied(Path("journal") / "note.md")
    assert vendor._is_denied(Path("crucible") / "journal")
    # Positive control: SKILL.md is not denied
    assert not vendor._is_denied(Path("foreman") / "SKILL.md")

    home = tmp_path / "home-deny"
    src = _make_bundle(tmp_path / "vendor-deny")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    check = sob.verify_package_a_acceptance(home, report)
    assert not any("denylist" in p for p in check["problems"]), check["problems"]


def test_package_a_zero_seat_not_ready(tmp_path):
    home = tmp_path / "home-zero"
    src = _make_bundle(tmp_path / "vendor-zero")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={
            "claude": False,
            "gemini": False,
            "grok": False,
        },
        platform_name="Windows",
        dialogue_complete=True,
    )
    assert report["readiness"]["status"] == "not-ready"
    assert report["exit_code"] != 0
    # Skills + registry still land; service still not started
    assert report["anchor_service_started"] is False
    assert ssr.load_registry(home) is not None


def test_package_a_silent_path_not_ready(tmp_path):
    home = tmp_path / "home-silent"
    src = _make_bundle(tmp_path / "vendor-silent")
    report = sob.run_package_a_onboard(
        home,
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        dialogue_complete=False,
    )
    assert report["readiness"]["status"] == "not-ready"
    assert report["silent"] is True or report["dialogue_complete"] is False
    stamp = sob.package_a_readiness_artifact(home)
    assert stamp is not None
    assert stamp["status"] != "ready"
