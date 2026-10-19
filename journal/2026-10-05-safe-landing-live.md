# Safe landing live — 2026-10-05

**What:** Part A of the delegated-work PROPOSAL v0.3 (his "approve", 2026-10-05): no automation rewrites a shared
working tree. The answer to the 2026-10-04 18:59 incident (a refused `git merge` reset the shared Anchor tree and
wiped uncommitted work).

**Live:** Anchor `da09bb5` (after `aeca9b2`, which untracks runtime state), restarted 12:01 with `busy: none`.

**Built:**
- `git_safety.py` — `repo_lock` (one commit lock, keep-alive, stale after an hour), `snapshot` (three trees under
  `refs/anchor-snapshots`), and the lander: only files tracked-and-unchanged or new-and-absent; the commit is built
  from the job's BLOBS in a private index (never the bytes on disk) and the branch moves by compare-and-swap; a
  rollback restores only a file still holding the bytes the land wrote; the shared index sync is retried and a
  failure is reported; literal pathspecs; strict `rev-parse --verify` blob lookups.
- `tools/gitguard/` — every agent session's `git` (steward, code job, workbench terminal) is a real `git.exe`
  launcher built per machine (`install.py`, `%LOCALAPPDATA%/anchor-gitguard/bin`) plus a `git` sh script and
  BASH_ENV for Git Bash; it refuses tree-rewriting verbs outside a code job's own worktree BEFORE git runs.
- Runtime state (`settings.json`, `rnd_registry.json`, `steward-cockpit-state.json`) untracked + ignored, with
  `.bak-N` rotation; the lander refuses while any is tracked.

**Review:** Grok code R1–R5 (R5 SOUND). R3/R4 found the real holes: commit-by-pathspec took bytes saved after the
check; the rollback could overwrite a fresh save; pathspec globbing (`a[1].txt` matched `a1.txt`); bare `rev-parse
HEAD:<glob-like path>` exits 0 echoing its argument (found by our own test).

**Tests:** `tests/test_git_safety_2026_10_05.py` 45 pass; the touched suites vs master: 192 failed on both (pre-existing),
no new failures, +45 passes.

**Friction:** the deploy's `git rm --cached` refused once the untrack commit had moved HEAD (index differed from both
file and HEAD); `git reset -- <paths>` (index only) cleared it. Two background checks were killed by the host on low
memory and rerun one at a time on his word.

**Residual (accepted):** an agent calling git by absolute path or Start-Process; a microsecond window between the
rollback's byte compare and its swap — snapshots cover both.

**Next:** land the two finished Foundry jobs through the new lander; Parts B (delegation lanes) and C (handoffs).
