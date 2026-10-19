// Fit Contract — parse the brief, lint phrases, assess a judged candidate, reweight.
const KEYS = ['DELIVERABLE', 'MUST', 'FIXED', 'FORBID', 'JUDGE'];

function splitItems(text) {
  return String(text ?? '')
    .split(/;|\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function parseBriefContract(brief) {
  const lines = String(brief ?? '').split(/\r?\n/);
  const buckets = { DELIVERABLE: [], MUST: [], FIXED: [], FORBID: [], JUDGE: [] };
  for (const line of lines) {
    const m = /^(DELIVERABLE|MUST|FIXED|FORBID|JUDGE)\s*:\s*(.*)$/i.exec(line.trim());
    if (!m) continue;
    buckets[m[1].toUpperCase()].push(m[2]);
  }
  const deliverableText = buckets.DELIVERABLE.join(' ').trim();
  const must = buckets.MUST.flatMap(splitItems).map((text, i) => ({ id: `M${i + 1}`, text, source: 'brief' }));
  const fixed = buckets.FIXED.flatMap(splitItems).map((text, i) => ({ id: `F${i + 1}`, text, source: 'brief' }));
  const forbid = buckets.FORBID.flatMap(splitItems).map((text, i) => ({ id: `X${i + 1}`, text, source: 'brief' }));
  const judge = [];
  for (const raw of buckets.JUDGE) {
    for (const part of splitItems(raw)) {
      const jm = /^(.+?)\s+(\d+(?:\.\d+)?)$/.exec(part.trim());
      if (jm) judge.push({ id: `J${judge.length + 1}`, axis: jm[1].trim(), weight: Number(jm[2]), source: 'brief' });
      else if (part) judge.push({ id: `J${judge.length + 1}`, axis: part, weight: 1, source: 'brief' });
    }
  }
  return {
    deliverable: deliverableText ? { kind: deliverableText, count: null, perCandidate: 1, source: 'brief' } : null,
    must, fixed, forbid, judge,
    parsed: KEYS.some((k) => buckets[k].length > 0),
  };
}

export function mergeContract(parsed, derived) {
  const d = derived && typeof derived === 'object' ? derived : {};
  const pick = (key) => {
    const fromBrief = parsed?.[key] || [];
    if (fromBrief.length) return fromBrief;
    return Array.isArray(d[key]) ? d[key].map((item) => ({ ...item, source: item.source || 'derived' })) : [];
  };
  return {
    deliverable: parsed?.deliverable || d.deliverable || null,
    must: pick('must'),
    fixed: pick('fixed'),
    forbid: pick('forbid'),
    judge: pick('judge'),
  };
}

const norm = (s) => String(s ?? '').toLowerCase().replace(/\s+/g, ' ').trim();

export function lints(deliverable, contract) {
  const d = norm(deliverable);
  return {
    fixed: (contract?.fixed || []).map((f) => ({ id: f.id, present: d.includes(norm(f.text)) })),
    forbid: (contract?.forbid || []).map((x) => ({ id: x.id, present: d.includes(norm(x.text)) })),
    note: 'lint — verbatim phrase presence only; evidence for the reviewer, never a verdict',
  };
}

export function assess(judge, contract) {
  if (!judge) return { eligible: false, killed: { term: 'unjudged', passage: null }, rating: null, uncertain: [] };
  const failMust = (judge.eligibility?.must || []).find((m) => m.passed === false);
  const failFixed = (judge.eligibility?.fixed || []).find((f) => f.kept === false);
  const failForbid = (judge.eligibility?.forbid || []).find((x) => x.absent === false);
  const explicitObj = (judge.gate3?.objections || []).find((o) => o.explicitItem && /^[MFX]/i.test(String(o.explicitItem)));
  const killed = judge.gate1?.passed === false ? { term: 'gate1', passage: judge.gate1.reasoning }
    : failMust ? { term: failMust.id, passage: failMust.passage }
    : failFixed ? { term: failFixed.id, passage: failFixed.passage }
    : failForbid ? { term: failForbid.id, passage: failForbid.passage }
    : explicitObj ? { term: explicitObj.explicitItem, passage: explicitObj.text } : null;
  const weights = new Map((contract?.judge || []).map((j) => [j.id, Number(j.weight) || 1]));
  let num = 0; let den = 0;
  for (const r of (judge.ratings || [])) {
    const w = weights.get(r.id) ?? 1;
    num += w * (Number(r.score) || 0);
    den += w * 2;
  }
  const rating = den ? num / den : null;
  const uncertain = [
    ...(judge.uncertain || []),
    ...(judge.gate3?.objections || [])
      .filter((o) => !o.explicitItem || /^J/i.test(String(o.explicitItem)))
      .map((o) => o.text),
  ];
  return { eligible: !killed, killed, rating, uncertain, gate2: judge.gate2?.passed ?? null };
}

export function orderSurvivors(candidates) {
  return [...candidates]
    .filter((c) => c.status === 'survivor')
    .sort((a, b) => (b.assessment?.rating ?? 0) - (a.assessment?.rating ?? 0)
      || (a.assessment?.uncertain?.length ?? 0) - (b.assessment?.uncertain?.length ?? 0));
}

export function reweight(result, weights) {
  const map = new Map();
  for (const [axis, w] of Object.entries(weights || {})) map.set(String(axis).toLowerCase(), Number(w));
  const contract = result.contract || {};
  const next = structuredClone(result);
  for (const c of (next.candidates || [])) {
    if (!c.judge) continue;
    const local = {
      ...contract,
      judge: (contract.judge || []).map((j) => {
        const w = map.get(String(j.axis).toLowerCase()) ?? map.get(String(j.id).toLowerCase());
        return w == null ? j : { ...j, weight: w };
      }),
    };
    c.assessment = assess(c.judge, local);
    if (c.status === 'killed' || c.status === 'unjudged') continue;
    c.status = c.assessment.eligible ? 'survivor' : 'killed';
  }
  next.order = orderSurvivors(next.candidates || []).map((c) => c.k);
  next.ranking = 'by anchored ratings on the contract axes; reweightable';
  return next;
}

export function parseWeightArg(text) {
  const out = {};
  for (const part of String(text ?? '').split(';')) {
    const m = /^\s*(.+?)\s+(\d+(?:\.\d+)?)\s*$/.exec(part);
    if (m) out[m[1].trim()] = Number(m[2]);
  }
  return out;
}
