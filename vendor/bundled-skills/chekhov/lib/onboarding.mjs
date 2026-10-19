/** Coherent recorded reading -> the existing commit replay format; never writes a ledger. */
import assert from 'node:assert/strict';
import {scenesOf, prepareCandidate} from './commit.mjs';
import {sha256Text} from './manifest.mjs';

const fields = new Set(['id','kind','entity','predicate','object','source_id','start_line','end_line',
  'source_role','planned_units','related_ids','note']);

/** Sources and receipt come from the operator's frozen recording, not from proposed claims. */
export function projectOnboardingRecording({sources, records, recording, pack, date}) {
  assert(Array.isArray(sources) && sources.length && Array.isArray(records), 'Sources and records are required');
  const interrupted = recording?.receipt?.ok === false && recording.receipt.error?.code === 'timeout' &&
    recording.durable_partial?.unreviewed === true && Array.isArray(recording.raw_outputs) &&
    recording.raw_outputs.length > 0 && recording.raw_outputs.every(x => x.file && /^[a-f0-9]{64}$/.test(x.sha256));
  assert(recording?.prompt_hash && (recording?.receipt?.ok === true || interrupted),
    'Successful reading receipt or explicitly unreviewed durable timeout output required');
  const sourceMap = new Map(), sourceFiles = new Set(), rows = [], ids = new Set();
  const recordedIds = new Set(records.map(record => record?.id));
  for (const source of sources) {
    assert(source.id && !sourceMap.has(source.id), 'Duplicate or missing source id');
    assert(typeof source.text === 'string' && sha256Text(source.text) === source.normalized_excerpt_sha256,
      `Frozen source hash mismatch: ${source.id}`);
    assert(Number.isSafeInteger(source.from) && source.from > 0 &&
      source.to === source.from + source.text.split('\n').length - 1, `Source bounds mismatch: ${source.id}`);
    assert(source.file && source.pilot_file && source.role && source.original_sha256, 'Source provenance missing');
    assert(!sourceFiles.has(source.pilot_file), 'Each frozen excerpt needs its own source-copy path');
    sourceFiles.add(source.pilot_file);
    const scenes = scenesOf({file: source.pilot_file, text: source.text});
    const projected = scenes.map(scene => ({file: scene.file, heading_path: scene.heading_path,
      line: scene.line, source_hash: scene.hash, tuples: [], receipt: {
        mode: 'coherent-source-recording', ...recording,
        original_source: {file: source.file, sha256: source.original_sha256,
          from: source.from, to: source.to, role: source.role,
          ...(source.derived ? {derived: source.derived, derived_sha256: source.derived_sha256} : {})},
      }}));
    rows.push(...projected);
    sourceMap.set(source.id, {source, scenes, projected});
  }
  for (const record of records) {
    assert(record && Object.keys(record).every(key => fields.has(key)), 'Unexpected or protected record field');
    assert(!ids.has(record.id), `Duplicate proposed id: ${record.id}`); ids.add(record.id);
    const selected = sourceMap.get(record.source_id);
    assert(selected, `Unknown source id: ${record.source_id}`);
    const {source, scenes, projected} = selected;
    assert(Number.isSafeInteger(record.start_line) && Number.isSafeInteger(record.end_line) &&
      record.start_line >= source.from && record.end_line >= record.start_line && record.end_line <= source.to,
      `Unbound source lines: ${record.id}`);
    assert(Array.isArray(record.planned_units) && record.planned_units.every(x => typeof x === 'string') &&
      Array.isArray(record.related_ids) && record.related_ids.every(x => typeof x === 'string'), 'Invalid narrative links/placement');
    const first = record.start_line - source.from + 1, last = record.end_line - source.from + 1;
    const sceneIndex = scenes.findIndex((scene, i) => first >= scene.line &&
      last < (scenes[i + 1]?.line ?? source.text.split('\n').length + 1));
    assert(sceneIndex >= 0, `Reference crosses a heading boundary: ${record.id}`);
    const span = source.text.split('\n').slice(first - 1, last).join('\n');
    assert(span.trim(), `Empty reference: ${record.id}`);
    assert(['fact','alias','thread','structural'].includes(record.kind), 'Author decisions cannot be extracted');
    const context = {source_role: source.role, attribution: record.source_role,
      origin_execution_status: interrupted ? 'interrupted' : 'completed',
      proposed_units: record.planned_units, narrative_links: record.related_ids,
      unresolved_narrative_links: record.related_ids.filter(id => !recordedIds.has(id)), note: record.note,
      original_file: source.file, original_lines: [record.start_line, record.end_line]};
    const value = record.kind === 'fact'
      ? {entity: record.entity, predicate: record.predicate, object: record.object, context}
      : {...record.object, context};
    const tuple = {schema: 1, id: record.id, kind: record.kind, value,
      interval: {scope: 'unspecified'}, lock: 'candidate',
      receipt: {span, heading_path: scenes[sceneIndex].heading_path, line_hint: first, date}};
    // Existing validation is authoritative. No fuzzy quote repair or inferred time/acceptance.
    prepareCandidate(tuple, scenes[sceneIndex], pack, projected[sceneIndex].receipt, date);
    projected[sceneIndex].tuples.push(tuple);
  }
  return {schema: 1, kind: 'actual-coherent-onboarding-recording', scenes: rows,
    note: 'Heading rows bind original sources for commit; they are not separate model calls. Narrative links are source-based analysis, not computed ripple edges.'};
}
