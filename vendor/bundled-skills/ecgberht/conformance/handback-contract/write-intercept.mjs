/**
 * Wave 21 — write-interception + S6 write-discipline probes (anti-stub law).
 *
 * Fixtures alone prove nothing: an adapter that returns canned handback files
 * without a real OS child process FAILS the write-interception clause by name.
 * Write-discipline additionally requires handback-before-marker order and
 * evidence of temp+fsync+rename (source and/or runtime write_trace).
 *
 * Stdlib only. No host-absolute paths in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(HERE, '..', '..');

/**
 * Relative writer sources the suite is allowed to treat as "real wrapper"
 * write paths (skill Node S6 + Anchor Python S6).
 */
export const REAL_WRITER_SOURCES = Object.freeze([
  'engine/durable-write.mjs',
  'engine/handback-contract.mjs',
  'commission_executor.py',
]);

/**
 * @param {string} sourceText
 * @returns {{ ok: boolean, has_temp: boolean, has_fsync: boolean, has_rename: boolean }}
 */
export function sourceShowsS6(sourceText) {
  const text = String(sourceText || '');
  const has_temp = /\.tmp|tmp-|temp\s*\+|with_name\(|openSync\(\s*tmp/i.test(text);
  const has_fsync = /fsyncSync|os\.fsync|fsync\s*\(/.test(text);
  const has_rename = /renameSync|os\.replace|rename\s*\(/.test(text);
  return {
    ok: has_temp && has_fsync && has_rename,
    has_temp,
    has_fsync,
    has_rename,
  };
}

/**
 * Load a real writer source by relative path under skill root or Anchor root.
 *
 * @param {string} rel
 * @param {{ skillRoot?: string, anchorRoot?: string|null }} [opts]
 * @returns {{ ok: true, path: string, text: string } | { ok: false, error: string }}
 */
export function loadWriterSource(rel, opts = {}) {
  const skillRoot = opts.skillRoot ?? SKILL_ROOT;
  const candidates = [];
  if (rel.endsWith('.py') && opts.anchorRoot) {
    candidates.push(path.join(opts.anchorRoot, rel));
  }
  candidates.push(path.join(skillRoot, rel));
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) {
        return { ok: true, path: p, text: fs.readFileSync(p, 'utf8') };
      }
    } catch {
      /* try next */
    }
  }
  return { ok: false, error: `writer_source_missing:${rel}` };
}

/**
 * Evaluate the write-interception (anti-stub) clause against a collect() result.
 *
 * @param {object} collect
 * @returns {{ ok: boolean, clause: 'write-interception', reason?: string }}
 */
export function evaluateWriteInterception(collect = {}) {
  if (collect.canned === true || collect.stub === true || collect.stub_adapter === true) {
    return {
      ok: false,
      clause: 'write-interception',
      reason:
        'adapter returned canned handback files without a real OS child — refused (anti-stub)',
    };
  }
  if (collect.spawned_child !== true) {
    return {
      ok: false,
      clause: 'write-interception',
      reason: 'collect.spawned_child !== true — suite cannot be greened by a stub',
    };
  }
  const pid = collect.child_pid ?? collect.pid;
  if (pid == null || !(Number(pid) > 0)) {
    return {
      ok: false,
      clause: 'write-interception',
      reason: 'no real child_pid observed — spawn did not produce an OS process',
    };
  }
  if (collect.wrote_via_canned_files === true) {
    return {
      ok: false,
      clause: 'write-interception',
      reason: 'adapter wrote files in-process without child (canned path)',
    };
  }
  return { ok: true, clause: 'write-interception' };
}

/**
 * Evaluate S6 write-discipline from collect + optional source probe.
 *
 * Injected drift: write_order with marker before handback, or
 * marker_before_handback_fsync: true, FAILS by name.
 *
 * @param {object} collect
 * @param {{ writerSourceText?: string }} [opts]
 * @returns {{ ok: boolean, clause: 'write-discipline', reason?: string, s6?: object }}
 */
export function evaluateWriteDiscipline(collect = {}, opts = {}) {
  if (collect.marker_before_handback_fsync === true) {
    return {
      ok: false,
      clause: 'write-discipline',
      reason:
        'marker written before handback fsync completed (injected drift) — S6 order violated',
    };
  }

  const order = Array.isArray(collect.write_order)
    ? collect.write_order.map(String)
    : null;
  if (order) {
    const hbIdx = order.findIndex((x) => /handback/i.test(x));
    const mkIdx = order.findIndex((x) => /marker|TERMINAL/i.test(x));
    if (hbIdx >= 0 && mkIdx >= 0 && mkIdx < hbIdx) {
      return {
        ok: false,
        clause: 'write-discipline',
        reason: `write_order has marker before handback: ${order.join(' → ')}`,
      };
    }
  }

  const sourceText =
    opts.writerSourceText ||
    collect.writer_source_text ||
    (Array.isArray(collect.write_trace)
      ? null
      : null);

  let s6 = null;
  if (typeof sourceText === 'string' && sourceText.length) {
    s6 = sourceShowsS6(sourceText);
    if (!s6.ok) {
      return {
        ok: false,
        clause: 'write-discipline',
        reason: 'writer source lacks temp+fsync+rename (S6)',
        s6,
      };
    }
  }

  const trace = Array.isArray(collect.write_trace) ? collect.write_trace : null;
  if (trace) {
    const ops = trace.map((t) => String(t?.op || t?.step || t).toLowerCase());
    const hasTemp = ops.some((o) => o.includes('temp') || o.includes('open'));
    const hasFsync = ops.some((o) => o.includes('fsync'));
    const hasRename = ops.some((o) => o.includes('rename') || o.includes('replace'));
    if (!(hasTemp && hasFsync && hasRename)) {
      return {
        ok: false,
        clause: 'write-discipline',
        reason: `write_trace missing S6 steps (temp/fsync/rename): ${ops.join(',')}`,
      };
    }
  }

  // Runtime cleanliness: complete pair with no leftover temps in handback dir
  if (collect.handback_dir && collect.complete_pair === true) {
    try {
      const names = fs.readdirSync(collect.handback_dir);
      const temps = names.filter((n) => n.includes('.tmp') || n.startsWith('.'));
      // allow hidden nothing; temp leftovers fail
      const bad = names.filter(
        (n) => n.includes('.tmp') || /\.tmp-/i.test(n),
      );
      if (bad.length) {
        return {
          ok: false,
          clause: 'write-discipline',
          reason: `temp strays left in handback dir: ${bad.join(',')}`,
        };
      }
      void temps;
    } catch {
      /* dir absent handled by other clauses */
    }
  }

  if (!s6 && !trace && collect.s6_proven !== true && collect.used_real_writer !== true) {
    return {
      ok: false,
      clause: 'write-discipline',
      reason:
        'no S6 evidence (writer source, write_trace, or used_real_writer) — cannot prove write-discipline',
    };
  }

  return { ok: true, clause: 'write-discipline', s6: s6 || undefined };
}

/**
 * Probe skill + optional Anchor writer sources for S6.
 *
 * @param {{ skillRoot?: string, anchorRoot?: string|null, executor?: string }} [opts]
 */
export function probeRealWriterS6(opts = {}) {
  const skillRoot = opts.skillRoot ?? SKILL_ROOT;
  const results = [];
  const skillWriters = [
    'engine/durable-write.mjs',
    'engine/handback-contract.mjs',
  ];
  for (const rel of skillWriters) {
    const loaded = loadWriterSource(rel, { skillRoot });
    if (!loaded.ok) {
      results.push({ rel, ok: false, error: loaded.error });
      continue;
    }
    const s6 = sourceShowsS6(loaded.text);
    results.push({ rel, ok: s6.ok, ...s6 });
  }
  if (opts.executor === 'anchor' || opts.anchorRoot) {
    const loaded = loadWriterSource('commission_executor.py', {
      skillRoot,
      anchorRoot: opts.anchorRoot,
    });
    if (!loaded.ok) {
      results.push({ rel: 'commission_executor.py', ok: false, error: loaded.error });
    } else {
      const s6 = sourceShowsS6(loaded.text);
      results.push({ rel: 'commission_executor.py', ok: s6.ok, ...s6 });
    }
  }
  return {
    ok: results.every((r) => r.ok),
    results,
  };
}
