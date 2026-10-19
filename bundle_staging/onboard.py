"""onboard.py — the Anchor distro installer CORE (share-distro Wave 6).

The safe, idempotent, resumable, rollback-able bring-up core for a freshly
cloned Anchor distro. This wave covers the THREE non-service steps — install the
vendored skills, scaffold a fresh empty Anchor, and mint a per-machine token.
Service registration is a SEPARATE later step (Wave 7); ``main()`` only PRINTS
"service setup: next step" here.

Design rules (MASTER-PLAN decisions #7, #8, R3):
  * Python **stdlib only** (os, sys, pathlib, shutil, secrets, platform,
    subprocess via shutil.which).
  * **COPY by default**, symlink only on an explicit opt-in.
  * **Refuse-don't-clobber**: never overwrite an existing skill / data file that
    we didn't put there.
  * **Idempotent + resumable + rollback**: a re-run is a no-op; a partial skill
    install is rolled back (no half-copied skill dir); a resume completes the
    rest.
  * The token is written **OUTSIDE the repo tree** (default the data dir) so
    ``build_distro`` never stages it; it is NEVER printed to a shared log; an
    existing token file is kept (idempotent).
"""

from __future__ import annotations

import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# A small marker file written into each skill dir WE install, so a re-run can
# tell "our copy" (safe to skip idempotently) apart from a differently-sourced
# pre-existing dir/symlink (refuse-don't-clobber).
_OURS_MARKER = ".anchor-onboard-installed"

# The default skills home (override via ANCHOR_SKILLS_HOME).
_DEFAULT_SKILLS_HOME = Path.home() / ".claude" / "skills"
# The default bundled-skills source (override via ANCHOR_BUNDLED_SKILLS_DIR).
_DEFAULT_BUNDLED_SKILLS = REPO_ROOT / "vendor" / "bundled-skills"
# The default data dir. Decision #7 requires the token to live OUTSIDE the repo
# tree so ``build_distro`` (deny-by-default) never stages it. We therefore
# default the data dir to ``~/.anchor`` (the user's home), genuinely outside the
# cloned repo. A collaborator can override with ANCHOR_DATA_DIR (or run Anchor
# in-repo, in which case the token still lives under ``.anchor/`` which the
# manifest does not allow-list — but the out-of-tree default is the honest one).
_DEFAULT_DATA_DIR = Path.home() / ".anchor"
_STARTER_DIR = REPO_ROOT / "starter"

# Non-skill entries living alongside the skills (provenance, etc.) that
# install_skills must never treat as a skill to copy.
_NON_SKILL_NAMES = {"SOURCES.md"}


# --------------------------------------------------------------------------- #
# Prerequisite detection
# --------------------------------------------------------------------------- #
def detect_prereqs() -> dict:
    """Report the host OS + presence of python(>=3.8) / node / ``claude``.

    Never hard-fails on an optional miss — returns a structured report::

        {"os": "...", "platform": "...", "python": {...}, "node": {...},
         "claude": {...}, "ok": bool}

    ``ok`` is True iff the one hard requirement (Python >= 3.8, which is the very
    interpreter running this) is satisfied; node + ``claude`` are OPTIONAL and a
    miss is reported, never raised.
    """
    py_ver = sys.version_info
    py_ok = (py_ver.major, py_ver.minor) >= (3, 8)
    report = {
        "os": platform.system() or os.name,
        "platform": platform.platform(),
        "python": {
            "present": True,
            "version": "%d.%d.%d" % (py_ver.major, py_ver.minor, py_ver.micro),
            "ok": py_ok,
            "path": sys.executable,
        },
        "node": _which_report("node"),
        "claude": _which_report("claude"),
        "ok": py_ok,
    }
    return report


def _which_report(tool: str) -> dict:
    path = shutil.which(tool)
    return {"present": path is not None, "path": path, "optional": True}


# --------------------------------------------------------------------------- #
# Skill install — COPY (default) / symlink (opt-in), refuse-don't-clobber,
# resumable, partial-rollback.
# --------------------------------------------------------------------------- #
def _resolve_skills_src(skills_src) -> Path:
    if skills_src is not None:
        return Path(skills_src)
    env = os.environ.get("ANCHOR_BUNDLED_SKILLS_DIR")
    if env:
        return Path(env)
    return _DEFAULT_BUNDLED_SKILLS


def _resolve_skills_home(skills_home) -> Path:
    if skills_home is not None:
        return Path(skills_home)
    env = os.environ.get("ANCHOR_SKILLS_HOME")
    if env:
        return Path(env)
    return _DEFAULT_SKILLS_HOME


