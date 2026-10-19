# Anchor R&D Surface v11 — "Reliable Trio Handoff" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-20. A **correctness fix**, not a feature.
> Branch `foreman/rnd-surface-v11` off master `465fda9` (v10 + v10.1 merged, GREEN 1202).
> From J.C. Liechty's live-use failure: advancing a live researchPrime session to
> planning produced only a bare "load Crucible" prompt — no research-doc references,
> the reports were never written into the project, and no handoff summary. The
> handoff is the whole point of the trio; this makes it actually work in the LIVE
> flow.

---

## Confirmed root cause (two independent corroborating traces — established, not re-derived)

1. **`advance_session` (research→plan) never persists the source docs.** Document
   persistence (`effort_history.persist_session_docs` via `terminal_session.capture_session_docs`)
   runs ONLY inside `terminal_session.kill` and inside `finish_to_build` (plan→build,
   `anchor_gui.py:12603`). When the user clicks **Advance to Planning** on a **live,
   unkilled** research session, the reports stay in the research worktree — never
   copied/committed to the project, never recorded as effort records.
2. **The prompt builder finds docs only via persisted, session-tagged effort records.**
   `terminal_session.research_set_for_session` reads `list_efforts(..., "research")` and
   keeps efforts where `session_id == research_session_id` — a tag written ONLY by
   `persist_session_docs`. With nothing persisted it returns `None` →
   `handoff.build_next_stage_prompt` falls to the **bare fallback** ("With Crucible
   loaded, plan from the upstream research session's findings … see HANDOFF.md"), no
   real doc paths, no "read these first" list.
3. **No HANDOFF.md is written for research→plan** (`prime_worktree` is never called and
   no-ops without a plan set). The only artifact is a `NEXT-PROMPT.md` carrying the bare
   prompt that points at a HANDOFF.md that doesn't exist.
4. **The Advance button has no done-state gate** (`anchor_gui.py:5756-5770`) — it fires
   while research is still live, the exact state in which nothing is persisted.
5. **The suite is GREEN because the tests mask the live flow.** Every research→plan test
   PRE-PERSISTS the report via `eh.record_effort(..., session_id=…)`
   (`test_advance_artifacts_v10.py:130-133`, `test_advance_paste_ui_v10.py:102-106`) —
   simulating a state the live "advance a still-live research session" path never
   produces. The plan→build side has a real worktree-only-then-advance test
   (`test_finish_to_build_persists_planning_docs_so_build_can_read_them`); **research→plan
   has NO equivalent.**
6. **The asymmetry, in the project's own record.** The v10 Wave-2 review found this
   "North-Star hole" but framed it as plan→build-specific and patched **only**
   `finish_to_build`. The identical defect in `advance_session` was never mirrored.
   Grass research→plan (`advance_grass_research_to_plan`, v10 W5) DOES persist — a third
   correct-vs-broken variant. The handoff logic is **scattered and half-wired**: three
   paths persist, one doesn't, and they each rebuild the handoff differently.

---

## North Star (locked — Crucible framing for John's approval)

**Advancing any trio stage (research→plan, plan→build) in the LIVE flow reliably PRIMES
the next stage: the source stage's produced docs are persisted into the project, the
next session opens with a REAL prompt that names the actual persisted doc paths +
"read these first," a HANDOFF.md / handoff summary is written so the next stage starts
informed, the sessions are linked — and this is VERIFIED against the real
worktree-only flow so "tests green but live broken" cannot recur.**

The deeper objective (the inclusion test): there is **ONE** handoff path, not four
half-wired ones. Every advance — research→plan, plan→build (button + auto-on-kill),
and the grass variant — flows through a single shared "persist → build handoff →
link" keystone, so this class of asymmetry bug is structurally impossible to
reintroduce.

---

## Locked decisions (Crucible — for John's approval/adjustment)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Patch vs unify | **Unify** — one shared `prepare_stage_handoff` keystone that ALL advance paths call | The bug WAS an un-mirrored one-line patch. A single keystone kills the asymmetry class permanently and is the "get it right" fix, not another patch. |
| D2 | Handoff richness | **Persist docs + write HANDOFF.md** (real persisted paths + "read these first" + correct skill + the source session's cached summary if present) + `NEXT-PROMPT.md` references them; **trigger a BACKGROUND source-stage summary on advance** (non-blocking) | Gives the user the "handoff summary" they asked for and a primed next stage, WITHOUT blocking advance on a synchronous model call. The real docs are the source of truth; the summary is the digest. |
| D3 | Done-gate on advance | **No hard gate** — persist whatever is in the source worktree at advance time | The user advances when they've seen the reports; persisting the current worktree state is correct and matches the natural flow. (The button label already says "when this research is done.") |
| D4 | Verification | **Live-flow tests** (start a live session, write docs to the WORKTREE ONLY — no `record_effort`, no kill — advance, assert persisted + referenced) for every advance path, **+ a `check_rnd_v11_surface` healthcheck** that walks the real flow | This is the exact coverage that was missing and would have caught the bug. The masking tests are kept (they still validate prompt-building given persisted docs) but the live-flow tests are the truth. |
| D5 | Idempotency / safety | Persist-on-advance is **best-effort + idempotent** (byte-identical skip, content-addressed efforts) and must NEVER break the advance if persistence fails | Mirrors the v8 keystone discipline; a persistence hiccup must not strand the user mid-handoff. |

---

## What "primed" means (the target experience)

After the user clicks **Advance to Planning** on a research session that produced
`research/<run>/REPORT.md` (+ others) in its worktree:

1. Those docs are **copied + committed into the project** and recorded as
   research-session-tagged efforts (so they are discoverable, survive, and ride into
   the planning worktree which is checked out off main HEAD).
2. A new **planning session** opens with the Crucible skill loaded and the pasted-unsent
   prompt: *"With Crucible loaded, plan from the upstream research session's findings.
   Read these documents first, then plan from them: - research/<run>/REPORT.md - …"* —
   the **real** paths.
3. A **HANDOFF.md** in the planning worktree lists those paths + the correct skill + (if
   available) the research session's cached summary.
4. The planning session is **linked** to the research session (chain lineage — already
   works).
5. The same for **plan→build** (already mostly works via finish_to_build) — now through
   the same keystone, so it is consistent and equally verified.

---

## Out of scope (inclusion test)

- New handoff *features* beyond making it reliably prime the next stage (no new
  stages, no cross-project handoff, no handoff editor UI).
- Changing the close-vs-kill / persistent-finished-tiles / paste-NOT-submit semantics
  (those are correct; v11 only fixes the persist-and-prompt gap).
- A synchronous, advance-blocking model call to generate the summary (D2 keeps it
  background).
- Re-architecting the summarizer (reuse the existing cache + summarize-on-finish hook).

---

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** + the single lazy `pywinpty` exception. `git` stays an external
  CLI behind the existing seam.
- **Hermetic tests** — stub PTY (`ANCHOR_PTY_BACKEND=stub`) + stream-json stub runner +
  temp git project + temp data dir; **never** bind `:8777` / touch real data / network.
- **Playwright DEV-ONLY** (`pytest.importorskip`), never in product code; `distro.py`
  scan stays green.
- **The v4 UI-verification standard** for any UI-changing wave: rendered-DOM
  positive+negative **+** a real Playwright/Chromium interaction test **+** an
  orchestrator screenshot vs the wave's mockup **+** John's sign-off. **And — the v11
  lesson — every advance test must exercise the WORKTREE-ONLY live flow, never a
  pre-persisted `record_effort` shortcut.** A test that pre-seeds the persisted effort
  is a masking test and cannot be the sole coverage of an advance path.
- **No merge to master / no `nssm restart anchor`** until John signs off.

---

## Adversarial review — Shark-Tank top findings (and mitigations)

| Risk | Finding | Mitigation |
|---|---|---|
| **R1 — persist mid-stream** | Advancing a live research session persists whatever is in the worktree, possibly an incomplete report. | Persist whatever exists (D3); the user advances when they judge it done. Idempotent re-persist (D5) means a later kill/advance re-captures any newer state. Honest: if NO docs exist, the prompt is the honest minimal one (no fabrication) and the UI says so. |
| **R2 — persistence failure strands the handoff** | If `capture_session_docs` throws, advance could fail mid-way. | Best-effort + idempotent (D5); persistence failure is logged and the advance still proceeds (degrades to the honest minimal prompt), never stranding the user. Mirrors the v8 kill-path discipline. |
| **R3 — unification regresses the working paths** | Routing finish_to_build / auto-advance / grass through the new keystone could break paths that currently work. | Wave 3 unifies AFTER the keystone + research→plan fix are proven (Waves 1–2); each path keeps its existing live-flow + regression tests; the keystone is a superset of what each path already does. |
| **R4 — the masking-test trap recurs** | New tests could again pre-persist docs and pass vacuously. | D4 + the constraint: every advance test writes docs to the WORKTREE ONLY and asserts persistence happened; a `check_rnd_v11_surface` healthcheck walks the real flow; the masking tests are explicitly annotated as prompt-building-given-docs coverage, not live-flow coverage. |
| **R5 — background summary never lands** | The non-blocking summary could silently never generate. | The summary is a NICE-TO-HAVE digest; the handoff is fully functional on the real doc paths alone. The background summary reuses the existing summarize-on-finish hook (already proven). Honest absence, never a blocker. |
| **R6 — placement/cycle** | A new keystone calling capture_session_docs (terminal_session) + build_next_stage_prompt (handoff) + summarizer risks an import cycle. | Place the keystone where the orchestration already lives (terminal_session, which already imports handoff lazily); reuse the existing lazy-import discipline. No new cycle. |

Convergence: after these mitigations the Shark Tank reached a dry round. John is the
final convergence authority — the Stage-1 gate.

## 🚦 Stage 1 gate

This Master Plan is presented for John's approval. On approval it freezes and Crucible
emits the wave-by-wave `IMPLEMENTATION-PLAN.md` (drafted alongside for review).
