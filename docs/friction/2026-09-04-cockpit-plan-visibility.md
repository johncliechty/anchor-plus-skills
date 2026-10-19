# Friction — a plan the steward asks John to approve is not visible in the cockpit

`date`: 2026-09-04
`surface`: Anchor AI cockpit (steward_cockpit), plan bar and active-run row
`reported by`: John, in the 3D Parametric Representation campaign, on being asked to approve a researchPrime plan
`outcome`: John had to ask for the plan to be pasted into the dialogue; the ask had named the file on disk, per the Elegance law, and the cockpit offered no way to open it

## What happened

The steward put a decision to John: approve the researchPrime plan for a novelty check. The plan artifact was on disk (`report/researchprime-novelty/planInputs.json` in the campaign folder) and the message named it by path, as the Elegance law requires (the artifact stays on disk, the ask stays under 200 words). John, reading the cockpit, could not see the plan and wrote back: "give me a summary of the report (or the full report, if not too long). We have to have an easier way to see these plans." He then asked for this intake and proposed the fix himself: a link on the plan bar, under the active run, that opens the plan so he can see it and act on it.

This is the second time today a report-shaped artifact had to be re-surfaced by hand (earlier: review reports needed a plain summary at the top, memory `cockpit-and-report-feedback`). Both are the same defect: the cockpit shows the map and the status, but not the *document John is being asked to decide on*.

## Why it matters

Every skill in the foundry has a gate that asks John to approve a plan, a proposal or a draft (researchPrime's plan gate, Crucible's stage gates, the kickoff proposal, Foreman's implementation plan). The Elegance law forbids pasting those into the ask. So the cockpit must render or link them, or every gate costs one round trip of "show me". Each such round trip is overhead on the ease metric, caused by the surface, not by John.

## What John asked for

A link on the plan bar, under the active run, to the artifact currently waiting on his decision, opening it in place (or in a pane beside the dialogue) so he can read it and answer in the same view.

## Proposed mechanism (for the cockpit owner to size)

1. **A `pending_decision` field in the campaign heartbeat.** The steward already writes `.ecgberht/attention.json` with `state: needs_you` and a reason. Add `artifact` (a path relative to the campaign folder) and `kind` (plan | proposal | draft | report). The steward writes it at the moment it asks; the cockpit reads only that file, as it already does for the state line.
2. **Render it on the plan bar.** Under the active run, when `state == needs_you` and `artifact` is set: a link with the artifact's title, opening the file rendered as Markdown or pretty-printed JSON in a side pane, without repainting the dialogue or the input box (the standing rule from the same day: never wipe what John is typing).
3. **Deliverables tile already knows how to link files.** Reuse its renderer; the difference is only the source (`attention.json` instead of `DELIVERABLES.md`).
4. **Optional:** the pane carries the same one-word answer buttons the decision needs (approve / edit / abort for plan gates), writing John's answer into the dialogue as if typed, so the steward's read-back gate still sees a human token.

## Acceptance (what John sees)

He opens the cockpit cold, the state line says "needs you", the plan bar shows "Plan: novelty check (researchPrime) — open", he clicks, reads the plan beside the dialogue, and types "approve". No paste, no "show me".

## Steward-side change, done today

Ecgberht will start writing `artifact` and `kind` into `attention.json` whenever it asks for a decision on a file, so the cockpit has the data the day the link is built. Until then the steward will also paste a short plain rendering of any plan it asks John to approve, over the Elegance word limit if he asks, as he did here.
