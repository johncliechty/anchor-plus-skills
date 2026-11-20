# -*- coding: utf-8 -*-
"""Comprehensive regression suite for the 2026-11-17 Journal Remediation Plan
(Scribe, Cave of Wonders, Reading Copy / Report Viewer, and AI Cockpit Code-Job Handoff).

Covers all 7 remediation items and all 12 adversarial review findings (B1-B3, M1-M9):
1. Scribe 90s budget, 42s/8s/8s seat caps (>=30s Claude headroom), exit-code-gated auth_error,
   strict --readonly preservation with scribe_request.md pointer on >10KB prompts, and fractional --timeout-min.
2. Cave of Wonders #btnCaveDlgSendDirectionsToSr un-hijacking, non-optimistic error handling on 504/503,
   queue_speed_racer_draft blank-draft refusal without marking unread mail Read, and concurrent-edit safety (M7).
3. Timezone-aware UTC comparison in _parse_local_or_utc_email_ts / classify_inbox_emails across MST (UTC-7),
   EST (UTC-5), and UTC+0 so replies arriving minutes after a Speed Racer send stay in Prime, plus M8 date preservation.
4. Reading Copy print CSS pagination hardening and report_viewer nested **bold *italic*** + safe standalone <hr>.
5. Engine._commit_if_dirty single-chokepoint guard for code_job / general / code_jobs_dir engines (M6).
6. code_job_handoff.snapshot_matches ancestry + NUL-delimited git diff --raw -z verification (zero commit-subject trust,
   Unicode path safety, symlink/gitlink mode rejection, and real MBA Teaching AI kept-worktree recovery check).
7. steward_review.mjs syntax & hermetic guard verification.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from typing import Any

import pytest

import comms_connector as cc
import high_seat_page as hsp
import paths
import report_viewer as rv
import scribe_engine as se
from steward_cockpit import code_job_handoff as cjh
from steward_cockpit import steward_engine as st_eng
from tools import reading_copy as rc


def _git_run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


def test_scribe_timeout_budget_exit_gated_auth_and_readonly_pointer(tmp_path: Path, monkeypatch: Any) -> None:
    """Verify B1, M1, M2, M9: 90s budget, returncode-gated auth_error, --readonly on >10KB prompts, and >=30s Claude headroom."""
    assert se.SCRIBE_LLM_TIMEOUT_SEC == 90.0

    # M1: returncode == 0 draft containing 'credit' / 'quota' / 'failed to authenticate' in quoted prose MUST succeed
    class FakePopenOk:
        pid = 99101
        returncode = 0
        stdin = None
        stdout = None
        stderr = None

        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]:
            return (
                "Hi Alice,\n\nWe still have extra credit and API quota left after the oauth session expired notice.\n\nBest,\nJohn",
                "",
            )

        def kill(self) -> None:
            pass

    monkeypatch.setattr(se.subprocess, "Popen", FakePopenOk)
    ok_res = se._invoke_scribe_cli_subprocess(["fake-llm"], "prompt", timeout_sec=10.0)
    assert ok_res["ok"] is True
    assert "extra credit" in ok_res["text"]

    # M1: returncode != 0 with standalone claude's exact expired-OAuth string MUST classify as auth_error
    class FakePopenAuthErr(FakePopenOk):
        returncode = 1

        def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]:
            return (
                '{"type":"result","is_error":true,"result":"Failed to authenticate: OAuth session expired and could not be refreshed"}',
                "",
            )

    monkeypatch.setattr(se.subprocess, "Popen", FakePopenAuthErr)
    err_res = se._invoke_scribe_cli_subprocess(["fake-claude"], "prompt", timeout_sec=10.0)
    assert err_res["ok"] is False
    assert err_res["error_code"] == "auth_error"

    # B3 (diff review): TimeoutExpired MUST tree-kill (`_kill_scribe_proc_tree`) before bounded communicate(timeout=2.0)
    killed_pids: list[int] = []
    comm_timeouts: list[float | None] = []

    class FakePopenTimeout(FakePopenOk):
        pid = 99202

        def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]:
            comm_timeouts.append(timeout)
            if len(comm_timeouts) == 1:
                raise subprocess.TimeoutExpired(cmd=["fake-cmd"], timeout=float(timeout or 8.0))
            return ("", "")

    monkeypatch.setattr(se.subprocess, "Popen", FakePopenTimeout)
    monkeypatch.setattr(se, "_kill_scribe_proc_tree", lambda p: killed_pids.append(int(p.pid)))
    to_res = se._invoke_scribe_cli_subprocess(["fake-cmd"], "prompt", timeout_sec=8.0)
    assert to_res["ok"] is False
    assert to_res["error_code"] == "timeout_exceeded"
    assert killed_pids == [99202]
    assert comm_timeouts == [8.0, 2.0]

    # B1 + M2 + M9: >10KB prompt keeps --readonly via scribe_request.md, fractional --timeout-min, and >=30s Claude headroom
    dispatch_stub = tmp_path / "agy-dispatch.mjs"
    dispatch_stub.write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(se, "_live_cli_allowed", lambda: True)
    monkeypatch.setattr(se, "_agy_dispatch_script", lambda: dispatch_stub)
    monkeypatch.setattr(se.shutil, "which", lambda name: f"/fake/bin/{name}")

    calls: list[tuple[list[str], float, str]] = []

    def fake_cli_sub(argv: list[str], prompt: str, timeout_sec: float = 90.0, output_file: Path | None = None) -> dict[str, Any]:
        pf_body = prompt
        if "--prompt-file" in argv:
            pf = Path(argv[argv.index("--prompt-file") + 1])
            if pf.is_file():
                pf_body = pf.read_text(encoding="utf-8")
        calls.append((list(argv), round(float(timeout_sec), 2), pf_body))
        joined = " ".join(argv)
        if "agy-dispatch.mjs" in joined and "Claude Opus 5.5 (High)" not in joined:
            return {"ok": False, "error_code": "timeout_exceeded", "stderr": "Gemini timed out"}
        if "/fake/bin/codex" in joined:
            return {"ok": False, "error_code": "cli_error", "stderr": "codex error"}
        if "/fake/bin/grok" in joined:
            return {"ok": False, "error_code": "timeout_exceeded", "stderr": "grok timed out"}
        if "/fake/bin/claude" in joined:
            return {"ok": False, "error_code": "auth_error", "stderr": "Failed to authenticate: OAuth session expired"}
        if "agy-dispatch.mjs" in joined and "Claude Opus 5.5 (High)" in joined:
            text = "Hi Alice,\n\nConfirmed for Thursday afternoon.\n\nBest,\nJohn"
            if output_file is not None:
                output_file.write_text(text, encoding="utf-8")
            return {"ok": True, "text": text, "returncode": 0}
        return {"ok": False, "error_code": "cli_error", "stderr": "unexpected"}

    monkeypatch.setattr(se, "_invoke_scribe_cli_subprocess", fake_cli_sub)

    large_draft = "Hi Alice,\n\n" + "\n".join(
        f"| {i:03d} | Participant {i:03d} | Confirmed for Thursday afternoon workshop |"
        for i in range(1, 165)
    ) + "\n\nBest,\nJohn"

    res = se.synthesize_reply(
        {
            "from": "Alice Example <alice@example.org>",
            "subject": "Workshop roster",
            "body": "Please confirm the Thursday workshop roster.",
            "current_draft": large_draft,
        },
        instruction="confirm Thursday afternoon",
        data_dir=tmp_path,
    )
    assert res["ok"] is True
    assert res["seat_used"] == "claude"
    assert len(calls) == 5

    gem_argv, gem_to, gem_pf = calls[0]
    assert "--readonly" in gem_argv
    assert gem_to == 42.0
    assert float(gem_argv[gem_argv.index("--timeout-min") + 1]) < 1.0
    assert "scribe_request.md" in gem_pf

    assert calls[1][1] == 8.0
    assert calls[2][1] == 8.0

    cl_argv, cl_to, _ = calls[4]
    assert "--readonly" in cl_argv
    assert cl_to >= 30.0


def test_speed_racer_button_unhijacked_refuses_blank_504_and_preserves_concurrent_edits(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Verify Fix 2 & M7: #btnCaveDlgSendDirectionsToSr has no data-steward-draft-intent, 504 never queues blank draft or marks Read, and redraft preserves concurrent user edits."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    # 1. Verify HTML + JS contract
    py_src = (Path(__file__).resolve().parent.parent / "high_seat_page.py").read_text(encoding="utf-8")
    idx_btn = py_src.index('id="btnCaveDlgSendDirectionsToSr"')
    btn_tag = py_src[max(0, idx_btn - 120) : idx_btn + 220]
    assert "data-steward-draft-intent" not in btn_tag

    js_src = (Path(__file__).resolve().parent.parent / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert '[data-steward-draft-intent]:not(#btnCaveDlgSendDirectionsToSr)' in js_src
    assert "res.status < 400 && d && d.ok" in js_src
    assert "pending_scribe_feedback" in js_src
    assert "preRefineDraftVal" in js_src

    # 2. Verify queue_speed_racer_draft on Scribe 504 does NOT queue a blank draft or mark unread mail Read / Acted
    anchor_dir = tmp_path / ".anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    unread_hdr = {
        "uid": "u-prime-101",
        "account_id": "acct-main",
        "account_badge": "Work 365",
        "from": "Colleague One <colleague@example.org>",
        "sender_email": "colleague@example.org",
        "subject": " Urgent Budget Sign-Off",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snippet": "Can you sign off on the Q4 budget today?",
        "is_read": False,
        "is_focused": True,
    }
    (anchor_dir / "comms-sync.json").write_text(
        json.dumps({"email_headers": [unread_hdr], "sent_email_headers": [], "calendar_events": []}),
        encoding="utf-8",
    )
    read_remote_calls: list[str] = []
    monkeypatch.setattr(cc, "mark_email_read_remote", lambda **_kw: read_remote_calls.append(str(_kw.get("uid") or "")))

    se.set_scribe_llm_hook(
        lambda **_kw: {"ok": False, "status": "timeout", "error": "Scribe timed out"}
    )
    try:
        q_fail, status_fail = cc.handle_comms_post({
            "action": "speed_racer_queue",
            "uid": "u-prime-101",
            "account_id": "acct-main",
            "from": "Colleague One <colleague@example.org>",
            "to": "colleague@example.org",
            "subject": "Urgent Budget Sign-Off",
            "incoming_snippet": "Can you sign off on the Q4 budget today?",
            "steward_directions": "Tell them I approve the Q4 budget and ask for the PDF copy.",
        })
    finally:
        se.set_scribe_llm_hook(None)

    assert q_fail["ok"] is False
    assert status_fail in (503, 504)
    assert cc.load_speed_racer_queue()["queue"] == []
    assert read_remote_calls == []
    assert "u-prime-101" not in (cc.load_triage_prefs().get("acted_upon_emails") or {})

    # 3. Verify M7: redraft persists pending_scribe_feedback on failure AND preserves concurrent user edits on success
    q_ok = cc.queue_speed_racer_draft({
        "id": "sr-conc-1",
        "uid": "u-conc-1",
        "to": "Colleague One <colleague@example.org>",
        "subject": "Re: Urgent Budget Sign-Off",
        "draft_body": "Hi Colleague,\n\nInitial Scribe draft.\n\nBest,\nJohn",
        "preserve_manual_draft": True,
    })
    assert q_ok["ok"] is True

    se.set_scribe_llm_hook(lambda **_kw: {"ok": False, "status": "timeout", "error": "Timed out"})
    try:
        r_fail = cc.act_speed_racer_draft({
            "sr_action": "redraft",
            "id": "sr-conc-1",
            "feedback": "Add a note requesting the signed appendix.",
        })
    finally:
        se.set_scribe_llm_hook(None)

    assert r_fail["ok"] is False
    saved_item = cc.load_speed_racer_queue()["queue"][0]
    assert saved_item["pending_scribe_feedback"] == "Add a note requesting the signed appendix."
    assert "Initial Scribe draft." in saved_item["draft_body"]

    # Simulate user concurrently editing the draft while Scribe redraft is in flight
    def hook_with_concurrent_user_edit(**_kw: Any) -> str:
        cc.act_speed_racer_draft({
            "sr_action": "edit",
            "id": "sr-conc-1",
            "draft_body": "Hi Colleague,\n\nManual edit typed by user mid-flight.\n\nBest,\nJohn",
        })
        return "Hi Colleague,\n\nLate Scribe redraft output.\n\nBest,\nJohn"

    se.set_scribe_llm_hook(hook_with_concurrent_user_edit)
    try:
        r_conc = cc.act_speed_racer_draft({
            "sr_action": "redraft",
            "id": "sr-conc-1",
            "feedback": "Make it shorter",
        })
    finally:
        se.set_scribe_llm_hook(None)

    assert r_conc["ok"] is True
    assert r_conc.get("concurrent_user_edit_preserved") is True
    after_conc = cc.load_speed_racer_queue()["queue"][0]
    assert "Manual edit typed by user mid-flight." in after_conc["draft_body"]
    assert after_conc["user_edited"] is True
    assert after_conc["pending_scribe_feedback"] == ""


@pytest.mark.parametrize(
    ("tz_offset_hours", "local_send_str", "expected_send_utc_hour"),
    [
        (-7, "2026-11-16 15:00", 22),  # MST (UTC-7): 15:00 local == 22:00Z
        (-5, "2026-11-16 15:00", 20),  # EST (UTC-5): 15:00 local == 20:00Z
        (0, "2026-11-16 15:00", 15),   # UTC+0:       15:00 local == 15:00Z
    ],
)
def test_focused_unread_reply_after_local_send_never_swallowed_across_timezones(
    tmp_path: Path,
    monkeypatch: Any,
    tz_offset_hours: int,
    local_send_str: str,
    expected_send_utc_hour: int,
) -> None:
    """Verify Fix 3 & M8: Naive local Speed Racer / manual send timestamps are converted to true UTC,
    so a fresh reply arriving 42 minutes AFTER our send stays in Prime across MST, EST, and UTC."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cc, "_LOCAL_NAIVE_TZ_OVERRIDE", timezone(timedelta(hours=tz_offset_hours)))
    cc._LOCAL_TS_MEMO.clear()

    parsed_str = cc._parse_local_or_utc_email_ts(local_send_str)
    assert parsed_str == f"2026-11-16 {expected_send_utc_hour:02d}:00"
    parsed = datetime.strptime(parsed_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)

    # Configure Speed Racer archive with a legacy naive local approved_at timestamp (no approved_at_utc)
    cc.save_speed_racer_queue({
        "queue": [],
        "archive": [
            {
                "id": "sr-prev-1",
                "uid": "u-old-thread",
                "to": "Collaborator <collab@example.org>",
                "subject": "Re: Research Grant Milestone",
                "status": "Approved & Sent",
                "send_ok": True,
                "approved_at": local_send_str,
            }
        ],
    })

    # Older message (30 min BEFORE our send) vs NEW unread reply (42 min AFTER our send)
    older_utc = (parsed - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer_reply_utc = (parsed + timedelta(minutes=42)).strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = [
        {
            "uid": "u-old-thread",
            "account_id": "acct-1",
            "account_badge": "Work 365",
            "from": "Collaborator <collab@example.org>",
            "sender_email": "collab@example.org",
            "subject": "Research Grant Milestone",
            "date": older_utc,
            "snippet": "Initial milestone question.",
            "is_read": False,
            "is_focused": True,
        },
        {
            "uid": "u-fresh-reply",
            "account_id": "acct-1",
            "account_badge": "Work 365",
            "from": "Collaborator <collab@example.org>",
            "sender_email": "collab@example.org",
            "subject": "Re: Research Grant Milestone",
            "date": newer_reply_utc,
            "snippet": "Thanks! One follow-up question on table 2.",
            "is_read": False,
            "is_focused": True,
        },
    ]

    imp, _oth = cc.classify_inbox_emails(headers, prefs=cc.load_triage_prefs(), sent_headers=[])
    imp_uids = [m["uid"] for m in imp]
    assert "u-fresh-reply" in imp_uids
    assert "u-old-thread" not in imp_uids

    # Also verify M8: approve_send stamps approved_at_utc and preserves original message date in acted_upon_emails
    monkeypatch.setattr(cc, "send_email_message", lambda _p: {"ok": True, "uid": "u-fresh-reply"})
    cc.save_triage_prefs({
        "acted_upon_emails": {
            "u-fresh-reply": {
                "uid": "u-fresh-reply",
                "date": newer_reply_utc,
                "subject": "Re: Research Grant Milestone",
            }
        }
    })
    q_fresh = cc.queue_speed_racer_draft({
        "id": "sr-reply-2",
        "uid": "u-fresh-reply",
        "to": "Collaborator <collab@example.org>",
        "subject": "Re: Research Grant Milestone",
        "draft_body": "Hi Collaborator,\n\nHere are the table 2 details.\n\nBest,\nJohn",
        "preserve_manual_draft": True,
    })
    assert q_fresh["ok"] is True
    app_res = cc.act_speed_racer_draft({
        "sr_action": "approve_send",
        "id": "sr-reply-2",
        "uid": "u-fresh-reply",
        "to": "Collaborator <collab@example.org>",
        "subject": "Re: Research Grant Milestone",
        "draft_body": "Hi Collaborator,\n\nHere are the table 2 details.\n\nBest,\nJohn",
    })
    assert app_res["ok"] is True
    arch0 = app_res["speed_racer"]["archive"][0]
    assert str(arch0.get("approved_at_utc") or "").endswith("Z")
    acted_entry = cc.load_triage_prefs()["acted_upon_emails"]["u-fresh-reply"]
    assert str(acted_entry.get("at_utc") or "").endswith("Z")
    assert acted_entry["date"] == newer_reply_utc


def test_reading_copy_print_css_and_report_viewer_nested_emphasis_and_hr() -> None:
    """Verify Fix 4 (M3, M4): reading_copy PRINT_CSS pagination rules + report_viewer nested bold/italic and safe <hr>."""
    assert "break-after:avoid" in rc.PRINT_CSS
    assert "orphans:3;widows:3" in rc.PRINT_CSS
    assert "thead{display:table-header-group}" in rc.PRINT_CSS
    assert "tr,blockquote{break-inside:avoid" in rc.PRINT_CSS
    assert "overflow:visible !important" in rc.PRINT_CSS
    assert "white-space:pre-wrap !important" in rc.PRINT_CSS

    md = (
        "---\n"
        "Chapter Title\n"
        "---\n\n"
        "She opened the **Second *Wizard's Dial*** and read the **bold *inner* tail**.\n\n"
        "---\n\n"
        "```markdown\n"
        "---\n"
        "inside code fence\n"
        "```\n"
    )
    rendered = rv.markdown_to_html(md)
    assert "<strong>Second <em>Wizard&#x27;s Dial</em></strong>" in rendered
    assert "<strong>bold <em>inner</em> tail</strong>" in rendered
    # Standalone scene break after blank line becomes <hr>, whereas line-0 and Setext-style lines and code-fence lines do not
    assert rendered.count("<hr>") == 1
    assert "inside code fence" in rendered


def test_checkpoint_guard_and_code_job_snapshot_matches_ancestry_diff(tmp_path: Path, monkeypatch: Any) -> None:
    """Verify Fix 5 (B3, M5, M6): _commit_if_dirty skips code_job/general/code_jobs_dir, and snapshot_matches
    accepts post-completion runtime checkpoint commits while rejecting tracked tampering, symlinks, and non-ancestors."""
    # 1. M6: Single-chokepoint guard in Engine._commit_if_dirty
    git_calls: list[list[str]] = []
    fake_code_jobs_root = tmp_path / "Anchor-code-jobs"
    fake_code_jobs_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "code_jobs_dir", lambda: fake_code_jobs_root)

    for dummy_eng in (
        SimpleNamespace(general=True, code_job=False, dir=tmp_path / "proj", _git=lambda args, **_k: git_calls.append(args)),
        SimpleNamespace(general=False, code_job=True, dir=tmp_path / "proj", _git=lambda args, **_k: git_calls.append(args)),
        SimpleNamespace(general=False, code_job=False, dir=fake_code_jobs_root / "job-1", _git=lambda args, **_k: git_calls.append(args)),
    ):
        st_eng.Engine._commit_if_dirty(dummy_eng, "steward auto-sleep checkpoint")
    assert git_calls == []

    # 2. B3 + M5: Synthetic git repo testing snapshot_matches with Unicode path, checkpoint commit, tampering, and symlink mode
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_run(repo, "init")
    _git_run(repo, "config", "core.autocrlf", "false")
    _git_run(repo, "config", "user.email", "tester@example.org")
    _git_run(repo, "config", "user.name", "Tester")

    base_file = repo / "README.md"
    base_file.write_text("base\n", encoding="utf-8")
    _git_run(repo, "add", "README.md")
    _git_run(repo, "commit", "-m", "base commit")
    base_commit = _git_run(repo, "rev-parse", "HEAD").stdout.strip()

    unicode_rel = "notes/café-minus−check.md"
    unicode_path = repo / unicode_rel
    unicode_path.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = "Verified result with Unicode minus (−) and café.\n".encode("utf-8")
    unicode_path.write_bytes(payload_bytes)
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()

    _git_run(repo, "add", unicode_rel)
    _git_run(repo, "commit", "-m", "Code job synthetic-1")
    worker_commit = _git_run(repo, "rev-parse", "HEAD").stdout.strip()

    job_rec: dict[str, Any] = {
        "id": "synthetic-1",
        "status": "done",
        "worktree": str(repo),
        "worktree_kept": True,
        "base": base_commit,
        "base_commit": base_commit,
        "worker_commit": worker_commit,
        "manifest": [unicode_rel],
        "outputs": [unicode_rel],
    }
    saved_snap = cjh.snapshot(job_rec)
    assert "error" not in saved_snap
    assert unicode_rel in saved_snap["files"]
    job_rec["recovery_snapshot"] = saved_snap
    assert cjh.snapshot_matches(job_rec, cjh.snapshot(job_rec), saved_snap) is True

    # Add a post-worker runtime-only commit (with ANY arbitrary commit subject — zero commit-subject trust!)
    rt_file = repo / ".ecgberht" / "strip.json"
    rt_file.parent.mkdir(parents=True, exist_ok=True)
    rt_file.write_text('{"idle": true}\n', encoding="utf-8")
    _git_run(repo, "add", ".ecgberht/strip.json")
    _git_run(repo, "commit", "-m", "steward auto-sleep checkpoint")
    assert cjh.snapshot_matches(job_rec, cjh.snapshot(job_rec), saved_snap) is True

    # Mutate the tracked deliverable in a post-worker commit -> MUST fail snapshot_matches!
    unicode_path.write_text("Tampered content!\n", encoding="utf-8")
    _git_run(repo, "add", unicode_rel)
    _git_run(repo, "commit", "-m", "steward auto-sleep checkpoint")
    assert cjh.snapshot_matches(job_rec, cjh.snapshot(job_rec), saved_snap) is False

    # Reset back to valid checkpoint state, then inject a mode 120000 symlink entry in git index -> MUST fail!
    _git_run(repo, "reset", "--hard", "HEAD~1")
    assert cjh.snapshot_matches(job_rec, cjh.snapshot(job_rec), saved_snap) is True
    blob_hash = _git_run(repo, "hash-object", "-w", "README.md").stdout.strip()
    _git_run(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob_hash},.ecgberht/sneaky-link")
    _git_run(repo, "commit", "-m", "inject symlink mode")
    assert cjh.snapshot_matches(job_rec, cjh.snapshot(job_rec), saved_snap) is False

    # M-1 (Round-2 diff review): core.autocrlf=true repo where a manifest CRLF file is committed AFTER saved_snap -> MUST pass!
    crlf_repo = tmp_path / "crlf_repo"
    crlf_repo.mkdir()
    _git_run(crlf_repo, "init")
    _git_run(crlf_repo, "config", "core.autocrlf", "true")
    _git_run(crlf_repo, "config", "user.email", "tester@example.org")
    _git_run(crlf_repo, "config", "user.name", "Tester")
    (crlf_repo / "README.md").write_bytes(b"base\r\n")
    _git_run(crlf_repo, "add", "README.md")
    _git_run(crlf_repo, "commit", "-m", "base")
    crlf_base = _git_run(crlf_repo, "rev-parse", "HEAD").stdout.strip()

    # Worker creates CRLF file in working tree before committing; snapshot is taken before _commit_manifest commits it
    crlf_rel = "output/table.csv"
    crlf_path = crlf_repo / crlf_rel
    crlf_path.parent.mkdir(parents=True, exist_ok=True)
    crlf_path.write_bytes(b"col_a,col_b\r\n1,2\r\n")
    crlf_job: dict[str, Any] = {
        "id": "crlf-1",
        "status": "done",
        "worktree": str(crlf_repo),
        "worktree_kept": True,
        "base": crlf_base,
        "manifest": [crlf_rel],
        "outputs": [crlf_rel],
    }
    crlf_saved = cjh.snapshot(crlf_job)
    assert crlf_rel in crlf_saved["files"]
    # Now _commit_manifest commits the CRLF file (stored as LF blob in Git while working tree retains CRLF)
    _git_run(crlf_repo, "add", crlf_rel)
    _git_run(crlf_repo, "commit", "-m", "candidate manifest commit")
    assert cjh.snapshot_matches(crlf_job, cjh.snapshot(crlf_job), crlf_saved) is True

    # 3. Optional local kept-worktree verification via env override (keeps test 100% host-path-free for distro scan)
    opt_jobs_env = os.environ.get("ANCHOR_OPTIONAL_KEPT_JOBS_JSON", "").strip()
    opt_jobs_file = Path(opt_jobs_env) if opt_jobs_env else None
    if opt_jobs_file is not None and opt_jobs_file.is_file():
        mba_data = json.loads(opt_jobs_file.read_text(encoding="utf-8"))
        jobs_list = (
            mba_data.get("jobs")
            if (isinstance(mba_data, dict) and isinstance(mba_data.get("jobs"), list))
            else (list(mba_data.values()) if isinstance(mba_data, dict) else mba_data)
        )
        matched = [
            j for j in (jobs_list or [])
            if isinstance(j, dict)
            and j.get("status") in ("done", "stopped")
            and isinstance(j.get("recovery_snapshot"), dict)
            and Path(str(j.get("worktree") or "")).is_dir()
        ]
        for mj in matched:
            assert cjh.snapshot_matches(mj, cjh.snapshot(mj), mj["recovery_snapshot"]) is True, (
                f"Expected kept worktree {mj['id']} to pass snapshot_matches"
            )
            if not mj.get("landed") and not mj.get("placed"):
                assert cjh.recovery_error(mj) == "", f"Expected recovery_error == '' for {mj['id']}, got {cjh.recovery_error(mj)!r}"


