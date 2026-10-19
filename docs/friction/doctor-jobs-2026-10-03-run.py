"""Run the real Doctor suite in an owned snapshot, then probe live jobs.

This one-off runner deliberately retains its snapshot and staged report. It never
publishes over the daily report or deletes campaign data. Run from the main agent
only after activating the repaired service; publish the reviewed staged report
when its full-suite result and live-route receipt are both successful.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


CODE_DIR = Path(__file__).resolve().parents[2]
FRICTION_DIR = CODE_DIR / "docs" / "friction"
REQUIRED_FILES = (
    "DASHBOARD.md",
    "PROJECTS.md",
    "INBOX.md",
    "CANCELLED.md",
    "SAVED_FOR_LATER.md",
    "WEEKLY_REVIEW.md",
)
TERMINAL_STATUSES = {"done", "failed", "cancelled", "interrupted"}


def _hide_child_processes() -> None:
    if os.name != "nt":
        return
    original_popen = subprocess.Popen
    creationflags_index = list(inspect.signature(original_popen).parameters).index("creationflags")

    class HiddenPopen(original_popen):
        def __init__(self, *args, **kwargs):
            if len(args) > creationflags_index:
                positional = list(args)
                positional[creationflags_index] = int(positional[creationflags_index] or 0) | subprocess.CREATE_NO_WINDOW
                args = tuple(positional)
            else:
                kwargs["creationflags"] = int(kwargs.get("creationflags", 0) or 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    # Install before Anchor imports so direct Popen imports also receive it.
    # Existing flags, including breakaway/process-group flags, are retained.
    subprocess.Popen = HiddenPopen


def _check_plain_source(path: Path) -> None:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise RuntimeError(f"Refusing to follow linked snapshot source: {path}")


def _copy_document(source: Path, destination: Path) -> dict:
    _check_plain_source(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    destination.write_bytes(raw)
    return {"name": source.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _snapshot(source: Path, destination: Path) -> dict:
    _check_plain_source(source)
    destination.mkdir(parents=True)
    documents = []
    for filename in REQUIRED_FILES:
        documents.append(_copy_document(source / filename, destination / filename))
    domains_source = source / "domains"
    _check_plain_source(domains_source)
    for domain in sorted(domains_source.glob("*.md")):
        documents.append(_copy_document(domain, destination / "domains" / domain.name))
    if (source / "settings.json").exists():
        documents.append(_copy_document(source / "settings.json", destination / "settings.json"))

    jobs_source = source / "rnd_jobs"
    _check_plain_source(jobs_source)
    jobs_destination = destination / "rnd_jobs"
    jobs_destination.mkdir()
    source_digest = hashlib.sha256()
    copied = 0
    inert_records = 0
    skipped_nonterminal = 0
    source_bytes = 0
    snapshot_bytes = 0
    for record_path in sorted(jobs_source.glob("*.json")):
        if record_path.name.endswith((".gate.json", ".cursor.json")):
            continue
        _check_plain_source(record_path)
        raw = record_path.read_bytes()
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            record = None
        if isinstance(record, dict) and record.get("status") not in TERMINAL_STATUSES:
            skipped_nonterminal += 1
            continue
        source_digest.update(record_path.name.encode("utf-8"))
        source_digest.update(b"\0")
        source_digest.update(raw)
        source_bytes += len(raw)
        # retry_terminal_handoffs explicitly skips metadata-only rows. This
        # changes only copies, retaining large payloads without following their
        # historical campaign paths during isolated server startup.
        if isinstance(record, dict):
            record["metadata_only"] = True
            projected = json.dumps(record, ensure_ascii=False).encode("utf-8")
        else:
            # The real job reader ignores malformed/non-object records; retain
            # those inert bytes so this snapshot preserves its scanning work.
            inert_records += 1
            projected = raw
        (jobs_destination / record_path.name).write_bytes(projected)
        snapshot_bytes += len(projected)
        copied += 1
    return {
        "documents": documents,
        "job_records_copied": copied,
        "inert_job_records_copied": inert_records,
        "job_records_skipped_nonterminal": skipped_nonterminal,
        "source_job_bytes": source_bytes,
        "snapshot_job_bytes": snapshot_bytes,
        "source_job_digest_sha256": source_digest.hexdigest(),
        "job_projection": "Terminal copies set metadata_only=true; all other payload fields retained.",
        "private_registries": "Live rnd_registry, sessions, .anchor records and campaign directories were not copied.",
    }


def _live_probe(base: str, path: str) -> dict:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=4.0) as response:
            headers_elapsed = time.perf_counter() - started
            body = response.read()
            result = {
                "path": path,
                "status": response.status,
                "headers_seconds": round(headers_elapsed, 6),
                "total_seconds": round(time.perf_counter() - started, 6),
                "body_bytes": len(body),
                "ok": response.status == 200,
            }
        if path == "/api/rnd/jobs":
            parsed = json.loads(body)
            if not isinstance(parsed, dict) or parsed.get("ok") is not True or not isinstance(parsed.get("jobs"), list):
                raise ValueError("Live jobs response does not contain the expected jobs list")
            result["job_rows"] = len(parsed["jobs"])
        return result
    except Exception as exc:
        return {
            "path": path,
            "ok": False,
            "error": type(exc).__name__,
            "total_seconds": round(time.perf_counter() - started, 6),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data", type=Path, default=CODE_DIR)
    parser.add_argument("--live-base", default="http://127.0.0.1:8777")
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root or Path(tempfile.mkdtemp(prefix="anchor-doctor-jobs-20261003-"))
    run_root = run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    _check_plain_source(run_root)
    data_root = run_root / "data"
    snapshot = _snapshot(args.source_data.resolve(), data_root)

    # Set these before importing any Anchor module; data_dir is environment-led.
    os.environ["ANCHOR_DATA_DIR"] = str(data_root)
    os.environ["ANCHOR_PROACTIVE_SUMMARY"] = "0"
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    os.environ["ANCHOR_ENGINE_CMD"] = subprocess.list2cmdline([sys.executable, "-c", "pass"])
    os.environ["PYTEST_CURRENT_TEST"] = "doctor-isolated-verification"
    os.environ["ANCHOR_SIDECAR_DIR"] = str(Path.home() / ".claude" / "projects")
    _hide_child_processes()
    sys.path.insert(0, str(CODE_DIR))
    import anchor_healthcheck as healthcheck

    # The healthcheck helper returns an unused requested port unchanged, even
    # when it is zero. Ask the OS for a concrete ephemeral port instead.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        test_port = port_socket.getsockname()[1]
    if test_port in (0, 8777, 8778):
        raise RuntimeError(f"Refusing invalid or live-service test port: {test_port}")
    healthcheck.TEST_PORT = test_port
    healthcheck.REPORTS_DIR = run_root / "health_reports"
    healthcheck.REPORTS_DIR.mkdir()
    # Legacy maintenance kills any aged listener on production/default test
    # ports. The test listener here is owned and fresh; preserve other services.
    healthcheck.cleanup_stale_processes = lambda report: None

    original_report = args.source_data.resolve() / "health_reports" / f"{healthcheck.TODAY}.md"
    before_report = FRICTION_DIR / "2026-10-03-doctor-before-jobs.md"
    if original_report.exists() and not before_report.exists():
        _check_plain_source(original_report)
        shutil.copy2(original_report, before_report)

    verification = {
        "run_root": str(run_root),
        "source_data": str(args.source_data.resolve()),
        "test_port": healthcheck.TEST_PORT,
        "snapshot": snapshot,
        "suite": "Actual anchor_healthcheck.main, with all correctness checks retained.",
        "cleanup": "Port/age-based unrelated-listener termination omitted; owned test server teardown retained.",
        "live_base": args.live_base,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    verification_path = run_root / "verification.json"
    verification_path.write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(json.dumps({
        "phase": "starting_full_health_check",
        "run_root": str(run_root),
        "test_port": healthcheck.TEST_PORT,
    }), flush=True)
    suite_started = time.perf_counter()
    try:
        result = healthcheck.main()
        suite_exit = int(result or 0)
    except SystemExit as exc:
        suite_exit = int(exc.code or 0)
    verification["suite_exit_code"] = suite_exit
    verification["suite_seconds"] = round(time.perf_counter() - suite_started, 3)
    verification["live_probes"] = [
        _live_probe(args.live_base, "/api/version"),
        _live_probe(args.live_base, "/api/rnd/jobs"),
    ]
    verification["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    staged_report = healthcheck.REPORTS_DIR / f"{healthcheck.TODAY}.md"
    verification["staged_report"] = str(staged_report)
    verification["ready_to_publish"] = suite_exit == 0 and all(
        probe["ok"] for probe in verification["live_probes"]
    )
    if staged_report.exists():
        jobs = verification["live_probes"][1]
        live_receipt = (
            f"HTTP {jobs['status']}; headers {jobs['headers_seconds']:.3f}s; "
            f"body {jobs['body_bytes']:,} bytes; {jobs.get('job_rows', '?')} rows"
            if jobs["ok"]
            else f"FAILED: {jobs.get('error', 'unknown error')}"
        )
        scope = (
            "\n\n## Verification scope for the jobs timeout repair\n\n"
            "The complete correctness suite ran against an owned data snapshot and an unused port. "
            "Current root/domain task documents and settings were copied. "
            f"The snapshot retained {snapshot['job_records_copied']:,} terminal or inert job records "
            f"({snapshot['source_job_bytes']:,} source bytes), with their existing payload fields. "
            "Only copied records were marked metadata-only to prevent historical campaign handoff writes. "
            f"{snapshot['job_records_skipped_nonterminal']:,} nonterminal records were excluded. "
            "Live session/campaign registries and campaign directories were not copied. "
            "The real sidecar folder was checked read-only. Port/age-based cleanup of unrelated "
            "listeners was omitted; every correctness check and owned-server teardown remained enabled.\n\n"
            f"After the suite, the active service GET /api/rnd/jobs probe with a four-second timeout returned: {live_receipt}. "
            "The active service /api/version was also probed. No live write routes were exercised.\n\n"
            f"Detailed receipt: `{verification_path}`. This report was staged for explicit publication "
            "after review of both suite and active-service results.\n"
        )
        with staged_report.open("a", encoding="utf-8") as report_file:
            report_file.write(scope)
    verification_path.write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(json.dumps({
        "suite_exit_code": suite_exit,
        "ready_to_publish": verification["ready_to_publish"],
        "staged_report": str(staged_report),
        "verification": str(verification_path),
        "live_jobs": verification["live_probes"][1],
    }, indent=2))
    return 0 if verification["ready_to_publish"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
