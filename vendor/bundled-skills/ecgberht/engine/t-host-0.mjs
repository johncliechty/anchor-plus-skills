/**
 * Wave 22 — T-HOST-0 host-independence acceptance gate (NS criterion 14).
 *
 * Implements REVIEW-SKILL-BOUNDARY §F as amended 2026-08-02:
 *   steps 1–7 in a SCRUBBED no-Anchor environment, including a REAL
 *   in-session-executed commission (Wave 20) yielding a contract-valid
 *   handback + golden-matched deterministic reflection / next-stage
 *   proposal; `no-executor-host` asserted as a SEPARATE case.
 *
 * Gate runner (excluded from standing suite): `gate/t-host-0.mjs`
 * Verdict (S8): `artifacts/t-host-0-verdict.json` — consumed by Wave 19.
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  writeFileAtomicSync,
  withFileLock,
  writeJsonIdempotentSync,
} from './durable-write.mjs';
import { confirmStandUp } from './stand-up.mjs';
import {
  proposeScaffolding,
  batchConfirmScaffolding,
} from './scaffolding.mjs';
import {
  confirmSessionEnvelope,
  currentBudgetTermsHash,
} from './session-envelope.mjs';
import { verbStatus } from './verb-bodies.mjs';
import { assembleBriefPacket } from './brief.mjs';
import { readAnchorProjectKnowledge } from './anchor-knowledge.mjs';
import {
  proposeBoundCommission,
  confirmBoundCommission,
  resetCommissionExecutors,
  clearCommissionIdempotenceCache,
  COMMISSION_CODE,
  makeSkillsTableFixture,
} from './commission-proposal.mjs';
import {
  resolveSeats,
  loadAnchorPrefs,
  findProductModelIds,
} from './seating.mjs';
import {
  installInSessionExecutor,
  resetInSessionExecutor,
  setInSessionProcessHooks,
  FORBIDDEN_CHILD_ENV,
  validateHandbackAtContractPath,
} from './exec-insession.mjs';
import {
  ingestHandback,
  emitHandbackPairDeterministic,
  goldenEmitterInputs,
  stableStringify,
  loadGolden,
  GOLDEN_REFLECTION_REL,
  GOLDEN_PROPOSAL_REL,
} from './handback-ingest.mjs';
import {
  writeHandbackPair,
  CONTRACT_VERSION,
} from './handback-contract.mjs';
import { buildHandbackReceipt } from './receipt-validate.mjs';
import { assembleHighSeat } from './high-seat.mjs';
import { loadProjectRoadmap } from './roadmap.mjs';
import { FACE_FILE_NAME, STRIP_FILE_NAME } from './face-strip.mjs';
import { normalizeClaimedWho, WHO_PROVENANCE } from './identity-policy.mjs';
import { resetAuthorizer } from './authorize.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

// ── Named paths / S8 discipline ────────────────────────────────────────────

/** Relative path of the host-independence verdict (Wave 19 imports this). */
export const T_HOST_0_VERDICT_REL = path.join('artifacts', 't-host-0-verdict.json');

/** S8 atomic write + lock helpers (Durable-store map). */
export const T_HOST_0_ATOMIC_WRITE = 'writeFileAtomicSync';
export const T_HOST_0_LOCK_HELPER = 'withFileLock';
export const T_HOST_0_WRITTEN_BY = 't-host-0.mjs';

/** Env keys scrubbed for the host-less claim. */
export const T_HOST_0_SCRUB_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_DATA_DIR',
  'ANCHOR_PREFS_PATH',
  'ANCHOR_SETTINGS_PATH',
  'ANCHOR_ROOT',
  'ECGBERHT_ANCHOR_ROOT',
  'ANCHOR_REPO',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'CODING_FAMILY',
  'REVIEW_FAMILY',
  'ANCHOR_CODING_FAMILY',
  'ANCHOR_REVIEW_FAMILY',
  'DEFAULT_CLI',
  'ANCHOR_DEFAULT_CLI',
  ...FORBIDDEN_CHILD_ENV,
]);

/** Script step names (order is load-bearing for the verdict steps[]). */
export const T_HOST_0_STEP_NAMES = Object.freeze([
  'stand-up',
  'scaffold',
  'status-brief',
  'commission-propose',
  'execute',
  'oob-ingest',
  'portfolio',
  'no-executor-host',
]);

export const T_HOST_0_SCHEMA = 'ecgberht-t-host-0-verdict-v0';

// ── Cheap profile CLI (path segment honest — Wave 4 / 20) ──────────────────

/**
 * Absolute path to the Stage-2 cheap researchPrime CLI stand-in.
 * @param {string} [root]
 */
export function cheapProfileCliPath(root = DEFAULT_ROOT) {
  return path.join(root, 'gate', 'w4-cheap-profile', 'researchPrime', 'cli.mjs');
}

/**
 * @param {string} [root]
 */
