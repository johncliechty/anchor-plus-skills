// server.mjs — THIN real-data server for the Foundry GUI.
// Plain Node http, zero dependencies. Serves the built app from ./dist and
// exposes /api endpoints backed by REAL files:
//   - skill manifest:  ../foundry_map_v2.json
//   - per-skill files: <source>/SKILL.md + <source>/journal/*.md
//   - global north star: C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md
// Plus the REAL learning loop: POST /api/foundry/sleep_session/{propose,apply,
// rollback} spawn the foundry-v2 kernel CLI (sleep-kernel-cli.mjs) headlessly
// and return its genuine JSON records — never a fabricated proposal.
// Every value traces to a file on disk; missing data yields honest empties.
// NOTE: no Date.now()/new Date() anywhere — the only timestamps served are
// real file mtimes; anything else is 0.

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const DIST_DIR = path.join(__dirname, 'dist');
const MANIFEST_PATH = process.env.FOUNDRY_MAP || path.resolve(__dirname, '..', 'foundry_map_v2.json');
const FOUNDRY_ROOT = process.env.FOUNDRY_ROOT || 'C:/dev/Skill Foundry';
const NORTH_STAR_PATH = process.env.FOUNDRY_NORTH_STAR || 'C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md';

// ── The REAL sleep-session kernel (foundry-v2 kernel build, Wave 2) ─────────
// Every /api/foundry/sleep_session/* endpoint spawns this CLI — the genuine
// propose→apply→rollback loop. Nothing here fabricates a proposal.
const KERNEL_DIR = process.env.FOUNDRY_KERNEL_DIR
  || 'C:/dev/skill-foundry-kernel-wt/planning/portfolio-program';
const KERNEL_CLI = path.join(KERNEL_DIR, 'src', 'sleep-kernel-cli.mjs');
const SKILLS_ROOT = process.env.FOUNDRY_SKILLS_ROOT || 'C:/dev/Skill Foundry/skills';
// The git repo whose HEAD is the FROZEN baseline (apply branches off it).
const SKILLS_REPO = process.env.FOUNDRY_SKILLS_REPO || path.dirname(SKILLS_ROOT);
// Where proposal artifacts land (one dir per run: proposal.json, units/, …).
const SLEEP_RUNS_DIR = process.env.FOUNDRY_SLEEP_RUNS || path.join(__dirname, 'sleep-runs');
const KERNEL_TIMEOUT_MS = Number(process.env.FOUNDRY_KERNEL_TIMEOUT_MS) || 180000;
const PORT = Number(process.env.PORT) || 8780;

const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/plain; charset=utf-8'
};

// ---------- safe fs helpers (a missing file is an honest empty, never a crash) ----------

function readTextSafe(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch {
    return null;
  }
}

function statSafe(filePath) {
  try {
    return fs.statSync(filePath);
  } catch {
    return null;
  }
}

function readDirSafe(dirPath) {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true });
  } catch {
    return [];
  }
}

// ---------- the REAL sleep-session kernel (spawned, never simulated) ----------

/** Read + parse a JSON request body (small, bounded). Rejects on malformed JSON. */
function readJsonBody(req, limitBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limitBytes) {
        reject(new Error('request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8');
      if (!text.trim()) return resolve({});
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(new Error('request body is not valid JSON'));
      }
    });
    req.on('error', reject);
  });
}

/**
 * Spawn the kernel CLI (node <KERNEL_CLI> <verb> <args…>) headlessly.
 * Never throws — resolves { status, stdout, stderr, timedOut } so the caller
 * can surface the kernel's honest exit codes (0 ok / 3 refused / 1 blocked).
 */
function runKernel(args) {
  return new Promise((resolve) => {
    execFile(
      process.execPath,
      [KERNEL_CLI, ...args],
      {
        cwd: KERNEL_DIR,
        windowsHide: true,
        timeout: KERNEL_TIMEOUT_MS,
        killSignal: 'SIGKILL',
        maxBuffer: 64 * 1024 * 1024,
        encoding: 'utf8'
      },
      (err, stdout, stderr) => {
        resolve({
          status: err ? (typeof err.code === 'number' ? err.code : null) : 0,
          spawnError: err && typeof err.code !== 'number' ? String(err.message || err) : null,
          timedOut: Boolean(err && err.killed),
          stdout: stdout || '',
          stderr: stderr || ''
        });
      }
    );
  });
}

