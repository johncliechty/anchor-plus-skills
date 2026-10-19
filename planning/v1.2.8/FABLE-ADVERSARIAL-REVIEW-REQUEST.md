# Fable adversarial review request — prepared, not invoked

Prepared: 2026-08-31  
Mode: independent read-only review  
Current disposition: **BLOCKED before release**

## Review objective

Adversarially determine whether this bounded Steward/Trio/Anchor slice is truthful,
safe, coherent, and ready for a human acceptance pass. Do not edit files, invoke a
model or provider, regenerate fixtures, change user settings, or perform any git or
release action.

Use these primary artifacts:

- `planning/v1.2.8/WAVE4-EVIDENCE.json`
- `planning/v1.2.8/WAVE4-IMPLEMENTATION-INVENTORY.md`
- `planning/v1.2.8/STEWARD-CONTROLLER-LEDGER.json`
- `planning/v1.2.8/RAMANUJAN-CODEX-BOUNDARY-DECISION.md`
- `planning/v1.2.8/WAVE4-HANDOFF.md`

## Questions Fable must try to falsify

1. **One seating law.** Confirm that Anchor settings and
   `~/.anchor/model_prefs.json` remain the only family-preference source; stale
   family environment values cannot silently select a production seat.
2. **Shared agent seam.** Confirm that Ecgberht and Tidy model roles enter the
   shared Trio `runAgent` substrate, with injected offline tests and receipt
   retention, rather than a second local dispatcher.
3. **ChatGPT Ultra truth.** Confirm that Ecgberht's frontier ChatGPT request asks
   for Ultra reasoning/orchestration and that no product model ID or successful
   live-call claim was invented.
4. **Verification honesty.** Confirm that reviewer/judge and Literature Review
   lineage derive from successful served-model receipts, and that unattested or
   same-family verification cannot be mislabeled cross-model.
5. **Four-role Anchor UX.** Confirm that Terminal, Coder, Reviewer, and Judge use
   one capability matrix; ChatGPT is enabled only where the underlying capability
   is real; Judge follows `review_family` rather than inventing a fourth setting.
6. **Cockpit default and graceful setup.** Confirm that the current AI cockpit is
   the default project surface, `?classic=1` is the explicit escape, Calendar and
   Email are truly empty synthetic states, and the Gmail/Outlook dialog is local
   preview only with no credential, token, fetch, storage, or account-data path.
7. **Distribution/data safety.** Confirm that `_mockups/dashboard-v2` has no
   tracked or selected distribution file and that no personal-looking sample data
   was copied into the production cockpit.
8. **Dirty-worktree provenance.** Compare the implementation inventory to the
   actual diffs. Flag any controller claim that absorbs pre-existing user work or
   omits a changed dependency.
9. **Test adequacy.** Decide whether the reported deterministic gates cover the
   changed seams and whether the two capability skips are acceptable for a local
   acceptance build.
10. **Known blocker.** Verify the five WH4 failures are genuinely caused by a
    stale prompt-bound real-seat replay. Treat any proposal to repin old reply text
    to new hashes as a release-blocking evidence violation.

## Required response shape

Return:

1. `VERDICT: PASS | BLOCK`
2. One row per question above: `PASS | BLOCK | NOT PROVEN`, with concise evidence.
3. Findings ordered P0 through P3, each with exact repository-relative file and
   line evidence, impact, and the smallest safe correction.
4. A separate list of pre-existing overlap that this slice must not claim.
5. A release recommendation that explicitly accounts for the WH4 replay blocker,
   the two Windows capability skips, the absence of live OAuth/provider tests, and
   the fact that no commit/push/merge has occurred.

Do not soften a blocker to preserve momentum. Do not require live calls merely to
review static contracts. Do not modify the repositories.

## Known facts to preserve

- Preference SHA-256 before and after:
  `CDC47E7267BB939F86C559CE705CE96ED210FB6228CF80A022E20DD134707A49`
- No live model, Fable, OAuth, Gmail, Outlook, network-provider, commit, push,
  merge, deploy, or personal-data migration occurred in this controller run.
- The requested Fable review has been prepared only. It has **not** been invoked.
