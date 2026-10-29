# 2073 — Safe landing live (delegated-work Part A)

**Skill:** Ecgberht (steward code jobs) · 2026-10-05
**Situation:** 2072's incident: a code job's refused `git merge` reset the shared Anchor tree and wiped uncommitted work.
**Did:** Part A of `planning/delegated-work-2026-10-04/PROPOSAL.md` v0.3, live at Anchor `da09bb5`: one commit lock,
snapshots before every land, a by-path lander that commits the job's blobs from a private index and moves HEAD by
compare-and-swap, gitguard as every agent's `git` (refuses tree rewrites outside a job's own worktree), runtime state
untracked. Grok code R1–R5 (R5 SOUND).
**Lesson:** a steward's land must never use porcelain that reads the shared tree (`merge`, `commit -- <paths>`, `add`)
— those race the user. Build the commit from blobs; move the ref by CAS.
**Next:** land the held Foundry jobs; Parts B and C.
**Detail:** `C:\dev\Anchor\journal\2026-10-05-safe-landing-live.md`.
