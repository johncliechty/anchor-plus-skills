# Anchor R&D v13: Dashboard Polish, File Uploads & Gemini Integration
> **North Star:** Improve the Anchor UX by elevating existing capabilities (markdown rendering, tab management), making the root dashboard a true workbench (general terminal/grasscatcher, global file upload), and deepening Gemini integration (hot-swapping in the terminal + headless engine adapter).

## 1. Intent & Framing
The Anchor UI has matured, but several areas need polish to reduce friction:
1. **Gandalf Reports:** Currently plain text or `<pre>` blocks, making them hard to read. They need rich Markdown rendering.
2. **Report Links:** Clicking reports spawns endless browser tabs. A dedicated named window (`target="anchor_report_window"`) will keep the workspace clean.
3. **File Ingestion:** No easy way to upload references. We need a file upload mechanism routing to the project folder or a global `dev` folder.
4. **Terminal Hot-Swapping:** Developers want to switch between Claude and Gemini contextually. We need graceful suspension, state summarization, and seamless handoff.
5. **Dashboard Workbench:** The main dashboard lacks immediate capture tools. General terminal and Grasscatcher should be accessible without entering a specific project.
6. **Gemini Headless Engine:** The unimplemented `gemini-adapter` plan needs to be built so Crucible and Foreman can run using the Gemini CLI.

## 2. Approach & Architecture

### A. UI Polish & Quality of Life
- **Gandalf Markdown:** Integrate the existing markdown rendering logic (like `marked`) directly into the Gandalf inline-expansion panels in `anchor_gui.py`.
- **Tab Targeting:** Update all `target="_blank"` report links to `target="anchor_report_window"`.
- **Upload Endpoint:** A new `POST /api/upload` endpoint in `anchor_gui.py` supporting `multipart/form-data`. Files upload to `.anchor/projects/<id>/uploads` (project-specific) or `C:\dev\Anchor\dev\` (dashboard-global).

### B. Dashboard Workbench Elevation
- Introduce a pseudo-project or dedicated global paths for the Dashboard.
- Render the `_render_grass_column_tile` and a general terminal pane on the root `/` route.
- Ensure ideas captured here can later be moved/promoted to specific projects.

### C. Claude ↔ Gemini Terminal Hot-Swapping
- Extend the terminal tab UI to emit a switch event.
- On switch, gracefully terminate the active PTY (triggering the existing `summarizer.summarize_session` hook).
- Start a new session for the target engine, injecting the generated summary as a `seed_context` prompt so it picks up where the other left off.
- The Gemini engine uses the `agy` (Antigravity) CLI.

### D. Gemini Headless Adapter (from `gemini-adapter/PLAN.md`)
- A new driver in the Node engines (`makeAgentDriver` analog) for `gemini --skip-trust -p --output-format stream-json`.
- A gate adapter to parse Gemini's tool-call frames for `AskUserQuestion`.
- Cost/latency capture mapped to Anchor's expected schema.

## 3. Risks & Mitigations
- **Hot-swapping Context Loss:** If summarization fails, the handoff fails. Mitigation: display an honest warning if context couldn't be loaded, but still start the terminal.
- **Global Grasscatcher Identity:** Currently grasscatcher is tied to a `project_id`. Mitigation: Use a reserved `__dashboard__` project ID or cleanly separate global grass logic.
- **Gemini Headless Approval Gates:** Headless Gemini might not surface interactive gates exactly like Claude. Mitigation: Spike the gate adapter carefully (as identified in `gemini-adapter/PLAN.md`).
