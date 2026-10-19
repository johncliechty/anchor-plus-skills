# Process rails — the codified standing rituals (W3)

The re-architecture's standing rituals, codified once (W3) and binding on
every later wave. These are process rails, not code: each wave's EXECUTION
LOG records compliance, and W18's closure audits it.

## 1. Per-wave live-service smoke checklist

Run after EVERY merged wave's deploy to the live service (John's daily use
never breaks — North-Star criterion 7). All steps, in order, from an elevated
shell where noted:

1. `nssm restart anchor` (elevated) — the service restarts cleanly.
2. `GET http://localhost:8777/` returns **200** and the page's
   `window.ANCHOR_BOOT.build_id` is the NEW build (no stale supervisor).
3. A project window loads (`GET /project/<id>` 200, window renders, no JS
   console errors).
4. A healthcheck run (`python anchor_healthcheck.py`) finishes **green** —
   including the pillar-state assertion (the live flag configuration is a
   NAMED hybrid state).
5. (post-W11) `git status --porcelain` on the repo is empty.

Record the result (pass/fail + anything observed) in the wave's execution
log. A failed smoke = the wave is NOT done, whatever the test suite says.

## 2. Healthcheck SLO

The daily 5AM healthcheck is the effort's continuous proof, so it gets a
service-level objective:

- **Wall-time cap:** the full run completes in **≤ 15 minutes**; a run that
  breaches the cap is a FAILED run even if every check passed.
- **Zero known flakes:** a check that flakes is fixed or explicitly
  quarantined BY NAME (with an issue recorded) — never re-run-until-green,
  never tolerated silently.
- **Quiescence:** walks that read live stores snapshot under `WRITE_LOCK` or
  tolerate a bounded tail window (the W14 parity discipline) — no
  race-shaped assertions.
- **Retry with classification:** a retried step must record WHY the first
  attempt failed ("Auto-fixes applied" degradation, not silent success).
- **20× nightly before 5AM:** every NEW walk (journal parity · supervisor
  probes · cookie/auth · relocated-data-dir) joins the 5AM run only after
  **20 consecutive green nightly repetitions** under this SLO.

## 3. Auth-flip sequencing rule

An auth-policy flip (open → warn → enforce on any route batch)
NEVER ships in the same deploy as JS changes calling the flipped routes.
Order, always:

1. ship the client/consumer token paths (W2-style) and soak;
2. flip the batch to **warn** on the live service; review the warn log —
   every would-401 maps to an enumerated consumer with a token path, or the
   flip holds;
3. flip to **enforce** in its own deploy, with the live tokenless-401 probe
   asserting the flip took.

A rollback of the flip is a FLAG change (`ANCHOR_AUTH_MODE`),
never a code revert (the pillar off-switch discipline, `pillar_flags.py`).

## 4. Soft merge-freeze protocol (the extraction waves)

While W4–W6 operate on `anchor_gui.py`'s embedded frontend:

- **Freeze scope:** no non-extraction change lands on `anchor_gui.py`
  between the pre-wave sentinel commit and the C1 exit gate (W6).
- **Exception path:** an urgent fix that must touch `anchor_gui.py` lands
  first, and the in-flight extraction increment REBASES onto it and re-runs
  the byte-parity gate + the anchor-freshness gate before proceeding.
- **Lift:** the freeze is formally lifted when W6's exit gate merges (the
  wave's done-when), recorded in the execution log.

## 5. Pillar-flag / hybrid-state ritual

Every deploy states which NAMED hybrid state (`pillar_flags.py` matrix) the
live service lands in; the healthcheck's `check_pillar_state` asserts it
continuously. Flag flips follow the cross-pillar DAG
(`planning/rearch-2026-07/PILLAR-DAG.md`); an unnamed combination is a
deploy-blocking failure, not a warning.
