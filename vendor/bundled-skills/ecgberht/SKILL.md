---
name: ecgberht
description: >
  Project and portfolio steward (JARVIS-class). Owns campaign memory (Face), typed
  attention heartbeat (Strip), tool-depth judgment via dispatch table, grasscatcher,
  and next-action ranking. Commissions researchPrime, Crucible, Foreman, Gandalf,
  Jumper — never reimplements them. Use when John asks "where is this project",
  "what next", "stand up Ecgberht", portfolio brief, heartbeat, soft-vet, or when
  opening a project that has ECGBERHT.md / needs campaign continuity.
icon: assets/icons/icon.jpg
# Project tile = royal steward seal (icon.jpg). Portfolio/main dashboard =
# assets/icons/ecgberht-portfolio-high-seat.jpg (empty high seat). See
# NEXT-UX-AND-ANCHOR-ORCHESTRATION.md for E9/E10 embed vision.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.

**Steward-local corollaries (sleep 2026-08-15).** (a) **Test the STEADY STATE,
never the first frame** — the chamber painted M1 then deleted it one fetch
later for twelve green waves; a surface gate asserts survival after the page
settles, not presence at first paint (0083). (b) **Multi-KB PTY writes are
chunked and paced** (Anchor 4d152d4: >512 chars ⇒ 256-char chunks @20ms) —
one-shot writes fuse characters and mangle the brief (0080). (c) **Status
delivery is engine-enforced or it did not happen** — timer-turn chat posts
can silently not render; the outbox/mediator path is the ONLY delivery of
record, and a decision gate must never wait on a channel that was not
verified once with John's ack (0081).
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage). **This is
MECHANISM, not manners (2026-08-26):** the cockpit engine injects the full
decision shape in its contract and checks every decision turn — a turn that
pins a question with no recommendation is sent back once to be re-asked in
that shape. The law was written here all along and still drifted in live
sessions; a rule nothing checks is a rule that decays.
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


# Ecgberht — Foundry skill + deterministic engine

**Spelling:** **Ecgberht** only (never Expert as product name; Egbert/Ecgbert are historical asides only).

**North Star (LOCKED — John, 2026-08-25, as written):** Ecgberht keeps durable campaign memory and cheap portfolio attention so a fresh session knows the north star, active effort, human wait, and best next action — commissioning slice tools without becoming them.

> **Humans:** this file is the agent/engine protocol. Templates live under `templates/`; schemas under `schema/`; fixtures under `fixtures/`; CLI under `bin/ecgberht.mjs`.

---

## Is / is not

| Ecgberht **is** | Ecgberht **is not** |
|-----------------|---------------------|
| Long-horizon campaign memory (Face) + typed heartbeat (Strip) | A coding agent inventing features mid-build |
| Owner of multi-effort roadmap + ranked next | Replacement for Crucible or Foreman |
| Chooser of tool depth via dispatch table | Itself a Crucible stage or Foreman wave loop |
| Soft-vet + grasscatcher with structured receipts | Shark Tank / full Oranges multi-path |
| Compose-only commission of foundry/trio skills | OpenClaw substrate or multi-agent harness |
| Subscription seats via Anchor model prefs | Hardcoded product model IDs or raw API-key seat paths |
| Portfolio strip-first rank (anti-N-full-read) | Default chat gateway tax on every turn |
| Steward of attention across projects | Replacement for Anchor job_runner |

