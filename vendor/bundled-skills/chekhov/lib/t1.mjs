/** W9 evidence only. Storage and transition ownership remain in the engine. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { createDataSession } from '../../../../trio/drivers/index.mjs';
import { sha256Text } from './manifest.mjs';
import { runT0 } from './t0.mjs';
import { evaluateIdea, ideaSeatStamp, unknownVerdict, VERDICTS } from './idea.mjs';
import { rippleFor } from './asks.brightheart.mjs';
import { intervalOverlaps, normaliseValue } from './pack.mjs';
import { LEDGER_SCHEMA } from './index.mjs';
import { bindRecordedSpan, sourceDescription, sourceReferenceMatches, compactLedgerRow } from './onboarding-t1.mjs';

export const T1_LIMITS = Object.freeze({ entries: 2048, packet_bytes: 262144,
  response_bytes: 262144, source_bytes: 2097152, sources: 16, turns: 128,
  turn_ms: 180000, t0_ms: 2000, full_ms: 60000 });
export const T1_PROMPT = fs.readFileSync(new URL('./prompts/judge.v1.md', import.meta.url), 'utf8');
export const T1_PROMPT_HASH = sha256Text(T1_PROMPT);
const relations = ['supports', 'conflicts', 'unaffected', 'absent'];
const roles = ['current-manuscript', 'current-plan', 'additional-writing', 'bible', 'history', 'unspecified'];
const tableSchema = { type: 'array', maxItems: T1_LIMITS.entries,
  items: { type: 'object', additionalProperties: false,
    required: ['entry_id', 'quoted_span', 'relation'], properties: {
      entry_id: { type: 'string' }, quoted_span: { type: 'string' },
      relation: { type: 'string', enum: relations },
    } } };
export const T1_SCHEMA = Object.freeze({ type: 'object', additionalProperties: false,
  required: ['rows'], properties: { rows: tableSchema } });
const clone = (value) => JSON.parse(JSON.stringify(value));
const bytes = (value) => Buffer.byteLength(typeof value === 'string' ? value : JSON.stringify(value), 'utf8');
const failed = (reason, pending = false) => ({ ...unknownVerdict([reason], pending), reason });

/** A source path is always local to the project; never follow a link. */
export function t1SourcePath(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative)
    || relative.includes(':') || relative.split(/[\\/]/).some((p) => p === '..' || p === '.')) throw new Error('root-relative source required');
  const base = fs.realpathSync(root), target = path.resolve(base, relative);
  const rel = path.relative(base, target);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw new Error('source escapes project root');
  let at = base;
  for (const part of rel.split(path.sep)) {
    at = path.join(at, part);
    if (fs.existsSync(at) && fs.lstatSync(at).isSymbolicLink()) throw new Error('linked source refused');
  }
  return target;
}

/** Exact continuous quote in its recorded heading. line_hint only disambiguates. */
export function bindT1Span(text, receipt) {
  return bindRecordedSpan(text, receipt);
}

function readSource(root, file, cache) {
  if (!cache.has(file)) {
    if (!/\.md$/i.test(file)) throw new Error('markdown source required');
    const target = t1SourcePath(root, file);
    if (fs.statSync(target).size > T1_LIMITS.source_bytes) throw new Error(`source exceeds ${T1_LIMITS.source_bytes} bytes; select a bounded source through the ordinary capture path`);
    cache.set(file, new TextDecoder('utf-8', { fatal: true }).decode(fs.readFileSync(target)));
  }
  return cache.get(file);
}

function sourceInfo(entry, selected) {
  return sourceDescription(entry, selected);
}

const qualified = (row) => row.source.limitations.some((s) => !['narration', 'revelation'].includes(s));

/** Every predicate/rung for named entities, dependency entries, and ALL threads.
 * Only receipt spans and deliberately selected passages reach the judge.
 */
