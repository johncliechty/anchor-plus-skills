"""Regression tests for the 2026-11-26 MacBook Air slowdown fix (Opus-validated Option 1):
1. E1: GET /api/steward/map is 100% read-pure (never writes .ecgberht/deliverable-batches.json or mutates map_stamp),
   compute_shelves_for_campaign merges unsynced refinement presentations purely in-memory, and sync_refinement_batches
   is an idempotent fixed point even when >100 refinement + register + curated batches coexist (using source timestamps).
2. E2: cockpit-feedback.js requests /api/steward/map?...&plan_history=0, steward_routes honors plan_history=0 (omitting
   plan_history while keeping steps, refinement, and stamp identical), and caches plan_history=0 separately from 1.
3. E4-lite: warmActive() skips hidden iframe preloading while #caveCockpitsTile is collapsed by default, then triggers
   warm preloading when #caveCockpitsToggle expands the AI Cockpits shelf.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import distro  # noqa: E402
import high_seat_page  # noqa: E402
from steward_cockpit import deliverable_shelves as ds  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
from steward_cockpit import steward_routes as sr  # noqa: E402


def _make_110_presentation_refinement_state(cdir: Path) -> dict:
    """Build a realistic refinement_state with 110 historical presentations (> MAX_STORED_BATCHES = 80)."""
    presentations = []
    revisions = {}
    deliv_lines = ["| What | Where | Date | Step |", "|---|---|---|---|"]
    for idx in range(1, 111):
        rel = f"deliverables/deck_r{idx:03d}.pdf"
        fp = cdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(b"%PDF-1.4 mock")
        rev_id = f"rev-{idx:03d}"
        prod_id = f"prod-{idx:03d}"
        # Strictly monotonic historical timestamps across Sept/Oct 2026 (4 hours apart)
        ep = 1788264000 + idx * 14400
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ep))
        day_str = ts[:10]
        revisions[rev_id] = {"revision_id": rev_id, "product_id": prod_id, "path": rel, "at": ts}
        presentations.append({
            "id": f"pres-{idx:03d}",
            "round": idx,
            "purpose": f"Publish revision {idx} for MBA lecture",
            "at": ts,
            "members": [{"revision_id": rev_id, "product_id": prod_id, "path": rel}],
        })
        deliv_lines.append(f"| Lecture Revision {idx} | `{rel}` | {day_str} | w1 |")

    (cdir / "DELIVERABLES.md").write_text("\n".join(deliv_lines) + "\n", encoding="utf-8")
    return {
        "last_event_at": "2026-10-28T15:50:00Z",
        "slices": {
            "w1": {
                "phase": "awaiting_review",
                "round": 110,
                "revisions": revisions,
                "presentations": presentations,
                "candidate": {},
                "review_requests": [],
            }
        },
        "producer_handoffs": {},
    }


def test_e1_read_pure_map_in_memory_merge_and_110_mixed_batch_idempotency(tmp_path: Path, monkeypatch):
    cdir = tmp_path / "mba_effort"
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text("# MBA Teaching AI\n\n## North Star\nBuild MBA AI course.\n", encoding="utf-8")
    steps = [{"id": "w1", "name": "Wave 1: Lectures", "goal": "Course decks", "status": "active", "done": False}]
    (cdir / "roadmap.json").write_text(
        json.dumps({
            "roadmap_projection": steps,
            "steps": steps,
            "roadmap_events": [{"kind": "refinement_update", "step_id": "w1", "at": "2026-10-28T15:50:00Z"}],
            "plan_history": [{"id": "snap-1", "date": "2026-10-01", "steps": steps, "blob": "x" * 20000}],
        }),
        encoding="utf-8",
    )
    ref_state = _make_110_presentation_refinement_state(cdir)
    monkeypatch.setattr(
        sc,
        "read_refinement",
        lambda campaign_dir, stale_ok=False: {
            "ok": True,
            "sequence": 110,
            "projection_status": {"consistent": True},
            "state": ref_state,
        },
    )

    batches_fp = cdir / ".ecgberht" / "deliverable-batches.json"
    assert not batches_fp.exists()

    # 1. Pure GET /api/steward/map + read_deliverables MUST NOT create deliverable-batches.json on disk,
    #    yet read_deliverables MUST surface the newest 2 presentations via in-memory merge with historical ago labels!
    stamp_before = sc.map_stamp(str(cdir))
    m1, code1 = sr.api_get(str(cdir), "map", {"pid": "mba", "dir": ""})
    m2, code2 = sr.api_get(str(cdir), "map", {"pid": "mba", "dir": ""})
    assert code1 == 200 and code2 == 200
    assert not batches_fp.exists(), "GET /api/steward/map must be 100% read-pure (zero disk writes)"
    assert m1["stamp"] == stamp_before == m2["stamp"]

    deliv_in_mem = sc.read_deliverables(str(cdir))
    assert not batches_fp.exists(), "read_deliverables must merge unsynced presentations in-memory without disk writes"
    recent = deliv_in_mem["shelves"]["most_recent_batches"]
    assert len(recent) == 2
    assert "110" in recent[0]["instruction_excerpt"]
    assert "109" in recent[1]["instruction_excerpt"]
    now_nov26 = 1795656000.0  # ~2026-11-26
    shelves_fixed_now = ds.compute_shelves(
        deliv_in_mem["items"],
        {"batches": ds.discover_refinement_batches(cdir, ref_state)},
        now_epoch=now_nov26,
    )
    assert shelves_fixed_now["most_recent_batches"][0]["ago"].endswith("d ago")

    # 2. Mixed sources (register + curated + 110 refinement presentations > MAX_STORED_BATCHES=80):
    #    Repeated sync_refinement_batches calls MUST be byte-for-byte idempotent (zero mtime churn on 2nd/3rd calls),
    #    and corrupted wall-clock epoch_s values on historical presentations MUST be repaired to source timestamps.
    ds.record_registered_deliverable(
        cdir,
        what="Syllabus Manual Register",
        where="deliverables/deck_r050.pdf",
        step="w1",
        date="2026-10-15T10:00:00Z",
        instruction="Register syllabus manually",
        batch_id="reg-manual-1",
    )
    ds.update_curation(cdir, {"headline": "Curated MBA Course", "recent_paths": ["deliverables/deck_r108.pdf"], "instruction": "Curate deck 108"})

    corrupted_doc = ds.read_batches_doc(cdir)
    corrupted_doc["batches"].append({
        "batch_id": "ref-pres-w1-pres-105",
        "turn_num": 394,
        "instruction_excerpt": "Publish revision 105 for MBA lecture",
        "ts": "2026-10-23T14:45:00Z",
        "epoch_s": 1795656451.45,
        "paths": ["deliverables/deck_r105.pdf"],
        "ids": ["prod-105"],
        "source": "refinement_update",
    })
    batches_fp.write_text(json.dumps(corrupted_doc, indent=2) + "\n", encoding="utf-8")

    ds.sync_refinement_batches(cdir, refinement_state=ref_state)
    bytes_after_1 = batches_fp.read_text(encoding="utf-8")
    mtime_after_1 = batches_fp.stat().st_mtime_ns
    saved_doc = json.loads(bytes_after_1)
    assert len(saved_doc["batches"]) == ds.MAX_STORED_BATCHES

    pres_105 = next(b for b in saved_doc["batches"] if b["batch_id"] == "ref-pres-w1-pres-105")
    assert pres_105["epoch_s"] < 1793500000.0, f"Expected repaired Oct 2026 epoch_s, got {pres_105['epoch_s']}"

    time.sleep(0.02)
    ds.sync_refinement_batches(cdir, refinement_state=ref_state)
    ds.sync_refinement_batches(cdir, refinement_state=ref_state)
    assert batches_fp.stat().st_mtime_ns == mtime_after_1, "2nd/3rd sync_refinement_batches calls must not rewrite disk"
    assert batches_fp.read_text(encoding="utf-8") == bytes_after_1

    st_after = sc.map_stamp(str(cdir))
    m_after_1, _ = sr.api_get(str(cdir), "map", {"pid": "mba", "dir": ""})
    m_after_2, _ = sr.api_get(str(cdir), "map", {"pid": "mba", "dir": ""})
    assert st_after == m_after_1["stamp"] == m_after_2["stamp"]
    assert batches_fp.stat().st_mtime_ns == mtime_after_1


def test_e2_plan_history_zero_opt_out_and_separate_cache_key(tmp_path: Path, monkeypatch):
    cdir = tmp_path / "hist_effort"
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text("# History Effort\n\n## North Star\nTest plan_history opt-out.\n", encoding="utf-8")
    steps = [{"id": "s1", "name": "Step 1", "status": "active", "done": False}]
    big_hist = [
        {"id": f"h{i}", "date": f"2026-09-{(i % 28) + 1:02d}", "digest": f"dig-{i}", "steps": steps, "summary": "Z" * 4000}
        for i in range(25)
    ]
    (cdir / "roadmap.json").write_text(
        json.dumps({"roadmap_projection": steps, "steps": steps, "roadmap_events": []}),
        encoding="utf-8",
    )
    (cdir / ".ecgberht" / "plan-history.json").write_text(
        json.dumps({"snapshots": big_hist}),
        encoding="utf-8",
    )

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    vars(sr).setdefault("_MAP_ROUTE_CACHE", {}).clear()

    m_slim, c_slim = sr.api_get(str(cdir), "map", {"pid": "p_hist", "dir": "", "plan_history": "0"})
    m_full, c_full = sr.api_get(str(cdir), "map", {"pid": "p_hist", "dir": ""})
    assert c_slim == 200 and c_full == 200
    assert m_slim.get("plan_history") in ([], None)
    assert len(m_full.get("plan_history") or []) >= 25
    assert m_slim["steps"] == m_full["steps"]
    assert m_slim["stamp"] == m_full["stamp"]
    assert len(json.dumps(m_slim)) < len(json.dumps(m_full)) // 4


def test_e4_playwright_feedback_plan_history_zero_and_collapsed_warm_active_gate():
    pw = pytest.importorskip("playwright.sync_api")
    seen_queries: list[tuple[str, dict]] = []

    card_markup = high_seat_page._card(
        {"id": "mba", "name": "MBA Teaching AI"},
        {"has_record": True, "effort": "", "next": "Review Lecture 10"},
        "",
        goal={"name": "MBA AI Course"},
        step={"id": "s-mba", "kind": "effort", "name": "MBA Teaching AI"},
        light={"light": "gray"},
    )
    html = (
        "<!doctype html><html><head><title>Cave of Wonders</title>"
        "<link rel=\"stylesheet\" href=\"/static/high-seat-page.css\">"
        "<script>window.ANCHOR_BOOT={campaign_pid:'camp',steward:'Aladdin',logged_in:true,auth_required:false};</script>"
        "</head><body>"
        "<div class=\"board\">"
        "  <div id=\"caveCockpitsTile\" class=\"cave-cockpits-hub\">"
        "    <button type=\"button\" id=\"caveCockpitsToggle\" data-cockpits-toggle=\"1\" aria-expanded=\"false\">"
        "      <span>AI Cockpits</span><span id=\"caveCockpitsTog\">Expand</span>"
        "    </button>"
        "    <div id=\"caveCockpitsBody\" hidden>"
        "      <section id=\"shActive\" class=\"shelf zone\" data-seat=\"active\">"
        "        <div class=\"shelf-h\"><span class=\"c\">1</span></div>"
        "        <div class=\"grid\">" + card_markup + "</div>"
        "      </section>"
        "    </div>"
        "  </div>"
        "</div>"
        "<textarea id=\"say\" aria-label=\"Cave draft\"></textarea><button id=\"sendBtn\">Send</button>"
        "<script src=\"/static/cockpit-feedback.js\"></script>"
        "<script src=\"/static/high-seat-page.js\"></script>"
        "<script src=\"/static/cave-tidy-controls.js\"></script>"
        "</body></html>"
    )

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def do_GET(self):
            u = urlsplit(self.path)
            q = parse_qs(u.query, keep_blank_values=True)
            seen_queries.append((u.path, q))
            if u.path in ("/", "/high-seat"):
                b = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b)
                return
            if u.path.startswith("/static/"):
                fp = ROOT / u.path.lstrip("/")
                if fp.is_file():
                    ct = "application/javascript" if fp.suffix == ".js" else "text/css"
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.end_headers()
                    self.wfile.write(fp.read_bytes())
                    return
            if u.path == "/steward/v1":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<!doctype html><html><body>Warm Cockpit Frame</body></html>")
                return
            if u.path == "/api/steward/state":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "light": "quiet", "busy": False, "stamp": "fixed-stamp-1"}).encode("utf-8"))
                return
            if u.path == "/api/steward/map":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "ok": True,
                    "stamp": "fixed-stamp-1",
                    "steps": [{"id": "w1", "status": "active", "navigation": {"current": True, "label": "Ready for review"}}],
                }).encode("utf-8"))
                return
            if u.path == "/api/steward/deliverables":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "ok": True,
                    "items": [{"is_current": True, "accepted": False, "managed": False, "owner_step_id": "w1", "what": "FOR REVIEW: Deck"}],
                }).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_timeout(2400)

            # 1. While AI Cockpits hub is collapsed by default, warmActive MUST NOT have spawned any /steward/v1 iframe!
            v1_while_closed = [x for x in seen_queries if x[0] == "/steward/v1"]
            assert v1_while_closed == [], f"Expected 0 warm iframes while shelf is collapsed, got {v1_while_closed}"

            # 2. Direct AnchorCockpitFeedback.read sends plan_history=0, caches until > now, and detects review=True!
            seen_before_direct = len([q for path, q in seen_queries if path == "/api/steward/map" and q.get("pid") == ["mba"]])
            fb_res = page.evaluate("""async () => {
              const r1 = await window.AnchorCockpitFeedback.read({pid: 'mba', dir: ''}, null, {});
              const r2 = await window.AnchorCockpitFeedback.read({pid: 'mba', dir: ''}, r1.record, {});
              return { ready1: r1.ready, reason1: r1.reason, until1: r1.record.until, now: Date.now(), cached2: r2.record === r1.record };
            }""")
            assert fb_res["ready1"] is True
            assert fb_res["reason1"] == "review waiting"
            assert fb_res["until1"] > fb_res["now"] + 60000
            assert fb_res["cached2"] is True, "Second read with matching stamp must hit client cache with zero extra /map calls"

            mba_map_calls = [q for path, q in seen_queries if path == "/api/steward/map" and q.get("pid") == ["mba"]]
            assert len(mba_map_calls) == seen_before_direct + 1
            assert all(q.get("plan_history") == ["0"] for q in mba_map_calls)

            # 3. Expanding #caveCockpitsToggle warms the Active card iframe cleanly
            page.click("#caveCockpitsToggle")
            page.wait_for_timeout(3200)
            v1_after_open = [x for x in seen_queries if x[0] == "/steward/v1"]
            assert len(v1_after_open) >= 1, "Expanding AI Cockpits shelf should warm Active card iframe"
            browser.close()
    finally:
        srv.shutdown()


def test_distro_stdlib_only_and_line_cap_clean():
    touched = [
        "steward_cockpit/deliverable_shelves.py",
        "steward_cockpit/steward_campaign.py",
        "steward_cockpit/steward_routes.py",
        "static/cockpit-feedback.js",
        "static/high-seat-page.js",
        "static/cave-tidy-controls.js",
        "tests/test_mac_air_slowdown_oscillator_fix_2026_11_26.py",
    ]
    for rel in touched:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = list(distro._scan_text(rel, txt))
        assert hits == [], f"Unexpected PII hits in {rel}: {hits}"

    py_staged = [(rel, ROOT / rel) for rel in touched if rel.endswith(".py") and not rel.startswith("tests/")]
    bad_imports = distro.scan_third_party_imports(py_staged, ROOT)
    assert not bad_imports, f"Unexpected third-party imports: {bad_imports}"
    assert len((ROOT / "steward_cockpit/deliverable_shelves.py").read_text(encoding="utf-8").splitlines()) < 320
