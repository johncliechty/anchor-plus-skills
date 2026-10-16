/**
 * Wave 9 — Scaffolding authoring: dialogue → step_create, coarse roadmap
 * proposed and batch-confirmed.
 *
 * Production path (not the Wave-2 fixture slice):
 *   typed NL description
 *     → compile (zero-model, Oranges annotations, steward-authored)
 *     → live envelope debit (no live envelope → refuse; Wave-8 law from birth)
 *     → typed scaffold_proposal event through the Wave-6 spine
 *     → ONE hash-bound batch confirm (who stamped claimed_unauthenticated)
 *     → all step_create events under one lock (all-or-none) with steward-authored
 *       provenance on every step
 *
 * Zero chat persistence is structural: only SPINE_EVENT_KINDS are writable.
 * No adversarial review is reachable from the scaffolding compile (zero-model
 * pure function; compile policy freezes adversarial_review:false).
 *
 * T-IDEM-09: double-submit of the same batch client_event_id commits exactly
 * once; ledger bytes are identical to the single-submit result.
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  FACE_FILE_NAME,
  loadProjectSurfaces,
} from './face-strip.mjs';
import {
  appendRoadmapEvent,
  emptyRoadmap,
  loadProjectRoadmap,
  projectRoadmapBytes,
  validateRoadmap,
  ROADMAP_FILE_NAME,
} from './roadmap.mjs';
import {
  appendRoadmapEventThroughSpine,
  roadmapLedgerPath,
  assertEventKindAllowed,
  SPINE_EVENT_KINDS,
  SPINE_CODE,
} from './ledger-spine.mjs';
import {
  debitSessionEnvelope,
  readEnvelopeState,
  ENVELOPE_CODE,
} from './session-envelope.mjs';
import {
  normalizeClaimedWho,
  WHO_PROVENANCE,
} from './identity-policy.mjs';
import { authorize } from './authorize.mjs';

// ── Schemas / policy ───────────────────────────────────────────────────────

/** Production scaffolding proposal schema (live spine — not fixture). */
export const SCAFFOLD_PROPOSAL_SCHEMA = 'ecgberht-scaffold-proposal-v0';

/** Compile policy — frozen for the no-adversarial-review gate. */
export const SCAFFOLD_COMPILE_POLICY = Object.freeze({
  zero_model: true,
  adversarial_review: false,
  model_calls: 0,
  shark: false,
  product_loop_review: false,
  deterministic: true,
});

/**
 * Coarse Oranges annotations attached to each proposed step — anticipatory
 * prompts the steward would surface (criterion 1), not model output.
 */
export const DEFAULT_ORANGES_PROMPTS = Object.freeze([
  'What would John ask next about this stage?',
  'What artifact must exist before the stage can close?',
  'What decision, if any, requires a human gate?',
]);

/** Provenance stamp on every steward-authored scaffolded step. */
export const STEWARD_AUTHORED_PROVENANCE = Object.freeze({
  author: 'steward',
  source: 'scaffold_batch_confirm',
  steward_authored: true,
  visibly_labelled: true,
});

/** Idempotence key name (T-IDEM-09). */
export const SCAFFOLD_IDEMPOTENCE_KEY = 'client_event_id';

// ── Failure states (scaffolding surface — Master-Plan P5 table) ────────────

export const SCAFFOLD_CODE = Object.freeze({
  NO_FACE: 'SCAFFOLD_NO_FACE',
  PROPOSAL_LOST: 'SCAFFOLD_PROPOSAL_LOST',
  PROPOSAL_INVALID: 'SCAFFOLD_PROPOSAL_INVALID',
  CONFIRM_HASH_MISMATCH: 'SCAFFOLD_CONFIRM_HASH_MISMATCH',
  ROADMAP_STORE_UNREADABLE: 'ROADMAP_STORE_UNREADABLE',
  EMPTY: 'SCAFFOLD_EMPTY',
  ROADMAP_STATE_UNKNOWN: 'ROADMAP_STATE_UNKNOWN',
  NO_ENVELOPE: 'ENVELOPE_ABSENT',
  AUTH_REFUSED: 'SCAFFOLD_AUTH_REFUSED',
  WHO_REQUIRED: 'SCAFFOLD_WHO_REQUIRED',
});

