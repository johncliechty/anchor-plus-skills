"""Wave 3 tests (2026-11-20): Single-Send AI Cockpit Dictation & Crash-Durable Unified Composer Drafts.

Covers:
1. Plain Enter / Send button = single submit, Shift+Enter = newline across all 5 composer surfaces:
   - /steward/v1 full AI cockpit ([data-say])
   - /steward/v1?view=tile Cave expanded initiative tile ([data-say], dialogue-only framing)
   - #say Cave right-rail steward composer
   - #exSay Star Chart steward composer
   - #caveDlgStewardDirectionsInput Cave email Scribe/Steward instruction box
2. Monotonic dictation_epoch fencing of late /api/steward/dictate responses after Send and [data-clear-draft] Clear.
3. Durable, cross-process-locked, bounded (<= 500) server-side client_msg_id idempotent deduplication across
   steward_routes / steward_engine, high_seat_say, dictation_engine, and comms_connector.
4. Crash-durable atomic disk composer drafts (/api/steward/drafts) unified across full cockpit & view=tile,
   real OS two-process concurrency, strict 256 KB payload refusal (413 BOUND_EXCEEDED_REFUSAL),
   escape-attempt path containment (403 PATH_CONTAINMENT_REFUSAL), keepalive unload flush, and [data-clear-draft].
5. Real 5-row failure-state table on /api/steward/drafts (503, 504, 400, 500 UNKNOWN, 200 EMPTY; UNKNOWN != EMPTY).
"""
from __future__ import annotations

import base64
import contextlib
import datetime
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Import every Wave 3 modified Python module for delta-coverage verification
import anchor_gui  # noqa: E402
import campaign_page  # noqa: E402
import chamber_enforcement  # noqa: E402
import comms_connector  # noqa: E402
import high_seat_page  # noqa: E402
import paths  # noqa: E402
import rnd_registry  # noqa: E402
import route_table  # noqa: E402
from steward_cockpit import dictation_engine, steward_engine, steward_routes  # noqa: E402

TEST_CRED = "placeholder"
FAKE_WAV_B64 = base64.b64encode(
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00@\x1f\x00\x00\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
).decode("ascii")


def _http_json(
    url: str,
    method: str = "GET",
    body: dict | str | bytes | None = None,
    auth_cred: str | None = TEST_CRED,
    extra_headers: dict | None = None,
) -> tuple[int, dict]:
    hdrs: dict[str, str] = {}
    if auth_cred:
        hdrs["Authorization"] = f"Bearer {auth_cred}"
        hdrs["X-Anchor-Token"] = auth_cred
    data_bytes: bytes | None = None
    if body is not None:
        if isinstance(body, bytes):
            data_bytes = body
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            data_bytes = body.encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        else:
            data_bytes = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(url, data=data_bytes, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {"_raw": raw}
        return exc.code, parsed


@contextlib.contextmanager
def _ephemeral_anchor_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Boot a hermetic ephemeral Anchor HTTP server on an OS-assigned port (!= 8777) backed by tmp_path."""
    steward_routes.ENGINES.clear()
    data_dir = tmp_path / "anchor_data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    (data_dir / "domains").mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (data_dir / "DASHBOARD.md").write_text("# Dashboard\n", encoding="utf-8")
    (data_dir / "PROJECTS.md").write_text("# Projects\n", encoding="utf-8")
    (data_dir / "INBOX.md").write_text("# Inbox\n", encoding="utf-8")
    (data_dir / "CANCELLED.md").write_text("# Cancelled\n", encoding="utf-8")
    (data_dir / "SAVED_FOR_LATER.md").write_text("# Saved\n", encoding="utf-8")

    # Seed an isolated Campaign root + a sample project/effort ("mba" / "lectures")
    campaign_dir = tmp_path / "Campaign"
    (campaign_dir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "cave" / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "Cave of Wonders" / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "ECGBERHT.md").write_text("# Goal\nStar Chart Strategic Goals\n", encoding="utf-8")
    (campaign_dir / "cave" / "ECGBERHT.md").write_text("# Goal\nCave of Wonders Steward\n", encoding="utf-8")
    (campaign_dir / "Cave of Wonders" / "ECGBERHT.md").write_text("# Goal\nCave of Wonders Steward\n", encoding="utf-8")
    (campaign_dir / "roadmap.json").write_text(
        json.dumps(
            {
                "goal": "Star Chart Strategic Goals",
                "roadmap_projection": [
                    {
                        "id": "g-mba",
                        "name": "MBA Teaching Fall 2026",
                        "kind": "goal",
                        "tier": 1,
                        "status": "in_progress",
                        "done_when": "Deliver Lectures 4-6",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    proj_dir = tmp_path / "mba-project"
    effort_dir = proj_dir / "lectures"
    (proj_dir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (effort_dir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    for d in (proj_dir, effort_dir):
        (d / "ECGBERHT.md").write_text("# Goal\nRevise Lecture 4 confidence intervals\n", encoding="utf-8")
        (d / "roadmap.json").write_text(
            json.dumps(
                {
                    "goal": "Revise Lecture 4 confidence intervals",
                    "roadmap_projection": [
                        {"id": "step-1", "name": "Draft Lecture 4 slides", "status": "in_progress"}
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Seed two unread inbox emails in .anchor/comms-sync.json so #caveDlgStewardDirectionsInput is live & visible
    sync_doc = {
        "synced_at": "2026-11-20 10:15",
        "calendar_events": [],
        "email_headers": [
            {
                "uid": "mail-w3-101",
                "account_id": "inst_365",
                "account_badge": "Institutional 365",
                "from": "Colleague <colleague@example.com>",
                "sender_email": "colleague@example.com",
                "to": "owner@example.com",
                "subject": "Lecture 4 Empirical Dataset Review",
                "date": "2026-11-20T10:15:00Z",
                "snippet": "Please confirm whether the sample size slide moves earlier.",
                "body": "Hi,\nPlease confirm whether the sample size slide moves before confidence intervals.\nThanks!",
                "is_read": False,
                "body_preloaded": True,
            },
            {
                "uid": "mail-w3-102",
                "account_id": "inst_365",
                "account_badge": "Institutional 365",
                "from": "Colleague 2 <colleague2@example.com>",
                "sender_email": "colleague2@example.com",
                "to": "owner@example.com",
                "subject": "Lecture 5 Follow-up",
                "date": "2026-11-20T10:20:00Z",
                "snippet": "Quick check on Lecture 5.",
                "body": "Hi,\nQuick check on Lecture 5.\nThanks!",
                "is_read": False,
                "body_preloaded": True,
            },
        ],
        "sent_email_headers": [],
    }
    sync_path = data_dir / ".anchor" / "comms-sync.json"
    paths.atomic_write_json(sync_path, sync_doc)
    comms_connector._invalidate_cached_json_file(sync_path)

    monkeypatch.setenv("ANCHOR_TOKEN", TEST_CRED)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    steward_dispatch_calls: list[tuple] = []
    stub_cave_eng = types.SimpleNamespace(
        say=lambda prompt, **kw: (steward_dispatch_calls.append((prompt, kw)), {"ok": True})[1]
    )
    monkeypatch.setattr(
        comms_connector,
        "_CAVE_STEWARD_DISPATCH_HOOK",
        stub_cave_eng,
        raising=False,
    )
    monkeypatch.setattr(
        comms_connector,
        "generate_steward_reply_draft",
        lambda *a, **kw: {"ok": True, "body": "Stub Scribe reply."},
        raising=False,
    )
    monkeypatch.setattr(anchor_gui, "_campaign_dir", lambda: campaign_dir)
    monkeypatch.setitem(steward_routes.CONFIG, "fake", True)

    reg_camp = anchor_gui.select_existing_project("Campaign", str(campaign_dir))
    reg_mba = anchor_gui.select_existing_project("MBA Teaching AI", str(proj_dir))
    pid_camp = reg_camp["entry"]["id"]
    pid_mba = reg_mba["entry"]["id"]

    steward_routes.set_draft_storage_available(True)
    steward_routes.set_draft_lock_timeout(5.0)
    dictation_engine.set_dictation_backend_available(True)
    dictation_engine.set_dictation_transcribe_hook(None)

    httpd = anchor_gui.make_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    assert port != 8777, "Ephemeral test server must never bind live port 8777"
    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()
    try:
        yield {
            "base_url": f"http://127.0.0.1:{port}",
            "port": port,
            "data_dir": data_dir,
            "campaign_dir": campaign_dir,
            "proj_dir": proj_dir,
            "effort_dir": effort_dir,
            "pid_camp": pid_camp,
            "pid_mba": pid_mba,
            "steward_dispatch_calls": steward_dispatch_calls,
        }
    finally:
        dictation_engine.set_dictation_transcribe_hook(None)
        dictation_engine.set_dictation_backend_available(True)
        steward_routes.set_draft_storage_available(True)
        steward_routes.set_draft_lock_timeout(5.0)
        httpd.shutdown()
        httpd.server_close()
        srv_thread.join(timeout=5)
        for eng in list(steward_routes.ENGINES.values()):
            try:
                eng.stop()
            except Exception:
                pass
        steward_routes.ENGINES.clear()


def test_w3_enter_newline_ctrl_enter_submit_five_surfaces(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Shift+Enter inserts newline (never submits) and plain Enter / Send submits once across all 5 composer surfaces."""
    pw_mod = pytest.importorskip("playwright.sync_api")
    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]

        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1360, "height": 900},
                extra_http_headers={"Authorization": f"Bearer {TEST_CRED}", "X-Anchor-Token": TEST_CRED},
            )
            page = context.new_page()
            page.add_init_script(f"localStorage.setItem('anchor_token', {json.dumps(TEST_CRED)});")

            say_posts: list[dict] = []
            comms_posts: list[dict] = []

            def _track_req(req):
                if req.method == "POST":
                    if "/api/steward/say" in req.url:
                        try:
                            say_posts.append(json.loads(req.post_data or "{}"))
                        except Exception:
                            pass
                    elif "/api/steward/comms" in req.url:
                        try:
                            comms_posts.append(json.loads(req.post_data or "{}"))
                        except Exception:
                            pass

            page.on("request", _track_req)

            # 1) Surface 1: Full AI Cockpit (/steward/v1)
            page.goto(f"{base}/steward/v1?project={pid_mba}&effort=lectures", wait_until="domcontentloaded")
            box = page.locator("[data-say]")
            box.wait_for(state="visible")
            assert page.locator("[data-clear-draft]").is_visible()
            box.click()
            box.type("First cockpit line")
            box.press("Shift+Enter")
            box.type("Second cockpit line")
            assert box.input_value() == "First cockpit line\nSecond cockpit line"
            assert len(say_posts) == 0, "Shift+Enter must insert a newline without submitting in /steward/v1"

            box.press("Enter")
            page.wait_for_function("() => document.querySelector('[data-say]').value === '' && !document.querySelector('[data-send]').disabled")
            assert len(say_posts) == 1
            assert say_posts[0]["text"] == "First cockpit line\nSecond cockpit line"
            assert say_posts[0].get("client_msg_id", "").startswith("say-")

            # Explicit Send button also submits once with a fresh client_msg_id
            box.click()
            box.type("Explicit button send")
            page.locator("[data-send]").click()
            page.wait_for_function("() => document.querySelector('[data-say]').value === '' && !document.querySelector('[data-send]').disabled")
            assert len(say_posts) == 2
            assert say_posts[1]["client_msg_id"] != say_posts[0]["client_msg_id"]

            # 2) Surface 2: Cave Expanded Initiative Tile (/steward/v1?view=tile)
            say_posts.clear()
            page.goto(f"{base}/steward/v1?project={pid_mba}&effort=lectures&view=tile", wait_until="domcontentloaded")
            tile_box = page.locator("[data-say]")
            tile_box.wait_for(state="visible")
            assert page.locator("[data-clear-draft]").is_visible()
            # Tile framing rule: Plan, Status, goalbar, and top bar MUST stay hidden even on wide 1360px viewport
            for hidden_sel in (".bar", ".leftcol", ".railtab", ".goalbar", ".rightcol", ".statustab"):
                assert not page.locator(hidden_sel).is_visible(), f"{hidden_sel} must be hidden in view=tile"

            tile_box.click()
            tile_box.type("Tile alpha")
            tile_box.press("Shift+Enter")
            tile_box.type("Tile beta")
            assert tile_box.input_value() == "Tile alpha\nTile beta"
            assert len(say_posts) == 0, "Shift+Enter must insert a newline without submitting in /steward/v1?view=tile"
            tile_box.press("Enter")
            page.wait_for_function("() => document.querySelector('[data-say]').value === '' && !document.querySelector('[data-send]').disabled")
            assert len(say_posts) == 1
            assert say_posts[0]["text"] == "Tile alpha\nTile beta"

            # 3) Surface 3 (#say Cave right-rail) & Surface 5 (#caveDlgStewardDirectionsInput Cave email bar)
            say_posts.clear()
            comms_posts.clear()
            page.goto(f"{base}/high-seat?comms_open=1", wait_until="domcontentloaded")
            cave_say = page.locator("#say")
            cave_say.wait_for(state="visible")
            assert page.locator("#clearSayDraftBtn[data-clear-draft]").is_visible()
            cave_say.click()
            cave_say.type("Cave thought one")
            cave_say.press("Shift+Enter")
            cave_say.type("Cave thought two")
            assert cave_say.input_value() == "Cave thought one\nCave thought two"
            assert len(say_posts) == 0, "Shift+Enter must insert a newline without submitting in Cave #say"
            cave_say.press("Enter")
            page.wait_for_function("() => document.querySelector('#say').value === ''")
            assert len(say_posts) == 1
            assert say_posts[0]["text"] == "Cave thought one\nCave thought two"
            assert say_posts[0].get("client_msg_id", "").startswith("say-")

            # Surface 5: #caveDlgStewardDirectionsInput
            page.wait_for_selector("#caveEmailDialoguePane:not([hidden])", timeout=10000)
            page.click('.cave-mail-card[data-mail-uid="mail-w3-101"]')
            em_input = page.locator("#caveDlgStewardDirectionsInput")
            em_input.wait_for(state="visible")
            assert page.locator("#btnCaveDlgClearDirectionsDraft[data-clear-draft]").is_visible()
            em_input.click()
            em_input.fill("")
            em_input.type("Scribe instruction line 1")
            em_input.press("Shift+Enter")
            em_input.type("Scribe instruction line 2")
            assert em_input.input_value() == "Scribe instruction line 1\nScribe instruction line 2"
            em_actions = [c for c in comms_posts if c.get("action") == "email_steward_action"]
            assert len(em_actions) == 0, "Shift+Enter must insert a newline without submitting in #caveDlgStewardDirectionsInput"

            em_input.press("Enter")
            page.wait_for_function("() => document.getElementById('caveDlgStewardDirectionsInput').value === ''")
            em_actions = [c for c in comms_posts if c.get("action") == "email_steward_action"]
            assert len(em_actions) == 1
            assert em_actions[0]["comment"] == "Scribe instruction line 1\nScribe instruction line 2"
            assert em_actions[0].get("client_msg_id", "").startswith("emsa-")

            # 4) Surface 4: Star Chart steward composer (#exSay)
            pid_camp = env["pid_camp"]
            say_posts.clear()
            page.goto(f"{base}/project/{pid_camp}", wait_until="domcontentloaded")
            star_say = page.locator("#exSay")
            star_say.wait_for(state="visible")
            assert page.locator("#exClearDraft[data-clear-draft]").is_visible()
            star_say.click()
            star_say.type("Star Chart goal note 1")
            star_say.press("Shift+Enter")
            star_say.type("Star Chart goal note 2")
            assert star_say.input_value() == "Star Chart goal note 1\nStar Chart goal note 2"
            assert len(say_posts) == 0, "Shift+Enter must insert a newline without submitting in Star Chart #exSay"
            star_say.press("Enter")
            page.wait_for_function("() => document.querySelector('#exSay').value === '' && !document.querySelector('#exSend').disabled")
            assert len(say_posts) == 1
            assert say_posts[0]["text"] == "Star Chart goal note 1\nStar Chart goal note 2"

            context.close()
            browser.close()


