/** W10 projection and human surface; source stores remain authoritative. */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { atomicWriteFile, journalEvent, loadSession, stateDirFor } from './store.mjs';
import { sha256Text } from './manifest.mjs';
import { verdictData, loadLedgerEntries } from './index.mjs';
import { hasAcceptance } from './tuples.mjs';
import { renderLine1, renderWaiting, setSurfaceLimit, SURFACE_CONTRACT, STATUS_FIELDS, surfaceText } from './surface.mjs';

function jsonIfPresent(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (e) { if (e.code === 'ENOENT') return fallback; throw new Error(`backing-store-unreadable: ${path.basename(file)}: ${e.message}`); }
}
export function readSurfaceInputs(root, opts = {}) {
  const dir = stateDirFor(root), config = jsonIfPresent(path.join(dir, 'config.json'), {});
  // ledger.json is a derived cache. Its presence marks an initialized store,
  // but stale bytes/shape cannot outrank the authoritative source sidecars.
  const hasIndex = fs.existsSync(path.join(dir, 'ledger.json'));
  const data = verdictData(root);
  // Before a pack or typed store exists, legacy bootstrap roots only inventory
  // managed files. Keep their manifest/HALT checks usable without interpreting
  // those files as an onboarded ledger. Existing typed stores remain strict.
  const entries = config?.pack || hasIndex || data.records.length ? loadLedgerEntries(root) : [];
  return { config, entries, records: data.verdicts, events: data.records,
    session: opts.session || loadSession(stateDirFor(root, opts.stateDir)), lint: opts.lint?.t0 || opts.lint || {},
    manifest: opts.manifest || {}, project: opts.project || config.project || path.basename(root),
    lintEvent: opts.lint?.t0 ? opts.now || new Date().toISOString() : null };
}
const tupleUnit = (t) => t.unit || t.receipt?.unit || t.source?.unit || t.value?.unit || null;
const unitName = (u) => typeof u === 'string' ? u : u?.name || u?.id || null;
const dateOf = (t) => t.accepted_on || t.receipt?.date || '';
const latest = (rows, getDate) => [...rows].sort((a, b) => String(getDate(a)).localeCompare(String(getDate(b)))).at(-1);
export function projectStatus({ project, config = {}, entries = [], records = [], events = [], session = {}, lint = {}, manifest = {}, lintEvent }) {
  const tuples = entries.map((e) => e.tuple);
  const accepted = tuples.filter((t) => hasAcceptance(t));
  const lastAccepted = latest(accepted.filter((t) => tupleUnit(t)), dateOf);
  const unit = unitName(config.active_unit) || unitName(records.filter((r) => r.unit).at(-1)?.unit)
    || unitName(tupleUnit(lastAccepted || {})) || SURFACE_CONTRACT.fields[1].empty;
  const inUnit = (t) => !tupleUnit(t) || unitName(tupleUnit(t)) === unit;
  const structural = latest(tuples.filter((t) => t.kind === 'structural' && inUnit(t)), dateOf);
  const cascade = latest(tuples.filter((t) => t.id === 'series.cascade_position' && t.lock === 'locked' && hasAcceptance(t)), dateOf);
  const cascadeValue = cascade?.value?.object ?? cascade?.value?.cascade_position ?? cascade?.value;
  const position = structural?.value?.['book.chapter'] || (typeof structural?.value?.position === 'string' && /^\d+\.\d+$/.test(structural.value.position) ? structural.value.position : null);
  const asks = tuples.filter((t) => t.kind === 'decision' && !hasAcceptance(t) && t.question);
  const waiting = {};
  for (const ask of asks) {
    const key = unitName(tupleUnit(ask)) || 'project';
    (waiting[key] ||= []).push(`${ask.id}: ${ask.question}`);
  }
  const pendingVerdict = records.filter((r) => (!r.unit || unitName(r.unit) === unit)
    && (r.final || r.t0)?.verdict === 'INCONSISTENT').at(-1);
  const contradiction = lint.contradictions?.[0];
  const drift = lint.receipt_drift?.[0];
  let next;
  if (session.halt?.open) {
    next = `Reconcile unmanaged edit ${session.halt.files?.[0] || '(see session)'} at the session prompt (${sessionCommand(project)})`;
    (waiting[unitName(config.active_unit) || 'project'] ||= []).unshift(next);
  } else if (pendingVerdict || contradiction) next = `Resolve contradiction ${pendingVerdict?.id || contradiction.claim || contradiction.ids?.join(', ')} before continuing`;
  else if (drift) next = `Review changed receipt ${drift.id} through accept`;
  const unitConfig = Array.isArray(config.units) ? config.units.find((u) => unitName(u) === unit) : config.units?.[unit];
  const checklist = unitConfig?.checklist || config.checklist || [];
  const open = checklist.find((c) => typeof c === 'object' && c.done !== true && c.status !== 'done' && (!c.unit || c.unit === unit));
  if (!next && open) next = open.action || open.text || open.title || open.id;
  const due = [...(lint.threads_due || [])].sort((a, b) => (a.order === 'reader_order' ? 0 : 1) - (b.order === 'reader_order' ? 0 : 1));
  if (!next && due.length) next = `Review ${due[0].thread}: ${due[0].note}`;
  if (!next) next = asks.find(inUnit)?.question;
  const eventDates = [...events.filter((e) => ['verdict', 'addendum'].includes(e.type)).map((e) => e.at),
    ...(session.receipts || []).filter((r) => (['accept', 'lint'].includes(r.transition) || r.lint_event) && !r.invalidated).map((r) => r.lint_event?.at || r.at),
    lintEvent].filter(Boolean).sort();
  const status = { project: surfaceText(project) || 'project', unit,
    cascade_position: typeof cascadeValue === 'string' || typeof cascadeValue === 'number' ? String(cascadeValue) : position || manifest.last_chapter || 'unset',
    next_action: next || 'none open - dictate an idea', waiting_on_john: waiting,
    last_session: eventDates.at(-1)?.slice(0, 10) || 'never' };
  return setSurfaceLimit(status, config.surface?.max_waiting_per_unit ?? 3);
}
export function rebuildStatus(root, opts = {}) {
  const inputs = readSurfaceInputs(root, opts), status = projectStatus(inputs);
  if (Object.keys(status).join() !== STATUS_FIELDS.join()) throw new Error('invalid status projection');
  const stateDir = stateDirFor(root, opts.stateDir);
  const isolated = path.resolve(stateDir) !== path.resolve(stateDirFor(root));
  const file = path.join(isolated ? stateDir : root, 'STATUS.json'), session = opts.session || inputs.session;
  const previous = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
  const drift = previous !== null && (!session.status_generation || sha256Text(previous) !== session.status_generation.digest);
  const text = JSON.stringify(status, null, 2) + '\n', digest = sha256Text(text);
  if (drift) journalEvent(stateDir, { event: 'status-drift', previous_digest: sha256Text(previous) });
  atomicWriteFile(file, text);
  // Metadata belongs to the transition receipt/session so STATUS has exactly its six keys.
  session.status_generation = { digest, at: opts.now || new Date().toISOString(), path: 'STATUS.json' };
  return { ok: true, status, inputs, digest, drift, session,
    warning: drift ? 'status: regenerated (hand edit discarded)' : null };
}
export function heartbeatArgs(root, status) {
  return ['heartbeat', '--project', root, '--phase', status.cascade_position,
    '--active-effort', `${status.project} · ${status.unit}`, '--human-wait', renderWaiting(status), '--next-recommended', status.next_action];
}
export function sessionCommand(project) {
  const value = surfaceText(project) || 'project';
  return `chekhov ${/^[a-z0-9_-]+$/i.test(value) ? value : `"${value.replaceAll('"', '')}"`}`;
}
export const DEFAULT_ECGBERHT_MODULE = '<path>';
/** An argv seam, never a shell command or a dependency on a PATH alias. */
export function heartbeatCommand(command) {
  const argv = command ?? (process.env.CHEKHOV_ECGBERHT_COMMAND
    ? JSON.parse(process.env.CHEKHOV_ECGBERHT_COMMAND)
    : [process.execPath, process.env.CHEKHOV_ECGBERHT_MODULE || DEFAULT_ECGBERHT_MODULE]);
  if (!Array.isArray(argv) || !argv.length || argv.some((v) => typeof v !== 'string' || !v || /[\r\n\0]/.test(v))) {
    throw new Error('Ecgberht command must be a nonempty JSON argv array');
  }
  return [...argv];
}
export function pushHeartbeat(root, { status, run = spawnSync, command, stateDir } = {}) {
  if (path.resolve(stateDirFor(root, stateDir)) !== path.resolve(stateDirFor(root))) {
    return { ok: true, pushed: false, reason: 'isolated_session', line: 'steward: not published (isolated session state)' };
  }
  if (!fs.existsSync(path.join(root, 'strip.json')) && !fs.existsSync(path.join(root, 'ECGBERHT.md'))) {
    return { ok: true, pushed: false, reason: 'no_face_or_strip', line: 'steward: not wired (no_face_or_strip)' };
  }
  const failed = (reason) => ({ ok: false, pushed: false, reason, line: `steward: not wired (${reason})` });
  try {
    const [binary, ...prefix] = heartbeatCommand(command);
    const out = run(binary, [...prefix, ...heartbeatArgs(root, status)], {
      encoding: 'utf8', windowsHide: true, shell: false, timeout: 10000, maxBuffer: 1024 * 1024,
    });
    if (out.error) return failed(out.error.code || out.error.message);
    let reply;
    try { reply = JSON.parse(out.stdout || ''); } catch { return failed('heartbeat-output-unreadable'); }
    if (out.status !== 0 || reply.ok !== true) return failed(reply.error || 'heartbeat-refused');
    const stripFile = path.join(root, 'strip.json');
    if (reply.persisted?.strip !== true || !fs.existsSync(stripFile)) return failed('strip-not-produced');
    const strip = JSON.parse(fs.readFileSync(stripFile, 'utf8'));
    const expected = { phase: status.cascade_position, active_effort: `${status.project} · ${status.unit}`,
      human_wait: renderWaiting(status), next_recommended: status.next_action };
    for (const [key, value] of Object.entries(expected)) if (strip[key] !== value) return failed(`strip-mismatch:${key}`);
    return { ok: true, pushed: true, fields: expected, line: `steward: wired ${fs.statSync(stripFile).mtime.toISOString()}` };
  } catch (e) { return failed(e.code || e.message); }
}
export function composeBrief({ status, inputs, steward = 'steward: not wired (no_face_or_strip)', warnings = [] }) {
  const lines = [renderLine1(status), [steward, ...warnings.filter(Boolean)].join(' | ')];
  const tuples = inputs.entries.map((e) => e.tuple);
  const body = [];
  for (const [unit, asks] of Object.entries(status.waiting_on_john)) for (const ask of asks) body.push(`Ask (${unit}): ${surfaceText(ask)}`);
  for (const t of tuples.filter((t) => t.kind === 'fact' && t.value.predicate === 'alive' && t.value.object === true && hasAcceptance(t))) body.push(`Alive: ${t.value.entity}`);
  for (const t of tuples.filter((t) => t.lock === 'locked' && hasAcceptance(t) && (!tupleUnit(t) || tupleUnit(t) === status.unit))) body.push(`Locked: ${t.id}`);
  for (const row of inputs.lint.threads_due || []) body.push(`Thread (${row.order}): ${row.thread} ${row.note}`);
  for (const t of tuples.filter((t) => t.kind === 'structural' && t.value.fork && t.value.status !== 'closed')) body.push(`Fork: ${t.id}`);
  const coverage = inputs.config.source_coverage || inputs.config.coverage;
  if (coverage) body.push(`Coverage: ${typeof coverage === 'string' ? coverage : JSON.stringify(coverage)}`);
  for (const t of tuples.filter((t) => t.kind === 'structural' && t.value.submission)) body.push(`Waiting on others (${tupleUnit(t) || 'project'}): ${surfaceText(typeof t.value.submission === 'string' ? t.value.submission : JSON.stringify(t.value.submission))}`);
  const words = (rows) => rows.join(' ').trim().split(/\s+/).length;
  const marker = 'brief: truncated at 200 words';
  for (const line of body) {
    if (words([...lines, line, marker]) > SURFACE_CONTRACT.max_words) { lines.push(marker); break; }
    lines.push(line);
  }
  // Full pinned asks are retained for an expanded reader even when the short brief truncates.
  return { lines, pinned_asks: status.waiting_on_john, over_limit: words(lines) > SURFACE_CONTRACT.max_words };
}
