# 0035 — Steward/Anchor handoff failure and latency investigation

8 October 2026. Requested by John, turn `a9ed1fff-f8a1-43bf-86c5-0b0f8b80ef4d`, at 23:28:29.962326 UTC (17:28:29 Denver). Investigated the actual job records, original coder transcript, current application source, render receipt and durable conversation. This is a diagnosis and journal, not an implemented application repair or a completed teaching review. No slice closes. Session overhead increases from 2 to 3 for this corrective request.

## Finding

The handoff contract is defective in two independent ways. First, Anchor collects authored paths only from a narrow set of recognized native file-edit events. In this Codex job, actual `tools.apply_patch` edits were inside the supported `exec` orchestration tool. Anchor recorded an empty manifest and rejected even the new generator. Second, generated PDF, PowerPoint, HTML and image outputs are legitimate commissioned work, but the landing rule requires each changed path to be in that native edit manifest. Exports created by the generator cannot meet that rule. The previous two main jobs hit the second defect; the latest hit both.

The safe behavior is to preserve unreviewed work. The defect is commissioning a normal build while providing no adequate route to recognize, review and deliver its actual output. This failure is not evidence that a reviewer rejected the work: each failed main job has `review: null` and `check_ok: null`. Refusal happened before those stages. No content verdict or independent v5 review is claimed.

## Repeated cases

| Product/job | Local recorded start–finish | Worker/finish interval | Recognized changed files | Other changed paths | Outcome |
| --- | --- | --- | --- | --- | --- |
| v3 / 20261008-112003-495d32 | 11:20:05–11:46:02 | 25m57s | 4 | 32 | done; not landed; no automatic review |
| v4 / 20261008-124237-7edff8 | 12:42:39–13:16:53 | 34m14s | 1 | 36 | done; not landed; no automatic review |
| v5 / 20261008-171225-376fa8 | 17:12:27–17:25:48 | 13m21s | 0 | 60 | done; not landed; no automatic review |

The tiny source-only correction jobs did land into the preserved worktrees after independent review. That contrast supports the manifest diagnosis; this is not a universal inability to place any delegated work. The v3/v4 teaching products were subsequently recovered and delivered. Their original job records still describe the original refusal, so those records alone must not trigger replay of completed recovery.

## Exact mechanism and evidence

`C:/dev/Anchor/steward_cockpit/code_jobs.py:335–343`, `manifest_of`, uses only `engine.written_ok`. `steward_engine.py:3051–3084` populates it for successful Write/Edit/NotebookEdit events or completed file_change events. It does not extract a nested apply_patch operation from exec. The native coder transcript is `C:/Users/john/.codex/sessions/2026/10/08/rollout-2026-10-08T17-12-29-01a11dca-2389-74d3-81e6-03e7227ebe7a.jsonl`. It records three exec calls containing `tools.apply_patch`, at 23:17:17.768Z, 23:17:44.695Z and 23:22:16.453Z, with completed tool outputs and the generator present on disk. Job metadata nevertheless records `manifest: []`, `files: []`, actual author family `chatgpt`. The coder did not merely ignore the instruction to use file tools.

`code_jobs.py:706–715` compares all changed paths with that manifest. Any unexpected path immediately selects the not-landed branch. Check, candidate commit and independent review are in the later branch. The generic coder instruction at lines654–664 tells the coder to use file tools, run checks and finish, while promising only tool-written files land. Our brief required a rendered 22-slide teaching product. These requirements do not compose: running the existing generator necessarily creates files beyond direct source edits.

`code_jobs.py:710` also labels a clean coder exit `done` even when placement is refused. Completion of production, review, landing and human publication are separate facts; one success-shaped state cannot stand for all four. At inspection the busy-repository map was empty, but the effort attention file still said the v5 build was working. It was corrected to quiet after confirming completion. This is an observed stale heartbeat, not an invented human-wait state.

The preserved v5 worktree remains at `C:/Users/john/AppData/Local/anchor-code-jobs/20261008-171225-376fa8`. Anchor has also registered readable kept copies in this effort. Its saved v5 PDF hash is `cbe958eafee41791567656ce7f20a2b23792687666ec38e1323ca5727918941e`; PowerPoint hash is `7595735d503090b4836977da50b17beee4d3038c79298b37a6cba0c013f73035`. These identify the preserved pair, not an accepted or independently reviewed pair. V4 remains the current delivered deck. V5 requires review and controlled placement under its existing authorization; this investigation does not repeat its build.

## Why it took so long

All wall-clock intervals below are elapsed time, not billing or exclusive compute time.

| Stage | Evidence and measured interval |
| --- | --- |
| Steward preparation before v5 start | John's density request at 23:07:43.710856Z to recorded job start 23:12:27Z: approximately 4m43s. Included earlier-example inspection, outlines, both readable plan updates, roadmap alignment and the job brief. |
| V5 worker through refusal | 23:12:27Z–23:25:48Z: 13m21s. The transcript contains31 exec calls, development, rendering, inspection and final checks. It does not support attributing every second to one inner activity. |
| Final v5 native render/export | Saved render receipt 23:22:17.415506Z–23:23:49.853814Z: 92.44s. This is one render pass inside the worker interval, not the entire build. |
| Post-finish publication | First kept-file receipt 23:25:50.099071Z; final PDF/PPTX receipt 23:29:01.396320Z: 3m11.30s, or approximately3m13s after recorded finish. There are53 kept-file receipt turns. The useful final pair appeared last. John complained while publication was still underway. |
| End-to-end v5 handback | Density request to final kept-pair receipt: approximately21m18s, still without independent review or landing. |
| Prior v4 recovery overhead | Original finish13:16:53 to delivered reply13:37:15: approximately20m22s in addition to its34m14s worker interval. Source: durable history and journal0033. |

