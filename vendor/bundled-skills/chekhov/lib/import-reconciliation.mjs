/** Verified operator import adoption. No model calls, author acceptance, or source writes.
 * session.json and commit.json are separate atomic files: a prepared receipt keeps
 * writing halted until the exact hash-bound commit merge and baseline finish.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { computeManifest, manifestHash, sha256File, sha256Text, CLASS_ENGINE } from './manifest.mjs';
import { SESSION_SCHEMA, stateDirFor, sessionPath, withLock, appendReceipt, atomicWriteFile } from './store.mjs';
import { loadLedgerEntries } from './index.mjs';
import { scenesOf, commitStatePath } from './commit.mjs';
import { sourceReferenceMatches } from './onboarding-t1.mjs';
import { verifyProductEvidence } from './product-evidence.mjs';

const suffix = '.ledger.yaml';
const digest = value => { assert.match(value, /^[a-f0-9]{64}$/); return value; };
const encoded = value => `${JSON.stringify(value, null, 2)}\n`;
const inside = (base, file) => { const rel = path.relative(base, file); return !path.isAbsolute(rel) && rel !== '..' && !rel.startsWith(`..${path.sep}`); };
function relativeFile(root, file) {
  assert.equal(typeof file, 'string');
  const rel = (path.isAbsolute(file) ? path.relative(root, file) : file).replace(/\\/g, '/');
  assert(rel && !path.win32.isAbsolute(rel) && !/^[a-z]:/i.test(rel) && rel.split('/').every(p => p && p !== '.' && p !== '..'), 'invalid import path');
  assert(inside(fs.realpathSync(root), fs.realpathSync(path.resolve(root, rel))), 'import path escapes root');
  assert(fs.statSync(path.resolve(root, rel)).isFile(), 'import target is not a file');
  return rel;
}
function checkedFile(ref) {
  assert(ref && path.isAbsolute(ref.file), 'evidence file must be absolute');
  assert.equal(sha256File(ref.file), digest(ref.sha256), `evidence hash drift: ${ref.file}`);
  return fs.readFileSync(ref.file, 'utf8');
}
function commitShape(value) {
  assert.equal(value?.schema, 1);
  assert(value.completed && typeof value.completed === 'object' && !Array.isArray(value.completed));
  assert(Array.isArray(value.candidates));
  assert(value.source_files === undefined || Array.isArray(value.source_files));
  return value;
}

function generatedBindings(root, ref, product) {
  const out = new Map();
  if (!ref) return out;
  const proof = JSON.parse(checkedFile(ref));
  assert.equal(proof.schema, 1);
  assert.equal(proof.type, 'chekhov-generated-output-provenance');
  assert(Array.isArray(proof.source_copies) && Array.isArray(proof.observer_outputs));
  const add = row => {
    const rel = relativeFile(root, row.file);
    assert(!out.has(rel), 'duplicate generated-output binding');
    assert.equal(sha256File(row.file), digest(row.sha256));
    out.set(rel, row.sha256);
  };
  for (const row of proof.source_copies) {
    assert(product.evidence.some(e => path.resolve(e.file) === path.resolve(row.input_file) && e.sha256 === row.input_sha256), 'copy input is outside product evidence');
    const input = JSON.parse(checkedFile({ file: row.input_file, sha256: row.input_sha256 }));
    const sources = input.sources.filter(s => s.id === row.input_source_id);
    assert.equal(sources.length, 1, 'copy source must bind uniquely');
    const source = sources[0];
    assert.equal(fs.readFileSync(row.file, 'utf8'), source.text, 'copy differs from recorded input');
    assert.equal(sha256Text(source.text), source.normalized_excerpt_sha256);
    assert.equal(row.sha256, source.normalized_excerpt_sha256);
    assert.equal(source.original_sha256, row.original_sha256);
    assert.equal(path.resolve(root, source.file), path.resolve(row.original_file));
    checkedFile({ file: row.original_file, sha256: row.original_sha256 });
    checkedFile({ file: row.derived_file, sha256: row.derived_sha256 });
    assert.equal(fs.readFileSync(row.derived_file, 'utf8'), source.text);
    add(row);
  }
  for (const row of proof.observer_outputs) {
    checkedFile({ file: row.writer_file, sha256: row.writer_sha256 });
    const finalState = (file, hash, line) => {
      const lines = checkedFile({ file, sha256: hash }).split(/\r?\n/);
      while (lines.at(-1) === '') lines.pop();
      assert.equal(line, lines.length, 'observer reference is not the final recorded line');
      return JSON.parse(lines.at(-1));
    };
    const state = finalState(row.tick_file, row.tick_sha256, row.final_tick_line);
    assert.deepEqual(finalState(row.log_file, row.log_sha256, row.final_log_line), state);
    assert.equal(state.done, true);
    const phase = JSON.parse(checkedFile({ file: row.phase_file, sha256: row.phase_sha256 }));
    for (const [key, value] of Object.entries(phase)) assert.deepEqual(state[key], value, `observer phase mismatch: ${key}`);
    assert.equal(row.physical_newline, 'CRLF');
    const bytes = JSON.stringify(state, null, 2).replace(/[\u007f-\uffff]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`).replace(/\n/g, '\r\n');
    assert.equal(fs.readFileSync(row.file, 'utf8'), bytes, 'observer bytes do not reconstruct from the final recorded state');
    add(row);
  }
  return out;
}

/** Read-only proof. New prose remains outside the adopted engine baseline. */
export function verifyImportReconciliation(root, proof) {
  root = path.resolve(root);
  assert.equal(proof?.schema, 1);
  const proofHash = sha256Text(JSON.stringify(proof));
  const stateDir = stateDirFor(root);
  const rawSession = fs.readFileSync(sessionPath(stateDir), 'utf8');
  const session = JSON.parse(rawSession); // never use the store's fresh-session fallback here
  assert.equal(session.schema, SESSION_SCHEMA);
  assert(Array.isArray(session.receipts) && session.manifest?.files, 'existing session baseline required');
  assert(session.halt?.open && session.halt.kind === 'reconciliation', 'an open reconciliation halt is required');
  assert.equal(manifestHash(session.manifest), digest(proof.previous_manifest_hash), 'prior baseline differs');
  const pending = session.receipts.findLast(r => r.transition === 'verified-import' && r.phase === 'prepared');
  if (pending && !session.receipts.some(r => r.transition === 'verified-import' && r.phase === 'completed' && r.proof_hash === pending.proof_hash)) {
    assert.equal(pending.proof_hash, proofHash, 'a different import is already prepared');
  }
  const configFile = path.join(stateDir, 'config.json');
  assert.equal(sha256File(configFile), digest(proof.config_sha256), 'configuration drift');
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  const current = computeManifest(root), previous = session.manifest;
  for (const [rel, old] of Object.entries(previous.files)) assert.deepEqual(current.files[rel], old, `prior file modified or deleted: ${rel}`);
  const additions = Object.keys(current.files).filter(rel => !previous.files[rel] && current.files[rel].class === CLASS_ENGINE).sort();
  assert(Array.isArray(proof.engine_additions) && proof.engine_additions.length, 'explicit engine additions required');
  const listed = new Map();
  for (const row of proof.engine_additions) {
    const rel = relativeFile(root, row.path);
    assert(!listed.has(rel), 'duplicate engine addition');
    assert.equal(current.files[rel]?.sha256, digest(row.sha256), `addition hash drift: ${rel}`);
    listed.set(rel, row.sha256);
  }
  assert.deepEqual([...listed.keys()].sort(), additions, 'unlisted or extra engine addition');
  assert.deepEqual([...new Set(session.halt.files)].sort(), additions, 'halt differs from the verified additions');
  const product = JSON.parse(checkedFile(proof.product_evidence));
  assert.equal(fs.realpathSync(product.project_root), fs.realpathSync(root));
  assert.deepEqual(config.ledger_sources, product.source_paths, 'active selection differs from recorded product');
  assert(product.public_capture, 'dated public capture required');
  const capture = JSON.parse(checkedFile(product.public_capture));
  const live = loadLedgerEntries(root);
  const report = verifyProductEvidence(product, { entries: live, verifyFiles: true });
  const expected = new Map(capture.entries.map(e => [e.tuple.id, e]));
  const importedFiles = new Set(), covered = new Set();
  for (const entry of live) {
    const recorded = expected.get(entry.tuple.id);
    assert.deepEqual(entry, recorded, `live entry differs from capture: ${entry.tuple.id}`);
    const sidecar = relativeFile(root, entry.sidecar);
    assert(sidecar.endsWith(suffix));
    const proseFile = relativeFile(root, sidecar.slice(0, -suffix.length));
    assert.equal(fs.readFileSync(path.join(root, proseFile), 'utf8'), entry.prose, 'copied source drift');
    importedFiles.add(proseFile); covered.add(sidecar); covered.add(proseFile);
  }
  const generated = generatedBindings(root, proof.generated_provenance, product);
  for (const rel of generated.keys()) assert(additions.includes(rel) && !covered.has(rel), 'generated proof overlaps or exceeds the remaining additions');
  for (const rel of additions) assert(covered.has(rel) || generated.has(rel), `unproven engine addition: ${rel}`);

  // Import only actually recorded completions, using declared relocation and
  // independently recomputed old/new scene hashes. Never infer completion.
  assert.notEqual(path.resolve(proof.previous_commit.file), path.resolve(commitStatePath(root)), 'preserve the prior commit state as separate evidence');
  const before = commitShape(JSON.parse(checkedFile(proof.previous_commit)));
  const recordedPath = path.join(product.recording_root, 'chekhov', 'commit.json');
  assert.equal(path.resolve(proof.recorded_commit.file), path.resolve(recordedPath));
  const recorded = commitShape(JSON.parse(checkedFile(proof.recorded_commit)));
  const merged = structuredClone(before), cache = new Map(), adoptedSources = new Set();
  const selectedRoots = config.ledger_sources.map(dir => fs.realpathSync(path.resolve(root, dir)));
  const sceneMap = (base, file) => {
    const absolute = path.resolve(base, file);
    if (!cache.has(absolute)) cache.set(absolute, new Map(scenesOf({ file, text: fs.readFileSync(absolute, 'utf8') }).map(s => [s.line, s.hash])));
    return cache.get(absolute);
  };
  const relocate = file => {
    const matches = (config.source_relocations || []).filter(m => typeof m.from === 'string' && typeof m.to === 'string' && file.startsWith(m.from))
      .map(m => m.to + file.slice(m.from.length)).filter(actual => sourceReferenceMatches(root, file, actual));
    if (!matches.length && sourceReferenceMatches(root, file, file)) matches.push(file);
    assert.equal(new Set(matches).size, 1, `ambiguous or missing declared relocation: ${file}`);
    const actual = relativeFile(root, matches[0]);
    assert(selectedRoots.some(dir => inside(dir, fs.realpathSync(path.resolve(root, actual)))), 'recorded completion is outside active source selection');
    return actual;
  };
  for (const [key, hash] of Object.entries(recorded.completed).sort(([a], [b]) => a.localeCompare(b))) {
    const match = /^(.*):(\d+)$/.exec(key);
    assert(match, 'malformed recorded completion');
    const [, file, lineText] = match, line = Number(lineText), actual = relocate(file);
    relativeFile(product.recording_root, file);
    assert.equal(sceneMap(product.recording_root, file).get(line), digest(hash), 'recorded scene hash drift');
    assert.equal(sceneMap(root, actual).get(line), hash, 'relocated scene hash drift');
    const target = `${actual}:${line}`;
    assert(merged.completed[target] === undefined || merged.completed[target] === hash, `conflicting existing completion: ${target}`);
    merged.completed[target] = hash; adoptedSources.add(actual);
  }
  const known = new Map(merged.candidates.map(c => [c.id, c])), recordedIDs = new Set();
  for (const candidate of recorded.candidates) {
    assert(!recordedIDs.has(candidate.id), 'duplicate recorded candidate'); recordedIDs.add(candidate.id);
    assert(expected.has(candidate.id), 'recorded candidate is outside verified product');
    assert(candidate.sidecar.endsWith(suffix));
    const source = relocate(candidate.sidecar.slice(0, -suffix.length));
    assert(importedFiles.has(source), 'candidate source is outside verified imported sidecars');
    const mapped = { ...candidate, sidecar: source + suffix };
    assert.equal(expected.get(candidate.id).sidecar, mapped.sidecar);
    assert.deepEqual(candidate.receipt, expected.get(candidate.id).tuple.receipt);
    if (known.has(candidate.id)) assert.deepEqual(known.get(candidate.id), mapped, 'conflicting existing candidate history');
    else { merged.candidates.push(mapped); known.set(candidate.id, mapped); }
  }
  assert([...expected.keys()].every(id => known.has(id)), 'recorded commit omits imported candidates');
  assert([...importedFiles].every(file => adoptedSources.has(file)), 'imported source lacks a recorded completion');
  // The index registry requires actual sidecars. Zero-proposal source scenes may
  // retain verified completion hashes without inventing an empty sidecar.
  merged.source_files = [...new Set([...(before.source_files || []), ...[...importedFiles].sort()])];
  const afterText = encoded(merged), afterHash = sha256Text(afterText);
  const currentCommitHash = sha256File(commitStatePath(root));
  assert(currentCommitHash === proof.previous_commit.sha256 || pending?.proof_hash === proofHash && pending.commit_after_hash === afterHash && currentCommitHash === afterHash, 'current commit-state drift');
  const adoptedManifest = structuredClone(previous);
  for (const rel of additions) adoptedManifest.files[rel] = current.files[rel];
  return { proofHash, session, rawSession, report, additions, adoptedManifest, afterText, afterHash,
    beforeHash: proof.previous_commit.sha256, currentCommitHash,
    newProsePending: Object.keys(current.files).filter(rel => !previous.files[rel] && current.files[rel].class !== CLASS_ENGINE),
  };
}

