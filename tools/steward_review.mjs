#!/usr/bin/env node
// The code-job review gate's one adapter (execution minimum item 3, 2026-10-07). THIN and FAIL-CLOSED: it asks the
// trio's existing runAgent for one review (role "review" - a verification seat, so the trio never fails it over to
// another family) of a candidate tree, and prints ONE JSON line:
//   {ok, family, model, model_attested, tree_hash, verdict: "PASS"|"FAIL", findings: [...], elegance}
// Anything else - an exception, no second family configured, the reviewer of the author's own family, an unreadable
// answer - prints {ok:false, error} and exits 2. Landing reads only this line; it never trusts prose.
//
//   node tools/steward_review.mjs --repo <worktree> --base <sha> --head <sha> --author-family <claude|chatgpt|grok|gemini>
//        [--reviewer-family <family>] [--exhausted <family,family>] [--brief-file <path>] [--delta-from <sha>]
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { reviewDiff, largest } from './review_diff.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAX_DIFF = 800_000;
const MAX_AGY_WHOLE_PROMPT_BYTES = 26_000;
const FAMILIES = ['claude', 'chatgpt', 'grok', 'gemini'];

function resolveAgyDispatchScript() {
  const candidates = [
    process.env.ANCHOR_AGY_DISPATCH,
    process.env.ECGBERHT_AGY_DISPATCH,
    process.env.SKILL_FOUNDRY_DIR && path.join(process.env.SKILL_FOUNDRY_DIR, 'tools', 'agy-dispatch.mjs'),
    path.resolve(HERE, 'agy-dispatch.mjs'),
    path.resolve(HERE, '..', '..', 'Skill Foundry', 'tools', 'agy-dispatch.mjs'),
    path.resolve(HERE, '..', '..', 'skill-foundry', 'tools', 'agy-dispatch.mjs'),
  ].filter(Boolean);
  return candidates.find((p) => { try { return fs.statSync(p).isFile(); } catch { return false; } }) || null;
}

function isStandaloneClaudeAuthFailure(error) {
  const seat = error && error.receipt;
  const codes = ((seat && seat.attempts) || []).map((a) => a && a.error && a.error.code).filter(Boolean);
  if (seat && seat.error && seat.error.code) codes.push(seat.error.code);
  if (codes.some((c) => ['authentication_required', 'subscription_auth_required', 'spawn_error'].includes(c))) {
    return true;
  }
  const msg = [
    error && error.message,
    seat && seat.error && seat.error.message,
    ...(((seat && seat.attempts) || []).map((a) => (a && a.error && a.error.message) || '')),
  ].filter(Boolean).join(' ');
  return /oauth session expired|failed to authenticate|not logged in|authentication_required|login required/i.test(msg);
}

function extractStrictReviewJson(rawText) {
  let t = String(rawText || '').trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const cands = [t, (t.match(/\{[\s\S]*\}/) || [])[0]].filter(Boolean);
  for (const c of cands) {
    for (const v of [c, c.replace(/,(\s*[}\]])/g, '$1')]) {
      try {
        const parsed = JSON.parse(v);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
      } catch { /* next */ }
    }
  }
  return null;
}

function tryAgyClaudeReviewFallback(prompt) {
  if (process.env.ANCHOR_DISABLE_AGY_CLAUDE_FALLBACK === '1' || process.env.PYTEST_CURRENT_TEST || process.env.ANCHOR_HEALTHCHECK) {
    return null;
  }
  const dispatchScript = resolveAgyDispatchScript();
  if (!dispatchScript) return null;
  const schemaFooter = [
    '',
    'OUTPUT FORMAT (MANDATORY): Reply with ONLY one valid JSON object matching this exact schema (no markdown fences, no commentary):',
    '{"verdict":"PASS"|"FAIL","findings":[{"severity":"BLOCKER"|"MAJOR"|"MINOR","file":"...","line":1,"issue":"...","fix":"..."}],"elegance":"..."}',
  ].join('\n');
  const fullPrompt = prompt + schemaFooter;
  const promptBytes = Buffer.byteLength(fullPrompt, 'utf8');
  if (promptBytes > MAX_AGY_WHOLE_PROMPT_BYTES) {
    throw new Error(
      `standalone claude CLI is not logged in, and the review prompt (${promptBytes} bytes) exceeds the ${MAX_AGY_WHOLE_PROMPT_BYTES}-byte whole-read agy fallback bound; run "claude login" or choose another Reviewer seat`
    );
  }
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'anchor-agy-rev-'));
  try {
    const pFile = path.join(tmpDir, 'prompt.txt');
    const oFile = path.join(tmpDir, 'reply.json');
    fs.writeFileSync(pFile, fullPrompt, 'utf8');
    let stdout = '';
    try {
      stdout = execFileSync(
        process.execPath,
        [dispatchScript, '--prompt-file', pFile, '--target', tmpDir, '--out', oFile, '--model', 'Claude Opus 5.5 (High)', '--readonly', '--json-safe', '--timeout-min', '4', '--label', 'steward-review-claude'],
        { encoding: 'utf8', timeout: 255_000, windowsHide: true }
      );
    } catch {
      return null;
    }
    const lines = String(stdout || '').trim().split(/\r?\n/).filter((l) => l.trim().startsWith('{'));
    let meta = null;
    try {
      meta = lines.length ? JSON.parse(lines[lines.length - 1]) : null;
    } catch {
      return null;
    }
    if (!meta || meta.status !== 'success') {
      return null;
    }
    const servedModel = String(meta.servedModel || meta.model || '');
    if (!/^claude/i.test(servedModel)) {
      throw new Error(`agy Claude review fallback refused non-Claude served model "${servedModel}"`);
    }
    const rawReply = fs.existsSync(oFile) ? fs.readFileSync(oFile, 'utf8') : '';
    const parsed = extractStrictReviewJson(rawReply);
    if (!parsed || !['PASS', 'FAIL'].includes(parsed.verdict) || !Array.isArray(parsed.findings) || typeof parsed.elegance !== 'string') {
      return null;
    }
    for (const f of parsed.findings) {
      if (!f || typeof f !== 'object' || !['BLOCKER', 'MAJOR', 'MINOR'].includes(f.severity) || typeof f.issue !== 'string') {
        return null;
      }
    }
    return {
      result: parsed,
      served: { family: 'claude', model: servedModel, model_attested: false, served_via: 'agy-dispatch' },
    };
  } finally {
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  }
}