/** Parse the kernel's single-JSON-document stdout; null when unparseable. */
function parseKernelJson(stdout) {
  const text = (stdout || '').trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Resolve the proposal dir from { proposalPath | proposalId }. The result must
 * live inside SLEEP_RUNS_DIR (every proposal this server mints does) — a path
 * outside it is refused (null).
 */
function resolveProposalDir(body) {
  let candidate = null;
  if (body && typeof body.proposalPath === 'string' && body.proposalPath.trim()) {
    candidate = path.resolve(body.proposalPath.trim());
  } else if (body && typeof body.proposalId === 'string' && body.proposalId.trim()) {
    candidate = path.join(SLEEP_RUNS_DIR, path.basename(body.proposalId.trim()));
  }
  if (!candidate) return null;
  const runsRoot = path.resolve(SLEEP_RUNS_DIR);
  const normalized = path.resolve(candidate);
  if (normalized !== runsRoot && !normalized.startsWith(runsRoot + path.sep)) return null;
  return normalized;
}

/** REAL sleep-run stats from the artifacts on disk (a run = a proposal.json dir). */
function sleepRunStats() {
  let runs = 0;
  let lastImproved = null;
  for (const dirent of readDirSafe(SLEEP_RUNS_DIR)) {
    if (!dirent.isDirectory()) continue;
    const runDir = path.join(SLEEP_RUNS_DIR, dirent.name);
    if (!statSafe(path.join(runDir, 'proposal.json'))) continue;
    runs += 1;
    const applyPath = path.join(runDir, 'apply-result.json');
    const applyStat = statSafe(applyPath);
    if (applyStat) {
      try {
        const record = JSON.parse(readTextSafe(applyPath) || 'null');
        if (record && record.outcome === 'applied') {
          lastImproved = Math.max(lastImproved || 0, applyStat.mtimeMs);
        }
      } catch {
        /* an unreadable record contributes nothing */
      }
    }
  }
  return { runs, lastImproved };
}

/** Honest summary derived from the real run artifacts (never a canned success). */
function buildSummary() {
  const { runs, lastImproved } = sleepRunStats();
  if (runs === 0) {
    return 'No sleep session has run yet — use "Run sleep session" in the Sleep & Training tile to propose one from the journal.';
  }
  return `${runs} sleep-session run(s) recorded under sleep-runs/` +
    (lastImproved ? ' (at least one proposal applied on a branch).' : ' (no proposal applied yet).');
}

// ---------- real-data extraction ----------

/** Resolve a manifest `source` to an absolute directory. */
function resolveSource(source) {
  if (!source) return null;
  if (/^[A-Za-z]:[\\/]/.test(source)) return source;
  return path.join(FOUNDRY_ROOT, source);
}

/** Parse SKILL.md into { description, body }. Frontmatter is optional. */
function parseSkillMd(text) {
  if (!text) return { description: '', body: '' };
  let body = text;
  let description = '';
  const fmMatch = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (fmMatch) {
    body = text.slice(fmMatch[0].length);
    const descMatch = fmMatch[1].match(/^description:\s*(.+)$/m);
    if (descMatch) description = descMatch[1].trim();
  }
  return { description, body };
}

/**
 * Parse HUMAN.md (people-first skill card) into a short blurb + body.
 * Prefer "**One sentence:** …" then first non-heading paragraph.
 * Agent SKILL.md YAML description is NOT used for human-facing surfaces.
 */
function parseHumanMd(text) {
  if (!text) return { oneSentence: '', body: '' };
  const body = String(text).trim();
  let oneSentence = '';
  const m = body.match(/\*\*One sentence:\*\*\s*(.+?)(?:\r?\n|$)/i)
    || body.match(/^One sentence:\s*(.+?)(?:\r?\n|$)/im);
  if (m) oneSentence = m[1].trim().replace(/\s+/g, ' ');
  if (!oneSentence) {
    // First non-heading, non-empty line
    for (const line of body.split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      oneSentence = t.replace(/^\*\*|\*\*$/g, '').trim();
      break;
    }
  }
  return { oneSentence, body };
}

/** Top-level "## " section titles from the SKILL.md body — the real documented structure. */
function extractSections(body) {
  if (!body) return [];
  const sections = [];
  for (const line of body.split(/\r?\n/)) {
    const m = line.match(/^##\s+(.+)$/);
    if (m) sections.push(m[1].trim());
  }
  return sections;
}

/** First paragraph of the body (used as a per-skill north star fallback). */
function firstParagraph(body) {
  if (!body) return '';
  const blocks = body.split(/\r?\n\s*\r?\n/);
  for (const block of blocks) {
    const trimmed = block.trim();
    if (trimmed) return trimmed;
  }
  return '';
}

/**
 * Real journal entries for a skill dir: files directly in <dir>/journal/*.md,
 * ignoring README.md, subdirectories (round-*, etc.) and all-caps files
 * (SYNTHESIS.md and kin). Each entry = { event, timestamp (mtime ms),
 * status: 'success', details (first ~280 chars of the body) }.
 */
function journalEvents(skillDir) {
  const journalDir = path.join(skillDir, 'journal');
  const events = [];
  for (const dirent of readDirSafe(journalDir)) {
    if (!dirent.isFile()) continue;
    const fileName = dirent.name;
    if (!fileName.toLowerCase().endsWith('.md')) continue;
    if (fileName.toLowerCase() === 'readme.md') continue;
    const base = fileName.replace(/\.md$/i, '');
    // all-caps entries (SYNTHESIS.md etc.) are not run records
    if (/[A-Z]/.test(base) && !/[a-z]/.test(base)) continue;

    const filePath = path.join(journalDir, fileName);
    const stat = statSafe(filePath);
    if (!stat) continue;
    const text = readTextSafe(filePath) || '';

    // Title: first "# " heading, else first non-empty line, else the filename.
    let title = '';
    const headingMatch = text.match(/^#\s+(.+)$/m);
    if (headingMatch) {
      title = headingMatch[1].trim();
    } else {
      const firstLine = text.split(/\r?\n/).find((l) => l.trim());
      title = firstLine ? firstLine.trim() : base;
    }

    // Details: entry body minus the title heading line, first ~280 chars.
    let details = text;
    if (headingMatch) details = details.replace(headingMatch[0], '');
    details = details.trim().slice(0, 280);

    events.push({
      event: title,
      timestamp: stat.mtimeMs,
      status: 'success',
      details
    });
  }
  events.sort((a, b) => b.timestamp - a.timestamp);
  return events;
}

/** Load the manifest fresh; [] when missing/unparseable. */
function loadManifest() {
  const text = readTextSafe(MANIFEST_PATH);
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed.skills) ? parsed.skills : [];
  } catch {
    return [];
  }
}

/** Build the full real /api/skills payload from the manifest + each skill's files. */
function buildSkills() {
  return loadManifest().map((entry) => {
    const skillDir = resolveSource(entry.source);
    const skillMdText = skillDir ? readTextSafe(path.join(skillDir, 'SKILL.md')) : null;
    const humanMdText = skillDir ? readTextSafe(path.join(skillDir, 'HUMAN.md')) : null;
    const { description: agentDescription, body } = parseSkillMd(skillMdText);
    const human = parseHumanMd(humanMdText);
    // Human-facing surfaces prefer HUMAN.md one-sentence + body; fall back to SKILL.md.
    const description = human.oneSentence || agentDescription || firstParagraph(body);
    const northStar = human.body
      ? human.body.slice(0, 4000)
      : (agentDescription || firstParagraph(body));
    const timeline = skillDir ? journalEvents(skillDir) : [];
    const edges = Array.isArray(entry.edges) ? entry.edges : [];
    // Human card sections (## Use this when, etc.) for Capabilities tile when present
    const humanSections = human.body ? extractSections(human.body) : [];
    const agentSections = extractSections(body);

    return {
      ref: entry.ref || '',
      name: entry.name || '',
      source: entry.source || '',
      status: entry.status || '',
      tier: entry.tier || '',
      version: entry.version || '',
      description,
      agentDescription: agentDescription || '',
      humanCard: !!humanMdText,
      humanOneSentence: human.oneSentence || '',
      northStar,
      file_path: entry.source ? `${entry.source}/SKILL.md` : '',
      human_path: entry.source && humanMdText ? `${entry.source}/HUMAN.md` : '',
      capabilities: humanSections.length ? humanSections : agentSections,
      dependencies: edges.map((e) => String(e.to || '').replace(/^skill:/, '')).filter(Boolean),
      edges,
      timeline,
      journalCount: timeline.length
    };
  });
}

function loadNorthStar() {
  const text = readTextSafe(NORTH_STAR_PATH);
  return text ? text.trim() : 'North Star file not found — expected at ' + NORTH_STAR_PATH;
}

function buildMetrics(skills) {
  const { runs, lastImproved } = sleepRunStats();
  return {
    skills: skills.length,
    journalEntries: skills.reduce((sum, s) => sum + s.journalCount, 0),
    sleepRuns: runs,
    lastImproved
  };
}

// ---------- http ----------

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-cache',
    'Access-Control-Allow-Origin': '*'
  });
  res.end(body);
}

