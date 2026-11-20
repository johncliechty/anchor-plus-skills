# ANVIL — Locked North Star, Trust Contract & Requirement Ledger

**Skill Path:** `skills/anvil/`  
**Date Locked:** 2026-11-17 (Rev 5 — Locked by John, Anvil v4 Process Schematic, Refactoring Crosswalk, Dual-Target Paper Mapper & Consented Scientific IDE Debugger Workbench; preserving Rev 4 `ANV-01..ANV-09`)  
**Author & Convergence Authority:** John  
**Visual Brand Asset:** `/vendor/brand/workbench-anvil.jpg` + Standard Anchor Mark (`/vendor/brand/anchor-tab-48.png`)

---

## 1. The Locked North Star (Exact Text)

> **ANVIL v4 NORTH STAR (Rev 5 — Locked by John, 2026-11-17)**
>
> **Mission:** Enable a human investigator to rapidly understand, validate, debug, and modernize trusted or operator-inspected software repositories (with or without a companion scientific paper) through an intuitive graphical workbench backed by a built-in 2-Seat Orchestrator ↔ Cross-Family Adversarial Validator pipeline plus deterministic AST, runtime-trace, and numeric gates.
>
> **Six Anvil v4 Core Pillars:**
>
> 1. **Multi-Level Dual-Channel Process Schematic (`process-map`: L0 Scenarios → L1 3–5 Macro Stages → L2 Sub-Steps → L3 Line-Numbered Code):**
>    - Synthesizes deterministic, repeat-invocation-identical stage IDs (`S1..Sk`) and steady spatial `(x, y)` coordinates via pure static AST analysis (**zero** target repository code executed during `process-map`).
>    - Leads with plain-English **Purpose**, **What Enters**, **Actions Run**, and **What Exits**, visually distinguishing static-only AST edges (`dashed` + `dynamic_blind_spots` flagged `⋯?` for `getattr`/`importlib`/callback hooks) from runtime-witnessed execution (`solid`) and iterative loops.
>
> 2. **Best-in-Class Refactoring Process Map & 3-Tier Null Set (`refactor-map`):**
>    - Synthesizes an `N1..Nk` Functional-Core / Imperative-Shell target process map, visual Old ↔ New (`S1..Sk ↔ N1..Nk`) stage crosswalk, 100% symbol conservation across `null_proven` dead code, `null_unexercised` CLI-guarded paths, and `null_redundant` clones, plus consented data-only Golden-Master stage-boundary equivalence checks.
>
> 3. **Companion Paper ↔ Software Visual Crosswalk (`paper-map`, auto-hidden when `has_paper: false`):**
>    - Compiles `.tex`, multi-file `.tex` trees, arXiv source bundles, `.md`, and `.pdf` manuscripts into `sections[]`, `algorithms[]`, and native `<math>` MathML `equations[]` (zero raw `$...$` LaTeX strings) mapped onto **BOTH** As-Built (`S1..Sk`) and Proposed Refactored (`N1..Nk`) process maps with `MAP_DRIFT`, `VERIFIED-TRACE`, and `VERIFIED-NUMERIC` stamps.
>
> 4. **Consented Local Subprocess Step-Through Validator (`trace-run`), 4-Stage Smart Variable Funnel & Expandable 3-Column Scientific IDE Debugger:**
>    - Runs only with explicit `--approve-run` operator consent under `isolation_boundary: "consented_local_subprocess"` inside an isolated ephemeral temporary worktree copy via a policy-validated `argv` array (`shell=False`), scrubbed credential environment, process-tree timeout termination, observer-safe O(1) structural variable sketches (never invoking `__repr__`, `__str__`, or `@property` descriptors), and explicit numeric event/byte bounds (`BOUND_EXCEEDED_REFUSAL`).
>    - Flags `+/-Infinity` and `NaN` tripwires at exact line/stage boundaries, stamps 3-way stage verdicts (`CODE_VIOLATES_SPEC`, `MAP_DRIFT`, `UNEXERCISED` alongside `VERIFIED_TRACE`), and drives the monotonic 5-scope (`function_locals`, `closure_nonlocals`, `instance_attrs`, `module_globals`, `stage_io_contracts`), 4-stage **Smart Variable Funnel** (`All State → Stage Scope → Delta Mutated → Anomalies & Pinned Watches`) plus the expandable `25% / 45% / 30%` Scientific IDE Debugger.
>
> 5. **Untraced Stage Profiler & Precondition-Checked Kernel Literature Enhancer (`profile-lit`):**
>    - Separates mundane Imperative-Shell I/O engineering bottlenecks from AST/shape precondition-checked Functional-Core algorithmic kernel upgrades.
>
> 6. **Grounded Anvil Steward Dialogue & 2-Seat Cross-Family Validator (`xval-audit` & `workbench`):**
>    - Persists state via cross-process file locking + atomic `temp` + `fsync` + `rename` writes (strictly schema-validated JSON; zero `eval`, `exec`, `pickle`, `marshal`, or `shelve`), keeping dialogue, breakpoints, and pinned watches synchronized across both the `48% / 52%` B3 Workbench posture and the `25% / 45% / 30%` B2 Open IDE Debugger posture.

