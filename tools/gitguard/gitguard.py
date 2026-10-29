"""gitguard - the `git` every steward and code-job agent runs (delegated-work PROPOSAL v0.3 A1; Grok code R1 F1-F3, F6).

Placed first on the agent process's PATH (steward_engine._spawn_env), so it sees each git call's real arguments and
real working directory BEFORE git runs - for every provider (Codex, Grok and Claude bridges all reach git through the
shell's PATH). It refuses the verbs that rewrite a working tree - merge, checkout, reset, stash, rebase, clean,
restore, switch, pull, am, cherry-pick, revert, apply - unless the target tree is a code job's own worktree
(under GITGUARD_ALLOW_UNDER). Everything else passes straight through to the real git with its exit code. When the
target cannot be proven, a destructive verb is refused (fail closed). Nothing is ever killed mid-command.

On 2026-10-04 a refused `git merge` in C:\\dev\\Anchor hard-reset other sessions' unsaved work; this is the guard.
"""
import os
import subprocess
import sys

DESTRUCTIVE = {"merge", "checkout", "reset", "stash", "rebase", "clean", "restore", "switch", "pull", "am",
               "cherry-pick", "revert", "apply"}
_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix",
                 "--config-env"}


def parse(argv, cwd):
    """(verb, target_dir) from git's argv: the last -C wins, --work-tree / --git-dir name the tree."""
    target, i, verb = cwd, 0, ""
    work_tree = git_dir = None
    while i < len(argv):
        a = argv[i]
        if a in _OPT_WITH_ARG and i + 1 < len(argv):
            val = argv[i + 1]
            if a == "-C":
                target = val if os.path.isabs(val) else os.path.join(target, val)
            elif a == "--work-tree":
                work_tree = val
            elif a == "--git-dir":
                git_dir = val
            i += 2
            continue
        if a.startswith("--work-tree="):
            work_tree = a.split("=", 1)[1]
        elif a.startswith("--git-dir="):
            git_dir = a.split("=", 1)[1]
        elif not a.startswith("-"):
            verb = a
            break
        i += 1
    if work_tree:
        target = work_tree if os.path.isabs(work_tree) else os.path.join(target, work_tree)
    elif git_dir:
        gd = git_dir if os.path.isabs(git_dir) else os.path.join(target, git_dir)
        target = os.path.dirname(os.path.normpath(gd))
    return verb.lower(), target


def allowed(target, real_git, allow_under):
    """A destructive verb runs only inside a code job's own worktree; unprovable means no."""
    if not allow_under:
        return False
    _nw = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run([real_git, "-C", target, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=30, creationflags=_nw)
        top = os.path.normcase(os.path.realpath(r.stdout.strip())) if r.returncode == 0 and r.stdout.strip() else ""
    except Exception:
        top = ""
    if not top:
        return False
    for base in allow_under.split(os.pathsep):
        b = os.path.normcase(os.path.realpath(base)).rstrip(os.sep)
        if b and (top == b or top.startswith(b + os.sep)):
            return True
    return False


def main(argv):
    real_git = os.environ.get("GITGUARD_REAL_GIT") or ""
    if not real_git or not os.path.isfile(real_git):
        sys.stderr.write("gitguard: the real git is not known (GITGUARD_REAL_GIT); refusing to run git\n")
        return 1
    verb, target = parse(argv, os.getcwd())
    if verb in DESTRUCTIVE and not allowed(target, real_git, os.environ.get("GITGUARD_ALLOW_UNDER", "")):
        sys.stderr.write(
            "gitguard: refused `git %s` in %s. Agents may not run merge, checkout, reset, stash, rebase, clean, restore,\n"
            "switch, pull, am, cherry-pick, revert or apply outside a code job's own worktree: on 2026-10-04 a refused\n"
            "merge in a shared tree wiped other sessions' unsaved work. To land work, use a code job (it lands safely,\n"
            "file by file); to discard your own edit, rewrite the file. Tell John if you need this verb.\n" % (verb, target))
        return 1
    _nw = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.call([real_git] + list(argv), creationflags=_nw)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
