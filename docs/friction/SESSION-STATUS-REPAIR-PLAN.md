# Session status: analysis and proposed repair

September 8, 2026. Requested by John. **Analysis complete; implementation proposed.**

The problem is that a generated status, a delivered status, and an accurate account of the work are treated as if they were the same thing. The ten-minute timer already exists. The repair should connect work ownership, evidence, publication and browser acknowledgement through the existing status system.

## Confirmed failure, beyond the journal

A focused probe drove the installed `Engine._handle(result)` with a temporary campaign and a fake model process. Before completion, the published status said the steward was working. After completion, the saved status correctly said nothing was running, but the engine emitted **zero new status events**. The probe launches neither a model nor a browser and modifies no live campaign or engine source.

The direct cause is `steward_engine.py`: the post-arbitration result path calls `_status_update(emit=False)`. In `shared.js`, `turn_end` closes the conversation/activity display but does not fetch the new status. An open pane therefore receives no immediate completion status from this path. This explains how the file can be correct while the pane still shows earlier work; it does not prove this caused every reported historical gap.

Other confirmed defects are independent: the composer chooses the first active roadmap row; local checks and journal entries do not feed their status rows; a working stamp expires after 120 seconds without recognized ownership evidence; free-text “no decision” can become a false blocker; and goal rereads are compared to projection order rather than the corresponding completion event. Actual browser acknowledgements at 19:26 and 19:36 prove one delivered interval, not reliability across all these cases.

## Recommended repair

Keep the existing timer, status pane, roadmap, Strip, attention cell, delivery record and event stream. Extend their contracts and their producers. Do not introduce a second product map or rely on a reminder for the model to post updates.

### 1. Publish completed work immediately

After result arbitration has finished and the stdin lock has been released, publish the post-arbitration status through `_status_update(emit=True)`. Preserve the existing status lock and ordering checks. The snapshot must describe the actual state after any queued human message or authorized continuation starts; it must not falsely publish idle between two turns.

Use the same publish path at meaningful run completion/failure transitions and on the ten-minute cadence. Do not reset the periodic deadline on every minor activity event, or continuous activity could postpone scheduled updates indefinitely. Do not advance the successful-publication clock when composition or persistence fails; record the failure and use a bounded retry.

This is the first small patch because it repairs a reproduced defect without replacing the reporting architecture.

### 2. Name the current work and attach its evidence

Add an explicit `current_step_id` reference to the existing Strip and bind execution receipts to that roadmap step plus session/run identity. The roadmap remains authoritative for the plan; the reference selects what the current status describes. Validate the ID. For legacy campaigns, use a sole active step when unambiguous; with several candidates, show that focus is unset rather than silently selecting the first. A completion snapshot may retain its just-completed step until the next work begins.

Make the local check launcher write a structured receipt automatically on start and exit: run/step identity, command, timestamps, exit code, evidence file and result classification. Adapt existing external-run receipts into the same small reporting shape. The status composer should render those receipts rather than parse conversational claims of success. Checks bypassing that launcher must be shown as unavailable evidence, never presumed passed.

Link journal updates by entry identity, timestamp, source path and a short summary, with a cursor identifying what is new since the preceding status. Use a small append helper that writes the human entry and its reference together. Keep the human journal as the record; the status holds references and bounded summaries. Preserve passed, failed, untested and unavailable distinctions.

Represent a current human request explicitly. `null` means no request; an omitted field means no new information and must not erase a real request. Retain compatibility with legacy fields. Calculate elapsed time from the bound run and its recorded pauses; show ETA as unavailable unless a current run supplies an estimate. Do not derive a work estimate from the date an unrelated roadmap row became active.

Audit each actual completion event against its later matching North Star verdict. Include the completion event sequence so reopening and completing the same step twice cannot reuse an old verdict. Projection reordering and a later unrelated reaffirmation must not change that result.

### 3. Let the execution owner maintain liveness

The launcher/supervisor must renew work evidence while the actual bound worker remains alive. The model should not have to remember a periodic file write. Reuse the existing process identity tuple `(pid, process creation time)`, run IDs and lease protocol from `status_outbox.py`; preserve its existing renewal/expiry contract and the mediator’s ownership of the roadmap ledger. Add a read adapter where the cockpit currently recognizes only supervised-seat heartbeat files.

For the steward’s own work, use its live process and current turn/epoch; for a background command, observe that command’s owner. A supervisor being alive is not evidence that its worker is alive. A silent but live worker may still be running; report the age of its last progress rather than inventing progress. Expired or unverifiable ownership must become unknown/stale, not quiet success. Completion retires the corresponding run, and recovery must not revive an old run merely because a PID was reused.

The attention cell remains the cockpit’s state projection. Liveness updates must preserve explicit user requests and blocked states and must not let a late completion clear a newer run. The short launch grace is a bridge to verified ownership, not an indefinite keep-alive.

### 4. Verify delivery to the correct pane

Extend the existing browser acknowledgement to include the exact `status_id`, session/epoch and pane identity. Store generated and rendered times separately. Older or unknown acknowledgements must not advance the newest delivery record. One tab’s acknowledgement must not conceal another attached pane being stale.

Use the pane’s last received generation and the server’s generation/acknowledgement records to expose a late or unconfirmed update. Missing acknowledgement means delivery is unconfirmed; it does not identify whether the break is generation, transport, rendering or acknowledgement. A disconnected browser cannot be claimed to have received a status.