---

## 2. Explicit Execution Trust Contract (`isolation_boundary: "consented_local_subprocess"`)

Anvil v4 enforces a fail-closed, transparent trust boundary whenever target repository code is executed (`trace-run`, `refactor-map --approve-run`, `profile-lit --approve-run`):

1. **Zero-Execution Static Default:** `process-map` parses source files statically and executes **zero** target code. Unconsented `trace-run` calls fail closed immediately with `CONSENT_REQUIRED_REFUSED` before staging files or spawning any child process.
2. **Isolated Ephemeral Temp Copy:** In Git repositories (`(repo_root / ".git").exists()`), consented runs stage only `git ls-files -z --cached --others --exclude-standard` tracked and non-gitignored repository files (always excluding `.env` and secret/credential/key files) into a fresh ephemeral directory (`tempfile.mkdtemp(prefix="anvil_v4_trace_")`); in non-Git directories, they stage contained source files while excluding `.git`, `.anvil`, `.foreman`, `__pycache__`, `node_modules`, `.venv`, and `.env`/credential/key files, so the operator's working tree is never mutated in-place and gitignored or untracked credentials are not copied.
3. **Canonical Path Containment (`CWE-22`):** All script, module, and artifact paths are validated through `Path.resolve().is_relative_to(repo_root.resolve())`, rejecting `..` traversals, unauthorized absolute paths, and escaping symlinks or NTFS junctions with `PATH_ESCAPE_REFUSED`.
4. **Strict `EXECUTION_POLICY` `argv` Allowlist (`CWE-78`):** Execution accepts **only** an explicit `list[str]` `argv` array (refusing raw command strings, empty `argv`, shell binaries `cmd`/`cmd.exe`/`powershell`/`pwsh`/`sh`/`bash`/`wsl`, and inline code flags `-c`/`-e`/`--eval`/`--command` with `EXECUTION_POLICY_REFUSED`), permits only resolved allowlisted runtimes (`python`, `python3`, `pytest`, `node`, `Rscript`) targeting repo-contained files, and always spawns with `shell=False`.
5. **Scrubbed Credential Environment & Process-Tree Kill:** Child processes receive only minimal OS runtime variables (`TEMP`/`TMP`/`HOME`/`USERPROFILE` redirected inside the ephemeral scratch folder), explicitly stripping `ANCHOR_TOKEN` and all `*KEY*`, `*SECRET*`, `*TOKEN*`, `*PASSWORD*`, and `*CREDENTIAL*` variables. Wall-clock timeouts kill the entire child process tree (`taskkill /T /F` on Windows; `os.killpg` on POSIX), raising `error_code="TRACE_TIMEOUT_REFUSED"` stamped with `verdict="TRACE_TIMEOUT_KILLED"` (`status_kind="dependency-slow-or-killed"`, HTTP 504) so callers distinguish a killed runtime timeout from pre-launch consent/policy refusals.
6. **Data-Only JSON & Boundedness (`CWE-94` / `CWE-502`):** Trace and state stores use `json.loads` / `json.dumps` exclusively (prohibiting `eval`, `exec`, `pickle`, `marshal`, and `shelve`) and enforce `max_events=50000` and `max_sketch_bytes=65536` (`64` KB) with `BOUND_EXCEEDED_REFUSAL`.
7. **Honest Non-Sandbox Boundary Statement:** `"isolation_boundary": "consented_local_subprocess"` provides local OS process, environment, and temp-copy isolation for **trusted or operator-inspected code**. It is **explicitly NOT an OS kernel sandbox, container, or hypervisor VM** against hostile untrusted malware; untrusted hostile binaries or scripts must only be run inside an external VM or isolated container.

