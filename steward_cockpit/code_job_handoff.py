"""The existing code job's inspect, recover and durable result handoff. No worker or scheduler lives here."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from steward_cockpit import code_jobs as cj

_HANDOFF_LOCKS = {}
_HANDOFF_LOCKS_LOCK = threading.Lock()


def _handoff_lock(cdir, jid):
    with _HANDOFF_LOCKS_LOCK:
        return _HANDOFF_LOCKS.setdefault((cj._norm(cdir), jid), threading.RLock())


def record_worker(job, pid):
    import proc_probe
    if pid:
        cj._transition(job["steward_dir"], job["id"], cj.LIVE,
                       worker_pid=pid, worker_birth=proc_probe.creation_time(pid))


def snapshot(job):
    """Pin saved bytes, deletions and Git HEAD; runtime/controller bookkeeping is not a product."""
    try:
        wt = job["worktree"]
        code, head, _ = cj._git(wt, "rev-parse", "HEAD")
        changed = cj.changed_paths(wt, cj.candidate_base(job))
        if code or changed is None:
            raise ValueError("cannot read saved Git tree")
        names = sorted(set(changed + list(job.get("manifest") or []) + list(job.get("outputs") or [])))
        files = {}
        for name in names:
            if cj._runtime(name):
                continue
            path = cj._output_path(wt, name)
            if path.is_file():
                files[name] = {"sha256": cj._file_hash(path), "mode": path.stat().st_mode}
            elif not path.exists():
                files[name] = None
            else:
                raise ValueError("not a regular artifact: " + name)
        return {"head": head, "files": files}
    except Exception as exc:
        return {"error": str(exc)[:300]}


_SKIP_WT_DIRS = {".git", ".anchor", ".ecgberht", ".foreman", ".foreman-job", "__pycache__", ".pytest_cache", "node_modules", ".next", "dist", "build", "venv", ".venv", ".worktrees", "rnd_jobs", "health_reports", "vendor"}
_WT_ACTIVITY_CACHE = {}
_WT_ACTIVITY_LOCK = threading.Lock()
_AUTO_FINISHING = set()


def worktree_activity(job):
    """Scan the job's worktree for files modified since the job started so live supervision and the Status pane see real
    file writes on disk even while a long tool call or script is running."""
    try:
        wt_raw = str(job.get("worktree") or "")
        if not wt_raw:
            return None
        wt = Path(wt_raw)
        if not wt.is_dir():
            return None
        floor = float(job.get("worker_birth") or job.get("phase_at") or 0) - 2.0
        if floor <= 0:
            return None
        now_bucket = int(time.time() // 10)
        cache_key = (wt_raw, int(floor), now_bucket)
        if cache_key in _WT_ACTIVITY_CACHE:
            return _WT_ACTIVITY_CACHE[cache_key]
        with _WT_ACTIVITY_LOCK:
            if cache_key in _WT_ACTIVITY_CACHE:
                return _WT_ACTIVITY_CACHE[cache_key]
            modified = []
            newest_mtime = 0.0
            newest_rel = ""
            newest_size = 0
            for root_dir, dirs, files in os.walk(wt):
                dirs[:] = [d for d in dirs if d not in _SKIP_WT_DIRS]
                for fname in files:
                    if fname in ("foreman.config.json", "_foreman-status.log", "foreman-checkpoint.json") or fname.endswith((".pyc", ".pyo", ".tmp")):
                        continue
                    fpath = Path(root_dir) / fname
                    try:
                        st = fpath.stat()
                    except OSError:
                        continue
                    if st.st_mtime >= floor:
                        rel = fpath.relative_to(wt).as_posix()
                        if cj._runtime(rel) or cj.never_lands(rel):
                            continue
                        modified.append(rel)
                        if st.st_mtime >= newest_mtime:
                            newest_mtime = st.st_mtime
                            newest_rel = rel
                            newest_size = st.st_size
            if not modified:
                _WT_ACTIVITY_CACHE[cache_key] = None
                return None
            kb = max(0.1, round(newest_size / 1024.0, 1)) if newest_size else 0.0
            summary = "%d file(s) modified in worktree \u00b7 latest %s (%.1f KB)" % (len(modified), newest_rel, kb)
            prog_stamp = "wt:%d:%s:%d" % (len(modified), newest_rel, int(newest_mtime))
            res = {
                "last_activity": newest_mtime,
                "progress_at": newest_mtime,
                "progress_token": prog_stamp,
                "worktree_summary": summary,
                "modified_count": len(modified),
            }
            if len(_WT_ACTIVITY_CACHE) > 128:
                _WT_ACTIVITY_CACHE.clear()
            _WT_ACTIVITY_CACHE[cache_key] = res
            return res
    except Exception:
        return None


def _merge_worktree_activity(job, out):
    wt_act = worktree_activity(job)
    if not wt_act:
        return out
    merged = dict(out)
    merged["worktree_summary"] = wt_act["worktree_summary"]
    if not merged.get("last_activity") or wt_act["last_activity"] > float(merged.get("last_activity") or 0):
        merged["last_activity"] = wt_act["last_activity"]
    if not merged.get("progress_at") or wt_act["progress_at"] > float(merged.get("progress_at") or 0):
        merged["progress_at"] = wt_act["progress_at"]
        merged["progress_token"] = wt_act["progress_token"]
    return merged


def observe(job):
    """Observe an existing worker without constructing/waking an engine. Unknown never means dead."""
    from steward_cockpit import steward_routes as sr
    out = {"state": "unknown", "last_activity": None}
    try:
        eng = sr.get_engine(job["worktree"], general=True, tid="1", create=False)
        if eng is not None:
            binding = getattr(eng, "code_job", None) or {}
            if binding.get("id") != job["id"] or cj._norm(binding.get("cdir", ".")) != cj._norm(job["steward_dir"]):
                return out
            out["last_activity"] = getattr(eng, "last_output", None) or None
            out.update(getattr(eng, "job_observation", None) or {})
            if eng.alive() and (eng.busy or eng.queue):
                return _merge_worktree_activity(job, {**out, "state": "active"})
            if job.get("worker_completed_at"):
                return _merge_worktree_activity(job, {**out, "state": "completed"})
        state = process_state(job.get("worker_pid"), job.get("worker_birth"), job.get("worker_completed_at"))
        return _merge_worktree_activity(job, {**out, "state": state})
    except Exception as exc:
        out["detail"] = str(exc)[:200]
    return out


def process_state(pid, birth, completed_at=None):
    import proc_probe
    if not pid:
        return "completed" if completed_at else "unknown"
    state, actual, _ = proc_probe.probe_status(pid)
    if actual is not None and birth is not None and abs(actual - birth) > 0.001:
        return "unknown"
    if state == proc_probe.PROBE_RUNNING:
        return "active" if birth is not None and actual == birth and not completed_at else "unknown"
    if state == proc_probe.PROBE_EXITED and actual == birth and birth is not None:
        return "completed" if completed_at else "dead"
    if proc_probe.pid_alive_via_enum(pid) is False:
        return "completed" if completed_at else "dead"
    return "unknown"


def check_state(job):
    if job.get("integration_check_ok") is False:
        return "failed"
    return "passed" if job.get("check_ok") is True else "failed" if job.get("check_ok") is False else "not_run"


def products(job):
    """Exact placed paths plus available reading links; this does not publish or accept anything."""
    import deliverables_register as dr
    found = []
    root = Path(job.get("land_to") or job["repo"]).resolve()
    scope = root / (job.get("work_dir") or "")
    for name in job.get("files") or []:
        item = {"path": name, "destination": str(root / name), "landed": bool(job.get("landed"))}
        try:
            path = cj._output_path(root, name)
            if path.is_file() and cj.is_document(name):
                pid, rel = dr.project_and_rel(scope)
                if pid:
                    target = dr.reading_target({"path": path.relative_to(scope).as_posix()},
                                              pid=pid, effort_rel=rel, effort_dir=str(scope))
                    item["href"] = target.get("read") or target.get("download") or ""
        except Exception as exc:
            item["link_error"] = str(exc)[:200]
        found.append(item)
    return found


def owned_job(cdir, job_id):
    job = cj.read_jobs(cdir).get(job_id)
    if not job or not job.get("steward_dir") or cj._norm(job["steward_dir"]) != cj._norm(cdir):
        return None
    return job


def inspect(cdir, job_id):
    job = owned_job(cdir, job_id)
    if job is None:
        return {"ok": False, "error": "no job owned by this commissioning effort"}
    worker = observe(job)
    supervision = supervise(job)
    why = recovery_error(job, worker=worker)
    try:
        start = time.mktime(time.strptime(job["started"], "%Y-%m-%d %H:%M:%S"))
        end = time.mktime(time.strptime(job["finished"], "%Y-%m-%d %H:%M:%S")) if job.get("finished") else time.time()
        elapsed = max(0, round(end - start))
    except (KeyError, ValueError):
        elapsed = None
    return {"ok": True, "job": job, "worker": worker, "supervision": supervision, "phase": job.get("phase") or job.get("status"),
            "phase_at": job.get("phase_at"), "elapsed_seconds": elapsed, "check_state": check_state(job),
            "stage": cj.stage_line(job), "recovery": {"available": not why, "reason": why,
                "action": "collect" if job.get("landed") else "inspect saved work; do not relaunch" if why
                    else "recover only when John asks to finish it" if job.get("status") == "stopped" else "recover"}}


def supervise(job, *, native=None, now=None):
    """Observe the currently responsible process, not the completed producer during its final checks."""
    from steward_cockpit import code_job_progress as progress
    now = time.time() if now is None else now
    if job.get("phase") not in (None, "producing", "outcome"):
        command = job.get("command") or {}
        claim = job.get("claim") or {}
        controller = process_state(claim.get("pid"), claim.get("birth")) if job.get("finalizer_active") else "unknown"
        worker = {"state": controller, "last_activity": command.get("activity_at")}
        if command.get("state") == "active" and command.get("phase") == job.get("phase"):
            child_state = process_state(command.get("pid"), command.get("birth"))
            if child_state == "dead" and controller == "active":
                worker["state"] = "completed"
            elif child_state == "dead" and controller == "unknown":
                worker["state"] = "unknown"
            else:
                worker["state"] = child_state
            worker["last_activity"] = command.get("activity_at")
        if command.get("state") == "cleanup_wait":
            worker.update(waiting=command.get("error") or "waiting for process tree to end", state="active")
        # Command completion is actual advancement, even if the controller is between phases.
        if command.get("ended_at") and command.get("phase") == job.get("phase"):
            worker.update(progress_at=command["ended_at"], progress_token="command:" + str(command.get("log")))
    else:
        worker = observe(job)
    if native is None and job.get("worker") == "foreman" and job.get("phase") in (None, "producing"):
        from steward_cockpit.steward_campaign import _code_job_native
        native = _code_job_native(job, now)
    res = progress.sample(job, worker, native=native, now=now)
    if worker.get("worktree_summary"):
        res["worktree_summary"] = worker["worktree_summary"]
    return res


def settle_stopped_finalizer(cdir, job):
    """Settle an explicit Stop only after proving its controller and child exited."""
    if (job.get("status") != "finishing" or not job.get("stop_requested")
            or not orphaned_finalizer(job)):
        return None
    attempt = job.get("attempt", 1)
    claim = job.get("claim")
    command = job.get("command")
    with cj._LOCK:
        current = owned_job(cdir, job.get("id"))
        if (not current or current.get("status") != "finishing"
                or not current.get("stop_requested")
                or current.get("attempt", 1) != attempt
                or current.get("claim") != claim
                or current.get("command") != command):
            return None
        stopped = cj._transition(
            cdir, current["id"], ("finishing",), expect_attempt=attempt,
            status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
            finalizer_active=False, phase="outcome", phase_at=time.time(),
            stopped_by=current.get("stop_requested_by") or "unknown",
            kept_worktree=current.get("worktree"),
            land_note="stopped after controller exited; saved work retained",
            files=current.get("files") or current.get("manifest") or [],
        )
    if stopped is not None:
        # Result recording and engine notification must not run under cj._LOCK.
        cj._report(cdir, stopped)
    return stopped


def refresh_supervision(cdir, *, engine=None):
    """The existing steward ticker takes one cheap sample per live job; no worker/model is started."""
    now = time.time()
    for job in cj.read_jobs(cdir).values():
        if settle_stopped_finalizer(cdir, job) is not None:
            continue
        if job.get("status") not in cj.LIVE or now - (job.get("supervision") or {}).get("observed_at", 0) < 30:
            continue
        observation = supervise(job, now=now)
        cj._transition(cdir, job["id"], cj.LIVE, expect_attempt=job.get("attempt", 1), supervision=observation)
        if (job.get("status") == "running" and job.get("phase") in (None, "producing")
                and not job.get("finalizer_active") and observation.get("liveness") == "dead"
                and now - float(job.get("phase_at") or 0) >= 15
                and job["id"] not in _AUTO_FINISHING
                and Path(str(job.get("worktree") or "")).is_dir()
                and (job.get("coder_family") in cj.FAMILIES or job.get("authors"))):
            try:
                wt_p = Path(job["worktree"])
                changed = [p for p in (cj.changed_paths(job["worktree"], cj.candidate_base(job)) or [])
                           if not cj._runtime(p) and not cj.never_lands(p)]
                if not changed:
                    dead_empty = cj._transition(
                        cdir, job["id"], ("running",), expect_attempt=job.get("attempt", 1),
                        status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        phase="outcome", phase_at=now, kept_worktree="",
                        error="worker process exited without modifying any files",
                        land_note="nothing changed; worker process exited",
                    )
                    if dead_empty is not None:
                        cj._report(cdir, dead_empty)
                    continue
                outputs_ready = True
                for decl in (job.get("outputs") or []):
                    dp = wt_p / decl
                    md_alt = dp.with_suffix(".md")
                    src_alt = dp.with_name(dp.stem + "_source.md")
                    if not ((dp.is_file() and dp.stat().st_size > 0)
                            or (md_alt.is_file() and md_alt.stat().st_size > 0)
                            or (src_alt.is_file() and src_alt.stat().st_size > 0)):
                        outputs_ready = False
                        break
                if not outputs_ready:
                    partial = cj._transition(
                        cdir, job["id"], ("running",), expect_attempt=job.get("attempt", 1),
                        status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        phase="outcome", phase_at=now, kept_worktree=job["worktree"],
                        files=changed,
                        error="worker process exited before completing all declared outputs",
                        land_note="not landed: worker process exited before completing all declared outputs; partial work is kept at %s" % job["worktree"],
                    )
                    if partial is not None:
                        cj._report(cdir, partial)
                    continue
                authors = [a for a in (job.get("authors") or [job.get("coder_family")]) if a in cj.FAMILIES]
                manifest = list(job.get("manifest") or []) or cj.foreman_manifest(job) or list(changed)
                _AUTO_FINISHING.add(job["id"])
                def _run_auto_finish(_cdir=cdir, _jid=job["id"], _authors=authors, _manifest=manifest):
                    try:
                        cj.finish(_cdir, _jid, {
                            "text": "Worker process exited with all declared outputs present; auto-finalizing saved worktree.",
                            "authors": _authors,
                            "manifest": _manifest,
                        })
                    finally:
                        _AUTO_FINISHING.discard(_jid)
                threading.Thread(target=_run_auto_finish, name="auto-finish-" + str(job["id"]), daemon=True).start()
                continue
            except Exception:
                _AUTO_FINISHING.discard(job["id"])
        if engine is not None and observation["state"] in {"needs_attention", "dead", "waiting", "needs_inspection", "visibility_lost"}:
            if now - float(job.get("phase_at") or 0) < 30:
                continue  # give a newly launched phase time to bind its handle; this never terminates work
            detail = {k: observation.get(k) for k in ("state", "reason", "progress_token", "progress_at")}
            revision = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()[:16]
            identity = "attention:%s:%s:%s" % (job["id"], job.get("attempt", 1), revision)
            if (job.get("attention_notice") or {}).get("id") == identity:
                continue
            text = ("Observation of original job %s (attempt %s), not a completion or a new assignment: %s\n"
                    "%s Inspect this original job for current evidence before acting; this observation may be old by delivery. "
                    "Elapsed time, silence or missing visibility does not authorize termination or a replacement worker. "
                    "Preserve its saved work and continue independent authorized work.") % (
                        job["id"], job.get("attempt", 1), observation["reason"], observation["action"])
            accepted = engine.enqueue_job_result(identity, text)
            if accepted.get("ok"):
                cj._transition(cdir, job["id"], cj.LIVE, expect_attempt=job.get("attempt", 1),
                               attention_notice={"id": identity, "at": now})


def recovery_error(job, worker=None):
    orphan = orphaned_finalizer(job)
    if job.get("landed") or job.get("placed"):
        return "already landed; collect the original result"
    if job.get("status") in cj.LIVE and not orphan:
        return "job is active or its finish is unresolved; no concurrent recovery"
    if job.get("finalizer_active") and not orphan:
        return "the prior controller has not released its finish; no concurrent recovery"
    stopped = job.get("status") == "stopped"          # John stopped it; finishing it later is his call, so it may be recovered
    if not stopped and ((job.get("status") not in ("done", "failed") and not orphan) or not job.get("worker_completed_at")):
        return "no completed-worker receipt; liveness/provenance is unknown"
    if (worker or observe(job))["state"] not in (("completed", "dead") if stopped else ("completed",)):
        return "worker is active or its liveness is unknown"
    if not job.get("authors") or any(a not in cj.FAMILIES for a in job["authors"]):
        return "original authorship is unknown"
    why = cj.destination_error(job.get("repo")) or cj.integration_required_error(job)
    if why:
        return why
    try:
        wt = Path(job["worktree"])
        if not wt.is_dir() or wt.resolve().name != job["id"]:
            return "saved worktree is missing or has the wrong identity"
        c, branch, _ = cj._git(wt, "branch", "--show-current")
        c2, common, _ = cj._git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
        c3, owner, _ = cj._git(job["repo"], "rev-parse", "--path-format=absolute", "--git-common-dir")
        if c or c2 or c3 or branch != job["branch"] or cj._norm(common) != cj._norm(owner):
            return "saved branch or owning repository does not match"
        saved = job.get("recovery_snapshot")
        if not isinstance(saved, dict) or saved.get("error") or "files" not in saved:
            return "no trustworthy saved path-hash manifest; preserve for attributed repair"
        if not snapshot_matches(job, snapshot(job), saved):
            return "saved work changed after completion; original authorship cannot be reused"
    except Exception as exc:
        return "cannot verify saved work: " + str(exc)[:200]
    return ""


def snapshot_matches(job, current_snap, saved_snap):
    """True when current_snap equals saved_snap, or when HEAD moved solely because _commit_manifest committed the
    job's own candidate commit on top of saved_snap['head'] with identical file hashes (plus Anchor reading copies)."""
    if not isinstance(current_snap, dict) or not isinstance(saved_snap, dict):
        return False
    if current_snap == saved_snap:
        return True
    if current_snap.get("error") or saved_snap.get("error"):
        return False
    cur_files = current_snap.get("files") or {}
    sav_files = saved_snap.get("files") or {}
    copies = set(job.get("anchor_copies") or [])
    if cur_files != sav_files:
        if {k: v for k, v in cur_files.items() if k not in copies} != {k: v for k, v in sav_files.items() if k not in copies}:
            return False
    if current_snap.get("head") == saved_snap.get("head"):
        return True
    wt = job.get("worktree") or ""
    c1, parent, _ = cj._git(wt, "rev-parse", str(current_snap.get("head") or "") + "^")
    c2, subj, _ = cj._git(wt, "log", "-1", "--format=%s", str(current_snap.get("head") or ""))
    return (c1 == 0 and c2 == 0 and parent.strip() == saved_snap.get("head")
            and subj.strip().startswith("Code job " + str(job.get("id") or "")))


