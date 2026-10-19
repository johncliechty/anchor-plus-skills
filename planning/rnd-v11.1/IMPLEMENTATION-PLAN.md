# Anchor R&D Surface v11.1 — "Handoff Always Primes" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-20. Frozen design: `MASTER-PLAN.md`. Build cwd
> = repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v11.1` (off master `b6719bd`,
> v11 merged, GREEN 1232).

test-command: python -m pytest -q

## Conventions (read before any wave)

- **No live claude/gemini/real PTY:** stub via `tests/fake_claude.py` /
  `tests/stub_streamjson.py`; PTY via `ANCHOR_PTY_BACKEND=stub`; git via the
  `worktrees._git` seam; temp dirs throughout.
- **THE v11 LESSON, hardened:** every advance/handoff test is WORKTREE-ONLY (no
  `eh.record_effort` pre-persist). The KEY new coverage is the **CONVERSATION-ONLY**
  case: write NOTHING to the worktree, instead seed the **stub PTY read buffer** with
  simulated transcript content, advance, assert the transcript is captured + persisted +
  named in the prompt + the next session opens. A pre-persisted/pre-written-file test is
  prompt-building coverage, never the sole coverage of an advance path.
- **pywinpty** lazy-only; **Playwright DEV-ONLY** (`pytest.importorskip`); `distro.py`
  green. f-string/RAW-string discipline (`_PROJECT_WINDOW_JS` RAW single-brace).
- **Snapshot is best-effort + idempotent** and must NEVER break an advance if it fails
  (degrade to the honest-minimal prompt).
- **Baseline:** GREEN 1232, 1 skipped. Each wave holds or grows.
- **UI verification** (v4 lesson) for the grass UI wave: rendered-DOM (pos+neg) + real
  Playwright + screenshot vs mockup + John's sign-off.

---

## Wave 1 — Keystone: transcript snapshot + honest no-docs prompt (backend, the core fix)

**Goal.** The shared `prepare_stage_handoff` keystone captures conversation-only research
and builds an honest, actionable prompt — fixing all four advance paths at the source.

**Changes.**
- `handoff.py`: rewrite the no-docs fallback in `build_next_stage_prompt` (~609-616 +
  the build fallback ~627-630). New text is HONEST (no false "report is in this
  worktree") and ACTIONABLE per skill: planning → *"With Crucible loaded: no written
  research artifact was produced upstream. Review the upstream research (transcript/
  summary if present), then CREATE the planning materials — a Master Plan and an
  Implementation Plan — grounded in the project objective."*; build → the Foreman analog
  ("create/execute the build from the plan; if the plan is thin, reconstruct it from the
  upstream context"). Never claims a doc exists that doesn't.
- `terminal_session.py` `prepare_stage_handoff` (~1670): after the initial
  `capture_session_docs` persist (~1731), if `out["persisted"]` is **empty** (D4 — no
  document-classified doc produced), SYNCHRONOUSLY snapshot the source session's
  transcript: read `pty_manager.read_since(source_session_id, 0)`, clean it (strip the
  recorded seed/greet prefix using the record's `seed_text`; strip ANSI/control
  sequences; cap length keeping the tail), and write it to
  `<source_worktree>/<source_lane>/<short-sid>-transcript.md` (deterministic filename;
  `_is_document_rel`-valid: `.md` under the lane dir). Then re-run `capture_session_docs`
  so the transcript is persisted + session-tagged. THEN build the prompt (so
  `research_set_for_session` finds the transcript → the real doc-referencing prompt).
  Best-effort: wrap the whole snapshot in try/except → on failure leave `persisted=[]`
  and fall to the honest prompt; never raise. The existing background-summary trigger
  (already in the keystone) now refines the persisted transcript.
- Add a small helper `terminal_session._snapshot_transcript_doc(record, ...)` (or inline)
  for the read+clean+write; keep it stdlib-only.

**Done-when.** For a source session whose docs live only as a CONVERSATION (transcript in
the PTY buffer, no written file): `prepare_stage_handoff` (a) snapshots the transcript to
`<lane>/<sid>-transcript.md`, (b) persists + session-tags it, (c) returns a prompt naming
that real path + a "review then create the materials" instruction, (d) `persisted` /
`doc_rels` are non-empty.

**Given/When/Then (the test that fails today).**
- *Given* a live research session (stub PTY) with simulated transcript content in its read
  buffer and NO file written to its worktree, *When* `prepare_stage_handoff(pid, rsid,
  'planning')` runs, *Then* `research/<sid>-transcript.md` is a file in the MAIN project +
  committed + a research effort tagged with `rsid`; `out["prompt"]` names it + says
  "create the … materials"; `out["doc_rels"]` contains it; `out["persisted"]` non-empty.
  **MUST FAIL against current code** (no snapshot → doc_rels=[] → misleading minimal
  prompt).
- *Given* a session with genuinely NO output (empty buffer, no file), *Then* no transcript
  is written, the prompt is the honest-minimal (D2) "create the materials" prompt,
  `persisted=[]`, no crash.
- *Given* a session that DID write `research/REPORT.md`, *Then* the transcript snapshot
  does NOT fire (D4), the real report is the material, behavior unchanged.
- *Given* `prepare_stage_handoff` called twice (re-advance), *Then* the transcript persist
  is idempotent (no dup effort; same prompt).
- *Given* the snapshot read raises (monkeypatch `read_since` to throw), *Then*
  `prepare_stage_handoff` still returns with the honest-minimal prompt; never propagates.

**Tests.** `tests/test_handoff_transcript_v11_1.py` (keystone, stub-PTY conversation-only)
+ `tests/test_advance_research_to_plan_conversation_v11_1.py` (the non-grass HTTP advance,
conversation-only end-to-end, asserts the transcript rides into the PLANNING worktree on
disk). No UI.

---

## Wave 2 — Grass: always proceed + open the session (UI)

**Goal.** The grass "Advance to Plan" never refuses — it opens the contained plan dev
session with the (now real, transcript-backed) prompt, like the non-grass path.

**Changes.**
- `effort_history.advance_grass_research_to_plan`: REMOVE the `no-research-material`
  early-return (effort_history.py:817-822). The path falls through to the existing
  mint/focus/link machinery with the keystone's prompt (now transcript-backed from W1, or
  honest-minimal). Preserve the contained-grass wiring verbatim (dedup, `queue_paste`
  focused-existing, `grass_origin`, `GRASS_DEV_LABEL_PREFIX`). If the keystone genuinely
  returns no prompt (impossible after W1 except the empty-session edge), still open the
  session with the honest-minimal prompt — never refuse.
- `anchor_gui.py` grass workbench: the "Advance to Plan" control now reliably opens the
  plan dev terminal; remove/replace any "no materials" UI note with the normal advance
  flow (the pending-paste hint). Build the mockup `_mockups/grass_advance_always.html`
  (grass workbench: research terminal → Advance to Plan → the plan terminal opens with
  the prompt naming the transcript + "create the plan").

**Done-when.** Advancing a grass research session that was a CONVERSATION (no file) opens
the contained grass plan dev session with the transcript-backed prompt; it never returns
"no materials".

**Given/When/Then.**
- *Given* a grass research dev session with transcript-only content, *When* "Advance to
  Plan" runs, *Then* the contained grass plan dev session OPENS (no refusal), is linked
  (`parent_session_id`/`chain_id`/`grass_origin`), contained (`GRASS_DEV_LABEL_PREFIX`),
  and its `pending_paste` names the persisted transcript + "create the plan".
- *Negative:* a grass session with literally no output → still opens with the honest-
  minimal prompt (never refuses).

**Tests.** `tests/test_grass_advance_conversation_v11_1.py` (backend: grass conversation-
only opens + contained + linked + transcript-named; the v10 W5 grass invariants preserved)
+ a Playwright `tests/test_grass_advance_ui_v11_1.py` (produce transcript-only content
live, click "Advance to Plan", assert the plan terminal opens with the prompt naming the
transcript path + no console error + screenshot vs the mockup). **UI wave — full
verification + John's sign-off.** This is the wave that fixes John's reported failure.

---

## Wave 3 — Healthcheck v11.1 + docs (PROJECT DONE)

**Goal.** Make the conversation-only flow a permanent guard, and close out.

**Changes.**
- `anchor_healthcheck.py`: `check_rnd_v11_1_surface(report, server_proc, rnd_env)` — fully
  stubbed (stub PTY + stream-json stub runner + temp git/worktree/data; never `:8777`).
  Walks the CONVERSATION-ONLY flow: start a live research session, seed its stub-PTY read
  buffer with transcript content (NO file written), `prepare_stage_handoff`/advance,
  assert the transcript is snapshotted + persisted + named in the prompt + the next
  session opens — for research→plan AND (equivalently) plan→build. Registered in `main()`.
  Reaps stub PTYs + synthetic rows, restores env, never binds `:8777`.
- `tests/test_healthcheck_v11_1.py` (mirrors test_healthcheck_v11.py: green + hermetic —
  env restored, no `:8777`, no leftovers).
- Update `CLAUDE.md`: a v11.1 note under the v11 section — the conversation-research
  capture (transcript snapshot when no doc), the grass-no-longer-refuses unification, the
  honest "create the materials" prompt, the conversation-only-test lesson. Update the
  auto-memory pointer.

**Done-when.** `python -m pytest -q` ≥ baseline (1232) + the new v11.1 tests, all green;
`check_rnd_v11_1_surface` passes fully stubbed walking the conversation-only flow; distro
green; docs updated.

**Given/When/Then.**
- *Given* the healthcheck, *When* `check_rnd_v11_1_surface` runs, *Then* it walks the
  conversation-only flow (transcript captured + referenced + next session opens) for both
  paths, hermetic, full teardown, never `:8777`.

**Tests.** Extend the healthcheck self-test; distro stays green. No UI.

---

## Wave dependency / ordering

```
W1 (keystone: transcript snapshot + honest prompt, backend)  ← fixes ALL paths at the source
  └─> W2 (grass: remove the refusal + UI — John's reported failure fixed)
        └─> W3 (healthcheck conversation-only walk + docs)   ← PROJECT DONE
```

## 🚦 Stage 2 gate

On John's approval this freezes and hands to Foreman: `node foreman/bin/locate-plan.mjs
--json planning/rnd-v11.1` must exit 0 before any wave runs. No branch is cut and no
`nssm restart` until John signs off.
