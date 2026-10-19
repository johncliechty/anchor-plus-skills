"""Where the Anchor program finds Anchor (PLAN v1.2 D1, Skill Foundry/planning/anchor-every-device-2026-10-03).

The program is only a window; the service lives on the owner's mother ship. On that computer it uses the local
copy (127.0.0.1); anywhere else it uses the owner's saved address, kept in %LOCALAPPDATA%/anchor-shell/settings.json.
Only https:// is accepted for another machine. When the address does not answer, the window shows a plain page
saying so, with Retry and Change address - never a browser error.
"""
import html
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

LOCAL = "http://127.0.0.1:8777"
EXAMPLE = "https://mother-ship.example"
APP_PATH = "/static/app.html"
DEFAULT_GITHUB_REPO = "https://github.com/johncliechty/ghostworldlabs-anchor.git"
FALLBACK_GITHUB_REPO = "https://github.com/johncliechty/anchor-plus-skills.git"


def settings_file(data_dir):
    return Path(data_dir) / "settings.json"


def load_address(data_dir):
    try:
        return json.loads(settings_file(data_dir).read_text(encoding="utf-8")).get("address") or ""
    except (OSError, ValueError):
        return ""


def save_address(data_dir, address):
    f = settings_file(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current["address"] = address
    f.write_text(json.dumps(current, indent=2), encoding="utf-8")


def normalize(text):
    """The typed address -> 'https://host[:port]', or (None, why). Only this device may use http."""
    t = (text or "").strip()
    if not t:
        return None, "Type your mother ship's address."
    if "://" not in t:
        t = "https://" + t
    try:
        parts = urlsplit(t)
        port = parts.port
    except ValueError:
        return None, "That address is invalid."
    if parts.username is not None or parts.password is not None:
        return None, "Use the mother ship HTTPS address without embedded credentials."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None, "That doesn't look like an address. Example only: " + EXAMPLE
    if parts.hostname.rstrip(".") == urlsplit(EXAMPLE).hostname:
        return None, "That is only an example. Type your own mother ship's address."
    local = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme == "http" and not local:
        return None, "Anchor on another machine must be reached over https (Tailscale Serve), not http."
    return "%s://%s" % (parts.scheme, parts.netloc), None


def reachable(address, timeout=5.0):
    """True when the address answers with Anchor's app page."""
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(address + APP_PATH, timeout=timeout, context=ctx) as r:
            return r.status == 200 and b"ANCHOR" in r.read(4096).upper()
    except (urllib.error.URLError, OSError, ValueError, ssl.SSLError):
        return False


def choose(data_dir, override=""):
    """The address to open now: an explicit one, local Anchor, else the saved one ('' = ask for an address)."""
    if override:
        address, error = normalize(override)
        if error:
            raise ValueError("Invalid --url: " + error)
        return address
    # First launch must choose this host or its existing mother ship before
    # provider work. A returning client must never drift to a local service.
    return load_address(data_dir)


# ---------- the two pages the program shows itself (no service needed) ----------
_STYLE = """<style>
:root{color-scheme:dark}*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:#0f141c;color:#e6ebf2;font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;display:grid;grid-template-rows:44px 1fr}
#bar{display:flex;align-items:center;gap:10px;padding-left:12px;background:#0b1018;border-bottom:1px solid #2b3546;-webkit-app-region:drag;app-region:drag}
#bar b{font-weight:600;font-size:13px;color:#98a4b8}#bar .sp{flex:1}
#bar button{-webkit-app-region:no-drag;app-region:no-drag;background:none;border:0;color:#98a4b8;width:46px;align-self:stretch;cursor:pointer;font-size:14px}
#bar button:hover{background:#1f2735;color:#e6ebf2}#bar button.c:hover{background:#c42b1c;color:#fff}
main{display:grid;place-items:center;padding:24px;min-width:0}.card{width:min(520px,100%);min-width:0;background:#161d29;border:1px solid #2b3546;border-radius:12px;padding:26px 28px}
h1{font-size:20px;margin:0 0 6px}p{color:#98a4b8;margin:0 0 16px}
label{display:block;margin-bottom:6px}.example{font-size:13px;margin:8px 0 0}
input{width:100%;font:15px "Segoe UI",system-ui;padding:9px 11px;border-radius:8px;border:1px solid #3a4658;background:#0f141c;color:#e6ebf2}
input:focus{outline:2px solid #e0a836;outline-offset:1px}
.row{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.btn{font:600 14px "Segoe UI",system-ui;padding:8px 16px;border-radius:8px;border:1px solid #3a4658;background:#1e2634;color:#e6ebf2;cursor:pointer}
.btn.go{background:#e0a836;border-color:#e0a836;color:#1a1a1a}.msg{min-height:22px;margin-top:12px;color:#e0a836;font-size:14px}
code{font:13px Consolas,monospace;color:#e9d9a8;overflow-wrap:anywhere}
.msg{overflow-wrap:anywhere}
</style>"""

_BAR = """<div id="bar"><b>Anchor</b><span class="sp"></span>
<button onclick="pywebview.api.window_control('minimize')" title="Minimize">&#8212;</button>
<button onclick="pywebview.api.window_control('maximize')" title="Maximize">&#9744;</button>
<button class="c" onclick="pywebview.api.window_control('close')" title="Close">&#10005;</button></div>"""

_SCRIPT = """<script>
function show(t){document.getElementById('msg').textContent=t||'';}
function act(name,arg){show('Connecting\\u2026');pywebview.api[name](arg).then(function(r){if(r)show(r);});}
</script>"""


def setup_page(prefill="", message=""):
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Anchor</title>%s</head><body>%s<main><div class="card">
<h1>Where is your Anchor?</h1>
<p>Enter the address of your own mother ship, the computer that runs Anchor for you. From another device, use its HTTPS address. Anchor remembers it after you connect.</p>
<label for="addr">Mother ship address</label>
<input id="addr" value="%s" aria-describedby="address-example" spellcheck="false" autofocus onkeydown="if(event.key==='Enter')act('connect',this.value)">
<p class="example" id="address-example">Example only: <code>%s</code>. Use your own address.</p>
<div class="row"><button class="btn go" onclick="act('connect',document.getElementById('addr').value)">Connect</button>
<button id="discover-tailscale" class="btn" onclick="act('discover_tailscale')">Find Tailscale mother ship</button></div>
<div class="msg" id="msg">%s</div></div></main>%s</body></html>""" % (
        _STYLE, _BAR, html.escape(prefill or "", quote=True), html.escape(EXAMPLE), html.escape(message), _SCRIPT)


def offline_page(address):
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Anchor</title>%s</head><body>%s<main><div class="card">
<h1>Anchor isn't reachable right now</h1>
<p>This computer can't reach your selected mother ship at <code>%s</code>. Check that Tailscale is on here, and that your mother ship is awake and Anchor is running there.</p>
<div class="row"><button class="btn go" onclick="act('retry')">Retry</button>
<button class="btn" onclick="act('change_address')">Change address</button></div>
<div class="msg" id="msg"></div></div></main>%s</body></html>""" % (_STYLE, _BAR, html.escape(address), _SCRIPT)


def first_launch_page():
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anchor setup</title>%s</head><body>%s<main><div class="card">
<h1>Choose your mother ship first</h1>
<p>Your mother ship keeps your provider accounts and runs your work. A connected computer uses those same accounts.</p>
<div class="row"><button id="choose-mother-ship" class="btn go" onclick="act('select_mother_ship')">This computer is my mother ship</button>
<button id="choose-existing-host" class="btn" onclick="act('change_address')">Connect to my existing mother ship</button></div>
<p class="example">An existing host connects through its secure Tailscale HTTPS address and Anchor pairing. Provider credentials stay there.</p>
<div class="msg" id="msg"></div></div></main>%s</body></html>""" % (_STYLE, _BAR, _SCRIPT)


def installation_state(package_root, which_fn=None):
    # Reuse the existing bootstrap's decisions; the client-only executable
    # has no bundled server installer or authenticated distribution source.
    import onboard_bootstrap
    package = onboard_bootstrap.package_root_has_cold_start(package_root)
    bootstrap = onboard_bootstrap.bootstrap_plan(which_fn=which_fn)
    return {"package": package, "bootstrap": bootstrap, "ready": False,
            "prerequisite": "A trusted complete Anchor/Foundry distribution containing onboard.cmd, onboard.ps1 and share_onboard.py. The standalone Anchor.exe client cannot install a mother ship.",
            "resume": "Re-run the same package's onboard.cmd after interruption; existing onboarding owns rollback and refuse-to-clobber checks. No completed host choice is saved until Anchor is reachable."}


def select_mother_ship(data_dir, package_root, probe_fn=None):
    probe = probe_fn or reachable
    if probe(LOCAL):
        save_address(data_dir, LOCAL)
        return {"ok": True, "address": LOCAL, "path": "/setup", "installed": False}
    return {"ok": False, "installation": installation_state(package_root)}


def installation_page(package_root):
    state = installation_state(package_root)
    missing = ", ".join(state["package"]["missing"]) or "Trusted source and completed service installation"
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anchor host installation</title>%s</head><body>%s<main><div class="card">
<h1>Install your mother ship</h1><p>%s</p><p>Required package files: <code>%s</code>.</p>
<p>%s</p>
<label for="github-repo">GitHub Mother Ship Repository</label>
<input id="github-repo" value="%s" spellcheck="false">
<div class="row"><button id="retry-host-setup" class="btn go" onclick="act('select_mother_ship')">Check installed mother ship</button>
<button id="install-from-github" class="btn" onclick="act('install_from_github',document.getElementById('github-repo').value)">Pull &amp; install from GitHub</button>
<button class="btn" onclick="act('change_address')">Connect to an existing host instead</button></div><div class="msg" id="msg"></div></div></main>%s</body></html>""" % (
        _STYLE, _BAR, html.escape(state["prerequisite"]), html.escape(missing), html.escape(state["resume"]), html.escape(DEFAULT_GITHUB_REPO, quote=True), _SCRIPT)


def pull_and_install_mothership(target_dir=None, repo_url=DEFAULT_GITHUB_REPO, run_onboard=True, runner_fn=None):
    """Clone or update the clean Anchor+Skills mother-ship repository from GitHub and optionally run onboard.cmd."""
    import onboard_bootstrap
    url = (repo_url or DEFAULT_GITHUB_REPO).strip()
    if not url.startswith("https://github.com/"):
        return {
            "ok": False,
            "target_dir": str(target_dir or ""),
            "repo_url": url,
            "onboard_ready": False,
            "message": "Only https://github.com/ repositories are supported for mother-ship installation.",
        }
    dest = Path(target_dir) if target_dir else (Path.home() / "Anchor-Mothership")
    run = runner_fn or (lambda cmd, cwd=None: subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180))
    used_url = url
    try:
        if (dest / ".git").is_dir():
            res = run(["git", "-C", str(dest), "pull", "--ff-only"], cwd=str(dest))
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            res = run(["git", "clone", used_url, str(dest)], cwd=str(dest.parent))
            if getattr(res, "returncode", 1) != 0 and used_url == DEFAULT_GITHUB_REPO:
                used_url = FALLBACK_GITHUB_REPO
                res = run(["git", "clone", used_url, str(dest)], cwd=str(dest.parent))
        if getattr(res, "returncode", 1) != 0:
            err = (getattr(res, "stderr", "") or getattr(res, "stdout", "") or "git clone/pull failed").strip()
            return {
                "ok": False,
                "target_dir": str(dest),
                "repo_url": used_url,
                "onboard_ready": False,
                "message": "GitHub pull failed: %s" % err[:240],
            }
    except Exception as exc:
        return {
            "ok": False,
            "target_dir": str(dest),
            "repo_url": used_url,
            "onboard_ready": False,
            "message": "Could not run git: %s" % exc,
        }

    pkg = onboard_bootstrap.package_root_has_cold_start(dest)
    if not pkg.get("ok"):
        return {
            "ok": False,
            "target_dir": str(dest),
            "repo_url": used_url,
            "onboard_ready": False,
            "message": "Repository cloned to %s, but missing cold-start files: %s" % (dest, ", ".join(pkg.get("missing") or [])),
        }

    if run_onboard:
        onboard_cmd = dest / "onboard.cmd"
        try:
            ob_res = run(["cmd.exe", "/c", str(onboard_cmd)], cwd=str(dest))
            if getattr(ob_res, "returncode", 1) != 0:
                return {
                    "ok": False,
                    "target_dir": str(dest),
                    "repo_url": used_url,
                    "onboard_ready": True,
                    "message": "Pulled mother ship to %s. Complete setup by running %s." % (dest, onboard_cmd),
                }
        except Exception as exc:
            return {
                "ok": False,
                "target_dir": str(dest),
                "repo_url": used_url,
                "onboard_ready": True,
                "message": "Pulled mother ship to %s (%s). Run onboard.cmd to finish." % (dest, exc),
            }

    return {
        "ok": True,
        "target_dir": str(dest),
        "repo_url": used_url,
        "onboard_ready": True,
        "message": "Mother ship pulled from %s into %s." % (used_url, dest),
    }


