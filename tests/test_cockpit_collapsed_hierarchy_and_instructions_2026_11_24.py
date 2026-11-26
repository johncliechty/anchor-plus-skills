"""Regression tests for AI Cockpit Collapsed Plan/Deliverables, Instruction-Grouped Most Recent,
Hierarchical Final Deliverables, Steward Active Curation CLI, and 10-Min Status Visibility (2026-11-24).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steward_cockpit import deliverable_shelves as ds  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
from steward_cockpit import steward_engine as se  # noqa: E402
from tools import steward_plan  # noqa: E402


def _seed_cockpit_with_instructions_and_hierarchy(cdir: Path) -> Path:
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "Final Deliverables" / "Lecture 1 - Foundations").mkdir(parents=True, exist_ok=True)
    (cdir / "Final Deliverables" / "Lecture 2 - Inference").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text("# Course AI Cockpit\n\n## North Star\nBuild verified lectures.\n", encoding="utf-8")

    steps = [
        {"id": "w1", "name": "Wave 1: Lecture 1", "goal": "Foundations deck", "status": "done", "done": True},
        {"id": "w2", "name": "Wave 2: Lecture 2", "goal": "Inference deck & notes", "status": "active", "done": False},
        {"id": "w3", "name": "Wave 3: Homework 1", "goal": "Problem set + solutions", "status": "proposed", "done": False},
    ]
    (cdir / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": steps, "steps": steps, "roadmap_events": []}, indent=2),
        encoding="utf-8",
    )

    f1 = "Final Deliverables/Lecture 1 - Foundations/Lecture_1_Deck.pdf"
    f2_pdf = "Final Deliverables/Lecture 2 - Inference/Lecture_2_Deck.pdf"
    f2_pptx = "Final Deliverables/Lecture 2 - Inference/Lecture_2_Deck.pptx"
    supp = "Supporting_Audit_Log.md"
    for rel in (f1, f2_pdf, f2_pptx, supp):
        (cdir / rel).write_bytes(b"%PDF-1.4 sample")

    (cdir / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        f"| FINAL: Lecture 2 Inference Slides | `{f2_pptx}` | 2026-11-24 | 2 |\n"
        f"| FINAL: Lecture 2 Inference Reading Copy | `{f2_pdf}` | 2026-11-24 | 2 |\n"
        f"| Supporting - Audit Notes | `{supp}` | 2026-11-24 | 2 |\n"
        f"| FINAL: Lecture 1 Foundations Deck | `{f1}` | 2026-11-23 | 1 |\n",
        encoding="utf-8",
    )

    turns = [
        {"role": "john", "turn_id": "u-1", "at": "2026-11-23T10:00:00Z", "text": "Draft Lecture 1 Foundations slide deck."},
        {"role": "steward", "turn_id": "s-1", "at": "2026-11-23T10:05:00Z", "text": "Lecture 1 is ready."},
        {
            "role": "steward",
            "turn_id": "receipt:r1",
            "at": "2026-11-23T10:05:01Z",
            "text": "**Anchor** · ready to read: [FINAL: Lecture 1 Foundations Deck](/api/steward/deliverable-file?pid=p1&dir=&path=Final%20Deliverables/Lecture%201%20-%20Foundations/Lecture_1_Deck.pdf)",
        },
        {"role": "john", "turn_id": "u-2", "at": "2026-11-24T11:00:00Z", "text": "Now build Lecture 2 Inference in both PDF and PPTX."},
        {"role": "steward", "turn_id": "s-2", "at": "2026-11-24T11:06:00Z", "text": "Lecture 2 PDF and PPTX are finalized."},
        {
            "role": "steward",
            "turn_id": "receipt:r2a",
            "at": "2026-11-24T11:06:01Z",
            "text": "**Anchor** · ready to read: [FINAL: Lecture 2 Inference Reading Copy](/api/steward/deliverable-file?pid=p1&dir=&path=Final%20Deliverables/Lecture%202%20-%20Inference/Lecture_2_Deck.pdf)",
        },
        {
            "role": "steward",
            "turn_id": "receipt:r2b",
            "at": "2026-11-24T11:06:02Z",
            "text": "**Anchor** · ready to read: [FINAL: Lecture 2 Inference Slides](/api/steward/deliverable-file?pid=p1&dir=&path=Final%20Deliverables/Lecture%202%20-%20Inference/Lecture_2_Deck.pptx)",
        },
        {
            "role": "steward",
            "turn_id": "receipt:r2supp",
            "at": "2026-11-24T11:06:03Z",
            "text": "**Anchor** · ready to read: [Supporting - Audit Notes](/api/steward/deliverable-file?pid=p1&dir=&path=Supporting_Audit_Log.md)",
        },
    ]
    (cdir / ".ecgberht" / "conversation-log.json").write_text(json.dumps({"turns": turns}, indent=2), encoding="utf-8")
    return cdir


def test_instruction_mined_batches_and_steward_curate_deliverables_cli(tmp_path: Path):
    cdir = _seed_cockpit_with_instructions_and_hierarchy(tmp_path / "course_effort")
    d0 = sc.read_deliverables(str(cdir))
    batches = d0["shelves"]["most_recent_batches"]

    # 1. Mined directly from conversation-log.json user instructions + landed receipts (supporting noise excluded)
    assert len(batches) == 2
    assert batches[0]["rank_label"] == "Last Instruction"
    assert batches[0]["instruction_excerpt"] == "Now build Lecture 2 Inference in both PDF and PPTX."
    assert len(batches[0]["items"]) == 1  # PDF + PPTX bundled into 1 sibling row!
    assert {p["label"] for p in batches[0]["items"][0]["format_pills"]} == {"PDF", "PPTX"}

    assert batches[1]["rank_label"] == "Instruction Before Last"
    assert batches[1]["instruction_excerpt"] == "Draft Lecture 1 Foundations slide deck."

    # 2. Hierarchical Final Deliverables exist before & after Steward explicit curation
    hier0 = d0["deliverable_hierarchy"]
    assert len(hier0["categories"]) >= 1

    # 3. Steward CLI `curate-deliverables` updates hierarchical summary & custom workstream groups
    rc = steward_plan.main([
        "--cdir", str(cdir),
        "curate-deliverables",
        "--headline", "2 Finalized Lecture Modules (Foundations & Statistical Inference)",
        "--summary", "Organized sequentially by course module with paired slide decks and reading copies.",
        "--groups-json", json.dumps([
            {
                "id": "mod-core",
                "title": "Core Lecture Sequence",
                "summary": "Lectures 1–2 finalized",
                "paths": [
                    "Final Deliverables/Lecture 1 - Foundations/Lecture_1_Deck.pdf",
                    "Final Deliverables/Lecture 2 - Inference/Lecture_2_Deck.pdf",
                ],
            }
        ]),
    ])
    assert rc == 0

    d1 = sc.read_deliverables(str(cdir))
    exec_sum = d1["deliverable_hierarchy"]["executive_summary"]
    assert exec_sum["steward_authored"] is True
    assert exec_sum["headline"] == "2 Finalized Lecture Modules (Foundations & Statistical Inference)"
    assert d1["deliverable_hierarchy"]["categories"][0]["title"] == "Core Lecture Sequence"

    # 4. Steward prompt capsule reflects both Most Recent by Instruction & Final Hierarchy
    capsule = se._plan_state_capsule(str(cdir))
    assert "Most Recent by Instruction:" in capsule
    assert "Last Instruction:" in capsule
    assert "Final Hierarchy (Steward-curated):" in capsule


def test_playwright_cockpit_closed_defaults_single_tile_collapse_and_10m_status(tmp_path: Path):
    pw = pytest.importorskip("playwright.sync_api")
    cdir = _seed_cockpit_with_instructions_and_hierarchy(tmp_path / "ui_effort")
    deliv_payload = sc.read_deliverables(str(cdir))
    from steward_cockpit import steward_routes as sr
    from steward_cockpit import wave_map_model as wmm
    wm_payload = wmm.build_wave_map_payload(cdir)
    map_payload, map_code = sr.api_get(str(cdir), "map", {"pid": "p1", "dir": ""})
    assert map_code == 200
    assert map_payload["folder_path"] == str(cdir.resolve())
    assert "Lecture 2" in map_payload["recent_done_sentence"]
    plan_payload = steward_plan.read_plan_state(cdir)

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    v1_html = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")

    status_payload = {
        "ok": True,
        "effort": "Course AI Cockpit",
        "doing": "Awaiting review on Lecture 2",
        "tests": "pass · layout verified",
        "lead_line": "Next: Start Wave 3 Homework 1",
        "eta": "15m",
        "status_card": {"timestamp": "06:35", "run_type": "Steward status", "project": "Course AI Cockpit"},
        "history_updates": [{"at": "06:25", "summary": "Completed Lecture 2 PDF + PPTX", "doing": "Packaging slides"}],
    }

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def do_GET(self):
            clean = self.path.split("?", 1)[0]
            if clean in ("/", "/steward/v1"):
                b = v1_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b)
                return
            api_map = {
                "/api/wave-state": wm_payload,
                "/api/map": map_payload,
                "/api/plan": plan_payload,
                "/api/deliverables": deliv_payload,
                "/api/status": status_payload,
                "/api/state": {"ok": True, "alive": True, "busy": False, "stamp": "st1"},
                "/api/history": {"turns": []},
            }
            if clean in api_map:
                b = json.dumps(api_map[clean]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b)
                return
            if clean == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                return
            rel = clean.lstrip("/")
            fp = (ROOT / "steward_cockpit" / rel) if rel.startswith("static/") else (ROOT / rel)
            if fp.is_file():
                data = fp.read_bytes()
                ct = "text/css" if fp.suffix == ".css" else ("application/javascript" if fp.suffix == ".js" else "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1480, "height": 940})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/steward/v1?pid=p1&dir=", wait_until="domcontentloaded")
            page.wait_for_selector("[data-deliv-master]", timeout=8000)
            page.wait_for_selector(".blk.status.latest", timeout=8000)

            # 0. Top presentation: Approve banner & Deliverables History Map are removed;
            #    Goal + Folder Location Pill + 1-sentence Recently Done summary sit cleanly along the top!
            assert page.locator("[data-top-approval-bar]").count() == 0
            assert page.locator("[data-poincare-toggle2]").count() == 0
            assert page.locator("[data-poincare-toggle]").is_visible()
            page.wait_for_selector("[data-cockpit-folder-pill]:not([hidden])", timeout=5000)
            assert page.locator("[data-cockpit-folder-path]").inner_text().strip() == str(cdir.resolve())
            recent_line_txt = page.locator("[data-recent-done-line]").inner_text().strip()
            assert "Lecture 2" in recent_line_txt
            gline_box = page.locator(".goalbar .gline").bounding_box()
            grecent_box = page.locator(".goalbar .grecent-line").bounding_box()
            assert gline_box is not None and grecent_box is not None
            assert grecent_box["y"] >= gline_box["y"] + gline_box["height"] - 2
            # Clicking folder pill copies path without toggling .goalbar open
            assert page.eval_on_selector("[data-goalbar]", "el => el.classList.contains('open')") is False
            page.click("[data-cockpit-folder-pill]")
            assert page.eval_on_selector("[data-goalbar]", "el => el.classList.contains('open')") is False

            # 1. Left Plan: Most Recently Done starts OPEN; Current Wave & Next Steps start CLOSED
            assert page.eval_on_selector('details[data-wave-zone="recent-history"]', "el => el.open") is True
            for zk in ("current-wave", "coming-next"):
                assert page.eval_on_selector(f'details[data-wave-zone="{zk}"]', "el => el.open") is False

            # Clicking Current Wave expands it cleanly
            page.click('details[data-wave-zone="current-wave"] > summary')
            assert page.eval_on_selector('details[data-wave-zone="current-wave"]', "el => el.open") is True
            assert page.locator("[data-wave-iterate]").is_visible()

            # 2. Right Deliverables: all 3 main sections start CLOSED, AND 10-Min Status Summary is visible right below!
            for sk in ("recent", "final", "earlier"):
                assert page.eval_on_selector(f'details.dtile[data-shelf="{sk}"]', "el => el.open") is False

            status_box = page.locator(".blk.status.latest").bounding_box()
            assert status_box is not None and status_box["y"] < 500, f"10-Min Status should be visible high in right panel, got {status_box}"
            assert page.locator(".pstatushead").is_visible()

            # 3. Clicking Most Recent opens Last Instruction & Instruction Before Last
            page.click('details.dtile[data-shelf="recent"] > summary')
            recent_txt = page.locator('details.dtile[data-shelf="recent"]').inner_text()
            assert "Most Recent · Last Instruction" in recent_txt
            assert "Most Recent · Instruction Before Last" in recent_txt
            assert "Now build Lecture 2 Inference" in recent_txt

            # 4. Clicking Final Deliverables opens hierarchical Steward Summary + Category -> Unit Folder tree
            page.click('details.dtile[data-shelf="final"] > summary')
            assert page.locator(".deliv-hier-summary-box").is_visible()
            assert page.locator("details.deliv-unit-folder").count() >= 2
            assert page.eval_on_selector("details.deliv-unit-folder", "el => el.open") is False
            page.click("details.deliv-unit-folder > summary")
            assert page.eval_on_selector("details.deliv-unit-folder", "el => el.open") is True

            # 5. Clicking outer `📦 Deliverables` master header collapses ALL deliverables down to a single tile!
            page.click("[data-deliv-master] > summary")
            assert page.eval_on_selector("[data-deliv-master]", "el => el.open") is False
            assert not page.locator('details.dtile[data-shelf="recent"]').is_visible()
            assert page.locator(".blk.status.latest").is_visible()
            assert errors == []
            browser.close()
    finally:
        srv.shutdown()
