#!/usr/bin/env node
// bin/tidy-idy.mjs — Wave 5: `tidy-idy <folder>`, the tool's own launch.
//
// THE single canonical entry point, reachable two ways and identical both:
//
//   a terminal / cowork:  node bin/tidy-idy.mjs /path/to/anything
//   Anchor's button:      job_runner dispatches exactly this argv
//
// It runs on ANY folder — an Anchor project or a plain directory Anchor has
// never heard of — and involves no Anchor process on the standalone path.
//
// STDOUT DISCIPLINE (this is a safety property, not formatting). Under `--json`
// this process is being run headless by job_runner, which streams its stdout
// into a DURABLE LOG FILE. So under `--json` it prints the panel's BASE url and
// the path of the 0600 bootstrap file — never the single-use bootstrap URL, and
// never, on any path, the capability token. The nonce reaches the opener through
// that 0600 file, which the server unlinks on redemption.

import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { tidyIdy, LAUNCH_STATUS } from '../engine/launch/launch.mjs';
import { ENVIRONMENT } from '../engine/launch/opener.mjs';
import { PANEL_READY_EVENT } from '../engine/launch/anchor-caller.mjs';

/** Canonical operator usage — also the source of truth for SKILL.md / SC5. */
export const USAGE = `tidy-idy <folder> [options]

  Runs a hygiene pass over <folder> and opens its Triage Panel.
  Works on any folder: an Anchor project, or a plain directory outside Anchor.

  --no-open                 run and serve the panel, but do not open a browser
  --no-serve                run and archive only; no panel server, lock released
  --json                    machine output (used by Anchor's thin caller)
  --environment=<env>       standalone (default) | anchor | none
  --nonce-file=<path>       write the single-use bootstrap URL to this 0600 file
  --port=<n>                bind the panel to this loopback port (default: free)
  --mode=<mode>             north-star | heuristic | advisory (default: detected)
  --idle-timeout=<seconds>  close the panel and release the lock after this long
  --no-cost-gate            skip the pre-scan cost gate (full scope)
  --no-verdict-cache        do not read or write the content-hash verdict cache
  --help
`;

export function parseArgs(argv) {
  const opts = {
    rootPath: null,
    open: true,
    serve: true,
    json: false,
    environment: ENVIRONMENT.STANDALONE,
    nonceFile: null,
    port: 0,
    mode: null,
    idleTimeoutMs: null,
    costGateEnabled: true,
    verdictCacheEnabled: true,
    help: false,
  };
  for (const raw of argv) {
    const arg = String(raw);
    if (arg === '--help' || arg === '-h') { opts.help = true; continue; }
    if (arg === '--no-open') { opts.open = false; continue; }
    if (arg === '--no-serve') { opts.serve = false; continue; }
    if (arg === '--json') { opts.json = true; continue; }
    if (arg === '--no-cost-gate') { opts.costGateEnabled = false; continue; }
    if (arg === '--no-verdict-cache') { opts.verdictCacheEnabled = false; continue; }
    const kv = /^--([a-z-]+)=(.*)$/.exec(arg);
    if (kv) {
      const [, key, value] = kv;
      if (key === 'environment') opts.environment = value;
      else if (key === 'nonce-file') opts.nonceFile = value;
      else if (key === 'port') opts.port = Number.parseInt(value, 10) || 0;
      else if (key === 'mode') opts.mode = value;
      else if (key === 'idle-timeout') opts.idleTimeoutMs = Math.max(1, Number.parseInt(value, 10) || 0) * 1000;
      else throw new Error(`unknown option --${key}`);
      continue;
    }
    if (arg.startsWith('-')) throw new Error(`unknown option ${arg}`);
    if (opts.rootPath === null) opts.rootPath = arg;
    else throw new Error(`tidy-idy takes ONE folder; got a second argument '${arg}' — one run, one project root`);
  }
  return opts;
}

/**
 * The CLI body, as a function so tests can drive it without spawning a process.
 *
 * @param {string[]} argv
 * @param {{stdout?: object, stderr?: object, launch?: Function}} io
 */
