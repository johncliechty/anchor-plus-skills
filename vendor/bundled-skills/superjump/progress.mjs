import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export function loadExpectations(file = path.join(HERE, 'calibration.json')) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  return raw.table || {};
}

export function expectationKey(family, effort, call) {
  return `${String(family).toLowerCase()}:${String(effort).toLowerCase()}:${String(call).toLowerCase()}`;
}

export function lookupExpectation(table, family, effort, call) {
  return table?.[expectationKey(family, effort, call)] || null;
}

/**
 * Progress verdict for one in-flight dispatch.
 * Never aborts. stalled-suspect only recommends a kill.
 */
export function verdict(dispatch, nowMs, { windowS = 180 } = {}) {
  const elapsedS = Math.max(0, (nowMs - (dispatch.startedAt ?? nowMs)) / 1000);
  const lastEventAt = dispatch.lastEventAt ?? null;
  const eventAgeS = lastEventAt == null ? Infinity : (nowMs - lastEventAt) / 1000;
  const longest = Number(dispatch.expectation?.max) || 0;
  const tier = dispatch.expectation?.tier || (dispatch.bytes > 0 ? 'A' : 'C');
  const childGone = dispatch.childGone === true;
  const tierA = tier === 'A' && eventAgeS <= windowS;
  if (childGone) {
    return { state: 'stalled-suspect', elapsedS, tier, reason: 'child process is gone' };
  }
  if (tierA || (longest > 0 && elapsedS <= longest) || (longest === 0 && elapsedS <= 600)) {
    return { state: 'progressing', elapsedS, tier, reason: tierA ? 'recent stream event' : 'inside calibrated range' };
  }
  const stallAfter = Math.max(2 * (longest || 300), 600);
  if (elapsedS > stallAfter) {
    return { state: 'stalled-suspect', elapsedS, tier, reason: `no tier-A evidence and elapsed ${Math.round(elapsedS)}s > ${Math.round(stallAfter)}s` };
  }
  return { state: 'quiet', elapsedS, tier, reason: 'no stream; between 1× and 2× longest observed success' };
}

export function readControl(file) {
  if (!file) return null;
  try {
    const text = fs.readFileSync(file, 'utf8').trim();
    if (!text) return null;
    const line = text.split(/\r?\n/).map((s) => s.trim()).find((s) => s.startsWith('kill')) || '';
    if (!line) return null;
    const parts = line.split(/\s+/);
    return { action: 'kill', dispatch: parts[1] || null, raw: line };
  } catch {
    return null;
  }
}

export class ProgressMonitor {
  constructor({ table = {}, now = () => Date.now(), log = () => {}, windowS = 180 } = {}) {
    this.table = table;
    this.now = now;
    this.log = log;
    this.windowS = windowS;
    this.dispatches = new Map();
    this.recommendKill = [];
  }

  start(id, meta) {
    this.dispatches.set(id, {
      id,
      startedAt: this.now(),
      lastEventAt: null,
      bytes: 0,
      expectation: meta.expectation || lookupExpectation(this.table, meta.family, meta.effort, meta.call),
      family: meta.family,
      effort: meta.effort,
      call: meta.call,
      childGone: false,
    });
  }

  onStdoutChunk(id, chunk) {
    const d = this.dispatches.get(id);
    if (!d) return;
    d.lastEventAt = this.now();
    d.bytes += Buffer.byteLength(String(chunk ?? ''));
  }

  markGone(id) {
    const d = this.dispatches.get(id);
    if (d) d.childGone = true;
  }

  tick(landed = [], forfeits = []) {
    const now = this.now();
    const lines = [];
    for (const d of this.dispatches.values()) {
      const v = verdict(d, now, { windowS: this.windowS });
      lines.push(`[+${Math.round(v.elapsedS)}s] ${d.id} ${v.state} — ${v.reason}; expected ${d.expectation?.min ?? '?'}–${d.expectation?.max ?? '?'}s`);
      if (v.state === 'stalled-suspect' && !this.recommendKill.some((r) => r.dispatch === d.id)) {
        const rec = {
          dispatch: d.id,
          elapsedS: Math.round(v.elapsedS),
          evidence: v.reason,
          expectation: d.expectation,
          landed: [...landed],
          forfeits: [...forfeits],
        };
        this.recommendKill.push(rec);
        this.log(`progress.recommend_kill:${JSON.stringify(rec)}`);
      }
    }
    for (const line of lines) this.log(line);
    return lines;
  }

  end(id) {
    this.dispatches.delete(id);
  }
}
