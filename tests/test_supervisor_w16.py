"""rearch W16 (C4) — External Supervisor Service + Live Probes.

Covers the frozen Wave-18 deliverables + acceptance:

  * the STDLIB supervisor PROCESS — a loopback token-authed HTTP IPC server
    (``supervisor.SupervisorServer``) implementing the IPC contract table — and
    the external CLIENT implementation of the ``ANCHOR_SUPERVISOR`` seam
    (``supervisor.ExternalSupervisor``), with the honest DEGRADED-to-inline
    behavior when the supervisor is down / rejects the token;
  * ``get_supervisor(env=external)`` resolving to a live external client when the
    server answers ``/ping`` and degrading to inline otherwise;
  * a launch → tail → cancel round-trip over 127.0.0.1 HTTP;
  * TAIL-CURSOR durability across a SUPERVISOR restart — a persisted read offset
    in the job dir survives ``stop()`` of the old server + ``start()`` of a new
    one over the same data dir (nothing in-memory has to survive);
  * GATE-ANSWER durability over the external hop — queued-then-delivered exactly
    once;
  * the two LIVE-PROBE operations the inline seam can never cover:
    (a) ``probe_claude_version`` (spawn ``claude --version`` under the account),
    (b) ``spawn_sacrificial`` — a job-object BREAKAWAY child that survives a
    supervisor restart (the mechanism; the true cross-service restart is the
    Wave-19 C4 runbook);
  * ``install_supervisor.ps1`` — the scripted (not documented) NSSM install with
    ``ObjectName .\\john`` + cloned ``AppEnvironmentExtra`` + the no-console
    discipline.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + ``ANCHOR_RUNNER_CMD`` → the deterministic
``tests/fake_claude.py`` mock; the server runs in-process on an OS-assigned free
loopback port. Never real claude / node / port 8777 / real data. The server and
client share the same process (so a "supervisor restart" is stop()+start() over
the same data dir) — the honest hermetic approximation of the second process;
the true cross-service survival is Wave-19's live runbook.
"""
import json
import os
import sys
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic data dir + stub runner; no external supervisor env leaking in."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    for k in ("ANCHOR_SUPERVISOR", "ANCHOR_SUPERVISOR_URL",
              "ANCHOR_SUPERVISOR_TOKEN", "ANCHOR_SUPERVISOR_PORT",
              "ANCHOR_JOURNAL"):
        monkeypatch.delenv(k, raising=False)
    import paths
    import job_runner
    import gate_adapter
    import supervisor
    paths.ensure_data_dirs()
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()
    yield job_runner, gate_adapter, supervisor, tmp_path
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()
    gate_adapter._SINKS.clear()


@pytest.fixture
def server(env):
    """A live loopback SupervisorServer (OS-assigned port) + a matched client env."""
    jr, ga, supmod, tmp = env
    token = os.urandom(8).hex()  # ephemeral loopback test token (no literal secret)
    srv = supmod.SupervisorServer(host="127.0.0.1", port=0, token=token)
    srv.start()
    client_env = {
        "ANCHOR_SUPERVISOR": "external",
        "ANCHOR_SUPERVISOR_URL": srv.url,
        "ANCHOR_SUPERVISOR_TOKEN": token,
    }
    yield jr, ga, supmod, tmp, srv, client_env, token
    try:
        srv.stop()
    except Exception:
        pass


