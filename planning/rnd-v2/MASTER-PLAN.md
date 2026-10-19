# Anchor R&D Surface v2 — Master Plan (frozen design)

> Crucible Stage 1 output, approved 2026-06-11. This is the frozen design for the
> second-generation R&D control surface. It supersedes the surface shipped by
> `planning/rnd-v1/` (which built the registry, per-project store, Kanban window,
> brownfield discovery, and the launch console). v2 does **not** rebuild those —
> it corrects how history is grouped, summarized, and surfaced, and replaces the
> raw-log launch console with an interactive terminal.

## North Star (locked)

Make Anchor's R&D surface a **truthful, useful memory** of each project's trio
work. Concretely:

1. **Imported history is first-class history.** A brownfield-discovered trio run
   counts as real project history, not a second-class `import` placeholder. A
   small honest "imported" provenance chip is fine; the lane status must reflect
   the *activity*, not masquerade it as empty.
2. **One trio run = one session.** A research / plan / build run is shown as a
   single *session* the user reads as a clean summary — not as N separate
   per-file cards (today one Crucible run shows as 7 planning cards).
3. **Cached, validated summaries.** Clicking a session opens a nicely rendered
   markdown **summary** (goal · files-with-links · findings · errors-overcome),
   generated **once with multi-run validation** and **cached** so the same
   summary appears every time. Never the raw execution log or a raw JSON dump as
   the primary view.
4. **Most-recent + expander.** Each lane shows the most-recent session with a
   "previous sessions" expander, not a wall of every run.
5. **Grass Catchers.** A 5th lane for future ideas, fed by manual add, promote
   from `INBOX.md`, and discovery of idea-docs.
6. **Deliverables reflect what shipped.** The real deliverable (e.g. the running
   `anchor_gui.py` web app) is representable even though it is not under a
   `deliverables/` directory.
7. **Interactive terminal.** "New research / plan / build" opens an interactive
   terminal that already knows the trio skill for the lane (research→researchPrime,
   plan→Crucible, build→Foreman), lets the user converse turn-by-turn, and on exit
   auto-discovers what it produced and asks the user to confirm adoption as a session.

## Real intent (the Parable of the Oranges)

The user is not asking for cosmetic tweaks. The deeper goal is for Anchor to be
the **control tower for trio-driven R&D across projects** — a place that
faithfully remembers what research/plans/ideas/builds exist for each project and
makes it cheap to both review past work and launch new work. Every element below
must serve that. Bloat that does not serve it is cut or sent to Grass Catchers.

## Current-state ground truth (brownfield ingest, 2026-06-11)

- **Effort model** (`effort_history.py`): an "effort" is an append-only per-lane
  pointer-record. Discovered efforts carry `source:"discovered"`; real runs do
  not. `rnd_registry.status_line()` returns `has-runs` / `imported` / `none-yet`.
- **Discovery** (`brownfield_scan.py`) extracts **title + kind + rel-path + mtime
  only** — no summary, findings, north-star, files-produced, or errors. Each
  discovered *file* becomes its own card; there is **no session grouping**.
- **Why the active project's summary lies:** the active Anchor project
  (`2fe37f39157f4c7aa3e2523baa41f40f`) has planning=7/build=3 — all *discovered*
  → renders as `Planning: import / Build: import`. Research=0 because the real
  researchPrime report lives under a **retired sibling** project-id
  (`227eb089706140388b829776d87e57c8`) for the same folder. The real deliverable
  (`anchor_gui.py`) is at repo root, not under `deliverables/`, so it is never found.
- **Launch console** (`lanes.py`, `job_runner.py`, project-window JS): a one-shot
  `claude -p --output-format stream-json` job with a canned per-lane seed; the
  console dumps **raw stream-json lines**; the "Ask" box writes a stream-json turn
  to the job's stdin (`gate_adapter.py`). Lane→skill mapping already exists in
  `lanes.py`. The report viewer (`report_viewer.py`) **already** renders
  markdown→HTML with vendored KaTeX; the ugly views are discovered plan-docs
  served raw via `/artifact` and build `*.json` served as raw JSON.
- **Registry** has 3 retired test "Anchor" ids + 1 active, all → `C:\dev\Anchor`.

## Architecture (frozen)

