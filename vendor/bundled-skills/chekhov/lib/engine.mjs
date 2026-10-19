/**
 * The session engine (RIDER 6) — W1 skeleton.
 *
 * A session is a STATE MACHINE: start → intake → check → write → status → end.
 * Later waves add lint, commit, structure, guard, render, draft and lock as
 * NAMED EDGES of this machine — never as free-standing commands an agent
 * chooses to run. The machine is the ONLY caller of the transition modules
 * (lib/transitions/*); a source-grep test fails on any other import path.
 *
 * No receipt, no step: a transition whose predecessor receipt is missing
 * REFUSES, naming the missing receipt. Every transition writes a receipt
 * {transition, at, inputs_hash, outputs_hash, manifest_hash, seat?} through
 * lib/store.mjs.
 *
 * The FIXED start order (RIDER 5): manifest verification → lint → STATUS.json
 * rebuild → heartbeat push → print. A stale status is never published ahead of
 * a detected edit: an engine-owned mismatch prints `unmanaged edit: <file>` on
 * line 2, opens a reconciliation HALT, suppresses the status rebuild, and
 * publishes only the current blocking projection through heartbeat (RIDER 7).
 * It invalidates every later receipt until John closes it (confirm key,
 * TTY-only — a seat can never launder a write).
 */
import { computeManifest, diffManifests, manifestHash, sha256Text } from './manifest.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';
import {
  stateDirFor,
  loadSession,
  saveSession,
  appendReceipt,
  lastReceipt,
  withLock, appendRecord, atomicWriteFile, SESSION_SCHEMA, journalEvent,
} from './store.mjs';
import { buildLedger, loadLedgerEntries, verdictData, entriesForUnit } from './index.mjs';
import { loadProjectPack, readPack } from './pack.mjs';
import { t0ForRoot } from './t0.mjs';
import { IDEA_LIMIT, IDEA_PROMPT_HASH, typeIdea, evaluateIdea, sanitizeIdea, unknownVerdict, renderIdea, VERDICTS } from './idea.mjs';
import { failureRow } from './failure-states.mjs';
import { runLint } from './transitions/lint.mjs';
import { rebuildStatus, pushHeartbeat, composeBrief, readSurfaceInputs, projectStatus } from './status.mjs';
import { renderLine1 } from './surface.mjs';
import { draftSessionJournal } from './session-journal.mjs';
import { validateAnchorRequest, callAnchorAdapter, publishAnchorSession } from './anchor.mjs';
import { renderStructure } from './structure.mjs';
import { commitProject } from './commit.mjs';
import { acceptProject } from './accept.mjs';
import { buildT1Packet, createT1Judge, runT1, renderT1, validateT1Replay,
  verifyT1Rows, verifyT1Index, T1_LIMITS, t1TimingReport, t1SourcePath } from './t1.mjs';

