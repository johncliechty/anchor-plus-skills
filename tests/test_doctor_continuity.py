"""Doctor navigation recovery with real app assets, template and transports.

Sessions and health runs are synthetic; no production service, PTY child or
model is launched. The ephemeral HTTP server exercises AnchorHandler itself.
"""
import importlib
import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def doctor_server(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "profile"))
    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    anchor_settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    import anchor_gui as gui
    monkeypatch.setattr(gui._aset, "read_settings_state", anchor_settings.read_settings_state)
    monkeypatch.setattr(gui._lanes, "detect_host_profile", lambda: {
        "claude": True, "chatgpt": True, "grok": True, "gemini": False})
    stats = {"status": "green", "status_text": "Healthy", "status_detail": "Synthetic check",
             "days_ago": None, "last_run": None, "report_count": 0,
             "reports": [], "issues": [], "warnings": []}
    monkeypatch.setattr(gui, "_doctor_stats", lambda: stats)
    monkeypatch.setattr(gui, "_build_doctor_seed", lambda: "Synthetic Doctor brief")
    monkeypatch.setattr(gui, "_doctor_probe_state", lambda: (stats, [], [], "rerun", []))
    state = {"records": {}, "outputs": {}, "starts": [], "health_starts": 0,
             "inputs": [], "health": {"started": False, "running": False, "text": "", "exit_code": None}}

    def start(seed_context=None, backend=None, resolve=False):
        if state.get('fail_start'):
            raise gui._termsess.TerminalSessionError('Synthetic launch denied')
        sid = "fixture-doctor-" + str(len(state["starts"]) + 1)
        rec = {"session_id": sid, "project_id": "__doctor__", "backend": backend,
               "status": "running", "doctor_mode": "resolve" if resolve else "diagnose",
               "doctor_posture": "write-enabled" if resolve else "read-only"}
        state["starts"].append({"id": sid, "backend": backend, "resolve": resolve})
        state["records"][sid] = rec
        state["outputs"][sid] = "PRIOR PROGRESS " + sid + " 🌟 é 漢字\r\n"
        return rec, False

    def read(sid, cursor=0):
        rec = state["records"].get(sid)
        if not rec:
            return {"ok": False, "reason": "unknown-session"}
        text = state["outputs"][sid]
        retained_start = max(0, len(text) - state.get('retain_chars', len(text)))
        return {"ok": True, "text": text[max(cursor, retained_start):], "next": len(text),
                "status": "running" if rec["status"] == "running" else "dead"}

    monkeypatch.setattr(gui._termsess, "start_doctor_session", start)
    monkeypatch.setattr(gui._termsess, "get_session", lambda sid: state["records"].get(sid))
    monkeypatch.setattr(gui._termsess, "list_sessions", lambda **kw: [
        r for r in state["records"].values()
        if r["project_id"] == kw.get("project_id") and r["status"] == kw.get("status")])
    monkeypatch.setattr(gui._termsess, "read_since", read)
    monkeypatch.setattr(gui._termsess, "resize", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(gui._termsess, "input", lambda sid, data: state["inputs"].append((sid, data)) or {"ok": True})

    class Handler(gui.AnchorHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if urlparse(self.path).path == "/api/doctor/healthcheck_tail":
                q = parse_qs(urlparse(self.path).query)
                since = int(q.get("since", ["0"])[0])
                health = state["health"]
                self._send_json({"ok": True, **health, "text": health["text"][since:], "next": len(health["text"])})
                return
            super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path == "/api/doctor/healthcheck_run":
                state["health_starts"] += 1
                self._send_json({"ok": False, "error": "Unexpected launch trapped by test"})
                return
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state["origin"] = "http://127.0.0.1:" + str(server.server_port)
    state["gui"] = gui
    state["stats"] = stats
    state["start"] = start
    yield state
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


@pytest.fixture
def app(doctor_server):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        origin = doctor_server["origin"]
        # A inert Cave avoids waking or modifying any steward conversation.
        ctx.route(origin + "/", lambda r: r.fulfill(body="<title>Cave</title><p>Navigation check</p>", content_type="text/html"))
        ctx.route("**/api/steward/**", lambda r: r.fulfill(json={"ok": True, "state": "quiet"}))
        # these tests prove a page comes back right after the app drops its frame (past the keep-alive cap):
        # cap 0 makes every hidden tile drop, as all of them did before 2026-10-08
        ctx.add_init_script("if(window===window.top)window.ANCHOR_KEEP_LIVE=0;")
        ctx.add_init_script("if(location.pathname==='/doctor')window.__instance=crypto.randomUUID();")
        page = ctx.new_page()
        failures = []
        responses = []
        page.on("pageerror", lambda err: failures.append(str(err)))
        def response_log(response):
            if '/api/doctor/' in response.url:
                try: responses.append({'url': response.url, 'status': response.status, 'body': response.json()})
                except Exception: pass
        page.on('response', response_log)
        doctor_server['responses'] = responses
        page.set_default_timeout(5000)
        page.goto(origin + "/static/app.html", wait_until="networkidle")
        page.evaluate("ANCHOR_APP.open('/doctor', '', window)")
        page.wait_for_function("Array.from(document.querySelectorAll('iframe')).some(f=>f.contentWindow.location.pathname==='/doctor')")
        frame = page.frame(url=origin + "/doctor")
        frame.wait_for_function("typeof runDiagnose==='function' && !document.getElementById('diagnoseBtn').disabled")
        yield page, frame, failures
        browser.close()


def navigate_back(page, origin):
    old = page.frame(url=origin + "/doctor").evaluate("window.__instance")
    page.locator("#strip .tile").first.click()
    page.wait_for_function("!Array.from(document.querySelectorAll('iframe')).some(f=>f.contentWindow.location.pathname==='/doctor')")
    page.locator("#strip .tile").filter(has_text="Anchor Doctor").click()
    page.wait_for_function("Array.from(document.querySelectorAll('iframe')).some(f=>f.contentWindow.location.pathname==='/doctor')")
    frame = page.frame(url=origin + "/doctor")
    frame.wait_for_function("typeof runDiagnose==='function'")
    assert frame.evaluate("window.__instance") != old
    return frame


@pytest.mark.parametrize("resolve", [False])   # W3: a write-enabled Resolve session no longer starts (see below)
def test_session_survives_frame_recreation(doctor_server, app, resolve):
    page, frame, failures = app
    frame.evaluate("resolve=>runDiagnose({resolve})", resolve)
    try:
        frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    except Exception:
        pytest.fail(json.dumps({'terminal': frame.locator('#terminal').inner_text(),
                                'responses': doctor_server['responses'], 'starts': doctor_server['starts'], 'errors': failures}))
    sid = doctor_server["starts"][0]["id"]
    frame = navigate_back(page, doctor_server["origin"])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    assert ("write-enabled" if resolve else "read-only") in frame.locator("#termEngine").inner_text()
    doctor_server["outputs"][sid] += "NEW OUTPUT AFTER RETURN\r\n"
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('NEW OUTPUT AFTER RETURN')")
    text = frame.locator("#terminal").inner_text()
    assert text.count("PRIOR PROGRESS") == 1
    assert "ANCHOR-CTL" not in text
    assert len(doctor_server["starts"]) == 1 and not doctor_server["inputs"]
    assert doctor_server["health_starts"] == 0 and not failures
    if os.environ.get('DOCTOR_CONTINUITY_EVIDENCE_DIR'):
        evidence = Path(os.environ['DOCTOR_CONTINUITY_EVIDENCE_DIR'])
        evidence.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(evidence / ('resolve-return.png' if resolve else 'diagnose-return.png')))


@pytest.mark.parametrize("running", [False, True])
def test_health_progress_restored_without_a_rerun(doctor_server, app, running):
    page, frame, failures = app
    doctor_server["health"].update(started=True, running=running, text="HEALTH PROGRESS\n", exit_code=None if running else 0)
    # An old report provokes the opening probe; restoration must suppress rerun.
    doctor_server["stats"]["issues"] = [{"component": "fixture", "detail": "Synthetic stale report"}]
    frame = navigate_back(page, doctor_server["origin"])
    frame.wait_for_function("document.getElementById('hcout').textContent.includes('HEALTH PROGRESS')")
    assert frame.locator("#hcout").is_visible()
    assert frame.locator("#runBtn").is_disabled() == running
    if running:
        doctor_server["health"].update(running=False, text="HEALTH PROGRESS\nCOMPLETE\n", exit_code=0)
        frame.wait_for_function("document.getElementById('hcout').textContent.includes('COMPLETE')")
        frame.wait_for_function("!document.getElementById('runBtn').disabled")
    assert doctor_server["health_starts"] == 0 and not doctor_server["starts"] and not failures
    if os.environ.get('DOCTOR_CONTINUITY_EVIDENCE_DIR'):
        evidence = Path(os.environ['DOCTOR_CONTINUITY_EVIDENCE_DIR'])
        evidence.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(evidence / ('health-running-return.png' if running else 'health-completed-return.png')))


