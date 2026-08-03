#!/usr/bin/env node
/**
 * claude-verify.mjs — one-shot, READ-ONLY Claude verification wrapper.
 *
 * Purpose: let a Gemini session drive a single, non-interactive Claude prompt
 * and capture its text answer, so cross-model verification can be automated.
 */

import { spawn } from 'node:child_process';

function parseArgs(argv) {
  const out = { prompt: null, cwd: process.cwd(), model: null, timeout: 300000 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--prompt' || a === '-p') out.prompt = argv[++i];
    else if (a === '--cwd') out.cwd = argv[++i];
    else if (a === '--model' || a === '-m') out.model = argv[++i];
    else if (a === '--timeout') out.timeout = parseInt(argv[++i], 10) || out.timeout;
  }
  return out;
}

function readStdin() {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) { resolve(''); return; }
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { data += c; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', () => resolve(data));
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  let prompt = args.prompt;
  if (prompt == null || prompt === '') prompt = (await readStdin()).trim();
  if (!prompt) {
    process.stderr.write('claude-verify: no prompt provided\n');
    process.exit(2);
  }

  const claudeArgs = ['-p', prompt, '--output-format', 'text'];
  if (args.model) claudeArgs.push('--model', args.model);

  const child = spawn(process.env.CLAUDE_CMD || 'claude', claudeArgs, {
    cwd: args.cwd,
    env: process.env,
    shell: false,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdoutBuf = '';
  let stderrBuf = '';
  child.stdout.on('data', (d) => { stdoutBuf += d.toString(); });
  child.stderr.on('data', (d) => { stderrBuf += d.toString(); });

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    try { child.kill('SIGKILL'); } catch { /* ignore */ }
  }, args.timeout);

  const exitCode = await new Promise((resolve) => {
    child.on('error', (err) => {
      process.stderr.write(`claude-verify: failed to spawn 'claude': ${err.message}\n`);
      resolve(-1);
    });
    child.on('close', (code) => resolve(code));
  });
  clearTimeout(timer);

  if (timedOut) {
    process.stderr.write(`claude-verify: timed out after ${args.timeout}ms\n`);
    process.exit(124);
  }
  if (exitCode === -1) process.exit(1);
  if (exitCode !== 0) {
    process.stderr.write(`claude-verify: claude exited ${exitCode}. stderr=${stderrBuf.slice(0, 500)}\n`);
    process.exit(exitCode || 1);
  }

  let text = stdoutBuf.trim();
  // Strip off the warning if no stdin was provided to claude directly but it expected it
  const warningLine = "Warning: no stdin data received";
  if (text.startsWith(warningLine)) {
      text = text.substring(text.indexOf('\n') + 1).trim();
  }

  if (!text) {
    process.stderr.write('claude-verify: no output received.\n');
    process.exit(3);
  }

  process.stdout.write(text + '\n');
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`claude-verify: unexpected error: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
