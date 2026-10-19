# Anchor sleep cycle — 2026-07-28

**Source:** the friction journal, 11 records captured 2026-07-26 → 2026-07-28.
**Two closed during triage; 9 remain.** Every record is John's verbatim words.
**North Star candidate:** John can run a real day's work through Anchor — and
through the steward — without hitting a dead control, a silent zero, or a
recovery path that destroys what he typed.

> **Rule from the intake brief itself:** *"Verify against the code before
> believing any diagnosis."* Everything in §2 below was checked against the code
> or the live system during triage. Where a record's premise turned out to be
> wrong, that is stated — those are the most valuable entries here.

---

## 1. Already fixed during triage (do not re-plan)

| Record | Fix |
|---|---|
| `2026-07-28-08` High Seat token re-prompt destroys input | **`3258464`** — a 401 now RETRIES the original request with the new token instead of `location.reload()`; stale `?token=` rewritten; `setAnchorToken({rejected:true})` no longer re-offers a refused token. 6 tests against the RENDERED dashboard. |
| `2026-07-27-02` Ecgberht had no version control | **`4134bcc`** — git repo + private mirror `E:/ecgberht.git`, versioned `v1.2.0-dev`. |

---

## 2. The nine open records, triaged

### P0 — blocks using the steward at all

**S1. Steward is reachable but unproven end-to-end.**
The High Seat auth blocker is fixed, but nothing has driven a real
speak → override → decide → artifact cycle since. The wiring gate
(`tests/test_ecgberht_steward_v12.py`, 22 tests) proves *structure*, not that a
human can hold a conversation with it.
**Wanted:** one genuine end-to-end steward session, journaled, with whatever
breaks captured as new records rather than fixed silently mid-run.

### P0 — dead controls (a dead button is worse than a missing one)

**S2. `2026-07-28-05` / `2026-07-28-07` — general session small-tab attach fails, Retry is dead, then it self-cleans.**
John's exact UI copy: *"Could not attach a live terminal (timeout). The warm view
below is still available."* — **printed twice, doubled**. Two distinct defects in
one symptom:
- the error is a **timeout misreported**; the record notes it was classified as
  unknown-session rather than timeout, so the user is told the wrong cause;
- the message **doubles**, which is the same duplicate-render family as the
  terminal double-print fixed on 2026-07-26 — check whether the attach error path
  re-mounts or re-appends rather than replacing.
- **Retry does nothing.** Either it re-issues a request that cannot succeed, or it
  is not wired. A dead Retry is a P0: it teaches the user the product is broken.

**S3. `2026-07-28-03` / `2026-07-28-04` — Doctor doesn't doctor.**
- Clicking **Diagnose** must actually run a diagnosis — *"not shell-only /
  seed-only / plan-only"* — and must also **fix** Anchor hygiene issues.
- The banner→Doctor handoff carries **no payload**: the Doctor session does not
  know what the health banner said. It must be seeded with the issue id,
  title/body, severity, lastError, suggested checks, report date/path, and the
  `diagnose=1` navigation context.
- **All three seats (Claude / Gemini / Grok) appear broken.** Verify each
  independently; report per-seat status honestly rather than a single blended
  "engine unavailable".

### P1 — the human cannot see what the system knows

**S4. `2026-07-28-01` — usage/time/dollars still invisible. ⚠ PREMISE CORRECTED.**
This was marked resolved at `121b479` and John reported it still broken. **He is
right that he cannot see it, and I was wrong to call it done — but the cause is
not what the record assumes.** Verified during triage:

```
project_effort_rollup('__dashboard__')
  -> {'tokens': 194422, 'cost_usd': 0.0, 'wall_clock_ms': 18549334, 'sessions': 11}
```

**The numbers exist.** The rollup is correct. The failure is entirely in
**surfacing** — the project dashboard, workbench tiles and session chrome do not
render it where John looks. So this is a UI wave, not a data wave.

Two sub-requirements from John's own success criteria:
- `cost_usd: 0.0` must **never** render as `$0.00` — that reads as "free". It is
  the locked no-pricing-table policy and must display as `(subscription)` or an
  equivalent honest-unmeasured label **with its reason**.
- Grok / no-sidecar cases that genuinely have no measurement must show a labelled
  unmeasured state, **not blank and not zero**.

