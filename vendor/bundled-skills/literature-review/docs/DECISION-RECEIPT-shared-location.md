# DECISION RECEIPT — trio shared-code location + frozen-gate contract findings (Wave 1)

Date: 2026-07-20 · Wave: 1 — Frozen-gate contract spike + shared-import topology pin
Status: PINNED (all later waves import from this home; changing it requires a plan amendment)

## 1. The pinned shared module home

The shared brownfield-intake front-end lives at:

```
<TRIO_ROOT>/trio-shared/brownfield-intake/index.mjs
```

where `TRIO_ROOT` is researchPrime's single pinned external-dependency root, exported by
`researchPrime/bin/contract.mjs` and overridable via the `RP_TRIO_ROOT` environment variable.
On this host `TRIO_ROOT` resolves to `<path> (the trio checkout containing
`crucible/`, `foreman/`, `researchPrime/`), so the concrete pinned path is:

```
<path>
```

**Why this home (empirical):**
- The trio actually lives at `<path> — the deployed `~/.claude/skills/{crucible,foreman,researchPrime}`
  entries are symlinks into it. `researchPrime/bin/contract.mjs` already pins exactly this root
  (`new URL('../../', import.meta.url)` from `bin/`, i.e. one convention, already committed, already
  `RP_TRIO_ROOT`-overridable for hermetic checkouts). Reusing that pin means literature-review adds
  NO second resolution convention: both skills reach the shared module through the same value.
- Proven by `test/shared-import-parity.test.mjs` (literature-review imports the stub through the pin)
  and `test/rp-shared-import-parity.test.mjs` (a SEPARATE process running from the researchPrime
  checkout imports the same stub through researchPrime's own `contract.TRIO_ROOT`): both consumers
  observe a byte-identical canonical JSON serialization of the same plan-artifact-shaped object,
  with neither side adapting or reshaping it.
- The skill's `src/` was rejected as a home (HARD CONSTRAINT 2: the shared module is consumed by
  BOTH skills, so it must not live inside either skill). `~/.claude/skills/` was rejected because it
  is a symlink farm, not a source-of-truth checkout — resolving through it computes a wrong
  `TRIO_ROOT` unless realpath'd first (see Resolution rules below).

**Resolution rules for consumers (what the tests implement — `test/_wave1-trio-resolve.mjs`):**
1. Locate researchPrime via `RP_ROOT` env override, else the deployed-skill convention
   `~/.claude/skills/researchPrime`.
2. **realpath the result BEFORE importing** — importing `contract.mjs` through the deployed symlink
   would make its `import.meta.url`-relative default resolve `TRIO_ROOT` to `~/.claude/skills/`
   (where `trio-shared/` does not exist) instead of the real trio root.
3. Use `contract.TRIO_ROOT` (which itself honors `RP_TRIO_ROOT`) to resolve
   `trio-shared/brownfield-intake/index.mjs`.

**Repo note:** `<path> is its own git repository, separate from Skill Foundry. The shared
module's commits land in the trio repo; literature-review's tests, receipts, and consumers land in
Skill Foundry. This receipt records the cross-repo dependency explicitly.

## 2. Empirical finding — the frozen gate reads a GENERIC plan body, no RP-specific field

Proven by `test/gate-contract-conformance.test.mjs` against `bin/plan-gate.mjs` +
`bin/two-gate.mjs` at their committed bytes (byte-hashes asserted unchanged before/after the suite):

- `runTwoGateMachine`'s injectable `buildPlan` seam is the gate's generic plan entry — the SAME
  seam `plan-gate.mjs` itself uses to inject the researchPrime Phase-1 plan. The gate serializes
  the returned plan opaquely (`JSON.stringify(plan, null, 2)` → sha256 → persisted artifact) and
  never inspects its fields.
- A hand-authored synthetic NON-researchPrime plan carrying ONLY `{ planVersion, body }` — `body`
  being a human-readable markdown prose plan — round-trips APPROVE / EDIT (re-hash to a NEW
  governance hash) / ABORT, with execution blocked without APPROVE and the headless
  approvalProvider routes (token / policy-grant / replay) resolving without any hard isTTY halt
  (`test/gate-headless-approval.test.mjs`, all runs with `ttyAllowed: false`).
- NO RP-specific field (`objective`, `tier`, `stakes`, `foresight`, `branches`, `baselines`) is
  required on the plan object by the gate itself.
- One caveat for Wave 9 wiring, found empirically: the governance record's `skill` field is
  validated against a registered extension validator. Passing `skill: 'literature-review'` HALTs
  until the caller registers an in-memory extension via the public
  `governance.registerExtension('literature-review', …)` seam — a supported caller-side call,
  ZERO edits to researchPrime files. (Default `skill: 'researchPrime'` passes as-is.)
- Non-Node path: the gate's non-Node contract is the documented prose stamp in researchPrime
  `SKILL.md` — literally `"plan-gate: prose, not hash-bound"` — pinned by a doc-anchored
  assertion (a non-Node host cannot be executed under `node --test`; stamped as such in the test).

## 3. The subtractive decision (recorded verbatim as pinned policy)

- The gate presents **prose only** — the PlanArtifact is rendered into the gate's generic
  markdown plan body as human-readable prose; the artifact itself never becomes the editable
  surface.
- **APPROVE-verbatim executes the derived artifact** — zero LLM parse calls on the unedited path.
- **APPROVE-with-EDITs re-derives via ONE bounded LLM parse** of the edited prose (validated
  exactly once; parse-FAIL → ABORT with a stamped reason; NEVER a re-present).
- **Coverage/provenance is an advisory sidecar** — display-only, derived from anchors; never a
  human-maintained body field, never a schema gate on edits, never a required PlanArtifact field
  (the Wave-1 stub deliberately omits it and the parity test asserts its absence).

## 4. What Wave 1 shipped against this pin

| Artifact | Role |
| --- | --- |
| `<path> | Wave-1 stub establishing the shared home (Wave 8 replaces it with the real ingest → grounded summary → derive entry) |
| `test/_wave1-trio-resolve.mjs` | The single resolution helper implementing the rules above |
| `test/gate-contract-conformance.test.mjs` | Frozen-gate APPROVE/EDIT/ABORT conformance + byte-hash fence |
| `test/gate-headless-approval.test.mjs` | Token / policy-grant / replay headless routes, no isTTY halt; non-Node prose-stamp pin |
| `test/shared-import-parity.test.mjs` | Lit-review-side import: shape + byte-stable canonical serialization |
| `test/rp-shared-import-parity.test.mjs` | researchPrime-side import (separate process, RP's own pin): byte-identical parity |
