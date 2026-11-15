"""Wave 4 tests: Status Daemon, Bounded Log Tail, Zero-Cadence Clutter & 5-State Failure Contract (2026-11-13)."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import git_safety
from steward_cockpit import (
    code_job_handoff,
    code_jobs,
    skill_jobs,
    steward_campaign as campaign,
    steward_engine as engine,
    steward_routes as routes,
)


@pytest.fixture(autouse=True)
def _isolated_anchor(tmp_path, monkeypatch):
    data_dir = tmp_path / "_anchor_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(engine, "STATE_FILE", str(data_dir / "steward-state.json"))

    saved_efforts = set(campaign._ACTIVE_EFFORTS)
    saved_last_push = dict(campaign._LAST_DAEMON_PUSH)
    saved_seq = dict(campaign._STATUS_SEQ_BY_DIR)
    saved_engines = dict(routes.ENGINES)

    campaign._ACTIVE_EFFORTS.clear()
    campaign._LAST_DAEMON_PUSH.clear()
    campaign._STATUS_SEQ_BY_DIR.clear()
    campaign._JSON_FILE_CACHE.clear()
    campaign._NEWEST_LOG_CACHE.clear()
    routes.ENGINES.clear()
    routes._DELIV_CACHE.clear()
    routes._STATE_CACHE.clear()
    try:
        yield
    finally:
        campaign._ACTIVE_EFFORTS.clear()
        campaign._ACTIVE_EFFORTS.update(saved_efforts)
        campaign._LAST_DAEMON_PUSH.clear()
        campaign._LAST_DAEMON_PUSH.update(saved_last_push)
        campaign._STATUS_SEQ_BY_DIR.clear()
        campaign._STATUS_SEQ_BY_DIR.update(saved_seq)
        campaign._JSON_FILE_CACHE.clear()
        campaign._NEWEST_LOG_CACHE.clear()
        routes.ENGINES.clear()
        routes.ENGINES.update(saved_engines)
        routes._DELIV_CACHE.clear()
        routes._STATE_CACHE.clear()


def _seed_campaign(cdir: Path, *, step_id: str = "step-1", status_source: str = "") -> Path:
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text(
        "# Face\n\n## North Star\nDeliver reliable 60s cockpit status telemetry.\n",
        encoding="utf-8",
    )
    roadmap = {
        "roadmap_projection": [
            {
                "id": step_id,
                "name": "Wave 4 Status Daemon",
                "status": "active",
                "part": "slice",
                "gate": "pytest -q",
                "commissioned_as": "Foreman",
            }
        ],
        "roadmap_events": [],
    }
    (cdir / "roadmap.json").write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    strip = {
        "phase": "build",
        "active_effort": "Wave 4 Status Daemon",
        "current_step_id": step_id,
        "human_wait": "none",
        "next_recommended": "Verify Wave 4 tests",
    }
    if status_source:
        strip["current_skill_status_source"] = status_source
    (cdir / "strip.json").write_text(json.dumps(strip, indent=2), encoding="utf-8")
    return cdir


def _seq_of(status_id: str) -> int:
    assert "#" in status_id, f"expected monotonic #<seq> suffix on status_id, got {status_id!r}"
    base, seq_txt = status_id.rsplit("#", 1)
    assert base.isdigit() and seq_txt.isdigit()
    return int(seq_txt)


def test_zero_cadence_clutter_journal_receipt_v1_html_and_shared_js_target_lock(tmp_path, monkeypatch):
    cdir = _seed_campaign(tmp_path / "campaign_cadence")
    eng = engine.Engine(str(cdir))
    eng.fake = False

    @contextlib.contextmanager
    def _fake_repo_lock(*_args, **_kwargs):
        yield True

    def _fake_git_run(argv, **_kwargs):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=" M ECGBERHT.md\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(git_safety, "toplevel", lambda _p: str(cdir))
    monkeypatch.setattr(git_safety, "repo_lock", _fake_repo_lock)
    monkeypatch.setattr(engine.subprocess, "run", _fake_git_run)

    checkpoint_fn = getattr(eng, "_git_checkpoint", None) or eng._commit_if_dirty
    checkpoint_fn("steward cadence checkpoint")

    assert all("committed work-in-progress" not in str(ev.get("text") or "") for ev in eng.events)
    assert all(not (ev.get("t") == "sys" and ev.get("tick")) for ev in eng.events)

    strip_after = json.loads((cdir / "strip.json").read_text(encoding="utf-8"))
    receipts = strip_after.get("receipts") or []
    assert any(
        isinstance(r, dict)
        and r.get("kind") == "journal_update"
        and "cadence_commit: committed work-in-progress" in str(r.get("summary") or "")
        for r in receipts
    )

    eng_src = (REPO_ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert "committed work-in-progress (cadence)" not in eng_src

    v1_html = (REPO_ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    shared_js = (REPO_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")

    assert "data-msgs" not in v1_html
    assert "data-msgs" not in shared_js

    tf_idx = shared_js.index("function targetFor(ev)")
    tf_block = shared_js[tf_idx : shared_js.index("}", tf_idx) + 1]
    assert "paneEl()" not in tf_block
    assert "return scrollEl();" in tf_block

    assert 'document.visibilityState === "hidden"' in shared_js
    assert 'document.addEventListener("visibilitychange"' in shared_js
    assert "[60000, 120000, 300000]" in shared_js
    assert 'fetch(api("/api/status"))' in shared_js


def test_bounded_64kb_log_tail_reader_and_truncation_notice(tmp_path):
    cdir = _seed_campaign(
        tmp_path / "campaign_tail",
        status_source="_foreman-status.log",
    )
    stale_block = "\n".join(
        [
            "[09:00] Foreman build \u00b7 OldRun",
            "\u2500" * 33,
            "Effort   Stale Morning Effort",
            "Doing    Stale early wave 1",
            "Status   1/4 waves \u00b7 stale",
            "Tests    fail \u2717 \u00b7 old failure",
            "Blocker  none",
            "Procs    py 1 \u00b7 node 0",
            "Journal  none",
            "\u2500" * 33,
            "ETA      ~99m",
            "To do    Old task",
            "",
        ]
    )
    fresh_block = "\n".join(
        [
            "[15:40] Foreman build \u00b7 Anchor",
            "\u2500" * 33,
            "Effort   Wave 4 Status Daemon",
            "Doing    Validating bounded 64KB tail reader",
            "Status   4/4 waves \u00b7 execute",
            "Tests    pass \u2713 \u00b7 18 passed",
            "Blocker  none",
            "Procs    py 1 \u00b7 claude 0 \u00b7 node 1",
            "Journal  none",
            "\u2500" * 33,
            "ETA      15:55",
            "To do    Ship Wave 4",
            "",
        ]
    )
    filler = ("worker progress line: streaming incremental output safely\n" * 2800)
    full_payload = stale_block + filler + fresh_block
    assert len(full_payload.encode("utf-8")) > 150_000

    log_path = cdir / "_foreman-status.log"
    log_path.write_text(full_payload, encoding="utf-8")

    tail_text, truncated = campaign.read_log_tail_bounded(log_path)
    assert truncated is True
    assert len(tail_text.encode("utf-8")) <= campaign.MAX_STATUS_LOG_TAIL_BYTES
    assert "Stale early wave 1" not in tail_text
    assert "[15:40] Foreman build" in tail_text
    assert "Validating bounded 64KB tail reader" in tail_text

    look = campaign.status_lookthrough(str(cdir))
    assert look is not None
    assert look.get("truncated") is True
    assert look.get("truncation_note") == campaign.LOG_TAIL_TRUNCATED_NOTE
    assert look.get("table_at") == "15:40"

    composed = campaign.compose_status(str(cdir))
    assert composed.get("truncated") is True
    assert composed.get("truncation_note") == campaign.LOG_TAIL_TRUNCATED_NOTE
    assert campaign.LOG_TAIL_TRUNCATED_NOTE in (composed.get("now") or [])


def test_skill_jobs_persisted_log_path_own_log_true_and_monotonic_status_id_seq(tmp_path, monkeypatch):
    cdir = _seed_campaign(tmp_path / "campaign_skill_log")
    skill_root = tmp_path / "skills_root"
    gandalf_script = skill_root / "gandalf" / "run_gandalf.py"
    gandalf_script.parent.mkdir(parents=True, exist_ok=True)
    gandalf_script.write_text("print('stub gandalf')\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(skill_root))
    monkeypatch.setattr(skill_jobs, "_report", lambda *_a, **_kw: None)

    done_event = threading.Event()
    skill_table = "\n".join(
        [
            "[16:05] Gandalf review \u00b7 Anchor",
            "\u2500" * 33,
            "Effort   Wave 4 Deep Read",
            "Doing    Auditing 5-state failure contract",
            "Status   2/3 passes \u00b7 deep-read",
            "Tests    pass \u2713 \u00b7 9 checks green",
            "Blocker  none",
            "Procs    py 1 \u00b7 claude 0 \u00b7 node 0",
            "Journal  none",
            "\u2500" * 33,
            "ETA      16:20",
            "To do    Stamp final tier",
            "",
        ]
    )

    class _FakeProc:
        def __init__(self, ev: threading.Event):
            self._ev = ev
            self.pid = os.getpid()

        @property
        def returncode(self):
            return 0 if self._ev.is_set() else None

        def poll(self):
            return 0 if self._ev.is_set() else None

        def wait(self, timeout=None):
            if not self._ev.wait(timeout=timeout):
                raise subprocess.TimeoutExpired(cmd="gandalf", timeout=timeout or 0)
            return 0

    class _FakeRun:
        def __init__(self, ev: threading.Event):
            self.proc = _FakeProc(ev)
            self.pid = self.proc.pid
            self.wjob = object()

        def poll(self):
            return self.proc.poll()

        def end(self, _wait_s=60):
            self.proc._ev.set()
            return True

    def _fake_popen_contained(_argv, _cwd, _env, out_fh):
        out_fh.write(skill_table)
        out_fh.flush()
        return _FakeRun(done_event)

    monkeypatch.setattr(code_jobs, "_popen_contained", _fake_popen_contained)

    job_id = ""
    try:
        started = skill_jobs.start(
            str(cdir),
            ["python", str(gandalf_script)],
            label="Gandalf deep review",
            actor="steward",
        )
        assert started.get("ok") is True
        job_id = started["job"]
        assert started.get("log_path") == started.get("log")

        persisted = skill_jobs.read_jobs(str(cdir))[job_id]
        assert persisted.get("log_path") == started["log_path"]
        assert (cdir / persisted["log_path"]).is_file()

        who, phase, _started_ep, tests_line, finish = campaign.who_is_working(str(cdir), {}, [], None)
        assert "gandalf" in who.lower()
        assert "2/3 passes" in phase
        assert phase != "running"
        assert "pass \u2713" in tests_line
        assert "16:20" in finish

        s1 = campaign.compose_status(str(cdir))
        s2 = campaign.compose_status(str(cdir))
        assert s1.get("own_log") is True or (s1.get("running") or {}).get("own_log") is True
        assert (s1.get("running") or {}).get("own_log") is True
        assert (s1.get("running") or {}).get("log_path") == persisted["log_path"]

        seq1 = _seq_of(s1["status_id"])
        seq2 = _seq_of(s2["status_id"])
        assert seq2 > seq1
    finally:
        done_event.set()
        if job_id:
            for th in list(threading.enumerate()):
                if th.name == f"skill-job-{job_id}":
                    th.join(timeout=2.0)


def test_engine_independent_60s_status_daemon_and_immediate_job_phase_finish_pushes(tmp_path, monkeypatch):
    cdir = _seed_campaign(tmp_path / "campaign_daemon")
    wt = tmp_path / "job_wt"
    wt.mkdir(parents=True, exist_ok=True)

    # Confirm NO Engine is registered/running (Engine.proc is absent / parked).
    assert routes.ENGINES == {}

    daemon_thread = campaign.ensure_status_daemon_started()
    assert daemon_thread.is_alive() is True
    assert daemon_thread.daemon is True

    job_id = "20261113-160000-aa11bb"
    job_rec = {
        "id": job_id,
        "repo": str(tmp_path),
        "branch": f"steward-job-{job_id}",
        "worktree": str(wt),
        "base": "0" * 40,
        "brief": "Implement Wave 4 status daemon",
        "work_dir": "",
        "attempt": 1,
        "phase": "producing",
        "phase_at": time.time(),
        "check": ["python", "-c", "print('ok')"],
        "status": "running",
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steward_dir": str(cdir),
        "worker": "coder",
        "coder_family": "claude",
    }
    cj_path = cdir / ".ecgberht" / "code-jobs.json"
    cj_path.write_text(json.dumps({job_id: job_rec}, indent=2), encoding="utf-8")
    campaign._JSON_FILE_CACHE.clear()

    summary_path = cdir / ".ecgberht" / "status-summary.json"
    if summary_path.exists():
        summary_path.unlink()

    campaign.register_active_effort(str(cdir))
    ticked = campaign.status_daemon_tick(force=True)
    norm_ticked = {os.path.normcase(os.path.abspath(p)) for p in ticked}
    assert os.path.normcase(os.path.abspath(str(cdir))) in norm_ticked
    assert summary_path.is_file()

    snap_daemon = json.loads(summary_path.read_text(encoding="utf-8"))
    assert snap_daemon.get("push_reason") == "daemon_60s"
    seq_daemon = _seq_of(snap_daemon["status_id"])

    # Immediate push on code_jobs.phase(...)
    code_jobs.phase(job_rec, "checking", cdir=str(cdir))
    snap_phase = json.loads(summary_path.read_text(encoding="utf-8"))
    assert snap_phase.get("push_reason") == "code_job_phase:checking"
    seq_phase = _seq_of(snap_phase["status_id"])
    assert seq_phase > seq_daemon

    # Immediate push on code_jobs._finish(...)
    monkeypatch.setattr(code_jobs, "changed_paths", lambda *_a, **_kw: [])
    monkeypatch.setattr(code_jobs, "_unlanded", lambda *_a, **_kw: [])
    monkeypatch.setattr(code_jobs, "ignored_outputs", lambda *_a, **_kw: [])
    monkeypatch.setattr(code_jobs, "_locked_served_changes", lambda *_a, **_kw: [])
    monkeypatch.setattr(code_jobs, "speed_line", lambda *_a, **_kw: "")
    monkeypatch.setattr(code_jobs, "_cleanup", lambda *_a, **_kw: None)
    monkeypatch.setattr(code_jobs, "_report", lambda *_a, **_kw: None)
    monkeypatch.setattr(code_job_handoff, "snapshot", lambda _j: {"state": "none"})

    finishing_job = code_jobs._transition(str(cdir), job_id, ("running",), status="finishing")
    assert finishing_job is not None
    code_jobs._finish(
        str(cdir),
        job_id,
        finishing_job,
        {"text": "Wave 4 complete", "authors": ["claude"], "manifest": []},
    )
    snap_finish = json.loads(summary_path.read_text(encoding="utf-8"))
    assert snap_finish.get("push_reason") == "code_job_finish"
    seq_finish = _seq_of(snap_finish["status_id"])
    assert seq_finish > seq_phase

    # Immediate push on skill_jobs finish transition
    sj_id = "20261113-160200-cc22dd"
    sj_path = cdir / ".ecgberht" / "skill-jobs.json"
    sj_path.write_text(
        json.dumps(
            {
                sj_id: {
                    "id": sj_id,
                    "argv": ["python", "skills/gandalf/run.py"],
                    "label": "Gandalf check",
                    "status": "running",
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "log": ".ecgberht/skill-logs/sj.log",
                    "log_path": ".ecgberht/skill-logs/sj.log",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (cdir / ".ecgberht" / "skill-logs").mkdir(parents=True, exist_ok=True)
    (cdir / ".ecgberht" / "skill-logs" / "sj.log").write_text("", encoding="utf-8")
    campaign._JSON_FILE_CACHE.clear()

    skill_jobs._transition(
        str(cdir),
        sj_id,
        ("running",),
        status="done",
        finished=time.strftime("%Y-%m-%d %H:%M:%S"),
        rc=0,
    )
    snap_skill_finish = json.loads(summary_path.read_text(encoding="utf-8"))
    assert snap_skill_finish.get("push_reason") == "skill_job_finish"
    seq_skill_finish = _seq_of(snap_skill_finish["status_id"])
    assert seq_skill_finish > seq_finish


def test_wave4_five_state_failure_contract_unknown_not_equal_empty(tmp_path):
    cdir = _seed_campaign(tmp_path / "campaign_contract")
    sj_file = cdir / ".ecgberht" / "skill-jobs.json"
    logs_dir = cdir / ".ecgberht" / "skill-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 1. empty-but-valid -> HTTP 200, ok=True, "Quiet — no active run"
    body_empty, code_empty = routes.handle_get(str(cdir), "status", {})
    assert code_empty == 200
    assert body_empty["ok"] is True
    assert body_empty["failure_state"] == "empty-but-valid"
    assert body_empty["message"] == "Quiet \u2014 no active run"

    # 2. dependency-missing -> HTTP 503, ok=False, "Worker log missing — status unknown"
    sj_file.write_text(
        json.dumps(
            {
                "sj-missing": {
                    "id": "sj-missing",
                    "status": "running",
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "log_path": ".ecgberht/skill-logs/does-not-exist.log",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    campaign._JSON_FILE_CACHE.clear()
    body_missing, code_missing = routes.handle_get(str(cdir), "status", {})
    assert code_missing == 503
    assert body_missing["ok"] is False
    assert body_missing["failure_state"] == "dependency-missing"
    assert body_missing["message"] == "Worker log missing \u2014 status unknown"

    # 3a. dependency-slow-or-killed (stalled/exited) -> HTTP 200, ok=False
    stalled_log = logs_dir / "stalled.log"
    stalled_log.write_text("worker started\n", encoding="utf-8")
    sj_file.write_text(
        json.dumps(
            {
                "sj-stalled": {
                    "id": "sj-stalled",
                    "status": "running",
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "log_path": ".ecgberht/skill-logs/stalled.log",
                    "process": {"state": "exited"},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    campaign._JSON_FILE_CACHE.clear()
    body_stalled, code_stalled = routes.handle_get(str(cdir), "status", {})
    assert code_stalled == 200
    assert body_stalled["ok"] is False
    assert body_stalled["failure_state"] == "dependency-slow-or-killed"
    assert body_stalled["message"] == "Worker process exited/stalled \u2014 inspect job record"

    # 3b. dependency-slow-or-killed (timed_out=True) -> HTTP 504, ok=False
    sj_file.write_text(
        json.dumps(
            {
                "sj-timeout": {
                    "id": "sj-timeout",
                    "status": "running",
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "log_path": ".ecgberht/skill-logs/stalled.log",
                    "timed_out": True,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    campaign._JSON_FILE_CACHE.clear()
    body_timeout, code_timeout = routes.handle_get(str(cdir), "status", {})
    assert code_timeout == 504
    assert body_timeout["ok"] is False
    assert body_timeout["failure_state"] == "dependency-slow-or-killed"
    assert body_timeout["message"] == "Worker process exited/stalled \u2014 inspect job record"

    # 4. dependency-returns-garbage -> HTTP 200, ok=True, raw_tail preserved
    garbage_log = logs_dir / "garbage.log"
    garbage_log.write_text(
        "<<<CORRUPT WORKER STREAM>>>\nmalformed table fragment without Effort/Doing rows\nraw_diag=42\n",
        encoding="utf-8",
    )
    sj_file.write_text(
        json.dumps(
            {
                "sj-garbage": {
                    "id": "sj-garbage",
                    "status": "running",
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "log_path": ".ecgberht/skill-logs/garbage.log",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    campaign._JSON_FILE_CACHE.clear()
    body_garbage, code_garbage = routes.handle_get(str(cdir), "status", {})
    assert code_garbage == 200
    assert body_garbage["ok"] is True
    assert body_garbage["failure_state"] == "dependency-returns-garbage"
    assert body_garbage["message"] == "Malformed worker status block \u2014 raw tail preserved"
    assert "raw_diag=42" in str(body_garbage.get("raw_tail") or "")

    # 5. backing-store-unreadable -> HTTP 500, ok=False, "Status ledger unreadable (unknown)" (unknown != empty)
    (cdir / ".ecgberht" / "status-summary.json").write_text("{corrupt-json!!!", encoding="utf-8")
    campaign._JSON_FILE_CACHE.clear()
    body_corrupt, code_corrupt = routes.handle_get(str(cdir), "status", {})
    assert code_corrupt == 500
    assert body_corrupt["ok"] is False
    assert body_corrupt["failure_state"] == "backing-store-unreadable"
    assert body_corrupt["failure_state"] != "empty-but-valid"
    assert body_corrupt["message"] == "Status ledger unreadable (unknown)"

