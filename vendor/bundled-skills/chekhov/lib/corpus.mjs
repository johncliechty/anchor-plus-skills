/** W7's fixed historical corpus and by-hand first-commit recording. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import { commitProject, EXTRACT_PROMPT_HASH } from './commit.mjs';
import { configPath, loadProjectPack } from './pack.mjs';
import { loadLedgerEntries, readCommitState } from './index.mjs';
import { hasAcceptance, serializeSidecar } from './tuples.mjs';
import { runT0, t0ForRoot } from './t0.mjs';
import { scanProse } from './prose.mjs';
import { scanDoctrine } from './doctrine.mjs';
import { buildStructuralRecord } from './structure.mjs';
import { atomicWriteFile, stateDirFor, withLock } from './store.mjs';
import { sha256Text } from './manifest.mjs';
import { AM_INVENTORY } from './inventory.mjs';

const SKILL = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const CORPUS_DIR = path.join(SKILL, 'test', 'fixtures');
export const BH_CAPTURE_FILES = Object.freeze([
  'Rework 2026/Revision/Series_Bible_v4.2_source.md',
  'COMPREHENSIVE_CASCADE_SUMMARY.md', 'CLAUDE.md',
  'Rework 2026/Book_1_Outline_v2_source.md',
]);
export const readHistoricalFixtures = (dir = CORPUS_DIR) => Array.from({ length: 9 }, (_, i) =>
  JSON.parse(fs.readFileSync(path.join(dir, `c3-${String(i + 1).padStart(2, '0')}.json`), 'utf8')));
const writeJSON = (file, value) => atomicWriteFile(file, JSON.stringify(value, null, 2) + '\n');

export function fixtureExpectation(fixture, accepted = []) {
  if (fixture.check !== 'alias') return fixture.expected;
  const alias = accepted.find((t) => fixture.required_ids.includes(t.id));
  return alias?.expected === 'authorial_rename' && alias.authorial_rename === true
    && alias.lock === 'locked' && hasAcceptance(alias) ? 'authorial_rename' : fixture.expected;
}

/** Reconstructed inputs are explicit; this never claims a live recording. */
export function replayHistoricalFixture(fixture, accepted = []) {
  if (fixture.tier === 'T1') return { pending: 'reserved for W9', ok: false };
  const pack = loadProjectPack(CORPUS_DIR);
  const tuples = fixture.input.tuples.map((t) => accepted.find((a) => a.id === t.id) || t);
  const doc = { file: fixture.input.file, text: fixture.input.text, kind: 'doctrine' };
  const result = runT0(pack, tuples.map((tuple) => ({ tuple, sidecar: doc.file + '.ledger.yaml', prose: doc.text })));
  result.prose = scanProse([doc]);
  result.doctrine = scanDoctrine([doc], { tag: fixture.doctrine_tag || pack.name, decisions: [], structural: [] });
  result.structure = buildStructuralRecord({ pack, documents: [doc], tuples, prose: result.prose });
  result.expected = fixtureExpectation(fixture, accepted);
  return result;
}

const recallTargets = (fixtures) => fixtures.flatMap((fixture) => fixture.input.tuples
  .filter((target) => fixture.live_recall_ids?.includes(target.id)).map((target) => ({ fixture, target })));
const sameClaim = (target, tuple) => tuple?.lock === 'candidate' && tuple.source !== 'dialogue'
  && tuple.kind === target.kind && isDeepStrictEqual(tuple.value, target.value)
  && isDeepStrictEqual(tuple.interval, target.interval);
const chapterTarget = (target) => target.kind === 'fact' && target.value.predicate === 'chapter_rule'
  && !target.interval.scope && target.interval.from === target.interval.to;
// Chapter entity names are not canonicalized by the schema. Source + exact
// finite chapter scope + predicate/range identify this target, not its spelling.
const matchesTarget = (target, tuple) => chapterTarget(target)
  ? typeof tuple?.value?.entity === 'string' && tuple.value.entity.length > 0
    && sameClaim({ ...target, value: { ...target.value, entity: tuple.value.entity } }, tuple)
  : sameClaim(target, tuple);