def test_w3_dictation_epoch_fences_late_chunks(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Late /api/steward/dictate responses from a prior dictation_epoch are discarded after Send or Clear."""
    pw_mod = pytest.importorskip("playwright.sync_api")
    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]

        release_evt = threading.Event()
        entered_evt = threading.Event()

        def _slow_transcribe_hook(_raw_bytes: bytes) -> str:
            entered_evt.set()
            release_evt.wait(timeout=5.0)
            return "STALE LATE CHUNK FROM PRIOR EPOCH"

        dictation_engine.set_dictation_transcribe_hook(_slow_transcribe_hook)

        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 860},
                extra_http_headers={"Authorization": f"Bearer {TEST_CRED}", "X-Anchor-Token": TEST_CRED},
            )
            page = context.new_page()
            page.add_init_script(f"localStorage.setItem('anchor_token', {json.dumps(TEST_CRED)});")

            for url, pre_click_sel, box_sel, send_sel, clear_sel in [
                (
                    f"{base}/steward/v1?project={pid_mba}&effort=lectures",
                    None,
                    "[data-say]",
                    "[data-send]",
                    "[data-clear-draft]",
                ),
                (
                    f"{base}/steward/v1?project={pid_mba}&effort=lectures&view=tile",
                    None,
                    "[data-say]",
                    "[data-send]",
                    "[data-clear-draft]",
                ),
                (f"{base}/project/{pid_camp}", None, "#exSay", "#exSend", "#exClearDraft"),
                (
                    f"{base}/high-seat?comms_open=1",
                    None,
                    "#say",
                    "#sendBtn",
                    "#clearSayDraftBtn[data-clear-draft]",
                ),
                (
                    f"{base}/high-seat?comms_open=1",
                    '.cave-mail-card[data-mail-uid="mail-w3-101"]',
                    "#caveDlgStewardDirectionsInput",
                    "#btnCaveDlgSendStewardAction",
                    "#btnCaveDlgClearDirectionsDraft[data-clear-draft]",
                ),
            ]:
                page.goto(url, wait_until="domcontentloaded")
                if pre_click_sel:
                    page.wait_for_selector("#caveEmailDialoguePane:not([hidden])", timeout=10000)
                    page.click(pre_click_sel)
                box = page.locator(box_sel)
                box.wait_for(state="visible")

                # Phase 1: Send bumps dictation_epoch and fences in-flight transcribe
                entered_evt.clear()
                release_evt.clear()
                box.fill("Confirmed instruction")
                page.evaluate(
                    f"""([sel, wav]) => {{
                        const el = document.querySelector(sel);
                        window.__lateProm = el._dispatchFencedTranscribe(wav);
                    }}""",
                    [box_sel, FAKE_WAV_B64],
                )
                assert entered_evt.wait(timeout=4.0), f"Transcribe hook did not receive in-flight request on {box_sel}"

                # Submit while prior-epoch transcribe is still in flight
                page.locator(send_sel).click()
                page.wait_for_function(f"() => document.querySelector({json.dumps(box_sel)}).value === ''")
                epoch_after_send = int(box.get_attribute("data-dictation-epoch") or "0")
                assert epoch_after_send >= 1

                # Now let the slow prior-epoch transcribe finish
                release_evt.set()
                res = page.evaluate("() => window.__lateProm")
                assert res["fenced"] is True
                assert box.input_value() == "", f"Late chunk repopulated {box_sel} after Send on {url}"

                # Phase 2: [data-clear-draft] Clear bumps dictation_epoch and fences in-flight transcribe
                entered_evt.clear()
                release_evt.clear()
                box.fill("Unsent words to clear")
                page.evaluate(
                    f"""([sel, wav]) => {{
                        const el = document.querySelector(sel);
                        window.__lateClearProm = el._dispatchFencedTranscribe(wav);
                    }}""",
                    [box_sel, FAKE_WAV_B64],
                )
                assert entered_evt.wait(timeout=4.0)
                page.locator(clear_sel).click()
                assert box.input_value() == ""
                epoch_after_clear = int(box.get_attribute("data-dictation-epoch") or "0")
                assert epoch_after_clear > epoch_after_send
                release_evt.set()
                res_clear = page.evaluate("() => window.__lateClearProm")
                assert res_clear["fenced"] is True
                assert box.input_value() == "", f"Late chunk repopulated {box_sel} after Clear on {url}"

            context.close()
            browser.close()


def test_w3_client_msg_id_repeat_deduplication(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Identical client_msg_id repeats across steward_routes/engine, high_seat_say, dictation_engine, and comms_connector
    never create duplicate turns, model calls, transcriptions, or Speed Racer queue items."""
    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]
        effort_dir = env["effort_dir"]
        data_dir = env["data_dir"]

        # 1) /api/steward/say idempotency
        msg_id = "say-dedup-001"
        payload = {"pid": pid_mba, "dir": "lectures", "text": "Deduplicate this cockpit turn", "client_msg_id": msg_id}
        st1, r1 = _http_json(f"{base}/api/steward/say", method="POST", body=payload)
        st2, r2 = _http_json(f"{base}/api/steward/say", method="POST", body=payload)
        st3, r3 = _http_json(f"{base}/api/steward/say", method="POST", body=payload)
        assert st1 == 200 and r1["ok"] is True and r1.get("deduplicated") is False
        assert st2 == 200 and r2["ok"] is True and r2.get("deduplicated") is True
        assert st3 == 200 and r3["ok"] is True and r3.get("deduplicated") is True

        # Wait briefly for background turn thread to finish and inspect emitted events (single john event!)
        time.sleep(0.25)
        st_evs, evs_doc = _http_json(f"{base}/api/steward/events?pid={pid_mba}&dir=lectures&since=0")
        assert st_evs == 200
        john_evs = [e for e in (evs_doc.get("events") or []) if e.get("t") == "john"]
        assert len(john_evs) == 1, f"Expected 1 john event, got {len(john_evs)}: {evs_doc}"
        assert john_evs[0]["text"] == "Deduplicate this cockpit turn"

        # Also verify direct Engine.say(..., client_msg_id=...) idempotency
        direct_eng = steward_engine.Engine(str(effort_dir), fake=True)
        try:
            d1 = direct_eng.say("Direct engine idempotency check", client_msg_id="eng-direct-001")
            d2 = direct_eng.say("Direct engine idempotency check", client_msg_id="eng-direct-001")
            assert d1["ok"] is True and d1.get("deduplicated") is False
            assert d2["ok"] is True and d2.get("deduplicated") is True
        finally:
            direct_eng.stop()

        # Ring bound check (<= 500 entries)
        for i in range(525):
            steward_engine.record_client_msg_id_receipt(
                str(effort_dir), f"ring-id-{i}", {"ok": True, "seq": i}, cdir=effort_dir
            )
        ring_doc = json.loads((effort_dir / ".ecgberht" / "client-msg-ids.json").read_text(encoding="utf-8"))
        assert len(ring_doc["scopes"][str(effort_dir)]) == steward_engine.CLIENT_MSG_ID_RING_MAX == 500

        # 2) /api/steward/dictate transcribe client_msg_id deduplication
        transcribe_calls = []

        def _counting_hook(_wav: bytes) -> str:
            transcribe_calls.append(1)
            return "transcribed once"

        dictation_engine.set_dictation_transcribe_hook(_counting_hook)
        d_body = {"action": "transcribe", "audio_b64": FAKE_WAV_B64, "client_msg_id": "dict-dedup-77", "dictation_epoch": 2}
        ds1, dj1 = _http_json(f"{base}/api/steward/dictate", method="POST", body=d_body)
        ds2, dj2 = _http_json(f"{base}/api/steward/dictate", method="POST", body=d_body)
        assert ds1 == 200 and dj1["ok"] is True and dj1["text"] == "transcribed once" and dj1["deduplicated"] is False
        assert ds2 == 200 and dj2["ok"] is True and dj2["text"] == "transcribed once" and dj2["deduplicated"] is True
        assert dj2["dictation_epoch"] == 2
        assert len(transcribe_calls) == 1

        # 3) /api/steward/comms speed_racer_queue + email_steward_action + email_triage_feedback deduplication
        sr_body = {
            "action": "speed_racer_queue",
            "client_msg_id": "sr-dedup-99",
            "uid": "mail-w3-101",
            "to": "colleague@example.com",
            "subject": "Re: Lecture 4",
            "steward_directions": "Confirm sample size slide order",
            "async_draft": True,
        }
        cs1, cj1 = _http_json(f"{base}/api/steward/comms", method="POST", body=sr_body)
        cs2, cj2 = _http_json(f"{base}/api/steward/comms", method="POST", body=sr_body)
        assert cs1 == 200 and cj1["ok"] is True and not cj1.get("deduplicated")
        assert cs2 == 200 and cj2["ok"] is True and cj2.get("deduplicated") is True
        sr_store = comms_connector.load_speed_racer_queue()
        assert len(sr_store["queue"]) == 1, "Duplicate speed_racer_queue client_msg_id must not enqueue twice"

        act_body = {
            "action": "email_steward_action",
            "client_msg_id": "ema-dedup-88",
            "uid": "mail-w3-101",
            "from": "colleague@example.com",
            "subject": "Lecture 4",
            "comment": "Add Lecture 4 dataset check to The List",
        }
        as1, aj1 = _http_json(f"{base}/api/steward/comms", method="POST", body=act_body)
        as2, aj2 = _http_json(f"{base}/api/steward/comms", method="POST", body=act_body)
        assert as1 == 200 and aj1["ok"] is True and not aj1.get("deduplicated")
        assert as2 == 200 and aj2["ok"] is True and aj2.get("deduplicated") is True
        assert len(env["steward_dispatch_calls"]) == 1, "Duplicate email_steward_action must not dispatch twice"

        # Concurrent overlapping threads with identical client_msg_id on email_steward_action (no check-then-act race!)
        race_calls: list[str] = []
        orig_hook = comms_connector._CAVE_STEWARD_DISPATCH_HOOK

        def _slow_race_say(prompt, **kw):
            time.sleep(0.25)
            race_calls.append(prompt)
            return {"ok": True}

        monkeypatch.setattr(
            comms_connector,
            "_CAVE_STEWARD_DISPATCH_HOOK",
            types.SimpleNamespace(say=_slow_race_say),
            raising=False,
        )
        try:
            race_body = {
                "action": "email_steward_action",
                "client_msg_id": "ema-concurrent-race-01",
                "uid": "mail-w3-102",
                "from": "colleague2@example.com",
                "subject": "Lecture 5 Follow-up",
                "comment": "Queue Lecture 5 follow-up check once",
            }
            race_results: list[tuple[int, dict]] = []
            race_lock = threading.Lock()
            barrier = threading.Barrier(2)

            def _fire_race_post():
                barrier.wait(timeout=5.0)
                st_r, j_r = _http_json(f"{base}/api/steward/comms", method="POST", body=race_body)
                with race_lock:
                    race_results.append((st_r, j_r))

            t_a = threading.Thread(target=_fire_race_post, daemon=True)
            t_b = threading.Thread(target=_fire_race_post, daemon=True)
            t_a.start()
            t_b.start()
            t_a.join(timeout=10.0)
            t_b.join(timeout=10.0)
            assert len(race_results) == 2
            assert all(st_r == 200 and j_r.get("ok") is True for st_r, j_r in race_results), race_results
            dedup_flags = sorted(bool(j_r.get("deduplicated")) for _, j_r in race_results)
            assert dedup_flags == [False, True], f"Expected [False, True] deduplicated flags, got {race_results}"
            assert len(race_calls) == 1, f"Expected 1 Steward dispatch under concurrent race, got {len(race_calls)}"
        finally:
            monkeypatch.setattr(comms_connector, "_CAVE_STEWARD_DISPATCH_HOOK", orig_hook, raising=False)

        fb_body = {
            "action": "email_triage_feedback",
            "client_msg_id": "fb-dedup-55",
            "uid": "mail-w3-101",
            "sender_email": "colleague@example.com",
            "subject": "Lecture 4",
            "feedback": "seen",
        }
        fs1, fj1 = _http_json(f"{base}/api/steward/comms", method="POST", body=fb_body)
        fs2, fj2 = _http_json(f"{base}/api/steward/comms", method="POST", body=fb_body)
        assert fs1 == 200 and fj1["ok"] is True and not fj1.get("deduplicated")
        assert fs2 == 200 and fj2["ok"] is True and fj2.get("deduplicated") is True

        # Comms client_msg_id ring bound check (<= 500 entries)
        for i in range(520):
            comms_connector._record_comms_client_msg_id("email_triage_feedback", f"comms-ring-{i}", {"ok": True, "i": i})
        comms_ring_doc = json.loads((data_dir / ".anchor" / "comms-client-msg-ids.json").read_text(encoding="utf-8"))
        assert len(comms_ring_doc["scopes"]["email_triage_feedback"]) == comms_connector.COMMS_CLIENT_MSG_ID_MAX == 500


