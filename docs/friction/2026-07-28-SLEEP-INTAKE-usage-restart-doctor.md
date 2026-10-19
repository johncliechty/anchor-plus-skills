# Sleep intake — Usage, stop/restart, Doctor, general attach, High Seat, Projects folders (2026-07-28)

**Audience:** Anchor sleep / improvement cycle (product-wide)  
**Reporter:** John (live general session on Puter; dashboard resume chain)  
**Priority:** High — blocks trust in spend, reliable stop/continue, self-heal hygiene, and basic general open  
**Status:** Journaled for sleep — **do not fix in ad-hoc sessions**; pull this intake when the Anchor sleep cycle runs  
**Machine:** PUTER · project lane: general / `__dashboard__` · reporter session family: `402ac459…`

Friction store records (verbatim capture path; open, severity `problem`):

| # | Friction id | Topic |
|---|-------------|--------|
| 1 | `2026-07-28-01-token-usage-time-dollars-still-not-visib` | Tokens / time / $ not visible |
| 2 | `2026-07-28-02-session-stop-leaves-no-tile-summary-dual` | Stop tile + dual restart + auto-continue |
| 3 | `2026-07-28-03-anchor-doctor-diagnose-must-run-and-fix` | Doctor diagnose+fix; all model seats |
| 4 | `2026-07-28-04-doctor-diagnose-session-not-tied-to-heal` | Doctor session unbound from health banner content |
| 5 | `2026-07-28-05-general-session-small-tab-open-attach-er` | Small-tab general open: attach error, dead Retry, self-cleanup |
| 5b | `2026-07-28-07-general-attach-error-was-timeout-doubled` | **Confirmed** UI: `(timeout)` doubled — not unknown-session |
| 6 | `2026-07-28-06-projects-tab-opens-with-all-project-fold` | Projects tab: all R&D folders expanded by default |
| 7 | `2026-07-28-08-high-seat-token-re-prompt-saved-then-rel` | High Seat: token re-prompt (saved) → reload → lost input |

Also refresh/supersede related open work:

- `docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md` — Defect 1 (restart material) is **still live**; this intake **adds** stop-tile, dual buttons, auto-send.
- `friction/2026-07-26-02-usage-numbers-read-zero.json` — was **resolved** (`121b479`); treat **2026-07-28-01** as **regression / incomplete product surface**.
- `docs/friction/2026-07-25-dual-terminal-screens.md` — dual dock/panel surfaces; **Defect 5** is the attach-fail / Retry dead-end sibling.
- `docs/friction/2026-07-28-general-small-tab-attach-error.md` — full investigation notes for Defect 5.
- `docs/friction/2026-07-28-projects-folders-default-expanded.md` — Defect 6 (small UX polish).
- `docs/friction/2026-07-28-high-seat-token-reload-loses-input.md` — Defect 7 (High Seat unusable).

---

## Defect 1 — Token usage, time, and dollars not visible

### What John said (verbatim intent)
> I am not seeing token usage, time dollars spent … that was supposed to be fixed.

### What “fixed” already claimed
Prior friction `2026-07-26-02-usage-numbers-read-zero` resolved with note that general-lane rollup worked in backend/index. **John still does not see** spend in the product UI he actually uses.

### Success criteria
1. Dashboard / workbench / session chrome show **tokens**, **elapsed time**, and **dollars** (or an explicit **unmeasured** state with reason — e.g. Grok sidecar gap — never a silent zero that reads as free).
2. Correct for **Claude, Gemini (agy), Grok** seats and for `run-cost` / session rollups after stop/resume.
3. Human can answer “what did this session cost?” without opening logs or JSON pointers.

### Sleep notes (investigation seams)
- `usage_ledger.py`, `usage_capture.py`, `rollup_honesty.py`, effort/run-cost pointers under `.anchor/projects/*/…/efforts/run-cost-*`
- UI: project window tiles, workbench, any cost chip that still binds only to Claude-shaped sidecars
- Live proof today: `run-cost-402ac459…` recorded `usage_state: unmeasured` / `grok-no-claude-sidecar` and `total_cost_usd: 0.0` — UI must not present that as “working free”

