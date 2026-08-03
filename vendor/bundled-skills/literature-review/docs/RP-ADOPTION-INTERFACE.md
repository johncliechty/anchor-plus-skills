# RP-ADOPTION-INTERFACE — the shared brownfield-intake module, for researchPrime

Date: 2026-07-21 · Wave: 11 — Full regression fence, day-one telemetry, and the RP interface-adoption doc
Status: **INTERFACE-ONLY.** This document proves and specifies how researchPrime can consume the
shared brownfield-intake module's PlanArtifact **unmodified**. It wires NOTHING into researchPrime's
runtime — no researchPrime file is modified by this wave (RP runtime adoption is the North Star's
explicit follow-on, out of scope here). The executable proof that an RP-shaped consumer accepts the
artifact as-is already runs in CI: `test/interface-parity-rp-consumer.test.mjs` and
`test/rp-shared-import-parity.test.mjs`.

---

## 1. Where the module lives and how to resolve it

The shared module's pinned home (see `docs/DECISION-RECEIPT-shared-location.md`, which this doc
defers to for the full rationale):

```
<TRIO_ROOT>/trio-shared/brownfield-intake/index.mjs
```

`TRIO_ROOT` is researchPrime's **own** pinned external-dependency root, exported by
`researchPrime/bin/contract.mjs` and overridable via `RP_TRIO_ROOT`. researchPrime therefore
resolves the shared module through a value it already owns — no second convention:

```js
import { TRIO_ROOT } from './contract.mjs'; // researchPrime/bin/contract.mjs — already committed
const intake = await import(new URL('trio-shared/brownfield-intake/index.mjs', TRIO_ROOT).href);
```

External consumers (like literature-review) locate researchPrime first (`RP_ROOT` env override,
else `~/.claude/skills/researchPrime`), **realpath it before importing** (the deployed entry is a
symlink; resolving through it computes a wrong `TRIO_ROOT`), then use `contract.TRIO_ROOT`.

## 2. The entry contract: `brownfieldIntake(options)`

One async entry, end to end: ingest → grounded Gandalf summary → ONE bounded derive → PlanArtifact.
Both skills call this and consume the returned artifact **unmodified** — no adapter, no reshaping.

```js
const result = await intake.brownfieldIntake({
  roots,            // string[]  declared brownfield content roots (opt-in ingest trigger)
  requests,         // string[]  explicit root-relative path requests (optional)
  intent,           // string|null  the user's research intent
  seeds,            // Array<{ idType, id, title, abstract? }> — strictly validated inside
  budgetTokens,     // number   intake token budget override (optional)
  autoTruncate,     // boolean  EXPLICIT opt-in to deterministic truncation (default false)
  summarize,        // async fn the host's Gandalf summarize adapter (content routes only)
  grounding,        // { buildNormalizedView, groundQuote }  the host's quote-grounding fns
  derive,           // async fn the host's ONE bounded derive adapter (content/intent routes)
  summaryMaxTokens, // number   retained-summary cap override (optional)
  maxOutputChars,   // number   derive output cap override (optional)
});
```

The LLM seats (`summarize`, `derive`) are **injected by the host skill**; the module guarantees at
most ONE Gandalf summarize call and at most ONE derive call per run, both bounded and budget-capped,
never retried. Deterministic code does only schema validation, canonical ordering, the verbatim-
anchor check, and seed-identity reconciliation — never semantic span→slot matching.

### The result (`BrownfieldIntakeResult`, frozen)