export function buildT1Packet(root, { pack, entries }, record, selections = []) {
  if (!Array.isArray(selections) || selections.length > T1_LIMITS.sources) throw new Error(`at most ${T1_LIMITS.sources} selected passages`);
  const base = runT0(pack, entries), ledger = base.ledger;
  const entities = [...new Set((record.t0.claims || []).map((c) => c.value.entity))].sort();
  const ids = new Set(entities.flatMap((e) => ledger.entities[e] || []));
  // Order decisions and covering decisions are part of thread/history context.
  for (const entry of entries) if (entry.tuple.kind === 'decision' && (entry.tuple.orders
    || /(?:^|\.)(?:theme|structure|doctrine_tag|voice)(?:\.|$)/.test(entry.tuple.id)
    || entries.some((e) => ids.has(e.tuple.id) && e.tuple.superseded_by === entry.tuple.id)
    || (entry.tuple.governs || []).some((id) => ids.has(id) || entities.includes(id)))) ids.add(entry.tuple.id);
  for (const id of rippleFor(ledger, [...entities, ...ids])) ids.add(id);
  for (const [id, row] of Object.entries(ledger.tuples)) if (row.kind === 'thread') ids.add(id);
  for (const id of rippleFor(ledger, [...ids])) ids.add(id);
  const gaps = [], sources = [], cache = new Map();
  for (const selection of selections) {
    try {
      if (!selection || !roles.includes(selection.role) || !Array.isArray(selection.limitations)
        || selection.limitations.some((s) => typeof s !== 'string')
        || !Array.isArray(selection.required_ids) || selection.required_ids.some((s) => typeof s !== 'string')) throw new Error('selection needs role, limitations and required_ids');
      const text = readSource(root, selection.file, cache);
      const binding = bindT1Span(text, selection);
      if (!binding) throw new Error('selected quote is missing, ambiguous or in another heading');
      sources.push({ file: selection.file, role: selection.role, span: selection.span,
        heading_path: binding.heading_path, line_hint: binding.line,
        source_hash: sha256Text(text), limitations: [...selection.limitations],
        required_ids: [...selection.required_ids], coverage: 'selected passage only' });
      for (const id of selection.required_ids) {
        const entry = entries.find((e) => e.tuple.id === id);
        if (!entry || entry.sidecar !== `${selection.file}.ledger.yaml`
          || !selection.span.includes(entry.tuple.receipt.span)) gaps.push(`selected coverage missing: ${id} in ${selection.file}`);
        else ids.add(id);
      }
      if (!selection.required_ids.length) gaps.push(`selected coverage undeclared: ${selection.file}`);
    } catch (e) { gaps.push(`source coverage: ${selection?.file || '(missing file)'}: ${e.message}`); }
  }
  if (!selections.length) gaps.push('selected manuscript/planning coverage not supplied; ledger-only check');
  for (const id of rippleFor(ledger, [...ids])) ids.add(id);
  if (ids.size > T1_LIMITS.entries) throw new Error(`T1 packet exceeds ${T1_LIMITS.entries} entries; nothing was truncated`);
  const excluded = new Set(base.superseded.filter((r) => r.honoured).map((r) => r.id));
  const packetEntries = [...ids].sort().map((id) => {
    const entry = entries.find((e) => e.tuple.id === id), row = ledger.tuples[id];
    const source = sourceInfo(entry, sources);
    let binding = null, sourceHash = null, citation_error = null;
    try {
      if (entry.verdict_id) {
        // loadLedgerEntries obtains this raw line through verified verdictData.
        if (entry.tuple.receipt.verdict_id !== entry.verdict_id || entry.prose !== row.receipt.span
          || row.receipt.line_hash && row.receipt.line_hash !== sha256Text(entry.prose)) throw new Error('verdict source binding mismatch');
        sourceHash = sha256Text(entry.prose); binding = { verdict_id: entry.verdict_id };
      } else {
        if (row.receipt.source_file && !sourceReferenceMatches(root, row.receipt.source_file, source.file)) throw new Error('receipt names a different source file');
        const text = readSource(root, source.file, cache);
        binding = bindT1Span(text, row.receipt); sourceHash = sha256Text(text);
        if (!binding) throw new Error('receipt quote missing, ambiguous or in another heading');
      }
    } catch (e) { citation_error = e.message; }
    return { entry_id: id, ...compactLedgerRow(row), source, source_hash: sourceHash, binding, citation_error,
      active: !excluded.has(id) && source.role !== 'history', superseded_by: entry.tuple.superseded_by ?? null,
      ...(entry.tuple.orders ? { orders: clone(entry.tuple.orders) } : {}) };
  });
  const packet = { schema: 1, idea: record.raw_line, scope_override: record.scope_override ?? null,
    claims: (record.t0.claims || []).map((c) => ({ value: c.value, interval: c.interval })),
    entities, entries: packetEntries, sources, orders: base.orders,
    form: { name: pack.name, beats: pack.beat_table || pack.beats, checklist: pack.checklist },
    coverage: { gaps,
      limitation: 'Selected receipts and passages only; missing material and unresolved chronology are not proof of absence.' } };
  if (bytes(packet) > T1_LIMITS.packet_bytes) throw new Error(`T1 packet exceeds ${T1_LIMITS.packet_bytes} bytes; nothing was truncated`);
  return { packet, hash: sha256Text(JSON.stringify(packet)), ledger };
}