export async function main(argv, io = {}) {
  const stdout = io.stdout || process.stdout;
  const stderr = io.stderr || process.stderr;
  const launch = io.launch || tidyIdy;

  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    stderr.write(`${err.message}\n\n${USAGE}`);
    return 2;
  }
  if (opts.help || !opts.rootPath) {
    stdout.write(USAGE);
    return opts.help ? 0 : 2;
  }

  const root = path.resolve(opts.rootPath);
  const log = (m) => stderr.write(`${m}\n`);

  const result = await launch({
    rootPath: root,
    environment: opts.environment,
    open: opts.open,
    serve: opts.serve,
    port: opts.port,
    // Under --json the bootstrap URL must NOT reach stdout (see the header), so a
    // 0600 nonce file is mandatory there — auto-allocated when none was passed.
    nonceFile: opts.nonceFile || (opts.json && opts.serve ? true : null),
    ...(opts.mode ? { mode: opts.mode } : {}),
    ...(opts.idleTimeoutMs ? { idleTimeoutMs: opts.idleTimeoutMs } : {}),
    costGateEnabled: opts.costGateEnabled,
    verdictCacheEnabled: opts.verdictCacheEnabled,
    log,
    // Stream early events (status-ready) to stdout under --json so job_runner
    // logs them before the long pipeline finishes.
    onEvent: opts.json
      ? (ev) => { try { stdout.write(`${JSON.stringify(ev)}\n`); } catch { /* ignore */ } }
      : null,
  });

  if (result.status === LAUNCH_STATUS.REFUSED) {
    if (opts.json) stdout.write(`${JSON.stringify({ event: 'refused', code: result.code, message: result.message, holder: result.holder || null })}\n`);
    stderr.write(`tidy-idy REFUSED: ${result.message}\n`);
    return 3;
  }

  // Second click while a run is live: hand back status/panel URLs; do not fail.
  if (result.status === LAUNCH_STATUS.ALREADY_RUNNING) {
    if (opts.json) {
      stdout.write(`${JSON.stringify({
        event: 'already-running',
        code: result.code,
        message: result.message,
        statusUrl: result.statusUrl || null,
        openUrl: result.openUrl || null,
        panelBaseUrl: result.panelBaseUrl || null,
        phase: result.phase || null,
        project: result.identity || null,
      })}\n`);
    } else {
      stderr.write(`tidy-idy: a run is already in progress for this folder.\n`);
      if (result.statusUrl) stdout.write(`status: ${result.statusUrl}\n`);
      if (result.openUrl) stdout.write(`open:   ${result.openUrl}\n`);
    }
    // Standalone re-click: open the existing status/panel page.
    if (opts.open && result.openUrl && opts.environment !== ENVIRONMENT.ANCHOR) {
      try {
        const { openPanel, panelLaunchSpec } = await import('../engine/launch/opener.mjs');
        await openPanel({
          spec: panelLaunchSpec({
            url: result.openUrl,
            identity: result.identity || { name: path.basename(root), path: root },
          }),
          environment: ENVIRONMENT.STANDALONE,
          log: () => {},
        });
      } catch { /* best-effort */ }
    }
    return 0;
  }

  const env = result.envelope;
  if (opts.json) {
    // status-ready is emitted early via onEvent when the status server starts.
    // Re-emit only if that path was skipped (no status server).
    if (result.statusUrl && !result.statusServer) {
      stdout.write(`${JSON.stringify({
        event: 'status-ready',
        statusUrl: result.statusUrl,
        project: { name: result.identity.name, path: result.identity.path },
      })}\n`);
    }
    stdout.write(`${JSON.stringify({
      event: 'run-complete',
      runId: env.runId,
      runNumber: result.runNumber,
      status: env.status,
      isClean: env.isClean,
      findings: (env.findings || []).length,
      archiveDir: result.archive.dir,
      costGated: Boolean(result.costGate && result.costGate.gated),
      project: { name: result.identity.name, path: result.identity.path },
      statusUrl: result.statusUrl || null,
    })}\n`);
    if (result.panel) {
      stdout.write(`${JSON.stringify({
        event: PANEL_READY_EVENT,
        url: result.panel.url,
        // The path, never the URL: job_runner persists this stream to disk.
        bootstrapFile: result.panel.nonceFile,
        runId: result.panel.runId,
        statusUrl: result.statusUrl || null,
        note: 'the single-use bootstrap URL is in the 0600 file above and is unlinked on redemption; the capability token is in server memory only',
      })}\n`);
    }
  } else {
    stdout.write(`${result.identity.label}\n`);
    stdout.write(`run ${result.runNumber} · ${env.runId} · status ${String(env.status).toUpperCase()} · ${(env.findings || []).length} finding(s)\n`);
    if (!env.isClean) for (const b of env.cleanBlockers || []) stdout.write(`  · ${b}\n`);
    if (result.costGate && result.costGate.gated) stdout.write(`  ! ${result.costGate.banner.message}\n`);
    stdout.write(`report: ${result.archive.dir}\n`);
    if (result.statusUrl) stdout.write(`status: ${result.statusUrl}\n`);
    if (result.panel) {
      stdout.write(`panel:  ${result.panel.bootstrapUrl}\n`);
      stdout.write('        (single-use — the first request redeems it; close the tab or press "Close & release" to free the project lock)\n');
    }
  }

  return env.status === 'failed' ? 1 : 0;
}

const isDirectRun = process.argv[1]
  && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isDirectRun) {
  main(process.argv.slice(2))
    .then((code) => {
      // A SERVED panel keeps this process alive on purpose: the server owns the
      // project lock, and that lock must outlive this function for a later Apply
      // from the panel to be safe. The process exits when the server closes —
      // explicitly, on idle timeout, or on a heartbeat gap.
      const serving = code === 0 && !process.argv.includes('--no-serve');
      if (!serving) process.exit(code);
    })
    .catch((err) => {
      process.stderr.write(`tidy-idy failed: ${err && err.stack ? err.stack : err}\n`);
      process.exit(1);
    });
}
