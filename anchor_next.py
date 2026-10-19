"""anchor_next - "landed" and "live" are two places for an INSTALLED SKILL REPOSITORY (2026-10-10).

The installed skill repositories are the checkouts the installed skills run from - the skill roots a skill job may
start (C:\\dev\\trio, C:\\dev\\Skill Foundry\\skills), the repository Foreman's run-live.mjs belongs to, the SKILLS_ROOT
registry and the Claude adapter farm's targets. A code job there lands on that repository's own integration branch
``anchor-next``, in a checkout the lander owns (under the code-jobs folder), and is NOT installed: the checked-out code
keeps running until a human activates it (``python anchor_next.py activate <repository>``). ``activate`` brings the
repository's own new commits into ``anchor-next`` in the lander's checkout, then fast-forwards the checkout to it. If an
uncommitted file would be overwritten, or the two branches conflict, it stops before anything changes and lists why -
never a reset.

The RUNNING Anchor is neither: its code is never changed from a cockpit (John, 2026-10-10) - he changes it from outside
Anchor. ``served_root`` / ``is_served_repo`` / ``is_served_checkout`` name it so every caller can refuse it
(code_jobs, git_safety.land_locked, the fence).

Every function never raises; stdlib only. CLI: ``python anchor_next.py status|check|activate <repository>``.

``is_installed_repo`` is the one predicate every caller
uses, keyed on the owning git common directory, so a worktree or a junction alias of an installed repository is the
same repository. Discovery fails CLOSED (``InstalledUnknown``): a configured source that is present but unreadable, or
a root whose git identity cannot be read, refuses every direct landing instead of reading as "nothing installed".
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

BRANCH = "anchor-next"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(repo, *args, timeout=600, strip=True):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        out = r.stdout or ""
        return r.returncode, (out.strip() if strip else out), (r.stderr or "").strip()
    except Exception as e:
        return 1, "", "git could not run: %s" % e


def _norm(p):
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except Exception:
        return os.path.normcase(str(p))


class ServedUnknown(RuntimeError):
    """The running checkout could not be identified: every caller refuses (fail closed)."""


class InstalledUnknown(RuntimeError):
    """Installation discovery cannot be trusted - a CONFIGURED source is present but unreadable (a manifest that will
    not parse, a farm that will not list, a provider that will not import) or a skill root's git identity cannot be
    read. Every caller refuses a DIRECT landing and says why (fail closed); it is never read as "nothing installed"."""


def served_root():
    """The checkout the Anchor service serves from - ONE answer wherever this module is imported from (ChatGPT W1a
    r1: a job worktree or a development worktree must not take itself for the running Anchor): the MAIN worktree of
    the repository this file belongs to (C:\\dev\\Anchor for every worktree of it), or ANCHOR_SERVED_ROOT (a throwaway
    repository in tests). Raises ServedUnknown when git cannot say."""
    env = os.environ.get("ANCHOR_SERVED_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    code, out, _ = _git(here, "worktree", "list", "--porcelain", timeout=60)
    first = next((ln[len("worktree "):] for ln in out.splitlines() if ln.startswith("worktree ")), "") if code == 0 else ""
    if not first:
        raise ServedUnknown("git could not name the main worktree of %s" % here)
    return Path(first)


def toplevel(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel", timeout=60)
    return _norm(out) if code == 0 and out else ""


def common_dir(path):
    """The repository's shared git directory: the same for the running checkout and every worktree of it."""
    code, out, _ = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=60)
    return _norm(out) if code == 0 and out else ""


def is_served_checkout(path):
    """True for the running checkout itself (by its working-tree root), never for a worktree of the same repository."""
    top = toplevel(path)
    return bool(top) and top == toplevel(served_root())


def is_served_repo(path):
    """True for the running checkout's repository - the checkout or any worktree of it."""
    c = common_dir(path)
    return bool(c) and c == common_dir(served_root())


