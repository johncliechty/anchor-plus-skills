# Steward E1 — the enforcement leg the chamber build never landed

## What this is FOR

Make E1 **true**. Today the steward *promises* not to walk away from a question
it asked John; it is not *unable* to. This build closes that gap.

E1 as the locked master plan defines it:

> A steward turn structurally CANNOT close while a ratified direct question id
> lacks a typed answer-reference; the ⏱ table + footer inject on the telemetry
> clock with zero model involvement.

## Why it is being built now, separately

The 12-wave steward-chamber build (2026-08-09 → 2026-08-11, all waves GREEN,
merged `3dbc21c`) landed E2–E9 but **E1 never landed at all**. W8 changed no
chamber source: parser ABSENT, ratification artifact ABSENT, turn hook ABSENT,
joint negative-path test ABSENT. The failure was silent by construction — the
F7 ratification HALT could not fire, because the parser it ratifies did not
exist, so nothing ever stopped to notice.

The consequence, from `chamber/E1-ENFORCEMENT-REPORT.md`:

> E1 is NOT engine-enforced in the assembled system. A steward turn CAN close
> on an unanswered direct question today. Convention (the seat prompt's
> one-question rule) is the only cover — exactly the failure class the master
> plan's Enforcement-Honesty table warns about.

W12 deliberately refused to build it: first-exercising a criterion in the
close-out wave is a defect by the plan's own rule. So it comes here, as its
own build, with the ratification gate the design always required.

## Scope

**In:** the four missing E1 legs (W3 parser + F7 artifact; W8 turn hook +
joint negative-path test), the V1 fixture amendment, the V5 "blocked turn"
drawn state, and verification of the telemetry-injection half of the
criterion.

**Out (named, not forgotten):** the ease-classifier stack (C8 — W3 classifier,
W8 live ledger, V6 latency log) is the *adjacent* gap from the same missing
waves, and is why `chamber/EASE-CLOSE-REPORT.md` reports UNAVAILABLE. It is a
separate criterion and is NOT in this build's scope. It remains John's
disposition.

## Normative inputs (bound by path — the build may not invent these)

- `planning/steward-chamber-2026-08-09/IMPLEMENTATION-PLAN.md` — W3, W8, V1,
  V5, and the C4/E1 criteria-ledger row. NORMATIVE and unchanged; this plan
  re-executes those rows, it does not redefine them.
- `chamber/E1-ENFORCEMENT-REPORT.md` — the mechanical instrument scan that
  established the four legs are absent. Its scan is the acceptance oracle:
  it must flip to all-present and stay re-runnable.
- `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\mockups.html`
  §M1 + §overlays — markup/classes are the UI spec. Signed hash
  `4a7f7953852b5563fd10e073f7cab8c1ac7930390d0743726b54aebc31aeedde`
  pinned for C9. Any new drawn state goes through the W1 batched amendment
  gate and re-pins that hash.
- The reference behavior: the Stage-2 Fable-driver session journal
  (`C:\dev\MBA Teaching AI\MBA Teaching with AI\journal\0001-…md`) — source of
  the verbatim T+15 fixture.

## Seats (John's direction, 2026-08-12)

- **Coding seats (execute/fix):** Claude family, Heavy → `claude-fable-5`.
- **Review/judge seats:** **Grok** (`grok-cli` → `grok.exe -p`, Grok Build
  subscription). True cross-family adversarial review — the chamber build ran
  review on Fable as well, i.e. single-family.

## Standing laws inherited from the chamber build

- Hermetic tests: `ANCHOR_PTY_BACKEND=stub`, temp git/data dirs, private
  `--basetemp`. Never `:8777`, never real data, never network.
- Auth-ON tagging on every new `tests/test_chamber_*.py`.
- Python stdlib only (the lazy `pywinpty` waiver in `pty_manager.py` stands).
- `anchor_gui.py` HTML is an f-string (double braces); `_PROJECT_WINDOW_JS` is
  RAW single-brace.
- Every new module lands in `dist_manifest.txt` in-wave, or the distro
  import-closure gate reds the wave.
- A wave's gate must include the distro/ship family whenever it touches
  shippable files (foreman journal 0091).
- No tile code is deleted. The tile-retirement gate stays UNSIGNED and
  `chamber_retirement.retirement_allowed` keeps refusing by name.
