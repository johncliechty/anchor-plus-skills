/**
 * Wave 14 — Handback validation, DETERMINISTIC reflection + next-stage
 * proposal (gate decision 4), multi-skill proof.
 *
 * On a validated durable handback file the steward IMMEDIATELY emits:
 *   - emitReflectionReceipt(dossier, ledgerView)     — zero-model, zero-spend
 *   - proposeNextStageDeterministic(dossier, ledgerView) — zero-model, zero-spend
 * both pure renders over the dossier + ledger (assembleBriefPacket / narration-floor
 * pattern). The richer model-authored NL-polish reflection compile is the ONLY
 * path that queues without a live envelope and fires at next session open.
 *
 * Ingestion is EXECUTOR-AGNOSTIC: a contract-conformant handback pair (Wave 4
 * skill-owned durable files) ingests identically whichever executor produced it.
 * Never stdout-tethered.
 *
 * Stdlib only. No host-absolute paths in shipped strings.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  readIngestableHandback,
  isIngestable,
  writeHandbackPair,
  handbackJsonPath,
  terminalMarkerPath,
  CONTRACT_VERSION,
  IDEMPOTENCE_KEY,
} from './handback-contract.mjs';
import { validateReceipt, buildHandbackReceipt } from './receipt-validate.mjs';
import {
  appendRoadmapEventThroughSpine,
  findEventByClientId,
  ROADMAP_EVENT_KINDS_VERSION,
  assertEventKindAllowed,
} from './ledger-spine.mjs';
import {
  emptyRoadmap,
  loadProjectRoadmap,
  buildRoadmapProjection,
} from './roadmap.mjs';
import {
  resolveNoLiveEnvelopePath,
  queueNlPolishReflectionCompile,
  readEnvelopeState,
  ZERO_SPEND_NEVER_QUEUE_KINDS,
  QUEUE_WITHOUT_ENVELOPE_KIND,
} from './session-envelope.mjs';
import {
  loadSkillsTable,
  selectCommissionableSkill,
} from './commission-proposal.mjs';
import {
  SC6_MIN_COMMISSIONABLE,
  commissionableSkillsPath,
} from './commissionable-skills.mjs';
import { recordHandbackOnDossier, emptyDossier } from './commission-dossier.mjs';
import { publishAttention } from './attention.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

// ── Schemas / constants ────────────────────────────────────────────────────

export const REFLECTION_RECEIPT_SCHEMA = 'ecgberht-reflection-receipt-v0';
export const NEXT_STAGE_PROPOSAL_SCHEMA = 'ecgberht-next-stage-proposal-v0';
export const HANDBACK_INGEST_SCHEMA = 'ecgberht-handback-ingest-v0';
export const MULTI_SKILL_PROOF_SCHEMA = 'ecgberht-multi-skill-proof-v0';

/** Wave-14 event kinds admitted on allow-list v4. */
export const W14_EVENT_KINDS = Object.freeze([
  'reflection_receipt',
  'next_stage_proposal',
]);

/** Named quarantine store relative path (S7). */
export const QUARANTINE_REL = path.join('.ecgberht', 'handback-quarantine');

/** Ingest registry (idempotence keys already adopted). */
export const INGEST_REGISTRY_REL = path.join(
  '.ecgberht',
  'handback-ingest-registry.json',
);

/** Durable helpers named for T-DUR-S7 removal-proof. */
export const QUARANTINE_ATOMIC_WRITE = 'writeFileAtomicSync';
export const QUARANTINE_LOCK_HELPER = 'withFileLock';

/**
 * Default Oranges prompts attached when the stage scaffolding carries none
 * (narration-floor; deterministic, not model output).
 */
export const DEFAULT_ORANGES_PROMPTS = Object.freeze([
  'What would John ask next about this stage?',
  'What artifact must exist before the stage can close?',
  'What decision, if any, requires a human gate?',
]);

// ── Failure-state table (handback surface — Master-Plan P8) ────────────────

export const HANDBACK_CODE = Object.freeze({
  HANDBACK_NO_BUNDLE: 'HANDBACK_NO_BUNDLE',
  HANDBACK_NEVER_ARRIVED: 'HANDBACK_NEVER_ARRIVED',
  HANDBACK_REFUSED_REPAIRABLE: 'HANDBACK_REFUSED_REPAIRABLE',
  HANDBACK_DUPLICATE_IGNORED: 'HANDBACK_DUPLICATE_IGNORED',
  QUARANTINE_UNREADABLE: 'QUARANTINE_UNREADABLE',
  HANDBACK_HONEST_EMPTY: 'HANDBACK_HONEST_EMPTY',
  FIELD_SOURCE_UNKNOWN: 'FIELD_SOURCE_UNKNOWN',
});

export const HANDBACK_TEXT = Object.freeze({
  [HANDBACK_CODE.HANDBACK_NO_BUNDLE]:
    'Handback arrived without its artifact bundle — quarantined; nothing accepted.',
  [HANDBACK_CODE.HANDBACK_NEVER_ARRIVED]:
    'Commission <id> confirmed <t> ago; no handback. Named as overdue, not absorbed.',
  [HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE]:
    'Handback failed validation on <fields> — quarantined for repair; work preserved.',
  [HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED]:
    'Handback <id> already ingested — duplicate ignored; one receipt stands.',
  [HANDBACK_CODE.QUARANTINE_UNREADABLE]:
    'Quarantine store unreadable — validation refused; raw handback untouched.',
  [HANDBACK_CODE.HANDBACK_HONEST_EMPTY]:
    'Handback valid but <n>/<m> fields honestly unavailable — coverage ratio shown.',
  [HANDBACK_CODE.FIELD_SOURCE_UNKNOWN]:
    'Field <f> cites no source artifact — rejected; shown as unknown, not filled.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function handbackFailure(code, extra = {}) {
  let text = HANDBACK_TEXT[code] ?? HANDBACK_TEXT[HANDBACK_CODE.FIELD_SOURCE_UNKNOWN];
  if (code === HANDBACK_CODE.HANDBACK_NEVER_ARRIVED) {
    if (extra.id != null) text = text.replace('<id>', String(extra.id));
    if (extra.t != null) text = text.replace('<t>', String(extra.t));
  }
  if (code === HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE && extra.fields != null) {
    const fields = Array.isArray(extra.fields)
      ? extra.fields.join(', ')
      : String(extra.fields);
    text = text.replace('<fields>', fields);
  }
  if (code === HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED && extra.id != null) {
    text = text.replace('<id>', String(extra.id));
  }
  if (code === HANDBACK_CODE.HANDBACK_HONEST_EMPTY) {
    if (extra.n != null) text = text.replace('<n>', String(extra.n));
    if (extra.m != null) text = text.replace('<m>', String(extra.m));
  }
  if (code === HANDBACK_CODE.FIELD_SOURCE_UNKNOWN && extra.f != null) {
    text = text.replace('<f>', String(extra.f));
  }
  return {
    ok: false,
    code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    handback_surface: true,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function handbackFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (bundle absent)',
      status_code: HANDBACK_CODE.HANDBACK_NO_BUNDLE,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.HANDBACK_NO_BUNDLE],
    }),
    Object.freeze({
      state: 'dependency-slow-or-killed (never arrived)',
      status_code: HANDBACK_CODE.HANDBACK_NEVER_ARRIVED,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.HANDBACK_NEVER_ARRIVED],
    }),
    Object.freeze({
      state: 'dependency-returns-garbage',
      status_code: HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE],
    }),
    Object.freeze({
      state: 'duplicate-handback-ignored',
      status_code: HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: HANDBACK_CODE.QUARANTINE_UNREADABLE,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.QUARANTINE_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid (all fields unavailable)',
      status_code: HANDBACK_CODE.HANDBACK_HONEST_EMPTY,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.HANDBACK_HONEST_EMPTY],
    }),
    Object.freeze({
      state: 'unknown (derivation source missing)',
      status_code: HANDBACK_CODE.FIELD_SOURCE_UNKNOWN,
      user_text: HANDBACK_TEXT[HANDBACK_CODE.FIELD_SOURCE_UNKNOWN],
    }),
  ]);
}

