# General session-status improvement report

Related formal improvement, 10 September: [Steward refinement lifecycle review](2026-09-10-steward-refinement-lifecycle-review.md) consolidates the cross-project feedback, plan freshness, revision/acceptance and current-reading design. It reuses this report's existing status work and remaining acceptance criteria; it does not claim these open general repairs are complete.

Date: 2026-09-08. Reported by John during the MBA Teaching AI campaign. Scope: Anchor session status across projects and providers. **General repair remains open.** This report records an observed failure and required proof; it does not certify an engine fix.

This incident is filed in Anchor’s general friction intake and linked to the earlier open report `2026-07-26-03-a-documented-status-cadence-with-no-sche`. The canonical report is `C:/dev/Anchor/docs/friction/2026-09-08-session-status-delivery-and-content.md`; an identical campaign copy makes it openable from the cockpit register.

General intake record: `2026-09-08-01-why-are-we-not-getting-status-updates` (open).

## What John experienced

John asked, “Why are we not getting status updates?”, then directed that the forgetting and the discovered flaw be journaled for general improvement of status within sessions. Jarvis had relied on writing campaign files and the engine timer without checking that the pane showed current, useful progress. This made John chase status and restate the reporting requirement.

## What the evidence establishes

The campaign’s `.ecgberht/delivery.json` recorded actual browser render acknowledgements at **19:26 and 19:36 local time on September 8**. They establish one successful ten-minute delivery interval. A generated status at 19:34 with a last acknowledgement at 19:26 was only an eight-minute difference; it did not establish a broken timer. No new acknowledgement was fabricated during the investigation.

The status content was misleading. It selected an old homework step, showed an irrelevant elapsed estimate of roughly 32,854 minutes, omitted this session’s numerical and Chrome test results, and treated “No outstanding scope decision…” as a literal user blocker. The campaign had already completed a sample-means browser run of 1,000 means with n=500 in 153.86 seconds, but that result did not populate the pane’s Tests row.

## Flaws and code locations

| Flaw | Observed mechanism | General consequence |
|---|---|---|
| Wrong current work | `steward_campaign.py`, `slice_of` and `compose_status`, pick the first active projection row. An old homework item and a parent milestone preceded the actual lecture slice. | Multiple active rows can hide the work actually running; progress and ETA follow the wrong item. |
| Working state expires | `read_map` downgrades working attention after 120 seconds unless a recognized owner heartbeat is fresh. The interface instruction only required a stamp at launch and completion. | A launch-only stamp cannot maintain background eligibility. This can suppress background cadence when both engine busy and queue are false; that causal chain was not established for the observed delivery interval. |
| Local results omitted | `compose_status` populates Tests from a live external skill report; it does not consume this session’s numerical/Chrome receipts. `shared.js` renders `stat.journal`, which the composer does not supply for this case. | Useful local work disappears from Tests and Journal even when its receipts exist. |
| False user blocker | `_real_wait` only treats a short set of literals as empty. Explanatory “no decision” prose was nonempty. | John sees “waiting on you” despite owing no action. |
| False goal warning | `read_map` compares the latest goal-flip step to the last done step in projection order. Later demo-iteration reaffirmations referred to drafts still waiting on classroom acceptance. | A valid prior research close appears to lack its North Star reread. |
| Delivery not verified | Jarvis checked state writes without following their actual render acknowledgements. | Generated status is mistaken for delivered, useful status. |

## Corrections already made in the campaign

The homework item and Block 1 umbrella now wait on their real dependencies, leaving the lecture revision as the current active step. The no-decision field uses the supported empty meaning. The North Star was re-read and the completed research verdict reaffirmed. The actual installed composer then selected `lectures-3-4-revision`, reported the reread, emitted no false user blocker, and read quiet at completion.

These are **campaign-data corrections only**. No Anchor engine source was changed. The local test/journal ingestion gap remains. The canonical user-global rule now requires verifying real render receipts and refreshing working evidence from observed activity within the reader’s lease. It must not keep dead work alive or invent a delivery receipt.

## Proof required before the general issue can close

