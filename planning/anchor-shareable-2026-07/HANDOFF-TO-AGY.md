# HANDOFF — Anchor "Securely & Easily Shareable" Crucible run
**For continuation in a native `agy` (Antigravity/Gemini, Ultra) interactive session.**
Prepared 2026-07-17 by the Claude/Fable-5 driving session. Self-contained — you should not need any other context to continue.

---

## 0. TL;DR — what to do next (read this first)

You are continuing a **Crucible planning run** (trio: researchPrime → **Crucible** → Foreman) whose goal is to turn the **Anchor** system into something securely + easily shareable to collaborators. State:

- ✅ **Stage 0 (North Star): LOCKED — do NOT redo.** (Authored by Claude/Fable-5, not tier-affected.) See §3.
- 🔴 **Stage 1 (Master Plan): RE-RUN FROM SCRATCH.** The earlier Stage-1 Shark-Tank ran on `agy -p` (headless), which — due to an agy auth bug (§6) — silently **defaulted to a lower/unverified Gemini tier instead of Gemini 3.1 Pro (High)**. **Discard the paused artifacts in `stage1-artifacts/` and `MASTER-PLAN-DRAFT.md` if present — do not trust them.** Re-run the full FULL-depth, Heavy Shark-Tank in THIS agy session where Ultra 3.1 Pro (High) actually serves.
- ⬜ **Stage 2 (Implementation Plan → Foreman handoff): not started.** Do after Stage 1 converges/approves.
- **Depth = FULL, Tier = Heavy** (top-frontier every seat; here that means real Gemini 3.1 Pro (High) on Sharks/Judge).
- **Working dir for all plan docs:** `C:\dev\Anchor\planning\anchor-shareable-2026-07\`

**The user (John) is the convergence authority.** Show him each approval artifact IN FULL before asking him to approve (never a file pointer). Present decisions one at a time, plain-English context + a recommendation first.

---

## 1. The project being planned

**Anchor** (`C:\dev\Anchor`) is a single-user, Python-stdlib local web app (`http://localhost:8777`, runs as the Windows NSSM service `anchor`) — a markdown productivity dashboard that grew an "R&D control surface": a per-project Kanban that launches the AI-agent **trio** as durable, resumable, git-worktree-isolated Claude/Gemini sessions with live ConPTY terminals, session summaries, cost telemetry, staged handoffs, and a grass-catcher idea workbench. All state is plain files (no DB). ~67k LOC; `anchor_gui.py` alone is ~14.8k lines.

**The goal of THIS run:** make the *whole integrated system* (Anchor + trio + foundry skills + their operating conventions) shareable to collaborators who run it on their own machines — securely, easily, cross-platform.

---

## 2. Where this came from (the source review)

A comprehensive **Gandalf** deep-review of Anchor (2026-07-17) produced the finding list this plan addresses. Key artifacts (already on disk):
- `C:\dev\Anchor\planning\anchor-shareable-2026-07\CRUCIBLE-SEED.md` — the full pre-vetted seed (scope + decisions).
- `C:\dev\Anchor\planning\anchor-shareable-2026-07\NORTH-STAR-CANDIDATE.md` — the locked North Star (also §3 below).

The review's headline: Anchor is class-leading for its niche + honest engineering, but **not yet safely shareable** — two share-blockers (open-by-default security = an unauthenticated data plane + filesystem browser + optional token → the `bypassPermissions` build lane becomes RCE once exposed; and both share paths broken = the repo leaks personal data, the distro bundle won't boot). Deep structural pattern: **"green-counter / unmoved-substance"** (capability built, last wiring mile repeatedly deferred). NOTE: the review's own cross-family refutation did NOT resolve (a Gandalf `--live` tooling bug), so its recommendations are advisory — which is *why* we're running Crucible to properly vet them.

---

## 3. NORTH STAR — LOCKED (verbatim; do not drift)

