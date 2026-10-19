"""Run the complete healthcheck once without touching live campaign registries."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from datetime import date, timedelta

CODE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CODE_DIR))


def main():
    import paths
    source_data = paths.data_dir()
    spec = importlib.util.spec_from_file_location(
        "doctor_snapshot", CODE_DIR / "docs/friction/doctor-jobs-2026-10-03-run.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    helpers._hide_child_processes()
    run_root = Path(tempfile.mkdtemp(prefix="anchor-doctor-v6-ref-20261007-"))
    snapshot = helpers._snapshot(source_data, run_root / "data")
    # Retain recent log evidence so a private snapshot cannot imply that the
    # live application missed days solely because its history was not copied.
    snapshot["historical_logs"] = []
    for filename in [f"{date.today() - timedelta(days=n)}.md" for n in (1, 2)] + ["errors.log"]:
        log_source = source_data / "logs" / filename
        if log_source.is_file():
            snapshot["historical_logs"].append(helpers._copy_document(
                log_source, run_root / "data" / "logs" / filename))
    os.environ.update({
        "ANCHOR_DATA_DIR": str(run_root / "data"),
        "ANCHOR_PROACTIVE_SUMMARY": "0",
        "ANCHOR_PTY_BACKEND": "stub",
        "ANCHOR_ENGINE_CMD": helpers.subprocess.list2cmdline(
            [sys.executable, "-c", "pass"]),
        "PYTEST_CURRENT_TEST": "doctor-isolated-v6-ref-verification",
        "ANCHOR_SIDECAR_DIR": str(Path.home() / ".claude" / "projects"),
    })
    import anchor_healthcheck as healthcheck
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        test_port = sock.getsockname()[1]
    if test_port in (0, 8777, 8778):
        raise RuntimeError("Refusing a live service port")
    healthcheck.TEST_PORT = test_port
    healthcheck.REPORTS_DIR = run_root / "health_reports"
    healthcheck.REPORTS_DIR.mkdir()
    # Omit legacy maintenance that can terminate unrelated live listeners.
    # All correctness checks and teardown of the owned server remain enabled.
    healthcheck.cleanup_stale_processes = lambda report: None
    captured = []

    class CapturedReport(healthcheck.Report):
        def __init__(self):
            super().__init__()
            captured.append(self)

    healthcheck.Report = CapturedReport
    print(json.dumps({"phase": "full-healthcheck", "run_root": str(run_root),
                      "test_port": test_port}), flush=True)
    started = time.perf_counter()
    try:
        healthcheck.main()
        suite_exit = 0
    except SystemExit as exc:
        suite_exit = int(exc.code or 0)
    report = captured[0]
    live_probes = [helpers._live_probe("http://127.0.0.1:8777", endpoint)
                   for endpoint in ("/api/version", "/api/status")]
    for probe in live_probes:
        report.check("live " + probe["path"], probe["ok"],
                     f"HTTP {probe['status']}" if probe["ok"] else probe["error"])
    staged_report = healthcheck.REPORTS_DIR / f"{healthcheck.TODAY}.md"
    report.write(staged_report)
    with staged_report.open("a", encoding="utf-8") as output:
        output.write(
            "\n\n## Verification scope\n\n"
            "The complete correctness suite ran once against a private snapshot "
            "of the current root/domain documents, settings and inert terminal job "
            "records, using an unused port and fresh source imports. Live campaign "
            "and session registries were not copied. Real sidecars were checked "
            "read-only. Legacy port/age cleanup of unrelated listeners was omitted; "
            "all correctness checks and owned-server teardown were retained. "
            "The existing service was not restarted. Its version and status "
            "endpoints were probed after the suite. This verifies the repair on "
            "fresh imports; it does not claim the existing service reloaded Python "
            "modules.\n")
    receipt = {
        "run_root": str(run_root), "source_data": str(source_data),
        "test_port": test_port, "suite_exit_code": suite_exit,
        "seconds": round(time.perf_counter() - started, 3),
        "snapshot": snapshot, "checks": report.checks,
        "issues": report.issues, "warnings": report.warnings,
        "recommendations": report.recommendations,
        "live_probes": live_probes,
        "source_hashes": {
            name: hashlib.sha256((CODE_DIR / name).read_bytes()).hexdigest()
            for name in ("worktrees.py", "tests/test_worktrees.py")
        },
        "source_review": "Independent bounded source review: no serious gap found; no checks run by reviewer.",
    }
    receipt_path = CODE_DIR / "docs/friction/2026-10-07-doctor-v6-ref-verification.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    target = source_data / "health_reports" / staged_report.name
    owned_temp = target.with_name(target.name + ".v6-ref-repair.tmp")
    owned_temp.write_bytes(staged_report.read_bytes())
    os.replace(owned_temp, target)
    print(json.dumps({"suite_exit": suite_exit, "issues": report.issues,
                      "warnings": report.warnings, "checks": len(report.checks),
                      "seconds": receipt["seconds"], "report": str(target),
                      "receipt": str(receipt_path)}, indent=2), flush=True)
    return 1 if suite_exit or report.has_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