function serveStatic(res, urlPath) {
  let relPath = decodeURIComponent(urlPath.split('?')[0]);
  if (relPath === '/' || relPath === '') relPath = '/index.html';

  const resolved = path.normalize(path.join(DIST_DIR, relPath));
  // traversal guard: everything served must stay inside dist/
  const safePath = resolved.startsWith(DIST_DIR) ? resolved : null;

  let filePath = safePath && statSafe(safePath)?.isFile() ? safePath : null;
  if (!filePath) {
    // SPA fallback: unknown non-/api routes get index.html
    filePath = path.join(DIST_DIR, 'index.html');
  }

  let data;
  try {
    data = fs.readFileSync(filePath);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('dist/ not found — run `npm run build` first.');
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  res.writeHead(200, {
    'Content-Type': CONTENT_TYPES[ext] || 'application/octet-stream',
    'Cache-Control': 'no-cache'
  });
  res.end(data);
}

// ---------- the sleep-session endpoints (invoke the REAL kernel CLI) ----------

async function handleSleepPropose(req, res) {
  const body = await readJsonBody(req);
  const skill = String(body.skill || 'gandalf').trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(skill)) {
    return sendJson(res, { error: `invalid skill name: ${JSON.stringify(skill)}` }, 400);
  }
  const skillDir = path.join(SKILLS_ROOT, skill);
  if (!statSafe(skillDir)?.isDirectory()) {
    return sendJson(res, { error: `skill directory not found: ${skillDir}` }, 404);
  }
  fs.mkdirSync(SLEEP_RUNS_DIR, { recursive: true });

  const run = await runKernel(['propose', skillDir, '--repo', SKILLS_REPO, '--runs-dir', SLEEP_RUNS_DIR]);
  const parsed = parseKernelJson(run.stdout);
  if (!parsed || parsed.error || run.status !== 0 || run.spawnError) {
    return sendJson(res, {
      error: (parsed && parsed.error)
        || run.spawnError
        || `kernel propose exited ${run.status}${run.timedOut ? ' (timed out)' : ''}`,
      stderr: run.stderr
    }, 500);
  }
  // Enrich each unit with its REAL diff text (read from the artifact the
  // kernel just wrote) so the UI can render the concrete change.
  for (const unit of (parsed.proposal && parsed.proposal.units) || []) {
    const diffText = readTextSafe(unit.diffPath);
    if (diffText != null) unit.diffText = diffText;
  }
  return sendJson(res, parsed);
}

