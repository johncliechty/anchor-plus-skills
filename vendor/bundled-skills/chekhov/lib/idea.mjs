/** W8: bounded data typing and a deterministic verdict. No project writes. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { createDataSession } from '../../../../trio/drivers/index.mjs';
import { sha256Text } from './manifest.mjs';
import { cardinalityOf, normaliseValue, intervalOverlaps, parseCoord, validateInterval } from './pack.mjs';
import { buildAliasTrie, resolveSurface } from './tuples.mjs';
import { runT0, singleValueOverlap, multiNegationConflict } from './t0.mjs';
import { rippleFor } from './asks.brightheart.mjs';

export const IDEA_PROMPT = fs.readFileSync(new URL('./prompts/idea-type.v1.md', import.meta.url), 'utf8');
export const IDEA_PROMPT_HASH = sha256Text(IDEA_PROMPT);
export const IDEA_LIMIT = 32768;
export const VERDICTS = Object.freeze({ consistent: 'CONSISTENT', adjustments: 'CONSISTENT-WITH-ADJUSTMENTS',
  inconsistent: 'INCONSISTENT', unknown: 'NO VERDICT (UNKNOWN)', pending: 'NO VERDICT (PENDING)' });
const scalar = { type: ['string', 'number', 'boolean', 'null'] };
const time = { anyOf: [{ type: ['string', 'null'] }, { type: 'object', additionalProperties: false,
  required: ['from', 'to'], properties: { from: { type: 'string' }, to: { type: ['string', 'null'] } } }] };
export const IDEA_SCHEMA = Object.freeze({ type: 'object', additionalProperties: false,
  required: ['kind', 'scope', 'claims', 'unknown_nouns', 'unknown_predicates'], properties: {
    kind: { type: 'string', enum: ['idea', 'decision', 'prose', 'question'] }, scope: { type: ['string', 'null'] },
    claims: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['entity', 'predicate', 'value', 'at'], properties: {
        entity: { type: 'string' }, predicate: { type: 'string' }, at: time,
        value: { anyOf: [scalar, { type: 'array', items: scalar }, { type: 'object', additionalProperties: false,
          required: ['min', 'max'], properties: { min: { type: 'number' }, max: { type: 'number' } } }] },
      } } }, unknown_nouns: { type: 'array', items: { type: 'string' } },
    unknown_predicates: { type: 'array', items: { type: 'string' } },
  } });

const map = (v) => v && typeof v === 'object' && !Array.isArray(v);
const stringList = (v) => Array.isArray(v) && v.length <= 64 && v.every((s) => typeof s === 'string' && s.length <= 256);
function cleanValue(v) {
  if (v === null || typeof v === 'boolean' || typeof v === 'string' && v.length <= IDEA_LIMIT || typeof v === 'number' && Number.isFinite(v)) return v;
  if (Array.isArray(v) && v.length <= 64 && v.every((x) => !map(x) && !Array.isArray(x))) return v.map(cleanValue);
  if (map(v) && Number.isFinite(v.min) && Number.isFinite(v.max) && v.min <= v.max) return { min: v.min, max: v.max };
  throw new Error('invalid claim value');
}

/** Allowlist construction: never spread a seat object into a durable tuple. */
export function sanitizeIdea(value) {
  if (!map(value) || !['idea', 'decision', 'prose', 'question'].includes(value.kind)
    || !(value.scope === null || typeof value.scope === 'string' && value.scope.length <= 256)
    || !Array.isArray(value.claims) || value.claims.length > 64
    || !stringList(value.unknown_nouns) || !stringList(value.unknown_predicates)) throw new Error('invalid idea schema');
  const claims = value.claims.map((c) => {
    if (!map(c) || !['entity', 'predicate'].every((k) => typeof c[k] === 'string' && c[k].trim() && c[k].length <= 256)
      || !Object.hasOwn(c, 'value') || !Object.hasOwn(c, 'at')) throw new Error('invalid claim schema');
    let at = c.at;
    if (map(at)) { at = { from: at.from, to: at.to }; validateInterval(at); if (at.to === undefined) throw new Error('missing interval end'); }
    else if (!(at === null || typeof at === 'string' && at.length <= 256)) throw new Error('invalid claim time');
    return { entity: c.entity, predicate: c.predicate, value: cleanValue(c.value), at };
  });
  return { kind: value.kind, scope: value.scope, claims,
    unknown_nouns: [...value.unknown_nouns], unknown_predicates: [...value.unknown_predicates] };
}

