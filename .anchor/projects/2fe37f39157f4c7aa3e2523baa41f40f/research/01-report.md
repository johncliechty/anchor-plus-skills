# Anchor — Brownfield Orientation Report for a New Owner

**Project:** Anchor (`C:\dev\Anchor`) · self-project id `2fe37f39157f4c7aa3e2523baa41f40f`
**Date:** 2026-06-11 · **Skill:** researchPrime
**Run mode:** **DEGRADED prose mode** — *schema conforms; adversarial verification did NOT run (Node engine).* The Node-backed adversarial engine could not execute because `node <script>`/`node -e` is approval-gated in this non-interactive lane (node v26.1.0 is installed; only `node --version` is permitted). In its place, Phase-3 used **real, context-isolated sub-agents** (Explore + general-purpose) for inventory and one independent adversarial-verifier pass. `cross_model: false`.
**ISOLATION:** main thread = approximated; the four inventory agents and the verifier = real (separate sub-agent contexts).
**Evidence ladder:** OBSERVED > CORROBORATED > CLAIMED > UNVERIFIED. See `evidence-ledger.jsonl` (E1–E25). Verdicts below cite `[ladder | Ex]`.

---

## 1. What Anchor *is* (in one paragraph)

Anchor is a **single-folder personal productivity system** for J.C. Liechty — plain-markdown task/project/inbox files (the source of truth, no database) fronted by a **stdlib-only Python HTTP dashboard** (`anchor_gui.py`, ~5,400 lines) that runs persistently as a **Windows NSSM service named `anchor` on `http://localhost:8777`** and writes the markdown directly. Layered on top is a second, much newer subsystem: an **"R&D control surface"** that turns Anchor into a *memory of trio work* — it registers other code projects, launches the **researchPrime → Crucible → Foreman** trio as durable `claude` subprocess jobs, and tracks each run as a session with validated, cached summaries, an interactive terminal, and a Kanban project window. `[OBSERVED | E1,E2]`

Mental model: **two products in one folder** — (a) the mature, boring, reliable *task manager*; (b) the actively-evolving *R&D orchestration surface* that is where ~all recent engineering effort has gone.

---

## 2. Current state — verified, not just claimed

### 2.1 Code architecture (on disk, confirmed)
- **Entry points:** `anchor_gui.py` (the application; HTTP server), `anchor.py` (~1,000-line CLI mirror + static `dashboard.html` generator + `rnd` subcommands), `anchor_healthcheck.py` (~965-line daily self-test), `launch_anchor.pyw` (browser-opener only, never spawns a server). `anchor_server.py` is a **dead legacy Flask server**, superseded. `[OBSERVED | E1]`
- **R&D v2 module set — complete.** All 13 modules CLAUDE.md names exist on disk with matching docstrings: `rnd_registry`, `effort_history`, `sessions`, `summarizer`, `rnd_terminal`, `deliverables`, `brownfield_scan`, `lanes`, `job_runner`, `gate_adapter`, `report_viewer`, `paths`, `anchor_marker`. `paths.py` is the shared base (path constants, write-lock, exclusive-bind helpers) imported everywhere; `anchor_gui.py:374–386` imports the whole set. One shipped module — `distro.py` (Wave 8 data-free export builder) — is **not** listed in CLAUDE.md's File-Structure block. `[OBSERVED | E2]`
- **Terminal:** the vendored console is now **real `@xterm/xterm` 6.0.0** (MIT, ~489 KB); `anchor-term.js` was rewritten into an adapter over `window.Terminal` (commit `6d36b11`). CLAUDE.md's prose still describes anchor-term as the console "swappable for xterm.js" — wording now lags the code. `[OBSERVED | E3]`
- **Tests:** ~43 `test_*.py` files + `tests/fake_claude.py`, a deterministic mock runner wired through `ANCHOR_RUNNER_CMD` so **no test or healthcheck path ever calls live `claude`** (zero billing). pytest config lives in `pyproject.toml`. There is **no CI** (`.github/` absent); tests are run manually or by the Foreman orchestrator. `[OBSERVED | E4,E25]`

### 2.2 Build state — DONE (the headline)
The R&D-surface-**v2** build is **finished**: all 8 Foreman waves GREEN, `PROJECT DONE` verdict dated 2026-06-11 in `planning/rnd-v2/EXECUTION-LOG.md`, pytest reported 391 passed / 1 skipped (394 after the xterm follow-up). `[OBSERVED | E7]`

