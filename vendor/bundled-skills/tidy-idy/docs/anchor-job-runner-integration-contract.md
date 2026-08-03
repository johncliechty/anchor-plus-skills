# Anchor `job_runner` integration contract (Wave 5)

**Status:** written from job_runner's ACTUAL source, not from its documentation.
**Sources read:** `<path> (1729 lines) and `<path> 2026-07-21.
**Scope:** what Anchor's Tidy-Idy button may do, and what it must NOT do.

The button is a THIN CALLER. It **dispatches** the tool's own entry point and
**opens** the URL that run prints. It adds no launch logic, no archive logic and
no panel logic. Everything below exists so that claim is checkable rather than
asserted: each row names the source fact it rests on, and every place the source
does *not* support what the plan assumed is called out explicitly.

---

## 1. Job-spec schema (source: `launch` / `launch_guarded`)

`launch_guarded(lane, project_id, folder_path, cwd=None, extra_args=None,
env=None, job_id=None, backend=DEFAULT_BACKEND, prompt=None, output_dir=None,
gated=False, permission_mode=None, command=None)`.

| field | value for a tidy run | why (source fact) |
| --- | --- | --- |
| `command` | `[node, <skill>/bin/tidy-idy.mjs, <root>, --environment=anchor, --json, --nonce-file=<path>]` | `launch()`'s docstring and body: when `command` is set "it IS the launched command verbatim" and backend resolution / `ANCHOR_RUNNER_CMD` indirection deliberately do not apply. A tidy run is deterministic local code, not a model seat, so it dispatches on this seam. |
| `lane` | `"build"` (`job_runner.BUILD_LANE`) | See §3 — the folder-level resource claim is BUILD-lane-only in the source. |
| `project_id` | Anchor's project id, when the button has one | Used as half of the `(project_id, lane)` same-lane serialization key. |
| `folder_path` | the project root | The key of the folder build lock. |
| `cwd` | the project root | Passed straight to `subprocess.Popen(cwd=...)`. |
| `gated` | `False` | `gated` truthiness opens a kept-open stdin PIPE and registers a gate adapter sink. A tidy run answers no AskUserQuestion frames; it must stay on the `stdin=DEVNULL` contract. |
| `backend` / `prompt` / `output_dir` / `permission_mode` | unset | Inert when `command` is given. |

The record `launch()` returns and persists contains at least
`{job_id, lane, pid, status, log_path, cwd, started_at, exit_code, session_id,
backend, crypt_token, proc_create_time, relaunch_spec}`, plus `project_id` /
`folder_path` stamped by `launch_guarded` via `_update_record`.

**Namespacing:** the tidy job type is identified by a `job_type: "tidy"` marker
on the spec, NOT by a bespoke lane — see §3 for why a bespoke lane would silently
cost the folder claim.

---

## 2. Completion-hook mechanism — THERE IS NO CALLBACK

Source: `_finalize(job_id, exit_code, result_envelope=None)`. On process exit the
reader thread calls it; it writes a terminal `status` (`done` when `exit_code == 0`,
else `failed`, preserving a deliberate `cancelled`/`interrupted`), stamps
`finished_at`/`exit_code`, emits `EV_JOB_FINISHED` to the journal, mirrors the
swarm session status, and best-effort bridges cost into `effort_history`.

**It invokes no caller-supplied hook.** There is no registration API for one
anywhere in the module. Completion is OBSERVED, via:

- `load_record(job_id)` → `status` in `TERMINAL_STATUSES`
  (`done | cancelled | interrupted | failed`);
- `tail(job_id, since)` / `long_poll(job_id, since, ...)` / `all_lines(job_id)`
  over the durable log at `<ANCHOR_DATA_DIR>/rnd_jobs/<job_id>.log`.

**Consequence for the button** (implemented in `engine/launch/anchor-caller.mjs`):
it watches the durable log for the run's own `panel-ready` line rather than
waiting to be called back. It does not poll for the run to FINISH before opening
the panel — the panel is up while the process is still alive holding the lock.

**Consequence for stdout discipline** (a safety property, implemented in
`bin/tidy-idy.mjs`): the durable log is a FILE. So under `--json` the run prints
the panel's base URL and the *path* of a 0600 bootstrap file — never the
single-use bootstrap URL itself, and never the capability token. The nonce is
read from that file by the opener, and the server unlinks it on redemption.

---

## 3. Resource-claim support — and the one place the plan's assumption is wrong

Source: `launch_guarded`, `_ACTIVE_LANE`, `_FOLDER_BUILD`, `BUILD_LANE`,
`REFUSED_SAME_LANE`, `REFUSED_FOLDER_BUILD`, `lane_holder`,
`folder_build_holder`, `release_slots`.

Three gates, all evaluated inside `paths.WRITE_LOCK`:

1. **Global spawn cap** — `ANCHOR_SPAWN_CAP` (default 16) counted over genuinely
   live jobs + live PTY children → `LaneBusyError("spawn-cap-reached")`.
2. **Same-lane, within a project** — `(project_id, lane)` must be free →
   `LaneBusyError(REFUSED_SAME_LANE, holder=<job_id>)`.
