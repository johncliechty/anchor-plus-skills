#!/usr/bin/env python3
"""Publish the built clean-ship Package B tree to the collaborator repo.

The distribution channel is a public GitHub repo containing only the scrubbed
collaborator export; collaborators clone it, and upgrades reach
them as `git pull`. This tool syncs the ALREADY-BUILT, already-gated tree
(run `planning/share-anchor-skills-2026-07/_build_clean_ship.py` first —
every scan/gate lives THERE, fail-closed) into a working clone, commits with
the shipped VERSION, tags, and pushes.

Usage:  python tools/publish_share_repo.py [--source DIR] [--work DIR]
                                           [--repo owner/name] [--no-push]

Safety: refuses a source tree without VERSION/anchor_gui.py (not a built B
tree); never touches the author repo; the work clone's .git is preserved and
everything else is mirrored from the source.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "johncliechty/anchor-plus-skills"
DEFAULT_SOURCE = Path(r"C:\dev\Anchor-ship\clean-ship\B-anchor-plus-skills")
DEFAULT_WORK = Path(r"C:\dev\Anchor-ship\repo")


def run(argv, cwd=None, check=True, timeout=600):
    p = subprocess.run(argv, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout)
    if check and p.returncode != 0:
        raise SystemExit("FAILED: %s\n%s\n%s"
                         % (" ".join(map(str, argv)), p.stdout, p.stderr))
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args(argv)

    source = Path(args.source)
    work = Path(args.work)
    url = "https://github.com/%s.git" % args.repo

    if not (source / "anchor_gui.py").is_file() or not (source / "VERSION").is_file():
        print("refusing: %s is not a built Package B tree (run the "
              "clean-ship builder first)" % source)
        return 2
    version = (source / "VERSION").read_text(encoding="utf-8").strip()

    # Working clone (create on first publish).
    if not (work / ".git").is_dir():
        work.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", url, str(work)])

    # Mirror: everything except .git is replaced by the built tree.
    for child in work.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source.iterdir():
        dst = work / child.name
        if child.is_dir():
            shutil.copytree(child, dst)
        else:
            shutil.copy2(child, dst)

    # FORCE-add: the built, GATED tree IS the repo content — the shipped
    # .gitignore serves the COLLABORATOR's runtime data, and must never be
    # able to silently drop shipped files from the publish (an unanchored
    # `gandalf/` author rule once ate the whole vendored gandalf skill).
    run(["git", "add", "-A", "-f"], cwd=work)
    status = run(["git", "status", "--porcelain"], cwd=work).stdout.strip()
    if status:
        run(["git", "-c", "user.email=anchor@localhost",
             "-c", "user.name=Anchor Publisher",
             "commit", "-m", "v%s" % version], cwd=work)
        print("committed v%s (%d changed paths)"
              % (version, len(status.splitlines())))
    else:
        print("no changes vs published tree (v%s)" % version)

    # COUNT INVARIANT: every file in the built tree must be tracked in the
    # published repo — a mismatch means something was silently dropped.
    n_src = sum(1 for p in source.rglob("*") if p.is_file())
    n_repo = len(run(["git", "ls-files"], cwd=work).stdout.strip()
                 .splitlines())
    if n_src != n_repo:
        print("REFUSING TO PUSH: built tree has %d files but the repo "
              "tracks %d — silent drop detected" % (n_src, n_repo))
        return 3
    print("count invariant OK: %d files tracked" % n_repo)
    run(["git", "tag", "-f", "v%s" % version], cwd=work)

    if args.no_push:
        print("(--no-push) skipping push")
        return 0
    run(["git", "push", "origin", "HEAD"], cwd=work)
    run(["git", "push", "-f", "origin", "v%s" % version], cwd=work)
    print("published %s @ v%s -> https://github.com/%s"
          % (source.name, version, args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