def orphaned_finalizer(job):
    """Only positive death evidence releases an interrupted controller, never its age.

    New Windows commands die with their owner's Job Object. A legacy/unknown
    command or controller is not presumed safe. Byte/provenance gates still apply.
    """
    def identity_dead(pid, birth):
        if not pid or birth is None:
            return False
        try:
            import proc_probe

            state, actual_birth, _ = proc_probe.probe_status(pid)
            if (state == proc_probe.PROBE_RUNNING and actual_birth is not None
                    and abs(float(actual_birth) - float(birth)) > 0.001):
                return True
        except Exception:
            pass
        return process_state(pid, birth) == "dead"

    claim, command = job.get("claim") or {}, job.get("command") or {}
    if not job.get("finalizer_active") or not claim.get("pid") or claim.get("birth") is None:
        return False
    if not identity_dead(claim["pid"], claim["birth"]):
        return False
    if command and command.get("state") != "completed":
        return bool(command.get("contained") and command.get("pid") and command.get("birth") is not None
                    and identity_dead(command["pid"], command["birth"]))
    return True


def recover(cdir, job_id, *, check=None, outputs=None, actor="the steward", outside_ok=None, reviewer=None):
    """Recheck and land saved bytes asynchronously; never start a producer. ``outside_ok`` names repository files
    the caller knows changed outside the job for its own reasons (a steward's AGENTS.md); each is pinned to its bytes
    now and stops counting as an outside write only while it stays exactly so."""
    from steward_cockpit import maintenance
    if maintenance.is_active():
        return {"ok": False, "error": "Anchor is in maintenance; recovery stays pending"}
    job = owned_job(cdir, job_id)
    if job is None:
        return {"ok": False, "error": "no job owned by this commissioning effort"}
    if (job.get("status") == "running" and not job.get("finalizer_active")
            and observe(job).get("state") == "dead" and Path(str(job.get("worktree") or "")).is_dir()):
        rec = cj.stopped_record(job)
        if not rec.get("manifest"):
            rec["manifest"] = cj.foreman_manifest(job)
            rec["recovery_snapshot"] = snapshot(dict(job, manifest=rec["manifest"]))
        job = cj._transition(cdir, job_id, ("running",), expect_attempt=job.get("attempt", 1),
                             status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                             stopped_by="worker_exited", kept_worktree=job["worktree"], **rec) or job
    if job.get("status") == "stopped" and not job.get("recovery_snapshot"):
        job = cj._transition(cdir, job_id, ("stopped",), expect_attempt=job.get("attempt", 1),
                             **cj.stopped_record(job)) or job        # a job stopped before its stop saved this record
    why = recovery_error(job)
    if why:
        return {"ok": False, "error": why}
    revised_check, why = cj.normalize_check(job.get("check") if check is None else check)
    if why or not revised_check or (isinstance(revised_check, str) and not revised_check.strip()):
        return {"ok": False, "error": why or "recovery needs the existing applicable check"}
    revised_outputs, why = cj.declared_outputs(job.get("outputs") if outputs is None else outputs)
    saved_files = job["recovery_snapshot"]["files"]
    if why or any(p not in saved_files for p in revised_outputs):
        return {"ok": False, "error": why or "a corrected output must already be in the saved path-hash manifest"}
    why = cj.scope_error(job, job["worktree"], revised_outputs)
    if why:
        return {"ok": False, "error": why}
    reviewer = str(reviewer or "").strip().lower()
    if reviewer:
        if reviewer not in cj.FAMILIES:
            return {"ok": False, "error": "unknown reviewer family: %s" % reviewer}
        authors = [str(a).lower() for a in (job.get("authors") or [job.get("coder_family") or ""]) if a]
        if reviewer in authors:
            return {"ok": False, "error": "reviewer family (%s) is an author's family (%s)" % (reviewer, ",".join(authors))}
        if reviewer in cj.exhausted_families():
            return {"ok": False, "error": "reviewer family (%s) hit its usage limit recently" % reviewer}
    import proc_probe
    orphan = orphaned_finalizer(job)
    # 2026-10-12 (Book 1 v3): the last attempt's audit was clean and its coder is proven ended (recovery_error), so
    # whatever changed in the repository since then is not this job's coder - a steward editing its own AGENTS.md
    # after the job ended. The re-filing's audit starts from now (read under the repo lock, released before the
    # record lock below); anything its own check writes into the repository is still caught.
    pinned = {}
    for rel in outside_ok or []:
        rel = str(rel).replace(chr(92), "/").strip()
        if not rel or rel.startswith("/") or ":" in rel or ".." in rel.split("/"):
            return {"ok": False, "error": "outside-ok paths are repository-relative: %r" % rel}
        digest = cj.file_hash(job["repo"], rel)
        if digest is None:
            return {"ok": False, "error": "outside-ok path is not a file in the repository: %s" % rel}
        owned = (set(job.get("files") or []) | set(job.get("outputs") or []) | set(job.get("manifest") or [])
                 | set(revised_outputs or []) | set(((job.get("recovery_snapshot") or {}).get("files") or {}).keys()))
        if rel in owned:
            return {"ok": False, "error": "outside-ok cannot name the job's own file: %s" % rel}
        pinned[rel] = digest
    audit_from = None
    if cj.audit_clean(job) and not orphan:
        audit_from = cj.audit_point(job)
        if audit_from is None:
            return {"ok": False, "error": "the repository's state could not be read for the re-filing's audit; try again"}
    # No repo lock here or during the check/review. All placements keep their existing repo -> record lock order.
    with cj._LOCK:
        current = owned_job(cdir, job_id)
        if (not current or (current.get("status") not in ("done", "failed", "stopped") and not orphan)
                or current.get("attempt", 1) != job.get("attempt", 1)
                or (current.get("finalizer_active") and not orphan)
                or (current.get("status") != "stopped" and (current.get("stop_requested") or current.get("stopped_by")))
                or (orphan and (current.get("claim") != job.get("claim") or current.get("command") != job.get("command")))
                or current.get("landed") or current.get("placed")):
            return {"ok": False, "error": "job changed while recovery was being prepared"}
        jobs_now = cj.read_jobs(cdir)
        def busy_or_landed(r):
            return bool(r) and (r.get("status") in cj.LIVE or r.get("landed") or r.get("placed") or r.get("finalizer_active"))
        redo = next((j for j, r in jobs_now.items() if r.get("escalates") == job_id and busy_or_landed(r)), None)
        if redo:                                      # five r3 #4 / r15: only while the redo runs or once it landed -
            return {"ok": False, "error": "%s is being redone at standard by %s, or that redo landed; inspect that job"
                    % (job_id, redo)}                 # a redo that ended unlanded leaves the original recoverable
        if current.get("escalates") and busy_or_landed(jobs_now.get(current["escalates"])):
            return {"ok": False, "error": "the small job this redoes (%s) is running or landed; inspect it first"
                    % current["escalates"]}
        if maintenance.is_active():
            return {"ok": False, "error": "Anchor entered maintenance"}
        history = list(current.get("attempts") or []) + [{k: current.get(k) for k in (
            "attempt", "finished", "check", "outputs", "check_ok", "review", "delta_review", "land_note", "error", "handoff",
            "command", "claim", "supervision", "stopped_by", "stop_requested", "stop_requested_by",
            "served_tree_changed", "audit_from", "audit_ok_attempt", "outside_ok")}]
        claimed = cj._transition(cdir, job_id, (current["status"],), status="finishing", finishing_at=time.time(),
            expect_attempt=job.get("attempt", 1), finalizer_active=True,
            finished="", attempt=job.get("attempt", 1) + 1, attempts=history, check=revised_check, outputs=revised_outputs,
            claim={"pid": os.getpid(), "birth": proc_probe.creation_time(os.getpid()), "actor": str(actor), "at": time.time()},
            handoff=None, phase="checking", phase_at=time.time(), error="", check_ok=None,
            stopped_by=None, stop_requested=None, stop_requested_by=None, kept_worktree="",
            worker_completed_at=current.get("worker_completed_at") or time.time(),   # a stopped coder is proven ended above
            integration_check_ok=None, review=None, delta_review=None, supervision=None, command=None,
            served_tree_changed=None, audit_ok_attempt=None, audit_from=audit_from or current.get("audit_from"),
            outside_ok=pinned or None, reviewer_family=reviewer or current.get("reviewer_family") or None)
        busy = cj._busy_read()
        busy[job_id] = {"job": job_id, "cdir": str(cdir), "repo": cj._norm(job["repo"])}
        try:
            cj._busy_write(busy)
        except Exception as exc:
            cj._transition(cdir, job_id, ("finishing",), status="failed", phase="outcome", phase_at=time.time(),
                expect_attempt=claimed["attempt"], finalizer_active=False,
                finished=time.strftime("%Y-%m-%d %H:%M:%S"), error="recovery reservation failed: " + str(exc))
            return {"ok": False, "error": "recovery reservation could not be saved: " + str(exc)}
    def complete():
        try:
            # Compare again after claim, before any controller command can alter the snapshot.
            if not snapshot_matches(job, snapshot(job), job["recovery_snapshot"]):
                raise ValueError("saved work changed while recovery was claimed")
            cj._finish(cdir, job_id, claimed, {"text": job.get("summary"), "manifest": job.get("manifest") or [],
                                           "authors": job["authors"]})
        except Exception as exc:
            done = cj._transition(cdir, job_id, ("finishing",), status="failed", phase="outcome", phase_at=time.time(),
                expect_attempt=claimed["attempt"],
                finished=time.strftime("%Y-%m-%d %H:%M:%S"), error="recovery failed: " + str(exc),
                kept_worktree=job["worktree"], land_note="not landed; saved work retained")
            if done:
                cj._report(cdir, done)
        finally:
            cj._transition(cdir, job_id, ("finishing", "done", "failed", "stopped"),
                           expect_attempt=claimed["attempt"], finalizer_active=False)
    try:
        threading.Thread(target=complete, name="recover-code-job-" + job_id, daemon=True).start()
    except Exception as exc:
        cj._transition(cdir, job_id, ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                       expect_attempt=claimed["attempt"], finalizer_active=False, error="recovery controller could not start: " + str(exc))
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "job": job_id, "attempt": claimed["attempt"], "repo": job["repo"],
            "work_dir": job.get("work_dir", ""), "worker_restarted": False}


