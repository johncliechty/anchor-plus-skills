"""Tidy-Idy thin caller for Anchor.

Dispatches the tool's own entry point (``bin/tidy-idy.mjs``) via
:func:`job_runner.launch_guarded` and surfaces a **status page URL** immediately,
then the Triage Panel URL when the scan finishes.

Second click: if a run is already live for the project folder, return its
status/panel URLs instead of starting a second pass (tool lock is the authority).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import job_runner

#: Env override for the tidy-idy CLI entry (absolute path to tidy-idy.mjs).
ENTRY_ENV = "ANCHOR_TIDY_IDY_ENTRY"

#: Well-known locations: an env-declared Skill Foundry checkout first (has the
#: status page), then the user-skill copy. No hardcoded author-machine paths —
#: a host without the skill resolves None and the runner degrades honestly
#: (v1.1.3 share-fix: the old literal worktree path tripped the ship scan).
def _default_candidates():
    cands = []
    foundry = (os.environ.get("ANCHOR_FOUNDRY_DIR") or "").strip()
    if foundry:
        cands.append(Path(foundry) / "skills" / "tidy-idy" / "bin" / "tidy-idy.mjs")
    cands.append(
        Path.home() / ".claude" / "skills" / "tidy-idy" / "bin" / "tidy-idy.mjs")
    return tuple(cands)


_DEFAULT_CANDIDATES = _default_candidates()

BUILD_LANE = "build"
TIDY_JOB_TYPE = "tidy"
PANEL_READY_EVENT = "panel-ready"
STATUS_READY_EVENT = "status-ready"
ALREADY_RUNNING_EVENT = "already-running"


def resolve_entry() -> Path | None:
    """Return the path to ``tidy-idy.mjs``, or None if not installed."""
    env = (os.environ.get(ENTRY_ENV) or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in _DEFAULT_CANDIDATES:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def build_command(root_path: str | Path, *, entry: Path | None = None,
                  nonce_file: str | Path | None = None,
                  node: str | None = None) -> list[str]:
    """Argv for job_runner's ``command=`` seam (verbatim local code, no model)."""
    entry = entry or resolve_entry()
    if entry is None:
        raise FileNotFoundError(
            f"tidy-idy entry not found; set {ENTRY_ENV} to bin/tidy-idy.mjs "
            "or install the skill under Skill Foundry / the tidy-idy worktree"
        )
    root = str(Path(root_path).resolve())
    cmd = [
        node or "node",
        str(entry),
        root,
        "--environment=anchor",
        "--json",
    ]
    if nonce_file:
        cmd.append(f"--nonce-file={Path(nonce_file)}")
    return cmd


def read_project_status(folder_path: str | Path) -> dict | None:
    """Read ``.tidy-idy/status.json`` written by the tool itself."""
    p = Path(folder_path).resolve() / ".tidy-idy" / "status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_log_text(job_id: str) -> str:
    path = job_runner.log_path_for(job_id)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_json_events(text: str) -> list[dict]:
    out = []
    for line in str(text or "").splitlines():
        t = line.strip()
        if not t.startswith("{"):
            continue
        try:
            obj = json.loads(t)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("event"):
            out.append(obj)
    return out


def latest_event(text: str, name: str) -> dict | None:
    found = None
    for ev in parse_json_events(text):
        if ev.get("event") == name:
            found = ev
    return found


def parse_panel_ready(text: str) -> dict | None:
    """Latest ``panel-ready`` JSON event in a job log (tests + thin callers)."""
    return latest_event(text, PANEL_READY_EVENT)


def read_bootstrap_file(path: str | Path) -> dict | None:
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) and obj.get("url") else None


def wait_for_event(job_id: str, event_name: str, *, timeout_s: float = 30.0,
                   poll_s: float = 0.2) -> dict | None:
    deadline = time.time() + max(0.5, float(timeout_s))
    while time.time() < deadline:
        found = latest_event(_read_log_text(job_id), event_name)
        if found:
            return found
        rec = job_runner.load_record(job_id)
        if rec and rec.get("status") not in (None, "running"):
            return None
        time.sleep(poll_s)
    return None


