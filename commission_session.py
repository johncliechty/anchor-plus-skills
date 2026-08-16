"""Conversation -> commission: the steward actually RUNS a skill (2026-08-06).

WHY THIS MODULE EXISTS. Every seam already existed and none of them were
joined: the chamber could talk (converse), the engine could propose and
hash-confirm a commission (commission-run-bridge), a managed session could be
launched with the skill loaded (commission_executor.launch_commission_in_session),
the run loop could drive it to a decision point (commission_runner), and the
engine could read a finished run back to John and raise the High Seat
(steward-run-ingest via the same bridge). This module is the join, and ONLY
the join:

    propose -> John confirms -> session starts -> run loop drives -> stopped
    -> the run record is written -> the bridge ingests it (report + raise
    + handback) -> John opens THAT session, answers, hands it back
    -> watch re-arms -> produced -> ingested -> reported.

THE LONG-LIVED-PROCESS LAW (learned the hard way): a throwaway process kills
the PTY it starts. Launch + drive must live in ONE long-lived process — this
module runs inside the Anchor service, and the watcher is a daemon thread of
that service.

WHAT IT NEVER DOES: answer a question the skill asked (commission_runner's
law), or derive project state (the engine's ledger owns that; run records
here are the steward's own bookkeeping about runs, nothing more).

Stdlib only. The Node bridge is an external CLI through an injectable seam
(``ANCHOR_ECGBERHT_BRIDGE_CMD``), fully stubbed in tests — same pattern as
``ANCHOR_RUNNER_CMD``.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import paths as _paths
import commission_executor as _ce
import commission_runner as _cr

ANCHOR_DIR = Path(__file__).resolve().parent

#: Durable per-project stores (under the project folder, like .anchor/ elsewhere).
COMMISSION_STORE_REL = os.path.join(".anchor", "commissions")
RUN_RECORDS_REL = os.path.join(".anchor", "commission-runs")

#: The bridge does a real seat call on ingest-run (report read) — be generous.
BRIDGE_TIMEOUT_S = 60
INGEST_TIMEOUT_S = 300

#: How much transcript tail a run record keeps. The session window replays the
#: full PTY; the record only needs enough for a post-mortem read.
TRANSCRIPT_TAIL_CHARS = 4000

RUN_RECORD_SCHEMA = "anchor-commission-run-v0"

#: Production watch bounds. MEASURED (E2E 2026-08-06): Crucible at xhigh
#: effort sat >4 minutes with ZERO TUI repaint mid-think — the runner's 90s
#: default would have classified a hard-working skill as QUIET. A real plan
#: run is tens of minutes, not seconds.
DEFAULT_RUNNER_KWARGS = {
    "poll_seconds": 10,
    "max_seconds": 2700,
    "quiet_seconds": 420,
}

#: The second turn — the one that turns "skill loaded" into "skill working".
#: The brief itself rides the session seed (launch_commission_in_session folds
#: it onto the lane seed), so this stays short and constant.
WORK_TURN = (
    "Begin the commissioned work now — the brief is in your opening context. "
    "Work autonomously and do not wait for further instruction. "
    "FIRST, check whether any decision on this step is genuinely John's alone "
    "(a goal lock, a direction choice, a spend approval): if so, ask that "
    "question plainly and STOP — before doing any deep work that the answer "
    "could invalidate. Otherwise work on; whenever you genuinely need John's "
    "decision, ask it plainly and stop."
)


# ── Bridge (the one door to the Ecgberht engine) ─────────────────────────────

def _ecgberht_root() -> Path:
    """ECGBERHT_ROOT env override, else the sibling checkout beside Anchor."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return ANCHOR_DIR.parent / "Ecgberht"


