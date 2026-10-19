# Decision Log: Scaled Gandalf Architecture

*Lane: planning · validated, cached summary*

**When run:** 2026-06-27

**What was asked:** Decision Log: Scaled Gandalf Architecture

## Actions & files produced

- Decision Log: Scaled Gandalf Architecture

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Decision Log: Scaled Gandalf Architecture — Summary
- **Include-list, not ignore-list scouting** — The Agentic Scout emits an "Include List" of files to keep rather than an "Ignore List" of files to drop. Rationale (Skeptic block): asking a fast model what to *ignore* risks hallucinated deletion of critical config files; asking what to *include* fails safe — a miss just triggers the fallback rather than destroying data.
- **Concurrency capped at 3** — Phase-3 Map-Reduce batches run under a strict concurrency semaphore of 3. Rationale (Contrarian block): unbounded async execution of large payload chunks would overwhelm the Anchor `job_runner`, hit API rate limits, and crash the local UI polling.
- **Graceful Scout fallback to unpruned payload** — If the Scout pass fails JSON parsing or hits an API timeout, the engine automatically reverts to sending the full unpruned payload. Rationale (Analyst block): the pipeline must not fail because an *optimization* step errored — rigor must survive optimization failures.

## Files

- [Decision Log: Scaled Gandalf Architecture](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=DECISION-LOG.md)
