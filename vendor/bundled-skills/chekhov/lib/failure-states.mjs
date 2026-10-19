/**
 * Shared five-row failure-state table (W3; ChatGPT BLOCKER 1 put the gate ids
 * in test/w03-ledger.test.mjs).
 *
 * Every surface lists the SAME five rows — dependency-missing,
 * dependency-slow-or-killed, dependency-returns-garbage,
 * backing-store-unreadable, empty-but-valid — each with a status code AND the
 * user-visible text. "Unknown" (garbage that does not parse) and "empty"
 * (present, valid, holding nothing) are DIFFERENT rows with different codes:
 * empty is a valid state, never an error.
 */

/** The closed row set. Order is the display order. */
export const FAILURE_ROWS = Object.freeze([
  'dependency-missing',
  'dependency-slow-or-killed',
  'dependency-returns-garbage',
  'backing-store-unreadable',
  'empty-but-valid',
]);

/** One status code per row, shared across surfaces (0 = not an error). */
export const ROW_STATUS = Object.freeze({
  'dependency-missing': 3,
  'dependency-slow-or-killed': 4,
  'dependency-returns-garbage': 5,
  'backing-store-unreadable': 6,
  'empty-but-valid': 0,
});

/** Every surface this plan asserts, with what its dependency and store are. */
const SURFACES = Object.freeze({
  store: { dep: 'the root lock and the target file', backing: 'the durable file being written or read' },
  'index-read': { dep: 'the rebuilt ledger.json', backing: 'ledger.json' },
  'index-write': { dep: 'the parsed sidecar tuples', backing: 'ledger.json' },
  rebuild: { dep: 'the sidecar ledger files', backing: 'the sidecar ledger files' },
  lint: { dep: 'the project pack and the ledger', backing: 'the bible markdown' },
  status: { dep: 'the rebuilt ledger and the session receipts', backing: 'STATUS.json' },
  brief: { dep: 'the status record', backing: 'STATUS.json' },
  accept: { dep: 'the decision record entry being walked', backing: 'the sidecar ledger files' },
  idea: { dep: 'the pack catalog and the alias trie', backing: 'the verdict log' },
  commit: { dep: 'the changed scene text and the pack catalog', backing: 'the sidecar ledger files' },
  'pack-enable': { dep: 'chekhov/config.json and the named pack', backing: 'chekhov/config.json' },
  render: { dep: 'the provenance-tagged markdown', backing: 'the rendered docx' },
  lock: { dep: 'the lock-event corpus and the seat replies', backing: 'the lock receipt' },
});

function rowText(surface, row) {
  const s = SURFACES[surface];
  switch (row) {
    case 'dependency-missing':
      return `${surface}: ${s.dep} is missing — nothing was read or written; provide it and rerun.`;
    case 'dependency-slow-or-killed':
      return `${surface}: ${s.dep} did not answer in time or was killed — the step stopped without a partial write; rerun when it is back.`;
    case 'dependency-returns-garbage':
      return `${surface}: ${s.dep} returned data that does not parse (unknown shape) — refused, never guessed; the input is quoted in the journal.`;
    case 'backing-store-unreadable':
      return `${surface}: ${s.backing} exists but cannot be read — nothing was overwritten; fix the file or restore it and rerun.`;
    case 'empty-but-valid':
      return `${surface}: ${s.backing} is present and empty — a valid state, not an error; there is simply nothing here yet.`;
    default:
      throw new Error(`unknown failure row: ${row}`);
  }
}

function buildTable() {
  const table = {};
  for (const surface of Object.keys(SURFACES)) {
    const rows = {};
    for (const row of FAILURE_ROWS) {
      rows[row] = Object.freeze({ status: ROW_STATUS[row], text: rowText(surface, row) });
    }
    table[surface] = Object.freeze(rows);
  }
  return Object.freeze(table);
}

/** surface → row → { status, text }. The single source every surface prints from. */
export const FAILURE_STATES = buildTable();

export const FAILURE_SURFACES = Object.freeze(Object.keys(SURFACES));

/** The row for a surface, refusing unknown names (never guesses). */
export function failureRow(surface, row) {
  const s = FAILURE_STATES[surface];
  if (!s) throw new Error(`unknown failure surface: ${surface}`);
  const r = s[row];
  if (!r) throw new Error(`unknown failure row: ${row}`);
  return r;
}
