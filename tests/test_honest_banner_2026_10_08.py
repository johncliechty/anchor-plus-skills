"""W3 of the night of 2026-10-08 (John that day: "I want it to diagnose, resolve health issues and have the banner go
down once that is done"): the banner tells the truth.

Red stays while the running Anchor's newest report fails, and only a run that checks the running code clears it (the
"fix verified on anchor-next" candidate state went with the Anchor activation path, 2026-10-12). One report store; the
live probe counts an error status as a failure; the health check never kills the running service; the Doctor's code
repair is off. Every proof runs on throwaway data folders - never C:\\dev\\Anchor, never :8777."""
import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import health_state as hs  # noqa: E402

RED = "# Anchor Health Report\n\nStatus: ISSUES FOUND\nRevision: x\n\n## Issues\n- [server] /api/status 500\n"
GREEN = "# Anchor Health Report\n\nStatus: OK\nRevision: y\n\n## Warnings\n(none)\n"


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "health_reports").mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    return data / "health_reports"


def _report(reports, name, body, age_s=0):
    p = reports / name
    p.write_text(body, encoding="utf-8")
    t = time.time() - age_s
    os.utime(str(p), (t, t))
    return p


def test_only_dated_reports_count_and_one_reading_classifies_them(reports):
    _report(reports, "2026-10-08.md", RED, age_s=60)
    _report(reports, "README.md", GREEN)
    _report(reports, "soak-2026-10-09.md", GREEN)
    _report(reports, "candidate-abc.md", GREEN)
    path, body = hs.latest()
    assert path.name == "2026-10-08.md" and hs.status_of(body) == "red"
    assert hs.status_of(GREEN) == "green" and hs.status_of("Status: OK\n\n## Warnings\n- slow home page\n") == "yellow"
    assert hs.status_of("nonsense") == "unknown"


def test_red_stays_until_a_run_of_the_running_code_passes(reports):
    _report(reports, "2026-10-08.md", RED, age_s=120)
    b = hs.banner()
    assert b["status"] == "red" and b["why"].endswith("Doctor can diagnose it")
    before = hs.signature()
    _report(reports, "2026-10-08.md", GREEN)
    assert hs.banner() is None and hs.signature() != before


def test_nothing_waits_on_anchor_next_any_more():
    """2026-10-12: no candidate check, no owed re-check, no "fix verified" line - Anchor's code is installed from
    outside Anchor."""
    import anchor_gui
    for gone in ("check_candidate", "recheck_needed", "verified_candidate", "mark_rechecked"):
        assert not hasattr(hs, gone), gone
    for gone in ("_doctor_start_candidate_check", "_health_recheck_if_owed", "_schedule_health_recheck"):
        assert not hasattr(anchor_gui, gone), gone
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert "anchor-next" not in src and "import anchor_next" not in src


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = int(self.path.strip("/") or 200)
        self.send_response(code)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_the_live_probe_counts_an_error_status_as_a_failure(monkeypatch):
    import anchor_gui
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_PORT", str(srv.server_address[1]))
        assert anchor_gui._doctor_live_probe("/200")["ok"] is True
        for code in ("401", "404", "500"):
            r = anchor_gui._doctor_live_probe("/" + code)
            assert r["ok"] is False and r["code"] == int(code), r
    finally:
        srv.shutdown()


def test_the_health_check_never_kills_the_running_service(monkeypatch):
    import anchor_healthcheck as hc
    netstat = ("  TCP    0.0.0.0:8777     0.0.0.0:0   LISTENING   4242\n"
               "  TCP    0.0.0.0:%d     0.0.0.0:0   LISTENING   5151\n"
               "  TCP    127.0.0.1:51515  127.0.0.1:8778  ESTABLISHED   4242\n") % hc.TEST_PORT
    killed = []

    def fake_run(argv, **kw):
        if argv[0] == "taskkill":
            killed.append(int(argv[-1]))
        class R:
            stdout = "2026-01-01T00:00:00"
        return R()
    monkeypatch.setattr(hc.sys, "platform", "win32")
    monkeypatch.setattr(hc.subprocess, "check_output", lambda *a, **k: netstat)
    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    monkeypatch.delenv("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", raising=False)
    hc.cleanup_stale_processes(hc.Report())
    assert killed == [5151], "only the test port's listener; never 8777 (pid 4242), never by a substring match"


