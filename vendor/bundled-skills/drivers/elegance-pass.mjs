// drivers/elegance-pass.mjs — the Elegance pass + Rabbit-Catcher pass, ONE module for the trio.
//
// John, 2026-09-05: "an elegance pass and a rabbit catcher pass that are run after the crucible
// plan gets built (along with an adversarial review of these). Then have an elegance and rabbit
// catcher review after each wave of foreman." Decision (John, same day): CUT verdicts BLOCK in
// Crucible (before anything is built) and in Foreman only when a SECOND seat confirms them.
//
// The criterion is ELEGANCE.md Part II (Skill Foundry root; the canonical text). The battery
// below is that text's per-element questions, compact, with the same verdicts. Two seats:
//   - the CATCHER runs the battery: the steering seat (role `synthesizer` → the dashboard's
//     coding family);
//   - the ADVERSARY attacks the verdicts: the review seat (role `shark` → the review family).
// Bounded by construction: one call each per hook, never recursive (a HOLD's investigation is
// not itself batteried). Everything the seats say is data; the engines apply verdicts.
//
// Provenance is not the seat's opinion. Every element's claimed need is tagged
//   `user-ratified` | `record` (a journal / incident / prior artifact) | `proposer-written` | `none`
// and a need whose only record is one the proposer wrote for this effort cannot earn KEEP
// (RC-1). The Foundry's own 2026-09-05 failure: a LITE run integrated 7/7 ideas, each "serving"
// a criterion the planner had written that morning (crucible journal 0094).

/** The pass's own typed failure — a seat that returned no judgeable JSON. */
export class ElegancePassError extends Error {
  constructor(message) { super(message); this.name = 'ElegancePassError'; }
}

export const ELEGANCE_PASS_VERSION = 'elegance-pass/1 (ELEGANCE.md Part II, 2026-08-15; engine hooks 2026-09-05)';

export const VERDICTS = Object.freeze(['KEEP', 'HOLD', 'CUT']);
export const PROVENANCE = Object.freeze(['user-ratified', 'record', 'proposer-written', 'none']);

/** The battery, compact. The canonical text is ELEGANCE.md Part II; this must not drift from it. */
export const RC_BATTERY = `
RC-1 Needed-because, with an INDEPENDENT citable need: what forces this element, named as a record
  independent of the element's proposer — it predates this effort, or carries the user's authorship
  or ratification, or is an incident/journal record. A record created in order to justify the
  element (by the proposer, in this effort) does not count; packaging an element beside a
  legitimately-needed sibling transfers nothing. No independent need ⇒ presumptive ⇒ CUT or park.
RC-2 Delete-and-check, objective named: what breaks if this is removed, for WHOM, against WHICH
  on-record objective. The only loss being an unexercised presumptive FEATURE ⇒ rabbit hole.
  Carve-out: malleability work (tests, seams, refactors, design investment) is never "unexercised
  capability" — IF it ships no user-facing behaviour nobody asked for AND names the next concrete
  change it cheapens (a change that passes RC-1 itself).
RC-3 Leverage: what disproportionately large consequence does this buy, and what does it let us
  DROP. A plan/process element that adds machinery while retiring none is presumed extraneous
  (guards are scored by RC-G instead).
RC-4 Whose simplicity: does this move complexity onto the user or maintainer? Cutting intrinsic
  complexity or interface-protecting depth is forbidden; only extraneous load is a target.
RC-5 Earned or premature, by written trigger: scaffolding is EARNED when it carries a written
  retirement trigger; a simplification is premature when it precedes the understanding it claims.
RC-6 Critical path: does the locked North Star FAIL without this, or merely feel less complete?
  When uncertain: PARK it (zero further spend) and carry one line to the user — never pursue silently.
RC-7 Tie-breaker only: elegance never overrides a requirement, a datum, or a failing test.
RC-8 Wave count (Stage 2 only): a wave is a change a reviewer would want to see alone. Adjacent
  waves that are ONE change merge, on the record: a parser without its renderer is invisible, a
  module without its hooks is dead code, a backend that exists only for one link ships with the
  link, a wave whose gate needs the NEXT wave's change to be tested is the same change. Waves that
  touch different failure surfaces, or bury an irreversible / externally visible step beside a safe
  one, stay apart.
RC-G Guards (tests, gates, error handling, journals, run-records): forced by a NAMED hazard that
  obeys the same independence law (predates the proposal, the user named it, or its class has
  occurred on the record); the guard must actually SEE the failure it guards; its false-alarm cost
  is stated. A guard that cannot see what the user sees is theater.
Disposition — exactly one verdict per element: KEEP (independent need, no failing question);
  HOLD (something unresolved and NAMED: a written cure + retirement trigger, or an RC-6 uncertainty
  parked for the user's one-line answer); CUT (no independent need, or a failing question with no
  cure — logged, so the cut is on the record).`;