---

## Defect 2 — Session stop/restart is not great (tile, dual buttons, auto-continue)

### What John said (verbatim intent)
- Stopping a session did **not** put the tile up with a summary of what had been worked on.
- Agent could dig and recover *this* thread, but an **earlier** session would likely not restart properly from the same path.
- On stop: need **session-specific ID**, **summary**, and **restart file/material**.
- When the session window starts back up: **only one restart button** (today there are **two**).
- Restart should be **automatic** — not load a prompt and wait for the human to hit Enter; the restart path should continue as part of restart.
- Other idle sessions: leave alone for now; John will deal later.

### Live proof (this resume)
- `general/RESTART.md` was mechanical / pointed at a **different** session id than the resume seed’s docs.
- `general/*-transcript.md` files are often **TUI-corrupted noise**, not readable handoffs.
- Resume seed listed files and asked the agent to re-orient — multi-turn archaeology before usefulness.
- UI still shows **two** continue/restart affordances.

### Success criteria
1. **On stop/close/park:** write immediately to MAIN (survives worktree eviction):
   - stable **session-specific ID**
   - plain-English **summary** (goal · status · done · open · next)
   - durable **RESTART/HANDOFF** material (not a file index only)
2. **Board/workbench tile** shows that summary within seconds so John can identify the session without opening it.
3. Resume surface has **exactly one** restart/continue control.
4. Restart **starts the engine and sends the resume seed** (agent begins working; no “hit Enter to continue”).
5. Older sessions remain **findable and restartable** by ID + tile summary, not only “latest dig luck.”

### Sleep notes (investigation seams)
- `terminal_session.py` — `_write_restart_seed`, `autosave_session`, `close_session` / park path
- `summarizer.py` — general-lane grounding; must prefer non-transcript docs; never title-only / filename-only tiles
- `orientation.py` / resume seed builder — auto-submit path for engine stdin/argv
- `static/project-window.js` — dual restart buttons; dock vs panel dual surfaces (also 2026-07-25 dual-terminal friction)
- Prior intake: `docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md` Defect 1

---

## Defect 3 — Anchor Doctor: diagnose must run + fix hygiene; all model seats

### What John said (verbatim intent)
> The Anchor Doctor is supposed to actually run the diagnosis when you click on diagnosis and it should both diagnose as well as fix the issues related to the Anchor hygiene. Also, the different options, grok, gemini and claude should all work (does not seem like they are working all).

### Success criteria
1. **Click Diagnose** (Doctor page, banner `diagnose=1`, health-check deep links) **runs diagnosis** — not shell paint + seed-only / plan-only / idle terminal.
2. Doctor **diagnoses and fixes** Anchor hygiene issues (or one-click Apply Fix with clear before/after), not advice-only that leaves the tree dirty.
3. **Claude, Gemini (agy), and Grok** each can start and complete Doctor diagnose (and fix where applicable). No dead family in the engine picker.
4. Failures are **honest in UI** (auth, missing binary, driver, quota) — never a no-op click.

### Sleep notes (investigation seams)
- `doctor.py`, `anchor_healthcheck.py`, `report_viewer.py`
- `anchor_gui.py` — W9 banner diagnose plans, async diagnose start, Doctor navigation (`startWhen`, seed-only paths)
- Family seating: UNIVERSAL SEATING LAW — `~/.anchor/model_prefs.json` / `settings.json`; Grok = `grok.exe -p` / `grok-cli`, Gemini = `agy` / agy-dispatch, Claude = `claude.exe`
- Do not “fix” by hardcoding one family; all three seats must work

---

## Defect 3b — Doctor diagnose session not bound to the health warning banner

**Friction id:** `2026-07-28-04-doctor-diagnose-session-not-tied-to-heal`  
**Related:** Defect 3 (`2026-07-28-03-…`) — same Doctor surface; this is the **banner context handoff** specifically.

