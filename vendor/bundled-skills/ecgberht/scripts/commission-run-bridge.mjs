/**
 * COMMISSION RUN BRIDGE — the host's one door for "the steward runs a skill".
 *
 * Spawned by Anchor (`node scripts/commission-run-bridge.mjs <mode>`), payload
 * on STDIN as one JSON object — never argv. Two hard-won facts drive that:
 * argv caps at 32,767 chars on Windows (a transcript crosses it instantly),
 * and the PTY transcript can carry every kind of quoting hazard.
 *
 * Modes (payload fields beyond `project` in brackets):
 *   propose-active  [step_id?, skill?, depth?]  → resolve the step in hand and
 *                   propose the commission for it (skill from the step's type
 *                   when not given). READ-ONLY — requires_confirm rides back.
 *   confirm         [proposal, who, job_id?]    → John's confirm; the bind is
 *                   written through the existing journaled spine path.
 *   ingest-run      [run{outcome, transcript, …}, project_id?] → the run came
 *                   home: report → conversation log → raise → handback ingest
 *                   (engine/steward-run-ingest.mjs), real seat call injected.
 *
 * Output: ONE JSON object on stdout. Exit 0 iff ok.
 */

import { verbCommissionPropose, verbCommissionConfirm } from '../engine/job-lifecycle.mjs';
import { ingestCommissionRun } from '../engine/steward-run-ingest.mjs';
import { loadProjectRoadmap } from '../engine/roadmap.mjs';
import { findActiveStep } from '../engine/steward-conversation.mjs';
import { skillForStepType } from '../engine/step-type-map.mjs';
import { indexPathsFrom } from '../engine/append-log.mjs';
import { makeSeatCall } from './seat-call.mjs';

export const BRIDGE_MODES = Object.freeze(['propose-active', 'confirm', 'ingest-run']);

/** Read all of stdin (the payload transport — never argv). */
export function readStdin(stream = process.stdin) {
  return new Promise((resolve, reject) => {
    let data = '';
    stream.setEncoding('utf8');
    stream.on('data', (d) => { data += d; });
    stream.on('end', () => resolve(data));
    stream.on('error', reject);
  });
}

/**
 * Resolve the step a commission is FOR: an explicit step_id wins; otherwise
 * the step in hand (running, else first not-done) — the same rule the
 * conversation uses, so the chamber and the commission agree on "this step".
 *
 * @param {object} roadmap loaded roadmap
 * @param {string|null} stepId
 * @returns {{ ok: boolean, step?: object, error?: string, message?: string }}
 */
export function resolveCommissionStep(roadmap, stepId = null) {
  const projection = Array.isArray(roadmap?.roadmap_projection)
    ? roadmap.roadmap_projection
    : [];

  let step = null;
  if (stepId) {
    step = projection.find((s) => (s.step_id ?? s.id) === stepId) ?? null;
    if (!step) {
      return { ok: false, error: 'unknown_step', message: `No roadmap step '${stepId}'.` };
    }
  } else {
    step = findActiveStep(projection);
    if (!step) {
      return {
        ok: false,
        error: 'no_open_step',
        message: 'No open roadmap step to commission — confirm a scaffolding first.',
      };
    }
  }

  // The projection intentionally keeps only run-state fields; the step's TYPE
  // (RESEARCH/PLAN/BUILD/REVIEW → skill) lives on its step_create event, where
  // the confirmed scaffolding wrote it.
  const id = step.step_id ?? step.id;
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  const created = events.find(
    (e) => e && e.kind === 'step_create' && (e.step_id ?? e.id) === id,
  );
  const step_type = step.step_type ?? created?.step_type ?? null;

  return { ok: true, step: step_type ? { ...step, step_type } : { ...step } };
}

