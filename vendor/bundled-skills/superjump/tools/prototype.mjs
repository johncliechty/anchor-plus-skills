#!/usr/bin/env node
// tools/prototype.mjs — Superjump Wave 0: the three hop prompts, prompts only, no engine.
//
// Spawns the two subscription CLIs directly (the trio's argv builders, not its dispatcher) so
// that the reasoning effort can be set per seat and EVERYTHING each CLI streams while it works
// is timestamped — the observation the W1 progress monitor will rest on. No time limits of any
// kind except a 60-minute safety kill per call, recorded as such. Results are written after
// every landed stage.
//
//   node tools/prototype.mjs --brief <file> --coding-effort ultra|max|... --review-effort highest|<name>
//        --candidates 3 --out <dir> [--label name] [--dry]
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildCodexExecArgs, subscriptionOnlyEnv } from '../../../../trio/drivers/chatgpt-cli.mjs';
import { resolveModelPolicy } from '../../../../trio/drivers/model-policy.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SAFETY_MS = 60 * 60 * 1000;
const SPHERES = [
  'the natural sciences (biology, physics, chemistry, geology, ecology)',
  'the arts and humanities (music, architecture, painting, literature, history)',
  'social and rule systems (economics, law, games, logistics, ritual)',
  'engineered physical systems (mechanics, materials, civil, aero, naval)',
  'information and communication systems outside software (linguistics, cryptography, signalling)',
];

function parseArgs(argv) {
  const o = { brief: null, codingEffort: 'ultra', reviewEffort: 'highest', candidates: 3, out: null, label: null, dry: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--brief') o.brief = argv[++i];
    else if (a === '--coding-effort') o.codingEffort = argv[++i];
    else if (a === '--review-effort') o.reviewEffort = argv[++i];
    else if (a === '--candidates') o.candidates = Number(argv[++i]);
    else if (a === '--out') o.out = argv[++i];
    else if (a === '--label') o.label = argv[++i];
    else if (a === '--dry') o.dry = true;
    else throw new Error(`unknown argument ${a}`);
  }
  if (!o.brief || !o.out) throw new Error('--brief and --out are required');
  return o;
}

// ── seats ──────────────────────────────────────────────────────────────────────────────────
const EFFORT_ORDER = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra']; // ascending (trio's order)
function grokEfforts() {
  try {
    const cache = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.grok', 'models_cache.json'), 'utf8'));
    const sel = resolveModelPolicy('grok', { env: process.env });
    const info = cache.models?.[sel.model]?.info ?? cache.models?.[sel.model] ?? {};
    const raw = info.reasoning_efforts ?? info.supportedReasoningEfforts ?? [sel.effort];
    const efforts = raw.map((e) => (typeof e === 'string' ? e : (e.id ?? e.value))).filter(Boolean)
      .sort((a, b) => EFFORT_ORDER.indexOf(a) - EFFORT_ORDER.indexOf(b));
    return { model: sel.model, highest: sel.effort, efforts };
  } catch (e) {
    return { model: 'grok-4.6', highest: 'high', efforts: ['high'], error: e.message };
  }
}
function codingSeat(effort) {
  const sel = resolveModelPolicy('chatgpt', { env: process.env });
  return { family: 'chatgpt', cmd: 'codex', model: sel.model, effort };
}
function reviewSeat(effortArg) {
  const g = grokEfforts();
  let effort = effortArg;
  if (effortArg === 'highest') effort = g.highest;
  else if (effortArg === 'next') { const i = g.efforts.indexOf(g.highest); effort = (i > 0 ? g.efforts[i - 1] : null) ?? g.highest; } // efforts ascending: the one below highest
  return { family: 'grok', cmd: process.platform === 'win32' ? 'grok.exe' : 'grok', model: g.model, effort, efforts: g.efforts };
}

