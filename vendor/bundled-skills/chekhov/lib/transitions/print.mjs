/**
 * Print transition — the brief's lines (RIDER 5: the brief is status + print).
 * Line 1 names project and session state; line 2 is the manifest verdict:
 *   `unmanaged edit: <file>`            → reconciliation HALT is open
 *   `changed since last session: <file>` → John's NEW MATERIAL, queued for commit
 *   `no changes since last session`      → clean
 * Only lib/engine.mjs may call this module (machine-only-caller test).
 */
export function composeBrief({ project, state, line2, halted }) {
  const lines = [];
  lines.push(`chekhov ${project} — session ${state}${halted ? ' [RECONCILIATION HALT]' : ''}`);
  lines.push(line2 || 'no changes since last session');
  return { transition: 'print', ok: true, lines };
}