def _manifest_roots():
    """The source directory of every skill the Foundry manifest registers (foundry_api.MANIFEST_PATH, each ``source``
    resolved by foundry_api._resolve_source) - an external registered skill needs no Claude farm junction to count. An
    ABSENT manifest is normal (nothing registered); a PRESENT one is read STRICTLY: unreadable, not JSON, without its
    ``skills`` list, an entry that is not an object or a source that will not resolve raises InstalledUnknown (the
    lenient foundry_api._load_manifest reads such a manifest as empty, which a landing guard may not)."""
    try:
        import foundry_api as _fa
    except Exception as e:
        raise InstalledUnknown("the Foundry manifest reader (foundry_api) cannot be imported: %s" % e)
    path = Path(_fa.MANIFEST_PATH)
    try:
        present = path.exists()
    except OSError as e:
        raise InstalledUnknown("the Foundry manifest %s cannot be looked at: %s" % (path, e))
    if not present:
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as e:
        raise InstalledUnknown("the Foundry manifest %s is present but cannot be read: %s" % (path, e))
    skills = parsed.get("skills") if isinstance(parsed, dict) else None
    if not isinstance(skills, list):
        raise InstalledUnknown("the Foundry manifest %s is present but has no 'skills' list" % path)
    roots = []
    for i, entry in enumerate(skills):
        if not isinstance(entry, dict):
            raise InstalledUnknown("the Foundry manifest %s: entry %d is not an object" % (path, i))
        source = entry.get("source")
        if source in (None, ""):
            continue                                    # registered without a location: nothing on disk to protect
        try:
            resolved = _fa._resolve_source(str(source))
        except Exception as e:
            raise InstalledUnknown("the Foundry manifest %s: the source of %s cannot be resolved (%s)" % (
                path, entry.get("name") or "entry %d" % i, e))
        if not resolved:
            raise InstalledUnknown("the Foundry manifest %s: the source of %s resolves to nothing (%r)" % (
                path, entry.get("name") or "entry %d" % i, source))
        roots.append(Path(resolved))
    return roots


def installed_sources():
    """[(where it is named, Path)] - every path an installed skill runs from, as the running Anchor actually knows
    them, never a list kept here: the skill roots a skill job may start a script under (steward_cockpit.skill_jobs.
    skill_roots, ANCHOR_SKILL_ROOTS), the repository Foreman's run-live.mjs belongs to (steward_cockpit.code_jobs.
    FOREMAN_RUN_LIVE), the SKILLS_ROOT the share registry names, the Foundry manifest's registered sources, and the
    targets of Claude's adapter farm (~/.claude/skills/<id>, junctions into the installed skills). An ABSENT optional
    directory is normal; a configured source that is PRESENT but cannot be read raises InstalledUnknown - discovery
    that cannot be trusted never reads as "nothing installed" (bounded review, 2026-10-10)."""
    found = []
    try:
        from steward_cockpit import skill_jobs as _sj
        found += [("skill root", Path(p)) for p in _sj.skill_roots()]
    except Exception as e:
        raise InstalledUnknown("the skill-job roots cannot be read: %s" % e)
    try:
        from steward_cockpit import code_jobs as _cj
        found.append(("Foreman's run-live", Path(_cj.FOREMAN_RUN_LIVE).parent))
    except Exception as e:
        raise InstalledUnknown("Foreman's location cannot be read: %s" % e)
    try:
        import share_skills_root as _ssr
        found.append(("SKILLS_ROOT", Path(_ssr.resolve_skills_root())))
    except Exception as e:
        raise InstalledUnknown("the SKILLS_ROOT registry cannot be read: %s" % e)
    found += [("Foundry manifest", p) for p in _manifest_roots()]
    farm = Path(os.environ.get("ANCHOR_SKILLS_DIR") or (Path.home() / ".claude" / "skills"))
    try:
        present = farm.is_dir()
    except OSError as e:
        raise InstalledUnknown("the Claude skills farm %s cannot be looked at: %s" % (farm, e))
    if present:
        try:
            entries = sorted(farm.iterdir())
        except OSError as e:
            raise InstalledUnknown("the Claude skills farm %s is present but cannot be listed: %s" % (farm, e))
        for entry in entries:
            try:
                if entry.is_dir():                      # a dangling junction is not a directory: absent, normal
                    found.append(("Claude farm", entry.resolve()))
            except OSError as e:
                raise InstalledUnknown("the Claude skills farm entry %s cannot be read: %s" % (entry, e))
    seen, roots = set(), []
    for label, p in found:
        key = _norm(p)
        if key not in seen:
            seen.add(key)
            roots.append((label, Path(p)))
    return roots


