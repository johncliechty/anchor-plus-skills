/** Draft-only session summary. Signing is exclusively a hand edit by John. */
import fs from 'node:fs';
import path from 'node:path';
import { atomicWriteFile, stateDirFor } from './store.mjs';
import { verdictData } from './index.mjs';

export function draftSessionJournal(root, session, opts = {}) {
  const dir = path.join(stateDirFor(root), 'journal');
  const names = fs.existsSync(dir) ? fs.readdirSync(dir) : [];
  const next = Math.max(0, ...names.map((s) => /^(\d{4})-/.exec(s)).filter(Boolean).map((m) => Number(m[1]))) + 1;
  const first = session.journal_cursor || 0;
  const receipts = session.receipts.slice(first);
  const ids = [...new Set(receipts.filter((r) => r.verdict_id).map((r) => r.verdict_id))];
  const verdicts = verdictData(root).verdicts.filter((v) => ids.includes(v.id));
  const file = path.join(dir, `${String(next).padStart(4, '0')}-session.md`);
  const lines = ['# Session draft', '', `Ended: ${opts.now || new Date().toISOString()}`,
    `Verdicts: ${verdicts.map((v) => `${v.id} ${(v.final || v.t0)?.verdict || 'unresolved'}`).join('; ') || 'none'}`,
    `Accept events: ${receipts.filter((r) => r.transition === 'accept').map((r) => `${r.id} ${r.action}`).join('; ') || 'none'}`,
    `Lint events: ${receipts.filter((r) => r.transition === 'lint' || r.steps?.includes('lint')).map((r) => r.at).join('; ') || 'none'}`,
    `Hands-on seconds: ${Number.isFinite(opts.handsOnSeconds) && opts.handsOnSeconds >= 0 ? opts.handsOnSeconds : 'not recorded'}`,
    'thirty_second_test: pending', '',
    'Unsigned draft. John adds the signature field and its date by hand after review.', ''];
  atomicWriteFile(file, lines.join('\n'));
  session.journal_cursor = session.receipts.length;
  return { path: path.relative(root, file).replace(/\\/g, '/'), verdict_ids: ids, unsigned: true };
}
