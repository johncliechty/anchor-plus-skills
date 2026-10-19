# 2026-07-28 — General session small-tab open: attach error, dead Retry, self-cleanup

- **id**: `2026-07-28-05-general-session-small-tab-open-attach-er` (friction store)
- **surface**: Anchor project window — general-lane open via **small tab** (live session-bar chip / compact general tile)
- **situation**: Sometimes opening a general session from the small tab cannot find anything, shows an error with a **Retry** button that does not work, then the UI **cleans itself up**.
- **severity**: high (core open path; false live tile + dead-end Retry)
- **status**: Journaled for sleep — **do not fix ad-hoc**; pull with other 2026-07-28 general-session defects
- **provenance**: genuine-user-report + code inspection (`static/project-window.js`, `terminal_session.py`, `anchor_gui` term attach)

---

## What John said (verbatim intent)

> Sometimes when I open a general session using the small tab it can't find anything and comes back with a error. A retry button, but that does not work. Then it cleaned itself up. Not sure why.

### Exact error copy (follow-up 2026-07-28 — **confirmed**)

> Could not attach a live terminal (timeout). The warm view below is still available.Could not attach a live terminal (timeout). The warm view below is still available.

| Fact | Meaning |
|------|---------|
| Reason = **`timeout`** | Not `unknown-session`. Explicit attach_ack failure did **not** fire. |
| **Doubled** sentence (no separator) | Two error overlays / two mounts both hit the same 5s timeout — dual dock+panel or double `_mountTerminal`. |
| Follow-up friction id | `2026-07-28-07-general-attach-error-was-timeout-doubled` |

---

## What the UI is (exact copy path)

This is the Layer-2 **attach-ack** error state in `_mountTerminal` (`static/project-window.js`):

1. Overlay: `connecting to live session…`
2. On failure: **Could not attach a live terminal (`<reason>`). The warm view below is still available.** + **Retry**
3. Reasons: `unknown-session` (attach_ack ok:false) **or** `timeout` (no `replay_complete` within **5s**)

**This incident = timeout path only.** Client sets `ackTimer` 5000ms; `_attachOk()` only runs on `replay_complete`. If neither success nor attach_ack ok:false arrives, UI shows `(timeout)`.

So “can’t find anything” here is **not** proven missing session id — it is **handshake never completed in 5s** (WS open-but-silent, SSE never started, hung pump, auth/upgrade stall, or dual mounts both waiting).
---

## Why Retry does not work (code-backed)

Retry is **not** recovery. It only remounts the same dead id:

```text
_attachError → dispose term/transport → _mountTerminal(same sessionId, same body)
```

It does **not** call:

- `/api/rnd/resume_live` (parked-warm reattach / seeded new session)
- `/api/rnd/term_start` (fresh general)
- any re-lookup of registry status

If the server already returned `unknown-session` (or the PTY was never in this process), **Retry fails identically every time**. That matches John’s report exactly.

---

## Why it then “cleaned itself up”

Defense-in-depth client reconcile (`repopulate` / `loadSessions`):

- On **focus** and every **~15s**, the client re-fetches live sessions from the registry.
- Any id in client `MANAGED` that the registry no longer reports as live is **dropped** and its panel is closed.
- Board refresh follows.

So a broken “live” chip that cannot attach **vanishes** once the server stops listing it (or never listed it after restart/reap), without a durable finished tile + summary for John to reopen. Feels like “it cleaned itself up” with no explanation.

Related: dock path only mounts live xterm when  
`MANAGED[sessionId] && status === 'running'`.  
Statuses like `idle` / `parked-warm` take the **read-only** body even though the human still thinks of the chip as “my session.”

---

## Likely failure modes (reprioritized after confirmed **timeout** + **double message**)

| Priority | Mode | How it produces *this* UX |
|----------|------|---------------------------|
| **1** | **Dual mount (dock + panel)** | Two `_mountTerminal` calls → two 5s timers → two error overlays → **doubled copy** John pasted. Ties 2026-07-25 dual-terminal. |
| **2** | **WS open-but-silent / no control frames** | Client tries WebSocket first; only falls back to SSE on close/error **if no data yet**. A stuck OPEN socket that never sends `replay_complete` burns the full 5s → `(timeout)`. |
| **3** | **Auth / upgrade stall** | WS upgrade or token path hangs instead of fast 401 → no attach_ack ok:false, just timeout. |
| **4** | **Server handshake slow/stuck** | `read_since` or first ctl frames delayed >5s under load (less likely alone; still check). |
| **5** | **unknown-session** (ruled out as *primary* for this paste) | Would show `(unknown-session)`, not `(timeout)`. Still possible on other repros / after cleanup. |
| 6 | Race on brand-new general (400ms open) | May contribute if attach starts before PTY is ready and handshake stalls. |
---

## Code seams for sleep

| Seam | Role |
|------|------|
| `static/project-window.js` `_mountTerminal` / `_attachError` / Retry | Error UI; Retry = remount only |
| `static/project-window.js` `repopulate` + `_RESUME_REPOLL_MS` (15s) | Self-cleanup of stale MANAGED |
| `static/project-window.js` `openEffortDock` `live = MANAGED && status === 'running'` | Non-running chips never get live attach |
| `static/project-window.js` `newGeneral` 400ms open | Fresh general open race |
| `terminal_session.read_since` / `pty_manager` | `unknown-session` source of truth |
| `anchor_gui` `term_ws` / `term_stream2` | attach_ack ok:false + timeout path |
| `session_registry` parked-warm / reaped / boot reconcile | Why ids disappear after restart |

---

## Success criteria (fixed when)

1. **Repro** for small-tab general open when PTY is missing (post-restart) and when session is freshly started — both documented with observed reason (`unknown-session` vs `timeout`).
2. **Retry is not a dead end:** on attach failure, offer real recovery — `resume_live` when parked/warm material exists, or “Start new general” when unknown — never only remount-same-id.
3. **No fake-live tile:** a chip that cannot attach either recovers within one action or becomes an honest finished/warm tile with summary (not silent deletion with no board evidence).
4. **Self-cleanup never erases findability** for a session John just tried to open if a registry/effort record still exists.
5. One interactive surface only for a given live general `session_id` (ties dual-terminal friction).

---

## Cross-links

| Item | Link |
|------|------|
| Friction store | `friction/2026-07-28-05-general-session-small-tab-open-attach-er.json` |
| Dual terminal surfaces | `docs/friction/2026-07-25-dual-terminal-screens.md` |
| Stop/tile/restart | `friction/2026-07-28-02-session-stop-leaves-no-tile-summary-dual` |
| Sleep intake (usage/restart/doctor) | `docs/friction/2026-07-28-SLEEP-INTAKE-usage-restart-doctor.md` — **add Defect 5** when refreshing intake |
| Restart quality | `docs/friction/2026-07-25-restart-handoff-quality.md` |
