/**
 * W16 - steward-bundle-v1: the off-box copy, and the health condition that it is old.
 *
 * WHY A BUNDLE AT ALL, GIVEN W15. W15 says a receipt whose intent is unacknowledged lives on
 * one disk and says so. It does not put a second copy anywhere - it cannot, because the side
 * that would do that ships from another repository. This wave is what an operator can do
 * about that TODAY, without a durability layer, without git, and without a network: package
 * the ONE store into a single file they can copy onto anything.
 *
 * WHAT GOES IN, AND WHY THE LIST IS SO SHORT. Exactly two things:
 *
 *   the LOG            - the whole live JSONL log, in full. It is the only member that is
 *                        AUTHORITATIVE, because it is the only thing in the index that is not
 *                        derived from something else. Membership events exist nowhere but
 *                        here (W7), so a bundle without the log is not a copy of the store.
 *
 *   the SNAPSHOT       - the current snapshot, carried as a labelled DERIVED cross-check copy
 *                        and NOTHING more. Its role is written into the manifest as such, and
 *                        restore refuses to install it. It rides along so that a restore can
 *                        PROVE the rebuild equation held rather than assert it: the body the
 *                        rebuilder recomputes from the restored log must hash to the body this
 *                        bundle recorded. That is the whole of its job.
 *
 * There is no third member. In particular there is no 'registry': the registry is a VIEW
 * materialized from NATIVE log events with no store of its own (W7), and packaging a view
 * would put a second, ageable copy of membership in the one artifact whose purpose is to be
 * trusted after everything else is gone.
 *
 * RESTORE IS REBUILD, and the bundled snapshot is never authoritative. restore-bundle unpacks
 * the LOG and chains `steward rebuild`. The alternative - dropping the bundled snapshot into
 * place because it is right there and already correct - is the single most tempting shortcut
 * in this wave and it is refused in code rather than in review: a snapshot installed without
 * being recomputed is a snapshot nobody has checked against its log, and the first time those
 * two disagree the disagreement is invisible.
 *
 * RESTORE NEVER OVERWRITES BYTES. Not the clobbering case, not the same-lineage case, not
 * ever. A live log that is AHEAD of the manifest's head, or whose head hash DIVERGES from the
 * lineage the bundle carries, is refused with RESTORE_WOULD_CLOBBER and the operator is told
 * to move the existing log aside by hand. A live log that is merely present and on the same
 * lineage is refused too - by its own named row, so the two situations are never confused -
 * because a restore that appends into somebody else's log is a merge, and a merge nobody
 * asked for is how two histories become one unreadable one. Moving a log aside is thirty
 * seconds of an operator's time; reconstructing one is not.
 *
 * 'LAST EXPORT' IS A HEALTH CONDITION. Every successful export appends a NATIVE
 * bundle-exported event, so recency is read from the log rather than from a directory listing
 * - a listing answers for whichever bundle happens still to be lying around, which is exactly
 * the wrong question. anchor-contract.mjs reads that recency and a DEGRADED portfolio with no
 * bundle newer than the degradation start escalates to the loudest rung there is: the case
 * where local disk is the only copy AND the only copy is old is not a notice.
 *
 * Stdlib only: node:fs, node:path and node:zlib. The bundle is a gzip stream over JSONL, so
 * any gunzip on any machine opens it, and a reader that has lost this engine entirely can
 * still read every byte it holds with `gunzip -c bundle | head -1`.
 */

import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

import {
  appendLineAt,
  appendEvents,
  ensureIndexHome,
  indexPathsFrom,
  logEventLine,
  readLogHead,
  withPortfolioLock,
} from '../append-log.mjs';
import { splitCanonicalText } from './canonical.mjs';
import { hashBytes } from './commit-intent.mjs';
import { INDEX_FILES } from './home.mjs';
import { logHeadSha256, rebuildIndex } from './rebuild.mjs';
import {
  EVENT_TYPE_FIELD,
  NATIVE_EVENT,
  makeBundleExportedEvent,
} from './registry.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The frozen artifact schema. A different member set means steward-bundle-v2. */
export const BUNDLE_SCHEMA = 'steward-bundle-v1';

/** This module's version, reported on every receipt. */
export const BUNDLE_VERSION = 'bundle-v1';

/**
 * The two verb names, spelled once. Every surface that mentions either reads them from here,
 * for the same reason rebuild.mjs names its own: a verb an operator is told to run must be
 * spelled the same way in the refusal that told them to run it.
 */
export const EXPORT_VERB = 'export-bundle';

/** @see EXPORT_VERB */
export const RESTORE_VERB = 'restore-bundle';

/** One day in milliseconds - the unit export recency is reported in. */
export const MS_PER_DAY = 86_400_000;

/**
 * What each contained file IS. The role is not decoration: restore branches on it, and the
 * DERIVED copy is refused as an input by name rather than by convention.
 */
export const MEMBER_ROLE = Object.freeze({
  LOG: 'LOG',
  DERIVED_CROSS_CHECK: 'DERIVED_CROSS_CHECK',
});

/**
 * The CLOSED member set. A bundle carrying anything else is refused on read rather than
 * partially trusted - an unexpected member is either a bundle from a version this engine
 * cannot honour or a file somebody added by hand, and both are answered the same way.
 */
