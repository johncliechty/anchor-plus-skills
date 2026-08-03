#!/usr/bin/env node
// bin/intake.mjs — Wave 4 Stage-0 triage emission + Wave-5 / Phase-1 @foundry/triage wire
//
// Triage (tier × depth + knobs) lives ONLY in the intake extension payload via
// researchprime-wire.mjs. governance.mjs is never imported here (byte-identity pin).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';
import { HaltError } from './trio-core/contract-core.mjs';

import { importFoundryTriage } from '../../drivers/foundry-triage-resolve.mjs';
const {
  buildResearchPrimeIntakeExtension,
  recommendResearchPrimeIntake,
  NS01_WAVE5_STAMP,
} = await importFoundryTriage('researchprime-wire.mjs');

/**
 * Perform intake, durably emit the Stage-0 triage artifact (+ extension), then prompt.
 * @param {object} inputs The intake data.
 * @param {object} options
 * @param {string} options.runDir Directory to write the artifact to.
 * @param {function} options.promptHuman Async function to prompt the human (returns 'APPROVE', 'EDIT', or 'ABORT').
 * @param {function} options.onBeforePrompt Optional callback before the prompt (used for testing crash-before-prompt).
 * @param {string} [options.confirmedDepth] Optional pre-confirmed process depth.
 * @param {string} [options.confirmedTier] Optional pre-confirmed model tier.
 * @param {object} [options.triageLock] Optional pre-built lock record.
 * @param {boolean} [options.headless]
 * @param {object} [options.triageConfig]
 * @returns {Promise<{ artifactPath, triageHash, decision, extension }>}
 */
/**
 * Load the latest locked (or advisory) intake extension from a runDir.
 * Used by run-rounds / formal path to honor band knobs (maxRounds, includeAdjudication).
 * @param {string} runDir
 * @returns {null | { extension: object, path: string, locked: boolean }}
 */
export function loadTriageExtensionFromRunDir(runDir) {
  if (!runDir || !fs.existsSync(runDir)) return null;
  let files;
  try {
    files = fs.readdirSync(runDir).filter((f) => /^triage-extension-.*\.json$/.test(f));
  } catch {
    return null;
  }
  if (!files.length) {
    // Fall back: any triage-*.json with .extension
    try {
      const triageFiles = fs.readdirSync(runDir).filter((f) => /^triage-[a-f0-9]+\.json$/i.test(f));
      for (const f of triageFiles.sort().reverse()) {
        const p = path.join(runDir, f);
        const data = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (data && data.extension) {
          return {
            extension: data.extension,
            path: p,
            locked: !!data.extension.locked,
          };
        }
      }
    } catch {
      return null;
    }
    return null;
  }
  // Prefer newest by mtime
  files.sort((a, b) => {
    const sa = fs.statSync(path.join(runDir, a)).mtimeMs;
    const sb = fs.statSync(path.join(runDir, b)).mtimeMs;
    return sb - sa;
  });
  const p = path.join(runDir, files[0]);
  try {
    const extension = JSON.parse(fs.readFileSync(p, 'utf8'));
    return { extension, path: p, locked: !!extension.locked };
  } catch {
    return null;
  }
}

/**
 * Formal / headless predicate for band-budget fail-closed.
 * Explicit `headless:true` wins; `headless:false` disables env auto-detect;
 * otherwise RESEARCHPRIME_HEADLESS=1|true marks RP formal headless.
 *
 * @param {object} [opts]
 * @param {boolean} [opts.headless]
 * @param {object} [opts.env]
 * @returns {boolean}
 */
export function isHeadlessFormal({ headless, env = process.env } = {}) {
  if (headless === true) return true;
  if (headless === false) return false;
  const v = env?.RESEARCHPRIME_HEADLESS;
  if (v === '1' || v === 'true' || v === true) return true;
  return false;
}