| Acceptance area | Required evidence inside real sessions |
|---|---|
| Timely pane delivery | Record generation and actual browser rendering separately during continuing work, over at least two configured cadence intervals. Verify the visible pane and real acknowledgements, not a hand-written status file. A missed deadline must become visible. Keep scheduled tables out of the conversation. |
| Correct current work | Exercise a parent milestone, an old active item and the actual current slice together. The pane must identify the actual work and derive progress, ETA, dependencies and North Star state from the relevant records. Preserve real acceptance gates without inventing user blockers. |
| Local tests and journal | Run a meaningful local check and record a failure or correction. The next status must expose the relevant result and journal update with source and time. Distinguish passed, failed, untested and unavailable evidence. Do not replace unknowns with invented success. |
| Background and restart | Keep real supervised work running beyond 120 seconds, let the model become idle, and exercise supported session/provider restart. Pane delivery and working state must remain accurate; completed work becomes quiet and abandoned work expires. Pending authorization must survive restart. |

Focused automated regressions should accompany the change, followed by real browser evidence for the session/provider paths the implementation claims to support. A passing composition test alone does not certify delivery, lifecycle behavior or the general fix.

## Evidence trail

Campaign: `C:/dev/MBA Teaching AI`. Incident and ownership account: `.ecgberht/session-journal.md`; raw status and delivery records: `.ecgberht/status-summary.json` and `.ecgberht/delivery.json`. Campaign corrections were committed as `a17f115`; explicit forgetting and prevention as `fba2fb2`. The browser/numerical receipts remain under `BA 815/Fall 2026/build/review-september8/` and the associated scripts.

Relevant installed source: `C:/dev/Anchor/steward_cockpit/steward_campaign.py`, `steward_engine.py`, and `static/shared.js`. The ten-minute timer is owned by the engine. Intake status stays open until a general fix is implemented and supported by the evidence above.

## Follow-up analysis and solution

The [concrete repair proposal](SESSION-STATUS-REPAIR-PLAN.md) now identifies four changes: immediate completion publication, explicit work focus and evidence, observed worker ownership, and exact-generation browser acknowledgements. A focused probe of the installed Engine result handler reproduced a stronger failure: saved state changed from working to idle, but zero status events were emitted after completion. The probe is in the campaign at `.ecgberht/reports/probe-session-status.py`; its `--require-fixed` check exits1 on the current defect. It launches no model or browser and is not evidence of a live-screen repair.

The proposal defines implementation order and separate behavioral/browser proof. General implementation and deployment remain proposed; this intake is still open.


### Additional September 8 observation

John again could not identify current work, finished deliverables or the next delivery, and saw a misleading waiting state. The steward had let this status proposal displace the requested Lecture3/4 decks and asked an unnecessary implementation question. That question is withdrawn. Actual deck production resumed with separate roadmap rows and no human blocker. The repair plan now includes the plain green/amber/neutral state contract, a compact current/next/ready presentation and five questions the cockpit itself must answer. General production repair remains open; campaign file corrections are not represented as an engine fix. Session overhead is6.


## September8 — steward/cockpit delivery repair, authorized and verified

John asked why Lecture3/4 proposals and the sample-means demo were missing from the left workflow, explicitly approved repair, and repeated that the failure and repair must be analyzed in the steward interaction journal. The failure was not missing production: the proposal PDFs, both draft decks and HTML existed. The steward treated DELIVERABLES registration as delivery without checking the renderer. The renderer matched Step by name or number while new rows carried stable step IDs, silently omitting those artifacts.

The immediate campaign compatibility repair uses current step names so an already-open client can show the links. The general client now also matches stable IDs and retains name/number compatibility; expansion state follows ID across renaming. Actual Chrome on the running service clicked the proposal PDF, Lecture3 PDF, Lecture4 PDF and HTML from their left-hand steps and verified successful opening.

