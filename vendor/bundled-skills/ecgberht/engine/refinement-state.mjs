import { createHash } from 'node:crypto';

// This module is a deterministic projection of the existing roadmap event stream.
// File integrity, authenticated human input, operation idempotency and append/CAS
// belong to the roadmap writer, not to a second store in this module.
const SCHEMA = 'ecgberht-refinement-v1';
const FULL_ASSESSMENTS = [
  'RC-1', 'RC-2', 'RC-3', 'RC-4', 'RC-5', 'RC-6', 'RC-7', 'RC-8', 'RC-G',
];

function fail(code, detail) {
  const error = new Error(detail);
  error.code = code;
  error.detail = detail;
  throw error;
}

function demand(condition, code, detail) {
  if (!condition) fail(code, detail);
}

function nonempty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function identifier(value, name) {
  demand(nonempty(value) && !['__proto__', 'constructor', 'prototype'].includes(value),
    'INVALID_IDENTIFIER', name + ' must be a nonempty, nonreserved string.');
  return value;
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function clone(value) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    fail('INVALID_JSON', 'Refinement operations must contain serializable JSON values.');
  }
}

function canonical(value, ancestors = new Set()) {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    demand(Number.isFinite(value), 'INVALID_DIGEST_VALUE', 'Digests require finite JSON numbers.');
    return JSON.stringify(value);
  }
  demand(object(value) || Array.isArray(value), 'INVALID_DIGEST_VALUE',
    'Digests require JSON values; undefined and executable values are not supported.');
  demand(!ancestors.has(value), 'INVALID_DIGEST_VALUE', 'Digests cannot contain cycles.');
  ancestors.add(value);
  let result;
  if (Array.isArray(value)) {
    result = '[' + Array.from(value, item => canonical(item, ancestors)).join(',') + ']';
  } else {
    result = '{' + Object.keys(value).sort()
      .map(key => JSON.stringify(key) + ':' + canonical(value[key], ancestors)).join(',') + '}';
  }
  ancestors.delete(value);
  return result;
}

export function refinementDigest(value) {
  return createHash('sha256').update(canonical(value)).digest('hex');
}

function emptyState() {
  return {
    schema: SCHEMA,
    managed: false,
    generation: 0, // Lifecycle event count; global roadmap sequence/CAS belongs to the writer.
    last_event_at: null,
    adoption: null,
    slices: {},
    producer_handoffs: {},
    pending_request: null,
  };
}

function elegance(value, mode) {
  demand(object(value) && value.mode === mode && nonempty(value.source),
    'ELEGANCE_REQUIRED', 'This operation requires ' + mode + ' elegance evidence and its source.');
  if (mode === 'full') {
    demand(object(value.assessments) && FULL_ASSESSMENTS.every(key => {
      const assessment = value.assessments[key];
      return nonempty(assessment) || (object(assessment) && nonempty(assessment.reason));
    }), 'FULL_ELEGANCE_REQUIRED', 'Full review requires sourced assessments for RC-1 through RC-8 and RC-G.');
  } else {
    demand(nonempty(value.reason), 'ELEGANCE_REASON_REQUIRED', 'RC6 requires a concrete review reason.');
  }
  return clone(value);
}

function getSlice(state, stepId) {
  identifier(stepId, 'step_id');
  demand(Object.hasOwn(state.slices, stepId), 'UNKNOWN_SLICE', 'Unknown slice: ' + stepId);
  return state.slices[stepId];
}

function currentRound(slice) {
  return slice.rounds[slice.round];
}

function lastPresentation(slice) {
  return slice.presentations.at(-1) ?? null;
}

function getPresentation(slice, id) {
  identifier(id, 'presentation_id');
  const presentation = slice.presentations.find(item => item.id === id);
  demand(presentation, 'UNKNOWN_PRESENTATION', 'Unknown presentation: ' + id);
  return presentation;
}

function revisionHashes(presentation) {
  return Object.fromEntries(presentation.members.map(member => [member.product_id, member.hash]));
}

function activeRequirements(slice) {
  return Object.fromEntries(Object.entries(slice.requirements)
    .filter(([, item]) => item.status === 'active' || item.status === 'pending')
    .map(([id, item]) => [id, {
      scope: item.scope, directive: item.directive, text: item.text,
    }]));
}

function productRequirementsDigest(slice, productId) {
  return refinementDigest(Object.fromEntries(Object.entries(activeRequirements(slice))
    .filter(([,r])=>r.scope===productId || !slice.product_ids.includes(r.scope))));
}
function productApplicable(slice,presentation,productId) {
  const expected=presentation.product_context?.version===1
    ? presentation.product_context.requirements_digests[productId]
    : presentation.applicable_requirements_digest;
  const current=presentation.product_context?.version===1
    ? productRequirementsDigest(slice,productId) : refinementDigest(activeRequirements(slice));
  const pending=slice.feedback.some(f=>f.disposition==='pending' &&
    (!f.changes.length || f.changes.some(id=>{
      const r=slice.requirements[id];return !r || r.scope===productId || !slice.product_ids.includes(r.scope);
    })));
  return expected===current && !pending &&
    presentation.dependencies_digest===refinementDigest(dependencyContext(slice)) &&
    slice.depends_on.every(d=>['pinned','rechecked'].includes(d.state));
}

/** One applicability projection for completion and the cockpit; no new approvals. */
export function currentProductApprovals(slice) {
  const latest=new Map();
  for(const accepted of slice.acceptance_history) {
    const p=getPresentation(slice,accepted.presentation_id);
    for(const member of p.members)if(!accepted.member_product_id || accepted.member_product_id===member.product_id)
      latest.set(member.product_id,{member,presentation:p});
  }
  return Object.fromEntries(slice.product_ids.map(id=>{
    const a=latest.get(id),current=slice.revisions[slice.candidate[id]];
    return [id,!!(a && current && a.member.revision_id===current.revision_id && a.member.hash===current.hash &&
      productApplicable(slice,a.presentation,id))];
  }));
}

function dependencyContext(slice) {
  return slice.depends_on.map(dependency => ({
    slice_id: dependency.slice_id,
    presentation_id: dependency.presentation_id,
    accepted_revision_hashes: dependency.accepted_revision_hashes,
  })).sort((a, b) => a.slice_id < b.slice_id ? -1 : a.slice_id > b.slice_id ? 1 : 0);
}

function hasClosedFoundation(state, dependency) {
  const foundation = state.slices[dependency.slice_id];
  return foundation && foundation.phase === 'done' && foundation.closed_presentation !== null;
}

