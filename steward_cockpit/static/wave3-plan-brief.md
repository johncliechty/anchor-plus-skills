# Anchor Setup — Wave 3 Vetted Design & Architecture Brief
## Star Chart & Workspace Onboarding (Stage 3 — Vetted with Claude)

### 0. Canonical Sources of Truth (Claude Architecture Alignment)
To prevent Setup from creating a parallel Star Chart or duplicate grouping store, Wave 3 binds directly to Anchor's existing markdown/JSON sources of truth:
1. **Workspace Root & External Roots**: Stored via `anchor_settings.save_settings` (`paths.data_dir()/settings.json` → `host.project_roots` & `host.external_roots`). `rnd_registry` remains the single authority on registered projects.
2. **Project Groupings / Campaign Areas (Mode 1)**: Uses `rnd_registry.set_group` (label-only grouping, aligned with Campaign `AREA_COLOURS` — never invokes on-disk `project_move.move_to_group`).
3. **Star Chart Goal Tiles (Mode 2)**: Reads and writes directly through `steward_cockpit/campaign_acts` (`campaign_page.py`), using Anchor's canonical tier vocabulary alongside tier numbers:
   - `Tier 1 · Primary (do first)`
   - `Tier 2 · Secondary (next in line)`
   - `Tier 3 · On Deck (when there is room)`
4. **Split Backend Endpoints by Owner**: Rather than a monolithic state dump, writes route cleanly to:
   - `POST /api/setup/workspace-root` (`anchor_settings.save_settings`)
   - `POST /api/setup/folder-role` (`rnd_registry` active/subordinate/excluded + parent link)
   - `POST /api/setup/project-group` (`rnd_registry.set_group`)
   - `POST /api/setup/draft-cockpit` (drafts cockpit specs without spawning live PTYs during Setup; launched on demand in Cave of Wonders)
   - `POST /api/setup/goal-tiles` (`campaign_acts`)

---

### 1. Pipeline Status Strip & Top Setup Progress Bar
Above the main two-column workspace, a **4-Stage Pipeline Status Strip** displays live counts and clickable gap filters:
- **`① Root Configured (C:\dev + 2 external)`** → **`② 20 Folders Curated (11 ★ Active · 4 ↳ Subordinate · 5 ○ Excluded)`** → **`③ 11 Project Pages & 16 AI Cockpits`** → **`④ 6 Star Chart Goal Tiles`**
- Includes clickable gap filter pills: `All Folders`, `⚠ Unassigned to Group`, `⚠ No Goal Tile Linked`, `⚠ Unlinked Subordinate`.

---