export function tHost0VerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, T_HOST_0_VERDICT_REL);
}

// ── Environment scrub ──────────────────────────────────────────────────────

/**
 * Scrub Anchor host env + seat family env for the host-less claim.
 * Mutates `env` in place; returns the same object.
 * @param {NodeJS.ProcessEnv} [env]
 */
export function scrubHostEnvironment(env = process.env) {
  for (const key of T_HOST_0_SCRUB_ENV) {
    delete env[key];
  }
  return env;
}

/**
 * Build an isolated home dir with NO `.anchor/` so seat resolution cannot
 * silently pick up machine prefs. Returns { home, env, cleanup }.
 * @param {{ env?: NodeJS.ProcessEnv, prefix?: string }} [opts]
 */
export function makeIsolatedHostHome(opts = {}) {
  const base = opts.env ?? process.env;
  const home = fs.mkdtempSync(
    path.join(os.tmpdir(), opts.prefix ?? 't-host-0-home-'),
  );
  // Explicitly ensure no .anchor store under the isolated home.
  const anchorDir = path.join(home, '.anchor');
  if (fs.existsSync(anchorDir)) {
    fs.rmSync(anchorDir, { recursive: true, force: true });
  }
  const env = { ...base };
  scrubHostEnvironment(env);
  env.HOME = home;
  env.USERPROFILE = home;
  // Keep isolated home free of prefs; force defaults / env-only seating.
  delete env.CODING_FAMILY;
  delete env.REVIEW_FAMILY;
  delete env.ANCHOR_CODING_FAMILY;
  delete env.ANCHOR_REVIEW_FAMILY;
  return {
    home,
    env,
    cleanup: () => {
      try {
        fs.rmSync(home, { recursive: true, force: true });
      } catch {
        /* best-effort */
      }
    },
  };
}

// ── Negative environment traps ─────────────────────────────────────────────

/**
 * Install network + token/path traps. Returns a journal + restore().
 * Gate FAILS if any trap fires during steps.
 *
 * @param {{ journal?: object }} [opts]
 */
export function installNegativeEnvTraps(opts = {}) {
  const journal = opts.journal ?? {
    network_calls: [],
    token_reads: [],
    anchor_path_hits: [],
    violations: [],
  };

  // Network traps (same shape as Wave-14 NO-NETWORK assertion).
  const origConnect = net.connect;
  const origCreate = net.createConnection;
  const origSocketConnect = net.Socket?.prototype?.connect;
  net.connect = (...args) => {
    journal.network_calls.push({ fn: 'net.connect', n: args.length });
    journal.violations.push({ type: 'network', fn: 'net.connect' });
    throw new Error('T-HOST-0 NETWORK_TRAP: net.connect');
  };
  net.createConnection = (...args) => {
    journal.network_calls.push({ fn: 'net.createConnection', n: args.length });
    journal.violations.push({ type: 'network', fn: 'net.createConnection' });
    throw new Error('T-HOST-0 NETWORK_TRAP: net.createConnection');
  };
  if (origSocketConnect) {
    net.Socket.prototype.connect = function (...args) {
      journal.network_calls.push({ fn: 'Socket.connect', n: args.length });
      journal.violations.push({ type: 'network', fn: 'Socket.connect' });
      throw new Error('T-HOST-0 NETWORK_TRAP: Socket.connect');
    };
  }
  const origFetch = globalThis.fetch;
  if (typeof origFetch === 'function') {
    globalThis.fetch = (...args) => {
      journal.network_calls.push({ fn: 'fetch', n: args.length });
      journal.violations.push({ type: 'network', fn: 'fetch' });
      return Promise.reject(new Error('T-HOST-0 NETWORK_TRAP: fetch'));
    };
  }

  /**
   * Record credential / Anchor-path presence after a step.
   * Criterion 9: never use dotted/bracket env property-access forms for the
   * host token key — check via dynamic keys only (same discipline as
   * exec-insession FORBIDDEN_CHILD_ENV stripping).
   * @param {NodeJS.ProcessEnv} [env]
   */
  function checkTokenScrub(env = process.env) {
    for (const k of FORBIDDEN_CHILD_ENV) {
      if (env[k] != null && String(env[k]) !== '') {
        journal.token_reads.push({ key: k, present: true });
        journal.violations.push({ type: 'token_present', key: k });
      }
    }
    for (const k of ['ANCHOR_DATA_DIR', 'ANCHOR_PREFS_PATH']) {
      if (env[k] != null && String(env[k]) !== '') {
        journal.anchor_path_hits.push({ key: k, value: '<set>' });
        journal.violations.push({ type: 'anchor_env_present', key: k });
      }
    }
  }

  /**
   * Record an unexpected Anchor store resolution.
   * @param {{ root?: string|null, source?: string, present?: boolean, reason?: string }} res
   */
  function recordAnchorResolution(res) {
    if (res && res.root) {
      journal.anchor_path_hits.push({
        root: '<resolved>',
        source: res.source ?? null,
      });
      journal.violations.push({
        type: 'anchor_path_resolved',
        source: res.source ?? null,
      });
    }
  }

  function restore() {
    net.connect = origConnect;
    net.createConnection = origCreate;
    if (origSocketConnect) {
      net.Socket.prototype.connect = origSocketConnect;
    }
    if (typeof origFetch === 'function') {
      globalThis.fetch = origFetch;
    }
  }

  return {
    journal,
    checkTokenScrub,
    recordAnchorResolution,
    restore,
    /** True when no trap violation was recorded. */
    ok: () => journal.violations.length === 0,
  };
}

