/**
 * Conversational kickoff synthesis v0 - the LIFECYCLE seam.
 *
 * Steward may propose one compact goal/product/plan synthesis while a project
 * has no Face. The proposal is model-authored and explicitly non-authoritative.
 * A human-confirmed, hash-bound kickoff_confirm event makes the exact version
 * authoritative. Face and Strip are projections repaired after that canonical
 * append; neither is a precondition for brainstorming or confirmation.
 *
 * Gate 5 / Wave 1 (seam inspection recorded in
 * planning/gate5-kickoff-synthesis-2026-08-31/wave1-seam-inspection-kickoff.md):
 * the RECORD - compile, canonical bytes, hashing, the one renderer, and the
 * failure table - lives in engine/kickoff-record.mjs and is re-exported here so
 * every existing caller keeps one seam. The tautology classifier that used to
 * live in this file is gone; the compiler now generates nothing, so there is
 * nothing to classify. What stays here: lineage projection, propose, confirm,
 * show, replay.
 */

import fs from 'node:fs';
import path from 'node:path';

import { authorize } from './authorize.mjs';
import { writeFileAtomicSync, withFileLock, LOCK_TIMEOUT_MS } from './durable-write.mjs';
import { applyIncrementalFaceRewrite } from './face-compile.mjs';
import {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  loadProjectSurfaces,
} from './face-strip.mjs';
import { normalizeClaimedWho, WHO_PROVENANCE } from './identity-policy.mjs';
import {
  KICKOFF_CODE,
  KICKOFF_PROPOSAL_KIND,
  compileKickoffProposal,
  kickoffFailure,
  kickoffHashBody,
  recomputeKickoffHash,
  validateKickoffProposal,
} from './kickoff-record.mjs';
import {
  appendRoadmapEventThroughSpine,
  roadmapLedgerPath,
} from './ledger-spine.mjs';
import {
  appendRoadmapEvent,
  emptyRoadmap,
  loadProjectRoadmap,
  projectRoadmapBytes,
  validateRoadmap,
} from './roadmap.mjs';
import { confirmStandUp } from './stand-up.mjs';

// The record law is one module; this seam re-exports it so callers need one import.
export {
  KICKOFF_PROPOSAL_SCHEMA,
  KICKOFF_PROPOSAL_KIND,
  KICKOFF_RELATIONSHIP_KINDS,
  KICKOFF_FORBIDDEN_FIELDS,
  KICKOFF_CODE,
  KICKOFF_TEXT,
  kickoffFailure,
  kickoffFailureTable,
  canonicalKickoffBytes,
  hashKickoffPayload,
  kickoffHashBody,
  recomputeKickoffHash,
  resolveKickoffProvenance,
  validateKickoffContent,
  validateKickoffProposal,
  normalizeKickoffInput,
  compileKickoffProposal,
  renderKickoffProposal,
} from './kickoff-record.mjs';

// Gate 5 / Wave 2: the lifecycle on the one store (<folder>/.ecgberht/kickoff/events.jsonl)
// lives in engine/kickoff-lifecycle.mjs and rides through this seam too. The roadmap-ledger
// verbs below are the pre-Gate-5 WH4 path; Wave 3 points the conversation at the store.
export {
  KICKOFF_DIR_REL,
  KICKOFF_EVENTS_FILE,
  KICKOFF_EVENTS_REL,
  KICKOFF_EVENTS_MAX_BYTES,
  KICKOFF_RECEIPT_SCHEMA,
  KICKOFF_EVENT_KIND,
  KICKOFF_STATE,
  KICKOFF_APPEND_PRIMITIVE,
  KICKOFF_LOCK_HELPER,
  kickoffEventsPath,
  kickoffLifecycleFailureTable,
  projectKickoffLineage,
  readKickoffLineage,
  openKickoffProposal,
  reproposeKickoff,
  confirmKickoffProposal,
  deriveConfirmedKickoff,
} from './kickoff-lifecycle.mjs';

