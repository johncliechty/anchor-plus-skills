"""Regression tests for Cave 'The List' Steward Auto-Checked Steps tray UX & lifecycle (2026-11-18):
- Automatic pruning of obsolete auto-check notices for already-archived / deleted / confirmed steps.
- `confirm_autocheck` (`✓ Confirm Done`), `confirm_autocheck(archive_tile=True)` (`✓ Done & Archive`),
  and `confirm_all_autochecks` (`✓ Confirm All & Clear`).
- `undo_autocheck` (`↺ Undo`) and manual `toggle_step` uncheck suppressing repeat auto-checking from the
  same sent email / deliverable while allowing genuinely new completions.
- End-to-end Chromium Playwright verification of `#wlAutoCheckedStrip` interactions against real `comms_connector`.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import comms_connector as comms
import high_seat_page
import paths

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def isolated_comms_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path, raising=False)
    comms._WORKING_LIST_SPINE_CACHE.clear()
    return tmp_path


def test_autocheck_pruning_confirm_archive_undo_suppression_and_step_toggle(
    isolated_comms_env: Path,
) -> None:
    """Backend lifecycle invariants for `auto_checked_log` / `auto_checked`:
    1. Already-archived tiles' stale auto-check entries are pruned automatically on load/prune.
    2. Active tiles retain concise `clean_step_text` + step progress metadata (`1/3`, `All 1/1`).
    3. `confirm_autocheck` keeps `step['done'] == True`, sets `auto_check_confirmed == True`,
       clears the tray entry, and stays clear across repeat `reconcile_working_list_activity`.
    4. `confirm_autocheck(archive_tile=True)` archives the tile to `Things Done` and drops
       any pending `tile-all-steps-done:<id>` proposal.
    5. `undo_autocheck` unchecks the step and suppresses repeat auto-checking from the SAME
       sent-email signal while still allowing a NEW distinct sent-email signal to auto-check.
    6. `confirm_all_autochecks` and manual `toggle_step` clean up `auto_checked` deterministically.
    """
    wl_path = isolated_comms_env / ".anchor" / "working-list-spine.json"
    wl_path.parent.mkdir(parents=True, exist_ok=True)
    seed_doc = {
        "tiles": [
            {
                "id": "tile-arch-old",
                "title": "Completed & Archived Transfer",
                "category": "Personal",
                "priority": 1,
                "done": True,
                "archived": True,
                "steps": [
                    {"id": "st-arch-1", "text": "Send transfer paperwork", "done": True, "auto_checked_at": "2026-11-14T18:00:00Z"}
                ],
            },
            {
                "id": "tile-trusts",
                "title": "Family Trusts & Ownership Assignments",
                "category": "Personal",
                "priority": 1,
                "done": False,
                "archived": False,
                "steps": [
                    {
                        "id": "st-tr-1",
                        "text": "Send assignment draft to counsel (From email: Re: Family Trusts)",
                        "done": True,
                        "auto_checked_at": "2026-11-18T15:00:00Z",
                    },
                    {"id": "st-tr-2", "text": "Review redlines with counsel", "done": False},
                    {"id": "st-tr-3", "text": "Execute final schedules", "done": False},
                ],
            },
            {
                "id": "tile-single",
                "title": "Approve Q4 Budget Memo",
                "category": "Business",
                "priority": 2,
                "done": False,
                "archived": False,
                "steps": [
                    {
                        "id": "st-sg-1",
                        "text": "Email signed Q4 budget approval to finance@example.org",
                        "done": False,
                    }
                ],
            },
        ],
        "proposals": [],
        "auto_checked_log": [
            {
                "id": "ac-stale-arch",
                "tile_id": "tile-arch-old",
                "tile_title": "Completed & Archived Transfer",
                "step_id": "st-arch-1",
                "step_text": "Send transfer paperwork",
                "source": "sent_email",
                "reason": "Sent reply: Transfer paperwork",
                "at": "2026-11-14T18:00:00Z",
            },
            {
                "id": "ac-deleted-ghost",
                "tile_id": "tile-missing",
                "tile_title": "Deleted Tile",
                "step_id": "st-ghost",
                "step_text": "Ghost step",
                "source": "sent_email",
                "reason": "Sent reply: Ghost",
                "at": "2026-11-14T18:05:00Z",
            },
            {
                "id": "ac-trusts-1",
                "tile_id": "tile-trusts",
                "tile_title": "Family Trusts & Ownership Assignments",
                "step_id": "st-tr-1",
                "step_text": "Send assignment draft to counsel (From email: Re: Family Trusts)",
                "source": "sent_email",
                "reason": "Sent reply: Re: Family Trusts",
                "at": "2026-11-18T15:00:00Z",
            },
        ],
    }
    wl_path.write_text(json.dumps(seed_doc), encoding="utf-8")
    comms._WORKING_LIST_SPINE_CACHE.clear()

    # 1) Loading spine prunes archived + deleted ghost notices and enriches active notice metadata
    loaded = comms.load_working_list_spine()
    assert [a["id"] for a in loaded["auto_checked"]] == ["ac-trusts-1"]
    ac0 = loaded["auto_checked"][0]
    assert ac0["clean_step_text"] == "Send assignment draft to counsel"
    assert ac0["done_steps_count"] == 1
    assert ac0["total_steps_count"] == 3
    assert ac0["all_steps_done"] is False

    # Reconcile triggers an auto-check on `tile-single` (1/1 steps -> all_steps_done=True + archive_tile proposal)
    now_ref = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)
    rec = comms.reconcile_working_list_activity(
        sent_event={
            "uid": "uid-bud-1",
            "subject": "Re: Q4 budget approval",
            "to": "finance@example.org",
        },
        live_reconcile=False,
        now_dt=now_ref,
        today=date(2026, 11, 18),
    )
    assert rec["ok"] is True
    ac_by_step = {a["step_id"]: a for a in rec["working_list"]["auto_checked"]}
    assert set(ac_by_step.keys()) == {"st-tr-1", "st-sg-1"}
    assert ac_by_step["st-sg-1"]["all_steps_done"] is True
    assert any(p.get("source_key") == "tile-all-steps-done:tile-single" for p in rec["working_list"]["proposals"])

    # 2) Confirm Done on `ac-trusts-1` -> step stays done=True, auto_check_confirmed=True, notice removed
    conf_res, conf_code = comms.handle_working_list_request(
        {"op": "confirm_autocheck", "autocheck_id": "ac-trusts-1"},
        method="POST",
    )
    assert conf_code == 200 and conf_res["ok"] is True
    tr_tile = next(t for t in conf_res["working_list"]["tiles"] if t["id"] == "tile-trusts")
    assert tr_tile["steps"][0]["done"] is True
    assert tr_tile["steps"][0]["auto_check_confirmed"] is True
    assert "ac-trusts-1" not in {a["id"] for a in conf_res["working_list"]["auto_checked"]}

    # 3) Undo on `st-sg-1` -> unchecks step, drops `tile-all-steps-done:tile-single`, and suppresses same sent email
    sg_ac_id = ac_by_step["st-sg-1"]["id"]
    undo_res, undo_code = comms.handle_working_list_request(
        {"op": "undo_autocheck", "autocheck_id": sg_ac_id},
        method="POST",
    )
    assert undo_code == 200 and undo_res["ok"] is True
    sg_tile = next(t for t in undo_res["working_list"]["tiles"] if t["id"] == "tile-single")
    assert sg_tile["steps"][0]["done"] is False
    assert not any(p.get("source_key") == "tile-all-steps-done:tile-single" for p in undo_res["working_list"]["proposals"])

    # Repeat reconcile with the SAME sent email does NOT re-check the undone step!
    rec_same = comms.reconcile_working_list_activity(
        sent_event={
            "uid": "uid-bud-1",
            "subject": "Re: Q4 budget approval",
            "to": "finance@example.org",
        },
        live_reconcile=False,
        now_dt=now_ref,
        today=date(2026, 11, 18),
    )
    sg_after_same = next(t for t in rec_same["working_list"]["tiles"] if t["id"] == "tile-single")
    assert sg_after_same["steps"][0]["done"] is False
    assert rec_same["working_list"]["auto_checked"] == []

    # A NEW distinct sent email DOES auto-check `st-sg-1` cleanly, and `archive_tile=True` archives it!
    rec_new = comms.reconcile_working_list_activity(
        sent_event={
            "uid": "uid-bud-2",
            "subject": "Final signed Q4 budget approval PDF",
            "to": "finance@example.org",
        },
        live_reconcile=False,
        now_dt=now_ref,
        today=date(2026, 11, 18),
    )
    assert len(rec_new["working_list"]["auto_checked"]) == 1
    new_ac_id = rec_new["working_list"]["auto_checked"][0]["id"]

    arch_res, arch_code = comms.handle_working_list_request(
        {"op": "confirm_autocheck", "autocheck_id": new_ac_id, "archive_tile": True},
        method="POST",
    )
    assert arch_code == 200 and arch_res["ok"] is True
    sg_archived = next(t for t in arch_res["working_list"]["tiles"] if t["id"] == "tile-single")
    assert sg_archived["archived"] is True and sg_archived["done"] is True
    assert arch_res["working_list"]["auto_checked"] == []
    assert not any(p.get("source_key") == "tile-all-steps-done:tile-single" for p in arch_res["working_list"]["proposals"])

    # 4) `confirm_all_autochecks` and manual `toggle_step` cleanup
    rec_more = comms.reconcile_working_list_activity(
        cockpit_events=[
            {
                "kind": "step_completed",
                "tile_id": "tile-trusts",
                "step_id": "st-tr-2",
                "title": "Review redlines with counsel",
            },
            {
                "kind": "step_completed",
                "tile_id": "tile-trusts",
                "step_id": "st-tr-3",
                "title": "Execute final schedules",
            },
        ],
        now_dt=now_ref,
        today=date(2026, 11, 18),
    )
    assert {a["step_id"] for a in rec_more["working_list"]["auto_checked"]} == {"st-tr-2", "st-tr-3"}

    # Manual toggle_step on st-tr-2 removes its auto-check notice immediately
    tog_res, tog_code = comms.handle_working_list_request(
        {"op": "toggle_step", "tile_id": "tile-trusts", "step_idx": 1, "done": False},
        method="POST",
    )
    assert tog_code == 200
    assert [a["step_id"] for a in tog_res["working_list"]["auto_checked"]] == ["st-tr-3"]

    # Confirm all clears remaining notices while keeping st-tr-3 done=True
    all_res, all_code = comms.handle_working_list_request({"op": "confirm_all_autochecks"}, method="POST")
    assert all_code == 200 and all_res["confirmed_count"] == 1
    assert all_res["working_list"]["auto_checked"] == []
    tr_final = next(t for t in all_res["working_list"]["tiles"] if t["id"] == "tile-trusts")
    assert tr_final["steps"][2]["done"] is True and tr_final["steps"][2]["auto_check_confirmed"] is True


def test_autocheck_tray_interactive_ux_in_chromium(
    isolated_comms_env: Path,
) -> None:
    """End-to-end Chromium Playwright test verifying `#wlAutoCheckedStrip` UI:
    - Clear header + `✓ Confirm All & Clear` button.
    - Clickable tile title (`data-wl-focus-tile`) expands the item on The List and shows
      the inline `✓ Auto-checked · Confirm` step badge.
    - Clicking `✓ Confirm Done` clears that row from `#wlAutoCheckedStrip` and clears the
      inline step badge while keeping the step checked (`done=True`).
    - Clicking `✓ Done & Archive` on an `All 1/1 done` item moves the item to `Things Done`
      and hides `#wlAutoCheckedStrip` completely.
    """
    pw = pytest.importorskip("playwright.sync_api")

    wl_path = isolated_comms_env / ".anchor" / "working-list-spine.json"
    wl_path.parent.mkdir(parents=True, exist_ok=True)
    seed_doc = {
        "tiles": [
            {
                "id": "tile-trusts",
                "title": "Family Trusts & Ownership Assignments",
                "category": "Personal",
                "priority": 1,
                "done": False,
                "archived": False,
                "steps": [
                    {
                        "id": "st-tr-1",
                        "text": "Send assignment draft to counsel (From email: Re: Family Trusts)",
                        "done": True,
                        "auto_checked_at": "2026-11-18T15:00:00Z",
                    },
                    {"id": "st-tr-2", "text": "Review redlines with counsel", "done": False},
                ],
            },
            {
                "id": "tile-memo",
                "title": "Finalize Seminar Memo",
                "category": "Teaching",
                "priority": 2,
                "done": False,
                "archived": False,
                "steps": [
                    {
                        "id": "st-mm-1",
                        "text": "Email seminar memo to department@example.net",
                        "done": True,
                        "auto_checked_at": "2026-11-18T15:10:00Z",
                    }
                ],
            },
        ],
        "proposals": [],
        "auto_checked_log": [
            {
                "id": "ac-ui-1",
                "tile_id": "tile-trusts",
                "tile_title": "Family Trusts & Ownership Assignments",
                "step_id": "st-tr-1",
                "step_text": "Send assignment draft to counsel (From email: Re: Family Trusts)",
                "source": "sent_email",
                "reason": "Sent reply: Re: Family Trusts",
                "at": "2026-11-18T15:00:00Z",
            },
            {
                "id": "ac-ui-2",
                "tile_id": "tile-memo",
                "tile_title": "Finalize Seminar Memo",
                "step_id": "st-mm-1",
                "step_text": "Email seminar memo to department@example.net",
                "source": "sent_email",
                "reason": "Sent reply: Seminar memo",
                "at": "2026-11-18T15:10:00Z",
            },
        ],
    }
    wl_path.write_text(json.dumps(seed_doc), encoding="utf-8")
    comms._WORKING_LIST_SPINE_CACHE.clear()
    comms.save_comms_config({"accounts": []})
    comms.save_comms_sync({"calendar_events": [], "email_headers": []})

    css_text = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")
    js_text = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")

    class _RealWlHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/static/high-seat-page.css"):
                data = css_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/static/high-seat-page.js"):
                data = js_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/api/steward/comms"):
                payload, code = comms.handle_comms_get({})
                data = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/high-seat") or self.path == "/":
                html_str = high_seat_page.render_high_seat_page(logged_in=True)
                data = html_str.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self) -> None:
            ln = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            req = json.loads(raw.decode("utf-8") or "{}")
            if self.path.startswith("/api/steward/comms"):
                payload, code = comms.handle_comms_post(req)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "11")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _RealWlHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="domcontentloaded")
                page.wait_for_selector("#wlAutoCheckedStrip .wl-autocheck-card", timeout=8000)

                # Verify clear header, count=2, Confirm All button, 1/2 vs All 1/1 badges, and Done & Archive button
                assert page.locator("#wlAutoCheckedCount").inner_text().strip() == "2"
                assert page.locator("#btnWlConfirmAllAutochecks").is_visible()
                assert page.locator('[data-wl-confirm-autocheck="ac-ui-1"]').is_visible()
                assert page.locator('[data-wl-confirm-archive-autocheck="ac-ui-1"]').count() == 0
                assert page.locator('[data-wl-confirm-archive-autocheck="ac-ui-2"]').is_visible()

                # Click title on ac-ui-1 -> expands `tile-trusts` and shows inline `✓ Auto-checked · Confirm` badge
                page.locator('#wlAutoCheckedStrip [data-wl-focus-tile="tile-trusts"]').click()
                page.wait_for_selector('#wlDetails-tile-trusts', timeout=5000)
                assert page.locator('#wlDetails-tile-trusts [data-wl-confirm-step-autocheck="tile-trusts"]').is_visible()

                # Click `✓ Confirm Done` on ac-ui-1 -> row clears (2 -> 1), step stays checked, inline badge clears!
                page.locator('[data-wl-confirm-autocheck="ac-ui-1"]').click()
                page.wait_for_function(
                    "() => document.querySelectorAll('#wlAutoCheckedStrip .wl-autocheck-card').length === 1",
                    timeout=5000,
                )
                assert page.locator("#wlAutoCheckedCount").inner_text().strip() == "1"
                step_cb = page.locator('#wlDetails-tile-trusts input[type="checkbox"][data-wl-step-idx="0"]')
                assert step_cb.is_checked()
                assert page.locator('#wlDetails-tile-trusts [data-wl-confirm-step-autocheck="tile-trusts"]').count() == 0

                # Click `✓ Done & Archive` on ac-ui-2 -> archives `tile-memo` to Things Done and hides `#wlAutoCheckedStrip`!
                page.locator('[data-wl-confirm-archive-autocheck="ac-ui-2"]').click()
                page.wait_for_function(
                    "() => { var el = document.getElementById('wlAutoCheckedStrip'); return !!el && el.hidden === true; }",
                    timeout=5000,
                )
                assert page.locator("#wlCntArchived").inner_text().strip() == "1"
                assert page.locator("#wlCntAll").inner_text().strip() == "1"
            finally:
                browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
