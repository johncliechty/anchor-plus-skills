# Replace the v0 chamber with M1 — and delete v0

## What this is FOR

Make the M1 chamber the surface John actually sees. Today it paints and is
then removed on every open; the steady-state UI is the pre-campaign v0
dialogue. This replaces v0 with M1 and **deletes v0** — replacement, not
coexistence.

## The defect (evidence, not assertion)

`ecgSealMountInline()` paints the W6/W7 M1 slice, then hydrates
`/api/ecgberht/chamber` → `_ecgRenderChamber(host, j)` and immediately calls
**`_ecgSealDropSlice()`**, which removes the M1 rail from the document. The
surviving chamber reports `schema: ecgberht-seal-chamber-v0`,
`mount.host: "anchor-dev"`, `screen: "S1"`.

`_ecgRenderChamber` (static/project-window.js:7788–7899, 112 lines) was last
modified **2026-07-27** in `b9252a9` — *"check in pre-existing uncommitted
steward work UNTOUCHED"*. The 12-wave steward-chamber campaign
(2026-08-09 → 08-11) never touched it; it only ADDED the slice (W6, `c5ce636`).

Full incident record: `C:\dev\Ecgberht\journal\0083-the-m1-chamber-paints-then-deletes-itself.md`.

## The complication that shapes this plan

The interactive work is in **v0**, not in M1. `_ecgRenderChamber` creates
`.ecg-convo-col` (7835) and `.ecg-saybox` (7854); the say box, Refine,
commission-propose, the goal row and the footer stamp all bind to that DOM.
The M1 slice is a display paint plus a pulse poll (`_ecgSealPaintSlice`,
`_ecgSealStopPulsePoll`).

So this is not a markup swap. Every interactive affordance must be re-homed
onto M1's drawn structure before v0 can go.

## Approach — hydrate INTO the slice, then delete v0

Two options were live:

- **A. Keep the slice, hydrate interactivity into it, delete v0.** ← CHOSEN
- B. Rewrite `_ecgRenderChamber` to emit M1-shaped markup.

A wins on one decisive ground: the slice is mounted in a shadow root carrying
the **hash-pinned, verbatim signed mockup CSS**, and C9 diffs its markup
against the pin (`fe77d058f19a…`). That guarantee is the campaign's whole
anti-drift mechanism. Option B re-authors the markup by hand and reopens
exactly the drift C9 exists to prevent — "M1-shaped" is not "M1".

## Scope note — this is three waves, not one

John asked for "a wave". Honestly scoped it is three, because the deletion
cannot safely precede the parity proof, and the parity proof cannot precede
the inventory:

1. inventory + the kill gate that proves the defect
2. re-home interactivity onto M1
3. delete v0, enforced by CI

Compressing them would put the deletion before the proof — the same ordering
error that let the tile-retirement gate stay unsigned for good reason.

## The law this exists to establish

**When code is replaced, the replaced code is DELETED.** A superseded surface
left in the tree does not sit inert — it competes, and here it won. The
campaign's C12 "build-vs-wire honesty" pillar governs re-homing vs
reimplementation; it has no rule for *the old surface outliving the new one*.
This build adds that rule and enforces it in CI.

## Normative inputs (bound by path — the build may not invent UI)

- `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\mockups.html` §M1 +
  §overlays + §amendments — markup/classes are the spec. C9 pin
  `fe77d058f19a10b2735333c6ddcfcfa4cf811d471d1c3ed7a8fbf398b0ef82e1`.
- `planning/steward-chamber-2026-08-09/IMPLEMENTATION-PLAN.md` — C1–C12,
  E1–E9 remain in force; this plan adds none and repeals none.
- `chamber/tile-affordance-inventory.json` — the parity pattern this plan
  reuses for the chamber itself.

## Standing laws inherited

- Hermetic tests (`ANCHOR_PTY_BACKEND=stub`, temp dirs, private `--basetemp`),
  auth-ON tags, Python stdlib only, new modules into `dist_manifest.txt`
  in-wave, gate scope must include the distro/ship family.
- No tile code is deleted by this plan; the tile-retirement gate stays
  UNSIGNED and `chamber_retirement.retirement_allowed` keeps refusing.
- E1 enforcement (v1.2.2) is untouched and must stay green.
