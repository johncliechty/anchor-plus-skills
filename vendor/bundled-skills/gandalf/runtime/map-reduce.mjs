import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { makeGeminiCliSeam, resolveGeminiModel } from 'fil<path>';
import { scoutAndFilter } from './scout.mjs';

/**
 * Resolves file path string payloads to objects containing paths and contents.
 */
export function resolvePayload(payload, projectDir = null) {
  if (Array.isArray(payload)) {
    return payload.map(item => {
      if (typeof item === 'string') {
        let content = '';
        try {
          const fullPath = projectDir ? path.resolve(projectDir, item) : path.resolve(item);
          content = fs.readFileSync(fullPath, 'utf8');
        } catch {
          // fallback
        }
        return { path: item, content };
      } else if (item && typeof item === 'object' && item.content === undefined && item.path) {
        let content = '';
        try {
          const fullPath = projectDir ? path.resolve(projectDir, item.path) : path.resolve(item.path);
          content = fs.readFileSync(fullPath, 'utf8');
        } catch {
          // fallback
        }
        return { ...item, content };
      }
      return item;
    });
  }
  return payload;
}

/**
 * Calculates the size of a payload in bytes.
 * Supports:
 * - Array of objects: [ { path: 'relative/path', content: '...' }, ... ]
 * - Array of strings: [ 'relative/path', ... ]
 * - Object dictionary: { 'relative/path': 'content', ... }
 */
export function calculatePayloadSize(payload, projectDir = null) {
  let totalBytes = 0;
  if (Array.isArray(payload)) {
    for (const item of payload) {
      if (typeof item === 'string') {
        if (projectDir) {
          try {
            const fullPath = path.resolve(projectDir, item);
            totalBytes += fs.statSync(fullPath).size;
            continue;
          } catch {
            // fallback if stat fails
          }
        }
        totalBytes += Buffer.byteLength(item);
      } else if (item && typeof item === 'object') {
        if (item.content !== undefined) {
          totalBytes += Buffer.byteLength(item.content || '');
        } else if (item.path) {
          if (projectDir) {
            try {
              const fullPath = path.resolve(projectDir, item.path);
              totalBytes += fs.statSync(fullPath).size;
              continue;
            } catch {
              // fallback
            }
          }
          totalBytes += Buffer.byteLength(item.path);
        }
      }
    }
  } else if (payload && typeof payload === 'object') {
    for (const [key, val] of Object.entries(payload)) {
      totalBytes += Buffer.byteLength(String(val || ''));
    }
  }
  return totalBytes;
}

/**
 * Estimates token count of a payload using bytes / 4.
 */
export function estimatePayloadTokens(payload, projectDir = null) {
  const bytes = calculatePayloadSize(payload, projectDir);
  return Math.ceil(bytes / 4);
}

/**
 * Normalizes path and returns the top-level directory (e.g. /backend, /frontend).
 * Root files return '/'.
 */
export function getTopLevelDir(filePath) {
  const normalized = filePath.replace(/\\/g, '/');
  const clean = normalized.startsWith('/') ? normalized.slice(1) : normalized;
  const parts = clean.split('/');
  if (parts.length > 1 && parts[0] !== '') {
    return '/' + parts[0];
  }
  return '/';
}

/**
 * Groups files in payload by their top-level directory.
 */
export function groupPayloadByTopLevelDir(payload) {
  const groups = {};

  if (Array.isArray(payload)) {
    for (const item of payload) {
      const filePath = typeof item === 'string' ? item : item.path;
      const groupName = getTopLevelDir(filePath);
      if (!groups[groupName]) {
        groups[groupName] = [];
      }
      groups[groupName].push(item);
    }
  } else if (payload && typeof payload === 'object') {
    for (const [filePath, content] of Object.entries(payload)) {
      const groupName = getTopLevelDir(filePath);
      if (!groups[groupName]) {
        groups[groupName] = {};
      }
      groups[groupName][filePath] = content;
    }
  }
  return groups;
}

/**
 * Serializes a chunk payload to a readable text format.
 */
