import fs from 'node:fs';
import path from 'node:path';
import { resolveGeminiModel } from 'fil<path>';

/**
 * Parses the .gitignore file inside the project directory and returns
 * an array of pattern strings. Includes default folders like .git and node_modules.
 */
export function getGitignorePatterns(projectDir) {
  const patterns = ['.git/', 'node_modules/', '.foreman/'];
  if (projectDir === null || projectDir === undefined || typeof projectDir !== 'string') {
    return patterns;
  }
  const gitignorePath = path.join(projectDir, '.gitignore');
  if (fs.existsSync(gitignorePath)) {
    try {
      const content = fs.readFileSync(gitignorePath, 'utf8');
      const lines = content.split(/\r?\n/);
      for (let line of lines) {
        line = line.trim();
        if (line && !line.startsWith('#')) {
          patterns.push(line);
        }
      }
    } catch {
      // Ignore reading errors to remain robust
    }
  }
  return patterns;
}

/**
 * Checks if a relative path matches any pattern in gitignore.
 */
export function isIgnored(relPath, patterns, isDir = false) {
  const pathStr = relPath.replace(/\\/g, '/');
  for (let pattern of patterns) {
    let pat = pattern.replace(/\\/g, '/');
    const matchesDirOnly = pat.endsWith('/');
    if (matchesDirOnly && !isDir) {
      pat = pat.slice(0, -1);
    }
    if (pat.endsWith('/')) {
      pat = pat.slice(0, -1);
    }
    
    const isAnchored = pat.startsWith('/');
    const cleanPat = isAnchored ? pat.slice(1) : pat;
    
    // Convert glob pattern to regular expression
    let regexStr = cleanPat
      .replace(/[-[\]{}()+\^$|#\s]/g, '\\$&')
      .replace(/\./g, '\\.')
      .replace(/\*/g, '.*')
      .replace(/\?/g, '.');
       
    const regex = new RegExp(isAnchored ? `^${regexStr}(?:/|$)` : `(?:^|/)${regexStr}(?:/|$)`);
    if (regex.test(pathStr)) {
      return true;
    }
  }
  return false;
}

/**
 * Recursively scans a directory (respecting standard ignores)
 * and returns the total bytes and the token count heuristic (bytes / 4).
 */
export function scanDirectory(projectDir) {
  const patterns = getGitignorePatterns(projectDir);
  let totalBytes = 0;

  function traverse(currentDir) {
    let files;
    try {
      files = fs.readdirSync(currentDir);
    } catch {
      return; // Skip unreadable directories
    }

    for (const file of files) {
      const fullPath = path.join(currentDir, file);
      const relPath = path.relative(projectDir, fullPath);
      
      let stat;
      try {
        stat = fs.statSync(fullPath);
      } catch {
        continue; // Skip if stat fails (e.g. broken symlink)
      }

      if (stat.isDirectory()) {
        if (isIgnored(relPath, patterns, true)) {
          continue;
        }
        traverse(fullPath);
      } else if (stat.isFile()) {
        if (isIgnored(relPath, patterns, false)) {
          continue;
        }
        totalBytes += stat.size;
      }
    }
  }

  traverse(projectDir);
  return {
    totalBytes,
    tokens: Math.ceil(totalBytes / 4),
  };
}

/**
 * Sums the byte size of an in-memory payload (the ARTIFACT under analysis), without
 * scanning the whole working directory. Supports the same payload shapes the map-reduce
 * runtime uses: an array of strings/objects, or an object dictionary.
 */
export function sizePayloadBytes(payload) {
  let totalBytes = 0;
  if (Array.isArray(payload)) {
    for (const item of payload) {
      if (typeof item === 'string') {
        totalBytes += Buffer.byteLength(item);
      } else if (item && typeof item === 'object') {
        if (item.content !== undefined) {
          totalBytes += Buffer.byteLength(String(item.content || ''));
        } else if (item.path) {
          totalBytes += Buffer.byteLength(String(item.path));
        }
      }
    }
  } else if (typeof payload === 'string') {
    totalBytes += Buffer.byteLength(payload);
  } else if (payload && typeof payload === 'object') {
    for (const val of Object.values(payload)) {
      totalBytes += Buffer.byteLength(String(val || ''));
    }
  }
  return totalBytes;
}

/**
 * Runs the router logic: computes a heuristic token count for the ARTIFACT under analysis
 * and overrides the configured model env variables only if THAT artifact exceeds
 * ANCHOR_FRONTIER_MAX.
 *
 * Sizing precedence (the artifact, never the whole cwd, unless nothing else is given):
 *   1. `tokens`   — an explicit token estimate of the artifact (preferred).
 *   2. `payload`  — an in-memory payload whose bytes are summed (bytes / 4 ≈ tokens).
 *   3. `projectDir` — LEGACY fallback: scan the directory. Only used when neither a token
 *                     estimate nor a payload is supplied. A focused, scoped question should
 *                     pass `tokens`/`payload` so it never trips a whole-repo model override.
 */
export function runRouter({ projectDir, payload = null, tokens = null, env = process.env, overrideMax = null } = {}) {
  let tokenHeuristic;
  let totalBytes;
  if (typeof tokens === 'number' && !Number.isNaN(tokens)) {
    tokenHeuristic = Math.max(0, Math.ceil(tokens));
    totalBytes = tokenHeuristic * 4;
  } else if (payload !== null && payload !== undefined) {
    totalBytes = sizePayloadBytes(payload);
    tokenHeuristic = Math.ceil(totalBytes / 4);
  } else {
    const sizerResult = scanDirectory(projectDir);
    tokenHeuristic = sizerResult.tokens;
    totalBytes = sizerResult.totalBytes;
  }

  let frontierMax = 100000;
  if (env.ANCHOR_FRONTIER_MAX) {
    const val = parseInt(env.ANCHOR_FRONTIER_MAX, 10);
    if (!isNaN(val)) frontierMax = val;
  }
  if (overrideMax !== null && overrideMax !== undefined) {
    frontierMax = overrideMax;
  }
  
  // W4 (2026-07-05): model ids are agy LABELS resolved via the TRIO_TIER ladder — NEVER a hardcoded
  // API-style id (the old hardcoded API-style defaults were PHANTOM ids that live agy does not
  // recognize and silently degrades to Flash). A big artifact that exceeds the frontier ceiling is
  // routed to the high-context, cheaper STANDARD label; a small artifact to the frontier HEAVY label.
  const highContextModel = env.GANDALF_HIGH_CONTEXT_MODEL || env.GEMINI_HIGH_CONTEXT_MODEL
    || resolveGeminiModel({ env: { ...env, TRIO_TIER: 'standard' } });
  const frontierModel = env.GANDALF_FRONTIER_MODEL || env.GEMINI_MODEL
    || resolveGeminiModel({ env: { ...env, TRIO_TIER: 'heavy' } });
  
  let selectedModel;
  let overridden = false;
  if (tokenHeuristic > frontierMax) {
    selectedModel = highContextModel;
    overridden = true;
  } else {
    selectedModel = frontierModel;
  }
  
  // Apply overrides to the provided env object
  env.GEMINI_MODEL = selectedModel;
  env.TRIO_MODEL = selectedModel;
  env.GANDALF_ROUTED_MODEL = selectedModel;
  
  return {
    tokenHeuristic,
    frontierMax,
    selectedModel,
    overridden,
    totalBytes
  };
}