### What John said (verbatim intent)
> The Doctor diagnosis session was not tied to the health warning banner (it did not know what was in the banner). That should not be the case.

### What went wrong (product requirement)
Clicking into Doctor **from** a health warning must carry the **banner’s issue payload** into the session. A Doctor that opens generic / empty / unaware of the warning the human just saw is a failed handoff — even if a terminal starts.

### Success criteria
1. Banner click / `diagnose=1` deep-link seeds Doctor with the **full issue context**: issue id, title/body, severity, `lastError`, suggested checks, report date/path, and any other facts shown on the banner.
2. Doctor first-turn / shell text **names that specific banner issue** and its facts — not a blank “open Doctor” shell.
3. Diagnose (and fix, per Defect 3) **focuses on that issue** as primary work.
4. If binding fails, UI shows an **honest error** — never a silent generic Doctor that looks fine but is uninformed.

### Sleep notes (investigation seams)
- `anchor_gui.py` — `_w9_build_doctor_navigation_from_banner`, `_w9_build_banner_diagnose_plan`, `_w9_attempt_async_banner_diagnose_start`, banner HTML `data-diagnose` / `issueId` query params
- Confirm seed text actually includes issue fields, not only `diagnose=1` + empty `issueId`
- Session start path must pass seed into engine argv/stdin **and** auto-send (same class of bug as Defect 2 auto-continue)
- Tests: banner → Doctor must assert seed contains issue id + lastError (or equivalent payload), not merely that a session record exists

---

## Defect 5 — General session small-tab open: attach error, Retry dead, self-cleanup

**Friction id:** `2026-07-28-05-general-session-small-tab-open-attach-er`  
**Write-up:** `docs/friction/2026-07-28-general-small-tab-attach-error.md`  
**Related:** Defect 2 (stop/restart findability); dual-terminal 2026-07-25 (two surfaces / Retry remount)

### What John said (verbatim intent)
> Sometimes when I open a general session using the small tab it can't find anything and comes back with a error. A retry button, but that does not work. Then it cleaned itself up. Not sure why.

### Exact error (follow-up, confirmed)
> Could not attach a live terminal (timeout). The warm view below is still available.Could not attach a live terminal (timeout). The warm view below is still available.

**Reason = `timeout` (not unknown-session).** Message **doubled** with no separator → two mounts both hit the 5s attach handshake limit. Follow-up id: `2026-07-28-07-general-attach-error-was-timeout-doubled`.

### What is going on (code-backed, not a mystery)
1. **Error UI** = `_mountTerminal` 5s ackTimer: no `replay_complete` → *Could not attach a live terminal (**timeout**)* + **Retry**.
2. **Not** attach_ack ok:false / unknown-session for this paste — handshake simply never completed in 5s.
3. **Doubled text** ⇒ dual dock+panel (or double mount) both timing out (ties dual-terminal friction).
4. **Retry is a dead end:** remounts same id only — can re-timeout the same way.
5. **Self-cleanup** = client `repopulate` ~15s drops stale MANAGED chips.

Sleep priority: why no `replay_complete` in 5s (WS silent / SSE not started / auth stall) + kill dual mount + real Retry.
### Success criteria
1. Small-tab open of general either **attaches live**, or offers **real recovery** (resume_live / start new) — never remount-same-id-only Retry.
2. No **fake-live** chip that cannot attach; cleanup leaves findable warm/finished evidence when a record still exists.
3. Post-restart and freshly-started general paths both covered by repro + fix.
4. Exactly one interactive terminal surface for a live general session (with dual-terminal criteria).

### Sleep notes (investigation seams)
- `static/project-window.js` — `_mountTerminal`, `_attachError`/Retry, `repopulate` 15s, `openEffortDock` (`status === 'running'` only), `newGeneral` 400ms open
- `terminal_session.read_since` / pty map → `unknown-session`
- `anchor_gui` term_ws / term_stream2 attach_ack
- `session_registry` boot reconcile / parked-warm / reaped