/**
 * Normalize elements to `{ id, text, kind }`. `kind` is 'element' | 'guard' | 'malleability'
 * (tests/seams/refactors) — the seat may re-classify, but the caller's hint rides along.
 */
export function normalizeElements(items) {
  const out = [];
  const list = Array.isArray(items) ? items : [];
  list.forEach((it, i) => {
    if (it === null || it === undefined) return;
    if (typeof it === 'string') {
      const t = it.trim();
      if (t) out.push({ id: `E${i + 1}`, text: t, kind: 'element' });
      return;
    }
    const text = String(it.text ?? it.title ?? '').trim();
    if (!text) return;
    out.push({
      id: String(it.id ?? `E${i + 1}`),
      text,
      kind: ['element', 'guard', 'malleability'].includes(it.kind) ? it.kind : 'element',
      ...(it.detail ? { detail: String(it.detail).slice(0, 1200) } : {}),
    });
  });
  return out;
}

const CATCHER_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'verdict', 'need', 'provenance', 'rc2', 'needed_because'],
        properties: {
          id: { type: 'string' },
          verdict: { type: 'string', enum: [...VERDICTS] },
          need: { type: 'string' },
          provenance: { type: 'string', enum: [...PROVENANCE] },
          rc2: { type: 'string' },
          trigger: { type: 'string' },
          needed_because: { type: 'string' },
          failing: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    nothing_cut_said_aloud: { type: 'boolean' },
  },
};

const ADVERSARY_SCHEMA = {
  type: 'object',
  required: ['disputes'],
  properties: {
    disputes: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'disputed_verdict', 'reason', 'severity'],
        properties: {
          id: { type: 'string' },
          disputed_verdict: { type: 'string', enum: [...VERDICTS] },
          proposed_verdict: { type: 'string', enum: [...VERDICTS] },
          reason: { type: 'string' },
          severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
          trigger: { type: 'string' },
        },
      },
    },
  },
};

function provenanceBlock(provenance) {
  const p = provenance && typeof provenance === 'object' ? provenance : {};
  const lines = [];
  if (Array.isArray(p.userRatified) && p.userRatified.length) {
    lines.push('USER-RATIFIED records (a need citing one of these is independent):');
    for (const r of p.userRatified) lines.push(`  - ${String(r).slice(0, 300)}`);
  }
  if (Array.isArray(p.records) && p.records.length) {
    lines.push('RECORDS on file (journals, incidents, prior artifacts):');
    for (const r of p.records) lines.push(`  - ${String(r).slice(0, 300)}`);
  }
  if (Array.isArray(p.proposerWritten) && p.proposerWritten.length) {
    lines.push('PROPOSER-WRITTEN this effort (NOT independent — a need citing only these cannot earn KEEP):');
    for (const r of p.proposerWritten) lines.push(`  - ${String(r).slice(0, 300)}`);
  }
  return lines.join('\n');
}

