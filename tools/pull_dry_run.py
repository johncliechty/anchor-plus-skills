#!/usr/bin/env python3
"""Pull-into-sandbox dry run — walk the collaborator journey from a BUILT
package (dev tool; the artifact-side half of v1.1.3 acceptance).

Where ``share_sandbox.py`` proves the BUILD side (manifest → gates → staged
tree), this proves the ARTIFACT side: take the actual built Package B, "pull"
it into a fresh directory exactly like a collaborator unzipping it, and run
the real journey against that copy —

  P1  doctor in the pulled tree (deterministic; must find no missing modules)
  P2  hermetic Package-B onboard from the pulled tree (mock claude seat,
      junction-forced skill registration → every skill Claude-readable,
      readiness stamped READY)
  P3  the REAL launcher (`launch_anchor_dashboard.py --no-browser`) on an
      ISOLATED port + data dir + stub PTY: probes, genuinely spawns the
      server with the token wired, re-probes to OK
  P4  against that live server: tokenless mutating POST → 401; tokened
      new_project → 200; New General session starts under the stub PTY
  P5  errors.log contains ZERO ModuleNotFoundError (the incident class)
  P6  teardown (kill the spawned server by port; scrub scratch)

Usage:  python tools/pull_dry_run.py [--package DIR] [--keep]
Default package: <repo-parent>/Anchor-ship/clean-ship/B-anchor-plus-skills

Never touches the live :8777 service, real ~/.claude/skills, or real data.
Exit 0 iff every gate passes; scratch is kept on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = REPO.parent / "Anchor-ship" / "clean-ship" / "B-anchor-plus-skills"

_RESULTS = []


def gate(name, ok, detail=""):
    _RESULTS.append((name, bool(ok)))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""))
    return bool(ok)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, body=None, token=None, timeout=10):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def kill_by_port(port: int) -> None:
    """Kill whatever listens on the sandbox port (Windows; scratch-only)."""
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetTCPConnection -LocalPort %d -State Listen "
             "-ErrorAction SilentlyContinue | Select-Object -First 1)"
             ".OwningProcess" % port],
            capture_output=True, text=True, timeout=20)
        pid = (out.stdout or "").strip()
        if pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                           capture_output=True, timeout=20)
    except Exception:
        pass


def scrub(path: Path) -> None:
    """Remove a scratch tree that may contain junctions (rmdir handles them)."""
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)
    if path.exists() and os.name == "nt":
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)],
                       capture_output=True, timeout=120)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default=str(DEFAULT_PACKAGE))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    package = Path(args.package)
    if not (package / "anchor_gui.py").is_file():
        print("no built package at %s — run the clean-ship builder first"
              % package)
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="anchor-pull-"))
    print("pull scratch:", scratch)
    install = scratch / "install"

    # ── P0: the "unzip" — a byte copy of the built artifact ────────────────
    shutil.copytree(package, install)
    n = sum(1 for p in install.rglob("*") if p.is_file())
    gate("P0 pull (simulated unzip)", n > 500, "%d files" % n)

    env_base = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    def run_in(cwd, argv2, extra_env=None, timeout=300):
        e = dict(os.environ)
        e.update(env_base)
        e.update(extra_env or {})
        return subprocess.run(argv2, cwd=str(cwd), env=e, capture_output=True,
                              text=True, errors="replace", timeout=timeout)

    # ── P1: doctor in the pulled tree ───────────────────────────────────────
    proc = run_in(install, [sys.executable, "doctor.py"])
    quiet = "is MISSING from this install" not in (proc.stdout or "")
    gate("P1 doctor finds no missing modules", quiet,
         "exit=%s" % proc.returncode if quiet else (proc.stdout or "")[:200])

    # ── P2: hermetic Package-B onboard from the pulled tree ─────────────────
    home = scratch / "home"
    code = r"""
import json
from pathlib import Path
import share_onboard as sob
import share_skills_root as ssr
home = Path(%r); pkg = Path.cwd()
rep = sob.run_share_onboard(
    home, package_id="B",
    skills_src=pkg / "vendor" / "bundled-skills",
    mock_seat_results={"claude": True},
    desktop_dir=str(home / "Desktop"),
    dialogue_complete=True)
farm = ssr.claude_skills_home(home)
src = pkg / "vendor" / "bundled-skills"
skills = [s["name"] for s in (rep.get("skills") or {}).get("installed", [])]
bad = [sid for sid in skills
       if (src / sid / "SKILL.md").is_file()
       and not (farm / sid / "SKILL.md").is_file()]
