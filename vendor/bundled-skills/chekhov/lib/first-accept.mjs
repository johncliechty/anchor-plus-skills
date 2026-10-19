/** Formal0037: one bounded, project-local named list; never selects by alias. */
import fs from 'node:fs';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { acceptanceHash, hasAcceptance, resolveReceipt } from './tuples.mjs';
import { atomicWriteFile, loadSession, stateDirFor, withLock, appendReceipt } from './store.mjs';
import { computeManifest, diffManifests, manifestHash, sha256Text } from './manifest.mjs';

export const FIRST_ACCEPT_LIMIT = 12;
export function firstAcceptPath(root) { return path.join(stateDirFor(root), 'first-accept.json'); }
export function readFirstAccept(root, entries, { project } = {}) {
  const file = firstAcceptPath(root);
  if (!fs.existsSync(file)) throw new Error('Missing first-accept list: root must select at most twelve actual candidate IDs for this project.');
  const list = JSON.parse(fs.readFileSync(file, 'utf8'));
  const configFile = path.join(stateDirFor(root), 'config.json');
  const config = fs.existsSync(configFile) ? JSON.parse(fs.readFileSync(configFile, 'utf8')) : {};
  const expectedProject = project || config.project || path.basename(root);
  if (list.schema !== 1 || list.project !== expectedProject || !Array.isArray(list.rows)
    || list.rows.length < 1 || list.rows.length > FIRST_ACCEPT_LIMIT) throw new Error('Invalid or wrong-project first-accept list.');
  const ids = new Set(), receipts = loadSession(stateDirFor(root)).receipts;
  for (const row of list.rows) {
    if (!row || typeof row.id !== 'string' || ids.has(row.id) || !['pending', 'accepted', 'rejected', 'swapped'].includes(row.disposition)
      || !/^[a-f0-9]{64}$/.test(row.receipt_hash || '') || !(row.swap_id === null || typeof row.swap_id === 'string')) throw new Error('Invalid first-accept disposition row.');
    ids.add(row.id);
    const id = row.swap_id || row.id;
    if (!id || list.rows.some((other) => other !== row && (other.swap_id || other.id) === id)) throw new Error('Duplicate or missing swap target.');
    const entry = entries.find((e) => e.tuple.id === id);
    if (row.disposition === 'rejected') {
      if (entry || !receipts.some((r) => r.transition === 'accept' && r.id === id && r.action === 'reject'
        && !r.invalidated && r.first_accept_hash === row.receipt_hash)) throw new Error(`Rejected disposition lacks its receipt: ${id}`);
      continue;
    }
    if (!entry) throw new Error(`First-accept ID is not in this project's candidate index: ${id}`);
    if (entry.tuple.orders || /^series\.(?:orders|reader_order|written_order|cascade_position)$/.test(id)) throw new Error('Series orders are held out of first-accept.');
    if (row.disposition === 'accepted') {
      if (!hasAcceptance(entry.tuple) || !receipts.some((r) => r.transition === 'accept' && r.id === id && r.action === 'accept'
        && !r.invalidated && r.first_accept_hash === row.receipt_hash)) throw new Error(`Accepted disposition does not match tuple and receipt: ${id}`);
    } else if (hasAcceptance(entry.tuple) || acceptanceHash(entry.tuple) !== row.receipt_hash) throw new Error(`First-accept candidate changed: ${id}`);
    if (entry.prose === null || resolveReceipt(entry.prose, entry.tuple.receipt).status !== 'exact') throw new Error(`First-accept receipt requires review: ${id}`);
  }
  return { file, list, ids: list.rows.filter((r) => ['pending', 'swapped'].includes(r.disposition)).map((r) => r.swap_id || r.id) };
}

/** Called only by the existing TTY answer writer while it holds the root lock. */
export function recordFirstDisposition(root, loaded, id, action, tuple) {
  if (!loaded) return;
  const current = JSON.parse(fs.readFileSync(loaded.file, 'utf8'));
  if (!isDeepStrictEqual(current, loaded.list)) throw new Error('First-accept list changed during the walk.');
  const row = current.rows.find((r) => (r.swap_id || r.id) === id);
  if (!row) throw new Error('Answer is outside the named sitting.');
  if (action === 'accept') row.disposition = 'accepted';
  else if (action === 'reject') row.disposition = 'rejected';
  else if (tuple) row.receipt_hash = acceptanceHash(tuple);
  atomicWriteFile(loaded.file, JSON.stringify(current, null, 2) + '\n');
  loaded.list = current;
}

export function firstAcceptGate(root, entries, opts = {}) {
  try {
    const loaded = readFirstAccept(root, entries, opts);
    const pending = loaded.list.rows.filter((r) => ['pending', 'swapped'].includes(r.disposition)).map((r) => r.swap_id || r.id);
    return { ok: pending.length === 0, pending, author_sitting: pending.length === 0 ? 'recorded dispositions require root validation' : 'pending John' };
  } catch (e) { return { ok: false, reason: e.message, author_sitting: 'pending John' }; }
}

export function swapFirstSelection(root, loaded, entry, target, entries) {
  if (!(process.stdin.isTTY === true && process.stdout.isTTY === true)) throw new Error('Human answers require a real terminal.');
  return withLock(stateDirFor(root), undefined, () => {
    const session = loadSession(stateDirFor(root)), manifest = computeManifest(root);
    if (session.halt?.open || session.manifest && diffManifests(session.manifest, manifest).unmanaged_engine.length) throw new Error('Reconciliation required before swapping.');
    const reread = readFirstAccept(root, entries, { project: loaded.list.project });
    if (!isDeepStrictEqual(loaded.list, reread.list)) throw new Error('First-accept list changed during the walk.');
    if (!target || hasAcceptance(target.tuple) || target.tuple.orders || /^series\.(?:orders|reader_order|written_order|cascade_position)$/.test(target.tuple.id)) throw new Error('Swap requires a pending ID in this project, excluding series orders.');
    if (target.prose === null || resolveReceipt(target.prose, target.tuple.receipt).status !== 'exact') throw new Error('Swap receipt requires review.');
    if (reread.list.rows.some((r) => (r.swap_id || r.id) === target.tuple.id)) throw new Error('Swap target is already in this list.');
    const row = reread.list.rows.find((r) => (r.swap_id || r.id) === entry.tuple.id);
    if (!row) throw new Error('Current ID is outside this list.');
    row.disposition = 'swapped'; row.swap_id = target.tuple.id; row.receipt_hash = acceptanceHash(target.tuple);
    atomicWriteFile(loaded.file, JSON.stringify(reread.list, null, 2) + '\n');
    appendReceipt(stateDirFor(root), session, { transition: 'first-accept-swap', at: new Date().toISOString(),
      id: entry.tuple.id, target: target.tuple.id, inputs_hash: sha256Text(JSON.stringify(loaded.list)),
      outputs_hash: sha256Text(JSON.stringify(reread.list)), manifest_hash: manifestHash(manifest) });
    loaded.list = reread.list;
  });
}
