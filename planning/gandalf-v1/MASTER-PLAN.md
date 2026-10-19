# Anchor R&D Surface — Gandalf Integration v1 — MASTER PLAN (FROZEN)

> Crucible, 2026-06-22. Brownfield addition to the Anchor per-project R&D dashboard.
> Depth: **FULL** (John). Branch `gandalf-integration` off master `7c2f51f` (v12, GREEN 1426 +1 skip).
> **Shark-Tank round 1 converged** (3 sharks; 2 BLOCKERs + 1 consensus MAJOR + 4 MAJORs + 9 minors —
> all verified against source and resolved below). This is the frozen design; waves live in `IMPLEMENTATION-PLAN.md`.

## North Star (LOCKED — verbatim, John 2026-06-22)
Give each Anchor project an honest "what's really going on here" read — the candid reality check
(real status vs claimed, done vs in-flight vs stalled, drift, risk/debt, a blunt bottom line) — by
invoking the **existing** Gandalf skill through Anchor's runner seam, storing each run's full report +
executive summary + one-line verdict, and surfacing the newest-first run history in a new white-wizard
"Gandalf" tab at the top of the project's right column. **Anchor is integration glue only; Gandalf's
reasoning is never reimplemented.** Runs once on first scan and on manual re-run, never blocks a render,
and never touches real data/network in tests.