def test_w3_composer_drafts_atomic_concurrency_and_256kb_cap(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Verifies two-process atomic writes, unified tile<->cockpit crash recovery, 256 KB 413 cap, and 403 path containment."""
    pw_mod = pytest.importorskip("playwright.sync_api")
    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]
        proj_dir = env["proj_dir"]
        effort_dir = env["effort_dir"]
        data_dir = env["data_dir"]

        # 1) Real 2-OS-process concurrent atomic writer stress test
        worker_code = (
            "import os, sys, pathlib\n"
            f"sys.path.insert(0, {str(ROOT_DIR)!r})\n"
            "from steward_cockpit import steward_routes\n"
            "wid = sys.argv[1]\n"
            f"proot = {str(proj_dir)!r}\n"
            "for i in range(25):\n"
            "    body, code = steward_routes.handle_drafts_request(\n"
            "        'POST', body={'surface': 'email', 'uid': f'w{wid}-{i}', 'draft': f'draft-{wid}-{i}'}, proot=proot\n"
            "    )\n"
            "    assert code == 200 and body['ok'] is True, (code, body)\n"
            "    body2, code2 = steward_routes.handle_drafts_request(\n"
            "        'POST', body={'surface': 'cockpit', 'dir': 'lectures', 'draft': f'shared-{wid}-{i}'}, proot=proot\n"
            "    )\n"
            "    assert code2 == 200 and body2['ok'] is True, (code2, body2)\n"
        )
        worker_env = os.environ.copy()
        worker_env["ANCHOR_DATA_DIR"] = str(data_dir)
        p1 = subprocess.Popen([sys.executable, "-c", worker_code, "A"], env=worker_env, stderr=subprocess.PIPE)
        p2 = subprocess.Popen([sys.executable, "-c", worker_code, "B"], env=worker_env, stderr=subprocess.PIPE)
        _, err1 = p1.communicate(timeout=30)
        _, err2 = p2.communicate(timeout=30)
        assert p1.returncode == 0, err1.decode("utf-8", errors="replace")
        assert p2.returncode == 0, err2.decode("utf-8", errors="replace")

        anchor_store = json.loads((data_dir / ".anchor" / "composer-drafts.json").read_text(encoding="utf-8"))
        effort_store = json.loads((effort_dir / ".ecgberht" / "composer-drafts.json").read_text(encoding="utf-8"))
        for wid in ("A", "B"):
            for i in range(25):
                assert anchor_store["drafts"][f"email::w{wid}-{i}"]["draft"] == f"draft-{wid}-{i}"
        expected_cockpit_key = f"cockpit::{os.path.normcase(str(effort_dir.resolve()))}"
        assert expected_cockpit_key in effort_store["drafts"]

        # Clear lectures draft cleanly before browser crash-recovery test
        del_st, del_j = _http_json(
            f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures&surface=cockpit",
            method="DELETE",
        )
        assert del_st == 200 and del_j["status_kind"] == "empty-but-valid"

        # 2) Unified Tile <-> Full Cockpit Crash Recovery + Unload keepalive flush + [data-clear-draft]
        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx1 = browser.new_context(
                viewport={"width": 920, "height": 640},
                extra_http_headers={"Authorization": f"Bearer {TEST_CRED}", "X-Anchor-Token": TEST_CRED},
            )
            page1 = ctx1.new_page()
            page1.add_init_script(f"localStorage.setItem('anchor_token', {json.dumps(TEST_CRED)});")
            page1.goto(f"{base}/steward/v1?project={pid_mba}&effort=lectures&view=tile", wait_until="domcontentloaded")
            tile_ta = page1.locator("[data-say]")
            tile_ta.wait_for(state="visible")
            crash_text = "Unsent dictated instruction from Cave tile\nacross simulated browser crash"
            tile_ta.click()
            tile_ta.fill(crash_text)
            # Trigger page close (pagehide + unload keepalive flush) immediately without waiting for debounce
            page1.close()
            ctx1.close()

            # Wait up to 2s for keepalive POST to land on disk
            deadline = time.time() + 2.5
            while time.time() < deadline:
                st_chk, j_chk = _http_json(f"{base}/api/steward/drafts?project={pid_mba}&effort=lectures")
                if st_chk == 200 and j_chk.get("draft") == crash_text:
                    break
                time.sleep(0.05)
            st_chk, j_chk = _http_json(f"{base}/api/steward/drafts?project={pid_mba}&effort=lectures")
            assert st_chk == 200 and j_chk["draft"] == crash_text

            # Verify BOTH .ecgberht/composer-drafts.json AND .anchor/composer-drafts.json hold the exact canonical draft
            eff_disk = json.loads((effort_dir / ".ecgberht" / "composer-drafts.json").read_text(encoding="utf-8"))
            anc_disk = json.loads((data_dir / ".anchor" / "composer-drafts.json").read_text(encoding="utf-8"))
            assert eff_disk["drafts"][expected_cockpit_key]["draft"] == crash_text
            assert anc_disk["drafts"][expected_cockpit_key]["draft"] == crash_text

            # Open a brand-new isolated browser context (empty localStorage) at FULL cockpit (/steward/v1, no view=tile!)
            ctx2 = browser.new_context(
                viewport={"width": 1280, "height": 840},
                extra_http_headers={"Authorization": f"Bearer {TEST_CRED}", "X-Anchor-Token": TEST_CRED},
            )
            page2 = ctx2.new_page()
            page2.add_init_script(f"localStorage.setItem('anchor_token', {json.dumps(TEST_CRED)});")
            page2.goto(f"{base}/steward/v1?project={pid_mba}&effort=lectures", wait_until="domcontentloaded")
            full_ta = page2.locator("[data-say]")
            full_ta.wait_for(state="visible")
            page2.wait_for_function(
                "expected => document.querySelector('[data-say]').value === expected",
                arg=crash_text,
            )
            assert full_ta.input_value() == crash_text

            # Explicit [data-clear-draft] Clear wipes both UI and disk
            page2.locator("[data-clear-draft]").click()
            assert full_ta.input_value() == ""
            page2.wait_for_function("() => document.querySelector('[data-say]').dataset.draftBadge === 'EMPTY'")
            st_after_clr, j_after_clr = _http_json(f"{base}/api/steward/drafts?project={pid_mba}&effort=lectures")
            assert st_after_clr == 200 and j_after_clr["draft"] == "" and j_after_clr["status_kind"] == "empty-but-valid"

            ctx2.close()
            browser.close()

        # 3) Strict 256 KB (262,144 UTF-8 bytes) payload bound -> 413 BOUND_EXCEEDED_REFUSAL
        exact_256k = "x" * steward_routes.COMPOSER_DRAFT_MAX_BYTES
        st_ok, j_ok = _http_json(
            f"{base}/api/steward/drafts",
            method="POST",
            body={"pid": pid_mba, "dir": "lectures", "draft": exact_256k},
        )
        assert st_ok == 200 and j_ok["ok"] is True and j_ok["byte_length"] == 262144

        over_256k = "y" * (steward_routes.COMPOSER_DRAFT_MAX_BYTES + 1)
        st_big, j_big = _http_json(
            f"{base}/api/steward/drafts",
            method="POST",
            body={"pid": pid_mba, "dir": "lectures", "draft": over_256k},
        )
        assert st_big == 413
        assert j_big["ok"] is False
        assert j_big["status_kind"] == "bound-exceeded"
        assert j_big["error_code"] == "BOUND_EXCEEDED_REFUSAL"

        # Prior valid 256KB draft must remain intact after 413 refusal
        st_keep, j_keep = _http_json(f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures")
        assert st_keep == 200 and len(j_keep["draft"]) == 262144

        # 4) Escape-attempt path containment tests -> 403 PATH_CONTAINMENT_REFUSAL
        outside_dir = tmp_path / "outside-secret"
        outside_dir.mkdir(parents=True, exist_ok=True)
        escape_cases = [
            {"pid": pid_mba, "dir": "../outside-secret", "draft": "escape"},
            {"pid": pid_mba, "dir": "..\\outside-secret", "draft": "escape"},
            {"pid": pid_mba, "dir": str(outside_dir), "draft": "escape"},
            {"pid": pid_mba, "dir": "lectures/../../outside-secret", "draft": "escape"},
            {"pid": pid_mba, "dir": "bad\x00null", "draft": "escape"},
        ]
        # Also test symlink/junction escape if supported by host privileges
        link_path = proj_dir / "escaped_link"
        symlink_created = False
        try:
            os.symlink(str(outside_dir), str(link_path), target_is_directory=True)
            symlink_created = True
        except OSError:
            if os.name == "nt":
                r_junc = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(outside_dir)],
                    capture_output=True,
                    text=True,
                )
                symlink_created = r_junc.returncode == 0
        if symlink_created:
            escape_cases.append({"pid": pid_mba, "dir": "escaped_link", "draft": "escape"})

        for bad_payload in escape_cases:
            st_esc, j_esc = _http_json(f"{base}/api/steward/drafts", method="POST", body=bad_payload)
            assert st_esc == 403, f"Expected 403 containment refusal for {bad_payload}, got {st_esc}: {j_esc}"
            assert j_esc["error_code"] == "PATH_CONTAINMENT_REFUSAL"

        # 5) Auth gate check: invalid credential from non-cookie request must be refused (401)
        bad_cred = "invalid"
        st_unauth, _ = _http_json(
            f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures",
            method="GET",
            auth_cred=bad_cred,
        )
        assert st_unauth == 401


def test_w3_drafts_failure_state_table(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Exercises all 5 real failure-state rows on /api/steward/drafts without fake URL query hooks, proving UNKNOWN != EMPTY."""
    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]
        effort_dir = env["effort_dir"]
        data_dir = env["data_dir"]

        # Row 5: empty-but-valid -> HTTP 200, unknown_state=False, draft="", badge="EMPTY"
        st_empty, j_empty = _http_json(f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures")
        assert st_empty == 200
        assert j_empty["ok"] is True
        assert j_empty["status_kind"] == "empty-but-valid"
        assert j_empty["unknown_state"] is False
        assert j_empty["draft"] == ""
        assert j_empty["badge"] == "EMPTY"

        # Row 4: backing-store-unreadable -> corrupt JSON on disk -> HTTP 500, unknown_state=True, draft=None, badge="UNKNOWN"
        corrupt_path = effort_dir / ".ecgberht" / "composer-drafts.json"
        corrupt_path.write_text("{corrupt-unparseable-json!!!", encoding="utf-8")
        st_unk, j_unk = _http_json(f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures")
        assert st_unk == 500
        assert j_unk["ok"] is False
        assert j_unk["status_kind"] == "backing-store-unreadable"
        assert j_unk["unknown_state"] is True
        assert j_unk["draft"] is None
        assert j_unk["badge"] == "UNKNOWN"
        assert j_unk["badge"] != j_empty["badge"]
        assert j_unk["unknown_state"] != j_empty["unknown_state"]

        # Client clearDraft() MUST surface UNKNOWN / backing-store-unreadable (never EMPTY) when DELETE hits 500
        pw_mod = pytest.importorskip("playwright.sync_api")
        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1100, "height": 760},
                extra_http_headers={"Authorization": f"Bearer {TEST_CRED}", "X-Anchor-Token": TEST_CRED},
            )
            page = ctx.new_page()
            page.add_init_script(f"localStorage.setItem('anchor_token', {json.dumps(TEST_CRED)});")
            corrupt_path.unlink()
            st_seed, _ = _http_json(
                f"{base}/api/steward/drafts",
                method="POST",
                body={"pid": pid_mba, "dir": "lectures", "draft": "seed before corruption"},
            )
            assert st_seed == 200
            page.goto(f"{base}/steward/v1?project={pid_mba}&effort=lectures", wait_until="domcontentloaded")
            page.locator("[data-say]").wait_for(state="visible")
            corrupt_path.write_text("{corrupt-on-delete!!!", encoding="utf-8")
            page.locator("[data-clear-draft]").click()
            page.wait_for_function("() => document.querySelector('[data-say]').dataset.draftBadge === 'UNKNOWN'")
            assert page.evaluate("() => document.querySelector('[data-say]').dataset.draftStatusKind") == "backing-store-unreadable"
            ctx.close()
            browser.close()
        corrupt_path.unlink()
        # Secondary .anchor store must also have been cleared despite primary store corruption
        st_post_fix, j_post_fix = _http_json(f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures")
        assert st_post_fix == 200 and j_post_fix["draft"] == "" and j_post_fix["status_kind"] == "empty-but-valid"

        # Row 3: dependency-returns-garbage -> malformed JSON & bad schema -> HTTP 400
        st_garb1, j_garb1 = _http_json(f"{base}/api/steward/drafts", method="POST", body=b"{malformed-json")
        assert st_garb1 == 400
        assert j_garb1["status_kind"] == "dependency-returns-garbage"
        assert j_garb1["badge"] == "REJECTED_GARBAGE"

        st_garb2, j_garb2 = _http_json(
            f"{base}/api/steward/drafts",
            method="POST",
            body={"pid": pid_mba, "dir": "lectures", "draft": ["not", "a", "string"]},
        )
        assert st_garb2 == 400
        assert j_garb2["status_kind"] == "dependency-returns-garbage"

        # Row 2: dependency-slow-or-killed -> real held cross_process_lock causes timeout -> HTTP 504
        steward_routes.set_draft_lock_timeout(0.08)
        anchor_drafts_file = data_dir / ".anchor" / "composer-drafts.json"
        lock_ready = threading.Event()
        release_lock = threading.Event()

        def _hold_exclusive_lock():
            lock_path = anchor_drafts_file.with_name(f"{anchor_drafts_file.name}.lock")
            with paths.cross_process_lock(lock_path, timeout_sec=5.0):
                lock_ready.set()
                release_lock.wait(timeout=5.0)

        holder = threading.Thread(target=_hold_exclusive_lock, daemon=True)
        holder.start()
        assert lock_ready.wait(timeout=3.0)
        try:
            st_slow, j_slow = _http_json(
                f"{base}/api/steward/drafts",
                method="POST",
                body={"surface": "cave_say", "draft": "blocked by lock"},
            )
            assert st_slow == 504
            assert j_slow["ok"] is False
            assert j_slow["status_kind"] == "dependency-slow-or-killed"
            assert j_slow["badge"] == "TIMEOUT"
        finally:
            release_lock.set()
            holder.join(timeout=3.0)
            steward_routes.set_draft_lock_timeout(5.0)

        # Row 1: dependency-missing -> draft store unavailable & dictation backend unavailable -> HTTP 503
        steward_routes.set_draft_storage_available(False)
        try:
            st_miss, j_miss = _http_json(f"{base}/api/steward/drafts?pid={pid_mba}&dir=lectures")
            assert st_miss == 503
            assert j_miss["ok"] is False
            assert j_miss["status_kind"] == "dependency-missing"
            assert j_miss["badge"] == "DEPENDENCY_MISSING"
        finally:
            steward_routes.set_draft_storage_available(True)

        dictation_engine.set_dictation_backend_available(False)
        try:
            st_dmiss, j_dmiss = _http_json(
                f"{base}/api/steward/dictate",
                method="POST",
                body={"action": "transcribe", "audio_b64": FAKE_WAV_B64},
            )
            assert st_dmiss == 503
            assert j_dmiss["status_kind"] == "dependency-missing"
        finally:
            dictation_engine.set_dictation_backend_available(True)


def test_w3_route_inventory_and_mockup_contract():
    """Verifies route_table/chamber inventory alignment, page renders, and hermetic Wave 3 mockup & look artifacts."""
    diff = chamber_enforcement.diff_inventory_vs_code()
    assert not diff.get("missing_from_inventory", []), diff
    assert not diff.get("missing_from_code", []), diff

    # Verify both high_seat_page and campaign_page render [data-clear-draft] cleanly
    camp_ctx = {
        "pid": "camp01",
        "stamp": "s1",
        "build": "b1",
        "you": "John",
        "today": datetime.date(2026, 11, 20),
        "steward": {"label": "Aladdin", "mode": "star_chart"},
        "steps": [],
        "resolved": {},
        "initiatives": [],
        "seeds": [],
        "boneyard": [],
        "areas": [],
    }
    star_html = campaign_page._panel(camp_ctx)
    assert 'id="exSay"' in star_html and "data-clear-draft" in star_html and 'id="exSend"' in star_html

    mockup_path = (
        ROOT_DIR
        / "planning"
        / "cross-system-upgrade-2026-11-20"
        / "mockups"
        / "w3-cockpit-drafts-dictation.html"
    )
    assert mockup_path.is_file()
    mockup_txt = mockup_path.read_text(encoding="utf-8")
    assert ":8777" not in mockup_txt
    assert "data-clear-draft" in mockup_txt

    looks_base = ROOT_DIR / "planning" / "cross-system-upgrade-2026-11-20" / "looks" / "w3"
    for sub in ("", "live-full", "live-tile"):
        lj = (looks_base / sub / "look.json") if sub else (looks_base / "look.json")
        assert lj.is_file(), f"Missing look verdict file: {lj}"
        verdict = json.loads(lj.read_text(encoding="utf-8"))
        results = verdict.get("results") or []
        assert len(results) >= 2, f"Expected phone+desktop results in {lj}: {verdict}"
        for vp in results:
            assert vp.get("errors", []) == [], f"Console/page errors in {lj} ({vp.get('size')}): {vp}"
            clear_checks = (vp.get("checks") or {}).get("[data-clear-draft]") or []
            assert len(clear_checks) >= 1, f"Missing [data-clear-draft] check in {lj}: {vp}"
            assert clear_checks[0].get("painted") is True, clear_checks[0]
            assert clear_checks[0].get("coveredBy") is None, clear_checks[0]


def test_w3_hot_reload_legacy_engine_and_500_draft_preservation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Guards against hot-reload Engine.say signature mismatch, 500 draft-wipe swallow, and stale restart_anchor.ps1 check."""
    ps1_txt = (ROOT_DIR / "restart_anchor.ps1").read_text(encoding="utf-8")
    assert "ANCHOR_BOOT" in ps1_txt and "Cave of Wonders" in ps1_txt

    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_camp = env["pid_camp"]
        cave_dir = str(env["campaign_dir"] / "Cave of Wonders")

        calls: list[tuple] = []

        class LegacyPreReloadEngine:
            def __init__(self, d: str):
                self.dir = d
                self.open_question = None
                self.question_context = None
                self.pending_questions = []

            def alive(self) -> bool:
                return True

            def say(self, text, human=True, question_id=None, goal=None):
                calls.append((text, question_id, goal))
                return {"ok": True, "queued": False}

        with steward_routes.ENGINES_LOCK:
            steward_routes.ENGINES[cave_dir] = LegacyPreReloadEngine(cave_dir)

        st1, j1 = _http_json(
            f"{base}/api/steward/say",
            method="POST",
            body={
                "pid": pid_camp,
                "dir": "Cave of Wonders",
                "text": "Check hot-reload compatibility",
                "client_msg_id": "say-legacy-sig-1",
            },
        )
        st2, j2 = _http_json(
            f"{base}/api/steward/say",
            method="POST",
            body={
                "pid": pid_camp,
                "dir": "Cave of Wonders",
                "text": "Check hot-reload compatibility",
                "client_msg_id": "say-legacy-sig-1",
            },
        )
        assert st1 == 200 and j1.get("ok") is True and j1.get("deduplicated") is False
        assert st2 == 200 and j2.get("ok") is True and j2.get("deduplicated") is True
        assert len(calls) == 1

        pw = pytest.importorskip("playwright.sync_api")
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            delete_calls: list[str] = []

            def fail_say(route):
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=json.dumps({"error": "steward: simulated 500"}),
                )

            def watch_drafts(route):
                if route.request.method == "DELETE":
                    delete_calls.append(route.request.url)
                route.continue_()

            page.route("**/api/steward/say*", fail_say)
            page.route("**/api/steward/drafts*", watch_drafts)
            page.goto(f"{base}/?token={TEST_CRED}", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(600)
            page.fill("#say", "Keep this unsent draft on 500")
            page.click("#sendBtn")
            page.wait_for_timeout(500)
            assert page.input_value("#say") == "Keep this unsent draft on 500"
            assert not delete_calls
            assert page.locator("#receipt").is_visible()
            assert "simulated 500" in page.locator("#receiptText").inner_text()
            browser.close()


def test_w3_cave_cockpit_lifecycle_spine_heal_and_build_mismatch(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Verifies:
    1) sync_steward_projections never corrupts evented roadmaps with roadmap_silent_rewrite,
    2) campaign_acts auto-heals roadmap_silent_rewrite so seat / home / archive_cockpit / retire_cockpit / restore_cockpit succeed,
    3) Cave of Wonders UI handles stale X-Anchor-Build 409 seamlessly via syncServerBuild + shows #caveToast + Undo,
    4) Cave Steward fast commands execute 'archive <name>', 'retire <name>', and 'send <name> back to goals'."""
    import rnd_registry as _rnd
    from steward_cockpit import campaign_acts, campaign_say, steward_campaign

    with _ephemeral_anchor_env(tmp_path, monkeypatch) as env:
        base = env["base_url"]
        pid_mba = env["pid_mba"]
        pid_camp = env["pid_camp"]
        camp_dir = pathlib.Path(_rnd.get_project(pid_camp)["folder_path"])

        # Initialize a clean Ecgberht Campaign surface + goal + seated MBA component
        (camp_dir / "roadmap.json").write_text(
            json.dumps(
                {
                    "schema": "ecgberht-roadmap-v0",
                    "project_id": None,
                    "as_of": "2026-11-20",
                    "roadmap_events": [],
                    "roadmap_projection": [],
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        (camp_dir / "strip.json").write_text(
            json.dumps(
                {
                    "schema": "ecgberht-strip-v0",
                    "project_id": "campaign",
                    "face_path": "ECGBERHT.md",
                    "as_of": "2026-11-20",
                    "phase": "executing",
                    "active_effort": "Star Chart",
                    "effort_status": "IN_PROGRESS",
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        res_goal = campaign_acts.new_goal(str(camp_dir), "MBA Teaching Goal", tier=1, area="professional")
        assert res_goal["ok"] is True, f"new_goal failed: {res_goal}"
        gid = res_goal["step"]
        res_add = campaign_acts.add(str(camp_dir), gid, "project", "MBA Teaching AI", project_id=pid_mba)
        assert res_add["ok"] is True
        comp_id = res_add["step"]
        res_seat = campaign_acts.seat(str(camp_dir), comp_id, "active")
        assert res_seat["ok"] is True

        # Inject silent projection drift (simulating legacy direct JSON edit) + strip mismatch
        rm_path = camp_dir / "roadmap.json"
        rm_doc = json.loads(rm_path.read_text(encoding="utf-8"))
        for st in rm_doc["roadmap_projection"]:
            if st["id"] == comp_id:
                st["done_when"] = "corrupted silent rewrite"
                st.setdefault("navigation", {})["pin"] = True
        rm_path.write_text(json.dumps(rm_doc, indent=2) + "\n", encoding="utf-8")

        # Auto-heal on seat -> On deck & home -> Back to goal
        r_deck = campaign_acts.seat(str(camp_dir), comp_id, "deck")
        assert r_deck["ok"] is True, f"Expected auto-heal on seat, got: {r_deck}"
        r_home = campaign_acts.home(str(camp_dir), comp_id)
        assert r_home["ok"] is True, f"Expected home to succeed, got: {r_home}"

        # sync_steward_projections must NOT re-introduce roadmap_silent_rewrite on evented roadmaps
        (camp_dir / "strip.json").write_text(
            json.dumps({"current_step_id": comp_id, "active_effort": "v9.9", "why_next": "should not overwrite"}),
            encoding="utf-8",
        )
        steward_campaign.sync_steward_projections(str(camp_dir))
        r_active = campaign_acts.seat(str(camp_dir), comp_id, "active")
        assert r_active["ok"] is True, f"sync_steward_projections broke spine: {r_active}"

        # Fast Steward commands: send back to goals, archive, restore, retire
        s_back = campaign_say.fast_steward_command(str(camp_dir), "send MBA Teaching AI back to goals")
        assert s_back and s_back["ok"] is True
        assert campaign_acts._step(str(camp_dir), comp_id).get("seat") is None

        campaign_acts.seat(str(camp_dir), comp_id, "deck")
        s_arch = campaign_say.fast_steward_command(str(camp_dir), "archive MBA Teaching AI")
        assert s_arch and s_arch["ok"] is True and s_arch["act"] == "archive_cockpit"
        assert _rnd.get_project(pid_mba)["state"] == "archived"

        r_undo = campaign_acts.act(str(camp_dir), s_arch["undo"])
        assert r_undo["ok"] is True
        assert _rnd.get_project(pid_mba)["state"] == "active"
        assert campaign_acts._step(str(camp_dir), comp_id).get("seat") == "deck"

        # Playwright UI check: stale X-Anchor-Build 409 auto-recovery + #caveToast + Retire + Undo
        pw = pytest.importorskip("playwright.sync_api")
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{base}/?token={TEST_CRED}", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_selector(f"#shDeck #card-{pid_mba}", timeout=10000)

            # Force stale client build_id while keeping a dummy .tile.open guard check clean:
            # act() must sync server_build from 409, retry immediately, and move card to Active!
            page.evaluate("window.ANCHOR_BOOT.build_id = 'stale-old-build-000';")
            # Keep tileOpen() true via a synthetic hidden open marker so renewBuild defers reload while act() still succeeds!
            page.evaluate("const d = document.createElement('div'); d.className = 'tile open'; d.id = 'holdReload'; d.hidden = true; document.body.appendChild(d);")
            page.click(f"#shDeck .t-seat-btn[data-seat='active'][data-step='{comp_id}']")
            page.wait_for_selector(f"#shActive #card-{pid_mba}", timeout=10000)
            assert page.locator("#caveToast").is_visible()

            # Hover card -> click Retire in .t-peek-lc -> card leaves shelves & project state becomes retired
            page.hover(f"#shActive #card-{pid_mba}")
            retire_btn = page.locator(f"#shActive #card-{pid_mba} .t-peek-lc [data-cockpit-lifecycle='retire']")
            retire_btn.wait_for(state="visible", timeout=5000)
            retire_btn.click()
            page.wait_for_selector(f"#card-{pid_mba}", state="detached", timeout=10000)
            assert _rnd.get_project(pid_mba)["state"] == "retired"
            assert "Retired" in page.locator("#caveToastText").inner_text()

            # Click Undo right on #caveToast -> restores project to active & re-seats card in Active!
            page.click("#caveToastUndo")
            page.wait_for_selector(f"#shActive #card-{pid_mba}", timeout=10000)
            assert _rnd.get_project(pid_mba)["state"] == "active"
            browser.close()


def test_w3_no_glitch_reload_on_live_edit_and_inplace_light_and_status_ack_dedupe(tmp_path):
    """Regression test for Anchor.exe anti-glitch stability (2026-11-21):
    1. Ordinary Cave renders (render_high_seat_page) do NOT call _doctor_sync_live_code();
       explicit Doctor Resolve All bumps ANCHOR_STARTED_AT when BUILD_ID moves.
    2. Live file edits with unchanged `boot` sync build_id quietly without location.reload();
       actual server restarts (`boot` changed) still renew cleanly.
    3. Cave card `.tlight` / `data-ready` transitions update in place ('face', never 'remake'),
       keeping card DOM nodes and prewarmed `.cframe` iframes alive.
    4. Cockpit `renderStatus` dedupes unchanged status payloads and fires `status-ack` once per `(status_id, at)`.
    """
    import inspect
    import json
    import os
    import pathlib
    import sys
    from unittest import mock
    import anchor_gui as ag
    _anchor_root = pathlib.Path(__file__).resolve().parent.parent

    # 1. Verify render_high_seat_page does not invoke _doctor_sync_live_code on ordinary reads
    src_rhs = inspect.getsource(ag.render_high_seat_page)
    assert "_doctor_sync_live_code" not in src_rhs

    old_boot = os.environ.get("ANCHOR_STARTED_AT", "1000.0")
    old_build = ag.BUILD_ID
    try:
        os.environ["ANCHOR_STARTED_AT"] = "1000.0"
        ag.BUILD_ID = "abc1234+old0001"
        with mock.patch.object(ag, "_compute_build_id", return_value="abc1234+new0002"):
            ag._doctor_sync_live_code()
        assert ag.BUILD_ID == "abc1234+new0002"
        assert os.environ["ANCHOR_STARTED_AT"] != "1000.0"
    finally:
        ag.BUILD_ID = old_build
        os.environ["ANCHOR_STARTED_AT"] = old_boot

    # 2, 3 & 4. Browser verification in Playwright
    pw = pytest.importorskip("playwright.sync_api")
    if str(_anchor_root / "tests") not in sys.path:
        sys.path.insert(0, str(_anchor_root / "tests"))
    import high_seat_page as hsp
    import test_high_seat_page_2026_09_26 as base_hsp

    state = {
        "version": "b1+initial",
        "boot": "boot-100",
        "health": "h1",
        "light": "gray",
        "why": "",
        "needs_you": "",
        "loads": 0,
        "frame_loads": 0,
        "status_at": "2026-11-21 07:05",
        "status_seq": 1,
        "status_acks": [],
    }

    def render_cave_html():
        ctx = base_hsp._ctx()
        ctx["build"] = "b1+initial"
        ctx["auth_required"] = False
        mba_pid = "6765ece4b3bc43b0b0b0907b92b17280"
        steps = [s for s in base_hsp._steps() if s["id"] != "mba-project"]
        steps.append({
            "id": "mba-project",
            "name": "MBA Teaching AI",
            "status": "proposed",
            "ref": "project:" + mba_pid,
            "seat": "active",
            "seat_order": 0,
            "navigation": {"path": ["mba-teaching"]},
        })
        ctx["initiatives"] = hsp.campaign_initiatives(steps, base_hsp._resolved())
        lights = dict(ctx.get("lights") or {})
        lights[(mba_pid, "")] = {"light": state["light"], "why": state["why"]}
        lights[mba_pid] = {"light": state["light"], "why": state["why"]}
        ctx["lights"] = lights
        ctx["facts"][mba_pid]["needs_you"] = state["needs_you"]
        return hsp.render_high_seat_html(ctx)

    frame_html = (
        "<!doctype html><html><body><script>"
        "window.__frameIdent = Math.random().toString(36).slice(2);"
        "var q = new URLSearchParams(location.search), inst = q.get('inst');"
        "parent.postMessage({proto:'anchor-tile', inst:inst, kind:'ready'}, location.origin);"
        "</script></body></html>"
    )

    from steward_cockpit import steward_routes as sr
    _cdoc = sr.serve_page_doc("v1", "2779ca24595247bc9f25dcb4a9e6429c", effort_dir="Book 1")
    cockpit_html = _cdoc if isinstance(_cdoc, str) else (_cdoc[0].decode("utf-8") if isinstance(_cdoc[0], (bytes, bytearray)) else str(_cdoc[0]))

    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def handle_route(route):
            req = route.request
            from urllib.parse import urlparse, parse_qs
            u = urlparse(req.url)
            path, q = u.path, parse_qs(u.query)
            if path in ("/", "/high-seat"):
                if req.resource_type == "document":
                    state["loads"] += 1
                return route.fulfill(status=200, content_type="text/html", body=render_cave_html())
            if path == "/steward/v1" and q.get("embed"):
                state["frame_loads"] += 1
                return route.fulfill(status=200, content_type="text/html", body=frame_html)
            if path == "/steward/v1":
                return route.fulfill(status=200, content_type="text/html", body=cockpit_html)
            if path == "/api/version":
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"version": state["version"], "boot": state["boot"], "health": state["health"]}),
                )
            if path in ("/api/steward/events", "/api/events"):
                state["ev_count"] = state.get("ev_count", 0) + 1
                if state["ev_count"] > 4:
                    return route.abort()
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"events": [], "state": {"epoch": 1, "alive": True, "busy": True}, "stamp": "st1"}),
                )
            if path in ("/api/steward/state", "/api/state"):
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"ok": True, "epoch": 1, "alive": True, "busy": True}),
                )
            if path in ("/api/steward/status", "/api/status"):
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "ok": True,
                        "status_id": f"{state['status_seq']}:2026-11-21T07:{5 + state['status_seq']:02d}:00Z",
                        "at": state["status_at"],
                        "effort": "Book 1",
                        "now": ["Drafting Chapter 3"],
                        "lead_line": "Drafting Chapter 3",
                        "plan": {"steps_done": 1, "steps_total": 4},
                    }),
                )
            if path in ("/api/steward/status-ack", "/api/status-ack"):
                body_json = json.loads(req.post_data or "{}")
                state["status_acks"].append(body_json.get("at", ""))
                return route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
            if path.startswith("/api/steward/") or path.startswith("/api/"):
                return route.fulfill(status=200, content_type="application/json", body='{"ok":true,"turns":[],"items":[],"steps":[]}')
            for prefix, folder in (
                ("/static/", _anchor_root / "static"),
                ("/steward-static/", _anchor_root / "steward_cockpit" / "static"),
                ("/vendor/", _anchor_root / "vendor"),
            ):
                if path.startswith(prefix):
                    rel_name = path[len(prefix):]
                    fp = folder / rel_name
                    if prefix == "/static/" and not fp.is_file():
                        fp = _anchor_root / "steward_cockpit" / "static" / rel_name
                    if fp.is_file():
                        ctype = "text/css" if rel_name.endswith(".css") else "application/javascript" if rel_name.endswith(".js") else "application/octet-stream"
                        return route.fulfill(status=200, content_type=ctype, body=fp.read_bytes())
            return route.fulfill(status=200, content_type="application/json", body="{}")

        # Install faster interval hook BEFORE loading Cave so we don't wait 30s in test
        page.add_init_script("""
            window.__versionCallbacks = [];
            const _origSetInterval = window.setInterval;
            window.setInterval = function(fn, ms) {
                if (ms === 30000 && String(fn).indexOf('/api/version') !== -1) {
                    window.__versionCallbacks.push(fn);
                }
                return _origSetInterval.apply(this, arguments);
            };
        """)
        page.route("**/*", handle_route)
        page.goto("http://cave.test/high-seat", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => { const f = document.querySelector('#card-6765ece4b3bc43b0b0b0907b92b17280 iframe.cframe'); return f && f.contentWindow && f.contentWindow.__frameIdent; }",
            timeout=10000,
        )
        initial_frame_ident = page.evaluate(
            "(() => { const c = document.getElementById('card-6765ece4b3bc43b0b0b0907b92b17280'); c.__domTag = 'same-node'; return c.querySelector('iframe.cframe').contentWindow.__frameIdent; })()"
        )
        initial_frame_loads = state["frame_loads"]
        assert state["loads"] == 1

        # 2A. Simulate live file save changing version while boot stays 'boot-100': MUST NOT reload!
        state["version"] = "b1+liveedit2"
        page.evaluate("window.__versionCallbacks.forEach(fn => fn());")
        page.wait_for_timeout(300)
        assert state["loads"] == 1, "Live edit with unchanged boot must not reload Cave"
        assert page.evaluate("window.ANCHOR_BOOT.build_id") == "b1+liveedit2"

        # 3. Simulate status light & attention changing on /high-seat (gray -> orange + data-ready):
        # MUST update in place ('face', NOT 'remake') — keeping same card DOM node and prewarmed iframe!
        state["light"] = "orange"
        state["why"] = "needs review"
        state["needs_you"] = "Approve outline"
        state["health"] = "h2"
        page.evaluate("window.__versionCallbacks.forEach(fn => fn());")
        page.wait_for_function(
            "() => (document.querySelector('#card-6765ece4b3bc43b0b0b0907b92b17280 .t-face') || {}).textContent.indexOf('Approve outline') !== -1",
            timeout=5000,
        )
        after_inplace = page.evaluate("""() => {
            const c = document.getElementById('card-6765ece4b3bc43b0b0b0907b92b17280');
            const f = c && c.querySelector('iframe.cframe');
            return {
                domTag: c && c.__domTag,
                frameIdent: f && f.contentWindow && f.contentWindow.__frameIdent,
            };
        }""")
        assert after_inplace["domTag"] == "same-node", "Card DOM node was destroyed instead of updated in place"
        assert after_inplace["frameIdent"] == initial_frame_ident, "Prewarmed tile iframe was torn down on light/ready change"
        assert state["frame_loads"] == initial_frame_loads, "Prewarmed tile iframe reloaded unnecessarily"
        assert state["loads"] == 1

        # 2B. Simulate real server restart (`boot` changes to 'boot-200' + version changes): MUST reload cleanly!
        state["boot"] = "boot-200"
        state["version"] = "b2+restarted"
        page.evaluate("window.__versionCallbacks.forEach(fn => fn());")
        page.wait_for_function("() => !window.__versionCallbacks || document.readyState === 'complete'", timeout=5000)
        page.wait_for_timeout(500)
        assert state["loads"] == 2, "Real server restart (new boot) must trigger clean reload"

        # 4. Verify cockpit shared.js dedupes unchanged renderStatus & status-ack across repeated polls
        state["status_acks"].clear()
        cpage = browser.new_page(viewport={"width": 1440, "height": 900})
        cpage.route("**/*", handle_route)
        cpage.goto("http://cave.test/steward/v1?pid=2779ca24595247bc9f25dcb4a9e6429c&dir=Book%201", wait_until="domcontentloaded")
        cpage.wait_for_selector(".blk.status.latest", state="attached", timeout=8000)
        cpage.wait_for_timeout(900)  # allow 800ms coalesced status-ack to fire once
        assert state["status_acks"] == ["2026-11-21 07:05"]

        # Trigger visibility re-polls with UNCHANGED status_at -> ZERO duplicate status-acks!
        cpage.evaluate("document.dispatchEvent(new Event('visibilitychange'));")
        cpage.wait_for_timeout(950)
        assert state["status_acks"] == ["2026-11-21 07:05"], f"Duplicate status-ack fired: {state['status_acks']}"

        # Advance status_at -> fires exactly ONE new status-ack for the new timestamp!
        state["status_at"] = "2026-11-21 07:15"
        state["status_seq"] = 2
        cpage.evaluate("document.dispatchEvent(new Event('visibilitychange'));")
        cpage.wait_for_timeout(950)
        assert state["status_acks"] == ["2026-11-21 07:05", "2026-11-21 07:15"]
        browser.close()