// ── Pure helpers ───────────────────────────────────────────────────────────

function nonEmpty(v) {
  return v != null && v !== '';
}

/**
 * Canonical JSON for golden byte-identity (stable key order).
 * @param {*} value
 * @returns {string}
 */
export function stableStringify(value) {
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeys(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * Content hash of a rendered body (deterministic).
 * @param {object} payload
 * @returns {string}
 */
export function contentHash(payload) {
  return crypto
    .createHash('sha256')
    .update(JSON.stringify(sortKeys(payload)))
    .digest('hex');
}

/**
 * Allow-list v4 proof for Wave 14 tests.
 */
export function assertW14KindsAdmitted() {
  const missing = [];
  for (const k of W14_EVENT_KINDS) {
    const gate = assertEventKindAllowed(k);
    if (!gate.ok) missing.push(k);
  }
  return {
    ok: missing.length === 0 && ROADMAP_EVENT_KINDS_VERSION >= 4,
    version: ROADMAP_EVENT_KINDS_VERSION,
    w14_kinds: [...W14_EVENT_KINDS],
    admitted: missing.length === 0,
    missing,
  };
}

/**
 * Source-removal proof: quarantine + ingest must name durable helpers.
 * @param {string} sourceText
 */
export function assertHandbackIngestDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('emitReflectionReceipt')) {
    missing.push('emitReflectionReceipt');
  }
  if (!sourceText.includes('proposeNextStageDeterministic')) {
    missing.push('proposeNextStageDeterministic');
  }
  if (!sourceText.includes(QUARANTINE_REL.split(path.sep).join('/')) &&
      !sourceText.includes('handback-quarantine')) {
    missing.push('handback-quarantine');
  }
  return { ok: missing.length === 0, missing };
}

// ── Ledger view construction ───────────────────────────────────────────────

/**
 * Build a pure ledgerView from a roadmap + optional scaffolding / opts.
 * Callers may pass a pre-built view; ingest builds one from disk when absent.
 *
 * @param {{
 *   roadmap?: object|null,
 *   events?: object[],
 *   projection?: object[],
 *   scaffolding?: object|null,
 *   steps?: object[],
 *   current_step_id?: string|null,
 *   handback?: object|null,
 *   at?: string|null,
 *   oranges_prompts?: string[]|null,
 * }} [input]
 * @returns {object}
 */
export function buildLedgerView(input = {}) {
  const roadmap = input.roadmap ?? null;
  const events = Array.isArray(input.events)
    ? input.events
    : Array.isArray(roadmap?.roadmap_events)
      ? roadmap.roadmap_events
      : [];
  const projection = Array.isArray(input.projection)
    ? input.projection
    : Array.isArray(roadmap?.roadmap_projection)
      ? roadmap.roadmap_projection
      : (() => {
          try {
            return buildRoadmapProjection(events).projection ?? [];
          } catch {
            return [];
          }
        })();

  const scaffolding = input.scaffolding ?? null;
  const scaffoldSteps = Array.isArray(scaffolding?.steps)
    ? scaffolding.steps
    : Array.isArray(scaffolding?.proposal?.steps)
      ? scaffolding.proposal.steps
      : [];

  // Prefer scaffolding steps (carry oranges); fall back to projection.
  const steps =
    Array.isArray(input.steps) && input.steps.length
      ? input.steps
      : scaffoldSteps.length
        ? scaffoldSteps
        : projection.map((s) => ({
            step_id: s.id ?? s.step_id,
            name: s.name,
            done_when: s.done_when ?? null,
            status: s.status ?? null,
            oranges_annotations: [...DEFAULT_ORANGES_PROMPTS],
          }));

  return {
    events,
    projection,
    steps,
    scaffolding,
    current_step_id: input.current_step_id ?? null,
    handback: input.handback ?? null,
    at: input.at ?? null,
    oranges_prompts: input.oranges_prompts ?? null,
  };
}

/**
 * Resolve dossier-like facts (accept full dossier or sparse handback facts).
 * @param {object|null} dossier
 * @returns {object}
 */
function normalizeDossier(dossier) {
  if (!dossier || typeof dossier !== 'object') {
    return emptyDossier('unknown');
  }
  return dossier;
}

// ── THE DETERMINISTIC EMITTERS (gate decision 4) ───────────────────────────

/**
 * ZERO-MODEL, ZERO-SPEND, ZERO-NETWORK pure render: reflection receipt from
 * dossier + ledger facts. Carries what the stage produced + its Oranges prompts.
 *
 * Signature locked by the frozen plan: emitReflectionReceipt(dossier, ledgerView).
 *
 * @param {object|null} dossier
 * @param {object|null} ledgerView
 * @returns {{ ok: true, receipt: object } | { ok: false, code: string, message: string }}
 */