---

## Defect 6 — Projects tab: all folders open by default (small)

**Friction id:** `2026-07-28-06-projects-tab-opens-with-all-project-fold`  
**Write-up:** `docs/friction/2026-07-28-projects-folders-default-expanded.md`

### What John said (verbatim intent)
> I do not want to have all of the project folders open when we open the projects tab on the main anchor page. That should not be the case.

### What happens
R&D folders on the main dashboard Projects tile render **expanded** (all project rows). Collapse is opt-in via `localStorage` (`anchor_rnd_folder_collapsed`). Fresh / never-toggled → everything open.

### Success criteria
1. Default: folders **collapsed** (headers + counts only).
2. Expand per folder; never auto-open-all on tab open.
3. Persistence OK if it does not reintroduce default-open-all; no expand-flash on paint.

### Sleep notes
- `anchor_gui.py` `_render_group_folders` (always expanded HTML) + `rndFolderInit` / `rndToggleFolder` / `RND_FOLDER_LS`
- Flip default to collapsed; store expanded set (or invert LS semantics with a version bump)

---

## Defect 7 — High Seat: token re-prompt (saved) → reload → lost input

**Friction id:** `2026-07-28-08-high-seat-token-re-prompt-saved-then-rel`  
**Write-up:** `docs/friction/2026-07-28-high-seat-token-reload-loses-input.md`

### What John said (verbatim intent)
> I just tried to give it [High Seat] input and it came back with asking me for the Anchor token, which I gave it (actually it was still saved--that may be a problem). Then it restarted anchor and lost/forgot what I had given it. So, we are not able to use the High Seat yet. I will take a look at the project level steward.

### What is going on (code-backed)
1. High Seat act hits **401** → global `fetch` wrapper calls `setAnchorToken()` (prompt **pre-filled** from `localStorage` — matches “still saved”).
2. On accept → **`location.reload()`** (likely what felt like “restarted Anchor,” not necessarily NSSM).
3. High Seat dialogue is **ephemeral by design** → typed input gone; surface unusable mid-conversation.

### Success criteria
1. Valid saved token → no token prompt on High Seat speak.
2. Real 401 → re-auth **without** wiping saybox / pending act.
3. One full speak→receipt without page reload.
4. Project-level steward is **out of scope** here (John handling separately).

### Sleep notes
- `static/high-seat.js` `_ecgHsPost` / speak / ephemeral policy
- `anchor_gui.py` 401→`setAnchorToken`→`location.reload()`
- `route_table` AUTH_TOKEN on `/api/ecgberht/high_seat*`
- Verify query `?token=` vs `X-Anchor-Token` for High Seat requests

---

## Out of scope for this intake (explicit)

- Do **not** resume or kill the other idle Claude sessions on Puter; John will handle later.
- Do **not** commit Ecgberht steward tree in this sleep intake (separate decision).
- Do **not** ad-hoc patch Anchor outside a sleep / formal improve cycle (global ban on skill ad-hoc patching still applies to product sleep work via normal Anchor improve process).
- **Project-level steward** — John inspecting separately (not Defect 7).

---

## Recommended sleep order

1. **Stop/restart handoff + single auto-continue control** (Defect 2) — unblocks every project’s daily use.  
2. **General small-tab attach + real Retry** (Defect 5) — same open/resume family as Defect 2; fix together if one PR can cover both.  
3. **Usage/time/$ surface honesty** (Defect 1) — trust + ops.  
4. **Doctor diagnose+fix + three engines** (Defect 3) **and banner→Doctor issue binding** (Defect 3b) — hygiene self-heal that knows *which* warning it is fixing.  
5. **High Seat token + no-reload draft** (Defect 7) — High Seat unusable until fixed; pair with auth hygiene.  
6. **Projects folders default collapsed** (Defect 6) — small polish; easy win at end of sleep or with any dashboard chrome pass.

When sleep closes each defect: `friction_journal.set_status(<id>, "resolved", note=…, commit=…)`.