function foundationsClosed(state, slice, requirePins = true) {
  for (const dependency of slice.depends_on) {
    demand(hasClosedFoundation(state, dependency), 'FOUNDATION_NOT_CLOSED',
      'Foundation must be explicitly closed: ' + dependency.slice_id);
    if (requirePins) {
      demand(dependency.presentation_id !== null, 'DEPENDENCY_NOT_PINNED',
        'Begin must pin foundation: ' + dependency.slice_id);
    }
  }
}

function dependenciesCurrent(state, slice) {
  foundationsClosed(state, slice);
  for (const dependency of slice.depends_on) {
    const foundation = state.slices[dependency.slice_id];
    const presentation = getPresentation(foundation, foundation.closed_presentation);
    demand(dependency.presentation_id === presentation.id &&
      refinementDigest(dependency.accepted_revision_hashes) === refinementDigest(revisionHashes(presentation)),
    'DEPENDENCY_NEEDS_RECONCILIATION', 'Foundation revision changed: ' + dependency.slice_id);
  }
}

function unclose(slice, generation, reason) {
  if (slice.closed_presentation !== null) {
    slice.invalidated_closures.push({
      presentation_id: slice.closed_presentation, generation, reason,
    });
    slice.closed_presentation = null;
  }
}

// Recompute through the DAG so reopening a foundation also blocks grandchildren.
// Operational phase is separate from the derived dependency readiness phase.
function refreshDependencies(state) {
  const visiting = new Set();
  const visited = new Set();
  function visit(slice) {
    demand(!visiting.has(slice.step_id), 'DEPENDENCY_CYCLE', 'Slice dependencies contain a cycle.');
    if (visited.has(slice.step_id)) return;
    visiting.add(slice.step_id);
    for (const dependency of slice.depends_on) {
      const foundation = getSlice(state, dependency.slice_id);
      visit(foundation);
      const previousState = dependency.state;
      if (!hasClosedFoundation(state, dependency)) {
        dependency.state = dependency.presentation_id === null ? 'waiting' : 'needs_reconciliation';
      } else if (dependency.presentation_id === null) {
        dependency.state = 'waiting';
      } else {
        const closed = getPresentation(foundation, foundation.closed_presentation);
        const matches = dependency.presentation_id === closed.id &&
          refinementDigest(dependency.accepted_revision_hashes) === refinementDigest(revisionHashes(closed));
        dependency.state = matches
          ? (dependency.state === 'rechecked' ? 'rechecked' : 'pinned')
          : 'needs_reconciliation';
      }
      if (dependency.state === 'needs_reconciliation' && previousState !== 'needs_reconciliation') {
        dependency.invalidated_candidate_digest = refinementDigest(slice.candidate);
        dependency.invalidated_generation = state.generation;
      }
    }
    const stale = slice.depends_on.some(dependency => dependency.state === 'needs_reconciliation');
    const waiting = slice.depends_on.some(dependency => dependency.state === 'waiting');
    if (stale || waiting) {
      unclose(slice, state.generation, 'foundation_not_ready');
      slice.phase = stale ? 'needs_reconciliation' : 'waiting_foundation';
      supersedeRequests(state, slice, 'foundation_not_ready');
    } else {
      slice.phase = slice.work_phase;
    }
    visiting.delete(slice.step_id);
    visited.add(slice.step_id);
  }
  for (const slice of Object.values(state.slices)) visit(slice);
  refreshProducerHandoffs(state);
  refreshPendingRequest(state);
}

function producerDependencyPins(dependencies) {
  if (!Array.isArray(dependencies)) return dependencies;
  return dependencies.map(dependency => object(dependency) ? {
    slice_id: dependency.slice_id ?? null,
    presentation_id: dependency.presentation_id ?? null,
    accepted_revision_hashes: dependency.accepted_revision_hashes ?? null,
  } : dependency).sort((a, b) => {
    const aKey = object(a) && nonempty(a.slice_id) ? a.slice_id : refinementDigest(a);
    const bKey = object(b) && nonempty(b.slice_id) ? b.slice_id : refinementDigest(b);
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  });
}

function validateHandoffPresentedOutputs(handoff, slice, presentation, reconciliation) {
  const declared = new Set(handoff.outputs.flatMap(output => typeof output === 'string' ? [output]
    : [output.source_ref, output.path].filter(nonempty)));
  const presentedRefs = new Set();
  for (const member of presentation.members) {
    const revision = slice.revisions[member.revision_id];
    for (const reference of [member.source_ref, member.path, revision?.source_ref, revision?.path]) {
      if (nonempty(reference)) presentedRefs.add(reference);
    }
  }
  const mappings = reconciliation?.output_mappings === undefined ? [] : reconciliation.output_mappings;
  demand(Array.isArray(mappings), 'INVALID_HANDOFF_OUTPUT_MAPPINGS',
    'output_mappings must be an array of sourced mappings to selected presentation members.');
  const mapped = new Set();
  for (const mapping of mappings) {
    demand(object(mapping) && nonempty(mapping.source_ref) && nonempty(mapping.product_id) &&
      nonempty(mapping.revision_id) && nonempty(mapping.source) && nonempty(mapping.reason),
    'INVALID_HANDOFF_OUTPUT_MAPPING',
    'Each output mapping requires source_ref, product_id, revision_id, source and reason.');
    demand(declared.has(mapping.source_ref) ||
      (!handoff.inventory_complete && reconciliation.inventory_verified === true),
    'HANDOFF_OUTPUT_MAPPING_UNDECLARED',
    'Newly inspected references require an originally incomplete inventory and explicit inventory verification.');
    demand(presentation.members.some(member =>
      member.product_id === mapping.product_id && member.revision_id === mapping.revision_id),
    'HANDOFF_OUTPUT_MAPPING_MEMBER_UNKNOWN',
    'An output mapping must name an existing member of the selected presentation.');
    demand(!mapped.has(mapping.source_ref), 'HANDOFF_OUTPUT_MAPPING_CONFLICT',
      'Each source reference must have one explicit output mapping.');
    mapped.add(mapping.source_ref);
  }
  demand(declared.size > 0 || (!handoff.inventory_complete && mappings.length > 0),
    'HANDOFF_OUTPUT_INVENTORY_REQUIRED',
    'Published resolution requires declared outputs, or verified inspected-output mappings for an originally incomplete inventory.');
  for (const reference of declared) {
    demand(presentedRefs.has(reference) || mapped.has(reference), 'HANDOFF_OUTPUT_NOT_PRESENTED',
      'Every declared output reference must identify a selected presentation member or have an explicit sourced mapping.');
  }
}

