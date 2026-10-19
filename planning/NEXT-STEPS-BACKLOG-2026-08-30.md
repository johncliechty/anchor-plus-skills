# Deferred ideas and possible next steps

This is a grasscatcher. Nothing here is part of the morning acceptance bar.

1. Obtain reliable served-model attestation from Codex so ChatGPT can be an honest
   reviewer/judge seat, not only a coding/orchestration seat.
2. Run Fable as the independent adversarial reviewer across Trio, Jumper, Steward,
   and Anchor integration.
3. Complete real Gmail and Outlook OAuth: consent, least-privilege scopes,
   encrypted token storage, refresh/revocation, disconnect, sync, and error states.
4. Refine Steward’s initial brainstorm into goal → plan → slices/core components →
   integration map → deliverables, while keeping the conversation lightweight.
5. Improve the deliverable visualization: dependencies, synthesis points, status,
   evidence, and “what is next” without turning it into project-management clutter.
6. Integrate and best-in-class review Doctor, Zombie Hunter, Skill Foundry,
   researchPrime, Crucible, Foreman, Gandalf, and the remaining domain skills one
   at a time with compatibility gates.
7. Finish Anchor v1.2.8 hygiene: remove user-specific fixtures, verify the clean
   release manifest, commit/push/merge, and document the deploy/restart procedure.
8. Add durable run records, ten-minute status history, process-census diagnostics,
   and a readable failure/recovery view in the cockpit.
9. Add offline/demo mode and accessibility/mobile polish for the cockpit.
11. Build the Ecgberht heartbeat supervisor: persistent ten-minute scheduler,
    chat/desktop notification bridge, missed-heartbeat detection, restart and
    failover journaling, and a cockpit status view. Until this exists, the
    session agent will monitor and relay updates whenever the session is active,
    but cannot guarantee push delivery while idle.
10. Revisit Jumper’s silence/respawn behavior with real-world runs after the
    deterministic contract has been used in production.
