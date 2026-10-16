/** Managed refinement disk adapter. The existing roadmap spine remains the sole writer. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { foldRefinements, refinementDigest, currentProductApprovals } from './refinement-state.mjs';
import { appendRoadmapEventThroughSpine, repairRoadmapProjectionsThroughSpine } from './ledger-spine.mjs';
import { demandClose } from './ledger-spine.mjs';
import { loadProjectRoadmap, buildRoadmapProjection, validateRoadmap, appendRoadmapEvent } from './roadmap.mjs';
import { writeFileAtomicSync } from './durable-write.mjs';
import { approvedDeliverables, publishApprovedDeliverables, approvedProjectionStatus } from './approved-deliverables.mjs';

export const REFINEMENT_SCHEMA = 'ecgberht-refinement-v1';
const DOCS = { 'PLAN.md': 'PLAN', 'DELIVERABLES.md': 'DELIVERABLES' };
const fail = (error, detail) => ({ ok: false, error, ...(detail ? { detail } : {}) });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cell = value => escape(value).replace(/\|/g, '&#124;').replace(/[\r\n]/g, ' ');
const sourceCell = value => cell(value).replace(/[\\`*_[\]()]/g, character => '\\' + character);
const markers = key => [`<!-- ECGBERHT-MANAGED-${key} v1 begin -->`, `<!-- ECGBERHT-MANAGED-${key} v1 end -->`];

function contained(root, rel, exists = true) {
  if (typeof rel !== 'string' || !rel || path.isAbsolute(rel) || /^[A-Za-z]:/.test(rel) || rel.split(/[\\/]/).includes('..')) throw Object.assign(new Error('Expected a contained relative path'), {code:'containment-refused'});
  const realRoot = fs.realpathSync(root);
  const abs = path.resolve(root, rel);
  let ancestor = abs;
  while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const resolved = fs.realpathSync(ancestor);
  const inside = p => p === realRoot || p.startsWith(realRoot + path.sep);
  if (!inside(resolved) || (exists && !fs.existsSync(abs))) throw Object.assign(new Error('Missing or escaping artifact'), {code:'containment-refused'});
  if (fs.existsSync(abs) && !inside(fs.realpathSync(abs))) throw Object.assign(new Error('Escaping artifact'), {code:'containment-refused'});
  return abs;
}

function readDocument(root, name) {
  const abs = contained(root, name, false);
  return fs.existsSync(abs) ? {exists:true, baseline:fs.readFileSync(abs,'utf8')} : {exists:false,baseline:''};
}

function splitManaged(text, key) {
  const [begin,end] = markers(key);
  const count = token => text.split(token).length - 1;
  // Any partial/foreign version marker for this region must also be reconciled.
  const mentions = (text.match(new RegExp(`<!--\\s*ECGBERHT-MANAGED-${key}\\b`, 'g')) || []).length;
  if (!mentions) return {absent:true};
  const start = text.indexOf(begin), stop = text.indexOf(end);
  if (count(begin)!==1 || count(end)!==1 || mentions!==2 || stop<start) throw Object.assign(new Error('Managed markers are missing, duplicated or malformed'),{code:'managed-content-conflict'});
  return {prefix:text.slice(0,start),region:text.slice(start,stop+end.length),suffix:text.slice(stop+end.length)};
}

function presentationMembers(slice, presentationId) {
  const p = slice.presentations.find(p => p.id === presentationId || p.presentation_id === presentationId);
  return p?.members || [];
}

export function renderRefinementDocument(state, name) {
  const [begin,end] = markers(DOCS[name]);
  const lines = [begin, `<!-- schema=${REFINEMENT_SCHEMA} campaign=${escape(state.adoption.campaign_id)} generation=${state.generation} -->`];
  if (name === 'PLAN.md') lines.push('## Current slice work');
  else lines.push('## START HERE — current work and earlier versions');
  for (const slice of Object.values(state.slices)) {
    const round = slice.round === 0 ? 'Initial draft' : `Refinement ${slice.round}`;
    lines.push(`\n### ${cell(slice.title)} — ${round} · ${cell(slice.phase)} · ${slice.round} refinements`);
    if (slice.depends_on?.length) lines.push(slice.depends_on.map(d=>`Foundation ${cell(d.slice_id)}: ${cell(d.state)} (${cell(d.presentation_id || 'not accepted')})`).join('; '));
    lines.push('\n| What | Where | Date | Step |','|---|---|---|---|');
    for (const [productId,revId] of Object.entries(slice.candidate)) {
      const rev = slice.revisions[revId];
      if (rev) lines.push(`| ${cell(productId)} — current ${round} | \`${rev.path}\` | ${cell(rev.at || state.last_event_at)} | ${cell(slice.step_id)} |`);
    }
    if (slice.accepted_presentation) lines.push(`\nAccepted presentation: ${cell(slice.accepted_presentation)}${slice.phase==='done'?' · Done':''}.`);
    if (slice.presentations.length) {
      lines.push('\n<details>','<summary>Earlier versions and presented rounds</summary>','');
      for (const p of slice.presentations) {
        const label = p.round===0 ? 'Initial draft' : `Refinement ${p.round}`;
        lines.push(`**${label}** · ${cell(p.at)}${p.id===slice.accepted_presentation?' · accepted':''}`,'');
        for (const m of p.members) lines.push(`- [${cell(m.product_id)}](${m.path.split('/').map(encodeURIComponent).join('/')})`);
      }
      lines.push('','</details>');
    }
  }
  const handoffs = Object.values(state.producer_handoffs || {});
  if (handoffs.length) {
    lines.push('\n<details open>', '<summary>Completed work awaiting Steward review</summary>', '');
    for (const handoff of handoffs.filter(item => item.status === 'pending_steward_review')) {
      lines.push(`- ${cell(handoff.producer_kind)} ${sourceCell(handoff.source_ref)} — ${cell(handoff.step_id || 'slice not yet mapped')} · ${cell(handoff.terminal || 'outcome unknown')} · ${cell(handoff.freshness)} · ${cell(handoff.at)}`);
      lines.push(`  Handoff: ${cell(handoff.handoff_id)}. Output inventory ${handoff.inventory_complete ? 'declared complete' : 'requires verification'}.`);
    }
    lines.push('', '</details>');
  }
  lines.push(end);
  return lines.join('\n');
}

// The editable generation is only a lookup hint. Accept a historical block only
// when its complete rendering matches the corresponding authoritative prefix.
function matchesHistoricalRegion(events, name, region, currentState, prefixStates) {
  if(typeof region!=='string') return false;
  const prefix=`${markers(DOCS[name])[0]}\n<!-- schema=${REFINEMENT_SCHEMA} campaign=${escape(currentState.adoption.campaign_id)} generation=`;
  if(!region.startsWith(prefix)) return false;
  const match=/^([1-9][0-9]*) -->\n/.exec(region.slice(prefix.length));
  if(!match) return false;
  const generation=Number(match[1]);
  if(!Number.isSafeInteger(generation) || String(generation)!==match[1] || generation>=currentState.generation) return false;
  let state=prefixStates.get(generation);
  if(!state) {
    let ordinal=0;
    for(let i=0;i<events.length;i++) if(events[i].kind==='refinement_update') {
      if(++ordinal!==generation) continue;
      state=foldRefinements(events.slice(0,i+1));
      break;
    }
    if(!state || !state.managed || state.generation!==generation) return false;
    prefixStates.set(generation,state);
  }
  return renderRefinementDocument(state,name)===region;
}

export function refinementProjectionStatus(root, roadmap) {
  try {
    const state=foldRefinements(roadmap.roadmap_events);
    if(!state.managed) return {consistent:true,managed:false};
    const documents={},prefixStates=new Map();
    for(const [name,key] of Object.entries(DOCS)) {
      const current=readDocument(root,name), parts=splitManaged(current.baseline,key);
      const desired=renderRefinementDocument(state,name);
      if(parts.absent) {
        const baseline=state.adoption.documents[name];
        // Initial publication can replay only against the exact source baseline.
        if(current.exists!==baseline.exists || current.baseline!==baseline.baseline) return {consistent:false,error:'managed-content-conflict',document:name};
        // Once a later operation exists, lost markers cannot be mistaken for first adopt.
        if(roadmap.roadmap_events.filter(e=>e.kind==='refinement_update').length>1) return {consistent:false,error:'managed-content-conflict',document:name};
        documents[name]='unpublished';
      } else if(parts.region===desired) documents[name]='current';
      else if(matchesHistoricalRegion(roadmap.roadmap_events,name,parts.region,state,prefixStates)) documents[name]='lagging';
      else return {consistent:false,error:'managed-content-conflict',document:name};
    }
    return {consistent:Object.values(documents).every(x=>x==='current'),managed:true,documents,generation:state.generation};
  } catch(e) { return {consistent:false,error:e.code || 'backing-store-unreadable',detail:e.message}; }
}

export function publishRefinementProjections(root, roadmap) {
  const state=foldRefinements(roadmap.roadmap_events);
  if(!state.managed) return {consistent:true};
  const status=refinementProjectionStatus(root,roadmap);
  if(status.error) return {ok:false,...status};
  const updated_documents=[];
  for(const [name,key] of Object.entries(DOCS)) {
    if(status.documents[name]==='current') continue;
    const current=readDocument(root,name), parts=splitManaged(current.baseline,key);
    const region=renderRefinementDocument(state,name);
    const text=parts.absent ? current.baseline+(current.baseline.endsWith('\n')||!current.baseline?'':'\n')+'\n'+region+'\n' : parts.prefix+region+parts.suffix;
    writeFileAtomicSync(contained(root,name,false),text);
    updated_documents.push(name);
  }
  try {
    const navigation=Object.fromEntries(buildRoadmapProjection(roadmap.roadmap_events).projection
      .filter(s=>s.navigation).map(s=>[s.id,s.navigation]));
    const finished=publishApprovedDeliverables(root,state,navigation);
    return {ok:true,consistent:true,generation:state.generation,updated_documents,finished};
  } catch(e) { return {ok:true,consistent:false,generation:state.generation,
    updated_documents,
    finished:{consistent:false,error:e.code||'approved-projection-failed',detail:e.message}}; }
}

/** Called only by the existing spine while holding roadmap.json's lock. */
export function prepareRefinementEvent(root, roadmap, event) {
  try {
    const operation=structuredClone(event.operation);
    const state=foldRefinements(roadmap.roadmap_events);
    if(operation.action==='adopt') {
      if(state.managed) return fail('already-managed');
      operation.documents=Object.fromEntries(Object.keys(DOCS).map(name=>[name,readDocument(root,name)]));
      for(const [name,key] of Object.entries(DOCS)) if(!splitManaged(operation.documents[name].baseline,key).absent) return fail('managed-adoption-conflict');
    } else {
      if(!state.managed) return fail('unmanaged-campaign');
      const status=refinementProjectionStatus(root,roadmap);
      if(!status.consistent) return fail(status.error || 'projection-lag','Replay the committed operation before another mutation');
    }
    if(operation.step_id && !roadmap.roadmap_projection.some(s=>s.id===operation.step_id)) return fail('unknown-step');
    if(operation.action==='present') {
      if(operation.product_context!==undefined || (operation.product_context_version!==undefined && operation.product_context_version!==1))
        return fail('invalid-product-context','The reducer derives product context; callers cannot supply its digest map.');
      operation.product_context_version=1;
    }
    if(operation.action==='open_slice') {
      const step=roadmap.roadmap_projection.find(s=>s.id===operation.step_id);
      if(step?.component_ids?.length && operation.product_ids.some(id=>!step.component_ids.includes(id))) return fail('kickoff-product-id-mismatch');
    }
    if(operation.action==='visual_companion') {
      const revision=state.slices[operation.step_id]?.revisions[operation.revision_id];
      if(!revision || revision.hash!==operation.source_hash) return fail('preview-source-mismatch');
      const source=contained(root,operation.preview_source_path);
      const bytes=fs.readFileSync(source),hash=sha(bytes);
      if(path.extname(source).toLowerCase()!=='.pdf' || !bytes.subarray(0,5).equals(Buffer.from('%PDF-')))
        return fail('preview-must-be-pdf');
      if(operation.preview_hash && operation.preview_hash!==hash) return fail('preview-hash-mismatch');
      const rel=`deliverables/${revision.product_id}/${hash}.pdf`,dest=contained(root,rel,false);
      fs.mkdirSync(path.dirname(dest),{recursive:true});
      if(fs.existsSync(dest) && sha(fs.readFileSync(dest))!==hash) return fail('artifact-hash-mismatch');
      if(!fs.existsSync(dest)) writeFileAtomicSync(dest,bytes);
      operation.preview={path:rel,hash};
    }
    if(operation.action==='publish') {
      operation.products=operation.products.map(p=>{
        const source=contained(root,p.source_path || p.path);
        // encoding-lint: raw-bytes — hash/copy all artifact formats without text conversion.
        const bytes=fs.readFileSync(source), hash=sha(bytes);
        if(p.hash && p.hash!==hash) throw Object.assign(new Error('Source bytes changed'),{code:'artifact-hash-mismatch'});
        if(!/^[A-Za-z0-9_-]+$/.test(p.product_id)) throw Object.assign(new Error('Invalid stable product ID'),{code:'invalid-product-id'});
        const rel=`deliverables/${p.product_id}/${hash}${path.extname(source).toLowerCase()}`;
        const dest=contained(root,rel,false);
        fs.mkdirSync(path.dirname(dest),{recursive:true});
        if(fs.existsSync(dest)) {
          // encoding-lint: raw-bytes — immutable binary digest comparison.
          if(sha(fs.readFileSync(dest))!==hash) throw Object.assign(new Error('Preserved revision was modified'),{code:'artifact-hash-mismatch'});
        } else writeFileAtomicSync(dest,bytes);
        return {...p,path:rel,hash};
      });
    }
    return {ok:true,event:{...event,operation}};
  } catch(e) { return fail(e.code || 'invalid-refinement-operation',e.message); }
}

