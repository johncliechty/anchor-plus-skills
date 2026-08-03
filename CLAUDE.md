# Anchor — collaborator install (agent notes)

This is a data-free Anchor distribution. Read this before exploring.

## Debugging an install: cheap checks FIRST
1. `python doctor.py` — deterministic install health (missing modules,
   pywinpty, engine CLIs, token, server). No model calls, free.
2. Tail `logs/errors.log` INSIDE THIS PACKAGE FOLDER (the package dir is the
   default data dir) — boot problems land there.
3. Only then read code, and read it NARROWLY.

## Reading rules (token discipline)
- Do NOT read `anchor_gui.py` end-to-end (18,000+ lines) — grep for the
  symbol you need and read that region only.
- Do NOT crawl `vendor/bundled-skills/` — those are 13 packaged skills, not
  app code.
- Do NOT bulk-scan `starter/`, `static/`, or `vendor/` trees.

## Paid tools are not debug tools
researchPrime / Crucible / Foreman / Gandalf are intentional MULTI-AGENT
skills: one invocation fans out many model calls against the user's paid
subscription. Never invoke them to diagnose an install problem.

## Running Anchor
- Start: `python launch_anchor_dashboard.py` (starts the server if needed,
  then opens the dashboard). After a reboot, run it again.
- The server is `anchor_gui.py` (Python stdlib only; optional `pywinpty` for
  real terminals). Default port 8777, loopback only.
- The API token lives OUTSIDE this tree (default
  `~/.anchor/.anchor/onboard-token`); the launcher wires it automatically.