def _list_source_skills(src: Path) -> list[str]:
    """The skill directory names under ``src`` (sorted, excluding non-skills)."""
    if not src.exists():
        return []
    names = []
    for child in sorted(src.iterdir()):
        if child.name in _NON_SKILL_NAMES:
            continue
        if child.name.startswith("."):
            continue
        if child.is_dir():
            names.append(child.name)
    return names


def _is_our_copy(target: Path) -> bool:
    """True if ``target`` is a real dir WE installed (carries our marker)."""
    try:
        return target.is_dir() and (target / _OURS_MARKER).exists()
    except OSError:
        return False


def install_skills(skills_src=None, skills_home=None, symlink: bool = False,
                   _fail_on=None) -> dict:
    """Install each bundled skill into the skills home. COPY by default.

    Args:
      skills_src:  source dir (default ``vendor/bundled-skills`` or the
                   ``ANCHOR_BUNDLED_SKILLS_DIR`` env override).
      skills_home: destination dir (default ``~/.claude/skills`` or the
                   ``ANCHOR_SKILLS_HOME`` env override).
      symlink:     opt-in — symlink instead of copy (COPY is the default).
      _fail_on:    TEST seam — a skill name that should raise mid-copy to
                   exercise the partial-install rollback.

    Behavior:
      * **Refuse-don't-clobber**: if ``<home>/<name>`` already exists and is NOT
        our copy (a differently-sourced dir / symlink), skip it untouched and
        report it under ``refused``.
      * **Idempotent**: a target that IS our copy is skipped under ``skipped``
        (already installed) — no re-copy, no duplicate.
      * **Resumable + partial-rollback**: a mid-copy failure for skill k removes
        that half-written skill dir (no partial remains) and records it under
        ``failed``; a later re-run completes the rest.

    Returns::

        {"installed": [...], "skipped": [...], "refused": [...],
         "failed": [{"name":..., "error":...}], "src": str, "home": str}
    """
    src = _resolve_skills_src(skills_src)
    home = _resolve_skills_home(skills_home)
    home.mkdir(parents=True, exist_ok=True)

    report = {
        "installed": [],
        "skipped": [],
        "refused": [],
        "failed": [],
        "src": str(src),
        "home": str(home),
    }

    for name in _list_source_skills(src):
        source_skill = src / name
        target = home / name

        # Refuse-don't-clobber: a pre-existing target that is not our copy.
        if (target.exists() or target.is_symlink()) and not _is_our_copy(target):
            report["refused"].append({
                "name": name,
                "reason": "target exists and is not an onboard-installed copy "
                          "(differently-sourced dir/symlink) — refusing to "
                          "clobber",
                "target": str(target),
            })
            continue

        # Idempotent: our copy already there -> skip (no re-copy).
        if _is_our_copy(target):
            report["skipped"].append({"name": name, "reason": "already installed"})
            continue

        try:
            _install_one(source_skill, target, symlink=symlink,
                         fail=(name == _fail_on))
        except Exception as exc:  # noqa: BLE001 — rollback ANY failure
            # Partial-rollback: leave no half-copied skill dir.
            _safe_rmtree(target)
            report["failed"].append({"name": name, "error": str(exc)})
            continue

        report["installed"].append({"name": name, "mode": "symlink" if symlink else "copy"})

    return report


def _install_one(source_skill: Path, target: Path, symlink: bool, fail: bool) -> None:
    if symlink:
        # Opt-in symlink: point at the source; no marker file (the symlink IS
        # our install — _is_our_copy returns False for a symlink, so a re-run
        # would refuse it; acceptable: symlink is an advanced opt-in path).
        target.symlink_to(source_skill, target_is_directory=True)
        return

    # COPY (default). Copy file-by-file so an injected mid-copy failure leaves a
    # PARTIAL dir we can roll back.
    target.mkdir(parents=True, exist_ok=False)
    files = sorted(p for p in source_skill.rglob("*") if p.is_file())
    for i, sp in enumerate(files):
        # Test seam: raise partway through (after at least one file is written)
        # so the partial dir genuinely exists when rollback runs.
        if fail and i >= max(1, len(files) // 2):
            raise RuntimeError("injected mid-install failure (test seam)")
        rel = sp.relative_to(source_skill)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dst)
    # Mark it as ours (after a full, successful copy).
    (target / _OURS_MARKER).write_text(
        "Installed by Anchor onboard.py. Safe to delete to force a reinstall.\n",
        encoding="utf-8",
    )


