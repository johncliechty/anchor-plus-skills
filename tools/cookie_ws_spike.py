"""Cookie-through-WS-upgrade spike + recorded verdict (rearch W3).

W9's cookie-based browser navigation (D3) hinges on one empirical question:
**does the browser send the auth cookie on a WebSocket upgrade request?** If
yes, the hand-rolled ``term_ws`` endpoint can authenticate the upgrade off the
session cookie and ``?token=`` disappears from page URLs entirely; if not,
``?token=`` stays as the declared WS fallback (already the W2 status quo:
query tokens are retained ONLY on WS/SSE transports).

The spike answers the PRE-WRITTEN acceptance questions (frozen with W3):

* **Q-COOKIE-DESKTOP** — a desktop browser (Playwright Chromium, driven by
  the gate) loads a page that sets an auth cookie, then opens a same-origin
  ``ws://`` connection: does the ``Cookie`` header arrive on the upgrade
  request with the auth value intact?
* **Q-COOKIE-PWA** — the iPhone PWA over Tailscale Serve HTTPS does the same
  against the real service. This leg CANNOT run in CI — it is a live manual
  runbook cell (below) to be executed with John; until then it is recorded
  honestly as not-yet-run.
* **Q-FALLBACK** — is ``?token=`` declared as the WS fallback if the Cookie
  header doesn't survive? (Declared by this spike, unconditionally: the W9
  wave consumes cookie-auth ONLY where a leg proved it; every unproven client
  keeps the query token on WS/SSE.)

The harness is a stdlib loopback capture server: ``GET /`` answers a page
that sets the spike cookie; a request to ``/spike-ws`` has its raw request
headers captured verbatim (the server never completes the WS handshake — the
question is what the CLIENT sends). The gate drives a real browser at it via
Playwright and records the desktop verdict mechanically;
``record_verdict`` merge-writes the checked-in artifacts
``planning/rearch-2026-07/SPIKE-COOKIE-WS-VERDICT.{json,md}``.

Stdlib only (``socket``, ``threading``, ``json``).
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"
VERDICT_JSON_NAME = "SPIKE-COOKIE-WS-VERDICT.json"
VERDICT_MD_NAME = "SPIKE-COOKIE-WS-VERDICT.md"

COOKIE_NAME = "anchor_spike_token"
COOKIE_VALUE = "spike-cookie-value-1"
WS_PATH = "/spike-ws"

ACCEPTANCE_QUESTIONS = (
    {"id": "Q-COOKIE-DESKTOP",
     "question": "Does a desktop browser send the auth cookie (Cookie "
                 "header, value intact) on a same-origin WebSocket upgrade "
                 "request?"},
    {"id": "Q-COOKIE-PWA",
     "question": "Does the iPhone PWA over Tailscale Serve HTTPS send the "
                 "auth cookie on the WebSocket upgrade against the real "
                 "service? (LIVE-MANUAL leg — runbook below, run with "
                 "John.)"},
    {"id": "Q-FALLBACK",
     "question": "Is ?token= declared as the WS fallback if the Cookie "
                 "header doesn't survive?"},
)

#: The declared fallback — recorded in the verdict unconditionally.
FALLBACK_DECLARATION = (
    "?token= remains the WS/SSE fallback: W9 adopts cookie-auth on a "
    "transport ONLY where a spike leg proved the cookie survives; every "
    "unproven client/transport keeps the query token (the W2 status quo)."
)

#: The manual runbook for the PWA leg (rendered into the verdict doc).
PWA_RUNBOOK = (
    "1. On the phone: install/refresh the Anchor PWA over the Tailscale "
    "Serve HTTPS origin (see planning/anchor-as-app).",
    "2. Set ANCHOR_TOKEN on the service; sign the PWA in so the auth cookie "
    "is set for the HTTPS origin.",
    "3. Open a project window and start a terminal (a term_ws upgrade).",
    "4. On the server: log the upgrade request's Cookie header "
    "(temporarily, via the term_ws handler) — record whether the cookie "
    "arrived with the upgrade.",
    "5. Record the answer with: python tools/cookie_ws_spike.py "
    "--record-pwa yes|no",
)


# ── the loopback capture server ───────────────────────────────────────────────

_PAGE = (b"<!doctype html><html><body>cookie-ws spike page</body></html>")


def start_capture_server():
    """Start the loopback capture server.

    Returns ``(port, state, stop)`` where ``state['ws_request']`` becomes the
    raw request head (str) of the first ``/spike-ws`` request observed, and
    ``stop()`` shuts the server down.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    srv.settimeout(0.25)
    port = srv.getsockname()[1]
    state = {"ws_request": None, "stopping": False}

    def _serve():
        while not state["stopping"]:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(3)
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 65536:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    head += chunk
                text = head.decode("latin-1", errors="replace")
                request_line = text.split("\r\n", 1)[0]
                if WS_PATH in request_line:
                    if state["ws_request"] is None:
                        state["ws_request"] = text
                    conn.sendall(b"HTTP/1.1 400 Bad Request\r\n"
                                 b"Connection: close\r\n\r\n")
                else:
                    cookie = (f"{COOKIE_NAME}={COOKIE_VALUE}; Path=/"
                              ).encode("latin-1")
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/html\r\n"
                        b"Set-Cookie: " + cookie + b"\r\n"
                        b"Content-Length: " +
                        str(len(_PAGE)).encode() + b"\r\n"
                        b"Connection: close\r\n\r\n" + _PAGE)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            srv.close()
        except OSError:
            pass

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    def stop():
        state["stopping"] = True
        t.join(timeout=5)

    return port, state, stop


