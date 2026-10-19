# Friction — the two host-contract defects every new Anchor UI wave reintroduces

`date`: 2026-08-04
`surface`: Anchor host contracts for a consumed foundry skill (Ecgberht)
`outcome`: both caught by guard tests BEFORE the user hit them; both had already been
hit by the user once, in an earlier wave, in exactly the same form

## What happened

Wave 18 added the Ecgberht chamber UI (steps / proposal / confirm / artifact /
correction). It shipped two defects, and **both were the same defects John reported by
hand two waves earlier** — reintroduced by new code that never saw the fix.

### 1. A route declared `migrated=True` with no registered handler → 404 "Unknown endpoint"

Five new rows in `route_table.py` were declared `migrated=True`, and all five handlers
were *defined* in `anchor_gui.py` — but none were added to `_MIGRATED_HANDLERS`. The
dispatcher answers such a route with **404 "Unknown endpoint"**.

This is verbatim the failure John reported on 2026-07-30 for
`handle_ecgberht_stand_up` ("Couldn't do that: Unknown endpoint — nothing was
created"). Registration is a THIRD place that must be edited, in a different file from
both the route row and the handler body, with nothing tying them together.

Caught by `test_every_migrated_route_has_a_registered_handler` — the guard added when
the original bug was fixed. It did its job: the entire chamber UI would have been dead
on first open.

### 2. A new UI module invented its own token accessor → 401 → re-prompt

`static/chamber-ui.js` read the token from `window._anchorTokenQuery` (**defined
nowhere in the codebase**), falling back to `window.ANCHOR_TOKEN` / `window.anchorToken`
(**not set on the project window**). The canonical accessor, used by
`project-window.js` and `high-seat.js`, is `_anchorToken()` reading `localStorage`
key `anchor_token`.

Result: every chamber GET went out unauthenticated, 401'd, and the 401 path prompted for
a token the window already held — verbatim John's 2026-07-29 report ("it asked for a
token again (which it had stored in the window)").

Three separate reads in the one file were affected (`_tok()`, `_getJson`, `_postJson`),
so a partial fix would have left a working page that re-prompts only on some actions.

## Why it recurs

Both defects share a shape: **the contract is real but implicit, and a new module can
satisfy the type-checker and the eye while missing it entirely.** Neither the route
registration nor the token accessor has a single import that a new file is forced
through. A wave built by an agent working from a plan will invent a plausible-looking
local helper (`_anchorTokenQuery`, `window.ANCHOR_TOKEN`) rather than discover the
existing one, because nothing makes the existing one discoverable at the point of use.

## What actually helps

- **The guard test is the mechanism that worked.** `_MIGRATED_HANDLERS` coverage is now
  a test, so the defect became a RED gate instead of a user report. Its value was proven
  the first time a new wave landed after it.
- **The token accessor needs the same treatment**: a test asserting no `static/*.js`
  file reads a token from anywhere except `_anchorToken()`. That test does not exist yet
  and is the single highest-value follow-up from this wave.
- **Both belong in the wave template**, not in review: any wave that adds a route row or
  a client-side fetch should have these two checks in its acceptance criteria by default.

## Standing rule (proposed)

> A new Anchor endpoint is not "added" until it appears in THREE places — the route row,
> the handler body, and `_MIGRATED_HANDLERS` — and a new client fetch is not "wired"
> until it takes its token from `_anchorToken()`. Anything else is a 404 or a re-prompt
> waiting for the user to find it.
