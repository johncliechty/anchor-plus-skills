# Master Plan — Anchor Improvement Effort (Crucible Stage 1)

> **Status: LOCKED 2026-06-30** by J.C. Liechty after Shark-Tank Round 1. Depth **FULL**.
> See `SHARK-TANK.md` for the round; resolutions folded in below (supersede the draft
> phase text where they conflict).
>
> ## Stage-1 lock resolutions (authoritative)
> - **#10 / Phase 5 — DECIDED: the 5:1 Claude-orchestrates-Gemini swarm lives at the
>   SKILL/SESSION layer**, NOT in Anchor's `job_runner`. Skills fan out to Gemini via
>   `agy-dispatch` (proven by this session). Anchor only: defaults sessions to Claude,
>   ensures agy-dispatch is available, surfaces the split, and falls back honestly
>   (Gemini-only degrades to research + Gemini-runnable; plan/build show "requires
>   Claude"). Keeps Anchor a uniform control surface.
> - **#1 / Phase 1 — reproduce-first.** The naive "don't warn on effort-bound sessions"
>   is REJECTED (neuters the hunter). Real cause = restart-survival + empty `_LIVE`. Fix
>   uses a genuine liveness signal (session heartbeat, or re-adopt surviving PTYs into
>   `_LIVE` on restart). A true orphan must still be caught.
> - **#12b — fix the structurally-dead zombie terminal** (valid lane + dashboard
>   project), not "reproduce."
> - **#5/#13 — `×` close = suspend PTY + preserve worktree/record (resumable);** one
>   `Kill→Boneyard` (better icon); drop the redundant `🗑`/`✕`. (No PTY leak, no forced
>   destroy.)
> - **#7 — raise the byte budget (~1 MB) + discount a fixed seed allowance** (the
>   "bytes-since-seed" idea breaks on buffer truncation).
> - **#9 — best-effort/timeout-bounded summary; never block the switch;** gitignore the
>   handoff doc; fix the "promoted from Grass Catchers" seed label.
> - **#2 Gandalf — no real dependency on Phase 5;** fans out via the existing
>   `job_runner`/agy-dispatch.

> **(Draft below — retained for the record.)** Depth **FULL**.
> Measured against `NORTH-STAR.md` (LOCKED). Root causes verified against real code
> by 5 Gemini swarms (see `DIAGNOSIS.md` → CORRECTIONS). File:line refs are live.

## The three pillars (from the North Star)
- **(A) Resumable sessions** — leave any effort, click to carry on (phase + docs +
  skills + summary). Includes brownfield/discovered efforts + model-switch handoff.
- **(B) Honest UI & warnings** — latest-per-tab + "previous" link; collapsed
  deliverables; correct terminal controls + width; warnings only on real problems;
  Gandalf produces real findings; zombie page is live.
- **(C) Model-flexible execution** — Claude default; Claude orchestrates Gemini
  swarm sub-agents at 5:1; clean single-subscription fallback, never cross-calling.