def test_a_report_names_its_revision(tmp_path):
    import anchor_healthcheck as hc
    out = tmp_path / "r.md"
    hc.Report().write(out)
    text = out.read_text(encoding="utf-8")
    assert "\nRevision: " in text and "\nTarget: " not in text


def test_the_doctors_code_repair_is_off(monkeypatch):
    import anchor_gui
    sent = []

    class H:
        def _send_json(self, obj, code=200):
            sent.append((code, obj))
    monkeypatch.setattr(anchor_gui._aset, "get_launch_settings",
                        lambda: {"default_cli": "claude", "coding_family": "claude", "review_family": "chatgpt", "settings_revision": 1})
    monkeypatch.setattr(anchor_gui, "_w8_shared_session_start_plan", lambda **k: {"engine": "claude"})
    anchor_gui.handle_doctor_session_start(H(), "/api/doctor/session_start", {"resolve": True, "issue": {"message": "x"}})
    assert sent and sent[0][0] == 409 and sent[0][1]["status"] == "repair_off"
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert "resolve: true" not in src.split("_DOCTOR_PAGE_TEMPLATE", 1)[1], "the Doctor page never asks for a write session"


# ---------- ChatGPT review round 1 ----------


def test_8777_is_never_a_test_port(monkeypatch):
    import anchor_healthcheck as hc
    netstat = "  TCP    0.0.0.0:8777     0.0.0.0:0   LISTENING   4242\n"
    killed = []
    monkeypatch.setattr(hc, "TEST_PORT", 8777)
    monkeypatch.setattr(hc.sys, "platform", "win32")
    monkeypatch.setattr(hc.subprocess, "check_output", lambda *a, **k: netstat)
    monkeypatch.setattr(hc.subprocess, "run", lambda argv, **k: killed.append(argv) or type("R", (), {"stdout": "2026-01-01T00:00:00"})())
    monkeypatch.delenv("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", raising=False)
    hc.cleanup_stale_processes(hc.Report())
    assert not [a for a in killed if a[0] == "taskkill"]


class _Version(http.server.BaseHTTPRequestHandler):
    build = "abc1234+ff"

    def do_GET(self):
        body = json.dumps({"version": self.build}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_running_pass_needs_the_running_service_on_the_checked_code(monkeypatch):
    """The served SOURCES' fingerprint decides (ChatGPT hardening): a steward's record checkpoint moves HEAD without
    changing the code - still a pass; different code running - a failure; nothing running - a failure."""
    import anchor_healthcheck as hc

    def server(build):
        h = type("V", (_Version,), {"build": build})
        s = http.server.HTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        return s
    running, checked = server("aaaaaaa+fp1"), server("bbbbbbb+fp1")      # another commit, the same code
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(running.server_address[1]))
        monkeypatch.setattr(hc, "TEST_PORT", checked.server_address[1])
        monkeypatch.setattr(hc, "_previous_issue_paths", lambda: [])
        r = hc.Report()
        hc.check_running_service(r)
        assert any(c[0] == "the running service runs the checked code" and c[1] for c in r.checks), r.checks
        checked.RequestHandlerClass.build = "bbbbbbb+fp2"                 # different code
        r = hc.Report()
        hc.check_running_service(r)
        assert any(c[0] == "the running service runs the checked code" and not c[1] for c in r.checks)
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", "1")
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues, "no running service, no pass"
    finally:
        running.shutdown()
        checked.shutdown()


