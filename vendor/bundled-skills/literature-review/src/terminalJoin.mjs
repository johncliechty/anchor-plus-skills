// Wave 4 — structural deterministic terminal join.
// Replaces the lossy LLM semantic merge: the isolated thread outputs from the
// MatrixScheduler (Wave 2) carrying grounded quote records (Wave 3) are merged
// STRUCTURALLY — pure data joins, no model in the loop — into one inline
// Assumptions Ledger. Determinism: the joined ledger is a pure function of the
// SET of thread outputs (canonical sort keys everywhere, no timestamps, no
// randomness), so any completion order of the threads produces byte-identical
// output.
//
// Every input record is accounted for — the no-silent-loss invariant:
//   claims (accepted + rejected) + duplicatesMerged === total records seen,
//   threads === completedThreads + failedThreads.
// A claim is ACCEPTED only after it re-proves its evidence lineage here at the
// join (never on the worker's word alone):
//   1. structural verification — the record carries a complete, well-typed
//      evidence block (claimId, quotes, integer offsets, occurrences >= 1);
//   2. lineage re-verification — when the raw source text is provided, the
//      recorded [start, end) span is re-extracted and must reproduce the
//      record's quotes exactly (lineage: "VERIFIED"); without the source the
//      claim carries lineage: "STRUCTURAL" so the weaker guarantee is visible.
// Anything that fails is rejected EXPLICITLY with a reason and kept in the
// ledger's rejected partition, prominently — never silently dropped. Failed
// threads are documented the same way.
//
// Every accepted claim is rigidly hyperlinked: its evidence block carries a
// deterministic anchor (evidence-s<sourceIndex>-<start>-<end>) that
// formatEvidenceLedgerMarkdown turns into inline [quote](#anchor) links backed
// by an anchored evidence appendix of the exact verbatim spans.

import { normalizeText } from './textNormalization.mjs';
import { sanitizeText } from './structuralSanitizer.mjs';
import { validateSchema } from './validateSchema.mjs';
import { evidenceLedgerSchema } from './schemas/evidenceLedger.mjs';

