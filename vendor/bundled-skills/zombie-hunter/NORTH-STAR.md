# North Star — zombie-hunter (BOTH substrates) — adapted in-folder 2026-07-25

> The locked origin document is `<path>
> (Gandalf "NOT safe to ARM" remediation, locked 2026-07-05). This file brings the North
> Star INTO the skill folder (it governed the skill from another repo's planning dir for
> 3 weeks) and extends it to the second substrate the skill has since grown. Amending
> either section is a human re-lock, not an edit.

## The objective

Kill or freeze ONLY a truly-orphaned sub-agent swarm — NEVER a legitimate run — via
ownership-based liveness, positive proof-of-death, abstain-by-default, and a
token-authenticated control plane. When in doubt, do nothing, loudly.

## Substrate 1 — the Python reaper (Anchor service)

Locked criteria carried verbatim from the 2026-07-05 lock (see origin doc for full text):
1. **Abstain by default (fail SAFE, never fail deadly)** — any exception, None, missing
   input, stale timestamp, partial set, empty owner-set, or degraded snapshot reads as
   OWNED/alive at every call site (`tests/test_reaper_abstain.py` incl. the source-grep
   assertion).
2. Single liveness source (ownership-based, not process-image identity).
3. Blast radius: `ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP` cap + boot grace + unknown-age ⇒ PROTECTED.
4. Win32 ctypes / STILL_ACTIVE (259) proof-of-death; restart-durable freeze.
5. Arming gate: SC1 canary receipt (version-matched) or the armed family REFUSES.
6. Spec truth: SKILL.md describes the SHIPPED mechanism, never an aspiration.

## Substrate 2 — the Node token-spend sentinel + The Ward GUI (this folder)

Grown after the lock; held to the same posture:
1. **Shadow before armed** — `classifierMode: shadow` until a human arms it through the
   SC1-gated ladder (`src/mode.js`: armed family refuses without a version-matched
   canary receipt; receipts cannot be written without `sc1CanaryGreen`).
2. **Quad predicate keeps** — SUPERVISED / QUAD_KEEP / VERDICT_KEEP: a keep-shaped
   answer at any leg ends the question (mirror of criterion 1).
3. **Measured dollars only** — the burn ledger's `evidenceClass: measured|activity`
   never invents spend; multi-engine collectors report what they can PROVE.
4. **The GUI is a viewer + explicit-action surface** — classifyAll runs read-only in a
   worker; Freeze/Kill stay forbidden until the armed gate passes (SC1 not claimed by
   a slim seed ⇒ report CLEAN, refuse action theater).
5. **Runtime debris is not product** — telemetry.db + status logs are gitignored and
   rotated (see OPERATOR-RUNBOOK); the skill that polices hygiene keeps its own.

## Non-goals

- Never arm on schedule or on trend — arming is a human act through SC1, both substrates.
- Never kill on identity (process image/name) — ownership + proof-of-death only.
- Never present an abstain as a scan failure, or a failure as CLEAN.
