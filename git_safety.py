"""git_safety - nothing automated ever rewrites a shared working tree (Ecgberht/planning/delegated-work-2026-10-04,
PROPOSAL v0.3 Part A, approved by John 2026-10-05; incident: Anchor/journal/2026-10-04-landing-rollback-incident.md).

On 2026-10-04 two code jobs landed with `git merge` in C:\\dev\\Anchor, a working tree shared by the service, several
stewards and Claude Code sessions; each refused merge hard-reset the tree and wiped other sessions' unsaved work.

This module is the whole of the rule's machinery:
  - ``repo_lock(repo)``: ONE commit lock per repository, taken by the lander and by every steward commit path, so no
    commit lands inside a land's check-write-commit window (Grok R2 G1).
  - ``snapshot(repo)``: before any automated git operation, three trees under ``refs/anchor-snapshots/<time>``: the
    working tree (tracked + untracked + the named runtime files), the index (``git write-tree``), and HEAD; restore a
    path with ``restore_path``. Snapshots older than 14 days are pruned.
  - ``destructive_git(command)``: the verbs no agent may run in a shared product tree (merge, checkout, reset, stash,
    rebase, clean, restore, switch) and the working tree a command targets, for the engine's guard (A1).
  - ``land(repo, branch, files, base)``: the safe lander (A2). Each file lands only if it is tracked-and-unchanged
    (index blob == HEAD blob == the clean-filtered worktree hash) or new-and-absent; bytes are copied from the job's
    blob (no text-mode rewrite), written by temp-and-rename, and committed with ``git commit -- <paths>`` so every
    other staged or unstaged change is left alone. Runtime paths never land. Any doubt refuses, with the reason.

Stdlib only; never raises to a caller.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import time
from pathlib import Path

SNAP_PREFIX = "refs/anchor-snapshots/"
SNAP_KEEP_DAYS = 14
LOCK_STALE_S = 3600          # well above the longest git step (600 s); the holder refreshes it
RUNTIME_FILES = ("settings.json", "rnd_registry.json", "steward-cockpit-state.json")
_RUNTIME_RE = re.compile(r"(^|/)(\.ecgberht|\.anchor)(/|$)|(^|/)(settings\.json|rnd_registry\.json|steward-cockpit-state\.json"
                         r"|strip\.json|conversation-log\.json)$", re.I)
DESTRUCTIVE = ("merge", "checkout", "reset", "stash", "rebase", "clean", "restore", "switch", "pull", "am", "cherry-pick")
_GIT_CALL = re.compile(r"\bgit(?:\.exe)?\b((?:\s+(?:-C\s+(?:\"[^\"]+\"|'[^']+'|\S+)|-c\s+\S+|--\S+))*)\s+([a-z][a-z-]*)", re.I)
_C_ARG = re.compile(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(repo, *args, timeout=120, env=None, input_bytes=None):
    """(code, stdout, stderr) as text; never raises."""
    try:
        r = subprocess.run(["git", "--literal-pathspecs", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env,
                           input=input_bytes, creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace").strip(), (r.stderr or b"").decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return 1, "", "git %s timed out after %ss" % (args[0] if args else "", timeout)
    except Exception as e:
        return 1, "", "git could not run: %s" % e


def _git_bytes(repo, *args, timeout=120):
    try:
        r = subprocess.run(["git", "--literal-pathspecs", "-C", str(repo), *args], capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        return r.returncode, r.stdout or b""
    except Exception:
        return 1, b""


def toplevel(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel")
    return os.path.normcase(str(Path(out).resolve())) if code == 0 and out else ""


def is_runtime_path(rel):
    return bool(_RUNTIME_RE.search(str(rel).replace("\\", "/")))


# ---------- the commit lock ----------
def _lock_path(repo):
    """Keyed on the repository's SHARED git directory (W1a, 2026-10-08): the running checkout, the lander's checkout of
    anchor-next and every job worktree of one repository take the one lock; a path that is not a repository keys on
    itself."""
    import paths as _paths
    base = _paths.code_jobs_dir()
    (base / "locks").mkdir(parents=True, exist_ok=True)
    code, common, _ = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=60)
    key = common if code == 0 and common else str(repo)
    try:
        key = str(Path(key).resolve())
    except Exception:
        pass
    return base / "locks" / (hashlib.sha1(os.path.normcase(key).encode()).hexdigest()[:16] + ".lock")


@contextlib.contextmanager
def repo_lock(repo, wait_s=120, who=""):
    """The repository's one commit lock (an exclusive lock file kept alive while held; a holder silent for an hour is
    stale). Yields True when held, False when it could not be had within ``wait_s``: the caller then skips or refuses,
    never proceeds without it (Grok code R1 F7)."""
    import threading
    p = _lock_path(repo)
    deadline = time.time() + wait_s
    fd = None
    while True:
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime > LOCK_STALE_S:
                    p.unlink()
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                yield False
                return
            time.sleep(0.25)
            continue
        except OSError:
            yield False
            return
        try:
            os.write(fd, ("%s %s %s" % (os.getpid(), time.time(), who)).encode())
            break
        except OSError:
            try:
                os.close(fd)
            finally:
                try:
                    p.unlink()
                except OSError:
                    pass
            yield False
            return
    stop = threading.Event()

    def keep_alive():
        while not stop.wait(60):
            try:
                os.utime(str(p), None)
            except OSError:
                pass
    t = threading.Thread(target=keep_alive, daemon=True)
    t.start()
    try:
        yield True
    finally:
        stop.set()
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            p.unlink()
        except Exception:
            pass


# ---------- the snapshot ----------
def snapshot(repo, reason=""):
    """Store the working tree (tracked + untracked + runtime files), the index and HEAD under
    refs/anchor-snapshots/<time>. Returns the ref, or "" when it could not be made (the caller should then refuse)."""
    code, head, _ = _git(repo, "rev-parse", "HEAD")
    if code != 0:
        return ""
    code, index_tree, _ = _git(repo, "write-tree")
    if code != 0:
        return ""
    tmp_index = str(_lock_path(repo)) + ".snapindex"
    env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
    try:
        code = _git(repo, "read-tree", head, env=env)[0]
        if code == 0:
            code = _git(repo, "add", "-A", "--", ".", env=env, timeout=600)[0]
        root = Path(toplevel(repo) or repo)
        extra = [f for f in RUNTIME_FILES if (root / f).exists()]
        if code == 0 and extra:
            code = _git(repo, "add", "-f", "--", *extra, env=env)[0]
        if code == 0:      # every step or no snapshot (Grok code R1 F5): a partial snapshot must not let a land proceed
            code, work_tree, _ = _git(repo, "write-tree", env=env)
    finally:
        try:
            os.remove(tmp_index)
        except Exception:
            pass
    if code != 0:
        return ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    env2 = dict(os.environ, GIT_AUTHOR_NAME="anchor-safety", GIT_AUTHOR_EMAIL="anchor@localhost",
                GIT_COMMITTER_NAME="anchor-safety", GIT_COMMITTER_EMAIL="anchor@localhost")
    code, idx_commit, _ = _git(repo, "commit-tree", index_tree, "-p", head, "-m", "anchor snapshot %s: the index" % stamp, env=env2)
    if code != 0:
        return ""
    code, snap, _ = _git(repo, "commit-tree", work_tree, "-p", head, "-p", idx_commit, "-m",
                         "anchor snapshot %s: the working tree (+untracked, runtime) | %s" % (stamp, reason[:200]), env=env2)
    if code != 0:
        return ""
    ref = SNAP_PREFIX + stamp + "-" + snap[:6]
    code, _, _ = _git(repo, "update-ref", ref, snap)
    if code != 0:
        return ""
    prune(repo)
    return ref


def list_snapshots(repo):
    code, out, _ = _git(repo, "for-each-ref", "--sort=-refname", "--format=%(refname) %(objectname) %(subject)", SNAP_PREFIX)
    return [ln.split(" ", 2) for ln in out.splitlines()] if code == 0 and out else []


def prune(repo, keep_days=SNAP_KEEP_DAYS):
    cutoff = time.strftime("%Y%m%d", time.localtime(time.time() - keep_days * 86400))
    for ref, _, _ in list_snapshots(repo):
        if ref[len(SNAP_PREFIX):len(SNAP_PREFIX) + 8] < cutoff:
            _git(repo, "update-ref", "-d", ref)


def restore_path(repo, ref, rel, from_index=False):
    """Write one path back from a snapshot (the working-tree tree, or its index tree) into the working tree; returns
    True when written. The caller decides what to restore; nothing else is touched."""
    obj = (ref + "^2:" if from_index else ref + ":") + str(rel).replace("\\", "/")
    code, data = _git_bytes(repo, "cat-file", "blob", obj)
    if code != 0:
        return False
    dest = Path(toplevel(repo) or repo) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".restore-tmp")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(dest))
    return True


# ---------- the guard's view of a command ----------
def destructive_git(command, cwd):
    """[(verb, target_dir)] for every destructive git verb in ``command`` (a shell line or a JSON-ish tool input)."""
    out = []
    for m in _GIT_CALL.finditer(str(command or "")):
        opts, verb = m.group(1) or "", m.group(2).lower()
        if verb not in DESTRUCTIVE:
            continue
        c = _C_ARG.search(opts)
        target = c.group(1).strip("\"'") if c else cwd
        out.append((verb, target))
    return out


def shared_product_tree(target, own_dir, jobs_base_dir=""):
    """A tree other sessions write: anything but this agent's own cockpit repo (a cockpit that is its own git root) and
    a job's own worktree. A cockpit inside a product repository (its toplevel is the product's) is NOT exempt."""
    top = toplevel(target) if target else ""
    if not top:
        return False
    if jobs_base_dir and top.startswith(os.path.normcase(str(Path(jobs_base_dir).resolve()))):
        return False
    own = os.path.normcase(str(Path(own_dir).resolve())) if own_dir else ""
    return top != own


# ---------- the safe lander ----------
def _blob_at(repo, rev, rel):
    code, out, _ = _git(repo, "rev-parse", "--verify", "-q", "%s:%s" % (rev, rel))   # bare rev-parse echoes an unknown glob-like arg with exit 0
    return out if code == 0 else ""


def _index_blob(repo, rel):
    code, out, _ = _git(repo, "ls-files", "-s", "--", rel)
    return out.split()[1] if code == 0 and out else ""


def _worktree_hash(repo, rel):
    code, out, _ = _git(repo, "hash-object", "--path=" + str(rel), "--", rel)
    return out if code == 0 else ""


def _untracked(repo, rel):
    code, out, _ = _git(repo, "ls-files", "--others", "--", rel)
    return bool(out.strip())


def tracked_runtime(repo):
    code, out, _ = _git(repo, "ls-files", "--", *RUNTIME_FILES)
    return [ln for ln in out.splitlines() if ln.strip()] if code == 0 else list(RUNTIME_FILES)


def _status_clean(repo, rel):
    code, out, _ = _git(repo, "status", "--porcelain", "--", rel)
    return code == 0 and not out.strip()


def land(repo, source_rev, files, message, who="code job", expect_head=""):
    """Take the repository's commit lock and land (see land_locked)."""
    with repo_lock(repo, wait_s=180, who=who) as held:
        if not held:
            return False, "not landed: the repository's commit lock is busy; try again shortly"
        return land_locked(repo, source_rev, files, message, who=who, expect_head=expect_head)


