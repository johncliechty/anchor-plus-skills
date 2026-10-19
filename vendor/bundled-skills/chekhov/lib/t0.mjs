/**
 * T0 — the deterministic checker (W4). A pure function under 2 seconds.
 *
 * The named comparator is single_value_overlap: conflict(a, b) iff same claim
 * id (entity.predicate), single cardinality, overlapping intervals and
 * normalised values differ. A multi-valued predicate conflicts ONLY against an
 * explicit negation entry (value.negation: true on the same normalised
 * object). Contradictions are counted across ALL rungs — the pre-decision
 * case fires before anything is locked, and both receipts are cited.
 *
 * Minted class: lock: locked OR allow_terms without an acceptance receipt is
 * demoted to candidate in the index (lib/index.mjs) and LISTED here — no hand
 * edit or extractor can lock canon.
 *
 * Superseded-span rule: a tuple carrying superseded_by <decision id> is
 * excluded and listed under superseded ONLY IF that decision exists, is
 * locked with an acceptance receipt, and covers the span's id and interval;
 * otherwise the annotation is listed as UNHONOURED with the reason and the
 * span counts.
 *
 * Absences use_before_plant and unpaid_due (at scope end) run on BOTH orders
 * held in the ONE series decision entry orders: {reader_order, written_order,
 * cascade_position}. Every finding is stamped with the order it fired on: a
 * reader-order hit is a reader-facing break; a written-order hit means the
 * plant is on no written page yet at the cascade position.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import {
  cardinalityOf,
  intervalContains,
  intervalOverlaps,
  loadProjectPack,
  normaliseValue,
  parseCoord,
  validateInterval,
} from './pack.mjs';
import { hasAcceptance, hasMintedFields, resolveReceipt } from './tuples.mjs';
import { buildLedger, loadLedgerEntries } from './index.mjs';
import { projectDocuments, scanProse } from './prose.mjs';
import { scanDoctrine } from './doctrine.mjs';
import { outlineGate } from './gate.mjs';
import { buildStructuralRecord, renderStructure } from './structure.mjs';

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));

export const COMPARATOR = 'single_value_overlap';
export const ORDER_NAMES = Object.freeze(['reader_order', 'written_order']);

/** The claim identity a fact tuple asserts on: entity.predicate. */
export function claimIdOf(tuple) {
  return `${tuple.value.entity}.${tuple.value.predicate}`;
}

/**
 * The named comparator. conflict(a, b) iff same claim id, single cardinality,
 * overlapping intervals and normalised values differ. Never consults the lock
 * rung — contradictions count across ALL rungs.
 */
export function singleValueOverlap(pack, a, b) {
  if (a.value.entity !== b.value.entity || a.value.predicate !== b.value.predicate) {
    return { conflict: false, reason: 'different-claim' };
  }
  if (cardinalityOf(pack, a.value.predicate) !== 'single') {
    return { conflict: false, reason: 'not-single-cardinality' };
  }
  validateInterval(a.interval);
  validateInterval(b.interval);
  if (a.interval.scope === 'unspecified' || b.interval.scope === 'unspecified') return { conflict: false, reason: 'scope-unspecified' };
  if (!intervalOverlaps(a.interval, b.interval)) {
    return { conflict: false, reason: 'intervals-disjoint' };
  }
  if (isDeepStrictEqual(normaliseValue(pack, a.value.object), normaliseValue(pack, b.value.object))) {
    return { conflict: false, reason: 'values-agree' };
  }
  return {
    conflict: true,
    comparator: COMPARATOR,
    claim: claimIdOf(a),
    values: [a.value.object, b.value.object],
    ids: [a.id, b.id],
  };
}
export { singleValueOverlap as single_value_overlap };

/**
 * A multi-valued predicate NEVER value-conflicts: two positive entries with
 * different objects coexist. It conflicts only against an EXPLICIT negation
 * entry — value.negation: true on the same normalised object, overlapping.
 */