def test_steward_review_mjs_syntax_and_hermetic_guard(tmp_path: Path) -> None:
    """Verify Fix 6 (B2, M11): steward_review.mjs syntax is clean and hermetic guard blocks live agy-dispatch in tests."""
    script = Path(__file__).resolve().parent.parent / "tools" / "steward_review.mjs"
    chk = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, encoding="utf-8")
    assert chk.returncode == 0, chk.stderr

    src = script.read_text(encoding="utf-8")
    assert "isStandaloneClaudeAuthFailure" in src
    assert "tryAgyClaudeReviewFallback" in src
    assert "'--readonly'" in src
    assert "'--json-safe'" in src
    assert "model_attested: false" in src
    assert "PYTEST_CURRENT_TEST" in src



def test_email_thread_messages_ordered_newest_first_across_cave_and_speed_racer(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Verify multi-message email threads display the most recent email at index 0 (top),
    followed by the next-most-recent below that, down to the oldest at the bottom across:
      1. classify_inbox_emails card thread_messages
      2. get_email_dialogue_context (including RFC-2822 + ISO-8601 + outbound sent items)
      3. queue_speed_racer_draft thread_messages
      4. _compact_archived_email_item and Scribe _bound_synthesis_context_256kb
      5. static/high-seat-page.js _sortThreadMsgsNewestFirst & _renderThreadMessagesStackHtml."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    anchor_dir = tmp_path / ".anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    headers = [
        {
            "uid": "u-msg-1-oldest",
            "account_id": "acct-1",
            "account_badge": "Work 365",
            "from": "Partner One <partner@example.org>",
            "sender_email": "partner@example.org",
            "subject": "Project Horizon Schedule",
            "date": "Fri, 13 Nov 2026 13:57:00 +0000",
            "body": "Oldest message from Friday.",
            "snippet": "Oldest message from Friday.",
            "is_read": True,
            "is_focused": True,
        },
        {
            "uid": "u-msg-2-mid",
            "account_id": "acct-1",
            "account_badge": "Work 365",
            "from": "Partner One <partner@example.org>",
            "sender_email": "partner@example.org",
            "subject": "Re: Project Horizon Schedule",
            "date": "Mon, 16 Nov 2026 13:58:00 +0000",
            "body": "Middle message from Monday — can you review the draft?",
            "snippet": "Middle message from Monday — can you review the draft?",
            "is_read": False,
            "is_focused": True,
        },
        {
            "uid": "u-msg-4-newest",
            "account_id": "acct-1",
            "account_badge": "Work 365",
            "from": "Partner One <partner@example.org>",
            "sender_email": "partner@example.org",
            "subject": "Re: Project Horizon Schedule",
            "date": "Tue, 17 Nov 2026 18:58:00 +0000",
            "body": "Most recent reply from Tuesday afternoon — can you confirm this works?",
            "snippet": "Most recent reply from Tuesday afternoon — can you confirm this works?",
            "is_read": False,
            "is_focused": True,
        },
    ]
    sent_headers = [
        {
            "uid": "sent-msg-3",
            "account_id": "acct-1",
            "account_badge": "Sent",
            "direction": "sent",
            "to": "Partner One <partner@example.org>",
            "subject": "Re: Project Horizon Schedule",
            "date": "2026-11-17T15:54:00Z",
            "body": "Our Tuesday morning outbound reply.",
            "snippet": "Our Tuesday morning outbound reply.",
        }
    ]
    (anchor_dir / "comms-sync.json").write_text(
        json.dumps({"email_headers": headers, "sent_email_headers": sent_headers, "calendar_events": []}),
        encoding="utf-8",
    )

    # 1. classify_inbox_emails puts newest unread message at index 0 of thread_messages
    imp, _oth = cc.classify_inbox_emails(headers, prefs=cc.load_triage_prefs(), sent_headers=[])
    assert len(imp) == 1
    card_tmsgs = imp[0]["thread_messages"]
    assert [m["uid"] for m in card_tmsgs] == ["u-msg-4-newest", "u-msg-2-mid", "u-msg-1-oldest"]
    assert card_tmsgs[0]["is_current"] is True

    # 2. get_email_dialogue_context merges inbound + sent messages and sorts strictly newest -> oldest
    dlg = cc.get_email_dialogue_context({
        "uid": "u-msg-4-newest",
        "account_id": "acct-1",
        "subject": "Re: Project Horizon Schedule",
    })
    assert [m["uid"] for m in dlg["thread_messages"]] == [
        "u-msg-4-newest",
        "sent-msg-3",
        "u-msg-2-mid",
        "u-msg-1-oldest",
    ]
    assert dlg["thread_messages"][0]["is_current"] is True
    assert "Most recent reply" in dlg["thread_messages"][0]["body"]
    assert "Oldest message" in dlg["thread_messages"][-1]["body"]

    # 3. _compact_archived_email_item keeps the 2 MOST RECENT messages (indices 0..1), never the oldest
    compacted = cc._compact_archived_email_item({"body": "latest", "thread_messages": dlg["thread_messages"]})
    assert [m["uid"] for m in compacted["thread_messages"]] == ["u-msg-4-newest", "sent-msg-3"]

    # 4. queue_speed_racer_draft attaches newest-first thread_messages onto Speed Racer item
    sr_q = cc.queue_speed_racer_draft({
        "id": "sr-horizon-1",
        "uid": "u-msg-4-newest",
        "account_id": "acct-1",
        "to": "Partner One <partner@example.org>",
        "subject": "Re: Project Horizon Schedule",
        "draft_body": "Hi Partner,\n\nConfirmed for Thursday.\n\nBest,\nJohn",
        "preserve_manual_draft": True,
    })
    assert sr_q["ok"] is True
    sr_tmsgs = sr_q["draft"]["thread_messages"]
    assert [m["uid"] for m in sr_tmsgs] == ["u-msg-4-newest", "u-msg-2-mid", "u-msg-1-oldest"]

    # 5. Scribe 256KB context bounding preserves newest turn when given newest-first thread_messages
    bounded = se._bound_synthesis_context_256kb(
        "latest body",
        thread_messages=[
            {"uid": "m-new", "date": "2026-11-17 18:58", "is_current": True, "body": "newest turn " + ("y" * 260)},
            {"uid": "m-old", "date": "2026-11-13 13:57", "is_current": False, "body": "oldest turn " + ("x" * 800)},
        ],
        max_bytes=500,
    )
    assert bounded["thread_truncated"] is True
    assert "newest turn" in bounded["bounded_thread"]
    assert "oldest turn" not in bounded["bounded_thread"]

    # 6. JS syntax & client-side newest-first helpers
    js_path = Path(__file__).resolve().parent.parent / "static" / "high-seat-page.js"
    chk_js = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True, encoding="utf-8")
    assert chk_js.returncode == 0, chk_js.stderr
    js_src = js_path.read_text(encoding="utf-8")
    assert "function _sortThreadMsgsNewestFirst" in js_src
    assert "function _renderThreadMessagesStackHtml" in js_src
