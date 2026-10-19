#!/usr/bin/env bash
# Foreman gate wrapper — runs under git-bash so the per-wave glob expands
# (cmd.exe, which Foreman's spawnSync uses, does NOT expand globs). nullglob
# means a non-matching wave glob disappears instead of erroring pytest.
# Resolve our own directory with pure bash builtins (no external `dirname` —
# the orchestrator's spawn PATH may not include git's coreutils, so shelling
# out to `dirname` made the gate non-hermetic and crashed it on PATH-strip).
_self="${BASH_SOURCE[0]:-$0}"
_dir="${_self%/*}"
if [ "$_dir" != "$_self" ] && [ -n "$_dir" ]; then
  cd "$_dir" || exit 2
fi
shopt -s nullglob
# Neuter the auto-loaded `langsmith` pytest plugin: it instruments the session
# and FLUSHES traces over the network at sessionfinish, which blocks interpreter
# shutdown ~20s AFTER pytest already printed "N passed" — pushing the gate past
# the orchestrator's 120s wall timeout (killed → exit_code null → not green) even
# though every test passed. No test in this suite uses langsmith, so disabling
# the plugin (and its tracing) is a pure no-op for coverage. Belt-and-suspenders:
# `-p no:langsmith_plugin` stops the plugin loading; the env vars stop any flush.
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
exec python -m pytest -v -p no:langsmith_plugin \
  tests/test_zombie_hunter.py tests/test_swarm_zombie_coverage.py tests/test_cancel_liveness.py \
  tests/test_session_registry.py tests/test_history.py tests/test_session_continue.py \
  tests/test_effort_view_v12.py tests/test_context_handoff_v12.py tests/test_deliverables.py \
  tests/test_build_deliverable.py tests/test_engine_persist.py tests/test_engine_selector.py \
  tests/test_lanes_concurrency.py tests/test_terminal_session.py tests/test_terminal_seed.py \
  tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py tests/test_worktrees.py \
  tests/test_parity_recovery_w14.py \
  tests/test_*_w[0-9].py \
  --deselect tests/test_session_continue.py::test_historical_panel_shows_summary_and_continue_works \
  --deselect tests/test_build_deliverable.py::test_build_deliverable_in_lane_and_panel_playwright
