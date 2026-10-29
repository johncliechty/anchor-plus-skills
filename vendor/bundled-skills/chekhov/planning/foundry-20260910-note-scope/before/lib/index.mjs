/**
 * The rebuilt ledger index (W3). <root>/chekhov/ledger.json is REBUILT every
 * run from the sidecar tuples (and, from W8, the verdict log), indexed by
 * entity so interval overlap is per entity. It is never hand-edited: a hand
 * edit is simply overwritten on rebuild, and two consecutive rebuilds of the
 * same files are byte-identical (no timestamps, sorted keys).
 *
 * depends_on producers — EXACTLY three:
 *   1. entities named inside a fact's receipt span at commit (alias trie);
 *   2. a decision entry's governs list, written by John at the ask;
 *   3. thread plant/pay scenes.
 * cost_of_change = size of that closure. A hand-entered depends_on on a fact
 * or a hand-entered cost_of_change is IGNORED — the index recomputes both.
 */
import fs from 'node:fs';
import path from 'node:path';
import { atomicWriteFile, stateDirFor, withLock, readRecords } from './store.mjs';
import { loadProjectPack } from './pack.mjs';
import { buildAliasTrie, hasAcceptance, hasMintedFields, namedEntitiesInSpan, readSidecar } from './tuples.mjs';

export const LEDGER_SCHEMA = 'chekhov-ledger-v1';
const SIDECAR_SUFFIX = '.ledger.yaml';
const SKIP_DIRS = new Set(['.git', 'node_modules']);

export function ledgerPath(stateDir) {
  return path.join(stateDir, 'ledger.json');
}

export function readCommitState(root) {
  const file = path.join(stateDirFor(root), 'commit.json');
  if (!fs.existsSync(file)) return { schema: 1, completed: {}, candidates: [], backlog: 0 };
  const state = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (state.schema !== 1 || !state.completed || !Array.isArray(state.candidates)) throw new Error('invalid commit state');
  return state;
}

/** Every sidecar under the root, sorted by relative path (deterministic walk). */
export function findSidecars(root) {
  const found = [];
  const walk = (dir) => {
    let names;
    try {
      names = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of names.sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name)) walk(full);
      } else if (entry.name.endsWith(SIDECAR_SUFFIX)) {
        found.push(full);
      }
    }
  };
  walk(root);
  return found;
}

/** W6 queue seam for W8's single append-only idea-candidate store. */
export function verdictData(root) {
  const sidecar = 'chekhov/VERDICTS.md';
  const records = readRecords(path.join(root, sidecar));
  const rows = new Map();
  for (const record of records) {
    for (const tuple of record.candidates || []) rows.set(tuple.id, { tuple, sidecar,
      prose: record.raw_line ?? record.raw ?? '', verdict_id: record.id });
    if (record.type === 'candidate-action' && rows.has(record.candidate_id)) {
      if (record.action === 'reject') rows.delete(record.candidate_id);
      else if (record.tuple) rows.set(record.candidate_id, { ...rows.get(record.candidate_id), tuple: record.tuple });
    }
  }
  return { records, entries: [...rows.values()] };
}

export function loadLedgerEntries(root) {
  const entries = [];
  for (const file of findSidecars(root)) {
    const proseFile = file.slice(0, -SIDECAR_SUFFIX.length);
    const sidecar = path.relative(root, file).split(path.sep).join('/');
    const prose = fs.existsSync(proseFile) ? fs.readFileSync(proseFile, 'utf8') : null;
    for (const tuple of readSidecar(proseFile).tuples) entries.push({ tuple, sidecar,
      prose: tuple.authored_by === 'john' && tuple.receipt.source === 'john-terminal' && hasAcceptance(tuple) ? tuple.receipt.span : prose });
  }
  return [...entries, ...verdictData(root).entries];
}

function entityFor(tuple) {
  if (tuple.kind === 'fact') return tuple.value.entity;
  if (tuple.kind === 'alias') return tuple.value.target;
  return tuple.id;
}

function sortedObject(map) {
  const out = {};
  for (const key of Object.keys(map).sort()) out[key] = map[key];
  return out;
}

/** Build the ledger object from tuples (pure; no I/O). */
export function buildLedger(pack, tuplesWithOrigin) {
  const trie = buildAliasTrie(tuplesWithOrigin.map((x) => x.tuple));

  const tuples = {};
  const entities = {};
  const edges = new Map(); // dep id -> Set(dependent ids), the ripple direction

  const addEdge = (from, to) => {
    if (!edges.has(from)) edges.set(from, new Set());
    edges.get(from).add(to);
  };

  for (const { tuple, sidecar } of tuplesWithOrigin) {
    if (tuples[tuple.id]) throw new Error(`duplicate tuple id across sidecars: ${tuple.id}`);

    // Locked with no acceptance receipt — or allow_terms smuggled in without
    // one (W4 minted class) — is indexed at rung candidate and carries a
    // minted flag for the T0 report: no hand edit or extractor can lock canon.
    const minted = hasMintedFields(tuple);
    const lock = minted ? 'candidate' : tuple.lock;

    // The three producers — and ONLY the three. A hand-entered depends_on on
    // a fact/thread/structural tuple never survives the rebuild.
    let depends_on = [];
    if (tuple.kind === 'fact') {
      depends_on = namedEntitiesInSpan(trie, tuple.receipt.span, tuple.interval);
    } else if (tuple.kind === 'decision') {
      depends_on = [...(tuple.governs || [])].sort();
    } else if (tuple.kind === 'thread') {
      depends_on = [tuple.value.plant, tuple.value.pay].filter(Boolean).map((scene) => `scene.${scene}`).sort();
    }

    for (const dep of depends_on) {
      if (tuple.kind === 'decision') addEdge(tuple.id, dep);
      else addEdge(dep, tuple.id);
    }

    const entity = entityFor(tuple);
    if (!entities[entity]) entities[entity] = [];
    entities[entity].push(tuple.id);

    const row = { kind: tuple.kind, entity, value: tuple.value, interval: tuple.interval, lock };
    if (minted) row.minted = true;
    row.receipt = tuple.receipt;
    row.sidecar = sidecar;
    row.depends_on = depends_on;
    tuples[tuple.id] = row;
  }

  // cost_of_change = size of the ripple closure from this id (self excluded).
  // A hand-entered cost_of_change was never read.
  for (const [id, row] of Object.entries(tuples)) {
    const seen = new Set([id]);
    const queue = [id];
    // A decision ripples INTO its governs list too, so seed from depends_on
    // edges already carries it (decision edges point outward).
    while (queue.length) {
      const cur = queue.pop();
      for (const next of edges.get(cur) || []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
    row.cost_of_change = seen.size - 1;
  }

  for (const key of Object.keys(entities)) entities[key].sort();

  return {
    schema: LEDGER_SCHEMA,
    pack: pack.name,
    entities: sortedObject(entities),
    tuples: sortedObject(tuples),
  };
}

/**
 * Rebuild <root>/chekhov/ledger.json from every sidecar under the root.
 * Overwrites whatever is there — including a hand edit — atomically, under
 * the root lock. Byte-identical across runs on the same inputs.
 */
export function rebuildIndex(root, { stateDir, packsDir, lockOpts } = {}) {
  const dir = stateDirFor(root, stateDir);
  const pack = loadProjectPack(root, { packsDir });
  const target = ledgerPath(dir);
  return withLock(dir, lockOpts, () => {
    const ledger = buildLedger(pack, loadLedgerEntries(root));
    const text = `${JSON.stringify(ledger, null, 2)}\n`;
    atomicWriteFile(target, text);
    return { path: target, ledger, text };
  });
}
