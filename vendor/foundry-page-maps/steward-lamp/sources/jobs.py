"""R3 of the steward-responsiveness plan (Ecgberht/planning/steward-responsiveness-2026-10-04, John 2026-10-04: "It is
fine to have the Cave Steward and the Star Steward both hand off to other agents ... but I don't want to have it not
use the best model at the fullest effort for hard problems").

A steward hands real work to a CODE JOB and stays free to talk. A code job is a workbench-terminal engine (the same
bridges, the same latest-model / highest-effort policy as every steward) running in its own git worktree of the
repository that owns the files, given the steward's brief as its first message. When its turn ends the job is
checked (the brief's check command, when one was given), committed on its branch, and landed into the repository
when that is clean; then the steward that commissioned it is woken with the result and reports it to John.

One writer: while a job runs on a repository, the steward does not write there (the engine's tool guard reads
``active_repos``). His "stop" kills the job; a change he asks for is held for the result turn, never piped into the
running job. One coder by default; a swarm only when his brief asks for one (the coder may fan out itself).

Records: ``<steward folder>/.ecgberht/code-jobs.json`` {job_id: {...}}. Never raises to a caller; every failure is a
record field and a line to the steward.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

JOBS_FILE = ".ecgberht/code-jobs.json"
CHECK_TIMEOUT_S = 900
_LOCK = threading.RLock()


def jobs_base():
    """Where the worktrees live: outside every repo and outside C:\\dev, so no scan or reaper meets them."""
    root = os.environ.get("ANCHOR_CODE_JOBS_DIR") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()), "anchor-code-jobs")
    Path(root).mkdir(parents=True, exist_ok=True)
    return Path(root)


def _git(repo, *args, timeout=120):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "", "git %s timed out after %ss" % (args[0] if args else "", timeout)
    except Exception as e:
        return 1, "", "git could not run: %s" % e
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _path(cdir):
    return Path(cdir) / JOBS_FILE


def read_jobs(cdir):
    try:
        d = json.loads(_path(cdir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_job(cdir, job):
    with _LOCK:
        d = read_jobs(cdir)
        d[job["id"]] = job
        p = _path(cdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(p))


LIVE = ("running", "finishing")


def _busy_path():
    return jobs_base() / "busy.json"


def _busy_read():
    try:
        d = json.loads(_busy_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _busy_write(d):
    p = _busy_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def _norm(path):
    return os.path.normcase(str(Path(path).resolve()))


def busy_repos():
    """Every repository a live code job owns, across all stewards: {repo: {"job", "cdir"}} (stale entries dropped)."""
    out = {}
    for repo, info in _busy_read().items():
        j = read_jobs(info.get("cdir", "")).get(info.get("job", ""), {})
        if j.get("status") in LIVE:
            out[repo] = info
    return out


def active_repos(cdir=None):
    """The repositories live code jobs own (all stewards: one writer per repository)."""
    return list(busy_repos())


def inside(path, repo):
    """True when ``path`` is ``repo`` or under it, on a path boundary (C:\\dev\\Anchor never matches C:\\dev\\Anchor-x)."""
    p, r = _norm(path), _norm(repo)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _transition(cdir, job_id, expect, **updates):
    """One locked status change: applies ``updates`` only when the job's status is in ``expect``; returns the job
    after the change, or None when it was not in that state (finish and stop never both win)."""
    with _LOCK:
        d = read_jobs(cdir)
        j = d.get(job_id)
        if not j or j.get("status") not in expect:
            return None
        j.update(updates)
        d[job_id] = j
        p = _path(cdir)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(p))
        if j.get("status") not in LIVE:
            b = _busy_read()
            if b.get(_norm(j["repo"]), {}).get("job") == job_id:
                b.pop(_norm(j["repo"]), None)
                _busy_write(b)
        return dict(j)


def _repo_root(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if code == 0 and out else None


def start(cdir, repo, brief, check="", engine_factory=None, steward=""):
    """Start a code job for the steward at ``cdir``: a worktree of ``repo`` and a coder engine given ``brief``.
    ``engine_factory(worktree) -> engine`` is the seam (steward_routes passes get_engine)."""
    brief = str(brief or "").strip()
    if not brief:
        return {"ok": False, "error": "a code job needs a brief"}
    root = _repo_root(repo or "")
    if root is None:
        return {"ok": False, "error": "not a git repository: %s" % repo}
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = "steward-job-" + job_id
    wt = jobs_base() / job_id
    with _LOCK:      # the check, the worktree and the busy entry: one step, so two stewards never both start
        if _norm(root) in busy_repos():
            return {"ok": False, "error": "a code job is already running on %s; one writer at a time" % root}
        code, base, err = _git(root, "rev-parse", "HEAD")
        if code != 0:
            return {"ok": False, "error": "the repository has no commit to start from: %s" % err}
        code, _, err = _git(root, "worktree", "add", "-b", branch, str(wt), base, timeout=600)
        if code != 0:
            return {"ok": False, "error": "could not make the worktree: %s" % err[:300]}
        job = {"id": job_id, "repo": str(root), "branch": branch, "worktree": str(wt), "base": base, "brief": brief[:8000],
               "check": str(check or "")[:500], "status": "running", "started": time.strftime("%Y-%m-%d %H:%M:%S"),
               "steward_dir": str(cdir), "steward": steward}
        _write_job(cdir, job)
        b = _busy_read()
        b[_norm(root)] = {"job": job_id, "cdir": str(cdir)}
        _busy_write(b)
    # the coder's own folder record: one workbench terminal
    terms = Path(wt) / ".anchor" / "steward-terms.json"
    terms.parent.mkdir(parents=True, exist_ok=True)
    terms.write_text(json.dumps({"1": {"label": "code job " + job_id, "created": job["started"], "archived": False}}), encoding="utf-8")
    _exclude_local(wt)
    try:
        eng = engine_factory(str(wt)) if engine_factory else None
        if eng is None:
            raise RuntimeError("no engine slot for the coder")
        eng.code_job = {"cdir": str(cdir), "id": job_id, "repo": str(root)}
        eng.on_turn_done = lambda result: threading.Thread(target=finish, args=(cdir, job_id, result), name="code-job-" + job_id, daemon=True).start()
        ok, why = eng.wake(fresh=True, seed=coder_brief(job))
        if not ok:
            raise RuntimeError(why)
    except Exception as e:
        j = _transition(cdir, job_id, LIVE, status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"), error="the coder could not start: %s" % e)
        _cleanup(j or job, keep_branch=False)
        return {"ok": False, "error": "the coder could not start: %s" % e, "job": job_id}
    return {"ok": True, "job": job_id, "branch": branch, "worktree": str(wt)}


def _exclude_local(wt):
    """The coder's .anchor/.ecgberht bookkeeping never lands in the repository."""
    try:
        code, gitdir, _ = _git(wt, "rev-parse", "--git-common-dir")
        if code == 0:
            ex = Path(wt, gitdir) if not os.path.isabs(gitdir) else Path(gitdir)
            f = ex / "info" / "exclude"
            f.parent.mkdir(parents=True, exist_ok=True)
            cur = f.read_text(encoding="utf-8") if f.exists() else ""
            add = [x for x in ("/.anchor/", "/.ecgberht/") if x not in cur]
            if add:
                f.write_text(cur.rstrip("\n") + ("\n" if cur else "") + "\n".join(add) + "\n", encoding="utf-8")
    except Exception:
        pass


