/** Thin transport to Anchor's existing run store and deliverables registrar. */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { renderLine1, renderWaiting } from './surface.mjs';

export const ANCHOR_PAYLOAD_SCHEMA = 'chekhov-anchor-session-v1';
export const ANCHOR_ADAPTER = fileURLToPath(new URL('../bin/anchor_adapter.py', import.meta.url));
export const DELIVERABLE_KINDS = Object.freeze(['ledger-report', 'verdicts', 'render', 'lock-receipt']);
const identifier = (s) => typeof s === 'string' && /^[a-z0-9][a-z0-9_.-]{0,95}$/i.test(s);
const object = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function validateAnchorRequest(payload, roots = {}) {
  const keys = ['schema', 'project', 'folder', 'project_id', 'session_id', 'commission_id', 'step_id', 'unit', 'live', 'replay', 'sources_file', 'text'];
  if (!object(payload) || payload.schema !== ANCHOR_PAYLOAD_SCHEMA || Object.keys(payload).some((k) => !keys.includes(k))) {
    throw new Error(`Anchor stdin requires a ${ANCHOR_PAYLOAD_SCHEMA} object with supported fields only`);
  }
  if (typeof payload.project !== 'string' || !payload.project.trim() || payload.project.length > 512 || /[\r\n\0"|]/.test(payload.project)) {
    throw new Error('Anchor session requires a bounded project name');
  }
  if (!identifier(payload.session_id) || !identifier(payload.project_id)) throw new Error('Anchor requires explicit project_id and unique session_id');
  for (const key of ['commission_id', 'step_id']) if (payload[key] != null && !identifier(payload[key])) throw new Error(`Invalid Anchor ${key}`);
  const registered = roots[payload.project]?.path;
  const requested = payload.folder ?? registered;
  if (typeof requested !== 'string' || !path.isAbsolute(requested) || !fs.statSync(requested).isDirectory()) throw new Error('Anchor requires an existing absolute project folder');
  const root = fs.realpathSync(requested);
  if (registered && fs.realpathSync(registered) !== root) throw new Error('Anchor folder disagrees with the registered project');
  const configFile = path.join(root, 'chekhov', 'config.json');
  const config = fs.existsSync(configFile) ? JSON.parse(fs.readFileSync(configFile, 'utf8')) : {};
  if (!object(config) || config.project && config.project !== payload.project || !registered && config.project !== payload.project) {
    throw new Error('Anchor folder must match the existing project configuration');
  }
  if (payload.unit != null && (typeof payload.unit !== 'string' || !payload.unit.trim() || payload.unit.length > 120 || /[\r\n\0]/.test(payload.unit))) throw new Error('Invalid session unit');
  if (payload.live != null && typeof payload.live !== 'boolean') throw new Error('live must be explicit true or false');
  if (payload.live && payload.replay) throw new Error('Choose live or replay');
  for (const key of ['replay', 'sources_file']) if (payload[key] != null && (typeof payload[key] !== 'string' || !payload[key])) throw new Error(`Invalid ${key}`);
  if (payload.text != null && (typeof payload.text !== 'string' || Buffer.byteLength(payload.text, 'utf8') > 32768)) throw new Error('Invalid bounded session text');
  const anchor = config.integrations?.anchor ?? {};
  if (!object(anchor) || anchor.enabled === false) throw new Error('Anchor integration is disabled or invalid for this project');
  return { root, payload, config, anchor };
}

export function callAnchorAdapter(request, config = {}, { run = spawnSync, timeout = 30000 } = {}) {
  try {
    const command = config.python_command ?? (process.env.CHEKHOV_ANCHOR_PYTHON
      ? JSON.parse(process.env.CHEKHOV_ANCHOR_PYTHON) : ['python']);
    if (!Array.isArray(command) || !command.length || command.some((v) => typeof v !== 'string' || !v || /[\r\n\0]/.test(v))) throw new Error('Python command must be a JSON argv array');
    const [binary, ...prefix] = command;
    const out = run(binary, [...prefix, '-B', ANCHOR_ADAPTER], { input: JSON.stringify({ ...request,
      anchor_dir: config.anchor_dir || process.env.CHEKHOV_ANCHOR_DIR || '<path>' }),
      encoding: 'utf8', windowsHide: true, shell: false, timeout, maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' } });
    if (out.error) throw out.error;
    let reply;
    try { reply = JSON.parse(out.stdout || ''); } catch { throw new Error(`Anchor adapter output unreadable (exit ${out.status}): ${(out.stderr || '').slice(-400)}`); }
    if (out.status !== 0 || reply.ok !== true) return { ...reply, ok: false, error: reply.error || `adapter-exit:${out.status}` };
    return reply;
  } catch (e) { return { ok: false, error: e.code || e.message }; }
}

/** These are artifact facts, not a new register. Missing files get no rows. */
export function producedDeliverables(root, config = {}) {
  const extra = config.deliverables ?? [];
  if (!Array.isArray(extra) || extra.length > 64) throw new Error('At most 64 declared deliverable paths');
  const declarations = [{ kind: 'ledger-report', path: 'chekhov/LEDGER-REPORT.md' },
    { kind: 'verdicts', path: 'chekhov/VERDICTS.md' }, ...extra];
  const seen = new Map(), files = [];
  for (const item of declarations) {
    if (!item || !DELIVERABLE_KINDS.includes(item.kind) || typeof item.path !== 'string' || !item.path
      || path.isAbsolute(item.path) || item.path.includes(':') || /[\r\n\0`|]/.test(item.path)) throw new Error('Invalid produced deliverable declaration');
    const target = path.resolve(root, item.path), relative = path.relative(root, target);
    if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error('Deliverable escapes project');
    let at = root;
    for (const segment of relative.split(path.sep)) {
      at = path.join(at, segment);
      if (fs.existsSync(at) && fs.lstatSync(at).isSymbolicLink()) throw new Error('Linked deliverables are refused');
    }
    if (!fs.existsSync(target)) continue;
    if (!fs.statSync(target).isFile()) throw new Error('Deliverable must be a produced file');
    const real = fs.realpathSync(target);
    if (seen.has(real)) {
      if (seen.get(real) !== item.kind) throw new Error('One produced path cannot have competing kinds');
      continue;
    }
    seen.set(real, item.kind);
    files.push({ kind: item.kind, path: relative.replaceAll('\\', '/') });
  }
  return files;
}

export function publishAnchorSession(request, { started, ended, result, lines, journal }) {
  try {
    const status = object(result.status) ? result.status : null;
    const human_wait = status ? renderWaiting(status) : '';
    const report = { say: [...(result.brief || lines), ...(journal ? [`Session draft: ${journal.path}`] : [])].join('\n'), start: started, end: ended,
      halt: Boolean(result.halted), human_wait, status_line: status ? renderLine1(status) : null,
      status_source: !status ? 'unavailable; no current status published'
        : result.halted ? 'current blocking projection; STATUS.json retained' : 'STATUS.json',
      heartbeat: result.heartbeat || null,
      journal: journal?.path || null, author_sitting: 'pending John', thirty_second_test: 'pending' };
    let deliverables = [], integration_errors = result.heartbeat?.pushed === true ? []
      : [`heartbeat: ${result.heartbeat?.reason || 'not produced'}`];
    try { deliverables = producedDeliverables(request.root, request.anchor); }
    catch (e) { integration_errors.push(e.message); }
    return callAnchorAdapter({ action: 'record_session', folder: request.root,
      project_id: request.payload.project_id, session_id: request.payload.session_id,
      commission_id: request.payload.commission_id || null, step_id: request.payload.step_id || null,
      outcome: result.halted || human_wait && human_wait !== 'none' ? 'asked'
        : result.ok && result.heartbeat?.pushed === true ? 'produced' : 'died',
      report, deliverables, integration_errors }, request.anchor);
  } catch (e) { return { ok: false, error: e.message }; }
}
