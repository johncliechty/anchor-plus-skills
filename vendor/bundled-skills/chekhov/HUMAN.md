# HUMAN.md — John's operator guide (W1 scaffold)

This is YOUR page, not a host's. The operator verbs and session keys below are
never told to an agent; SKILL.md shows a host only the four public verbs.
Stopping halfway through any step list loses nothing — every step is
idempotent and re-runnable.

## The operator verbs (yours alone)

### Notes do not need a chapter assignment

Chekhov keeps the quoted source and a candidate entry for each supported claim.
An explicit chapter scope stays attached to that chapter. A statement explicitly
applying to the whole project uses project-wide scope. When timing is absent,
the entry says **timing unspecified — pending**; no chapter is invented.

The ledger report lists **Scope pending** with the source quotes. Those entries
are retained while timing-dependent checks wait. A report with zero contradictions
and pending scope is not a completed check. Capture does not interrupt you to assign
chapters; resolve timing during the existing review/edit walk when it matters.
Project-wide structural notes stay visible as unplaced rather than filling every book.
Conflicting whole-series claims remain separately cited candidates.

The shared extraction convention names the current series `series`, keeps other
subjects distinct, stores numeric counts as numbers, and stores explicit word-count
ranges as `{min,max}`. It supplies no expected story answers. Existing timed entries
remain valid. Older Chekhov versions reject the new explicit scope forms; the current
fixed prompt hash identifies this additive contract. The failed first capture is
preserved and must not be relabelled or resumed under a changed prompt.

| Verb | What it does |
|---|---|
| `chekhov roots` | Initialise the four project roots: extract the text from the two zips (first run only), make each root its own git repository, write the binary-excluding .gitignore/.gitattributes, the host write-denial rules and the one-line consumer paragraph, record the zip SHA-256s, mark the zips read-only |
| `chekhov roots --check-remote` | Read the foundry remote's visibility once (`gh repo view --json isPrivate`) and journal it; if not private, every promoted fixture is labelled reconstructed-deidentified |
| `chekhov fixture promote <verdict-id> --from <verdicts.json>` | Promote a verdict record to `test/fixtures/<id>.json` (refuses without a `kind`) |
| `chekhov fixture report` | Count real-replay and reconstructed fixtures separately (criterion 3) |
| `chekhov migrate <docx>` | Convert one Word file to `<name>_source.md` beside it (headings and paragraphs preserved, header comment with the docx SHA-256 and date). An existing `*_source.md` is kept — never overwritten; a divergence is printed and journaled |
| `chekhov migrate bright-heart` | The W2 named set: keeps `Series_Bible_v4.2_source.md` as canonical, registers `COMPREHENSIVE_CASCADE_SUMMARY.md` and `CLAUDE.md` as-is, migrates `Book_1_Outline_v2` and the manuscript, records the word count under the one rule (prior 167,412 beside it) in `chekhov/manifest.json` |
| `chekhov pack enable` | Arrives in Phase 3 |

## First sitting after the W1 build (about 5 minutes)

1. `chekhov roots`
   What appears: one line per root — `extracted-text-from-zip` (first run only),
   `initialised` or `already-toplevel`, then `gitignore, gitattributes,
   write-denial, consumer-line`, and `zip-checksum-recorded` for the two
   zip-backed roots. Done looks like: four lines, no ERROR.
2. `chekhov roots --check-remote`
   What appears: `remote visibility: private` (or `public`/`unknown`). The
   result also lands in `journal/0001-scaffold.md`. If it is not `private`,
   nothing breaks — fixtures are simply labelled reconstructed-deidentified
   until the remote is private.
3. `chekhov bright-heart`
   What appears: two lines — `chekhov bright-heart — session start` and either
   `no changes since last session`, `changed since last session: <file>` (your
   own edits, queued for commit — expected, never a violation) or
   `unmanaged edit: <file>` (a reconciliation HALT: something other than the
   engine touched an engine-owned file; you confirm or revert it at the
   session prompt).

## After the W2 build (about 2 minutes; the gate already did the heavy lift)

1. `chekhov migrate bright-heart`
   What appears: one line per canonical file — `kept existing canonical:
   Series_Bible_v4.2_source.md`, `registered canonical as-is: …` (twice),
   `kept existing: Book_1_Outline_v2_source.md`, `migrated:` or `kept
   existing:` for the manuscript — then the manuscript word count under the
   one rule with the prior 167,412 beside it, any `DIVERGENCE:` lines (also
   recorded in `journal/0002-bright-heart-migration.md`), and `manifest:
   chekhov/manifest.json`. Done looks like: no `MISSING:` line, exit 0.
   Re-running changes nothing (idempotent; your `*_source.md` files are
   never overwritten).
