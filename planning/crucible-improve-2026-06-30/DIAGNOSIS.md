# Diagnosis — Anchor Improvement Effort (Stage 0 brownfield ingest)

Grounded in a read-only T1 inventory of `C:\dev\Anchor` (2026-06-30). Labels:
**Confirmed** (read the code) / **Gap** (couldn't find / needs reproduce).

## The reframes (where code disagreed with observed behavior)

### ① Restart carry-on — root cause: discovered efforts aren't managed sessions
The resume machinery **exists** (`session_registry.py`, `summarizer.py`,
`terminal_session.attach()` replays the screen buffer, a `seeded` flag, per-stage
`summaries/`). It applies **only to sessions Anchor itself launched**. Older
brownfield efforts are stored as **"discovered" pointer-records** (`discovered:True`,
`effort_history.py` / `brownfield_scan.py`) with no session record, no summary, no
skill seed. Clicking one opens a **cold** terminal — no skills, no doc reading, no
phase memory. **Fix = promote discovered/brownfield efforts to first-class
resumable sessions** (Pillar A). *Confirmed.*

### ② Gandalf is not map-reduce
`gandalf.py` runs a **single Stage-A agentic pass** (`claude -p` with
`--add-dir <folder>`) then a Stage-B host grader (`gandalf-run.mjs`). No fan-out /
reduce. Over a tree as large as `C:\dev`, one pass goes shallow → thin findings.
"Doesn't show immediately" = the index sits at `ok:false,
reason:"generation in progress"` with **no UI affordance** until both stages finish.
**Fix = a genuine map-reduce decomposition + an in-progress/queued indicator**
(Pillar B). *Confirmed.*

### ③ Context-window warning is not Anchor's code
**No** context/token warning exists anywhere in Anchor (`Gap`). The banner is almost
certainly the **embedded Claude Code harness's own** warning surfacing inside the
Anchor terminal, fired on a fresh session. **Fix likely = suppress / contextualize
in the terminal pane**, not tune an Anchor threshold. **Reproduce first** to confirm
the source (Pillar B).

### ④ Claude default — already true; handoff doc is the gap
`DEFAULT_ENGINE = BACKEND_CLAUDE` (`terminal_session.py`). Windows already defaults
to Claude. `switch_engine()` re-seeds once but **writes no carry-on/summary doc** on
model switch. **Fix = auto-create + auto-load a handoff/summary doc on switch**
(Pillars A + C). *Confirmed.*

### ⑤ Claude-orchestrates-Gemini 5:1 — net-new, with a constraint
**No 5:1 capability exists.** `lanes.py` limits Gemini to the research lane
(Crucible/Foreman are Claude-Code engines Gemini can't run). Correct shape: **Claude
stays orchestrator/driver; the swarm *sub-agents* it spawns are Gemini at 5:1**;
Claude does synthesis / double-checks / management. Single-subscription users fall
back cleanly, **never cross-calling**. *Confirmed (absence).* **This is the biggest
build item.**

### ⑥ Terminal controls — three actions exist
`×` close = **tile / non-destructive / reopenable** (`closePanel`). `🗑` =
**hard-kill** (`killPanel` → `POST /api/rnd/term_kill`, reaps PTY + worktree, drops
tile). **Boneyard** = archival index (`boneyard.py`, v10). User wants: **remove the
redundant hard-kill, keep Boneyard, `×` = archive-and-resume.** *Confirmed.*

### ⑦ Two gaps to reproduce after lock
- **"Previous efforts" expander** *exists* in code (`efforts_by_lane[lane][1:]`,
  `anchor_gui.py` ~1993–2478 / `render_project_window_html`) but the user didn't see
  it on the research tab — likely renders only when >1 effort exists, or is
  mis-scoped. **Reproduce.**
- **Swarm *warning* emitter** is separate from the hunter's (sound) kill logic
  (`zombie_hunter.classify()` only KILLs our-process/running/not-attached). The false
  warning on *attached* swarms is a UI/census signal not pinned in the inventory.
  **Reproduce + locate the emitter.**

### Trivially-confirmed fixes
- **Deliverables always-expanded** — `render_deliverables_html` (`anchor_gui.py`
  ~10095). Add collapse-by-default. (Pillar B, #4)
- **Terminal width init** — `.panel.pin` defaults narrow (`max-width` / 360px
  min-width, `anchor_gui.py` ~4695); xterm fits the narrow box on open, grows only on
  resize/maximize. Init `width:auto` or call fit-addon on open. (Pillar B, #8)

## Scope ledger (11 items)
1. Swarm-warning false positives on attached swarms → orphan-only. (B)
2. Gandalf thin reports + no immediate render → real map-reduce + progress indicator. (B)
3. Latest-effort-per-tab + "previous efforts" link (per-project + workbench). (B)
4. Deliverables collapsed by default. (B)
5. Terminal controls: keep Boneyard, remove redundant hard-kill, `×` = archive. (B)
6. Effort restart = true carry-on (phase + docs + skills + summary). (A) — *keystone*
7. Context-window warning realistic / suppressed-when-false. (B)
8. Terminal full-width from open. (B)
9. Claude default on Windows + model-switch handoff doc auto-loaded. (A/C)
10. Default exec = Claude-orchestrates-Gemini 5:1, single-sub fallback. (C) — *biggest build*
11. (folded into #1)

## Substrate reality (read before Stage 1)
The 5:1 Claude→Gemini sub-agent capability **does not exist yet IN ANCHOR** and is
item #10. The Gemini backend driver exists only for the research lane today.

**UPDATE 2026-06-30:** an *orchestration-level* bridge DOES exist —
`C:\dev\Skill Foundry\tools\agy-dispatch.mjs` (Claude writes short prompts, Gemini
reads/edits on its own tokens via the `agy` CLI; no-shell STEER, `windowsHide`). It
is what verified this diagnosis (3 read-only Gemini swarms + 2 focused re-tasks).
So the 5:1 pattern is usable to BUILD this effort even though Anchor's in-product
5:1 (#10) is still net-new.

---

## CORRECTIONS — post-Gemini-swarm code verification (2026-06-30)

Five Gemini swarms read the real code. Net corrections to the Stage-0 reads above:

- **#7 context-window warning — REVERSED. It IS Anchor's own code** (not the embedded
  harness). `terminal_session.py:1309-1313` (`CONTEXT_FULL_BUDGET_BYTES=200_000`,
  `CONTEXT_FULL_RATIO=0.8`) + `context_fullness()` (`1342-1380`): it warns at 80% of a
  200 KB budget, but "context" = **UTF-8 byte length of the live PTY buffer** (all
  printed terminal output, seed included). A fresh session that seeds a big skill
  prints past 160 KB fast → fires on a new session. Banner markup `dockWarn`
  (`anchor_gui.py:3759-3763`); poller `_startDockContextPoll` every 8 s
  (`9444-9467`); route `/api/rnd/context_status` (`14398-14425`). **Fix = replace the
  bad proxy** (measure bytes *since seed completion*, raise budget, or use a real token
  signal), NOT suppress a foreign banner.

- **#1 swarm warning — root cause pinned.** Emitter `_ORPHAN_ALERT_JS`
  (`anchor_gui.py:13340-13386`) polls `/api/rnd/orphan_check` (`14613-14648`) every
  45 s. The "attached/live" set is `live_ids = pty_manager.live_sessions()` — **only
  the ConPTY sessions pty_manager is actively streaming**. Any *registered-running*
  session whose PID matches but is not in that streaming set is classed `kill`
  (`zombie_hunter.classify`, `zombie_hunter.py:151-170`) → banner (gated also by
  `created_at >= _SERVER_BOOT_TS`). **A legit, effort-bound, work-doing session with
  no open browser stream falls out of `live_ids` → false warning.** Fix = broaden
  "attached" to include registered-running effort-bound sessions with a live PID (or
  `classify` abstains, not kills, when effort-bound).

- **#6 resume keystone — exact seam.** Discovered effort card onclick is just
  `openReport('/artifact/…')` (`anchor_gui.py:2133`) — no resume-as-session at all.
  When resumed via `/api/rnd/continue_session`, the seed is `_build_continue_seed`
  (`1330-1408`), which loads from the **session-registry record + cached summary**;
  discovered efforts have **neither** → returns `""` → `start_session`
  (`terminal_session.py:405-585`) gets `seed_context=""` → **cold** terminal (default
  lane skill only). Fix = on registry/summary miss, scan the effort's on-disk docs and
  synthesize a digest; add a real "resume as session" affordance to discovered cards.

- **#3 previous-efforts link — confirmed + nuance.** `_render_lane_sessions`
  (`anchor_gui.py:4006-4036`): `older = session_views[1:]`, `if not older: return
  recent` → the expander renders **only when ≥2 sessions exist**. Layout-D
  `_render_layoutd_zone` (`3231-3269`) same. If the user saw *multiple* research
  efforts and still no link, the real bug is **discovered efforts not entering
  `session_views`** — couples #3 to the #6 keystone. Main/grass workbench doesn't
  slice at all.

- **#5/#13 terminal controls — exact inventory.** A panel header carries FOUR controls
  (`anchor_gui.py:4705-4722`): `–` min · `×` `.close` (non-destructive tile,
  reopenable) · `🗑` `.hardkill` (confirm → `term_kill` → reap PTY+worktree, **no
  Boneyard**) · `✕` `.delete` (v9 true-delete, removes the record). The Layout-D dock
  instead has `Kill → Boneyard` (`dockKill()`, `3775-3776`). Project-level `Boneyard`
  button (`5194`) only opens the searchable discard browser. **Fix = every session's
  destructive action becomes `Kill → Boneyard` (better icon); `×` close stays the only
  non-destructive control; drop the redundant `🗑`/`✕`.**

- **#9 switch_engine — confirmed no handoff doc.** `switch_engine`
  (`terminal_session.py:756-826`) reaps the PTY, relaunches the other engine in the
  same worktree, re-seeds the lane skill ONCE; `seed_context` is used only if a caller
  passes it, and the switch path passes nothing. **Writes no carry-on/summary.** Fix =
  summarize before reap, feed as `seed_context` (or write `SWITCH-HANDOFF.md`).

- **#4 deliverables — confirmed always-expanded** (`render_deliverables_html`,
  `anchor_gui.py:10095-10182`); fix = `<details>` wrap.

- **#8 terminal width — confirmed.** `.panel .pin` (`4694-4695`) has no `width`
  (defaults `auto`) + `resize:both` → shrink-wraps to xterm's 80-col default; after
  maximize→restore the grid is already wide. Fix = `width:100%` on `.panel .pin` +
  ensure `fit()` runs on open.

- **#12 zombie page — confirmed static + a discrepancy.** Page
  `/api/rnd/zombie_hunter_report` (`14650-15036`) has **no auto-refresh**
  (no `setInterval`/SSE) → needs one. BUT an interactive terminal IS already wired
  (`Start Terminal` → `<iframe>` `/zombie_terminal` over `term_ws`; brief at
  `16429-16551`). User couldn't use it → **reproduce whether it's broken vs
  non-obvious** before scoping #12b as build-new.