// Bind observed claims after extraction. No historical identifiers or answers
// reach the seat, and an equal claim from another source cannot satisfy recall.
const findCapturedClaim = (entries, fixture, target) => entries.find((entry) => {
  if (entry.sidecar !== fixture.source_file + '.ledger.yaml' || !matchesTarget(target, entry.tuple)) return false;
  if (!chapterTarget(target)) return true;
  const heading = target.receipt.heading_path.at(-1);
  return entry.tuple.receipt.heading_path.some(h => h === heading || h.startsWith(heading + ':'));
});

// A genuine focused recording must still have its original private evidence.
// Ordinary replay checks excerpts; original full-file hashes were verified by
// the operator at capture and are kept distinct from the excerpt hashes.
export function verifyFocusedRecording(recording) {
  try {
    const dir = recording.raw_recording;
    if (typeof dir !== 'string' || !dir) return false;
    const raw = fs.readFileSync(path.join(dir, 'result.json'), 'utf8');
    if (sha256Text(raw) !== recording.raw_output_hash) return false;
    const input = JSON.parse(fs.readFileSync(path.join(dir, 'input.json'), 'utf8'));
    const receipt = JSON.parse(fs.readFileSync(path.join(dir, 'receipt.json'), 'utf8'));
    if (!receipt.ok || !isDeepStrictEqual(receipt, recording.model_receipt)) return false;
    if (sha256Text(fs.readFileSync(path.join(dir, 'prompt.txt'), 'utf8')) !== input.prompt_hash) return false;
    const output = JSON.parse(raw);
    if (output.scenes.length !== input.sources.length) return false;
    for (const source of input.sources) {
      if (sha256Text(source.text) !== source.hash) return false;
      if (!recording.source_hashes.some(s => s.file === source.file && s.sha256 === source.original_sha256)) return false;
      if (output.scenes.filter(s => s.key === source.key).length !== 1) return false;
    }
    return recording.candidates.every(row => input.sources.some(source => {
      if (source.file !== row.source_file) return false;
      const scene = output.scenes.find(s => s.key === source.key);
      return scene.tuples.some(encoded => {
        const tuple = JSON.parse(encoded);
        const {schema, id, kind, value, interval, lock} = tuple;
        return isDeepStrictEqual({schema, id, kind, value, interval, lock}, row.tuple)
          && typeof tuple.receipt?.span === 'string' && tuple.receipt.span.trim()
          && source.text.includes(tuple.receipt.span);
      });
    }));
  } catch { return false; }
}

/** Check the independent BH targets; other histories have their own T0 replay. */
export function extractionRecall(fixtures, recording) {
  const missing = [], mismatched = [];
  for (const { fixture, target } of recallTargets(fixtures)) {
    const row = recording?.candidates?.find((r) => r.target_id === target.id && r.origin === 'bright-heart');
    if (!row) missing.push(target.id);
    else if (row.source_file !== fixture.source_file || !matchesTarget(target, row.tuple)) mismatched.push(target.id);
  }
  // John-approved W7 amendment, 2026-09-11/formal0036-0037: a completed
  // focused supplement proves these independent targets, not the old backlog.
  const focused = recording?.capture === 'coherent-source-supplement'
    && recording.coverage_scope === 'historical-critical-source-passages'
    && recording.model_receipt?.ok === true
    && /^[a-f0-9]{64}$/.test(recording.raw_output_hash || '')
    && Array.isArray(recording.source_hashes) && recording.source_hashes.length > 0
    && recording.source_hashes.every(s => s.file && /^[a-f0-9]{64}$/.test(s.sha256 || ''))
    && verifyFocusedRecording(recording);
  const captured = (recording?.capture === 'john-terminal-live' || focused) && recording.complete === true;
  return { ok: captured && !missing.length && !mismatched.length, missing, mismatched,
    reason: !captured ? 'Missing completed source recording and its provenance.' : null };
}