def discover_tailscale_motherships(runner_fn=None):
    """Query local Tailscale status for online peer machines that may host an Anchor mother ship over HTTPS."""
    run = runner_fn or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=10))
    try:
        res = run(["tailscale", "status", "--json"])
        if getattr(res, "returncode", 1) != 0:
            return {
                "ok": False,
                "backend_state": "Unavailable",
                "self_dns": "",
                "peers": [],
                "message": "Tailscale is not running or not installed. Start Tailscale to connect to a remote mother ship.",
            }
        payload = json.loads(getattr(res, "stdout", "") or "{}")
    except Exception as exc:
        return {
            "ok": False,
            "backend_state": "Error",
            "self_dns": "",
            "peers": [],
            "message": "Could not query Tailscale (%s). Ensure Tailscale is installed and signed in." % exc,
        }

    backend_state = str(payload.get("BackendState") or "Unknown")
    self_node = payload.get("Self") or {}
    self_dns = str(self_node.get("DNSName") or "").rstrip(".")
    peers_map = payload.get("Peer") or {}
    peers = []
    for _key, peer in peers_map.items():
        if not isinstance(peer, dict):
            continue
        dns = str(peer.get("DNSName") or "").rstrip(".")
        host = str(peer.get("HostName") or "").strip()
        online = bool(peer.get("Online", False))
        if dns:
            peers.append({
                "hostname": host or dns.split(".")[0],
                "dns_name": dns,
                "https_url": "https://%s" % dns,
                "online": online,
            })
    peers.sort(key=lambda p: (not p["online"], p["hostname"].lower()))
    if backend_state != "Running":
        msg = "Tailscale state is '%s'. Sign in to Tailscale first." % backend_state
        return {"ok": False, "backend_state": backend_state, "self_dns": self_dns, "peers": peers, "message": msg}
    online_peers = [p for p in peers if p["online"]]
    if online_peers:
        msg = "Found %d online Tailscale peer(s): %s" % (
            len(online_peers),
            ", ".join(p["https_url"] for p in online_peers[:4]),
        )
    elif self_dns:
        msg = "Tailscale is running (%s), no other online peers found." % ("https://" + self_dns)
    else:
        msg = "Tailscale is running, but no peers with MagicDNS names were found."
    return {
        "ok": True,
        "backend_state": backend_state,
        "self_dns": self_dns,
        "peers": peers,
        "message": msg,
    }