function arg(name, fallback = '') {
  const i = process.argv.indexOf('--' + name);
  return i > 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function out(obj, code = 0) {
  process.stdout.write(JSON.stringify(obj) + '\n');
  process.exit(code);
}

const CAUSES = {
  schema_nonconforming: 'its answer was not in the required review form',
  invalid_json: 'its answer was not readable', invalid_final: 'its answer was not readable',
  malformed_jsonl: 'its answer was not readable',
  turn_timeout: 'it ran out of time', rpc_timeout: 'it ran out of time', open_timeout: 'it did not start in time',
  usage_limit_reached: 'it hit a usage limit', session_limit: 'it hit a usage limit',
  authentication_required: 'it is not logged in', subscription_auth_required: 'it is not logged in',
  spawn_error: 'it could not start', capability_unavailable: 'it is not available on this machine',
};
function seatCause(seat) {
  const codes = (seat.attempts || []).map(a => a && a.error && a.error.code).filter(Boolean);
  const code = codes[codes.length - 1] || (seat.error && seat.error.code) || seat.status || 'unknown';
  return `${CAUSES[code] || 'the seat failed'} (${code}); retry later, or choose another Reviewer seat on the dashboard`;
}

let attempted = null;     // the reviewer family asked, so a quota failure can be remembered against it
function fail(error) {
  out({ ok: false, family: attempted, error: String(error && error.message ? error.message : error).slice(0, 600) }, 2);
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim();
}

const SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings', 'elegance'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'issue'],
        properties: {
          severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
          file: { type: 'string' }, line: { type: 'integer' }, issue: { type: 'string' }, fix: { type: 'string' },
        },
      },
    },
    elegance: { type: 'string' },
  },
};