`code_jobs.py:999–1000` calls `announce_kept` synchronously before waking/notifying the steward at lines1020–1022. `announce_kept:1038–1049` loops over every readable file and calls `deliverables_register.register` for each. That helper at line221 synchronously calls `notify_receipt`, which scans/publishes the register. The observed53 serial receipts and increasing register provide direct evidence of a poor publication path. Individual call CPU costs were not instrumented, so no precise complexity or CPU attribution is claimed. The steward notification waits behind the entire loop.

V4 additionally hit the existing review adapter's400000-character limit because its static HTML embedded about4.5MB of PNG data. Recovery represented that large file as binary for the reviewer while retaining authored source and small JSON, and inspected actual pixels separately. A wording defect then required a small isolated correction and a fresh export/review. The safe lander needed scoped shared-index reconciliation. Finally, my browser checks wasted time on folded controls, ambiguous duplicate links and premature reads after reload. Those retries were avoidable Steward overhead. Technical checking was necessary; repeatedly rediscovering routine delivery controls was not.

PowerPoint saved-file opening remains unavailable in this environment. The existing reconstruction route produced the render/PDF evidence. That limitation accounts for some export work, but does not explain the manifest refusal or the serial receipt delay. It must not become a blanket excuse for the whole elapsed time.

## Repair requirements to carry into Steward and Anchor

These are evidence-backed requirements for a later authorized repair, not a claim that code has changed.

1. Recognize actual supported native/nested edit provenance across providers, rather than treating a wrapper event as evidence that no edit occurred. Do not trust a model's textual manifest without corroboration.
2. Give commissioned build outputs an explicit scoped route into the candidate: approved output roots, isolated before/after inventory, exact hashes and successful build/check evidence. Review source plus generated artifacts as appropriate. Continue rejecting out-of-scope files, failed writes, served-tree writes and concurrent conflicts; do not solve this by allowing every dirty path.
3. Keep produced, awaiting review, blocked placement, landed and published distinguishable. Preserve the result and a deterministic next recovery action when placement cannot proceed. Reconcile previous recovery before retrying a stale completion notice.
4. Publish one useful handback bundle first: matching PDF, PowerPoint and preview, clearly qualified if not yet landed. Keep per-slide images as supporting evidence without flooding the conversation. Batch register writes/notification, and do not delay steward wake behind auxiliary receipt publication.
5. Make ordinary artifact review and shared-index placement work without recurring base64 diff failures or manual index repair. Review coverage must stay explicit; representing an image-heavy artifact as binary does not itself review its appearance.
6. Steward must inspect the handoff contract before commissioning the same kind of job again, carry this defect into the next brief, reuse stable delivery controls, report measured stages, and keep attention true. Formal skill-engine improvements go through the existing Foundry improvement route; Anchor program changes go through an isolated code job and another-family review. Foreman/Crucible remain on hold.

The same diagnosis is filed in Anchor's existing docs/friction journal and Ecgberht's human/machine usage journal. No application or skill code is patched as part of this investigation. No new validator, skill run, lifecycle adoption, slice closure or acceptance is invented. This legacy campaign has no refinement_update event; the conditional managed producer handoff is therefore inapplicable. Existing cumulative teaching feedback and authorization remain intact.

Publication verification: the installed register posted the report Read link; normal authenticated browser requests returned HTTP200 for the rendered Markdown and exact source bytes. The served source hash matched the saved report. Roadmap seq134 records v5 recovery outstanding; attention is quiet.

Subsequent authorized recovery: v5 passed attested Gemini3.8FlashHigh review and was placed as main6348ad9a9caa5274de2bc3646eeb349fa49743b2, after exact60-path candidate-blob verification and scoped shared-index reconciliation. Normal browser PDF/PPTX/preview routes and refreshed Current-work pins passed. V5 is now delivered for teaching feedback; the original job refusal remains historical and must not trigger another build. This recovery does not repair the Anchor/Steward application defects. Receipts: MIT Lectures/.ecgberht/v5-recovery/{review,landing,live-delivery}.json. No slice closes.

## Direct PDF correction and remaining link defects

John turn `52cc8359-683b-4340-be3e-a658dafc752d` requests the PDF in Next steps and reports broken HTML links. Placement made the matching PDF appear 0.0918939 seconds older than its PowerPoint. The timestamp-based stale-PDF filter consequently removed the verified PDF and selected HTML. Root verified both hashes against the same-version render receipt, reconciled only the PDF timestamp, and moved its existing register row first as `START HERE — Einstein v5 PDF — 22 slides`. No PDF or application bytes changed. The disk-backed Next steps reader now selects that PDF; its shared conversation receipt opens the verified 22-page copy. Live Next steps repaint remains unverified: the authenticated deliverables API timed out after 12 seconds and the pane rows were unavailable during bounded inspection.

All five visible Offline navigation links return 404 in the served HTML: relative filesystem links resolve against the API route rather than the artifact directory. Earlier checks covered only the five Online navigation links and did not establish that every visible link worked or that the default Next steps action selected PDF. The additional timestamp and served-link defects remain outstanding program repairs; metadata reconciliation is not a permanent Anchor fix. Exact evidence: `MIT Lectures/.ecgberht/v5-recovery/pdf-next-steps.json`; receipt: `journal/0036-direct-pdf-next-steps.md`. Session overhead is 4; no slice closes.