export function multiNegationConflict(pack, a, b) {
  if (a.value.entity !== b.value.entity || a.value.predicate !== b.value.predicate) {
    return { conflict: false, reason: 'different-claim' };
  }
  if (cardinalityOf(pack, a.value.predicate) !== 'multi') {
    return { conflict: false, reason: 'not-multi-cardinality' };
  }
  validateInterval(a.interval);
  validateInterval(b.interval);
  if (a.interval.scope === 'unspecified' || b.interval.scope === 'unspecified') return { conflict: false, reason: 'scope-unspecified' };
  const aNeg = a.value.negation === true;
  const bNeg = b.value.negation === true;
  if (aNeg === bNeg) return { conflict: false, reason: 'no-explicit-negation-entry' };
  if (!intervalOverlaps(a.interval, b.interval)) {
    return { conflict: false, reason: 'intervals-disjoint' };
  }
  if (!isDeepStrictEqual(normaliseValue(pack, a.value.object), normaliseValue(pack, b.value.object))) {
    return { conflict: false, reason: 'different-objects' };
  }
  return {
    conflict: true,
    comparator: 'multi_negation',
    claim: claimIdOf(a),
    values: [a.value.object, b.value.object],
    ids: [a.id, b.id],
  };
}

/**
 * Does a decision cover a span's tuple? The decision's value.covers list
 * must name the tuple's id (or, for a fact, its claim id) with an interval
 * containing the span. The decision interval must also contain the span;
 * optional governs dependency metadata is not a coverage prerequisite.
 */
export function decisionCovers(decision, tuple) {
  if (!intervalContains(decision.interval, tuple.interval)) return false;
  const covers = Array.isArray(decision.value?.covers) ? decision.value.covers : [];
  return covers.some((span) => {
    if (!span?.interval || (span.id !== tuple.id && (tuple.kind !== 'fact' || span.id !== claimIdOf(tuple)))) return false;
    try {
      return intervalContains(span.interval, tuple.interval);
    } catch {
      return false; // malformed coverage cannot honour a superseded annotation
    }
  });
}

/** Minted iff lock: locked OR allow_terms present, without an acceptance receipt. */
export function isMinted(tuple) {
  if (hasAcceptance(tuple)) return null;
  if (tuple.lock === 'locked') return 'lock: locked without an acceptance receipt';
  if (Array.isArray(tuple.allow_terms) && tuple.allow_terms.length > 0) {
    return 'allow_terms without an acceptance receipt';
  }
  if (hasMintedFields(tuple)) return 'hand-set acceptance fields without a matching acceptance receipt';
  return null;
}

// ---------------------------------------------------------------------------
// Orders: the ONE series decision entry orders: {reader_order, written_order,
// cascade_position}. Until a decision says otherwise, reader order defaults
// to the pack's declared orders. Packs without defaults derive reader order
// from the books the threads touch and report that written order is unknown.
// ---------------------------------------------------------------------------

export function seriesOrders(tuples, defaultOrders) {
  const carriers = tuples
    .filter((t) => t.kind === 'decision' && t.interval.scope !== 'unspecified' && t.orders && typeof t.orders === 'object')
    .sort((a, b) => (a.id < b.id ? -1 : 1));
  if (carriers.length) {
    const o = carriers[0].orders;
    return {
      reader_order: o.reader_order || null,
      written_order: o.written_order || null,
      cascade_position: o.cascade_position ?? null,
      source: `decision ${carriers[0].id}`,
    };
  }
  if (defaultOrders && (defaultOrders.reader_order || defaultOrders.written_order)) {
    return {
      reader_order: defaultOrders.reader_order || null,
      written_order: defaultOrders.written_order || null,
      cascade_position: defaultOrders.cascade_position ?? null,
      source: 'default',
    };
  }
  let maxBook = 0;
  for (const t of tuples) {
    if (t.kind !== 'thread' || t.interval.scope) continue;
    for (const coord of threadCoords(t)) maxBook = Math.max(maxBook, parseCoord(coord)[0]);
  }
  const reader = [];
  for (let b = 1; b <= maxBook; b++) reader.push(b);
  return { reader_order: reader.length ? reader : null, written_order: null, cascade_position: null, source: 'default' };
}

function threadCoords(t) {
  const v = t.value;
  return [v.plant, v.due, v.pay, ...(Array.isArray(v.uses) ? v.uses : [])].filter(Boolean);
}

function posInOrder(order, coord) {
  return order.indexOf(parseCoord(coord)[0]);
}