def _wait_lines(jr, jid, n, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if len(jr.all_lines(jid)) >= n:
            return True
        time.sleep(0.03)
    return False


class _Sink:
    def __init__(self):
        self.writes = []
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self.writes.append(data)

    def flush(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 1) The seam resolves honestly against a REAL external process
# ══════════════════════════════════════════════════════════════════════════════

class TestExternalSeamResolution:
    def test_external_up_resolves_to_client_not_degraded(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        assert sup.mode == supmod.MODE_EXTERNAL
        assert sup.degraded is False
        assert isinstance(sup, supmod.ExternalSupervisor)

    def test_wrong_token_degrades_to_inline(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        bad = dict(cenv, ANCHOR_SUPERVISOR_TOKEN="not-the-token")
        sup = supmod.get_supervisor(env=bad)
        assert sup.mode == supmod.MODE_INLINE
        assert sup.degraded is True
        assert "external" in (sup.reason or "").lower()

    def test_supervisor_down_degrades_to_inline(self, env):
        jr, ga, supmod, tmp = env
        # A URL that nothing is serving → available() False → inline degraded.
        sup = supmod.get_supervisor(env={
            "ANCHOR_SUPERVISOR": "external",
            "ANCHOR_SUPERVISOR_URL": "http://127.0.0.1:9",  # discard port
            "ANCHOR_SUPERVISOR_TOKEN": "x"})
        assert sup.mode == supmod.MODE_INLINE
        assert sup.degraded is True

    def test_default_flag_is_plain_inline(self, env):
        jr, ga, supmod, tmp = env
        sup = supmod.get_supervisor(env={})
        assert sup.mode == supmod.MODE_INLINE
        assert sup.degraded is False


# ══════════════════════════════════════════════════════════════════════════════
# 2) Loopback auth: 401 before any work
# ══════════════════════════════════════════════════════════════════════════════

class TestLoopbackAuth:
    def test_ping_requires_the_token(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        # Correct token → 200 ok.
        req = urllib.request.Request(
            f"{srv.url}/ping",
            headers={"Authorization": f"Bearer {token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read().decode())
        assert body["ok"] is True and body["mode"] == supmod.MODE_EXTERNAL

        # Missing/blank token → 401 before any dispatch.
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(
                urllib.request.Request(f"{srv.url}/ping", method="GET"),
                timeout=5)
        assert ei.value.code == 401

    def test_post_with_bad_token_is_401(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        req = urllib.request.Request(
            f"{srv.url}/list_jobs", data=b"{}",
            headers={"Authorization": "Bearer WRONG",
                     "Content-Type": "application/json"}, method="POST")
        # A bad token MUST be rejected. The server answers 401 and closes; on a
        # loaded loopback the client can observe the close as a connection reset
        # BEFORE it reads the 401 (a socket race, not an auth bypass) — both
        # outcomes prove rejection (the request never returns an authorized body).
        try:
            with pytest.raises(urllib.error.HTTPError) as ei:
                urllib.request.urlopen(req, timeout=5)
            assert ei.value.code == 401
        except (ConnectionError, ConnectionAbortedError, ConnectionResetError):
            pass  # rejected-by-close is still rejected

    def test_client_available_reflects_token(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        good = supmod.ExternalSupervisor(base_url=srv.url, token=token)
        assert good.available() is True
        bad = supmod.ExternalSupervisor(base_url=srv.url, token="nope")
        assert bad.available() is False


# ══════════════════════════════════════════════════════════════════════════════
# 3) launch → tail → introspect → cancel round-trip over HTTP
# ══════════════════════════════════════════════════════════════════════════════

class TestExternalRoundTrip:
    def test_launch_tail_list_cancel(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        rec = sup.launch("research",
                         extra_args=["--lines", "4", "--line-interval", "0.1",
                                     "--sleep", "5"])
        jid = rec["job_id"]
        assert jid and rec.get("pid")

        assert _wait_lines(jr, jid, 2)
        out = sup.tail(jid, since=0)
        assert out["total"] >= 2 and out["lines"]

        # list_jobs / load_job / is_live all round-trip.
        listed = [r["job_id"] for r in sup.list_jobs(running_only=True)]
        assert jid in listed
        loaded = sup.load_job(jid)
        assert loaded["job_id"] == jid
        assert sup.is_live(jid) is True

        out = sup.cancel(jid)
        assert out["status"] == jr.STATUS_CANCELLED
        assert sup.is_live(jid) is False

    def test_launch_guarded_holds_the_lane_slot(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        folder = tmp / "proj"
        folder.mkdir()
        rec = sup.launch_guarded("build", project_id="pid-ext",
                                 folder_path=str(folder), cwd=str(folder),
                                 extra_args=["--lines", "3", "--sleep", "5"])
        jid = rec["job_id"]
        # The server + client share the process, so the durable slot is visible.
        assert jr.lane_holder("pid-ext", "build") == jid
        assert jr.folder_build_holder(str(folder)) == jid
        sup.cancel(jid)


# ══════════════════════════════════════════════════════════════════════════════
# 4) Tail-cursor durability ACROSS a supervisor restart (AC2)
# ══════════════════════════════════════════════════════════════════════════════

class TestCursorSurvivesSupervisorRestart:
    def test_persisted_offset_reloads_after_restart(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        rec = sup.launch("research", extra_args=["--lines", "5"])
        jid = rec["job_id"]
        jr.wait(jid, timeout=30)

        out = sup.tail(jid, persist=True)
        offset = sup.read_cursor(jid)
        assert offset == out["total"] >= 5

        # ── Restart the supervisor: stop the old server, start a new one over
        #    the SAME data dir. The offset file in the job dir carries across. ──
        srv.stop()
        srv2 = supmod.SupervisorServer(host="127.0.0.1", port=0, token=token)
        srv2.start()
        try:
            cenv2 = dict(cenv, ANCHOR_SUPERVISOR_URL=srv2.url)
            sup2 = supmod.get_supervisor(env=cenv2)
            assert sup2.mode == supmod.MODE_EXTERNAL and not sup2.degraded
            # The restarted supervisor re-serves the SAME persisted offset.
            assert sup2.read_cursor(jid) == offset
            # Resuming from the persisted cursor yields no re-read.
            resumed = sup2.tail(jid, since=None)
            assert resumed["lines"] == [] and resumed["next"] == offset
        finally:
            srv2.stop()


# ══════════════════════════════════════════════════════════════════════════════
# 5) Gate-answer durability over the external hop (exactly-once)
# ══════════════════════════════════════════════════════════════════════════════

GATE_FRAME = {
    "type": "assistant",
    "message": {"role": "assistant", "content": [{
        "type": "tool_use", "id": "toolu_w16_gate", "name": "AskUserQuestion",
        "input": {"questions": [{
            "question": "Which output format?", "header": "Format",
            "multiSelect": False,
            "options": [{"label": "JSON files", "description": "j"},
                        {"label": "Markdown", "description": "m"}]}]}}]}}


class TestGateAnswerOverHop:
    def _await_gate(self, jr, ga, tmp):
        rec = jr.launch("plan", cwd=str(tmp),
                        extra_args=["--lines", "1", "--sleep", "6"])
        jid = rec["job_id"]
        prompt = ga.parse_event(GATE_FRAME)[0]
        ga.mark_awaiting_input(jid, prompt)
        return jid

    def test_queued_while_no_sink_then_delivered_once(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        jid = self._await_gate(jr, ga, tmp)
        sink = _Sink()

        # No sink registered → durably QUEUED, not delivered.
        r1 = sup.answer_gate(jid, "Markdown")
        assert r1["ok"] is True and r1["queued"] is True
        assert r1["delivered"] is False and r1["deferred"] is True
        assert sink.writes == []
        g = ga.load_gate_file(jid)
        assert g["answered"] is True and not g.get("delivered_at")

        # Retry with a sink → delivered EXACTLY once.
        ga.register_stdin_sink(jid, sink)
        r2 = sup.answer_gate(jid, "Markdown")
        assert r2["delivered"] is True
        assert len(sink.writes) == 1

        # A third retry is a clean no-op.
        r3 = sup.answer_gate(jid, "Markdown")
        assert r3["delivered"] is False
        assert len(sink.writes) == 1
        jr.cancel(jid)

    def test_deliver_gate_retry_entry_point(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        jid = self._await_gate(jr, ga, tmp)
        sink = _Sink()
        ga.register_stdin_sink(jid, sink)
        ga.queue_gate_answer(jid, "JSON files")
        d1 = sup.deliver_gate(jid)
        d2 = sup.deliver_gate(jid)
        assert d1["delivered"] is True and d2["delivered"] is False
        assert len(sink.writes) == 1
        jr.cancel(jid)


# ══════════════════════════════════════════════════════════════════════════════
# 6) Live probe (a): claude --version through the supervisor
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeClaudeVersion:
    def test_reports_version_from_a_stub_binary(self, server, tmp_path,
                                                monkeypatch):
        jr, ga, supmod, tmp, srv, cenv, token = server
        # A stub "claude" that prints a version and exits 0.
        stub = tmp_path / "claude_stub.py"
        stub.write_text("import sys; print('1.42.0 (Claude Code stub)')\n",
                        encoding="utf-8")
        monkeypatch.setenv("ANCHOR_CLAUDE_CMD", f"{sys.executable} {stub}")
        # Server already running — its handler reads os.environ at call time.
        sup = supmod.get_supervisor(env=cenv)
        out = sup.probe_claude_version(timeout=15)
        assert out["ok"] is True
        assert "1.42.0" in out["output"]

    def test_absent_claude_is_honest_not_a_crash(self, server, monkeypatch):
        jr, ga, supmod, tmp, srv, cenv, token = server
        monkeypatch.setenv("ANCHOR_CLAUDE_CMD",
                           "definitely-not-a-real-binary-xyz-w16")
        sup = supmod.get_supervisor(env=cenv)
        out = sup.probe_claude_version(timeout=10)
        assert out["ok"] is False
        assert out["reason"]

    def test_probe_shape_direct(self):
        import supervisor
        out = supervisor.probe_claude_version.__doc__
        assert "claude" in out.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 7) Live probe (b): the breakaway sacrificial child
# ══════════════════════════════════════════════════════════════════════════════

class TestBreakawayChild:
    def test_spawn_breakaway_child_is_alive_then_reapable(self):
        import supervisor
        import proc_probe
        import job_runner
        out = supervisor.spawn_breakaway_child(
            [sys.executable, "-c", "import time; time.sleep(20)"])
        assert out["ok"] is True and out["pid"]
        pid = out["pid"]
        try:
            # Give the interpreter a beat to be schedulable (liveness cross-plat:
            # proc_probe is Windows-only, job_runner._pid_alive covers POSIX).
            end = time.monotonic() + 3
            alive = False
            while time.monotonic() < end:
                if proc_probe.is_alive(pid) or job_runner._pid_alive(pid):
                    alive = True
                    break
                time.sleep(0.05)
            assert alive
        finally:
            proc_probe.tree_kill(pid)  # Windows reap
            import os as _os
            import signal as _sig
            if _os.name != "nt":
                try:
                    _os.kill(pid, _sig.SIGKILL)  # POSIX reap (no zombie leak)
                except Exception:
                    pass

    def test_spawn_sacrificial_over_the_hop(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        sup = supmod.get_supervisor(env=cenv)
        out = sup.spawn_sacrificial(seconds=20)
        assert out["ok"] is True and out["pid"]
        pid = out["pid"]
        import proc_probe
        try:
            end = time.monotonic() + 3
            alive = False
            while time.monotonic() < end:
                if proc_probe.is_alive(pid) or jr._pid_alive(pid):
                    alive = True
                    break
                time.sleep(0.05)
            assert alive
            # Reap via the hop.
            sup.reap_pid(pid)
        finally:
            proc_probe.tree_kill(pid)


# ══════════════════════════════════════════════════════════════════════════════
# 8) Degraded transport behavior (supervisor down mid-call)
# ══════════════════════════════════════════════════════════════════════════════

class TestDegradedTransport:
    def test_call_after_stop_raises_unavailable(self, server):
        jr, ga, supmod, tmp, srv, cenv, token = server
        client = supmod.ExternalSupervisor(base_url=srv.url, token=token,
                                           timeout=1.5)
        assert client.available() is True
        srv.stop()
        with pytest.raises(supmod.SupervisorUnavailable):
            client.list_jobs()

    def test_available_is_false_when_down(self, env):
        jr, ga, supmod, tmp = env
        client = supmod.ExternalSupervisor(base_url="http://127.0.0.1:9",
                                           token="x", timeout=1.0)
        assert client.available() is False


# ══════════════════════════════════════════════════════════════════════════════
# 9) The scripted NSSM installer (install_supervisor.ps1)
# ══════════════════════════════════════════════════════════════════════════════

class TestInstallScript:
    def test_install_script_exists_and_honors_the_disciplines(self):
        p = REPO / "install_supervisor.ps1"
        assert p.is_file(), "install_supervisor.ps1 must be a scripted artifact"
        text = p.read_text(encoding="utf-8")
        # nssm install of the --serve entry point.
        assert "nssm" in text.lower()
        assert "install" in text
        assert "--serve" in text
        # Runs under John's account, env cloned from the anchor service.
        assert "ObjectName" in text
        assert ".\\john" in text          # the .\john service account literal
        assert "AppEnvironmentExtra" in text
        # No-console discipline + loopback-only IPC + the supervisor token.
        assert "AppNoConsole" in text
        assert "127.0.0.1" in text
        assert "ANCHOR_SUPERVISOR_TOKEN" in text

    def test_serve_entrypoint_exists(self):
        import supervisor
        assert hasattr(supervisor, "serve")
        assert hasattr(supervisor, "SupervisorServer")


# ══════════════════════════════════════════════════════════════════════════════
# 10) The IPC contract artifacts remain intact (unchanged by W16)
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifactsIntact:
    def test_contract_and_rebuild_tables_still_resolve(self):
        import supervisor
        assert supervisor.unresolved_rebuild_rows() == []
        names = {r["interaction"] for r in supervisor.IPC_CONTRACT}
        assert {"launch", "tail-cursor-durability", "gate-answer"} <= names
