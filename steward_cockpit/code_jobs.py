"""R3 of the steward-responsiveness plan (Ecgberht/planning/steward-responsiveness-2026-10-04, John 2026-10-04: "It is
fine to have the Cave Steward and the Star Steward both hand off to other agents ... but I don't want to have it not
use the best model at the fullest effort for hard problems").

A steward hands real work to a CODE JOB and stays free to talk. A code job is a workbench-terminal engine (the same
bridges, the same latest-model / highest-effort policy as every steward) running in its own git worktree of the
repository that owns the files, given the steward's brief as its first message. When its turn ends the job is
checked (the brief's check command, when one was given), committed on its branch, and landed into the repository
when that is clean; then the steward that commissioned it is woken with the result and reports it to John.

The steward does not write into a repository while a job runs there (the engine's tool guard reads
``active_repos``). His "stop" kills the job; a change he asks for is held for the result turn, never piped into the
running job. One coder by default; a swarm only when his brief asks for one (the coder may fan out itself).

Records: ``<steward folder>/.ecgberht/code-jobs.json`` {job_id: {...}}. Never raises to a caller; every failure is a
record field and a line to the steward.

Execution minimum item 3 (PROPOSAL v1.1, 2026-10-07) - one commit: preservation, safe checks, the Foreman/Crucible
hold, and the review gate.
- HOLD: Crucible never starts from Anchor's managed entries until John lifts the hold (ANCHOR_FOREMAN_CRUCIBLE_HOLD=0).
  Foreman starts ONLY as a code job's worker (2026-10-09): in the job's worktree, through this same finish.
- CHECKS: an argument list, or the full command text run from a temp script - never cut, never re-quoted - in the
  job's OWN tree; the live tree is touched only by the landing itself.
- MANIFEST: only the paths the coder's tools wrote are staged and placed (no ``git add -A``); any other changed path
  blocks the landing and the worktree is KEPT with everything in it, listed; foreman.config.json never lands; after
  a landing every placed file is verified in the repository before the worktree goes.
- REVIEW GATE: ``land`` refuses unless a review record (tools/steward_review.mjs, the trio's runAgent review role)
  names a family other than the author's AND the exact candidate tree; an error, the author's own family, a missing
  family or a changed tree keeps the worktree and says why. A change after review (integrating newer commits) gets a
  review of that delta only.
- SEATS: the coder's family is the job's choice, else the dashboard's Coder seat; a family known to be exhausted is
  not called again (the other family may run); model preferences are never written.
"""
from __future__ import annotations

import json
import shlex
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from pathlib import Path

JOBS_FILE = ".ecgberht/code-jobs.json"
_LOCK = threading.RLock()


def jobs_base():
    """Where the worktrees live: outside every repository, beside the Anchor checkout under C:\\dev (backed up)."""
    import paths as _paths      # under C:\dev, beside the checkout (John, 2026-10-08: C:\dev is backed up)
    root = _paths.code_jobs_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _git(repo, *args, timeout=120):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "", "git %s timed out after %ss" % (args[0] if args else "", timeout)
    except Exception as e:
        return 1, "", "git could not run: %s" % e
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _git_raw(repo, *args, timeout=600):
    """git with its stdout exactly as written (no strip): porcelain status columns start with a space."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except Exception as e:
        return 1, "", str(e)
    return r.returncode, r.stdout or "", (r.stderr or "").strip()


def porcelain_paths(repo):
    """Every changed or untracked path of ``repo`` (no renames), parsed from NUL-delimited porcelain v1; None on
    failure."""
    code, out, _ = _git_raw(repo, "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all",
                            "--no-renames")
    if code != 0:
        return None
    return [rec[3:] for rec in out.split("\0") if len(rec) > 3]


def _replace(src, dst):
    """os.replace, retried briefly: on Windows a reader holding the record open (a page polling the jobs) makes the
    replace fail for a moment (WinError 5); a record write must not fail a job for that."""
    for attempt in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def _path(cdir):
    return Path(cdir) / JOBS_FILE


def read_jobs(cdir, *, strict=False):
    # Share the writer's lock: Windows replacement can briefly deny an unsynchronized read.
    # A writer must never interpret an unreadable existing registry as an empty one.
    with _LOCK:
        try:
            d = json.loads(_path(cdir).read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("the code-job registry is not an object")
            return d
        except FileNotFoundError:
            return {}
        except Exception:
            if strict:
                raise
            return {}


def _write_job(cdir, job):
    with _LOCK:
        d = read_jobs(cdir, strict=True)
        d[job["id"]] = job
        p = _path(cdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        _replace(str(tmp), str(p))


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
    _replace(str(tmp), str(p))


def _norm(path):
    return os.path.normcase(str(Path(path).resolve()))


def busy_repos():
    """Every repository a live code job works on, across all stewards: {repo: {"job", "cdir"}} - one entry per
    repository even when several jobs run there (stale entries dropped; a Foreman lost to a restart reconciled)."""
    out = {}
    _prune_finished()
    from steward_cockpit import code_job_handoff as _ch
    for key, info in _busy_read().items():
        repo = info.get("repo") or key           # keyed by job since 2026-10-09; older entries by repository
        j = read_jobs(info.get("cdir", "")).get(info.get("job", ""), {})
        if j.get("worker") == "foreman":
            j = reconcile_foreman(info.get("cdir", ""), j)
        if j.get("status") == "finishing" and not j.get("stop_requested") and _ch.orphaned_finalizer(j):
            continue
        if j.get("status") == "running" and _ch.observe(j).get("state") == "dead":
            continue
        if j.get("status") in LIVE:
            out[repo] = info
    return out


def _prune_finished():
    """Drop busy entries whose job record READS as finished (fcj review r7: a crash between the record and the ledger
    write left one that blocked drained restarts for ever). An entry whose record cannot be read is kept."""
    with _LOCK:
        b = _busy_read()
        gone = []
        for key, info in b.items():
            if not isinstance(info, dict):
                continue
            try:
                d = json.loads(_path(info.get("cdir", "")).read_text(encoding="utf-8"))
            except Exception:
                continue                          # unreadable: kept, conservatively
            j = d.get(info.get("job", "")) if isinstance(d, dict) else None
            if isinstance(j, dict) and j.get("status") and j.get("status") not in LIVE:
                gone.append(key)
        if gone:
            for k in gone:
                b.pop(k, None)
            _busy_write(b)


def active_repos(cdir=None):
    """The repositories live code jobs work on (all stewards); the stewards do not write there meanwhile. Several jobs
    may share one (John 2026-10-09)."""
    return list(busy_repos())


def inside(path, repo):
    """True when ``path`` is ``repo`` or under it, on a path boundary (C:\\dev\\Anchor never matches C:\\dev\\Anchor-x)."""
    p, r = _norm(path), _norm(repo)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _transition(cdir, job_id, expect, *, expect_attempt=None, **updates):
    """One locked status change: applies ``updates`` only when the job's status is in ``expect``; returns the job
    after the change, or None when it was not in that state (finish and stop never both win)."""
    with _LOCK:
        d = read_jobs(cdir, strict=True)
        j = d.get(job_id)
        if not j or j.get("status") not in expect:
            return None
        if expect_attempt is not None and j.get("attempt", 1) != expect_attempt:
            return None
        previous_status, previous_phase = j.get("status"), j.get("phase")
        stop_request, stop_actor = j.get("stop_requested"), j.get("stop_requested_by")
        j.update(updates)
        if previous_status in LIVE and j.get("status") not in LIVE:
            # Stop wins at the same atomic boundary as the outcome, including a
            # request arriving after the controller assembled its local fields.
            if previous_status == "finishing" and stop_request and not (j.get("placed") or j.get("landed")):
                j.update(status="stopped", stopped_by=stop_actor or "unknown", stop_requested=stop_request,
                         stop_requested_by=stop_actor, kept_worktree=j.get("worktree", ""),
                         land_note="stopped by %s during %s; saved work is kept at %s" % (
                             stop_actor or "unknown", previous_phase or "finishing", j.get("worktree", "")))
                command = j.get("command") or {}
                if command.get("cancelled"):
                    if command.get("phase") == "checking":
                        if j.get("check_ok") is True:
                            if j.get("integration_check_ok") is not True:
                                j["integration_check_ok"] = None
                        else:
                            j["check_ok"] = None
                    elif command.get("phase") == "reviewing":
                        if j.get("delta_review") is not None:
                            j["delta_review"] = None
                        else:
                            j["review"] = None
            # A crash before _report must leave a durable obligation. Legacy
            # terminal rows are collected explicitly, not broadcast at boot.
            if not (j.get("handoff") or {}).get("id"):
                j["handoff"] = {"state": "needs_report", "attempt": j.get("attempt", 1)}
        d[job_id] = j
        p = _path(cdir)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        _replace(str(tmp), str(p))
        if j.get("status") not in LIVE:
            b = _busy_read()
            mine = [k for k, v in b.items() if isinstance(v, dict) and v.get("job") == job_id]
            for k in mine:
                b.pop(k, None)
            if mine:
                _busy_write(b)
        return dict(j)


def _repo_root(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if code == 0 and out else None


def destination_error(repo):
    """A product belongs to its main checkout, never to another job's linked worktree."""
    import paths
    if not repo or ":" in str(repo)[2:]:
        return "invalid repository destination"
    root = Path(repo).resolve()
    if any(inside(root, base) for base in (paths.code_jobs_dir(), paths.legacy_code_jobs_dir())):
        return "destination is a temporary code-job worktree; inspect/collect or recover the original job %s in its commissioning effort" % root.name
    c, gd, _ = _git(root, "rev-parse", "--absolute-git-dir")
    c2, common, _ = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if c or c2:
        return "destination repository identity could not be verified"
    if _norm(gd) != _norm(common):
        return "destination is a linked worktree; use its owning main checkout, or recover the original job in its commissioning effort"
    return ""


def integration_required_error(job):
    """Why a job may NOT land directly into its repository: an INSTALLED skill repository (2026-10-10: C:\\dev\\trio,
    C:\\dev\\Skill Foundry, anchor_next.is_installed_repo) takes a landing only on its own anchor-next, in the lander's
    checkout named at the job's start as ``land_to``. A record without one - an older job, a hand-made one - is REFUSED,
    never redirected, so neither a finish nor a recovery can install skill code by landing it. "" when the landing may
    proceed. Fails closed when the question cannot be answered. John 2026-10-10: nothing lands on Anchor's own code from
    a cockpit - an older job's work there is kept for a look, never landed or recovered."""
    repo = job.get("repo") or ""
    try:
        import anchor_next
        served = anchor_next.is_served_repo(repo)
    except Exception:
        served = True                                 # unknown: the careful answer
    if served:
        return ("Anchor's own code is never changed from a cockpit (John's rule); this job's work is kept for a look "
                "and John makes the change from outside Anchor")
    if job.get("land_to"):
        return ""
    if job.get("installed_repo"):                     # durable: a classification made at the start is never un-learned
        return ("%s was classified an installed skill repository when this job started, and the job names no "
                "integration checkout (land_to): a direct landing would install skill code by a model pass. Keep this "
                "job's work for a look; a NEW job there lands on anchor-next and waits for a human activation" % repo)
    try:
        import anchor_next
        installed = anchor_next.is_installed_repo(repo)
    except Exception as e:                            # discovery cannot be trusted: refuse, never guess
        return ("could not tell whether %s is an installed skill repository (%s): a direct landing is refused until "
                "the installed-skill sources can be read; the work is kept" % (repo, e))
    if installed:
        return ("%s is an installed skill repository and this job names no integration checkout (land_to): a direct "
                "landing would install skill code by a model pass. Keep this job's work for a look; a NEW job there "
                "lands on anchor-next and waits for a human activation" % repo)
    return ""


def work_scope(root, requested, work_dir, outputs):
    """Omitted scope derives from --repo; explicit empty scope preserves root-wide jobs."""
    try:
        if work_dir is None:
            scope = Path(requested).resolve().relative_to(Path(root).resolve()).as_posix()
        else:
            scope = str(work_dir).replace(chr(92), "/").strip()
        scope = "" if scope in ("", ".") else scope
        if scope:
            _output_path(root, scope)
        why = scope_error({"work_dir": scope}, root, outputs)
        return (scope, why)
    except (OSError, ValueError) as exc:
        return "", "invalid work directory: %s" % exc


def scope_error(job, tree, paths):
    name = job.get("work_dir") or "(repository)"
    try:
        root = Path(tree).resolve()
        scope = _output_path(root, job["work_dir"]) if job.get("work_dir") else root
        for name in paths:
            if not _runtime(name):
                _output_path(root, name).relative_to(scope)
        return ""
    except (OSError, ValueError) as exc:
        return "path outside the job's work directory or unsafe path (%s): %s" % (name, exc)


def phase(job, value, **fields):
    """Controller observation, written at the actual transition, not a guessed heartbeat."""
    stamp = time.time()
    out = _transition(job["steward_dir"], job["id"], LIVE, expect_attempt=job.get("attempt", 1), phase=value, phase_at=stamp, **fields)
    if out:
        job.update(phase=value, phase_at=stamp, **fields)
    return out


# ── The Foreman/Crucible hold (execution minimum item 3) ────────────────────────────────────────────────────────────
def foreman_crucible_held():
    """True while Crucible (and the job runner's plan/build lanes) may not start from Anchor's managed entries (John's
    binding, 2026-10-07). Foreman is not held by it: it runs only as a code job's worker, inside the protected
    lifecycle (own worktree, a passing check, reviewed landing) - the path the final review of 2026-10-10 asked for - and
    never as a skill job. ANCHOR_FOREMAN_CRUCIBLE_HOLD=0 lifts the rest by hand."""
    return os.environ.get("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1").strip() != "0"


HOLD_REASON = ("Crucible, and Foreman outside a code job, are on hold in Anchor (John, 2026-10-07); Foreman runs as a "
               "code job (steward_code_job.py start --worker foreman), and Anchor did not start this")
FOREMAN_AS_SKILL = ("Foreman runs only as a code job (its own worktree, a passing check, another family's "
                    "review, the safe landing): python C:/dev/Anchor/tools/steward_code_job.py start --worker foreman "
                    "--repo <repo> --brief-file <brief> --check \"<test command>\" [--plan-file <plan>]")


# ── Foreman as a code job's worker (John 2026-10-09: "route Foreman through the code-job path") ─────────────────────
# The final review of the night of 2026-10-10 held Foreman because, started as a skill job, it wrote the project
# directly. Here it builds INSIDE the job's worktree, exactly where a coder would, and its result goes through the same
# finish: the job's own check, a review by a family that wrote none of it, and the locked, verified landing. Foreman
# runs without --git (the job commits); its documents and foreman.config.json are Anchor's, written in the worktree and
# never landed. Its sub-agents are not held to the worktree by a fence; no code job runs on Anchor's own code, and a
# write into the source repository blocks the landing.
FOREMAN_RUN_LIVE = Path(os.environ.get("ANCHOR_FOREMAN_RUN_LIVE") or
                        (Path(os.environ.get("ANCHOR_TRIO_ROOT") or r"C:\dev\trio") / "foreman" / "bin" / "run-live.mjs"))
FOREMAN_PROFILES = ("slim", "standard")
FOREMAN_DIR = ".foreman-job"
_FOREMAN_PROCS = {}
_FOREMAN_STOPPING = set()     # job ids Stop is ending: their Foreman never launches, and its end never finishes them
_DRIVER_FAMILY = {"claude": "claude", "chatgpt-cli": "chatgpt", "chatgpt-session": "chatgpt", "codex": "chatgpt", "openai": "chatgpt",
                  "grok-cli": "grok", "grok": "grok", "gemini-cli": "gemini", "gemini": "gemini"}


def foreman_code_jobs_on():
    """Foreman code jobs are on by default; ANCHOR_FOREMAN_CODE_JOBS=0 turns them off."""
    return os.environ.get("ANCHOR_FOREMAN_CODE_JOBS", "1").strip() != "0"


_SHELL_META = re.compile(r'[|&<>^%!()"\s]')
GATE_SCRIPT = FOREMAN_DIR + "/run_check.py"


def check_text(check):
    """The check as one command line - Foreman's plan declares its gate as text, and Foreman runs it in a SHELL. An
    argument list whose arguments a shell would read differently (fcj review r7: a | in a test pattern) runs through
    Anchor's own wrapper in .foreman-job, which executes the exact list with no shell; a plain list (pytest ...) stays
    readable, so Foreman still recognizes its test runner."""
    if not isinstance(check, list):
        return str(check or "").strip()
    if any(_SHELL_META.search(a) or not a for a in check):
        return subprocess.list2cmdline([sys.executable, GATE_SCRIPT])
    return subprocess.list2cmdline(check)


GATE_PYTEST_ADDOPTS = "-vv"


def _write_gate(job, wt):
    """The wrapper check_text names, when it does (never landed: .foreman-job is Anchor's). It runs the job's exact
    argument list with no shell. Behind it Foreman cannot see a pytest to make verbose, and its GREEN needs a line per
    test - so the wrapper asks pytest itself, through pytest's own PYTEST_ADDOPTS (fcj reviews r8-r10: no guessing
    from the arguments; any pytest the check reaches - directly, through python options, through make - reads it, and
    no other program does). -vv outweighs one -q. The job's own final check runs exactly as given, without it."""
    if isinstance(job.get("check"), list):
        (Path(wt) / FOREMAN_DIR / "run_check.json").write_text(json.dumps(job["check"]), encoding="utf-8")
        (Path(wt) / GATE_SCRIPT).write_text(
            "import json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "argv = json.loads((Path(__file__).parent / 'run_check.json').read_text(encoding='utf-8'))\n"
            "env = dict(os.environ)\n"
            "env['PYTEST_ADDOPTS'] = (env.get('PYTEST_ADDOPTS', '') + ' %s').strip()\n"
            "sys.exit(subprocess.run(argv, shell=False, env=env).returncode)\n" % GATE_PYTEST_ADDOPTS,
            encoding="utf-8")


def foreman_docs(job, plan_text=""):
    """(description, plan, execution log): Foreman's three documents. A plan John approved is used as written (its
    test command is the job's check unless it names one); without one, the brief is a single wave gated by the check."""
    check = check_text(job["check"])
    title = next((ln.strip().lstrip("#").strip() for ln in job["brief"].splitlines() if ln.strip()), "the change")[:120]
    description = "# Code job %s - description\n\n%s\n" % (job["id"], job["brief"])
    description += "\nOwning repository: %s. Artifact work directory: %s. Commands run at the worktree root; output paths are repository-relative. Change only this scope.\n" % (
        job.get("repo", ""), job.get("work_dir") or "repository root (root-wide)")
    if plan_text.strip():
        plan = plan_text if re.search(r"(?im)^\s*(test[-_ ]?command|build[-_ ]?and[-_ ]?test|gate[-_ ]?command)\s*[:=]",
                                      plan_text) else "test-command: `%s`\n\n%s" % (check, plan_text)
    else:
        brief = "\n".join(ln.lstrip("#").strip() if ln.lstrip().startswith("#") else ln for ln in job["brief"].splitlines())
        plan = ("# Code job %s - Implementation Plan\n\n**North Star:** %s\n\ntest-command: `%s`\n\n"
                "## Wave 1 - %s\n\n%s\n\nDone when: `%s` passes and the change is reached by a test.\n") % (
            job["id"], title, check, title, brief, check)
    return description, plan, "# Code job %s - execution log\n" % job["id"]


