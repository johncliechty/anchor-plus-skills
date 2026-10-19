# Anchor R&D Surface v10 — "Live Handoff & Boneyard" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-17. Follows v9 "Tidy" (merged to master,
> HEAD `9baabf0`, GREEN 1068). Branch `foreman/rnd-surface-v10` off master `9baabf0`.
> From J.C. Liechty's live-use feedback on three flaws: the stage handoff auto-fires
> instead of letting him review the prompt; the grass workbench stacks two confusing
> terminals with no toggle; and killed/discarded session material is saved but has no
> findable home.

---

## North Star (locked — John's Stage-0 answers)

**Make stage transitions a reviewable, human-in-the-loop handoff (research → plan →
build); make the grass workbench a clean, two-terminal toggleable bench whose ideas
carry full lineage into project work; and give every discarded session a searchable
Boneyard home — all on the existing v4–v9 seams, stdlib-only, holding the v4 UI
verification standard.**

Three pillars, each a North-Star criterion. Every element of this plan must serve one
of them (the inclusion test); growth that serves them is welcome, non-serving bloat is
cut or Grasscatched.

### Pillar 1 — Live, seeded, paste-NOT-submit stage handoff

When the user clicks **Advance** (research → planning, and identically planning →
build):

1. The current session generates **two artifacts**: the existing structural
   `HANDOFF.md` **and** a new, durable, reviewable **`NEXT-PROMPT.md`** (the
   ready-to-run prompt — the exact text that will be pasted).
2. A new terminal panel opens for the next stage and the correct trio skill
   **auto-loads and greets** (research → **Crucible**; planning → **Foreman**) — the
   terminal becomes "ready".
3. The generated prompt is then **typed into the input line UNSENT** (no trailing
   newline) — cursor waiting. The user reviews, optionally edits/adds instructions,
   and presses **Enter** to run.
4. The two sessions are **linked** (the existing `parent_session_id` / `chain_id`
   lineage).

This is the **same structure and dynamics** for planning → build as for research →
planning.

### Pillar 2 — Clean grass workbench: two toggle terminals + full lineage

1. In the grass (idea) workbench, **Research** and **Plan** each get their **own**
   terminal area. Each button **toggles** its terminal (open → click again to
   close/minimize). No more two terminals stacked with nothing between them.
2. From a grass **research** dev session the user can **push research → plan** with the
   **same paste-NOT-submit seeded handoff** as Pillar 1, staying inside the grass
   workbench, linked.
3. The user can **archive** a grass research or planning dev session: its produced
   docs **and** its brainstorming summary are persisted into a per-idea bundle tied to
   **that specific grass idea** (survives session kill; available at promotion).
4. When the idea is **promoted to the project level**, all that material is available,
   and **every downstream project plan/build session traces back** to the originating
   grass idea (a `grass_origin` stamp riding the chain).

### Pillar 3 — The Boneyard (searchable store of discarded material)

1. A **per-project Boneyard** view: a searchable list of discarded ideas + docs.
2. Fed by three sources (locked): **hard-killed sessions that had material**,
   **v9-deleted sessions**, and **deleted grass ideas**.
3. The Boneyard is an **index, not a second copy** — it references the already-
   persisted docs (v8 keystone). It is **non-destructive**: a killed session keeps its
   normal finished tile *and* gets a Boneyard record; a v9-deleted session (whose tile
   + pointer-records are gone) finds its **only** remaining home here.
4. Search is **stdlib-only** substring/token matching over the entry's title, summary
   excerpt, originating idea text, and document paths/names.

---

## Locked decisions (Stage 0 user gates + Crucible inferences)

