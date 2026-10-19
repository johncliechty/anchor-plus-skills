# Spike verdict — ConPTY across processes (rearch W3)

Recorded against the PRE-WRITTEN acceptance questions (frozen with W3, before any run). Architecture under test: owner-side PTY + byte proxying over loopback IPC — the supervisor shape (D2). Refreshed mechanically by `tools/conpty_spike.py record_verdict`; never hand-edited. Consumed by W17 (PTY adoption follow-on, or the pre-designed drain + honestly-recorded narrowing).

## Acceptance questions (pre-written)

- **Q-LATENCY** — Is the median echo round-trip through the cross-process hop <= 150 ms (median of 5 rounds)?
- **Q-REATTACH** — After the first client detaches (simulating a dashboard restart), does a new connection re-attach with full replay of prior output AND working live I/O, the owner-held PTY having survived the client's death?
- **Q-COMPLEXITY** — Does the whole across-process ownership harness fit within 400 significant lines?

## Legs

### stub — stub PTY (deterministic; architecture + protocol + IPC hop)

**Verdict: YES**

- Q-LATENCY: **PASS** — median 0.1 ms over 5 rounds (bound 150 ms)
- Q-REATTACH: **PASS** — owner survived client detach; re-attach replayed prior output and live echo worked
- Q-COMPLEXITY: **PASS** — 382 significant lines (budget 400)

### real — real ConPTY (pywinpty cmd.exe)

**Verdict: YES**

- Q-LATENCY: **PASS** — median 10.8 ms over 5 rounds (bound 150 ms)
- Q-REATTACH: **PASS** — owner survived client detach; re-attach replayed prior output and live echo worked
- Q-COMPLEXITY: **PASS** — 382 significant lines (budget 400)

## Reading the verdict

- The **stub** leg proves the across-process OWNERSHIP architecture (owner survives client death; re-attach replays; latency of the IPC hop) deterministically.
- The **real** leg proves live ConPTY behaves the same under an owner that is not the interactive session.
- A **NO** on either leg routes W17 to the pre-designed drain (`tools/pre_restart_drain.py`) + the North-Star-amendment narrowing — PTYs stay dashboard-owned; the jobs half of C4 is unaffected (non-negotiable).