function parseJsonReply(reply) {
  if (reply && typeof reply === 'object') return reply;
  const text = String(reply ?? '');
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start < 0 || end <= start) throw new ElegancePassError('elegance pass: the seat returned no JSON object');
  return JSON.parse(text.slice(start, end + 1));
}

function coerceVerdicts(raw, elements) {
  const byId = new Map(elements.map((e) => [e.id, e]));
  const out = [];
  const seen = new Set();
  for (const v of Array.isArray(raw?.verdicts) ? raw.verdicts : []) {
    const id = String(v?.id ?? '');
    if (!byId.has(id) || seen.has(id)) continue;
    seen.add(id);
    const verdict = VERDICTS.includes(v.verdict) ? v.verdict : 'HOLD';
    const provenance = PROVENANCE.includes(v.provenance) ? v.provenance : 'none';
    out.push({
      id,
      text: byId.get(id).text,
      kind: byId.get(id).kind,
      verdict: (verdict === 'KEEP' && (provenance === 'proposer-written' || provenance === 'none'))
        ? 'HOLD' : verdict,   // RC-1: a KEEP without an independent need is not a KEEP
      need: String(v.need ?? '').slice(0, 600),
      provenance,
      rc2: String(v.rc2 ?? '').slice(0, 600),
      trigger: String(v.trigger ?? '').slice(0, 300),
      needed_because: String(v.needed_because ?? '').slice(0, 300),
      failing: Array.isArray(v.failing) ? v.failing.map(String).slice(0, 8) : [],
      downgraded_from_keep: verdict === 'KEEP' && (provenance === 'proposer-written' || provenance === 'none'),
    });
  }
  // an element the seat did not judge is HOLD (named: "not judged"), never silently KEEP
  for (const e of elements) {
    if (!seen.has(e.id)) {
      out.push({ id: e.id, text: e.text, kind: e.kind, verdict: 'HOLD', need: '', provenance: 'none',
        rc2: '', trigger: 'the catcher did not judge this element — judge it before it is built',
        needed_because: '', failing: ['not judged'], downgraded_from_keep: false });
    }
  }
  return out;
}

/**
 * The CATCHER: the steering seat runs the battery over the enumerated elements.
 * @param {object} o
 * @param {Array} o.elements   strings or {id,text,kind,detail}
 * @param {string} o.northStar
 * @param {string[]} [o.criteria]
 * @param {{userRatified?:string[], records?:string[], proposerWritten?:string[]}} [o.provenance]
 * @param {Function} o.agent   agent(prompt, {role,label,schema}) → object | JSON text
 * @param {string} [o.context] what is being judged (a plan phase list, a wave's diff, …)
 */
