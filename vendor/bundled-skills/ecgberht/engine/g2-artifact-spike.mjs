/**
 * Wave 5 — G2 artifact-rendering spike.
 *
 * Real converged Crucible doc-trio through packet-view.mjs
 * classifyArtifact / buildArtifactCard. Verbatim verdict.
 * FAIL routes a plan-shaped renderer into Wave 18 AS A RECORDED SCOPE
 * ADDITION, not a silent mutation.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { classifyArtifact, buildArtifactCard } from './packet-view.mjs';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

export const G2_SPIKE_SCHEMA = 'ecgberht-g2-artifact-spike-v0';
export const G2_VERDICT_REL = path.join(
  'artifacts',
  'g2-artifact-spike-verdict.json',
);

/**
 * Default doc-trio: the locked steward-handoff Crucible-shaped trio
 * (relative paths only — never host-absolute).
 */
export const DEFAULT_DOC_TRIO = Object.freeze([
  {
    role: 'description',
    path: 'planning/steward-handoff-v3/DESCRIPTION.md',
    title: 'Description',
  },
  {
    role: 'implementation_plan',
    path: 'planning/steward-handoff-v3/IMPLEMENTATION-PLAN.md',
    title: 'Implementation Plan',
  },
  {
    role: 'execution_log',
    path: 'planning/steward-handoff-v3/EXECUTION-LOG.md',
    title: 'Execution Log',
  },
]);

/**
 * Plan-shaped paths are out of packet-view MVP scope. Generic open_in_viewer
 * is not a plan-shaped renderer — G2 must FAIL and record Wave-18 scope.
 *
 * Plan-shaped = Implementation-Plan-like deliverables the chamber must walk
 * as a plan (not only the literal `.plan` extension): `.plan`, plan-named
 * paths that are not plain markdown doc-trio members already covered by MVP.
 * Doc-trio `.md` members PASS via open_in_viewer; dedicated plan-shaped
 * renderer scope is recorded on FAIL for Wave 18.
 *
 * @param {string|null|undefined} refPath
 * @returns {boolean}
 */
export function isPlanShapedPath(refPath) {
  if (typeof refPath !== 'string' || !refPath.trim()) return false;
  const parts = refPath.trim().toLowerCase().split(/[\\/]/);
  const base = parts.pop() || '';
  // Explicit plan extension always plan-shaped (MVP has no plan renderer).
  if (base.endsWith('.plan')) return true;
  // Bare plan filenames without markdown/html (e.g. APPROVED.PLAN) — plan-shaped.
  if (base === 'plan' || base.endsWith('.plan.json')) return true;
  return false;
}

/**
 * Classify + card one artifact path. Pure over path strings.
 * @param {{ path: string, title?: string, role?: string }} artifact
 */
export function renderDocTrioMember(artifact) {
  const classified = classifyArtifact(artifact.path);
  const card = buildArtifactCard({
    path: artifact.path,
    title: artifact.title ?? artifact.path,
    note: artifact.role ?? null,
    provenance: [{ source: artifact.path, field: artifact.role ?? null }],
  });
  const barePathOnly = card.bare_path_only === true;
  const hasOpenAction =
    Array.isArray(card.actions) &&
    card.actions.some(
      (a) => a.act === 'open_full' || a.opens || a.mode === 'walk_through',
    );
  // MVP classify/build treats unknown extensions as open_in_viewer — that is
  // NOT a plan-shaped renderer. Plan-shaped paths fail the spike on purpose.
  // Doc-trio markdown PASS is intentional: open_in_viewer is adequate for .md;
  // the Wave-18 addition is only for true plan-shaped artifacts.
  const planShaped = isPlanShapedPath(artifact.path);
  const mvpDocRender =
    classified.kind === 'text' ||
    classified.kind === 'html' ||
    classified.kind === 'image';
  const ok =
    !planShaped &&
    classified.kind !== 'none' &&
    classified.render != null &&
    !barePathOnly &&
    mvpDocRender &&
    (card.unknown !== true ? hasOpenAction : true);

  return {
    role: artifact.role ?? null,
    path: artifact.path,
    classified,
    card: {
      unknown: card.unknown === true,
      bare_path_only: barePathOnly,
      render: card.render ?? null,
      actions_count: (card.actions || []).length,
      has_open_action: hasOpenAction,
    },
    plan_shaped: planShaped,
    mvp_doc_render: mvpDocRender,
    ok,
  };
}

