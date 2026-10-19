/** John's contextual, seat-free walk. No author action is reachable off-TTY. */
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { isDeepStrictEqual } from 'node:util';
import { buildLedger, loadLedgerEntries, verdictData, readCommitState } from './index.mjs';
import { loadProjectPack, validateClaim } from './pack.mjs';
import { acceptanceHash, hasAcceptance, readSidecar, resolveReceipt, serializeSidecar, validateTuple } from './tuples.mjs';
import { rippleFor } from './asks.brightheart.mjs';
import { markdownRows } from './prose.mjs';
import { atomicWriteFile, withLock, stateDirFor, loadSession, appendReceipt, appendRecord } from './store.mjs';
import { computeManifest, diffManifests, manifestHash, sha256Text } from './manifest.mjs';
import { failureRow } from './failure-states.mjs';
import { readFirstAccept, recordFirstDisposition, swapFirstSelection } from './first-accept.mjs';

const realTty = () => process.stdin.isTTY === true && process.stdout.isTTY === true;
const keys = 'a accept | r reject | l leave | s swap | ? explain | e edit | n new | d defer | q quit';
const relDecision = 'chekhov/DECISIONS.md.ledger.yaml';
const pending = (entry) => entry.tuple.lock !== 'locked' || !hasAcceptance(entry.tuple);

export function acceptanceQueue(root, { list, project } = {}) {
  const entries = loadLedgerEntries(root);
  const byId = new Map(entries.map((e) => [e.tuple.id, e]));
  const commit = readCommitState(root);
  const seen = new Set();
  const queue = [];
  const add = (entry, source) => {
    if (!entry || seen.has(entry.tuple.id)) return;
    const drift = entry.prose !== null && resolveReceipt(entry.prose, entry.tuple.receipt).status === 'drift';
    if (!pending(entry) && !drift) return;
    seen.add(entry.tuple.id); queue.push({ ...entry, queue: source });
  };
  for (const ref of commit.candidates) add(byId.get(ref.id), 'commit');
  // Recover pending sidecar insertions after a stopped run, including minted
  // annotations; decisions retain their distinct third queue.
  for (const e of entries) if (!e.verdict_id && e.tuple.kind !== 'decision') add(e, 'commit');
  for (const e of verdictData(root).entries) add(e, 'idea');
  for (const e of entries) if (e.tuple.kind === 'decision') add(e, 'decision');
  let selected = queue;
  let named = null;
  if (list) {
    if (list === 'first-accept') named = readFirstAccept(root, entries, { project });
    const raw = named ? null : fs.readFileSync(list, 'utf8').trim();
    const ids = named ? named.ids : raw.startsWith('[') ? JSON.parse(raw) : raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (!Array.isArray(ids) || ids.some((id) => typeof id !== 'string')) throw new Error('--list requires one id per line or a JSON string array');
    if (new Set(ids).size !== ids.length || ids.some((id) => !byId.has(id))) throw new Error('--list contains duplicate or unknown project IDs');
    const wanted = new Set(ids);
    selected = queue.filter((e) => wanted.has(e.tuple.id));
  }
  return { entries, queue: selected, waiting: queue.length - selected.length, total: queue.length, named };
}

export function renderContext(entry, ledger, records, full = false) {
  const t = entry.tuple;
  const closure = rippleFor(ledger, [t.id]);
  const citing = records.flatMap((record, i) => {
    const text = JSON.stringify(record);
    return text.includes(t.id) ? [`VERDICTS.md:${i + 1} ${text}`] : [];
  });
  const resolution = entry.prose === null ? { status: 'unanchored' } : resolveReceipt(entry.prose, t.receipt);
  const recommendation = t.value == null ? 'Provide a value or defer: this decision has no answer yet.'
    : resolution.status === 'unanchored' ? 'Leave pending: the receipt has no current source match.'
      : resolution.status === 'drift' ? 'Review the proposed quote before accepting: the source has changed.'
        : 'Accept only if this is your intended value: the quoted source matches, but the choice is yours.';
  const lines = [
    ...(t.deferred ? [`Deferred ${t.deferred.date}: ${t.deferred.note}`] : []),
    `${entry.queue || 'new'}: ${t.id}`, `Heading: ${t.receipt.heading_path.join(' > ') || '(no heading)'}`,
    `Receipt: "${t.receipt.span}" (${entry.sidecar}; line ${t.receipt.line_hint})`,
    `Value: ${JSON.stringify(t.value)}; interval: ${JSON.stringify(t.interval)}`,
    `Governs: ${JSON.stringify(t.governs || [])}; allowed terms: ${JSON.stringify(t.allow_terms || [])}`,
    ...(t.question ? [`Question: ${t.question}`] : []),
    `Depends on: ${(ledger.tuples[t.id]?.depends_on || []).join(', ') || '(none)'}`,
    `cost_of_change=${closure.length}; dependent entries: ${closure.join(', ') || '(none)'}`,
  ];
  for (const id of closure) {
    const row = ledger.tuples[id];
    lines.push(`- ${id}: ${row?.lock || 'unresolved'}; cost_of_change=${row?.cost_of_change ?? 'unknown'}${full ? `; ${JSON.stringify(row?.value)}; receipt: "${row?.receipt?.span || ''}"` : ''}`);
  }
  lines.push(...(citing.length ? citing : ['Citing verdict lines: (none)']));
  if (resolution.status === 'drift') lines.push(`Proposed receipt: "${resolution.drift.proposed.span}" (line ${resolution.drift.proposed.line_hint})`);
  lines.push(`Recommendation: ${recommendation}`);
  return lines;
}

