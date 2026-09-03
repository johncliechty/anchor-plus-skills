/**
 * TW5 — Seal chamber bridge: the ONE entry the Anchor-dev docked overlay
 * calls (spawned as `node scripts/seal-chamber-bridge.mjs …` by the
 * /api/ecgberht/* handlers). It only composes the engine's closed read
 * surfaces — the overlay gets the same pointer `ecgberht status` prints,
 * which is what makes CLI parity structural (annex A5 self-run smoke).
 *
 * Modes (all print a single JSON object to stdout):
 *   --project <path>                 → Screen 1 chamber view model + parity
 *   --project <path> --speak <text>  → compile the utterance (closed acts /
 *                                      refuse-with-proposal; off-flow park
 *                                      offers ride along; nothing is written)
 *   --project <path> --recall <q>    → provenance recall beat (record or
 *                                      honest unknown + thin-evidence offer)
 *   --project <path> (no steward)    → Screen 4 stand-up chamber (TW7):
 *                                      goal asked, never invented; nothing
 *                                      created until confirm
 *   --stand-up-confirm <json>        → TW7 confirm ONLY path: create
 *                                      Face+Strip from templates
 *   --not-now                        → TW7 clean exit (zero writes)
 *
 * Zero write authority except --stand-up-confirm, which is John's explicit
 * confirm — the single place Face+Strip creation happens. Receipts land
 * only through the closed verbs when an act is APPLIED.
 */

import {
  assembleSealChamber,
  chamberAgreesWithStatus,
  chamberSpeak,
  buildGrasscatcherOffer,
  buildSeatSwitchDivider,
  buildProvenanceRecall,
} from '../engine/seal-chamber.mjs';
import { verbStatus } from '../engine/verb-bodies.mjs';
import { assembleBriefPacket } from '../engine/brief.mjs';
import {
  assembleStandUp,
  confirmStandUp,
  standUpNotNow,
  buildThinEvidenceBeat,
} from '../engine/stand-up.mjs';
import {
  compileScaffoldDescription,
  proposeScaffolding,
  batchConfirmScaffolding,
} from '../engine/scaffolding.mjs';
import { showKickoff, replayKickoff } from '../engine/kickoff.mjs';
// Gate 5 / Wave 3: show and confirm land on the one store (<folder>/.ecgberht/kickoff/
// events.jsonl); the roadmap projections the chamber paints today are mirrored by name.
import { confirmKickoffSpoken, showKickoffSpoken } from '../engine/kickoff-conversation.mjs';
import { converse } from '../engine/steward-conversation.mjs';
import {
  reconstructStepDetail,
  evaluateCommissionability,
  deriveTargetedQuestions,
} from '../engine/progressive-elaboration.mjs';
import { findingsForStep, appendStepFindings } from '../engine/step-findings.mjs';
import { loadProjectRoadmap } from '../engine/roadmap.mjs';
import { makeSeatCall } from './seat-call.mjs';

/**
 * Step detail for the rail click (2026-08-07, John): "I should be able to
 * click on that description for each portion of the master plan and have it
 * open up and give me whatever details there are and suggestions for details."
 * Read-only: the step's accumulated elaboration + what it still needs.
 */
export function buildStepDetailPayload(opts = {}) {
  if (!opts.project) return { ok: false, error: 'missing_project', mode: 'step_detail' };
  if (!opts.step_id) return { ok: false, error: 'missing_step_id', mode: 'step_detail' };
  const loaded = loadProjectRoadmap(opts.project);
  if (!loaded.ok || !loaded.exists) {
    return { ok: false, error: 'no_roadmap', mode: 'step_detail' };
  }
  const step = (loaded.roadmap?.roadmap_projection ?? [])
    .find((s) => (s.id ?? s.step_id) === opts.step_id) ?? null;
  if (!step) return { ok: false, error: 'unknown_step', mode: 'step_detail', step_id: opts.step_id };

  const detail = reconstructStepDetail(loaded.roadmap, opts.step_id);
  const predicate = detail && detail.ok !== false
    ? evaluateCommissionability(detail) : null;
  const suggestions = predicate && !predicate.ready
    ? deriveTargetedQuestions(predicate, detail) : [];
  return {
    ok: true,
    mode: 'step_detail',
    step_id: opts.step_id,
    name: step.name ?? null,
    status: step.status ?? null,
    done_when: step.done_when ?? null,
    detail: detail && detail.ok !== false ? detail : null,
    // The findings ledger: what runs and reflection have FED this step.
    findings: findingsForStep(opts.project, opts.step_id),
    ready: predicate ? predicate.ready === true : null,
    suggestions,
  };
}

