#!/usr/bin/env python3
"""Stranger-install sandbox — the v1.1.3 share-fix acceptance suite (dev tool).

Simulates a collaborator receiving the package on THIS machine, with every
side effect confined to a scratch directory: builds the package with the one
blessed builder (all gates fail-closed), then proves the things the 1.1.x
share silently broke — the incident modules ship, the server cold-boots with
a CLEAN error log, auth is enforced when the token is wired, a "New General"
terminal session starts under the stub PTY, onboard registers skills in a
form Claude can actually read (junction/copy — never a bare pointer), and the
doctor deterministically catches a hole punched into the install.

Usage:  python tools/share_sandbox.py [--scratch DIR] [--keep]

NEVER touches the live :8777 service, the real ~/.claude/skills, or real
data. Prints one PASS/FAIL line per gate; exit 0 iff all gates pass. On
failure the scratch dir is kept for inspection.

This is the AUTOMATED half of acceptance. The other half — a genuinely clean
Windows box (no Dev Mode, no admin, no pre-installed tools) — is
tools/vm_check.ps1, run by a human on a VM before re-sharing.
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
sys.path.insert(0, str(REPO))

import distro  # noqa: E402

#: The modules the 1.1.x share was missing (friction-intake-2026-07-30 + the
#: two the import-closure gate found). Every one must be in the package.
INCIDENT_MODULES = (
    "proc_probe.py", "reaper.py", "reaper_arming.py", "freeze_state.py",
    "zombie_hunter.py", "tidy_idy_runner.py", "foundry_integrity.py",
    "foundry_safety.py", "foundry_skills.py", "foundry_acceptance.py",
    "verify_freeze_manifest.py", "orientation.py", "parity.py",
)

COLD_START_FILES = (
    "onboard.cmd", "onboard.ps1", "onboard.py", "onboard_cli.py",
    "onboard_bootstrap.py", "share_onboard.py", "launch_anchor_dashboard.py",
    "USER-ONBOARD.md", "VERSION", "CHANGELOG.md", "anchor.ico",
    "CLAUDE.md", "README.md", "doctor.py",
)

_RESULTS = []


def gate(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
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


def run_py(staging, code, env=None, timeout=180):
    """Run a python snippet with cwd=staging (imports resolve in-package)."""
    e = dict(os.environ)
    e.update(env or {})
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, "-c", code], cwd=str(staging),
                          env=e, capture_output=True, text=True,
                          errors="replace", timeout=timeout)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    scratch = Path(args.scratch) if args.scratch else Path(
        tempfile.mkdtemp(prefix="anchor-sandbox-"))
    scratch.mkdir(parents=True, exist_ok=True)
    print("sandbox scratch:", scratch)
    staging = scratch / "pkg"

    # Author-machine skill sources (packaging-time only), like the wrapper.
    os.environ.setdefault("ANCHOR_TRIO_DIR", r"C:\dev\trio")
    os.environ.setdefault("ANCHOR_FOUNDRY_DIR", r"C:\dev\Skill Foundry")
    os.environ.setdefault("ANCHOR_GANDALF_DIR", r"C:\dev\Skill Foundry")
    # v1.2.3: the Ecgberht steward is its own git root (repo root IS the
    # skill). Without this the sandbox silently exercises a 13-skill bundle
    # while the real builder ships 14 — an acceptance suite that does not test
    # what ships.
    os.environ.setdefault("ANCHOR_ECGBERHT_DIR", r"C:\dev\Ecgberht")

    # ── G1: build via the ONE blessed builder (all gates fail-closed) ───────
    try:
        import vendor_skills as vs
        sources = [(n, "ANCHOR_FOUNDRY_DIR", "skills/gandalf") if n == "gandalf"
                   else (n, ev, sub) for (n, ev, sub) in vs.SKILL_SOURCES]
        report = distro.build_distro(output_dir=staging,
                                     vendor_sources=sources)
        gate("G1 build (PII + import-closure + startup gates)", True,
             "%d files" % len(report["files"]))
    except Exception as exc:
        gate("G1 build (PII + import-closure + startup gates)", False,
             "%s: %s" % (type(exc).__name__, str(exc)[:400]))
        return finish(scratch, args.keep)

    # ── G2: the incident modules + cold-start surface actually shipped ──────
    missing = [m for m in INCIDENT_MODULES if not (staging / m).is_file()]
    missing += [f for f in COLD_START_FILES if not (staging / f).is_file()]
    gate("G2 package completeness", not missing,
         ("missing: " + ", ".join(missing)) if missing else
         "all incident modules + cold-start files present")

    # ── G3: version stamps agree ────────────────────────────────────────────
    try:
        # The invariant is AGREEMENT between the two stamps, not equality with a
        # frozen release number. Pinning the literal (was "1.1.3") made this gate
        # fail on every subsequent line for a reason unrelated to product health,
        # and masked the real v1.2 desync (VERSION 1.2.2 vs pyproject 1.1.3).
        v_file = (staging / "VERSION").read_text(encoding="utf-8").strip()
        py_toml = (staging / "pyproject.toml").read_text(encoding="utf-8")
        ok = bool(v_file) and ('version = "%s"' % v_file) in py_toml
        gate("G3 version alignment", ok,
             "VERSION=%s pyproject-match=%s" % (v_file, ok))
    except Exception as exc:
        gate("G3 version alignment", False, str(exc)[:200])

    # ── G4: cold boot from the package — clean log, token-gated, general
    #        session starts under the stub PTY ──────────────────────────────
    data_dir = scratch / "data"
    port = free_port()
    token = "sbx-" + secrets.token_urlsafe(16)
    proj = scratch / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(proj),
                       capture_output=True, timeout=30)
        (proj / "README.md").write_text("# sandbox proj\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(proj),
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-c", "user.email=anchor@localhost",
                        "-c", "user.name=anchor", "commit", "-qm", "init"],
                       cwd=str(proj), capture_output=True, timeout=30)
    except Exception:
        pass

    env = dict(os.environ)
    env.update({
        "ANCHOR_DATA_DIR": str(data_dir),
        "ANCHOR_PTY_BACKEND": "stub",
        "ANCHOR_TOKEN": token,
        "ANCHOR_PROACTIVE_SUMMARY": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    base = "http://127.0.0.1:%d" % port
    server = subprocess.Popen(
        [sys.executable, "anchor_gui.py", "--no-browser", "--port", str(port)],
        cwd=str(staging), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(90):
            code, _b = http("GET", base + "/", timeout=3)
            if code == 200:
                up = True
                break
            time.sleep(0.5)
        gate("G4a cold boot serves GET /", up, base)

        if up:
            # Token discipline: tokenless mutating POST → 401; with token ≠ 401.
            code_no, _ = http("POST", base + "/api/rnd/new_project",
                              body={"mode": "existing", "name": "sbx",
                                    "folder_path": str(proj)})
            code_yes, body_yes = http("POST", base + "/api/rnd/new_project",
                                      body={"mode": "existing", "name": "sbx",
                                            "folder_path": str(proj)},
                                      token=token)
            gate("G4b mutating API token-gated",
                 code_no == 401 and code_yes not in (None, 401),
                 "no-token=%s with-token=%s" % (code_no, code_yes))

            # New General session under the stub PTY (the friction repro).
            pid = None
            try:
                doc = json.loads(body_yes.decode("utf-8"))
                pid = (doc.get("entry") or {}).get("id") or doc.get("id")
            except Exception:
                pass
            if pid:
                code_ts, body_ts = http(
                    "POST", base + "/api/rnd/term_start",
                    body={"project_id": pid, "lane": "general",
                          "backend": "claude"},
                    token=token, timeout=60)
                sid = None
                try:
                    doc_ts = json.loads(body_ts.decode("utf-8"))
                    sid = ((doc_ts.get("session") or doc_ts.get("record")
                            or {}).get("session_id"))
                except Exception:
                    pass
                gate("G4c New General session starts (stub PTY)",
                     code_ts == 200 and bool(sid),
                     "status=%s session=%s" % (code_ts, sid or
                                               (body_ts or b"")[:120]))
                if sid:
                    http("POST", base + "/api/rnd/term_kill",
                         body={"project_id": pid, "session": sid,
                               "confirm": True}, token=token, timeout=60)
            else:
                gate("G4c New General session starts (stub PTY)", False,
                     "no project id from new_project: %s"
                     % (body_yes or b"")[:200])
    finally:
        try:
            server.terminate()
            server.wait(timeout=10)
        except Exception:
            try:
                server.kill()
            except Exception:
                pass

    # Clean error log — the 1.1.x installs spammed ModuleNotFoundError.
    spam = []
    for log in data_dir.rglob("errors.log"):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        spam += [ln for ln in text.splitlines() if "ModuleNotFoundError" in ln]
    gate("G4d error log clean of ModuleNotFoundError", not spam,
         (spam[0][:160] if spam else "0 occurrences"))

    # ── G5: onboard from the package — skills READABLE by Claude ────────────
    home_b = scratch / "home-b"
    onboard_code = r"""
