# Sleep intake — Anchor restart quality + terminal dictation + dual screens (2026-07-25)

**Audience:** Anchor sleep / improvement session (product-wide, all projects)  
**Reporter:** John (live use friction, Family Trusts general lane + multi-device)  
**Priority:** High — blocks reliable stop/restart, clean terminal chrome, and voice input on the primary UX surface  
**Status:** Journaled for sleep — not yet fixed

This file is the **single intake** for a sleep run. Three product defects; fix independently where possible. **Defect 3 (dual screens)** is code-inspected and may explain Defect 2 focus issues.

---

## Defect 1 — Stop/restart material is not human-usable

### What John sees
- Session tiles / continue-in-live-session do **not** show a clear human-facing summary of what the session was for, what got done, what is open, and what to do next.
- On restart (including after worktree eviction), the engine is told to read `RESTART.md` + transcripts, then **digs around** for many turns before it can be useful.
- Live proof (2026-07-25 Family Trusts / general lane, session family `56d08b64…` / resume chain):
  - `RESTART.md` only listed session id, lane, engine, first seed line, and a doc list — **no goal, status, decisions, or next step**.
  - Persisted `*-transcript.md` was **corrupted / repeated garbage** (terminal UI noise + stuck dictation loops), not a readable conversation.
  - Cached general-lane `summary.md` examples on the Anchor project board are near-empty (“transcript name”, “no grounded claims”) — so the **board display** also fails John’s “easy to understand” bar.

### Root cause (code-level, verified on disk)
1. **`terminal_session._write_restart_seed`** (autosave path) builds a **mechanical** RESTART only:
   - metadata + seed first line + produced-doc bullets
   - **explicitly no model call and no human status section**
2. **`summarizer.py`** pipeline for general-lane sessions often has only a raw transcript as the seed → grounding fails or produces title-only summaries → board shows useless tiles.
3. Resume seed after worktree eviction is effectively: *“Here is the context… (resumed from persisted docs)”* + list of files → agent re-derives state from noisy transcripts instead of a durable handoff.

### Success criteria (what “fixed” means for John)
On **every** project, every lane (especially **general**):

1. **Board tile / session open** shows a short plain-English summary a human can absorb in ~20 seconds:
   - What this session is for (goal)
   - Current status (done / blocked / waiting on human)
   - Key decisions locked
   - Open next action (one line)
   - Links to the few real deliverables (not a dump of every autosaved transcript)
2. **`RESTART.md` (or successor)** is a **handoff brief**, not a file index. Minimum sections:
   - Goal
   - Status
   - Done (bullets)
   - Open / blocked
   - Next action
   - Deliverable paths
   - “Do not re-litigate” locks
3. **Restart agent** can orient in **one read** of that brief and continue without multi-file archaeology **unless** the brief points at a specific doc for detail.
4. Transcripts remain for audit, but **must not be the primary resume substrate** when they are UI-corrupted or voice-loop polluted.
5. Works after **worktree eviction** (docs on MAIN must carry the handoff, not only the live PTY).

### Suggested fix shape (for sleep to design/implement — not prescribed as the only design)
- Autosave / suspend / kill: write or refresh a **structured handoff** (`RESTART.md` or `HANDOFF.md`) from:
  - last good agent “status” block if present, else
  - a cheap periodic / on-suspend summary job (job_runner), else
  - deterministic extraction from produced non-transcript docs
- General-lane summarizer: **prefer non-transcript member docs**; treat raw PTY transcript as last-resort seed; never ship a summary that is only the transcript filename.
- Resume prompt: *“Read RESTART/HANDOFF only first; dig into transcripts only if HANDOFF is missing or contradicts.”* (partially already in orientation intent — not delivered by content quality.)
- Optional: strip / gate terminal ANSI / spinner noise from transcript snapshots so even fallback reads are usable.

### Reproduction notes
- Project: any Anchor project with general-lane sessions; hard case = Family Trusts + multi-restart chain.
- Trigger: session autosave while running → kill/evict worktree → “Continue in a live session”.
- Observe: RESTART thin; agent rereads many transcripts; John gets no scannable summary on the board.

### Evidence paths
- `C:\dev\Anchor\terminal_session.py` → `_write_restart_seed`, `autosave_session`
- `C:\dev\Anchor\summarizer.py` → general-lane seed/grounding
- `C:\dev\Anchor\orientation.py` / `fix_orientation.py` → intended “read RESTART first”
- Example thin RESTART: session worktree `general/RESTART.md` (mechanical template)
- Example empty/near-empty summaries:  
  `C:\dev\Anchor\.anchor\projects\f69f6d66171f4dbd95c8c45db6846d97\general\summaries\*\summary.md`

---

## Defect 2 — Dictation into Anchor terminal (laptop + iPad)