print(json.dumps({
    "installed": len(skills), "unreadable": bad,
    "readiness": (rep.get("readiness") or {}).get("status"),
    "pywinpty_step": next((s["result"].get("status") for s in rep["steps"]
                           if s["step"] == "terminal_extra"), None),
}))
""" % str(home)
    proc = run_in(install, [sys.executable, "-c", code], extra_env={
        "ANCHOR_ONBOARD_SKIP_PIP": "1",
        "ANCHOR_SKILLS_LINK_MODE": "junction" if os.name == "nt" else "auto",
    })
    ok2, detail2 = False, (proc.stderr or proc.stdout or "")[-300:]
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        ok2 = (out["installed"] > 0 and not out["unreadable"]
               and out["readiness"] == "ready")
        detail2 = ("%d skills, readiness=%s, pywinpty-step=%s"
                   % (out["installed"], out["readiness"], out["pywinpty_step"]))
    except Exception:
        pass
    gate("P2 onboard: skills Claude-readable + readiness READY", ok2, detail2)

    # ── P3: the REAL launcher on an isolated port/data dir ──────────────────
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    token = "pull-" + secrets.token_urlsafe(16)
    data_dir = scratch / "data"
    launcher_env = {
        "ANCHOR_DASHBOARD_URL": base,
        "ANCHOR_DATA_DIR": str(data_dir),
        "ANCHOR_TOKEN": token,
        "ANCHOR_PTY_BACKEND": "stub",   # never a real engine/PTY in the dry run
    }
    try:
        proc = run_in(install, [sys.executable, "launch_anchor_dashboard.py",
                                "--no-browser"],
                      extra_env=launcher_env, timeout=120)
        code_probe, _ = http("GET", base + "/", timeout=5)
        gate("P3 launcher genuinely starts the server",
             proc.returncode == 0 and code_probe == 200,
             "launcher-exit=%s GET/=%s" % (proc.returncode, code_probe))

        # ── P4: auth + New General against the spawned server ───────────────
        proj = scratch / "proj"
        proj.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(proj),
                       capture_output=True, timeout=30)
        (proj / "README.md").write_text("# pull proj\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(proj),
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-c", "user.email=anchor@localhost",
                        "-c", "user.name=anchor", "commit", "-qm", "init"],
                       cwd=str(proj), capture_output=True, timeout=30)

        code_no, _ = http("POST", base + "/api/rnd/new_project",
                          body={"mode": "existing", "name": "pull",
                                "folder_path": str(proj)})
        code_yes, body_yes = http("POST", base + "/api/rnd/new_project",
                                  body={"mode": "existing", "name": "pull",
                                        "folder_path": str(proj)},
                                  token=token)
        gate("P4a mutating API token-gated",
             code_no == 401 and code_yes == 200,
             "no-token=%s with-token=%s" % (code_no, code_yes))

        pid = None
        try:
            doc = json.loads(body_yes.decode("utf-8"))
            pid = (doc.get("entry") or {}).get("id") or doc.get("id")
        except Exception:
            pass
        sid = None
        if pid:
            code_ts, body_ts = http("POST", base + "/api/rnd/term_start",
                                    body={"project_id": pid,
                                          "lane": "general",
                                          "backend": "claude"},
                                    token=token, timeout=60)
            try:
                doc_ts = json.loads(body_ts.decode("utf-8"))
                sid = ((doc_ts.get("session") or doc_ts.get("record")
                        or {}).get("session_id"))
            except Exception:
                pass
            gate("P4b New General session starts (stub PTY)",
                 code_ts == 200 and bool(sid),
                 "status=%s session=%s" % (code_ts, sid))
            if sid:
                http("POST", base + "/api/rnd/term_kill",
                     body={"project_id": pid, "session": sid,
                           "confirm": True}, token=token, timeout=60)
        else:
            gate("P4b New General session starts (stub PTY)", False,
                 "no project id: %s" % (body_yes or b"")[:160])
    finally:
        kill_by_port(port)

    # ── P5: the incident class stays dead ───────────────────────────────────
    spam = []
    for log in data_dir.rglob("errors.log"):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        spam += [ln for ln in text.splitlines() if "ModuleNotFoundError" in ln]
    gate("P5 errors.log clean of ModuleNotFoundError", not spam,
         (spam[0][:160] if spam else "0 occurrences"))

    # ── verdict + teardown ──────────────────────────────────────────────────
    failed = [nm for (nm, ok) in _RESULTS if not ok]
    print("\n%d/%d gates passed." % (len(_RESULTS) - len(failed),
                                     len(_RESULTS)))
    if failed:
        print("FAILED:", ", ".join(failed))
        print("scratch kept:", scratch)
        return 1
    if args.keep:
        print("scratch kept (--keep):", scratch)
    else:
        scrub(scratch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
