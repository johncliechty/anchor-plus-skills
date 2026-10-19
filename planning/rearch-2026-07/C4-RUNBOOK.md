# C4 live-demo runbook — restart survival on the real service (rearch W17)

**Criterion (C4, non-negotiable half):** a spawned lane job keeps running across
`nssm restart anchor`, and the restarted dashboard reports it live with an
advancing tail. **This criterion is honestly UNMET until this runbook has run
once on the real service** — the hermetic gate proves the mechanism; only a live
run proves the cross-process survival. Run this WITH John, in one sitting.

The mechanical steps below are scripted by the harness `tools/c4_live_demo.py`
so this runbook is *executable*, not prose. Because a real cross-process restart
must land BETWEEN launch and verify (and the one-shot `run_demo` rolls back in
its own `finally`), the live run uses the harness's **phased** CLI —
`--phase launch` → *(manual `nssm restart anchor`)* → `--phase verify` →
`--phase rollback` — each phase a production-safe building block
(`setup_demo_project` · `launch_demo_job` · `verify_survival` · `rollback_demo`)
operating against the LIVE `ANCHOR_DATA_DIR`. The only difference from the
hermetic gate is that here the restart is the REAL `nssm restart anchor`, not a
simulated in-memory table teardown.

---

## Prerequisites

- The `anchor` NSSM service is running on :8777 (`Get-Service anchor`).
- The supervisor service is installed (`install_supervisor.ps1`) and the
  dashboard is in **external** mode (`ANCHOR_SUPERVISOR=external`), so job
  ownership already lives in the separate process (W16). If the supervisor is
  down the dashboard degrades to inline and the demo still proves the durable
  re-adoption, but the true cross-process survival needs external mode.
- An elevated PowerShell (nssm restart requires it).
- `ANCHOR_RUNNER_CMD` points at the deterministic `tests/fake_claude.py` mock
  for the demo job — **no real model call, no side effects**.

## Step 1 — register a dedicated THROWAWAY R&D project

A disposable project, never a real one, rooted at a scratch folder. The
`launch` phase registers the project AND launches the job (Step 2), prints the
`project_id` + `job_id`, and **leaves the job running** (no rollback) so the
restart can land next:

```powershell
# scratch folder OUTSIDE the repo (git stays clean)
$root = Join-Path $env:TEMP "c4-live-demo"
python tools\c4_live_demo.py --phase launch --root $root
# → prints {"project_id": "...", "job_id": "...", "went_live": true}
```

Or, driven from the dashboard: **New project** → name `C4 Live Demo (throwaway)`
→ point it at the scratch folder. Note its `project_id`.

## Step 2 — launch a harmless long-running job through the REAL launch path

The `--phase launch` command above launches a **build** lane job (folder-locked,
so the demo proves BOTH the lane slot and the folder-build lock survive) that
drips lines for ~10s then sleeps — the same lane-guarded launch the dashboard's
`/api/rnd/launch_lane` build path uses (`supervisor.launch_guarded`).
fake_claude-driven, harmless (default job args `--lines 60 --line-interval 0.15
--sleep 3`).

Confirm it is live: the launch output shows `"went_live": true`, and the project
window shows a running (green) tile with an advancing tail; note the `job_id`.

## Step 3 — restart the dashboard MID-FLIGHT (the demo)

From the elevated shell, with the job still dripping lines:

```powershell
nssm restart anchor
```

## Step 4 — expected observations (the criterion, demonstrated)

After the restart, WITHOUT relaunching the job, run the **verify** phase against
the `job_id` from Step 1 (it re-adopts via `supervisor.rebuild` — the same
idempotent boot re-adoption the dashboard performs):

```powershell
python tools\c4_live_demo.py --phase verify --job-id <job_id> --project-id <project_id>
# → prints {"survived": true, "listed_running": true, "tail_advanced": true, ...}
```

Expected, WITHOUT relaunching the job:

- The job process **never stopped** — its OS pid is still alive across the
  restart (supervisor-owned; the dashboard restart did not reap it).
- The restarted dashboard lists the **SAME `job_id`** as running (re-adopted
  from the durable records at boot — `supervisor.rebuild()`).
- Its `/api/rnd/tail` cursor **keeps advancing** (the persisted read offset
  survived and the log kept growing).
- The lane slot and the folder-build lock are **rebuilt** (a second launch in
  the same lane/folder is still serialized).
- `cancel` from the dashboard **tree-kills** the job cleanly.

Record the observed `job_id`, the pre- and post-restart tail offsets, and the
pid liveness in the execution log below.

## Step 5 — rollback (supervisor stop + lane-lock clear)

Always leave the service clean. The **rollback** phase targets the SAME
`job_id`/`project_id` from Step 1 — it cancels the *live* demo job (never starts
a new demo): cancel reaps the process AND releases the lane lock,
`release_slots` clears any stranded lock defensively (idempotent), and the
throwaway project is retired (kept, never hard-deleted):

```powershell
# 1–3. cancel the LIVE demo job + clear the lane lock + retire the project:
python tools\c4_live_demo.py --phase rollback --job-id <job_id> --project-id <project_id>
#    (or use the dashboard Stop button on that job's tile)

# 4. if the supervisor was started only for the demo, stop it:
nssm stop anchor-supervisor
```

The harness `rollback_demo(sup, job_id, project_id)` performs steps 1–3
mechanically and never raises; step 4 (**supervisor stop**) is the ops command.

---

## Execution log

> **STATUS: NOT YET RUN.** This cell is filled in only after the runbook is
> executed live on the real service WITH John — it is never fabricated. Until
> then C4's live half is honestly unmet (the hermetic gate
> `tests/test_c4_w17.py` proves the mechanism; this cell proves the deploy).

| field | value |
|-------|-------|
| date run | _(pending)_ |
| operator | _(pending — run WITH John)_ |
| project_id | _(pending)_ |
| job_id | _(pending)_ |
| tail offset before restart | _(pending)_ |
| tail offset after restart | _(pending)_ |
| job pid alive across restart? | _(pending)_ |
| same job_id listed live after restart? | _(pending)_ |
| cancel tree-killed cleanly? | _(pending)_ |
| rollback clean (lane lock cleared, project retired)? | _(pending)_ |
| supervisor mode during demo | _(pending — external expected)_ |
| notes | _(pending)_ |
