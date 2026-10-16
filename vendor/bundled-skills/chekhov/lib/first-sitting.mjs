/** Recording preparation for any selected project. Buckets never filter lines. */
import fs from 'node:fs';
import path from 'node:path';
import { verdictData, loadLedgerEntries, entriesForUnit } from './index.mjs';
import { evaluateIdea, unknownVerdict, VERDICTS } from './idea.mjs';
import { loadProjectPack } from './pack.mjs';
import { t1TimingReport } from './t1.mjs';
import { sha256Text } from './manifest.mjs';
import { stateDirFor } from './store.mjs';

export function firstWritingReplay(root, ids, { project } = {}) {
  if (!Array.isArray(ids) || ids.length !== 3 || new Set(ids).size !== 3) throw new Error('Select exactly three distinct actual verdict IDs, in writing order.');
  const data = verdictData(root), pack = loadProjectPack(root), entries = loadLedgerEntries(root);
  const config = JSON.parse(fs.readFileSync(path.join(stateDirFor(root), 'config.json'), 'utf8'));
  const records = ids.map((id) => {
    const record = data.verdicts.find((r) => r.id === id);
    if (!record || project && record.project !== project) throw new Error(`Missing selected-project writing input: ${id}`);
    if (record.line_hash !== sha256Text(record.raw_line)) throw new Error(`Input receipt mismatch: ${id}`);
    const unit = [record.unit, config.active_unit].find(value => typeof value === 'string' && value.trim());
    const expected = config.shared_story_world === false && !unit
      ? unknownVerdict(['Choose the story or novella for this idea. The draft is saved; unrelated stories will not be combined.'])
      : evaluateIdea(pack, entriesForUnit(entries, config, unit, id), record.extraction,
        { id, raw: record.raw_line, date: record.at, scope: record.scope_override });
    return { id, raw_line: record.raw_line, line_hash: record.line_hash, extraction: record.extraction,
      expected_t0_from_current_evidence: expected.verdict, recorded_t0: record.t0.verdict,
      final: record.final || record.t0, timings: record.timings, t1: record.t1 || null, seats: record.seats,
      unknown_predicates: record.extraction?.unknown_predicates || [],
      coverage: record.t1?.packet?.coverage || { gaps: ['No completed semantic evidence packet'] },
      real_model_recording: record.t1?.mode === 'live' && record.t1?.seats?.judge?.mode !== 'synthetic'
        && Boolean(record.t1?.response_json && record.t1?.packet_hash) };
  });
  const complete = records.every((r) => r.real_model_recording && ![VERDICTS.unknown, VERDICTS.pending].includes(r.final.verdict));
  return { schema: 1, project, records, timing: t1TimingReport(records), complete_semantic_recordings: complete,
    author_sitting: 'pending verification of John’s actual sitting; terminal/model records alone do not establish authorship',
    limitation: 'Expected T0 is recomputed from recorded extraction and current evidence. Freeze each source snapshot at recording time for historical replay.' };
}