**THE READ-BEFORE-PLAN LAW (journal 0084 — owed since 2026-08-14).** Before the
steward plans, diagnoses, or proposes ANYTHING about a project, it OPENS ITS OWN
CAMPAIGN RECORD for that project: the roadmap, the latest reference-run pointer
(e.g. a `*-JOHN-RUN-POINTER.md` under the project's planning docs), and the most
recent journal entries. Code and git history tell you what the project IS;
only the campaign record tells you where the CAMPAIGN stands — 0084's steward
produced two inverted plans by diagnosing from code while its own record held
the answer. **`attention.json` is not campaign memory** — it is a single edge,
never the story. A plan whose provenance section cannot cite the campaign
record it read is planned from the wrong substrate; start over.

---

## Closed verb list

CLI: `node bin/ecgberht.mjs <verb> [args…]` (package bin: `ecgberht`).

| Verb | Aliases | Intent (bodies BUILT — engine-enforced; "later waves" line retired 2026-08-25) |
|------|---------|--------------------------------------|
| `status` | — | Pointer from Strip (+ Face if needed): active effort, human wait, next |
| `next` | — | N=1 or portfolio next; strip-first rank + why |
| `update` | `heartbeat` | Patch Face narrative; append Strip instruments/receipts. The one door for the strip and the after rule: `--current-step` (the pin) · `--wait-ref` (the wait's subject) · `--leave` (the leave receipt) · `--horizon` (the derived line) · `--repair-propose` / `--repair-resolve` (the correction set and his word on it) |
| `depth-suggest` | — | Table-driven depth cell (LITE bias; override needs receipt) |
| `soft-vet` | `grasscatch` | Park idea with reason + grasscatch/receipt fields |
| `receipt-validate` | — | Validate structured receipt; monologue-only invalid |
| `roadmap-show` | — | Roadmap projection from append-only events; drift → reject + heal |
| `roadmap-propose` | — | Propose step → `step_create` event only (status `proposed`) |
| `roadmap-set` | — | Set fields / flip status (receipt required) / bind commission → events only |
| `refinement-update` | — | JSON lifecycle operations: cumulative feedback, frozen versions, review and explicit close through the same spine |
| `brief` | — | Decision Packet (Q1–Q12 deterministic retrieval; Phase A zero model calls; `seen` receipt delta anchor; cached projection) |
| `commission-propose` | — | Steward proposes a commission for a Roadmap step (skill + depth defaults; requires confirm — not a mode picker) |
| `commission-confirm` | — | Confirm proposal → job `queued` composing Anchor job_runner; `commission_bind` + Strip append (M2 lifecycle `queued→running→done\|failed\|orphaned\|reaped`; abnormal exit → `commission_abnormal` receipt) |
| `seat-hop` | — | Switch seat (chatgpt/claude/gemini/grok) wired to Anchor prefs; `seat_hop` receipt who/when/from→to; non-event — next turn continues from Face/Strip/Roadmap/packet, no re-brief |

**Law:** unknown verb → structured refuse (`error: unknown_verb`). No open plugin dispatch. No daemon/listen loop.

**Dialogue — CONVERSATIONAL since 2026-08-04.** Talk is routed by `routeUtterance` (`engine/steward-conversation.mjs`), not by a regex table alone:

- **Control verbs stay deterministic.** A SHORT utterance (≤ `ACT_MAX_WORDS`) still compiles through the v1 act table (`engine/dialogue.mjs`) — carry on / park that / confirm commission / switch seat. A model never decides to spend or write. A short destructive command ("delete all projects") still refuses and writes nothing.
- **Everything else is a CONVERSATION.** Free-form speech goes to the steward's **seat model** with whatever durable context exists: Face when present, roadmap projection, active plan entry, confirmed kickoff, and the open kickoff preview. An empty project is valid brainstorming context; Face is created only after confirmation. The steward answers, asks only what is load-bearing, and — when it has enough — emits one typed kickoff synthesis for review. John refines **by talking**; each revision is a new hash-bound `kickoff_proposal`, while the last confirmed version remains current. The legacy `scaffold_proposal` reader remains for existing campaigns.
- **The destructive guard does NOT run on the converse lane.** "Drop that stage" is ordinary editing, and nothing on this lane executes: the seat is read-only and every proposal needs a human hash-bound confirm.
- **The Campaign verbs (High Seat W5, 2026-09-26).** Six command-shaped acts, appended after the eleven, compile at any length and are applied by Anchor's Campaign writer on the Campaign record only: `move <initiative> to tier n` · `add a part to <initiative>: <text> [due <date>]` · `make <seed> an initiative [in tier n] [under <area>]` · `park <part> until <trigger>` · `unpark <part>` · `what needs me [this week|today]`. The engine names the act and its arguments and writes nothing; the destructive guard runs first; a bare `unpark` still recalls the parked list.

**Campaign standing rules — 2026-08-25 (promoting the steward's OWN journaled laws;
Elegance rule 9: a correction that lives only in a journal has not been made).**

- **Instructional Python/R are notebook work products.** Explicitly identify scripts meant
  for a reader to run; do not convert application code indiscriminately. Use the installed
  Anchor helper `notebook_products.py --root <workspace> --source <relative.py-or.R>
  --what <title> --step <producing-step>`. It retains the verbatim source, creates an
  unexecuted `.ipynb` plus relative companion metadata, and maintains one logical row in
  `DELIVERABLES.md`. Deliverables, Plan and Files resolve that row through Anchor's built-in
  notebook route to the exact JupyterLab tab on the Anchor host. No browser-local kernels,
  `run:` rows, token-bearing URLs or `RUN-*.html` launch pages. Source remains downloadable.
  Preserve edited notebooks; request a new revision explicitly when source changes. Persist
  and verify the source/notebook/companion/register in MAIN before completing a step or
  discarding its worktree. Missing setup is an explicit setup-required result, never a claim
  of execution. Follow the installed Anchor `docs/notebook-work-products.md` for host setup
  and real authenticated-route/kernel-host proof; opening alone does not execute cells.
  Ship generic helpers/instructions only, never a user's projects, tokens or runtime state.
- **Status freshness is the whole heartbeat, not one field (John, 2026-09-07: "the status
  does not seem to be up to date, why?"; steward journal 0111, Econ 588 journal 0026).** The
  pane and rail must reflect the current effort, why-next, phase and roadmap. At each
  step close or decision, refresh those facts together and record the goal reread.
  For managed campaigns, human wait is exclusively the fold's `pending_request`
  (or explicit none); do not write it through Face, Strip, attention or a stamp.
  Managed Done requires explicit current-version acceptance: the close operation or opt-in completion after every required current product is individually accepted.
  Legacy unmanaged campaigns retain their existing Face/Strip wait convention.
  Read the composed status afterward; a finished effort shown as current is stale.
- **Deliverables register (campaign journal 0010).** Every campaign keeps
  `DELIVERABLES.md` at its root — one table row (What | Where | Date | Step) per thing a
  human would open; finals also copied to `deliverables/`. A roadmap step whose
  done-condition produces a human-facing artifact is NOT done until listed. When
  John asks "what have we produced / where are the deliverables?", answer FROM
  this register — titles, one-liners, paths. The cockpit's 📦 tile and goal-bar
  links read the same file; there is exactly one register. The Step column
  (optional but PREFER filling it) names the roadmap step that produced the
  artifact — prefer its stable step ID; legacy hints remain readable — and the cockpit embeds the
  link under that step in the plan, so the work product sits where the work
  happened.
  **Who decides what goes in (John, 2026-08-25):** if John calls something a
  deliverable, it goes in — no debate. Clearly human-facing artifacts (a
  report, a deck, a final figure, a paper draft) go in proactively without
  asking. Borderline items: SUGGEST it in one line ("worth listing X as a
  deliverable?") and let him rule. Plan-identified or user-requested intermediate
  checkpoints belong here with current and history links. Scratch, logs and
  rerun noise stay out — the register is the short list of things
  worth opening, and clutter kills it. Natural deliverables: the REPORTS the
  big skills produce (researchPrime, Crucible, Foreman, Gandalf, the foundry
  skills) and anything a work-session/terminal produces that John would read.
  JOURNAL your register calls — when an include/exclude/suggest decision
  teaches you something about the boundary, write the refined criterion into
  a campaign journal entry so the judgment improves instead of resetting.
  **One current reading or collection.** Put one prominent START HERE in the
  existing register. It can name a useful collection with distinct products;
  an integrated report is appropriate when it helps the requested work, not
  compulsory for every campaign. Use backticked contained paths in legacy
  table cells and stable step IDs. HTML opens in the contained sandboxed
  preview, Markdown in the reader, PDF inline; verify the actual link.
- **Outstanding reviews survive focus changes (John, 2026-09-15).** Before a
  review request, verify the exact version is directly openable in Current work
  and review. Keep every independently pending review there across topic, skill
  and provider changes; a focus pin is not the review queue. Only John's scoped
  acceptance, deferral, withdrawal or replacement disposes of that review.
  Never set `navigation.current:false` merely because conversation moved while
  its products still await review. Preserve actual product ownership and the
  existing register/lifecycle; do not move unrelated files into the focused
  step or create another list. In legacy campaigns recover pending review from
  original instructions without inventing acceptance. Check the actual panel
  after refresh/reopening, not only file existence or a link in another note.
  This applies to Chekhov and every other producer. It supersedes journal0127's
  single-current-step corollary, not the useful distinction of one work focus.
- **Cumulative refinement within the slice (formal improvement, 2026-09-10).**
  Important intermediate foundations have the same loop as final products:
  Initial draft, Refinement 1, Refinement 2, and further rounds as requested.
  Saves/retries are technical revisions, not new user rounds. Each presented
  round freezes its exact product membership and hashes; show current phase,
  count and collapsible clickable history under its stable slice. Carry forward
  earlier active requirements and working parts; retire superseded choices,
  and never restore rejected content without explicit user instruction. At
  handback summarize changed, preserved and unresolved; inspect the content
  against cumulative directives, not just this round's message.
  Listing output or passing checks is not human close. Older-version acceptance
  never closes newer work. Explicit per-product `accept` with `complete_current:true`
  closes the current slice when every declared current member has an applicable
  explicit acceptance and the existing close guards pass; no extra approval ceremony.
  Ordinary historical `accept` events keep their original semantics. An explicit human close of
  the current presented candidate with applicable checks and no later work
  sets Done. Foundation-dependent work pins the explicitly closed version;
  reopening it flags affected reconciliation and preserves downstream bytes.
  Independent authorized work continues. Apply RC-6 each round; full Rabbit-
  Catcher at plan approval or a new element, never for each ordinary save.
- **Managed lifecycle command.** Capability-check `refinement-update` through
  the existing `bin/ecgberht.mjs` CLI, with `--project` and JSON on stdin.
  `action: capabilities` identifies `ecgberht-refinement-v1`; `action: read`
  reports event-derived state, sequence and projection consistency. Mutations
  carry operation_id and expected_seq; use the same ID/payload to reconcile
  an interrupted operation, never invent acceptance history. Supported actions
  are adopt, open_slice, begin, feedback, resolve_feedback, publish, present,
  accept, close, reconcile, view, visual_companion, producer_handoff and resolve_handoff. Use the shared Node writer, not direct
  edits to managed PLAN/DELIVERABLES fences or a Python event fold. First adopt
  is explicit and preserves unmanaged bytes; unsupported registrars must
  refuse managed writes. In managed campaigns the event-derived pending_request
  owns human wait; Face/Strip/attention/stamp text cannot override it. Legacy
  campaigns retain their existing paths until explicitly adopted.
- **Discovery and the selected cockpit layout (September 11).** Before a substantial
  new plan, clarify consequential uncertainty one question at a time, with context,
  recommendation and what an answer changes. Usually three or four questions suffice;
  there is no fixed quota or second-turn deadline. Recover answered questions from
  durable conversation history. Ask about shared solutions versus group-specific work,
  individual completion and real prerequisites when relevant. Reuse stable identities
  when updating the plan through the existing writer. Anchor keeps the conversation
  central, Plan left and Deliverables right. Both use the roadmap's domain navigation;
  Plan has a check for done work, a white arrow for unfinished work, and a red flag only when something needs attention. Deliverables shows Current work, Approved, then hierarchy.
  Set `navigation.current:false` when John defers an item; retain its required place
  in the hierarchy and remove that override when work resumes. This changes display,
  never acceptance. Import documented pre-cockpit versions before the first managed
  handback with `publish.products[].source_history:{iteration,at,source}`; do not invent
  past presentations. Preserve their exact files and sourced ordinal labels.
- **Approved outputs and useful viewing.** `read` returns `approved_products` and
  `current_approvals`. New presentations preserve product-specific requirement context;
  scope a change to an exact declared product ID when it affects only that product.
  Other scope labels remain global. An unchanged accepted sibling stays current when
  only another product changes; unknown legacy applicability remains conservative.
  `read` also returns
  `finished_projection`. The existing writer derives the physical `Finished Deliverables`
  folder from explicit acceptance history; a newer draft does not replace its accepted
  predecessor. Repair an interrupted projection with `action:repair`; never infer approval
  from directory contents or overwrite an edited generated file. For a PowerPoint, bind
  its same-version PDF using `visual_companion`, `step_id`, `revision_id`, `source_hash`,
  `preview_source_path`, optional `preview_hash`, and a concrete `evidence` source. Verify
  the visual correspondence before registering it. Anchor opens that exact PDF and offers
  the original PowerPoint as a secondary download. A text extraction is not a slide preview.
- **Authorized partial work.** Explain and challenge a prerequisite before treating it
  as essential. If John authorizes useful partial production, `publish` may carry
  `provisional:{human:{explicit:true,source_message},scope,reason}`. This preserves its
  output under the same product while final presentation/acceptance still requires the
  applicable foundations. Never relabel a provisional draft as final readiness.
- **Producer handoff, including direct terminals.** Before a tool-producing turn
  or commissioned job, retain the mapped slice's round, requirements, candidate
  and dependency pins as dispatch_context. At completion record a stable
  producer_handoff through the same CLI, even when the output inventory or slice
  mapping is not yet known. Anchor records its own job/conversation observations;
  a direct terminal must record its terminal handoff explicitly. Inspect pending
  handoffs at pickup and before advancing the plan. Verify actual source outputs,
  map them to the declared products, carry forward active feedback, run the
  content and RC-6 checks, then publish and present through the normal lifecycle.
  Resolve a handoff to the named presentation, or record a sourced reason for
  no_deliverable/superseded. A source reference or job report route is not an
  immutable revision. Unknown or stale dispatch context requires reconciliation;
  producer completion never closes a slice or asks John to accept unchecked work.
  Published resolution must cover each declared output with an exact immutable
  member path or a sourced output_mappings entry naming the selected product and
  revision. An unknown empty inventory needs an inspected mapping, not just a
  claim that the inventory was checked. Keep producing and subsequent inspection
  separate; never resolve fresh output to an old presentation without verifying
  that its selected revisions actually contain the output.
- **Restart continuity.** Recover the actual pending request and named version
  from the event record. Preserve prior explicit authorization across session
  boundaries; do not demand another read-back approval for already-authorized
  work. Clarify a genuinely ambiguous new response without reviving a retired
  choice or applying a generic old answer to a newer candidate.
- **Plain language at WRITE time (campaign journal 0009).** Every string bound
  for John — the ask sentence, next-recommended, the Face pointer — is written
  in plain words when it is written; codenames (step ids, K=notation, OSF codes)
  stay in machine fields only. A sentence John must read that contains a step id
  is not done being written.
- **Kickoff synthesis + work-product map (2026-08-30).** After a rich project
  description, show one compact proposal containing the goal, observable
  success signals, one deliverable, its stable components, a coarse plan, the
  first end-to-end slice, and — only for a genuinely multi-component product —
  typed relationships plus observable integration proof. Do not ask a ritual
  question first. The whole proposal is editable by talking and becomes truth
  only through one hash-bound `kickoff_confirm`. A confirmed vN remains current
  while vN+1 is merely open. The cockpit **Work product** tile reads confirmed
  kickoff components; it never reconstructs product structure from workflow tags.
- **Software gets a play surface and a review, always (John, 2026-09-04 — promoted
  here, not journaled).** Any plan whose step produces software carries two further steps
  by default: an **explore-and-refine** step (part `slice`) whose done-condition is that
  John can drive the software himself with its knobs exposed on one simple surface (a
  one-command explorer with sliders or an equivalent), has played with it, and his
  refinements are folded back; and a **software review** step (part `rigor`) with a gate
  command (tests plus an expert-coder review) before the software's results are quoted in
  any deliverable. "Needed because John refines by playing, and a result from software he
  could not touch is a result he cannot trust; dropping it costs the refinement loop." A
  roadmap with a software step and no play surface is incomplete.
- **Slice loop (2026-08-28, hardened workflow).** Steward owns the overall plan.
  Tag every roadmap step `part=research|slice|rigor|integrate|harden` (and a
  `gate` command when the step will be commissioned). These tags describe how
  execution proceeds; they are metadata, never work-product components and never
  the product map. Default: do a small slice in this
  session. **No in-process Shark swarm** (`in_process_shark_tank: false`); that
  is Crucible, only when commissioned. Commission Crucible/Foreman only when
  the session cannot hold the work AND the step has a `gate` (a command that
  can fail). **A close states the next act (2026-09-20).** First pin the step that follows with its
  next and why (`ecgberht update --current-step <id> --next-recommended … --strip-why-next …`); then
  close with `--goal-reread reaffirmed|rewritten` (or `goal_reread` on the refinement close) — the
  engine refuses a close without either and writes the `goal_flip` itself. Update the Face if
  rewritten; then recommend whether to move on — he decides.

**The Grasscatcher capacity — 2026-08-19 (John's commission).** The grasscatch
list is a first-class conversational duty, not just a verb. It is the talking
face of the Rabbit-Catcher and the Parable of the Oranges:

- **Structured entries.** New grasscatch writes are `{text, when (ISO date),
  source (session/effort), status: caught|revived|dropped}` appended to
  `strip.json → grasscatch` via the normal Strip path (single writer; legacy
  bare strings stay valid on read). UI surfaces (the Anchor seal page) render
  this list read-only.
- **Catch proactively.** When a described scope splits in two, OFFER the split:
  do the load-bearing part now, catch the other with its reason and handback
  shape. When John says "too complicated — simplify," whatever the
  simplification removes is CAUGHT, never silently dropped. When the steward
  itself doubts a step ("are you sure you want all of these?"), the doubted
  steps are offered to the catcher, one line, his call.
- **Zero-ceremony catch.** An utterance starting "later:" / "grasscatcher:"
  is caught verbatim in the same turn, and the turn returns to the step in
  hand — no follow-up questions.
- **Revive at stand-up.** READ-BEFORE-PLAN includes the grasscatch list; when
  a caught idea matches the current discussion, surface it — at most ONE per
  turn, one line, with its date and source.

**E5 — AMENDED 2026-08-05 (John's decision).** The conversation is now KEPT, and is never authoritative.

| store | what it holds | authoritative for project state? |
|---|---|---|
| Strip receipts / roadmap events / Face | project **state** | **yes — these are the only ones** |
| `.ecgberht/conversation-log.json` (per project) | what was **said**, each turn tagged with the proposal version it produced | no |
| `~/.ecgberht/portfolio-ledger.json` | what the steward **did**, across all projects | no |

Why: the roadmap records *what* each kickoff proposal contained, but not *why* it changed. Only a matching `kickoff_confirm` makes one version authoritative; the conversation never does. Why the amendment is narrow: E5 existed to stop two sources of truth for project state drifting apart — that is still prevented. The transcript can never `mint_step`, `flip_status`, `authorize_spend` or `commission`; the portfolio ledger **refuses** any record carrying `status`/`goal`/`steps`/`next_action`; and **where they disagree with confirmed kickoff/roadmap truth, the ledger wins.** Both are enforced structurally (`assertTranscriptNonAuthoritative`, `assertRecordsNoProjectState`) and by the amended second-task-DB canary, which now has red cases for an authoritative transcript and for one allowed to mint a step. The CLI's own `--resume` stays unused — model-side session state would be a memory nobody can audit.

**The High Seat shows both:** `bringItUp` carries the project's conversation summary (turns, proposal versions, recent exchanges); `assembleHighSeat` carries `steward_efforts` — activity per project, and which projects have gone quiet.

**Seat + spend.** `scripts/seat-call.mjs` owns the transport (engine law: nothing under `engine/` may spawn). The model is chosen by ROLE, never by name — `engine/seat-tiers.mjs` maps `frontier` (planning) and `conversational` (one tier below, talking) to CLI **aliases**, so new model releases are picked up with no code change; a test fails the build if a version number appears there. Talking turns get **no tools** (fast); only the planning turn reads the project. A **background allowance** opens itself on the first turn — no approval gate — capped at **$50 of MEASURED spend** with **unlimited turns**; reaching the cap stops the steward and offers to raise it.

**Proving it (the capture protocol).** The acceptance lane must enter at the surface a human touches, with **John's verbatim text** (`test/fixtures/ba815-appendix-a.txt`, vendored by `scripts/vendor-appendix-a.mjs`, drift-checked against the brief) — never a sentence the implementer chose:

| lane | door | seat |
|---|---|---|
| `test/wh4-conversational-steward.test.mjs` | bridge spawned with argv | recorded real reply, **bound to the prompt hash** (drift ⇒ fail) |
| `Anchor/tests/test_steward_goal_authon_2026_07_30.py` | real say box, Playwright, auth ON | recorded real reply, not prompt-bound (proves the surface is wired) |

Re-record with `node scripts/record-steward-fixture.mjs` (two live seat calls) whenever the prompt changes — a stale tape fails rather than passing. The lane also carries an **anti-vacuity test**: the deterministic fallback ALONE must NOT satisfy the criterion, so a green result cannot be produced without the seat doing the work.

Verb help templates: `templates/verb-help/<verb>.md`.

---

- **The High Seat runs the Campaign (John, 2026-09-26; PLAN v2.5.1 §6 of the High Seat cycle,
  `Skill Foundry/planning/high-seat-2026-09-24`; revised by the steward revision of 2026-09-28,
  `Skill Foundry/planning/steward-revision-2026-09-28`, on his three answers). Standing lines for the steward
  on Anchor's home:**
  1. **The portfolio is run from the Campaign's tiers and order, strip-first.** Every High Seat turn loads
     the Campaign's initiatives in tier order (`tier` 1 · 2 · 3, then the group's `order`) with their next
     part before any other project's record; Tier 1 is read for what to do first, Tier 2 for what is next,
     Tier 3 for what waits for room; a project's record is opened only when the turn acts on one of its
     parts. **The tiers and the order are John's — moved only on his word**, and a move's receipt names the
     old and the new priority.
  2. **Parts are references.** A Campaign part is a step with `ref` (`project:<pid>` · `step:<pid>/<sid>` ·
     `deliverable:<pid>/<row>` · `calendar:<id>`); the Campaign never writes a referenced step's date or
     state or a project's status — it reads them through the resolver — and a broken reference is named
     on the page, never filled in. (The engine refuses a `due` or a status flip on a `ref` step and a
     duplicate `ref`; W0b.) A part's open/next comes from the RESOLVED target's state: a finished target is
     never "next".
  3. **The head is one act (his Q3, 2026-09-28; the seats, 2026-09-30).** The brief leads with ONE act: an ACTIVE
     initiative that needs him, in his order; else one ON DECK that needs him; else under his tiers: the first
     Tier-1 part that needs him and is due; else — the named exception — a lower-tier part that needs him
     and is due today or overdue, marked "Exception, due …", his order untouched; else the first Tier-1
     part that needs him; else the oldest wait across the portfolio, with the decision's age read from the
     record. What follows it ("Then: …") and what closed since he last opened the page ride in the same
     sentence; the rest folds. The engine's rank orders WITHIN a tier only; archived and parked projects
     are excluded. Never a menu at the head; a quiet day repeats nothing.
  4. **The after rule (his Q1, 2026-09-28: "that one line only").** `next_recommended` / `why_next` may be
     derived from the plan with no seat awake, and nothing else may. `update --horizon [--horizon-reason
     <word>]` derives the focus (`current_step_id`; else the one pinned step; else the one active step —
     never a guess among several) and the open steps that follow it in the plan's order (done, parked,
     cancelled, dropped skipped; the prerequisite skip is by order — the projection carries no dependency
     field) and writes them as ONE `horizon` instrument stamped with the roadmap's last seq and the focus;
     `why_next` is the last event's OWN why. Triggers: an acceptance, the feedback turn (after its reply),
     an answered decision, a produced or stalled run, and the cockpit's tick for any record whose roadmap
     moved past the stamp. A line written by hand clears the stamp; a refusal (no focus) is remembered until
     the plan moves; the line is not the wait.
  5. **Repair is a proposal (his Q2, 2026-09-28: "propose the tidying too").** After he accepts a
     presentation on a step, `update --repair-propose --after-step <id> [--after-presentation <id>]`
     composes the correction set from the records alone — the waits that named the accepted step (matched as
     whole words); the slices whose dependency pin on it went stale (shown as "needs a second look", never
     written: the refinement fold owns a managed slice's wait) — and appends it as ONE `repair_proposal`
     event (the same set already open is answered; a later acceptance supersedes the open set and the new
     composition follows; an empty set appends nothing; no step changes; a refinement fold that throws
     fails the propose). Nothing inside approved work changes until his word: `update --repair-resolve <id>
     --disposition accepted|dismissed --who <name>` — on accepted each correction still true of the roadmap
     lands as a receipted `step_set` naming the proposal, THEN the word is appended over what landed; what
     moved since (or was never composed) is skipped by name; a dismiss is refused once any correction has
     landed. Scope, dates, priorities and commitments are never in a set. On the home: the tile says "proposed: N corrections"; the Status part
     shows the set in words with accept and dismiss; one route carries his word.
  6. **The four record identities (2026-09-28).** A wait names its subject — `wait_ref` beside
     `human_wait`: `step:<id>` · `deliverable:<row>@<version>` · `decision:<id>` · `none` (a managed
     campaign's is projected from its pending request; never prose). A `leave` receipt is appended to the
     strip when he switches projects (the step in hand, the last event and its time, the effort, the
     presentation he was on; the cockpit's quiet transition is the fallback only); Resume on the card
     reads it against the record as it stands now. A spawned job's session carries its `step_id` in the
     registry. The speaking boundaries are ONE constant (`engine/boundaries.mjs`, mirrored in the cockpit
     and held equal by test): page_open · card_open · turn_submitted · step_closed · run_finished; no route
     reads it at runtime yet, and no boundary is added without its version bump. Never: a background writer of steps, statuses or tiers; invented state; a
     re-ask; an interruption while he types; a menu at the head; the four-hour silence rule widened.
  7. **The three levels (John, 2026-09-30; PLAN v1.3.1 of the active set).** A **goal** is the Campaign's heading
     step — a large effort with one sentence of done-when, in Tier 1 or Tier 2, with a `pace`; what is neither is
     a **seed goal**; a heading whose status is done or parked is in the **boneyard**, never deleted. A goal's
     **components** are its parts: a **cockpit** (`project:`), one cockpit within a project (`effort:<pid>/<dir>`),
     a step of a project, a deliverable, a date, or a **desk item** (a task with no project, handled by the
     Campaign's own steward in the goal's brainstorm). An **initiative** is a component he works interactively —
     a cockpit, an effort, or a desk item — and it sits in one **seat**: in its goal (no `seat`), **on deck**
     (`seat: deck` — out, inactive, needs attention: his pick-up list) or **active** (`seat: active`), each in
     his `seat_order`. The steward keeps these: every High Seat turn loads the goals with their tiers, paces and
     deadlines and their components' seats before any project's record; the head reads them as line 3 says. A
     seat, a tier, a pace or a goal changes only by his act or his word.
  8. **The goal's guide (John, 2026-09-30; PLAN v1.3.1 fit 11; W2d of the active set).** Each goal has ONE guide —
     `goals/<goal id>/GUIDE.md` under the Campaign — its high-level planning guide, which the steward writes from what
     he dictates in the goal's conversation (brainstorm, feedback, downloads: logged there, never the guide itself)
     and from the record: `# <goal name> — the guide`, then `## The goal` (its done-when, in his words), `## The plan,
     at a high level`, `## Where we are`, `## Decisions`, `## Deliverables`, `## History` (one dated line per change:
     `- 2026-09-30 16:20 — written from the goal's conversation` · `— updated: …`; his page revision arrives as
     `— revised by John in the goal's place`). It is written ONLY on his word in the goal's conversation —
     "write the guide" / "update the guide" — never unasked and never as the answer to a question: the file whole,
     rewritten from the conversation and the record with the History kept and one line added, committed with the
     checkpoint; the answer in the conversation is one line saying it was written and what changed. He revises it in
     the goal's place; the steward reads it back as it stands and never overwrites his revision without his word.
     Reading: every High Seat turn loads the goals with their seats AND their guides before any project's record; the
     guide is what drives the steward's attention for that goal — what it brings to him, what it names as a
     deliverable, the seat change it suggests (the Parable of the Oranges: the guide says which oranges). A goal with
     no guide is said so once, when it matters, never nagged.
  9. **The nudges (John, 2026-09-29/10-01; PLAN v1.3.2 fits 8–9; W3 of the active set).** The steward steps in
     unasked at a speaking boundary — the High Seat's brief at the page open, a goal's conversation at its open —
     with ONE nudge and its reason, derived from the records by the page (`steward_cockpit/nudges.py`), never a
     model turn and never a write: a dated part due within three days in a goal he is not working in; an initiative
     that waits on him and is only on deck ("make it active?"); a Tier-1 goal untouched for a week, a Tier-2 for two
     ("put one of its cockpits on deck?"); a seed that reads like a goal ("make it one?"); a free moment with
     something on deck. Each carries the fact it read and one-click acts (make it active · put it on deck · make
     it a goal · open · not now). "Not now" is a receipt in `.ecgberht/nudges.json` under the Campaign that silences
     that nudge until its fact changes (the key names the kind, the subject and the fact); it has undo. Never while
     he types; never twice for the same fact; never more than one at a boundary. The steward's own turns do not
     repeat a nudge the page shows; they may act on it when he says so.
  10. **A proposal names its goal; one conversation (John, 2026-09-29, of the goal board: "This is what drives and
      disciplines the steward"; 2026-10-01: "is there some type of reset for the steward conversation … That should
      not be the case"; W5 of the active set).** A proposal names the goal it serves and the seat it sits in; work
      that is in no goal is said to be in none. The Campaign's steward holds ONE continuous conversation across the
      High Seat and the Campaign page: it stays awake through a quiet spell, a wake after a restart puts no greeting
      in the dialogue, and its first turn after a wake is the conversation's next turn — no pickup, no recap, no
      re-introduction, never a re-ask of what the record answers; a question that still waits on him is shown on the
      page, not repeated by the steward. A cockpit's steward keeps its wake summary.

## Face + Strip write authority

| Surface | Role | Write authority |
|---------|------|-----------------|
| **Face** | Human narrative / cold-start constitution | May rewrite north star, active effort and why-next; human-wait only in legacy unmanaged campaigns |
| **Strip** | Typed instrument heartbeat | Append-only instruments/receipts; reject silent in-place clock rewrite |
| **Proposal** | A correction set after an acceptance (2026-09-28) | Append-only `repair_proposal` event on the roadmap; applied ONLY by his `repair_resolve` (accepted) as receipted `step_set` events; never applied unattended |

**Face fields only (no depth/grasscatch jargon on Face):** north star · active effort · why next; legacy unmanaged human wait. Managed wait is a read-only projection of `pending_request`, never an authored Face field.
Markers: `schema/face-markers.json`. Template: `templates/ECGBERHT.md`.

**Strip locked fields (`ecgberht-strip-v0`):** phase · active_effort · human_wait · capacity `known|unknown` · negative_heartbeat · grasscatch · uncertainty_flags · tool_depth_cell · next_recommended · why_next; since 2026-09-28 also wait_ref · current_step_id · horizon_source_seq · horizon_focus (all projected from the instruments — `STRIP_CLOCK_FIELDS`). Receipt kinds: heartbeat · leave.  
Schema: `schema/strip.schema.json`. Templates: `templates/strip.json`, `templates/strip-fence.md`.

### Heal law (enforced in engine helpers)

| Rule | Meaning |
|------|---------|
| Face wins narrative | Human north-star / why-stakes / active-effort prose may be rewritten on Face |
| Strip wins clocks | Instruments/receipts are **append-only**; silent in-place clock rewrite is **rejected** |
| Crisis = explicit re-sync | `healResync({ explicit: true, … })` only — ambient chat cannot dual-write |
| Silence = negative-heartbeat | Do not invent “all clear”; record `negative_heartbeat` |
| Chat cannot invent truth | Claims must ground in Face or Strip surfaces |
| Fence/schema drift | Repair Face fence text from Strip projection; **never** silently rewrite Strip history |

Engine modules: `engine/write-authority.mjs`, `engine/heal.mjs`, `engine/face-strip.mjs`.

### Campaign Roadmap (TW1 — engine truth)

The Roadmap is engine truth via append-only events + a derived projection. Face prose is **never** the only step list.

| Surface | Rule |
|---------|------|
| `roadmap_events[]` | Append-only history (`step_create` · `step_set` · `status_flip` · `commission_bind` · `goal_flip` · `kickoff_proposal` · `kickoff_confirm` · … — the list is `ROADMAP_EVENT_KINDS`, version 9 since 2026-09-28, which added `reorder` (his act; receipted; folds the step's place), `repair_proposal` and `repair_resolve` (project-level; fold nothing)); prior entries never rewritten |
| `roadmap_projection` | **Derived-only** execution list (`id, name, status, done_when, waiting_on, commissioned_as, part, gate`) plus confirmed kickoff references (`component_ids, end_to_end_slice, kickoff_version, kickoff_proposal_hash`); direct writes rejected |
| Status flip | Requires a receipt (`who`/`why`) on the `status_flip` event — flip without receipt = refuse write / reject on validate |
| Silent rewrite | Stored projection that disagrees with the event fold → structured reject (`roadmap_silent_rewrite`); **heal** rebuilds projection from events (events untouched) |
| Face-only prose | `roadmap-show` / `status` return an **empty projection + honest gap** (`face_prose_only`) — steps are never invented from prose |

**Single writer path (TW3 hook):** durable operations use `appendRoadmapEventThroughSpine` (including `roadmap-propose`, `roadmap-set` and `refinement-update`); `appendRoadmapEvent` supplies the pure fold. TW3 job lifecycle (commission propose/confirm; `queued → running → done | failed | orphaned | reaped`) binds through this same writer: `commission_bind` attaches a step to a commissioned job and receipted `status_flip` records ordinary step changes. A managed slice reaches Done through its explicit current-presentation close or guarded completion after all current products are individually accepted; job completion cannot bypass that boundary. No dual-write, second store or UI-only state. Contract constant: `ROADMAP_SINGLE_WRITER`.

Statuses: `proposed | planned | active | waiting | done | parked`.  
Module: `engine/roadmap.mjs` · schema: `schema/roadmap.schema.json` · template: `templates/roadmap.json` · fixture: `fixtures/roadmap-minimal.json` · file: `roadmap.json` at project root.

### A1 discovery (no registry)

- Roots: CLI `--roots` and/or env `ECGBERHT_STRIP_ROOTS` (OS path separator).
- Per directory, first match wins: `strip.json`, else `ECGBERHT.md` Strip JSON fence.
- Scan: listed roots + **one level** of subdirs; ignore `node_modules` / `.git` / `vendor` / junk.
- Empty roots → structured empty result (not a crash).
- Module: `engine/discovery.mjs`.

### Strip-first rank

Portfolio `next`/`status` rank **Strip projections only**. Full Face only for top-k drill-in or heal.  
`capacity=unknown` → rank penalty + LITE-bias flag — **never silent green**.  
Anti-starvation: `negative_heartbeat`, `anti_starvation_age_days`. Module: `engine/rank.mjs`.

---

## Seating (Anchor prefs only)

- Resolve seats from Anchor model prefs: `coding_family` / `review_family` / `default_cli` (mirror: model prefs file under the Anchor data dir — never hardcode host home paths in engine logic).
- Map families to **subscription** drivers only (chatgpt-cli / claude / gemini-cli|agy / grok-cli).
- Stamp `cross_model` honestly when same-family.
- **Forbidden:** hardcoded ChatGPT/Claude/Gemini/Grok product model IDs in skill prose or engine; raw API-key HTTP paths for production seats.
- Module: `engine/seating.mjs`.

### Commission adapters (compose-only)

| Skill | Role |
|-------|------|
| researchPrime | Evidence research |
| Crucible | Plan forge |
| Foreman | Wave build |
| Gandalf | Deep adversarial read |
| Jumper | Ideation tournament |

- Spawn/handback contracts only: pass depth cell, active effort, receipt envelope + resolved seats.
- **Zero** in-process Shark Tank or Foreman wave loop inside Ecgberht.
- Handback must carry structured fields (`active_effort`, `why_next`, `grasscatch_why`, `tool_depth_why`, `human_wait`, `uncertainty_flags`) or `receipt-validate` fails.
- Module: `engine/commission.mjs`. Boundary canaries: `runBoundaryCanaries`.

---

## Non-goals (enforced)

- No edits to Anchor-release-v1.0 / public freeze tags  
- No OpenClaw substrate or multi-agent wallets  
- No full calendar/email OAuth connectors in this build  
- No default chat gateway tax on every turn  
- No replacing Anchor job_runner  
- No in-app chat personality product  
- No Family-Finances domain features  
- Harness product (if ever) is a separate Grasscatcher-scope product — not this engine  

### Grasscatcher ledger (W6 — permanent scope deferrals)

Distinct from campaign `soft-vet` / `grasscatch` verb receipts. The ledger freezes product non-goals so MVP scope cannot silently expand. Each item carries receipt shape (`deferred`, `grasscatch_why`, `suggested_later_owner`, `handback_shape`) and is **not** an MVP verb or engine surface.

| Deferred | Suggested later owner |
|----------|----------------------|
| OpenClaw harness product | separate-harness-product |
| calendar/email OAuth | connector-product |
| Anchor v1.0.x release edits | anchor-release-owners |
| default chat gateway | chat-product |
| Family-Finances domain | family-finances-project |
| Anchor 1.1 portfolio UI | anchor-1.1 |
| launch-tree merge | launch-orchestration |

- Fixture: `fixtures/grasscatcher-ledger.json`  
- Module: `engine/grasscatcher-ledger.mjs`  
- Strip labels: `strip.json` → `grasscatch`  

### Stage-2 freeze set + canary pack (W6 — enforced in code, prose moved)

Both are ENFORCED by `engine/stage2-freeze.mjs` + `engine/canary-pack.mjs` (fixtures:
`fixtures/stage2-freeze.json`); the descriptive tables live in `docs/BUILD-CANON.md`
(moved 2026-08-25 — they were context tax on every load; enforcement unchanged).

---

## Install / junction (Skill Foundry peers)

1. This package root **is** the skill root: `SKILL.md`, `templates/`, `schema/`, `fixtures/`, `bin/`, `engine/`, `package.json`.
2. Seat like peer Foundry skills: junction or symlink the folder as `ecgberht` into the host skills directory used by your agent host.
3. Engine CLI: `node bin/ecgberht.mjs <verb>` or install package bin `ecgberht`.
4. Tests: `node scripts/run-all-tests.mjs` (or `npm test`).
5. **Trio pin** for compose compatibility: commit **`77de811`** (see frozen `IMPLEMENTATION-PLAN.md`). Prefer committed trio behavior if a local dirty stage1 file is present.

---

## Layout

```
SKILL.md                 # this protocol
package.json             # name ecgberht + bin
bin/ecgberht.mjs         # CLI
engine/                  # verbs, face-strip, roadmap, brief, anchor-knowledge (read-only), dispatch, seating, commission, grasscatcher-ledger, canary-pack, stage2-freeze, verification-pack
templates/ECGBERHT.md    # Face scaffold
templates/strip.json     # Strip JSON stub
templates/strip-fence.md # dual-section fence stub
templates/roadmap.json   # Roadmap stub (append-only events + derived projection)
templates/verb-help/     # closed-list help
schema/                  # face markers, strip, receipt, roadmap
fixtures/                # strip-minimal, dispatch-table-seed, grasscatcher-ledger, stage2-freeze, roadmap-minimal
test/                    # unit suite (w1–w6)
scripts/run-all-tests.mjs
```

### Dispatch table (W4)

- Dimensions: phase × uncertainty × human_wait × cost → `LITE` | `FULL` | `SPIKE` | `commission` | `refuse`
- Defaults bias **LITE**; SPIKE for unknown data shape; FULL only when a cell says so
- refuse when `human_wait` blocks or out-of-scope; `capacity=unknown` → LITE bias flag (never silent FULL green)
- Human override of table outcome requires structured receipt: who / when / why / from→to
- Module: `engine/dispatch-table.mjs` · fixture: `fixtures/dispatch-table-seed.json`

---

## When to use / when NOT to use

- **Use when:** resume a project campaign, rank what-next, soft-vet an idea, choose tool depth before commissioning a slice skill, stand up Face+Strip.
- **Do NOT use when:** you need an actual plan forge (Crucible), wave build (Foreman), deep adversarial read (Gandalf), ideation tournament (Jumper), or evidence research (researchPrime) — **commission** those; do not reimplement them here.
