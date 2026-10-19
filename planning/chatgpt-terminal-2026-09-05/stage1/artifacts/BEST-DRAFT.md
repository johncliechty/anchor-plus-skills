# Master Plan (draft)

**North Star:** # North Star — ChatGPT is a first-class Terminal engine in Anchor (2026-09-05)

**Statement.** ChatGPT (the Codex CLI, v0.151) becomes a first-class engine for Anchor's
**Terminal** role — the fourth and last role that still said "bridge pending". An interactive
cockpit terminal opens on the Codex TUI in the session's worktree exactly as Claude and Grok
terminals do: seeded once with the lane skill, engine-switchable in place, closable and
resumable, Doctor-capable in a read-only posture; the dashboard offers it as ready; a saved
`default_cli=chatgpt` persists; and usage accounting says honestly "unmeasured" for the ChatGPT
segment (the RULED Option C) instead of guessing. John, 2026-09-05: "Is ChatGPT available for
all of the roles in Anchor? … Do that, integrate, before shipping v1.2.12."

**Why now.** v1.2.8 deferred the Terminal seat as "bridge pending" on the belief that a
persistent Codex exec/resume bridge was needed. It is not, for the terminal: Codex ships an
interactive TUI (`codex [PROMPT]`, `-C/--cd`, `-s/--sandbox`, `-a`, `-m`, `--no-alt-screen`,
`resume <id>`), the engine-command resolver for it already exists (`terminal_session.
_resolve_engine_cmd`), and the only thing closing the seat is one guard
(`_check_engine_allowed`) plus the settings/capability tables. Reviewer and Judge opened this
morning; Coder was open already.

## Success criteria (the SURFACE, not the capability)

1. **A terminal opens on ChatGPT.** With `default_cli=chatgpt` (or the engine toggle),
   `POST /api/rnd/term_start` starts a PTY running the Codex TUI in the session worktree
   (`--cd <worktree>`, `--no-alt-screen`, `-s workspace-write`, approvals left to the user in
   the terminal), the lane seed is written exactly once and the greet arrives, the registry
   record carries `backend: chatgpt`, and `POST /api/rnd/term_set_engine` switches a live
   session to and from ChatGPT in the same worktree with no orphan PTY.
2. **The truth tables agree.** The Terminal picker shows "ChatGPT — ready" (no "bridge
   pending" anywhere: capability matrix, option labels, the capability note, `anchor_settings`
   comments); `VALID_DEFAULT_CLIS` includes `chatgpt` and `save_settings(default_cli="chatgpt")`
   persists; `_check_engine_allowed` no longer gates `chatgpt`; a host without the Codex binary
   still fails closed with the existing `chatgpt-terminal-binary-missing` error.
3. **Doctor posture and honest accounting.** `live_doctor_session(backend="chatgpt")` launches
   with `-s read-only` (a `DOCTOR_READONLY_CLI_ARGS` entry); no session-id pin exists for Codex,
   so the session's usage state is `uncorrelated` and any rollup that includes it is stamped
   `partial (chatgpt segment unmeasured)` — never an mtime guess, never a fabricated $0.00.
4. **Nothing regresses, and it is seen.** The terminal nets stay green under the stub PTY
   (`ANCHOR_PTY_BACKEND=stub` + `ANCHOR_ENGINE_CMD`), `_LIVE_ENGINE_BASENAMES` still refuses a
   real `codex` spawn under test, the 5 AM v3/v4 walks are unchanged, `distro.py`'s import
   scan stays clean; and before v1.2.12 ships a ChatGPT terminal is opened from the dashboard
   and its greet is seen on the page (Playwright screenshot), not inferred from a stub.

## Non-goals (parked, named)

- The ChatGPT **Steward** (the cockpit dialogue engine speaks stream-json to `claude -p`; a
  ChatGPT steward is the F1B exec/resume bridge) — its own Foundry cycle.