def installed_roots():
    """The installed skill roots as paths (installed_sources without the labels); raises InstalledUnknown alike."""
    return [p for _, p in installed_sources()]


def _git_anchor(path):
    """The nearest ancestor of ``path`` (itself included) holding a .git entry - a directory (a checkout) or a file
    (a linked worktree) - so one git call per REPOSITORY identifies many skill directories of it; "" when none."""
    try:
        p = Path(path).resolve()
    except Exception as exc:
        raise InstalledUnknown("cannot resolve repository path %s: %s" % (path, exc)) from exc
    for cand in (p, *p.parents):
        try:
            # exists() can turn access errors into False. A failed identity
            # inspection must not make an installed repository look absent.
            (cand / ".git").lstat()
            return str(cand)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise InstalledUnknown("cannot inspect repository identity at %s: %s" % (cand, exc)) from exc
    return ""


def installed_common_dirs():
    """The owning git common directories of every installed skill root - one git call per distinct repository (roots
    are grouped by their nearest .git entry first, within this one discovery). A root that is not under git
    contributes nothing (nothing there is a repository a job could target); a root whose .git entry is PRESENT but
    whose identity git cannot read raises InstalledUnknown, never reads as absent."""
    anchors, seen = [], set()
    for label, root in installed_sources():
        a = _git_anchor(root)
        if a and _norm(a) not in seen:
            seen.add(_norm(a))
            anchors.append((label, a))
    dirs = set()
    for label, a in anchors:
        c = common_dir(a)
        if not c:
            raise InstalledUnknown("the %s %s has a .git entry but git cannot name its repository - fix or remove it "
                                   "before anything lands there" % (label, a))
        dirs.add(c)
    return dirs


def is_installed_repo(path):
    """True when ``path`` is - or is a worktree or an alias of - a repository an installed skill runs from. The running
    Anchor's own repository is served, not installed (``is_served_repo`` decides it); it is never reported here.
    Raises InstalledUnknown when discovery cannot be trusted (a caller then refuses a direct landing, never guesses)."""
    c = common_dir(path)
    if not c:
        try:
            Path(path).lstat()
        except FileNotFoundError:
            return False  # an absent child of a checkout is not a failed Git lookup
        except OSError as e:
            raise InstalledUnknown("cannot inspect repository path %s: %s" % (path, e))
        if _git_anchor(path):
            raise InstalledUnknown("cannot verify Git common directory for %s" % path)
        return False
    try:
        served = served_root()
        served_common = common_dir(served)
        if not served_common and _git_anchor(served):
            raise InstalledUnknown("cannot verify served Anchor Git common directory for %s" % served)
        if c == served_common:
            return False
    except ServedUnknown as exc:
        raise InstalledUnknown("cannot identify the served Anchor repository: %s" % exc) from exc
    return c in installed_common_dirs()


INSTALLED_NOTE = ("landed to integration (branch %s in %s); NOT installed - %s still runs its checked-out code until a "
                  "human activates it: python anchor_next.py activate \"%s\"")


def installed_note(repo, integration):
    """The one sentence every result about an installed-repository landing carries."""
    return INSTALLED_NOTE % (BRANCH, integration, repo, repo)


def integration_dir(repo, common=""):
    import paths as _paths
    base = _paths.code_jobs_dir()
    return base / "integration" / hashlib.sha1((common or common_dir(repo)).encode()).hexdigest()[:16]