export async function runRabbitCatcher({ elements, northStar, criteria = [], provenance = {}, agent, context = '', label = 'rabbit-catcher', log = () => {} } = {}) {
  if (typeof agent !== 'function') throw new ElegancePassError('runRabbitCatcher requires an agent() seam');
  const els = normalizeElements(elements);
  if (!els.length) return { version: ELEGANCE_PASS_VERSION, verdicts: [], keep: [], hold: [], cut: [], nothingCut: true, stamp: 'no elements' };
  const prompt = [
    'You are the STEERING seat running the Elegance pass and the Rabbit-Catcher battery over an enumerated',
    'list of plan/build elements. Judge each element with the battery below; give exactly one verdict each.',
    'Cite the INDEPENDENT record that forces the element (RC-1) and tag its provenance honestly. A need that',
    'exists only because the proposer wrote it for this effort is `proposer-written` and cannot earn KEEP.',
    'Tests, seams and refactors are malleability work: judge them by the carve-out, never as "unused".',
    'A guard is judged by RC-G. When uncertain about the critical path (RC-6), HOLD with a one-line question',
    'for the user — never KEEP by default. Return JSON only, matching the schema.',
    '',
    `NORTH STAR:\n${String(northStar || '').slice(0, 6000)}`,
    criteria.length ? `\nSUCCESS CRITERIA:\n${criteria.map((c, i) => `${i + 1}. ${String(c).slice(0, 500)}`).join('\n')}` : '',
    provenanceBlock(provenance) ? `\nPROVENANCE:\n${provenanceBlock(provenance)}` : '',
    context ? `\nWHAT IS BEING JUDGED: ${String(context).slice(0, 400)}` : '',
    `\nTHE BATTERY:${RC_BATTERY}`,
    '\nELEMENTS:',
    ...els.map((e) => `- [${e.id}] (${e.kind}) ${e.text}${e.detail ? `\n    detail: ${e.detail}` : ''}`),
    '',
    'Output: {"verdicts":[{"id","verdict":"KEEP|HOLD|CUT","need","provenance":"user-ratified|record|proposer-written|none",',
    '"rc2","trigger","needed_because","failing":["RC-n",...]}], "nothing_cut_said_aloud": boolean}',
  ].filter((s) => s !== '').join('\n');
  const reply = await agent(prompt, { role: 'synthesizer', label, schema: CATCHER_SCHEMA });
  const verdicts = coerceVerdicts(parseJsonReply(reply), els);
  const keep = verdicts.filter((v) => v.verdict === 'KEEP').map((v) => v.id);
  const hold = verdicts.filter((v) => v.verdict === 'HOLD').map((v) => v.id);
  const cut = verdicts.filter((v) => v.verdict === 'CUT').map((v) => v.id);
  log(`elegance pass: ${els.length} element(s) → keep ${keep.length} · hold ${hold.length} · cut ${cut.length}` +
    (cut.length === 0 ? ' · nothing cut (said aloud)' : ''));
  return { version: ELEGANCE_PASS_VERSION, verdicts, keep, hold, cut, nothingCut: cut.length === 0, stamp: 'catcher' };
}

/**
 * The ADVERSARY: the review seat attacks the verdicts. A CUT the adversary refutes is RESTORED to
 * HOLD (with the adversary's trigger); a KEEP the adversary attacks with BLOCKER/MAJOR severity is
 * demoted to HOLD; a CUT the adversary confirms (or does not dispute) stays CUT.
 */
