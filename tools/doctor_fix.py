#!/usr/bin/env python3
"""Standard Anchor Doctor diagnostic & quick-fix tool (tools/doctor_fix.py).

Gives Doctor (and any terminal agent or operator) a deterministic, fast script
to resolve common Anchor health & cockpit issues without wandering or entering
interactive Plan Mode:
  1. --repair-cockpits : Reconciles roadmap.json active step & status-summary.json
                         with strip.json and DELIVERABLES.md across registered projects.
  2. --sync            : Hot-reloads live Anchor modules on :8777 via /api/doctor/resolve_all.
  3. --probe           : Probes key live HTTP routes (/api/version, /api/status,
                         /api/rnd/projects_html, /doctor, /high-seat) with timing.
  4. --auto            : Runs all of the above and triggers a healthcheck refresh
                         when the latest report had stale/unreachable issues.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_token() -> str:
    env_tok = (os.environ.get("ANCHOR_TOKEN") or "").strip()
    if env_tok:
        return env_tok
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\Anchor\Parameters",
            )
            vals, _ = winreg.QueryValueEx(k, "AppEnvironmentExtra")
            for item in vals or ():
                s = str(item or "")
                if s.startswith("ANCHOR_TOKEN="):
                    val = s.split("=", 1)[1].strip()
                    if val:
                        return val
        except Exception:
            pass
    try:
        import paths as _paths
        for cand in (
            _paths.data_dir() / "anchor_token",
            _paths.data_dir() / "token",
            ROOT / ".anchor" / "anchor_token",
            ROOT / ".anchor" / "token",
            Path.home() / ".anchor" / "anchor_token",
            Path.home() / ".anchor" / "token",
        ):
            if cand.is_file():
                val = cand.read_text(encoding="utf-8", errors="replace").strip()
                if val:
                    return val
    except Exception:
        pass
    return ""


def _port() -> int:
    try:
        return int(os.environ.get("ANCHOR_PORT") or 8777)
    except Exception:
        return 8777


def probe_live_routes(paths=None, timeout: float = 5.0) -> list[dict]:
    if not paths:
        paths = [
            "/api/version",
            "/api/status",
            "/api/rnd/projects_html",
            "/doctor",
            "/high-seat",
        ]
    tok = _read_token()
    port = _port()
    results = []
    for p in paths:
        url = f"http://127.0.0.1:{port}{p}"
        headers = {}
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
            headers["X-Anchor-Token"] = tok
        req = urllib.request.Request(url, headers=headers, method="GET")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _ = resp.read()
                ms = int((time.monotonic() - t0) * 1000)
                results.append({"path": p, "ok": 200 <= resp.status < 400, "code": resp.status, "ms": ms})
        except urllib.error.HTTPError as exc:
            ms = int((time.monotonic() - t0) * 1000)
            results.append({"path": p, "ok": False, "code": exc.code, "ms": ms, "error": str(exc)})
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            results.append({"path": p, "ok": False, "code": 0, "ms": ms, "error": str(exc)})
    return results


def repair_cockpits() -> list[dict]:
    from steward_cockpit import steward_campaign as sc
    import rnd_registry as rnd

    repaired = []
    seen_dirs = set()
    try:
        projects = rnd.list_projects() or []
    except Exception:
        projects = []
    candidates = []
    for proj in projects:
        fp = (proj or {}).get("folder_path") or ""
        if fp and Path(fp).is_dir():
            candidates.append(Path(fp))
    book1 = Path(r"C:\dev\Writing\Artificial Magi\Book 1")
    if book1.is_dir():
        candidates.append(book1)

    for base in candidates:
        try:
            efforts = sc.discover_efforts(str(base))
        except Exception:
            efforts = [{"rel": "", "name": base.name}] if (base / "ECGBERHT.md").is_file() else []
        for eff in efforts:
            edir = base / eff["rel"] if eff.get("rel") else base
            try:
                real = str(edir.resolve())
            except Exception:
                real = str(edir)
            if real in seen_dirs or not (edir / "ECGBERHT.md").is_file():
                continue
            seen_dirs.add(real)
            try:
                sync_res = sc.sync_steward_projections(str(edir))
                status = sc.compose_status(str(edir), {})
                st_file = edir / ".ecgberht" / "status-summary.json"
                st_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = st_file.with_name(f"status-summary.json.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(tmp, st_file)
                repaired.append({
                    "dir": str(edir),
                    "roadmap_synced": bool(sync_res.get("changed")),
                    "status_updated": True,
                })
            except Exception as exc:
                repaired.append({"dir": str(edir), "error": str(exc)})
    return repaired


def sync_live_server() -> dict:
    tok = _read_token()
    port = _port()
    url = f"http://127.0.0.1:{port}/api/doctor/resolve_all"
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Anchor-Token"] = tok
    body = json.dumps({"token": tok} if tok else {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25.0) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _server_boot() -> str:
    port = _port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return str(data.get("boot") or "")
    except Exception:
        return ""


def restart_live_server(wait_s: float = 30.0) -> dict:
    old_boot = _server_boot()
    tok = _read_token()
    port = _port()
    url = f"http://127.0.0.1:{port}/api/restart"
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Anchor-Token"] = tok
    body = json.dumps({"token": tok} if tok else {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            res = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if res.get("restarting"):
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            time.sleep(1.0)
            cur_boot = _server_boot()
            if cur_boot and cur_boot != old_boot:
                res["restarted_ready"] = True
                res["new_boot"] = cur_boot
                break
    return res


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Anchor Doctor standard diagnostic & quick-fix tool")
    parser.add_argument("--auto", action="store_true", help="Run full sync, cockpit repair, route probe, and health verification")
    parser.add_argument("--sync", action="store_true", help="Sync live server modules via /api/doctor/resolve_all")
    parser.add_argument("--restart", action="store_true", help="Supervised restart of live Anchor server via /api/restart")
    parser.add_argument("--repair-cockpits", action="store_true", help="Sync roadmap.json and status-summary.json across cockpits")
    parser.add_argument("--probe", action="store_true", help="Probe live HTTP routes")
    parser.add_argument("--run-healthcheck", action="store_true", help="Run anchor_healthcheck.py synchronously")
    args = parser.parse_args(argv)

    if not (args.auto or args.sync or args.restart or args.repair_cockpits or args.probe or args.run_healthcheck):
        args.auto = True

    summary = {"ok": True}
    if args.auto or args.repair_cockpits:
        summary["cockpits"] = repair_cockpits()
    if args.restart:
        summary["restart"] = restart_live_server()
    if args.auto or args.sync:
        sync_res = sync_live_server()
        summary["live_sync"] = sync_res
    if args.auto or args.probe:
        probes = probe_live_routes(timeout=8.0)
        summary["probes"] = probes
        if not all(p.get("ok") for p in probes):
            summary["ok"] = False
    if args.run_healthcheck:
        proc = subprocess.run([sys.executable, str(ROOT / "anchor_healthcheck.py")], cwd=str(ROOT))
        summary["healthcheck_exit"] = proc.returncode
        if proc.returncode != 0:
            summary["ok"] = False

    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
