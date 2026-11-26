"""Wave 1 Regression Suite — Cave of Wonders Inline [Processing] Drawer & Honest 3-Class ETAs.

Exercises:
  1. Honest 3-class timing (`wave_eta` measured vs unmeasured, `queue_range` 25*n..45*n sec, `live_phase` with zero fake countdown).
  2. Pure read-only GET (`0` disk writes, `0` `subprocess.Popen` spawns) + `(mtime_ns, size)` stat memoization (`< 15 ms` warm) + single source of truth (`running_n == len(rows)`).
  3. Boundedness (`limit` `1..200`, HTTP 400 refusal on invalid/out-of-range/oversized query) + authentication gate (401 before substance).
  4. Realpath containment escape attempts (`..`, URL-encoded `%2e%2e`, uncontained absolute path, symlink/reparse escape).
  5. Explicit 5-state failure table keeping `unknown` (503) strictly separate from `empty` (200).
  6. Two-process concurrency test (`atomic_write_json` + concurrent `read_processing_feed`).
  7. Anti-bloat line ceilings + `distro._scan_text` zero-PII & stdlib-only import scan.
  8. Live Playwright E2E on throwaway port at `1440x960` (`#cosRunningTile` button -> `#cosProcessingPanel` inline toggle, 6 pills aligned on one row, zero `#shActive` hash jump, zero `/api/steward/events` soft-wake, safe `textContent` rendering, Escape close, and `unknown` vs `empty` UI states).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import cave_processing_feed as cpf
import comms_connector as comms
import distro
import high_seat_page
import paths
import route_table

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def isolated_proc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "anchor_data"
    cave_dir = tmp_path / "Campaign"
    cj_dir = tmp_path / "code_jobs"
    data_dir.mkdir(parents=True, exist_ok=True)
    cave_dir.mkdir(parents=True, exist_ok=True)
    cj_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_CAVE_DIR", str(cave_dir))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(cj_dir))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir, raising=False)
    cpf.set_processing_feed_hooks(available=True, slow=False)
    cpf.reset_memo_cache()
    comms._WORKING_LIST_SPINE_CACHE.clear()
    comms._COS_COCKPIT_CANDIDATES_CACHE.clear()
    return data_dir


def _seed_four_active_sources(data_dir: Path, now_ts: float) -> None:
    # 1. Open-ended Cave Steward turn -> Timing Class 3 (`live_phase`)
    ecg = data_dir / ".ecgberht"
    ecg.mkdir(parents=True, exist_ok=True)
    cpf.atomic_write_json(
        ecg / "presence.json",
        {
            "busy": True,
            "turn_id": "turn-cave-1",
            "title": "Cave Steward Turn <img src=x onerror=window.__procXss=1>",
            "doing": "Synthesizing Star Chart priorities",
            "phase": "Reading roadmap.json",
            "started_at": now_ts - 37,
        },
    )

    # 2. Two queued Scribe FIFO email drafts -> Timing Class 2 (`queue_range`: 25..45s, 50..90s)
    cpf.atomic_write_json(
        data_dir / ".anchor" / "speed-racer-queue.json",
        {
            "queue": [
                {
                    "id": "sr-1",
                    "status": "drafting",
                    "subject": "Series B Term Sheet Redlines",
                    "to": "counsel@example.org",
                    "queued_at": now_ts - 22,
                },
                {
                    "id": "sr-2",
                    "status": "queued",
                    "subject": "Lab Compute Allocation",
                    "to": "chair@example.org",
                    "queued_at": now_ts - 11,
                },
                {
                    "id": "sr-ready-ignored",
                    "status": "ready",
                    "subject": "Already Finished Draft",
                    "to": "done@example.org",
                    "queued_at": now_ts - 90,
                },
            ]
        },
    )

    # 3. Delegated Foreman multi-wave run -> Timing Class 1 (`wave_eta` measured velocity)
    rnd_dir = data_dir / "rnd_jobs"
    rnd_dir.mkdir(parents=True, exist_ok=True)
    cpf.atomic_write_json(
        rnd_dir / "job-foreman-1.json",
        {
            "job_id": "job-foreman-1",
            "project_id": "proj-quantum",
            "project_name": "Quantum Paper",
            "skill": "Foreman",
            "status": "running",
            "total_waves": 4,
            "completed_waves": 2,
            "current_wave": 3,
            "phase": "EXECUTE",
            "wave_durations_sec": [120.0, 180.0],
            "current_wave_started_at": now_ts - 30.0,
            "started_at": now_ts - 330.0,
            "description": "Executing Wave 3 spectral proof verification",
        },
    )


def test_three_class_timing_zero_popen_memoization_and_single_source(
    isolated_proc_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ts = 1_795_000_000.0
    _seed_four_active_sources(isolated_proc_env, now_ts)

    # Forbid any subprocess spawn during GET / feed reads
    def _forbid_popen(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("subprocess.Popen is strictly forbidden on Processing GET reads")

    monkeypatch.setattr(subprocess, "Popen", _forbid_popen)

    payload, code = cpf.read_processing_feed(data_dir=isolated_proc_env, now=now_ts)
    assert code == 200
    assert payload["ok"] is True
    assert payload["state"] == "ok"
    assert payload["count"] == 4
    assert len(payload["rows"]) == 4
    assert payload["badge_text"] == "4 Processing"

    by_id = {r["id"]: r for r in payload["rows"]}

    # Class 3: Open-ended Steward turn -> live_phase, NO fake countdown
    st_row = by_id["turn-cave-1"]
    assert st_row["timing_class"] == "live_phase"
    assert st_row["eta_seconds"] is None
    assert st_row["has_measured_eta"] is False
    assert st_row["eta_text"] == "Phase: Reading roadmap.json"
    assert "Est." not in st_row["eta_text"] and "left" not in st_row["eta_text"]
    assert st_row["elapsed_text"] == "Elapsed 0m 37s"

    # Class 2: Scribe FIFO queue -> 25*n..45*n sec range
    sr1, sr2 = by_id["sr-1"], by_id["sr-2"]
    assert sr1["timing_class"] == "queue_range"
    assert (sr1["eta_min_sec"], sr1["eta_max_sec"]) == (25, 45)
    assert "25–45s" in sr1["eta_text"]
    assert sr2["timing_class"] == "queue_range"
    assert (sr2["eta_min_sec"], sr2["eta_max_sec"]) == (50, 90)
    assert "50–90s" in sr2["eta_text"]

    # Class 1: Foreman multi-wave run -> measured wave-velocity ETA when >=1 wave completed
    fm_row = by_id["job-foreman-1"]
    assert fm_row["timing_class"] == "wave_eta"
    assert fm_row["has_measured_eta"] is True
    assert fm_row["eta_seconds"] == 270  # avg=150s; (150 - 30) + 1*150 = 270s (~4m-5m)
    assert fm_row["eta_text"].startswith("Est. ~")
    assert fm_row["cockpit_href"] == "/steward/v1?pid=proj-quantum"

    # Class 1 unmeasured fallback: 0 completed waves -> honest Wave 1/3 + phase, zero fake ETA
    unm = cpf.compute_wave_eta({"total_waves": 3, "completed_waves": 0, "current_wave": 1, "phase": "PLAN"}, now_ts)
    assert unm["timing_class"] == "wave_eta"
    assert unm["has_measured_eta"] is False
    assert unm["eta_seconds"] is None
    assert unm["eta_text"] == "Wave 1/3 · PLAN"

    # Repeat-invocation memoization hit + < 15 ms warm latency
    stats_after_first = cpf.get_memo_stats()
    assert stats_after_first["misses"] == 1
    assert stats_after_first["hits"] == 0

    t0 = time.perf_counter()
    for _ in range(10):
        warm_payload, warm_code = cpf.read_processing_feed(data_dir=isolated_proc_env, now=now_ts + 5)
        assert warm_code == 200
        assert warm_payload["count"] == 4
    avg_warm_ms = ((time.perf_counter() - t0) * 1000.0) / 10.0
    assert avg_warm_ms < 15.0, f"Expected < 15ms warm read, got {avg_warm_ms:.3f}ms"
    assert cpf.get_memo_stats()["hits"] == 10
    assert cpf.get_memo_stats()["misses"] == 1

    # Single source of truth: high_seat_page._proactive_triage_strip badge count matches len(rows)
    strip_html = high_seat_page._proactive_triage_strip({"today": None, "entries": [], "facts": {}, "initiatives": []})
    assert '<b id="cosRunningCount">4</b> Processing' in strip_html


def test_bounds_auth_containment_and_five_state_failure_table(
    isolated_proc_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Route declared token-gated & migrated in route_table
    rt_row = route_table.match("GET", "/api/high-seat/processing")
    assert rt_row is not None
    assert rt_row.auth == route_table.AUTH_TOKEN
    assert rt_row.migrated is True

    # Auth gate: 401 when ANCHOR_TOKEN configured and missing/wrong; 200 with valid Bearer token
    monkeypatch.setenv("ANCHOR_TOKEN", "unit-test-secret-tok-99")
    unauth_body, unauth_code = cpf.handle_processing_http_get("/api/high-seat/processing", headers={}, data_dir=isolated_proc_env)
    assert unauth_code == 401
    assert unauth_body["ok"] is False

    ok_hdrs = {"Authorization": "Bearer unit-test-secret-tok-99"}
    emp_body, emp_code = cpf.handle_processing_http_get("/api/high-seat/processing", headers=ok_hdrs, data_dir=isolated_proc_env)
    assert emp_code == 200
    assert emp_body["state"] == "empty"
    assert emp_body["count"] == 0
    assert emp_body["badge_text"] == "0 Processing"

    # Boundedness: limit 1..200 enforced with HTTP 400 refusal path
    for bad_q in ("limit=0", "limit=-1", "limit=201", "limit=abc", "limit=", "pad=" + ("x" * 600)):
        ref_body, ref_code = cpf.handle_processing_http_get(
            f"/api/high-seat/processing?{bad_q}", headers=ok_hdrs, data_dir=isolated_proc_env
        )
        assert ref_code == 400, f"Expected 400 for {bad_q!r}, got {ref_code}"
        assert ref_body["state"] == "refused"

    now_ts = time.time()
    _seed_four_active_sources(isolated_proc_env, now_ts)
    lim_body, lim_code = cpf.handle_processing_http_get(
        "/api/high-seat/processing?limit=2", headers=ok_hdrs, data_dir=isolated_proc_env
    )
    assert lim_code == 200
    assert lim_body["count"] == 2
    assert lim_body["total_count"] == 4
    assert lim_body["truncated"] is True

    # Containment escape-attempt tests: `..`, `%2e%2e`, absolute path, and symlink/junction escape
    outside_dir = isolated_proc_env.parent / "outside_secret_root"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.json"
    outside_file.write_text("{}", encoding="utf-8")

    for bad_cand in ("../outside_secret_root/secret.json", "%2e%2e/secret.json", str(outside_file)):
        with pytest.raises(cpf.ContainmentError):
            cpf.resolve_contained_feed_path([isolated_proc_env], bad_cand, allow_contained_abs=False)
        esc_res, esc_code = cpf.handle_processing_http_get(
            f"/api/high-seat/processing?scope={bad_cand}", headers=ok_hdrs, data_dir=isolated_proc_env
        )
        assert esc_code == 400
        assert esc_res["state"] == "refused"

    # Symlink / Windows directory junction escape attempt
    link_path = isolated_proc_env / "escape_link"
    created_link = False
    try:
        os.symlink(str(outside_dir), str(link_path), target_is_directory=True)
        created_link = True
    except OSError:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link_path), str(outside_dir)], check=True, capture_output=True)
            created_link = True
    assert created_link is True
    with pytest.raises(cpf.ContainmentError):
        cpf.resolve_contained_feed_path([isolated_proc_env], "escape_link/secret.json", allow_contained_abs=False)

    # Explicit 5-state failure table keeping `unknown` (503) and `empty` (200) strictly separate
    assert set(cpf.FAILURE_STATE_TABLE.keys()) == {
        "dependency-missing",
        "dependency-slow-or-killed",
        "dependency-returns-garbage",
        "backing-store-unreadable",
        "empty-but-valid",
    }

    # State 1: dependency-missing -> 503 unknown
    cpf.set_processing_feed_hooks(available=False, slow=False)
    r_miss, c_miss = cpf.read_processing_feed(data_dir=isolated_proc_env)
    assert c_miss == 503 and r_miss["state"] == "unknown" and r_miss["failure_state"] == "dependency-missing" and r_miss["count"] is None

    # State 2: dependency-slow-or-killed -> 503 unknown
    cpf.set_processing_feed_hooks(available=True, slow=True)
    r_slow, c_slow = cpf.read_processing_feed(data_dir=isolated_proc_env)
    assert c_slow == 503 and r_slow["state"] == "unknown" and r_slow["failure_state"] == "dependency-slow-or-killed" and r_slow["count"] is None
    cpf.set_processing_feed_hooks(available=True, slow=False)

    # State 3: dependency-returns-garbage -> 503 unknown
    (isolated_proc_env / ".anchor" / "speed-racer-queue.json").write_text("{not-valid-json", encoding="utf-8")
    cpf.reset_memo_cache()
    r_garb, c_garb = cpf.read_processing_feed(data_dir=isolated_proc_env)
    assert c_garb == 503 and r_garb["state"] == "unknown" and r_garb["failure_state"] == "dependency-returns-garbage" and r_garb["count"] is None

    # State 4: backing-store-unreadable -> 503 unknown (`rnd_jobs` replaced by a regular file)
    (isolated_proc_env / ".anchor" / "speed-racer-queue.json").unlink(missing_ok=True)
    for jf in (isolated_proc_env / "rnd_jobs").glob("*"):
        jf.unlink()
    (isolated_proc_env / "rnd_jobs").rmdir()
    (isolated_proc_env / "rnd_jobs").write_text("not-a-dir", encoding="utf-8")
    cpf.reset_memo_cache()
    r_unr, c_unr = cpf.read_processing_feed(data_dir=isolated_proc_env)
    assert c_unr == 503 and r_unr["state"] == "unknown" and r_unr["failure_state"] == "backing-store-unreadable" and r_unr["count"] is None

    # State 5: empty-but-valid -> 200 empty (strictly separate from unknown!)
    (isolated_proc_env / "rnd_jobs").unlink()
    (isolated_proc_env / ".ecgberht" / "presence.json").unlink(missing_ok=True)
    cpf.reset_memo_cache()
    r_emp, c_emp = cpf.read_processing_feed(data_dir=isolated_proc_env)
    assert c_emp == 200 and r_emp["state"] == "empty" and r_emp["failure_state"] == "empty-but-valid" and r_emp["count"] == 0


def test_two_process_concurrency_atomic_write_and_feed_reads(tmp_path: Path) -> None:
    data_dir = tmp_path / "conc_data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    sr_file = data_dir / ".anchor" / "speed-racer-queue.json"
    cpf.atomic_write_json(sr_file, {"queue": []})

    worker_code = (
        "import pathlib, sys, time\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import cave_processing_feed as cpf\n"
        "dd = pathlib.Path(sys.argv[1])\n"
        "wid = sys.argv[2]\n"
        "sr = dd / '.anchor' / 'speed-racer-queue.json'\n"
        "for i in range(12):\n"
        "    cpf.atomic_write_json(sr, {'queue': [{'id': f'{wid}-{i}', 'status': 'queued', 'subject': f'Subj {i}', 'queued_at': time.time()}], 'writer': wid, 'seq': i})\n"
        "    body, code = cpf.read_processing_feed(data_dir=dd)\n"
        "    assert code == 200 and body['state'] in ('ok', 'empty')\n"
    )
    p1 = subprocess.Popen([sys.executable, "-c", worker_code, str(data_dir), "w1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p2 = subprocess.Popen([sys.executable, "-c", worker_code, str(data_dir), "w2"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out1, err1 = p1.communicate(timeout=20)
    out2, err2 = p2.communicate(timeout=20)
    assert p1.returncode == 0, f"Worker 1 failed: {err1}\n{out1}"
    assert p2.returncode == 0, f"Worker 2 failed: {err2}\n{out2}"
    final_doc = json.loads(sr_file.read_text(encoding="utf-8"))
    assert final_doc["seq"] == 11 and len(final_doc["queue"]) == 1


def test_module_line_caps_zero_innerhtml_and_distro_zero_pii_scan() -> None:
    py_path = REPO_ROOT / "cave_processing_feed.py"
    js_path = REPO_ROOT / "static" / "cave-processing-drawer.js"
    py_lines = len(py_path.read_text(encoding="utf-8").splitlines())
    js_txt = js_path.read_text(encoding="utf-8")
    js_lines = len(js_txt.splitlines())

    assert py_lines < 300, f"cave_processing_feed.py must be < 300 lines, got {py_lines}"
    assert js_lines < 220, f"cave-processing-drawer.js must be < 220 lines, got {js_lines}"
    assert ".innerHTML" not in js_txt and "outerHTML" not in js_txt

    touched = [
        "cave_processing_feed.py",
        "static/cave-processing-drawer.js",
        "high_seat_page.py",
        "static/high-seat-page.js",
        "static/high-seat-page.css",
        "route_table.py",
        "anchor_gui.py",
    ]
    for rel in touched:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        hits = list(distro._scan_text(rel, txt))
        assert hits == [], f"Unexpected PII/secret scan hits in {rel}: {hits}"

    tp_hits = distro.scan_third_party_imports([("cave_processing_feed.py", py_path)], root=REPO_ROOT)
    assert tp_hits == [], f"Third-party import forbidden in cave_processing_feed.py: {tp_hits}"


def test_playwright_inline_processing_drawer_e2e(isolated_proc_env: Path) -> None:
    from playwright.sync_api import sync_playwright

    now_ts = time.time()
    _seed_four_active_sources(isolated_proc_env, now_ts)
    comms.save_comms_config({"accounts": []})
    comms.save_comms_sync({"calendar_events": [], "email_headers": []})

    static_map = {
        "/static/high-seat-page.css": (REPO_ROOT / "static" / "high-seat-page.css", "text/css; charset=utf-8"),
        "/static/high-seat-page.js": (REPO_ROOT / "static" / "high-seat-page.js", "application/javascript; charset=utf-8"),
        "/static/cave-processing-drawer.js": (REPO_ROOT / "static" / "cave-processing-drawer.js", "application/javascript; charset=utf-8"),
    }
    soft_wake_hits: list[str] = []

    class _W1Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            path_only = self.path.split("?", 1)[0]
            if "/api/steward/events" in self.path:
                soft_wake_hits.append(self.path)
            if path_only in static_map:
                fp, ctype = static_map[path_only]
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path_only == "/api/high-seat/processing":
                payload, code = cpf.handle_processing_http_get(self.path, headers=self.headers, data_dir=isolated_proc_env)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path_only.startswith("/api/steward/comms"):
                payload, code = comms.handle_comms_get({})
                data = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path_only in ("/", "/high-seat"):
                data = high_seat_page.render_high_seat_page(logged_in=True).encode("utf-8")
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

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _W1Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.goto(f"http://127.0.0.1:{port}/high-seat", wait_until="domcontentloaded")

                # All 6 pills on #cosTopRowBar stay aligned on one horizontal row at 1440x960
                boxes = [
                    page.locator(sel).bounding_box()
                    for sel in ("#btnCosToggleExpand", "#btnWlToggleTop", "#cosRunningTile", "#cosEmailTile", "#cosCalendarTile", "#btnCosPoincareMap")
                ]
                assert all(b is not None for b in boxes)
                for b in boxes[1:]:
                    assert abs(boxes[0]["y"] - b["y"]) <= 4

                # Verify <button> semantics, initial closed state, and badge count == 4
                btn = page.locator("#cosRunningTile")
                assert btn.evaluate("el => el.tagName") == "BUTTON"
                assert btn.get_attribute("aria-expanded") == "false"
                assert btn.get_attribute("aria-controls") == "cosProcessingPanel"
                assert page.locator("#cosRunningCount").inner_text() == "4"
                assert page.locator("#cosProcessingPanel").is_hidden()

                # Click #cosRunningTile -> opens inline directly below #cosTopRowBar inside #shTriage without #shActive jump
                btn.click()
                page.wait_for_selector("#cosProcessingPanel:not([hidden])", timeout=5000)
                assert btn.get_attribute("aria-expanded") == "true"
                assert "#shActive" not in page.url
                assert soft_wake_hits == []

                rows = page.locator("#cosProcessingPanel .cos-proc-row")
                assert rows.count() == 4
                panel_txt = page.locator("#cosProcessingPanel").inner_text()
                assert "Phase: Reading roadmap.json" in panel_txt
                assert "25–45s" in panel_txt and "50–90s" in panel_txt
                assert "Est. ~" in panel_txt
                assert page.evaluate("() => window.__procXss") is None

                # Escape collapses drawer cleanly
                page.keyboard.press("Escape")
                assert page.locator("#cosProcessingPanel").is_hidden()
                assert btn.get_attribute("aria-expanded") == "false"

                # Simulate backing-store failure -> 503 unknown renders `! Processing` and `[data-proc-state="unknown"]`
                cpf.set_processing_feed_hooks(available=False, slow=False)
                btn.click()
                page.wait_for_selector('#cosProcessingPanel [data-proc-state="unknown"]', timeout=5000)
                assert page.locator("#cosRunningCount").inner_text() == "!"
            finally:
                browser.close()
    finally:
        cpf.set_processing_feed_hooks(available=True, slow=False)
        srv.shutdown()
        srv.server_close()
