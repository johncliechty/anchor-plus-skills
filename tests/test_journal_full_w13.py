"""W13 (rearch 2026-07, C3) — full mutation-set instrumentation + events CLI + perf.

Covers the frozen Wave-15 deliverables + acceptance:

  * EVERY enumerated mutation-of-record class the W1 tripwire scoped is
    instrumented via the blessed wrappers (``journal.journaled`` /
    ``journal.dual_write`` / ``journal.emit_safe``) and journals a
    schema-versioned SEMANTIC event when the journal flag is on —
      - doc persisted (``effort_history.persist_session_docs`` → the low-level
        ``record_effort`` is the shared writer, pairing-armed);
      - job launched / finished / cancelled (``job_runner``);
      - effort promoted (inbox → grass / grass → lane);
      - grass idea lifecycle (added / status / refined / deleted);
      - deliverable pinned (``deliverables.pin_deliverable``);
      - project lifecycle (created / archive-retire-…);
      - handoff recorded (``handoff.record_handoff``);
      - boneyard capture (``boneyard.record_entry``);
  * the write-site tripwire flipped to the permanent ENFORCE mode — the C3
    completeness gate: driving the blessed paths under the gate never violates,
    while an UNPAIRED raw ``.anchor/`` store write raises ``TripwireViolation``
    naming the write site (``journal.completeness_gate``);
  * the ``anchor.py rnd events <pid> [--since seq]`` journal-tail CLI — reads the
    real per-project journal, oldest-first, ``--since`` filtered, no model / no
    server;
  * the healthcheck perf-budget gate — the journal-on overhead over the store
    mutations the v2–v5 walks drive is under the hard <5% budget.

Journaling is OFF by default, so the instrumentation is byte-identical at runtime
unless a test turns the ``journal`` flag on — the whole existing suite is
unaffected. Folder-explicit tests need no data dir; the registry/CLI/job tests
set a temp ``ANCHOR_DATA_DIR`` (read live by ``paths.data_dir``). Nothing binds
``:8777`` or touches real data.
"""
import importlib
import io
import json
import os
import subprocess
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import journal