A second defect appeared only on that real path: the isolated HTML preview could run the demo, but its comparison links requested the authenticated server from an opaque origin and were refused with403. The demo now makes independent in-memory comparison pages, with n/population parameters in their fragments. Preview isolation and the cross-origin guard remain enforced. Actual Chrome now passes single sample, n change, automatic/pause, independent n30/n500 tabs and CSV export, with no page errors. This is why file-origin checks alone were insufficient.

The client status line now uses plain working/question/idle wording with green/amber/neutral colors, preserving red for broken state; provider diagnostics are in its tooltip. It fetches a fresh status shortly after completion, covering older running servers that persist without broadcasting. The narrow client patch is installed and was verified on a newly opened live cockpit; no claim is made that every already-open tab has reloaded its JavaScript. The data-level link repair does not require that reload.

Server-side completion publication, explicit current-step focus, null request semantics, source-bound local check/journal evidence and honest ETA are implemented in an isolated checkout. The focused result probe now emits exactly one newer status. Current root tests:89 backend regressions plus9 Chrome renderer checks and15 focus/evidence cases pass. These code tests do not prove server activation or two scheduled live intervals. The current Anchor process owns the active Codex conversation (ancestry verified), so restarting it now would interrupt the repair session. Server activation remains pending a safe restart. No new approval is required from John.

Remaining general scope stays open: automatic check/journal receipt producers, verified owner renewal beyond the old lease, exact per-pane generation acknowledgements, completion-event North Star audit, and full lifecycle/two-interval acceptance. This is a verified usability repair plus a tested first server patch, not certification of that whole plan.

Evidence in the MBA campaign: `.ecgberht/reports/workflow-links-live.json`, `workflow-links-live.png`, `sampling-demo-live-route.png`, and reproducible `check-live-workflow.py`. The isolated Anchor branch is `codex/status-workflow-20260908`. The campaign journal records observed failures, attempted checks, fixes and the activation boundary. The durable global rule now requires visible workflow links and actual viewer checks before a delivery claim. Session overhead is8.


### Final first-patch verification — 2026-09-08T21:00:43.056271-06:00

The focused and adjacent status/workflow suites finish174 passed. Two legacy status assertions were updated to the approved contract: missing evidence and unsupported ETA must be explicit, not blank or a guessed part-duration. A wider11-test dashboard group has7 failures and4 passes; all7 failures reproduce on the unchanged isolated baseline `1b1ed90`. They concern retired inline dashboard JS/CSS expectations and discovered-tile rendering, not the changed steward renderer. They are recorded in `anchor-dashboard-baseline.json`; no whole-application green claim is made.

Repair code is committed in isolated branch `codex/status-workflow-20260908` as `9f62a5f`. Only narrow source diffs were applied to the live source tree, preserving unrelated existing edits. The client is served now; Python source is installed on disk and will activate on a safe server restart. The running server was not restarted because it owns this conversation. The status intake remains open for activation and the remaining general acceptance work.


### Report opening correction — 2026-09-08T21:02:48.486459-06:00

The final live-reader check found that the general report’s registered `.ecgberht/reports` path was rejected as “bad path”: the text-report reader intentionally excludes hidden path components. The proposals and demo checks were unaffected. The human-facing repair report and its existing plan are now published under the course planning folder and the single register points there. The reader guard remains intact. Both report copies and the campaign journal record this further steward/viewer contract mismatch.


## September 9 — hierarchy campaign: feedback before close and simpler status

John approved archiving Hierarchical AR Networks (source eb56abca-546b-4651-8bff-31c90c347948) and explicitly asked for workflow lessons. New canonical intake: `2026-09-09-02-research-ran-ahead-of-feedback-status-an` (open). The full original words are retained there; the campaign reading is `C:\dev\Mathematics Problems\Transformer Math\Hierarchical AR Networks\archive\LESSONS.pdf`.

The failure is partly a workflow boundary: producing and independently reviewing an artifact was repeatedly treated as readiness for the next research step while John still needed the central architecture explained. Shared understanding must be a named result. The visible plan should keep the slice in feedback/revision until John accepts its close; downstream work remains waiting. Routine work inside the approved slice continues, and pickups preserve approvals. This must not become a new permission ritual.

