import fs from 'node:fs';
import path from 'node:path';
import {
  createJumperSeatingLedger,
  createJumperDispatchAgent,
  resolveGate3Seating,
  JumperSelfReviewHalt,
  JumperCrossFamilyDegradeHalt,
} from '../jumper/index.js';
import { parseBriefContract, mergeContract, lints, assess, orderSurvivors } from './fit.mjs';
import {
  SPHERES, readPrompt, leapPrompt, judgePrompt, dedupePrompt,
  READ_SCHEMA, LEAP_SCHEMA, JUDGE_SCHEMA, DEDUPE_SCHEMA,
} from './prompts.mjs';
import { ProgressMonitor, loadExpectations, lookupExpectation, readControl } from './progress.mjs';

export {
  parseBriefContract, mergeContract, lints, assess, orderSurvivors,
  JumperSelfReviewHalt, JumperCrossFamilyDegradeHalt,
};

const DEFAULT_TIMEOUT_MS = 60 * 60 * 1000;

function extractJson(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  const text = typeof value === 'string' ? value : (value?.text ?? '');
  if (!text) return null;
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(text);
  const cands = [fenced?.[1], text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1)].filter(Boolean);
  for (const c of cands) { try { return JSON.parse(c); } catch {} }
  return null;
}

export function superjumpPartial(result, extra = {}) {
  return { ...result, status: result.status || 'killed', ...extra };
}

async function callJson({ ledger, kind, dispatchId, runAgent, prompt, schema, driver, role, label, signal, timeoutMs }) {
  const agent = createJumperDispatchAgent({ ledger, kind, dispatchId, runAgent, signal });
  const raw = await agent({
    prompt, schema, driver, label, role, freshContext: true, signal, timeoutMs,
  });
  const obj = extractJson(raw);
  return { obj, raw };
}

