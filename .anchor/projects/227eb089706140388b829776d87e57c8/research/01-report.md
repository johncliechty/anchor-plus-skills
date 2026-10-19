# Anchor — Brownfield Orientation Report

**For:** a brand-new owner of `C:\dev\Anchor`
**Date:** 2026-06-10 · **plan_id:** anchor-bf-7f3a
**ISOLATION:** approximated (single-context orchestrator wrote this report; four fresh read-only sub-agents gathered the evidence; no planning nonce planted — so isolation is *approximated*, not *real*)
**r2_mode:** MIXED — local `grep`/`find` checks ran this session and are **OBSERVED** (E9, E10); the full test-suite GREEN state is **CORROBORATION-ONLY** because `python -m pytest` was gated by the harness this session (E12). There is **no external "best-in-class" axis** for a single-project inventory — that crown is N/A by design.
**Method:** 5 sub-questions, one lane each. Evidence is local: file reads, git history, and two control-cased greps. Every load-bearing claim carries a `[level | E#]` tag pointing into `evidence-ledger.jsonl`.

---

## 1. What Anchor is (and who it serves)

Anchor is a **single-user, plain-markdown personal productivity system** for **J.C. Liechty** (john.liechty@gmail.com), which over the last week has grown a second, larger feature: a **per-project "R&D control surface"** that launches AI coding skills (the *researchPrime → Crucible → Foreman* trio) as durable background jobs and serves their reports. `[CORROBORATED | E2,E6]`

- **Core product:** markdown files are the source of truth (no database); a stdlib-only Python HTTP server (`anchor_gui.py`) renders an interactive browser dashboard at `http://localhost:8777` and writes edits straight back to the markdown. A CLI (`anchor.py`) mirrors the same operations and regenerates a static `dashboard.html`. `[CORROBORATED | E2,E13]`
- **R&D control surface:** turns each *code-project folder* into a launchpad that runs the trio as server-owned `claude -p` subprocesses, streams their output to a console, and serves the resulting reports — exactly the mechanism that produced *this* report. `[OBSERVED | E5,E10]`

The two halves share one process, one auth model, and the `.anchor/` artifact tree, but are otherwise distinct: the core product manages **the owner's life tasks** (academic / commercial / family / writing domains); the R&D surface manages **software projects**. `[CORROBORATED | E2]`

---

## 2. Current state — the headline

The R&D feature was built in a disciplined, plan-driven way (Crucible-planned, Foreman-built across **9 waves**, ~29 test files) and its own gate reports **"PROJECT DONE — all 9 waves GREEN, 158→168 tests passed."** `[CORROBORATED | E11]` The `claude` launch→stream→report spine is **live-proven**: a real job in `rnd_jobs/` invoked the researchPrime skill and wrote artifacts into the project namespace. `[OBSERVED | E5,E10]`

**But "done" here has historically meant "unit tests pass," not "works in production," and three concrete gaps confirm that distinction is still live:**

