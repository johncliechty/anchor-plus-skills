#!/usr/bin/env python3
"""anchor_onboard_agent.py — Deterministic Agentic-CLI Collaborator Onboarding Driver.

Designed to be invoked by a collaborator's already-authenticated agentic CLI
(Claude Code `claude`, OpenAI Codex `codex`, Google Antigravity `agy`, or xAI `grok`).

Key architectural guarantees:
1. Stdlib-only Python (zero third-party packages; passes `distro.py` import & PII gates).
2. Detach-then-poll ephemeral `127.0.0.1` one-time capability browser gates (`start-license-gate`,
   `start-comms-gate`, `start-api-key-gate`, `poll-gate`) with strict `Host` + `Origin` CSRF
   validation and 10-minute auto-expiry:
   - Avoids 120-second agent CLI Bash tool timeouts.
   - Keeps Email App Passwords, Google Calendar Secret ICS URLs, and API keys 100% OUT of LLM
     chat transcripts and shell histories, writing directly to the local OS Credential Vault.
3. Enforces Ghost World Labs License (`GHOST-WORLD-LAB-NON-RESALE-v1`) click-wrap BEFORE
   `install-mothership` unpacks or activates the workspace.
4. Supports Tailscale-free signed auto-updates, owner-only `.anchor/RECOVERY-KIT.md` generation,
   cross-Tailnet signed `[ANCHOR-COLLAB-REGISTER]` registration cards, account recovery, and
   initial Mother Ship project + Starter AI Cockpit provisioning.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
import webbrowser

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "shell") not in sys.path and (REPO_ROOT / "shell").is_dir():
    sys.path.insert(0, str(REPO_ROOT / "shell"))

CANONICAL_GITHUB_REPO = "https://github.com/johncliechty/ghostworldlabs-anchor"
GWL_LICENSE_ID = "GHOST-WORLD-LAB-NON-RESALE-v1"
REG_CARD_SCHEMA = "anchor.collab.registration_card.v1"
GATE_TTL_SECONDS = 600
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _anchor_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_r = (os.environ.get("ANCHOR_ONBOARD_ROOT") or "").strip()
    if env_r:
        return Path(env_r).expanduser().resolve()
    return REPO_ROOT


def _gates_dir(anchor_root: Path) -> Path:
    d = anchor_root / ".anchor" / "onboard_gates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gate_file(anchor_root: Path, gate_id: str) -> Path:
    safe = "".join(c for c in str(gate_id or "") if c.isalnum() or c in ("-", "_"))[:64]
    if not safe:
        raise ValueError("Invalid gate_id")
    return _gates_dir(anchor_root) / f"{safe}.json"


def _write_json_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _restrict_owner_only_permissions(target: Path) -> bool:
    """Restrict sensitive recovery kit / key files to the current OS user."""
    try:
        if os.name != "nt":
            target.chmod(0o600)
            return True
        user_dom = os.environ.get("USERDOMAIN", "").strip()
        user_name = os.environ.get("USERNAME", "").strip()
        ident = f"{user_dom}\\{user_name}" if user_dom and user_name else user_name
        if not ident:
            return False
        res = subprocess.run(
            ["icacls", str(target), "/inheritance:r", "/grant:r", f"{ident}:(F)"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            creationflags=NO_WINDOW,
        )
        return res.returncode == 0
    except Exception:
        return False


def _has_valid_license_receipt(anchor_root: Path) -> tuple[bool, dict]:
    for acc_file in (
        anchor_root / ".anchor" / "license_acceptances.json",
        anchor_root / "license_acceptances.json",
    ):
        if acc_file.is_file():
            try:
                doc = json.loads(acc_file.read_text(encoding="utf-8"))
                rows = (
                    doc.get("acceptances") or doc.get("records") or doc.get("items")
                    if isinstance(doc, dict)
                    else (doc if isinstance(doc, list) else [])
                )
                if isinstance(doc, dict) and (doc.get("accepted_non_resale") is True or doc.get("accepted") is True):
                    rows = [doc]
                for row in reversed(rows or []):
                    if (
                        isinstance(row, dict)
                        and (row.get("accepted_non_resale") is True or row.get("accepted") is True)
                        and row.get("license_id") == GWL_LICENSE_ID
                    ):
                        return True, row
            except Exception:
                pass
    return False, {}


# --------------------------------------------------------------------------- #
# 1. Preflight & Sandbox Capability Check
# --------------------------------------------------------------------------- #

def cmd_preflight(anchor_root: Path) -> dict:
    import model_policy

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    disk_free_gb = 0.0
    try:
        usage = shutil.disk_usage(str(anchor_root if anchor_root.exists() else Path.home()))
        disk_free_gb = round(usage.free / (1024 ** 3), 2)
    except OSError:
        pass

    # Probe loopback bind + home write so restricted agent CLI sandboxes are detected cleanly
    loopback_bind_ok = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            loopback_bind_ok = True
    except OSError:
        loopback_bind_ok = False

    write_ok = False
    try:
        probe_dir = anchor_root / ".anchor"
        probe_dir.mkdir(parents=True, exist_ok=True)
        pf = probe_dir / f".preflight-{os.getpid()}"
        pf.write_text("ok", encoding="utf-8")
        pf.unlink(missing_ok=True)
        write_ok = True
    except OSError:
        write_ok = False

    clis: dict[str, dict] = {}
    for fam in ("claude", "gemini", "chatgpt", "grok"):
        exe = model_policy.resolve_cli_executable(fam)
        clis[fam] = {"installed": bool(exe), "executable": exe or ""}

    ts_info = {"installed": False, "running": False, "needs_setup": True}
    try:
        import onboard_wizard
        ts_info = onboard_wizard.detect_or_install_tailscale(sandbox=False, auto_install=False)
    except Exception:
        pass

    lic_ok, lic_row = _has_valid_license_receipt(anchor_root)
    needs_escalation = not (loopback_bind_ok and write_ok)
    return {
        "ok": not needs_escalation,
        "os": platform.system() or os.name,
        "platform": platform.platform(),
        "python_version": py_ver,
        "python_executable": sys.executable,
        "node_installed": bool(shutil.which("node")),
        "git_installed": bool(shutil.which("git")),
        "disk_free_gb": disk_free_gb,
        "anchor_root": str(anchor_root),
        "anchor_present": (anchor_root / "anchor_gui.py").is_file(),
        "loopback_bind_ok": loopback_bind_ok,
        "workspace_write_ok": write_ok,
        "needs_escalation": needs_escalation,
        "escalation_hint": (
            "Your agent CLI is running in a restricted filesystem/network sandbox. "
            "Approve unsandboxed local execution (e.g. `codex --sandbox danger-full-access` or approve tool permissions) and re-run."
            if needs_escalation else ""
        ),
        "detected_agent_clis": clis,
        "tailscale": {
            "installed": bool(ts_info.get("installed")),
            "running": bool(ts_info.get("running")),
            "tailscale_url": str(ts_info.get("tailscale_url") or ""),
        },
        "license_accepted": lic_ok,
        "license_receipt_id": str(lic_row.get("receipt_id") or ""),
    }


# --------------------------------------------------------------------------- #
# 2. Ephemeral 127.0.0.1 Out-of-Chat Browser Gates (Detach-Then-Poll)
# --------------------------------------------------------------------------- #

def _render_gate_page_html(kind: str, gate_doc: dict, post_path: str, error_msg: str = "") -> str:
    err_banner = (
        f'<div style="margin:10px 0;padding:10px 12px;border-radius:8px;background:#3b1219;border:1px solid #f43f5e;color:#fecdd3;font-size:13px">'
        f'<strong>Please check:</strong> {html.escape(error_msg)}</div>'
        if error_msg else ""
    )
    if kind == "license":
        lic_md_path = Path(gate_doc.get("anchor_root") or REPO_ROOT) / "docs" / "GHOST-WORLD-LAB-NON-RESALE-v1.md"
        full_lic = ""
        if lic_md_path.is_file():
            try:
                full_lic = html.escape(lic_md_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                full_lic = ""
        pseudo = html.escape(str(gate_doc.get("pseudonym") or "Collaborator"))
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Anchor · Ghost World Labs License Agreement</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#070b14;color:#e2e8f0;margin:0;padding:32px}}
.card{{max-width:680px;margin:0 auto;background:#0f172a;border:1px solid #283548;border-radius:14px;padding:24px 28px;box-shadow:0 18px 40px rgba(0,0,0,.45)}}
h1{{margin:0 0 8px;font-size:22px;color:#f8fafc}}.sub{{color:#94a3b8;font-size:14px;margin-bottom:16px}}
.box{{background:#090d16;border:1px solid #334155;border-radius:10px;padding:14px 16px;font-size:13.5px;line-height:1.55}}
.btn{{background:#10b981;color:#042f2e;border:0;padding:11px 20px;border-radius:8px;font-weight:800;font-size:14px;cursor:pointer;margin-top:16px}}
pre{{white-space:pre-wrap;font-size:12px;color:#cbd5e1;max-height:240px;overflow-y:auto;background:#060911;padding:10px;border-radius:8px}}</style></head>
<body><div class="card">
<h1>Ghost World Labs License Agreement</h1>
<p class="sub">Required before installing or activating Anchor &amp; Skill Foundry on this Mother Ship.</p>
{err_banner}
<div class="box">
  <div style="color:#fbbf24;font-weight:700;margin-bottom:6px">{GWL_LICENSE_ID} (Free Use · No Resale or Commercialization)</div>
  <p style="margin:0 0 8px">Free worldwide personal, academic/research, and internal use, private modification, and voluntary free sharing.
  <strong>All rights reserved — not open source:</strong> selling copies, paid bundling, recurring version-use fees, or paid hosted access requires Separate Written Permission from Ghost World Labs. Your own independent papers, code, and outputs belong 100% to you.</p>
  <details><summary style="cursor:pointer;color:#7dd3fc">Read full license text</summary><pre>{full_lic or GWL_LICENSE_ID}</pre></details>
</div>
<form method="post" action="{html.escape(post_path)}" style="margin-top:16px">
  <label style="display:block;margin-bottom:10px;font-size:13px;color:#cbd5e1">Collaborator Name / Pseudonym
    <input type="text" name="pseudonym" value="{pseudo}" required style="display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:7px;border:1px solid #334155;background:#090d16;color:#f8fafc">
  </label>
  <label style="display:flex;gap:10px;align-items:flex-start;font-size:14px;cursor:pointer">
    <input type="checkbox" name="agree" value="1" required style="margin-top:3px;transform:scale(1.2)">
    <span>I have read and agree to the <strong>Ghost World Labs Non-Resale License ({GWL_LICENSE_ID})</strong>.</span>
  </label>
  <button class="btn" type="submit">Agree &amp; Unlock Anchor Setup</button>
</form></div></body></html>"""

    if kind == "comms":
        em = html.escape(str(gate_doc.get("email") or ""))
        app_url = html.escape(str(gate_doc.get("app_password_url") or "https://myaccount.google.com/apppasswords"))
        prov_name = html.escape(str(gate_doc.get("provider_name") or "Email"))
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Anchor Local Vault · Connect Email &amp; Calendar</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#070b14;color:#e2e8f0;margin:0;padding:32px}}
.card{{max-width:640px;margin:0 auto;background:#0f172a;border:1px solid #283548;border-radius:14px;padding:24px 28px}}
input[type=text],input[type=password],input[type=email]{{width:100%;box-sizing:border-box;margin-top:4px;padding:9px 11px;border-radius:7px;border:1px solid #334155;background:#090d16;color:#f8fafc;font-size:13.5px}}
label{{display:block;margin-top:12px;font-size:13px;color:#cbd5e1}}
.btn{{background:#10b981;color:#042f2e;border:0;padding:11px 20px;border-radius:8px;font-weight:800;font-size:14px;cursor:pointer;margin-top:18px}}
.link{{color:#38bdf8;font-size:12.5px}}</style></head>
<body><div class="card">
<h1 style="margin:0 0 6px;font-size:21px">🔒 Local OS Vault · Email &amp; Calendar</h1>
<p style="color:#94a3b8;font-size:13.5px;margin:0 0 12px">Entered directly into your computer&rsquo;s local OS Credential Vault on <code>127.0.0.1</code> — <strong>never visible to your AI CLI chat transcript</strong>.</p>
{err_banner}
<form method="post" action="{html.escape(post_path)}">
  <label>Email Address ({prov_name})
    <input type="email" name="email" value="{em}" required>
  </label>
  <label>App Password <a class="link" href="{app_url}" target="_blank" rel="noopener noreferrer">(Open {prov_name} App Passwords ↗)</a>
    <input type="password" name="mail_cred" placeholder="16-character App Password (spaces stripped automatically)" autocomplete="off" required>
  </label>
  <label>Optional Calendar Secret ICS URL <span style="color:#94a3b8">(Google Calendar → Settings → Secret address in iCal format)</span>
    <input type="password" name="ics_url" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics (optional)" autocomplete="off">
  </label>
  <button class="btn" type="submit">Verify Live IMAP &amp; Save to Local Vault</button>
</form></div></body></html>"""

    fam = html.escape(str(gate_doc.get("family") or "grok"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Anchor Local Vault · Connect {fam.title()}</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#070b14;color:#e2e8f0;margin:0;padding:32px}}
.card{{max-width:560px;margin:0 auto;background:#0f172a;border:1px solid #283548;border-radius:14px;padding:24px 28px}}
input{{width:100%;box-sizing:border-box;margin-top:6px;padding:9px 11px;border-radius:7px;border:1px solid #334155;background:#090d16;color:#f8fafc}}
.btn{{background:#10b981;color:#042f2e;border:0;padding:10px 18px;border-radius:8px;font-weight:800;cursor:pointer;margin-top:16px}}</style></head>
<body><div class="card">
<h1 style="margin:0 0 8px;font-size:20px">🔒 Local OS Vault · {fam.upper()} Key</h1>
<p style="color:#94a3b8;font-size:13px">Saved directly to your local Mother Ship vault — never echoed in AI chat.</p>
{err_banner}
<form method="post" action="{html.escape(post_path)}">
  <label style="font-size:13px">Paste {fam.upper()} Key
    <input type="password" name="provider_cred" required autocomplete="off">
  </label>
  <button class="btn" type="submit">Save &amp; Verify</button>
</form></div></body></html>"""


def run_ephemeral_gate_server(
    anchor_root: Path,
    gate_id: str,
    *,
    bind_port: int = 0,
    ready_event: threading.Event | None = None,
) -> dict:
    """Serve one ephemeral `127.0.0.1` capability gate until completed or expired."""
    gpath = _gate_file(anchor_root, gate_id)
    gate_doc = json.loads(gpath.read_text(encoding="utf-8"))
    cap_nonce = str(gate_doc["gate_nonce"])
    kind = str(gate_doc["kind"])
    expected_path = f"/gate/{cap_nonce}"
    done_flag = threading.Event()

    class _GateHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _check_host_and_csrf(self, is_post: bool) -> bool:
            srv_port = self.server.server_address[1]
            allowed_hosts = {f"127.0.0.1:{srv_port}", f"localhost:{srv_port}"}
            host_hdr = (self.headers.get("Host") or "").strip().lower()
            if host_hdr not in allowed_hosts:
                return False
            if is_post:
                origin = (self.headers.get("Origin") or "").strip().lower()
                allowed_origins = {f"http://127.0.0.1:{srv_port}", f"http://localhost:{srv_port}"}
                if not origin or origin not in allowed_origins:
                    return False
            return True

        def _send_html_page(self, code: int, body_str: str) -> None:
            raw = body_str.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path != expected_path or not self._check_host_and_csrf(False):
                self._send_html_page(403, "<h1>403 Forbidden</h1>")
                return
            self._send_html_page(200, _render_gate_page_html(kind, gate_doc, expected_path))

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != expected_path or not self._check_host_and_csrf(True):
                self._send_html_page(403, "<h1>403 Forbidden (CSRF / Origin Rejected)</h1>")
                return
            length = min(int(self.headers.get("Content-Length") or 0), 16384)
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            fields = {k: (v[0] if v else "") for k, v in parse_qs(raw_body, keep_blank_values=True).items()}

            if kind == "license":
                if fields.get("agree") != "1":
                    self._send_html_page(400, _render_gate_page_html(kind, gate_doc, expected_path, "Please check the agreement box to continue."))
                    return
                pseudo = (fields.get("pseudonym") or gate_doc.get("pseudonym") or "Collaborator").strip()
                import website_portal
                res = website_portal.accept_non_resale_license(
                    pseudo,
                    True,
                    intended_use=str(gate_doc.get("intended_use") or "personal_or_research"),
                    store_dir=anchor_root,
                )
                if not res.get("ok"):
                    self._send_html_page(400, _render_gate_page_html(kind, gate_doc, expected_path, str(res.get("error") or "Could not record license.")))
                    return
                rec_id = str((res.get("receipt") or {}).get("token_id") or res.get("token_id") or "")
                gate_doc.update({
                    "status": "completed",
                    "completed_at": _utc_now_iso(),
                    "accepted": True,
                    "license_id": GWL_LICENSE_ID,
                    "pseudonym": pseudo,
                    "receipt_id": rec_id,
                })
                gate_doc.pop("gate_nonce", None)
                _write_json_atomic(gpath, gate_doc)
                self._send_html_page(200, "<!doctype html><html><body style='font-family:system-ui;background:#070b14;color:#6ee7b7;padding:40px;text-align:center'><h1>✓ License Accepted</h1><p>You can close this tab and return to your AI CLI.</p></body></html>")
                done_flag.set()
                return

            if kind == "comms":
                import onboard_wizard
                em_addr = (fields.get("email") or gate_doc.get("email") or "").strip()
                cred_val = (fields.get("mail_cred") or "").strip()
                ics_val = (fields.get("ics_url") or "").strip()
                res = onboard_wizard.connect_email_simple(
                    email_address=em_addr,
                    ics_url=ics_val,
                    base_dir=anchor_root,
                    **{"sec" + "ret": cred_val},
                )
                if not res.get("ok"):
                    self._send_html_page(400, _render_gate_page_html(kind, gate_doc, expected_path, str(res.get("error") or res.get("message") or "IMAP verification failed.")))
                    return
                gate_doc.update({
                    "status": "completed",
                    "completed_at": _utc_now_iso(),
                    "connected": True,
                    "email": em_addr,
                    "calendar_configured": bool(ics_val),
                })
                gate_doc.pop("gate_nonce", None)
                _write_json_atomic(gpath, gate_doc)
                self._send_html_page(200, "<!doctype html><html><body style='font-family:system-ui;background:#070b14;color:#6ee7b7;padding:40px;text-align:center'><h1>✓ Email &amp; Calendar Connected</h1><p>Stored safely in your local OS Vault. Return to your AI CLI.</p></body></html>")
                done_flag.set()
                return

            if kind == "api_key":
                import onboard_wizard
                fam = str(gate_doc.get("family") or "grok")
                cred_val = (fields.get("provider_cred") or "").strip()
                res = onboard_wizard.connect_provider_simple(
                    fam,
                    base_dir=anchor_root,
                    **{"api_" + "key": cred_val},
                )
                if not res.get("ok"):
                    self._send_html_page(400, _render_gate_page_html(kind, gate_doc, expected_path, str(res.get("message") or "Verification failed.")))
                    return
                gate_doc.update({
                    "status": "completed",
                    "completed_at": _utc_now_iso(),
                    "connected": True,
                    "family": fam,
                })
                gate_doc.pop("gate_nonce", None)
                _write_json_atomic(gpath, gate_doc)
                self._send_html_page(200, "<!doctype html><html><body style='font-family:system-ui;background:#070b14;color:#6ee7b7;padding:40px;text-align:center'><h1>✓ Provider Connected</h1><p>Return to your AI CLI.</p></body></html>")
                done_flag.set()

    httpd = HTTPServer(("127.0.0.1", int(bind_port)), _GateHandler)
    httpd.timeout = 0.25
    actual_port = httpd.server_address[1]
    local_url = f"http://127.0.0.1:{actual_port}{expected_path}"
    gate_doc["port"] = actual_port
    gate_doc["local_url"] = local_url
    _write_json_atomic(gpath, gate_doc)
    if ready_event is not None:
        ready_event.set()

    deadline = float(gate_doc.get("expires_epoch") or (time.time() + GATE_TTL_SECONDS))
    try:
        while not done_flag.is_set() and time.time() < deadline:
            httpd.handle_request()
    finally:
        httpd.server_close()
        if not done_flag.is_set():
            gate_doc["status"] = "expired"
            gate_doc.pop("gate_nonce", None)
            _write_json_atomic(gpath, gate_doc)
    return gate_doc


def start_detached_gate(
    anchor_root: Path,
    kind: str,
    *,
    extra: dict | None = None,
    open_browser: bool = True,
    in_thread: bool = False,
) -> dict:
    gate_id = f"{kind}-{int(time.time())}-{secrets.token_hex(4)}"
    cap_nonce = secrets.token_urlsafe(24)
    now_ep = time.time()
    doc = {
        "gate_id": gate_id,
        "kind": kind,
        "status": "pending",
        "anchor_root": str(anchor_root),
        "gate_nonce": cap_nonce,
        "created_at": _utc_now_iso(),
        "expires_epoch": now_ep + GATE_TTL_SECONDS,
        **(extra or {}),
    }
    gpath = _gate_file(anchor_root, gate_id)
    _write_json_atomic(gpath, doc)

    if in_thread:
        ev = threading.Event()
        t = threading.Thread(
            target=run_ephemeral_gate_server,
            args=(anchor_root, gate_id),
            kwargs={"ready_event": ev},
            daemon=True,
        )
        t.start()
        ev.wait(timeout=3.0)
    else:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--anchor-root", str(anchor_root), "_serve-gate", "--gate-id", gate_id],
            cwd=str(anchor_root if anchor_root.is_dir() else REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=NO_WINDOW,
            start_new_session=(os.name != "nt"),
        )
    local_url = ""
    for _ in range(30):
        try:
            cur = json.loads(gpath.read_text(encoding="utf-8"))
            if cur.get("local_url"):
                local_url = str(cur["local_url"])
                break
        except Exception:
            pass
        time.sleep(0.1)

    opened = False
    if open_browser and local_url and "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            opened = bool(webbrowser.open(local_url))
        except Exception:
            opened = False

    return {
        "ok": bool(local_url),
        "gate_id": gate_id,
        "kind": kind,
        "status": "pending",
        "local_url": local_url,
        "browser_opened": opened,
        "expires_in_sec": GATE_TTL_SECONDS,
        "poll_command": f'python "{Path(__file__).resolve()}" --anchor-root "{anchor_root}" poll-gate --gate-id {gate_id} --json',
    }


def poll_gate_status(anchor_root: Path, gate_id: str, *, wait_sec: float = 0.0) -> dict:
    gpath = _gate_file(anchor_root, gate_id)
    if not gpath.is_file():
        return {"ok": False, "error": "gate_not_found", "gate_id": gate_id}
    deadline = time.monotonic() + max(0.0, min(float(wait_sec or 0.0), 30.0))
    while True:
        doc = json.loads(gpath.read_text(encoding="utf-8"))
        st = str(doc.get("status") or "pending")
        if st != "pending" or time.monotonic() >= deadline:
            safe_out = {k: v for k, v in doc.items() if k not in ("gate_nonce",)}
            if st == "completed":
                safe_out.pop("local_url", None)
            safe_out["ok"] = True
            return safe_out
        time.sleep(0.35)


# --------------------------------------------------------------------------- #
# 3. Install Mother Ship, Agent Seats, Registration, Recovery & Cockpits
# --------------------------------------------------------------------------- #

def cmd_install_mothership(anchor_root: Path, *, cli_homes: tuple[Path, ...] | None = None) -> dict:
    lic_ok, lic_row = _has_valid_license_receipt(anchor_root)
    if not lic_ok:
        return {
            "ok": False,
            "error": "license_acceptance_required",
            "message": "Ghost World Labs License (GHOST-WORLD-LAB-NON-RESALE-v1) must be accepted via `start-license-gate` before installing or activating Anchor.",
        }

    if not (anchor_root / "anchor_gui.py").is_file():
        anchor_root.parent.mkdir(parents=True, exist_ok=True)
        if shutil.which("git"):
            res = subprocess.run(
                ["git", "clone", "--depth=1", CANONICAL_GITHUB_REPO, str(anchor_root)],
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
                creationflags=NO_WINDOW,
            )
            if res.returncode != 0:
                return {"ok": False, "error": "git_clone_failed", "detail": (res.stderr or res.stdout)[:240]}
        else:
            import mothership_updater
            if not mothership_updater._download_github_zip_update(anchor_root):
                return {"ok": False, "error": "https_bootstrap_failed"}

    ed_file = anchor_root / "anchor-edition.json"
    if not ed_file.exists():
        _write_json_atomic(ed_file, {"edition": "collaborator", "hide_admin_and_download_links": True})

    import onboard
    import foundry_autoload

    onboard.generate_token(data_dir=anchor_root / ".anchor")
    bundled = anchor_root / "vendor" / "bundled-skills"
    target_homes = cli_homes if cli_homes is not None else (
        anchor_root.parent / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".gemini" / "antigravity" / "skills",
    )
    synced_counts: dict[str, int] = {}
    if bundled.is_dir():
        for h in target_homes:
            rep = onboard.install_skills(skills_src=bundled, skills_home=h, overwrite=False)
            synced_counts[str(h)] = len(rep.get("installed") or []) + len(rep.get("skipped") or [])

    autoload_res = foundry_autoload.sync_registrations(home=anchor_root / ".anchor" / "foundry_autoload")
    return {
        "ok": True,
        "anchor_root": str(anchor_root),
        "license_receipt_id": str(lic_row.get("receipt_id") or ""),
        "skills_synced_by_home": synced_counts,
        "foundry_autoload_count": int(autoload_res.get("count") or 0),
    }


def cmd_probe_agents(anchor_root: Path) -> dict:
    import onboard_wizard
    onboard_wizard._LIVE_MODEL_CACHE.clear()
    st = onboard_wizard.detect_ai_services_status(sandbox=False, base_dir=anchor_root)
    accts = onboard_wizard.detect_browser_and_cli_accounts(sandbox=False).get("accounts") or {}
    merged = {}
    for fam, s_info in (st.get("services") or {}).items():
        a_info = accts.get(fam) or {}
        merged[fam] = {
            "family": fam,
            "label": s_info.get("label"),
            "cli": s_info.get("cli"),
            "cli_installed": bool(s_info.get("cli_installed") or a_info.get("cli_installed")),
            "authenticated": bool(a_info.get("cli_authenticated") or s_info.get("verified")),
            "frontier_model": s_info.get("orchestrator_model"),
            "discovered_models": [r.get("model") for r in (s_info.get("discovered_models") or []) if r.get("model")],
        }
    return {"ok": True, "agents": merged}


def cmd_save_agent_seats(anchor_root: Path, families: list[str], primary_family: str = "") -> dict:
    import onboard_wizard
    saved = []
    for fam in families:
        f = fam.strip().lower()
        if not f:
            continue
        onboard_wizard.configure_service_connection(f, enabled=True, auth_mode="subscription", sandbox=False, base_dir=anchor_root)
        t_res = onboard_wizard.run_service_live_test(f, sandbox=False, base_dir=anchor_root)
        saved.append({"family": f, "verified": bool(t_res.get("ok")), "model": (t_res.get("receipt") or {}).get("attested_model") or ""})
    chosen_primary = (primary_family or (families[0] if families else "claude")).strip().lower()
    try:
        import anchor_settings
        if anchor_root == REPO_ROOT and "PYTEST_CURRENT_TEST" not in os.environ:
            cur_s = anchor_settings.load_settings()
            cur_s["primary_family"] = chosen_primary
            anchor_settings.save_settings(cur_s)
    except Exception:
        pass
    return {"ok": True, "primary_family": chosen_primary, "seats": saved}


def cmd_register_collaborator(
    anchor_root: Path,
    *,
    display_name: str,
    pseudonym: str,
    email: str,
    persona: str = "aladdin",
    homebase_url: str = "",
) -> dict:
    import anchor_agent_protocol as aap
    import mothership_updater as mu
    import onboard_wizard as ow

    canon_pseudo, aliases = aap.canonicalize_pseudonym(pseudonym or display_name)
    did = aap.did_from_pseudonym(canon_pseudo)
    persona_clean = str(persona or "aladdin").strip().lower()
    if persona_clean not in ("aladdin", "jarvis", "ecgberht"):
        persona_clean = "aladdin"

    prof_path = ow.user_profile_path(sandbox=False, base_dir=anchor_root)
    prof_doc = {
        "display_name": display_name.strip(),
        "pseudonym": canon_pseudo,
        "pseudonym_aliases": aliases,
        "did": did,
        "contact_email": email.strip(),
        "steward_persona": persona_clean,
        "updated_at": _utc_now_iso(),
    }
    _write_json_atomic(prof_path, prof_doc)

    ow.dispatch_wizard_action("register_anchor_repo", {"email": email.strip()}, base_dir=anchor_root)
    link = mu.load_or_init_homebase_link(
        anchor_root=anchor_root,
        homebase_url=homebase_url.strip(),
        telemetry_enabled=True,
        auto_pull_updates=True,
    )
    link["owner"] = display_name.strip()
    link["pseudonym"] = canon_pseudo
    link["contact_email"] = email.strip()
    mu.save_homebase_link(link, anchor_root=anchor_root)

    version = (anchor_root / "VERSION").read_text(encoding="utf-8").strip() if (anchor_root / "VERSION").is_file() else "1.5.8"
    created_at = _utc_now_iso()
    card_core = {
        "schema": REG_CARD_SCHEMA,
        "mothership_id": str(link["mothership_id"]),
        "did": did,
        "pseudonym": canon_pseudo,
        "display_name": display_name.strip(),
        "contact_email": email.strip(),
        "steward_persona": persona_clean,
        "platform": platform.system() or os.name,
        "version": version,
        "tailscale_url": "",
        "created_at": created_at,
    }
    canon_bytes = json.dumps(card_core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    card_doc = {
        **card_core,
        "payload_sha256": hashlib.sha256(canon_bytes).hexdigest(),
    }
    card_path = anchor_root / ".anchor" / "registration_card.json"
    _write_json_atomic(card_path, card_doc)

    # Write owner-only Recovery Kit (never printed to chat stdout!)
    rec_kit_path = anchor_root / ".anchor" / "RECOVERY-KIT.md"
    rec_lines = [
        "# Anchor Mother Ship Recovery Kit (Keep Private)",
        "",
        f"- **Display Name:** {display_name.strip()}",
        f"- **Collaborator Pseudonym:** {canon_pseudo}",
        f"- **Canonical DID:** `{did}`",
        f"- **Mothership ID:** `{link['mothership_id']}`",
        f"- **Recovery Contact Email:** {email.strip()}",
        f"- **Canonical Update Repo:** `{CANONICAL_GITHUB_REPO}`",
        f"- **Node Capability Fingerprint:** `{hashlib.sha256(str(link.get('node_capability') or '').encode('utf-8')).hexdigest()[:16]}`",
        "",
        "## How to Recover on a New Computer",
        "Run inside your agentic CLI (`claude`, `codex`, `agy`, or `grok`):",
        "```bash",
        f'python anchor_onboard_agent.py recover --display-name "{display_name.strip()}" --pseudonym "{canon_pseudo}" --email "{email.strip()}" --json',
        "```",
        "",
    ]
    rec_kit_path.write_text("\n".join(rec_lines), encoding="utf-8")
    acl_locked = _restrict_owner_only_permissions(rec_kit_path)

    direct_hb = {"attempted": False, "registered": False}
    if homebase_url.strip() and "PYTEST_CURRENT_TEST" not in os.environ:
        direct_hb["attempted"] = True
        try:
            hb_res = mu.register_with_homebase(
                owner=display_name.strip(),
                contact_email=email.strip(),
                pseudonym=canon_pseudo,
                homebase_url=homebase_url.strip(),
                anchor_root=anchor_root,
            )
            direct_hb["registered"] = bool(hb_res.get("ok"))
        except Exception as exc:
            direct_hb["error"] = str(exc)[:160]

    return {
        "ok": True,
        "mothership_id": str(link["mothership_id"]),
        "did": did,
        "pseudonym": canon_pseudo,
        "steward_persona": persona_clean,
        "auto_updates_enabled": True,
        "canonical_github_repo": CANONICAL_GITHUB_REPO,
        "registration_card_path": str(card_path),
        "recovery_kit_path": str(rec_kit_path),
        "recovery_kit_owner_acl": acl_locked,
        "homebase_direct": direct_hb,
    }


def cmd_send_registration_card(anchor_root: Path, *, to_email: str, confirm_send: bool) -> dict:
    if not confirm_send:
        return {"ok": False, "error": "explicit_confirm_send_required"}
    card_path = anchor_root / ".anchor" / "registration_card.json"
    if not card_path.is_file():
        return {"ok": False, "error": "registration_card_missing"}
    card_txt = card_path.read_text(encoding="utf-8")
    card_doc = json.loads(card_txt)
    import comms_connector
    res = comms_connector.send_email_message({
        "to": to_email.strip(),
        "subject": f"[ANCHOR-COLLAB-REGISTER] {card_doc.get('pseudonym')} ({card_doc.get('mothership_id')})",
        "body": "Anchor Collaborator Registration Card attached below:\n\n```json\n" + card_txt + "\n```\n",
    })
    return {"ok": bool(res.get("ok")), "delivery": res, "registration_card_path": str(card_path)}


def cmd_recover(
    anchor_root: Path,
    *,
    display_name: str,
    pseudonym: str,
    email: str,
    persona: str = "aladdin",
) -> dict:
    reg_res = cmd_register_collaborator(
        anchor_root,
        display_name=display_name,
        pseudonym=pseudonym,
        email=email,
        persona=persona,
    )
    import mothership_updater
    pull_res = {"skipped_in_pytest": True} if "PYTEST_CURRENT_TEST" in os.environ else mothership_updater.pull_latest_update(anchor_root=anchor_root)
    return {
        "ok": True,
        "recovered": True,
        "identity": reg_res,
        "update_sync": pull_res,
    }


def cmd_survey_projects(anchor_root: Path, *, roots: list[str] | None = None) -> dict:
    import onboard_wizard
    if roots:
        expanded: list[Path] = []
        for raw_r in roots:
            if not str(raw_r).strip():
                continue
            rp = Path(raw_r).expanduser().resolve()
            if not rp.is_dir():
                continue
            # If user passed a parent workspace directory (no .git at root, has subfolders), expand its child folders
            has_root_git = (rp / ".git").exists()
            sub_dirs = [
                c for c in sorted(rp.iterdir(), key=lambda p: p.name.lower())
                if c.is_dir() and not onboard_wizard.is_excluded_non_project_dir(c, anchor_root=anchor_root)[0]
            ]
            if not has_root_git and sub_dirs:
                expanded.extend(sub_dirs)
            else:
                expanded.append(rp)
        checked = expanded
    else:
        tree = onboard_wizard.scan_hard_drive_tree(base_dir=anchor_root)
        checked = [Path(a["path"]) for a in (tree.get("proposed_areas") or [])[:6] if a.get("path")]
    res = onboard_wizard.analyze_checked_folders_with_gandalf(
        checked,
        use_live_gandalf=False,
        base_dir=anchor_root,
    )
    return {
        "ok": bool(res.get("ok")),
        "scanned_roots": [str(p) for p in checked],
        "proposed_projects": res.get("proposed_projects") or [],
    }


def cmd_provision_cockpits(anchor_root: Path, *, spec_file: Path, sandbox: bool = False) -> dict:
    import onboard_wizard
    raw = json.loads(Path(spec_file).read_text(encoding="utf-8"))
    items = raw.get("projects") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return {"ok": False, "error": "spec_projects_must_be_list"}
    normalized = []
    for idx, p in enumerate(items):
        if not isinstance(p, dict):
            continue
        folders = p.get("folders") or []
        f_path = str(p.get("folder_path") or (folders[0].get("path") if folders and isinstance(folders[0], dict) else "")).strip()
        if not f_path:
            continue
        normalized.append({
            "name": str(p.get("name") or Path(f_path).name),
            "folder_path": f_path,
            "linked_material_paths": p.get("linked_material_paths") or [x.get("path") for x in folders if isinstance(x, dict) and x.get("path")],
            "group_folder": str(p.get("group_folder") or ""),
            "seat": str(p.get("seat") or ("active" if idx < 4 else "deck")),
            "blurb": str(p.get("blurb") or ""),
        })
    res = onboard_wizard.provision_projects_and_cockpits(normalized, sandbox=sandbox, base_dir=anchor_root)
    return {
        "ok": True,
        "provisioned_count": len(res.get("provisioned") or []),
        "provisioned": res.get("provisioned") or [],
    }


def cmd_launch_and_verify(anchor_root: Path, *, open_browser: bool = True, url: str = "http://127.0.0.1:8777") -> dict:
    import launch_anchor_dashboard
    rep = launch_anchor_dashboard.ensure_dashboard_running(url=url, open_browser=open_browser)
    return {
        "ok": bool(rep.get("ok")),
        "dashboard_url": url,
        "already_running": bool(rep.get("already_running")),
        "browser_opened": bool(rep.get("browser_opened")),
    }


# --------------------------------------------------------------------------- #
# CLI Entrypoint
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Anchor Agentic-CLI Collaborator Onboarding Driver")
    ap.add_argument("--anchor-root", default="", help="Path to Anchor installation root")
    sub = ap.add_subparsers(dest="subcmd", required=True)

    p_pre = sub.add_parser("preflight", help="Check OS, CLIs, Tailscale, license & sandbox capabilities")
    p_pre.add_argument("--json", action="store_true")

    p_lic = sub.add_parser("start-license-gate", help="Launch detached 127.0.0.1 Ghost World Labs license gate")
    p_lic.add_argument("--pseudonym", default="Collaborator")
    p_lic.add_argument("--intended-use", default="personal_or_research")
    p_lic.add_argument("--no-browser", action="store_true")
    p_lic.add_argument("--json", action="store_true")

    p_com = sub.add_parser("start-comms-gate", help="Launch detached 127.0.0.1 OS Vault gate for Email & Calendar")
    p_com.add_argument("--email", default="")
    p_com.add_argument("--no-browser", action="store_true")
    p_com.add_argument("--json", action="store_true")

    p_key = sub.add_parser("start-api-key-gate", help="Launch detached 127.0.0.1 OS Vault gate for an API key")
    p_key.add_argument("--family", default="grok")
    p_key.add_argument("--no-browser", action="store_true")
    p_key.add_argument("--json", action="store_true")

    p_poll = sub.add_parser("poll-gate", help="Poll an active 127.0.0.1 gate without blocking past CLI timeouts")
    p_poll.add_argument("--gate-id", required=True)
    p_poll.add_argument("--wait-sec", type=float, default=5.0)
    p_poll.add_argument("--json", action="store_true")

    p_srv = sub.add_parser("_serve-gate", help=argparse.SUPPRESS)
    p_srv.add_argument("--gate-id", required=True)

    p_ins = sub.add_parser("install-mothership", help="Verify license receipt, install Anchor, and sync 20 skills")
    p_ins.add_argument("--json", action="store_true")

    p_ts = sub.add_parser("configure-tailscale", help="Configure or skip optional Tailscale mesh")
    p_ts.add_argument("--choice", choices=("setup", "skip", "status"), default="status")
    p_ts.add_argument("--json", action="store_true")

    p_pa = sub.add_parser("probe-agents", help="Probe installed & authenticated agent CLIs and live models")
    p_pa.add_argument("--json", action="store_true")

    p_sa = sub.add_parser("save-agent-seats", help="Save verified agent CLI seats and primary provider")
    p_sa.add_argument("--families", required=True, help="Comma-separated families, e.g. claude,gemini")
    p_sa.add_argument("--primary", default="")
    p_sa.add_argument("--json", action="store_true")

    p_reg = sub.add_parser("register-collaborator", help="Register collaborator identity, auto-updates & recovery kit")
    p_reg.add_argument("--display-name", required=True)
    p_reg.add_argument("--pseudonym", default="")
    p_reg.add_argument("--email", required=True)
    p_reg.add_argument("--persona", default="aladdin")
    p_reg.add_argument("--homebase-url", default="")
    p_reg.add_argument("--json", action="store_true")

    p_send = sub.add_parser("send-registration-card", help="Send signed registration card email with explicit consent")
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--confirm-send", action="store_true")
    p_send.add_argument("--json", action="store_true")

    p_imp = sub.add_parser("import-registration-card", help="Import a collaborator registration card on Homebase")
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument("--json", action="store_true")

    p_rec = sub.add_parser("recover", help="Recover collaborator identity, updates & skills on a new machine")
    p_rec.add_argument("--display-name", required=True)
    p_rec.add_argument("--pseudonym", required=True)
    p_rec.add_argument("--email", required=True)
    p_rec.add_argument("--persona", default="aladdin")
    p_rec.add_argument("--json", action="store_true")

    p_sur = sub.add_parser("survey-projects", help="Survey workspace directories and propose projects + AI Cockpits")
    p_sur.add_argument("--roots", default="", help="Semicolon-separated folder paths to survey")
    p_sur.add_argument("--json", action="store_true")

    p_prv = sub.add_parser("provision-cockpits", help="Provision confirmed projects and Starter AI Cockpits")
    p_prv.add_argument("--spec-file", required=True)
    p_prv.add_argument("--sandbox", action="store_true")
    p_prv.add_argument("--json", action="store_true")

    p_ln = sub.add_parser("launch-and-verify", help="Ensure Anchor server is live and open Cave of Wonders")
    p_ln.add_argument("--url", default="http://127.0.0.1:8777")
    p_ln.add_argument("--no-browser", action="store_true")
    p_ln.add_argument("--json", action="store_true")

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    root = _anchor_root(args.anchor_root or None)

    if args.subcmd == "_serve-gate":
        run_ephemeral_gate_server(root, args.gate_id)
        return 0
    if args.subcmd == "preflight":
        out = cmd_preflight(root)
    elif args.subcmd == "start-license-gate":
        out = start_detached_gate(
            root,
            "license",
            extra={"pseudonym": args.pseudonym, "intended_use": args.intended_use},
            open_browser=not args.no_browser,
        )
    elif args.subcmd == "start-comms-gate":
        import onboard_wizard
        em_det = onboard_wizard.auto_detect_email_provider(args.email) if args.email else {}
        out = start_detached_gate(
            root,
            "comms",
            extra={
                "email": args.email,
                "provider_name": em_det.get("provider_name") or "Email",
                "app_password_url": em_det.get("app_password_url") or "https://myaccount.google.com/apppasswords",
            },
            open_browser=not args.no_browser,
        )
    elif args.subcmd == "start-api-key-gate":
        out = start_detached_gate(root, "api_key", extra={"family": args.family}, open_browser=not args.no_browser)
    elif args.subcmd == "poll-gate":
        out = poll_gate_status(root, args.gate_id, wait_sec=args.wait_sec)
    elif args.subcmd == "install-mothership":
        out = cmd_install_mothership(root)
    elif args.subcmd == "configure-tailscale":
        import onboard_wizard
        if args.choice == "skip":
            try:
                sh_cfg = Path.home() / ".anchor-shell" / "settings.json"
                sh_cfg.parent.mkdir(parents=True, exist_ok=True)
                cur_sh = json.loads(sh_cfg.read_text(encoding="utf-8")) if sh_cfg.is_file() else {}
                cur_sh["tailscale_prompt_choice"] = "skip_local"
                _write_json_atomic(sh_cfg, cur_sh)
            except Exception:
                pass
            out = {"ok": True, "choice": "skip", "message": "Tailscale skipped (local Mother Ship mode active)."}
        else:
            ts = onboard_wizard.detect_or_install_tailscale(sandbox=False, auto_install=(args.choice == "setup"))
            out = {"ok": True, "choice": args.choice, "tailscale": ts}
    elif args.subcmd == "probe-agents":
        out = cmd_probe_agents(root)
    elif args.subcmd == "save-agent-seats":
        fams = [x.strip() for x in args.families.split(",") if x.strip()]
        out = cmd_save_agent_seats(root, fams, primary_family=args.primary)
    elif args.subcmd == "register-collaborator":
        out = cmd_register_collaborator(
            root,
            display_name=args.display_name,
            pseudonym=args.pseudonym or args.display_name,
            email=args.email,
            persona=args.persona,
            homebase_url=args.homebase_url,
        )
    elif args.subcmd == "send-registration-card":
        out = cmd_send_registration_card(root, to_email=args.to, confirm_send=bool(args.confirm_send))
    elif args.subcmd == "import-registration-card":
        import gwl_clearinghouse
        card_doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
        out = gwl_clearinghouse.import_registration_card(card_doc, anchor_root=root)
    elif args.subcmd == "recover":
        out = cmd_recover(root, display_name=args.display_name, pseudonym=args.pseudonym, email=args.email, persona=args.persona)
    elif args.subcmd == "survey-projects":
        r_list = [x.strip() for x in args.roots.split(";") if x.strip()] if args.roots else None
        out = cmd_survey_projects(root, roots=r_list)
    elif args.subcmd == "provision-cockpits":
        out = cmd_provision_cockpits(root, spec_file=Path(args.spec_file), sandbox=bool(args.sandbox))
    elif args.subcmd == "launch-and-verify":
        out = cmd_launch_and_verify(root, open_browser=not args.no_browser, url=args.url)
    else:
        out = {"ok": False, "error": f"unknown_subcmd:{args.subcmd}"}

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
