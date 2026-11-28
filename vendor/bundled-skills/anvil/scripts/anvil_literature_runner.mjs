#!/usr/bin/env node
/**
 * Hermetic Pillar-4 Literature Snowball + Quote-Grounded Extraction + researchPrime Governed Round.
 * Invoked ONLY after explicit 2-click operator privacy consent on public catalog IDs (`DOI:`/`arXiv:`/`PMID:`).
 * Enforces 100% zero-tool `agent()` isolation:
 *   - Claude CLI: `--setting-sources user --permission-mode dontAsk --max-turns 1 --tools "" --strict-mcp-config`
 *   - Gemini (`agy.exe` stream-json): `--mode plan --sandbox --disable-slash-commands -p=` inside an isolated `.git`
 *     scratch dir with a `.agents/hooks.json` `PreToolUse` (`matcher: "*"`) `"decision": "deny"` hard-block +
 *     post-flight rejection of any `step_type === "tool"` event.
 * Zero `agy-dispatch.mjs` delegation, zero `--dangerously-skip-permissions`, zero edits to `trio/drivers/`.
 */
import fs from 'node:fs/promises';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname, resolve, delimiter } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CAND_FOUNDRY_A = resolve(__dirname, '..', '..', '..');
const CAND_FOUNDRY_B = resolve(__dirname, '..', '..', '..', '..', '..', 'Skill Foundry');
const FOUNDRY_ROOT = existsSync(join(CAND_FOUNDRY_A, 'skills', 'literature-review', 'src')) ? CAND_FOUNDRY_A : CAND_FOUNDRY_B;
const LIT_SRC = join(FOUNDRY_ROOT, 'skills', 'literature-review', 'src');

const ENV_ALLOWLIST = new Set([
  'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP', 'TMPDIR',
  'USERPROFILE', 'HOME', 'HOMEDRIVE', 'HOMEPATH', 'APPDATA', 'LOCALAPPDATA',
  'USERNAME', 'COMPUTERNAME', 'OS', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE',
  'SYSTEMDRIVE', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'COMMONPROGRAMFILES',
  'TRIO_TIER', 'ANCHOR_STRENGTH', 'ANCHOR_INHERITED_STRENGTH',
]);

function buildCleanChildEnv() {
  const out = { NO_COLOR: '1', NoDefaultCurrentDirectoryInExePath: '1' };
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && ENV_ALLOWLIST.has(k.toUpperCase())) out[k] = v;
  }
  return out;
}

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i].startsWith('--') && i + 1 < argv.length) {
      out[argv[i].slice(2)] = argv[i + 1];
      i += 1;
    }
  }
  return out;
}

function extractJson(raw) {
  const s = String(raw || '').trim();
  const m = s.match(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/);
  if (m) { try { return JSON.parse(m[1]); } catch { /* fallthrough */ } }
  const a = s.indexOf('{');
  const b = s.lastIndexOf('}');
  if (a !== -1 && b > a) { try { return JSON.parse(s.slice(a, b + 1)); } catch { /* ignore */ } }
  return null;
}

function inferVendorFromModel(modelStr) {
  const low = String(modelStr || '').toLowerCase();
  if (/gemini|argon|carbon|neon|hydrogen/.test(low)) return 'gemini';
  if (/claude|anthropic|opus|sonnet|haiku|fable/.test(low)) return 'claude';
  return '';
}

function resolveAgyExe(cleanEnv) {
  const isWin = process.platform === 'win32';
  const exeName = isWin ? 'agy.exe' : 'agy';
  const localApp = cleanEnv.LOCALAPPDATA || '';
  if (isWin && localApp) {
    const pinned = join(localApp, 'agy', 'bin', 'agy.exe');
    if (existsSync(pinned)) return pinned;
  }
  const cwdLower = resolve(process.cwd()).toLowerCase();
  for (const dir of String(cleanEnv.PATH || '').split(delimiter)) {
    const d = dir.trim().replace(/^"|"$/g, '');
    if (!d) continue;
    if (resolve(d).toLowerCase() === cwdLower) continue;
    const cand = join(d, exeName);
    if (existsSync(cand)) return cand;
  }
  return '';
}

