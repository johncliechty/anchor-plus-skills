function esc(s) { return String(s ?? ''); }

export function renderReport(result) {
  const lines = [];
  lines.push('# Superjump report');
  lines.push('');
  lines.push(`Status: ${result.status || 'unknown'}`);
  lines.push('');
  lines.push('## Fit Contract');
  const c = result.contract || {};
  if (c.deliverable) lines.push(`- Deliverable: ${esc(c.deliverable.kind || c.deliverable)}`);
  for (const m of (c.must || [])) lines.push(`- MUST ${m.id} (${m.source}): ${m.text}`);
  for (const f of (c.fixed || [])) lines.push(`- FIXED ${f.id} (${f.source}): ${f.text}`);
  for (const x of (c.forbid || [])) lines.push(`- FORBID ${x.id} (${x.source}): ${x.text}`);
  for (const j of (c.judge || [])) lines.push(`- JUDGE ${j.id} ${j.axis} weight ${j.weight} (${j.source})`);
  lines.push('');
  lines.push('## Survivors');
  const byK = new Map((result.candidates || []).map((x) => [x.k, x]));
  for (const k of (result.order || [])) {
    const cand = byK.get(k);
    if (!cand) continue;
    lines.push(`### ${k}. ${esc(cand.leap?.domain)}`);
    lines.push(`- Mechanism: ${esc(cand.leap?.mechanism)}`);
    lines.push(`- Rating: ${cand.assessment?.rating ?? 'n/a'}`);
    if (cand.assessment?.uncertain?.length) lines.push(`- Uncertain: ${cand.assessment.uncertain.join('; ')}`);
    lines.push('');
    lines.push(esc(cand.leap?.deliverable));
    lines.push('');
    lines.push(`Smallest test (unperformed): ${esc(cand.leap?.smallestTest)}`);
    lines.push('');
  }
  const killed = (result.candidates || []).filter((x) => x.status === 'killed');
  if (killed.length) {
    lines.push('## Kills');
    for (const cand of killed) {
      lines.push(`- ${cand.k}. ${esc(cand.leap?.domain)} — ${cand.assessment?.killed?.term}: ${esc(cand.assessment?.killed?.passage)}`);
    }
    lines.push('');
  }
  const unjudged = (result.candidates || []).filter((x) => x.status === 'unjudged');
  if (unjudged.length) {
    lines.push('## Unjudged');
    for (const cand of unjudged) lines.push(`- ${cand.k}. ${esc(cand.error || cand.leap?.domain || 'unjudged')}`);
    lines.push('');
  }
  if (result.dedupe) {
    lines.push('## Duplicates');
    for (const g of result.dedupe) lines.push(`- members ${JSON.stringify(g.members)} — ${esc(g.reason)}`);
    lines.push('');
  }
  lines.push('## Process');
  lines.push(`- first reviewed: +${result.clocks?.firstReviewedS ?? '?'}s`);
  lines.push(`- portfolio: +${result.clocks?.portfolioS ?? '?'}s`);
  lines.push(`- total: ${result.totalS ?? '?'}s`);
  lines.push(`- seats: coding ${result.seating?.codingFamily} / review ${result.seating?.reviewFamily}`);
  if (result.progress?.recommend_kill?.length) {
    lines.push('- recommend_kill: ' + JSON.stringify(result.progress.recommend_kill));
  }
  lines.push('');
  return lines.join('\n');
}
