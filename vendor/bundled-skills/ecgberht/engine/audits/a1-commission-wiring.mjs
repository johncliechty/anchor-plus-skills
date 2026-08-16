/**
 * Wave 3 — A1 commission-half WIRING audit harness.
 *
 * Audits (never re-plans) the BUILT propose/confirm half:
 *   proposeCommission        job-lifecycle.mjs:~141
 *   confirmCommission        job-lifecycle.mjs:~250
 *   verbCommissionPropose    job-lifecycle.mjs:~841
 *   verbCommissionConfirm    job-lifecycle.mjs:~908
 *
 * Produces a checked-in seam table of actual parameters/returns and the
 * wiring seams a host must call. No FAIL-rebuild branch.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  proposeCommission,
  confirmCommission,
  verbCommissionPropose,
  verbCommissionConfirm,
  COMMISSION_PROPOSAL_SCHEMA_ID,
  JOB_SCHEMA_ID,
} from '../job-lifecycle.mjs';
import { appendRoadmapEvent, emptyRoadmap, writeProjectRoadmap } from '../roadmap.mjs';
import { writeFileAtomicSync, writeJsonIdempotentSync } from '../durable-write.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENGINE_ROOT = path.resolve(HERE, '..');
const JOB_LIFECYCLE_REL = 'engine/job-lifecycle.mjs';
const JOB_LIFECYCLE_ABS = path.join(ENGINE_ROOT, 'job-lifecycle.mjs');

/** Expected export → approximate line anchors from the frozen plan. */
export const A1_SEAM_ANCHORS = Object.freeze([
  {
    id: 'proposeCommission',
    export_name: 'proposeCommission',
    plan_line: 141,
    role: 'pure propose (no write)',
  },
  {
    id: 'confirmCommission',
    export_name: 'confirmCommission',
    plan_line: 250,
    role: 'confirm: bind + strip instrument (in-memory)',
  },
  {
    id: 'verbCommissionPropose',
    export_name: 'verbCommissionPropose',
    plan_line: 841,
    role: 'CLI verb wrapper — read-only propose',
  },
  {
    id: 'verbCommissionConfirm',
    export_name: 'verbCommissionConfirm',
    plan_line: 908,
    role: 'CLI verb wrapper — persist roadmap then strip (A4 pair)',
  },
]);

/** Artifact relative path for the checked-in seam table. */
export const A1_SEAM_TABLE_REL = path.join('artifacts', 'a1-seam-table.json');

/**
 * Locate `export function <name>` line number in job-lifecycle.mjs source.
 * @param {string} source
 * @param {string} exportName
 * @returns {number|null} 1-based line
 */
export function findExportLine(source, exportName) {
  const lines = String(source).split(/\r?\n/);
  const re = new RegExp(
    `^export\\s+function\\s+${exportName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\(`,
  );
  for (let i = 0; i < lines.length; i += 1) {
    if (re.test(lines[i])) return i + 1;
  }
  return null;
}

/**
 * Static source wiring audit: exports exist near plan anchors.
 * @param {{ sourcePath?: string }} [opts]
 */
export function auditA1SourceWiring(opts = {}) {
  const sourcePath = opts.sourcePath ?? JOB_LIFECYCLE_ABS;
  const source = fs.readFileSync(sourcePath, 'utf8');
  const seams = A1_SEAM_ANCHORS.map((anchor) => {
    const line = findExportLine(source, anchor.export_name);
    const delta =
      line == null ? null : Math.abs(line - anchor.plan_line);
    return {
      ...anchor,
      file: JOB_LIFECYCLE_REL,
      observed_line: line,
      plan_line: anchor.plan_line,
      line_delta: delta,
      // Plan line anchors are approximate; tolerate modest drift from prior waves.
      wiring_ok: line != null && delta != null && delta <= 40,
      present: line != null,
    };
  });
  return {
    ok: seams.every((s) => s.present && s.wiring_ok),
    file: JOB_LIFECYCLE_REL,
    seams,
  };
}

