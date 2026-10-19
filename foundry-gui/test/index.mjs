import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

const testFiles = fs
  .readdirSync(here)
  .filter((f) => f.endsWith('.test.mjs') && f !== 'index.mjs')
  .sort();

for (const f of testFiles) {
  await import(pathToFileURL(path.join(here, f)).href);
}
