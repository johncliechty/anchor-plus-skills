# 0060 — Image generation interrupted across a resumed turn

John, turn `44945d59-ac47-4398-9f84-88187ff27f3d`: “Where are the updated drawings? It seems like you got ‘rebooted’ somehow. Please investigate and journal about this.”

## Findings

The native ChatGPT conversation identity remained `01a0c676-bddd-72f2-a43f-d33d1598108d`. The durable history prefix was unchanged; all 236 current turns were read. This was not a new conversation or loss of the author's decisions.

The native rollout records turn starts at 08:49:22 UTC, 09:02:55 UTC and 09:07:31 UTC on September 27. It records the first image orchestration cell still running at 09:00:59, then `exec cell 9 not found` at 09:03:28 after the resumed turn. Two actual PNGs survived, written at 08:58:10 and 09:01:05. No completed third image or saved result was found when recovery was checked. These two were inspected, copied into the project and preserved under `visuals-v3/pre-cover` before the requested hiding-place edits.

Anchor's live state retains the same session ID and contains no September 27 interruption reason in its routing events. Its resume code deliberately prefixes the next message with “waking from a parked session”; that wording alone does not prove a fresh model conversation. The inspected local reaper receipts around the transition report zero killed/frozen processes. No matching recent transport error was found in the inspected error-log tail. Default bridge watchdogs are two hours per turn and fifteen minutes idle, which does not itself explain this transition. The initiating stop/restart cause is therefore unconfirmed; do not call it maintenance, a timeout, a reaper kill or a user-requested cancellation without further evidence.

## What failed and what changed

The immediate recoverability failure is confirmed: an in-memory execution cell and its unreturned batch results did not remain available after the transition. Jarvis compounded it by leaving completed drawings outside a usable current-work gallery while preparing the whole package. John had to ask where they were. This is overhead: cumulative count rises from 7 to 8.

A clearly marked partial gallery was published at the intended final URL and opened with normal browser authentication; both recovered drawings loaded. The same setup-chapters navigation now points to it alongside the independent Chapter 1 Review 3. The continuing generation copies each completed image and writes an individual provenance receipt immediately after that result, before waiting for the other images. Existing files are recovered before any repeat call. This reduces loss after an individual result; it is not durable supervision of a still-running remote call and does not repair the shared engine.

The complete gallery will replace the preview at the same URL. No new prose, chapter acceptance or slice close follows. The final selected architecture remains unchanged.

## Proposed general repair, not installed

Anchor should durably record every park/stop/restart reason and the state of outstanding external calls before transport teardown. On resume it should reconcile completed artifact receipts and uncertain jobs without replaying finished work. A queued human clarification should be steered into the active task when possible; if interruption is necessary, retain exact pending work and report the interruption once in plain language. Pending calls require an honest active/uncertain indicator; a partial result should be directly accessible as soon as it exists.

Acceptance checks: start a multi-image call, deliver a mid-run refinement, deliberately restart transport after one image completes, then verify the same conversation, preserved image, visible partial gallery, explicit unfinished jobs, no duplicate paid calls, correct attention, and final current-work links. This has been recorded for Anchor's normal improvement intake; no app repair or restart is commissioned by this investigation.


Canonical friction record: 2026-09-27-01-salt-hall-image-batch-lost-running-handl (open).