/** Only small attestation fields survive. Never log wire diagnostics or replies. */
export function ideaSeatStamp(receipt = {}) {
  const out = { cross_model: false, model_attested: receipt.model_attested === true,
    served_model: null, tool_isolation_verified: null };
  for (const k of ['family', 'driver', 'served_model', 'requested_model', 'requested_effort', 'effort', 'mode', 'runtime_policy_status']) {
    if (typeof receipt[k] === 'string' && receipt[k].length <= 200) out[k] = receipt[k];
  }
  if (typeof receipt.tool_isolation_verified === 'boolean') out.tool_isolation_verified = receipt.tool_isolation_verified;
  return out;
}

/** Small source-free timeout fallback. It never certifies full coverage or
 * invents a typed predicate from a generic quotation. Raw input stays in log.
 */
export function literalIdeaPartial(raw, pack) {
  if (typeof raw !== 'string' || raw.length > 8000) return null;
  const clauses = raw.split(/(?<=[.!?])\s+|\r?\n/).filter((s) => s.trim());
  if (clauses.length > 32) return null;
  const claims = [];
  for (const clause of clauses) {
    const text = clause.trim();
    if (text.endsWith('?')) continue;
    const knowledge = /^([\p{Lu}][\p{L}'’-]*(?: [\p{Lu}][\p{L}'’-]*){0,3}) knows\s+\S.+[.!]?$/u.exec(text);
    const relationship = /^([\p{Lu}][\p{L}'’-]*(?: [\p{Lu}][\p{L}'’-]*){0,3}) is ([\p{Lu}][\p{L}'’-]*(?: [\p{Lu}][\p{L}'’-]*){0,3})['’]s (?:sister|brother|mother|father|parent|child|daughter|son|friend|partner|wife|husband)[.!]?$/u.exec(text);
    const predicate = knowledge ? 'knows' : relationship ? 'relation' : null;
    const match = knowledge || relationship;
    if (predicate && cardinalityOf(pack, predicate)) claims.push({ entity: match[1], predicate, value: text, at: null });
  }
  if (!claims.length) return null;
  return { kind: 'idea', scope: null, claims, unknown_nouns: [],
    unknown_predicates: ['typing unavailable: literal claims only; the complete raw submission still requires review'] };
}

/** One ordinary coding-family session, at most one schema correction, no project
 * cwd. Each attempt has a 120s operational timeout, separate from speed targets.
 */
export async function typeIdea(raw, pack, opts = {}) {
  const started = Date.now();
  let session, scratch;
  const seats = [];
  let attempts = 0;
  try {
    scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'chekhov-idea-'));
    const open = () => (opts.createSession || createDataSession)({ role: 'idea-typer', cwd: scratch,
      env: { ...process.env, CRUCIBLE_AGENT_LIVE: '1' }, maxTurns: 2, turnTimeoutMs: 120000 });
    session = await open();
    for (attempts = 1; attempts <= 2; attempts++) {
      try {
        const { value, receipt } = await session.request({ schema: IDEA_SCHEMA,
          prompt: `${IDEA_PROMPT}\nCATALOG_JSON: ${JSON.stringify(Object.keys(pack.predicate_catalog))}\nIDEA_DATA_JSON: ${JSON.stringify({ text: raw, scope: opts.scope ?? null })}${attempts === 2 ? '\nReturn the fixed schema; the previous response failed validation.' : ''}` });
        seats.push(ideaSeatStamp(receipt));
        return { extraction: sanitizeIdea(value), seats, attempts, duration_ms: Date.now() - started };
      } catch (e) {
        if (e.code && !['schema_nonconforming', 'malformed_jsonl', 'invalid_schema'].includes(e.code)) throw e;
        if (e.receipt) seats.push(ideaSeatStamp(e.receipt));
        if (attempts === 2) return { extraction: null, seats, attempts, row: 'dependency-returns-garbage', duration_ms: Date.now() - started };
        // The canonical transport closes on a wire-schema failure. Its one
        // permitted schema re-ask needs a fresh ordinary data session.
        if (session.closed || session.state === 'failed') { await session.close(); session = await open(); }
      }
    }
  } catch (e) {
    const row = /timeout|timed.?out|killed|cancel|closed|exit/i.test(e.code || '') ? 'dependency-slow-or-killed' : 'dependency-missing';
    if (e.receipt) seats.push(ideaSeatStamp(e.receipt));
    const partial = row === 'dependency-slow-or-killed' ? literalIdeaPartial(raw, pack) : null;
    return { extraction: partial, seats, attempts, row, ...(partial ? { fallback: 'literal-partial' } : {}), duration_ms: Date.now() - started };
  } finally {
    try { await session?.close(); } finally { if (scratch) fs.rmSync(scratch, { recursive: true, force: true }); }
  }
}