// A captured dispatch context is written once (cloned at the handoff) and only read after, so its
// field digests are kept with it; a slice's digests are taken once per refresh, not once per handoff.
// The fold refreshes after every event, so without this the read re-hashed every pending handoff's
// context on every event (the MBA record: 717 events, ~6 s a read).
const capturedDigests = new WeakMap();

function capturedDigest(dispatch, field) {
  let digests = capturedDigests.get(dispatch);
  if (!digests) capturedDigests.set(dispatch, digests = new Map());
  if (!digests.has(field)) {
    digests.set(field, refinementDigest(field === 'depends_on' ? producerDependencyPins(dispatch[field]) : dispatch[field]));
  }
  return digests.get(field);
}

function refreshProducerHandoffs(state) {
  const fields = ['step_id', 'round', 'requirements', 'candidate', 'depends_on'];
  const currentDigests = new Map();
  const currentDigest = (slice, field) => {
    let digests = currentDigests.get(slice);
    if (!digests) currentDigests.set(slice, digests = new Map());
    if (!digests.has(field)) {
      digests.set(field, refinementDigest(field === 'depends_on' ? producerDependencyPins(slice[field]) : slice[field]));
    }
    return digests.get(field);
  };
  for (const handoff of Object.values(state.producer_handoffs)) {
    if (handoff.status !== 'pending_steward_review') continue;
    const slice = handoff.step_id === null ? null : getSlice(state, handoff.step_id);
    const dispatch = handoff.dispatch_context;
    const known = object(dispatch) && nonempty(dispatch.step_id) &&
      Number.isInteger(dispatch.round) && dispatch.round >= 0 &&
      object(dispatch.requirements) && object(dispatch.candidate) && Array.isArray(dispatch.depends_on) &&
      dispatch.depends_on.every(dependency => object(dependency) && nonempty(dependency.slice_id) &&
        Object.hasOwn(dependency, 'presentation_id') &&
        (dependency.presentation_id === null || nonempty(dependency.presentation_id)) &&
        object(dependency.accepted_revision_hashes)) &&
      new Set(dispatch.depends_on.map(dependency => dependency.slice_id)).size === dispatch.depends_on.length;
    const changed = [];
    if (slice && object(dispatch)) {
      for (const field of fields) {
        if (Object.hasOwn(dispatch, field)) {
          if (capturedDigest(dispatch, field) !== currentDigest(slice, field)) changed.push(field);
        }
      }
    }
    const reasons = [];
    if (!slice) reasons.push('slice_unmapped');
    if (!known) reasons.push('dispatch_context_unknown');
    if (changed.length > 0) reasons.push('dispatch_context_changed');
    if (!handoff.inventory_complete) reasons.push('output_inventory_incomplete');
    if (handoff.terminal === null) reasons.push('terminal_observation_missing');
    handoff.freshness = !slice || !known ? 'unknown' : changed.length > 0 ? 'stale' : 'current';
    handoff.changed_context_fields = changed;
    handoff.review_reasons = reasons;
  }
}

function refreshPendingRequest(state) {
  let oldest = null;
  let oldestGeneration = Infinity;
  for (const slice of Object.values(state.slices)) {
    for (const request of slice.review_requests) {
      if (request.status !== 'pending') continue;
      const generation = getPresentation(slice, request.presentation_id).generation;
      if (generation < oldestGeneration ||
        (generation === oldestGeneration && (oldest === null || request.id < oldest.id))) {
        oldest = request;
        oldestGeneration = generation;
      }
    }
  }
  // Focus is derived from existing requests; it is not a second queue or store.
  state.pending_request = oldest === null ? null : clone(oldest);
}

function supersedeRequests(state, slice, reason) {
  for (const request of slice.review_requests) {
    if (request.status === 'pending') {
      request.status = 'superseded';
      request.superseded_reason = reason;
      request.superseded_generation = state.generation;
    }
  }
}

function recordElegance(slice, review, action, state) {
  slice.elegance_reviews.push({
    action, round: slice.round, generation: state.generation, at: state.last_event_at, ...review,
  });
}

function humanEvidence(human) {
  demand(object(human) && human.explicit === true && nonempty(human.source_message),
    'EXPLICIT_HUMAN_REQUIRED', 'Explicit human input naming the revision is required.');
  return clone(human);
}

function recomputeRequirements(slice) {
  // Feedback disposition concerns a proposed instruction, not its content polarity.
  // Declining "include X" does not turn it into an active "exclude X" directive.
  for (const requirement of Object.values(slice.requirements)) {
    const feedback = slice.feedback.find(item => item.id === requirement.feedback_id);
    requirement.status = feedback.disposition === 'incorporated' ? 'active'
      : feedback.disposition === 'declined' ? 'rejected'
      : feedback.disposition === 'parked' ? 'parked' : 'pending';
    delete requirement.superseded_by;
  }
  for (const requirement of Object.values(slice.requirements)) {
    if (requirement.status === 'active' && requirement.supersedes) {
      const previous = slice.requirements[requirement.supersedes];
      previous.status = 'superseded';
      previous.superseded_by = requirement.id;
    }
  }
}

function requireOpenRound(slice) {
  demand(currentRound(slice).presentations.length === 0, 'ROUND_ALREADY_PRESENTED',
    'Feedback must open the next round before producing another handback.');
}

function candidateMembers(slice) {
  demand(Object.keys(slice.candidate).length === slice.product_ids.length &&
    slice.product_ids.every(id => Object.hasOwn(slice.candidate, id)),
  'INCOMPLETE_CANDIDATE', 'A presentation must contain every declared product.');
  return slice.product_ids.map(productId => {
    const revision = slice.revisions[slice.candidate[productId]];
    return {
      product_id: productId, revision_id: revision.revision_id,
      hash: revision.hash, path: revision.path,
    };
  });
}

function requireApplicablePresentation(state, slice, presentation) {
  dependenciesCurrent(state, slice);
  demand(presentation.applicable_requirements_digest === refinementDigest(activeRequirements(slice)),
    'REQUIREMENTS_CHANGED', 'The presentation does not match the applicable cumulative requirements.');
  demand(presentation.dependencies_digest === refinementDigest(dependencyContext(slice)),
    'PRESENTATION_DEPENDENCIES_CHANGED', 'The presentation used different foundation revisions.');
}