/**
 * John adds detail FROM the rail's step panel (2026-08-07: "have the steward
 * interact with you to refine include add the details so it's not just
 * looking at it"). The note lands durably on the step's findings ledger,
 * source-attributed to him; the conversational refinement rides the normal
 * converse turn the chamber sends alongside. Step must exist — an invented
 * id is refused, never written.
 */
export function buildStepNotePayload(opts = {}) {
  if (!opts.project) return { ok: false, error: 'missing_project', mode: 'step_note' };
  if (!opts.step_id) return { ok: false, error: 'missing_step_id', mode: 'step_note' };
  const note = String(opts.note ?? '').trim();
  if (!note) return { ok: false, error: 'missing_note', mode: 'step_note' };
  const loaded = loadProjectRoadmap(opts.project);
  if (!loaded.ok || !loaded.exists) {
    return { ok: false, error: 'no_roadmap', mode: 'step_note' };
  }
  const known = (loaded.roadmap?.roadmap_projection ?? [])
    .some((s) => (s.id ?? s.step_id) === opts.step_id);
  if (!known) return { ok: false, error: 'unknown_step', mode: 'step_note', step_id: opts.step_id };
  const rec = appendStepFindings(opts.project, {
    step_id: opts.step_id,
    findings: [note],
    source: opts.who && String(opts.who).trim() ? String(opts.who).trim() : 'john',
  });
  if (rec.ok === false) {
    return { ok: false, error: rec.error ?? 'append_failed', mode: 'step_note' };
  }
  return {
    ok: true,
    mode: 'step_note',
    step_id: opts.step_id,
    findings: findingsForStep(opts.project, opts.step_id),
  };
}
import {
  confirmSessionEnvelope,
  currentBudgetTermsHash,
  raiseSessionEnvelope,
  readEnvelopeState,
} from '../engine/session-envelope.mjs';
import { normalizeClaimedWho } from '../engine/identity-policy.mjs';
import { noteStewardEffort } from '../engine/portfolio-ledger.mjs';

/** Parse the tiny closed flag set (no free-form option surface). */
export function parseBridgeArgs(argv = []) {
  // Base shape is the frozen TW5 flag set; the TW7 stand-up flags join the
  // result only when actually present so the TW5 contract stays exact.
  const out = {
    project: null,
    speak: null,
    recall: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--project' && argv[i + 1] != null) out.project = argv[++i];
    else if (t === '--speak' && argv[i + 1] != null) out.speak = argv[++i];
    else if (t === '--recall' && argv[i + 1] != null) out.recall = argv[++i];
    else if (t === '--stand-up-confirm' && argv[i + 1] != null)
      out.standUpConfirm = argv[++i];
    else if (t === '--goal' && argv[i + 1] != null) out.goal = argv[++i];
    else if (t === '--scaffold-preview' && argv[i + 1] != null)
      out.scaffoldPreview = argv[++i];
    else if (t === '--scaffold-confirm' && argv[i + 1] != null)
      out.scaffoldConfirm = argv[++i];
    else if (t === '--kickoff-show') out.kickoffShow = true;
    else if (t === '--kickoff-confirm' && argv[i + 1] != null)
      out.kickoffConfirm = argv[++i];
    else if (t === '--kickoff-replay' && argv[i + 1] != null)
      out.kickoffReplay = argv[++i];
    else if (t === '--converse' && argv[i + 1] != null) out.converse = argv[++i];
    else if (t === '--turns' && argv[i + 1] != null) out.turns = argv[++i];
    // E1 bound payload (steward-e1 W2): the ratification state + the
    // deterministic question ids the Anchor owner (chamber_e1_hook.py)
    // computed for this turn — the engine's turn-completion hook enforces
    // ONLY what this payload says is enforceable.
    else if (t === '--e1' && argv[i + 1] != null) out.e1 = argv[++i];
    // Frozen clock for the RECORD/REPLAY lane: conversation-log dates ride the
    // prompt, so a tape recorded yesterday mismatches today without this.
    else if (t === '--as-of' && argv[i + 1] != null) out.asOf = argv[++i];
    // Step detail for the rail click (2026-08-07): everything the campaign has
    // accumulated on one step + what it still needs. Read-only.
    else if (t === '--step-detail' && argv[i + 1] != null) out.stepDetail = argv[++i];
    // Step note (2026-08-07): John's added detail from the rail panel lands
    // on the step's findings ledger. Pairs with --note <text>.
    else if (t === '--step-note' && argv[i + 1] != null) out.stepNote = argv[++i];
    else if (t === '--note' && argv[i + 1] != null) out.note = argv[++i];
    else if (t === '--who' && argv[i + 1] != null) out.who = argv[++i];
    else if (t === '--client-event-id' && argv[i + 1] != null)
      out.clientEventId = argv[++i];
    else if (t === '--envelope-confirm' && argv[i + 1] != null)
      out.envelopeConfirm = argv[++i];
    else if (t === '--envelope-raise' && argv[i + 1] != null)
      out.envelopeRaise = argv[++i];
    else if (t === '--not-now') out.notNow = true;
  }
  return out;
}

