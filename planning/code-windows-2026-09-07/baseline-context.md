# Baseline context (brownfield, Anchor @ v1.2.15, 2026-09-07)

## Tooling on this machine (inventory 2026-09-07)
- JupyterLab (`jupyter-lab`), `jupyter_server`, `nbformat`, `nbconvert`, `ipykernel`; kernels
  `python3` and `ir` (R) — `jupyter kernelspec list`.
- VS Code at `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` with the `code` CLI on PATH.
- Python stdlib-only rule for product code: JupyterLab and VS Code are EXTERNAL processes launched by
  argv (like `git`/`gh`), never imported; `nbformat` is not importable by product code either — a
  one-cell notebook is a small JSON document (nbformat 4) written by stdlib `json`.

## Seams to reuse (control paths, not names — journal 0098)
- **Managed local servers:** `preview_server.py` — `pick_free_port()` (never 8777), `previews.json`
  registry under `.anchor/`, `_spawn_preview`, `list/stop/reap_orphans`; SAFE projections (no absolute
  paths); the health check walks it stubbed. A JupyterLab server is the same shape:
  `jupyter-lab --no-browser --port <p> --ServerApp.token=<t> --ServerApp.root_dir=<project>` (+ `--ip
  127.0.0.1`); its URL is `http://127.0.0.1:<p>/lab/tree/<rel>?token=<t>`.
- **Type-aware launch:** `deliverables.infer_type` / `launch_deliverable` (doc / script / skill /
  program / tool / service); a `notebook` and an `editor` outcome belong beside them.
- **The register and its renderers (v1.2.13):** `steward_campaign.read_deliverables` + `classify_route`
  (contained routes; `run:` marker); `shared.js delivRow` / `stepDelivLine`; `cockpit.html loadDeliv`;
  the files tile (`cockpit.html loadFiles`, `shared.js renderFiles`) — rows are links by extension;
  `.ipynb` today opens as raw JSON through deliverable-file.
- **The Run link (wave 3):** `POST /api/rnd/run_deliverable_terminal` allowlists a command against the
  register and stages it in a shell session — the pattern for "a control that starts a process from a
  register row, token-gated, never auto-run".
- **Where cells:** file rows contained to the effort; routes `/report/…` and `/artifact/…`; anything
  else is text (journal 0110: a JupyterLab/Shiny URL is unreachable from the register).

## Tests that pin today's truth
- `tests/test_reports_links_2026_09_05.py` (22), `tests/test_steward_deliverables.py`,
  `tests/test_files_tile_2026_09_05.py`, the preview_server tests (`tests/test_*preview*`), the
  healthcheck v3/v4 stubbed walks (preview guard ≠ 8777).
- Gate for the build: `python -m pytest tests/test_code_windows_2026_09_07.py tests/test_steward_deliverables.py tests/test_reports_links_2026_09_05.py -p no:cacheprovider`
  (no -q — the engine reads the counts). Wave 1 extends the seed file.

## Constraints
- Stdlib only; external tools by argv; nothing bound on 8777; no auto-execution of cells; a `.py` is
  converted to a notebook at most once and never over an existing `.ipynb`.
- The live service serves the working tree; restart via `POST /api/restart` when a build lands.
