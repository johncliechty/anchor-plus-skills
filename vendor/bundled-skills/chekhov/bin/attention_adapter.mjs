// Project persisted Chekhov session events through the installed Ecgberht publisher.
import { createHash } from 'node:crypto';
import { realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const WHO = 'chekhov-session';
const CALL_SITE = 'chekhov-session-integration';
const ID = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$/;
const MAX_INPUT = 1024 * 1024;

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function eventTime(value, field) {
  requireValue(typeof value === 'string' && /[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value), `Invalid ${field}`);
  const parsed = Date.parse(value);
  requireValue(Number.isFinite(parsed), `Invalid ${field}`);
  return parsed;
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function meaningful(value) {
  return typeof value === 'string' && value.trim() !== '' && !['none', 'null', 'n/a'].includes(value.trim().toLowerCase());
}

async function projectAttention(input) {
  requireValue(object(input) && typeof input.project_id === 'string' && ID.test(input.project_id), 'Invalid project identity');
  requireValue(typeof input.folder === 'string' && path.isAbsolute(input.folder), 'Absolute project folder required');
  const folder = await realpath(input.folder);
  requireValue((await stat(folder)).isDirectory(), 'Existing project directory required');
  const record = input.record;
  requireValue(object(record) && record.skill === 'chekhov' && record.ran === true, 'Actual Chekhov run record required');
  requireValue(typeof record.session_id === 'string' && ID.test(record.session_id), 'Invalid session identity');
  requireValue(record.project_id == null || record.project_id === input.project_id, 'Record project identity mismatch');
  const commissionId = record.commission_id ?? null;
  requireValue(commissionId === null || (typeof commissionId === 'string' && commissionId.trim() !== '' && commissionId.length <= 256), 'Invalid commission identity');
  requireValue(record.step_id == null || (typeof record.step_id === 'string' && record.step_id.trim() !== '' && record.step_id.length <= 256), 'Invalid step identity');
  const report = record.report;
  requireValue(object(report), 'Actual report required');
  for (const key of ['project_id', 'session_id', 'commission_id']) {
    const expected = key === 'project_id' ? input.project_id : key === 'session_id' ? record.session_id : commissionId;
    requireValue(report[key] == null || report[key] === expected, `Report ${key} mismatch`);
  }
  requireValue(['asked', 'produced', 'died'].includes(record.outcome), 'Unknown run outcome');
  requireValue(report.outcome == null || report.outcome === record.outcome, 'Report outcome mismatch');
  const start = eventTime(report.start, 'report.start');
  const end = eventTime(report.end, 'report.end');
  requireValue(end >= start && end <= Date.now(), 'Reversed or future report timestamps');
  requireValue(eventTime(record.at, 'record.at') === end, 'Record timestamp differs from report end');
  requireValue(report.human_wait == null || typeof report.human_wait === 'string', 'Invalid report.human_wait');
  const waiting = meaningful(report.human_wait);
  requireValue(record.outcome !== 'asked' || waiting, 'Asked report has no meaningful human wait');
  requireValue(record.outcome !== 'produced' || !waiting, 'Produced report still carries a human wait');
  if (record.outcome === 'died') return { ok: true, published: false, reason: 'No attention transition for died outcome' };

  const cliModule = process.env.CHEKHOV_ECGBERHT_MODULE || '<path>';
  requireValue(path.isAbsolute(cliModule) && (await stat(cliModule)).isFile(), 'Installed Ecgberht module required');
  const attentionModule = path.resolve(path.dirname(cliModule), '../engine/attention.mjs');
  requireValue((await stat(attentionModule)).isFile(), 'Installed attention API missing');
  const { publishAttention, readAttentionCell } = await import(pathToFileURL(attentionModule).href);
  requireValue(typeof publishAttention === 'function' && typeof readAttentionCell === 'function', 'Installed attention exports missing');
  const read = await readAttentionCell(folder);
  requireValue(read?.ok === true, 'Existing attention cell is unreadable');
  const cell = read.cell ?? null;
  requireValue(!read.exists || object(cell), 'Existing attention cell is invalid');
  requireValue(cell?.project_id == null || cell.project_id === input.project_id, 'Attention project identity mismatch');
  const prior = object(cell?.briefing?.chekhov_session) ? cell.briefing.chekhov_session : null;
  const ours = cell?.who === WHO && prior?.adapter === CALL_SITE && prior.project_id === input.project_id;
  const commissionConflict = commissionId !== null && prior?.commission_id != null && commissionId !== prior.commission_id;
  const sameWork = ours && !commissionConflict && (
    (commissionId !== null && commissionId === prior.commission_id) || record.session_id === prior.session_id
  );

  if (record.outcome === 'produced' && (!cell || cell.state === 'quiet')) {
    return { ok: true, published: false, reason: 'No active wait to clear', cell };
  }
  if (record.outcome === 'asked' && cell?.state === 'needs_you' && cell.reason === report.human_wait) {
    requireValue(sameWork, 'Identical wait text belongs to another commission or session');
    return { ok: true, published: false, reason: 'Existing identical wait retained without changing ownership', matched_existing_wait: true, owns_wait: Boolean(sameWork), cell };
  }
  if (record.outcome === 'produced') {
    requireValue(cell?.state === 'needs_you' && sameWork, 'Refusing to clear another commission or session attention');
  } else if (cell && cell.state !== 'quiet') {
    requireValue(cell.state === 'needs_you' && sameWork, 'Refusing to overwrite unrelated active attention');
  }
  if (cell) {
    const previousTime = prior?.adapter === CALL_SITE ? prior.report_end : cell.at;
    requireValue(previousTime != null && end >= eventTime(previousTime, 'prior attention event'), 'Refusing stale attention event');
  }

  const event = {
    adapter: CALL_SITE, project_id: input.project_id, session_id: record.session_id,
    commission_id: commissionId, step_id: record.step_id ?? null,
    outcome: record.outcome, report_start: report.start, report_end: report.end,
  };
  const state = record.outcome === 'asked' ? 'needs_you' : 'quiet';
  const reason = state === 'needs_you' ? report.human_wait : null;
  const derived = {
    readable: true, state, reason,
    waiting_steps: state === 'needs_you' ? 1 : 0,
    provenance: [{ source: 'chekhov-run-record', ...event }],
    bundle_hash: createHash('sha256').update(JSON.stringify({ ...event, state, reason })).digest('hex'),
    briefing: { chekhov_session: event },
  };
  const publicationAt = new Date().toISOString();
  const publication = await publishAttention(folder, {
    derived, who: WHO, at: publicationAt, call_site: CALL_SITE,
    project_id: input.project_id, client_event_id: `chekhov-${derived.bundle_hash}`,
  });
  requireValue(object(publication) && typeof publication.ok === 'boolean', 'Invalid response from installed publisher');
  if (!publication.ok) return { ...publication, event_at: report.end, requested_publication_at: publicationAt };
  const after = await readAttentionCell(folder);
  if (after?.ok !== true || after.cell?.state !== state || (state === 'needs_you' && after.cell.reason !== reason)) {
    return { ok: false, error: 'Installed publisher did not expose the requested attention state', publication, observed: after };
  }
  return { ...publication, cell: after.cell, event_at: report.end, requested_publication_at: publicationAt };
}

let result;
try {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    requireValue(size <= MAX_INPUT, 'Attention input exceeds one MiB');
    chunks.push(chunk);
  }
  result = await projectAttention(JSON.parse(Buffer.concat(chunks).toString('utf8')));
} catch (error) {
  result = { ok: false, error: error.message };
}
let output = JSON.stringify(result);
if (Buffer.byteLength(output, 'utf8') > 65536) {
  result = { ok: false, error: 'Installed attention response exceeds 64 KiB; inspect the actual cell and publisher receipt' };
  output = JSON.stringify(result);
}
process.stdout.write(output + '\n');
process.exitCode = result.ok === true ? 0 : 1;
