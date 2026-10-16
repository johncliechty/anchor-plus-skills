/** W5 intake: computed suggestions only; no author decisions or receipts are written. */
import fs from 'node:fs';
import { hasAcceptance } from './tuples.mjs';
import { fold, chapterRule, bookCount } from './prose.mjs';

const recommendations = JSON.parse(fs.readFileSync(new URL('../packs/brightheart-intake.json', import.meta.url), 'utf8'));

export function decisionValues(decisions, id) {
  return [...new Map(decisions.filter((d) => d.kind === 'decision' && d.interval?.scope !== 'unspecified').flatMap((d) => {
    let value;
    if (d.value?.entity === 'series' && `series.${d.value.predicate}` === id) value = d.value.object;
    else if (d.id === id || d.value?.topic === id) value = d.value?.object ?? d.value?.answer ?? d.value;
    else if (d.value && Object.hasOwn(d.value, id.split('.').at(-1))) value = d.value[id.split('.').at(-1)];
    if (value === null || value === undefined || value === '' || (typeof value === 'object' && ('topic' in value || 'covers' in value))) return [];
    if (id === 'series.book_count') value = bookCount(value);
    if (id === 'series.chapter_rule') value = chapterRule(value);
    if (id === 'series.doctrine_tag') value = typeof value === 'string' ? fold(value).trim() || null : null;
    return value === null || (typeof value === 'number' && (!Number.isInteger(value) || value < 1)) ? [] : [[JSON.stringify(value), value]];
  })).values()];
}

/** Walk the existing index dependency directions, counting each affected id once. */
export function rippleFor(ledger, seeds) {
  const rows = ledger?.tuples || {};
  const seen = new Set(seeds);
  const queue = [...seeds];
  while (queue.length) {
    const id = queue.pop();
    const next = rows[id]?.kind === 'decision' ? [...(rows[id].depends_on || [])] : [];
    for (const [key, row] of Object.entries(rows)) {
      if (row.kind !== 'decision' && row.depends_on?.includes(id)) next.push(key);
    }
    for (const key of next) if (!seen.has(key)) { seen.add(key); queue.push(key); }
  }
  return [...seen].filter((id) => !seeds.includes(id)).sort();
}

/** Only successful commit receipts covering BOTH books establish fork coverage. */
export function forkPackage(tuples, commitReceipts = []) {
  const threads = tuples.filter((t) => t.kind === 'thread' && !t.interval?.scope && /^7\./.test(String(t.value?.due)));
  const accepted = threads.filter((t) => t.lock === 'locked' && hasAcceptance(t) && t.receipt?.span?.trim() && t.receipt?.heading_path?.length && Number.isInteger(t.receipt?.line_hint));
  const covered = new Set(commitReceipts.filter((r) => r.transition === 'commit' && !r.invalidated && r.ok !== false).flatMap((r) => r.books || r.scope?.books || []));
  const known = accepted.length > 0 && covered.has(6) && covered.has(7);
  return {
    known, count: known ? accepted.length : null, thread_entries: threads.length, accepted: accepted.length,
    ids: accepted.map((t) => t.id).sort(),
    text: known ? `fork package: ${accepted.length} accepted, receipt-bearing threads due in Book 7 (${accepted.map((t) => t.id).sort().join(', ')})`
      : `fork package: unknown (${threads.length} thread entries, ${accepted.length} accepted)`,
  };
}

export function brightHeartAsks({ tuples = [], ledger, prose, commitReceipts = [] } = {}) {
  const fork = forkPackage(tuples, commitReceipts);
  const specs = [
    ['series.western_layer', 'Keep a Western layer? Name any allowed terms in allow_terms.', recommendations.western_layer],
    ['series.doctrine_tag', 'Which single doctrine governs this project?', recommendations.doctrine_tag],
    ['series.book_count', 'Six or seven books? Resolve the Book 7 fork package before deciding.', fork.known ? `Review the ${fork.count} accepted Book 7 promises before choosing six or seven; retain a seventh book if those promises cannot be paid in six.` : null],
    ['series.book1_boundary', 'Where does Book 1 end?', 'Review the cut-after-a-triumph candidates and keep a complete Book 1 promise and closure; apply the duology checklist before splitting.'],
    ['series.chapter_rule', 'Which single chapter-length rule governs revisions?', 'Settle ask (6), age category, before choosing a length target; then reconcile the bible rule and outline expansions.'],
    ['series.age_category', 'Which age category is intended? Answer before choosing any length target; this ask never blocks.', 'Choose the intended reader first, using the approved Harry-Potter-1 comparison as context, then set length.'],
    ['series.naming', 'Are el/Remi/Elra, Raggi/Corvo, and Daguan/Durgan deliberate renames or drift?', 'Confirm each pair separately; preserve stable ids with dated aliases for deliberate renames and repair only confirmed drift.'],
  ];
  return specs.map(([id, question, recommendation], i) => {
    const seeds = [id];
    // Seed the claim's actual index entries, so a differently named decision
    // and its governs closure contribute to the same ask.
    seeds.push(...tuples.filter((t) => t.value?.entity === 'series' && `series.${t.value?.predicate}` === id || t.value?.topic === id).map((t) => t.id));
    if (i === 6) seeds.push(...Object.entries(ledger?.tuples || {}).filter(([, row]) => row.kind === 'alias' && row.value?.variants?.some((v) => /^(el|remi|elra|raggi|corvo|daguan|durgan)$/i.test(v))).flatMap(([key, row]) => [key, row.value.target]));
    const ripple = rippleFor(ledger, seeds);
    return { number: i + 1, id, question, recommendation, ripple_count: ripple.length, ripple,
      context: (prose?.hits || []).filter((h) => h.id === id), ...(i === 2 ? { fork_package: fork } : {}) };
  });
}

export function renderAsks(asks) {
  const lines = ['Age category must be answered before any length target; ask (6) never blocks.', ''];
  for (const ask of asks) {
    lines.push(`(${ask.number}) ${ask.question}`, `Ripple: ${ask.ripple_count}${ask.ripple.length ? ` (${ask.ripple.join(', ')})` : ''}`);
    if (ask.fork_package) lines.push(ask.fork_package.text);
    if (ask.recommendation) lines.push(`Recommendation: ${ask.recommendation}`);
    for (const hit of ask.context || []) lines.push(`Context: "${hit.span}" (${hit.heading_path.join(' > ')}, line ${hit.line}; ${hit.file})`);
  }
  return lines;
}