John reports the status as complicated and slow to reflect useful events. The campaign saved status at 18:28 showed check/journal evidence unavailable despite local receipts; this establishes a content gap, not a proven timer outage on every device. The requested front surface is simply current activity, last meaningful event with actual time, and a working way to open earlier updates. Details remain behind that summary. The existing register should expose one current START HERE artifact/collection and keep superseded material below it.

Acceptance for the general improvement: deliver a draft in a real session and show feedback wait with no dependent job; revise it from feedback and update the same map/product; accept a close and advance only then. Exercise a local check and completion, two scheduled status intervals, clicking an earlier update, and provider pickup. Actual browser content and render acknowledgements must match the current slice and event times; no fabricated cost, ETA, check or delivery receipt. The current reference guide must open from its intended step and conversation.

Applied here: canonical user-global workflow rules, latest-reading order, final-plan-before-projection save, reference preservation and explicit parking of unperformed work. Still open for Anchor: the general feedback-phase/status-history behavior and its full live acceptance. No new cockpit implementation or research campaign was commissioned by this archive.


Archive lifecycle observation (20:21 local): retirement in place preserves `/artifact/...` report paths and joins the archive listing, but the existing active effort map/register routes return 404 `unknown effort`. The prior work page consequently shows an empty-map error. The archived reference guide and its internal links were verified as the reading entry point. A future archive/status improvement should provide a clear archived-reading state with its reference link, rather than the empty active-work page. This observation is recorded, not claimed repaired here. Final scoped local-check and journal receipts were also written into the campaign Strip; the deterministic composer reads their completed evidence correctly. That composer result is not a browser render acknowledgement.


## September 9 live-work follow-up — 2026-09-09T20:32:35.107358-06:00

The cafe revision continued with a supervised hidden owner and a live Jumper child. The first composed review finished at20:29:11 and the next model process began; the attention lease was being renewed. However, campaign delivery.json still recorded its last render acknowledgement at20:13:56 after a20:28 live workflow test. This does not establish why acknowledgement is absent, or prove a particular scheduler outage. It does establish that fresh scheduled-pane delivery is not verified. Keep the prior per-pane-generation acknowledgement and two-interval acceptance work open; file writes and successful document clicks are not substitutes. The teaching artifacts were delivered while this reporting limitation was recorded. No production server restart or additional Anchor repair is claimed.
# September 9 Chekhov chat-delivery recurrence

Canonical intake `2026-09-09-03-chekhov-scheduled-chat-relay-missed-desp` records an observed20:47Denver missed chat relay, corrected20:55. The main-owned watcher remained live; by02:55:13Z its current phase/census agreed with the ongoing recovery. The narrow established defect is that a live file emitter did not ensure the session relayed its scheduled chat table while preparing recovery work. No engine timer outage or Anchor runtime root cause is established. Main added a clock-only reminder helper as a session mitigation; it does not own or monitor the run and is not a claimed Anchor product repair.

General repair recommendation remains to distinguish emitted status from actual delivery and preserve an unacknowledged update across context refresh, using the existing status surface. Real-session acceptance needs two scheduled intervals, one spanning refresh, with actual chat/pane delivery evidence, no fabricated acknowledgements and no duplicate monitor ownership. Product capture continued while this defect was recorded. Evidence: `C:/dev/Skill Foundry/skills/chekhov/.foreman/restart-20260910/friction.jsonl` and `status-intake.json`.

Further evidence from the same Chekhov run: the September 9 22:35 Denver chat table was delivered at 22:38 after a context handoff. The capture owner and file observer remained live. Main journaled the delay and reported it in that table; the 22:45 and later scheduled relays resumed. This supports retaining pending delivery across context handoffs in the existing open recommendation. It does not establish a timer outage or a repaired Anchor delivery path.


## September9 current pane acknowledgement — 2026-09-09T21:00:37.091091-06:00

