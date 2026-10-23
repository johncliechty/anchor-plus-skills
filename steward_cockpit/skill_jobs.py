"""Skill jobs (two-lane step 3, John 2026-10-06 "build 3 anyway ... see how it performs"): a FENCED steward cannot
run a Foundry skill in its own turn (its edits and shell are fenced to its effort folder), so it asks the server, and
the server - outside any fence - starts the skill in the effort folder, keeps its log, and wakes the steward with the
result, the way a code job does. Only a skill's own run script under a skill root is accepted (node or python + a
script inside C:/dev/trio or C:/dev/Skill Foundry/skills); the record is .ecgberht/skill-jobs.json.

Lifetime parity with code jobs (2026-10-10). The skill runs CONTAINED - code_jobs._popen_contained, the verified
kill-on-close Windows Job Object every code-job command runs in, so Anchor's own end takes every process the skill
started - and with NO clock on it: a skill runs until it ends or John stops it (the six-hour auto-kill is gone;
duration is never evidence of a hang). Its process identity (pid + creation time), its phase and its progress evidence
(log growth) are persisted on the record and sampled by the steward's own ticker through code_job_progress: quiet means
inspect, never failed. Stop ends the whole tree and SEES it gone before the record says stopped; a tree that cannot be
seen to end keeps the job - and its claim - until it can. A running record no live Anchor holds is reconciled after a
restart as INTERRUPTED under the same job id (its log kept), never as a success and never by starting another run. The
result is a durable handoff on the record (needs_report -> pending -> queued -> collected) delivered through the
engine's job-result queue, collectable by ``steward_skill.py collect --job <id>``. A skill job runs in the effort
folder itself, not a worktree: Anchor lands, reviews and commits nothing for it, and its result never says otherwise.
Foreman never runs here (it writes a project: code_jobs.start --worker foreman). Only Crucible's proved slim
entry point is available by default; its older launch paths keep their hold.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from steward_cockpit import code_jobs as _cj

JOBS_FILE = ".ecgberht/skill-jobs.json"
LOG_DIR = ".ecgberht/skill-jobs"
LIVE = ("running",)
OBSERVE_S = _cj.COMMAND_OBSERVE_S      # observation cadence - never a runtime limit
END_WAIT_S = 60                        # how long one end attempt waits to SEE the tree gone before it says it could not
SUPERVISE_EVERY_S = 30
_LOCK = threading.RLock()
_PROCS = {}            # job id -> _Reserved | code_jobs._Run: the skill processes THIS Anchor holds
_STOPPING = set()      # job ids a Stop is ending: a launch that has not happened never happens
_HANDOFF_LOCKS = {}
_log = logging.getLogger(__name__)


def skill_roots():
    env = os.environ.get("ANCHOR_SKILL_ROOTS")
    ws = Path(__file__).resolve().parents[2]
    roots = env.split(os.pathsep) if env else [str(ws / "trio"), str(ws / "Skill Foundry" / "skills")]
    return [Path(r).resolve() for r in roots if r]


def _path(cdir):
    return Path(cdir) / JOBS_FILE


def read_jobs(cdir, *, strict=False):
    """The registry; a WRITER (strict) never takes an unreadable existing registry for an empty one."""
    with _LOCK:
        try:
            data = json.loads(_path(cdir).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("the skill-job registry is not an object")
            return data
        except FileNotFoundError:
            return {}
        except Exception:
            if strict:
                raise
            return {}


def _write_all(cdir, jobs):
    p = _path(cdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp-%s" % uuid.uuid4().hex[:6])
    tmp.write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    _cj._replace(str(tmp), str(p))


def _write_job(cdir, job):
    with _LOCK:
        jobs = read_jobs(cdir, strict=True)
        jobs[job["id"]] = job
        _write_all(cdir, jobs)


def _transition(cdir, job_id, expect, **updates):
    """One locked status change (the code-job contract): ``updates`` apply only while the job's status is in
    ``expect``; returns the job after the change, else None (an end and a Stop never both win). Leaving ``running``
    leaves a durable obligation: a result that has not been written yet is ``needs_report``."""
    with _LOCK:
        jobs = read_jobs(cdir, strict=True)
        j = jobs.get(job_id)
        if not j or j.get("status") not in expect:
            return None
        was_live = j.get("status") in LIVE
        j.update(updates)
        if was_live and j.get("status") not in LIVE and not (j.get("handoff") or {}).get("id"):
            j["handoff"] = {"state": "needs_report", "attempt": j.get("attempt", 1)}
        jobs[job_id] = j
        _write_all(cdir, jobs)
        return dict(j)


def validate(argv):
    """(ok, reason): node|python + a script inside a skill root; no shell, no other program."""
    if not isinstance(argv, list) or len(argv) < 2 or not all(isinstance(a, str) and a for a in argv):
        return False, "argv must be a list: node|python <a skill's script> [args]"
    if Path(argv[0]).name.lower().replace(".exe", "") not in ("node", "python"):
        return False, "only node or python may start a skill"
    try:
        script = Path(argv[1]).resolve()
    except Exception:
        return False, "the script path does not resolve"
    if not script.is_file():
        return False, "no such script: %s" % argv[1]
    parts = [part.lower() for part in script.parts]
    if "foreman" in parts or "foreman" in script.name.lower():   # 2026-10-09: Foreman writes a project, so it runs only
                                                                     # as a code job - its wrappers too (run-foreman.mjs)
        return False, _cj.FOREMAN_AS_SKILL
    slim = any(script == (root / "crucible" / "bin" / "slim.mjs").resolve() for root in skill_roots())
    if _cj.foreman_crucible_held() and "crucible" in parts and not slim:
        return False, _cj.HOLD_REASON
    for root in skill_roots():
        try:
            script.relative_to(root)
            return True, ""
        except ValueError:
            continue
    return False, "the script is not inside a skill root (%s)" % ", ".join(str(r) for r in skill_roots())


def running(cdir):
    """The running skill jobs, after the records no live Anchor holds have been reconciled."""
    reconcile(cdir)
    return [j for j in read_jobs(cdir).values() if j.get("status") in LIVE]


class _Reserved:
    """A place in _PROCS taken before the drain question is asked (final review r2): a restart that begins between
    the question and the spawn still sees a skill job about to run."""
    pid = None

    def poll(self):
        return None


def _stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _tail(path, n=1500):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def _observe(cdir, job_id, stuck=None, **fields):
    """Persist process evidence on the running record (best effort: an observation that cannot be written never
    changes what is kept, nor the job's claim)."""
    try:
        with _LOCK:
            cur = read_jobs(cdir).get(job_id)
            if not cur or cur.get("status") not in LIVE:
                return None
            process = dict(cur.get("process") or {})
            process.update(fields)
            upd = {"process": process}
            if stuck is not None:
                upd["stuck"] = stuck
            return _transition(cdir, job_id, LIVE, **upd)
    except Exception as exc:
        _log.warning("skill job %s: observation not saved: %s", job_id, exc)
        return None


def _stop_asked(cdir, job_id):
    try:
        cur = read_jobs(cdir, strict=True).get(job_id)
    except Exception:
        return False                                    # lost visibility is not a Stop instruction
    if not isinstance(cur, dict) or not cur.get("status"):
        return False
    return bool(cur.get("stop_requested") or cur.get("status") not in LIVE)


def start(cdir, argv, label="", actor=""):
    """Start a skill job in the effort folder ``cdir``: contained, recorded FIRST (a launch that fails leaves an
    honest failed record under the same id, never an unowned process), with no clock on it."""
    ok, why = validate(argv)
    if not ok:
        return {"ok": False, "error": why}
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    _PROCS[job_id] = _Reserved()
    try:
        from steward_cockpit import maintenance
        if maintenance.is_active():
            _PROCS.pop(job_id, None)
            return {"ok": False, "error": "Anchor is draining for a restart; start the skill when it is back"}
    except ImportError:
        pass
    log_rel = "%s/%s.log" % (LOG_DIR, job_id)
    log_path = Path(cdir) / log_rel
    now = time.time()
    job = {"id": job_id, "label": (label or Path(argv[1]).stem)[:120], "argv": argv, "status": "running",
           "attempt": 1, "started": _stamp(), "started_epoch": now, "started_by": str(actor or "the steward"),
           "log": log_rel, "cwd": str(Path(cdir)), "phase": "running", "phase_at": now,
           "process": {"state": "starting", "pid": None, "birth": None, "contained": None, "activity_at": None,
                       "output_bytes": 0}}
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)          # subscription billing, as every skill launcher does
    env["CRUCIBLE_AGENT_LIVE"] = "1"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "w", encoding="utf-8")
    except Exception as e:
        _PROCS.pop(job_id, None)
        return {"ok": False, "error": "could not open the skill job's log (%s); nothing started" % e}
    try:
        _write_job(cdir, job)
    except Exception as e:                          # unrecorded means unowned: nothing is launched
        out.close()
        _PROCS.pop(job_id, None)
        return {"ok": False, "error": "could not record the skill job (%s); nothing started" % e}
    try:
        with _LOCK:                                 # Stop and the launch never cross: one sees the other
            cur = read_jobs(cdir).get(job_id) or {}
            if job_id in _STOPPING or cur.get("status") not in LIVE:
                out.close()
                _PROCS.pop(job_id, None)
                _STOPPING.discard(job_id)
                return {"ok": False, "error": "the skill job was stopped before it launched", "job": job_id}
            try:
                run = _cj._popen_contained(argv, str(cdir), env, out)
            except _cj._Uncontained as u:         # it may run: kept counted, watched, and Stop ends it
                _PROCS[job_id] = u.run
                _observe(cdir, job_id, stuck=str(u) + "; Stop ends it and releases the job", state="active",
                         pid=u.run.pid, contained=False, launched_at=time.time())
                threading.Thread(target=_wait, args=(cdir, job_id, u.run, out, log_path),
                                 name="skill-job-" + job_id, daemon=True).start()
                return {"ok": False, "error": "%s; the job keeps its place until Stop ends it" % u, "job": job_id,
                        "log": log_rel}
            _PROCS[job_id] = run
    except Exception as e:
        out.close()
        _PROCS.pop(job_id, None)
        failed = _transition(cdir, job_id, LIVE, status="failed", finished=_stamp(), rc=None,
                             error="could not start: %s" % e, phase="outcome", phase_at=time.time(),
                             process=dict(job["process"], state="dead"))
        if failed:
            _report(cdir, failed)
        return {"ok": False, "error": "could not start: %s" % e, "job": job_id}
    birth = None
    try:
        import proc_probe
        birth = proc_probe.creation_time(run.pid)
    except Exception:
        pass
    _observe(cdir, job_id, state="active", pid=run.pid, birth=birth, contained=run.wjob is not None,
             launched_at=time.time())
    threading.Thread(target=_wait, args=(cdir, job_id, run, out, log_path), name="skill-job-" + job_id,
                     daemon=True).start()
    return {"ok": True, "job": job_id, "log": log_rel, "pid": run.pid, "contained": run.wjob is not None}


