#!/usr/bin/env python3
"""A hermetic stub for the ``gh`` CLI behind the ``ANCHOR_GH_CMD`` seam (v8 Wave 3).

``project_remote.link_github(mode='create')`` runs the seam command with the
``gh`` sub-args appended, e.g.::

    python tests/stub_gh.py repo create <name> --private --source . --remote origin

This stub NEVER touches the network / real github.com. For a ``repo create`` it
simply prints a deterministic fake repo URL to stdout — in the
``https://github.com/<owner>/<name>`` shape that ``project_remote._parse_repo_url``
parses — and exits 0. ``project_remote.link_github`` then wires that url as the
local ``origin`` itself (the minimal stub does not run any git op).

An optional ``ANCHOR_GH_STUB_REMOTE`` env var overrides the printed URL — tests
that want a push to land somewhere real point it at a LOCAL BARE repo
(``file:///…``) so a subsequent ``git push`` has NO network either.

An optional ``ANCHOR_GH_STUB_FAIL`` env var makes the stub emit a gh-not-logged-in
style error on stderr and exit 1 — used to exercise the gh-unavailable → paste-only
degrade path WITHOUT uninstalling gh.
"""
import os
import sys


def main(argv):
    # Simulate an absent/un-authed gh when asked to (gh-unavailable degrade test).
    if os.environ.get("ANCHOR_GH_STUB_FAIL"):
        sys.stderr.write(
            "gh: To get started with GitHub CLI, please run: gh auth login\n")
        return 1

    args = argv[1:]
    # We only model `gh repo create ...`. Anything else is a benign no-op exit 0.
    if len(args) >= 2 and args[0] == "repo" and args[1] == "create":
        name = args[2] if len(args) >= 3 and not args[2].startswith("-") \
            else "stub-repo"
        override = os.environ.get("ANCHOR_GH_STUB_REMOTE")
        url = override or ("https://github.com/johncliechty/%s" % name)
        # gh repo create echoes the created repo URL on stdout — match that shape.
        sys.stdout.write(url + "\n")
        return 0

    # Unmodeled gh sub-command: succeed quietly (the stub is best-effort).
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