def evaluate_desktop(state) -> dict:
    """Judge the captured upgrade request → the Q-COOKIE-DESKTOP answer."""
    raw = state.get("ws_request")
    if not raw:
        return {"pass": False,
                "detail": "no WebSocket upgrade request was captured"}
    headers = {}
    for line in raw.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    is_upgrade = "websocket" in headers.get("upgrade", "").lower()
    cookie = headers.get("cookie", "")
    sent = f"{COOKIE_NAME}={COOKIE_VALUE}" in cookie
    return {
        "pass": bool(is_upgrade and sent),
        "detail": ("Cookie header arrived on the upgrade with the auth value "
                   "intact" if (is_upgrade and sent) else
                   f"upgrade={is_upgrade}, cookie header={cookie!r}"),
    }


# ── the checked-in verdict artifacts (merge-written) ──────────────────────────

def _leg_verdict(answer):
    return "YES" if answer.get("pass") else "NO"


def _render_md(payload) -> str:
    legs = payload["legs"]
    lines = [
        "# Spike verdict — cookie through the WS upgrade (rearch W3)",
        "",
        "Recorded against the PRE-WRITTEN acceptance questions (frozen with "
        "W3). Refreshed mechanically by `tools/cookie_ws_spike.py "
        "record_verdict`; never hand-edited. Consumed by W9 (cookie "
        "navigation + the ?token= WS fallback decision).",
        "",
        "## Acceptance questions (pre-written)",
        "",
    ]
    for q in payload["questions"]:
        lines.append(f"- **{q['id']}** — {q['question']}")
    lines += ["", "## Q-COOKIE-DESKTOP — desktop browser (mechanical leg)",
              ""]
    desktop = legs.get("desktop")
    if not desktop or not desktop.get("ran"):
        lines += ["**NOT YET RUN** — the gate's Playwright leg records this "
                  "verdict mechanically.", ""]
    else:
        lines += [f"**Verdict: {_leg_verdict(desktop['answer'])}** — "
                  f"{desktop['answer'].get('detail', '')}",
                  "",
                  f"Browser: {desktop.get('browser', 'chromium')} "
                  f"(same-origin ws:// against the loopback capture server).",
                  ""]
    lines += ["## Q-COOKIE-PWA — iPhone PWA over Tailscale HTTPS "
              "(LIVE-MANUAL leg)", ""]
    pwa = legs.get("pwa")
    if not pwa or not pwa.get("ran"):
        lines += ["**NOT YET RUN** — this leg needs the REAL clients (the "
                  "phone + the live service over Tailscale Serve HTTPS) and "
                  "is executed with John. Until it runs, W9 must treat the "
                  "PWA as UNPROVEN and keep the ?token= fallback on its WS "
                  "transport.", "", "Runbook:", ""]
        lines += [f"{step}" for step in PWA_RUNBOOK]
        lines.append("")
    else:
        lines += [f"**Verdict: {_leg_verdict(pwa['answer'])}** — "
                  f"{pwa['answer'].get('detail', '')}", ""]
    lines += [
        "## Q-FALLBACK — the declared WS fallback",
        "",
        f"**DECLARED.** {FALLBACK_DECLARATION}",
        "",
    ]
    return "\n".join(lines)


def record_verdict(desktop_result=None, pwa_result=None, out_dir=None):
    """Merge leg results into the checked-in verdict artifacts.

    Either result may be ``None`` (leave that leg as recorded). The fallback
    declaration is always present. Skips unchanged rewrites. Returns
    ``(json_path, md_path)``.
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / VERDICT_JSON_NAME
    md_path = out / VERDICT_MD_NAME

    payload = {
        "schema": 1,
        "spike": "cookie-through-ws-upgrade",
        "questions": list(ACCEPTANCE_QUESTIONS),
        "fallback_declared": True,
        "fallback": FALLBACK_DECLARATION,
        "legs": {},
    }
    if json_path.exists():
        try:
            prior = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(prior.get("legs"), dict):
                payload["legs"] = prior["legs"]
        except (json.JSONDecodeError, OSError):
            pass
    changed = False
    if desktop_result is not None:
        changed |= payload["legs"].get("desktop") != desktop_result
        payload["legs"]["desktop"] = desktop_result
    if pwa_result is not None:
        changed |= payload["legs"].get("pwa") != pwa_result
        payload["legs"]["pwa"] = pwa_result

    if changed or not json_path.exists():
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True)
                             + "\n", encoding="utf-8")
    if changed or not md_path.exists():
        md_path.write_text(_render_md(payload), encoding="utf-8")
    return json_path, md_path


def main(argv=None):  # pragma: no cover - thin CLI shim
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if "--record-pwa" in argv:
        ans = argv[argv.index("--record-pwa") + 1].strip().lower()
        ok = ans in ("yes", "y", "true", "1")
        jp, mp = record_verdict(pwa_result={
            "ran": True,
            "answer": {"pass": ok,
                       "detail": "recorded from the live manual runbook run "
                                 f"(answer: {ans})"},
        })
        print(f"recorded → {jp}\nrendered → {mp}")
        return 0
    # default: (re)render the artifacts from what is already recorded
    jp, mp = record_verdict()
    print(f"rendered → {jp}\n          {mp}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