/** Spawn one CLI call, timestamping every stdout/stderr line. Returns {text, rec}. */
function runCli(seat, prompt, { id, outDir, log }) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const streamPath = path.join(outDir, `${id}.stream.log`);
    const stream = fs.createWriteStream(streamPath, { flags: 'a' });
    const stamp = () => `+${((Date.now() - t0) / 1000).toFixed(1)}s`;
    let args; let stdinText = null; let tmp = null;
    const env = { ...subscriptionOnlyEnv(process.env), NO_COLOR: '1', CI: '1' };
    if (seat.family === 'chatgpt') {
      args = buildCodexExecArgs({ model: seat.model, reasoningEffort: seat.effort, sandbox: 'read-only', target: '<path>' });
      stdinText = prompt;
    } else {
      args = ['--output-format', 'json', '--model', seat.model, '--reasoning-effort', seat.effort, '--permission-mode', 'plan', '--max-turns', '8'];
      if (Buffer.byteLength(prompt, 'utf8') > 24000) { tmp = path.join(os.tmpdir(), `superjump-w0-${process.pid}-${id}.txt`); fs.writeFileSync(tmp, prompt, 'utf8'); args.push('--prompt-file', tmp); }
      else args.push('-p', prompt);
    }
    const child = spawn(seat.cmd, args, { env, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    const events = [];
    let out = ''; let err = '';
    const onLine = (which, line) => {
      if (!line.trim()) return;
      const s = (Date.now() - t0) / 1000;
      events.push({ s, which, len: line.length });
      stream.write(`[${stamp()}] ${which} ${line.slice(0, 160).replace(/\s+/g, ' ')}\n`);
    };
    let obuf = ''; let ebuf = '';
    child.stdout.on('data', (d) => { const t = d.toString(); out += t; obuf += t; const parts = obuf.split('\n'); obuf = parts.pop(); for (const p of parts) onLine('out', p); });
    child.stderr.on('data', (d) => { const t = d.toString(); err += t; ebuf += t; const parts = ebuf.split('\n'); ebuf = parts.pop(); for (const p of parts) onLine('err', p); });
    const killer = setTimeout(() => { stream.write(`[${stamp()}] SAFETY 60-min kill\n`); try { child.kill(); } catch {} }, SAFETY_MS);
    child.on('error', (e) => { err += `\nspawn error: ${e.message}`; });
    child.on('close', (code) => {
      clearTimeout(killer);
      if (obuf) onLine('out', obuf); if (ebuf) onLine('err', ebuf);
      if (tmp) { try { fs.unlinkSync(tmp); } catch {} }
      const seconds = (Date.now() - t0) / 1000;
      stream.write(`[${stamp()}] close code=${code}\n`); stream.end();
      let text = ''; let served = null; let interim = 0;
      if (seat.family === 'chatgpt') {
        for (const line of out.split('\n')) { try { const e = JSON.parse(line); if (e.type === 'item.completed' && e.item?.type === 'agent_message') { text = e.item.text || text; interim++; } } catch {} }
        interim = Math.max(0, interim - 1);
      } else {
        try { const j = JSON.parse(out.trim()); text = j.text || ''; served = j.modelUsage ? Object.keys(j.modelUsage)[0] : null; } catch { text = out.trim(); }
      }
      const outEvents = events.filter((e) => e.which === 'out');
      const rec = {
        id, family: seat.family, model: seat.model, effort: seat.effort, served, code, seconds: Math.round(seconds),
        promptChars: prompt.length, replyChars: text.length, stdoutLines: outEvents.length, stderrLines: events.length - outEvents.length,
        interimMessages: interim, firstEventS: events[0]?.s ?? null, lastEventBeforeEndS: events.length > 1 ? events[events.length - 2].s : null,
        streamLog: path.basename(streamPath), startedAt: new Date(t0).toISOString(),
      };
      log(`${id} done in ${rec.seconds}s (${rec.stdoutLines} stdout lines, ${rec.stderrLines} stderr lines, reply ${rec.replyChars} chars)`);
      resolve({ text, rec, stderr: err.slice(-2000) });
    });
    if (stdinText != null) { child.stdin.end(stdinText); } else child.stdin.end();
  });
}

function extractJson(text) {
  if (!text) return null;
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(text);
  const cands = [fenced?.[1], text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1)].filter(Boolean);
  for (const c of cands) { try { return JSON.parse(c); } catch {} }
  return null;
}
async function callJson(seat, prompt, ctx) {
  const first = await runCli(seat, prompt, ctx);
  let obj = extractJson(first.text); let retries = 0; let recs = [first.rec];
  if (!obj) {
    retries = 1;
    const second = await runCli(seat, `${prompt}\n\nYour previous reply was not a single valid JSON object. Return ONLY the JSON object, nothing else.`, { ...ctx, id: `${ctx.id}.retry` });
    obj = extractJson(second.text); recs.push(second.rec);
    if (!obj) return { obj: null, recs, retries, raw: second.text };
  }
  return { obj, recs, retries, raw: first.text };
}