/**
 * Chamber payload: the Screen 1 view model plus the CLI-parity attestation
 * the overlay footer can show ("status agrees with this chamber").
 * TW7: a project with NO steward (no Face, no Strip) gets the Screen 4
 * stand-up chamber instead — the steward asks for the goal and invents
 * nothing; injected surfaces (tests) are respected for the detection.
 * @param {{ project: string, inject?: object }} opts
 */
export function buildChamberPayload(opts = {}) {
  const inject = opts.inject ?? {};
  const standUp = assembleStandUp({
    project: opts.project,
    ...(inject.surfaces !== undefined ? { surfaces: inject.surfaces } : {}),
  });
  if (standUp.stand_up) {
    return { ok: true, mode: 'stand_up', stand_up: standUp.chamber };
  }
  const chamber = assembleSealChamber({ project: opts.project, ...inject });
  const status = inject.status ?? verbStatus({ project: opts.project, roots: [], ...inject });
  const parity = chamberAgreesWithStatus(chamber, status);
  return { ok: true, mode: 'chamber', chamber, parity };
}

/**
 * TW7 stand-up confirm payload — the one write path in this bridge, and it
 * only runs on John's explicit confirm. Fields arrive as JSON:
 * { project_path, north_star, project_id?, active_effort?, who? }.
 * @param {{ json: string, inject?: object }} opts
 */
export function buildStandUpConfirmPayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      error: 'stand_up_bad_json',
      message: 'stand-up fields must be JSON { project_path, north_star, who? }',
    };
  }
  const result = confirmStandUp({ ...fields, ...(opts.inject ?? {}) });
  return { ...result, mode: 'stand-up-confirm' };
}

/**
 * Speak payload: compile-only. A compiled `park_that` carries the
 * Grasscatcher offer beat; a compiled `switch_seat` carries the divider
 * preview. Refusals come back structured (refuse-with-proposal).
 * @param {{ project: string, text: string, session?: object, inject?: object }} opts
 */
export function buildSpeakPayload(opts = {}) {
  const spoken = chamberSpeak(opts.text, { session: opts.session });
  const compiled = spoken.compiled;
  const payload = {
    ok: true,
    mode: 'speak',
    compiled,
    dialogue_persisted: false,
    store_policy: spoken.store_policy,
  };
  if (compiled.compiled && compiled.act === 'park_that') {
    payload.offer = buildGrasscatcherOffer({ idea: compiled.args?.deferred ?? opts.text });
  }
  if (compiled.compiled && compiled.act === 'switch_seat' && compiled.args?.seat) {
    payload.divider_preview = buildSeatSwitchDivider({
      from: opts.session?.seat ?? 'claude',
      to: compiled.args.seat,
      who: 'john',
    });
  }
  return payload;
}

