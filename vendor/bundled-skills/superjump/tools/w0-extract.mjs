// tools/w0-extract.mjs — Wave 0 data: per-run and per-call timings, streaming observations,
// expectation table, kill terms, contract summaries; plus the blind items for John's packet.
// Usage: node tools/w0-extract.mjs   (writes planning/crucible-2026-09-14/proto/CALIBRATION-DATA.md and proto/blind/*)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROTO = path.resolve(HERE, '..', 'planning', 'crucible-2026-09-14', 'proto');
const CMP = path.resolve(HERE, '..', '..', 'jumper', 'planning', 'review-2026-09-13', 'comparison');
const runs = fs.readFileSync(path.join(PROTO, 'runs.jsonl'), 'utf8').split('\n').filter((l) => l.startsWith('{')).map((l) => JSON.parse(l));
const R = runs.map((r) => ({ ...r, result: JSON.parse(fs.readFileSync(path.join(PROTO, r.label, 'result.json'), 'utf8')) }));
// Corrected assessment (W0 finding): a gate-3 objection tied to a JUDGING axis (J*) is a flag, not a
// kill; only explicit hard items (M*/F*/X*), gate 1, or reviewer-marked eligibility failures kill.
// The runs recorded the uncorrected rule; statuses below are recomputed from the judge JSON.
for (const r of R) for (const c of r.result.candidates) {
  const j = c.judge; if (!j) continue;
  const failMust = (j.eligibility?.must || []).find((m) => m.passed === false);
  const failFixed = (j.eligibility?.fixed || []).find((f) => f.kept === false);
  const failForbid = (j.eligibility?.forbid || []).find((x) => x.absent === false);
  const hardObj = (j.gate3?.objections || []).find((o) => o.explicitItem && /^[MFX]/i.test(String(o.explicitItem)));
  const killed = j.gate1?.passed === false ? { term: 'gate1', passage: j.gate1.reasoning }
    : failMust ? { term: failMust.id, passage: failMust.passage } : failFixed ? { term: failFixed.id, passage: failFixed.passage }
    : failForbid ? { term: failForbid.id, passage: failForbid.passage } : hardObj ? { term: hardObj.explicitItem, passage: hardObj.text } : null;
  c.assessment = { ...(c.assessment || {}), killed, eligible: !killed, corrected: true,
    uncertain: [...(j.uncertain || []), ...(j.gate3?.objections || []).filter((o) => !o.explicitItem || /^J/i.test(String(o.explicitItem))).map((o) => o.text)] };
  c.status = killed ? 'killed' : 'survivor';
}
const briefOf = (label) => (label.startsWith('teaching') ? 'teaching' : 'artifact');
const kind = (id) => id.replace(/-c\d+/, '').replace(/\.retry$/, '');
const med = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };

let md = '# Wave 0 — calibration data (auto-extracted 2026-09-14)\n\n';
md += '## Runs\n\n| run | brief | coding effort | review effort | total | first reviewed | portfolio | survivors | killed | unjudged | dedupe groups | retries |\n|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n';
for (const r of R) {
  const res = r.result; const c = res.candidates;
  const retries = res.calls.filter((x) => x.id.endsWith('.retry')).length;
  md += `| ${r.label} | ${briefOf(r.label)} | ${res.seats.coding.effort} | ${res.seats.review.effort} | ${res.totalS}s | ${res.clocks.firstReviewedS ?? '—'}s | ${res.clocks.portfolioS ?? '—'}s | ${c.filter((x) => x.status === 'survivor').length} | ${c.filter((x) => x.status === 'killed').length} | ${c.filter((x) => x.status === 'unjudged').length} | ${res.dedupe ? res.dedupe.length : '—'} | ${retries} |\n`;
}
md += '\nControls (yesterday, jumper lean mode, ChatGPT ultra + Grok xhigh): teaching 8 min (2 survivors of 3), Book 1 15 min (3 of 3).\n\n';

md += '## Calls\n\n| run | call | family | effort | seconds | prompt chars | reply chars | stdout lines | first event | last event before end | interim msgs |\n|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n';
const calls = [];
for (const r of R) for (const c of r.result.calls) { calls.push({ run: r.label, ...c, kind: kind(c.id) }); md += `| ${r.label} | ${c.id} | ${c.family} | ${c.effort} | ${c.seconds} | ${c.promptChars} | ${c.replyChars} | ${c.stdoutLines} | ${c.firstEventS ?? '—'} | ${c.lastEventBeforeEndS ?? '—'} | ${c.interimMessages} |\n`; }

md += '\n## Expectation table (seconds; min / median / max over Wave 0 calls)\n\n| family | effort | call kind | n | min | median | max |\n|---|---|---|---:|---:|---:|---:|\n';
const groups = new Map();
for (const c of calls) { const k = `${c.family}|${c.effort}|${c.kind}`; (groups.get(k) || groups.set(k, []).get(k)).push(c.seconds); }
for (const [k, v] of [...groups.entries()].sort()) { const [f, e, kd] = k.split('|'); md += `| ${f} | ${e} | ${kd} | ${v.length} | ${Math.min(...v)} | ${med(v)} | ${Math.max(...v)} |\n`; }

