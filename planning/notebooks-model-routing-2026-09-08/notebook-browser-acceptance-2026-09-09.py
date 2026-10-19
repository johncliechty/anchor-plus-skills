"""Private, interactive notebook acceptance check; never handles login input."""

import ctypes  # The same Windows API is used inside the remote Python cell.
import json
import platform
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


PLAN = Path(__file__).resolve().parent
RUNTIME = Path("C:/dev/Anchor/notebook-runtime.json")
BASE = "https://gwl-server.tailb49f65.ts.net:8448"


class SafeFailure(Exception):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


FETCH = """async ({path, method, body}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const xsrf = document.cookie.split('; ').find(c => c.startsWith('_xsrf='));
    const headers = {'Content-Type': 'application/json'};
    if (xsrf) headers['X-XSRFToken'] = decodeURIComponent(xsrf.slice(6));
    const response = await fetch(path, {
      method, headers, credentials: 'same-origin', redirect: 'manual',
      cache: 'no-store', signal: controller.signal,
      ...(body === null ? {} : {body: JSON.stringify(body)})
    });
    if (!response.ok) return {status: response.status, ok: false};
    if (response.status === 204) return {status: 204, ok: true, data: null};
    if (!(response.headers.get('content-type') || '').includes('application/json'))
      return {status: response.status, ok: false};
    return {status: response.status, ok: true, data: await response.json()};
  } catch (_) {
    return {status: null, ok: false};
  } finally { clearTimeout(timer); }
}"""


EXECUTE = """({kernel, code, session, message}) => new Promise(resolve => {
  const outputs = [];
  let reply = null, idle = false, count = null, finished = false, ws;
  const finish = error => {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    if (ws) ws.close();
    resolve({outputs, reply, idle, execution_count: count, error});
  };
  const timer = setTimeout(() => finish('EXECUTION_TIMEOUT'), 90000);
  try {
    const url = new URL('/api/kernels/' + encodeURIComponent(kernel) + '/channels', location.origin);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('session_id', session);
    // No subprotocol selects Jupyter's standard JSON message protocol.
    ws = new WebSocket(url);
    ws.onopen = () => ws.send(JSON.stringify({
      header: {msg_id: message, username: 'anchor-notebook-check', session,
               date: new Date().toISOString(), msg_type: 'execute_request', version: '5.3'},
      parent_header: {}, metadata: {}, channel: 'shell', buffers: [],
      content: {code, silent: false, store_history: false, user_expressions: {},
                allow_stdin: false, stop_on_error: true}
    }));
    ws.onmessage = event => {
      if (finished) return;
      if (typeof event.data !== 'string') { finish('UNEXPECTED_BINARY_PROTOCOL'); return; }
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { finish('INVALID_PROTOCOL_JSON'); return; }
      if (msg.parent_header?.msg_id !== message) return;
      const c = msg.content || {}, kind = msg.header?.msg_type;
      if (kind === 'stream') outputs.push({output_type: 'stream', name: c.name, text: c.text});
      if (kind === 'display_data') outputs.push({output_type: kind, data: c.data, metadata: c.metadata || {}});
      if (kind === 'execute_result') outputs.push({output_type: kind, data: c.data,
        metadata: c.metadata || {}, execution_count: c.execution_count});
      if (kind === 'error') outputs.push({output_type: 'error', ename: c.ename,
        evalue: c.evalue, traceback: c.traceback});
      if (kind === 'execute_reply') { reply = c.status; count = c.execution_count; }
      if (kind === 'status' && c.execution_state === 'idle') idle = true;
      if (reply !== null && idle) finish(null);
    };
    ws.onerror = () => finish('WEBSOCKET_ERROR');
    ws.onclose = () => finish('WEBSOCKET_CLOSED');
  } catch (_) { finish('WEBSOCKET_SETUP_FAILED'); }
})"""


