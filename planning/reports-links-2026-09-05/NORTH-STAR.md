# North Star — every report is a link, in the plan outline and in the deliverables register; a runnable deliverable opens in an Anchor window (2026-09-05)

**Statement.** When a skill produces a report or a plan for an effort — a Gandalf read, a
researchPrime plan or report, a Foreman execution log, a Crucible plan — it appears in the cockpit
as a **clickable link in two places at once**: under the roadmap step it belongs to in the plan
outline (so John opens the step and clicks), and in the effort's deliverables register (always).
A deliverable that is a piece of code John can run locally on puter carries a **Run link** that
opens it inside an Anchor window (a cockpit terminal in the project's tree with the command staged,
Enter to run), so a runnable thing is never a path he has to go and type. John, 2026-09-05: "when
reports are built (e.g. a Gandalf report, or a researchPrime plan or report) they need to show up
with a clickable link in the plan outline … as well as they always need to have a clickable link in
the deliverable section. If it is a bit of code that opens in another window and runs locally on
puter, but displays in an anchor window that still needs a clickable link."

**Why now.** The register (`DELIVERABLES.md`) only opens files INSIDE the effort folder; skill
reports live in the project's lane output dirs and the Gandalf run dirs, so they render as text,
never as links — and nothing writes a register row when a run finishes, so the steward's own
convention ("a step producing a human-facing artifact is not done until listed") is a hope. The
runnable-deliverable link was a design note (`planning/deliverable-runner-2026-09-04/NOTE.md`),
not built.

## Success criteria (the SURFACE)

1. **A finished run registers itself.** When a Gandalf run finalizes, a researchPrime / lane job
   finishes, or a Foreman wave GOes, one row is appended to the effort's `DELIVERABLES.md`
   (the project root when the run has no effort): what it is, where (an Anchor route the cockpit
   can open), the date, and the roadmap step it belongs to (the active step at the time).
2. **A register row may point at an Anchor route, not only an in-effort file.** A Where cell that
   is `/report/…`, `/artifact/…` or another contained Anchor route is `openable`; the pane and the
   plan outline render it as a link that opens in a new window. Rows pointing outside the effort
   AND outside Anchor's routes still render as text (containment stands).
3. **Both places, one source.** The plan outline's step expansion lists the step's register rows
   (already keyed by the register's step column) — a report registered with a step shows there;
   the deliverables tile always shows it. No second registry.
4. **A runnable deliverable has a Run link.** A register row whose Where/How cell declares
   `run: <command>` renders a Run link that opens a cockpit terminal (general lane) in the
   project's tree with the command staged as a pending paste (Enter runs it) — an Anchor window,
   token-gated, killable like any session. Documents keep their open link; nothing else changes.
5. **Nothing regresses, and it is seen.** The steward/cockpit nets stay green; a Gandalf run on a
   real project is opened from the plan outline AND the deliverables tile on the page; a
   `run:` row opens a terminal with the command staged (Playwright screenshots), before v1.2.13.

## Non-goals (parked, named)

- The app slot (an iframe-proxied local web app), the remote display for native GUIs, and Roar —
  the deliverable-runner note's items 2 and 3; parked with the trigger "a web-UI deliverable is registered".
- Auto-running anything: the Run link stages the command; John presses Enter.
- A new registry, a database, or a schema change to `DELIVERABLES.md` beyond an optional cell.

## Risk taxonomy

| Risk | Mitigation |
|---|---|
| A run finishes with no effort context (classic window job) | the project root is the effort of record; the row lands there |
| A route-valued Where cell escapes containment | only Anchor's own contained routes (`/report/`, `/artifact/`) qualify; anything else stays text |
| Double rows on retry/resume | the registrar is idempotent on (what, where) |
| The Run link runs something on the user's behalf | it never submits — pending paste only, the user presses Enter |

## Foresight brief

Once every run registers itself, the status look-through can say "report ready → link" in the
Doing row; the app slot becomes one more `run:` kind when a web deliverable actually appears.