const cleanText = (value) => String(value ?? '').trim();

function proposalFromEvent(event) {
  if (!event || event.kind !== KICKOFF_PROPOSAL_KIND) return null;
  const proposal = {
    ...kickoffHashBody(event),
    proposal_id: event.proposal_id,
    proposal_hash: event.proposal_hash,
  };
  // The event stores the rendered prose and its hash beside the record; carry both so
  // a reader (and Wave 2's confirm) can bind to what was actually shown.
  if (typeof event.rendered_prose === 'string') proposal.rendered_prose = event.rendered_prose;
  if (typeof event.rendered_prose_hash === 'string') {
    proposal.rendered_prose_hash = event.rendered_prose_hash;
  }
  return proposal;
}

/** Pure projection of confirmed and open kickoff intent from roadmap history. */
export function projectKickoff(roadmap) {
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  const proposals = new Map();
  const proposalOrder = [];
  const confirmedHashes = new Set();
  let confirmed = null;
  let confirmedEvent = null;

  for (const [index, event] of events.entries()) {
    if (event?.kind === 'kickoff_proposal') {
      const proposal = proposalFromEvent(event);
      const valid = validateKickoffProposal(proposal);
      if (!valid.ok) {
        return kickoffFailure(KICKOFF_CODE.CORRUPT, {
          error: 'kickoff_proposal_corrupt',
          at_index: index,
          issue: valid,
        });
      }
      if (proposals.has(proposal.proposal_hash)) {
        const prior = proposals.get(proposal.proposal_hash);
        if (JSON.stringify(prior) !== JSON.stringify(proposal)) {
          return kickoffFailure(KICKOFF_CODE.CORRUPT, {
            error: 'kickoff_hash_reused_for_different_content',
            at_index: index,
          });
        }
      } else {
        proposals.set(proposal.proposal_hash, proposal);
        proposalOrder.push(proposal);
      }
      continue;
    }
    if (event?.kind !== 'kickoff_confirm') continue;

    const proposal = proposals.get(event.proposal_hash);
    if (!proposal) {
      return kickoffFailure(KICKOFF_CODE.CORRUPT, {
        error: 'kickoff_confirm_without_proposal',
        at_index: index,
        proposal_hash: event.proposal_hash ?? null,
      });
    }
    if (confirmedHashes.has(proposal.proposal_hash)) continue;
    const priorHash = confirmed?.proposal_hash ?? null;
    if (proposal.prior_confirmed_hash !== priorHash
        || event.prior_confirmed_hash !== priorHash
        || event.version !== proposal.version
        || proposal.version !== (confirmed?.version ?? 0) + 1) {
      return kickoffFailure(KICKOFF_CODE.CORRUPT, {
        error: 'kickoff_confirmation_lineage_invalid',
        at_index: index,
        proposal_hash: proposal.proposal_hash,
        expected_prior_confirmed_hash: priorHash,
      });
    }
    confirmed = proposal;
    confirmedEvent = event;
    confirmedHashes.add(proposal.proposal_hash);
  }

  const nextVersion = (confirmed?.version ?? 0) + 1;
  const priorHash = confirmed?.proposal_hash ?? null;
  let open = null;
  for (const proposal of proposalOrder) {
    if (!confirmedHashes.has(proposal.proposal_hash)
        && proposal.version === nextVersion
        && proposal.prior_confirmed_hash === priorHash) {
      open = proposal;
    }
  }

  return {
    ok: true,
    authority: confirmed ? 'kickoff_confirm' : 'none',
    confirmed,
    confirmed_event: confirmedEvent,
    open,
    next_version: nextVersion,
    proposal_count: proposalOrder.length,
    confirmation_count: confirmedHashes.size,
  };
}

