// fast-gates.mjs — Pre-Execute Anvil AST Slice, Git-Diff Fast Baseline,
// Self-Contained Bounded Diff Builder, and Post-Gate Deterministic Fast-Gates
// (Tidy-Idy scratch hygiene, Aegis CWE security scan, Anvil AST syntax/diff gate,
// and hunk-scoped elegance test-trim verification).

import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isTestPath } from './delta-coverage-gate.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TRIO_ROOT = path.resolve(__dirname, '..', '..');

const MAX_SLICE_BYTES = 14 * 1024; // < 15 KB contract
const DEFAULT_MAX_DIFF_BYTES = 60 * 1024; // <= 60 KB inline diff contract

function sha256File(absPath) {
  return crypto.createHash('sha256').update(fs.readFileSync(absPath)).digest('hex');
}

function resolvePythonBin(env = process.env) {
  return env.PYTHON || env.ANCHOR_PYTHON || 'python';
}

/**
 * Resolve a Skill Foundry script (`aegis/scripts/aegis_engine.py`, `anvil/scripts/anvil_engine.py`)
 * via `ANCHOR_FOUNDRY_DIR` or sibling `Skill Foundry` checkout — zero hardcoded user paths.
 */
export function resolveFoundrySkillScript(skillName, scriptRelPath, env = process.env) {
  const candidates = [];
  if (env?.ANCHOR_FOUNDRY_DIR) {
    candidates.push(path.resolve(env.ANCHOR_FOUNDRY_DIR, 'skills', skillName, scriptRelPath));
    candidates.push(path.resolve(env.ANCHOR_FOUNDRY_DIR, skillName, scriptRelPath));
  }
  candidates.push(path.resolve(TRIO_ROOT, '..', 'Skill Foundry', 'skills', skillName, scriptRelPath));
  for (const cand of candidates) {
    try {
      if (fs.statSync(cand).isFile()) return cand;
    } catch { /* try next */ }
  }
  return null;
}

/**
 * True iff `projectDir` is itself a git repository root or git worktree root
 * (has `.git` dir/file and `git rev-parse --is-inside-work-tree` succeeds).
 */
export function isGitWorktreeOrRepoRoot(projectDir) {
  try {
    if (!projectDir || !fs.existsSync(path.join(projectDir, '.git'))) return false;
    const res = spawnSync('git', ['-C', projectDir, 'rev-parse', '--is-inside-work-tree'], {
      encoding: 'utf8',
      windowsHide: true,
      shell: false,
      timeout: 5000,
    });
    return res.status === 0 && String(res.stdout || '').trim() === 'true';
  } catch {
    return false;
  }
}

