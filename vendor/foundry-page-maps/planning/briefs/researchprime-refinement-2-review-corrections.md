# researchPrime Refinement 2: apply actual review findings before integration

Continue John's authorized researchPrime-first grade-B Refinement 2 scope. Content landed at 3e3ba03d893eb1f6c0c0197a456ac0a3a3378366 with 54 passing tests. Do not reconstruct it, start other skills, change skill engines or close/accept the campaign. Scope: effort researchprime/ and shared/ display components, existing tests/browser checks and associated generated evidence. Preserve Refinement 1 frozen bytes and cumulative feedback, accepted:false and closed:false.

Read actual review .ecgberht/foreman/20261006-212041-ef9f20/wave-1-review-0.json in the effort folder. It retains open findings despite GO. Correct each before dependent integration:

1. shared/flow-diagram.js:129, researchprime/display.css: 1046x2224 drawing forced width:100% shrinks 11px labels to about 4px at 390px viewport. Provide readable tappable nodes with contained pan/zoom or equivalent. Keep canonical reusable components and bundle copies consistent. No page overflow alone does not prove readability.
2. researchprime/display.js:104 and :204: Process opens step text above the diagram and scrolls it into view. Lead with the architecture diagram on desktop/phone, default to process.entry and retain accessible click-to-expand details.
3. researchprime/check_browser.py:209: phone proof was weakened from failed node interaction to tab-heading prefix. Restore real phone clicks on diagram nodes, level dial and source buttons with assertions on resulting selected node/detail/source. Add a regression that fails on current illegible diagram. Inspect final desktop and phone screenshots; no existence/count-only or mocked replacement.
4. shared/layer-library.js:32: show all four Library kinds on every layer, including explicit zeros rather than truthy-filtering missing kinds. Verify layers with absent kinds.

Use existing test_maps.py as external gate and extend existing checks meaningfully to reach these defects. Regenerate browser evidence against final bytes and inspect screenshots. Preserve original reviewer receipts; record each finding's correction and evidence, then obtain independent review of exact changed final bytes. Resolve findings even if internal Foreman classification skips them. Reject a finding only with reproducible contrary evidence, not GREEN alone. Do not patch Foreman or weaken safeguards.

Keep DELIVERABLES.md accurate: artifact corrections in progress, Anchor integration/live activation pending. /foundry?skill=researchprime is the existing route, not proof of Refinement 2 activation. Land scoped corrections and hand back explicit test and evidence references for subsequent Anchor integration; no new human acceptance request needed.
