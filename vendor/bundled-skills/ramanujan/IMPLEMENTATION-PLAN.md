# Implementation Plan — Implementation Plan (Foreman-ready)

test-command: node --test test/

**North Star:** Overhaul Ramanujan into a fully automated, Crucible/Foreman-backed mathematical reasoning engine that silently intercepts claims via semantic classification and verifies them in a cross-platform sandbox, gated by a strict Honesty Law UI.

## Success criteria
- CertifierQueue is completely dismantled and certification tasks are routed exclusively through the Crucible/Foreman pipeline.
- Phase 1 semantic classifier accurately intercepts Claim<Empirical> and mathematical assertions, entirely replacing legacy regex interception.
- Phase 2 implements a strict cross-platform security sandbox for executing all exact-arithmetic and logic verifications.
- Phase 3 introduces a UI gating mechanism that strictly enforces the Honesty Law, ensuring unverified claims never bypass the verification tiering.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Semantic Interception & Event Bus Dispatch

**Intent:** Establish non-blocking text streaming and intercept claims via a semantic classifier, severing the UI rendering path from verification.

**Deliverables:** Unblocked UI text streaming pipeline; Lightweight semantic classifier for Claim<Empirical> and math assertions; Event bus dispatch mechanism replacing legacy regex.

**Depends on:** —

**done-when:** The UI streams text without blocking while the semantic classifier accurately intercepts claims and dispatches them to the event bus.

- **Given** A stream of incoming text containing mathematical or empirical claims, **when** The text is processed by the application, **then** Text renders immediately without wait-states while claims are asynchronously intercepted and dispatched to the event bus

## Wave 2 — Crucible/Foreman Pipeline Integration

**Intent:** Route intercepted claims from the event bus to the Crucible/Foreman pipeline, fully dismantling the legacy CertifierQueue.

**Deliverables:** Event bus listeners for claim routing; Fast-path WASM queue for local proofs; Foreman background worker orchestration for multi-step agentic proofs; Dismantled CertifierQueue.

**Depends on:** Semantic Interception & Event Bus Dispatch

**done-when:** All certification tasks bypass the legacy queue and are exclusively routed to the fast-path queue or Foreman background pipeline based on complexity.

- **Given** An intercepted claim residing on the event bus, **when** The routing layer processes the event, **then** The claim is passed to the fast-path queue or Foreman background worker, and legacy CertifierQueue logic is completely bypassed

## Wave 3 — Secure WASM Sandbox Runtime

**Intent:** Implement a strict cross-platform security sandbox with hard boundaries for executing exact-arithmetic and logic verifications.

**Deliverables:** WASM runtime environment (e.g., Wasmtime); Pre-compiled z3 and exact-arithmetic WASM integration; Native runner enforcing memory (OOM) and instruction-count/timeout limits.

**Depends on:** Crucible/Foreman Pipeline Integration

**done-when:** Verifications securely execute within the WASM sandbox, enforce strict resource boundaries, and publish structured evidence back to the event bus.

- **Given** A complex verification task involving z3 executing in the background worker, **when** The task is run inside the WASM runtime, **then** The execution completes within the enforced memory and timeout limits and publishes structured evidence, or is safely terminated if limits are exceeded

## Wave 4 — Honesty Law UI & Asynchronous State Resolution

**Intent:** Strictly enforce the Honesty Law by dynamically reflecting asynchronous verification states in the UI and resolving off-screen updates.

**Deliverables:** UI event listener for verification results; Dynamic claim state styling (pending, verified, unverified, refuted); Interactive refuted claim context (tooltips/inline blocks); Off-screen margin indicator or global status tray.

**Depends on:** Secure WASM Sandbox Runtime

**done-when:** The UI accurately reflects real-time Honesty Law verification states, surfaces context for refuted claims, and alerts users to off-screen asynchronous updates.

- **Given** An asynchronous verification result returns from the event bus for a claim that is currently off-screen, **when** The UI receives the resolution payload, **then** The visual state of the claim updates dynamically to its final Honesty Law tier (e.g., refuted with context) and a margin indicator alerts the user to the off-screen state change