function writeAgyZeroToolHooks(tmp) {
  mkdirSync(join(tmp, '.git'), { recursive: true });
  writeFileSync(
    join(tmp, 'AGENTS.md'),
    'CRITICAL ZERO-TOOL ISOLATION RULE: DO NOT call any tools (read_file, grep_search, list_dir, run_command, search_web, etc.). Every tool is disabled and any tool call rejects your response. Output STRICT JSON ONLY from the inline prompt.\n',
    'utf8',
  );
  const agDir = join(tmp, '.agents');
  mkdirSync(agDir, { recursive: true });
  const denyJs = join(agDir, 'deny_all_tools.mjs');
  writeFileSync(
    denyJs,
    'process.stdin.resume();process.stdin.on("data",()=>{});process.stdin.on("end",()=>{process.stdout.write(JSON.stringify({decision:"deny",reason:"anvil-zero-tool-seat"})+"\\n");});\n',
    'utf8',
  );
  const hooksCfg = {
    'anvil-zero-tool-gate': {
      PreToolUse: [{
        matcher: '*',
        hooks: [{ type: 'command', command: `"${process.execPath}" "${denyJs}"`, timeout: 5 }],
      }],
    },
  };
  writeFileSync(join(agDir, 'hooks.json'), JSON.stringify(hooksCfg), 'utf8');
}

function parseAgyStreamZeroTool(stdout) {
  let servedModel = '';
  let streamed = '';
  let finalResp = '';
  let toolSteps = 0;
  for (const rawLine of String(stdout || '').split(/\r?\n/)) {
    const s = rawLine.trim();
    if (!s || !s.startsWith('{')) continue;
    let ev;
    try { ev = JSON.parse(s); } catch { continue; }
    if (!ev || typeof ev !== 'object') continue;
    if (ev.event === 'init' && ev.init && typeof ev.init.model === 'string') {
      servedModel = ev.init.model;
    } else if (ev.event === 'step_update' && ev.step_update) {
      const stType = String(ev.step_update.step_type || '');
      if (stType === 'agent_response' && typeof ev.step_update.text_delta === 'string') {
        streamed += ev.step_update.text_delta;
      } else if (stType !== 'agent_response' && stType !== 'thinking') {
        toolSteps += 1;
      }
    } else if (ev.event === 'result' && ev.result && typeof ev.result.response === 'string' && ev.result.response.trim()) {
      finalResp = ev.result.response;
    }
  }
  return { text: finalResp || streamed, servedModel, toolSteps };
}

