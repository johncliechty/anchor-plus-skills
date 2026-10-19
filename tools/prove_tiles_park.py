"""Proof (2026-10-08, the tiles keep-alive): a REAL cockpit kept alive in a hidden app tile parks its event poll and
holds its build self-reload; shown again it resumes, with its draft and page intact.

A throwaway Anchor from THIS checkout on a free port (never 8777), its own data dir holding one made-up project with
two efforts, STEWARD_COCKPIT_FAKE=1 (no model is ever called), no token. Prints one JSON line per check; exit 0 iff
all pass. usage: python tools/prove_tiles_park.py [evidence.json]"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(json.dumps(results[-1]), flush=True)


scratch = Path(tempfile.mkdtemp(prefix="tiles-park-", dir=os.environ.get("ANCHOR_PROOF_DIR") or None))
proj = scratch / "Proof Project"
for eff in ("Effort One", "Effort Two"):
    (proj / eff).mkdir(parents=True)
    (proj / eff / "ECGBERHT.md").write_text("# %s\n\nA made-up effort for the tiles proof.\n" % eff, encoding="utf-8")
data = scratch / "data"
data.mkdir()
pid = "a" * 32
(data / "rnd_registry.json").write_text(json.dumps([{"id": pid, "name": "Proof Project", "folder_path": str(proj),
                                                      "priority": 2, "state": "active"}]), encoding="utf-8")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
assert port != 8777
env = dict(os.environ, ANCHOR_DATA_DIR=str(data), ANCHOR_PORT=str(port), STEWARD_COCKPIT_FAKE="1",
           ANCHOR_SERVED_ROOT=str(HERE), ANCHOR_CODE_JOBS_DIR=str(scratch / "jobs"), ANCHOR_WORKTREE_BASE=str(scratch / "wt"),
           ANCHOR_PROACTIVE_SUMMARY="0")
env.pop("ANCHOR_TOKEN", None)
log = open(scratch / "server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, str(HERE / "anchor_gui.py"), "--port", str(port), "--no-browser"],
                        cwd=str(scratch), env=env, stdout=log, stderr=subprocess.STDOUT)
base = "http://127.0.0.1:%d" % port
try:
    t0 = time.time()
    while time.time() - t0 < 180:
        try:
            urllib.request.urlopen(base + "/api/version", timeout=5); break
        except Exception:
            time.sleep(1)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
        polls = []                                     # (time, frame url) of every events poll
        page.on("request", lambda r: polls.append((time.time(), r.frame.url if r.frame else "")) if "/api/steward/events" in r.url else None)
        page.goto(base + "/static/app.html", wait_until="load")
        page.wait_for_function("() => document.querySelector('#stage iframe')")
        cave = page.frames[1] if len(page.frames) > 1 else page.main_frame
        one = "/steward/v1?pid=%s&dir=Effort%%20One" % pid
        two = "/steward/v1?pid=%s&dir=Effort%%20Two" % pid
        cave.evaluate("u => window.open(u)", one)
        page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2", timeout=60000)
        page.wait_for_timeout(4000)

        def fr(sub):
            return next((f for f in page.frames if sub in f.url), None)
        f1 = fr("Effort%20One")
        check("the cockpit for Effort One opened as a tile", f1 is not None, [f.url for f in page.frames])
        f1.wait_for_selector("[data-say]", timeout=60000)
        f1.evaluate("window.__alive = 'same page'")
        f1.locator("[data-say]").fill("a half-dictated thought")
        shown_at = time.time()
        page.wait_for_timeout(20000)                  # the control: the same 20 s while shown
        before = [x for x in polls if "Effort%20One" in x[1] and x[0] > shown_at]
        check("while shown it polls its events (the same 20 s)", len(before) >= 2, len(before))
        cave.evaluate("u => window.open(u)", two)
        page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3", timeout=60000)
        page.wait_for_timeout(2000)
        hidden_at = time.time()
        page.wait_for_timeout(20000)                  # well past an 8 s long-poll and the 15 s old drop timer
        during = [x for x in polls if "Effort%20One" in x[1] and x[0] > hidden_at]
        f1 = fr("Effort%20One")
        check("hidden, its page is kept (not reloaded)", f1 is not None and f1.evaluate("window.__alive") == "same page")
        check("hidden, it starts no event poll for 20 s", len(during) == 0, len(during))
        check("hidden, its build self-reload holds", f1.evaluate("!!(window.__stewardBusy && window.__stewardBusy())"))
        page.locator("#strip .tile").nth(1).click()
        page.wait_for_timeout(4000)
        after = [x for x in polls if "Effort%20One" in x[1] and x[0] > hidden_at + 20]
        check("shown again, it polls again", len(after) > 0, len(after))
        check("shown again, the draft is there", f1.locator("[data-say]").input_value() == "a half-dictated thought")
        b.close()
finally:
    proc.terminate()
    try:
        proc.wait(20)
    except Exception:
        proc.kill()
    log.close()
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(results, indent=2), encoding="utf-8")
bad = [r for r in results if not r["ok"]]
print("%d/%d checks passed" % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
