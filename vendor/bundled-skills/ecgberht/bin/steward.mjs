#!/usr/bin/env node
/**
 * Ecgberht STEWARD portfolio CLI — the second closed surface.
 *
 * Usage: node bin/steward.mjs <verb> [--root <path>] [--home <path>]
 *
 * Separate from `bin/ecgberht.mjs` on purpose: that binary owns the fifteen
 * per-project talk acts, this one owns the portfolio/index operator verbs. Two
 * surfaces, named separately in engine/verbs.mjs, each closed — folding them into
 * one list would widen a surface Stage 2 froze at fifteen.
 *
 * Unknown verbs → structured JSON refuse (exit 1). Never open plugin dispatch.
 */

import { runStewardVerb } from '../engine/steward-surface.mjs';
import { isDirectInvocation } from '../engine/direct-invocation.mjs';

/**
 * Parse the small flag set this surface accepts.
 * @param {string[]} argv
 * @returns {{verb: string|null, opts: object}}
 */
export function parseStewardArgv(argv) {
  const tokens = Array.isArray(argv) ? argv.map(String) : [];
  const opts = {};
  let verb = null;

  for (let i = 0; i < tokens.length; i += 1) {
    const t = tokens[i];
    if (t === '--root' || t === '-r' || t === '--project' || t === '-p') {
      opts.root = tokens[i + 1] ?? null;
      i += 1;
      continue;
    }
    if (t === '--home' || t === '-H') {
      opts.home = tokens[i + 1] ?? null;
      i += 1;
      continue;
    }
    if (t.startsWith('--root=')) { opts.root = t.slice('--root='.length); continue; }
    if (t.startsWith('--project=')) { opts.root = t.slice('--project='.length); continue; }
    if (t.startsWith('--home=')) { opts.home = t.slice('--home='.length); continue; }
    if (t.startsWith('-')) continue; // unknown flag: ignored, never the verb
    if (verb === null) verb = t;
  }
  return { verb, opts };
}

/**
 * CLI runner (importable for tests).
 * @param {string[]} argv
 * @param {{ write?: (s: string) => void, exit?: (code: number) => void }} [io]
 */
export function runStewardCli(argv, io = {}) {
  const write = io.write ?? ((s) => process.stdout.write(s));
  const exit = io.exit ?? ((code) => process.exit(code));
  const { verb, opts } = parseStewardArgv(argv);

  const result =
    verb === null
      ? runStewardVerb('', opts) // no verb → the surface's own structured refusal
      : runStewardVerb(verb, opts);

  const exitCode = result && result.ok === true ? 0 : 1;
  write(`${JSON.stringify(result, null, 2)}\n`);
  exit(exitCode);
  return { result, exitCode };
}

// Junction/symlink-safe — see engine/direct-invocation.mjs. This CLI shipped with the
// old guard hours before the sleep cycle caught it, so it too was a silent no-op via
// the registered skill path.
if (isDirectInvocation(process.argv[1], import.meta.url)) {
  runStewardCli(process.argv.slice(2));
}