const ideaJudges = new Map();
function judgeFor(root, opts) {
  if (opts.judge) return opts.judge;
  const key = path.resolve(root);
  if (!ideaJudges.has(key)) ideaJudges.set(key, createT1Judge({ createSession: opts.createJudgeSession }));
  return ideaJudges.get(key);
}
export async function closeIdeaJudge(root) {
  const key = path.resolve(root), judge = ideaJudges.get(key);
  ideaJudges.delete(key);
  await judge?.close();
}
function readIdeaReplay(root, value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  const file = t1SourcePath(root, value);
  if (fs.statSync(file).size > T1_LIMITS.packet_bytes * 4) throw new Error('replay exceeds 1048576 bytes');
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/** The CLOSED session states. Adding a state is a plan change, not a patch. */
export const STATES = Object.freeze(['start', 'intake', 'check', 'write', 'status', 'end']);

/** Named edges later waves attach to this machine (W4/W6/W5/W18/W19/W20). */
export const FUTURE_EDGES = Object.freeze([
  'lint', 'commit', 'structure', 'guard', 'render', 'draft', 'lock', 'journal', 'brief',
]);

/** Predecessor chain: no receipt, no step. */
const PRED = Object.freeze({
  intake: 'start',
  check: 'intake',
  write: 'check',
  status: 'write',
  end: 'status',
});

/**
 * Session prompt keys — operator transitions John presses at the TTY prompt.
 * Hosts NEVER see these: promptKeys() returns [] off-TTY, and no host-facing
 * document names them (they live in HUMAN.md only).
 */
const SESSION_KEYS = Object.freeze([
  Object.freeze({ key: 'l', action: 'lint' }),
  Object.freeze({ key: 's', action: 'structure' }),
  Object.freeze({ key: 'c', action: 'commit' }),
  Object.freeze({ key: 'm', action: 'migrate' }),
  Object.freeze({ key: 'u', action: 'set unit' }),
  Object.freeze({ key: 'r', action: 'render' }),
]);

function isRealTty() {
  return process.stdin.isTTY === true && process.stdout.isTTY === true;
}

/** The operator key table — empty unless the session runs on a real TTY. */
export function promptKeys() {
  return isRealTty() ? SESSION_KEYS.map((k) => ({ ...k })) : [];
}

function refuse(reason) {
  return { ok: false, refused: true, reason };
}

/** W6 operator edges still enter through the session engine. */
export async function requestCommit(root, opts = {}) {
  return commitProject(root, opts);
}

export async function requestAccept(root, opts = {}) {
  return acceptProject(root, opts);
}

/** Operator inspections are engine edges; W5 changes only the report on disk. */
export function requestInspection(root, name, opts = {}) {
  if (!['lint', 'structure'].includes(name)) return refuse(`unknown inspection: ${name}`);
  const session = loadSession(stateDirFor(root, opts.stateDir));
  if (session.halt?.open) return refuse('reconciliation HALT open — inspection refused');
  const lint = runLint(root, opts);
  if (!lint.t0) return { ...refuse(lint.t0_error || lint.t0_skipped), lint };
  return { ok: true, transition: name, lint, structure: lint.t0.structure,
    lines: name === 'structure' ? renderStructure(lint.t0.structure) : [
      `contradictions=${lint.contradictions}`, `criterion 1: ${lint.criterion1 ? 'GREEN' : 'NOT GREEN'}`, ...lint.outline_gate.lines,
    ] };
}

function openHalt(session, files, now) {
  session.halt = {
    kind: 'reconciliation',
    files: [...files],
    detected_at: now,
    open: true,
  };
  // Invalidate every receipt written after the halt is detected, until it
  // closes — a receipt that lands while a halt is open proves nothing.
  markInvalidatedReceipts(session);
}

/** Flag receipts written after an open halt's detection (laundering guard). */
export function markInvalidatedReceipts(session) {
  if (!session.halt || !session.halt.open) return session;
  for (const r of session.receipts) {
    if (r.at > session.halt.detected_at) r.invalidated = true;
  }
  return session;
}

/**
 * The start transition — the FIXED order, each step recorded:
 * manifest → lint → status → heartbeat → print.
 */
export function startSession(root, opts = {}) {
  return withLock(stateDirFor(root, opts.stateDir), opts.lockOpts, (token) =>
    startSessionLocked(root, { ...opts, lockOpts: { ...opts.lockOpts, heldToken: token } }));
}

function startSessionLocked(root, opts) {
  const now = opts.now || new Date().toISOString();
  const stateDir = stateDirFor(root, opts.stateDir);
  const project = opts.project || 'project';
  const session = loadSession(stateDir);
  const steps = [];
  // 1. manifest verification — always first; a stale status is never
  //    published ahead of a detected edit.
  const prev = session.manifest;
  const cur = computeManifest(root);
  const diff = prev ? diffManifests(prev, cur) : { changed_prose: [], unmanaged_engine: [] };
  // W10 gives this generated projection its own drift receipt; all other
  // engine files still use the original reconciliation guard.
  diff.unmanaged_engine = diff.unmanaged_engine.filter((file) => file !== 'STATUS.json');
  let line2 = null;
  let halted = Boolean(session.halt && session.halt.open);
  if (diff.unmanaged_engine.length > 0) {
    line2 = `unmanaged edit: ${diff.unmanaged_engine[0]}`;
    openHalt(session, diff.unmanaged_engine, now);
    halted = true;
  } else if (halted) {
    line2 = `unmanaged edit: ${session.halt.files[0]}`;
  } else if (diff.changed_prose.length > 0) {
    line2 = `changed since last session: ${diff.changed_prose[0]}`;
    session.queued_for_commit = [...new Set([...(session.queued_for_commit || []), ...diff.changed_prose])];
  }
  steps.push({ step: 'manifest', ok: true, halted, changed_prose: diff.changed_prose, unmanaged: diff.unmanaged_engine });

  try { readSurfaceInputs(root, { ...opts, session }); }
  catch (e) {
    // A malformed authoritative file must not prevent a detected unmanaged
    // edit from opening its durable HALT. No derived status is published.
    if (halted) saveSession(stateDir, session);
    const reason = e.message.startsWith('backing-store-unreadable:') ? e.message : `backing-store-unreadable: ${e.message}`;
    return { ok: false, halted: true, reason, line2, lines: [reason, line2].filter(Boolean), steps, session, stateDir };
  }

  // 2. lint (T0 seam; ≤ 2 s budget)
  const lintLockOpts = { ...opts.lockOpts };
  if (path.resolve(stateDirFor(root, opts.stateDir)) !== path.resolve(stateDirFor(root))) delete lintLockOpts.heldToken;
  const lint = runLint(root, { lockOpts: lintLockOpts });
  steps.push({ step: 'lint', ok: lint.ok, duration_ms: lint.duration_ms });

  let projection, heartbeat;
  if (!halted) {
    projection = rebuildStatus(root, { ...opts, now, session, project, lint, manifest: cur });
    steps.push({ step: 'status', ok: true });
    heartbeat = pushHeartbeat(root, { status: projection.status, stateDir, run: opts.heartbeatRun,
      command: opts.heartbeatCommand || projection.inputs.config.integrations?.ecgberht?.command });
    steps.push({ step: 'heartbeat', ok: heartbeat.ok, pushed: heartbeat.pushed });
  } else {
    const inputs = readSurfaceInputs(root, { ...opts, project, session, lint, manifest: cur });
    projection = { inputs, status: projectStatus(inputs) };
    projection.warning = 'status: retained on disk; this brief and heartbeat describe the current reconciliation HALT';
    heartbeat = pushHeartbeat(root, { status: projection.status, stateDir, run: opts.heartbeatRun,
      command: opts.heartbeatCommand || inputs.config.integrations?.ecgberht?.command });
    steps.push({ step: 'status', ok: false, skipped: 'reconciliation HALT open — status not rebuilt' });
    steps.push({ step: 'heartbeat', ok: heartbeat.ok, pushed: heartbeat.pushed, blocking_projection: true });
  }
  const brief = composeBrief({ ...projection, steward: heartbeat.line,
    warnings: [line2, projection.warning, ...(session.stale_renders || []).map((file) => `stale render: ${file}`)] });
  steps.push({ step: 'print', ok: true });

  // Baseline only moves when the tree is reconciled.
  if (!halted) session.manifest = computeManifest(root);

  appendReceipt(stateDir, session, {
    transition: opts.transition || 'start',
    at: now,
    inputs_hash: prev ? manifestHash(prev) : sha256Text('no-prior-manifest'),
    outputs_hash: manifestHash(cur),
    manifest_hash: manifestHash(cur),
    halted,
    ...(lint.t0 ? { lint_event: { at: now } } : {}),
    generation: projection.digest ? { digest: projection.digest, path: 'STATUS.json' } : null,
    steps: steps.map((s) => s.step),
  });

  return { ok: !halted, halted, line2, lines: opts.print === false ? [] : brief.lines,
    brief: brief.lines, status: projection.status, heartbeat, steps, lint, session, stateDir };
}

export function requestStatus(root, opts = {}) {
  const result = startSession(root, { ...opts, transition: 'status', print: false });
  if (opts.line && result.status) result.lines = [renderLine1(result.status)];
  return result;
}
export function setSessionUnit(root, unit, opts = {}) {
  if (typeof unit !== 'string' || !unit.trim() || unit.length > 120 || /[\r\n]/.test(unit)) return refuse('Supply a short unit name.');
  return withLock(stateDirFor(root), opts.lockOpts, () => {
    const session = ideaSession(root);
    verifyIdeaManifest(root, session);
    const file = path.join(stateDirFor(root), 'config.json');
    const config = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
    config.active_unit = unit.trim();
    atomicWriteFile(file, JSON.stringify(config, null, 2) + '\n');
    return { ok: true, unit: config.active_unit };
  });
}
/** No-Bible setup records only explicit operator configuration, never canon. */
export function prepareSession(root, opts = {}) {
  if (!fs.existsSync(root)) fs.mkdirSync(root, { recursive: true });
  return withLock(stateDirFor(root), opts.lockOpts, () => {
    const session = ideaSession(root);
    verifyIdeaManifest(root, session);
    const file = path.join(stateDirFor(root), 'config.json');
    const config = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
    if (opts.pack) {
      const pack = readPack(opts.pack);
      if (pack.stub) return refuse('This form pack is a stub; complete its existing pack contract before intake.');
      if (config.pack && config.pack !== opts.pack) return refuse('Existing form selection must be changed through the supported decision path.');
      config.pack = opts.pack;
    }
    if (opts.unit) config.active_unit = opts.unit;
    if (opts.project && !config.project) config.project = opts.project;
    if (!config.surface) config.surface = { max_waiting_per_unit: 3 };
    atomicWriteFile(file, JSON.stringify(config, null, 2) + '\n');
    return { ok: true, config };
  });
}
export function endSession(root, opts = {}) {
  const result = startSession(root, { ...opts, transition: 'end', print: false });
  // A readable reconciliation HALT can end and leave an unsigned draft. It
  // still cannot rebuild STATUS, accept anything or close the HALT.
  if (!result.ok && !result.status) return result;
  return withLock(stateDirFor(root, opts.stateDir), opts.lockOpts, () => {
    const session = loadSession(stateDirFor(root, opts.stateDir));
    const journal = draftSessionJournal(root, session, { ...opts,
      now: result.session.receipts.findLast((r) => r.transition === 'end')?.at || new Date().toISOString() });
    saveSession(stateDirFor(root, opts.stateDir), session);
    return { ...result, journal, lines: [`Session saved. Journal draft: ${journal.path}`] };
  });
}

/**
 * Request a non-start transition. Refusal rules, in order:
 *   1. unknown transition (closed set)
 *   2. reconciliation HALT open
 *   3. missing predecessor receipt (the EARLIEST missing one is named)
 *   4. write only: the manifest is re-verified immediately before the write;
 *      an engine-owned mismatch refuses naming the file and opens the HALT.
 */
export function requestTransition(root, name, opts = {}) {
  if (name === 'intake' && (Object.hasOwn(opts, 'text') || opts.file)) return requestIdea(root, opts);
  if (name === 'write' && (Object.hasOwn(opts, 'text') || opts.verdict_id)) return writeIdea(root, opts);
  return withLock(stateDirFor(root, opts.stateDir), opts.lockOpts, (token) =>
    requestTransitionLocked(root, name, { ...opts, lockOpts: { ...opts.lockOpts, heldToken: token } }));
}

function requestTransitionLocked(root, name, opts) {
  const now = opts.now || new Date().toISOString();
  const stateDir = stateDirFor(root, opts.stateDir);
  const session = opts.session || loadSession(stateDir);

  if (!STATES.includes(name) || name === 'start') {
    return refuse(`unknown transition: ${name} (closed set: ${STATES.join(' → ')})`);
  }
  if (session.halt && session.halt.open) {
    return refuse(
      `reconciliation HALT open (${session.halt.files.join(', ')}) — confirm or revert through accept before any transition`,
    );
  }
  // Walk the chain from the beginning; name the EARLIEST missing receipt.
  const chain = [];
  for (let s = name; PRED[s]; s = PRED[s]) chain.unshift(PRED[s]);
  for (const predecessor of chain) {
    if (!lastReceipt(session, predecessor)) {
      return refuse(`no receipt, no step: missing receipt '${predecessor}' before '${name}'`);
    }
  }

  let cur = session.manifest;
  if (name === 'write') {
    // Re-verify IMMEDIATELY before the write; an edit between transitions is
    // caught at the next write, not the next session.
    cur = computeManifest(root);
    const diff = diffManifests(session.manifest, cur);
    if (diff.unmanaged_engine.length > 0) {
      openHalt(session, diff.unmanaged_engine, now);
      saveSession(stateDir, session);
      return refuse(`unmanaged edit: ${diff.unmanaged_engine[0]} — write refused; reconciliation HALT opened`);
    }
    if (diff.changed_prose.length > 0) {
      session.queued_for_commit = [...new Set([...(session.queued_for_commit || []), ...diff.changed_prose])];
    }
    // Every configured writing path consults the same decision gate after
    // unmanaged edits have been checked; generic W1 roots still have no pack.
    const lint = runLint(root, { open: false, lockOpts: opts.lockOpts });
    if (lint.t0_error) return refuse(lint.t0_error);
    if (lint.t0?.gate.refused) return { ...refuse(lint.t0.gate.lines.join('\n')), gate: lint.t0.gate };
    if (lint.t0 && !lint.t0.criterion1) return refuse('Outline refused: criterion 1 is not green on prose; see LEDGER-REPORT.md.');
    if (lint.t0?.doctrine.hits.length) return refuse(`Outline refused: unallowed doctrine vocabulary (${lint.t0.doctrine.hits.map((h) => h.term).join(', ')}); see LEDGER-REPORT.md.`);
  }
  const mh = manifestHash(cur || { files: {} });
  const receipt = {
    transition: name,
    at: now,
    inputs_hash: opts.inputs_hash || mh,
    outputs_hash: opts.outputs_hash || mh,
    manifest_hash: mh,
  };
  if (opts.seat) receipt.seat = opts.seat;
  if (name === 'write') session.manifest = cur;
  appendReceipt(stateDir, session, receipt);
  return { ok: true, receipt, session };
}

// Intake snapshots are checked again after each bounded seat call. No seat
// holds a root lock and no model response becomes a document write.
function ideaSession(root) {
  const dir = stateDirFor(root), file = path.join(dir, 'session.json');
  if (fs.existsSync(file)) {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (parsed.schema !== SESSION_SCHEMA || !Array.isArray(parsed.receipts)) throw new Error('invalid session store');
    return parsed;
  }
  return loadSession(dir);
}
function verifyIdeaManifest(root, session) {
  if (session.halt?.open) throw new Error('reconciliation HALT open');
  const current = computeManifest(root);
  const diff = session.manifest ? diffManifests(session.manifest, current) : { unmanaged_engine: [], changed_prose: [] };
  if (diff.unmanaged_engine.length) {
    openHalt(session, diff.unmanaged_engine, new Date().toISOString());
    saveSession(stateDirFor(root), session);
    throw new Error(`unmanaged edit: ${diff.unmanaged_engine[0]} — reconciliation HALT opened`);
  }
  const previous = JSON.stringify(session.queued_for_commit || []);
  session.queued_for_commit = [...new Set([...(session.queued_for_commit || []), ...diff.changed_prose])];
  if (JSON.stringify(session.queued_for_commit) !== previous) saveSession(stateDirFor(root), session);
  return current;
}
function ideaInputs(root, id, selectedUnit) {
  const pack = loadProjectPack(root);
  const data = verdictData(root);
  const configText = fs.readFileSync(path.join(stateDirFor(root), 'config.json'), 'utf8');
  const config = JSON.parse(configText);
  const unit = [selectedUnit, data.verdicts.find((r) => r.id === id)?.unit, config.active_unit]
    .find(value => typeof value === 'string' && value.trim());
  const unitRequired = config.shared_story_world === false && !unit;
  const entries = unitRequired ? [] : entriesForUnit(loadLedgerEntries(root), config, unit, id);
  const actions = data.records.filter((r) => r.type === 'candidate-action' && r.verdict_id === id);
  const manifest = computeManifest(root);
  const hash = sha256Text(JSON.stringify({ pack, entries, actions, manifest,
    config: configText, unit: unit || null }));
  return { pack, entries, hash, manifest, unit, unitRequired };
}
function ideaFailure(row, reason) {
  const f = failureRow('idea', row);
  return { ok: false, status: f.status, row, reason, lines: [f.text, reason].filter(Boolean) };
}
function containedFile(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || relative.includes(':')) throw new Error('root-relative file required');
  const absoluteRoot = fs.realpathSync(root), target = path.resolve(absoluteRoot, relative);
  const rel = path.relative(absoluteRoot, target);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw new Error('file escapes project root');
  let at = absoluteRoot;
  for (const part of rel.split(path.sep)) {
    at = path.join(at, part);
    if (fs.existsSync(at) && fs.lstatSync(at).isSymbolicLink()) throw new Error('linked writing paths are refused');
  }
  return target;
}