/** No decisions, including provisional ones, may precede this snapshot. */
export function assertPreDecision(root) {
  if (loadLedgerEntries(root).some((e) => e.tuple.kind === 'decision')
    || (fs.existsSync(path.join(stateDirFor(root), 'DECISIONS.md'))
      && fs.readFileSync(path.join(stateDirFor(root), 'DECISIONS.md'), 'utf8').trim())) {
    throw new Error('Pre-decision snapshot unavailable: a decision entry already exists. Preserve history; do not delete it to manufacture a first recording.');
  }
}

export function freezePreDecision(root, dir, fixture, { remoteVisibility = 'unknown', captured = false } = {}) {
  assertPreDecision(root);
  if (path.resolve(dir) === path.resolve(root) || path.resolve(dir).startsWith(path.resolve(root) + path.sep)) {
    throw new Error('Snapshot must be distinct from the live bible root.');
  }
  const marker = path.join(dir, 'fixture.json');
  if (fs.existsSync(marker) && JSON.parse(fs.readFileSync(marker, 'utf8')).captured) return JSON.parse(fs.readFileSync(marker, 'utf8'));
  const entries = loadLedgerEntries(root);
  const found = fixture.required_ids.map((id) => findCapturedClaim(entries, fixture, fixture.input.tuples.find((t) => t.id === id)));
  if (found.some((e) => !e)) throw new Error(`Missing real capture candidates for snapshot: ${fixture.required_ids.filter((id, i) => !found[i]).join(', ')}`);
  const kind = remoteVisibility === 'private' ? 'real-replay' : 'reconstructed';
  const files = [];
  if (kind === 'real-replay') {
    for (const file of BH_CAPTURE_FILES) {
      const text = fs.readFileSync(path.join(root, file), 'utf8');
      atomicWriteFile(path.join(dir, file), text);
      const rows = entries.filter((e) => e.sidecar === file + '.ledger.yaml').map((e) => e.tuple);
      atomicWriteFile(path.join(dir, file + '.ledger.yaml'), serializeSidecar({ tuples: rows }));
      files.push({ file, sha256: sha256Text(text) });
    }
  } else {
    // Only the independently authored, minimal de-identified text ships.
    // Values must be observed in the real capture before this is called.
    for (let i = 0; i < found.length; i++) if (!isDeepStrictEqual(found[i].tuple.value, fixture.input.tuples[i].value)) throw new Error(`Snapshot claim mismatch: ${found[i].tuple.id}`);
    atomicWriteFile(path.join(dir, 'bible.md'), fixture.input.text);
    atomicWriteFile(path.join(dir, 'bible.md.ledger.yaml'), serializeSidecar({ tuples: fixture.input.tuples }));
    files.push({ file: 'bible.md', sha256: sha256Text(fixture.input.text) });
  }
  atomicWriteFile(configPath(dir), fs.readFileSync(configPath(root), 'utf8'));
  const record = { id: 'fixture-1-pre-decision', kind, criterion: 3, tier: 'T0', source_file: fixture.source_file,
    expected: 'drift', input: 'frozen migrated markdown and candidate sidecars', captured, remote_visibility: remoteVisibility,
    live_root: 'roots.json#bright-heart', snapshot_root: 'test/fixtures/brightheart-pre-decision',
    privacy: kind === 'real-replay' ? 'private-remote-checked' : 'reconstructed-deidentified',
    note: kind === 'real-replay' ? 'Distinct frozen copy; no decision entry existed.' : 'Minimal reconstruction, verified against recorded candidate values; not a copy of the live bible.',
    files, at: new Date().toISOString() };
  writeJSON(marker, record);
  return record;
}

