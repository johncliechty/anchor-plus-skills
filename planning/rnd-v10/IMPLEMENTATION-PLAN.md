# Anchor R&D Surface v10 — "Live Handoff & Boneyard" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-17. Frozen design: `MASTER-PLAN.md` +
> approved mockups under `_mockups/` (to be produced + signed off per UI wave). Build
> cwd = repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v10` (off master
> `9baabf0`, v9 merged, GREEN 1068).

test-command: python -m pytest -q

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time (do not
  hard-code). Synthetic test ids only in tests/healthcheck.
- **No live claude/gemini/real PTY:** stub via `tests/fake_claude.py` /
  `tests/stub_streamjson.py`; PTY via `ANCHOR_PTY_BACKEND=stub`; git/gh via the
  `worktrees._git` / `ANCHOR_GH_CMD` seams (`tests/stub_gh.py` + local bare remote).
- **pywinpty** lazy-only (in `pty_manager.py`); **Playwright DEV-ONLY**
  (`pytest.importorskip("playwright.sync_api")`); `distro.py` scan must stay green.
- **f-string discipline:** `_PROJECT_WINDOW_JS` is a RAW single-brace string; double
  literal braces in f-string HTML/CSS.
- **Security:** token gate on every mutating endpoint; GET read-only + traversal-safe.
- **Reuse, don't fork:** lean on the v4–v9 seams named in `MASTER-PLAN.md`.
- **Scoped commits:** code/test only; never commit runtime-data churn (`.anchor/`,
  `rnd_jobs/`, `health_reports/`).
- **Baseline:** v9 = 1068 passed, 1 skipped. Each wave holds or grows the count.
- **UI VERIFICATION MANDATORY** (v4 lesson) for every UI-changing wave: rendered-DOM
  positive+negative **+** real Playwright/Chromium interaction test **+** screenshot vs
  the wave's mockup **+** John's sign-off. String-grep-only = wave HALT.
- **New product module this version:** `boneyard.py` (stdlib-only) → add to
  `dist_manifest.txt`; the import scan must accept it as first-party.

---

## Wave 1 — Paste-NOT-submit handoff substrate (backend only)

**Goal.** Split seed delivery so the trio skill auto-loads/greets, then the task prompt
sits in the PTY input **unsent** until the user presses Enter.

**Changes.**
- `terminal_session.py`: add a `pending_paste` concept. `start_session(...,
  paste_prompt=None)` writes **phase-1** (the existing load+greet seed, ends `\n`) and
  records `paste_prompt` on the session registry record as `pending_paste` **without**
  writing it yet. Add `_flush_pending_paste(session_id)` that writes `pending_paste` to
  the PTY **without a trailing newline** exactly once, after the greet is observed
  (first `read_since`/`attach` whose buffer contains the greet marker, or first
  attach), then clears the field (records `paste_flushed=True`).
- Keep the existing `seed_context` path working for back-compat (no `paste_prompt` →
  today's behavior, but see Wave 2 which routes advances through the new path).
- `session_registry.py`: normalize the two new record fields (`pending_paste: str=""`,
  `paste_flushed: bool=False`); old records back-compat to empty/False.

**Done-when.** A session can be started so that (a) the load+greet turn is submitted,
(b) the task prompt is delivered to the PTY with **no trailing newline**, (c) it is
delivered **once**, after the greet, and never re-sent on later reads/attach.

**Given/When/Then.**
- *Given* a stub-PTY session started with `paste_prompt="PLAN FROM X"`, *When* it is
  started and read until the greet appears, *Then* the PTY input buffer contains
  `PLAN FROM X` with **no** trailing newline and `pending_paste` is cleared +
  `paste_flushed=True`.
- *Given* the same session, *When* `read_since`/`attach` is called again, *Then* the
  paste is **not** re-emitted (idempotent).
- *Given* a session started **without** `paste_prompt`, *Then* behavior is exactly as
  v9 (regression guard).

**Tests.** `tests/test_pending_paste_v10.py` (stub PTY; assert no-newline, once-only,
back-compat). No UI.

---

## Wave 2 — Both-artifact handoff + advance routed through paste (research→plan & plan→build)

**Goal.** Every advance generates `HANDOFF.md` **and** `NEXT-PROMPT.md`, links the
sessions, and delivers the prompt as a **pending paste** (attended) or holds it pending
(unattended). This wave is **backend + the advance endpoints**; the visible panel UX is
Wave-2b is folded into the existing inline panel (the panel already opens on advance),
so this wave's UI surface is the panel showing the pending prompt — verified by
Playwright here.

**Changes.**
- `handoff.py`: add `build_next_stage_prompt(folder, pid, from_session, to_lane)` →
  returns the reviewable prompt text (reuses `_build_seed_for_plan` /
  `_build_seed_for_research` doc-path logic) and `write_next_prompt(worktree_path,
  text)` → writes `NEXT-PROMPT.md` into the next stage's worktree (alongside
  `HANDOFF.md`).
- `terminal_session.py`: `auto_advance_planning_to_build`, `reconcile_and_advance`,
  and the explicit advance helpers pass the generated prompt as `paste_prompt` (Wave 1)
  instead of folding it into the auto-submitted seed. The load+greet still fires;
  the task prompt is pending.
- `anchor_gui.py`: `/api/rnd/advance_session` and `/api/rnd/finish_to_build` build both
  artifacts, start the next session with `paste_prompt`, link via
  `parent_session_id`/`record_stage_link`, and return the new session record. The
  frontend opens the panel and the pending prompt appears in the terminal input unsent.

**Done-when.** Clicking Advance (research→plan) and Finish→Build (plan→build) each:
writes both artifacts into the next worktree, starts a **linked** next-stage session,
and the next terminal shows the prompt **pasted but unsent**; pressing Enter runs it.

**Given/When/Then.**
- *Given* a finished research session with persisted report docs, *When*
  `advance_session` is called, *Then* the new planning session's worktree contains
  `HANDOFF.md` + `NEXT-PROMPT.md` (both referencing the real doc paths), the planning
  record has `parent_session_id == research_sid` and shares the `chain_id`, and its
  `pending_paste` equals the `NEXT-PROMPT.md` body.
- *Given* a planning session with a MASTER+IMPL plan set, *When* `finish_to_build`
  fires, *Then* a single linked build session opens with both artifacts + the prompt
  pending (idempotent on `parent_session_id`).
- *Given* the reconcile-dead unattended path, *Then* the build session greets and holds
  the prompt **pending** (nothing auto-submitted) until first attach flushes it unsent.

**Tests.** `tests/test_advance_artifacts_v10.py` (backend: both artifacts, linkage,
pending paste, idempotency) + `tests/test_advance_paste_ui_v10.py` (Playwright: click
Advance → new panel → assert the input line shows the prompt text and it is **not** yet
submitted; screenshot). **UI wave — full verification + sign-off.**

---

## Wave 3 — Grass workbench: two independently-toggleable terminals (UI)

**Goal.** Research and Plan each get their own terminal area in the grass workbench;
each button toggles its terminal open/closed. No stacked-with-nothing-between.

**Changes.**
- `effort_history.develop_grass_idea`: already keyed by `(idea, lane)` in
  `dev_sessions` — confirm two concurrent dev sessions (research + plan) per idea are
  supported; no re-mint on re-click (focus/toggle only).
- `anchor_gui.py` `_PROJECT_WINDOW_JS` + grass workbench HTML/CSS: render **two**
  labeled, collapsible terminal hosts (research, plan), each with a ▾/▸ toggle on its
  button. Toggling shows/hides (minimize) that terminal without killing the session;
  the other is independent. Reuse the `term_ws`→`term_stream2` transport.
- Build the approved mockup `_mockups/grass_two_terminals.html` first.

**Done-when.** In the grass workbench, clicking Research opens its terminal; clicking
Plan opens a **separate** terminal; clicking either again collapses **only** that one;
both sessions stay live while collapsed.

**Given/When/Then.**
- *Given* an idea, *When* Research is clicked then Plan is clicked, *Then* two distinct
  terminal hosts exist, each bound to its own session id, visually separated/labeled.
- *Given* both open, *When* Research's toggle is clicked, *Then* only the research
  terminal collapses; the plan terminal and both sessions remain live.
- *Negative:* a fresh idea with no dev sessions renders both toggles **collapsed** with
  no orphan terminal host.

**Tests.** `tests/test_grass_two_terminals_v10.py` (DOM positive+negative) + Playwright
(click Research, click Plan, assert two hosts; toggle each; screenshot vs mockup).
**UI wave — full verification + sign-off.**

---

## Wave 4 — Grass archive + grass→project lineage back-reference

**Goal.** Archive a grass dev session's docs + summary into a per-idea bundle; stamp
`grass_origin` so all downstream project sessions trace back to the idea.

**Changes.**
- `effort_history.py`: add `archive_grass_session(pid, idea_id, lane)` → persist the
  dev session's produced docs (reuse `persist_session_docs`) + trigger/attach its
  cached summary, recorded as a per-idea **archive** bundle on the idea record
  (`archives: [{lane, session_id, docs:[rel...], summary_ref, when}]`); idea stays in
  grass. Distinct from `save_grass_refinement` (a text snapshot).
- `effort_history.export_grass_to_project`: stamp `grass_origin = idea_id` on the
  exported lane efforts **and** seed the chain so subsequent project plan/build sessions
  inherit it. `session_registry.py`: add normalized `grass_origin: str=""` field
  (back-compat empty); `chain_members`/projections carry it (SAFE — no worktree/branch).
- `terminal_session.start_session`: propagate `grass_origin` from parent when present.
- `anchor_gui.py`: archive button on each grass dev terminal; the idea panel lists
  archived bundles (doc links + summary). Project plan/build tiles whose chain carries
  `grass_origin` show a "from grass: <idea>" breadcrumb linking back to the idea.

**Done-when.** Archiving a grass dev session saves its docs + summary tied to the idea;
after promotion, a fresh project plan or build session in that chain shows a back-link
to the originating grass idea.

**Given/When/Then.**
- *Given* a grass research dev session that produced a doc, *When* archived, *Then* the
  idea record gains an archive bundle referencing that doc (on disk) + its summary, and
  the idea stays in grass.
- *Given* an exported idea, *When* a new project plan session is started in that chain,
  *Then* its record/projection carries `grass_origin == idea_id` and the UI shows the
  back-link.
- *Negative:* a non-grass session has `grass_origin == ""` and shows no breadcrumb.

**Tests.** `tests/test_grass_archive_lineage_v10.py` (backend: archive bundle,
grass_origin propagation, back-compat) + Playwright (archive button → bundle appears;
breadcrumb on a lineage tile; screenshot). **UI wave — full verification + sign-off.**

---

## Wave 5 — Grass research→plan live handoff (within the workbench)

**Goal.** From a grass research dev session, push research → plan using the **same**
paste-NOT-submit seeded handoff (Wave 1/2), staying in the grass workbench, linked.

**Changes.**
- `effort_history.py` / `terminal_session.py`: a grass advance helper that builds the
  next-stage prompt (Wave 2) from the research dev session's docs, starts the grass
  **plan** dev session with `paste_prompt` (Wave 1), links it
  (`parent_session_id`/`record_stage_link`, carries `grass_origin`), and toggles its
  terminal open in the workbench (Wave 3).
- `anchor_gui.py`: an "Advance to Plan →" control inside the grass research terminal;
  on click the grass plan terminal opens with the prompt pasted unsent.

**Done-when.** Inside the grass workbench, advancing from the research terminal opens
the plan terminal with the prompt pasted-but-unsent and the two grass dev sessions
linked.

**Given/When/Then.**
- *Given* a grass research dev session with material, *When* "Advance to Plan" is
  clicked, *Then* the grass plan dev terminal opens, its `pending_paste` equals the
  generated prompt (unsent), and it is linked to the research dev session +
  carries `grass_origin`.
- *Negative:* advancing with no research material yields an honest note (no fabricated
  prompt), no plan session minted.

**Tests.** `tests/test_grass_advance_v10.py` (backend) + Playwright (click Advance in
grass research → plan terminal opens with pending prompt; screenshot). **UI wave — full
verification + sign-off.**

---

## Wave 6 — Boneyard store + capture wiring (backend + new module)

**Goal.** A per-project Boneyard index over discarded material, fed by hard-kill,
v9-delete, and grass-idea-delete; stdlib search.

**Changes.**
- **NEW `boneyard.py`** (stdlib-only): `record_entry(folder, pid, entry)`,
  `list_entries(folder, pid)`, `search(folder, pid, query)` (token/substring over
  title + summary excerpt + idea text + doc paths), `get_entry(folder, pid, entry_id)`.
  Store: `.anchor/projects/<id>/boneyard/index.json` + `entries/<entry_id>.json`. Entry
  shape: `{entry_id, source: "killed"|"deleted"|"grass-deleted", session_id, lane,
  title, summary_excerpt, doc_rels:[...], idea_text, when}`. Index references the
  already-persisted docs (no copy). Idempotent upsert on `entry_id` (content-addressed).
- Wire capture:
  - `terminal_session.kill`: **after** docs persist, if the session produced material,
    `boneyard.record_entry(source="killed", ...)` (best-effort; never blocks kill).
  - `terminal_session.delete_session`: **before** `delete_session_efforts` drops the
    pointer-records, build the entry from `efforts_for_session_id` + cached summary
    (D10), then `record_entry(source="deleted", ...)`.
  - `effort_history.delete_grass_idea`: capture idea text + any dev docs into
    `record_entry(source="grass-deleted", ...)` before purge.
- Add `boneyard.py` to `dist_manifest.txt`.

**Done-when.** Killing a session with material, deleting a session, or deleting a grass
idea each leaves a searchable Boneyard entry that references the kept docs; search finds
it by title/summary/idea/doc terms.

**Given/When/Then.**
- *Given* a stub session that produced a doc, *When* hard-killed, *Then* a `killed`
  Boneyard entry exists referencing that doc's rel path, with a summary excerpt.
- *Given* a v9-delete, *Then* a `deleted` entry is captured **before** the pointer-
  records are dropped (the entry's `doc_rels` are non-empty even though the efforts are
  gone).
- *Given* a deleted grass idea, *Then* a `grass-deleted` entry holds the idea text.
- *Given* three entries, *When* `search("cache")` runs, *Then* only the matching
  entries return; non-destructive (no docs removed).

**Tests.** `tests/test_boneyard_v10.py` (stub PTY + temp git: capture on
kill/delete/grass-delete, ordering for v9-delete, search, idempotency) +
`tests/test_distro_scan_v10.py` (or extend existing) asserting `boneyard.py` is
first-party-clean. No UI in this wave.

---

## Wave 7 — Boneyard UI (per-project view)

**Goal.** A per-project Boneyard tab/view: searchable list of discarded items, open
doc links, view summary.

**Changes.**
- `anchor_gui.py`: `GET /api/rnd/boneyard?project_id=<id>&q=<query>` (read-only, token
  via `?token=`) → SAFE projection of entries (no absolute paths/worktree). A Boneyard
  tab in the project window rendering the entry list + a search box; each entry expands
  to summary + doc links (via `/report` / `/artifact`).
- Build the approved mockup `_mockups/boneyard.html` first.

**Done-when.** The project window has a Boneyard view that lists discarded entries,
filters live by the search box, and opens each entry's docs/summary.

**Given/When/Then.**
- *Given* a project with Boneyard entries, *When* the Boneyard tab is opened, *Then*
  the entries render (newest-first) with source badges and doc links.
- *Given* the search box, *When* a term is typed, *Then* the list filters to matching
  entries (calls the GET endpoint or filters the loaded set).
- *Negative:* a project with no discarded material shows an honest empty state.

**Tests.** `tests/test_boneyard_ui_v10.py` (DOM positive+negative) + Playwright (open
tab, type search, assert filtered list, open a doc link; screenshot vs mockup). **UI
wave — full verification + sign-off.**

---

## Wave 8 — CLI mirror + healthcheck v10 + distro scan + docs (PROJECT DONE)

**Goal.** Mirror the read seams into `anchor.py`, add the fully-stubbed healthcheck
walk, keep distro green, update docs.

**Changes.**
- `anchor.py` (read-only, honest-absent):
  - `rnd boneyard <pid> [--search <q>]` → `boneyard.list_entries` / `boneyard.search`
    (SAFE projection; honest "No discarded material" when empty).
  - `rnd next-prompt <pid> --session <id>` → the generated `NEXT-PROMPT.md` body for a
    session's handoff (read-only; honest absent). *(Delete/move/live-paste stay
    interactive — no one-shot CLI, consistent with prior versions.)*
- `anchor_healthcheck.py`: `check_rnd_v10_surface(report, server_proc, rnd_env)` —
  fully stubbed (stub PTY + stream-json stub runner + temp `ANCHOR_WORKTREE_BASE` +
  temp git project + temp data dir), walks: (a) pending-paste once-only/no-newline;
  (b) advance writes both artifacts + links + pending paste (attended) and the
  reconcile-dead unattended path holds pending; (c) two grass terminals supported +
  archive bundle + `grass_origin` propagation; (d) grass research→plan advance pending
  paste; (e) Boneyard capture on kill/delete/grass-delete (incl. the v9-delete ordering)
  + search. Reaps every stub PTY + synthetic session row, restores all forced env, tears
  down temp dirs, never binds `:8777`/touches real data/network. Register in `main()`.
- `distro.py`: `boneyard.py` in `dist_manifest.txt`; import scan green (only the
  declared `pywinpty` exception; Playwright never in product code).
- Update `CLAUDE.md` (v10 section + file-structure + endpoint table + CLI mirror) and
  the auto-memory pointer.

**Done-when.** `python -m pytest -q` ≥ the v9 baseline (1068) + the new v10 tests, all
green; the healthcheck v10 walk passes fully stubbed; `distro.py` scan green; docs
updated.

**Given/When/Then.**
- *Given* a project with Boneyard entries, *When* `anchor.py rnd boneyard <pid>
  --search <q>` runs, *Then* it prints the matching entries (read-only) and exits 0.
- *Given* the healthcheck, *When* `check_rnd_v10_surface` runs, *Then* every sub-step
  passes with no real PTY/claude/`:8777`/network and full env+temp teardown.
- *Given* the distro scan, *Then* `boneyard.py` is accepted as first-party and no new
  third-party import is introduced.

**Tests.** Extend the healthcheck self-test; `tests/test_cli_rnd_v10.py`; distro scan
test. No UI.

---

## Wave dependency / ordering

```
W1 (paste substrate, backend)
  └─> W2 (both-artifact advance + paste, UI)        ← Pillar 1 complete
W3 (grass two terminals, UI)
  └─> W4 (grass archive + lineage)
        └─> W5 (grass research→plan handoff, reuses W1/W2)   ← Pillar 2 complete
W6 (Boneyard store + capture, backend + new module)
  └─> W7 (Boneyard UI)                              ← Pillar 3 complete
W8 (CLI + healthcheck + distro + docs)              ← PROJECT DONE
```

W1→W2 and W6→W7 are hard chains. W3→W4→W5 is the grass chain (W5 depends on W1/W2). W6
is independent of the grass/handoff work and could run in parallel by a separate
builder, but the single-Foreman default is sequential W1…W8.

## 🚦 Stage 2 gate

On John's approval this freezes and hands to Foreman:
`node foreman/bin/locate-plan.mjs --json planning/rnd-v10` must exit 0 before any build
wave runs. No branch is cut and no `nssm restart anchor` happens until the UI waves are
signed off.
