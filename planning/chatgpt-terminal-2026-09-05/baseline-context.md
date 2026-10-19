# Baseline context (brownfield, Anchor @ be968fa, 2026-09-05)

## The code that closes the seat today
- `terminal_session.py`
  - `_check_engine_allowed(lane, backend)` (~388-408): raises `chatgpt-gated-bridge-pending` for
    `BACKEND_CHATGPT` — THE gate. Called from `start_session` (~675) and `switch_engine` (~1506).
  - `_resolve_engine_cmd(engine)` (~486-528): already resolves `codex` (PATH, `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`, `~/.codex/bin/codex.exe`); no binary → `chatgpt-terminal-binary-missing` (keep).
  - `_engine_launch_argv(cmd, backend, engine_uuid)` (~553-580): claude gets `--session-id <uuid>`, grok `-s <uuid>`; add the chatgpt argv (`--cd <worktree>`, `--no-alt-screen`, `-s workspace-write`; NO session pin exists — Option C).
  - `start_session` (~583-870): worktree, PTY launch, registry record, the ONE seed write (`seeded=True`, ~849-869); `switch_engine` (~1456-1640): reap + relaunch in the same worktree, re-seed once.
  - `DOCTOR_READONLY_CLI_ARGS` (~950): claude `--permission-mode plan`, gemini `--approval-mode plan`; add chatgpt `-s read-only`.
  - `_LIVE_ENGINE_BASENAMES` (~452) already includes `codex` (the test guard); `ENGINE_CMD_ENV=ANCHOR_ENGINE_CMD` is the stub seam.
  - Honest Telemetry: `uncorrelated` usage state when no pin (~540, ~811); Option C stamping `partial (<engine> segment unmeasured)` (~835-840).
- `session_registry.py`: `BACKEND_CHATGPT = "chatgpt"`, `VALID_BACKENDS` includes it (187-189).
- `anchor_settings.py`: `VALID_DEFAULT_CLIS = {claude, gemini, grok}` + the "bridge pending" comment (26-33); `save_settings` validates per key (~198-210). `VALID_REVIEW_FAMILIES` already includes chatgpt (be968fa).
- `anchor_gui.py`: `model_role_capabilities` (~5822-5860) — the terminal branch sets `selectable=False`, `status="bridge_pending"`; option-label maps (~5918-5921 Python, ~6008-6013 JS); capability note text (~5943, ~6047). `lanes.py` `check_engine_allowed` (Gemini research-only policy) — confirm chatgpt is allowed on every lane.
- `pty_manager.py`: ConPTY spawn (real) | stub backend (`ANCHOR_PTY_BACKEND=stub`).

## Tests that pin the old truth (rewrite in the same wave)
- `tests/test_backend_chatgpt.py`: terminal `bridge_pending` / `selectable False`, "ChatGPT &mdash; terminal bridge pending" label count, disabled-option count, the browser test (`#mpDefaultCli option[value=chatgpt]` disabled).
- `tests/test_chatgpt_lane_routing.py`: bridge-pending expectations.
- `tests/test_anchor_settings.py`: `save_settings(default_cli="chatgpt")` raises; `VALID_DEFAULT_CLIS` set equality.
- Terminal nets: `tests/test_terminal_*.py`, `tests/test_model_switch_w7.py` (engine switch), `tests/test_resume_*.py` — all under the stub PTY + `ANCHOR_ENGINE_CMD` stub (`tests/conftest.py`).

## Codex CLI facts (v0.151, probed 2026-09-05)
- Interactive: `codex [OPTIONS] [PROMPT]`; `-C/--cd <DIR>`; `-s/--sandbox read-only|workspace-write|danger-full-access`;
  `-a/--ask-for-approval on-request|never`; `-m <MODEL>`; `--no-alt-screen` (inline TUI, keeps scrollback);
  `resume [SESSION_ID] [PROMPT]` / `--last`; `fork`; `queue`. No flag pins a session id at launch.
- Non-interactive `codex exec --json` (the trio driver) is a different surface; not this effort.

## Constraints
- Python stdlib only (the one declared exception is pywinpty); `distro.py` import scan must stay clean.
- No real engine spawn under test (`ANCHOR_TESTS_ALLOW_LIVE` guard); hermetic tests via the stub PTY + `ANCHOR_ENGINE_CMD`.
- The live service serves from the working tree: no restart until the build is done; the ship (v1.2.12) follows via the pipeline (`_build_clean_ship.py`, `tools/share_sandbox.py`, `tools/pull_dry_run.py`, nets, tag, `tools/publish_share_repo.py`, clone verify).
- Gate command for the build: `python -m pytest tests/test_backend_chatgpt.py tests/test_anchor_settings.py tests/test_chatgpt_lane_routing.py tests/test_chatgpt_terminal_2026_09_05.py tests/test_model_switch_w7.py -q -p no:cacheprovider` — wave 1 MUST create `tests/test_chatgpt_terminal_2026_09_05.py`.
