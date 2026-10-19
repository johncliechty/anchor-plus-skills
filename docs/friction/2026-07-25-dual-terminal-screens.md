# 2026-07-25 — Dual terminal screens in one general session (laptop)

- **id**: 2026-07-25-dual-terminal-screens
- **surface**: Anchor project window — general-lane live session terminal (laptop browser)
- **situation**: John sees **two screens in one terminal** — one in the background and one on top — for a general session on his laptop. Looks like a stacked double UI, not a single clean session surface.
- **context**: Family Trusts / general lane, live session on laptop (2026-07-25). Same day as restart-quality + dictation friction. User explicitly asked this to be journaled as something to fix.
- **outcome**: friction
- **severity**: high (core UX; confuses “where am I typing / what is live”; likely related to status spam and focus/dictation failures)
- **provenance**: genuine-user-report + code inspection of `static/project-window.js` / `project-window.css`

---

## What John sees

- Opening or using a **general** session in the Anchor project window shows **two terminal-like layers**:
  - a screen/content layer in the **background**
  - another on **top**
- Feels like double chrome / double session, not one pane.
- Co-occurs with earlier reports of status-ish “wave / budget / state running” noise and poor resume material.

## Root cause candidates (code-backed — pick one in fix with repro)

### A. Two terminal **surfaces** still coexist (most likely product structure)

After **v12 Wave 10 (Layout-D bottom dock)**, the cockpit has **two live terminal homes**:

| Surface | DOM / entry | Used for |
|---------|-------------|----------|
| **Bottom dock** | `#effortDock` / `openEffortDock` / `#dockTermHost` | Effort tiles with `data-effort-id`; comment SC6: bare **general** also opens in dock |
| **Inline panel stack** | `#panelStack` / `openPanel` / `.panel .tpane .term-host` | Live-session bar chips, grass, boneyard, chain-nav, and **`newTermSession` → always `openPanel`** |

Evidence in `static/project-window.js`:

- Header comment (legacy): panel stack is “the” terminal surface — **stale vs W10 dock**.
- W10 comment: dock is for effort tiles; **panel stack “stays”** for chips/grass/boneyard/chain.
- `newTermSession` (new general terminal): ends with **`openPanel(sid)` only** — never dock.
- `laneTileClick`: if tile has `data-effort-id` → **dock**; else → **panel**.
- General sessions can therefore open via **different surfaces depending on path** (New terminal chip vs tile click vs resume).

**Incomplete mutual exclusion:**

- `openPanel(sessionId)` **does** redirect to dock **if** `DOCK.session_id === sessionId`.
- `openEffortDock` **does not** tear down / close an existing **inline panel** for the same session.
- So: open via panel first (new general), then open/bind dock (tile / resume / parent workbench), and you can get **two UIs for one session** — one behind/above the other depending on scroll/z-order/maximize.

Also: continue/resume paths mint a **new** session id and try to close the source panel, but dock + panel for **related** source/new ids can still stack.

### B. Two **xterm** instances / transports on one session

`_mountTerminal(sessionId, body, rec)`:

- Always creates `new Terminal(...)` and `term.open(body)`.
- Does **not** globally enforce “one mount per session_id”.
- Dock and panel each keep their own `term` + `transport` on `DOCK` vs `PANELS[sessionId]`.
- If both surfaces mount the same live session, **two WebSocket/SSE consumers** attach and **two canvases** render the same PTY → classic “ghost terminal behind / on top.”

Retry path on attach error disposes `w.term` then calls `_mountTerminal` again on the same `body` without fully guaranteeing a single clean host (risk of leftover DOM + second open).

### C. Intentional Layer-1 warm view **under** live attach layer

Telemetry-resume design:

- Layer-1 (`.layer1`) warm narration sits in the terminal chrome.
- Layer-2 attach overlay (`.term-attach`, `z-index: 5`, semi-opaque) sits over the xterm until `replay_complete`.
- On attach error, copy says **“The warm view below is still available.”**

That is **by design two layers**, but a stuck attach overlay, failed detach, or warm block left under a live xterm can look exactly like “background screen + top screen” even when only one PTY is intended.

CSS: `.term-attach { position:absolute; inset:0; … z-index:5; background: rgba(5,7,12,.86) }` over `.term-host { position:relative }`.

### D. Parent dashboard + project window (secondary)

`openEffortDock` tries to open parent `#dashboard-workbench-details`. If the project window is also embedded/framed, a user can perceive **dashboard chrome + project terminal** as two stacked screens. Less specific to “inside this terminal” but worth ruling out on laptop.

---

## Likely interaction with other 2026-07-25 friction

| Other journal | Link |
|---------------|------|
| Restart / summary quality | Dual surfaces confuse which session is authoritative for autosave/transcript |
| Win+H dictation flash-dismiss | Focus lands on wrong layer / non-caret surface |
| iPad dictation blow-up | Dual input targets or paste into wrong host |
| Status “wave/budget/running” spam | Dock metrics + dual consumers replaying status chrome into both panes |

---

## Success criteria (fixed when)

1. **Exactly one** interactive terminal surface is visible and focusable for a given live `session_id` (general included).
2. Opening general via **New session**, **tile click**, **live chip**, **Continue / Resume live**, or **engine switch** never leaves a second terminal chrome in the background.
3. Switching surface (if dock vs panel both remain for non-general cases) **tears down** the other mount (dispose xterm + close transport) for that session.
4. Layer-1 warm view and Layer-2 attach overlay never permanently stack as two full “screens”; attach either completes (overlay gone) or fails cleanly without a ghost live pane.
5. Laptop repro: open Family Trusts (or any) general session → one pane only; type/dictate into that one surface.

---

## Suggested fix direction (for sleep — not the only design)

1. **Single-owner rule:** `session_id → one of {dock, panel}`; opening one **closes** the other for that id.
2. **`openEffortDock`:** if `PANELS[sessionId]` exists, `_closePanel(sessionId)` (DOM/transport only) before dock mount.
3. **`newTermSession('general')`:** either always dock (match SC6) **or** always panel — **one** product rule; don’t split by entry path.
4. **`_mountTerminal`:** refuse or remount-in-place if `sessionId` already has a live term elsewhere; dispose previous.
5. **Attach handshake:** on success remove overlay; on error don’t leave dual full-height UIs; don’t remount without clearing host.
6. Add a UI healthcheck or dev assert: count `.xterm` nodes per session_id ≤ 1.

---

## Evidence paths

- `C:\dev\Anchor\static\project-window.js`
  - `laneTileClick` / `openPanel` / `openEffortDock` / `newTermSession`
  - `_mountTerminal` / `_mountLayer1Narration` / `_resumeLive` / `continueSession`
  - DOCK vs PANELS dual records
- `C:\dev\Anchor\static\project-window.css` — `.layer1`, `.term-attach`, `.dock`, `.panel`
- `C:\dev\Anchor\static\project-window.html` — `#panelStack` + dock chrome

## Related sleep intake

Also listed in:

`docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md` (updated cross-link)

---

## Reproduction sketch

1. Laptop, Anchor project window (e.g. Family Trusts).
2. Start or open a **general** live session (New terminal / continue / resume after eviction).
3. Also click the session tile and/or live chip if present.
4. Observe: two terminal layers (background + foreground), not a single pane.
5. Optional: note focus target for typing / Win+H.
