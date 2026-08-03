import fs from 'node:fs';
import path from 'node:path';

process.env.CRUCIBLE_AGENT_LIVE = "1";
process.env.TRIO_DRIVER = "gemini-cli";

const TARGET = process.cwd();
const STATUS_FILE = path.join(TARGET, '_foreman-status.log');

function emit(line) {
  const stamp = new Date().toISOString().slice(11, 19);
  const out = `[${stamp}] ${line}\n`;
  process.stdout.write(out);
  try { fs.appendFileSync(STATUS_FILE, out); } catch { /* ignore */ }
}

const { runProject } = await import('../../../trio/foreman/bin/project-engine.mjs');
const { makeForemanDriver } = await import('../../../trio/drivers/index.mjs');

// Reset checkpoint so we start fresh from wave 1
try { fs.unlinkSync(path.join(TARGET, 'foreman-checkpoint.json')); } catch {}
try { fs.writeFileSync(STATUS_FILE, ''); } catch { /* ignore */ }
emit(`=== JUMPER FOREMAN LIVE RUN ===`);
emit(`target: ${TARGET}`);

let result;
try {
  result = await runProject({
    projectDir: TARGET,
    driver: await makeForemanDriver({ log: (s) => emit(s) }),
    reviewerCount: 2,
    fixIterCap: 4,
    resume: false,
    log: (s) => emit(s),
  });
} catch (e) {
  emit(`!! runProject THREW: ${e.name}: ${e.message}`);
}

emit(`SUMMARY: status=${result?.status ?? 'THREW'}`);