function cmp(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

// Accept either the scheduler's drained report ({completed, failed}) or a
// plain array of settled entries; give every entry an integer batchId and put
// the entries in canonical batchId order so the join never depends on
// completion order.
function normalizeEntries(reportOrEntries) {
  const raw = Array.isArray(reportOrEntries)
    ? reportOrEntries
    : [...(reportOrEntries?.completed ?? []), ...(reportOrEntries?.failed ?? [])];
  return raw
    .map((entry, index) => ({
      entry: entry && typeof entry === 'object' ? entry : {},
      batchId: Number.isInteger(entry?.batchId) ? entry.batchId : index
    }))
    .sort((a, b) => a.batchId - b.batchId || cmp(String(a.entry.paperId ?? ''), String(b.entry.paperId ?? '')));
}

// Worker outputs cross IPC sanitized, so their paperId strings are the
// sanitized form; index the caller's sources under both spellings so lineage
// re-verification finds the raw text either way.
function buildSourceLookup(sources) {
  const lookup = new Map();
  if (!sources) return lookup;
  const pairs = sources instanceof Map ? sources.entries() : Object.entries(sources);
  for (const [key, text] of pairs) {
    lookup.set(String(key), String(text));
    lookup.set(sanitizeText(String(key)), String(text));
  }
  return lookup;
}

function structuralIssues(record) {
  const issues = [];
  if (!record || typeof record !== 'object') return ['record must be an object'];
  if (typeof record.claimId !== 'string' || record.claimId.length === 0) issues.push('claimId must be a non-empty string');
  if (typeof record.statement !== 'string') issues.push('statement must be a string');
  if (typeof record.verbatimQuote !== 'string' || record.verbatimQuote.length === 0) issues.push('verbatimQuote must be a non-empty string');
  if (typeof record.normalizedQuote !== 'string' || record.normalizedQuote.length === 0) issues.push('normalizedQuote must be a non-empty string');
  if (!Number.isInteger(record.start) || record.start < 0) issues.push('start must be an integer at least 0');
  if (!Number.isInteger(record.end) || !Number.isInteger(record.start) || record.end <= record.start) issues.push('end must be an integer greater than start');
  if (!Number.isInteger(record.occurrences) || record.occurrences < 1) issues.push('occurrences must be a positive integer');
  if (record.column !== undefined && record.column !== null && typeof record.column !== 'string') issues.push('column must be a string or null');
  return issues;
}

// Re-prove the unbroken evidence lineage: the raw [start, end) span of the
// primary source must reproduce BOTH recorded quote forms exactly (the worker
// sanitizes its outputs, so the comparison happens in sanitized space).
function lineageMismatch(record, rawSource) {
  const rawSpan = String(rawSource).slice(record.start, record.end);
  if (sanitizeText(rawSpan) !== record.verbatimQuote) {
    return 'recorded verbatimQuote does not match the raw source span';
  }
  if (sanitizeText(normalizeText(rawSpan)) !== record.normalizedQuote) {
    return 'recorded normalizedQuote does not match the normalized raw source span';
  }
  return null;
}

/**
 * Deterministically join isolated thread outputs into one EvidenceLedger.
 *
 * @param {object|Array} reportOrEntries the MatrixScheduler run() report
 *   ({completed, failed}) or a flat array of settled batch entries.
 * @param {{sources?: object|Map}} [options] optional map paperId -> raw source
 *   text; when a claim's source is present its lineage is re-verified here
 *   (lineage "VERIFIED"), otherwise the claim carries lineage "STRUCTURAL".
 * @returns {object} an EvidenceLedger (validated against evidenceLedgerSchema).
 */
export function terminalJoin(reportOrEntries, { sources = null } = {}) {
  const entries = normalizeEntries(reportOrEntries);
  const sourceLookup = buildSourceLookup(sources);

  const paperMeta = new Map(); // paperId -> {title, threadIds:Set}
  const acceptedByKey = new Map();
  const rejectedByKey = new Map();
  const failedThreads = [];
  let completedThreads = 0;
  let duplicatesMerged = 0;

  const notePaper = (paperId, entry, batchId) => {
    if (!paperMeta.has(paperId)) paperMeta.set(paperId, { title: null, threadIds: new Set() });
    const meta = paperMeta.get(paperId);
    meta.threadIds.add(batchId);
    if (meta.title === null && typeof entry.title === 'string') meta.title = sanitizeText(entry.title);
  };

  const addRejected = (fields, batchId, workerId) => {
    const key = JSON.stringify([fields.paperId, fields.claimId, fields.column, fields.quote, fields.reason]);
    const existing = rejectedByKey.get(key);
    if (existing) {
      duplicatesMerged += 1;
      existing.batchIds.add(batchId);
      if (workerId) existing.workerIds.add(workerId);
      return;
    }
    rejectedByKey.set(key, { ...fields, batchIds: new Set([batchId]), workerIds: new Set(workerId ? [workerId] : []) });
  };

  const addAccepted = (fields, batchId, workerId) => {
    const key = JSON.stringify([fields.paperId, fields.claimId, fields.column, fields.start, fields.end, fields.normalizedQuote]);
    const existing = acceptedByKey.get(key);
    if (existing) {
      duplicatesMerged += 1;
      existing.batchIds.add(batchId);
      if (workerId) existing.workerIds.add(workerId);
      return;
    }
    acceptedByKey.set(key, { ...fields, batchIds: new Set([batchId]), workerIds: new Set(workerId ? [workerId] : []) });
  };

  for (const { entry, batchId } of entries) {
    const workerId = typeof entry.workerId === 'string' ? sanitizeText(entry.workerId) : null;

    if (entry.status !== 'completed') {
      const paperId = sanitizeText(String(entry.paperId ?? 'unknown'));
      notePaper(paperId, entry, batchId);
      failedThreads.push({
        batchId,
        paperId,
        workerId,
        error: {
          name: sanitizeText(String(entry.error?.name ?? 'Error')),
          message: sanitizeText(String(entry.error?.message ?? 'unknown failure'))
        }
      });
      continue;
    }

    const result = entry.result;
    if (!result || typeof result !== 'object' || !Array.isArray(result.quotes) || !Array.isArray(result.rejected)) {
      const paperId = sanitizeText(String(entry.paperId ?? 'unknown'));
      notePaper(paperId, entry, batchId);
      failedThreads.push({
        batchId,
        paperId,
        workerId,
        error: {
          name: 'MalformedThreadOutput',
          message: 'completed thread returned no structurally valid extraction result: quotes/rejected arrays missing'
        }
      });
      continue;
    }

    completedThreads += 1;
    const paperId = typeof result.paperId === 'string' && result.paperId.length > 0
      ? result.paperId
      : sanitizeText(String(entry.paperId ?? 'unknown'));
    notePaper(paperId, entry, batchId);
    const rawSource = sourceLookup.has(paperId) ? sourceLookup.get(paperId) : null;

    for (const record of result.quotes) {
      const issues = structuralIssues(record);
      const column = record && typeof record.column === 'string' ? record.column : null;
      const claimId = typeof record?.claimId === 'string' && record.claimId ? record.claimId : 'unknown-claim';
      const statement = typeof record?.statement === 'string' ? record.statement : '';
      if (issues.length > 0) {
        addRejected({
          claimId, statement, paperId, column,
          quote: typeof record?.normalizedQuote === 'string' ? record.normalizedQuote : null,
          reason: 'structurally-unverified',
          rejection: `STRUCTURALLY-UNVERIFIED: ${issues.join('; ')}`
        }, batchId, workerId);
        continue;
      }
      if (rawSource !== null) {
        const mismatch = lineageMismatch(record, rawSource);
        if (mismatch) {
          addRejected({
            claimId, statement, paperId, column,
            quote: record.normalizedQuote,
            reason: 'lineage-mismatch',
            rejection: `LINEAGE-MISMATCH: ${mismatch}; the claim does not re-verify against the primary source`
          }, batchId, workerId);
          continue;
        }
      }
      addAccepted({
        claimId, statement, paperId, column,
        lineage: rawSource !== null ? 'VERIFIED' : 'STRUCTURAL',
        verbatimQuote: record.verbatimQuote,
        normalizedQuote: record.normalizedQuote,
        start: record.start,
        end: record.end,
        occurrences: record.occurrences
      }, batchId, workerId);
    }

    for (const record of result.rejected) {
      const rec = record && typeof record === 'object' ? record : {};
      addRejected({
        claimId: typeof rec.claimId === 'string' && rec.claimId ? rec.claimId : 'unknown-claim',
        statement: typeof rec.statement === 'string' ? rec.statement : '',
        paperId,
        column: typeof rec.column === 'string' ? rec.column : null,
        quote: typeof rec.quote === 'string' ? rec.quote : null,
        reason: typeof rec.reason === 'string' && rec.reason ? rec.reason : 'unspecified',
        rejection: typeof rec.rejection === 'string' && rec.rejection
          ? rec.rejection
          : 'REJECTED-BY-THREAD: the extraction thread rejected this claim without a recorded message'
      }, batchId, workerId);
    }
  }

  // Canonical source order -> deterministic anchor prefixes.
  const sourcesList = [...paperMeta.entries()]
    .sort((a, b) => cmp(a[0], b[0]))
    .map(([paperId, meta]) => ({
      paperId,
      title: meta.title,
      threadIds: [...meta.threadIds].sort((a, b) => a - b)
    }));
  const sourceIndex = new Map(sourcesList.map((s, i) => [s.paperId, i]));

  const accepted = [...acceptedByKey.values()]
    .sort((a, b) =>
      cmp(a.paperId, b.paperId) || (a.start - b.start) || (a.end - b.end) ||
      cmp(a.claimId, b.claimId) || cmp(a.column ?? '', b.column ?? ''))
    .map((r) => ({
      claimId: r.claimId,
      statement: r.statement,
      paperId: r.paperId,
      column: r.column,
      lineage: r.lineage,
      evidence: {
        anchor: `evidence-s${sourceIndex.get(r.paperId)}-${r.start}-${r.end}`,
        verbatimQuote: r.verbatimQuote,
        normalizedQuote: r.normalizedQuote,
        start: r.start,
        end: r.end,
        occurrences: r.occurrences
      },
      provenance: {
        batchIds: [...r.batchIds].sort((a, b) => a - b),
        workerIds: [...r.workerIds].sort(cmp)
      }
    }));

  const rejected = [...rejectedByKey.values()]
    .sort((a, b) =>
      cmp(a.paperId, b.paperId) || cmp(a.claimId, b.claimId) ||
      cmp(a.column ?? '', b.column ?? '') || cmp(a.reason, b.reason) || cmp(a.quote ?? '', b.quote ?? ''))
    .map((r) => ({
      claimId: r.claimId,
      statement: r.statement,
      paperId: r.paperId,
      column: r.column,
      quote: r.quote,
      reason: r.reason,
      rejection: r.rejection,
      provenance: {
        batchIds: [...r.batchIds].sort((a, b) => a - b),
        workerIds: [...r.workerIds].sort(cmp)
      }
    }));

  failedThreads.sort((a, b) => a.batchId - b.batchId || cmp(a.paperId, b.paperId));

  const ledger = {
    stats: {
      threads: entries.length,
      completedThreads,
      failedThreads: failedThreads.length,
      claims: accepted.length + rejected.length,
      accepted: accepted.length,
      rejected: rejected.length,
      duplicatesMerged
    },
    sources: sourcesList,
    accepted,
    rejected,
    failedThreads
  };

  validateSchema(ledger, evidenceLedgerSchema);
  return ledger;
}

/**
 * Render the joined ledger as the inline Markdown Assumptions Ledger: every
 * accepted claim's exact quote is a hyperlink into the anchored evidence
 * appendix, and rejected claims / failed threads get their own prominent,
 * always-present sections. Pure function of the ledger — deterministic.
 */
export function formatEvidenceLedgerMarkdown(ledger) {
  const s = ledger.stats;
  const lines = [];
  lines.push('# Assumptions Ledger — structural deterministic terminal join', '');
  lines.push('## Overview', '');
  lines.push(`- **Threads:** ${s.completedThreads} completed, ${s.failedThreads} failed (of ${s.threads})`);
  lines.push(`- **Claims:** ${s.accepted} accepted, ${s.rejected} rejected (${s.claims} total; ${s.duplicatesMerged} duplicate record(s) merged)`);
  lines.push(`- **Sources:** ${ledger.sources.map((src) => src.paperId).join(', ') || 'none'}`);
  lines.push('');
  if (s.rejected > 0 || s.failedThreads > 0) {
    lines.push(
      `> ⚠ **${s.rejected} claim(s) were REJECTED and ${s.failedThreads} thread(s) FAILED.** ` +
      'Every one is documented in [Rejected claims](#rejected-claims) and [Failed threads](#failed-threads) below — ' +
      'nothing was silently dropped.', '');
  }

  lines.push('## Accepted claims', '');
  if (ledger.accepted.length === 0) {
    lines.push('_None._', '');
  } else {
    lines.push('| Claim | Source | Column | Statement | Exact quote (hyperlinked) | Lineage |');
    lines.push('| --- | --- | --- | --- | --- | --- |');
    for (const a of ledger.accepted) {
      lines.push(
        `| ${a.claimId} | ${a.paperId} | ${a.column ?? '—'} | ${a.statement || '—'} ` +
        `| [“${a.evidence.normalizedQuote}”](#${a.evidence.anchor}) | ${a.lineage} |`);
    }
    lines.push('');
  }

  lines.push('<a id="rejected-claims"></a>', '', '## ⚠ Rejected claims', '');
  if (ledger.rejected.length === 0) {
    lines.push('_None — every extracted claim re-verified at the join._', '');
  } else {
    lines.push('| Claim | Source | Column | Statement | Candidate quote | Reason | Rejection |');
    lines.push('| --- | --- | --- | --- | --- | --- | --- |');
    for (const r of ledger.rejected) {
      lines.push(
        `| ${r.claimId} | ${r.paperId} | ${r.column ?? '—'} | ${r.statement || '—'} ` +
        `| ${r.quote ?? '—'} | ${r.reason} | ${r.rejection} |`);
    }
    lines.push('');
  }

  lines.push('<a id="failed-threads"></a>', '', '## ⚠ Failed threads', '');
  if (ledger.failedThreads.length === 0) {
    lines.push('_None — every thread output was consumed._', '');
  } else {
    lines.push('| Thread | Source | Worker | Error |');
    lines.push('| --- | --- | --- | --- |');
    for (const f of ledger.failedThreads) {
      lines.push(`| ${f.batchId} | ${f.paperId} | ${f.workerId ?? '—'} | ${f.error.name}: ${f.error.message} |`);
    }
    lines.push('');
  }

  lines.push('## Evidence appendix', '');
  const seen = new Set();
  for (const a of ledger.accepted) {
    if (seen.has(a.evidence.anchor)) continue;
    seen.add(a.evidence.anchor);
    lines.push(`### <a id="${a.evidence.anchor}"></a> ${a.paperId} — chars ${a.evidence.start}–${a.evidence.end}`, '');
    lines.push(`> ${a.evidence.verbatimQuote}`, '');
    lines.push(`- Normalized form: ${a.evidence.normalizedQuote}`);
    lines.push(`- Occurrences in source: ${a.evidence.occurrences}`, '');
  }
  if (seen.size === 0) lines.push('_No evidence — no claims were accepted._', '');

  return lines.join('\n');
}
