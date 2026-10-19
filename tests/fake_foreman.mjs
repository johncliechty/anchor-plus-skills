// A hermetic stand-in for the trio's foreman/bin/run-live.mjs, used by tests/test_foreman_code_job_2026_10_10.py
// through code_jobs.FOREMAN_RUN_LIVE. It writes what the real run leaves behind - the project's edited file and
// .foreman/run-record.json - as FAKE_FOREMAN_MODE chooses:
//   done (default) | halt | stray (also writes FAKE_FOREMAN_STRAY, outside the project) | new-file (also adds b.py)
//   | staged (also adds report.json and stages it with git)
//   | own (writes a file named for its worktree, so parallel jobs touch different files)
//   | sleep (starts a child that keeps writing .foreman/child.pid, then waits)
//   | straggler (starts a detached child that outlives it, then finishes DONE)
// FAKE_FOREMAN_LOG (a file) records argv, foreman.config.json's documents, the plan, the profile and the settings
// Anchor gave it (ANCHOR_DATA_DIR/settings.json).
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

const project = path.resolve(process.argv[2]);
const mode = process.env.FAKE_FOREMAN_MODE || 'done';
const write = (rel, text) => {
  fs.mkdirSync(path.dirname(path.join(project, rel)), { recursive: true });
  fs.writeFileSync(path.join(project, rel), text, 'utf8');
};
if (process.env.FAKE_FOREMAN_LOG) {
  const cfg = JSON.parse(fs.readFileSync(path.join(project, 'foreman.config.json'), 'utf8'));
  const plan = fs.readFileSync(path.join(project, cfg.docs.plan), 'utf8');
  let settings = null;
  try { settings = JSON.parse(fs.readFileSync(path.join(process.env.ANCHOR_DATA_DIR, 'settings.json'), 'utf8')); } catch { /* none */ }
  fs.appendFileSync(process.env.FAKE_FOREMAN_LOG, JSON.stringify({ argv: process.argv.slice(2), docs: cfg.docs, plan,
    profile: process.env.FOREMAN_PROFILE, settings }) + '\n');
}
const child = (detached) => {
  const pidFile = path.join(project, '.foreman', 'child.pid');
  const code = `const fs=require('fs');setInterval(()=>fs.writeFileSync(${JSON.stringify(pidFile)},String(process.pid)),100)`;
  const c = spawn(process.execPath, ['-e', code], { detached, stdio: 'ignore' });
  if (detached) c.unref();
};
if (mode === 'sleep') {
  fs.mkdirSync(path.join(project, '.foreman'), { recursive: true });
  child(false);
  write('.foreman/started', String(process.pid));
  setTimeout(() => {}, 600000);
} else {
  if (mode === 'straggler') child(true);
  write(mode === 'own' ? `out-${path.basename(project)}.txt` : 'a.txt', 'two\n');
  if (mode === 'new-file') write('b.py', 'x = 1\n');
  if (mode === 'staged') {                    // a new file a script STAGED (not untracked any more)
    write('report.json', '{}\n');
    spawnSync('git', ['add', 'report.json'], { cwd: project });
  }
  if (mode === 'stray') fs.writeFileSync(process.env.FAKE_FOREMAN_STRAY, 'written outside the worktree\n', 'utf8');
  const status = mode === 'halt' ? 'HALT' : 'DONE';
  write('.foreman/run-record.json', JSON.stringify({ schema: 'foreman-run-record/v1', status,
    halt_reason: status === 'HALT' ? 'the gate stayed red [taxonomy:no-progress]' : null,
    waves: [{ wave: 1, status: status === 'HALT' ? 'HALTED' : 'GREEN' }] }));
  if (mode === 'straggler') setTimeout(() => process.exit(0), 500);
}
