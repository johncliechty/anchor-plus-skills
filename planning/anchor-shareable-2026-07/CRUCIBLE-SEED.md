# Crucible seed — "Make the integrated Anchor system securely & easily shareable"
_Derived from the Gandalf review 2026-07-17 (Fable-5 deep-think, cross-family refutation attempted) + John's issue-by-issue decisions._

## Scope (LOCKED by John)
The distributable is the **whole integrated package**: Anchor + the trio (researchPrime/Crucible/Foreman) + the foundry skills + the **operating conventions/governance** (10-min status-table format, skill-immutability/foundry-only-edit, driver-init) — packaged so a collaborator's setup behaves **identically** to the author's.

## Candidate North Star (for Crucible Stage 0 to refine)
A collaborator on any major OS can obtain a **scrubbed bundle**, onboard to a **working, secure-by-default** instance with **zero manual token handling**, and get the **same agent behavior + governance** as the author — without leaking the author's data or compromising their own machine, and without regressing the durability the last rebuild established.

## Decided work items (priority-ordered)

### P0 — Share-blockers (must close before any collaborator runs it)
1. **Security baseline (full).** Mandatory token (server refuses to start without one) + enforce auth-mode by default + token-gate/remove `/api/rnd/dir_browse` + validate `Host`/`X-Forwarded-For` (kill the reverse-proxy bypass).
   - **HARD CONSTRAINT (John):** token is **auto-provisioned + persisted locally** (env / `0600` config the service reads at startup) and auto-injected into the local browser session (SameSite=Strict cookie). The author **never** finds/types it. Enforcement blocks only a **remote peer without the token**.
2. **Redact token in logs** — strip/mask `?token=` in the access logger + both exception loggers. (bundled with #1)
3. **Distro bundle boots** — re-sync `dist_manifest.txt` (7 missing modules) **and** add a smoke-boot gate to `build_distro` (`import anchor_gui` in the staging dir; fail the build on drift).
4. **Bundle-only distribution** — the scrubbed bundle is the sole share channel (skills verified inside it); never hand out the working repo.
5. **Onboard makes it real** — genuinely stand up the instance, mint+persist the token (satisfies #1's constraint), wire it end-to-end, honest cross-platform launch.

### P1
6. **Durability cluster (all four):** (a) route `anchor.py` CLI + ~10 secondary writes through `atomic_write_text`; (b) real cross-process lock (retire the shared `.tmp` name); (c) rebuild a torn efforts index from surviving pointer files (no heal-to-empty); (d) boot-reaper owner-set fix (don't delete a live worktree after a server-only crash).
9. **Cross-platform readiness:** honest POSIX launch/onboard, single upfront dependency gate (Python/git/`claude` CLI), purge hardcoded `john`/`C:\` paths.
10. **Governance packaging (full):** bundle canonical `AGENTS.md` conventions (10-min status format), skills **read-only** + foundry-only-edit enforced where practical, ship driver-init defaults so skills self-configure to the collaborator's engine subscriptions.
11. **Hygiene (all three):** (a) fix `requirements.txt` (drop flask/Pillow); (b) move/delete the ~15 root `fix*.py` scratch scripts; (c) make the test billing guard **fail-closed** (suite refuses a real engine without explicit opt-in).

### P2
7. **Monolith follow-through:** move the 123 already-dispatched handlers into real modules (proven by the project-window.js extraction) + memoize `GET /` lane reads (read each lane once).

### P3 — queued, its own future effort (NOT this run)
8. **WAL inversion:** make `journal.py` the single source of truth, demote registries/summaries to derived, replay-rebuilt views (`effort_view.py` proves the pattern). The permanent durability cure; multi-quarter; deserves its own Crucible pass. Queued so it isn't forgotten.

## Honest caveats carried in
- Recommendations are **advisory** — the Gandalf `--live` cross-family refutation did not resolve (deterministic seam bug, journaled gandalf/0276-0277); the **diagnosis** was graded PROMISING (Fable-5 deep-think, single-family ceiling). Reader sub-agents were not pinned to Fable-5 (evidence-gathering seat only).
- Decomposition (P2) + WAL inversion (P3) carry regression risk against a large wave-pinned suite.
