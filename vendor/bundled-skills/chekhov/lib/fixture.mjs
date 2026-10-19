/**
 * Fixture record format (criterion 3) — W1.
 *
 * ONE JSON shape for verdicts and fixtures:
 *   { id, kind: 'real-replay' | 'reconstructed', source_file, tier: 'T0'|'T1',
 *     criterion, input, expected, recorded_seat_output?, timing? }
 *
 * `chekhov fixture promote <verdict-id>` writes test/fixtures/<id>.json.
 * `chekhov fixture report` counts the two kinds SEPARATELY (the criterion-3
 * report skeleton). Privacy scaffold: when the foundry remote is not known to
 * be private, every promoted fixture is labelled reconstructed-deidentified.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadLedgerEntries, verdictData, entriesForUnit } from './index.mjs';
import { buildT1Packet, t1SourcePath } from './t1.mjs';
import { loadProjectPack } from './pack.mjs';
import { hasAcceptance } from './tuples.mjs';

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_FIXTURES_DIR = path.join(LIB_DIR, '..', 'test', 'fixtures');

export const FIXTURE_KINDS = Object.freeze(['real-replay', 'reconstructed']);
export const FIXTURE_TIERS = Object.freeze(['T0', 'T1']);
export const KIND_REQUIRED_MESSAGE = 'kind required: real-replay | reconstructed';

export function fixtureFromLog(root, id, { kind } = {}) {
  const record = verdictData(root).verdicts.find((r) => r.id === id && r.t0);
  if (!record) throw new Error(`verdict not found: ${id}`);
  if (record.judge_required) {
    if (!record.t1?.response_json || !record.t1?.packet_hash) throw new Error('missing recorded T1 response');
    if (kind === 'real-replay' && (record.t1.mode !== 'live' || record.t1.seats?.judge?.mode === 'synthetic')) throw new Error('real-replay requires an actual live recording');
    if (kind === 'reconstructed' && record.t1.response_kind === 'real-replay') throw new Error('A live private-source response cannot be relabelled reconstructed; author a separate synthetic fixture.');
    const config = JSON.parse(fs.readFileSync(path.join(root, 'chekhov/config.json'), 'utf8'));
    const entries = entriesForUnit(loadLedgerEntries(root), config, record.unit || config.active_unit, id);
    const current = buildT1Packet(root, { pack: loadProjectPack(root), entries }, record, record.source_selections);
    if (current.hash !== record.t1.packet_hash) throw new Error('source changed since recording; preserve the earlier log and snapshot');
    const relevant = entries.filter((e) => record.t1.packet.entries.some((r) => r.entry_id === e.tuple.id));
    const files = [...new Set([...record.t1.packet.entries.map((e) => e.source.file), ...record.t1.packet.sources.map((s) => s.file)])];
    const snapshot = { files: files.map((file) => ({ file, text: fs.readFileSync(t1SourcePath(root, file), 'utf8') })),
      entries: relevant.map(({ tuple, sidecar, verdict_id }) => ({ tuple, sidecar, ...(verdict_id ? { verdict_id } : {}) })) };
    return { schema: 1, id, kind, project: record.project, unit: record.unit, pack: config.pack,
      shared_story_world: config.shared_story_world, source_file: 'chekhov/VERDICTS.md', tier: 'T1', criterion: 2,
      input: { raw_line: record.raw_line, extraction: record.extraction, scope_override: record.scope_override, sources: record.source_selections || [] },
      expected: record.final.verdict, typing_fallback: record.typing_fallback || null,
      recorded_seat_output: record.t1.response_json, response_encoding: record.t1.response_encoding,
      packet: record.t1.packet, packet_hash: record.t1.packet_hash, snapshot, required_cites: record.t1.rows,
      timing: record.timings, seats: record.seats, line_hash: record.line_hash, recorded_at: record.at };
  }
  return { id, kind, source_file: 'chekhov/VERDICTS.md', tier: 'T0', criterion: 2,
    input: record.raw_line, expected: record.t0.verdict, recorded_seat_output: record.extraction,
    timing: record.timings, seats: record.seats, line_hash: record.line_hash };
}

/** Validate one record → list of problems (empty = valid). */
export function validateFixtureRecord(rec) {
  const problems = [];
  if (!rec || typeof rec !== 'object') return ['record is not an object'];
  if (!rec.id || typeof rec.id !== 'string') problems.push('id required');
  if (!FIXTURE_KINDS.includes(rec.kind)) problems.push(KIND_REQUIRED_MESSAGE);
  if (!rec.source_file || typeof rec.source_file !== 'string') problems.push('source_file required');
  if (!FIXTURE_TIERS.includes(rec.tier)) problems.push('tier required: T0 | T1');
  if (rec.criterion === undefined || rec.criterion === null) problems.push('criterion required');
  if (!('input' in rec)) problems.push('input required');
  if (!('expected' in rec)) problems.push('expected required');
  return problems;
}