PYTHON = '''import ctypes, platform
name = ctypes.create_unicode_buffer(257)
size = ctypes.c_ulong(len(name))
if not ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)):
    raise RuntimeError("GetUserNameW failed")
print("ANCHOR_LANGUAGE=python")
print("ANCHOR_HOST=" + platform.node())
print("ANCHOR_USER=" + name.value)
print("ANCHOR_ARITH=" + str(2 * 3))
'''
R = '''cat("ANCHOR_LANGUAGE=r\\n")
cat("ANCHOR_HOST=", unname(Sys.info()[["nodename"]]), "\\n", sep="")
cat("ANCHOR_USER=", unname(Sys.info()[["user"]]), "\\n", sep="")
cat("ANCHOR_ARITH=", 2 * 3, "\\n", sep="")
'''


def api(page, method, path, body=None, allow_missing=False):
    result = page.evaluate(FETCH, {"path": path, "method": method, "body": body})
    if allow_missing and result["status"] == 404:
        return None
    if not result["ok"]:
        raise SafeFailure("API_REQUEST_FAILED", result["status"])
    return result


def contents(path):
    return "/api/contents/" + quote(path, safe="/")


def new_path(page, path, body):
    if api(page, "GET", contents(path), allow_missing=True) is not None:
        raise SafeFailure("REFUSED_EXISTING_PATH")
    result = api(page, "PUT", contents(path), body)
    if result["status"] != 201:
        raise SafeFailure("NEW_PATH_NOT_CREATED", result["status"])


def notebook(kernel, language, code):
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": kernel, "display_name": kernel,
                                     "language": language}},
        "cells": [{"id": uuid.uuid4().hex[:8], "cell_type": "code", "metadata": {},
                   "source": code, "execution_count": None, "outputs": []}],
    }


def markers(outputs):
    text = "".join(o.get("text", "") for o in outputs if o["output_type"] == "stream")
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ANCHOR_LANGUAGE", "ANCHOR_HOST", "ANCHOR_USER", "ANCHOR_ARITH"}:
            values[key] = value.strip()
    return values