export async function runRabbitCatcherAdversary({ catcher, elements, northStar, agent, label = 'rabbit-catcher-adversary', log = () => {} } = {}) {
  // (2026-09-07, crucible journal 0099) a KEEP whose need is USER-RATIFIED is not the proposer's
  // own record — the user's lock is the independent need — so a dispute is recorded but moves nothing.
  const userLocked = (v) => String(v?.provenance || '').toLowerCase().startsWith('user');
  if (typeof agent !== 'function') throw new ElegancePassError('runRabbitCatcherAdversary requires an agent() seam');
  const verdicts = Array.isArray(catcher?.verdicts) ? catcher.verdicts : [];
  if (!verdicts.length) return { disputes: [], verdicts: [], confirmedCuts: [], restored: [], demoted: [] };
  const prompt = [
    'You are an independent ADVERSARIAL reviewer (a different model family from the steering seat) attacking',
    'the verdicts of an Elegance / Rabbit-Catcher pass. Refute what is wrong: a KEEP whose cited need is not',
    'independent of its proposer (RC-1), a CUT that surrenders a datum or removes malleability work that',
    'names its next change (RC-2 carve-out), a HOLD with no trigger, a guard kept without a hazard that',
    'meets the independence law (RC-G). Do not restate agreement; only disputes. Return JSON only.',
    '',
    `NORTH STAR:\n${String(northStar || '').slice(0, 4000)}`,
    `\nTHE BATTERY:${RC_BATTERY}`,
    '\nVERDICTS UNDER ATTACK:',
    ...verdicts.map((v) => `- [${v.id}] ${v.verdict} — ${v.text}\n    need: ${v.need || '(none)'} [${v.provenance}]\n    rc2: ${v.rc2 || '(none)'}${v.trigger ? `\n    trigger: ${v.trigger}` : ''}`),
    '',
    'Output: {"disputes":[{"id","disputed_verdict":"KEEP|HOLD|CUT","proposed_verdict":"KEEP|HOLD|CUT","reason","severity":"BLOCKER|MAJOR|MINOR","trigger"}]}',
  ].join('\n');
  const reply = await agent(prompt, { role: 'shark', label, schema: ADVERSARY_SCHEMA });
  const raw = parseJsonReply(reply);
  const byId = new Map(verdicts.map((v) => [v.id, { ...v }]));
  const disputes = [];
  const restored = [];
  const demoted = [];
  for (const d of Array.isArray(raw?.disputes) ? raw.disputes : []) {
    const id = String(d?.id ?? '');
    const v = byId.get(id);
    if (!v) continue;
    const severity = ['BLOCKER', 'MAJOR', 'MINOR'].includes(d.severity) ? d.severity : 'MINOR';
    const dispute = { id, disputed_verdict: v.verdict, proposed_verdict: VERDICTS.includes(d.proposed_verdict) ? d.proposed_verdict : 'HOLD',
      reason: String(d.reason ?? '').slice(0, 600), severity, trigger: String(d.trigger ?? '').slice(0, 300) };
    disputes.push(dispute);
    if (severity === 'MINOR') continue;   // a minor dispute is recorded, it moves nothing
    if (v.verdict === 'CUT') {
      v.verdict = 'HOLD'; v.trigger = dispute.trigger || dispute.reason; v.restored_by_adversary = true; restored.push(id);
    } else if (v.verdict === 'KEEP' && !userLocked(v)) {
      v.verdict = 'HOLD'; v.trigger = dispute.trigger || dispute.reason; v.demoted_by_adversary = true; demoted.push(id);
    }
  }
  const final = [...byId.values()];
  const confirmedCuts = final.filter((v) => v.verdict === 'CUT').map((v) => v.id);
  log(`elegance adversary: ${disputes.length} dispute(s) → ${restored.length} cut(s) restored to HOLD, ${demoted.length} keep(s) demoted to HOLD, ${confirmedCuts.length} cut(s) confirmed`);
  return { disputes, verdicts: final, confirmedCuts, restored, demoted };
}

/**
 * The whole pass: catcher, then adversary. `cuts` are CONFIRMED cuts (the adversary did not
 * refute them); the engines apply those. Never throws on an empty element list.
 */
export async function runElegancePass({ elements, northStar, criteria, provenance, agent, context, log = () => {}, adversary = true } = {}) {
  const catcher = await runRabbitCatcher({ elements, northStar, criteria, provenance, agent, context, log });
  if (!catcher.verdicts.length) {
    return { ...catcher, cuts: [], holds: [], keeps: [], disputes: [], markdown: renderElegancePass({ verdicts: [], disputes: [], context }) };
  }
  let verdicts = catcher.verdicts;
  let disputes = [];
  if (adversary) {
    const adv = await runRabbitCatcherAdversary({ catcher, elements, northStar, agent, log });
    verdicts = adv.verdicts;
    disputes = adv.disputes;
  }
  const cuts = verdicts.filter((v) => v.verdict === 'CUT').map((v) => v.id);
  const holds = verdicts.filter((v) => v.verdict === 'HOLD').map((v) => v.id);
  const keeps = verdicts.filter((v) => v.verdict === 'KEEP').map((v) => v.id);
  return { version: ELEGANCE_PASS_VERSION, verdicts, disputes, cuts, holds, keeps, nothingCut: cuts.length === 0,
    markdown: renderElegancePass({ verdicts, disputes, context }) };
}

