"""Wave 9 — CLI mirror of the v4 "Project Cockpit" data seams (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 9 — CLI mirror": the four new read/data
subcommands DELEGATE to the shared v4 modules (no forked logic):

  - rnd rollup <pid> [--window lifetime|30d]  → effort_history.project_effort_rollup
  - rnd doc-roles <pid> --lane --session      → summarizer.session_doc_roles
  - rnd deliverable-type <pid> <id>           → deliverables type detect + verify
  - rnd engine <pid>                          → terminal_session.last_engine_for_project

Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend, ANCHOR_RUNNER_CMD →
tests/fake_claude.py (NEVER live claude / real PTY / :8777). Exercised in-process
via the mirror functions + the `_rnd_cli` dispatcher with argv lists.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.setenv("ANCHOR_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "sessions",
                 "deliverables", "report_viewer", "summarizer",
                 "session_registry", "worktrees", "pty_manager",
                 "terminal_session", "anchor_marker", "brownfield_scan",
                 "anchor"):
        mod = importlib.import_module(name)
        importlib.reload(mod)
    import anchor
    import effort_history
    import sessions
    import deliverables
    import summarizer
    import terminal_session
    import rnd_registry
    import job_runner
    yield {
        "tmp": tmp_path, "anchor": anchor, "eh": effort_history,
        "sessions": sessions, "deliverables": deliverables,
        "summarizer": summarizer, "ts": terminal_session, "rnd": rnd_registry,
        "jr": job_runner,
    }
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()
    # Reap any live stub PTY sessions left running.
    try:
        import pty_manager
        for sid in list(pty_manager.live_sessions()):
            try:
                pty_manager.kill(sid)
            except Exception:
                pass
    except Exception:
        pass


def _mkproject(env, name="Anchor"):
    folder = env["tmp"] / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder)), folder


# ── rollup mirror ──────────────────────────────────────────────────────────

def test_cli_rollup_shape_and_delegates(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    roll = anchor.rnd_rollup(pid, window="lifetime")
    # Same shape the shared module returns.
    assert set(roll.keys()) == {"tokens", "cost_usd", "wall_clock_ms", "sessions"}
    # Empty project → all zeros (run-only; nothing fabricated).
    assert roll["tokens"] == 0 and roll["sessions"] == 0

    direct = env["eh"].project_effort_rollup(pid, window="30d",
                                             folder_path=proj["folder_path"])
    mirror = anchor.rnd_rollup(pid, window="30d")
    assert mirror == direct

    anchor._rnd_cli(["rollup", pid, "--window", "30d"])
    out = capsys.readouterr().out
    assert "Effort rollup" in out and "tokens:" in out and "30d" in out


# ── doc-roles mirror ───────────────────────────────────────────────────────

def test_cli_doc_roles_delegates(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    # A discovered planning session with a MASTER+IMPL pair → planning roles.
    bd = folder / "planning" / "v4-cli"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Master Plan\n\n## North Star\ncli doc-roles.\n", encoding="utf-8")
    (bd / "IMPLEMENTATION-PLAN.md").write_text(
        "# Implementation Plan\n\n## Wave 1\nx.\n", encoding="utf-8")
    import brownfield_scan
    importlib.reload(brownfield_scan)
    scan = brownfield_scan.scan(str(folder))
    env["eh"].adopt_discovered(folder, pid, scan)

    sess = env["sessions"].list_sessions(str(folder), pid, "planning")
    assert sess
    sid = sess[0]["session_id"]

    roles = anchor.rnd_doc_roles(pid, "planning", sid)
    assert isinstance(roles, dict)
    direct = env["summarizer"].session_doc_roles(
        pid, "planning", sid, folder_path=str(folder))
    assert roles == direct
    # Each resolved role carries a label + href.
    for meta in roles.values():
        assert "label" in meta and "href" in meta

    anchor._rnd_cli(["doc-roles", pid, "--lane", "planning", "--session", sid])
    out = capsys.readouterr().out
    assert "doc role(s)" in out


# ── deliverable-type mirror ────────────────────────────────────────────────

def test_cli_deliverable_type_script(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    (folder / "app.py").write_text("print('hi')\n", encoding="utf-8")
    rec = env["deliverables"].pin_deliverable(str(folder), pid, "app.py",
                                              dtype="script")
    info = anchor.rnd_deliverable_type(pid, rec["job_id"])
    assert info["type"] == "script"
    assert info["artifact_path"] == "app.py"
    assert "verify" not in info  # only skill/tool get a verify block

    anchor._rnd_cli(["deliverable-type", pid, rec["job_id"]])
    out = capsys.readouterr().out
    assert "type:     script" in out


def test_cli_deliverable_type_skill_verifies(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    # A skill present under the TEMP skills dir → verify "available", no spawn.
    skills = env["tmp"] / "skills" / "myskill"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL.md").write_text("# myskill\n", encoding="utf-8")
    (folder / "myskill").mkdir(parents=True, exist_ok=True)
    rec = env["deliverables"].pin_deliverable(str(folder), pid, "myskill",
                                              name="myskill", dtype="skill")
    info = anchor.rnd_deliverable_type(pid, rec["job_id"])
    assert info["type"] == "skill"
    assert info["verify"]["status"] == env["deliverables"].VERIFY_AVAILABLE

    anchor._rnd_cli(["deliverable-type", pid, rec["job_id"]])
    out = capsys.readouterr().out
    assert "verify:" in out and "available" in out


def test_cli_deliverable_type_unknown_clean(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    anchor._rnd_cli(["deliverable-type", proj["id"], "no-such-deliverable"])
    out = capsys.readouterr().out
    assert "Error:" in out and "unknown deliverable" in out


# ── engine mirror ──────────────────────────────────────────────────────────

def test_cli_engine_default_and_persisted(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    # Unset → settings-backed default_cli (currently grok).
    import anchor_settings as _aset
    assert anchor.rnd_engine(pid) == _aset.get_default_cli()

    # Persist gemini and read it back through the mirror.
    env["ts"].set_last_engine_for_project(pid, "gemini")
    assert anchor.rnd_engine(pid) == "gemini"

    anchor._rnd_cli(["engine", pid])
    out = capsys.readouterr().out
    assert "Last-used engine" in out and "gemini" in out


# ── unknown project is clean (no traceback) ────────────────────────────────

def test_cli_v4_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["rollup", "deadbeef-not-real"])
    out = capsys.readouterr().out
    assert "Unknown project" in out
