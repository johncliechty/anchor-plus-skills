import sys
import shutil
import platform
import os
import subprocess
from pathlib import Path

#: First-party modules that are ALLOWED to be absent on an install — each is a
#: documented deliberate exclusion whose consumers degrade safely (lazy
#: try/except imports). Mirrors distro._OPTIONAL_FIRST_PARTY.
#: Modules whose ABSENCE is intentional, so doctor must not call the install
#: broken over them. THE BUILDER OWNS THIS LIST. ``distro._OPTIONAL_FIRST_PARTY``
#: is what the fail-closed import-closure gate actually enforces at build time,
#: each entry carrying a written justification; this module derives from it
#: rather than keeping a second copy.
#:
#: WHY (found by share_sandbox G6a on the v1.2 line, 2026-08): this WAS a
#: hand-maintained duplicate — ``{"update_transaction", "tools"}`` — and it
#: drifted. The builder grew declarations for the steward-chamber modules
#: (``chamber_mockup_diff`` et al., lazily imported inside try/except and
#: honestly degrading) while doctor did not, so a CORRECTLY-built package made
#: doctor announce "This install is INCOMPLETE — re-download". Doctor is the
#: FIRST thing the consumer CLAUDE.md tells a collaborator to run, so the one
#: cheap deterministic check told every new user their good install was broken.
#: Two lists disagreeing is the same root cause as the v1.1.x two-builders
#: incident: one must win, and it is the one the gate enforces.
_FALLBACK_OPTIONAL_ABSENT = frozenset({"update_transaction", "tools"})


def _optional_absent():
    """The builder's declared-optional set, with an honest fallback.

    Doctor must stay useful on a PARTIAL install (that is its whole job), so a
    missing or broken ``distro`` degrades to the historical literal rather than
    raising — but on any real package ``distro.py`` is on the manifest and the
    builder's list wins.
    """
    try:
        import distro
        declared = getattr(distro, "_OPTIONAL_FIRST_PARTY", None)
        if declared:
            return frozenset(declared) | _FALLBACK_OPTIONAL_ABSENT
    except Exception:
        pass
    return _FALLBACK_OPTIONAL_ABSENT


OPTIONAL_ABSENT = _optional_absent()

#: Import names that are OPTIONAL EXTRAS (probed separately, never counted as
#: a missing first-party module): the winpty native dep is the [terminal]
#: extra; pytest is dev-only.
_EXTRA_NAMES = frozenset({"winpty", "pytest"})


def get_node_version():
    node = shutil.which("node")
    if not node:
        return None
    try:
        proc = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return proc.stdout.strip()
    except Exception:
        return None


def find_missing_modules(root=None):
    """Deterministically find first-party modules this install is MISSING.

    v1.1.3 share-fix: this is the automated form of the audit the 2026-07-30
    collaborator had to burn Claude tokens performing by hand. Every top-level
    import (module-scope AND lazy — ``ast.walk`` sees both) in every root
    ``.py`` file is resolved with ``importlib.util.find_spec``; a name that
    resolves nowhere and is not a declared-optional absence is a REAL gap that
    will ModuleNotFoundError at runtime. Pure stdlib, no model call, ~1s.

    Returns ``{missing_name: [importing_file, ...]}`` (empty == closed).
    """
    import ast
    import importlib.util

    base = Path(root) if root is not None else Path(__file__).resolve().parent
    stdlib = frozenset(getattr(sys, "stdlib_module_names", ()) or ())
    missing = {}
    checked = {}
    for py in sorted(base.glob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                names.add(node.module.split(".", 1)[0])
        for name in names:
            if (not name or name in stdlib or name in OPTIONAL_ABSENT
                    or name in _EXTRA_NAMES):
                continue
            if name not in checked:
                try:
                    checked[name] = importlib.util.find_spec(name) is not None
                except Exception:
                    checked[name] = False
            if not checked[name]:
                missing.setdefault(name, []).append(py.name)
    return missing


def probe_pywinpty():
    """The optional [terminal] extra. Absent → terminals degrade (not fatal)."""
    if os.name != "nt":
        return {"present": False, "applicable": False}
    try:
        import importlib.util
        present = importlib.util.find_spec("winpty") is not None
    except Exception:
        present = False
    return {"present": present, "applicable": True}


def probe_token(data_dir=None):
    """Where the onboard-minted token lives, and whether one exists."""
    base = Path(data_dir) if data_dir else (
        Path(os.environ.get("ANCHOR_DATA_DIR") or (Path.home() / ".anchor")))
    path = base / ".anchor" / "onboard-token"
    env_set = bool((os.environ.get("ANCHOR_TOKEN") or "").strip())
    try:
        file_present = path.is_file() and bool(
            path.read_text(encoding="utf-8").strip())
    except OSError:
        file_present = False
    return {"file_present": file_present, "env_set": env_set,
            "path": str(path)}


def probe_server(url="http://127.0.0.1:8777/api/status", timeout=2.0):
    """Is a local Anchor server answering? Loopback only; never raises."""
    from urllib.request import Request, urlopen
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode() or 0)
            return {"up": 200 <= code < 500, "status_code": code}
    except Exception as exc:
        return {"up": False, "error": str(exc)[:120]}


