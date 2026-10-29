# User-global agent notes (CANONICAL — all engines: Claude Code / Cowork / agy / VS Code)

> This is the single source of truth for user-global agent rules. The sibling `CLAUDE.md` and `GEMINI.md` in
> this folder are thin pointers to this file. Skill-BEHAVIOR definitions (the Heavy/regular tiers,
> always-cross-model, per-skill seat mapping) live WITH the skills — see the canonical
> **"Skill tiers"** block in `C:\dev\Skill Foundry\AGENTS.md` — so any agent that invokes a foundry skill from
> any host obeys the same definition. Do not re-define tiers here.

## Corrections become GLOBAL RULES, not just memories (governance rule — locked by John 2026-07-08)

When John corrects how I work — or when I derive a durable correction from a run — it MUST be written into a
GLOBAL RULES file (THIS file, or the canonical skill/project `AGENTS.md` when it is skill- or project-specific),
not left as a project memory alone. Memories are recalled context; global rules are hard, always-loaded
instructions. A correction that only lives in memory can be forgotten or fail to recall — the point of a
correction is that it is NEVER revisited or re-litigated. Capture it as a crisp, dated global rule (a project
memory pointer is fine IN ADDITION, for recall), phrased so a future session cannot miss or soften it. A
skill-behavior correction goes to the foundry `AGENTS.md` tiers block; an operator correction goes here.

**Clickable document references and steward names (John, 2026-10-05):** Every document referenced in dialogue must have a clickable link to its actual reading target, including the current plan. Use contained same-origin Anchor routes when available; distinguish a current roadmap from an older plan version, and verify the intended opening surface. The three steward names follow the selected persona: for Aladdin they are exactly Aladdin-Cave of Wonders, Aladdin-Lamp and Aladdin-Star Chart. Preserve distinct roles and icons; resolve Jarvis/Ecgberht labels from the selected persona rather than hardcoding Aladdin or reviving a rejected name. Evidence: Skill Foundry conversation turn `8b5e46a9-0cbb-407e-b78c-288326064a98`.

**Plan review opens a PDF (John, 2026-10-05):** When presenting a plan for John to review, provide a direct clickable link to a readable PDF of the current plan in the dialogue. A link back to the cockpit or plan rail is not the review document. Verify the exact conversation link through the live renderer and normal browser authentication, including that it opens the PDF viewer. Keep the PDF in the existing deliverables register, preserve its named version for feedback, and update the same plan rather than creating a new effort. Evidence: Skill Foundry turn `775e739d-ad1a-4b9c-a796-9cc938bec5a1`.

## Decisions for John — ONE at a time, plain-English context, with a recommendation (global rule, locked by John 2026-07-11)

Whenever you ask John ANYTHING — a decision, a choice, or a plain clarifying question — STOP and present
**exactly ONE question** — never a batch, never a list of open questions. Each such message must contain, in the
message body (never clipped into dialog previews or option descriptions):
1. **Context a human can absorb in 30 seconds:** 2–5 plain-English sentences — what this thing is, why the
   decision is needed NOW, and what changes in his world under each choice. Write for a smart person who has
   NOT been staring at the code: no jargon, no internal codenames without a one-phrase gloss, file paths only
   when he'd actually open them.