def test_ws_fallback_replays_no_unicode_twice(doctor_server, app):
    page, frame, failures = app
    frame.evaluate("runDiagnose()")
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    sid = doctor_server["starts"][0]["id"]
    # Recreate the page with a controlled WS wrapper that closes after replay.
    page.context.add_init_script("""if(location.pathname==='/doctor') {
      const Native=window.WebSocket;
      window.WebSocket=class extends Native { constructor(url) { super(url);
        this.addEventListener('message', e=>{if(String(e.data).includes('replay_complete'))setTimeout(()=>this.close(),20);});
      }};
    }""")
    frame = navigate_back(page, doctor_server["origin"])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    page.wait_for_timeout(200)
    doctor_server["outputs"][sid] += "UNICODE FALLBACK 🌟 漢字\r\n"
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('UNICODE FALLBACK')")
    text = frame.locator("#terminal").inner_text()
    assert text.count("PRIOR PROGRESS") == 1 and text.count("UNICODE FALLBACK") == 1
    assert len(doctor_server["starts"]) == 1 and not failures


def test_missing_pointer_does_not_select_another_session(doctor_server, app):
    page, frame, failures = app
    frame.evaluate("runDiagnose()")
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    sid = doctor_server["starts"][0]["id"]
    del doctor_server["records"][sid]
    doctor_server["start"](backend="grok", resolve=True)
    frame = navigate_back(page, doctor_server["origin"])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('Saved session is unavailable')")
    bookmark = json.loads(frame.evaluate("sessionStorage.getItem('anchor_doctor_session_v1')"))
    assert bookmark['session_id'] == sid and bookmark['unavailable'] is True
    assert "PRIOR PROGRESS" not in frame.locator("#terminal").inner_text()
    assert len(doctor_server["starts"]) == 2 and not failures
    frame = navigate_back(page, doctor_server['origin'])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('Saved session is unavailable')")
    assert 'PRIOR PROGRESS' not in frame.locator('#terminal').inner_text()
    assert len(doctor_server['starts']) == 2


