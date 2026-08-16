/**
 * Wave 3 — A4 non-atomic confirm-pair defect harness.
 *
 * verbCommissionConfirm persists writeProjectRoadmap then writeFileAtomicSync
 * (strip) as two separate durable writes (job-lifecycle.mjs:929–944). A crash
 * between them leaves a commission bound in the roadmap with no Strip receipt.
 *
 * This harness:
 *   1. cites file:line evidence from source,
 *   2. demonstrates the orphaned bind via a kill-between-writes probe,
 *   3. records a defect row pointing at Wave 7 (confirm journal).
 *
 * Does NOT fix the defect (Wave 7 owns the confirm journal).
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  proposeCommission,
  confirmCommission,
} from '../job-lifecycle.mjs';
import {
  appendRoadmapEvent,
  emptyRoadmap,
  writeProjectRoadmap,
  loadProjectRoadmap,
} from '../roadmap.mjs';
import { writeFileAtomicSync, writeJsonIdempotentSync } from '../durable-write.mjs';
import { STRIP_FILE_NAME, loadProjectSurfaces } from '../face-strip.mjs';
import { appendFixItem, FIX_ITEM_KIND } from './fix-item-ledger.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENGINE_ROOT = path.resolve(HERE, '..');
const JOB_LIFECYCLE_REL = 'engine/job-lifecycle.mjs';
const JOB_LIFECYCLE_ABS = path.join(ENGINE_ROOT, 'job-lifecycle.mjs');

/** Plan-cited kill window. */
export const A4_PLAN_WINDOW = Object.freeze({
  file: JOB_LIFECYCLE_REL,
  start_line: 929,
  end_line: 944,
  first_write: 'writeProjectRoadmap',
  second_write: 'writeFileAtomicSync(strip)',
});

/** Defect owns Wave 7 confirm journal. */
export const A4_FIX_WAVE = 7;

/** Artifact path for the defect row. */
export const A4_DEFECT_REL = path.join('artifacts', 'a4-confirm-pair-defect.json');

/**
 * Extract the non-atomic pair region from source with line evidence.
 * @param {{ sourcePath?: string }} [opts]
 */
