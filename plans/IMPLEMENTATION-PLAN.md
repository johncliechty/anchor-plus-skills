# Implementation Plan — Implementation Plan (Foreman-ready)

test-command: node --test test/

**North Star:** Anchor's journaling system requires explicit, qualitative human reflection structured around Inputs, Outputs, and Lessons Learned, completely replacing passive automated logging.

## Success criteria
- Automated log generation is disabled and its data paths are fully severed from the journaling UI.
- The journaling interface requires non-empty inputs for 'Input', 'Output', and 'Lessons' before a journal entry can be submitted.
- Historical automated logs are clearly segregated from qualitative reflection entries and not merged into the new view.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Wave 1: Sever Automated Logging & Telemetry Isolation

**Intent:** Decouple telemetry from user journaling and disable legacy automated pipelines feeding the UI.

**Deliverables:** Hidden telemetry storage stream; Disabled automated pipelines feeding the user-facing journal database

**Depends on:** —

**done-when:** Automated logs no longer populate the reflection database, but system telemetry continues writing to a separate store.

- **Given** An automated background process fires an event, **when** The legacy automated logging pipeline processes it, **then** It routes to the decoupled telemetry store and NOT the user-facing reflection database

## Wave 2 — Wave 2: Core Reflection UI & Submission Validation

**Intent:** Build the new qualitative journaling interface requiring structured Input, Output, and Lessons with semantic validation.

**Deliverables:** Journaling form UI with Input, Output, and Lessons fields; Input validation logic enforcing non-empty and minimum word counts; Reflection database save procedures

**Depends on:** Wave 1: Sever Automated Logging & Telemetry Isolation

**done-when:** A user cannot submit a journal entry unless 'Input', 'Output', and 'Lessons' are all populated and meet minimum validation criteria.

- **Given** A user is on the new journaling interface, **when** They attempt to submit with an empty 'Lessons' field, **then** The submission is blocked and a validation error is displayed

## Wave 3 — Wave 3: Reflection Cues & Snooze Functionality

**Intent:** Reduce user friction by adding memory cues and a snooze option for the reflection prompt.

**Deliverables:** Memory cues panel surfacing recent git or calendar activity; Snooze button UI and backend timer logic

**Depends on:** Wave 2: Core Reflection UI & Submission Validation

**done-when:** The reflection prompt can be temporarily dismissed via snooze, and a memory cues panel displays recent activity without auto-saving it.

## Wave 4 — Wave 4: Unified Timeline & Legacy Segregation

**Intent:** Provide a unified chronological view that distinctly separates read-only legacy automated logs from new qualitative reflections.

**Deliverables:** Unified timeline UI merging both data sources chronologically; Visual styling rules for legacy vs. new entries; Read-only enforcement for legacy entries

**Depends on:** Wave 3: Reflection Cues & Snooze Functionality

**done-when:** The user can view a timeline where historical automated logs are visually distinct from new reflections and cannot be edited or merged.

- **Given** A user views the unified timeline containing both entry types, **when** They interact with a legacy automated log entry, **then** It is styled distinctly from new reflections and provides no editing controls