def test_discovery_is_unique_and_filters_foreign_and_unkeyed_sessions(doctor_server):
    state = doctor_server
    state["start"](backend="grok", resolve=True)
    recovery = state["gui"]._doctor_restore_session()
    assert recovery["session"]["mode"] == "resolve"
    assert "seed_text" not in recovery["session"]
    state["start"](backend="chatgpt", resolve=False)
    assert state["gui"]._doctor_restore_session()["error"] == "multiple"
    record = state["records"]["fixture-doctor-2"]
    record["project_id"] = "other-project"
    assert state["gui"]._doctor_restore_session(record["session_id"])["error"] == "unavailable"
    record["project_id"] = "__doctor__"
    del record["doctor_mode"]
    del record["doctor_posture"]
    assert state["gui"]._doctor_restore_session(record["session_id"])["error"] == "unavailable"


def test_a_refused_resolve_keeps_the_prior_session(doctor_server, app):
    """W3 (2026-10-08): the Doctor's code repair is off - a Resolve request is refused (it never starts a write
    session) and the read-only session he had stays his, still connected."""
    page, frame, failures = app
    frame.evaluate('runDiagnose()')
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    prior = doctor_server['starts'][0]['id']
    frame.evaluate('runDiagnose({resolve:true})')
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('code repair is off')")
    assert json.loads(frame.evaluate("sessionStorage.getItem('anchor_doctor_session_v1')"))['session_id'] == prior
    doctor_server['outputs'][prior] += 'PRIOR STILL CONNECTED\r\n'
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR STILL CONNECTED')")
    assert len(doctor_server['starts']) == 1 and not doctor_server['inputs']
    assert 'write-enabled' not in frame.locator('#termEngine').inner_text()


