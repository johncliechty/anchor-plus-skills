import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {writeFileAtomicSync} from './durable-write.mjs';

const FOLDER = 'Finished Deliverables';
const INDEX = 'index.json';
const PENDING = '.steward-approved-pending.json';
const SCHEMA = 'steward-approved-deliverables-v1';
const PENDING_SCHEMA = 'steward-approved-deliverables-pending-v1';
const HEX = /^[a-f0-9]{64}$/;

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

const digest = value => crypto.createHash('sha256').update(
  Buffer.isBuffer(value) ? value : JSON.stringify(canonical(value)),
).digest('hex');
const jsonBytes = value => Buffer.from(`${JSON.stringify(value, null, 2)}\n`);

function relativeParts(value) {
  if (typeof value !== 'string' || !value || path.isAbsolute(value)
      || path.win32.isAbsolute(value) || /[\\:\x00-\x1f]/.test(value)) {
    fail('APPROVED_PATH_INVALID', `Unsafe relative path: ${String(value)}`);
  }
  const parts = value.split('/');
  if (parts.some(part => !part || part === '.' || part === '..')) {
    fail('APPROVED_PATH_INVALID', `Unsafe relative path: ${value}`);
  }
  return parts;
}

function safeLabel(label) {
  if (typeof label !== 'string') fail('APPROVED_NAVIGATION_INVALID', 'Group labels must be strings.');
  let safe = label.normalize('NFC').replace(/[<>:"/\\|?*\x00-\x1f\x7f]/g, '-')
    .replace(/^[ .]+|[ .]+$/g, '');
  if (!safe) fail('APPROVED_NAVIGATION_INVALID', 'A group label has no safe filename characters.');
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(safe)) safe = `_${safe}`;
  if (safe.length > 100) safe = `${safe.slice(0, 90)}-${digest(label).slice(0, 8)}`;
  return safe;
}

function filename(productId, sourcePath) {
  if (typeof productId !== 'string' || !/^[A-Za-z0-9_-]+$/.test(productId)
      || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(productId)) {
    fail('APPROVED_PRODUCT_ID_INVALID', `Unsafe product ID: ${String(productId)}`);
  }
  relativeParts(sourcePath);
  const extension = path.posix.extname(sourcePath);
  if (extension && !/^\.[A-Za-z0-9_-]{1,20}$/.test(extension)) {
    fail('APPROVED_EXTENSION_INVALID', `Unsafe product extension: ${extension}`);
  }
  return `${productId}${extension}`;
}

function acceptedRecords(state) {
  if (!state?.slices || typeof state.slices !== 'object' || Array.isArray(state.slices)) {
    fail('APPROVED_STATE_INVALID', 'Expected the folded refinement slices.');
  }
  const records = [];
  for (const key of Object.keys(state.slices).sort()) {
    const slice = state.slices[key];
    const stepId = slice?.step_id ?? key;
    const presentations = new Map();
    for (const presentation of slice?.presentations ?? []) {
      if (!presentation?.id || presentations.has(presentation.id) || !Array.isArray(presentation.members)) {
        fail('APPROVED_STATE_INVALID', `Invalid presentation in ${stepId}.`);
      }
      presentations.set(presentation.id, presentation);
    }
    for (const acceptance of slice?.acceptance_history ?? []) {
      const presentation = presentations.get(acceptance.presentation_id);
      if (!presentation) fail('APPROVED_ACCEPTANCE_INVALID', `Accepted presentation is missing in ${stepId}.`);
      const members = acceptance.member_product_id == null
        ? presentation.members
        : presentation.members.filter(member => member.product_id === acceptance.member_product_id);
      if (!members.length) fail('APPROVED_ACCEPTANCE_INVALID', `Accepted members are missing in ${stepId}.`);
      const seen = new Set();
      for (const member of members) {
        const hash = member.hash ?? member.sha256;
        if (typeof hash !== 'string' || !HEX.test(hash)
            || (member.hash && member.sha256 && member.hash !== member.sha256)
            || typeof member.revision_id !== 'string' || !member.revision_id
            || seen.has(member.product_id)) {
          fail('APPROVED_ACCEPTANCE_INVALID', `Invalid accepted member in ${stepId}.`);
        }
        filename(member.product_id, member.path);
        seen.add(member.product_id);
        records.push({
          ...member, hash, step_id: stepId, title: slice.title ?? stepId,
          accepted_at: acceptance.at ?? null, presentation_id: presentation.id,
        });
      }
    }
  }
  return records;
}

/** Derive current approvals exclusively from acceptance_history, never candidates. */
export function approvedDeliverables(state, navigation = {}, {strictNavigation=false} = {}) {
  try {
  const groups = new Map();
  for (const entry of Object.values(navigation)) {
    for (const group of entry?.groups ?? []) {
      if (typeof group?.id !== 'string' || typeof group.label !== 'string') {
        fail('APPROVED_NAVIGATION_INVALID', 'Invalid navigation group definition.');
      }
      if (groups.has(group.id) && groups.get(group.id).label !== group.label) {
        fail('APPROVED_NAVIGATION_INVALID', `Conflicting labels for group ${group.id}.`);
      }
      groups.set(group.id, { id: group.id, label: group.label, order: group.order ?? null });
    }
  }
  const latest = new Map();
  for (const member of acceptedRecords(state)) latest.set(`${member.step_id}\0${member.product_id}`, member);
  return [...latest.values()].map(member => {
    const groupPath = navigation[member.step_id]?.path ?? [];
    if (!Array.isArray(groupPath)) fail('APPROVED_NAVIGATION_INVALID', 'Group paths must be arrays.');
    return {
      ...member, group_path: [...groupPath],
      groups: groupPath.map(id => {
        if (!groups.has(id)) fail('APPROVED_NAVIGATION_INVALID', `Undefined navigation group ${String(id)}.`);
        return { ...groups.get(id) };
      }),
    };
  }).sort((a, b) => `${a.step_id}\0${a.product_id}`.localeCompare(`${b.step_id}\0${b.product_id}`));
  } catch(error) {
    if(!strictNavigation && error.code==='APPROVED_NAVIGATION_INVALID')
      return approvedDeliverables(state,{}, {strictNavigation:true});
    throw error;
  }
}

function statOrNull(file) {
  try { return fs.lstatSync(file); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function within(root, target) {
  const relative = path.relative(root, target);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function outputPath(root, relative) {
  const parts = [FOLDER, ...relativeParts(relative)];
  let current = root;
  for (let index = 0; index < parts.length; index += 1) {
    current = path.join(current, parts[index]);
    const stat = statOrNull(current);
    if (stat?.isSymbolicLink()) fail('APPROVED_SYMLINK', `Projection paths cannot be symlinks: ${current}`);
    if (stat && index < parts.length - 1 && !stat.isDirectory()) {
      fail('APPROVED_PATH_CONFLICT', `A projection directory is occupied by a file: ${current}`);
    }
  }
  return current;
}

function outputBytes(root, relative) {
  const file = outputPath(root, relative);
  const stat = statOrNull(file);
  if (!stat) return null;
  if (!stat.isFile()) fail('APPROVED_PATH_CONFLICT', `A projection file is occupied by another object: ${file}`);
  return fs.readFileSync(file);
}

function metadata(root, relative) {
  const bytes = outputBytes(root, relative);
  if (bytes === null) return { bytes: null, value: null };
  try { return { bytes, value: JSON.parse(bytes.toString('utf8')) }; }
  catch { fail('APPROVED_METADATA_INVALID', `Cannot parse ${relative}; it was left untouched.`); }
}

const signature = file => digest([
  file.step_id, file.presentation_id, file.product_id, file.revision_id,
  file.hash, file.source_path ?? file.path, file.accepted_at,
]);

function validateIndex(index, state) {
  if (index === null) return [];
  if (index.schema !== SCHEMA || !Array.isArray(index.files) || index.acceptance_digest !== digest(index.files)) {
    fail('APPROVED_INDEX_INVALID', 'The existing generated index failed validation.');
  }
  const accepted = new Set(acceptedRecords(state).map(signature));
  const seen = new Set();
  for (const file of index.files) {
    const parts = relativeParts(file.path);
    const key = file.path.normalize('NFC').toLowerCase();
    if (parts.at(-1) !== filename(file.product_id, file.source_path)
        || parts.slice(0, -1).some(part => safeLabel(part) !== part)
        || file.path === INDEX || file.path === PENDING
        || !accepted.has(signature(file)) || seen.has(key)) {
      fail('APPROVED_INDEX_INVALID', `An indexed file is not a valid historical approval: ${file.path}`);
    }
    seen.add(key);
  }
  return index.files;
}

function temporaryName(relative, transaction) {
  const parts = relativeParts(relative);
  const basename = parts.pop();
  return [...parts, `.${basename}.steward-${transaction}.tmp`].join('/');
}

function atomicWrite(root, relative, bytes, transaction, resume) {
  const target = outputPath(root, relative);
  const temporary = temporaryName(relative, transaction);
  const existing = outputBytes(root, temporary);
  if (existing !== null && (!resume || digest(existing) !== digest(bytes))) {
    fail('APPROVED_TEMP_CONFLICT', `A staging file has unexpected bytes: ${temporary}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  outputPath(root, relative);
  const temporaryPath = outputPath(root, temporary);
  // The established writer retries transient Windows sharing failures and
  // cleans a failed first-marker staging file before a subsequent repair.
  writeFileAtomicSync(target,bytes);
  if(existing !== null)fs.unlinkSync(temporaryPath);
}

/**
 * Publish a derived folder under the existing project writer's serialization.
 * Preflight precedes writes. A digest-only pending marker permits same-state
 * recovery after completed file writes or stale-file deletion. Conflicting user
 * edits, malformed markers, and partial staging bytes fail visibly untouched.
 */
export function publishApprovedDeliverables(root, state, navigation = {}) {
  const realRoot = fs.realpathSync(root);
  const approved = approvedDeliverables(state, navigation, {strictNavigation:true});
  const sources = new Map();
  const destinations = new Set();
  const files = approved.map(member => {
    const relative = [...member.groups.map(group => safeLabel(group.label)), filename(member.product_id, member.path)].join('/');
    const key = relative.normalize('NFC').toLowerCase();
    if (relative === INDEX || relative === PENDING || destinations.has(key)) {
      fail('APPROVED_PATH_COLLISION', `Approved products collide at ${relative}.`);
    }
    destinations.add(key);
    const source = fs.realpathSync(path.join(realRoot, ...relativeParts(member.path)));
    if (!within(realRoot, source) || within(path.join(realRoot, FOLDER), source)) {
      fail('APPROVED_SOURCE_ESCAPE', `Accepted source is outside immutable project storage: ${member.path}`);
    }
    if (!fs.statSync(source).isFile()) fail('APPROVED_SOURCE_INVALID', `Accepted source is not a file: ${member.path}`);
    const bytes = fs.readFileSync(source);
    if (digest(bytes) !== member.hash) fail('APPROVED_SOURCE_HASH', `Accepted source changed: ${member.path}`);
    sources.set(relative, bytes);
    return {
      path: relative, source_path: member.path, hash: member.hash,
      step_id: member.step_id, product_id: member.product_id, revision_id: member.revision_id,
      presentation_id: member.presentation_id, accepted_at: member.accepted_at,
    };
  });
  const desired = { schema: SCHEMA, acceptance_digest: digest(files), files };
  const desiredBytes = jsonBytes(desired);
  const desiredHash = digest(desiredBytes);
  const old = metadata(realRoot, INDEX);
  if (old.bytes !== null && old.value === null) fail('APPROVED_INDEX_INVALID', 'Existing index is null.');
  const oldFiles = validateIndex(old.value, state);
  const oldHash = old.bytes === null ? null : digest(old.bytes);
  const pending = metadata(realRoot, PENDING);
  const resume = pending.value !== null;
  let marker = pending.value;
  if (resume) {
    const keys = Object.keys(marker).sort().join(',');
    if (keys !== 'acceptance_digest,base_hash,desired_hash,schema,transaction'
        || marker.schema !== PENDING_SCHEMA
        || (marker.base_hash !== null && !HEX.test(marker.base_hash))
        || marker.desired_hash !== desiredHash || marker.acceptance_digest !== desired.acceptance_digest
        || marker.transaction !== digest([marker.base_hash, marker.desired_hash]).slice(0, 24)
        || (oldHash !== marker.base_hash && oldHash !== marker.desired_hash)) {
      fail('APPROVED_PENDING_MISMATCH', 'Pending publication does not match this acceptance state and index.');
    }
  } else {
    marker = {
      schema: PENDING_SCHEMA, base_hash: oldHash, desired_hash: desiredHash,
      acceptance_digest: desired.acceptance_digest,
      transaction: digest([oldHash, desiredHash]).slice(0, 24),
    };
  }
  const markerBytes = pending.bytes ?? jsonBytes(marker);
  const oldByPath = new Map(oldFiles.map(file => [file.path, file]));
  const nextByPath = new Map(files.map(file => [file.path, file]));
  const readHash = relative => {
    const bytes = outputBytes(realRoot, relative);
    return bytes === null ? null : digest(bytes);
  };
  const checkCurrent = relative => {
    const prior = oldByPath.get(relative);
    const next = nextByPath.get(relative);
    const current = readHash(relative);
    if (prior) {
      if (resume && !next && current === null) return current;
      if (current !== prior.hash && !(resume && next && current === next.hash)) {
        fail('APPROVED_FILE_CONFLICT', `Previously indexed bytes changed or disappeared: ${relative}`);
      }
    } else if (current !== null && !(resume && next && current === next.hash)) {
      fail('APPROVED_UNKNOWN_FILE', `An unowned file occupies the approved destination: ${relative}`);
    }
    return current;
  };

  // All desired and formerly generated files, including staging slots, are
  // inspected before the first directory, marker, or product write.
  for (const relative of new Set([...oldByPath.keys(), ...nextByPath.keys()])) checkCurrent(relative);
  for (const [relative, bytes] of [...sources, [INDEX, desiredBytes], [PENDING, markerBytes]]) {
    const temporary = temporaryName(relative, marker.transaction);
    const current = readHash(temporary);
    if (current !== null && (!resume || current !== digest(bytes))) {
      fail('APPROVED_TEMP_CONFLICT', `A staging file is not safely reusable: ${temporary}`);
    }
  }
  const result = { ok: true, folder: FOLDER, index_path: `${FOLDER}/${INDEX}`, files, acceptance_digest: desired.acceptance_digest };
  if (!resume && oldHash === desiredHash) return { ...result, updated: false };

  if (!resume) {
    if (outputBytes(realRoot, PENDING) !== null) fail('APPROVED_PENDING_MISMATCH', 'A publication marker appeared during preflight.');
    atomicWrite(realRoot, PENDING, markerBytes, marker.transaction, false);
  }
  for (const file of files) {
    if (checkCurrent(file.path) !== file.hash) {
      atomicWrite(realRoot, file.path, sources.get(file.path), marker.transaction, resume);
    }
  }
  for (const file of oldFiles) {
    if (!nextByPath.has(file.path) && checkCurrent(file.path) !== null) {
      fs.unlinkSync(outputPath(realRoot, file.path));
    }
  }
  if (readHash(INDEX) !== oldHash) fail('APPROVED_INDEX_CONFLICT', 'The generated index changed during publication.');
  if (oldHash !== desiredHash) atomicWrite(realRoot, INDEX, desiredBytes, marker.transaction, resume);
  if (readHash(PENDING) !== digest(markerBytes)) fail('APPROVED_PENDING_MISMATCH', 'The publication marker changed during publication.');
  fs.unlinkSync(outputPath(realRoot, PENDING));
  return { ...result, updated: true };
}

/** Read-only health of the derived folder; never repairs during a GET. */
export function approvedProjectionStatus(root, state, navigation = {}) {
  try {
    const realRoot=fs.realpathSync(root), saved=metadata(realRoot,INDEX);
    if (saved.value===null) return {consistent:false,error:'approved-projection-missing'};
    const files=validateIndex(saved.value,state), approved=approvedDeliverables(state,navigation,{strictNavigation:true});
    if (files.length!==approved.length) return {consistent:false,error:'approved-projection-lag'};
    for (const member of approved) {
      const expected=[...member.groups.map(g=>safeLabel(g.label)),filename(member.product_id,member.path)].join('/');
      const file=files.find(f=>f.step_id===member.step_id && f.product_id===member.product_id);
      if (!file || file.path!==expected || file.revision_id!==member.revision_id || file.hash!==member.hash ||
          file.presentation_id!==member.presentation_id || file.accepted_at!==member.accepted_at)
        return {consistent:false,error:'approved-projection-lag'};
      const bytes=outputBytes(realRoot,expected);
      if (bytes===null || digest(bytes)!==member.hash) return {consistent:false,error:'approved-projection-file-changed'};
    }
    if(metadata(realRoot,PENDING).bytes!==null) return {consistent:false,error:'approved-projection-interrupted'};
    return {consistent:true,count:files.length,folder:FOLDER};
  } catch(error) { return {consistent:false,error:error.code||'approved-projection-unreadable'}; }
}