export function unknownVerdict(asks = [], pending = false) {
  return { verdict: pending ? VERDICTS.pending : VERDICTS.unknown, asks, findings: [], ripple: [],
    alternatives: [], candidates: [], scope_dependent: false, requires_lock_event: false, ripple_count: 0 };
}

function scopeOf(value) {
  if (value == null || value === '' || value === 'unspecified') return null;
  if (map(value)) return { interval: validateInterval(value) };
  if (value === 'project') return { interval: { scope: 'project' } };
  const text = String(value).replace(/^B/i, '');
  if (/^\d+$/.test(text)) return { book: Number(text) };
  parseCoord(text);
  return { interval: { from: text, to: text } };
}
function inScope(interval, scope) {
  if (interval.scope === 'unspecified') return false;
  if (scope?.book !== undefined) return interval.scope === 'project'
    || parseCoord(interval.from)[0] <= scope.book && (interval.to == null || interval.to === 'end' || parseCoord(interval.to)[0] >= scope.book);
  return !scope || intervalOverlaps(interval, scope.interval);
}
function timeGrounded(at, raw) {
  if (at == null || at === 'unspecified') return true;
  if (at === 'project') return /\b(project|series|throughout|always|every book)\b/i.test(raw);
  if (map(at)) return timeGrounded(at.from, raw) && (at.to === null ? /\b(onward|forever|scope end)\b/i.test(raw) : timeGrounded(at.to, raw));
  return String(raw).toLowerCase().includes(String(at).toLowerCase())
    || /^B\d+$/i.test(at) && new RegExp(`\\bbook\\s+${Number(at.slice(1))}\\b`, 'i').test(raw);
}
const conflict = (pack, a, b) => singleValueOverlap(pack, a, b).conflict || multiNegationConflict(pack, a, b).conflict;