/**
 * Recall payload: answered from the brief packet's record, or honest unknown.
 * @param {{ project: string, question: string, inject?: object }} opts
 */
export function buildRecallPayload(opts = {}) {
  const inject = opts.inject ?? {};
  const packet =
    inject.packet ??
    assembleBriefPacket({ project: opts.project, roots: [], altitude: 'project', ...inject });
  const recall = buildProvenanceRecall({ question: opts.question, packet });
  // TW7 S4-E3 — a silent record rides with the thin-evidence beat: honest
  // unknown + a constructive offer (commission a fresh look), never padding.
  const thin_evidence = recall.unknown
    ? buildThinEvidenceBeat({ question: opts.question })
    : null;
  return {
    ok: true,
    mode: 'recall',
    recall,
    thin_evidence,
  };
}

/**
 * SCAFFOLD PREVIEW — pure, zero-model, ZERO WRITES (2026-08-04).
 *
 * The chamber's act table has eleven closed acts and none of them is "scaffold this
 * project", so a dictated project description compiled to nothing and the user was
 * offered only "pick an act or park the thought". This is the missing path: it turns
 * the description into a PROPOSED scaffolding the user can see, with no ledger write
 * and no session envelope required, because seeing a proposal costs nothing.
 *
 * Confirming is a separate, explicit act (--scaffold-confirm).
 */
export function buildScaffoldPreviewPayload(opts = {}) {
  const compiled = compileScaffoldDescription({
    goal: opts.goal ?? null,
    description: opts.text,
  });
  if (!compiled.ok) {
    return {
      ok: true,
      mode: 'scaffold-preview',
      compiled: false,
      code: compiled.code ?? null,
      // Honest and actionable: the steward invents nothing, so when no action clause
      // is found it ASKS instead of manufacturing a plan.
      message:
        compiled.code === 'SCAFFOLD_EMPTY'
          ? 'I could not hear any stages in that. Tell me the stages — one per line, '
            + 'or as "build X, develop Y, pilot Z" — and I will propose a campaign.'
          : (compiled.message ?? 'That did not compile to a scaffolding.'),
      ledger_write: false,
    };
  }
  return {
    ok: true,
    mode: 'scaffold-preview',
    compiled: true,
    proposal: compiled.proposal,
    step_count: (compiled.proposal?.steps ?? []).length,
    ledger_write: false,
    confirm_hint: 'Confirm to write these steps to the campaign roadmap.',
  };
}

/**
 * CONVERSE — the conversational door (2026-08-04).
 *
 * This is the surface that replaces "pick a closed act or park the thought" for
 * free-form speech. Routing happens in the ENGINE (routeUtterance): control verbs still
 * compile deterministically, and only genuine talk reaches the seat. Prior turns ride in
 * as EPHEMERAL context from the caller — the browser page or the test holds them, they
 * are replayed for continuity, and they are never written anywhere.
 *
 * Nothing is written here. A proposal lands as a typed scaffold_proposal for review;
 * confirming remains a separate explicit act.
 *
 * @param {{ project: string, text: string, turns?: string, who?: string }} opts
 */
