# Independent review (Fable) — the ChatGPT Terminal effort, before anything is built

**Asked by John, 2026-09-05:** "I want this to be elegant and not overbuilt … do an independent
review of the plan and effort and journal about what Crucible and Foreman are doing. Then
potentially modify the plan (with an adversarial review) … put out the rabbit catcher."

**Yardstick:** ELEGANCE.md Part II — the largest result carried by the least machinery John can
hold; every element forced by an INDEPENDENT citable need; malleability work (tests, seams) is
never cut as "unused"; guards judged by RC-G. Verdicts: KEEP / HOLD (with a written trigger) / CUT.

## 1. What the change actually is (read from the code, not from the plan)

The Terminal seat is closed by exactly one guard and two truth tables. The engine-command
resolver for Codex already exists; the registry already knows the backend; the seed path, the
engine switch, the worktree isolation and the stub-PTY test seam are backend-agnostic.

| # | Edit | File:line | Forced by (independent record) |
|---|---|---|---|
| 1 | Delete the `chatgpt` raise in `_check_engine_allowed` | terminal_session.py ~398-403 | John's request (the seat) |
| 2 | Widen `VALID_DEFAULT_CLIS` to `VALID_CLIS`; retire the "bridge pending" comment | anchor_settings.py 26-33 | John's request; the comment says "widen when the bridge lands" |
| 3 | Terminal/chatgpt capability: `selectable True`, status `ready`; drop the "bridge pending" labels/note (Python + JS) | anchor_gui.py ~5838-5845, ~5918-5921, ~5943, ~6008-6013, ~6047 | John's request; the truth-table law (server and browser tell the same truth, v1.2.8) |
| 4 | `_engine_launch_argv`: chatgpt branch returns `[cmd]` — no session pin exists | terminal_session.py ~553-580 | a datum: Codex has no launch-time session-id flag (probed 2026-09-05) |
| 5 | Doctor read-only posture: `DOCTOR_READONLY_CLI_ARGS[BACKEND_CHATGPT] = ('-s', 'read-only')` | terminal_session.py ~950 | the existing Doctor invariant (2026-07, "can never mutate") now reachable on a chatgpt default_cli |
| 6 | Honest accounting: the existing unmeasured-segment stamp fires for chatgpt as it does for gemini (wording "engine segment unmeasured") | terminal_session.py ~835-843 | Honest Telemetry W5 (RULED Option C) — same lie otherwise: a chatgpt→claude switch would read complete |
| 7 | Rewrite every test that pins "bridge pending"; extend `tests/test_chatgpt_terminal_2026_09_05.py` with the stub-PTY proofs (start on chatgpt → backend recorded, seed written once, argv = [cmd]; switch to/from chatgpt → no orphan; capability matrix ready; live-spawn guard still refuses `codex` under pytest) | tests/test_backend_chatgpt.py, test_anchor_settings.py, test_chatgpt_lane_routing.py, the new file | malleability work — never cut; John's "nothing regresses" |
| 8 | The proof on his screen: a ChatGPT terminal opened from the dashboard, greet visible (Playwright screenshot, done by me, not a suite test) | scratchpad script | THE VERIFICATION LAW (ELEGANCE rules 6-9, John 2026-08-15) |

That is the whole change: on the order of 60 lines of product code plus test edits.

