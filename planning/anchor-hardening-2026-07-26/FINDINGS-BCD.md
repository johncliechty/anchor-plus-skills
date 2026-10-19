# FINDINGS B / C / D — tiles+summaries+restart · terminal · iPad dictation (2026-07-26)

All file:line verified read-only. Canonical tree = `C:\dev\Anchor` (release mirror
`C:\dev\Anchor-release-v1.0` ships the SAME defects — propagate every fix).
**Ecgberht: zero footprint in Anchor or the .anchor state tree — v1.2 integration
unobstructed.**

---

# B — SUMMARIES + RESTART DOCS (John: "summaries not great, restart docs not great")

## B1. The summary pipeline (it IS a model call ×2, then a token filter)
- Session summary: `summarizer.py:1154 summarize_session` → `:1130 _write_cache`;
  triggered at terminal state by `anchor_gui.py:1703`, on-view, on rescan
  (`anchor_gui.py:1970`), and at drain (`tools/pre_restart_drain.py:84`).
- Project summary: `summarizer.py:1836 summarize_project` → `:1798 _write_project_cache`
  (rescan/background ONLY — never on the render path).
- Tile blurb: `summarizer.py:1753 session_blurb` / `:1746 tile_blurb`, pure cache read
  at render (`anchor_gui.py:3815`).
- Mechanism: deterministic seed (`:267 extraction_seed`, ≤12 members ≤16KB, headings
  from `:209 _SECTION_SIGNALS`) → **generate TWICE** (`:585`, `GENERATE_RUNS=2` at
  `:73`, via `job_runner.launch("research")`, 60s) → grounding filter
  (`:649 _validate` → `:619 is_grounded`, `GROUNDING_MIN_RATIO=0.7` at `:84`; project
  path 0.5 at `:97`) = **pure token-overlap, no judge, no semantics** → cache
  (`SUMMARY_SCHEMA_VERSION=3`, never time-invalidated; only a schema bump regenerates).

## B2. Why they read badly — four distinct defects, each with evidence
1. **BLANK is the most common outcome (~60%+).** The DASHBOARD's own
   `C:\dev\.anchor\projects\__dashboard__\project-summary.md` is
   `"_No grounded objective could be extracted…_"` with `claims: []`,
   `no_grounded_claims: true`, `runs: 2` — **the model ran twice and 100% was
   rejected**; title is literally `"CLAUDE.md"` (`summarizer.py:1453 _first_heading`).
   Also 13/16 general-lane summaries, 3/5 zombie, both fallback build tiles.
   One zombie tile burned **194,422 tokens / 66.6s** and rendered blank.
   ROOT CAUSE: `summarizer.py:190 _read_bounded` returns `""` when `:167 _member_path`
   can't resolve an artifact → the grounding corpus is only member TITLES → every real
   sentence fails 0.7 overlap against a 3-word corpus. Compounded for `general`:
   `:286` falls back to `_SECTION_SIGNALS["planning"]`, scanning raw PTY transcripts
   for "north star/objective/decision" headings they never have → `anchors: []`.
2. **DUPLICATION — "generate twice, keep BOTH".** `summarizer.py:658-670 _validate`
   **unions** both runs, deduping only on exact-normalized-string (`:664`), then
   `:1598 render_project_markdown` joins them. Two paraphrases both survive.
   Evidence: `.anchor/projects/f69f6d66…/project-summary.md` ≈700 words saying the
   same thing twice; `__dashboard__/planning/summaries/dir_Agentic-Home/summary.md`
   29 bullets where :18 and :32 restate each other. "Generate twice for validation"
   was designed as consensus, implemented as concatenation.
3. **Wrong altitude / title echo.** `__dashboard__/planning/summaries/a148b810…/summary.md`:
   "What was asked: A148B810Db41 Transcript" (a hex filename), "Goal & key decisions"
   = the session BANNER (signed-in user, tier, model). `_session_what_was_asked`
   (`:450`) falls through to the title; `_session_actions` (`:399`) echoes it again.
