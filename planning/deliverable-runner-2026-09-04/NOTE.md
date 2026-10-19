# Running software deliverables from Anchor — design note (2026-09-04)

**The ask (John, 2026-09-04).** When Anchor produces a software deliverable, run it from the
browser — on puter (the Anchor host) first, the Penn State Roar cluster second — including
deliverables with a GUI that needs interaction, "like a type of dumb terminal" inside a web page.

## What already exists on puter

- Anchor serves the cockpit and every page over one token-authed HTTP server (:8777, reachable
  from any device through Tailscale Serve). Sessions and commissioned runs already live
  server-side and survive the browser closing.
- The steward cockpit already has managed terminals (a PTY per campaign; `steward-terms.json`),
  so a text program can already be driven from a page.
- Deliverables are registered in `DELIVERABLES.md` and open through the contained
  `deliverable-file` route (documents, Office, PDF, Markdown).

## Three kinds of deliverable, three runners (recommendation)

1. **Command-line or text-UI program → a browser terminal.** An xterm.js pane in the cockpit
   bound to a PTY on puter (the same mechanism the steward terminals use), started from a
   "Run" button on the deliverable's row with its declared command. Output streams live;
   input goes back; the process outlives the tab. Cheapest and covers most research code.
2. **A program with its own web UI → an app slot.** The deliverable contract says "web-first":
   a GUI deliverable is a small local web app. Anchor starts it on a free localhost port and
   reverse-proxies it under `/apps/<id>/` inside an iframe on the deliverable page, with the
   token gate in front. Streamlit, Dash, Flask, a static page — all fit. No new auth surface.
3. **A native desktop GUI (tkinter, Qt, matplotlib windows) → a remote display in the page.**
   Run it inside a virtual display on puter with noVNC or xpra's HTML5 client in the iframe.
   This is the true "dumb terminal": pixels in, mouse and keys out. Heavier, so it is the
   fallback the contract steers away from, not the default.

**The contract that makes it work:** a deliverable that is software declares in its register
row how it runs — `run: <command>` plus `ui: terminal | web:<port> | desktop` — and the
steward's build laws prefer `web` over `desktop`. Anchor renders the right runner from that
declaration; nothing is guessed.

## Roar (second target)

Roar exposes Open OnDemand (a web portal with a shell, file browser, Jupyter and noVNC
desktops) plus SSH. The same three runners map onto it: Anchor submits through SSH (a job
script per deliverable, files synced with rsync), and the deliverable page links the Open
OnDemand session for interaction. Keep puter as the interactive default; Roar is for what
needs the cluster.

## What it costs / the one thing that gets worse

A running program inside the page is a process on puter that anyone with the page token can
start. The runner therefore stays token-gated, runs under a per-deliverable working dir, has
a kill button and a wall-clock cap, and is logged like a commissioned run. Nothing else in
Anchor changes shape.

## Next step

Plan it as its own effort (Crucible LITE: terminal runner + app slot first; desktop and
Roar as follow-on waves) on John's word. Nothing here is built yet.
