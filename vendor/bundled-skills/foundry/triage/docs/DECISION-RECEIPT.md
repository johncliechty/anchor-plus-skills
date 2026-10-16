# DECISION RECEIPT — shared triage package home (NS-01 · Wave 1)

Date: 2026-07-22 · Wave: 1 — Shared core + vocabulary + project skeleton  
Status: **PINNED** (all later waves import from this home; changing it requires a plan amendment)

## 1. The pinned shared-module home

The shared two-dimension triage core lives at:

```
<path> Foundry\foundry\triage\
```

Entry points:

| Path | Role |
| --- | --- |
| `...\foundry\triage\core.mjs` | Implementation: `recommend(intake) → {tier, depth, rationale, …}` + vocabulary |
| `...\foundry\triage\lock.mjs` | Wave 2: lock schema, `getLockedBand`, interactive + headless lock paths |
| `...\foundry\triage\crucible-wire.mjs` | Wave 3: Stage-0 wire + handoff emit (`assessComplexity`, `resolveStage0TriageLock`, `buildHandoffTriageEmit`) |
| `...\foundry\triage\foreman-wire.mjs` | Wave 4: Foreman inherit-only + reviewer fan-out (`inheritReviewerCount`, never re-triages) |
| `...\foundry\triage\index.mjs` | Public re-export surface (`@foundry/triage`) |
| `...\foundry\triage\skills-manifest.mjs` | Wave 6: all 11 skills · intake class · runtime_enforced |
| `...\foundry\triage\prose-block.mjs` | Wave 6: generated triage block template + regenerate |
| `...\foundry\triage\entry-points.mjs` | Wave 6: uniform skill entry (recommend + lock + knobs) |
| `...\foundry\triage\repairs.mjs` | Wave 6: doc-locator + prompt-size acceptance pins |
| `...\foundry\triage\package.json` | Package manifest; `npm test` → explicit `node --test` file list |

**No dual homes.** Consumers (trio engines + Foundry skills) import this path (or a
future path-alias that resolves to it). A second hand-rolled Heavy/Standard ×
FULL/LITE/SPIKE-FIRST rubric in skill trees is out of contract (NS-01 criterion 1).

## 2. Foundry vs trio — why this pin

| Candidate | Decision | Reason |
| --- | --- | --- |
| **`<path> Foundry\foundry\triage\`** | **PINNED** | Plan's first suggested root; 8 of 11 listed skills already live under Skill Foundry; Foundry is the natural home for portfolio-wide substrate. |
| `<path> | **Rejected** | trio-shared is the right home for *trio-only* shared code (e.g. brownfield-intake). NS-01 spans Foundry skills too; putting triage only under trio would force Foundry→trio reverse imports for the majority of consumers. |
| Dual homes (Foundry copy + trio copy) | **Rejected** | Plan: "pin paths, no dual homes." |

## 3. Vocabulary pin (both axes)

| Axis | Tokens (exact strings) |
| --- | --- |
| Model tier | `Heavy` · `Standard` |
| Process depth | `FULL` · `LITE` · `SPIKE-FIRST` |

Exported constants: `MODEL_TIERS`, `DEPTH_BANDS`, `MODEL_TIER_VALUES`, `DEPTH_BAND_VALUES`
in `core.mjs`. Normalizers accept common aliases (`light`→`LITE`, `spike_first`→`SPIKE-FIRST`,
`frontier`→`Heavy`) but **emit only** the pin tokens above.

## 4. Empty / unknown intake (fail-closed contract)

`recommend()` never returns a silent empty lock:

- Default: returns `{tier, depth, rationale}` with non-empty rationale and
  `defaulted: true` (FULL + Heavy when uncertain — explicit, not silent).
- Opt-in: `recommend(intake, { failClosed: true })` **throws**
  `TriageFailClosedError` (`code: TRIAGE_EMPTY_INTAKE`) on empty/unknown intake.

Locking both dimensions before work proceeds is Wave 2 (`lock.mjs`):

| API | Role |
| --- | --- |
| `createLockRecord` / `isLockRecord` | Validating lock schema (`locked:true` + both pin axes + source + rationale) |
| `getLockedBand(hostOrLock)` | **Sole** reader — throws `TriageUnlockedError` (`TRIAGE_UNLOCKED`) if unlocked |
| `lockFromInteractive` | Engine-host confirm / edit path; forbidden when `headless:true` |
| `lockFromHeadless` | Config-time lock or inherit; missing both → `TriageHeadlessHaltError` (`TRIAGE_HEADLESS_UNLOCKED`) |
| `applyLock(host, lock)` | Stores validated record on `host.lock` |

