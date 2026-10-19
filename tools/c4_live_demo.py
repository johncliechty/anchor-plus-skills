"""C4 live-demo harness — restart-survival on the real service (rearch W17).

The C4 success criterion (Master Plan Phase 5) is DEMONSTRATED, not narrated:
a harmless long-running job launched through the REAL launch path keeps running
across ``nssm restart anchor``, and the restarted dashboard reports it live with
an advancing tail. This module scripts the mechanical building blocks the
``C4-RUNBOOK.md`` runbook cites, so the runbook is *executable*, not prose:

* :func:`setup_demo_project`  — register a dedicated THROWAWAY R&D project;
* :func:`launch_demo_job`     — launch a harmless long-running fake_claude job
  through the real supervisor launch path (lane-guarded, exactly as the
  dashboard does);
* :func:`verify_survival`     — after a restart, re-adopt from the durable
  records and assert the SAME job_id lists running, its tail cursor advances,
  and it is cancellable;
* :func:`rollback_demo`       — the runbook's rollback: cancel (reaps + clears
  the lane lock) + retire the throwaway project;
* :func:`run_demo`            — the whole flow end-to-end, with an injectable
  ``restart_hook`` so the hermetic gate can SIMULATE the restart (tear down the
  in-memory tables) exactly where the live runbook runs the real
  ``nssm restart anchor``.

The building blocks are production-safe (no test-only calls): on the live
service the operator runs them across a REAL restart; :func:`verify_survival`
calls :meth:`supervisor.Supervisor.rebuild` — the same idempotent re-adoption
the dashboard performs at boot. The hermetic gate is the honest approximation
(same process; the restart is a table teardown); the true cross-service
survival is the live runbook run WITH John.

Stdlib only. Never hardcodes port 8777 / real data — it operates against
whatever ``ANCHOR_DATA_DIR`` is configured (a temp dir in the gate; the live
data dir when run by the runbook).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The throwaway project name the runbook registers on the real service.
DEMO_PROJECT_NAME = "C4 Live Demo (throwaway)"
#: The lane the demo job runs in. build is folder-locked, so the runbook proves
#: BOTH the lane slot and the folder-build lock survive the restart.
DEMO_LANE = "build"


def _bootstrap_path():  # pragma: no cover - script-mode import shim
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _harmless_job_args(lines=60, interval=0.15, sleep=3):
    """A harmless, long-running fake_claude invocation.

    Drips ``lines`` lines at ``interval`` seconds (so the tail keeps advancing
    across the restart window) then sleeps ``sleep`` more — no side effects, no
    real model call.
    """
    return ["--lines", str(lines), "--line-interval", str(interval),
            "--sleep", str(sleep)]


def setup_demo_project(folder_path, name=DEMO_PROJECT_NAME):
    """Register a dedicated THROWAWAY R&D project rooted at ``folder_path``.

    Returns the stored project record (carries ``id``). On the live service
    this is a real, disposable project; the runbook retires it in rollback.
    """
    import rnd_registry as rnd

    folder = Path(folder_path)
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name=name, folder_path=str(folder))


def launch_demo_job(sup, project_id, folder_path, lane=DEMO_LANE,
                    extra_args=None):
    """Launch the harmless long-running demo job through the REAL launch path.

    Uses ``supervisor.Supervisor.launch_guarded`` — the same lane-guarded launch
    the dashboard's ``/api/rnd/launch_lane`` build path uses — so the lane slot
    and (for ``build``) the folder-build lock are held durably. Returns the job
    record (carries ``job_id`` + ``pid``).
    """
    args = extra_args if extra_args is not None else _harmless_job_args()
    return sup.launch_guarded(lane, project_id=project_id,
                              folder_path=str(folder_path), cwd=str(folder_path),
                              extra_args=args)


def wait_live(job_id, min_lines=2, timeout=8.0):
    """Wait until the job has produced ``min_lines`` — proof it is live.

    Returns True once enough lines exist, False on timeout.
    """
    import job_runner as jr

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if len(jr.all_lines(job_id)) >= min_lines:
            return True
        time.sleep(0.03)
    return False


def verify_survival(sup, job_id, project_id=None, folder_path=None,
                    lane=DEMO_LANE, tail_timeout=8.0):
    """Assert the in-flight job SURVIVED a (real or simulated) restart.

    Called in the restarted process (or after the gate's simulated teardown):

    1. :meth:`rebuild` re-adopts the in-flight job from the durable records —
       the same idempotent re-adoption the dashboard runs at boot;
    2. the SAME ``job_id`` lists running and is live;
    3. the concurrency slots are rebuilt (lane slot; folder-build lock for
       ``build``);
    4. the tail cursor keeps ADVANCING after the restart.

    Returns a structured report; ``report["survived"]`` is the headline.
    """
    import job_runner as jr

    summary = sup.rebuild()
    listed = [r["job_id"] for r in sup.list_jobs(running_only=True)]
    listed_running = listed.count(job_id) == 1
    is_live = sup.is_live(job_id)

    lane_ok = True
    if project_id:
        lane_ok = jr.lane_holder(project_id, lane) == job_id
    folder_ok = True
    if lane == jr.BUILD_LANE and folder_path:
        folder_ok = jr.folder_build_holder(str(folder_path)) == job_id

    # The tail cursor must advance after the restart.
    sup.tail(job_id, persist=True)
    cur1 = jr.load_read_cursor(job_id)
    advanced = False
    end = time.monotonic() + tail_timeout
    while time.monotonic() < end:
        sup.tail(job_id, persist=True)
        if jr.load_read_cursor(job_id) > cur1:
            advanced = True
            break
        time.sleep(0.05)
    cur2 = jr.load_read_cursor(job_id)

    survived = bool(listed_running and is_live and lane_ok and folder_ok
                    and advanced)
    return {
        "survived": survived,
        "job_id": job_id,
        "listed_running": listed_running,
        "is_live": is_live,
        "lane_slot_ok": lane_ok,
        "folder_lock_ok": folder_ok,
        "tail_advanced": advanced,
        "cursor_before": cur1,
        "cursor_after": cur2,
        "rebuild_summary": summary,
    }


def rollback_demo(sup, job_id=None, project_id=None, retire=True):
    """The runbook's rollback: cancel the job + clear the lane lock + retire.

    * ``cancel`` tree-kills the job and releases its concurrency slots;
    * ``release_slots`` is called defensively (idempotent) so no lane/folder
      lock is ever stranded even if the record already went terminal;
    * the throwaway project is retired (kept, never hard-deleted) so the
      dashboard is left clean.

    Never raises — a rollback must always make progress. Returns a report.
    """
    import job_runner as jr

    report = {"cancelled": False, "slots_cleared": False,
              "project_retired": False}
    if job_id:
        try:
            out = sup.cancel(job_id)
            report["cancelled"] = out.get("status") == jr.STATUS_CANCELLED
        except Exception as e:
            report["cancel_error"] = f"{type(e).__name__}: {e}"
        try:
            jr.release_slots(job_id)          # defensive: never strand a lock
            report["slots_cleared"] = True
        except Exception as e:
            report["slots_error"] = f"{type(e).__name__}: {e}"
    if retire and project_id:
        try:
            import rnd_registry as rnd
            rnd.retire_project(project_id)
            report["project_retired"] = True
        except Exception as e:
            report["retire_error"] = f"{type(e).__name__}: {e}"
    return report


def run_demo(root, sup=None, restart_hook=None, lane=DEMO_LANE,
             extra_args=None, project_id=None, folder_path=None):
    """Drive the whole C4 demo flow end-to-end; return the full report.

    ``restart_hook`` is called AFTER the job is confirmed live and BEFORE
    :func:`verify_survival` — the live runbook does nothing here (it runs the
    real ``nssm restart anchor`` out of band); the hermetic gate passes a hook
    that tears down the in-memory tables (``job_runner._reset_live_table_for_tests``)
    to SIMULATE the restart.

    Always rolls back (cancel + retire) in a finally, so a failure never strands
    a running job or a held lane lock.
    """
    if sup is None:
        import supervisor
        sup = supervisor.get_supervisor()

    root = Path(root)
    if folder_path is None:
        folder_path = root / "c4-demo-project"
    created_project = False
    job_id = None
    report = {"ok": False}
    try:
        if project_id is None:
            proj = setup_demo_project(folder_path)
            project_id = proj["id"]
            created_project = True
        report["project_id"] = project_id

        rec = launch_demo_job(sup, project_id, folder_path, lane=lane,
                              extra_args=extra_args)
        job_id = rec["job_id"]
        report["job_id"] = job_id
        report["launched"] = bool(job_id and rec.get("pid"))

        report["went_live"] = wait_live(job_id)

        if restart_hook is not None:
            restart_hook()

        report["survival"] = verify_survival(
            sup, job_id, project_id=project_id, folder_path=folder_path,
            lane=lane)
        report["ok"] = bool(report["launched"] and report["went_live"]
                            and report["survival"]["survived"])
        return report
    finally:
        report["rollback"] = rollback_demo(
            sup, job_id=job_id, project_id=project_id, retire=created_project)


def _build_parser():
    """The C4-demo CLI parser (extracted so the W18 gate can assert its shape).

    The live runbook is PHASED across a REAL ``nssm restart anchor`` — a single
    one-shot ``run_demo`` cannot demonstrate cross-process survival because it
    rolls back in its own ``finally`` before an out-of-band restart could land.
    So the runbook uses ``--phase``:

    * ``launch``   — register the throwaway project + launch the job, print the
      ``project_id`` / ``job_id``, and LEAVE IT RUNNING (no rollback);
    * *(manual)*   — ``nssm restart anchor`` from an elevated shell;
    * ``verify``   — re-adopt (``rebuild``) + assert the same job_id survived;
    * ``rollback`` — cancel the LIVE job + clear the lane lock + retire (targets
      the given ``--job-id``/``--project-id``, never starts a new demo);
    * ``demo``     — the hermetic one-shot (setup+launch+verify+rollback in one
      process; ``--simulate-restart`` tears down the in-memory tables).
    """
    import argparse

    ap = argparse.ArgumentParser(
        description="C4 live-demo harness: restart-survival of a harmless "
                    "long-running job through the real launch path.")
    ap.add_argument("--phase", choices=("demo", "launch", "verify", "rollback"),
                    default="demo",
                    help="demo = hermetic one-shot; launch/verify/rollback = the "
                         "live phased runbook across a real nssm restart")
    ap.add_argument("--root", default=None,
                    help="root dir for the throwaway project (default: a temp "
                         "dir). On the live service, pass a scratch folder.")
    ap.add_argument("--simulate-restart", action="store_true",
                    help="(demo phase) simulate the restart in-process (tear "
                         "down the in-memory tables) instead of a real nssm "
                         "restart — the hermetic demo")
    ap.add_argument("--job-id", default=None,
                    help="the demo job_id (required by --phase verify/rollback)")
    ap.add_argument("--project-id", default=None,
                    help="the demo project_id (launch prints it; rollback "
                         "retires it)")
    return ap


def main(argv=None):  # pragma: no cover - thin CLI shim
    import json
    import tempfile

    _bootstrap_path()
    import supervisor

    ap = _build_parser()
    args = ap.parse_args(argv)
    sup = supervisor.get_supervisor()

    if args.phase == "launch":
        root = args.root or tempfile.mkdtemp(prefix="c4-demo-")
        folder = Path(root) / "c4-demo-project"
        proj = setup_demo_project(folder)
        rec = launch_demo_job(sup, proj["id"], folder)
        live = wait_live(rec["job_id"])
        out = {"phase": "launch", "project_id": proj["id"],
               "job_id": rec["job_id"], "pid": rec.get("pid"),
               "went_live": live, "folder": str(folder)}
        print(json.dumps(out, indent=2, default=str))
        return 0 if (rec.get("job_id") and live) else 1

    if args.phase == "verify":
        if not args.job_id:
            ap.error("--phase verify requires --job-id")
        rep = verify_survival(sup, args.job_id, project_id=args.project_id)
        print(json.dumps({"phase": "verify", **rep}, indent=2, default=str))
        return 0 if rep.get("survived") else 1

    if args.phase == "rollback":
        if not args.job_id:
            ap.error("--phase rollback requires --job-id")
        rep = rollback_demo(sup, job_id=args.job_id,
                            project_id=args.project_id,
                            retire=bool(args.project_id))
        print(json.dumps({"phase": "rollback", **rep}, indent=2, default=str))
        return 0 if rep.get("cancelled") else 1

    # default: the hermetic one-shot demo.
    root = args.root or tempfile.mkdtemp(prefix="c4-demo-")
    hook = None
    if args.simulate_restart:
        import job_runner as jr
        hook = jr._reset_live_table_for_tests
    report = run_demo(root, sup=sup, restart_hook=hook)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