- Doctor and Zombie Hunter ChatGPT *certification* beyond the read-only posture.
- Usage-cost correlation for Codex sessions (Option C stays honest-unmeasured).
- Per-seat model pinning in the terminal (`-m`) beyond what the prefs already carry.

## Risk taxonomy

| Risk | Mitigation |
|---|---|
| The Codex TUI's alternate screen renders badly through ConPTY + xterm.js | `--no-alt-screen` (inline mode) by default; verified on John's screen before ship |
| The seed turn lands before the TUI is ready, or Codex asks for approval on the seed | reuse the Grok seed timing (write after first output); the seed only loads the skill and greets; approvals stay `on-request` for the user to answer in the terminal |
| A saved `default_cli=chatgpt` reaches a host without Codex | the resolver's fail-closed `chatgpt-terminal-binary-missing` stands; the picker shows "unavailable" there |
| Tests that pin "bridge pending" go stale silently | every pin is rewritten to the new truth in the same wave, with the wave's done-when naming the file |

## Foresight brief

With the Terminal seat open, the four dashboard roles are complete for Claude, Grok and
ChatGPT. The next cycle is the ChatGPT steward (F1B): a per-turn `codex exec` with `resume`
behind the same status pane. The engine-toggle code path this effort exercises is the one
that bridge will reuse.


## Success criteria
- A terminal opens on ChatGPT: with default_cli=chatgpt or the engine toggle, POST /api/rnd/term_start starts a PTY running the Codex TUI in the session worktree (--cd <worktree>, --no-alt-screen, -s workspace-write; approvals left to the user), the lane seed is written exactly once and the greet arrives, the registry record carries backend chatgpt, and term_set_engine switches a live session to and from chatgpt in the same worktree with no orphan PTY
- The truth tables agree: the Terminal picker shows "ChatGPT — ready" (no "bridge pending" anywhere: capability matrix, option labels, capability note, anchor_settings comments); VALID_DEFAULT_CLIS includes chatgpt and save_settings(default_cli="chatgpt") persists; _check_engine_allowed no longer gates chatgpt; a host without the Codex binary still fails closed with the existing chatgpt-terminal-binary-missing error
- Doctor posture and honest accounting: live_doctor_session(backend="chatgpt") launches with -s read-only (a DOCTOR_READONLY_CLI_ARGS entry); no session-id pin exists for Codex so the usage state is uncorrelated and a rollup that includes it is stamped partial (chatgpt segment unmeasured) — never an mtime guess, never a fabricated $0.00
- Nothing regresses and it is seen: the terminal nets stay green under the stub PTY (ANCHOR_PTY_BACKEND=stub + ANCHOR_ENGINE_CMD), _LIVE_ENGINE_BASENAMES still refuses a real codex spawn under test, the 5 AM v3/v4 walks are unchanged, distro.py import scan stays clean; every test that pinned "bridge pending" is rewritten to the new truth in the same wave; a ChatGPT terminal opened from the dashboard shows its greet on the page (Playwright) before v1.2.12 ships

Four phases, ordered so the seat opens first and is proven last. Phase 1 opens the one guard and makes every truth table say 'ready' (criterion 2, and the register-as-chatgpt half of criterion 1). Phase 2 adds the per-backend interactive launch argv (--no-alt-screen, -s workspace-write, --cd <worktree>) and the first-output-gated seed so a terminal actually opens on the Codex TUI and survives an engine switch (criterion 1). Phase 3 adds the Doctor read-only contract and generalizes the W5 gemini-only 'unmeasured segment' marker so a ChatGPT segment is stamped 'partial (chatgpt segment unmeasured)' / 'uncorrelated' and never a fabricated number (criterion 3). Phase 4 is the regression net plus the only real proof: a Playwright live test that opens a ChatGPT terminal from the dashboard, sees the Codex greet on the page, screenshots it, and toggles engines with no orphan PTY (criterion 4), then the v1.2.12 ship gate. The premortem mitigation slots arrived empty ('undefined'), so the plan builds in the North Star's own risk-table mitigations explicitly instead: inline mode by default, Grok-style seed timing, the fail-closed missing-binary error, and same-wave rewrites of every 'bridge pending' pin. Named non-goals stay parked: the job-layer / one-shot bridge-pending gates in lanes.py (CHATGPT_RUNNABLE_LANES, select_engine_plan) and job_runner.py are the F1B steward and are NOT touched by this effort.