function cleanCandidate(tuple) {
  const out = { ...tuple, lock: 'candidate' };
  for (const key of ['accepted_by', 'accepted_on', 'acceptance_receipt', 'allow_terms']) delete out[key];
  return out;
}

function validateValue(tuple, pack) {
  validateTuple(tuple);
  if (tuple.value && typeof tuple.value === 'object' && Object.hasOwn(tuple.value, 'predicate')) {
    const r = validateClaim(pack, tuple.value);
    if (!r.ok) throw new Error(`${r.refusal}: ${r.predicate}`);
  }
}

function promote(tuple, entry, date) {
  if (tuple.value == null) throw new Error('Value is unset; use e or n to supply your answer.');
  if (entry && entry.prose == null) throw new Error('Source is missing; leave pending or author a new decision.');
  const out = { ...tuple, lock: 'locked', accepted_by: 'john', accepted_on: date };
  if (entry?.prose != null) {
    const resolution = resolveReceipt(entry.prose, tuple.receipt);
    if (resolution.status === 'unanchored') throw new Error('Receipt has no current source match; leave pending or author a new decision.');
    if (resolution.status === 'drift') {
      const proposed = resolution.drift.proposed;
      const heading = markdownRows(entry.prose).filter((r) => r.line <= proposed.line_hint).at(-1)?.heading_path || [];
      out.receipt = { ...tuple.receipt, ...proposed, heading_path: heading, reanchored_by: 'john', reanchored_on: date };
    }
  }
  delete out.deferred;
  // The fixture expectation and rename are in the SAME atomic sidecar answer.
  if (out.kind === 'alias' && out.authorial_rename === true) out.expected = 'authorial_rename';
  out.acceptance_receipt = { writer: 'accept', accepted_by: 'john', accepted_on: date, tuple_hash: acceptanceHash(out) };
  return out;
}

/** Save one answer while holding the root lock; reread before any mutation. */
function recordAnswer(root, entry, action, tuple, pack, named) {
  if (!realTty()) throw new Error('Human answers require a real terminal.');
  const dir = stateDirFor(root);
  return withLock(dir, undefined, (token) => {
    const priorSession = loadSession(dir);
    if (priorSession.halt?.open || (priorSession.manifest && diffManifests(priorSession.manifest, computeManifest(root)).unmanaged_engine.length)) throw new Error('Unmanaged engine edit; reconcile at the session prompt before answering.');
    const all = loadLedgerEntries(root);
    const current = all.find((e) => e.tuple.id === (entry?.tuple.id || tuple.id));
    if (entry && (!current || !isDeepStrictEqual(current.tuple, entry.tuple))) throw new Error('Row changed during the walk; reopen accept.');
    if (entry && current.prose !== entry.prose) throw new Error('Source changed during the walk; reopen accept to review the current quote.');
    if (!entry && current) throw new Error('That stable id already exists; use e on its pending row.');
    if (action === 'reject' && current && !pending(current)) throw new Error('Only a pending candidate can be rejected.');
    if (tuple) validateValue(tuple, pack);
    if (named) {
      const reread = readFirstAccept(root, all, { project: named.list.project });
      if (!isDeepStrictEqual(reread.list, named.list)) throw new Error('First-accept list changed during the walk.');
    }
    if (entry?.verdict_id) {
      const file = path.join(dir, 'VERDICTS.md');
      // The immutable candidate's outcome is an addendum in the SAME store.
      const record = { type: 'candidate-action', verdict_id: entry.verdict_id, candidate_id: entry.tuple.id,
        action, date: new Date().toISOString(), ...(tuple ? { tuple } : {}) };
      appendRecord(dir, file, record, undefined, token);
    } else {
      const sidecar = entry?.sidecar || relDecision;
      const prose = path.join(root, sidecar.slice(0, -'.ledger.yaml'.length));
      const doc = readSidecar(prose);
      const at = doc.tuples.findIndex((t) => t.id === (entry?.tuple.id || tuple.id));
      if (action === 'reject') doc.tuples.splice(at, 1);
      else if (at >= 0) doc.tuples[at] = tuple;
      else doc.tuples.push(tuple);
      atomicWriteFile(`${prose}.ledger.yaml`, serializeSidecar(doc));
    }
    const ledger = buildLedger(pack, loadLedgerEntries(root));
    atomicWriteFile(path.join(dir, 'ledger.json'), JSON.stringify(ledger, null, 2) + '\n');
    const session = loadSession(dir);
    session.manifest = computeManifest(root);
    appendReceipt(dir, session, { transition: 'accept', at: new Date().toISOString(), action,
      ...(named ? { first_accept_hash: named.list.rows.find((r) => (r.swap_id || r.id) === entry?.tuple.id)?.receipt_hash } : {}),
      id: entry?.tuple.id || tuple.id, inputs_hash: sha256Text(JSON.stringify(entry?.tuple || null)),
      outputs_hash: sha256Text(JSON.stringify(tuple)), manifest_hash: manifestHash(session.manifest) });
    recordFirstDisposition(root, named, entry?.tuple.id || tuple.id, action, tuple);
    return tuple;
  });
}