def _commit_blobs(repo, source_rev, plan, message, head):
    """Commit ``plan``'s files exactly as they are at ``source_rev`` on top of ``head``: a private index read from
    ``head``, the job's blobs placed by hash, and the branch moved by compare-and-swap from ``head`` (raises)."""
    _, gitdir, _ = _git(repo, "rev-parse", "--absolute-git-dir")
    idx = os.path.join(gitdir or str(repo), "anchor-land-%d-%d.index" % (os.getpid(), int(time.time() * 1000)))
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        code, _, err = _git(repo, "read-tree", head, env=env)
        if code != 0:
            raise RuntimeError("could not read HEAD's tree: " + err[:200])
        for f, src, _ in plan:
            if src:
                _, line, _ = _git(repo, "ls-tree", source_rev, "--", f)
                mode = line.split()[0] if line else "100644"
                code, _, err = _git(repo, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, src, f), env=env)
            else:
                code, _, err = _git(repo, "update-index", "--force-remove", "--", f, env=env)
            if code != 0:
                raise RuntimeError("could not stage %s: %s" % (f, err[:200]))
        code, tree, err = _git(repo, "write-tree", env=env)
        if code != 0 or not tree:
            raise RuntimeError("could not write the tree: " + err[:200])
        code, commit, err = _git(repo, "-c", "user.name=Anchor lander", "-c", "user.email=anchor@localhost",
                                 "commit-tree", tree, "-p", head, "-m", message)
        if code != 0 or not commit:
            raise RuntimeError("git commit-tree failed: " + err[:200])
        code, ref, _ = _git(repo, "symbolic-ref", "-q", "HEAD")
        code, _, err = _git(repo, "update-ref", "-m", "anchor land: " + message[:60], ref if code == 0 and ref else "HEAD", commit, head)
        if code != 0:
            raise RuntimeError("HEAD moved during the land (compare-and-swap refused): " + err[:200])
    finally:
        for p in (idx, idx + ".lock"):
            try:
                os.unlink(p)
            except OSError:
                pass