## Rigor contract (UPDATED 2026-06-22 — Gandalf's Tier-1 runtime host now EXISTS)
The grading is now **deterministic and earned**, not model-narrated. Gandalf's Tier-1 runtime host shipped
(`C:\dev\Skill Foundry\skills\gandalf\runtime\gandalf-run.mjs`, gate `node --test` = 147/147): it runs a live
analysis's RAW draft through the shipped seam engine to produce a **canary-conformant graded** output
(`assertIncrement1Conformant`). So Anchor's flow is two-stage: (a) the model executes Gandalf's protocol and
emits the **RAW draft** (un-stamped findings/elevations, per the skill's `runtime/RAW-DRAFT-CONTRACT.md`);
(b) Anchor runs the **host** on that draft → deterministic grades. Honest Tier-1 properties (surfaced, never
hidden): elevations land **SPECULATIVE** (no independent challenger ran), `risk_labels` are **PROMISING**-
capped (single-family `cross_model:false`), diagnosis findings carry `gandalf_core`, only **REFUTED** drops,
`degraded:true` only when the host actually computed it. The top tier **PROMISING** (live independent
challengers) is the **sequenced follow-on** (needs Gandalf's `agent()` seam) — Anchor's tab shows the honest
Tier-1 grades now and upgrades transparently when that lands. Anchor never re-grounds/second-guesses the
read (that would reimplement the skill); the host (Gandalf's own engine) owns the grades.

## Locked decisions (do not relitigate without flagging)
1. **Engine = two-stage: model emits the RAW draft → Gandalf's Tier-1 HOST grades it** (this replaces the
   earlier "emit the schema directly" plan now that the host exists). `gandalf.py`:
   - **Stage A (model):** reads `SKILL.md` from a configurable skill dir (`ANCHOR_GANDALF_SKILL_DIR`, default
     `C:\dev\Skill Foundry\skills\gandalf`; resolves BLOCKER B — `/gandalf` is not auto-discoverable) and
     builds a prompt = the skill protocol + "analyze the project at `<folder>` and emit ONLY the RAW draft
     JSON per `runtime/RAW-DRAFT-CONTRACT.md` as your final message; do NOT self-assign tiers/stamps — the
     host applies them." Invoked through `ANCHOR_RUNNER_CMD` (prod → `claude -p`; tests → a stub emitting one
     compact **raw-draft** JSON in a `result` envelope). Anchor extracts the raw draft via
     `job_runner.extract_assistant_text` + last-balanced-JSON parse.
   - **Stage B (host):** runs Gandalf's host on the raw draft through an **injectable seam**
     `ANCHOR_GANDALF_HOST_CMD` (default `node "<ANCHOR_GANDALF_SKILL_DIR>/runtime/gandalf-run.mjs"`; tests
     stub it to emit a canned **graded** `advisor-output.json`, OR run the real host since it's deterministic
     + fast — the plan picks stub for pure-Python hermeticity). `node` is an external CLI through a seam,
     exactly like `git`/`gh` — never a Python dep. **Honest degrade if `node`/the host is absent**
     (`{reason:"host-unavailable"}`, recorded as an error run — never fabricated, never a crash).
   This is "using the existing skill" end-to-end (its protocol + its grading engine); Anchor reimplements
   neither. Both seams (runner + host) are stub-testable, so tests never touch real claude / real node-skill.
2. **Analysis input = point Gandalf at the project FOLDER** (John). The run is launched with
   `cwd = <folder>` AND `--add-dir <folder>` so Gandalf can READ the project (resolves MAJOR S1-5: the
   default argv grants only `--add-dir <output_dir>`), under a **Gandalf-specific injectable timeout**
   (`ANCHOR_GANDALF_TIMEOUT`, default e.g. 600s — NOT summarizer's 60s) — an honest degraded run on timeout,
   never a hang.
3. **Output = a full run → artifacts at the PROJECT ROOT (resolves BLOCKER A)**, under
   `<folder>/gandalf/run-<ts>/`: `report.md` (full rendered schema), `exec-summary.md` (verdict + top
   findings-by-severity + top elevations) — **served by the existing `/artifact` route** (project-root rel
   paths, NEVER under `.anchor`, which `/artifact` hard-rejects) — plus `advisor-output.json` (the raw
   schema, audit truth). The internal **index** lives at `.anchor/projects/<id>/gandalf/index.json` (read
   directly by the GET endpoint, never served via `/artifact`). `gandalf/` is added to the project
   `.gitignore` (best-effort) so regenerable analysis doesn't clutter git status. The **one-line verdict**
   is the cleaned top-level `verdict` field (`summarizer.short_summary_text`, conservative cap + ellipsis),
   stored IN `index.json` (no separate `verdict.txt`). Honesty stamps (`cross_model:false`, `degraded:true`)
   are stored on the index entry and surfaced as chips.
4. **Cadence = first scan + manual.** First-ever run scheduled via a NEW `_trigger_gandalf(...)` that
   **mirrors `anchor_gui._trigger_project_summary` exactly** (resolves MAJOR S1-4): checks the module flag
   `_PROACTIVE_SUMMARY_ENABLED` (off in tests), snapshots the runner env (`ANCHOR_RUNNER_CMD` + `STUB_*`/
   `FAKE_*`) and forwards it to `job_runner.launch(env=...)`, runs in a daemon thread, never blocks render.
   Hooked into the register/open/rescan block (~`anchor_gui.py:933`). First-run-ONLY via
   `run_gandalf_if_absent` guarded by a **per-project in-process lock** (`{pid: threading.Lock}`,
   check-and-set atomically BEFORE scheduling — resolves MAJOR S3-4 TOCTOU double-fire) + skip-if-running.
   The manual `POST /api/rnd/gandalf_run` endpoint is **NOT gated** by the module flag (manual is explicit).
5. **UI = a right-column "Gandalf" tab ABOVE Grass** (order: Gandalf → Grass → Deliverables). Run history
   newest-first; each row = one-line verdict + timestamp + a `degraded`/`cross_model` chip; clicking a row
   **expands the exec-summary INLINE** (mirror the cockpit accordion, not a page bounce — addresses S2-5),
   with `[Full report]` + `[raw JSON]` opening via the traversal-safe `/artifact` route. A **degraded/error
   run** renders an honest row (reason text, "(no report)" placeholder, no dead links — resolves minor
   S3-9). Honest empty state ("No Gandalf read yet" + a Run button) before the first run. A **white-wizard**
   icon (Gandalf the White — white robes/staff, NOT GWL green) = a new vendored SVG
   `vendor/brand/gandalf-white-icon.svg`, served by `/vendor/brand/`, **added to `dist_manifest.txt`**
   (resolves minor S3-7). HTML is f-string (double braces); panel JS in the RAW `_PROJECT_WINDOW_JS`.
6. **Re-runnable any time**; each run a new timestamped entry; history accumulates newest-first.

## Architecture — modules & seams (EXTEND, do not fork)

### New: `gandalf.py` (stdlib only; in `dist_manifest.txt`)
- `run_gandalf(folder_path, project_id, *, force=False, env=None) -> dict` — build the embedded-protocol
  prompt → `job_runner.launch_guarded`/`launch` with `cwd=folder`, `--add-dir folder`, the Gandalf timeout,
  the forwarded env → `job_runner.extract_assistant_text` → **locate the last balanced top-level JSON
  object + parse** → **validate the schema contract** (9 required top-level keys + per-item required keys
  for any findings/elevations/risk_labels actually rendered — resolves MAJOR S3-3) → render `report.md` +
  `exec-summary.md` → write them + `advisor-output.json` to `gandalf/run-<ts>/` → append a SAFE record to
  `.anchor/projects/<id>/gandalf/index.json` under `paths.WRITE_LOCK`. **Every run is stamped
  `degraded:true`** per the v1 honesty contract (the seam didn't run). A parse/validate/timeout failure is
  recorded as an honest **error run** (reason captured, no fabricated verdict, never raises to the caller).
- `run_gandalf_if_absent(folder_path, project_id, env=None)` — the first-scan idempotent no-op-if-prior-run.
- `list_runs(folder_path, project_id) -> list[dict]` — newest-first SAFE projections (ts · run_id ·
  one-line verdict · cross_model · degraded · ok · report_rel · exec_rel · reason?). Never absolute paths.
- `get_run(...)`, render helpers `_render_full_report` / `_render_exec_summary` / `_one_line_verdict`
  (pinned to the top-level `verdict` field — resolves minor S1-6; defensive `.get()` everywhere).
- **Store/index** stamped with `GANDALF_INDEX_SCHEMA_VERSION`; `list_runs` normalizes older/missing
  versions with honest defaults (resolves minor S3-8).

### Extend `anchor_gui.py`
- `POST /api/rnd/gandalf_run {project_id}` (token-authed) → schedule a fresh run in a daemon thread
  (returns `{ok, scheduled:true}` immediately; in-flight guard; NOT module-flag-gated).
- `GET /api/rnd/gandalf?project_id=<id>` (`?token=`) → `gandalf.list_runs` SAFE projection.
- `_trigger_gandalf(...)` (mirrors `_trigger_project_summary`) + the first-scan hook in the rescan block.
- `_render_layoutd_gandalf_panel(folder_path, project_id)` inserted in `_render_layoutd_html` BEFORE
  `{grass_panel}` in `<div class='rightcol'>` (`:3266`).
- `vendor/brand/gandalf-white-icon.svg` via the existing `/vendor/brand/` route.

### Reuse unchanged
`job_runner` (launch + `extract_assistant_text` + `wait`), `report_viewer` (`/artifact`),
`paths.WRITE_LOCK`, `/vendor/brand/`, `summarizer.short_summary_text`.

### CLI / healthcheck / distro / docs (PROJECT DONE wave)
- `anchor.py`: `rnd gandalf <pid>` → `gandalf.list_runs` (read-only, newest-first, honest-absent). No
  mutating CLI form (run/re-run is interactive).
- `anchor_healthcheck.check_gandalf_surface` — fully stubbed (`ANCHOR_RUNNER_CMD` → `tests/stub_gandalf.py`
  + temp data/git dirs + `ANCHOR_PROACTIVE_SUMMARY` off): run → 3 artifacts + index → `list_runs` shape →
  re-run appends a 2nd entry → a degraded/unparseable run recorded honestly. **Snapshots+restores
  `ANCHOR_RUNNER_CMD` + `ANCHOR_PROACTIVE_SUMMARY`, registers temp dirs in `rnd_env["v3_temp_dirs"]`,
  registered in `main()` after `check_rnd_v12_surface`** (resolves minor S3-6). Never binds `:8777`.
- `distro.py`: `gandalf.py` + the SVG in `dist_manifest.txt`; import scan green (assert the SVG manifest
  entry in the distro test).
- `CLAUDE.md` + `SESSION-HANDOFF.md` updated.
- **Live-smoke (manual, NOT a pytest gate — needs real claude):** before declaring prod done, one real
  `claude -p` Gandalf run on a representative project must emit parseable schema JSON within the timeout
  (resolves the prod-path half of BLOCKER B / S1-1). Documented as a deploy checklist item.

## Hard constraints (carried, non-negotiable)
- Python stdlib only (lone lazy `pywinpty` waiver); `gandalf.py` stdlib-only + manifest; distro scan green.
- Hermetic tests: `tests/stub_gandalf.py` (one compact schema JSON in a `result` envelope), temp git/data
  dirs, `ANCHOR_PTY_BACKEND=stub` where PTY touched, `ANCHOR_PROACTIVE_SUMMARY` off; NEVER bind `:8777` /
  real data / network / real claude / the real Skill-Foundry skill.
- Playwright DEV-ONLY (`pytest.importorskip`), never imported by product code.
- `anchor_gui.py` HTML f-string (double braces); `_PROJECT_WINDOW_JS` RAW single-brace; render-smoke before
  any Playwright wave.
- UI wave GREEN = rendered-DOM (pos+neg) + a real Playwright+Chromium interaction test (machine-checkable) +
  an orchestrator screenshot vs the Gandalf-tab mockup + John's sign-off. NO merge / NO `nssm restart`
  until John signs off. Every wave holds or grows the test count.

## Risks & mitigations (post-Shark-Tank)
- **R1 — schema parse/validate fragility.** Extract assistant text → last balanced top-level JSON object →
  validate the named contract; on any failure → honest error run (reason), never crash. Stub-tested happy
  AND degraded paths.
- **R2 — first-scan cost.** Pointing at the folder is an unbounded agentic run; first-run-ONLY +
  background daemon + module-flag-gated + a Gandalf-specific timeout. Honest that prod first-scan WILL
  auto-fire one run per newly-registered project (decision #4).
- **R3 — render-path blocking.** The tab/CLI read `index.json` only; generation is always a daemon thread.
- **R4 — same-model honesty / un-seamed run.** Every run stamped `degraded:true` + `cross_model:false`,
  surfaced as chips (the v1 honesty contract); never dressed up as full-rigor.
- **R5 — artifact serving.** Served artifacts live at PROJECT ROOT `gandalf/` (NOT `.anchor`, which
  `/artifact` rejects) via the existing traversal-safe route; the internal index is never served.
- **R6 — concurrent/double first-scan.** Per-project in-process lock check-and-set BEFORE scheduling +
  skip-if-running + atomic index writes under `paths.WRITE_LOCK`; a concurrency test asserts ≤1 run.
- **R7 — token-auth/traversal.** New endpoints token-authed; artifacts only via `/artifact` (project-rel).

## Out of scope (Grasscatched for a possible v2)
- **Full Node-seam Gandalf rigor** (deterministic tier validation / canary harness in the loop) — v1 is
  honestly degraded. Cross-model/Enhanced substrate; auto-run on every rescan; global cross-project Gandalf
  view; diffing two runs; turning a Gandalf finding into an effort/grass idea.
