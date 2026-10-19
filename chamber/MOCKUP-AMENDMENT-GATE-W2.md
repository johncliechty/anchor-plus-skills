# W2 batched mockup-amendment gate (steward-e1)

**Signed by:** John — 2026-08-13
**Prepared:** steward-e1 W2 (2026-08-12)
**Gate code:** `chamber_e1_hook.py :: amendment_gate_state` — the fail-closed
signature reader (absent or unsigned ⇒ the drawn blocked-turn state is never
claimed signed). The C9 re-pin (below) FOLLOWS the signature; it never
precedes it.
**Amends:** the signed `mockups.html` §amendments (the W1 gate's file, inside
the Ecgberht sibling at `planning/steward-assessment-2026-08-08/mockups.html`,
resolved via `ECGBERHT_ROOT` / the sibling checkout — never a host-absolute
path).

## Why this comes to you (context first)

Two drawn states are missing from the signed mockup, and both are already
owed by name:

1. **The E1 refusal state (V5).** The steward-e1 build wires the
   turn-completion hook: once you ratify the F7 bound, the engine
   structurally refuses to close a steward turn while a direct question of
   yours lacks a typed answer-reference. V5's law: that refusal must be a
   DRAWN state — "so the cure never looks like the disease ('are you
   working')." Today the refusal has no signed face.
2. **The transcript-link row (your ruling, 2026-08-11).** At the W12
   tile-retirement signing you ruled decision 1 `AMENDMENT ORDERED`: "Draw a
   transcript link onto the rail runcard's links row and route it through
   the W1 batched amendment gate; John re-signs and the new markup hash is
   re-pinned for C9." This record is that routing.

Both are batched here for ONE signature, per the plan.

## Row 1 — AG-BLOCKED-TURN (the V5 E1 refusal state)

A blocked close paints a VARIANT of the locked `msg steward` element (the
variant law: base classes + marker), carrying the named finding and every
unanswered question with its deterministic id. Drawn in the M1 v2 idiom:

```html
<div class="astate"><!-- AG-BLOCKED-TURN -->
  <div class="ahd">Turn blocked — unanswered direct question <span class="ag">AG-BLOCKED-TURN</span></div>
  <div class="abody">
    <div class="msg steward blocked">
      <div class="who">⛔ Jarvis — turn blocked</div>
      <div class="bfind">E1-TURN-CLOSE-BLOCKED · a direct question from John lacks a typed answer-reference</div>
      <div class="bq">“confirm you got comments on the whole deck” <span class="bqid">q01-63e8debfddfa</span></div>
      <div class="bnote">The engine refused to close this turn — the E1 refusal state, drawn distinct from “are you working”.</div>
    </div>
  </div>
</div>
```

The live render is `chamber_e1_hook.render_blocked_turn` — structurally
identical to this fragment by test
(`tests/test_chamber_e1_enforcement_w8.py`). New drawn signatures this row
adds: `div.msg.steward.blocked` (variant), `div.bfind`, `div.bq`,
`span.bqid`, `div.bnote`.

## Row 2 — AG-RUNCARD-TRANSCRIPT-LINK (tile-retirement decision 1, ordered)

The rail runcard's links row gains the one-click transcript link the bottom
tile carried — the durable transcript (`general/<session>-transcript.md`)
through the traversal-safe `/artifact` route:

```html
<div class="astate"><!-- AG-RUNCARD-TRANSCRIPT-LINK -->
  <div class="ahd">Runcard links row — full transcript <span class="ag">AG-RUNCARD-TRANSCRIPT-LINK</span></div>
  <div class="abody">
    <div class="fstep run">
      <span class="dot">▶</span>
      <div class="nm">External scan <span class="skillch">· researchPrime</span></div>
      <div class="runcard">
        <div class="ttable">⏱ 14:32 · wave 2/4 · 11 sources</div>
        <div class="links"><a href="#">status ▸</a><a href="#">session ▸</a><a href="#">transcript ▸</a></div>
      </div>
    </div>
  </div>
</div>
```

No new element signature (an `<a>` under `div.links` is already drawn); the
row exists so the LINK ITSELF is signed, per your ruling. The live render
(`chamber_rail._runcard_html`) already emits it, traversal-safe and
F5-validated at click.

## Effect while unsigned

The C9 pin stands at the W1 hash (`chamber/MOCKUP-AMENDMENT-GATE.md`,
`4a7f7953852b…`); `mockups.html` is NOT modified before your signature. The
blocked-turn state cannot appear live anyway while the F7 bound is unsigned
(enforcement fails closed by name and never blocks). The tile-retirement row
`full-transcript-log-link` stays `amendment-ordered` and keeps blocking
retirement.

## On signing — the exact re-pin procedure (the signature's mechanical tail)

1. Append the two `astate` blocks above, VERBATIM, to `mockups.html`
   §amendments (before the section's closing `</div>`).
2. Recompute `sha256(mockups.html)` and REPLACE the hash line in
   `chamber/MOCKUP-AMENDMENT-GATE.md` — that is the C9 re-pin; every DOM
   diff re-points automatically (`chamber_mockup_diff.signed_hash` reads
   that record).
3. Record the signature HERE: replace the **Signed by:** line with
   `**Signed by:** John — <date>`, delete `— UNSIGNED` from the first line.
4. In `chamber/tile-affordance-inventory.json`, flip the
   `full-transcript-log-link` row's `john_ruling` to `equivalent` (the
   ordered amendment has landed) — the tile-retirement gate itself stays
   UNSIGNED (decision 3 remains deferred; no tile code is deleted).

## Recommendation, then the decision

**Recommendation:** sign both as drawn. Row 1 is the V5 law made visible —
without it the first real E1 refusal would read as a hung steward. Row 2 is
your own ordered amendment, drawn exactly as ruled, with no new element
shapes. One signature closes both.

Sign the batched amendment — AG-BLOCKED-TURN and the runcard transcript-link
row, as drawn above?