function loadHealthyRoadmap(projectPath, projectId = null) {
  const loaded = loadProjectRoadmap(projectPath);
  if (!loaded.ok && loaded.exists) {
    return kickoffFailure(KICKOFF_CODE.ROADMAP_UNREADABLE, {
      error: 'roadmap_unreadable',
      detail: loaded.message ?? loaded.error,
    });
  }
  const roadmap = loaded.exists ? loaded.roadmap : emptyRoadmap(projectId);
  const validated = validateRoadmap(roadmap);
  if (!validated.ok) {
    return kickoffFailure(KICKOFF_CODE.ROADMAP_UNREADABLE, {
      error: 'roadmap_invalid',
      detail: validated,
    });
  }
  return { ok: true, exists: loaded.exists, roadmap };
}

/** Read-only engine verb: show confirmed vN and any open vN+1 separately. */
export function showKickoff(projectPath) {
  const root = path.resolve(projectPath);
  const loaded = loadHealthyRoadmap(root);
  if (!loaded.ok) return loaded;
  const projected = projectKickoff(loaded.roadmap);
  if (!projected.ok) return projected;
  return {
    ...projected,
    project_path: root,
    roadmap_exists: loaded.exists,
    applied: projected.confirmed != null,
  };
}

/** Append a full non-authoritative proposal. Face and an envelope are not required. */
export function proposeKickoff(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const loaded = loadHealthyRoadmap(root, opts.project_id ?? null);
  if (!loaded.ok) return loaded;
  const current = projectKickoff(loaded.roadmap);
  if (!current.ok) return current;

  const expectedVersion = current.next_version;
  const expectedPrior = current.confirmed?.proposal_hash ?? null;
  if (opts.proposal?.version != null && Number(opts.proposal.version) !== expectedVersion) {
    return kickoffFailure(KICKOFF_CODE.STALE, {
      error: 'proposal_version_stale',
      expected_version: expectedVersion,
      provided_version: Number(opts.proposal.version),
    });
  }
  if (opts.proposal?.prior_confirmed_hash !== undefined
      && opts.proposal.prior_confirmed_hash !== expectedPrior) {
    return kickoffFailure(KICKOFF_CODE.STALE, {
      error: 'proposal_prior_confirmation_stale',
      expected_prior_confirmed_hash: expectedPrior,
      provided_prior_confirmed_hash: opts.proposal.prior_confirmed_hash,
    });
  }

  // Provenance is the HOST's assertion (which seat answered), never the reply's claim:
  // a provenance-less or zero_model input is refused inside compile, before any write.
  const compiled = compileKickoffProposal(opts.proposal ?? opts, {
    version: expectedVersion,
    prior_confirmed_hash: expectedPrior,
    source_turn_id: opts.source_turn_id ?? opts.client_event_id ?? null,
    source_turn_at: opts.source_turn_at ?? opts.at ?? null,
    seat_family: opts.seat_family,
    driver: opts.driver,
    provenance: opts.provenance,
  });
  if (!compiled.ok) return compiled;
  const proposal = compiled.proposal;
  const clientEventId = opts.client_event_id
    ?? `kickoff-propose-${proposal.proposal_hash.slice(0, 16)}`;
  // The proposal event stores the record + its hash AND the rendered prose + its hash.
  const event = {
    ...proposal,
    rendered_prose: compiled.rendered_prose,
    rendered_prose_hash: compiled.rendered_prose_hash,
    client_event_id: clientEventId,
    at: opts.at,
  };
  const appended = appendRoadmapEventThroughSpine(root, event, {
    project_id: opts.project_id,
    skip_index: opts.skip_index !== false ? opts.skip_index ?? true : false,
    at: opts.at,
  });
  if (!appended.ok) {
    return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
      error: 'kickoff_proposal_append_failed',
      detail: appended,
    });
  }
  return {
    ok: true,
    phase: 'proposed',
    authoritative: false,
    applied: false,
    proposal,
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    rendered_prose: compiled.rendered_prose,
    rendered_prose_hash: compiled.rendered_prose_hash,
    version: proposal.version,
    event: appended.event,
    roadmap: appended.roadmap,
    projection: appended.projection,
    plan_entries_written: false,
    face_written: false,
    idempotent: appended.idempotent === true,
  };
}