REPO = Path(__file__).resolve().parent.parent
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Default every test to journal OFF, tripwire OFF, a clean seq cache."""
    for v in ("ANCHOR_JOURNAL", "ANCHOR_JOURNAL_FSYNC", "ANCHOR_WRITE_TRIPWIRE"):
        monkeypatch.delenv(v, raising=False)
    journal.reset_seq_cache()
    yield
    journal.reset_seq_cache()
    # Never leave the process-wide tripwire installed for the next test.
    try:
        from tools import write_tripwire as _wt
        _wt.uninstall()
    except Exception:
        pass


def _types(folder, pid):
    return [e["type"] for e in journal.read_events(pid, folder_path=str(folder))]


# ══════════════════════════════════════════════════════════════════════════════
# 1) Enumerated mutation classes — folder-explicit (no data dir needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestEnumeratedSemanticEvents:
    def test_grass_idea_lifecycle_journals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidG"
        rec = eh.add_idea(str(f), pid, "a shiny idea")
        jid = rec["job_id"]
        eh.set_grass_status(str(f), pid, jid, eh.GRASS_REFINED)
        eh.save_grass_refinement(str(f), pid, jid, text="refined thoughts")
        eh.delete_grass_idea(str(f), pid, jid)

        types = set(_types(f, pid))
        assert journal.EV_GRASS_IDEA_ADDED in types
        assert journal.EV_GRASS_IDEA_STATUS in types
        assert journal.EV_GRASS_IDEA_REFINED in types
        assert journal.EV_GRASS_IDEA_DELETED in types
        # every event is schema-versioned + monotonic
        evs = journal.read_events(pid, folder_path=str(f))
        assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
        assert all(e["schema_ver"] == journal.CURRENT_SCHEMA_VER for e in evs)

    def test_effort_promoted_from_inbox_journals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidP"
        eh.promote_inbox(str(f), pid, "do the thing",
                         inbox_items=[{"text": "do the thing"}])
        assert journal.EV_EFFORT_PROMOTED in set(_types(f, pid))

    def test_deliverable_pinned_journals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import deliverables as deliv
        f, pid = tmp_path, "pidD"
        deliv.pin_deliverable(str(f), pid, "anchor_gui.py")
        assert journal.EV_DELIVERABLE_PINNED in set(_types(f, pid))

    def test_handoff_recorded_journals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import handoff as ho
        f, pid = tmp_path, "pidH"
        out = ho.record_handoff(str(f), pid, "build-1", {
            "plan_session_id": "plan-1", "plan_dir": "planning/x",
            "doc_rels": ["MASTER-PLAN.md"]})
        assert out.get("ok")
        assert journal.EV_HANDOFF_RECORDED in set(_types(f, pid))

    def test_boneyard_capture_journals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import boneyard as bone
        f, pid = tmp_path, "pidB"
        bone.record_entry(str(f), pid, {
            "source": bone.SOURCE_DELETED, "session_id": "sess-1",
            "lane": "research", "title": "a discarded run",
            "doc_rels": ["research/findings.md"]})
        assert journal.EV_BONEYARD_CAPTURED in set(_types(f, pid))

    def test_offswitch_off_writes_no_journal(self, tmp_path, monkeypatch):
        """With the flag OFF (default), the SAME instrumented paths journal
        nothing — byte-identical to pre-journal behavior."""
        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
        import effort_history as eh
        import deliverables as deliv
        f, pid = tmp_path, "pidOff"
        eh.add_idea(str(f), pid, "quiet idea")
        deliv.pin_deliverable(str(f), pid, "anchor.py")
        assert journal.read_events(pid, folder_path=str(f)) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2) Registry / job classes — temp ANCHOR_DATA_DIR (read live)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def datadir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    import paths
    paths.ensure_data_dirs()
    # rnd_registry / job_runner read data_dir() live — no reload needed.
    yield tmp_path
    try:
        import job_runner
        job_runner._reset_live_table_for_tests()
    except Exception:
        pass


class TestRegistryAndJobEvents:
    def test_project_lifecycle_journals(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import rnd_registry as rnd
        proj_folder = datadir / "proj"
        proj_folder.mkdir()
        (proj_folder / "CLAUDE.md").write_text("# probe\n", encoding="utf-8")
        proj = rnd.add_project("W13 lifecycle", str(proj_folder), scaffold=True)
        pid = proj["id"]
        rnd.archive_project(pid)

        types = set(_types(proj_folder, pid))
        assert journal.EV_PROJECT_CREATED in types
        assert journal.EV_PROJECT_LIFECYCLE in types

    def test_job_cancelled_journals(self, datadir, monkeypatch):
        """A pre-written job record (project_id/folder_path stamped, no live pid)
        cancelled through ``job_runner.cancel`` journals ``job-cancelled`` into
        the project's journal — deterministic, no subprocess."""
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import job_runner as jr
        proj_folder = datadir / "cjob"
        proj_folder.mkdir()
        pid = "pidJC"
        jr._write_record({
            "job_id": "job-cancel-1", "project_id": pid,
            "folder_path": str(proj_folder), "status": jr.STATUS_RUNNING,
            "pid": None})
        jr.cancel("job-cancel-1")
        assert journal.EV_JOB_CANCELLED in set(_types(proj_folder, pid))

    def test_job_launched_and_finished_journals(self, datadir, monkeypatch):
        """A real guarded launch through the fake-claude stub journals
        ``job-launched`` (synchronously, before launch returns) and — once the
        reader finalizes — ``job-finished``."""
        if not FAKE_CLAUDE.exists():
            pytest.skip("fake_claude stub absent")
        monkeypatch.setenv("ANCHOR_RUNNER_CMD",
                           f"python {FAKE_CLAUDE.as_posix()}")
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import job_runner as jr
        proj_folder = datadir / "ljob"
        proj_folder.mkdir()
        pid = "pidJL"
        rec = jr.launch_guarded("research", pid, str(proj_folder),
                                cwd=str(proj_folder), prompt="hello")
        jid = rec["job_id"]
        # launched is emitted synchronously inside launch() → already on disk.
        assert journal.EV_JOB_LAUNCHED in set(_types(proj_folder, pid))

        # poll for the reader to finalize the job → job-finished journaled.
        deadline = time.time() + 25
        finished = False
        while time.time() < deadline:
            r = jr.load_record(jid) or {}
            if r.get("status") in (jr.STATUS_DONE, jr.STATUS_FAILED):
                finished = True
                break
            time.sleep(0.2)
        assert finished, "stub job never reached a terminal status"
        # the finalize emit lands right around the status flip; give it a beat.
        for _ in range(25):
            if journal.EV_JOB_FINISHED in set(_types(proj_folder, pid)):
                break
            time.sleep(0.2)
        assert journal.EV_JOB_FINISHED in set(_types(proj_folder, pid))


# ══════════════════════════════════════════════════════════════════════════════
# 3) The permanent ENFORCE completeness gate
# ══════════════════════════════════════════════════════════════════════════════