| Field | Meaning |
| --- | --- |
| `ok` | `true` iff a finished PlanArtifact was produced (a failed derivation yields **no** artifact — never a partial one) |
| `route` | `'content'` \| `'intent-only'` \| `'seeds-only-bootstrap'` \| `'zero-input-fail-fast'` |
| `gandalfCalls` / `deriveCalls` | each `0` or `1` — the hard LLM boundaries, observable |
| `artifact` | the PlanArtifact (schema-valid, verbatim-anchored, canonically ordered) or `null` |
| `groundedSources` | `sourceId -> grounded text` map the artifact's anchors quote from (the gate round-trip consumes this) |
| `summary` / `ingest` | the grounded-summary and ingest stage results (content routes) |
| `manifest` | the pre-Gandalf intake manifest — display + fail-fast, explicitly NOT a second approval gate |
| `seeds` | `{ accepted, rejected }` after strict Wave-6 validation (precedence doi → pmid → arxiv → title-hash) |
| `failure` | `{ stamp, reason, failures[] }` stamped derive/summary failure when `ok` is false |
| `readinessPreview` | the advisory plan-readiness preview (display only — never a schema gate) |
| `truncated` / `truncationStamp` | intake auto-truncation posture (thread into your run stamp) |
| `reason` | why the run stopped, when `ok` is false |

### The four input routes (decided inside the module — content wins, then intent, then seeds)

1. **content** — brownfield roots present: trust-boundary ingest → ONE quote-grounded Gandalf
   summary → ONE bounded derive. Content is the SOLE Gandalf trigger.
2. **intent-only** — no content, intent present: ONE derive over the fenced intent + seed context;
   Gandalf is invoked ZERO times.
3. **seeds-only-bootstrap** — seeds only: a trivial default plan bootstrapped deterministically
   from seed metadata; ZERO Gandalf calls and ZERO derive calls.
4. **zero-input-fail-fast** — nothing supplied: fails fast at the door asking for content, intent,
   or seeds. Nothing is called; nothing is derived.

## 3. The PlanArtifact (module-owned schema — the gate never reads it)

Owned by `trio-shared/brownfield-intake/planArtifact.schema.mjs` (`artifactVersion` stamp
`plan-artifact/1`). Strict surface — exactly these six fields, no extras:

```js
{
  artifactVersion: 'plan-artifact/1',
  scope:         { statement, axis, anchors },          // what the research is FOR + the win condition
  branches:      [{ question, rationale, anchors }],    // candidate research branches (may be empty)
  sourcesToBeat: [{ title, why, anchors }],             // best-in-class baselines (may be empty)
  foresight:     { dropped, counterfactualCost, stamp, anchors },  // honesty-stamped receipt
  seeds:         [{ idType, id, title }],               // user-supplied identity — NO anchors (may be empty)
}
```

- Every **anchor** is `{ sourceId, quote }`: the model quotes the grounded summary / seed text
  **word-for-word**; the deterministic check (`verbatimAnchorCheck.mjs`) enforces verbatim-ness,
  minimum length, and token-boundary alignment. Seeds carry no anchors by design — they are
  covered instead by exact `(idType, id)` **multiset reconciliation** against the validated
  upstream seed set (an invented, dropped, or altered seed identity fails derivation).
- `coverage` / `provenance` are **forbidden keys at every level**: coverage is an advisory
  display-only sidecar derived from anchors at render time, never an artifact field and never a
  schema gate on edits.
- Canonical key order for byte-stable serialization is exported as `CANONICAL_KEY_ORDER`; use
  `canonicalizePlanArtifact` / `canonicalStringifyPlanArtifact` — never your own ordering.

## 4. Companion functions an adopting consumer will want (same directory)

| Module | Consumer-relevant exports |
| --- | --- |
| `validatePlanArtifact.mjs` | `validatePlanArtifact(a)` → `{ ok, reasons }`; `canonicalizePlanArtifact`; `canonicalStringifyPlanArtifact` |
| `renderPlanProse.mjs` | `renderPlanProse(a)` → the gate's markdown prose plan body; `renderPlanPresentation(a)` → `{ planBody, coverageSidecar }` |
| `rederiveFromProse.mjs` | `resolveApprovedPlan({ derivedArtifact, approvedProse, groundedSources, parse })` — APPROVE-verbatim executes the derived artifact with ZERO parse calls; any edit takes ONE bounded parse that RUNs or fail-to-ABORTs (stamp `brownfield-intake/rederive-abort/1`) and NEVER re-presents |
| `planReadinessPreview.mjs` | `planReadinessPreview(...)` — the advisory sidecar text (display only) |
| `seedIdentity.mjs` | `validateSeed`, `deriveSeedIdentity`, `seedIdentityKey`, precedence `SEED_ID_PRECEDENCE` |