1. **Effort-history is built and unit-tested but NOT wired into the running app.** `effort_history.record_effort / finalize_effort / attach_cost` have **no production caller** (only the module's own definition + a doc mention), and **no `index.json` / `efforts/` directories exist on disk**. Consequence: the Kanban effort cards, the cost rollup, and the per-effort git auto-commit (success criterion "C9") are **inert in production** despite being fully coded and tested. `[OBSERVED | E10]`
2. **The human SETUP gate is still PENDING** — most importantly the *real-Crucible go/no-go* was never run; Wave 5 tested the gate adapter against a **synthetic** `crucible_gate.jsonl`, not a real Crucible transcript. The plan itself flags this as "the one residual risk." `[CORROBORATED | E14]`
3. **The first real browser use of the "done" build exposed an entire un-assembled UI layer** (orphaned view function, no nav tab, no launch endpoint — "the dashboard looked old"), fixed afterward. `[CORROBORATED | E11]`

The working tree is also **dirty**: 7 modified + 4 untracked paths are uncommitted, including the live `rnd_registry.json` and `.anchor/`. `[OBSERVED | E4]`

---

## 3. Architecture map

### 3a. Core product
| File | Role | Evidence |
|---|---|---|
| `anchor_gui.py` (~205 KB) | **The live application.** stdlib `ThreadingHTTPServer`, port 8777, bind 127.0.0.1; `generate_html()` builds the whole dashboard per request as one big f-string; holds parsing + change-ops + HTTP handler. | `[CORROBORATED | E2]` |
| `anchor.py` (~29 KB) | CLI engine + static `dashboard.html` generator; mirrors the GUI's change-ops. Commands: `dashboard, status, done, cancel, save, restore, add, link, capture`. | `[CORROBORATED | E2]` |
| `paths.py` | Path resolution (rooted at `ANCHOR_DATA_DIR`), auth helpers, and the **single-instance / exclusive-bind guard**. | `[CORROBORATED | E15]` |
| `anchor_healthcheck.py` | Daily 5 AM self-test (Task Scheduler "Anchor Health Check"): parses every markdown file, boots a throwaway server on port 8778 (free-port fallback if busy), walks a synthetic `__healthcheck__` task through every state, writes `health_reports/YYYY-MM-DD.md`. | `[CORROBORATED | E7]` |
| `anchor_server.py` (~16 KB) | **DEAD LEGACY.** Old Flask app on port 5000, references the retired "Anchor PSU" dual-folder layout, ignores `paths.py`, not shipped, not referenced by runtime. Superseded by `anchor_gui.py`. | `[OBSERVED | E9,E13]` |

**Data model:** active task = `- [ ] text — Priority: 2 — energy: med — [domain] — Due: YYYY-MM-DD — Notes: … — Project: <id>`. States: Active → Done (`[x]`) → Cancelled (`CANCELLED.md`) / Saved (`SAVED_FOR_LATER.md`) → Restored. Tasks live in `DASHBOARD.md` + `domains/*.md` (deduped by first 60 chars); projects in `PROJECTS.md` (now nearly empty — life-domain projects archived to `_archive/PROJECTS_legacy_2026-06-09.md`); inbox in `INBOX.md`. `[CORROBORATED | E2,E4]`

**Runtime:** persistent **NSSM Windows service `anchor`** running `python anchor_gui.py --no-browser` on 8777. No Stop button / no `/api/shutdown` (the UI cannot kill its own server). A non-loopback bind is refused unless `ANCHOR_TOKEN` is set. `[CORROBORATED | E15]`

### 3b. R&D control surface (the trio launcher)
| File | Owns | Evidence |
|---|---|---|
| `rnd_registry.py` | id-keyed project registry → `rnd_registry.json`; lifecycle states `active/archived/future/retired` (+ computed `path-missing`); scaffolds `<folder>/.anchor/projects/<id>/{research,planning,build,deliverables,jobs}/`. | `[CORROBORATED | E5]` |
| `job_runner.py` (~47 KB, keystone) | Spawns server-owned `claude -p --output-format stream-json` subprocess (new process group), streams stdout → durable `.log` + ring buffer, persists `rnd_jobs/<id>.json`, long-poll tail, **tree-kill cancel** (`taskkill /T /F`), liveness reconcile (dead-but-"running" → `interrupted`), Wave-6 concurrency policy. | `[CORROBORATED | E2]` |
| `lanes.py` | Frozen lane map: **research→researchPrime** (`research/`, ungated, claude **or gemini**), **plan→crucible** (`planning/`, gated, claude-only), **build→foreman** (`build/`, gated, **mutates tree**, claude-only). `GEMINI_LANES={research}`. | `[CORROBORATED | E14]` |
| `gate_adapter.py` | Parses an `AskUserQuestion` stream-json frame → a prompt record, sets job `state=awaiting-input`, answers single-consumer by writing one plain-text stdin turn. **Self-described as "inherently FRAGILE / best-effort"** (headless `AskUserQuestion` auto-dismisses). | `[CLAIMED | E8]` |
| `effort_history.py` | Versioned per-effort pointer records + `index.json`, cost rollup, per-effort git auto-commit. **Built + tested but not production-wired (see §2.1).** | `[OBSERVED | E10]` |
| `report_viewer.py` | Resolves a finished effort's artifact: serves `report.pdf` by default, else stdlib markdown→HTML with vendored KaTeX; path-traversal-safe. | `[CLAIMED | E8]` |
| `deliverables.py` | Runs a project deliverable by type contract (doc/script/skill/program success), timeout + tree-kill. **Note: a real product module but MISSING from `dist_manifest.txt`** → would not ship under the deny-by-default rule. | `[CLAIMED | E8]` |
| `distro.py` | Deny-by-default shippable-file allowlist (`dist_manifest.txt`) + a no-PII/secret scanner that **fails the build on any leak**; builds a data-free local export (never publishes). | `[CORROBORATED | E2]` |
| `dir_browser.py` | Server-side child-directory enumerator for the "select existing folder" new-project UI. | `[CLAIMED | E2]` |

**Project window (`GET /project/<id>`):** a 4-column Kanban (Research / Planning / Build / Deliverables) of versioned effort cards, a multi-session console drawer (attach-on-click, Ask/gate box + reply + Stop scoped to the *attached* job only), a token-aware lifecycle header (priority / notes / archive / retire / reactivate), and a linked-tasks strip. `[CLAIMED | E6]`

---

## 4. Done vs. outstanding

### Done (evidenced)
- Core productivity product: mature, predates the repo (first commit 2026-05-02 is a *migration* from OneDrive, not a genesis). `[CORROBORATED | E11]`
- R&D feature waves 1–9: all marked GO; suite reported 158→168 passing. `[CORROBORATED | E11]`
- `claude` launch → stream → tail → cancel → report spine: live-proven on disk. `[OBSERVED | E5,E10]`
- Single-instance / exclusive-bind guard + rogue-`Anchor-Server` reaper: shipped (commits `bb660a5`, `31a3832`), resolving the duplicate-supervisor / stale-server saga. `[CORROBORATED | E15]`
- Distribution scanner with 10 planted-secret test fixtures proving the PII gate. `[CORROBORATED | E7]`
- stdlib-only product contract: **true** — flask/Pillow are imported only by the dead `anchor_server.py` and the optional `create_shortcut.py` icon helper, neither shipped. `[OBSERVED | E9]`

### Outstanding / not done
1. **Wire effort-history into launch + a terminal-status finalize hook** — until then Kanban cards, cost rollup, and C9 auto-commit are inert. **(Highest-value gap.)** `[OBSERVED | E10]`
2. **Run the human SETUP gate**, especially the real-Crucible live go/no-go (capture a real `crucible_gate.jsonl`); the keystone gate mechanism is proven only against a synthetic fixture. `[CORROBORATED | E14]`
3. **Gemini for plan/build** is deferred (Research-lane-only); the adapter (Gemini `agent()` driver for Crucible/Foreman, a Gemini gate adapter, cost capture, a green dogfood run) is unbuilt. `[CORROBORATED | E14]`
4. **Phase-F deferrals (none built):** stall/heartbeat timeout, automatic interrupted→resume relaunch, weekly live-smoke test, richer status contract, full PTY/xterm terminal, multi-user. `[CORROBORATED | E14]`
5. **Hygiene:** stale `requirements.txt` (flask/Pillow); dead `anchor_server.py` + its `dashboard_api.html`/`dashboard_live.html` stack; `deliverables.py` missing from the ship manifest; uncommitted working tree; doc trail (`EXECUTION-LOG`) stops at 06-08 while 06-09/06-10 code landed. `[OBSERVED | E4,E9]`

---

## 5. Key risks / unknowns to resolve before further work

| # | Risk | Severity | Evidence |
|---|---|---|---|
| R1 | **Effort-history not wired** — a marquee, tested subsystem is dead in prod; anyone reading the Kanban will think jobs aren't running. | High | `[OBSERVED | E10]` |
| R2 | **Gate mechanism unproven on a real engine** — plan/build lanes depend on a "best-effort, inherently FRAGILE" `AskUserQuestion` text-turn answer that was only ever tested against a synthetic fixture. The plan calls this "the one residual risk." | High | `[CORROBORATED | E14]`, `[CLAIMED | E8]` |
| R3 | **Real-host job liveness is un-exercised** — if live `claude` re-execs its worker as a child, the recorded PID dies → false `interrupted` → could drop the folder build-lock. All gates used a mock runner. | Med-High | `[CORROBORATED | E14]` |
| R4 | **Single-context "done" ≠ working** — this project's own history shows tests-GREEN shipping a non-functional UI. Re-verify any "done" claim against live behavior. | Med | `[CORROBORATED | E11]` |
| R5 | **Security surface is new and recent** — token-on-mutating-`/api/*` + `enable_remote.ps1` (Tailscale/0.0.0.0 bind) landed in the last few days; not soak-tested. GET endpoints are unauthenticated. | Med | `[CORROBORATED | E6,E15]` |
| R6 | **Single 205 KB file** (`anchor_gui.py`) holds parsing + change-ops + HTML + all routes; high merge/maintenance surface, triple-duplicated markdown parsers across `anchor.py`/`anchor_gui.py`/`anchor_server.py` with subtle drift. | Med | `[CORROBORATED | E2,E13]` |
| R7 | **Test-GREEN not independently confirmed this session** — `pytest` was harness-gated; the 158/168 figure is the build's own self-report (checkpoint + EXECUTION-LOG are one origin). Re-run `python -m pytest -v` as the first onboarding step. | Med | `[CORROBORATED | E11]`, gated `[E12]` |
| R8 | **Two retired "Anchor" dogfood projects** in the registry pointing at the same folder; the active one (227eb089…) is self-referential (Anchor's R&D surface managing Anchor). Mildly confusing provenance. | Low | `[OBSERVED | E5]` |

---

## 6. "What you hoped vs. what is true"

This research lane was auto-launched by Anchor's own R&D surface; the implicit hope is *"the project is coherent and the R&D feature is basically done."* **Checked — partly true, with material exceptions:** the feature is genuinely code-complete and well-tested at the unit level and the claude spine runs for real, **but** the effort-history subsystem is not wired into production (`OBSERVED`), the keystone gate is proven only against a synthetic fixture, Gemini plan/build is deferred, and the project's own track record shows "tests pass" has shipped non-working UI before. Treat "done" as "unit-complete, integration-unverified."

---

## 7. Bandwagon watch
No popularity-based claims were used. Every state claim is grounded in a read file, git output, or a control-cased grep run this session. The one place doc-consensus could mislead — "all tests pass / project done" — is explicitly downgraded because both supporting documents are the **same build's self-report** and `pytest` could not be re-run here (R7, E12).

## 8. Open questions
- Does a terminal-status job *anywhere* call `effort_history.finalize_effort`? (Searched: no — but confirm there's no dynamic/late binding.) `[OBSERVED | E10]`
- Will the live `crucible`/`foreman` gate actually surface an answerable `AskUserQuestion` headless, or auto-dismiss? (Never run.) `[CORROBORATED | E14]`
- Exact production service invocation: `setup_service_as_john.ps1` only sets account/env, not `Application`/`AppParameters` — the `--no-browser`/8777 invocation rests on docs, not a committed installer. `[CLAIMED | E2]`
- Current `pytest` pass count on this exact tree (harness-gated this session). `[E12]`

---

## 9. Source table
| # | Source | independent? |
|---|---|---|
| E1 | `git ls-files` type counts + commit count | primary (repo) |
| E2 | top-level `ls -la` + module sizes | primary (repo) |
| E3 | `pyproject.toml` + `requirements.txt` | primary (repo) |
| E4 | `git status --short` | primary (repo) |
| E5 | `rnd_registry.json` + `launch.pointer.json` | primary (repo) |
| E6 | `git log --oneline` | primary (repo) |
| E7 | `tests/` listing | primary (repo) |
| E8 | `planning/`, `_mockups/`, `vendor/` listings | primary (repo) |
| E9 | **control-cased grep**: flask/PIL import sites | OBSERVED this session |
| E10 | **control-cased grep + find**: effort-history wiring | OBSERVED this session |
| E11 | `foreman-checkpoint.json` + `EXECUTION-LOG.md` | primary, **single build-origin** |
| E12 | pytest attempt (gated) | negative result |
| E13 | `anchor_server.py` head/binds | primary (repo) |
| E14 | `SETUP.md` + `DECISION-LOG.md` + `gemini-adapter/PLAN.md` | primary (repo) |
| E15 | `paths.py` + `anchor_gui.py` bind-guard | primary (repo) |

**TRUTH AUDIT: PASS** — every cited `E#` exists in `evidence-ledger.jsonl` with a non-empty `raw`; experiment entries E9/E10 carry controls. The test-GREEN claim was downgraded from any OBSERVED implication to CORROBORATED-single-origin (R7) because pytest was harness-gated (E12). No claim conveniently matching requester_hopes survives on thin evidence; the hope-divergent findings (effort-history gap, synthetic gate fixture, deferred Gemini) are the OBSERVED/CORROBORATED ones. No requester-praise in prose.
