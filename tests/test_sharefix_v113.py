"""v1.1.3 share-fix gates.

Covers the recovery release for the broken 1.1.x collaborator distribution
(friction-intake-2026-07-30): the import-closure build gate, the consumer
CLAUDE.md emission, the symlink→junction→copy skill-registration chain, the
honest onboard service story (no fake ports; a real server spawn), the
launcher's token wiring, the shared-install background-summary opt-out, and
the doctor's deterministic missing-module probe.

NOTE (scanner discipline): every literal token value in this file is < 8
chars ("tok9" etc.) so the shipped copy of this test can never trip the
auth-token-value pattern in distro's no-personal-data scan.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import distro
import doctor as doctor_mod
import launch_anchor_dashboard as lad
import onboard
import share_onboard as sob
import share_skills_root as ssr


# ── helpers ──────────────────────────────────────────────────────────────────

def _mk_tree(tmp_path, files, manifest_lines):
    root = tmp_path / "src"
    root.mkdir()
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (root / "dist_manifest.txt").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8")
    return root


def _mk_skill(tmp_path, name="demo"):
    target = tmp_path / "skillsroot" / name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    (target / "notes.md").write_text("payload\n", encoding="utf-8")
    return target


# ── import-closure gate (the 2026-07-30 incident class) ──────────────────────

def test_closure_catches_lazy_import_of_unstaged_module(tmp_path):
    """A staged file lazily importing an unstaged first-party module FAILS the
    build — exactly the reaper/freeze_state/zombie_hunter class (lazy imports
    the startup-import probe structurally cannot see)."""
    root = _mk_tree(tmp_path, {
        "a.py": "def go():\n    import b\n    return b\n",
        "b.py": "X = 1\n",
    }, ["a.py"])  # b.py exists in SOURCE, is NOT staged
    with pytest.raises(distro.ImportClosureError) as ei:
        distro.build_distro(root=root, output_dir=tmp_path / "out",
                            manifest_path=root / "dist_manifest.txt",
                            vendor_skills_=False)
    assert "'b'" in str(ei.value)
    assert "a.py" in str(ei.value)


def test_closure_allows_declared_optional(tmp_path):
    """update_transaction is the documented deliberate exclusion — a staged
    file importing it (guarded) builds fine without it being staged."""
    root = _mk_tree(tmp_path, {
        "a.py": ("try:\n    import update_transaction\n"
                 "except Exception:\n    pass\n"),
        "update_transaction.py": "X = 1\n",
    }, ["a.py"])
    report = distro.build_distro(root=root, output_dir=tmp_path / "out",
                                 manifest_path=root / "dist_manifest.txt",
                                 vendor_skills_=False)
    assert Path(report["staging"]).exists()


def test_closure_clean_when_import_staged(tmp_path):
    root = _mk_tree(tmp_path, {
        "a.py": "import b\n",
        "b.py": "X = 1\n",
    }, ["a.py", "b.py"])
    report = distro.build_distro(root=root, output_dir=tmp_path / "out",
                                 manifest_path=root / "dist_manifest.txt",
                                 vendor_skills_=False)
    assert "b.py" in report["files"]


def test_real_manifest_selection_is_import_closed_and_complete():
    """THE regression pin: the live manifest selection is import-closed, and
    every module + cold-start file the 1.1.x share was missing is selected."""
    sel = distro.select_shippable()
    pairs = [(rel, distro.REPO_ROOT / rel) for rel in sel]
    assert distro.scan_import_closure(pairs, root=distro.REPO_ROOT) == []
    for mod in ("proc_probe.py", "reaper.py", "reaper_arming.py",
                "freeze_state.py", "zombie_hunter.py", "tidy_idy_runner.py",
                "foundry_integrity.py", "foundry_safety.py",
                "foundry_skills.py", "foundry_acceptance.py",
                "verify_freeze_manifest.py", "orientation.py", "parity.py"):
        assert mod in sel, "incident module missing from selection: %s" % mod
    for extra in ("onboard.cmd", "onboard.ps1", "share_onboard.py",
                  "USER-ONBOARD.md", "launch_anchor_dashboard.py",
                  "VERSION", "CHANGELOG.md", "anchor.ico"):
        assert extra in sel, "cold-start file missing from selection: %s" % extra


def test_consumer_claude_md_emitted(tmp_path):
    root = _mk_tree(tmp_path, {"a.py": "X = 1\n"}, ["a.py"])
    report = distro.build_distro(root=root, output_dir=tmp_path / "out",
                                 manifest_path=root / "dist_manifest.txt",
                                 vendor_skills_=False)
    cm = Path(report["claude_md"])
    assert cm.name == "CLAUDE.md"
    text = cm.read_text(encoding="utf-8")
    # The thin consumer agent-notes: cheap probes first, no monolith reads,
    # paid multi-agent skills are not debug tools.
    assert "doctor.py" in text
    assert "anchor_gui.py" in text
    assert "launch_anchor_dashboard.py" in text


# ── skill registration: symlink → junction → copy (never a bare pointer) ─────

def test_link_mode_copy_is_loadable_and_marked(tmp_path, monkeypatch):
    target = _mk_skill(tmp_path)
    link = tmp_path / "farm" / "demo"
    monkeypatch.setenv(ssr.LINK_MODE_ENV, "copy")
    kind = ssr._try_link_skill(link, target)
    assert kind == "copy"
    assert (link / "SKILL.md").is_file()          # Claude can actually load it
    marker = link / ssr.CLAUDE_POINTER_MARKER
    assert marker.is_file()
    assert "mechanism: copy" in marker.read_text(encoding="utf-8")
    tgt = ssr.read_claude_pointer_target(link)
    assert tgt is not None
    assert os.path.realpath(str(tgt)) == os.path.realpath(str(target))
    # Idempotent: a re-run recognizes our copy.
    assert ssr._try_link_skill(link, target) == "copy"


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_link_mode_junction_stock_windows(tmp_path, monkeypatch):
    """The stock-Windows mechanism: no admin, no Developer Mode required."""
    target = _mk_skill(tmp_path)
    link = tmp_path / "farm" / "demo"
    monkeypatch.setenv(ssr.LINK_MODE_ENV, "junction")
    kind = ssr._try_link_skill(link, target)
    try:
        assert kind == "junction"
        assert ssr._is_dir_junction(link)
        assert (link / "SKILL.md").is_file()      # loads THROUGH the junction
        tgt = ssr.read_claude_pointer_target(link)
        assert tgt is not None
        assert os.path.realpath(str(tgt)) == os.path.realpath(str(target))
        assert ssr._try_link_skill(link, target) == "junction"  # idempotent
    finally:
        # rmtree refuses reparse points; remove the junction itself.
        if ssr._is_dir_junction(link):
            os.rmdir(link)


def test_legacy_pointer_only_dir_heals_to_loadable(tmp_path, monkeypatch):
    """The retired v1.1.x fallback (marker-only dir Claude cannot read) is
    UPGRADED in place on re-register — a broken install heals on re-onboard."""
    target = _mk_skill(tmp_path)
    link = tmp_path / "farm" / "demo"
    link.mkdir(parents=True)
    (link / ssr.CLAUDE_POINTER_MARKER).write_text(
        "../../skillsroot/demo\n", encoding="utf-8")
    assert not (link / "SKILL.md").is_file()      # the broken state
    monkeypatch.setenv(ssr.LINK_MODE_ENV, "copy")
    kind = ssr._try_link_skill(link, target)
    assert kind == "copy"
    assert (link / "SKILL.md").is_file()


def test_inspect_marked_copy_is_ours_not_dual(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = home / "skills"
    target = root / "demo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    link = ssr.claude_skills_home(home) / "demo"
    monkeypatch.setenv(ssr.LINK_MODE_ENV, "copy")
    assert ssr._try_link_skill(link, target) == "copy"
    insp = ssr.inspect_claude_adapter(home, "demo", skills_root=root)
    assert insp["is_copy"] is True
    assert insp["dual_copy"] is False
    assert insp["pointer_only"] is True
    assert insp["matches_skills_root"] is True


# ── onboard honesty ──────────────────────────────────────────────────────────

def test_register_service_reports_no_service_manager(monkeypatch):
    """No ANCHOR_SERVICE_CMD → an honest report. The old path imported
    anchor.registrar (impossible: anchor.py shadows the package) and printed a
    foreground-fallback port NOTHING listened on."""
    monkeypatch.delenv("ANCHOR_SERVICE_CMD", raising=False)
    out = onboard.register_service("tok9")
    assert out["status"] == "no_service_manager"
    assert "port" not in out
    assert "launch_anchor_dashboard.py" in out["hint"]


def test_install_terminal_extra_skip_seam(monkeypatch):
    monkeypatch.setenv("ANCHOR_ONBOARD_SKIP_PIP", "1")
    out = onboard.install_terminal_extra()
    assert out["status"] == "skipped"
    assert out["installed"] is False


def test_install_terminal_extra_non_windows(monkeypatch):
    if os.name == "nt":
        # Simulated via env: not patchable cheaply — assert the Windows probe
        # path instead (already-present short-circuits without touching pip).
        monkeypatch.delenv("ANCHOR_ONBOARD_SKIP_PIP", raising=False)
        out = onboard.install_terminal_extra(
            pip_argv=["definitely-not-a-real-pip-cmd"])
        # On a box WITH winpty this is already_present (no pip run); on a box
        # without it the bogus argv must yield an HONEST failure, never a
        # crash and never a fake success.
        assert out["status"] in ("already_present", "error", "failed")
        if out["status"] != "already_present":
            assert "pywinpty" in out["message"]
    else:
        out = onboard.install_terminal_extra()
        assert out["status"] == "skipped_non_windows"


# ── the real server spawn ────────────────────────────────────────────────────

def test_spawn_anchor_server_wires_token_and_summary_optout(tmp_path):
    (tmp_path / "anchor_gui.py").write_text("# stub\n", encoding="utf-8")
    seen = {}

    class _P:
        pid = 4242

    def fake_popen(argv, cwd=None, env=None, **kw):
        seen.update(argv=argv, cwd=cwd, env=env)
        return _P()

    out = sob.spawn_anchor_server(
        package_root=tmp_path, token="tok9", popen_fn=fake_popen)
    assert out["started"] is True
    assert out["token_wired"] is True
    assert seen["env"]["ANCHOR_TOKEN"] == "tok9"
    # Shared-install default: background summaries OPT-IN (never spend a
    # collaborator's subscription without an explicit action).
    assert seen["env"]["ANCHOR_PROACTIVE_SUMMARY"] == "0"
    assert seen["argv"][0] == __import__("sys").executable
    assert seen["argv"][1].endswith("anchor_gui.py")
    assert "--no-browser" in seen["argv"]
    assert seen["cwd"] == str(tmp_path)


def test_spawn_anchor_server_explicit_env_wins(tmp_path):
    (tmp_path / "anchor_gui.py").write_text("# stub\n", encoding="utf-8")
    seen = {}

    def fake_popen(argv, cwd=None, env=None, **kw):
        seen.update(env=env)
        return type("P", (), {"pid": 1})()

    sob.spawn_anchor_server(
        package_root=tmp_path, popen_fn=fake_popen,
        env={"ANCHOR_PROACTIVE_SUMMARY": "1"})
    # An explicit author-style env is respected — defaults never clobber.
    assert seen["env"]["ANCHOR_PROACTIVE_SUMMARY"] == "1"


def test_spawn_anchor_server_honest_when_gui_missing(tmp_path):
    out = sob.spawn_anchor_server(package_root=tmp_path)
    assert out["started"] is False
    assert out["status"] == "no_anchor_gui"


def test_start_package_b_service_production_path_spawns(monkeypatch):
    called = {}

    def fake_spawn(**kw):
        called.update(kw)
        return {"started": True, "status": "spawned", "token_wired": True}

    monkeypatch.setattr(sob, "spawn_anchor_server", fake_spawn)
    svc = sob.start_package_b_service(token="tok9")
    assert svc["attempted"] is True
    assert svc["started"] is True
    assert svc["foreground_fallback"] is False
    assert svc["raw"]["token_wired"] is True
    assert called["token"] == "tok9"


# ── launcher token hand-off ──────────────────────────────────────────────────

def test_launcher_starts_when_down_and_opens_with_token():
    calls = {"probe": 0}

    def probe(url):
        calls["probe"] += 1
        return calls["probe"] > 1  # down on first probe, up after start

    started = {}

    def start():
        started["yes"] = True
        return {"started": True, "status": "spawned"}

    opened = {}
    rep = lad.ensure_dashboard_running(
        probe_fn=probe, start_fn=start,
        open_fn=lambda u: opened.setdefault("url", u),
        token="tok9", retries=3, sleep_s=0)
    assert started.get("yes") is True
    assert rep["ok"] is True
    assert opened["url"].startswith(lad.DEFAULT_URL)
    assert "token=tok9" in opened["url"]


def test_launcher_already_up_no_start_no_token_leak():
    opened = {}

    def must_not_start():
        raise AssertionError("server already up — must not start")

    rep = lad.ensure_dashboard_running(
        probe_fn=lambda u: True, start_fn=must_not_start,
        open_fn=lambda u: opened.setdefault("url", u),
        token=None, retries=1, sleep_s=0)
    assert rep["already_running"] is True
    assert "token=" not in opened["url"]


# ── shared-install background-summary preference ─────────────────────────────

def test_proactive_summary_pref_explicit_off_only():
    import anchor_gui
    assert anchor_gui._proactive_summary_pref(None) is True
    assert anchor_gui._proactive_summary_pref("") is True
    assert anchor_gui._proactive_summary_pref("1") is True
    assert anchor_gui._proactive_summary_pref("on") is True
    for off in ("0", "false", "no", "off", " OFF "):
        assert anchor_gui._proactive_summary_pref(off) is False, off


# ── Package-B onboard mints the launcher token (v1.1.3 keystone) ─────────────

def _tiny_bundle(tmp_path):
    src = tmp_path / "bundle"
    (src / "demo").mkdir(parents=True)
    (src / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    return src


def test_share_onboard_b_mints_token_into_data_dir(tmp_path):
    """The documented cold start (`python -m share_onboard`, package B) must
    leave the token the launcher wires — the legacy onboard.py core was the
    only minter until v1.1.3 (found preparing the true-VM run)."""
    data = tmp_path / "data"
    env = {"ANCHOR_DATA_DIR": str(data)}  # hermetic redirect, no PYTEST key
    rep = sob.run_share_onboard(
        tmp_path / "home", package_id="B",
        skills_src=_tiny_bundle(tmp_path),
        mock_seat_results={"claude": True},
        desktop_dir=str(tmp_path / "Desktop"),
        dialogue_complete=True,
        env=env)
    step = next(s["result"] for s in rep["steps"]
                if s["step"] == "access_token")
    assert step.get("created") is True
    assert step.get("in_repo") is False
    tok_file = data / ".anchor" / "onboard-token"
    assert tok_file.is_file()
    assert tok_file.read_text(encoding="utf-8").strip()
    # And the launcher-side reader resolves the SAME token.
    assert sob.read_onboard_token(data) == tok_file.read_text(
        encoding="utf-8").strip()


def test_share_onboard_b_token_hermetic_guard(tmp_path):
    """A bare pytest context with no data-dir redirect must NOT write the
    real user profile — the step skips honestly."""
    env = {"PYTEST_CURRENT_TEST": "x"}  # no ANCHOR_DATA_DIR
    rep = sob.run_share_onboard(
        tmp_path / "home2", package_id="B",
        skills_src=_tiny_bundle(tmp_path),
        mock_seat_results={"claude": True},
        desktop_dir=str(tmp_path / "Desktop2"),
        dialogue_complete=True,
        env=env)
    step = next(s["result"] for s in rep["steps"]
                if s["step"] == "access_token")
    assert step.get("skipped") is True


# ── doctor: deterministic missing-module probe ───────────────────────────────

def test_doctor_finds_missing_module(tmp_path):
    (tmp_path / "a.py").write_text(
        "def go():\n    import zz_missing_mod_v113\n", encoding="utf-8")
    missing = doctor_mod.find_missing_modules(root=tmp_path)
    assert "zz_missing_mod_v113" in missing
    assert missing["zz_missing_mod_v113"] == ["a.py"]


def test_doctor_optional_absences_not_flagged(tmp_path):
    (tmp_path / "a.py").write_text(
        "try:\n    import update_transaction\nexcept Exception:\n    pass\n"
        "try:\n    from tools import write_tripwire\nexcept Exception:\n"
        "    pass\n", encoding="utf-8")
    assert doctor_mod.find_missing_modules(root=tmp_path) == {}


def test_doctor_author_tree_is_closed():
    """On the source tree every first-party import resolves — the probe is
    quiet exactly when the install is complete."""
    assert doctor_mod.find_missing_modules() == {}
