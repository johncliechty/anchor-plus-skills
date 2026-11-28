"""Regression tests ensuring the Cave of Wonders base tile in Anchor never turns into an AI Cockpit (2026-11-28).

Covers:
1. `steward-dialogue.js` / `high-seat-page.js` `open_cockpit` acts open a separate tile via `ANCHOR_APP.open` /
   `window.open(..., '_blank')` instead of mutating `window.location.href` on the Cave base frame.
2. `static/app.js` (`onLoad` / `show`) structurally guards `t.kind === 'cave'` so any accidental in-place
   navigation inside `cave.frame` restores `/` on the Cave base tile and opens the target URL in its own tile.
3. `static/app-frame.js` self-heals an already-open `Anchor` window whose `caveFrame` (`#stage iframe.pane[0]`)
   was previously navigated onto `/steward/v1` or `/project/*`.
4. `steward_cockpit/campaign_say.py` does not hijack anaphoric/compound instructions such as
   "Please open this AI Cockpit and place it in the list of Active AI Cockpits." onto a wrong cockpit.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from urllib.parse import urlparse

import pytest

from steward_cockpit import campaign_say

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
BRAND = ROOT / "vendor" / "brand"


def _start_server(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, port


def test_campaign_say_skips_anaphoric_and_compound_open_cockpit(tmp_path):
    camp = tmp_path / "Campaign"
    camp.mkdir()
    rm = {
        "schema": "ecgberht-roadmap-v0",
        "project_id": "campaign",
        "as_of": "2026-11-28",
        "roadmap_events": [],
        "roadmap_projection": [
            {
                "id": "anchor-steward",
                "name": "Anchor Steward Active List",
                "status": "active",
                "group": "anchor-steward",
                "tier": 1,
            },
            {
                "id": "gwl-harnesses",
                "name": "Ghost World Labs harnesses and cognitive structures",
                "status": "active",
                "seat": "deck",
                "ref": "project:6765ece4b3bc43b0b0b0907b92b17280",
                "navigation": {"path": ["anchor-steward"]},
            },
        ],
    }
    (camp / "roadmap.json").write_text(json.dumps(rm), encoding="utf-8")

    # Exact prompt that previously false-matched `anchor-steward` and hijacked Cave onto /project/Campaign:
    anaphoric_compound = campaign_say.fast_steward_command(
        str(camp),
        "Please open this AI Cockpit and place it in the list of Active AI Cockpits.",
        from_cave=True,
    )
    assert anaphoric_compound is None

    # Explicit named cockpit resolves directly to /steward/v1?pid=...&dir=
    explicit = campaign_say.fast_steward_command(
        str(camp),
        "Please open Ghost World Labs harnesses and cognitive structures",
        from_cave=True,
    )
    assert explicit is not None and explicit.get("ok") is True
    assert explicit.get("act") == "open_cockpit"
    assert explicit.get("open_url") == "/steward/v1?pid=6765ece4b3bc43b0b0b0907b92b17280&dir="


def test_cave_base_tile_stays_cave_on_open_cockpit_and_inplace_nav():
    pw = pytest.importorskip("playwright.sync_api")

    cave_html = b"""<!doctype html><html><head><meta charset="utf-8"><title>Cave of Wonders</title></head>
    <body>
      <h1 id="caveHeading">Cave of Wonders Board</h1>
      <script>
        window.ANCHOR_BOOT = { campaign_pid: "camp" };
        window.ANCHOR_TILES = {
          seat_name: "Cave of Wonders",
          seat_icon: "/vendor/brand/aladdin-high-seat-cave.png",
          mode_name: "Star Chart",
          mode_icon: "/vendor/brand/campaign-aladdin-star-chart.jpg"
        };
      </script>
      <div id="exState">listening</div>
      <ul id="exList"></ul>
      <textarea id="say"></textarea>
      <button id="sendBtn" type="button">Send</button>
      <button id="forceInPlace" type="button" onclick="window.location.href='/steward/v1?pid=p2&dir=Paper%202'">Force In-Place</button>
      <script src="/static/steward-dialogue.js"></script>
      <script>
        var dlg = StewardDialogue.init({
          pid: "camp", dir: "Cave of Wonders", stamp: "s1",
          list: "#exList", state: "#exState",
          headers: function() { return { "Content-Type": "application/json" }; },
          receipt: function() {}
        });
        document.getElementById("sendBtn").onclick = function() {
          var box = document.getElementById("say");
          dlg.send(box.value, null, dlg.mainList(), this, box, "");
        };
      </script>
    </body></html>"""

    def cockpit_html(label: str) -> bytes:
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{label} — AI Cockpit</title>"
            "<script src='/static/app-frame.js'></script></head>"
            f"<body><h2 class='ck-head'>{label}</h2></body></html>"
        ).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            if p == "/static/app.html":
                return self._send(200, (STATIC / "app.html").read_bytes(), "text/html; charset=utf-8")
            if p.startswith("/static/"):
                fp = STATIC / p.split("/static/", 1)[1]
                if fp.is_file():
                    ctype = "text/css; charset=utf-8" if fp.suffix == ".css" else "application/javascript; charset=utf-8"
                    return self._send(200, fp.read_bytes(), ctype)
            if p.startswith("/vendor/brand/"):
                fp = BRAND / p.split("/vendor/brand/", 1)[1]
                if fp.is_file():
                    return self._send(200, fp.read_bytes(), "image/png")
                return self._send(200, b"", "image/png")
            if p in ("/", "/high-seat"):
                return self._send(200, cave_html, "text/html; charset=utf-8")
            if p == "/steward/v1":
                return self._send(200, cockpit_html(u.query), "text/html; charset=utf-8")
            if p == "/setup":
                return self._send(
                    200,
                    b"<!doctype html><html><head><title>Setup</title><script src='/static/app-frame.js'></script></head><body>Setup</body></html>",
                    "text/html; charset=utf-8",
                )
            if p == "/api/steward/events":
                return self._send(
                    200,
                    json.dumps({"events": [], "state": {"alive": True, "busy": False, "epoch": 1}, "stamp": "s1"}).encode(),
                    "application/json",
                )
            if p == "/api/steward/state":
                return self._send(200, b'{"ok":true,"light":"quiet","busy":false,"alive":true}', "application/json")
            if p == "/api/steward/deliverables":
                return self._send(200, b'{"ok":true,"items":[]}', "application/json")
            return self._send(200, b'{"ok":true}', "application/json")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 0:
                self.rfile.read(n)
            u = urlparse(self.path)
            if u.path == "/api/steward/say":
                payload = {
                    "ok": True,
                    "campaign_act": True,
                    "read_only": True,
                    "act": "open_cockpit",
                    "say": "Opening AI Cockpit…",
                    "receipt": "Opening AI Cockpit…",
                    "open_url": "/steward/v1?pid=p1&dir=Deck",
                }
                return self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return self._send(200, b'{"ok":true}', "application/json")

    srv, port = _start_server(Handler)
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1360, "height": 840})
            page.goto(f"http://127.0.0.1:{port}/static/app.html", wait_until="domcontentloaded")
            cave_frame = page.frame_locator("#stage iframe.pane").first
            cave_frame.locator("#caveHeading").wait_for(timeout=10000)

            # 1. Trigger open_cockpit from Cave Steward dialogue: opens a 2nd tile, Cave base tile stays Cave!
            cave_frame.locator("#say").fill("open Deck cockpit")
            cave_frame.locator("#sendBtn").click()
            page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2", timeout=10000)

            # Click the first tile (Cave of Wonders): it MUST still be the Cave of Wonders board!
            page.locator("#strip .tile.cave").click()
            cave_frame.locator("#caveHeading").wait_for(timeout=5000)
            first_frame_path = page.evaluate("() => new URL(document.querySelectorAll('#stage iframe.pane')[0].contentWindow.location.href).pathname")
            assert first_frame_path in ("/", "/high-seat")

            # 2. Force an in-place window.location.href inside cave.frame: app.js snaps Cave back to '/' and opens a 3rd tile!
            cave_frame.locator("#forceInPlace").click()
            page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3", timeout=10000)
            page.wait_for_function(
                "() => { try { const p = new URL(document.querySelectorAll('#stage iframe.pane')[0].contentWindow.location.href).pathname; return p === '/' || p === '/high-seat'; } catch(e) { return false; } }",
                timeout=10000,
            )
            page.locator("#strip .tile.cave").click()
            cave_frame.locator("#caveHeading").wait_for(timeout=5000)
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