export function serializeChunk(chunk, projectDir = null) {
  let serialized = '';
  if (Array.isArray(chunk)) {
    for (const item of chunk) {
      if (typeof item === 'string') {
        let content = '';
        try {
          const fullPath = projectDir ? path.resolve(projectDir, item) : path.resolve(item);
          content = fs.readFileSync(fullPath, 'utf8');
        } catch {
          // fallback
        }
        serialized += `File: ${item}\n\`\`\`\n${content}\n\`\`\`\n\n`;
      } else if (item && typeof item === 'object') {
        if (item.content !== undefined) {
          serialized += `File: ${item.path}\n\`\`\`\n${item.content || ''}\n\`\`\`\n\n`;
        } else {
          let content = '';
          try {
            const fullPath = projectDir ? path.resolve(projectDir, item.path) : path.resolve(item.path);
            content = fs.readFileSync(fullPath, 'utf8');
          } catch {
            // fallback
          }
          serialized += `File: ${item.path}\n\`\`\`\n${content}\n\`\`\`\n\n`;
        }
      }
    }
  } else if (chunk && typeof chunk === 'object') {
    for (const [filePath, content] of Object.entries(chunk)) {
      serialized += `File: ${filePath}\n\`\`\`\n${content || ''}\n\`\`\`\n\n`;
    }
  }
  return serialized.trim();
}

/**
 * Estimates the serialized size in bytes without materializing the whole payload in memory.
 */
export function estimateSerializedSize(payload, projectDir = null) {
  let size = 0;
  if (Array.isArray(payload)) {
    for (const item of payload) {
      if (typeof item === 'string') {
        let fileBytes = 0;
        try {
          const fullPath = projectDir ? path.resolve(projectDir, item) : path.resolve(item);
          fileBytes = fs.statSync(fullPath).size;
        } catch {
          // fallback
        }
        size += 16 + Buffer.byteLength(item) + fileBytes;
      } else if (item && typeof item === 'object') {
        if (item.content !== undefined) {
          size += 16 + Buffer.byteLength(item.path || '') + Buffer.byteLength(item.content || '');
        } else if (item.path) {
          let fileBytes = 0;
          try {
            const fullPath = projectDir ? path.resolve(projectDir, item.path) : path.resolve(item.path);
            fileBytes = fs.statSync(fullPath).size;
          } catch {
            // fallback
          }
          size += 16 + Buffer.byteLength(item.path) + fileBytes;
        }
      }
    }
  } else if (payload && typeof payload === 'object') {
    for (const [filePath, content] of Object.entries(payload)) {
      size += 16 + Buffer.byteLength(filePath) + Buffer.byteLength(String(content || ''));
    }
  }
  return size;
}

export function getLockDir() {
  if (process.env.GANDALF_LOCK_DIR) {
    return process.env.GANDALF_LOCK_DIR;
  }
  let home = '';
  try {
    home = os.homedir();
  } catch {
    home = os.tmpdir();
  }
  const cacheDir = process.env.GANDALF_CACHE_DIR || path.join(home || os.tmpdir(), '.gandalf', 'cache');
  return path.join(cacheDir, 'locks');
}

// Cross-process file-lock semaphore: mkdir slot dirs under the lock dir. mkdir is
// atomic on every platform, so exactly one contender (handle or process) can own a
// slot at a time. The C4 (2026-07-11) fail-HANG mode — a crashed run's stale slot
// dir starving every future run forever — is closed here at the root instead of by
// retiring the semaphore: each slot records its owner pid, a slot whose owner is
// provably dead is reclaimed, and acquisition has an honest timeout (throws, never
// spins forever). The in-process limiter in limitConcurrency stays lock-free.

const SLOT_POLL_MS = 25;
const DEFAULT_LOCK_TIMEOUT_MS = 5 * 60 * 1000;

function slotDirPath(lockDir, slotIndex) {
  return path.join(lockDir, `slot-${slotIndex}`);
}

function isPidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM means the pid exists but belongs to another user — still alive.
    return err.code === 'EPERM';
  }
}