3. **Folder build lock** — **only when `lane == BUILD_LANE`** →
   `LaneBusyError(REFUSED_FOLDER_BUILD, holder=<job_id>)`.

> **The correction.** A "namespaced tidy lane" would get gate 2 and NOT gate 3.
> A Foreman build (`lane="build"`) on the same folder would therefore NOT queue
> behind it — the exact R1 sequence the amendment is about. So the button
> dispatches the tidy run on the **build lane** to acquire the real folder claim,
> and namespaces the job by `job_type` instead. The namespacing that the plan
> actually needs — "never rows in Gandalf's index" — is about the RUN INDEX (§4),
> and it holds regardless of lane.

**Both claims are advisory-to-each-other, and neither is the authority.**
job_runner's registries are *in-process* tables (their own comment says so): a
second Anchor server, a bare CLI run, or a killed-and-restarted server sees none
of them. The tool's OWN lockfile is the cross-agent authority (§5). The
job_runner claim is strictly additive.

---

## 4. Run-index conventions (source: `gandalf.py`)

| Gandalf (source) | tidy-idy (this wave) |
| --- | --- |
| artifacts at `<folder>/gandalf/run-<ts>/` (`GANDALF_DIRNAME`) | artifacts at `<root>/reports/tidy/run-NNN/` |
| index at `<folder>/.anchor/projects/<id>/gandalf/index.json` (`_index_path`) | index at `<root>/.tidy-idy/runs-tidy/index.json` — **tool-owned**, so a folder with no Anchor project store still has a history |
| `_append_index` UPSERTS by `run_id` and CAPS to `ANCHOR_GANDALF_MAX_RUNS` (default 20) | append-only, newest-first, **no upsert and no cap** — "previous reports kept as browsable references, never overwritten" is a criterion here |
| `_add_gitignore_best_effort` appends `gandalf/` to the project `.gitignore` | never touches the user's `.gitignore`; the archive self-ignores from the inside (`reports/tidy/.gitignore` = `*`), preserving the consent-scope invariant |
| per-run files `report.md`, `exec-summary.md`, `advisor-output.json` | per-run files `envelope.json`, `report.md`, `protection-withheld.json`, `excluded-subtrees.json`, `cost-and-coverage.json` |

**No tidy run writes a row into Gandalf's index, reads it, or changes any file
Gandalf owns.** Gandalf's existing suite is therefore the no-behavior-change
regression suite for this integration: nothing in this wave touches
`gandalf.py`, `job_runner.py`, or any file either of them writes.

---

## 5. Cross-agent lock authority (the R1 refinement)

**The well-known path:** `<project-root>/.tidy-idy/tidy-idy.lock`
(exported as `TIDY_LOCK_REL` from `engine/launch/lock-authority.mjs`).

**The record** (written by `engine/apply/lock.mjs`, JSON):

```json
{ "version": 1, "pid": 1234, "jobId": null, "purpose": "run",
  "host": "...", "token": "...", "acquiredAt": "2026-07-21T12:00:00.000Z" }
```

**The consult**, for any process in any language, is three steps:

1. read and JSON-parse the file — absent/unreadable ⇒ **not held**;
2. check whether `pid` is alive — dead owner ⇒ **stale ⇒ not held** (this must
   match the writer, which steals a dead owner's lock; a consulter that queued on
   a stale lock would wedge the folder the writer would happily reclaim);
3. otherwise **held** ⇒ QUEUE, never mutate.

Python sketch for Anchor's Foreman/Gandalf launchers:

```python
import json, os
from pathlib import Path

TIDY_LOCK_REL = ".tidy-idy/tidy-idy.lock"

def tidy_lock_holder(folder_path):
    """Return the holder record if a live tidy run owns this root, else None."""
    p = Path(folder_path) / TIDY_LOCK_REL
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None                      # absent or corrupt == not held
    pid = rec.get("pid")
    try:
        os.kill(int(pid), 0)             # Windows: use proc_probe / psutil
    except PermissionError:
        return rec                       # alive, not ours to signal
    except (OSError, TypeError, ValueError):
        return None                      # dead owner: stale, reclaimable
    return rec
```

A launcher that finds a holder QUEUES (or refuses with the holder shown); it does
not mutate the root. The JS side of the same decision —
`guardMutatingLaunch()` / `queueBehindTidyLock()` — has no "mutate anyway" branch
at all, and `test/launch-lock-authority.test.mjs` drives a mock Foreman build
against a locked root to prove it queues.

**Symmetrically**, a standalone CLI run that detects an Anchor-managed workspace
registers a best-effort job_runner resource claim
(`registerResourceClaimBestEffort`). Best-effort is load-bearing: every failure
there is swallowed, because the run's correctness already rests on the lockfile
taken before any analysis started.

---

## 6. What the button MUST NOT do

- open a second panel, or serve any tidy content itself;
- write anything under `reports/tidy/` or `runs-tidy/` — the run does that;
- read or mint the capability token (it is server-memory-only and never leaves
  the redeemed panel body);
- put the bootstrap NONCE anywhere but the 0600 file / the loopback URL;
- take the tidy lock, release it, or delete the lockfile;
- write a row into Gandalf's index, or otherwise touch Gandalf's files.