export async function runSuperjump(brief, opts = {}) {
  if (opts.deadline != null || opts.deadlineMin != null) {
    throw new TypeError('superjump: a --deadline option does not exist');
  }
  const skipReview = Boolean(opts.skipReview);
  const N = Math.max(1, Math.min(5, Number(opts.candidates) || 3));
  const timeoutMs = Number.isFinite(opts.timeoutMs) ? opts.timeoutMs : DEFAULT_TIMEOUT_MS;
  const now = opts.now || (() => Date.now());
  const t0 = now();
  const elapsed = () => Math.round((now() - t0) / 1000);
  const log = opts.log || ((m) => process.stderr.write(`[+${elapsed()}s] ${m}\n`));
  const seatingLedger = opts.seatingLedger || createJumperSeatingLedger();
  const runAgent = opts.runAgent;
  if (typeof runAgent !== 'function') throw new TypeError('runSuperjump requires runAgent');
  const rootSignal = opts.signal;
  const table = opts.expectations || loadExpectations();
  const monitor = opts.monitor || new ProgressMonitor({ table, now, log });
  const seating = opts.seating || resolveGate3Seating({
    drafterDriver: opts.driver ?? null,
    gate3Driver: opts.gate3Driver ?? null,
    gate3Agent: opts.gate3Agent ?? null,
    env: opts.env || process.env,
    assertIndependent: !opts.gate3Agent,
  });
  const codingDriver = seating.drafterDriverName;
  const reviewDriver = seating.gate3DriverName;
  const codingEffort = opts.codingEffort || 'highest';
  const reviewEffort = opts.reviewEffort || 'highest';
  const parsed = parseBriefContract(brief);
  const result = {
    skill: 'superjump',
    status: 'in-progress',
    startedAt: new Date(t0).toISOString(),
    candidates: [],
    landed: [],
    clocks: {},
    ranking: 'by anchored ratings on the contract axes; reweightable',
    progress: { recommend_kill: [] },
    seating: { codingFamily: seating.drafterFamily, reviewFamily: seating.gate3Family, independent: seating.independent },
    timeoutMs,
  };
  const save = () => {
    if (opts.outputPath) {
      fs.mkdirSync(path.dirname(path.resolve(opts.outputPath)), { recursive: true });
      fs.writeFileSync(opts.outputPath, JSON.stringify(result, null, 2));
    }
    if (typeof opts.onSave === 'function') opts.onSave(result);
  };
  const pollControl = () => {
    const cmd = readControl(opts.controlPath);
    if (cmd?.action === 'kill') {
      const err = new Error('killed_by:operator');
      err.killed_by = 'operator';
      err.dispatch = cmd.dispatch;
      throw err;
    }
  };

  try {
    pollControl();
    log('read: start');
    monitor.start('coding:read', { family: seating.drafterFamily, effort: codingEffort, call: 'read' });
    let readObj;
    try {
      const r = await callJson({
        ledger: seatingLedger, kind: 'coding', dispatchId: 'coding:read', runAgent,
        prompt: readPrompt(brief), schema: READ_SCHEMA, driver: codingDriver,
        role: 'ideate', label: 'SuperjumpRead', signal: rootSignal, timeoutMs,
      });
      readObj = r.obj;
    } finally {
      monitor.end('coding:read');
    }
    if (!readObj) {
      result.status = 'failed';
      result.error = 'read nonconforming after retry';
      save();
      return result;
    }
    result.read = readObj.read;
    result.scamper = readObj.scamper;
    result.contract = mergeContract(parsed, readObj.contract);
    result.landed.push('read');
    result.clocks.readS = elapsed();
    save();
    log(`read: done (${(result.contract.must || []).length} must)`);

    const taken = [];
    result.candidates = Array.from({ length: N }, (_, i) => ({
      k: i + 1, hint: SPHERES[i % SPHERES.length], status: 'leaping',
    }));
    save();

    const judgeOne = async (c) => {
      if (skipReview) {
        // NG-1: skipReview is ignored. The judge seat still runs.
      }
      if (opts.gate3ChannelDead) {
        c.status = 'unjudged';
        c.error = `independent review channel dead after ping retries: ${opts.gate3ChannelDead.reason || 'no response'}`;
        result.landed.push(`judge:c${c.k}:skipped`);
        result.honesty_stamp = 'NOT VETTED — independent review channel unreachable after ping retries';
        result.gate3_ping = { live: false, ...opts.gate3ChannelDead };
        save();
        log(`judge:c${c.k}: unjudged (review channel dead)`);
        return;
      }
      log(`judge:c${c.k}: start`);
      const id = `gate3:judge:c${c.k}`;
      monitor.start(id, { family: seating.gate3Family, effort: reviewEffort, call: 'judge' });
      let j;
      try {
        j = await callJson({
          ledger: seatingLedger, kind: 'verdict', dispatchId: id,
          runAgent: opts.gate3Agent || runAgent,
          prompt: judgePrompt(brief, result.contract, c.leap), schema: JUDGE_SCHEMA,
          driver: reviewDriver, role: 'gate3', label: `SuperjumpJudge${c.k}`,
          signal: rootSignal, timeoutMs,
        });
      } catch (err) {
        monitor.end(id);
        if (err instanceof JumperSelfReviewHalt) throw err;
        const halt = new JumperCrossFamilyDegradeHalt(reviewDriver, err);
        halt.superjumpPartial = superjumpPartial(result, {
          status: 'failed',
          honesty_stamp: 'NOT FULLY VETTED — independent review seat failed; landed candidates preserved',
        });
        throw halt;
      }
      monitor.end(id);
      c.judge = j.obj;
      c.assessment = assess(j.obj, result.contract);
      if (!j.obj) c.status = 'unjudged';
      else c.status = c.assessment.eligible ? 'survivor' : 'killed';
      c.judgedS = elapsed();
      if (!result.clocks.firstReviewedS) result.clocks.firstReviewedS = elapsed();
      result.landed.push(`judge:c${c.k}`);
      save();
      log(`judge:c${c.k}: ${c.status}`);
    };

    await Promise.all(result.candidates.map(async (c) => {
      pollControl();
      const id = `coding:leap:c${c.k}`;
      log(`leap:c${c.k}: start`);
      monitor.start(id, { family: seating.drafterFamily, effort: codingEffort, call: 'leap' });
      let l;
      try {
        l = await callJson({
          ledger: seatingLedger, kind: 'coding', dispatchId: id, runAgent,
          prompt: leapPrompt(brief, result.read, result.contract, c.hint, taken),
          schema: LEAP_SCHEMA, driver: codingDriver, role: 'ideate',
          label: `SuperjumpLeap${c.k}`, signal: rootSignal, timeoutMs,
        });
      } finally {
        monitor.end(id);
      }
      if (!l.obj) {
        c.status = 'unjudged';
        c.error = 'leap nonconforming';
        result.landed.push(`leap:c${c.k}:failed`);
        save();
        return;
      }
      c.leap = l.obj;
      c.lints = lints(l.obj.deliverable, result.contract);
      if (l.obj.domain) taken.push(l.obj.domain);
      c.status = 'judging';
      result.landed.push(`leap:c${c.k}`);
      save();
      await judgeOne(c);
    }));

    result.clocks.portfolioS = elapsed();
    const items = result.candidates.filter((c) => c.leap?.mechanism).map((c) => ({
      k: c.k, title: c.leap.domain, mechanism: c.leap.mechanism,
    }));
    if (items.length >= 2 && !opts.gate3ChannelDead) {
      log('dedupe: start');
      monitor.start('gate3:dedupe', { family: seating.gate3Family, effort: reviewEffort, call: 'dedupe' });
      try {
        const d = await callJson({
          ledger: seatingLedger, kind: 'verdict', dispatchId: 'gate3:dedupe',
          runAgent: opts.gate3Agent || runAgent,
          prompt: dedupePrompt(items), schema: DEDUPE_SCHEMA, driver: reviewDriver,
          role: 'gate3', label: 'SuperjumpDedupe', signal: rootSignal, timeoutMs,
        });
        result.dedupe = d.obj?.groups ?? null;
        result.landed.push('dedupe');
      } finally {
        monitor.end('gate3:dedupe');
      }
    }
    result.order = orderSurvivors(result.candidates).map((c) => c.k);
    result.progress.recommend_kill = monitor.recommendKill;
    result.status = 'complete';
    result.totalS = elapsed();
    result.cross_model = Boolean(seating.independent && seating.drafterFamily !== seating.gate3Family);
    save();
    log(`complete: ${result.order.length} survivor(s) of ${N}`);
    return result;
  } catch (err) {
    if (err?.killed_by === 'operator') {
      result.status = 'killed';
      result.killed_by = 'operator';
      result.forfeited = result.candidates.filter((c) => !['survivor', 'killed', 'unjudged'].includes(c.status)).map((c) => c.k);
      result.progress.recommend_kill = monitor.recommendKill;
      result.totalS = elapsed();
      save();
      return result;
    }
    result.status = result.status === 'complete' ? result.status : 'failed';
    result.error = err?.message || String(err);
    result.progress.recommend_kill = monitor.recommendKill;
    save();
    throw err;
  }
}

export function refuseImplement(text) {
  const t = String(text || '').toLowerCase();
  if (/\bimplement the winner\b/.test(t) || /\bbuild the winner\b/.test(t)) {
    return { refused: true, pointer: 'Use Crucible to plan and Foreman to build. Superjump only produces ideas.' };
  }
  return { refused: false };
}