/** The human-readable record — the "show a cut" line the Elegance Law demands is generated here. */
export function renderElegancePass({ verdicts = [], disputes = [], context = '' } = {}) {
  const cuts = verdicts.filter((v) => v.verdict === 'CUT');
  const holds = verdicts.filter((v) => v.verdict === 'HOLD');
  const keeps = verdicts.filter((v) => v.verdict === 'KEEP');
  const lines = [
    `# Elegance pass — Rabbit-Catcher (${ELEGANCE_PASS_VERSION})`,
    '',
    context ? `**Judged:** ${context}` : '',
    `**Verdicts:** keep ${keeps.length} · hold ${holds.length} · cut ${cuts.length} · disputes ${disputes.length}`,
    cuts.length ? `**Cut:** ${cuts.map((v) => `[${v.id}] ${v.text}`).join('; ')}` : '**Nothing cut** (said aloud).',
    '',
    '| id | verdict | element | need (provenance) | delete-and-check | trigger / needed-because |',
    '|---|---|---|---|---|---|',
    ...verdicts.map((v) => `| ${v.id} | ${v.verdict}${v.restored_by_adversary ? ' (restored)' : ''}${v.demoted_by_adversary ? ' (demoted)' : ''}${v.downgraded_from_keep ? ' (no independent need)' : ''} | ${cell(v.text)} | ${cell(v.need)} (${v.provenance}) | ${cell(v.rc2)} | ${cell(v.trigger || v.needed_because)} |`),
  ];
  if (disputes.length) {
    lines.push('', '## Adversary disputes', ...disputes.map((d) => `- [${d.id}] ${d.severity}: ${d.disputed_verdict} → ${d.proposed_verdict} — ${d.reason}`));
  }
  return lines.filter((l) => l !== '' || true).join('\n') + '\n';
}

function cell(s) {
  return String(s ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').slice(0, 220);
}

const RC6_SCHEMA = {
  type: 'object',
  required: ['items'],
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'critical', 'reason'],
        properties: {
          id: { type: 'string' },
          critical: { type: 'boolean' },
          reason: { type: 'string' },
        },
      },
    },
  },
};

/**
 * RC-6 only — the round-boundary question (ELEGANCE.md Part II: "round boundaries ask only
 * RC-6"). Over a list of open items (researchPrime blockers, open findings), the steering seat
 * answers "does the locked North Star FAIL without resolving this, or merely feel less complete?".
 * Items answered "merely" are PARKED: zero further spend, one line for the user
 * ("possible rabbit hole: … — pursue or drop?"). One call; skipped when there is nothing open.
 *
 * @returns {Promise<{ critical: string[], parked: Array<{id, text, reason}>, lines: string[] }>}
 */
export async function runCriticalPathCheck({ items, northStar, agent, label = 'rc6-critical-path', log = () => {} } = {}) {
  const list = normalizeElements(items);
  if (!list.length) return { critical: [], parked: [], lines: [] };
  if (typeof agent !== 'function') throw new ElegancePassError('runCriticalPathCheck requires an agent() seam');
  const prompt = [
    'You are the STEERING seat asking ONE question (RC-6, the critical-path question) about each open item:',
    'does the locked North Star FAIL without resolving this item, or would the result merely feel less complete?',
    'Answer critical=true only when the North Star fails without it. A "merely" item is parked, never pursued',
    'silently. Return JSON only.',
    '',
    'NORTH STAR:',
    String(northStar || '').slice(0, 4000),
    '',
    'OPEN ITEMS:',
    ...list.map((e) => '- [' + e.id + '] ' + e.text),
    '',
    'Output: {"items":[{"id","critical":true|false,"reason"}]}',
  ].join(String.fromCharCode(10));
  const reply = await agent(prompt, { role: 'synthesizer', label, schema: RC6_SCHEMA });
  const raw = parseJsonReply(reply);
  const byId = new Map(list.map((e) => [e.id, e]));
  const critical = [];
  const parked = [];
  const seen = new Set();
  for (const it of Array.isArray(raw?.items) ? raw.items : []) {
    const id = String(it?.id ?? '');
    if (!byId.has(id) || seen.has(id)) continue;
    seen.add(id);
    if (it.critical === true) critical.push(id);
    else parked.push({ id, text: byId.get(id).text, reason: String(it.reason ?? '').slice(0, 300) });
  }
  for (const e of list) if (!seen.has(e.id)) critical.push(e.id);   // unjudged stays on the path (never silently parked)
  const lines = parked.map((p) => 'possible rabbit hole: [' + p.id + '] ' + p.text.slice(0, 120) + ' because ' + (p.reason || 'not on the critical path') + ' — pursue or drop?');
  log('RC-6: ' + list.length + ' open item(s) → ' + critical.length + ' critical, ' + parked.length + ' parked');
  return { critical, parked, lines };
}