export const BUNDLE_MEMBERS = Object.freeze([
  Object.freeze({
    path: INDEX_FILES.LOG,
    role: MEMBER_ROLE.LOG,
    authoritative: true,
    why: 'the append-only log: the only member nothing else can reproduce.',
  }),
  Object.freeze({
    path: INDEX_FILES.SNAPSHOT,
    role: MEMBER_ROLE.DERIVED_CROSS_CHECK,
    authoritative: false,
    why:
      'a labelled DERIVED copy, carried so a restore can prove the rebuild equation held. It '
      + 'is never installed and never read as input.',
  }),
]);

/** The one member restore may ever write. Stated as data so the test can enumerate it. */
export const RESTORE_WRITES = Object.freeze([MEMBER_ROLE.LOG]);

/** The outcomes both verbs report. Every one is a named row, never a thrown surprise. */
export const BUNDLE_CODE = Object.freeze({
  EXPORT_OK: 'BUNDLE_EXPORT_OK',
  EXPORT_TARGET_MISSING: 'BUNDLE_EXPORT_TARGET_MISSING',
  EXPORT_TARGET_EXISTS: 'BUNDLE_EXPORT_TARGET_EXISTS',
  EXPORT_TARGET_UNWRITABLE: 'BUNDLE_EXPORT_TARGET_UNWRITABLE',
  EXPORT_INDEX_UNREADABLE: 'BUNDLE_EXPORT_INDEX_UNREADABLE',
  EXPORT_EVENT_APPEND_FAILED: 'BUNDLE_EXPORT_EVENT_APPEND_FAILED',
  RESTORE_OK: 'BUNDLE_RESTORE_OK',
  RESTORE_SOURCE_UNREADABLE: 'BUNDLE_RESTORE_SOURCE_UNREADABLE',
  RESTORE_MANIFEST_MISMATCH: 'BUNDLE_RESTORE_MANIFEST_MISMATCH',
  RESTORE_WOULD_CLOBBER: 'RESTORE_WOULD_CLOBBER',
  RESTORE_LOG_PRESENT: 'BUNDLE_RESTORE_LOG_PRESENT',
  RESTORE_WRITE_FAILED: 'BUNDLE_RESTORE_WRITE_FAILED',
  RESTORE_EQUATION_MISMATCH: 'BUNDLE_RESTORE_EQUATION_MISMATCH',
  RESTORE_REBUILD_FAILED: 'BUNDLE_RESTORE_REBUILD_FAILED',
});

/**
 * The user-visible sentence per row. Read, never composed at the call site - a refusal whose
 * wording is assembled where it is raised is a refusal that says something slightly different
 * on each surface.
 */
export const BUNDLE_ROWS = Object.freeze({
  [BUNDLE_CODE.EXPORT_OK]: {
    status: INTEGRITY.OK,
    text:
      '{schema} written to {target}: the log to head {head_seq} plus a derived cross-check '
      + 'copy of the snapshot, {byte_len} bytes compressed.',
  },
  [BUNDLE_CODE.EXPORT_TARGET_MISSING]: {
    status: FRESHNESS.UNKNOWN,
    text:
      `${EXPORT_VERB} needs a target path to write to. No default is composed: a bundle written `
      + 'somewhere the operator did not name is an off-box copy nobody knows the location of.',
  },
  [BUNDLE_CODE.EXPORT_TARGET_EXISTS]: {
    // A presence code, not an integrity one: nothing is damaged, there is simply already a
    // file living where this one was asked to go.
    status: PRESENCE.LIVE,
    text:
      'a file already exists at {target}, and export refuses to replace it. An earlier bundle '
      + 'is somebody\'s only copy until they say otherwise; choose another name or move that '
      + 'one aside.',
  },
  [BUNDLE_CODE.EXPORT_TARGET_UNWRITABLE]: {
    status: PRESENCE.UNREACHABLE,
    text: 'the bundle could not be written to {target} ({errno}). Nothing was recorded as exported.',
  },
  [BUNDLE_CODE.EXPORT_INDEX_UNREADABLE]: {
    status: FRESHNESS.UNKNOWN,
    text:
      'the index could not be read, so there is nothing to package ({reason}). No bundle was '
      + 'written and no export was recorded.',
  },
  [BUNDLE_CODE.EXPORT_EVENT_APPEND_FAILED]: {
    status: INTEGRITY.TORN,
    text:
      'the bundle at {target} is on disk and complete, but the {event} event recording it could '
      + 'not be appended ({reason}). The copy exists; this log does not know about it, so '
      + 'export recency will still read as though it were never taken.',
  },
  [BUNDLE_CODE.RESTORE_OK]: {
    status: INTEGRITY.OK,
    text:
      'the log was restored from {source} to head {head_seq} and rebuilt. The rebuilt body '
      + 'hashes to {body_sha256}, which is what the manifest recorded - the rebuild equation '
      + 'held, and the bundled snapshot was never treated as input.',
  },
  [BUNDLE_CODE.RESTORE_SOURCE_UNREADABLE]: {
    status: INTEGRITY.UNPARSEABLE,
    text: 'the bundle at {source} could not be read as a {schema} ({reason}). Nothing was written.',
  },
  [BUNDLE_CODE.RESTORE_MANIFEST_MISMATCH]: {
    status: INTEGRITY.TAMPERED,
    text:
      'the bundle at {source} does not match its own manifest ({reason}). It is refused whole '
      + 'rather than unpacked in part: a bundle whose integrity line disagrees with its bytes '
      + 'cannot say which of the two is wrong. Nothing was written.',
  },
  [BUNDLE_CODE.RESTORE_WOULD_CLOBBER]: {
    status: INTEGRITY.TAMPERED,
    text:
      'refusing to restore over the live log at {log}: {why}. Not one byte was written. Move '
      + 'the existing log aside by hand (rename it, do not delete it - it is a source of truth '
      + `this bundle does not contain) and run ${RESTORE_VERB} again against an empty index home.`,
  },
  [BUNDLE_CODE.RESTORE_LOG_PRESENT]: {
    status: FRESHNESS.STALE,
    text:
      'a live log is already present at {log} (head {live_head}, on the same lineage as this '
      + 'bundle\'s head {head_seq}). Nothing was written: restoring into an existing log would '
      + 'be a merge, and this verb replaces a lost log rather than merging two. Move the '
      + `existing log aside by hand and run ${RESTORE_VERB} again.`,
  },
  [BUNDLE_CODE.RESTORE_WRITE_FAILED]: {
    status: INTEGRITY.TORN,
    text:
      'the restore stopped after {written} of {total} lines ({reason}). The lines already '
      + 'written are durable and in order; the log is short of the bundle\'s head and must be '
      + 'moved aside before another attempt.',
  },
  [BUNDLE_CODE.RESTORE_EQUATION_MISMATCH]: {
    status: INTEGRITY.TAMPERED,
    text:
      'the log was restored, but the rebuilt body hashes to {rebuilt} where the manifest '
      + 'recorded {expected}. The bundled snapshot is NOT installed to paper over that - the '
      + 'two disagree, and which of them is right is a question about the roots on this machine '
      + 'rather than about these bytes.',
  },
  [BUNDLE_CODE.RESTORE_REBUILD_FAILED]: {
    status: FRESHNESS.UNKNOWN,
    text:
      'the log was restored but the rebuild that follows it did not complete ({reason}), so the '
      + 'equation is unproven. The restored log is intact; run rebuild again once the reason is '
      + 'addressed.',
  },
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) => (
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole
  ));
}

