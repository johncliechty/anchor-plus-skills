# Anvil

**One sentence:** Human-first graphical workbench and polyglot AST/runtime engine that maps how software works (`L0 → L1 → L2 → L3` Dual-Channel Process Schematic), verifies companion scientific papers (`Sections, Algorithms & Native MathML ⇄ Code`), plans pure-core refactors with a 3-Tier Null Set, and steps through consented local traces with a **4-Stage Smart Variable Funnel** and expandable **3-Column Scientific IDE Debugger**.

## Use this when
- You want to understand a **trusted or operator-inspected repository** (`Python`, `JS/TS/MJS`, `R`, `C/C++`) quickly through steady-coordinate macro stages (`Purpose`, `What Enters`, `Actions Run`, `What Exits`) before reading raw files
- You want to see **dashed static AST paths** (plus `⋯?` dynamic dispatch blind spots) side by side with **solid runtime-witnessed paths** and iterative loops
- You want to debug numerical or state bugs without drowning in noise—filtering runtime state through the **4-Stage Smart Variable Funnel** (`All State → Stage Scope → Delta Mutated → Anomalies & Pinned Watches`) with automatic `NaN` / `+/-Infinity` tripwires
- You are modernizing tangled code into a clean **Functional Core / Imperative Shell** (`N1..Nk` target stages) with **100% symbol conservation** across `null_proven` dead helpers, `null_unexercised` CLI-guarded paths, and `null_redundant` clones, backed by Golden-Master stage-boundary equivalence checks
- You have a companion paper (`.tex` tree, arXiv bundle, `.md`, or `.pdf`) and want every section, step-by-step algorithm, and native `<math>` MathML equation mapped onto **both** the As-Built (`S1..Sk`) and Proposed Refactored (`N1..Nk`) process maps (when no paper is attached, the Paper tab hides automatically)

## Do not use this when
- You are inspecting **hostile or untrusted malware** — Anvil's `consented_local_subprocess` runner is local process isolation, **not** a hypervisor VM or OS kernel sandbox (use an isolated external VM/container instead)
- You only want a strategic prose review of a memo or policy document with no software or formal algorithm (use Gandalf)
- You are running broad multi-paper literature discovery across dozens of external citations (use literature-review or researchPrime)
- You are executing an already-planned multi-wave build (use Foreman, which invokes Anvil's fast `slice` and `verify-diff` primitives automatically)

## How to start (human)
1. **Launch the live Anvil v4 Workbench** from the `anvil` skill directory:
   ```powershell
   python scripts/anvil_engine.py workbench --repo <dir> [--paper <main.tex>] --serve --port 0
   ```
   *(Or export a self-contained snapshot with `--export-html <out>/anvil_workbench.html`.)*
2. **Explore Posture 1 (`48% / 52%` Process Workbench):**
   - **Left (`48%`):** Click macro stages (`S1..Sk`) on the steady-coordinate Dual-Channel Process Schematic, switch to the **Refactoring Crosswalk (`S1..Sk ↔ N1..Nk`)**, or inspect the **Paper ⇄ Software Crosswalk** (shown automatically when `--paper` is provided).
   - **Right (`52%`):** Switch cleanly across `Story Stream`, `IDE + Watch Split`, `Smart Funnel`, and the 2-Seat `Cross-Validator`, with the **Grounded Steward Co-Pilot** docked below.
3. **Expand Posture 2 (`25% / 45% / 30%` `Open IDE Debugger` — click `Open IDE Debugger` or press `Esc` to toggle):**
   - **Left (`25%`):** Compact Live Process Rail + `L2` file jumpers so you keep architectural orientation while reading code.
   - **Center (`45%`):** Multi-Tab Code Window with gutter breakpoints, `Paper Light / Studio Dark` theme toggle, active execution line `▶`, inline runtime ghost values, and clickable variable tokens that pin directly to your watch list.
   - **Right (`30%`):** The **4-Stage Smart Variable Funnel** (`All State → Stage Scope → Delta Mutated → Anomalies & Pinned Watches`) + synced **Steward Co-Debugger**. Breakpoints, pinned watches, and Steward dialogue stay 100% synchronized whenever you press `Esc` to switch postures or reload the page.
4. **Approve a Consented Local Trace (optional):** Static maps load immediately with **zero** target code executed. When you click to run a runtime trace or stage profile, the **UI Trace Consent Gate** shows the exact `argv` array, isolated temporary worktree path, and trust-boundary notice before anything executes.

## What you get
- **Dual-Channel Process Schematic (`process-map`):** Zero-execution static AST stages (`S1..Sk`) + traced runtime overlay
- **Consented Tracer & Smart Variable Funnel (`trace-run`):** Observer-safe O(1) variable sketches (never triggering custom `__repr__` side effects), `NaN`/`+/-Infinity` tripwires, and 3-way verdicts (`VERIFIED_TRACE`, `CODE_VIOLATES_SPEC`, `MAP_DRIFT`, `UNEXERCISED`)
- **Pure-Core Refactoring Crosswalk (`refactor-map`) & Scope-Safe `LibCST` (`cst-rewrite`):** `N1..Nk` target stages, 3-Tier Null Set conservation, Golden-Master stage-boundary replay, and `LibCST` structural rewrites
- **Dual-Target Paper Crosswalk (`paper-map`):** Native `<math>` MathML equations and algorithm steps tied to both As-Built and Refactored stages (`VERIFIED-NUMERIC`, `VERIFIED-TRACE`, `MAP_DRIFT`)
- **Stage Profiler, Literature Enhancer & 2-Seat Cross-Validator (`profile-lit`, `xval-audit`, `beta-readers`):** Separates I/O plumbing fixes from precondition-checked kernel upgrades, runs bounded `<= 2` cross-family validation, and preserves the 5-Seat Beta-Reader + Aegis (`AEG-01..AEG-06`) security panel

## Trust boundary & limits (honest)
- **`consented_local_subprocess` (not a VM sandbox):** Target code never runs during static `process-map`. When you explicitly consent (`--approve-run` or the Workbench Trace Consent modal), Anvil runs an allowlisted runtime (`python`, `pytest`, `node`, `Rscript`) with `shell=False` on an **isolated temporary copy** of tracked repo files, strips credentials and tokens (`ANCHOR_TOKEN`, API keys, `.env`) from the child environment, enforces event/byte caps (`50,000` events, `64 KB` sketches), and kills the process tree on timeout. Because child processes still run under your local OS user account, **never** approve traces on untrusted or potentially malicious code outside an external VM or container.
- **Distinct failure states (`unknown` is never shown as `empty`):** If a runtime is missing (`503`), a trace times out (`504`), a payload is malformed (`502`), or a state file is unreadable (`500` badged `UNKNOWN`), the Workbench surfaces the exact cause rather than pretending `0` items matched.
- **Scope-safe `LibCST`:** Python structural rewrites require `libcst`; when `libcst` is absent, `cst-rewrite` refuses cleanly rather than falling back to unsafe regex replacements.

## For agents / engines
Full CLI flags, trust-contract invariants, HTTP failure-state codes, and schemas live in `SKILL.md`, `NORTH-STAR.md`, `FLOW.json`, `LIBRARY.json`, and `scripts/anvil_engine.py` next to this file.