| # | Decision | Choice | Source |
|---|---|---|---|
| D1 | Handoff prompt delivery | **Two-phase**: skill auto-loads + greets, THEN prompt pasted UNSENT | John (gate) |
| D2 | Grass terminals | **Two independently-toggleable** terminals (research + plan) | John (gate) |
| D3 | Boneyard sources | **hard-killed (w/ material) + v9-deleted + deleted-grass-ideas** (NOT empty ghosts) | John (gate) |
| D4 | Boneyard scope | **Per-project** | John (gate) |
| D5 | Auto plan→build advance | Also goes **paste-pending** (no more silent auto-submit); the unattended advance opens the build with the prompt PENDING until the user looks | Crucible (inferred, stated) |
| D6 | Handoff artifacts | **Both** `HANDOFF.md` (structure, exists) **and** `NEXT-PROMPT.md` (the reviewable prompt) | Crucible (inferred) |
| D7 | Grass "archive" | A **new verb** = persist dev docs + summary into a per-idea bundle; distinct from `save_grass_refinement` (a text snapshot) | Crucible (inferred) |
| D8 | Grass→project lineage | A **`grass_origin`** field stamped on the chain so all downstream sessions trace back to the idea | Crucible (inferred) |
| D9 | Boneyard storage | **Index over already-persisted docs** (no second copy); per-project store under `.anchor/projects/<id>/boneyard/` | Crucible (inferred) |
| D10 | Boneyard for v9-delete | Capture the entry **BEFORE** `delete_session_efforts` drops the pointer-records | Crucible (inferred, risk-driven) |

---

## How it maps onto the existing seams (reuse, never fork)

| Concern | Existing seam (v4–v9) | v10 change |
|---|---|---|
| Seed delivery to PTY | `terminal_session.start_session(seed_context=…)` writes `seed_text` ending in `\n` (auto-submits) | **Split** into phase-1 (load+greet, ends `\n`) + phase-2 **pending paste** (no `\n`), delivered after greet |
| Prompt generation | `_build_seed_for_plan` / `_build_seed_for_research` (list real doc paths) | Reused to build the **`NEXT-PROMPT.md`** body + the paste text |
| Handoff doc | `handoff.prime_worktree` writes `HANDOFF.md` | Add `handoff.write_next_prompt` → `NEXT-PROMPT.md` |
| Linkage | `parent_session_id` / `chain_id`, `record_stage_link` | Unchanged; + `grass_origin` carried on the chain |
| Advance endpoints | `/api/rnd/advance_session`, `/api/rnd/finish_to_build`, `auto_advance_planning_to_build`, `reconcile_and_advance` | All deliver **pending paste** instead of auto-submit |
| Grass dev sessions | `effort_history.develop_grass_idea` (keyed by `(idea, lane)` in `dev_sessions`) | Already supports one-per-lane → host two terminals; + `archive_grass_session`, `export_grass_to_project` carries `grass_origin` |
| Doc persistence | `effort_history.persist_session_docs` (v8 keystone), `capture_session_docs` | Reused by archive + Boneyard capture |
| Session kill/delete | `terminal_session.kill` / `delete_session`, `effort_history.delete_session_efforts`, `delete_grass_idea` | Each emits a **Boneyard entry** at the right point |
| Storage | `.anchor/projects/<id>/<lane>/…` | + `.anchor/projects/<id>/boneyard/{index.json, entries/}` |

**New module:** `boneyard.py` (stdlib-only) — the per-project Boneyard index + search +
capture helpers. Added to `dist_manifest.txt`.

---

## The attended-vs-unattended handoff (D5 detail — the crux)

Today plan→build **auto-submits** on hard-kill / reconcile-dead / finish-to-build.
v10 removes auto-submit from **all** advance paths:

- **Attended** (user clicks *Advance to Planning* / *Finish → Build*): the new panel
  opens, the skill greets, the prompt is pasted **unsent** in front of the watching
  user.
- **Unattended** (reconcile-dead auto-advance, user not watching): the build session is
  started, the skill greets, and the prompt is held as a **pending paste** on the
  session record. The first time the user opens that panel, the prompt appears in the
  input line, unsent. Nothing fires without a human pressing Enter.

This makes "the model never starts work I didn't see" a global invariant, not a
per-button behavior.

---

## Out of scope (inclusion test — explicitly cut)

- **Boneyard "restore/revive"** (re-open a discarded session as a new seeded one). Nice,
  but not in the brief; the existing `continue_session` already covers reviving a
  *kept* session. Boneyard v10 is **browse + search + open-doc** only.