// ---------------------------------------------------------------------------------------------
// RC-8 — the wave-count question (John, 2026-09-05: seven emitted waves for three real changes went
// through the element battery unchallenged; the battery judged elements, never the wave count).
// The steering seat proposes merges of ADJACENT waves that are one change; the adversary (the other
// family) disputes; only undisputed merges are applied by the caller. Pure over the reply.
// ---------------------------------------------------------------------------------------------
const RC8_SCHEMA = {
  type: 'object', required: ['merges'],
  properties: { merges: { type: 'array', items: {
    type: 'object', required: ['waves', 'reason'],
    properties: { waves: { type: 'array', items: { type: 'number' } }, reason: { type: 'string' } },
  } } },
};
const RC8_DISPUTE_SCHEMA = {
  type: 'object', required: ['disputes'],
  properties: { disputes: { type: 'array', items: {
    type: 'object', required: ['waves', 'severity', 'reason'],
    properties: { waves: { type: 'array', items: { type: 'number' } }, severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR'] }, reason: { type: 'string' } },
  } } },
};

/** A merge is a run of ≥2 distinct, ascending, ADJACENT 1-based wave numbers inside 1..n; runs never overlap (first wins). */
export function normalizeWaveMerges(raw, n) {
  const out = [];
  const taken = new Set();
  for (const m of Array.isArray(raw) ? raw : []) {
    const ws = Array.isArray(m?.waves) ? m.waves.map((x) => Number(x)).filter((x) => Number.isInteger(x)) : [];
    if (ws.length < 2) continue;
    const sorted = [...ws].sort((a, b) => a - b);
    if (sorted[0] < 1 || sorted[sorted.length - 1] > n) continue;
    let adjacent = true;
    for (let i = 1; i < sorted.length; i++) if (sorted[i] !== sorted[i - 1] + 1) { adjacent = false; break; }
    if (!adjacent || sorted.some((w) => taken.has(w))) continue;
    sorted.forEach((w) => taken.add(w));
    out.push({ waves: sorted, reason: String(m?.reason ?? '').slice(0, 400) });
  }
  return out;
}

function waveLine(w, i) {
  const dels = Array.isArray(w?.deliverables) ? w.deliverables.map((d) => String(d ?? '').slice(0, 140)) : [];
  return '[' + (i + 1) + '] ' + String(w?.title ?? '').slice(0, 160) +
    (w?.dependsOn ? ' (depends on: ' + String(w.dependsOn).slice(0, 80) + ')' : '') +
    String.fromCharCode(10) + '    done-when: ' + String(w?.doneWhen ?? '').slice(0, 260) +
    (dels.length ? String.fromCharCode(10) + dels.map((d) => '    - ' + d).join(String.fromCharCode(10)) : '');
}

/**
 * RC-8 over a wave list. Returns `{ merges, confirmed, disputes, lines }` — `confirmed` are the merges
 * no MAJOR/BLOCKER dispute touched. A list of fewer than two waves asks nothing.
 */
export async function runWaveCountCheck({ waves, northStar, agent, label = 'rc8-wave-count', log = () => {} } = {}) {
  const list = Array.isArray(waves) ? waves : [];
  if (list.length < 2) return { merges: [], confirmed: [], disputes: [], lines: [] };
  if (typeof agent !== 'function') throw new ElegancePassError('runWaveCountCheck requires an agent() seam');
  const NL = String.fromCharCode(10);
  const shown = list.map(waveLine).join(NL);
  const prompt = [
    'You are the STEERING seat asking ONE question (RC-8, the wave-count question) about a wave decomposition:',
    'is each wave a change a reviewer would want to see alone? Adjacent waves that are ONE change merge:',
    'a parser without its renderer is invisible; a module without its hooks is dead code; a backend that',
    'exists only for one link ships with the link; a wave whose gate needs the NEXT wave\'s change to be',
    'TESTED is the same change. Do NOT merge waves that touch different failure surfaces, or that would',
    'bury an irreversible / externally visible step beside a safe one. Name only ADJACENT runs',
    '([n, n+1] or [n, n+1, n+2]); an empty list means every wave stands alone. Return JSON only.',
    '',
    'NORTH STAR:',
    String(northStar || '').slice(0, 4000),
    '',
    'WAVES:',
    shown,
    '',
    'Output: {"merges":[{"waves":[n,m],"reason"}]}',
  ].join(NL);
  const reply = await agent(prompt, { role: 'synthesizer', label, schema: RC8_SCHEMA });
  const merges = normalizeWaveMerges(parseJsonReply(reply)?.merges, list.length);
  let disputes = [];
  if (merges.length) {
    const advPrompt = [
      'You are an independent ADVERSARIAL reviewer (a different model family from the steering seat) attacking',
      'proposed MERGES of waves in a decomposition (RC-8, the wave-count question). Refute a merge that would',
      'combine changes a reviewer must see separately: different failure surfaces; an irreversible or externally',
      'visible step buried beside a safe one; a wave whose gate is meaningful alone and whose separate GREEN is',
      'worth having. Do not restate agreement; only disputes. Return JSON only.',
      '',
      'NORTH STAR:',
      String(northStar || '').slice(0, 4000),
      '',
      'WAVES:',
      shown,
      '',
      'PROPOSED MERGES:',
      ...merges.map((m) => '- waves ' + m.waves.join('+') + ' — ' + m.reason),
      '',
      'Output: {"disputes":[{"waves":[n,m],"severity":"BLOCKER"|"MAJOR"|"MINOR","reason"}]}',
    ].join(NL);
    const advReply = await agent(advPrompt, { role: 'shark', label: label + '-adversary', schema: RC8_DISPUTE_SCHEMA });
    disputes = (parseJsonReply(advReply)?.disputes ?? []).filter((d) => Array.isArray(d?.waves)).map((d) => ({
      waves: d.waves.map((x) => Number(x)).filter(Number.isInteger).sort((a, b) => a - b),
      severity: ['BLOCKER', 'MAJOR', 'MINOR'].includes(d.severity) ? d.severity : 'MINOR',
      reason: String(d.reason ?? '').slice(0, 400),
    }));
  }
  const blocked = (m) => disputes.some((d) => (d.severity === 'BLOCKER' || d.severity === 'MAJOR') && d.waves.some((w) => m.waves.includes(w)));
  const confirmed = merges.filter((m) => !blocked(m));
  const lines = confirmed.map((m) => 'RC-8: merge waves ' + m.waves.join('+') + ' — ' + (m.reason || 'one change'));
  log('RC-8: ' + list.length + ' wave(s) → ' + merges.length + ' merge(s) proposed, ' + disputes.length + ' dispute(s), ' + confirmed.length + ' confirmed');
  return { merges, confirmed, disputes, lines };
}