function beforeInOrder(order, a, b) {
  const aPos = posInOrder(order, a);
  const bPos = posInOrder(order, b);
  return aPos < bPos || (aPos === bPos && parseCoord(a)[1] < parseCoord(b)[1]);
}

/**
 * The absence pass for ONE order. Every finding is stamped with the order it
 * fired on. On written_order the cascade position bounds the written pages:
 * a plant past it is NOT-YET-WRITTEN (on no written page yet), and a due past
 * it has not fallen due on any written page.
 */
export function absencesOnOrder(threads, order, orderName, cascadePosition) {
  const findings = [];
  const isWritten = orderName === 'written_order';
  let cascadeIdx = order.length - 1;
  if (isWritten && cascadePosition !== null && cascadePosition !== undefined) {
    const idx = order.indexOf(cascadePosition);
    if (idx >= 0) cascadeIdx = idx;
  }
  for (const t of threads) {
    if (t.interval.scope) continue;
    const v = t.value;
    const plantPos = posInOrder(order, v.plant);
    if (plantPos === -1) continue; // plant's book outside this order's scope

    if (isWritten && plantPos > cascadeIdx) {
      findings.push({
        order: orderName,
        class: 'NOT-YET-WRITTEN',
        thread: t.id,
        at: v.plant,
        note: `plant at ${v.plant} is on no written page yet at cascade position book ${order[cascadeIdx]}`,
      });
    }

    for (const use of [v.pay, ...(Array.isArray(v.uses) ? v.uses : [])].filter(Boolean)) {
      const usePos = posInOrder(order, use);
      if (usePos === -1 || (isWritten && usePos > cascadeIdx)) continue;
      if (beforeInOrder(order, use, v.plant)) {
        findings.push({
          order: orderName,
          class: 'USE-BEFORE-PLANT',
          thread: t.id,
          at: use,
          note: isWritten
            ? `use at ${use} lands before the plant at ${v.plant} in written order`
            : `use at ${use} before plant at ${v.plant} — a reader-facing break`,
        });
      }
    }

    const payPos = v.pay ? posInOrder(order, v.pay) : -1;
    const paidInScope = payPos !== -1 && (!isWritten || payPos <= cascadeIdx);
    if (!paidInScope && !v.release_reason) {
      const duePos = posInOrder(order, v.due);
      const dueInScope = duePos !== -1 && (!isWritten || duePos <= cascadeIdx);
      if (dueInScope) {
        findings.push({
          order: orderName,
          class: 'UNPAID-DUE',
          thread: t.id,
          at: v.due,
          note: `due at ${v.due}, unpaid at scope end`,
        });
      }
    }
  }
  return findings;
}

// ---------------------------------------------------------------------------
// The T0 run — pure over [{tuple, sidecar, prose}].
// ---------------------------------------------------------------------------

/**
 * Run T0 over the loaded entries. Pure: no I/O, no clock. Returns the classes
 * the report prints: contradictions (across ALL rungs), superseded (honoured
 * and unhonoured), receipt_drift, threads_due (reader order first, then
 * written order), minted, the effective ledger, and the orders that governed
 * the absence passes. The shared index is built in memory on every run.
 */