def run_bridge(mode: str, payload: dict, timeout: int = BRIDGE_TIMEOUT_S) -> dict:
    """Spawn the commission-run bridge with ``payload`` on STDIN (never argv —
    transcripts cross the 32,767-char argv cap instantly) and parse its
    one-line JSON reply.

    ``ANCHOR_ECGBERHT_BRIDGE_CMD`` overrides the command for tests (a python
    stub), exactly like ``ANCHOR_RUNNER_CMD`` stubs the model runner.
    """
    override = os.environ.get("ANCHOR_ECGBERHT_BRIDGE_CMD", "").strip()
    if override:
        # posix=False so Windows backslash paths survive (job_runner's carried
        # fix) — but then quoted tokens KEEP their quotes, and subprocess would
        # double-quote them. Strip one layer of surrounding quotes per token.
        cmd = [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t
               for t in shlex.split(override, posix=(os.name != "nt"))] + [mode]
        cwd = str(ANCHOR_DIR)
    else:
        bridge = _ecgberht_root() / "scripts" / "commission-run-bridge.mjs"
        if not bridge.exists():
            return {"ok": False, "error": "ecgberht_engine_missing",
                    "message": "commission-run bridge not found (set ECGBERHT_ROOT "
                               "or keep the Ecgberht checkout beside Anchor)"}
        cmd = ["node", str(bridge), mode]
        cwd = str(_ecgberht_root())
    try:
        res = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            cwd=cwd, creationflags=getattr(_paths, "NO_WINDOW", 0))
    except Exception as exc:
        return {"ok": False, "error": "bridge_spawn_failed", "message": str(exc)}
    out = (res.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "bridge_no_output",
                "message": (res.stderr or "").strip()[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "bridge_bad_json", "message": out[:500]}


# ── Run records (the steward's own bookkeeping — never project state) ───────

def _run_record_path(folder: str, session_id: str) -> Path:
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_.")
    return Path(folder) / RUN_RECORDS_REL / f"{safe}.json"


def _atomic_write_json(target: Path, obj: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_run_record(folder: str, session_id: str) -> Optional[dict]:
    p = _run_record_path(folder, session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(folder: str) -> list:
    """SAFE projections of the project's commission runs, newest-first.
    Never a worktree path, never the transcript body."""
    root = Path(folder) / RUN_RECORDS_REL
    if not root.exists():
        return []
    rows = []
    for p in sorted(root.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "session_id": rec.get("session_id"),
            "commission_id": rec.get("commission_id"),
            "skill": rec.get("skill"),
            "step_id": rec.get("step_id"),
            "lane": rec.get("lane"),
            "outcome": rec.get("outcome"),
            "ran": rec.get("ran"),
            "elapsed_s": rec.get("elapsed_s"),
            "at": rec.get("at"),
            "watch_count": rec.get("watch_count", 1),
            "report": rec.get("report"),
            "prior_reports": rec.get("prior_reports") or [],
            "reflection": rec.get("reflection"),
            "auto_continue": rec.get("auto_continue"),
            "auto_chain": rec.get("auto_chain"),
            "raised": rec.get("raised"),
        })
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows


# ── Watcher registry (one watcher per session, ever) ────────────────────────

_WATCHERS: dict = {}
_WATCHERS_LOCK = threading.Lock()


def watcher_active(session_id: str) -> bool:
    with _WATCHERS_LOCK:
        t = _WATCHERS.get(session_id)
        return bool(t and t.is_alive())


def _claim_watcher(session_id: str, thread: threading.Thread) -> bool:
    with _WATCHERS_LOCK:
        existing = _WATCHERS.get(session_id)
        if existing and existing.is_alive():
            return False
        _WATCHERS[session_id] = thread
        return True


# ── Propose ─────────────────────────────────────────────────────────────────

def propose(folder: str, step_id: Optional[str] = None,
            skill: Optional[str] = None, depth: Optional[str] = None,
            who: str = "ecgberht-steward") -> dict:
    """Ask the engine to propose a commission for the step in hand.
    READ-ONLY — the reply carries requires_confirm and the hash John binds."""
    payload = {"project": str(folder), "who": who}
    if step_id:
        payload["step_id"] = step_id
    if skill:
        payload["skill"] = skill
    if depth:
        payload["depth"] = depth
    return run_bridge("propose-active", payload)


# ── Confirm + launch + watch (the join) ─────────────────────────────────────

def confirm_and_launch(
    folder: str,
    proposal: dict,
    *,
    project_id: str,
    who: str = "john",
    backend: str = "claude",
    directive: Optional[str] = None,
    record_extra: Optional[dict] = None,
    watch: bool = True,
    start_session_fn: Optional[Callable] = None,
    read_fn: Optional[Callable] = None,
    write_fn: Optional[Callable] = None,
    runner_kwargs: Optional[dict] = None,
    auth_ctx: Optional[dict] = None,
    expected_token: Optional[str] = None,
    enforce_auth: bool = False,
    thread_factory: Optional[Callable] = None,
) -> dict:
    """John said go: hash-confirm through the engine, launch the managed
    session with the skill loaded and the brief seeded, and start the watcher
    that will fetch him when the skill needs him.

    Injectable seams (``start_session_fn`` / ``read_fn`` / ``write_fn`` /
    ``thread_factory``) make this fully testable without a live PTY.
    """
    if not proposal or not isinstance(proposal, dict):
        return {"ok": False, "error": "proposal_required"}

    # W4 commission-time manifest lint (steward-chamber plan, F2): a NEW
    # scaffold (born under the manifest convention) without a valid sidecar
    # manifest is a HARD refusal before anything is confirmed or launched;
    # a campaign predating the manifest routes to the W5 brownfield dual
    # path (route "brownfield-w5") and proceeds.
    import chamber_manifest as _cm
    manifest_lint = _cm.commission_time_lint(folder)
    if not manifest_lint.get("ok"):
        return {"ok": False, "error": manifest_lint.get("error"),
                "message": manifest_lint.get("message"),
                "manifest_lint": manifest_lint}

    # W10 E2 enqueue gate (steward-chamber, C5 — ENGINE-ENFORCED on THIS
    # seam, the W2-proven leg b): while the campaign carries a death whose
    # containment-checked sweep card is not yet BOUND into the decision-gate
    # queue, a re-commission is REFUSED with the named finding — before the
    # engine confirm, before any spend. The guard fails CLOSED on an
    # unreadable gate store (a safety gate never guesses).
    import chamber_gates as _cgates
    e2 = _cgates.enqueue_guard(folder)
    if not e2.get("ok"):
        return {"ok": False, "error": e2.get("error"),
                "finding": e2.get("finding"),
                "message": e2.get("message"),
                "blocking_deaths": e2.get("blocking_deaths")}

    confirmed = run_bridge("confirm", {
        "project": str(folder),
        "proposal": proposal,
        "who": who,
    })
    if not confirmed.get("ok"):
        return {"ok": False, "error": confirmed.get("error", "confirm_failed"),
                "message": confirmed.get("message"), "confirm": confirmed}

    job = confirmed.get("job") or {}
    skill = job.get("skill") or proposal.get("skill")
    step_id = job.get("step_id") or proposal.get("step_id")
    commission_id = (job.get("commission_id") or job.get("job_id")
                     or proposal.get("proposal_id"))

    # Lane resolution. researchPrime/Crucible/Foreman have dedicated lanes whose
    # seeds load them. Gandalf and Jumper have NO lane — but a `general` session
    # sends its seed_context ALONE as the opening turn, so the brief itself can
    # load the skill by name (they are registered globally). Found in hardening
    # 2026-08-06: John's step 1 IS a Gandalf read; without this his first Go
    # refused. Truly unknown skills still refuse by name.
    lane = _ce.lane_for_commissioned_skill(skill)
    load_preamble = None
    if not lane and str(skill).lower() in ("gandalf", "jumper"):
        lane = "general"
        load_preamble = (
            f"Load the {skill} skill now. Confirm it's ready by greeting me "
            f"EXACTLY once with: \"{skill} loaded — what would you like to do?\" "
            "Then stop and wait for my next message.\n\n")
    if not lane:
        return {"ok": False, "error": "skill_has_no_session_lane",
                "message": f"'{skill}' has no managed-session lane — it cannot "
                           "run as a commissioned session yet.",
                "skill": skill, "confirm": confirmed}

    # (2026-08-07) THE DIRECTIVE. The steward composes the brief from what the
    # campaign has learned (the reflection), John iterates and approves it, and
    # it rides here as the heart of the session's opening context — the "glue"
    # between runs he asked for.
    directive_block = ""
    if directive and str(directive).strip():
        directive_block = (
            "COMMISSION DIRECTIVE (composed by the steward from the campaign's "
            "current state; approved by John):\n" + str(directive).strip() + "\n\n")
    brief = (load_preamble or "") + directive_block + build_brief(proposal, skill=skill)

    # (steward-chamber W11, E6) Standing-preferences PRELOAD: the feedback
    # ledger + global standing rules fold DETERMINISTICALLY into the talk
    # instruction at session start, and the projection listing EXACTLY the
    # loaded entries persists to the chamber sidecar
    # (chamber_preload.preload_into_instruction; verify_preload is the
    # mechanical diff — a missing entry is a diffable failure).
    try:
        import chamber_preload as _cpl
        brief = _cpl.preload_into_instruction(folder, brief)["instruction"]
    except Exception:
        # A preload hiccup never strands a launch; the projection sidecar's
        # absence is itself the honest record that nothing was loaded.
        pass

    def _launch(**kwargs):
        return _ce.launch_commission_in_session(
            start_session_fn=start_session_fn, **kwargs)

    store_root = Path(folder) / COMMISSION_STORE_REL
    commission = {
        "confirmed": True,
        "commission_id": commission_id,
        "skill": skill,
        "depth": proposal.get("depth_cell"),
        "step_id": step_id,
        "who": who,
    }
    launched = _ce.execute_confirmed_commission(
        commission,
        store_root=store_root,
        launch_fn=_launch,
        lane=lane,
        backend=backend,
        project_id=project_id,
        folder_path=folder,
        prompt=brief,
        auth_ctx=auth_ctx,
        expected_token=expected_token,
        enforce_auth=enforce_auth,
    )
    if not launched.get("ok", True) and launched.get("error"):
        return {"ok": False, "error": launched.get("error"),
                "message": launched.get("message") or launched.get("user_text"),
                "launch": launched}

    session_id = launched.get("session_id") or launched.get("job_id")
    if not session_id:
        return {"ok": False, "error": "no_session_id", "launch": launched}

    record = {
        "schema": RUN_RECORD_SCHEMA,
        "session_id": session_id,
        "commission_id": commission_id,
        "skill": skill,
        "step_id": step_id,
        "lane": lane,
        "project_id": project_id,
        "outcome": "running",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "watch_count": 0,
        "worktree_path": launched.get("worktree_path"),
        # The composed brief rides the record so the pulse tile can show WHAT
        # this run was aimed at (2026-08-07, John's inspect-naturally ask).
        "directive": (str(directive).strip() if directive else None),
        # e.g. the autonomy chain depth — merged BEFORE the watcher starts so
        # the watcher's in-memory record carries it to its own finish_run
        # (a post-launch disk patch would be silently dropped at run end).
        **(record_extra or {}),
    }
    _atomic_write_json(_run_record_path(folder, session_id), record)

    # W4 chamber sidecar: the commission_start event-time projection, plus the
    # manifest hash keyed to the commission id from the run record's EXISTING
    # receipt fields (route "manifest" only). Best-effort — a sidecar hiccup
    # never blocks a launch John just confirmed; the projections are
    # rebuildable derived data (W5 cold-open rebuild).
    try:
        import chamber_projections as _cproj
        _cproj.record_commission_start(
            folder, commission_id, session_id=session_id,
            step_id=step_id, skill=skill, lane=lane)
        if manifest_lint.get("route") == _cm.ROUTE_MANIFEST:
            _cm.record_manifest_hash(folder, record)
    except Exception:
        pass

    watching = False
    if watch:
        watching = _start_watcher(
            folder, project_id, record, watch_only=False,
            read_fn=read_fn, write_fn=write_fn,
            runner_kwargs=runner_kwargs, thread_factory=thread_factory)

    return {
        "ok": True,
        "session_id": session_id,
        "commission_id": commission_id,
        "skill": skill,
        "step_id": step_id,
        "lane": lane,
        "watching": watching,
        "say": (f"Commissioned — {skill} is running in a session I manage. "
                "I'll come get you the moment it needs you."),
    }


def build_brief(proposal: dict, skill: Optional[str] = None) -> str:
    """The opening brief, folded onto the lane seed. Everything the engine
    proposal already knows about the step — nothing invented here."""
    step = proposal.get("step") or {}
    lines = [
        f"COMMISSION BRIEF — {skill or proposal.get('skill') or 'skill'} "
        f"for roadmap step '{step.get('name') or proposal.get('step_id') or ''}'.",
    ]
    if step.get("done_when"):
        lines.append(f"The step is done when: {step['done_when']}")
    commission = proposal.get("commission") or {}
    if commission.get("active_effort"):
        lines.append(f"Active effort: {commission['active_effort']}")
    lines.append(
        "Work from the project in this folder. When you genuinely need John's "
        "decision, ask it plainly and stop — do not guess on his behalf.")
    return "\n".join(lines)


# ── The watcher (runs inside the service — the long-lived process) ──────────

def _start_watcher(folder, project_id, record, *, watch_only,
                   read_fn=None, write_fn=None, runner_kwargs=None,
                   thread_factory=None) -> bool:
    session_id = record["session_id"]

    def _run():
        _watch_session(folder, project_id, record,
                       watch_only=watch_only,
                       read_fn=read_fn, write_fn=write_fn,
                       runner_kwargs=runner_kwargs)

    factory = thread_factory or (lambda fn: threading.Thread(
        target=fn, name=f"commission-watch-{session_id}", daemon=True))
    thread = factory(_run)
    if not _claim_watcher(session_id, thread):
        return False
    thread.start()
    return True


def _watch_session(folder, project_id, record, *, watch_only,
                   read_fn=None, write_fn=None, runner_kwargs=None) -> dict:
    """One watch: drive (or resume watching) the session, then bring the run
    home through the bridge. Runs on the watcher thread."""
    session_id = record["session_id"]
    if read_fn is None or write_fn is None:
        import terminal_session as _ts
        read_fn = read_fn or _ts.read_since
        write_fn = write_fn or _ts.input

    kwargs = dict(DEFAULT_RUNNER_KWARGS) if runner_kwargs is None else dict(runner_kwargs)
    try:
        result = _cr.run_commissioned_session(
            session_id,
            WORK_TURN,
            read_fn=read_fn,
            write_fn=write_fn,
            watch_only=watch_only,
            **kwargs,
        )
    except Exception as exc:
        # (2026-08-07 shark round) A runner exception used to kill the daemon
        # thread SILENTLY — the record stranded "running" forever and John was
        # never fetched. A dead watcher is a died run: report it honestly.
        result = {"outcome": "died", "ran": None, "elapsed_s": None,
                  "transcript": "", "transcript_chars": 0,
                  "watcher_error": str(exc)[:300]}
    return finish_run(folder, project_id, record, result,
                      read_fn=read_fn, write_fn=write_fn,
                      runner_kwargs=runner_kwargs)


#: How many runs the steward may chain WITHOUT John touching the campaign.
#: John's standing rule (2026-08-07): "I want the steward to be able to do as
#: much as it can without asking me" — but an unattended chain still checks in
#: after this many consecutive auto-hops, so an abandoned campaign never
#: burns unbounded runs.
AUTO_CHAIN_CAP = 3


def finish_run(folder, project_id, record, result, *,
               read_fn=None, write_fn=None, runner_kwargs=None) -> dict:
    """The run stopped: persist the record, then hand it to the engine —
    report, conversation log, raise, handback — via the ingest bridge.
    If the reflection says the next move needs no human input, CARRY ON:
    launch it unasked (John's standing autonomy rule), capped by AUTO_CHAIN_CAP."""
    session_id = record["session_id"]
    transcript = result.get("transcript", "") or ""
    # A re-armed watch must never ERASE the first watch's read (found live
    # 2026-08-06: watch 2 saw only post-snap silence and its thin report
    # replaced the rich verdict). Every prior report is kept.
    prior_reports = list(record.get("prior_reports") or [])
    if isinstance(record.get("report"), dict) and record["report"].get("say"):
        prior_reports.append(record["report"])
    updated = {
        **record,
        "prior_reports": prior_reports,
        "outcome": result.get("outcome"),
        "ran": result.get("ran"),
        "elapsed_s": result.get("elapsed_s"),
        "transcript_chars": result.get("transcript_chars"),
        "transcript_tail": transcript[-TRANSCRIPT_TAIL_CHARS:],
        "watch_count": int(record.get("watch_count", 0)) + 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # (steward-chamber W11, E3) THE RESURRECTION GUARD on the W2-proven
    # handback seam: BEFORE the ingest bridge reaches Ecgberht
    # engine/handback-ingest.mjs :: ingestHandback /
    # ingestValidatedHandbackBody, every predicate-bearing correction is
    # re-asserted against the artifact it names. A regression BLOCKS the
    # handback with the named finding; the unassertable remainder rides the
    # report DEMOTED. Fails CLOSED on an unreadable corrections store; a
    # project with zero corrections passes trivially (honest zero report).
    try:
        import chamber_corrections as _ccx
        guard = _ccx.handback_guard(folder)
    except Exception as exc:
        guard = {"ok": False, "blocked": True,
                 "finding": "E3-CORRECTION-REGRESSED-HANDBACK-BLOCKED",
                 "error": "guard-crashed", "message": str(exc)[:200]}
    if guard.get("blocked"):
        updated["handback_blocked"] = guard
        updated["ingest_error"] = guard.get("finding")
        updated["report"] = {
            "say": "Handback BLOCKED (%s): %s"
                   % (guard.get("finding"),
                      guard.get("message") or "correction regression"),
        }
        _atomic_write_json(_run_record_path(folder, session_id), updated)
        return {"ok": False, "record": updated, "blocked": guard,
                "ingest": None}

    ingest = run_bridge("ingest-run", {
        "project": str(folder),
        "project_id": project_id,
        "run": {
            "outcome": result.get("outcome"),
            "transcript": transcript,
            "ran": result.get("ran"),
            "elapsed_s": result.get("elapsed_s"),
            "skill": record.get("skill"),
            "step_id": record.get("step_id"),
            "session_id": session_id,
            "commission_id": record.get("commission_id"),
            "worktree": record.get("worktree_path"),
        },
    }, timeout=INGEST_TIMEOUT_S)

    if ingest.get("ok"):
        updated["report"] = ingest.get("report")
        # (2026-08-07) The frontier reflection: impact, findings fed into the
        # scaffolding, and the composed next-move directive John iterates on.
        updated["reflection"] = ingest.get("reflection")
        updated["raised"] = ingest.get("raised")
        updated["handback"] = (ingest.get("handback") or {}).get("ingested") \
            if isinstance(ingest.get("handback"), dict) else None
    else:
        # The ingest failing is a fact John gets, not a silent swallow.
        updated["report"] = {
            "say": "The run stopped but I could not read it back "
                   f"({ingest.get('error', 'bridge_failed')}). Open the session to see it.",
        }
        updated["ingest_error"] = ingest.get("error")

    if result.get("watcher_error"):
        updated["watcher_error"] = result.get("watcher_error")

    # BANK the terminal state FIRST (2026-08-07 shark round): the auto hop
    # spawns bridge processes and can block for seconds — during which the
    # rest of the system must already see this run as finished, not running.
    _atomic_write_json(_run_record_path(folder, session_id), updated)

    # CARRY ON (2026-08-07): reflection said the next move is fully determined
    # by what is on file — no decision is John's — so launch it now. Only after
    # a clean produced run (asked/died/timeout always come back to him), and
    # never more than AUTO_CHAIN_CAP hops without him touching the campaign.
    updated["auto_continue"] = _maybe_auto_continue(
        folder, project_id, updated, ingest,
        read_fn=read_fn, write_fn=write_fn, runner_kwargs=runner_kwargs)
    if updated["auto_continue"] is not None:
        _atomic_write_json(_run_record_path(folder, session_id), updated)

    # W5 brief precompute (steward chamber): the reflection just landed, so
    # precompute the situation brief into the chamber sidecar NOW — the next
    # Seal open paints it with zero model calls (E8: steward-plane sidecar
    # only; roadmap/receipts/reflection stores untouched). Best-effort by
    # contract — a projector hiccup never blocks a run finishing; the W5
    # cold-open rebuild is the cure. Runs BEFORE the campaign commit so the
    # sidecar rides the same bank.
    try:
        import chamber_reconcile as _chamber_reconcile
        _chamber_reconcile.on_reflection_landing(folder)
    except Exception:
        pass

    # W9 deliverable landing (steward chamber, C2 — ENGINE-FED, never
    # model-remembered): the run just stopped, so if the manifest-declared
    # output now exists CONTAINED on disk, record the W4 deliverable_landing
    # projection NOW — the open chamber's injection-clock poll flips the ◇
    # box live with no reopen. Idempotent per output path; best-effort by
    # the same contract as the brief precompute above (a sidecar hiccup
    # never blocks a run finishing).
    try:
        import chamber_deliverable as _chamber_deliverable
        _chamber_deliverable.record_landing_if_present(folder, updated)
    except Exception:
        pass

    # W10 died→sweep-card state machine (steward-chamber, C5/E2): a run that
    # ended died/quiet/timeout registers SWEEP-PENDING now — from here the
    # E2 gate in confirm_and_launch blocks any re-commission until the
    # containment-checked sweep card is bound into the queue, and a HELD
    # gate is never dropped (the transition never touches the queue head).
    # Best-effort by the same sidecar contract as the hooks above; the E2
    # refusal itself is enforced at the confirm_and_launch seam.
    try:
        if result.get("outcome") in ("died", "quiet", "timeout"):
            import chamber_gates as _cgates
            _cgates.on_run_death(folder, updated)
    except Exception:
        pass

    # A finished run changed campaign state (record, attention, log) — bank it.
    commit_campaign_state(
        folder, f"{record.get('skill', 'skill')} run {result.get('outcome')}")
    return {"ok": True, "record": updated, "ingest": ingest}


def _maybe_auto_continue(folder, project_id, updated, ingest, *,
                         read_fn=None, write_fn=None,
                         runner_kwargs=None) -> Optional[dict]:
    """The autonomy hop: propose + confirm + launch the reflection's next move
    when it declared needs_human false. Returns the note stored on the run
    record (None when the situation simply doesn't call for one). Best-effort —
    a failed hop is a recorded fact, never an exception up the watcher."""
    try:
        reflection = ingest.get("reflection") if ingest.get("ok") else None
        nxt = (reflection or {}).get("next") if isinstance(reflection, dict) else None
        if not (isinstance(nxt, dict) and nxt.get("skill") and nxt.get("directive")):
            return None
        if nxt.get("needs_human") is not False:
            return None
        # Defense in depth (2026-08-07 shark round): an unattended hop must
        # aim a NAMED roadmap step with one of the five commissionable
        # engines — the engine parse enforces both, this refuses if anything
        # slipped through a stale bridge.
        if nxt.get("skill") not in ("researchPrime", "Crucible", "Foreman",
                                    "Gandalf", "Jumper"):
            return {"launched": False, "reason": "skill-not-commissionable",
                    "detail": str(nxt.get("skill"))[:60]}
        if not nxt.get("step_id"):
            return {"launched": False, "reason": "no-step-id",
                    "say": "The next move named no roadmap step — bringing "
                           "it to John instead."}
        # A stuck model re-proposing the move that JUST ran is the classic
        # burn loop (shark P1) — an identical hop always goes back to John.
        if (nxt.get("step_id") == updated.get("step_id")
                and nxt.get("skill") == updated.get("skill")):
            return {"launched": False, "reason": "same-move",
                    "say": "The next move would repeat the run that just "
                           "finished — checking with you instead of looping."}
        if updated.get("outcome") != "produced":
            return {"launched": False, "reason": "outcome-not-produced",
                    "say": "The next move was ready but this run didn't end "
                           "clean — bringing it to John instead."}
        chain = int(updated.get("auto_chain") or 0)
        if chain >= AUTO_CHAIN_CAP:
            return {"launched": False, "reason": "auto-chain-cap",
                    "say": f"I've carried on {chain} times in a row without "
                           "you — checking in before the next move."}
        # The finished session's PTY is usually STILL OPEN, and the executor's
        # DEGRADED one-run-at-a-time scan refuses a new launch while a prior
        # intent's pid is alive (found in the 2026-08-07 hardening pass —
        # without this every auto hop dies EXEC_SUBSTRATE_BUSY). The run is
        # produced + ingested + reflected: park it gracefully (close is
        # warm-resumable, docs persisted; John reopens it any time).
        try:
            import terminal_session as _ts
            _ts.close_session(updated.get("session_id"),
                              project_id=project_id, actor="steward-auto-continue")
        except Exception:
            pass
        proposed = propose(folder, step_id=(nxt.get("step_id") or None),
                           skill=nxt.get("skill"))
        if not proposed.get("ok"):
            detail = proposed.get("error") or proposed.get("message")
            return {"launched": False, "reason": "propose-refused",
                    "detail": detail,
                    "say": "I tried to carry on but couldn't frame the next "
                           f"commission ({detail}) — your call from here."}
        tok = _paths.expected_token()
        launched = confirm_and_launch(
            folder, proposed,
            project_id=project_id,
            # Honest provenance: John's 2026-08-07 standing autonomy rule is
            # the confirming authority, never a fabricated human click.
            who="john-standing-autonomy",
            directive=nxt.get("directive"),
            # Chain depth rides the record FROM BIRTH — the watcher's
            # in-memory copy must carry it or its finish_run would drop it
            # (cap bypass, found in the 2026-08-07 hardening pass).
            record_extra={"auto_chain": chain + 1,
                          "auto_from": updated.get("session_id")},
            read_fn=read_fn, write_fn=write_fn, runner_kwargs=runner_kwargs,
            auth_ctx={"token": tok} if tok else None,
            expected_token=tok,
            enforce_auth=bool(tok),
        )
        if not launched.get("ok"):
            detail = launched.get("error") or launched.get("message")
            return {"launched": False, "reason": "launch-refused",
                    "detail": detail,
                    "say": "I tried to carry on but the launch was refused "
                           f"({detail}) — nothing is running; your call."}
        new_sid = launched.get("session_id")
        return {"launched": True, "session_id": new_sid,
                "skill": launched.get("skill"), "step_id": launched.get("step_id"),
                "auto_chain": chain + 1,
                "say": f"Carried on without you: {launched.get('skill')} is now "
                       "running with the directive I composed — "
                       + (nxt.get("why") or "it needed no decision of yours.")}
    except Exception as exc:
        return {"launched": False, "reason": "auto-continue-threw",
                "detail": str(exc)[:200]}


# ── Campaign state → git (a crash costs nothing) ────────────────────────────

#: The campaign's durable surfaces — staged EXPLICITLY, never `git add -A`
#: (the user's unrelated changes are not the steward's to commit).
CAMPAIGN_STATE_PATHS = (
    "roadmap.json", "ECGBERHT.md", "Anchor.md", "strip.json",
    ".ecgberht", ".anchor",
)


def commit_campaign_state(folder, label: str = "campaign state") -> dict:
    """Commit the steward's campaign surfaces in the PROJECT repo. Best-effort,
    never raises — John's standing rule (2026-08-06, his first real campaigns):
    'you should be committing things as we go along so they don't lose
    anything.' Both his campaigns sat untracked for a day before this existed.
    """
    out = {"ok": False, "committed": False, "reason": "ok"}
    try:
        import subprocess as _sp
        import project_bootstrap as _pb
        folder = str(folder)
        _pb.ensure_git_repo(folder)

        def _git(*args):
            return _sp.run(["git", *args], cwd=folder, capture_output=True,
                           text=True, timeout=60,
                           creationflags=getattr(_paths, "NO_WINDOW", 0))

        present = [p for p in CAMPAIGN_STATE_PATHS
                   if (Path(folder) / p).exists()]
        if not present:
            out.update(ok=True, reason="no-campaign-state")
            return out
        _git("add", "--", *present)
        staged = _git("diff", "--cached", "--name-only")
        if not (staged.stdout or "").strip():
            out.update(ok=True, reason="nothing-new")
            return out
        done = _git("-c", "user.email=ecgberht@anchor.local",
                    "-c", "user.name=Ecgberht Steward",
                    "commit", "-m", f"ecgberht: {label}")
        out.update(ok=done.returncode == 0, committed=done.returncode == 0,
                   reason="ok" if done.returncode == 0
                   else (done.stderr or done.stdout or "commit-failed")[:200])
        return out
    except Exception as exc:
        out["reason"] = str(exc)[:200]
        return out


# ── Hand it back (after John answered in the session) ───────────────────────

def rearm_watch(folder, project_id, session_id, *,
                read_fn=None, write_fn=None, runner_kwargs=None,
                thread_factory=None) -> dict:
    """John answered in the session and handed it back — resume the watch
    WITHOUT sending anything (the cursor snaps past the old question first)."""
    record = load_run_record(folder, session_id)
    if record is None:
        return {"ok": False, "error": "unknown_run",
                "message": "No commission run record for that session."}
    if watcher_active(session_id):
        return {"ok": True, "already_watching": True, "session_id": session_id}
    started = _start_watcher(
        folder, project_id, record, watch_only=True,
        read_fn=read_fn, write_fn=write_fn,
        runner_kwargs=runner_kwargs, thread_factory=thread_factory)
    return {"ok": started, "session_id": session_id, "watching": started,
            "say": "Watching again — carry on; I'll take it from here."}

# NOTE deliberately ABSENT: a panel-close re-arm hook. The panel × is a
# GRACEFUL CLOSE that STOPS the PTY (terminal_session.close_session) — there
# is nothing left to watch after it. Handing a session back to the steward is
# an explicit act on a LIVE session ("Hand it back" → /commission_watch),
# which is also exactly how John described the flow.
