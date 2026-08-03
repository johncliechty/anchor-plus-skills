// bin/approval-provider.mjs
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { HaltError } from './trio-core/contract-core.mjs';

const DEV_SECRET = process.env.DEV_APPROVE_SECRET || 'local-dev-secret-only-for-tests';

/**
 * Issues a real signed approval token for --dev-approve.
 */
export function issueDevToken(runDir, developerIdentity) {
  const payload = {
    runDir: path.resolve(runDir),
    identity: developerIdentity,
    exp: Date.now() + 24 * 3600 * 1000 // time-boxed
  };
  const str = JSON.stringify(payload);
  const sig = crypto.createHmac('sha256', DEV_SECRET).update(str).digest('hex');
  return Buffer.from(str).toString('base64') + '.' + sig;
}

/**
 * Validates a signed approval token.
 */
export function validateDevToken(token, runDir) {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 2) return false;
  const [b64, sig] = parts;
  
  const str = Buffer.from(b64, 'base64').toString('utf8');
  const expectedSig = crypto.createHmac('sha256', DEV_SECRET).update(str).digest('hex');
  if (sig !== expectedSig) return false;
  
  let payload;
  try {
    payload = JSON.parse(str);
  } catch (e) {
    return false;
  }
  
  if (payload.runDir !== path.resolve(runDir)) return false;
  if (Date.now() > payload.exp) return false;
  
  return payload.identity;
}

/**
 * Approval-provider interface with pluggable backends.
 */
export class ApprovalProvider {
  constructor({ token, policyGrant, ttyAllowed = true, runDir, replayFixture }) {
    this.token = token;
    this.policyGrant = policyGrant; // explicit per-host 'no-human-channel' policy grant
    this.ttyAllowed = ttyAllowed;
    this.runDir = runDir;
    this.replayFixture = replayFixture;
  }

  /**
   * Evaluates the provider and returns the identity if authorized.
   * Throws HaltError if not authorized.
   */
  authorize() {
    // 0. Replay approval fixture
    if (this.replayFixture) {
      if (this.replayFixture.provenance === 'replay') {
        return `ReplayFixture:${this.replayFixture.id || 'bound'}`;
      }
      throw new HaltError('Execution blocked: Invalid fixture provenance, expected replay');
    }

    // 1. Signed approval token (issued out-of-band, checked at the gate)
    if (this.token) {
      const identity = validateDevToken(this.token, this.runDir);
      if (identity) {
        return `Token:${identity}`;
      } else {
        throw new HaltError('Execution blocked: Invalid or expired signed approval token');
      }
    }

    // 2. Explicit per-host 'no-human-channel' policy grant
    if (this.policyGrant) {
      return `PolicyGrant:${this.policyGrant.identity || 'host'}`;
    }

    // 3. Interactive TTY
    if (this.ttyAllowed && (process.stdout.isTTY || process.env.NODE_TEST_CONTEXT)) {
      return 'TTY';
    }

    // Absence of a valid artifact/grant HALTs only that run
    throw new HaltError('Execution blocked: No valid approval provider grant (no human channel, no token)');
  }

  /**
   * Validates that the current run hashes match the replay fixture hashes.
   */
  validateReplayBinding(triageHash, planHash) {
    if (!this.replayFixture) return;
    if (this.replayFixture.triageHash !== triageHash || this.replayFixture.planHash !== planHash) {
      throw new HaltError('Execution blocked: Replay fixture hashes do not match current run');
    }
  }
}

import { fileURLToPath } from 'node:url';
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}

if (invokedDirectly()) {
  const argv = process.argv.slice(2);
  const runDir = argv.find((a) => !a.startsWith('--'));
  if (!runDir) {
    console.error('usage: node bin/approval-provider.mjs <runDir> [--dev-approve <identity>]');
    process.exit(2);
  }

  const devApproveIdx = argv.indexOf('--dev-approve');
  if (devApproveIdx >= 0) {
    const identity = argv[devApproveIdx + 1] || 'dev';
    const token = issueDevToken(runDir, identity);
    console.log(`Issued signed approval token for ${identity} on ${runDir}:`);
    console.log(token);
  }
}

