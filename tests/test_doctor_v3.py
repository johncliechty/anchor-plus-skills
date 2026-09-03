"""Anchor Doctor UI V3 — STUB GATE (planning/anchor-doctor-ui/handoff).

Wave 2 — "The doctor agentic session backend":
 - POST /api/doctor/session_start starts ONE interactive doctor session on the
   EXISTING PTY substrate (stubbed: ANCHOR_PTY_BACKEND=stub — never a real
   ConPTY / live model), registered under the reserved ``__doctor__``
   pseudo-project, cwd = the live Anchor folder (NO worktree), engine CLI in
   READ-ONLY plan permission mode;
 - the one-time seed contains the latest health report (graceful "no reports
   yet" when absent), fresh doctor.py output, the severity rule, and a
   capability list — ASCII-safe;
 - engine honesty per the W8 model-flex seams (ANCHOR_CLAUDE_AVAILABLE /
   ANCHOR_GEMINI_AVAILABLE): claude-only → claude drives; gemini-only → gemini
   drives; neither → an honest ``unavailable`` status, never a crash and never
   a session;
 - idempotent: a second session_start while one doctor session is LIVE
   attaches to it (never stacks a duplicate);
 - ``__doctor__`` is FILTERED from the term_sessions projection (the
   dashboard/board repopulate hook) — even when queried directly;
 - 401-before-substance: with ANCHOR_TOKEN configured, a tokenless POST gets
   401 from the default-deny middleware and NO session/PTY is ever created.

Wave 1 — "Rip out the API-key backend + swept-in scratch":
 - the V2 Gemini API-key agent, its tests/mocks, the standalone-product mock
   page, and the scratch files swept into master by 65e93e1 are DELETED and
   stay deleted;
 - NO module in the repo imports the third-party Gemini SDK (the repo is
   stdlib-only; distro.py's import scan is the broader enforcement, this gate
   pins the specific V2 regression);
 - POST /api/doctor/run no longer routes to a Gemini API wrapper — the V2
   handler is gone entirely (an unmatched POST falls through to the 404), and
   anchor_gui no longer references the deleted agent script or spawns anything
   synchronously for the doctor surface.

All model seams are stubbed suite-wide by tests/conftest.py
(ANCHOR_PTY_BACKEND=stub + ANCHOR_RUNNER_CMD -> tests/fake_claude.py); no test
here spawns a live model, a real ConPTY, or the :8777 service.

NOTE ON THIS FILE: it ships via the manifest glob (tests/test_*.py) and the
wave's done-when is "zero repo references" to the forbidden SDK — so, exactly
like tests/test_distro_scan.py does for the personal email, the forbidden
module name and the deleted agent-script name are ASSEMBLED AT RUNTIME, never
stored as contiguous literals in this file's source.
"""
import importlib
import io
import json
import re
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()

# The forbidden third-party Gemini SDK module, assembled at runtime so this
# file itself adds no repo reference to it.
_GEMINI_SDK = "google" + "." + "generat" + "iveai"

# The deleted V2 agent script's module name, likewise assembled.
_AGENT_MODULE = "anchor_" + "doctor_" + "agent"

# Everything wave 1 deletes, repo-relative (POSIX separators).
_DELETED = [
    _AGENT_MODULE + ".py",
    "test_doctor.py",
    "test/test_doctor_ui.mjs",
    "prototypes.html",
    "test.py",
    "test_quote.js",
    "test_agy_out.txt",
    "touch_loop.ps1",
]

# Directories never scanned for imports: VCS/data/caches, frozen archives, and
# vendored third-party assets (same exclusion idiom as distro.py's scan).
_SKIP_DIRS = {".git", ".anchor", "__pycache__", "_archive", "_mockups",
              "node_modules", "vendor"}

# An import statement pulling in the `google` namespace package in ANY form
# (spelled `google.<sdk>` here so this file honors its own contiguous-literal
# ban, per the NOTE in the module docstring):
#   import google.<sdk> [as x] / from google.<sdk>[.sub] import y
#   from google import <sdk> / import google
_GOOGLE_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+google(?:[.\s]|$)|from\s+google(?:[.\s]))",
    re.MULTILINE,
)


def _repo_python_files():
    """Every .py file in the repo outside the skipped dirs."""
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield rel.as_posix(), path


# ── Wave 1: the deleted files STAY deleted ───────────────────────────────────

@pytest.mark.parametrize("rel", _DELETED)
def test_deleted_file_stays_deleted(rel):
    assert not (REPO_ROOT / rel).exists(), (
        f"{rel} was deleted in doctor-V3 wave 1 and must stay deleted")


# ── Wave 1: no module in the repo imports the Gemini SDK ─────────────────────

def test_no_module_imports_gemini_sdk():
    offenders = []
    for rel, path in _repo_python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _GEMINI_SDK in text or _GOOGLE_IMPORT_RE.search(text):
            offenders.append(rel)
    assert offenders == [], (
        f"module(s) reference/import the forbidden Gemini SDK: {offenders}")