function findConfirmByClientId(roadmap, clientEventId) {
  if (!clientEventId) return null;
  return (roadmap?.roadmap_events ?? []).find(
    (event) => event?.kind === 'kickoff_confirm'
      && event.client_event_id === clientEventId,
  ) ?? null;
}

function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function appendPlanProjection(current, proposal, confirmEventId, who, at) {
  let roadmap = current;
  const appended = [];
  for (const entry of proposal.plan_entries) {
    const existing = (roadmap.roadmap_projection ?? []).find((step) => step.id === entry.id);
    if (!existing) {
      const created = appendRoadmapEvent(roadmap, {
        kind: 'step_create',
        step_id: entry.id,
        name: entry.name,
        status: 'planned',
        done_when: entry.done_when,
        component_ids: [...entry.component_ids],
        end_to_end_slice: entry.end_to_end_slice,
        kickoff_version: proposal.version,
        kickoff_proposal_hash: proposal.proposal_hash,
        steward_authored: true,
        provenance: {
          author: 'steward',
          source: 'kickoff_confirm',
          proposal_id: proposal.proposal_id,
          proposal_hash: proposal.proposal_hash,
        },
        who,
        who_provenance: WHO_PROVENANCE,
        client_event_id: `${confirmEventId}#plan:${entry.id}`,
        at,
      }, { at });
      if (!created.ok) return created;
      roadmap = created.roadmap;
      appended.push(created.event);
      continue;
    }

    if (!existing.kickoff_proposal_hash) {
      return kickoffFailure(KICKOFF_CODE.PLAN_CONFLICT, {
        error: 'plan_entry_id_conflicts_with_non_kickoff_step',
        plan_entry_id: entry.id,
      });
    }
    const desired = {
      name: entry.name,
      done_when: entry.done_when,
      component_ids: [...entry.component_ids],
      end_to_end_slice: entry.end_to_end_slice,
      kickoff_version: proposal.version,
      kickoff_proposal_hash: proposal.proposal_hash,
    };
    const fields = Object.fromEntries(
      Object.entries(desired).filter(([key, value]) => !sameValue(existing[key], value)),
    );
    if (!Object.keys(fields).length) continue;
    const updated = appendRoadmapEvent(roadmap, {
      kind: 'step_set',
      step_id: entry.id,
      fields,
      provenance: {
        author: 'steward',
        source: 'kickoff_confirm',
        proposal_id: proposal.proposal_id,
        proposal_hash: proposal.proposal_hash,
      },
      who,
      who_provenance: WHO_PROVENANCE,
      client_event_id: `${confirmEventId}#plan:${entry.id}`,
      at,
    }, { at });
    if (!updated.ok) return updated;
    roadmap = updated.roadmap;
    appended.push(updated.event);
  }
  return { ok: true, roadmap, events: appended };
}

