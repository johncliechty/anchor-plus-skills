/** W6: one serial data session; validate a batch, then insert candidates only. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createDataSession } from '../../../../trio/drivers/index.mjs';
import { loadProjectPack, validateClaim } from './pack.mjs';
import { markdownRows, projectDocuments } from './prose.mjs';
import { readSidecar, parseSidecarText, serializeSidecar, validateTuple } from './tuples.mjs';
import { loadLedgerEntries, readCommitState, createLedgerSourceSelector } from './index.mjs';
import { atomicWriteFile, withLock, stateDirFor, loadSession, appendReceipt } from './store.mjs';
import { computeManifest, diffManifests, manifestHash, sha256Text, classifyRel, CLASS_ENGINE } from './manifest.mjs';
import { failureRow } from './failure-states.mjs';

export const EXTRACT_PROMPT = fs.readFileSync(new URL('./prompts/extract.v1.md', import.meta.url), 'utf8');
export const EXTRACT_PROMPT_HASH = sha256Text(EXTRACT_PROMPT);
export const EXTRACT_SCHEMA = Object.freeze({ type: 'object', required: ['tuples'], additionalProperties: false,
  properties: { tuples: { type: 'array', items: { type: 'string' } } } });
const protectedFields = ['allow_terms', 'accepted_by', 'accepted_on', 'acceptance_receipt', 'authored_by', 'edited_by', 'governs', 'orders', 'authorial_rename', 'expected'];
export const commitStatePath = (root) => path.join(stateDirFor(root), 'commit.json');

export { readCommitState } from './index.mjs';

export function scenesOf(doc) {
  const lines = doc.text.split('\n');
  const headings = markdownRows(doc.text).filter((r) => r.heading);
  const starts = [...new Set([1, ...headings.map((r) => r.line)])];
  return starts.map((line, i) => {
    const text = lines.slice(line - 1, starts[i + 1] ? starts[i + 1] - 1 : lines.length).join('\n');
    const heading_path = headings.find((r) => r.line === line)?.heading_path || [];
    return { file: doc.file, heading_path, line, text, key: `${doc.file}:${line}`, hash: sha256Text(text) };
  }).filter((s) => s.text.trim());
}

/** Validate the unmodified proposal, then bind its exact quote to this scene. */
export function prepareCandidate(proposal, scene, pack, seatReceipt, date) {
  if (proposal?.lock === 'locked') throw new Error('locked output rejected');
  for (const key of protectedFields) if (Object.hasOwn(proposal || {}, key)) throw new Error(`${key} output rejected`);
  validateTuple(proposal);
  if (proposal.value && Object.hasOwn(proposal.value, 'predicate')) {
    const claim = validateClaim(pack, proposal.value);
    if (!claim.ok) throw new Error(`${claim.refusal}: ${claim.predicate}`);
  }
  const span = proposal.receipt.span;
  if (typeof span !== 'string' || !span.trim() || !scene.text.includes(span)) throw new Error('receipt span is not in this scene');
  const localLine = scene.text.slice(0, scene.text.indexOf(span)).split('\n').length - 1;
  return { ...proposal, lock: 'candidate', receipt: { span, heading_path: scene.heading_path,
    line_hint: scene.line + localLine, date, source_file: scene.file, prompt_hash: EXTRACT_PROMPT_HASH,
    extraction: seatReceipt } };
}