md += '\n## Streaming observation (what each CLI emitted while working)\n\n';
for (const fam of ['chatgpt', 'grok']) {
  const cs = calls.filter((c) => c.family === fam);
  const early = cs.filter((c) => c.lastEventBeforeEndS != null && c.lastEventBeforeEndS < c.seconds - 5);
  const withEarly = cs.filter((c) => c.firstEventS != null && c.firstEventS < 5);
  md += `- **${fam}**: ${cs.length} calls; ${withEarly.length} emitted something in the first 5 s (start events); ${early.length} emitted any line more than 5 s before the end (i.e. mid-generation progress); interim messages total ${cs.reduce((n, c) => n + (c.interimMessages || 0), 0)}. `;
  md += fam === 'chatgpt' ? 'Codex `exec --json` prints thread/turn start events immediately and then nothing until the final message: in a single-message generation there is NO mid-call progress signal. Tier C (expectation) for these seats.\n' : 'Grok `--output-format json` prints its whole JSON at the end: NO mid-call signal. Tier C (expectation).\n';
}

md += '\n## Contracts and kills\n\n';
for (const r of R) {
  const res = r.result; const k = res.contract || {};
  md += `### ${r.label}\n\n- deliverable: ${JSON.stringify(k.deliverable)}\n- must: ${(k.must || []).map((m) => `${m.id} "${m.text}" [${m.source === 'brief' ? 'brief' : m.source ? 'quoted' : 'derived'}]`).join('; ')}\n- fixed: ${(k.fixed || []).map((m) => `${m.id} "${m.text}"`).join('; ')}\n- forbid: ${(k.forbid || []).map((m) => `${m.id} "${m.text}"`).join('; ')}\n- judge: ${(k.judge || []).map((j) => `${j.id} ${j.axis} w${j.weight}`).join('; ')}\n`;
  for (const c of res.candidates) {
    const a = c.assessment || {};
    md += `- c${c.k} (${c.leap?.domain ?? '—'}): **${c.status}**${a.killed ? ` on ${a.killed.term} — "${String(a.killed.passage || '').slice(0, 220).replace(/\s+/g, ' ')}"` : ''}; rating ${a.rating != null ? a.rating.toFixed(2) : '—'}; gate2 ${a.gate2 ?? '—'}; uncertain ${a.uncertain?.length ?? 0}; contractCheck ${c.judge?.contractCheck?.matches ?? '—'}${c.judge?.contractCheck?.corrections?.length ? ` (${c.judge.contractCheck.corrections.length} corrections)` : ''}\n`;
  }
  if (res.dedupe) md += `- dedupe: ${res.dedupe.map((g) => `[${g.members.join(',')}] ${String(g.reason || '').slice(0, 120)}`).join(' · ')}\n`;
  md += '\n';
}
fs.writeFileSync(path.join(PROTO, 'CALIBRATION-DATA.md'), md);

// ── blind items ─────────────────────────────────────────────────────────────────────────────
const items = [];
for (const r of R) for (const c of r.result.candidates) if (c.leap) items.push({
  brief: briefOf(r.label), source: `${r.label}/c${c.k}`, mode: 'superjump', coding: r.result.seats.coding.effort, review: r.result.seats.review.effort,
  domain: c.leap.domain, mechanism: c.leap.mechanism, deliverable: c.leap.deliverable, weakness: c.leap.residual, test: c.leap.smallestTest,
  status: c.status, killTerm: c.assessment?.killed?.term ?? null, rating: c.assessment?.rating ?? null,
});
for (const [brief, file] of [['teaching', 'teaching/lean.json'], ['artifact', 'artifact/lean.json']]) {
  const j = JSON.parse(fs.readFileSync(path.join(CMP, file), 'utf8'));
  for (const s of j.survivors) items.push({ brief, source: `lean/${s.title}`, mode: 'lean', coding: 'ultra', review: 'xhigh', domain: null, mechanism: s.concept.mechanism, deliverable: s.concept.deliverable, weakness: s.concept.principalWeakness, test: s.concept.smallestTest, status: 'survivor', killTerm: null, rating: null });
  for (const k of j.killLog) items.push({ brief, source: `lean/${k.title}`, mode: 'lean', coding: 'ultra', review: 'xhigh', domain: null, mechanism: k.concept?.mechanism, deliverable: k.concept?.deliverable, weakness: k.concept?.principalWeakness, test: k.concept?.smallestTest, status: 'killed', killTerm: 'lean-review', rating: null });
}
// deterministic shuffle per brief, then letters
function shuffled(arr, seed) { const a = [...arr]; let s = seed; for (let i = a.length - 1; i > 0; i--) { s = (s * 1103515245 + 12345) & 0x7fffffff; const j = s % (i + 1); [a[i], a[j]] = [a[j], a[i]]; } return a; }
const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const blind = [];
for (const [brief, seed] of [['teaching', 7], ['artifact', 11]]) {
  const list = shuffled(items.filter((i) => i.brief === brief), seed);
  list.forEach((it, i) => blind.push({ letter: `${brief === 'teaching' ? 'T' : 'B'}${letters[i]}`, ...it }));
}
fs.mkdirSync(path.join(PROTO, 'blind'), { recursive: true });
fs.writeFileSync(path.join(PROTO, 'blind', 'items.json'), JSON.stringify(blind, null, 2));
let map = '# Wave 0 blind packet — MAPPING (do not open before marking)\n\n| letter | brief | mode | coding effort | review effort | source | domain | status | kill term | rating |\n|---|---|---|---|---|---|---|---|---|---|\n';
for (const b of blind) map += `| ${b.letter} | ${b.brief} | ${b.mode} | ${b.coding} | ${b.review} | ${b.source} | ${b.domain ?? '—'} | ${b.status} | ${b.killTerm ?? '—'} | ${b.rating != null ? b.rating.toFixed(2) : '—'} |\n`;
fs.writeFileSync(path.join(PROTO, 'blind', 'MAPPING.md'), map);
console.log(`runs ${R.length}, calls ${calls.length}, blind items ${blind.length}`);
