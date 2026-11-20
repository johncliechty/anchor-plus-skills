// crucible/bin/elegance-hooks.mjs — the Elegance / Rabbit-Catcher pass at Crucible's two hooks.
//
// John, 2026-09-05: run the pass after the plan is built (Stage 1) and after the wave
// decomposition (Stage 2), BEFORE the Shark round, so the Sharks review the CUT plan together
// with the verdict table — that is the adversarial review of the pass. CUT verdicts BLOCK here
// (John's decision: the cheapest point, before anything is built). Pure apply functions +
// one runner; the engine is drivers/elegance-pass.mjs.

import fs from 'node:fs';
import path from 'node:path';
import { runElegancePass, renderElegancePass, runWaveCountCheck } from '../../drivers/elegance-pass.mjs';

/** Elements of a Stage-1 plan: every near-term specific, id `P<phase>.<n>`. */
export function elementsFromPlan(plan) {
  const out = [];
  const phases = Array.isArray(plan?.phases) ? plan.phases : [];
  phases.forEach((p, i) => {
    const specs = Array.isArray(p?.nearTermSpecifics) ? p.nearTermSpecifics : [];
    specs.forEach((s, j) => {
      const text = String(s ?? '').trim();
      if (text) out.push({ id: `P${i + 1}.${j + 1}`, text, kind: kindOf(text), detail: `phase ${i + 1}: ${String(p?.name ?? '').slice(0, 120)}` });
    });
  });
  return out;
}

/** Apply verdicts to a Stage-1 plan: CUT removes the specific; HOLD annotates it with its trigger. Pure. */
export function applyVerdictsToPlan(plan, verdicts) {
  const byId = new Map((Array.isArray(verdicts) ? verdicts : []).map((v) => [v.id, v]));
  const phases = (Array.isArray(plan?.phases) ? plan.phases : []).map((p, i) => {
    const specs = Array.isArray(p?.nearTermSpecifics) ? p.nearTermSpecifics : [];
    const kept = [];
    const cut = [];
    specs.forEach((s, j) => {
      const v = byId.get(`P${i + 1}.${j + 1}`);
      if (v?.verdict === 'CUT') { cut.push(String(s)); return; }
      if (v?.verdict === 'HOLD') { kept.push(`${String(s)} (HOLD — ${v.trigger || v.needed_because || 'trigger to be named'})`); return; }
      kept.push(s);
    });
    const deferred = [...(Array.isArray(p?.deferred) ? p.deferred : []), ...cut.map((s) => `${s} (CUT by the elegance pass)`)];
    return { ...p, nearTermSpecifics: kept, deferred };
  });
  return { ...plan, phases };
}

/** Elements of a Stage-2 decomposition: every wave deliverable, id `W<n>.<k>`; a wave with none contributes its title. */
export function elementsFromWaves(waves) {
  const out = [];
  (Array.isArray(waves) ? waves : []).forEach((w, i) => {
    const dels = Array.isArray(w?.deliverables) ? w.deliverables.map((d) => String(d ?? '').trim()).filter(Boolean) : [];
    if (!dels.length) {
      out.push({ id: `W${i + 1}.1`, text: String(w?.title ?? `Wave ${i + 1}`), kind: 'element', detail: `done-when: ${String(w?.doneWhen ?? '').slice(0, 300)}` });
      return;
    }
    dels.forEach((d, k) => out.push({ id: `W${i + 1}.${k + 1}`, text: d, kind: kindOf(d), detail: `wave ${i + 1} "${String(w?.title ?? '').slice(0, 80)}" — done-when: ${String(w?.doneWhen ?? '').slice(0, 300)}` }));
  });
  return out;
}

const WAVE_NUM_PREFIX = /^\s*W\d+\s*[—–-]\s*/;
const stripWaveNum = (t) => String(t ?? '').replace(WAVE_NUM_PREFIX, '').trim();
const joinNonEmpty = (parts, sep) => parts.map((p) => String(p ?? '').trim()).filter(Boolean).join(sep);

/**
 * Remap a single `dependsOn` token/value across wave drops or merges without clobbering DAG edges.
 * Supports number (`1`), `W1` / `Wave 1`, full/bare wave title, comma/semicolon lists, or arrays.
 */
