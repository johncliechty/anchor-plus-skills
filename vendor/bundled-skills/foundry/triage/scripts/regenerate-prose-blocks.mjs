#!/usr/bin/env node
// Regenerate committed NS-01 triage prose blocks (Wave 6).
// Usage (from package root):
//   node scripts/regenerate-prose-blocks.mjs
//   node scripts/regenerate-prose-blocks.mjs --check   # exit 1 on drift
//
// CI: npm run regenerate-prose-blocks:check  (or gate via test/wave6-*.test.mjs)

import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  WAVE6_BLOCK_SKILLS,
  ALL_SKILLS,
  generatedBlockFileName,
  renderGeneratedFile,
  normalizeGeneratedText,
  diffGenerated,
} from '../prose-block.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');
const outDir = join(pkgRoot, 'generated');

const args = process.argv.slice(2);
const checkOnly = args.includes('--check');
const all = args.includes('--all');
const ids = all ? ALL_SKILLS : WAVE6_BLOCK_SKILLS;

mkdirSync(outDir, { recursive: true });

let drift = 0;
for (const id of ids) {
  const name = generatedBlockFileName(id);
  const path = join(outDir, name);
  const expected = normalizeGeneratedText(renderGeneratedFile(id));
  if (checkOnly) {
    if (!existsSync(path)) {
      console.error(`MISSING ${name} — run: node scripts/regenerate-prose-blocks.mjs`);
      drift += 1;
      continue;
    }
    const actual = normalizeGeneratedText(readFileSync(path, 'utf8'));
    const d = diffGenerated(expected, actual);
    if (!d.match) {
      console.error(`DRIFT ${name}: ${d.detail}`);
      drift += 1;
    } else {
      console.log(`ok ${name}`);
    }
  } else {
    writeFileSync(path, expected, 'utf8');
    console.log(`wrote ${name}`);
  }
}

if (checkOnly && drift > 0) {
  console.error(`regenerate-and-diff: ${drift} file(s) out of date`);
  process.exit(1);
}
if (checkOnly) {
  console.log(`regenerate-and-diff: ${ids.length} file(s) clean`);
}
