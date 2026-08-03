# Anchor — per-project R&D control surface

Anchor turns a task/project tracker into a per-project **R&D control surface**:
each code project is a folder, and a single dashboard drives the
**researchPrime → Crucible → Foreman** trio as durable, server-owned jobs with
versioned effort history, task↔project integration, and deliverable execution.

This is a **clean, data-free distribution** — it ships only the product code and
dependency-free assets. There is no personal task/project data, no R&D registry,
and no `.anchor/` store in this export; you start from an empty state.

## Requirements
- Python 3.8+ (the shipped product is **Python standard library only** — with
  ONE optional, isolated exception: the v3 ConPTY terminal subsystem can use the
  native `pywinpty` package).
- **Optional terminal extra (`pywinpty`):** real in-browser ConPTY terminals
  (`pty_manager.py`) need `pywinpty` (`pip install .[terminal]`, Windows only).
  It is imported LAZILY and ONLY by the terminal subsystem — if absent, the
  terminal feature reports "real terminal unavailable" and the rest of Anchor is
  unaffected. The core import path stays stdlib-only.
- Optional system tools, invoked as subprocesses when present: `claude`
  (Claude Code), `git`, `latexmk` (for PDF reports).

## Run
```
python anchor_gui.py --no-browser      # local web server (default :8777)
```
Then open the dashboard in your browser.

## Develop / test
`pytest` is a dev-only dependency (not shipped at runtime):
```
pip install -e ".[dev]"
python -m pytest -v
```

## Layout
- `anchor_gui.py` — the dashboard server (main interface).
- `anchor.py` — CLI engine.
- `paths.py`, `rnd_registry.py`, `job_runner.py`, `gate_adapter.py`,
  `lanes.py`, `effort_history.py`, `report_viewer.py`, `dir_browser.py`,
  `anchor_healthcheck.py` — supporting modules.
- `vendor/katex/` — vendored KaTeX (math rendering for the report viewer).
- `dist_manifest.txt` — the deny-by-default shippable-file manifest.

## License
See `LICENSE` if present, otherwise all rights reserved by the author.