**A datum found after the first draft (probed 2026-09-05):** John's `~/.codex/config.toml` sets
`approval_policy = "never"` and `sandbox_mode = "danger-full-access"` globally (Windows sandbox
`unelevated`). A bare `codex` argv therefore inherits his own no-approvals, full-access posture — the
same posture he gets in his own shell, so the cockpit terminal adds no new exposure; it also makes
edit 5 (the Doctor's `-s read-only` override) load-bearing rather than cosmetic. Edit 4 turns out to
be a no-op: `_engine_launch_argv` already returns `[cmd]` for a backend without a pin.

## 2. The Rabbit-Catcher over Crucible's seven elements (Stage-1 triage, all "integrate")

| Crucible element | RC-1 need | RC-2 delete-and-check | Verdict |
|---|---|---|---|
| Open the gate in one place (guard + VALID_DEFAULT_CLIS + capability ready) | John's request | the seat stays closed | **KEEP** (= edits 1-3) |
| A per-backend `ENGINE_LAUNCH_ARGS` table applied after `_engine_launch_argv` | none independent — one backend, one branch suffices; the table's only beneficiary is itself | nothing breaks | **CUT** — a 3-line branch in the existing function (edit 4) |
| `--no-alt-screen` + `-s workspace-write` at launch | no datum: nobody has seen the Codex TUI misrender in xterm.js, and the interactive default sandbox already asks John for approvals in the terminal | if the render IS broken, the terminal is unusable | **HOLD** — trigger: the on-screen proof (edit 8) shows a broken render or a refused write; then add the flag that fixes what was seen |
| Seed timing "gate the write on first PTY output" | none — the code writes the seed right after launch for every backend today (start_session ~849); my own risk table asserted the Grok path differs, and it does not | nothing breaks today | **CUT** — trigger to re-open: the greet never arrives on screen |
| Generalize `usage_gemini_segment` into `usage_unmeasured_segments: [...]` | the honesty need is real (Option C) but the new schema's only beneficiary is the generalization | with the existing flag extended to chatgpt (edit 6) nothing is lost | **CUT the schema, KEEP the stamp** (edit 6) |
| A Playwright sign-off wave with an `importorskip` + `ANCHOR_TESTS_ALLOW_LIVE=1` test | the verification law wants the render SEEN — by me, now; a live-spawning test in the suite is the class of hazard that once leaked 8,816 sessions | losing the WAVE loses nothing; losing the PROOF breaks rule 6 | **CUT the wave, KEEP the proof** (edit 8, by hand) |
| A regression-net wave (codex still refused under pytest; distro scan) | malleability — tests are exempt from YAGNI | none | **KEEP as two assertions inside edit 7, not a wave** |


### 2b. Crucible's Grok Shark round on the seven elements (dry: 0 two-Shark blockers, 15 single-reviewer findings) — disposition against the CUT plan

- "default_cli not consumed at term_start" — already false: `handle_term_start` (anchor_gui.py ~14790) takes `body.backend or _aset.get_default_cli()`. No edit.
- "picker ready without a Codex probe" — already false: `present` in `model_role_capabilities` comes from `detect_host_profile` → `_chatgpt_available`; "ready" is only offered when the binary is detected. No edit.
- "Doctor reuse key omits backend" — already false: `live_doctor_session(mode, backend, posture)` matches `backend` exactly (~1042-1070). No edit.
- "uncorrelated vs partial accounting" — answered by edit 6: a Codex session classifies exactly as a Gemini one (RULED Option C), with the label made engine-neutral.
- "seed on first byte / timeout into an approval prompt" — the seed-timing element is on HOLD with the on-screen proof as the trigger; John's Codex config has approvals off, so no prompt can swallow the seed on his host.
- "live greet oracle is Codex chrome, not the lane seed" — taken: the proof asserts the LANE greet text on the page, not the Codex banner.
- "screenshot-exists ship gate" — the proof is a step I perform and look at (rule 6), not a file-exists gate.

## 3. The ceremony itself (RC-G: guards judged by what they catch)

- **Crucible (LITE, sharks on Grok):** ran for a change whose shape was fully known from a 20-minute
  read. Its value here is the Grok Shark round on the seven elements — the same adversarial pass
  I now run on the CUT plan. Verdict: the plan is the deliverable; its waves are not.
- **Foreman (5 waves):** for one wave of ~60 lines, the orchestrator's two products — an
  independent gate and a cross-family review — I run directly: the gate is the pytest command, the
  review is a Grok read of the diff (attested). The wave machinery, the checkpoints and the
  execute seat re-reading a 22k-line file for 15 minutes carry nothing here. Verdict: **CUT the
  orchestrator for this change; keep its two products.** Foreman remains the mechanism for multi-wave
  builds (the literature-review build was five real waves).
- **Time:** the earlier "hour or two" was the ceremony's time, not the change's. Expected now: build
  and tests ~20 min, Grok review ~8 min, proof on screen ~5 min, ship ~30 min.

## 4. The cut plan (one wave, the adversarial review below applies to THIS)

Edits 1-7 above, in one commit, gate = `python -m pytest tests/test_backend_chatgpt.py
tests/test_anchor_settings.py tests/test_chatgpt_lane_routing.py tests/test_chatgpt_terminal_2026_09_05.py
tests/test_model_switch_w7.py -q -p no:cacheprovider`; then edit 8 (the proof), then ship v1.2.12.
Parked with triggers: `--no-alt-screen` / sandbox flags (trigger: the proof), seed-timing (trigger:
no greet), the ChatGPT steward F1B, Doctor/Hunter certification, Codex usage correlation.

**What gets worse:** nothing the user can see; the one honest loss is that a Codex session's cost is
"unmeasured" in the rollup, as Gemini's already is.

## 5. Adversarial review of the cut plan

Grok (attested grok-4.6-build, 6.7 min, read-only in the repo): **"the cut is the right size for opening the
Terminal seat, and it is not overbuilt as a product change"** — with five things the cut had wrong or missing,
all folded before the build:

- **BLOCKER (taken):** `tests/test_chatgpt_lane_routing.py` is the job-layer / legacy-REPL fail-closed net — the
  parked F1B steward surface, not the ConPTY terminal. It is NOT rewritten; only the terminal pins in
  `test_backend_chatgpt.py` and `test_anchor_settings.py` change. (§1 row 7 corrected.)
- **MAJOR (taken):** Option C accounting must fire at `start_session` for chatgpt (ChatGPT→Claude switches were
  the uncovered case) and the badge title must stop saying "gemini" — done, one condition and one string;
  no schema.
- **MAJOR (taken as process):** `--no-alt-screen` stays on HOLD only because the ship WAITS on the on-screen
  proof; if the render is broken, the flag goes in at the three launch sites (start / switch / resume), never a table.
- **MAJOR (taken):** Doctor Diagnose fail-closes any backend missing from `DOCTOR_READONLY_CLI_ARGS`; the
  chatgpt entry is load-bearing against John's `danger-full-access` config — a stub-PTY assertion is in the gate
  file, and grok's refusal is asserted unchanged.
- **MAJOR (taken):** `tests/test_settings_api.py:104-105` would go red (and line 105 was already stale after
  this morning's reviewer change) — flipped in the same commit and added to the gate.
- **MINOR (taken):** two stale comments retitled; the release-note history left as history.
- Rabbit holes it confirmed closed: `--cd` (the PTY already starts in the worktree), `-s workspace-write` (his own
  shell posture), the argv table, the usage-schema array, a "chatgpt → [cmd]" branch that would be a comment.

## 6. Outcome (2026-09-05, same day)

- **Built as one wave** (commits aa7aa98, 23468ac, 2baeb03): the gate deleted, settings and truth tables
  widened, the Doctor fence, Option-C accounting, tests rewritten. Gate + terminal-session net: 326 green.
- **The on-screen proof produced three datums the stub could not** (each fixed with the smallest change, none
  with a table or a new schema):
  1. the browser attach "timeout" was my Playwright flow (the page keeps its token in localStorage) — not the seat;
  2. the Codex TUI opened on its own "Update available" menu and swallowed the stdin seed → launch with
     `-c check_for_update_on_startup=false`, and the lane seed rides Codex's positional PROMPT (the Gemini `-i`
     pattern) at start and switch;
  3. Codex asks its one-time per-repository trust question on a project's first ChatGPT terminal → left to the
     user (Enter = Yes; Anchor never auto-trusts); the seed survives it and the page then reads
     "✓ researchPrime loaded — what would you like to do?" with the worktree as cwd (`chatgpt_terminal_proof3.png`).
- **A latent defect found by the same proof:** three sites inferred "this engine pins a session id" from argv
  length; the Codex argv now carries flags and a prompt, so a chatgpt→claude switch lost its Option-C stamp.
  `_engine_pins_session(backend)` decides by backend now.
- **HOLDs closed by datum:** `--no-alt-screen` not needed (the TUI renders in xterm.js as is); `--cd` not needed
  (cwd is the worktree, read off the page); `-s workspace-write` not added (the user's own Codex posture).
- **Grok reviewed the diff too** (GROK-REVIEW-DIFF-2026-09-05.md: "with fixes" → the Doctor fence asserted on the
  spawn, the stale comments retired, and its three on-screen checks are exactly what the proof showed).
- **Time:** review + cut ~35 min, build + gate ~25 min, proof and its three fixes ~50 min, ship gate ~20 min.
  The five-wave Crucible/Foreman path would have spent that on ceremony before the first datum.
- **Crucible's Stage 2 for the record:** its Grok Sharks BLOCKED its own five-wave decomposition (3 blockers);
  the artifacts stay under stage1/, stage2/, handoff/ as the record of what the ceremony produced.
