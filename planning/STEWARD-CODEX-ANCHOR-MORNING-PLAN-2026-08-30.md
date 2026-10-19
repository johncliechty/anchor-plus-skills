# Steward–Codex–Anchor implementation plan

**Purpose:** deliver a small, testable morning build: Codex routing foundations,
ChatGPT choices in Anchor, and the current AI-cockpit/main-dashboard prototype
with empty synthetic calendar/email surfaces.

## Definition of done

- Every skill entry point uses the shared Trio `runAgent` seam for coding,
  orchestration, review, and judge roles; no skill silently hard-codes a model.
- Codex/ChatGPT is selectable for terminal, coding, review, and judge configuration
  where the seat can honestly support that role. Unattested Codex verification is
  visibly unavailable/degraded, never falsely marked cross-model.
- Anchor’s main dashboard exposes terminal, coder, reviewer, and judge selectors;
  choices persist through the existing settings/mirror law.
- The current Anchor v1.2.8 cockpit prototype is the served surface, with no
  project-specific or account-specific data committed.
- Calendar and email show empty synthetic states and a concise guided setup dialog:
  “Connect Gmail” or “Connect Outlook.” No OAuth token, mailbox, event, or contact
  data is stored in the repository.
- Deterministic tests and UI/API smoke tests pass; every real run has a journal
  record. No commit/push/merge occurs before the user reviews the batch.

## Bounded waves

### Wave 0 — freeze the foundation

Verify the completed Trio/Jumper work, preserve the dirty-work baseline, and stop
if the focused or full deterministic gates regress. No live model calls.

### Wave 1 — Codex across the skills

Inventory each skill’s driver/orchestrator/reviewer seam; route it through Trio;
add only the missing adapters and hermetic tests. Keep verification fail-closed
when Codex cannot attest the served model. Record a capability matrix by role.

### Wave 2 — Anchor model choices

Add ChatGPT/Codex to the main dashboard’s terminal, coder, reviewer, and judge
controls. Show availability and the reason for any disabled/degraded reviewer
choice. Exercise persistence with synthetic settings only.

### Wave 3 — cockpit prototype readiness

Serve the current prototype cockpit as the default dashboard. Refine the initial
Steward conversation surface and work-product map only enough to make the demo
clear. Replace calendar/email content with empty states and the Gmail/Outlook
guided setup dialog. Do not implement real OAuth in this wave.

### Wave 4 — evidence and handoff

Run focused and full suites, inspect the complete diff against the baseline, and
obtain Fable’s independent adversarial review. Present the exact changed files,
tests, skips, and known limitations. Commit, push, and merge only after approval.

## Operating guardrails

- One slice at a time; no new edge-case framework after the named gates are green.
- ChatGPT drives implementation; Fable is the independent reviewer when invoked.
- Settings are the only family-value source; test transports are injected and
  cannot reach live CLIs.
- 10-minute status tables include tests, blockers, process census, and journal.

## Steward operating contract (bottom section)

Steward begins each wave with a short human-facing restatement, asks for ideas
without forcing premature structure, then produces: goal, smallest useful plan,
work-product map, integration links, and the next single action. It keeps a
grasscatcher for deferred ideas, reports evidence after each slice, and asks for
approval only at a meaningful scope or release boundary. Complexity is earned by
the project’s needs; synthetic calendar/email are intentionally a light slice.