After the20:56 live-workflow opening check, delivery.json recorded last_render_ack_at20:56:42, last_acked_status_at20:56 and106render acknowledgements. This verifies a fresh pane acknowledgement during this session. It does not establish that the recurring ten-minute publication path is reliable, because the observation followed an explicit page load. Keep the two-interval acceptance test open. During the transition from Jumper's ended owner to contributor-only work, the root attention timestamp also exceeded its120second lease before correction. The subsequent ResearchPrime CLI run has a genuine supervised owner refreshing from live child state. A general repair must supervise active session/contributor work as well as external CLI children and reconcile terminal results; merely adding another instruction to stamp attention is insufficient. No production Anchor source patch or restart was performed in this pass.

### September 10 - Attention encoding and actual opening-surface follow-up

During the authorized Lecture3/4 revision, the actual cockpit displayed `Working - unreadable (JSONDecodeError)`. The steward's Windows PowerShell UTF-8 writer had inserted a BOM into attention.json; the installed reader decodes strict UTF-8 JSON. The campaign repair uses an atomic plain-UTF-8 writer and checks both bytes and actual displayed state. Recommend one shared attention writer (and a BOM-compatible reader or explicit encoding diagnostic), with a real-session regression covering PowerShell producers, green working state and transition to human review. This is a verified campaign file repair, not a claim that all general status issues are fixed.

Live acknowledgements reached 01:40, but the pane still reports local check/journal/ETA evidence unavailable and no work-product plate despite recorded artifacts. Those integrations remain open. A separate token-free report URL returned401; actual authenticated workflow viewer/download controls work. Final handback uses those controls and publishes no credential-bearing URL. A browser's PDF popup can remain about:blank, so validation must verify served bytes and viewer behavior rather than deriving a conversation route from that URL. Evidence: MBA campaign build/review-machine/live-receipt.json and live-workflow.png; campaign journal records the failures and corrections.


Chekhov September10 recovery observation: the import owner ended at10:36:36Z (04:36Denver) with a terminal service error; the native reminder worker separately reported a usage limit. Root next resumed at12:11Z. The file observer was still alive and refreshed a manually authored running phase despite the capture owner being failed. Root verified the failed result and corrected the phase immediately; a bounded service check and source/ledger audit then allowed a controlled continuation at12:21Z. This proves that freshness of an observer file is insufficient: the displayed run state must derive from the owned child’s terminal receipt, and status must distinguish a session interruption from continuing model work. Add this case to the existing open intake2026-09-09-03-chekhov-scheduled-chat-relay-missed-desp; no general Anchor implementation is claimed. Acceptance must include a real provider/session interruption, owner failure while the coordinator is unavailable, correct stopped-state rendering and actual delivery after pickup. Evidence: Chekhov .foreman/restart-20260910/batch-17-attempt-01/, friction.jsonl and .foreman/readiness-20260910/availability.json.


September10 further Chekhov evidence (intake 2026-09-10-02-chekhov-status-relay-delayed-across-cont): Agent-observed follow-up to2026-09-09-03-chekhov-scheduled-chat-relay-missed-desp. Chekhov chat table last delivered16:42Z; next delivered17:00Z after context recovery, an18-minute interval. The main-owned observer remained alive; heartbeat files did not establish chat delivery. Root acknowledged the late update and resumed reporting. No engine timer outage or Anchor implementation repair is established. Recommendation: retain undelivered scheduled status across context refresh and derive running state from actual child receipts. Real-session acceptance: two actual delivered intervals, one spanning refresh, without fabricated acknowledgements or duplicate monitoring. Evidence: Chekhov journal/runs/2026-09-10-writing-readiness.json and .foreman/scope-20260910/status.json. Current product repair and trial continue.


## September 11 — status size, usefulness and portfolio consistency

John again reports that the status is too large, hard to interpret, and unsuitable for the main Steward dashboard. Current intake: `2026-09-11-05-status-is-still-too-large-and-unclear-fo` (open; linked to the existing status incident). The live MBA pane measured 380 pixels wide; its status area was 357 × 717 pixels. The main status body contained 1,077 characters and scrolled, and the latest-update strip overflowed. The header said Working while its text described the older Lecture 3 review. Evidence is in MBA `.ecgberht/status-design/current-window.json` and current-status-pane.png.

