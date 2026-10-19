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

/** Collection membership does not make unrelated stories one fictional world. */
export function entriesForUnit(entries, config, unit, excludedVerdict) {
  return entries.filter(entry => {
    if (excludedVerdict && entry.verdict_id === excludedVerdict) return false;
    const tuple = entry.tuple;
    const explicit = tuple.unit || tuple.receipt?.unit || tuple.source?.unit;
    if (!unit) return true;
    if (explicit) return explicit === unit;
    if (config.shared_story_world !== false) return true;
    if (entry.unit) return entry.unit === unit;
    const units = tuple.value?.context?.proposed_units;
    if (!Array.isArray(units)) return false;
    if (units.includes(unit)) return true;
    return tuple.kind === 'decision' && units.includes('Collection')
      && /(?:^|[._-])(?:theme|structure)(?:[._-]|$)/.test(tuple.id);
  });
}

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

function ledgerSourceWithin(base, candidate) {
  const relative = path.relative(base, candidate);
  return relative === '' || (relative !== '..'
    && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative));
}

function configuredLedgerSourceDirectories(root) {
  let configText;
  try {
    configText = fs.readFileSync(path.join(root, 'chekhov', 'config.json'), 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  const config = JSON.parse(configText.replace(/^\uFEFF/, ''));
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('config.json must be an object to select ledger_sources');
  }
  if (!Object.hasOwn(config, 'ledger_sources')) return null;
  if (!Array.isArray(config.ledger_sources) || config.ledger_sources.length === 0) {
    throw new Error('ledger_sources must be a nonempty array of relative directories');
  }
  const rootPath = path.resolve(root);
  const realRoot = fs.realpathSync(rootPath);
  const selected = [];
  for (const entry of config.ledger_sources) {
    if (typeof entry !== 'string' || entry.trim().length === 0
      || path.isAbsolute(entry) || path.win32.isAbsolute(entry)
      || /^[A-Za-z]:/.test(entry)) {
      throw new Error('ledger_sources entries must be relative directory paths');
    }
    const sourcePath = path.resolve(rootPath, entry);
    if (!ledgerSourceWithin(rootPath, sourcePath)) {
      throw new Error('ledger_sources directory is outside the project root: ' + entry);
    }
    let real;
    try {
      real = fs.realpathSync(sourcePath);
      if (!fs.statSync(real).isDirectory()) throw new Error('not a directory');
    } catch (error) {
      throw new Error('ledger_sources requires an existing directory: ' + entry + ' (' + error.message + ')');
    }
    if (!ledgerSourceWithin(realRoot, real)) {
      throw new Error('ledger_sources resolves outside the project root: ' + entry);
    }
    if (selected.some(previous => ledgerSourceWithin(previous.path, sourcePath)
      || ledgerSourceWithin(sourcePath, previous.path)
      || ledgerSourceWithin(previous.real, real) || ledgerSourceWithin(real, previous.real))) {
      throw new Error('ledger_sources directories must not duplicate or overlap: ' + entry);
    }
    selected.push({ path: sourcePath, real });
  }
  return selected.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
}

function findSelectedSidecars(root, selected) {
  const found = [];
  const directories = new Set();
  const sidecars = new Set();
  const realKey = value => process.platform === 'win32' ? value.toLowerCase() : value;
  const walk = (dir, boundary) => {
    const realDir = fs.realpathSync(dir);
    if (!ledgerSourceWithin(boundary, realDir)) {
      throw new Error('ledger_sources directory link escapes its selected directory: ' + dir);
    }
    if (directories.has(realKey(realDir))) {
      throw new Error('ledger_sources repeats a directory through a link: ' + dir);
    }
    directories.add(realKey(realDir));
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0)) {
      if (SKIP_DIRS.has(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (!entry.isDirectory() && !entry.isSymbolicLink() && !entry.name.endsWith(SIDECAR_SUFFIX)) continue;
      const real = fs.realpathSync(full);
      if (!ledgerSourceWithin(boundary, real)) {
        throw new Error('ledger_sources entry resolves outside its selected directory: ' + full);
      }
      const stat = fs.statSync(real);
      if (stat.isDirectory()) {
        walk(full, boundary);
      } else if (stat.isFile() && entry.name.endsWith(SIDECAR_SUFFIX)) {
        if (sidecars.has(realKey(real))) {
          throw new Error('ledger_sources repeats a sidecar through a link: ' + full);
        }
        sidecars.add(realKey(real));
        found.push(full);
      }
    }
  };
  for (const source of selected) walk(source.path, source.real);
  return found.sort((a, b) => {
    const left = path.relative(root, a), right = path.relative(root, b);
    return left < right ? -1 : left > right ? 1 : 0;
  });
}

/** Exact files written by this engine stay visible after their review queue clears. */
function committedSourceFiles(root, state = readCommitState(root)) {
  const files = state.source_files ?? [];
  if (!Array.isArray(files)) throw new Error('commit source_files must be an array');
  const base = fs.realpathSync(root);
  return files.map(file => {
    if (typeof file !== 'string' || !file || path.isAbsolute(file) || path.win32.isAbsolute(file)
      || file.includes(':') || file.split(/[\\/]/).some(p => !p || p === '..' || p === '.')) {
      throw new Error('commit source_files requires contained relative prose paths');
    }
    const prose = path.resolve(base, file), sidecar = prose + SIDECAR_SUFFIX;
    for (const target of [prose, sidecar]) {
      if (!ledgerSourceWithin(base, fs.realpathSync(target)) || !fs.statSync(target).isFile()) {
        throw new Error('commit source_files escapes project or is not a file');
      }
      let at = base;
      for (const part of path.relative(base, target).split(path.sep)) {
        at = path.join(at, part);
        if (fs.lstatSync(at).isSymbolicLink()) throw new Error('commit source_files linked path refused');
      }
    }
    return { file: file.replace(/\\/g, '/'), sidecar };
  });
}

/** Validate once for one discovery pass; callers rebuild this under their write lock. */
export function createLedgerSourceSelector(root, state) {
  const selected = configuredLedgerSourceDirectories(root);
  if (selected === null) return () => true;
  const registered = new Set(committedSourceFiles(root, state).map(row => row.file));
  return file => {
    const normalized = file.replace(/\\/g, '/');
    if (registered.has(normalized)) return true;
    const target = path.resolve(root, file);
    return selected.some(source => ledgerSourceWithin(source.path, target)
      && ledgerSourceWithin(source.real, fs.realpathSync(target)));
  };
}

/** Fresh standalone lookup; scope never silently activates history. */
export function ledgerSourceSelected(root, file) {
  return createLedgerSourceSelector(root)(file);
}

/** Selected source sidecars, or the legacy recursive walk when selection is absent. */
export function findSidecars(root) {
  const selected = configuredLedgerSourceDirectories(root);
  if (selected !== null) {
    const found = [...findSelectedSidecars(root, selected), ...committedSourceFiles(root).map(row => row.sidecar)];
    // Author decisions have their existing canonical engine-owned location.
    const decisions = path.join(root, 'chekhov', 'DECISIONS.md.ledger.yaml');
    if (fs.existsSync(decisions)) {
      const real = fs.realpathSync(decisions);
      if (!ledgerSourceWithin(fs.realpathSync(root), real) || fs.lstatSync(decisions).isSymbolicLink()) {
        throw new Error('linked author decision sidecar refused');
      }
      found.push(decisions);
    }
    return [...new Set(found.map(file => path.resolve(file)))].sort();
  }
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
  const verdicts = new Map();
  const answered = new Set();
  for (const record of records) {
    const id = record.verdict_id || record.id;
    if (record.type === 'addendum') {
      const previous = verdicts.get(id);
      if (!previous) throw new Error(`addendum has no verdict: ${id}`);
      verdicts.set(id, { ...previous, ...record, id, type: 'verdict', raw_line: previous.raw_line,
        line_hash: previous.line_hash, at: previous.at });
      if (Array.isArray(record.candidates)) for (const [key, row] of rows) {
        if (row.verdict_id === id && !answered.has(key) && !row.decision_ask) rows.delete(key);
      }
    } else if (record.type !== 'candidate-action' && record.type !== 'decision-ask' && record.id) {
      if (verdicts.has(id)) throw new Error(`duplicate verdict: ${id}`);
      verdicts.set(id, record);
    }
    for (const tuple of record.candidates || []) if (!answered.has(tuple.id)) rows.set(tuple.id, { tuple, sidecar,
      prose: verdicts.get(id)?.raw_line ?? record.raw_line ?? record.raw ?? '', verdict_id: id,
      ...(verdicts.get(id)?.unit ? { unit: verdicts.get(id).unit } : {}),
      ...(record.type === 'decision-ask' ? { decision_ask: true } : {}) });
    if (record.type === 'candidate-action' && rows.has(record.candidate_id)) {
      answered.add(record.candidate_id);
      if (record.action === 'reject') rows.delete(record.candidate_id);
      else if (record.tuple) rows.set(record.candidate_id, { ...rows.get(record.candidate_id), tuple: record.tuple });
    }
  }
  return { records, entries: [...rows.values()], verdicts: [...verdicts.values()] };
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
    } else if (tuple.kind === 'thread' && !tuple.interval.scope) {
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
    if (tuple.unit) row.unit = tuple.unit;
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