export async function requestIdea(root, opts = {}) {
  const fullStarted = Date.now();
  let judgeRequired = !opts.createSession || Boolean(opts.live || opts.replay || opts.createJudgeSession || opts.judge);
  let raw, inputs, id, source = null, replay = null, selections = opts.sources || [];
  try {
    containedFile(root, 'chekhov/session.json');
    if (opts.file && Object.hasOwn(opts, 'text')) return ideaFailure('dependency-returns-garbage', 'Choose text or file.');
    if (opts.file) {
      const relative = path.isAbsolute(opts.file) ? path.relative(root, opts.file) : opts.file;
      const file = containedFile(root, relative);
      if (!path.relative(root, file).replace(/\\/g, '/').startsWith('chekhov/inbox/')) return ideaFailure('dependency-returns-garbage', 'Drop files belong in chekhov/inbox; project documents are not typing context.');
      if (fs.statSync(file).size > IDEA_LIMIT) throw new Error('idea exceeds the bounded input size');
      raw = new TextDecoder('utf-8', { fatal: true }).decode(fs.readFileSync(file));
      source = { file: path.relative(root, file).replace(/\\/g, '/'), hash: sha256Text(raw) };
    } else raw = opts.text;
    if (typeof raw !== 'string' || Buffer.byteLength(raw, 'utf8') > IDEA_LIMIT) return ideaFailure('dependency-returns-garbage', 'Supply bounded text or a UTF-8 drop file.');
    if (opts.scope != null && (typeof opts.scope !== 'string' || opts.scope.length > 256 || /\s/.test(opts.scope))) return ideaFailure('dependency-returns-garbage', 'Scope must be one bounded word.');
    if (!raw.trim()) {
      const f = failureRow('idea', 'empty-but-valid');
      return { ok: true, status: f.status, row: 'empty-but-valid', lines: [f.text] };
    }
    if (opts.outOfScope === true) return { ok: true, status: 0, lines: [`grasscatch: ${raw.replace(/\s+/g, ' ').trim()}`] };
    if (opts.live && opts.replay) throw new Error('Choose recorded replay or explicit --live, not both.');
    if (opts.tolerance && !opts.live) throw new Error('tolerance is permitted only with --live');
    replay = readIdeaReplay(root, opts.replay);
    if (replay) validateT1Replay(replay, raw);
    if (opts.scope == null && replay?.input.scope_override != null) opts = { ...opts, scope: replay.input.scope_override };
    if (opts.sourcesFile) {
      const file = containedFile(root, opts.sourcesFile);
      if (fs.statSync(file).size > T1_LIMITS.packet_bytes) throw new Error('source selections exceed 262144 bytes');
      selections = JSON.parse(fs.readFileSync(file, 'utf8'));
    } else if (replay?.input.sources) selections = replay.input.sources;
    if (!Array.isArray(selections) || selections.length > T1_LIMITS.sources) throw new Error('at most 16 source selections');
    id = opts.rerun_id || `v${crypto.randomUUID().replaceAll('-', '')}`;
    const incoming = ideaInputs(root, id, opts.unit);
    if (!incoming.unitRequired && !opts.rerun_id && opts.rerunPending !== false) await rerunPendingIdeas(root, opts);
    if (!lastReceipt(ideaSession(root), 'start')) {
      const start = startSession(root, { project: opts.project || path.basename(root), lockOpts: opts.lockOpts });
      if (!start.ok) return ideaFailure('backing-store-unreadable', start.reason || 'reconciliation HALT open');
    }
    withLock(stateDirFor(root), opts.lockOpts, () => {
      const session = ideaSession(root), manifest = verifyIdeaManifest(root, session);
      inputs = ideaInputs(root, id, opts.unit);
      if (opts.rerun_id) {
        const original = verdictData(root).verdicts.find((r) => r.id === id);
        if (!original || original.raw_line !== raw) throw new Error('rerun line does not match its immutable verdict');
        judgeRequired ||= original.judge_required === true;
      }
      appendReceipt(stateDirFor(root), session, { transition: 'intake', at: new Date().toISOString(),
        verdict_id: id, inputs_hash: sha256Text(raw), outputs_hash: inputs.hash, manifest_hash: manifestHash(manifest) });
    });
  } catch (e) {
    return ideaFailure(/config_missing|pack_missing|ENOENT/.test(e.code || '') ? 'dependency-missing' : 'backing-store-unreadable', e.message);
  }
  let typed;
  try {
    const saved = replay?.input.extraction || opts.typedReplay;
    typed = inputs.unitRequired ? { extraction: null, seats: [], attempts: 0, duration_ms: 0 }
      : saved ? { extraction: sanitizeIdea(saved), seats: replay?.seats?.typer || opts.typedSeats || [],
      fallback: replay?.typing_fallback || null, attempts: 0, duration_ms: 0 }
      : opts.live || opts.createSession ? await typeIdea(raw, inputs.pack, opts)
        : { extraction: null, seats: [], attempts: 0, duration_ms: 0, row: 'dependency-missing' };
  } catch { typed = { extraction: null, seats: [], attempts: 0, duration_ms: 0, row: 'dependency-returns-garbage' }; }
  try {
    const out = withLock(stateDirFor(root), opts.lockOpts, (token) => {
      const session = ideaSession(root), manifest = verifyIdeaManifest(root, session), current = ideaInputs(root, id, opts.unit);
      const intake = session.receipts.findLast((r) => r.transition === 'intake' && r.verdict_id === id && !r.invalidated);
      if (!intake || intake.inputs_hash !== sha256Text(raw)) throw new Error('missing exact intake receipt');
      const date = new Date().toISOString();
      const stale = current.hash !== inputs.hash || source && sha256Text(fs.readFileSync(containedFile(root, source.file), 'utf8')) !== source.hash;
      const t0Started = Date.now();
      let t0 = current.unitRequired ? unknownVerdict(['Choose the story or novella for this idea. The draft is saved; unrelated stories will not be combined.'])
        : stale ? unknownVerdict(['checked inputs changed during typing; rerun required'], true)
        : typed.extraction ? evaluateIdea(current.pack, current.entries, typed.extraction, { id, raw, date, scope: opts.scope })
          : unknownVerdict([typed.row], typed.row !== 'dependency-returns-garbage');
      if (judgeRequired && t0.claims?.length) {
        try {
          const built = buildT1Packet(root, current, { id, raw_line: raw, t0, scope_override: opts.scope }, selections);
          const cited = new Set([...t0.findings.flatMap((f) => f.cited.map((c) => c.id)),
            ...t0.ripple.filter((r) => r.receipt).map((r) => r.id), ...t0.alternatives.map((a) => a.cited)]);
          const failed = built.packet.entries.filter((e) => cited.has(e.entry_id) && e.citation_error);
          if (failed.length) t0 = unknownVerdict(failed.map((e) => `failed cite: ${e.entry_id}: ${e.citation_error}`));
          else for (const finding of t0.findings) for (const cite of finding.cited) cite.source = built.packet.entries.find((e) => e.entry_id === cite.id)?.source;
        } catch (e) { t0 = unknownVerdict([e.message]); }
      }
      t0.duration_ms = Date.now() - t0Started;
      const config = JSON.parse(fs.readFileSync(path.join(stateDirFor(root), 'config.json'), 'utf8'));
      const record = { type: opts.rerun_id ? 'addendum' : 'verdict', ...(opts.rerun_id ? { verdict_id: id } : { id }),
        at: date, raw_line: raw, line_hash: sha256Text(raw), extraction: typed.extraction, t0,
        typing_fallback: typed.fallback || null,
        unit: current.unit || null, candidates: t0.candidates, seats: typed.seats, prompt_hash: IDEA_PROMPT_HASH,
        timings: { typing_ms: typed.duration_ms, t0_ms: t0.duration_ms, attempts: typed.attempts, full_ms: Date.now() - fullStarted },
        scope_override: opts.scope ?? null, checked_inputs_hash: current.hash, ...(source ? { source } : {}) };
      if (judgeRequired) Object.assign(record, { judge_required: true, source_selections: selections,
        project: opts.project || path.basename(root), candidates: [], t1: null,
        final: [VERDICTS.unknown, VERDICTS.pending].includes(t0.verdict) ? t0 : unknownVerdict(['T1 evidence pending'], true) });
      if (!stale && typed.extraction?.kind === 'prose' && !typed.extraction.claims.length
        && !typed.extraction.unknown_predicates.length && !typed.extraction.unknown_nouns.length) record.inbox = `chekhov/inbox/${id}.prose`;
      appendRecord(stateDirFor(root), path.join(stateDirFor(root), 'VERDICTS.md'), record, opts.lockOpts, token);
      if (record.inbox) atomicWriteFile(containedFile(root, record.inbox), raw);
      atomicWriteFile(path.join(stateDirFor(root), 'ledger.json'), JSON.stringify(buildLedger(current.pack, loadLedgerEntries(root)), null, 2) + '\n');
      session.manifest = manifest;
      appendReceipt(stateDirFor(root), session, { transition: 'check', at: new Date().toISOString(),
        verdict_id: id, inputs_hash: record.line_hash, outputs_hash: sha256Text(JSON.stringify(record)),
        manifest_hash: manifestHash(manifest), checked_inputs_hash: current.hash, seat: typed.seats });
      const joined = verdictData(root).verdicts.find((r) => r.id === id), lines = renderIdea(joined);
      if (typed.row) lines.push(failureRow('idea', typed.row).text);
      return { ok: true, status: typed.row ? failureRow('idea', typed.row).status : 0, row: typed.row || null, record: joined, lines };
    });
    if (!judgeRequired || !out.record) return out;
    opts.onT0?.(out.lines, out.record);
    if (!out.record.t0.claims?.length || out.record.inbox) {
      const verdict = (out.record.final || out.record.t0).verdict;
      return { ...out, status: out.record.inbox ? out.status : verdict === VERDICTS.pending ? 3 : verdict === VERDICTS.unknown ? 5 : out.status };
    }
    const judged = await completeIdeaJudge(root, out.record, { ...opts, replay, fullStarted });
    return { ...judged, t0_lines: out.lines, t0_emitted: Boolean(opts.onT0) };
  } catch (e) { return ideaFailure('backing-store-unreadable', e.message); }
}

