// tier0-and-simplifier.mjs — Shell-free (`shell: false`, CWE-78 safe) Tier-0
// Fail-Fast Targeted Test Pre-Check, Pre-Execute Reusable Repo Helper Discovery,
// Granular File/Symbol Elegance Elements (`file::symbol`), and Symbol-Cut Verifier.

import fs from 'node:fs';
import path from 'node:path';
import { isTestPath } from './delta-coverage-gate.mjs';

export const INFRA_HELPER_NAMES = new Set([
  'exclusive_file_lock',
  'atomic_write_json',
  '_atomic_write_json',
  'write_json_atomic',
  'resolve_contained_path',
  '_is_symlink_or_junction',
  'atomicWriteJson',
  'writeFileAtomic',
]);

const REUSABLE_HELPER_FILE_RE = /(?:^|\/)(?:paths|job_runner|deliverables|reliability|atomic|lock|shared|common|utils?|helpers?|fs[-_]?utils?|io[-_]?utils?)\.(?:py|m?js|cjs|ts)$/i;
const SAFE_PYTEST_NODE_SUFFIX_RE = /^(?:::[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_.,: /=-]*\])?)+$/;

function countLines(txt) {
  if (!txt) return 0;
  return String(txt).split(/\r?\n/).length;
}

function isInternalForemanRel(rel) {
  return /^\.foreman\//i.test(rel) || rel === 'foreman-checkpoint.json';
}

export function walkBoundedRepoFiles(projectDir, maxFiles = 200) {
  const out = [];
  const skip = new Set(['node_modules', '.git', '.foreman', '.crucible', '.anchor', '__pycache__', '.pytest_cache', 'vendor', 'dist', 'build', 'bundle', 'bundle_staging', '_archive']);
  function walk(dir, depth) {
    if (depth > 5 || out.length >= maxFiles) return;
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (out.length >= maxFiles) break;
      if (skip.has(e.name) || (e.name.startsWith('.') && e.name !== '.github')) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (e.isFile()) out.push(path.relative(projectDir, full).replace(/\\/g, '/'));
    }
  }
  walk(projectDir, 0);
  return out;
}

export function extractTopLevelFunctionDefs(src, rel = '') {
  const defs = [];
  const isPy = /\.py$/i.test(rel);
  const lines = String(src || '').split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    const m = isPy
      ? ln.match(/^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/)
      : ln.match(/^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(/);
    if (!m) continue;
    let decorated = false;
    if (isPy) {
      for (let j = i - 1; j >= 0; j--) {
        const prev = lines[j].trim();
        if (!prev || prev.startsWith('#')) continue;
        if (prev.startsWith('@')) decorated = true;
        break;
      }
    }
    defs.push({ name: m[1], line: i + 1, decorated });
  }
  return defs;
}

/**
 * Verify that a symbol-level elegance cut (`file::symbol`) strictly removed `symbol`
 * from top-level defs, left all other top-level defs intact, and reduced file line count.
 */
export function verifySymbolEleganceRemoval(beforeTxt, afterTxt, rel, symbol) {
  if (!symbol || typeof afterTxt !== 'string') return false;
  if (countLines(afterTxt) >= countLines(beforeTxt)) return false;
  const beforeNames = extractTopLevelFunctionDefs(beforeTxt, rel).map((d) => d.name);
  const afterNames = extractTopLevelFunctionDefs(afterTxt, rel).map((d) => d.name);
  if (!beforeNames.includes(symbol) || afterNames.includes(symbol)) return false;
  const expected = beforeNames.filter((n) => n !== symbol);
  return afterNames.length === expected.length && expected.every((n, i) => afterNames[i] === n);
}

/**
 * Discover existing reusable helper modules in `projectDir` (<= 1.4 KB prompt summary,
 * 0 LLM calls) so `executePrompt` steers builders to import existing lock/atomic/path
 * primitives on iteration 0 instead of re-implementing them.
 */