export const SCAFFOLD_TEXT = Object.freeze({
  [SCAFFOLD_CODE.NO_FACE]:
    'No project Face yet — describe the project first; the scaffolding anchors to it.',
  [SCAFFOLD_CODE.PROPOSAL_LOST]:
    'The scaffolding proposal did not complete; nothing was written. Ask again.',
  [SCAFFOLD_CODE.PROPOSAL_INVALID]:
    'Proposed scaffolding failed validation — shown for reference, not confirmable.',
  [SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH]:
    'The proposal changed since it was shown — confirm refused; review the current version.',
  [SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE]:
    'Roadmap store unreadable — batch confirm refused rather than partially written.',
  [SCAFFOLD_CODE.EMPTY]:
    "I couldn't derive any stages from that description — tell me more.",
  [SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN]:
    'Existing roadmap health unknown (validate failed) — heal before scaffolding.',
  [SCAFFOLD_CODE.NO_ENVELOPE]:
    'No confirmed session envelope — spend refused; confirm a budget to proceed.',
  [SCAFFOLD_CODE.AUTH_REFUSED]:
    'Credential invalid at confirm time — nothing written.',
  [SCAFFOLD_CODE.WHO_REQUIRED]:
    'Batch confirm is a human decision — pass who (claimed identity).',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function scaffoldFailure(code, extra = {}) {
  const text = SCAFFOLD_TEXT[code] ?? SCAFFOLD_TEXT[SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN];
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    scaffolding: true,
    steps_written: false,
    ...extra,
  };
}

/**
 * Full failure-state table for the scaffolding surface (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function scaffoldFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (no Face to anchor)',
      status_code: SCAFFOLD_CODE.NO_FACE,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.NO_FACE],
    }),
    Object.freeze({
      state: 'dependency-slow-or-killed (compile dies)',
      status_code: SCAFFOLD_CODE.PROPOSAL_LOST,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.PROPOSAL_LOST],
    }),
    Object.freeze({
      state: 'dependency-returns-garbage',
      status_code: SCAFFOLD_CODE.PROPOSAL_INVALID,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.PROPOSAL_INVALID],
    }),
    Object.freeze({
      state: 'confirm-hash-mismatch',
      status_code: SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid (no steps derivable)',
      status_code: SCAFFOLD_CODE.EMPTY,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.EMPTY],
    }),
    Object.freeze({
      state: 'unknown (roadmap state unclear)',
      status_code: SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN,
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN],
    }),
  ]);
}

// ── Hash / compile helpers ─────────────────────────────────────────────────

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
 * Deterministic content hash of a proposal payload (hash-bound confirm).
 * @param {object} payload
 * @returns {string}
 */
export function hashScaffoldPayload(payload) {
  const canonical = JSON.stringify(sortKeys(payload));
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

function nonEmpty(v) {
  return v != null && String(v).trim() !== '';
}

function firstLine(text) {
  const line = String(text).split(/\r?\n/).find((l) => l.trim());
  return line ? line.trim() : null;
}

function slugFromName(name, index) {
  const base = String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return base || `stage-${index + 1}`;
}

function normalizeStages(stages) {
  if (!Array.isArray(stages) || !stages.length) return [];
  const out = [];
  for (let i = 0; i < stages.length; i++) {
    const s = stages[i];
    if (typeof s === 'string' && s.trim()) {
      out.push({ name: s.trim() });
      continue;
    }
    if (s && typeof s === 'object' && nonEmpty(s.name)) {
      out.push({
        step_id: s.step_id ?? s.id ?? undefined,
        name: String(s.name).trim(),
        done_when: s.done_when ?? s.doneWhen ?? undefined,
        oranges: s.oranges ?? s.oranges_annotations,
        step_type: s.step_type ?? s.type ?? undefined,
      });
    }
  }
  return out;
}

/**
 * Best-effort deterministic stage parse from prose:
 * lines matching "Stage: X", "N. X", or "- X".
 * @param {string} prose
 */
function parseStagesFromProse(prose) {
  const lines = String(prose).split(/\r?\n/);
  const out = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const m =
      line.match(/^stage\s*[:\-]\s*(.+)$/i) ||
      line.match(/^\d+[.)]\s+(.+)$/) ||
      line.match(/^[-*]\s+(.+)$/);
    if (m && m[1].trim()) {
      out.push({ name: m[1].trim() });
    }
  }
  return out;
}

/**
 * Candidate stages from DICTATED prose — the shape a person actually speaks.
 *
 * WHY (2026-08-04). parseStagesFromProse only recognises a LIST: "Stage: x", "1. x",
 * "- x". Dictation does not arrive as a list; it arrives as "I want to build a syllabus,
 * develop case studies, create assessments, and pilot it with a small cohort". Against
 * that, the compiler answered SCAFFOLD_EMPTY — which is how the steward's headline
 * capability looked broken to its first real user.
 *
 * DETERMINISTIC AND ZERO-MODEL, like everything on this path. List markers win when
 * present; otherwise the text is split into enumerated clauses and only clauses that
 * OPEN WITH AN ACTION are kept, so narration ("this project is about teaching an MBA
 * course") does not become a stage while "build a syllabus" does.
 *
 * This DERIVES candidates for a human to see and confirm — it never writes. The steward
 * still invents nothing: when no action clause is found the caller gets an empty list
 * and must ASK, rather than manufacturing a plan.
 *
 * @param {string} prose
 * @returns {Array<{name: string}>}
 */