def coder_brief(job):
    return ("You are a CODE JOB commissioned by John's steward. Work only in this folder, a git worktree of "
            "%s on branch %s. Do the work in the brief below completely, at your best; you may use sub-agents if "
            "the brief asks for a swarm. Do not ask questions back: if something is genuinely John's to decide, "
            "stop and say so in your final message. Do not write plan pages, reports, journals or status files; "
            "edit the code, run the checks that apply, and end with a plain summary of what you changed and how "
            "you checked it. Do not commit; the job commits and lands your work.%s\n\nBRIEF:\n%s") % (
        job["repo"], job["branch"], ("\nThe job will run this check after you finish: " + job["check"]) if job.get("check") else "", job["brief"])


def finish(cdir, job_id, result):
    """The coder's turn ended: check, commit, land when clean, wake the steward with the result. Never raises.
    The job is claimed first (running -> finishing): a stop that already won leaves it alone."""
    job = _transition(cdir, job_id, ("running",), status="finishing", finishing_at=time.time())
    if not job:
        return
    try:
        _finish(cdir, job_id, job, result)
    except Exception as e:      # never leave the repository owned by a finish that died
        j = _transition(cdir, job_id, ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        error="the job's finish failed: %s" % e, land_note="not landed; the work waits on branch %s" % job["branch"])
        if j:
            _report(cdir, j)