### A. Session model
A **session** = the set of artifacts from one trio run.
- Run sessions group by the job's `job_id` / `output_dir` (already 1:1).
- Discovered sessions group by common parent directory (`planning/brownfield-discovery/`
  is one session, `planning/rnd-v1/` another). Fallback grouping key for flat
  folders = `skill` + run-timestamp cluster.
- Session record: `{session_id, lane, skill, timestamp, title, member_files[],
  provenance: "run"|"imported", summary_ref}`.
- A new `sessions.py` wraps `effort_history`. `list_sessions(folder, pid, lane)`
  returns sessions newest-first. A manual **merge/split** escape hatch exists for
  mis-grouped discovered files.

### B. Cached, validated summaries
Per session, a **bounded summarizer** (`summarizer.py`) reads member docs and
emits a structured `summary.json` + rendered `summary.md`, then caches them
(git-tracked, small). Generation is **extraction-seeded** (pull headings, the
North-Star line, the findings section) so it is anchored, generated **twice**,
then a **validation pass drops any claim not grounded** in the member docs before
caching. Lane-specific shape: research → question · findings · reports; planning →
goal · key decisions · files-produced(links); build → what-was-built · Crucible
docs referenced · errors-overcome · files-produced. A **Regenerate** action
re-runs it. Summaries are testable against `tests/fake_claude.py` via
`ANCHOR_RUNNER_CMD` — **never live `claude` in the gate**.

### C. First-class imported history
`status_line` returns per-lane **counts + provenance**, not `import`. "imported"
becomes a per-card chip. Tiles gain a **project blurb** (what the project is —
generated-once + user-editable, seeded from `CLAUDE.md`/`README`/`Anchor.md`) and
a real per-lane summary line.

### D. Folder-history unification + reconcile + deliverables
Rescan adopts sessions from **sibling project-ids for the same folder**. A
one-time, **explicit and reviewable** reconcile folds the retired test ids' real
sessions into the active id, then **hard-deletes** the test ids (user-approved:
"fold history into active, then delete tests"). Deliverables may be **declared**
via an `Anchor.md` marker or **manually pinned**, not only discovered under
`deliverables/`.

### E. Interactive terminal (substrate decision: stream-json REPL)
A true ConPTY terminal needs a native dependency, which violates Anchor's
stdlib-only / no-compiled-assets rule. So v2 keeps the terminal **feel** (vendored
**xterm.js**, exactly as KaTeX is already vendored) over a **persistent
`stream-json` REPL**: one long-lived `claude`/`gemini` process per session, user
turns POSTed to stdin, assistant output streamed back via **SSE** (stdlib-friendly;
replaces the 1.5s poll). It generalizes the existing gate-stdin mechanism,
auto-seeds the right skill per lane, and on exit auto-discovers produced files and
asks the user to confirm adoption as a session.

### F. Grass Catchers
New `grass` lane dir + Kanban column. Sources: manual add, promote from
`INBOX.md`, and discovery of idea-docs (`SAVED_FOR_LATER`, un-run `*PLAN.md`
stubs, scoping notes).

### G. Task linking
Surface the existing `link_task`: a Link affordance in the window, a linked-tasks
strip, and the reverse (project → its tasks).

## Constraints (inherited + binding)

- **Python stdlib only at runtime.** No third-party runtime deps. `pytest` is
  dev/test-only. Vendored client JS (KaTeX, and now **xterm.js**) is allowed as a
  static asset; **no native/compiled assets** (this is why the terminal is a
  stream-json REPL, not ConPTY).
- **Markdown/JSON files are the source of truth.** Pointer-records and small
  summary JSON are git-trackable (C9); raw logs / heavy artifacts stay ignored (C10).
- **`anchor_gui.py` HTML is f-string-generated** — literal `{`/`}` in CSS/JS must
  be doubled; the `_PROJECT_WINDOW_JS` block is a RAW single-brace string.
- **Mirror CLI:** new backend functions are mirrored into `anchor.py`.
- **Test gate:** `python -m pytest -v`. The runner/terminal/summarizer waves
  verify against `tests/fake_claude.py` via `ANCHOR_RUNNER_CMD`; **never live
  `claude` in the gate.**
- **Single-instance / NSSM service** runtime is unchanged; no Stop button, no
  `/api/shutdown`.

## Out of scope (Grass Catchers for a later run)

- Real ConPTY terminal fidelity (would require waiving the stdlib rule).
- Cross-machine sync of `.anchor/` stores.
- A general LLM chat unrelated to the trio lanes.
