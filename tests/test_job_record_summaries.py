"""The jobs index stays small and current without changing durable records."""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

import job_runner


@pytest.fixture
def record_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(job_runner, "jobs_dir", lambda: tmp_path)
    return tmp_path


def write_record(record_dir, record):
    path = record_dir / (record["job_id"] + ".json")
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_summary_omits_large_private_payloads_and_keeps_full_records(record_dir):
    metadata = {
        "job_id": "job-large", "project_id": "project-a", "lane": "build",
        "status": "running", "started_at": 123.0, "backend": "codex",
        "session_id": "session-a", "cost": {"usd": 0.25, "tokens": 800},
    }
    record = dict(metadata, crypt_token="secret", cwd="private-path",
                  relaunch_spec={"prompt": "x" * (2 * 1024 * 1024)},
                  refinement_handoff={"prompt": "private-handoff"},
                  model_receipt={"details": "private-receipt"})
    write_record(record_dir, record)

    assert job_runner.list_record_summaries() == [metadata]
    assert len(json.dumps(job_runner.list_record_summaries())) < 1000
    assert job_runner.list_records() == [record]
    assert job_runner.load_record("job-large") == record


def test_unchanged_records_are_not_reread_and_caller_cannot_change_cache(
        record_dir, monkeypatch):
    write_record(record_dir, {
        "job_id": "job-a", "status": "running", "cost": {"usd": 0.25},
    })
    original_read = Path.read_text
    reads = []

    def tracked_read(path, *args, **kwargs):
        if path.parent == record_dir:
            reads.append(path.name)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read)
    first = job_runner.list_record_summaries()
    first[0]["status"] = "changed-by-caller"
    first[0]["cost"]["usd"] = 999

    assert job_runner.list_record_summaries() == [{
        "job_id": "job-a", "status": "running", "cost": {"usd": 0.25},
    }]
    assert reads == ["job-a.json"]


def test_record_replacement_deletion_and_recreation_refresh_cache(record_dir):
    record = {"job_id": "job-a", "status": "running"}
    path = write_record(record_dir, record)
    assert job_runner.list_record_summaries()[0]["status"] == "running"
    original_stat = path.stat()
    replacement = record_dir / "replacement.tmp"
    replacement.write_text(json.dumps(dict(record, status="success")),
                           encoding="utf-8")
    os.utime(replacement, ns=(original_stat.st_atime_ns,
                             original_stat.st_mtime_ns + 1_000_000))
    replacement.replace(path)
    assert job_runner.list_record_summaries()[0]["status"] == "success"

    success_stat = path.stat()
    path.unlink()
    assert job_runner.list_record_summaries() == []
    write_record(record_dir, record)
    # Reusing the deleted file's signature must not revive its old cache row.
    os.utime(path, ns=(success_stat.st_atime_ns, success_stat.st_mtime_ns))
    assert path.stat().st_size == success_stat.st_size
    assert job_runner.list_record_summaries()[0]["status"] == "running"


def test_overlapping_callers_share_one_scan_and_get_independent_results(
        record_dir, monkeypatch):
    path = write_record(record_dir, {
        "job_id": "job-a", "status": "running", "cost": {"usd": 0.25},
    })
    read_started = threading.Event()
    release_read = threading.Event()
    all_entering_lock = threading.Event()
    counter_lock = threading.Lock()
    counters = {"lock_entries": 0, "reads": 0, "stats": 0}
    original_lock = job_runner._JOB_SUMMARY_LOCK
    original_read = Path.read_text
    original_stat = Path.stat

    class ObservedLock:
        def __enter__(self):
            with counter_lock:
                counters["lock_entries"] += 1
                if counters["lock_entries"] == 4:
                    all_entering_lock.set()
            return original_lock.__enter__()

        def __exit__(self, *args):
            return original_lock.__exit__(*args)

    def blocking_read(candidate, *args, **kwargs):
        if candidate == path:
            with counter_lock:
                counters["reads"] += 1
            read_started.set()
            assert release_read.wait(timeout=5)
        return original_read(candidate, *args, **kwargs)

    def counted_stat(candidate, *args, **kwargs):
        if candidate == path:
            with counter_lock:
                counters["stats"] += 1
        return original_stat(candidate, *args, **kwargs)

    monkeypatch.setattr(job_runner, "_JOB_SUMMARY_LOCK", ObservedLock())
    monkeypatch.setattr(Path, "read_text", blocking_read)
    monkeypatch.setattr(Path, "stat", counted_stat)
    with ThreadPoolExecutor(max_workers=4) as pool:
        try:
            first = pool.submit(job_runner.list_record_summaries)
            assert read_started.wait(timeout=5)
            followers = [pool.submit(job_runner.list_record_summaries)
                         for _ in range(3)]
            # The first scan cannot finish until every follower has observed
            # the old generation and reached the locked cache boundary.
            assert all_entering_lock.wait(timeout=5)
        finally:
            release_read.set()
        results = [future.result(timeout=5) for future in [first] + followers]

    assert counters["reads"] == 1
    assert counters["stats"] == 1
    assert all(result == results[0] for result in results)
    results[0][0]["cost"]["usd"] = 999
    assert all(result[0]["cost"]["usd"] == 0.25 for result in results[1:])


def test_sidecars_invalid_records_and_missing_directory_are_skipped(
        record_dir, monkeypatch):
    write_record(record_dir, {"job_id": "job-a", "status": "done"})
    for name, body in (("job-a.gate.json", "{}"),
                       ("job-a.cursor.json", "{}"),
                       ("broken.json", "{"), ("wrong-shape.json", "[]")):
        (record_dir / name).write_text(body, encoding="utf-8")
    assert job_runner.list_record_summaries() == [
        {"job_id": "job-a", "status": "done"},
    ]
    monkeypatch.setattr(job_runner, "jobs_dir", lambda: record_dir / "missing")
    assert job_runner.list_record_summaries() == []


def test_jobs_http_uses_summaries_and_preserves_project_filter_and_order(
        record_dir, monkeypatch):
    import anchor_gui

    for job_id, project_id, started_at in (("old-a", "a", 1),
                                           ("new-a", "a", 3),
                                           ("other-b", "b", 2)):
        write_record(record_dir, {
            "job_id": job_id, "project_id": project_id,
            "started_at": started_at, "status": "done",
            "crypt_token": "secret", "relaunch_spec": {"prompt": "private"},
        })

    def full_records_are_not_the_index():
        raise AssertionError("The HTTP jobs index loaded full records")

    monkeypatch.setattr(job_runner, "list_records", full_records_are_not_the_index)
    server = ThreadingHTTPServer(("127.0.0.1", 0), anchor_gui.AnchorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    try:
        with urlopen(base + "/api/rnd/jobs?project_id=a", timeout=4) as response:
            filtered = json.load(response)
        assert filtered["ok"] is True
        assert [row["job_id"] for row in filtered["jobs"]] == ["new-a", "old-a"]
        with urlopen(base + "/api/rnd/jobs", timeout=4) as response:
            all_jobs = json.load(response)
        assert [row["job_id"] for row in all_jobs["jobs"]] == [
            "new-a", "other-b", "old-a",
        ]
        assert all("crypt_token" not in row and "relaunch_spec" not in row
                   for row in all_jobs["jobs"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
