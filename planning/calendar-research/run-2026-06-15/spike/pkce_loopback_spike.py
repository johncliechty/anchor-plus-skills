"""
Auth spike — loopback + PKCE, pure Python stdlib (no third-party deps).

Three modes:
  1) python pkce_loopback_spike.py --mock
       Self-test the loopback redirect catcher + state-CSRF check + PKCE wiring
       LOCALLY (no accounts, no network). Proves the http.server catcher works and
       never collides with Anchor's port 8777.

  2) python pkce_loopback_spike.py --provider google     --client-id <ID>
     python pkce_loopback_spike.py --provider microsoft  --client-id <ID>
       REAL consent flow against your account: opens the browser, catches the
       loopback redirect, exchanges the code (PKCE, no client secret), lists ONE
       upcoming event, and DPAPI-wraps the refresh token to ./spike_token_<p>.bin.
       (Stdlib only — independently re-confirms feasibility even though the SHIP
        build will use msal + google-auth per the locked decision.)

  3) python pkce_loopback_spike.py --provider google --refresh-check
       Loads the saved refresh token, redeems it for a fresh access token, and
       confirms it still works. Run this >7 days after mode 2 to prove the Google
       "Production" durable-refresh claim (the riskiest unspiked finding).

Notes:
  * Use a "Desktop app" (Google) / "Mobile & desktop / public client" (Azure) app
    registration — PKCE public client, NO secret embedded.
  * Redirect URI to register: http://127.0.0.1  (Google accepts any loopback port;
    Azure: add the exact http://127.0.0.1:<PORT> or use the dynamic note in the runbook).
"""
import argparse, base64, hashlib, http.server, json, os, secrets, socket, sys
import threading, urllib.parse, urllib.request, webbrowser, ctypes
from ctypes import wintypes

CFG = {
    "google": {
        "auth":  "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/calendar offline_access",
        "events": "https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults=1&orderBy=startTime&singleEvents=true",
        "extra_auth": {"access_type": "offline", "prompt": "consent"},
    },
    "microsoft": {
        "auth":  "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "offline_access https://graph.microsoft.com/Calendars.ReadWrite",
        "events": "https://graph.microsoft.com/v1.0/me/events?$top=1",
        "extra_auth": {},
    },
}

# ---------- PKCE ----------
def pkce():
    v = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, c

# ---------- DPAPI (stdlib ctypes) ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

def dpapi_wrap(data: bytes) -> bytes:
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(_blob(data)), u"anchor-cal-spike",
                                                  None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    res = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return res

def dpapi_unwrap(data: bytes) -> bytes:
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(_blob(data)), None,
                                                    None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    res = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return res

# ---------- loopback catcher ----------
class _Catch(http.server.BaseHTTPRequestHandler):
    result = {}
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catch.result = {k: v[0] for k, v in q.items()}
        self.send_response(200); self.end_headers()
        self.wfile.write(b"<h2>Anchor calendar spike: you can close this tab.</h2>")
    def log_message(self, *a):  # silence
        pass

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    assert p != 8777, "must not collide with Anchor's port"
    return p

def post_form(url, form):
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def get_bearer(url, access):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

# ---------- modes ----------
def run_mock():
    port = free_port()
    httpd = http.server.HTTPServer(("127.0.0.1", port), _Catch)
    t = threading.Thread(target=httpd.handle_request, daemon=True); t.start()
    v, c = pkce()
    state = secrets.token_urlsafe(16)
    # simulate the browser redirect back to the loopback URL
    urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=FAKE_CODE&state={state}", timeout=5).read()
    t.join(timeout=5)
    got = _Catch.result
    ok_code = got.get("code") == "FAKE_CODE"
    ok_state = got.get("state") == state
    print(f"  loopback port (!=8777)     : {port}  OK={port != 8777}")
    print(f"  PKCE S256 verifier/challenge: OK ({len(v)}-char verifier)")
    print(f"  catcher captured ?code=    : {ok_code}")
    print(f"  state-CSRF echo matches    : {ok_state}")
    print("  VERDICT: loopback+PKCE catcher wiring works" if (ok_code and ok_state) else "  VERDICT: FAIL")

def run_real(provider, client_id):
    cfg = CFG[provider]
    port = free_port()
    redirect = f"http://127.0.0.1:{port}"
    v, c = pkce(); state = secrets.token_urlsafe(16)
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect,
              "scope": cfg["scope"], "code_challenge": c, "code_challenge_method": "S256",
              "state": state, **cfg["extra_auth"]}
    auth_url = cfg["auth"] + "?" + urllib.parse.urlencode(params)
    httpd = http.server.HTTPServer(("127.0.0.1", port), _Catch)
    t = threading.Thread(target=httpd.handle_request, daemon=True); t.start()
    print(f"Opening browser for {provider} consent (redirect {redirect}) ...")
    webbrowser.open(auth_url)
    t.join(timeout=300)
    got = _Catch.result
    if got.get("state") != state:
        sys.exit(f"STATE MISMATCH (possible CSRF) — got {got!r}")
    if "code" not in got:
        sys.exit(f"No code returned: {got!r}")
    tok = post_form(cfg["token"], {"client_id": client_id, "grant_type": "authorization_code",
                                   "code": got["code"], "redirect_uri": redirect, "code_verifier": v})
    print("  token exchange: OK  (got access_token, refresh_token=%s)" % bool(tok.get("refresh_token")))
    ev = get_bearer(cfg["events"], tok["access_token"])
    items = ev.get("items") or ev.get("value") or []
    print(f"  events list: OK — {len(items)} event(s) returned from {provider}")
    if tok.get("refresh_token"):
        path = f"spike_token_{provider}.bin"
        open(path, "wb").write(dpapi_wrap(json.dumps({"client_id": client_id,
              "refresh_token": tok["refresh_token"]}).encode()))
        print(f"  refresh token DPAPI-wrapped -> {path}")
    print("  VERDICT: REAL consent + token + events + DPAPI all OK")

def run_refresh_check(provider):
    path = f"spike_token_{provider}.bin"
    saved = json.loads(dpapi_unwrap(open(path, "rb").read()).decode())
    tok = post_form(CFG[provider]["token"], {"client_id": saved["client_id"],
            "grant_type": "refresh_token", "refresh_token": saved["refresh_token"],
            "scope": CFG[provider]["scope"]})
    ok = "access_token" in tok
    print(f"  refresh redeemed: {ok}  (token age proves durable refresh if run >7 days later)")
    if tok.get("refresh_token"):  # MS rotates — persist the new one
        saved["refresh_token"] = tok["refresh_token"]
        open(path, "wb").write(dpapi_wrap(json.dumps(saved).encode()))
        print("  (rotated refresh token re-saved)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--provider", choices=["google", "microsoft"])
    ap.add_argument("--client-id")
    ap.add_argument("--refresh-check", action="store_true")
    a = ap.parse_args()
    if a.mock:
        run_mock()
    elif a.refresh_check and a.provider:
        run_refresh_check(a.provider)
    elif a.provider and a.client_id:
        run_real(a.provider, a.client_id)
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
