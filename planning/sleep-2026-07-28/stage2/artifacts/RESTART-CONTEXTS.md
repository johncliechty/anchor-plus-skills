# Restart contexts enumeration

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W17 — Phase 3: Per-context restart contract
Surface: `restart`
Schema: restart-contexts/v1

**Intent:** Enumerate every restart context, guarantee **exactly one** restart
control per context, and write each control's **scope name** and
**preserved/lost** contract. Cross-context unification is explicitly **out of
scope**.

Inventory control ids (from `CAPABILITY-INVENTORY.md`): `restart_run`,
`restart_session`, `restart_engine`, `restart_workbench`.

## Enumeration (machine-readable)

| context_id | control_id | scope_name | control_label | preserved | lost | contract_line | requires_scope_confirmation | dual_controls_forbidden |
|------------|------------|------------|---------------|-----------|------|---------------|----------------------------|-------------------------|
| run | restart_run | Restart run | Restart run | session_identity, transcript, workspace_files | running_tool_calls, in_flight_run_handle, partial_run_output | session identity and transcript preserved; running tool calls and in-flight run handle lost | false | true |
| session | restart_session | Restart session | Restart session | transcript | running_tool_calls | transcript preserved, running tool calls lost | false | true |
| engine | restart_engine | Restart engine | Restart engine | session_record, workspace, on_disk_transcript | live_pty, engine_process, in_memory_engine_state | session record and on-disk transcript preserved; live PTY and engine process lost | true | true |
| workbench | restart_workbench | Restart workbench | Restart workbench | project_registry, persisted_documents | open_panels, live_terminal_attachments, ephemeral_ui_state | project registry and persisted documents preserved; open panels and live terminal attachments lost | true | true |

## Per-context detail

### run — Restart run

- **Control id:** `restart_run`
- **Single control label:** Restart run
- **Preserved:** session identity, transcript, workspace files
- **Lost:** running tool calls, in-flight run handle, partial run output
- **Contract line:** session identity and transcript preserved; running tool calls and in-flight run handle lost
- **Entry point:** `anchor.session.restart.restart_run`
- **Blast radius:** narrow (this run only) — no scope-naming confirmation

### session — Restart session

- **Control id:** `restart_session`
- **Single control label:** Restart session
- **Preserved:** transcript
- **Lost:** running tool calls
- **Contract line:** transcript preserved, running tool calls lost
- **Entry point:** `anchor.session.restart.restart_session`
- **Blast radius:** session process — no dual competing 'Restart' + 'Restart session' controls

### engine — Restart engine

- **Control id:** `restart_engine`
- **Single control label:** Restart engine
- **Preserved:** session record, workspace, on-disk transcript
- **Lost:** live PTY, engine process, in-memory engine state
- **Contract line:** session record and on-disk transcript preserved; live PTY and engine process lost
- **Entry point:** `anchor.session.restart.restart_engine`
- **Blast radius:** large — **requires_scope_confirmation = true**

### workbench — Restart workbench

- **Control id:** `restart_workbench`
- **Single control label:** Restart workbench
- **Preserved:** project registry, persisted documents
- **Lost:** open panels, live terminal attachments, ephemeral UI state
- **Contract line:** project registry and persisted documents preserved; open panels and live terminal attachments lost
- **Entry point:** `anchor.session.restart.restart_workbench`
- **Blast radius:** large — **requires_scope_confirmation = true**

## Invariants (enforced)

1. Exactly **one** restart control per context (render-time + `tools/restart_control_audit.py`).
2. A context that currently renders both a bare `Restart` and a `Restart session`
   control **fails the audit** naming the context and both controls.
3. When restart is not possible on this build, the view renders a named
   `cannot_restart` state and **no** dead button.
4. Cross-context unification is **not** performed by this wave.

## Source of truth

- Contracts: `anchor/session/restart.py` → `RESTART_CONTRACTS`
- Render: `anchor/ui/restart_controls.py`
- Audit: `tools/restart_control_audit.py`
- Failure-state table: `artifacts/failure-states/restart.md`
- Traces: `artifacts/traces/restart-*-e2e.json`