class _Service(http.server.BaseHTTPRequestHandler):
    build = "abc1234+ff"
    broken = "/api/status"

    def do_GET(self):
        if self.path == "/api/version":
            body = json.dumps({"version": self.build}).encode()
            self.send_response(200)
        elif self.path.startswith("/api/") and not self.headers.get("Authorization"):
            body = b"no"                                   # a protected read, asked without the service's token
            self.send_response(401)
        elif self.path.split("?")[0] == self.broken:
            body = b"boom"
            self.send_response(500)
        else:
            body = b"ok"
            self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_the_running_service_must_answer_its_own_pages_not_only_its_version(monkeypatch):
    import anchor_healthcheck as hc
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(srv.server_address[1]))
        monkeypatch.setenv("ANCHOR_TOKEN", "t")
        monkeypatch.setattr(hc, "RUN_REVISION", "abc1234def")
        monkeypatch.setattr(hc, "TEST_PORT", srv.server_address[1])     # the checked code: the same build here
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any("GET /api/status" in c[0] and not c[1] for c in r.checks), r.checks
        _Service.broken = "/nothing"
        r = hc.Report()
        hc.check_running_service(r)
        assert not r.has_issues, r.checks
    finally:
        _Service.broken = "/api/status"
        srv.shutdown()


def test_an_older_run_never_overwrites_a_newer_runs_report(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    today = tmp_path / ("%s.md" % hc.TODAY)
    today.write_text("Status: OK\nRun: %.3f\n" % (time.time() + 100), encoding="utf-8")
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % time.time())
    assert hc._newer_run_published(today) is True
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % (time.time() + 200))
    assert hc._newer_run_published(today) is False


