# Week 1 products present but hard to find and navigate

John reported this in the Math 541 Student Resources cockpit on 2026-09-08: promised products were not apparent under Week 1 or at the top of Deliverables. Campaign overhead increased by one.

Observed in the live service: both effort and union registers had all four files. The renderer truncates What at its first em dash, leaving the primary guide labelled only START HERE. Step matching placed the four links under distant artifact steps instead of the main Week 1 Foundations step. This was not missing output or a wrong project register.

Campaign correction: descriptive Week 1 Foundations prefixes, PDF format before the separator, first four register rows and exact main-step association. Durable rule added to campaign AGENTS.md; no duplicate register.

Opening the real served HTML also exposed broken sibling navigation. Relative paths resolve against the query endpoint; retaining the API endpoint is rejected by the opaque-origin navigation guard. Campaign HTML now uses the existing contained /artifact route for sibling navigation, preserving local relative links when downloaded. No security relaxation or Anchor code patch.

Acceptance passed on the running service: four recognisable top rows and main Week 1 links; all four documents HTTP 200; actual register click opened the example; radius/endpoint controls worked; click to cards succeeded and reveal worked. Evidence lives at C:/dev/Teaching/Math 541/Student Resources/reviews/week-01/delivery/live-delivery.json and the adjacent live screenshots. This does not claim verification on John's device.

For the Anchor owner: consider showing the first pending-review artifact without generic-prefix truncation and document a supported contained sibling-link mechanism for HTML producers. Any future change must preserve sandbox isolation and be checked through an actual cockpit click, not just API response tests. This note records the defect for the normal improvement intake; no app change is commissioned here.

## Steward/cockpit follow-up at John's explicit request

John also had to ask whether the standing Elegance/Rabbit-Catcher checks were being used in plan creation, then asked that this be journaled for the Steward skill working with the cockpit. The full assessment had not been recorded; it is now applied in the existing Week 1 plan, and the visible roadmap was updated. That omission belongs to steward execution; it is not evidence that Anchor caused it. The UI delivery faults above and this planning omission share the consequence that John had to police readiness claims.

Existing local corrections are verified, not merely proposed: clear current product labels and main-step links, contained HTML navigation, instructor-only solution separation, and an updated plan opened through the live register. New evidence: C:/dev/Teaching/Math 541/Student Resources/reviews/week-01/delivery/live-plan-check.json and PNG. The review drafts remain available to John; specialist validation and student release are still pending.

Recommended general improvement: connect the product shown in the existing register/roadmap to the actual required-review state and its evidence, so a present file or generic done label cannot imply completed validation. Have stewardship check the current plan assessment and live opening path before declaring a handoff. Reuse existing surfaces; do not add another registry, approval system or status narrative. The protocol/engine improvement is proposed only, not built or commissioned by this journal request.

Real-session acceptance: create or revise a plan, see the correct named product under its work step, open it from there, show pending specialist checks accurately, and retain the updated state across refresh. An instructor answer key remains labelled in John's review workspace and excluded from student navigation/downloads. No claim that these checks were performed on John's device; no fabricated acknowledgements. Steward counterpart: C:/dev/Ecgberht/journal/0112-math541-products-must-open-from-the-live-cockpit.md.

## September 9 pickup: a teaching question appears as an approval wait

The live Math 541 cockpit screenshot `Student Resources/reviews/week-01/delivery/live-deliverables.png` (September 9, about 14:19 local) shows a red “waiting on your answer” banner quoting the steward's explanatory question about finitely many sets covering infinitely many points. This was a teaching objective in a progress message, not a question asking John to authorize work. ECGBERHT.md and the current strip instrument both say human wait is none; work is explicitly authorized. The same screenshot correctly shows the attention line as working and the four revised deliverables first, so these are distinct state readers.

Root-cause assessment is bounded: the banner consumes a different interpretation of the dialogue than the explicit human-wait/attention state and has misclassified this passage. The particular parser branch has not been established; no runtime fix is claimed. Proposed general improvement: prefer an explicit unresolved decision record for an approval banner and suppress historical/rhetorical teaching questions when current authorization and human_wait=none say work continues. Acceptance should include a rhetorical question in a progress message, a real one-question decision, a later explicit go, and a session pickup; only the real unresolved decision should raise the banner. Keep the normal cadence pane and attention reader intact.

Two review processes were also absent after the parked session, with stale start records and no final receipts. The exact termination cause is unestablished. Recovery used a hidden Windows process-service launch of the existing ConPTY wrapper, with durable per-run PID/result files. New supervisors refresh attention from observed live child state. This is a project-owned run wrapper, not an Anchor or installed skill-engine repair; survival of another real host shutdown is not yet verified. Product revision and review continued while this defect was recorded.