**S5. `2026-07-28-02` — stopping a session leaves no tile summary; dual restart buttons; restart is not automatic.**
John: *"Restart quality is disappointing."* Stopping should leave a tile that says
what was being worked on. There are **two** restart controls where there should be
one, and restart does not resume on its own. This is the same complaint as the
original 2026-07-26 review item ("the summaries are not great and the restart docs
are not great — I often have to have the session do a search for what is going
on") — it was deferred to v1.2 then. It is now due.

**S6. `2026-07-28-09` — file preview shows raw binary for Word / PPTX / Excel / PDF.**
Clicking a file in the Project Files pane or the workbench list renders the raw
bytes. John: *"we need to have the capacity everywhere in Anchor where a file is
clicked on to be viewed that we see the human friendly version."* Note the phrase
**everywhere** — the fix belongs at the shared preview path
(`/api/rnd/project_file_content` → `previewProjectFile`), not per-pane. Opening in
a new browser window reportedly already renders correctly, so the working path
exists and should be reused rather than reinvented.
The record also carries a `JSONDecodeError: Unterminated string` in the logs —
likely the same endpoint choking on binary; confirm before assuming.

### P2 — friction, not failure

**S7. `2026-07-28-06` — Projects tab opens with every project folder expanded.**
John: *"That should not be the case."* Verified: `anchor_gui.py:7630` renders
`<details class="dash-tile" id="tile-projects">` and there are **zero**
`<details open>` in the file — so the expansion is happening in JS or CSS, not in
the emitted markup. Find the real cause before changing the template. Default to
collapsed, and remember the user's choice.

**S8. `2026-07-26-03` — a documented status cadence with no scheduler.**
My own record, deliberately left open. A cadence written into a plan file read as
an armed mechanism and nothing ever fired. The record's own suggestion is the
right one and belongs to Anchor, not to an agent's memory: *"Anchor could own
this — emit the status table itself from live session telemetry on a timer."*

---

## 3. Ordering (dependency-driven, not severity-sorted)

1. **S2 (attach/Retry)** — every other session-level fix is unobservable while
   opening a session is unreliable.
2. **S4 (usage surfacing)** — pure render work over data that already exists;
   fastest visible win, and it closes a record John has now raised twice.
3. **S3 (Doctor)** — largest single item; wants its own waves for diagnose-runs,
   banner payload, and per-seat verification.
4. **S5 (stop/summary/restart)** — depends on S2 being solid.
5. **S6 (file preview)** — self-contained; reuse the working new-window path.
6. **S7 (folders collapsed)**, **S8 (cadence)** — small, independent.
7. **S1 (steward end-to-end)** — last, because it is a *validation* pass over
   everything above, and its output is new journal records rather than code.

---

## 4. Gates this effort must satisfy

This is a v1.2 effort on Anchor, so both trio gates apply:

- **Crucible `bin/hardening-gate.mjs` (journal 0080/0081).** This plan will assert
  honesty properties — "never a silent zero", "unknown is labelled", "a dead
  control is a defect". Each must emit a mechanism, and every surface-bearing wave
  needs a failure-state table with **unknown and empty as separate rows**. That is
  literally S4's requirement, so the gate and the work agree.
- **Foreman `bin/delta-coverage-gate.mjs` (journal 0091).** Every wave touching a
  route, handler or frontend entry needs a test naming it. Anchor's convention is
  `tests/test_<subject>_<date>.py`.
- **Render-level assertions.** Anchor's dashboard JS is generated inside a Python
  f-string, so UI waves must assert against the **rendered** output and run
  `node --check` over the emitted script blocks — see
  `tests/test_auth_reprompt_2026_07_28.py` for the pattern. Source-level
  assertions do not prove what the browser receives.

## 5. Standing constraints

- **Never a silent zero.** Unknown, empty and zero are three different states and
  must render differently. This is the single most repeated defect across every
  review this month.
- **No pricing table.** Cost is `(subscription)`, never a fabricated dollar figure.
- **A dead control is a defect**, equal in severity to a crash — Retry, Diagnose
  and restart buttons must either work or not be shown.
- **Anchor v1.1.x stays steward-free.** This work is v1.2; collaborators are on
  `v1.1.2` and nothing here ships to them.

---

## 6. PRE-FLIGHT — read before launching Foreman (a live landmine)

`C:\dev\Anchor` root carries a **complete stale Foreman doc-set from three
different, unrelated efforts**. Launching Foreman with `cwd = C:\dev\Anchor`
would not halt — it would silently build the WRONG plan:

| Root artifact | Actually points at |
|---|---|
| `foreman.config.json` | `planning/anchor-doctor-ui/handoff/` — branch `foreman/doctor-v3`, models pinned `claude-fable-5` |
| `foreman-checkpoint.json` | `planning/share-canonical-onboard-2026-07/…` — `status: done`, 8/8 |
| root `IMPLEMENTATION-PLAN.md` | "Anchor Re-architecture — the Butler substrate", dated 2026-07-24 |

Per Foreman §4 an explicit `foreman.config.json` `docs` block **wins over the
heuristic glob**, so the ambiguity HALT never fires — the doctor-ui plan is simply
chosen. This is exactly foreman journal 0093 F4 ("refuse to start against a
foreign checkpoint"), and it is armed right now.

**Therefore:**

1. Crucible emits this effort's doc-trio into **`planning/sleep-2026-07-28/stage2/`**,
   with its **own** `foreman.config.json` beside it — never at the repo root.
2. Foreman runs with **`cwd = planning/sleep-2026-07-28/stage2/`**, the same
   isolation the steward-tracking run used successfully.
3. **Do not modify or delete the root artifacts.** They belong to other efforts
   and are not this effort's to clean up.

### Gate command — this repo can spend real money

Anchor's suite is `pytest`. There is history here: **8,816 leaked billable
sessions (2026-06-20 → 2026-07-14)** from tests spawning real engine processes.
`tests/conftest.py` is now fail-closed at three layers, but the gate must still
be **scoped to the tests this effort touches** — a `gate-command:` line per wave
(Foreman 0086) — never a bare full-suite run. Use `-v`, never `-q` (Foreman
refuses `-q` at contract time).

### UI waves assert against RENDERED output

Anchor's dashboard JS is generated inside a Python f-string. A source-level
assertion does not prove what the browser receives, and a brace-escaping mistake
yields syntactically broken script that no Python test would catch. Follow
`tests/test_auth_reprompt_2026_07_28.py`: render `generate_html(...)`, assert on
that string, and run `node --check` over the extracted `<script>` blocks.
