# FINDING A — zombie-hunter detection is STRUCTURALLY BLIND to the orphan John cares about

**Verdict (agent A, 2026-07-26, read-only, file:line verified):** shadow mode's
"CLEAN / zombieActionable: 0" is **not** true detection. On Windows the single most
common orphan geometry — **parent process is dead** — is routed to `UNCERTAIN` →
`ABSTAIN` *before any other leg is consulted*. The one geometry the SC1 canary proves
(`ORPHAN_DETACHED_SPENDER`, fixture geometry A) is a **reparented** orphan under
`services.exe` — a shape **Windows never produces**. So the hunter has never been
tested against, and cannot flag, a real abandoned spender.

## The chain (zombie-hunter/src/, Node sentinel)

`classifyAll` (classify.js:337) → engine leg (engine-leg.js:159) → supervision
(host-walk.js:351) → spend (spend.js:391) → ownership (ownership.js:225) → quad
(quad.js:375) → server bucketing (server.js:328-381).

Quad order: ANY leg UNCERTAIN ⇒ ABSTAIN (quad.js:400-413) · ownership NEGATIVE ⇒ KEEP
(:415) · **supervision NEGATIVE ⇒ KEEP (:430)** · all four POSITIVE ⇒ WOULD_BE_RED
(:445) · else KEEP (:467).

"Supervised" = **image-basename match on any ancestor** against allowlist H
(host-walk.js:43-79: code, cursor, windowsterminal|wt, openconsole, conhost, grok,
anchor/anchor_gui, powershell|pwsh|cmd, explorer) AND `isHostSessionActive`
(host-walk.js:295-330) — which is **ONLY the Win32 SessionId integer**. No window
handle, no console/PTY check, no socket, no CPU/IO liveness. The journal-0002 fix only
closed the session-0 case.

## The false negatives (each traced)

- **FN-1 (killer): dead parent ⇒ ABSTAIN, always** (host-walk.js:358-364). Windows does
  not reparent; PPID keeps pointing at a dead/recycled PID → `MISSING_PARENT` →
  UNCERTAIN → ABSTAIN. Recycled PID → `CREATETIME_INVERSION` (:398-415) → also
  UNCERTAIN. **The canonical orphan can never reach WOULD_BE_RED.**
- **FN-2: dead grandparent ⇒ `MISSING_ANCESTOR`** (:454-466) → ABSTAIN.
- **FN-3: `explorer.exe` is an immortal supervisor** (:78) — session-1, never exits;
  anything under it is SUPERVISED forever.
- **FN-4: hidden/detached shells count as live** (:309-312) — `Start-Process -WindowStyle
  Hidden powershell` supervises its descendants permanently.
- **FN-5: missing SessionId defaults ACTIVE** (:317, :326-328).
- **FN-6: node-hosted engines invisible** — E2 requires an E1 image within K=2 parent
  hops (engine-leg.js:111-141); npm/cli.js-shaped Claude Code, agy node children, deeper
  sub-agents are dropped at classify.js:430 (never classified, never counted).
- **FN-7: spend = one instantaneous :443 socket sample** (spend.js:336) with exact-host
  DNS-cache reverse map (:225-250, atlas :30-46). Between requests during the 5.5s sweep
  ⇒ SPEND_NEGATIVE ⇒ **KEEP**. The real measured Claude token ledger (spend.js:782)
  feeds only the burn UI, **contributes nothing to the RED leg**.
- **FN-8: ownership fail-closed = machine-wide amnesty** (ownership.js:270-272).
- **WT tabs have no per-tab identity**: closing a tab changes no signal (all tabs are one
  WindowsTerminal.exe) — exactly John's "not tied to a session" case, undetectable.
- **SSH not handled at all** (absent from H, R, and job-parents).
- **False-POSITIVE risk (mirror image)**: Anchor's own terminals are ConPTY children of
  the NSSM-hosted `python anchor_gui.py`; if that service is session 0,
  `HOST_SESSION0_NONINTERACTIVE` (:304-305) makes a LEGITIMATE Anchor session
  UNSUPERVISED.

To emit WOULD_BE_RED today you need a spender whose whole ancestry is ALIVE and reaches
services/wininit/csrss without passing explorer/pwsh/cmd/conhost/code/cursor/wt/
openconsole/grok/anchor — i.e. a service- or scheduled-task-launched spender: **the
opposite of an orphan.**

## The live state file is structurally incapable of showing the blind spot