def _finish(cdir, job_id, job, result):
    wt, repo = job["worktree"], job["repo"]
    summary = str((result or {}).get("text") or "")[-1500:]
    err = str((result or {}).get("error") or "")
    check_out, check_ok = "", None
    if job.get("check") and not err:
        try:
            r = subprocess.run(job["check"], cwd=wt, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT_S)
            check_ok = r.returncode == 0
            check_out = ((r.stdout or "") + (r.stderr or ""))[-1200:]
        except Exception as e:
            check_ok, check_out = False, "the check did not run: %s" % e
    commit_err = ""
    files = []
    code, _, gerr = _git(wt, "add", "-A", timeout=600)
    if code != 0:
        commit_err = "git add failed: " + gerr[:250]
    if not commit_err:
        code, staged, gerr = _git(wt, "diff", "--cached", "--name-only", timeout=600)
        if code != 0:
            commit_err = "git diff failed: " + gerr[:250]
        elif staged:
            code, out, gerr = _git(wt, "commit", "-q", "-m", "Code job %s for the steward\n\n%s" % (job_id, job["brief"][:600]), timeout=600)
            if code != 0:
                commit_err = "git commit failed: " + (gerr or out)[:250]
    if not commit_err:
        # the change is what the branch holds beyond its base (the coder may have committed itself)
        code, names, gerr = _git(wt, "diff", "--name-only", job["base"], "HEAD", timeout=600)
        if code != 0:
            commit_err = "git diff failed: " + gerr[:250]
        else:
            files = [n for n in names.splitlines() if n.strip()]
    landed, land_note = False, ""
    if commit_err:
        land_note = "not landed: the commit failed (%s); the worktree is kept at %s" % (commit_err, wt)
    elif not files:
        land_note = "nothing changed"
    elif err:
        land_note = "not landed: the coder's turn ended in an error; the work waits on branch %s" % job["branch"]
    elif check_ok is False:
        land_note = "not landed: the check failed; the work waits on branch %s" % job["branch"]
    else:
        landed, land_note = land(job, files)
    done = _transition(cdir, job_id, ("finishing",), status="failed" if (err or commit_err) else "done",
                       finished=time.strftime("%Y-%m-%d %H:%M:%S"), summary=summary, error=err or commit_err,
                       check_ok=check_ok, check_output=check_out, files=files, landed=landed, land_note=land_note)
    if done is None:
        return
    if not commit_err:
        _cleanup(done, keep_branch=not (landed or not files))
    _report(cdir, done)


def land(job, files):
    """A2 (PROPOSAL v0.3): bring the job's branch up to the repository's current HEAD inside the job's OWN worktree
    (never in the shared tree), re-run its check there, then land only its own files with git_safety.land, which
    refuses any file someone else has changed or staged and commits by path. Returns (landed, note)."""
    import git_safety as _gs
    repo, wt = job["repo"], job["worktree"]
    with _gs.repo_lock(repo, wait_s=300, who="code job " + job["id"]) as held:
        if not held:
            return False, "not landed: the repository's commit lock is busy; the work waits on branch %s" % job["branch"]
        return _land_under_lock(job, _gs)


def _land_under_lock(job, _gs):
    repo, wt = job["repo"], job["worktree"]
    code, head, err = _git(repo, "rev-parse", "HEAD")
    if code != 0:
        return False, "not landed: could not read %s HEAD (%s)" % (repo, err[:120])
    code, out, err = _git(wt, "merge", "--no-edit", head, timeout=600)       # the job's own worktree: safe
    if code != 0:
        _git(wt, "merge", "--abort")
        return False, "not landed: the work conflicts with newer changes in %s; it waits on branch %s" % (repo, job["branch"])
    if job.get("check"):
        try:
            r = subprocess.run(job["check"], cwd=wt, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT_S)
            if r.returncode != 0:
                return False, "not landed: the check failed after bringing in newer changes; the work waits on branch %s" % job["branch"]
        except Exception as e:
            return False, "not landed: the check could not run after integration (%s)" % e
    code, src, _ = _git(wt, "rev-parse", "HEAD")
    code2, names, _ = _git(wt, "diff", "--name-only", head, src)
    if code != 0 or code2 != 0:
        return False, "not landed: could not read the integrated change"
    land_files = [n for n in names.splitlines() if n.strip()]
    if not land_files:
        return False, "nothing changed beyond what %s already has" % repo
    return _gs.land_locked(repo, src, land_files, "Code job %s for the steward\n\n%s" % (job["id"], job["brief"][:600]),
                           who="code job " + job["id"], expect_head=head)