export function reconcileVerifiedImport(root, proof, opts = {}) {
  const initial = verifyImportReconciliation(root, proof);
  return withLock(stateDirFor(root), opts.lockOpts, () => {
    const checked = verifyImportReconciliation(root, proof);
    assert.equal(checked.proofHash, initial.proofHash);
    const { session } = checked, at = opts.now || new Date().toISOString();
    const receipt = phase => ({ transition: 'verified-import', phase, at, actor: 'operator-import-adoption',
      author_acceptance: false, proof_hash: checked.proofHash,
      inputs_hash: checked.beforeHash, outputs_hash: checked.afterHash,
      manifest_hash: manifestHash(checked.adoptedManifest), previous_manifest_hash: proof.previous_manifest_hash,
      config_sha256: proof.config_sha256, commit_before_hash: checked.beforeHash, commit_after_hash: checked.afterHash,
      engine_paths: checked.additions, product_evidence: proof.product_evidence, generated_provenance: proof.generated_provenance || null,
      limitations: 'Recorded import adoption only; observer reconstruction is not creation-time attestation, current status, author acceptance, or a new model review.',
    });
    if (!session.receipts.some(r => r.transition === 'verified-import' && r.phase === 'prepared' && r.proof_hash === checked.proofHash)) {
      appendReceipt(stateDirFor(root), session, receipt('prepared')); // baseline and HALT remain unchanged
    }
    if (checked.currentCommitHash !== checked.afterHash) atomicWriteFile(commitStatePath(root), checked.afterText);
    // A failed recheck or final session write leaves the prepared HALT recoverable.
    const final = verifyImportReconciliation(root, proof);
    assert.equal(final.afterHash, checked.afterHash);
    final.session.manifest = final.adoptedManifest;
    final.session.halt = { ...final.session.halt, open: false, closed_at: at, resolution: 'verified-operator-import', proof_hash: final.proofHash };
    appendReceipt(stateDirFor(root), final.session, receipt('completed'));
    return { ok: true, receipt: final.session.receipts.at(-1), report: final.report,
      adopted_engine_files: final.additions.length, new_prose_pending: final.newProsePending, author_acceptance: false };
  });
}