function makeOpenRoadmap(projectId = 'a1-audit-proj') {
  const created = appendRoadmapEvent(emptyRoadmap(projectId), {
    kind: 'step_create',
    step_id: 'stage-a1',
    name: 'A1 wiring audit stage',
    status: 'planned',
    done_when: 'seams table checked in',
    at: '2026-08-02',
  });
  if (!created.ok) throw new Error(`roadmap fixture failed: ${created.error}`);
  const flipped = appendRoadmapEvent(created.roadmap, {
    kind: 'status_flip',
    step_id: 'stage-a1',
    from: 'planned',
    to: 'active',
    at: '2026-08-02',
    receipt: { who: 'a1-harness', when: '2026-08-02', why: 'open for commission' },
  });
  if (!flipped.ok) throw new Error(`status_flip failed: ${flipped.error}`);
  return flipped.roadmap;
}

function baseStrip() {
  return {
    schema: 'ecgberht-strip-v0',
    project_id: 'a1-audit-proj',
    phase: 'build',
    active_effort: 'A1 wiring audit',
    human_wait: 'none',
    capacity: 'known',
    negative_heartbeat: { no_attention_needed: false, why: null, until: null },
    anti_starvation_age_days: 0,
    grasscatch: [],
    uncertainty_flags: [],
    tool_depth_cell: 'LITE',
    next_recommended: 'audit seams',
    why_next: 'Wave 3 A1',
    as_of: '2026-08-02',
    instruments: [],
    receipts: [],
  };
}

/**
 * Live call-shape audit: free-floating refused, who required, job_id minted,
 * commission_bind appended, strip instrument on confirm.
 * @param {{ prefs?: object, env?: object }} [opts]
 */
export function auditA1CallShapes(opts = {}) {
  const prefs = opts.prefs ?? {
    coding_family: 'claude',
    review_family: 'gemini',
    default_cli: 'claude',
  };
  const roadmap = makeOpenRoadmap();
  const strip = baseStrip();

  const freeFloating = proposeCommission({
    skill: 'researchPrime',
    roadmap,
    prefs,
    env: opts.env,
  });
  const freeFloatingRefused =
    freeFloating.ok === false &&
    (freeFloating.error === 'commission_propose_requires_step' ||
      String(freeFloating.error ?? '').includes('step'));

  const proposal = proposeCommission({
    step_id: 'stage-a1',
    skill: 'researchPrime',
    depth_cell: 'LITE',
    roadmap,
    prefs,
    env: opts.env,
    who: 'ecgberht-steward',
    at: '2026-08-02',
  });

  const whoMissing = confirmCommission({
    proposal: proposal.ok ? proposal : null,
    roadmap,
    strip,
  });
  const whoRequired =
    whoMissing.ok === false &&
    whoMissing.error === 'commission_confirm_requires_who';

  let confirmed = { ok: false };
  if (proposal.ok) {
    confirmed = confirmCommission({
      proposal,
      roadmap,
      strip,
      who: 'john',
      at: '2026-08-02',
      job_id: 'ecgberht-job-a1-audit-001',
    });
  }

  const bindEvent =
    confirmed.ok &&
    Array.isArray(confirmed.roadmap?.roadmap_events) &&
    confirmed.roadmap.roadmap_events.some((e) => e.kind === 'commission_bind');

  const stripInstrument =
    confirmed.ok === true && confirmed.strip_appended === true;

  const verbPropose = verbCommissionPropose({
    step: 'stage-a1',
    skill: 'researchPrime',
    roadmap,
    prefs,
    env: opts.env,
    persist: false,
  });

  const verbConfirm = verbCommissionConfirm({
    step: 'stage-a1',
    skill: 'researchPrime',
    who: 'john',
    roadmap: confirmed.ok ? confirmed.roadmap : roadmap,
    strip: confirmed.ok ? confirmed.strip : strip,
    prefs,
    env: opts.env,
    persist: false,
    dry_run: true,
  });

  const callShapes = {
    free_floating_refused: freeFloatingRefused,
    free_floating_error: freeFloating.error ?? null,
    proposal_ok: proposal.ok === true,
    proposal_schema: proposal.schema ?? null,
    proposal_requires_confirm: proposal.requires_confirm === true,
    proposal_step_id: proposal.step_id ?? null,
    confirm_who_required: whoRequired,
    confirm_ok: confirmed.ok === true,
    job_id_minted: Boolean(confirmed.job?.job_id),
    job_schema: confirmed.job?.schema ?? null,
    commissioned_as: confirmed.commissioned_as ?? null,
    commission_bind_appended: Boolean(bindEvent),
    strip_instrument_appended: stripInstrument,
    verb_propose_ok: verbPropose.ok === true,
    verb_propose_written: verbPropose.written === false || verbPropose.persisted?.roadmap === false,
    verb_confirm_ok: verbConfirm.ok === true,
    verb_confirm_dry_run: verbConfirm.dry_run === true,
  };

  const ok =
    freeFloatingRefused &&
    proposal.ok === true &&
    whoRequired &&
    confirmed.ok === true &&
    bindEvent &&
    stripInstrument &&
    verbPropose.ok === true &&
    verbConfirm.ok === true;

  return {
    ok,
    call_shapes: callShapes,
    host_seams: [
      {
        seam: 'propose',
        call: 'proposeCommission | verbCommissionPropose',
        inputs: ['step_id|step', 'skill', 'roadmap|project', 'depth_cell?', 'who?'],
        outputs: [
          'kind=commission_proposal',
          'requires_confirm=true',
          'confirmed=false',
          'commission (compose contract)',
        ],
        host_must: 'Render proposal; wait for human confirm — never auto-launch.',
      },
      {
        seam: 'confirm',
        call: 'confirmCommission | verbCommissionConfirm',
        inputs: ['proposal | step+skill', 'who (required)', 'roadmap', 'strip?'],
        outputs: [
          `job.schema=${JOB_SCHEMA_ID}`,
          'commission_bind event',
          'strip instrument commission_confirm',
          'commissioned_as',
        ],
        host_must:
          'Pass claimed who; hand confirmed job to executor seam (Wave 4/11/20).',
      },
    ],
    schemas: {
      commission_proposal: COMMISSION_PROPOSAL_SCHEMA_ID,
      job: JOB_SCHEMA_ID,
    },
  };
}