/** T0 is local: no Bible or index content is ever passed to typeIdea. */
export function evaluateIdea(pack, entries, extraction, { id, raw, date, scope: override } = {}) {
  const began = Date.now();
  const result = unknownVerdict();
  if (!extraction) return result;
  const unknownPredicates = [...new Set([...extraction.unknown_predicates,
    ...extraction.claims.filter((c) => !Object.hasOwn(pack.predicate_catalog, c.predicate) || !cardinalityOf(pack, c.predicate)).map((c) => c.predicate)])];
  const asks = [...extraction.unknown_nouns.map((noun) => `unknown noun: ${noun}`), ...unknownPredicates.map((p) => `unknown predicate: ${p}`)];
  if (!extraction.claims.length) return { ...result, asks: asks.length ? asks : [`${extraction.kind}: no checkable claims`] };
  const base = runT0(pack, entries);
  const excluded = new Set(base.superseded.filter((r) => r.honoured).map((r) => r.id));
  const ledger = base.ledger;
  const trie = buildAliasTrie(entries.filter((e) => !excluded.has(e.tuple.id)).map((e) => e.tuple));
  const proposals = [];
  const findings = [], candidates = [], alternatives = [], seeds = new Set(), timingAsks = new Set();
  let scopeDependent = false;
  for (const [i, c] of extraction.claims.entries()) {
    if (unknownPredicates.includes(c.predicate)) continue;
    let scope;
    try {
      if (override != null && (typeof override !== 'string' || /\s/.test(override))) throw new Error('scope override must be one word');
      if (override == null && !timeGrounded(c.at ?? extraction.scope, raw)) throw new Error('unquoted time');
      scope = scopeOf(override ?? c.at ?? extraction.scope);
    } catch { asks.push('scope: supply an explicit known interval or one-word override'); continue; }
    const resolved = resolveSurface(trie, c.entity, { includeHits: true, includeUnspecified: true });
    const hits = (resolved.hits || []).filter((h) => h.interval.scope === 'unspecified' || inScope(h.interval, scope));
    const targets = [...new Set(hits.map((h) => h.target))];
    // Canonical entity names can be used only if already present in the index.
    const entity = targets.length === 1 ? targets[0] : !resolved.hits && Object.hasOwn(ledger.entities, c.entity) ? c.entity : null;
    if (!entity) { asks.push(`unknown noun: ${c.entity}`); continue; }
    const inferred = hits.length && hits.every((h) => isDeepStrictEqual(h.interval, hits[0].interval)) ? hits[0].interval : null;
    const interval = scope?.interval || (!scope ? inferred : null) || { scope: 'unspecified' };
    const dependent = interval.scope === 'unspecified';
    scopeDependent ||= dependent;
    const tuple = { schema: 1, id: `idea.${id}.${i + 1}`, kind: 'fact', lock: 'candidate',
      value: { entity, predicate: c.predicate, object: normaliseValue(pack, c.value) }, interval,
      receipt: { span: raw, heading_path: [id], line_hint: 1, date, source_file: 'chekhov/VERDICTS.md',
        verdict_id: id, line_hash: sha256Text(raw), prompt_hash: IDEA_PROMPT_HASH } };
    // Broad checks do not invent coordinates or promote a conditional result.
    const probe = dependent ? { ...tuple, interval: { scope: 'project' } } : tuple;
    const relevant = (ledger.entities[entity] || []).filter((key) => !excluded.has(key)).map((key) => ({ id: key, ...ledger.tuples[key] }))
      .filter((row) => row.kind === 'fact' && row.value.predicate === c.predicate && inScope(row.interval, scope || { interval: probe.interval }));
    const pending = (ledger.entities[entity] || []).map((key) => ledger.tuples[key])
      .some((row) => row.kind === 'fact' && row.value.predicate === c.predicate && row.interval.scope === 'unspecified');
    if (pending) {
      const question = `timing pending: ${entity}.${c.predicate}`;
      asks.push(question); timingAsks.add(question);
    }
    for (const drift of base.receipt_drift) if (relevant.some((row) => row.id === drift.id)) asks.push(`receipt drift: ${drift.id}; resolve at accept`);
    const clashes = relevant.filter((row) => conflict(pack, probe, row));
    const status = clashes.length ? 'conflict' : relevant.length ? 'supported-or-unaffected' : 'no-entry';
    const cited = (clashes.length ? clashes : relevant).map((row) => ({ id: row.id, rung: row.lock, receipt: row.receipt, sidecar: row.sidecar }));
    findings.push({ claim: tuple.id, status, cited, scope_dependent: dependent });
    for (const row of clashes) { seeds.add(row.id); seeds.add(row.entity); }
    if (status === 'no-entry') candidates.push(tuple);
    proposals.push({ tuple, probe, relevant, clashes });
  }
  // Incompatible assertions in one line must never certify one another.
  for (let i = 0; i < proposals.length; i++) for (let j = i + 1; j < proposals.length; j++) {
    if (conflict(pack, proposals[i].probe, proposals[j].probe)) return { ...result, asks: ['conflicting claims within the dictated line'] };
  }
  const relevantThreads = new Set();
  for (const p of proposals) for (const key of rippleFor(ledger, [p.tuple.value.entity, ...p.relevant.map((r) => r.id)])) relevantThreads.add(key);
  const absences = base.threads_due.filter((row) => relevantThreads.has(row.thread)
    || proposals.some((p) => intervalOverlaps(p.probe.interval, ledger.tuples[row.thread].interval)));
  for (const absence of absences) seeds.add(absence.thread);
  const affected = [...new Set([...seeds, ...rippleFor(ledger, [...seeds])])].filter((key) => ledger.tuples[key]).sort();
  const ripple = affected.map((key) => ({ id: key, rung: ledger.tuples[key].lock,
    action: absences.some((a) => a.thread === key) ? 'resolve absence' : 'review change', receipt: ledger.tuples[key].receipt }));
  for (const tuple of candidates) ripple.push({ id: tuple.id, rung: 'candidate', action: 'add as candidate', value: tuple.value.object, interval: tuple.interval });
  const lockedConflict = proposals.some((p) => p.clashes.some((row) => row.lock === 'locked'));
  const needsLock = ripple.some((row) => row.rung === 'locked');
  // Alternatives are conservative exact recorded values, checked against all
  // overlapping rungs. No speculative time shift or free-text repair is shown.
  if (lockedConflict) for (const p of proposals) for (const row of p.clashes) {
    const alternative = { ...p.tuple, value: { ...p.tuple.value, object: row.value.object } };
    const probe = { ...p.probe, value: alternative.value };
    if (!p.relevant.some((r) => conflict(pack, probe, r)) && absences.length === 0
      && !proposals.some((other) => other !== p && conflict(pack, probe, other.probe))) {
      if (!alternatives.some((a) => isDeepStrictEqual(a.claim, alternative))) alternatives.push({ claim: alternative, t0_clean: true, cited: row.id });
    }
  }
  const verdict = lockedConflict ? VERDICTS.inconsistent : candidates.length || ripple.length ? VERDICTS.adjustments : VERDICTS.consistent;
  const evaluated = { verdict, asks: [...asks, ...(needsLock ? [`requires a lock event; ripple count=${affected.length}`] : [])], findings,
    absences, ripple, alternatives, candidates: lockedConflict ? [] : candidates, claims: proposals.map((p) => p.tuple),
    scope_dependent: scopeDependent, requires_lock_event: needsLock, ripple_count: affected.length, duration_ms: Date.now() - began };
  if (!asks.length) return evaluated;
  // Unknowns cannot promote candidates, but must not hide already established
  // conflicts or their consequences from the subsequent evidence check.
  return { ...evaluated, verdict: VERDICTS.unknown, candidates: [], alternatives: [],
    ripple: ripple.filter((row) => row.action !== 'add as candidate'), partial: true,
    timing_only: proposals.length === extraction.claims.length && asks.every(ask => timingAsks.has(ask)) };
}