/** Closed schema even for replay: extra verdict fields are discarded, recorded. */
export function evidenceRows(value) {
  const discarded = [];
  if (value && !Array.isArray(value) && Array.isArray(value.rows)) {
    discarded.push(...Object.keys(value).filter((k) => k !== 'rows')); value = value.rows;
  }
  if (!Array.isArray(value) || value.length > T1_LIMITS.entries || bytes(value) > T1_LIMITS.response_bytes) throw new Error('invalid or oversized evidence table');
  const rows = value.map((row) => {
    if (!row || typeof row.entry_id !== 'string' || !row.entry_id || typeof row.quoted_span !== 'string'
      || !row.quoted_span.trim() || !relations.includes(row.relation)) throw new Error('invalid evidence row');
    discarded.push(...Object.keys(row).filter((k) => !['entry_id', 'quoted_span', 'relation'].includes(k)));
    return { entry_id: row.entry_id, quoted_span: row.quoted_span, relation: row.relation };
  });
  return { rows, discarded_fields: [...new Set(discarded)].sort() };
}

export function verifyT1Rows(rows, packet, required = []) {
  const failed_cites = [], seen = new Set();
  for (const row of rows) {
    const entry = packet.entries.find((e) => e.entry_id === row.entry_id);
    let reason = !entry ? 'id is not in the current entity packet/ledger' : entry.citation_error;
    if (!reason && row.quoted_span !== entry.receipt.span) reason = 'quote must equal the complete current receipt span';
    if (!reason && row.relation === 'absent' && entry.kind !== 'thread') reason = 'absence must cite a recorded thread obligation';
    if (seen.has(row.entry_id)) reason = 'duplicate evidence id';
    seen.add(row.entry_id);
    if (reason) failed_cites.push({ ...row, reason });
  }
  // Missing rows are failures too, including an empty answer to a nonempty packet.
  for (const entry of packet.entries) if (!seen.has(entry.entry_id)) failed_cites.push({ entry_id: entry.entry_id, reason: 'missing cite' });
  for (const cite of required) if (!rows.some((r) => r.entry_id === cite.entry_id
    && r.quoted_span === cite.quoted_span && (!cite.relation || r.relation === cite.relation))) {
    failed_cites.push({ entry_id: cite.entry_id, reason: 'missing required replay cite/relation' });
  }
  return { ok: failed_cites.length === 0, failed_cites };
}

/** Compare every displayed row with the actual rebuilt ledger.json as well.
 * The sidecars/log remain truth; an altered index cannot certify a citation.
 */
export function verifyT1Index(root, rows, packet) {
  const failed_cites = [];
  try {
    const index = JSON.parse(fs.readFileSync(t1SourcePath(root, 'chekhov/ledger.json'), 'utf8'));
    if (index.schema !== LEDGER_SCHEMA || !index.tuples) throw new Error('invalid current ledger.json');
    for (const row of rows) {
      const indexed = index.tuples[row.entry_id], entry = packet.entries.find((e) => e.entry_id === row.entry_id);
      const evidenceKeys = ['kind', 'entity', 'value', 'interval', 'lock', 'receipt', 'sidecar', 'minted'];
      if (!indexed || !entry || evidenceKeys.some((key) => !isDeepStrictEqual(compactLedgerRow(indexed)[key], entry[key]))) {
        failed_cites.push({ entry_id: row.entry_id, reason: 'id or evidence differs from current ledger.json' });
      }
    }
  } catch (e) { failed_cites.push({ entry_id: 'ledger.json', reason: `backing-store-unreadable: ${e.message}` }); }
  return { ok: !failed_cites.length, failed_cites };
}

