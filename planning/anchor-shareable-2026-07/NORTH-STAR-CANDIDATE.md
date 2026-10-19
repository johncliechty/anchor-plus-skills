# North Star (CANDIDATE) — Anchor: securely & easily shareable

## Statement
Transform the integrated Anchor system — the Anchor app **+** the researchPrime/Crucible/Foreman trio **+** the foundry skills **+** their operating conventions — from a single-user, single-machine tool into a **package a trusted collaborator can obtain and run on their own Windows/macOS/Linux machine**, such that: (1) they receive it as a **scrubbed, self-contained bundle** that never carries the author's personal or proprietary data; (2) **onboarding brings up a working, secure-by-default instance with zero manual token handling**; (3) the instance is **safe to run and safe to expose** — no unauthenticated data-read or code-execution surface; (4) the **agent trio behaves identically** to the author's — same governance, status discipline, and skill-immutability; and (5) none of this **regresses** the durability, honesty, and safety engineering the system already has.

## Success criteria (checkable)
1. **Secure-by-default.** A freshly-onboarded instance placed behind a loopback reverse proxy (e.g. Tailscale Serve) returns 401 to a **tokenless** request on **every** data-plane, terminal, and directory-browse route, and the `bypassPermissions` build lane is unreachable without the token. No unauthenticated read, filesystem-enumeration, or code-execution surface remains.
2. **Zero-friction token.** The author and each collaborator **never manually find or type a token** — it is auto-provisioned + persisted locally at onboard, auto-used by the local browser, and survives restarts with no token step. Security comes from the token being *present + enforced*, not from manual entry.
3. **No-leak distribution.** The **only** share channel is the scrubbed bundle; a fresh scan of the shipped artifact contains none of the author's personal/proprietary files or git history, and `import anchor_gui` inside the staged bundle boots (smoke-gated so drift can't ship).
4. **Works-on-arrival, cross-platform.** A collaborator on Windows **and** on macOS/Linux can go bundle → onboard → live dashboard via one documented path; missing prerequisites (Python / git / `claude` CLI) surface as **one upfront actionable message**, not a deep per-job failure.
5. **Identical agent behavior.** The trio + foundry skills run on the collaborator's machine under the same governance — the 10-min status-table format, skills **read-only / foundry-only-edit**, and driver-init that self-configures to whatever engine subscription(s) the host has.
6. **No durability regression.** The durability cluster (CLI + secondary atomic writes, cross-process lock, torn-index rebuild-from-pointers, boot-reaper owner-set) is closed and covered; no new corruption/loss path is introduced; existing honest-telemetry, narration-floor, and reaper-safety invariants still hold.
7. **Money-safe + clean.** Running the test suite cannot spend real money without explicit opt-in (fail-closed); the shipped tree is free of dev debris and dependency-doc contradictions.

## Non-goals (explicitly OUT)
- **The WAL inversion** (journal-as-source-of-truth) — deferred to its own future effort; guard the boundary.
- **Multi-user / multi-tenant on one instance** — each collaborator runs their OWN single-user instance; this is NOT making Anchor multiplayer.
- **OS-level sandboxing of agent execution** — agents still run at the user's privilege (documented + accepted for the single-user-per-machine model); no containers/VMs in this run.
- **A frontend rewrite / framework migration** — the monolith work is decomposition-*in-place* (P2), not a rewrite.
- **Cloud hosting / a hosted service** — self-hosted on the collaborator's own machine only.
- **Observability/metrics stack** — out of scope.
- **Re-architecting the trio/foundry skills' internals** — we package + govern them, we don't rebuild them.

## Risk taxonomy
- **R1 — Security false-safe (highest consequence):** a fix makes it *look* secure while a bypass remains (incomplete Host/`X-Forwarded-For` validation; a newly-added route silently `AUTH_OPEN`).
- **R2 — Usability-vs-security tension:** mandatory token breaks the zero-friction requirement if persistence/cookie wiring is wrong → author annoyed → disables it → insecure.
- **R3 — Distribution incompleteness:** the scrubbed bundle silently omits something needed (a skill, a module, a convention) → dead/degraded on arrival; OR the scrub misses a personal-data file → leak.
- **R4 — Cross-platform breakage:** POSIX path/service/terminal differences → works on Windows, fails on Mac/Linux in ways the author can't test locally.
- **R5 — Durability-fix regression:** atomic/lock changes introduce a deadlock or perf cliff; the torn-index rebuild misfires.
- **R6 — Decomposition regression (P2):** moving handlers out of the monolith breaks behavior against the large wave-pinned suite — or the suite's flakiness masks a real break.
- **R7 — Governance over-enforcement:** hard-enforcing skill-immutability blocks a legitimate author/foundry edit loop.
- **R8 — Scope creep into P3:** durability work tempts a drift into the WAL inversion.

## Foresight brief (Parable of the Oranges)
- **The real goal** isn't "share code" — it's "collaborators become productive with the *same* system without the author babysitting their setup or leaking his data." So **onboarding UX and secure-by-default are the true load-bearing pieces**, more than any single code fix.
- **Two steps ahead:** the first collaborator *will* try to reach their instance remotely (that's how people use a personal dashboard from a laptop). If secure-by-default isn't airtight, the first real use is a breach — **plan for exposure as the expected case, not the edge case.**
- **Three steps ahead:** once shared, skills will improve — the governance model needs a working **update/redistribute path**, or collaborators fork and drift and the "identical behavior" guarantee rots. A distribution with no refresh story decays into stale forks.
- **A coming problem the author may not see:** the large wave-pinned test suite is *both* the safety net for the P2 decomposition *and* a flakiness source — the plan needs a test-suite-health thread, or the decomposition ends up gated by a flaky oracle.