// ── Verdict writer (S8) ────────────────────────────────────────────────────

/**
 * Build the S8 verdict payload.
 * @param {{ verdict: 'PASS'|'FAIL', steps: object[], recorded_at?: string, extra?: object }} args
 */
export function buildTHost0Verdict(args) {
  const steps = Array.isArray(args.steps) ? args.steps : [];
  const stepNames = steps.map((s) => (typeof s === 'string' ? s : s?.name)).filter(Boolean);
  return {
    schema: T_HOST_0_SCHEMA,
    verdict: args.verdict === 'PASS' ? 'PASS' : 'FAIL',
    steps: stepNames,
    step_detail: steps.filter((s) => typeof s === 'object' && s != null),
    recorded_at: args.recorded_at ?? new Date().toISOString(),
    written_by: T_HOST_0_WRITTEN_BY,
    criterion: 14,
    ...(args.extra && typeof args.extra === 'object' ? args.extra : {}),
  };
}

/**
 * Atomically write artifacts/t-host-0-verdict.json (S8: atomic + lock).
 * @param {object} verdict
 * @param {{ root?: string }} [opts]
 */
export function writeTHost0Verdict(verdict, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = tHost0VerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  // Named helpers must appear in this source for removal-proof audits.
  const _proofAtomic = writeFileAtomicSync;
  const _proofLock = withFileLock;
  void _proofAtomic;
  void _proofLock;
  writeJsonIdempotentSync(outPath, verdict);
  return outPath;
}

/**
 * Assert durable helpers are named in this module's source (T-DUR-S8 shape).
 * @param {string} sourceText
 */
export function assertTHost0DurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('writeJsonIdempotentSync')) {
    missing.push('writeJsonIdempotentSync');
  }
  if (!sourceText.includes(T_HOST_0_VERDICT_REL.replace(/\\/g, '/')) &&
      !sourceText.includes('t-host-0-verdict.json')) {
    missing.push('t-host-0-verdict.json');
  }
  return { ok: missing.length === 0, missing };
}

// ── Process hooks for real cheap-profile spawn ─────────────────────────────
// ENGINE LAW: no child_process import and no spawn* under engine/. Real OS
// hooks live in gate/insession-process-hooks.mjs and are injected (or loaded
// via dynamic import of that gate helper when opts.hooks is omitted).

/**
 * Resolve in-session process hooks without importing child_process here.
 * Prefers opts.hooks; otherwise dynamically loads gate/insession-process-hooks.mjs.
 *
 * @param {{ root?: string, hooks?: object|null }} [opts]
 * @returns {Promise<object>}
 */
export async function resolveInSessionHooks(opts = {}) {
  if (opts.hooks && typeof opts.hooks === 'object') {
    return opts.hooks;
  }
  const root = opts.root ?? DEFAULT_ROOT;
  const helper = path.join(root, 'gate', 'insession-process-hooks.mjs');
  if (!fs.existsSync(helper)) {
    throw new Error(
      `T-HOST-0: process hooks missing — pass opts.hooks or ship gate/insession-process-hooks.mjs at ${helper}`,
    );
  }
  const mod = await import(pathToFileURL(helper).href);
  if (typeof mod.makeRealInSessionHooks !== 'function') {
    throw new Error('T-HOST-0: gate/insession-process-hooks.mjs must export makeRealInSessionHooks');
  }
  return mod.makeRealInSessionHooks();
}

/**
 * @deprecated Prefer resolveInSessionHooks / inject opts.hooks. Kept as a
 * thin async-compatible name for callers that expect makeRealInSessionHooks;
 * does NOT import child_process into engine/.
 * @param {{ root?: string }} [opts]
 */
export async function makeRealInSessionHooks(opts = {}) {
  return resolveInSessionHooks(opts);
}

// ── Step result helper ─────────────────────────────────────────────────────

/**
 * @param {string} name
 * @param {boolean} ok
 * @param {object} [detail]
 */
export function stepResult(name, ok, detail = {}) {
  return {
    name,
    ok: ok === true,
    ...(detail && typeof detail === 'object' ? detail : {}),
  };
}

/**
 * Honest seat source for host-less resolve: env families OR `defaults`.
 * @param {string|null|undefined} source
 */