/**
 * Resolve hard round budget from (explicit CLI > env > locked triage knobs > default).
 *
 * Sole budget resolver for run-rounds (Track B1 W3). includeAdjudication is NEVER
 * taken from argv/env — extension knobs only. Under headless / formal fail-closed,
 * missing extension or locked!==true throws HaltError (no source==='default' FULL
 * knobs: cap=8, includeAdjudication=true). CLI maxRounds is not a lock substitute.
 *
 * @param {object} [opts]
 * @param {string} [opts.runDir]
 * @param {number|null} [opts.maxRounds]  explicit CLI --max-rounds only
 * @param {object} [opts.env]
 * @param {number} [opts.fallback=8]
 * @param {boolean} [opts.headless]  force headless formal predicate
 * @param {boolean} [opts.failClosed]  force fail-closed even if not headless (run-rounds formal path)
 * @returns {{ cap: number, source: string, knobs: object|null, includeAdjudication: boolean, locked: boolean }}
 */
export function resolveBandRoundBudget({
  runDir = null,
  maxRounds = null,
  env = process.env,
  fallback = 8,
  headless,
  failClosed,
} = {}) {
  const loaded = runDir ? loadTriageExtensionFromRunDir(runDir) : null;
  const knobs = loaded?.extension?.knobs && typeof loaded.extension.knobs === 'object'
    ? loaded.extension.knobs
    : null;
  const locked = !!(loaded && (loaded.locked === true || loaded.extension?.locked === true));

  // Fail-closed: headless (or RP formal headless) OR explicit failClosed (run-rounds).
  const formalClosed =
    failClosed === true || isHeadlessFormal({ headless, env });

  if (formalClosed && (!loaded || locked !== true)) {
    throw new HaltError(
      'run-rounds band budget HALT: headless/formal path requires a locked triage extension ' +
        '(missing extension or locked!==true). Refusing source=default FULL knobs ' +
        `(cap=${fallback}, includeAdjudication=true). CLI/env maxRounds is not a lock substitute. ` +
        'Gate-1 must emit triage-extension-*.json with locked:true before formal rounds.',
      {
        code: 'BAND_UNLOCKED_HEADLESS',
        runDir,
        hasExtension: !!loaded,
        locked,
      },
    );
  }

  // includeAdjudication: extension knobs ONLY — never --include-adjudication or env.
  let includeAdjudication;
  if (knobs && Object.prototype.hasOwnProperty.call(knobs, 'includeAdjudication')) {
    includeAdjudication = !!knobs.includeAdjudication;
  } else if (formalClosed) {
    throw new HaltError(
      'run-rounds band budget HALT: locked extension missing knobs.includeAdjudication — ' +
        'refuse invented FULL adjudication default',
      { code: 'BAND_MISSING_ADJUDICATION_KNOB', runDir },
    );
  } else {
    // Interactive / non-formal soft path only (never under headless unlocked).
    includeAdjudication = true;
  }

  // Cap precedence: explicit maxRounds arg > RESEARCHPRIME_MAX_ROUNDS env > locked knobs > fallback.
  // (CLI/env only apply after lock gate when formalClosed — already enforced above.)
  if (maxRounds != null && Number.isFinite(Number(maxRounds)) && Number(maxRounds) > 0) {
    return {
      cap: Math.floor(Number(maxRounds)),
      source: 'explicit',
      knobs,
      includeAdjudication,
      locked,
    };
  }
  const envRaw = env?.RESEARCHPRIME_MAX_ROUNDS;
  if (envRaw != null && String(envRaw).trim() !== '' && Number.isFinite(Number(envRaw)) && Number(envRaw) > 0) {
    return {
      cap: Math.floor(Number(envRaw)),
      source: 'env',
      knobs,
      includeAdjudication,
      locked,
    };
  }
  if (knobs && typeof knobs.maxRounds === 'number' && knobs.maxRounds > 0) {
    return {
      cap: Math.floor(knobs.maxRounds),
      source: locked ? 'triage-lock' : 'triage-advisory',
      knobs,
      includeAdjudication,
      locked,
    };
  }

  // Would invent source=default FULL knobs (cap=fallback, includeAdjudication often true).
  if (formalClosed) {
    throw new HaltError(
      `run-rounds band budget HALT: refuse source=default FULL knobs (cap=${fallback}, ` +
        'includeAdjudication=true) under headless/formal — locked extension lacks knobs.maxRounds',
      { code: 'BAND_DEFAULT_REFUSED', runDir, locked },
    );
  }

  return {
    cap: fallback,
    source: 'default',
    knobs,
    includeAdjudication,
    locked,
  };
}