def test_w3_scoped_pdf_zoom_and_unicode_content_disposition(tmp_path):
    """Verify:
    1. Unicode PDF titles (e.g. em-dash '\\u2014') produce RFC-5987 / latin-1-safe Content-Disposition
       in both steward_routes._format_content_disposition and AnchorHandler._latin1_safe_content_disposition
       (never HTTP 500 UnicodeEncodeError).
    2. Inside Anchor's 2-pane app shell (static/app.html), opening a PDF deliverable opens scrollview=1,
       and Ctrl+ / Ctrl- / Ctrl+0 / Ctrl+wheel / toolbar buttons inside or hovered over the PDF pane
       smoothly rescale & pan ONLY the PDF pages (up to 300%, zero white blank space on the left,
       pywebview.api.zoom NOT invoked), while Ctrl+ in the left non-PDF pane still zooms Anchor's UI."""
    pw_sync = pytest.importorskip("playwright.sync_api")
    import fitz
    import anchor_gui as ag
    from steward_cockpit import steward_routes as sr

    # 1. Unit-verify latin-1 header safety + UTF-8 filename* preservation
    unicode_title = "Young Men Deacons Quorum Lesson Guide \u2014 Sunday, November 22, 2026.pdf"
    cd1 = sr._format_content_disposition("inline", unicode_title)
    cd1.encode("latin-1")  # Must never raise UnicodeEncodeError!
    assert 'filename="Young Men Deacons Quorum Lesson Guide - Sunday, November 22, 2026.pdf"' in cd1
    assert "filename*=UTF-8''Young%20Men%20Deacons%20Quorum%20Lesson%20Guide%20%E2%80%94%20Sunday" in cd1

    cd2 = ag.AnchorHandler._latin1_safe_content_disposition(
        content_disposition=f'inline; filename="{unicode_title}"',
        disposition="inline",
        filename=unicode_title,
    )
    cd2.encode("latin-1")
    assert "filename*=UTF-8''" in cd2

    # Pure ASCII filenames stay byte-identical without extra filename* noise
    cd_ascii = sr._format_content_disposition("attachment", "Manuscript_Ch7_8_v5.docx")
    assert cd_ascii == 'attachment; filename="Manuscript_Ch7_8_v5.docx"'

    # 2. Generate a real 2-page PDF via PyMuPDF and render real _serve_pdf_scrollview + _serve_pdf_page_png
    cdir = tmp_path / "Cave of Wonders"
    cdir.mkdir(parents=True, exist_ok=True)
    pdf_path = cdir / "Deacons-Lesson.pdf"
    doc = fitz.open()
    for pg_num in (1, 2):
        pg = doc.new_page(width=612, height=792)
        pg.insert_text((72, 100), f"Deacons Lesson Guide \u2014 Page {pg_num}", fontsize=20)
    doc.save(str(pdf_path))
    doc.close()

    scroll_res, scroll_code = sr._serve_pdf_scrollview(
        str(pdf_path),
        {"pid": "p_cave", "dir": "Cave of Wonders", "filename": unicode_title},
        "Deacons-Lesson.pdf",
        str(cdir),
    )
    assert scroll_code == 200
    pdf_scroll_html = scroll_res["__html__"]
    png_res, png_code = sr._serve_pdf_page_png(str(pdf_path), 0)
    assert png_code == 200
    png_bytes = pathlib.Path(png_res["__file__"]).read_bytes()

    anchor_root = pathlib.Path(__file__).resolve().parent.parent
    app_html = (anchor_root / "static" / "app.html").read_text(encoding="utf-8")
    app_css = (anchor_root / "static" / "app.css").read_text(encoding="utf-8")
    app_js = (anchor_root / "static" / "app.js").read_text(encoding="utf-8")
    app_frame_js = (anchor_root / "static" / "app-frame.js").read_text(encoding="utf-8")
    fb_js = (anchor_root / "static" / "cockpit-feedback.js").read_text(encoding="utf-8")
    alarm_js = (anchor_root / "static" / "calendar-alarm.js").read_text(encoding="utf-8")

    cave_stub_html = """<!doctype html><html><head><meta charset="utf-8"><title>Cave of Wonders</title></head>
    <body style="background:#0f1117;color:#e2e4e9">
      <button id="caveFocusBtn" type="button">Cave Focus</button>
      <a id="openPdfLink" href="/api/steward/deliverable-file?pid=p_cave&dir=Cave+of+Wonders&path=Deacons-Lesson.pdf" target="_blank">Open Lesson PDF</a>
    </body></html>"""

    def handle_route(route):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(route.request.url)
        p = u.path
        qs = parse_qs(u.query)
        if p == "/static/app.html":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=app_html)
        elif p == "/static/app.css":
            route.fulfill(status=200, content_type="text/css; charset=utf-8", body=app_css)
        elif p == "/static/app.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=app_js)
        elif p == "/static/app-frame.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=app_frame_js)
        elif p == "/static/cockpit-feedback.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=fb_js)
        elif p == "/static/calendar-alarm.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=alarm_js)
        elif p in ("/", "/high-seat"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=cave_stub_html)
        elif p == "/api/steward/deliverable-file":
            if "pdf_page" in qs:
                route.fulfill(status=200, content_type="image/png", body=png_bytes)
            elif qs.get("scrollview") == ["1"]:
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=pdf_scroll_html)
            else:
                route.fulfill(
                    status=200,
                    content_type="application/pdf",
                    headers={"Content-Disposition": cd1},
                    body=pdf_path.read_bytes(),
                )
        elif p.startswith("/api/"):
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            route.fulfill(status=200, content_type="image/svg+xml", body="<svg xmlns='http://www.w3.org/2000/svg'/>")

    with pw_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 860})
        page.add_init_script("""
            window.__shellZoomCalls = [];
            window.pywebview = {
                api: {
                    zoom: function(step) { window.__shellZoomCalls.push(step); return 1.0; },
                    window_control: function() {}
                }
            };
        """)
        page.route("**/*", handle_route)
        page.goto("http://anchor.test/static/app.html", wait_until="networkidle")

        from urllib.parse import urlparse as _up
        page.wait_for_function(
            "() => { const f = document.querySelector('iframe.pane'); return f && f.contentWindow && f.contentWindow.__anchorFrame; }",
            timeout=8000,
        )
        cave_frame = next(f for f in page.frames if f != page.main_frame and _up(f.url).path in ("/", "/high-seat"))
        cave_frame.locator("#openPdfLink").click()
        page.wait_for_function(
            "() => document.body.classList.contains('two') && Array.from(document.querySelectorAll('iframe.pane')).some(f => f.contentWindow && f.contentWindow.__anchorPdfViewer)",
            timeout=8000,
        )
        pdf_frame = next(f for f in page.frames if "scrollview=1" in f.url)
        pdf_frame.wait_for_selector("#pdfZoomReadout", timeout=5000)

        w_100 = pdf_frame.evaluate("document.getElementById('pdfMain').offsetWidth")
        stage_w = pdf_frame.evaluate("document.getElementById('pdfStage').clientWidth")
        assert w_100 <= stage_w

        # Click inside PDF pane and press Ctrl + three times -> scales PDF to 160%, shell zoom NEVER called!
        pdf_frame.locator("#pdfStage").click()
        for _ in range(3):
            page.keyboard.press("Control+=")
        assert pdf_frame.locator("#pdfZoomReadout").inner_text() == "160%"
        w_160 = pdf_frame.evaluate("document.getElementById('pdfMain').offsetWidth")
        assert w_160 > stage_w, f"Expected zoomed PDF width ({w_160}) > pane stage width ({stage_w})"
        assert page.evaluate("window.__shellZoomCalls") == [], "Ctrl+ inside PDF must NOT zoom the Anchor shell!"

        # Toolbar stay-in-place & zero left blank space check
        bar_w = pdf_frame.evaluate("document.querySelector('.pdf-bar').offsetWidth")
        assert abs(bar_w - pdf_frame.evaluate("window.innerWidth")) <= 2
        left_pane_rect = page.evaluate("document.querySelector('iframe.pane[data-pane=\"0\"]').getBoundingClientRect().toJSON()")
        assert left_pane_rect["left"] <= 2 and left_pane_rect["width"] > 550

        # Ctrl+0 inside PDF resets PDF back to 100% cleanly without touching shell zoom
        page.keyboard.press("Control+0")
        assert pdf_frame.locator("#pdfZoomReadout").inner_text() == "100%"
        assert page.evaluate("window.__shellZoomCalls") == []

        # Clicking back in Cave (left pane) and pressing Ctrl + zooms Anchor's shell as normal
        cave_frame.locator("#caveFocusBtn").click()
        page.mouse.move(120, 200)
        page.keyboard.press("Control+=")
        assert page.evaluate("window.__shellZoomCalls") == [1]
        browser.close()