`recommend()` only **recommends** — it never produces a lock record.

## 5. Foreman control plane vs package home

| Location | Role |
| --- | --- |
| `<path> | Foreman control plane (DESCRIPTION, IMPLEMENTATION-PLAN, EXECUTION-LOG, gate tests that import the pin) |
| `<path> Foundry\foundry\triage\` | **Sole** implementation home for the shared core |

## 6. What Wave 1 shipped against this pin

| Artifact | Role |
| --- | --- |
| `core.mjs` | `recommend` + vocabulary + normalizers |
| `index.mjs` | Package entry |
| `package.json` | `@foundry/triage`, `node --test test/` |
| `test/vocabulary.test.mjs` | Both axes exhaustiveness |
| `test/recommend.test.mjs` | Recommend paths + empty-intake contract |
| This receipt | Path + vocabulary pin |

## 7. Wave 3 — Crucible Stage-0 wire + handoff emit (2026-07-22)

**Closes NS criterion 3:** `runStage0` never called triage; now it does.

| Artifact | Role |
| --- | --- |
| `crucible-wire.mjs` | Stage-0 adapter: `assessComplexity` → `recommend`; `resolveStage0TriageLock`; `buildHandoffTriageEmit` |
| `test/stage0-wire.test.mjs` | Unlocked Stage-0 fails; emit shape matches Foreman consumer |
| Crucible `bin/stage0.mjs` | Live path: `runStage0` calls shared triage **before** framing; unlocked → HALT `confirm-complexity-band` |
| Crucible `bin/stage2.mjs` `writeDocTrio` | Emits `triage_track` + `triage` into `foreman.config.json` |

### Handoff schema (recon → extend)

**Foreman consumer today** (`trio/foreman/bin/run-live.mjs`): reads
`foreman.config.json.triage_track` as a **string** to size reviewer fan-out
(`LITE`/`LIGHT` → 1; `FULL`/`HEAVY` → 2; floor ≥ 1).

**Wave 3 emit (compatible + both axes):**

```json
{
  "triage_track": "FULL",
  "triage": {
    "locked": true,
    "tier": "Heavy",
    "depth": "FULL",
    "rationale": "…",
    "source": "interactive",
    "lockedAt": "…"
  },
  "docs": { "description": "…", "plan": "…", "execution_log": "…" }
}
```

| Field | Contract |
| --- | --- |
| `triage_track` | Process-depth **pin token** string: `FULL` \| `LITE` \| `SPIKE-FIRST`. **Not** model tier. Historical mis-emit used `HEAVY` here; new emits never do (Wave 4 inherit still accepts the alias on input). |
| `triage` | Schema extension (additive): both axes + lock provenance. Foreman Wave 4 inherits depth from this / track; does not re-triage. |

### Stage-0 lock rules

- `runStage0` **always** calls `assessComplexity` (shared `recommend`).
- Without `depth`/`tier` confirm, `triageLock`, or headless config/inherit → **HALT** (`confirm-complexity-band` / `TRIAGE_UNLOCKED`). No silent default band on the live path.
- Return includes `complexity`, `triageLock`, `triage`, `handoffTriage` for Stage-1/2 to thread through.

## 8. Wave 4 — Foreman inherit only + band alignment (2026-07-22)

**Closes NS criterion 4:** Foreman inherits depth; does not re-assess; bands aligned; LITE never zeros reviewers.

| Artifact | Role |
| --- | --- |
| `foreman-wire.mjs` | Inherit-only API: `inheritDepthFromHandoff`, `reviewersForDepth`, `inheritReviewerCount` |
| `test/foreman-inherit.test.mjs` | Spy call-count 0 on assess; LITE ≥ 1; FULL recognized; FULL/LITE/SPIKE-FIRST map |
| Foreman `bin/run-live.mjs` (trio + skill copy) | Live path: reads handoff via `inheritReviewerCount`; no inline LIGHT→0 path |

### Reviewer fan-out (pin depths)

| Depth pin | Reviewers | Notes |
| --- | ---: | --- |
| `LITE` | 1 | floor ≥ 1 — never 0 (closes dark LIGHT→0 path) |
| `FULL` | 2 | recognized (was silently missed when only HEAVY matched) |
| `SPIKE-FIRST` | 2 | uncertain work keeps full panel |

Legacy **input** aliases still normalize on inherit: `LIGHT`→LITE, `HEAVY`→FULL (historical tier-in-track mis-emit), `MID`/`STANDARD`→LITE fan-out. New Stage-0 emits use pin tokens only.

### Inherit rules

- Precedence: `triage.depth` (structured) then `triage_track` string.
- **Never** calls `recommend` / `assessComplexity` (inherit spy call-count stays 0).
- Missing / unknown track → leave CLI `--reviewers` default (still floored at 1 when a band applies).

## 9. Wave 5 — researchPrime intake-only + mapping tables (2026-07-22)

**Closes NS criteria 5–6:** RP triage only via intake extension; `governance.mjs` byte-unchanged; per-skill mapping tables change real knobs (tested inequality).

| Artifact | Role |
| --- | --- |
| `mapping.mjs` | Band → knobs for crucible / foreman / researchPrime / gandalf (sample) |
| `researchprime-wire.mjs` | Intake extension builder + lock resolve; never imports governance |
| `fixtures/researchprime-governance.baseline.mjs` | Wave-5 byte-identity pin for RP `bin/governance.mjs` |
| `test/rp-intake-mapping.test.mjs` | Inequality + named sites + governance diff assert + live intake wire |
| RP `bin/intake.mjs` (trio + skill copy) | Writes `extension` payload; does not import governance |

### Named consumption sites

| Site | How mapping is consumed |
| --- | --- |
| Crucible | `assessComplexity` attaches `bandKnobs` from `crucibleKnobs` |
| Foreman | `REVIEWERS_BY_DEPTH` sourced from `foremanKnobs` |
| researchPrime | intake `extension.knobs` from `researchPrimeKnobs` |
| gandalf (+ Wave-6 skills) | per-skill knobs + `entry-points.mjs` (Wave 6 completes all 11) |

### researchPrime intake extension shape

```json
{
  "inputs": { "...": "..." },
  "timestamp": "...",
  "extension": {
    "skill": "researchPrime",
    "stamp": "ns01-w5-rp-intake-mapping",
    "recommendation": { "tier": "Heavy", "depth": "FULL", "rationale": "…", "defaulted": false },
    "triage": { "locked": true, "tier": "Heavy", "depth": "FULL", "rationale": "…", "source": "interactive", "lockedAt": "…" },
    "knobs": { "maxRounds": 8, "includeAdjudication": true, "seats": "frontier", "ceremony": "full", "skill": "researchPrime", "depth": "FULL" },
    "locked": true
  },
  "ns01_wave5_stamp": "ns01-w5-rp-intake-mapping"
}
```

Gate-1 `gate1-record.json` stays core-only (`triageHash`, `gate1Decision`) — triage never enters `governance.mjs`.

## 10. Wave 6 — Remaining 11 skills + prose blocks + small repairs (2026-07-22)

**Closes NS criteria 1–2, 6 (full), 8–9:** full 11-skill manifest; generated prose blocks + regenerate-and-diff; entry points; single-source grep; repairs status.

| Artifact | Role |
| --- | --- |
| `skills-manifest.mjs` | All 11 skills · intakeClass engine\|prose · `runtime_enforced` honesty |
| `mapping.mjs` | Band → knobs for **all 11** (Wave 5 trio+gandalf + remaining 8) |
| `prose-block.mjs` | ONE template → generated triage blocks + markers |
| `entry-points.mjs` | `entryPointContract` / `resolveSkillLock` / `openSkillEntry` for every skill |
| `repairs.mjs` | Doc-locator + prompt-size acceptance matrix (already-ok pins) |
| `scripts/regenerate-prose-blocks.mjs` | Write + `--check` regenerate-and-diff CI |
| `generated/*.triage-block.md` | Committed blocks for the Wave-6 remaining 8 |
| `test/wave6-prose-manifest.test.mjs` | Manifest · entry · prose honesty · regenerate-and-diff · single-source · repairs |

### Intake class (honest)

| Class | Skills | `runtime_enforced` |
| --- | --- | --- |
| engine | crucible, foreman, researchPrime, gandalf, jumper, ramanujan, tidy-idy, zombie-hunter, literature-review | `true` (lock path) |
| prose | financial-analyst, legal-beagle | `false` (honest — NS-02/03 engines out of scope) |

### regenerate-and-diff

```
node scripts/regenerate-prose-blocks.mjs          # write generated/
node scripts/regenerate-prose-blocks.mjs --check  # CI: exit 1 on drift
```

Also gated by `test/wave6-prose-manifest.test.mjs` (renderer vs committed files).

### Single-source

`recommend()` remains only in `core.mjs`. Mapping/entry/prose import core; suite greps package `*.mjs` for a second `export function recommend`.

### Small repairs (criterion 8)

Doc-locator already accepts `DESCRIPTION.md` + `*design*` (incl. `*-engine-design.md`); prompt-size markdown-first threshold pinned at 20_000 bytes. Status exported via `repairsStatus()`.