export function discoverReusableRepoHelpers(projectDir, { maxModules = 10, maxBytes = 1400 } = {}) {
  if (!projectDir || !fs.existsSync(projectDir)) return '';
  const files = walkBoundedRepoFiles(projectDir, 160);
  const rows = [];
  for (const rel of files) {
    if (rows.length >= maxModules) break;
    if (isTestPath(rel) || isInternalForemanRel(rel)) continue;
    if (!/\.(?:py|m?js|cjs|ts)$/i.test(rel)) continue;
    const abs = path.join(projectDir, rel);
    let txt = '';
    try {
      const st = fs.statSync(abs);
      if (!st.isFile() || st.size > 256_000) continue;
      txt = fs.readFileSync(abs, 'utf8');
    } catch { continue; }
    const defs = extractTopLevelFunctionDefs(txt, rel).map((d) => d.name);
    const constExports = [...txt.matchAll(/^(?:export\s+const\s+|([A-Z][A-Z0-9_]{2,})\s*=)([A-Za-z0-9_$]*)/gm)]
      .map((m) => m[1] || m[2])
      .filter(Boolean);
    const allSyms = [...new Set([...defs, ...constExports])];
    const infraHits = allSyms.filter((s) => INFRA_HELPER_NAMES.has(s) || /^(?:WRITE_LOCK|load_record|makeReliableAgent)$/.test(s));
    if (infraHits.length > 0 || (REUSABLE_HELPER_FILE_RE.test(rel) && allSyms.some((s) => !s.startsWith('_')))) {
      const exported = [
        ...infraHits,
        ...allSyms.filter((s) => !s.startsWith('_') && !infraHits.includes(s)),
      ].slice(0, 8);
      if (exported.length > 0) rows.push(`- ${rel}: ${exported.join(', ')}`);
    }
  }
  if (!rows.length) return '';
  let out = rows.join('\n');
  if (Buffer.byteLength(out, 'utf8') > maxBytes) out = out.slice(0, maxBytes - 4) + '\n...';
  return out;
}

/**
 * Build compact per-file line-delta summary & granular file/symbol elements for
 * `eleganceInReview` and `driver.elegance` (`runElegancePass`), allowing the
 * Rabbit-Catcher pass to CUT individual overbuilt functions (`file::fn`) without
 * having to delete an entire required deliverable file.
 */