/** Separate event warnings admitted by the normal writer from projection drift. */
export function refinementRoadmapStatus(roadmap) {
  const validated=validateRoadmap(roadmap),events=roadmap.roadmap_events;
  const issues=validated.issues || [];
  const adoption=events.findIndex(e=>e?.kind==='refinement_update' && e.operation?.action==='adopt');
  const boundaryValid=adoption>=0 && events[adoption].seq===adoption+1 &&
    events[adoption].operation.expected_seq===adoption;
  const replays=new Map();
  const invalid_issues=issues.filter(issue=>{
    if(!boundaryValid || !Number.isInteger(issue.at_index) || issue.at_index<0 || issue.at_index>=events.length) return true;
    // Adoption accepted this prefix under the existing legacy writer contract.
    // Preserve its warnings; neither repair nor read certifies it as clean.
    if(issue.at_index<adoption) return false;
    if(issue.code==='event_seq_break') return true;
    let replay=replays.get(issue.at_index);
    if(!replay) {
      const prefix=events.slice(0,issue.at_index);
      // Force validation, rather than the writer's client-ID retry shortcut.
      const {client_event_id,...event}=events[issue.at_index];
      replay=appendRoadmapEvent({...roadmap,roadmap_events:prefix,
        roadmap_projection:buildRoadmapProjection(prefix).projection},event);
      replays.set(issue.at_index,replay);
    }
    // Managed status overlays can make a writer-admitted flip warn in the full
    // fold. Only the same warning reproduced by the normal append law is safe.
    return !replay.ok || replay.idempotent ||
      !replay.issues.some(candidate=>refinementDigest(candidate)===refinementDigest(issue));
  });
  if(adoption>=0 && !boundaryValid) invalid_issues.push({code:'adoption_sequence_mismatch',at_index:adoption});
  return {consistent:validated.ok && invalid_issues.length===0,clean:validated.clean===true,
    ...(validated.error ? {error:validated.error} : invalid_issues.length ? {error:'roadmap-events-invalid'} : {}),
    ...(validated.drift ? {drift:validated.drift} : {}),issues,invalid_issues};
}