/** W8's rule with semantic conflicts/absences added; never a seat verdict. */
export function computeT1Verdict(inputs, record, packet, rows) {
  const byId = new Map(packet.entries.map((e) => [e.entry_id, e]));
  // Qualified evidence remains in the packet. It cannot serve as unqualified
  // deterministic support or a canonical contradiction in the final result.
  const unqualified = inputs.entries.filter((e) => !byId.has(e.tuple.id)
    || byId.get(e.tuple.id).active && (e.tuple.kind === 'alias' || !qualified(byId.get(e.tuple.id))));
  const result = evaluateIdea(inputs.pack, unqualified, record.extraction, { id: record.id,
    raw: record.raw_line, date: record.at, scope: record.scope_override });
  // Unknown dates do not make a fully understood relationship unreadable.
  // T1 may give qualified feedback while retaining every timing question.
  // Missing nouns, predicates, claims, sources or typing still prevent a verdict.
  const incompleteUnderstanding = verdict => [VERDICTS.unknown, VERDICTS.pending].includes(verdict.verdict)
    && !(verdict.verdict === VERDICTS.unknown && verdict.timing_only === true && verdict.claims?.length);
  const incomplete = incompleteUnderstanding(record.t0) || incompleteUnderstanding(result);
  result.qualified_evidence = [];
  const seeds = new Set(), asks = new Set(result.asks), affectedEntities = new Set();
  let lockedConflict = result.verdict === VERDICTS.inconsistent || result.findings.some((finding) =>
    finding.status === 'conflict' && !finding.scope_dependent && finding.cited.some((cite) => {
      const entry = byId.get(cite.id);
      return cite.rung === 'locked' && entry?.active && !qualified(entry);
    }));
  for (const row of rows) {
    const entry = byId.get(row.entry_id);
    if (!entry.active || row.relation === 'unaffected') continue;
    if (row.relation === 'supports') {
      const comparable = packet.claims.some((c) => c.value.entity === entry.entity
        && c.value.predicate === entry.value?.predicate);
      if (!comparable) {
        asks.add(`context only: ${entry.entry_id}; this quotation does not establish the proposed typed predicate`);
        continue;
      }
      if (qualified(entry)) result.qualified_evidence.push({ entry_id: entry.entry_id,
        relation: row.relation, source: entry.source, quoted_span: row.quoted_span });
    }
    const overlapping = entry.kind === 'thread' || packet.claims.some((c) =>
      c.value.entity === entry.entity && intervalOverlaps(c.interval, entry.interval));
    const semanticConsequence = ['conflicts', 'absent'].includes(row.relation);
    if (!overlapping && !qualified(entry) && !semanticConsequence) continue;
    if (entry.interval.scope === 'unspecified') asks.add(`timing pending: ${entry.entry_id}`);
    if (qualified(entry)) asks.add(`source limitation: ${entry.entry_id} (${entry.source.role}; ${entry.source.limitations.join(', ')})`);
    if (semanticConsequence) {
      // Verified T1 rows concern the whole idea, not a particular typed claim.
      // A compound entity or unknown chronology must not erase their cited
      // revision consequence, or turn it into a proven temporal contradiction.
      result.findings.push({ claim: null, level: 'idea',
        status: row.relation === 'conflicts' ? 'conflict' : 'absent',
        cited: [{ id: entry.entry_id, rung: entry.lock, receipt: entry.receipt,
          sidecar: entry.sidecar, source: entry.source, quoted_span: row.quoted_span }],
        scope_dependent: !overlapping });
    }
    if (semanticConsequence || qualified(entry)) {
      seeds.add(entry.entry_id); affectedEntities.add(entry.entity);
      if (row.relation === 'conflicts' && entry.lock === 'locked' && !qualified(entry) && overlapping) lockedConflict = true;
    }
  }
  const ledger = runT0(inputs.pack, inputs.entries).ledger;
  // Coexistence of generic narrative relations is not evidence for a new
  // assertion. Preserve a new possibility when neither exact data nor the
  // checked semantic rows evaluates it as support or conflict.
  if (!incomplete) for (const claim of result.claims || []) {
    if (!['relation', 'knows'].includes(claim.value.predicate)) continue;
    const relevant = packet.entries.filter((e) => e.active && e.kind === 'fact'
      && e.entity === claim.value.entity && e.value.predicate === claim.value.predicate);
    const evaluated = rows.some((r) => ['supports', 'conflicts'].includes(r.relation)
      && relevant.some((e) => e.entry_id === r.entry_id));
    const exact = relevant.some((e) => isDeepStrictEqual(normaliseValue(inputs.pack, e.value.object), normaliseValue(inputs.pack, claim.value.object)));
    if (!evaluated && !exact && !result.candidates.some((c) => c.id === claim.id)) {
      result.candidates.push(claim);
      result.ripple.push({ id: claim.id, rung: 'candidate', action: 'add as candidate', value: claim.value.object, interval: claim.interval });
    }
  }
  const closure = [...new Set([...seeds, ...rippleFor(ledger, [...seeds, ...affectedEntities])])]
    .filter((id) => ledger.tuples[id] && byId.get(id)?.active !== false);
  const ripple = new Map(result.ripple.map((r) => [r.id, r]));
  for (const id of closure) {
    const entry = byId.get(id), row = ledger.tuples[id];
    ripple.set(id, { id, rung: row.lock, action: entry && qualified(entry) ? 'review source limitation' : 'review semantic consequence', receipt: row.receipt });
  }
  result.ripple = [...ripple.values()];
  result.ripple_count = result.ripple.filter((r) => r.action !== 'add as candidate').length;
  result.requires_lock_event = result.ripple.some((r) => r.rung === 'locked');
  if (result.requires_lock_event) asks.add(`requires a lock event; ripple count=${result.ripple_count}`);
  result.asks = [...asks];
  result.verdict = lockedConflict ? VERDICTS.inconsistent : result.ripple.length || result.candidates.length || asks.size
    ? VERDICTS.adjustments : VERDICTS.consistent;
  if (lockedConflict) result.candidates = [];
  if (incomplete) {
    result.verdict = VERDICTS.unknown;
    result.candidates = [];
    result.ripple = result.ripple.filter((r) => r.action !== 'add as candidate');
    result.asks = [...new Set([...record.t0.asks, ...result.asks])];
    result.partial = true;
  }
  // Semantic conflicts cannot be repaired by inventing an alternate relation.
  // Retain only W8 alternatives already checked by its deterministic rule.
  return result;
}