export function buildWaveEleganceElements(projectDir, changedFiles = [], getBeforeLines = null, getBeforeContent = null) {
  const beforeContentFn = typeof getBeforeContent === 'function' ? getBeforeContent : () => '';
  const elements = [];
  const summaryRows = [];
  let fIdx = 0;
  let sIdx = 0;

  for (const raw of changedFiles || []) {
    const rel = String(raw || '').replace(/\\/g, '/').replace(/^\.\//, '');
    if (!rel || rel.endsWith(' (deleted)') || isInternalForemanRel(rel)) continue;
    const abs = path.join(projectDir, rel);
    const isTest = isTestPath(rel);
    let afterTxt = '';
    let afterLines = 0;
    try {
      if (fs.existsSync(abs)) {
        afterTxt = fs.readFileSync(abs, 'utf8');
        afterLines = countLines(afterTxt);
      }
    } catch { /* ignore */ }
    const beforeLines = typeof getBeforeLines === 'function' ? Number(getBeforeLines(rel) || 0) : 0;
    const delta = afterLines - beforeLines;
    const sign = delta >= 0 ? `+${delta}` : `${delta}`;
    summaryRows.push(`${rel} (${sign} net, ${afterLines} total lines)`);
    fIdx++;
    elements.push({
      id: `F${fIdx}`,
      text: rel,
      kind: isTest ? 'malleability' : 'element',
      detail: `${sign} net lines (${beforeLines} -> ${afterLines} lines)`,
    });

    if (!isTest && delta >= 50 && /\.(?:py|m?js|cjs)$/i.test(rel) && sIdx < 16) {
      const beforeTxt = beforeLines > 0 ? String(beforeContentFn(rel) || '') : '';
      const beforeNames = new Set(extractTopLevelFunctionDefs(beforeTxt, rel).map((d) => d.name));
      for (const d of extractTopLevelFunctionDefs(afterTxt, rel)) {
        if (beforeNames.has(d.name) || sIdx >= 16) continue;
        sIdx++;
        elements.push({
          id: `S${sIdx}`,
          text: `${rel}::${d.name}`,
          kind: 'element',
          detail: `newly added function at ${rel}:${d.line} (file delta ${sign} lines)`,
        });
      }
    }
  }

  return {
    elements,
    locSummary: summaryRows.slice(0, 20).join(', '),
  };
}

function splitPytestBracketSafe(rawLine) {
  let depth = 0;
  for (let i = 0; i < rawLine.length; i++) {
    const c = rawLine[i];
    if (c === '[') depth++;
    else if (c === ']') depth = Math.max(0, depth - 1);
    else if (depth === 0 && rawLine.startsWith(' - ', i)) return rawLine.slice(0, i).trim();
  }
  return rawLine.trim();
}

function resolveContainedRealRel(projectDir, candidatePath) {
  try {
    const realRoot = fs.realpathSync(projectDir);
    const abs = path.resolve(projectDir, candidatePath);
    if (!fs.existsSync(abs)) return null;
    const realAbs = fs.realpathSync(abs);
    const rel = path.relative(realRoot, realAbs);
    if (!rel || path.isAbsolute(rel) || rel === '..' || rel.startsWith('..' + path.sep)) {
      return null;
    }
    return rel.replace(/\\/g, '/');
  } catch {
    return null;
  }
}

export function extractTier0Targets(gateArtifact, projectDir) {
  if (!gateArtifact || gateArtifact.green || gateArtifact.timed_out || gateArtifact.vacuous_reason) {
    return { runner: null, targets: [] };
  }
  const merged = `${gateArtifact.stdout || ''}\n${gateArtifact.stderr || ''}`;
  const pyTargets = [];
  const pySeen = new Set();
  const addPyCandidate = (cand) => {
    const clean = String(cand || '').trim().replace(/^['"]+|['"]+$/g, '');
    if (!clean || pySeen.has(clean)) return;
    const filePart = clean.split('::')[0].replace(/\\/g, '/');
    if (!/\.py$/i.test(filePart)) return;
    const relFile = resolveContainedRealRel(projectDir, filePart);
    if (!relFile) return;
    const rawSuffix = clean.includes('::') ? clean.slice(clean.indexOf('::')) : '';
    const safeSuffix = rawSuffix && SAFE_PYTEST_NODE_SUFFIX_RE.test(rawSuffix) ? rawSuffix : '';
    const norm = `${relFile}${safeSuffix}`;
    if (!pySeen.has(norm) && pyTargets.length < 12) {
      pySeen.add(norm);
      pyTargets.push(norm);
    }
  };

  for (const line of merged.split(/\r?\n/)) {
    let m;
    if ((m = /^(?:FAILED|ERROR)\s+(.+)$/.exec(line.trim()))) {
      addPyCandidate(splitPytestBracketSafe(m[1]));
    } else if ((m = /^(\S.*?\.py(?:::[^\s]+)?)\s+(?:FAILED|ERROR)(?:\s+\[\s*\d+%\])?\s*$/.exec(line.trim()))) {
      addPyCandidate(m[1]);
    }
  }
  if (pyTargets.length > 0) return { runner: 'pytest', targets: pyTargets };

  const nodeTargets = [];
  const nodeSeen = new Set();
  const fileRe = /([A-Za-z0-9_./\\:-]+?\.(?:test|spec)\.(?:m?js|cjs))\b/g;
  let m;
  while ((m = fileRe.exec(merged)) !== null && nodeTargets.length < 12) {
    const rawRel = m[1].replace(/^\.\//, '');
    const rel = resolveContainedRealRel(projectDir, rawRel);
    if (!rel || nodeSeen.has(rel)) continue;
    nodeSeen.add(rel);
    nodeTargets.push(rel);
  }
  if (nodeTargets.length > 0) return { runner: 'node', targets: nodeTargets };

  return { runner: null, targets: [] };
}

export function buildTier0Command(waveTestCommand, tier0Info, projectDir, env = process.env) {
  if (!tier0Info || !tier0Info.runner || !Array.isArray(tier0Info.targets) || tier0Info.targets.length === 0) {
    return null;
  }
  const cmdStr = String(waveTestCommand || '').trim();
  if (/[;&|]|\bcd\s+|\bset\s+\w+=|^[A-Za-z_]\w*=|--(?:import|loader|require|rootdir)\b|\s-c\s+/i.test(cmdStr)) {
    return null;
  }

  if (tier0Info.runner === 'pytest') {
    if (tier0Info.targets.length === 1 && cmdStr.includes(tier0Info.targets[0]) && !cmdStr.includes('run-all')) {
      return null;
    }
    const firstTokMatch = cmdStr.match(/^(?:"([^"]+)"|(\S+))/);
    const rawFirst = firstTokMatch ? (firstTokMatch[1] || firstTokMatch[2] || '') : '';
    const baseFirst = path.basename(rawFirst);
    const pyFile = /^python[0-9.]*(?:\.exe)?$/i.test(baseFirst)
      ? rawFirst
      : (env?.PYTHON || env?.ANCHOR_PYTHON || 'python');
    const args = ['-B', '-m', 'pytest', '-p', 'no:cacheprovider', '-v', ...tier0Info.targets];
    return {
      file: pyFile,
      args,
      display: `${pyFile} ${args.join(' ')}`,
    };
  }

  if (tier0Info.runner === 'node') {
    if (tier0Info.targets.length === 1 && cmdStr.endsWith(tier0Info.targets[0]) && /--test\b/.test(cmdStr)) {
      return null;
    }
    const args = ['--test', ...tier0Info.targets];
    return {
      file: process.execPath,
      args,
      display: `${process.execPath} ${args.join(' ')}`,
    };
  }

  return null;
}
