import fs from 'node:fs';
import path from 'node:path';

const TARGET = process.cwd();
const STATUS_FILE = path.join(TARGET, '_foreman-status.log');

// --max-waves N: HARD pre-flight budget (e.g. `--max-waves 1` for a Wave-1 proving run).
// Omit for a full autonomous build. Foreman resumes from foreman-checkpoint.json if present.
const MAX_WAVES = (() => {
  const i = process.argv.indexOf('--max-waves');
  return i >= 0 && process.argv[i + 1] != null ? Number(process.argv[i + 1]) : null;
})();

function emit(line) {
  const stamp = new Date().toISOString().slice(11, 19);
  const out = `[${stamp}] ${line}\n`;
  process.stdout.write(out);
  try { fs.appendFileSync(STATUS_FILE, out); } catch { /* ignore */ }
}

const { runProject } = await import('fil<path>');
const { makeForemanDriver } = await import('fil<path>');

try { fs.writeFileSync(STATUS_FILE, ''); } catch { /* ignore */ }
emit(`=== LITERATURE REVIEW FOREMAN LIVE RUN ===`);
emit(`target: ${TARGET}`);
emit(`budget: ${MAX_WAVES == null ? 'unlimited (full build)' : MAX_WAVES + ' wave(s) this run'}`);

let result;
try {
  result = await runProject({
    projectDir: TARGET,
    driver: await makeForemanDriver({ log: (s) => emit(s) }),
    reviewerCount: 2,
    fixIterCap: 2,
    resume: fs.existsSync('foreman-checkpoint.json'),
    budgetConfig: MAX_WAVES != null ? { maxWaves: MAX_WAVES } : undefined,
    log: (s) => emit(s),
  });
} catch (e) {
  emit(`!! runProject THREW: ${e.name}: ${e.message}`);
}

emit(`SUMMARY: status=${result?.status ?? 'THREW'}`);