def ensure_integration(repo):
    """(path, "") - the lander's own checkout of ``anchor-next`` for this repository, made when missing (the branch
    starts at the repository's HEAD) - or (None, why). A checkout that is not on the branch, or holds changes
    nobody committed, is refused, never cleaned: it is the lander's, and something else wrote there. Whatever sits at
    the expected path must be a checkout of THIS repository (the same git common directory) - another repository
    there, even on a branch named anchor-next, is refused, never trusted by its path or its branch name (bounded
    review, 2026-10-10)."""
    mine = common_dir(repo)
    if not mine:
        return None, "not a git repository: %s" % repo
    try:
        if is_served_repo(repo):
            return None, "%s is the running Anchor - its code is changed only from outside Anchor" % repo
    except ServedUnknown as e:
        return None, "could not tell whether %s is the running Anchor (%s)" % (repo, e)
    path = integration_dir(repo, mine)
    try:
        present = (path / ".git").exists()
    except OSError as e:
        return None, "could not look at the lander's checkout %s: %s" % (path, e)
    if not present:
        code, _, _ = _git(repo, "rev-parse", "--verify", "-q", "refs/heads/" + BRANCH, timeout=60)
        if code != 0:
            code, head, err = _git(repo, "rev-parse", "HEAD", timeout=60)
            if code != 0:
                return None, "could not read the repository's HEAD: %s" % err[:200]
            code, _, err = _git(repo, "branch", BRANCH, head, timeout=60)
            if code != 0:
                return None, "could not make the %s branch: %s" % (BRANCH, err[:200])
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "prune", timeout=120)
        code, _, err = _git(repo, "worktree", "add", str(path), BRANCH)
        if code != 0:
            return None, "could not make the lander's checkout of %s: %s" % (BRANCH, err[:300])
    owner = common_dir(path)
    if owner != mine:
        return None, ("the lander's checkout %s belongs to another repository (%s), not %s - nothing landed" % (
            path, owner or "no readable repository", repo))
    code, branch, _ = _git(path, "symbolic-ref", "--short", "-q", "HEAD", timeout=60)
    if code != 0 or branch != BRANCH:
        return None, "the lander's checkout %s is not on %s (it is on %s) - nothing landed" % (path, BRANCH, branch or "a detached HEAD")
    code, dirt, _ = _git(path, "status", "--porcelain", "--untracked-files=all", timeout=120)
    if code != 0:
        return None, "could not read the lander's checkout %s" % path
    if dirt:
        return None, "the lander's checkout %s holds changes nobody committed (%s) - nothing landed" % (
            path, ", ".join(ln[3:] for ln in dirt.splitlines()[:6]))
    return path, ""


def head_of(repo, rev="HEAD"):
    code, out, _ = _git(repo, "rev-parse", "--verify", "-q", rev, timeout=60)
    return out if code == 0 else ""


def waiting(repo):
    """The commits landed on anchor-next that the checkout does not carry yet: [(sha, subject)]."""
    root = Path(repo)
    code, out, _ = _git(root, "log", "--format=%H%x09%s", "HEAD.." + BRANCH, timeout=120)
    if code != 0:
        return []
    return [tuple(ln.split("\t", 1)) for ln in out.splitlines() if "\t" in ln]


def _dirty(root):
    """{path: status} for every path in the running checkout an activation must not overwrite: uncommitted, untracked
    and IGNORED (ChatGPT W1a r1: git's default would overwrite an ignored local file). An ignored folder is listed as
    ``dir/``."""
    code, out, _ = _git(root, "-c", "core.quotepath=false", "status", "--porcelain", "-z", "--untracked-files=all",
                        "--ignored=matching", timeout=300, strip=False)
    if code != 0:
        return None
    paths, items = {}, out.split("\0")
    i = 0
    while i < len(items):
        it = items[i]
        if len(it) > 3:
            st, p = it[:2], it[3:]
            paths[p] = st
            if st[0] in "RC":       # a rename carries its source as the next field
                i += 1
                if i < len(items) and items[i]:
                    paths[items[i]] = st
        i += 1
    return paths


def _incoming(root, rev):
    """The paths the fast-forward to ``rev`` would write in the running checkout."""
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", "HEAD", rev,
                        timeout=300, strip=False)
    return None if code != 0 else [p for p in out.split("\0") if p]


def _incoming_tree(root, tree):
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff-tree", "-r", "--no-renames", "--name-only", "-z", "HEAD",
                        tree, timeout=300, strip=False)
    return None if code != 0 else [p for p in out.split("\0") if p]


def _collides(incoming, dirty):
    """Incoming paths that meet a path the checkout holds: the same path, or one inside the other (a file where a
    folder is, a folder where a file is)."""
    held = [d.rstrip("/") for d in dirty]
    out = set()
    for p in incoming:
        for d in held:
            if p == d or p.startswith(d + "/") or d.startswith(p + "/"):
                out.add(p)
    return sorted(out)


