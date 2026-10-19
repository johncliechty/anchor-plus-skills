# Anchor R&D Surface v11.1 — "Handoff Always Primes" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-20. A focused correctness+design fix on top
> of v11 "Reliable Trio Handoff". Branch `foreman/rnd-surface-v11.1` off master
> `b6719bd` (v11 merged, GREEN 1232). From J.C. Liechty's live-use failure: advancing a
> GRASS research session that was a CONVERSATION (no written file) returned "no
> materials to advance" and opened NOTHING.

---

## Confirmed root cause (two corroborating read-only traces — established, not re-derived)

1. **Grass advance HARD-REFUSES on no written doc.** `effort_history.advance_grass_research_to_plan`
   (effort_history.py:735) calls the v11 keystone `prepare_stage_handoff(pid, rsid,
   "planning")`, then a guard at **effort_history.py:817-822** —
   `has_material = bool(prompt.strip()) and any(rel in prompt for rel in research_doc_rels);
   if not has_material: return {"ok": False, "reason": "no-research-material"}` — returns
   **before** any `start_session`. No planning session is opened.
2. **"Material" = a written, document-classified FILE only.** The keystone persists docs
   the source session WROTE to its worktree (`capture_session_docs` →
   `persist_session_docs` → `_produced_doc_rels` via `git status`, filtered by
   `_is_document_rel` to `.md`/`.pdf` under the lane dirs or a root trio-doc name). A
   **conversation-only** research session (model answered in the terminal, wrote no file)
   → `doc_rels=[]` → guard fires. The conversation/transcript is **never captured**; the
   cached summary is read via `load_cached` but the background summary is gated +
   daemon-threaded, so it is **never ready at advance time**. Conversation-only research
   is **lost** — only files survive.
3. **Asymmetry (confirmed).** The non-grass project-level advance (`/api/rnd/advance_session`,
   anchor_gui.py:12464-12587) does **not** apply this guard — it proceeds with the
   honest-minimal prompt and links the planning session even with no docs. So **grass
   hard-refuses (no session) while non-grass proceeds** — same conversation-only
   situation, two behaviors.
4. **The honest-minimal prompt is MISLEADING when there are no docs** (handoff.py:609-616):
   it claims *"the research report is in this worktree checkout; see HANDOFF.md"* when
   nothing was persisted, and it does **not** instruct the planner to CREATE the
   materials.

---

## North Star (locked — John's intent)

**Advancing any trio stage (research→plan, plan→build), grass or non-grass, ALWAYS opens
the next stage with a useful, honest transition prompt — even when the source produced
no written doc — and the source session's CONTENT is captured and made available to the
next stage so nothing is lost. When there are no written materials, the next session
opens, loads the transition prompt, and is set up to CREATE the materials (informed by
the captured research conversation).**

One handoff path (the v11 `prepare_stage_handoff` keystone) — the snapshot + honest-prompt
logic lives in ONE place, applied to all four advance paths. No path can refuse; no
conversation is lost.

---

## Locked decisions (John approved)

| # | Decision | Detail |
|---|---|---|
| **D1** | **Remove the grass hard-refusal.** | Delete the `no-research-material` block (effort_history.py:817-822) so the grass advance ALWAYS proceeds + opens the next session, exactly like the non-grass path. Unify the two behaviors. |
| **D2** | **Honest + actionable no-docs prompt.** | Rewrite the no-docs fallback (handoff.py:609-616 + the build fallback): no false "the research report is in this worktree" claim; instead instruct the next skill to review the captured research (transcript/summary) and **CREATE** the planning materials (Master Plan + Implementation Plan) from the project objective. Shared by both paths → fixes grass + non-grass at once. |
| **D3** | **Capture conversation research = BOTH.** | In `prepare_stage_handoff`, when the initial persist produced NO document-classified doc, SYNCHRONOUSLY snapshot the source session's PTY transcript (`pty_manager.read_since(sid, 0)`) into a handoff doc (`<lane>/<short-sid>-transcript.md` in the source worktree), then re-run `capture_session_docs` so it is persisted + session-tagged → `research_set_for_session` finds it → the REAL doc-referencing prompt engages → it rides into the next worktree. Instant advance (no model call). AND the existing background summary (triggered by the keystone) refines the now-persisted transcript into a clean digest afterward. Best-effort + idempotent; a snapshot failure NEVER breaks the advance. |
| **D4** | **Trigger = only when no written doc was produced.** | The transcript snapshot fires only when the initial persist yields zero doc-classified files (the gap case). When the model DID write a real report, that report is the material (the transcript is supplementary — out of scope here). Keeps the change minimal (inclusion test) and directly fixes the reported failure. |
| **D5** | **One keystone.** | All of the above lives in `prepare_stage_handoff` (terminal_session) + `build_next_stage_prompt` (handoff) — the v11 unification — so research→plan, plan→build, grass, and auto-advance all inherit it. |