def test_no_module_references_deleted_agent_script():
    """The deleted V2 agent module is referenced by NO repo .py file (this gate
    file holds only assembled fragments, so it passes its own scan)."""
    offenders = []
    for rel, path in _repo_python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _AGENT_MODULE in text:
            offenders.append(rel)
    assert offenders == [], (
        f"module(s) still reference the deleted V2 agent script: {offenders}")


# ── Wave 1: /api/doctor/run no longer routes to a Gemini API wrapper ─────────

def _post(gui, path, body_dict):
    """Drive anchor_gui's real do_POST without a socket (suite FakeHandler
    idiom) and return (status_code, decoded-JSON-or-None)."""

    class FakeHandler(gui.AnchorHandler):
        def __init__(self):
            self.path = path
            body_bytes = json.dumps(body_dict).encode("utf-8")
            self.headers = {"Content-Length": str(len(body_bytes))}
            self.rfile = io.BytesIO(body_bytes)
            self.wfile = io.BytesIO()
            self.response_code = None

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            pass

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    handler = FakeHandler()
    handler.do_POST()
    raw = handler.wfile.getvalue()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = None
    return handler.response_code, payload


def test_api_doctor_run_is_gone_404s_and_spawns_nothing(monkeypatch):
    """POST /api/doctor/run is an UNKNOWN endpoint now (404) — it neither
    spawns a subprocess nor blocks the request thread on a child process."""
    import subprocess

    import anchor_gui
    import paths as _paths

    spawned = []
    real_popen = subprocess.Popen

    class _TrappingPopen(real_popen):
        def __init__(self, *args, **kwargs):
            spawned.append(args[0] if args else kwargs.get("args"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _TrappingPopen)

    # Hermetic against the ambient env: supply the configured token (None when
    # auth is disabled — then it is simply ignored).
    body = {"init": True, "token": _paths.expected_token()}
    code, payload = _post(anchor_gui, "/api/doctor/run", body)

    assert code == 404, (code, payload)
    assert payload is not None and payload.get("ok") is False
    assert "unknown" in str(payload.get("error", "")).lower()
    assert spawned == [], f"/api/doctor/run spawned a process: {spawned}"

    # The healthcheck arm of the old handler is equally gone (no synchronous
    # 75s anchor_healthcheck.py spawn in the request thread).
    code2, payload2 = _post(
        anchor_gui, "/api/doctor/run?cmd=healthcheck",
        {"token": _paths.expected_token()})
    assert code2 == 404, (code2, payload2)
    assert spawned == [], f"cmd=healthcheck spawned a process: {spawned}"


def test_anchor_gui_source_has_no_doctor_agent_spawn_path():
    """Source-level pin: anchor_gui carries no handler branch for the V2
    doctor endpoint and no reference to the deleted agent script."""
    src = (REPO_ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert _AGENT_MODULE not in src
    assert _GEMINI_SDK not in src
    # The old POST branch compared _path_only against the endpoint literal;
    # with the handler removed, no code path matches it any more.
    assert '_path_only == "/api/doctor/run"' not in src
    # The /doctor page no longer fires client-side calls at the dead endpoint.
    assert "fetch('/api/doctor/run" not in src


# ═════════════════════════════════════════════════════════════════════════════
# Wave 2 — the doctor agentic session backend
# ═════════════════════════════════════════════════════════════════════════════
#
# Hermetic: temp data dir + stub PTY + the fake runner + a temp worktree base —
# NEVER :8777 / real data / a live model / a real ConPTY. The reserved
# ``__doctor__`` pseudo-project needs no git repo (no worktree is ever created
# for it — the whole point).

DOCTOR_PID = "__doctor__"


@pytest.fixture
def denv(tmp_path, monkeypatch):
    """Temp data dir + stub PTY + fake runner, with the session stack reloaded
    so every module resolves against this test's environment."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_CLAUDE_AVAILABLE", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_AVAILABLE", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "brownfield_scan", "effort_view",
                "deliverables", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import pty_manager
    import route_table
    import session_registry
    import terminal_session
    yield {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "pty": pty_manager, "routes": route_table, "data": data,
        "wbase": wbase,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _claude_only(monkeypatch):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "0")


def _write_report(data_dir, name="2026-07-17.md",
                  body="# Anchor Health Check\nHEALTHREPORT-MARKER all clear\n"):
    rd = data_dir / "health_reports"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / name).write_text(body, encoding="utf-8")


class _CaptureGet:
    """Minimal stand-in for a GET request against a module-level handler."""

    def __init__(self, path):
        self.path = path
        self.sent = []

    def _send_json(self, data, code=200):
        self.sent.append((code, data))


def _doctor_records(reg):
    return reg.list_sessions(project_id=DOCTOR_PID)


# ── session starts stubbed, seeded, read-only, no worktree ───────────────────

def test_doctor_session_start_stubbed_seeded_readonly(denv, monkeypatch):
    _claude_only(monkeypatch)
    _write_report(denv["data"])
    code, payload = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code == 200, payload
    assert payload["ok"] is True
    assert payload["attached"] is False
    sess = payload["session"]
    sid = sess["session_id"]
    assert sid
    assert sess["project_id"] == DOCTOR_PID
    assert sess["backend"] == "claude"
    assert sess["status"] == denv["reg"].STATUS_RUNNING
    assert sess["mode"] == denv["ts"].DOCTOR_MODE_DIAGNOSE
    assert sess["posture"] == denv["ts"].DOCTOR_POSTURE_READ_ONLY
    # SAFE projection: never worktree_path / branch / seed text.
    assert "worktree_path" not in sess and "branch" not in sess

    rec = denv["reg"].get_session(sid)
    assert rec is not None and rec.get("seeded") is True
    assert rec["doctor_mode"] == denv["ts"].DOCTOR_MODE_DIAGNOSE
    assert rec["doctor_posture"] == denv["ts"].DOCTOR_POSTURE_READ_ONLY
    seed = rec.get("seed_text", "")
    # Seed content: latest report + fresh doctor output + severity rule +
    # capability list — and ASCII-safe end to end.
    assert "HEALTHREPORT-MARKER" in seed
    assert "doctor.py system check" in seed
    assert "CORRECTNESS" in seed and "PERFORMANCE" in seed
    assert "What you can do in this session" in seed
    seed.encode("ascii")  # raises if any non-ASCII byte survived

    # The PTY is the stub backend, launched in READ-ONLY plan permission mode
    # with cwd = the live Anchor folder — and NO worktree was created.
    child = denv["pty"]._LIVE[sid]
    argv = child.cmd
    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert Path(child.cwd).resolve() == denv["data"].resolve()
    assert not denv["wbase"].exists() or not any(denv["wbase"].iterdir()), \
        "a doctor session must never create a worktree"


def test_doctor_session_start_no_reports_yet_is_graceful(denv, monkeypatch):
    _claude_only(monkeypatch)
    # health_reports/ exists but is empty (ensure_data_dirs made it).
    code, payload = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code == 200 and payload["ok"] is True
    rec = denv["reg"].get_session(payload["session"]["session_id"])
    assert "No health reports yet" in rec.get("seed_text", "")


# ── idempotent: a live doctor session is attached to, never duplicated ───────

def test_doctor_session_start_attaches_never_stacks(denv, monkeypatch):
    _claude_only(monkeypatch)
    code1, p1 = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code1 == 200 and p1["ok"] is True and p1["attached"] is False
    sid1 = p1["session"]["session_id"]

    code2, p2 = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code2 == 200 and p2["ok"] is True
    assert p2["attached"] is True
    assert p2["session"]["session_id"] == sid1

    running = denv["reg"].list_sessions(project_id=DOCTOR_PID,
                                        status=denv["reg"].STATUS_RUNNING)
    assert len(running) == 1, "a second start must never stack a duplicate"


def test_doctor_same_key_concurrent_start_is_singleflight(denv, monkeypatch):
    _claude_only(monkeypatch)
    barrier = threading.Barrier(3)
    results = []
    errors = []

    def _start():
        barrier.wait()
        try:
            results.append(denv["ts"].start_doctor_session(
                seed_context="doctor concurrency fixture", backend="claude"))
        except Exception as exc:  # surfaced below with full repr
            errors.append(exc)

    workers = [threading.Thread(target=_start) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive(), "Doctor start lock deadlocked"

    assert errors == []
    assert len(results) == 2
    assert len({rec["session_id"] for rec, _attached in results}) == 1
    assert sorted(attached for _rec, attached in results) == [False, True]
    assert len(denv["pty"].live_sessions()) == 1


def test_doctor_reuse_key_separates_diagnose_from_resolve(denv, monkeypatch):
    """Mode and posture are part of reuse identity: read-only Diagnose can
    never attach to write-enabled Resolve, or the reverse."""
    _claude_only(monkeypatch)
    code_d, diagnose = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "claude"})
    assert code_d == 200 and diagnose["ok"] is True
    assert diagnose["attached"] is False

    issue = {"message": "repair the fixture", "component": "doctor-test"}
    code_r, resolve = _post(
        denv["gui"], "/api/doctor/session_start",
        {"backend": "claude", "resolve": True, "issue": issue})
    assert code_r == 200 and resolve["ok"] is True
    assert resolve["attached"] is False
    assert resolve["session"]["session_id"] != diagnose["session"]["session_id"]
    assert resolve["session"]["mode"] == denv["ts"].DOCTOR_MODE_RESOLVE
    assert resolve["session"]["posture"] == \
        denv["ts"].DOCTOR_POSTURE_WRITE_ENABLED

    d_child = denv["pty"]._LIVE[diagnose["session"]["session_id"]]
    r_child = denv["pty"]._LIVE[resolve["session"]["session_id"]]
    assert "--permission-mode" in d_child.cmd
    assert "--permission-mode" not in r_child.cmd

    # Each repeated request returns only its own exact-key session even though
    # the other posture remains live and the Resolve row is newer.
    _, diagnose_again = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "claude"})
    _, resolve_again = _post(
        denv["gui"], "/api/doctor/session_start",
        {"backend": "claude", "resolve": True, "issue": issue})
    assert diagnose_again["attached"] is True
    assert diagnose_again["session"]["session_id"] == \
        diagnose["session"]["session_id"]
    assert resolve_again["attached"] is True
    assert resolve_again["session"]["session_id"] == \
        resolve["session"]["session_id"]


def test_doctor_reuse_key_checks_backend_and_posture(denv, monkeypatch):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    _, claude = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "claude"})
    _, gemini = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "gemini"})
    assert claude["attached"] is False and gemini["attached"] is False
    assert claude["session"]["session_id"] != gemini["session"]["session_id"]

    # Even a row whose mode/backend match is not reusable if its durable
    # posture does not. This simulates legacy/corrupt metadata fail-closed.
    sid = claude["session"]["session_id"]
    denv["reg"].update_session(
        sid, doctor_posture=denv["ts"].DOCTOR_POSTURE_WRITE_ENABLED)
    _, fresh = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "claude"})
    assert fresh["attached"] is False
    assert fresh["session"]["session_id"] != sid
    assert fresh["session"]["posture"] == \
        denv["ts"].DOCTOR_POSTURE_READ_ONLY


def test_doctor_stale_running_row_is_reconciled_not_attached(denv, monkeypatch):
    """A registry row claiming RUNNING with a dead PTY is honestly re-statused
    (never 'attached' to); the next start opens a FRESH live session."""
    _claude_only(monkeypatch)
    _, p1 = _post(denv["gui"], "/api/doctor/session_start", {})
    sid1 = p1["session"]["session_id"]
    denv["pty"].kill(sid1)  # PTY dies; registry row still says running

    code2, p2 = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code2 == 200 and p2["ok"] is True
    assert p2["attached"] is False
    assert p2["session"]["session_id"] != sid1
    stale = denv["reg"].get_session(sid1)
    assert stale["status"] in denv["reg"].TERMINAL_STATUSES


# ── engine honesty (W8 model-flex seams) ─────────────────────────────────────

def test_doctor_engine_gemini_only_drives_on_gemini(denv, monkeypatch):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    code, payload = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code == 200 and payload["ok"] is True, payload
    sess = payload["session"]
    assert sess["backend"] == "gemini"
    # Read-only posture on the gemini CLI too.
    child = denv["pty"]._LIVE[sess["session_id"]]
    assert "--approval-mode" in child.cmd
    assert child.cmd[child.cmd.index("--approval-mode") + 1] == "plan"


def test_doctor_diagnose_unsupported_engine_fails_closed_before_pty(
        denv, monkeypatch):
    """Grok is selectable elsewhere, but Doctor must not guess a read-only
    flag. An unsupported Diagnose contract refuses before any paid PTY starts."""
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    code, payload = _post(
        denv["gui"], "/api/doctor/session_start", {"backend": "grok"})
    assert code == 400
    assert payload["ok"] is False
    assert "no explicitly tested read-only argv contract" in payload["error"]
    assert _doctor_records(denv["reg"]) == []
    assert denv["pty"].live_sessions() == []


def test_doctor_truthy_resolve_string_cannot_enable_write_posture(
        denv, monkeypatch):
    _claude_only(monkeypatch)
    code, payload = _post(
        denv["gui"], "/api/doctor/session_start",
        {"backend": "claude", "resolve": "false"})
    assert code == 200 and payload["ok"] is True
    assert payload["session"]["mode"] == denv["ts"].DOCTOR_MODE_DIAGNOSE
    assert payload["session"]["posture"] == denv["ts"].DOCTOR_POSTURE_READ_ONLY
    child = denv["pty"]._LIVE[payload["session"]["session_id"]]
    assert "--permission-mode" in child.cmd


def test_doctor_engine_neither_is_honest_unavailable(denv, monkeypatch):
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "0")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "0")
    code, payload = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code == 200, payload  # an honest status, never a crash
    assert payload["ok"] is False
    assert payload["status"] == "unavailable"
    assert payload.get("reason")
    assert payload.get("session") is None
    assert _doctor_records(denv["reg"]) == [], \
        "an unavailable host must not mint a session"
    assert denv["pty"].live_sessions() == []


# ── __doctor__ is filtered from the term_sessions projection ─────────────────

def test_doctor_filtered_from_term_sessions_listing(denv, monkeypatch):
    _claude_only(monkeypatch)
    _, p1 = _post(denv["gui"], "/api/doctor/session_start", {})
    assert p1["ok"] is True
    # Queried directly by the reserved pseudo-project id…
    cap = _CaptureGet("/api/rnd/term_sessions?project_id=" + DOCTOR_PID)
    denv["gui"].handle_term_sessions(cap, cap.path, None)
    code, data = cap.sent[-1]
    assert code == 200 and data["ok"] is True
    assert data["sessions"] == []
    # …and in the unscoped (all-projects) listing.
    cap2 = _CaptureGet("/api/rnd/term_sessions")
    denv["gui"].handle_term_sessions(cap2, cap2.path, None)
    _, data2 = cap2.sent[-1]
    assert all(s.get("project_id") != DOCTOR_PID
               for s in data2["sessions"])


# ── 401-before-substance on the new endpoint ─────────────────────────────────

def test_doctor_session_start_401_before_substance(denv, monkeypatch):
    _claude_only(monkeypatch)
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    code, payload = _post(denv["gui"], "/api/doctor/session_start", {})
    assert code == 401, payload
    assert payload["ok"] is False
    assert "unauthorized" in str(payload.get("error", "")).lower()
    # No substance: nothing was registered, no PTY was started.
    assert _doctor_records(denv["reg"]) == []
    assert denv["pty"].live_sessions() == []
    # The SAME request WITH the token is served.
    code2, p2 = _post(denv["gui"], "/api/doctor/session_start",
                      {"token": "tok-123"})
    assert code2 == 200 and p2["ok"] is True, p2


# ── structural pin: the route row is declared token + migrated ───────────────

def test_doctor_session_start_route_declared_token_migrated(denv):
    route = denv["routes"].match("POST", "/api/doctor/session_start")
    assert route is not None
    assert route.auth == denv["routes"].AUTH_TOKEN
    assert route.migrated is True
    assert route.handler == "handle_doctor_session_start"
    assert route.handler in denv["gui"]._MIGRATED_HANDLERS


# ═════════════════════════════════════════════════════════════════════════════
# Wave 3 — the /doctor page in Anchor's own style + background diagnostics
# ═════════════════════════════════════════════════════════════════════════════
#
# The page shows REAL stat cards only (status per the severity rule / last-run
# date + days ago / report count), a reports list of the ACTUAL files, and the
# Wave-2 agentic terminal. "Run diagnostics" launches anchor_healthcheck.py as
# a BACKGROUND process tailed cursor-stably (never the V2 75s synchronous
# block). Empty/corrupt health_reports/ renders honestly. The V2 fabrications
# (fake disk-usage card, fake SVG chart, dead nav, literal {placeholder}
# f-string bug, hardcoded "68%") are regression-pinned OUT.

import sys
import textwrap
import time as _time


def _get(gui, path, headers=None):
    """Drive anchor_gui's real do_GET without a socket; return (code, body)."""

    class FakeGetHandler(gui.AnchorHandler):
        def __init__(self):
            self.path = path
            self.headers = dict(headers or {})
            self.wfile = io.BytesIO()
            self.response_code = None

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            pass

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    handler = FakeGetHandler()
    handler.do_GET()
    return handler.response_code, handler.wfile.getvalue().decode(
        "utf-8", errors="replace")


def _get_json(gui, path, headers=None):
    code, raw = _get(gui, path, headers=headers)
    try:
        return code, json.loads(raw)
    except Exception:
        return code, None


def _report_body(status_ok=True, warnings=(), marker="HEALTHREPORT-MARKER"):
    """A body in anchor_healthcheck.Report.write's real format."""
    lines = [
        "# Anchor Health Report — 2026-07-17",
        "",
        "Status: %s" % ("OK" if status_ok else "ISSUES FOUND"),
        "Run time: 12.3s (05:00:01)",
        "",
        "## Checks",
        "- + file system integrity  (%s)" % marker,
        "",
        "## Issues",
    ]
    lines.append("(none)" if status_ok else "- [endpoint] GET / returned 500")
    lines.extend(["", "## Warnings (non-blocking)"])
    if warnings:
        lines.extend("- %s" % w for w in warnings)
    else:
        lines.append("(none)")
    lines.extend(["", "## Auto-fixes applied", "(none)", ""])
    return "\n".join(lines)


# ── the page renders REAL stats in Anchor's idiom ────────────────────────────

def test_doctor_page_green_renders_real_stats(denv):
    today = __import__("datetime").date.today().isoformat()
    _write_report(denv["data"], name=today + ".md", body=_report_body())
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "Anchor" in html and "Doctor" in html
    assert "Healthy" in html                    # green per the severity rule
    assert today in html                        # the REAL last-run date
    assert "today" in html                      # days-ago from the filename
    assert 'id="cardCount">1<' in html          # the REAL on-disk count
    # The row links to the ACTUAL file.
    assert "/doctor/report?name=" + today + ".md" in html


def test_doctor_page_red_when_issues_found(denv):
    _write_report(denv["data"], name="2026-07-16.md",
                  body=_report_body(status_ok=False))
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "Issues found" in html
    assert "Healthy" not in html


def test_doctor_page_yellow_when_only_warnings(denv):
    # Severity rule: a non-blocking PERFORMANCE warning must NOT read as red.
    _write_report(denv["data"], name="2026-07-16.md",
                  body=_report_body(status_ok=True,
                                    warnings=["[home page render] 6.1s"]))
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "Warnings" in html
    assert "Issues found" not in html


def test_doctor_page_no_fabricated_values_regression(denv):
    """The V2 bug classes stay dead: no literal {placeholder} text, no
    hardcoded fake values, no fake chart, no dead nav, no Gemini SDK."""
    _write_report(denv["data"], name="2026-07-16.md", body=_report_body())
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    # The V2 f-string bug rendered "{fname}" literally into the page.
    assert re.findall(r"\{[a-z_]+\}", html) == [], \
        "literal {placeholder} text leaked into the rendered /doctor page"
    assert "68%" not in html                    # the fake disk-usage value
    assert "Disk Usage" not in html             # the fabricated card
    assert "polyline" not in html.lower()       # the fake SVG chart
    assert "fonts.googleapis.com" not in html   # standalone-product mock look
    for dead_nav in ("Scan History", "Schedule Scan"):
        assert dead_nav not in html, f"dead V2 control still rendered: {dead_nav}"
    assert _GEMINI_SDK not in html


def test_doctor_page_empty_reports_is_graceful(denv):
    # health_reports/ exists but is empty — honest empty states, no 500.
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "No reports yet" in html
    assert "No health reports on disk yet" in html
    assert 'id="cardCount">0<' in html
    assert "Traceback" not in html


def test_doctor_page_corrupt_report_is_graceful(denv):
    rd = denv["data"] / "health_reports"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "2026-07-01.md").write_bytes(b"\x00\xff\xfe not a report \x9d")
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "Unreadable report" in html          # honest 'unknown', never a guess
    assert "Traceback" not in html


def test_doctor_page_terminal_wired_to_wave2_session(denv):
    """The xterm panel attaches to the Wave-2 doctor session over the
    EXISTING transports (live attach is the Playwright sign-off's job)."""
    code, html = _get(denv["gui"], "/doctor")
    assert code == 200
    assert "/vendor/xterm/xterm.js" in html
    assert "/api/doctor/session_start" in html
    assert "/api/rnd/term_ws" in html
    assert "/api/rnd/term_stream2" in html
    assert "/api/rnd/term_input2" in html


def test_opening_doctor_never_starts_a_model(denv, monkeypatch):
    """Plain and banner-seeded page opens may run deterministic reads only;
    neither path may invoke the paid session-start action without a click."""
    _claude_only(monkeypatch)
    _write_report(
        denv["data"], name="2026-07-16.md",
        body=_report_body(status_ok=False))

    code, html = _get(
        denv["gui"],
        "/doctor?diagnose=1&issueId=ZH_HEALTH_CHECK_ISSUES"
        "&message=health+failed&component=health-check")
    assert code == 200
    assert _doctor_records(denv["reg"]) == []
    assert denv["pty"].live_sessions() == []

    # Pin the actual browser boot block: status fetch + context preload are
    # allowed, but no runDiagnose invocation occurs before its click handler is
    # defined. The resolveIssue call lives in an explicit button handler above.
    template = denv["gui"]._DOCTOR_PAGE_TEMPLATE
    boot = template.split("fetch(tq('/api/doctor/status')", 1)[1]
    boot = boot.split("window.runDiagnose = function", 1)[0]
    assert "window.runDiagnose(" not in boot
    assert "/api/doctor/session_start" not in boot
    assert "NEVER starts a paid model" in template
    assert "Click Diagnose to start a model session" in boot


# ── /api/doctor/status — the card-refresh data is real ───────────────────────

def test_doctor_status_endpoint_real_counts(denv):
    _write_report(denv["data"], name="2026-07-10.md",
                  body=_report_body(status_ok=False))
    _write_report(denv["data"], name="2026-07-14.md",
                  body=_report_body(warnings=["[journal overhead] 16%"]))
    _write_report(denv["data"], name="2026-07-16.md", body=_report_body())
    code, data = _get_json(denv["gui"], "/api/doctor/status")
    assert code == 200 and data["ok"] is True
    assert data["report_count"] == 3
    assert data["status"] == "green"            # from the NEWEST report
    assert data["last_run"] == "2026-07-16"
    by_date = {r["date"]: r["status"] for r in data["reports"]}
    assert by_date == {"2026-07-16": "green", "2026-07-14": "yellow",
                       "2026-07-10": "red"}
    # Newest-first ordering (the page list mirrors this).
    assert [r["date"] for r in data["reports"]] == \
        ["2026-07-16", "2026-07-14", "2026-07-10"]


def test_doctor_status_401_before_substance(denv, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    code, data = _get_json(denv["gui"], "/api/doctor/status")
    assert code == 401 and data["ok"] is False
    code2, data2 = _get_json(
        denv["gui"], "/api/doctor/status?token=tok-123")
    assert code2 == 200 and data2["ok"] is True


# ── /doctor/report — real file, rendered, traversal-safe ─────────────────────

def test_doctor_report_serves_the_actual_file(denv):
    _write_report(denv["data"], name="2026-07-16.md",
                  body=_report_body(marker="REPORT-BODY-MARKER-77"))
    code, html = _get(denv["gui"], "/doctor/report?name=2026-07-16.md")
    assert code == 200
    assert "REPORT-BODY-MARKER-77" in html


def test_doctor_report_traversal_and_unknown_are_safe(denv):
    secret = denv["data"] / "secret.md"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    for bad in ("../secret.md", "..%2Fsecret.md", "a/../../secret.md",
                "secret.txt", ""):
        code, raw = _get(denv["gui"],
                         "/doctor/report?name=" + bad)
        assert code == 400, f"traversal name {bad!r} was not rejected"
        assert "TOP-SECRET" not in raw
    code, _raw = _get(denv["gui"], "/doctor/report?name=nope.md")
    assert code == 404


def test_doctor_report_401_before_substance(denv, monkeypatch):
    _write_report(denv["data"], name="2026-07-16.md", body=_report_body())
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    code, raw = _get(denv["gui"], "/doctor/report?name=2026-07-16.md")
    assert code == 401
    assert "HEALTHREPORT-MARKER" not in raw
    code2, html2 = _get(denv["gui"],
                        "/doctor/report?name=2026-07-16.md"
                        "&token=tok-123")
    assert code2 == 200 and "HEALTHREPORT-MARKER" in html2


# ── the background diagnostics run + cursor-stable live tail ─────────────────

def _fake_hc_script(tmp_path, report_name, sleep_s=1.2):
    """A stand-in anchor_healthcheck.py: prints, sleeps, writes a REAL report
    into ANCHOR_DATA_DIR/health_reports, prints again. Never the live 75s
    check."""
    script = tmp_path / "fake_healthcheck.py"
    script.write_text(textwrap.dedent("""\
        import os, sys, time
        print("HC-BEGIN", flush=True)
        time.sleep(%s)
        rd = os.path.join(os.environ["ANCHOR_DATA_DIR"], "health_reports")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, %r), "w", encoding="utf-8") as f:
            f.write("# Anchor Health Report\\n\\nStatus: OK\\n"
                    "Run time: 1.0s (05:00:01)\\n\\n## Checks\\n- + ok\\n\\n"
                    "## Issues\\n(none)\\n\\n"
                    "## Warnings (non-blocking)\\n(none)\\n")
        print("HC-END", flush=True)
    """ % (sleep_s, report_name)), encoding="utf-8")
    return script


def test_healthcheck_runs_in_background_and_tails_live(denv, tmp_path,
                                                       monkeypatch):
    report_name = "2026-07-18.md"
    script = _fake_hc_script(tmp_path, report_name)
    monkeypatch.setenv("ANCHOR_HEALTHCHECK_CMD",
                       f"{sys.executable} {script}")

    code, p = _post(denv["gui"], "/api/doctor/healthcheck_run", {})
    assert code == 200 and p["ok"] is True and p["already_running"] is False

    # BACKGROUND, not a synchronous block: the POST returned while the run is
    # still going (the stand-in sleeps), and the tail reports running=True.
    code_t, t0 = _get_json(denv["gui"], "/api/doctor/healthcheck_tail?since=0")
    assert code_t == 200 and t0["ok"] is True
    assert t0["running"] is True

    # Idempotent while live: a second POST attaches, never stacks a second run.
    code2, p2 = _post(denv["gui"], "/api/doctor/healthcheck_run", {})
    assert code2 == 200 and p2["ok"] is True and p2["already_running"] is True

    # Cursor-stable incremental tail until completion.
    collected, cursor = "", 0
    deadline = _time.time() + 30
    while _time.time() < deadline:
        _c, t = _get_json(denv["gui"],
                          "/api/doctor/healthcheck_tail?since=%d" % cursor)
        assert t["ok"] is True
        assert t["next"] >= cursor              # the cursor never runs backward
        collected += t["text"]
        cursor = t["next"]
        if not t["running"]:
            break
        _time.sleep(0.2)
    else:
        pytest.fail("background healthcheck never finished")
    assert "HC-BEGIN" in collected and "HC-END" in collected
    assert t["exit_code"] == 0

    # Cursor stability after completion: a re-read from 0 replays the same
    # output; a read from the end is an honest empty.
    _c, replay = _get_json(denv["gui"], "/api/doctor/healthcheck_tail?since=0")
    assert "HC-BEGIN" in replay["text"] and "HC-END" in replay["text"]
    _c, atend = _get_json(denv["gui"],
                          "/api/doctor/healthcheck_tail?since=%d" % cursor)
    assert atend["text"] == "" and atend["next"] == cursor

    # On completion the stat cards refresh from the NEW report.
    _c, stats = _get_json(denv["gui"], "/api/doctor/status")
    assert stats["report_count"] == 1
    assert stats["last_run"] == report_name[:-3]
    assert stats["status"] == "green"


def test_healthcheck_tail_before_any_run_is_honest_empty(denv):
    code, t = _get_json(denv["gui"], "/api/doctor/healthcheck_tail?since=0")
    assert code == 200 and t["ok"] is True
    assert t["text"] == "" and t["running"] is False and t["started"] is False


def test_healthcheck_run_401_before_substance(denv, tmp_path, monkeypatch):
    import subprocess

    script = _fake_hc_script(tmp_path, "2026-07-18.md", sleep_s=0)
    monkeypatch.setenv("ANCHOR_HEALTHCHECK_CMD",
                       f"{sys.executable} {script}")
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")

    spawned = []
    real_popen = subprocess.Popen

    class _TrappingPopen(real_popen):
        def __init__(self, *args, **kwargs):
            spawned.append(args[0] if args else kwargs.get("args"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _TrappingPopen)

    code, p = _post(denv["gui"], "/api/doctor/healthcheck_run", {})
    assert code == 401 and p["ok"] is False
    assert spawned == [], "a tokenless POST must never spawn the healthcheck"

    code2, p2 = _post(denv["gui"], "/api/doctor/healthcheck_run",
                      {"token": "tok-123"})
    assert code2 == 200 and p2["ok"] is True
    assert len(spawned) == 1


# ── structural pins: the wave-3 routes are declared ──────────────────────────

def test_doctor_wave3_routes_declared(denv):
    rt = denv["routes"]
    gui = denv["gui"]
    # The page itself: declared OPEN (browser bootstrap, like "/"), legacy-
    # served — and mirrored in the reviewed OPEN_ROUTES.json allowlist.
    page = rt.match("GET", "/doctor")
    assert page is not None and page.auth == rt.AUTH_OPEN
    open_file = json.loads(
        (REPO_ROOT / "OPEN_ROUTES.json").read_text(encoding="utf-8"))
    assert any(e["method"] == "GET" and e["pattern"] == "/doctor"
               for e in open_file["routes"])
    # The data/mutating surface: default-deny token, migrated, registered.
    for method, path, handler_name in (
            ("GET", "/api/doctor/status", "handle_doctor_status"),
            ("GET", "/doctor/report", "handle_doctor_report"),
            ("GET", "/api/doctor/healthcheck_tail",
             "handle_doctor_healthcheck_tail"),
            ("POST", "/api/doctor/healthcheck_run",
             "handle_doctor_healthcheck_run")):
        route = rt.match(method, path)
        assert route is not None, (method, path)
        assert route.auth == rt.AUTH_TOKEN, (method, path)
        assert route.migrated is True and route.handler == handler_name
        assert route.handler in gui._MIGRATED_HANDLERS


# ═════════════════════════════════════════════════════════════════════════════
# Wave 4 — hardening, suite health, deploy
# ═════════════════════════════════════════════════════════════════════════════
#
# Deliverable 1: the distro import scan passes — the doctor surface added NO
# third-party import anywhere in product code, no new import exception was
# declared, and the ONE runtime module the /doctor seed imports (doctor.py) is
# deliberately declared in the deny-by-default manifest so the SHIPPED
# product's doctor surface actually works (the manifest header's rule: a new
# unlisted source file will not silently ship — add it deliberately).
# Deliverable 2: anchor_healthcheck.py non-regression — the daily check's
# module imports cleanly with the doctor changes in place and carries no
# reference to the removed V2 endpoint, so its endpoint walk cannot regress
# against this build (the live end-to-end run is the orchestrator's/deploy's
# job — never run inside the stub gate).

import ast


def test_w4_doctor_module_ships_in_manifest():
    """doctor.py is declared in dist_manifest.txt and selected by the deny-by-
    default stager (anchor_gui.py imports it at runtime for the doctor seed)."""
    import distro
    manifest = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "doctor.py" in manifest, (
        "doctor.py must be deliberately declared in dist_manifest.txt")
    selected = set(distro.select_shippable())
    assert "doctor.py" in selected, "doctor.py should ship"
    assert "anchor_gui.py" in selected


def test_w4_import_scan_clean_over_full_shipped_set():
    """The WHOLE shipped product set passes the stdlib-only import scan after
    the doctor waves (modulo the single declared pywinpty exception)."""
    import distro
    selected = distro.select_shippable()
    pairs = [(rel, distro.REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_third_party_imports(pairs, root=distro.REPO_ROOT)
    assert hits == [], (
        f"undeclared third-party import(s) in product code: {hits}")


def test_w4_no_new_import_exception_declared():
    """The doctor waves declared NO new third-party-import exception: the
    allowlist is still exactly winpty, scoped to pty_manager.py."""
    import distro
    allow = distro._THIRD_PARTY_IMPORT_ALLOWLIST
    assert set(allow.keys()) == {"winpty"}, (
        "the doctor build must not add a third-party-import exception")
    assert allow["winpty"]["files"] == frozenset({"pty_manager.py"})


def test_w4_doctor_py_scans_clean_and_guards_its_optional_probe():
    """doctor.py itself is stdlib/first-party only per the real scanner, and
    its interrupted-update probe import stays OUT of module level: it lives
    inside run_doctor's try/except, because update_transaction.py is
    deliberately NOT in the manifest — the shipped doctor must degrade
    gracefully (probe skipped), never ImportError at import time."""
    import distro
    doctor_path = REPO_ROOT / "doctor.py"
    src = doctor_path.read_text(encoding="utf-8")
    hits = distro.scan_third_party_imports(
        [("doctor.py", doctor_path)], root=distro.REPO_ROOT)
    assert hits == [], f"doctor.py leaks a third-party import: {hits}"
    top_level = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            top_level |= {a.name.split(".", 1)[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".", 1)[0])
    assert "update_transaction" not in top_level, (
        "doctor.py must keep the update_transaction probe import guarded "
        "(function-scoped, inside try/except) — it is not shipped")


def test_w4_healthcheck_module_clean_against_doctor_changes(denv):
    """anchor_healthcheck imports cleanly with the doctor build in place (its
    module-level ensure_data_dirs runs against this test's temp data dir), its
    entrypoint survives, and its source references neither the removed V2
    endpoint (so the daily endpoint walk cannot hit a 404-dead route) nor the
    deleted V2 agent/SDK."""
    hc = importlib.reload(importlib.import_module("anchor_healthcheck"))
    assert callable(hc.main)
    assert callable(hc.check_server_and_endpoints)
    assert callable(hc.check_route_table_walk)
    src = (REPO_ROOT / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "/api/doctor/run" not in src, (
        "the daily check must not probe the removed V2 doctor endpoint")
    assert _AGENT_MODULE not in src
    assert _GEMINI_SDK not in src