def save_result(cdir, job, text):
    """The result exists before a wake or send; same attempt and text has the same immutable identity."""
    revision = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    identity = "%s:%s:%s" % (job["id"], job.get("attempt", 1), revision)
    with cj._LOCK:
        current = owned_job(cdir, job["id"])
        if not current or current.get("attempt", 1) != job.get("attempt", 1) or current.get("status") in cj.LIVE:
            return None
        old = current.get("handoff") or {}
        if old.get("id") == identity:
            return old
        handoff = {"id": identity, "attempt": job.get("attempt", 1), "content_rev": revision, "state": "pending",
                   "text": text, "created_at": time.time(), "check_state": check_state(job),
                   "repo": job["repo"], "work_dir": job.get("work_dir", ""), "stage": cj.stage_line(job),
                   "products": job.get("products") or [], "kept_delivery": job.get("kept_delivery") or {}}
        cj._transition(cdir, job["id"], (current["status"],), handoff=handoff)
        return handoff


def _handoff_update(cdir, jid, identity, expected, **changes):
    with cj._LOCK:
        job = owned_job(cdir, jid)
        current = (job or {}).get("handoff") or {}
        if current.get("id") != identity or current.get("state") not in expected:
            return False
        cj._transition(cdir, jid, (job["status"],), handoff={**current, **changes})
        return True


