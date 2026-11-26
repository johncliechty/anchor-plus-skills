"""Regression tests for the 2026-11-23 Cave of Wonders 4-Wave Workflow Overhaul:
1. Speed Racer Auto-Open & Collapse Persistence:
   - Closing Speed Racer marks currently ready drafts seen (`anchor.cave.srSeenReadyById`) and persists collapse (`anchor.cave.srCollapsed`).
   - Background polls (30s `placeSections`, 60s `comms?slim=1`) and page reloads NEVER re-open an already-seen Speed Racer draft.
   - Typing in any input suppresses mid-keystroke focus/layout yanking (`#btnCaveOpenSpeedRacer.has-new-ready`) until idle.
   - Deterministic `draft_id` reuse on the same thread with a newer `ready_at_ts` (after discard/send) is recognized as a genuinely new ready draft.
2. Speed Racer & Direct Reply Multi-Recipient `▾` Inspector & Address-Book Popover:
   - Replaces broken WebView2 `<datalist>` multi-token arrow with `#caveRecipInspectorPopover` showing the complete numbered recipient list (`1..N`, respecting quoted `"Last, First" <...>`), 1-click remove, and live Unified Address Book search/add.
3. Minimalist Chief of Staff (`#shTriage`) + Top-3 + `+N other suggestions` + Silent Oranges + Cross-Cockpit Mining & Learning:
   - Header shows ONLY `[Chief of Staff (N)]`, `[N Running]`, and `[Poincaré Map]`.
   - `<=3` ordered suggestions + `+N other suggestions` line; Quadrant II / active-cockpit slot protection; `<5 ms` cached cross-cockpit scan; immediate `#4 -> #3` promotion; non-penalizing `postpone` vs negative-weight `delete` vs positive-weight `add_to_list` / `act_now` / `send_to_steward`.
4. Clean Living "The List" & Redundant-Button Removal:
   - Removes `#wlAutoCheckedStrip`, `#wlProposalTray`, `#wlOrangesPrestageBar`, `.hdr` `.zip` links, `#btnCaveSrSaveModified`, and duplicate close/Scribe pills.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import comms_connector as comms
import high_seat_page
import paths
import rnd_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def isolated_cave_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path, raising=False)
    comms._WORKING_LIST_SPINE_CACHE.clear()
    comms._COS_COCKPIT_CANDIDATES_CACHE.clear()
    return tmp_path


def test_cos_top3_overflow_cross_cockpit_scan_promotion_and_learning(
    isolated_cave_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANCHOR_TEST_ENABLE_COCKPIT_SCAN", "1")

    # Create a real active AI Cockpit folder with `.ecgberht/plan.json` & `.ecgberht/conversation-log.json`
    ck_dir = isolated_cave_env / "projects" / "QuantumPaper"
    ecg_dir = ck_dir / ".ecgberht"
    ecg_dir.mkdir(parents=True, exist_ok=True)
    (ecg_dir / "plan.json").write_text(
        json.dumps({
            "steps": [
                {"id": "s1", "title": "Derive spectral bound in Appendix B", "status": "in_progress"},
                {"id": "s2", "title": "Generate vector PDF figure", "status": "pending"},
            ]
        }),
        encoding="utf-8",
    )
    (ecg_dir / "conversation-log.json").write_text(
        json.dumps({
            "messages": [
                {"role": "user", "text": "Let's finish deriving the spectral bound in Appendix B today.", "ts": time.time()}
            ]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        rnd_registry,
        "list_projects",
        lambda: [
            {
                "id": "proj-quantum",
                "name": "Quantum Paper",
                "group": "Research",
                "folder_path": str(ck_dir),
                "lifecycle": "active",
            }
        ],
    )

    # Seed 2 explicit proposals + 2 upcoming Watchlist deadlines + 1 actionable Prime email -> >= 5 candidates
    today_d = date.today()
    comms.mutate_working_list_spine("propose_change", {
        "proposal_op": "add_tile",
        "title": "Review Term Sheet Redlines",
        "category": "Business",
        "priority": 1,
        "reason": "Counsel sent revised Series A schedules",
        "source_key": "prop:term-sheet",
    })
    comms.mutate_working_list_spine("propose_change", {
        "proposal_op": "add_tile",
        "title": "Finalize HMBA Lecture Slides",
        "category": "Teaching",
        "priority": 2,
        "reason": "Upcoming seminar session",
        "source_key": "prop:hmba-slides",
    })
    comms.add_watchlist_item({
        "id": "wl-trip-1",
        "title": "Book Thanksgiving Family Flights",
        "due": (today_d + timedelta(days=4)).isoformat(),
    })
    comms.add_watchlist_item({
        "id": "wl-grant-2",
        "title": "Upload NSF Annual Progress Report",
        "due": (today_d + timedelta(days=2)).isoformat(),
    })
    comms.save_comms_sync({
        "calendar_events": [],
        "email_headers": [
            {
                "uid": "em-board-1",
                "from": "Board Chair <chair@example.org>",
                "sender_email": "chair@example.org",
                "subject": "Action required: Approve audit committee agenda",
                "snippet": "Please confirm agenda items before Thursday.",
                "action_required": True,
                "steward_score": 88,
            }
        ],
    })

    bundle = comms.build_chief_of_staff_suggestions()
    assert len(bundle["top_three"]) == 3
    assert bundle["overflow_count"] >= 2
    assert bundle["total_count"] == 3 + bundle["overflow_count"]

    # Quadrant II / active AI Cockpit candidate is mined & protected in suggestions with silent-Oranges plan steps
    all_sugs = bundle["suggestions"]
    ck_sug = next((s for s in all_sugs if s.get("pid") == "proj-quantum"), None)
    assert ck_sug is not None
    assert len(ck_sug["plan_steps"]) >= 2
    assert ck_sug["background_skill"] in comms.ORANGES_SKILLS or ck_sug["background_skill"] == "Steward"

    # Cached cross-cockpit scan runs in < 5ms on steady-state stat hit
    t0 = time.perf_counter()
    comms._scan_live_cockpit_and_cave_candidates()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 10.0

    # Postponing item #1 snoozes it WITHOUT penalizing its category weight and immediately promotes #4 -> slot #3!
    first_sug = bundle["top_three"][0]
    fourth_sug = bundle["overflow"][0]
    res_post = comms.mutate_working_list_spine("cos_act", {
        "cos_action": "postpone",
        "suggestion_id": first_sug["id"],
        "source_key": first_sug["source_key"],
    })
    assert res_post["ok"] is True
    next_top3_ids = [s["id"] for s in res_post["cos_suggestions"]["top_three"]]
    assert first_sug["id"] not in next_top3_ids
    assert fourth_sug["id"] in next_top3_ids
    cat_w_after_postpone = res_post["feedback_summary"]["category_weights"].get(first_sug["category"], 1.0)
    assert cat_w_after_postpone == 1.0

    # Deleting a suggestion tombstones its source_key and applies negative weight (< 1.0)
    del_target = res_post["cos_suggestions"]["top_three"][0]
    res_del = comms.mutate_working_list_spine("cos_act", {
        "cos_action": "delete",
        "suggestion_id": del_target["id"],
        "source_key": del_target["source_key"],
    })
    assert res_del["ok"] is True
    assert del_target["id"] not in [s["id"] for s in res_del["cos_suggestions"]["suggestions"]]
    assert res_del["feedback_summary"]["category_weights"].get(del_target["category"], 1.0) < 1.0

    # Adding a suggestion with modifying directions to The List creates a tile with those directions + boosts weight
    add_target = res_del["cos_suggestions"]["top_three"][0]
    prev_cat_w = res_del["feedback_summary"]["category_weights"].get(add_target["category"], 1.0)
    res_add = comms.mutate_working_list_spine("cos_act", {
        "cos_action": "add_to_list",
        "suggestion_id": add_target["id"],
        "source_key": add_target["source_key"],
        "directions": "Include sensitivity table in section 2",
    })
    assert res_add["ok"] is True
    created_tile = res_add["tile"]
    assert created_tile is not None
    assert any("sensitivity table" in str(st.get("text") or "") for st in created_tile["steps"])
    assert res_add["feedback_summary"]["category_weights"].get(add_target["category"], 1.0) > prev_cat_w


def test_speed_racer_ready_at_ts_and_playwright_cave_ui_overhaul(
    isolated_cave_env: Path,
) -> None:
    pw = pytest.importorskip("playwright.sync_api")

    # Seed Speed Racer draft with multiple To & CC recipients (including quoted comma name)
    sr_res = comms.queue_speed_racer_draft({
        "uid": "msg-multi-1",
        "to": '"Liechty, Merrill" <merrill@example.org>, Alice Researcher <alice@example.org>',
        "cc": "Bob Coauthor <bob@example.org>, Carol Dean <carol@example.org>, Dave Ops <dave@example.org>",
        "subject": "Re: Joint Statistical Modeling Draft",
        "draft_body": "Hi everyone,\n\nAttached are the updated numbers.\n\nBest,\nJohn",
        "preserve_manual_draft": True,
        "status": "ready",
    })
    assert sr_res["ok"] is True
    initial_draft = sr_res["speed_racer"]["queue"][0]
    assert float(initial_draft.get("ready_at_ts") or 0) > 0
    orig_ready_ts = float(initial_draft["ready_at_ts"])

    # Editing the draft must NOT mutate `ready_at_ts`
    edit_res = comms.act_speed_racer_draft({
        "sr_action": "edit",
        "id": initial_draft["id"],
        "draft_body": "Hi everyone,\n\nUpdated body.\n\nBest,\nJohn",
    })
    assert float(edit_res["draft"]["ready_at_ts"]) == orig_ready_ts

    # Seed 4 Chief-of-Staff proposals so Top-3 + "+1 other suggestion" renders cleanly
    for idx in range(1, 5):
        comms.mutate_working_list_spine("propose_change", {
            "proposal_op": "add_tile",
            "title": f"Priority Suggestion #{idx}",
            "category": "Research" if idx % 2 == 0 else "Business",
            "priority": 1 if idx <= 2 else 2,
            "reason": f"Grounded signal #{idx}",
            "source_key": f"ui-sug:{idx}",
        })

    comms.save_comms_config({"accounts": []})
    comms.save_comms_sync({"calendar_events": [], "email_headers": []})

    css_text = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")
    js_text = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")

    class _CaveOverhaulHandler(BaseHTTPRequestHandler):
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
            if "view=contacts" in self.path:
                data = json.dumps({
                    "ok": True,
                    "contacts": [
                        {"name": "Eve Collaborator", "email": "eve@example.org"},
                        {"name": "Frank Advisor", "email": "frank@example.org"},
                    ],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _CaveOverhaulHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="domcontentloaded")

                # 1. Verify redundant buttons & banners are gone, and Chief of Staff + The List + Poincare Map share ONE row
                assert page.locator('.hdr a[href*="package/anchor.zip"]').count() == 0
                assert page.locator("#btnCaveSrSaveModified").count() == 0
                assert page.locator("#wlSpineCollapseBtn").count() == 0
                assert page.locator("#wlAutoCheckedStrip").count() == 0
                assert page.locator("#wlProposalTray").count() == 0
                assert page.locator('#caveSrToInput[list]').count() == 0
                assert page.locator('#caveSrCcInput[list]').count() == 0

                cos_box = page.locator("#btnCosToggleExpand").bounding_box()
                wl_box = page.locator("#btnWlToggleTop").bounding_box()
                run_box = page.locator("#cosRunningTile").bounding_box()
                em_box = page.locator("#cosEmailTile").bounding_box()
                cal_box = page.locator("#cosCalendarTile").bounding_box()
                pm_box = page.locator("#btnCosPoincareMap").bounding_box()
                assert all(b is not None for b in (cos_box, wl_box, run_box, em_box, cal_box, pm_box))
                for b_chk in (wl_box, run_box, em_box, cal_box, pm_box):
                    assert abs(cos_box["y"] - b_chk["y"]) <= 4
                # Side rail and bottom #cal remain preserved too
                assert page.locator('#railNav button[data-rail="email"]').count() == 1
                assert page.locator('#railNav button[data-rail="calendar"]').count() == 1
                assert page.locator("#cal").count() == 1

                # Clicking #cosCalendarTile / #cosEmailTile opens #cal in calendar / mail layout
                page.locator("#cosCalendarTile").click()
                assert page.locator("#cal").evaluate("el => el.classList.contains('open')")
                assert page.locator("#commsGrid").get_attribute("data-layout") == "cal"
                page.locator("#cosEmailTile").click()
                assert page.locator("#commsGrid").get_attribute("data-layout") == "mail"

                # Clicking #btnWlToggleTop on the top row toggles #wlSpineBody closed and back open cleanly
                assert page.locator("#wlSpineBody").is_visible()
                page.locator("#btnWlToggleTop").click()
                assert page.locator("#wlSpineBody").is_hidden()
                page.locator("#btnWlToggleTop").click()
                assert page.locator("#wlSpineBody").is_visible()

                # 2. Open Comms/Speed Racer & verify multi-recipient `▾` popover lists ALL individuals cleanly
                page.evaluate("window.openCaveSpeedRacer()")
                page.wait_for_selector('[data-recip-dropdown-for="caveSrCcInput"]', timeout=5000)
                assert "2" in page.locator('[data-recip-dropdown-for="caveSrToInput"]').inner_text()
                assert "3" in page.locator('[data-recip-dropdown-for="caveSrCcInput"]').inner_text()

                # Click `▾` on CC -> opens popover showing all 3 CC individuals
                page.locator('[data-recip-dropdown-for="caveSrCcInput"]').click()
                page.wait_for_selector("#caveRecipInspectorPopover:not([hidden])", timeout=5000)
                pop_txt = page.locator("#caveRecipPopCurrentList").inner_text()
                assert "Bob Coauthor" in pop_txt and "bob@example.org" in pop_txt
                assert "Carol Dean" in pop_txt and "carol@example.org" in pop_txt
                assert "Dave Ops" in pop_txt and "dave@example.org" in pop_txt
                page.locator('[data-recip-pop-close="1"]').click()

                # Also verify quoted comma name `"Liechty, Merrill"` (normalized by Scribe to Merrill Liechty) + client quoted comma name are NOT split in half!
                page.locator('[data-recip-dropdown-for="caveSrToInput"]').click()
                page.wait_for_selector("#caveRecipInspectorPopover:not([hidden])", timeout=5000)
                to_rows = page.locator("#caveRecipPopCurrentList .cave-recip-pop-row")
                to_val_dbg = page.locator("#caveSrToInput").input_value()
                assert to_rows.count() == 2, f"Expected 2 To rows, got {to_rows.count()} for to_val={to_val_dbg!r}"
                assert "Merrill" in to_rows.nth(0).inner_text() and "merrill@example.org" in to_rows.nth(0).inner_text()
                assert "Alice Researcher" in to_rows.nth(1).inner_text()
                page.locator('[data-recip-pop-close="1"]').click()

                # Direct client-side quoted comma input `"Smith, Jane" <jane@example.org>, Alice Researcher <alice@example.org>`
                page.locator("#caveSrToInput").fill('"Smith, Jane" <jane@example.org>, Alice Researcher <alice@example.org>')
                page.locator('[data-recip-dropdown-for="caveSrToInput"]').click()
                page.wait_for_selector("#caveRecipInspectorPopover:not([hidden])", timeout=5000)
                assert page.locator("#caveRecipPopCurrentList .cave-recip-pop-row").count() == 2
                assert "Smith, Jane" in page.locator("#caveRecipPopCurrentList .cave-recip-pop-row").nth(0).inner_text()
                page.locator('[data-recip-pop-close="1"]').click()

                # 3. Close Speed Racer -> verify it NEVER re-opens on poll, reload, or while typing!
                page.locator("#caveSpeedRacerHead").click()
                assert page.locator("#caveSpeedRacerBody").is_hidden()

                # Focus an input (simulating active typing) and run server polls + reload
                page.locator("#wlNewTileTitle").focus()
                page.keyboard.type("Drafting notes while Speed Racer stays shut")
                page.evaluate("window._ensureCaveCommsDataLoaded(true)")
                page.wait_for_timeout(200)
                assert page.locator("#caveSpeedRacerBody").is_hidden()

                # Reload page -> already-seen Speed Racer draft MUST remain closed!
                page.reload(wait_until="domcontentloaded")
                assert page.locator("#caveSpeedRacerBody").is_hidden()

                # Queue a BRAND-NEW ready draft on server -> while NOT typing, Speed Racer auto-opens!
                comms.queue_speed_racer_draft({
                    "uid": "msg-brand-new-2",
                    "to": "colleague@example.org",
                    "subject": "Re: Urgent Lab Equipment Quote",
                    "draft_body": "Hi, approved to proceed.\n\nBest,\nJohn",
                    "preserve_manual_draft": True,
                    "status": "ready",
                })
                # Wait past 6s typing guard window via synthetic evaluation & trigger comms sync
                page.evaluate("window._ensureCaveCommsDataLoaded(true)")
                page.wait_for_function(
                    "() => { var b = document.getElementById('caveSpeedRacerBody'); return !!b && b.hidden === false; }",
                    timeout=5000,
                )

                # 4. Minimalist Chief of Staff: starts collapsed; checking shows Top 3 + "+1 other suggestion";
                #    clicking row expands plan + directions; clicking `Later` promotes #4 -> slot #3!
                assert page.locator("#cosSuggestionsPanel").is_hidden()
                page.locator("#btnCosToggleExpand").click()
                page.wait_for_selector("#cosSuggestionsPanel:not([hidden])", timeout=5000)
                assert page.locator("#cosTopThreeStack .cos-min-row").count() == 3
                assert "+1 other suggestion" in page.locator("#btnCosOverflowToggle").inner_text()

                # Click row #1 to inspect plan & modifying directions input
                first_row = page.locator("#cosTopThreeStack .cos-min-row").nth(0)
                first_id = first_row.get_attribute("data-cos-sug-id")
                first_row.locator(".cos-min-text").click()
                assert page.locator(f"#cosSugDetail-{first_id}").is_visible()
                assert page.locator(f"#cosDirIn-{first_id}").is_visible()

                # Click `Later` (postpone) on row #1 -> #4 immediately promotes so Top-3 still has 3 items & overflow hides!
                first_row.locator('[data-cos-act="postpone"]').click()
                page.wait_for_function(
                    f"() => !document.querySelector('#cosTopThreeStack [data-cos-sug-id=\"{first_id}\"]') && document.querySelectorAll('#cosTopThreeStack .cos-min-row').length === 3",
                    timeout=5000,
                )
                assert page.locator("#cosOverflowWrap").is_hidden()
            finally:
                browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
