"""Wave 8 — CLI mirror of the v2 R&D surface (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — CLI mirror": the new backend data
functions (sessions, status_line, reconcile, grass add-idea / promote-inbox,
pin-deliverable, set-blurb, regenerate-summary) are reachable from the CLI and
DELEGATE to the shared modules (no forked logic).

Hermetic: tmp ANCHOR_DATA_DIR; the summarize path goes through ANCHOR_RUNNER_CMD
→ tests/fake_claude.py (NEVER live claude). The CLI is exercised in-process by
calling the mirror functions + the dispatcher with argv lists.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import deliverables
    importlib.reload(deliverables)
    import report_viewer
    importlib.reload(report_viewer)
    import summarizer
    importlib.reload(summarizer)
    import session_registry
    importlib.reload(session_registry)
    import preview_server
    importlib.reload(preview_server)
    import anchor_marker
    importlib.reload(anchor_marker)
    import handoff
    importlib.reload(handoff)
    import anchor
    importlib.reload(anchor)
    yield {
        "tmp": tmp_path, "paths": paths, "rnd": rnd_registry,
        "eh": effort_history, "sessions": sessions, "deliverables": deliverables,
        "summarizer": summarizer, "anchor": anchor, "jr": job_runner,
        "sreg": session_registry, "preview": preview_server, "handoff": handoff,
    }
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _mkproject(env, name="Anchor"):
    folder = env["tmp"] / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder)), folder


# ── add-idea + sessions mirror ────────────────────────────────────────────

def test_cli_add_idea_and_list_sessions(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]

    rec = anchor.add_idea(proj["folder_path"], pid, "Try a Gemini adapter")
    assert rec["title"] == "Try a Gemini adapter"

    # The mirror reads it back as a grass session.
    sess = anchor.rnd_list_sessions(pid, "grass")
    assert len(sess) == 1
    assert sess[0]["member_files"][0]["title"] == "Try a Gemini adapter"

    # And via the dispatcher (argv form).
    anchor._rnd_cli(["sessions", pid, "--lane", "grass"])
    out = capsys.readouterr().out
    assert "1 session(s) in lane 'grass'" in out
    assert "Try a Gemini adapter" in out


def test_cli_add_idea_dispatcher(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    anchor._rnd_cli(["add-idea", pid, "Investigate", "ConPTY", "later",
                     "--notes", "from review"])
    out = capsys.readouterr().out
    assert "Idea added to grass lane" in out
    sess = env["sessions"].list_sessions(proj["folder_path"], pid, "grass")
    assert sess and sess[0]["member_files"][0]["title"] == "Investigate ConPTY later"
    assert sess[0]["member_files"][0]["notes"] == "from review"


# ── status_line mirror ────────────────────────────────────────────────────

def test_cli_status_line_shape(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    sl = anchor.rnd_status_line(pid)
    # Per-lane counts+provenance dict (Wave 3 contract), not the import masquerade.
    for lane in ("research", "planning", "build", "deliverables"):
        assert lane in sl
        assert set(sl[lane].keys()) == {"count", "imported", "running"}

    anchor._rnd_cli(["status", pid])
    out = capsys.readouterr().out
    assert "planning" in out and "count=" in out and "imported=" in out


# ── set-blurb mirror ──────────────────────────────────────────────────────

def test_cli_set_blurb(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    entry = anchor.rnd_set_blurb(pid, "An R&D control tower.")
    assert entry["blurb"] == "An R&D control tower."
    assert env["rnd"].get_project(pid)["blurb"] == "An R&D control tower."

    anchor._rnd_cli(["set-blurb", pid, "Updated", "blurb", "text"])
    assert env["rnd"].get_project(pid)["blurb"] == "Updated blurb text"
    assert "Blurb set" in capsys.readouterr().out


# ── pin-deliverable mirror ────────────────────────────────────────────────

def test_cli_pin_deliverable(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    (folder / "app.py").write_text("print('hi')\n", encoding="utf-8")

    rec = anchor.rnd_pin_deliverable(pid, "app.py", description="the app")
    assert rec["artifact_path"] == "app.py"
    assert rec["source"] == env["deliverables"].SOURCE_PINNED

    pinned = env["deliverables"].list_pinned_deliverables(proj["folder_path"], pid)
    assert any(r["artifact_path"] == "app.py" for r in pinned)

    anchor._rnd_cli(["pin-deliverable", pid, "app.py", "--type", "script",
                     "--desc", "again"])
    assert "Pinned deliverable" in capsys.readouterr().out


# ── reconcile mirror (preview = dry-run; apply mutates) ───────────────────

def test_cli_reconcile_preview_then_apply(env, capsys):
    anchor = env["anchor"]
    eh = env["eh"]
    proj, folder = _mkproject(env, "Anchor")
    active_id = proj["id"]
    # A same-folder retired sibling holding a real grass idea to fold.
    sib = env["rnd"].add_project("Anchor (old)", str(folder))
    sib_id = sib["id"]
    eh.add_idea(str(folder), sib_id, "legacy idea")

    # PREVIEW (default): non-destructive — sibling still present afterward.
    report = anchor.rnd_reconcile(active_id, apply=False)
    assert report["ok"] is True
    assert report["applied"] is False
    assert sib_id in report["to_delete"]
    assert env["rnd"].get_project(sib_id) is not None  # nothing destroyed

    # APPLY: folds the sibling's idea into the active id and deletes the sibling.
    report2 = anchor.rnd_reconcile(active_id, apply=True)
    assert report2["applied"] is True
    assert sib_id in report2["deleted"]
    assert env["rnd"].get_project(sib_id) is None
    folded = env["sessions"].list_sessions(str(folder), active_id, "grass")
    assert any(
        m.get("title") == "legacy idea"
        for s in folded for m in s.get("member_files", [])
    )

    anchor._rnd_cli(["reconcile", active_id])
    assert "PREVIEW" in capsys.readouterr().out


# ── promote-inbox mirror ──────────────────────────────────────────────────

def test_cli_promote_inbox(env):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    anchor.INBOX_MD.write_text(
        "# Inbox\n\n- 2026-06-11: Look into NSSM hardening [commercial]\n",
        encoding="utf-8")
    rec = anchor.promote_inbox(proj["folder_path"], pid,
                               "Look into NSSM hardening")
    assert rec["title"] == "Look into NSSM hardening"
    assert rec["promoted_from"] == "inbox"
    # Copy-by-default: INBOX.md untouched.
    assert "Look into NSSM hardening" in anchor.INBOX_MD.read_text(encoding="utf-8")


# ── regenerate-summary mirror (through the fake runner) ───────────────────

def test_cli_regenerate_summary_stubbed(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    # Build a discovered planning session with a member doc on disk.
    bd = folder / "planning" / "brownfield-discovery"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Master Plan\n\n## North Star\nfake line goal.\n", encoding="utf-8")
    import brownfield_scan
    importlib.reload(brownfield_scan)
    scan = brownfield_scan.scan(str(folder))
    env["eh"].adopt_discovered(folder, pid, scan)

    sess = anchor.rnd_list_sessions(pid, "planning")
    assert sess, "expected a discovered planning session"
    sid = sess[0]["session_id"]

    summary = anchor.rnd_regenerate_summary(pid, "planning", sid)
    assert summary["session_id"] == sid
    assert "claims" in summary
    # The cache now exists (force regenerated through the fake runner).
    cached = env["summarizer"].load_cached(str(folder), pid, "planning", sid)
    assert cached is not None

    anchor._rnd_cli(["regenerate-summary", pid, "--lane", "planning",
                     "--session", sid])
    assert "Summary regenerated" in capsys.readouterr().out


# ── Wave 10: v3 inspection mirror — term-sessions / previews / handoff ────

def test_cli_term_sessions(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    # Register a managed terminal session directly in the registry.
    rec = env["sreg"].register_session(pid, "build",
                                       status=env["sreg"].STATUS_RUNNING,
                                       label="cli probe")
    recs = anchor.rnd_term_sessions(pid)
    assert any(r["session_id"] == rec["session_id"] for r in recs)

    anchor._rnd_cli(["term-sessions", pid])
    out = capsys.readouterr().out
    assert "managed terminal session(s)" in out
    assert "build" in out and "cli probe" in out


def test_cli_previews(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    # Inject a (stopped) preview record — list_previews reconciles, never spawns.
    env["preview"]._put_record({
        "preview_id": "cli-prev-1", "project_id": pid, "target": "anchor_gui.py",
        "port": 54321, "url": "http://127.0.0.1:54321/", "status": "stopped",
        "pid": 0, "started_at": 1.0,
    })
    recs = anchor.rnd_previews(pid)
    assert any(r["preview_id"] == "cli-prev-1" for r in recs)
    # Never the live port.
    assert all(r.get("port") != env["preview"].LIVE_PORT for r in recs)

    anchor._rnd_cli(["previews", pid])
    out = capsys.readouterr().out
    assert "deliverable preview(s)" in out
    assert "anchor_gui.py" in out


def test_cli_handoff(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    # Build a discovered planning session with a MASTER+IMPL plan pair.
    bd = folder / "planning" / "rnd-vX"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Master Plan\n\n## North Star\ncli handoff goal.\n", encoding="utf-8")
    (bd / "IMPLEMENTATION-PLAN.md").write_text(
        "# Implementation Plan\n\n## Wave 1\nx.\n", encoding="utf-8")
    import brownfield_scan
    importlib.reload(brownfield_scan)
    scan = brownfield_scan.scan(str(folder))
    env["eh"].adopt_discovered(folder, pid, scan)

    out = anchor.rnd_handoff(pid, lane="build")
    assert out["proposal"]["has_plan_set"] is True
    assert "handoffs" in out

    # Record one so the inspection mirror surfaces it.
    plan_set = env["handoff"].discover_recent_plan_set(str(folder), pid)
    env["handoff"].record_handoff(str(folder), pid, "build-sess-1", plan_set)
    out2 = anchor.rnd_handoff(pid, lane="build")
    assert any(h["build_session_id"] == "build-sess-1"
               for h in out2["handoffs"])

    anchor._rnd_cli(["handoff", pid, "--lane", "build"])
    printed = capsys.readouterr().out
    assert "Most-recent plan set" in printed
    assert "recorded handoff(s)" in printed


def test_cli_handoff_no_plan_set(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    pid = proj["id"]
    anchor._rnd_cli(["handoff", pid])
    out = capsys.readouterr().out
    assert "No plan set available" in out


# ── error handling: unknown project / session are clean (no traceback) ────

def test_cli_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["status", "deadbeef-not-a-real-id"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


def test_cli_unknown_session_clean(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env)
    anchor._rnd_cli(["regenerate-summary", proj["id"], "--lane", "planning",
                     "--session", "no-such-session"])
    out = capsys.readouterr().out
    assert "Error:" in out and "unknown session" in out