async function handleSleepApply(req, res) {
  const body = await readJsonBody(req);
  if (body.confirm !== true) {
    return sendJson(res, {
      error: 'refused: confirm must be exactly true — the human is the promotion authority',
      outcome: 'refused'
    }, 409);
  }
  const proposalDir = resolveProposalDir(body);
  if (!proposalDir) {
    return sendJson(res, { error: 'proposalId or proposalPath (inside the sleep-runs dir) required' }, 400);
  }
  if (!statSafe(path.join(proposalDir, 'proposal.json'))) {
    return sendJson(res, { error: `no proposal.json in ${proposalDir}` }, 404);
  }
  // The kernel requires an explicit confirm token; the GUI's confirm:true is
  // the human click, recorded honestly as this token in the apply record.
  const args = ['apply', proposalDir, '--confirm', 'foundry-gui-user'];
  if (body.unit) args.push('--unit', String(body.unit));

  const run = await runKernel(args);
  const parsed = parseKernelJson(run.stdout);
  if (!parsed || parsed.error || run.spawnError) {
    return sendJson(res, {
      error: (parsed && parsed.error) || run.spawnError
        || `kernel apply exited ${run.status}${run.timedOut ? ' (timed out)' : ''}`,
      stderr: run.stderr
    }, 500);
  }
  // outcome: applied (exit 0) | refused (exit 3) | blocked (exit 1, gate
  // regressed → auto-rolled-back). All are REAL kernel records.
  return sendJson(res, parsed, parsed.outcome === 'refused' ? 409 : 200);
}

