# Plan A v2 - reliable, portable model selection

Revised after Grok review 1. Plan only; transport proofs, implementation and release gates remain ahead. Companion plan: notebook-deliverables-v2.md. The recommendation and review dispositions are in review-disposition.md.

## A1. Stored product contract

Keep family authority in Anchor settings.json and its existing mirror. Add this versioned policy to that same contract (proposed schema, not yet written into live settings):

```json
{
  "model_policy_version": 1,
  "provider_policies": {
    "chatgpt": {"mode": "latest_supported", "effort": "ultra", "scope": "all_chatgpt_production_seats"}
  }
}
```

Selecting ChatGPT offers and persists the clearly labeled **Latest supported + Ultra** policy in the existing model controls; it is the default for a new ChatGPT selection. Show effective model/effort beside the selection. Migrate an existing ChatGPT selection to this documented default once, visibly, without changing coding/review/terminal family choices. A non-ChatGPT-only installation is not assigned a ChatGPT model. This explicit policy overrides ordinary ChatGPT tier notches and stale caller pins; record its precedence in the canonical Foundry tier instructions through the formal improvement cycle, not a second tier definition. Future alternate policies are outside this release.

Settings changes carry one revision and atomic writes; the mirror includes that revision. Primary wins, mirror is a fallback when primary is absent; unreadable/invalid authority is an error, not permission to guess Claude. Define and test partial/mismatched mirror recovery. A failed settings save cannot show success. The policy itself contains no John's-specific model ID or filesystem path.

Resolve a deployment-local exact tuple `{family, model, effort, role, settings_revision, capability_timestamp, requested_policy, policy_source}`. A versioned schema and shared conformance fixtures bind the Python and Node consumers. Cache under the installation's Anchor state directory, not shipped source or skills. Use the current officially supported target and installed authenticated CLI catalog; do not sort IDs lexically or invent a model name. Currently John's validated target is Astra/Ultra. Refresh boundedly on CLI/policy changes and capability expiry; a last-known-supported selection is visibly stale, not called newly verified latest. Absence of a supported tuple is explicit unavailable. Account access is not supplied by the package.

## A2. Bounded caller release checklist

| Surface | Existing seam / bypass to repair | Required proof |
|---|---|---|
| Doctor | anchor_gui.py status initialization and backend-omitted start; terminal_session.py doctor launch | Auth-first UI; server policy resolution; no initial Claude launch race |
| Steward cockpit | steward_routes.py get_engine; steward_engine.py constructor, wake, switch and resume | Actual provider transport, not only a different label/argv token |
| Anchor terminals | terminal_session.py engine argv; project/sticky session restores | Explicit resolved tuple; saved IDs scoped to provider; visible pending switch |
| Anchor jobs | codex_adapter.py CODEX_MODEL/EFFORT and isolated config; job_runner dispatch | Explicit tuple survives ignore-user-config; structured outcome/receipt retained |
| Trio | drivers/index.mjs role dispatch; chatgpt-cli.mjs defaults and model/effort precedence | Heavy/standard/untiered calls obey the stored policy; no stale explicit/env pin bypass |
| Foundry/Steward producers | Production manifest and driver call sites, including Ramanujan tools.manifest.json; distributed custom agents/helpers | Same policy through installed seams; all production ChatGPT subagent overrides covered |

Before coding, enumerate actual call sites within these six surfaces into this checklist using bounded source searches. Each has a conformance case; unresolved bypasses block the claim 'everywhere'. Historical fixtures, unrelated products and archived conversations are not rewrite targets. Discovering a live custom agent in these paths is in scope; generalized user-home archaeology is not.

Freeze provider/model/effort for a logical session, job or independently dispatched seat, not individual tool calls. Settings changes do not interrupt in-flight work or rewrite its receipts. New jobs/seats see the new revision. Existing interactive chats show selected versus active provider and a pending switch; after the current turn is complete, before accepting the next new message, roll to a new provider session with visible history handoff. Never reuse a provider-native session ID across families. Queued unsent messages stay queued until the switch succeeds. Restart restores pending-switch state. A run may therefore contain differently resolved seats, but every seat carries its own revision and actual provider.

## A3. Doctor and real cockpit support

Doctor enables AI launch only after authenticated status succeeds; an error remains an error. Backend-omitted calls resolve policy on the server. Explicit one-session provider buttons are labeled and do not mutate global settings. The server rechecks the revision at launch to reject/re-resolve a stale client selection instead of trusting a cached Claude default.