def test_the_cave_acknowledges_only_the_fingerprint_a_placed_request_carried():
    js = (ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert "if (h && h !== healthSig) { healthPending = h; renewInPlace(); }" in js
    assert "var sig = healthPending;   // the fingerprint THIS request will place" in js
    assert "if (sig) { healthSig = sig; if (healthPending === sig) healthPending = ''; }" in js
    assert "if (placeAgain || (healthPending" not in js, "a failed repaint waits for the next poll, never loops"


# ---------- ChatGPT review round 3 ----------

def test_a_run_without_the_services_token_never_passes_while_issues_are_open(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(srv.server_address[1]))
        monkeypatch.setattr(hc, "RUN_REVISION", "abc1234def")
        monkeypatch.setattr(hc, "REPORTS_DIR", tmp_path)
        (tmp_path / "2026-10-07.md").write_text("Status: ISSUES FOUND\n\n## Issues\n- [HTTP endpoints] GET /api/status: 500\n- [HTTP endpoints] failures: GET /a GET /b GET /c GET /d GET /e GET /f GET /g GET /h GET /i\n", encoding="utf-8")
        assert len(hc._previous_issue_paths()) == 10, "every affected target, no cap"
        monkeypatch.setattr(hc, "_TOKEN_MINTED", True)       # the daily task: the throwaway's token is never used live
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any("not verifiable without the service's token" in c[2] for c in r.checks)
        monkeypatch.setattr(hc, "_TOKEN_MINTED", False)
        monkeypatch.setenv("ANCHOR_TOKEN", "the-service-token")
        _Service.broken = "/i"                                 # the ninth/tenth affected endpoint still fails
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any(c[0].endswith("GET /i") and not c[1] for c in r.checks)
    finally:
        _Service.broken = "/api/status"
        srv.shutdown()


def test_publication_is_one_locked_step_and_an_older_run_never_overwrites(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    path = tmp_path / ("%s.md" % hc.TODAY)
    monkeypatch.setattr(hc, "SERVICE_BOOT", "b1")                      # the probed instance is still the one running
    monkeypatch.setattr(hc, "_live_boot", lambda: "b1")
    newer_id = "%.3f" % (time.time() + 100)
    monkeypatch.setattr(hc, "RUN_ID", newer_id)
    hc._publish(hc.Report(), path)
    assert ("\nRun: %s\n" % newer_id) in path.read_text(encoding="utf-8")
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % time.time())     # an OLDER run finishing later
    hc._publish(hc.Report(), path)
    assert ("\nRun: %s\n" % newer_id) in path.read_text(encoding="utf-8"), "the newer run's report stands"
    assert list(tmp_path.glob("superseded-*.md")), "kept beside it, never over it"
    assert not (tmp_path / ".publish.lock").exists()


# ---------- the hardening round ----------


def test_without_its_lock_a_run_never_publishes_the_report(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    path = tmp_path / ("%s.md" % hc.TODAY)
    path.write_text("Status: ISSUES FOUND\n", encoding="utf-8")
    (tmp_path / ".publish.lock").write_text("held", encoding="utf-8")      # a fresh lock another run holds
    monkeypatch.setattr(hc.time, "sleep", lambda s: None)
    real_time = hc.time.time
    clock = [real_time()]
    monkeypatch.setattr(hc.time, "time", lambda: clock.__setitem__(0, clock[0] + 5) or clock[0])
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % real_time())
    hc._publish(hc.Report(), path)
    assert path.read_text(encoding="utf-8") == "Status: ISSUES FOUND\n", "the report another run holds is untouched"
    assert list(tmp_path.glob("unpublished-*.md"))


def test_an_issue_path_ends_where_the_sentence_does(tmp_path, monkeypatch):
    """Caught by the end-to-end proof: 'GET /api/status.' was asked as /api/status. (a 404) and the banner stayed."""
    import anchor_healthcheck as hc
    monkeypatch.setattr(hc, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-10-07.md").write_text("Status: ISSUES FOUND\n\n## Issues\n- [the running service: GET /api/status.] answered 500\n"
                                            "- [HTTP endpoints] failures: GET /api/status: HTTP Error 500, GET /high-seat?x=1.\n", encoding="utf-8")
    assert hc._previous_issue_paths() == ["/api/status", "/high-seat?x=1"]


# ---------- the final reviews (Fable, ChatGPT) ----------

def test_a_walks_label_is_never_carried_as_a_route(tmp_path, monkeypatch):
    """Fable: '[R&D v2 surface] GET /summary: timed out' names a label, not a route - asking the live service for it
    would 404 every day and keep the banner red forever."""
    import anchor_healthcheck as hc
    monkeypatch.setattr(hc, "REPORTS_DIR", tmp_path)
    monkeypatch.delenv("ANCHOR_HEALTH_AFFECTED", raising=False)
    (tmp_path / "2026-10-07.md").write_text("Status: ISSUES FOUND\n\n## Issues\n- [R&D v2 surface] GET /summary: timed out\n"
                                            "- [auth walk] GET /api/routes (authed) failed\n- [HTTP endpoints] failures: GET /api/status: 500\n",
                                            encoding="utf-8")
    assert hc._previous_issue_paths() == ["/api/status"]


# ---------- the confirmation round (ChatGPT) ----------

def test_a_pass_is_published_only_with_its_probed_instance_still_running(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    path = tmp_path / ("%s.md" % hc.TODAY)
    path.write_text("Status: ISSUES FOUND\n", encoding="utf-8")
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % (time.time() + 500))
    for probed, live in (("b1", ""), ("", "b1"), ("b1", "b2")):
        monkeypatch.setattr(hc, "SERVICE_BOOT", probed)
        monkeypatch.setattr(hc, "_live_boot", lambda live=live: live)
        hc._publish(hc.Report(), path)
        assert path.read_text(encoding="utf-8") == "Status: ISSUES FOUND\n", (probed, live)
    monkeypatch.setattr(hc, "SERVICE_BOOT", "b1")
    monkeypatch.setattr(hc, "_live_boot", lambda: "b1")
    hc._publish(hc.Report(), path)
    assert "Status: OK" in path.read_text(encoding="utf-8")


def test_the_cave_reads_the_banners_fingerprint_before_the_banner():
    """ChatGPT + Grok, last pass: read in that order, a report published in between leaves the page's fingerprint
    older than its banner, and the page's next poll places the newer one."""
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    i_sig, i_banner = src.index("    health_sig = _health_sig_for_boot()"), src.index("    hr = latest_health_report()\n    names = {")
    assert i_sig < i_banner and '"health_sig": health_sig,' in src
