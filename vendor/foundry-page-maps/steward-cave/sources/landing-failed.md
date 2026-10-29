# Code-job landing rolled back shared uncommitted work - 2026-10-04

**Skill:** Ecgberht (the code-job hand-off from journal 2071), across the Cave, Distribution and Foundry cockpits.
**Input:** Anchor reflog (failed merges 18:49:34 and 18:59:14 with "updating HEAD"), file times (eight tracked files reset at 18:59), the four cockpits' code-jobs.json, John: "What happened to the star chart? It seems to have disappeared."
**Work:** Traced the rollback; restored the registry (four projects from ids in their own records) and settings; landed the two stuck jobs once the index was clean; froze landing; renamed the running jobs' branches; restarted on John's word; relaunched the Foundry coders from their held branches; notified the other Claude sessions.
**Output:** Anchor f255c1f (freeze + restored state), merges c2c5c1c and 7933539; relaunched jobs 20261004-191251-2cc7b3 (Skill Foundry) and 20261004-191301-c36b42 (Anchor); journal Anchor/journal/2026-10-04-landing-rollback-incident.md.
**Result:** The Star Chart, the four projects and his Aladdin persona are back. Another session's uncommitted code is lost in source (rescue copies exist). Root cause: landing by `git merge` in a shared, always-dirty working tree (cockpits inside the product repo, runtime state tracked in git).
**Friction:** My 2071 build tested landing only against clean temp repos; the shared live tree was never in the tests. Grok's R1 F2 had flagged aborting merges, not that a refused merge itself resets the tree.
**Next:** The proposal at planning/delegated-work-2026-10-04/PROPOSAL.md (clash strategy, delegation inside the effort, context hand-off at ~70%), through review, then John's word. Host Claude Code (Opus 5.5).