export function refinementResult(root, roadmap) {
  const state=foldRefinements(roadmap.roadmap_events);
  const navigation=Object.fromEntries(buildRoadmapProjection(roadmap.roadmap_events).projection
    .filter(s=>s.navigation).map(s=>[s.id,s.navigation]));
  const documents=refinementProjectionStatus(root,roadmap);
  const roadmap_projection_status=refinementRoadmapStatus(roadmap);
  const refinement_projection_status={consistent:!state.managed ||
    (roadmap.refinement_projection!=null && refinementDigest(roadmap.refinement_projection)===refinementDigest(state))};
  const finished=state.managed ? approvedProjectionStatus(root,state,navigation) : null;
  return {ok:true,state,sequence:roadmap.roadmap_events.length,projection_status:documents,
    roadmap_projection_status,refinement_projection_status,
    consistent:roadmap_projection_status.consistent && refinement_projection_status.consistent &&
      documents.consistent && (!finished || finished.consistent),
    approved_products:approvedDeliverables(state,navigation),
    current_approvals:Object.fromEntries(Object.entries(state.slices).map(([id,slice])=>[id,currentProductApprovals(slice)])),
    finished_projection:finished,
    ...(Object.keys(navigation).length ? {navigation} : {})};
}

export function verbRefinementUpdate(opts={}) {
  try {
    const input=opts.refinement_operation || JSON.parse(fs.readFileSync(0,'utf8'));
    if(input.action==='capabilities') return {ok:true,capabilities:{schema:REFINEMENT_SCHEMA,version:1,
      actions:['producer_handoff','resolve_handoff','visual_companion'],
      individual_completion:true,approved_collection:true,provisional_publish:true}};
    const root=path.resolve(opts.project || '.');
    const loaded=loadProjectRoadmap(root);
    if(!loaded.ok || !loaded.exists) return fail(loaded.exists?'backing-store-unreadable':'empty-but-valid');
    if(input.action==='read') return refinementResult(root,loaded.roadmap);
    if(input.action==='repair') {
      return repairRoadmapProjectionsThroughSpine(root,{timeoutMs:opts.timeoutMs});
    }
    if(input.action==='operation_status') {
      const found=loaded.roadmap.roadmap_events.find(e=>e.kind==='refinement_update'&&e.operation?.operation_id===input.operation_id);
      const result=refinementResult(root,loaded.roadmap);
      return {...result,operation_id:input.operation_id,committed:!!found,result:found?{...result,committed:true,operation_id:input.operation_id}:undefined};
    }
    if(!input.operation_id || !Number.isInteger(input.expected_seq)) return fail('operation-id-and-sequence-required');
    if(input.action==='close') {
      // cockpit Wave B: the steward's close states the next act and the goal re-read first
      const demand=demandClose(root,loaded.roadmap,input.step_id,input.goal_reread??null);
      if(!demand.ok) return demand;
    }
    const result=appendRoadmapEventThroughSpine(root,{kind:'refinement_update',at:new Date().toISOString(),client_event_id:input.operation_id,request_digest:refinementDigest(input),operation:input},{skip_index:true});
    if(!result.ok) return result;
    const view=refinementResult(root,result.roadmap);
    return {...view,committed:true,operation_id:input.operation_id,idempotent:result.idempotent};
  } catch(e) { return fail(e.code || 'invalid-refinement-operation',e.message); }
}
