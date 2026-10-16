#!/usr/bin/env node
/**
 * chekhov — the writing skill's ONE dispatcher (RIDER 6).
 *
 * PUBLIC verbs (the CLOSED table a host may learn):
 *   chekhov <project>   the session engine: start or resume
 *   chekhov idea        typed intake + verdict (arrives W8)
 *   chekhov accept      John's seat-free promotion (first real sitting W11)
 *   chekhov lock        the lock-event pass (arrives W20)
 *
 * lint, commit, status, brief, structure, journal, guard, render and draft are
 * TRANSITIONS of the engine — named edges of the state machine, never
 * free-standing commands. This file imports ONLY the engine and the operator
 * modules; a source-grep test fails if any transition module is imported here.
 *
 * Unknown command → usage on stderr, exit 2.
 */
import process from 'node:process';
import { invokeSession, sessionPrompt, promptKeys, requestTransition, requestInspection, requestCommit, requestAccept,
  closeIdeaJudge, requestStatus, startSession, prepareSession, invokeAnchorSession } from '../lib/engine.mjs';
import { loadRoots, initRoots, checkRemote, DEFAULT_ROOTS_MANIFEST } from '../lib/roots.mjs';
import { promoteVerdict, fixtureFromLog, fixtureReport, KIND_REQUIRED_MESSAGE } from '../lib/fixture.mjs';
import { migrateDocx } from '../lib/migrate.mjs';
import { migrateBrightHeartRoot } from '../lib/migrate-root.mjs';
import { recordFirstCommit } from '../lib/corpus.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** W2 divergence notes land in the wave's own journal entry. */
const W2_JOURNAL = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..', 'journal', '0002-bright-heart-migration.md',
);

const USAGE = `usage: chekhov <project>   start or resume the writing session
       chekhov idea        check a dictated idea against the ledger
       chekhov accept      walk the waiting-on-John list
       chekhov lock        run the lock-event pass`;

function fail(msg, code) {
  process.stderr.write(`${msg}\n`);
  process.exit(code);
}