export function emitReflectionReceipt(dossier, ledgerView) {
  const d = normalizeDossier(dossier);
  const view = buildLedgerView(ledgerView ?? {});
  const handback =
    view.handback ??
    d.handback?.body ??
    d.handback ??
    null;

  if (!handback || (handback.kind && handback.kind !== 'handback')) {
    // Accept body without kind when it carries campaign-memory fields.
    if (!handback || !nonEmpty(handback.active_effort)) {
      return handbackFailure(HANDBACK_CODE.FIELD_SOURCE_UNKNOWN, {
        f: 'handback',
        error: 'reflection_requires_handback',
        message:
          'Reflection blocked — validated handback required (gate decision 4).',
      });
    }
  }

  const step_id =
    view.current_step_id ??
    d.proposal?.step_id ??
    d.confirmation?.step_id ??
    handback.step_id ??
    null;

  const steps = view.steps ?? [];
  const current =
    steps.find((s) => (s.step_id ?? s.id) === step_id) ?? null;
  const oranges =
    Array.isArray(view.oranges_prompts) && view.oranges_prompts.length
      ? [...view.oranges_prompts]
      : current?.oranges_annotations?.length
        ? [...current.oranges_annotations]
        : [...DEFAULT_ORANGES_PROMPTS];

  // Deterministic timestamp: never wall-clock; prefer ledger/dossier facts.
  const at =
    view.at ??
    handback.as_of ??
    d.handback?.at ??
    d.updated_at ??
    '1970-01-01T00:00:00.000Z';

  const stage_produced = {
    active_effort: handback.active_effort ?? null,
    why_next: handback.why_next ?? null,
    human_wait: handback.human_wait ?? null,
    tool_depth_why: handback.tool_depth_why ?? null,
    grasscatch_why:
      handback.grasscatch_why !== undefined ? handback.grasscatch_why : null,
    uncertainty_flags: Array.isArray(handback.uncertainty_flags)
      ? [...handback.uncertainty_flags]
      : [],
    skill:
      handback.skill ??
      d.proposal?.skill ??
      d.commissioned_as?.split?.(':')?.[0] ??
      null,
    depth: handback.depth ?? d.proposal?.depth_cell ?? null,
  };

  // Coverage for honest-empty reporting (fields present vs non-null).
  const coverageKeys = [
    'active_effort',
    'why_next',
    'human_wait',
    'tool_depth_why',
    'grasscatch_why',
    'uncertainty_flags',
  ];
  let available = 0;
  for (const k of coverageKeys) {
    const v = stage_produced[k];
    if (k === 'uncertainty_flags') {
      if (Array.isArray(v)) available += 1;
    } else if (v !== null && v !== undefined && v !== '') {
      available += 1;
    }
  }

  const receiptBody = {
    schema: REFLECTION_RECEIPT_SCHEMA,
    kind: 'reflection_receipt',
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    deterministic: true,
    gate_decision: 4,
    step_id,
    job_id: d.job_id ?? null,
    handback_id:
      handback.handback_id ?? d.handback?.handback_id ?? null,
    skill: stage_produced.skill,
    stage_produced,
    oranges_prompts: oranges,
    handback_summary: {
      active_effort: stage_produced.active_effort,
      why_next: stage_produced.why_next,
      human_wait: stage_produced.human_wait,
      uncertainty_flags: stage_produced.uncertainty_flags,
    },
    coverage: {
      available,
      total: coverageKeys.length,
      ratio: `${available}/${coverageKeys.length}`,
    },
    provenance: 'ledger-facts-deterministic',
    at,
    message:
      'ZERO-MODEL reflection receipt emitted at handback (gate decision 4) — not a queued split.',
  };

  const fingerprint = contentHash(receiptBody);
  const receipt = { ...receiptBody, content_hash: fingerprint };

  return {
    ok: true,
    receipt,
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    content_hash: fingerprint,
  };
}

/**
 * ZERO-MODEL, ZERO-SPEND, ZERO-NETWORK pure render: next-stage proposal from
 * dossier + ledger facts. Names the next roadmap step with its why; enters the
 * standard propose → confirm path (requires_confirm: true, confirmed: false).
 *
 * Signature locked by the frozen plan: proposeNextStageDeterministic(dossier, ledgerView).
 *
 * @param {object|null} dossier
 * @param {object|null} ledgerView
 * @returns {{ ok: true, proposal: object } | { ok: false, code: string, message: string }}
 */
export function proposeNextStageDeterministic(dossier, ledgerView) {
  const d = normalizeDossier(dossier);
  const view = buildLedgerView(ledgerView ?? {});
  const handback =
    view.handback ??
    d.handback?.body ??
    d.handback ??
    null;

  if (!handback && !view.steps?.length) {
    return handbackFailure(HANDBACK_CODE.FIELD_SOURCE_UNKNOWN, {
      f: 'handback_or_steps',
      error: 'next_stage_requires_facts',
      message:
        'Next-stage proposal blocked — validated handback or ledger steps required.',
    });
  }

  const steps = Array.isArray(view.steps) ? view.steps : [];
  const currentId =
    view.current_step_id ??
    d.proposal?.step_id ??
    d.confirmation?.step_id ??
    handback?.step_id ??
    null;

  const currentIdx = steps.findIndex((s) => (s.step_id ?? s.id) === currentId);
  const next =
    currentIdx >= 0 && currentIdx + 1 < steps.length
      ? steps[currentIdx + 1]
      : currentIdx < 0 && steps.length > 0
        ? null // current unknown — do not invent a next
        : null;

  const at =
    view.at ??
    handback?.as_of ??
    d.handback?.at ??
    d.updated_at ??
    '1970-01-01T00:00:00.000Z';

  const why_from_handback = handback?.why_next ?? null;

  if (!next) {
    const proposalBody = {
      schema: NEXT_STAGE_PROPOSAL_SCHEMA,
      kind: 'next_stage_proposal',
      zero_model: true,
      zero_spend: true,
      zero_network: true,
      deterministic: true,
      gate_decision: 4,
      from_step_id: currentId,
      next_step_id: null,
      next_step: null,
      why:
        why_from_handback ??
        'No further stage in the confirmed scaffolding — campaign stages exhausted.',
      campaign_complete: true,
      requires_confirm: true,
      confirmed: false,
      enters_propose_confirm_path: true,
      oranges_prompts: [...DEFAULT_ORANGES_PROMPTS],
      provenance: 'ledger-facts-deterministic',
      at,
      message:
        'ZERO-MODEL next-stage proposal: no further stage — campaign stages exhausted.',
    };
    const fingerprint = contentHash(proposalBody);
    const proposal = { ...proposalBody, content_hash: fingerprint };
    return {
      ok: true,
      proposal,
      zero_model: true,
      zero_spend: true,
      zero_network: true,
      content_hash: fingerprint,
    };
  }

  const nextId = next.step_id ?? next.id;
  const nextName = next.name ?? nextId;
  const oranges =
    next.oranges_annotations?.length
      ? [...next.oranges_annotations]
      : [...DEFAULT_ORANGES_PROMPTS];

  const why =
    why_from_handback ??
    next.done_when ??
    `Advance to '${nextName}' — next roadmap step after '${currentId ?? 'current'}'.`;

  const proposalBody = {
    schema: NEXT_STAGE_PROPOSAL_SCHEMA,
    kind: 'next_stage_proposal',
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    deterministic: true,
    gate_decision: 4,
    from_step_id: currentId,
    next_step_id: nextId,
    next_step: {
      step_id: nextId,
      name: nextName,
      done_when: next.done_when ?? null,
      oranges_annotations: oranges,
    },
    why,
    campaign_complete: false,
    requires_confirm: true,
    confirmed: false,
    enters_propose_confirm_path: true,
    oranges_prompts: oranges,
    provenance: 'ledger-facts-deterministic',
    at,
    message: `ZERO-MODEL next-stage proposal for '${nextId}' emitted at handback (gate decision 4).`,
  };
  const fingerprint = contentHash(proposalBody);
  const proposal = { ...proposalBody, content_hash: fingerprint };
  return {
    ok: true,
    proposal,
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    content_hash: fingerprint,
  };
}

/**
 * Gate decision 4 pair from pure emitters (no I/O, no model).
 * @param {object|null} dossier
 * @param {object|null} ledgerView
 */
export function emitHandbackPairDeterministic(dossier, ledgerView) {
  const reflection = emitReflectionReceipt(dossier, ledgerView);
  if (!reflection.ok) return reflection;
  const next = proposeNextStageDeterministic(dossier, ledgerView);
  if (!next.ok) return next;
  return {
    ok: true,
    reflection_receipt: reflection.receipt,
    next_stage_proposal: next.proposal,
    gate_decision: 4,
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    queued_proposal_split: false,
  };
}

// ── Quarantine store (S7) ──────────────────────────────────────────────────

/**
 * @param {string} projectRoot
 * @returns {string}
 */
export function quarantineDir(projectRoot) {
  return path.join(String(projectRoot), ...QUARANTINE_REL.split(path.sep));
}

/**
 * @param {string} projectRoot
 * @param {string} key
 */
export function quarantineEntryPath(projectRoot, key) {
  const safe = String(key).replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 120);
  return path.join(quarantineDir(projectRoot), `${safe}.json`);
}