async function completeIdeaJudge(root, record, opts) {
  let inputs, built, checkHash;
  try {
    withLock(stateDirFor(root), opts.lockOpts, () => {
      const session = ideaSession(root);
      verifyIdeaManifest(root, session);
      inputs = ideaInputs(root, record.id);
      if (inputs.hash !== record.checked_inputs_hash) throw new Error('checked inputs changed before judge');
      built = buildT1Packet(root, inputs, record, record.source_selections);
      const check = session.receipts.findLast((r) => r.transition === 'check' && r.verdict_id === record.id && !r.invalidated);
      if (!check) throw new Error('missing exact check receipt');
      checkHash = check.outputs_hash;
    });
  } catch (e) { built = { hash: null, packet: { entries: [], coverage: { gaps: [e.message] } } }; }
  let t1 = built.hash ? await runT1({ inputs, record, built, replay: opts.replay,
    live: opts.live === true, judge: opts.live ? judgeFor(root, opts) : null })
    : { rows: [], failed_cites: [], seats: { judge: null }, mode: opts.live ? 'live' : 'replay',
      packet: built.packet, packet_hash: null, final: unknownVerdict(built.packet.coverage.gaps) };
  return withLock(stateDirFor(root), opts.lockOpts, (token) => {
    const session = ideaSession(root), manifest = verifyIdeaManifest(root, session), current = ideaInputs(root, record.id);
    const check = session.receipts.findLast((r) => r.transition === 'check' && r.verdict_id === record.id && !r.invalidated);
    if (built.hash) {
      const latest = buildT1Packet(root, current, record, record.source_selections);
      if (current.hash !== inputs.hash || latest.hash !== built.hash || check?.outputs_hash !== checkHash) {
        t1 = { ...t1, rows: [], final: unknownVerdict(['source, ledger or check changed during judge; rerun required'], true) };
      } else if (t1.rows.length) {
        const verified = verifyT1Rows(t1.rows, latest.packet, opts.replay?.required_cites || []);
        const indexed = verifyT1Index(root, t1.rows, latest.packet);
        if (!verified.ok || !indexed.ok) t1 = { ...t1, rows: [], failed_cites: [...verified.failed_cites, ...indexed.failed_cites],
          final: unknownVerdict(['failed cite during final source verification']) };
      }
    }
    const timings = { ...record.timings, full_ms: Date.now() - opts.fullStarted };
    const addendum = { type: 'addendum', phase: 'T1', verdict_id: record.id, at: new Date().toISOString(),
      t1, final: t1.final, candidates: t1.final.candidates, timings, checked_inputs_hash: current.hash,
      seats: { typer: Array.isArray(record.seats) ? record.seats : record.seats?.typer || [], judge: t1.seats.judge } };
    appendRecord(stateDirFor(root), path.join(stateDirFor(root), 'VERDICTS.md'), addendum, opts.lockOpts, token);
    atomicWriteFile(path.join(stateDirFor(root), 'ledger.json'), JSON.stringify(buildLedger(current.pack, loadLedgerEntries(root)), null, 2) + '\n');
    session.manifest = manifest;
    appendReceipt(stateDirFor(root), session, { transition: 'check', phase: 'T1', at: addendum.at,
      verdict_id: record.id, inputs_hash: record.line_hash, outputs_hash: sha256Text(JSON.stringify(addendum)),
      manifest_hash: manifestHash(manifest), checked_inputs_hash: current.hash, seat: t1.seats });
    const joined = verdictData(root).verdicts.find((r) => r.id === record.id);
    const report = t1TimingReport([joined], { live: opts.live, tolerance: opts.tolerance });
    if (opts.live) journalEvent(stateDirFor(root), { event: 't1-live', verdict_id: record.id,
      timing: report, timings, judge: t1.seats.judge, packet_hash: built.hash });
    return { ok: true, status: t1.final.verdict === VERDICTS.pending ? 3 : t1.final.verdict === VERDICTS.unknown ? 5 : 0,
      record: joined, lines: renderT1(joined), timing: report };
  });
}