def _wait(cdir, job_id, run, out, log_path):
    """Watch the skill until it ends or Stop ends it, with no deadline: observe the log for evidence, then SEE the
    whole tree gone before anything is recorded or released. A tree that cannot be seen to end keeps the job running
    and registered (its claim holds), whoever asked."""
    size = 0
    try:
        while True:
            exited = False
            try:
                run.proc.wait(timeout=OBSERVE_S)
                exited = True
            except subprocess.TimeoutExpired:
                pass                                # quiet, elapsed time: inspect, never a failure
            except Exception:
                try:
                    exited = run.poll() is not None
                except Exception:
                    exited = False
            cur = _size(log_path)
            if cur is not None and cur != size:
                size = cur
                _observe(cdir, job_id, activity_at=time.time(), output_bytes=size)
            if not (exited or _stop_asked(cdir, job_id)):
                continue
            ended = False
            try:
                ended = run.end(END_WAIT_S)
            except Exception as exc:
                _log.warning("skill job %s: end not confirmed: %s", job_id, exc)
            if ended:
                break
            _observe(cdir, job_id, stuck="the skill's process tree could not be seen to end; the job keeps its claim "
                     "until it can (Stop asks again)", state="cleanup_wait")
            if exited:
                time.sleep(OBSERVE_S)
    finally:
        try:
            out.close()
        except Exception:
            pass
    rc = run.proc.returncode
    size = _size(log_path)
    cur = read_jobs(cdir).get(job_id) or {}
    process = dict(cur.get("process") or {})
    process.update(state="ended", ended_at=time.time(), returncode=rc, tree_seen=True,
                   output_bytes=size if size is not None else process.get("output_bytes"))
    common = dict(finished=_stamp(), rc=rc, tail=_tail(log_path), phase="outcome", phase_at=time.time(),
                  process=process, stuck=None)
    if cur.get("stop_requested") or job_id in _STOPPING:
        done = _transition(cdir, job_id, LIVE, status="stopped", stopped_by=cur.get("stop_requested_by") or "unknown",
                           **common)
    else:
        done = _transition(cdir, job_id, LIVE, status="done" if rc == 0 else "failed",
                           error="" if rc == 0 else "the skill exited %s" % rc, **common)
    _PROCS.pop(job_id, None)                        # after the record: a reconcile never sees a running record unheld
    _STOPPING.discard(job_id)
    if done:
        try:
            _report(cdir, done)
        except Exception as exc:
            _log.warning("skill job %s: result not reported yet: %s", job_id, exc)


