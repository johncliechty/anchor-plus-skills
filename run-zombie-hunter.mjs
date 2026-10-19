import fs from 'node:fs';
import path from 'node:path';

process.env.CRUCIBLE_AGENT_LIVE = "1";
process.env.TRIO_DRIVER = "gemini-cli";
process.env.GEMINI_MODEL = "gemini-1.5-pro"; // Enforcing most capable model

const TARGET = "C:\\dev\\Anchor";
const STATUS_FILE = path.join(TARGET, '_foreman-status.log');

function emit(line) {
  const stamp = new Date().toISOString().slice(11, 19);
  const out = `[${stamp}] ${line}\n`;
  process.stdout.write(out);
  try { fs.appendFileSync(STATUS_FILE, out); } catch { /* ignore */ }
}

const { runProject } = await import('file:///C:/dev/trio/foreman/bin/project-engine.mjs');
const { makeForemanDriver } = await import('file:///C:/dev/trio/drivers/index.mjs');

emit(`=== ZOMBIE HUNTER FOREMAN LIVE RUN ===`);
emit(`target: ${TARGET}`);

let result;
try {
  result = await runProject({
    projectDir: TARGET,
    driver: await makeForemanDriver({ log: (s) => emit(s) }),
    git: { branch: 'foreman/zombie-hunter' },
    reviewerCount: 2,
    fixIterCap: 4,
    resume: false,
    log: (s) => emit(s),
  });
} catch (e) {
  emit(`!! runProject THREW: ${e.name}: ${e.message}`);
}

emit(`SUMMARY: status=${result?.status ?? 'THREW'}`);
