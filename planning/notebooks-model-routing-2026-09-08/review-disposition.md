# Grok review 1 dispositions and recommendation

Actual reviewer: Grok subscription CLI, served model **grok-4.6-build**, model_attested:true, cross_model:true, completed 2026-09-08T14:41:28Z. Both v1 plans received **revise**. Raw output: grok-review-1.json. The review is of supplied plans/evidence, not an independent live code or execution test.

| Finding | Decision and v2 revision |
|---|---|
| A1 stored policy missing | Accepted. A1 names versioned settings/mirror fields, visible Latest supported + Ultra selection/default, migration, exact deployment-local resolution and precedence. No hidden personal-config dependency. |
| A2 remove automatic failover | Rejected as contrary to John's standing Rule 3. Accepted the risk of hidden substitution. A4 specifies the authorized candidate order, failure classes, no unsafe replay, UI/receipt/journal events and verification fail-closed rules. Current source has a Claude-only coding fallback; that insufficiency is a formal repair target. |
| A3 unproven cockpit transport | Accepted. A3 makes two-turn subscription transport/cancel/resume/permissions a first implementation proof with an explicit revision gate if exec/resume cannot satisfy it. A plan cannot truthfully claim that unrun proof already passed. |
| A4 inventory/freeze/cache ambiguity | Accepted. A2 bounds six production surfaces, maps known seams, requires caller conformance, defines session/job/seat freeze and pending interactive rollover. Cache is deployment-local, not release material. |
| B1 remote-auth architecture | Accepted the need for a firm architecture and early proof. B3 chooses Jupyter's own cookie/password on its HTTPS origin, token-free Anchor redirect, fresh sign-in/renewal and real WSS/iPad tests. Rejected the premise that Anchor auth must become Jupyter auth; separate sign-in is intentional and documented. |
| B2 durable associations/surfaces | Accepted. B1 gives an adjacent versioned companion format and contained Where path; all three UI handlers use typed shared resolution; missing setup cannot paint a live action. |
| B3 size/MAIN/lifecycle | Accepted. B2 has one 1 MiB technical cap, no pedagogical length cutoff, scoped MAIN persistence before teardown and recoverable completion. B4 uses a dedicated persistent Jupyter adapter, not preview lifecycle. |
| AB1 distribution/formal cycle | Accepted. Both release gates include the real packages, version compatibility, installed helper paths, formal skill changes, synthetic clean-install proof and content/secret exclusions. Do not serialize unrelated work unnecessarily: Jupyter auth proof can proceed alongside model repair; each feature retains its release gates. |

Additional source-backed tightening: login is renewable, not forever; a local Jupyter server may use remote kernels, so verify local specs plus runtime host; R must work under the service account; root_dir is not security isolation; workspace restoration requires exact active-tab assertions. Sources are in source-notes.md.

## Recommendation

Implement both revised plans through the formal journal-backed repair process, with Jupyter as the only Python/R execution surface in this release. Begin with small, falsifiable transport and notebook auth/host proofs, then shared model policy and durable producer/launcher integration. Ship only after your real surfaces and a clean collaborator installation both pass. This is a recommendation for the next implementation task, not a claim that the code, notebook execution or packaging has already been repaired.

Tradeoff: reliable setup and portability require host dependency/service/auth configuration; a collaborator download alone cannot supply R, Jupyter, tailnet access or model subscriptions. The benefit is a supported setup path with explicit missing-capability messages rather than machine-specific workarounds.

## Follow-up Grok verdict

Second actual subscription review completed 2026-09-08T14:51:05Z, again served by **grok-4.6-build**, model_attested:true, cross_model:true. Verdict for both v2 plans: **ready_for_implementation_planning**. Findings: **none**. Grok explicitly accepted the revised Rule 3 failover ladder and closed all eight prior findings. One genuinely dry review ends the loop; no further review rounds were launched.

The review does not establish implementation readiness of untested transports or a successful deployment. Remaining gates are the specified Codex/Grok conversation proofs, Jupyter authentication/WSS/local-kernel proof, service-account setup, actual iPad access, restart recovery and clean-package installation. The older seat_unavailable cause remains unproven and is not relabeled quota.

Implementation clarification from the follow-up: operator-approved extra fallback families have no v1 settings schema, so the v1 extra list is **empty**; only the configured coding/review/terminal families form that release's ladder. Adding extras needs an explicit versioned policy change, not an ad-hoc script or guessed family.

Raw follow-up: grok-review-2.json, retaining its brief leading narration plus final verdict JSON. The exact reviewed v2 texts are embedded in grok-review-2-input.md. No v2 plan content was changed after that review.