---

## What "primed" now means (the target experience)

You do research as a **conversation** in the grass (or project) research terminal — no
`REPORT.md` written. You click **Advance to Plan**:

1. The keystone persists produced docs; finding none, it **snapshots the research
   terminal's transcript** to `research/<sid>-transcript.md`, persists it (session-tagged).
2. `build_next_stage_prompt` now finds that doc → the planning session opens with a
   prompt naming `research/<sid>-transcript.md` + *"read the upstream research, then
   create the Master Plan + Implementation Plan."*
3. The transcript **rides into the planning worktree** (off main HEAD) so Crucible can
   open it.
4. The planning session is **linked**; the background summary refines the transcript into
   a clean digest.
5. If the session had literally no output (no transcript either), the **honest-minimal
   prompt (D2)** still opens the session: *"no written research upstream — create the
   planning materials from the project objective."* It never refuses.

---

## Out of scope (inclusion test)

- Always-capturing the transcript even when a real report WAS written (D4 limits it to
  the no-doc case). A future option, not needed to fix the failure.
- A synchronous model-summary at advance time (D3 keeps the click instant via the raw
  snapshot; the background summary refines it — John's "both").
- Changing close-vs-kill / paste-NOT-submit / persistent-finished-tiles / the v11
  keystone's persist+commit contract.
- New handoff features beyond "always prime + nothing lost."

---

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** + the lazy `pywinpty` exception. `git` stays an external CLI.
- **Hermetic tests** — stub PTY (whose `read_since` buffer carries simulated transcript
  content) + stream-json stub runner + temp git project + temp data dir; never bind
  `:8777` / touch real data / network.
- **Playwright DEV-ONLY** (`pytest.importorskip`), never in product; `distro.py` green.
- **The v11 lesson, hardened:** every advance test is WORKTREE-ONLY (no `record_effort`
  pre-persist) and there is a **CONVERSATION-ONLY** test (no written file, transcript in
  the PTY buffer) for BOTH grass and non-grass that FAILS against current code.
- **v4 UI-verification standard** for the grass UI wave (the "Advance to Plan" control
  now opening a session is a behavior change → rendered-DOM + Playwright + screenshot +
  John's sign-off).
- **No merge to master / no `nssm restart`** until John signs off.

---

## Adversarial review — Shark-Tank findings + mitigations

| Risk | Finding | Mitigation |
|---|---|---|
| **R1 — noisy/huge transcript** | The raw PTY buffer includes the seed+greet boilerplate + ANSI + could be large. | The snapshot strips the known seed/greet prefix + control sequences and caps length (keep the tail if over a sane cap); writes clean markdown. The background summary then refines it. The doc is honest ("research session transcript"), not claimed to be a polished report. |
| **R2 — transcript snapshot fails / PTY gone** | Reading the buffer of a reaped/dead PTY could raise. | Best-effort + never-raise (mirrors the keystone's existing persist guard): on failure → no transcript → fall to the honest-minimal prompt (D2). The advance still proceeds. |
| **R3 — removing the grass guard regresses v10 W5** | The grass contained-session wiring (dedup, queue_paste, grass_origin, contained label) must survive. | D1 removes ONLY the `no-research-material` early-return; the mint/focus/link machinery below it is untouched. With D3 there is now always material, so the path that the guard used to block now has a real prompt. A grass conversation-only test asserts the contained+linked+grass_origin invariants still hold. |
| **R4 — idempotent re-advance** | Re-advancing re-snapshots → duplicate transcript docs. | The transcript filename is deterministic per session (`<short-sid>-transcript.md`); `persist_session_docs` is content-addressed + byte-identical-skip, so a re-advance with the same buffer produces no dup. A grown buffer overwrites the same path (newer transcript), persisted idempotently. |
| **R5 — the masking-test trap recurs** | New tests could pre-persist or pre-write a file, masking the conversation-only flow. | The conversation-only tests write NOTHING to the worktree and instead seed the stub PTY's read buffer — exercising the exact live path. The healthcheck walks it too. A pre-persisted test is annotated, never the sole coverage. |
| **R6 — transcript for the wrong session** | The snapshot must read the SOURCE session's PTY, written into the SOURCE worktree, under the SOURCE lane. | The keystone already resolves the source record (lane + worktree_path); the snapshot uses those. Tested: the persisted transcript is session-tagged with the source sid + lands under the source lane dir. |

Convergence: dry round after these mitigations. John is the final authority — the gate
below.

## 🚦 Stage gate

Decisions D1-D5 are John-locked, so this Master Plan + the accompanying
`IMPLEMENTATION-PLAN.md` are presented together for a single approval. On approval they
freeze and hand to Foreman (after the `locate-plan` well-formedness gate).