export function runT0(pack, entries, opts = {}) {
  const ledger = buildLedger(pack, entries);
  // Use the index's effective rungs while retaining the raw acceptance,
  // governs, orders and superseded_by metadata needed to check decisions.
  // Index rows alone intentionally omit those sidecar fields.
  const tuples = entries.map(({ tuple }) => ({ ...tuple, ...ledger.tuples[tuple.id] }));
  const byId = new Map();
  const originOf = new Map();
  for (const e of entries) {
    originOf.set(e.tuple.id, e.sidecar);
  }
  for (const tuple of tuples) byId.set(tuple.id, tuple);

  // Diagnose the raw annotation; the effective index above already demoted it.
  const minted = [];
  for (const { tuple: t } of entries) {
    const reason = isMinted(t);
    if (reason) minted.push({ id: t.id, reason: `${reason} (demoted to candidate)`, sidecar: originOf.get(t.id) });
  }

  // Superseded spans — honoured only by an existing, locked, accepted,
  // covering decision; otherwise unhonoured with the reason, and the span
  // COUNTS below.
  const superseded = [];
  const excluded = new Set();
  for (const t of tuples) {
    if (!t.superseded_by) continue;
    const decision = byId.get(t.superseded_by);
    let reason = null;
    if (!decision || decision.kind !== 'decision') reason = 'decision not found';
    else if (decision.lock !== 'locked' || !hasAcceptance(decision)) reason = 'decision not locked';
    else if (!decisionCovers(decision, t)) reason = 'decision does not cover the span';
    if (reason) {
      superseded.push({ id: t.id, superseded_by: t.superseded_by, honoured: false, reason });
    } else {
      superseded.push({ id: t.id, superseded_by: t.superseded_by, honoured: true });
      excluded.add(t.id);
    }
  }

  // Contradictions — across ALL rungs; only honoured-superseded spans are out.
  const contradictions = [];
  const byClaim = new Map();
  for (const t of tuples) {
    if (t.kind !== 'fact' || excluded.has(t.id)) continue;
    if (t.source === 'dialogue' && !(t.lock === 'locked' && hasAcceptance(t))) continue;
    const key = claimIdOf(t);
    if (!byClaim.has(key)) byClaim.set(key, []);
    byClaim.get(key).push(t);
  }
  const cite = (t) => ({ id: t.id, sidecar: originOf.get(t.id), receipt: t.receipt });
  const pending_scope = tuples.filter(t => t.interval.scope === 'unspecified'
    || (t.interval.scope === 'project' && ['thread', 'structural'].includes(t.kind)))
    .map(t => ({ ...cite(t), reason: t.interval.scope === 'unspecified'
      ? 'Timing unspecified; timing-dependent checks are pending.'
      : 'Project-wide note retained; no book/chapter placement has been supplied.' }));
  for (const claim of [...byClaim.keys()].sort()) {
    const group = byClaim.get(claim);
    const card = cardinalityOf(pack, group[0].value.predicate);
    for (let i = 0; i < group.length; i++) {
      for (let j = i + 1; j < group.length; j++) {
        const found = card === 'single'
          ? singleValueOverlap(pack, group[i], group[j])
          : card === 'multi'
            ? multiNegationConflict(pack, group[i], group[j])
            : { conflict: false, reason: 'unknown-predicate' };
        if (found.conflict) {
          contradictions.push({ ...found, cited: [cite(group[i]), cite(group[j])] });
        }
      }
    }
  }

  // Receipt drift — the stored span never moves; a fuzzy match is listed with
  // its proposed anchor, a vanished span is listed unanchored.
  const receipt_drift = [];
  for (const e of entries) {
    if (typeof e.prose !== 'string') continue;
    const resolved = resolveReceipt(e.prose, e.tuple.receipt);
    if (resolved.status === 'drift') {
      receipt_drift.push({
        id: e.tuple.id,
        sidecar: e.sidecar,
        stored_span: e.tuple.receipt.span,
        proposed: resolved.drift.proposed,
      });
    } else if (resolved.status === 'unanchored') {
      receipt_drift.push({
        id: e.tuple.id,
        sidecar: e.sidecar,
        stored_span: e.tuple.receipt.span,
        proposed: null,
        note: 'span not found in the prose',
      });
    }
  }

  // Absences on BOTH orders — reader order first, then written order.
  const orders = seriesOrders(tuples, opts.default_orders || pack.default_orders);
  const threads = tuples.filter((t) => t.kind === 'thread' && !t.interval.scope && !excluded.has(t.id));
  const threads_due = [];
  if (orders.reader_order) {
    threads_due.push(...absencesOnOrder(threads, orders.reader_order, 'reader_order', null));
  }
  if (orders.written_order) {
    threads_due.push(...absencesOnOrder(threads, orders.written_order, 'written_order', orders.cascade_position));
  }

  const alias_drift = tuples.filter((t) => t.kind === 'alias' && t.value.variants.length > 1
    && !(t.authorial_rename === true && t.lock === 'locked' && hasAcceptance(t)))
    .map((t) => ({ id: t.id, target: t.value.target, variants: t.value.variants,
      interval: t.interval, cited: [cite(t)] }));
  return {
    comparator: COMPARATOR,
    ledger,
    contradictions,
    superseded,
    receipt_drift,
    threads_due,
    minted,
    alias_drift,
    pending_scope,
    orders,
    counts: { contradictions: contradictions.length },
  };
}