export async function rerunPendingIdeas(root, opts = {}) {
  const rows = verdictData(root).verdicts.filter((r) => r.t0 && !r.inbox
    && [VERDICTS.pending, VERDICTS.unknown, 'PENDING'].includes((r.final || r.t0).verdict));
  const out = [];
  for (const row of rows) out.push(await requestIdea(root, { ...opts, text: row.raw_line, unit: row.unit,
    scope: row.scope_override, file: undefined, sources: row.source_selections || [],
    replay: typeof opts.replay === 'object' && opts.replay.input?.raw_line !== row.raw_line ? null : opts.replay,
    typedReplay: row.judge_required && !row.typing_fallback ? row.extraction : undefined,
    typedSeats: Array.isArray(row.seats) ? row.seats : row.seats?.typer || [], rerun_id: row.id, rerunPending: false }));
  return out;
}

function writeIdea(root, opts) {
  try {
    containedFile(root, 'chekhov/session.json');
    return withLock(stateDirFor(root), opts.lockOpts, (token) => {
      const session = ideaSession(root), manifest = verifyIdeaManifest(root, session);
      for (const name of ['start', 'intake', 'check']) if (!lastReceipt(session, name)) return refuse(`no receipt, no step: missing receipt '${name}' before 'write'`);
      const data = verdictData(root), record = data.verdicts.find((r) => r.id === opts.verdict_id);
      const exact = data.records.findLast((r) => r.id === opts.verdict_id || r.type === 'addendum' && r.verdict_id === opts.verdict_id);
      const check = session.receipts.findLast((r) => r.transition === 'check' && r.verdict_id === opts.verdict_id && !r.invalidated);
      if (!record || !exact || !check || typeof opts.text !== 'string' || record.raw_line !== opts.text
        || record.line_hash !== sha256Text(opts.text) || check.inputs_hash !== record.line_hash
        || check.outputs_hash !== sha256Text(JSON.stringify(exact))) return refuse('no receipt, no write: exact verdict-log receipt required');
      const verdict = record.final || record.t0;
      if ([VERDICTS.unknown, VERDICTS.pending, 'PENDING'].includes(verdict.verdict)) return refuse('no verdict: line held in the log; nothing written');
      const inputs = ideaInputs(root, record.id);
      if (record.checked_inputs_hash !== inputs.hash) return refuse('stale verdict: source or ledger changed; check this line again');
      if (record.judge_required) {
        if (!record.t1?.packet_hash) return refuse('no receipt, no write: verified T1 evidence required');
        const current = buildT1Packet(root, inputs, record, record.source_selections);
        if (current.hash !== record.t1.packet_hash || !verifyT1Rows(record.t1.rows, current.packet).ok
          || !verifyT1Index(root, record.t1.rows, current.packet).ok) return refuse('stale or failed T1 citation: check this line again');
      }
      if (verdict.verdict === VERDICTS.inconsistent) {
        const askId = `decision.${record.id}`;
        if (!data.entries.some((e) => e.tuple.id === askId)) {
          const ask = { schema: 1, kind: 'decision', id: askId, lock: 'candidate', value: null,
            interval: { scope: 'unspecified' }, question: `Review inconsistent idea: ${record.raw_line}`,
            receipt: { span: record.raw_line, heading_path: [record.id], line_hint: 1, date: new Date().toISOString(),
              source_file: 'chekhov/VERDICTS.md', verdict_id: record.id, line_hash: record.line_hash, prompt_hash: IDEA_PROMPT_HASH } };
          appendRecord(stateDirFor(root), path.join(stateDirFor(root), 'VERDICTS.md'), {
            type: 'decision-ask', verdict_id: record.id, id: `ask-${record.id}`, raw_line: record.raw_line,
            rung: 'provisional', candidates: [ask], at: new Date().toISOString(),
          }, opts.lockOpts, token);
          atomicWriteFile(path.join(stateDirFor(root), 'ledger.json'), JSON.stringify(buildLedger(inputs.pack, loadLedgerEntries(root)), null, 2) + '\n');
        }
        const receipt = { transition: 'write', at: new Date().toISOString(), route: 'decision-ask', verdict_id: record.id,
          inputs_hash: record.line_hash, outputs_hash: sha256Text(askId), manifest_hash: manifestHash(manifest) };
        appendReceipt(stateDirFor(root), session, receipt);
        return { ok: true, route: 'decision-ask', rung: 'provisional', id: askId, receipt };
      }
      if (verdict.scope_dependent || verdict.requires_lock_event) return refuse('conditional verdict: resolve scope or the required lock event before writing');
      if (verdict.ripple.some((r) => r.action !== 'add as candidate')) return refuse('ripple must be resolved and the line checked again before writing');
      const lint = t0ForRoot(root);
      if (lint.gate.refused) return { ...refuse(lint.gate.lines.join('\n')), gate: lint.gate };
      if (!lint.criterion1) return refuse('Outline refused: criterion 1 is not green on prose; see LEDGER-REPORT.md.');
      if (lint.doctrine.hits.length) return refuse('Outline refused: unallowed doctrine vocabulary.');
      const target = containedFile(root, opts.target), rel = path.relative(root, target).replace(/\\/g, '/');
      if (rel.startsWith('chekhov/') || !/(?:bible|outline|beat[\s_-]?sheet)[^/]*\.md$/i.test(path.basename(target))) return refuse('write target must be bible, outline or beat-sheet markdown');
      if (session.receipts.some((r) => r.transition === 'write' && !r.invalidated && r.verdict_id === record.id && r.target === rel)) return refuse('this verdict already wrote this target');
      verifyIdeaManifest(root, session);
      if (ideaInputs(root, record.id).hash !== inputs.hash) return refuse('stale verdict immediately before write');
      const previous = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : '';
      const text = previous + (previous && !previous.endsWith('\n') ? '\n' : '') + opts.text;
      atomicWriteFile(target, text);
      session.manifest = computeManifest(root);
      const receipt = { transition: 'write', at: new Date().toISOString(), verdict_id: record.id, target: rel,
        inputs_hash: record.line_hash, outputs_hash: sha256Text(text), manifest_hash: manifestHash(session.manifest) };
      appendReceipt(stateDirFor(root), session, receipt);
      return { ok: true, route: 'text', target: rel, receipt };
    });
  } catch (e) { return refuse(e.message); }
}