/** Canonical data session reused serially for the life of this engine owner.
 * No project cwd, no separate transport, no invented resume-token API.
 * Each request has a 180s operational timeout; queue time and the strict
 * performance targets do not cancel it. No additional retry is introduced.
 */
export function createT1Judge({ createSession = createDataSession } = {}) {
  let session, scratch, turns = 0, closed = false, queue = Promise.resolve();
  const close = async () => {
    closed = true;
    try { await session?.close(); }
    finally { if (scratch) { fs.rmSync(scratch, { recursive: true, force: true }); scratch = null; } }
  };
  const request = (packet) => {
    const run = async () => {
      if (closed || turns >= T1_LIMITS.turns || session?.closed || session?.state === 'failed') throw Object.assign(new Error('judge session unavailable or exhausted'), { code: 'session_closed' });
      if (!session) {
        scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'chekhov-judge-'));
        try { session = await createSession({ role: 'idea-judge', cwd: scratch,
          env: { ...process.env, CRUCIBLE_AGENT_LIVE: '1' }, maxTurns: T1_LIMITS.turns, turnTimeoutMs: T1_LIMITS.turn_ms }); }
        catch (e) { await close(); throw e; }
      }
      turns++;
      return session.request({ schema: T1_SCHEMA, timeoutMs: T1_LIMITS.turn_ms, prompt: `${T1_PROMPT}\nEVIDENCE_DATA_JSON: ${JSON.stringify(packet)}` });
    };
    const result = queue.then(run); queue = result.catch(() => {}); return result;
  };
  return { request, close: async () => { await queue; await close(); } };
}

export function validateT1Replay(fixture, raw) {
  if (!fixture || fixture.schema !== 1 || !['real-replay', 'reconstructed'].includes(fixture.kind)
    || fixture.tier !== 'T1' || fixture.input?.raw_line !== raw || !fixture.input?.extraction
    || !Array.isArray(fixture.required_cites) || !fixture.required_cites.length
    || !Object.hasOwn(fixture, 'recorded_seat_output')) throw new Error('missing or mismatched recorded T1 fixture');
  if (fixture.kind === 'real-replay' && (!fixture.packet_hash || !fixture.seats?.judge
    || fixture.seats.judge.mode === 'synthetic' || !fixture.recorded_at)) throw new Error('real-replay needs actual packet, date and judge receipt');
  return fixture;
}