First implementation gate: a small Codex subscription transport proof, using synthetic conversations only, demonstrates two turns, returned native thread ID and resume, streamed/result events, cancellation and child cleanup, permission refusals, disconnect/reconnect, retained partial output and no duplicate replay. Start with supported exec/resume behind the Engine interface; if its protocol cannot meet these requirements, document the exact deficit and revise the transport design before claiming cockpit support. This is an unproven engineering gate, not a success asserted by this plan. Keep existing provider adapters separate. The selected Grok transport also requires its own conformance test; no provider receives Claude-only stream flags.

Ultra and subagent defaults are applied explicitly at every ChatGPT launch/spawn, including custom agents. Do not enable broader filesystem/network permissions to satisfy effort selection. Where a job's safety contract disables delegation, report that restriction separately from requested effort; do not advertise the full automatic-delegation capability while suppressing it invisibly. Official model and subagent references are in source-notes.md.

## A4. Visible failover, per John's standing rule

Do not adopt Grok A2's proposed blanket ban on automatic failover. John's Rule 3 requires capable-model continuation with immediate journaling. Source inspection adds a concrete defect: Trio's current dispatchWithFailover sends failed non-Claude coding seats only to Claude, while verification fails closed. That ladder can stop when Claude is exhausted even though Grok is usable. Repair it through the formal cycle, not a one-off retry script.

Proposed bounded ladder contract: selected provider first; on a confirmed provider availability/quota/auth failure, try the remaining configured coding/review/terminal families, de-duplicated in that order, followed by any separately operator-approved installed fallback families. Skip known-exhausted/unsupported candidates; one dispatch per candidate, no reset-wait loop. Do not introduce an unselected family merely because its executable exists. This adds a documented selected-family ladder where the current Claude-only fallback is insufficient. Each candidate must support the needed seat protocol/tools; a name in settings alone is not capability proof. User cancellation, invalid local input/configuration, and ambiguous in-flight side effects do not trigger blind replay on another model. Preserve the work and report the specific recovery boundary.

Before launching a fallback, journal the failed model/seat and next candidate and emit a UI event. The UI changes active-provider labeling before rendering its output; global preferences remain unchanged. Store requested and actual family/model/effort, reason and attempts. Every fallback that is still ChatGPT must retain the selected ChatGPT model/Ultra policy, not silently use a weaker ChatGPT model. Never fabricate a served model: model_attested:false is allowed when family is proven, consistent with the canonical verification law.

Verification seats retain the skill's existing fail-closed policy. No exhausted Grok review is presented as Grok if another provider serves it; a skill that explicitly permits same-family degradation records cross_model:false. The current review request specifically asks for Grok, so only actual Grok satisfies it. Exhausting capable authorized candidates yields a journaled HALT, not a guessed wait-until-reset message.

## A5. Gates, delivery and scope

Implementation order: contract and inventory; Doctor/terminal/job wiring; cockpit transport proof and integration; formal Trio/Foundry changes; combined packaging. Notebook auth/setup proof can run independently and need not wait for an unrelated cockpit redesign, but neither capability is declared complete until its required integrated surfaces pass.

Focused tests cover settings/mirror corruption/races, stale adapter/manifest/env/custom-agent pins, session rollover and queued messages, provider cancellation versus replayable failure, quota with Claude exhausted/Grok available, fail-closed review, and honest model attestation. Use fake transports first; then minimal authorized live turns and real Doctor/cockpit/terminal pixels on family toggles. Test actual service-account config visibility as well as interactive login. Rollback preserves histories, model settings and existing work; coordinate restarts.

Ship the resolver contract, migrations, caller integrations and compatible skill versions using installation-relative imports. Require a fresh-profile install of the actual release archives without John's home or workspace, synthetic fixtures and the collaborator's own login (or explicit no-account capability result). Archive allowlists must exclude private projects, notebooks, settings, journals, transcripts, logs, screenshots and credentials. Check archive contents for private paths/content and secrets; a secret scan alone does not establish privacy. No claim of portable success until the clean-install gate passes.

Needed because saved model choices currently do not bind all launch paths; dropping the shared contract leaves the original bypasses. Cut: other-provider model migrations, a full settings redesign, raw API transports, permission expansion, historical fixture rewrites and live-session interruption.
