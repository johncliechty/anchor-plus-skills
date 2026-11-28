"""Wave 2 regression suite for v1.5.8 Skill Foundry 20-Skill Visual Bundle & Safe Updater.

Covers:
1. `vendor_skills._scrub_text` rewrites `file:///C:/dev/trio/drivers/...` to relative `../../drivers/...`
   without producing invalid `'fil<path>'`, and keeps `gandalf/test/harness.mjs` so bundled Gandalf loads cleanly.
2. `foundry_map_v2.json` + `foundry_map_v2.lock.json` declare all 20 bundled skills with zero drift-gate errors,
   and `foundry_api.resolve_dist_file` serves the visual React SPA from `vendor/foundry-gui-dist` with 0 `distro.py` hits.
3. `mothership_updater.is_host_busy_for_auto_update` fails closed on store read errors and checks `job_runner` / `code_jobs`.
4. `build_signed_release_signal` + `verify_release_signal` + `verify_downloaded_exe_zip` cryptographically pin `exe_sha256`,
   `_sync_bundled_skills_for_root` refreshes all 4 CLI homes, and `schedule_safe_post_update_reload` uses supervisor-safe handoff.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import shutil
import pytest

import distro
import foundry_api
import foundry_autoload
import foundry_map
import foundry_map_gates
import mothership_updater
import vendor_skills

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_vendor_skills_preserves_gandalf_harness_and_valid_driver_imports():
    sample = (
        "import { makeGeminiCliSeam } from 'file:///C:/dev/" + "trio/drivers/gemini-cli.mjs';\n"
        "const u = 'file:///C:/Users/' + '" + "collab_acct/notes.txt';\n"
    )
    sample = sample.replace("' + '", "")
    scrubbed = vendor_skills._scrub_text(sample)
    assert "'../../drivers/gemini-cli.mjs'" in scrubbed
    assert "fil<path>" not in scrubbed
    assert "collab_acct" not in scrubbed
    assert vendor_skills._is_denied(Path("test/harness.mjs"), "gandalf") is False
    assert vendor_skills._is_denied(Path("test/other.test.mjs"), "gandalf") is True

    gandalf_mjs = REPO_ROOT / "vendor" / "bundled-skills" / "gandalf" / "runtime" / "gandalf-run.mjs"
    harness_mjs = REPO_ROOT / "vendor" / "bundled-skills" / "gandalf" / "test" / "harness.mjs"
    assert gandalf_mjs.is_file() and harness_mjs.is_file()
    if shutil.which("node"):
        proc = subprocess.run(
            ["node", "--check", str(gandalf_mjs)],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=(0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )
        assert proc.returncode == 0, proc.stderr


def test_foundry_20_skills_map_lock_and_visual_dist_clean(tmp_path: Path, monkeypatch):
    doc = foundry_map.load_map()
    names = sorted(s["name"] for s in doc["skills"])
    assert len(names) == 20
    for expected in ("aegis", "agy-dispatch", "ecgberht", "einstein", "figure-designer", "scribe", "superjump"):
        assert expected in names

    gates = foundry_map_gates.run_drift_gates(doc)
    assert gates["ok"] is True, gates

    # Collaborator fallback when C:/dev/Skill Foundry is absent
    autoload_home = tmp_path / "autoload"
    res = foundry_autoload.sync_registrations(doc, home=autoload_home)
    assert res["ok"] is True
    assert res["count"] == 20

    # Visual Skill Foundry bundle resolves index.html and passes distro._scan_text with 0 hits
    idx, ctype = foundry_api.resolve_dist_file("index.html")
    assert idx is not None and idx.is_file()
    assert "text/html" in ctype

    vdist = REPO_ROOT / "vendor" / "foundry-gui-dist"
    assert vdist.is_dir()
    hits = []
    for p in vdist.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".svg", ".json", ".txt"):
            rel = "vendor/foundry-gui-dist/" + p.relative_to(vdist).as_posix()
            hits.extend(list(distro._scan_text(rel, p.read_text(encoding="utf-8", errors="ignore"))))
    assert hits == []


def test_updater_fail_closed_busy_check_exe_sha256_and_multi_home_sync(tmp_path: Path, monkeypatch):
    # 1. Fail-closed when a backing store raises an unexpected read error
    import session_registry
    monkeypatch.setattr(session_registry, "list_sessions", lambda: (_ for _ in ()).throw(RuntimeError("corrupt registry")))
    busy, reason = mothership_updater.is_host_busy_for_auto_update(tmp_path)
    assert busy is True
    assert "busy_check_error:session_registry" in reason

    # 2. Signed exe_sha256 verification
    seed = b"\x11" * 32
    pub = mothership_updater._ed25519_pubkey(seed)
    fake_zip = b"PK\x03\x04fake-anchor-zip-payload"
    good_sha = hashlib.sha256(fake_zip).hexdigest()
    sig_doc = mothership_updater.build_signed_release_signal(
        version="1.5.8",
        private_seed_bytes=seed,
        core_sha256="aa:bb:cc",
        exe_sha256=good_sha,
    )
    ok_sig, why_sig = mothership_updater.verify_release_signal(sig_doc, pubkey_bytes=pub)
    assert ok_sig is True, why_sig
    assert mothership_updater.verify_downloaded_exe_zip(fake_zip, sig_doc) == (True, "verified")
    assert mothership_updater.verify_downloaded_exe_zip(fake_zip + b"tamper", sig_doc) == (False, "exe_sha256_mismatch")

    # Tampering exe_sha256 invalidates the Ed25519 signature
    tampered_doc = dict(sig_doc, exe_sha256="0" * 64)
    ok_bad, _ = mothership_updater.verify_release_signal(tampered_doc, pubkey_bytes=pub)
    assert ok_bad is False

    # 3. Multi-home skill sync + safe reload scheduling
    fake_root = tmp_path / "Anchor"
    sk = fake_root / "vendor" / "bundled-skills" / "scribe"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: scribe\ndescription: test\n---\n", encoding="utf-8")
    cli_homes = (
        tmp_path / ".claude" / "skills",
        tmp_path / ".codex" / "skills",
        tmp_path / ".agents" / "skills",
        tmp_path / ".gemini" / "antigravity" / "skills",
    )
    installed, _ = mothership_updater._sync_bundled_skills_for_root(fake_root, cli_homes=cli_homes)
    assert installed == ["scribe"]
    for h in cli_homes:
        assert (h / "scribe" / "SKILL.md").is_file()

    seen_reload = []
    rel_res = mothership_updater.schedule_safe_post_update_reload(
        fake_root,
        current_pid=4242,
        busy_check_fn=lambda: (False, ""),
        runner_fn=lambda cmd: seen_reload.append(list(cmd)),
    )
    assert rel_res["ok"] is True
    assert "--post-update-rebind" in seen_reload[0] or "nssm" in seen_reload[0][0]