export async function runT1({ inputs, record, built, replay, live = false, judge }) {
  const result = { rows: [], failed_cites: [], discarded_fields: [], seats: { judge: null },
    prompt_hash: T1_PROMPT_HASH, packet_hash: built.hash, packet: built.packet,
    mode: live ? 'live' : 'replay', response_kind: live ? 'real-replay' : replay?.kind || null,
    response_json: null, response_encoding: null };
  try {
    let value;
    if (live) {
      if (!judge) throw Object.assign(new Error('judge unavailable'), { code: 'capability_unavailable' });
      let reply;
      try { reply = await judge.request(built.packet); }
      catch (e) {
        if (e.receipt) result.seats.judge = { role: 'idea-judge', ...ideaSeatStamp(e.receipt) };
        if (['schema_nonconforming', 'malformed_jsonl', 'invalid_schema'].includes(e.code)) throw e;
        const code = /timeout|killed|cancel|closed|exit/i.test(e.code || '') ? e.code : 'capability_unavailable';
        throw Object.assign(new Error('judge unavailable'), { code });
      }
      result.seats.judge = { role: 'idea-judge', ...ideaSeatStamp(reply.receipt) };
      // The inspected driver seam exposes value/receipt, not original wire bytes.
      result.response_json = JSON.stringify(reply.value);
      result.response_encoding = 'JSON.stringify(driver.value); original wire bytes unavailable';
      const typerSeats = Array.isArray(record.seats) ? record.seats : record.seats?.typer || [];
      const family = typerSeats.findLast((s) => s.family && s.family !== 'synthetic')?.family;
      if (!result.seats.judge.family || family && family !== result.seats.judge.family
        || !family && record.typing_fallback !== 'literal-partial' && result.seats.judge.mode !== 'synthetic') throw Object.assign(new Error('same-family judge seat unavailable'), { code: 'capability_unavailable' });
      value = reply.value;
    } else {
      if (!replay) throw Object.assign(new Error('recorded T1 response unavailable; use an explicit replay or --live'), { code: 'capability_unavailable' });
      validateT1Replay(replay, record.raw_line);
      if (replay.kind === 'real-replay') {
        const family = replay.seats.typer?.findLast((s) => s.family)?.family;
        if (family ? family !== replay.seats.judge.family : replay.typing_fallback !== 'literal-partial') throw new Error('recorded judge lacks matching coding-family provenance');
      }
      if (replay.packet_hash && replay.packet_hash !== built.hash) throw new Error('recorded packet no longer matches current source/ledger');
      result.seats.judge = replay.seats?.judge ? { role: 'idea-judge', ...ideaSeatStamp(replay.seats.judge) } : { role: 'idea-judge', mode: 'reconstructed', served_model: null, model_attested: false, cross_model: false };
      result.response_json = typeof replay.recorded_seat_output === 'string' ? replay.recorded_seat_output : JSON.stringify(replay.recorded_seat_output);
      result.response_encoding = typeof replay.recorded_seat_output === 'string' ? 'original replay JSON bytes' : 'JSON.stringify(fixture.recorded_seat_output)';
      if (bytes(result.response_json) > T1_LIMITS.response_bytes) throw new Error('oversized evidence response');
      value = JSON.parse(result.response_json);
    }
    if (bytes(result.response_json) > T1_LIMITS.response_bytes) { result.response_json = null; throw new Error('oversized evidence response'); }
    const cleaned = evidenceRows(value); result.discarded_fields = cleaned.discarded_fields;
    const verification = verifyT1Rows(cleaned.rows, built.packet, replay?.required_cites || []);
    result.failed_cites = verification.failed_cites;
    if (!verification.ok) return { ...result, final: failed(`failed cite: ${verification.failed_cites.map((c) => c.entry_id).join(', ')}`) };
    result.rows = cleaned.rows;
    // No selection is an explicit limitation of an ordinary ledger check.
    // A requested selection with missing coverage is a failed check.
    const gaps = built.packet.coverage.gaps.filter((g) => !g.startsWith('selected manuscript/planning coverage not supplied'));
    if (gaps.length) return { ...result, final: failed(gaps.join('; ')) };
    return { ...result, final: computeT1Verdict(inputs, record, built.packet, cleaned.rows) };
  } catch (e) {
    const pending = ['capability_unavailable', 'session_closed', 'turn_timeout'].includes(e.code)
      || /timeout|killed|cancel|closed|exit|unavailable|missing/i.test(e.code || '');
    return { ...result, final: failed(pending ? `judge unavailable (${e.code || 'dependency-missing'})` : e.message, pending) };
  }
}