export function deriveStagesFromDictation(prose) {
  const text = String(prose ?? '').trim();
  if (!text) return [];

  const listed = parseStagesFromProse(text);
  if (listed.length) return listed;

  // Verbs that open a piece of WORK. Deliberately a small closed list: it is
  // auditable, and a wrong guess costs the user one confirm, never a write.
  const ACTION =
    /^(?:then\s+|also\s+|finally\s+|next\s+)?(?:i\s+(?:want|need|plan)\s+to\s+|we\s+(?:want|need|plan)\s+to\s+|to\s+)?(build|develop|create|design|write|draft|pilot|test|launch|run|deliver|produce|prepare|assemble|review|research|analyse|analyze|evaluate|validate|ship|publish|teach|record|gather|collect|define|scope|plan|refine|implement|integrate|migrate|document)\b/i;

  const clauses = text
    .split(/(?:[.;\n]|,\s*(?:and\s+)?|\s+and\s+then\s+|\s+then\s+)/i)
    .map((c) => c.trim())
    .filter(Boolean);

  const seen = new Set();
  const out = [];
  for (const clause of clauses) {
    if (!ACTION.test(clause)) continue;
    const name = clause
      .replace(/^(?:then|also|finally|next)\s+/i, '')
      .replace(/^(?:i|we)\s+(?:want|need|plan)\s+to\s+/i, '')
      .replace(/^to\s+/i, '')
      .trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ name: name.charAt(0).toUpperCase() + name.slice(1) });
  }
  return out;
}

/**
 * Pure, zero-model compile of a typed NL / structured description into a
 * scaffolding proposal body (no I/O, no debit, no spine write).
 *
 * Accepts either:
 * - `{ goal, stages: string[] | {name, done_when?}[] }` (preferred typed form)
 * - `{ description: string }` free-form with lines like "Stage: …" or "1. …"
 *
 * @param {object} input
 * @returns {{ ok: true, proposal: object } | { ok: false, code: string, message: string }}
 */
export function compileScaffoldDescription(input = {}) {
  // Zero-model pure path — never reaches adversarial review.
  if (SCAFFOLD_COMPILE_POLICY.adversarial_review !== false) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'compile-policy-violated',
    });
  }

  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'description_not_object',
    });
  }

  const goal =
    nonEmpty(input.goal) ? String(input.goal).trim()
    : nonEmpty(input.description) ? firstLine(String(input.description))
    : null;

  if (!goal) {
    return scaffoldFailure(SCAFFOLD_CODE.EMPTY, {
      error: 'goal_missing',
    });
  }

  let stages = normalizeStages(input.stages);
  if (!stages.length && nonEmpty(input.description)) {
    // Dictation is not a list. deriveStagesFromDictation falls back to enumerated
    // ACTION clauses when no list marker is present, so a spoken description
    // compiles instead of answering SCAFFOLD_EMPTY (2026-08-04).
    stages = deriveStagesFromDictation(String(input.description));
  }
  if (!stages.length) {
    return scaffoldFailure(SCAFFOLD_CODE.EMPTY, {
      error: 'stages_missing',
    });
  }

  const steps = stages.map((s, i) => {
    const step_id = s.step_id ?? slugFromName(s.name, i);
    const name = s.name;
    const done_when = s.done_when ?? `Stage '${name}' meets its done-when.`;
    const oranges = Array.isArray(s.oranges) && s.oranges.length
      ? s.oranges.map(String)
      : [...DEFAULT_ORANGES_PROMPTS];
    return {
      step_id,
      name,
      status: 'proposed',
      done_when,
      oranges_annotations: oranges,
      order: i + 1,
      steward_authored: true,
      visibly_labelled: true,
      ...(s.step_type ? { step_type: s.step_type } : {}),
    };
  });

  // Hash input: rendered proposal content John sees (excludes proposal_id/hash).
  const hashBody = {
    schema: SCAFFOLD_PROPOSAL_SCHEMA,
    kind: 'scaffold_proposal',
    goal,
    steps,
    oranges: {
      law: 'anticipatory-prompts-zero-model',
      per_step: true,
      default_prompts: [...DEFAULT_ORANGES_PROMPTS],
    },
    requires_batch_confirm: true,
    confirmed: false,
    zero_model: true,
    steward_authored: true,
    adversarial_review: false,
  };
  const proposal_hash = hashScaffoldPayload(hashBody);
  const proposal = {
    ...hashBody,
    proposal_hash,
    proposal_id: `scaffold-${proposal_hash.slice(0, 12)}`,
    compile_policy: { ...SCAFFOLD_COMPILE_POLICY },
  };

  return { ok: true, proposal };
}

/**
 * Validate a proposal object is confirmable (not garbage).
 * @param {object} proposal
 * @returns {{ ok: true } | ReturnType<typeof scaffoldFailure>}
 */
export function validateScaffoldProposal(proposal) {
  if (!proposal || typeof proposal !== 'object' || Array.isArray(proposal)) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'proposal_not_object',
    });
  }
  if (proposal.kind !== 'scaffold_proposal' && proposal.kind !== 'scaffolding_proposal') {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'proposal_wrong_kind',
    });
  }
  if (!Array.isArray(proposal.steps) || proposal.steps.length === 0) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'proposal_no_steps',
    });
  }
  for (const s of proposal.steps) {
    if (!s || !nonEmpty(s.step_id) || !nonEmpty(s.name)) {
      return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
        error: 'proposal_step_invalid',
      });
    }
    if (!Array.isArray(s.oranges_annotations) || s.oranges_annotations.length === 0) {
      return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
        error: 'proposal_oranges_missing',
      });
    }
  }
  const recomputed = recomputeProposalHash(proposal);
  if (proposal.proposal_hash && proposal.proposal_hash !== recomputed) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
      error: 'proposal_hash_corrupt',
      expected_hash: recomputed,
      provided_hash: proposal.proposal_hash,
    });
  }
  return { ok: true };
}