function remapDependsOnValue(dep, resolveRef, selfNewN) {
  if (dep == null || dep === '' || dep === '—') return dep === '' ? '' : null;
  if (Array.isArray(dep)) {
    const mapped = [];
    for (const item of dep) {
      const r = remapDependsOnValue(item, resolveRef, selfNewN);
      const items = Array.isArray(r) ? r : (r != null ? [r] : []);
      for (const x of items) {
        const key = typeof x === 'number' ? `#${x}` : String(x);
        if (!mapped.some((m) => (typeof m === 'number' ? `#${m}` : String(m)) === key)) {
          mapped.push(x);
        }
      }
    }
    return mapped.length ? mapped : null;
  }
  if (typeof dep === 'number') {
    const resolved = resolveRef(dep, 'number');
    if (!resolved || resolved.newN === selfNewN) return null;
    return resolved.newN;
  }
  const raw = String(dep).trim();
  if (!raw || raw === '—') return null;

  // Support comma- or semicolon-delimited multi-dependency strings ("W1, W2" or "A; B").
  if (/[,;]/.test(raw) && !resolveRef(raw, 'string')) {
    const sep = raw.includes(';') ? '; ' : ', ';
    const parts = raw.split(/\s*[,;]\s*/).filter(Boolean);
    const mappedParts = [];
    for (const p of parts) {
      const r = remapDependsOnValue(p, resolveRef, selfNewN);
      if (r != null && r !== '' && !mappedParts.includes(String(r))) mappedParts.push(String(r));
    }
    return mappedParts.length ? mappedParts.join(sep) : null;
  }

  const resolved = resolveRef(raw, 'string');
  if (!resolved) return raw; // external or unknown dependency reference preserved verbatim
  if (resolved.droppedReplacement !== undefined) {
    return remapDependsOnValue(resolved.droppedReplacement, resolveRef, selfNewN);
  }
  if (resolved.newN === selfNewN) return null;
  if (/^\d+$/.test(raw)) return String(resolved.newN);
  if (/^W\d+$/i.test(raw)) return `W${resolved.newN}`;
  if (/^Wave\s+\d+$/i.test(raw)) return `Wave ${resolved.newN}`;
  return resolved.newTitle;
}

function buildWaveRefResolver(oldRecords) {
  const byOldN = new Map();
  const byTitle = new Map();
  for (const rec of oldRecords) {
    byOldN.set(rec.oldN, rec);
    if (rec.oldTitle) byTitle.set(rec.oldTitle.toLowerCase(), rec);
    if (rec.oldBareTitle) byTitle.set(rec.oldBareTitle.toLowerCase(), rec);
  }
  return (token, kind) => {
    if (kind === 'number') return byOldN.get(Number(token)) || null;
    const s = String(token ?? '').trim();
    if (!s) return null;
    if (/^\d+$/.test(s)) return byOldN.get(Number(s)) || null;
    const wShort = s.match(/^W(?:ave\s*)?(\d+)$/i);
    if (wShort) return byOldN.get(Number(wShort[1])) || null;
    const exact = byTitle.get(s.toLowerCase()) || byTitle.get(stripWaveNum(s).toLowerCase());
    if (exact) return exact;
    const wPrefixed = s.match(/^W(?:ave\s*)?(\d+)\s*[—–:-]/i);
    if (wPrefixed) return byOldN.get(Number(wPrefixed[1])) || null;
    return null;
  };
}