/**
 * Full A1 harness: source + call shapes → seam table.
 * @param {{ root?: string, writeArtifact?: boolean, prefs?: object, env?: object }} [opts]
 */
export function runA1Audit(opts = {}) {
  const source = auditA1SourceWiring();
  const calls = auditA1CallShapes({ prefs: opts.prefs, env: opts.env });
  const table = {
    schema: 'ecgberht-a1-seam-table-v0',
    audit: 'A1',
    title: 'Commission-half wiring seam table',
    recorded_at: new Date().toISOString(),
    source_file: JOB_LIFECYCLE_REL,
    seams: source.seams,
    call_shapes: calls.call_shapes,
    host_seams: calls.host_seams,
    schemas: calls.schemas,
    ok: source.ok && calls.ok,
    rebuild_forbidden: true,
    note: 'Audit only — no FAIL-rebuild of propose/confirm half.',
  };

  let artifact_path = null;
  if (opts.writeArtifact !== false && opts.root) {
    artifact_path = path.join(opts.root, A1_SEAM_TABLE_REL);
    // Idempotent: a semantically-unchanged table leaves the file byte-identical
    // (no timestamp re-stamp, no git delta — journal 0070 thrash fix).
    writeJsonIdempotentSync(artifact_path, table);
  }

  return {
    ok: table.ok,
    table,
    artifact_path,
    source,
    calls,
  };
}

/**
 * Write a project tree for verb path integration (optional).
 * @param {string} projectDir
 * @param {object} roadmap
 * @param {object} strip
 */
export function writeA1ProjectTree(projectDir, roadmap, strip) {
  fs.mkdirSync(projectDir, { recursive: true });
  writeProjectRoadmap(projectDir, roadmap);
  writeFileAtomicSync(
    path.join(projectDir, 'strip.json'),
    `${JSON.stringify(strip, null, 2)}\n`,
  );
  writeFileAtomicSync(
    path.join(projectDir, 'ECGBERHT.md'),
    '# A1 audit fixture\n\n## North star\n\nWire the commission half.\n',
  );
}