// ── prompts ─────────────────────────────────────────────────────────────────────────────────
const readPrompt = (brief) => `You are Superjump's READ seat: a bounded diagnostic read of a brief, in Gandalf's discipline (what is really being asked, hidden assumptions, the real contradictions, what would make an answer wrong) — no honesty tiers, no refutation, no ideas yet.

THE BRIEF (verbatim):
${brief}

Return ONE JSON object and nothing else, under about 4000 characters:
{
 "read": {"ask": "what is really being asked, one paragraph", "assumptions": ["hidden assumption ..."], "contradictions": ["a real contradiction the brief contains, or leave the list empty"], "wrongIf": ["what would make an answer wrong for THIS brief"]},
 "scamper": [{"move": "substitute|combine|adapt|modify|putToOtherUse|eliminate|reverse", "transformation": "a concrete productive transformation of the brief's own elements"}],
 "contract": {
   "deliverable": {"kind": "what one candidate must deliver", "count": <how many candidates the brief wants overall>, "perCandidate": 1},
   "must": [{"id": "M1", "text": "...", "source": "the brief line this comes from, quoted"}],
   "fixed": [{"id": "F1", "text": "a fact, number or name that must not change, verbatim", "source": "quoted brief line"}],
   "forbid": [{"id": "X1", "text": "...", "source": "quoted brief line"}],
   "judge": [{"id": "J1", "axis": "...", "weight": <number>, "anchors": {"0": "what a 0 looks like", "1": "...", "2": "..."}, "source": "brief|derived"}]
 }
}
Rules: list only productive SCAMPER moves (any number, including none); do not invent contradictions; if the brief contains lines beginning DELIVERABLE:, MUST:, FIXED:, FORBID: or JUDGE:, copy them into the contract exactly with source "brief"; otherwise derive and mark source "derived"; every contract item quotes its source line.`;

const leapPrompt = (brief, read, contract, hint, taken) => `You are Superjump's LEAP seat: analogical transfer plus TRIZ resolution plus instantiation, in ONE ordered pass, so the transfer is inspectable.

THE BRIEF (verbatim):
${brief}

THE READ (from the read seat):
${JSON.stringify(read)}

THE FIT CONTRACT (what the deliverable is judged against; FIXED items are verbatim facts that must not change; FORBID items must be absent):
${JSON.stringify(contract)}

FOREIGN-DOMAIN HINT: choose a domain of a different kind from [${taken.join('; ') || 'none yet'}]; suggested kind: ${hint}. The domain is a stimulus for finding the idea; the deliverable is judged on its own.

Produce ONE JSON object and nothing else, under about 6000 characters, with these fields IN THIS ORDER:
{
 "domain": "the foreign domain you chose",
 "sourceMechanism": "how that domain solves its analogous problem — causal, 3 to 6 sentences",
 "correspondences": [{"original": "element of the brief", "foreign": "its counterpart", "why": "structural reason"}],
 "breakingPoint": "where the analogy stops holding for this brief",
 "adaptation": {"borrowed": "the concrete design consequence you take from the source", "consequence": "what it forces in the deliverable"},
 "triz": ["named TRIZ principles actually used"],
 "deliverable": "the instantiated thing the contract's deliverable asks for — ONE complete instance, ready to hand over; keep every FIXED fact verbatim; nothing FORBIDden",
 "mechanism": "one sentence: the principal idea that makes this candidate different",
 "residual": "what of the brief this candidate does not solve — text, honest",
 "smallestTest": "the smallest fair test, proportionate to the brief, marked as unperformed"
}
No numeric self-scores. The deliverable must be the thing itself, not a framework for making it.`;

const judgePrompt = (brief, contract, candidate) => `READ-ONLY SEAT: use no tools or commands; answer only with the JSON asked for.
You are Superjump's independent JUDGE — a different model family from the seat that generated this candidate. You judge one candidate against the brief and its contract. Do not rank, merge or rewrite it.

THE BRIEF (verbatim):
${brief}

THE FIT CONTRACT (extracted by another seat — check it first):
${JSON.stringify(contract)}

THE CANDIDATE (its full transfer trace and deliverable):
${JSON.stringify(candidate)}

Return ONE JSON object and nothing else, under about 4000 characters:
{
 "contractCheck": {"matches": true|false, "corrections": ["where the contract misreads or misses the brief"]},
 "gate1": {"passed": true|false, "reasoning": "is the deliverable possible — no invented mechanism, data or rule it depends on?"},
 "gate2": {"passed": true|false, "reasoning": "trace inspection: does the adaptation actually borrow the named consequence from the source domain, or is the analogy decoration?"},
 "gate3": {"objections": [{"text": "a structural gap, hand-waving or invented fact the deliverable depends on", "explicitItem": "M1|F1|X1|... or null when not tied to an explicit contract item"}]},
 "eligibility": {"must": [{"id": "M1", "passed": true|false, "passage": "quote from the deliverable"}], "fixed": [{"id": "F1", "kept": true|false, "passage": "..."}], "forbid": [{"id": "X1", "absent": true|false, "passage": "..."}]},
 "ratings": [{"id": "J1", "score": 0|1|2, "passage": "the passage that earns this score against the anchors"}],
 "uncertain": ["anything you could not settle from the material"]
}`;

