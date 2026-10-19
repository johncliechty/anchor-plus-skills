"""Graceful pre-restart drain: park every live PTY WARM (rearch W3).

Pre-designed in W3 as the fallback the ConPTY spike verdict may route W17 to:
if PTYs stay dashboard-owned, then a dashboard restart (``nssm restart
anchor``, a deploy) must cost each live terminal a WARM reconnect — never
dead context. For EVERY live PTY session this drain:

1. **parks** it via :func:`terminal_session.close_session` — the graceful
   close (crucible-improve W6): stops the PTY, KEEPS the registry record
   (re-statused ``STATUS_IDLE``), preserves the worktree, and PERSISTS the
   produced docs into the main project (``capture_session_docs``) so they
   survive the boot orphan-reaper;
2. **seeds the warm resume** — ensures the session's validated summary is
   CACHED (the thing :func:`anchor_gui._build_continue_seed` reads first), by
   generating it synchronously through the runner seam when absent, BOUNDED
   by a daemon-thread timeout (:data:`DRAIN_SUMMARY_TIMEOUT`, module-global →
   test-tunable) so a wedged model call can never block the restart.

The post-restart reopen (click the parked tile → ``continue_session``) then
opens WARM: docs persisted + summary cached. Proven against a stub PTY
session by the W3 gate (``tests/test_rearch_2026_07.py``); wired into the
deploy script by W17 iff the spike verdict is NO.

Best-effort throughout: a failure on one session never blocks draining the
rest, and the drain never raises out of :func:`drain`. Stdlib only.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Per-session cap on the synchronous warm-seed summary generation. Module
#: global (not captured at import) so tests/operators can tune it.
DRAIN_SUMMARY_TIMEOUT = 20.0


def _bootstrap_path():  # pragma: no cover - script-mode import shim
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _live_pty_records(project_id=None):
    """The registry records the drain targets: live-PTY-attached OR RUNNING.

    The union is deliberate: a RUNNING record whose PTY already died still
    deserves the park (close_session is tolerant), and an attached PTY whose
    record drifted still gets stopped.
    """
    import pty_manager
    import session_registry as reg

    attached = set(pty_manager.live_sessions())
    out = []
    for rec in reg.list_sessions(project_id=project_id):
        sid = rec.get("session_id")
        if sid in attached or rec.get("status") == reg.STATUS_RUNNING:
            out.append(rec)
    return out


def _resolve_session_dict(folder, project_id, lane, session_id):
    """The effort-history session dict the summarizer keys on (docs-tied).

    Reuses :func:`anchor_gui._resolve_finished_session` (the v8 no-loss
    resolution that ties the managed session to the docs it PRODUCED) when
    available; falls back to a minimal ``{"session_id": ...}`` record so the
    summarizer can still cache an honest summary.
    """
    try:
        import anchor_gui
        session = anchor_gui._resolve_finished_session(
            folder, project_id, lane, session_id)
        if session is not None:
            return session
    except Exception:
        pass
    return {"session_id": session_id}


def ensure_warm_seed(project_id, lane, session_id, timeout=None) -> str:
    """Ensure the session's summary is CACHED (the warm-resume seed).

    Returns one of:

    * ``"cached"``     — a summary was already cached (idempotent no-op);
    * ``"generated"``  — generated + cached now, through the runner seam;
    * ``"timeout"``    — the bounded generation did not finish in time (the
      restart proceeds; resume falls back to the persisted docs / intent);
    * ``"unavailable"``— the project/folder could not be resolved or the
      generation failed honestly (no cache written — never poisoned).
    """
    import effort_history as eh
    import rnd_registry as rnd
    import summarizer

    if timeout is None:
        timeout = DRAIN_SUMMARY_TIMEOUT
    try:
        proj = rnd.get_project(project_id) if project_id else None
        folder = (proj or {}).get("folder_path", "")
        if not folder:
            return "unavailable"
        store_lane = eh._resolve_subdir(lane)
        if summarizer.load_cached(folder, project_id, store_lane,
                                  session_id) is not None:
            return "cached"
        session = _resolve_session_dict(folder, project_id, lane, session_id)

        # Bounded synchronous generation: a wedged runner can NEVER block the
        # restart (same daemon-thread discipline as switch_engine's digest).
        def _gen():
            try:
                summarizer.summarize_session(folder, project_id, store_lane,
                                             session)
            except Exception:
                pass

        t = threading.Thread(target=_gen, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return "timeout"
        if summarizer.load_cached(folder, project_id, store_lane,
                                  session_id) is not None:
            return "generated"
        return "unavailable"
    except Exception:
        return "unavailable"


def legacy_target():
    """{"pid", "dir"} of one registered project with a discovered steward effort (W5, 2026-10-09). A service from
    before this change answers drain-all only inside a valid project and effort - it posted {} and was answered
    "unknown project" - and its handler then parks EVERY engine of the service, not only that effort's. The new
    service ignores both fields. None when no such effort exists."""
    try:
        import rnd_registry as rnd
        from steward_cockpit import steward_campaign as camp
        for proj in rnd.list_projects(include_archived=True, include_future=True, include_retired=False):
            folder = (proj.get("folder_path") or "").strip()
            if not folder or not Path(folder).is_dir():
                continue
            try:
                efforts = camp.discover_efforts(folder)
            except Exception:
                continue
            if efforts:
                return {"pid": proj.get("id"), "dir": efforts[0].get("rel", "")}
    except Exception:
        return None
    return None


def service_drain(url=None, token=None, target=None, timeout=30):
    """Ask THE SERVICE to park its own cockpit engines. Returns the cockpit report; ``note`` is set (and the drain
    fails) on 401, on any other HTTP error, on an unreachable service, on an answer that is not the drain's own
    structured report, and on any engine that failed to park - never a vacuous success."""
    import json as _json
    import os as _os
    import urllib.request as _rq
    import urllib.error as _er
    cockpit = {"mode": "http", "parked": [], "idle": [], "errors": [], "note": None}
    url = (url or _os.environ.get("ANCHOR_URL", "http://127.0.0.1:8777")) + "/api/steward/drain-all"
    token = _os.environ.get("ANCHOR_TOKEN", "") if token is None else token
    target = legacy_target() if target is None else target
    payload = dict(target or {})
    if payload.get("pid"):
        url += "?pid=" + str(payload["pid"])
    req = _rq.Request(url, data=_json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Anchor-Token", token)
        req.add_header("Authorization", "Bearer " + token)
    try:
        with _rq.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        try:
            body = _json.loads(raw.decode("utf-8"))
        except Exception:
            body = None                                  # judged below: not a drain report
    except _er.HTTPError as e:
        if e.code == 401:
            cockpit["note"] = ("cockpit engines NOT parked: the service refused the token (401) - run this with "
                               "ANCHOR_TOKEN set (restart_anchor.ps1 reads it from the service)")
        else:
            cockpit["note"] = "cockpit drain HTTP %s: engines NOT parked" % e.code
        return cockpit
    except Exception as e:
        cockpit["note"] = "service unreachable (%s): engines NOT parked" % type(e).__name__
        return cockpit
    shaped = (isinstance(body, dict) and body.get("ok") in (True, False)
              and all(isinstance(body.get(k), list) for k in ("parked", "idle", "errors")))
    if not shaped:
        cockpit["note"] = "the service's answer was not a drain report: engines NOT known to be parked"
        return cockpit
    cockpit.update({k: body[k] for k in ("parked", "idle", "errors")})
    if body["errors"] or body["ok"] is not True:
        cockpit["note"] = "%d cockpit engine(s) failed to park" % max(1, len(body["errors"]))
    return cockpit


def drain(project_id=None, dry_run=False, summary_timeout=None) -> dict:
    """Park every live PTY session warm; returns the drain report.

    ``dry_run=True`` only enumerates what WOULD be drained (no mutation).
    Never raises: per-session failures are recorded in the report and the
    drain proceeds to the next session.
    """
    import terminal_session as ts

    records = _live_pty_records(project_id=project_id)
    drained = []
    for rec in records:
        sid = rec.get("session_id")
        pid = rec.get("project_id")
        lane = rec.get("lane", "")
        entry = {"session_id": sid, "project_id": pid, "lane": lane,
                 "label": rec.get("label", "")}
        if dry_run:
            entry["would_drain"] = True
            drained.append(entry)
            continue
        try:
            closed = ts.close_session(sid, project_id=pid)
            # final r1 (2026-10-09): this is a separate process - a terminal the SERVICE owns is not stopped here
            # (pty_killed False); its record is parked, its docs persisted and its summary cached, and its process ends
            # with the service's stop. Reported as that, never as "parked"; a failed close is a failure.
            entry["recorded"] = bool(closed.get("ok"))
            entry["parked"] = bool(closed.get("ok")) and bool(closed.get("pty_killed"))
            entry["ends_with_stop"] = bool(closed.get("ok")) and not closed.get("pty_killed")
            entry["status"] = closed.get("status")
            docs = closed.get("docs") or {}
            entry["docs_persisted"] = list(docs.get("persisted") or [])
            entry["seed"] = ensure_warm_seed(pid, lane, sid,
                                             timeout=summary_timeout)
        except Exception as e:                      # never blocks the rest
            entry["parked"] = entry["recorded"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        drained.append(entry)

    # ── Cockpit steward engines (2026-08-25; REWIRED same day after review) ──
    # The cockpit engines are long-lived `claude` processes owned by the RUNNING
    # SERVICE — this drain is a separate process, so an in-process registry read
    # is a structural no-op (first version's defect: it always saw an empty
    # ENGINES and reported [] — indistinguishable from "none live"). The drain
    # now asks THE SERVICE to park its own engines via POST /api/steward/drain-all
    # and reports each failure class BY NAME — never a vacuous empty.
    if dry_run:
        cockpit = {"mode": "http", "parked": [], "idle": [], "errors": [], "note": "dry-run: service drain-all not called"}
    else:
        cockpit = service_drain()

    # W5 (2026-10-09): fail closed - the restart stops before shutdown unless every engine and session parked
    failed = [d.get("session_id") for d in drained if not dry_run and not d.get("recorded")]
    ok = bool(dry_run) or (not failed and not cockpit.get("note"))
    return {"ok": ok, "dry_run": bool(dry_run), "count": len(drained), "failed_sessions": failed,
            "terminals_end_with_stop": [d.get("session_id") for d in drained if d.get("ends_with_stop")],
            "drained": drained, "cockpit": cockpit}


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse
    import json

    _bootstrap_path()
    ap = argparse.ArgumentParser(
        description="Graceful pre-restart drain: park every live PTY warm "
                    "(close_session park + docs capture + warm-resume seed).")
    ap.add_argument("--project", default=None,
                    help="drain only this project id (default: all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="enumerate what would be drained; mutate nothing")
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-session warm-seed generation cap in seconds "
                         f"(default {DRAIN_SUMMARY_TIMEOUT})")
    args = ap.parse_args(argv)
    report = drain(project_id=args.project, dry_run=args.dry_run,
                   summary_timeout=args.timeout)
    print(json.dumps(report, indent=2))
    if not report.get("ok"):
        print("DRAIN FAILED: %s" % ((report.get("cockpit") or {}).get("note")
                                    or "sessions not parked: %s" % ", ".join(map(str, report.get("failed_sessions") or []))))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
