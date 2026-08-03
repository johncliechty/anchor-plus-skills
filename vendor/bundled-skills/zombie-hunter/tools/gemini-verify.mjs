#!/usr/bin/env node
/**
 * gemini-verify.mjs — one-shot, READ-ONLY Gemini verification wrapper.
 *
 * Purpose: let a Claude session drive a single, non-interactive Gemini prompt
 * and capture its text answer, so cross-model verification (a second-model
 * VERDICT on a diff/claim) can be automated with zero human cut-and-paste.
 *
 * Gemini only READS and REPLIES with text. This wrapper NEVER requests tool
 * or edit permissions and NEVER passes --dangerously-skip-permissions or any
 * auto-approve / permission-bypass flag.
 *
 * Usage:
 *   echo "your prompt" | node gemini-verify.mjs
 *   node gemini-verify.mjs --prompt "your prompt"
 *   node gemini-verify.mjs --prompt "..." --cwd C:/some/dir --model "Gemini 3.1 Pro" --timeout 300000
 *
 * Output: ONLY the model's final assistant TEXT is written to stdout.
 * Exit 0 on success with non-empty text; non-zero with a clear stderr message
 * on failure / timeout.
 *
 * TRANSPORT NOTE (why we read a transcript instead of stdout):
 * The `agy` (Antigravity Gemini) CLI v1.0.13 print mode (`-p`) renders its
 * reply through a TUI/glamour renderer that only writes when stdout is a TTY;
 * when stdout is a pipe it emits NOTHING (whereas `agy --help`/`changelog` do
 * print to a pipe). This agy build also no longer accepts `--output-format
 * stream-json` or `--skip-trust` (the flags the older trio driver used —
 * `agy --help` confirms they are gone). It DOES, however, reliably (a) reach
 * the model and (b) persist the assistant reply to its conversation
 * transcript, and `--log-file` exposes the conversation id. So we spawn agy
 * exactly like the proven driver (prompt on stdin, shell:false,
 * windowsHide:true), then read the final assistant text out of that
 * conversation's transcript.jsonl. No permission flags are involved.
 */

import { spawn } from 'node:child_process';
import { readFileSync, existsSync, mkdtempSync, statSync, readdirSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';

const AGY_BRAIN_DIR = join(homedir(), '.gemini', 'antigravity-cli', 'brain');

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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Extract the conversation id agy logged for this print-mode run. */
function conversationIdFromLog(logPath) {
  if (!existsSync(logPath)) return null;
  let txt = '';
  try { txt = readFileSync(logPath, 'utf8'); } catch { return null; }
  // "Print mode: conversation=<uuid>, sending message"
  const m = txt.match(/Print mode:\s*conversation=([0-9a-fA-F-]{8,})/);
  return m ? m[1] : null;
}

function transcriptPathForId(id) {
  return join(AGY_BRAIN_DIR, id, '.system_generated', 'logs', 'transcript.jsonl');
}

/** Fallback: newest transcript.jsonl under the brain dir modified since `since`. */
function newestTranscriptSince(since) {
  if (!existsSync(AGY_BRAIN_DIR)) return null;
  let best = null, bestMtime = since;
  let ids = [];
  try { ids = readdirSync(AGY_BRAIN_DIR); } catch { return null; }
  for (const id of ids) {
    const p = transcriptPathForId(id);
    try {
      const st = statSync(p);
      if (st.mtimeMs >= bestMtime) { best = p; bestMtime = st.mtimeMs; }
    } catch { /* no transcript for this id */ }
  }
  return best;
}

/** Pull the final assistant TEXT out of a transcript.jsonl file. */
function finalTextFromTranscript(path) {
  if (!path || !existsSync(path)) return '';
  let raw = '';
  try { raw = readFileSync(path, 'utf8'); } catch { return ''; }
  let last = '';
  for (const line of raw.split('\n')) {
    const s = line.trim();
    if (!s) continue;
    let o;
    try { o = JSON.parse(s); } catch { continue; }
    // The assistant's reply is a MODEL step with non-empty string `content`
    // (e.g. type PLANNER_RESPONSE). Ignore `thinking`, USER/SYSTEM steps.
    if (o && o.source === 'MODEL' && typeof o.content === 'string' && o.content.trim()) {
      last = o.content.trim();
    }
  }
  return last;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  let prompt = args.prompt;
  if (prompt == null || prompt === '') prompt = (await readStdin()).trim();
  if (!prompt) {
    process.stderr.write('gemini-verify: no prompt provided (pass via stdin or --prompt)\n');
    process.exit(2);
  }

  const logDir = mkdtempSync(join(tmpdir(), 'gemini-verify-'));
  const logPath = join(logDir, 'agy.log');
  const startMs = Date.now();

  // Spawn agy exactly like the proven driver: prompt written to stdin,
  // `-p` print mode, shell:false (MUST NOT pop a console), windowsHide:true.
  // NO permission-bypass / auto-approve flag anywhere.
  // Pass prompt via argv to avoid stdin truncation for large diffs.
  const agyArgs = ['-p', prompt, '--log-file', logPath];
  if (args.model) agyArgs.push('-m', args.model);

  const child = spawn(process.env.AGY_CMD || 'agy', agyArgs, {
    cwd: args.cwd,
    env: process.env,
    shell: false,
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  let stderrBuf = '';
  child.stdout.on('data', () => {}); // print mode emits nothing here; drained.
  child.stderr.on('data', (d) => { stderrBuf += d.toString(); });

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    try { child.kill('SIGKILL'); } catch { /* ignore */ }
  }, args.timeout);

  const exitCode = await new Promise((resolve) => {
    child.on('error', (err) => {
      process.stderr.write(`gemini-verify: failed to spawn 'agy': ${err.message}\n`);
      resolve(-1);
    });
    child.on('close', (code) => resolve(code));
    child.stdin.on('error', () => {}); // tolerate EPIPE if agy exits early
    // Prompt is now passed via argv, we just close stdin
    child.stdin.end();
  });
  clearTimeout(timer);

  if (timedOut) {
    process.stderr.write(`gemini-verify: timed out after ${args.timeout}ms\n`);
    process.exit(124);
  }
  if (exitCode === -1) process.exit(1);
  if (exitCode !== 0) {
    process.stderr.write(`gemini-verify: agy exited ${exitCode}. stderr=${stderrBuf.slice(0, 500)}\n`);
    process.exit(exitCode || 1);
  }

  // Locate this run's transcript and extract the final assistant text.
  // The transcript is written just before agy exits, but allow a short poll
  // window in case of filesystem lag.
  const id = conversationIdFromLog(logPath);
  let text = '';
  for (let attempt = 0; attempt < 20; attempt++) {
    let path = id ? transcriptPathForId(id) : null;
    text = finalTextFromTranscript(path);
    if (!text) {
      // Fall back to the newest transcript touched during this run.
      path = newestTranscriptSince(startMs - 2000);
      text = finalTextFromTranscript(path);
    }
    if (text) break;
    await sleep(250);
  }

  if (!text) {
    process.stderr.write(
      'gemini-verify: no assistant text captured ' +
      `(conversation id=${id || 'unknown'}, log=${logPath}). ` +
      'agy may not be authenticated, or the transcript was not written.\n'
    );
    process.exit(3);
  }

  process.stdout.write(text + '\n');
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`gemini-verify: unexpected error: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