export async function invokeSession(root, opts = {}) {
  try { containedFile(root, 'chekhov/session.json'); ideaSession(root); verdictData(root); }
  catch (e) { return { ...ideaFailure('backing-store-unreadable', e.message), halted: true }; }
  const result = startSession(root, opts);
  if (!result.ok) return result;
  try {
    result.ideas = await rerunPendingIdeas(root, opts);
    const inbox = path.join(stateDirFor(root), 'inbox');
    if (fs.existsSync(inbox)) for (const entry of fs.readdirSync(inbox, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (!entry.isFile() || !/\.(txt|md)$/i.test(entry.name)) continue;
      const relative = `chekhov/inbox/${entry.name}`, file = containedFile(root, relative);
      if (fs.statSync(file).size > IDEA_LIMIT) { result.ideas.push(ideaFailure('dependency-returns-garbage', `Oversize drop: ${entry.name}`)); continue; }
      const hash = sha256Text(fs.readFileSync(file, 'utf8'));
      if (verdictData(root).verdicts.some((r) => r.source?.file === relative && r.source.hash === hash)) continue;
      result.ideas.push(await requestIdea(root, { ...opts, file: relative, rerunPending: false }));
    }
    result.lines.push(...result.ideas.flatMap((r) => r.lines));
  } catch (e) { result.ok = false; result.lines.push(`idea: backing-store-unreadable (${e.message})`); }
  return result;
}

/** Anchor's manifest supplies JSON on stdin and expects the existing text
 * surface. This adapter owns no state machine: it enters and ends this engine.
 * Session identities come from the caller; times are observed here, never input.
 */
export async function invokeAnchorSession(payload, { roots = {} } = {}) {
  const request = validateAnchorRequest(payload, roots), root = request.root;
  const existing = callAnchorAdapter({ action: 'read', folder: root,
    project_id: payload.project_id, session_id: payload.session_id }, request.anchor);
  if (!existing.ok) return { ok: false, exitCode: 5, lines: [`anchor: not wired (${existing.error})`] };
  if (existing.runs.some((r) => r.session_id === payload.session_id)) {
    return { ok: false, exitCode: 2, lines: ['Anchor session_id already recorded; supply the next actual session identity.'] };
  }
  const opts = { project: payload.project, unit: payload.unit, live: payload.live === true,
    replay: payload.replay, sourcesFile: payload.sources_file };
  if (payload.unit && payload.unit !== request.config.active_unit) {
    const prepared = prepareSession(root, opts);
    if (!prepared.ok) return { ...prepared, exitCode: 2, lines: [prepared.reason] };
  }
  let started = new Date().toISOString(), ended;
  let result, journal;
  const lines = [];
  try {
    result = await invokeSession(root, opts);
    started = result.session?.receipts.findLast((r) => r.transition === 'start')?.at || started;
    lines.push(...result.lines);
    if (result.ok && payload.text != null) {
      const intake = await requestTransition(root, 'intake', { ...opts, text: payload.text });
      lines.push(...intake.lines);
      if (!intake.ok) result.ok = false;
    }
  } catch (e) {
    result = { ok: false, halted: false };
    lines.push(`session failed: ${e.message}`);
  } finally {
    try {
      const endResult = endSession(root, opts);
      ended = endResult.session?.receipts.findLast((r) => r.transition === 'end')?.at || new Date().toISOString();
      journal = endResult.journal;
      lines.push(...endResult.lines);
      result = { ...endResult, ok: Boolean(result?.ok && endResult.ok), halted: Boolean(result?.halted || endResult.halted) };
    } catch (e) {
      result = { ok: false, halted: Boolean(result?.halted) };
      ended = new Date().toISOString();
      lines.push(`session end failed: ${e.message}`);
    }
    try { await closeIdeaJudge(root); }
    catch (e) { result.ok = false; lines.push(`judge close failed: ${e.message}`); }
  }
  const integration = withLock(stateDirFor(root), undefined, () =>
    publishAnchorSession(request, { started, ended, result, lines, journal }));
  const heartbeatFailed = result.heartbeat?.ok === false;
  if (!integration.ok) lines.push(`anchor: not wired (${integration.error})`);
  // HALT stays nonzero. Anchor's text runner records host-nonzero-exit; the
  // commission reader independently exposes the stopped session and its wait.
  return { ...result, integration, lines,
    exitCode: !integration.ok || heartbeatFailed ? 5 : result.halted ? 4 : result.ok ? 0 : 1 };
}

export async function sessionPrompt(root, opts = {}) {
  if (!isRealTty()) return endSession(root, opts);
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
  const print = opts.print || ((line) => process.stdout.write(line + '\n'));
  print('Paste an idea to check; q ends the session.');
  try {
    const input = terminal[Symbol.asyncIterator]();
    for await (const text of input) {
      if (text === 'q') break;
      const currentSession = ideaSession(root);
      if (currentSession.halt?.open) {
        if (text !== 'confirm') {
          print(`Unmanaged edits: ${(currentSession.halt.files || []).join(', ')}. Inspect the changed files first. Type confirm only to claim these edits as yours, or q to leave the HALT open.`);
          continue;
        }
        const confirmed = confirmReconciliation(root);
        if (!confirmed.ok) print(confirmed.reason);
        else for (const line of startSession(root, opts).lines) print(line);
        continue;
      }
      if (text === 'u') {
        print('Name the story, novella, book or essay to work on:');
        const answer = await input.next();
        if (answer.done) break;
        const changed = setSessionUnit(root, answer.value, opts);
        if (changed.ok) {
          opts = { ...opts, unit: changed.unit };
          for (const line of startSession(root, opts).lines) print(line);
        } else print(changed.reason);
        continue;
      }
      if (text === 'c') {
        const committed = await requestCommit(root, { live: opts.live === true });
        for (const line of committed.lines || []) print(line);
        continue;
      }
      if (text === 'm' || text === 'r') { print('Use the documented migration/render operator path; this key has no attached transition yet.'); continue; }
      const result = ['l', 's'].includes(text) ? requestInspection(root, text === 'l' ? 'lint' : 'structure')
        : await requestTransition(root, 'intake', { ...opts, text });
      for (const line of result.lines || [result.reason]) if (line) print(line);
    }
  } finally {
    terminal.close();
    await closeIdeaJudge(root);
    const ended = endSession(root, opts);
    for (const line of ended.lines || []) print(line);
  }
}

/**
 * Close a reconciliation HALT — John claims the edit as his own (confirm key)
 * or reverts it. TTY-ONLY: the check reads the real process TTY so a seat in
 * a pipe can never launder a write. `confirmAll` covers a batch.
 */
export function confirmReconciliation(root, opts = {}) {
  const stateDir = stateDirFor(root, opts.stateDir);
  const session = opts.session || loadSession(stateDir);
  if (!session.halt || !session.halt.open) {
    return refuse('no reconciliation HALT is open');
  }
  if (!isRealTty()) {
    return refuse('reconciliation confirm is TTY-only — John presses the confirm key at the session prompt; a seat can never launder a write');
  }
  session.halt.open = false;
  session.halt.closed_at = opts.now || new Date().toISOString();
  session.halt.resolution = opts.revert ? 'reverted' : 'confirmed-by-john';
  session.manifest = computeManifest(root);
  saveSession(stateDir, session);
  return { ok: true, session };
}
