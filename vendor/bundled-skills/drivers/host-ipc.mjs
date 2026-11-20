// drivers/host-ipc.mjs — First-class Host-IPC model backend (`driver: 'host-ipc'`).
//
// Delegates sub-agent turns over an atomic filesystem IPC directory (default
// `<target>/.foreman/ipc` or `TRIO_HOST_IPC_DIR`) so an interactive host session
// (Antigravity, Claude Code, Codex, or Anchor steward) can fulfill seats directly
// with sub-agents without spawning nested CLI logins.
//
// Protocol:
//   1. Writer atomically writes `req-<id>.json.tmp-<pid>` and renames -> `req-<id>.json`.
//   2. Host worker may periodically touch/write `hb-<id>.json` (`{ at_ms }` or mtime)
//      to extend the per-request heartbeat lease (`heartbeatTimeoutMs`, default 180s).
//   3. Host worker atomically writes `resp-<id>.json.tmp` and renames -> `resp-<id>.json`
//      carrying `{ ok, text?, result?, model_family?, model_served?, model_attested?,
//      family_attested?, usage?, cost_usd?, duration_ms?, status?, error?, replay_safe? }`.
//   4. `defaultRunHostIpc` parses the response, emits full receipt accounting, and
//      removes request/heartbeat/response files unless `keepIpcFiles: true`.

import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { extractJson } from './claude.mjs';
import { normalizeRole } from './roles.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';

export const DEFAULT_HOST_IPC_TIMEOUT_MS = 30 * 60 * 1000;
export const DEFAULT_HOST_IPC_HEARTBEAT_TIMEOUT_MS = 180 * 1000;
export const DEFAULT_HOST_IPC_POLL_MS = 100;