export function renderT1(record) {
  const t1 = record.t1, verdict = record.final || t1.final;
  const lines = [`${verdict.verdict} (${record.id})`, ...verdict.asks.map((s) => `Ask: ${s}`)];
  if (verdict.partial && verdict.timing_only && ![VERDICTS.unknown, VERDICTS.pending].includes(verdict.verdict)) {
    lines.push('The proposal was understood, but its place in the chronology remains open. The feedback below keeps that uncertainty; no part of this line was promoted.');
  } else if (verdict.partial) lines.push('Only part of this submission could be checked. The raw input and unsupported parts remain visible; no part of this line was promoted.');
  const relevant = (t1.rows || []).filter((r) => r.relation !== 'unaffected');
  if (relevant.some((r) => r.relation === 'conflicts')) lines.push('Revision consequence: the proposal changes the cited relationship, condition or plan below. Resolve that change before writing it into the project.');
  else if (relevant.some((r) => r.relation === 'supports')) lines.push('The cited passages support the understood proposal within their stated source roles. Any listed limitations and open consequences still apply.');
  else if (verdict.candidates.length) lines.push('This is a new possibility in the checked material. It stays a candidate until you choose to keep it.');
  for (const cite of t1.failed_cites || []) lines.push(`Failed cite: ${JSON.stringify(cite)}`);
  for (const row of t1.rows || []) {
    const entry = t1.packet.entries.find((e) => e.entry_id === row.entry_id);
    lines.push(`${row.entry_id} [${entry.lock}; ${entry.source.role}; ${entry.source.limitations.join(', ') || 'no additional attribution'}] ${row.relation}: ${JSON.stringify(row.quoted_span)} (${entry.source.file})`);
  }
  for (const gap of t1.packet?.coverage.gaps || []) lines.push(`Coverage: ${gap}`);
  for (const ripple of verdict.ripple) lines.push(`${ripple.action}: ${ripple.id} [${ripple.rung}]`);
  for (const alternative of verdict.alternatives) lines.push(`Alternative (T0-clean): ${JSON.stringify(alternative.claim.value)}; ${alternative.cited}`);
  const stamp = t1.seats?.judge;
  lines.push(`Judge: served=${stamp?.served_model || 'unattested'}; requested=${stamp?.requested_model || 'unknown'}; mode=${t1.mode}; model_attested=${stamp?.model_attested === true}`);
  lines.push(`Timing: T0=${record.timings.t0_ms} ms; full=${record.timings.full_ms} ms`);
  if (record.timings.t0_ms >= T1_LIMITS.t0_ms || record.timings.full_ms >= T1_LIMITS.full_ms) {
    lines.push('Slow response: the strict T0 <2s / full <60s performance target was missed; the evidence verdict above is unchanged.');
  }
  return lines;
}

/** Strict recorded gate. Live tolerance is diagnostic, never forgives a cite. */
export function t1TimingReport(records, { live = false, tolerance } = {}) {
  if (tolerance && !live) throw new Error('tolerance is permitted only with --live');
  if (!Array.isArray(records) || !records.length) throw new Error('timing recording is empty');
  const misses = records.filter((r) => ![VERDICTS.consistent, VERDICTS.adjustments, VERDICTS.inconsistent].includes(r.final?.verdict)
    || !Number.isFinite(r.timings?.t0_ms) || r.timings.t0_ms < 0 || r.timings.t0_ms >= T1_LIMITS.t0_ms
    || !Number.isFinite(r.timings?.full_ms) || r.timings.full_ms < r.timings.t0_ms || r.timings.full_ms >= T1_LIMITS.full_ms
    || r.t1?.failed_cites?.length).map((r) => r.id);
  const M = records.length, N = M - misses.length;
  if (tolerance && (!Number.isInteger(tolerance.N) || tolerance.M !== M || tolerance.N < 1 || tolerance.N > M)) throw new Error('invalid live N-of-M tolerance');
  return { ok: N === M, mode: live ? 'live' : 'replay', N, M, misses,
    ...(tolerance ? { tolerance: { ...tolerance, met: N >= tolerance.N } } : {}) };
}
