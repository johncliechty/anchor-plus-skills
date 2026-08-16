/**
 * Wave 18 — Chamber UI bridge: the ONE entry Anchor chamber surfaces call
 * (spawned as `node scripts/chamber-ui-bridge.mjs …` by /api/ecgberht/chamber_*
 * handlers). Composes engine/chamber-ui.mjs closed surfaces only.
 *
 * Modes (single JSON line on stdout):
 *   --project <path>                         → full chamber UI assembly
 *   --project <path> --steps                 → steps view only
 *   --project <path> --proposal <json>       → proposal/confirm surface
 *   --project <path> --confirm <json>        → hash-bound confirm
 *   --project <path> --artifact <json>       → artifact view (I52 gated)
 *   --project <path> --resolve-path <rel>    → T-CON-18 contained resolve
 *   --project <path> --correct <json>        → propose artifact correction
 *   --project <path> --confirm-correction <json> → confirm correction
 *   --receipts <json>                        → typed receipt render (dossier)
 *   --poller-audit <source-file>             → audit client poller pattern
 *
 * No host-absolute paths baked in. Stdout purity: one JSON object.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  assembleChamberUi,
  buildStepsView,
  buildProposalConfirmSurface,
  buildArtifactView,
  buildReceiptRenderSurface,
  confirmProposalHashBound,
  proposeArtifactCorrection,
  confirmArtifactCorrection,
  resolveChamberArtifactPath,
  renderCommissionedArtifactCard,
  auditChamberPoller,
  CHAMBER_CODE,
  CHAMBER_TEXT,
  chamberFailureTable,
} from '../engine/chamber-ui.mjs';

/** Parse the closed flag set. */
export function parseChamberUiArgs(argv = []) {
  const out = {
    project: null,
    steps: false,
    proposal: null,
    confirm: null,
    artifact: null,
    resolvePath: null,
    correct: null,
    confirmCorrection: null,
    receipts: null,
    pollerAudit: null,
    failureTable: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--project' && argv[i + 1] != null) out.project = argv[++i];
    else if (t === '--steps') out.steps = true;
    else if (t === '--proposal' && argv[i + 1] != null) out.proposal = argv[++i];
    else if (t === '--confirm' && argv[i + 1] != null) out.confirm = argv[++i];
    else if (t === '--artifact' && argv[i + 1] != null) out.artifact = argv[++i];
    else if (t === '--resolve-path' && argv[i + 1] != null)
      out.resolvePath = argv[++i];
    else if (t === '--correct' && argv[i + 1] != null) out.correct = argv[++i];
    else if (t === '--confirm-correction' && argv[i + 1] != null)
      out.confirmCorrection = argv[++i];
    else if (t === '--receipts' && argv[i + 1] != null) out.receipts = argv[++i];
    else if (t === '--poller-audit' && argv[i + 1] != null)
      out.pollerAudit = argv[++i];
    else if (t === '--failure-table') out.failureTable = true;
  }
  return out;
}