def stop(cdir, job_id=None, actor="unknown"):
    """Stop the running skill job (the newest when no id) on behalf of ``actor``: the Stop is recorded, the whole
    tree is ended and SEEN gone, and only then does the record say stopped. A tree that cannot be seen to end - or a
    process this Anchor does not hold - keeps the job and its claim, and says so."""
    jobs = [j for j in running(cdir) if not job_id or j["id"] == job_id]
    if not jobs:
        return {"ok": False, "error": "no skill job is running"}
    job = sorted(jobs, key=lambda j: j["started"])[-1]
    who = str(actor or "unknown")
    asked = _transition(cdir, job["id"], LIVE, stop_requested=_stamp(), stop_requested_by=who)
    if asked is None:
        return {"ok": False, "error": "the skill job finished while the stop was asked; see its result"}
    with _LOCK:
        _STOPPING.add(job["id"])
        run = _PROCS.get(job["id"])
        if isinstance(run, _Reserved):              # never launched, and now it never will
            _PROCS.pop(job["id"], None)
            _STOPPING.discard(job["id"])
            stopped = _transition(cdir, job["id"], LIVE, status="stopped", finished=_stamp(), stopped_by=who,
                                  phase="outcome", phase_at=time.time(), rc=None,
                                  process=dict(job.get("process") or {}, state="ended", stopped_before_launch=True))
            return {"ok": True, "job": job["id"], "stopped_by": who, "note": "stopped before it launched"}
    if not isinstance(run, _cj._Run):
        p = job.get("process") or {}
        pid = p.get("pid") or job.get("pid")
        from steward_cockpit.code_job_handoff import process_state
        state = process_state(pid, p.get("birth")) if pid else "unknown"
        if state == "dead":
            stopped = _transition(cdir, job["id"], LIVE, status="stopped", finished=_stamp(), stopped_by=who,
                                  phase="outcome", phase_at=time.time(), rc=None, tail=_tail(Path(cdir) / job["log"]),
                                  process=dict(p, state="ended", ended_at=time.time(), pid_seen_gone=True))
            _STOPPING.discard(job["id"])
            return {"ok": True, "job": job["id"], "stopped_by": who,
                    "note": "its process (pid %s) was already gone; nothing was running" % pid}
        _STOPPING.discard(job["id"])
        return {"ok": False, "job": job["id"], "stop_requested": True,
                "error": "this Anchor does not hold the skill's process (pid %s, started before a restart); it cannot "
                         "be verified ended from here, so the job keeps its claim - the stop stays recorded" % pid}
    ended = False
    try:
        ended = run.end(END_WAIT_S)
    except Exception as exc:
        _log.warning("skill job %s: stop not confirmed: %s", job["id"], exc)
    if not ended:
        _observe(cdir, job["id"], stuck="Stop could not see the skill's process tree end (pid %s); it keeps its claim - "
                 "try Stop again" % run.pid, state="cleanup_wait")
        return {"ok": False, "job": job["id"], "stop_requested": True,
                "error": "the skill job did not end when asked (pid %s); it keeps its claim - try Stop again" % run.pid}
    process = dict(job.get("process") or {}, state="ended", ended_at=time.time(), returncode=run.proc.returncode,
                   tree_seen=True)
    stopped = _transition(cdir, job["id"], LIVE, status="stopped", finished=_stamp(), stopped_by=who,
                          rc=run.proc.returncode, tail=_tail(Path(cdir) / job["log"]), phase="outcome",
                          phase_at=time.time(), process=process, stuck=None)
    _STOPPING.discard(job["id"])                    # recorded: the record's stop_requested carries it from here
    if stopped is None:                             # its wait saw the end first and recorded it
        cur = read_jobs(cdir).get(job["id"]) or {}
        return {"ok": True, "job": job["id"], "status": cur.get("status"), "stopped_by": cur.get("stopped_by") or who,
                "note": "its process tree was seen to end; its log is kept at %s" % job["log"]}
    return {"ok": True, "job": job["id"], "stopped_by": who,
            "note": "stopped; its process tree was seen to end; its log is kept at %s" % job["log"]}


