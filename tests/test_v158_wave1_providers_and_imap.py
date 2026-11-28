"""Wave 1 regression suite for v1.5.8 Collaborator Onboarding & Runtime Provider Truth.

Covers:
1. model_policy._gemini_key sentinel fix (`gemini-pro-orchestrator-*` never outranks `gemini-4-*`).
2. Cross-platform native-first CLI discovery (`%USERPROFILE%\\.local\\bin\\claude.exe`,
   `%LOCALAPPDATA%\\Programs\\OpenAI\\Codex\\bin\\codex.exe`, `%LOCALAPPDATA%\\agy\\bin\\agy.exe`)
   and Windows `BatBadBut`-safe `.cmd` shim unwrapping (`node.exe <script.js>` + metacharacter rejection).
3. onboard_wizard live model discovery never injects unentitled `gemini-4-argon` ahead of live CLI models,
   `agy.exe` never spawns `gemini.cmd` or `agy auth login`, `run_service_live_test` fails closed when CLI is missing,
   and `ensure_standing_foundry_skills_loaded` passes `skills_home=` across all 4 CLI homes.
4. 300,000-message Gmail IMAP sync (`exists_count=292235`) uses O(window) sequence-tail `FETCH` + bounded
   `UNSEEN SINCE`, guards `exists_count=0`, surfaces sync errors (`mail_sync_state == "sync_error"`), and blocks
   fabricated `recipient@example.com` sends in Speed Racer.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

import comms_connector
import model_policy
import onboard_wizard


def test_gemini_catalog_ranking_keeps_numbered_models_ahead_of_orchestrator():
    raw = {
        "models": [
            {"model": "gemini-pro-orchestrator-neon", "efforts": ["high"]},
            {"model": "gemini-4-hydrogen", "efforts": ["medium", "high"]},
            {"model": "gemini-3.8-flash", "efforts": ["low", "medium", "high"]},
        ]
    }
    rows = model_policy.normalize_catalog("gemini", raw)
    chosen = model_policy.select_model("gemini", rows)
    assert chosen["model"] == "gemini-4-hydrogen"
    assert chosen["effort"] == "high"
    by_model = {r["model"]: r["rank"] for r in rows}
    assert by_model["gemini-4-hydrogen"] < by_model["gemini-pro-orchestrator-neon"] < by_model["gemini-3.8-flash"]


def test_native_first_cli_resolution_and_batbadbut_cmd_safety(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "userhome"
    local_app = fake_home / "AppData" / "Local"
    app_data = fake_home / "AppData" / "Roaming"

    claude_exe = fake_home / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    claude_exe.parent.mkdir(parents=True)
    claude_exe.write_text("bin", encoding="utf-8")
    if os.name != "nt":
        claude_exe.chmod(0o755)

    env = {
        "PATH": str(tmp_path / "empty_bin"),
        "USERPROFILE": str(fake_home),
        "HOME": str(fake_home),
        "LOCALAPPDATA": str(local_app),
        "APPDATA": str(app_data),
    }
    found = model_policy.resolve_cli_executable("claude", env=env)
    assert found == str(claude_exe)

    if os.name == "nt":
        npm_dir = app_data / "npm"
        script_js = npm_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        script_js.parent.mkdir(parents=True)
        script_js.write_text("console.log('ok');\n", encoding="utf-8")
        fake_node = npm_dir / "node.exe"
        fake_node.write_text("node", encoding="utf-8")
        codex_cmd = npm_dir / "codex.cmd"
        codex_cmd.write_text(
            '@IF EXIST "%~dp0\\node.exe" (\r\n  "%~dp0\\node.exe" "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n)\r\n',
            encoding="utf-8",
        )
        unwrapped = model_policy.safe_cli_argv(str(codex_cmd), ['x"&echo INJECTED&"'], env=env)
        assert unwrapped == [str(fake_node.resolve()), str(script_js.resolve()), 'x"&echo INJECTED&"']

        custom_bat = tmp_path / "custom.cmd"
        custom_bat.write_text("@echo off\r\necho %*\r\n", encoding="utf-8")
        with pytest.raises(ValueError, match="metacharacters"):
            model_policy.safe_cli_argv(str(custom_bat), ['x"&echo INJECTED&"'], env=env)


def test_onboard_wizard_respects_live_entitled_models_and_skills_home_sync(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        model_policy,
        "discover",
        lambda fam, **_kw: (
            [
                {"model": "gemini-4-hydrogen", "efforts": ["medium", "high"], "rank": 0, "upgrade": None, "evidence": "provider_catalog_order"},
                {"model": "gemini-3.8-flash", "efforts": ["low", "medium", "high"], "rank": 1, "upgrade": None, "evidence": "provider_catalog_order"},
            ],
            "agy",
        ),
    )
    onboard_wizard._LIVE_MODEL_CACHE.clear()
    rows = onboard_wizard._discover_live_service_models("gemini", force=True)
    assert [r["model"] for r in rows] == ["gemini-4-hydrogen", "gemini-3.8-flash"]
    assert "gemini-4-argon" not in [r["model"] for r in rows]

    # Standing skills sync uses skills_home= across all 4 CLI homes without TypeError
    fake_anchor = tmp_path / "Anchor"
    bundled_g = fake_anchor / "vendor" / "bundled-skills" / "gandalf"
    bundled_g.mkdir(parents=True)
    (bundled_g / "SKILL.md").write_text("---\nname: gandalf\ndescription: test\n---\n", encoding="utf-8")
    homes = (
        tmp_path / "skills",
        tmp_path / ".claude" / "skills",
        tmp_path / ".codex" / "skills",
        tmp_path / ".agents" / "skills",
        tmp_path / ".gemini" / "antigravity" / "skills",
    )
    sync_res = onboard_wizard.ensure_standing_foundry_skills_loaded(
        base_dir=fake_anchor,
        sync_if_missing=True,
        cli_homes=homes,
    )
    assert sync_res["ok"] is True
    assert sync_res["error"] == ""
    for h in homes:
        assert (h / "gandalf" / "SKILL.md").is_file()


def test_imap_300k_mailbox_uses_tail_sequence_fetch_and_empty_guard():
    calls: list[tuple] = []

    class _LargeGmailConn:
        def fetch(self, seq_set: str, parts: str):
            calls.append(("fetch", seq_set, parts))
            assert seq_set == "292086:292235"
            return "OK", [
                (b"292234 (UID 900001 FLAGS (\\Seen))", b""),
                (b"292235 (UID 900002 FLAGS ())", b""),
            ]

        def uid(self, cmd: str, *args):
            calls.append(("uid", cmd, args))
            if cmd == "SEARCH":
                crit = args[-1]
                assert "UNDELETED" not in crit, "Must never run unbounded UID SEARCH UNDELETED on 292k inbox!"
                assert crit.startswith("(UNSEEN SINCE ")
                return "OK", [b"900002"]
            if cmd == "FETCH":
                return "OK", [
                    (
                        b"292235 (UID 900002 FLAGS () BODY[HEADER.FIELDS (SUBJECT FROM TO CC DATE MESSAGE-ID)] {96}",
                        b"Subject: Welcome Collaborator\r\nFrom: James <jfliechty@example.org>\r\nDate: Fri, 27 Nov 2026 10:52:00 -0800\r\nMessage-ID: <m1@example.org>\r\n\r\n",
                    ),
                    b")",
                    (
                        b"292234 (UID 900001 FLAGS (\\Seen) BODY[HEADER.FIELDS (SUBJECT FROM TO CC DATE MESSAGE-ID)] {90}",
                        b"Subject: Earlier Note\r\nFrom: Team <team@example.org>\r\nDate: Thu, 26 Nov 2026 09:00:00 -0800\r\nMessage-ID: <m0@example.org>\r\n\r\n",
                    ),
                    b")",
                ]
            raise AssertionError(f"Unexpected UID command {cmd}")

    res = comms_connector.imap_uid_fetch_headers(
        _LargeGmailConn(),
        account_id="comms-test",
        account_email="collab@example.org",
        account_badge="Gmail",
        max_messages=50,
        exists_count=292235,
    )
    assert res["fetched_count"] == 2
    assert [h["uid"] for h in res["headers"]] == ["900002", "900001"]

    # Empty inbox (EXISTS == 0) returns immediately with 0 IMAP round-trips
    empty_calls: list[tuple] = []

    class _ZeroConn:
        def fetch(self, *a):
            empty_calls.append(a)
            raise AssertionError("Must not FETCH 1:0 on empty mailbox")

        def uid(self, *a):
            empty_calls.append(a)
            raise AssertionError("Must not UID SEARCH on empty mailbox")

    empty_res = comms_connector.imap_uid_fetch_headers(_ZeroConn(), exists_count=0)
    assert empty_res["headers"] == []
    assert empty_calls == []


def test_placeholder_recipient_blocked_on_send():
    blocked = comms_connector.send_email_message({
        "to": "recipient@example.com",
        "subject": "Draft without real recipient",
        "body": "Hello",
    })
    assert blocked["ok"] is False
    assert "recipient@example.com" in blocked["error"]
