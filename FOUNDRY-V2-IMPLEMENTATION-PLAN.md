# Skill Foundry v2 — Implementation Plan (Foreman-ready) — ANCHOR-SIDE BUILD (split)

test-command: python -m pytest tests/ -v -k "foundry or gandalf or reaper or manifest or skill_runner or journal or sleep or telemetry or map_json or library or isolation or scaffold or north_star"

> **SPLIT (John's decision 2026-07-07):** the two FOUNDRY-RESIDENT waves — the sleep-kernel fix and the gated
> sleep session — are DEFERRED to a separate Foreman build rooted in the foundry repo (`C:/dev/Skill Foundry`),
> because the sleep kernel lives there (a different repo from this Anchor build root) and Foreman can only
> isolate/commit changes inside its own project dir. Their plan is `../plans/2026-07-foundry-v2/FOUNDRY-KERNEL-PLAN.md`.
> THIS build delivers the ANCHOR-SIDE platform; the sleep-loop closure + GUI sleep-review wiring is completed by
> the foundry build + a final integration pass (see W10/W12 notes).
>
> **Build root:** `C:/dev/Anchor` · **Gate:** the scoped, VERBOSE pytest above (fast: ~75s / ~300 tests, and
> `-v` emits the per-test `PASSED` events Foreman's vacuous-GREEN guard requires; the full 2261-test suite
> takes >13min and blows the gate timeout — do NOT use bare `pytest -q`).
> **TEST-NAMING CONVENTION (mandatory):** every wave's NEW test file MUST be named `test_foundry_<area>_w<N>.py`
> so the `-k "foundry …"` gate always collects the wave's own tests (keeps the gate non-vacuous). Each wave must
> change real WORKTREE code (in `C:/dev/Anchor`) exercised by its test — NEVER edit files outside the worktree
> (e.g. the foundry) in this build. A full `python -m pytest tests/` regression run is the human MERGE gate.
> **EXECUTE SELF-VERIFY (mandatory — avoids the §5 test-immutability halt):** before finishing, EXECUTE MUST run
> its own new test (`python -m pytest tests/test_foundry_<area>_w<N>.py -q`) and ensure it PASSES against the code
> it just wrote. The FIX loop may NOT edit test files (Foreman §5), so any wrong assertion you leave for "fix"
> will HALT the wave — correct a wrong assertion in EXECUTE now, not later. Keep tests deterministic (no
> time/id-dependent assertions).
> **Design:** `DESCRIPTION.md`. **North Star:** `../NORTH-STAR.md`. Claude writes code; a 3-Gemini panel reviews
> each wave (5:1). **Single-source:** skills/kernel are CONSUMED from `Skill Foundry`, never forked.

## Wave 1 — Phase 0: de-risking spikes → decisions (as CODE + rationale docs)
**IMPORTANT (Foreman §5): a wave must change real CODE exercised by a test — a docs-only wave HALTs. So the
four Phase-0 decisions are encoded as an IMPORTABLE Python module, not just prose.**
**Deliverables:** (A) a new source module **`foundry_decisions.py`** (in the Anchor build root) that encodes
the four resolved decisions as machine-readable constants/enums that LATER waves import (this puts the
decisions on the consumption path): (1) `ANCHOR_API_CONTRACT` — the native READ/EXECUTE surface vs. the
MUTATIVE verbs the control plane must supply (control-plane wave's op inventory); (2) `ISOLATION_RUNTIME` — the
chosen OS-level primitive (WASM/container/microVM/Deno-perms) + its cost/latency envelope, or an explicit
`PERMISSIONS_ADVISORY_V2` downgrade; (3) `TEST_PROVENANCE_CLASSES` — the taxonomy (human /
agent+cross-model-verified / agent+human-ratified / frozen-benchmark-delta) with per-class trust ceilings;
(4) `PROCESS_TELEMETRY_DEPTH` + the droppable-side-channel design. Each decision also carries a
`traces_to_north_star` tag. (B) the four `DR-0*.md` rationale docs. Keep `foundry_decisions.py` stdlib-only.
**done-when:** the gate passes `tests/test_foundry_decisions_w1.py`, which **imports `foundry_decisions`** and
asserts the isolation runtime + cost, the provenance classes, the mutative-verb inventory, and a
`traces_to_north_star` tag on each decision — a real SOURCE module exercised by the test (§5 satisfied).

## Wave 2 — Phase 1: host-enforced journaling write-back seam
**Deliverables:** the write-back seam in `gandalf.py`'s finalize path (Anchor already holds inputs/verdict/
timing/outcome) that auto-appends a 7-field entry (provenance; operation/kind; model+billed-cost+cache-tokens;
inputs-ref; outputs-ref; verdict+timing; outcome/linkage) to `<skill_dir>/journal/`; heavy I/O to a droppable
side-channel; a grep/drift gate proving no honor-system capture path remains; PLAN.md §7 backfilled.
**done-when:** the gate shows every gandalf run through Anchor auto-journals a schema-valid 7-field entry with
zero author action, the droppable side-channel keeps the skeleton entry small, and the drift gate fails if a
capture path bypasses the seam.

## Wave 3 — Phase 2a: generic manifest-driven skill_runner core
**Deliverables:** generalize Anchor's `gandalf.py` consumer ADAPTER (NOT the skill) into one module
parameterized by a per-skill manifest (`skill_dir`, `host_cmd`, `output_contract`, panel meta, journal spec,
tier, declared capabilities + runtime pre-flight probe, lazy activation trigger, `op_kind` = `run`|`mutate`);
declare-then-resolve dispatch built from manifests WITHOUT executing skill code; the `mutate` kind requires a
confirm token + declared write-scope. The Wave-2 journaling seam moves into this runner.
**done-when:** the gate proves the runner builds its dispatch table from manifests without importing skill code,
lazy activation fires only on the declared trigger, and a `mutate` op without a valid confirm token / outside
its write-scope is refused.

## Wave 4 — Phase 2b: re-express gandalf on the runner + prove on jumper
**Deliverables:** gandalf re-expressed as a manifest on the generic runner with NO behavior change (byte-parity
on the graded output for a fixture project); jumper (composes gandalf) wired via a manifest registry entry; a
3rd skill wired in under a small line budget; all three auto-journal via the runner seam.
**done-when:** the gate shows gandalf-on-runner output parity vs. the legacy adapter, jumper running end-to-end
via its manifest, and the 3rd skill wiring diff under the declared line budget — all three auto-journaling.

## Wave 5 — Phase 5a: map.json v2 schema + resolved-graph lockfile
**Deliverables:** `map.json` v2 with machine-readable typed edges (compose/import/augment) keyed by a stable
ref, closed-enum status (PyPI Development-Status ladder), tier + semver; manifest ranges plus a SEPARATE
resolved-graph lockfile (Cargo.lock analogue); a JSON Schema + validator (all worktree-local Python/JSON).
**done-when:** the gate validates a good map.json v2 against the schema, the resolved-graph lockfile pins the
transitive closure, and an untyped/overloaded edge or an out-of-enum status fails validation.

## Wave 6 — Phase 5b: three drift gates + consumption path + supply-chain signing
**Deliverables:** three automated drift gates — schema-in-CI, regenerate + `git diff --exit-code`,
target-existence at ingest (every declared edge resolves to a real skill); put map.json v2 ON THE CONSUMPTION
PATH (the real consumer reads it so a wrong/empty edge breaks a build); couple signing/checksums to the
lockfile (supply-chain integrity).
**done-when:** the gate shows a wrong/empty edge breaking a build loudly, all three drift gates green on a
consistent graph and red on a stale/forged one, and a tampered lockfile failing the checksum gate.

## Wave 7 — Phase 6a: control-plane ops (scaffold + gen_manifest)
**Deliverables:** `foundry.scaffold_skill` (creates a new skill on disk from a template — SKILL.md, manifest,
journal dir, per-skill North-Star stub — registers it in map.json v2, commits on a branch; idempotent, refuses
to overwrite) and `foundry.gen_manifest` (derives/updates a skill's runner manifest, validated against the
Wave-3 schema), both as manifest-registered `mutate` ops dispatched through job_runner (auto-journaled +
confirm-gated). No new server/DB/store.
**done-when:** the gate shows each op running HEADLESSLY via job_runner (no GUI), scaffolding a demo skill
end-to-end into a runnable + journaled + map-registered skill, and the scaffold op refusing to overwrite.

## Wave 8 — Phase 6b: edit_north_star op + auto-load registration
**Deliverables:** `foundry.edit_north_star` — the ONLY sanctioned per-skill North-Star mutation path
(proposal-diff → explicit human confirm token → apply as a branch commit with the prior version retained); a
grep/drift gate catching any out-of-band North-Star write; the auto-load registration op set that makes every
foundry skill clickable inside Anchor, driven from map.json v2.
**done-when:** the gate shows a North-Star edit round-tripping proposal → confirm → branch commit with history
preserved, the drift gate FAILING on a direct out-of-band North-Star write, and auto-load registration making a
scaffolded skill appear in Anchor's clickable set from map.json alone.

## Wave 9 — Phase 7a: Foundry GUI read surface (stateless client)
**Deliverables:** the Foundry GUI as a stateless client over Anchor's real job_runner/session/artifact (Wave-1
§1 contract): run/monitor skills, see changes, browse the library + knowledge graph. Launched from an Anchor
button. Every displayed value traces to an engine-written artifact; NO parallel run/progress store.
**done-when:** the gate (driving the GUI's data layer) shows every rendered value resolving to a real engine
artifact, an integration test asserting a monitor view reads job_runner state (not a mirror), and the
anti-theater check failing if a parallel store is introduced.

## Wave 10 — Phase 7b: Foundry GUI write surface + Anchor-side user-journey
**Deliverables:** the GUI's mutative actions wired to the control-plane ops — create a skill
(→ `foundry.scaffold_skill`), edit a per-skill North Star (→ `foundry.edit_north_star`); all foundry skills
auto-loaded into Anchor as clickable; every GUI mutation is an op invocation, never a GUI-side file write.
**SPLIT NOTE — sleep-review:** the "Run sleep session → review" button is wired to a declared op INTERFACE
`foundry.sleep_session` that the SEPARATE foundry build implements; until then it resolves to an honest
"sleep session not yet wired (foundry build pending)" status — the GUI seam is present + tested, the op body
is delivered by the foundry build + integration. Do NOT implement the sleep kernel/session in this build.
**done-when:** the gate drives the Anchor-side user-journey (create → run/monitor → edit North Star → browse
library) end-to-end over REAL machinery, asserts each GUI mutation lands as a journaled job_runner op, the
sleep-review button targets the `foundry.sleep_session` interface and shows the honest pending status, and the
2nd-surface honesty test passes (every implemented verb runs headless).

## Wave 11 — Phase 8: safety before scale
**Deliverables:** arm the reaper to ≥FREEZE after re-checking the 2026-07-05 fail-deadly finding; a per-host
concurrent-skill-run budget enforced IN the generic runner before default-on fan-out; zombie-hunter kept a
native built-in (not forced into the skill-action manifest).
**done-when:** the gate shows the reaper armed to FREEZE within its safety envelope (never kill-on-uncertainty),
the concurrency budget refusing an over-budget fan-out, and the fail-deadly path retired or explicitly bounded.

## Wave 12 — Anchor-side North-Star acceptance proof (end-to-end)
**Deliverables:** an end-to-end acceptance test proving the ANCHOR-SIDE North-Star journey from the GUI on
genuine data — create a skill, run/monitor it + see changes, browse library + graph, edit its North Star —
plus every foundry skill auto-available/clickable in Anchor, all mutations journaled, safety envelope armed.
**SPLIT NOTE — deferred to integration:** the North Star's central sleep-loop clause ("run+review a test-gated
sleep improvement that has turned over ≥1× on genuine data") is delivered by the SEPARATE foundry-kernel build
(`FOUNDRY-KERNEL-PLAN.md`) + a FINAL integration pass that wires the `foundry.sleep_session` op body to the GUI
seam from W10 and proves the full journey. This wave proves everything EXCEPT that clause and records it as the
one explicit open item for the integration step — it is NOT silently dropped.
**done-when:** the gate is green including the end-to-end Anchor-side acceptance test over real machinery, the
invariant/drift gates from all prior waves stay green, and the test asserts the sleep-loop clause is the single
declared-pending item (targeting the `foundry.sleep_session` interface) for the integration step.