function sleep(ms, signal = null) {
  return new Promise((resolve) => {
    if (signal?.aborted) { resolve(); return; }
    let timer = null;
    const onAbort = () => {
      if (timer) clearTimeout(timer);
      resolve();
    };
    timer = setTimeout(() => {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}

/** Write JSON atomically via temp file + rename in the same directory. */
export function writeJsonAtomic(filePath, payload) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${filePath}.tmp-${process.pid}-${randomUUID().slice(0, 8)}`;
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), 'utf8');
  fs.renameSync(tmpPath, filePath);
}

function readHeartbeatMs(hbPath) {
  try {
    const st = fs.statSync(hbPath);
    let ts = st.mtimeMs;
    try {
      const parsed = JSON.parse(fs.readFileSync(hbPath, 'utf8'));
      const explicit = Number(parsed?.at_ms ?? parsed?.updated_at_ms ?? Date.parse(parsed?.at || ''));
      if (Number.isFinite(explicit) && explicit > ts) ts = explicit;
    } catch { /* mtimeMs is authoritative fallback */ }
    return ts;
  } catch {
    return null;
  }
}

function safeUnlink(filePath) {
  if (!filePath) return;
  try { fs.rmSync(filePath, { force: true }); } catch { /* best effort */ }
}

/**
 * Execute one host-IPC request/response turn with atomic write-temp-then-rename,
 * per-request heartbeat lease + wall-clock timeout, and full receipt accounting.
 */
export async function defaultRunHostIpc(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  ipcDir = null,
  requestId = null,
  model = null,
  role = null,
  jsonSchema = null,
  repairOnly = false,
  timeoutMs = (Number(env.TRIO_HOST_IPC_TIMEOUT_MS) || DEFAULT_HOST_IPC_TIMEOUT_MS),
  heartbeatTimeoutMs = (Number(env.TRIO_HOST_IPC_HEARTBEAT_MS) || DEFAULT_HOST_IPC_HEARTBEAT_TIMEOUT_MS),
  pollIntervalMs = (Number(env.TRIO_HOST_IPC_POLL_MS) || DEFAULT_HOST_IPC_POLL_MS),
  keepIpcFiles = false,
  signal = null,
  log = () => {},
  now = Date.now,
} = {}) {
  const resolvedIpcDir = ipcDir
    || env.TRIO_HOST_IPC_DIR
    || path.join(target || process.cwd(), '.foreman', 'ipc');
  const id = String(requestId || randomUUID()).replace(/[^A-Za-z0-9._-]/g, '_');
  const reqPath = path.join(resolvedIpcDir, `req-${id}.json`);
  const respPath = path.join(resolvedIpcDir, `resp-${id}.json`);
  const hbPath = path.join(resolvedIpcDir, `hb-${id}.json`);

  const seatRole = normalizeRole({ role, label });
  const startedAtMs = Number(now());

  if (signal?.aborted) {
    return {
      text: '',
      rec: {
        label, ok: false, status: 'aborted', aborted: true,
        error: 'host-ipc seat aborted before request write',
        requested_model: model ?? null, model_served: null, model_family: null,
        family_attested: false, model_attested: false, degraded: true,
      },
    };
  }

  const requestPayload = {
    schema: 'trio.host-ipc.request.v1',
    id,
    created_at: new Date(startedAtMs).toISOString(),
    label,
    role: seatRole,
    requested_model: model ?? null,
    target: target || null,
    repair_only: repairOnly === true,
    json_schema: jsonSchema ?? null,
    prompt: String(fullPrompt ?? ''),
  };

  writeJsonAtomic(reqPath, requestPayload);
  let lastActivityMs = startedAtMs;

  try {
    while (true) {
      if (signal?.aborted) {
        return {
          text: '',
          rec: {
            label, ok: false, status: 'aborted', aborted: true,
            error: 'host-ipc seat aborted while awaiting response',
            requested_model: model ?? null, model_served: null, model_family: null,
            family_attested: false, model_attested: false, degraded: true,
          },
        };
      }

      if (fs.existsSync(respPath)) {
        let rawText = '';
        let parsed = null;
        try {
          rawText = fs.readFileSync(respPath, 'utf8');
          parsed = JSON.parse(rawText);
        } catch (err) {
          return {
            text: '',
            rec: {
              label, ok: false, status: 'protocol_error',
              error: `malformed host-ipc response (${path.basename(respPath)}): ${err?.message || err}`.slice(0, 400),
              requested_model: model ?? null, model_served: null, model_family: null,
              family_attested: false, model_attested: false, degraded: true,
              replay_safe: false,
            },
          };
        }

        const durationMs = typeof parsed?.duration_ms === 'number' && Number.isFinite(parsed.duration_ms)
          ? parsed.duration_ms
          : Math.max(0, Number(now()) - startedAtMs);
        const ok = parsed?.ok !== false && parsed?.is_error !== true;
        const text = typeof parsed?.text === 'string'
          ? parsed.text
          : parsed?.result !== undefined && parsed?.result !== null
            ? (typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result))
            : '';
        const servedFamily = typeof parsed?.model_family === 'string' && parsed.model_family.trim()
          ? parsed.model_family.trim().toLowerCase()
          : (typeof parsed?.family === 'string' && parsed.family.trim() ? parsed.family.trim().toLowerCase() : null);
        const servedModel = typeof parsed?.model_served === 'string' && parsed.model_served.trim()
          ? parsed.model_served.trim()
          : (typeof parsed?.model === 'string' && parsed.model.trim() ? parsed.model.trim() : null);
        const familyAttested = ok && Boolean(servedFamily) && parsed?.family_attested !== false;
        const modelAttested = ok && Boolean(servedModel) && parsed?.model_attested !== false;
        const usage = parsed?.usage && typeof parsed.usage === 'object' ? parsed.usage : null;
        const costUsd = typeof parsed?.cost_usd === 'number' && Number.isFinite(parsed.cost_usd)
          ? parsed.cost_usd
          : (typeof parsed?.total_cost_usd === 'number' && Number.isFinite(parsed.total_cost_usd)
            ? parsed.total_cost_usd
            : null);

        const rec = {
          label,
          ipc_request_id: id,
          ok,
          status: ok ? 'success' : String(parsed?.status || 'cli_error'),
          error: ok ? undefined : String(parsed?.error || 'host-ipc worker reported error').slice(0, 500),
          replay_safe: !ok && parsed?.replay_safe === true,
          requested_model: model ?? null,
          model_family: familyAttested ? servedFamily : null,
          family_attested: familyAttested,
          model_served: modelAttested ? servedModel : null,
          model_attested: modelAttested,
          degraded: !modelAttested,
          duration_ms: durationMs,
          usage,
          input_tokens: usage?.input_tokens ?? null,
          output_tokens: usage?.output_tokens ?? null,
          cost_usd: costUsd,
          session_id: typeof parsed?.session_id === 'string' ? parsed.session_id : `host-ipc:${id}`,
        };
        return { text, rec };
      }

      const hbMs = readHeartbeatMs(hbPath);
      if (hbMs !== null && hbMs > lastActivityMs) {
        lastActivityMs = hbMs;
      }

      const currentMs = Number(now());
      if (Number.isFinite(timeoutMs) && timeoutMs > 0 && currentMs - startedAtMs >= timeoutMs) {
        log(`!! ${label}: host-ipc request ${id} exceeded wall-clock timeout (${timeoutMs}ms)`);
        return {
          text: '',
          rec: {
            label, ipc_request_id: id, ok: false, status: 'timeout', timed_out: true,
            error: `host-ipc timed out after ${timeoutMs}ms waiting for ${path.basename(respPath)}`,
            requested_model: model ?? null, model_served: null, model_family: null,
            family_attested: false, model_attested: false, degraded: true,
            duration_ms: Math.max(0, currentMs - startedAtMs),
          },
        };
      }
      if (Number.isFinite(heartbeatTimeoutMs) && heartbeatTimeoutMs > 0 && currentMs - lastActivityMs >= heartbeatTimeoutMs) {
        log(`!! ${label}: host-ipc request ${id} exceeded heartbeat timeout (${heartbeatTimeoutMs}ms)`);
        return {
          text: '',
          rec: {
            label, ipc_request_id: id, ok: false, status: 'idle_timeout', timed_out: true,
            error: `host-ipc heartbeat idle timeout after ${heartbeatTimeoutMs}ms waiting for ${path.basename(respPath)}`,
            requested_model: model ?? null, model_served: null, model_family: null,
            family_attested: false, model_attested: false, degraded: true,
            duration_ms: Math.max(0, currentMs - startedAtMs),
          },
        };
      }

      await sleep(Math.max(5, pollIntervalMs), signal);
    }
  } finally {
    if (!keepIpcFiles) {
      safeUnlink(reqPath);
      safeUnlink(hbPath);
      safeUnlink(respPath);
    }
  }
}

export function makeHostIpcAgentSeam(options = {}) {
  const {
    runHostIpc = null,
    env = process.env,
    target = process.cwd(),
    log = () => {},
  } = options;
  const run = runHostIpc || ((prompt, label, callOpts = {}) =>
    defaultRunHostIpc(prompt, label, { ...options, env, target, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    const role = normalizeRole({ role: opts.role, label });
    const callOpts = {
      model: opts.model,
      role,
      timeoutMs: opts.timeoutMs,
      heartbeatTimeoutMs: opts.heartbeatTimeoutMs ?? options.heartbeatTimeoutMs,
      pollIntervalMs: opts.pollIntervalMs ?? options.pollIntervalMs,
      ipcDir: opts.ipcDir ?? options.ipcDir,
      keepIpcFiles: opts.keepIpcFiles ?? options.keepIpcFiles,
      signal: opts.signal,
      ...(opts.schema ? { jsonSchema: opts.schema } : {}),
    };
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts,
      driverOpts: opts,
      familyName: 'HostIPC',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

export const hostIpcDriver = {
  name: 'host-ipc',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (host-ipc json)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role, timeoutMs, signal } = opts;
    const { agent } = makeHostIpcAgentSeam(opts);
    return agent(prompt, { ...opts, schema, label, model, role, timeoutMs, signal });
  },
};

export default hostIpcDriver;
