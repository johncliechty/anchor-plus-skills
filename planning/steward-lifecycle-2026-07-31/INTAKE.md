# Stage-0 intake — verified fact base (build-vs-wire ledger)

Source: Gandalf-Heavy read (`cross_model:true`, 7 live cross-family refuters, 7
commissions minted) + direct code verification. 5 elevations GROUNDED, 2 REFUTED
(e-1 artifact channel, e-4 bind/derive — both already exist; do NOT resurrect),
1 diagnose finding (d-4 "no proposing half") FALSIFIED by the refuters.

## ALREADY BUILT — wiring only

| Capability | Location |
|---|---|
| Propose a commission FOR a roadmap step (refuses free-floating; validates roadmap health) | `Ecgberht/engine/job-lifecycle.mjs:141` |
| Confirm as a human decision (`who`), mint `job_id` + `commissioned_as`, append `commission_bind` via the SINGLE WRITER | `Ecgberht/engine/job-lifecycle.mjs:250` |
| Render a produced artifact | `Ecgberht/engine/packet-view.mjs` `classifyArtifact` / `buildArtifactCard` |
| Validate a specialist handback (6 campaign-memory fields) | `Ecgberht/engine/receipt-validate.mjs` |
| Roadmap projection + status derived FROM events | `Ecgberht/engine/roadmap.mjs` |
| Face/Strip creation (the path that works today) | `Ecgberht/engine/stand-up.mjs` `confirmStandUp` |
| Face/Strip write authority | `Ecgberht/engine/write-authority.mjs` |

## NOT BUILT — real new code

| Missing | Side | Evidence |
|---|---|---|
| A dialogue → `step_create` path | Ecgberht | `step_create` is minted in exactly ONE place, `pe-gate.mjs:444`, for PARKED future steps; `stand-up.mjs` creates Face+Strip but no steps |
| The commission executor (confirmed commission → real trio run) | Anchor | `grep -rni commission` over every Anchor `.py` returns NOTHING |
| `status_flip` emission as sessions transition | both | rail declares provenance "status: Anchor job receipts"; nothing emits |
| Chamber UI: steps, proposal, confirm, artifact card | Anchor | chamber renders goal bar + rail + convo + saybox only |

## Invariants Stage 1 MUST NOT violate

1. **E5 single ledger** — Strip receipts + roadmap events + Face narrative are the SOLE
   durable ledger; chat turns are NEVER persisted. The scoping dialogue COMPILES into
   the Face (`refine_goal` → `face_rewrite_receipt`). A cross-family refuter attacked
   this and FAILED to land it.
2. **Single writer** — `roadmap_events` is append-only, the projection derives; Anchor
   must not become a second writer.
3. **Commissions are FOR roadmap steps** — no free-floating jobs; confirm carries `who`.
4. **Production seats are subscription CLIs only** — cross family/driver through
   `resolveSeats` (Anchor's `default_cli` is the bare `grok`; a bare `grok` DRIVER is
   refused, family `grok` maps to `grok-cli`).
5. **Auth-ON proof** — this surface shipped broken twice this week because effectively
   the whole Anchor suite runs auth-off.

## Open GAPs for Stage 1 (inferred, not verified)

- What a commissioned Crucible returns as its handback, and where its plan document
  lands relative to `buildArtifactCard`.
- Whether `job_runner` can host a commissioned trio run headlessly under the steward.
- Who emits `status_flip` without becoming a second writer.
