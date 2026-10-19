# v5 Foreman build — new-session handoff prompt

Paste the block below into a fresh Claude Code session started in `C:\dev\Anchor`.

---

Build **Anchor R&D Surface v5 "Durable Work"** with Foreman. The Crucible plan is
already forged and passes Foreman's gate. Project: `C:\dev\Anchor` (you start on
`master`).

CONTEXT (read these first):
- Plan doc-trio: `planning/rnd-v5/MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` +
  `EXECUTION-LOG.md`. Root `foreman.config.json` already points at rnd-v5.
- Confirm the contract: `node /c/Users/john/.claude/skills/foreman/bin/locate-plan.mjs .`
  (should print 6 waves, exit 0).
- Full history + lessons: the memory file
  `C:\Users\john\.claude\projects\C--dev-Anchor\memory\anchor-rnd-surface-v4-design.md`
  and `CLAUDE.md`.
- Approved Grass design (Wave 5): `_mockups/grass_catcher_refined.html` (B filter-tabs
  + C two-pane workbench). Other mockups: `_mockups/project_window_proposals.html`.

HOW TO BUILD (drive the Foreman loop as the orchestrator):
- Work on a branch off master: `git checkout -b foreman/rnd-surface-v5`.
- For each wave (1..6): spawn a fresh-context EXECUTE sub-agent (Agent tool) →
  **YOU run the ground-truth gate yourself** (`$env:ANCHOR_PTY_BACKEND='stub';
  python -m pytest -q`) so a sub-agent can't forge GREEN → spawn an adversarial
  REVIEW sub-agent (prompted to refute) → FIX if needed → re-gate → **scoped**
  commit on GREEN, then advance. Append a wave record to the EXECUTION-LOG.
- Baseline before Wave 1: **643 passed, 1 skipped** (the skip is a pre-existing
  host symlink/git skip). Each wave must hold or grow that.
- SCOPED commits only — never sweep the runtime-data churn (`dashboard.html`,
  `PROJECTS.md`, `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`,
  `rnd_registry.json`, `logs/`). Commit only the code/test files each wave touched.

MANDATORY UI VERIFICATION (the v4 lesson — non-negotiable for Waves 1,2,4,5):
"GREEN" for a UI wave requires ALL of:
  1. rendered-DOM assertions (parse the served HTML with `html.parser`,
     style/script stripped) — assert the NEW structure present AND the OLD/replaced
     structure ABSENT (positive + negative). Model on `tests/test_cockpit_paradigm2.py`.
  2. a REAL Playwright + Chromium interaction test (boot a throwaway
     `gui.make_server('127.0.0.1',0)`, click the actual control, assert the DOM +
     no JS console errors). Playwright + chromium are installed; import via
     `pytest.importorskip("playwright.sync_api")` (dev-only; never in product code).
  3. YOU capture a screenshot (Playwright → save PNG under `_devtest/`) and
     **actually Read the PNG to look at it**, diffing against the mockup. A
     string-grep-only test is NOT acceptable — it once shipped a broken UI.
- Hard rules: stdlib-only product code (+ lazy `pywinpty` in `pty_manager.py`);
  `distro.py` import scan must stay clean (Playwright must NOT appear in product
  code); never bind/touch `:8777` or real data in tests; previews on an OS-assigned
  port HARD-guarded `!= 8777` + isolated temp `ANCHOR_DATA_DIR`; token-auth on new
  mutating/terminal endpoints; `_PROJECT_WINDOW_JS` is a RAW single-brace string
  (double literal braces elsewhere in the f-string HTML/CSS).

WHEN ALL 6 WAVES ARE GREEN:
- Start a preview on a non-8777 port from the branch
  (`$env:ANCHOR_PTY_BACKEND='stub'; python anchor_gui.py --port 8791 --no-browser`),
  screenshot the new surfaces, and present them to me for a consolidated **incognito
  sign-off BEFORE merging**. On my OK: `git checkout master; git merge --no-ff
  foreman/rnd-surface-v5`, update `CLAUDE.md` + the daily log, and tell me to
  `nssm restart anchor`. Do not push to origin unless I ask.
- After deploy, the project window footer shows a green "Project Cockpit · build
  <id>" stamp — that's the deployed-vs-cached truth check.

Start by confirming the locate-plan contract, then build Wave 1.

---