---

## 3. John's Requirement Ledger (`ANV-01` .. `ANV-15`)

| ID | Requirement / Idea | Where It Lives in `Anvil` |
| :--- | :--- | :--- |
| **ANV-01** | Orient for **human understanding** with import-graph-clustered Conceptual Modules and a System Process Map. | Mode 1 (`scripts/anvil_engine.py map` & `facts`) |
| **ANV-02** | Show **where AI agents interact and in what way** across the blocks of code. | Mode 1 (`ai_agent_touchpoints` badges & seam summaries) |
| **ANV-03** | Drill into any module/file with full Level 3 numbered source across **all** member files, never silently truncating multi-file clusters. | Mode 1/2 (`get_file_level3_source` & `anvil_v4_process.get_l3_numbered_file`) |
| **ANV-04** | Run code in an **isolated child subprocess (`shell=False`)** and stamp `EXECUTED_PASS` (`validated=True`) ONLY on exit code `0`. | Mode 2 (`inspect`, `walkthrough`, & `anvil_v4_trace.py`) |
| **ANV-05** | **Repo-grounded Anvil dialogue** across all tabs + lockable validated descriptions rolling up into `ANVIL-REPORT.md`. | All Modes (`anvil_chat` & Workbench Steward Co-Pilot) |
| **ANV-06** | 5-Seat Beta-Reader Panel with **Seat 5 wired deterministically to Aegis (`AEG-01..AEG-06`)**. | `run_beta_reader_panel` (`../aegis/scripts/aegis_engine.py`) |
| **ANV-07** | Full-AST + `tests/` reference index preventing false dead-code flags, plus scope-safe `LibCST` rewriting. | Mode 3 (`extract_orange_split`, `remap`, `cst-rewrite`, `verify-diff`) |
| **ANV-08** | Validate 3-stage pipeline (`1. Get Data` → `2. Do Analysis` → `3. Create Output`) and child-subprocess differential equivalence. | Mode 3 (`remap` & `verify-equivalence`) |
| **ANV-09** | **Rich Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Software** across `.tex` trees and arXiv `/e-print/` bundles. | Mode 4 (`paper-map` — `sections[]`, `algorithms[]`, `equations[]`, `code_only_modules[]`) |
| **ANV-10** | **Dual-Channel Steady-Coordinate Process Map (`L0 → L1 → L2 → L3`)** separating dashed static AST edges + `dynamic_blind_spots` (`⋯?`) from solid traced edges & loops. | v4 Pillar 1 (`scripts/anvil_v4_process.py` & `anvil_engine.py process-map`) |
| **ANV-11** | **Consented Local Subprocess Tracer (`--approve-run`)** with `consented_local_subprocess` trust contract, `EXECUTION_POLICY` `argv` allowlist, temp-copy staging, env scrub, observer-safe O(1) sketches, and process-tree timeout kill. | v4 Pillar 4 (`scripts/anvil_v4_trace.py` & `anvil_engine.py trace-run`) |
| **ANV-12** | **Non-Finite (`NaN`/`+/-Infinity`) Tripwires, 3-Way Stage Verdicts (`CODE_VIOLATES_SPEC`, `MAP_DRIFT`, `UNEXERCISED`, `VERIFIED_TRACE`) & Monotonic 5-Scope 4-Stage Smart Variable Funnel**. | v4 Pillar 4 (`scripts/anvil_v4_trace.py` & `scripts/anvil_v4_process.py`) |
| **ANV-13** | **Atomic Cross-Process File-Locked JSON State Store** (`lock` + `temp` + `fsync` + `rename`, strictly data-only JSON). | v4 Storage Layer (`scripts/anvil_v4_process.py`) |
| **ANV-14** | **Pure-Core `N1..Nk` Refactoring Crosswalk, 3-Tier Null Set, Dual-Target Paper Crosswalk, Untraced Profiler/Literature & 2-Seat Cross-Validator**. | v4 Pillars 2, 3, 5 (`scripts/anvil_v4_refactor.py`, `scripts/anvil_v4_xval.py`) |
| **ANV-15** | **Merged `48/52` B3 Workbench + Expandable `25/45/30` Scientific IDE Debugger** with UI Trace Consent Gate and 5-row failure-state distinction. | v4 Pillar 6 (`static/anvil_v4_workbench.html`, `scripts/anvil_v4_workbench.py`) |
