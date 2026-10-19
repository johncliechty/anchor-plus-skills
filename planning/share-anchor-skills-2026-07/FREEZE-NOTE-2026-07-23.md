# Skill freeze note (John 2026-07-23)

## Ship set = **v1.0** (collaborator share)

John: current **final master** of Trio + Skill Foundry (pushed) is what we share — call it **v1.0** for this distro cut.

| Component | Freeze policy |
|-----------|----------------|
| Trio (researchPrime, Crucible, Foreman) | **master pushed** — ship that |
| Skill Foundry skills (full roster) | **master pushed** — ship that |
| Anchor (+ Anchor Doctor in-app) | Build/ship from this tree after scrub; no personal project data |
| Zombie Hunter | **Late pin** — John finishing one more update; if still running at package time, wait (poll ~20 min) then commit/push/re-vendor latest |
| Crucible (if still under live improvement) | Same as ZH — wait for quiet master before final pin if still active |

## Personal-data hard rules (public share)

**Must never ship:**
- Author task lists, inbox, dashboard content, project boards
- `.anchor/` project state, worktrees, transcripts, personal logs
- Host paths (`C:\Users\john\…`, machine names), emails, tokens, API keys
- Personal journals / EXECUTION-LOG personal dumps / CLAUDE_hist
- Family Finances / Trusts / private project trees

**Must ship:** scrubbed code + starter empty templates + governance pack (denylist of author paths) + vendored skills from freeze tags.

Enforcement: existing `distro.py` deny-by-default + host-path/PII scans + clean-scan gate before any public push. Operator verifies clean-scan GREEN before release.

## Operator checklist when packaging

1. Check no live Foreman/Crucible/ZH improve runs on foundry/zombie (or wait ~20m polls until quiet).
2. `git status` clean (or intentional) on trio, Skill Foundry, Anchor; HEAD on master; pushed.
3. Re-vendor from freeze commits; SOURCES.md stamps SHAs.
4. `build_distro` / clean-scan — zero personal hits.
5. ZH last: if John finished, re-pin ZH only (or full canary).