/** Measure the actual named markdown, including I/O and the whole T0 surface. */
export function measureCorpusTiming(roots, journalFile = path.join(SKILL, 'journal', '0003-timing-t0.md')) {
  const figures = [];
  for (const id of ['bright-heart', 'artificial-magi']) {
    const root = roots[id]?.path || roots[id];
    if (!root || !fs.existsSync(root)) throw new Error(`Missing real corpus: ${id}`);
    const start = performance.now();
    const files = id === 'bright-heart' ? BH_CAPTURE_FILES : AM_INVENTORY.map((e) => e.rel);
    const documents = files.map((file) => ({ file, text: fs.readFileSync(path.join(root, file), 'utf8'), kind: 'doctrine' }));
    // An existing project config always wins. For a corpus not configured yet,
    // the explicit timing fixture selects the shipped reference pack as data.
    const packRoot = fs.existsSync(configPath(root)) ? root : path.join(CORPUS_DIR, 'timing', id);
    const pack = loadProjectPack(packRoot);
    const result = t0ForRoot(root, { pack, documents, manuscripts: [] });
    figures.push({ project: id, duration_ms: performance.now() - start, tuple_count: result.tuple_count,
      pack: pack.name, pack_stub: pack.stub === true,
      pack_config: packRoot === root ? `roots.json#${id}/chekhov/config.json` : `test/fixtures/timing/${id}/chekhov/config.json`,
      bytes: documents.reduce((n, d) => n + Buffer.byteLength(d.text), 0),
      files: documents.map((d) => ({ file: d.file, sha256: sha256Text(d.text) })) });
  }
  const report = { at: new Date().toISOString(), kind: 'real-corpus-measurement', figures };
  const reportName = `${report.at.replace(/[:.]/g, '-')}-t0-corpus.json`;
  writeJSON(path.join(path.dirname(journalFile), 'runs', reportName), report);
  const measured = figures.map(row => `${row.project}: ${row.duration_ms.toFixed(1)} ms`).join('; ');
  atomicWriteFile(journalFile, '# T0 timing on the real corpora\n\n'
    + `Measured ${report.at}: ${measured}.\n\n`
    + 'Includes reads, index, prose, doctrine, structure and intake checks on the named markdown; excludes manuscript capture. '
    + 'The record identifies the actual pack configuration, including any reference stub.\n\n'
    + 'These measurements do not establish manuscript coverage or W7 completion.\n\n'
    + `[Full measurements and source hashes](runs/${reportName})\n`);
  return report;
}

