"""Where the Anchor program finds Anchor (PLAN v1.2 D1, Skill Foundry/planning/anchor-every-device-2026-10-03).

The program is only a window; the service lives on the owner's mother ship. On that computer it uses the local
copy (127.0.0.1); anywhere else it uses the owner's saved address, kept in %LOCALAPPDATA%/anchor-shell/settings.json.
Only https:// is accepted for another machine. When the address does not answer, the window shows a plain page
saying so, with Retry and Change address - never a browser error.
"""
import html
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
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
function act(name,arg){show('Connecting\\u2026');try{pywebview.api[name](arg).then(function(r){if(r)show(r);}).catch(function(e){show('Error: '+((e&&e.message)||String(e)));});}catch(e){show('Error: '+((e&&e.message)||String(e)));}}
</script>"""


def _load_onboard_bootstrap():
    try:
        import onboard_bootstrap
        return onboard_bootstrap
    except ImportError:
        for cand in (Path(__file__).resolve().parent.parent, Path(sys.executable).resolve().parent.parent):
            if (cand / "onboard_bootstrap.py").is_file() and str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
        try:
            import onboard_bootstrap
            return onboard_bootstrap
        except ImportError:
            pass

    def _resolve_python_command(*, which_fn=None, **_kw):
        which = which_fn or shutil.which
        if which("py"):
            return {"ok": True, "command": "py -3", "argv_prefix": ["py", "-3"], "note": "py_launcher"}
        for name in ("python", "python3"):
            p = which(name)
            if p:
                return {"ok": True, "command": p, "argv_prefix": [p], "note": "path_" + name}
        return {"ok": False, "command": None, "argv_prefix": [], "note": "python_missing"}

    def _bootstrap_plan(*, which_fn=None, **_kw):
        which = which_fn or shutil.which
        resolved = _resolve_python_command(which_fn=which)
        if resolved["ok"]:
            return {"action": "run_onboard", "python": resolved, "winget": bool(which("winget")), "module": "share_onboard"}
        if which("winget"):
            return {"action": "install_python_then_run", "python": resolved, "winget": True, "winget_id": "Python.Python.3.12", "module": "share_onboard", "fix_link": "https://www.python.org/downloads/"}
        return {"action": "fail_manual", "python": resolved, "winget": False, "module": "share_onboard", "fix_link": "https://www.python.org/downloads/", "note": "Install Python 3.8+ then re-run onboard.cmd"}

    def _package_root_has_cold_start(root):
        r = Path(root)
        needed = ("onboard.cmd", "onboard.ps1", "share_onboard.py", "USER-ONBOARD.md")
        missing = [n for n in needed if not (r / n).is_file()]
        return {"ok": not missing, "root": str(r), "missing": missing, "has_launcher": (r / "launch_anchor_dashboard.py").is_file()}

    return SimpleNamespace(
        resolve_python_command=_resolve_python_command,
        bootstrap_plan=_bootstrap_plan,
        package_root_has_cold_start=_package_root_has_cold_start,
    )


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


def find_local_anchor_root(package_root=None, check_system_dirs=False):
    """Locate a local Anchor package containing launch_anchor_dashboard.py and anchor_gui.py."""
    candidates = []
    if package_root:
        p = Path(package_root)
        candidates.append(p)
        if check_system_dirs:
            candidates.append(p.parent)
    if check_system_dirs:
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([exe_dir, exe_dir.parent, exe_dir.parent.parent])
        except OSError:
            pass
        candidates.extend([
            Path(DEFAULT_INSTALL_ROOT) / "Anchor",
            Path(DEFAULT_INSTALL_ROOT) / "anchor-plus-skills",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "anchor-plus-skills",
        ])
    seen = set()
    for cand in candidates:
        try:
            rc = cand.resolve()
        except OSError:
            rc = cand
        key = str(rc).lower()
        if key in seen:
            continue
        seen.add(key)
        if (rc / "launch_anchor_dashboard.py").is_file() and (rc / "anchor_gui.py").is_file():
            return rc
    return None


def ensure_local_service_running(package_root=None, check_system_dirs=False, probe_fn=None):
    """Start the local Anchor server on port 8777 if a local package exists and port 8777 is down."""
    probe = probe_fn or reachable
    if probe(LOCAL):
        return {"ok": True, "started": False, "root": ""}
    root = find_local_anchor_root(package_root=package_root, check_system_dirs=check_system_dirs)
    if root is None:
        return {"ok": False, "started": False, "root": "", "message": "No local Anchor package found."}

    ws_home = Path(DEFAULT_INSTALL_ROOT) if Path(DEFAULT_INSTALL_ROOT).is_dir() else root.parent
    try:
        _sync_workspace_skills_and_governance(root, ws_home)
    except Exception:
        pass

    ob = _load_onboard_bootstrap()
    py_cmd = ob.resolve_python_command()
    if not py_cmd.get("ok"):
        return {"ok": False, "started": False, "root": str(root), "message": "Python 3.8+ is required to start the local Anchor server."}

    env = dict(os.environ)
    env.setdefault("ANCHOR_WORKSPACE_ROOT", str(ws_home))
    run_kwargs = {"cwd": str(root), "env": env, "capture_output": True, "text": True, "timeout": 45}
    if os.name == "nt":
        run_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    launcher = root / "launch_anchor_dashboard.py"
    try:
        subprocess.run(
            list(py_cmd["argv_prefix"]) + [str(launcher), "--no-browser", "--retries", "20"],
            **run_kwargs,
        )
    except Exception:
        pass

    for _ in range(10):
        if probe(LOCAL):
            return {"ok": True, "started": True, "root": str(root)}
        time.sleep(0.4)

    # Direct detached fallback if launch_anchor_dashboard exited early
    gui = root / "anchor_gui.py"
    if gui.is_file():
        popen_kwargs = {
            "cwd": str(root),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = 0x00000008 | 0x08000000 | 0x00000200
        try:
            subprocess.Popen(list(py_cmd["argv_prefix"]) + [str(gui), "--no-browser"], **popen_kwargs)
        except Exception:
            pass
        for _ in range(16):
            if probe(LOCAL):
                return {"ok": True, "started": True, "root": str(root)}
            time.sleep(0.5)

    return {"ok": bool(probe(LOCAL)), "started": True, "root": str(root)}


def installation_state(package_root, which_fn=None):
    # Reuse the existing bootstrap's decisions; the client-only executable
    # has no bundled server installer or authenticated distribution source.
    ob = _load_onboard_bootstrap()
    package = ob.package_root_has_cold_start(package_root)
    bootstrap = ob.bootstrap_plan(which_fn=which_fn)
    return {"package": package, "bootstrap": bootstrap, "ready": False,
            "prerequisite": "A trusted complete Anchor/Foundry distribution containing onboard.cmd, onboard.ps1 and share_onboard.py. The standalone Anchor.exe client cannot install a mother ship.",
            "resume": "Re-run the same package's onboard.cmd after interruption; existing onboarding owns rollback and refuse-to-clobber checks. No completed host choice is saved until Anchor is reachable."}


def select_mother_ship(data_dir, package_root, probe_fn=None, auto_bootstrap=False):
    probe = probe_fn or reachable
    if probe(LOCAL):
        save_address(data_dir, LOCAL)
        return {"ok": True, "address": LOCAL, "path": "/setup", "installed": False}
    if probe_fn is None:
        started = ensure_local_service_running(package_root, check_system_dirs=auto_bootstrap, probe_fn=probe)
        if started.get("ok") and probe(LOCAL):
            save_address(data_dir, LOCAL)
            return {"ok": True, "address": LOCAL, "path": "/setup", "installed": False}
        if auto_bootstrap:
            pulled = pull_and_install_mothership(workspace_dir=DEFAULT_INSTALL_ROOT)
            if pulled.get("ok") or pulled.get("onboard_ready"):
                ensure_local_service_running(pulled.get("target_dir") or package_root, check_system_dirs=True, probe_fn=probe)
            if probe(LOCAL):
                save_address(data_dir, LOCAL)
                return {"ok": True, "address": LOCAL, "path": "/setup", "installed": True}
    return {"ok": False, "installation": installation_state(package_root)}


DEFAULT_INSTALL_ROOT = r"C:\dev"


def installation_page(package_root, default_dir=DEFAULT_INSTALL_ROOT):
    state = installation_state(package_root)
    missing = ", ".join(state["package"]["missing"]) or "Trusted source and completed service installation"
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anchor host installation</title>%s</head><body>%s<main><div class="card">
<h1>Install your mother ship</h1><p>%s</p><p>Required package files: <code>%s</code>.</p>
<p>%s</p>
<label for="install-target-dir">Workspace &amp; Skills Folder (recommended: <code>C:\\dev</code>)</label>
<input id="install-target-dir" value="%s" spellcheck="false">
<p class="example" style="margin-bottom:12px">Pulls core Anchor into <code>&lt;folder&gt;\\Anchor</code> and Foundry skills into <code>&lt;folder&gt;\\skills</code>.</p>
<label for="github-repo">GitHub Mother Ship Repository</label>
<input id="github-repo" value="%s" spellcheck="false">
<div class="row"><button id="retry-host-setup" class="btn go" onclick="act('select_mother_ship')">Check installed mother ship</button>
<button id="install-from-github" class="btn" onclick="act('install_from_github',{repo_url:document.getElementById('github-repo').value,target_dir:document.getElementById('install-target-dir').value})">Pull &amp; install from GitHub</button>
<button class="btn" onclick="act('change_address')">Connect to an existing host instead</button></div><div class="msg" id="msg"></div></div></main>%s</body></html>""" % (
        _STYLE, _BAR, html.escape(state["prerequisite"]), html.escape(missing), html.escape(state["resume"]),
        html.escape(default_dir or DEFAULT_INSTALL_ROOT, quote=True), html.escape(DEFAULT_GITHUB_REPO, quote=True), _SCRIPT)