/**
 * One outcome, worded from the frozen row.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function bundleOutcome(code, params = {}, extra = {}) {
  const row = BUNDLE_ROWS[code];
  if (row === undefined) throw new Error(`bundle: ${code} is not a frozen row`);
  return Object.freeze({
    ok: code === BUNDLE_CODE.EXPORT_OK || code === BUNDLE_CODE.RESTORE_OK,
    code,
    status: assertStatusCode(row.status, `bundle row ${code}`),
    text: fill(row.text, { schema: BUNDLE_SCHEMA, ...params }),
    version: BUNDLE_VERSION,
    ...extra,
  });
}

// -- the framing ----------------------------------------------------------------

/** @param {unknown} value @returns {string} one JSONL line, LF-terminated */
function line(value) {
  const json = JSON.stringify(value);
  if (json.includes('\n') || json.includes('\r')) {
    throw new Error('bundle: a framed line carries a raw newline');
  }
  return `${json}\n`;
}

/**
 * The sha256 of the manifest LINE, exactly as it sits in the stream - trailing LF included.
 *
 * The line rather than the object, because the line is what a reader has: anybody with gunzip
 * can take the first line of a bundle, hash it, and compare it with the number the log
 * recorded, without knowing anything about how this engine serializes objects.
 *
 * @param {string} manifestLine @returns {string}
 */
export function manifestHashOf(manifestLine) {
  return hashBytes(Buffer.from(String(manifestLine), 'utf8'));
}

/**
 * The body region hash of a canonical snapshot document.
 *
 * D-2 is why this is the BODY and not the file: two snapshots of one logical state, computed
 * at different wall-clock times, differ inside the freshness block and nowhere else. Hashing
 * the file would make the equation check fail on a `computed_at` that is SUPPOSED to differ,
 * and an assertion that fails when nothing is wrong is an assertion somebody switches off.
 *
 * @param {string|Buffer} text @returns {string|null} null when the text is not a snapshot
 */
