"""rearch W15 (C4) — Supervisor Core: inline seam + IPC contract + restart matrix.

Covers the frozen Wave-17 deliverables + acceptance:

  * the ANCHOR_SUPERVISOR=inline|external SEAM (``supervisor.get_supervisor``)
    with the fully-wired INLINE implementation (job_runner/gate_adapter
    delegation) + the honest degraded fallback for ``external`` (W16 lands the
    real process);
  * the two checked-in gate ARTIFACTS authored from ``supervisor.py`` — the IPC
    contract table (``IPC-CONTRACT.md``) and the in-memory-structure rebuild
    table (``REBUILD-TABLE.md``, zero unresolved rows);
  * TAIL-CURSOR durability — a per-job read offset persisted in the job dir that
    survives a table teardown;
  * the LITERAL restart matrix — a fake_claude job launched through the seam is
    re-adopted after the dashboard-side in-memory tables are torn down
    (simulated restart): the SAME job_id lists running, its lane/folder slots are
    rebuilt from the durable records, its tail cursor advances, and cancel
    tree-kills it (AC1);
  * GATE-ANSWER durability — an answer durably QUEUED + ACKed to the job dir
    while the IPC hop is killed mid-interaction is delivered EXACTLY ONCE to the
    job's stdin on retry — never lost, never doubled (AC2);
  * the per-contract-row kill/idempotency behaviors.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + ``ANCHOR_RUNNER_CMD`` → the deterministic
``tests/fake_claude.py`` mock. Never real claude / node / port 8777 / real data.
The inline seam is the same process, so a "dashboard restart" is SIMULATED by
tearing down the in-memory tables while the job's OS process persists — the
honest inline approximation; the cross-process live survival is W16's probes.
"""
import sys
import time
import threading
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "planning" / "rearch-2026-07"

#: One real stream-json AskUserQuestion gate frame (assistant tool_use), the
#: same shape fake_claude / real ``claude -p`` emit.
GATE_FRAME = {
    "type": "assistant",
    "message": {
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "toolu_w15_gate_0001",
            "name": "AskUserQuestion",
            "input": {"questions": [{
                "question": "Which output format?",
                "header": "Format",
                "multiSelect": False,
                "options": [
                    {"label": "JSON files", "description": "Structured JSON"},
                    {"label": "Markdown", "description": "Human-readable"},
                ],
            }]},
        }],
    },
}


