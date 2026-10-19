# Friction — Python and R must open as a live Jupyter notebook from every cockpit surface

`date`: 2026-09-07
`surface`: Anchor AI cockpit (steward_cockpit): the deliverables register tile, the plan's per-step links, and the artifact route
`reported by`: John, in the Econ 588 Student Summaries campaign, reading from an iPad over the tailnet
`outcome`: fixed on the steward's side the same day with in-effort launch pages; a cockpit-side mechanism is proposed below so the workaround is not needed forever

## What happened

The campaign ships, per week, a Python Jupyter notebook and an R Markdown walkthrough. From the week's links page (Markdown rendered by the Reader) the Python and R links opened JupyterLab on the home computer and ran there. The same items in the deliverables register and under the plan step "just died or opened something that is not a Jupyter notebook". John's words: "Can you make that consistent so that when the python or r get opened, they are opened in a Jupiter notebook and have it so that the R engine and the python engine are running back on the computer so that the execution happens there and the results get reflected in the webpage."

## Why the surfaces differed

`read_deliverables` opens exactly two kinds of Where cell: an in-effort file, or a contained route (`/report/…`, `/artifact/…`). An external URL, even one on the tailnet, is text. The links page had no such limit. So the register rows pointed at the read-only HTML renders of the notebooks, which are not notebooks and, served at 1.4 MB under `Content-Security-Policy: sandbox …`, did not reliably open on the iPad.

## The standing requirement (John, 2026-09-07)

Python and R code in a campaign runs in a Jupyter notebook on the home computer that runs the Anchor service, reached over Tailscale; the reader's browser is only a view. Every place the cockpit shows a Python or R item must open that live notebook. Read-only renders are fallbacks, never the target.

## Steward-side fix, done today

Each week carries `notebooks/RUN-<week>-python.html` and `RUN-<week>-R.html` inside the effort: a meta refresh to the JupyterLab deep link (`https://gwl-server.tailb49f65.ts.net:8446/lab/tree/<path>.ipynb?token=…`), the same link visible as a fallback (`target=_blank`, allowed by the route's `allow-popups`), and one line saying what runs where. The register rows point at those pages through the artifact route, so the plan's step links follow. Verified with headless Edge through the real route: the DOM title after the redirect was "week02-python… - JupyterLab". Pattern recorded in the steward skill (journal 0110, SKILL.md standing rules) and the campaign (journal 0025).

## Proposed cockpit mechanism (for the cockpit owner to size)

1. **Let a Where cell name a tailnet service.** Extend `read_deliverables` / `classify_route` with a third openable form: an `https://` URL whose host ends in the machine's own tailnet suffix (read from `tailscale status --json`, never hard-coded). Anything else stays text, as now. The row renders as an ordinary new-tab link, so live notebooks and Shiny apps need no launch page.
2. **A `/notebook/<pid>?path=<rel>` route** that redirects to the JupyterLab deep link for an in-effort `.ipynb`, adding the token server-side from the same place `jupyter-serve` writes it. Then a register row can simply name `weeks/week-02/notebooks/week02-python.ipynb` and the cockpit does the rest, and the token never sits in a Markdown file.
3. **Health, not hope.** The state line already reads `attention.json`. A `services` list there (name, local port, tailnet URL) lets the cockpit show a red dot when a notebook server or explorer is down, instead of a link that "dies".
4. **Start at logon.** The notebook server and explorers are hand-started today and do not survive a reboot. A per-project `services.json` the Anchor host starts at logon (or a Task Scheduler entry the steward may register with John's yes) closes the last gap.

## Acceptance (what John sees)

From the iPad, in the register or under the plan step, he taps "Week 2 in Python" and the live notebook opens in JupyterLab; Shift+Enter runs a cell on the home computer and the output appears. The same for R. If the server is down, the cockpit says so before he taps.