def notify(cdir, job_id, *, engine=None, wake=False):
    from steward_cockpit import maintenance, steward_routes
    job = owned_job(cdir, job_id)
    handoff = (job or {}).get("handoff") or {}
    if handoff.get("state") != "pending" or maintenance.is_active():
        return False
    try:
        eng = engine or steward_routes.get_engine(str(cdir), create=wake)
        if eng is None or cj._norm(eng.dir) != cj._norm(cdir) or getattr(eng, "general", False):
            return False
        if getattr(eng, "job_results_paused", False):
            return False
        if not eng.alive():
            if not wake:
                return False
            ok, why = eng.wake(fresh=False)
            if not ok:
                raise RuntimeError("wake refused: " + str(why))
        # Never enter the engine while holding cj._LOCK (the engine also reads job state).
        # Collection serializes with acceptance, then the record update compares the exact identity.
        with _handoff_lock(cdir, job_id):
            current = (owned_job(cdir, job_id) or {}).get("handoff") or {}
            if current.get("id") != handoff["id"] or current.get("state") != "pending":
                return False
            result = eng.enqueue_job_result(handoff["id"], handoff["text"])
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "control queue rejected the result")
            return _handoff_update(cdir, job_id, handoff["id"], ("pending",), state="queued", queued_at=time.time(), error="")
    except Exception as exc:
        _handoff_update(cdir, job_id, handoff["id"], ("pending",), error=str(exc)[:300], last_try=time.time())
        return False