/**
 * Recompute the content hash of a rendered proposal (post-render TOCTOU guard).
 * @param {object} proposal
 * @returns {string}
 */
export function recomputeProposalHash(proposal) {
  const hashBody = {
    schema: proposal.schema ?? SCAFFOLD_PROPOSAL_SCHEMA,
    kind: 'scaffold_proposal',
    goal: proposal.goal,
    steps: (proposal.steps ?? []).map((s) => ({
      step_id: s.step_id,
      name: s.name,
      status: s.status ?? 'proposed',
      done_when: s.done_when,
      oranges_annotations: s.oranges_annotations,
      order: s.order,
      steward_authored: s.steward_authored !== false,
      visibly_labelled: s.visibly_labelled !== false,
      ...(s.step_type ? { step_type: s.step_type } : {}),
    })),
    oranges: proposal.oranges ?? {
      law: 'anticipatory-prompts-zero-model',
      per_step: true,
      default_prompts: [...DEFAULT_ORANGES_PROMPTS],
    },
    requires_batch_confirm: true,
    confirmed: false,
    zero_model: true,
    steward_authored: true,
    adversarial_review: false,
  };
  return hashScaffoldPayload(hashBody);
}

// ── Preflight helpers ──────────────────────────────────────────────────────

/**
 * Require a project Face (scaffolding anchors to it).
 * @param {string} projectPath
 */
export function requireProjectFace(projectPath) {
  const root = path.resolve(projectPath);
  const facePath = path.join(root, FACE_FILE_NAME);
  if (!fs.existsSync(facePath) || !fs.statSync(facePath).isFile()) {
    return scaffoldFailure(SCAFFOLD_CODE.NO_FACE, {
      error: 'dependency-missing',
      face_path: facePath,
    });
  }
  return { ok: true, face_path: facePath, project_path: root };
}

/**
 * Check existing roadmap health. Missing file is fine (fresh project).
 * Unreadable → ROADMAP_STORE_UNREADABLE; validate fail → ROADMAP_STATE_UNKNOWN.
 * @param {string} projectPath
 */
export function checkRoadmapHealth(projectPath) {
  const loaded = loadProjectRoadmap(projectPath);
  if (!loaded.ok && loaded.exists) {
    return scaffoldFailure(SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: loaded.message ?? loaded.error,
    });
  }
  if (!loaded.exists) {
    return {
      ok: true,
      exists: false,
      roadmap: emptyRoadmap(null),
      roadmap_path: loaded.roadmap_path,
    };
  }
  const validated = validateRoadmap(loaded.roadmap);
  if (!validated.ok) {
    return scaffoldFailure(SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN, {
      error: 'roadmap-validate-failed',
      detail: validated.message ?? validated.error,
      validation: validated,
    });
  }
  return {
    ok: true,
    exists: true,
    roadmap: loaded.roadmap,
    roadmap_path: loaded.roadmap_path,
    validated,
  };
}

/**
 * Source-removal proof: scaffolding module must not reach adversarial review.
 * @param {string} sourceText
 */