function applyOperation(state, operation, event) {
  demand(object(operation), 'INVALID_OPERATION', 'refinement_update requires an operation object.');
  demand((event.version === undefined || event.version === 1) &&
    (operation.version === undefined || operation.version === 1),
  'UNSUPPORTED_VERSION', 'Only refinement_update version 1 is supported.');
  identifier(operation.operation_id, 'operation_id');
  demand(Number.isInteger(operation.expected_seq) && operation.expected_seq >= 0,
    'INVALID_EXPECTED_SEQ', 'expected_seq must be a nonnegative integer.');
  demand(nonempty(operation.action), 'INVALID_ACTION', 'An action is required.');
  state.generation += 1;
  state.last_event_at = event.at ?? event.timestamp ?? event.ts ?? null;

  if (operation.action === 'adopt') {
    demand(!state.managed, 'ALREADY_ADOPTED', 'Managed refinement mode can only be adopted once.');
    identifier(operation.campaign_id, 'campaign_id');
    for (const name of ['PLAN.md', 'DELIVERABLES.md']) {
      const document = operation.documents?.[name];
      demand(object(document) && typeof document.exists === 'boolean' &&
        typeof document.baseline === 'string', 'INVALID_ADOPTION_BASELINE',
      'Adoption must record existence and an exact baseline string for ' + name + '.');
    }
    state.adoption = {
      campaign_id: operation.campaign_id,
      documents: clone(operation.documents),
      elegance: elegance(operation.elegance, 'full'),
      at: state.last_event_at,
      generation: state.generation,
    };
    state.managed = true;
    return state;
  }

  demand(state.managed, 'NOT_ADOPTED', 'Explicit adoption is required before refinement operations.');

  if (operation.action === 'producer_handoff') {
    const handoffId = identifier(operation.handoff_id, 'handoff_id');
    demand(!Object.hasOwn(state.producer_handoffs, handoffId),
      'HANDOFF_EXISTS', 'Producer handoff IDs are immutable; retry through ledger operation idempotency.');
    demand(['job', 'conversation', 'terminal'].includes(operation.producer_kind),
      'INVALID_PRODUCER_KIND', 'Producer kind must be job, conversation or terminal.');
    demand(nonempty(operation.source_ref), 'HANDOFF_SOURCE_REQUIRED',
      'A producer handoff requires an explicit source reference.');
    demand(Array.isArray(operation.outputs) && operation.outputs.every(output =>
      nonempty(output) || (object(output) && nonempty(output.source_ref))),
    'INVALID_HANDOFF_OUTPUTS', 'Outputs must be explicit nonempty references or objects with source_ref.');
    demand(typeof operation.inventory_complete === 'boolean', 'HANDOFF_INVENTORY_REQUIRED',
      'A handoff must explicitly state whether its output inventory is complete.');
    const stepId = operation.step_id ?? null;
    if (stepId !== null) getSlice(state, stepId);
    const dispatch = operation.dispatch_context ?? null;
    demand(dispatch === null || object(dispatch), 'INVALID_DISPATCH_CONTEXT',
      'dispatch_context must be a captured context object or null.');
    const terminal = operation.terminal ?? null;
    demand(terminal === null || nonempty(terminal) || object(terminal), 'INVALID_TERMINAL_OBSERVATION',
      'terminal must preserve an explicit terminal observation or be null.');
    state.producer_handoffs[handoffId] = {
      handoff_id: handoffId, producer_kind: operation.producer_kind,
      source_ref: operation.source_ref, step_id: stepId, outputs: clone(operation.outputs),
      dispatch_context: dispatch === null ? null : clone(dispatch),
      terminal: terminal === null ? null : clone(terminal),
      inventory_complete: operation.inventory_complete,
      status: 'pending_steward_review',
      freshness: 'unknown', changed_context_fields: [], review_reasons: [],
      operation_id: operation.operation_id, generation: state.generation, at: state.last_event_at,
      resolution: null,
    };
    refreshProducerHandoffs(state);
    refreshPendingRequest(state);
    return state;
  }

  if (operation.action === 'resolve_handoff') {
    const handoffId = identifier(operation.handoff_id, 'handoff_id');
    demand(Object.hasOwn(state.producer_handoffs, handoffId),
      'UNKNOWN_HANDOFF', 'Unknown producer handoff: ' + handoffId);
    const handoff = state.producer_handoffs[handoffId];
    demand(handoff.status === 'pending_steward_review', 'HANDOFF_ALREADY_RESOLVED',
      'A handoff disposition is immutable; retry through ledger operation idempotency.');
    demand(['published', 'no_deliverable', 'superseded'].includes(operation.disposition),
      'INVALID_HANDOFF_DISPOSITION', 'A handoff must be published, explicitly have no deliverable, or be superseded.');
    demand(nonempty(operation.source), 'HANDOFF_DISPOSITION_SOURCE_REQUIRED',
      'Resolving a producer handoff requires a recorded source.');
    let mappedStepId = handoff.step_id;
    let presentationId = null;
    let reconciliation = null;
    if (operation.disposition === 'published') {
      demand(nonempty(operation.reason), 'HANDOFF_DISPOSITION_REASON_REQUIRED',
        'Published resolution requires a reason explaining the verified mapping and current feedback review.');
      mappedStepId = operation.step_id ?? handoff.step_id;
      demand(nonempty(mappedStepId), 'HANDOFF_MAPPING_REQUIRED',
        'Published resolution requires an explicit slice mapping.');
      demand(handoff.step_id === null || handoff.step_id === mappedStepId,
        'HANDOFF_SLICE_MISMATCH', 'A published resolution must use the handoff mapped slice.');
      const mappedSlice = getSlice(state, mappedStepId);
      const presentation = getPresentation(mappedSlice, operation.presentation_id);
      demand(presentation.generation > handoff.generation, 'HANDOFF_PRESENTATION_PREDATES_HANDOFF',
        'Published resolution requires a presentation created after this handoff; late work needs a new reviewed round or an explicit non-deliverable disposition.');
      demand(lastPresentation(mappedSlice)?.id === presentation.id && presentation.round === mappedSlice.round,
        'NOT_CURRENT_PRESENTATION', 'Published resolution requires the current round and latest presentation.');
      demand(refinementDigest(mappedSlice.candidate) === presentation.candidate_digest &&
        refinementDigest(mappedSlice.requirements) === presentation.requirements_digest &&
        mappedSlice.feedback.length === presentation.feedback_count,
      'PRESENTATION_CHANGED', 'Candidate or feedback changed after the handoff presentation.');
      requireApplicablePresentation(state, mappedSlice, presentation);
      presentationId = presentation.id;
      const needsReconciliation = handoff.freshness !== 'current' || !handoff.inventory_complete;
      const evidence = operation.reconciliation ?? null;
      demand(!needsReconciliation || object(evidence), 'HANDOFF_RECONCILIATION_REQUIRED',
        'Stale or unknown dispatch context and incomplete output inventories require explicit reconciliation.');
      if (evidence !== null) {
        demand(object(evidence) && nonempty(evidence.source) && nonempty(evidence.reason) &&
          Array.isArray(evidence.changed_context_fields) && evidence.changed_context_fields.every(nonempty) &&
          Array.isArray(evidence.review_reasons) && evidence.review_reasons.every(nonempty),
        'INVALID_HANDOFF_RECONCILIATION',
        'Reconciliation requires source, reason, changed_context_fields and review_reasons arrays.');
        demand(handoff.changed_context_fields.every(field => evidence.changed_context_fields.includes(field)) &&
          handoff.review_reasons.every(reason => evidence.review_reasons.includes(reason)),
        'HANDOFF_RECONCILIATION_INCOMPLETE',
        'Reconciliation must cover every recorded context change and review reason.');
        demand(handoff.inventory_complete || evidence.inventory_verified === true,
          'HANDOFF_INVENTORY_UNVERIFIED', 'An incomplete producer inventory must be explicitly verified during reconciliation.');
        reconciliation = clone(evidence);
      }
      validateHandoffPresentedOutputs(handoff, mappedSlice, presentation, reconciliation);
    } else {
      demand(nonempty(operation.reason), 'HANDOFF_DISPOSITION_REASON_REQUIRED',
        'No-deliverable and superseded dispositions require an explicit reason.');
    }
    handoff.status = operation.disposition;
    handoff.resolution = {
      disposition: operation.disposition, source: operation.source,
      reason: operation.reason ?? null, step_id: mappedStepId, presentation_id: presentationId,
      reconciliation,
      operation_id: operation.operation_id, generation: state.generation, at: state.last_event_at,
    };
    // Resolving producer bookkeeping does not accept a presentation or close a slice.
    refreshPendingRequest(state);
    return state;
  }


  if (operation.action === 'open_slice') {
    const stepId = identifier(operation.step_id, 'step_id');
    demand(!Object.hasOwn(state.slices, stepId), 'SLICE_EXISTS', 'The slice already exists.');
    demand(nonempty(operation.title), 'INVALID_TITLE', 'A slice title is required.');
    demand(Array.isArray(operation.product_ids) && operation.product_ids.length > 0,
      'INVALID_PRODUCTS', 'A slice must declare at least one stable product ID.');
    const products = operation.product_ids.map(id => identifier(id, 'product_id'));
    demand(new Set(products).size === products.length, 'DUPLICATE_PRODUCT', 'Duplicate declared product IDs.');
    for (const existing of Object.values(state.slices)) {
      demand(!products.some(id => existing.product_ids.includes(id)), 'PRODUCT_ALREADY_OWNED',
        'A stable product ID can belong to only one slice.');
    }
    demand(Array.isArray(operation.depends_on), 'INVALID_DEPENDENCIES', 'depends_on must be an array.');
    const seen = new Set();
    const dependencies = operation.depends_on.map(item => {
      const id = identifier(item?.slice_id, 'slice_id');
      demand(id !== stepId && !seen.has(id), 'INVALID_DEPENDENCY', 'Self or duplicate dependency.');
      getSlice(state, id);
      seen.add(id);
      return { slice_id: id, presentation_id: null, accepted_revision_hashes: {}, state: 'waiting',
        ...(nonempty(item.reason) ? {reason:item.reason} : {}) };
    });
    const review = elegance(operation.elegance, 'full');
    const slice = {
      step_id: stepId, title: operation.title, product_ids: products,
      phase: 'preparing', work_phase: 'preparing', round: 0,
      rounds: [{ index: 0, feedback_ids: [], presentations: [] }],
      requirements: {}, feedback: [], revisions: {}, candidate: {},
      presentations: [], accepted_presentation: null, closed_presentation: null,
      accepted_members: {}, acceptance_history: [], closure_history: [], invalidated_closures: [],
      depends_on: dependencies, checks: [], elegance_reviews: [], review_requests: [],
      reconciliation_history: [], views: [],
    };
    state.slices[stepId] = slice;
    recordElegance(slice, review, operation.action, state);
    refreshDependencies(state);
    return state;
  }

  const slice = getSlice(state, operation.step_id);
  switch (operation.action) {
    case 'begin': {
      const review = elegance(operation.elegance, 'RC6');
      requireOpenRound(slice);
      foundationsClosed(state, slice, false);
      for (const dependency of slice.depends_on) {
        const foundation = state.slices[dependency.slice_id];
        const presentation = getPresentation(foundation, foundation.closed_presentation);
        demand(dependency.presentation_id === null || dependency.presentation_id === presentation.id,
          'DEPENDENCY_NEEDS_RECONCILIATION', 'Begin cannot silently replace an existing foundation pin.');
        dependency.presentation_id = presentation.id;
        dependency.accepted_revision_hashes = revisionHashes(presentation);
        dependency.state = 'pinned';
      }
      slice.work_phase = slice.round === 0 ? 'preparing' : 'revising';
      recordElegance(slice, review, operation.action, state);
      break;
    }
    case 'feedback': {
      const review = elegance(operation.elegance, 'RC6');
      identifier(operation.feedback_id, 'feedback_id');
      demand(!slice.feedback.some(item => item.id === operation.feedback_id),
        'DUPLICATE_FEEDBACK', 'Feedback ID already exists.');
      demand(nonempty(operation.source_message), 'FEEDBACK_SOURCE_REQUIRED', 'Feedback requires its source message.');
      if (slice.presentations.length > 0 || operation.base_presentation_id != null) {
        getPresentation(slice, operation.base_presentation_id);
      }
      demand(Array.isArray(operation.changes), 'INVALID_REQUIREMENTS', 'Feedback changes must be an array.');
      if (currentRound(slice).presentations.length > 0) {
        slice.round += 1;
        slice.rounds.push({ index: slice.round, feedback_ids: [], presentations: [] });
      }
      const priorRequirements = new Set(Object.keys(slice.requirements));
      const superseded = new Set();
      const feedback = {
        id: operation.feedback_id, source_message: operation.source_message,
        base_presentation_id: operation.base_presentation_id ?? null,
        round: slice.round, disposition: 'pending', changes: [],
        at: state.last_event_at, generation: state.generation,
      };
      for (const change of operation.changes) {
        identifier(change?.id, 'requirement id');
        demand(!Object.hasOwn(slice.requirements, change.id),
          'REQUIREMENT_EXISTS', 'Requirement IDs are immutable; use a new ID and explicit supersedes.');
        demand(nonempty(change.scope) && nonempty(change.text) &&
          ['require', 'preserve', 'exclude'].includes(change.directive),
        'INVALID_REQUIREMENT', 'Each requirement needs scope, text and a supported directive.');
        if (change.supersedes !== undefined) {
          identifier(change.supersedes, 'supersedes');
          demand(priorRequirements.has(change.supersedes) && !superseded.has(change.supersedes),
            'INVALID_SUPERSESSION', 'Supersedes must identify one existing prior requirement, once per feedback.');
          demand(!Object.values(slice.requirements).some(item =>
            item.supersedes === change.supersedes && ['pending', 'active'].includes(item.status)),
          'SUPERSESSION_CONFLICT', 'An active or unresolved replacement already supersedes that requirement.');
          superseded.add(change.supersedes);
        }
        slice.requirements[change.id] = {
          id: change.id, scope: change.scope, directive: change.directive, text: change.text,
          ...(change.supersedes !== undefined ? { supersedes: change.supersedes } : {}),
          feedback_id: feedback.id, source_message: feedback.source_message,
          round: slice.round, status: 'pending',
        };
        feedback.changes.push(change.id);
      }
      slice.feedback.push(feedback);
      currentRound(slice).feedback_ids.push(feedback.id);
      unclose(slice, state.generation, 'new_feedback');
      slice.work_phase = 'revising';
      supersedeRequests(state, slice, 'new_feedback');
      recordElegance(slice, review, operation.action, state);
      break;
    }
    case 'resolve_feedback': {
      const feedback = slice.feedback.find(item => item.id === operation.feedback_id);
      demand(feedback, 'UNKNOWN_FEEDBACK', 'Unknown feedback ID.');
      demand(feedback.disposition === 'pending', 'FEEDBACK_ALREADY_RESOLVED',
        'A resolved feedback decision is immutable; record a new sourced feedback item.');
      demand(['incorporated', 'declined', 'parked'].includes(operation.disposition),
        'INVALID_FEEDBACK_DISPOSITION', 'Feedback must be incorporated, declined or parked.');
      demand(nonempty(operation.source), 'FEEDBACK_DISPOSITION_SOURCE_REQUIRED', 'A disposition requires its source.');
      if (operation.disposition !== 'incorporated') {
        demand(nonempty(operation.reason), 'FEEDBACK_DISPOSITION_REASON_REQUIRED',
          'Declining or parking feedback requires an explicit reason.');
      }
      feedback.disposition = operation.disposition;
      feedback.resolution = {
        source: operation.source, reason: operation.reason ?? null,
        at: state.last_event_at, generation: state.generation,
      };
      recomputeRequirements(slice);
      break;
    }
    case 'publish': {
      const review = elegance(operation.elegance, 'RC6');
      requireOpenRound(slice);
      if (operation.provisional !== undefined) {
        humanEvidence(operation.provisional?.human);
        demand(nonempty(operation.provisional.scope) && nonempty(operation.provisional.reason),
          'PROVISIONAL_SCOPE_REQUIRED', 'Partial work needs explicit human scope and a prerequisite explanation.');
      } else foundationsClosed(state, slice);
      demand(Array.isArray(operation.products) && operation.products.length > 0,
        'INVALID_PRODUCTS', 'Publish requires at least one product revision.');
      const seen = new Set();
      for (const product of operation.products) {
        identifier(product?.product_id, 'product_id');
        identifier(product.revision_id, 'revision_id');
        demand(slice.product_ids.includes(product.product_id), 'UNKNOWN_PRODUCT', 'Product is not owned by this slice.');
        demand(!seen.has(product.product_id), 'DUPLICATE_PRODUCT', 'Publish cannot include the same product twice.');
        seen.add(product.product_id);
        demand(!Object.values(state.slices).some(item => Object.hasOwn(item.revisions, product.revision_id)),
          'REVISION_EXISTS', 'Revision IDs are immutable and globally unique.');
        demand(typeof product.hash === 'string' && /^[a-f0-9]{64}$/i.test(product.hash) && nonempty(product.path),
          'INVALID_REVISION', 'A revision needs a SHA256 digest and immutable file locator.');
        if(product.source_history!==undefined) demand(slice.presentations.length===0 && object(product.source_history) &&
          Number.isInteger(product.source_history.iteration) && product.source_history.iteration>=0 &&
          product.source_history.iteration<=10000 && !Object.values(slice.revisions).some(r=>r.product_id===product.product_id &&
            r.source_history && r.source_history.iteration>=product.source_history.iteration) &&
          nonempty(product.source_history.source) && nonempty(product.source_history.at),
          'INVALID_SOURCE_HISTORY','Imported iterations require their actual source and date.');
        const expectedParent = slice.candidate[product.product_id] ?? null;
        const parent = product.parent_revision_id ?? null;
        if (parent !== expectedParent) {
          const rollback = product.rollback_source;
          const sourceRevision = object(rollback) ? slice.revisions[rollback.revision_id] : null;
          demand(sourceRevision && sourceRevision.product_id === product.product_id &&
            parent === sourceRevision.revision_id && nonempty(rollback.source),
          'INVALID_REVISION_PARENT', 'Parent must be the current candidate or an explicitly sourced rollback revision.');
        } else if (product.rollback_source !== undefined) {
          const rollback = product.rollback_source;
          demand(object(rollback) && nonempty(rollback.source) &&
            slice.revisions[rollback.revision_id]?.product_id === product.product_id,
          'INVALID_ROLLBACK_SOURCE', 'Rollback source must identify an existing revision of the same product.');
        }
        slice.revisions[product.revision_id] = {
          product_id: product.product_id, revision_id: product.revision_id,
          hash: product.hash.toLowerCase(), path: product.path,
          parent_revision_id: parent, previous_candidate_revision_id: expectedParent,
          ...(product.rollback_source ? { rollback_source: clone(product.rollback_source) } : {}),
          round: slice.round, at: state.last_event_at, generation: state.generation,
          ...(operation.provisional ? {provisional:clone(operation.provisional)} : {}),
          ...(product.source_history ? {source_history:clone(product.source_history)} : {}),
        };
        slice.candidate[product.product_id] = product.revision_id;
      }
      slice.work_phase = slice.round === 0 ? 'preparing' : 'revising';
      recordElegance(slice, review, operation.action, state);
      break;
    }
    case 'present': {
      demand(operation.product_context_version===undefined || operation.product_context_version===1,
        'INVALID_PRODUCT_CONTEXT_VERSION','Unsupported product applicability context.');
      const review = elegance(operation.elegance, 'RC6');
      requireOpenRound(slice);
      dependenciesCurrent(state, slice);
      demand(slice.feedback.every(item => item.disposition !== 'pending'),
        'UNRESOLVED_FEEDBACK', 'Every feedback item needs an explicit disposition before presentation.');
      const presentationId = identifier(operation.presentation_id, 'presentation_id');
      const requestId = identifier(operation.request_id, 'request_id');
      demand(!Object.values(state.slices).some(item => item.presentations.some(p => p.id === presentationId)),
        'PRESENTATION_EXISTS', 'Presentation IDs are immutable and globally unique.');
      demand(!Object.values(state.slices).some(item => item.review_requests.some(r => r.id === requestId)),
        'REQUEST_EXISTS', 'Review request IDs are globally unique.');
      demand(nonempty(operation.source_message) && nonempty(operation.purpose),
        'REVIEW_REQUEST_SOURCE_REQUIRED', 'Presentation requires a source message and concrete review purpose.');
      const members = candidateMembers(slice);
      const candidateDigest = refinementDigest(slice.candidate);
      const requirementsDigest = refinementDigest(slice.requirements);
      demand(Array.isArray(operation.checks) && operation.checks.some(check => check.kind === 'content'),
        'CONTENT_REVIEW_REQUIRED', 'A sourced semantic content review is required for each presentation.');
      for (const check of operation.checks) {
        demand(object(check) && ['content', 'tests'].includes(check.kind) &&
          check.outcome === 'pass' && nonempty(check.source),
        'INVALID_CHECK', 'Checks must pass and identify their evidence source.');
        demand(check.candidate_digest === candidateDigest && check.requirements_digest === requirementsDigest,
          'STALE_CHECK', 'Checks must refer to the exact candidate and cumulative requirement state.');
      }
      const presentation = {
        id: presentationId, round: slice.round, at: state.last_event_at, generation: state.generation,
        members, requirements_digest: requirementsDigest, candidate_digest: candidateDigest,
        applicable_requirements_digest: refinementDigest(activeRequirements(slice)),
        ...(operation.product_context_version===1 ? {product_context:{version:1,
          requirements_digests:Object.fromEntries(slice.product_ids.map(id=>[id,productRequirementsDigest(slice,id)]))}} : {}),
        dependency_pins: clone(dependencyContext(slice)),
        dependencies_digest: refinementDigest(dependencyContext(slice)),
        feedback_count: slice.feedback.length, checks: clone(operation.checks),
        elegance: review,
      };
      slice.presentations.push(presentation);
      currentRound(slice).presentations.push(presentationId);
      slice.checks.push(...clone(operation.checks).map(check => ({ ...check, presentation_id: presentationId })));
      const request = {
        id: requestId, step_id: slice.step_id, presentation_id: presentationId,
        members: clone(members), source_message: operation.source_message,
        purpose: operation.purpose, status: 'pending',
      };
      slice.review_requests.push(request);
      slice.work_phase = 'awaiting_review';
      recordElegance(slice, review, operation.action, state);
      break;
    }
    case 'accept': {
      demand(operation.complete_current === undefined || typeof operation.complete_current === 'boolean',
        'INVALID_COMPLETION_OPTION', 'complete_current must be Boolean.');
      const human = humanEvidence(operation.human);
      const presentation = getPresentation(slice, operation.presentation_id);
      if(operation.complete_current===true && operation.member_product_id && presentation.product_context) {
        dependenciesCurrent(state,slice);
        demand(productApplicable(slice,presentation,operation.member_product_id),'REQUIREMENTS_CHANGED',
          'The named product does not match its applicable cumulative requirements.');
      } else requireApplicablePresentation(state, slice, presentation);
      let member = null;
      if (operation.member_product_id !== undefined) {
        member = presentation.members.find(item => item.product_id === operation.member_product_id);
        demand(member, 'UNKNOWN_PRESENTATION_MEMBER', 'The named product is absent from this presentation.');
        slice.accepted_members[member.product_id] = {
          presentation_id: presentation.id, revision_id: member.revision_id,
          human, generation: state.generation, at: state.last_event_at,
        };
      } else {
        slice.accepted_presentation = presentation.id;
      }
      slice.acceptance_history.push({
        presentation_id: presentation.id, member_product_id: member?.product_id ?? null,
        human, generation: state.generation, at: state.last_event_at,
      });
      // Opt-in semantics for new events only: replay of earlier approvals stays unchanged.
      // Each latest product decision must still apply to the exact current work.
      if (operation.complete_current === true && member &&
          lastPresentation(slice)?.id === presentation.id && presentation.round === slice.round &&
          refinementDigest(slice.candidate) === presentation.candidate_digest &&
          refinementDigest(slice.requirements) === presentation.requirements_digest &&
          slice.feedback.length === presentation.feedback_count &&
          slice.feedback.every(item => item.disposition !== 'pending')) {
        const complete=Object.values(currentProductApprovals(slice)).every(Boolean);
        if (complete) {
          slice.accepted_presentation = presentation.id;
          slice.closed_presentation = presentation.id;
          slice.work_phase = 'done';
          slice.closure_history.push({presentation_id:presentation.id, human,
            source:'individual-acceptances', generation:state.generation, at:state.last_event_at});
          for (const request of slice.review_requests) if (request.presentation_id === presentation.id) {
            request.status = 'resolved'; request.resolved_generation = state.generation;
          }
        }
      }
      // Named historical acceptance is valid without completing a newer round.
      break;
    }
    case 'visual_companion': {
      const revision = slice.revisions[operation.revision_id];
      demand(revision && revision.hash === operation.source_hash, 'PREVIEW_SOURCE_MISMATCH',
        'A visual companion must identify the exact preserved source revision.');
      demand(object(operation.preview) && /^[a-f0-9]{64}$/.test(operation.preview.hash) &&
        nonempty(operation.preview.path) && operation.preview.path.toLowerCase().endsWith('.pdf') &&
        nonempty(operation.evidence), 'PREVIEW_EVIDENCE_REQUIRED', 'A PDF companion needs its digest and same-version evidence.');
      demand(!revision.visual_companion || refinementDigest(revision.visual_companion) ===
        refinementDigest({...operation.preview,source_hash:operation.source_hash,evidence:operation.evidence}),
        'PREVIEW_ALREADY_BOUND', 'A visual companion cannot silently replace an existing version binding.');
      revision.visual_companion = {...clone(operation.preview),source_hash:operation.source_hash,evidence:operation.evidence};
      break;
    }
    case 'view': {
      const presentation = getPresentation(slice, operation.presentation_id);
      const request = slice.review_requests.find(item => item.id === operation.request_id);
      demand(request && request.presentation_id === presentation.id, 'VIEW_REQUEST_MISMATCH',
        'A view receipt must name the request associated with the frozen presentation.');
      const member = presentation.members.find(item => item.product_id === operation.member_product_id);
      demand(member && operation.hash === member.hash, 'VIEW_MEMBER_MISMATCH',
        'A view receipt must identify the exact frozen member and digest.');
      demand(nonempty(operation.session_id) && operation.source === 'cockpit-user-open',
        'INVALID_VIEW_SOURCE', 'A view receipt requires an explicit cockpit open and session ID.');
      slice.views.push({
        step_id: slice.step_id, presentation_id: presentation.id, request_id: request.id,
        member_product_id: member.product_id, revision_id: member.revision_id,
        hash: member.hash, session_id: operation.session_id, source: operation.source,
        generation: state.generation, at: state.last_event_at,
      });
      break;
    }
    case 'close': {
      const human = humanEvidence(operation.human);
      const presentation = getPresentation(slice, operation.presentation_id);
      demand(lastPresentation(slice)?.id === presentation.id && presentation.round === slice.round,
        'NOT_CURRENT_PRESENTATION', 'Only the current round and latest presentation can be closed.');
      demand(slice.candidate && refinementDigest(slice.candidate) === presentation.candidate_digest &&
        refinementDigest(slice.requirements) === presentation.requirements_digest &&
        slice.feedback.length === presentation.feedback_count,
      'PRESENTATION_CHANGED', 'Current candidate or feedback changed after presentation.');
      demand(slice.feedback.every(item => item.disposition !== 'pending'), 'UNRESOLVED_FEEDBACK',
        'Unresolved feedback prevents closure.');
      requireApplicablePresentation(state, slice, presentation);
      slice.accepted_presentation = presentation.id;
      slice.closed_presentation = presentation.id;
      slice.work_phase = 'done';
      slice.acceptance_history.push({
        presentation_id: presentation.id, member_product_id: null,
        human, generation: state.generation, at: state.last_event_at,
      });
      slice.closure_history.push({
        presentation_id: presentation.id, human, generation: state.generation, at: state.last_event_at,
      });
      for (const request of slice.review_requests) {
        if (request.presentation_id === presentation.id) {
          request.status = 'resolved';
          request.resolved_generation = state.generation;
        }
      }
      break;
    }
    case 'reconcile': {
      requireOpenRound(slice);
      foundationsClosed(state, slice);
      const previous = lastPresentation(slice);
      const digest = refinementDigest(slice.candidate);
      const invalidated = slice.depends_on.filter(item => item.state === 'needs_reconciliation');
      const baselineDigests = previous ? [previous.candidate_digest]
        : invalidated.map(item => item.invalidated_candidate_digest);
      demand(Object.keys(slice.candidate).length > 0 && baselineDigests.length > 0 &&
        baselineDigests.every(baseline => nonempty(baseline) && digest !== baseline),
        'RECONCILIATION_REVISION_REQUIRED', 'Reconciliation requires a changed downstream candidate after its handback.');
      demand(object(operation.evidence) && operation.evidence.outcome === 'pass' &&
        nonempty(operation.evidence.source) && operation.evidence.candidate_digest === digest,
      'RECONCILIATION_EVIDENCE_REQUIRED', 'Reconciliation must name the changed candidate digest and passing evidence.');
      demand(Array.isArray(operation.depends_on) && operation.depends_on.length > 0,
        'INVALID_DEPENDENCIES', 'Reconcile requires explicit dependency pins.');
      const seen = new Set();
      for (const requested of operation.depends_on) {
        const dependency = slice.depends_on.find(item => item.slice_id === requested?.slice_id);
        demand(dependency && !seen.has(dependency.slice_id), 'INVALID_DEPENDENCY',
          'Reconcile can only update existing dependency edges, once each.');
        seen.add(dependency.slice_id);
        const foundation = state.slices[dependency.slice_id];
        demand(requested.presentation_id === foundation.closed_presentation,
          'FOUNDATION_PRESENTATION_NOT_CLOSED', 'The replacement pin must name the foundation current closed set.');
        const presentation = getPresentation(foundation, requested.presentation_id);
        dependency.presentation_id = presentation.id;
        dependency.accepted_revision_hashes = revisionHashes(presentation);
        dependency.state = 'rechecked';
        delete dependency.invalidated_candidate_digest;
        delete dependency.invalidated_generation;
      }
      slice.reconciliation_history.push({
        round: slice.round, candidate_digest: digest, evidence: clone(operation.evidence),
        pins: clone(operation.depends_on), generation: state.generation, at: state.last_event_at,
      });
      slice.work_phase = slice.round === 0 ? 'preparing' : 'revising';
      break;
    }
    default:
      fail('UNKNOWN_ACTION', 'Unsupported refinement action: ' + operation.action);
  }
  refreshDependencies(state);
  return state;
}

export function foldRefinements(events) {
  demand(Array.isArray(events), 'INVALID_EVENTS', 'Roadmap events must be an array.');
  const state = emptyState();
  for (const event of events) {
    if (event?.kind !== 'refinement_update') continue;
    applyOperation(state, clone(event.operation), event);
  }
  return state;
}

export function validateRefinementOperation(events, operation, context = {}) {
  try {
    const state = foldRefinements(events);
    applyOperation(state, clone(operation), {
      at: context.event_at ?? context.at ?? null,
    });
    return { ok: true, state };
  } catch (error) {
    return {
      ok: false,
      error: error.code ?? 'INVALID_OPERATION',
      detail: error.detail ?? error.message,
    };
  }
}