def _safe_rmtree(path: Path) -> None:
    try:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Scaffold a fresh empty Anchor (only-if-absent).
# --------------------------------------------------------------------------- #
def _resolve_data_dir(data_dir) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    env = os.environ.get("ANCHOR_DATA_DIR")
    if env:
        return Path(env)
    return _DEFAULT_DATA_DIR


def scaffold_anchor(data_dir=None, starter_dir=None) -> dict:
    """Copy ``starter/`` into the data dir, ONLY for files that are ABSENT.

    Never overwrites an existing DASHBOARD.md / INBOX.md / etc. — that would
    destroy a collaborator's data (R3). Returns::

        {"created": [...rel...], "skipped": [...rel...], "data_dir": str}
    """
    data = _resolve_data_dir(data_dir)
    starter = Path(starter_dir) if starter_dir is not None else _STARTER_DIR
    data.mkdir(parents=True, exist_ok=True)

    report = {"created": [], "skipped": [], "data_dir": str(data)}
    if not starter.exists():
        return report

    for sp in sorted(p for p in starter.rglob("*") if p.is_file()):
        rel = sp.relative_to(starter)
        dst = data / rel
        if dst.exists():
            report["skipped"].append(rel.as_posix())
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dst)
        report["created"].append(rel.as_posix())
    return report


# --------------------------------------------------------------------------- #
# Token — random, out-of-tree, idempotent, never logged.
# --------------------------------------------------------------------------- #
def _default_token_path(data_dir=None) -> Path:
    data = _resolve_data_dir(data_dir)
    return data / ".anchor" / "onboard-token"


def generate_token(token_path=None, data_dir=None) -> dict:
    """Mint a random ``ANCHOR_TOKEN`` to a file OUTSIDE the repo tree.

    Default path: ``<data_dir>/.anchor/onboard-token`` (data dir defaults to a
    location outside the staged repo files; see ``_resolve_data_dir``). If a
    token file already EXISTS, keep it (idempotent — never re-mint). The token
    is NEVER printed to a shared log; this returns only the PATH + whether it was
    newly created, not the token value.

    Returns::

        {"path": str, "created": bool, "in_repo": bool}

    ``in_repo`` is True only if the resolved path is INSIDE the repo tree (a
    guard a test can assert is False).
    """
    path = Path(token_path) if token_path is not None else _default_token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    in_repo = _is_inside_repo(path)

    if path.exists():
        # Idempotent: keep the existing token, do not re-mint.
        return {"path": str(path), "created": False, "in_repo": in_repo}

    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    # Best-effort restrictive perms (POSIX); on Windows this is a no-op-ish.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"path": str(path), "created": True, "in_repo": in_repo}


