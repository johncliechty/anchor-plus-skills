# rnd-v13

*Lane: planning · validated, cached summary*

**When run:** 2026-06-26

**What was asked:** rnd-v13

## Actions & files produced

- Anchor R&D v13: Dashboard Polish, File Uploads & Gemini Integration
- Anchor R&D v13 — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- Here's the grounded summary of the **rnd-v13** planning trio session:
- ## Anchor R&D v13 — Planning Summary
- **North Star:** Improve Anchor UX by elevating existing capabilities, making the root dashboard a true workbench, and deepening Gemini integration.
- **Gandalf reports** render as plain `<pre>` text → need rich Markdown rendering.
- **Report links** spawn endless browser tabs → unify to a single named window.
- **No file ingestion** → add an upload mechanism routing to project or global folders.
- **Terminal hot-swapping** between Claude and Gemini → graceful suspend, summarize, handoff.
- **Dashboard lacks capture tools** → expose general terminal + Grasscatcher on the root `/` route.
- **Gemini headless adapter unbuilt** → make Crucible/Foreman runnable on the Gemini CLI.
- **Implementation plan — 5 waves (all checked off in the plan doc):**
- 1. **Gandalf Markdown & unified links** — `marked.parse` in `_render_layoutd_gandalf_panel` / `_PROJECT_WINDOW_JS`; all report `<a>` targets → `target="anchor_report_window"`.
- 2. **File upload** — new `POST /api/upload` (`multipart/form-data`); project files → `.anchor/projects/<id>/uploads/`, dashboard-global → `C:\dev\Anchor\dev\`.
- 3. **Dashboard workbench** — embed Grasscatcher + general terminal on `/` under a reserved `__dashboard__` project ID, handled gracefully so it doesn't pollute the real registry.
- 4. **Claude↔Gemini hot-swap** — tab-switch hits `/api/rnd/switch_terminal_engine`; suspend+summarize the live PTY, then launch the other engine with the summary as `seed_context` (Gemini uses the `agy`/Antigravity CLI).
- 5. **Gemini headless adapter** — new `driver-gemini.mjs` spawning `gemini --skip-trust -p --output-format stream-json`; gate adapter parses Gemini tool-calls → `AskUserQuestion`; cost/latency from `stats.models.*.tokens`; add `plan`+`build` to `lanes.GEMINI_LANES`.
- **Risks flagged:** summarization failure breaks hot-swap handoff (mitigate with honest warning, still start terminal); global Grasscatcher identity tied to `project_id` (use reserved `__dashboard__` ID); headless Gemini may not surface interactive gates like Claude (mitigate by carefully spiking the gate adapter).
- **Definition of Done:** all 5 waves complete, UI behaves as specified, `pytest -q` green with no regressions, Playwright dev-tests pass.
- **Note:** This is the *planning* output (Master Plan + Foreman-ready Implementation Plan) — the plan is marked Foreman-ready, but these docs don't themselves record a completed build/merge.
- Anchor R&D v13 — "Dashboard Polish, File Uploads & Gemini Integration" — planning trio session summary (grounded in MASTER-PLAN.md and IMPLEMENTATION-PLAN.md):
- Improve Anchor UX by elevating existing capabilities (markdown rendering, tab management), making the root dashboard a true workbench (general terminal/grasscatcher + global file upload), and deepening Gemini integration (terminal hot-swapping + headless engine adapter).
- Six framed friction points: plain-text Gandalf reports, report links spawning endless tabs, no file-ingestion path, no Claude↔Gemini terminal switching, a dashboard lacking immediate capture tools, and an unbuilt Gemini headless adapter.
- **Planned waves (implementation plan, all 5 marked done in the doc)**
- **Wave 1 — Gandalf markdown & unified report links:** render `exec-summary.md`/`report.md` via `marked.parse` in `_render_layoutd_gandalf_panel` + `_PROJECT_WINDOW_JS`; retarget all report `<a>` links to `target="anchor_report_window"` so they reuse one named window instead of new tabs.
- **Wave 2 — File upload:** new `POST /api/upload` (`multipart/form-data`) in `anchor_gui.py`; UI file input in both `generate_html` and the project window; routes to `.anchor/projects/<id>/uploads/` for a project, or `C:\dev\Anchor\dev\` when `project_id` is `__dashboard__`/`dev`.
- **Wave 3 — Dashboard workbench:** embed Grasscatcher (`_render_grass_column_tile`/`_render_grass_workbench`) and a general terminal on the root `/` route under a reserved `__dashboard__` project ID; `rnd_registry`/`effort_history`/`terminal_session` must handle `__dashboard__` without polluting the real registry; ideas persist across restart and can later be promoted to real projects.
- **Wave 4 — Claude↔Gemini hot-swapping:** clicking the inactive engine tab calls `/api/rnd/switch_terminal_engine`; gracefully terminate the active PTY, summarize the session (`summarizer.summarize_session`), and inject that summary as `seed_context` into the new engine's session (Gemini uses the `agy`/Antigravity CLI); `switch_engine`/`last_engine_for_project` updated.
- **Wave 5 — Gemini headless adapter** (from `gemini-adapter/PLAN.md`): new `driver-gemini.mjs` spawning `gemini --skip-trust -p --output-format stream-json`; gate adapter parses Gemini tool-call frames into `AskUserQuestion`; cost/latency from `stats.models.*.tokens` mapped to the effort log; add `plan` and `build` to `lanes.GEMINI_LANES`.
- Hot-swap context loss if summarization fails → still start the terminal but show an honest warning.
- Global grasscatcher identity (currently tied to a `project_id`) → reserved `__dashboard__` ID or cleanly separated global grass logic.
- Headless Gemini may not surface interactive approval gates like Claude → spike the gate adapter carefully.
- **Definition of Done:** all 5 waves complete, UI behaves as specified, `pytest -q` green with no regressions, and any Playwright dev-tests pass.

## Files

- [Anchor R&D v13: Dashboard Polish, File Uploads & Gemini Integration](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v13%2FMASTER-PLAN.md)
- [Anchor R&D v13 — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v13%2FIMPLEMENTATION-PLAN.md)