/**
 * Run the G2 spike over a doc-trio.
 *
 * @param {{
 *   trio?: { path: string, title?: string, role?: string }[],
 *   root?: string,
 *   requireExists?: boolean,
 * }} [opts]
 * @returns {{
 *   schema: string,
 *   verdict: 'PASS'|'FAIL',
 *   members: object[],
 *   fail_reasons: string[],
 *   wave18_scope_addition: object|null,
 * }}
 */
export function runG2ArtifactSpike(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const trio = opts.trio ?? DEFAULT_DOC_TRIO;
  const requireExists = opts.requireExists !== false;
  const members = [];
  const fail_reasons = [];

  for (const member of trio) {
    if (requireExists) {
      const abs = path.isAbsolute(member.path)
        ? member.path
        : path.join(root, member.path);
      if (!fs.existsSync(abs)) {
        fail_reasons.push(`missing:${member.path}`);
        members.push({
          role: member.role ?? null,
          path: member.path,
          ok: false,
          missing: true,
        });
        continue;
      }
    }
    // Spike always feeds RELATIVE paths into classify/build (no host absolutes)
    const relPath = path.isAbsolute(member.path)
      ? path.basename(member.path)
      : member.path.split(path.sep).join('/');
    const rendered = renderDocTrioMember({
      ...member,
      path: relPath,
    });
    members.push(rendered);
    if (rendered.plan_shaped) {
      fail_reasons.push(`plan_shaped_needs_wave18_renderer:${relPath}`);
    }
    if (!rendered.ok) {
      fail_reasons.push(`render_fail:${relPath}`);
    }
    if (rendered.card?.bare_path_only) {
      fail_reasons.push(`bare_path_only:${relPath}`);
    }
  }

  const allOk =
    members.length >= 3 &&
    members.every((m) => m.ok) &&
    fail_reasons.length === 0;
  const verdict = allOk ? 'PASS' : 'FAIL';

  // FAIL → recorded Wave-18 scope addition (never a silent plan mutation)
  const wave18_scope_addition =
    verdict === 'FAIL'
      ? {
          wave: 18,
          kind: 'plan-shaped-renderer',
          reason:
            'G2 artifact-rendering spike FAILED — Wave 18 must ship a plan-shaped renderer for Crucible doc-trio artifacts beyond packet-view MVP classifyArtifact/buildArtifactCard',
          recorded: true,
          silent_mutation: false,
          source_spike: 'G2',
        }
      : null;

  return {
    schema: G2_SPIKE_SCHEMA,
    verdict,
    members,
    fail_reasons,
    wave18_scope_addition,
    trio_source: 'planning/steward-handoff-v3 doc-trio',
    renderer: 'packet-view.mjs classifyArtifact/buildArtifactCard',
  };
}

/**
 * @param {string} [root]
 */
export function g2VerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, G2_VERDICT_REL);
}

/**
 * Write the G2 spike verdict artifact.
 * @param {object} [verdict]
 * @param {{ root?: string }} [opts]
 */
export function writeG2SpikeVerdict(verdict, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const body = verdict ?? runG2ArtifactSpike({ root });
  const outPath = g2VerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const payload = {
    ...body,
    written_by: 'g2-artifact-spike.mjs',
  };
  withFileLock(outPath, () => {
    writeFileAtomicSync(outPath, `${JSON.stringify(payload, null, 2)}\n`);
  });
  return outPath;
}
