# Frozen Contract Surface — the trio symbols researchPrime crosses (Wave 1)

> **Import GO/NO-GO verdict (2026-06-06): GO.** All five trio modules smoke-import cleanly from
> `researchPrime-upgrade/` with no side effects, and every crossed symbol below resolves with the
> expected kind. researchPrime builds on the trio directly (imports, never forks). The NO-GO branch
> (Phase 0.5 owned trio-core extraction) is **not** taken.

The machine source of truth for this list is `bin/contract.mjs` (`CROSSED_SYMBOLS`); the contract
test (`test/contract.test.mjs`) asserts each symbol is present in the live trio export and will go
**RED** if any is dropped or renamed upstream — that RED is the NO-GO signal, not a license to fork.

Trio modules imported (relative to the pinned `TRIO_ROOT` in `bin/contract.mjs`):
`crucible/bin/{shark-tank,synthesizer,judge,enhanced}.mjs` and `foreman/bin/foreman-lib.mjs`.
`TRIO_ROOT` defaults to the sibling tree under the shared parent (`C:/dev/{crucible,foreman}`) and
can be overridden via `RP_TRIO_ROOT` to pin a hermetic, version-pinned checkout — so the one
external dependency is declared and pinnable in a single place, not scattered across the map.

## shark-tank.mjs — G3 ≥2-agree heterogeneous reviewers · G5 convergence-until-dry · G6 finding identity
| symbol | kind | serves |
|--------|------|--------|
| `runSharkTank` | function | G3/G5 multi-round ≥2-agree loop |
| `makeSharkDriver` | function | reviewer driver seam |
| `tallyFindings` | function | G3 ≥2-agree quorum tally |
| `normalizeFindingId` | function | G6 stable finding identity |
| `angleForShark` | function | G3 reviewer heterogeneity |
| `SHARK_SCHEMA` | value | reviewer output schema |
| `SHARK_ROLES` | value | heterogeneous reviewer roster |

## synthesizer.mjs — active Deep-Think Synthesizer
| symbol | kind | serves |
|--------|------|--------|
| `makeSynthesizer` | function | active Synthesizer |
| `freshEyesColdPass` | function | isolated cold pass |
| `reconcileFreshEyes` | function | Synthesizer reconciliation |
| `SYNTHESIZER_ROLE` | value | role stamp |
| `DIRECTION_SCHEMA` | value | steering output schema |

## judge.mjs — G4 separate context-free Judge
| symbol | kind | serves |
|--------|------|--------|
| `makeJudge` | function | G4 separate Judge |
| `selectJudgeModel` | function | G4 cross-context selection |
| `stampRole` | function | role/provenance stamp |
| `JUDGE_ROLE` | value | role stamp |
| `JUDGE_SCHEMA` | value | Judge verdict schema |

## enhanced.mjs — G8 cross-lineage origin fusion (Enhanced) · I3 origin integrity
| symbol | kind | serves |
|--------|------|--------|
| `detectAndProvision` | function | Enhanced provisioning |
| `provisionRoles` | function | cross-lineage role provisioning |
| `makeCrossModelProbe` | function | cross-model reachability probe |
| `selectSynthesizerModel` | function | Synthesizer model selection |
| `MODEL_REGISTRY` | value | attested lineage registry seed |

## foreman-lib.mjs — checkpoint/resume · budget pre-flight · HALT signalling
| symbol | kind | serves |
|--------|------|--------|
| `HaltError` | function | HALT-for-human signalling |
| `makeBudget` | function | budget pre-flight |
| `newCheckpoint` | function | checkpoint create |
| `readCheckpoint` | function | resume read |
| `writeCheckpointAtomic` | function | durable checkpoint write |
| `validateCheckpoint` | function | checkpoint integrity |

## Note on the transitive dependency
`crucible/bin/shark-tank.mjs` itself imports `../../foreman/bin/wave-engine.mjs` — i.e. the trio is
proven to load as a unit only when crucible and foreman are **sibling trees** under the same parent.
The smoke import exercises that transitive edge; if the sibling layout breaks, the contract test
goes RED (NO-GO).