export function assertNoAdversarialReviewReachable(sourceText) {
  const forbidden = [
    /from\s+['"].*gandalf/i,
    /from\s+['"].*shark/i,
    /adversarialReview\s*\(/,
    /runShark\s*\(/,
    /invokeGandalf\s*\(/,
    /product_loop_review\s*:\s*true/,
    /adversarial_review\s*:\s*true/,
  ];
  const hits = [];
  for (const re of forbidden) {
    if (re.test(sourceText)) hits.push(re.source);
  }
  // Positive: policy freezes adversarial_review:false
  const hasPolicy =
    /adversarial_review\s*:\s*false/.test(sourceText) &&
    /zero_model\s*:\s*true/.test(sourceText);
  return {
    ok: hits.length === 0 && hasPolicy,
    hits,
    hasPolicy,
    adversarial_review: false,
  };
}

/**
 * Zero-chat structural proof: chat-shaped kinds refuse on the spine allow-list.
 * @returns {{ ok: boolean, refused: string[], admitted: readonly string[] }}
 */
export function assertZeroChatPersistenceStructural() {
  const chatKinds = ['chat_turn', 'chat', 'utterance', 'transcript', 'dialogue_turn'];
  const refused = [];
  for (const k of chatKinds) {
    const gate = assertEventKindAllowed(k);
    if (!gate.ok) refused.push(k);
  }
  return {
    ok: refused.length === chatKinds.length && !SPINE_EVENT_KINDS.some((k) =>
      /chat|utterance|transcript|dialogue/i.test(k),
    ),
    refused,
    admitted: SPINE_EVENT_KINDS,
    kinds_refused_code: SPINE_CODE.KIND_REFUSED,
  };
}

// ── Propose (compile + debit + scaffold_proposal) ──────────────────────────

/**
 * Compile a spoken/typed description inside a live envelope and emit a
 * PROPOSED scaffolding as a typed scaffold_proposal event through the spine.
 * Does NOT write step_create events (roadmap projection stays empty of new steps).
 *
 * @param {string} projectPath
 * @param {{
 *   description?: object|string,
 *   goal?: string,
 *   stages?: Array,
 *   client_event_id?: string,
 *   auth?: object,
 *   tokens?: number,
 *   monoNow?: () => number,
 *   wallNow?: () => string|number,
 *   at?: string,
 *   project_id?: string,
 *   skip_index?: boolean,
 * }} [opts]
 */
export function proposeScaffolding(projectPath, opts = {}) {
  try {
    return proposeScaffoldingInner(projectPath, opts);
  } catch (e) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
      error: 'compile-died',
      detail: String(e?.message ?? e),
    });
  }
}

function proposeScaffoldingInner(projectPath, opts = {}) {
  const face = requireProjectFace(projectPath);
  if (!face.ok) return face;

  const health = checkRoadmapHealth(projectPath);
  if (!health.ok) return health;

  // Wave-8 law from birth: no live envelope → refuse (do not queue scaffold compile).
  const envState = readEnvelopeState(projectPath, {
    monoNow: opts.monoNow,
    wallNow: opts.wallNow,
  });
  if (!envState.ok || !envState.live) {
    const code =
      envState.code === ENVELOPE_CODE.EXHAUSTED ? ENVELOPE_CODE.EXHAUSTED
      : envState.code === ENVELOPE_CODE.EXPIRED ? ENVELOPE_CODE.EXPIRED
      : SCAFFOLD_CODE.NO_ENVELOPE;
    return scaffoldFailure(code, {
      error: 'no-live-envelope',
      envelope: envState,
      text: SCAFFOLD_TEXT[SCAFFOLD_CODE.NO_ENVELOPE],
      message: SCAFFOLD_TEXT[SCAFFOLD_CODE.NO_ENVELOPE],
      user_text: SCAFFOLD_TEXT[SCAFFOLD_CODE.NO_ENVELOPE],
    });
  }

  // Build typed input
  let input = opts.description;
  if (typeof input === 'string') {
    input = { description: input, goal: opts.goal, stages: opts.stages };
  } else if (!input || typeof input !== 'object') {
    input = {
      goal: opts.goal,
      stages: opts.stages,
      description: opts.description,
    };
  } else {
    input = {
      ...input,
      goal: input.goal ?? opts.goal,
      stages: input.stages ?? opts.stages,
    };
  }

  const compiled = compileScaffoldDescription(input);
  if (!compiled.ok) return compiled;

  const proposal = compiled.proposal;
  const validated = validateScaffoldProposal(proposal);
  if (!validated.ok) return validated;

  // Debit live envelope (shown). Compile text is the goal + stage names.
  const compileText = [
    proposal.goal,
    ...proposal.steps.map((s) => s.name),
  ].join('\n');
  const debit = debitSessionEnvelope(projectPath, {
    kind: 'compile',
    text: compileText,
    // When the caller KNOWS the real token count (the conversational path gets it back
    // from the seat), price on that instead of the text estimate. The rate stays the
    // synthetic accounting rate — this grounds the token input, it does not import
    // vendor billing (see COST_MODEL_DISCLAIMER).
    ...(Number.isFinite(Number(opts.tokens)) && Number(opts.tokens) > 0
      ? { tokens: Number(opts.tokens) }
      : {}),
    // Measured spend wins over the synthetic estimate when the caller has it.
    ...(Number.isFinite(Number(opts.cost_usd)) && Number(opts.cost_usd) >= 0
      ? { cost_usd: Number(opts.cost_usd) }
      : {}),
    auth: opts.auth,
    monoNow: opts.monoNow,
    wallNow: opts.wallNow,
    client_event_id: opts.debit_client_event_id,
  });
  if (!debit.ok) {
    // Map envelope absences to the scaffolding surface; preserve exhausted/expired.
    if (debit.code === ENVELOPE_CODE.ABSENT || debit.code === ENVELOPE_CODE.NONE_YET) {
      return scaffoldFailure(SCAFFOLD_CODE.NO_ENVELOPE, {
        error: 'envelope-debit-refused',
        debit,
      });
    }
    return {
      ...debit,
      scaffolding: true,
      steps_written: false,
      message: debit.message ?? debit.text,
    };
  }

  // Emit typed scaffold_proposal through the spine — no step_create yet.
  const client_event_id =
    opts.client_event_id ??
    `scaffold-propose-${proposal.proposal_hash.slice(0, 16)}`;

  const event = {
    kind: 'scaffold_proposal',
    schema: SCAFFOLD_PROPOSAL_SCHEMA,
    client_event_id,
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    goal: proposal.goal,
    steps: proposal.steps,
    oranges: proposal.oranges,
    requires_batch_confirm: true,
    confirmed: false,
    zero_model: true,
    steward_authored: true,
    adversarial_review: false,
    compile_policy: { ...SCAFFOLD_COMPILE_POLICY },
    envelope_id: debit.envelope_id ?? debit.envelope?.envelope_id ?? null,
    debit_shown: debit.shown ?? null,
    at: opts.at,
  };

  const spine = appendRoadmapEventThroughSpine(projectPath, event, {
    project_id: opts.project_id,
    skip_index: opts.skip_index !== false ? opts.skip_index ?? true : false,
    at: opts.at,
  });

  if (!spine.ok) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
      error: 'spine-append-failed',
      spine,
      debit,
      // Compile was debited; proposal not durable — honest lost.
    });
  }

  // Projection must not gain steps from scaffold_proposal alone.
  const projectionLen = Array.isArray(spine.projection) ? spine.projection.length : 0;
  const priorProjectionLen = Array.isArray(health.roadmap?.roadmap_projection)
    ? health.roadmap.roadmap_projection.length
    : 0;

  return {
    ok: true,
    spelling: 'Ecgberht',
    phase: 'proposed',
    proposal,
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    event: spine.event,
    seq: spine.seq,
    roadmap: spine.roadmap,
    projection: spine.projection,
    steps_written: false,
    projection_steps_unchanged: projectionLen === priorProjectionLen,
    steward_authored: true,
    zero_model: true,
    adversarial_review: false,
    compile_policy: { ...SCAFFOLD_COMPILE_POLICY },
    debit: {
      ok: true,
      debited: true,
      shown: debit.shown,
      cost_usd: debit.shown?.cost_usd ?? debit.pricing?.cost_usd,
      envelope_id: debit.envelope_id ?? debit.envelope?.envelope_id,
      pricing: debit.pricing,
    },
    shown: debit.shown,
    spine: true,
    idempotent: spine.idempotent === true,
    message:
      'Scaffolding proposed as typed scaffold_proposal (steward-authored); compile shown and debited; no roadmap steps written.',
  };
}