def reconcile(cdir):
    """A running record this Anchor does not hold was started by an Anchor that has since ended. A CONTAINED skill
    (its Job Object died with that Anchor) is marked INTERRUPTED under its own id, its log kept - never a success,
    never a new run. A legacy or uncontained one is judged only by positive evidence of its process identity: gone ->
    interrupted; alive -> left running, unheld, said; unknown -> left running (quiet means inspect)."""
    try:
        jobs = read_jobs(cdir)
    except Exception:
        return
    from steward_cockpit.code_job_handoff import process_state
    for job in list(jobs.values()):
        if not isinstance(job, dict) or job.get("status") not in LIVE:
            continue
        with _LOCK:
            if job["id"] in _PROCS:
                continue
            p = job.get("process") or {}
            pid = p.get("pid") or job.get("pid")
            state = process_state(pid, p.get("birth")) if pid else "unknown"
            if p.get("contained") and state == "dead":
                why = ("interrupted: Anchor restarted while %s ran; its contained process tree ended with that Anchor "
                       "(exit code unknown); its log is kept at %s" % (job.get("label"), job.get("log")))
            elif state == "dead":
                why = ("interrupted: its process (pid %s) is gone and no Anchor held it (exit code unknown); its log is "
                       "kept at %s" % (pid, job.get("log")))
            else:
                if not job.get("unheld"):
                    _transition(cdir, job["id"], LIVE, unheld=True, stuck=(
                        "not held by this Anchor (started before a restart): its process%s cannot be stopped from here "
                        "until it ends; its log is watched" % ((" (pid %s)" % pid) if pid else "")))
                continue
            _transition(cdir, job["id"], LIVE, status="failed", finished=_stamp(), rc=None, interrupted=True, error=why,
                        tail=_tail(Path(cdir) / str(job.get("log") or "")), phase="outcome", phase_at=time.time(),
                        process=dict(p, state="dead"))