async function proposeActive(payload) {
  const project = payload.project;
  if (!project) return { ok: false, error: 'missing_project', mode: 'propose-active' };

  const loaded = loadProjectRoadmap(project);
  if (!loaded.ok || !loaded.exists) {
    return {
      ok: false,
      error: 'no_roadmap',
      mode: 'propose-active',
      message: 'No roadmap yet — the steward commissions FOR a confirmed step.',
    };
  }
  const resolved = resolveCommissionStep(loaded.roadmap, payload.step_id ?? null);
  if (!resolved.ok) return { ...resolved, mode: 'propose-active' };
  const step = resolved.step;
  const step_id = step.step_id ?? step.id;

  // Skill: explicit > the step's own type. Refused honestly when neither —
  // the steward never guesses which engine to spend money on.
  let skill = payload.skill ?? null;
  if (!skill && step.step_type) {
    const mapped = skillForStepType(step.step_type);
    if (mapped.ok) skill = mapped.skill;
  }
  if (!skill) {
    return {
      ok: false,
      error: 'skill_unresolved',
      mode: 'propose-active',
      step_id,
      message:
        `Step '${step.name ?? step_id}' names no type I can map to a skill — say which `
        + 'skill to commission (researchPrime, Crucible, Foreman, Gandalf, Jumper).',
    };
  }

  const proposal = verbCommissionPropose({
    project,
    step: step_id,
    skill,
    depth_cell: payload.depth ?? null,
    who: payload.who ?? 'ecgberht-steward',
    env: process.env,
  });
  return { ...proposal, mode: 'propose-active', step_name: step.name ?? null };
}

async function confirm(payload) {
  const project = payload.project;
  if (!project) return { ok: false, error: 'missing_project', mode: 'confirm' };
  if (!payload.proposal || typeof payload.proposal !== 'object') {
    return { ok: false, error: 'missing_proposal', mode: 'confirm' };
  }
  // verbCommissionConfirm wants the PLAIN who string (it writes its own
  // receipt); normalizeClaimedWho's stamped OBJECT fails its nonEmpty check —
  // found live: "commission-confirm requires --who" with who present.
  const who = String(payload.who ?? 'john').trim() || 'john';
  const confirmed = verbCommissionConfirm({
    project,
    proposal: payload.proposal,
    who,
    job_id: payload.job_id ?? null,
    client_event_id: payload.client_event_id ?? null,
    env: process.env,
  });
  return { ...confirmed, mode: 'confirm' };
}

async function ingestRun(payload) {
  const project = payload.project;
  if (!project) return { ok: false, error: 'missing_project', mode: 'ingest-run' };

  // The RAISE must land on the SAME index the High Seat reads. publishAttention
  // deliberately refuses ambient default-home writes (a test that forgot the
  // env must not touch the operator's real home) — so this production bridge
  // resolves the home EXPLICITLY, exactly the way `steward register` does, and
  // passes it. An unresolvable home degrades to a project-cell-only raise.
  let home = payload.home ?? null;
  if (!home) {
    try {
      home = indexPathsFrom({ env: process.env }).home;
    } catch {
      home = null;
    }
  }

  const result = await ingestCommissionRun(project, payload.run ?? {}, {
    seatCall: makeSeatCall(),
    env: process.env,
    home,
    project_id: payload.project_id ?? null,
    who: payload.who ?? 'steward-run-ingest',
  });
  return { ...result, mode: 'ingest-run' };
}

/** Dispatch one bridge invocation. Exported for the test suite. */
export async function runCommissionBridge(mode, payload) {
  if (mode === 'propose-active') return proposeActive(payload ?? {});
  if (mode === 'confirm') return confirm(payload ?? {});
  if (mode === 'ingest-run') return ingestRun(payload ?? {});
  return {
    ok: false,
    error: 'unknown_mode',
    message: `Mode must be one of: ${BRIDGE_MODES.join(', ')}`,
    mode: mode ?? null,
  };
}

const invokedDirectly =
  process.argv[1] &&
  import.meta.url.endsWith(process.argv[1].replace(/\\/g, '/').split('/').pop());

if (invokedDirectly) {
  let result;
  try {
    const mode = process.argv[2] ?? null;
    const raw = await readStdin();
    let payload = {};
    if (raw.trim()) {
      try {
        payload = JSON.parse(raw);
      } catch (e) {
        result = { ok: false, error: 'payload_unparseable', message: String(e?.message ?? e) };
      }
    }
    if (!result) result = await runCommissionBridge(mode, payload);
  } catch (err) {
    result = { ok: false, error: 'bridge_failed', message: String(err?.message ?? err) };
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.ok ? 0 : 1;
}