export function renderIdea(record) {
  const t0 = record.t0;
  const lines = [`${t0.verdict} (${record.id})`, ...t0.asks.map((s) => `Ask: ${s}`)];
  if (t0.scope_dependent) lines.push('scope-dependent: broad checks only; timing remains unspecified.');
  for (const f of t0.findings) for (const c of f.cited) lines.push(`${c.id} [${c.rung}${c.source ? `; ${c.source.role}; ${c.source.limitations.join(', ') || 'no additional attribution'}` : ''}]: ${JSON.stringify(c.receipt.span)} (${c.sidecar})`);
  for (const a of t0.absences || []) lines.push(`${a.order}: ${a.class} ${a.thread}: ${a.note}`);
  for (const r of t0.ripple) lines.push(r.action === 'add as candidate'
    ? `add as candidate: (${r.id}, ${JSON.stringify(r.value)}, ${JSON.stringify(r.interval)})`
    : `${r.action}: ${r.id} [${r.rung}]`);
  for (const a of t0.alternatives) lines.push(`Alternative (T0-clean): ${JSON.stringify(a.claim.value)} at ${JSON.stringify(a.claim.interval)}; ${a.cited}`);
  if (record.inbox) lines.push(`Dictation saved unchanged: ${record.inbox}`);
  return lines;
}