export function extractA4SourceEvidence(opts = {}) {
  const sourcePath = opts.sourcePath ?? JOB_LIFECYCLE_ABS;
  const source = fs.readFileSync(sourcePath, 'utf8');
  const lines = source.split(/\r?\n/);

  // Find writeProjectRoadmap + writeFileAtomicSync in verbCommissionConfirm body.
  // Wave 7: the production apply pair also lives in commission-dossier.mjs
  // applyConfirmIntent (confirm journal) — scan both sources.
  let confirmStart = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (/^export\s+function\s+verbCommissionConfirm\s*\(/.test(lines[i])) {
      confirmStart = i;
      break;
    }
  }

  let roadmapWriteLine = null;
  let stripWriteLine = null;
  if (confirmStart >= 0) {
    for (let i = confirmStart; i < lines.length; i += 1) {
      // stop at next top-level export
      if (i > confirmStart && /^export\s+function\s+/.test(lines[i])) break;
      // Wave 6: first write may be spine / appendRoadmapEventDurable rather than
      // bare writeProjectRoadmap — still a separate durable write from strip.
      if (
        roadmapWriteLine == null &&
        (/writeProjectRoadmap\s*\(/.test(lines[i]) ||
          /appendRoadmapEventDurable\s*\(/.test(lines[i]) ||
          /appendRoadmapEventThroughSpine\s*\(/.test(lines[i]) ||
          /writeRoadmapThroughSpine\s*\(/.test(lines[i]))
      ) {
        roadmapWriteLine = i + 1;
      }
      if (
        stripWriteLine == null &&
        roadmapWriteLine != null &&
        (/writeFileAtomicSync\s*\(/.test(lines[i]) ||
          /writeStripThroughSpine\s*\(/.test(lines[i]) ||
          /appendStripInstrumentDurable\s*\(/.test(lines[i]))
      ) {
        stripWriteLine = i + 1;
      }
    }
  }

  // Wave 7 confirm journal apply pair (A4 fix lives here; dual writes remain
  // two durable ops, recovered by repairConfirmJournal).
  if (roadmapWriteLine == null || stripWriteLine == null) {
    const dossierPath = path.join(ENGINE_ROOT, 'commission-dossier.mjs');
    if (fs.existsSync(dossierPath)) {
      const dLines = fs.readFileSync(dossierPath, 'utf8').split(/\r?\n/);
      let applyStart = -1;
      for (let i = 0; i < dLines.length; i += 1) {
        if (/^export\s+function\s+applyConfirmIntent\s*\(/.test(dLines[i])) {
          applyStart = i;
          break;
        }
      }
      if (applyStart >= 0) {
        for (let i = applyStart; i < dLines.length; i += 1) {
          if (i > applyStart && /^export\s+function\s+/.test(dLines[i])) break;
          if (
            roadmapWriteLine == null &&
            /appendRoadmapEventThroughSpine\s*\(/.test(dLines[i])
          ) {
            roadmapWriteLine = i + 1;
          }
          if (
            stripWriteLine == null &&
            roadmapWriteLine != null &&
            /writeStripThroughSpine\s*\(/.test(dLines[i])
          ) {
            stripWriteLine = i + 1;
          }
        }
      }
    }
  }

  const region = lines
    .slice(
      Math.max(0, (roadmapWriteLine ?? A4_PLAN_WINDOW.start_line) - 3),
      Math.min(lines.length, (stripWriteLine ?? A4_PLAN_WINDOW.end_line) + 2),
    )
    .map((text, idx) => {
      const line =
        Math.max(0, (roadmapWriteLine ?? A4_PLAN_WINDOW.start_line) - 3) + idx + 1;
      return { line, text };
    });

  const nonAtomic =
    roadmapWriteLine != null &&
    stripWriteLine != null &&
    stripWriteLine > roadmapWriteLine;

  return {
    ok: nonAtomic,
    file: JOB_LIFECYCLE_REL,
    verb: 'verbCommissionConfirm',
    writeProjectRoadmap_line: roadmapWriteLine,
    writeFileAtomicSync_strip_line: stripWriteLine,
    plan_window: A4_PLAN_WINDOW,
    region,
    defect:
      'Two separate durable writes: roadmap bind can land without Strip instrument '
      + 'if the process dies between them.',
    fix: {
      wave: A4_FIX_WAVE,
      mechanism: 'confirm journal (two-phase apply + boot repair)',
      test_id: 'T-ATOM-CONFIRM',
    },
  };
}

function makeOpenRoadmap(projectId) {
  const created = appendRoadmapEvent(emptyRoadmap(projectId), {
    kind: 'step_create',
    step_id: 'stage-a4',
    name: 'A4 kill-between probe',
    status: 'planned',
    done_when: 'orphan bind demonstrated',
    at: '2026-08-02',
  });
  const flipped = appendRoadmapEvent(created.roadmap, {
    kind: 'status_flip',
    step_id: 'stage-a4',
    from: 'planned',
    to: 'active',
    at: '2026-08-02',
    receipt: { who: 'a4-harness', when: '2026-08-02', why: 'open' },
  });
  return flipped.roadmap;
}

function baseStrip(projectId) {
  return {
    schema: 'ecgberht-strip-v0',
    project_id: projectId,
    phase: 'build',
    active_effort: 'A4 non-atomic pair',
    human_wait: 'none',
    capacity: 'known',
    negative_heartbeat: { no_attention_needed: false, why: null, until: null },
    anti_starvation_age_days: 0,
    grasscatch: [],
    uncertainty_flags: [],
    tool_depth_cell: 'LITE',
    next_recommended: 'demonstrate kill-between',
    why_next: 'Wave 3 A4',
    as_of: '2026-08-02',
    instruments: [],
    receipts: [],
  };
}

/**
 * Kill-between-writes probe: write roadmap only, skip strip — restart observes orphan.
 * @param {{ projectDir: string, prefs?: object, env?: object }} opts
 */
export function probeA4KillBetweenWrites(opts) {
  const projectDir = opts.projectDir;
  const projectId = 'a4-kill-probe';
  const prefs = opts.prefs ?? {
    coding_family: 'claude',
    review_family: 'gemini',
    default_cli: 'claude',
  };

  fs.mkdirSync(projectDir, { recursive: true });
  const roadmap0 = makeOpenRoadmap(projectId);
  const strip0 = baseStrip(projectId);
  writeProjectRoadmap(projectDir, roadmap0);
  writeFileAtomicSync(
    path.join(projectDir, STRIP_FILE_NAME),
    `${JSON.stringify(strip0, null, 2)}\n`,
  );

  const proposal = proposeCommission({
    step_id: 'stage-a4',
    skill: 'researchPrime',
    depth_cell: 'LITE',
    roadmap: roadmap0,
    prefs,
    env: opts.env,
    who: 'ecgberht-steward',
    project_cwd: projectDir,
    at: '2026-08-02',
  });
  if (!proposal.ok) {
    return { ok: false, error: 'propose_failed', proposal };
  }

  const confirmed = confirmCommission({
    proposal,
    roadmap: roadmap0,
    strip: strip0,
    who: 'john',
    at: '2026-08-02',
    job_id: 'ecgberht-job-a4-orphan-001',
  });
  if (!confirmed.ok) {
    return { ok: false, error: 'confirm_failed', confirmed };
  }

  // --- KILL WINDOW SIMULATION ---
  // Mirror verbCommissionConfirm's first write only (roadmap), then "die"
  // before the strip writeFileAtomicSync. This is the A4 defect demonstration.
  writeProjectRoadmap(projectDir, confirmed.roadmap);
  // intentionally NO strip write

  // --- RESTART OBSERVATION ---
  const loadedRoadmap = loadProjectRoadmap(projectDir);
  const surfaces = loadProjectSurfaces(projectDir);
  const events = loadedRoadmap.roadmap?.roadmap_events ?? [];
  const bind = events.find((e) => e.kind === 'commission_bind');
  const stripInstruments = surfaces?.strip?.instruments ?? [];
  const stripHasConfirm = stripInstruments.some(
    (i) =>
      i?.kind === 'commission_confirm' ||
      i?.job_id === confirmed.job?.job_id,
  );

  const orphaned =
    Boolean(bind) &&
    !stripHasConfirm &&
    (surfaces?.strip?.instruments?.length ?? 0) ===
      (strip0.instruments?.length ?? 0);

  return {
    ok: orphaned,
    phase: 'restart_observation',
    evidence: {
      roadmap_written: true,
      strip_written: false,
      commission_bind_present: Boolean(bind),
      commissioned_as: bind?.commissioned_as ?? confirmed.commissioned_as ?? null,
      job_id: confirmed.job?.job_id ?? null,
      strip_confirm_instrument_present: stripHasConfirm,
      orphaned_bind: orphaned,
    },
    file_line: {
      first_write: `${JOB_LIFECYCLE_REL}:writeProjectRoadmap`,
      second_write: `${JOB_LIFECYCLE_REL}:writeFileAtomicSync(strip)`,
      plan_window: `${JOB_LIFECYCLE_REL}:${A4_PLAN_WINDOW.start_line}-${A4_PLAN_WINDOW.end_line}`,
    },
    fix_wave: A4_FIX_WAVE,
  };
}

/**
 * Full A4 harness: source evidence + kill probe + defect row (+ optional ledger).
 * @param {{
 *   root?: string,
 *   projectDir: string,
 *   writeArtifact?: boolean,
 *   appendLedger?: boolean,
 *   prefs?: object,
 *   env?: object,
 * }} opts
 */
export function runA4Audit(opts) {
  const source = extractA4SourceEvidence();
  const probe = probeA4KillBetweenWrites({
    projectDir: opts.projectDir,
    prefs: opts.prefs,
    env: opts.env,
  });

  const defect = {
    schema: 'ecgberht-a4-defect-v0',
    audit: 'A4',
    id: 'A4-non-atomic-confirm-pair',
    title: 'Non-atomic confirm pair (roadmap then strip)',
    recorded_at: new Date().toISOString(),
    kind: FIX_ITEM_KIND.DEFECT,
    counts_against_cap: false,
    reason:
      'Pre-known defect; fix is Wave 7 confirm journal — not a residual A5/A4 cap item.',
    source_evidence: {
      file: source.file,
      writeProjectRoadmap_line: source.writeProjectRoadmap_line,
      writeFileAtomicSync_strip_line: source.writeFileAtomicSync_strip_line,
      plan_window: source.plan_window,
      region: source.region,
    },
    kill_between_probe: probe,
    owning_wave: A4_FIX_WAVE,
    fix_mechanism: 'confirm journal (confirm_intent → apply → confirm_applied + repairConfirmJournal)',
    test_id_when_fixed: 'T-ATOM-CONFIRM',
    ok: source.ok && probe.ok,
  };

  let artifact_path = null;
  if (opts.writeArtifact !== false && opts.root) {
    artifact_path = path.join(opts.root, A4_DEFECT_REL);
    // Idempotent: unchanged defect record leaves the file byte-identical (0070 fix).
    writeJsonIdempotentSync(artifact_path, defect);
  }

  let ledger = null;
  if (opts.appendLedger && opts.root) {
    ledger = appendFixItem(
      {
        id: defect.id,
        kind: FIX_ITEM_KIND.DEFECT,
        counts_against_cap: false,
        title: defect.title,
        audit: 'A4',
        owning_wave: A4_FIX_WAVE,
        evidence: `${JOB_LIFECYCLE_REL}:${source.writeProjectRoadmap_line}-${source.writeFileAtomicSync_strip_line}`,
      },
      { root: opts.root },
    );
  }

  return {
    ok: defect.ok,
    defect,
    artifact_path,
    source,
    probe,
    ledger,
  };
}
