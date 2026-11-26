"""Regression & browser verification for uniform Cave of Wonders AI Cockpit tiles (2026-11-26).

Verifies both halves of the 'Publishing My Writing' tile discrepancy:
1. `home_rows.project_facts` recognizes Steward cockpits initialized via `ECGBERHT.md` /
   `.ecgberht/overview.json` (even before `strip.json` or `roadmap.json` exist) as `has_record=True`
   and surfaces `.ecgberht/overview.json`'s `todo_summary` / `headline` as `next`.
2. Even genuinely record-less projects (`has_record=False`, `.tile.quiet`) render with the exact
   same compact 40px height, solid 1px outline, `.t-go` `/steward/v1` link, hover `.t-peek`
   preview, and click-to-expand inline `.t-body` dialogue in both Dark and Skill Foundry Light modes.
"""
from __future__ import annotations

import json
import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import high_seat_page as hsp
import home_rows as hr

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 26)


def test_project_facts_recognizes_ecgberht_face_and_overview_json(tmp_path: Path) -> None:
    pub = tmp_path / "Publishing"
    (pub / ".ecgberht").mkdir(parents=True)
    (pub / "ECGBERHT.md").write_text("# Ecgberht — Publishing My Writing\n\n## North star\n\n> Publish work.\n", encoding="utf-8")
    (pub / "DELIVERABLES.md").write_text("# Deliverables\n", encoding="utf-8")
    (pub / ".ecgberht" / "overview.json").write_text(
        json.dumps(
            {
                "goal": "Publish novels and essays.",
                "headline": "2027 Storymakers Conference Seated",
                "todo_summary": "Nov 30 Author Ala Carte window -> Jan 13 Zoom Class",
            }
        ),
        encoding="utf-8",
    )

    facts = hr.project_facts({"id": "b9984fbfc8ca42b890ecfb8f83a9e268", "name": "Publishing My Writing", "folder_path": str(pub)}, TODAY)
    assert facts["has_record"] is True
    assert facts["next"] == "Nov 30 Author Ala Carte window -> Jan 13 Zoom Class"

    card_html = hsp._card(
        {"id": "b9984fbfc8ca42b890ecfb8f83a9e268", "name": "Publishing My Writing", "blurb": "Publishing strategy"},
        facts,
        "",
        goal={"id": "g-write", "name": "Writing"},
        step={"id": "cand-publishing-my-writing", "name": "Publishing My Writing", "seat": "deck", "kind": "project"},
    )
    assert 'class="tile"' in card_html
    assert 'class="tile quiet"' not in card_html
    assert 'href="/steward/v1?pid=b9984fbfc8ca42b890ecfb8f83a9e268&amp;dir="' in card_html


def test_quiet_card_has_compact_cockpit_structure_without_data_part() -> None:
    q = hsp._card(
        {"id": "q1", "name": "Quiet one", "blurb": "nothing yet"},
        {"has_record": False, "effort": ""},
        "",
        goal={"id": "g1", "name": "Writing"},
        step={"id": "s-q1", "name": "Quiet one", "seat": "deck", "kind": "project"},
    )
    assert 'class="tile quiet"' in q
    assert "no steward record yet" in q
    assert "Open cockpit" in q
    assert "data-part=" not in q
    assert '<span class="t-nm">Quiet one</span>' in q
    assert 'class="t-go" href="/steward/v1?pid=q1&amp;dir="' in q
    assert '<div class="t-face">' in q
    assert '<div class="t-body" hidden></div>' in q


def test_playwright_uniform_compact_outlined_tiles_dark_and_light() -> None:
    pw_mod = pytest.importorskip("playwright.sync_api")

    step_rec = {"id": "s-rec", "name": "Family Trusts - counsel follow-up", "seat": "deck", "kind": "project"}
    step_pub = {"id": "cand-publishing-my-writing", "name": "Publishing My Writing", "seat": "deck", "kind": "project"}
    step_quiet = {"id": "s-quiet", "name": "Unstarted Project Tile", "seat": "deck", "kind": "project"}
    goal = {"id": "g-main", "name": "Core Goals"}

    cards_html = "".join(
        [
            hsp._card(
                {"id": "p-rec", "name": "Family Trusts - counsel follow-up", "blurb": "Trusts"},
                {"has_record": True, "effort": "", "next": "Review Form 6460"},
                "",
                goal=goal,
                step=step_rec,
            ),
            hsp._card(
                {"id": "b9984fbfc8ca42b890ecfb8f83a9e268", "name": "Publishing My Writing", "blurb": "Storymakers 2027"},
                {"has_record": True, "effort": "", "next": "Nov 30 Author Ala Carte window"},
                "",
                goal=goal,
                step=step_pub,
            ),
            hsp._card(
                {"id": "p-quiet", "name": "Unstarted Project Tile", "blurb": "No steward record on disk yet"},
                {"has_record": False, "effort": ""},
                "",
                goal=goal,
                step=step_quiet,
            ),
        ]
    )

    page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Cave of Wonders</title>
  <link rel="stylesheet" href="/static/high-seat-page.css">
  <link rel="stylesheet" href="/static/cave-foundry-light.css">
