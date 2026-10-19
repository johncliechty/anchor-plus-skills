#!/usr/bin/env node
// agy_job_adapter.mjs — Anchor job_runner's Gemini transport shim.
//
// This host has NO bare `gemini` CLI; Gemini IS the `agy` (Antigravity) CLI. job_runner captures a child's
// STDOUT and parses stream-json envelopes, so this shim runs ONE agy turn and re-emits the reply as exactly ONE
// stream-json `result` line, which job_runner.extract_assistant_text (and gandalf._map_shards / summarizer) parse
// unchanged.
//
// 2026-10-07: agy 1.3.x streams JSON itself (`--input-format stream-json --output-format stream-json -p=`, the
// prompt as ONE NDJSON {"event":"user","message":{...}} on stdin, proven to 80 KB), so the shim drives agy directly.
// It no longer goes through agy-dispatch.mjs, whose transcript polling and model-label allowlist date from agy 1.0
// and refuse today's ids (gemini-3.8-flash-high).
//
// Invoked by job_runner._build_gemini_argv as:
//   node agy_job_adapter.mjs --prompt-file <f> --model <agy model id> [--readonly] --target <dir>

import { spawn } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const isMain = process.argv[1] && process.argv[1] === fileURLToPath(import.meta.url);

export function agyExecutable(env = process.env) {
  const local = path.join(env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'agy', 'bin', 'agy.exe');
  return env.ANCHOR_AGY_EXE || (existsSync(local) ? local : 'agy');
}

export function agyArgs({ model, readonly }) {
  const args = ['--input-format', 'stream-json', '--output-format', 'stream-json', '--model', model];
  // plan mode: agy reads and answers but does not edit; a write-capable lane (research) runs in agy's default
  // print-mode posture, which proceeds without asking.
  if (readonly) args.push('--mode', 'plan');
  args.push('-p=');
  return args;
}

// agy's text can carry stray raw control characters; a JSON draft downstream must stay parseable. The model escapes
// its own newlines, so a raw byte below 32 (other than tab) is flattened to a space.
export function flatten(text) {
  return Array.from(String(text || ''), (ch) => (ch.charCodeAt(0) < 32 && ch !== '\t' ? ' ' : ch)).join('');
}

if (isMain) {
  const argVal = (flag) => {
    const i = process.argv.indexOf(flag);
    return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
  };
  const emit = (text) => process.stdout.write(JSON.stringify({ type: 'result', result: String(text || '') }) + '\n');

  const promptFile = argVal('--prompt-file');
  const model = argVal('--model') || process.env.GEMINI_MODEL || 'gemini-3.8-flash-high';
  const target = argVal('--target') || process.cwd();
  const readonly = process.argv.includes('--readonly');
  if (!promptFile) {
    process.stderr.write('agy_job_adapter: --prompt-file required\n');
    emit('');
    process.exit(2);
  }
  const prompt = readFileSync(promptFile, 'utf8');
  const child = spawn(agyExecutable(), agyArgs({ model, readonly }), {
    cwd: existsSync(target) ? target : process.cwd(), stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true,
  });
  let buffer = '';
  let response = '';
  let streamed = '';
  let status = null;
  let error = '';
  child.stdout.on('data', (chunk) => {
    buffer += chunk.toString('utf8');
    let nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      if (event.event === 'step_update' && event.step_update?.step_type === 'agent_response'
          && typeof event.step_update.text_delta === 'string') {
        streamed += event.step_update.text_delta;
      } else if (event.event === 'result' && event.result) {
        status = event.result.status;
        response = typeof event.result.response === 'string' ? event.result.response : '';
        error = event.result.error || '';
        // progress for the job log (stderr is folded into it; stdout carries only the one result line)
        process.stderr.write(JSON.stringify({ label: 'agy', status, conversation_id: event.result.conversation_id,
          usage: event.result.usage }) + '\n');
      }
    }
  });
  child.stdin.end(JSON.stringify({ event: 'user', message: { role: 'user', content: prompt } }) + '\n');
  child.on('close', (code) => {
    const text = flatten(response || streamed);
    if (status !== 'SUCCESS' && error) process.stderr.write(`agy_job_adapter: agy reported ${status}: ${error}\n`);
    emit(status === 'SUCCESS' ? text : '');
    // Exit 0 only for a real reply, so job_runner marks the job DONE (gandalf skips non-done shards).
    process.exit(status === 'SUCCESS' && text.trim() ? 0 : (code || 1));
  });
}
