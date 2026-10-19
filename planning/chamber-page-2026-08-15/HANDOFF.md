# The chamber page — handoff

**Read this first if you are picking this up in a fresh context.**
Owner: John. Date: 2026-08-15. Repos touched: `C:\dev\Anchor`, `C:\dev\Ecgberht`.

## What John asked for, in his words

> "It's like a VS Code session — I just talk to it, we scaffold, but I need the scaffolding
> shown… then it just runs and gives me a status update every 10 minutes… it can't be little
> tiny windows and it can't be great big huge long windows I have to scroll through. It's got
> to be right there, and the content moves up to the top as it fills in… super easy, super
> elegant, super useful."

And, decisively, on 2026-08-15 after seeing the promoted drawer:

> "I don't know why you're so stuck on the old cockpit… you write something completely new,
> it's great, and you can't embed it. We just want to take that old stuff off, archive it."

## The state of play

**The steward chamber is now the project page.** `GET /project/<id>` serves
`render_chamber_page_document` (`anchor_gui.py`), which renders `chamber_page.py` into a
document loading exactly two assets: `static/chamber-page.css` and `static/chamber-page.js`.
It does **not** load the cockpit's 8,600-line `project-window.js`.

- `?classic=1` → the old cockpit, unchanged. The escape hatch.
- `__dashboard__` → **always** classic. The home page iframes it as the Workbench tile
  (`anchor_gui.py` ~7919); a chamber nested in the dashboard is what slim mode exists to stop.

**Measured, in a real browser at 1600×1000 (not asserted — rendered and looked at):**

| | before | now |
|---|---|---|
| chrome above the conversation | 762px | **68px** |
| conversation viewport | 446px | **843px** |
| opens on | oldest message, 7,215px hidden | **newest turn** |
| his BA-815 scaffolding | **0 steps shown** | **10 steps** |

## The five findings that mattered

1. **`R-PROPOSED-EXCLUDED` was hiding his whole plan.** `chamber_rail.seal_rail_view` filtered
   out every step with `status == "proposed"`. His live BA-815 campaign has TEN steps, all
   proposed (framed in VS Code, never batch-confirmed) — so the rail painted empty over a full
   plan on disk. **Amended:** drafts render, carry `data-draft="1"` (attribute only, so the C9
   signature holds), and the page shows a "10 steps proposed and not yet confirmed" banner.
   This is the single highest-value change in the effort.
2. **The transcript never painted.** Turns were always persisted at
   `.ecgberht/conversation-log.json`; nothing read them. `chamber_open.read_conversation_tail`
   now does, `_render_convo` paints them, and the page opens pinned to the newest.
3. **A turn had nothing to press.** Proposals/commissions/spend cards rendered only into
   `#ecgConvo`, DOM deleted in chamber-m1 W2. `chamber-page.js :: renderTurn` renders them.
4. **The E1 held answer was thrown away.** Fixed in engine + all renderers; the prompt
   contradiction fixed *conditionally* so unbounded prompts stay byte-identical.
5. **The dashboard rolled up `runs[0]`.** A project whose second run was waiting on him read
   "running now". Now ranked by urgency, and the tile carries `needs_you` + a ⚑.

## Where things are

| Thing | File |
|---|---|
| Page renderer | `Anchor/chamber_page.py` |
| Page document + route | `Anchor/anchor_gui.py :: render_chamber_page_document` |
| Page styles / script | `Anchor/static/chamber-page.{css,js}` |
| Rail + steps (shared with classic) | `Anchor/chamber_rail.py` |
| View, transcript, degraded face | `Anchor/chamber_open.py` |
| The signed drawing | `/mockup` route → `Ecgberht/planning/steward-assessment-2026-08-08/mockups.html` |
| Journal | `Ecgberht/journal/0085-*.md` |

## Iteration 2 (same day) — status window, freshness, workbench

John, after opening it: *"I thought the M1 dashboard had a status option… where's the
window that shows me the 10-minute status?"* · *"You should automatically when you open the
project go look and see if there's a version of the steward process going… what you've got
when you open MBA Teaching is out of date and I don't have a way of updating."* · *"I don't
want to have to hit a button that says move me back to the cockpit, because then it loses
all the functionality I have from the M1 dashboard — I want Boneyard, open terminal, the
Gandalf summary, basically the workbench."*

