"""Integration regressions for the second delegation hardening review.

These use real disposable Git repositories and check processes. No model is
called: the existing workflow fixture supplies the producer and reviewer.
"""

import json
import sys
import time
from pathlib import Path

from steward_cockpit import code_job_handoff as ch, code_jobs as cj
from tools import steward_code_job as cli

from tests.test_delegation_workflow_2026_10_10 import (
    FAIL,
    PASS,
    await_job,
    project,
)


def test_recovery_preserves_sibling_landed_before_failed_integration(
    project, monkeypatch
):
    root, workers, factory = project
    cdir = root / "A"
    first = cj.start(
        cdir,
        root / "B",
        "Produce only B/first.py",
        PASS,
        outputs=["B/first.py"],
        engine_factory=factory,
    )
    assert first["ok"], first
    second = cj.start(
        cdir,
        root / "B",
        "Produce only B/sibling.py",
        PASS,
        outputs=["B/sibling.py"],
        engine_factory=factory,
    )
    assert second["ok"], second
    sibling = "sibling_answer = 84\n"
    workers[1].produce({"B/sibling.py": sibling})
    sibling_job = await_job(cdir, second["job"])
    assert sibling_job["landed"] and sibling_job["verified"], sibling_job

    original_run_check = cj.run_check
    check_calls = []

    def fail_only_integration(job, tree):
        check_calls.append(Path(tree))
        if len(check_calls) == 2:
            job = {**job, "check": FAIL}
        return original_run_check(job, tree)

    monkeypatch.setattr(cj, "run_check", fail_only_integration)
    first_contents = "first_answer = 42\n"
    workers[0].produce({"B/first.py": first_contents})
    failed = await_job(cdir, first["job"])
    assert len(check_calls) == 2, failed
    assert not failed["landed"], failed
    assert (root / "B/sibling.py").read_text() == sibling

    monkeypatch.setattr(cj, "run_check", original_run_check)
    recovered = ch.recover(cdir, first["job"], check=PASS)
    assert recovered["ok"], recovered
    assert recovered["worker_restarted"] is False
    finished = await_job(cdir, first["job"], attempt=2)
    assert finished["landed"] and finished["verified"], finished
    assert (root / "B/first.py").read_text() == first_contents
    assert (root / "B/sibling.py").read_text() == sibling
    assert len(workers) == 2


def test_stop_during_real_check_preserves_work_without_reporting_check_failure(
    project, tmp_path
):
    root, workers, factory = project
    cdir = root / "A"
    marker = tmp_path / "check-started.txt"
    check = [
        sys.executable,
        "-c",
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).write_text('running'); time.sleep(60)",
    ]
    started = cj.start(
        cdir,
        root / "B",
        "Produce only B/result.py",
        check,
        outputs=["B/result.py"],
        engine_factory=factory,
    )
    assert started["ok"], started
    jid = started["job"]
    produced = "answer = 42\n"
    try:
        workers[0].produce({"B/result.py": produced})
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert marker.exists(), cj.read_jobs(cdir).get(jid)
        cj.stop(cdir, jid, actor="human")
        stopped = await_job(cdir, jid)
        assert stopped["status"] == "stopped", stopped
        assert stopped.get("check_ok") is not False, stopped
        assert ch.check_state(stopped) == "not_run", stopped
        assert not stopped.get("landed"), stopped
        assert (workers[0].wt / "B/result.py").read_text() == produced
        assert not (root / "B/result.py").exists()
    finally:
        if (cj.read_jobs(cdir).get(jid) or {}).get("status") in cj.LIVE:
            cj.stop(cdir, jid, actor="human")


def test_direct_start_rejects_relative_repo_before_worker_allocation(
    project, monkeypatch
):
    root, workers, factory = project
    monkeypatch.chdir(root)
    result = cj.start(
        root / "A",
        Path("B"),
        "Produce only B/result.py",
        PASS,
        outputs=["B/result.py"],
        engine_factory=factory,
    )
    assert not result["ok"], result
    assert "absolute" in str(result).lower(), result
    assert workers == []


def test_stop_only_during_integration_preserves_the_passed_coder_check(project, tmp_path):
    root, workers, factory = project
    cdir = root / "A"
    marker = tmp_path / "integration-check-started"
    check = [sys.executable, "-c",
             "from pathlib import Path; import time\n"
             "if Path('B/sibling.py').exists():\n"
             f" Path({str(marker)!r}).write_text('integration')\n"
             " time.sleep(60)\n"]
    first = cj.start(cdir, root / "B", "Produce B/first.py", check, engine_factory=factory)
    second = cj.start(cdir, root / "B", "Produce B/sibling.py", PASS, engine_factory=factory)
    assert first["ok"] and second["ok"]
    workers[1].produce({"B/sibling.py": "sibling = 84\n"})
    assert await_job(cdir, second["job"])["landed"]
    try:
        workers[0].produce({"B/first.py": "first = 42\n"})
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert marker.exists(), cj.read_jobs(cdir)
        assert cj.read_jobs(cdir)[first["job"]]["check_ok"] is True
        assert cj.stop(cdir, first["job"], actor="human")["ok"]
        stopped = await_job(cdir, first["job"])
        assert stopped["status"] == "stopped" and stopped["stopped_by"] == "human"
        assert stopped["check_ok"] is True
        assert stopped["integration_check_ok"] is None
        assert not stopped["landed"] and not stopped.get("placed")
        assert not (root / "B/first.py").exists()
        assert (root / "B/sibling.py").read_text() == "sibling = 84\n"
        assert (workers[0].wt / "B/first.py").read_text() == "first = 42\n"
        assert len(workers) == 2
    finally:
        if (cj.read_jobs(cdir).get(first["job"]) or {}).get("status") in cj.LIVE:
            cj.stop(cdir, first["job"], actor="human")


def test_cli_resolves_relative_repo_against_callers_working_directory(
    project, monkeypatch
):
    root, workers, _factory = project
    cdir = root / "A"
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def capture(request, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.chdir(cdir)
    monkeypatch.setattr(cli, "project_for", lambda _cwd: ("fixture", "A"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", capture)
    monkeypatch.setenv("ANCHOR_TOKEN", "test-only")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "steward_code_job.py",
            "start",
            "--repo",
            "../B",
            "--brief",
            "Produce only B/result.py",
            "--check-argv",
            json.dumps(PASS),
            "--output",
            "B/result.py",
        ],
    )
    cli.main()
    assert len(requests) == 1
    assert Path(requests[0]["repo"]) == (root / "B").resolve()
    assert Path(requests[0]["repo"]).is_absolute()
    assert workers == []