def _resolve_mothership_paths(target_dir=None, workspace_dir=None):
    """Return (dest_repo_dir, workspace_home_dir).

    When ``target_dir`` is explicitly supplied (e.g. direct path or unit tests),
    ``dest_repo_dir`` is ``Path(target_dir)``. When ``workspace_dir`` is supplied
    from the installer UI (default ``C:\\dev``), core Anchor code installs into
    ``<workspace_dir>\\Anchor`` while Foundry skills and governance install under
    ``<workspace_dir>\\skills`` and ``<workspace_dir>\\governance``.
    """
    if target_dir is not None:
        dest = Path(target_dir).expanduser()
        if workspace_dir:
            ws_home = Path(workspace_dir).expanduser()
        elif dest.name.lower() in ("anchor", "anchor-mothership"):
            ws_home = dest.parent
        else:
            ws_home = dest
        return dest, ws_home

    raw_ws = (workspace_dir or DEFAULT_INSTALL_ROOT).strip() or DEFAULT_INSTALL_ROOT
    ws = Path(raw_ws).expanduser()
    if ws.name.lower() in ("anchor", "anchor-mothership") or (ws / "anchor_gui.py").is_file():
        return ws, ws.parent
    return ws / "Anchor", ws


def pull_and_install_mothership(target_dir=None, repo_url=DEFAULT_GITHUB_REPO, run_onboard=True, runner_fn=None, workspace_dir=None):
    """Clone or update the clean Anchor+Skills mother-ship repository from GitHub and optionally run onboard.cmd."""
    onboard_bootstrap = _load_onboard_bootstrap()
    url = (repo_url or DEFAULT_GITHUB_REPO).strip()
    if not url.startswith("https://github.com/"):
        return {
            "ok": False,
            "target_dir": str(target_dir or workspace_dir or ""),
            "repo_url": url,
            "onboard_ready": False,
            "message": "Only https://github.com/ repositories are supported for mother-ship installation.",
        }
    dest, ws_home = _resolve_mothership_paths(target_dir=target_dir, workspace_dir=workspace_dir)
    run = runner_fn or (lambda cmd, cwd=None: subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=240))
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
                "workspace_dir": str(ws_home),
                "repo_url": used_url,
                "onboard_ready": False,
                "message": "GitHub pull failed: %s" % err[:240],
            }
    except Exception as exc:
        return {
            "ok": False,
            "target_dir": str(dest),
            "workspace_dir": str(ws_home),
            "repo_url": used_url,
            "onboard_ready": False,
            "message": "Could not run git: %s" % exc,
        }

    pkg = onboard_bootstrap.package_root_has_cold_start(dest)
    if not pkg.get("ok"):
        return {
            "ok": False,
            "target_dir": str(dest),
            "workspace_dir": str(ws_home),
            "repo_url": used_url,
            "onboard_ready": False,
            "message": "Repository cloned to %s, but missing cold-start files: %s" % (dest, ", ".join(pkg.get("missing") or [])),
        }

    installed_skills = _sync_workspace_skills_and_governance(dest, ws_home)

    if run_onboard:
        onboard_cmd = dest / "onboard.cmd"
        try:
            if runner_fn is not None:
                ob_res = run(["cmd.exe", "/c", str(onboard_cmd)], cwd=str(dest))
            else:
                env = dict(os.environ)
                env.setdefault("ANCHOR_SHARE_LIVE_PROBES", "1")
                env.setdefault("ANCHOR_WORKSPACE_ROOT", str(ws_home))
                ob_res = subprocess.run(
                    ["cmd.exe", "/c", str(onboard_cmd), "--home", str(ws_home), "--package", "B", "--yes"],
                    cwd=str(dest),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                # Ensure the local Mother Ship service on :8777 is started even when
                # CLI provider subscriptions have not been signed in yet (Stage 2 of /setup).
                launcher = dest / "launch_anchor_dashboard.py"
                if launcher.is_file() and not reachable(LOCAL, timeout=1.5):
                    py_cmd = onboard_bootstrap.resolve_python_command()
                    if py_cmd.get("ok"):
                        subprocess.run(
                            list(py_cmd["argv_prefix"]) + [str(launcher), "--no-browser", "--home", str(ws_home)],
                            cwd=str(dest),
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=45,
                        )
            if getattr(ob_res, "returncode", 1) != 0 and (runner_fn is not None or not reachable(LOCAL, timeout=2.0)):
                return {
                    "ok": False,
                    "target_dir": str(dest),
                    "workspace_dir": str(ws_home),
                    "installed_skills": installed_skills,
                    "repo_url": used_url,
                    "onboard_ready": True,
                    "message": "Pulled mother ship to %s (skills home %s). Complete setup by running %s." % (dest, ws_home, onboard_cmd),
                }
        except Exception as exc:
            return {
                "ok": False,
                "target_dir": str(dest),
                "workspace_dir": str(ws_home),
                "installed_skills": installed_skills,
                "repo_url": used_url,
                "onboard_ready": True,
                "message": "Pulled mother ship to %s (%s). Run onboard.cmd to finish." % (dest, exc),
            }

    return {
        "ok": True,
        "target_dir": str(dest),
        "workspace_dir": str(ws_home),
        "installed_skills": installed_skills,
        "repo_url": used_url,
        "onboard_ready": True,
        "message": "Mother ship pulled from %s into %s (workspace & skills: %s)." % (used_url, dest, ws_home),
    }


def _sync_workspace_skills_and_governance(dest: Path, ws_home: Path) -> list[str]:
    """Ensure bundled Foundry skills and governance pack are present under ``ws_home``."""
    installed = []
    src_skills = None
    for cand in (dest / "vendor" / "bundled-skills", dest / "bundled-skills", dest / "skills"):
        if cand.is_dir():
            src_skills = cand
            break
    dst_skills = ws_home / "skills"
    if src_skills is not None and src_skills.resolve() != dst_skills.resolve():
        dst_skills.mkdir(parents=True, exist_ok=True)
        for child in sorted(src_skills.iterdir()):
            if child.name.startswith(".") or child.name == "SOURCES.md" or not child.is_dir():
                continue
            target = dst_skills / child.name
            if not target.exists():
                shutil.copytree(child, target)
                (target / ".anchor-onboard-installed").write_text(
                    "Installed by Anchor onboard.py. Safe to delete to force a reinstall.\n",
                    encoding="utf-8",
                )
            installed.append(child.name)
        sources_md = src_skills / "SOURCES.md"
        if sources_md.is_file() and not (dst_skills / "SOURCES.md").exists():
            shutil.copy2(sources_md, dst_skills / "SOURCES.md")
    elif dst_skills.is_dir():
        installed = [
            c.name for c in sorted(dst_skills.iterdir())
            if c.is_dir() and not c.name.startswith(".")
        ]

    src_gov = dest / "governance"
    dst_gov = ws_home / "governance"
    if src_gov.is_dir() and src_gov.resolve() != dst_gov.resolve():
        dst_gov.mkdir(parents=True, exist_ok=True)
        for gfile in src_gov.iterdir():
            if gfile.is_file() and not (dst_gov / gfile.name).exists():
                shutil.copy2(gfile, dst_gov / gfile.name)
    return installed


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
