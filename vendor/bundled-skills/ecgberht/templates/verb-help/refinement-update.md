# Verb: refinement-update

**Closed list:** yes · **Primary:** refinement-update

Maintain a managed slice's cumulative feedback, immutable product revisions,
presentations, explicit acceptance and foundation dependencies through the existing
roadmap event ledger. Read one JSON request from stdin.

Usage: `node bin/ecgberht.mjs refinement-update --project <path>`

Read actions: `capabilities`, `read`, `operation_status`.
Repair: `'{"action":"repair"}' | node bin/ecgberht.mjs refinement-update --project <path>`
(PowerShell). No operation ID or sequence is needed. Under the existing writer
lock, repair reloads unchanged events and rebuilds only the roadmap/refinement
projections and authenticated lagging document/approved-folder projections.
Current documents and immutable revisions stay untouched. Invalid event folds
and edited managed regions are refused; approved-folder conflicts remain visible.
Adoption preserves inherited event warnings. Later warnings are tolerated only
when the normal writer admits the event and reproduces the same warning against
its preceding history. `roadmap_projection_status.clean` stays `false` with the
original `issues`; `invalid_issues` identifies warnings that still require refusal.
Stable historical warnings do not make an otherwise matching projection drift.
The result includes `repair.repaired_fields`, `repair.persisted`,
`repair.updated_documents`, `repair.finished`, and `events_rewritten: false`
inside `repair`. `consistent` includes roadmap drift; incomplete repair returns
`ok: false` with its actual error and any completed projection writes.

Mutations require a stable `operation_id` and the read result's `expected_seq`.
Actions: `adopt`, `open_slice`, `begin`, `feedback`, `resolve_feedback`, `publish`,
`present`, `accept`, `close`, `view`, `reconcile`, `producer_handoff`, `resolve_handoff`.

`producer_handoff` records `handoff_id`, `producer_kind` (job, conversation or
terminal), `source_ref`, nullable `step_id`, explicit `outputs` source references,
Boolean `inventory_complete`, `terminal`, and nullable `dispatch_context`.
Dispatch context is the captured `{step_id, round, requirements, candidate,
depends_on}` from the read state. Unknown mapping/context remains visible for
Steward review. Never infer output inventory from arbitrary edited files.
`resolve_handoff` requires `handoff_id`, `disposition`, and a sourced `source`;
`published` binds `step_id` and `presentation_id`, while `no_deliverable` or
`superseded` requires a reason. Resolution never accepts or closes a presentation.

Published resolution requires a current handoff context and a complete output inventory, or explicit `reconciliation` evidence. The evidence must contain nonempty `source` and `reason`, plus `changed_context_fields` and `review_reasons` arrays covering every recorded context change and review reason. Explain how those issues were resolved and identify the supporting review. An incomplete inventory additionally requires `inventory_verified: true` inside the reconciliation object. This evidence is preserved in the resolution record.

The selected presentation must have been created after the handoff. If new work arrives while an older presentation is awaiting review, use a sourced no-deliverable/superseded resolution or incorporate it in the next feedback round; never attach it to the earlier presentation.

Every declared output must match a selected presentation member's immutable `path`, or have a sourced `reconciliation.output_mappings` entry naming its `source_ref`, `product_id`, `revision_id`, `source`, and `reason`. Map inspected source bytes to the revision that contains them. Empty incomplete inventories require at least one such inspected mapping; a complete empty inventory cannot be published. A current presentation alone does not establish that it includes the new work. Inspect pending work before publishing, presenting, and resolving it.

For example, a handoff with an unknown dispatch context, no initial slice mapping, and an incomplete inventory needs evidence shaped like:

```json
{
  "reconciliation": {
    "source": "Recorded Steward review of the completed output inventory and current slice",
    "reason": "Verified the product mapping, complete inventory, and current cumulative feedback before presentation",
    "changed_context_fields": [],
    "review_reasons": ["slice_unmapped", "dispatch_context_unknown", "output_inventory_incomplete"],
    "inventory_verified": true,
    "output_mappings": [{
      "source_ref": "draft.md",
      "product_id": "diagram",
      "revision_id": "diagram-r1",
      "source": "Recorded comparison of draft.md with the immutable revision",
      "reason": "The selected member includes the inspected output"
    }]
  }
}
```

Include any additional recorded changes or reasons in the evidence. Naming a slice during resolution does not remove the need to reconcile an unknown dispatch context. Dependency freshness compares only the stable `slice_id`, `presentation_id`, and `accepted_revision_hashes` pins; mutable dependency status and invalidation metadata do not create false changes. Existing checks still require the latest presentation in the current round, unchanged candidate and requirements, and applicable foundations.

Retry an interrupted mutation with the identical operation and ID; never invent a
replacement ID before checking its receipt. Explicit adoption preserves existing
document text and introduces bounded generated regions. Repair a lagging projection
with `action: repair` or by replaying the committed operation; an edited managed
region is a conflict.

Only John's explicit close of the current presentation marks a slice done.
Accepting an older presentation does not close a newer refinement. Reading a file
does not record a human view or acceptance.

Modules: `engine/refinement.mjs`, `engine/refinement-state.mjs`.
