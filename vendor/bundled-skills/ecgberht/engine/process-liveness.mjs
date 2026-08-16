/**
 * Wave 13 — Process liveness by (pid, proc_create_time) with BATCHED probes
 * and TTL-cached results (never per-render — the June O(everything) lesson).
 *
 * Engine law: nothing under engine/ may import child_process. Full OS
 * tasklist/ps is a host/tool concern — inject `probeBatch(pids)` from the
 * host gate or mediator. In-process, we only use process.kill(pid, 0) and
 * optional /proc create-time (same shape as g4-verdict observeProcessIdentity).
 *
 * Stdlib only.
 */

import { observeProcessIdentity, observeProcCreateTime } from './g4-verdict.mjs';

/** Default cache TTL for batched probe results (ms). */
export const LIVENESS_PROBE_CACHE_TTL_MS = 2_000;

/**
 * Identity key — never pid alone.
 * @param {number|null|undefined} pid
 * @param {number|null|undefined} procCreateTime
 * @returns {string|null}
 */
export function processIdentityKey(pid, procCreateTime) {
  const p = pid == null ? null : Number(pid);
  const c =
    procCreateTime == null || procCreateTime === ''
      ? null
      : Number(procCreateTime);
  if (p == null || !Number.isFinite(p) || p <= 0) return null;
  if (c == null || !Number.isFinite(c)) return `pid:${p}:ct:unknown`;
  return `pid:${p}:ct:${c}`;
}

/**
 * In-process single-identity observation (no spawn).
 * @param {number|null|undefined} pid
 * @param {number|null|undefined} procCreateTime
 */
export function observeIdentity(pid, procCreateTime) {
  return observeProcessIdentity(pid, procCreateTime);
}

/**
 * TTL-cached batched liveness probe.
 *
 * @param {{
 *   cacheTtlMs?: number,
 *   nowMs?: () => number,
 *   probeBatch?: (pids: number[]) => Map<number, { live: boolean, proc_create_time?: number|null }>|Record<number, object>,
 * }} [opts]
 */
export function createLivenessProbeCache(opts = {}) {
  const cacheTtlMs = Number(opts.cacheTtlMs ?? LIVENESS_PROBE_CACHE_TTL_MS);
  const nowMs =
    typeof opts.nowMs === 'function' ? opts.nowMs : () => Date.now();
  /** @type {Map<string, { expires: number, result: object }>} */
  const cache = new Map();
  let batchCalls = 0;
  let probeCalls = 0;

  const defaultProbeBatch = (pids) => {
    const out = new Map();
    for (const pid of pids) {
      let live = false;
      try {
        process.kill(pid, 0);
        live = true;
      } catch (e) {
        const code = e && (e.code || e.errno);
        live = code === 'EPERM';
      }
      const ct = live ? observeProcCreateTime(pid) : null;
      out.set(pid, { live, proc_create_time: ct });
    }
    return out;
  };

  const probeBatch =
    typeof opts.probeBatch === 'function' ? opts.probeBatch : defaultProbeBatch;

  /**
   * Resolve many identities in ONE batch (cache-aware).
   * @param {Array<{ pid: number, proc_create_time?: number|null }>} identities
   * @returns {Array<{ pid: number, proc_create_time: number|null, status: string, cached: boolean, key: string|null }>}
   */
  function probeMany(identities) {
    probeCalls += 1;
    const list = Array.isArray(identities) ? identities : [];
    const now = nowMs();
    const need = [];
    const results = new Array(list.length);

    for (let i = 0; i < list.length; i += 1) {
      const id = list[i] || {};
      const key = processIdentityKey(id.pid, id.proc_create_time);
      const hit = key ? cache.get(key) : null;
      if (hit && hit.expires > now) {
        results[i] = { ...hit.result, cached: true, key };
      } else {
        need.push(i);
      }
    }

    if (need.length > 0) {
      batchCalls += 1;
      const pids = [
        ...new Set(
          need
            .map((i) => Number(list[i].pid))
            .filter((p) => Number.isFinite(p) && p > 0),
        ),
      ];
      const raw = probeBatch(pids);
      const map =
        raw instanceof Map
          ? raw
          : new Map(
              Object.entries(raw || {}).map(([k, v]) => [Number(k), v]),
            );

      for (const i of need) {
        const id = list[i] || {};
        const pid = Number(id.pid);
        const wantCt =
          id.proc_create_time == null || id.proc_create_time === ''
            ? null
            : Number(id.proc_create_time);
        const obs = map.get(pid);
        let status;
        if (!obs || obs.live !== true) {
          status = 'dead';
        } else if (wantCt == null || !Number.isFinite(wantCt)) {
          status = 'unknown';
        } else if (
          obs.proc_create_time != null &&
          Number.isFinite(Number(obs.proc_create_time)) &&
          Math.abs(Number(obs.proc_create_time) - wantCt) > 1.5
        ) {
          status = 'dead'; // pid reuse
        } else if (
          obs.proc_create_time == null &&
          // live but create-time unreadable
          true
        ) {
          // Prefer identity helper when batch didn't return create-time
          const full = observeProcessIdentity(pid, wantCt);
          status = full.status;
        } else {
          status = 'alive';
        }
        const result = {
          pid: Number.isFinite(pid) ? pid : null,
          proc_create_time: wantCt,
          status,
          cached: false,
          key: processIdentityKey(pid, wantCt),
        };
        results[i] = result;
        if (result.key) {
          cache.set(result.key, {
            expires: now + cacheTtlMs,
            result: {
              pid: result.pid,
              proc_create_time: result.proc_create_time,
              status: result.status,
            },
          });
        }
      }
    }

    return results;
  }

  /**
   * Single identity — always goes through the batch path (never per-render spawn).
   * @param {number} pid
   * @param {number|null|undefined} procCreateTime
   */
  function probeOne(pid, procCreateTime) {
    return probeMany([{ pid, proc_create_time: procCreateTime }])[0];
  }

  function stats() {
    return {
      batch_calls: batchCalls,
      probe_calls: probeCalls,
      cache_size: cache.size,
      cache_ttl_ms: cacheTtlMs,
    };
  }

  function clear() {
    cache.clear();
  }

  return {
    probeMany,
    probeOne,
    stats,
    clear,
    cacheTtlMs,
  };
}

/**
 * Removal-proof: source must not spawn tasklist/ps per render.
 * @param {string} sourceText
 */
export function assertNoPerRenderTasklist(sourceText) {
  const bad = [];
  // Per-render anti-pattern: tasklist/ps inside a tight loop without cache
  if (/for\s*\([^)]*\)\s*\{[^}]*tasklist/i.test(sourceText)) {
    bad.push('tasklist-inside-for');
  }
  if (/for\s*\([^)]*\)\s*\{[^}]*\bps\s+-/.test(sourceText)) {
    bad.push('ps-inside-for');
  }
  return { ok: bad.length === 0, bad };
}

// Re-export create-time helper for hosts that already observed it.
export { observeProcCreateTime, observeProcessIdentity };