def check(repo):
    """What the activation would do, changing nothing: {"ok", "waiting", "blockers", "conflicts", "why", "incoming"}. A
    blocker is a path the fast-forward would write that the checkout holds uncommitted, untracked or ignored (or a
    folder/file in its way); a conflict is a path where the checked-out branch's own new commits and anchor-next
    disagree."""
    root = Path(repo)
    out = {"ok": False, "waiting": waiting(root), "blockers": [], "conflicts": [], "why": "", "incoming": []}
    if not head_of(root, "refs/heads/" + BRANCH):
        out.update(ok=True, why="nothing has landed on %s; nothing to activate" % BRANCH)
        return out
    target = BRANCH
    code, _, _ = _git(root, "merge-base", "--is-ancestor", "HEAD", BRANCH, timeout=60)
    if code != 0:      # the running branch has commits of its own (record checkpoints): they are merged in first
        code, tree, err = _git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", BRANCH, "HEAD", timeout=300)
        if code != 0:
            lines = [ln for ln in tree.splitlines()[1:] if ln.strip()]
            out["conflicts"] = lines or [err[:200] or "the merge could not be computed"]
            out["why"] = "%s and the running branch conflict (%s)" % (BRANCH, ", ".join(out["conflicts"][:8]))
            return out
        target = tree.splitlines()[0] if tree else BRANCH       # the merged TREE: what the running checkout would hold
    incoming = _incoming_tree(root, target) if target != BRANCH else _incoming(root, BRANCH)
    dirty = _dirty(root)
    if incoming is None or dirty is None:
        out["why"] = "git could not compare the running checkout with %s" % BRANCH
        return out
    out["incoming"] = incoming
    out["blockers"] = _collides(incoming, dirty)
    if out["blockers"]:
        out["why"] = "local files in %s would be overwritten: %s" % (root, ", ".join(out["blockers"][:12]))
        return out
    out["ok"] = True
    return out


def _blob(root, rev, path):
    code, out, _ = _git(root, "--literal-pathspecs", "rev-parse", "--verify", "-q", "%s:%s" % (rev, path), timeout=60)
    return out if code == 0 else ""


def _on_disk(root, path, *, raw=False):
    """The blob id the file on disk would have (git's own filters, or its literal bytes when ``raw``), "" when absent."""
    if not (Path(root) / path).is_file():
        return ""
    options = ("--no-filters",) if raw else ("--path=" + path,)
    code, out, _ = _git(root, "--literal-pathspecs", "hash-object", *options, "--", path, timeout=60)
    return out if code == 0 else "?"


def _restore(root, head, want, incoming, before):
    """After a refused fast-forward (ChatGPT W1a r1-r2): put back ONLY what this activation wrote. For each incoming
    path the disk holds one of three things: HEAD's version (untouched - nothing to do), the version anchor-next would
    have written (git wrote it before it gave up - HEAD's version is put back, or the new file removed), or something
    else (someone else's save - kept as it is, and the result is unverified). Index entries are reset for restored
    paths only, by literal path. Returns what could not be verified ([] = restored and verified)."""
    unverified, restored = [], []
    for path in incoming:
        if _collides([path], before):
            # a byte match never makes a pre-existing local change ours: activation refuses this overlap, and the
            # rollback keeps that rule even after an interrupted refusal (283fc40, 2026-10-11)
            unverified.append(path + " (pre-existing local change - kept as it is)")
            continue
        old, new, now = _blob(root, head, path), _blob(root, want, path), _on_disk(root, path)
        if now == old:
            continue
        # a candidate can hold literal CRLF bytes: only its exact bytes count as ours, never a new normalized edit
        if now == new or (new and _on_disk(root, path, raw=True) == new):
            if old:
                code, _, _ = _git(root, "--literal-pathspecs", "checkout", head, "--", path, timeout=120)
                if code != 0:
                    unverified.append(path + " (could not be put back)")
                    continue
            else:
                try:
                    (Path(root) / path).unlink()
                except OSError:
                    unverified.append(path + " (could not be removed)")
                    continue
            restored.append(path)
        else:
            unverified.append(path + " (changed by someone else during the restart - kept as it is)")
    if restored:
        _git(root, "--literal-pathspecs", "reset", "-q", head, "--", *restored, timeout=300)
    after = _dirty(root)
    if after is None:
        return unverified + ["(git could not read the checkout)"]
    drift = sorted(set(after) ^ set(before)) + sorted(p for p in set(after) & set(before) if after[p] != before[p])
    return unverified + [d for d in drift if not any(d == u.split(" (")[0] for u in unverified)]