def wait_for_panel(job_id: str, *, timeout_s: float = 180.0,
                   poll_s: float = 0.25) -> dict | None:
    """Poll the durable job log for the tool's ``panel-ready`` line."""
    return wait_for_event(job_id, PANEL_READY_EVENT, timeout_s=timeout_s, poll_s=poll_s)


def _child_env() -> dict:
    child_env = {}
    for key in ("TIDY_IDY_DRIVER", "TRIO_DRIVER", "TRIO_DRIVER_PATH",
                "TRIO_DRIVER_REVIEW", "TRIO_MODEL_REVIEW"):
        if os.environ.get(key):
            child_env[key] = os.environ[key]
    if not child_env.get("TIDY_IDY_DRIVER") and not child_env.get("TRIO_DRIVER_PATH"):
        for cand in (
            Path(r"C:\dev\trio\drivers\gemini-cli.mjs"),
            Path(r"C:\dev\Skill Foundry\tools\agy-dispatch.mjs"),
        ):
            if cand.is_file():
                child_env.setdefault("TRIO_DRIVER_PATH", str(cand))
                break
    return child_env


def _pid_alive(pid) -> bool:
    """True if *pid* looks like a live process (Windows-safe)."""
    try:
        n = int(pid)
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, n)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        import os
        os.kill(n, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def is_loopback_url(url: str | None) -> bool:
    """True when *url* points at this host's loopback (tool-owned servers)."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def probe_loopback_alive(url: str | None, *, timeout_s: float = 1.5) -> bool:
    """True if a loopback tool URL accepts a TCP/HTTP connection right now.

    Used to distinguish a live panel/status server from a STALE status.json that
    still names ports after the process exited (common after idle close / crash).

    NEVER GET a ``/bootstrap/<nonce>`` URL — that path is single-use and redeeming
    it from a liveness probe burns the Triage Panel open ticket (observed live
    2026-07-22: status stuck mid-run while panel was ready but bootstrap was 410).
    Always probe ``/api/health`` on the same origin instead.
    """
    if not url or not is_loopback_url(url):
        return False
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    try:
        u = urlparse(str(url))
        # Always health-check the origin. Paths like /bootstrap/<nonce> are
        # single-use capability URLs — a GET redeems (and burns) them.
        probe = f"{u.scheme}://{u.netloc}/api/health"
        req = urllib.request.Request(probe, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            # Any HTTP response (incl. 401/404) means the port is live.
            _ = getattr(resp, "status", 200)
            return True
    except urllib.error.HTTPError:
        return True  # server answered — alive
    except Exception:
        return False


def mark_status_stale(folder_path: str | Path, *, reason: str = "panel process is gone") -> None:
    """Best-effort: rewrite status.json so a second click starts a fresh run."""
    root = Path(folder_path).resolve()
    p = root / ".tidy-idy" / "status.json"
    try:
        prev = {}
        if p.is_file():
            prev = json.loads(p.read_text(encoding="utf-8"))
        next_st = {
            **prev,
            "phase": "done",
            "message": f"Previous tidy-idy session ended ({reason}). Re-click to start a new pass.",
            "progress": 100,
            "step": "done",
            "stepLabel": "Session ended",
            "openUrl": None,
            "panelBaseUrl": None,
            "statusUrl": None,
            "statusPort": None,
            "stale": True,
            "staleReason": reason,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(next_st, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def live_tool_endpoints(folder_path: str | Path) -> dict:
    """Which tool loopback endpoints are actually accepting connections."""
    st = read_project_status(folder_path) or {}
    status_url = st.get("statusUrl")
    panel_base = st.get("panelBaseUrl")
    open_url = st.get("openUrl")
    status_live = probe_loopback_alive(status_url)
    # Derive panel origin from panelBaseUrl or from openUrl's host — never GET
    # the bootstrap path itself (single-use nonce).
    panel_origin = None
    if panel_base and is_loopback_url(panel_base):
        panel_origin = str(panel_base).rstrip("/")
    elif open_url and is_loopback_url(open_url):
        try:
            from urllib.parse import urlparse
            u = urlparse(str(open_url))
            panel_origin = f"{u.scheme}://{u.netloc}"
        except Exception:
            panel_origin = None
    panel_live = probe_loopback_alive(panel_origin) if panel_origin else False
    if panel_live and not panel_base:
        panel_base = panel_origin
    return {
        "status": st,
        "status_live": status_live,
        "panel_live": panel_live,
        "any_live": status_live or panel_live,
        "status_url": status_url if status_live else None,
        "panel_base": panel_base if panel_live else None,
        "open_url": open_url if panel_live else None,
    }


def proxy_mount_for(project_id: str) -> str:
    """Same-origin mount path for the reverse proxy (Tailscale / remote browsers)."""
    return f"/api/rnd/tidy_idy_proxy/{project_id}"


def reissue_panel_bootstrap(folder_path: str | Path) -> str | None:
    """Ask a LIVE panel process for a fresh single-use bootstrap URL (loopback only).

    The first bootstrap nonce is single-use; a second click / F5 would otherwise
    show raw JSON ``{ "error": "bootstrap nonce already redeemed" }``. Anchor
    (on the host) POSTs ``/api/reissue-bootstrap`` to mint a new open link for
    the same panel process without restarting the hygiene pass.
    """
    import urllib.error
    import urllib.request

    live = live_tool_endpoints(folder_path)
    base = live.get("panel_base")
    if not base or not is_loopback_url(base):
        return None
    url = str(base).rstrip("/") + "/api/reissue-bootstrap"
    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        boot = data.get("bootstrapUrl") or data.get("openUrl")
        if boot and is_loopback_url(boot):
            # Persist so status polls / second clicks share the new URL.
            try:
                p = status_path(folder_path)
                prev = {}
                if p.is_file():
                    prev = json.loads(p.read_text(encoding="utf-8"))
                prev["openUrl"] = boot
                if data.get("panelBaseUrl"):
                    prev["panelBaseUrl"] = data["panelBaseUrl"]
                prev["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                p.write_text(json.dumps(prev, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
            return str(boot)
    except Exception:
        return None
    return None


def browser_open_url(project_id: str, loopback_url: str | None) -> str | None:
    """Map a tool loopback URL onto the Anchor reverse-proxy path (path only).

    Remote browsers (Tailscale) cannot reach 127.0.0.1 on the Anchor host; the
    proxy path is same-origin with the Anchor GUI so it works from any client.
    """
    if not loopback_url or not project_id:
        return None
    if not is_loopback_url(loopback_url):
        return str(loopback_url)
    try:
        from urllib.parse import urlparse
        u = urlparse(str(loopback_url))
        sub = u.path or "/"
        if u.query:
            sub = f"{sub}?{u.query}"
        return f"{proxy_mount_for(project_id)}{sub}"
    except Exception:
        return None


def panel_upstream_base(folder_path: str | Path, *, require_live: bool = True) -> str | None:
    """Loopback panel base URL from status.json (optionally only if still listening)."""
    live = live_tool_endpoints(folder_path) if require_live else None
    if require_live:
        return live.get("panel_base") if live else None
    st = read_project_status(folder_path) or {}
    base = st.get("panelBaseUrl") or None
    if base and is_loopback_url(base):
        return str(base).rstrip("/")
    open_url = st.get("openUrl") or ""
    if is_loopback_url(open_url) and "/bootstrap/" in open_url:
        try:
            from urllib.parse import urlparse
            u = urlparse(open_url)
            return f"{u.scheme}://{u.netloc}"
        except Exception:
            return None
    return None


def status_upstream_base(folder_path: str | Path, *, require_live: bool = True) -> str | None:
    if require_live:
        live = live_tool_endpoints(folder_path)
        return live.get("status_url")
    st = read_project_status(folder_path) or {}
    base = st.get("statusUrl") or None
    if base and is_loopback_url(base):
        return str(base).rstrip("/")
    return None


def resolve_proxy_upstream(folder_path: str | Path, rel_path: str) -> str | None:
    """Choose panel vs status loopback upstream for a relative path under the proxy.

    Panel owns /bootstrap/* and its /api/* control plane. Status owns / and
    /api/status during the pre-panel phase. Only returns URLs that still answer.
    """
    route = rel_path.split("?", 1)[0] or "/"
    live = live_tool_endpoints(folder_path)
    panel = live.get("panel_base")
    status = live.get("status_url")
    if not live.get("any_live"):
        # Stale status.json naming dead ports — clear so next click restarts.
        st = live.get("status") or {}
        if st.get("phase") in (
                "starting", "scanning", "analyzing", "archiving", "panel-ready"):
            mark_status_stale(folder_path, reason="no process listening on recorded ports")
        return None
    if route.startswith("/bootstrap/") or route in (
            "/api/heartbeat", "/api/close", "/api/apply", "/api/restore",
            "/api/rescan", "/api/confirm-full-run", "/api/investigate",
            "/api/reissue-bootstrap",
            "/api/envelope", "/api/panel", "/api/trash", "/api/staleness",
            "/api/apply-state", "/api/identity", "/api/lock", "/api/cost-gate",
            "/api/archive", "/api/runs",
    ):
        return panel
    if route == "/api/health":
        return panel or status
    if route in ("/", "/status", "/api/status") or route.startswith("/api/status"):
        return status or panel
    return panel or status


def _proxy_timeout_for(rel_path: str, *, default_s: float = 30.0) -> float:
    """Bootstrap/HTML can be multi‑MB (hundreds of findings); Tailscale needs longer."""
    route = (rel_path or "/").split("?", 1)[0]
    if route.startswith("/bootstrap/") or route in ("/", "/status"):
        return max(float(default_s), 180.0)
    return float(default_s)


def _strip_anchor_auth_query(query: str) -> str:
    """Drop Anchor shared-secret from the upstream query (tool must not see it)."""
    if not query:
        return ""
    from urllib.parse import parse_qsl, urlencode

    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
            if k.lower() not in ("token", "anchor_token")]
    return urlencode(kept)


def proxy_to_loopback(
    folder_path: str | Path,
    *,
    method: str,
    rel_path: str,
    query: str = "",
    headers: dict | None = None,
    body: bytes | None = None,
    timeout_s: float | None = None,
) -> dict:
    """HTTP reverse-proxy to the tool's loopback status/panel server.

    Returns ``{ok, status, headers, body, content_type, upstream}`` or
    ``{ok: False, error, code}``. Hard-refuses non-loopback upstreams (SSRF).

    Tailscale / remote note (2026-07-22): the Triage Panel HTML can be very large.
    A short timeout used to abort mid-transfer and then ``mark_status_stale`` —
    remote status shells froze (often last seen ~42% / save) while the host was
    still fine. Timeouts are soft failures; only hard connection-refused marks stale.
    """
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    base = resolve_proxy_upstream(folder_path, rel_path)
    if not base:
        return {
            "ok": False,
            "error": "no live tidy-idy status/panel for this project",
            "code": "no-upstream",
        }
    if not is_loopback_url(base):
        return {"ok": False, "error": "upstream is not loopback", "code": "ssrf-guard"}

    path = rel_path if rel_path.startswith("/") else f"/{rel_path}"
    target = f"{base.rstrip('/')}{path}"
    clean_q = _strip_anchor_auth_query(query or "")
    if clean_q:
        target = f"{target}?{clean_q}"

    # Final SSRF check on the fully resolved URL.
    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"ok": False, "error": "upstream host refused", "code": "ssrf-guard"}
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "upstream scheme refused", "code": "ssrf-guard"}

    # Forward only the tool capability header + content-type — never Anchor's
    # shared secret (that authenticates the proxy hop, not the tool).
    out_headers = {}
    for key, val in (headers or {}).items():
        lk = str(key).lower()
        if lk in (
            "x-tidy-idy-token",
            "content-type",
            "accept",
        ):
            out_headers[key] = val

    effective_timeout = (
        float(timeout_s) if timeout_s is not None else _proxy_timeout_for(path)
    )

    data = body if method.upper() in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(
        target, data=data, headers=out_headers, method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
            raw = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
            return {
                "ok": True,
                "status": getattr(resp, "status", 200) or 200,
                "headers": resp_headers,
                "body": raw,
                "content_type": resp.headers.get("Content-Type") or "application/octet-stream",
                "upstream": base,
            }
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        try:
            raw = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw or b"")
        except Exception:
            raw = b""
        return {
            "ok": True,  # HTTP error from upstream is still a completed proxy hop
            "status": int(e.code or 502),
            "headers": dict(e.headers.items()) if e.headers else {},
            "body": raw,
            "content_type": (e.headers.get("Content-Type") if e.headers else None)
            or "application/octet-stream",
            "upstream": base,
        }
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        low = err.lower()
        # Hard dead only: connection refused. Timeouts are often "panel is busy
        # rendering a large HTML page" or a slow Tailscale hop — do NOT kill the
        # live session (that was the remote-stuck-at-42% failure mode).
        refused = (
            "10061" in err or "refused" in low
            or "winerror 10061" in low or "errno 111" in low
        )
        if refused:
            mark_status_stale(folder_path, reason="upstream connection refused")
            return {
                "ok": False,
                "error": (
                    "The tidy-idy panel is no longer running on the host "
                    "(previous session ended). Close this tab and click Tidy-Idy again."
                ),
                "code": "upstream-gone",
                "upstream": base,
            }
        if "timed out" in low or "10060" in err or "timeout" in low:
            return {
                "ok": False,
                "error": (
                    "Timed out loading the Triage Panel through Anchor (large report "
                    "or slow link). The host session may still be live — wait a few "
                    "seconds and click Open Triage Panel again, or re-click Tidy-Idy."
                ),
                "code": "proxy-timeout",
                "upstream": base,
            }
        return {
            "ok": False,
            "error": err,
            "code": "proxy-failed",
            "upstream": base,
        }


def rewrite_proxied_body(
    body: bytes,
    *,
    content_type: str,
    upstream_base: str,
    public_base: str,
) -> bytes:
    """Rewrite absolute loopback URLs in HTML/JS so the panel stays on the proxy."""
    ct = (content_type or "").lower()
    if "text/html" not in ct and "javascript" not in ct and "json" not in ct:
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    # Longest first so we don't partial-replace.
    replacements = [
        (upstream_base.rstrip("/") + "/", public_base.rstrip("/") + "/"),
        (upstream_base.rstrip("/"), public_base.rstrip("/")),
    ]
    for old, new in replacements:
        if old and old in text:
            text = text.replace(old, new)
    return text.encode("utf-8")


def status_for_folder(folder_path: str | Path, *, job_id: str | None = None,
                      project_id: str | None = None) -> dict:
    """Unified status for the browser status tab (poll endpoint)."""
    st = read_project_status(folder_path) or {}
    # Drop dead loopback URLs so the browser is not sent to a corpse.
    # Use a slightly longer probe: the panel process can be busy building a
    # multi‑MB HTML page (Tailscale open) and a 0.6s health miss was wrongly
    # marking the whole session stale mid-handoff.
    live = live_tool_endpoints(folder_path)
    if st.get("phase") in (
            "starting", "scanning", "analyzing", "archiving", "panel-ready"
    ) and not live.get("any_live") and (st.get("statusUrl") or st.get("panelBaseUrl")):
        # Double-check once more before killing the session (transient busy).
        import time as _time
        _time.sleep(0.35)
        live = live_tool_endpoints(folder_path)
    if st.get("phase") in (
            "starting", "scanning", "analyzing", "archiving", "panel-ready"
    ) and not live.get("any_live") and (st.get("statusUrl") or st.get("panelBaseUrl")):
        # Confirm the recorded PID is gone — do not stale on a single probe miss
        # while the process is still alive (large HTML render blocks the loop).
        if not _pid_alive(st.get("pid")):
            mark_status_stale(folder_path, reason="recorded ports no longer accept connections")
            st = read_project_status(folder_path) or st
            live = live_tool_endpoints(folder_path)
    log_ev = None
    rec = None
    if job_id:
        rec = job_runner.load_record(job_id)
        # Job interrupted (Anchor restart / kill) while status.json still says
        # analyzing → heal so remote clients stop spinning at a corpse progress.
        jstat = (rec or {}).get("status")
        if jstat in ("interrupted", "cancelled", "failed") and st.get("phase") in (
                "starting", "scanning", "analyzing", "archiving"):
            mark_status_stale(
                folder_path,
                reason=f"Anchor job {jstat} (often: service restart killed the run)",
            )
            st = read_project_status(folder_path) or st
            live = live_tool_endpoints(folder_path)
        log_text = _read_log_text(job_id)
        log_ev = {
            "status_ready": latest_event(log_text, STATUS_READY_EVENT),
            "panel_ready": latest_event(log_text, PANEL_READY_EVENT),
            "already_running": latest_event(log_text, ALREADY_RUNNING_EVENT),
            "refused": latest_event(log_text, "refused"),
            "run_complete": latest_event(log_text, "run-complete"),
        }
        pr = log_ev["panel_ready"]
        if pr and pr.get("bootstrapFile") and not st.get("openUrl"):
            boot = read_bootstrap_file(pr["bootstrapFile"])
            if boot and boot.get("url"):
                st = {**st, "openUrl": boot["url"], "phase": st.get("phase") or "panel-ready",
                      "panelBaseUrl": pr.get("url") or st.get("panelBaseUrl")}
        sr = log_ev["status_ready"]
        if sr and sr.get("statusUrl") and not st.get("statusUrl"):
            st = {**st, "statusUrl": sr["statusUrl"]}
        ar = log_ev["already_running"]
        if ar:
            st = {
                **st,
                "phase": ar.get("phase") or st.get("phase") or "scanning",
                "statusUrl": ar.get("statusUrl") or st.get("statusUrl"),
                "openUrl": ar.get("openUrl") or st.get("openUrl"),
                "panelBaseUrl": ar.get("panelBaseUrl") or st.get("panelBaseUrl"),
                "message": ar.get("message") or st.get("message") or "A tidy-idy run is already in progress.",
                "alreadyRunning": True,
            }

    phase = st.get("phase") or ("running" if rec and rec.get("status") == "running" else "unknown")
    message = st.get("message") or {
        "starting": "Starting hygiene pass…",
        "scanning": "Scanning the folder…",
        "analyzing": "Analyzing (this can take a minute on large trees)…",
        "archiving": "Writing the report…",
        "panel-ready": "Triage Panel is ready.",
        "failed": "Run failed.",
        "refused": "Run refused.",
        "done": "Done.",
        "running": "Hygiene pass in progress…",
    }.get(phase, "Working…")

    # Only advertise URLs that still answer (or non-loopback).
    raw_open = st.get("openUrl") or st.get("panelBaseUrl") or st.get("statusUrl")
    open_url = None
    if live.get("panel_live"):
        open_url = live.get("open_url") or live.get("panel_base")
    elif live.get("status_live"):
        open_url = live.get("status_url")
    elif raw_open and not is_loopback_url(raw_open):
        open_url = raw_open
    status_url_live = live.get("status_url") or (
        st.get("statusUrl") if st.get("statusUrl") and not is_loopback_url(st.get("statusUrl")) else None
    )
    proxy_open = browser_open_url(project_id, open_url) if project_id else None
    proxy_status = browser_open_url(project_id, status_url_live) if project_id else None
    # Progress % — prefer status.json; fall back to coarse phase map.
    progress = st.get("progress")
    if progress is None:
        progress = {
            "starting": 2,
            "scanning": 8,
            "analyzing": 20,
            "archiving": 96,
            "panel-ready": 100,
            "failed": 100,
            "refused": 100,
            "done": 100,
            "running": 15,
        }.get(phase, 0)
    try:
        progress = max(0, min(100, int(round(float(progress)))))
    except (TypeError, ValueError):
        progress = 0

    return {
        "ok": True,
        "phase": phase,
        "message": message,
        "projectName": st.get("projectName"),
        "rootPath": st.get("rootPath") or str(Path(folder_path).resolve()),
        "statusUrl": status_url_live,
        "openUrl": open_url,
        "panelBaseUrl": live.get("panel_base") if live.get("panel_live") else None,
        # Same-origin paths for Tailscale / remote browsers (never 127.0.0.1).
        "proxyOpenPath": proxy_open,
        "proxyStatusPath": proxy_status,
        "loopbackOnly": bool(open_url and is_loopback_url(open_url)),
        "upstreamLive": bool(live.get("any_live")),
        "findings": st.get("findings"),
        "runId": st.get("runId"),
        "error": st.get("error"),
        "job_id": job_id,
        "job_status": (rec or {}).get("status"),
        "alreadyRunning": bool(st.get("alreadyRunning")) and bool(live.get("any_live")),
        "updatedAt": st.get("updatedAt"),
        "startedAt": st.get("startedAt"),
        "progress": progress,
        "step": st.get("step"),
        "stepLabel": st.get("stepLabel") or st.get("step") or phase,
        "stepIndex": st.get("stepIndex"),
        "stepTotal": st.get("stepTotal"),
    }


def launch_tidy_idy(project_id: str, folder_path: str | Path, *,
                    wait_for_panel_s: float = 180.0,
                    wait_for_status_s: float = 4.0,
                    async_mode: bool = True) -> dict:
    """Thin-caller launch.

    ``async_mode=True`` (default): return as soon as the status page URL is known
    (or after a short wait), so the browser tab can show progress. The status
    endpoint is then polled for panel handoff.
    """
    root = Path(folder_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"folder not found: {root}", "code": "no-folder"}

    # Second click: only short-circuit when the tool process is STILL listening.
    # A stale status.json (panel-ready + dead ports) used to send remote browsers
    # to the reverse proxy → connection refused. Probe first; if dead, restart.
    existing = read_project_status(root)
    if existing and existing.get("phase") in (
            "starting", "scanning", "analyzing", "archiving", "panel-ready"):
        live = live_tool_endpoints(root)
        if live.get("any_live"):
            phase = existing.get("phase") or "scanning"
            # Prefer a FRESH bootstrap URL — the stored openUrl is often already
            # redeemed (single-use), which made re-clicks show raw JSON "{" .
            open_url = None
            if live.get("panel_live") and phase == "panel-ready":
                open_url = reissue_panel_bootstrap(root)
            if not open_url and live.get("panel_live") and phase == "panel-ready":
                # Old panel without reissue, or reissue failed — do NOT send a
                # spent bootstrap URL (browser shows raw JSON). Restart the pass.
                mark_status_stale(
                    root,
                    reason="panel live but cannot mint a fresh bootstrap; restarting tidy pass",
                )
                # Fall through to a new launch below.
            else:
                if not open_url:
                    # Never fall back to panel_base alone — that endpoint is health JSON.
                    # Never reuse a spent bootstrap path if reissue failed.
                    open_url = live.get("status_url")
                return {
                    "ok": True,
                    "already_running": True,
                    "job_id": None,
                    "job_type": TIDY_JOB_TYPE,
                    "folder_path": str(root),
                    "status_url": live.get("status_url"),
                    "open_url": open_url,
                    "panel_base": live.get("panel_base"),
                    "proxy_open_path": browser_open_url(project_id, open_url),
                    "proxy_status_path": browser_open_url(project_id, live.get("status_url")),
                    "loopback_only": bool(open_url and is_loopback_url(open_url)),
                    "phase": phase,
                    "progress": existing.get("progress") if existing.get("progress") is not None else (
                        100 if phase == "panel-ready" else 20
                    ),
                    "step": existing.get("step"),
                    "stepLabel": existing.get("stepLabel") or existing.get("step") or phase,
                    "message": existing.get("message") or "A tidy-idy run is already in progress for this project.",
                    "contributed_launch_logic": False,
                    "contributed_archive_logic": False,
                    "contributed_panel_logic": False,
                }
        # Recorded as in-flight / panel-ready but nothing is listening → restart.
        mark_status_stale(root, reason="stale status.json; process gone")

    entry = resolve_entry()
    if entry is None:
        return {
            "ok": False,
            "error": (
                f"tidy-idy CLI not installed (looked for bin/tidy-idy.mjs). "
                f"Set {ENTRY_ENV} or install the skill."
            ),
            "code": "no-entry",
        }

    nonce_dir = Path(tempfile.gettempdir()) / "anchor-tidy-idy"
    nonce_dir.mkdir(parents=True, exist_ok=True)
    nonce_file = nonce_dir / f"nonce-{project_id}-{int(time.time() * 1000)}.json"

    try:
        command = build_command(root, entry=entry, nonce_file=nonce_file, node="node")
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "code": "no-entry"}

    try:
        rec = job_runner.launch_guarded(
            BUILD_LANE,
            project_id,
            str(root),
            cwd=str(root),
            gated=False,
            command=command,
            env=_child_env() or None,
            # Panel process must outlive Anchor restarts (Tailscale remote open
            # depends on it). Default KILL_ON_JOB_CLOSE murders tidy mid-run.
            kill_on_job_close=False,
        )
    except job_runner.LaneBusyError as e:
        # Folder build lock often means a tidy run is already live — surface status.
        st = status_for_folder(root, project_id=project_id)
        return {
            "ok": False,
            "error": getattr(e, "message", None) or str(e),
            "code": getattr(e, "reason", "busy"),
            "holder": getattr(e, "holder", None),
            "status_url": st.get("statusUrl"),
            "open_url": st.get("openUrl"),
            "panel_base": st.get("panelBaseUrl"),
            "proxy_open_path": st.get("proxyOpenPath"),
            "proxy_status_path": st.get("proxyStatusPath"),
            "phase": st.get("phase"),
            "progress": st.get("progress"),
            "step": st.get("step"),
            "stepLabel": st.get("stepLabel"),
            "message": st.get("message") or "A tidy-idy run is already holding this folder.",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "code": "launch-failed"}

    job_id = rec.get("job_id")
    try:
        job_runner._update_record(job_id, job_type=TIDY_JOB_TYPE)  # noqa: SLF001
    except Exception:
        pass

    # Prefer status.json (written as soon as the status server binds). Do NOT wait
    # for the late status-ready stdout line that only appears after the full scan —
    # that made the browser sit at 2% for the entire analysis.
    already = wait_for_event(job_id, ALREADY_RUNNING_EVENT, timeout_s=0.4) if job_id else None
    file_st = {}
    status_ev = None
    if job_id and wait_for_status_s > 0:
        deadline = time.time() + float(wait_for_status_s)
        while time.time() < deadline:
            status_ev = latest_event(_read_log_text(job_id), STATUS_READY_EVENT)
            file_st = read_project_status(root) or {}
            if status_ev or file_st.get("statusUrl") or file_st.get("phase"):
                break
            rec_now = job_runner.load_record(job_id)
            if rec_now and rec_now.get("status") not in (None, "running"):
                break
            time.sleep(0.1)
    file_st = file_st or read_project_status(root) or {}
    status_url = (
        (status_ev or {}).get("statusUrl")
        or (already or {}).get("statusUrl")
        or file_st.get("statusUrl")
    )

    open_url = file_st.get("openUrl") or (already or {}).get("openUrl")
    panel_base = file_st.get("panelBaseUrl")
    phase = file_st.get("phase") or "starting"
    progress = file_st.get("progress")
    if progress is None:
        progress = {
            "starting": 2, "scanning": 8, "analyzing": 20, "archiving": 96,
            "panel-ready": 100, "failed": 100, "refused": 100, "done": 100,
        }.get(phase, 2)
    if async_mode:
        return {
            "ok": True,
            "async": True,
            "job_id": job_id,
            "job_type": TIDY_JOB_TYPE,
            "lane": BUILD_LANE,
            "entry": str(entry),
            "folder_path": str(root),
            "status": rec.get("status"),
            "log_path": rec.get("log_path"),
            "status_url": status_url,
            "open_url": open_url,
            "panel_base": panel_base,
            "proxy_open_path": browser_open_url(project_id, open_url or panel_base),
            "proxy_status_path": browser_open_url(project_id, status_url),
            "loopback_only": bool(
                (open_url and is_loopback_url(open_url))
                or (status_url and is_loopback_url(status_url))
            ),
            "phase": phase,
            "progress": progress,
            "step": file_st.get("step"),
            "stepLabel": file_st.get("stepLabel") or file_st.get("step") or phase,
            "message": file_st.get("message") or "Hygiene pass started — status page will update live.",
            "already_running": bool(already),
            "contributed_launch_logic": False,
            "contributed_archive_logic": False,
            "contributed_panel_logic": False,
        }

    # Legacy sync path: wait for panel-ready (kept for tests / callers that want it).
    ready = wait_for_panel(job_id, timeout_s=wait_for_panel_s) if job_id else None
    bootstrap_url = None
    if ready and ready.get("bootstrapFile"):
        boot = read_bootstrap_file(ready["bootstrapFile"])
        bootstrap_url = boot.get("url") if boot else None
    return {
        "ok": True,
        "async": False,
        "job_id": job_id,
        "job_type": TIDY_JOB_TYPE,
        "lane": BUILD_LANE,
        "entry": str(entry),
        "folder_path": str(root),
        "status": rec.get("status"),
        "log_path": rec.get("log_path"),
        "status_url": status_url,
        "panel": ready,
        "open_url": bootstrap_url,
        "panel_base": (ready or {}).get("url"),
        "contributed_launch_logic": False,
        "contributed_archive_logic": False,
        "contributed_panel_logic": False,
    }