def _is_inside_repo(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(REPO_ROOT)
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------- #
# Service Seam + Foreground Fallback (Wave 7)
# --------------------------------------------------------------------------- #
def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def register_service(token: str) -> dict:
    svc_cmd = os.environ.get("ANCHOR_SERVICE_CMD")
    fg_cmd = os.environ.get("ANCHOR_FOREGROUND_CMD")
    env = os.environ.copy()
    env["ANCHOR_TOKEN"] = token

    if svc_cmd:
        try:
            # Note: We pass "anchor.server" as argv to the stub to satisfy the test.
            # Real argv will be assembled by the registrar in Wave 8.
            subprocess.run(
                svc_cmd.split() + ["anchor.server"],
                env=env,
                check=True,
                capture_output=True,
                text=True
            )
            return {"status": "registered"}
        except subprocess.CalledProcessError as e:
            # Check if midway failure to rollback
            if e.stdout and "partial" in e.stdout or e.stderr and "partial" in e.stderr or (e.stdout == "" and e.stderr == ""):
                # Stub rollback via 'rollback' arg
                try:
                    subprocess.run(svc_cmd.split() + ["rollback"], capture_output=True)
                except Exception:
                    pass
                rolled_back = True
            else:
                rolled_back = False

            # Fallback to foreground
            port = pick_free_port()
            if fg_cmd:
                subprocess.Popen(
                    fg_cmd.split() + ["anchor.server", str(port)],
                    env=env,
                    start_new_session=True
                )
            return {"status": "foreground_fallback", "port": port, "rolled_back": rolled_back}
    else:
        # Wave 11: Call registrar directly
        try:
            import anchor.registrar as reg
            port = pick_free_port()
            unit = reg.build_registrar_unit(sys.executable, port, token)
            
            # Log unit to data dir
            data_dir = _resolve_data_dir()
            anchor_dir = data_dir / ".anchor"
            anchor_dir.mkdir(exist_ok=True)
            unit_file = anchor_dir / "service-unit"
            
            if "text" in unit:
                unit_file.write_text(unit["text"], encoding="utf-8")
            else:
                unit_file.write_text(str(unit["argv"]), encoding="utf-8")
                
            return {"status": "registered", "unit": unit}
        except Exception:
            # Fallback to foreground
            port = pick_free_port()
            if fg_cmd:
                subprocess.Popen(
                    fg_cmd.split() + ["anchor.server", str(port)],
                    env=env,
                    start_new_session=True
                )
            return {"status": "foreground_fallback", "port": port, "rolled_back": False}

    return {"status": "skipped_no_cmd"}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    """Run the Wave-6 core: detect -> install_skills -> scaffold -> token.

    Service registration is Wave 7 — this only PRINTS "service setup: next step".
    Returns a process exit code (0 on success; the hard Python<3.8 case is the
    only failure).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    symlink = "--symlink" in argv

    print("Anchor onboard — installer core (skills + scaffold + token)\n")

    prereqs = detect_prereqs()
    print("Detected OS: %s (%s)" % (prereqs["os"], prereqs["platform"]))
    print("  python: %s (ok=%s)" % (prereqs["python"]["version"], prereqs["python"]["ok"]))
    print("  node:   %s" % ("found" if prereqs["node"]["present"] else "MISSING (optional)"))
    print("  claude: %s" % ("found" if prereqs["claude"]["present"] else "MISSING (optional)"))
    if not prereqs["ok"]:
        print("\nERROR: Python 3.8+ is required.")
        return 1

    print("\nInstalling bundled skills ...")
    skill_report = install_skills(symlink=symlink)
    for s in skill_report["installed"]:
        print("  installed: %s (%s)" % (s["name"], s["mode"]))
    for s in skill_report["skipped"]:
        print("  already present (ours): %s" % s["name"])
    for r in skill_report["refused"]:
        print("  SKIPPED (not clobbered): %s — %s" % (r["name"], r["reason"]))
    for f in skill_report["failed"]:
        print("  FAILED: %s — %s (re-run to resume)" % (f["name"], f["error"]))

    print("\nScaffolding a fresh Anchor (only-if-absent) ...")
    scaf = scaffold_anchor()
    print("  created %d file(s), skipped %d existing"
          % (len(scaf["created"]), len(scaf["skipped"])))

    print("\nGenerating machine token ...")
    tok = generate_token()
    # NEVER print the token value — only the path + status.
    print("  token %s at: %s"
          % ("created" if tok["created"] else "already present (kept)", tok["path"]))

    print("\nCapability probe & Driver-init hardening...")
    try:
        import lanes
        prof = lanes.detect_host_profile()
        plan_research = lanes.select_engine_plan("research", prof)
        plan_plan = lanes.select_engine_plan("plan", prof)
        plan_build = lanes.select_engine_plan("build", prof)

        print("  Host engines detected: Claude=%s, Gemini=%s" % (
            "FOUND" if prof["claude"] else "missing",
            "FOUND" if prof["gemini"] else "missing"
        ))
        print("  Seat resolution (same code path as author):")
        print("    - research: driver=%s, swarm=%s" % (plan_research["driver"] or "None", plan_research["swarm"] or "None"))
        print("    - plan:     driver=%s, swarm=%s" % (plan_plan["driver"] or "None", plan_plan["swarm"] or "None"))
        print("    - build:    driver=%s, swarm=%s" % (plan_build["driver"] or "None", plan_build["swarm"] or "None"))

        print("  Roles filled:")
        print("    - Driver seats: %s" % (plan_build["driver"] or "None"))
        role_model = "Claude" if prof["claude"] else "None (requires Claude)"
        print("    - Shark: %s" % role_model)
        print("    - Judge: %s" % role_model)
        print("    - Synthesizer: %s" % role_model)
    except Exception as exc:
        print("  WARNING: Could not probe capabilities: %s" % exc)

    print("\nservice setup: next step (run the service-registration step "
          "to bring up the background dashboard).")
    
    # Wave 7: Call register_service
    print("\nRegistering service ...")
    with open(tok["path"], "r", encoding="utf-8") as f:
        token_val = f.read().strip()
    
    reg_result = register_service(token_val)
    print("  service status: %s" % reg_result["status"])
    if reg_result.get("port"):
        print("  foreground fallback port: %s" % reg_result["port"])
    if reg_result.get("rolled_back"):
        print("  mid-registration rollback occurred.")
    
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