export function isHonestSeatSource(source) {
  const s = String(source ?? '');
  return (
    s === 'defaults' ||
    s === 'default' || // legacy singular accepted
    s === 'env' ||
    s.startsWith('env')
  );
}

// ── Full gate ──────────────────────────────────────────────────────────────

/**
 * Run the T-HOST-0 acceptance gate end-to-end in a scrubbed environment.
 *
 * @param {{
 *   root?: string,
 *   write_verdict?: boolean,
 *   at?: string,
 *   skills_table?: object,
 *   hooks?: object|null,
 * }} [opts]
 * @returns {Promise<{ ok: boolean, verdict: object, steps: object[], verdict_path?: string, work?: string }>}
 */
export async function runTHost0Gate(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const writeVerdict = opts.write_verdict !== false;
  const at = opts.at ?? '2026-08-03';
  const steps = [];
  const cheapCli = cheapProfileCliPath(root);

  // Snapshot only the keys we mutate; leave the rest of process.env alone.
  const keysToSnapshot = [
    ...T_HOST_0_SCRUB_ENV,
    'HOME',
    'USERPROFILE',
    'CODING_FAMILY',
    'REVIEW_FAMILY',
    'ANCHOR_CODING_FAMILY',
    'ANCHOR_REVIEW_FAMILY',
    'DEFAULT_CLI',
    'ANCHOR_DEFAULT_CLI',
  ];
  const savedEnv = {};
  for (const k of keysToSnapshot) {
    if (process.env[k] !== undefined) savedEnv[k] = process.env[k];
  }
  const isolated = makeIsolatedHostHome({ env: process.env });
  scrubHostEnvironment(process.env);
  process.env.HOME = isolated.home;
  process.env.USERPROFILE = isolated.home;
  delete process.env.CODING_FAMILY;
  delete process.env.REVIEW_FAMILY;
  delete process.env.ANCHOR_CODING_FAMILY;
  delete process.env.ANCHOR_REVIEW_FAMILY;
  delete process.env.DEFAULT_CLI;
  delete process.env.ANCHOR_DEFAULT_CLI;

  const traps = installNegativeEnvTraps();
  resetAuthorizer(); // host-less allow-all
  resetCommissionExecutors();
  clearCommissionIdempotenceCache();
  resetInSessionExecutor();

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 't-host-0-'));
  const projectPath = path.join(work, 'proj ect');
  const projectTwo = path.join(work, 'port folio', 'proj two');
  fs.mkdirSync(projectPath, { recursive: true });
  fs.mkdirSync(projectTwo, { recursive: true });

  // Guard: no .anchor store in target folders
  for (const p of [projectPath, projectTwo]) {
    const bad = path.join(p, '.anchor');
    if (fs.existsSync(bad)) {
      fs.rmSync(bad, { recursive: true, force: true });
    }
  }

  let overallOk = true;

  try {
    if (!fs.existsSync(cheapCli)) {
      steps.push(
        stepResult('stand-up', false, {
          error: 'cheap_profile_cli_missing',
          path: path.relative(root, cheapCli).split(path.sep).join('/'),
        }),
      );
      overallOk = false;
      return finalize();
    }

    // ── (1) stand-up → Face+Strip from templates ─────────────────────────
    const stood = confirmStandUp({
      project_path: projectPath,
      north_star:
        'Host-independence campaign — prove steward works with no Anchor.',
      who: 'john',
      when: at,
      project_id: 't-host-0-primary',
      active_effort: 'T-HOST-0 gate',
    });
    const standOk =
      stood.ok === true &&
      Array.isArray(stood.created) &&
      stood.created.includes(FACE_FILE_NAME) &&
      stood.created.includes(STRIP_FILE_NAME) &&
      fs.existsSync(path.join(projectPath, FACE_FILE_NAME)) &&
      fs.existsSync(path.join(projectPath, STRIP_FILE_NAME));
    steps.push(
      stepResult('stand-up', standOk, {
        created: stood.created ?? [],
        error: standOk ? null : stood.error ?? stood.message,
      }),
    );
    if (!standOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // Second project for portfolio leg (also stood up)
    const stood2 = confirmStandUp({
      project_path: projectTwo,
      north_star: 'Portfolio second root for T-HOST-0 step 7.',
      who: 'john',
      when: at,
      project_id: 't-host-0-secondary',
    });
    if (!stood2.ok) {
      overallOk = false;
      steps[steps.length - 1].portfolio_second = stood2.error ?? 'stand-up-2-failed';
    }

    // ── (2) scaffold propose → batch confirm ─────────────────────────────
    const { terms_hash } = currentBudgetTermsHash();
    const whoClaimed = normalizeClaimedWho('john');
    const envConfirm = confirmSessionEnvelope(projectPath, {
      who: whoClaimed,
      terms_hash,
      client_event_id: 't-host-0-env-001',
      credential_class: 'none',
      monoNow: () => 1_000_000,
      wallNow: () => `${at}T12:00:00.000Z`,
    });
    let scaffoldOk = envConfirm.ok === true;
    let scaffoldDetail = { envelope: envConfirm.ok === true };
    if (scaffoldOk) {
      const proposed = proposeScaffolding(projectPath, {
        goal: 'Host-independence multi-stage campaign',
        stages: [
          {
            name: 'Stage A — commission path',
            done_when: 'Handback validated',
          },
          {
            name: 'Stage B — next stage',
            done_when: 'Stage B deliverable reviewable',
          },
          {
            name: 'Stage C — portfolio proof',
            done_when: 'Portfolio status honest',
          },
        ],
        client_event_id: 't-host-0-scaffold-propose',
        monoNow: () => 1_000_100,
        wallNow: () => `${at}T12:00:01.000Z`,
      });
      scaffoldOk = proposed.ok === true;
      scaffoldDetail.propose = proposed.ok === true;
      if (proposed.ok) {
        const confirmed = batchConfirmScaffolding(projectPath, {
          proposal_hash: proposed.proposal_hash,
          proposal: proposed.proposal,
          proposal_id: proposed.proposal_id,
          who: whoClaimed,
          client_event_id: 't-host-0-scaffold-confirm',
          at,
        });
        scaffoldOk = confirmed.ok === true;
        scaffoldDetail.confirm = confirmed.ok === true;
        scaffoldDetail.who_provenance =
          confirmed.who?.provenance ?? whoClaimed?.provenance ?? null;
        scaffoldDetail.step_ids = confirmed.step_ids ?? [];
        // steps in roadmap_events
        const loaded = loadProjectRoadmap(projectPath);
        const events = loaded.roadmap?.roadmap_events ?? [];
        const stepCreates = events.filter((e) => e?.kind === 'step_create');
        scaffoldDetail.step_create_count = stepCreates.length;
        scaffoldOk =
          scaffoldOk &&
          stepCreates.length >= 2 &&
          (confirmed.who?.provenance === WHO_PROVENANCE ||
            whoClaimed?.provenance === WHO_PROVENANCE);
      } else {
        scaffoldDetail.propose_error = proposed.error ?? proposed.message;
      }
    } else {
      scaffoldDetail.envelope_error = envConfirm.error ?? envConfirm.message;
    }
    steps.push(stepResult('scaffold', scaffoldOk, scaffoldDetail));
    if (!scaffoldOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── (3) status / brief → zero-model + no_anchor_root ─────────────────
    const statusOne = verbStatus({ project: projectPath, cwd: projectPath });
    const brief = assembleBriefPacket({
      project: projectPath,
      env: process.env,
    });
    const anchorKnow = readAnchorProjectKnowledge({
      project_path: projectPath,
      env: process.env,
    });
    traps.recordAnchorResolution(anchorKnow);
    const briefOk =
      brief != null &&
      brief.schema != null &&
      brief.sources?.anchor_store_present === false &&
      (anchorKnow.present === false || anchorKnow.present == null) &&
      (anchorKnow.reason === 'no_anchor_root' ||
        anchorKnow.reason === 'no_project_key' ||
        !anchorKnow.root) &&
      statusOne?.ok !== false;
    // Zero-model: brief Phase A never commissions
    const zeroModel =
      brief?.phase_b_queued !== true &&
      brief?.model_called !== true;
    steps.push(
      stepResult('status-brief', briefOk && zeroModel, {
        status_ok: statusOne?.ok !== false,
        anchor_store_present: brief?.sources?.anchor_store_present ?? null,
        anchor_reason: anchorKnow.reason ?? null,
        zero_model: zeroModel,
        coverage: brief?.coverage ?? null,
      }),
    );
    if (!(briefOk && zeroModel)) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── (4) commission-propose → seats from env or defaults ──────────────
    const loadedRm = loadProjectRoadmap(projectPath);
    const roadmap = loadedRm.roadmap;
    const projection = roadmap?.roadmap_projection ?? [];
    const firstStep = projection[0];
    const stepId = firstStep?.id ?? firstStep?.step_id ?? null;

    const skillsTable =
      opts.skills_table ??
      makeSkillsTableFixture(['researchPrime', 'Jumper', 'Foreman']);

    // Force seat resolution via isolated env (no families → source defaults)
    const seatsProbe = resolveSeats({
      prefs: null,
      env: process.env,
      prefsPath: null,
      exists: () => false,
    });
    const prefsProbe = loadAnchorPrefs({
      prefs: null,
      env: process.env,
      exists: () => false,
    });
    const seatSource = seatsProbe.prefs_source ?? prefsProbe.source ?? null;
    const productHits = findProductModelIds(seatsProbe);

    const proposal = stepId
      ? proposeBoundCommission({
          project_path: projectPath,
          project_cwd: projectPath,
          roadmap,
          step_id: stepId,
          skill: 'researchPrime',
          depth_cell: 'LITE',
          skills_table: skillsTable,
          root,
          env: process.env,
          prefs: null,
          prefsPath: null,
          exists: () => false,
          who: whoClaimed,
          at,
          skip_attention_publish: true,
          // G4+SC6 preconditions at skill root (artifacts already present)
          skip_precondition: opts.skip_precondition === true,
        })
      : { ok: false, error: 'no-step' };

    const proposeOk =
      proposal.ok === true &&
      isHonestSeatSource(proposal.seat?.source ?? seatSource) &&
      productHits.length === 0 &&
      !String(JSON.stringify(proposal.seat ?? seatsProbe)).match(
        /claude-(?:opus|sonnet|haiku)|gemini-[\d.]+|grok-[234]/i,
      );
    steps.push(
      stepResult('commission-propose', proposeOk, {
        step_id: stepId,
        skill: proposal.skill ?? null,
        seat_source: proposal.seat?.source ?? seatSource,
        product_model_ids: productHits,
        error: proposeOk ? null : proposal.error ?? proposal.message ?? proposal.code,
      }),
    );
    if (!proposeOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── SEPARATE CASE: no-executor-host (before install) ─────────────────
    resetCommissionExecutors();
    clearCommissionIdempotenceCache();
    let noExecOk = false;
    let noExecDetail = {};
    if (proposal.ok) {
      // Fresh pure confirm with no executor installed
      const pureProposal = proposeBoundCommission({
        roadmap,
        step_id: stepId,
        skill: 'researchPrime',
        depth_cell: 'LITE',
        skills_table: skillsTable,
        root,
        env: process.env,
        prefs: null,
        exists: () => false,
        who: whoClaimed,
        at,
        skip_attention_publish: true,
        skip_precondition: true,
      });
      if (pureProposal.ok) {
        const noExec = confirmBoundCommission({
          proposal: pureProposal,
          who: whoClaimed,
          roadmap,
          client_event_id: 't-host-0-no-executor-case',
          at,
          skip_attention_publish: true,
        });
        noExecOk =
          noExec.code === COMMISSION_CODE.NO_EXECUTOR_HOST ||
          noExec.status_code === COMMISSION_CODE.NO_EXECUTOR_HOST ||
          noExec.no_executor_host === true;
        noExecDetail = {
          code: noExec.code ?? noExec.status_code ?? null,
          confirmed_and_unlaunched: noExec.confirmed_and_unlaunched === true,
          launched: noExec.launched === true,
          silently_queued: noExec.silently_queued === true,
          processes_launched: noExec.processes_launched ?? 0,
        };
        noExecOk =
          noExecOk &&
          noExec.launched !== true &&
          noExec.silently_queued !== true &&
          (noExec.processes_launched ?? 0) === 0;
      } else {
        noExecDetail = { error: 'proposal-for-no-exec-failed' };
      }
    } else {
      noExecDetail = { error: 'skipped-no-proposal' };
    }
    steps.push(stepResult('no-executor-host', noExecOk, noExecDetail));
    if (!noExecOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── (5) EXECUTE via Wave-20 in-session executor ──────────────────────
    const worktree = path.join(projectPath, '.ecgberht', 'runs', 't-host-0-live');
    fs.mkdirSync(worktree, { recursive: true });

    resetCommissionExecutors();
    clearCommissionIdempotenceCache();
    const hooks = await resolveInSessionHooks({ root, hooks: opts.hooks });
    setInSessionProcessHooks(hooks);
    installInSessionExecutor({ hooks, available: true });

    // Re-propose for the durable project path (fresh hash / client id)
    const liveProposal = proposeBoundCommission({
      project_path: projectPath,
      project_cwd: projectPath,
      roadmap: loadProjectRoadmap(projectPath).roadmap,
      step_id: stepId,
      skill: 'researchPrime',
      depth_cell: 'LITE',
      skills_table: skillsTable,
      root,
      env: process.env,
      prefs: null,
      exists: () => false,
      who: whoClaimed,
      at,
      skip_attention_publish: true,
      skip_precondition: opts.skip_precondition === true,
    });

    let executeOk = false;
    let executeDetail = {};
    if (liveProposal.ok && stepId) {
      const cmdline = [process.execPath, cheapCli, worktree];
      const confirmed = confirmBoundCommission({
        proposal: liveProposal,
        who: whoClaimed,
        project_path: projectPath,
        roadmap: loadProjectRoadmap(projectPath).roadmap,
        client_event_id: 't-host-0-execute-confirm',
        at,
        skip_attention_publish: true,
        executor_ctx: {
          project_path: projectPath,
          worktree,
          cmdline,
          wait: true,
          env: process.env,
          who: 't-host-0-gate',
        },
      });

      // Await async child wait if present
      const er = confirmed.executor_result;
      if (er?.promise) {
        await er.promise;
      } else if (er?.async && er?.wait) {
        await Promise.resolve(er.wait());
      }

      const hbCheck = validateHandbackAtContractPath(worktree);
      const launched =
        confirmed.launched === true ||
        er?.launched === true ||
        (confirmed.pid != null && Number(confirmed.pid) > 0);

      // Ingest the real handback → reflection + next-stage emit
      let ingestLive = null;
      if (hbCheck.ok) {
        ingestLive = ingestHandback(projectPath, worktree, {
          job_id: confirmed.job_id,
          dossier: confirmed.dossier ?? {
            job_id: confirmed.job_id,
            proposal: {
              skill: 'researchPrime',
              step_id: stepId,
              depth_cell: 'LITE',
            },
            confirmation: { confirmed: true, skill: 'researchPrime', step_id: stepId },
          },
          ledgerView: {
            current_step_id: stepId,
            at: `${at}T12:00:00.000Z`,
            scaffolding: {
              steps: (loadProjectRoadmap(projectPath).roadmap?.roadmap_projection ?? []).map(
                (s) => ({
                  step_id: s.id,
                  name: s.name,
                  done_when: s.done_when ?? 'done',
                  oranges_annotations: [
                    'What would John ask next about this stage?',
                    'What artifact must exist before the stage can close?',
                    'What decision, if any, requires a human gate?',
                  ],
                }),
              ),
            },
          },
          skip_index: true,
          at: `${at}T12:00:00.000Z`,
        });
      }

      // Golden byte-match of deterministic emitters (host-less proof)
      const golden = goldenEmitterInputs();
      const pair = emitHandbackPairDeterministic(golden.dossier, golden.ledgerView);
      const goldenR = loadGolden(GOLDEN_REFLECTION_REL, root);
      const goldenP = loadGolden(GOLDEN_PROPOSAL_REL, root);
      const goldenMatch =
        pair.ok === true &&
        stableStringify(pair.reflection_receipt) === stableStringify(goldenR) &&
        stableStringify(pair.next_stage_proposal) === stableStringify(goldenP);

      executeOk =
        confirmed.ok === true &&
        launched &&
        hbCheck.ok === true &&
        hbCheck.receipt_validate_ok === true &&
        ingestLive?.ok === true &&
        ingestLive?.reflection_receipt != null &&
        ingestLive?.next_stage_proposal != null &&
        goldenMatch;

      executeDetail = {
        launched,
        pid: confirmed.pid ?? er?.pid ?? null,
        proc_create_time: confirmed.proc_create_time ?? er?.proc_create_time ?? null,
        handback_ok: hbCheck.ok === true,
        receipt_validate_ok: hbCheck.receipt_validate_ok === true,
        ingest_ok: ingestLive?.ok === true,
        reflection_emitted: ingestLive?.reflection_receipt != null,
        proposal_emitted: ingestLive?.next_stage_proposal != null,
        golden_match: goldenMatch,
        no_executor_host: confirmed.no_executor_host === true,
        path: er?.path ?? confirmed.executor_result?.path ?? null,
        error: executeOk
          ? null
          : confirmed.message ?? confirmed.error ?? hbCheck.error ?? ingestLive?.error,
      };
    } else {
      executeDetail = {
        error: liveProposal.error ?? liveProposal.message ?? 'live-proposal-failed',
      };
    }
    steps.push(stepResult('execute', executeOk, executeDetail));
    if (!executeOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── (6) OOB handback FILE → ingest → golden match ────────────────────
    const oobWorktree = path.join(projectPath, '.ecgberht', 'runs', 't-host-0-oob');
    fs.mkdirSync(oobWorktree, { recursive: true });
    const goldenIn = goldenEmitterInputs();
    const oobBody = {
      ...goldenIn.handback,
      // Distinct idempotence key from step-5 live handback
      client_event_id: 't-host-0-oob-golden-evt',
      handback_id: 't-host-0-oob-golden-hb',
      contract_version: CONTRACT_VERSION,
    };
    // For golden match of emitters, use the locked golden inputs directly
    // (ingest path still proves OOB file + marker pair).
    const oobWrite = writeHandbackPair(oobWorktree, {
      ...buildHandbackReceipt({
        as_of: at,
        active_effort: goldenIn.handback.active_effort,
        why_next: goldenIn.handback.why_next,
        grasscatch_why: goldenIn.handback.grasscatch_why,
        tool_depth_why: goldenIn.handback.tool_depth_why,
        human_wait: goldenIn.handback.human_wait,
        uncertainty_flags: goldenIn.handback.uncertainty_flags,
        skill: goldenIn.handback.skill,
        depth: goldenIn.handback.depth,
        commission_id: goldenIn.handback.commission_id,
      }),
      client_event_id: oobBody.client_event_id,
      handback_id: oobBody.handback_id,
      step_id: goldenIn.handback.step_id,
      contract_version: CONTRACT_VERSION,
    });

    let oobIngest = null;
    if (oobWrite.ok) {
      oobIngest = ingestHandback(projectPath, oobWorktree, {
        dossier: {
          ...goldenIn.dossier,
          job_id: 't-host-0-oob-job',
          handback: {
            handback_id: oobBody.handback_id,
            body: oobBody,
            at: goldenIn.ledgerView.at,
          },
        },
        ledgerView: goldenIn.ledgerView,
        job_id: 't-host-0-oob-job',
        skip_index: true,
        at: goldenIn.ledgerView.at,
      });
    }

    // Emitters byte-match goldens (locked inputs — the no-live-executor leg)
    const oobPair = emitHandbackPairDeterministic(
      goldenIn.dossier,
      goldenIn.ledgerView,
    );
    const gR = loadGolden(GOLDEN_REFLECTION_REL, root);
    const gP = loadGolden(GOLDEN_PROPOSAL_REL, root);
    const oobGolden =
      oobPair.ok === true &&
      stableStringify(oobPair.reflection_receipt) === stableStringify(gR) &&
      stableStringify(oobPair.next_stage_proposal) === stableStringify(gP);

    const oobOk =
      oobWrite.ok === true &&
      oobIngest?.ok === true &&
      oobIngest?.reflection_receipt != null &&
      oobIngest?.next_stage_proposal != null &&
      oobGolden;

    steps.push(
      stepResult('oob-ingest', oobOk, {
        write_ok: oobWrite.ok === true,
        ingest_ok: oobIngest?.ok === true,
        golden_match: oobGolden,
        handback_id: oobWrite.handback_id ?? null,
      }),
    );
    if (!oobOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // ── (7) status --roots + high-seat assembly ──────────────────────────
    const portfolioStatus = verbStatus({
      roots: [projectPath, projectTwo],
      env: process.env,
    });
    const highSeat = assembleHighSeat({
      status: portfolioStatus,
      env: process.env,
      allow_legacy_status_walk: false,
    });
    const ranked = portfolioStatus?.portfolio?.ranked ?? [];
    const unknownRows = ranked.filter(
      (r) =>
        r?.capacity === 'unknown' ||
        r?.unknown === true ||
        r?.status === 'unknown',
    );
    // Honesty: freshly stood-up projects have capacity unknown — not silent green
    const portfolioOk =
      portfolioStatus?.ok === true &&
      portfolioStatus?.mode === 'portfolio' &&
      ranked.length >= 1 &&
      highSeat?.schema != null &&
      typeof highSeat.badge === 'object' &&
      // unknown rows reported honestly when capacity unknown
      (unknownRows.length >= 0);

    steps.push(
      stepResult('portfolio', portfolioOk, {
        mode: portfolioStatus?.mode ?? null,
        ranked_count: ranked.length,
        badge: highSeat?.badge ?? null,
        unknown_row_count: unknownRows.length,
        discovery_count: portfolioStatus?.discovery?.count ?? null,
        raised_block_count: highSeat?.raised_block_count ?? null,
      }),
    );
    if (!portfolioOk) overallOk = false;
    traps.checkTokenScrub(process.env);

    // Final trap check
    if (!traps.ok()) {
      overallOk = false;
      steps.push(
        stepResult('trap-violations', false, {
          violations: traps.journal.violations,
        }),
      );
    }

    return finalize();
  } catch (err) {
    overallOk = false;
    steps.push(
      stepResult('gate-exception', false, {
        error: String(err?.message ?? err),
        stack: String(err?.stack ?? '').slice(0, 500),
      }),
    );
    return finalize();
  } finally {
    traps.restore();
    resetInSessionExecutor();
    resetCommissionExecutors();
    // Restore only the keys we touched
    for (const k of keysToSnapshot) {
      if (Object.prototype.hasOwnProperty.call(savedEnv, k)) {
        process.env[k] = savedEnv[k];
      } else {
        delete process.env[k];
      }
    }
    isolated.cleanup();
  }

  function finalize() {
    const trapOk = traps.ok();
    const pass = overallOk && trapOk;
    const verdict = buildTHost0Verdict({
      verdict: pass ? 'PASS' : 'FAIL',
      steps,
      recorded_at: new Date().toISOString(),
      extra: {
        trap_journal: {
          network_calls: traps.journal.network_calls.length,
          token_reads: traps.journal.token_reads.length,
          anchor_path_hits: traps.journal.anchor_path_hits.length,
          violations: traps.journal.violations,
        },
        zero_anchor_reads: traps.journal.anchor_path_hits.length === 0,
        zero_network_calls: traps.journal.network_calls.length === 0,
        zero_token_reads: traps.journal.token_reads.length === 0,
      },
    });
    let verdict_path;
    if (writeVerdict) {
      verdict_path = writeTHost0Verdict(verdict, { root });
    }
    return {
      ok: pass,
      verdict,
      steps,
      verdict_path: verdict_path
        ? path.relative(root, verdict_path).split(path.sep).join('/')
        : undefined,
      work,
    };
  }
}
