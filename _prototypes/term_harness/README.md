# Anchor Terminal Harness — ConPTY × WebSocket × xterm.js

A standalone proof-test for running a **real interactive Claude Code / Gemini / PowerShell
session in a browser terminal**, the way the project-window terminals should work. It does
**not** touch the live `:8777` service (pinned to port **8799**, loopback only).

## Run it
```
python -u _prototypes/term_harness/term_test_server.py
# then open http://localhost:8799
```

A Claude Code window opens automatically. The top bar launches more:
- **Claude Code → Raw / Embedded / Console** — the same proven bridge, three *looks*:
  - **Raw** — full xterm.js, behaves exactly like your desktop terminal.
  - **Embedded** — xterm.js with the Anchor tile header (status light · session · doc links) — how it looks inside a project window.
  - **Console** — ANSI stripped, clean transcript + a message box (no cursor/escape noise).
- **+ PowerShell** (control) and **+ Gemini**.

Windows are draggable / resizable / minimizable / killable — a live preview of the
"multiple sessions open at once" UX.

## What it proves (all verified headlessly)
- `pty_smoke.py` — spawns PowerShell, `claude --version`, and `claude -p "…"` in a real
  ConPTY. Result: PowerShell echoes + runs; `claude --version` → `2.1.175 (Claude Code)`;
  `claude -p` runs a **real model turn** under ConPTY and returns its answer, then exits.
- `ws_client_test.py` — a stdlib WebSocket client that connects to `/ws`, gets the 101
  upgrade, reads the PTY banner, sends `echo WS_BRIDGE_OK`, and reads it echoed back.
  Result: **PASS**.

## Why the live terminal felt "weird" (root cause)
Two different terminal substrates are half-wired into the same window:
- the **v2 stream-json REPL** (`rnd_terminal.py`, the console drawer) re-seeds a skill prompt
  each turn → the repeated *"this is the beginning of planning session…"*;
- the **v3 bare ConPTY** (`terminal_session.py` → `term_start`) launches bare `claude` with
  no opening turn, so you land on an empty REPL.

The fix the mockups propose: **one** substrate (raw ConPTY, proven here) + a launch dialog
that picks the engine and sends your task description as the **single opening turn** — then
it behaves like a normal Claude Code session. No re-prompt loop.

## Files
- `term_test_server.py` — the bridge server (stdlib + pywinpty).
- `pty_smoke.py` — headless ConPTY substrate test.
- `ws_client_test.py` — headless end-to-end WebSocket bridge test.