def foreman_plan_ok(plan_text):
    """'' when a plan has the wave structure Foreman needs, else why not."""
    if plan_text and not re.search(r"(?m)^##\s+Wave\s+\d+", plan_text):
        return "the plan has no '## Wave N' sections, so Foreman cannot build it"
    return ""


FOREMAN_WRITER = "claude"


def foreman_settings(job):
    """(settings dir, None) or (None, why). fcj review r2: Foreman's writing seats are pinned to Claude for the whole
    run - it reads a PRIVATE copy of the dashboard settings (ANCHOR_DATA_DIR) whose Coder seat and terminal are Claude,
    so its execute and fix seats take the Claude transport (no failover, no per-call reload) and a change on the
    dashboard mid-run cannot move them. The author is therefore Claude by construction; the landing reviewer is the
    dashboard's Reviewer seat, which must be another family. The dashboard's own settings are only read."""
    try:
        import anchor_settings
        s = dict(anchor_settings.get_launch_settings())
    except Exception as e:
        return None, "the dashboard settings cannot be read (%s)" % e
    if str(s.get("review_family") or "").lower() == FOREMAN_WRITER:
        return None, ("the Reviewer seat is Claude - the family Foreman writes with - so nothing it built could be "
                      "reviewed by another family; choose another Reviewer seat")
    s.update(coding_family=FOREMAN_WRITER, default_cli=FOREMAN_WRITER)
    d = jobs_base() / "checks" / ("%s-foreman-settings" % job["id"])
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    except OSError as e:
        return None, "Foreman's settings could not be written (%s)" % e
    return d, None


def _note_stuck(cdir, jid, why):
    """Best effort (fcj review r6): the note is a diagnosis; failing to write it never changes what is kept."""
    try:
        _transition(cdir, jid, ("running",), stuck=why)
    except Exception:
        pass


class _Uncontained(Exception):
    """A Foreman process that may be running outside its containment: the run is kept so it stays counted and Stop
    can still end it (fcj review r5)."""

    def __init__(self, run, why):
        super().__init__(why)
        self.run = run


class _ForemanStuck(Exception):
    """Foreman's start failed and its process could not be seen to end: the job stays running and registered."""


class _ForemanRan(Exception):
    """Foreman began and its start failed afterwards; it was ended and seen gone - its worktree is kept, not removed."""


class _Starting:
    """Foreman's place in _FOREMAN_PROCS from the moment its job is recorded until it is launched (fcj review r2:
    registered atomically with the running record, so a reconcile never mistakes a launch for a lost Foreman)."""
    pid = None

    def poll(self):
        return None


class _Run:
    """A launched Foreman: its process, and the kill-on-close Windows Job Object every process it starts belongs to.
    Anchor holds the only handle, so when Anchor's process ends - a restart, a crash - Windows ends the whole tree."""

    def __init__(self, proc, wjob):
        self.proc, self.wjob, self.pid = proc, wjob, proc.pid
        self._end_lock, self.ended = threading.Lock(), False

    def poll(self):
        return self.proc.poll()

    def end(self, wait_s=60):
        """True once the whole tree is SEEN gone (the job empty and the root reaped). Stop and Foreman's own wait may
        both ask: one ends it, the other sees it ended (the handle is closed only once, after it is seen empty)."""
        with self._end_lock:
            if self.ended:
                return True
            self.ended = self._end(wait_s)
            return self.ended

    def _end(self, wait_s):
        if self.wjob is not None and not self.wjob.assigned:      # never contained: end the process itself
            try:
                self.proc.kill()
                self.proc.wait(timeout=wait_s)
                self.wjob.close()
                return True
            except Exception:
                return False
        if self.wjob is not None:
            if not self.wjob.terminate_verified(self.proc, timeout_seconds=wait_s):
                return False
            self.wjob.close()
            return True
        try:                                            # elsewhere: the process group (Windows without a Job: itself)
            if os.name == "nt":
                self.proc.kill()
            else:
                import signal
                os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=wait_s)
            return True
        except Exception:
            return False


def _popen_contained(argv, cwd, env, out):
    """Start ``argv`` suspended, place it in a verified kill-on-close Job Object, then let it run (Windows); a process
    group elsewhere. Never returns a process that runs outside its containment. Accepted residual (fcj review r6,
    disclosed to John): if Anchor itself dies in the instant between the suspended start and the assignment, the
    suspended process is left behind unaccounted - it never runs (only Anchor would resume it), so it cannot write."""
    env = {k: v for k, v in env.items() if k != "ANCHOR_TOKEN"}   # a job's commands never carry Anchor's key
    if os.name != "nt":
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
        return _Run(proc, None)
    from codex_adapter import _WindowsJob       # the containment Anchor's ChatGPT coder already uses
    wjob = _WindowsJob()
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                                creationflags=_WindowsJob.CREATE_SUSPENDED | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except BaseException:
        wjob.close()
        raise
    try:
        if not wjob.assign_and_resume(proc):
            raise OSError("Foreman was not resumed")
    except BaseException as e:
        if not wjob.abort_suspended(proc):            # it may run: never dropped - the caller keeps it accounted for
            raise _Uncontained(_Run(proc, wjob), "Foreman could not be contained (%s), and its end could not be seen "
                               "(pid %s)" % (e, proc.pid))
        wjob.close()
        raise
    return _Run(proc, wjob)


def end_foreman(job, wait_s=60):
    """(ended, why): end this job's Foreman - every process it started - and SEE it gone before anything is released.
    A Foreman not yet launched is told not to launch; one that is not in this Anchor's hands cannot be running (its
    Job Object died with the Anchor process that held it)."""
    jid = job["id"]
    with _LOCK:
        _FOREMAN_STOPPING.add(jid)
        run = _FOREMAN_PROCS.get(jid)
        if isinstance(run, _Starting):                  # never launched, and now it never will
            _FOREMAN_PROCS.pop(jid, None)
    if not isinstance(run, _Run):
        return True, ""
    if run.end(wait_s):
        return True, ""
    return False, "Foreman did not end when asked (pid %s); it keeps its claim - try Stop again" % run.pid


