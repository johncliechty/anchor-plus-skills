# North Star — ChatGPT is a first-class Terminal engine in Anchor (2026-09-05)

**Statement.** ChatGPT (the Codex CLI, v0.151) becomes a first-class engine for Anchor's
**Terminal** role — the fourth and last role that still said "bridge pending". An interactive
cockpit terminal opens on the Codex TUI in the session's worktree exactly as Claude and Grok
terminals do: seeded once with the lane skill, engine-switchable in place, closable and
resumable, Doctor-capable in a read-only posture; the dashboard offers it as ready; a saved
`default_cli=chatgpt` persists; and usage accounting says honestly "unmeasured" for the ChatGPT
segment (the RULED Option C) instead of guessing. John, 2026-09-05: "Is ChatGPT available for
all of the roles in Anchor? … Do that, integrate, before shipping v1.2.12."

**Why now.** v1.2.8 deferred the Terminal seat as "bridge pending" on the belief that a
persistent Codex exec/resume bridge was needed. It is not, for the terminal: Codex ships an
interactive TUI (`codex [PROMPT]`, `-C/--cd`, `-s/--sandbox`, `-a`, `-m`, `--no-alt-screen`,
`resume <id>`), the engine-command resolver for it already exists (`terminal_session.
_resolve_engine_cmd`), and the only thing closing the seat is one guard
(`_check_engine_allowed`) plus the settings/capability tables. Reviewer and Judge opened this
morning; Coder was open already.

## Success criteria (the SURFACE, not the capability)

1. **A terminal opens on ChatGPT.** With `default_cli=chatgpt` (or the engine toggle),
   `POST /api/rnd/term_start` starts a PTY running the Codex TUI in the session worktree
   (`--cd <worktree>`, `--no-alt-screen`, `-s workspace-write`, approvals left to the user in
   the terminal), the lane seed is written exactly once and the greet arrives, the registry
   record carries `backend: chatgpt`, and `POST /api/rnd/term_set_engine` switches a live
   session to and from ChatGPT in the same worktree with no orphan PTY.
2. **The truth tables agree.** The Terminal picker shows "ChatGPT — ready" (no "bridge
   pending" anywhere: capability matrix, option labels, the capability note, `anchor_settings`
   comments); `VALID_DEFAULT_CLIS` includes `chatgpt` and `save_settings(default_cli="chatgpt")`
   persists; `_check_engine_allowed` no longer gates `chatgpt`; a host without the Codex binary
   still fails closed with the existing `chatgpt-terminal-binary-missing` error.
3. **Doctor posture and honest accounting.** `live_doctor_session(backend="chatgpt")` launches
   with `-s read-only` (a `DOCTOR_READONLY_CLI_ARGS` entry); no session-id pin exists for Codex,
   so the session's usage state is `uncorrelated` and any rollup that includes it is stamped
   `partial (chatgpt segment unmeasured)` — never an mtime guess, never a fabricated $0.00.
4. **Nothing regresses, and it is seen.** The terminal nets stay green under the stub PTY
   (`ANCHOR_PTY_BACKEND=stub` + `ANCHOR_ENGINE_CMD`), `_LIVE_ENGINE_BASENAMES` still refuses a
   real `codex` spawn under test, the 5 AM v3/v4 walks are unchanged, `distro.py`'s import
   scan stays clean; and before v1.2.12 ships a ChatGPT terminal is opened from the dashboard
   and its greet is seen on the page (Playwright screenshot), not inferred from a stub.

## Non-goals (parked, named)

- The ChatGPT **Steward** (the cockpit dialogue engine speaks stream-json to `claude -p`; a
  ChatGPT steward is the F1B exec/resume bridge) — its own Foundry cycle.
- Doctor and Zombie Hunter ChatGPT *certification* beyond the read-only posture.
- Usage-cost correlation for Codex sessions (Option C stays honest-unmeasured).
- Per-seat model pinning in the terminal (`-m`) beyond what the prefs already carry.

## Risk taxonomy

| Risk | Mitigation |
|---|---|
| The Codex TUI's alternate screen renders badly through ConPTY + xterm.js | `--no-alt-screen` (inline mode) by default; verified on John's screen before ship |
| The seed turn lands before the TUI is ready, or Codex asks for approval on the seed | reuse the Grok seed timing (write after first output); the seed only loads the skill and greets; approvals stay `on-request` for the user to answer in the terminal |
| A saved `default_cli=chatgpt` reaches a host without Codex | the resolver's fail-closed `chatgpt-terminal-binary-missing` stands; the picker shows "unavailable" there |
| Tests that pin "bridge pending" go stale silently | every pin is rewritten to the new truth in the same wave, with the wave's done-when naming the file |

## Foresight brief

With the Terminal seat open, the four dashboard roles are complete for Claude, Grok and
ChatGPT. The next cycle is the ChatGPT steward (F1B): a per-turn `codex exec` with `resume`
behind the same status pane. The engine-toggle code path this effort exercises is the one
that bridge will reuse.
