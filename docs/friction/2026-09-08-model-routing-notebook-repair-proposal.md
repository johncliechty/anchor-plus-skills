# Anchor / Steward repair proposal - 2026-09-08

Historical first proposal. Superseded for current planning by the two revised plans and Grok review dispositions in [the review packet](../../planning/notebooks-model-routing-2026-09-08/review-disposition.md). The revised scope includes portable, built-in Anchor/skill capabilities for collaborators and Jupyter-only execution on each installation's Anchor host. No implementation has been authorized by this document.

Status: proposed, not implemented. Based on the companion investigation and the existing notebook friction journal. Do not resume or overwrite the older halted run implicitly.

## 1. Consistent provider and model selection

Preserve Anchor settings / ~/.anchor/model_prefs.json as the sole family authority. Current choices are ChatGPT coder and terminal, Grok reviewer. Jarvis is a persona choice, not a provider override.

- Resolve the selected provider when a new Doctor, terminal, or Steward session is started. Existing sessions must identify their actual provider; do not silently resume a Claude session as ChatGPT.
- Doctor: authenticated preference initialization must succeed before enabling provider launch. Remove permissive Claude initialization; backend-omitted requests must resolve durable preferences on the server. Test authentication failure, slow initialization, explicit overrides, and existing-session reuse.
- Steward cockpit: add a real subscription Codex transport and its own session/event handling. The existing Claude stream command is incompatible with Codex; an allowlist edit is insufficient. Keep user conversations and existing changes intact.
- Implement the user's explicit latest/Ultra override for every ChatGPT production seat: currently gpt-6-astra/ultra, including subagents where delegation is supported. Address Anchor's isolated adapter, interactive terminals, Trio Heavy/Standard/untiered defaults, and explicit manifests such as Ramanujan. Historical fixtures and other providers are not blanket replacement targets. Do not broaden tool permissions to accomplish a model change.
- Audit all effective model/effort overrides and record the requested and actual served model. Preserve Grok review and honest cross-family reporting. Rate-limit failover must follow the documented capable-provider ladder, journal substitutions immediately, and honor each verification seat's fail-closed policy.

## 2. Live notebooks hosted by PUTER

Use the earlier notebook North Star as input, resolving its blocked review findings before implementation.

- Route deliverable-register, plan-produced-file, and ordinary file-list notebook actions through one authenticated, project-contained launcher. Never send the browser to its own localhost.
- Open existing .ipynb without overwriting it. For eligible classroom .py/.R snippets, apply the agreed conversion rules and kernel metadata; do not convert general program source indiscriminately.
- Make host Jupyter startup, health, project-root isolation, and lifecycle explicit. Confirm Python and R availability, a remotely reachable URL, recoverable errors, and restart persistence. Keep access tokens out of logs and new public deliverable URLs.
- Preserve the working Week 1/2 launch pages until the integrated path passes its checks. No automatic notebook execution just from opening a link.

## Formal improvement gate and verification

Follow the Foundry improvement cycle: distill the relevant journals into lessons, propose the smallest changes, check the North Star, then apply and evaluate through the formal workflow with human and machine journal records and a changelog. This proposal does not authorize ad-hoc skill patches or claim a completed cycle.

Before deployment, inspect and preserve the dirty worktrees. Use focused regression tests for preference resolution, transport arguments/events, session reuse, contained paths, and all three notebook launch surfaces. Then verify rendered pages and actual served-model receipts with a minimal live turn, and run harmless Python/R kernel probes on PUTER with execution explicitly identified. Finally verify from the user's remote-device path and check startup after an agreed controlled restart. Do not interrupt unrelated sessions or restart the service without coordinating its impact.

Acceptance: dashboard changes reach new sessions across all affected surfaces; every ChatGPT seat uses Astra/Ultra or reports an explicit unsupported/degraded state; review-family integrity is preserved; both languages open and execute on PUTER from register and plan without client-side compute.