const dedupePrompt = (items) => `READ-ONLY SEAT: use no tools; answer only with JSON.
Group these candidate ideas by principal mechanism: two candidates are the SAME idea if they rely on the same principal mechanism, whatever domain they came from.
${items.map((c) => `${c.k}. ${c.title}: ${c.mechanism}`).join('\n')}
Return ONE JSON object: {"groups": [{"members": [k, ...], "reason": "..."}]} — every candidate appears in exactly one group.`;

// ── assessment (mirrors the planned W2 assess; deterministic) ──────────────────────────────
const norm = (s) => String(s ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
function lints(deliverable, contract) {
  const d = norm(deliverable);
  return {
    fixed: (contract.fixed || []).map((f) => ({ id: f.id, present: d.includes(norm(f.text)) })),
    forbid: (contract.forbid || []).map((x) => ({ id: x.id, present: d.includes(norm(x.text)) })),
    note: 'lint — verbatim phrase presence only; evidence for the reviewer, never a verdict',
  };
}
function assess(judge, contract) {
  if (!judge) return { eligible: false, killed: { term: 'unjudged', passage: null }, rating: null };
  const failMust = (judge.eligibility?.must || []).find((m) => m.passed === false);
  const failFixed = (judge.eligibility?.fixed || []).find((f) => f.kept === false);
  const failForbid = (judge.eligibility?.forbid || []).find((x) => x.absent === false);
  // Only EXPLICIT HARD items (M*, F*, X*) can kill through a gate-3 objection; an objection tied
  // to a judging axis (J*) lowers nothing by itself — it is an uncertain flag (W0 finding: three
  // candidates were wrongly killed "on J1" before this line existed).
  const explicitObj = (judge.gate3?.objections || []).find((o) => o.explicitItem && /^[MFX]/i.test(String(o.explicitItem)));
  const killed = judge.gate1?.passed === false ? { term: 'gate1', passage: judge.gate1.reasoning }
    : failMust ? { term: failMust.id, passage: failMust.passage }
    : failFixed ? { term: failFixed.id, passage: failFixed.passage }
    : failForbid ? { term: failForbid.id, passage: failForbid.passage }
    : explicitObj ? { term: explicitObj.explicitItem, passage: explicitObj.text } : null;
  const weights = new Map((contract.judge || []).map((j) => [j.id, Number(j.weight) || 1]));
  let num = 0; let den = 0;
  for (const r of (judge.ratings || [])) { const w = weights.get(r.id) ?? 1; num += w * (Number(r.score) || 0); den += w * 2; }
  const rating = den ? num / den : null;
  const uncertain = [...(judge.uncertain || []), ...(judge.gate3?.objections || []).filter((o) => !o.explicitItem || /^J/i.test(String(o.explicitItem))).map((o) => o.text)];
  return { eligible: !killed, killed, rating, uncertain, gate2: judge.gate2?.passed ?? null };
}

// ── the run ─────────────────────────────────────────────────────────────────────────────────
async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const brief = fs.readFileSync(opts.brief, 'utf8');
  fs.mkdirSync(opts.out, { recursive: true });
  const coding = codingSeat(opts.codingEffort);
  const review = reviewSeat(opts.reviewEffort);
  const t0 = Date.now();
  const el = () => Math.round((Date.now() - t0) / 1000);
  const logPath = path.join(opts.out, 'run.log');
  const log = (m) => { const line = `[+${el()}s] ${m}`; process.stderr.write(line + '\n'); fs.appendFileSync(logPath, line + '\n'); };
  const result = { label: opts.label, brief: opts.brief, seats: { coding, review }, startedAt: new Date(t0).toISOString(), status: 'in-progress', landed: [], calls: [], clocks: {}, read: null, contract: null, candidates: [] };
  const save = () => fs.writeFileSync(path.join(opts.out, 'result.json'), JSON.stringify(result, null, 2));
  save();
  if (opts.dry) { log(`DRY: coding=${JSON.stringify(coding)} review=${JSON.stringify(review)}`); log(`READ prompt ${readPrompt(brief).length} chars`); return; }
  log(`seats: coding ${coding.model}@${coding.effort} · review ${review.model}@${review.effort} (grok efforts: ${JSON.stringify(review.efforts)})`);

  // Hop 1 — Read
  log('read: start');
  const r = await callJson(coding, readPrompt(brief), { id: 'read', outDir: opts.out, log });
  result.calls.push(...r.recs);
  if (!r.obj) { result.status = 'failed'; result.error = 'read nonconforming after retry'; save(); log('read: FAILED'); return; }
  result.read = r.obj.read; result.contract = r.obj.contract; result.scamper = r.obj.scamper; result.landed.push('read'); result.clocks.readS = el(); save();
  log(`read: done (${(result.contract?.must || []).length} must, ${(result.contract?.fixed || []).length} fixed, ${(result.contract?.forbid || []).length} forbid, ${(result.contract?.judge || []).length} judge axes)`);

  // Hop 2 — Leap ×N in parallel; Hop 3 — Judge each as it lands
  const N = Math.max(1, Math.min(5, opts.candidates));
  const taken = [];
  result.candidates = Array.from({ length: N }, (_, i) => ({ k: i + 1, hint: SPHERES[i % SPHERES.length], status: 'leaping' }));
  save();
  const judgeOne = async (c) => {
    log(`judge:c${c.k}: start`);
    const j = await callJson(review, judgePrompt(brief, result.contract, c.leap), { id: `judge-c${c.k}`, outDir: opts.out, log });
    result.calls.push(...j.recs);
    c.judge = j.obj; c.judgeRaw = j.obj ? undefined : j.raw?.slice(0, 2000); c.judgeRetries = j.retries;
    c.assessment = assess(j.obj, result.contract);
    c.status = j.obj ? (c.assessment.eligible ? 'survivor' : 'killed') : 'unjudged';
    c.judgedS = el();
    if (!result.clocks.firstReviewedS) result.clocks.firstReviewedS = el();
    result.landed.push(`judge:c${c.k}`); save();
    log(`judge:c${c.k}: ${c.status}${c.assessment.killed ? ` (${c.assessment.killed.term})` : ''} rating=${c.assessment.rating?.toFixed(2) ?? 'n/a'}`);
  };
  await Promise.all(result.candidates.map(async (c) => {
    log(`leap:c${c.k}: start (${c.hint})`);
    const l = await callJson(coding, leapPrompt(brief, result.read, result.contract, c.hint, taken), { id: `leap-c${c.k}`, outDir: opts.out, log });
    result.calls.push(...l.recs);
    if (!l.obj) { c.status = 'unjudged'; c.error = 'leap nonconforming after retry'; c.leapRaw = l.raw?.slice(0, 2000); result.landed.push(`leap:c${c.k}:failed`); save(); log(`leap:c${c.k}: FAILED`); return; }
    c.leap = l.obj; c.leapRetries = l.retries; c.lints = lints(l.obj.deliverable, result.contract); c.leapS = el(); if (c.leap.domain) taken.push(c.leap.domain);
    c.status = 'judging'; result.landed.push(`leap:c${c.k}`); save();
    log(`leap:c${c.k}: built (${c.leap.domain}) — ${String(c.leap.deliverable || '').length} chars`);
    await judgeOne(c);
  }));
  result.clocks.portfolioS = el();

  // Dedupe (one small call) when ≥2 candidates have a mechanism
  const items = result.candidates.filter((c) => c.leap?.mechanism).map((c) => ({ k: c.k, title: c.leap.domain, mechanism: c.leap.mechanism }));
  if (items.length >= 2) {
    log('dedupe: start');
    const d = await callJson(review, dedupePrompt(items), { id: 'dedupe', outDir: opts.out, log });
    result.calls.push(...d.recs); result.dedupe = d.obj?.groups ?? null; result.landed.push('dedupe'); save();
    log(`dedupe: ${result.dedupe ? `${result.dedupe.length} group(s)` : 'nonconforming'}`);
  }
  // Ordering (mirrors W2): eligible survivors by rating desc, then fewer uncertain
  result.order = result.candidates.filter((c) => c.status === 'survivor').sort((a, b) => (b.assessment.rating ?? 0) - (a.assessment.rating ?? 0) || (a.assessment.uncertain?.length ?? 0) - (b.assessment.uncertain?.length ?? 0)).map((c) => c.k);
  result.ranking = 'by anchored ratings on the contract axes; reweightable';
  result.status = 'complete'; result.totalS = el(); save();
  log(`complete: ${result.order.length} survivor(s) of ${N}; first reviewed at +${result.clocks.firstReviewedS}s; portfolio at +${result.clocks.portfolioS}s; total ${result.totalS}s`);
}
main().catch((e) => { process.stderr.write(`prototype: fatal — ${e.stack || e.message}\n`); process.exitCode = 1; });