function parseJson(raw, label) {
  try {
    return { ok: true, value: JSON.parse(raw) };
  } catch (e) {
    return {
      ok: false,
      error: 'bridge_bad_json',
      code: CHAMBER_CODE.DEP_GARBAGE,
      message: CHAMBER_TEXT[CHAMBER_CODE.DEP_GARBAGE].replace(
        '<surface>',
        label,
      ),
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Build the bridge payload for the parsed flags.
 * @param {ReturnType<typeof parseChamberUiArgs>} args
 * @param {{ inject?: object }} [opts]
 */
export function buildChamberUiPayload(args, opts = {}) {
  if (args.failureTable) {
    return {
      ok: true,
      mode: 'failure_table',
      table: chamberFailureTable(),
    };
  }

  if (args.pollerAudit) {
    let src;
    try {
      src = fs.readFileSync(args.pollerAudit, 'utf8');
    } catch (e) {
      return {
        ok: false,
        mode: 'poller_audit',
        error: 'poller_source_unreadable',
        code: CHAMBER_CODE.STORE_UNREADABLE,
        message: String(e?.message ?? e),
      };
    }
    const audit = auditChamberPoller(src);
    return { ok: audit.ok, mode: 'poller_audit', audit };
  }

  if (args.resolvePath) {
    if (!args.project) {
      return {
        ok: false,
        mode: 'resolve_path',
        error: 'project required',
        code: CHAMBER_CODE.DEP_MISSING,
      };
    }
    const resolved = resolveChamberArtifactPath(args.project, args.resolvePath);
    return { ...resolved, mode: 'resolve_path' };
  }

  if (args.confirm) {
    const parsed = parseJson(args.confirm, 'Proposal/confirm');
    if (!parsed.ok) return { ...parsed, mode: 'confirm' };
    const result = confirmProposalHashBound(parsed.value);
    return { ...result, mode: 'confirm' };
  }

  if (args.confirmCorrection) {
    const parsed = parseJson(args.confirmCorrection, 'Proposal/confirm');
    if (!parsed.ok) return { ...parsed, mode: 'confirm_correction' };
    const result = confirmArtifactCorrection(parsed.value);
    return { ...result, mode: 'confirm_correction' };
  }

  if (args.correct) {
    const parsed = parseJson(args.correct, 'Proposal/confirm');
    if (!parsed.ok) return { ...parsed, mode: 'correct' };
    const result = proposeArtifactCorrection(parsed.value);
    return { ...result, mode: 'correct' };
  }

  if (args.artifact) {
    const parsed = parseJson(args.artifact, 'Artifact view');
    if (!parsed.ok) return { ...parsed, mode: 'artifact' };
    const art = parsed.value;
    // I52 path: if the payload is a bare scaffold, renderCommissionedArtifactCard
    if (art && (art.scaffold_only || art.kind === 'scaffold_proposal')) {
      const card = renderCommissionedArtifactCard(art);
      return { ...card, mode: 'artifact' };
    }
    const view = buildArtifactView({
      project_path: args.project ?? art.project_path,
      artifact: art.artifact ?? art,
      rel: art.rel,
      failure: art.failure,
    });
    return { ...view, mode: 'artifact' };
  }

  if (args.proposal) {
    const parsed = parseJson(args.proposal, 'Proposal/confirm');
    if (!parsed.ok) return { ...parsed, mode: 'proposal' };
    const view = buildProposalConfirmSurface({
      proposal: parsed.value.proposal ?? parsed.value,
      failure: parsed.value.failure,
      last_good: parsed.value.last_good,
      last_good_age_ms: parsed.value.last_good_age_ms,
    });
    return { ...view, mode: 'proposal' };
  }

  if (args.receipts) {
    const parsed = parseJson(args.receipts, 'Receipt render');
    if (!parsed.ok) return { ...parsed, mode: 'receipts' };
    const view = buildReceiptRenderSurface(parsed.value);
    return { ...view, mode: 'receipts' };
  }

  if (args.steps) {
    if (!args.project && !opts.inject) {
      return {
        ok: false,
        mode: 'steps',
        error: 'project required',
        code: CHAMBER_CODE.DEP_MISSING,
        message: CHAMBER_TEXT[CHAMBER_CODE.DEP_MISSING].replace(
          '<surface>',
          'Steps view',
        ),
      };
    }
    const view = buildStepsView({
      project_path: args.project,
      inject: opts.inject,
    });
    return { ...view, mode: 'steps' };
  }

  // Default: full assembly
  if (!args.project && !opts.inject) {
    return {
      ok: false,
      mode: 'chamber_ui',
      error: 'project required',
      code: CHAMBER_CODE.DEP_MISSING,
      message: CHAMBER_TEXT[CHAMBER_CODE.DEP_MISSING].replace(
        '<surface>',
        'Chamber UI',
      ),
    };
  }

  const assembled = assembleChamberUi({
    project_path: args.project,
    inject: opts.inject,
    proposal: opts.inject?.proposal,
    artifact: opts.inject?.artifact,
    dossier: opts.inject?.dossier,
    ledgerView: opts.inject?.ledgerView,
  });
  return { ...assembled, mode: 'chamber_ui' };
}

/**
 * CLI entry — when run as main.
 * @param {string[]} argv
 */
export function runChamberUiBridge(argv = process.argv.slice(2)) {
  const args = parseChamberUiArgs(argv);
  const payload = buildChamberUiPayload(args);
  process.stdout.write(JSON.stringify(payload) + '\n');
  return payload;
}

// Main only when executed directly (not when imported by tests).
const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) ===
    path.resolve(fileURLToPath(import.meta.url));

if (isMain) {
  try {
    runChamberUiBridge();
  } catch (e) {
    process.stdout.write(
      JSON.stringify({
        ok: false,
        error: 'bridge_exception',
        code: CHAMBER_CODE.STATE_UNKNOWN,
        message: String(e?.message ?? e),
      }) + '\n',
    );
    process.exitCode = 1;
  }
}