# ── Observation on the steward's ticker (code_job_progress: quiet means inspect, never failed) ─────────────────────
def supervise(job, *, now=None):
    now = time.time() if now is None else now
    from steward_cockpit import code_job_progress as progress
    from steward_cockpit.code_job_handoff import process_state
    p = job.get("process") or {}
    run = _PROCS.get(job["id"])
    if isinstance(run, _cj._Run):
        liveness = "active" if run.poll() is None else "completed"
    elif isinstance(run, _Reserved):
        liveness = "active"
    else:
        pid = p.get("pid") or job.get("pid")
        liveness = process_state(pid, p.get("birth"), p.get("ended_at")) if pid else "unknown"
    worker = {"state": liveness, "last_activity": p.get("activity_at")}
    if p.get("state") == "cleanup_wait":
        worker.update(waiting=job.get("stuck") or "waiting for the process tree to end", state="active")
    return progress.sample(job, worker, now=now)


def refresh_supervision(cdir, *, engine=None):
    """One cheap sample per live skill job on the existing steward tick; no process is started or ended here. An
    observation worth the steward's eye (quiet, lost visibility, dead) goes once through the engine's job-result queue
    as an OBSERVATION - never a completion, never an authorization to terminate or replace the run."""
    reconcile(cdir)
    now = time.time()
    for job in read_jobs(cdir).values():
        if not isinstance(job, dict) or job.get("status") not in LIVE:
            continue
        if now - float((job.get("supervision") or {}).get("observed_at") or 0) < SUPERVISE_EVERY_S:
            continue
        observation = supervise(job, now=now)
        _transition(cdir, job["id"], LIVE, supervision=observation)
        if engine is None or observation["state"] not in {"needs_attention", "dead", "waiting", "needs_inspection", "visibility_lost"}:
            continue
        if now - float(job.get("phase_at") or 0) < SUPERVISE_EVERY_S:
            continue                                # a fresh launch binds its handle first; this never ends work
        detail = {k: observation.get(k) for k in ("state", "reason", "progress_token", "progress_at")}
        revision = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()[:16]
        identity = "attention:skill:%s:%s:%s" % (job["id"], job.get("attempt", 1), revision)
        if (job.get("attention_notice") or {}).get("id") == identity:
            continue
        text = ("Observation of skill job %s (%s), not a completion or a new assignment: %s\n"
                "%s Inspect this original job for current evidence before acting (steward_skill.py inspect --job %s); "
                "this observation may be old by delivery. Elapsed time, silence or missing visibility does not "
                "authorize termination or a replacement run. Its log is %s. Continue independent authorized work.") % (
                    job["id"], job.get("label"), observation["reason"], observation["action"], job["id"], job.get("log"))
        accepted = engine.enqueue_job_result(identity, text)
        if accepted.get("ok"):
            _transition(cdir, job["id"], LIVE, attention_notice={"id": identity, "at": now})