Cause and recommendation: selection and meaning are wrong as well as size. Stop copying the plan/log and missing-receipt filler into the primary summary. Use one current fact record for project and portfolio: state/current task, latest meaningful result and time, last-confirmed time, next action and current-work link. Put other reviews, checks, journal, estimates and previous updates behind Details. Repaint is not evidence of ongoing work; an old review must not override a fresh active task. Ten-minute confirmation updates one card rather than accumulating report blocks.

Concrete proposals are in `C:/dev/MBA Teaching AI/planning/WORKFLOW-ORGANIZATION.html`, with analysis in WORKFLOW-ORGANIZATION-PLAN.md: A uses Now / Latest / Next; B uses a short project brief. Root recommends A. Both are tested as project and dashboard cards across six example states and widths 280–380, with readable type, visible next action, optional details and the same task link. They sit alongside the retained course hierarchy. These are local prototypes, not installed status repairs.

Implementation acceptance remains open: real paired project/dashboard behavior, two scheduled intervals spanning refresh and interruption, honest freshness and current-review selection, usable links/history, narrow-window and larger-text fit, and no invented check or ETA receipts. The existing general reliability incident is not closed by this design delivery. Steward learning: journal/0122-compact-status-and-portfolio-meaning.md.

September11 final delivery check also found a managed text-link defect in shared.js delivRow: after refinement-open verification, preview.location is assigned /report?dir=...&path=... directly, bypassing the window.open shim that adds /steward, pid and token. This produces a failed navigation for Open current version on the analysis Markdown. The combined preview opens and its existing server-rendered Read the analysis link works; exact source/frozen bytes match. Add this ordinary-context text-opening case to general integration checks. No installed source was patched during the design proposal. Evidence: MBA .ecgberht/status-design/published-checks.json.


## September 11 — navigation delivered, status remains open
The course hierarchy now appears in the live Plan, Work product map and Deliverables. Current and earlier lecture files open correctly; managed Markdown opening was corrected. This removes the navigation/findability part of the incident. Compact status design A/B, mixed Working/older-review wording and actual scheduled project/portfolio status proof remain open. No status implementation acceptance is inferred. Formal record: Skill Foundry/planning/course-navigation-20260911; browser receipts: MBA .ecgberht/live-hierarchy/.

## September 15 — Chapter 1 review disappeared when the topic changed

New canonical intake: `2026-09-15-01-that-failure-to-put-something-you-asked` (open). John's original turn `0f856f33-1b05-425a-b3c0-e7c4e456598e` asks for Steward and Anchor to ensure that anything requested for review is immediately available in Current work and review, including Chekhov and other producers. The preceding Chapter 1 voice-sample and panel-location questions were avoidable user effort. This follow-up does not reopen a previously repaired stable-ID link bug; it documents a different review-selection failure.

Evidence: in `C:/dev/Writing/Artificial Magi/Book 1`, Chapter 1 v1 was registered and awaiting prose feedback. `.ecgberht/update-consistency-review.mjs` set `setup-chapters.navigation.current:false` while `waiting_on` still explicitly said John was reviewing it. The installed `steward_cockpit/static/shared.js`, `renderNavigation`, excludes an unmanaged item whose owner has that override. Steward conflated the current topic with the set of independently pending reviews. Journal0127's single-current-step instruction contributed an incompatible operating rule; it has now been explicitly superseded by Ecgberht journal0132 and the canonical skill/global rules.

The later campaign writer `.ecgberht/update-ghost-followup.mjs` restored chapter `current:true`, leaving the spine as the focus pin (event101, commit `d49f960`). That data correction already happened. The earlier browser receipt `.ecgberht/receipts/ghost-followup-reading.json` proves the chapter opens from a separate reading note, not that its own item stays in the Current work panel. No new live-panel, cross-provider or automatic-safeguard success is claimed here. No restart or Anchor engine source patch was performed.

