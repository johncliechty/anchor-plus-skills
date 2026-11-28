#!/usr/bin/env node
// crucible.mjs — Unified Crucible CLI Entrypoint.
// Routes `--lite` / `--depth LITE` to `runLiteFastPath` (<=4 model calls),
// `--matrix-fast-track` / `--depth MATRIX-FAST-TRACK` to `runMatrixFastTrack` (6-9 model calls),
// and `--depth FULL` / `--depth SPIKE-FIRST` to the multi-round Stage 0 -> 1 -> 2 pipeline,
// or auto-triages via Stage-0 `assessComplexity` when no explicit depth flag is passed.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HaltError } from './crucible-lib.mjs';
import { assessComplexity, runStage0 } from './stage0.mjs';
import { runStage1 } from './stage1.mjs';
import { runStage2 } from './stage2.mjs';
import { runLiteFastPath, runMatrixFastTrack, writeCrucibleRunRecord } from './matrix-fast-track.mjs';
import { normalizeBandDepth } from './band-profile.mjs';

export function resolveCliDepthFlag(argv = []) {
  if (argv.includes('--matrix-fast-track')) return 'MATRIX-FAST-TRACK';
  if (argv.includes('--lite')) return 'LITE';
  const idx = argv.indexOf('--depth');
  if (idx >= 0 && idx + 1 < argv.length) {
    return normalizeBandDepth(argv[idx + 1]);
  }
  return null;
}

export async function runCrucible({
  agent,
  intent,
  northStar = null,
  repoDir = null,
  outputDir,
  depth = null,
  approved = false,
  pauseAtStage0Lock = false,
  recordRun = false,
  runsDir = null,
  spikeProbe = null,
  superjump = false,
  families = {},
  log = () => {},
} = {}) {
  const started = new Date().toISOString();
  const t0 = Date.now();
  const explicitDepth = depth ? normalizeBandDepth(depth) : null;
  const triage = explicitDepth
    ? { depth: explicitDepth, nsDepth: explicitDepth, nsTier: explicitDepth === 'LITE' ? 'Standard' : 'Heavy' }
    : assessComplexity({ intent, repoDir });
  const resolvedDepth = normalizeBandDepth(explicitDepth || triage.nsDepth || triage.depth);

  if (resolvedDepth === 'LITE') {
    const res = await runLiteFastPath({
      agent,
      task: intent,
      repoDir,
      outDir: outputDir,
      families,
      tier: String(triage.nsTier || 'standard').toLowerCase(),
      log,
    });
    if (recordRun || runsDir || process.env.CRUCIBLE_RUNS_DIR) {
      writeCrucibleRunRecord({
        band: 'LITE',
        tier: triage.nsTier || 'Standard',
        started,
        input: intent,
        params: { depth: 'LITE', calls: res.calls, max_calls: res.maxModelCalls },
        output: res.files ? [res.files.plan, res.files.description, res.files.execution_log, res.files.config, res.files.review] : [],
        result: `LITE_OK calls=${res.calls}`,
        cross_model: res.cross_model === true,
        family_attested: Boolean(res.provenance?.review?.family_attested),
        models: res.provenance ? [res.provenance.draft, res.provenance.review, res.provenance.revise].filter(Boolean) : [],
        duration_s: Math.max(0, Math.round((Date.now() - t0) / 1000)),
      }, { runsDir });
    }
    return res;
  }

  if (resolvedDepth === 'MATRIX-FAST-TRACK') {
    return runMatrixFastTrack({
      agent,
      intent,
      northStar,
      repoDir,
      outputDir,
      superjump,
      approved,
      pauseAtStage0Lock,
      recordRun,
      runsDir,
      tier: triage.nsTier || 'Heavy',
      log,
    });
  }

  // FULL or SPIKE-FIRST
  const s0 = await runStage0({
    intent,
    input: repoDir ? { repoDir } : {},
    agent,
    salvageAnswer: repoDir ? 'salvage' : null,
    approved,
    log,
  });
  const s1 = await runStage1({
    agent,
    northStar: s0.lock.northStar,
    criteria: s0.lock.criteria,
    depth: resolvedDepth,
    spikeProbe,
    approved,
    log,
  });
  const s2 = await runStage2({
    agent,
    northStar: s0.lock.northStar,
    masterPlan: s1.approval.masterPlan,
    criteria: s0.lock.criteria,
    outputDir,
    depth: resolvedDepth,
    tier: triage.nsTier || 'Heavy',
    triageLock: s0.triage?.lock || null,
    approved,
    log,
  });
  if (recordRun || runsDir || process.env.CRUCIBLE_RUNS_DIR) {
    writeCrucibleRunRecord({
      band: resolvedDepth,
      tier: triage.nsTier || 'Heavy',
      started,
      input: intent,
      params: { depth: resolvedDepth, approved },
      output: s2?.docTrio ? [s2.docTrio.files.plan, s2.docTrio.files.description, s2.docTrio.files.execution_log] : [],
      result: `CRUCIBLE_${resolvedDepth}_OK`,
      cross_model: Boolean(s1?.cross_model || s2?.cross_model),
      family_attested: Boolean(s1?.cross_model || s2?.cross_model),
      models: [],
      duration_s: Math.max(0, Math.round((Date.now() - t0) / 1000)),
    }, { runsDir });
  }
  return { band: resolvedDepth, stage0: s0, stage1: s1, stage2: s2 };
}

