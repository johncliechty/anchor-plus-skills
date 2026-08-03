import fs from 'node:fs';
import path from 'node:path';

const TARGET = process.cwd();
const STATUS_FILE = path.join(TARGET, '_foreman-status.log');

function emit(line) {
  const stamp = new Date().toISOString().slice(11, 19);
  const out = `[${stamp}] ${line}\n`;
  process.stdout.write(out);
  try { fs.appendFileSync(STATUS_FILE, out); } catch { /* ignore */ }
}

const { runProject } = await import('fil<path>');
const { makeForemanDriver } = await import('fil<path>');

try { fs.writeFileSync(STATUS_FILE, ''); } catch { /* ignore */ }
emit(`=== RAMANUJAN FOREMAN LIVE RUN ===`);
emit(`target: ${TARGET}`);

let result;
try {
  result = await runProject({
    projectDir: TARGET,
    driver: await makeForemanDriver({ log: (s) => emit(s) }),
    reviewerCount: 2,
    fixIterCap: 2,
    resume: fs.existsSync('foreman-checkpoint.json'),
    log: (s) => emit(s),
  });
} catch (e) {
  emit(`!! runProject THREW: ${e.name}: ${e.message}`);
}

emit(`SUMMARY: status=${result?.status ?? 'THREW'}`);