/** Apply verdicts to waves: CUT removes the deliverable; a wave whose deliverables are ALL cut is dropped; HOLD annotates; surviving waves renumber 1..K and remap DAG dependsOn. Pure. */
export function applyVerdictsToWaves(waves, verdicts) {
  const src = Array.isArray(waves) ? waves : [];
  const byId = new Map((Array.isArray(verdicts) ? verdicts : []).map((v) => [v.id, v]));
  const numbered = src.some((w) => WAVE_NUM_PREFIX.test(String(w?.title ?? '')));
  const hasExplicitN = src.some((w) => typeof w?.n === 'number');
  const records = [];
  const out = [];

  src.forEach((w, i) => {
    const oldN = Number.isInteger(w?.n) ? w.n : i + 1;
    const oldTitle = String(w?.title ?? '');
    const oldBareTitle = stripWaveNum(oldTitle);
    const dels = Array.isArray(w?.deliverables) ? w.deliverables : [];

    if (!dels.length) {
      const v = byId.get(`W${i + 1}.1`);
      if (v?.verdict === 'CUT') {
        records.push({ oldN, oldTitle, oldBareTitle, droppedReplacement: w?.dependsOn ?? null });
        return;
      }
      const nextWave = v?.verdict === 'HOLD'
        ? { ...w, title: `${w.title} (HOLD — ${v.trigger || 'trigger to be named'})` }
        : { ...w };
      const idx = out.push(nextWave) - 1;
      records.push({ oldN, oldTitle, oldBareTitle, outIndex: idx });
      return;
    }

    const kept = [];
    dels.forEach((d, k) => {
      const v = byId.get(`W${i + 1}.${k + 1}`);
      if (v?.verdict === 'CUT') return;
      kept.push(v?.verdict === 'HOLD' ? `${d} (HOLD — ${v.trigger || v.needed_because || 'trigger to be named'})` : d);
    });
    if (!kept.length) {
      records.push({ oldN, oldTitle, oldBareTitle, droppedReplacement: w?.dependsOn ?? null });
      return; // every deliverable cut ⇒ the wave is gone
    }
    const idx = out.push({ ...w, deliverables: kept }) - 1;
    records.push({ oldN, oldTitle, oldBareTitle, outIndex: idx });
  });

  const anyDropped = out.length !== src.length;
  for (let i = 0; i < out.length; i++) {
    const newN = i + 1;
    if (hasExplicitN || anyDropped) out[i].n = newN;
    if (numbered && anyDropped) {
      out[i].title = `W${newN} — ${stripWaveNum(out[i].title)}`;
    }
  }
  for (const rec of records) {
    if (rec.outIndex != null) {
      rec.newN = rec.outIndex + 1;
      rec.newTitle = out[rec.outIndex].title;
    }
  }
  if (anyDropped) {
    const resolveRef = buildWaveRefResolver(records);
    for (let i = 0; i < out.length; i++) {
      if ('dependsOn' in out[i] && out[i].dependsOn != null) {
        out[i].dependsOn = remapDependsOnValue(out[i].dependsOn, resolveRef, i + 1);
      }
    }
  }
  return out;
}

function kindOf(text) {
  const t = String(text).toLowerCase();
  if (/\btest(s|ing)?\b|fixture|hermetic|seam|refactor/.test(t)) return 'malleability';
  if (/\bgate\b|guard|fail[- ]closed|invariant|assert/.test(t)) return 'guard';
  return 'element';
}

/**
 * Run the pass over a plan or a wave list and persist the record. Returns the applied plan/waves
 * plus the markdown the Shark draft carries. Never throws on an empty element list.
 *
 * @param {object} o
 * @param {object} [o.plan]       Stage-1 plan (phases[]) — exactly one of plan / waves
 * @param {object[]} [o.waves]    Stage-2 waves
 * @param {string} o.northStar
 * @param {string[]} [o.criteria]
 * @param {object} [o.provenance] {userRatified[], records[], proposerWritten[]}; default: the criteria are proposer-written
 * @param {Function} o.agent      role-routed agent (synthesizer → catcher, shark → adversary)
 * @param {string} [o.artifactsDir]
 * @param {Function} [o.log]
 */
export async function runPlanElegancePass({ plan = null, waves = null, northStar, criteria = [], provenance = null, agent, artifactsDir = null, log = () => {}, adversary = true, fileTag = '' } = {}) {
  const isWaves = Array.isArray(waves);
  const elements = isWaves ? elementsFromWaves(waves) : elementsFromPlan(plan);
  const prov = provenance || { userRatified: [], records: [], proposerWritten: criteria.map((c) => `criterion: ${String(c).slice(0, 200)}`) };
  const context = isWaves ? `the Stage-2 wave decomposition (${waves.length} wave(s))` : `the Stage-1 master plan (${plan?.phases?.length ?? 0} phase(s))`;
  const result = await runElegancePass({ elements, northStar, criteria, provenance: prov, agent, context, log, adversary });
  const applied = isWaves ? applyVerdictsToWaves(waves, result.verdicts) : applyVerdictsToPlan(plan, result.verdicts);
  if (artifactsDir) {
    try {
      fs.mkdirSync(artifactsDir, { recursive: true });
      fs.writeFileSync(path.join(artifactsDir, `ELEGANCE-PASS${fileTag}.md`), result.markdown, 'utf8');
      fs.writeFileSync(path.join(artifactsDir, `elegance-pass${fileTag}.json`), JSON.stringify({
        version: result.version, context, cuts: result.cuts, holds: result.holds, keeps: result.keeps,
        verdicts: result.verdicts, disputes: result.disputes, at: new Date().toISOString(),
      }, null, 2) + '\n', 'utf8');
    } catch (e) { log(`!! elegance pass record not written (non-fatal): ${e?.message || e}`); }
  }
  log(`elegance pass (${context}): cut ${result.cuts.length} · hold ${result.holds.length} · keep ${result.keeps.length}` +
    (result.cuts.length ? ` — cut: ${result.cuts.join(', ')}` : ' — nothing cut (said aloud)'));
  return { ...result, plan: isWaves ? null : applied, waves: isWaves ? applied : null, elements };
}

