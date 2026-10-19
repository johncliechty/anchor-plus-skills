# Anchor: code opens where it runs — notebooks in the project's JupyterLab, short code as a notebook, long code in the editor, live links from the register — Description

**North Star:** # North Star — code opens where it runs (John, 2026-09-07)

> "the jupyter notebooks need to come up every time python or R code is called (at least if the code is
> descriptive/shorter) longer bits of code can have a GUI that runs in a window ... a bit like running in
> something like VS Code"

**Statement.** When Anchor produces or lists Python or R code, one click opens it where it runs: short code
as a Jupyter notebook in the project's own JupyterLab (Python and R kernels), longer code in an editor
window, and notebooks always in JupyterLab — and every such thing is a clickable row in the plan, the
deliverables and the files, like every other report.

## Success criteria (the SURFACE)

1. **A project's own JupyterLab, managed like a preview:** started on demand for a project (cwd = the
   project folder), on an OS-assigned free port that is never 8777, with its own token, registered,
   listed, stoppable, and reaped when dead — the same discipline `preview_server` already has.
2. **A notebook row opens in JupyterLab:** a `.ipynb` in the register, under its step in the plan, or in
   the files tile opens in a new window at the lab's `/lab/tree/<rel>` for that file (starting the lab
   if needed); a stale or dead lab is restarted, never a blank page.
3. **Code rows open where they run:** a `.py` or `.R` row that is short (≤ 120 lines) or marked as a
   notebook (`# %%` cells, or `# notebook` in its first lines) is converted once to a sibling one-cell
   `.ipynb` (nbformat; kernel `python3` or `ir`) and opened in JupyterLab; longer code opens in the
   editor (VS Code on this machine, `code -r <file>`), and the row says which ("notebook" / "editor").
4. **Live links from the register:** a Where cell that is a `http://localhost:<port>/…`,
   `http://127.0.0.1:<port>/…` or `http://<this machine's tailnet name>/…` URL renders as a link
   (new window); every other host stays text (the 2026-09-07 journal 0110 gap — a JupyterLab or Shiny
   address reachable from the register and the plan without a launch page).
5. **Seen on the page before it ships:** on a real project, a `.ipynb` row opens the lab with the file
   selected, a short `.py` opens as a notebook, a long `.py` opens in the editor, and a live-link row
   opens (Playwright screenshots), then the release pipeline.

## Non-goals (parked, named)

- Browser-hosted VS Code (code-server) or remote (iPad) editing — the editor is the local VS Code.
- Running Python or R inside the dashboard's origin; the lab is its own origin on its own port.
- Roar / cluster execution; Shiny app management (a Shiny URL is a live-link row, nothing more).
- Notebook *execution* on open (the user runs cells); nbconvert renders as a fallback are not built.

## Risk taxonomy

- A lab bound on 8777 → hard-guarded `pick_free_port` (existing).
- A lab left running forever → reap-on-dead + a stop control (existing preview discipline).
- A `.py` converted twice or converted over a hand-edited notebook → convert once; never overwrite an
  existing `.ipynb` (open the existing one).
- A live-link row pointing at a hostile host → only localhost / 127.0.0.1 / this machine's tailnet name.

## Foresight brief

The `run:` shell terminal (v1.2.13) and this are the two halves of "a deliverable runs in an Anchor
window": commands in a shell, code in a notebook or editor. The register row is the one place both hang
off; the plan and the files inherit it.


A per-project JupyterLab managed like a preview; .ipynb rows open in it; short .py/.R rows convert once to a notebook and open there, long ones open in VS Code; localhost/tailnet URLs in the register are links; seen on the page before shipping.

## Success criteria
- A project's own JupyterLab is managed like a preview: started on demand (cwd = the project folder) on an OS-assigned free port that is never 8777, with its own token, registered, listed, stoppable, reaped when dead (the preview_server discipline)
- A .ipynb row (register, plan outline, files tile) opens in a new window at the lab's /lab/tree/<rel> for that file, starting or restarting the lab if needed — never a blank page
- A .py or .R row that is short (<= 120 lines) or marked as a notebook (# %% cells or "# notebook" in its first lines) is converted ONCE to a sibling one-cell .ipynb (nbformat 4 JSON written with stdlib; kernel python3 or ir) and opened in JupyterLab; longer code opens in the local editor (code -r <file>); the row says which (notebook / editor); an existing .ipynb is never overwritten
- A Where cell that is a http://localhost:<port>/…, http://127.0.0.1:<port>/… or http://<this machine's tailnet name>/… URL renders as a link opening in a new window; every other host stays text
- Seen on the page before it ships: on a real project a .ipynb row opens the lab with the file selected, a short .py opens as a notebook, a long .py opens in the editor, a live-link row opens (Playwright screenshots); nets green; then the release pipeline

## Provenance

Generated by Crucible Stage 2 from an approved Master Plan, vetted by the Shark-Tank loop and the well-formedness gate before handoff.