async function main(argv) {
  const [cmd, ...rest] = argv;
  if (!cmd) {
    if (process.stdin.isTTY === true) fail(USAGE, 2);
    const chunks = [];
    let size = 0;
    for await (const chunk of process.stdin) {
      size += chunk.length;
      if (size > 65536) fail('Anchor stdin exceeds 65536 bytes', 2);
      chunks.push(chunk);
    }
    const raw = Buffer.concat(chunks).toString('utf8');
    if (!raw.trim()) fail(USAGE, 2);
    let payload;
    try { payload = JSON.parse(raw); } catch { fail('Anchor stdin must be one JSON object', 2); }
    let roots = {};
    try { roots = loadRoots(DEFAULT_ROOTS_MANIFEST).roots || {}; } catch { /* explicit configured folder remains supported */ }
    const result = await invokeAnchorSession(payload, { roots });
    for (const line of result.lines) process.stdout.write(`${line}\n`);
    if (result.exitCode) process.stderr.write(`${result.halted ? 'reconciliation HALT remains open' : result.lines.at(-1) || 'Anchor session failed'}\n`);
    process.exitCode = result.exitCode;
    return;
  }

  // Public verbs whose waves have not landed yet refuse honestly (exit 3).
  if (cmd === 'idea') {
    const project = rest[0];
    if (!project) fail('usage: chekhov idea <project> --text <line> | --file <drop> [--scope <word>] [--unit <unit>]', 2);
    const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
    const root = manifest.roots?.[project]?.path || (fs.existsSync(project) && fs.statSync(project).isDirectory() ? path.resolve(project) : null);
    if (!root) fail('unknown project for idea', 2);
    const text = flagValue(rest, '--text'), file = flagValue(rest, '--file');
    if ((text === null) === (file === null)) fail('Supply exactly one of --text <line> or --file <drop>.', 2);
    try {
      const replay = flagValue(rest, '--replay');
      const out = await requestTransition(root, 'intake', { project, ...(file !== null ? { file } : { text }),
        unit: flagValue(rest, '--unit'), scope: flagValue(rest, '--scope'), live: replay === null, replay,
        sourcesFile: flagValue(rest, '--sources'),
        onT0: (lines) => { for (const line of lines) process.stdout.write(`T0: ${line}\n`); } });
      for (const line of out.lines) process.stdout.write(`${line}\n`);
      process.exitCode = out.status;
    } finally { await closeIdeaJudge(root); }
    return;
  }
  if (cmd === 'lock') fail('chekhov lock arrives in W20 (seats from Anchor prefs); nothing to run yet', 3);

  // Operator-only verbs (documented in HUMAN.md, never told to a host).
  if (cmd === 'status' || cmd === 'brief') {
    const project = rest[0], manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
    const root = manifest.roots?.[project]?.path || (project && fs.existsSync(project) && fs.statSync(project).isDirectory() ? path.resolve(project) : null);
    if (!root) fail(`unknown project for ${cmd}`, 2);
    const out = cmd === 'brief' ? startSession(root, { project }) : requestStatus(root, { project, line: rest.includes('--line') });
    for (const line of out.lines) process.stdout.write(`${line}\n`);
    process.exitCode = out.ok ? 0 : 4;
    return;
  }
  if (cmd === 'commit' || cmd === 'accept') {
    const project = rest[0];
    if (!project) fail(`usage: chekhov ${cmd} <project>`, 2);
    const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
    const root = manifest.roots?.[project]?.path || (fs.existsSync(project) && fs.statSync(project).isDirectory() ? path.resolve(project) : null);
    if (!root) fail(`unknown project for ${cmd}`, 2);
    if (cmd === 'commit' && rest.includes('--record-first')) {
      if (project !== 'bright-heart' || !rest.includes('--live') || flagValue(rest, '--scope') || flagValue(rest, '--replay')) fail('usage: chekhov commit bright-heart --live --record-first (default corpus only)', 2);
      const batchSize = recordBatchSize(rest);
      const out = await recordFirstCommit(root, { roots: manifest.roots, remoteVisibility: manifest.remote_visibility, batchSize });
      for (const line of out.lines) process.stdout.write(`${line}\n`);
      process.exitCode = out.status;
      return;
    }
    const out = cmd === 'commit'
      ? await requestCommit(root, { scope: flagValue(rest, '--scope'), replay: flagValue(rest, '--replay'), live: rest.includes('--live') })
      : await requestAccept(root, { list: flagValue(rest, '--list'), project });
    if (cmd === 'commit') for (const line of out.lines) process.stdout.write(`${line}\n`);
    process.exitCode = out.status || (out.ok ? 0 : 1);
    return;
  }
  if (cmd === 'lint' || cmd === 'structure') {
    const project = rest[0];
    const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
    const root = manifest.roots?.[project]?.path || (project && fs.existsSync(project) && fs.statSync(project).isDirectory() ? path.resolve(project) : null);
    if (!root) fail(`unknown project for ${cmd}`, 2);
    const out = requestInspection(root, cmd);
    if (!out.ok) fail(out.reason, 1);
    for (const line of out.lines) process.stdout.write(`${line}\n`);
    return;
  }
  if (cmd === 'roots') {
    const manifestPath = flagValue(rest, '--manifest') || DEFAULT_ROOTS_MANIFEST;
    if (rest.includes('--check-remote')) {
      const out = checkRemote({ manifestPath });
      process.stdout.write(`remote visibility: ${out.visibility}\n`);
      return;
    }
    const { results } = initRoots(manifestPath);
    for (const r of Object.values(results)) {
      if (r.error) process.stdout.write(`${r.id}: ERROR ${r.error}\n`);
      else process.stdout.write(`${r.id}: ${r.actions.join(', ')}\n`);
    }
    const anyError = Object.values(results).some((r) => r.error);
    if (anyError) process.exit(1);
    return;
  }
  if (cmd === 'migrate') {
    // Operator-only (HUMAN.md): one docx → <name>_source.md beside it, or the
    // named Bright-Heart set (the W2 proof substrate) plus chekhov/manifest.json.
    const target = rest.find((a) => !a.startsWith('--'));
    if (!target) fail('usage: chekhov migrate <docx> | chekhov migrate bright-heart', 2);
    const job = target === 'bright-heart'
      ? (() => {
          const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
          const root = manifest.roots['bright-heart']?.path;
          if (!root || !fs.existsSync(root)) fail('bright-heart root missing — run the roots step first (HUMAN.md)', 1);
          return migrateBrightHeartRoot(root, {
            journalPath: W2_JOURNAL,
            amRootPath: manifest.roots['artificial-magi']?.path,
          });
        })()
      : migrateDocx(target, { journalPath: W2_JOURNAL });
    job.then((out) => {
      for (const line of out.lines) process.stdout.write(`${line}\n`);
      if (out.error) process.stderr.write(`${out.error}\n`);
      process.exit(out.ok ? 0 : 1);
    }).catch((e) => fail(`migrate failed: ${e.message}`, 1));
    return;
  }
  if (cmd === 'pack') fail('chekhov pack enable arrives in the Phase-3 waves; nothing to run yet', 3);
  if (cmd === 'fixture') {
    const [sub, ...subRest] = rest;
    if (sub === 'promote') {
      const project = flagValue(subRest, '--project');
      if (project) {
        const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
        const root = manifest.roots?.[project]?.path || (fs.existsSync(project) && fs.statSync(project).isDirectory() ? path.resolve(project) : null);
        if (!root || !subRest[0] || subRest[0].startsWith('--')) fail('usage: chekhov fixture promote <verdict-id> --project <project> --kind <real-replay|reconstructed>', 2);
        const out = promoteVerdict(fixtureFromLog(root, subRest[0], { kind: flagValue(subRest, '--kind') }), { remoteVisibility: manifest.remote_visibility });
        if (!out.ok) fail(out.problems.join('; '), 1);
        process.stdout.write(`fixture written: ${out.wrote}\n`);
        return;
      }
      const fromPath = flagValue(subRest, '--from');
      const verdictId = subRest.find((a) => !a.startsWith('--') && a !== fromPath);
      if (!fromPath || !verdictId) fail('usage: chekhov fixture promote <verdict-id> --from <verdicts.json>', 2);
      let records;
      try {
        records = JSON.parse(fs.readFileSync(fromPath, 'utf8'));
      } catch (e) {
        fail(`cannot read verdicts file: ${e.message}`, 1);
      }
      const list = Array.isArray(records) ? records : records.verdicts || [];
      const verdict = list.find((v) => v && v.id === verdictId);
      if (!verdict) fail(`verdict not found: ${verdictId}`, 1);
      const manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
      const out = promoteVerdict(verdict, { remoteVisibility: manifest.remote_visibility });
      if (!out.ok) fail(out.problems.includes(KIND_REQUIRED_MESSAGE) ? KIND_REQUIRED_MESSAGE : out.problems.join('; '), 1);
      process.stdout.write(`fixture written: ${out.wrote}\n`);
      return;
    }
    if (sub === 'report') {
      const report = fixtureReport();
      process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
      return;
    }
    fail('usage: chekhov fixture promote <verdict-id> --from <file> | chekhov fixture report', 2);
  }

  // A known project id runs the session engine.
  let manifest;
  try {
    manifest = loadRoots(DEFAULT_ROOTS_MANIFEST);
  } catch {
    manifest = { roots: {} };
  }
  if (manifest.roots?.[cmd] || (fs.existsSync(cmd) && fs.statSync(cmd).isDirectory()) || flagValue(rest, '--pack')) {
    const root = manifest.roots?.[cmd]?.path || path.resolve(cmd);
    if (flagValue(rest, '--pack') || flagValue(rest, '--unit')) {
      const prepared = prepareSession(root, { project: cmd, pack: flagValue(rest, '--pack'), unit: flagValue(rest, '--unit') });
      if (!prepared.ok) fail(prepared.reason, 2);
    }
    if (!fs.existsSync(root)) fail(`project root missing: ${root} — run the roots step first (HUMAN.md)`, 1);
    const replay = flagValue(rest, '--replay');
    const options = { project: cmd, live: replay === null, replay, unit: flagValue(rest, '--unit'),
      sourcesFile: flagValue(rest, '--sources'), onT0: (lines) => { for (const line of lines) process.stdout.write(`T0: ${line}\n`); } };
    try {
      const result = await invokeSession(root, options);
      for (const line of result.lines) process.stdout.write(`${line}\n`);
      const seed = flagValue(rest, '--text');
      if (result.ok && seed !== null) {
        const intake = await requestTransition(root, 'intake', { ...options, text: seed });
        for (const line of intake.lines) process.stdout.write(`${line}\n`);
      }
      const keys = promptKeys();
      if (keys.length) process.stdout.write(`keys: ${keys.map((k) => `${k.key}=${k.action}`).join('  ')}\n`);
      if (result.ok || result.halted) await sessionPrompt(root, options);
      process.exitCode = result.halted ? 4 : result.ok ? 0 : 1;
    } finally { await closeIdeaJudge(root); }
    return;
  }

  fail(USAGE, 2);
}

function flagValue(args, flag) {
  const i = args.indexOf(flag);
  return i !== -1 && i + 1 < args.length ? args[i + 1] : null;
}

function recordBatchSize(args) {
  let batchSize = 20, seen = false;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (!arg.startsWith('--batch-size')) continue;
    if (seen) fail('--batch-size may be supplied only once', 2);
    seen = true;
    let value;
    if (arg === '--batch-size') value = args[++i];
    else if (arg.startsWith('--batch-size=')) value = arg.slice('--batch-size='.length);
    const parsed = Number(value);
    if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 20 || String(parsed) !== value) {
      fail('--batch-size must be an integer from 1 to 20', 2);
    }
    batchSize = parsed;
  }
  return batchSize;
}

main(process.argv.slice(2)).catch((e) => fail(e.message, 1));