/** The section appended to the Shark draft so the reviewers attack the verdicts too. */
export function elegancePassSection(result) {
  if (!result) return '';
  return `\n\n## Elegance pass (Rabbit-Catcher) — verdicts the reviewers may dispute\n\n` +
    renderElegancePass({ verdicts: result.verdicts, disputes: result.disputes, context: '' }) +
    `\nA reviewer who disagrees with a verdict states it as a finding: a KEEP without an independent need, a CUT that surrenders a datum, a HOLD without a trigger.\n`;
}


// ---------------------------------------------------------------------------------------------
// RC-8 — the wave-count question, Stage 2 (John, 2026-09-05). Pure merge + the hook that asks it.
// ---------------------------------------------------------------------------------------------

/**
 * Apply confirmed merges (`[{ waves: [n, n+1, ...] }]`, 1-based, adjacent) to a wave list. A merged
 * wave carries every member's deliverables and scenarios, its done-when joined, the first member's
 * dependency; wave numbers `w.n` renumber contiguously `1..K`, titles keep their `W<n> —` numbering,
 * and `dependsOn` wave IDs/titles are remapped accurately across DAGs (never clobbered to `i - 1`).
 * Pure. Returns `{ waves, merged: [{ from, title }] }`.
 */
export function applyWaveMerges(waves, merges) {
  const src = Array.isArray(waves) ? waves : [];
  const groups = new Map();
  for (const m of Array.isArray(merges) ? merges : []) {
    const ws = Array.isArray(m?.waves) ? m.waves : [];
    if (ws.length >= 2) groups.set(ws[0], ws);
  }
  const numbered = src.some((w) => WAVE_NUM_PREFIX.test(String(w?.title ?? '')));
  const hasExplicitN = src.some((w) => typeof w?.n === 'number');
  const out = [];
  const merged = [];
  const records = [];

  for (let i = 0; i < src.length; i++) {
    const n = i + 1;
    const g = groups.get(n);
    if (!g) {
      const oldW = src[i];
      const oldN = Number.isInteger(oldW?.n) ? oldW.n : n;
      const idx = out.push({ ...oldW }) - 1;
      records.push({
        oldN,
        oldTitle: String(oldW?.title ?? ''),
        oldBareTitle: stripWaveNum(oldW?.title),
        outIndex: idx,
      });
      continue;
    }
    const members = g.map((k) => src[k - 1]).filter(Boolean);
    const first = members[0] ?? src[i];
    const w = {
      ...first,
      title: joinNonEmpty(members.map((x) => stripWaveNum(x?.title)), ' + '),
      intent: joinNonEmpty(members.map((x) => x?.intent), ' '),
      deliverables: members.flatMap((x) => (Array.isArray(x?.deliverables) ? x.deliverables : [])),
      dependsOn: first?.dependsOn ?? null,
      doneWhen: joinNonEmpty(members.map((x) => x?.doneWhen), '; '),
      nonTrivial: members.some((x) => x?.nonTrivial === true),
      gwt: members.flatMap((x) => (Array.isArray(x?.gwt) ? x.gwt : [])),
    };
    if (!w.intent) delete w.intent;
    const idx = out.push(w) - 1;
    for (const k of g) {
      const member = src[k - 1];
      if (!member) continue;
      records.push({
        oldN: Number.isInteger(member?.n) ? member.n : k,
        oldTitle: String(member?.title ?? ''),
        oldBareTitle: stripWaveNum(member?.title),
        outIndex: idx,
      });
    }
    merged.push({ from: [...g], title: w.title });
    i += g.length - 1;
  }

  const anyMerged = merged.length > 0;
  for (let i = 0; i < out.length; i++) {
    const newN = i + 1;
    const bare = stripWaveNum(out[i].title);
    out[i].title = numbered ? 'W' + newN + ' — ' + bare : bare;
    if (hasExplicitN || anyMerged) out[i].n = newN;
  }
  for (const rec of records) {
    rec.newN = rec.outIndex + 1;
    rec.newTitle = out[rec.outIndex].title;
  }

  const resolveRef = buildWaveRefResolver(records);
  for (let i = 0; i < out.length; i++) {
    if (i === 0 && out[i].dependsOn != null) {
      const remapped0 = remapDependsOnValue(out[i].dependsOn, resolveRef, 1);
      out[i].dependsOn = remapped0 ?? null;
      continue;
    }
    if ('dependsOn' in out[i] && out[i].dependsOn != null) {
      out[i].dependsOn = remapDependsOnValue(out[i].dependsOn, resolveRef, i + 1);
    }
  }
  return { waves: out, merged };
}