</head>
<body>
  <div class="app"><main class="main"><div class="canvas"><div class="board">
    <section class="shelf zone" id="shDeck" data-seat="deck">
      <div class="grid">{cards_html}</div>
    </section>
  </div></div></main></div>
  <script>window.ANCHOR_BOOT = {{logged_in: true, auth_required: false, campaign_pid: "camp", build_id: "test"}};</script>
  <script src="/static/steward-dialogue.js"></script>
  <script src="/static/high-seat-page.js"></script>
</body>
</html>"""

    tile_frame_html = """<!doctype html><html><body><textarea id="draft"></textarea></body></html>"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            sp = urlsplit(self.path)
            p = sp.path
            if p in ("/", "/high-seat"):
                self._send(200, page_html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if p.startswith("/static/"):
                fp = ROOT / p.lstrip("/")
                if fp.is_file():
                    ctype = "text/css; charset=utf-8" if fp.suffix == ".css" else "application/javascript; charset=utf-8"
                    self._send(200, fp.read_bytes(), ctype)
                    return
            if p == "/steward/v1":
                self._send(200, tile_frame_html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if p == "/api/steward/map":
                self._send(200, json.dumps({"steps": [step_rec, step_pub, step_quiet]}).encode("utf-8"), "application/json")
                return
            if p == "/api/high-seat/card":
                qs = parse_qs(sp.query)
                part = (qs.get("part") or ["brief"])[0]
                self._send(200, json.dumps({"ok": True, "part": part, "html": '<div class="cbrief"><div class="cp-quiet">Ready</div></div>'}).encode("utf-8"), "application/json")
                return
            if p.startswith("/api/steward/"):
                self._send(200, json.dumps({"ok": True, "light": "quiet", "busy": False, "stamp": "s1"}).encode("utf-8"), "application/json")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        with pw_mod.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="networkidle")
            page.wait_for_function("() => document.querySelectorAll('.tile[data-tile]').length === 3 && [...document.querySelectorAll('.tile[data-tile]')].every(c => c._compact === true)")

            for theme in ("dark", "light"):
                if theme == "light":
                    page.evaluate("document.documentElement.setAttribute('data-cave-theme', 'light')")
                else:
                    page.evaluate("document.documentElement.removeAttribute('data-cave-theme')")

                metrics = page.evaluate(
                    """() => ['#card-p-rec', '#card-b9984fbfc8ca42b890ecfb8f83a9e268', '#card-p-quiet'].map(sel => {
                        const el = document.querySelector(sel);
                        const cs = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return {
                            sel,
                            h: Math.round(r.height),
                            bw: cs.borderTopWidth,
                            bs: cs.borderTopStyle,
                            bc: cs.borderTopColor,
                            bg: cs.backgroundColor,
                            goHref: el.querySelector('a.t-go')?.getAttribute('href') || ''
                        };
                    })"""
                )
                base = metrics[0]
                assert base["h"] == 40
                assert base["bw"] == "1px" and base["bs"] == "solid"
                for m in metrics[1:]:
                    assert m["h"] == base["h"], f"{theme}: height mismatch {m} vs {base}"
                    assert m["bw"] == base["bw"] and m["bs"] == base["bs"], f"{theme}: border mismatch {m} vs {base}"
                    assert m["bc"] == base["bc"], f"{theme}: outline color mismatch {m} vs {base}"
                    assert m["bg"] == base["bg"], f"{theme}: background mismatch {m} vs {base}"
                assert metrics[1]["goHref"].startswith("/steward/v1?pid=b9984fbfc8ca42b890ecfb8f83a9e268")
                assert metrics[2]["goHref"].startswith("/steward/v1?pid=p-quiet")

            # Hover preview + Escape dismiss + click-to-expand inline Steward dialogue on both Publishing and Quiet tiles
            for cid in ("#card-b9984fbfc8ca42b890ecfb8f83a9e268", "#card-p-quiet"):
                page.mouse.move(0, 0)
                card = page.locator(cid)
                card.hover()
                assert card.locator(".t-peek").is_visible()
                page.keyboard.press("Escape")
                assert not card.locator(".t-peek").is_visible()
                card.locator(".t-nm").click()
                assert card.get_attribute("aria-expanded") == "true"
                card.locator(".t-nm").click()
                assert card.get_attribute("aria-expanded") == "false"
                page.mouse.move(0, 0)

            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