function projectConfirmedKickoffToFace(projectPath, proposal, opts = {}) {
  const root = path.resolve(projectPath);
  const when = cleanText(opts.at || new Date().toISOString()).slice(0, 10);
  const who = normalizeClaimedWho(opts.who);
  const dry = confirmStandUp({
    project_path: root,
    north_star: proposal.goal,
    active_effort: proposal.plan_entries[0]?.name ?? proposal.work_product.name,
    who: who?.claimed ?? 'john',
    when,
    write: false,
    surfaces: { face: null, strip: null },
    receipt_note: 'kickoff: model-authored synthesis reviewed and confirmed by the human',
  });
  if (!dry.ok) {
    return { ok: false, error: 'kickoff_face_projection_refused', detail: dry };
  }

  try {
    fs.mkdirSync(root, { recursive: true });
    let surfaces = loadProjectSurfaces(root);
    const files = [];
    if (!surfaces.face) {
      writeFileAtomicSync(path.join(root, FACE_FILE_NAME), dry.face_markdown);
      files.push(FACE_FILE_NAME);
    } else if (surfaces.face.narrative?.north_star !== proposal.goal) {
      const rewritten = applyIncrementalFaceRewrite(
        root,
        { north_star: { value: proposal.goal, provenance: {
          source: 'kickoff_confirm',
          proposal_hash: proposal.proposal_hash,
        } } },
        { changed: ['north_star'], added: [], removed: [] },
      );
      if (!rewritten.ok) return rewritten;
      if (rewritten.rewritten) files.push(FACE_FILE_NAME);
    }
    surfaces = loadProjectSurfaces(root);
    if (!surfaces.strip) {
      writeFileAtomicSync(
        path.join(root, STRIP_FILE_NAME),
        `${JSON.stringify(dry.strip, null, 2)}\n`,
      );
      files.push(STRIP_FILE_NAME);
    }
    return {
      ok: true,
      repaired: files.length > 0,
      files,
      proposal_hash: proposal.proposal_hash,
      version: proposal.version,
    };
  } catch (error) {
    return {
      ok: false,
      error: 'kickoff_face_projection_failed',
      detail: String(error?.message ?? error),
    };
  }
}

/**
 * Confirm an open proposal with optimistic lineage CAS. The canonical roadmap
 * append commits before Face/Strip projection; projection failure is reported
 * as repair-pending while confirmation remains successful and replayable.
 */