/** Reclaims a slot whose recorded owner process is dead. Returns true if reclaimed. */
function reclaimIfStale(slotDir) {
  let owner;
  try {
    owner = JSON.parse(fs.readFileSync(path.join(slotDir, 'owner.json'), 'utf8'));
  } catch {
    // No readable owner record — the holder may be mid-acquisition; never steal.
    return false;
  }
  if (typeof owner?.pid !== 'number' || isPidAlive(owner.pid)) return false;
  try {
    fs.rmSync(slotDir, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

export async function acquireSlot(lockDir, maxConcurrency, { timeoutMs } = {}) {
  const slots = Math.max(1, parseInt(maxConcurrency, 10) || 1);
  const envTimeout = parseInt(process.env.GANDALF_LOCK_TIMEOUT_MS, 10);
  const deadline = Date.now() + (timeoutMs ?? (Number.isNaN(envTimeout) ? DEFAULT_LOCK_TIMEOUT_MS : envTimeout));
  fs.mkdirSync(lockDir, { recursive: true });

  for (;;) {
    for (let slot = 0; slot < slots; slot++) {
      const slotDir = slotDirPath(lockDir, slot);
      try {
        fs.mkdirSync(slotDir);
      } catch (err) {
        if (err.code !== 'EEXIST') throw err;
        reclaimIfStale(slotDir); // dead owner → freed; a live contender retries it next pass
        continue;
      }
      fs.writeFileSync(path.join(slotDir, 'owner.json'), JSON.stringify({ pid: process.pid, acquired_at: new Date().toISOString() }));
      return slot;
    }
    if (Date.now() >= deadline) {
      throw new Error(`acquireSlot: timed out waiting for one of ${slots} slot(s) under ${lockDir}`);
    }
    await new Promise(resolve => setTimeout(resolve, SLOT_POLL_MS));
  }
}

export function releaseSlot(lockDir, slotIndex) {
  try {
    fs.rmSync(slotDirPath(lockDir, slotIndex), { recursive: true, force: true });
  } catch {
    // Releasing an already-gone slot is not an error.
  }
}

/**
 * Executes a list of task functions concurrently, with a maximum limit.
 * Pure in-process semaphore: no filesystem locks, nothing to leak on a crash.
 */
export async function limitConcurrency(tasks, limit) {
  let resolvedLimit = 3;
  if (process.env.GANDALF_MAX_CONCURRENCY) {
    const val = parseInt(process.env.GANDALF_MAX_CONCURRENCY, 10);
    if (!isNaN(val)) resolvedLimit = val;
  } else if (typeof limit === 'number') {
    resolvedLimit = limit;
  }
  resolvedLimit = Math.max(1, resolvedLimit);

  const results = [];
  const executing = new Set();
  for (const task of tasks) {
    const p = Promise.resolve().then(() => task());
    results.push(p);
    executing.add(p);
    const clean = () => executing.delete(p);
    p.then(clean, clean);
    if (executing.size >= resolvedLimit) {
      await Promise.race(executing);
    }
  }
  return Promise.all(results);
}

export const GANDALF_MAX_CHUNK_BYTES = 500000;

/** Above this file count, a payload "looks like a whole repo" rather than a curated, scoped
 *  artifact. A focused question over a whole-repo payload must NOT silently fan out to Map-Reduce —
 *  it scouts to curate first, and only fans out when the operator explicitly opts in
 *  (GANDALF_ALLOW_REPO_SCALE=1). */
export const GANDALF_REPO_FILE_THRESHOLD = 50;
export const GANDALF_DEFAULT_HIGH_CONTEXT_LIMIT = 100000;

/** Resolve the High-Context token limit from explicit override → env → default, mirroring
 *  runMapReduce so decideTier and the runner never disagree. */
export function resolveHighContextLimit(env = process.env, override = null) {
  if (override !== null && override !== undefined) return override;
  if (env.GANDALF_HIGH_CONTEXT_LIMIT) {
    const val = parseInt(env.GANDALF_HIGH_CONTEXT_LIMIT, 10);
    if (!isNaN(val)) return val;
  }
  if (env.ANCHOR_FRONTIER_MAX) {
    const val = parseInt(env.ANCHOR_FRONTIER_MAX, 10);
    if (!isNaN(val)) return val;
  }
  return GANDALF_DEFAULT_HIGH_CONTEXT_LIMIT;
}

/** Resolve the per-chunk byte ceiling from env → default. */
export function resolveMaxChunkBytes(env = process.env, override = null) {
  if (override !== null && override !== undefined) return override;
  if (env.GANDALF_MAX_CHUNK_BYTES) {
    const val = parseInt(env.GANDALF_MAX_CHUNK_BYTES, 10);
    if (!isNaN(val)) return val;
  }
  return GANDALF_MAX_CHUNK_BYTES;
}

/** True iff the payload looks like a whole repo (more files than the curated-artifact threshold). */
export function looksLikeWholeRepo(payload) {
  return getPayloadItemCount(payload) > GANDALF_REPO_FILE_THRESHOLD;
}

/**
 * JUDGE-SCOPE-FIRST tier gate. Decides the cheapest tier that can honestly answer the objective
 * over the given (already-SCOPED) payload, and DEFAULTS to 'direct'. It only escalates when the
 * scoped artifact genuinely exceeds the limits:
 *
 *   • 'direct'    — the payload fits the High-Context token limit AND the per-chunk byte ceiling.
 *                   This is the default for a small, focused question.
 *   • 'scout'     — the payload exceeds limits and must be curated first (the safe default
 *                   escalation). A whole-repo-sized payload on a focused question lands here and
 *                   will NOT proceed to a Map-Reduce fan-out without an explicit opt-in.
 *   • 'mapreduce' — only when escalation is warranted AND the operator has opted into a bulk
 *                   fan-out (GANDALF_ALLOW_REPO_SCALE=1, or a scout bypass) so the curated
 *                   payload may legitimately be fanned out.
 *
 * Pure: never spawns, never mutates. `payload` should be the scoped artifact, never the raw repo.
 */
export function decideTier({
  payload,
  objective = '',
  env = process.env,
  projectDir = null,
  highContextLimit = null,
  maxChunkBytes = null
} = {}) {
  const limit = resolveHighContextLimit(env, highContextLimit);
  const chunkCeiling = resolveMaxChunkBytes(env, maxChunkBytes);

  const tokens = estimatePayloadTokens(payload, projectDir);
  const bytes = estimateSerializedSize(payload, projectDir);

  // Default: a scoped payload that fits is answered directly — no scaling up.
  if (tokens <= limit && bytes <= chunkCeiling) {
    return 'direct';
  }

  const wholeRepo = looksLikeWholeRepo(payload);
  const allowRepoScale = env.GANDALF_ALLOW_REPO_SCALE === '1';
  const skipScout = env.GANDALF_SKIP_SCOUT === 'true' || env.GANDALF_FORCE_WHOLE_REPO === 'true';

  // WHOLE-REPO GUARD: a whole-repo payload must be curated by the scout before any fan-out, and
  // the bulk fan-out itself requires an explicit opt-in. Without it, stay at 'scout'.
  if (wholeRepo && !allowRepoScale) {
    return 'scout';
  }

  // A scout bypass (or an opted-in whole-repo run) goes straight to the fan-out; otherwise the safe
  // default is still to scout-first and curate before deciding to fan out.
  if (skipScout) {
    return 'mapreduce';
  }
  return 'scout';
}

/** Take payload items in order until the cumulative serialized size would exceed `maxChunkBytes`.
 *  Returns the kept slice plus original/kept counts so the caller can stamp an honest degraded note. */
function capPayloadToBudget(payload, maxChunkBytes, projectDir) {
  const items = getChunkItems(payload);
  const total = items.length;
  const kept = [];
  let used = 0;
  for (const item of items) {
    const itemSize = estimateSerializedSize([item], projectDir);
    if (kept.length > 0 && used + itemSize > maxChunkBytes) break;
    kept.push(item);
    used += itemSize;
  }
  return { kept, total, keptCount: kept.length };
}

function getChunkItems(chunk) {
  if (Array.isArray(chunk)) {
    return chunk;
  } else if (chunk && typeof chunk === 'object') {
    return Object.entries(chunk).map(([path, content]) => ({ path, content }));
  }
  return [];
}

async function mapOrSplit({
  payload,
  groupName,
  userObjective,
  activeAgent,
  reduceAgent = null,
  maxChunkBytes,
  projectDir,
  log
}) {
  // W4: bulk MAP reads run on activeAgent (STANDARD); intra-shard SYNTHESIS on the reduce
  // (HEAVY/frontier) seat when supplied, else fall back to the single agent (legacy behaviour).
  const activeReduceAgent = reduceAgent || activeAgent;
  const items = getChunkItems(payload);
  
  const estimatedSize = estimateSerializedSize(items, projectDir);

  if (estimatedSize <= maxChunkBytes) {
    log(`Payload size (${estimatedSize} bytes) is within ceiling (${maxChunkBytes}). Mapping chunk: ${groupName}`);
    const serializedContent = serializeChunk(items, projectDir);
    const chunkPrompt = `Analyze the following files from directory/chunk: ${groupName}
User Objective: "${userObjective}"

Provide a summary of findings, code patterns, and potential issues for this chunk.

Codebase Chunk Files:
${serializedContent}`;

    return await activeAgent(chunkPrompt, { label: `map-reduce-chunk-${groupName}` });
  }

  log(`Payload size (${estimatedSize} bytes) exceeds ceiling (${maxChunkBytes}) for chunk ${groupName}. Splitting recursively.`);

  if (items.length > 1) {
    const mid = Math.floor(items.length / 2);
    const leftItems = items.slice(0, mid);
    const rightItems = items.slice(mid);

    log(`Splitting ${groupName} by file into two sub-chunks (sizes: ${leftItems.length}, ${rightItems.length})`);

    const leftName = `${groupName}.1`;
    const rightName = `${groupName}.2`;

    const leftSummary = await mapOrSplit({
      payload: leftItems,
      groupName: leftName,
      userObjective,
      activeAgent,
      reduceAgent: activeReduceAgent,
      maxChunkBytes,
      projectDir,
      log
    });

    const rightSummary = await mapOrSplit({
      payload: rightItems,
      groupName: rightName,
      userObjective,
      activeAgent,
      reduceAgent: activeReduceAgent,
      maxChunkBytes,
      projectDir,
      log
    });

    log(`Synthesizing split file summaries for ${groupName}`);
    const synthPrompt = `You are a codebase synthesizer. You are given several chunk summaries of a codebase analysis.
User Objective: "${userObjective}"

Chunk Summaries:
--- Chunk: ${leftName} ---
${leftSummary}

--- Chunk: ${rightName} ---
${rightSummary}

Please fuse these summaries into a single, coherent advisory report addressing the user objective.`;

    return await activeReduceAgent(synthPrompt, { label: `map-reduce-synth-${groupName}` });
  } else {
    const item = items[0];
    let filePath = '';
    let content = '';

    if (typeof item === 'string') {
      filePath = item;
      try {
        const fullPath = projectDir ? path.resolve(projectDir, filePath) : path.resolve(filePath);
        content = fs.readFileSync(fullPath, 'utf8');
      } catch {
        // fallback
      }
    } else if (item && typeof item === 'object') {
      filePath = item.path;
      if (item.content !== undefined) {
        content = item.content;
      } else {
        try {
          const fullPath = projectDir ? path.resolve(projectDir, filePath) : path.resolve(filePath);
          content = fs.readFileSync(fullPath, 'utf8');
        } catch {
          // fallback
        }
      }
    }

    const lines = content.split(/\r?\n/);
    if (lines.length <= 1) {
      log(`Warning: single line in ${filePath} exceeds ceiling. Mapping as-is.`);
      const serializedContent = serializeChunk(items, projectDir);
      const chunkPrompt = `Analyze the following files from directory/chunk: ${groupName}
User Objective: "${userObjective}"

Provide a summary of findings, code patterns, and potential issues for this chunk.

Codebase Chunk Files:
${serializedContent}`;

      return await activeAgent(chunkPrompt, { label: `map-reduce-chunk-${groupName}` });
    }

    const mid = Math.floor(lines.length / 2);
    const leftLines = lines.slice(0, mid);
    const rightLines = lines.slice(mid);

    log(`Splitting file ${filePath} by line into two halves (${leftLines.length} lines, ${rightLines.length} lines)`);

    const leftItem = {
      path: filePath,
      content: leftLines.join('\n')
    };
    const rightItem = {
      path: filePath,
      content: rightLines.join('\n')
    };

    const leftName = `${groupName}.1`;
    const rightName = `${groupName}.2`;

    const leftSummary = await mapOrSplit({
      payload: [leftItem],
      groupName: leftName,
      userObjective,
      activeAgent,
      reduceAgent: activeReduceAgent,
      maxChunkBytes,
      projectDir,
      log
    });

    const rightSummary = await mapOrSplit({
      payload: [rightItem],
      groupName: rightName,
      userObjective,
      activeAgent,
      reduceAgent: activeReduceAgent,
      maxChunkBytes,
      projectDir,
      log
    });

    log(`Synthesizing split line summaries for ${groupName}`);
    const synthPrompt = `You are a codebase synthesizer. You are given several chunk summaries of a codebase analysis.
User Objective: "${userObjective}"

Chunk Summaries:
--- Chunk: ${leftName} ---
${leftSummary}

--- Chunk: ${rightName} ---
${rightSummary}

Please fuse these summaries into a single, coherent advisory report addressing the user objective.`;

    return await activeReduceAgent(synthPrompt, { label: `map-reduce-synth-${groupName}` });
  }
}

/**
 * INTERNAL pre-summarizer for OVERSIZED artifacts — NOT the canonical Gandalf entrypoint.
 *
 * The canonical, branded output is the `gandalf-advisor-1` JSON advisor envelope produced by the
 * seam-pass host (runtime/gandalf-run.mjs → runtime/seam-pass.applySeamPass →
 * assertIncrement1Conformant). runMapReduce returns RAW model prose; it is meant to be used only as
 * a PRE-STAGE that pre-summarizes an artifact too large to fit a single model context, whose prose
 * is then fed BACK as the draft into applySeamPass — never returned to the user as the report.
 *
 * Tiering JUDGES SCOPE FIRST via decideTier (defaults to 'direct'). If the SCOPED payload fits, it
 * is analyzed directly. If it exceeds limits it scouts to curate first; a whole-repo-sized payload
 * on a focused question will NOT fan out to Map-Reduce unless the operator opts in with
 * GANDALF_ALLOW_REPO_SCALE=1. When it does fan out, it chunks by top-level directory, processes up
 * to 3 chunks concurrently using a semaphore, and synthesizes the report. The honest degraded stamp
 * ("analyzed slice N of M; skipped K", degraded:true) is preserved end-to-end.
 */
/**
 * Cap top-level shard groups to maxShards (band-thin LITE). Stable order; overflow
 * merges into the last kept bucket so work is not dropped silently.
 * @param {Record<string, unknown>} groups
 * @param {number|null|undefined} maxShards
 * @returns {Record<string, unknown>}
 */
export function capGroupsToMaxShards(groups, maxShards) {
  if (!groups || typeof groups !== 'object') return groups || {};
  const entries = Object.entries(groups);
  const n = Number(maxShards);
  if (!Number.isFinite(n) || n < 1 || entries.length <= n) {
    return groups;
  }
  const kept = entries.slice(0, n);
  const overflow = entries.slice(n);
  const lastKey = kept[kept.length - 1][0];
  let lastVal = kept[kept.length - 1][1];
  for (const [, chunk] of overflow) {
    if (Array.isArray(lastVal) && Array.isArray(chunk)) {
      lastVal = lastVal.concat(chunk);
    } else if (lastVal && typeof lastVal === 'object' && chunk && typeof chunk === 'object' && !Array.isArray(lastVal)) {
      lastVal = { ...lastVal, ...chunk };
    } else if (Array.isArray(lastVal)) {
      lastVal = lastVal.concat(chunk);
    } else {
      lastVal = chunk;
    }
  }
  kept[kept.length - 1] = [lastKey, lastVal];
  return Object.fromEntries(kept);
}

export async function runMapReduce({
  projectDir = null,
  payload,
  userObjective,
  agent = null,
  reduceAgent = null,
  env = process.env,
  log = () => {},
  highContextLimit = null,
  concurrencyLimit = 3,
  /** Band knobs from @foundry/triage gandalf table (optional). */
  maxShards = null,
  fusionPasses = null,
} = {}) {
  let activeAgent = agent;
  if (!activeAgent) {
    // W4 (2026-07-05): resolve the agy LABEL via the TRIO_TIER ladder — NEVER a hardcoded API-style id
    // (the old hardcoded default was a phantom id that live agy silently degrades to Flash). The clever
    // map=STANDARD / reduce=HEAVY split is applied by the CLI wiring (runtime/gandalf-run.mjs
    // runScaledAnalysis), which injects distinct map/reduce agents; standalone callers get one
    // ladder-resolved agent for both roles.
    const model = env.GANDALF_HIGH_CONTEXT_MODEL || env.GEMINI_MODEL || resolveGeminiModel({ env });
    const seam = makeGeminiCliSeam({ model, env, log });
    activeAgent = seam.agent;
  }
  // W4: the REDUCE/synthesis seat (and the single-frontier direct pass) may run on a distinct,
  // higher-tier agent than the bulk MAP reads. Defaults to activeAgent so standalone/legacy callers
  // (and every existing test that injects a single `agent`) behave exactly as before.
  const activeReduceAgent = reduceAgent || activeAgent;

  // Resolve High-Context + per-chunk byte limits (shared with decideTier so they never disagree).
  const limit = resolveHighContextLimit(env, highContextLimit);
  const maxChunkBytes = resolveMaxChunkBytes(env);

  // Resolve Concurrency limit
  let resolvedConcurrency = 3;
  if (env.GANDALF_MAX_CONCURRENCY) {
    const val = parseInt(env.GANDALF_MAX_CONCURRENCY, 10);
    if (!isNaN(val)) resolvedConcurrency = val;
  } else if (concurrencyLimit !== null && concurrencyLimit !== undefined) {
    resolvedConcurrency = concurrencyLimit;
  }

  const estimatedTokens = estimatePayloadTokens(payload, projectDir);
  const totalSerializedSize = estimateSerializedSize(payload, projectDir);

  // JUDGE SCOPE FIRST: default to a direct pass; only escalate when the scoped artifact warrants it.
  const tier = decideTier({ payload, objective: userObjective, env, projectDir, highContextLimit });

  if (tier === 'direct') {
    const resolvedPayload = resolvePayload(payload, projectDir);
    log(`Payload size (${estimatedTokens} tokens, ${totalSerializedSize} bytes) is within limits. Processing directly (tier=direct).`);
    const directPrompt = `Analyze the following files for the objective: "${userObjective}"

Codebase Payload:
${serializeChunk(resolvedPayload, projectDir)}

Provide a coherent advisory report addressing the user objective.`;

    // W4: a SMALL target answered in ONE frontier pass — the reduce (HEAVY/frontier) seat.
    const report = await activeReduceAgent(directPrompt, { label: 'map-reduce-direct' });
    return report;
  }

  log(`Payload size (${estimatedTokens} tokens, ${totalSerializedSize} bytes) exceeds limits. Checking scout-pass default.`);

  let scoutedPayload = payload;
  let degraded = false;
  let stamp = '';

  const skipScout = env.GANDALF_SKIP_SCOUT === 'true' || env.GANDALF_FORCE_WHOLE_REPO === 'true';

  if (!skipScout) {
    log(`Scouting first to filter the payload.`);
    scoutedPayload = await scoutAndFilter({
      projectDir,
      payload,
      userObjective,
      agent: activeAgent,
      env,
      log
    });

    if (isContentDropped(payload, scoutedPayload)) {
      degraded = true;
      const originalCount = getPayloadItemCount(payload);
      const prunedCount = getPayloadItemCount(scoutedPayload);
      const skippedCount = originalCount - prunedCount;
      stamp = `analyzed slice ${prunedCount} of ${originalCount}; skipped ${skippedCount}`;
      log(`Scouting dropped content. Stamp: "${stamp}"`);
    }
  } else {
    log(`Bypassing scout pass as requested.`);
  }

  const scoutedTokens = estimatePayloadTokens(scoutedPayload, projectDir);
  const scoutedSerializedSize = estimateSerializedSize(scoutedPayload, projectDir);

  if (scoutedTokens <= limit && scoutedSerializedSize <= maxChunkBytes) {
    const resolvedPayload = resolvePayload(scoutedPayload, projectDir);
    log(`Scouted payload size (${scoutedTokens} tokens, ${scoutedSerializedSize} bytes) is within limits. Processing directly.`);
    const directPrompt = `Analyze the following files for the objective: "${userObjective}"

Codebase Payload:
${serializeChunk(resolvedPayload, projectDir)}

Provide a coherent advisory report addressing the user objective.`;

    // W4: the final advisory over the curated (scouted) payload — the reduce (HEAVY/frontier) seat.
    let report = await activeReduceAgent(directPrompt, { label: 'map-reduce-direct' });
    if (degraded) {
      report = report + `\n\n[degraded:true] Stamp: ${stamp}`;
      const reportStr = new String(report);
      reportStr.degraded = true;
      reportStr.stamp = stamp;
      return reportStr;
    }
    return report;
  }

  // WHOLE-REPO GUARD: scouting could not curate this below whole-repo scale. Do NOT silently fan out
  // the whole repo for a focused question — that requires an explicit operator opt-in. Without it,
  // run a bounded, honestly-degraded direct pass over the slice that fits the per-chunk ceiling.
  const allowRepoScale = env.GANDALF_ALLOW_REPO_SCALE === '1';
  if (looksLikeWholeRepo(scoutedPayload) && !allowRepoScale) {
    const { kept, total, keptCount } = capPayloadToBudget(scoutedPayload, maxChunkBytes, projectDir);
    const skippedCount = total - keptCount;
    log(`Whole-repo guard: ${total} files exceed limits and GANDALF_ALLOW_REPO_SCALE!=1. Capping to ${keptCount} files and running a degraded direct pass instead of a Map-Reduce fan-out.`);
    const resolvedPayload = resolvePayload(kept, projectDir);
    const directPrompt = `Analyze the following files for the objective: "${userObjective}"

Codebase Payload:
${serializeChunk(resolvedPayload, projectDir)}

Provide a coherent advisory report addressing the user objective.`;

    // W4: the bounded degraded pass over the fitting slice — the reduce (HEAVY/frontier) seat.
    let report = await activeReduceAgent(directPrompt, { label: 'map-reduce-direct' });
    // Compose an honest degraded stamp (preserving any earlier scout-drop count in the total).
    const guardStamp = `analyzed slice ${keptCount} of ${total}; skipped ${skippedCount} (whole-repo fan-out gated; set GANDALF_ALLOW_REPO_SCALE=1 to opt in)`;
    const finalStamp = degraded && stamp ? `${stamp}; ${guardStamp}` : guardStamp;
    report = report + `\n\n[degraded:true] Stamp: ${finalStamp}`;
    const reportStr = new String(report);
    reportStr.degraded = true;
    reportStr.stamp = finalStamp;
    return reportStr;
  }

  log(`Payload size (${scoutedTokens} tokens, ${scoutedSerializedSize} bytes) exceeds limits. Initiating Map-Reduce.`);

  let groups = groupPayloadByTopLevelDir(scoutedPayload);
  // Band-thin + legacy env cap (L2/L4):
  // - locked call sites pass maxShards = knobs.shards; GANDALF_MAX_SHARDS may only TIGHTEN
  //   (min), never expand past the lock.
  // - unlocked call sites leave maxShards null; GANDALF_MAX_SHARDS is the legacy-only cap.
  let shardCap = null;
  if (maxShards != null && Number.isFinite(Number(maxShards))) {
    shardCap = Math.max(1, Math.floor(Number(maxShards)));
    if (env.GANDALF_MAX_SHARDS) {
      const envCap = Math.max(1, parseInt(env.GANDALF_MAX_SHARDS, 10) || 8);
      if (Number.isFinite(envCap)) shardCap = Math.min(shardCap, envCap);
    }
  } else if (env.GANDALF_MAX_SHARDS) {
    shardCap = Math.max(1, parseInt(env.GANDALF_MAX_SHARDS, 10) || 8);
  }
  if (shardCap != null) {
    const before = Object.keys(groups).length;
    groups = capGroupsToMaxShards(groups, shardCap);
    const after = Object.keys(groups).length;
    if (after < before) log(`band-thin: capped shards ${before} → ${after} (maxShards=${shardCap})`);
  }
  const groupEntries = Object.entries(groups);

  let activeCount = 0;
  let maxActiveCount = 0;

  const tasks = groupEntries.map(([groupName, chunk]) => {
    return async () => {
      activeCount++;
      if (activeCount > maxActiveCount) {
        maxActiveCount = activeCount;
      }
      log(`Starting chunk analysis for ${groupName} (current active: ${activeCount}, max active: ${maxActiveCount})`);
      
      try {
        const resultText = await mapOrSplit({
          payload: chunk,
          groupName,
          userObjective,
          activeAgent,
          reduceAgent: activeReduceAgent,
          maxChunkBytes,
          projectDir,
          log
        });
        return { group: groupName, text: resultText };
      } finally {
        activeCount--;
        log(`Finished chunk analysis for ${groupName} (current active: ${activeCount})`);
      }
    };
  });

  let chunkSummaries = await limitConcurrency(tasks, resolvedConcurrency);

  log(`Completed all ${chunkSummaries.length} chunk analyses (max concurrent tasks: ${maxActiveCount}). Initiating synthesis.`);

  const passes =
    fusionPasses != null && Number.isFinite(Number(fusionPasses))
      ? Math.max(1, Math.floor(Number(fusionPasses)))
      : 1;

  // fusionPasses > 1: hierarchical pair-fuse then final reduce (FULL band); LITE keeps one pass.
  if (passes >= 2 && chunkSummaries.length > 2) {
    log(`band-thin: fusionPasses=${passes} — intermediate pair fusion over ${chunkSummaries.length} shards`);
    const mid = [];
    for (let i = 0; i < chunkSummaries.length; i += 2) {
      const pair = chunkSummaries.slice(i, i + 2);
      if (pair.length === 1) {
        mid.push(pair[0]);
        continue;
      }
      const midPrompt = `You are a codebase synthesizer. Fuse these two chunk summaries.
User Objective: "${userObjective}"

${pair.map((s) => `--- Chunk: ${s.group} ---\n${s.text}`).join('\n\n')}

Return one fused summary.`;
      const text = await activeReduceAgent(midPrompt, { label: `map-reduce-fusion-mid-${i}` });
      mid.push({ group: `${pair[0].group}+${pair[1].group}`, text });
    }
    chunkSummaries = mid;
  }

  const synthPrompt = `You are a codebase synthesizer. You are given several chunk summaries of a codebase analysis.
User Objective: "${userObjective}"

Chunk Summaries:
${chunkSummaries.map(s => `--- Chunk: ${s.group} ---\n${s.text}`).join('\n\n')}

Please fuse these summaries into a single, coherent advisory report addressing the user objective.`;

  // W4: the top-level REDUCE — fuse the shard summaries on the HEAVY/frontier seat.
  const finalReport = await activeReduceAgent(synthPrompt, { label: 'map-reduce-synthesis' });
  if (degraded) {
    const reportWithStamp = finalReport + `\n\n[degraded:true] Stamp: ${stamp}`;
    const reportStr = new String(reportWithStamp);
    reportStr.degraded = true;
    reportStr.stamp = stamp;
    return reportStr;
  }
  return finalReport;
}

function isContentDropped(original, pruned) {
  if (!pruned || !original) return false;
  if (Array.isArray(original) && Array.isArray(pruned)) {
    return pruned.length < original.length;
  }
  if (typeof original === 'object' && typeof pruned === 'object') {
    return Object.keys(pruned).length < Object.keys(original).length;
  }
  return false;
}

function getPayloadItemCount(payload) {
  if (Array.isArray(payload)) {
    return payload.length;
  }
  if (payload && typeof payload === 'object') {
    return Object.keys(payload).length;
  }
  return 0;
}