## Phase 1 — Phase 1 — Open the gate and make the truth tables agree

Serves criterion 2 (no 'bridge pending' anywhere; VALID_DEFAULT_CLIS includes chatgpt; _check_engine_allowed no longer gates it; absent Codex still fails closed) and the registry half of criterion 1 (record carries backend chatgpt). Grounded audit: the ConPTY start path is terminal_session.start_session -> _check_engine_allowed (line 388) -> lanes.check_engine_allowed, and lanes.check_engine_allowed already passes chatgpt on every lane, so the ONLY terminal-path guard is the raise at terminal_session.py:398-403. Everything else is settings and capability tables.

**Near-term specifics:**
- terminal_session.py:398-403 — delete the BACKEND_CHATGPT raise in _check_engine_allowed; keep the VALID_BACKENDS check and the lanes.check_engine_allowed call unchanged. Rewrite the stale comment at terminal_session.py:520-523 ('_check_engine_allowed gates this engine off earlier today') and KEEP the fail-closed 'chatgpt-terminal-binary-missing' raise in _resolve_engine_cmd exactly as is.
- anchor_settings.py:29-34 — VALID_DEFAULT_CLIS = frozenset({'claude','gemini','grok','chatgpt'}); rewrite the 'bridge pending' comment to name the terminal seat as ready; keep the VALID_DEFAULT_CLIS name (anchor_settings.py:121/153/205 and tests/test_backend_chatgpt.py:60/65 reference it) — if a VALID_CLIS alias is wanted, add it as an alias, never a rename. Done-when: save_settings(default_cli='chatgpt') persists and get_default_cli() returns 'chatgpt' after reload.
- anchor_gui.py:5838-5844 model_role_capabilities — the terminal/chatgpt branch becomes selectable=True, status='ready', reason='Codex CLI detected; the interactive terminal opens on the Codex TUI in the session worktree.' Remove the 'bridge_pending' status from the label maps at anchor_gui.py:5920 and :6012, and rewrite the capability note strings at :5944 and :6047 to '... reviewer and judge ready (model unattested, stamped) · terminal ready'.
- rnd_terminal.py:100-107 — delete the duplicate v2-REPL pre-gate so that legacy fallback path defers to job_runner's single gate (job_runner's own stream-json bridge-pending gates at job_runner.py:493/741/787 are the F1B steward and stay).
- Same-wave test rewrites (the risk-table rule): tests/test_backend_chatgpt.py:60,65 (chatgpt IS in VALID_DEFAULT_CLIS), :76 (status == 'ready'), :100/:105 (the picker option renders 'ChatGPT &mdash; ready' once and no seat is disabled), :204-255 (the three bridge-pending tests become: stub-PTY start_session(backend='chatgpt') returns a record with backend=='chatgpt' and creates a worktree; switch_engine to chatgpt and back in the same worktree; a shutil.which-patched absent-codex host raises 'chatgpt-terminal-binary-missing' BEFORE any worktree is created). tests/test_chatgpt_lane_routing.py:419-428 pins the JOB-layer select_engine_plan('general', chatgpt) bridge-pending — that gate is a named non-goal, so the test is retitled to say 'job-layer' and kept green as is.
- Done-when for the phase: under ANCHOR_PTY_BACKEND=stub + ANCHOR_ENGINE_CMD=<stub>, start_session(pid,'general',backend='chatgpt') registers backend 'chatgpt'; a grep for 'bridge pending' / 'bridge_pending' over anchor_gui.py, anchor_settings.py, terminal_session.py, rnd_terminal.py and tests/test_backend_chatgpt.py returns zero hits (lanes.py and job_runner.py hits are listed by line as the parked F1B set).

