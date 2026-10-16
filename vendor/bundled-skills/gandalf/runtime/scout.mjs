import fs from 'node:fs';
import path from 'node:path';
import { getGitignorePatterns, isIgnored } from './context-sizer.mjs';
import { makeGeminiCliSeam, resolveGeminiModel } from 'fil<path>';

/**
 * Generates a lightweight, indented .txt tree representation of the codebase,
 * respecting standard gitignore patterns.
 *
 * @param {string} projectDir - The root directory of the project.
 * @returns {string} - Formatted directory tree text.
 */
export function generateTreeText(projectDir) {
  if (projectDir === null || projectDir === undefined || typeof projectDir !== 'string') {
    return '';
  }
  const patterns = getGitignorePatterns(projectDir);
  const lines = [];

  function traverse(currentDir, depth = 0) {
    let files;
    try {
      files = fs.readdirSync(currentDir);
    } catch {
      return; // Skip unreadable directories
    }

    // Sort alphabetically for deterministic tree structure
    files.sort();

    for (const file of files) {
      const fullPath = path.join(currentDir, file);
      const relPath = path.relative(projectDir, fullPath);
      
      let stat;
      try {
        stat = fs.statSync(fullPath);
      } catch {
        continue; // Skip if stat fails
      }

      const isDir = stat.isDirectory();
      if (isIgnored(relPath, patterns, isDir)) {
        continue;
      }

      const indent = '  '.repeat(depth);
      if (isDir) {
        lines.push(`${indent}${file}/`);
        traverse(fullPath, depth + 1);
      } else {
        lines.push(`${indent}${file}`);
      }
    }
  }

  traverse(projectDir);
  return lines.join('\n');
}

/**
 * Helper to check if a file path is included in the Scout's list of relative paths.
 * Supports exact file matches and directory prefix matches.
 *
 * @param {string} filePath - The relative path of the file to check.
 * @param {string[]} includeList - Array of paths/directories to include.
 * @returns {boolean} - True if the path is semantically included.
 */
export function isPathIncluded(filePath, includeList) {
  if (!Array.isArray(includeList)) return false;
  const normalizedFile = filePath.replace(/\\/g, '/');

  for (let item of includeList) {
    if (typeof item !== 'string') continue;
    const normalizedItem = item.replace(/\\/g, '/');

    if (normalizedFile === normalizedItem) {
      return true;
    }

    // Directory prefix match (e.g., if "src" is in include list, "src/index.js" matches)
    const dirPrefix = normalizedItem.endsWith('/') ? normalizedItem : normalizedItem + '/';
    if (normalizedFile.startsWith(dirPrefix)) {
      return true;
    }
  }
  return false;
}

/**
 * Filters the codebase payload to only include files and directories matching the include list.
 * Supports both:
 * - Array of objects: [ { path: 'relative/path', content: '...' }, ... ] (filters by `file.path`)
 * - Array of strings: [ 'relative/path', ... ] (filters by string value)
 * - Object dictionary: { 'relative/path': 'content', ... } (filters keys)
 *
 * @param {Array|Object} payload - The unfiltered codebase payload.
 * @param {string[]} includeList - The list of allowed relative paths.
 * @returns {Array|Object} - The pruned payload.
 */
export function prunePayload(payload, includeList) {
  if (!includeList || !Array.isArray(includeList)) {
    return payload;
  }

  if (Array.isArray(payload)) {
    return payload.filter(file => {
      const filePath = typeof file === 'string' ? file : file.path;
      return isPathIncluded(filePath, includeList);
    });
  } else if (payload && typeof payload === 'object') {
    const pruned = {};
    for (const [filePath, content] of Object.entries(payload)) {
      if (isPathIncluded(filePath, includeList)) {
        pruned[filePath] = content;
      }
    }
    return pruned;
  }

  return payload;
}

/**
 * Calls the Scout model with the tree text and the objective, returning the list of paths to include.
 *
 * @param {object} params
 * @param {string} params.projectDir - Root project directory.
 * @param {string} params.userObjective - The user's query or objective.
 * @param {Function} [params.agent] - Optional agent override (useful for mock testing).
 * @param {object} [params.env] - Process env override.
 * @param {Function} [params.log] - Log callback.
 * @returns {Promise<string[]|null>} - List of relative paths to include, or null on failure.
 */
export async function runScoutPass({
  projectDir,
  userObjective,
  agent = null,
  env = process.env,
  log = () => {}
} = {}) {
  try {
    const treeText = generateTreeText(projectDir);

    let activeAgent = agent;
    if (!activeAgent) {
      // W4 (2026-07-05): the scout is a lightweight, high-volume curation pass — it reads a whole tree
      // to pick relevant paths — so it runs on the STANDARD (current, cheaper, high-context) agy LABEL,
      // resolved via the TRIO_TIER ladder. NEVER a hardcoded API-style id (the old hardcoded default
      // was a phantom id that live agy silently degrades to Flash anyway).
      const model = env.GANDALF_SCOUT_MODEL || env.GEMINI_MODEL
        || resolveGeminiModel({ env: { ...env, TRIO_TIER: 'standard' } });
      const seam = makeGeminiCliSeam({ model, env, log });
      activeAgent = seam.agent;
    }

    const prompt = `You are an agentic codebase scout. You are given a directory tree structure of a codebase and the user's objective.
Your task is to identify and return a list of files or directories that are semantically relevant to the user's objective and should be included in the context.

User Objective:
"${userObjective}"

Codebase Directory Tree:
\`\`\`
${treeText}
\`\`\`

Respond with a JSON object containing an "include" key with an array of relative paths (files or directories) to include.`;

    const schema = {
      type: 'object',
      properties: {
        include: {
          type: 'array',
          items: { type: 'string' }
        }
      },
      required: ['include']
    };

    const result = await activeAgent(prompt, { schema, label: 'scout-pass' });
    let includeList = null;

    if (typeof result === 'object' && result !== null) {
      includeList = result.include;
    } else if (typeof result === 'string') {
      const parsed = JSON.parse(result);
      includeList = parsed.include;
    }

    if (Array.isArray(includeList)) {
      return includeList;
    }
    throw new Error('Scout model response did not contain an array under the "include" key.');
  } catch (err) {
    log(`Scout pass error: ${err.message}`);
    return null;
  }
}

/**
 * High-level Scout pre-flight check wrapper.
 * Initiates the scout call and filters the payload. Gracefully falls back to the full payload on failure.
 *
 * @param {object} params
 * @param {string} params.projectDir - Root project directory.
 * @param {Array|Object} params.payload - Full payload.
 * @param {string} params.userObjective - User objective.
 * @param {Function} [params.agent] - Optional agent override.
 * @param {object} [params.env] - Process env override.
 * @param {Function} [params.log] - Log callback.
 * @returns {Promise<Array|Object>} - Filtered payload, or full payload on fallback.
 */
export async function scoutAndFilter({
  projectDir,
  payload,
  userObjective,
  agent = null,
  env = process.env,
  log = () => {}
} = {}) {
  const includeList = await runScoutPass({ projectDir, userObjective, agent, env, log });
  if (includeList === null) {
    log('Scout pass failed or returned malformed data. Gracefully falling back to full payload.');
    return payload;
  }
  return prunePayload(payload, includeList);
}
