# Wave 4 evidence and handoff

## Outcome

The bounded implementation is functionally green across Trio/Jumper, Tidy,
Literature Review, Ramanujan's capability boundary, and Anchor's affected surface.
It is **not ready to release** because Ecgberht's complete deterministic gate has
five red WH4 conversational-kickoff cases.

Those failures are narrow and understood: the current dirty kickoff/synthesis
prompt changed, while the acceptance fixture remains a real, prompt-hash-bound
Steward recording from August 6. The bridge correctly refuses the mismatch. The
old reply must not be relabeled with new hashes.

## Green evidence

- Trio: 189 passed, 5 explicit live skips; Jumper: 42/42.
- Ecgberht shared-Trio adapter: 46/46; seal-chamber contract: 30/30;
  auth lane: 125/125; Python bridge: 30/30.
- Tidy-Idy: 494 passed, 1 explicit host-capability skip.
- Literature Review: 934/934.
- Ramanujan boundary: 64/64, with real-tool lanes disabled.
- Anchor affected surface: 378 passed, 2 explicit Windows link-capability skips.
- Relevant syntax and bounded diff checks passed.
- The user-global model preference file retained its exact baseline hash.

## Blocked evidence

Ecgberht skill lane: 1156 passed, 5 failed. All five are in
`test/wh4-conversational-steward.test.mjs` and fail closed at the prompt-bound
seat-replay seam. See `WAVE4-EVIDENCE.json` for their exact names.

## Recommended next step

With explicit approval for a live model call, record a new Steward session against
the current kickoff/synthesis prompt using the configured production seat, inspect
the resulting reply and receipt, rerun WH4, then rerun the complete Ecgberht gate.
Only after that gate is green should Fable perform the prepared read-only
adversarial review. Commit, push, merge, and deploy remain separate approval steps.

If a live fixture refresh is deferred, preserve this as a blocked development
handoff; do not call it release-ready and do not weaken the prompt-drift guard.

## Safety boundaries retained

- No Fable or live model was invoked.
- No OAuth/provider connection was attempted.
- Calendar and Email remain empty synthetic onboarding previews.
- `_mockups/dashboard-v2` remains untracked and distribution-excluded.
- No commit, push, merge, deployment, or broad dirty-worktree cleanup occurred.