Recommended repair: keep review visibility independent of execution focus, using the existing product/version lifecycle and register/roadmap ownership. Explicit managed presentation and scoped acceptance/deferral/replacement are authoritative; legacy reviews require original source-backed state, not invented acceptance or automatic campaign adoption. A focus-only update must preserve other outstanding reviews. Conflicting navigation metadata should be diagnosed rather than silently removing them. Do not add a second review registry or infer that every unapproved historical artifact needs review.

Real-session acceptance: present an exact chapter version and a separate spine note; both must be directly visible and openable in Current work and review. Change topic and producer skill, resume with another provider, refresh/reopen and wait through normal repaint; both remain. Accept, defer, withdraw or replace one review only and verify the other remains, with accepted/history versions still accessible. Repeat for managed and legacy campaigns, including a focus-only `current:false` conflict. Inspect the actual panel and intended viewer, not just file existence, API state or a link buried in another document. Ordinary independent work must continue without invented human waits.

The canonical intake retains John's words verbatim and appears in the generated open friction brief. Steward learning: `C:/dev/Ecgberht/journal/0132-pending-reviews-survive-focus-changes.md`; local account: Book 1 `.ecgberht/journal/0029-requested-review-visibility.md`. General implementation and verification remain open; this journaling request is not a deployment commission or permission to close the book's slice.

## 3 October: Doctor progress disappears when changing desktop app tiles

An additional observed child-cockpit ownership gap is documented in `2026-10-03-cave-inherited-status.md`: Cave status renders an empty local plan despite its Face delegating to the populated parent Campaign map. Actual acknowledgement does not prove the repair facts are in that pane. A canonical friction capture accompanies the evidence; the ownership/status repair remains open and is outside Doctor continuity repair v1.

New source-backed intake: `2026-10-03-01-anchor-doctor-loses-visible-progress-whe` preserves Cave turn `009cedae-66b4-487e-9092-4ce06a51483c` verbatim. [The diagnosis and proposed real-use checks](2026-10-03-doctor-app-continuity.md) distinguish a discarded/rebuilt iframe from stopped server work. Actually served app/Doctor pages reproduced missing session identity and visible progress after return; a simulated launch prevented paid activity. The actual latest healthcheck completed exit 0 with all 32 correctness checks passing and one non-blocking timing warning. The earlier paid-session history remains unproved.

Restore server-owned state and exact session/permission identity on return without implicitly launching a paid session. Verify during and after a controlled run inside the actual desktop window, with no duplicate launch and truthful completion. This is a proposed Doctor continuity repair, not a timer delivery outage, completed implementation or authorization to restart live sessions. Diagnosis v1 opens through the real Cave Deliverables bar and survives reopening; shared Anchor renderer and service code were unchanged.


## 5 October: stopped teaching job still looked active

Intake `2026-10-05-01-stopped-mit-teaching-job-left-old-slides` records MIT Lectures turn `13df8b1c-47f4-4666-ab35-28a69b67e9ed`. The [existing interruption report](2026-09-30-mit-lectures-interrupted-work-not-resumed.md) now contains the stopped-job evidence, separately identified stale-plan omission, concrete recovery and real-session acceptance checks. The committed 25-slide draft is recovered and its actual MAIN PDF opens and survives refresh; the independent review and current plan PDFs are being finished in a supported recovery job. Shared restart reconciliation and supervised-attention reliability remain proposed, not implemented or accepted. No engine code, running service or campaign acceptance was changed by this entry.


5 October recovery delivery: job `20261005-173455-5810f8` completed, and root integrated artifact-only commit `536af19` as MAIN `aecb937`. The 25-slide translation revision, Section 4 plan v2 PDF and course plan v2 PDF open through actual authenticated conversation and Current work links in the native PDF viewer; exact bytes and refresh persistence passed. Root corrected three legacy register labels to `CURRENT —` after live inspection found the delimiter missing, restored receipt-bound CRLF text after git conversion, and inspected all six viewer screenshots separately from a failed root embed selector. Evidence: MIT Lectures journal0028 and `translation-v2/checks/finished-main-inspection.json`. Attention is quiet and human feedback remains open. The independent text review actually returned; saved-file native Office reopening remains unavailable. Local recovery is delivered, while shared restart/status repair remains open and uninstalled.
