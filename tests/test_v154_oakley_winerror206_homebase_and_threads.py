"""Focused regression suite for Anchor v1.5.4 (Oakley [WinError 206], Cross-Tailnet Homebase
Outbound Heartbeat Updates, Self-Bootstrapping v1.5.1 Updater, Same-Day Email Thread UTC/Local
Triage + Full thread_messages + Cached Graph Attachments, and Deliverable-Link 404 Fixes).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import types
import urllib.error
import urllib.request

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anchor_gui  # noqa: E402
import comms_connector  # noqa: E402
import mothership_updater  # noqa: E402
import paths  # noqa: E402
from steward_cockpit import steward_campaign, steward_engine, steward_routes  # noqa: E402


class _QuietAnchorHandler(anchor_gui.AnchorHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return


@pytest.fixture
def live_hb_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _QuietAnchorHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


# ==============================================================================
# WAVE 1: Windows [WinError 206] Steward Spawn Overflow & Popen Error Logging
# ==============================================================================


def _setup_large_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data_dir = tmp_path / "anchor_data"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    monkeypatch.setattr(steward_engine, "STATE_FILE", data_dir / "steward-cockpit-state.json")

    repo = tmp_path / "Stat 331"
    (repo / ".ecgberht").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(".ecgberht/\n", encoding="utf-8")
    (repo / "ECGBERHT.md").write_text("# Stat 331 Course Pack\n" + ("Course context line.\n" * 200), encoding="utf-8")
    (repo / "roadmap.json").write_text(
        json.dumps({"goal": "Build Stat 331 Einstein packs", "roadmap_projection": [{"id": "w1", "name": "Wave 1", "status": "active"}]}),
        encoding="utf-8",
    )
    from steward_cockpit import conversation_history as ch
    for idx in range(20):
        ch.append_turn(
            str(repo),
            "john" if idx % 2 == 0 else "steward",
            f"Turn {idx} detailed Stat 331 statistical modeling discussion with quotes \"alpha\" and notes: " + ("X" * 1600),
            at=f"2026-11-22T16:{idx:02d}:00Z",
        )
    import poincare_state_map as _psm
    _psm.build_cockpit_poincare_map(str(repo), persist=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return data_dir, repo


def _mock_claude_policy(monkeypatch: pytest.MonkeyPatch):
    import anchor_settings
    import model_policy
    import provider_setup

    sel = {
        "family": "claude",
        "cli": "claude",
        "model": "opus",
        "effort": "high",
        "requested_policy": {"family": "claude", "model": "opus", "effort": "high"},
        "cli_args": ["--model", "opus", "--effort", "high"],
    }
    base_settings = anchor_settings.load_settings()
    base_settings.update({
        "default_cli": "claude",
        "coding_family": "claude",
        "review_family": "gemini",
        "settings_revision": 1,
        "provider_preferences": {"accounts": {}, "quality": {}},
    })
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: dict(base_settings))
    monkeypatch.setattr(anchor_settings, "read_settings_state", lambda: {"valid": True, "settings": dict(base_settings)})
    monkeypatch.setattr(
        provider_setup,
        "selected_for_launch",
        lambda settings, family, *a, **kw: {
            "id": f"{family}-default",
            "family": family,
            "mode": "subscription",
            "native_default": True,
        },
    )
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **kw: dict(sel))
    monkeypatch.setattr(model_policy, "cached_selection", lambda *a, **kw: dict(sel))
    monkeypatch.setattr(model_policy, "launch_args", lambda s: ["--model", "opus", "--effort", "high"])
    monkeypatch.setattr(provider_setup, "resolve_quality", lambda *a, **kw: dict(sel))
    monkeypatch.setattr(provider_setup, "require_capacity_choice", lambda *a, **kw: None)
    return base_settings


def test_wave1_claude_system_prompt_file_and_native_exe_and_git_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir, repo = _setup_large_effort(tmp_path, monkeypatch)
    base_settings = _mock_claude_policy(monkeypatch)
    monkeypatch.setattr(steward_engine.os, "name", "nt")
    steward_engine._CLAUDE_SYSTEM_PROMPT_FILE_CACHE.clear()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_exe = fake_bin / "claude.exe"
    fake_cmd = fake_bin / "claude.cmd"
    fake_exe.write_bytes(b"MZ")
    fake_cmd.write_text("@echo off\r\n", encoding="utf-8")

    def _which(name: str, **kwargs):
        if name == "claude.exe":
            return str(fake_exe)
        if name == "claude":
            return str(fake_cmd)
        return None

    monkeypatch.setattr(steward_engine.shutil, "which", _which)
    assert steward_engine._cli_cmd("claude") == [str(fake_exe)]

    help_calls: list[list[str]] = []

    real_run = steward_engine._REAL_SUBPROCESS_RUN

    def _fake_run(cmd, **kwargs):
        if cmd and str(cmd[0]).lower().startswith("git"):
            return real_run(cmd, **kwargs)
        help_calls.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="Usage: claude [options]\n  --append-system-prompt-file <path>\n", stderr="")

    monkeypatch.setattr(steward_engine.subprocess, "run", _fake_run)

    spawned_cmds: list[list[str]] = []

    class _FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.pid = 42424

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def _fake_popen(cmd, **kwargs):
        spawned_cmds.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(steward_engine.subprocess, "Popen", _fake_popen)

    eng = steward_engine.Engine(str(repo), fake=False, steward="Aladdin")
    monkeypatch.setattr(eng, "_desired_policy", lambda: (base_settings, "claude"))
    eng.cli = "claude"
    eng.steward = "Aladdin (" + ("Persona detail " * 900) + ")"
    ok, msg = eng._wake_locked(fresh=False, seed=None, send_initial=False)
    assert ok is True, msg
    assert len(help_calls) == 1
    # Cached on second check
    assert steward_engine._claude_supports_system_prompt_file([str(fake_exe)]) is True
    assert len(help_calls) == 1

    claude_cmds = [c for c in spawned_cmds if c and "claude" in str(c[0]).lower()]
    assert len(claude_cmds) == 1
    cmd = claude_cmds[0]
    assert "--append-system-prompt-file" in cmd
    assert "--append-system-prompt" not in cmd
    pf_idx = cmd.index("--append-system-prompt-file")
    prompt_path = Path(cmd[pf_idx + 1])
    assert prompt_path.is_file()
    assert prompt_path.parent == data_dir / ".anchor" / "steward-prompts"
    assert len(prompt_path.read_text(encoding="utf-8")) > 40000
    assert len(subprocess.list2cmdline(cmd)) < 4000

    # Target repository must remain 100% git-clean!
    monkeypatch.setattr(steward_engine.subprocess, "Popen", steward_engine._REAL_SUBPROCESS_POPEN)
    monkeypatch.setattr(steward_engine.subprocess, "run", real_run)
    git_st = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert git_st.strip() == ""
    assert not list(repo.rglob("*.system.md"))
    assert "/.anchor/steward-prompts/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_wave1_legacy_windows_fallback_under_24k_and_popen_winerror206_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir, repo = _setup_large_effort(tmp_path, monkeypatch)
    base_settings = _mock_claude_policy(monkeypatch)
    monkeypatch.setattr(steward_engine.os, "name", "nt")
    monkeypatch.setattr(steward_engine.shutil, "which", lambda c, **kw: "C:/fake/claude.exe" if c.startswith("claude") else None)
    monkeypatch.setattr(steward_engine, "_claude_supports_system_prompt_file", lambda base_cmd: False)

    spawned_cmds: list[list[str]] = []
    procs: list[object] = []

    class _FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.pid = 51515

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def _fake_popen(cmd, **kwargs):
        p = _FakeProc()
        if cmd and "claude" in str(cmd[0]).lower():
            spawned_cmds.append(list(cmd))
            procs.append(p)
        return p

    monkeypatch.setattr(steward_engine.subprocess, "Popen", _fake_popen)

    eng = steward_engine.Engine(str(repo), fake=False, steward="Aladdin")
    monkeypatch.setattr(eng, "_desired_policy", lambda: (base_settings, "claude"))
    eng.cli = "claude"
    eng.steward = "Aladdin \"" + ("quoted_persona " * 800) + "\""
    eng.queue = ["Please check the Einstein pack output."]
    steward_engine._update_state(eng.skey(), {"session_id": "11111111-2222-3333-4444-555555555555", "cli": "claude"})

    ok, why = eng._wake_locked(fresh=False, seed=None, send_initial=True)
    assert ok is True, why
    assert len(spawned_cmds) == 1
    cmd = spawned_cmds[0]
    assert "--append-system-prompt" in cmd
    sys_val = cmd[cmd.index("--append-system-prompt") + 1]
    assert len(sys_val) < 12000
    assert len(subprocess.list2cmdline(cmd)) <= 24000

    # Overflow was prepended once onto the first stdin stream-json message
    stdin_lines = [ln for ln in procs[-1].stdin.getvalue().splitlines() if ln.strip()]
    assert len(stdin_lines) == 1
    first_env = json.loads(stdin_lines[0])
    first_txt = first_env["message"]["content"][0]["text"]
    assert "steward system context overflow" in first_txt
    assert "Please check the Einstein pack output." in first_txt

    # Second message must NOT repeat the overflow
    eng.busy = False
    assert eng._send_locked("Follow-up turn question", origin="human") is True
    stdin_lines_2 = [ln for ln in procs[-1].stdin.getvalue().splitlines() if ln.strip()]
    assert len(stdin_lines_2) == 2
    second_txt = json.loads(stdin_lines_2[1])["message"]["content"][0]["text"]
    assert "steward system context overflow" not in second_txt

    # Now simulate Popen raising [WinError 206] and verify logs/errors.log captures structured metadata without raw prompt secrets
    secret_canary = "SUPER_SECRET_PROMPT_CANARY_DO_NOT_LOG_9911"
    eng2 = steward_engine.Engine(str(repo), fake=False, steward=secret_canary)

    def _boom_popen(cmd, **kwargs):
        raise OSError(22, "The filename or extension is too long", None, 206)

    monkeypatch.setattr(steward_engine.subprocess, "Popen", _boom_popen)
    ok2, err2 = eng2._wake_locked(fresh=True, seed=None, send_initial=False)
    assert ok2 is False
    err_log = data_dir / "logs" / "errors.log"
    assert err_log.is_file()
    logged = err_log.read_text(encoding="utf-8")
    assert "ERROR steward_engine.Popen failed:" in logged
    assert "cli=claude" in logged
    assert "cmd_chars=" in logged
    assert "argc=" in logged
    assert "206" in logged
    assert secret_canary not in logged


# ==============================================================================
# WAVES 2 & 3: v1.5.1 Paths Shims, CRLF Stash/Reload & Zero-Inbound Outbound Update
# ==============================================================================


def test_wave3_mothership_updater_runs_against_v151_paths_stub_and_stashes_crlf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws = tmp_path / "ws"
    root = ws / "Anchor"
    (root / ".git").mkdir(parents=True)
    (root / ".anchor").mkdir(parents=True)
    (root / "vendor" / "bundled-skills" / "ecgberht" / "scripts").mkdir(parents=True)
    (root / "vendor" / "bundled-skills" / "ecgberht" / "scripts" / "seal-chamber-bridge.mjs").write_text("// bridge\n", encoding="utf-8")
    (root / "VERSION").write_text("1.5.1\n", encoding="utf-8")
    (root / "paths.py").write_text("# v1.5.1 paths\n", encoding="utf-8")
    (root / "onboard.py").write_text("# v1.5.1 onboard\n", encoding="utf-8")
    (root / "mothership_updater.py").write_text("# v1.5.1 updater\n", encoding="utf-8")
    (root / ".anchor" / "user_profile.json").write_text(json.dumps({"display_name": "Merrill"}), encoding="utf-8")

    # Simulate v1.5.1 `paths` module lacking read_version, read_collaborator_display_name, resolve_ecgberht_root, atomic_write_text, safe_urlopen
    v151_paths_stub = types.SimpleNamespace(CODE_DIR=root)
    monkeypatch.setattr(mothership_updater, "paths", v151_paths_stub)

    vstat = mothership_updater.get_version_status(root)
    assert vstat["ok"] is True
    assert vstat["version"] == "1.5.1"
    assert vstat["collaborator_name"] == "Merrill"
    assert "ecgberht" in vstat["ecgberht_root"].lower()

    git_cmds: list[list[str]] = []

    def _fake_git_runner(cmd: list[str], cwd=None, timeout=120):
        git_cmds.append(list(cmd))
        if "status" in cmd and "--porcelain" in cmd:
            return types.SimpleNamespace(returncode=0, stdout=" M mothership_updater.py\n", stderr="")
        if "diff" in cmd and "--ignore-cr-at-eol" in cmd:
            # Pure core.autocrlf EOL noise -> exit code 0
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "pull" in cmd and "--ff-only" in cmd:
            (root / "VERSION").write_text("1.5.4\n", encoding="utf-8")
            (root / "paths.py").write_text("# v1.5.4 paths updated\n", encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="Updating 1.5.1..1.5.4\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mothership_updater.onboard, "install_skills", lambda **kw: {"installed": [{"name": "einstein"}], "skipped": []})
    pull_out = mothership_updater.pull_latest_update(anchor_root=root, runner_fn=_fake_git_runner, sync_skills=True)
    assert pull_out["ok"] is True
    assert pull_out["before_version"] == "1.5.1"
    assert pull_out["after_version"] == "1.5.4"
    assert pull_out["core_files_changed"] is True
    assert any("stash" in c and "anchor-auto-pull-crlf" in c for c in git_cmds)
    # Pure CRLF stash should NOT be popped back over clean pulled files
    assert not any("pop" in c for c in git_cmds)

    gitattrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("* text=auto eol=lf", "*.py text eol=lf", "*.js text eol=lf", "*.bat text eol=crlf", "*.ps1 text eol=crlf"):
        assert rule in gitattrs


def test_wave2_cross_tailnet_outbound_heartbeat_pulls_pending_update_zero_inbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_hb_server: str,
):
    hb_root = tmp_path / "homebase"
    hb_root.mkdir(parents=True)
    (hb_root / "VERSION").write_text("1.5.4\n", encoding="utf-8")

    collab_root = tmp_path / "oakley_collab" / "Anchor"
    collab_root.mkdir(parents=True)
    (collab_root / "VERSION").write_text("1.5.3\n", encoding="utf-8")

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(hb_root))
    monkeypatch.setenv("ANCHOR_TOKEN", "hb-secret-token-1234567890")
    monkeypatch.setenv("ANCHOR_HOMEBASE_URL", live_hb_server)

    # 1. Collaborator registers outbound using ANCHOR_HOMEBASE_URL override with NO inbound tailscale_url (port 8777 unexposed)
    reg_res = mothership_updater.register_with_homebase(
        owner="Merrill",
        hostname="oakley",
        tailscale_url="",
        tailscale_ip="",
        anchor_root=collab_root,
    )
    assert reg_res["ok"] is True
    assert reg_res["homebase_url"] == live_hb_server
    mid = reg_res["mothership_id"]

    # 2. Lead Homebase pushes v1.5.4 -> cannot reach oakley inbound, so queues pending_update bulletin on Homebase
    push_res = mothership_updater.push_update_to_motherships(
        target_id=mid,
        notes="Anchor v1.5.4 release",
        push_git=False,
        anchor_root=hb_root,
    )
    assert push_res["ok"] is True
    assert push_res["results"][0]["pushed_live"] is False
    assert push_res["results"][0]["queued_bulletin"] is True

    # 3. Collaborator runs idle outbound heartbeat (`events == []`, `heartbeat_even_if_empty=True`) -> receives pending_update & auto-pulls!
    pulled_targets: list[str] = []

    def _stub_collab_pull(*, anchor_root=None, target_version=None, **kwargs):
        pulled_targets.append(str(target_version))
        (Path(anchor_root) / "VERSION").write_text(f"{target_version}\n", encoding="utf-8")
        return {"ok": True, "before_version": "1.5.3", "after_version": str(target_version), "updated": True}

    monkeypatch.setattr(mothership_updater, "pull_latest_update", _stub_collab_pull)

    hb_sync = mothership_updater.sync_telemetry_to_homebase(
        anchor_root=collab_root,
        heartbeat_even_if_empty=True,
    )
    assert hb_sync["ok"] is True
    assert hb_sync["sent_count"] == 0
    assert hb_sync["heartbeat_sent"] is True
    assert pulled_targets == ["1.5.4"]
    assert hb_sync["auto_pull"]["after_version"] == "1.5.4"

    # Follow-up receipt cleared pending_update on Homebase and logged the journal receipt!
    hb_reg_after = mothership_updater.load_mothership_registry(hb_root)
    oakley_entry = next(m for m in hb_reg_after["motherships"] if m["id"] == mid)
    assert oakley_entry["installed_version"] == "1.5.4"
    assert oakley_entry["pending_update"] is None

    tel_events = mothership_updater.list_homebase_telemetry(mothership_id=mid, anchor_root=hb_root)
    assert any("Auto-applied Homebase update to v1.5.4" in ev["title"] for ev in tel_events["events"])


# ==============================================================================
# WAVE 4: Same-Day UTC/Local Thread Triage, 5-Message Hydration & Cached Attachments
# ==============================================================================


def test_wave4_same_day_utc_vs_local_triage_and_5_msg_thread_and_cached_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    data_dir = tmp_path / "comms_data"
    (data_dir / ".anchor").mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    # Simulate MST (UTC-7): 09:20 MST == 16:20Z, 10:28 MST == 17:28Z
    mst = timezone(timedelta(hours=-7))
    monkeypatch.setattr(comms_connector, "_LOCAL_NAIVE_TZ_OVERRIDE", mst)
    comms_connector._COMPARABLE_TS_MEMO.clear()
    comms_connector._LOCAL_TS_MEMO.clear()

    aid = "comms-01fd25fe"
    subj = "You've been given free access to this story from The Economist as a gift."
    conv_id = "AAQkAGI3YmRk-corey-agora-thread"

    comms_connector.save_comms_config({
        "accounts": [{
            "id": aid,
            "email": "faculty@example.org",
            "label": "PSU Outlook",
            "family": "outlook",
            "auth_mode": "oauth_token",
        }],
        "manual_logs": [],
    })

    headers = [
        {
            "uid": "msg-1-0401",
            "account_id": aid,
            "conversation_id": conv_id,
            "subject": subj,
            "from": "Corey Phelps <dean.phelps@example.org>",
            "sender_email": "dean.phelps@example.org",
            "to": "faculty@example.org, mish.velikov@example.org",
            "date": "2026-11-22 04:01",
            "snippet": "Thought you both would enjoy this Economist article.",
            "body": "Thought you both would enjoy this Economist article.",
            "is_read": True,
            "has_attachments": False,
        },
        {
            "uid": "msg-2-0758",
            "account_id": aid,
            "conversation_id": conv_id,
            "subject": "Re: " + subj,
            "from": "Mihail Velikov <mish.velikov@example.org>",
            "sender_email": "mish.velikov@example.org",
            "to": "dean.phelps@example.org, faculty@example.org",
            "date": "2026-11-22 07:58",
            "snippet": "Thanks Corey, very relevant to AGORA.",
            "body": "Thanks Corey, very relevant to AGORA.",
            "is_read": True,
            "has_attachments": False,
        },
        {
            "uid": "msg-3-0844",
            "account_id": aid,
            "conversation_id": conv_id,
            "subject": "Re: " + subj,
            "from": "Corey Phelps <dean.phelps@example.org>",
            "sender_email": "dean.phelps@example.org",
            "to": "mish.velikov@example.org, faculty@example.org",
            "date": "2026-11-22 08:44",
            "snippet": "Agreed — let's connect this to participant recruitment.",
            "body": "Agreed — let's connect this to participant recruitment.",
            "is_read": True,
            "has_attachments": False,
        },
        {
            "uid": "msg-4-0848",
            "account_id": aid,
            "conversation_id": conv_id,
            "subject": "Re: " + subj,
            "from": "Mihail Velikov <mish.velikov@example.org>",
            "sender_email": "mish.velikov@example.org",
            "to": "dean.phelps@example.org, faculty@example.org",
            "date": "2026-11-22 08:48",
            "snippet": "Sounds great, looking forward to your draft.",
            "body": "Sounds great, looking forward to your draft.",
            "is_read": True,
            "has_attachments": False,
        },
        {
            "uid": "msg-5-1028",
            "account_id": aid,
            "conversation_id": conv_id,
            "subject": "Re: " + subj,
            "from": "Corey Phelps <dean.phelps@example.org>",
            "sender_email": "dean.phelps@example.org",
            "to": "faculty@example.org, mish.velikov@example.org",
            "date": "2026-11-22 10:28",
            "snippet": "Please review the attached AGORA marketing plan from my flight.",
            "body": "Please review the attached AGORA marketing plan from my flight.",
            "is_read": False,
            "has_attachments": True,
        },
    ]
    (data_dir / ".anchor" / "comms-sync.json").write_text(
        json.dumps({"email_headers": headers, "sent_email_headers": []}),
        encoding="utf-8",
    )

    # John marked msg-1 Seen & Important at 09:20 MST (16:20Z)
    prefs = {
        "upgraded_senders": ["dean.phelps@example.org"],
        "seen_opened_uids": ["msg-1-0401"],
        "acted_upon_emails": {
            f"{aid}:msg-1-0401": {
                "uid": "msg-1-0401",
                "account_id": aid,
                "subject": subj,
                "norm_subject": comms_connector._norm_email_subject(subj),
                "from": "Corey Phelps",
                "sender_email": "dean.phelps@example.org",
                "date": "2026-11-22 04:01",
                "at_utc": "2026-11-22T16:20:00Z",
                "status": "⭐ Seen · Important",
                "tone": "amber",
            }
        },
    }

    imp, oth = comms_connector.classify_inbox_emails(headers, prefs=prefs, sent_headers=[])
    assert len(imp) == 1, f"Unread 10:28 MST (17:28Z) reply must remain in important_emails, got imp={imp!r}, oth={oth!r}"
    card = imp[0]
    assert card["uid"] == "msg-5-1028"
    assert card["acted_upon"] is False
    assert card["thread_count"] == 5

    slim = comms_connector._slim_email_row(card)
    assert "thread_messages" not in slim
    assert slim["latest_uid"] == "msg-5-1028"
    assert slim["thread_uids"][0] == "msg-5-1028"
    assert len(slim["thread_uids"]) == 5

    # Pre-cache msg-5 body WITHOUT attachments (simulating background body pre-cache with attachments: None)
    comms_connector.email_body_cache_put(aid, "msg-5-1028", {
        "subject": "Re: " + subj,
        "from": "Corey Phelps <dean.phelps@example.org>",
        "to": "faculty@example.org, mish.velikov@example.org",
        "date": "2026-11-22 10:28",
        "body": "Please review the attached AGORA marketing plan from my flight.",
        "attachments": None,
    })

    monkeypatch.setattr(comms_connector, "get_account_secret", lambda _aid: "fake-oauth-access-token")
    monkeypatch.setattr(comms_connector, "_get_valid_oauth_access_token", lambda *a, **kw: "fake-oauth-access-token")

    graph_calls: list[str] = []

    class _FakeGraphResp:
        def __init__(self, doc: dict):
            self._raw = json.dumps(doc).encode("utf-8")
            self.status = 200

        def read(self, n=-1):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(req, timeout=6.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        graph_calls.append(url)
        if "/attachments" in url:
            return _FakeGraphResp({
                "value": [{
                    "id": "att-agora-docx",
                    "name": "AGORA Research Arena — Participant Recruitment Marketing Plan.docx",
                    "size": 48210,
                    "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "isInline": False,
                }]
            })
        return _FakeGraphResp({
            "id": "msg-5-1028",
            "subject": "Re: " + subj,
            "from": {"emailAddress": {"name": "Corey Phelps", "address": "dean.phelps@example.org"}},
            "toRecipients": [{"emailAddress": {"name": "Faculty Lead", "address": "faculty@example.org"}}],
            "ccRecipients": [],
            "receivedDateTime": "2026-11-22T17:28:00Z",
            "body": {"contentType": "text", "content": "Please review the attached AGORA marketing plan from my flight."},
            "hasAttachments": True,
        })

    monkeypatch.setattr(paths, "safe_urlopen", _fake_urlopen)

    read_res = comms_connector.read_email_message({"account_id": aid, "uid": "msg-5-1028"})
    assert read_res["ok"] is True
    assert any("/attachments" in u for u in graph_calls), "has_attachments=True must bypass attachments=None cache!"
    assert len(read_res["attachments"]) == 1
    assert read_res["attachments"][0]["filename"] == "AGORA Research Arena — Participant Recruitment Marketing Plan.docx"
    assert read_res["thread_count"] == 5
    assert [m["uid"] for m in read_res["thread_messages"]] == [
        "msg-5-1028",
        "msg-4-0848",
        "msg-3-0844",
        "msg-2-0758",
        "msg-1-0401",
    ]
    assert read_res["thread_messages"][0]["is_current"] is True

    # Subsequent read hits fast local cache (0 extra Graph calls) and STILL returns attachments + all 5 thread_messages!
    calls_before = len(graph_calls)
    read_cached = comms_connector.read_email_message({"account_id": aid, "uid": "msg-5-1028"})
    assert len(graph_calls) == calls_before
    assert read_cached.get("cache") == "local"
    assert len(read_cached["attachments"]) == 1
    assert read_cached["thread_count"] == 5
    assert [m["uid"] for m in read_cached["thread_messages"]][0] == "msg-5-1028"


# ==============================================================================
# WAVE 5: Cross-Repo md.js file:/// Guard, Multi-Path DELIVERABLES & Subfolders
# ==============================================================================


def test_wave5_multipath_where_cell_custom_subfolder_and_cross_repo_md_js(tmp_path: Path):
    effort = tmp_path / "Campaign" / "Cave of Wonders"
    sub_plan = effort / "anchor-v154-oakley-plan-2026-11-22"
    sub_custom = effort / "custom-research-pack-2026-11-22"
    dot_anchor = effort / ".anchor"
    sub_plan.mkdir(parents=True)
    sub_custom.mkdir(parents=True)
    dot_anchor.mkdir(parents=True)

    (sub_plan / "Anchor-v154-Plan.pdf").write_bytes(b"%PDF-1.4\n%test\n")
    (sub_plan / "VS-CODE-PROMPT-ANCHOR-V154.md").write_text("# Anchor v1.5.4 Prompt\nWave details.\n", encoding="utf-8")
    (sub_custom / "UNLISTED-SUBFOLDER-NOTE.md").write_text("# Subfolder Note\nContained inside effort.\n", encoding="utf-8")
    (dot_anchor / "HIDDEN-INTERNAL.md").write_text("internal state\n", encoding="utf-8")

    (effort / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n"
        "| --- | --- | --- | --- |\n"
        "| START HERE - FOR REVIEW: Anchor v1.5.4 Plan & Prompt | "
        "`anchor-v154-oakley-plan-2026-11-22/Anchor-v154-Plan.pdf` · "
        "`anchor-v154-oakley-plan-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md` | 2026-11-22 | w1 |\n",
        encoding="utf-8",
    )

    parsed = steward_campaign._read_deliverables(str(effort))
    row = parsed["items"][0]
    assert row["path"] == "anchor-v154-oakley-plan-2026-11-22/Anchor-v154-Plan.pdf"
    assert "anchor-v154-oakley-plan-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md" in row["companion_paths"]

    # 1. Secondary backticked file in multi-path Where cell resolves via deliverable-file even when queried by wrong/bare path
    body_comp, code_comp = steward_routes.handle_get(
        str(effort),
        "deliverable-file",
        {"path": "archive/merrill-v153-oakley-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md", "render": "1"},
    )
    assert code_comp == 200, body_comp

    # 2. Unlisted file inside a custom non-hidden subfolder of cdir resolves cleanly
    body_sub, code_sub = steward_routes.handle_get(
        str(effort),
        "deliverable-file",
        {"path": "UNLISTED-SUBFOLDER-NOTE.md", "render": "1"},
    )
    assert code_sub == 200, body_sub

    # 3. Hidden .anchor directory files are skipped by subfolder search
    _body_hid, code_hid = steward_routes.handle_get(
        str(effort),
        "deliverable-file",
        {"path": "HIDDEN-INTERNAL.md"},
    )
    assert code_hid == 404

    # 4. Verify md.js does NOT rewrite cross-repo file:///C:/dev/OtherRepo/... into current cockpit's deliverable-file route
    node_exe = shutil.which("node")
    assert node_exe, "node is required to verify md.js"
    js_probe = (
        "global.window = { location: { href: 'http://127.0.0.1:8777/steward/v1?pid=campaign&dir=Cave+of+Wonders', origin: 'http://127.0.0.1:8777' }, "
        "STEWARD_PID: 'campaign', STEWARD_DIR: 'Cave of Wonders', STEWARD_PROJECT_DIR: 'C:/dev/Campaign' };\n"
        f"require({json.dumps(str(REPO_ROOT / 'steward_cockpit' / 'static' / 'md.js'))});\n"
        "const cross1 = global.mdReportHref('file:///C:/dev/OtherRepo/docs/SPEC.md', 'SPEC.md');\n"
        "const cross2 = global.mdReportHref('file:///C:/dev/Anchor/archive/merrill-v153-oakley-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md', 'Prompt');\n"
        "const same = global.mdReportHref('file:///C:/dev/Campaign/Cave%20of%20Wonders/anchor-v154-oakley-plan-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md', 'Prompt');\n"
        "delete global.window.STEWARD_PROJECT_DIR;\n"
        "const crossNoRoot = global.mdReportHref('file:///C:/dev/OtherRepo/docs/SPEC.md', 'SPEC.md');\n"
        "const sameNoRoot = global.mdReportHref('file:///C:/dev/Campaign/Cave%20of%20Wonders/anchor-v154-oakley-plan-2026-11-22/VS-CODE-PROMPT-ANCHOR-V154.md', 'Prompt');\n"
        "console.log(JSON.stringify({ cross1, cross2, same, crossNoRoot, sameNoRoot }));\n"
    )
    n_res = subprocess.run([node_exe, "-e", js_probe], capture_output=True, text=True, check=True)
    out = json.loads(n_res.stdout.strip())
    assert out["cross1"] == "file:///C:/dev/OtherRepo/docs/SPEC.md"
    assert out["cross2"].startswith("file:///C:/dev/Anchor/")
    assert out["crossNoRoot"] == "file:///C:/dev/OtherRepo/docs/SPEC.md"
    assert out["same"].startswith("/api/steward/deliverable-file?pid=campaign")
    assert "anchor-v154-oakley-plan-2026-11-22%2FVS-CODE-PROMPT-ANCHOR-V154.md" in out["same"]
    assert out["sameNoRoot"].startswith("/api/steward/deliverable-file?pid=campaign")


def test_shell_overlay_never_downgrades_newer_repo_or_clobbers_same_version_patch(tmp_path: Path):
    import zipfile as _zf
    from shell import connect as shell_connect

    dest = tmp_path / "Anchor"
    dest.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=dest, check=True, capture_output=True)

    (dest / "VERSION").write_text("1.5.4\n", encoding="utf-8")
    (dest / "anchor_gui.py").write_text("# v1.5.4 server\n", encoding="utf-8")
    (dest / "steward_engine.py").write_text("# v1.5.4 clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "v1.5.4"], cwd=dest, check=True, capture_output=True)

    # 1. Older v1.5.3 overlay must be skipped completely and logged
    old_zip = tmp_path / "old-overlay.zip"
    with _zf.ZipFile(old_zip, "w") as zf:
        zf.writestr("VERSION", "1.5.3\n")
        zf.writestr("steward_engine.py", "# stale v1.5.3\n")
    applied_old = shell_connect._apply_bundled_core_overlay(dest, candidates_override=[old_zip])
    assert applied_old is False
    assert (dest / "steward_engine.py").read_text(encoding="utf-8") == "# v1.5.4 clean\n"
    log_txt = (dest / "logs" / "overlay.log").read_text(encoding="utf-8")
    assert "Skipped stale overlay" in log_txt

    # 2. Same-version overlay must preserve locally modified git-tracked hotfixes
    (dest / "steward_engine.py").write_text("# v1.5.4 collaborator hotfix\n", encoding="utf-8")
    same_zip = tmp_path / "same-overlay.zip"
    with _zf.ZipFile(same_zip, "w") as zf:
        zf.writestr("VERSION", "1.5.4\n")
        zf.writestr("steward_engine.py", "# v1.5.4 zip original\n")
        zf.writestr("new_helper.py", "# added file\n")
    applied_same = shell_connect._apply_bundled_core_overlay(dest, candidates_override=[same_zip])
    assert applied_same is True
    assert (dest / "steward_engine.py").read_text(encoding="utf-8") == "# v1.5.4 collaborator hotfix\n"
    assert (dest / "new_helper.py").read_text(encoding="utf-8") == "# added file\n"
    log_txt2 = (dest / "logs" / "overlay.log").read_text(encoding="utf-8")
    assert "preserved_local=1" in log_txt2


def test_session0_and_offscreen_desktop_browser_guard():
    import paths

    # Session 0 Windows Service -> never interactive, always flagged as Session 0
    assert paths.is_windows_service_or_session0(_probe_fn=lambda: (0, "Service-0x0-3e7$", "Default")) is True
    assert paths.is_interactive_desktop_session(_probe_fn=lambda: (0, "Service-0x0-3e7$", "Default")) is False

    # Session 1 offscreen sandbox desktop (exebox-*) -> not Session 0, but not interactive Default desktop
    assert paths.is_windows_service_or_session0(_probe_fn=lambda: (1, "WinSta0", "exebox-TEST")) is False
    assert paths.is_interactive_desktop_session(_probe_fn=lambda: (1, "WinSta0", "exebox-TEST")) is False

    # Session 1 real interactive user desktop (WinSta0\Default) -> interactive!
    assert paths.is_windows_service_or_session0(_probe_fn=lambda: (1, "WinSta0", "Default")) is False
    assert paths.is_interactive_desktop_session(_probe_fn=lambda: (1, "WinSta0", "Default")) is True