/**
 * @param {string} projectRoot
 */
export function ingestRegistryPath(projectRoot) {
  return path.join(String(projectRoot), ...INGEST_REGISTRY_REL.split(path.sep));
}

/**
 * Read the durable ingest registry (set of adopted idempotence keys).
 * @param {string} projectRoot
 */
export function readIngestRegistry(projectRoot) {
  const p = ingestRegistryPath(projectRoot);
  try {
    if (!fs.existsSync(p)) {
      return { ok: true, exists: false, keys: [], path: p };
    }
    const raw = fs.readFileSync(p, 'utf8');
    const parsed = JSON.parse(raw);
    const keys = Array.isArray(parsed?.keys) ? parsed.keys.map(String) : [];
    return { ok: true, exists: true, keys, path: p, value: parsed };
  } catch (e) {
    return {
      ok: false,
      error: 'registry_unreadable',
      detail: String(e?.message ?? e),
      path: p,
    };
  }
}

/**
 * Atomically record an adopted key (idempotent set add).
 * @param {string} projectRoot
 * @param {string} key
 * @returns {{ ok: true, already: boolean, keys: string[] } | { ok: false, ... }}
 */
export function recordIngestKey(projectRoot, key) {
  if (!key || typeof key !== 'string') {
    return { ok: false, error: 'key_required' };
  }
  const p = ingestRegistryPath(projectRoot);
  try {
    let already = false;
    let keys = [];
    withFileLock(
      p,
      () => {
        let base = { schema: 'ecgberht-handback-ingest-registry-v0', keys: [] };
        if (fs.existsSync(p)) {
          try {
            base = { ...base, ...JSON.parse(fs.readFileSync(p, 'utf8')) };
          } catch {
            /* start fresh on torn */
          }
        }
        keys = Array.isArray(base.keys) ? base.keys.map(String) : [];
        if (keys.includes(key)) {
          already = true;
        } else {
          keys = [...keys, key];
          base = { ...base, keys, updated_at: new Date().toISOString() };
          fs.mkdirSync(path.dirname(p), { recursive: true });
          writeFileAtomicSync(p, `${JSON.stringify(base, null, 2)}\n`);
        }
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
    return { ok: true, already, keys, key };
  } catch (e) {
    return {
      ok: false,
      error: 'registry_write_failed',
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Quarantine a refused handback (S7). Duplicate key → one entry (idempotent).
 *
 * @param {string} projectRoot
 * @param {{
 *   key: string,
 *   reason: string,
 *   status_code: string,
 *   fields?: string[],
 *   raw?: *,
 *   worktree?: string|null,
 * }} entry
 */
export function quarantineHandback(projectRoot, entry) {
  const key = entry.key ?? 'unknown';
  const filePath = quarantineEntryPath(projectRoot, key);
  try {
    let already = false;
    let written = null;
    withFileLock(
      filePath,
      () => {
        if (fs.existsSync(filePath)) {
          already = true;
          try {
            written = JSON.parse(fs.readFileSync(filePath, 'utf8'));
          } catch {
            written = null;
          }
          return;
        }
        written = {
          schema: 'ecgberht-handback-quarantine-v0',
          key,
          reason: entry.reason ?? null,
          status_code: entry.status_code ?? HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE,
          fields: entry.fields ?? [],
          raw: entry.raw ?? null,
          worktree_rel: entry.worktree
            ? path.basename(String(entry.worktree))
            : null,
          contract_version: CONTRACT_VERSION,
          at: entry.at ?? new Date().toISOString(),
          repairable: true,
        };
        fs.mkdirSync(path.dirname(filePath), { recursive: true });
        writeFileAtomicSync(filePath, `${JSON.stringify(written, null, 2)}\n`);
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
    return {
      ok: true,
      quarantined: true,
      already,
      path: filePath,
      entry: written,
      status_code: entry.status_code ?? HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE,
    };
  } catch (e) {
    return handbackFailure(HANDBACK_CODE.QUARANTINE_UNREADABLE, {
      error: 'quarantine_write_failed',
      detail: String(e?.message ?? e),
    });
  }
}

/**
 * List quarantine entries (for tests / repair surfaces).
 * @param {string} projectRoot
 */
export function listQuarantine(projectRoot) {
  const dir = quarantineDir(projectRoot);
  try {
    if (!fs.existsSync(dir)) return { ok: true, entries: [] };
    const files = fs.readdirSync(dir).filter((f) => f.endsWith('.json'));
    const entries = [];
    for (const f of files) {
      try {
        entries.push(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
      } catch {
        /* skip torn */
      }
    }
    return { ok: true, entries };
  } catch (e) {
    return handbackFailure(HANDBACK_CODE.QUARANTINE_UNREADABLE, {
      detail: String(e?.message ?? e),
    });
  }
}

// ── Missing handback (NAMED, never absorbed) ───────────────────────────────

/**
 * Name a never-arrived handback. Never silently absorbs the absence.
 *
 * @param {{
 *   commission_id: string,
 *   confirmed_at?: string|null,
 *   confirmed_ago?: string|null,
 * }} opts
 */
export function nameMissingHandback(opts = {}) {
  const id = opts.commission_id ?? opts.id ?? 'unknown';
  const t =
    opts.confirmed_ago ??
    opts.confirmed_at ??
    opts.t ??
    'unknown duration';
  return handbackFailure(HANDBACK_CODE.HANDBACK_NEVER_ARRIVED, {
    id,
    t,
    named: true,
    absorbed: false,
    commission_id: id,
  });
}

// ── Ingest pipeline ────────────────────────────────────────────────────────

/**
 * Resolve the idempotence key for a handback body.
 * @param {object} handback
 * @returns {string|null}
 */
export function handbackIdempotenceKey(handback) {
  if (!handback || typeof handback !== 'object') return null;
  if (nonEmpty(handback.client_event_id)) return String(handback.client_event_id);
  if (nonEmpty(handback.handback_id)) return String(handback.handback_id);
  if (nonEmpty(handback.commission_id)) {
    return `commission:${handback.commission_id}`;
  }
  return null;
}

/**
 * Count reflection_receipt / next_stage_proposal events for a handback key.
 * @param {object} roadmap
 * @param {string} key
 */
export function countEmittedForKey(roadmap, key) {
  const events = Array.isArray(roadmap?.roadmap_events)
    ? roadmap.roadmap_events
    : [];
  let receipts = 0;
  let proposals = 0;
  for (const e of events) {
    if (!e) continue;
    if (
      e.kind === 'reflection_receipt' &&
      (e.client_event_id === `reflection:${key}` || e.idempotence_key === key)
    ) {
      receipts += 1;
    }
    if (
      e.kind === 'next_stage_proposal' &&
      (e.client_event_id === `next-stage:${key}` || e.idempotence_key === key)
    ) {
      proposals += 1;
    }
  }
  return { receipts, proposals };
}

/**
 * Ingest a durable handback pair from a run worktree into the campaign.
 *
 * EXECUTOR-AGNOSTIC: only the Wave-4 file contract is required.
 * ALWAYS emits reflection receipt + next-stage proposal on first valid ingest
 * (zero-model, regardless of envelope). NL-polish alone queues without envelope.
 *
 * @param {string} projectRoot  campaign project root (ledger home)
 * @param {string} worktreeRoot run worktree holding `.ecgberht/handback/`
 * @param {{
 *   dossier?: object|null,
 *   ledgerView?: object|null,
 *   job_id?: string|null,
 *   skip_index?: boolean,
 *   require_bundle?: boolean,
 *   bundle_present?: boolean,
 *   at?: string|null,
 * }} [opts]
 */
export function ingestHandback(projectRoot, worktreeRoot, opts = {}) {
  if (!projectRoot || typeof projectRoot !== 'string') {
    return {
      ok: false,
      error: 'project_root_required',
      message: 'ingestHandback requires a project root.',
    };
  }
  if (!worktreeRoot || typeof worktreeRoot !== 'string') {
    return {
      ok: false,
      error: 'worktree_required',
      message: 'ingestHandback requires a worktree root with the durable handback pair.',
    };
  }

  // Bundle-absent refusal (artifact bundle dependency).
  if (opts.require_bundle === true && opts.bundle_present === false) {
    const q = quarantineHandback(projectRoot, {
      key: `no-bundle:${path.basename(worktreeRoot)}`,
      reason: 'bundle_absent',
      status_code: HANDBACK_CODE.HANDBACK_NO_BUNDLE,
      worktree: worktreeRoot,
    });
    return {
      ...handbackFailure(HANDBACK_CODE.HANDBACK_NO_BUNDLE),
      quarantined: q.ok === true,
      quarantine: q,
      reflection_receipt: null,
      next_stage_proposal: null,
    };
  }

  // Pair must be ingestable (both handback.json + TERMINAL.marker).
  if (!isIngestable(worktreeRoot)) {
    const read = readIngestableHandback(worktreeRoot);
    return {
      ok: false,
      error: read.error ?? 'not_ingestable',
      status_code: read.status_code ?? 'EXEC_HANDBACK_MISSING',
      message: read.message ?? 'Handback pair not ingestable.',
      reflection_receipt: null,
      next_stage_proposal: null,
    };
  }

  const read = readIngestableHandback(worktreeRoot);
  if (!read.ok) {
    // Corrupted / unreadable body on an otherwise present pair → quarantine.
    const key =
      `refused:${path.basename(worktreeRoot)}:${read.error ?? 'invalid'}`;
    let raw = null;
    try {
      if (fs.existsSync(handbackJsonPath(worktreeRoot))) {
        raw = fs.readFileSync(handbackJsonPath(worktreeRoot), 'utf8');
      }
    } catch {
      /* leave raw null */
    }
    const fields = read.issues ?? [read.error ?? 'validation'];
    const q = quarantineHandback(projectRoot, {
      key,
      reason: read.error ?? 'validation_failed',
      status_code: HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE,
      fields: Array.isArray(fields) ? fields : [String(fields)],
      raw,
      worktree: worktreeRoot,
    });
    if (!q.ok && q.status_code === HANDBACK_CODE.QUARANTINE_UNREADABLE) {
      return {
        ...q,
        reflection_receipt: null,
        next_stage_proposal: null,
      };
    }
    return {
      ...handbackFailure(HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE, {
        fields: Array.isArray(fields) ? fields : [String(fields)],
      }),
      quarantined: true,
      quarantine: q,
      reflection_receipt: null,
      next_stage_proposal: null,
      refused_repairable: true,
    };
  }

  const handback = read.handback;

  // Re-validate campaign-memory fields via receipt-validate (single validator).
  const validated = validateReceipt(handback);
  if (!validated.ok) {
    const fields = validated.issues ?? [validated.error ?? 'receipt_schema_invalid'];
    const key =
      handbackIdempotenceKey(handback) ??
      `refused:${path.basename(worktreeRoot)}`;
    const q = quarantineHandback(projectRoot, {
      key: `refused:${key}`,
      reason: validated.error ?? 'receipt_schema_invalid',
      status_code: HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE,
      fields: Array.isArray(fields) ? fields : [String(fields)],
      raw: handback,
      worktree: worktreeRoot,
    });
    return {
      ...handbackFailure(HANDBACK_CODE.HANDBACK_REFUSED_REPAIRABLE, {
        fields: Array.isArray(fields) ? fields : [String(fields)],
      }),
      quarantined: true,
      quarantine: q,
      reflection_receipt: null,
      next_stage_proposal: null,
      refused_repairable: true,
    };
  }

  const key = handbackIdempotenceKey(handback);
  if (!key) {
    return handbackFailure(HANDBACK_CODE.FIELD_SOURCE_UNKNOWN, {
      f: IDEMPOTENCE_KEY,
      error: 'idempotence_key_missing',
      message:
        'Field client_event_id (or handback_id) cites no source — rejected; shown as unknown, not filled.',
      reflection_receipt: null,
      next_stage_proposal: null,
    });
  }

  // ── Idempotence (T-IDEM-14): duplicate delivery → one receipt, one proposal
  const reg = readIngestRegistry(projectRoot);
  if (!reg.ok) {
    // Registry unreadable is not quarantine-unreadable; still refuse re-derive
    // blindly — treat as state unknown by refusing duplicate-unsafe path.
    return {
      ok: false,
      error: 'ingest_registry_unreadable',
      message: reg.detail ?? 'Ingest registry unreadable.',
      reflection_receipt: null,
      next_stage_proposal: null,
    };
  }

  if (reg.keys.includes(key)) {
    // Already ingested — load existing emissions; emit nothing new.
    const loaded = loadProjectRoadmap(projectRoot);
    const roadmap = loaded.ok && loaded.exists ? loaded.roadmap : emptyRoadmap();
    const counts = countEmittedForKey(roadmap, key);
    const existingReceipt =
      (roadmap.roadmap_events ?? []).find(
        (e) =>
          e?.kind === 'reflection_receipt' &&
          e.client_event_id === `reflection:${key}`,
      ) ?? null;
    const existingProposal =
      (roadmap.roadmap_events ?? []).find(
        (e) =>
          e?.kind === 'next_stage_proposal' &&
          e.client_event_id === `next-stage:${key}`,
      ) ?? null;
    return {
      ...handbackFailure(HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED, { id: key }),
      duplicate: true,
      duplicate_handback_ignored: true,
      status: 'duplicate-handback-ignored',
      idempotence_key: key,
      reflection_receipt: existingReceipt?.receipt ?? existingReceipt ?? null,
      next_stage_proposal: existingProposal?.proposal ?? existingProposal ?? null,
      receipt_count: counts.receipts,
      proposal_count: counts.proposals,
      emitted: false,
    };
  }

  // Build dossier + ledgerView for pure emitters.
  const dossier =
    opts.dossier ??
    emptyDossier(opts.job_id ?? handback.commission_id ?? key, null);
  if (!dossier.handback) {
    dossier.handback = {
      handback_id: handback.handback_id ?? key,
      body: handback,
      at: opts.at ?? handback.as_of ?? null,
    };
  }

  const loaded = loadProjectRoadmap(projectRoot);
  const roadmap =
    opts.ledgerView?.roadmap ??
    (loaded.ok && loaded.exists ? loaded.roadmap : emptyRoadmap());

  const ledgerView = buildLedgerView({
    ...(opts.ledgerView ?? {}),
    roadmap,
    handback,
    current_step_id:
      opts.ledgerView?.current_step_id ??
      dossier.proposal?.step_id ??
      handback.step_id ??
      null,
    at: opts.at ?? handback.as_of ?? null,
  });

  // ALWAYS emit at handback — regardless of envelope (zero spend).
  const pair = emitHandbackPairDeterministic(dossier, ledgerView);
  if (!pair.ok) {
    return {
      ...pair,
      reflection_receipt: null,
      next_stage_proposal: null,
      emitted: false,
    };
  }

  // Append both events through the spine (allow-list v4).
  const spineOpts = {
    skip_index: opts.skip_index !== false ? true : false,
    seed: loaded.ok && loaded.exists ? undefined : emptyRoadmap(),
  };

  const receiptEvent = {
    kind: 'reflection_receipt',
    step_id: pair.reflection_receipt.step_id ?? null,
    client_event_id: `reflection:${key}`,
    idempotence_key: key,
    receipt: pair.reflection_receipt,
    content_hash: pair.reflection_receipt.content_hash,
    zero_model: true,
    zero_spend: true,
    gate_decision: 4,
    at: pair.reflection_receipt.at,
  };
  const proposalEvent = {
    kind: 'next_stage_proposal',
    step_id: pair.next_stage_proposal.from_step_id ?? null,
    client_event_id: `next-stage:${key}`,
    idempotence_key: key,
    proposal: pair.next_stage_proposal,
    content_hash: pair.next_stage_proposal.content_hash,
    zero_model: true,
    zero_spend: true,
    gate_decision: 4,
    requires_confirm: true,
    at: pair.next_stage_proposal.at,
  };

  const rAppend = appendRoadmapEventThroughSpine(
    projectRoot,
    receiptEvent,
    spineOpts,
  );
  if (!rAppend.ok) {
    return {
      ok: false,
      error: 'spine_append_receipt_failed',
      detail: rAppend,
      reflection_receipt: pair.reflection_receipt,
      next_stage_proposal: pair.next_stage_proposal,
      emitted: false,
    };
  }

  const pAppend = appendRoadmapEventThroughSpine(
    projectRoot,
    proposalEvent,
    { ...spineOpts, seed: undefined },
  );
  if (!pAppend.ok) {
    return {
      ok: false,
      error: 'spine_append_proposal_failed',
      detail: pAppend,
      reflection_receipt: pair.reflection_receipt,
      next_stage_proposal: pair.next_stage_proposal,
      emitted: false,
    };
  }

  // Record registry key AFTER successful appends (first-write wins).
  const recorded = recordIngestKey(projectRoot, key);
  if (!recorded.ok) {
    return {
      ok: false,
      error: 'registry_record_failed',
      detail: recorded,
      reflection_receipt: pair.reflection_receipt,
      next_stage_proposal: pair.next_stage_proposal,
      emitted: true,
      warning: 'emitted_but_registry_failed',
    };
  }
  // Race: another process recorded first between our check and append —
  // spine client_event_id idempotence still keeps one event each.
  if (recorded.already) {
    const reloaded = loadProjectRoadmap(projectRoot);
    const rm = reloaded.ok && reloaded.exists ? reloaded.roadmap : null;
    const counts = countEmittedForKey(rm, key);
    return {
      ...handbackFailure(HANDBACK_CODE.HANDBACK_DUPLICATE_IGNORED, { id: key }),
      duplicate: true,
      duplicate_handback_ignored: true,
      reflection_receipt: pair.reflection_receipt,
      next_stage_proposal: pair.next_stage_proposal,
      receipt_count: counts.receipts,
      proposal_count: counts.proposals,
      emitted: false,
    };
  }

  // Record on dossier (best-effort; non-fatal).
  try {
    if (dossier.job_id && dossier.job_id !== 'unknown') {
      recordHandbackOnDossier(projectRoot, {
        job_id: dossier.job_id,
        handback_path: handbackJsonPath(worktreeRoot),
        handback_id: handback.handback_id ?? key,
        body: handback,
      });
    }
  } catch {
    /* dossier optional for pure ingest tests */
  }

  // NL-polish ONLY queues without a live envelope (receipt/proposal never queue).
  let nl_polish = null;
  let envelope_live = false;
  try {
    const envState = readEnvelopeState(projectRoot, {
      monoNow: opts.monoNow,
    });
    envelope_live = envState?.live === true || envState?.balance?.live === true;
  } catch {
    envelope_live = false;
  }

  const zeroPath = resolveNoLiveEnvelopePath(
    'deterministic_reflection_receipt',
    { live: envelope_live },
  );
  // Assert plan posture: zero-spend kinds never queue.
  if (!envelope_live) {
    const qPath = resolveNoLiveEnvelopePath(QUEUE_WITHOUT_ENVELOPE_KIND, {
      live: false,
    });
    if (qPath.queue) {
      nl_polish = queueNlPolishReflectionCompile(projectRoot, {
        client_event_id: `nl-polish:${key}`,
        payload: {
          handback_id: handback.handback_id ?? key,
          reflection_content_hash: pair.reflection_receipt.content_hash,
          deferred: true,
          fires_at: 'next_session_open_inside_envelope',
        },
      });
    }
  }

  // Honest-empty coverage note when few fields available.
  const cov = pair.reflection_receipt.coverage;
  const honestEmpty =
    cov && cov.available === 0
      ? handbackFailure(HANDBACK_CODE.HANDBACK_HONEST_EMPTY, {
          n: cov.available,
          m: cov.total,
        })
      : null;

  // T-ATT-CS3: validated handback ingested → publish from the Wave-14 ingester.
  let attention_publish = null;
  if (opts.skip_attention_publish !== true) {
    const bundle_hash =
      handback.bundle_hash ??
      handback.content_hash ??
      pair.reflection_receipt?.content_hash ??
      null;
    const expected_bundle_hash =
      opts.expected_bundle_hash ??
      handback.expected_bundle_hash ??
      dossier?.bundle_hash ??
      bundle_hash;
    attention_publish = publishAttention(projectRoot, {
      // T-ATT-CS3 — removal-proof marker must be the literal call-site id
      call_site: 'handback_ingest', // ATTENTION_CALL_SITES.HANDBACK
      who: opts.who || 'handback-ingest',
      at: opts.at ?? handback.as_of ?? null,
      seed: loaded.ok && loaded.exists ? undefined : emptyRoadmap(),
      skip_index: true,
      ledgerView: {
        ...ledgerView,
        deliverable_ready: true,
        bundle_hash,
        expected_bundle_hash,
        handback,
        events: [
          ...(ledgerView.events || []),
          { kind: 'reflection_receipt', content_hash: pair.reflection_receipt.content_hash },
        ],
        nl_polish_queued: nl_polish?.queued === true,
      },
      home: opts.home,
      env: opts.env,
      project_id: opts.project_id,
      skip_brief_cache: opts.skip_brief_cache === true,
    });
  }

  return {
    ok: true,
    schema: HANDBACK_INGEST_SCHEMA,
    status: 'ingested',
    idempotence_key: key,
    handback_id: handback.handback_id ?? key,
    client_event_id: handback.client_event_id ?? null,
    contract_version: handback.contract_version ?? CONTRACT_VERSION,
    reflection_receipt: pair.reflection_receipt,
    next_stage_proposal: pair.next_stage_proposal,
    emitted: true,
    zero_model: true,
    zero_spend: true,
    zero_network: true,
    envelope_live,
    receipt_queued: false,
    proposal_queued: false,
    nl_polish_queued: nl_polish?.queued === true,
    nl_polish,
    zero_spend_path: zeroPath,
    honest_empty: honestEmpty,
    receipt_append: { seq: rAppend.seq, idempotent: rAppend.idempotent === true },
    proposal_append: {
      seq: pAppend.seq,
      idempotent: pAppend.idempotent === true,
    },
    attention_publish,
  };
}

/**
 * Ingest from an already-validated handback body (tests / fixture worktrees
 * that write the pair then call this). Thin wrapper.
 */
export function ingestValidatedHandbackBody(projectRoot, handbackBody, opts = {}) {
  const work =
    opts.worktreeRoot ??
    path.join(String(projectRoot), '.ecgberht', 'runs', `hb-${Date.now()}`);
  fs.mkdirSync(work, { recursive: true });
  const written = writeHandbackPair(work, handbackBody, {
    client_event_id: handbackBody.client_event_id,
    handback_id: handbackBody.handback_id,
  });
  if (!written.ok) return written;
  return ingestHandback(projectRoot, work, opts);
}

// ── Multi-skill executor proof (criterion 6) ───────────────────────────────

/**
 * Select TEST-BOUND commissionable skills from the table.
 * Fewer than SC6_MIN_COMMISSIONABLE (2) → HALT (never prove with one).
 *
 * @param {object|null} [table]
 * @param {{ root?: string, count?: number }} [opts]
 */
export function selectMultiSkillProofSkills(table, opts = {}) {
  let tbl = table;
  if (!tbl) {
    const load = loadSkillsTable({ root: opts.root ?? DEFAULT_ROOT });
    if (!load.ok) {
      return {
        ok: false,
        halt: true,
        reason: 'skills_table_unreadable',
        message: load.message,
        commissionable_count: 0,
      };
    }
    tbl = load.table;
  }
  const rows = (Array.isArray(tbl?.rows) ? tbl.rows : []).filter(
    (r) => r && r.commissionable === true,
  );
  const need = opts.count ?? SC6_MIN_COMMISSIONABLE;
  if (rows.length < need) {
    return {
      ok: false,
      halt: true,
      reason: 'insufficient_commissionable_skills',
      message: `Multi-skill proof HALT: commissionable_count ${rows.length} < ${need} — never prove criterion 6 with fewer than two skills.`,
      commissionable_count: rows.length,
      min_required: need,
      skills: rows.map((r) => r.skill),
    };
  }
  const selected = rows.slice(0, need);
  return {
    ok: true,
    halt: false,
    commissionable_count: rows.length,
    min_required: need,
    skills: selected.map((r) => r.skill),
    rows: selected,
  };
}

/**
 * Drive one skill through propose → confirm → execute(stub durable handback)
 * → validated handback → emitted receipt + proposal inside one campaign.
 *
 * Uses the durable handback FILE contract (not stdout). Executor is a labelled
 * stub for the standing suite; the wave-local real-run gate exercises live
 * skills.
 *
 * @param {string} projectRoot
 * @param {{
 *   skill: string,
 *   step_id: string,
 *   step_name?: string,
 *   depth?: string,
 *   client_event_id?: string,
 *   handback_id?: string,
 *   scaffolding?: object|null,
 *   at?: string,
 * }} opts
 */
export function driveSkillToValidatedHandback(projectRoot, opts = {}) {
  const skill = opts.skill;
  if (!skill) {
    return { ok: false, error: 'skill_required' };
  }

  // Table-bound selection (test-bound).
  const load = loadSkillsTable({
    root: opts.root ?? DEFAULT_ROOT,
    skills_table: opts.skills_table,
  });
  if (!load.ok) {
    return { ok: false, error: 'skills_table', detail: load };
  }
  const selected = selectCommissionableSkill(skill, load.table);
  if (!selected.ok) {
    return {
      ok: false,
      error: 'skill_not_commissionable',
      skill,
      detail: selected,
    };
  }

  const step_id = opts.step_id ?? `step-${skill}`;
  const step_name = opts.step_name ?? `${skill} stage`;
  const at = opts.at ?? '2026-08-03';
  const client_event_id =
    opts.client_event_id ?? `w14-${skill}-${step_id}-evt`;
  const handback_id = opts.handback_id ?? `w14-${skill}-${step_id}-hb`;

  // Ensure step exists on the campaign ledger.
  const seedStep = appendRoadmapEventThroughSpine(
    projectRoot,
    {
      kind: 'step_create',
      step_id,
      name: step_name,
      status: 'active',
      at,
      client_event_id: `step-create:${step_id}`,
    },
    { skip_index: true, seed: emptyRoadmap('w14-multi') },
  );
  // Idempotent re-create is fine; unknown errors surface.
  if (!seedStep.ok && seedStep.error !== 'duplicate_step_id') {
    // spine may return idempotent or pure-law duplicate — continue if step exists
    const loaded = loadProjectRoadmap(projectRoot);
    const has = (loaded.roadmap?.roadmap_projection ?? []).some(
      (s) => s.id === step_id,
    );
    if (!has && seedStep.error !== 'events-bound-exceeded') {
      // try without seed (ledger already exists)
      const retry = appendRoadmapEventThroughSpine(
        projectRoot,
        {
          kind: 'step_create',
          step_id,
          name: step_name,
          status: 'active',
          at,
          client_event_id: `step-create:${step_id}`,
        },
        { skip_index: true },
      );
      if (!retry.ok && retry.idempotent !== true) {
        // continue — step may already exist from prior skill in campaign
      }
    }
  }

  // Propose / confirm facts (dossier-shaped; zero model).
  const dossier = {
    schema: 'ecgberht-commission-dossier-v0',
    job_id: `job-${skill}-${step_id}`,
    commissioned_as: `${skill}:${step_id}`,
    proposal: {
      skill,
      step_id,
      step_name,
      depth_cell: opts.depth ?? 'LITE',
      confirmed: false,
    },
    confirmation: {
      skill,
      step_id,
      step_name,
      depth_cell: opts.depth ?? 'LITE',
      confirmed: true,
      who: { claimed: 'john', provenance: 'claimed_unauthenticated' },
      at,
    },
    launch: { stub: true, at },
    handback: null,
    repaired_at_boot: false,
    updated_at: at,
  };

  // Execute → durable handback pair (fixture stub shape, contract-conformant).
  const worktree = path.join(
    projectRoot,
    '.ecgberht',
    'runs',
    `${skill}-${step_id}`,
  );
  fs.mkdirSync(worktree, { recursive: true });

  const handbackBody = buildHandbackReceipt({
    as_of: at.slice(0, 10),
    active_effort: step_name,
    why_next: `Stage '${step_id}' complete via ${skill} — propose next roadmap step.`,
    grasscatch_why: null,
    tool_depth_why: `LITE multi-skill proof executor for ${skill} (Wave 14 criterion 6).`,
    human_wait: 'none',
    uncertainty_flags: ['multi-skill-proof', 'wave-14'],
    skill,
    depth: opts.depth ?? 'LITE',
    commission_id: dossier.job_id,
  });
  handbackBody.client_event_id = client_event_id;
  handbackBody.handback_id = handback_id;
  handbackBody.step_id = step_id;
  handbackBody.contract_version = CONTRACT_VERSION;

  const written = writeHandbackPair(worktree, handbackBody, {
    client_event_id,
    handback_id,
  });
  if (!written.ok) {
    return { ok: false, phase: 'write_handback', detail: written, skill };
  }

  const scaffolding =
    opts.scaffolding ??
    {
      steps: [
        {
          step_id,
          name: step_name,
          done_when: `Handback from ${skill} validated`,
          oranges_annotations: [...DEFAULT_ORANGES_PROMPTS],
        },
        {
          step_id: opts.next_step_id ?? `${step_id}-next`,
          name: opts.next_step_name ?? `After ${skill}`,
          done_when: 'Next stage confirmed',
          oranges_annotations: [...DEFAULT_ORANGES_PROMPTS],
        },
      ],
    };

  const ingested = ingestHandback(projectRoot, worktree, {
    dossier,
    ledgerView: {
      scaffolding,
      current_step_id: step_id,
      at,
    },
    job_id: dossier.job_id,
    skip_index: true,
    at,
  });

  return {
    ok: ingested.ok === true,
    skill,
    step_id,
    phase: ingested.ok ? 'complete' : 'ingest',
    propose: { skill, step_id, depth: opts.depth ?? 'LITE' },
    confirm: dossier.confirmation,
    execute: {
      worktree_rel: path.relative(projectRoot, worktree).split(path.sep).join('/'),
      handback_path: path
        .relative(projectRoot, written.handback_path)
        .split(path.sep)
        .join('/'),
      handback_id,
      client_event_id,
    },
    ingest: ingested,
    reflection_receipt: ingested.reflection_receipt ?? null,
    next_stage_proposal: ingested.next_stage_proposal ?? null,
  };
}

/**
 * Criterion 6 multi-skill proof: two DIFFERENT commissionable skills each
 * driven propose → confirm → execute → validated handback → receipt + proposal
 * in ONE campaign. < 2 rows HALTs.
 *
 * @param {string} projectRoot
 * @param {{ root?: string, skills_table?: object, at?: string }} [opts]
 */
export function runMultiSkillProof(projectRoot, opts = {}) {
  const selection = selectMultiSkillProofSkills(opts.skills_table ?? null, {
    root: opts.root ?? DEFAULT_ROOT,
  });
  if (!selection.ok) {
    return {
      schema: MULTI_SKILL_PROOF_SCHEMA,
      ok: false,
      halt: true,
      ...selection,
      results: [],
    };
  }

  const results = [];
  for (let i = 0; i < selection.skills.length; i += 1) {
    const skill = selection.skills[i];
    const driven = driveSkillToValidatedHandback(projectRoot, {
      skill,
      step_id: `w14-s${i + 1}-${skill}`,
      step_name: `${skill} multi-skill stage`,
      skills_table: opts.skills_table,
      root: opts.root,
      at: opts.at ?? '2026-08-03',
      scaffolding: {
        steps: selection.skills.flatMap((sk, j) => [
          {
            step_id: `w14-s${j + 1}-${sk}`,
            name: `${sk} multi-skill stage`,
            done_when: `Validated handback from ${sk}`,
            oranges_annotations: [...DEFAULT_ORANGES_PROMPTS],
          },
        ]).concat([
          {
            step_id: 'w14-campaign-close',
            name: 'Campaign close',
            done_when: 'Both skills reflected',
            oranges_annotations: [...DEFAULT_ORANGES_PROMPTS],
          },
        ]),
      },
    });
    results.push(driven);
    if (!driven.ok) {
      return {
        schema: MULTI_SKILL_PROOF_SCHEMA,
        ok: false,
        halt: false,
        failed_skill: skill,
        skills: selection.skills,
        results,
        message: `Multi-skill proof failed on ${skill}`,
      };
    }
  }

  // Distinct skills + each has receipt and proposal.
  const skillSet = new Set(results.map((r) => r.skill));
  const allEmitted = results.every(
    (r) => r.reflection_receipt && r.next_stage_proposal,
  );

  return {
    schema: MULTI_SKILL_PROOF_SCHEMA,
    ok: skillSet.size >= 2 && allEmitted && results.length >= 2,
    halt: false,
    skills: selection.skills,
    distinct_skill_count: skillSet.size,
    results,
    criterion_6: skillSet.size >= 2 && allEmitted,
    message:
      skillSet.size >= 2 && allEmitted
        ? `Criterion 6 proven: ${[...skillSet].join(' + ')} each reached validated handback → receipt + proposal.`
        : 'Multi-skill proof incomplete.',
  };
}

// ── Golden helpers ─────────────────────────────────────────────────────────

/**
 * Relative golden paths (no host-absolute paths).
 */
export const GOLDEN_REFLECTION_REL = path.join(
  'fixtures',
  'w14-golden',
  'reflection-receipt.golden.json',
);
export const GOLDEN_PROPOSAL_REL = path.join(
  'fixtures',
  'w14-golden',
  'next-stage-proposal.golden.json',
);

/**
 * Load a golden file relative to the skill root.
 * @param {string} rel
 * @param {string} [root]
 */
export function loadGolden(rel, root = DEFAULT_ROOT) {
  const p = path.join(root, rel);
  const raw = fs.readFileSync(p, 'utf8');
  return JSON.parse(raw);
}

/**
 * Canonical fixture inputs for golden pinning (frozen, no wall-clock).
 */
export function goldenEmitterInputs() {
  const handback = {
    schema: 'ecgberht-receipt-v0',
    kind: 'handback',
    as_of: '2026-08-03',
    active_effort: 'Wave 14 golden stage',
    why_next: 'Emit next-stage proposal for stage-b from ledger facts.',
    grasscatch_why: null,
    tool_depth_why: 'LITE golden fixture — zero model.',
    human_wait: 'none',
    uncertainty_flags: ['golden', 'wave-14'],
    skill: 'researchPrime',
    depth: 'LITE',
    commission_id: 'golden-commission-001',
    client_event_id: 'golden-client-evt-001',
    handback_id: 'golden-hb-001',
    step_id: 'stage-a',
    contract_version: CONTRACT_VERSION,
    partial: false,
  };
  const dossier = {
    schema: 'ecgberht-commission-dossier-v0',
    job_id: 'golden-job-001',
    commissioned_as: 'researchPrime:stage-a',
    proposal: {
      skill: 'researchPrime',
      step_id: 'stage-a',
      depth_cell: 'LITE',
    },
    confirmation: {
      skill: 'researchPrime',
      step_id: 'stage-a',
      confirmed: true,
    },
    launch: null,
    handback: {
      handback_id: 'golden-hb-001',
      body: handback,
      at: '2026-08-03T12:00:00.000Z',
    },
    repaired_at_boot: false,
    updated_at: '2026-08-03T12:00:00.000Z',
  };
  const ledgerView = {
    at: '2026-08-03T12:00:00.000Z',
    current_step_id: 'stage-a',
    handback,
    scaffolding: {
      steps: [
        {
          step_id: 'stage-a',
          name: 'Stage A',
          done_when: 'Handback validated',
          oranges_annotations: [
            'What would John ask next about this stage?',
            'What artifact must exist before the stage can close?',
            'What decision, if any, requires a human gate?',
          ],
        },
        {
          step_id: 'stage-b',
          name: 'Stage B',
          done_when: 'Stage B deliverable reviewable',
          oranges_annotations: [
            'What would John ask next about this stage?',
            'What artifact must exist before the stage can close?',
            'What decision, if any, requires a human gate?',
          ],
        },
      ],
    },
  };
  return { handback, dossier, ledgerView };
}
