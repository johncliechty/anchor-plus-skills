import test from 'node:test';
import assert from 'node:assert';
import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const START_SCRIPT = path.join(__dirname, '..', 'start.mjs');

test('start.mjs parses --intent and triggers executeMetaSkillPipeline', async (t) => {
  try {
    const output = execSync(`node "${START_SCRIPT}" --intent "Build X"`, { encoding: 'utf8', stdio: 'pipe' });
    assert.ok(output.includes('Starting pipeline for intent: "Build X"'), 'Output should indicate pipeline started');
  } catch (err) {
    assert.ok(err.stdout.includes('Starting pipeline for intent: "Build X"'), 'Output should indicate pipeline started even if it failed later');
  }
});