**Statement:** Transform the integrated Anchor system — the Anchor app + the researchPrime/Crucible/Foreman trio + the foundry skills + their operating conventions — from a single-user, single-machine tool into a package a trusted collaborator can obtain and run on their own Windows/macOS/Linux machine, such that: (1) they receive it as a **scrubbed, self-contained bundle** that never carries the author's personal or proprietary data; (2) **onboarding brings up a working, secure-by-default instance with zero manual token handling**; (3) the instance is **safe to run and safe to expose** — no unauthenticated data-read or code-execution surface; (4) the **agent trio behaves identically** to the author's — same governance, status discipline, skill-immutability; and (5) none of this **regresses** the durability, honesty, and safety engineering the system already has.

**Success criteria (checkable):**
1. **Secure-by-default:** a freshly-onboarded instance behind a loopback reverse proxy (e.g. Tailscale Serve) returns 401 to a **tokenless** request on **every** data-plane, terminal, and directory-browse route, and the `bypassPermissions` build lane is unreachable without the token. No unauthenticated read / filesystem-enumeration / code-execution surface remains.
2. **Zero-friction token:** author + each collaborator **never manually find or type a token** — auto-provisioned + persisted locally at onboard, auto-used by the local browser, survives restarts. Security = token present + enforced, not manual entry.
3. **No-leak distribution:** the ONLY share channel is a scrubbed bundle containing none of the author's personal/proprietary files or git history; `import anchor_gui` inside the staged bundle boots (smoke-gated).
4. **Works-on-arrival cross-platform:** a collaborator on Windows AND macOS/Linux goes bundle → onboard → live dashboard via one documented path; missing prerequisites (Python/git/`claude` CLI) surface as one upfront actionable message.
5. **Identical agent behavior:** trio + foundry skills run under the same governance — 10-min status-table format, skills read-only / foundry-only-edit, driver-init self-configures to the host's engine subscriptions.
6. **No durability regression:** the durability cluster (below) is closed + covered; existing telemetry/narration/reaper-safety invariants hold.
7. **Money-safe + clean:** the test suite cannot spend real money without explicit opt-in (fail-closed); shipped tree free of dev debris + dependency-doc contradictions.

**Non-goals (OUT):** the WAL inversion (deferred — its own future effort); multi-user/multi-tenant on one instance; OS-level agent sandboxing; a frontend rewrite; cloud hosting; an observability stack; re-architecting the trio/foundry skills' internals.

**Risk taxonomy:** R1 security false-safe (highest) · R2 usability-vs-security tension · R3 distribution incompleteness/leak · R4 cross-platform breakage · R5 durability-fix regression · R6 decomposition regression vs a flaky wave-pinned test suite · R7 governance over-enforcement · R8 scope creep into the WAL inversion.

---

## 4. SCOPE — John's locked decisions (refine into the plan; do NOT re-litigate)

