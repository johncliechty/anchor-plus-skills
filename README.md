# Anchor — per-project R&D control surface

Anchor turns a task/project tracker into a per-project **R&D control surface**:
each code project is a folder, and a single dashboard drives the
**researchPrime → Crucible → Foreman** trio as durable, server-owned jobs with
versioned effort history, task↔project integration, and deliverable execution.

This is a **clean, data-free distribution** — it ships only the product code and
dependency-free assets. There is no personal task/project data, no R&D registry,
and no `.anchor/` store in this export; you start from an empty state.

## Requirements
- Python 3.8+ for the core dashboard; use a current supported Python installation.
  The core import path uses the Python standard library.
- **Optional terminal extra (`pywinpty`):** real in-browser ConPTY terminals
  (`pty_manager.py`) need `pywinpty` (`pip install .[terminal]`, Windows only).
  It is imported LAZILY and ONLY by the terminal subsystem — if absent, the
  terminal feature reports "real terminal unavailable" and the rest of Anchor is
  unaffected. The core import path stays stdlib-only.
- For AI features, install and sign in to your selected subscription CLI:
  Claude Code, ChatGPT Codex, or Grok Build. Choose coding and review families
  in Settings. Model and effort selection follow the installed CLI's current
  capabilities. Git and Node.js are needed by the project and skill engines.
- Optional notebooks use a separate Jupyter/Python environment on the Anchor
  host. R notebooks also require R and IRkernel. These are one-time setup
  dependencies; opening a notebook never installs software.

## Install and run
Start with the [collaborator installation guide](USER-ONBOARD.md). On Windows,
run `onboard.cmd` from the downloaded package to configure the local install,
then start Anchor with its authenticated launcher:

```
python launch_anchor_dashboard.py
```
The launcher opens the dashboard in your browser. Keep your project folders
and their backups separate from replaceable notebook software.

**Optional Windows notebook-host setup is under repair in this release. Skip it
for now; the Anchor dashboard and bundled skills can be installed independently.**

Notebook documentation: [host setup](docs/notebook-host-setup.md), then
[notebook work products](docs/notebook-work-products.md). The Windows notebook
installer defaults to `C:/ProgramData/AnchorNotebook` for software and asks for
the existing folder containing your notebooks. This optional setup requires
administrator confirmation and a password entered locally. Enable notebook
links only after authenticated Python/R acceptance on your host.

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