// ── Batch confirm (hash-bound, atomic step_create) ─────────────────────────

/**
 * Find the latest open (unconfirmed) scaffold_proposal on the roadmap, or one
 * matching proposal_id / proposal_hash.
 * @param {object} roadmap
 * @param {{ proposal_id?: string, proposal_hash?: string }} [opts]
 */
export function findOpenScaffoldProposal(roadmap, opts = {}) {
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  const proposals = events.filter((e) => e && e.kind === 'scaffold_proposal');
  if (!proposals.length) return null;

  // Already-confirmed hashes: any step_create carrying matching proposal_hash.
  const confirmedHashes = new Set();
  for (const e of events) {
    if (e?.kind === 'step_create' && e.scaffold_proposal_hash) {
      confirmedHashes.add(e.scaffold_proposal_hash);
    }
    if (e?.kind === 'step_create' && e.provenance?.proposal_hash) {
      confirmedHashes.add(e.provenance.proposal_hash);
    }
  }

  let candidates = proposals;
  if (opts.proposal_id) {
    candidates = candidates.filter((p) => p.proposal_id === opts.proposal_id);
  }
  if (opts.proposal_hash) {
    candidates = candidates.filter((p) => p.proposal_hash === opts.proposal_hash);
  }

  // Prefer newest open proposal
  for (let i = candidates.length - 1; i >= 0; i--) {
    const p = candidates[i];
    if (p.confirmed === true) continue;
    if (confirmedHashes.has(p.proposal_hash)) continue;
    return p;
  }
  // Fall back to newest matching even if confirmed (for already-confirmed path)
  return candidates[candidates.length - 1] ?? null;
}

/**
 * Whether a batch client_event_id already committed steps.
 * @param {object} roadmap
 * @param {string} clientEventId
 */
export function findBatchConfirmByClientId(roadmap, clientEventId) {
  if (!clientEventId) return null;
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  const steps = events.filter(
    (e) =>
      e?.kind === 'step_create' &&
      (e.batch_client_event_id === clientEventId ||
        e.client_event_id === clientEventId ||
        (typeof e.client_event_id === 'string' &&
          e.client_event_id.startsWith(`${clientEventId}#`))),
  );
  if (!steps.length) return null;
  return {
    client_event_id: clientEventId,
    step_ids: steps.map((s) => s.step_id),
    steps,
    proposal_hash: steps[0].scaffold_proposal_hash ?? steps[0].provenance?.proposal_hash,
    who: steps[0].who ?? null,
  };
}

/**
 * ONE batch confirmation binds the whole scaffolding. Hash-bound to the
 * rendered proposal content; who recorded; atomic all-steps-or-none through
 * the spine lock.
 *
 * @param {string} projectPath
 * @param {{
 *   proposal_hash: string,
 *   who: string|object,
 *   proposal?: object,
 *   proposal_id?: string,
 *   client_event_id?: string,
 *   auth?: object,
 *   at?: string,
 *   project_id?: string,
 * }} opts
 */
export function batchConfirmScaffolding(projectPath, opts = {}) {
  try {
    return batchConfirmScaffoldingInner(projectPath, opts);
  } catch (e) {
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
      error: 'confirm-died',
      detail: String(e?.message ?? e),
    });
  }
}

