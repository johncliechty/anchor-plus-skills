# plans

*Lane: planning · validated, cached summary*

**When run:** 2026-07-14

**What was asked:** plans

**North Star:** **Intent:** Build the new qualitative journaling interface requiring structured Input, Output, and Lessons with semantic validation. **Deliverables:** Journaling form UI with Input, Output, and Lessons fields; Input validation logic enforcing non-empty and minimum word counts; Reflection database save procedures **Depends on:** Wave 1: Sever Automated Logging & Telemetry Isolation **done-when:** A user cannot submit a journal entry unless 'Input', 'Output', and 'Lessons' are all populated and meet minimum validation criteria. - **Given** A user is on the new journaling interface, **when** They

## Actions & files produced

- Implementation Plan — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star:** Replace Anchor's passive automated logging with explicit, qualitative human reflection structured around three required fields — Inputs, Outputs, and Lessons Learned.
- **Success criteria:** (1) automated log generation disabled and its data paths severed from the journaling UI; (2) journal submission blocked unless Input, Output, and Lessons are all non-empty; (3) historical automated logs segregated from new reflection entries, never merged.
- **Wave 1 — Sever Automated Logging & Telemetry Isolation:** decouple telemetry into a hidden separate store and disable the legacy automated pipelines feeding the user-facing journal database; done when automated logs no longer populate the reflection database while telemetry keeps writing elsewhere.
- **Wave 2 — Core Reflection UI & Submission Validation** (depends on W1): the journaling form with Input/Output/Lessons fields, non-empty + minimum-word-count validation, and reflection-database save procedures; an empty Lessons field blocks submission with a visible error.
- **Wave 3 — Reflection Cues & Snooze** (depends on W2): a memory-cues panel surfacing recent git/calendar activity (displayed, never auto-saved) plus a snooze button with backend timer logic to dismiss the reflection prompt temporarily.
- **Wave 4 — Unified Timeline & Legacy Segregation** (depends on W3): one chronological timeline merging both data sources, with legacy automated logs visually distinct, read-only (no edit controls), and never merged into new reflections.
- **Conventions:** test command is `node --test test/`; every wave must ship real source that its new tests import and exercise, with D16 hybrid acceptance criteria (one-line done-when plus Given/When/Then for non-trivial waves).

## Files

- [Implementation Plan — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=plans%2FIMPLEMENTATION-PLAN.md)
