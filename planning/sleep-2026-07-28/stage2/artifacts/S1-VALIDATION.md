# S1 Validation — live session script

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W22 — Phase 5: S1 post-build validation session + terminal status emission
Branch: **v1.2** (this effort only — never publish to v1.1.x collaborators)

## Status of this session

| field | value |
|-------|-------|
| session kind | **live with John** — not a structure test |
| S1 overall verdict | **PENDING** |
| date of overall verdict | _(blank until John records)_ |
| recorded by | _(blank until John records)_ |
| North Star | **pending S1** — structural gates alone cannot declare MET |

> **Do not fake S1.** This file ships with every step and the overall verdict as
> PENDING. Only John, running live on branch v1.2, may fill the dated result
> lines. An agent-authored PASS is not evidence. Until S1 returns a real
> verdict, `exit_register.terminal_status()` must emit the structural
> CANDIDATE-MET phrase with North Star pending S1.

S1 is the **only** gate that may convert a criterion's CANDIDATE-MET stamp to
MET in `artifacts/TRACEABILITY-MATRIX.md`. A step John fails reverts that
criterion to OPEN.

Upstream task triple (W1): `artifacts/verification-task-triple.json` — open /
run / stop-restart. S1 replays those three and adds Doctor diagnose + session
attach (the six North-Star controls).

---

## Preconditions

1. Branch **v1.2** is checked out.
2. Anchor service is running and the dashboard is reachable
   (`http://localhost:8777/` or the live Tailscale surface John uses).
3. Structural waves W1–W21 are GREEN at the rendered-string level
   (CANDIDATE-MET only — not MET).
4. Exit register is reconciled; signed exits (if any) are listed honestly in
   the terminal status string — never hidden to force an unqualified phrase.

---

## Session steps

For each step: run exactly as written, then fill **John's dated result**.
Leave blank / PENDING until the live run. Do not pre-fill PASS.

### Step 1 — open

| field | value |
|-------|-------|
| control | open |
| maps to | verification-task-triple `T1-open` |
| branch | v1.2 |

**Script**

1. Hard-refresh the dashboard (`Ctrl+Shift+R`).
2. Open the R&D project registered against this repository.
3. Click open on an existing effort tile (planning or build).
4. Observe: effort documents reachable, or a **named** cannot-open state with
   reason — never a dead control, blank pane, or silent no-op.

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

### Step 2 — run

| field | value |
|-------|-------|
| control | run |
| maps to | verification-task-triple `T2-run` |
| branch | v1.2 |

**Script**

1. From the open project window, start a live session (Open terminal / general).
2. Enter a one-line prompt and wait for the response to stream.
3. Read usage / time / cost on session chrome and on the project tile.
4. Observe: every value is a measured number **or** a named state
   (`unknown` / `empty` / `zero_measured` / `pending` / `unmeasured`) — never a
   silent zero, never a fabricated `$0.00`, never a bare empty where state is
   unknown.

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

### Step 3 — stop

| field | value |
|-------|-------|
| control | stop |
| maps to | verification-task-triple `T3-stop-restart` (stop half) |
| branch | v1.2 |

**Script**

1. Close the running session from its panel control.
2. Read the stop summary tile left behind.
3. Observe: in-flight work is listed with counts traceable to inventory, or a
   named unknown if inventory could not be read — never an empty-looking
   "nothing was in flight" when the inventory was unreadable.

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

### Step 4 — restart

| field | value |
|-------|-------|
| control | restart |
| maps to | verification-task-triple `T3-stop-restart` (restart half) |
| branch | v1.2 |

**Script**

1. Count restart controls in this context — there must be **exactly one**.
2. Use that control; confirm it names its scope and preserved/lost contract.
3. Optionally warm-restart the service (`restart_anchor.ps1` elevated) and
   reopen the session tile; session should return warm rather than cold.
4. Observe: no dual Restart + Restart session; no dead restart button when
   restart is impossible (named cannot_restart instead).

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

### Step 5 — Doctor diagnose

| field | value |
|-------|-------|
| control | Doctor diagnose |
| maps to | W14/W15 diagnose surfaces (not in the W1 triple; S1 owns the live check) |
| branch | v1.2 |

**Script**

1. Open Doctor and run Diagnose.
2. Observe: findings quote live readings (or a named no-finding / unknown
   state). A **dead Diagnose control** is BUILD_BLOCKING — never route to E6.
3. Confirm depth labels when multi-engine reports are shown.

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

### Step 6 — session attach

| field | value |
|-------|-------|
| control | session attach |
| maps to | W11 attach surface (not in the W1 triple; S1 owns the live check) |
| branch | v1.2 |

**Script**

1. From a session that supports attach, invoke session attach.
2. Observe: attach succeeds with named state, or a named cannot-attach /
   failure state — never a dead control or silent no-op.
3. Confirm attach traces / payload honesty if the surface exposes them.

**John's dated result**

| field | value |
|-------|-------|
| outcome | PENDING |
| date | |
| observed line | |
| finding class (if any) | |
| notes | |

---

## Finding routing (machine-enforced)

Classify every S1 finding with `anchor.build.s1_findings`. The four North-Star
violation classes are **BUILD_BLOCKING** and **cannot** be routed to E6:

| class | token | routing |
|-------|-------|---------|
| dead control | `dead_control` | BUILD_BLOCKING — fix or named state; never E6 |
| silent zero | `silent_zero` | BUILD_BLOCKING — never E6 |
| mislabelled empty | `mislabelled_empty` | BUILD_BLOCKING — never E6 |
| raw-binary preview | `raw_binary_preview` | BUILD_BLOCKING — never E6 |

Other findings may be follow-on (E6) only when the classifier says so and
`exit_register.validate_justification` accepts E6 for that class.

---

## Overall S1 verdict

| field | value |
|-------|-------|
| **S1 verdict** | **PENDING** |
| date | |
| John confirmation line | |
| steps passed | _(blank)_ |
| steps failed | _(blank)_ |
| BUILD_BLOCKING findings | _(blank)_ |
| criteria reverted to OPEN | _(blank)_ |

Allowed verdict tokens (machine-read by `exit_register` / `s1_findings`):

* `PENDING` — default; North Star pending S1
* `PASS` / `S1 PASS` — only when every step above is live-PASS with dated lines
* `FAIL` / `S1 FAIL` — any BUILD_BLOCKING finding or failed North-Star step

### Machine-readable verdict block

```
S1_VERDICT: PENDING
S1_VERDICT_DATE:
S1_VERDICT_BY:
```

---

## Terminal status emission

Do **not** hand-write the North Star line. Emit via:

```text
from anchor.build.exit_register import terminal_status, ExitRegister
# default (S1 not run): CANDIDATE-MET … North Star pending S1
terminal_status(register.rows)  # s1_verdict defaults to pending

# after live S1 PASS and zero signed exits only:
terminal_status([], s1_verdict="PASS")  # → unqualified "ten criteria met"
```

Until this file's `S1_VERDICT` is a real PASS recorded by John, status stays:

> ten criteria CANDIDATE-MET (structural, rendered-string level) with N signed
> exits (E\<ids\>); North Star pending S1

Release: `tools/release_guard.py` refuses any publish path to v1.1.x
collaborators from this effort's branch/channel.