function batchConfirmScaffoldingInner(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const face = requireProjectFace(root);
  if (!face.ok) return face;

  const who = normalizeClaimedWho(opts.who);
  if (!who) {
    return scaffoldFailure(SCAFFOLD_CODE.WHO_REQUIRED, {
      error: 'who-required',
    });
  }

  // Auth at confirm seam (NS criterion 9) when auth ctx supplied.
  if (opts.auth != null) {
    const decision = authorize('confirm', opts.auth);
    if (!decision || decision.ok !== true) {
      return scaffoldFailure(SCAFFOLD_CODE.AUTH_REFUSED, {
        error: 'auth-refused',
        auth: decision ?? { ok: false },
      });
    }
  }

  const providedHash = opts.proposal_hash ?? opts.proposal?.proposal_hash;
  if (!providedHash || typeof providedHash !== 'string') {
    return scaffoldFailure(SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH, {
      error: 'confirm-hash-missing',
      provided_hash: providedHash ?? null,
    });
  }

  const client_event_id =
    opts.client_event_id ??
    `scaffold-confirm-${providedHash.slice(0, 16)}`;

  const ledgerPath = roadmapLedgerPath(root);
  const timeoutMs = opts.timeoutMs ?? LOCK_TIMEOUT_MS;

  let lockedResult;
  try {
    lockedResult = withFileLock(
      ledgerPath,
      () => {
        // LOAD under lock
        const loaded = loadProjectRoadmap(root);
        if (!loaded.ok && loaded.exists) {
          return scaffoldFailure(SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE, {
            error: 'backing-store-unreadable',
            detail: loaded.message ?? loaded.error,
          });
        }

        let base = loaded.exists
          ? loaded.roadmap
          : emptyRoadmap(opts.project_id ?? null);

        // Validate health under lock
        if (loaded.exists) {
          const validated = validateRoadmap(base);
          if (!validated.ok) {
            return scaffoldFailure(SCAFFOLD_CODE.ROADMAP_STATE_UNKNOWN, {
              error: 'roadmap-validate-failed',
              detail: validated.message ?? validated.error,
            });
          }
        }

        // T-IDEM-09: same client_event_id already committed → already-confirmed
        const prior = findBatchConfirmByClientId(base, client_event_id);
        if (prior) {
          return {
            ok: true,
            already_confirmed: true,
            idempotent: true,
            client_event_id,
            proposal_hash: prior.proposal_hash ?? providedHash,
            step_ids: prior.step_ids,
            who: prior.who ?? who,
            steps_written: false,
            roadmap: base,
            projection: base.roadmap_projection ?? [],
            message: 'already-confirmed',
            status: 'already-confirmed',
          };
        }

        // Resolve open proposal from ledger (or caller-supplied body for hash check)
        const open = findOpenScaffoldProposal(base, {
          proposal_id: opts.proposal_id,
          proposal_hash: providedHash,
        });

        const proposalSource = opts.proposal && opts.proposal.steps
          ? opts.proposal
          : open;

        if (!proposalSource) {
          return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
            error: 'no-open-proposal',
          });
        }

        // Already confirmed by proposal_hash (different client_event_id)
        const events = base.roadmap_events ?? [];
        const stepsForHash = events.filter(
          (e) =>
            e?.kind === 'step_create' &&
            (e.scaffold_proposal_hash === providedHash ||
              e.provenance?.proposal_hash === providedHash),
        );
        if (stepsForHash.length > 0) {
          return {
            ok: true,
            already_confirmed: true,
            idempotent: true,
            client_event_id,
            proposal_hash: providedHash,
            step_ids: stepsForHash.map((s) => s.step_id),
            who: stepsForHash[0].who ?? who,
            steps_written: false,
            roadmap: base,
            projection: base.roadmap_projection ?? [],
            message: 'already-confirmed',
            status: 'already-confirmed',
          };
        }

        // Hash-bound: recompute from current rendered content
        const expectedHash = recomputeProposalHash(proposalSource);
        if (providedHash !== expectedHash) {
          return scaffoldFailure(SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH, {
            error: 'confirm-hash-mismatch',
            expected_hash: expectedHash,
            provided_hash: providedHash,
          });
        }

        // Also require the open ledger event's hash matches when present
        if (open && open.proposal_hash && open.proposal_hash !== providedHash) {
          return scaffoldFailure(SCAFFOLD_CODE.CONFIRM_HASH_MISMATCH, {
            error: 'confirm-hash-mismatch-ledger',
            expected_hash: open.proposal_hash,
            provided_hash: providedHash,
          });
        }

        const steps = proposalSource.steps;
        if (!Array.isArray(steps) || steps.length === 0) {
          return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_INVALID, {
            error: 'proposal_no_steps',
          });
        }

        // Atomic multi-append: pure law in memory, one write at end.
        let current = base;
        const appended = [];
        const at = opts.at ?? new Date().toISOString().slice(0, 10);
        const proposal_id =
          proposalSource.proposal_id ??
          open?.proposal_id ??
          `scaffold-${expectedHash.slice(0, 12)}`;

        for (const s of steps) {
          const stepEvent = {
            kind: 'step_create',
            step_id: s.step_id,
            name: s.name,
            status: 'proposed',
            done_when: s.done_when ?? null,
            oranges_annotations: Array.isArray(s.oranges_annotations)
              ? [...s.oranges_annotations]
              : [...DEFAULT_ORANGES_PROMPTS],
            steward_authored: true,
            visibly_labelled: true,
            provenance: {
              ...STEWARD_AUTHORED_PROVENANCE,
              proposal_id,
              proposal_hash: expectedHash,
            },
            who,
            who_provenance: WHO_PROVENANCE,
            scaffold_proposal_id: proposal_id,
            scaffold_proposal_hash: expectedHash,
            batch_client_event_id: client_event_id,
            client_event_id: `${client_event_id}#${s.step_id}`,
            at,
            ...(s.step_type ? { step_type: s.step_type } : {}),
          };

          const law = appendRoadmapEvent(current, stepEvent, { at });
          if (!law.ok) {
            // All-or-none: refuse without writing any of this batch
            return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
              error: law.error ?? 'step-create-failed',
              failed_step_id: s.step_id,
              pure: law,
              steps_written: false,
            });
          }
          current = law.roadmap;
          appended.push(law.event);
        }

        // Persist once under the same lock (atomicity)
        fs.mkdirSync(root, { recursive: true });
        writeFileAtomicSync(ledgerPath, projectRoadmapBytes(current));

        return {
          ok: true,
          already_confirmed: false,
          idempotent: false,
          client_event_id,
          proposal_id,
          proposal_hash: expectedHash,
          who,
          step_ids: appended.map((e) => e.step_id),
          events: appended,
          steps_written: true,
          roadmap: current,
          projection: current.roadmap_projection ?? [],
          spine: true,
          atomic: true,
          steward_authored: true,
          message:
            'Batch confirmation committed all scaffold steps through the spine (who recorded; steward-authored).',
        };
      },
      {
        timeoutMs,
        onTimeout: (info) => {
          const err = new Error(SCAFFOLD_TEXT[SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE]);
          err.code = 'ELOCKTIMEOUT';
          err.scaffold_info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if (e && (e.code === 'ELOCKTIMEOUT' || e.code === SPINE_CODE.LOCK_TIMEOUT)) {
      return scaffoldFailure(SCAFFOLD_CODE.ROADMAP_STORE_UNREADABLE, {
        error: 'lock-contended',
      });
    }
    return scaffoldFailure(SCAFFOLD_CODE.PROPOSAL_LOST, {
      error: 'confirm-lock-failed',
      detail: String(e?.message ?? e),
    });
  }

  return lockedResult;
}