/**
 * Load every sidecar (and its prose) under a root and run T0. The pack comes
 * from <root>/chekhov/config.json unless the caller passes one; an orders
 * default may sit in config.json under "orders" until the series decision
 * entry exists. Reads only; writes nothing.
 */
export function t0ForRoot(root, { pack, packsDir, documents: suppliedDocuments, manuscripts: suppliedManuscripts } = {}) {
  const started = Date.now();
  const p = pack || loadProjectPack(root, { packsDir });
  const entries = loadLedgerEntries(root);
  let defaultOrders = null;
  try {
    const config = JSON.parse(fs.readFileSync(path.join(root, 'chekhov', 'config.json'), 'utf8'));
    if (config.orders && typeof config.orders === 'object') defaultOrders = config.orders;
  } catch {
    /* no config or no orders default — the fixture default applies */
  }
  const result = runT0(p, entries, { default_orders: defaultOrders });
  const effective = entries.map(({ tuple }) => ({ ...tuple, ...result.ledger.tuples[tuple.id], id: tuple.id }));
  const documents = suppliedDocuments || projectDocuments(root);
  const manuscripts = suppliedManuscripts || projectDocuments(root, { manuscripts: true });
  result.prose = scanProse(documents);
  for (const conflict of result.prose.contradictions) {
    const tupleConflict = result.contradictions.find((c) => c.claim === conflict.claim);
    if (tupleConflict) tupleConflict.spans = conflict.spans;
    else result.contradictions.push(conflict);
  }
  result.counts.contradictions = result.contradictions.length;
  result.criterion1 = result.contradictions.length === 0 && result.prose.single_valued && result.pending_scope.length === 0;
  result.structure = buildStructuralRecord({ pack: p, documents, manuscripts, tuples: effective, prose: result.prose });
  let commitReceipts = [];
  const sessionFile = path.join(root, 'chekhov', 'session.json');
  if (fs.existsSync(sessionFile)) commitReceipts = JSON.parse(fs.readFileSync(sessionFile, 'utf8')).receipts || [];
  result.gate = outlineGate({ tuples: effective, ledger: result.ledger, prose: result.prose, commitReceipts });
  result.doctrine = scanDoctrine(documents, { tag: result.gate.values['series.doctrine_tag'][0] || p.name,
    decisions: effective.filter((t) => t.kind === 'decision'), structural: effective.filter((t) => t.kind === 'structural') });
  result.duration_ms = Date.now() - started;
  result.tuple_count = entries.length;
  return result;
}

// ---------------------------------------------------------------------------
// LEDGER-REPORT.md — line 1 contradictions=N (T0 only), then FOUR sections in
// order: contradictions (including the minted list), superseded,
// receipt-drift, threads due — with W2's coverage list beneath.
// ---------------------------------------------------------------------------

export function reportPath(stateDir) {
  return path.join(stateDir, 'LEDGER-REPORT.md');
}

