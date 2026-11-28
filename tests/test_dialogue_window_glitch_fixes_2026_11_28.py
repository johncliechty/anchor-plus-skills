"""Regression tests for dialogue window anti-glitch fixes (2026-11-28).

Covers:
1. AI Cockpit `shared.js:poll()` backs off cleanly on HTTP 404 / non-OK / malformed
   responses instead of spinning in a 0ms infinite fetch loop that starves WebView2's
   per-origin connection pool across open dialogue windows.
2. AI Cockpit 1s/2.5s ticks (`updateState`, `renderFiles`, `cockpit-wave-map`,
   `cockpit-deliverable-shelves`, `renderStatus._lastRefreshEta`) preserve existing
   DOM nodes and do not spam identical `postMessage` frames or yank `.scroll` when
   the user has scrolled up while typing in `[data-say]`.
3. Cave Steward dialogue (`high-seat-page.js` + `steward-dialogue.js`) preserves
   upward scroll position (`_follow === false`) across typing in `#say` and window
   resizes, while still following at the bottom when `_follow === true`.
4. 30-second code-job / skill-job supervision heartbeats (`observed_at`, `activity_at`)
   do not rewrite `.ecgberht/code-jobs.json` unnecessarily or oscillate `map_stamp()`.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from steward_cockpit import code_job_handoff as ch
from steward_cockpit import code_jobs as cj
from steward_cockpit import steward_campaign as campaign
from steward_cockpit import steward_routes


def _start_server(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, port


def test_code_job_supervision_heartbeat_does_not_oscillate_map_stamp(tmp_path, monkeypatch):
    cdir = tmp_path / "Cave of Wonders"
    (cdir / ".ecgberht").mkdir(parents=True)
    (cdir / "ECGBERHT.md").write_text("# Cave\n", encoding="utf-8")

    now = [1_700_000_000.0]
    monkeypatch.setattr(ch.time, "time", lambda: now[0])
    monkeypatch.setattr(
        ch,
        "observe",
        lambda job: {"state": "active", "last_activity": now[0] - 5.0},
    )

    jobs_path = cdir / ".ecgberht" / "code-jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "job-1": {
                    "id": "job-1",
                    "attempt": 1,
                    "status": "running",
                    "phase": "producing",
                    "phase_at": now[0] - 60.0,
                    "steward_dir": str(cdir),
                    "started": "2026-11-28 06:30:00",
                }
            }
        ),
        encoding="utf-8",
    )

    # Initial supervision pass persists baseline supervision state.
    ch.refresh_supervision(cdir)
    stamp_initial = campaign.map_stamp(str(cdir))
    mtime_initial = jobs_path.stat().st_mtime_ns

    # 35s later: worker is still active with only heartbeat timestamps advancing.
    now[0] += 35.0
    ch.refresh_supervision(cdir)
    assert jobs_path.stat().st_mtime_ns == mtime_initial
    assert campaign.map_stamp(str(cdir)) == stamp_initial

    # Even if an external writer updates volatile heartbeat keys + mtime + size,
    # map_stamp remains stable.
    data = json.loads(jobs_path.read_text(encoding="utf-8"))
    data["job-1"]["supervision"]["observed_at"] = now[0] + 123.456789
    data["job-1"]["supervision"]["activity_at"] = now[0] + 120.123456
    time.sleep(0.01)
    jobs_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert jobs_path.stat().st_mtime_ns != mtime_initial
    assert campaign.map_stamp(str(cdir)) == stamp_initial

    # Real semantic transition MUST advance map_stamp.
    data["job-1"]["supervision"]["state"] = "needs_inspection"
    time.sleep(0.01)
    jobs_path.write_text(json.dumps(data), encoding="utf-8")
    assert campaign.map_stamp(str(cdir)) != stamp_initial


def test_cockpit_poll_404_backs_off_without_flooding(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    events_hits: list[float] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            if p == "/steward/v1":
                doc = steward_routes.serve_page_doc("v1", pid="proj1", effort_dir="Paper 1")
                body = doc.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if p.startswith("/steward-static/"):
                raw, ctype = steward_routes.serve_static(p.split("/steward-static/", 1)[1])
                if raw is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
            if p == "/api/version":
                return self._json(200, {"version": "test-v1", "boot": "1000"})
            if p == "/api/steward/events":
                events_hits.append(time.monotonic())
                return self._json(404, {"error": "unknown effort"})
            if p.startswith("/api/steward/"):
                return self._json(404, {"error": "unknown effort"})
            self.send_response(404)
            self.end_headers()

    srv, port = _start_server(Handler)
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/steward/v1?pid=proj1&dir=Paper%201", wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            # Previously fired 60-200+ requests in 2.2s; with backoff it must be <= 2.
            assert 1 <= len(events_hits) <= 2, f"Expected <=2 /api/events polls in 2.2s, got {len(events_hits)}"
            # Wait past first 3s retry so second 404 surfaces the single calm notice.
            page.wait_for_timeout(1400)
            assert len(events_hits) <= 3
            sys_txt = page.locator(".scroll").inner_text()
            assert "renamed or archived" in sys_txt
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_cockpit_1s_tick_preserves_dom_and_scroll_while_typing():
    pw = pytest.importorskip("playwright.sync_api")

    turns = [
        {"role": "john" if i % 2 == 0 else "steward", "text": f"Message line {i} " + ("detail " * 18), "ts": "06:30"}
        for i in range(30)
    ]
    state_payload = {
        "ok": True,
        "alive": True,
        "busy": False,
        "queued": 0,
        "epoch": 1,
        "stamp": "st-1",
        "cli": "gemini",
        "turns": 15,
        "tokens": 42000,
        "token_status": "reported",
        "spend_usd": 1.25,
        "reported_spend_usd": 1.25,
        "cost_status": "reported",
        "secs": 180,
        "files": ["notes/analysis.md", "outputs/summary.pdf"],
        "pending_questions": [],
        "usage_rollup": {
            "ok": True,
            "total": {
                "reported_spend": 1.25,
                "estimated_spend": 0.0,
                "tokens": 42000,
                "token_status": "reported",
                "cost_status": "reported",
                "cost_complete": True,
                "turns": 15,
                "secs": 180,
            },
        },
    }
    wave_map_payload = {
        "ok": True,
        "counts": {"done": 1, "total": 2},
        "all_done": False,
        "goal_brief": "Mixture of Experts empirical demand",
        "folder_path": "C:/dev/HEDML/Mixture of Experts",
        "recent_history": [{"text": "Completed intake review", "ago": "5m ago"}],
        "current_wave": {
            "step_id": "w2",
            "wave_num": 2,
            "total_waves": 2,
            "round": 1,
            "title": "Run Sean-to-Jason specification check",
            "goal": "Verify MoE baseline",
        },
        "coming_next": [],
    }
    map_payload = {
        "ok": True,
        "name": "Mixture of Experts",
        "goal": "Mixture of Experts empirical demand",
        "steps": [
            {"id": "w1", "title": "Intake", "status": "done"},
            {"id": "w2", "title": "Run Sean-to-Jason specification check", "status": "active"},
        ],
        "wave_map": wave_map_payload,
        "stamp": "st-1",
    }
    deliv_payload = {
        "ok": True,
        "exists": True,
        "items": [
            {"path": "notes/analysis.md", "what": "Sean Email Analysis", "date": "2026-11-28", "is_current": True}
        ],
        "shelves": {
            "most_recent_batches": [
                {
                    "batch_id": "b1",
                    "rank_label": "Last Instruction",
                    "turn_num": 15,
                    "ago": "2m ago",
                    "instruction_excerpt": "Analyze email from Sean to Jason",
                    "file_count": 1,
                    "items": [{"path": "notes/analysis.md", "what": "Sean Email Analysis", "date": "2026-11-28"}],
                }
            ],
            "final": [],
            "earlier": [],
        },
    }
    status_payload = {
        "ok": True,
        "latest": {
            "id": "stat-1",
            "at": "2026-11-28 06:35:00",
            "doing": "Checking Mixture of Experts run",
            "eta": "12m -> 25m -> 45m",
            "steps_done": 1,
            "steps_total": 2,
            "attention": "working",
        },
        "history": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            if p == "/steward/v1":
                doc = steward_routes.serve_page_doc("v1", pid="proj1", effort_dir="Mixture of Experts")
                body = doc.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if p.startswith("/steward-static/"):
                raw, ctype = steward_routes.serve_static(p.split("/steward-static/", 1)[1])
                if raw is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
            if p == "/api/version":
                return self._json(200, {"version": "test-v1", "boot": "1000"})
            if p == "/api/steward/map":
                return self._json(200, map_payload)
            if p == "/api/steward/wave-state":
                return self._json(200, wave_map_payload)
            if p == "/api/steward/plan":
                return self._json(200, {"ok": True, "steps": map_payload["steps"]})
            if p == "/api/steward/state":
                return self._json(200, state_payload)
            if p == "/api/steward/history":
                return self._json(200, {"ok": True, "turns": turns})
            if p == "/api/steward/deliverables":
                return self._json(200, deliv_payload)
            if p == "/api/steward/status":
                return self._json(200, status_payload)
            if p == "/api/steward/drafts":
                return self._json(200, {"ok": True, "draft": "", "badge": "EMPTY"})
            if p == "/api/steward/events":
                time.sleep(0.35)
                return self._json(200, {"events": [], "state": state_payload, "oldest_seq": 0, "gap": False, "stamp": "st-1"})
            return self._json(200, {"ok": True})

        def do_POST(self):
            return self._json(200, {"ok": True, "badge": "SAVED"})

    srv, port = _start_server(Handler)
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 860})
            # Host inside an outer page so window.parent !== window and postMessage spam is measurable.
            outer_html = (
                "<!doctype html><html><body style='margin:0'>"
                "<script>window.__stateMsgs=0;window.addEventListener('message',e=>{"
                "if(e.data&&e.data.proto==='anchor-cockpit-state')window.__stateMsgs++;});</script>"
                f"<iframe id='f' src='http://127.0.0.1:{port}/steward/v1?pid=proj1&dir=Mixture%20of%20Experts' "
                "style='width:1400px;height:840px;border:0'></iframe></body></html>"
            )
            page.goto(f"http://127.0.0.1:{port}/api/version")
            page.set_content(outer_html)
            frame = page.frame_locator("#f")
            frame.locator("[data-flist] .frow").first.wait_for(state="attached", timeout=10000)
            frame.locator("[data-delivmount] [data-deliv-master]").wait_for(timeout=10000)
            frame.locator("[data-wave-map] details").first.wait_for(timeout=10000)
            frame.locator(".scroll .blk").first.wait_for(timeout=10000)

            cf = page.frame(url=lambda u: "/steward/v1" in u)
            assert cf is not None

            # Scroll up in .scroll and record baseline DOM node references + postMessage count.
            baseline_msgs = cf.evaluate(
                """() => {
                    const sc = document.querySelector('.scroll');
                    sc.dispatchEvent(new WheelEvent('wheel', { deltaY: -120 }));
                    sc.scrollTop = 90;
                    sc.dispatchEvent(new Event('scroll'));
                    window.__refs = {
                        frow: document.querySelector('[data-flist] .frow'),
                        spendMain: document.querySelector('[data-spend] .spend-pill-main'),
                        waveDet: document.querySelector('[data-wave-map] details'),
                        delivMaster: document.querySelector('[data-delivmount] [data-deliv-master]'),
                    };
                    return window.parent.__stateMsgs;
                }"""
            )

            # Let two 1-second ticks + renderDeliverablesTile + multi-line typing (Shift+Enter) run.
            cf.locator("[data-say]").click()
            cf.locator("[data-say]").type("First line")
            cf.locator("[data-say]").press("Shift+Enter")
            cf.locator("[data-say]").type("Second line")
            cf.locator("[data-say]").press("Shift+Enter")
            cf.locator("[data-say]").type("Third line")
            page.wait_for_timeout(2400)
            cf.evaluate("() => Proto.renderDeliverablesTile()")
            page.wait_for_timeout(200)

            res = cf.evaluate(
                """() => ({
                    sameFrow: window.__refs.frow === document.querySelector('[data-flist] .frow'),
                    sameSpend: window.__refs.spendMain === document.querySelector('[data-spend] .spend-pill-main'),
                    sameWave: window.__refs.waveDet === document.querySelector('[data-wave-map] details'),
                    sameDeliv: window.__refs.delivMaster === document.querySelector('[data-delivmount] [data-deliv-master]'),
                    scrollTop: document.querySelector('.scroll').scrollTop,
                    stateMsgs: window.parent.__stateMsgs,
                })"""
            )
            assert res["sameFrow"] is True
            assert res["sameSpend"] is True
            assert res["sameWave"] is True
            assert res["sameDeliv"] is True
            assert 70 <= res["scrollTop"] <= 110, f"Expected upward scroll preserved near 90, got {res['scrollTop']}"
            # Unchanged state across 2.6s must not emit postMessage on every 1s tick.
            assert res["stateMsgs"] - baseline_msgs == 0
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_cave_dialogue_typing_and_resize_preserve_upward_scroll():
    pw = pytest.importorskip("playwright.sync_api")
    repo_root = Path(__file__).resolve().parent.parent
    sd_js = (repo_root / "static" / "steward-dialogue.js").read_bytes()

    items_html = "".join(
        f"<li class='exrow st'><div class='exw'><b>Aladdin</b></div><div class='ext'>Turn {i}: "
        + ("Cave status line " * 10)
        + "</div></li>"
        for i in range(25)
    )
    cave_html = f"""<!doctype html><html><head><meta charset="utf-8">
    <style>
      body {{ margin: 0; font-family: sans-serif; }}
      .panel {{ position: sticky; top: 12px; display: flex; flex-direction: column; height: 500px; width: 460px; }}
      #exScroll {{ flex: 1; overflow-y: auto; border: 1px solid #334; }}
      #exList {{ list-style: none; margin: 0; padding: 8px; }}
      .exrow {{ padding: 8px 0; }}
      #say {{ min-height: 48px; width: 100%; box-sizing: border-box; }}
    </style></head><body>
    <div class="panel">
      <div id="exState">listening</div>
      <div id="exScroll"><ul id="exList">{items_html}</ul></div>
      <div class="composer"><textarea id="say"></textarea><button id="send">Send</button></div>
    </div>
    <script src="/static/steward-dialogue.js"></script>
    <script>
      var say = document.getElementById('say');
      var dlg = StewardDialogue.init({{
        pid: 'cave1', dir: 'Cave of Wonders', stamp: 's1',
        list: '#exList', state: '#exState',
        headers: function() {{ return {{'Content-Type': 'application/json'}}; }},
        receipt: function() {{}}
      }});
      function grow() {{
        if (!say) return;
        var ex = document.getElementById('exScroll'), list = document.getElementById('exList');
        var keepTop = ex ? ex.scrollTop : 0;
        var shouldFollow = (!ex || ex._follow !== false) && (!list || list._follow !== false);
        if (window.StewardDialogue) StewardDialogue.fitComposer(say);
        if (ex) {{
          if (shouldFollow) ex.scrollTop = ex.scrollHeight;
          else ex.scrollTop = keepTop;
        }}
      }}
      grow();
      window.addEventListener('resize', grow);
      say.addEventListener('input', grow);
    </script></body></html>""".encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            p = urlparse(self.path).path
            if p == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cave_html)))
                self.end_headers()
                self.wfile.write(cave_html)
                return
            if p == "/static/steward-dialogue.js":
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(sd_js)))
                self.end_headers()
                self.wfile.write(sd_js)
                return
            if p == "/api/steward/events":
                body = json.dumps({"events": [], "state": {"alive": True, "busy": False, "epoch": 1}, "stamp": "s1"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = b'{"ok":true,"corrections":[]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv, port = _start_server(Handler)
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 700})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # Simulate user wheeling upward to read an earlier Steward message.
            before = page.evaluate(
                """() => {
                    const ex = document.getElementById('exScroll');
                    ex.dispatchEvent(new WheelEvent('wheel', { deltaY: -120 }));
                    ex.scrollTop = 110;
                    ex.dispatchEvent(new Event('scroll'));
                    return { top: ex.scrollTop, max: ex.scrollHeight - ex.clientHeight, follow: ex._follow };
                }"""
            )
            assert before["max"] > 300
            assert before["follow"] is False

            # Type multiple lines into #say and resize viewport; upward scroll must NOT be yanked.
            page.locator("#say").click()
            page.locator("#say").type("Checking earlier message\nSecond line\nThird line")
            page.set_viewport_size({"width": 960, "height": 680})
            page.wait_for_timeout(150)

            after = page.evaluate(
                """() => {
                    const ex = document.getElementById('exScroll');
                    return { top: ex.scrollTop, follow: ex._follow };
                }"""
            )
            assert after["follow"] is False
            assert after["top"] == 110
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
