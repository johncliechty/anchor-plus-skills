# Butler user stories — the binding Phase-4 envelope validation target (W3)

These three user stories are the BINDING validation target for the W12 Butler
envelope: W12 must land a test that answers all three **from journal envelope
fields alone** (`correlation_id` · `causation_id` · `actor{kind,id}` ·
per-project `seq` + wall `ts` · `schema_ver` · the event type). If a story
cannot be answered from the envelope, the envelope — not the story — changes
(via the documented amendment path). Checked in by W3 so the envelope is
designed against real Butler needs, not guessed at after the fact.

## Story 1 — "What happened while I was away?"

> As John, back at the dashboard after a day away, I ask the Butler: *"what
> changed in this project since I last looked, in order, and who or what did
> each change?"*

**Envelope answer path:** filter the per-project journal to events with `seq`
greater than the last-seen seq (or `ts` inside the away window), order by
`seq` (monotonic per project — no clock trust needed), and label each event
with its type plus `actor.kind`/`actor.id` (`user-click` · `auto-advance` ·
`healthcheck-synthetic` · `cli`). No legacy-store read is required.

## Story 2 — "Why did this build start?"

> As John, seeing a build session appear, I ask the Butler: *"trace this back
> — what caused it, and which user action is at the root?"*

**Envelope answer path:** from the build session's `session-started` event,
follow `causation_id` to the parent event (the planning session's
finish/advance), and transitively to the root event whose `actor.kind` is
`user-click`; `correlation_id` groups every event of the same effort so the
whole lineage (research → plan → build) reads out as one chain. The
auto-advance hop is visible as `actor.kind=auto-advance` — the Butler can
distinguish "John did this" from "the machine did this on John's behalf".

## Story 3 — "Show me real activity — ignore the synthetic noise."

> As John (or the Butler computing a daily digest), I ask: *"how much REAL
> work happened per project this week — excluding the healthcheck's synthetic
> walks and mechanical churn?"*

**Envelope answer path:** partition events by `actor.kind`, excluding
`healthcheck-synthetic` outright; bucket by `ts` day and project; count by
event type. `schema_ver` guarantees a reader that spans old and new events
keeps working (additive-only within a major version, unknown-field-tolerant
readers — the W12 schema-evolution rule).