`.zh-last-known.json`: 1 active (claude.exe pid 47168, supervised via a **powershell**
ancestor, QUAD_KEEP), 34 idle, 0 zombies, `hiddenNonEngine: 2` (implausibly low →
FN-6). **35 engine-positive processes; only the 1 holding an atlas-attributed socket was
bucket-evaluated** — server.js:337 drops non-burning engines to `idle` before their quad
verdict is read. And `radar-cache.js:94-97` persists only observe/active/would_be tiles:
**the `burnUncertain` bucket — where every abstained orphan lives — is never written to
disk.**

## The Investigate slim-seed loss (journal 0004) — 3 stages

(A) server.js:894 `_startInvestigate` POSTs `{backend, slim, deepBrief}` with **no pid/
id/class** (the button at :829 is a global header control, not per-tile). (B) fallback
candidate literal is `{pid: null, reasonCodes: lastReasonCodes, engineClass: 'unknown'}`
(server.js:1098-1105). (C) `hydrateFromDurableLastKnown` (:253-268) never restores
`lastReasonCodes` (declared [] at :228, set only after a live sweep at :296). Plus the
durable tile shape (radar-cache.js:78-91) drops supervisionStatus/Reason, spendStatus,
hostId, root, createTime, imagePath, sessionId, engineClass, uncertainLegs — so an
Investigate agent can never see WHICH leg abstained, and `identityActionGate`
(:564-576) refuses the row as CACHE_ONLY_IDENTITY_REFUSED anyway.

## The 5 fixes (all shadow-safe: mode.js:184-187 + classify.js:654 keep freeze/kill off)

1. **Distinguish "parent dead" from "parent unknown"** (host-walk.js:358-371, :454-466):
   PPID absent from a COMPLETE enumeration = positive proof of death ⇒ new
   `UNSUPERVISED / PARENT_CONFIRMED_DEAD`; emit the already-catalogued
   `ORPHAN_DETACHED_SPENDER` (reason-catalog.js:54) which the classifier currently NEVER
   emits. Keep UNCERTAIN only for degraded/partial enumeration. **Add a geometry-B
   fixture** (ppid absent from nodes[] = the real Windows shape) next to
   fixtures/sc1/recorded/orphan-detached-spender-a.json.
2. **Real session-activity test** (host-walk.js:295-330): require a visible top-level
   window (GetWindowThreadProcessId) or attached console (GetConsoleProcessList), or —
   for Anchor — membership in Anchor's live PTY set. **Anchor already computes exactly
   this**: `live_owner_ids` = attached_pty ∪ job_owned ∪ parent_owned ∪ orientation_owned
   (C:\dev\Anchor\reaper.py:512-523, consumed by owner_ids_or_abstain :721). Wire it in
   through the ownership registry seam (ownership.js:244-248, ZH_OWNERSHIP_REGISTRY_PATH).
3. **Demote `explorer` + bare `conhost` from H to weak-host** (needs a 2nd signal);
   bump HOST_ALLOWLIST_VERSION (host-walk.js:19) which auto-forces re-shadow
   (mode.js:321-349) so the change cannot silently arm anything.
4. **Two-signal spend with memory** (spend.js:391-543, server.js:337): per-identity spend
   window in the worker; admit the MEASURED Claude ledger as a corroborator
   (`SPEND_POSITIVE_LEDGER` when evidenceClass==='measured' && recent); and fix
   server.js:337 so the idle shortcut still records the quad verdict.
5. **Fix the Investigate seed + durable shape** (server.js:894/:1098-1105/:253-268,
   radar-cache.js:78-91/:94-97, session-start.js:180-228): per-tile pid, restore
   lastReasonCodes on hydrate, persist burnUncertain, carry the abstaining leg.

## Cross-check: the Python reaper is the stronger model (and not the blind one)

`C:\dev\Anchor\reaper.py` distinguishes abstain/reap_dead/reap_recycled/alive/kill
(:540-590), abstains on degraded snapshots (:593-620), returns keep-everything owners on
registry-integrity failure (:721-740), and returns None on enumeration gaps so denied ≠
gone (:495-509). Tests: tests/test_reaper_abstain.py + work_evidence/win32/bounds. Its
scope is Anchor-REGISTERED sessions, not arbitrary OS token-spenders — so it also cannot
see John's orphan, but for a defensible reason. **No reaper/sentinel lines exist in
C:\dev\Anchor\logs\** (only daily markdown + NSSM stdout/stderr) — zero independent log
corroboration that any sweep ever ran.