function readGitPorcelainPaths(projectDir) {
  try {
    const res = spawnSync(
      'git',
      ['-C', projectDir, '--no-optional-locks', '-c', 'core.quotepath=false', 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames'],
      {
        encoding: 'utf8',
        windowsHide: true,
        shell: false,
        timeout: 15000,
        maxBuffer: 16 * 1024 * 1024,
      },
    );
    if (res.status !== 0) return null;
    const out = [];
    for (const rec of String(res.stdout || '').split('\0')) {
      if (rec.length > 3) {
        const rel = rec.slice(3).replace(/\\/g, '/');
        if (rel) out.push(rel);
      }
    }
    return out;
  } catch {
    return null;
  }
}

/**
 * Capture an O(dirty-files) baseline for a git repo/worktree even when `gitCommit === false`,
 * avoiding expensive whole-repo SHA-256 `snapshotHashes` walks.
 */
export function makeGitDiffBaseline(projectDir, shouldSkipRel = () => false) {
  const dirty = readGitPorcelainPaths(projectDir);
  if (dirty === null) return null;
  const dirtyHashes = {};
  for (const rel of dirty) {
    if (shouldSkipRel(rel)) continue;
    const abs = path.join(projectDir, rel);
    try {
      dirtyHashes[rel] = fs.statSync(abs).isFile() ? sha256File(abs) : '(deleted)';
    } catch {
      dirtyHashes[rel] = '(deleted)';
    }
  }
  return { dirtyHashes };
}

/**
 * Measure per-wave file changes against `baseline` using `git status --porcelain=v1 -z`
 * in O(dirty-files) time. Returns `null` if git fails so caller can fall back cleanly.
 */
export function measuredGitDiffChanges(projectDir, baseline, shouldSkipRel = () => false) {
  if (!baseline || typeof baseline.dirtyHashes !== 'object') return null;
  const dirtyNow = readGitPorcelainPaths(projectDir);
  if (dirtyNow === null) return null;

  const changed = [];
  const seenNow = new Set();
  for (const rel of dirtyNow) {
    if (shouldSkipRel(rel)) continue;
    seenNow.add(rel);
    const abs = path.join(projectDir, rel);
    let curHash = '(deleted)';
    try {
      if (fs.statSync(abs).isFile()) curHash = sha256File(abs);
    } catch {
      curHash = '(deleted)';
    }
    if (!(rel in baseline.dirtyHashes)) {
      changed.push(curHash === '(deleted)' ? `${rel} (deleted)` : rel);
    } else if (baseline.dirtyHashes[rel] !== curHash) {
      changed.push(curHash === '(deleted)' ? `${rel} (deleted)` : rel);
    }
  }

  for (const [rel, prevHash] of Object.entries(baseline.dirtyHashes)) {
    if (seenNow.has(rel) || shouldSkipRel(rel)) continue;
    // Was dirty/untracked at wave start, now clean vs HEAD or deleted
    const abs = path.join(projectDir, rel);
    let curHash = '(deleted)';
    try {
      if (fs.statSync(abs).isFile()) curHash = sha256File(abs);
    } catch {
      curHash = '(deleted)';
    }
    if (curHash !== prevHash) {
      changed.push(curHash === '(deleted)' ? `${rel} (deleted)` : rel);
    }
  }

  return changed;
}

function fallbackSymbolSlice(projectDir, relFiles) {
  const blocks = [];
  let bytes = 0;
  for (const rel of relFiles) {
    const abs = path.join(projectDir, rel);
    let src = '';
    try { src = fs.readFileSync(abs, 'utf8'); } catch { continue; }
    const lines = src.split(/\r?\n/);
    const syms = [];
    const pyRe = /^(\s*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)\s*(\([^)]*\)|:)?/;
    const jsRe = /^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:(function|class)\s+([A-Za-z_$][\w$]*)\s*(\([^)]*\))?|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)/;
    for (let i = 0; i < lines.length && syms.length < 40; i++) {
      const ln = lines[i];
      if (rel.endsWith('.py')) {
        const m = pyRe.exec(ln);
        if (m) syms.push(`  - L${i + 1}: ${m[2]} ${m[3]}${(m[4] || '').slice(0, 80)}`);
      } else {
        const m = jsRe.exec(ln);
        if (m) {
          const kind = m[1] || 'fn';
          const name = m[2] || m[4];
          syms.push(`  - L${i + 1}: ${kind} ${name}${(m[3] || '').slice(0, 80)}`);
        }
      }
    }
    const chunk = `- \`${rel}\` (${lines.length} lines)` + (syms.length ? `\n${syms.join('\n')}` : '');
    if (bytes + Buffer.byteLength(chunk, 'utf8') > MAX_SLICE_BYTES) break;
    blocks.push(chunk);
    bytes += Buffer.byteLength(chunk, 'utf8') + 1;
  }
  return blocks.length ? blocks.join('\n') : '';
}

/**
 * Pre-`EXECUTE` Anvil AST Slice (<15 KB):
 * Resolves `anvil_engine.py slice` when available (graceful fallback/no-op otherwise)
 * so coding seats start with exact symbol names, signatures, and line spans.
 */