### 2a — Windows laptop: Win+H dies immediately
**Device:** John’s laptop (Windows)  
**Action:** Focus Anchor session terminal → press **Windows + H** (Windows Voice Typing)  
**Observed:** Mic UI appears, then **disappears**; dictation never stays active / never produces usable text into the session.

**Likely product surface:** focus / PTY / ConPTY / embedded terminal / window ownership — voice typing often requires a stable editable text focus; Anchor’s terminal may steal focus, not expose a real text caret, or lose the input target when the overlay opens.

**Success criteria:**
- Win+H (or an in-app mic control, if preferred) stays open and streams text into the **session input** the user is typing into.
- If OS voice typing cannot target the PTY reliably, Anchor must either:
  - provide a **dictation compose box** (plain text field → insert into terminal), or
  - document a supported path and make it one-click from the session UI.
- No silent failure (mic flash then gone without explanation).

### 2b — iPad remote session: dictation explosion (repeat-all loop)
**Device:** iPad driving an Anchor project session (remote / tablet path)  
**Observed:** User dictates a sentence; the system (or composition path) **re-pastes everything said so far plus the new sentence** on each utterance → text **blows up** (exponential / cumulative repetition). Live proof polluted Family Trusts general transcripts (hundreds of repeated “three clear questions… PDF…” loops).

**Likely causes to investigate (sleep should pick the real one with instrumentation):**
1. **IME / composition commit** firing full buffer each time instead of delta
2. **Paste-not-submit / seed re-injection** re-applying prior input
3. **Remote keyboard / WebView** sending cumulative text as new keystrokes
4. **PTY echo + client re-send** feedback loop
5. Interaction with **autosave transcript snapshot** is less likely for live blow-up; this is an **input path** bug first

**Success criteria:**
- Each dictation utterance appends **only the new words** once.
- No full-history reinsertion.
- Long voice sessions stay linear and readable.
- If tablet path is degraded vs desktop, UI must warn rather than corrupt the session.

### Cross-cutting for dictation
- Add a **compose / dictation buffer** mode for sessions (especially tablet + OS voice typing) that inserts on explicit Send, so IME composition never hits the raw PTY character-by-character path.
- Log input source (keyboard vs paste vs IME composition vs remote) for one debug build to prove the loop.
- Never let a runaway input storm fill the primary resume transcript without size/repeat guards (secondary safety).

### Reproduction notes
- Laptop: open live general session → click input → Win+H → observe mic flash-dismiss.
- iPad: open same class of session → dictate 3–4 short sentences → observe cumulative re-paste.

---

## Defect 3 — Two screens in one general terminal (laptop)

**Observed (John, laptop):** In an Anchor **general** session, the terminal area shows **two screens** — one in the background and one on top. Feels stacked / double, not a single session pane.

**Code-backed likely cause (inspect, then prove with repro):**

After Layout-D (v12 W10), the project window has **two terminal homes**:

1. **Bottom dock** (`openEffortDock` / `#dockTermHost`) — effort tiles; SC6 also routes bare general here  
2. **Inline panel stack** (`openPanel` / `#panelStack`) — live chips, grass, etc.; **`newTermSession` always opens panel**

Mutual exclusion is **one-way only**: `openPanel` defers to dock if dock already owns that `session_id`, but **`openEffortDock` does not close an existing inline panel** for the same session. `_mountTerminal` can therefore create **two xterm + two transports** on one live session → ghost pane behind / on top.

Secondary stack: Layer-1 warm view (`.layer1`) + Layer-2 attach overlay (`.term-attach`) intentionally layer; a stuck attach or warm block under live xterm also looks like dual screens.

**Detail journal:** `docs/friction/2026-07-25-dual-terminal-screens.md`

**Success:** Exactly one interactive terminal surface per live `session_id`; opening general by any path never leaves a second chrome behind.

---

## Sleep session acceptance (ship when true)

| # | Check |
|---|--------|
| 1 | New or resumed general session shows a human 20-second summary (goal/status/next) on board or first paint |
| 2 | After worktree eviction, continue-session orients from HANDOFF/RESTART without multi-transcript dig |
| 3 | Win+H or in-app dictation works on Windows laptop into session input |
| 4 | iPad dictation does not re-inject full prior text each sentence |
| 5 | **General (and any) live session shows exactly one terminal surface — no background + foreground double screen** |
| 6 | Friction journals remain; add fix journals with outcome=worked when closed |

---

## Do not conflate
- This is **Anchor product** friction (all projects), not Family Trusts legal content.
- Family Trusts deliverables for Stanford/siblings are a **separate** track and already have a built pack under `C:\dev\Family Trusts\reviews\2026-07-24\crucible-lite-holdco-trust-pack\`.

## Provenance
- Captured 2026-07-25 in a resumed general-lane session after worktree eviction.
- John explicitly requested journaling so a **sleep session on Anchor** can improve restart material, dictation, and dual-terminal chrome.