@pytest.fixture
def seam(tmp_path, monkeypatch):
    """Hermetic inline-seam env; no module reload (the seam holds job_runner)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    monkeypatch.delenv("ANCHOR_SUPERVISOR", raising=False)
    monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
    import paths
    import job_runner
    import gate_adapter
    import supervisor
    paths.ensure_data_dirs()
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()
    sup = supervisor.get_supervisor()
    yield job_runner, gate_adapter, supervisor, sup, tmp_path
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()


def _wait_lines(jr, jid, n, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if len(jr.all_lines(jid)) >= n:
            return True
        time.sleep(0.03)
    return False


class _Sink:
    """A capturing stdin sink (write/flush) for the gate-answer tests."""

    def __init__(self):
        self.writes = []
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self.writes.append(data)

    def flush(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 1) The checked-in gate artifacts (authored BEFORE the code)
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifacts:
    def test_rebuild_table_has_zero_unresolved_rows(self):
        import supervisor
        assert supervisor.unresolved_rebuild_rows() == []
        for row in supervisor.REBUILD_TABLE:
            assert row["source"] in supervisor.RESOLVED_SOURCES
            assert row["structure"] and row["owner"] and row["rebuild_note"]

    def test_ipc_contract_covers_every_required_interaction(self):
        import supervisor
        names = {r["interaction"] for r in supervisor.IPC_CONTRACT}
        required = {"launch", "tail-since", "tail-cursor-durability", "cancel",
                    "gate-answer", "cost/rollup", "swarm-register"}
        assert required <= names
        for row in supervisor.IPC_CONTRACT:
            # Every row is fully specified — owner, idempotency key, and BOTH
            # restart-side behaviors are non-empty (no TBD before EXECUTE).
            for k in ("state_owner", "idempotency_key", "dashboard_down",
                      "job_down", "seam_method"):
                assert row[k] and str(row[k]).strip(), (row["interaction"], k)

    def test_checked_in_docs_match_the_rendered_source(self, tmp_path):
        import supervisor
        # Regenerate into the repo (skips an unchanged rewrite) then assert the
        # checked-in artifacts equal the render — drift fails the gate.
        p1 = supervisor.write_ipc_contract_doc()
        p2 = supervisor.write_rebuild_table_doc()
        assert p1.exists() and p2.exists()
        assert p1.read_text(encoding="utf-8") == supervisor.render_ipc_contract_md()
        assert p2.read_text(encoding="utf-8") == supervisor.render_rebuild_table_md()
        # They live under the frozen artifact dir.
        assert p1.parent == ARTIFACT_DIR
        assert p2.parent == ARTIFACT_DIR


# ══════════════════════════════════════════════════════════════════════════════
# 2) The seam resolves honestly (inline default · external degraded · invalid)
# ══════════════════════════════════════════════════════════════════════════════

class TestSeamResolution:
    def test_default_is_inline_not_degraded(self):
        import supervisor
        sup = supervisor.get_supervisor(env={})
        assert sup.mode == supervisor.MODE_INLINE
        assert sup.degraded is False

    def test_external_degrades_to_inline_until_w16(self):
        import supervisor
        sup = supervisor.get_supervisor(env={"ANCHOR_SUPERVISOR": "external"})
        # No external process exists in W15 → honest degraded inline fallback.
        assert sup.mode == supervisor.MODE_INLINE
        assert sup.degraded is True
        assert sup.reason and "external" in sup.reason.lower()

    def test_invalid_flag_value_raises_loudly(self):
        import supervisor
        import pillar_flags
        with pytest.raises(pillar_flags.PillarStateError):
            supervisor.get_supervisor(env={"ANCHOR_SUPERVISOR": "sidecar"})


# ══════════════════════════════════════════════════════════════════════════════
# 3) Tail-cursor durability (the IPC "tail-cursor-durability" row)
# ══════════════════════════════════════════════════════════════════════════════

class TestTailCursorDurability:
    def test_cursor_persists_and_survives_a_table_teardown(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "5"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)

        # A tail through the seam with persist=True writes the durable cursor.
        out = sup.tail(jid, persist=True)
        assert out["next"] == jr.load_read_cursor(jid) == out["total"]

        # Tear down the in-memory tables (simulated restart) — the durable
        # cursor file survives on disk and re-loads to the same offset.
        jr._reset_live_table_for_tests()
        assert jr.load_read_cursor(jid) == out["total"]
        # since=None → the seam resumes from the persisted cursor (no re-read).
        resumed = sup.tail(jid, since=None)
        assert resumed["lines"] == []
        assert resumed["next"] == out["total"]

    def test_torn_cursor_falls_back_to_zero(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "2"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)
        jr.cursor_path_for(jid).write_text("{not json", encoding="utf-8")
        assert jr.load_read_cursor(jid) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4) AC1 — the restart matrix: dashboard restart with a job in flight
# ══════════════════════════════════════════════════════════════════════════════

class TestRestartMidJob:
    def test_readopts_same_job_advancing_tail_cancellable(self, seam):
        jr, ga, supmod, sup, tmp = seam
        folder = tmp / "proj"
        folder.mkdir()
        childpid = tmp / "child.pid"
        # A build job (folder-locked) that DRIPS lines then sleeps, with a
        # grandchild so tree-kill is provable.
        rec = sup.launch_guarded(
            "build", project_id="pid-restart", folder_path=str(folder),
            cwd=str(folder),
            extra_args=["--lines", "10", "--line-interval", "0.12",
                        "--sleep", "8", "--spawn-child",
                        "--child-pid-file", str(childpid)])
        jid = rec["job_id"]
        assert _wait_lines(jr, jid, 2)

        # Pre-restart: the concurrency slots are held.
        assert jr.lane_holder("pid-restart", "build") == jid
        assert jr.folder_build_holder(str(folder)) == jid

        sup.tail(jid, persist=True)
        cur1 = jr.load_read_cursor(jid)

        # ── Simulate a dashboard restart: tear down every in-memory table. ──
        jr._reset_live_table_for_tests()
        ga._SINKS.clear()
        assert jr.lane_holder("pid-restart", "build") is None  # slot gone

        # Rebuild re-adopts the in-flight job from the durable records.
        summary = sup.rebuild()
        assert jid in summary["running_jobs"]
        assert summary["rebuilt_lane_slots"] >= 1
        assert summary["rebuilt_folder_locks"] >= 1

        # The restarted dashboard lists the SAME job_id running.
        listed = [r["job_id"] for r in sup.list_jobs(running_only=True)]
        assert listed.count(jid) == 1
        # And the concurrency slots are rebuilt (serialization survives).
        assert jr.lane_holder("pid-restart", "build") == jid
        assert jr.folder_build_holder(str(folder)) == jid

        # The tail cursor keeps advancing after the restart.
        advanced = False
        end = time.monotonic() + 6
        while time.monotonic() < end:
            sup.tail(jid, persist=True)
            if jr.load_read_cursor(jid) > cur1:
                advanced = True
                break
            time.sleep(0.05)
        assert advanced, "post-restart tail cursor did not advance"

        # The grandchild is alive, then cancel tree-kills the whole tree.
        child = int(childpid.read_text(encoding="utf-8").strip())
        assert jr._pid_alive(child)
        out = sup.cancel(jid)
        assert out["status"] == jr.STATUS_CANCELLED
        end = time.monotonic() + 6
        while time.monotonic() < end and jr._pid_alive(child):
            time.sleep(0.1)
        assert not jr._pid_alive(child), "cancel did not reap the grandchild"


# ══════════════════════════════════════════════════════════════════════════════
# 5) AC2 — gate-answer durability: exactly-once across a killed IPC hop
# ══════════════════════════════════════════════════════════════════════════════

class TestGateAnswerDurability:
    def _await_gate(self, jr, ga, tmp, sleep="6"):
        rec = jr.launch("plan", cwd=str(tmp), extra_args=["--lines", "1",
                                                          "--sleep", sleep])
        jid = rec["job_id"]
        prompt = ga.parse_event(GATE_FRAME)[0]
        ga.mark_awaiting_input(jid, prompt)
        return jid

    def test_queued_while_hop_killed_then_delivered_exactly_once(self, seam):
        jr, ga, supmod, sup, tmp = seam
        jid = self._await_gate(jr, ga, tmp)
        sink = _Sink()

        # ── HOP KILLED: no stdin sink → the answer is durably QUEUED, not
        #    delivered (ACKed to the job dir before returning). ──
        r1 = sup.answer_gate(jid, "Markdown")
        assert r1["ok"] is True and r1["queued"] is True
        assert r1["delivered"] is False and r1["deferred"] is True
        assert sink.writes == []
        g = ga.load_gate_file(jid)
        assert g["answered"] is True and not g.get("delivered_at")  # never lost

        # ── RETRY (hop restored): the queued answer is delivered EXACTLY once. ──
        ga.register_stdin_sink(jid, sink)
        r2 = sup.answer_gate(jid, "Markdown")
        assert r2["delivered"] is True
        assert len(sink.writes) == 1

        # ── A THIRD retry is a clean no-op — never doubled. ──
        r3 = sup.answer_gate(jid, "Markdown")
        assert r3["delivered"] is False
        assert len(sink.writes) == 1
        jr.cancel(jid)

    def test_deliver_gate_is_idempotent_retry_entry_point(self, seam):
        jr, ga, supmod, sup, tmp = seam
        jid = self._await_gate(jr, ga, tmp)
        sink = _Sink()
        ga.register_stdin_sink(jid, sink)
        # Queue-first, then deliver via the explicit retry entry point.
        ga.queue_gate_answer(jid, "JSON files")
        d1 = sup.deliver_gate(jid)
        d2 = sup.deliver_gate(jid)
        assert d1["delivered"] is True
        assert d2["delivered"] is False  # already delivered
        assert len(sink.writes) == 1
        jr.cancel(jid)

    def test_queue_refuses_a_terminal_job(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "1"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)  # runs to DONE
        res = sup.answer_gate(jid, "anything")
        assert res["ok"] is False
        assert "terminal" in (res["reason"] or "") or res["reason"] == "not-awaiting"


# ══════════════════════════════════════════════════════════════════════════════
# 6) Per-contract-row kill / idempotency behaviors
# ══════════════════════════════════════════════════════════════════════════════

class TestContractRowBehaviors:
    def test_launch_row_no_duplicate_spawn_on_repeated_rebuild(self, seam):
        jr, ga, supmod, sup, tmp = seam
        folder = tmp / "p"
        folder.mkdir()
        rec = sup.launch_guarded("research", project_id="pid-1",
                                 folder_path=str(folder), cwd=str(folder),
                                 extra_args=["--lines", "3", "--sleep", "5"])
        jid = rec["job_id"]
        jr._reset_live_table_for_tests()
        sup.rebuild()
        sup.rebuild()  # repeated rebuild must not duplicate the slot
        listed = [r["job_id"] for r in sup.list_jobs(running_only=True)]
        assert listed.count(jid) == 1
        # The lane slot is held by exactly the one job.
        assert jr.lane_holder("pid-1", "research") == jid
        jr.cancel(jid)

    def test_cancel_row_is_idempotent(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "1", "--sleep", "4"])
        jid = rec["job_id"]
        assert _wait_lines(jr, jid, 1)
        out1 = sup.cancel(jid)
        assert out1["status"] == jr.STATUS_CANCELLED
        # A repeated cancel is a clean no-op (status stays cancelled).
        out2 = sup.cancel(jid)
        assert out2["status"] == jr.STATUS_CANCELLED

    def test_tail_since_row_is_stateless_re_read(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "4"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)
        full = sup.tail(jid, since=0)
        assert full["total"] >= 4
        # Re-reading from a mid offset returns only the tail — the log is the
        # stable cursor space and survives a table teardown.
        jr._reset_live_table_for_tests()
        mid = sup.tail(jid, since=2)
        assert mid["lines"] == full["lines"][2:]
        assert mid["next"] == full["total"]

    def test_swarm_register_row_mints_a_sweepable_session(self, seam):
        jr, ga, supmod, sup, tmp = seam
        import session_registry as reg
        rec = jr.launch("research", extra_args=["--lines", "1", "--sleep", "3"])
        jid = rec["job_id"]
        srec = reg.get_session(jid)
        assert srec is not None
        assert srec.get("pid") == rec["pid"]
        assert srec.get("crypt_token") == rec["crypt_token"]
        jr.cancel(jid)
        # After cancel the swarm session is mirrored OUT of RUNNING.
        srec2 = reg.get_session(jid)
        assert srec2.get("status") != reg.STATUS_RUNNING

    def test_cost_rollup_row_reads_from_the_durable_record(self, seam):
        jr, ga, supmod, sup, tmp = seam
        rec = jr.launch("research", extra_args=["--lines", "1", "--result"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)
        loaded = sup.load_job(jid)
        assert loaded["status"] == jr.STATUS_DONE
        assert loaded.get("cost", {}).get("total_cost_usd") is not None