/**
 * End-to-end helper: propose then batch-confirm (tests / T-HOST-0 shape).
 * @param {string} projectPath
 * @param {object} opts
 */
export function describeAndConfirmScaffolding(projectPath, opts = {}) {
  const proposed = proposeScaffolding(projectPath, opts);
  if (!proposed.ok) return { ...proposed, phase: 'propose' };

  const confirmed = batchConfirmScaffolding(projectPath, {
    proposal_hash: proposed.proposal_hash,
    proposal: proposed.proposal,
    proposal_id: proposed.proposal_id,
    who: opts.who ?? 'john',
    client_event_id: opts.confirm_client_event_id ?? opts.client_event_id,
    auth: opts.auth,
    at: opts.at,
    project_id: opts.project_id,
  });
  if (!confirmed.ok) {
    return { ...confirmed, phase: 'confirm', proposal: proposed.proposal, debit: proposed.debit };
  }
  return {
    ok: true,
    phase: 'complete',
    proposal: proposed.proposal,
    proposal_hash: proposed.proposal_hash,
    debit: proposed.debit,
    confirmation: confirmed,
    step_ids: confirmed.step_ids,
    who: confirmed.who,
    roadmap: confirmed.roadmap,
    projection: confirmed.projection,
    steward_authored: true,
    zero_chat: true,
  };
}

/**
 * Scan stores for chat-shaped kinds after a scaffolding session.
 * @param {object} roadmap
 */
export function scanForChatTurns(roadmap) {
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  const chat = events.filter((e) => {
    const k = String(e?.kind ?? '');
    return /chat|utterance|transcript|dialogue_turn/i.test(k);
  });
  return {
    ok: chat.length === 0,
    chat_count: chat.length,
    chat_kinds: chat.map((e) => e.kind),
    event_kinds: events.map((e) => e.kind),
    reconstructable_from_typed_events: chat.length === 0,
  };
}

/**
 * Ledger bytes for T-IDEM-09 byte-identity checks.
 * @param {string} projectPath
 * @returns {string|null}
 */
export function readRoadmapLedgerBytes(projectPath) {
  const p = path.join(path.resolve(projectPath), ROADMAP_FILE_NAME);
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p, 'utf8');
}

export {
  FACE_FILE_NAME,
  ROADMAP_FILE_NAME,
  loadProjectSurfaces,
  SPINE_EVENT_KINDS,
};