def test_auth_failure_preserves_pointer_without_a_replacement(doctor_server, app):
    page, frame, failures = app
    frame.evaluate('runDiagnose()')
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    prior = doctor_server['starts'][0]['id']
    page.context.route('**/api/doctor/status?restore=1*', lambda r: r.fulfill(status=401, json={'ok':False}))
    frame = navigate_back(page, doctor_server['origin'])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('Reconnection could not be checked')")
    assert json.loads(frame.evaluate("sessionStorage.getItem('anchor_doctor_session_v1')"))['session_id'] == prior
    assert len(doctor_server['starts']) == 1 and frame.locator('#diagnoseBtn').is_disabled()
    assert 'Saved session is unavailable' not in frame.locator('#terminal').inner_text()
    assert not failures


def test_truncated_replay_disconnect_before_confirmation_is_not_duplicated(doctor_server, app):
    page, frame, failures = app
    frame.evaluate('runDiagnose()')
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('PRIOR PROGRESS')")
    sid = doctor_server['starts'][0]['id']
    doctor_server['outputs'][sid] = 'OLDER OUTPUT ' * 500 + 'RETAINED PROGRESS 🌟 é 漢字\r\n'
    doctor_server['retain_chars'] = 60
    # Keep the real socket and its replay, but lose replay_complete exactly
    # before delivery. The existing real SSE endpoint must replay once from
    # its authoritative absolute cursor, including a dropped buffer prefix.
    page.context.add_init_script("""if(location.pathname==='/doctor') {
      const Native=window.WebSocket;
      window.WebSocket=class {
        constructor(url) {
          this.ws=new Native(url);
          this.ws.onmessage=e=>{
            if(String(e.data).startsWith('\\x00ANCHOR-CTL:') && String(e.data).includes('replay_complete')) {this.ws.close();return;}
            if(this.onmessage)this.onmessage(e);
          };
          this.ws.onclose=e=>{if(this.onclose)this.onclose(e);};
          this.ws.onerror=e=>{if(this.onerror)this.onerror(e);};
        }
        get readyState(){return this.ws.readyState;}
        send(data){this.ws.send(data);}
        close(){this.ws.close();}
      };
    }""")
    frame = navigate_back(page, doctor_server['origin'])
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('RETAINED PROGRESS')")
    assert frame.locator('#terminal').inner_text().count('RETAINED PROGRESS') == 1
    doctor_server['outputs'][sid] += 'AFTER EARLY FALLBACK\r\n'
    frame.wait_for_function("document.getElementById('terminal').textContent.includes('AFTER EARLY FALLBACK')")
    assert frame.locator('#terminal').inner_text().count('RETAINED PROGRESS') == 1
    assert len(doctor_server['starts']) == 1 and not failures
