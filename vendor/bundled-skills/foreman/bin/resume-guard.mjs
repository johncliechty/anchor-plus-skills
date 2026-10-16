import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '../..');
const LOCK_FILE = path.join(REPO_ROOT, 'build-lock.json');

// Lock Lifecycle: ACQUIRE -> HOLD -> RELEASE -> CRASH-RECOVERY (fail-closed via named human-clear step)
export class BuildLock {
  static read() {
    if (!fs.existsSync(LOCK_FILE)) return null;
    return JSON.parse(fs.readFileSync(LOCK_FILE, 'utf8'));
  }

  static write(data) {
    fs.writeFileSync(LOCK_FILE, JSON.stringify(data, null, 2) + '\n');
  }

  static acquire(holder) {
    const state = this.read() || {};
    if (state.holder && state.committing_state) {
      throw new Error(`Lock is held by ${state.holder} in COMMITTING state. Cannot acquire.`);
    }
    state.holder = holder;
    state.committing_state = false;
    state.resume_interlock = true;
    state.pid = process.pid;
    state.liveness_heartbeat = new Date().toISOString();
    this.write(state);
  }

  static hold() {
    const state = this.read();
    if (state && state.pid === process.pid) {
      state.liveness_heartbeat = new Date().toISOString();
      this.write(state);
    }
  }

  static release() {
    const state = this.read();
    if (state && state.pid === process.pid) {
      state.holder = null;
      state.committing_state = false;
      state.resume_interlock = false;
      state.pid = null;
      this.write(state);
    }
  }

  static setCommittingState(isCommitting) {
    const state = this.read();
    if (state && state.pid === process.pid) {
      state.committing_state = isCommitting;
      this.write(state);
    }
  }

  static verifyResumeGate() {
    const state = this.read();
    if (!state) return; // Clean
    
    // ABORTS resume on a live- OR stale-committing hold
    if (state.holder && state.committing_state) {
      console.error(`\n[RESUME GUARD] ABORTING RESUME (fail-closed)`);
      console.error(`[RESUME GUARD] The trio commit-lock records a committing hold by ${state.holder}.`);
      console.error(`[RESUME GUARD] Heartbeat: ${state.liveness_heartbeat}`);
      console.error(`[RESUME GUARD] A human must clear the crashed committing state before resuming (CRASH-RECOVERY).\n`);
      process.exit(1);
    }
  }
}

// When invoked directly as a script (e.g. from go.ps1)
if (import.meta.url === `file://${process.platform === 'win32' ? __filename.replace(/\\/g, '/') : __filename}`) {
  BuildLock.verifyResumeGate();
}