export async function buildConversePayload(opts = {}) {
  let turns = [];
  if (opts.turns) {
    try {
      const parsed = JSON.parse(opts.turns);
      if (Array.isArray(parsed)) turns = parsed;
    } catch {
      // Malformed ephemeral context is never fatal — the durable ledger still
      // carries the scaffolding-so-far, so the turn degrades to less continuity,
      // not to a wrong answer.
      turns = [];
    }
  }

  // E1 (steward-e1 W2): the bound payload rides in as JSON. An UNREADABLE
  // payload is NOT treated as "no bound" — it fails CLOSED by name, so a
  // mangled seam can never silently disarm the turn-completion hook.
  let e1 = null;
  if (opts.e1 != null) {
    try {
      e1 = JSON.parse(opts.e1);
    } catch {
      e1 = {
        schema_version: 1,
        enforceable: false,
        finding: 'E1-F7-ARTIFACT-MISSING',
        reason: 'the --e1 bound payload was unreadable at the bridge '
          + 'boundary — fail closed by name, never silently open',
      };
    }
  }

  const result = await converse(opts.project, {
    utterance: opts.text,
    turns,
    ...(e1 ? { e1 } : {}),
    ...(opts.asOf ? { at: opts.asOf } : {}),
    ...(opts.clientEventId ? { client_event_id: opts.clientEventId } : {}),
    seatCall: makeSeatCall(),
    // THE BACKGROUND ALLOWANCE. John does not want to approve spend before the steward
    // will say anything — so the first turn opens one silently at the default cap. He
    // still cannot be spent past it: reaching the cap stops the steward and asks.
    openAllowance: (projectPath) => {
      // THE STEWARD ALWAYS TALKS (John, 2026-08-07). The first allowance
      // opened with the default 240-minute TTL and a client_event_id derived
      // ONLY from the terms hash — so once it expired, every reopen attempt
      // idempotently returned the same dead envelope and talk stayed blocked
      // behind "no confirmed session budget". Two fixes, both here:
      //   1. the background allowance lives a WEEK, not an afternoon;
      //   2. the idempotency key carries a 10-minute time bucket — retries
      //      inside a bucket stay idempotent (no double-open race), while an
      //      expired envelope gets a FRESH one on the next bucket.
      // The $50 cap is unchanged — the law that matters (stop at the cap and
      // ask) still holds.
      const overrides = { max_compiles: null, ttl_minutes: 7 * 24 * 60 };
      const { terms_hash } = currentBudgetTermsHash(overrides);
      const bucket = Math.floor(Date.now() / 600000);
      const env = confirmSessionEnvelope(projectPath, {
        who: normalizeClaimedWho(opts.who ?? 'john'),
        terms_hash,
        terms_overrides: overrides,
        client_event_id: `allowance-${terms_hash.slice(0, 16)}-${bucket}`,
        credential_class: 'none',
      });
      return { ok: env.ok === true || env.already_confirmed === true };
    },
  });

  return { ...result, mode: 'converse' };
}

/**
 * ENVELOPE CONFIRM — the human "yes, spend on this session" act.
 *
 * Talking to the steward costs a model call, and the law is that nothing is spent
 * without human confirmation. Asking per sentence would be unusable, so ONE confirmation
 * covers the whole session until a bound trips (25 compiles / $5 synthetic / 240 min,
 * whichever first). This is that one confirmation.
 */
export function buildEnvelopeConfirmPayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      mode: 'envelope-confirm',
      error: 'envelope_bad_json',
      message: 'envelope-confirm needs JSON { project_path, who? }',
    };
  }
  const projectPath = fields.project_path ?? opts.project;
  if (!projectPath) {
    return { ok: false, mode: 'envelope-confirm', error: 'missing_project' };
  }
  const who = normalizeClaimedWho(fields.who ?? 'john');

  // The DOLLAR CAP is John's to set, and turns are deliberately unlimited: the turn
  // count was sized for a compile-a-description surface, and a conversation should not
  // be rationed by it. `max_compiles: null` means unlimited; the spend cap is the one
  // that stops us, and reaching it is a checkpoint he can lift.
  const overrides = { max_compiles: null };
  if (Number.isFinite(Number(fields.max_spend_usd)) && Number(fields.max_spend_usd) > 0) {
    overrides.max_spend_usd = Number(fields.max_spend_usd);
  }
  const { terms, terms_hash } = currentBudgetTermsHash(overrides);
  const env = confirmSessionEnvelope(projectPath, {
    who,
    terms_hash,
    terms_overrides: overrides,
    client_event_id: fields.client_event_id ?? `envelope-${terms_hash.slice(0, 12)}`,
    credential_class: 'none',
  });
  const live = env.ok === true || env.already_live === true;
  return {
    ...env,
    ok: live,
    mode: 'envelope-confirm',
    already_live: env.already_live === true,
    max_spend_usd: terms.max_spend_usd,
    unlimited_turns: terms.max_compiles === null,
    message: live
      ? (env.message ?? 'Session budget confirmed — we can talk.')
      : (env.message ?? env.text ?? 'Could not open a session envelope.'),
  };
}

