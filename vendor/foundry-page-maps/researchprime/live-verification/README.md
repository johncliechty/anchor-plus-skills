# Live researchPrime verification

**The evidence packet is complete; the live page does not pass every check.** Desktop and phone journeys produced **19 passes, 3 failures, no skips**. Both browser commands exited **1**, honestly preserving the failures.

- **Phone citation readability fails.** Anchor `a108` opens `sources/skill.md`, line 208, and the highlight is inside the iframe and screen. Its preformatted text extends beyond the phone viewport, hiding the end of the sentence, including “DECIDES.” Compare [phone](screenshots/phone-source-a108-L208.png) with [desktop](screenshots/desktop-source-a108-L208.png).
- **Console cleanliness fails at both sizes.** Chromium reports blocked script execution in the sandboxed source frame and in `about:srcdoc`. The returned source viewer includes an inline scrolling script. All console messages remain in the [machine receipt](receipt.json); the additional `srcdoc` messages' exact cause is unestablished. Request failures, HTTP errors, page exceptions, writes and injected auth headers were zero in the final monitored journeys.
- **The remaining checks pass.** The Library, touch dial, visible diagram, disagreement record, formatted documents, actual downloads and preserved feedback have fresh evidence below. This does not approve the product: John's **grade B**, **accepted:false**, **closed:false** remain intact. Independent Gandalf review is still for the steward to commission.

## What was tested

Live URL: `http://127.0.0.1:8777/foundry?skill=researchprime`. This is the tested local origin, not a promised remote access link. Final browser runs: **2026-10-07 14:07:31–14:09:03 UTC**, **08:07:31–08:09:03 MDT**.

The service reported **2229b5d+c934631** before and after both journeys. Its git prefix resolves to `2229b5db46d315d1ae3d249e8d6768a4e24bbf75`, containing `f9f1078`. Five served display assets match that commit, with CRLF normalization explicitly recorded. The live map payload equals this job's registered bundle: **42 process nodes, 67 edges, 35 knowledge nodes, 32 resources**. All **34 captured source files** were fetched and matched their declared SHA256 hashes and this bundle's bytes. This proves the served page and snapshots; it does not turn on-disk engine origins into runtime-execution evidence.

Fresh Chromium sessions used desktop **1440×1000** and phone **390×844**, pixel ratio 1. Phone input used mobile/touch emulation, not a hardware phone. Authentication used the normal local `/doctor` navigation and its server-issued HttpOnly cookie. Unrelated Doctor follow-ups were deliberately blocked before monitoring; no auth-header, token-query or injected-cookie bypass was used. No claim is made about John's existing Chrome window.

## Checks and readable evidence