/** Insert bytes inside a JSON/YAML list; never reserialize existing tuples. */
export function insertSidecarText(raw, existing, additions) {
  if (!additions.length) return raw;
  if (!raw) return serializeSidecar({ schema: 1, tuples: additions });
  const flow = /(?:"tuples"|\btuples)\s*:\s*\[/.exec(raw);
  if (flow) {
    const start = flow.index + flow[0].length - 1;
    let depth = 0, quoted = false, escaped = false;
    for (let i = start; i < raw.length; i++) {
      const c = raw[i];
      if (quoted) { if (escaped) escaped = false; else if (c === '\\') escaped = true; else if (c === '"') quoted = false; continue; }
      if (c === '"') { quoted = true; continue; }
      if (c === '[') depth++;
      if (c === ']' && --depth === 0) {
        const insert = `${existing.length ? ',' : ''}\n${additions.map((t) => JSON.stringify(t)).join(',\n')}\n`;
        return raw.slice(0, i) + insert + raw.slice(i);
      }
    }
    throw new Error('unreadable tuples array');
  }
  const block = /^tuples:\s*(?:#.*)?\r?$/m.exec(raw);
  if (!block) throw new Error('unsupported sidecar list layout');
  const from = block.index + block[0].length;
  const tail = raw.slice(from);
  const next = /\n(?=[A-Za-z_][\w-]*:)/.exec(tail);
  const at = next ? from + next.index : raw.length;
  const insert = '\n' + additions.map((t) => '  -\n' + Object.entries(t).map(([k, v]) => `    ${k}: ${JSON.stringify(v)}`).join('\n')).join('\n') + '\n';
  return raw.slice(0, at) + insert + raw.slice(at);
}

function failure(error, row) {
  const f = failureRow('commit', row);
  return { ok: false, status: f.status, row, candidates: [], rejected: [], lines: [f.text, error.message] };
}

export async function commitProject(root, opts = {}) {
  if (!opts.replay && !opts.live) return failure(new Error('Use --replay <fixture>; --live is by hand only.'), 'dependency-missing');
  if (opts.replay && opts.live) return failure(new Error('Choose --replay or --live.'), 'dependency-returns-garbage');
  if (opts.live && !(process.stdin.isTTY === true && process.stdout.isTTY === true)) return failure(new Error('--live requires John at a terminal.'), 'dependency-missing');
  let stage = 'backing-store-unreadable', scratch, session;
  try {
    const startingSession = loadSession(stateDirFor(root));
    if (startingSession.halt?.open) throw new Error('reconciliation HALT open');
    if (startingSession.manifest && diffManifests(startingSession.manifest, computeManifest(root)).unmanaged_engine.length) throw new Error('Unmanaged engine edit; open the session to reconcile before commit.');
    stage = 'dependency-missing';
    const pack = loadProjectPack(root);
    stage = 'backing-store-unreadable';
    const state = readCommitState(root);
    const sourceSelected = createLedgerSourceSelector(root, state);
    const docs = [...projectDocuments(root), ...(opts.scope ? projectDocuments(root, { manuscripts: true }) : [])]
      .filter((doc) => !opts.files || opts.files.includes(doc.file))
      .filter((doc) => sourceSelected(doc.file) || opts.files?.includes(doc.file) || opts.scope === doc.file);
    // Registered plain writing stays discoverable after its queue clears.
    // Engine-owned imported copies remain index evidence; registration alone
    // must not recast a copy excluded by projectDocuments as editable prose.
    const implicit = (state.source_files || []).filter(file => classifyRel(file) !== CLASS_ENGINE);
    const explicit = [...(opts.files || implicit), ...(typeof opts.scope === 'string' && /\.md$/i.test(opts.scope) ? [opts.scope] : [])];
    for (const file of new Set(explicit)) {
      if (docs.some(doc => doc.file === file)) continue;
      if (typeof file !== 'string' || !/\.md$/i.test(file) || path.isAbsolute(file) || path.win32.isAbsolute(file)
        || file.includes(':') || file.split(/[\\/]/).some(part => !part || part.startsWith('.') || ['chekhov','skills','node_modules'].includes(part))
        || classifyRel(file) === CLASS_ENGINE) throw new Error('Explicit capture requires a contained writing file');
      const base = fs.realpathSync(root), target = path.resolve(base, file);
      let at = base;
      for (const part of path.relative(base, target).split(path.sep)) {
        at = path.join(at, part);
        if (fs.lstatSync(at).isSymbolicLink()) throw new Error('Linked writing file refused');
      }
      if (!fs.statSync(target).isFile()) throw new Error(`Writing file missing: ${file}`);
      docs.push({ file, kind: 'manuscript', entry: {}, text: fs.readFileSync(target, 'utf8') });
    }
    for (const doc of docs) {
      if (!sourceSelected(doc.file) && fs.existsSync(path.join(root, doc.file) + '.ledger.yaml')) {
        throw new Error(`Excluded legacy sidecar: ${doc.file}; review its source selection before capturing it, or use a new revision file.`);
      }
    }
    const scenes = docs.flatMap(scenesOf).filter((s) => !opts.scope || s.file === opts.scope || s.heading_path.includes(opts.scope));
    const waiting = scenes.filter((s) => state.completed[s.key] !== s.hash);
    const cap = opts.batchSize ?? 20;
    if (!Number.isSafeInteger(cap) || cap < 1) throw new Error('batchSize must be positive');
    const batch = waiting.slice(0, cap);
    const date = new Date().toISOString();
    let replay;
    if (opts.replay) {
      stage = 'dependency-missing';
      const raw = fs.readFileSync(opts.replay, 'utf8');
      stage = 'dependency-returns-garbage';
      replay = JSON.parse(raw);
      if (replay.schema !== 1 || !Array.isArray(replay.scenes)) throw new Error('replay requires schema: 1 and scenes');
    }
    const proposed = [], rejected = [], recordedScenes = [];
    if (opts.recordFile && !opts.live) throw new Error('A real recording requires --live at John’s terminal.');
    const recording = opts.recordFile && fs.existsSync(opts.recordFile)
      ? JSON.parse(fs.readFileSync(opts.recordFile, 'utf8')) : { schema: 1, kind: opts.recordKind || 'real-replay', scenes: [], batches: [] };
    if (batch.length && opts.live) {
      stage = 'dependency-missing';
      scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'chekhov-extract-'));
      session = await (opts.createSession || createDataSession)({ role: 'extractor', cwd: scratch,
        env: { ...process.env, CRUCIBLE_AGENT_LIVE: '1' }, maxTurns: batch.length, turnTimeoutMs: 600000 });
    }
    try {
      for (const scene of batch) {
        stage = 'dependency-returns-garbage';
        let value, receipt;
        if (replay) {
          const matchesScene = (r) => r.file === scene.file && JSON.stringify(r.heading_path) === JSON.stringify(scene.heading_path);
          const rows = replay.scenes.filter((r) => matchesScene(r) && (!Object.hasOwn(r, 'line') || r.line === scene.line));
          const [row] = rows;
          if (!row) throw new Error(`Replay missing scene: ${scene.key} (${scene.heading_path.join(' > ')})`);
          // The binding must be unique on both sides, including scenes outside this batch.
          const boundScenes = scenes.filter((s) => matchesScene(s) && (!Object.hasOwn(row, 'line') || s.line === row.line));
          if (rows.length > 1 || boundScenes.length > 1) throw new Error(`Replay ambiguous scene: ${scene.key} (${scene.heading_path.join(' > ')})`);
          value = { tuples: row.tuples };
          receipt = { mode: 'replay', served_model: null, model_attested: false,
            tool_isolation_verified: null, runtime_policy_status: 'requested-unattested', recorded: row.receipt || null };
        } else {
          stage = 'dependency-slow-or-killed';
          ({ value, receipt } = await session.request({
            prompt: `${EXTRACT_PROMPT}\nCATALOG_JSON: ${JSON.stringify(pack.predicate_catalog)}\nSCENE_DATA_JSON: ${JSON.stringify({ file: scene.file, heading_path: scene.heading_path, text: scene.text })}`,
            schema: EXTRACT_SCHEMA,
          }));
        }
        stage = 'dependency-returns-garbage';
        if (!value || !Array.isArray(value.tuples)) throw new Error(`Malformed scene response: ${scene.key}`);
        // Structured Outputs requires closed objects. Tuple values are pack data,
        // so only the live wire uses JSON strings; replay and stored tuples stay objects.
        if (!replay) value = { tuples: value.tuples.map((encoded) => {
          if (typeof encoded !== 'string') throw new Error(`Malformed tuple encoding: ${scene.key}`);
          const tuple = JSON.parse(encoded);
          if (!tuple || typeof tuple !== 'object' || Array.isArray(tuple)) throw new Error(`Encoded tuple is not an object: ${scene.key}`);
          return tuple;
        }) };
        recordedScenes.push({ file: scene.file, heading_path: scene.heading_path, line: scene.line,
          source_hash: scene.hash, tuples: value.tuples, receipt });
        for (const tuple of value.tuples) {
          try {
            if (opts.preDecision && tuple?.kind === 'decision') throw new Error('first recording precedes all decision entries; decision proposal rejected');
            proposed.push({ file: scene.file, tuple: prepareCandidate(tuple, scene, pack, receipt, date) });
          }
          catch (e) { rejected.push({ id: tuple?.id || '(no id)', scene: scene.key, reason: e.message }); }
        }
      }
    } finally {
      if (session) { const held = session; session = null; await held.close(); }
    }
    stage = 'backing-store-unreadable';
    const candidates = [];
    withLock(stateDirFor(root), opts.lockOpts, () => {
      const current = readCommitState(root);
      if (JSON.stringify(current) !== JSON.stringify(state)) throw new Error('commit state changed during extraction; rerun');
      const latestSession = loadSession(stateDirFor(root));
      if (latestSession.halt?.open) throw new Error('reconciliation HALT opened during extraction');
      if (latestSession.manifest && diffManifests(latestSession.manifest, computeManifest(root)).unmanaged_engine.length) throw new Error('Unmanaged engine edit during extraction; reconcile before commit.');
      for (const doc of docs) if (fs.readFileSync(path.join(root, doc.file), 'utf8') !== doc.text) throw new Error(`prose changed during extraction: ${doc.file}`);
      const currentSourceSelected = createLedgerSourceSelector(root, current);
      for (const doc of docs) if (!currentSourceSelected(doc.file) && fs.existsSync(path.join(root, doc.file) + '.ledger.yaml')) {
        throw new Error(`Excluded legacy sidecar appeared during capture: ${doc.file}`);
      }
      const existingEntries = loadLedgerEntries(root);
      if (opts.preDecision && existingEntries.some((e) => e.tuple.kind === 'decision')) throw new Error('A decision entry appeared during first recording; preserve the evidence for review.');
      const ids = new Set(existingEntries.map((e) => e.tuple.id));
      const groups = new Map();
      for (const row of proposed) {
        if (ids.has(row.tuple.id)) { rejected.push({ id: row.tuple.id, reason: 'existing or duplicate id; insertion refused' }); continue; }
        ids.add(row.tuple.id);
        if (!groups.has(row.file)) groups.set(row.file, []);
        groups.get(row.file).push(row.tuple);
        candidates.push({ id: row.tuple.id, sidecar: `${row.file}.ledger.yaml`, receipt: row.tuple.receipt,
          ...(row.tuple.interval.scope ? { scope: row.tuple.interval.scope } : {}) });
      }
      const writes = [...groups].map(([file, tuples]) => {
        const prose = path.join(root, file), sidecar = `${prose}.ledger.yaml`;
        const old = readSidecar(prose);
        const text = insertSidecarText(fs.existsSync(sidecar) ? fs.readFileSync(sidecar, 'utf8') : '', old.tuples, tuples);
        parseSidecarText(text);
        return [sidecar, text];
      });
      const capturedFiles = new Set(batch.map(scene => scene.file));
      // A candidate-free file qualifies only when every processed response was
      // truly empty; rejected proposals must not turn into an empty sidecar.
      for (const scene of recordedScenes) {
        if (scene.tuples.length > 0 && !groups.has(scene.file)) capturedFiles.delete(scene.file);
      }
      // A valid empty capture still admits the source for future edits. Its
      // empty sidecar satisfies the existing registry without inventing a claim.
      for (const file of capturedFiles) {
        const sidecar = path.join(root, file) + '.ledger.yaml';
        if (!groups.has(file) && !fs.existsSync(sidecar)) {
          const text = serializeSidecar({ schema: 1, tuples: [] });
          parseSidecarText(text);
          writes.push([sidecar, text]);
        }
      }
      // All proposals and existing sidecars have passed before the first write.
      // Persist the response before candidate/state writes, so interrupted recording
      // never silently completes a scene without its replay evidence.
      if (opts.recordFile) {
        recording.scenes = [...recording.scenes.filter((r) => !recordedScenes.some((s) => s.file === r.file && s.line === r.line)), ...recordedScenes];
        recording.batches.push({ at: date, processed: batch.length, backlog: waiting.length - batch.length,
          candidate_ids: candidates.map((r) => r.id), rejected });
        recording.prompt_hash = EXTRACT_PROMPT_HASH;
        atomicWriteFile(opts.recordFile, JSON.stringify(recording, null, 2) + '\n');
      }
      for (const [file, text] of writes) atomicWriteFile(file, text);
      for (const scene of batch) state.completed[scene.key] = scene.hash;
      const candidateIdsBySidecar = new Map();
      const prior = state.candidates.filter((r) => {
        if (!candidateIdsBySidecar.has(r.sidecar)) {
          const tuples = readSidecar(path.join(root, r.sidecar.slice(0, -'.ledger.yaml'.length))).tuples;
          candidateIdsBySidecar.set(r.sidecar, new Set(tuples.filter(t => t.lock === 'candidate').map(t => t.id)));
        }
        return candidateIdsBySidecar.get(r.sidecar).has(r.id);
      });
      state.candidates = [...prior, ...candidates];
      state.backlog = waiting.length - batch.length;
      state.last_commit = candidates.map((r) => r.id);
      state.source_files = [...new Set([...(state.source_files || []), ...capturedFiles])].sort();
      atomicWriteFile(commitStatePath(root), JSON.stringify(state, null, 2) + '\n');
      const journal = loadSession(stateDirFor(root));
      journal.manifest = computeManifest(root);
      appendReceipt(stateDirFor(root), journal, { transition: 'commit', at: date,
        inputs_hash: sha256Text(JSON.stringify(batch.map((s) => s.hash))), outputs_hash: sha256Text(JSON.stringify(candidates)),
        manifest_hash: manifestHash(journal.manifest), prompt_hash: EXTRACT_PROMPT_HASH,
        scenes: batch.map(({ file, heading_path }) => ({ file, heading_path })), backlog: state.backlog });
    });
    const lines = [`Commit: ${batch.length}/${waiting.length} pending scenes processed; backlog=${state.backlog} scenes.`,
      ...rejected.map((r) => `Rejected ${r.id}: ${r.reason}`), 'Candidates:',
      ...candidates.map((r) => `- ${r.id}${r.scope ? ` [${r.scope === 'unspecified' ? 'timing unspecified — pending' : 'project-wide'}]` : ''}: "${r.receipt.span}" (${r.sidecar}; ${r.receipt.heading_path.join(' > ')})`)];
    if (!candidates.length) lines.push('(none)');
    return { ok: true, status: 0, candidates, rejected, backlog: state.backlog, processed: batch.length, lines };
  } catch (e) {
    if (['schema_nonconforming', 'malformed_jsonl', 'invalid_schema', 'config_unreadable', 'pack_unreadable'].includes(e.code)) stage = 'dependency-returns-garbage';
    return failure(e, stage);
  }
  finally {
    if (session) await session.close();
    if (scratch) fs.rmSync(scratch, { recursive: true, force: true });
  }
}