# ── The durable result (the code-job handoff pattern on this registry) ─────────────────────────────────────────────
def _handoff_lock(cdir, jid):
    with _LOCK:
        return _HANDOFF_LOCKS.setdefault((_cj._norm(cdir), jid), threading.RLock())


def stage_line(job):
    """What John reads about a skill job: it ran, and how it ended - never a coding stage, never a landing."""
    if not isinstance(job, dict):
        return ""
    status = job.get("status")
    if status in LIVE:
        return "running" + ((" - " + job["stuck"]) if job.get("stuck") else "")
    if job.get("interrupted"):
        return "interrupted (no result; the run did not finish)"
    if status == "stopped":
        return "stopped by %s; its log is kept" % (job.get("stopped_by") or "unknown")
    if status == "done":
        return "finished (exit 0); nothing landed - a skill job has no Git landing"
    return "failed (%s)" % (job.get("error") or "exit %s" % job.get("rc"))


def _skill_name(job):
    """The skill a record ran, from its script (steward_campaign.skill_identity), else the script's own name."""
    script = str((job.get("argv") or ["", ""])[1])
    try:
        from steward_cockpit.steward_campaign import skill_identity
        return skill_identity(job) or Path(script).stem
    except Exception:
        return Path(script).stem


def _result_text(job):
    rc = job.get("rc")
    lines = ["(skill job %s result - not John) %s: %s%s." % (
                 job["id"], job.get("label"), job.get("status"), (" (exit %s)" % rc) if rc is not None else ""),
             "Skill: %s (%s). Ran in: %s - this effort folder itself, not a worktree." % (
                 _skill_name(job), (job.get("argv") or ["", ""])[1], job.get("cwd") or "the effort folder")]
    size = (job.get("process") or {}).get("output_bytes")
    lines.append("Log: %s%s - read it; what the skill wrote is in this folder, exactly as it left it." % (
        job.get("log"), (" (%s bytes)" % size) if isinstance(size, int) else ""))
    if job.get("error"):
        lines.append("Error: " + str(job["error"])[:300])
    if job.get("status") == "stopped":
        p = job.get("process") or {}
        evidence = ("its process tree was seen to end" if p.get("tree_seen") else
                    "stopped before launch" if p.get("stopped_before_launch") else
                    "the recorded pid was already gone" if p.get("pid_seen_gone") else
                    "see the recorded process evidence")
        lines.append("Stopped by %s; %s." % (job.get("stopped_by") or "unknown", evidence))
    lines.append("Stage: " + stage_line(job) + " (say the job's state in these words)")
    lines.append("Log tail: " + (job.get("tail") or "")[-600:])
    lines.append("No Git landing: Anchor landed, reviewed and committed nothing for this run; files the skill wrote are "
                 "in place, uncommitted (a read-only skill left none). Never call it landed, installed or live.")
    lines.append("Collect this original job's CURRENT result before acting (steward_skill.py collect --job %s). A "
                 "repeated notice is the same result: never start another run because it repeats. Tell John the "
                 "result in two or three plain sentences, with links to what it produced (give a concise summary "
                 "of what the run accomplished and organize clickable links to the key deliverables by topic/step)." % job["id"])
    return "\n".join(lines)


