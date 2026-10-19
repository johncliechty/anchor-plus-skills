# EARLY-SLICE-PARTIAL — after W10

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W10 — Phase 3: Open + Run control honesty

## This slice is PARTIAL

**Do not mistake this slice for the North Star.**

After W10 the build reaches **one honest user-facing path** for Open and Run —
dead-control contract, named cannot-open / cannot-run states, surface-native
failure-state table, and rendered-string end-to-end traces. That path is
**explicitly labelled PARTIAL**.

The North Star still requires: open, run, stop, and restart real Anchor work
(including Doctor diagnose and session attach) without a dead control, a silent
zero, a mislabelled empty, or a preview that dumps raw binary — plus honest
usage, cost, cadence, and projects collapse. **None of that is claimed here.**

## What is honest after W10

* **Open control** — live button only when the inventory authorizes live PRESENT
  on a non-STALE row; otherwise a named cannot-open (or unknown when the project
  store is unreadable) with **no** dead button.
* **Run control** — same contract with cannot-run reasons; ABSENT inventory
  yields no Run button at all.
* **unknown ≠ empty** on the project list (store unreadable vs legitimately
  empty).
* **Shared dead-control primitive** (`anchor/ui/dead_control.py`) for attach
  (W11) and restart (W17) to import.
* **Schema-valid e2e traces** at `proof_level: rendered-string` for open and run
  (structural only — not a human-driven user path; S1 / W22 alone may claim that).

## What is still unbuilt

| Area | Status after W10 | Owning wave(s) |
|------|------------------|----------------|
| Session attach + Retry | unbuilt | W11 |
| Usage / time tiles | unbuilt | W12 |
| Cost surfaces | unbuilt | W13 |
| Doctor diagnose + banner | unbuilt | W14 |
| Per-engine Doctor (Claude/Gemini/Grok) | unbuilt | W15 |
| Stop summary | unbuilt | W16 |
| Restart controls | unbuilt | W17 |
| File preview (Office/PDF) | unbuilt | W18 |
| Projects collapsed-by-default | unbuilt | W19 |
| Cadence telemetry / as_of / stale | unbuilt | W20 |
| Close-out audits + traceability | unbuilt | W21 |
| Live North Star validation with John | not run | S1 (W22) |

## Status language that is forbidden here

* Claiming the North Star is met, or that open/run criteria are **MET**
  (only S1 may stamp MET; W10 may at most support CANDIDATE-MET structure later).
* Calling this slice "end-to-end" in the human-path sense. Build traces are
  **rendered-string** structural proof only.
* Implying usage, cost, Doctor, stop/restart, preview, or cadence work because
  Open/Run honesty exists.

## One-line summary

**PARTIAL:** Open and Run are honest (work or named cannot-*, never a dead
button). Everything else the North Star names is still unbuilt.
