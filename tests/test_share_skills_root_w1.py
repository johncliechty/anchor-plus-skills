"""SKILLS_ROOT install + multi-host register + journal law (W1 / Foreman wave 2).

Frozen plan: ``planning/share-canonical-onboard-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 2.

Hermetic: temp homes only; no network; no paid CLI; never edits real
``C:\\Users\\...\\.claude`` / ``.grok`` — always ``tmp_path`` as home root.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onboard  # noqa: E402
import share_skill_journal as sjournal  # noqa: E402
import share_skills_root as ssr  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

PIN = ["researchPrime", "crucible", "foreman", "gandalf"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _plant_src(src: Path, names) -> Path:
    src.mkdir(parents=True, exist_ok=True)
    for name in names:
        d = src / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            "# %s\n\nbody for %s\n" % (name, name),
            encoding="utf-8",
        )
        (d / "notes.txt").write_text("notes\n", encoding="utf-8")
    return src


def _write_registry(home: Path, *, skills_root, mode="copy", hosts=None, pin=None):
    doc = ssr.build_skills_root_doc(
        skills_root,
        install_mode=mode,
        hosts_registered=list(hosts or []),
        portfolio_manifest=list(pin if pin is not None else PIN),
    )
    return ssr.write_registry(doc, home=home)


def _realpath(p) -> str:
    return os.path.realpath(str(p))


# ── 1. Recipient install: product bytes only under SKILLS_ROOT ───────────────

def test_install_skills_to_skills_root_product_bytes_once(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    src = _plant_src(tmp_path / "vendor_skills", PIN)

    report = ssr.install_skills_to_skills_root(
        home, src, mode="copy", portfolio=PIN
    )
    root = Path(report["skills_root"])
    assert root == home / "skills"
    assert set(x["name"] for x in report["installed"]) == set(PIN)

    # Product bytes under SKILLS_ROOT only.
    for sid in PIN:
        skill = root / sid
        assert skill.is_dir()
        assert (skill / "SKILL.md").is_file()
        assert (skill / onboard._OURS_MARKER).is_file()

    # No second full tree under home/.claude/skills before register.
    claude_farm = home / ".claude" / "skills"
    if claude_farm.exists():
        for sid in PIN:
            p = claude_farm / sid
            assert not (p / "SKILL.md").is_file() or p.is_symlink()

    proof = ssr.product_bytes_only_under_skills_root(home, portfolio=PIN)
    assert proof["ok"] is True, proof["problems"]


def test_install_does_not_write_claude_product_tree(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    src = _plant_src(tmp_path / "src", PIN)
    ssr.install_skills_to_skills_root(home, src, mode="copy", portfolio=PIN)

    claude = home / ".claude" / "skills"
    assert not claude.exists() or not any(
        (claude / sid / "SKILL.md").is_file() and not (claude / sid).is_symlink()
        for sid in PIN
    )


# ── 2. Claude adapter: junction/symlink/pointer only ─────────────────────────

def test_claude_register_creates_pointer_not_dual_copy(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    src = _plant_src(tmp_path / "src", PIN)
    report = ssr.install_skills_to_skills_root(home, src, mode="copy", portfolio=PIN)
    root = Path(report["skills_root"])

    entry = ssr.register_host("claude", root, "copy", home=home)
    assert entry["pointer_only"] is True
    assert entry["dual_copy_forbidden"] is True
    assert entry.get("pointers")
    assert set(entry["pointers"].keys()) == set(PIN)

    for sid in PIN:
        insp = ssr.inspect_claude_adapter(home, sid, skills_root=root)
        assert insp["exists"] is True
        assert insp["pointer_only"] is True, insp
        assert insp["dual_copy"] is False
        # v1.1.3 chain: symlink → junction → marked full copy (the retired
        # pointer-marker-only dir can no longer be created; a marker now
        # implies our tracked copy fallback).
        assert (insp["is_symlink"] or insp["is_junction"]
                or insp["is_pointer_marker"])
        # realpath of target under SKILLS_ROOT
        if insp["is_symlink"] or insp["is_junction"]:
            assert _realpath(insp["path"]).startswith(_realpath(root))
        else:
            assert insp["matches_skills_root"] is True

    proof = ssr.product_bytes_only_under_skills_root(home, portfolio=PIN)
    assert proof["ok"] is True, proof["problems"]
    assert proof["claude_dual_copy_ids"] == []


def test_claude_dual_copy_detected_when_full_tree_planted(tmp_path):
    """Falsify dual-copy: full SKILL.md under .claude without pointer → fail."""
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    # Evil second tree (full product bytes under Claude home).
    evil = home / ".claude" / "skills" / "foreman"
    evil.mkdir(parents=True)
    (evil / "SKILL.md").write_text("# dual\n", encoding="utf-8")

    insp = ssr.inspect_claude_adapter(home, "foreman", skills_root=root)
    assert insp["dual_copy"] is True
    assert insp["pointer_only"] is False

    proof = ssr.product_bytes_only_under_skills_root(home, portfolio=PIN)
    assert proof["ok"] is False
    assert any("claude-dual-copy:foreman" in p for p in proof["problems"])


# ── 3. Grok: [skills].paths includes SKILLS_ROOT under TEMP home ─────────────

def test_grok_register_writes_config_toml_under_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    entry = ssr.register_host(
        "grok", root, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    cfg = Path(entry["config_path_resolved"])
    assert cfg == home / ".grok" / "config.toml"
    assert cfg.is_file()
    text = cfg.read_text(encoding="utf-8")
    assert "[skills]" in text
    assert "paths" in text
    # Must not touch real user profile
    assert str(tmp_path) in str(cfg)

    paths = ssr._read_grok_skills_paths(home)
    assert any(_realpath(p) == _realpath(root) or p == str(root) for p in paths)
    assert entry["skills_paths_include_skills_root"] is True


def test_grok_omit_skills_root_equality_fails(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    ssr.register_host("claude", root, "copy", home=home)
    ssr.register_host("anchor", root, "copy", home=home)
    ssr.register_host(
        "grok", root, "copy", home=home,
        skills_paths_include_skills_root=False,
    )

    # Config exists but paths empty.
    paths = ssr._read_grok_skills_paths(home)
    assert paths == []

    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is False
    assert any("grok-claude-compat-only" in p for p in report["problems"])


# ── 4. Gemini: single skills.json → SKILLS_ROOT ──────────────────────────────

def test_gemini_register_single_skills_json_entry(tmp_path):
    if ssr.GEMINI_HOST_POLICY != "promoted":
        pytest.skip("gemini demoted")
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    entry = ssr.register_host("gemini", root, "copy", home=home)
    assert entry["skills_json_points_at_skills_root"] is True
    path = Path(entry["config_path_resolved"])
    assert path == home / ".gemini" / "config" / "skills.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert Path(doc["skills_root"]) == root
    # Single-entry doc — not a dual farm list of per-skill masters.
    assert "skills_root" in doc


# ── 5. Anchor: adapter state + env stamp + equality ──────────────────────────

def test_anchor_register_sets_env_stamp_and_equality(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    entry = ssr.register_host("anchor", root, "copy", home=home)
    assert entry["env_var"] == "ANCHOR_SKILLS_ROOT"
    assert entry["env_points_at_skills_root"] is True
    assert Path(entry["env_value"]) == root

    env_path = ssr.anchor_env_path(home)
    assert env_path.is_file()
    doc = json.loads(env_path.read_text(encoding="utf-8"))
    assert Path(doc["ANCHOR_SKILLS_ROOT"]) == root

    # Equality with all adapters pointing at SKILLS_ROOT.
    ssr.register_host("claude", root, "copy", home=home)
    ssr.register_host(
        "grok", root, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    report = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert report["ok"] is True, report["problems"]
    for host in ("claude", "grok", "anchor"):
        assert set(report["host_ids"][host]) == set(PIN)


def test_equality_passes_when_all_adapters_point_at_skills_root(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    src = _plant_src(tmp_path / "src", PIN)
    report = ssr.install_skills_to_skills_root(home, src, mode="copy", portfolio=PIN)
    root = Path(report["skills_root"])

    hosts = ["claude", "grok", "anchor"]
    if ssr.GEMINI_HOST_POLICY == "promoted":
        hosts.append("gemini")
    for host in hosts:
        kwargs = {}
        if host == "grok":
            kwargs["skills_paths_include_skills_root"] = True
        ssr.register_host(host, root, "copy", home=home, **kwargs)

    eq = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert eq["ok"] is True, eq["problems"]


# ── 6. Journal law: resolve_skill_journal_dir is THE path ────────────────────

def test_resolve_skill_journal_dir_is_under_skills_root(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    jdir = ssr.resolve_skill_journal_dir("foreman", home=home)
    assert jdir == root / "foreman" / "journal"

    runs = sjournal.records_dir_for_skill("foreman", home=home)
    assert runs == root / "foreman" / "journal" / "runs"


def test_share_skill_journal_prefers_resolve_when_home_given(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    _plant_src(root, PIN)
    _write_registry(home, skills_root=root, pin=PIN)

    # skill_dir deliberately elsewhere — home+skill_id must win.
    wrong = tmp_path / "other" / "foreman"
    wrong.mkdir(parents=True)

    path = sjournal.append_structured_run(
        wrong,
        skill_id="foreman",
        skill_version="1.0.0",
        outcome="worked",
        structural_failure_codes=["none"],
        home=home,
    )
    assert path.is_file()
    assert _realpath(path).startswith(_realpath(root))
    assert "other" not in path.parts or _realpath(path).startswith(_realpath(root))
    # Canonical layout
    assert path.parent.name == "runs"
    assert path.parent.parent.name == "journal"
    assert path.parent.parent.parent.name == "foreman"


# ── 7. Simulated multi-host journal write realpath under SKILLS_ROOT ─────────

def test_simulated_journal_write_realpath_under_skills_root(tmp_path):
    """Criterion 3: Claude / Grok / Anchor entry → journal realpath under root."""
    home = tmp_path / "home"
    home.mkdir()
    src = _plant_src(tmp_path / "src", PIN)
    report = ssr.install_skills_to_skills_root(home, src, mode="copy", portfolio=PIN)
    root = Path(report["skills_root"])

    ssr.register_host("claude", root, "copy", home=home)
    ssr.register_host(
        "grok", root, "copy", home=home,
        skills_paths_include_skills_root=True,
    )
    ssr.register_host("anchor", root, "copy", home=home)

    root_rp = _realpath(root)
    written = []

    # Claude adapter entry: resolve skill via pointer target, then journal.
    for sid in ("foreman",):
        insp = ssr.inspect_claude_adapter(home, sid, skills_root=root)
        assert insp["pointer_only"] is True
        # Write as if Claude ran the skill (adapter points at SKILLS_ROOT).
        p = sjournal.append_structured_run(
            skill_id=sid,
            skill_version="1.0.0",
            outcome="worked",
            home=home,
        )
        written.append(("claude", p))

    # Grok entry: config paths → SKILLS_ROOT; same resolve helper.
    p_grok = sjournal.append_structured_run(
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="friction",
        structural_failure_codes=["timeout"],
        home=home,
    )
    written.append(("grok", p_grok))

    # Anchor runner entry: ANCHOR_SKILLS_ROOT / registry → SKILLS_ROOT.
    p_anchor = sjournal.append_structured_run(
        skill_id="gandalf",
        skill_version="1.0.0",
        outcome="worked",
        home=home,
    )
    written.append(("anchor", p_anchor))

    for host, path in written:
        assert path.is_file(), host
        rp = _realpath(path)
        assert rp.startswith(root_rp), (host, rp, root_rp)
        # Never under a second tree (.claude farm as product copy).
        assert ".claude" not in Path(rp).parts or rp.startswith(root_rp)


def test_records_root_fallback_without_home_keeps_legacy(tmp_path):
    """Legacy skill_dir-only callers still write under skill_dir/journal/runs."""
    skill = tmp_path / "standalone" / "crucible"
    skill.mkdir(parents=True)
    path = sjournal.append_structured_run(
        skill,
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="worked",
    )
    assert path.is_file()
    assert path.parent == skill / "journal" / "runs"


# ── 8. Registry after install + multi-host register ──────────────────────────

def test_full_recipient_flow_install_register_equality_journal(tmp_path):
    home = tmp_path / "recipient"
    home.mkdir()
    src = _plant_src(tmp_path / "bundle", PIN)

    inst = ssr.install_skills_to_skills_root(home, src, mode="copy", portfolio=PIN)
    root = Path(inst["skills_root"])
    assert ssr.load_registry(home)["portfolio_manifest"] == PIN

    for host in ("claude", "grok", "gemini", "anchor"):
        if host == "gemini" and ssr.GEMINI_HOST_POLICY != "promoted":
            continue
        kwargs = {}
        if host == "grok":
            kwargs["skills_paths_include_skills_root"] = True
        ssr.register_host(host, root, "copy", home=home, **kwargs)

    reg = ssr.load_registry(home)
    assert "claude" in reg["hosts_registered"]
    assert "grok" in reg["hosts_registered"]
    assert "anchor" in reg["hosts_registered"]

    eq = ssr.portfolio_equality_oracle(home, portfolio=PIN)
    assert eq["ok"] is True, eq["problems"]

    proof = ssr.product_bytes_only_under_skills_root(home, portfolio=PIN)
    assert proof["ok"] is True, proof["problems"]

    # Journal via named helper
    jpath = sjournal.append_structured_run(
        skill_id="researchPrime",
        skill_version="0.1.0",
        outcome="worked",
        home=home,
    )
    assert _realpath(jpath).startswith(_realpath(root))


# ── 9. W0 surface still importable / apply_side_effects=False path ───────────

def test_register_host_apply_side_effects_false_adapter_state_only(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "skills"
    root.mkdir()
    _write_registry(home, skills_root=root, pin=PIN)

    entry = ssr.register_host(
        "grok", root, "copy", home=home,
        skills_paths_include_skills_root=True,
        apply_side_effects=False,
    )
    assert entry["skills_paths_include_skills_root"] is True
    # No live config.toml when side effects off.
    assert not (home / ".grok" / "config.toml").is_file()


def test_module_exports_w1_helpers():
    assert callable(ssr.install_skills_to_skills_root)
    assert callable(ssr.inspect_claude_adapter)
    assert callable(ssr.product_bytes_only_under_skills_root)
    assert callable(ssr.claude_skills_home)
    assert callable(ssr.grok_config_path)
    assert callable(ssr.gemini_skills_json_path)
    assert callable(sjournal.records_dir_for_skill)
    assert ssr.CLAUDE_POINTER_MARKER == ".anchor-skills-root-pointer"
