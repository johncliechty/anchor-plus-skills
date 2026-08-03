// lifecycle-launch.mjs — cf-slick Wave B (journal 0027).
//
// Prefer host-owned long runs over naked `Start-Process -WindowStyle Hidden`
// which drops the parent Job and kills mid-await Stage-1 (orphan grok).
// This module documents + helpers for safe launch; run-live already uses
// proc-guard for children.

import { spawn } from 'node:child_process';
import path from 'node:path';

/**
 * Classify a child exit for journaling (transport vs content).
 * @param {{code?:number|null, signal?:string|null, timedOut?:boolean, error?:Error|null}} r
 * @returns {'ok'|'transport_timeout'|'transport_signal'|'transport_spawn'|'content_nonzero'|'unknown'}
 */
export function classifyAgentExit(r = {}) {
  if (r.timedOut) return 'transport_timeout';
  if (r.error && /ENOENT|spawn/i.test(String(r.error.message || r.error))) return 'transport_spawn';
  if (r.signal) return 'transport_signal';
  if (r.code === 0 || r.code === null || r.code === undefined) return 'ok';
  if (typeof r.code === 'number' && r.code !== 0) return 'content_nonzero';
  return 'unknown';
}

/**
 * Spawn a long-lived node engine under THIS process tree (not detached hidden).
 * Caller must keep the parent process alive for the duration (tool background
 * or interactive). windowsHide avoids focus steal without detaching.
 *
 * @param {string} engineAbs  absolute path to run-live.mjs / self-run.mjs
 * @param {string[]} args
 * @param {{cwd?:string, env?:object, log?:Function}} [opts]
 * @returns {import('node:child_process').ChildProcess}
 */
export function spawnEngineOwned(engineAbs, args = [], opts = {}) {
  const log = opts.log || (() => {});
  const cwd = opts.cwd || process.cwd();
  const child = spawn(process.execPath, [engineAbs, ...args], {
    cwd,
    env: { ...process.env, ...(opts.env || {}), CRUCIBLE_AGENT_LIVE: process.env.CRUCIBLE_AGENT_LIVE || '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    detached: false, // journal 0027: detached hidden parents die mid-await
  });
  log(`lifecycle-launch: spawned pid=${child.pid} engine=${path.basename(engineAbs)} detached=false`);
  return child;
}

/**
 * Whether a prior exit class is worth a single automatic retry.
 * @param {string} exitClass  from classifyAgentExit
 */
export function shouldRetryTransport(exitClass) {
  return exitClass === 'transport_timeout' || exitClass === 'transport_signal' || exitClass === 'transport_spawn';
}
