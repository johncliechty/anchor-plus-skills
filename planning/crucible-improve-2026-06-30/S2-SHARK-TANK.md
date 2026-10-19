# Stage-2 Shark-Tank Synthesis (wave decomposition)

> 3 cross-model Sharks (Gemini) refuted the IMPLEMENTATION-PLAN wave decomposition
> against real code. This round forced a substantial reshape — the original plan would
> have made the Foreman build fail. Resolutions folded into IMPLEMENTATION-PLAN.md.

## CONFIRMED BLOCKER I — "re-adopt surviving PTYs on restart" is impossible
**Agreement: S2-Shark-1 #2 + S2-Shark-3 #1 + #biggest-risk (≥2).** On a server restart
the OS closes the PTY master FDs; `pty_manager` has no adopt-a-PID seam. The #1 fix
CANNOT rely on re-adoption.
- **Resolution (from a static reproduce):** the real trigger is `classify`
  (`zombie_hunter.py:127-170`) flagging `kill` for a registered-running, identity-alive
  session whose `session_id` ∉ `pty_manager.live_sessions()` — i.e. **lane/job swarms
  `_LIVE` never tracks**, not ConPTY terminals. Fix = a **liveness-of-OWNER
  discriminator**: attached ⇔ in `_LIVE` OR owning job actively running OR parent
  session live. A true orphan (alive PID, no live owner) is still killed. **Stub-testable
  via injected records** (the harness already injects dead-pid records). The
  banner-stops-live check is a post-deploy sign-off, not a build dependency.

## CONFIRMED BLOCKER II — a reproduce/investigation step cannot live in a build wave
**S2-Shark-1 #1.** Foreman builds, it does not investigate. **Resolution:** the #1
reproduce is done pre-handoff (static trace above); Wave 2 ships a single, resolved,
testable design.

## CONFIRMED BLOCKER III — the keystone must precede the UI that depends on it
**S2-Shark-2 #1 + #3.** Discovered efforts are loose singletons
(`_gather_project_sessions:2456-2463`); if the efforts-list / controls ship before the
keystone folds them into effort-views, a stale discovered effort usurps the primary
tile and shoves a live session into the drawer, and `×`-closed sessions reopen cold.
**Resolution:** reorder so the resume backend lands first; split the keystone into
backend (stub-testable) + UI (sign-off).

## CONFIRMED BLOCKER IV — Gandalf hard-depends on the model-flex substrate
**S2-Shark-2 #5.** Gandalf map-reduce fans out via agy-dispatch, whose availability +
single-sub fallback live in the model-flex wave. **Resolution:** Gandalf is the LAST
wave, after model-flex.

## CONFIRMED BLOCKER V — several done-whens are not stub-testable
**S2-Shark-3 #2 + list.** CSS width, warm-greeting quality, "no agy spawned," and
"non-trivial findings" need browser/live-model verification the stubbed healthcheck
can't do. **Resolution:** every wave's done-when is split into a **STUB GATE** (a
concrete pytest assertion Foreman's gate runs) + a **SIGN-OFF** (UI/live, user-verified
post-build) — matching Anchor's standing rule: *every UI wave is gated by Playwright +
a screenshot + user sign-off* (the v4 lesson).

## ADOPTED (lower severity)
- Split the keystone into backend seed-synthesis (unit-testable) + UI/history.
- `×` close = **stop the PTY + preserve worktree/record (resumable)** — NOT OS process
  suspension (`pty_manager` has no suspend seam; S2-Shark-1 #5). Depends on the resume
  wave.
- W-controls must update JS listeners + CSS selectors in lockstep (S2-Shark-2 #2).
- Pin concrete values: switch-handoff summary timeout = **5 s**; quantify Gandalf
  "non-trivial" as **≥1 finding per shard across ≥2 shards**.