def test_w3_cockpit_responsive_fit_inside_anchor_shell():
    """Verify AI Cockpit (v1.html + shared.css) fits cleanly inside Anchor.exe across wide (1500px),
    medium/laptop (1180px), and narrow/split-pane (780px) widths without clipping .bar controls
    (Spend, Go, Boneyard, Collapse) off the right edge or crushing the center dialogue column."""
    pw_sync = pytest.importorskip("playwright.sync_api")
    from steward_cockpit import steward_routes as sr

    anchor_root = pathlib.Path(__file__).resolve().parent.parent
    shared_css = (anchor_root / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")
    shared_js = (anchor_root / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    md_js = (anchor_root / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    plate_js = (anchor_root / "steward_cockpit" / "static" / "plate.js").read_text(encoding="utf-8")
    icons_js = (anchor_root / "steward_cockpit" / "static" / "skill-icons.js").read_text(encoding="utf-8")
    v1_doc = sr.serve_page_doc("v1", pid="p_book1", effort_dir="Book 1", embed=False, view="")

    events_polls = {"n": 0}

    def handle_route(route):
        from urllib.parse import urlparse
        p = urlparse(route.request.url).path
        if p == "/steward/v1":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=v1_doc)
        elif p == "/static/shared.css":
            route.fulfill(status=200, content_type="text/css; charset=utf-8", body=shared_css)
        elif p == "/static/shared.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=shared_js)
        elif p == "/static/md.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=md_js)
        elif p == "/static/plate.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=plate_js)
        elif p == "/static/skill-icons.js":
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=icons_js)
        elif p == "/api/steward/state":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "busy": True,
                    "light": "quiet",
                    "name": "Book 1 — Artificial Magi",
                    "spend_text": "Total $1,387.36 · 1,702,042,117 (1702.04M) tok · 4760m ▾",
                }),
            )
        elif p == "/api/steward/events":
            events_polls["n"] += 1
            if events_polls["n"] > 3:
                route.abort()
            else:
                route.fulfill(status=200, content_type="application/json", body='{"ok":true,"events":[],"next":1,"busy":true}')
        elif p.startswith("/api/"):
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        else:
            route.fulfill(status=200, content_type="image/svg+xml", body="<svg xmlns='http://www.w3.org/2000/svg'/>")

    with pw_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1180, "height": 760})
        page.route("**/*", handle_route)
        page.goto("http://cockpit.test/steward/v1?pid=p_book1&dir=Book%201", wait_until="domcontentloaded")
        page.wait_for_selector(".bar [data-min]", timeout=8000)
        page.evaluate("""() => {
            document.querySelector('[data-name]').textContent = 'Book 1 — Artificial Magi';
            document.querySelector('[data-spend]').textContent = 'Total $1,387.36 · 1,702,042,117 (1702.04M) tok · 4760m ▾';
        }""")
        page.wait_for_timeout(150)

        for vw, vh, min_main_w in [(1500, 950, 640), (1180, 760, 440), (780, 700, 700)]:
            page.set_viewport_size({"width": vw, "height": vh})
            page.wait_for_timeout(120)
            m = page.evaluate("""() => {
                const bar = document.querySelector('.bar');
                const minBtn = document.querySelector('.bar [data-min]');
                const goBtn = document.querySelector('.bar [data-drive]');
                const main = document.querySelector('.main');
                return {
                    innerW: window.innerWidth,
                    docScrollW: document.documentElement.scrollWidth,
                    barScrollW: bar.scrollWidth,
                    barClientW: bar.clientWidth,
                    minBtnRight: minBtn.getBoundingClientRect().right,
                    goBtnRight: goBtn.getBoundingClientRect().right,
                    mainW: main.offsetWidth,
                };
            }""")
            assert m["docScrollW"] <= m["innerW"] + 1, f"Horizontal overflow at {vw}px: {m}"
            assert m["barScrollW"] <= m["barClientW"] + 1, f"Top .bar clipped at {vw}px: {m}"
            assert m["minBtnRight"] <= m["innerW"] + 1, f"Collapse button clipped off right edge at {vw}px: {m}"
            assert m["goBtnRight"] <= m["innerW"] + 1, f"Go button clipped off right edge at {vw}px: {m}"
            assert m["mainW"] >= min_main_w, f"Center dialogue too narrow at {vw}px: {m}"
        browser.close()