def save_result(cdir, job, text):
    """The result exists before a wake or send; same attempt and text has the same immutable identity."""
    revision = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    identity = "skill:%s:%s:%s" % (job["id"], job.get("attempt", 1), revision)
    with _LOCK:
        current = read_jobs(cdir).get(job["id"])
        if not current or current.get("status") in LIVE or current.get("attempt", 1) != job.get("attempt", 1):
            return None
        old = current.get("handoff") or {}
        if old.get("id") == identity:
            return old
        handoff = {"id": identity, "attempt": job.get("attempt", 1), "content_rev": revision, "state": "pending",
                   "text": text, "created_at": time.time(), "label": job.get("label"), "log": job.get("log"),
                   "cwd": job.get("cwd"), "status": current.get("status"), "stage": stage_line(current)}
        _transition(cdir, job["id"], (current["status"],), handoff=handoff)
        return handoff


def _handoff_update(cdir, jid, identity, expected, **changes):
    with _LOCK:
        job = read_jobs(cdir).get(jid)
        current = (job or {}).get("handoff") or {}
        if current.get("id") != identity or current.get("state") not in expected:
            return False
        _transition(cdir, jid, (job["status"],), handoff={**current, **changes})
        return True


def materialize(cdir, job_id):
    """Write the terminal result from the record's own persisted fields, without waking an engine."""
    with _handoff_lock(cdir, job_id):
        job = read_jobs(cdir).get(job_id)
        if not job or job.get("status") in LIVE:
            return None
        current = job.get("handoff") or {}
        if current.get("id"):
            return current
        try:
            return save_result(cdir, job, _result_text(job))
        except Exception as exc:
            with _LOCK:
                latest = read_jobs(cdir).get(job_id) or {}
                if latest.get("status") not in LIVE and not (latest.get("handoff") or {}).get("id"):
                    _transition(cdir, job_id, (latest.get("status"),), handoff={
                        "state": "needs_report", "attempt": job.get("attempt", 1), "last_try": time.time(),
                        "error": str(exc)[:300]})
            return None