export function snapshotBodySha256(text) {
  try {
    const split = splitCanonicalText(Buffer.isBuffer(text) ? text.toString('utf8') : String(text));
    return hashBytes(Buffer.from(split.body_text, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Pack the two members into the frozen stream.
 *
 * @param {{log_bytes: Buffer, snapshot_bytes?: Buffer|null, head_seq: number,
 *          head_sha256: string|null, created_at?: string}} parts
 * @returns {Readonly<{bytes: Buffer, text: string, manifest: object, manifest_line: string,
 *          manifest_sha256: string, byte_len: number}>}
 */
export function packBundle(parts) {
  const logBytes = Buffer.isBuffer(parts.log_bytes) ? parts.log_bytes : Buffer.from('', 'utf8');
  const derived = Buffer.isBuffer(parts.snapshot_bytes) ? parts.snapshot_bytes : null;

  const members = [
    { path: INDEX_FILES.LOG, role: MEMBER_ROLE.LOG, bytes: logBytes },
  ];
  if (derived !== null) {
    members.push({ path: INDEX_FILES.SNAPSHOT, role: MEMBER_ROLE.DERIVED_CROSS_CHECK, bytes: derived });
  }

  const files = members.map((m) => Object.freeze({
    path: m.path,
    role: m.role,
    sha256: hashBytes(m.bytes),
    byte_len: m.bytes.length,
  }));

  const manifest = {
    schema: BUNDLE_SCHEMA,
    created_at: String(parts.created_at ?? new Date().toISOString()),
    // The log head, which is what the clobber guard compares against and what makes a bundle
    // placeable in the history of the store it came from.
    log_head_seq: Number(parts.head_seq ?? 0),
    log_head_sha256: parts.head_sha256 ?? null,
    // The DERIVED member's body hash: the equation's expected answer, recorded by the side
    // that had a correct snapshot in hand.
    snapshot_body_sha256: derived === null ? null : snapshotBodySha256(derived),
    files,
  };

  const manifestLine = line(manifest);
  const text = manifestLine + members.map((m) => line({
    path: m.path,
    role: m.role,
    sha256: hashBytes(m.bytes),
    byte_len: m.bytes.length,
    b64: m.bytes.toString('base64'),
  })).join('');

  const bytes = zlib.gzipSync(Buffer.from(text, 'utf8'), { level: 9 });
  return Object.freeze({
    bytes,
    text,
    manifest: Object.freeze(manifest),
    manifest_line: manifestLine,
    manifest_sha256: manifestHashOf(manifestLine),
    byte_len: bytes.length,
  });
}

/**
 * Unpack and CHECK. Every problem found is reported; the caller refuses the bundle whole.
 *
 * @param {Buffer} bytes the gzip stream
 * @returns {Readonly<{ok: boolean, manifest: object|null, members: object|null,
 *          manifest_sha256: string|null, problems: ReadonlyArray<string>}>}
 */
export function readBundleBytes(bytes) {
  /** @type {string[]} */
  const problems = [];
  let text;
  try {
    text = zlib.gunzipSync(Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes)).toString('utf8');
  } catch (err) {
    return Object.freeze({
      ok: false,
      manifest: null,
      members: null,
      manifest_sha256: null,
      problems: Object.freeze([`the stream is not gzip (${err && err.code ? err.code : err.message})`]),
    });
  }

  const lines = text.split('\n').filter((l) => l !== '');
  if (lines.length === 0) {
    return Object.freeze({
      ok: false,
      manifest: null,
      members: null,
      manifest_sha256: null,
      problems: Object.freeze(['the stream carries no manifest line']),
    });
  }

  let manifest;
  try {
    manifest = JSON.parse(lines[0]);
  } catch (err) {
    return Object.freeze({
      ok: false,
      manifest: null,
      members: null,
      manifest_sha256: null,
      problems: Object.freeze([`line 1 is not the integrity manifest (${err.message})`]),
    });
  }
  if (manifest === null || typeof manifest !== 'object' || manifest.schema !== BUNDLE_SCHEMA) {
    return Object.freeze({
      ok: false,
      manifest: null,
      members: null,
      manifest_sha256: null,
      problems: Object.freeze([`line 1 declares ${JSON.stringify(manifest?.schema)}, not ${BUNDLE_SCHEMA}`]),
    });
  }

  /** @type {Record<string, {path: string, role: string, bytes: Buffer, sha256: string}>} */
  const members = {};
  for (let i = 1; i < lines.length; i += 1) {
    let record;
    try {
      record = JSON.parse(lines[i]);
    } catch (err) {
      problems.push(`line ${i + 1} is not a contained file (${err.message})`);
      continue;
    }
    const known = BUNDLE_MEMBERS.find((m) => m.path === record.path && m.role === record.role);
    if (known === undefined) {
      // The member set is CLOSED: an unexpected file is either a bundle this engine does not
      // understand or one somebody edited, and both are answered by refusing the whole.
      problems.push(
        `line ${i + 1} carries ${JSON.stringify(record.path)} as ${JSON.stringify(record.role)}, `
        + `which is not a ${BUNDLE_SCHEMA} member`,
      );
      continue;
    }
    const decoded = Buffer.from(String(record.b64 ?? ''), 'base64');
    const sha256 = hashBytes(decoded);
    if (sha256 !== record.sha256) {
      problems.push(`${record.path}: the bytes hash to ${sha256}, the line records ${record.sha256}`);
      continue;
    }
    if (decoded.length !== Number(record.byte_len)) {
      problems.push(
        `${record.path}: ${decoded.length} bytes decoded, the line records ${record.byte_len}`,
      );
      continue;
    }
    members[record.role] = { path: record.path, role: record.role, bytes: decoded, sha256 };
  }

  // The manifest's file list is the integrity claim; the lines are the bytes. Both directions
  // are checked, because a manifest naming a file that is absent and a stream carrying a file
  // the manifest never named are different damage with the same remedy.
  const listed = Array.isArray(manifest.files) ? manifest.files : [];
  for (const entry of listed) {
    const member = Object.values(members).find((m) => m.path === entry.path);
    if (member === undefined) {
      problems.push(`the manifest lists ${entry.path}, which the stream does not carry intact`);
      continue;
    }
    if (member.sha256 !== entry.sha256) {
      problems.push(
        `${entry.path}: the manifest records ${entry.sha256}, the contained bytes hash to ${member.sha256}`,
      );
    }
  }
  for (const member of Object.values(members)) {
    if (!listed.some((entry) => entry.path === member.path)) {
      problems.push(`the stream carries ${member.path}, which the manifest does not list`);
    }
  }
  if (members[MEMBER_ROLE.LOG] === undefined) {
    problems.push(`the bundle carries no ${MEMBER_ROLE.LOG} member, so it is not a copy of the store`);
  }

  return Object.freeze({
    ok: problems.length === 0,
    manifest: Object.freeze(manifest),
    members: Object.freeze(members),
    manifest_sha256: manifestHashOf(`${lines[0]}\n`),
    problems: Object.freeze(problems),
  });
}

// -- export ----------------------------------------------------------------------

/**
 * `steward export-bundle` - package EXACTLY the ONE store.
 *
 * The order of operations is the honest one and it is not negotiable: the log and the derived
 * copy are read under the portfolio lock (so the pair is a consistent instant rather than two
 * reads with an append between them), the bundle is made durable on disk, and only THEN is the
 * NATIVE event appended. An event written first would claim an off-box copy in exactly the
 * case where the write then failed.
 *
 * @param {{home?: string, paths?: object, env?: object, target?: string, now?: number|Date,
 *          fsx?: object, boundMs?: number, staleMs?: number, quarantine?: boolean,
 *          lockOpts?: object}} opts
 * @returns {Readonly<object>}
 */
export function exportBundle(opts = {}) {
  if (opts.target === undefined || opts.target === null || String(opts.target).trim() === '') {
    return bundleOutcome(BUNDLE_CODE.EXPORT_TARGET_MISSING, {}, { written: false });
  }
  const targetPath = path.resolve(String(opts.target));
  const paths = indexPathsFrom(opts);

  if (fs.existsSync(targetPath)) {
    return bundleOutcome(
      BUNDLE_CODE.EXPORT_TARGET_EXISTS,
      { target: targetPath },
      { target: targetPath, written: false },
    );
  }

  // The home is READ, never brought into existence: a home this verb created would hold an
  // empty log, and an empty bundle written from it would record an export in a log that has
  // nothing in it - a copy of nothing, dated today, quietening the recency banner.
  try {
    const stat = fs.statSync(paths.home);
    if (!stat.isDirectory()) throw Object.assign(new Error(paths.home), { code: 'ENOTDIR' });
  } catch (err) {
    return bundleOutcome(
      BUNDLE_CODE.EXPORT_INDEX_UNREADABLE,
      { reason: `${paths.home} (${err && err.code ? err.code : String(err.message ?? err)})` },
      { written: false },
    );
  }

  let packed;
  try {
    packed = withPortfolioLock(
      paths,
      () => {
        const head = readLogHead(paths.log, {
          fsx: opts.fsx,
          write: false,
          quarantine: opts.quarantine,
        });
        if (!head.ok) return { failed: head.outcome };

        let logBytes;
        try {
          // A copy of the store copies the bytes that are THERE, damage included: decoding
          // and re-encoding on the way past would silently repair - or silently mangle - the
          // very evidence an operator restores a bundle in order to inspect.
          // encoding-lint: raw-bytes
          logBytes = fs.existsSync(paths.log) ? fs.readFileSync(paths.log) : Buffer.from('', 'utf8');
        } catch (err) {
          return { failed: { code: String(err.code ?? ''), text: String(err.message ?? err) } };
        }

        let derivedBytes = null;
        try {
          // As above: the cross-check member is carried verbatim or not at all.
          // encoding-lint: raw-bytes
          const at = paths.snapshot;
          if (fs.existsSync(at)) derivedBytes = fs.readFileSync(at);
        } catch {
          derivedBytes = null;   // a snapshot that cannot be read is simply not carried
        }

        return {
          packed: packBundle({
            log_bytes: logBytes,
            snapshot_bytes: derivedBytes,
            head_seq: head.head_seq,
            head_sha256: logHeadSha256(head.events),
            created_at: new Date(opts.now ?? Date.now()).toISOString(),
          }),
          head_seq: head.head_seq,
          event_count: head.events.length,
        };
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    return bundleOutcome(
      BUNDLE_CODE.EXPORT_INDEX_UNREADABLE,
      { reason: String(err && err.message ? err.message : err) },
      { written: false },
    );
  }

  if (packed.failed !== undefined) {
    return bundleOutcome(
      BUNDLE_CODE.EXPORT_INDEX_UNREADABLE,
      { reason: packed.failed.text ? packed.failed.text : String(packed.failed.code) },
      { written: false, index_outcome: packed.failed },
    );
  }

  // 'wx' rather than a plain write: O_EXCL is what makes "export never replaces an existing
  // file" a property of the syscall instead of a property of the existsSync above, which
  // another process can invalidate between the check and the write.
  let fd;
  try {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fd = fs.openSync(targetPath, 'wx');
    fs.writeSync(fd, packed.packed.bytes, 0, packed.packed.bytes.length);
    try {
      fs.fsyncSync(fd);
    } catch {
      /* some filesystems refuse fsync; the bytes are still written */
    }
  } catch (err) {
    return bundleOutcome(
      err && err.code === 'EEXIST' ? BUNDLE_CODE.EXPORT_TARGET_EXISTS : BUNDLE_CODE.EXPORT_TARGET_UNWRITABLE,
      { target: targetPath, errno: err && err.code ? err.code : String(err.message ?? err) },
      { target: targetPath, written: false },
    );
  } finally {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
  }

  const event = makeBundleExportedEvent({
    target: targetPath,
    manifest_sha256: packed.packed.manifest_sha256,
    log_head_seq: packed.head_seq,
  });
  const appended = appendEvents([event], {
    ...opts,
    home: paths.home,
    paths,
    target: undefined,
  });
  if (appended.ok !== true) {
    return bundleOutcome(
      BUNDLE_CODE.EXPORT_EVENT_APPEND_FAILED,
      {
        target: targetPath,
        event: NATIVE_EVENT.BUNDLE_EXPORTED,
        reason: appended.text ? appended.text : String(appended.code),
      },
      {
        target: targetPath,
        written: true,
        manifest: packed.packed.manifest,
        manifest_sha256: packed.packed.manifest_sha256,
        head_seq: packed.head_seq,
        recorded: false,
        index_outcome: appended,
      },
    );
  }

  return bundleOutcome(
    BUNDLE_CODE.EXPORT_OK,
    {
      target: targetPath,
      head_seq: packed.head_seq,
      byte_len: packed.packed.byte_len,
    },
    {
      target: targetPath,
      written: true,
      recorded: true,
      manifest: packed.packed.manifest,
      manifest_sha256: packed.packed.manifest_sha256,
      head_seq: packed.head_seq,
      event_count: packed.event_count,
      byte_len: packed.packed.byte_len,
      files: packed.packed.manifest.files,
      event_seq: appended.seq,
      index_outcome: appended,
    },
  );
}

// -- restore ---------------------------------------------------------------------

/**
 * The hash of the bundled log's line at `seq`, or null when the bundle does not carry it.
 *
 * This is what makes the divergence half of the clobber guard answerable for a live log that
 * is BEHIND the manifest's head: same head number is not same history, and a log whose line 4
 * is a different line 4 is a different log however small its head is.
 *
 * The line is hashed through `logEventLine` - the primitive's own serializer - rather than as
 * the raw text it was read as, because the LIVE side of the comparison (`logHeadSha256`) hashes
 * a re-serialized event too. Two hashes of the same event must be computed the same way, or the
 * guard fires on a difference in whitespace and calls it a different history.
 *
 * @param {Buffer|string} logBytes @param {number} seq @returns {string|null}
 */
export function bundledLineHashAt(logBytes, seq) {
  const text = Buffer.isBuffer(logBytes) ? logBytes.toString('utf8') : String(logBytes);
  const wanted = Number(seq);
  for (const raw of text.split('\n')) {
    if (raw === '') continue;
    let value;
    try {
      value = JSON.parse(raw);
    } catch {
      continue;
    }
    if (Number(value?.seq) !== wanted) continue;
    try {
      return hashBytes(Buffer.from(logEventLine(value), 'utf8'));
    } catch {
      return null;   // a line this engine cannot re-serialize is a line it cannot vouch for
    }
  }
  return null;
}

/**
 * Decide whether restoring into this index home would destroy history. Pure, so the decision
 * can be tested without a filesystem and so the two verbs cannot word the rule apart.
 *
 * @param {{live_head: number, live_head_sha256: string|null, event_count: number}} live
 * @param {{head_seq: number, head_sha256: string|null, log_bytes: Buffer|string}} bundled
 * @returns {Readonly<{allowed: boolean, code: string|null, why: string}>}
 */
export function clobberVerdict(live, bundled) {
  if (Number(live.event_count ?? 0) === 0) {
    return Object.freeze({ allowed: true, code: null, why: 'the index home carries no live log' });
  }

  const liveHead = Number(live.live_head ?? 0);
  const bundleHead = Number(bundled.head_seq ?? 0);

  if (liveHead > bundleHead) {
    return Object.freeze({
      allowed: false,
      code: BUNDLE_CODE.RESTORE_WOULD_CLOBBER,
      why:
        `its head is sequence ${liveHead}, which is AHEAD of the ${bundleHead} this bundle `
        + `carries. ${liveHead - bundleHead} event(s) exist here that the bundle does not have, `
        + 'and they exist nowhere else',
    });
  }

  const atLive = bundledLineHashAt(bundled.log_bytes, liveHead);
  if (atLive === null || (live.live_head_sha256 !== null && atLive !== live.live_head_sha256)) {
    return Object.freeze({
      allowed: false,
      code: BUNDLE_CODE.RESTORE_WOULD_CLOBBER,
      why:
        `its head at sequence ${liveHead} hashes to ${live.live_head_sha256 ?? '(unreadable)'} `
        + `while this bundle records ${atLive ?? '(no such sequence)'} there. These are two `
        + 'different histories that happen to have reached the same number',
    });
  }

  return Object.freeze({
    allowed: false,
    code: BUNDLE_CODE.RESTORE_LOG_PRESENT,
    why: `it is on the same lineage as this bundle at sequence ${liveHead}`,
  });
}

/**
 * `steward restore-bundle` - unpack the LOG, then chain `steward rebuild`.
 *
 * The bundled snapshot is read for exactly one purpose: to know what the rebuilt body OUGHT to
 * hash to. It is never written, and RESTORE_WRITES says so as data.
 *
 * @param {{home?: string, paths?: object, env?: object, source?: string, rebuild?: boolean,
 *          fsx?: object, boundMs?: number, staleMs?: number, quarantine?: boolean,
 *          lockOpts?: object}} opts
 * @returns {Readonly<object>}
 */
export function restoreBundle(opts = {}) {
  const sourcePath = opts.source === undefined ? '' : path.resolve(String(opts.source));
  const paths = indexPathsFrom(opts);

  let raw;
  try {
    // A gzip stream is not text and never was.
    // encoding-lint: raw-bytes
    raw = fs.readFileSync(sourcePath);
  } catch (err) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_SOURCE_UNREADABLE,
      { source: sourcePath, reason: err && err.code ? err.code : String(err.message ?? err) },
      { source: sourcePath, wrote: Object.freeze([]), lines_written: 0 },
    );
  }

  const read = readBundleBytes(raw);
  if (read.manifest === null) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_SOURCE_UNREADABLE,
      { source: sourcePath, reason: read.problems.join('; ') },
      { source: sourcePath, wrote: Object.freeze([]), lines_written: 0, problems: read.problems },
    );
  }
  if (!read.ok) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_MANIFEST_MISMATCH,
      { source: sourcePath, reason: read.problems.join('; ') },
      {
        source: sourcePath,
        wrote: Object.freeze([]),
        lines_written: 0,
        manifest: read.manifest,
        problems: read.problems,
      },
    );
  }

  const logMember = read.members[MEMBER_ROLE.LOG];
  const bundledLines = logMember.bytes.toString('utf8').split('\n')
    .filter((l) => l !== '')
    .map((l) => `${l}\n`);

  const prepared = ensureIndexHome(paths, { fsx: opts.fsx });
  if (prepared.ok !== true) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_WRITE_FAILED,
      {
        written: 0,
        total: bundledLines.length,
        reason: prepared.text ? prepared.text : String(prepared.code),
      },
      { source: sourcePath, wrote: Object.freeze([]), lines_written: 0, index_outcome: prepared },
    );
  }

  let result;
  try {
    result = withPortfolioLock(
      paths,
      () => {
        const head = readLogHead(paths.log, {
          fsx: opts.fsx,
          write: true,
          quarantine: opts.quarantine,
        });
        // A live log this engine cannot even read is the strongest possible reason NOT to
        // write into it: unreadable is not empty.
        const verdict = head.ok
          ? clobberVerdict(
            {
              live_head: head.head_seq,
              live_head_sha256: logHeadSha256(head.events),
              event_count: head.events.length,
            },
            {
              head_seq: read.manifest.log_head_seq,
              head_sha256: read.manifest.log_head_sha256 ?? null,
              log_bytes: logMember.bytes,
            },
          )
          : Object.freeze({
            allowed: false,
            code: BUNDLE_CODE.RESTORE_WOULD_CLOBBER,
            why:
              'a log is present that this engine could not read '
              + `(${head.outcome?.text ?? head.outcome?.code ?? ''}), and bytes it cannot read `
              + 'are bytes it must not append to',
          });

        if (!verdict.allowed) {
          return { verdict, live_head: head.head_seq ?? 0, written: 0 };
        }

        let size = 0;
        for (let i = 0; i < bundledLines.length; i += 1) {
          const wrote = appendLineAt(paths.log, bundledLines[i], {
            expected_size: size,
            fsx: opts.fsx,
          });
          if (wrote.ok !== true) {
            return { verdict, live_head: head.head_seq ?? 0, written: i, failed: wrote };
          }
          size += wrote.bytes_written;
        }
        return { verdict, live_head: head.head_seq ?? 0, written: bundledLines.length };
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_WRITE_FAILED,
      { written: 0, total: bundledLines.length, reason: String(err && err.message ? err.message : err) },
      { source: sourcePath, wrote: Object.freeze([]), lines_written: 0 },
    );
  }

  if (!result.verdict.allowed) {
    return bundleOutcome(
      result.verdict.code,
      {
        log: paths.log,
        why: result.verdict.why,
        live_head: result.live_head,
        head_seq: read.manifest.log_head_seq,
      },
      {
        source: sourcePath,
        // The claim the test asserts: not one byte was written on this path.
        wrote: Object.freeze([]),
        lines_written: 0,
        live_head: result.live_head,
        manifest: read.manifest,
      },
    );
  }

  if (result.failed !== undefined) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_WRITE_FAILED,
      {
        written: result.written,
        total: bundledLines.length,
        reason: result.failed.text ? result.failed.text : String(result.failed.code),
      },
      {
        source: sourcePath,
        wrote: Object.freeze([MEMBER_ROLE.LOG]),
        lines_written: result.written,
        index_outcome: result.failed,
      },
    );
  }

  const expected = read.manifest.snapshot_body_sha256 ?? null;
  const common = {
    source: sourcePath,
    // Exactly one member was written, and it is the authoritative one. The DERIVED copy was
    // read for its hash and never installed.
    wrote: RESTORE_WRITES,
    lines_written: result.written,
    manifest: read.manifest,
    manifest_sha256: read.manifest_sha256,
    head_seq: read.manifest.log_head_seq,
    expected_body_sha256: expected,
  };

  if (opts.rebuild === false) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_OK,
      {
        source: sourcePath,
        head_seq: read.manifest.log_head_seq,
        body_sha256: `${expected ?? '(not carried)'} (rebuild not chained)`,
      },
      { ...common, rebuilt: null, equation_checked: false },
    );
  }

  const rebuilt = rebuildIndex({
    home: paths.home,
    paths,
    boundMs: opts.boundMs,
    staleMs: opts.staleMs,
    lockOpts: opts.lockOpts,
  });
  if (rebuilt.ok !== true) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_REBUILD_FAILED,
      { reason: rebuilt.outcome?.text ?? String(rebuilt.outcome?.code ?? '') },
      { ...common, rebuilt, equation_checked: false },
    );
  }

  const rebuiltBody = hashBytes(Buffer.from(String(rebuilt.body_text), 'utf8'));
  if (expected !== null && rebuiltBody !== expected) {
    return bundleOutcome(
      BUNDLE_CODE.RESTORE_EQUATION_MISMATCH,
      { rebuilt: rebuiltBody, expected },
      { ...common, rebuilt, rebuilt_body_sha256: rebuiltBody, equation_checked: true, equation_held: false },
    );
  }

  return bundleOutcome(
    BUNDLE_CODE.RESTORE_OK,
    {
      source: sourcePath,
      head_seq: read.manifest.log_head_seq,
      body_sha256: rebuiltBody,
    },
    {
      ...common,
      rebuilt,
      rebuilt_body_sha256: rebuiltBody,
      // `expected === null` is an honest "not checkable" rather than a pass: a bundle taken
      // when no snapshot existed carries no expected answer, and reporting that as a proven
      // equation would be the exact silence this wave exists to break.
      equation_checked: expected !== null,
      equation_held: expected !== null ? true : null,
    },
  );
}