export async function runIntake(inputs, {
  runDir,
  promptHuman,
  onBeforePrompt,
  confirmedDepth,
  confirmedTier,
  triageLock,
  headless,
  triageConfig,
} = {}) {
  const recommendation = recommendResearchPrimeIntake(inputs || {});

  // Pre-prompt extension: advisory knobs; locked:false until Gate-1 APPROVE / explicit lock.
  const preExtension = buildResearchPrimeIntakeExtension(inputs || {}, {
    recommendation,
    confirmedDepth,
    confirmedTier,
    triageLock,
    headless,
    triageConfig,
    requireLock: false,
  });

  const triageData = {
    inputs,
    timestamp: new Date().toISOString(),
    stamp: NS01_WAVE5_STAMP,
    extension: preExtension,
  };

  const triageStr = JSON.stringify(triageData, null, 2);
  const triageHashStr = JSON.stringify({ inputs }, null, 2);
  const triageHash = crypto.createHash('sha256').update(triageHashStr).digest('hex');

  fs.mkdirSync(runDir, { recursive: true });
  const artifactPath = path.join(runDir, `triage-${triageHash}.json`);

  // Durably write the artifact BEFORE any prompt
  fs.writeFileSync(artifactPath, triageStr, 'utf8');
  // Dedicated extension surface (Wave-5 contract — greppable "extension" write)
  const extensionPath = path.join(runDir, `triage-extension-${triageHash}.json`);
  fs.writeFileSync(extensionPath, JSON.stringify(preExtension, null, 2), 'utf8');

  if (onBeforePrompt) {
    await onBeforePrompt({ artifactPath, triageHash, extension: preExtension });
  }

  let decision = 'ABORT';
  if (promptHuman) {
    decision = await promptHuman({ artifactPath, triageHash, extension: preExtension });
  } else {
    // Default interactive prompt
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question(
      `Triage artifact written to ${artifactPath} (hash: ${triageHash}).\n` +
        `Advisory: tier=${preExtension.recommendation.tier} depth=${preExtension.recommendation.depth}\n` +
        `Gate 1 Decision (APPROVE, EDIT, ABORT)? `,
    );
    rl.close();
    decision = answer.trim().toUpperCase();
    if (!['APPROVE', 'EDIT', 'ABORT'].includes(decision)) {
      decision = 'ABORT';
    }
  }

  // After Gate-1: lock extension when APPROVE (or when pre-locked via headless/lock).
  let extension = preExtension;
  if (decision === 'APPROVE' || triageLock || headless === true) {
    extension = buildResearchPrimeIntakeExtension(inputs || {}, {
      recommendation,
      gate1Decision: decision === 'APPROVE' ? 'APPROVE' : undefined,
      confirmedDepth,
      confirmedTier,
      triageLock,
      headless,
      triageConfig,
      requireLock: headless === true,
    });
    fs.writeFileSync(extensionPath, JSON.stringify(extension, null, 2), 'utf8');
    // Refresh main artifact with locked extension
    fs.writeFileSync(
      artifactPath,
      JSON.stringify({ ...triageData, extension, gate1Decision: decision }, null, 2),
      'utf8',
    );
  }

  // Triage-artifact hashing feeding the canonical governance record (partial record for Gate 1)
  const governanceRecord = {
    triageHash,
    gate1Decision: decision,
    triageExtensionStamp: extension?.stamp || NS01_WAVE5_STAMP,
    triageDepth: extension?.triage?.depth || extension?.recommendation?.depth || null,
    triageTier: extension?.triage?.tier || extension?.recommendation?.tier || null,
  };
  fs.writeFileSync(path.join(runDir, 'gate1-record.json'), JSON.stringify(governanceRecord, null, 2), 'utf8');

  if (decision === 'ABORT') {
    throw new HaltError(`Run halted at Gate 1 with decision ABORT (Artifact: ${triageHash})`);
  }

  return { artifactPath, triageHash, decision, extension, extensionPath };
}

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}

if (invokedDirectly()) {
  const runDir = process.argv[2] || process.cwd();
  // Collect stdin for inputs in a real scenario, but for now just mock it
  const inputs = { note: 'interactive intake' };
  runIntake(inputs, { runDir }).then(res => {
    console.log('Intake complete:', res);
  }).catch(err => {
    if (err instanceof HaltError) {
      console.error(err.message);
      process.exit(1);
    }
    console.error(err);
    process.exit(2);
  });
}