export function confirmKickoff(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const who = normalizeClaimedWho(opts.who);
  if (!who) {
    return kickoffFailure(KICKOFF_CODE.WHO_REQUIRED, { error: 'who_required' });
  }
  if (opts.auth != null) {
    const decision = authorize('confirm', opts.auth);
    if (!decision || decision.ok !== true) {
      return kickoffFailure(KICKOFF_CODE.AUTH_REFUSED, {
        error: 'auth_refused',
        auth: decision ?? { ok: false },
      });
    }
  }
  const providedHash = cleanText(opts.proposal_hash ?? opts.proposal?.proposal_hash);
  if (!/^[a-f0-9]{64}$/.test(providedHash)) {
    return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
      error: 'proposal_hash_missing_or_invalid',
    });
  }
  const clientEventId = opts.client_event_id
    ?? `kickoff-confirm-${providedHash.slice(0, 16)}`;
  const ledgerPath = roadmapLedgerPath(root);
  let committed;

  try {
    committed = withFileLock(ledgerPath, () => {
      const loaded = loadHealthyRoadmap(root, opts.project_id ?? null);
      if (!loaded.ok) return loaded;
      let roadmap = loaded.roadmap;
      const projection = projectKickoff(roadmap);
      if (!projection.ok) return projection;

      const priorById = findConfirmByClientId(roadmap, clientEventId);
      if (priorById) {
        if (priorById.proposal_hash !== providedHash) {
          return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
            error: 'confirm_client_event_id_reused',
            prior_proposal_hash: priorById.proposal_hash,
          });
        }
        return {
          ok: true,
          canonical_committed: true,
          already_confirmed: true,
          idempotent: true,
          ledger_write: false,
          proposal: projection.confirmed,
          proposal_hash: providedHash,
          roadmap,
          plan_events: [],
        };
      }
      if (projection.confirmed?.proposal_hash === providedHash) {
        return {
          ok: true,
          canonical_committed: true,
          already_confirmed: true,
          idempotent: true,
          ledger_write: false,
          proposal: projection.confirmed,
          proposal_hash: providedHash,
          roadmap,
          plan_events: [],
        };
      }
      const proposal = projection.open;
      if (!proposal || proposal.proposal_hash !== providedHash) {
        return kickoffFailure(KICKOFF_CODE.STALE, {
          error: 'proposal_is_not_current_open_version',
          current_confirmed_hash: projection.confirmed?.proposal_hash ?? null,
          current_open_hash: projection.open?.proposal_hash ?? null,
        });
      }
      const expectedHash = recomputeKickoffHash(proposal);
      if (expectedHash !== providedHash) {
        return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
          error: 'confirm_hash_mismatch',
          expected_hash: expectedHash,
          provided_hash: providedHash,
        });
      }
      const currentPrior = projection.confirmed?.proposal_hash ?? null;
      const providedPrior = opts.prior_confirmed_hash !== undefined
        ? opts.prior_confirmed_hash : proposal.prior_confirmed_hash;
      if (providedPrior !== currentPrior || proposal.prior_confirmed_hash !== currentPrior) {
        return kickoffFailure(KICKOFF_CODE.STALE, {
          error: 'confirm_compare_and_swap_failed',
          expected_prior_confirmed_hash: currentPrior,
          provided_prior_confirmed_hash: providedPrior,
        });
      }

      const at = opts.at ?? new Date().toISOString();
      const confirmEvent = {
        kind: 'kickoff_confirm',
        proposal_id: proposal.proposal_id,
        proposal_hash: providedHash,
        version: proposal.version,
        prior_confirmed_hash: currentPrior,
        who,
        who_provenance: WHO_PROVENANCE,
        client_event_id: clientEventId,
        at,
      };
      const confirmedLaw = appendRoadmapEvent(roadmap, confirmEvent, { at });
      if (!confirmedLaw.ok) return confirmedLaw;
      roadmap = confirmedLaw.roadmap;

      const plan = appendPlanProjection(roadmap, proposal, clientEventId, who, at);
      if (!plan.ok) return plan;
      roadmap = plan.roadmap;
      fs.mkdirSync(root, { recursive: true });
      writeFileAtomicSync(ledgerPath, projectRoadmapBytes(roadmap));
      return {
        ok: true,
        canonical_committed: true,
        already_confirmed: false,
        idempotent: false,
        ledger_write: true,
        confirm_event: confirmedLaw.event,
        proposal,
        proposal_hash: providedHash,
        roadmap,
        plan_events: plan.events,
      };
    }, {
      timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
    });
  } catch (error) {
    return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
      error: error?.code === 'ELOCKTIMEOUT' ? 'kickoff_lock_contended' : 'kickoff_confirm_failed',
      detail: String(error?.message ?? error),
    });
  }
  if (!committed.ok) return committed;

  let face;
  try {
    face = typeof opts.projectFace === 'function'
      ? opts.projectFace(root, committed.proposal, { who, at: opts.at })
      : projectConfirmedKickoffToFace(root, committed.proposal, {
        who,
        at: opts.at,
      });
  } catch (error) {
    face = {
      ok: false,
      error: 'kickoff_face_projection_failed',
      detail: String(error?.message ?? error),
    };
  }
  return {
    ...committed,
    phase: 'confirmed',
    authoritative: true,
    applied: true,
    plan_entries_written: committed.plan_events.length,
    projection: face,
    projection_pending: face.ok !== true,
  };
}

/** Repair/replay Face and Strip from the latest canonical kickoff confirmation. */
export function replayKickoff(projectPath, opts = {}) {
  const shown = showKickoff(projectPath);
  if (!shown.ok) return shown;
  if (!shown.confirmed) {
    return kickoffFailure(KICKOFF_CODE.NOTHING_CONFIRMED, {
      error: 'no_confirmed_kickoff',
      open: shown.open,
    });
  }
  const projection = projectConfirmedKickoffToFace(projectPath, shown.confirmed, {
    who: opts.who ?? shown.confirmed_event?.who ?? 'john',
    at: opts.at ?? shown.confirmed_event?.at,
  });
  return {
    ok: projection.ok === true,
    phase: 'replayed',
    authoritative: true,
    proposal: shown.confirmed,
    proposal_hash: shown.confirmed.proposal_hash,
    version: shown.confirmed.version,
    projection,
  };
}

// Named aliases for host/bridge code that treats these exports as engine verbs.
export const kickoffShow = showKickoff;
export const kickoffConfirm = confirmKickoff;
export const kickoffReplay = replayKickoff;