def _cleanup(job, keep_branch=True):
    """The worktree goes; the branch goes only when there is nothing on it worth keeping."""
    try:
        _git(job["repo"], "worktree", "remove", "--force", job["worktree"], timeout=300)
        if not keep_branch:
            _git(job["repo"], "branch", "-D", job["branch"])
    except Exception:
        pass


def live_note(job):
    """Landed is not live (his word, 2026-10-05: a tile repair 'landed with all 20 checks passing' and nothing on his
    screen changed - the running Anchor still had the old code and his page the old stylesheet). For a job landed in the
    repository the Anchor service runs from, the one sentence the steward must carry: it waits for a restart."""
    if not job.get("landed"):
        return ""
    try:
        here = Path(__file__).resolve().parents[1]
        if Path(str(job.get("repo") or "")).resolve() != here:
            return ""
    except Exception:
        return ""
    return ("NOT LIVE YET: this landed in Anchor's repository, but John's screen runs the build that was started before "
            "it - the change shows only after Anchor restarts (an Anchor restart is John's word, or his standing "
            "'restart when idle'). Tell him it is landed and waits for a restart; never call it installed, live or done "
            "on his screen until the running build carries it.")


def _report(cdir, job):
    """Wake the steward that commissioned the job with its result (a control turn, not his words)."""
    lines = ["(code job %s finished - not John) Status: %s." % (job["id"], job["status"])]
    if job.get("error"):
        lines.append("Error: " + job["error"][:300])
    if job.get("files"):
        lines.append("Files: " + ", ".join(job["files"][:20]) + (" and %d more" % (len(job["files"]) - 20) if len(job["files"]) > 20 else ""))
    if job.get("check"):
        lines.append("Check `%s`: %s." % (job["check"], "passed" if job.get("check_ok") else "FAILED") + ((" Output tail: " + job["check_output"][-400:]) if job.get("check_ok") is False else ""))
    lines.append("Landing: " + job.get("land_note", ""))
    live = live_note(job)
    if live:
        lines.append(live)
    lines.append("The coder's summary: " + (job.get("summary") or "(none)"))
    lines.append("Tell John the result in two or three plain sentences; ask him only what is genuinely his to decide.")
    try:
        from steward_cockpit import steward_routes as _sr
        eng = _sr.get_engine(str(cdir))
        if eng is not None:
            if not eng.alive():
                eng.wake(fresh=False)
            eng.say("\n".join(lines), human=False)
    except Exception:
        pass


def stop(cdir, job_id=None, engine_lookup=None):
    """His "stop": kill the running job (the newest when no id); its work so far stays on its branch."""
    jobs = [j for j in read_jobs(cdir).values() if j.get("status") in LIVE and (not job_id or j["id"] == job_id)]
    if not jobs:
        return {"ok": False, "error": "no code job is running"}
    job = sorted(jobs, key=lambda j: j["started"])[-1]
    if job.get("status") == "finishing":
        if time.time() - float(job.get("finishing_at") or 0) < CHECK_TIMEOUT_S + 900:
            return {"ok": False, "error": "the code job is already finishing; its result is on the way"}
        _transition(cdir, job["id"], ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                    error="the job's finish never completed", land_note="released by stop; the work waits on branch %s" % job["branch"])
        return {"ok": True, "job": job["id"], "branch": job["branch"], "released": True}
    stopped = _transition(cdir, job["id"], ("running",), status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                          land_note="stopped by John; nothing landed; the work so far stays on branch %s" % job["branch"])
    if stopped is None:
        return {"ok": False, "error": "the code job is already finishing; its result is on the way"}
    try:
        eng = engine_lookup(job["worktree"]) if engine_lookup else None
        if eng is not None:
            eng.on_turn_done = None
            eng.stop()
    except Exception:
        pass
    try:
        _git(job["worktree"], "add", "-A")
        _git(job["worktree"], "commit", "-q", "-m", "Code job %s stopped by John (unfinished)" % job["id"])
        _git(job["repo"], "worktree", "remove", "--force", job["worktree"], timeout=300)
    except Exception:
        pass
    return {"ok": True, "job": job["id"], "branch": job["branch"]}