4. **Stale caches never expire + mojibake.** `227eb089…/project-summary.md` still
   renders the v2 heading `## What this project is`; `f69f6d66…` contains
   `researchPrimeâ†'Crucibleâ†'Foreman` (pre-fix cp1252 mojibake).
   `load_cached_project` (`:1816`) invalidates ONLY on schema mismatch (`:1831`).

## B3. The restart/carry-on pipeline — why a fresh session still searches
- Writer: `terminal_session.py:3105 _write_restart_seed` → `<worktree>/<lane>/RESTART.md`
  (`:3153`); called from autosave (`:3191`, every 120s `:3077`) and halt (`:3339`).
  **Model-free by design** (`:3108`).
- Template (`:3137-3151`) emits exactly: session id, lane, engine, **first 200 chars of
  the seed** (`:3130`), a doc list, boilerplate. REAL example (`C:\dev\Anchor\general\RESTART.md`)
  has ✗ no goal ✗ no status ✗ no decisions ✗ no next action, and **all five "produced
  documents" are raw PTY transcripts**. `research/RESTART.md` is worse: the seed line is
  the skill-loading boilerplate ("Load the researchPrime skill now…").
- THREE readers, all degraded:
  1. `orientation.py:66 build_orientation_prompt` (fired by `_resumeLive`,
     `project-window.js:3280` → `anchor_gui.py:13284`) — `:117` correctly says "read
     RESTART.md first, don't read raw transcripts" but **the content it points at is
     empty**; its facts come from `narration.py:181 _floor_done` = literally
     `"ran researchPrime in research (2026-07-18, done)"`.
  2. `anchor_gui.py:1864 _build_continue_seed` — precedence cached summary (`:1892`) →
     digest → `_synthesize_discovered_seed` (`:1831`) → bare title (`:1958`).
     **It NEVER reads RESTART.md.** When the cached summary is the blank (common), the
     seed IS the blank.
  3. `terminal_session.py:1148` (engine switch) — the only reader that opens it.
- Also exists: `HANDOFF.md` (`handoff.py:700`, structure-only by design `:741`);
  **`NEXT-PROMPT.md` (`handoff.py:663`/`:585`) is the STRONGEST artifact in the system**
  (real doc paths, skill-correct) but exists ONLY on a lane ADVANCE — a same-lane
  restart never gets one. `pre_restart_drain.py:84 ensure_warm_seed` = good plumbing
  pointed at a weak generator.

## B4. Tile transitions — the jank source
`project-window.js:2212 _RESUME_REPOLL_MS=15000` → `:2217 setInterval(loadSessions)` →
`:2198 refreshBoard()` → `:3922` GET `/api/rnd/board_html` (`anchor_gui.py:15152` →
`:15181 _render_layoutd_html`) → **`:3966 board.innerHTML = data.html`**.
Five jank sources: (1) whole-subtree teardown every 15s destroys CSS transitions,
hover, focus, selection, scroll — no keyed diff; (2) state re-applied keyed on
`className` (`:3937`, `:3942`) so a tile whose classes change (exactly running→done)
LOSES state — already patched twice at `:3955-3963` for grassMiniList/gandalfRuns;
(3) `:3978` full-tree walk `#kanbanBoard *` every poll; (4) no transition possible on
status change (`.dot` swap inside a replaced node); (5) Layer-1 narration remount race
(`:3155`, polls 20× while enrichment generates, writing into a host refreshBoard may
have replaced). Plus `window.location.reload()` at `anchor_gui.py:7831`, `:8754`
(full white-flash).

## B5. Big-tile inventory vs restart support
Research ✅ full · Plan/Build ✅ full (best path: HANDOFF + NEXT-PROMPT) ·
**General ⚠️ WORST (no seed, no stage track `:3834`, no summarizer signal set) — and
it is John's daily lane** · Discovered ⚠️ filename-only phase inference (`:1797`) ·
Deliverables ❌ · Grass ⚠️ workbench-only, explicitly excluded from summaries
(`anchor_gui.py:1982-1984`) · Gandalf ❌ · Zombie ❌ (4/5 summaries blank) · Boneyard ❌ (by design).