/**
 * ENVELOPE RAISE — "go past it". Reaching the cap stops the steward and asks; this is
 * John answering "carry on". Still a human confirmation, still recorded with who.
 */
export function buildEnvelopeRaisePayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      mode: 'envelope-raise',
      error: 'envelope_bad_json',
      message: 'envelope-raise needs JSON { project_path, max_spend_usd, who? }',
    };
  }
  const projectPath = fields.project_path ?? opts.project;
  if (!projectPath) return { ok: false, mode: 'envelope-raise', error: 'missing_project' };

  const raised = raiseSessionEnvelope(projectPath, {
    who: normalizeClaimedWho(fields.who ?? 'john'),
    max_spend_usd: fields.max_spend_usd,
    client_event_id: fields.client_event_id,
  });
  return {
    ...raised,
    mode: 'envelope-raise',
    ok: raised.ok === true,
    message: raised.message ?? raised.text ?? 'Could not raise the session budget.',
  };
}

/** Read confirmed vN and open vN+1 without merging them. */
export function buildKickoffShowPayload(opts = {}) {
  if (!opts.project) return { ok: false, error: 'missing_project', mode: 'kickoff-show' };
  // The pre-Gate-5 roadmap view stays at the top level for the chamber that reads it;
  // `store` is what a fresh session paints from events.jsonl alone (prose + both hashes).
  const legacy = showKickoff(opts.project);
  const store = showKickoffSpoken(opts.project);
  return { ...legacy, store, mode: 'kickoff-show', ok: legacy.ok === true && store.ok === true };
}

/** One hash-bound human confirmation of the currently open kickoff version. */
export function buildKickoffConfirmPayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      mode: 'kickoff-confirm',
      error: 'kickoff_bad_json',
      message: 'kickoff-confirm needs JSON { project_path, proposal_hash, prior_confirmed_hash, who }',
    };
  }
  const projectPath = fields.project_path ?? opts.project;
  if (!projectPath) return { ok: false, error: 'missing_project', mode: 'kickoff-confirm' };
  // ONE spoken confirmation: the receipt lands on the store bound to BOTH hashes John saw
  // (a caller that sent only the record hash has the prose hash resolved from that exact
  // record, and the result says so), then the confirmed bundle is mirrored into the
  // roadmap / Face / Strip the chamber paints today.
  const confirmed = confirmKickoffSpoken(projectPath, {
    proposal_hash: fields.proposal_hash,
    rendered_prose_hash: fields.rendered_prose_hash,
    prior_confirmed_hash: fields.prior_confirmed_hash,
    who: fields.who ?? 'john',
    client_event_id: fields.client_event_id,
    project_id: fields.project_id,
    at: fields.at,
  });
  if (confirmed.ok === true && confirmed.already_confirmed !== true) {
    noteStewardEffort({
      kind: 'kickoff_confirmed',
      project_path: projectPath,
      project_id: fields.project_id ?? null,
      summary: `Confirmed kickoff v${confirmed.proposal?.version ?? '?'} with ${(confirmed.proposal?.plan_entries ?? []).length} plan entries`,
    });
  }
  return {
    ...confirmed,
    mode: 'kickoff-confirm',
    hash_bound: confirmed.ok === true,
  };
}

/** Repair Face/Strip from canonical kickoff truth after a projection crash. */
export function buildKickoffReplayPayload(opts = {}) {
  let fields = {};
  try {
    fields = opts.json ? JSON.parse(opts.json) : {};
  } catch {
    return { ok: false, error: 'kickoff_bad_json', mode: 'kickoff-replay' };
  }
  const projectPath = fields.project_path ?? opts.project;
  if (!projectPath) return { ok: false, error: 'missing_project', mode: 'kickoff-replay' };
  return {
    ...replayKickoff(projectPath, { who: fields.who ?? 'john', at: fields.at }),
    mode: 'kickoff-replay',
  };
}