class TestCompletenessGate:
    def test_paired_passes_unpaired_fires_naming_site(self, tmp_path):
        from tools import write_tripwire as wt
        import effort_history as eh
        f, pid = tmp_path, "pidC"

        with journal.completeness_gate():
            # (1) blessed instrumented mutation → paired → must NOT raise.
            eh.add_idea(str(f), pid, "gated idea")
            eh.record_effort(str(f), pid, "build", "gate-job",
                             extra={"kind": "doc"})

            # (2) an UNPAIRED raw .anchor store write MUST raise, naming the site.
            rogue = f / ".anchor" / "projects" / pid / "grass" / "rogue.json"
            rogue.parent.mkdir(parents=True, exist_ok=True)  # mkdir isn't policed
            with pytest.raises(wt.TripwireViolation) as ei:
                with open(rogue, "w", encoding="utf-8") as fh:
                    fh.write("{}")
            # the violation names the store write site (mechanical, not narrated)
            assert "rogue.json" in str(ei.value) or "grass" in str(ei.value)

        # gate exited cleanly: tripwire uninstalled + journal flag restored.
        assert not wt.is_installed()

    def test_gate_is_off_by_default(self, tmp_path):
        """Without the gate, the same unpaired write is fine (no enforcement)."""
        f = tmp_path / ".anchor" / "projects" / "p" / "x.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}", encoding="utf-8")  # no raise — tripwire not installed
        assert f.exists()


# ══════════════════════════════════════════════════════════════════════════════
# 4) The events CLI — anchor.py rnd events <pid> [--since seq]
# ══════════════════════════════════════════════════════════════════════════════

class TestEventsCLI:
    def test_rnd_events_mirror_and_since(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import rnd_registry as rnd
        import effort_history as eh
        import anchor

        proj_folder = datadir / "cli"
        proj_folder.mkdir()
        (proj_folder / "CLAUDE.md").write_text("# cli probe\n", encoding="utf-8")
        proj = rnd.add_project("W13 cli", str(proj_folder), scaffold=True)
        pid = proj["id"]
        # generate a few journaled mutations (add_project already emitted one).
        for i in range(3):
            eh.add_idea(str(proj_folder), pid, f"cli idea {i}")

        evs = anchor.rnd_events(pid)
        assert len(evs) >= 4  # project-created + 3 grass-idea-added
        # oldest-first (append order): seq strictly increasing
        seqs = [e["seq"] for e in evs]
        assert seqs == sorted(seqs)

        # --since filters to strictly-greater seq
        cut = seqs[0]
        after = anchor.rnd_events(pid, since=cut)
        assert after and all(e["seq"] > cut for e in after)
        assert len(after) == len(evs) - 1

        # a bad --since is a clean ValueError (not a crash)
        with pytest.raises(ValueError):
            anchor.rnd_events(pid, since="not-an-int")

    def test_rnd_cli_events_subcommand_prints(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import rnd_registry as rnd
        import effort_history as eh
        import anchor

        proj_folder = datadir / "cli2"
        proj_folder.mkdir()
        (proj_folder / "CLAUDE.md").write_text("# cli2\n", encoding="utf-8")
        proj = rnd.add_project("W13 cli2", str(proj_folder), scaffold=True)
        pid = proj["id"]
        eh.add_idea(str(proj_folder), pid, "printed idea")

        buf = io.StringIO()
        with redirect_stdout(buf):
            anchor._rnd_cli(["events", pid])
        out = buf.getvalue()
        assert "journal event(s)" in out
        assert journal.EV_GRASS_IDEA_ADDED in out

        # --since path prints too
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            anchor._rnd_cli(["events", pid, "--since", "1"])
        assert "after seq 1" in buf2.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# 5) The perf-budget gate (the healthcheck check runs green)
# ══════════════════════════════════════════════════════════════════════════════

class TestPerfBudget:
    def test_perf_budget_check_passes(self):
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_journal_perf_budget(report)
        # find our check; it must have PASSED (journal-on overhead < 5%)
        rows = [c for c in report.checks if c[0].startswith("journal perf budget")]
        assert rows, "perf-budget check did not run"
        name, ok, detail = rows[0]
        assert ok, f"perf budget regressed: {detail}"
        assert "journaled=yes" in detail

    def test_completeness_gate_healthcheck_passes(self):
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_journal_completeness_gate(report)
        rows = [c for c in report.checks
                if c[0].startswith("journal completeness gate")]
        assert rows, "completeness-gate check did not run"
        name, ok, detail = rows[0]
        assert ok, f"completeness gate failed: {detail}"
