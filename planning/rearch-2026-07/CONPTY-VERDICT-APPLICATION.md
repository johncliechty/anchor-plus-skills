# ConPTY verdict — W17 application

The W3 ConPTY-across-processes spike verdict (`SPIKE-CONPTY-VERDICT.json`), APPLIED by W17 (Wave 19).
Rendered mechanically by `tools/conpty_verdict.py` — never hand-edited.

- **Overall verdict:** YES
- **Applied branch:** adoption
- **Ran legs:** real, stub

## Applied branch: PTY ADOPTION (verdict YES)

Both recorded legs (real, stub) answered **YES** against the pre-written W3
acceptance questions (latency bound, re-attach after client death, complexity
budget). The across-process PTY-ownership architecture — owner-side PTY + byte
proxying over loopback IPC, the same shape the W15/W16 supervisor already uses
for jobs — is economically feasible.

Per the plan's fork, W17 applies the **YES** branch: **the PTY-adoption
follow-on wave is SCHEDULED inside this phase's plan** (below). No North-Star
narrowing amendment is required or recorded — a YES verdict narrows nothing; the
jobs half of C4 (non-negotiable) is unaffected and already lands in W15/W16.

Until the adoption follow-on ships, the pre-designed graceful drain
(`tools/pre_restart_drain.py`) remains the **safety net**: any dashboard restart
that lands before PTY adoption parks every live PTY WARM (close_session park +
capture_session_docs + warm-resume seed), so a restart costs a warm reconnect,
never dead context. The drain is retained, not deleted — it is the belt to
adoption's braces.

### Scheduled follow-on wave — PTY Adoption (Foreman-ready scope)

> Scheduled, NOT yet a plan ordinal. The frozen plan is 20 wave ordinals
> (W1–W18 with W6a/b/c); this follow-on is a checked-in scoped wave the way
> Crucible/Foreman schedule downstream work — it is taken up as its own effort
> after this phase closes (W18), so the C4 jobs half is not blocked on it.

**Intent:** Move PTY-session ownership behind the ANCHOR_SUPERVISOR seam using
the spike-proven owner-side-PTY + loopback-byte-proxy architecture, so
`nssm restart anchor` leaves live terminals attached to the supervisor-owned
PTY — the same restart survival jobs already have.

**Deliverables (scoped):**
- Owner-side PTY in the supervisor process: `pty_manager` sessions owned by the
  supervisor, bytes proxied over the existing loopback token-authed IPC (the
  W16 transport), re-using the spike's ≤400-significant-line harness shape.
- The dashboard-side client: `term_ws` / `term_stream2` bridge the browser
  socket to the supervisor byte-proxy instead of a dashboard-local PTY; auth
  unchanged (401-before-101 preserved).
- Re-attach on restart: a new dashboard connection re-attaches with full replay
  of prior output + live I/O, the owner-held PTY having survived (the spike's
  Q-REATTACH, now on the real service).
- Degraded mode: supervisor down → PTYs fall back to dashboard-owned + the
  pre-restart drain (unchanged safety net); named in the hybrid-state matrix.
- Live probe: a terminal open, `nssm restart anchor`, and a warm re-attach with
  the PTY still live — the PTY analogue of the C4 jobs runbook.

**Depends on:** W16 (external supervisor service + loopback IPC) — landed.
**Not blocking:** W18 closure; the jobs half of C4 stands alone.