2. `chekhov bright-heart`
   The session brief's lint now carries the coverage section: every docx
   with no `*_source.md` beside it is named there (informational — the
   archive docx stay stale until Phase 4's render), and the Artificial Magi
   JS bible generators are listed FROZEN (kept, not run).

## The session prompt keys (TTY only — hosts never see these)

| Key | Transition |
|---|---|
| `l` | lint (W4) |
| `s` | structure (W5) |
| `c` | commit (W6) |
| `m` | migrate (W2) |
| `u` | set unit |
| `r` | render (W19) |

In W1 the keys are registered but their transitions land in the named waves;
pressing one before its wave tells you which wave brings it.

## W5 inspections and intake

W5 operator inspections are available as `chekhov lint bright-heart` and
`chekhov structure bright-heart`. The engine regenerates only
`chekhov/LEDGER-REPORT.md`. Lint lists the quoted prose spans, doctrine hits,
chapter breaches and seven intake asks. Structure lists chapter counts as
candidates, per-book beat slots, cut-after-a-triumph candidates and the duology
checklist. These commands record no author choices or acceptances.

The outline gate requires exactly three decision entries: doctrine tag,
single-valued book count, and single-valued chapter rule. Age category is a
nonblocking ask that must be answered before choosing a length target. When
Book 6–7 commit coverage or accepted Book 7 threads are absent, the fork
package stays unknown and ask (3) offers no recommendation. The first real
writing sitting remains the W11 halt.

## How a sitting works

`chekhov commit bright-heart --replay <fixture.json>` extracts candidates from
recorded replies. A fixture is `{ "schema": 1, "scenes": [ { "file": "bible.md",
"heading_path": ["Bible"], "tuples": [] } ] }`; paths are relative to the project.
For repeated headings, add `"line": 2` (the scene's 1-based starting line) to
each fixture scene. Without `line`, file and heading path must identify a unique
scene; duplicate or unmatched bindings are refused before candidates are written.
The fixture must contain every scene in the batch. `--live` is a separate,
by-hand terminal command using the selected coding family. It is never part of
the test gate. Each run handles up to 20 pending heading-delimited scenes and
prints rejected outputs, the candidate list and the remaining scene count.
Run the same command again for the next batch. Markdown is untouched; candidates
are inserted into its sidecar. `--scope "Chapter 2"` restricts extraction to that
heading (or give a project-relative markdown path); manuscript extraction requires
a scope. Live extraction records the shared driver's observed controls and its
model-attestation limits; a requested model is not proof of the served model.

1. Run `chekhov accept bright-heart --list <ids.txt>` for a bounded sitting
   (one stable id per line, or a JSON array). Omit `--list` for all waiting rows.
2. The walk visits commit candidates, idea candidates in the verdict log, then
   provisional decisions, including unanswered ones. Each screen quotes the
   source heading and receipt, the current value and interval, dependent entries
   and their cost of change, citing verdict lines, and a recommendation with its
   reason. A previous defer note prints first. A drifted receipt shows the proposed
   new quote before you decide.
3. Enter a key, followed by Enter:

| Key | What is recorded |
|---|---|
| `a` | Accept the displayed value and receipt; record John and the date |
| `r` | Delete this pending candidate; an idea rejection is an immutable log addendum |
| `l` | Leave it pending |
| `s` | Swap the current row with another named pending row |
| `?` | Print the full dependent closure and every citing verdict line |
| `e` | Refine the value as text or JSON, or use a patch with `value`, `interval`, `governs`, or `question`; record `edited_by: john`, then show the revised row before acceptance |
| `n` | Author a decision directly, without a candidate; type its value for an unanswered decision, or JSON with `id`, `value`, `interval`, and optional `governs` for a new one; record authorship and acceptance |
| `d` | Leave pending with your dated note, shown first next time |
| `q` | Save progress and quit |

A decision edit may also specify `allow_terms`; they take effect only after `a`.
New values are available only at a real terminal. EOF or redirected input accepts
nothing. Each answer saves immediately: quitting halfway loses nothing. Done
looks like `Sitting saved: 0 pending`, or a named remainder waiting on you outside
the selected list. This command records your decisions; it does not establish
that the bible's prose has no contradictions. The first real writing sitting
remains W11's explicit halt.

## Record the first corpus (W7)

From this skill's directory, run this in your own terminal:

```powershell
node bin/chekhov.mjs commit bright-heart --live --record-first
```

The correction passed independent Grok verification on2026-09-08 evening; only
the required real-capture checks remain. Run the same command until it says
`Recording complete; all Bright-Heart live targets recalled.` Each invocation processes
up to 20 pending heading-delimited scenes in one serial data session. The screen
lists candidates, rejected proposals and the remaining scenes; completed batches
survive quitting. No author interview, acceptance, rename or signature is supplied
by recording. Keep decision entries absent until the snapshot is frozen.

The named corpus has469 sections, at most20 per invocation. John has authorized
Codex to operate this capture; he need not type the mechanical commands. The failed
old-contract attempt processed20 sections and stored one candidate. Formal recovery0017
preserves that attempt separately before a fresh capture. A repaired20-section sample
took about nine minutes; full capture is likely to take hours. Capture allows up to
ten minutes for one model response: two valid sample responses exceeded the old
three-minute limit. Keep source files unchanged during capture.
If backlog is zero but recall fails, preserve the output and stop; do not keep
rerunning or manufacture missing entries. Tell the driver when capture completes
so Foreman can verify the actual evidence before advancing.

The required live corpus is the migrated Bright-Heart bible, cascade summary,
root CLAUDE.md and Outline v2 named in `roots.json` and its migration manifest.
The manuscript remains per-scene, on demand with ordinary `commit --scope`.
Dialogue claims remain candidates and do not conflict in T0 until accepted.

Raw first-commit replay (including file, heading, line identity, response and seat
receipt) is saved under the Bright-Heart root at
`chekhov/recordings/bh-first-commit/extractor.json`; its sibling `backlog.json`
records the pending counts. With W1's private-remote check, a full replay is also
exported to `test/fixtures/recorded/bh-first-commit/extractor.json`. Otherwise
`test/fixtures/recorded/bh-first-commit/fixture.json` exports only a minimal,
de-identified candidate view labelled reconstructed, with the raw-recording pointer.
Unexpected private extractor text is never copied into that view.

At the end of the live corpus, the command freezes
`test/fixtures/brightheart-pre-decision/`, distinct from the live bible. It copies
markdown and candidate sidecars only with a private-remote receipt; otherwise it
uses minimal reconstructed excerpts verified against the captured candidates.
The snapshot is never updated after it is captured. Lint it with
`node bin/chekhov.mjs lint test/fixtures/brightheart-pre-decision`.

The recall check requires three pre-authored Bright-Heart targets: the six-book
claim, the seven-book claim and the Outline v2 expansion. The extractor receives
the fixed instructions, predicate catalog and current scene. Observed claims
are matched to the historical targets afterward by their source file, kind,
value and interval; their extracted IDs stay intact. Missing or mismatched targets
fail by name. If recall fails after the backlog reaches zero, stop and preserve
the recording for review; repeated extraction or seeded candidates cannot repair
missing evidence. The book-count pair freezes the snapshot even if the separate
Outline target is missing.

c3-03 through c3-08 remain labelled historical T0 replay fixtures. They require no
additional live recording. The command also journals the real-corpus T0 timings
at `journal/0003-timing-t0.md` when the Bright-Heart backlog reaches zero. Timing
uses each project's saved pack configuration. For the currently unconfigured AM
root, an explicit timing fixture selects its existing pack stub; the journal
labels that limitation. This does not configure the live project or build W15.

`fixture report` maps each fixture to its criterion and counts real-replay and
reconstructed separately. c3-09 is explicitly reserved for W9's relationship judge.
The age case preserves Anya's approximately 13, her unresolved spoken 11, and
the note that Jess is 11. The spoken claim is dialogue and remains excluded from
T0 conflicts until accepted. No birth years or author reconciliation are inferred.

For ask (7), the naming fixtures remain drift until you accept each deliberate
rename. In the relevant project's ordinary `accept` sitting, use `e` on an
existing alias candidate with `{"authorial_rename":true}` (and your actual
interval), then `a`. The alias and its `expected: authorial_rename` field save in
the same atomic answer. Historical replay/report can read that accepted entry
when explicitly supplied its acceptance root; the default fixture report retains
the frozen expectation. Merely editing or leaving a row accepts nothing.

The required recording tests fail with **Missing real capture** until this
terminal recording exists. Synthetic tests are labelled and cannot satisfy that
boundary. Foreman owns the test gate and git; this command performs no git action.

## Reconciliation (session edits)


The engine names the file on line 2 (`unmanaged edit: <file>`). It preserves
STATUS.json while reconciliation is open. The brief and Steward heartbeat
publish the current blocking action and explicitly label the retained status
as stale; they do not claim it was rebuilt. Inspect the edit, then type
`confirm` at the real session prompt to claim it, or revert it. A seat in a
pipe cannot confirm. A headless session records the wait and leaves it open.
## Formal0037 first-session preparation

The operator handles commands and preparation; you choose the writing work and
make the creative decisions. From the canonical skill directory, the Node entry
is `node bin/chekhov.mjs`, for example `node bin/chekhov.mjs bright-heart`.
In this section, `chekhov` is shorthand for that invocation; it does not mean
a bare command has been installed on PATH.

Choose `chekhov bright-heart`, `chekhov artificial-magi`, or
`chekhov sing-for-the-dead`. Use `--unit "Book 1"` or the current story/novella
name to select your work. BrightHeart uses its Kishotenketsu selection,
Artificial Magi its Four-Part selection, and Sing for the Dead its story/novella
Eddy selection. Existing author decisions remain in force through their recorded
provenance; source candidates are still proposals. Operator validation and your
first sitting have separate receipts; preparation alone supplies neither.

The brief shows the project, unit, cascade, next useful action, your open asks
and last event date. `chekhov brief <project>` opens the same textual brief;
`chekhov status <project> --line` prints only its first line. Wiring diagnostics
are secondary. The ledger report and quoted source passages explain concerns.

At the terminal session prompt, paste an idea or your host's dictation transcript.
You can also use `chekhov idea <project> --text "your line" --unit "your unit"`
or place a UTF-8 transcript in that project's `chekhov/inbox/` and use
`--file chekhov/inbox/your-note.txt`. This is transcript intake, not new speech
recognition. Raw text is preserved. UNKNOWN/PENDING means the line is still open;
source-qualified support for one claim does not accept unevaluated material.

For the prepared bounded walk, use `chekhov accept <project> --list first-accept`.
The context and recommendation precede each question. Use `a` to keep an entry,
`e` to revise it, `d` to defer with a note, `l` to leave it, or `q` to stop.
Swap only to an actual candidate ID in that project. EOF also preserves pending
rows. Acceptance occurs only in your real terminal; a headless launch leaves
answers pending. Known documented choices do not need to be invented again.

At the session prompt `u` changes unit, `l` inspects lint, `s` inspects structure,
`c` invokes the existing commit path, and `q` saves an unsigned session draft.
Resume with the same project command. Unresolved lines remain in VERDICTS.md.
A genuinely new root can start with `chekhov <root> --pack <installed-form-name>
--unit "New story" --text "a vague seed"`. Voice, structure and theme may remain
provisional. A Bible is unnecessary; the existing author-review and theme rules
still govern later writing/acceptance.

### The 30-second test

Fields: project, unit, cascade_position, next_action, waiting_on_john, last_session.
The machine example is `renderLine1(status)` from `lib/surface.mjs`, also used by
the brief and status command. With a Face present, open the cockpit project page;
start the clock when it renders, then name aloud the project, unit, cascade
position, next action and what is waiting on you (the count including overflow
suffices). Stop and record `thirty_second_test: <seconds>` in your first-job
journal. The identical brief line is the headless fallback, not a second timed
procedure. Add `signed_by: john` and its date only by hand after your review.

Follow the [first writing session guide](references/first-writing-session.md).
This September 11 project-selection amendment governs older fixed-project
sitting instructions above.

### Anchor session integration (root validation pending)

Anchor's existing Chekhov registry entry launches the same public dispatcher.
For a headless launch it sends one JSON object on stdin with schema
`chekhov-anchor-session-v1`, the existing `project` and absolute `folder`, and
Anchor's `project_id` plus a unique `session_id`. A supplied `commission_id` or
`step_id` is preserved. Optional `unit`, `text`, `replay` and `sources_file` use
the existing engine. Model use requires explicit `live: true`; a headless
launch accepts no author choices. Ordinary CLI arguments retain their behavior.

The session's run row uses Anchor's existing commission store and reader. Its
report contains the current brief, observed transition times and the identical
rendered human wait. A reconciliation HALT retains exit 4; integration failure
returns exit 5. Anchor's text runner treats either as a failed host operation,
while its commission reader retains the actual wait. No success is inferred
from an openable deliverable or a saved draft.

Existing ledger-report and verdict-log files register automatically during that
headless session. For produced renders or lock receipts, root can declare
`integrations.anchor.deliverables` in `chekhov/config.json` as an array of
`{"kind":"render","path":"relative/produced-file"}` or `lock-receipt` entries.
Absent files receive no row. No render or lock event is generated by registration.
Anchor owns row formatting, locking, links and deduplication. Managed campaigns
that require `refinement-update` refuse this legacy registration/heartbeat path
explicitly; this adapter cannot change their authority.

Operator integration checks and their receipts are separate from the author-use
checks in the [first writing session guide](references/first-writing-session.md).
Successful dispatch and file registration do not establish a validated full UI.
Actual cockpit opening, your sitting and the timed screen test remain pending.
