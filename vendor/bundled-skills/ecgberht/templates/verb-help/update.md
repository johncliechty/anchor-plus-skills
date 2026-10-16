# Verb: update

**Closed list:** yes · **Primary:** update · **Alias:** heartbeat

Patch Face narrative fields where human-authoritative; append Strip instrument/receipt entries. Never rewrite Strip
history in place. The one door for the strip and the after rule (the steward revision, 2026-09-28):

| Flag | What it does |
|------|--------------|
| `--next-recommended <text>` · `--strip-why-next <text>` · `--human-wait <text>` | the strip's lead fields, word-capped (15 · 20 · 15); a hand-written line clears the horizon stamp |
| `--current-step <id>` | pins the step that follows (`navigation.current` through the spine); a pin needs a next and a why |
| `--wait-ref step:<id> · deliverable:<row>@<version> · decision:<id> · none` | what the wait names — typed, never prose; a managed campaign's is projected, not set here |
| `--leave [--leave-at <iso>]` | appends a `leave` receipt (the step in hand, the last event and its time, the effort, the presentation he was on); a bare leave appends no instrument |
| `--horizon [--horizon-reason <word>]` | derives the line from the plan (the focus, then the open steps that follow it; done/parked/cancelled/dropped skipped) and writes it as ONE `horizon` instrument stamped with the roadmap's last seq and the focus; `unchanged` when the strip already equals the derivation; `no_horizon` when no focus can be read |
| `--repair-propose --after-step <id> [--after-presentation <id>]` | composes the correction set after an acceptance and appends ONE `repair_proposal` (one open set per step; an empty set appends nothing; no step changes) |
| `--repair-resolve <id> --disposition accepted\|dismissed --who <name> [--why <text>]` | his word: on accepted each correction still true lands as a receipted `step_set` naming the proposal, THEN `repair_resolve` is appended over what landed; what moved since (or was never composed) is skipped by name; a dismiss is refused once any correction landed |

A repair act travels alone (`repair_exclusive`). Refusals: `bad_wait_ref`, `managed-wait-event-owned`, `over_cap`,
`spine_required`, `unknown_step`, `no_horizon`, `repair_needs_step`, `refinement_fold_failed`, `unknown_proposal`,
`proposal_resolved`, `repair_partly_applied`, `bad_disposition`, `repair_needs_who`.