| Check | Desktop / phone | Evidence and limits |
| --- | --- | --- |
| Normal authentication; live build, assets and source identities | Pass / pass | [Receipt](receipt.json): cookie attributes without secrets; exact build, asset URLs/hashes, source snapshot bytes and declared anchor targets. |
| Library layers and explicit zeros | Pass / pass | Descended levels 0→1→2→3 to a single resource leaf. Four kinds and their counts match each layer, including zeros; use frequency remains unknown. [Desktop root](screenshots/desktop-library-root.png), [leaf](screenshots/desktop-library-leaf.png); [phone root](screenshots/phone-library-root.png), [leaf](screenshots/phone-library-leaf.png). |
| Actual level dial | Pass / pass | Level 3→0 using a mouse on desktop and `touchscreen.tap` on phone, with a recorded `touchstart` event. No ArrowLeft or synthetic range-value change. [Desktop result](screenshots/desktop-library-dial.png), [phone result](screenshots/phone-library-dial.png). |
| Diagram nodes and edges in the viewport | Pass / pass | Every node was selected and its complete box visible at some point; native title text is at least 11 px. Every edge exposed ≥12 px of actual stroke after viewport/scroll-box clipping. [Desktop entry](screenshots/desktop-process-entry.png), [judge](screenshots/desktop-process-judge.png); [phone entry](screenshots/phone-process-entry.png), [judge](screenshots/phone-process-judge.png). The phone must pan: this proves visible labels and stroke segments, not simultaneous whole-map fit, complete long-edge visibility, or an independent judgment that the map is intuitive. |
| Instruction/code disagreement and source position | Pass / pass | Explicitly expanded the judge record and its disagreement: instruction, code behavior and what a run follows. [Desktop record](screenshots/desktop-disagreement.png), [phone record](screenshots/phone-disagreement.png). The actual `a108` link opens `skill.md#L208`; its quote/hash and vertical iframe/screen geometry were checked. |
| Complete cited text readable without horizontal clipping | Pass / **fail** | A DOM text range measures the overflowing text rather than the misleading full-width highlight box. [Desktop citation](screenshots/desktop-source-a108-L208.png), [phone clipping](screenshots/phone-source-a108-L208.png). |
| Formatted Human Guide, actual download and Back navigation | Pass / pass | [Desktop](screenshots/desktop-human-guide.png), [phone](screenshots/phone-human-guide.png). Fresh desktop evidence contains the formatted guide, unlike the prior review's recorded blank shot. Actual browser download `human.md`: **1,961 bytes**, SHA256 `3d207a10200aa6e896a6790cb17bc6bcfcd7b187f7ace5c904fd52739005557a`, byte-identical to the snapshot. Back returns within the live Library. |
| Formatted North Star, locked location, actual download and deep link | Pass / pass | [Desktop document](screenshots/desktop-purpose.png), [location](screenshots/desktop-north-star-location.png); [phone document](screenshots/phone-purpose.png), [scrolled location](screenshots/phone-north-star-location.png). Location and John-only LOCKED rule are readable. Actual `skill.md` download: **21,291 bytes**, SHA256 `33897bf9008f7c54e4f9bc5e3545fe8837b1d8dbcf36f403c67d56f00327c2a8`, byte-identical to the snapshot. The document's process link routes within the live page. |
| Grade B and open lifecycle | Pass / pass | [Desktop](screenshots/desktop-review-record.png), [phone](screenshots/phone-review-record.png). The complete cumulative feedback and lifecycle equal the registered payload, retained in the receipt. |
| No request errors, page exceptions, writes; stable build | Pass / pass | [Receipt](receipt.json): zero monitored failures/errors/writes and matching start/end build. This excludes intentionally blocked pre-test Doctor follow-ups. |
| No console errors | **Fail / fail** | [Receipt](receipt.json): exact messages, timestamps and active check; no filtering or green reclassification. |

All **22 final screenshots were opened and visually inspected**, then bound to their exact dimensions, byte counts and SHA256 hashes. They are new captures; no deleted previous-job image was recovered or reviewed.

## Recovery and replay

Before adapting the procedure, this job read the retained Anchor branch's `tests/test_foundry_page_walkthrough.py` and the actual prior gate/reviewer/run receipts under `C:/dev/Skill Foundry/Foundry page and knowledge maps/.ecgberht/foreman/20261007-071029-ff8ea0`. The gate really records 52 individual passes and exit 0; the reviewers record a blank desktop guide screenshot, and the run ends HALT on generated-screenshot coverage classification. Those prior observations are preserved with source hashes in the receipt; they are not this job's visual observations. The subsequent zero-file/all-launch-failed audit described in the commission supplies no independent verification here.

The adapted [verification program](verify_live.py) retains the live walkthrough and citation geometry while adding touch input, actual clipped SVG/text geometry, paint settling and complete error monitoring. It imports no Anchor modules, starts no server and issues no application writes. Early setup failures and corrected test assumptions are recorded separately from final live findings.

From the repository root, with installed Python Playwright/Chromium, run:

```powershell
python -X utf8 "Foundry page and knowledge maps\researchprime\live-verification\verify_live.py" --viewport desktop
python -X utf8 "Foundry page and knowledge maps\researchprime\live-verification\verify_live.py" --viewport phone
```

Each command writes a fresh transient receipt under `_scratch` and updates its screenshots. The durable [receipt.json](receipt.json) freezes this run's commands, individual outcomes and actual exit codes. Replaying against a changed service is a new observation and must not be represented as this frozen packet.

Only this evidence folder was changed. Production, gates, review links and campaign/lifecycle files were untouched; Anchor was not restarted. This worker leaves the packet for the owning Anchor job to commit and land, as instructed. It accepts no refinement and closes no slice.