import json
from pathlib import Path
import share_onboard as sob
import share_skills_root as ssr
home = Path(%r); staging = Path.cwd()
rep = sob.run_share_onboard(
    home, package_id="B",
    skills_src=staging / "vendor" / "bundled-skills",
    mock_seat_results={"claude": True},
    desktop_dir=str(home / "Desktop"),
    dialogue_complete=True)
farm = ssr.claude_skills_home(home)
src = staging / "vendor" / "bundled-skills"
skills = [s["name"] for s in (rep.get("skills") or {}).get("installed", [])]
bad = []
checked = 0
for sid in skills:
    # Support bundles (drivers/foundry) carry no SKILL.md by design — only
    # REAL skills must be Claude-readable through the farm link.
    if not (src / sid / "SKILL.md").is_file():
        continue
    checked += 1
    if not (farm / sid / "SKILL.md").is_file():
        bad.append(sid)
print(json.dumps({"installed": len(skills), "checked": checked,
                  "unreadable": bad, "hosts": rep.get("hosts_registered")}))
""" % str(home_b)
    proc = run_py(staging, onboard_code, env={
        "ANCHOR_ONBOARD_SKIP_PIP": "1",
        # Stock-Windows realism: force the junction mechanism (no symlinks).
        "ANCHOR_SKILLS_LINK_MODE": "junction" if os.name == "nt" else "auto",
    }, timeout=300)
    ok5, detail5 = False, (proc.stderr or proc.stdout or "")[-300:]
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        ok5 = out["installed"] > 0 and not out["unreadable"]
        detail5 = ("%d skills installed; unreadable=%s; hosts=%s"
                   % (out["installed"], out["unreadable"], out["hosts"]))
    except Exception:
        pass
    gate("G5 onboard installs Claude-readable skills (junction mode)",
         ok5, detail5)

    # ── G6: doctor — quiet on the full package, LOUD on a punched hole ──────
    proc = run_py(staging, "import doctor,sys;sys.exit(doctor.run_doctor())")
    quiet = "is MISSING from this install" not in (proc.stdout or "")
    gate("G6a doctor quiet on complete package", quiet,
         (proc.stdout or "")[:200] if not quiet else "no missing modules")

    broken = scratch / "pkg-broken"
    try:
        shutil.copytree(staging, broken,
                        ignore=shutil.ignore_patterns("__pycache__"))
        (broken / "reaper.py").unlink()
        proc = run_py(broken, "import doctor,sys;sys.exit(doctor.run_doctor())")
        loud = (proc.returncode == 1
                and "reaper" in (proc.stdout or "")
                and "is MISSING from this install" in (proc.stdout or ""))
        gate("G6b doctor catches a deleted module", loud,
             "exit=%s reaper-flagged=%s" % (proc.returncode,
                                            "reaper" in (proc.stdout or "")))
    except Exception as exc:
        gate("G6b doctor catches a deleted module", False, str(exc)[:200])

    return finish(scratch, args.keep)


def finish(scratch, keep) -> int:
    failed = [n for (n, ok, _d) in _RESULTS if not ok]
    print("\n%d/%d gates passed." % (len(_RESULTS) - len(failed),
                                     len(_RESULTS)))
    if failed:
        print("FAILED:", ", ".join(failed))
        print("scratch kept for inspection:", scratch)
        return 1
    if not keep:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print("scratch kept (--keep):", scratch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