Two artifacts *look* like the build is unfinished — both are **traps that resolve to "done"**:
- **`foreman-checkpoint.json` says `current_wave:1, status:"running"`.** This is **stale** — frozen at the Wave-1 EXECUTE start and never cleared after completion. It is gitignored, but discovery still surfaces it as a "build" artifact in the UI. `[OBSERVED | E10]`
- **`EXECUTION-LOG.md:111` says the work is on branch `foreman/rnd-surface-v2`, "not yet merged to master."** Also **stale doc text** — `git branch --contains 9e4b740` proves the PROJECT-DONE commit and the full Wave 1–8 + xterm sequence are on **`master`**. `[OBSERVED | E8,E9]`

So: **on-disk code is complete and merged to master.** `master` is **20 commits ahead of `origin` (unpushed)**. `[OBSERVED | E8]`

### 2.3 What was wired since the prior research
A sibling research run (2026-06-10, under retired id `227eb089…`) concluded "unit-complete, integration-unverified" and named **effort-history-not-wired-to-production** as the highest-value gap. **That gap is now closed** — `effort_history` is imported (`anchor_gui.py:376`) and called in ~11 sites including the live POST handlers `/api/rnd/add_idea` and `/api/rnd/promote_inbox`. The prior finding was overtaken by Wave 5 (2026-06-11). `[OBSERVED | E11,E23]`

### 2.4 Health & runtime signal
Latest health report (`health_reports/2026-06-11.md`) = **Status OK**, all 9 checks pass (incl. the 12-step R&D-v2 surface walk), 1 cosmetic auto-fix (test port busy → free port). The healthcheck has run daily and clean for ~8 days. `[OBSERVED | E17]`

---

## 3. Done vs. Outstanding

### DONE (verified)
| Item | Evidence |
|---|---|
| Core markdown productivity app + dashboard + daily healthcheck | E1,E17 |
| R&D surface **v1** — Crucible-planned, Foreman-built, 9 waves GREEN (2026-06-08); the prior live baseline | E20 |
| **Brownfield discovery** — 7 waves complete (2026-06-09); writes `Anchor.md` marker, adopts discovered sessions with provenance | E20 |
| R&D surface **v2** — 8 waves GREEN, PROJECT DONE (2026-06-11), **merged to master** | E7,E8 |
| Real xterm.js swap (follow-up) | E3 |
| effort_history wired into live GUI | E11 |
| Shipped product is genuinely stdlib-only (deny-by-default `dist_manifest.txt`) | E5 |

### OUTSTANDING (explicit, by priority)
1. **Confirm the live service is running the new code, then push.** On-disk master is done but the in-memory NSSM `anchor` process may still be serving old code until `nssm restart anchor` (elevated). Also push the 20 unpushed commits. `[UNVERIFIED runtime | E12]`
2. **Run `reconcile_folder` on the Anchor project.** Three `Anchor` registrations point at `C:\dev\Anchor` (1 active, 2 retired); real sessions are stranded on the retired ids. Reconcile folds + hard-deletes siblings. `[CORROBORATED | E14,E15]`
3. **Commit/decide durability of R&D state.** `rnd_registry.json`, the `.anchor/` pointer-records (which `.anchor/README` says *should* be tracked, policy C9), and `Anchor.md` are untracked **and not gitignored** — a fresh checkout loses all R&D history + the registry. `[OBSERVED | E18]`
4. **Clean registry pollution + stale job records.** 16 retired `%TEMP%` test projects; 1 failed job; ≥1 orphaned `running` job record with no `finished_at`. `[OBSERVED | E14,E16]`
5. **Gemini plan/build adapter** — the main deferred greenfield item. Today `lanes.GEMINI_LANES = {'research'}`; scoping notes exist (`planning/gemini-adapter/PLAN.md`) but no build started. `[CLAIMED | E20,E21]`
6. **Phase-F deferrals** (lower value): stall/heartbeat, interrupted→resume relaunch, weekly live-smoke test, richer status contract, Foreman run-live adapter, multi-user. `[CLAIMED | E21]`
7. **Hygiene:** delete data-debris `domains/test.md` (cp1252 byte breaks live healthcheck parse); drop stale `requirements.txt`/dead `anchor_server.py`; consider gitignoring the regenerated `dashboard*.html`. `[CLAIMED/OBSERVED | E22,E6,E19]`