The one-shot plan-review gate itself is researchPrime's own frozen `bin/plan-gate.mjs` +
`bin/two-gate.mjs` — the artifact is rendered to prose INTO the gate's generic plan body; the gate
serializes the plan opaquely and reads no artifact field (Wave-1 empirical finding).

## 5. Worked example — an RP-shaped consumer, end to end

This is the exact shape `test/interface-parity-rp-consumer.test.mjs` executes in CI (there against
a real derive; here shown on the deterministic seeds-only route, which needs no LLM seat at all):

```js
// Inside researchPrime (bin/), TRIO_ROOT is already yours:
import { TRIO_ROOT } from './contract.mjs';

const base = new URL('trio-shared/brownfield-intake/', TRIO_ROOT);
const { brownfieldIntake } = await import(new URL('index.mjs', base).href);
const { validatePlanArtifact, canonicalStringifyPlanArtifact } =
  await import(new URL('validatePlanArtifact.mjs', base).href);

// 1. One call, unmodified consumption. (Content/intent routes additionally take the
//    host's injected summarize/derive/grounding seats — same call, more options.)
const result = await brownfieldIntake({
  seeds: [
    { idType: 'doi', id: '10.5555/rp.adoption', title: 'RP Adoption Example Seed' },
    { idType: 'arxiv', id: '2203.15556', title: 'A Second Seed' },
  ],
});

if (!result.ok) throw new Error(`no plan derived: ${result.reason}`); // no partial artifact exists

// 2. The artifact validates against the module-owned schema AS RETURNED — if a consumer
//    feels the need to reshape it, that is an interface bug, not an adapter requirement.
const check = validatePlanArtifact(result.artifact);
if (!check.ok) throw new Error('module contract violation'); // CI-pinned to never happen

// 3. Feed YOUR planning surface directly from the artifact's fields:
const plan = {
  objective: result.artifact.scope.statement,     // scope → RP objective
  axis: result.artifact.scope.axis,               // AXIS → RP win condition
  branches: result.artifact.branches,             // candidate branches/questions
  baselines: result.artifact.sourcesToBeat,       // sources-to-beat
  foresight: result.artifact.foresight,           // honesty-stamped receipt
  seeds: result.artifact.seeds,                   // identity-validated seed set
};

// 4. Byte-stable persistence uses the module's canonical serialization, nothing else:
const bytes = canonicalStringifyPlanArtifact(result.artifact);
```

Gate round-trip (when RP routes this plan through its own frozen gate): render with
`renderPlanProse(result.artifact)` into the gate's plan body, show `coverageSidecar` alongside
(never inside) it, and on APPROVE call `resolveApprovedPlan` with `result.groundedSources` and
your bounded `parse` seat.

## 6. Honesty posture the consumer must preserve

- `truncated === true` means intake auto-truncated under budget: propagate the stamp — a run built
  on a truncated summary must not present itself as full-coverage.
- The gate's `governed` claim is scoped to plan-review governance ONLY; it never upgrades a run's
  own stamp (literature-review enforces this with `src/posture-resolver.mjs` +
  `test/posture-end-to-end.test.mjs` — adopt the same rule or import the same discipline).
- `readinessPreview` and the coverage sidecar are DISPLAY ONLY. Never persist them into the
  artifact, never ask a human to hand-edit them, never gate an edit on them.

## 7. What is explicitly NOT here

- No researchPrime runtime file is changed, imported into, or wired by this wave.
- No second derivation path: derivation logic lives in the shared module only; both skills are
  thin consumers.
- No new resolution convention: the module home is reached exclusively through
  `contract.TRIO_ROOT` (Wave-1 pin).
