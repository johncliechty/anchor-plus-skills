#!/usr/bin/env node
/**
 * Ecgberht CLI — closed verb surface only.
 * Usage: node bin/ecgberht.mjs <verb> [args...]
 * Unknown verbs → structured JSON refuse (exit 1). Never open plugin dispatch.
 */

import { main, isDirectInvocation } from '../engine/index.mjs';

/**
 * CLI runner (importable for tests).
 * @param {string[]} argv
 * @param {{ write?: (s: string) => void, exit?: (code: number) => void }} [io]
 */
export function runCli(argv, io = {}) {
  const write = io.write ?? ((s) => process.stdout.write(s));
  const exit = io.exit ?? ((code) => process.exit(code));
  const result = main(argv);
  const exitCode = result && result.ok === true ? 0 : 1;
  write(`${JSON.stringify(result, null, 2)}\n`);
  exit(exitCode);
  return { result, exitCode };
}

// Junction/symlink-safe (sleep cycle 2026-08-04, from gandalf journal 0275): the old
// guard compared resolve(argv[1]) against this module's path, which are DIFFERENT
// STRINGS for the SAME FILE through a junction — so invoking via the registered skill
// path `~/.claude/skills/ecgberht/bin/...` exited 0 and printed NOTHING.
if (isDirectInvocation(process.argv[1], import.meta.url)) {
  runCli(process.argv.slice(2));
}