async function main() {
  const repo = arg('repo'), base = arg('base'), head = arg('head');
  const authors = arg('author-family').toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
  const exhausted = new Set(arg('exhausted').toLowerCase().split(',').map(s => s.trim()).filter(Boolean));
  if (!repo || !base || !head) throw new Error('usage: --repo --base --head --author-family are required');
  if (!authors.length || !authors.every(a => FAMILIES.includes(a))) throw new Error(`unknown author families "${authors}"`);
  const trioRoot = process.env.ANCHOR_TRIO_ROOT || 'C:/dev/trio';
  const drivers = await import(pathToFileURL(path.join(trioRoot, 'drivers', 'index.mjs')).href);

  // the reviewer: the asked family (--reviewer-family), else the dashboard's Reviewer seat - never the author's
  // family, never a family known to be exhausted. No second family: refuse (never review oneself).
  const prefs = drivers.loadModelFamilies(process.env);
  const asked = arg('reviewer-family').toLowerCase().trim();
  const reviewer = asked || String(prefs.review || '').toLowerCase();
  attempted = FAMILIES.includes(reviewer) ? reviewer : null;
  if (!FAMILIES.includes(reviewer)) throw new Error(`the Reviewer seat (${reviewer || 'unset'}) is not a known family`);
  if (authors.includes(reviewer)) throw new Error(`the Reviewer seat (${reviewer}) is an author's family (${authors}); choose another Reviewer seat on the dashboard`);
  if (exhausted.has(reviewer)) throw new Error(`the Reviewer seat (${reviewer}) hit its usage limit recently; wait or choose another Reviewer seat`);

  const treeHash = git(repo, 'rev-parse', head + '^{tree}');
  const deltaFrom = arg('delta-from');
  const from = deltaFrom || base;
  const diff = reviewDiff(repo, from, head, { excludeRuntime: Boolean(deltaFrom), deltaBase: deltaFrom ? base : '' });
  if (!diff.trim()) {
    if (deltaFrom) {
      return out({
        ok: true, family: reviewer, model: 'delta-noop', model_attested: true,
        tree_hash: treeHash, verdict: 'PASS', findings: [],
        elegance: 'Only upstream main commits or cockpit runtime records changed during integration; candidate files are unchanged.',
      });
    }
    throw new Error('the candidate has no change to review');
  }
  if (diff.length > MAX_DIFF) throw new Error(`the diff is ${diff.length} characters (one review reads ${MAX_DIFF} at most)`
    + `${largest(repo, from, head)}; split the job`);
  // fcj review r5: the brief is read WHOLE or the review refuses - never sliced (a cut brief could drop a requirement)
  const brief = arg('brief-file') && fs.existsSync(arg('brief-file')) ? fs.readFileSync(arg('brief-file'), 'utf8') : '';
  if ([...brief].length > 16000) throw new Error(`the brief is ${[...brief].length} characters - longer than the reviewer reads whole`);

  const prompt = [
    'You are the adversarial second-family reviewer of a code change an AI coder made for John.',
    'Decide PASS only if the change is correct, does what the brief asks, and introduces no defect you can name.',
    'FAIL on any BLOCKER or MAJOR finding: a concrete wrong result, a crash, data loss, a security hole, or a',
    'missing part of the brief. MINOR findings alone do not fail it. No style preferences.',
    'Add "elegance": at most three lines on what is heavier than it needs to be.',
    from !== base ? `This is a DELTA review: only the change since an earlier reviewed candidate (${from}).` : '',
    '', 'BRIEF:', brief || '(none given)', '', `DIFF (${from}..${head}):`, diff,
  ].join('\n');

  // 2026-10-12 (Book 1 jobs 07bd1c, 45f140): the Reviewer seat failed closed on a malformed answer and two finished
  // jobs stayed unlanded. A review is read-only, so a seat failure is retried once on the SAME seat; a second
  // failure is reported with its real cause in plain words. Never another family here, never unreviewed.
  let tempSettingsDir = null;
  let agentEnv = process.env;
  if (asked && asked !== String(prefs.review || '').toLowerCase()) {
    tempSettingsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'anchor-review-'));
    fs.writeFileSync(path.join(tempSettingsDir, 'settings.json'), JSON.stringify({
      coding_family: prefs.coding || 'claude',
      review_family: reviewer,
      default_cli: prefs.terminal || 'claude',
      model_policy: prefs.model_policy || { mode: 'latest_supported', effort: 'highest_supported' },
      settings_revision: Number.isSafeInteger(prefs.settings_revision) ? prefs.settings_revision : 0,
    }), 'utf8');
    agentEnv = { ...process.env, ANCHOR_DATA_DIR: tempSettingsDir };
  }
  let receipt = null;
  let result = null;
  let triedAgyFallback = false;
  try {
    for (let attempt = 1; ; attempt++) {
      try {
        result = await drivers.runAgent({
          prompt, schema: SCHEMA, role: 'review', label: 'review:code-job',
          driver: drivers.familyToDriverName(reviewer), freshContext: true,
          env: agentEnv,
          onReceipt: (r) => { receipt = r; },
        });
        break;
      } catch (error) {
        if (!triedAgyFallback && reviewer === 'claude' && !authors.includes('claude') && isStandaloneClaudeAuthFailure(error)) {
          triedAgyFallback = true;
          const fallback = tryAgyClaudeReviewFallback(prompt);
          if (fallback) {
            result = fallback.result;
            receipt = { served: fallback.served };
            break;
          }
        }
        const seat = error && error.receipt;
        if (!seat || seat.status === 'aborted') throw error;
        if (attempt >= 2) throw new Error(`the reviewer (${reviewer}) could not give a review twice - ${seatCause(seat)}`);
        await new Promise(r => setTimeout(r, Number(process.env.ANCHOR_REVIEW_RETRY_MS || 15000)));
      }
    }
  } finally {
    if (tempSettingsDir) {
      try { fs.rmSync(tempSettingsDir, { recursive: true, force: true }); } catch {}
    }
  }
  const served = (receipt && receipt.served) || {};
  const family = String(served.family || '').toLowerCase();
  if (!family) throw new Error('the review seat did not report which family served it');
  if (authors.includes(family)) throw new Error(`the review was served by an author's own family (${family})`);
  if (!result || !['PASS', 'FAIL'].includes(result.verdict)) throw new Error('the review answer had no verdict');
  const findings = Array.isArray(result.findings) ? result.findings : [];
  if (result.verdict === 'PASS' && findings.some(f => f && ['BLOCKER', 'MAJOR'].includes(f.severity))) {
    result.verdict = 'FAIL';                 // a PASS that lists a blocking finding is not a pass
  }
  out({ ok: true, family, model: served.model || null, model_attested: !!served.model_attested, tree_hash: treeHash,
        verdict: result.verdict, findings: Array.isArray(result.findings) ? result.findings : [],
        elegance: String(result.elegance || '').slice(0, 600) });
}

main().catch(fail);