// -- export recency, as a health input --------------------------------------------

/**
 * Every export this log records, in replay order.
 *
 * @param {Array<object>} events
 * @returns {ReadonlyArray<{seq: number, target: string, manifest_sha256: string,
 *          log_head_seq: number, written_at: string|null}>}
 */
export function bundleExportsIn(events = []) {
  const out = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (!event || typeof event !== 'object') continue;
    if (event[EVENT_TYPE_FIELD] !== NATIVE_EVENT.BUNDLE_EXPORTED) continue;
    out.push(Object.freeze({
      seq: Number(event.seq ?? 0),
      target: String(event.target ?? ''),
      manifest_sha256: String(event.manifest_sha256 ?? ''),
      log_head_seq: Number(event.log_head_seq ?? 0),
      written_at: event.written_at === undefined ? null : String(event.written_at),
    }));
  }
  return Object.freeze(out);
}

/**
 * How old the newest off-box copy is - and whether it is newer than a degradation that is
 * already running.
 *
 * `covers` is the question the banner escalates on, and it is asked in milliseconds rather
 * than in whole days: a bundle taken six hours after the degradation started covers it, and a
 * comparison in floored days would say both were "0 days" and call that a tie.
 *
 * @param {{events?: Array<object>, now?: number|Date, degraded_since?: number|Date|null}} [inputs]
 * @returns {Readonly<{ever: boolean, last_export_at: string|null, last_export_days: number|null,
 *          last_export_seq: number|null, target: string|null, covers: boolean|null,
 *          text: string}>}
 */