**Deferred (explicitly):**
- The job-layer gates: lanes.py:343 CHATGPT_RUNNABLE_LANES and lanes.py:549-557 select_engine_plan bridge-pending for general/plan/build, plus job_runner.py:493/741/787 — these are the one-shot exec/resume steward (F1B), a named non-goal; left byte-identical.
- Historical docs that say 'bridge pending' (planning/v1.2.8/SESSION.md, planning/chatgpt-terminal-2026-09-05/baseline-context.md) stay as history; only CHANGELOG.md gets the new v1.2.12 line in Phase 4.
- bundle_staging/ mirrors (bundle_staging/terminal_session.py etc.) are NOT hand-edited; they are regenerated by the distro builder at ship time in Phase 4.

## Phase 2 — Phase 2 — Interactive launch argv and first-output seed for the Codex TUI

Serves criterion 1: a PTY running the Codex TUI in the worktree with --cd <worktree>, --no-alt-screen, -s workspace-write, the lane seed written exactly once with the greet arriving, and term_set_engine switching to and from chatgpt in the same worktree with no orphan PTY. This is also where the two top risks in the North Star table are mitigated in code: alternate-screen rendering (inline mode by default) and seed-before-ready (write after first output).

**Near-term specifics:**
- terminal_session.py near line 550 — add a module-level ENGINE_LAUNCH_ARGS = {_reg.BACKEND_CHATGPT: ('--no-alt-screen', '-s', 'workspace-write')} and a PURE helper _interactive_launch_args(backend, cwd, extra_cli_args) -> list that returns the table entry plus ['--cd', cwd] for chatgpt only (Codex resolves its sandbox root from --cd, not the PTY cwd), and DROPS the default '-s workspace-write' pair when extra_cli_args already carries a '-s' (so the Doctor's read-only posture in Phase 3 replaces, never duplicates, the sandbox flag). cwd is whatever is actually passed to _pty.start (the worktree for lanes; the live Anchor folder for the Doctor).
- Apply it in start_session after _engine_launch_argv (terminal_session.py:727) and before the extra_cli_args append (:733), and at BOTH switch_engine relaunch sites (:1546 and :1692) so a claude->chatgpt switch launches the same argv shape as a fresh start. For chatgpt _engine_launch_argv returns [cmd] alone (no session-id pin), so stored_engine_uuid == '' — exactly the 'uncorrelated' state Phase 3 relies on; assert that under the stub.
- Argv order asserted under the stub in a new tests/test_chatgpt_terminal_w2.py: [<cmd>, '--no-alt-screen', '-s', 'workspace-write', '--cd', <worktree_path>] followed by any extra_cli_args; claude/grok/gemini argv byte-unchanged (pin with the existing tests/test_backend_grok.py:100 and tests/test_usage_capture_w4.py:392 shapes).
- Seed timing (the Grok 'write after first output' mitigation): keep the stdin seed at terminal_session.py:854-864 as the primary path for chatgpt, but for backends in a new SEED_AFTER_FIRST_OUTPUT_BACKENDS = {chatgpt} wait (bounded by a ANCHOR_SEED_FIRST_OUTPUT_TIMEOUT seam, default ~8s; the stub PTY emits output immediately so tests stay fast) for the first PTY output before the write; on timeout still write (never leave a live session silently unseeded) and record seed_delivery='stdin-after-first-output' or 'stdin-timeout-fallback' alongside seeded=True so the Phase 4 live sign-off can tell which path ran. seeded=True is recorded only after a successful _pty.write, as today.
- Approvals stay with the user: no '-a' / approval flag is injected; the seed only loads the lane skill and greets. The gemini '-i' argv-seed branch at :742-744 is untouched.
- Done-when: stub start_session(backend='chatgpt') yields record.seeded True with the seed written exactly once (no re-emit on repeated read_since, the v4 seed-once walk); switch_engine chatgpt->claude->chatgpt leaves exactly one id in pty_manager.live_sessions() and the same worktree_path on the record.

**Deferred (explicitly):**
- Positional-argv seed fallback (codex '<seed>' as the first argv prompt) — only if the Phase 4 live run shows the Codex composer drops early stdin; named here so it is not silently omitted.
- Per-seat model pinning in the terminal (codex -m <model>) beyond what the prefs already carry — North Star non-goal.
- Codex-native warm resume (codex resume <id>) for a parked chatgpt session — close/resume today re-seeds engine-agnostically from the cached summary (W3/W6), which is sufficient for this cycle.

## Phase 3 — Phase 3 — Doctor read-only posture and honest 'unmeasured' accounting

Serves criterion 3: live_doctor_session(backend='chatgpt') launches with -s read-only via a DOCTOR_READONLY_CLI_ARGS entry, and because Codex has no session-id pin the usage state is 'uncorrelated' with any rollup that includes it stamped 'partial (chatgpt segment unmeasured)' — never an mtime guess, never a fabricated $0.00. This generalizes the RULED Option C from a gemini-only marker to a per-backend list.

**Near-term specifics:**
- terminal_session.py:950-953 — add _reg.BACKEND_CHATGPT: ('-s', 'read-only') to DOCTOR_READONLY_CLI_ARGS; rewrite the docstring/comment at :1031-1033 (which currently names 'partial Codex/ChatGPT support' as deliberately absent). Behavioral test: start_doctor_session(backend='chatgpt') under the stub launches argv containing '--no-alt-screen', exactly ONE '-s' whose value is 'read-only', and '--cd' equal to the Doctor cwd (the Phase 2 dedupe rule is what makes 'exactly one' true); a second start attaches via live_doctor_session(mode, backend='chatgpt', posture) keyed reuse; resolve=True keeps the Phase 2 workspace-write default (write posture) and asserts no 'read-only' in argv.
- Accounting generalization: a new UNMEASURED_SEGMENT_BACKENDS = {gemini, chatgpt} in terminal_session.py; at the launch stamp (:841-845) and the switch_engine stamp (:1607) write usage_unmeasured_segments=[...backend] (append, deduped) and, for gemini only, keep writing the legacy usage_gemini_segment=True so old readers and old records stay valid. session_registry.py:433/518/883 — carry usage_unmeasured_segments (default []) through the SAFE projection and the persisted-field list.
- rollup_honesty.py:96-109 — has_gemini_segment stays as a compatibility wrapper; add unmeasured_segments(record) -> list built from backend in UNMEASURED_SEGMENT_BACKENDS OR the new list OR the legacy gemini marker. classify_session_usage (:114-156): measured + any segment -> STATE_PARTIAL with reason per segment; usage_capture.py:69 gains REASON_CHATGPT_SEGMENT = 'chatgpt-segment' and _REASON_LABELS (rollup_honesty.py:73) gains 'partial (chatgpt segment unmeasured)'; a session that ended on chatgpt with no reason is stamped chatgpt-segment.
- Finalize truth: a chatgpt-START session has stored_engine_uuid == '' (Phase 2), so the existing W4 finalize path yields usage_state 'uncorrelated' — add a test that asserts this and that NO cost/tokens number is written for it (no $0.00 measured row) and that the mtime/cwd-window path is never entered.
- Tests: tests/test_rollup_honesty_w5.py gemini cases stay green unchanged; new chatgpt cases mirror each of them (launch stamp, switch stamp, claude->chatgpt->claude round-trip still partial, SAFE projection carries the list, legacy record with only usage_gemini_segment still classifies partial).
- Done-when: rnd rollup / the dashboard badge for a project with one chatgpt session reads partial with title 'partial (chatgpt segment unmeasured)'; the Doctor Diagnose button with backend chatgpt opens a read-only Codex TUI under the stub walk.

**Deferred (explicitly):**
- Usage-cost correlation for Codex sessions (reading the Codex JSONL / receipts to measure the segment) — North Star non-goal; Option C stays honest-unmeasured.
- Doctor and Zombie Hunter ChatGPT certification beyond the read-only launch posture (identity/liveness proofs specific to the codex process tree) — non-goal.
- Retiring the legacy usage_gemini_segment key entirely — kept readable this cycle; a later cleanup once no pre-v1.2.12 records remain.

## Phase 4 — Phase 4 — Regression net, live Playwright sign-off, and the v1.2.12 ship gate

Serves criterion 4: the terminal nets stay green under the stub, _LIVE_ENGINE_BASENAMES still refuses a real codex spawn under test, the 5 AM v3/v4 walks and distro.py's import scan are unchanged, every 'bridge pending' pin was rewritten in its own wave (verified here by grep), and a ChatGPT terminal opened from the dashboard shows its greet on the page before v1.2.12 ships — the only proof for the render and seed-timing risks that no stub can supply.

**Near-term specifics:**
- Explicit refusal test: with codex 'present' (patched shutil.which), ANCHOR_ENGINE_CMD unset and pytest loaded, start_session(backend='chatgpt') raises 'live-engine-spawn-refused' before any PTY starts; assert 'codex' in terminal_session._LIVE_ENGINE_BASENAMES (:452).
- Unchanged-surface guards: a test asserting anchor_healthcheck.py contains zero occurrences of 'chatgpt'/'codex' (it has 0 today and the v3/v4 walks must stay byte-identical); run the existing distro.py import-scan test and the stub terminal suites (tests/test_backend_chatgpt.py, test_backend_grok.py, test_usage_capture_w4.py, test_rollup_honesty_w5.py, test_model_switch_w7.py, the doctor V3 tests) as the wave gate; a final grep for 'bridge pending'/'bridge_pending'/'chatgpt-gated-bridge-pending' whose only hits are the named F1B job-layer lines in lanes.py and job_runner.py.
- Live sign-off test tests/test_chatgpt_terminal_live.py: pytest.importorskip('playwright'), skipped unless ANCHOR_TESTS_ALLOW_LIVE=1 and a real codex binary resolves; boots a throwaway server on an OS-assigned port (never 8777) with a temp data dir and real ConPTY; sets default_cli=chatgpt through the settings API; opens a terminal from the dashboard 'Open terminal' button; waits for the Codex greet text on the page; screenshots to planning/chatgpt-terminal-2026-09-05/signoff/chatgpt-terminal-greet.png; toggles the engine to claude and back to chatgpt asserting len(pty_manager.live_sessions()) is unchanged after each switch (no orphan) and the worktree_path is the same; records which seed_delivery path ran.
- Deployed verification on John's screen: warm restart (restart_anchor.ps1), open a ChatGPT terminal on a real project, confirm inline (--no-alt-screen) rendering through xterm.js is legible and the greet is visible; if the composer dropped the early seed, invoke the Phase 2 deferred positional-argv fallback before ship.
- Ship: CHANGELOG.md v1.2.12 entry ('ChatGPT is a first-class Terminal engine'); CLAUDE.md engine line updated; regenerate bundle_staging/ via the distro builder (never hand-edit); tag v1.2.12 only after the Playwright screenshot exists and the full stub suite is green.

**Deferred (explicitly):**
- The ChatGPT Steward (F1B): a per-turn codex exec with resume behind the same status pane, reusing the engine-toggle path this effort exercises — its own Foundry cycle.
- A 5 AM healthcheck walk for the chatgpt seat — deliberately NOT added (the walks must stay unchanged and never spawn a real engine); revisit when a stub-only chatgpt walk is worth its maintenance.
- Full-suite flakiness under load on PUTER (a known base condition) is not this effort's to fix; the wave gate is the named terminal/rollup/doctor subset plus the import scan.