def run_doctor(argv=None):
    print("Anchor Doctor — System Check\n")
    issues = []
    notes = []

    # Python
    py_ver = sys.version_info
    if (py_ver.major, py_ver.minor) < (3, 8):
        issues.append(f"Python version is too old. Requires >= 3.8. Current: {py_ver.major}.{py_ver.minor}.{py_ver.micro}. Install from python.org.")

    # ── Missing first-party modules (the 2026-07-30 incident class) ─────────
    missing = find_missing_modules()
    for name, importers in sorted(missing.items()):
        issues.append(
            "Module '%s' is MISSING from this install (imported by %s). "
            "This install is INCOMPLETE — re-download the v1.1.3+ package "
            "(older packages shipped without required modules)."
            % (name, ", ".join(sorted(set(importers))[:5])))

    # ── pywinpty (optional [terminal] extra; degrade, not fatal) ────────────
    pw = probe_pywinpty()
    if pw["applicable"] and not pw["present"]:
        issues.append(
            'pywinpty (ConPTY terminal backend) is not installed — in-browser '
            'terminals will report "real terminal unavailable". Fix: '
            'pip install "pywinpty>=2.0" (onboard v1.1.3+ does this for you).')

    # Node
    node_ver = get_node_version()
    if not node_ver:
        issues.append("Node.js is MISSING. It is required for running Crucible/Foreman. Install Node.js from nodejs.org.")
    else:
        try:
            ver_num = int(node_ver.lstrip('v').split('.')[0])
            if ver_num < 16:
                issues.append(f"Node.js version is too old. Requires >= 16. Current: {node_ver}. Install from nodejs.org.")
        except Exception:
            pass

    # git (worktree-isolated sessions need it)
    if not shutil.which("git"):
        issues.append("git is MISSING. Session worktrees and doc persistence "
                      "require it. Install from git-scm.com.")

    # Capability Probe / CLIs
    claude = shutil.which("claude")
    gemini = shutil.which("agy") or shutil.which("gemini")

    if not claude and not gemini:
        issues.append("No Claude or Gemini CLI detected. Install via npm (e.g. npm install -g @anthropic-ai/claude-code).")

    # ── Token + server (informational — a fresh install starts both later) ──
    tok = probe_token()
    if tok["file_present"] or tok["env_set"]:
        notes.append("Access token: present (%s)." % (
            "env" if tok["env_set"] else "file"))
    else:
        notes.append("Access token: none minted yet — run onboard "
                     "(python -m share_onboard) to create one.")
    srv = probe_server()
    if srv.get("up"):
        notes.append("Anchor server: UP on 127.0.0.1:8777.")
    else:
        notes.append("Anchor server: not running — start it with: "
                     "python launch_anchor_dashboard.py")

    # Interrupted update transaction
    try:
        import update_transaction
        txn = update_transaction.UpdateTransaction()
        marker = txn.read_marker()
        if marker is not None:
            phase = marker.get("phase", 0)
            issues.append(f"Interrupted update transaction detected at phase {phase}.\n  To resume or rollback, run: python anchor.py update")
    except Exception:
        pass

    if issues:
        print("Doctor found the following issues to fix:\n")
        for i, iss in enumerate(issues, 1):
            print(f"{i}. {iss}")
        print("\nAll prescriptions above use standard environment installs or anchor commands — NO manual git or openssl surgery is required.")
    else:
        print("All prerequisites met. System is healthy.")
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"- {n}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(run_doctor())