function makeReadOnlyAgent(claudeExe, claudeModel, telemetry, seatOpts = {}) {
  const cleanEnv = buildCleanChildEnv();
  const agyExe = resolveAgyExe(cleanEnv);
  const strength = String(seatOpts.strength || cleanEnv.ANCHOR_STRENGTH || cleanEnv.TRIO_TIER || 'heavy').toLowerCase();
  const geminiModel = seatOpts.geminiModel || (strength === 'light' || strength === 'standard' ? 'gemini-4-carbon-medium' : 'gemini-4-neon-xhigh');
  const claudeEffort = seatOpts.claudeEffort || (strength === 'light' || strength === 'standard' ? 'medium' : 'max');
  return async function readOnlyAgent(prompt, opts = {}) {
    const tmp = mkdtempSync(join(tmpdir(), 'anvil-lit-seat-'));
    try {
      const mcpPath = join(tmp, 'empty_mcp.json');
      writeFileSync(mcpPath, '{"mcpServers":{}}', 'utf8');
      const role = String(opts.role || 'judge');
      if (role !== 'extraction' && agyExe) {
        writeAgyZeroToolHooks(tmp);
        const ndjsonIn = JSON.stringify({ event: 'user', message: { role: 'user', content: `ZERO-TOOL MODE: DO NOT invoke any tool; any tool call rejects your response.\n\n${prompt}\n\nRespond with STRICT JSON ONLY.` } }) + '\n';
        const r = spawnSync(agyExe, [
          '--input-format', 'stream-json', '--output-format', 'stream-json',
          '--mode', 'plan', '--sandbox', '--disable-slash-commands',
          '--model', geminiModel, '--print-timeout', '60s', '-p=',
        ], { cwd: tmp, env: cleanEnv, input: ndjsonIn, encoding: 'utf8', windowsHide: true, timeout: 68000 });
        if (r.status === 0 && r.stdout) {
          const agyRes = parseAgyStreamZeroTool(r.stdout);
          const parsed = agyRes.toolSteps === 0 ? extractJson(agyRes.text) : null;
          const vendor = inferVendorFromModel(agyRes.servedModel);
          if (parsed && typeof parsed === 'object' && vendor) {
            telemetry.realSeatResponses += 1;
            telemetry.calls.push({ role, vendor, model_served: agyRes.servedModel });
            return parsed;
          }
        }
      }
      if (claudeExe && existsSync(claudeExe)) {
        const primaryClaude = claudeModel || (strength === 'light' || strength === 'standard' ? 'claude-opus-5-5' : 'claude-fable-5-2');
        const runClaudeOnce = (mdl, eff) => spawnSync(claudeExe, [
          '-p', '--setting-sources', 'user', '--model', mdl, '--effort', eff,
          '--permission-mode', 'dontAsk', '--max-turns', '1', '--tools', '', '--strict-mcp-config',
          '--mcp-config', mcpPath, '--no-session-persistence', '--output-format', 'json',
        ], {
          cwd: tmp, env: cleanEnv, input: `${prompt}\n\nRespond with STRICT JSON ONLY.`,
          encoding: 'utf8', windowsHide: true, timeout: 68000,
        });
        let r = runClaudeOnce(primaryClaude, claudeEffort);
        if (r.status !== 0 && primaryClaude === 'claude-fable-5-2' && /hit your limit|rate_limit|quota|usage limit/i.test(`${r.stdout || ''} ${r.stderr || ''}`)) {
          r = runClaudeOnce('claude-opus-5-5', 'medium');
        }
        if (r.status === 0 && r.stdout) {
          try {
            const env = JSON.parse(r.stdout.trim());
            const musage = (env && typeof env.modelUsage === 'object' && env.modelUsage) ? Object.keys(env.modelUsage) : [];
            const servedModel = musage.length > 0 ? String(musage[0]) : '';
            const parsed = extractJson(env.result || '');
            const vendor = inferVendorFromModel(servedModel);
            if (parsed && typeof parsed === 'object' && vendor) {
              telemetry.realSeatResponses += 1;
              telemetry.calls.push({ role, vendor, model_served: servedModel });
              return parsed;
            }
          } catch { /* fallthrough to seatFailures */ }
        }
      }
      telemetry.seatFailures += 1;
      throw new Error('SEAT_UNAVAILABLE: read-only review seat failed or unavailable');
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  };
}

async function main() {
  const args = parseArgs(process.argv);
  const cfg = JSON.parse(await fs.readFile(args.input, 'utf8'));
  const SAFE_SEED_RE = /^(?!.*\.\.)(?:DOI:10\.\d{4,9}\/[-._;()/:A-Za-z0-9]{1,120}|arXiv:\d{4}\.\d{4,5}(?:v\d+)?|PMID:\d{1,10})$/;
  const seeds = (Array.isArray(cfg.catalog_seeds) ? cfg.catalog_seeds : [])
    .filter((s) => s && typeof s.seed_id === 'string' && SAFE_SEED_RE.test(s.seed_id))
    .slice(0, 4);
  const searchMod = await import(pathToFileURL(join(LIT_SRC, 'search.mjs')).href);
  const extractMod = await import(pathToFileURL(join(LIT_SRC, 'extraction.mjs')).href);
  const advMod = await import(pathToFileURL(join(LIT_SRC, 'adversarial-compose.mjs')).href);
  const telemetry = { realSeatResponses: 0, seatFailures: 0, calls: [] };
  const agent = makeReadOnlyAgent(cfg.claude_exe || '', cfg.claude_model || '', telemetry, {
    geminiModel: cfg.gemini_model || '',
    claudeEffort: cfg.claude_effort || '',
    strength: cfg.strength || '',
  });

  const allCandidates = [];
  const fetchFailures = [];
  const fallbacks = [];
  for (const s of seeds) {
    const res = await searchMod.performSnowballSearch(s.seed_id, searchMod.DEFAULT_VENUE_WHITELIST, { depth: 1 });
    for (const c of (res.candidates || []).slice(0, 4)) {
      if (!allCandidates.some((x) => x.paperId === c.paperId)) allCandidates.push(c);
    }
    fetchFailures.push(...(res.fetchFailures || []));
    fallbacks.push(...(res.providerFallbacks || []));
  }

  const groundedClaims = [];
  const rejectedQuotes = [];
  const cols = ['estimator_specification', 'regularization_and_identification', 'numerical_properties'];
  for (const paper of allCandidates.slice(0, 3)) {
    const body = String(paper.abstract || '').trim();
    if (body.length < 40) continue;
    try {
      const ex = await extractMod.extractLedgerLean(paper, body, cols, agent);
      for (const a of ex.ledger.assumptions) {
        groundedClaims.push({ ...a, posture: 'QUOTE_VERIFIED' });
      }
      rejectedQuotes.push(...(ex.rejected || []));
    } catch { /* seat unavailable or minGrounded floor rejected paper cleanly */ }
  }

  let advSummary = { skipped: true, judgeSupported: false, displayState: 'NO_RECEIPT', callReceipts: telemetry.calls };
  if (groundedClaims.length > 0 && cfg.adversarial_rounds >= 1) {
    const beforeReal = telemetry.realSeatResponses;
    const beforeFail = telemetry.seatFailures;
    const beforeCallIdx = telemetry.calls.length;
    try {
      const adv = await advMod.composeLiteratureReviewAdversarialPass({
        ledger: { assumptions: groundedClaims },
        band: 'LITE',
        knobs: { adversarialRounds: 1 },
        agent,
        stakes: 'medium',
        northStar: 'Verify methodological assumptions for locked replication scope',
      });
      const r0 = (adv.rounds || [])[0] || {};
      const extractVendors = new Set(telemetry.calls.slice(0, beforeCallIdx).map((c) => c.vendor).filter(Boolean));
      const judgeCalls = telemetry.calls.slice(beforeCallIdx);
      const judgeVendors = new Set(judgeCalls.map((c) => c.vendor).filter(Boolean));
      const hasTrueCrossFamily = extractVendors.size >= 1
        && judgeCalls.length >= Math.max(1, Number(adv.invokeCount || 1))
        && judgeVendors.size >= 1
        && Array.from(judgeVendors).every((jv) => !extractVendors.has(jv));
      const advSeatsSucceeded = (telemetry.realSeatResponses - beforeReal) >= Math.max(1, Number(adv.invokeCount || 1))
        && (telemetry.seatFailures === beforeFail);
      const explicitZeroBlockers = Array.isArray(r0.openBlockers) && r0.openBlockers.length === 0;
      const verifiedJudgeSupport = Boolean(advSeatsSucceeded && explicitZeroBlockers && hasTrueCrossFamily);
      advSummary = {
        skipped: false,
        invokeCount: adv.invokeCount,
        judgeSupported: verifiedJudgeSupport,
        crossFamilyVerified: hasTrueCrossFamily,
        callReceipts: telemetry.calls,
        displayState: verifiedJudgeSupport ? 'ATTESTED' : (telemetry.seatFailures > beforeFail ? 'SEAT_UNAVAILABLE' : 'SINGLE_FAMILY_CLAIMED'),
      };
      if (verifiedJudgeSupport) {
        for (const gc of groundedClaims) gc.posture = 'CLAIM_SUPPORTED';
      }
    } catch (e) {
      advSummary = {
        skipped: false,
        judgeSupported: false,
        crossFamilyVerified: false,
        callReceipts: telemetry.calls,
        displayState: 'SEAT_UNAVAILABLE',
        error: String(e?.message || e).slice(0, 240),
      };
    }
  }

  const outPayload = {
    ok: true,
    candidates_found: allCandidates.length,
    claims: groundedClaims,
    rejected_quotes_count: rejectedQuotes.length,
    fetch_failures: fetchFailures,
    provider_fallbacks: fallbacks,
    adversarial: advSummary,
  };
  await fs.writeFile(args.output, JSON.stringify(outPayload, null, 2), 'utf8');
}

main().catch(async (err) => {
  const args = parseArgs(process.argv);
  if (args.output) {
    await fs.writeFile(args.output, JSON.stringify({ ok: false, error: String(err?.message || err).slice(0, 400) }), 'utf8');
  }
  process.exit(1);
});
