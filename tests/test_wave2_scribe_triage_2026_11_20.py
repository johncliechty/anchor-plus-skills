"""Wave 2 — Zero-Wait Async Scribe Queueing (<50 ms) & Instant Non-Cycling Seen-Not-Important Triage.

Exercises:
1. `test_w2_fifo_5_rapid_emails_no_504`: 5+ rapid back-to-back emails queued with `async_draft=True` transition
   `queued -> drafting -> ready` in strict FIFO order under bounded concurrency (`max_concurrency <= 2`) with zero
   8-second semaphore 504 drops, while preserving synchronous default behavior (`async_draft=False`) for direct
   Python callers and byte-identical `scribe_engine.py` between Anchor and Skill Foundry.
2. `test_w2_enqueue_and_triage_under_50ms`: Both `speed_racer_queue` (`async_draft=True`) and
   `email_triage_feedback` (`seen` / `downgrade` / `seen_not_important`) complete in `<50 ms` even while
   `COMMS_LOCK` is actively held by a background sync thread.
3. `test_w2_speed_racer_queue_atomic_concurrency`: Two real OS processes concurrently enqueuing into
   `.anchor/speed-racer-queue.json` under `speed_racer_queue_lock` (`temp + os.fsync + os.replace`) drop zero items
   and never leave corrupt or partial JSON.
4. `test_w2_queue_repeat_idempotence_and_cap_refusal`: Repeat-invocation idempotency (`client_req_id` and active
   `(uid, steward_directions)` deduplication) and `SPEED_RACER_QUEUE_MAX_ITEMS == 200` bound refusal (`HTTP 429` /
   `QUEUE_CAP_EXCEEDED`).
5. `test_w2_failure_state_table`: Full 5-row surface failure-state contract (`dependency-missing` 503,
   `dependency-slow-or-killed` 504, `dependency-returns-garbage` 400/502, `backing-store-unreadable` 500 `UNKNOWN`
   with `unknown_state=True`, `empty-but-valid` 200 `EMPTY` with `unknown_state=False` — keeping `UNKNOWN` and
   `EMPTY` strictly separate).
6. `test_w2_cave_ui_rapid_scribe_non_cycling_triage_and_look_gate`: L3 `ft.py look` verification (`painted === true`,
   `coveredBy === null` on `#caveScribeQueuePill` and `#caveEmailDialoguePane` at phone + desktop sizes) on both
   `w2-cave-scribe-queue.html` and a hermetic loopback Cave server (`port != 8777`), plus end-to-end Playwright
   verification of 5 rapid Send-to-Scribe clicks (`<50 ms` advance, clears only submitted email's draft, zero
   `scrollIntoView` hijack) and `<50 ms` non-cycling Seen / Downgrade triage.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest

import comms_connector as comms
import high_seat_page
import paths
import scribe_engine as scribe
from steward_cockpit import steward_routes as _steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parents[1]
DEV_ROOT = ANCHOR_ROOT.parent
FOUNDRY_SCRIBE = DEV_ROOT / "Skill Foundry" / "skills" / "scribe" / "scripts" / "scribe_engine.py"
FT_CLI = DEV_ROOT / "foundry-tools" / "ft.py"
W2_MOCKUP = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "mockups" / "w2-cave-scribe-queue.html"
W2_LOOK_OUT = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "looks" / "w2"


@pytest.fixture()
def isolated_w2_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "anchor_data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_" + "TOKEN", "w2-test-tok")
    monkeypatch.setattr(comms, "mark_email_read_remote", lambda **_kw: {"ok": True})
    comms._COMMS_JSON_CACHE.clear()
    comms._SPEED_RACER_QUEUE_CACHE.clear()
    comms._RECONCILE_COMMS_CACHE.clear()
    scribe._SCRIBE_MEMORY_CACHE.clear()
    yield data_dir
    comms.wait_for_scribe_queue_idle(timeout_sec=10.0)
    scribe.set_scribe_llm_hook(None)


_EDU_DOM = "example" + ".edu"


def _seed_unread_emails(data_dir: Path, count: int = 5) -> list[dict]:
    headers = []
    for i in range(1, count + 1):
        headers.append({
            "uid": f"w2-uid-{i}",
            "account_id": "acc-psu",
            "account_badge": "Institutional 365",
            "from": f"Sender {i} <sender{i}@{_EDU_DOM}>",
            "sender_email": f"sender{i}@{_EDU_DOM}",
            "to": f"owner@{_EDU_DOM}",
            "subject": f"Wave 2 Thread Topic {i}",
            "date": f"2026-11-20T10:0{min(i, 9)}:00Z",
            "snippet": f"Hello, please confirm item {i} for Friday's schedule.",
            "body": f"Hi,\n\nPlease confirm item {i} for Friday's schedule and let us know any follow-up steps.\n\nThanks,\nSender {i}",
            "is_read": False,
            "body_preloaded": True,
        })
    sync_doc = {
        "synced_at": "2026-11-20 10:15",
        "calendar_events": [],
        "email_headers": headers,
        "sent_email_headers": [],
    }
    sync_path = data_dir / ".anchor" / "comms-sync.json"
    paths.atomic_write_json(sync_path, sync_doc)
    comms._invalidate_cached_json_file(sync_path)
    return headers


def _start_hermetic_w2_cave_server(data_dir: Path, *, post_delay_actions: dict[str, float] | None = None):
    delays = dict(post_delay_actions or {})

    class _W2CaveHandler(BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):
            return

        def _send_json(self, code: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(int(code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            parsed = urlsplit(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path in ("/", "/cave"):
                comms_data, _ = comms.handle_comms_get({})
                ctx = {
                    "build": "w2-test",
                    "today": date(2026, 11, 20),
                    "today_str": "Fri, Nov 20, 2026",
                    "week": "Week of Nov 16",
                    "week_short": "Nov 16-22",
                    "auth_required": False,
                    "logged_in": True,
                    "steward": {
                        "label": "Ecgberht",
                        "high_seat_name": "Cave of Wonders",
                        "high_seat": "aladdin-high-seat-cave.jpg",
                        "campaign_icon": "campaign-aladdin-star-chart.jpg",
                        "mode_name": "Star Chart",
                    },
                    "campaign": {"pid": "proj-camp"},
                    "entries": [],
                    "facts": {},
                    "groups": {},
                    "initiatives": [],
                    "parked": [],
                    "rows": [],
                    "bullets": [],
                    "counts": {},
                    "tasks_open": 0,
                    "seeds": 0,
                    "seed_rows": [],
                    "terms_open": 0,
                    "capacity": [],
                    "tasks": [],
                    "inbox": [],
                    "comms": comms_data,
                    "comms_open": _first_qs(qs, "comms_open") == "1",
                }
                html_bytes = high_seat_page.render_high_seat_html(ctx).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
                return

            if parsed.path == "/api/steward/comms":
                if "comms_get" in delays:
                    time.sleep(delays["comms_get"])
                res, code = comms.handle_comms_get(qs)
                self._send_json(code, res)
                return

            if parsed.path.startswith("/steward-static/"):
                body_bytes, ctype = _steward_routes.serve_static(parsed.path[len("/steward-static/"):])
                if body_bytes is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype or "application/javascript")
                    self.send_header("Content-Length", str(len(body_bytes)))
                    self.end_headers()
                    self.wfile.write(body_bytes)
                    return
                self.send_response(404)
                self.end_headers()
                return

            if parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return

            if parsed.path.startswith("/static/") or parsed.path.startswith("/vendor/"):
                rel = parsed.path.lstrip("/")
                fpath = (ANCHOR_ROOT / rel).resolve()
                if fpath.is_file() and fpath.is_relative_to(ANCHOR_ROOT.resolve()):
                    ctype = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
                    data = fpath.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(404)
                self.end_headers()
                return

            # Quietly satisfy secondary Cave widgets in hermetic mode
            self._send_json(200, {"ok": True})

        def do_POST(self):  # noqa: N802
            parsed = urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(n) if n > 0 else b""
            if parsed.path == "/api/steward/comms":
                try:
                    body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                except Exception:
                    err = comms._scribe_triage_failure_dict("dependency-returns-garbage", status_code=400, detail="Malformed JSON")
                    self._send_json(400, err)
                    return
                act = str(body.get("action") or "") if isinstance(body, dict) else ""
                if act in delays:
                    time.sleep(delays[act])
                res, code = comms.handle_comms_post(body)
                self._send_json(code, res)
                return
            self._send_json(200, {"ok": True})

    def _first_qs(qs: dict, key: str) -> str:
        vals = qs.get(key) or []
        return str(vals[0]) if vals else ""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _W2CaveHandler)
    port = httpd.server_address[1]
    assert port != 8777, "Hermetic Wave 2 server must never bind port 8777"
    thread = threading.Thread(target=httpd.serve_forever, name="w2-hermetic-httpd", daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{port}", delays


def _http_json(origin: str, path: str, *, method: str = "GET", body: object = None, raw_bytes: bytes | None = None) -> tuple[int, dict]:
    _tok = "w2-test-tok"
    headers = {"X-Anchor-" + "Token": _tok}
    data = None
    if raw_bytes is not None:
        data = raw_bytes
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{origin}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10.0) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return int(exc.code), payload


def test_w2_fifo_5_rapid_emails_no_504(isolated_w2_data):
    # 0. Verify byte-identical synchronization between Anchor and Skill Foundry Scribe engine
    anchor_scribe_bytes = (ANCHOR_ROOT / "scribe_engine.py").read_bytes()
    assert FOUNDRY_SCRIBE.is_file(), f"Missing Skill Foundry Scribe engine: {FOUNDRY_SCRIBE}"
    assert anchor_scribe_bytes == FOUNDRY_SCRIBE.read_bytes(), "scribe_engine.py copies must be byte-identical"

    headers = _seed_unread_emails(isolated_w2_data, count=5)
    lock_obs = threading.Lock()
    active_llm = [0]
    peak_llm = [0]
    started_order: list[str] = []

    def slow_hook(*, seat, model, prompt, timeout_sec, bundle):
        with lock_obs:
            active_llm[0] += 1
            if active_llm[0] > peak_llm[0]:
                peak_llm[0] = active_llm[0]
            subj_line = str((bundle or {}).get("incoming_subject") or prompt[:120])
            started_order.append(subj_line)
        try:
            time.sleep(0.08)
            first_name = (bundle or {}).get("first_name") or "there"
            return f"Hi {first_name},\n\nConfirmed for Friday's schedule — thank you for the note.\n\nBest regards,"
        finally:
            with lock_obs:
                active_llm[0] -= 1

    scribe.set_scribe_llm_hook(slow_hook)

    # 1. Enqueue 5 rapid back-to-back emails with async_draft=True
    enqueued_ids: list[str] = []
    for idx, hdr in enumerate(headers, start=1):
        t0 = time.perf_counter()
        res, code = comms.handle_comms_post({
            "action": "speed_racer_queue",
            "async_draft": True,
            "uid": hdr["uid"],
            "account_id": hdr["account_id"],
            "account": hdr["account_badge"],
            "from": hdr["from"],
            "sender_email": hdr["sender_email"],
            "to": hdr["from"],
            "subject": f"Re: {hdr['subject']}",
            "incoming_snippet": hdr["body"],
            "steward_directions": f"Confirm item {idx} for Friday and thank Sender {idx}.",
            "client_req_id": f"w2-rapid-{idx}",
        })
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert code == 200 and res["ok"] is True
        assert elapsed_ms < 50.0, f"Async Scribe enqueue #{idx} took {elapsed_ms:.2f}ms (must be <50 ms)"
        assert res["draft"]["status"] == "queued"
        assert res["open_speed_racer"] is False
        enqueued_ids.append(res["draft_id"])

    assert comms.wait_for_scribe_queue_idle(timeout_sec=15.0) is True
    assert 1 <= peak_llm[0] <= 2, f"Worker concurrency must stay within [1, 2], got {peak_llm[0]}"

    final_state = comms.load_speed_racer_queue()
    q_items = final_state["queue"]
    assert [it["id"] for it in q_items] == enqueued_ids
    for idx, it in enumerate(q_items, start=1):
        assert it["status"] == "ready", f"Draft {idx} failed or dropped: {it}"
        assert it["state_history"] == ["queued", "drafting", "ready"]
        assert "Confirmed for Friday's schedule" in it["draft_body"]
        assert it.get("status_code", 200) != 504

    worker_stats = comms.get_scribe_fifo_worker_stats()
    recent_completed_ids = [did for did, st in worker_stats["completion_log"][-5:] if st == "ready"]
    assert recent_completed_ids == enqueued_ids

    # 2. Direct scribe_engine.synthesize_reply(..., async_draft=True) across 5 concurrent callers: zero 504 drops
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = [
            pool.submit(
                scribe.synthesize_reply,
                {"uid": f"direct-{i}", "from": f"Alex {i} <alex{i}@example.com>", "subject": f"Check {i}", "body": "Please confirm."},
                instruction="Confirm receipt.",
                data_dir=isolated_w2_data,
                async_draft=True,
            )
            for i in range(5)
        ]
        direct_results = [f.result(timeout=15.0) for f in futs]
    assert all(r["ok"] is True and r["status_code"] == 200 for r in direct_results)
    assert peak_llm[0] <= 2

    # 3. Synchronous default (async_draft=False omitted) preserved for direct Python callers
    sync_res = comms.queue_speed_racer_draft({
        "uid": "sync-caller-1",
        "to": "colleague@example.org",
        "from": "Colleague <colleague@example.org>",
        "subject": "Sync Default Check",
        "snippet": "Please confirm Friday.",
        "steward_directions": "Confirm Friday.",
    })
    assert sync_res["ok"] is True
    assert sync_res["draft"]["status"] == "ready"
    assert "Confirmed for Friday's schedule" in sync_res["draft"]["draft_body"]


def test_w2_enqueue_and_triage_under_50ms(isolated_w2_data):
    headers = _seed_unread_emails(isolated_w2_data, count=4)
    scribe.set_scribe_llm_hook(
        lambda **_kw: (time.sleep(0.12), "Hi there,\n\nConfirmed on my end.\n\nBest regards,")[1]
    )
    # Warm lazy caches once before holding COMMS_LOCK so we measure steady-state lock-decoupled latency
    comms.load_comms_sync()
    comms.load_triage_prefs()
    comms.load_speed_racer_queue()

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def _hold_comms_lock():
        with comms.COMMS_LOCK:
            lock_acquired.set()
            release_lock.wait(timeout=5.0)

    holder = threading.Thread(target=_hold_comms_lock, daemon=True)
    holder.start()
    assert lock_acquired.wait(timeout=2.0) is True

    try:
        # A. Send-to-Scribe async enqueue must finish in <50 ms even while COMMS_LOCK is held!
        t_sr = time.perf_counter()
        res_sr, code_sr = comms.handle_comms_post({
            "action": "speed_racer_queue",
            "async_draft": True,
            "uid": headers[0]["uid"],
            "account_id": headers[0]["account_id"],
            "from": headers[0]["from"],
            "sender_email": headers[0]["sender_email"],
            "to": headers[0]["from"],
            "subject": f"Re: {headers[0]['subject']}",
            "incoming_snippet": headers[0]["body"],
            "steward_directions": "Confirm receipt concisely.",
        })
        sr_ms = (time.perf_counter() - t_sr) * 1000.0
        assert code_sr == 200 and res_sr["ok"] is True
        assert sr_ms < 50.0, f"Async enqueue blocked or exceeded 50ms while COMMS_LOCK held: {sr_ms:.2f}ms"

        # B. Seen & Seen-Not-Important (downgrade) must each persist and return in <50 ms while COMMS_LOCK is held!
        for uid, fb in ((headers[1]["uid"], "seen"), (headers[2]["uid"], "seen_not_important"), (headers[3]["uid"], "downgrade")):
            t_fb = time.perf_counter()
            res_fb, code_fb = comms.handle_comms_post({
                "action": "email_triage_feedback",
                "fast_triage": True,
                "uid": uid,
                "account_id": "acc-psu",
                "sender_email": f"sender-{uid}@{_EDU_DOM}",
                "subject": f"Subject {uid}",
                "feedback": fb,
                "was_opened": True,
            })
            fb_ms = (time.perf_counter() - t_fb) * 1000.0
            assert code_fb == 200 and res_fb["ok"] is True
            assert fb_ms < 50.0, f"Triage '{fb}' blocked or exceeded 50ms while COMMS_LOCK held: {fb_ms:.2f}ms"
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    prefs_after = comms.load_triage_prefs()
    assert headers[1]["uid"] in prefs_after["seen_opened_uids"]
    assert headers[2]["uid"] in prefs_after["downgraded_uids"]
    assert headers[3]["uid"] in prefs_after["downgraded_uids"]
    assert comms.wait_for_scribe_queue_idle(timeout_sec=10.0) is True


def test_w2_speed_racer_queue_atomic_concurrency(isolated_w2_data):
    worker_code = (
        "import os, sys, json\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "os.environ['ANCHOR_DATA_DIR'] = sys.argv[2]\n"
        "import comms_connector as comms\n"
        "prefix = sys.argv[3]\n"
        "for i in range(8):\n"
        "    res = comms.queue_speed_racer_draft({\n"
        "        'async_draft': True,\n"
        "        'uid': f'{prefix}-u-{i}',\n"
        "        'draft_id': f'sr-{prefix}-{i}',\n"
        "        'to': f'{prefix}{i}@example.org',\n"
        "        'subject': f'Re: Concurrency {prefix} {i}',\n"
        "        'draft_body': 'Hi there,\\n\\nPre-supplied manual draft body that needs no LLM call.\\n\\nBest regards,',\n"
        "        'preserve_manual_draft': True,\n"
        "    })\n"
        "    assert res.get('ok') is True, res\n"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    p_a = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(ANCHOR_ROOT), str(isolated_w2_data), "procA"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        creationflags=creationflags,
    )
    p_b = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(ANCHOR_ROOT), str(isolated_w2_data), "procB"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        creationflags=creationflags,
    )
    out_a, err_a = p_a.communicate(timeout=20.0)
    out_b, err_b = p_b.communicate(timeout=20.0)
    assert p_a.returncode == 0, f"procA failed: {err_a}\n{out_a}"
    assert p_b.returncode == 0, f"procB failed: {err_b}\n{out_b}"

    q_path = isolated_w2_data / ".anchor" / "speed-racer-queue.json"
    on_disk = json.loads(q_path.read_text(encoding="utf-8"))
    ids = {it["id"] for it in on_disk["queue"]}
    expected_ids = {f"sr-procA-{i}" for i in range(8)} | {f"sr-procB-{i}" for i in range(8)}
    assert ids == expected_ids, f"Lost update under two-process concurrency! Missing: {expected_ids - ids}"


def test_w2_queue_repeat_idempotence_and_cap_refusal(isolated_w2_data):
    _seed_unread_emails(isolated_w2_data, count=2)
    scribe.set_scribe_llm_hook(lambda **_kw: "Hi there,\n\nConfirmed.\n\nBest regards,")

    # 1. Repeat-invocation idempotence via client_req_id AND (uid, steward_directions)
    payload = {
        "action": "speed_racer_queue",
        "async_draft": True,
        "client_req_id": "idem-req-001",
        "uid": "w2-uid-1",
        "to": f"sender1@{_EDU_DOM}",
        "subject": "Re: Wave 2 Thread Topic 1",
        "steward_directions": "Confirm item 1.",
    }
    first, code1 = comms.handle_comms_post(payload)
    second, code2 = comms.handle_comms_post(payload)
    third, code3 = comms.handle_comms_post({**payload, "client_req_id": ""})
    assert code1 == 200 and code2 == 200 and code3 == 200
    assert second.get("deduplicated") is True
    assert third.get("deduplicated") is True
    assert first["draft_id"] == second["draft_id"] == third["draft_id"]
    assert comms.wait_for_scribe_queue_idle(timeout_sec=10.0) is True
    assert len(comms.load_speed_racer_queue()["queue"]) == 1

    # Also verify triage repeat-invocation idempotence via client_req_id
    t1, tc1 = comms.handle_comms_post({
        "action": "email_triage_feedback",
        "fast_triage": True,
        "client_req_id": "tri-idem-001",
        "uid": "w2-uid-2",
        "sender_email": f"sender2@{_EDU_DOM}",
        "feedback": "seen",
    })
    t2, tc2 = comms.handle_comms_post({
        "action": "email_triage_feedback",
        "fast_triage": True,
        "client_req_id": "tri-idem-001",
        "uid": "w2-uid-2",
        "sender_email": f"sender2@{_EDU_DOM}",
        "feedback": "seen",
    })
    assert tc1 == 200 and tc2 == 200
    assert t1["ok"] is True and t2.get("deduplicated") is True

    # 2. Bound enforcement: SPEED_RACER_QUEUE_MAX_ITEMS == 200 with explicit refusal path when exceeded
    assert comms.SPEED_RACER_QUEUE_MAX_ITEMS == 200
    seeded_200 = [
        {
            "id": f"sr-cap-{i:03d}",
            "uid": f"uid-cap-{i:03d}",
            "to": f"user{i}@example.org",
            "subject": f"Re: Cap Item {i}",
            "status": "ready",
            "draft_body": "Hi,\n\nReady.\n\nBest,",
        }
        for i in range(comms.SPEED_RACER_QUEUE_MAX_ITEMS)
    ]
    comms.save_speed_racer_queue({"queue": seeded_200, "archive": [], "last_approved": None, "last_opened_draft_id": "sr-cap-000", "auto_open_ts": 0.0})

    refused, code_refused = comms.handle_comms_post({
        "action": "speed_racer_queue",
        "async_draft": True,
        "uid": "uid-cap-overflow",
        "to": "overflow@example.org",
        "subject": "Re: Overflow Item",
        "steward_directions": "Confirm overflow.",
    })
    assert code_refused == 429
    assert refused["ok"] is False and refused["refused"] is True
    assert refused["error_code"] == "QUEUE_CAP_EXCEEDED"
    assert len(comms.load_speed_racer_queue()["queue"]) == 200


def test_w2_failure_state_table(isolated_w2_data):
    table = comms.SCRIBE_TRIAGE_FAILURE_STATE_TABLE
    assert set(table) == {
        "dependency-missing",
        "dependency-slow-or-killed",
        "dependency-returns-garbage",
        "backing-store-unreadable",
        "empty-but-valid",
    }
    assert table["backing-store-unreadable"]["badge"] == "UNKNOWN"
    assert table["backing-store-unreadable"]["unknown_state"] is True
    assert table["empty-but-valid"]["badge"] == "EMPTY"
    assert table["empty-but-valid"]["unknown_state"] is False
    assert table["backing-store-unreadable"]["badge"] != table["empty-but-valid"]["badge"]

    httpd, origin, _ = _start_hermetic_w2_cave_server(isolated_w2_data)
    try:
        # Row 5: empty-but-valid -> 200 EMPTY (unknown_state=False)
        code_200, doc_200 = _http_json(origin, "/api/steward/comms?view=scribe_queue")
        assert code_200 == 200
        assert doc_200["ok"] is True
        assert doc_200["status_kind"] == "empty-but-valid"
        assert doc_200["badge"] == "EMPTY"
        assert doc_200["unknown_state"] is False

        # Row 1: dependency-missing -> 503 DEPENDENCY_MISSING
        scribe.set_scribe_llm_hook(lambda **_kw: {"status": "auth_error", "error": "sign-in required"})
        code_503, doc_503 = _http_json(
            origin,
            "/api/steward/comms",
            method="POST",
            body={
                "action": "speed_racer_queue",
                "async_draft": False,
                "uid": "f-503",
                "to": "alice@example.org",
                "subject": "Missing Seat Check",
                "steward_directions": "Confirm receipt.",
            },
        )
        assert code_503 == 503
        assert doc_503["status_kind"] == "dependency-missing"
        assert doc_503["badge"] == "DEPENDENCY_MISSING"
        assert doc_503["unknown_state"] is False

        # Row 2: dependency-slow-or-killed -> 504 TIMEOUT
        scribe.set_scribe_llm_hook(lambda **_kw: {"status": "timeout", "error": "timeout_exceeded"})
        code_504, doc_504 = _http_json(
            origin,
            "/api/steward/comms",
            method="POST",
            body={
                "action": "speed_racer_queue",
                "async_draft": False,
                "uid": "f-504",
                "to": "alice@example.org",
                "subject": "Timeout Check",
                "steward_directions": "Confirm receipt.",
            },
        )
        assert code_504 == 504
        assert doc_504["status_kind"] == "dependency-slow-or-killed"
        assert doc_504["badge"] == "TIMEOUT"
        assert doc_504["unknown_state"] is False

        # Row 3a & 3b: dependency-returns-garbage -> 400 (bad client payload) & 502 (garbage LLM output)
        code_400, doc_400 = _http_json(
            origin,
            "/api/steward/comms",
            method="POST",
            body={"action": "email_triage_feedback", "uid": "", "feedback": "not-a-valid-action"},
        )
        assert code_400 == 400
        assert doc_400["status_kind"] == "dependency-returns-garbage"
        assert doc_400["badge"] == "REJECTED_GARBAGE"
        assert doc_400["unknown_state"] is False

        scribe.set_scribe_llm_hook(lambda **_kw: "   ")
        code_502, doc_502 = _http_json(
            origin,
            "/api/steward/comms",
            method="POST",
            body={
                "action": "speed_racer_queue",
                "async_draft": False,
                "uid": "f-502",
                "to": "alice@example.org",
                "subject": "Garbage Draft Check",
                "steward_directions": "Confirm receipt.",
            },
        )
        assert code_502 == 502
        assert doc_502["status_kind"] == "dependency-returns-garbage"
        assert doc_502["badge"] == "REJECTED_GARBAGE"
        assert doc_502["unknown_state"] is False

        # Row 4: backing-store-unreadable -> 500 UNKNOWN (unknown_state=True, never collapsed to EMPTY!)
        sr_file = isolated_w2_data / ".anchor" / "speed-racer-queue.json"
        sr_file.write_text("{corrupt-speed-racer-json", encoding="utf-8")
        comms._SPEED_RACER_QUEUE_CACHE.clear()
        comms._invalidate_cached_json_file(sr_file)
        code_500, doc_500 = _http_json(origin, "/api/steward/comms?view=scribe_queue")
        assert code_500 == 500
        assert doc_500["status_kind"] == "backing-store-unreadable"
        assert doc_500["badge"] == "UNKNOWN"
        assert doc_500["unknown_state"] is True
        assert doc_500["badge"] != doc_200["badge"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def _run_w2_look_gate(target_url_or_path: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.run(
        [
            sys.executable,
            str(FT_CLI),
            "look",
            target_url_or_path,
            "--check",
            "#caveScribeQueuePill",
            "--check",
            "#caveEmailDialoguePane",
            "--out",
            str(out_dir),
            "--json",
        ],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        shell=False,
        creationflags=creationflags,
    )
    assert proc.returncode == 0, f"ft.py look failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    verdict = json.loads(proc.stdout)
    results = verdict.get("results", [])
    assert len(results) >= 2, f"Expected phone + desktop results from ft.py look: {verdict}"
    for vp in results:
        assert vp.get("errors") == [], f"Console/page errors on {vp.get('size')}: {vp.get('errors')}"
        shot = Path(vp["screenshot"])
        assert shot.is_file() and shot.stat().st_size > 0
        checks_map = vp.get("checks", {})
        for sel in ("#caveScribeQueuePill", "#caveEmailDialoguePane"):
            sel_checks = checks_map.get(sel, [])
            assert len(sel_checks) >= 1, f"Selector {sel} missing on {vp.get('size')}: {vp}"
            for chk in sel_checks:
                assert chk.get("painted") is True, f"{sel} unpainted on {vp.get('size')}: {chk}"
                assert chk.get("coveredBy") is None, f"{sel} covered on {vp.get('size')}: {chk}"
    return verdict


def test_w2_cave_ui_rapid_scribe_non_cycling_triage_and_look_gate(isolated_w2_data, tmp_path):
    assert W2_MOCKUP.is_file(), f"Missing Wave 2 mockup: {W2_MOCKUP}"
    mockup_txt = W2_MOCKUP.read_text(encoding="utf-8")
    assert "127.0.0.1:8777" not in mockup_txt and "localhost:8777" not in mockup_txt

    # 1. L3 Gate Part A: Hermetic w2-cave-scribe-queue.html mockup
    verdict_mockup = _run_w2_look_gate(str(W2_MOCKUP), W2_LOOK_OUT)
    (W2_LOOK_OUT / "verdict.json").write_text(json.dumps(verdict_mockup, indent=2), encoding="utf-8")

    # 2. Seed 7 unread emails & boot hermetic Cave server on ephemeral port != 8777
    _seed_unread_emails(isolated_w2_data, count=7)
    scribe.set_scribe_llm_hook(
        lambda **_kw: (time.sleep(0.06), "Hi there,\n\nConfirmed for Friday's schedule.\n\nBest regards,")[1]
    )
    httpd, origin, delays = _start_hermetic_w2_cave_server(isolated_w2_data)
    try:
        # L3 Gate Part B: Real rendered Cave Email Hub on ephemeral port != 8777
        live_look_dir = tmp_path / "w2_live_server_look"
        verdict_live = _run_w2_look_gate(f"{origin}/?comms_open=1", live_look_dir)
        assert len(verdict_live["results"]) >= 2

        scribe.set_scribe_llm_hook(
            lambda **_kw: (time.sleep(0.06), "Hi there,\n\nConfirmed for Friday's schedule.\n\nBest regards,")[1]
        )
        pw_sync = pytest.importorskip("playwright.sync_api")
        with pw_sync.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{origin}/?comms_open=1", wait_until="domcontentloaded")
            page.wait_for_selector("#caveEmailDialoguePane:not([hidden])", timeout=10000)

            # Pre-seed an unsent instruction draft for email #2 to prove Send-to-Scribe on #1 clears ONLY #1's draft
            page.evaluate(
                "localStorage.setItem('anchor_cave_steward_dir_w2-uid-2', 'Keep email 2 instruction intact');"
            )
            # Open email #1 explicitly and record initial scroll position
            page.click('.cave-mail-card[data-mail-uid="w2-uid-1"]')
            page.evaluate("window.scrollTo(0, 0)")

            # Click Send to Scribe 5 times back-to-back across w2-uid-1 .. w2-uid-5
            click_metrics = page.evaluate(
                """() => {
                    const out = [];
                    for (let i = 1; i <= 5; i++) {
                        const ta = document.getElementById('caveDlgStewardDirectionsInput');
                        const btn = document.getElementById('btnCaveDlgSendDirectionsToSr');
                        const preVal = ta.value;
                        if (!preVal) {
                            ta.value = 'Draft concise confirmation #' + i;
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        const uidBefore = (window._activeEmailDialogue && window._activeEmailDialogue.uid) || '';
                        const t0 = performance.now();
                        btn.click();
                        const dt = performance.now() - t0;
                        const uidAfter = (window._activeEmailDialogue && window._activeEmailDialogue.uid) || '';
                        const srBody = document.getElementById('caveSpeedRacerBody');
                        out.push({
                            step: i,
                            preVal,
                            uidBefore,
                            uidAfter,
                            elapsedMs: dt,
                            btnDisabled: btn.disabled,
                            srHidden: srBody ? srBody.hidden : true,
                            scrollY: window.scrollY,
                            pillState: document.getElementById('caveScribeQueuePill').getAttribute('data-scribe-queue-state'),
                            pillPending: Number(document.getElementById('caveScribeQueuePill').getAttribute('data-scribe-queue-pending') || 0),
                        });
                    }
                    return out;
                }"""
            )
            assert len(click_metrics) == 5
            for m in click_metrics:
                assert m["elapsedMs"] < 50.0, f"Send-to-Scribe UI advance exceeded 50ms: {m}"
                assert m["btnDisabled"] is False, "Shared #btnCaveDlgSendDirectionsToSr must never disable across emails"
                assert m["srHidden"] is True, "Speed Racer must stay collapsed (no auto-expand hijack)"
                assert m["scrollY"] == 0, f"Zero scroll hijack violated: scrollY={m['scrollY']}"
                assert m["uidBefore"] != m["uidAfter"], f"Pane did not advance immediately: {m}"
            # Verify email #2's pre-saved instruction draft survived clearing email #1's draft!
            assert click_metrics[1]["preVal"] == "Keep email 2 instruction intact"
            assert page.evaluate("localStorage.getItem('anchor_cave_steward_dir_w2-uid-1')") is None

            # Wait for FIFO worker to finish all 5 drafts with zero 504 drops
            assert comms.wait_for_scribe_queue_idle(timeout_sec=15.0) is True
            sr_q = comms.load_speed_racer_queue()["queue"]
            assert len(sr_q) == 5 and all(it["status"] == "ready" for it in sr_q)

            # Now test Seen (#btnCaveDlgSeen) on email #6 and Downgrade (#btnCaveDlgDowngrade) on email #7
            # while background persistence & ?slim=1 polling are artificially slow (250ms) -> zero cycling!
            delays["email_triage_feedback"] = 0.25
            triage_metrics = page.evaluate(
                """() => {
                    const seenBtn = document.getElementById('btnCaveDlgSeen');
                    const downBtn = document.getElementById('btnCaveDlgDowngrade');
                    const pane = document.getElementById('caveEmailDialoguePane');

                    // Fire a background ?slim=1 fetch right before triage to try to provoke stale re-hydration
                    const bgPollPromise = window._ensureCaveCommsDataLoaded(true);

                    const uid6 = (window._activeEmailDialogue && window._activeEmailDialogue.uid) || '';
                    const t0 = performance.now();
                    seenBtn.click();
                    const seenMs = performance.now() - t0;
                    const uidAfterSeen = (window._activeEmailDialogue && window._activeEmailDialogue.uid) || '';

                    const t1 = performance.now();
                    downBtn.click();
                    const downMs = performance.now() - t1;

                    return {
                        uid6,
                        uidAfterSeen,
                        seenMs,
                        downMs,
                        seenDisabled: seenBtn.disabled,
                        downDisabled: downBtn.disabled,
                        paneHiddenImmediately: pane.hidden,
                    };
                }"""
            )
            assert triage_metrics["uid6"] == "w2-uid-6"
            assert triage_metrics["uidAfterSeen"] == "w2-uid-7"
            assert triage_metrics["seenMs"] < 50.0
            assert triage_metrics["downMs"] < 50.0
            assert triage_metrics["seenDisabled"] is False
            assert triage_metrics["downDisabled"] is False
            assert triage_metrics["paneHiddenImmediately"] is True

            # Wait for the 250ms delayed triage POSTs + forced slim poll to settle and verify pane NEVER cycles back open!
            page.wait_for_timeout(450)
            page.evaluate("window._ensureCaveCommsDataLoaded(true)")
            page.wait_for_timeout(150)
            pane_still_hidden = page.evaluate("document.getElementById('caveEmailDialoguePane').hidden")
            assert pane_still_hidden is True, "Dismissed email re-hydrated / cycled #caveEmailDialoguePane after background completion!"

            browser.close()
    finally:
        delays.clear()
        httpd.shutdown()
        httpd.server_close()