def test_w3_all_doc_types_fit_split_pane_and_app_frame_upgrades_open_shell(tmp_path):
    """Verify PDF (compact bar + Fit Page), wide 820px HTML deliverables (auto-fit sandboxed srcdoc),
    Markdown reports (report_viewer.reader_html), and Office previews (office_preview.render_preview)
    all fit cleanly inside a 560px split pane with zero horizontal clipping and scoped Ctrl+ zoom."""
    pw_sync = pytest.importorskip("playwright.sync_api")
    import zipfile
    import fitz
    import office_preview as op
    import report_viewer as rv
    from steward_cockpit import steward_routes as sr

    cdir = tmp_path / "Cave"
    cdir.mkdir(parents=True, exist_ok=True)

    # 1. Wide 820px print-style HTML deliverable (like Ben Midway briefing)
    wide_html = cdir / "Wide-Briefing.html"
    wide_html.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        ".sheet{width:820px;padding:20px;background:#fff}"
        "table{width:780px;border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px}"
        "</style></head><body><div class='sheet'><h1>Wide Executive Briefing</h1>"
        "<table><tr><th>Option</th><th>Value</th><th>Loan</th><th>Payment</th><th>Equity</th></tr>"
        "<tr><td>Mid-Market</td><td>$2,000,000</td><td>$997,870</td><td>$6,592/mo</td><td>$932,977</td></tr>"
        "</table></div></body></html>",
        encoding="utf-8",
    )
    html_sv, html_code = sr._serve_html_scrollview(str(wide_html), {"pid": "p1", "dir": "Cave"}, "Wide-Briefing.html", str(cdir))
    assert html_code == 200
    assert "sandbox='allow-scripts allow-popups allow-forms allow-modals allow-downloads'" in html_sv["__html__"]
    assert "allow-same-origin" not in html_sv["__html__"]

    # 2. Markdown report with wide table + long unspaced URL + oversized image
    md_doc = rv.reader_html(
        "# Financial Model\n\n"
        "Link: https://example.com/" + ("very-long-segment-" * 12) + "\n\n"
        "| Col A | Col B | Col C | Col D | Col E | Col F |\n"
        "|---|---|---|---|---|---|\n"
        "| 1000000 | 2000000 | 3000000 | 4000000 | 5000000 | 6000000 |\n",
        title="Model Report",
    )

    # 3. DOCX preview with long unspaced line & multi-column table
    docx_buf_path = cdir / "Brief.docx"
    with zipfile.ZipFile(docx_buf_path, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>' + ("LongToken_" * 30) + '</w:t></w:r></w:p></w:body></w:document>',
        )
    docx_html = op.render_preview(docx_buf_path.read_bytes(), "Brief.docx", "/dl")

    # 4. PDF scrollview with compact 1-row bar + Fit Page button
    pdf_path = cdir / "Report.pdf"
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((72, 100), "Page 1 Fit Test", fontsize=22)
    doc.save(str(pdf_path))
    doc.close()
    pdf_sv, _ = sr._serve_pdf_scrollview(str(pdf_path), {"pid": "p1", "dir": "Cave"}, "Report.pdf", str(cdir))
    png_res, _ = sr._serve_pdf_page_png(str(pdf_path), 0)
    png_bytes = pathlib.Path(png_res["__file__"]).read_bytes()

    with pw_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 560, "height": 680})

        def route_all(route):
            u = route.request.url
            if "pdf_page=" in u:
                route.fulfill(status=200, content_type="image/png", body=png_bytes)
            elif u.endswith("/html-sv"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html_sv["__html__"])
            elif u.endswith("/md"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=md_doc)
            elif u.endswith("/docx"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=docx_html)
            elif u.endswith("/pdf-sv"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=pdf_sv["__html__"])
            else:
                route.fulfill(status=200, content_type="text/css", body="")

        page.route("**/*", route_all)

        # Verify Markdown & DOCX fit within 560px split pane with zero horizontal overflow
        for path_slug in ("/md", "/docx"):
            page.goto("http://doc.test" + path_slug, wait_until="domcontentloaded")
            page.wait_for_timeout(120)
            m = page.evaluate("({iw: innerWidth, sw: document.documentElement.scrollWidth, z: typeof window.__anchorPdfZoom})")
            assert m["sw"] <= m["iw"] + 1, f"{path_slug} overflowed 560px pane: {m}"
            if path_slug == "/md":
                assert m["z"] == "function"
                assert page.evaluate("window.__anchorPdfZoom(1)") == 115
                assert page.evaluate("window.__anchorPdfZoom(0)") == 100
            else:
                assert "<script>" not in docx_html  # OfficePreviewTest XSS invariant preserved!

        # Verify wide 820px HTML deliverable auto-fits inside 560px split pane (< 100% scale readout)
        page.goto("http://doc.test/html-sv", wait_until="load")
        page.wait_for_function(
            "() => (document.getElementById('htmlZoomReadout') || {}).textContent.indexOf('Fit ') === 0",
            timeout=5000,
        )
        readout = page.locator("#htmlZoomReadout").inner_text()
        assert readout.startswith("Fit ") and "%" in readout, f"Expected auto-scaled Fit readout, got {readout!r}"

        # Verify PDF compact bar (1 row) + Fit Page toggle fits full page height inside 680px pane
        page.goto("http://doc.test/pdf-sv", wait_until="load")
        page.wait_for_selector("img.pdf-page-img", timeout=5000)
        page.wait_for_timeout(150)
        bar_h = page.evaluate("document.querySelector('.pdf-bar').offsetHeight")
        assert bar_h <= 52, f"Expected compact 1-row PDF bar, got {bar_h}px"
        page.locator("#pdfFitToggle").click()
        fit_info = page.evaluate("""() => {
            const st = document.getElementById('pdfStage');
            const img = document.querySelector('.pdf-page-img');
            return { stageH: st.clientHeight, imgH: img.getBoundingClientRect().height, btn: document.getElementById('pdfFitToggle').textContent };
        }""")
        assert fit_info["btn"] == "Fit Width"
        assert fit_info["imgH"] <= fit_info["stageH"], f"Expected Fit Page image height <= stage height: {fit_info}"
        browser.close()