def activate(repo):
    """The human's step that installs what landed: anchor-next takes the checked-out branch's own new commits (a merge
    in the lander's checkout), then the checkout is fast-forwarded to it, never overwriting an ignored file. Under the
    repository's commit lock. {"ok", "from", "to", "why", "blockers", "conflicts", "unverified"}. On a refusal the
    checkout is verified to hold what it held at the check; when it cannot be verified, ``unverified`` lists why and
    it must be looked at before it is used (ChatGPT W1a r1: git may write files before it fails to move HEAD)."""
    import git_safety as _gs
    root = Path(repo)
    out = {"ok": False, "from": head_of(root), "to": "", "why": "", "blockers": [], "conflicts": [], "unverified": []}
    try:
        served = is_served_repo(root)
    except ServedUnknown as e:
        out["why"] = "could not tell whether %s is the running Anchor (%s); nothing changed" % (root, e)
        return out
    if served:
        out["why"] = "%s is the running Anchor - its code is installed from outside Anchor; nothing changed" % root
        return out
    if not head_of(root, "refs/heads/" + BRANCH):
        out.update(ok=True, to=out["from"], why="nothing has landed on %s" % BRANCH)
        return out
    with _gs.repo_lock(str(root), wait_s=300, who="the restart's activation") as held:
        if not held:
            out["why"] = ("the repository's commit lock is held (a landing in progress, or one cut off by the stop - such "
                          "a lock clears itself after an hour); nothing changed")
            return out
        pre = check(root)
        if not pre["ok"]:
            out.update(why=pre["why"], blockers=pre["blockers"], conflicts=pre["conflicts"])
            return out
        before = _dirty(root)
        ip, why = ensure_integration(root)
        if ip is None or before is None:
            out["why"] = why or "git could not read the running checkout"
            return out
        code, _, _ = _git(root, "merge-base", "--is-ancestor", "HEAD", BRANCH, timeout=60)
        if code != 0:
            code, _, err = _git(ip, "-c", "user.name=Anchor lander", "-c", "user.email=anchor@localhost",
                                "merge", "--no-edit", "-m", "Bring the running branch's own commits into %s" % BRANCH, out["from"])
            if code != 0:
                _git(ip, "merge", "--abort")
                out["why"] = "%s and the running branch would not merge (%s); nothing changed" % (BRANCH, err[:200])
                return out
        incoming = _incoming(root, BRANCH) or []
        want = head_of(root, "refs/heads/" + BRANCH)
        code, _, err = _git(root, "merge", "--ff-only", "--no-overwrite-ignore", BRANCH)
        now = head_of(root)
        if code == 0 and now == want:
            out.update(ok=True, to=now)
            return out
        if now == out["from"]:
            out["unverified"] = _restore(root, out["from"], want, incoming, before)
            out["why"] = "the fast-forward was refused (%s); %s" % (err[:300], "the running checkout was restored and "
                         "verified - nothing changed" if not out["unverified"] else "the running checkout could NOT be "
                         "verified (%s) - do not start it until it is looked at" % ", ".join(out["unverified"][:8]))
        else:
            out["unverified"] = ["HEAD is at %s - neither the old build nor %s" % (now[:12], BRANCH)]
            out["why"] = out["unverified"][0] + " - do not start it until it is looked at"
        out["to"] = now
    return out


def _main(argv):
    # the repository: an INSTALLED skill repository (its activation is the human's explicit step after a code job
    # landed there - a model pass never installs skill code)
    if len(argv) < 3 or argv[1] not in ("status", "check", "activate"):
        print("usage: python anchor_next.py status|check|activate <repository>")
        return 2
    cmd, repo = argv[1], argv[2]
    if cmd == "status":
        w = waiting(repo)
        print("%d change(s) landed on %s wait for activation in %s" % (len(w), BRANCH, repo))
        for sha, subj in w[:20]:
            print("  %s %s" % (sha[:10], subj[:100]))
        return 0
    if cmd == "check":
        r = check(repo)
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 3
    r = activate(repo)
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else (4 if r.get("unverified") else 3)     # 4: look at this checkout before it is used


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