**P0 — share-blockers:**
1. **Security baseline (full):** mandatory token (server refuses to start without one) + enforce auth-mode by default + token-gate/remove `/api/rnd/dir_browse` + validate `Host`/`X-Forwarded-For` (kill the reverse-proxy bypass). **HARD CONSTRAINT:** the token is **auto-provisioned + persisted locally** (env / `0600` file the service reads at startup) + auto-injected into the local browser (SameSite=Strict cookie); the user NEVER finds/types it; enforcement blocks only a remote peer without the token.
2. **Redact token in logs** — strip/mask `?token=` in the access logger + both exception loggers.
3. **Distro bundle boots** — re-sync `dist_manifest.txt` (currently missing ≥7 module imports: supervisor, narration, usage_capture, rollup_honesty, foundry_gui, foundry_gui_write, foundry_api) + add a smoke-boot gate to `build_distro` (`import anchor_gui` in the staging dir; fail the build on drift).
4. **Bundle-only distribution** — the scrubbed bundle (skills verified inside) is the sole share channel; never hand out the working repo (it tracks `DASHBOARD.md`, `domains/commercial.md`, 512 `.anchor/` files in git history).
5. **Onboard stands up a real instance** — genuinely start/register the service (or honest cross-platform launch), mint + persist the token (satisfies #1), wire it end-to-end. (Currently onboard reports "registered" but registers nothing; the minted token is read by no code.)

**P1:**
6. **Durability cluster (all four):** (a) route `anchor.py` CLI + ~10 secondary writes through `paths.atomic_write_text`; (b) real cross-process lock (retire the shared fixed `.tmp` name — service/CLI/5AM-healthcheck collide); (c) rebuild a torn efforts `index.json` from surviving pointer files (no heal-to-empty history loss); (d) boot-reaper owner-set fix (don't delete a live worktree after a server-only crash). NOTE: the single-process GUI atomic-write fix is already REAL/verified; these are the edges it didn't reach.
9. **Cross-platform readiness:** honest POSIX launch/onboard, one upfront dependency gate (Python/git/`claude` CLI), purge hardcoded `john`/`C:\` paths. (POSIX groundwork already exists: a stdlib-pty backend, systemd/launchd unit generators, relocatable data dirs.)
10. **Governance packaging (full):** bundle the canonical `AGENTS.md` operating conventions (incl. the 10-min status-table format), set skills **read-only + foundry-only-edit** (enforced where practical), ship driver-init defaults so skills self-configure to the host's engine subscriptions.
11. **Hygiene (all three):** (a) fix `requirements.txt` (drop flask/Pillow — contradicts stdlib-only); (b) move/delete the ~15 root `fix*.py` scratch scripts; (c) make the test billing guard **fail-closed** (suite refuses a real engine without explicit opt-in — it once leaked 8,816 billed sessions).

**P2:**
7. **Monolith follow-through:** move the 123 already-table-dispatched handlers OUT of `anchor_gui.py` into real modules (the `static/project-window.js` extraction proves the path) + memoize `GET /` lane reads (it recomputes ~738 file opens with ~3× redundancy per hit). Not a rewrite. Gated by a large wave-pinned suite (regression risk — a test-suite-health thread may be warranted).

**P3 — OUT of this run, queued as its own future effort:**
8. **WAL inversion** — make `journal.py` the single source of truth, demote registries/summaries to derived replay-rebuilt views (`effort_view.py` proves the pattern). Multi-quarter; the permanent durability cure; guard the boundary — do NOT pull it into this run.

---

## 5. Crucible run mechanics

- **Depth:** FULL (confirmed by John). **Tier:** Heavy.
- **Plan dir / artifacts / status log:** `C:\dev\Anchor\planning\anchor-shareable-2026-07\` (`stage1-artifacts/`, `_crucible-status.log`).
- **Stage-1 loop** = 3 fresh-context Sharks (Skeptic/Contrarian/Analyst, each prompted to refute) → BLOCKER = ≥2 agree; a persistent Synthesizer steers (never decides); a Judge decides; **the user is the final authority.** Round cap 5 → HALTs with the best draft + open findings for John.
- **The md/delta file-flow fix IS verified working** (the re-run showed revisions landing markdown-first, findings flowing, no EI1 shrinkage). Only the *tier* was the problem.
- **A high-value shark finding already surfaced — carry it in:** *"Phase 1 mandates `fsync(parent dir)` for atomic writes, but on Windows `fs.open()` on a directory throws EPERM/EACCES → crashes the durability primitive → dead-on-arrival for Windows collaborators."* (Ties to criterion 6 + risk R4/R5.) Also flagged: host-engine config drift breaking "identical behavior" (criterion 4/5), and exposure-safety being dodged (criterion 3/1).

---

## 6. WHY the handoff — the agy tier issue (fully diagnosed)

Running Crucible from the Claude session drove Gemini via `agy -p` (headless print mode). **`agy -p` cannot reach your Ultra Gemini 3.1 Pro (High):**
- Reproduced with a bare `agy -p "…" --model "Gemini 3.1 Pro (High)" --log-file X` — nothing to do with crucible/driver/routes/env (`TRIO_MODEL_SHARK` is correctly set).
- Per-call log: `Model ID Gemini 3.1 Pro (High) not in local config, defaulting to CCPA` / `resolved via default` + `error getting token source: You are not logged into Antigravity` + `Entering local chrome mode! This is WRONG`.
- Root cause: `agy -p` won't perform the headless OAuth **refresh** that interactive agy does. Your `~/.gemini/oauth_creds.json` holds a valid long-lived `refresh_token` (interactive uses it fine, minting access tokens in-memory), but it is **frozen at June 23** — no login today rewrote it, and its access_token is expired. Interactive refreshes via a browser-capable path; `-p` jumps to a browser flow it can't complete headless → falls back to a default (possibly lower) tier. Base Google inference still works (real output returns), so it's a *silent tier downgrade*, not a hard failure.
- **On the latest agy (1.1.3; `agy update` confirms latest)** — updating does NOT fix it. This is an agy `-p` headless-auth bug worth reporting.

**Implication for you (running natively in agy interactive/Ultra):** you serve real **Gemini 3.1 Pro (High)** at full tier, so the Shark-Tank you run is genuinely Heavy. **That is exactly why Stage 1 must be redone here** — the prior rounds may have been lower-tier.

**Credential state I left:** to test a fix I moved the stale cred aside — `~/.gemini/oauth_creds.json` is currently **absent**; backups are `~/.gemini/oauth_creds.json.bak-20260717` and `…STALE-moved-aside`. A fresh `agy` login should write a new one. To restore the prior file exactly: `mv ~/.gemini/oauth_creds.json.bak-20260717 ~/.gemini/oauth_creds.json`.

---

## 7. Two foundry-level gaps to carry (fix in the foundry, not on the fly)

1. **Same-model Judge:** the Stage-1 loop's Judge stamped `same-model persona: claude` rather than cross-family Gemini. Cause: `runStage1` does **not** accept/forward a `routes` param to `runMasterPlanLoop` (which DOES take `routes`). The Sharks WERE cross-family; only the Judge decision fell back to same-model. To get a cross-family Judge, drive `runMasterPlanLoop({…, routes})` directly (the runbook's blessed live path) — but note the pre-loop brainstorm/triage/phased-plan steps are internal to `runStage1` (`phasedPlanPrompt` is not exported), so a faithful manual drive must reuse the exported `runBrainstorm` / `triageIdeas` / `renderMasterPlanDraft` and not re-implement the phased-plan prompt.
2. **`runStage1` ↔ runbook drift:** the runbook says `runStage1({…, routes})` but the code signature has no `routes`. Reconcile in the foundry.

---

## 8. File & command map

- **Active trio engine:** `C:\dev\trio\crucible\bin\` (the `~/.claude/skills/crucible` junction points to `C:\dev\trio\crucible`). Drivers: `C:\dev\trio\drivers\` (`index.mjs` role-router; `gemini-cli.mjs` = agy; `gemini.mjs` = raw-HTTP API [rejected — John wants Ultra, not an API key]).
- **The driver script the Claude session used (reference; re-run Stage 1 with real tier):** `C:\dev\trio\crucible\bin\_anchor_stage1.mjs` — builds `buildLiveCrucibleAgent({routes})` with `shark/judge → gemini-cli`, `synthesizer/default → claude (claude-fable-5)`, and calls `runStage1({agent, northStar, criteria, depth:'FULL', artifactsDir, statusLog})`. In a native agy session you may instead drive Crucible per its SKILL.md runbook so the Gemini seats are your Ultra session.
- **Model labels (agy):** heavy = `Gemini 3.1 Pro (High)` (agy's `GEMINI_HEAVY_MODEL`, the default). NEVER an API-style id like `gemini-3.1-pro` (agy rejects it → the exact "not in local config" symptom).
- **Env:** `TRIO_MODEL_SHARK/REVIEW/REVIEWER/DEBATE = Gemini 3.1 Pro (High)`, `TRIO_DRIVER_* = gemini-cli` are set. Crucible live seam needs `CRUCIBLE_AGENT_LIVE=1`.
- **Verify tier before trusting a run:** after a shark call, read its `~/AppData/Local/Temp/agy-gemini-cli-*/agy.log` — a healthy call shows the model **resolved** (NOT `not in local config, defaulting`) and NO `not logged into Antigravity`.

---

## 9. Definition of done for this run

Stage 1 Master Plan converges (or round-cap HALTs) and John approves → Stage 2 decomposes into waves with per-wave acceptance criteria (done-when + Given/When/Then) and John approves → the well-formedness gate passes → emit the Foreman-ready doc-trio + `foreman.config.json` in the plan dir. Then Foreman builds it (separate step). The P3 WAL inversion is explicitly NOT part of this — it's queued as its own future Crucible pass.