/**
 * SCAFFOLD CONFIRM — the one write. Opens the session envelope, proposes through the
 * spine, then batch-confirms, so the steps land in roadmap_events via the single writer.
 * Mirrors the sequence T-HOST-0 proves.
 *
 * (2026-08-04) When a `proposal_hash` is supplied — the conversational path, where the
 * proposal is ALREADY a typed scaffold_proposal on the ledger — this binds straight to
 * that proposal and does NOT re-derive stages from prose. Re-deriving would silently
 * re-run the dead keyword matcher and confirm something OTHER than what John reviewed,
 * as well as double-debiting the compile. Hash-binding is what makes "confirm exactly
 * what you saw" true.
 */
export function buildScaffoldConfirmPayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      mode: 'scaffold-confirm',
      error: 'scaffold_bad_json',
      message: 'scaffold-confirm needs JSON { project_path, goal, description|stages, who? }',
    };
  }
  const projectPath = fields.project_path ?? opts.project;
  if (!projectPath) {
    return { ok: false, mode: 'scaffold-confirm', error: 'missing_project' };
  }

  const who = normalizeClaimedWho(fields.who ?? 'john');
  const { terms_hash } = currentBudgetTermsHash();
  const idem = fields.client_event_id ?? `scaffold-${fields.proposal_id ?? 'confirm'}`;

  // Name the real problem rather than letting an empty confirm fall through to the
  // prose path and answer SCAFFOLD_EMPTY ("I couldn't derive any stages from that
  // description") — which points at the wrong thing and opens an envelope on the way.
  if (!fields.proposal_hash && !fields.description && !fields.stages) {
    return {
      ok: false,
      mode: 'scaffold-confirm',
      error: 'nothing_to_confirm',
      message:
        'Nothing to confirm: pass the proposal_hash of the scaffolding you were shown '
        + '(or stages/description for the deterministic path). Nothing was written.',
    };
  }

  // CONVERSATIONAL PATH: the proposal already exists on the ledger as a typed
  // scaffold_proposal. Bind to it by hash — never re-derive from prose.
  if (fields.proposal_hash) {
    const confirmed = batchConfirmScaffolding(projectPath, {
      proposal_hash: fields.proposal_hash,
      proposal_id: fields.proposal_id,
      who,
      client_event_id: `${idem}-confirm`,
      at: fields.at ?? new Date().toISOString().slice(0, 10),
    });
    if (confirmed.ok === true) {
      // The moment a scaffolding becomes real work — the effort worth remembering at
      // portfolio altitude. Best-effort; bookkeeping never fails a confirmed write.
      noteStewardEffort({
        kind: 'scaffold_confirmed',
        project_path: projectPath,
        project_id: fields.project_id ?? null,
        summary: `Confirmed ${(confirmed.step_ids ?? []).length} stages onto the roadmap`,
      });
    }
    return {
      ...confirmed,
      mode: 'scaffold-confirm',
      ok: confirmed.ok === true,
      hash_bound: true,
      step_ids: confirmed.step_ids ?? [],
    };
  }

  // MINT ONLY IF THERE IS NO LIVE ENVELOPE (2026-08-04).
  //
  // This used to mint unconditionally, which meant every confirm created a NEW
  // envelope carrying the DEFAULT bounds — so a user-set spend cap was silently
  // replaced by $5.00/25 on the very next write, and the cap could never bind. It
  // also reset spend to zero each time, which makes a budget meaningless.
  const liveState = readEnvelopeState(projectPath, {});
  const env = liveState.ok && liveState.live
    ? { ok: true, already_live: true, envelope: liveState }
    : confirmSessionEnvelope(projectPath, {
      who,
      terms_hash,
      client_event_id: `${idem}-env`,
      credential_class: 'none',
    });
  if (env.ok !== true && env.already_live !== true) {
    return {
      ok: false,
      mode: 'scaffold-confirm',
      error: env.error ?? env.code ?? 'envelope_refused',
      message: env.message ?? env.text ?? 'Could not open a session envelope.',
    };
  }

  const proposed = proposeScaffolding(projectPath, {
    goal: fields.goal ?? null,
    description: fields.description ?? null,
    stages: fields.stages ?? null,
    client_event_id: `${idem}-propose`,
  });
  if (proposed.ok !== true) {
    return {
      ok: false,
      mode: 'scaffold-confirm',
      error: proposed.code ?? proposed.error ?? 'propose_failed',
      message: proposed.message ?? proposed.text ?? 'Could not propose the scaffolding.',
    };
  }

  const confirmed = batchConfirmScaffolding(projectPath, {
    proposal_hash: proposed.proposal_hash,
    proposal: proposed.proposal,
    proposal_id: proposed.proposal_id,
    who,
    client_event_id: `${idem}-confirm`,
    at: fields.at ?? new Date().toISOString().slice(0, 10),
  });
  return {
    ...confirmed,
    mode: 'scaffold-confirm',
    ok: confirmed.ok === true,
    step_ids: confirmed.step_ids ?? [],
  };
}