/** One supported by-hand command; each invocation processes at most 20 scenes. */
export async function recordFirstCommit(root, opts = {}) {
  const batchSize = opts.batchSize === undefined ? 20 : opts.batchSize;
  if (!Number.isSafeInteger(batchSize) || batchSize < 1 || batchSize > 20) return { ok: false, status: 2,
    lines: ['batchSize must be a safe integer from 1 to 20.'] };
  if (!(process.stdin.isTTY === true && process.stdout.isTTY === true)) return { ok: false, status: 3,
    lines: ['Missing real capture: W7 requires John at a terminal. No extraction or decisions were performed.'] };
  const fixturesDir = opts.fixturesDir || CORPUS_DIR;
  const fixtures = readHistoricalFixtures(fixturesDir);
  const dir = path.join(fixturesDir, 'recorded', 'bh-first-commit');
  const privateDir = path.join(stateDirFor(root), 'recordings', 'bh-first-commit');
  const rawFile = path.join(privateDir, 'extractor.json');
  const startFile = path.join(privateDir, 'start.json');
  try {
    assertPreDecision(root);
    const targetsHash = sha256Text(JSON.stringify(fixtures));
    let start;
    if (fs.existsSync(startFile)) {
      start = JSON.parse(fs.readFileSync(startFile, 'utf8'));
      if (start.targets_hash !== targetsHash || start.prompt_hash !== EXTRACT_PROMPT_HASH) throw new Error('Historical targets or fixed prompt changed during capture; preserve the old recording for review.');
    } else {
      if (Object.keys(readCommitState(root).completed).length) throw new Error('First recording is missing but commit state is already populated; cannot relabel an earlier unrecorded commit.');
      start = { at: new Date().toISOString(), targets_hash: targetsHash, prompt_hash: EXTRACT_PROMPT_HASH,
        files: BH_CAPTURE_FILES.map((file) => ({ file, sha256: sha256Text(fs.readFileSync(path.join(root, file), 'utf8')) })) };
      writeJSON(startFile, start);
    }
    for (const row of start.files) if (row.sha256 !== sha256Text(fs.readFileSync(path.join(root, row.file), 'utf8'))) throw new Error(`First-recording source changed: ${row.file}; preserve the partial capture for review.`);
    const out = await commitProject(root, { live: true, preDecision: true, batchSize, files: BH_CAPTURE_FILES,
      recordFile: rawFile, createSession: opts.createSession });
    if (!out.ok) return out;
    const lines = [...out.lines];
    const candidates = [];
    const recorded = JSON.parse(fs.readFileSync(rawFile, 'utf8'));
    const entries = loadLedgerEntries(root).filter((entry) => recorded.scenes.some((scene) =>
      entry.sidecar === scene.file + '.ledger.yaml' && scene.tuples.some((tuple) =>
        tuple.id === entry.tuple.id && sameClaim(entry.tuple, tuple))));
    for (const { fixture, target } of recallTargets(fixtures)) {
      const entry = findCapturedClaim(entries, fixture, target);
      if (!entry) continue;
      // Copy the observed fields after matching, not expected answers. Keep the
      // raw receipt private and retain its hash in this minimal exported view.
      const { schema, id, kind, value, interval, lock } = entry.tuple;
      candidates.push({ target_id: target.id, origin: 'bright-heart', source_file: fixture.source_file,
        tuple: { schema, id, kind, value, interval, lock },
        observed_receipt_hash: sha256Text(JSON.stringify(entry.tuple.receipt)) });
    }
    const complete = out.backlog === 0;
    const exportRaw = opts.remoteVisibility === 'private' && complete;
    const record = { schema: 1, id: 'bh-first-commit', kind: exportRaw ? 'real-replay' : 'reconstructed', capture: 'john-terminal-live',
      source_file: 'roots.json#bright-heart', tier: 'T0', criterion: 3, expected: 'pre-authored Bright-Heart live targets recalled',
      input: 'Phase-1 BH bible, cascade summary, CLAUDE.md and Outline v2',
      privacy: exportRaw ? 'private-remote-checked' : 'reconstructed-deidentified', raw_kind: 'real-replay',
      raw_recording: 'roots.json#bright-heart/chekhov/recordings/bh-first-commit/extractor.json',
      note: 'Minimal exported candidate view of actual terminal output, bound to independent targets after extraction. No acceptance implied.',
      started: start.at, updated: new Date().toISOString(), targets_hash: targetsHash, prompt_hash: EXTRACT_PROMPT_HASH,
      backlog: { bright_heart: out.backlog }, complete, candidates };
    writeJSON(path.join(dir, 'fixture.json'), record);
    if (exportRaw) {
      // Only a W1 private-remote receipt permits full raw prose-bearing output.
      atomicWriteFile(path.join(dir, 'extractor.json'), fs.readFileSync(rawFile, 'utf8'));
    }
    writeJSON(path.join(privateDir, 'backlog.json'), { at: record.updated, ...record.backlog, candidates: readCommitState(root).candidates.length });
    if (complete) {
      const recall = extractionRecall(fixtures, record);
      // Persist the failed recording before any snapshot prerequisite can refuse.
      // The book-count pair alone is sufficient to freeze fixture #1.
      const snapshotRecall = extractionRecall([fixtures[0]], record);
      if (snapshotRecall.ok) withLock(stateDirFor(root), undefined, () => freezePreDecision(root,
        path.join(fixturesDir, 'brightheart-pre-decision'), fixtures[0], { remoteVisibility: opts.remoteVisibility, captured: true }));
      lines.push(recall.ok ? 'Recording complete; all Bright-Heart live targets recalled.' : `Recall failed: missing ${recall.missing.join(', ')}; mismatched ${recall.mismatched.join(', ')}. Preserve this recording; do not manufacture entries.`);
      if (opts.roots) measureCorpusTiming(opts.roots);
      return { ok: recall.ok, status: recall.ok ? 0 : 1, lines, recording: record, recall };
    }
    lines.push(`Recording saved; backlog BH=${out.backlog}. Run the same command for the next batch. No interview is needed.`);
    return { ok: true, status: 0, lines, recording: record };
  } catch (error) { return { ok: false, status: 1, lines: [error.message] }; }
}