async function handleSleepRollback(req, res) {
  const body = await readJsonBody(req);
  const proposalDir = resolveProposalDir(body);
  if (!proposalDir) {
    const hint = body.baselineSha
      ? ' (a bare baselineSha is not enough — the kernel reads the frozen baseline from the proposal artifact)'
      : '';
    return sendJson(res, { error: `proposalId or proposalPath (inside the sleep-runs dir) required${hint}` }, 400);
  }
  if (!statSafe(path.join(proposalDir, 'proposal.json'))) {
    return sendJson(res, { error: `no proposal.json in ${proposalDir}` }, 404);
  }
  const run = await runKernel(['rollback', proposalDir]);
  const parsed = parseKernelJson(run.stdout);
  if (!parsed || parsed.error || run.spawnError) {
    return sendJson(res, {
      error: (parsed && parsed.error) || run.spawnError
        || `kernel rollback exited ${run.status}${run.timedOut ? ' (timed out)' : ''}`,
      stderr: run.stderr
    }, 500);
  }
  return sendJson(res, parsed);
}

const server = http.createServer(async (req, res) => {
  try {
    const urlPath = (req.url || '/').split('?')[0];

    if (urlPath.startsWith('/api/')) {
      // The sleep-session ops: POST-only, spawn the REAL kernel CLI.
      if (urlPath === '/api/foundry/sleep_session/propose' && req.method === 'POST') {
        return await handleSleepPropose(req, res);
      }
      if (urlPath === '/api/foundry/sleep_session/apply' && req.method === 'POST') {
        return await handleSleepApply(req, res);
      }
      if (urlPath === '/api/foundry/sleep_session/rollback' && req.method === 'POST') {
        return await handleSleepRollback(req, res);
      }

      // Everything is read FRESH per request — cheap, and keeps the data live.
      if (urlPath === '/api/skills') {
        return sendJson(res, buildSkills());
      }
      if (urlPath === '/api/north-star') {
        return sendJson(res, { northStar: loadNorthStar() });
      }
      if (urlPath === '/api/summary') {
        return sendJson(res, { summary: buildSummary() });
      }
      if (urlPath === '/api/timeline') {
        const all = buildSkills().flatMap((s) => s.timeline);
        all.sort((a, b) => b.timestamp - a.timestamp);
        return sendJson(res, all);
      }
      if (urlPath === '/api/metrics') {
        return sendJson(res, buildMetrics(buildSkills()));
      }
      if (urlPath === '/api/agent-payload') {
        const skills = buildSkills();
        return sendJson(res, {
          timestamp: 0, // no wall-clock reads in this server; 0 = "not from a file"
          version: '2.0.0',
          northStar: loadNorthStar(),
          summary: buildSummary(),
          metrics: buildMetrics(skills),
          skillCount: skills.length
        });
      }
      return sendJson(res, { error: 'Unknown API route: ' + urlPath }, 404);
    }

    return serveStatic(res, req.url || '/');
  } catch (err) {
    return sendJson(res, { error: String(err && err.message ? err.message : err) }, 500);
  }
});

server.listen(PORT, () => {
  console.log(`foundry-gui real-data server listening on http://localhost:${PORT} (dist: ${DIST_DIR})`);
});
