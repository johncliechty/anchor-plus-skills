# tidy-idy — Frozen acceptance handoff bundle (Wave 9)

**Status:** FROZEN. This is the Wave-9 deliverable "Frozen handoff bundle." It is
the single index a downstream integrator (or the Stage-2 planning trio) reads to
find every load-bearing contract this project ships, plus the acceptance spec
that proves the whole thing holds together. It adds no new behaviour; it points
at the authoritative artifacts and states what each one guarantees.

The rule of this bundle: **every entry names the file that IS the contract and
the test(s) that PROVE it.** A contract with no green test behind it is not in
this bundle, by construction.

---

## 1. The acceptance spec (this wave — the definition of done, made executable)

The frozen definition of done is not prose; it is a set of CI cells that fail the
build if any safety invariant regresses. One `node --test` run executes them all,
alongside the full legacy suite and every earlier wave's suite (the criterion-5
"extend-don't-fork + green" proof).

| Acceptance surface | Where it lives | What it asserts |
|---|---|---|
| **E2E matrix** — {Foundry git repo, plain git repo, non-git folder, non-git inside an enclosing repo, dirty tree, nested repo} × {scan, approve subset, Apply, revert/restore} | `test/e2e-matrix.test.mjs` | zero-write scan (metadata tripwire), exactly one commit per Apply + one atomic Trash move-set, mixed-batch failure commits nothing, excluded subtree untouched, git:null semantics (no enclosing-repo mutation), byte-for-byte revert/restore, consent-scope holds, undo-refusal leaves the tree untouched |
| **Adversarial losing-sequence cells** | `test/acceptance-adversarial.test.mjs` | edit-during-Apply and stage-during-Apply drop stale (lose nothing); undo-after-later-commits refuses; Bootstrap-undo-after-new-work refuses; post-Apply-edit-then-undo REFUSES per no-clobber across **every** undo path (git-revert, SAVE compensation, Trash restore, reorg move-back, Bootstrap undo); mixed-reorg-kill-after-commit rolls FORWARD; mixed-reorg-kill-before-commit rolls BACK bit-identical |
| **Reorg crash-at-every-step matrix** | `test/apply-reorg.test.mjs` (one cell per row of `docs/reorg-two-phase-crash-table.md`) | a mixed reorg apply resolves to exactly fully-applied OR bit-identical under a crash at ANY state — never a third state |
| **Trash / Bootstrap kill + reoccupied-path cells** | `test/apply-trash.test.mjs`, `test/apply-bootstrap.test.mjs` | interrupted move-set / restore resume idempotently; restore-onto-reoccupied-path refuses; Bootstrap undo restores the prior `.gitignore` byte-for-byte and refuses once HEAD moved past B |
| **Protection-monotonicity property test** | `test/engine-protection.test.mjs` | `protected(defaults) ⊆ protected(defaults + config)` for every fuzzed `.tidy-idy.toml` — no config can narrow the built-in protected set |
| **SAVE-undo compensation round-trips** | `test/save-undo-compensation.test.mjs` | a SAVE'd untracked file and a SAVE'd dirty-modified file each round-trip Apply→undo bit-identical AND back to their original tracking class (decision #8) |
| **Heuristic precision gate** | `test/corpus.test.mjs` over `test/fixtures/corpus/` | on the hand-labeled corpus, heuristic-mode removal precision = 1.0 (zero keep-labeled file offered for removal); the negative control yields zero verdicts |

### The heuristic-mode shipping gate

The bar is **precision 1.0** on the labeled corpus — v1 gates precision on
removals, where wrong = data-loss risk ("missing some mess is acceptable,
flagging good files is not"). The gate measures the heuristic stage's emitted
removal candidates, post-protection — exactly the set a human would see a remove
control for. Until `test/corpus.test.mjs` is green, the heuristic-mode flag does
not ship enabled; each false positive is filed as an exclusion/tuning task, never
a shipped bad batch. Recall is reported for visibility but is **not** gated.

---

## 2. The frozen contracts, by wave of origin

### W0 — coupling inventory + no-overlay verdict
- **`spike/baseline-record.md`** — the recorded green baseline of the legacy
  suite (the seven `test/*.test.mjs` files every later wave must preserve) and
  the extend-don't-fork decision.
- **`spike/*.test.mjs`** — the Wave-0 VERIFY-OR-KILL spikes, including the
  measured verdict that `git checkout --no-overlay` propagates deletions on the
  supported git range (>= 2.22), which the whole Apply realization depends on.

### W1 / W3 / W6 — envelope, finding-identity, and token control-plane contracts
- **Envelope** — `engine/envelope.mjs`: the uniform per-stage result and the run
  envelope (terminal status = worst stage status; `isClean` is computed, never
  asserted). Proven by `test/engine-envelope.test.mjs`.
- **Finding identity** — `engine/apply/identity.mjs`: `ID = hash(run_id, action,
  path, content_hash)`, stamped at emission and round-tripped in full; Apply
  refuses any ID it cannot match exactly. Proven by `test/apply-identity.test.mjs`.
- **Protection predicate** — `engine/protection.mjs`: deny-by-default, strictly
  additive. Proven by `test/engine-protection.test.mjs` (incl. the monotonicity
  property test above).
- **Apply control plane** — `engine/apply/executor.mjs` (`applyApproved`),
  `engine/apply/lock.mjs` (per-project advisory lock, borrowable by the panel),
  `engine/apply/consent-scope.mjs` (the porcelain-class diff asserted after every
  Apply). Proven by `test/panel-apply-plane.test.mjs`, `test/panel-apply-state.test.mjs`
  and the E2E matrix.

### W5 — job_runner integration contract
- **`docs/anchor-job-runner-integration-contract.md`** — how the standalone tool
  is driven as a background job and how Anchor's Tidy-Idy button is a thin caller.
  The launch surface it describes lives in `engine/launch/` and is proven by the
  `test/launch-*.test.mjs` suites.

### W4 / W8 — Trash and two-phase reorg journal contracts (incl. the crash table)
- **Trash** — `engine/apply/trash.mjs` + `engine/apply/journal.mjs`: the reversible
  journaled move-set (undo = journaled move-back), no-clobber guarded. Proven by
  `test/apply-trash.test.mjs`.
- **Bootstrap** — `engine/apply/bootstrap.mjs`: secret-triage-FIRST `git init` +
  baseline commit B, undoable byte-for-byte while HEAD == B. Proven by
  `test/apply-bootstrap.test.mjs`.
- **Two-phase reorg** — `engine/apply/reorg.mjs` and its normative crash table
  **`docs/reorg-two-phase-crash-table.md`**: the explicit, code-enforced state
  machine (`PLANNED → PREFLIGHTED → FS_MOVING → FS_DONE → COMMITTED → REF_ADVANCED
  → DONE`), the recovery rule ("last durable state + one git fact"), and the
  invariant that a mixed apply resolves to exactly fully-applied OR bit-identical.
  Every crash-table row is instantiated in `test/apply-reorg.test.mjs`.

---

## 3. How to run the acceptance harness

```
node --test        # from the skill root — Node's default discovery runs the
                   # legacy suite AND every wave's suite in one invocation
```

A green run of that single command is the criterion-5 proof: the full legacy
tidy-idy suite plus every new suite pass together, and no adversarial cell has a
surviving losing sequence. Any red cell — a lost byte, an overwritten post-Apply
edit, a heuristic false positive, a reorg apply that landed in a third state — is
a release blocker, not a warning.

---

## 4. Explicitly deferred (recorded so the boundary is honest)

- Precision bars for the SAVE and reorg classes (v1 gates precision on removals
  only; SAVE/reorg precision measurement is a fast-follow once real-run data
  exists).
- Recall targets for heuristic mode (v1 gates on precision only).
- `lock-a-file-mid-sync` is asserted through the working-tree realization's
  journaled `complete: false` retry path (`engine/apply/realize.mjs`), not through
  a platform-specific OS file-lock test — the failure mode is "the sync is
  incomplete, journaled, and retryable; git still holds the content," which the
  realization contract already guarantees and the Apply result reports honestly.
- Performance/scale benchmarks beyond the cost-gate thresholds.