1. **The status window exists and now has a caller.** `chamber_status_overlay.py` +
   `/api/ecgberht/status_overlay` were built waves ago and nothing on this page called them.
   Clicking the ⏱ strip opens the drawn overlay: latest ⏱ table + remaining flow + ETAs.
   (It is the ONE `innerHTML` on the page — server-rendered, server-escaped.)
2. **Freshness, in the command bar.** `chamber_open.campaign_freshness` stats the four files
   the steward engine writes from ANY host and reports `live` / `talked` / `plan` /
   `sidecar_stale`. On his MBA project it reads **"talked 1d ago · plan 7d ago"** — which is
   the true shape of his confusion: he has been talking in VS Code for days, and the roadmap
   has not moved since 08-07. Anchor cannot see a Claude session it did not start, and does
   not pretend to; it reports file mtimes, which is a fact.
3. **`POST /api/ecgberht/refresh`** rebuilds the derived sidecar from the ledger on disk —
   no model, no bridge spawn. The bar shows `stale · refresh` when the sidecar is older than
   its source, `↻` otherwise. Verified: it cleared `sidecar_stale` on his real MBA folder.
4. **The workbench** is a 30px strip at the bottom of the page — Terminal · Gandalf · Files ·
   Boneyard — opening to 34vh. The terminal is a real `general` session over
   `/api/rnd/term_ws` with its own tiny xterm mount (NOT the cockpit's `_mountTerminal`,
   which is entangled with `PANELS`/`DOCK` globals). It takes ~8s because `term_start` cuts a
   git worktree first, so the wait message says so and counts.

**Gates: 295 passed / 0 failed.** Three governance gates objected during this iteration and
all three were right: the routes inventory wanted a row for `/api/ecgberht/refresh`; the
open-view determinism test caught `freshness` (elapsed time) riding a view contracted to be
byte-identical across two opens — it moved to render time; and a stale assertion of mine.

Bugs my own probing caught, worth remembering as a class: **shape assumptions.**
`gandalf.list_runs` returns `ts` as a Unix *float* and `.slice()` on it threw inside the
render, so the panel reported "could not read the Gandalf index" about an index that had
answered perfectly. `term_start` returns `{ok, session:{session_id}}`, not `{session_id}`.
Both were silent — the catch block turned a type error into a lie about the server.

## Iteration 5 — multi-seal + the three-audit hardening pass (John: "free rein")

**Multi-seal (his third ask, now built).** `chamber_efforts.py`: effort threads over the ONE
campaign — a seal strip of persona-icon tiles under the North Star, ＋ new effort, click to
switch, each seal its own painted conversation (`.anchor/chamber/effort-<id>-dialogue.json`;
the campaign seal = the engine's own log). The engine's single roadmap/gate-queue stays
shared BY DESIGN; the clash warning fires before a second seal commissions during a live run.
Store is WRITE_LOCK'd, capped at 24 open efforts, effort ids regex-gated before touching any
filename. Routes: `efforts` / `effort_act` / `effort_dialogue`; converse takes `effort_id`.

**Three Fable audits (security / correctness / elegance) — 20 findings, all P0/P1 fixed:**

- **P0 transcript leak**: `/project/` is an OPEN route and the chamber inlines the whole
  conversation server-side → tokenless tailnet viewers could read it. Fix:
  `render_chamber_lock_document` — a tokenless GET (token configured) gets a lock page that
  self-bounces via the browser's stored token, so John never sees it. Gate:
  `test_a_tokenless_viewer_never_reads_the_transcript` (asserts on the bytes in BOTH refusal
  shapes). Verified live in open mode against his real MBA data.
- **P0 liveness**: commission_runs sends `outcome`, never `status` — the strip read "idle"
  for a stranded running record while the rail said live, and RUN_LIVE=false disarmed the
  clash warning. Now: running+watched = live; running+unwatched = "needs a look".
- **P0 stale false-alarm**: chat turns tripped `stale · refresh` forever (the sidecar derives
  from the roadmap, not the chat). Now compares roadmap only.
- **Share blockers**: `dist_manifest.txt` had NO rows for chamber_page.py /
  chamber_efforts.py / tests/chamber_harness.py — a collaborator's every project click would
  have been a 500 (the v1.1.0 lesson, again). Rows added with the why written next to them.
- **Turn protection**: say box locks during the 60-162s turn (twice-Enter = two debits);
  seal-switch and the redeploy auto-reload refuse while a turn is in flight, an input is
  non-empty, or a terminal is attached.
- **Spend guard**: tile summary reads carry `cache_only=1` — a fan-out of uncached tiles used
  to launch a background MODEL job each (the 2026-07-14 usage-leak class).
- Also: degraded rail speaks English and its Rebuild button finally works (wired to
  `/api/ecgberht/refresh`); "Still the plan" wired; clamp actually clamps; the closed
  workbench can no longer eat 34vh (regression-gated); GPOLL can't yank a doc mid-read;
  transcript label is "You" not "John"; /mockup declared + generic fallback (no path leak);
  dead handlers/CSS deleted; a SERVER CONTRACTS block heads chamber-page.js.

**Gates: 299 passed / 0 failed.** Accepted, deliberately: `prompt()/confirm()` for seal
creation and boneyard (right-sized over custom modals), the campaign thread interleaving all
seals' turns (it is the audit trail; the tile's tooltip says so), P2s left: proposal cards
don't survive reload; run_pulse read via fallback chain.