Keep scheduled updates in the status pane. Publication and delivery errors must be visible without requiring John to ask; no synthetic acknowledgement may be written by the steward.

## Implementation order and proof

Implement the publication patch first, then explicit focus/evidence, then ownership and acknowledgement integration. Retain the existing queue-arbitration tests and add behavioral regressions at the changed boundaries. Use an isolated checkout for the repair; do not restart the live session that is reviewing this proposal.

| Gate | Required result |
|---|---|
| Completion between ticks | A real browser receives the new completed/idle state promptly, before the next cadence. A queued next turn remains shown as running. No older snapshot overwrites it. |
| Continuous work | At least two real configured ten-minute intervals publish and render while work continues. Record the allowed scheduler/transport tolerance, generation IDs and actual pane acknowledgements. |
| Current focus and evidence | Old active rows and parent milestones cannot steal focus. Run a local passing check and a failing check and record a correction; the next status shows the relevant results and journal update with their sources. Missing evidence stays explicit. |
| Lifecycle and recovery | Test background work beyond the old 120-second threshold, idle model, worker death, completion, provider/session restart, reconnect and delayed/out-of-order acknowledgements. No dead owner is resurrected and no live completion is hidden. |
| Real user requests | An actual unanswered question remains visible; explicit no-request does not become “waiting on you.” Reopened/completed steps require their own North Star verdicts. |

The immediate regression runner is `python .ecgberht/reports/probe-session-status.py --require-fixed` from the MBA Teaching AI root. It **currently exits 1**, correctly detecting the missing publication. Its receipt is `status-boundary-probe.json`. Passing this focused probe will only establish the completion-event repair, not the full browser or lifecycle acceptance above.

Extend the existing Anchor suites `test_steward_decision_shape.py`, `test_cockpit_status_window_2026_09_03.py`, `test_status_freshness_2026_09_07.py` and `test_status_outbox_w13.py`; add real browser coverage for the supported session/provider paths. Run focused checks after each slice and the complete status regression set once before the real-session proof. Do not replace behavioral checks with searches for strings in source files.

## Choice and limits

I recommend this bounded Anchor repair: it removes dependence on model memory and fixes the reporting path John actually uses. Manual verification alone is immediately available but keeps imposing operator work. Fixing only the completion broadcast is smaller, but leaves incorrect focus, missing local evidence and background ownership unresolved.

No production change or deployment has been made. John renewed the instruction to deliver the lecture drafts first; this supporting repair does not require a new question before course work continues. The general friction record remains open until the selected scope is implemented and its corresponding real-session evidence is recorded.


## September 8 usability correction: make the state obvious

John reports that the cockpit is too dense to identify what is ready, what is running or when the next deliverable will arrive. The technical defects above are compounded by ambiguous wording and a plan organized around broad course blocks. A green dot should mean observed current work, amber should mean an actual question requiring John, and a neutral dot should mean nothing is running. Expired evidence must say status is unconfirmed, with the last verified time; it must not silently become a request for John. Text must accompany color.

The main line should contain one plain sentence identifying the concrete output in progress. Directly below, show the next expected deliverable and a grounded estimate, plus the most recently completed artifact as an openable link. Keep diagnostics, process counts and historical warnings behind details. Reuse roadmap steps as the product map; Lecture3, Lecture4 and the sample-means demo need distinct rows. This is a presentation simplification within the same repair, not another register.

Acceptance requires a user to answer from the visible cockpit alone: Is work running? Which output? What can I open now? What arrives next and when? Is there a question for me? Exercise real work, worker death, quiet completion and a genuine waiting question. The working state must stay green for observed foreground and background activity, then change immediately when the last owned work finishes.

Immediate campaign correction is implemented: separate active deck rows, no false human wait, fresh activity stamps and linked existing artifacts. The general Anchor code and visual design changes remain proposed. The previous status-repair approval question is withdrawn; it must not delay the already-authorized decks.


## September8 implementation receipt

John explicitly approved repair. Live workflow links and sandboxed demo comparisons are repaired and browser-verified; the client supports stable step IDs, clearer work status and a completion refresh. Server publication/focus/evidence changes pass isolated behavioral checks and await safe server activation. Automatic receipt producers, owner renewal, exact per-pane acknowledgements, North Star completion auditing and full lifecycle/two-interval acceptance remain open. The general friction report contains the evidence and activation boundary. This update supersedes earlier “proposed/no production change” wording for the completed client and campaign scope only.


## 16 September: legacy campaign focus integration

Observed in Open Source Token Source / Basic Infastructure on 2026-09-16: roadmap had two active steps, no strip.json and no current_step_id. Live Current work showed PLAN.md correctly and opened the report, but the status row showed no active step. Source _focused_step deliberately returns unavailable when multiple steps lack explicit focus; campaign initialization/writer integration had omitted that focus. Campaign now initializes the existing Strip schema and points current_step_id to standard-performance-tests; no engine source changed. Keep general prevention open: create or require truthful focus when a campaign gains multiple active/review steps, preserve every review pin, and verify across refresh, provider pickup and two status cadences without inferring acceptance. Evidence: Basic Infastructure/.ecgberht/plan-current-work.png and journal/0005-standard-performance-test-plan.md. Local status evidence rows still report unavailable; do not claim journal/test receipts are consumed.

Canonical friction record: `2026-09-16-03-legacy-campaign-missing-explicit-status`. Prevention remains open; campaign bookkeeping is not a general engine repair.