function quote(text, max = 100) {
  const s = String(text).replace(/\s+/g, ' ').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function receiptLine(cited) {
  const r = cited.receipt;
  const headings = Array.isArray(r.heading_path) ? r.heading_path.join(' > ') : String(r.heading_path);
  return `  - ${cited.id}: "${quote(r.span)}" (${headings}, line ${r.line_hint}; ${cited.sidecar})`;
}

/** Render the four-section report. Deterministic: no clock, no host paths. */
export function renderLedgerReport(t0, coverage) {
  const lines = [`contradictions=${t0.contradictions.length}`, ''];

  lines.push('## Contradictions', '');
  if (!t0.contradictions.length) lines.push('- none');
  for (const c of t0.contradictions) {
    lines.push(`- ${c.claim}: ${c.values.map((v) => JSON.stringify(v)).join(' vs ')} (${c.comparator})`);
    for (const cited of c.cited || []) lines.push(receiptLine(cited));
    for (const span of c.spans || []) lines.push(`  - "${quote(span.span)}" (${span.heading_path.join(' > ')}, line ${span.line}; ${span.file})`);
  }
  lines.push('');

  lines.push('### Minted', '');
  if (!t0.minted.length) lines.push('- none');
  for (const m of t0.minted) lines.push(`- ${m.id} — ${m.reason} (${m.sidecar})`);
  lines.push('');

  lines.push('### Scope pending', '');
  if (!t0.pending_scope?.length) lines.push('- none');
  for (const row of t0.pending_scope || []) lines.push(`- ${row.id}: ${row.reason}`, receiptLine(row));
  if (t0.pending_scope?.length) lines.push('- Zero reported contradictions does not resolve these pending checks.');
  lines.push('');

  lines.push('### Alias drift', '');
  for (const drift of t0.alias_drift || []) {
    lines.push(`- ${drift.id}: ${drift.variants.join(' / ')} (unaccepted naming pair)`);
    for (const cited of drift.cited) lines.push(receiptLine(cited));
  }

  lines.push('## Superseded', '');
  if (!t0.superseded.length) lines.push('- none');
  for (const s of t0.superseded) {
    lines.push(s.honoured
      ? `- ${s.id} superseded_by ${s.superseded_by} — honoured (span excluded)`
      : `- ${s.id} superseded_by ${s.superseded_by} — unhonoured: ${s.reason} (the span counts)`);
  }
  lines.push('');

  lines.push('## Receipt drift', '');
  if (!t0.receipt_drift.length) lines.push('- none');
  for (const d of t0.receipt_drift) {
    lines.push(d.proposed
      ? `- ${d.id}: stored span "${quote(d.stored_span)}" no longer matches; proposed line ${d.proposed.line_hint}: "${quote(d.proposed.span)}" (${d.sidecar})`
      : `- ${d.id}: stored span "${quote(d.stored_span)}" — ${d.note} (${d.sidecar})`);
  }
  lines.push('');

  lines.push('## Threads due', '');
  if (!t0.threads_due.length) lines.push('- none');
  for (const f of t0.threads_due) {
    lines.push(`- ${f.order}: ${f.class} ${f.thread} — ${f.note}`);
  }
  if (t0.orders && !t0.orders.written_order) {
    lines.push('- written order: not decided — the written-order pass did not run');
  }
  lines.push('');

  lines.push('## Coverage', '');
  const unmigrated = (coverage && coverage.unmigrated_docx) || [];
  const generators = (coverage && coverage.generators_frozen) || [];
  if (!unmigrated.length) lines.push('- unmigrated docx: none');
  for (const rel of unmigrated) lines.push(`- unmigrated docx: ${rel}`);
  for (const g of generators) lines.push(`- generator ${g.rel} — ${g.status} (${g.note})`);
  lines.push('');

  if (t0.prose) {
    lines.push('### Prose evidence', '', `criterion 1: ${t0.criterion1 ? 'GREEN' : 'NOT GREEN'} (zero contradictions, no pending scope, and all three named ids single-valued on prose)`, '');
    for (const [id, values] of Object.entries(t0.prose.values)) lines.push(`- ${id}: ${values.length === 1 ? 'single-valued' : values.length ? 'conflicting' : 'missing'} on prose`);
    for (const h of t0.prose.hits) lines.push(`- ${h.id}: ${JSON.stringify(h.value)} — "${quote(h.span)}" (${h.heading_path.join(' > ')}, line ${h.line}; ${h.file})`);
    lines.push('', '### Doctrine', '');
    if (!t0.doctrine.hits.length) lines.push('- none');
    for (const h of t0.doctrine.hits) lines.push(`- ${h.doctrine}: ${h.term} — "${quote(h.span)}" (${h.heading_path.join(' > ')}, line ${h.line}; ${h.file})`);
    lines.push('', '### Outline intake', '', ...t0.gate.lines, '', '### Structural record', '', ...renderStructure(t0.structure), '');
  }

  return `${lines.join('\n')}\n`;
}

/**
 * Append one timing figure to the skill's journal/runs/ (the W4 timing gate
 * writes the measured T0 figure through this, in the foundry run-record
 * naming convention).
 */
export function appendRunRecord(record) {
  const dir = path.join(MODULE_DIR, '..', 'journal', 'runs');
  fs.mkdirSync(dir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const file = path.join(dir, `${ts}-${process.pid}.json`);
  fs.writeFileSync(file, `${JSON.stringify({ at: new Date().toISOString(), ...record }, null, 2)}\n`, 'utf8');
  return file;
}