## B6. PARKED C1 Stage 2 — no fix requires unparking it
C1 = extract the embedded frontend blobs from anchor_gui.py
(`planning/crucible-rearchitecture-2026-07/NORTH-STAR.md:25`). The **project-window
half ALREADY SHIPPED** (`static/project-window.js/.css/.html` are live). John parked
only the **home-dashboard f-string** half. Fixes B1-B4 are backend or live in the
already-extracted `static/project-window.js`. The ONLY brush with the parked blob is
the two `window.location.reload()` calls at `anchor_gui.py:7831`/`:8754` — a one-line
substitution each, NOT an extraction. **Recommend: change in place or drop from scope;
flag to John, never treat as licence to reopen C1 Stage 2.**

## B7. Top fixes (quality bars are assertable)
1. **RESTART.md becomes a real handoff brief generated AT HALT from live state**
   (`terminal_session.py:3105-3163`): bounded model pass at halt only (reuse
   `pre_restart_drain.py:84` 20s-timeout pattern so a wedged engine can't block close);
   demote `*-transcript.md` to an audit section; replace the boilerplate seed line
   (`:3130`) with the real objective. BAR: every brief has `## Goal` (≤25 words),
   `## Status` (running/blocked/waiting-on-human/done + because-clause), `## Done`
   (≤7), `## Open decisions & blockers`, `## Next action` (ONE imperative line),
   `## Deliverables` (non-transcript only), `## Do not re-litigate`. Empty Goal or
   Next-action = gate failure.
2. **Make run 2 a JUDGE, not a second author** (`summarizer.py:649-670`): keep a claim
   only if matched in ≥2 runs; collapse near-dupes (Jaccard ≥0.6, keep longer); cap
   project objective at 3 sentences. BAR: no two sentences with ≥60% content-token
   overlap; project summary ≤90 words. Fixture: `f69f6d66…` must shrink 700→~1 para.
3. **Fix the grounding CORPUS** (`summarizer.py:190/:167/:619/:286/:209`): if seed text
   <400 chars after member reads, **do not call the model at all** — emit an honest
   deterministic tile (the zombie tile burned 194k tokens for a blank); add a real
   `general` signal set + transcript-aware seed (strip ANSI/spinners, lift USER TURNS
   as anchors); prefer non-transcript members. BAR: `no_grounded_claims` rate from
   ~60% → <10%; zero model calls on a title-only corpus.
4. **Wire the brief into the readers** (`anchor_gui.py:1864-1967`, `orientation.py:66-118`,
   `narration.py:294`): RESTART.md becomes precedence rank 0 in `_build_continue_seed`
   (it survives worktree eviction — `terminal_session.py:3111` persists it to MAIN);
   orientation inlines Goal/Status/Next verbatim instead of `_floor_done`; narration
   spine gains `goal` + `open_decisions`. BAR: a resumed session's FIRST model turn
   cites Goal + Next action with **zero** exploratory Read/Grep calls first
   (instrument + assert `tool_calls_before_first_answer == 0`).
5. **Keyed diff instead of the 15s innerHTML swap** (`project-window.js:3922-4015`,
   `:2212-2217`; `anchor_gui.py:15152`): server-computed `data-state-hash` per zone →
   unchanged ⇒ DO NOTHING (today it re-swaps regardless); changed ⇒ diff by
   `data-session`, patch text/`data-light` on the REUSED node so CSS transitions fire;
   delete the whole openStates block (`:3934-4003`); add a reduced-motion-aware 200ms
   cross-fade + stable `.headline` min-height; replace the two `location.reload()`s.
   BAR: zero innerHTML writes when state unchanged; same node identity across a
   running→done transition (Playwright); no lost `<details>`/scroll/selection over 5 polls.

---

# C — TERMINAL DOUBLE-PRINTING (John's laptop) — ROOT CAUSE FOUND

## C1. Architecture
ConPTY (pywinpty) → `pty_manager.py:232 _drain` → cumulative in-memory `_buf` +
absolute counters, capped `MAX_BUFFER_CHARS=200_000` (`:68`, `:246 _append`) →
`:310 read_since(cursor)` → `terminal_session.py:1661` → server:
`anchor_gui.py:16539 _serve_term_ws` (hand-rolled RFC-6455) or `:16416
_serve_term_stream2` (SSE + POST `term_input2`) → client `project-window.js:4248
_mountTerminal`, appends at `:4427` (WS) / `:4405` (SSE). **Not the ZH/tidy-idy
pattern — bespoke.** Release mirror byte-identical in this region.

## C2. THE BUG (#1): every (re)connect replays the whole 200KB buffer from cursor 0
- `since=` appears **NOWHERE** in `project-window.js` (all 5873 lines). SSE URL built
  without it at `:4395`; server defaults `since=0` (`anchor_gui.py:16434-16436`),
  `cursor=since` (`:16466`), replays the retained window (`:16488-16492`).
- **WS is worse: no `since` knob at all** — `anchor_gui.py:16608` hard-codes
  `cursor = 0`, replays at `:16635-16638`.
- Client has no dedupe and no `term.reset()` before replay — it writes ON TOP.
#2 **`ws.onclose` falls back to SSE even when WS WAS working** (`:4429-4434`): the guard
only checks `sseStarted`, never whether bytes arrived (no `gotData` flag) → a WS that
streamed for an hour then closes (sleep/roam/service restart) triggers a full cursor-0
SSE replay = instant duplicate.
#3 **`_mountTerminal` never tears down the previous term/transport** (`:4248-4262`):
disconnects ResizeObserver (`:4282`) but no `transport.close()` / `term.dispose()`.
Re-entrant call sites `:1209, :1512, :1622, :2747, :4380`; `openPanel` replaces
`PANELS[sessionId]` wholesale at `:2739` orphaning the old transport.
#4 **EventSource auto-reconnect unmanaged** (`:4408` empty onerror): server sends
`Connection: close` (`:16463`) and NO `id:` field (`_sse_event` `:16118`) so
Last-Event-ID resumption is impossible → every auto-retry restarts at cursor 0.
RULED OUT: server+client echo, poller+stream, duplicate status injector
(`terminal_session.py:1933`, single call site `:795` — its `[STATUS hh:mm]` lines are a
useful replay MARKER, not a cause).

## C3. "Not tracking well"
Cursor is server-only, per-connection, in the handler frame (`:16466`, `:16608`) —
destroyed on any TCP teardown, client has no copy. `read_since` clamps a stale cursor to
`_dropped` (`pty_manager.py:314`); `attach` returns `dropped`/`truncated` honestly
(`terminal_session.py:1622-1631`) but **neither transport forwards them and the client
never reads them** — silent scrollback loss past 200k chars. xterm `scrollback: 5000`
(`:4260`) is blown through by one replay, evicting real history and yanking the viewport.

## C4. Laptop-specific
**No `visibilitychange` / `pagehide` / `online` / `offline` handler exists anywhere** in
project-window.js — only `focus → repopulate` (`:2214-2216`) which refreshes tiles, not
the transport. Background-tab throttling coalesces the 15s interval then bursts. DPI/
dock change: PTY resized (`pty_manager.py:319-326`) but buffered ANSI was rendered for
the OLD cols → a later cursor-0 replay re-renders old-width escapes at the new width =
garbled. `_fitPanelTerminalDeferred` gives up after 40 frames (`:3842-3870`) — under
battery-saver frame throttling the fit can silently never run.

## C5. LOG EVIDENCE (nssm-stdout.log)
- **3 mounts + 3 full replays in 3s** — `:78310`, `:78313`, `:78315` (each
  `term_stream2` preceded by a `term_resize`; `_fitPanelTerminalDeferred` fits exactly
  once per mount by design `:3861-3867` ⇒ each resize = a NEW Terminal object).
  Duplicated `/api/rnd/chain` at `:78306`/`:78308` — openPanel AND openEffortDock ran.
- **Sleep-shaped 92-minute gap then TWO simultaneous replays** — `:82256-:82260`:
  two EventSources for the same session in the SAME second, no term_resize between
  (not a remount) = leaked transport (#3) + auto-reconnect (#4). **This is John's exact
  symptom.**
- Same pattern `:12319/:12332/:12355`, `:78507/:78515`.
- `term_ws` never appears in the log (handshake via raw `sendall` at `:16600` bypasses
  logging) — absence is not proof WS is unused; but 16 SSE hits prove fallback is routine.

## C6. Top 3 fixes
1. **Client-side cursor + resume** — carry `var cursor` in `_mountTerminal`, append
   `&since=` to BOTH URLs (`:4395`, `:4390`), update from the `next` already in every
   SSE payload (`:4404-4406`, currently discarded at `:4403`); make the WS read `since`
   like SSE does (`anchor_gui.py:16608` vs `:16434-16436`). Surface `dropped` in
   `replay_complete` (`:16493`/`:16639`) and print a `── N chars dropped ──` divider.
   VERIFY (no laptop): `tests/test_terminal_session.py` with `ANCHOR_PTY_BACKEND=stub` —
   two sequential `term_stream2`, second with `since=<next>`, assert `text == ""`.
2. **`gotData` flag before SSE fallback + real teardown in `_mountTerminal`**
   (`:4429-4433`, `:4248-4262`, `openPanel :2739`). VERIFY: Playwright (harness exists:
   `tests/test_ui_quickfix_w5.py`, `test_window_controls_v6.py`) + CDP
   `Network.emulateNetworkConditions{offline}` to reproduce sleep/resume deterministically;
   assert one `.xterm` per host and a sentinel line appears exactly once.
3. **Explicit resume/visibility handling** (`:2214-2218`): `visibilitychange`/`online`/
   `pageshow` → `_ensureTransport` reconnecting FROM THE STORED CURSOR with backoff +
   an in-flight flag (kills the 14:22:28 double); raise scrollback; `term.reset()` before
   a forced cursor-0 replay.

---

# D — iPad DICTATION — ROOT CAUSE FOUND (vendor xterm defect + Anchor amplifiers)

## D1. There is NO chat box — the iPad types into xterm's hidden 0×0 helper textarea
Mount `project-window.js:4259-4261`; **every byte streams as it arrives**:
`:4311 term.onData(d => _sendInput(d))` → `:4300-4310` WS send or POST
`/api/rnd/term_input2` → `anchor_gui.py:13010-13024` → `_termsess.input()`.
**No length cap, no dedupe, no repeat guard** (contrast the legacy REPL which DOES cap:
`anchor_gui.py:11024-11033`, `rnd_terminal.MAX_TURN_CHARS` `rnd_terminal.py:175-179`).
The editable element is `.xterm-helper-textarea`, styled `opacity:0; left:-9999em;
width:0; height:0; z-index:-5` (`vendor/xterm/xterm.css:61-77`, @xterm/xterm 6.0.0).

## D2. ROOT CAUSE (one line)
In `vendor/xterm/xterm.js:1` `CompositionHelper._finalizeComposition`, the textarea is
**never cleared after commit**; the only anti-duplication guard is
`e.start += this._dataAlreadySent.length`, and `_dataAlreadySent` is written ONLY by
`_handleAnyTextareaChanges()`, reachable ONLY from `keyCode === 229` keydown.
**iOS dictation sends NO keydown at all** ⇒ `_dataAlreadySent` stays `""` ⇒ every
`compositionend` re-emits `value.substring(start)` of an ever-growing buffer ⇒
`"a"`, `"a b"`, `"a b c"` — the exponential blow-up. Anchor then forwards it verbatim,
uncapped (`project-window.js:4311` → `anchor_gui.py:13018`).
Secondary: `_inputEvent` accepts ONLY `inputType === "insertText"`, so iOS's
`insertReplacementText` re-recognition commit is DROPPED — but the textarea still grows,
so the next compositionend sweeps it up (missing-then-duplicated in one defect).
Contributing: the 0×0/off-screen/negative-z target gives iOS no caret rect, pushing
Safari into whole-field replacement per utterance.
Anchor has **zero** composition awareness: grep `composition|beforeinput|
insertReplacement|isComposing` across `static/**` + `*.py` = NO MATCHES; the only key
hook is keydown-gated (`:4318 if (e.type !== 'keydown') return true`).
AMPLIFIER: two live mounts per session (5 call sites; one-way exclusion documented in
`docs/friction/2026-07-25-dual-terminal-screens.md:129`, `:83` explicitly links it to
"iPad dictation blow-up | Dual input targets").

## D3. Transport is CLEAN (not the cause)
`:4388-4390` protocol-derived same-origin wss/ws (no mixed content); graceful SSE
fallback; case-insensitive upgrade detection (`anchor_gui.py:16719`). The `apiUrl`/
reverse-proxy mechanism is a DIFFERENT subsystem (zombie-hunter/tidy-idy sidecar via
`/api/rnd/tidy_idy_proxy/`), not on the input path. One real iPad risk: WS auth token
from localStorage (`:155`, `:4264-4265`, `:4390`) — an "Add to Home Screen" PWA has
separate localStorage ⇒ 401 before upgrade ⇒ silent SSE fallback (degrades, doesn't
duplicate). `anchor_gui.py:182` names this hazard.

## D4. Evidence — no HTTP access log; the FRICTION JOURNALS are the record
`logs/` has only daily markdown + NSSM stdout/stderr; grep iPad|Safari|composition = none.
- `docs/friction/2026-07-25-terminal-dictation.md:9` — "**iPad:** each new dictated
  sentence re-includes all prior dictated text → exponential/cumulative blow-up."
- `docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md:92` — "re-pastes
  everything said so far plus the new sentence… Live proof polluted Family Trusts
  general transcripts (hundreds of repeated loops)."; `:95` hypothesis #1 "IME/
  composition commit firing full buffer instead of delta" — **CONFIRMED CORRECT**.
- RULED OUT from that list: #2 paste-not-submit/seed re-injection — guarded idempotent
  (`terminal_session.py:989`, `:1045` sets `paste_flushed` + clears under lock).

## D5. Top 3 fixes
1. **Add a dictation-safe COMPOSE BOX for the ConPTY session (highest value — the
   widget already exists)**: `vendor/anchor-term/anchor-term.js:72-82` is exactly right
   (visible `<input>`, Enter-to-send) but wired only to the legacy v2 REPL (`:194`).
   Port it into the ConPTY panel/dock beside `body` (`project-window.js:4248-4270`) and
   route to `_sendInput` so nothing hits the raw per-character PTY path. Gate the send
   on `e.isComposing === false && e.keyCode !== 229` BEFORE reading `.value`; add
   `enterkeyhint="send"`, `autocapitalize="sentences"`, `autocorrect="on"`.
   VERIFY (desktop): dispatch `compositionstart` → set value → `InputEvent('input',
   {inputType:'insertReplacementText'})` → `compositionend`, twice; assert the network
   carries `"hello"` then `" world"` — never `"hello world"` twice.
2. **Break the loop at Anchor's boundary (no vendor fork)** (`:4300-4311`): listen on
   `body.querySelector('.xterm-helper-textarea')` for compositionstart/end, suppress
   `_sendInput` while composing, emit once on end with a locally-tracked `lastSent`
   prefix stripped, and **clear `textarea.value = ''` after each commit** (this alone
   kills the `substring(e.start)` regrowth). Add a server-side cap mirroring the REPL
   (`anchor_gui.py:13014` ← use `MAX_TURN_CHARS` as at `:11029`).
3. **Make the textarea dictation-addressable + one mount per session**:
   `@media (pointer: coarse) { .xterm-helper-textarea { left:0; top:0; width:1px;
   height:1em; opacity:.01; z-index:5; } }` in `static/project-window.css` (a non-zero
   rect is what lets iOS do caret-relative delta insert); dispose any existing mount for
   the same sessionId across BOTH homes (`PANELS[sessionId]` and `DOCK`) in
   `_mountTerminal` (`:4248-4253`); add `visualViewport resize → _fitPanelTerminal`
   (`:4283`) so the iOS keyboard doesn't occlude.

---

# CROSS-CUTTING (all three agents independently)
- **`_mountTerminal` lacking teardown is a SHARED root cause** of terminal duplication
  (C#3) and iPad dual-input (D-amplifier) — fix once, both improve.
- **The release mirror `C:\dev\Anchor-release-v1.0` carries every one of these defects**
  (byte-identical client code) — the v1.1.0 bundle collaborators would install today
  has the terminal replay bug, the dictation blow-up, and the blank summaries.
- **John's daily "general" lane is the WORST-supported path** (no seed, no stage track,
  no summarizer signal set, blank summaries, thinnest RESTART.md).