export function buildAnvilSlice(projectDir, targetFiles = [], env = process.env) {
  try {
    if (env?.FOREMAN_DISABLE_ANVIL_SLICE === '1') return '';
    const existing = [...new Set((targetFiles || []).map((f) => String(f || '').replace(/\\/g, '/').replace(/^\.\//, '')))]
      .filter((rel) => {
        if (!rel || rel.includes('..')) return false;
        try { return fs.statSync(path.join(projectDir, rel)).isFile(); } catch { return false; }
      })
      .slice(0, 20);
    if (existing.length === 0) return '';

    const anvilScript = resolveFoundrySkillScript('anvil', path.join('scripts', 'anvil_engine.py'), env);
    if (anvilScript) {
      const res = spawnSync(
        resolvePythonBin(env),
        [anvilScript, 'slice', '--repo', projectDir, '--files', ...existing],
        {
          cwd: projectDir,
          env,
          encoding: 'utf8',
          windowsHide: true,
          shell: false,
          timeout: 8000,
          maxBuffer: 4 * 1024 * 1024,
        },
      );
      if (res.status === 0 && res.stdout) {
        const parsed = JSON.parse(res.stdout);
        if (parsed && Array.isArray(parsed.files)) {
          const outLines = [];
          let usedBytes = 0;
          for (const f of parsed.files) {
            if (!f || !f.found) continue;
            const header = `- \`${f.file}\` (${f.total_lines ?? '?'} lines)`;
            const symLines = [];
            for (const s of (f.symbols || []).slice(0, 35)) {
              const span = s.end_lineno ? `L${s.lineno}-L${s.end_lineno}` : `L${s.lineno}`;
              const sig = String(s.signature || s.name || '').slice(0, 100);
              const callers = Array.isArray(s.callers) && s.callers.length
                ? ` [callers: ${s.callers.slice(0, 3).join(', ')}]`
                : '';
              symLines.push(`  - ${span}: \`${sig}\`${callers}`);
            }
            const block = symLines.length ? `${header}\n${symLines.join('\n')}` : header;
            const bLen = Buffer.byteLength(block, 'utf8') + 1;
            if (usedBytes + bLen > MAX_SLICE_BYTES) break;
            outLines.push(block);
            usedBytes += bLen;
          }
          if (outLines.length > 0) return outLines.join('\n');
        }
      }
    }
    return fallbackSymbolSlice(projectDir, existing);
  } catch {
    return '';
  }
}

/**
 * Build a self-contained bounded diff (`<= 60 KB` inline, with per-file summary if truncated)
 * so read-only review seats can verify small/medium waves without 6-10m of cold repo exploration.
 */
export function buildBoundedGitDiff(projectDir, changedFiles = [], { maxBytes = DEFAULT_MAX_DIFF_BYTES } = {}) {
  try {
    const cleanChanged = (changedFiles || [])
      .map((f) => String(f || '').replace(/\\/g, '/'))
      .filter(Boolean);
    if (cleanChanged.length === 0) return '(no changed files)';

    const livePaths = cleanChanged
      .filter((f) => !f.endsWith(' (deleted)'))
      .map((f) => f.replace(/\s+\(deleted\)$/, ''));
    const deletedPaths = cleanChanged
      .filter((f) => f.endsWith(' (deleted)'))
      .map((f) => f.replace(/\s+\(deleted\)$/, ''));

    const summaryLines = cleanChanged.map((entry) => {
      if (entry.endsWith(' (deleted)')) return `  - ${entry}`;
      const abs = path.join(projectDir, entry);
      try {
        const st = fs.statSync(abs);
        return `  - ${entry} (${st.size} B)`;
      } catch {
        return `  - ${entry}`;
      }
    });

    const parts = [`Changed file manifest (${cleanChanged.length}):\n${summaryLines.join('\n')}`];

    if (isGitWorktreeOrRepoRoot(projectDir)) {
      const diffPaths = [...livePaths, ...deletedPaths].slice(0, 60);
      if (diffPaths.length > 0) {
        const gd = spawnSync(
          'git',
          ['-C', projectDir, '--no-optional-locks', '-c', 'core.quotepath=false', 'diff', '--unified=3', 'HEAD', '--', ...diffPaths],
          {
            encoding: 'utf8',
            windowsHide: true,
            shell: false,
            timeout: 10000,
            maxBuffer: 8 * 1024 * 1024,
          },
        );
        if (gd.status === 0 && gd.stdout && gd.stdout.trim()) {
          parts.push(gd.stdout.trim());
        }
        // Include untracked new files that `git diff HEAD` omits
        const untrackedRes = spawnSync(
          'git',
          ['-C', projectDir, '--no-optional-locks', '-c', 'core.quotepath=false', 'ls-files', '--others', '--exclude-standard', '-z', '--', ...livePaths],
          { encoding: 'utf8', windowsHide: true, shell: false, timeout: 5000 },
        );
        if (untrackedRes.status === 0 && untrackedRes.stdout) {
          for (const uRel of untrackedRes.stdout.split('\0').filter(Boolean)) {
            const abs = path.join(projectDir, uRel);
            try {
              const txt = fs.readFileSync(abs, 'utf8');
              parts.push(`--- /dev/null\n+++ b/${uRel}\n${txt.slice(0, 12000)}`);
            } catch { /* binary or unreadable */ }
          }
        }
      }
    } else {
      for (const rel of livePaths.slice(0, 25)) {
        const abs = path.join(projectDir, rel);
        try {
          const txt = fs.readFileSync(abs, 'utf8');
          parts.push(`=== ${rel} ===\n${txt.slice(0, 8000)}`);
        } catch { /* skip */ }
      }
    }

    const joined = parts.join('\n\n');
    if (Buffer.byteLength(joined, 'utf8') <= maxBytes) return joined;

    // Truncate cleanly on UTF-8 character boundary within maxBytes
    let truncated = Buffer.from(joined, 'utf8').subarray(0, Math.max(1024, maxBytes - 180)).toString('utf8');
    // Strip any trailing replacement char from mid-codepoint slice
    truncated = truncated.replace(/\uFFFD+$/, '');
    return `${truncated}\n\n[... diff truncated at ${Math.round(maxBytes / 1024)} KB; inspect full files listed in manifest if needed ...]`;
  } catch {
    return '';
  }
}

const SCRATCH_PATTERNS = [
  /(^|\/)\.provider-schema-[^/]*$/i,
  /\.(?:bak|orig|tmp|swp)$/i,
  /\.(?:sqlite-wal|sqlite-shm|db-wal|db-shm)$/i,
  /(^|\/)_scratch[^/]*$/i,
  /~$/,
];

/**
 * Post-`GATE` Deterministic Fast-Gate 1: `Tidy-Idy` Scratch & Byproduct Hygiene Check.
 */
export function runFastHygieneGate(changedFiles = [], declaredAllowed = []) {
  const allowed = new Set((declaredAllowed || []).map((p) => String(p || '').replace(/\\/g, '/').replace(/^\.\//, '')));
  const findings = [];
  for (const raw of changedFiles || []) {
    const s = String(raw || '').replace(/\\/g, '/');
    if (!s || s.endsWith(' (deleted)')) continue;
    const rel = s.replace(/^\.\//, '');
    if (allowed.has(rel)) continue;
    if (SCRATCH_PATTERNS.some((re) => re.test(rel))) {
      findings.push({
        id: `${rel}:1+tidy-idy-hygiene`,
        severity: 'BLOCKER',
        file: rel,
        line: 1,
        rule: 'tidy-idy-hygiene',
        status: 'open',
        agreement: 2,
        repro_cmd: `node -e "const fs=require('fs'); if(fs.existsSync(${JSON.stringify(rel)})) process.exit(1)"`,
        repro_output: `untracked scratch/byproduct file present in workspace: ${rel}`,
        message: `[taxonomy:hygiene] remove untracked scratch/byproduct artifact "${rel}" (.bak/.provider-schema-*/.sqlite-wal/_scratch*) before review`,
      });
    }
  }
  return { pass: findings.length === 0, findings };
}

function scanPythonFileWithAegis(absPath, env = process.env) {
  const aegisScript = resolveFoundrySkillScript('aegis', path.join('scripts', 'aegis_engine.py'), env);
  if (aegisScript) {
    try {
      const res = spawnSync(
        resolvePythonBin(env),
        [aegisScript, 'scan', '--target', absPath],
        {
          env,
          encoding: 'utf8',
          windowsHide: true,
          shell: false,
          timeout: 15000,
          maxBuffer: 4 * 1024 * 1024,
        },
      );
      if (res.stdout && res.stdout.trim().startsWith('{')) {
        const rep = JSON.parse(res.stdout);
        if (Array.isArray(rep.findings)) {
          return rep.findings.filter((f) => {
            const sev = String(f.severity || '').toUpperCase();
            return sev === 'CRITICAL' || sev === 'HIGH';
          });
        }
      }
    } catch { /* fall through to lightweight regex fallback */ }
  }

  // Deterministic lightweight fallback when Skill Foundry Aegis script is absent
  let src = '';
  try { src = fs.readFileSync(absPath, 'utf8'); } catch { return []; }
  const out = [];
  const lines = src.split(/\r?\n/);
  const rules = [
    { id: 'AEG-01', cwe: 'CWE-78', sev: 'CRITICAL', re: /\bsubprocess\.(?:Popen|run|call|check_output|check_call)\s*\([^)]*\bshell\s*=\s*True\b/, msg: 'subprocess invoked with shell=True' },
    { id: 'AEG-02', cwe: 'CWE-502', sev: 'CRITICAL', re: /\bpickle\.loads?\s*\(/, msg: 'unsafe pickle deserialization' },
    { id: 'AEG-02', cwe: 'CWE-94', sev: 'HIGH', re: /(?:^|[^\w.])(?:eval|exec)\s*\(/, msg: 'dynamic code execution via eval/exec' },
  ];
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    if (/^\s*#/.test(ln)) continue;
    for (const r of rules) {
      if (r.re.test(ln)) {
        out.push({
          rule_id: r.id,
          cwe: r.cwe,
          severity: r.sev,
          line: i + 1,
          message: r.msg,
          snippet: ln.trim().slice(0, 120),
        });
      }
    }
  }
  return out;
}

function aegisFindingSignature(f) {
  return `${f.rule_id || f.cwe || 'CWE'}|${String(f.snippet || f.code || f.message || '').trim()}`;
}

/**
 * Capture pre-wave Aegis finding signatures on existing `.py` files so legacy untouched lines
 * do not false-block an unrelated localized fix, while any NEW sink blocks immediately.
 */
export function captureAegisBaseline(projectDir, env = process.env) {
  const cache = new Map();
  return function getBaselineForRel(relPath, preWaveContent = null) {
    if (cache.has(relPath)) return cache.get(relPath);
    if (preWaveContent == null) {
      // Try reading committed HEAD version if inside git repo
      if (isGitWorktreeOrRepoRoot(projectDir)) {
        try {
          const r = spawnSync('git', ['-C', projectDir, 'show', `HEAD:${relPath}`], {
            encoding: 'utf8',
            windowsHide: true,
            shell: false,
            timeout: 5000,
          });
          if (r.status === 0 && r.stdout) preWaveContent = r.stdout;
        } catch { /* new file */ }
      }
    }
    if (!preWaveContent) {
      const empty = new Set();
      cache.set(relPath, empty);
      return empty;
    }
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-aegis-base-'));
    const tmpFile = path.join(tmpDir, path.basename(relPath));
    try {
      fs.writeFileSync(tmpFile, preWaveContent, 'utf8');
      const baseFindings = scanPythonFileWithAegis(tmpFile, env);
      const sigs = new Set(baseFindings.map(aegisFindingSignature));
      cache.set(relPath, sigs);
      return sigs;
    } catch {
      const empty = new Set();
      cache.set(relPath, empty);
      return empty;
    } finally {
      try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch { /* ignore */ }
    }
  };
}

/**
 * Post-`GATE` Deterministic Fast-Gate 2: `Aegis` CWE Security Scan on changed non-test `.py` files.
 */
export function runFastAegisGate(projectDir, changedFiles = [], getBaseline = null, env = process.env) {
  if (env?.FOREMAN_DISABLE_AEGIS_GATE === '1') return { pass: true, findings: [] };
  const pyFiles = (changedFiles || [])
    .map((f) => String(f || '').replace(/\\/g, '/'))
    .filter((f) => f && !f.endsWith(' (deleted)') && f.toLowerCase().endsWith('.py') && !isTestPath(f));

  if (pyFiles.length === 0) return { pass: true, findings: [] };

  const findings = [];
  for (const rel of pyFiles) {
    const abs = path.join(projectDir, rel);
    if (!fs.existsSync(abs)) continue;
    const rawFindings = scanPythonFileWithAegis(abs, env);
    if (rawFindings.length === 0) continue;
    const baseSigs = typeof getBaseline === 'function' ? getBaseline(rel) : new Set();
    for (const f of rawFindings) {
      if (baseSigs.has(aegisFindingSignature(f))) continue;
      const line = Number(f.line || f.lineno || 1);
      const rule = String(f.rule_id || f.cwe || 'aegis-cwe');
      findings.push({
        id: `${rel}:${line}+${rule}`,
        severity: 'BLOCKER',
        file: rel,
        line,
        rule: `aegis-${rule.toLowerCase()}`,
        status: 'open',
        agreement: 2,
        repro_cmd: `aegis scan --target ${rel}`,
        repro_output: `${f.severity} ${rule} (${f.cwe || 'CWE'}) at ${rel}:${line}: ${f.message || f.title || 'security sink'}`,
        message: `[taxonomy:aegis-security] ${f.severity} ${rule} (${f.cwe || 'CWE'}) in ${rel}:${line} — ${f.message || f.title || 'unsafe security sink'}; remediate before review`,
      });
    }
  }
  return { pass: findings.length === 0, findings };
}

/**
 * Post-`GATE` Deterministic Fast-Gate 3: `Anvil` AST Syntax & Duplicate-Definition Gate.
 */
export function runFastAnvilAstGate(projectDir, changedFiles = [], env = process.env) {
  if (env?.FOREMAN_DISABLE_ANVIL_GATE === '1') return { pass: true, findings: [] };
  const live = (changedFiles || [])
    .map((f) => String(f || '').replace(/\\/g, '/'))
    .filter((f) => f && !f.endsWith(' (deleted)'));

  const pyFiles = live.filter((f) => f.toLowerCase().endsWith('.py') && fs.existsSync(path.join(projectDir, f)));
  const jsFiles = live.filter((f) => /\.(?:mjs|cjs|js)$/i.test(f) && fs.existsSync(path.join(projectDir, f)));

  const findings = [];

  if (pyFiles.length > 0) {
    const anvilScript = resolveFoundrySkillScript('anvil', path.join('scripts', 'anvil_engine.py'), env);
    let handledByAnvil = false;
    if (anvilScript) {
      try {
        const res = spawnSync(
          resolvePythonBin(env),
          [anvilScript, 'verify-diff', '--repo', projectDir, '--files', ...pyFiles, '--json'],
          {
            cwd: projectDir,
            env,
            encoding: 'utf8',
            windowsHide: true,
            shell: false,
            timeout: 12000,
            maxBuffer: 4 * 1024 * 1024,
          },
        );
        if (res.stdout && res.stdout.trim().startsWith('{')) {
          const rep = JSON.parse(res.stdout);
          handledByAnvil = true;
          for (const se of rep.syntax_errors || []) {
            const rel = String(se.file || pyFiles[0]).replace(/\\/g, '/');
            const ln = Number(se.line || se.lineno || 1);
            findings.push({
              id: `${rel}:${ln}+anvil-syntax`,
              severity: 'BLOCKER',
              file: rel,
              line: ln,
              rule: 'anvil-syntax',
              status: 'open',
              agreement: 2,
              repro_cmd: `python -m py_compile ${rel}`,
              repro_output: String(se.error || se.message || 'Python syntax error'),
              message: `[taxonomy:anvil-ast] syntax error in ${rel}:${ln} — ${se.error || se.message}`,
            });
          }
          for (const dd of rep.duplicate_definitions || []) {
            const rel = String(dd.file || pyFiles[0]).replace(/\\/g, '/');
            const ln = Number(dd.line || dd.second_line || 1);
            findings.push({
              id: `${rel}:${ln}+anvil-dup-def`,
              severity: 'BLOCKER',
              file: rel,
              line: ln,
              rule: 'anvil-duplicate-def',
              status: 'open',
              agreement: 2,
              repro_cmd: `anvil verify-diff --files ${rel}`,
              repro_output: `duplicate definition "${dd.name || dd.symbol || '?'}" in ${rel}:${ln}`,
              message: `[taxonomy:anvil-ast] duplicate top-level/class definition "${dd.name || dd.symbol || '?'}" in ${rel}:${ln}`,
            });
          }
        }
      } catch { /* fallback below */ }
    }
    if (!handledByAnvil) {
      for (const rel of pyFiles) {
        const abs = path.join(projectDir, rel);
        const r = spawnSync(resolvePythonBin(env), ['-m', 'py_compile', abs], {
          cwd: projectDir,
          encoding: 'utf8',
          windowsHide: true,
          shell: false,
          timeout: 8000,
        });
        if (r.status !== 0) {
          findings.push({
            id: `${rel}:1+anvil-syntax`,
            severity: 'BLOCKER',
            file: rel,
            line: 1,
            rule: 'anvil-syntax',
            status: 'open',
            agreement: 2,
            repro_cmd: `python -m py_compile ${rel}`,
            repro_output: String(r.stderr || r.stdout || 'py_compile failed').trim().slice(0, 300),
            message: `[taxonomy:anvil-ast] syntax error in ${rel}: ${String(r.stderr || r.stdout || '').trim().slice(0, 200)}`,
          });
        }
      }
    }
  }

  for (const rel of jsFiles) {
    const abs = path.join(projectDir, rel);
    const r = spawnSync(process.execPath, ['--check', abs], {
      cwd: projectDir,
      encoding: 'utf8',
      windowsHide: true,
      shell: false,
      timeout: 5000,
    });
    if (r.status !== 0) {
      findings.push({
        id: `${rel}:1+anvil-js-syntax`,
        severity: 'BLOCKER',
        file: rel,
        line: 1,
        rule: 'anvil-syntax',
        status: 'open',
        agreement: 2,
        repro_cmd: `node --check ${rel}`,
        repro_output: String(r.stderr || r.stdout || 'node --check failed').trim().slice(0, 300),
        message: `[taxonomy:anvil-ast] JS syntax error in ${rel}: ${String(r.stderr || r.stdout || '').trim().slice(0, 200)}`,
      });
    }
  }

  return { pass: findings.length === 0, findings };
}

const SKIP_MARKER_RE = /\b(?:it|test|describe|context|suite)\.(?:skip|xfail)\b|\b(?:xit|xtest|xdescribe)\s*\(|@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\(/i;

/**
 * Scope `releasedFoldedTests` / `releasedEleganceTests` validation to newly added/changed
 * diff lines only — never penalizing pre-existing untouched test assertions or helpers,
 * while refusing newly injected `.skip` / `xfail` markers inside the changed hunks.
 */
export function checkHunkScopedTestEdits(beforeContentsMap, projectDir, releasedFiles = []) {
  for (const rel of releasedFiles || []) {
    const abs = path.join(projectDir, rel);
    if (!fs.existsSync(abs)) continue; // whole-file removal was explicitly authorized by reviewer cut
    let afterTxt = '';
    try { afterTxt = fs.readFileSync(abs, 'utf8'); } catch { continue; }
    const beforeTxt = String(beforeContentsMap?.[rel] ?? '');
    if (afterTxt === beforeTxt) continue;

    // Bag-of-lines multiset diff so pre-existing untouched lines are ignored
    const beforeCounts = new Map();
    for (const ln of beforeTxt.split(/\r?\n/)) {
      beforeCounts.set(ln, (beforeCounts.get(ln) || 0) + 1);
    }
    const addedLines = [];
    for (const ln of afterTxt.split(/\r?\n/)) {
      const c = beforeCounts.get(ln) || 0;
      if (c > 0) beforeCounts.set(ln, c - 1);
      else addedLines.push(ln);
    }

    for (const added of addedLines) {
      if (SKIP_MARKER_RE.test(added)) {
        return `elegance trim added skip/xfail marker in released test hunk (${rel}: "${added.trim().slice(0, 80)}")`;
      }
    }
  }
  return null;
}

const VALID_ATTESTED_FAMILIES = new Set(['claude', 'gemini', 'grok', 'chatgpt']);

function isForemanInternalRelPath(relPath) {
  const norm = String(relPath || '').replace(/\\/g, '/').replace(/^\/+/, '');
  if (!norm) return true;
  if (
    norm === 'foreman-checkpoint.json'
    || norm === 'foreman.config.json'
    || /^_foreman-status/.test(norm)
    || /^_out-\d+/.test(norm)
  ) {
    return true;
  }
  const first = norm.split('/')[0];
  return ['.git', '.foreman', '.foreman-job', '.anchor', '.ecgberht'].includes(first);
}

/**
 * Unify raw physical receipts (`PHYSICAL_RECEIPT_HOOK`) + canonical `trio.seat.v1`
 * `onReceipt` into a complete per-call Foreman telemetry record so `calls[]`,
 * `phase-timings.jsonl`, `phase-report.mjs`, and `.foreman/run-record.json` carry
 * real duration, token, cost, model, and family attribution across all 4 CLI families.
 */
export function normalizeReceiptTelemetry({
  label = '(unlabeled)',
  role = 'default',
  physicalEntries = [],
  seatReceipt = null,
  wallDurationMs = 0,
  codingFamily = null,
  error = null,
} = {}) {
  let durationMs = 0;
  let inputTokens = 0;
  let outputTokens = 0;
  let totalTokens = 0;
  let costUsd = 0;
  let hasExplicitCost = false;
  let tools = 0;
  let permissionDenials = 0;
  let lastRaw = null;

  for (const entry of physicalEntries || []) {
    const r = entry?.receipt;
    if (!r || typeof r !== 'object') continue;
    lastRaw = r;
    if (typeof r.duration_ms === 'number' && Number.isFinite(r.duration_ms) && r.duration_ms > 0) {
      durationMs += r.duration_ms;
    }
    const u = r.usage && typeof r.usage === 'object' ? r.usage : {};
    const inTok = Number(u.input_tokens ?? u.inputTokens ?? r.input_tokens ?? 0) || 0;
    const outTok = Number(u.output_tokens ?? u.outputTokens ?? r.output_tokens ?? 0) || 0;
    const totTok = Number(u.total_tokens ?? u.totalTokens ?? r.total_tokens ?? (inTok + outTok)) || 0;
    inputTokens += inTok;
    outputTokens += outTok;
    totalTokens += totTok;
    const c = typeof r.cost_usd === 'number' ? r.cost_usd
      : (typeof r.total_cost_usd === 'number' ? r.total_cost_usd : null);
    if (c !== null && Number.isFinite(c)) {
      costUsd += c;
      hasExplicitCost = true;
    }
    if (typeof r.tools === 'number' && Number.isFinite(r.tools)) tools += r.tools;
    if (typeof r.permission_denials === 'number' && Number.isFinite(r.permission_denials)) {
      permissionDenials += r.permission_denials;
    }
  }

  if (durationMs <= 0 && Number.isFinite(wallDurationMs) && wallDurationMs > 0) {
    durationMs = Math.round(wallDurationMs);
  } else {
    durationMs = Math.round(durationMs);
  }

  let costEstimated = false;
  if (!hasExplicitCost && (inputTokens > 0 || outputTokens > 0)) {
    costUsd = Number(((inputTokens * 3 + outputTokens * 15) / 1_000_000).toFixed(6));
    costEstimated = true;
  }

  const ok = Boolean(seatReceipt ? seatReceipt.ok : (lastRaw?.ok && !error));
  const rawFamily = seatReceipt?.served?.family || lastRaw?.model_family || seatReceipt?.requested?.family || null;
  const family = typeof rawFamily === 'string' ? rawFamily.trim().toLowerCase() : null;
  const familyAttested = Boolean(
    ok && VALID_ATTESTED_FAMILIES.has(family)
    && (seatReceipt?.served?.family_attested === true || lastRaw?.family_attested === true),
  );
  const servedModel = seatReceipt?.served?.model || lastRaw?.model_served || null;
  const modelAttested = Boolean(
    ok && servedModel && (seatReceipt?.served?.model_attested === true || lastRaw?.model_attested === true),
  );
  const driver = seatReceipt?.attempts?.at(-1)?.requested?.driver
    || seatReceipt?.requested?.driver
    || null;
  const normCoding = typeof codingFamily === 'string' ? codingFamily.trim().toLowerCase() : '';
  const crossModel = Boolean(
    familyAttested && normCoding && VALID_ATTESTED_FAMILIES.has(normCoding) && family !== normCoding,
  );
  const providerStatus = error?.provider_status
    || seatReceipt?.attempts?.at(-1)?.transport_attempts?.at(-1)?.provider_status
    || seatReceipt?.error?.code
    || lastRaw?.status
    || (ok ? 'OK' : 'CLI_ERROR');
  const timedOut = Boolean(error?.exit?.timedOut || lastRaw?.timed_out || /timeout|timed_out/i.test(String(providerStatus)));
  const exitClass = ok ? 'OK' : (timedOut ? 'TIMEOUT' : String(providerStatus).toUpperCase());

  return {
    schema: 'foreman-call-telemetry/v1',
    label,
    role: String(role || 'default').toLowerCase(),
    driver,
    family,
    family_attested: familyAttested,
    served_model: servedModel,
    model_attested: modelAttested,
    cross_model: crossModel,
    failover_used: Boolean(seatReceipt?.failover?.used),
    ok,
    exit_class: exitClass,
    cli_status: typeof lastRaw?.cli_status === 'number' ? lastRaw.cli_status : (ok ? 0 : 1),
    signal: lastRaw?.signal || null,
    duration_ms: durationMs,
    tools,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens || (inputTokens + outputTokens),
    cost_usd: costUsd,
    cost_estimated: costEstimated,
    permission_denials: permissionDenials,
  };
}

/**
 * Compute the verified `changed_files` SHA-256 manifest and `attested_review` summary
 * for `.foreman/run-record.json` so Anchor `code_jobs.py` can fast-path landing when
 * Foreman already ran a genuine cross-family review over the exact file hashes.
 */
export function buildAttestedRunManifest({
  projectDir,
  foremanDir,
  initialHead = null,
  result = null,
  calls = [],
  codingFamily = null,
} = {}) {
  if (!result || result.status !== 'DONE') {
    return { changed_files: null, attested_review: null };
  }
  const waveResults = Array.isArray(result.waveResults) ? result.waveResults : [];
  const rawSet = new Set();
  for (const w of waveResults) {
    for (const f of w.changedFiles || []) {
      if (f) rawSet.add(String(f));
    }
  }
  if (projectDir && isGitWorktreeOrRepoRoot(projectDir)) {
    const gitMeasured = measuredGitDiffChanges(
      projectDir,
      { dirtyHashes: {} },
      isForemanInternalRelPath,
    );
    for (const f of gitMeasured || []) {
      if (f) rawSet.add(String(f));
    }
    if (initialHead) {
      const diffCommitted = spawnSync('git', ['diff', '--name-only', '-z', `${initialHead}..HEAD`], {
        cwd: projectDir,
        encoding: 'utf8',
        windowsHide: true,
        shell: false,
        timeout: 10000,
      });
      if (diffCommitted.status === 0 && diffCommitted.stdout) {
        for (const f of diffCommitted.stdout.split('\0')) {
          if (f) rawSet.add(f.replace(/\\/g, '/'));
        }
      }
    }
  }

  const changedFiles = {};
  for (const entry of [...rawSet].sort()) {
    const deleted = entry.endsWith(' (deleted)');
    const cleanRel = (deleted ? entry.slice(0, -' (deleted)'.length) : entry).replace(/\\/g, '/').replace(/^\/+/, '');
    if (isForemanInternalRelPath(cleanRel)) continue;
    const abs = path.join(projectDir, cleanRel);
    if (deleted || !fs.existsSync(abs)) {
      changedFiles[cleanRel] = 'DELETED';
    } else {
      try {
        if (fs.statSync(abs).isFile()) {
          changedFiles[cleanRel] = sha256File(abs);
        }
      } catch { /* ignore transient */ }
    }
  }

  const everyWaveReviewed = waveResults.length > 0 && waveResults.every((w) => {
    if (w.status !== 'GO') return false;
    if (!w.reviewSummary) return true;
    return (w.reviewSummary.completedReviewers ?? 0) >= 1 && (w.reviewSummary.blockingFindings ?? 0) === 0;
  });

  const reviewCalls = (calls || []).filter((c) => c && c.ok && c.role === 'review');
  const codingCalls = (calls || []).filter((c) => c && c.ok && (c.role === 'execute' || c.role === 'fix'));
  const codingFamilies = new Set(
    [codingFamily, ...codingCalls.map((c) => c.family)]
      .filter(Boolean)
      .map((f) => String(f).trim().toLowerCase())
      .filter((f) => VALID_ATTESTED_FAMILIES.has(f)),
  );
  const reviewFamilies = [...new Set(
    reviewCalls
      .map((c) => String(c.family || '').trim().toLowerCase())
      .filter((f) => VALID_ATTESTED_FAMILIES.has(f)),
  )];
  const allReviewsAttested = reviewCalls.length > 0 && reviewCalls.every(
    (c) => c.family_attested === true && VALID_ATTESTED_FAMILIES.has(String(c.family || '').trim().toLowerCase()),
  );
  const isCrossModel = Boolean(
    everyWaveReviewed
    && allReviewsAttested
    && codingFamilies.size > 0
    && reviewFamilies.length > 0
    && reviewFamilies.every((rf) => !codingFamilies.has(rf)),
  );
  const lastReview = reviewCalls.at(-1) || null;
  const attestedReview = {
    go: Boolean(everyWaveReviewed && reviewCalls.length > 0),
    cross_model: isCrossModel,
    family: lastReview?.family || null,
    families: reviewFamilies,
    coding_families: [...codingFamilies],
    model_served: lastReview?.served_model || null,
    family_attested: allReviewsAttested,
    model_attested: reviewCalls.length > 0 && reviewCalls.every((c) => c.model_attested === true),
    review_calls: reviewCalls.length,
    blocking_findings: 0,
    reviewed_at: new Date().toISOString(),
  };

  return { changed_files: changedFiles, attested_review: attestedReview };
}
