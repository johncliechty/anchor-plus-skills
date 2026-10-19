"""Wave 9 — AC1: deliverables run via the launch+watch primitive with per-type
success contracts; a long-running/interactive deliverable times out cleanly.

Contracts (frozen design — MASTER-PLAN "Deliverables" + IMPLEMENTATION-PLAN
Wave 9 AC1):
  - doc           = exists + nonempty (read/rendered)  → success
  - script/skill  = exit 0 / result-no-error           → success; nonzero → fail
  - program       = exit 0 within the timeout          → success
  - long-running/interactive → TIMES OUT CLEANLY: process tree reaped (no
    orphan), stdin closed, status == timed-out.

NEVER invokes live ``claude`` — executed deliverables are small real scripts /
the deterministic mock runner. All spawned processes are cleaned up.
"""
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def deliv(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import job_runner
    importlib.reload(job_runner)
    import report_viewer
    importlib.reload(report_viewer)
    import deliverables
    importlib.reload(deliverables)
    return deliverables


def _pid_alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                             capture_output=True, text=True)
        return str(int(pid)) in (out.stdout or "")
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


# ── doc: exists + nonempty ──────────────────────────────────────────────────

def test_doc_nonempty_is_success(deliv, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text("# Title\n\nSome **rendered** content with $x^2$ math.\n",
                   encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_DOC, target=doc)
    assert rec["status"] == deliv.STATUS_SUCCESS
    assert rec["exists"] is True
    assert rec["size_bytes"] > 0
    # "read/rendered": the doc was rendered to HTML (nonzero chars).
    assert rec["rendered_chars"] > 0


def test_doc_empty_is_failure(deliv, tmp_path):
    doc = tmp_path / "empty.md"
    doc.write_text("", encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_DOC, target=doc)
    assert rec["status"] == deliv.STATUS_FAILED


def test_doc_missing_is_failure(deliv, tmp_path):
    rec = deliv.run_deliverable(deliv.TYPE_DOC, target=tmp_path / "nope.md")
    assert rec["status"] == deliv.STATUS_FAILED
    assert rec["exists"] is False


# ── script/skill: exit 0 / result-no-error ──────────────────────────────────

def test_script_exit0_is_success(deliv, tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("import sys; print('did work'); sys.exit(0)\n",
                      encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_SCRIPT,
                                argv=[sys.executable, str(script)],
                                timeout=30)
    assert rec["status"] == deliv.STATUS_SUCCESS
    assert rec["exit_code"] == 0


def test_script_nonzero_is_failure(deliv, tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("import sys; sys.exit(7)\n", encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_SCRIPT,
                                argv=[sys.executable, str(script)],
                                timeout=30)
    assert rec["status"] == deliv.STATUS_FAILED
    assert rec["exit_code"] == 7


def test_skill_result_error_is_failure_even_on_exit0(deliv):
    """A skill driven via the stream-json mock emits a result envelope; an
    ``is_error: true`` envelope fails the result-no-error contract even though
    the mock exits 0."""
    rec = deliv.run_deliverable(
        deliv.TYPE_SKILL,
        argv=[sys.executable, FAKE, "--lines", "1", "--result-error",
              "--exit-code", "0"],
        timeout=30,
    )
    assert rec["exit_code"] == 0
    assert rec["result_error"] is True
    assert rec["status"] == deliv.STATUS_FAILED


def test_skill_result_ok_is_success(deliv):
    rec = deliv.run_deliverable(
        deliv.TYPE_SKILL,
        argv=[sys.executable, FAKE, "--lines", "1", "--result",
              "--exit-code", "0"],
        timeout=30,
    )
    assert rec["exit_code"] == 0
    assert rec["result_error"] is False
    assert rec["status"] == deliv.STATUS_SUCCESS


# ── program: exit 0 within timeout ──────────────────────────────────────────

def test_program_exit0_within_timeout_is_success(deliv, tmp_path):
    prog = tmp_path / "prog.py"
    prog.write_text("print('program ran')\n", encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_PROGRAM,
                                argv=[sys.executable, str(prog)],
                                timeout=30)
    assert rec["status"] == deliv.STATUS_SUCCESS
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False


# ── long-running / interactive → CLEAN TIMEOUT (no orphan, stdin closed) ────

def test_interactive_deliverable_times_out_cleanly(deliv, tmp_path):
    """A deliverable that blocks on stdin (interactive) or runs long must time
    out cleanly: stdin is DEVNULL so input() raises EOF immediately OR the long
    sleep is reaped. We assert the tree (incl. a spawned grandchild) is reaped
    with NO orphan, and status == timed-out."""
    pid_file = tmp_path / "child.pid"
    start = time.monotonic()
    # The mock spawns a long-sleeping grandchild then sleeps far past the
    # timeout; stdin is closed by the runner so it can never be interactive.
    rec = deliv.run_deliverable(
        deliv.TYPE_PROGRAM,
        argv=[sys.executable, FAKE, "--lines", "1", "--spawn-child",
              "--child-pid-file", str(pid_file), "--sleep", "60"],
        timeout=1.0,
    )
    elapsed = time.monotonic() - start

    # Did NOT hang the gate (returned shortly after the 1s timeout).
    assert elapsed < 30, f"timeout did not return promptly: {elapsed}s"
    assert rec["status"] == deliv.STATUS_TIMED_OUT
    assert rec["timed_out"] is True

    # The grandchild must have been reaped (tree-kill, no orphan).
    assert pid_file.exists(), "mock never recorded its child pid"
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 15
    while _pid_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_alive(child_pid), "orphan grandchild survived the timeout"


def test_stdin_is_closed_non_interactive(deliv, tmp_path):
    """An interactive deliverable reading stdin gets EOF (DEVNULL), so it does
    NOT block — it finishes on its own. Proves stdin is closed."""
    script = tmp_path / "reads_stdin.py"
    script.write_text(
        "import sys\n"
        "data = sys.stdin.read()\n"           # EOF immediately on DEVNULL
        "print('read', repr(data))\n"
        "sys.exit(0 if data == '' else 1)\n",
        encoding="utf-8",
    )
    rec = deliv.run_deliverable(deliv.TYPE_PROGRAM,
                                argv=[sys.executable, str(script)],
                                timeout=10)
    assert rec["timed_out"] is False, "stdin was not closed — it blocked"
    assert rec["status"] == deliv.STATUS_SUCCESS
    assert rec["exit_code"] == 0


# ── status reports to the dashboard (persisted record) ──────────────────────

def test_status_persisted_for_dashboard(deliv, tmp_path):
    import rnd_registry
    folder = tmp_path / "proj"
    folder.mkdir()
    entry = rnd_registry.add_project("Demo", str(folder))
    pid = entry["id"]

    doc = folder / "report.md"
    doc.write_text("content\n", encoding="utf-8")
    rec = deliv.run_deliverable(deliv.TYPE_DOC, target=doc,
                                folder_path=str(folder), project_id=pid,
                                name="my-doc")
    assert rec["status"] == deliv.STATUS_SUCCESS

    # The dashboard reads these status records back.
    listed = deliv.list_status(str(folder), pid)
    assert len(listed) == 1
    assert listed[0]["name"] == "my-doc"
    assert listed[0]["status"] == deliv.STATUS_SUCCESS
    loaded = deliv.load_status(str(folder), pid, rec["deliverable_id"])
    assert loaded is not None and loaded["type"] == deliv.TYPE_DOC


# ── Wave 2: deliverable DECLARE (Anchor.md marker) + PIN ─────────────────────

@pytest.fixture
def deliv2(tmp_path, monkeypatch):
    """Fixture that also reloads rnd_registry + effort_history (declare/pin
    record into the deliverables-lane effort store)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import job_runner
    importlib.reload(job_runner)
    import report_viewer
    importlib.reload(report_viewer)
    import deliverables
    importlib.reload(deliverables)
    return deliverables, rnd_registry, effort_history


def test_pin_deliverable_surfaces_as_deliverables_effort(deliv2, tmp_path):
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "anchor_gui.py").write_text("print('app')\n", encoding="utf-8")
    pid = rnd.add_project("Anchor", str(folder))["id"]

    rec = deliv.pin_deliverable(str(folder), pid, "anchor_gui.py",
                                name="anchor_gui.py")
    assert rec["source"] == deliv.SOURCE_PINNED
    assert rec["artifact_path"] == "anchor_gui.py"
    assert rec["deliverable_type"] == deliv.TYPE_SCRIPT  # .py → script

    # It appears as a DELIVERABLES-lane effort even though it is NOT under
    # deliverables/.
    efforts = eh.list_efforts(str(folder), pid, "deliverables")
    assert any(e.get("artifact_path") == "anchor_gui.py" for e in efforts)
    pinned = deliv.list_pinned_deliverables(str(folder), pid)
    assert len(pinned) == 1
    assert pinned[0]["title"] == "anchor_gui.py"


def test_pin_deliverable_is_idempotent(deliv2, tmp_path):
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]
    deliv.pin_deliverable(str(folder), pid, "anchor_gui.py")
    deliv.pin_deliverable(str(folder), pid, "anchor_gui.py")
    assert len(eh.list_efforts(str(folder), pid, "deliverables")) == 1


def test_pin_absolute_path_under_folder_is_relativized(deliv2, tmp_path):
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]
    abs_path = str(folder / "anchor_gui.py")
    rec = deliv.pin_deliverable(str(folder), pid, abs_path)
    assert rec["artifact_path"] == "anchor_gui.py"


def test_declare_deliverables_from_anchor_md(deliv2, tmp_path):
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]
    # An Anchor.md marker with a Deliverables declaration block.
    (folder / "Anchor.md").write_text(
        "# Anchor.md\n"
        "\n"
        "## Deliverables (declared)\n"
        "\n"
        "- `anchor_gui.py` — program — The running web app\n"
        "- `DASHBOARD.md` — doc — Daily dashboard\n"
        "\n"
        "## Anchor\n"
        "\n"
        "- `should-not-be-parsed.py` — script — past the block\n",
        encoding="utf-8",
    )

    items = deliv.parse_anchor_md_deliverables(str(folder))
    assert [it["path"] for it in items] == ["anchor_gui.py", "DASHBOARD.md"]
    assert items[0]["type"] == deliv.TYPE_PROGRAM
    assert items[1]["type"] == deliv.TYPE_DOC
    assert items[0]["description"] == "The running web app"

    res = deliv.declare_deliverables_from_marker(str(folder), pid)
    assert res["declared"] == 2

    pinned = deliv.list_pinned_deliverables(str(folder), pid)
    paths_ = {p["artifact_path"] for p in pinned}
    assert paths_ == {"anchor_gui.py", "DASHBOARD.md"}
    assert all(p["source"] == deliv.SOURCE_DECLARED for p in pinned)


def test_declare_no_marker_is_empty(deliv2, tmp_path):
    deliv, rnd, _ = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]
    assert deliv.parse_anchor_md_deliverables(str(folder)) == []
    res = deliv.declare_deliverables_from_marker(str(folder), pid)
    assert res["declared"] == 0


def test_declare_is_idempotent(deliv2, tmp_path):
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]
    (folder / "Anchor.md").write_text(
        "## Deliverables\n\n- `anchor_gui.py` — program\n", encoding="utf-8")
    deliv.declare_deliverables_from_marker(str(folder), pid)
    deliv.declare_deliverables_from_marker(str(folder), pid)
    assert len(deliv.list_pinned_deliverables(str(folder), pid)) == 1


def test_pin_relative_traversal_escape_is_rejected(deliv2, tmp_path):
    """A RELATIVE ``..``-escaping path (e.g. ../../../../etc/passwd) must be
    REJECTED — it never gets stored as a deliverable's artifact_path. An
    in-folder relative path still works (containment, not blanket-deny)."""
    deliv, rnd, eh = deliv2
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("Anchor", str(folder))["id"]

    # Escaping relative path → rejected with a clear ValueError, nothing stored.
    with pytest.raises(ValueError):
        deliv.pin_deliverable(str(folder), pid, "../../../../etc/passwd")
    # An absolute path outside the folder is likewise rejected.
    outside = (tmp_path / "outside" / "loot.txt")
    with pytest.raises(ValueError):
        deliv.pin_deliverable(str(folder), pid, str(outside))
    # No bad effort leaked into the deliverables lane.
    assert eh.list_efforts(str(folder), pid, "deliverables") == []

    # An IN-FOLDER relative path still pins fine (containment, not deny-all).
    (folder / "anchor_gui.py").write_text("print('app')\n", encoding="utf-8")
    rec = deliv.pin_deliverable(str(folder), pid, "anchor_gui.py")
    assert rec["artifact_path"] == "anchor_gui.py"
    # And a nested in-folder relative path normalizes to POSIX-relative.
    sub = folder / "sub"
    sub.mkdir()
    (sub / "tool.py").write_text("x=1\n", encoding="utf-8")
    rec2 = deliv.pin_deliverable(str(folder), pid, "sub/tool.py")
    assert rec2["artifact_path"] == "sub/tool.py"