## NOT built — do not claim otherwise

- **Reorder a step.** No verb, no endpoint, not in the mockup. Unbuilt.
- **Concurrent steward efforts per project.** Refused by `INSESSION_MAX_CONCURRENT_RUNS = 1`
  (`Ecgberht/engine/exec-insession.mjs:75`) plus single `strip.json` `active_effort`, one
  `roadmap.json`, one gate queue. The RUN layer is parallel-safe; the NARRATIVE layer is not.
  Raising the bound without splitting the narrative interleaves two runs into one rail.
- **Spend gates removed.** Investigated, not done. Key fact: the envelope covers CONVERSATION
  only — commissions are explicitly not dollar-gated
  (`Ecgberht/engine/session-envelope.mjs:1156-1179`). Removing it costs little. The real
  backstops are `AUTO_CHAIN_CAP = 3` (`commission_session.py:520`) and the watcher clock;
  researchPrime's 8-round cap (`run-rounds.mjs:128`) is the ONE that cannot be removed safely.
- **Open terminal / Gandalf / files / grasscatcher are NOT on the new page yet.** They live in
  classic. Census says each is an independent panel and carrying them is days, not weeks:
  terminal ≈600-800 JS + `_mountTerminal` (project-window.js:5025-5362); Gandalf panel
  `anchor_gui.py:4090-4297` renders from its own index; files `handle_project_files`
  (~py:16430); grass add/list only — **do not carry the 880-line grass workbench (0 uses)**.

## Landmines

- **Byte-parity twins.** `static/project-window.{html,js,css}` have in-source twins via
  `tools/extract_project_window_shell.py`. Edits to those three need the twin regenerated.
- **63 `--deselect` lines** in `scripts/run-all-tests.mjs`. "GREEN" is partly by exclusion;
  three of them are the steward-tile shape tests. Check what is switched off before trusting a
  green run.
- **`test_e1_refusal_paints_visible_as_the_drawn_blocked_state`** asserts `turn_blocked is
  True` as the PASSING outcome for a question. The success path is not asserted anywhere.
- **The C9 mockup diff** compares `(tag, sorted-classes)` + parent→child edges of the CLASSIC
  render only. New classes on shared renderers (`_fstep_html`) break it — use attributes.
- **The F5 DOM law** demands an inventory row + hostile fixture for every new render function
  and every changed interpolation count: `chamber/dom-slot-inventory.json` +
  `tests/test_chamber_dom_law_w9.py::HOSTILE_FIXTURES`. `chamber_page.py` is NOT yet registered
  there — register it if it grows agent-influenced slots.
- **Two MBA campaigns exist** (`C:\dev\MBA Teaching AI` and the nested
  `MBA Teaching with AI`), forking his story. The nested one's `roadmap_projection` was edited
  outside the spine and disagrees with its event fold; the engine's heal law would revert four
  done statuses. His call, not the machine's.

## The rule this work runs under

`C:\dev\Skill Foundry\ELEGANCE.md`, injected into all 14 canonical SKILL.md. Approvals ≤200
words. Summaries ≤150. Default to the lightest band. Needed-because line on anything he did
not ask for. Show a cut. **And: a gate that cannot see what the user sees is not a gate —
render it, screenshot it, look at it.**