def land_locked(repo, source_rev, files, message, who="code job", expect_head=""):
    """Land ``files`` as they are at ``source_rev`` into ``repo``'s checked-out branch without touching anything else.
    Returns (landed: bool, note: str). Every refusal names the file and the reason."""
    repo = str(repo)
    root = Path(toplevel(repo) or repo)
    try:      # W1a (2026-10-08): the running Anchor is never a landing target, whatever a caller passes
        import anchor_next
        if anchor_next.is_served_checkout(repo):
            return False, ("not landed: %s is the running Anchor - its code is changed only from outside Anchor" % root)
    except Exception as e:
        return False, "not landed: could not tell whether %s is the running Anchor (%s)" % (root, e)
    files = [f.replace("\\", "/") for f in files if f.strip()]
    if not files:
        return False, "nothing to land"
    bad = [f for f in files if is_runtime_path(f)]
    if bad:
        return False, "not landed: runtime or steward-state paths never land (%s)" % ", ".join(bad[:5])
    if True:      # the caller holds the repository's commit lock (land() takes it)
        if tracked_runtime(repo):
            return False, "not landed: %s still tracks runtime state (%s); untrack it first" % (root, ", ".join(tracked_runtime(repo)))
        _, head, _ = _git(repo, "rev-parse", "HEAD")
        if expect_head and head != expect_head:
            return False, "not landed: %s moved while the job was being integrated; it will be re-integrated" % root
        snap = snapshot(repo, "before landing %s" % message[:80])
        if not snap:
            return False, "not landed: the safety snapshot could not be made"
        plan = []
        for f in files:
            src = _blob_at(repo, source_rev, f)                       # "" when the job deleted it
            cur = _blob_at(repo, "HEAD", f)                           # "" when HEAD lacks it
            path = root / f
            if cur:
                if _index_blob(repo, f) != cur:
                    return False, "not landed: %s is staged by someone else (index differs from HEAD)" % f
                if not path.exists() or _worktree_hash(repo, f) != cur or not _status_clean(repo, f):
                    return False, "not landed: %s has uncommitted edits in %s" % (f, root)
            else:
                if path.exists() or _untracked(repo, f) or _index_blob(repo, f):
                    return False, "not landed: %s exists in %s but not in HEAD (someone else's new file)" % (f, root)
            plan.append((f, src, cur))
        prewrite = {}
        written = []
        try:
            for f, src, cur in plan:
                # the exact bytes before the write (a clean CRLF checkout differs from its LF HEAD blob), read before any
                # write is recorded, so a failed read can never invent a rollback image (283fc40, 2026-10-11)
                path = root / f
                existed = path.exists()
                before = path.read_bytes() if existed else b""
                if existed != bool(cur):
                    raise RuntimeError("%s changed on disk before the land" % f)
                if existed:
                    code, seen, _ = _git(repo, "hash-object", "--path=" + f, "--stdin", input_bytes=before)
                    if code != 0 or seen != cur:
                        raise RuntimeError("%s changed on disk before the land" % f)
                prewrite[f] = (existed, before)
            for f, src, cur in plan:
                path = root / f
                written.append((f, cur))          # recorded BEFORE the write: any failure below puts it back (R2 N3)
                if src:
                    code, data = _git_bytes(repo, "cat-file", "blob", src)
                    if code != 0:
                        raise RuntimeError("could not read %s from %s" % (f, source_rev))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(path.name + ".land-tmp")
                    tmp.write_bytes(data)
                    os.replace(str(tmp), str(path))
                    if path.read_bytes() != data:      # a concurrent writer: never commit someone else's bytes (F9)
                        raise RuntimeError("%s changed on disk during the land" % f)
                elif path.exists():
                    path.unlink()
            _, head2, _ = _git(repo, "rev-parse", "HEAD")
            if head2 != head or any(_index_blob(repo, f) != (cur or "") for f, cur in written):
                raise RuntimeError("HEAD or the index changed during the land")
            for f, src, _ in plan:                 # the bytes on disk are still the job's, right before committing
                p = root / f
                if src:
                    c, want = _git_bytes(repo, "cat-file", "blob", src)
                    if c != 0 or not p.exists() or p.read_bytes() != want:
                        raise RuntimeError("%s changed on disk before staging" % f)
                elif p.exists():
                    raise RuntimeError("%s reappeared before staging" % f)
            # the commit is built from the job's BLOBS in a private index, never from the bytes on disk, and HEAD moves
            # only by compare-and-swap: a save racing the land can neither enter the commit nor be overwritten (R3)
            _commit_blobs(repo, source_rev, plan, message, head)
        except Exception as e:
            # put every written file back to its exact bytes before the write - but only a file that still holds what THIS
            # land wrote: a concurrent writer's fresh bytes are never overwritten
            srcs = {f: src for f, src, _ in plan}
            for f, cur in written:
                try:
                    p = root / f
                    src = srcs.get(f, "")
                    existed, old = prewrite[f]
                    ours = b""
                    if src:
                        c, ours = _git_bytes(repo, "cat-file", "blob", src)
                        if c != 0:
                            continue
                    if existed:
                        tmp = p.with_name(p.name + ".unland-tmp")
                        tmp.write_bytes(old)
                        if (p.exists() and p.read_bytes() == ours) if src else not p.exists():
                            os.replace(str(tmp), str(p))  # atomic swap: never a truncated or half-written file
                        else:
                            tmp.unlink()              # not the bytes this land left there: someone else's, leave them
                    elif src and p.exists() and p.read_bytes() == ours:
                        p.unlink()                    # this land created it and nobody has touched it since
                    _git(repo, "reset", "-q", "--", f)                # index entry of THIS path only, back to HEAD
                except Exception:
                    pass
            unverified = []                           # say so when a file is not back as it was (283fc40, 2026-10-11)
            for f, _ in written:
                try:
                    existed, before = prewrite[f]
                    p = root / f
                    if not ((p.is_file() and p.read_bytes() == before) if existed else not p.exists()):
                        unverified.append(f)
                except Exception:
                    unverified.append(f)
            if unverified:
                return False, "not landed: %s (rollback unverified for %s; snapshot %s)" % (e, ", ".join(unverified), snap)
            return False, "not landed: %s (nothing changed; snapshot %s)" % (e, snap)
        # the shared index: these paths now = the new HEAD. A held index.lock (an editor's git status) makes the reset
        # fail, so retry; if it never succeeds, say so - a stale entry would stage a revert of this land (Grok R4 #2)
        paths = [f for f, _ in written]
        for _ in range(60):
            if _git(repo, "reset", "-q", "--", *paths)[0] == 0 and all(_index_blob(repo, f) == _blob_at(repo, "HEAD", f) for f in paths):
                break
            time.sleep(0.5)
        else:
            return True, ("landed on %s (snapshot %s) BUT the shared index still holds the old entries for %s: run "
                          "`git reset -q -- <those paths>` there before committing" % (root, snap, ", ".join(paths)))
        _trigger_auto_push_after_land(root)
        return True, "landed on %s (%d file%s; snapshot %s)" % (root, len(written), "" if len(written) == 1 else "s", snap)


def _trigger_auto_push_after_land(root_path):
    """If a landed repo belongs to a project with GitHub auto-push enabled, push in the background."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("ANCHOR_HEALTHCHECK"):
        return
    import threading
    r_str = str(root_path)
    def _bg():
        try:
            import rnd_registry as _rnd_gs
            import project_remote as _rem_gs
            r_norm = os.path.normcase(os.path.realpath(r_str))
            for proj in _rnd_gs.load_registry().values():
                fp = proj.get("folder_path") or ""
                if fp and os.path.normcase(os.path.realpath(fp)) == r_norm:
                    _rem_gs.auto_push_if_opted(proj.get("id"))
                    break
        except Exception:
            pass
    threading.Thread(target=_bg, name="anchor-land-autopush", daemon=True).start()