/** The Stage-2 hook: ask RC-8, apply what the adversary did not dispute, write the record. */
export async function runWaveCountPass({ waves, northStar, agent, artifactsDir = null, log = () => {}, fileTag = '-stage2' } = {}) {
  const before = Array.isArray(waves) ? waves.length : 0;
  const check = await runWaveCountCheck({ waves, northStar, agent, log });
  const applied = applyWaveMerges(waves, check.confirmed);
  const after = applied.waves.length;
  const NL = String.fromCharCode(10);
  const md = [
    '# Wave count (RC-8) — the wave-count question',
    '',
    '**Judged:** ' + before + ' wave(s) → **' + after + '**' + (applied.merged.length ? '' : ' (every wave stands alone — said aloud)'),
    '',
    ...(check.merges.length ? ['| proposed merge | reason | disputed | applied |', '|---|---|---|---|',
      ...check.merges.map((m) => {
        const ds = check.disputes.filter((d) => d.waves.some((w) => m.waves.includes(w)));
        const ok = check.confirmed.includes(m);
        return '| waves ' + m.waves.join('+') + ' | ' + m.reason.replace(/\|/g, '/') + ' | ' +
          (ds.length ? ds.map((d) => d.severity + ': ' + d.reason.replace(/\|/g, '/')).join('; ') : 'no') + ' | ' + (ok ? 'yes' : 'no') + ' |';
      })] : ['No merge proposed.']),
    '',
    ...(applied.merged.length ? ['## Applied', ...applied.merged.map((m) => '- waves ' + m.from.join('+') + ' → "' + m.title + '"')] : []),
    '',
    '## Waves after RC-8', ...applied.waves.map((w, i) => '- [' + (i + 1) + '] ' + String(w?.title ?? '')),
    '',
  ].join(NL);
  if (artifactsDir) {
    try {
      fs.mkdirSync(artifactsDir, { recursive: true });
      fs.writeFileSync(path.join(artifactsDir, 'ELEGANCE-RC8' + fileTag + '.md'), md, 'utf8');
      fs.writeFileSync(path.join(artifactsDir, 'elegance-rc8' + fileTag + '.json'), JSON.stringify({
        before, after, merges: check.merges, confirmed: check.confirmed, disputes: check.disputes, merged: applied.merged, at: new Date().toISOString(),
      }, null, 2) + NL, 'utf8');
    } catch (e) { log('!! RC-8 record not written (non-fatal): ' + (e?.message || e)); }
  }
  log('RC-8 (wave count): ' + before + ' wave(s) → ' + after + (applied.merged.length
    ? ' — merged: ' + applied.merged.map((m) => m.from.join('+')).join(', ')
    : ' — every wave stands alone (said aloud)'));
  return { waves: applied.waves, merged: applied.merged, merges: check.merges, confirmed: check.confirmed, disputes: check.disputes, markdown: md, before, after };
}

/** The section appended to the Shark draft so the reviewers attack the wave count too. */
export function waveCountSection(result) {
  if (!result) return '';
  const NL = String.fromCharCode(10);
  return NL + NL + '## Wave count (RC-8) — a merge the reviewers may dispute' + NL + NL + String(result.markdown ?? '') + NL +
    'A reviewer who disagrees states it as a finding: a merge that buries an irreversible step, or a split that leaves a wave untestable alone.' + NL;
}
