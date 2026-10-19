# Anchor R&D v13 — Implementation Plan (Foreman-ready)

> **Goal:** Deliver Dashboard UI polish (Gandalf markdown, unified link targets, file upload), add global Dashboard workbench (General Grasscatcher + General Terminal), support Claude↔Gemini terminal hot-swapping, and incorporate the Gemini headless adapter.
> **Baseline Requirements:** All tests must pass (`pytest -q`). New features must be adequately tested. 

## Wave 1 — Gandalf Markdown & Unified Report Links (UI Polish)
**Goal:** Render Gandalf reports with rich markdown and unify report links to open in a dedicated tab.
- [x] **Gandalf Markdown Rendering:** Update `anchor_gui.py` (`_render_layoutd_gandalf_panel`) and `_PROJECT_WINDOW_JS` to use `marked.parse` for rendering the `exec-summary.md` and full `report.md`. Ensure that when a user clicks a Gandalf run row, the inline-expansion renders clean HTML.
- [x] **Unified Tab Target:** In `anchor_gui.py`, identify all `<a>` tags pointing to reports (e.g. `artifact` or `download` links for `.md` / `.pdf` files) and set their target to `target="anchor_report_window"`.
- [x] **Verify:** Ensure clicking report links doesn't spawn endless new tabs, but rather refreshes the `anchor_report_window`. Ensure Gandalf inline expansion shows structured lists/bold text instead of plain text.

## Wave 2 — File Upload Mechanism
**Goal:** Allow users to upload files via the UI to their project or dashboard workspace.
- [x] **UI Elements:** Add a `<input type="file" id="global-upload">` and "Upload File" button in both `generate_html` and the project window layout in `anchor_gui.py`.
- [x] **Backend Endpoint:** Implement `do_POST` routing for `/api/upload` in `anchor_gui.py`.
- [x] **Routing Logic:** If `project_id` is provided, save to `C:\dev\Anchor\.anchor\projects\<project_id>\uploads\`. If `project_id` is `__dashboard__` or `dev`, route to `C:\dev\Anchor\dev\`.
- [x] **Verify:** Upload a test text file from both the project view and the dashboard view. Ensure the files appear in the correct server-side directories.

## Wave 3 — Dashboard Workbench (General Terminal & Grasscatcher)
**Goal:** Expose "General Terminal" and "Grasscatcher" features directly on the main dashboard (`/`).
- [x] **Dashboard Grasscatcher:** Update `anchor_gui.py` (`generate_html`) to embed the Grasscatcher panel (`_render_grass_column_tile` / `_render_grass_workbench`). Map this to a dummy project ID like `__dashboard__`.
- [x] **Dashboard Terminal:** Update the dashboard layout to include a general terminal UI panel. 
- [x] **Backend Support:** Ensure `rnd_registry.py` or `effort_history.py` can handle a `__dashboard__` project ID gracefully without polluting the actual project registry. Ensure `terminal_session.py` can launch a `general` lane for `__dashboard__`.
- [x] **Verify:** Add an idea to the dashboard Grasscatcher. Open the dashboard General Terminal. Restart server and ensure they persist.

## Wave 4 — Claude ↔ Gemini Terminal Hot-Swapping
**Goal:** Allow graceful suspension of a terminal session, summary extraction, and contextual handoff to the other engine (Claude ↔ Gemini).
- [x] **UI Tab Switch Event:** Update the terminal UI tabs (JS) so clicking the inactive engine tab sends an `/api/rnd/switch_terminal_engine` request.
- [x] **Suspend & Summarize:** In `terminal_session.py`, implement graceful termination (`kill_session(..., keep_docs=True, force_summary=True)`) or a new `suspend_session` method that calls `summarizer.summarize_session()`.
- [x] **Handoff Launch:** Use the summary as `seed_context` when launching the new session. Update `last_engine_for_project` and `terminal_session.switch_engine` to support this handoff context.
- [x] **Verify:** Start Claude terminal, type "I am working on feature X". Switch to Gemini. Ask Gemini "What am I working on?". Gemini should reply "Feature X" based on the injected context.

## Wave 5 — Gemini Headless Engine Adapter
**Goal:** Make the Crucible and Foreman Node engines runnable via the `gemini` CLI for plan/build lanes (incorporating `planning/gemini-adapter/PLAN.md`).
- [x] **Gemini Driver:** Create `driver-gemini.mjs` (similar to `makeAgentDriver`) that spawns `gemini --skip-trust -p --output-format stream-json`.
- [x] **Gate Adapter Update:** Update the gate adapter to parse Gemini's tool calls and map them to `AskUserQuestion`.
- [x] **Cost Capture:** Parse Gemini's `stats.models.*.tokens` and latency and record them in the effort log.
- [x] **Lane Configuration:** Add `"plan"` and `"build"` to `lanes.GEMINI_LANES`.
- [x] **Verify:** Run a test planning session (`Crucible`) using the Gemini engine. Verify structured output and tool calls work correctly.

---
**Definition of Done:** All 5 waves completed, UI behaves as specified, Pytest suite is green (no regressions), and Playwright dev-tests (if any) succeed.