export function exportRecency(inputs = {}) {
  const nowMs = new Date(inputs.now ?? Date.now()).getTime();
  const exports_ = bundleExportsIn(inputs.events ?? []);
  // The NEWEST export is the one with the highest `seq`, not the last element handed in:
  // seq is the sole total order (NG-4), and a caller who assembled its events in some other
  // order would otherwise get an answer that quietly depends on array position.
  const latest = exports_.reduce(
    (best, entry) => (best === null || entry.seq > best.seq ? entry : best),
    /** @type {object|null} */ (null),
  );
  const since = inputs.degraded_since === null || inputs.degraded_since === undefined
    ? null
    : new Date(inputs.degraded_since).getTime();

  if (latest === null || latest.written_at === null) {
    return Object.freeze({
      ever: false,
      last_export_at: null,
      last_export_days: null,
      last_export_seq: null,
      target: null,
      covers: since === null ? null : false,
      text: 'last export-bundle: never',
    });
  }

  const at = Date.parse(latest.written_at);
  const days = Number.isFinite(at) ? Math.max(0, Math.floor((nowMs - at) / MS_PER_DAY)) : null;
  return Object.freeze({
    ever: true,
    last_export_at: latest.written_at,
    last_export_days: days,
    last_export_seq: latest.seq,
    target: latest.target,
    covers: since === null || !Number.isFinite(at) ? null : at > since,
    text: `last export-bundle: ${days === null ? 'never' : `${days} days ago`}`,
  });
}