### 2. Configurable Mother Ship Workspace Root (`Configure Root`)
- **Plain-English Explanation**: Explains that the **Mother Ship Workspace Root (Home Directory)** is the primary folder on the server (`Puter`) where Anchor stores and automatically discovers project folders (`C:\dev` on John's machine, or e.g. `D:\Projects` / `C:\Users\<name>\AnchorWorkspace` on another machine).
- **3 Core Root Actions**:
  1. **`📂 Change / Browse or Create Root Directory`**: Interactive drawer/modal to browse via Windows Explorer (`System.Windows.Forms.FolderBrowserDialog`), enter a path, or click **`+ Create New Root Folder`** on disk.
  2. **`➕ Add External Folder (Windows Explorer)`**: Attaches standalone folders outside `C:\dev` (e.g., `C:\Users\john\Documents\Estate_Files`, `C:\Users\john\OneDrive\BA815_Course`). External folders carry an `EXTERNAL` badge and a non-destructive `Unlink (never deletes files)` action.
  3. **`🔍 AI-Assisted Computer Search & Pull (Copy-Only & Reversible)`**:
     - Interactive drawer where the user tells Steward what topic to gather across `Desktop`, `Documents`, `Downloads`, and `OneDrive`.
     - **Privacy & Cloud Safety Banner**: Explicitly states that Steward scans *file names, paths, and metadata only* (never uploading file contents without per-file opt-in), skips OneDrive `cloud-only (not downloaded)` placeholders by default to avoid mass downloads, and scans for accidental secrets.
     - **Two-Phase Checklist & Copy-Only Execution**: Shows matched files with checkboxes, source path, size, match reason, and cloud-status filter. Primary button is strictly **`Copy N Selected Files (X MB) into C:\dev\<Target>\Gathered_Docs`** (never destructive `Move`).
     - **SHA-256 Verified Undo History**: Stores manifest in `.anchor/pulls/<id>.json` and provides a **"Past Pulls · Undo"** list that safely sends unmodified copies to the Recycle Bin while preserving any files edited after the pull.

---

### 3. Left Column: Project Storage Roots (`★ Active` / `↳ Subordinate` / `○ Excluded`)
- **3-State Role Toggle on Every Folder Card**:
  - **`★ Active`**: Standalone project; gets its own **Project Page (`/project/<id>`)**, can draft/launch **AI Cockpits**, and can be dragged into Mode 1 Project Groups or Mode 2 Star Chart Goal Tiles.
  - **`↳ Subordinate`**: Companion/support folder attached to an Active parent project. Selecting `↳ Subordinate` immediately displays a **`Linked to Parent:` dropdown** (listing only `★ Active` projects, pre-filled by prefix/submodule heuristics, e.g., `claude-code-bridge → Anchor`, `foundry-tools → Skill Foundry`, `Axmra_Anoc_Comp → Axmra`) plus a clear runtime note: *"Sessions & files roll up under Parent Project Page"*.
  - **`○ Excluded`**: Hides utility, git worktree, or archive folders (`_worktrees`, `_attic`, `.anchor`, `Anchor-boot-wt`).
- **Claude UX Safeguards**:
  - **`suggested · reason` Chips**: Auto-detected worktrees/utility folders show `suggested: git worktree` or `suggested: dotfile/archive`.
  - **Live-Work Guard on Exclude**: If the user clicks `○ Excluded` on a folder that has active/parked sessions, efforts, or recent commits, an inline confirmation banner warns: *"This folder has existing efforts/commits. Excluding only hides it from the Star Chart (nothing is deleted on disk)."*
  - **Automatic Top / Bottom Sorting with Undo Toast**:
    - **`★ Active`** folders sort into the **Top Section** (`Active Project Storage Roots — Drag to Right Panel →`).
    - **`↳ Subordinate`** and **`○ Excluded`** folders automatically sort into the **Bottom Collapsible Section** (`Subordinate & Excluded Folders`), accompanied by a floating **Undo Role Change** toast bar so a misclick is 1-click reversible.
  - **HTML5 Drag-and-Drop (`draggable="true"`)**: Every folder card is draggable into the Right Column.

---

### 4. Right Column: 3-Mode Interactive Switcher

#### Mode 1: `📁 Organize into Projects & Cockpits` (Project Grouping + Project Page + AI Cockpit Setup)
- **Project Grouping / Campaign Area Tiles**:
  - Color-coded domain tiles (`Anchor & Foundry Core`, `Research & Mathematics`, `Teaching & MBA Courses`, `Family Trusts & Legal`, `Creative Writing & Books`).
  - **`✨ Ask Steward to Suggest Project Groupings`** button automatically clusters any ungrouped `★ Active` folders into the best-fit Project Grouping Tiles.
  - **`+ New Project Group`**, **`✎ Rename`**, and **`⇄ Combine Groups`** controls.
  - **Drag-and-Drop**: Drag any folder from the Left Column into a Project Grouping Tile.
- **Project Page + AI Cockpit Commissioning Pipeline**:
  - Every project row shows its automatic **Project Page badge** (`/project/anchor`, `/project/campaign`, `/project/mba-teaching-ai`, etc.).
  - Clicking **`⚙ Configure AI Cockpits (Efforts)`** opens the project's **AI Cockpit Commissioning Drawer**:
    - Lists drafted/active AI Cockpits inside that project (e.g., `Campaign` → `Book 1 — Novel Cockpit`, `Chekhov Continuity Cockpit`; `MBA Teaching AI` → `BA 815 Supplements`, `Case Study Generator`).
    - Includes **`+ Draft / Spin Up AI Cockpit`** (Cockpit Name, Seat/Engine, Objective) and shows a read-only cross-link to its Mode 2 Star Chart Goal (`Linked Goal: ... · Edit in Mode 2 →`), plus badges showing how it wires into **The Cave of Wonders** and **Star Chart Goal Tiles**.

#### Mode 2: `✦ Organize into Star Chart Goal Tiles` (Strategic Goals & Major Efforts)
- **Steward Goal-Shaping Dialogue Box** (`Enter` to send, `Shift+Enter` for newline):
  - User describes their workflows, research, teaching, or engineering priorities in plain English; Steward proposes or updates Star Chart Goal Tiles. Includes 1-click prompt templates.
- **Star Chart Goal Tile Cards (`campaign_acts`)**:
  - Grouped and badged by Priority Tier:
    - **`Tier 1 · Primary (do first)`**
    - **`Tier 2 · Secondary (next in line)`**
    - **`Tier 3 · On Deck (when there is room)`**
  - **Drag-and-Drop from Left Column**: Dropping any folder onto a Goal Tile links that Project (and its AI Cockpits) to the goal. If a `↳ Subordinate` or `○ Excluded` folder is dropped onto a Goal Tile, it automatically promotes to `★ Active` first (`Promoted to Project /project/<id>`) and links to the goal.
  - **Full Goal Tile Controls**:
    - **`+ New Goal Tile`**
    - **`✎ Rename`** (inline or prompt)
    - **`⇄ Combine / Merge Tile`** (opens a clear **Merge Preview Modal/Drawer** showing which Goal heading survives and how assigned Projects & AI Cockpits union together, plus 1-click Undo). Also supports dragging one Goal Tile onto another to trigger the same safe Merge Preview.

#### Mode 3: `🧭 Interactive Setup Coach & Guide` (Human-Readable Interactive Onboarding)
- **4-Step Interactive Coach with Live State Checkmarks**:
  - Computes real completion checkmarks (`✓`) from the live workspace state:
    1. **Step 1 · Configure Mother Ship Workspace Root** (`Show Me Root Controls ↑` — scrolls & spotlights the Root Configuration bar).
    2. **Step 2 · Curate Active vs. Subordinate & Excluded Folders** (`Highlight Folder Toggles ←` — spotlights the 3-state toggles in the Left Column).
    3. **Step 3 · Group Projects & Commission AI Cockpits** (`Jump to Mode 1 & Highlight Drawer →` — switches to Mode 1 and opens/spotlights an AI Cockpit drawer).
    4. **Step 4 · Shape Your Star Chart Goal Tiles** (`Jump to Mode 2 & Highlight Goal Shaper →` — switches to Mode 2 and spotlights the Steward Goal-Shaping dialogue & Goal Tiles).
- **Grounded "Ask Steward Coach" Interactive Q&A Box**:
  - Interactive question input (`Enter` to ask) + 5 instant FAQ pills with grounded, deterministic explanations (*"How do Storage Roots, Project Pages, AI Cockpits, and Goal Tiles fit together?"*, *"When should I mark a folder Subordinate vs. Active?"*, *"Is AI Search & Pull safe for my OneDrive and Documents?"*, *"How do I combine two Goal Tiles?"*, *"How do I connect a secondary laptop over Tailscale?"* with direct link back to Wave 1).