/**
 * Promote a verdict record to a fixture file. REFUSES (writes nothing) on any
 * validation problem — a missing kind is named with KIND_REQUIRED_MESSAGE.
 * `remoteVisibility` !== 'private' ⇒ the fixture carries
 * privacy: 'reconstructed-deidentified'.
 */
export function promoteVerdict(verdict, opts = {}) {
  const problems = validateFixtureRecord(verdict);
  if (problems.length) {
    return { ok: false, refused: true, problems, wrote: null };
  }
  const dir = opts.fixturesDir || DEFAULT_FIXTURES_DIR;
  const record = { ...verdict };
  if (record.tier === 'T1' && record.kind === 'real-replay' && opts.remoteVisibility !== 'private') {
    return { ok: false, refused: true, problems: ['Private-source T1 recording stays in the project; a public reconstruction must be authored separately.'], wrote: null };
  }
  if (opts.remoteVisibility !== 'private') {
    record.privacy = 'reconstructed-deidentified';
  }
  fs.mkdirSync(dir, { recursive: true });
  const target = path.join(dir, `${record.id}.json`);
  fs.writeFileSync(target, `${JSON.stringify(record, null, 2)}\n`, 'utf8');
  return { ok: true, wrote: target, record };
}

/** Count the two kinds SEPARATELY over a fixtures dir (criterion-3 skeleton). */
export function fixtureReport(fixturesDir = DEFAULT_FIXTURES_DIR, { acceptanceRoot } = {}) {
  const counts = { 'real-replay': 0, reconstructed: 0 };
  const invalid = [];
  const files = [], fixtures = [];
  const accepted = acceptanceRoot && fs.existsSync(acceptanceRoot) ? loadLedgerEntries(acceptanceRoot).map((e) => e.tuple) : [];
  const walk = (dir) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (entry.name.endsWith('.json')) files.push(path.relative(fixturesDir, file).replace(/\\/g, '/'));
    }
  };
  walk(fixturesDir);
  for (const f of files) {
    try {
      const rec = JSON.parse(fs.readFileSync(path.join(fixturesDir, f), 'utf8'));
      if (!rec.id && !rec.criterion) continue; // configs and raw scene payloads are not fixtures
      if (validateFixtureRecord(rec).length) { invalid.push(f); continue; }
      counts[rec.kind] += 1;
      const alias = accepted.find((t) => rec.required_ids?.includes(t.id) && t.kind === 'alias'
        && t.authorial_rename === true && t.expected === 'authorial_rename' && t.lock === 'locked' && hasAcceptance(t));
      fixtures.push({ id: rec.id, file: f, criterion: rec.criterion, tier: rec.tier, kind: rec.kind,
        expected: alias ? alias.expected : rec.expected, captured: rec.captured ?? null });
    } catch {
      invalid.push(f);
    }
  }
  return {
    schema: 'chekhov-fixture-report-v1',
    counts,
    total: counts['real-replay'] + counts.reconstructed,
    invalid,
    fixtures,
  };
}