function decodeEdit(text, tuple) {
  let patch;
  try { patch = JSON.parse(text); } catch { return { value: text }; }
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return { value: patch };
  const fields = ['value', 'interval', 'governs', 'question', 'allow_terms', 'authorial_rename'];
  if (!Object.keys(patch).some((k) => fields.includes(k))) return { value: patch };
  for (const key of Object.keys(patch)) if (!fields.includes(key)) throw new Error(`Cannot edit ${key}; stable ids and acceptance fields are managed.`);
  if ('governs' in patch && (!Array.isArray(patch.governs) || patch.governs.some((x) => typeof x !== 'string'))) throw new Error('governs must be an id array');
  if ('allow_terms' in patch && (tuple.kind !== 'decision' || !Array.isArray(patch.allow_terms) || patch.allow_terms.some((x) => typeof x !== 'string'))) throw new Error('allow_terms requires a decision and a string array');
  return patch;
}

export async function acceptProject(root, opts = {}) {
  const lines = [], outcomes = [];
  const print = (text) => { lines.push(text); (opts.print || ((s) => process.stdout.write(s + '\n')))(text); };
  let terminal;
  try {
    const session = loadSession(stateDirFor(root));
    if (session.halt?.open || (session.manifest && diffManifests(session.manifest, computeManifest(root)).unmanaged_engine.length)) throw new Error('reconciliation required; open the session before accept.');
    const pack = loadProjectPack(root);
    const loaded = acceptanceQueue(root, opts);
    const { queue } = loaded;
    print(`${loaded.total} candidates awaiting accept. Acceptance: ${queue.length} rows in this sitting; ${loaded.waiting} waiting outside --list. Batch rule: named ids only when --list is used; other rows remain pending.`);
    if (!realTty()) {
      if (queue[0]) for (const line of renderContext(queue[0], buildLedger(pack, loaded.entries), verdictData(root).records)) print(line);
      print('Non-TTY: all rows remain pending. Open accept at your terminal to answer.');
      return { ok: true, status: 0, lines, outcomes, pending: loaded.total };
    }
    let ask = opts.ask;
    if (!ask) {
      terminal = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
      const input = terminal[Symbol.asyncIterator]();
      ask = async (prompt) => { print(prompt); const row = await input.next(); return row.done ? null : row.value; };
    }
    let position = 0;
    // The empty sitting still offers n: authored decisions need no candidate.
    while (position < queue.length || queue.length === 0) {
      let entry = queue[position];
      const show = (full = false) => {
        if (entry) for (const line of renderContext(entry, buildLedger(pack, loadLedgerEntries(root)), verdictData(root).records, full)) print(line);
        else print('No pending candidates. A new decision is authored by you; no source or value is inferred.');
      };
      const read = async (prompt, full = false) => { show(full); return ask(prompt); };
      const key = (await read(keys))?.trim().toLowerCase();
      if (!key || key === 'q') break;
      if (key === '?') { show(true); continue; }
      const date = new Date().toISOString();
      try {
        if (key === 'n') {
          // Deliberately recheck the process, never a caller-supplied tty flag.
          if (!realTty()) throw new Error('n is TTY-only; a seat cannot author a value.');
          const raw = await read('Type your decision value (JSON or text); for a new id use {"id":"decision.name","value":...,"interval":{"scope":"unspecified"},"governs":[]}. Supply project scope or chapter coordinates only when known.');
          if (raw === null || raw.trim() === '') break;
          let input; try { input = JSON.parse(raw); } catch { input = raw; }
          const supplied = input && typeof input === 'object' && !Array.isArray(input) && 'id' in input ? input : null;
          const placeholder = entry?.tuple.kind === 'decision' && entry.tuple.value == null && (!supplied || supplied.id === entry.tuple.id) ? entry : null;
          const id = supplied?.id || placeholder?.tuple.id;
          if (!id) throw new Error('A new decision needs a stable id in the JSON object.');
          const value = supplied ? supplied.value : input;
          const tuple = { schema: 1, id, kind: 'decision', value,
            interval: supplied?.interval || placeholder?.tuple.interval || { scope: 'unspecified' }, lock: 'candidate',
            receipt: { span: raw, heading_path: ['John’s authored decision'], line_hint: 1, date, source: 'john-terminal' }, authored_by: 'john',
            ...(supplied?.governs ? { governs: supplied.governs } : {}) };
          if (supplied?.allow_terms) tuple.allow_terms = supplied.allow_terms;
          const accepted = promote(tuple, null, date);
          if (loaded.named) throw new Error('New decisions are outside this bounded list; use the ordinary acceptance walk.');
          recordAnswer(root, placeholder, 'new', accepted, pack);
          outcomes.push({ id, action: 'new' }); print(`Authored and accepted ${id}.`);
          if (placeholder) position++;
          if (!queue.length) break;
          continue;
        }
        if (!entry) { print('Use n to author a new decision or q to quit.'); continue; }
        if (key === 'l') { outcomes.push({ id: entry.tuple.id, action: 'leave' }); position++; continue; }
        if (key === 's') {
          if (loaded.named) {
            const id = await read('Swap to an actual pending candidate ID in this project; the replacement remains pending.');
            if (id === null) break;
            const candidates = acceptanceQueue(root);
            const target = candidates.queue.find((r) => r.tuple.id === id.trim());
            swapFirstSelection(root, loaded.named, entry, target, candidates.entries);
            queue[position] = target;
            outcomes.push({ id: entry.tuple.id, action: 'swap', swap_id: target.tuple.id });
            continue;
          }
          const id = await read(`Swap to pending id: ${queue.slice(position + 1).map((r) => r.tuple.id).join(', ') || '(none)'}`);
          if (id === null) break;
          const target = queue.findIndex((r, i) => i > position && r.tuple.id === id.trim());
          if (target < 0) throw new Error('No later pending row has that id.');
          [queue[position], queue[target]] = [queue[target], queue[position]]; continue;
        }
        if (key === 'e') {
          const text = await read('Type the refined value or JSON patch {value, interval, governs, question}; only your entered text is recorded.');
          if (text === null) break;
          if (!pending(entry)) throw new Error('This is a locked receipt; e cannot re-value it. Use a new decision.');
          const refined = { ...cleanCandidate(entry.tuple), ...decodeEdit(text, entry.tuple), edited_by: 'john' };
          if (refined.kind === 'fact' && !(refined.value && typeof refined.value === 'object' && 'entity' in refined.value && 'predicate' in refined.value && 'object' in refined.value)) {
            refined.value = { ...entry.tuple.value, object: refined.value };
          }
          recordAnswer(root, entry, 'edit', refined, pack, loaded.named);
          entry = { ...entry, tuple: refined }; queue[position] = entry; continue;
        }
        if (key === 'd') {
          const note = await read('Type your defer note (shown first next sitting).');
          if (note === null) break;
          const deferred = { ...entry.tuple, deferred: { date, note } };
          recordAnswer(root, entry, 'defer', deferred, pack, loaded.named);
          outcomes.push({ id: entry.tuple.id, action: 'defer' }); position++; continue;
        }
        if (key === 'r') {
          recordAnswer(root, entry, 'reject', null, pack, loaded.named);
          outcomes.push({ id: entry.tuple.id, action: 'reject' }); position++; continue;
        }
        if (key === 'a') {
          const accepted = promote(entry.tuple, entry, date);
          recordAnswer(root, entry, 'accept', accepted, pack, loaded.named);
          outcomes.push({ id: entry.tuple.id, action: 'accept' }); position++; continue;
        }
        print(`Unknown key: ${key}. ${keys}`);
      } catch (e) { print(`Pending: ${e.message}`); }
    }
    const remaining = acceptanceQueue(root).total;
    print(`Sitting saved: ${remaining} pending. Quitting halfway loses nothing.`);
    return { ok: true, status: 0, lines, outcomes, pending: remaining };
  } catch (e) {
    const row = /ETIMEDOUT|cancelled|killed/.test(e.code || '') ? 'dependency-slow-or-killed'
      : e instanceof SyntaxError ? 'dependency-returns-garbage'
      : /ENOENT|pack.*missing/.test(e.message) ? 'dependency-missing' : 'backing-store-unreadable';
    const f = failureRow('accept', row); print(f.text); print(e.message);
    return { ok: false, status: f.status, row, lines, outcomes };
  } finally { terminal?.close(); }
}
