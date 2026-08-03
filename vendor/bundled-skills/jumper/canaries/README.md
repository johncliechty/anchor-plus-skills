# canaries/ — the skill's frozen, versioned canary SET (append-only)

> Wave 6 (P0.E / FIX-6). This directory holds the skill's canary SET as **data**, one
> file per version (`canary-set.v<N>.json`). The Foundry stays stateless prose — the
> canary set is recorded here as data/refs and registered in `map.json`; nothing
> executes from inside the Foundry.

## The append-only rule (FIX-6)

A canary set is **versioned alongside the skill** and is **append-only**:

- A sleep cycle (P0.D) may **PROPOSE a new version** (`canary-set.v<N+1>.json`) that
  **APPENDS** new canaries — strengthening coverage as the skill learns.
- A sleep cycle may **NEVER edit or delete** an existing canary. Every canary id present
  in version `N` must survive byte-identical into version `N+1`.
- A **deletion is a human call** — it is BLOCKED by governance, never automated, so the
  set neither ossifies (NS1) nor is silently weakened (NS2).

This rule is enforced deterministically by `src/governance.mjs`
(`validateCanarySetChange(prev, next)`) and gated by `test/governance.test.mjs`. The
canary/template `map.json` entries are validated by the Foundry invariant suite
(`tests/test_foundry_invariants.py`, Wave 6 section).

## File shape (`canary-set/v1`)

```json
{
  "schema": "canary-set/v1",
  "skill": "<skill-name>",
  "version": 1,
  "append_only": true,
  "canaries": [
    { "id": "c1", "kind": "capability", "name": "...", "input": { ... }, "expected": { ... } }
  ]
}
```

Each canary is **deterministic** and runnable by the wave-2 `canaryEvalValidator`
(`input` → `expected`). `kind` is `capability` (a core behavior that must PASS) or
`non-goal` (a negative canary mirroring a `NORTH-STAR.md` non-goal).