---

## 4. Key risks & unknowns (resolve before further work)

| # | Risk / unknown | Severity | Status |
|---|---|---|---|
| R1 | **Live process may run stale code** — disk is merged, but no proof the NSSM service was restarted to load it. | High (correctness of "it's live") | **UNVERIFIED** — needs an approved `Get-Service`/`nssm restart` (E12,E13) |
| R2 | **No live trio gate ever proven** — every Crucible/Foreman/researchPrime go/no-go path is tested only against `tests/fake_claude.py`; real-engine behavior under load/timeout/gates is unobserved. | High (integration) | CORROBORATED across this run + prior research (E24) |
| R3 | **R&D durability gap** — registry + `.anchor/` pointer-records untracked & not ignored; 20 unpushed commits. A checkout/loss event drops all R&D memory. | High (data loss) | OBSERVED (E18) |
| R4 | **Reconcile never run** — multi-id-per-folder; real sessions stranded on retired ids; UI history fragmented. | Medium | CORROBORATED (E15) |
| R5 | **Stale state artifacts mislead the UI** — `foreman-checkpoint.json` (wave-1/running) + stale `running` job records show phantom in-flight build/lanes. | Medium | OBSERVED (E10,E16) |
| R6 | **Doc drift** — CLAUDE.md & EXECUTION-LOG describe pre-merge / pre-xterm reality (anchor-term as console; "not merged to master"). A new owner trusting the docs over the tree will be misled. | Medium | OBSERVED (E3,E9) |
| R7 | **Three third-party imports in the tree** (flask, Pillow, pywin32) contradict the "stdlib-only" identity — *but* all are excluded from the ship manifest, so the shipped product is clean. Stale `requirements.txt`. | Low | OBSERVED (E6) |
| R8 | **Single-file monolith** — `anchor_gui.py` ~5,400 lines with HTML/CSS/JS in f-strings and historically-drifted markdown parsers; high change-risk surface. | Low–Med (maintainability) | OBSERVED (E1) |
| R9 | **Could not verify any live runtime fact** — service status, single-listener-on-8777, whether the 3 `running` pids are alive — all blocked by approval-gated PowerShell in this lane. | n/a | UNVERIFIED (E13) |

---

## 5. First-day playbook for the new owner
1. **Don't break the running service.** It's a persistent NSSM service writing markdown source-of-truth with no DB/undo. Never blanket-kill `pythonw`; to restart use `nssm restart anchor` (elevated). Markdown files are the source of truth.
2. **Establish ground truth before trusting docs.** `git log --oneline -15`, `git status`, read `planning/rnd-v2/EXECUTION-LOG.md` — but cross-check against the tree (this report found 2 stale "build unfinished" signals that are actually DONE).
3. **Verify R1 first:** confirm the live process is on the merged code (`nssm restart anchor` if unsure), then `git push`.
4. **Then housekeeping:** run folder reconcile (R4), decide tracking for `.anchor/`+registry (R3), clean the temp test projects (E14).
5. **Highest-value next feature:** the Gemini plan/build adapter (scoping doc ready). Highest-value *de-risking*: a real, non-stubbed end-to-end trio dogfood run (R2).

---

## 6. Method, honesty & coverage limits
- **Engine NOT run.** Phase-3 ran in degraded prose mode (node execution approval-gated). The adversarial value came from 5 independent sub-agent contexts (4 inventory + 1 verifier), not the Node loop. No `parity`/cross-model claim is made.
- **Not independently executed:** pytest was not re-run (test pass counts are CLAIMED via the log, E7); the server was not started; no live PowerShell runtime check was possible (E13). Empirical (OBSERVED) items rest on direct file/git reads.
- **Deferred by design (branch B3):** no full end-to-end code audit of every module — out of scope for an orientation; handed to the new owner as outstanding work. A subtle behavioral bug could therefore go unseen.
- **Prior work:** the sibling 2026-06-10 research run was corroborated where still valid and **corrected where overtaken** (effort_history wiring, E11/E23).
- **Findings the inventory under/over-stated, corrected by the adversarial pass:** branch *is* merged (not stranded); effort_history *is* wired (not inert); there is a *third* stdlib violation (pywin32), not two.