def reconcile_foreman(cdir, job):
    """A Foreman job marked running that this Anchor process does not hold was started by an Anchor that has since
    ended - and its Job Object took every Foreman process with it. The job is marked interrupted; its work is kept."""
    if job.get("worker") != "foreman" or job.get("status") != "running":
        return job
    with _LOCK:
        if job["id"] in _FOREMAN_PROCS:
            return job
        done = _transition(cdir, job["id"], ("running",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                           error="interrupted: Anchor restarted while Foreman ran (Foreman ended with it)",
                           kept_worktree=job["worktree"],
                           land_note="not landed: Anchor restarted while Foreman ran; the work is kept at %s" % job["worktree"])
    if done:
        _remove_foreman_config(job["worktree"])
    return done or job


def candidate_base(job):
    """The job's own delta after integration; its original base remains the audit boundary."""
    return job.get("integrated_base") or job["base"]


def foreman_manifest(job):
    """Foreman's seats keep no per-file write record, so its manifest is its whole change in its own worktree (minus
    runtime records and what never lands) - and every NEW file is named to the landing reviewer (review_note), who
    blocks a byproduct of running the tests (fcj r2, his call 2026-10-09: no pre-run of the check)."""
    return [p for p in (changed_paths(job["worktree"], candidate_base(job)) or []) if not never_lands(p) and not _runtime(p)]


REVIEW_BRIEF_READ = 16000   # tools/steward_review.mjs reads this much of the brief file; a longer one is refused


def added_files(tree, base, head):
    """Every path the candidate ``head`` ADDS to ``base`` (a committed candidate: what was untracked or staged is in
    it), or None when git cannot say."""
    code, out, _ = _git_raw(tree, "-c", "core.quotepath=false", "diff", "--no-renames", "--diff-filter=A",
                            "--name-only", "-z", base, head, timeout=600)
    return sorted(p for p in out.split("\0") if p.strip()) if code == 0 else None


def foreman_review_note(new):
    """What the landing reviewer must be told, before the brief: Foreman keeps no per-file write record, so every
    new file is named for the reviewer to block a byproduct (John's call, 2026-10-09)."""
    return ("FOREMAN BUILT THIS (several sub-agents), so there is no per-file write record: every file in the diff "
            "changed in its worktree. NEW files (added since the job's base): %s. "
            "Check each new file is intended work (source, test, document), not a byproduct of running the tests or "
            "the build (a report, a cache, a log, an output); a byproduct that would land is a MAJOR finding."
            ) % (", ".join(new) or "none")


def _remove_foreman_config(wt):
    try:
        (Path(wt) / "foreman.config.json").unlink()   # Anchor's own file, never the project's
    except OSError:
        pass


def _start_foreman(cdir, job, wt, plan_text, profile, settings_dir):
    """Write Foreman's documents (never landed), launch Foreman contained in the worktree (unless Stop came first),
    and finish the job when it ends. Raises when it cannot launch (start() records that)."""
    jid = job["id"]
    d = Path(wt) / FOREMAN_DIR
    d.mkdir(parents=True, exist_ok=True)
    desc, plan, log = foreman_docs(job, plan_text)
    _write_gate(job, wt)
    (d / "DESCRIPTION.md").write_text(desc, encoding="utf-8")
    (d / "IMPLEMENTATION-PLAN.md").write_text(plan, encoding="utf-8")
    (d / "EXECUTION-LOG.md").write_text(log, encoding="utf-8")
    (Path(wt) / "foreman.config.json").write_text(json.dumps({"docs": {
        "description": FOREMAN_DIR + "/DESCRIPTION.md", "plan": FOREMAN_DIR + "/IMPLEMENTATION-PLAN.md",
        "execution_log": FOREMAN_DIR + "/EXECUTION-LOG.md"}}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TRIO_DRIVER_", "TRIO_MODEL_", "CLAUDE_MODEL_"))}
    env.pop("ANTHROPIC_API_KEY", None)          # subscription billing, as every skill launcher does
    env.update(CRUCIBLE_AGENT_LIVE="1", FOREMAN_PROFILE=profile, ANCHOR_DATA_DIR=str(settings_dir))
    out = open(d / "foreman-run.log", "w", encoding="utf-8")
    try:
        with _LOCK:                                 # Stop and the launch never cross: one sees the other
            cur = read_jobs(cdir).get(jid) or {}
            if jid in _FOREMAN_STOPPING or cur.get("status") != "running":
                out.close()
                _remove_foreman_config(wt)
                _FOREMAN_PROCS.pop(jid, None)
                return
            try:
                run = _popen_contained(["node", str(FOREMAN_RUN_LIVE), str(wt), "--profile", profile], str(wt), env, out)
            except _Uncontained as u:
                _FOREMAN_PROCS[jid] = u.run              # still counted by the restart check; Stop ends it
                _note_stuck(cdir, jid, str(u) + "; Stop ends it and releases the job")
                raise _ForemanStuck(str(u))
            _FOREMAN_PROCS[jid] = run
    except _ForemanStuck:
        raise                                       # out stays open: the process may still write to it
    except BaseException:
        out.close()
        raise
    # fcj review r3: from here Foreman runs - nothing below may abandon it. A failure ends it and SEES it gone before
    # start() records the failure; if it cannot be seen gone, the job keeps running and registered (its claim holds)
    try:
        try:                                        # informational: never a reason to end a running Foreman
            from steward_cockpit.code_job_handoff import record_worker
            record_worker(job, run.pid)
            _transition(cdir, jid, ("running",), foreman_pid=run.pid)
        except Exception:
            pass
        threading.Thread(target=lambda: _wait_foreman(cdir, job, wt, run, out), name="foreman-job-" + jid,
                         daemon=True).start()
    except BaseException as e:
        if run.end(60):
            out.close()
            raise _ForemanRan(str(e))
        _note_stuck(cdir, jid, "Foreman's start failed after launch (%s) and its processes could not be seen to end; "
                    "Stop ends them and releases the job" % e)
        raise _ForemanStuck("Foreman's start failed after launch (%s) and it could not be seen to end" % e)


def _wait_foreman(cdir, job, wt, run, out):
    """Foreman ended: end what it left running and SEE it gone, then - unless Stop ended it -
    hand its whole change to the code job's finish. A tree that cannot be seen gone keeps the job running and
    registered, whoever asked (fcj review r3: never released on a failed end)."""
    jid = job["id"]
    try:
        run.proc.wait()  # duration is not evidence of a hang; the existing ticker observes progress
        ended = run.end(60)
    finally:
        out.close()
    if not ended:
        _note_stuck(cdir, jid, "Foreman's processes could not be seen to end; Stop ends them and releases the job")
        return
    _transition(cdir, jid, ("running",), worker_completed_at=time.time())
    _remove_foreman_config(wt)                      # gone before the inventory
    if jid in _FOREMAN_STOPPING:                    # Stop ended it: Stop records the job
        _FOREMAN_PROCS.pop(jid, None)
        return
    result = foreman_result(job)
    if result.get("error") is None and run.proc.returncode != 0:
        result["error"] = "Foreman exited %s" % run.proc.returncode
    result["manifest"] = foreman_manifest(job)
    try:
        finish(cdir, jid, result)
    finally:
        _FOREMAN_PROCS.pop(jid, None)


def foreman_result(job):
    """Foreman's run as the job's result: DONE -> its waves; anything else (HALT, BUDGET-STOP, no record) -> an error.
    The author is Claude by construction (foreman_settings)."""
    d = Path(job["worktree"])
    try:
        rec = json.loads((d / ".foreman" / "run-record.json").read_text(encoding="utf-8"))
    except Exception:
        rec = {}
    status = str(rec.get("status") or "")
    waves = "; ".join("wave %s %s" % (w.get("wave"), w.get("status")) for w in (rec.get("waves") or []) if isinstance(w, dict))
    text = "Foreman %s%s" % (status or "ended without a run record", (": " + waves) if waves else "")
    out = {"text": text[:1500], "authors": [FOREMAN_WRITER], "foreman_status": status}
    if status != "DONE":
        why = str(rec.get("halt_reason") or rec.get("taxonomy") or "no run record")
        out["error"] = "Foreman %s: %s" % (status or "did not finish", why[:400])
    return out


# ── Seats: the coder's family, never the model preferences ─────────────────────────────────────────────────────────
FAMILIES = ("claude", "chatgpt", "grok", "gemini")
CLI_FAMILY = {"claude": "claude", "codex": "chatgpt", "chatgpt": "chatgpt", "grok": "grok", "gemini": "gemini"}
EXHAUSTED_FOR_S = 5 * 3600
_LIMIT_WORDS = re.compile(r"usage limit|rate limit|quota|session limit|limit reached|too many requests|exhausted", re.I)


def _exhausted_path():
    return jobs_base() / "exhausted.json"


def exhausted_families():
    """Families whose last code-job turn hit a usage limit within EXHAUSTED_FOR_S - not called again until then."""
    try:
        d = json.loads(_exhausted_path().read_text(encoding="utf-8"))
    except Exception:
        return set()
    now = time.time()
    return {f for f, until in (d.items() if isinstance(d, dict) else []) if isinstance(until, (int, float)) and until > now}


def mark_exhausted(family):
    if family not in FAMILIES:
        return
    try:
        d = json.loads(_exhausted_path().read_text(encoding="utf-8")) if _exhausted_path().is_file() else {}
    except Exception:
        d = {}
    d[family] = time.time() + EXHAUSTED_FOR_S
    tmp = _exhausted_path().with_suffix(".json.%s.tmp" % uuid.uuid4().hex[:6])
    tmp.write_text(json.dumps(d), encoding="utf-8")
    _replace(str(tmp), str(_exhausted_path()))


# consensus C3: a coder family must report its completed file writes (the manifest) - Claude, Codex, and Gemini do;
# the Grok bridge does not yet, so its jobs could never land. Refused, honestly, until its bridge reports writes.
CODE_JOB_FAMILIES = ("claude", "chatgpt", "gemini")
NO_MANIFEST = "%s cannot run a code job yet: its bridge does not report which files it wrote, so its work could never land"


SIZES = ("small", "standard")
CLAUDE_TIER_MODELS = ("sonnet", "opus", "haiku")    # the Claude CLI's aliases; its catalog shows only "best"


def _redo_refusal(jobs, escalates):
    """Why ``escalates`` cannot be redone now, or None: it must be a small-tier job of this effort that ended without
    landing, not being re-filed, and not redone already."""
    orig = jobs.get(escalates)
    if not orig or not str(orig.get("tier") or "").startswith("small"):
        return "%s is not a small-tier job of this effort" % escalates
    if orig.get("status") in LIVE or orig.get("landed") or orig.get("placed") or orig.get("finalizer_active"):
        return "%s is still running, being re-filed, or already landed" % escalates
    twin = next((j for j, r in jobs.items() if r.get("escalates") == escalates), None)
    if twin:
        return "%s is already redone by %s; inspect that job" % (escalates, twin)
    try:                                              # five r11 #2: the same confirmed-exit test a re-filing uses
        from steward_cockpit import code_job_handoff as handoff
        state = handoff.observe(orig)["state"]
    except Exception:
        state = "unknown"
    if state not in (("completed", "dead") if orig.get("status") == "stopped" else ("completed",)):
        return "%s's worker is not confirmed ended (%s); inspect it first" % (escalates, state)
    return None


def tiers_path():
    from steward_cockpit import foundry_tools
    return Path(os.environ.get("ANCHOR_TIERS_FILE") or foundry_tools.index_path().parent / "tiers.json")


def small_tier(family, discover=None):
    """John 2026-10-13: "smaller jobs on a model below frontier (one tier down) and at a lower effort". The small tier
    for ``family`` from John's tiers.json, checked against what the family really offers: (selection, None) or
    (None, why). Anchor and stewards only read the file; nothing here changes the dashboard's settings."""
    import model_policy
    try:
        data = json.loads(tiers_path().read_text(encoding="utf-8"))
        want = (data.get("small") or {}).get(family)
    except (OSError, ValueError, AttributeError) as e:
        return None, "the tier file could not be read (%s)" % str(e)[:80]
    if not isinstance(want, dict):
        return None, "no small tier for %s" % family
    model, effort = str(want.get("model") or ""), str(want.get("effort") or "")
    if effort not in model_policy.EFFORT_ORDER:
        return None, "effort %r is not a known level" % effort
    if family not in ("claude", "chatgpt", "gemini"):
        return None, "no small tier for %s" % family
    if family == "claude" and model not in CLAUDE_TIER_MODELS:
        return None, "Claude model %r is not one of %s" % (model, ", ".join(CLAUDE_TIER_MODELS))
    try:
        rows, _ = (discover or model_policy.discover)(family)
    except Exception as e:
        return None, "the %s models could not be listed (%s)" % (family, str(e)[:80])
    # Claude's catalog is one moving alias ("best") with the efforts the CLI accepts; ChatGPT and Gemini list each model
    row = rows[0] if family == "claude" and rows else next((r for r in rows if r.get("model") == model), None)
    if row is None:
        return None, "%s offers no model %r" % (family, model)
    levels = {e.get("effort") if isinstance(e, dict) else e for e in row.get("efforts") or []}
    if effort not in levels:
        return None, "%s has no %r effort" % (model, effort)
    sel = {"family": family, "model": model, "effort": effort}
    try:
        model_policy.launch_args(sel)
    except Exception as e:
        return None, "the tier does not make a valid launch (%s)" % str(e)[:80]
    return sel, None


def choose_coder(requested=""):
    """(family, None) or (None, reason): the job's own choice, else the Coder seat, else the Terminal seat - never a
    family known to be exhausted. Reads the dashboard settings; writes nothing."""
    try:
        import anchor_settings
        settings = anchor_settings.get_launch_settings()
    except Exception as exc:
        return None, "the dashboard settings could not be read: %s" % exc
    tired = exhausted_families()
    asked = str(requested or "").strip().lower()
    if asked:
        if asked not in FAMILIES:
            return None, "unknown coder family %r" % asked
        if asked not in CODE_JOB_FAMILIES:
            return None, NO_MANIFEST % asked
        if asked in tired:
            return None, "%s hit its usage limit recently; choose another family or wait" % asked
        return asked, None
    for fam in (settings.get("coding_family"), settings.get("default_cli"), settings.get("review_family")):
        fam = str(fam or "").lower()
        if fam in CODE_JOB_FAMILIES and fam not in tired:
            return fam, None
    return None, "no configured code-job family (Claude, ChatGPT, or Gemini) is available now"


# ── Checks: an argument list or a temp script; never cut, never re-quoted ──────────────────────────────────────────
CHECK_MAX = 20000
BRIEF_MAX = 8000


def normalize_check(check):
    """(check, None) or (None, reason). A list is an argument list (no shell); a string is the full command text."""
    if isinstance(check, (list, tuple)):
        argv = [str(a) for a in check]
        if not argv or not all(a.strip() for a in argv):
            return None, "a check given as a list needs a program and its arguments"
        return argv, None
    text = str(check or "")
    if len(text) > CHECK_MAX:
        return None, "the check is %d characters - put it in a script file in the repository" % len(text)
    return text, None


COMMAND_OBSERVE_S = 5  # observation cadence, never a runtime limit


def run_command(job, tree, argv, *, output_limit=128 * 1024):
    """One owned, contained check/review. Observe until exit or explicit Stop, without a guessed deadline.

    Reuses Foreman's process containment. File-backed output avoids pipe deadlocks and unbounded RAM;
    the log remains outside the product tree for inspection. A live/unknown tree never releases its claim.
    """
    import proc_probe
    d = jobs_base() / "checks"
    d.mkdir(parents=True, exist_ok=True)
    log = d / ("%s-%s-%s.log" % (job["id"], job.get("attempt", 1), uuid.uuid4().hex[:8]))
    cdir = job.get("steward_dir")
    command = {"phase": job.get("phase"), "started_at": time.time(), "log": str(log),
               "state": "starting", "activity_at": None}
    def observation_error(message):
        if (command.get("last_observation_error") or {}).get("text") != message:
            logging.getLogger(__name__).warning("code job %s: %s", job["id"], message)
        command["last_observation_error"] = {"text": message, "at": time.time()}

    def save():
        if cdir:
            try:
                if not _transition(cdir, job["id"], LIVE, expect_attempt=job.get("attempt", 1), command=dict(command)):
                    observation_error("command observation was not saved; checking current ownership")
            except Exception as exc:
                observation_error("command observation could not be saved: " + str(exc)[:200])
    if cdir and _stop_asked(job, on_error=observation_error):
        command.update(state="completed", ended_at=time.time(), cancelled=True)
        save()
        return subprocess.CompletedProcess(argv, 130, "", "stopped before command launch")
    with log.open("wb") as output:
        fatal_launch = None
        try:
            run = _popen_contained(argv, str(tree), dict(os.environ), output)
        except _Uncontained as exc:
            run = exc.run
            fatal_launch = command["error"] = str(exc)
        try:
            birth = proc_probe.creation_time(run.pid)
        except Exception as exc:
            birth = None
            observation_error("command identity could not be observed: " + str(exc)[:200])
        command.update(pid=run.pid, birth=birth, state="active", contained=run.wjob is not None)
        save()
        size, cancelled = 0, False
        while True:
            if cdir and _stop_asked(job, on_error=observation_error):
                cancelled = True
            exited = False
            try:
                exited = run.poll() is not None
            except Exception as exc:
                observation_error("command exit could not be observed: " + str(exc)[:200])
            if cancelled or fatal_launch or exited:
                ended = False
                try:
                    ended = run.end(5)
                except Exception as exc:
                    observation_error("command cleanup could not be confirmed: " + str(exc)[:200])
                if ended:
                    command.pop("cleanup_detail", None)
                    break
                command.update(state="cleanup_wait", cleanup_detail="process tree has not been confirmed ended; work stays claimed")
                save()
                time.sleep(COMMAND_OBSERVE_S)
                continue
            try:
                try:
                    run.proc.wait(timeout=COMMAND_OBSERVE_S)
                except subprocess.TimeoutExpired:
                    pass  # inspect; never convert quiet or elapsed time into failure
                current_size = log.stat().st_size
                if current_size != size:
                    size = current_size
                    command.update(activity_at=time.time(), output_bytes=size)
            except Exception as exc:
                observation_error("command observation failed: " + str(exc)[:200])
                time.sleep(COMMAND_OBSERVE_S)
            save()  # retry observation persistence even when the command is quiet
        try:
            size = log.stat().st_size
        except OSError as exc:
            observation_error("command log size could not be read: " + str(exc)[:200])
        command.update(state="completed", ended_at=time.time(), returncode=run.proc.returncode,
                       cancelled=cancelled, output_bytes=size)
        save()
    try:
        with log.open("rb") as output:
            output.seek(max(0, log.stat().st_size - output_limit))
            text = output.read(output_limit).decode("utf-8", errors="replace")
    except OSError as exc:
        text = ""
        observation_error("command output could not be read: " + str(exc)[:200])
        save()
    if cancelled:
        text += "\nStopped at the user's request; saved work is retained."
    if fatal_launch:
        text += "\n" + fatal_launch
    return subprocess.CompletedProcess(argv, 130 if cancelled else 1 if fatal_launch else run.proc.returncode, text, "")


def _escape_cmd_percent(text):
    """Escape literal '%' as '%%' for Windows .cmd batch scripts while preserving %ENV_VAR% expansions."""
    env_keys = {k.upper() for k in os.environ} | {
        "CD", "DATE", "TIME", "RANDOM", "ERRORLEVEL", "CMDEXTVERSION", "CMDCMDLINE"
    }
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "%":
            out.append(text[i])
            i += 1
            continue
        if i + 1 < n and text[i + 1] == "%":
            out.append("%%")
            i += 2
            continue
        m = re.match(r"^%([A-Za-z_][A-Za-z0-9_()]*)%", text[i:])
        if m and m.group(1).upper() in env_keys:
            out.append(m.group(0))
            i += len(m.group(0))
            continue
        out.append("%%")
        i += 1
    return "".join(out)


def run_check(job, tree):
    """Run the job's check in ``tree`` (the job's own worktree). (ok, output tail). A string runs from a temp script
    so its quotes and length reach the shell unchanged; a list runs with no shell at all."""
    check = job.get("check")
    if not check:
        return None, ""
    script = None
    try:
        if isinstance(check, list):
            argv = check
        else:
            d = jobs_base() / "checks"
            d.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                script = d / ("%s-%s.cmd" % (job["id"], uuid.uuid4().hex[:6]))
                cmd_body = _escape_cmd_percent(check.replace("\r\n", "\n")).replace("\n", "\r\n")
                with script.open("w", encoding="utf-8", newline="") as fh:   # already CRLF: text mode made CR CR LF
                    fh.write("@echo off\r\n" + cmd_body + "\r\n")
                argv = ["cmd.exe", "/d", "/c", "call", str(script)]
            else:
                script = d / ("%s-%s.sh" % (job["id"], uuid.uuid4().hex[:6]))
                script.write_text(check + "\n", encoding="utf-8")
                argv = ["sh", str(script)]
        r = run_command(job, tree, argv, output_limit=1200)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-1200:]
    except Exception as e:
        return False, "the check did not run: %s" % e
    finally:
        if script is not None:
            try:
                script.unlink()
            except OSError:
                pass


def check_names_absent(job, tree):
    """Files a failed check names that are not in the job's tree (2026-10-13: two MBA jobs were kept because their
    checks tested an evidence.zip the worker never made). It states the fact only: the file may be a declared output
    the worker missed or an input the check needs. A list check's arguments are taken as given; a string check is
    split on spaces outside quotes. Never raises."""
    try:
        check = job.get("check")
        if isinstance(check, list):
            words = [str(a) for a in check[1:]]
        else:
            words = [w.strip(chr(34) + chr(39)) for w in shlex.split(str(check or ""), posix=False)[1:]]
        absent = []
        for w in words:
            name = w.replace(chr(92), "/")
            if (not name or name.startswith("-") or "://" in name or ":" in name or name.startswith("/")
                    or not ("/" in name or Path(name).suffix) or any(c in name for c in "*?<>|%$")):
                continue
            if (Path(tree) / name).exists():
                continue
            absent.append(name)
        return absent
    except Exception:
        return []


# ── The manifest: what the coder's tools wrote ─────────────────────────────────────────────────────────────────────
NEVER_LAND = {"foreman.config.json"}


FOREMAN_OWN = ("foreman.config.json", ".foreman-job", ".foreman", "_foreman-status.log", "foreman-checkpoint.json")


def never_lands(path):
    """foreman.config.json never lands - in any letter case, at any depth (Windows opens FOREMAN.CONFIG.JSON too) -
    nor anything a Foreman code job writes for itself at the root (fcj review r1: never by git's ignore rules alone)."""
    p = str(path).replace(chr(92), "/").replace(" (ignored by git)", "").lstrip("/").casefold()
    if p.rsplit("/", 1)[-1] in NEVER_LAND:
        return True
    return any(p == own or p.startswith(own + "/") for own in FOREMAN_OWN)


def _rel_in(tree, raw):
    try:
        root = Path(tree).resolve()
        fp = Path(raw)
        fp = (fp if fp.is_absolute() else root / fp).resolve()
        return fp.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def manifest_of(engine, tree):
    """The coder's own COMPLETED writes - a Write/Edit whose tool result came back without an error, a Codex
    file_change that completed - relative to its worktree. An attempted write that failed is not in it."""
    out = []
    for raw in list(getattr(engine, "written_ok", None) or []):
        rel = _rel_in(tree, raw)
        if rel and rel not in out:
            out.append(rel)
    return out


def authors_of(engine):
    """Every model family that actually served this coder (its provider can fall back mid-job), as family names."""
    used = set(getattr(engine, "families_used", None) or ()) | {str(getattr(engine, "cli", "") or "")}
    return sorted({CLI_FAMILY.get(c.lower(), c.lower()) for c in used if c})


def _landed_path():
    return jobs_base() / "landed-commits.json"


def record_landed_commit(commit):
    """Remember a commit a reviewed, verified code-job landing made (the only commits the served-code audit exempts)."""
    with _LOCK:
        try:
            d = json.loads(_landed_path().read_text(encoding="utf-8")) if _landed_path().is_file() else []
        except Exception:
            d = []
        if commit not in d:
            d = (d + [commit])[-2000:]
            tmp = _landed_path().with_suffix(".json.%s.tmp" % uuid.uuid4().hex[:6])
            tmp.write_text(json.dumps(d), encoding="utf-8")
            _replace(str(tmp), str(_landed_path()))


def landed_commits():
    """Every verified landing's commit - the ledger here, and the one kept in the old %LOCALAPPDATA% folder."""
    out = set()
    import paths as _paths
    for p in (_landed_path(), _paths.legacy_code_jobs_dir() / "landed-commits.json"):
        try:
            out |= set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


APP_CODE_EXT = (".py", ".js", ".mjs", ".css", ".ps1")


def is_app_file(path):
    """Application code of a repository: code files anywhere, HTML only in application folders (static/, templates/,
    ...). The ONE classifier the steward guard and the served-code audit share."""
    p = str(path).replace(chr(92), "/").lower()
    if p.endswith(APP_CODE_EXT):
        return True
    if p.endswith((".html", ".htm")):
        return bool(set(p.split("/")[:-1]) & APP_FOLDERS)
    return False


_RECORDS = re.compile(r"(?:^|/)\.ecgberht/|(?:^|/)\.anchor/|(?:^|/)(?:ECGBERHT|DELIVERABLES|STATUS[^/]*)\.md$"
                      r"|(?:^|/)(?:strip|roadmap)\.json$|(?:^|/)journal/|(?:^|/)code-job-outputs/", re.I)


def watched(path):
    """What the source audit protects (consensus C1): application code and agent-instruction files - never a
    cockpit's runtime records (its .ecgberht, strip, roadmap, register, journal), which change during every job when
    the cockpit lives inside the repository."""
    p = str(path).replace(chr(92), "/")
    try:
        import git_safety as _gs
        if _gs.is_runtime_path(p):
            return False
    except Exception:
        pass
    if _RECORDS.search(p):
        return False
    return is_app_file(p) or p.rsplit("/", 1)[-1].casefold() in INSTRUCTION_FILES


def dirty_snapshot(repo):
    """{path: content hash} of the source repository's changed or untracked WATCHED files right now (application code
    and instruction files; never runtime records). Hashed in one batch. Compared at finish/stop with the commits made
    since the job began. None when git cannot say."""
    paths = porcelain_paths(repo)
    if paths is None:
        return None
    paths = [p for p in paths if watched(p)]
    snap, present = {}, []
    for path in paths:
        if (Path(repo) / path).is_file():
            present.append(path)
        else:
            snap[path] = "(gone)"
    if present:
        try:
            r = subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin-paths"], input="\n".join(present) + "\n",
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            hashes = r.stdout.split() if r.returncode == 0 else []
        except Exception:
            hashes = []
        if len(hashes) != len(present):                  # one unreadable file must not spoil the batch: per path
            snap.update(dirty_snapshot_paths(repo, present))
        else:
            snap.update(dict(zip(present, hashes)))
    return snap


MAX_OUTPUTS = 80      # W1 (2026-10-09): exact paths named before the job starts; more is refused, never cut short


def _runtime(path):
    """A steward's runtime record (git_safety.is_runtime_path - the one rule): it never refuses a job and never enters
    its commit; a dirty one keeps the worktree. Fails closed (not runtime) when git_safety cannot be read."""
    try:
        import git_safety as _gs
        return bool(_gs.is_runtime_path(str(path).replace(" (ignored by git)", "").replace(chr(92), "/")))
    except Exception:
        return False


def _not_runtime(paths):
    return [p for p in paths if not _runtime(p)]


def declare_hint(path):
    """The declaration line that would admit ``path`` (a refusal is actionable, W1) - only when declared_outputs
    would accept it; otherwise why it cannot be declared."""
    p = str(path).replace(" (ignored by git)", "")
    ok, why = declared_outputs([p])
    return ("declare it: --output %s" % ok[0]) if ok else ("cannot be declared: %s" % why)


def refusal_detail(paths):
    """Every refused path, each with its declaration line or why it cannot be declared - never cut short."""
    return "; ".join("%s [%s]" % (p, declare_hint(p)) for p in paths)


_BOOKKEEPING = re.compile(r"^(?:\.anchor/|\.ecgberht/|\.foreman-job/|\.foreman/|_foreman-status\.log$|foreman-checkpoint\.json$)"
                          r"|(?:^|/)__pycache__/|(?:^|/)\.pytest_cache/|\.pyc$")


def ignored_outputs(tree):
    """Files git ignores in the worktree that are not the job's own bookkeeping - a coder's or a check's outputs
    (a fresh worktree has none), which removing the worktree would destroy."""
    code, out, _ = _git_raw(tree, "-c", "core.quotepath=false", "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
                        timeout=600)
    if code != 0:
        return ["(git could not list ignored files)"]
    return [p for p in out.split("\0") if p.strip() and not _BOOKKEEPING.search(p.replace(chr(92), "/"))]


def changed_paths(tree, base):
    """Every path that differs from ``base`` in the worktree: committed, staged, unstaged and untracked (ignored
    files excepted). None when git cannot say."""
    code, out, _ = _git_raw(tree, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", base, timeout=600)
    code2, untracked, _ = _git_raw(tree, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z",
                               timeout=600)
    if code != 0 or code2 != 0:
        return None
    names = [n for n in (out + "\0" + untracked).split("\0") if n.strip()]
    return sorted(set(names))


# ── The review gate ────────────────────────────────────────────────────────────────────────────────────────────────
DOCUMENT_EXTS = {".md", ".markdown", ".pdf", ".ics", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"}
# instruction files steer agents - they are never "just documents"
INSTRUCTION_FILES = {"claude.md", "agents.md", "skill.md", "gemini.md", "copilot-instructions.md"}


APP_FOLDERS = {"static", "templates", "template", "public", "src", "app", "steward_cockpit", "vendor", "lib", "shell",
               "foundry-gui", "dist", "foundry-display"}   # consensus C5: served application HTML is code


def is_document(path):
    """A document never enters the review gate. HTML counts as one only outside application folders (a page in
    static/ or templates/ is application code)."""
    parts = str(path).replace(chr(92), "/").casefold().split("/")
    name = parts[-1]
    ext = os.path.splitext(name)[1]
    if name in INSTRUCTION_FILES:
        return False
    if ext in (".html", ".htm"):
        return not (set(parts[:-1]) & APP_FOLDERS)
    return ext in DOCUMENT_EXTS
REVIEW_TOOL = Path(__file__).resolve().parents[1] / "tools" / "steward_review.mjs"


def run_review(job, tree, head, delta_from=""):
    """One review of the candidate ``head`` in ``tree`` by a family other than the author's. Returns the review
    record; ``record["ok"]`` is False on ANY failure. ANCHOR_REVIEW_CMD (a JSON argv) is the test seam."""
    brief = jobs_base() / "checks" / ("%s-brief.md" % job["id"])
    note = ""
    if job.get("worker") == "foreman":                # fcj r4: from THIS candidate, after every output it gained
        new = added_files(tree, candidate_base(job), head)
        if new is None:
            return {"ok": False, "error": "the files Foreman added could not be listed, so it cannot be reviewed"}
        note = foreman_review_note(new)
    text = (note + "\n\nBRIEF:\n" if note else "") + (job.get("brief") or "")
    if len(text) > REVIEW_BRIEF_READ:                 # never sent cut short: the reviewer reads it whole or not at all
        return {"ok": False, "error": "the review's brief is too long for the reviewer to read whole (%d characters, "
                                      "%d at most); the work is kept for a look" % (len(text), REVIEW_BRIEF_READ)}
    try:
        brief.parent.mkdir(parents=True, exist_ok=True)
        with open(brief, "w", encoding="utf-8", newline="") as fh:   # exactly the characters counted above
            fh.write(text)
    except OSError as e:                              # fcj r4: a reviewer given no brief is never asked
        return {"ok": False, "error": "the review's brief could not be written (%s)" % e}
    seam = os.environ.get("ANCHOR_REVIEW_CMD")
    try:
        cmd = json.loads(seam) if seam else ["node", str(REVIEW_TOOL)]
    except ValueError:
        return {"ok": False, "error": "ANCHOR_REVIEW_CMD is not a JSON argument list"}
    argv = cmd + ["--repo", str(tree), "--base", candidate_base(job), "--head", head,
                  "--author-family", ",".join(job.get("authors") or [job.get("coder_family") or ""]), "--brief-file", str(brief),
                  "--exhausted", ",".join(sorted(exhausted_families()))]
    if delta_from:
        argv += ["--delta-from", delta_from]
    if job.get("reviewer_family"):
        argv += ["--reviewer-family", str(job["reviewer_family"])]
    try:
        r = run_command(job, tree, argv)
    except Exception as e:
        return {"ok": False, "error": "the review could not run: %s" % e}
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")]
    try:
        rec = json.loads(lines[-1]) if lines else None
    except ValueError:
        rec = None
    if not isinstance(rec, dict):
        return {"ok": False, "error": "the review gave no record (exit %s): %s" % (r.returncode, (r.stderr or "")[-300:])}
    if r.returncode != 0:                     # a record from a review that did not finish is never a pass (283fc40)
        rec.update(ok=False, error=rec.get("error") or
                   "the review process did not complete successfully (exit %s)" % r.returncode)
    rec["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec["delta_from"] = delta_from or None
    if not rec.get("ok") and rec.get("family") and _LIMIT_WORDS.search(str(rec.get("error") or "")):
        mark_exhausted(str(rec["family"]).lower())        # the reviewer's family is not asked again for a while
    return rec


def review_blocks(job, rec, tree, head):
    """The reason this review does NOT allow landing, or "" when it does. Fail closed on every doubt."""
    if not isinstance(rec, dict) or not rec.get("ok"):
        return "the review failed: %s" % ((rec or {}).get("error") or "no record")
    fam = str(rec.get("family") or "").lower()
    if not fam:
        return "the review record names no family"
    authors = [a for a in (job.get("authors") or []) if a]
    if not authors:
        return "the job has no record of which model family wrote it"
    if fam in authors or fam == str(job.get("coder_family") or "").lower():
        return "the review was done by the author's own family (%s)" % fam
    blocking = [f for f in (rec.get("findings") or []) if isinstance(f, dict) and f.get("severity") in ("BLOCKER", "MAJOR")]
    if rec.get("verdict") == "PASS" and blocking:
        return "the review says PASS but lists a %s finding: %s" % (blocking[0].get("severity"), str(blocking[0].get("issue"))[:160])
    code, tree_hash, _ = _git(tree, "rev-parse", head + "^{tree}")
    if code != 0 or not tree_hash or rec.get("tree_hash") != tree_hash:
        return "the reviewed tree is not the candidate (reviewed %s, candidate %s)" % (rec.get("tree_hash"), tree_hash)
    if rec.get("verdict") != "PASS":
        found = "; ".join("%s %s" % (f.get("severity", "?"), str(f.get("issue", ""))[:160])
                          for f in (rec.get("findings") or [])[:4] if isinstance(f, dict))
        return "the %s reviewer did not pass it: %s" % (fam, found or "no findings given")
    return ""


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            proc.kill()
    except Exception:
        pass


def declared_outputs(outputs):
    """([relative paths], None) or (None, why): the files a job names up front as its outputs (W2, 2026-10-08) - a
    plain path inside the repository, never a runtime record, never foreman.config.json, at most MAX_OUTPUTS (80).
    The whole declaration is validated; it is never cut short (W1, 2026-10-09)."""
    out = []
    for raw in list(outputs or []):
        p = str(raw or "").strip().replace(chr(92), "/")
        if not p:
            continue
        if p.startswith("/") or ":" in p or any(ord(c) < 32 for c in p) or ".." in p.split("/") or "*" in p or "?" in p:
            return None, "a declared output is a plain path inside the repository: %s" % p
        import posixpath
        p = posixpath.normpath(p)          # normalized FIRST, then every exclusion applies to this exact path (ChatGPT r3)
        if p in (".", "") or p.startswith("../"):
            return None, "a declared output is a plain path inside the repository: %s" % raw
        try:
            import git_safety as _gs
            if _gs.is_runtime_path(p) or never_lands(p) or _RECORDS.search(p):
                return None, ("a declared output may not be a runtime record, a cockpit record (ECGBERHT, DELIVERABLES, "
                              "STATUS, strip, roadmap, journal) or foreman.config.json: %s" % p)
        except Exception:
            return None, "the declared outputs could not be checked"
        if p not in out:
            out.append(p)
    if len(out) > MAX_OUTPUTS:
        return None, "at most %d declared outputs (%d named)" % (MAX_OUTPUTS, len(out))
    return out, None


def start(cdir, repo, brief, check="", engine_factory=None, steward="", coder="", actor="", skill="", outputs=None,
          worker="coder", plan="", profile="slim", work_dir=None, size="standard", escalates="", reviewer=""):
    """Start a code job for the steward at ``cdir``: a worktree of ``repo`` and a coder engine given ``brief``.
    ``engine_factory(worktree) -> engine`` is the seam (steward_routes passes get_engine). ``coder`` is this job's
    family choice (else the Coder seat); ``check`` is an argument list or the full command text. ``worker="foreman"``
    builds the brief (or the approved ``plan``) with Foreman in the same worktree, gated by the check (2026-10-09)."""
    brief = str(brief or "").strip()
    if not brief:
        return {"ok": False, "error": "a code job needs a brief"}
    if len(brief) > BRIEF_MAX:
        return {"ok": False, "error": "no job started: the brief is %d characters; the limit is %d. "
                "Keep the assignment within that limit and reference supporting files; nothing was truncated."
                % (len(brief), BRIEF_MAX)}
    if not repo or not Path(repo).is_absolute():
        return {"ok": False, "error": "no job started: repository must be an absolute path resolved by the caller"}
    check, why = normalize_check(check)
    if why:
        return {"ok": False, "error": why}
    if not check or (isinstance(check, str) and not check.strip()):
        return {"ok": False, "error": "no job started: every code job needs --check or --check-argv "
                "with the existing verification/test command for its output"}
    worker = str(worker or "coder").strip().lower()
    plan, profile = str(plan or ""), str(profile or "slim").strip().lower()
    if worker == "foreman":
        if not foreman_code_jobs_on():
            return {"ok": False, "error": "no job started: Foreman code jobs are off (ANCHOR_FOREMAN_CODE_JOBS=0)"}
        if not check:
            return {"ok": False, "error": "no job started: Foreman needs the test command it builds to (--check)"}
        if profile not in FOREMAN_PROFILES:
            return {"ok": False, "error": "no job started: the Foreman profile is slim or standard, not %s" % profile}
        why = foreman_plan_ok(plan)
        if why:
            return {"ok": False, "error": "no job started: %s" % why}
        if FOREMAN_WRITER in exhausted_families():   # fcj review r7: its pinned writer is cooling down
            return {"ok": False, "error": "no job started: Claude - the family Foreman writes with - hit its usage "
                    "limit recently; start it when that has passed"}
        if not FOREMAN_RUN_LIVE.is_file():
            return {"ok": False, "error": "no job started: Foreman is not at %s" % FOREMAN_RUN_LIVE}
        family = FOREMAN_WRITER                  # its writing seats are pinned to Claude (foreman_settings)
    elif worker == "coder":
        family, why = choose_coder(coder)
        if why:
            return {"ok": False, "error": why}
    else:
        return {"ok": False, "error": "a code job's worker is a coder or foreman, not %s" % worker}
    reviewer = str(reviewer or "").strip().lower()
    if reviewer:
        if reviewer not in FAMILIES:
            return {"ok": False, "error": "no job started: unknown reviewer family %s" % reviewer}
        if reviewer == family:
            return {"ok": False, "error": "no job started: reviewer family (%s) must differ from coder family (%s)" % (reviewer, family)}
        if reviewer in exhausted_families():
            return {"ok": False, "error": "no job started: reviewer family (%s) hit its usage limit recently" % reviewer}
    size = str(size or "standard").strip().lower()
    if size not in SIZES:
        return {"ok": False, "error": "no job started: a job's size is small or standard, not %s" % size}
    escalates = str(escalates or "").strip()
    if escalates and not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", escalates):
        return {"ok": False, "error": "no job started: --escalates names a job id (like 20261013-070623-b2a758)"}
    if escalates:                                  # plan r2 #3: one standard redo per ended, unlanded small job
        if size != "standard":
            return {"ok": False, "error": "no job started: a redo of a small job runs at standard size"}
        why = _redo_refusal(read_jobs(cdir), escalates)
        if why:
            return {"ok": False, "error": "no job started: " + why}
    tier, tier_note = None, "standard"
    if size == "small":
        if worker != "coder":
            tier_note = "standard (small unavailable: Foreman runs its own seats)"
        else:
            tier, why = small_tier(family)
            tier_note = ("small: %s %s" % (tier["model"], tier["effort"])) if tier else "standard (small unavailable: %s)" % why
    outputs, why = declared_outputs(outputs)
    if why:
        return {"ok": False, "error": why}
    doc_stems = {k for p in (outputs or []) if (k := _doc_stem_key(p)) is not None}
    if len(doc_stems) > 3:
        return {"ok": False, "error": "no job started: %d distinct document stems declared in outputs (max 3 per job) - "
                "split multi-chapter or multi-deliverable bundles into separate focused jobs" % len(doc_stems)}
    root = _repo_root(repo or "")
    if root is None:
        return {"ok": False, "error": "not a git repository: %s" % repo}
    why = destination_error(root)
    if why:
        return {"ok": False, "error": "no job started: " + why}
    work_dir, why = work_scope(root, repo, work_dir, outputs)
    if why:
        return {"ok": False, "error": "no job started: " + why}
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = "steward-job-" + job_id
    wt = jobs_base() / job_id
    settings_dir = None
    if worker == "foreman":
        settings_dir, why = foreman_settings({"id": job_id})
        if why:
            return {"ok": False, "error": "no job started: %s" % why}
    # John 2026-10-09: several jobs may run on one repository at once - each has its own worktree, landings take the
    # repository's commit lock one at a time, and a job whose base moved is integrated, re-checked and its delta
    # re-reviewed before it is placed (a conflict keeps the work, never lands it). Ordering is the steward's call.
    # fcj review r4: the start's base and its snapshot of the repository's own changes are read under the repository's
    # commit lock (the one lock every checkout of it shares), so another job's landing is never seen half-placed; the
    # lock is always taken before _LOCK (the landing's order)
    import git_safety as _gs
    with _gs.repo_lock(str(root), wait_s=600, who="start of code job " + job_id) as held:
        if not held:
            return {"ok": False, "error": "no job started: the repository's commit lock stayed busy (a landing); try again"}
        with _LOCK:      # the worktree and the busy entry: one step
            land_to, installed = "", False
            try:
                import anchor_next
                if anchor_next.is_served_repo(root):
                    # John 2026-10-10: a cockpit never changes Anchor's own code; he makes those changes from outside
                    # Anchor
                    return {"ok": False, "error": "no job started: Anchor's own code is never changed from a cockpit (John's "
                            "rule) - write what should change in a note for John; he makes Anchor changes from outside Anchor"}
                if anchor_next.is_installed_repo(root):
                    # 2026-10-10: an INSTALLED skill repository (C:\dev\trio, C:\dev\Skill Foundry, ...) is live code the
                    # next skill run executes. A model pass never installs it: the job lands on that repository's own
                    # anchor-next in the lander's checkout, and a human activates it (anchor_next.activate <repo>)
                    ip, why = anchor_next.ensure_integration(root)
                    if ip is None:
                        return {"ok": False, "error": "no job started: %s" % why}
                    land_to, installed = str(ip), True
            except Exception as e:
                return {"ok": False, "error": "no job started: could not tell where the job may land (%s)" % e}
            code, base, err = _git(land_to or root, "rev-parse", "HEAD")
            if code != 0:
                return {"ok": False, "error": "the repository has no commit to start from: %s" % err}
            if worker == "foreman":                  # Anchor writes foreman.config.json in the worktree: never over the project's
                code, tracked, _ = _git(land_to or root, "ls-tree", "-r", "--name-only", base, "--", *FOREMAN_OWN)
                if code != 0 or tracked.strip():
                    return {"ok": False, "error": "no job started: %s tracks files a Foreman code job writes for itself (%s); "
                            "run Foreman there by hand" % (root, ", ".join(tracked.split()[:4]) or "unreadable")}
            code, _, err = _git(root, "worktree", "add", "-b", branch, str(wt), base, timeout=600)
            if code != 0:
                why = "\n".join(ln for ln in re.split(r"[\r\n]+", err) if ln.strip() and not re.match(
                    r"(Updating files|Preparing worktree|Checking out files):", ln.strip()))    # the error, not progress
                return {"ok": False, "error": "could not make the worktree: %s" % (why or err)[-300:]}
            served_dirt = dirty_snapshot(root)
            if served_dirt is None:
                return {"ok": False, "error": "could not record the repository's own changes before starting; no job started"}
            why = _redo_refusal(read_jobs(cdir), escalates) if escalates else None
            if why:                                   # five r1 #2 / r2 #2: raced with another redo or a re-filing
                _cleanup({"id": job_id, "repo": str(root), "branch": branch, "worktree": str(wt)}, keep_branch=False)
                return {"ok": False, "error": "no job started: " + why}
            job = {"id": job_id, "repo": str(root), "branch": branch, "worktree": str(wt), "base": base, "brief": brief,
                   "work_dir": work_dir, "attempt": 1, "phase": "producing", "phase_at": time.time(),
                   "repo_dirt": served_dirt,
                   "check": check, "status": "running", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "land_to": land_to, "outputs": outputs,
                   "steward_dir": str(cdir), "steward": steward, "worker": worker, "coder_family": family,
                   "started_by": str(actor or "the steward"), "size": size, "tier": tier_note}
            if reviewer:
                job["reviewer_family"] = reviewer
            if escalates:
                job["escalates"] = escalates
            # 2026-10-08 (John: "identify the actual skill being used"): a job that runs a skill says which, so the status
            # names it and its finish time is reckoned from that skill's own history - never from other coding jobs
            label = re.sub(r"[^A-Za-z0-9 ._-]", "", str(skill or "")).strip()[:40]
            if label:
                job["skill"] = label
            if installed:                                 # the record says where it lands and that it does not install
                job["installed_repo"] = True
            if worker == "foreman":
                job.update(skill="Foreman", foreman_profile=profile, plan_given=bool(plan.strip()))
                _FOREMAN_PROCS[job_id] = _Starting()     # registered with the record: never taken for a lost Foreman
            try:
                _write_job(cdir, job)
                _index_job(job)
                b = _busy_read()
                b[job_id] = {"job": job_id, "cdir": str(cdir), "repo": _norm(root)}
                _busy_write(b)
            except Exception as e:                    # fcj r5: never a reservation without a record nobody can stop
                _FOREMAN_PROCS.pop(job_id, None)
                try:
                    d = read_jobs(cdir)
                    if job_id in d:
                        d.pop(job_id)
                        p_ = _path(cdir)
                        tmp_ = p_.with_suffix(".json.tmp")
                        tmp_.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
                        _replace(str(tmp_), str(p_))
                except Exception:
                    pass
                _cleanup(job, keep_branch=False)
                return {"ok": False, "error": "no job started: its record could not be written (%s)" % e}
    def abandon(why):                                 # nothing ran in the worktree: it goes, and so does the reservation
        _FOREMAN_PROCS.pop(job_id, None)
        j = _transition(cdir, job_id, LIVE, status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"), error=why)
        _cleanup(j or job, keep_branch=False)
        return {"ok": False, "error": why, "job": job_id}

    # fcj review r4: the restart barrier is asked AFTER the job is counted (its busy entry, and Foreman's reservation),
    # so a drain that began meanwhile either sees this job or is seen here - never a job launched into a restart
    try:
        from steward_cockpit import maintenance as _maint
        draining = _maint.is_active()
    except Exception:
        draining = False
    if draining:
        return abandon("no job started: Anchor is restarting once running work finishes; start it after the restart")
    try:                                              # the coder's own folder record: one workbench terminal
        terms = Path(wt) / ".anchor" / "steward-terms.json"
        terms.parent.mkdir(parents=True, exist_ok=True)
        terms.write_text(json.dumps({"1": {"label": "code job " + job_id, "created": job["started"], "archived": False}}), encoding="utf-8")
        if str(brief or "").startswith("FULL BRIEF FILE"):
            first_ln = str(brief).splitlines()[0]
            bf_cand = first_ln.split(":", 1)[1].strip() if ":" in first_ln else ""
            if bf_cand and Path(bf_cand).is_file():
                shutil.copy2(bf_cand, Path(wt) / ".anchor" / "full_brief.md")
        _exclude_local(wt)
    except Exception as e:
        return abandon("no job started: the job's worktree could not be prepared (%s)" % e)
    if worker == "foreman":
        try:
            _start_foreman(cdir, job, wt, plan, profile, settings_dir)
        except _ForemanStuck as e:                    # it may be running: the job stays running, registered and counted
            return {"ok": False, "error": "%s; the job keeps its place until Stop ends it" % e, "job": job_id}
        except _ForemanRan as e:                      # it ran, and was ended and seen gone: its work is kept
            _FOREMAN_PROCS.pop(job_id, None)
            _transition(cdir, job_id, LIVE, status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        error="Foreman's start failed after it began: %s" % e, kept_worktree=str(wt),
                        land_note="not landed: Foreman's start failed after it began; the work is kept at %s" % wt)
            return {"ok": False, "error": "Foreman's start failed after it began (%s); its work is kept at %s" % (e, wt),
                    "job": job_id}
        except Exception as e:
            return abandon("Foreman could not start: %s" % e)
        return {"ok": True, "job": job_id, "branch": branch, "worktree": str(wt), "worker": "foreman",
                "coder": "Foreman (%s)" % profile, "repo": str(root), "work_dir": work_dir, "outputs": outputs}
    try:
        eng = engine_factory(str(wt)) if engine_factory else None
        if eng is None:
            raise RuntimeError("no engine slot for the coder")
        eng.code_job = {"cdir": str(cdir), "id": job_id, "repo": str(root),
                        "worktree": str(wt), "work_dir": work_dir, "outputs": outputs}
        eng.job_observation = {}
        eng.tier_override = tier                      # round 5: this job's engine only; the dashboard is never written
        try:   # this job's family, for this engine only (the dashboard's preferences are never written)
            import anchor_settings
            eng.policy_override = {"family": family, "revision": anchor_settings.get_launch_settings()["settings_revision"],
                                   "reason": "code_job_choice"}
        except Exception:
            pass
        eng.on_turn_done = lambda result: threading.Thread(
            target=finish, args=(cdir, job_id, dict(result or {}, manifest=manifest_of(eng, wt), authors=authors_of(eng),
                                                    model_served=(getattr(eng, "model_selection", None) or {}).get("model_served"),
                                                    failed_over=list((getattr(eng, "policy_override", None) or {}).get("failed_families") or []))),
            name="code-job-" + job_id, daemon=True).start()
        ok, why = eng.wake(fresh=True, seed=coder_brief(job))
        if not ok:
            raise RuntimeError(why)
        from steward_cockpit.code_job_handoff import record_worker
        record_worker(job, getattr(getattr(eng, "proc", None), "pid", None))
        try:   # 2026-10-08: the status names the model and effort the coder was asked for, not only its family
            sel = getattr(eng, "model_selection", None) or {}
            asked = " ".join(str(x) for x in (sel.get("model"), sel.get("effort")) if x)
            if asked:
                _transition(cdir, job_id, LIVE, coder_model=asked[:60])
        except Exception:
            pass
    except Exception as e:
        j = _transition(cdir, job_id, LIVE, status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"), error="the coder could not start: %s" % e)
        _cleanup(j or job, keep_branch=False)
        return {"ok": False, "error": "the coder could not start: %s" % e, "job": job_id}
    return {"ok": True, "job": job_id, "branch": branch, "worktree": str(wt), "worker": "coder", "coder": family,
            "repo": str(root), "work_dir": work_dir, "outputs": outputs}


def _exclude_local(wt):
    """The coder's .anchor/.ecgberht bookkeeping never lands in the repository."""
    try:
        code, gitdir, _ = _git(wt, "rev-parse", "--git-common-dir")
        if code == 0:
            ex = Path(wt, gitdir) if not os.path.isabs(gitdir) else Path(gitdir)
            f = ex / "info" / "exclude"
            f.parent.mkdir(parents=True, exist_ok=True)
            cur = f.read_text(encoding="utf-8") if f.exists() else ""
            add = [x for x in ("/.anchor/", "/.ecgberht/", "/.foreman-job/", "/.foreman/",
                               "/_foreman-status.log", "/foreman-checkpoint.json", "__pycache__/", ".pytest_cache/",
                               "*.pyc") if x not in cur]
            if add:
                f.write_text(cur.rstrip("\n") + ("\n" if cur else "") + "\n".join(add) + "\n", encoding="utf-8")
    except Exception:
        pass


_COCKPIT_LEDGER_RE = re.compile(r"(?:^|/)(?:ECGBERHT|DELIVERABLES|STATUS[^/]*)\.md$|(?:^|/)roadmap\.json$", re.I)
_COMPANION_DOC_EXT = (".md", ".markdown", ".docx", ".pdf", ".html", ".htm")
_STEM_SUFFIX_RE = re.compile(r"(?:_source|-source|_redline|-redline|_track[-_]?changes|_tracked|_clean|-clean|_reading)$", re.I)


def _doc_stem_key(path):
    p = Path(str(path).replace(chr(92), "/").lstrip("/"))
    if p.suffix.lower() not in _COMPANION_DOC_EXT:
        return None
    stem = _STEM_SUFFIX_RE.sub("", p.stem).lower()
    return (p.parent.as_posix().lower(), stem) if stem else None


def _companion_outputs(job, wt, allowed, candidates, *, base=None):
    """Admit newly created same-directory, same-stem document companions (.md, _source.md, .docx, .pdf, .html) of any
    declared output or tool-written document so Markdown-first + CLI packaging never blocks landing on a companion file,
    while refusing undeclared edits to existing tracked files."""
    allowed_keys = {k for p in (allowed or ()) if (k := _doc_stem_key(p)) is not None}
    if not allowed_keys:
        return []
    out = []
    for c in candidates or ():
        if c in allowed or never_lands(c) or _runtime(c):
            continue
        if _doc_stem_key(c) in allowed_keys and not scope_error(job, wt, [c]):
            if base and _blob(wt, base, c) is not None:
                continue
            out.append(c)
    if out:
        job["admitted_companions"] = sorted(set(job.get("admitted_companions") or []) | set(out))
    return out


def _hold_cockpit_records(wt, job, manifest):
    """When a worker produces real deliverable files and also edits cockpit ledger files (DELIVERABLES.md, ECGBERHT.md,
    STATUS*.md, roadmap.json) inside the worktree, stash those ledger copies under .anchor/held-records/ and restore
    them in the worktree so they never block landing. Explicitly declared outputs are exempt."""
    try:
        base = candidate_base(job)
        changed = changed_paths(wt, base) or []
        declared_set = set(job.get("outputs") or [])
        ledgers = [p for p in changed if p not in declared_set and _COCKPIT_LEDGER_RE.search(p.replace(chr(92), "/"))]
        others = [p for p in changed if p not in set(ledgers) and not _runtime(p) and not never_lands(p)]
        if not ledgers or (not others and not declared_set):
            return []
        brief_l = str(job.get("brief") or "").lower()
        held = []
        hold_root = Path(wt) / ".anchor" / "held-records"
        for rel in ledgers:
            if Path(rel).name.lower() in brief_l:
                continue
            src = Path(wt) / rel
            if src.is_file():
                dst = hold_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            code, _, _ = _git(wt, "cat-file", "-e", "%s:%s" % (base, rel))
            if code == 0:
                _git(wt, "--literal-pathspecs", "checkout", "-q", base, "--", rel)
                _git(wt, "--literal-pathspecs", "reset", "-q", "--", rel)
            else:
                _git(wt, "--literal-pathspecs", "rm", "-q", "-f", "--ignore-unmatch", "--", rel)
                try:
                    if src.is_file() or src.is_symlink():
                        src.unlink()
                except OSError:
                    pass
            held.append(rel)
        if held:
            manifest[:] = [p for p in manifest if p not in set(held)]
            job["held_cockpit_records"] = sorted(set(job.get("held_cockpit_records") or []) | set(held))
        return held
    except Exception:
        return []


def coder_brief(job):
    documents = reading_outputs(job)
    assignment = (
        "The commissioned reading outputs are: %s. Produce these declared documents as part of the brief. A PDF, "
        "HTML, or DOCX reading copy is ONE command that takes seconds - `python \"%s\" <document.md> [--html] [--docx]` "
        "or `python C:/dev/foundry-tools/ft.py docx-redline --from-md <document.md> --out <document.docx>` (and for "
        "Word redlines: `python C:/dev/foundry-tools/ft.py docx-redline --redline <old.docx> <new.docx> --out <redline.docx>`) - "
        "or leave it: the job makes a missing one from the Markdown of the same name. Never write your own renderer or custom python-docx builder script. "
        "A declared output may also be generated by the stated check. "
        "Do not create extra deliverables, campaign plans, journals, attention or status records. "
        "Do not add review passes beyond the brief; the controller independently reviews the finished candidate. "
        % (", ".join(documents), READING_COPY_TOOL.as_posix())
    ) if documents else (
        "Do not write plan pages, reports, journals or status files; edit the commissioned code. "
    )
    return ("You are a CODE JOB commissioned by John's steward. Work only in this folder, a git worktree of "
            "%s on branch %s. Do the work in the brief below completely, at your best; you may use sub-agents if "
            "the brief asks for a swarm. Do not ask questions back: if something is genuinely John's to decide, "
            "stop and say so in your final message. %s"
            "Work in proportion to the brief: a small fix is the edit plus the stated check, done in minutes. Use the "
            "FOUNDRY TOOLS in your rules for chores (screenshots: look; waiting on something you started: wait) and "
            "do not build screenshot rigs, inspection or verification scripts, hash, receipt or provenance files, or "
            "extra checks the brief does not ask for - the job runs the check and another family reviews the result. "
            "Never end your turn while a command you started still runs: wait for it. "
            "Use your file tools (only the files your tools write will land; anything else that "
            "changes keeps the work from landing), run the checks that apply, and end with a plain summary of what "
            "you changed and how you checked it. Do not commit; the job commits your files, a reviewer of another "
            "model family reviews them, and they land only if that review passes.%s%s\n"
            "Destination: %s. Work directory: %s. Stay at the worktree root for commands; output paths are always "
            "repository-relative, including the work-directory prefix. Change files only within that scope.\n\nBRIEF:\n%s") % (
        job["repo"], job["branch"], assignment, ("\nNamed up front as this job's outputs (they may land even when a command you ran "
                                     "wrote them, not your file tools): " + ", ".join(job["outputs"])) if job.get("outputs") else "",
        ("\nThe job will run this check after you finish: " + (
            " ".join(job["check"]) if isinstance(job["check"], list) else job["check"])) if job.get("check") else "",
        job["repo"], job.get("work_dir") or "(repository root; root-wide assignment)", job["brief"])


def finish(cdir, job_id, result):
    """The coder's turn ended: check, commit, land when clean, wake the steward with the result. Never raises.
    The job is claimed first (running -> finishing): a stop that already won leaves it alone."""
    import proc_probe
    job = _transition(cdir, job_id, ("running",), status="finishing", finishing_at=time.time(), worker_completed_at=time.time(),
                      finalizer_active=True, claim={"pid": os.getpid(), "birth": proc_probe.creation_time(os.getpid()),
                                                    "actor": "finish controller", "at": time.time()})
    if not job:
        return
    try:
        _finish(cdir, job_id, job, result)
    except Exception as e:      # never leave the repository owned by a finish that died
        j = _transition(cdir, job_id, ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        expect_attempt=job.get("attempt", 1),
                        phase="outcome", phase_at=time.time(), kept_worktree=job["worktree"],
                        error="the job's finish failed: %s" % e, land_note="not landed; the work waits on branch %s" % job["branch"])
        if j:
            _report(cdir, j)
    finally:
        _transition(cdir, job_id, ("finishing", "done", "failed", "stopped"),
                    expect_attempt=job.get("attempt", 1), finalizer_active=False)


def _with_declared_ignored(job, wt, changed):
    """2026-10-12: a declared output git ignores (a PDF under a *.pdf rule) is part of the change - it lands, added
    by force by its literal path - instead of leaving the job with "nothing landable changed"."""
    if changed is None:
        return None
    declared = set(job.get("outputs") or [])
    if not declared:
        return changed
    extra = [p for p in ignored_outputs(wt) if p in declared and not never_lands(p) and p not in changed]
    return sorted(set(changed) | set(extra))


def _finish(cdir, job_id, job, result):
    from steward_cockpit import code_job_handoff as handoff
    wt, repo = job["worktree"], job["repo"]
    summary = str((result or {}).get("text") or "")[-1500:]
    err = str((result or {}).get("error") or "")
    if err and _LIMIT_WORDS.search(err):
        mark_exhausted(job.get("coder_family"))          # not called again for a while; the other family may run
    for fam in (result or {}).get("failed_over") or []:  # a family the engine failed over from mid-job
        mark_exhausted(CLI_FAMILY.get(str(fam).lower(), str(fam).lower()))
    job["authors"] = [a for a in ((result or {}).get("authors") or []) if a in FAMILIES]
    manifest = [p for p in ((result or {}).get("manifest") or []) if isinstance(p, str)]
    _hold_cockpit_records(wt, job, manifest)
    job["manifest"] = manifest
    saved = handoff.snapshot(job)
    if not _transition(cdir, job_id, ("finishing",), expect_attempt=job.get("attempt", 1),
                       authors=job["authors"], manifest=manifest, recovery_snapshot=saved):
        return
    made_copies = list(job.get("anchor_copies") or [])                # five r5 #1: copies an earlier attempt made stay ours
    _make_reading_copies(job, wt, made_copies)                        # a declared PDF/HTML/DOCX left to package is made, not missed
    changed = _with_declared_ignored(job, wt, changed_paths(wt, candidate_base(job)))
    fields = {"summary": summary, "manifest": manifest, "check_ok": None, "check_output": "", "files": [],
              "unexpected": [], "landed": False, "landed_commit": "", "review": None, "authors": job["authors"],
              "model_served": (result or {}).get("model_served") or job.get("model_served") or None}
    checked = False
    if changed == [] and not err and missing_reading_outputs(job, wt):
        # A packaging check can be the only producer (e.g. unchanged source -> new PDF).
        phase(job, "checking")
        fields["check_ok"], fields["check_output"] = run_check(job, wt)
        _make_reading_copies(job, wt, made_copies)                # review r4: the check may be what wrote the Markdown
        checked = True
        phase(job, "checking", check_ok=fields["check_ok"], check_output=fields["check_output"],
                  anchor_copies=list(made_copies), copy_prints=dict(job.get("copy_prints") or {}))
        changed = _with_declared_ignored(job, wt, changed_paths(wt, candidate_base(job)))
    keep = True                                            # the worktree stays unless the work is safely placed
    if changed is None:
        note, status, error = "not landed: git could not list the changes; the worktree is kept at %s" % wt, "failed", "git status failed"
    elif not changed:
        note, status, error = "nothing changed", ("failed" if err else "done"), err
        left = _unlanded(wt, manifest)                 # an ignored output the coder wrote is still work: keep it
        keep = bool(left)
        if left:
            fields["unexpected"] = left
            note = "nothing landable changed; outputs git ignores are kept at %s (%s)" % (wt, ", ".join(left[:8]))
        missing = missing_reading_outputs(job, wt)
        if missing:
            keep, status, error = True, "failed", "declared reading outputs missing or unsafe: " + ", ".join(missing)
            note = "not landed: " + error + "; the work is kept at %s" % wt
            fields["missing_outputs"] = missing
    else:
        # W2 (2026-10-08): only what the coder's tools recorded writing lands - plus a file the job named up front as
        # its declared output (a render a script made) and same-stem document companions, still reviewed; exclusions hold
        allowed = {p for p in manifest + list(job.get("outputs") or []) if not never_lands(p)}
        companions = _companion_outputs(job, wt, allowed, changed, base=candidate_base(job))
        if companions:
            allowed |= set(companions)
        unexpected = [p for p in changed if p not in allowed and not _runtime(p)]     # W1: runtime never refuses
        unexpected += [p for p in changed if not _runtime(p) and scope_error(job, wt, [p]) and p not in unexpected]
        files = [p for p in changed if p in allowed and not _runtime(p)]              # ... and never lands
        fields.update(unexpected=unexpected, files=files,
                      admitted_companions=list(job.get("admitted_companions") or []),
                      held_cockpit_records=list(job.get("held_cockpit_records") or []))
        status, error = ("failed" if err else "done"), err
        if err:
            note = "not landed: the coder's turn ended in an error; the work is kept at %s" % wt
        elif unexpected:
            note = ("not landed: %d changed path(s) the coder's tools did not write (%s); everything is kept at %s"
                    % (len(unexpected), refusal_detail(unexpected), wt))
        elif not files:
            note = "not landed: nothing the coder wrote changed; the worktree is kept at %s" % wt
        else:
            phase(job, "checking")
            before = worker_copy_prints(job, wt, made_copies)
            if not checked:
                fields["check_ok"], fields["check_output"] = run_check(job, wt)
                _make_reading_copies(job, wt, made_copies)        # review r4: the check may be what wrote the Markdown
            stale_worker = [n for n in stale_worker_copies(job, wt, before) if n not in made_copies]   # r12: remade = fresh
            phase(job, "checking", check_ok=fields["check_ok"], check_output=fields["check_output"],
                  anchor_copies=list(made_copies), copy_prints=dict(job.get("copy_prints") or {}))
            _hold_cockpit_records(wt, job, manifest)
            after = changed_paths(wt, candidate_base(job))
            late = sorted(set(after or []) - set(changed)) if after is not None else ["(git could not list the changes)"]
            late = _not_runtime(late)                    # W1: a runtime record the check touched never refuses
            late_companions = _companion_outputs(job, wt, allowed, late, base=candidate_base(job))
            fields["admitted_companions"] = list(job.get("admitted_companions") or [])
            fields["held_cockpit_records"] = list(job.get("held_cockpit_records") or [])
            made = [x for x in late if (x in set(job.get("outputs") or []) or x in set(late_companions)) and not never_lands(x)]
            if made:                                     # a declared output the check produced lands with the rest (W2)
                files = files + made
                fields["files"] = files
                late = [x for x in late if x not in made]
            # 2026-10-12 (MBA job 66e90d: a hand-built browser profile, 2,292 ignored files, refused a finished fix):
            # a file git ignores that the job DECLARED lands (added by force, by literal path); one nobody declared is
            # scratch - it stays in the kept worktree, named in the note, and never refuses the deliverable
            ignored = _not_runtime(ignored_outputs(wt))
            unreadable = [p for p in ignored if p.startswith("(")]
            declared = set(job.get("outputs") or [])
            forced = [p for p in ignored if p in declared and not never_lands(p) and p not in unreadable]
            scratch = [p for p in ignored if p not in declared and p not in unreadable]
            if forced:
                files = files + [p for p in forced if p not in files]
            if scratch:
                files = [p for p in files if p not in set(scratch)]
            if forced or scratch:
                fields["files"] = files
            job["force_add"] = forced
            job["scratch_kept"] = fields["scratch_kept"] = scratch
            late += unreadable + [p + " (ignored by git)" for p in ignored if p in declared and p not in forced]
            served = _locked_served_changes(job)
            missing = missing_reading_outputs(job, wt)
            fields["missing_outputs"] = missing
            if late:
                fields["unexpected"] = sorted(set(fields["unexpected"]) | set(late))
            if fields["check_ok"] is None:       # W1a (2026-10-08): every landing needs an explicit passing check
                note = ("not landed: no check was given - every landing needs a passing check (start the job with "
                        "--check); the work is kept at %s" % wt)
            elif fields["check_ok"] is not True:
                note = "not landed: the check failed in the job's tree; the work is kept at %s" % wt
                absent = check_names_absent(job, wt)
                if absent:
                    note += ("; the check names %s, which is not in the job's tree - read the brief before recovering "
                             "with another check" % ", ".join(absent[:3]))
            elif missing:
                note = "not landed: declared reading outputs missing or unsafe (%s); finish packaging in the kept worktree %s" % (
                    ", ".join(missing), wt)
            elif stale_owned(job, wt, made_copies, files):    # five r13: a copy that could not be remade never lands
                note = ("not landed: %s could not be made again from its changed inputs (is it open elsewhere?); the "
                        "work is kept at %s" % (", ".join(stale_owned(job, wt, made_copies, files)), wt))
            elif stale_worker:
                note = ("not landed: the check changed what %s is made from, so that copy may be out of date; remake it "
                        "from the current Markdown; the work is kept at %s" % (", ".join(stale_worker), wt))
            elif late:
                fields["unexpected"] = sorted(set(fields["unexpected"]) | set(late))
                note = ("not landed: the check or the coder left changes outside the coder's own files (%s); everything "
                        "is kept at %s" % (refusal_detail(late), wt))
            elif served:
                fields["served_tree_changed"] = served
                note = ("not landed: %s changed during the job outside the landing (%s) - something wrote into it "
                        "directly; check those files; the work is kept at %s" % (job["repo"], ", ".join(served[:8]), wt))
            else:
                job["anchor_copies"] = fields["anchor_copies"] = list(made_copies)    # five r3 #1: ours to remake
                commit_err = _commit_manifest(wt, job, files)
                if commit_err:
                    note, status, error = "not landed: %s; the worktree is kept at %s" % (commit_err, wt), "failed", commit_err
                else:
                    committed_snapshot = handoff.snapshot(job)
                    if not committed_snapshot.get("error"):
                        job["recovery_snapshot"] = fields["recovery_snapshot"] = committed_snapshot
                        phase(job, "reviewing", recovery_snapshot=committed_snapshot,
                              anchor_copies=list(made_copies), copy_prints=dict(job.get("copy_prints") or {}),
                              files=list(files))
                    for _attempt in range(3):   # several jobs per repository: one that lost the race integrates again
                        landed, note, extra = land(job, files)
                        if landed or not extra.get("head_moved"):
                            break
                    fields.update(extra)
                    fields["landed"] = landed
                    left = _unlanded(wt, manifest) if landed else ["not landed"]
                    if landed:                   # a runtime record held back from the commit is kept, never removed
                        left += [p for p in job.get("held_runtime") or [] if (Path(wt) / p).exists() and p not in left]
                    keep = not (landed and extra.get("verified")) or bool(left)
                    if landed and left and left != ["not landed"]:
                        note += "; work the landing did not carry is kept at %s (%s)" % (wt, ", ".join(left[:6]))
    if not fields.get("landed"):                     # the complete preserved inventory, whatever check failed
        fields["unexpected"] = sorted(set(fields.get("unexpected") or [])
                                      | {p + " (ignored by git)" for p in ignored_outputs(wt)})
    served = _locked_served_changes(job)              # on every path: did anything write into the source repository?
    if not served:                                    # an affirmative, attempt-bound clean audit (review r1 #1)
        fields["audit_ok_attempt"] = job.get("attempt", 1)
    if served:
        fields["served_tree_changed"] = served
        if not fields.get("landed"):
            note += ("; ALSO: %s changed during the job outside any landing (%s) - check those files"
                     % (job["repo"], ", ".join(served[:8])))
    if small_missed(job, fields, err, note):
        note += "; small tier missed - start it again at standard with --escalates %s" % job["id"]
    fields["anchor_copies"] = list(made_copies)
    fields["copy_prints"] = dict(job.get("copy_prints") or {})
    fields["recovery_snapshot"] = handoff.snapshot(job)
    # review r3 #2: timed BEFORE the outcome, so no report can go out without it; the job is still "finishing" (durable,
    # recoverable) and the profile is capped at 5 s and never raises
    speed = speed_line(dict(job, **fields), wt)
    done = _transition(cdir, job_id, ("finishing",), status=status, finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                       expect_attempt=job.get("attempt", 1),
                       error=error, land_note=note, kept_worktree=(wt if keep else ""), phase="outcome", phase_at=time.time(),
                       speed=speed, **fields)
    if done is None:
        return
    if not keep and done["status"] != "stopped":
        _cleanup(done, keep_branch=False)
    _report(cdir, done)
    try:
        from steward_cockpit import job_ledger
        job_ledger.nudge_later()                  # round 5: the Campaign steward keeps the books
    except Exception:
        pass


def small_missed(job, fields, err, note):
    """A small-tier job that did not land for a reason in the work itself: its check failed, its reviewer read it and
    did not pass it, its worker failed, or it made nothing. A review seat that failed, a usage limit, a stop or a
    restart is not the tier's miss (round 5 plan, C4)."""
    if not str(job.get("tier") or "").startswith("small") or fields.get("landed") or job.get("status") == "stopped":
        return False
    rec = fields.get("review") or {}
    delta = fields.get("delta_review") or {}
    return bool(fields.get("check_ok") is False or fields.get("integration_check_ok") is False
                or (isinstance(delta, dict) and delta.get("ok") and delta.get("verdict") not in (None, "PASS"))
                or (err and not _LIMIT_WORDS.search(err))
                or (isinstance(rec, dict) and rec.get("ok") and rec.get("verdict") not in (None, "PASS"))
                or note == "nothing changed" or note.startswith("not landed: nothing the coder wrote"))


def speed_line(job, wt):
    """One plain line on where the job's time went (John 2026-10-12: a slide back to minutes shows the same day):
    the whole job, the worker's own share from its session logs (the Foundry time-profile tool), and the rest - check,
    review, landing. Also appended to <jobs>/speed.jsonl. Never raises and never holds the job up long."""
    try:
        from steward_cockpit import foundry_tools
        now = time.time()
        born = job.get("worker_birth") or 0
        ended = job.get("worker_completed_at") or now
        total = (now - born) / 60 if born else None
        worker, line, helpers = None, "", []
        tool = foundry_tools.index_path().parent / "time-profile" / "tool.py"
        if tool.is_file() and born:
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(born - 60))
            r = subprocess.run([sys.executable, str(tool), "--worktree", str(wt), "--since", since, "--json"],
                               capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                prof = json.loads(r.stdout)
                if prof.get("steps"):
                    worker, line, helpers = prof, prof.get("line", ""), prof.get("helpers_written") or []
        parts = []
        refiled = (job.get("claim") or {}).get("at") if job.get("attempts") else None
        if refiled:                   # 2026-10-13 (Book 1 v3 "1043 min in all"): a re-filing is timed from its claim
            parts.append("re-filed: check, review and landing %.0f min" % (max(0.0, now - refiled) / 60))
            total = None
        elif total is not None:
            parts.append("%.0f min in all" % total)
        if born and not refiled:
            parts.append("worker %.0f min" % ((ended - born) / 60))
            parts.append("check, review and landing %.0f min" % (max(0.0, now - ended) / 60))
        if line:
            parts.append("worker detail: " + line)
        text = "; ".join(parts) or "no timing recorded"
        try:
            with open(jobs_base() / "speed.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"job": job["id"], "attempt": job.get("attempt", 1), "at": now,
                                    "steward_dir": job.get("steward_dir") or "", "refiled": bool(refiled),
                                    "minutes": (round(total, 1) if total is not None else
                                                round(max(0.0, now - refiled) / 60, 1) if refiled else None),
                                    "worker_minutes": round((ended - born) / 60, 1) if born else None,
                                    "steps": (worker or {}).get("steps"), "helpers_written": helpers[:20],
                                    "by_category": (worker or {}).get("by_category"), "line": text}) + "\n")
        except OSError:
            pass
        return text
    except Exception as exc:
        return "timing could not be read (%s)" % str(exc)[:120]


def _unlanded(wt, manifest):
    """What in the worktree would be LOST if it were removed now: any uncommitted or untracked change (a check that
    wrote a file, an edit nobody committed), and any file the coder wrote that git ignores. [] when nothing."""
    left = []
    paths = porcelain_paths(wt)
    if paths is None:
        return ["git status failed"]
    left += paths
    left += [p + " (ignored by git)" for p in ignored_outputs(wt)]
    return left


def audit_clean(job):
    """True only when THIS attempt's end-of-job audit ran to its end and found nothing written into the repository
    from outside - an affirmative mark the finish writes for its own attempt (a snapshot alone proves nothing: it is
    saved before the audit, after an interrupted finish, and for a stopped job)."""
    return (job.get("status") in ("done", "failed") and job.get("audit_ok_attempt") == job.get("attempt", 1)
            and not job.get("served_tree_changed"))


def file_hash(repo, path):
    """sha256 of a repository file's bytes now; None when it is not a readable file."""
    try:
        return hashlib.sha256((Path(repo) / path).read_bytes()).hexdigest()
    except OSError:
        return None


def audit_point(job):
    """The repository's HEAD and watched dirty files right now, read under its commit lock - where a re-filing's
    audit starts when the last audit was clean and no coder of this job runs any more. None when unreadable."""
    import git_safety as _gs
    repo = job.get("land_to") or job["repo"]
    with _gs.repo_lock(repo, wait_s=120, who="re-filing audit point for code job " + job["id"]) as held:
        if not held:
            return None
        code, head, _ = _git(job["repo"], "rev-parse", "HEAD")
        dirt = dirty_snapshot(job["repo"])
        if code != 0 or not head or dirt is None:
            return None
        return {"head": head, "dirt": dirt, "at": time.time()}


def _locked_served_changes(job):
    """_served_tree_changes read under the repository's commit lock (2026-10-09, several jobs per repository; fcj r3):
    another job's landing is never seen half-placed. A lock that stays busy is a doubt, so it is reported, never
    passed."""
    import git_safety as _gs
    with _gs.repo_lock(job.get("land_to") or job["repo"], wait_s=600, who="audit for code job " + job["id"]) as held:
        if not held:
            return ["(the repository's commit lock stayed busy, so its changes could not be read cleanly)"]
        return _served_tree_changes(job)


def _served_tree_changes(job):
    """Watched source files new or changed since the job started - uncommitted (the dirty-file comparison, including
    a file dirty at the start and now clean or gone) or COMMITTED since the job's base (consensus C2), except commits a
    verified code-job landing recorded."""
    before = job.get("repo_dirt")
    since = job.get("audit_from")          # a re-filing after a clean audit with the coder proven ended (2026-10-12)
    if isinstance(since, dict) and isinstance(since.get("dirt"), dict) and since.get("head"):
        before = since["dirt"]
    now = dirty_snapshot(job["repo"])
    if before is None:
        return ["(no record of the repository's changes at the start)"]
    if now is None:
        return ["(git could not list the repository's changes)"]
    before = {p: h for p, h in before.items() if watched(p)}
    changed = {p for p, h in now.items() if before.get(p) != h}
    gone = [p for p in before if p not in now]
    if gone:
        cur = dirty_snapshot_paths(job["repo"], gone)
        changed |= {p for p in gone if cur.get(p) != before[p]}
    base = job.get("base")
    if isinstance(since, dict) and isinstance(since.get("dirt"), dict) and since.get("head"):
        base = since["head"]
    if base:
        verified = landed_commits()
        code, out, _ = _git_raw(job["repo"], "-c", "core.quotepath=false", "log", "--format=%x00%H", "--name-only",
                                "--no-renames", "%s..HEAD" % base)
        if code != 0:
            changed.add("(could not read the commits made during the job)")
        else:
            for block in out.split("\x00")[1:]:
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if lines and lines[0] not in verified:
                    changed |= {"%s (committed %s)" % (p, lines[0][:10]) for p in lines[1:] if watched(p)}
    ok = job.get("outside_ok") or {}                  # named at the re-filing, each pinned to its bytes then
    if isinstance(ok, dict) and ok:
        def _path(entry):
            return entry.split(" (committed ", 1)[0]
        changed = {c for c in changed if not (_path(c) in ok and ok[_path(c)]
                                              and file_hash(job["repo"], _path(c)) == ok[_path(c)])}
    return sorted(changed)


def dirty_snapshot_paths(repo, paths):
    """Current content hashes of specific paths ("(gone)" when absent)."""
    out = {}
    for path in paths:
        full = Path(repo) / path
        if full.is_file():
            c, h, _ = _git(repo, "hash-object", "--", path)
            out[path] = h if c == 0 else "?"
        else:
            out[path] = "(gone)"
    return out


def _commit_manifest(wt, job, files):
    """Stage ONLY the coder's own changed paths, by literal path, and commit them on the job's branch."""
    files = _not_runtime(files)
    present = [p for p in files if (Path(wt) / p).exists()]
    gone = [p for p in files if p not in present]
    forced = [p for p in present if p in set(job.get("force_add") or [])]   # declared outputs git ignores
    plain = [p for p in present if p not in forced]
    for group, args in ((plain, ("add",)), (forced, ("add", "-f"))):
        if group:
            code, _, err = _git(wt, "--literal-pathspecs", *args, "--", *group, timeout=600)
            if code != 0:
                return "git add failed: " + err[:250]
    if gone:
        code, _, err = _git(wt, "--literal-pathspecs", "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone, timeout=600)
        if code != 0:
            return "git rm failed: " + err[:250]
    def _staged():
        c, out, e = _git_raw(wt, "-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--no-renames", "-z",
                             timeout=600)
        return (None, e) if c != 0 else ([s for s in out.split("\0") if s.strip()], "")
    staged, err = _staged()
    if staged is None:
        return "git diff failed: " + err[:250]
    held = [s for s in staged if _runtime(s)]
    if held:                                             # W1: kept in the worktree, absent from the commit
        code, _, err = _git(wt, "--literal-pathspecs", "reset", "-q", "--", *held, timeout=600)
        if code != 0:
            return "git reset of runtime records failed: " + err[:250]
        job["held_runtime"] = sorted(set(job.get("held_runtime") or []) | set(held))
        staged, err = _staged()
        if staged is None:
            return "git diff failed: " + err[:250]
        if [s for s in staged if _runtime(s)]:
            return "runtime records are still staged after the reset"
    if staged:
        code, out, err = _git(wt, "commit", "-q", "-m", "Code job %s for the steward\n\n%s" % (job["id"], job["brief"][:600]),
                              timeout=600)
        if code != 0:
            return "git commit failed: " + (err or out)[:250]
    return ""


def _stop_asked(job, *, on_error=None):
    try:
        current = read_jobs(job.get("steward_dir") or "", strict=True).get(job["id"])
    except Exception as exc:
        if on_error:
            on_error("job ownership could not be read: " + str(exc)[:200])
        return False  # lost visibility is not a Stop instruction
    if not isinstance(current, dict) or not current.get("status"):
        if on_error:
            on_error("job ownership is unavailable; no Stop is established")
        return False
    return bool(current.get("stop_requested") or current.get("status") not in LIVE
                or current.get("attempt", 1) != job.get("attempt", 1))


def land(job, files):
    """Bring the job's branch up to the repository's current HEAD inside the job's OWN worktree, review the candidate
    (and, when integration changed it, the delta), re-run the check there, then - under the repository's commit lock,
    with HEAD unchanged - place only the job's own files with git_safety.land_locked and verify each placed file.
    Returns (landed, note, fields)."""
    import git_safety as _gs
    wt = job["worktree"]
    # The landing target - the lander's checkout of anchor-next for an installed skill repository (named at the job's
    # start and checked again here), else the repository itself. The running Anchor is refused by land_locked.
    repo = job.get("land_to") or job["repo"]
    fields = {"verified": False}
    why = destination_error(job["repo"]) or integration_required_error(job) or scope_error(job, wt, files)
    if why:
        return False, "not landed: " + why, fields
    if job.get("land_to"):
        import anchor_next
        with _gs.repo_lock(job["repo"], wait_s=600, who="code job " + job["id"]) as held:   # fcj r4: never half-placed
            if not held:
                fields["head_moved"] = True
                return False, "not landed: the repository's commit lock stayed busy; the work is kept at %s" % wt, fields
            ip, why = anchor_next.ensure_integration(job["repo"])
        if ip is None or os.path.normcase(str(ip)) != os.path.normcase(str(job["land_to"])):
            return False, "not landed: %s; the work is kept at %s" % (why or "the lander's checkout moved", wt), fields
    code, cand, _ = _git(wt, "rev-parse", "HEAD")
    if code != 0:
        return False, "not landed: could not read the candidate; the work is kept at %s" % wt, fields
    if _stop_asked(job):
        return False, "not landed: John asked to stop it; the work is kept at %s" % wt, fields
    phase(job, "reviewing")
    rec = run_review(job, wt, cand)           # W2 (2026-10-08): every job is reviewed by another family, documents too
    fields["review"] = rec
    why = review_blocks(job, rec, wt, cand)
    if why:
        return False, "not landed: %s; the work is kept at %s" % (why, wt), fields
    code, head, err = _git(repo, "rev-parse", "HEAD")
    if code != 0:
        return False, "not landed: could not read %s HEAD (%s)" % (repo, err[:120]), fields
    code, _, _ = _git(wt, "merge-base", "--is-ancestor", head, cand)
    if code != 0:                                          # newer commits in the repository: integrate in the job's tree
        phase(job, "integrating")
        if not any(f == ".ecgberht" or f.startswith(".ecgberht/") for f in (files or [])):
            _git(wt, "checkout", "--", ".ecgberht")
        code, _, _ = _git(wt, "merge", "--no-edit", "--no-overwrite-ignore", head, timeout=600)
        if code != 0:
            _git(wt, "merge", "--abort")
            return False, "not landed: the work conflicts with newer changes in %s; it is kept at %s" % (repo, wt), fields
        code, merged, _ = _git(wt, "rev-parse", "HEAD")
        remade, why = _remake_after_integration(job, wt, cand, merged, files)
        if why:
            return False, "not landed: %s; the work is kept at %s" % (why, wt), fields
        if remade:
            code, merged, _ = _git(wt, "rev-parse", "HEAD")
        from steward_cockpit import code_job_handoff as handoff
        # Pair the upstream comparison boundary with the exact integrated tree
        # before another command can change it. Preserve it on later failures.
        job["integrated_base"] = head
        integrated_snapshot = handoff.snapshot(job)
        fields.update(integrated_base=head, recovery_snapshot=integrated_snapshot)
        try:
            saved = not integrated_snapshot.get("error") and phase(job, "checking", integrated_base=head,
                                                                    recovery_snapshot=integrated_snapshot,
                                                                    anchor_copies=list(job.get("anchor_copies") or []),
                                                                    copy_prints=dict(job.get("copy_prints") or {}))
        except Exception:
            saved = False  # the terminal write still carries this exact pair; never run an unrecorded check
        if not saved:
            return False, "not landed: the integrated recovery snapshot could not be saved; work is kept at " + wt, fields
        before = worker_copy_prints(job, wt, job.get("anchor_copies") or [])
        ok, out = run_check(job, wt)
        fields["integration_check_ok"] = ok is True        # final review 10-10: the stage line reads the final gate
        if ok is not True:                                 # a missing check is a failure too (W1a)
            return False, "not landed: the check did not pass after bringing in newer changes; the work is kept at %s" % wt, fields
        # five r10: the check just run may have redrawn a figure Anchor's copies are made from - those copies are made
        # again from the final bytes and committed, so the delta review below sees exactly what lands
        stale_worker = stale_worker_copies(job, wt, before)
        if stale_worker:                                   # five r11 #1: never overwritten, never delivered stale
            return False, ("not landed: the check after integration changed what %s is made from, so that copy may be "
                           "out of date; the work is kept at %s" % (", ".join(stale_worker), wt)), fields
        redrawn, why = _refresh_owned_copies(job, wt, files)
        if why:
            return False, "not landed: %s; the work is kept at %s" % (why, wt), fields
        if redrawn:
            files = list(files) + [n for n in redrawn if n not in set(files)]   # declared outputs: they land too
            code, merged, _ = _git(wt, "rev-parse", "HEAD")
            integrated_snapshot = handoff.snapshot(job)
            if integrated_snapshot.get("error") or not phase(job, "checking", recovery_snapshot=integrated_snapshot,
                                                             copy_prints=dict(job.get("copy_prints") or {})):
                return False, "not landed: the refreshed snapshot could not be saved; work is kept at " + wt, fields
            fields.update(recovery_snapshot=integrated_snapshot)
        missing = missing_reading_outputs(job, wt)
        if missing:
            fields.update(integration_check_ok=False, missing_outputs=missing)
            return False, "not landed: declared reading outputs missing or unsafe after integration: " + ", ".join(missing), fields
        if _stop_asked(job):
            return False, "not landed: John asked to stop it; the work is kept at %s" % wt, fields
        phase(job, "reviewing")
        delta = run_review(job, wt, merged, delta_from=cand)
        fields["delta_review"] = delta
        why = review_blocks(job, delta, wt, merged)
        if why:
            return False, "not landed (after integration): %s; the work is kept at %s" % (why, wt), fields
        cand = merged
    code2, names, _ = _git_raw(wt, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", head, cand)
    land_files = [n for n in names.split("\0") if n.strip()]
    if code2 != 0 or not land_files:
        return False, "not landed: nothing changed beyond what %s already has" % repo, fields
    stray = [n for n in land_files if n not in set(files)]
    if stray:
        return False, "not landed: the candidate would place paths outside the job's own files (%s); kept at %s" % (
            ", ".join(stray[:8]), wt), fields
    phase(job, "landing")
    with _gs.repo_lock(job["repo"], wait_s=300, who="code job " + job["id"]) as held:
        if not held:
            return False, "not landed: the repository's commit lock is busy; the work is kept at %s" % wt, fields
        current = read_jobs(job.get("steward_dir") or "").get(job["id"]) or {}
        why = destination_error(job["repo"]) or scope_error(job, wt, land_files)
        if why or current.get("attempt", 1) != job.get("attempt", 1):
            return False, "not landed: " + (why or "the job attempt changed"), fields
        if current.get("stop_requested"):              # his Stop, honoured under the same lock placement holds
            return False, "not landed: %s asked to stop it; the work is kept at %s" % (
                current.get("stop_requested_by") or "John", wt), fields
        if current.get("status") != "finishing":       # a stop released it while it was being reviewed: no landing
            return False, "not landed: the job was stopped (%s) before placement; the work is kept at %s" % (
                current.get("stopped_by") or current.get("status") or "unknown", wt), fields
        code_h, now_head, _ = _git(wt, "rev-parse", "HEAD")
        if code_h != 0 or now_head != cand:           # something committed after the review: never place an older candidate
            return False, ("not landed: the job's branch moved after review (%s, reviewed %s); everything is kept at %s"
                           % (now_head[:12], cand[:12], wt)), fields
        left = _not_runtime(_unlanded(wt, files))      # a second check after integration made nothing extra (W1: runtime records aside)
        # ignored scratch nobody declared - named at the finish or made since (a repeated check) - stays behind in the
        # kept worktree; the cleanup inventory after placement still lists it, so the worktree is kept (review r1 #2)
        tag = " (ignored by git)"
        mine = set(job.get("outputs") or []) | set(files)
        def _scratch(p):                               # an unreadable listing is never scratch (review r2 #3)
            return p.endswith(tag) and not p.startswith("(") and p[:-len(tag)] not in mine
        late_scratch = [p[:-len(tag)] for p in left if _scratch(p)]
        if late_scratch:
            job["scratch_kept"] = sorted(set(job.get("scratch_kept") or []) | set(late_scratch))
            fields["scratch_kept"] = job["scratch_kept"]
        left = [p for p in left if not _scratch(p)]
        if left:
            fields["unexpected"] = sorted(set(fields.get("unexpected") or []) | set(left))
            return False, ("not landed: changes outside the coder's own files appeared before placement (%s); "
                           "everything is kept at %s" % (refusal_detail(left), wt)), fields
        served_now = _served_tree_changes(job)
        if served_now:
            fields["served_tree_changed"] = served_now
            return False, ("not landed: %s changed during the job outside the landing (%s); the work is kept at %s"
                           % (repo, ", ".join(served_now[:8]), wt)), fields
        code, now, _ = _git(repo, "rev-parse", "HEAD")
        if code != 0 or now != head:
            fields["head_moved"] = True                 # another landing came first: _finish integrates and tries again
            return False, "not landed: %s moved during the review; the work is kept at %s - start the landing again" % (
                repo, wt), fields
        if job.get("land_to"):
            import anchor_next
            ip, why = anchor_next.ensure_integration(job["repo"])
            if (ip is None or os.path.normcase(str(ip)) != os.path.normcase(str(job["land_to"]))
                    or anchor_next.common_dir(repo) != anchor_next.common_dir(job["repo"])):
                return False, "not landed: %s; the work is kept at %s" % (
                    why or "the integration checkout changed identity during review", wt), fields
        landed, note = _gs.land_locked(repo, cand, land_files, "Code job %s for the steward\n\n%s" % (
            job["id"], job["brief"][:600]), who="code job " + job["id"], expect_head=head)
        bad = []
        if landed:                                      # recorded before the lock goes: a stop can no longer release it
            _transition(job.get("steward_dir") or "", job["id"], ("finishing",), expect_attempt=job.get("attempt", 1), placed=True)
            c, out, _ = _git(repo, "rev-parse", "HEAD")  # the landing commit itself: read while nothing else can commit
            fields["landed_commit"] = out.strip() if c == 0 else ""
            # the placed tree is the reviewed one for every path the job touched - additions, edits AND deletions -
            # verified and recorded UNDER the lock (2026-10-09, several jobs per repository: the next landing never
            # sees this commit before it is known to be a verified code-job landing)
            code, diff, _ = _git_raw(repo, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z",
                                     fields["landed_commit"] or "HEAD", cand, "--", *land_files)
            bad = [n for n in diff.split("\0") if n.strip()] if code == 0 else ["(could not compare)"]
            if not bad:
                fields["verified"] = True
                if fields.get("landed_commit"):
                    record_landed_commit(fields["landed_commit"])     # only a verified landing's own commit is exempt
    if not landed:
        return False, note + "; the work is kept at %s" % wt, fields
    tail = ""
    if job.get("installed_repo"):                   # landed is not installed: the human's activation is the only way
        import anchor_next
        tail = "; " + anchor_next.installed_note(job["repo"], repo)
    if bad:
        return True, "landed, but %d placed file(s) differ from the candidate (%s); the worktree is kept at %s%s" % (
            len(bad), ", ".join(bad[:8]), wt, tail), fields
    return True, note + tail, fields


def _cleanup(job, keep_branch=True):
    """The worktree goes; the branch goes only when there is nothing on it worth keeping."""
    try:
        _git(job["repo"], "worktree", "remove", "--force", job["worktree"], timeout=300)
        if not keep_branch:
            _git(job["repo"], "branch", "-D", job["branch"])
    except Exception:
        pass


def live_state(job):
    """'live' | 'waits for a restart' | '' (not an Anchor landing, or unknown) - OBSERVED (two-lane step 6, 2026-10-05):
    the running build (ANCHOR_RUNNING_HEAD, set by the server at start) contains the commit the job landed."""
    if not job.get("landed"):
        return ""
    try:
        here = Path(__file__).resolve().parents[1]
        if Path(str(job.get("repo") or "")).resolve() != here:
            return ""
    except Exception:
        return ""
    running, landed = os.environ.get("ANCHOR_RUNNING_HEAD", ""), str(job.get("landed_commit") or "")
    if not running or not landed:
        return "waits for a restart"
    c, _, _ = _git(str(here), "merge-base", "--is-ancestor", landed, running)
    return "live" if c == 0 else "waits for a restart"


def stage_line(job):
    """W4 (2026-10-10): what John reads about a code job - the stages it reached, in order, stopping at the first
    one it did not: made, checked, reviewed, landed, then waits for restart or live. The stored status stays
    done/failed (the one-writer lock depends on it); this line is derived from the record's own evidence. A job that
    ran a SKILL (--skill) gets no coding stages - only whether it finished (review r1). "Reviewed" counts only when
    the FINAL candidate passed: an integration recheck (delta_review) that did not pass is said."""
    if not isinstance(job, dict):
        return ""
    if job.get("status") == "stopped":
        return "stopped; saved work retained"
    if job.get("status") in LIVE:
        return "%s%s" % ((str(job.get("skill")) + ": ") if job.get("skill") else "",
                         job.get("phase") or ("producing" if job.get("status") == "running" else "finishing"))
    out = []
    if not (job.get("files") or job.get("manifest")):
        return "nothing made"
    out.append("made")
    if job.get("check"):
        if job.get("check_ok") is True:
            out.append("checked")
        else:
            return " → ".join(out + ["check failed" if job.get("check_ok") is False else "not checked"])
    else:
        out.append("no check")
    review = job.get("review") if isinstance(job.get("review"), dict) else {}
    verdict = str(review.get("verdict") or "").upper()
    if verdict:
        if not verdict.startswith("PASS"):
            return " → ".join(out + ["review blocked (%s)" % verdict.lower()])
        if job.get("integration_check_ok") is False:
            return " \u2192 ".join(out + ["reviewed", "integration check failed"])
        delta = job.get("delta_review") if isinstance(job.get("delta_review"), dict) else None
        dverdict = str((delta or {}).get("verdict") or "").upper()
        if delta is not None and not dverdict.startswith("PASS"):
            return " → ".join(out + ["integration review blocked (%s)" % (dverdict.lower() or "no verdict")])
        out.append("reviewed")
    if not job.get("landed"):
        return " → ".join(out + ["not landed"])
    out.append("landed")
    if job.get("installed_repo"):                    # an installed skill repository: landed on anchor-next, not installed
        out.append("not installed (awaits a human activation)")
    state = live_state(job)
    if state:
        out.append("waits for restart" if state.startswith("waits") else state)
    return " → ".join(out)


def live_note(job):
    """Landed is not live (his word, 2026-10-05: a tile repair 'landed with all 20 checks passing' and nothing on his
    screen changed - the running Anchor still had the old code and his page the old stylesheet). For a job landed in the
    repository the Anchor service runs from, the one sentence the steward must carry: it waits for a restart."""
    if live_state(job) != "waits for a restart":
        return ""
    return ("NOT LIVE YET: this landed in Anchor's repository, but John's screen runs the build that was started before "
            "it - the change shows only after Anchor restarts (an Anchor restart is John's word, or his standing "
            "'restart when idle'). Tell him it is landed and waits for a restart; never call it installed, live or done "
            "on his screen until the running build carries it.")


def installed_note(job):
    """For a job landed in an INSTALLED skill repository (2026-10-10): landed is not installed. The installed skill
    keeps running its checked-out code until a human activates anchor-next there; the steward must never say
    installed, live or active before that."""
    if not (job.get("landed") and job.get("installed_repo")):
        return ""
    try:
        import anchor_next
        branch = anchor_next.BRANCH
    except Exception:
        branch = "anchor-next"
    return ("NOT INSTALLED: this landed on %s in the lander's checkout (%s), not in %s - the installed skill still runs "
            "its checked-out code. Activation is a human step (python anchor_next.py activate \"%s\"); tell John it is "
            "landed to integration and awaits his activation, and never call it installed, live or active until he has "
            "activated it." % (branch, job.get("land_to") or "the integration checkout", job["repo"], job["repo"]))


def _report(cdir, job, *, notify_result=True):
    """Materialize the saved terminal outcome once, then optionally notify its steward."""
    from steward_cockpit import code_job_handoff as handoff
    with handoff._handoff_lock(cdir, job["id"]):
        current = handoff.owned_job(cdir, job["id"])
        if (not current or current.get("status") in LIVE
                or current.get("attempt", 1) != job.get("attempt", 1)):
            return None
        receipt = current.get("handoff") or {}
        if not receipt.get("id"):
            try:
                receipt = _materialize_report(cdir, current)
            except Exception as exc:
                with _LOCK:
                    latest = handoff.owned_job(cdir, job["id"])
                    if (latest and latest.get("attempt", 1) == job.get("attempt", 1)
                            and latest.get("status") not in LIVE and not (latest.get("handoff") or {}).get("id")):
                        _transition(cdir, job["id"], (latest["status"],), expect_attempt=job.get("attempt", 1),
                            handoff={"state": "needs_report", "attempt": job.get("attempt", 1),
                                     "last_try": time.time(), "error": str(exc)[:300]})
                raise
    if receipt and notify_result:
        handoff.notify(cdir, job["id"], wake=True)
    return receipt


def _materialize_report(cdir, job):
    """Render only persisted outcome fields; never re-execute a gate or placement."""
    from steward_cockpit import code_job_handoff as handoff
    lines = ["(code job %s, attempt %s result - not John) Status: %s." % (job["id"], job.get("attempt", 1), job["status"]),
             "Destination: %s; work directory: %s." % (job["repo"], job.get("work_dir") or "repository root")]
    if job.get("error"):
        lines.append("Error: " + job["error"][:300])
    if job.get("files"):
        lines.append("Files: " + ", ".join(job["files"][:20]) + (" and %d more" % (len(job["files"]) - 20) if len(job["files"]) > 20 else ""))
    if job.get("admitted_companions"):
        lines.append("Admitted same-stem companions: " + ", ".join(job["admitted_companions"][:10]))
    if job.get("held_cockpit_records"):
        lines.append("Held cockpit ledger edits (preserved in .anchor/held-records/): " + ", ".join(job["held_cockpit_records"][:10]))
    if job.get("check"):
        lines.append("Check: %s." % handoff.check_state(job).replace("_", " ") + ((" Output tail: " + job.get("check_output", "")[-400:]) if job.get("check_ok") is False else ""))
    lines.append("Landing: " + job.get("land_note", ""))
    if job.get("size") == "small" or job.get("escalates"):
        lines.append("Tier: %s%s%s." % (job.get("tier") or "standard",
                                         ("; model served " + job["model_served"]) if job.get("model_served") else "",
                                         ("; redo of small job " + job["escalates"]) if job.get("escalates") else ""))
    if job.get("speed"):
        lines.append("Time: " + job["speed"] + " (a worker that wrote helper scripts by hand is a Foundry tool candidate)")
    lines.append("Stage: " + stage_line(job) + " (say the job's state in these words)")
    if job.get("landed"):
        products = handoff.products(job)
        job["products"] = products
        links = ["[%s](%s)" % (Path(p["path"]).name.replace("[", "\\["), p["href"]) for p in products if p.get("href")]
        if links:
            lines.append("Landed reading outputs: " + ", ".join(links[:6]))
        try:
            import deliverables_register as _dr
            cdir_p = Path(cdir).resolve()
            repo_p = Path(job.get("repo") or cdir).resolve()
            rich_stems = {
                _doc_stem_key(str(p.get("path") or ""))
                for p in products
                if Path(str(p.get("path") or "")).suffix.lower() in (".docx", ".pdf", ".html", ".htm")
            }
            for p in products:
                rel_p = str(p.get("path") or "")
                if not rel_p or not is_document(rel_p):
                    continue
                if re.search(r"(?:_source|-source)\.md$", rel_p, re.I) and _doc_stem_key(rel_p) in rich_stems:
                    continue
                abs_p = (repo_p / rel_p).resolve()
                if abs_p.is_file() and (abs_p == cdir_p or abs_p.is_relative_to(cdir_p)):
                    effort_rel = str(abs_p.relative_to(cdir_p)).replace(chr(92), "/")
                    _dr.register(cdir_p, "START HERE \u2014 " + abs_p.name + " (code job " + str(job.get("id") or "") + ")", effort_rel)
            from steward_cockpit import steward_campaign as _sc
            _sc.sync_steward_projections(cdir_p)
        except Exception:
            pass
        lines.append("Landing is verified placement, not managed publication or human acceptance; register the reading products through their owning effort's existing writer.")
    kept = job.get("kept_worktree") and (job.get("files") or job.get("unexpected")) and not job.get("landed")
    if kept:
        lines.append("Saved work: %s. Collect/inspect returns reading-copy links and any delivery errors; kept copies are not landed or accepted." % job["kept_worktree"])
    live = live_note(job)
    if live:
        lines.append(live)
    installed = installed_note(job)
    if installed:
        lines.append(installed)
    lines.append("The coder's summary: " + (job.get("summary") or "(none)"))
    lines.append("Collect this original job's CURRENT result before acting (steward_code_job.py collect --job %s). "
                 "A later attempt supersedes an earlier result. Reconcile prior delivery; never start another worker "
                 "because this notice repeats. For unchanged kept work, inspect/recover this original job instead of "
                 "rebuilding. Report briefly, preserve pending human decisions, and continue independent authorized work. "
                 "Give John a concise 2-3 sentence summary of what this run accomplished, followed by organized clickable "
                 "links to the key deliverables grouped by topic/step (never an unorganized wall of links)." % job["id"])
    receipt = handoff.save_result(cdir, job, "\n".join(lines))
    if receipt:
        if kept:
            # Even a copy/registrar failure cannot erase the controller's already durable result.
            try:
                announce_kept(cdir, job)
            except Exception as exc:
                _transition(cdir, job["id"], (job["status"],), expect_attempt=job.get("attempt", 1), kept_delivery={
                    "errors": [{"reason": str(exc)[:300]}], "recovery": "saved work remains in " + job["kept_worktree"]})
    return receipt


def reading_outputs(job):
    """Only explicitly declared reading products grant the worker a document assignment."""
    return list(dict.fromkeys(p for p in job.get("outputs") or [] if isinstance(p, str) and is_document(p)))


def _output_path(root, name):
    """A plain relative path, contained after resolving Windows links as well as POSIX links."""
    name = str(name).replace(chr(92), "/")
    if (not name or name.startswith("/") or ":" in name or any(ord(c) < 32 for c in name)
            or any(p in ("", ".", "..") for p in name.split("/"))):
        raise ValueError("unsafe output path")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("output link escapes its root")
    return path


READING_COPY_TOOL = Path(__file__).resolve().parent.parent / "tools" / "reading_copy.py"


def _make_reading_copies(job, tree, refresh=None):
    """A declared PDF, HTML, or DOCX reading copy the coder did not make is made here, in seconds, from the declared or
    written Markdown of the same name beside it (John 2026-10-12: workers spent 16-19 minutes writing renderers).
    ``refresh``: copies made earlier in this finish - remade when their Markdown changed since (review r5); a copy
    anyone else made is never touched. Never raises; returns the outputs made."""
    made = []
    for name in job.get("outputs") or []:
        suffix = Path(name).suffix.lower()
        if suffix not in (".pdf", ".html", ".htm", ".docx"):
            continue
        try:
            target = _output_path(tree, name)
            source = target.with_suffix(".md")
            md_rel = str(Path(name).with_suffix(".md")).replace(chr(92), "/")
            if not source.is_file() and suffix == ".docx":
                alt = target.with_name(target.stem + "_source.md")
                if alt.is_file():
                    source = alt
                    md_rel = str(Path(name).with_name(Path(name).stem + "_source.md")).replace(chr(92), "/")
            printed = (job.get("copy_prints") or {}).get(name)
            if (refresh and name in refresh and target.is_file() and not target.is_symlink() and source.is_file()
                    and (inputs_print(tree, md_rel) != printed if printed      # five r7: the inputs' bytes decide
                         else _newest_input(source, target, tree) > target.stat().st_mtime)):
                target.unlink()                          # ours, and stale: made again below
                refresh.remove(name)
            if inherited_stale(job, tree, name, target, source):
                target.unlink()                          # the base's copy of an older Markdown: made again below
            # review r1: never through a link, never from (or to) outside the job's tree, never over a file
            if (target.exists() or target.is_symlink() or not source.is_file() or source.is_symlink()
                    or not inside(str(source.resolve()), str(Path(tree).resolve()))
                    or not inside(str(target.parent.resolve()), str(Path(tree).resolve()))):
                continue
            args = [sys.executable, str(READING_COPY_TOOL), str(source)]
            if suffix == ".pdf":
                args += ["--out", str(target)]
            elif suffix == ".docx":
                args += ["--no-pdf", "--docx", str(target)]
            else:
                args += ["--no-pdf", "--html", str(target)]
            r = subprocess.run(args, capture_output=True, text=True, timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and target.is_file():
                made.append(name)
                job.setdefault("copy_prints", {})[name] = inputs_print(tree, md_rel)
                if refresh is not None and name not in refresh:
                    refresh.append(name)
        except Exception:
            continue
    return made


def stale_owned(job, wt, ours, files):
    """Declared reading copies that would land or stay stale (five r13/r14): Anchor's own copies whose inputs no
    longer match the fingerprint of their last render, and any declared copy still identical to the base's while what
    it is made from changed (a locked file that could not be made again)."""
    prints = job.get("copy_prints") or {}
    out = [n for n in ours if n in prints            # five r16: every owned copy, changed in the job or not
           and inputs_print(wt, str(Path(n).with_suffix(".md")).replace(chr(92), "/")) != prints[n]]
    for n in job.get("outputs") or []:
        if n in out or Path(n).suffix.lower() not in (".pdf", ".html", ".htm"):
            continue
        if n in ours and n in prints:                 # five r15: made by Anchor from these very inputs - fresh, even
            continue                                  # when byte-identical to the base's copy
        try:
            target = _output_path(wt, n)
            if inherited_stale(job, wt, n, target, target.with_suffix(".md")):
                out.append(n)
        except (OSError, ValueError):
            continue
    return out


def worker_copy_prints(job, wt, ours):
    """Fingerprints of the inputs of every declared reading copy the WORKER made (not Anchor), taken before a check -
    so a check that changes what such a copy is made from is caught (five r11 #1). Never raises."""
    out = {}
    for name in job.get("outputs") or []:
        try:
            if Path(name).suffix.lower() in (".pdf", ".html", ".htm") and name not in set(ours) \
                    and _output_path(wt, name).is_file():
                out[name] = inputs_print(wt, str(Path(name).with_suffix(".md")).replace(chr(92), "/"))
        except (OSError, ValueError):
            continue
    return out


def stale_worker_copies(job, wt, before):
    return [n for n, p in (before or {}).items()
            if inputs_print(wt, str(Path(n).with_suffix(".md")).replace(chr(92), "/")) != p]


def _refresh_owned_copies(job, wt, files):
    """Anchor's own landing copies whose inputs' bytes differ from their last render are made again and committed.
    Returns (paths remade, why not)."""
    stale = []
    for name in job.get("anchor_copies") or []:      # five r16: every owned copy, changed in the job or not
        md = str(Path(name).with_suffix(".md")).replace(chr(92), "/")
        if inputs_print(wt, md) != (job.get("copy_prints") or {}).get(name):
            stale.append(name)
    if not stale:
        return [], None
    for name in stale:
        try:
            _output_path(wt, name).unlink()
        except (OSError, ValueError) as e:
            return [], "%s could not be made again (%s)" % (name, e)
    made = _make_reading_copies(job, wt)
    lost = [n for n in stale if n not in made]
    if lost:
        return [], "%s could not be made again from the final Markdown" % ", ".join(lost)
    code, _, err = _git(wt, "add", "-f", "--", *stale)
    if code == 0 and _git(wt, "diff", "--cached", "--quiet")[0] == 0:
        return [], None                               # made again, byte for byte the same
    if code == 0:
        code, _, err = _git(wt, "commit", "-q", "-m", "Reading copies made again from final inputs: " + ", ".join(stale))
    if code != 0:
        return [], "the remade reading copies could not be committed (%s)" % err[:160]
    return stale, None


def _remake_after_integration(job, wt, cand, merged, files):
    """Review five r2 #1: newer changes brought in by integration touched the Markdown (or a figure beside it) of a
    reading copy this job delivers, so the copy is made again from the integrated inputs and committed; the check and
    the delta review that follow see it. Returns (paths remade, why not) - a copy that cannot be remade keeps the work."""
    remade = []
    ours = set(job.get("anchor_copies") or [])
    for name in job.get("outputs") or []:
        if Path(name).suffix.lower() not in (".pdf", ".html", ".htm") or name not in set(files):
            continue
        md = str(Path(name).with_suffix(".md")).replace(chr(92), "/")
        inputs = copy_inputs(wt, md)
        code, out, _ = _git(wt, "diff", "--name-only", cand, merged, "--", *inputs)
        if code != 0:
            return [], "the integrated changes to %s could not be read" % md
        if not out.strip():
            continue
        if name not in ours:                          # five r3 #1: the worker's own copy is never overwritten
            return [], ("newer work changed %s after the worker made %s, so that copy may be out of date; remake it "
                        "from the current Markdown" % (", ".join(out.split()[:3]), name))
        try:
            target = _output_path(wt, name)
            if not target.with_suffix(".md").is_file():
                return [], "%s changed in newer work but its Markdown is gone; make the copy again" % name
            target.unlink()
        except (OSError, ValueError) as e:
            return [], "%s could not be made again after integration (%s)" % (name, e)
        if name not in _make_reading_copies(job, wt):     # five r10: the fingerprint is recorded on the job itself
            return [], "%s could not be made again from the integrated Markdown" % name
        remade.append(name)
    if remade:
        code, _, err = _git(wt, "add", "-f", "--", *remade)
        if code == 0 and _git(wt, "diff", "--cached", "--quiet")[0] == 0:
            return [], None                           # five r3 #2: made again, byte for byte the same - nothing to commit
        if code == 0:
            code, _, err = _git(wt, "commit", "-q", "-m", "Reading copies made again after integration: " + ", ".join(remade))
        if code != 0:
            return [], "the remade reading copies could not be committed (%s)" % err[:160]
    return remade, None


def _newest_input(source, target, tree=None):
    """The newest change among a reading copy's inputs - its Markdown and the local images it names - so a check
    that redraws a figure after the first render gets a fresh copy (five r1 #1, r3 #3). The copy itself is left out."""
    newest = source.stat().st_mtime
    if tree is None:
        return newest
    root = Path(tree)
    md = source.resolve().relative_to(root.resolve()).as_posix()
    for rel in copy_inputs(tree, md)[1:]:
        p = root / rel
        try:
            if p.is_file() and not p.is_symlink() and p.resolve() != target.resolve():
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    return newest


def _index_job(job):
    """Round 5 (plan r2 #5): one pointer line per started job, so the ledger finds every job's own record - a job that
    failed before its timing line included. Never raises."""
    try:
        with open(jobs_base() / "jobs-index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"job": job["id"], "steward_dir": job.get("steward_dir") or "", "at": time.time()}) + "\n")
    except Exception:
        pass


def _blob(tree, rev, rel):
    code, out, _ = _git(tree, "rev-parse", "%s:%s" % (rev, rel))
    return out.strip() if code == 0 else None


def inherited_stale(job, tree, name, target, source):
    """2026-10-13 (round 5, plan r1 #6): a declared copy the job inherited unchanged from its base, beside Markdown
    this job changed, is the old version - remade, never delivered stale. A copy the worker changed is its own and is
    never touched; anything unreadable leaves the file alone."""
    try:
        if not target.is_file() or target.is_symlink() or not source.is_file():
            return False
        base = candidate_base(job)
        md = str(Path(name).with_suffix(".md")).replace(chr(92), "/")
        was = _blob(tree, base, name)
        if not was:
            return False
        code, now, _ = _git(tree, "hash-object", "--", str(target))
        if code != 0 or now.strip() != was:
            return False
        # plan r2 #2 / five r3 #3 / r8 #1: the Markdown and every image it names, each compared by its bytes with the
        # base - tracked, untracked or ignored alike
        for rel in copy_inputs(tree, md):
            path = Path(tree) / rel
            now_blob = None
            if path.is_file():
                code, out, _ = _git(tree, "hash-object", "--", str(path))
                if code != 0:
                    return False
                now_blob = out.strip()
            if now_blob != _blob(tree, base, rel):
                return True
        return False
    except Exception:
        return False


_IMAGE_REF = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^)\s]+))(?:\s+[^)]*)?\)|<img[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.I)


def inputs_print(tree, md):
    """One fingerprint of a reading copy's inputs - their paths and bytes - taken when Anchor makes the copy, so a
    check that swaps a figure while keeping its old timestamp still gets a fresh copy (five r7). Never raises."""
    h = hashlib.sha256()
    for rel in copy_inputs(tree, md):
        h.update(rel.encode("utf-8") + b"\0")
        try:
            h.update(hashlib.sha256((Path(tree) / rel).read_bytes()).digest())
        except OSError:
            h.update(b"missing")
    return h.hexdigest()


def _html_unquote(text):
    import html as _html
    import urllib.parse as _up
    return _up.unquote(_html.unescape(text))


def copy_inputs(tree, md):
    """What a reading copy is made from: its Markdown (repository-relative ``md``) and the local images it names -
    ![..](path) and <img src> - resolved beside it and kept inside the tree (five r3 #3: ../assets/chart.png counts).
    Links, data: URIs and anything outside the tree are not inputs. Never raises."""
    out = [md]
    try:
        root = Path(tree).resolve()
        text = (root / md).read_text(encoding="utf-8", errors="replace")
        refs = [m.group(1) or m.group(2) or m.group(3) or "" for m in _IMAGE_REF.finditer(text)]
        try:                                          # five r4 #1: the renderer's own reading of the figures -
            import report_viewer                      # its Markdown parser, then unescaped and %-decoded as
                                                      # tools/reading_copy.py does ("plot one.png", "plot%20one.png")
            page = report_viewer.reader_html(text, title="inputs", katex_url_prefix="")
            refs += re.findall(r'!<a href="([^"]+)" rel="noopener noreferrer">', page)
            refs += re.findall(r'<img[^>]*?src="([^"]+)"', page)
        except Exception:
            pass
        names = []
        for raw in refs:                              # five r5 #2: chart%231.png is the file chart#1.png
            for form in (raw, raw.split("#")[0].split("?")[0]):
                for name in (form, _html_unquote(form)):
                    if name not in names:
                        names.append(name)
        for ref in names:
            if not ref or ":" in ref or ref.startswith(("/", "//")):
                continue
            p = ((root / md).parent / ref).resolve()
            if p.is_relative_to(root) and p != root:
                rel = p.relative_to(root).as_posix()
                if rel not in out:
                    out.append(rel)
    except Exception:
        pass
    return out                                        # five r8 #2: every input, never a cut list


def missing_reading_outputs(job, tree):
    missing = []
    for name in reading_outputs(job):
        try:
            if not _output_path(tree, name).is_file():
                missing.append(name)
        except (OSError, ValueError):
            missing.append(name)
    return missing


def _file_hash(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _copy_kept(src, dst):
    """Atomic, no-clobber publication: partial copying never becomes a reading target."""
    wanted = _file_hash(src)
    if dst.exists():
        if not dst.is_file() or _file_hash(dst) != wanted:
            raise ValueError("different preserved copy exists; both versions kept")
        return wanted
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".kept-", dir=dst.parent)
    os.close(fd)
    try:
        shutil.copy2(src, temp)
        if _file_hash(temp) != wanted:
            raise ValueError("source changed while copying; retry from the preserved worktree")
        try:
            os.link(temp, dst)           # same directory/volume; never replaces an existing target
        except FileExistsError:
            if not dst.is_file() or _file_hash(dst) != wanted:
                raise ValueError("different preserved copy exists; both versions kept")
        return wanted
    finally:
        os.unlink(temp)


def announce_kept(cdir, job):
    """Bounded reading handback, not an evidence sweep. Original work and acceptance stay untouched."""
    from steward_cockpit import steward_engine as _se
    import deliverables_register as _dr
    delivery = {"items": [], "errors": [], "retained_count": 0, "recovery": ""}
    previous = (read_jobs(cdir).get(job["id"]) or job).get("kept_delivery") or {}
    links, readable = [], []
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", str(job["id"])):
            raise ValueError("unsafe job id")
        root = Path(cdir).resolve()
        relative_out = "code-job-outputs/" + job["id"]
        out = _output_path(root, relative_out)
        pid, rel = _dr.project_and_rel(cdir)
        preserved = list(dict.fromkeys(list(job.get("files") or []) + [str(u).removesuffix(" (ignored by git)")
                                      for u in job.get("unexpected") or []]))
        selected = reading_outputs(job)
        if not job.get("outputs"):      # legacy jobs retain a small useful handback
            selected = [p for p in preserved if is_document(p)]
            selected.sort(key=lambda p: (Path(p).suffix.lower() != ".pdf", p))
            selected = selected[:6]
        else:
            selected.sort(key=lambda p: (Path(p).suffix.lower() != ".pdf", p))
        delivery["retained_count"] = len(set(preserved) - set(selected))
        for name in selected:
            try:
                src = _output_path(job["kept_worktree"], name)
                dst = _output_path(out, name)
                # Check from the cockpit too: the job directory itself must not escape through a junction.
                if dst != _output_path(root, relative_out + "/" + name):
                    raise ValueError("preserved output root changed")
                if not src.is_file():
                    raise ValueError("output missing from preserved worktree")
                digest = _copy_kept(src, dst)
                where = relative_out + "/" + name.replace(chr(92), "/")
                item = {"path": name, "where": where, "sha256": digest, "registered": False}
                delivery["items"].append(item)
                old = next((i for i in previous.get("items", []) if i.get("where") == where
                            and i.get("sha256") == digest and i.get("registered")), None)
                from steward_cockpit.steward_campaign import job_noun as _job_noun
                j_noun = _job_noun(job)
                try:
                    registration = {"written": True} if old else _dr.register(
                        cdir, "Supporting - %s %s kept (not landed): %s" % (j_noun[:1].upper() + j_noun[1:], job["id"], Path(name).name), "`%s`" % where, notify=False)
                except Exception as exc:
                    registration = {"reason": str(exc)[:200]}
                item["registered"] = bool(registration.get("written") or registration.get("reason") == "dup")
                if not item["registered"]:
                    delivery["errors"].append({"path": name, "reason": "registration: " + str(registration.get("reason"))})
                target = _dr.reading_target({"path": where}, pid=pid, effort_rel=rel, effort_dir=cdir)
                href = target.get("read") or target.get("download")
                if href:
                    label = Path(name).name.replace("[", "\\[").replace("]", "\\]")
                    links.append(Path(name).name)
                    readable.append("[%s](%s)" % (label, href))
                    item["href"] = href
                else:
                    delivery["errors"].append({"path": name, "reason": "reading target unavailable"})
            except Exception as exc:
                delivery["errors"].append({"path": name, "reason": str(exc)[:240]})
    except Exception as exc:
        delivery["errors"].append({"path": "", "reason": str(exc)[:240]})
    if delivery["errors"]:
        delivery["recovery"] = "%d handback item(s) need recovery; use the kept worktree %s and the job's kept_delivery errors. Do not rerun the worker." % (
            len(delivery["errors"]), job.get("kept_worktree", "(unavailable)"))
    elif delivery["retained_count"]:
        delivery["recovery"] = "%d supporting file(s) remain in %s; the reading copies above are not landed or accepted." % (
            delivery["retained_count"], job.get("kept_worktree", "(unavailable)"))
    from steward_cockpit.steward_campaign import job_noun as _job_noun
    line = "**Anchor** · kept from %s %s (not landed): %s" % (_job_noun(job), job["id"], ", ".join(readable[:6]) or "no reading copy published")
    if len(readable) > 6:
        line += "; %d more reading copies are listed in this job's kept_delivery record" % (len(readable) - 6)
    if delivery["recovery"]:
        line += ". " + delivery["recovery"]
    # A changed partial result must not collide with the history writer's immutable turn ID.
    rid = "receipt:kept:%s:%s" % (job["id"], hashlib.sha256(line.encode("utf-8")).hexdigest()[:16])
    try:
        if previous.get("receipt_id") != rid and _se._default_record(cdir)(line, rid):
            delivery["receipt_id"] = rid
            from steward_cockpit import steward_routes as _sr
            eng = _sr.get_engine(str(cdir), create=False)
            if eng is not None:
                (getattr(eng, "emit_receipt", None) or eng._emit)({"t": "receipt", "text": line, "id": rid})
        elif previous.get("receipt_id") == rid:
            delivery["receipt_id"] = rid
        else:
            delivery["errors"].append({"path": "", "reason": "dialogue receipt not saved"})
    except Exception as exc:
        delivery["errors"].append({"path": "", "reason": "receipt: " + str(exc)[:200]})
    if delivery["errors"]:
        delivery["recovery"] = "%d handback item(s) need recovery; inspect this job's kept_delivery errors. Original work remains at %s; do not rerun the worker." % (
            len(delivery["errors"]), job.get("kept_worktree", "(unavailable)"))
    job["kept_delivery"] = delivery
    try:
        _transition(cdir, job["id"], (job.get("status"),), expect_attempt=job.get("attempt", 1), kept_delivery=delivery)
    except Exception as exc:
        delivery["recovery"] = "Handback record could not be saved (%s); original work remains at %s." % (
            str(exc)[:160], job.get("kept_worktree", "(unavailable)"))
    try:
        from steward_cockpit import steward_campaign as _sc
        _sc.sync_steward_projections(Path(cdir).resolve())
    except Exception:
        pass
    return links


def stopped_record(job, engine=None):
    """What a normal finish saves for a later recovery: who wrote the work, what its tools wrote and a pin of its bytes."""
    from steward_cockpit import code_job_handoff as handoff
    if engine is None and job.get("worker") != "foreman":
        try:                                          # the coder's engine still knows who served it and what it wrote
            from steward_cockpit import steward_routes as sr
            engine = sr.get_engine(job["worktree"], general=True, tid="1", create=False)
        except Exception:
            engine = None
    foreman = job.get("worker") == "foreman"
    authors = [FOREMAN_WRITER] if foreman else (authors_of(engine) if engine is not None else job.get("authors")) or [
        job.get("coder_family")]
    manifest = (foreman_manifest(job) if foreman else manifest_of(engine, job["worktree"]) if engine is not None
                else job.get("manifest") or [])
    job = dict(job, manifest=manifest)
    return {"authors": [a for a in authors if a in FAMILIES], "manifest": job["manifest"],
            "recovery_snapshot": handoff.snapshot(job)}


def stop(cdir, job_id=None, engine_lookup=None, actor="unknown"):
    """Stop the running job (the newest when no id) on behalf of ``actor`` (recorded as said - never assumed to be
    John). Nothing is committed or removed: the worktree is kept exactly as the coder left it."""
    jobs = [j for j in read_jobs(cdir).values() if j.get("status") in LIVE and (not job_id or j["id"] == job_id)]
    if not jobs:
        return {"ok": False, "error": "no code job is running"}
    job = sorted(jobs, key=lambda j: j["started"])[-1]
    who = str(actor or "unknown")
    if job.get("status") == "finishing":
        # Stop is an explicit instruction, not a guessed stale-age release. The controller
        # stops its contained command and retains ownership until the whole tree is gone.
        import git_safety as _gs
        with _gs.repo_lock(job.get("land_to") or job["repo"], wait_s=900,
                           who="stop of code job " + job["id"]) as held:
            if not held:
                return {"ok": False, "error": "the repository is busy landing; try the stop again in a moment"}
            if (read_jobs(cdir).get(job["id"]) or {}).get("placed"):
                return {"ok": False, "error": "too late: it has already landed; its report is on the way"}
            asked = _transition(cdir, job["id"], ("finishing",), expect_attempt=job.get("attempt", 1),
                                stop_requested=time.strftime("%Y-%m-%d %H:%M:%S"), stop_requested_by=who)
        if asked is None:
            return {"ok": False, "error": "the code job finished while the stop was asked; see its result"}
        from steward_cockpit.code_job_handoff import settle_stopped_finalizer
        settled = settle_stopped_finalizer(cdir, asked)
        if settled is not None:
            return {"ok": True, "job": job["id"], "branch": job["branch"],
                    "kept": job["worktree"], "stopped_by": settled["stopped_by"],
                    "note": settled["land_note"]}
        served = _locked_served_changes(job)
        if served:
            _transition(cdir, job["id"], ("finishing",), expect_attempt=job.get("attempt", 1), served_tree_changed=served)
        return {"ok": True, "job": job["id"], "branch": job["branch"], "stop_requested": True,
                "kept": job["worktree"], "served_tree_changed": served,
                "note": "stop recorded; its process tree must end before the claim is released; saved work stays kept"}
    if job.get("worker") == "foreman":
        ended, why = end_foreman(job)
        if not ended:
            return {"ok": False, "error": why}
        _remove_foreman_config(job["worktree"])
    stopped = _transition(cdir, job["id"], ("running",), status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                          stopped_by=who, kept_worktree=job["worktree"],
                          land_note="stopped by %s; nothing landed; the work so far is kept at %s (branch %s)" % (
                              who, job["worktree"], job["branch"]))
    if stopped is None:
        return {"ok": False, "error": "the code job is already finishing; its result is on the way"}
    eng = None
    try:
        eng = engine_lookup(job["worktree"]) if engine_lookup else None
        if eng is not None:
            eng.on_turn_done = None
            eng.stop()
    except Exception:
        pass
    try:                                              # so John can have it finished later, as a normal finish would allow
        _transition(cdir, job["id"], ("stopped",), **stopped_record(stopped, eng))
    except Exception:
        pass
    served = _locked_served_changes(job)              # the finish will not run: audit the source repository here
    if served:
        _transition(cdir, job["id"], ("stopped",), served_tree_changed=served,
                    land_note=stopped["land_note"] + ("; ALSO: %s changed during the job outside any landing (%s) - "
                                                      "check those files" % (job["repo"], ", ".join(served[:8]))))
    return {"ok": True, "job": job["id"], "branch": job["branch"], "kept": job["worktree"], "stopped_by": who,
            "served_tree_changed": served}