function isMain() {
  try {
    if (!process.argv[1]) return false;
    return fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(path.resolve(process.argv[1]));
  } catch {
    return false;
  }
}

if (isMain()) {
  const argv = process.argv.slice(2);
  const flag = (n) => {
    const i = argv.indexOf(n);
    return i >= 0 && i + 1 < argv.length ? argv[i + 1] : null;
  };
  const outputDir = flag('--out') || flag('--output') || argv.find((a) => !a.startsWith('--'));
  const intent = flag('--intent') || flag('--task');
  const repoDir = flag('--repo') || flag('--project');
  const depth = resolveCliDepthFlag(argv);
  const approved = argv.includes('--approve') || argv.includes('--approved');

  if (!outputDir || !intent) {
    process.stderr.write(
      'usage: node crucible/bin/crucible.mjs <outDir> --intent "<goal>" [--repo <dir>] [--matrix-fast-track|--lite|--depth <LITE|MATRIX-FAST-TRACK|SPIKE-FIRST|FULL>] [--approve]\n',
    );
    process.exit(2);
  }

  const { buildLiveCrucibleAgent } = await import('./enhanced.mjs');
  const built = await buildLiveCrucibleAgent({
    env: process.env,
    target: repoDir || process.cwd(),
    log: (s) => console.log(s),
  });

  try {
    const out = await runCrucible({
      agent: built.agent,
      intent,
      northStar: flag('--north-star'),
      repoDir,
      outputDir,
      depth,
      approved,
      pauseAtStage0Lock: argv.includes('--lock-north-star-first'),
      recordRun: true,
      spikeProbe: flag('--spike-probe'),
      superjump: argv.includes('--superjump'),
      families: built.families,
      log: (s) => console.log(s),
    });
    console.log(`CRUCIBLE_OK band=${out.band}`);
    process.exit(0);
  } catch (e) {
    if (e instanceof HaltError || e?.halt_for_human) {
      if (!e?.candidatePlanPath) {
        writeCrucibleRunRecord({
          band: depth || 'AUTO',
          tier: 'heavy',
          input: intent,
          params: { approved },
          result: `GATE: ${e.pending_action || e.message || 'halt'}`,
          cross_model: e?.cross_model === true || e?.slim?.provenance?.cross_model === true,
          family_attested: Boolean(e?.provenance?.family_attested || e?.slim?.provenance?.review?.family_attested),
          models: e?.provenance?.models || [],
        });
      }
      console.log(`GATE ${e.message}`);
      process.exit(3);
    }
    console.error(`crucible failed: ${e?.message || e}`);
    process.exit(2);
  }
}