## Verified root causes (the planning ground truth)
| # | Item | Root cause (file:line) | Fix shape |
|---|---|---|---|
| 1 | Swarm warning on legit swarms | `live_ids = pty_manager.live_sessions()` = streaming set only; effort-bound non-streamed sessions fall out → `kill` (`anchor_gui.py:14613-14648`, `zombie_hunter.py:151-170`) | Broaden "attached" to effort-bound live-PID sessions; or `classify` abstains when effort-bound |
| 7 | Context warning on fresh session | warns at 80%×200KB of **PTY-buffer bytes** incl. seed (`terminal_session.py:1309-1380`) | Replace proxy: bytes-since-seed / real token signal / higher budget |
| 6 | Restart not carry-on | `_build_continue_seed` returns `""` for discovered efforts (no registry rec/summary) → cold (`anchor_gui.py:1330-1408`); discovered card only opens artifact (`:2133`) | Synthesize seed from on-disk docs; add resume-as-session affordance |
| 3 | No "previous efforts" link | expander needs ≥2 in `session_views` (`anchor_gui.py:4006-4036`); discovered efforts may not enter it | Always show latest + link; fold discovered into `session_views` (couples to #6) |
| 5/13 | Trash-can vs Boneyard, redundant ×s | panel has 4 controls `– × 🗑 ✕` (`anchor_gui.py:4705-4722`); dock has `Kill→Boneyard` (`:3775`) | Unify: `Kill→Boneyard` everywhere (better icon); `×`=only non-destructive; drop `🗑`/`✕` |
| 9 | No model-switch handoff | `switch_engine` re-seeds skill only, writes no doc (`terminal_session.py:756-826`) | Summarize before reap → `seed_context`/`SWITCH-HANDOFF.md` |
| 4 | Deliverables always open | `render_deliverables_html` no collapse (`anchor_gui.py:10095-10182`) | `<details>` collapse-by-default |
| 8 | Terminal opens narrow | `.panel .pin` no width + `resize:both` shrink-wraps to 80 cols (`:4694-4695`) | `width:100%` + `fit()` on open |
| 12 | Zombie page stale + no terminal | page static, no refresh (`anchor_gui.py:14650-15036`); embedded terminal IS wired (`:16429-16551`) but unused | Add auto-refresh (SSE/interval); reproduce terminal before scoping |
| 2 | Gandalf thin | single Stage-A pass, no fan-out; index `ok:false` w/ no UI affordance (`gandalf.py`) | Real map-reduce decomposition + in-progress indicator |
| 10 | No in-product 5:1 | `lanes.py` limits Gemini to research; no orchestrator-swarm | Claude-orchestrates-Gemini substrate + single-sub fallback |

## Phasing (low-risk → keystone → biggest build)

### Phase 1 — Honest warnings (B) · lowest risk, highest daily payoff
- **#1** swarm warning → orphan-only (broaden the attached set / effort-bound abstain).
- **#7** context warning → fix the proxy so it doesn't fire on a fresh seeded session.
- **#12a** zombie page auto-refresh; **#12b** reproduce the embedded terminal first.
- **Done-when:** a legit effort-bound session never trips the orphan banner; a freshly
  seeded session shows no context warning; the zombie page updates live without reload.

### Phase 2 — UI correctness (B) · small render-layer cluster
- **#3** latest-per-tab + "previous efforts" link (incl. research lane + workbench).
- **#4** deliverables collapsed by default.
- **#5/#13** controls: `Kill→Boneyard` on every session (better icon), `×`=archive-only,
  remove redundant `🗑`/`✕`.
- **#8** terminal full-width from open.
- **Done-when:** each lane shows the latest effort with older ones one click away;
  deliverables start collapsed; every panel has exactly close-`×` + `Kill→Boneyard`;
  a panel fills its column width on open.

### Phase 3 — Resumable sessions (A) · ⭐ KEYSTONE
- **#6** promote discovered/brownfield efforts to first-class resumable sessions:
  `_build_continue_seed` synthesizes from on-disk docs (phase + doc list + skill +
  summary) when no registry/summary exists; discovered cards get a resume affordance.
- **#9** model-switch handoff doc auto-generated + auto-loaded into the new engine.
- **Done-when:** clicking an OLD/brownfield effort opens a WARM session — correct lane
  phase, its documents available, the right skill loaded, a summary orienting the turn;
  switching engines mid-session carries context forward with no manual re-priming.
- **Acceptance test (dogfood):** THIS effort's planning docs resume warm inside Anchor.

### Phase 4 — Gandalf map-reduce (B) · self-contained engine rework
- **#2** real fan-out (map shards of the tree) → reduce/synthesize → graded findings;
  an in-progress/queued indicator while `ok:false`.
- **Done-when:** a Gandalf run over a large tree returns non-trivial, grouped findings
  and the UI shows progress until the report is ready.
- **Sequenced after Phase 5's substrate** so map-reduce can use Gemini shards.

### Phase 5 — Model-flexible execution (C) · 🔨 BIGGEST BUILD
- **#10** Claude-orchestrates-Gemini at 5:1 as the default Anchor execution substrate
  (productize the agy-dispatch pattern: short Claude prompts, Gemini swarm sub-agents
  on their own tokens, Claude synthesizes/double-checks/manages); clean fallback to
  whichever single subscription exists — **never cross-calling**.
- **Done-when:** an Anchor session defaults to Claude-driver + Gemini-swarm at ~5:1 on
  a host with both; a host with only one subscription runs entirely on that one with no
  attempt to call the other; the split is observable.

## Sequencing rationale
1 → 2 are independent, low-risk quick wins that stop daily annoyance immediately.
3 is the keystone (the North Star's core promise) and shares carry-on-doc machinery
with #9. 5 builds the substrate that 4 then exploits, so Gandalf map-reduce lands on a
real swarm engine rather than a second bespoke fan-out. Each phase is independently
shippable; a `nssm restart anchor` deploys after merge.

## Reproduce-at-build (not yet certain)
- #12b: is the zombie-page terminal broken or just non-obvious? (code says wired)
- #3: do multiple research efforts already exist but not enter `session_views`?
(Both resolved by a 5-minute live reproduce at the start of their phase.)

## Meta-requirement (dogfood Pillar A)
Every Crucible and Foreman run on this effort writes its own summary into the effort's
planning folder so the effort itself is a resumable Anchor session.