def notify(cdir, job_id, *, engine=None, wake=False):
    """Queue the pending result on the steward's engine once (the existing job-result queue); a refusal keeps it
    pending with its error for the next tick."""
    from steward_cockpit import maintenance, steward_routes
    job = read_jobs(cdir).get(job_id)
    handoff = (job or {}).get("handoff") or {}
    if handoff.get("state") != "pending" or maintenance.is_active():
        return False
    try:
        eng = engine or steward_routes.get_engine(str(cdir), create=wake)
        if eng is None or _cj._norm(eng.dir) != _cj._norm(cdir) or getattr(eng, "general", False):
            return False
        if getattr(eng, "job_results_paused", False):
            return False
        if not eng.alive():
            if not wake:
                return False
            ok, why = eng.wake(fresh=False)
            if not ok:
                raise RuntimeError("wake refused: " + str(why))
        with _handoff_lock(cdir, job_id):           # never enter the engine while holding _LOCK
            current = (read_jobs(cdir).get(job_id) or {}).get("handoff") or {}
            if current.get("id") != handoff["id"] or current.get("state") != "pending":
                return False
            result = eng.enqueue_job_result(handoff["id"], handoff["text"])
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "control queue rejected the result")
            try:
                eng._emit({"t": "sys", "text": "skill job %s %s - %s" % (job_id, job.get("status"), job.get("label"))})
            except Exception:
                pass
            return _handoff_update(cdir, job_id, handoff["id"], ("pending",), state="queued", queued_at=time.time(), error="")
    except Exception as exc:
        _handoff_update(cdir, job_id, handoff["id"], ("pending",), error=str(exc)[:300], last_try=time.time())
        return False


def retry_pending(cdir, *, engine):
    """Materialize one saved outcome, then retry one notification, on the existing tick."""
    jobs = [j for j in read_jobs(cdir).values() if isinstance(j, dict)]
    due = [j for j in jobs if (j.get("handoff") or {}).get("state") == "needs_report"]
    if due:
        job = min(due, key=lambda j: (j.get("handoff") or {}).get("last_try", 0))
        materialize(cdir, job["id"])
    pending = [j for j in read_jobs(cdir).values() if isinstance(j, dict) and (j.get("handoff") or {}).get("state") == "pending"]
    if pending:
        job = min(pending, key=lambda j: (j.get("handoff") or {}).get("last_try", 0))
        return notify(cdir, job["id"], engine=engine, wake=True)
    return False


def collect(cdir, job_id, handoff_id=None):
    with _handoff_lock(cdir, job_id):
        materialize(cdir, job_id)
        with _LOCK:
            job = read_jobs(cdir).get(job_id)
            handoff = (job or {}).get("handoff") or {}
            if not job:
                return {"ok": False, "error": "no such skill job in this effort"}
            if not handoff.get("id"):
                return {"ok": False, "error": "no durable result yet; inspect this original job"}
            if handoff_id and handoff["id"] != handoff_id:
                return {"ok": False, "error": "this result was superseded; collect the current result", "handoff_id": handoff["id"]}
            _handoff_update(cdir, job_id, handoff["id"], ("pending", "queued"), state="collected", collected_at=time.time())
            current = read_jobs(cdir).get(job_id)
            return {"ok": True, "job": job_id, "handoff": current["handoff"], "status": current.get("status"),
                    "label": current.get("label"), "log": current.get("log"), "cwd": current.get("cwd")}


def inspect(cdir, job_id):
    reconcile(cdir)
    job = read_jobs(cdir).get(job_id)
    if not job:
        return {"ok": False, "error": "no such skill job in this effort"}
    try:
        start_at = time.mktime(time.strptime(job["started"], "%Y-%m-%d %H:%M:%S"))
        end_at = time.mktime(time.strptime(job["finished"], "%Y-%m-%d %H:%M:%S")) if job.get("finished") else time.time()
        elapsed = max(0, round(end_at - start_at))
    except (KeyError, ValueError):
        elapsed = None
    return {"ok": True, "job": job, "supervision": supervise(job) if job.get("status") in LIVE else job.get("supervision"),
            "phase": job.get("phase") or job.get("status"), "phase_at": job.get("phase_at"), "elapsed_seconds": elapsed,
            "stage": stage_line(job), "held": job["id"] in _PROCS}


def _report(cdir, job):
    """The job ended: its result is written durably first, then the steward is woken to read it and tell John."""
    try:
        if job.get("status") == "done":
            from steward_cockpit import steward_engine as _se
            _se.publish_delivery_receipts(cdir, since=float(job.get("started_epoch") or 0.0))
    except Exception:
        pass
    receipt = materialize(cdir, job["id"])
    if receipt and receipt.get("state") == "pending":
        notify(cdir, job["id"], wake=True)
    return receipt