- **Global cross-project Boneyard** (D4 chose per-project). Not built.
- **Full-text/fuzzy search engine.** Stdlib substring/token match only.
- **Boneyard for empty/ghost sessions** (D3 excluded them — nothing to keep).
- **Auto-advance of research → planning.** Stays **manual** (button), as today.
- **Changing the v8 close-vs-kill semantics.** Kill still persists docs + keeps the
  finished tile; v10 only *also* indexes it in the Boneyard.

---

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** + the single lazy `pywinpty` exception (terminal only). The
  new `boneyard.py` is stdlib-only. `git`/`gh` stay external CLIs behind the existing
  stubbed seams.
- **Never bind/touch `:8777` or real data/network** in any test or healthcheck. Stub
  PTY (`ANCHOR_PTY_BACKEND=stub`) + stream-json stub runner + temp git projects + temp
  data dirs throughout.
- **Playwright is DEV-ONLY** (`pytest.importorskip`), never imported by product code;
  `distro.py`'s import scan stays green (only the declared `pywinpty` exception).
- **Token gate** on every mutating endpoint; GET endpoints read-only + traversal-safe.
- **f-string discipline:** `_PROJECT_WINDOW_JS` is a RAW single-brace string; literal
  `{`/`}` in f-string HTML/CSS doubled.
- **UI verification standard (the v4 lesson, non-negotiable):** every UI-changing wave
  requires rendered-DOM assertions (positive + negative) **+** a real Playwright +
  Chromium interaction test **+** an orchestrator screenshot checked against the
  rnd-v10 mockup **+** John's sign-off before merge. A string-grep-only test is an
  automatic wave HALT.
- **No merge to master / no `nssm restart anchor`** until John signs off on the UI
  waves. Then: merge, restart elevated, rescan each project.

---

## Adversarial review — Shark-Tank top findings (and mitigations)

| Risk | Finding | Mitigation (in the plan) |
|---|---|---|
| **R1 — paste/skill-load race** | Pasting the prompt before the skill finishes loading could interleave bytes into the load turn. | The pending paste is delivered **after** the greet line is observed (a `pending_paste` field on the record, flushed on the first `read_since` that contains the greet marker, or on first attach). Deterministic + stub-PTY testable. Wave 1. |
| **R2 — unattended auto-advance** | Removing auto-submit could strand an unattended build session. | D5: unattended advance holds a **pending paste**; the session greets but waits. Explicit, idempotent, tested via the reconcile-dead path. Wave 2. |
| **R3 — v9-delete ordering** | A Boneyard entry built *after* `delete_session_efforts` would have no docs to reference. | D10: capture the entry from `efforts_for_session_id` + cached summary **before** dropping pointer-records. Wave 6. |
| **R4 — Boneyard noise/dup** | Every hard-kill spamming the Boneyard; docs double-counted vs lane history. | Index-only (no copy); a killed session's normal tile is untouched. Hard-kill is already the deliberate "I'm done/discarding" action (close ≠ kill since v5), so it is good signal. Entries are lightweight. Wave 6. |
| **R5 — search scale/perf** | No external search engine allowed. | Stdlib token/substring match over a per-project JSON index; scale is hundreds of entries — trivially fast. Wave 6. |
| **R6 — grass two-terminal state** | Two live grass dev sessions per idea could collide. | `dev_sessions` already keys by `(idea, lane)`; one research + one plan is the natural max. Toggling hides/shows, never re-mints. Wave 3. |
| **R7 — lineage leakage** | `grass_origin` must not contaminate non-grass chains. | Stamped only when a session's chain root is a grass export/promote; defaults `""`; back-compat normalize. Wave 4. |
| **R8 — UI regression undetected** | The v4.1 lesson — a string-grep "GREEN" missed a broken hybrid UI. | Every UI wave: DOM positive+negative + real Playwright click test + screenshot vs mockup + sign-off. Waves 2,3,4,5,7. |

Convergence: after these mitigations the Shark Tank reached a **dry round** (no ≥2-Shark
BLOCKER remaining). John is the final convergence authority — the Stage-1 gate below.

---

## 🚦 Stage 1 gate

This Master Plan is presented for John's approval. On approval it freezes and Crucible
emits the wave-by-wave `IMPLEMENTATION-PLAN.md` (already drafted alongside this doc for
review). No branch is cut and no build starts until sign-off.
