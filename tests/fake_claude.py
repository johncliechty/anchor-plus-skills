#!/usr/bin/env python3
"""Deterministic mock runner for Anchor's job_runner (Wave 4).

This stands in for a live ``claude -p --input-format stream-json
--output-format stream-json`` invocation so the Foreman gate (pytest) NEVER
calls real ``claude`` and never incurs billing. It is wired in via the
``ANCHOR_RUNNER_CMD`` indirection: tests set
``ANCHOR_RUNNER_CMD=python <abs path>/tests/fake_claude.py`` (plus per-launch
extra args) and the job runner spawns this instead of ``claude``.

Behavior (all configurable via argv flags OR env vars so it can be driven both
ways). argv takes precedence over env.

  --lines N        / FAKE_CLAUDE_LINES   emit N stdout lines then continue.
  --sleep SECS     / FAKE_CLAUDE_SLEEP   sleep SECS *after* emitting lines
                                         (keeps the job "running" so it can be
                                         observed / cancelled).
  --line-interval SECS / FAKE_CLAUDE_LINE_INTERVAL
                                         sleep SECS *between* each content line,
                                         so stdout DRIPS over time (a long-poll /
                                         tail reader observes an advancing cursor
                                         while the job is still alive — rearch
                                         W15 restart-survival). Default 0.
  --spawn-child    / FAKE_CLAUDE_SPAWN_CHILD=1
                                         spawn a long-sleeping grandchild
                                         process before sleeping, so tree-kill
                                         (taskkill /T /F) can be exercised. The
                                         child's PID is written to the file
                                         given by --child-pid-file so the test
                                         can assert it was reaped.
  --child-pid-file PATH / FAKE_CLAUDE_CHILD_PID_FILE
                                         where to write the spawned child's PID.
  --exit-code C    / FAKE_CLAUDE_EXIT_CODE
                                         exit with code C (default 0).
  --result         / FAKE_CLAUDE_RESULT=1
                                         after the N content lines, emit one
                                         fake stream-json ``result`` envelope
                                         line carrying cost/usage/duration (for
                                         later waves; Wave 4 ignores it but the
                                         durable-line capture still works).
  --result-error   / FAKE_CLAUDE_RESULT_ERROR=1
                                         like --result but the envelope has
                                         ``is_error: true`` (subtype "error"),
                                         so a script/skill deliverable's
                                         result-no-error contract FAILS even on
                                         exit 0 (Wave 9). Implies --result.
  --gate           / FAKE_CLAUDE_GATE=1  emit ONE real stream-json
                                         ``AskUserQuestion`` tool_use frame
                                         (assistant message) AFTER the N content
                                         lines, so the gated-lane production wiring
                                         (reader_loop → gate_adapter) can be
                                         exercised end-to-end without a live CLI.
                                         The frame shape matches what real
                                         ``claude -p --output-format stream-json``
                                         emits for an AskUserQuestion gate.

Stdlib only. Self-contained. Lines are flushed immediately so a long-polling
reader can observe them as they arrive.
"""
import argparse
import json
import os
import sys
import time


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_flag(name):
    raw = os.environ.get(name)
    return bool(raw) and raw.strip() not in ("0", "", "false", "False")


def parse_args(argv):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--lines", type=int, default=None)
    p.add_argument("--sleep", type=float, default=None)
    p.add_argument("--line-interval", type=float, default=None)
    p.add_argument("--spawn-child", action="store_true")
    p.add_argument("--child-pid-file", default=None)
    p.add_argument("--exit-code", type=int, default=None)
    p.add_argument("--result", action="store_true")
    p.add_argument("--result-error", action="store_true")
    p.add_argument("--gate", action="store_true")
    # Tolerate any extra args the runner appends (e.g. a prompt seed) without
    # failing — a real runner would consume stdin / its own flags.
    args, _unknown = p.parse_known_args(argv)
    return args


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    a = parse_args(argv)

    lines = a.lines if a.lines is not None else _env_int("FAKE_CLAUDE_LINES", 3)
    sleep_s = a.sleep if a.sleep is not None else _env_float("FAKE_CLAUDE_SLEEP", 0.0)
    line_interval = (a.line_interval if a.line_interval is not None
                     else _env_float("FAKE_CLAUDE_LINE_INTERVAL", 0.0))
    spawn_child = a.spawn_child or _env_flag("FAKE_CLAUDE_SPAWN_CHILD")
    child_pid_file = a.child_pid_file or os.environ.get("FAKE_CLAUDE_CHILD_PID_FILE")
    exit_code = a.exit_code if a.exit_code is not None else _env_int("FAKE_CLAUDE_EXIT_CODE", 0)
    emit_result_error = a.result_error or _env_flag("FAKE_CLAUDE_RESULT_ERROR")
    emit_result = a.result or emit_result_error or _env_flag("FAKE_CLAUDE_RESULT")
    emit_gate = a.gate or _env_flag("FAKE_CLAUDE_GATE")

    # Emit N deterministic content lines (optionally dripped over time so a
    # tail reader sees an advancing cursor while the job is still alive).
    for i in range(lines):
        if line_interval > 0 and i > 0:
            time.sleep(line_interval)
        sys.stdout.write(f"fake-line {i}\n")
        sys.stdout.flush()

    # Optionally emit ONE real AskUserQuestion gate frame (assistant tool_use)
    # so the gated-lane production wiring can be exercised without a live CLI.
    # Shape matches real claude -p --output-format stream-json.
    if emit_gate:
        gate = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_fake_gate_0001",
                        "name": "AskUserQuestion",
                        "input": {
                            "questions": [
                                {
                                    "question": "Which output format?",
                                    "header": "Format",
                                    "multiSelect": False,
                                    "options": [
                                        {"label": "JSON files",
                                         "description": "Structured JSON"},
                                        {"label": "Markdown",
                                         "description": "Human-readable"},
                                    ],
                                }
                            ]
                        },
                    }
                ],
            },
        }
        sys.stdout.write(json.dumps(gate) + "\n")
        sys.stdout.flush()

    # Optionally spawn a long-sleeping grandchild so tree-kill can be proven.
    child = None
    if spawn_child:
        import subprocess
        # A python child that sleeps well past any test timeout.
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"]
        )
        if child_pid_file:
            try:
                with open(child_pid_file, "w", encoding="utf-8") as fh:
                    fh.write(str(child.pid))
            except OSError:
                pass
        sys.stdout.write(f"spawned-child {child.pid}\n")
        sys.stdout.flush()

    # Keep the job "running" so it can be observed / cancelled.
    if sleep_s > 0:
        time.sleep(sleep_s)

    # Optional fake stream-json result envelope (cost/usage/duration) for later
    # waves. Wave 4 only needs durable line capture.
    if emit_result:
        envelope = {
            "type": "result",
            "subtype": "error" if emit_result_error else "success",
            "is_error": bool(emit_result_error),
            "total_cost_usd": 0.0123,
            "duration_ms": 4567,
            "usage": {"input_tokens": 100, "output_tokens": 42},
            "session_id": "fake-session-0001",
        }
        sys.stdout.write(json.dumps(envelope) + "\n")
        sys.stdout.flush()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