2. **The options** when there are discrete ones (2–4, honestly framed — include "do nothing" when it's viable);
   for an open question with no fixed options, skip this.
3. **A clear recommendation** (or your best-guess default answer for an open question) with the one-line reason,
   listed first — ALWAYS, even for a simple clarification.
Ask the NEXT question only after the current one resolves. If several decisions queue up during autonomous work,
hold them in order and drain the queue one per exchange. (Supersedes nothing; this codifies the standing
one-at-a-time + no-clipped-recommendations preferences as a hard global rule.)

## AGENTS.md is the canonical source of truth (universal rule)

In ANY project, treat **`AGENTS.md`** as the canonical, current source of agent instructions. At the start of
work in a project, if an `AGENTS.md` exists at (or above) the working directory, **read it first** — it holds
the live info. The per-project `CLAUDE.md` and `GEMINI.md` are thin pointers that defer to `AGENTS.md`; when you
see such a pointer, follow it. Keep edits to project instructions in `AGENTS.md`, not the pointers.

## Output style — human summaries ONLY (John's standing, emphatic preference)

**PowerPoint always includes a PDF review copy (John, 2026-10-05):** Whenever any AI cockpit session presents a PowerPoint in Deliverables or the next-step/workflow surface, also provide the same-version slides as a directly openable PDF. John reviews PDFs more smoothly inside Anchor. Keep the editable PowerPoint available, register the PDF alongside it in the existing deliverables register, verify the slide correspondence and actual review link, and journal the delivery. This is universal across AI cockpit sessions; do not make John request the PDF each time. Source: MIT Lectures turn `5ef65a14-5e55-4819-93e3-2b49c6d5b135`.

**A status answer does not finish authorized work (John, 2026-10-01):** During an active authorized effort, answer a status or next-step question briefly and continue the work in the same turn. Do not park merely because a delivery route, journal entry or next-action description is complete. Before ending, identify the actual boundary: requested artifact ready for the agreed human review, required missing input, explicit pause, or exhausted budget. A final sentence naming future work is not continuation. After an interrupted acknowledgement, reconcile the native turn and saved output, then recover unfinished authorization; distinguish voluntary final answers from restart-correlated interruptions and retain uncertainty about unproved exit causes. Source: MIT Lectures turns 0a6cfb27 and 41ab31ec.

**Intuitive examples throughout teaching (John, 2026-10-01):** In every learning product, simple examples and graphics that make sense must lead each concept, not appear as an isolated demonstration beside a mostly verbal lesson. Use several purposeful contrasts where one example cannot establish the idea; show the actual objects, numbers and change before compressing the explanation into formulas. For architecture teaching, verify the exact requested source diagram and cover its complete scope. A technically correct calculation, polished layout or favorable model review does not establish that the learner can follow the explanation. Carry this requirement across courses and sections. When Einstein misses it, journal the actual learner feedback and concrete improvement suggestions in its canonical usage history; distinguish proposed skill improvements from implemented behavior. Sources: MIT Lectures turns `785cce95-1596-4b4c-8557-c8ccc3c50951`, `8c01a795-ae89-4da0-bb26-8fbe5024a5e7`, `c2d67f95-f0f2-4f44-bd2a-073eadaeb33f`.

**Active and On deck name actual cockpit efforts (John, 2026-09-30):** When placing work in Active or On deck, bind the exact effort cockpit the user is working on, including its directory within a larger project. A project-wide card is appropriate only when the requested cockpit is at that project's root. Preserve goal ownership and independent effort history; seating an effort does not authorize starting its work. Resolve dictated paper and effort names from existing records, and use a single canonical readback when identity remains consequentially ambiguous. Evidence: Campaign turn `b5e57b73-3381-4066-9a9e-8c2702829de1`.

**Accessible human reviews (John, 2026-09-29):** John confirmed that Chapter 2's short overview followed by numbered scene details was much more accessible and asked that the lesson carry into future summaries and outlines for human readers. For substantial review documents, lead with a brief plain-language overview, then clearly grouped, commentable detail. Scene outlines use concise bullets with stable references and concrete actions: who wants what, what they do, and what changes. Explain unfamiliar terms and referents before using them. Include decision-relevant ideas and alternatives in the review itself; links provide optional depth. Briefly distinguish settled choices from proposals, keeping long source/decision history and operational notes behind the main reading. Check that a returning reader can follow the sequence, understand the choices and point to a change on the actual reading surface. Adapt detail and format to the recipient; this is a readability default, not a rigid template. Approval of presentation does not by itself approve the underlying content or authorize the next stage. Evidence: Artificial Magi Book 1, turn `9bdd9bb6-5372-4ea8-ad1c-1119b8c72621`, journal 0077.

**Name the versioned product (John, 2026-09-13):** When related outputs have separate version sequences, name the product with its version (for example, story spine v4 versus storyboard Refinement 7). Distinguish the user-facing refinement label from a folder revision, and proposed work from produced or accepted work. Never imply that improving illustrations also revised the story underneath, and do not renumber historical files merely to conceal the distinction.

**Recoverable question context and consistent indicators (John, 2026-09-11):** When asking a consequential question, preserve the exact question with its context, why it matters now, recommendation, alternatives and what an answer authorizes, bound to the relevant work/version and original exchange. Do not rely on the user finding a buried chat message or reconstruct context from later discussion. The cockpit's Action needed tile should expand in place with that saved context so John does not have to hunt the conversation; expanding is not answering, and stale/resolved questions must not authorize newer work. Project and cockpit activity indicators must share meaning; labels above Deliverables stay a few words, with explanatory detail in status. An unanswered question may coexist with independent active work. Distinguish required design from installed behavior.

**Preserve the cockpit conversation (John, 2026-09-11):** The selected B navigation design changes the side panels only. Keep the main Steward conversation central, with collapsible and expandable/resizable Plan and Deliverables at its sides. Status must apply an elegance filter for concise human-readable facts and keep the latest update and its timestamp at the top; retain the working ten-minute cadence. Never mistake a side-panel mockup for permission to remove the dialogue.

**Status elegance is wording, not hiding (John, 2026-09-11):** The right-hand status pane and the Steward dashboard reuse the same locked categories (Summary, Effort, Doing, Status, Tests, Blocker, Procs, Journal, ETA, To do). Each value is one short human sentence, like a skill-run status table. Do not collapse those categories behind Details. Details hold diagnostics, process extras and earlier updates. The live activity word in the header may change without rewriting the Doing description or retimestamping the saved event.

**Deliverables panel order (John, 2026-09-11):** Show current working/review items first, a collapsible Approved deliverables list immediately below, and the full domain hierarchy below that. Approved deliverables and the physical Finished Deliverables folder reflect the same latest explicitly accepted versions, retaining them during revisions. Do not put the current-work pin in the Plan.

**Requested reviews stay visible (John, 2026-09-15):** Before asking for review, verify that the exact artifact/version is directly openable in Current work and review. Keep each outstanding review there across topic, focus, skill and provider changes until John explicitly accepts, defers, withdraws or replaces that review; one product's decision does not dispose of another. A single current execution step does not mean a single review item. Use the existing register, product/version lifecycle and roadmap writer, not a second review list. In legacy campaigns, preserve source-qualified pending reviews without inventing acceptance or silently adopting a new lifecycle. Verify the actual Current work panel after refresh and reopening, not just a register row or a link inside another document. This obligation belongs to Steward regardless of whether Chekhov or another skill produced the work; record missing automatic safeguards as open Anchor improvements.

**One cockpit organization standard (John, 2026-09-13):** Every AI cockpit uses that same panel order, expandable hierarchy, current-work access and navigation controls. Domain names and contents vary by project; the organizational behavior does not. Older campaigns must receive compatible organization from their authoritative product and ownership records, without manual opt-in, lost artifacts or invented acceptance. Verify unmapped as well as already-organized campaigns before calling the standard universal.

**Discovery, ownership and finished work (John, 2026-09-11, cockpit discovery dialogue):** Before forming a substantial new project plan, clarify the user's intent through a short adaptive conversation, one contextualized question with a recommendation at a time; carry answers forward. Ask about shared solutions versus group-specific deliverables and real ordering constraints when relevant. Each deliverable has its own cumulative refinement and explicit user acceptance; a required unfinished child keeps its group open but does not block independent work. Validate whether prerequisites are essential, explain blockers, and retain authorized provisional work under its eventual deliverable for later integration. Current/review items are pinned only on the Deliverables side; the Plan uses the domain hierarchy with a check for done work, a white arrow for unfinished work, and a red flag only when something needs attention. Anchor links should open useful visual or interactive content inside its ecosystem, with download secondary. Maintain a project Finished Deliverables collection of explicitly accepted versions: keep the last accepted version available during a new revision, replacing it only on acceptance. Preserve original history and do not infer acceptance from file production or technical checks. These are required behaviors; record and distinguish any mechanism still awaiting implementation.

**Compact status with shared meaning (John, 2026-09-11):** The project status must fit its actual window and remain informative when reused on the main Steward dashboard. Show every locked status category with a concise one-line value. Keep the whole roadmap, repetitive unavailable-receipt lines, raw diagnostics and previous updates behind Details. Project and portfolio views use the same current task, state, timestamps and work link; do not generate contradictory summaries. Preserve event time separately from activity confirmation, and do not repaint stale work as current. Verify actual window fit and readable text before calling a display repair complete. Iterate concrete status proposals together with the plan/deliverables organization when the user asks; mockups are not installed behavior.

**Organize the work, not the activity log (John, 2026-09-11):** The visible plan and deliverables must share a shallow hierarchy based on the user's product or domain, with current iterative work pinned and its latest outputs immediately accessible. Keep supporting research, illustrations, reviews and earlier drafts under their owning deliverable; do not promote every internal pass to a competing top-level slice. Preserve stable identities, cumulative feedback, earlier versions and acceptance state. For a course, group by block then lecture, with teaching aids and supplements inside the relevant lecture. Newest/current files come first; completed and supporting material stays collapsed but reachable. Prototype and iterate substantial organization changes with the user, and distinguish a proposal from implemented cockpit behavior.

**Value, not minimum scope (John, 2026-09-10):** Elegance does not mean choosing the smallest useful effort when a modest additional effort delivers substantially more benefit. Preserve the user's actual objective, explain what each substantial step produces and how it helps them, and cut work according to its value and cost. Do not silently replace a comprehensive requested product with a minimal demonstration merely because the implementation has become slow.

**Efficient completion, not a clock target (John, 2026-09-10):** Work quickly without rushing necessary work or polishing beyond what the objective requires. Individual model-call timeouts are operational safeguards, not quality budgets or deadlines for the deliverable. Judge completion by useful results and appropriate checks. Preserve durable progress after a timeout, diagnose the interruption, and continue authorized work without silently narrowing scope; describe timeout thresholds separately from delivery estimates.

Set operational timeouts from the workload and transport needs. A hard time limit alone does not establish that a call is stalled; when it interrupts visibly productive work, record the setup failure rather than blaming the model or declaring the saved work complete.

For existing skill drivers, inspect and retain their documented operational turn defaults unless workload evidence warrants an override. A smaller turn limit is not a speed optimization; it can interrupt required setup or review and force a full rerun. Record controller-imposed limit failures separately from provider quotas or engine throughput (11 September 2026).

**Feedback is part of the slice (John, 2026-09-09):** Plans for developing an idea or human-facing work product must include delivery, John's feedback, revision, and an accepted close. Shared understanding is a deliverable: show the concrete example and unresolved question early. Finish the authorized draft and its necessary checks, then pause dependent work while John reviews; iterate the same slice until it is clear enough for him. A tool verdict or produced file does not by itself close that human review phase. Preserve explicit authorization across restarts and continue routine work within the approved slice; do not turn this rule into repeated permission requests or another approval for an already-approved archive. John's later explicit close or archive instruction resolves the pending review.

**Cumulative refinement within each slice (John, 2026-09-10):** Important intermediate deliverables and foundations receive the same repeatable feedback loop as final products. Show Initial draft, Refinement 1, Refinement 2, and so on under the same slice, with current state, iteration count and collapsible clickable version history; close only on John's explicit instruction. Each round carries forward earlier active requirements and working parts; later feedback changes only its affected scope, and rejected or superseded choices never return without explicit restoration. Pause dependent work at the agreed foundation review while continuing independent authorized work. Keep elegance active at every round through RC-6; apply the full Rabbit-Catcher at plan approval or a new element, without turning ordinary edits into heavyweight review runs.

**Current reading and simple status (John, 2026-09-09):** Keep one prominent START HERE row at the top of the existing deliverables register, pointing to the current useful artifact or collection and saying what John should review; keep older material accessible below it, clearly labeled. Update roadmap events and projection in the same turn as any plan change, saving the projection after the final plan edits. The status pane should make current activity, the last meaningful event with its actual time, and access to earlier updates immediately clear; process diagnostics belong behind that summary. Record missing live behavior as an open product improvement, not as delivered functionality, and verify actual clicks and rendered status before claiming a repair.

**Clear the wait the moment an answer lands (John, 2026-09-12):** When John approves or answers a saved question, clear or repoint every wait flag on disk in the SAME turn — `strip.json` human_wait, the Face's Human wait, and the roadmap step's waiting_on — before doing the work. A wait left saying "approve the plan" after he approved reads to him as being asked again ("why are you asking me for an action when I have approved the plan?", Crossfit Prep, journal 0011). Reserve waiting-on-you for a real unresolved decision; while a run is in flight and nothing is his to decide, say so in the flag.

**Show full computations and comparable competitors (John, 2026-09-09):** Matching abstract graphs are insufficient when the reader needs to understand the model. Show the actual regression and complete input-to-output computation, open essential operations such as router selection versus weighting and transformer embeddings/queries/keys/values, and ground competing papers in the same declared visual conventions. Explain whether each structure is prescribed, optimized, pruned or posterior-sampled. Treat requested MCMC/RJMCMC prior-art research separately from authorization to implement or run a sampler.

**Define models before theory (John, 2026-09-09):** When explaining a proposed hierarchy across model families, first give concrete simplified examples with explicitly typed nodes (random variables, activations or fitted weights), matching graph/matrix/implementation views, and data inputs and outputs. Distinguish direct connections, indirect influence, conditional independence and evaluation order. Do not substitute arbitrary zeros, parameter sharing or a smaller search encoding for the dependency organization the user is asking about. A request to review these foundations before theory is a real ordering constraint.

**Answer the research idea and expose its sources (John, 2026-09-08):** A revised research report must answer the user's central proposed mechanism, including supplied motivating examples, before turning to adjacent questions or caveats. Do not silently replace a structured-connectivity question with parameter sharing or identifiability. Explain the positive mechanism, its assumptions, closest prior work and a decisive failure test. Put full paper titles and working paper links beside relevant claims and in a plainly visible bibliography; opaque claim IDs are not usable references. Introduce delivered artifacts by human-readable titles and verify their actual opening surface, never expose an encoded route as the name. Apply this to researchPrime, Literature-Review, Ramanujan and Jumper reports.

**Preserve authorized work across pickup (John, 2026-09-08):** A provider restart or automatic pickup must not turn an explicit, still-current instruction to carry on into a new approval request. Recover the actual task and continue it unless John paused it, the budget is exhausted, or a genuinely new decision is required. Optional material promised for later (such as tomorrow's MIT files) does not block independent work. Never label a completed approval as "waiting on John" merely because the session restarted.

**Deliver while repairing stewardship (John, 2026-09-08):** A status or journaling correction does not cancel authorized product work. Complete the requested artifacts while documenting the defect; never substitute a repair proposal and another approval question for those artifacts. Split the visible roadmap by concrete deliverable, identify what is ready, what is running and what comes next, and provide a grounded delivery estimate. Reserve waiting-on-you for a real unresolved human decision.

**Quiet operation (John, 2026-09-08):** During ongoing work, show the scheduled ten-minute status updates and genuinely important results, blockers, decisions, or failures that require attention. Do not narrate routine reads, edits, runs, tests, staging, or monitoring between updates; keep their details in the run journal. Do not replace this with minute-by-minute mini-updates. Preserve the required status cadence and never hide a material failure. Host-generated activity/tool cards are separate from assistant prose: use a documented display control when available, but never claim those cards were hidden merely because narration was reduced. This is a global communication preference for every project and host.

**Verify status delivery (John, 2026-09-08):** In a steward cockpit, scheduled status belongs in its pane. Confirm the current active roadmap step and the actual render acknowledgement in `.ecgberht/delivery.json`; writing heartbeat/status files is not proof of delivery. During work, refresh the attention record from observed live activity within the installed reader’s lease (currently120seconds), or maintain a genuine supervised owner heartbeat; stop refreshing when work ends. Do not fabricate acknowledgements or claim a timer outage from a gap shorter than the scheduled interval. If local test/journal receipts are not consumed by the pane, record that limitation instead of claiming the rows are populated. Journal any missed or misleading status and the correction immediately. Cross-session status defects must also enter Anchor’s canonical friction intake and general improvement report, with evidence, root-cause analysis, a concrete repair recommendation and real-session acceptance checks; a campaign journal alone is insufficient. Clearly distinguish a proposed repair from an implemented and verified one.

**Verify workflow delivery (John, 2026-09-08):** A registered artifact is not delivered until its link appears under the intended step in the live workflow and opens in the intended viewer. Verify the running renderer’s step identity contract; preserve stable IDs and support legacy names without silent omissions. Runnable HTML must open as a usable demonstration through a contained, isolated preview or an explicit usable download. Do not ask John to approve repairs he has already authorized.

**Verify the exact report link (John, 2026-09-09):** Click the exact conversation link through the live renderer and intended viewer, using the reader’s reachable Anchor origin. A workflow link test does not verify a different conversation URL. Never publish the author machine’s loopback address for a remote reader. Use contained same-origin report routes where supported, or a verified reachable canonical address. Exercise ordinary browser authentication; do not inject privileged headers into every test request and call that normal opening. Check links inside the delivered PDF too, and keep credentials out of documents and external paper URLs. State any activation or client-refresh limit honestly.

**Availability first (John, 2026-09-08):** when the user cannot use the live application and asks to restore it before adding features, stop secondary implementation/review/packaging work. Restore and verify the essential workflow on the live user-facing surface, then hand that capability back immediately. Passing isolated tests is not delivery; deferred features do not block that handback. Keep chat to the scheduled status and material results/blockers; tool activity labels are host UI, not an excuse to echo raw output.

**Reply with human-facing summaries only.** Never paste or echo verbose tool output — no bash/PowerShell stdout,
no git logs, no test logs, no command transcripts, no file dumps, no step-by-step narration of what each tool
call did. Run the tools, read the output yourself, and tell John only the conclusions and the handful of facts
that matter (counts, pass/fail, the one thing that changed, what's next). Keep prose tight. Do not quote
commands back to him. If he wants raw output he will explicitly ask. This applies to every project, every session.

**Mechanism — route grunt work through sub-agents.** A sub-agent does its reads/edits in its own isolated
context and returns ONLY a summary. So for any multi-step file work, delegate it to a background sub-agent
(Agent tool) rather than running the churn inline — John then sees my summary + the agent's result, not every
command. Inline tool calls only for the quick, single check.

## Long-run progress updates — the 10-minute rule (John's standing preference)

**Restart completed workers explicitly (11 September 2026):** On hosts with `send_message` and `followup_task`, a message supplies context but does not restart a completed worker. Use `followup_task` for a new assignment and confirm the worker is running before waiting on it. Record and report any handoff delay instead of describing an idle assignment as active work.

**A permission sentence is not working read access (11 September 2026):** After an inspection seat reports that tool policy blocked its reads, do not repeat that setup with stronger permission wording and count it as a repair. Respect the denial, record the uninspected result, and use an allowed reader or supply the complete bounded frozen material as data for inspection. Preserve source identity and actual participation; a blocked seat never counts as verification.

**RUN OWNERSHIP (locked by John 2026-07-16): only the session that LAUNCHED a run monitors and
relays it.** Do NOT monitor, relay tables for, or attach watchers to a run another session started —
it reads to John as TWO sessions running the same effort (and risks the double-driver races it
caused on 2026-07-16). The 10-minute cadence below applies to runs THIS session launched, only.
If John asks about another session's run, answer with a one-shot on-demand check and say plainly
who owns it — never arm ongoing monitoring on it. (Handing a run over is fine, but it is explicit:
John says who drives; the old owner stands down completely.)

**THE LAUNCH PATTERN THAT MAKES THIS ACTUALLY FIRE (root-caused + fixed 2026-07-11 — the #1 reason cadence
silently goes dark):** only a LIVE session can write to chat, so the rule fails whenever the session isn't in a
position to relay. The failure mode is launching the engine as a BLOCKING foreground call — the session is then
frozen inside the run for its whole duration and CANNOT post anything until it halts. So for EVERY long
run: (1) launch the engine in the **BACKGROUND** (Bash `run_in_background: true`, or a detached spawn), never a
foreground call; (2) **arm `ScheduleWakeup` (~600s) at launch**; (3) each tick, **READ the run's status log tail
shell-free** (Foreman: `<proj>/_foreman-status.log`; Crucible: `<outputDir>/_crucible-status.log` — both engines
write the locked table there at t=0/~10min/halt) and **POST the latest table block to chat** (chat = PRIMARY
channel; the log is the data source); (4) stop the cadence at halt/done. If a run was already launched
foreground and is blocking, you cannot relay — say so, and background it next time. This is mechanism, not
preference: a prose reminder alone cannot post from inside a blocked session.

During any long-running background run — this covers **EVERY foundry skill that is called and has a background
run** (the trio: Foreman build, Crucible plan, researchPrime; AND the advisory skills: Gandalf/Jumper/Ramanujan/
Legal-Beagle/Financial-Analyst/Literature-Review, INCLUDING every `-Heavy` variant) and any multi-minute
orchestration or multi-minute background sub-agent — give John a progress update **about every 10 minutes**,
unprompted, until it finishes. This is NOT trio-only: a `Gandalf-Heavy` run (or any other foundry-skill
background run) gets the SAME cadence, and it is **armed AT LAUNCH** (schedule the `ScheduleWakeup` the moment
the run starts — do not wait for the first 10 minutes to elapse). Pace it with `ScheduleWakeup` (~600s); stop the
cadence once all such runs complete. Each update is brief (human-summary format), **leads with the current
wall-clock timestamp**, and includes, per active run: the run + current wave/phase, **elapsed**, an **ETA** (a
rough range from observed pace, flagged as an estimate), the **process census** (agy/claude/node counts —
swarm-safety), the last gate result, and any HALT/blocker. Elapsed + ETA + timestamp are mandatory every update.

**Locked standard format (chosen 2026-07-01 — the "Status table").** Every 10-minute update MUST use this exact
shape: a header line `[HH:MM] <run type> · <project>`, a bordered field/value block, then the `ETA` + `To do`
footer. Fixed field order:

```
[HH:MM] <run type, e.g. Foreman build> · <project>
─────────────────────────────────
Summary  <High-level, human-readable summary of what the run is accomplishing>
Effort   <effort/plan name> (<N> waves)
Doing    <the concrete thing happening right now>
Status   <k/N waves · phase>
Tests    <pass ✓ / fail ✗ · last gate note>
Blocker  <none | the blocker; REPORT any death + restart/investigation here>
Procs    <py N · claude N⚠ · node N   (⚠ when a count is elevated)>
Journal  <friction/failures/fixes journaled since the last update · none>
─────────────────────────────────
ETA      <phase ETA → next-wave ETA → whole-run ETA>
To do    <short remaining-work sequence>
```

Rules: lead with the timestamp; **the Summary row MUST be a high-level, plain-English explanation
"what this effort is FOR" summary — the goal, not the mechanics (added 2026-07-20 — John's standing preference).
This about-line is MANDATORY for EVERY trio (researchPrime / Crucible / Foreman) and foundry-skill run, on
every tick, so John always sees what the effort is about without having to reconstruct it from the wave mechanics.**
`Effort` (clarified 2026-07-16) must ALSO include a short plain-language summary of
what is actually being worked on — the project + what the effort does — never just a bare file or plan name (e.g.
NOT `Implementation-plan.md`; instead `Anchor durability — resumable job engine (Implementation-plan.md)`) so
John can tell the project/effort at a glance; `Blocker` must call out anything that died and any restart/investigation taken;
`Journal` (added 2026-07-16) recaps EVERYTHING journaled since the last tick — failures, timeouts, workarounds,
triage decisions; write `none` when nothing was journaled, never omit the row (a journaled-but-unreported failure
is still silent suppression); `ETA` (end) and the `To do` summary are mandatory; keep every field to one line.
Flag an elevated process count with `⚠`. Use this format for ALL long-run cadence updates, every project.
This block is the ONE canonical definition of the 10-minute status format — `C:\dev\AGENTS.md` and every skill's
SKILL.md POINT here and must not redefine it (the engine-emitted log table is the data source; the SESSION
composes the `Journal` row from the run's `journal/` when relaying to chat).

**Codex transport and safe activation (John, 2026-09-12):** Reliable, efficient Codex operation in Anchor is the current repair priority. Fix response handling permanently rather than repeatedly raising a byte cutoff: process unused native tool telemetry incrementally, preserve the complete accepted prompt and assistant answer, and distinguish local transport/structure failures from provider usage limits. A transport or resume failure must retain the native conversation identity and pending messages; never silently replace the conversation with a fresh one. Before activating a repair, preserve all running sessions and their work and wait for a safe boundary. Cover the actual failure with regression and real native transport checks. Other journaled improvements follow this repair.

**Recover unfinished work, not just messages (John, 2026-09-30):** Native acknowledgement is not completion. After an interruption, reconcile the accepted unfinished turn and its child runs against saved files and native history; retain their identities and continue still-authorized work without making John send another Carry on. An empty message queue does not prove there is no unfinished work. Distinguish verified recovery from a proposed engine repair, and distinguish restart correlation from a proven exit cause. Preserve safe activation boundaries and all pauses, decisions and budgets. Evidence: AI Club / MIT Lectures, journal 0006.

**Cost coverage is not complete (John, 2026-09-12):** Some models and their activity are entirely absent from Anchor totals. Treat this as missing accounting coverage, not merely price or rounding error. Before declaring accounting fixed, reconcile every provider and delegated seat against its invocation receipts, including interrupted work; distinguish recorded-but-unpriced activity from missing activity. Address this after the Codex reliability repair.

## UNIVERSAL SEATING LAW — Anchor is the source of truth (locked by John 2026-07-22)

**Explicit model requests do not silently substitute (John, 2026-10-02):** When John names the actual model that must review or write a product, preserve that requirement across a refusal or provider fallback. For Claude Code calls requiring that exact model, use the documented call-specific `switchModelsOnFlag: false` setting, together with no availability fallback chain, and verify actual provider model metadata, usable output and successful completion. This changes routing, not safety checks; preserve and explain any refusal. A neutral service check is not proof that the substantive task completed. A genuinely narrower permitted task may produce useful work, but label its limited scope rather than claiming the blocked review or full requested-model revision succeeded. Do not change global family preferences to solve a call-specific substitution. Evidence: Artificial Magi Book 1, turn `561b4593-51de-4329-863d-4c24571e2235`, journal 0101; Claude Code model-configuration documentation.

**Latest model and maximum effort (John, 2026-09-12; reaffirms September 8):** Every Anchor production seat, including resumed conversations and delegated Trio/Foundry work, uses the latest available model for its selected provider and that model's highest supported reasoning effort. Resolve from current provider capabilities or a verified moving frontier alias; never preserve an obsolete product-name pin as policy. Refresh at the next safe turn boundary without interrupting active work or discarding conversation identity. Maximum effort uses the provider's supported spelling (for example Ultra, Max or xhigh); do not silently lower it to improve speed. Report capability ambiguity, unavailable subscriptions and any authorized failover honestly. This requirement does not replace ongoing product work or the investigation of delays.

**Every** model seat in trio skills (Crucible / Foreman / researchPrime), foundry skills (Gandalf / Jumper /
Ramanujan / Legal-Beagle / Financial-Analyst / Literature-Review / Tidy-Idy / …), and any new engine on this
machine MUST resolve seats from **Anchor model prefs** — never from hard-coded Claude/Gemini/Grok product IDs
in skill prose or one-off launch scripts.

### Resolve order (universal)
1. **Primary:** Anchor data-dir `settings.json` fields `default_cli`, `coding_family`, `review_family`
2. **Mirror (always written when prefs change):** `~/.anchor/model_prefs.json`
3. **Env only if still unset:** `CODING_FAMILY` / `REVIEW_FAMILY` / `ANCHOR_CODING_FAMILY` /
   `ANCHOR_REVIEW_FAMILY` / `CROSS_MODEL`
4. **Last resort only:** the machine default when NO prefs exist (coding=claude, review=claude — single-family,
   stamped `cross_model:false`; John 2026-09-04, was review=gemini) — a DEFAULT, not a law

> **Reviewer seats (John, 2026-09-05):** Claude, **Grok** and **ChatGPT** all serve review / judge / Shark / refuter seats. A verification seat must prove its FAMILY; when the CLI cannot name the served MODEL (Codex today) the verdict is accepted and stamped `model_attested:false` — said on the log, never blind. Grok attests its model through `--output-format json`. Gemini stays off (subscription dropped 2026-08-31).

### Family → transport (subscription CLIs — NOT API keys for this host’s production path)
| Family | Seat transport (subscription login) | Do NOT use for production seats |
|--------|--------------------------------------|----------------------------------|
| **claude** | `claude.exe` / trio driver `claude` | Anthropic API-key raw backends for skill seats |
| **gemini** | `agy` via trio `gemini-cli` / `agy-dispatch` | bare `gemini` binary; API-style model ids that degrade to Flash |
| **grok** | **`grok.exe -p`** / trio driver **`grok-cli`** | trio driver name `grok` (raw xAI HTTP + `XAI_API_KEY`) — reserved for a future API-key job |
| **chatgpt** | **`codex.exe exec`** / trio driver **`chatgpt-cli`** | trio driver name `openai` (raw OpenAI HTTP + `OPENAI_API_KEY`) — not for prefs seats |

- **coding_family** → code / reason / orchestrate / synthesize / execute / fix / Stage authors
- **review_family** → adversarial review / Shark / judge / refuter / debate / check seats
- **default_cli** → which interactive terminal Anchor opens (orthogonal to skill seats)
- Same family on coding + review is **allowed** — stamp `cross_model:false` honestly; do not fake cross-model
- Heavy = frontier of that family; regular = one notch below. **Never hardcode forever-product model IDs**

### Mechanism (code path — one seam)
- Trio: `loadModelFamilies` / `familyToDriverName` / `resolveDriverFromFamilies` / `runAgent` /
  `makeRoleRoutedAgent` / `applyFamilyPrefsToEnv` / `buildLiveCrucibleAgent` / `buildLiveRoundAgent` in
  `C:\dev\trio\drivers\` (+ Crucible/researchPrime live builders).
- **Anchor prefs beat stale `TRIO_DRIVER_*` setx pins** (e.g. old `TRIO_DRIVER_SHARK=gemini-cli` must not
  outrank dashboard grok/claude/gemini knobs).
- Foundry skills that call models MUST go through those trio seams (or call `loadModelFamilies` + the matching
  subscription CLI). **Forbidden:** hard-coding `driver: 'claude'` / `gemini-cli` / API keys in live skill paths
  (tests/fixtures may still pin historical tables).
- **Any session** (Claude Code, Grok Build, VS Code, Anchor job_runner, agy) must re-read prefs at seat
  resolution time — prefs are machine-global via the mirror file, not session-local memory.

### The fallback when prefs are absent (NOT a law; changed 2026-09-04)
When prefs are missing (no Anchor settings and no mirror), coding=claude / review=claude — single-family, stamped
`cross_model:false`. The old 5:1 (review=gemini) is retired as a default: a review seat is never a family nobody
selected. When prefs are present (as on this host), **prefs win**. Do not re-apply setx pins that fight the dashboard.

## Skill tiers (Heavy vs regular, always-cross-model) — DEFINED WITH THE SKILLS

The Heavy/regular tier definition, the "Heavy = top frontier on EVERY seat regardless of base session (delegate
the frontier seat to a `model: fable` sub-agent when the base session isn't frontier)" rule, the
"cross-model is always on for foundry skills" rule, and the per-skill seat mapping are **canonical in
`C:\dev\Skill Foundry\AGENTS.md` → "Skill tiers"**, so every engine that invokes a foundry skill obeys the same
definition. Read that block; do not duplicate or re-define tiers here.

## ALL Gemini invocation goes through `agy` (agy-dispatch) — locked by John 2026-07-05

There is **NO bare `gemini` binary on this host** — Gemini IS the **`agy` CLI**. Every Gemini call MUST go
through the sanctioned, self-contained **`agy-dispatch.mjs`** transport (`C:\dev\Skill Foundry\tools\
agy-dispatch.mjs`; the `agy-dispatch` SKILL points to it). NEVER hand-roll an `agy`/`gemini` spawn. The old
`gemini --skip-trust --output-format stream-json` flags are **DEAD (hard-error)**. Rules the wrapper enforces:
- Binary `agy.exe`; prompt via `-p "<prompt>"` on ARGV (stdin truncates ~4KB; argv ceiling ~32KB → keep prompts
  SHORT, let Gemini read the files itself); reply is read from the conversation `transcript.jsonl`
  (agy-dispatch.mjs polls it — print mode writes nothing to a pipe).
- **No-shell STEER (the anti-popup fix):** agy spawns a VISIBLE `powershell.exe` per shell tool-call and no
  launch flag suppresses it — the wrapper prepends a no-shell steer so Gemini stays on in-process file tools
  (verified 0 child shells). Do NOT bypass with `--allow-shell`. `windowsHide:true`; child tree killed on
  timeout; keep concurrent agy ≤ 2–3.
- `--readonly` for investigations/reviews/judges; omit → `--sandbox --add-dir <target>` for edits. Default model
  `gemini-3.1-pro`.
INTEGRATION STATUS (2026-07-05): the TRIO drivers (`gemini-cli.mjs`) are agy-correct, AND **Anchor's
`job_runner` Gemini backend is wired** — `_build_gemini_argv` routes through `C:\dev\Anchor\agy_job_adapter.mjs`,
a thin shim that runs agy-dispatch.mjs and re-emits the reply as a stream-json `result` line (parsed unchanged by
`extract_assistant_text`/gandalf/summarizer); verified end-to-end (PONG smoke, 0 popups). `agy_job_adapter.mjs`
writes the prompt to a temp FILE and picks read/edit posture from `permission_mode`. Any NEW code that calls
Gemini uses agy-dispatch (never bare `gemini`).

## Three STANDING rules for EVERY foundry-skill run (trio, gandalf, jumper — locked by John 2026-07-03)

1. **Frontier Claude builds.** Foreman execute/fix + any code-authoring seat = frontier Claude.
2. **Gemini checks.** Foreman reviewers, Crucible Sharks, researchPrime panels = Gemini.
3. **The tier's Claude steers** (John 2026-07-04: frontier steering is overkill for routine build supervision —
   the steering seat runs the TIER's Claude model: Opus on standard-tier work, Fable only for heavy-tier
   planning/synthesis). The orchestrator/tracking seat — Crucible Synthesizer, the session supervising a run,
   any "is this being done right" agent — gives John the 10-minute Status-table updates for the run's whole
   life: schedule the cadence (ScheduleWakeup ~600s) AT LAUNCH, post the table EVERY tick (the table IS the
   deliverable of a tick), stop only when the run is finished or parked at a human gate. The table must be the
   LOCKED FORMAT above — every field, with the timestamp, ELAPSED time, and the Procs census on every update; an
   ad-hoc summary does not satisfy the rule. CENSUS MECHANISM (John 2026-07-03): cadence ticks must be
   SHELL-FREE — at run launch, start ONE hidden persistent census loop and have every tick only READ files (run
   log via the Read tool + `_census.log`). The loop creates ZERO processes per sample: in-process PowerShell
   cmdlets (`Get-Process` counts, `Add-Content`), launched once via `Start-Process powershell -WindowStyle
   Hidden -ArgumentList '-NoProfile','-Command',$body` (NOT `-File`). NEVER a loop that shells out per iteration
   (a console flash per minute). No foreground shell calls on a timer tick, ever. DELIVERY (John 2026-07-03):
   **the CHAT WINDOW is the PRIMARY channel** — every tick MUST post the full table in chat; he will NOT open a
   board file. Secondary: append the table to the run's board file (archive); PushNotification one-liner
   (auto-suppressed when his terminal has focus). If chat rendering ever visibly fails, tell John rather than
   silently demoting chat.
Long-running engine processes are launched from the MAIN session (never owned by a disposable subagent — a
reaped subagent kills its children; proven live 2026-07-02).

## Quota boundaries — carry on with credits (John 2026-07-03)

If a session hits its subscription usage limit mid-run, DO NOT park/handoff for the quota window: John has
purchased extra credits — carry straight on using them. Only stop for quota if credits are also exhausted; then
park cleanly and tell him.

## Claude writes the code — the trio coding rule (John's standing preference)

In ANY trio skill run (Foreman build, Crucible, researchPrime) — even when the rest of the orchestration runs on
Gemini/agy or under the 5:1 split — **the actual CODE-WRITING stays on CLAUDE.** Foreman's EXECUTE step and any
production code authoring/editing run on Claude; Gemini/agy is for the parallelizable work around the coding —
investigation, research, bulk reading, review/Shark fan-out, swarms. Coding is the least-parallelizable,
highest-stakes step, Claude is the stronger coder, and Foreman's topology already mandates single-threaded
coding. Single-subscription hosts use whatever they have, never cross-calling. (Host fact: the Claude binary is
**`claude.exe`** in `~/.local/bin`, NOT `claude.cmd` — modern Node won't spawn a `.cmd` with `shell:false`.)

## No shell spawns from subagents (universal rule, 2026-07-02 — John's typing gets disrupted)

Every Bash/PowerShell tool call on this host spawns a console process that can steal focus while John types.
Therefore, in EVERY session: (1) sub-agents launched via the Agent tool must be instructed to use
Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans; put that
constraint verbatim in every agent prompt. (2) Shell commands run ONLY in the main session, batched (one
combined call instead of many small ones), and test suites run at most once per gate — never per-edit. (2b) While
a background run is being monitored, the main session's timer ticks are SHELL-FREE too: tail logs with the Read
tool and read the persistent census logger's file. Shell calls during monitoring are reserved for real
interventions (a HALT remedy, a gate-transition action), batched into one call. (3) A long-running engine/build
launch (node/foreman/etc.) is ONE background spawn and is acceptable; a storm of short-lived shells is never
acceptable. (4) Anything a dedicated tool can do (Read/Grep/Glob) must never be done via the shell.

## Engine runs launch under ConPTY (global rule, John 2026-07-03 — third popup complaint)

`windowsHide` on the engine's direct children is NOT enough: the headless claude.exe agents' own Bash tool calls
allocate a fresh conhost PER CALL, and those flash/steal focus. The class fix: launch ANY long-running agentic
engine (Foreman run-live, Crucible, researchPrime, gandalf hosts) under a **ConPTY pseudoconsole** — all
descendant console processes (claude.exe, bash, pytest, git) inherit it and can never materialize a visible
window. Wrapper: `C:\dev\plans\2026-07-review\pty-launch.py` (pywinpty; VT-stripped log + exit-code propagation):
`python pty-launch.py <logfile> <command...>` as the ONE background spawn. Never retrofit mid-run (don't kill a
live wave for it); apply on every (re)launch.

## No background processes spawning visible shells (universal rule)

Any process started in the background — by me, by Gemini, or by code/driver scripts I write or run (e.g. trio
`driver-*.mjs`, Anchor `job_runner`) — must **not** pop visible PowerShell/console windows. Enforce in spawn
code: `windowsHide: true`, `shell: false`, explicit `.cmd` on Windows, and `CREATE_NO_WINDOW` for Python
`subprocess`. When running my own long tasks, use the background runner rather than launching a visible shell.

## Host-shell bridge

**Reuse verified browser retrieval before requesting manual exports (John, 2026-10-02):** For authorized retrieval from a project already open in John's signed-in browser, check successful sibling-cockpit methods before declaring access blocked by Windows session 0. Hierarchical Normalizing Flows / Paper 1 demonstrated a temporary hidden interactive scheduled task using UI Automation in session 1. Verify the exact project address, use normal download controls, remove the temporary task, and verify saved files. Session separation alone is not proof that John must export manually; this method does not require reading authentication stores. The installed `overleaf-intake` skill in `.codex/skills`, `.agents/skills` and `.claude/skills` packages this method for future academic paper work. Source: Paper 1 turns `6222b41c-18ef-4844-bfe3-c6ac1f2a7390` and `fd975de0-a408-4ba7-be62-db207650ced5`.

The `claude-code-bridge` plugin exposes `mcp__Claude_Code_Bridge__run_command` for running PowerShell on the
Windows host. Load it at session start via `ToolSearch("select:mcp__Claude_Code_Bridge__run_command")`. If
`git` / `gh` / bare `python` fail there (the MCP server's spawned PATH is stripped), use the file-IPC fallback:
write a JSON request to `C:\dev\claude-code-bridge\ipc\inbox\<uuid>.json` and poll the matching `outbox` file.
Use FORWARD SLASHES in Windows paths inside the JSON to avoid `\a`/`\t` escape corruption.

---

## The Elegance Law (locked by John, 2026-08-15)

Canonical, model-agnostic text: **`C:\dev\Skill Foundry\ELEGANCE.md`** — and it is injected
verbatim into every canonical `SKILL.md` (trio + foundry + Ecgberht), so it travels with the
skill to any host and any model, not just to Claude reading this file.

Why it exists: a ten-day steward rebuild produced ~140 process artifacts (~15,000 lines) and
about four usable affordances, none confirmed on John's screen. **Long plans manufacture
false consent** — thoroughness funded by approvals he did not truly give.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation, the one
   thing that gets worse. The artifact stays on disk and is named, never pasted. An approval
   obtained with a longer block is VOID; treat that work as unapproved.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings ranked by
   consequence, the single next decision. Never rounds, waves, seats, stamps, gate counts, or
   file inventories. Never restate what he just said.
3. **Default to the lightest band, without asking.** A heavier tier requires the run's first
   status line to NAME its trigger: irreversible or externally visible, inputs unconverged, a
   prior failure in this exact area, or he asked for it. A heavy run with no named trigger is
   a defect. Right-sizing DOWN never costs him a question.
4. **Needed-because line.** Any element he did not request carries one line in the plan:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE genuinely dry round ends a review loop — never a streak, which pays
   reviewers to produce filler. Every plan names at least one thing it removed, with the cost
   saved; "nothing cut" must be said out loud.

**Two laws these serve.**
*A gate that cannot see what the user sees is not a gate.* Prove any UI claim against real
pixels and the real service. Structure diffs, markup hashes and slot inventories are lints —
label them as lints. The chamber logged an identical `1135/1135` for twelve waves while the
surface it was building deleted itself on every open.
*A guardrail is never the whole product of a turn.* If enforcement withholds output he has
already paid for, show the withheld output anyway.

### The verification law (added 2026-08-15 — its FOURTH recurrence)

Each of the first three was written into a journal afterwards and recurred anyway. Journals
are read after the fact; this is here because this file is read before the work.

- 2026-07-26 — 63/63 tests green, run against the wrong directory.
- 2026-08-12 — 53 model gates + 27 deck checks passed while four charts rendered CLIPPED, a
  headline overflowed its subtitle, a footnote lay across the footer.
- 2026-08-13 — John: *"a lot of work was done but it isn't showing up."* I offered a data
  explanation instead of looking. He was right; the chamber was deleting itself on open.
- 2026-08-15 — *"I restarted and nothing changed"*, four times. Each time I verified the
  SERVER and blamed his browser without testing it. Real cause: the redeploy signal was
  keyed on the last commit, so uncommitted work never moved it and no page ever reloaded.
- 2026-10-01 — *"where are my icons in Chrome tabs? I have asked for this a number of
  times"* (the fourth ask). Each fix was proven on the server and in a driven browser and
  handed back as "your Chrome cached it". His own tab strip, captured, showed the icon
  painted but dark-on-dark at 16 px, old preview files and documents opened from disk.
  A browser claim is now proven by capturing HIS window: `Skill Foundry/planning/
  active-set-2026-09-29/tools/capture_his_tabstrip.ps1`, `chrome_tab_names.ps1`,
  `chrome_favicon_store.py`. An icon is judged at tab size on his tab colour.

1. **Verify the claim you actually made, on the surface he actually uses.** "It's live /
   fixed / renders" is a claim about HIS screen. That the server emits new bytes, that a
   build exited zero, or that assertions passed are claims about something else. Render it
   and look at it.
2. **A symptom reported twice retires the first explanation.** The second report means the
   hypothesis was wrong or never tested. Test it; do not repeat it. An explanation that makes
   his report false ("it's your cache", "it's a data issue") needs MORE evidence, not less —
   it is the one you want to be true.
3. **Prefer a mechanism to an instruction.** If the same instruction is given every session
   ("hard-refresh", "check the exit code"), the instruction is the defect. Build the thing
   that makes it unnecessary.
4. **A correction that lives only in a journal or a memory has not been made.** Promote it to
   where it loads before the work starts — this file, and the ELEGANCE block in every
   shipped SKILL.md.


## Durable run checks across session refresh (2026-09-08)

On hosts that may refresh the agent session, do not infer a live run from its last start message or a stale IN-FLIGHT record. Verify the recorded process and a current heartbeat/result before saying work is running; mark attention quiet/needs_you promptly when it has ended. Long engines should be launched through a hidden detached ConPTY helper with a durable PID/result receipt so their lifetime does not depend on an exec tool session. Keep exact termination causes unclaimed unless established. This follows Math541 runs that were observed absent after refresh without terminal outputs; source work and previews were preserved.

## Make local setup instructions concrete (John, 2026-09-09)

When an installation needs John's local interaction, explain what is being installed, distinguish the software destination from the existing data/project folder, recommend an exact verified folder when context supports it, and give numbered steps using the visible window/button names. Resolve routine technical choices yourself. Never hand back a generic "choose your project folder" or "complete the prompts" instruction when John has not been told which folder, what the choice controls, and what happens next. Keep passwords in the local secure prompt, never in chat; do the remaining installation and verification work within the existing authorization.

## Preserve Unicode through PowerShell input (2026-09-09)

When piping a Python or other script through PowerShell, set both `$OutputEncoding=[System.Text.UTF8Encoding]::new($false)` and the child’s UTF-8 input/output configuration before the pipe; output decoding alone does not preserve script input. Prefer structured file-edit tools for Unicode text. Inspect rendered punctuation after report edits; a successful script can otherwise silently replace smart quotes and dashes with question marks.


**Verify review participation (2026-09-09):** Before reporting an engine review as verified or converged, inspect actual returned responses, abstentions and required quorum. A successful exit or DRY label does not override an unmet quorum or missing reviewers. Preserve the raw result, report partial review honestly, and disposition any useful findings. Do not invent votes, approvals or refutations to repair the label; journal the engine defect for its own maintenance effort.


**Preserve shared staging (2026-09-09):** In a shared or neighboring repository, inspect the existing index before committing and commit only the task’s explicit paths. Adding one journal file does not make pre-staged changes yours. Use a path-limited commit so another session’s staged work stays staged and uncommitted.

**Code jobs produce artifacts; the steward updates campaign state (2026-10-05):** Scope a code job to its artifact files and checks. Do not include attention or Strip changes in its placement set, or copy its Face/roadmap state back into the authoritative effort. After the job releases repository ownership, the steward updates campaign records through their existing writer and clears attention when the work lands. If automatic placement rejects protected state, preserve the committed output and integrate only the verified artifact paths; do not disable the protection or make John repeat authorization. Evidence: MIT Lectures PDF job `20261005-132545-cf4530`, journal 0025.

**Delegated software still needs independent assurance (John, 2026-10-05):** A direct code job and passing tests do not replace the software's independent expert/adversarial review or its failure-path hardening. Keep those obligations explicit in the existing roadmap, with executable gates and actual live/client proof appropriate to the feature; backups are not a substitute for software hardening. Record completed reviewer participation and serious findings honestly, and distinguish author checks, independent review and human acceptance. Select Foreman/Crucible when their depth is needed and their gate exists; do not invent a prior review or a robustness claim from a test count. Source: Setup and Mother Ship turn `56d231a8-8117-447d-9d37-51eb60220b5a`.


## Concise Action needed explanations - September 17

John reports that long explanations run off the page and cannot be scrolled. Give a decision summary of roughly 40-60 words: two short context sentences, recommendation with one reason, the main alternative and its tradeoff, then one question. This includes any pickup; do not prepend a research recap or repeat plan bullets. John reiterated this correction on September 17 after a roughly 150-word handback. Never paste accumulated progress commentary or a full assistant turn into the explanation. Keep longer history optional; any expanded detail must fit the viewport and scroll. Preserve the saved question and version scope. Journal UI defects in Anchor and Steward; do not claim a display repair without checking the actual live control. Apply this concise form immediately in conversation.


## Mockups before the plan word, and before any build - September 24

When John asks for mockups of a surface, the mockups are the decision, not an input to it: he goes through them (looks, says what to change, looks again) BEFORE he is asked to approve a plan and before anything is implemented. Put the mockups in front of him with how to open them, one line each, and one recommendation; iterate on his words; only then bring the plan for its word. Do not ask for plan approval while the mockup look is still open, even when the plan gates the build on his pick (High Seat cycle, 2026-09-24: "I don't want you building things, implementing a plan until we have gone through those set of steps"; "I thought that I had asked for this in the overall plan").

## Answered decisions stay settled - September18

After John answers a scoped question, record the answer and clear the managed pending request before substantial further planning. Carry the accepted meaning into the same plan; do not keep or recreate the question with different wording, or turn routine implementation choices into another approval. Before presenting any question or final handback, read all newly appended original user turns, including messages received while tools ran; compare against the last actually read position, not merely a Git prefix. A new question must concern a materially different unresolved decision and explain why the existing answer does not settle it. Never infer a specific content choice from a process correction; recover the separate original authorization. Preserve independent deliverable acceptance and prior versions.

**Scope recording does not finish mockup feedback (John, 2026-10-04):** When new feedback adds visible controls to an authorized mockup, update the existing roadmap and continue that mockup's refinement in the same turn. A later live-integration prerequisite does not block independent prototype work. Do not park after merely registering future tasks. An instruction to resume work preserves the original scope and review boundary; it does not accept the unreviewed product or close its slice. Source: Setup and Mother Ship turns `49427a76-73ad-4823-8c3f-2ee92a922279` and `13a7ff78-dd88-4d79-8bf8-f842af161ecd`.