def main():
    run_id = uuid.uuid4().hex[:8]
    receipt_path = PLAN / ("notebook-browser-acceptance-2026-09-09-" + run_id + ".json")
    receipt = {"schema_version": 1, "time_utc": datetime.now(timezone.utc).isoformat(),
               "passed": False, "expected_host": platform.node(), "results": [], "cleanup": []}
    kernels, sessions = [], []
    browser = page = None
    try:
        if not RUNTIME.is_file():
            raise SafeFailure("PUBLIC_RUNTIME_MISSING")
        runtime = json.loads(RUNTIME.read_text(encoding="utf-8-sig"))
        root = runtime.get("root_dir")
        if not isinstance(root, str) or not root or not Path(root).is_absolute():
            raise SafeFailure("CONFIGURED_ROOT_INVALID")
        if runtime.get("public_base_url", "").rstrip("/") != BASE:
            raise SafeFailure("PUBLIC_BASE_URL_MISMATCH")
        receipt["configured_root_dir"] = root
        directory = "Anchor-notebook-check-20260909-" + run_id
        receipt["synthetic_directory"] = directory
        print("Opening JupyterLab. Enter its password privately in the browser.", flush=True)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto(BASE + "/lab", wait_until="domcontentloaded", timeout=60000)
                deadline = time.monotonic() + 900
                specs = None
                while time.monotonic() < deadline:
                    try:
                        probe = page.evaluate(FETCH, {"path": "/api/kernelspecs", "method": "GET", "body": None})
                    except Exception:
                        if page.is_closed():
                            raise SafeFailure("BROWSER_CLOSED_DURING_LOGIN") from None
                        time.sleep(1)
                        continue
                    if probe["ok"] and isinstance(probe.get("data", {}).get("kernelspecs"), dict):
                        specs = probe["data"]["kernelspecs"]
                        break
                    time.sleep(1)
                if specs is None:
                    raise SafeFailure("AUTHENTICATION_TIMEOUT")
                if not {"python3", "ir"}.issubset(specs):
                    raise SafeFailure("REQUIRED_KERNELS_MISSING")
                new_path(page, directory, {"type": "directory"})
                for kernel_name, language, code in [("python3", "python", PYTHON), ("ir", "r", R)]:
                    path = directory + "/" + language + "-check.ipynb"
                    doc = notebook(kernel_name, language, code)
                    new_path(page, path, {"type": "notebook", "format": "json", "content": doc})
                    row = {"language": language, "kernel_name": kernel_name, "path": path,
                           "absolute_path": str(Path(root) / Path(path)), "passed": False}
                    receipt["results"].append(row)
                    kernel = api(page, "POST", "/api/kernels", {"name": kernel_name})["data"]
                    kernels.append(kernel["id"])
                    session = api(page, "POST", "/api/sessions", {
                        "path": path, "name": path.rsplit("/", 1)[1], "type": "notebook",
                        "kernel": {"id": kernel["id"]},
                    })["data"]
                    sessions.append(session["id"])
                    if session["kernel"]["id"] != kernel["id"]:
                        kernels.append(session["kernel"]["id"])
                        raise SafeFailure("SESSION_KERNEL_MISMATCH")
                    execution = page.evaluate(EXECUTE, {"kernel": kernel["id"], "code": code,
                        "session": uuid.uuid4().hex, "message": uuid.uuid4().hex})
                    cell = doc["cells"][0]
                    cell["outputs"] = execution["outputs"]
                    cell["execution_count"] = execution["execution_count"]
                    api(page, "PUT", contents(path), {"type": "notebook", "format": "json", "content": doc})
                    reopened = api(page, "GET", contents(path))["data"]["content"]["cells"][0]
                    persisted = reopened["outputs"] == cell["outputs"] and reopened["source"] == code
                    observed = markers(execution["outputs"])
                    row.update({"observed": observed, "outputs_persisted": persisted,
                                "execute_reply": execution["reply"], "idle_received": execution["idle"],
                                "execution_error": execution["error"]})
                    page.goto(BASE + "/lab/tree/" + quote(path, safe="/"),
                              wait_until="domcontentloaded", timeout=60000)
                    # Only the synthetic notebook panel is captured, after its output is visible.
                    panel = page.locator(".jp-NotebookPanel:visible").filter(
                        has=page.locator(".jp-OutputArea-output").filter(has_text="ANCHOR_LANGUAGE=" + language))
                    panel.wait_for(state="visible", timeout=60000)
                    screenshot = PLAN / ("notebook-browser-acceptance-" + run_id + "-" + language + ".png")
                    panel.screenshot(path=str(screenshot), timeout=30000)
                    row["screenshot"] = str(screenshot)
                    row["ui_loaded"] = True
                    row["passed"] = bool(persisted and execution["reply"] == "ok" and execution["idle"]
                        and execution["error"] is None and observed.get("ANCHOR_LANGUAGE") == language
                        and observed.get("ANCHOR_HOST", "").casefold() == platform.node().casefold()
                        and observed.get("ANCHOR_ARITH") == "6"
                        and (language != "python" or observed.get("ANCHOR_USER") == "AnchorNotebook"))
                receipt["passed"] = len(receipt["results"]) == 2 and all(r["passed"] for r in receipt["results"])
            finally:
                if page is not None and not page.is_closed():
                    for kind, identifiers in [("sessions", sessions), ("kernels", kernels)]:
                        for identifier in dict.fromkeys(identifiers):
                            try:
                                api(page, "DELETE", "/api/" + kind + "/" + quote(identifier, safe=""), allow_missing=True)
                                receipt["cleanup"].append({"kind": kind, "deleted_or_absent": True})
                            except Exception as exc:
                                receipt["cleanup"].append({"kind": kind, "deleted_or_absent": False,
                                    "error_type": type(exc).__name__, "status": getattr(exc, "status", None)})
                                receipt["passed"] = False
                elif kernels or sessions:
                    receipt["cleanup"].append({"deleted_or_absent": False, "code": "BROWSER_UNAVAILABLE"})
                    receipt["passed"] = False
                if browser is not None:
                    browser.close()
    except Exception as exc:
        receipt["passed"] = False
        receipt["error"] = {"type": type(exc).__name__, "status": getattr(exc, "status", None)}
        if isinstance(exc, SafeFailure):
            receipt["error"]["code"] = exc.code
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(("PASS" if receipt["passed"] else "FAIL") + ": " + str(receipt_path), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
