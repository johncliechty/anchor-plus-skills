# Zombie Hunter — Operator Runbook (W10 / P7)

Secondary operator docs only. Arm/disarm control plane is enforced in code (`mode.js` + canaryReceipt), not by this runbook.

## Freeze then Kill

1. Prefer **Freeze** (reversible NtSuspendProcess on the sole boundary `freeze.js`) before Kill.
2. Confirm spend postcondition class when reported (`STOPPED` / `CONTINUES` / `UNCERTAIN`).
3. **Kill** requires server-validated confirm token every time; tree-kill + death verify; row removes only on success.
4. Kill-without-freeze stays disabled until `freezeCapability` is proven under the operator envelope.

## Red vs abstain vs observe-only

| Signal | Meaning | Action |
|--------|---------|--------|
| **Actionable RED** | Armed mode + joint quad would-be RED | Freeze/Kill chrome may light (if capability allows) |
| **Observe-only** | Shadow dual-run `wouldBeActionableRed` | Investigate only — no scare reap affordance |
| **Abstain** | Any uncertain leg (supervision/spend/engine/ownership IPC) | Never RED; Uncertain ≠ red |
| **KEEP** | Supervised **active** interactive host **or** Anchor-owned / ownership fail-closed | Do not Node-reap |

## What “tied to a session” means (2026-07-23)

Supervision is **active session**, not mere host image on the parent chain:

| Host | KEEP (supervised) when |
|------|-------------------------|
| VS Code / Cursor | Process on ancestry **and** interactive user SessionId (not services session 0) |
| Anchor | `python`/`pythonw` + `anchor_gui.py` on ancestry **and** interactive SessionId |
| PowerShell / cmd / other shell | Interactive SessionId **or** not job-orphaned; **session 0** and **taskeng/svchost-only** shells do **not** KEEP |
| Windows Terminal / conhost / explorer / grok | Allowlisted ancestor **and** not session 0 |

**Zombie (unsupervised leg):** engine + paid spend + **not** under any of those **active** sessions (+ not Anchor-owned). Stale shells must not protect spenders.

## Long engines vs agent sessions (universal)

Long Crucible/Foreman/foundry runs should launch **outside** the interactive agent’s process/Job tree when the chat host reaps tool children. This is **not Grok-only** — Claude Code, Cursor agents, and Gemini/agy tool shells can do the same. Canonical note: `<path>

## Doctor vs Investigate

| Surface | When | Seed |
|---------|------|------|
| **Investigate** | Selected process / zombie radar candidate | Slim: pid, class, top reason codes, freeze/kill status; optional deep brief |
| **Doctor** | Health / reaper-health banners, system diagnosis | issueId, exact message, component, lastError, suggestedChecks (not a markdown path) |

## Shadow vs armed

- **Shadow (default):** dual-write dark — no actionable RED on radar, dashboard banner, or reaper-health scare. Observe dual-run fields still visible (dark ≠ silence). Freeze/Kill refused.
- **Armed:** only after operator arm request **and** a version-matched `canaryReceipt` with SC1 canary green. Atlas/allowlist hash bumps force re-shadow.

## Arm / disarm / re-shadow

1. **Arm** — requires version-matched canaryReceipt (classifier + host allowlist + engine atlas + spend atlas hashes) and `sc1CanaryGreen` from the G5 `sc1_canary_gate` evidence pack. Residual host attestation alone cannot mint global arm.
2. **Disarm** — request shadow / clear receipt path / set kill-switch style refuse; runtime forces shadow without a valid receipt.
3. **Re-shadow** — automatic when any atlas/allowlist hash bumps (`test_atlas_bump_forces_reshadow`); also after false-positive armed events (operator policy).

## Ownership badge

- Badge fields: `owned`, `keep`, `failClosed`, `label`, `reasonCodes`, `stub`, `stubMaxWave`.
- **Freeze/Kill hidden when owned** (or ownership fail-closed KEEP).
- Anchor-registered sessions stay on the Anchor reaper path, not Node kill.

## Health fields (W10)

- `abstainRate` — fraction of engines abstaining this sweep (flying-blind signal).
- `unsupervisedSpendTruePositiveCount` — joint would-be unsupervised paid-spend shapes (OL1 TP signal).

## Process depth / reaper passes (Track B6)

- **`REAPER_PASSES_MIN = 1`** — LITE may use a single ownership-confirmation pass; **never 0**. Zero passes would skip multi-pass confirmation and is load-fail closed in `@foundry/triage`.
- **FULL multi-pass** remains **mapping-driven** (live `BAND_MAPPINGS['zombie-hunter'].FULL.reaperPasses`), not a hard-coded literal in the skill.
- Depth may thin ceremony (UI chrome / explain verbosity) only. **`requireProofOfDeath` and abstain-by-default stay true** at LITE, FULL, and SPIKE — never assign `requireProofOfDeath=false`, `abstainByDefault=false`, or `reaperPasses=0` from a depth branch.
- Depth pins: `FOUNDRY_TRIAGE_DEPTH` > `ZOMBIE_DEPTH`; unknown refuses; missing → FULL default.

## SC1 human sign-off (promotion-only)

Optional human checklist in `fixtures/sc1/sc1-human-signoff-checklist.json` must bind to the **same G5 evidence paths and receipt hash tuple** as `sc1_canary_gate`. Sign-off never enables Freeze/Kill by itself.

## Telemetry retention (P2 2026-07-25)

`telemetry.db` grows without bound (observed at 152 MB inside the versioned skill
folder — ironic for the hygiene sentinel). It is now gitignored along with
`_foreman-status.log`/`_sentinel-err.log`. Retention: when it exceeds ~200 MB, stop the
sentinel, archive or delete the db (it is rebuildable runtime telemetry, not product
state), and restart. A future wave may add automatic rotation; until then this runbook
entry IS the rotation policy — do not let the db ride a release.