def retry_pending(cdir, *, engine):
    """Materialize one saved outcome, then retry one notification on the existing tick."""
    jobs = list(cj.read_jobs(cdir).values())
    # Separate passes: a previously pending notification cannot hide a missing
    # result. Old unmarked terminal jobs remain quiet until explicit collection.
    due = [j for j in jobs if (j.get("handoff") or {}).get("state") == "needs_report"]
    if due:
        job = min(due, key=lambda j: (j.get("handoff") or {}).get("last_try", 0))
        materialize(cdir, job["id"])
    pending = [j for j in cj.read_jobs(cdir).values() if (j.get("handoff") or {}).get("state") == "pending"]
    if pending:
        job = min(pending, key=lambda j: (j.get("handoff") or {}).get("last_try", 0))
        return notify(cdir, job["id"], engine=engine, wake=True)
    return False


def materialize(cdir, job_id):
    """Repair a terminal result through the normal report writer, without waking an engine."""
    with _handoff_lock(cdir, job_id):
        job = owned_job(cdir, job_id)
        if not job or job.get("status") in cj.LIVE:
            return None
        current = job.get("handoff") or {}
        if current.get("id"):
            return current
        try:
            return cj._report(cdir, job, notify_result=False)
        except Exception:
            # The normal report writer preserves the obligation and its error.
            # Another tick/collect retries only reporting, never execution.
            return None


def collect(cdir, job_id, handoff_id=None):
    with _handoff_lock(cdir, job_id):
        materialize(cdir, job_id)
        return _collect_saved(cdir, job_id, handoff_id)


def _collect_saved(cdir, job_id, handoff_id):
    with cj._LOCK:
        job = owned_job(cdir, job_id)
        handoff = (job or {}).get("handoff") or {}
        if not handoff.get("id"):
            return {"ok": False, "error": "no durable result yet; inspect this original job"}
        if handoff_id and handoff["id"] != handoff_id:
            return {"ok": False, "error": "this result was superseded; collect the current result", "handoff_id": handoff["id"]}
        _handoff_update(cdir, job_id, handoff["id"], ("pending", "queued"), state="collected", collected_at=time.time())
        current = owned_job(cdir, job_id)
        return {"ok": True, "job": job_id, "handoff": current["handoff"], "kept_delivery": current.get("kept_delivery") or {}}