/**
 * Dispatch one bridge invocation (SYNCHRONOUS — used by tests and by main).
 *
 * Stays sync on purpose: w11/w14 call runBridge() directly and assert on the returned
 * object, so making this async would hand them a Promise and break assertions that have
 * nothing to do with this change. The one async mode (converse) is dispatched by
 * runBridgeAsync below.
 */
export function runBridge(argv = []) {
  const args = parseBridgeArgs(argv);
  if (args.envelopeConfirm != null)
    return buildEnvelopeConfirmPayload({ json: args.envelopeConfirm, project: args.project });
  if (args.envelopeRaise != null)
    return buildEnvelopeRaisePayload({ json: args.envelopeRaise, project: args.project });
  if (args.kickoffConfirm != null)
    return buildKickoffConfirmPayload({ json: args.kickoffConfirm, project: args.project });
  if (args.kickoffReplay != null)
    return buildKickoffReplayPayload({ json: args.kickoffReplay, project: args.project });
  if (args.scaffoldConfirm != null)
    return buildScaffoldConfirmPayload({ json: args.scaffoldConfirm, project: args.project });
  if (args.standUpConfirm != null)
    return buildStandUpConfirmPayload({ json: args.standUpConfirm });
  if (args.notNow) return { ...standUpNotNow(), mode: 'stand-up-not-now' };
  if (!args.project) {
    return {
      ok: false,
      error: 'missing_project',
      message:
        'usage: --project <path> [--speak <text> | --recall <question>] | --stand-up-confirm <json> | --not-now',
    };
  }
  if (args.kickoffShow) return buildKickoffShowPayload({ project: args.project });
  if (args.scaffoldPreview != null)
    return buildScaffoldPreviewPayload({
      project: args.project,
      text: args.scaffoldPreview,
      goal: args.goal ?? null,
    });
  if (args.stepDetail != null) return buildStepDetailPayload({ project: args.project, step_id: args.stepDetail });
  if (args.stepNote != null) {
    return buildStepNotePayload({
      project: args.project, step_id: args.stepNote, note: args.note, who: args.who,
    });
  }
  if (args.speak != null) return buildSpeakPayload({ project: args.project, text: args.speak });
  if (args.recall != null) return buildRecallPayload({ project: args.project, question: args.recall });
  return buildChamberPayload({ project: args.project });
}

/**
 * Async dispatch — the real entry point. Everything except `--converse` is handled by
 * the synchronous runBridge; converse needs a seat call, which is async by nature.
 */
export async function runBridgeAsync(argv = []) {
  const args = parseBridgeArgs(argv);
  if (args.converse != null) {
    if (!args.project) {
      return { ok: false, error: 'missing_project', mode: 'converse' };
    }
    return buildConversePayload({
      project: args.project,
      text: args.converse,
      turns: args.turns,
      who: args.who,
      asOf: args.asOf,
      clientEventId: args.clientEventId,
    });
  }
  return runBridge(argv);
}

const invokedDirectly =
  process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, '/').split('/').pop());

if (invokedDirectly) {
  let result;
  try {
    result = await runBridgeAsync(process.argv.slice(2));
  } catch (err) {
    result = { ok: false, error: 'bridge_failed', message: String(err?.message ?? err) };
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.ok ? 0 : 1;
}
