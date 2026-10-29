/* Lamp presentation only. Geometry and math reuse the landed pure Foundry seam. */
(() => {
  'use strict';
  const D=globalThis.FOUNDRY_MAPS, api=globalThis.FoundryDisplay, $=s=>document.querySelector(s);
  const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const R=new Map(D.resources.map(r=>[r.id,r])), A=new Map(D.anchors.map(a=>[a.id,a]));
  const S=new Map(D.sources.map(s=>[s.id,s])), P=new Map(D.process.steps.map(s=>[s.id,s]));
  const N=D.knowledge.nodes, pos=api.seededPositions(N);
  const queryPersona=new URLSearchParams(location.search).get('persona');
  const state={view:matchMedia('(max-width:760px)').matches?'outline':'disk',focus:null,query:'',category:'',
    persona:D.personas[queryPersona]?queryPersona:(D.personas[globalThis.FOUNDRY_PERSONA]?globalThis.FOUNDRY_PERSONA:'aladdin')};
  function resource(id,label){const r=R.get(id);return '<a class="button" data-resource="'+id+'" href="'+esc(r.target)+'">'+esc(label||r.title)+'</a>';}
  function anchor(id){const a=A.get(id),s=S.get(a.source_id);return '<a class="anchor-link" data-source="'+id+'" href="source-pages/'+a.source_id+'.html#L'+a.start+'">'+esc(a.source_id)+' · '+esc(s.kind)+' · L'+a.start+'–'+a.end+'</a>';}
  function knowledge(){
    let graphic;
    if(state.view==='outline'){
      const branch=id=>'<ul>'+N.filter(n=>n.parent_id===id).map(n=>'<li>'+resource(n.resource_id,n.title)+'<small>Declared depth '+n.ring+' · '+esc(n.facets.join(', '))+'</small>'+branch(n.id)+'</li>').join('')+'</ul>';
      graphic='<div class="outline">'+branch(null)+'</div>';
    }else{
      const focus=state.focus?pos.get(state.focus):{x:0,y:0};
      const xy=n=>{const p=api.recenter(pos.get(n.id),focus);return {x:300+270*p.x,y:300+270*p.y};};
      graphic='<svg class="disk" viewBox="0 0 600 600" role="group" aria-label="Seeded Lamp knowledge disk"><circle class="boundary" cx="300" cy="300" r="280"/>';
      for(const n of N.filter(n=>n.parent_id)){const p=xy(N.find(a=>a.id===n.parent_id)),q=xy(n);graphic+='<line class="edge" x1="'+p.x+'" y1="'+p.y+'" x2="'+q.x+'" y2="'+q.y+'"/>';}
      const labels={purpose:'One effort',continuity:'Continuity',discovery:'Discovery',writers:'Writers',dispatch:'Dispatch',supervision:'Supervision',persona:'Persona'};
      for(const n of N){const p=xy(n);graphic+='<a data-node="'+n.id+'" data-resource="'+n.resource_id+'" href="'+esc(R.get(n.resource_id).target)+'" aria-label="Open '+esc(n.title)+'"><title>'+esc(n.title)+'</title><circle cx="'+p.x+'" cy="'+p.y+'" r="5" fill="transparent"/><circle class="dot '+(n.ring===0?'root-dot':n.ring===1?'domain-dot':'')+'" cx="'+p.x+'" cy="'+p.y+'" r="'+(n.ring===0?10:n.ring===1?7:5)+'"/>'+(n.ring<=1&&!state.focus?'<text x="'+p.x+'" y="'+(p.y+23)+'" text-anchor="middle">'+esc(labels[n.id])+'</text>':'')+'</a>';}
      graphic+='</svg>';
    }
    return '<h2>Knowledge map</h2><p>Explore continuity, discovery, writers, dispatch and supervision. Every node opens useful Library material and its precise original-source excerpt.</p><p class="badge">Seeded geometry · resource access frequency unknown</p><div class="toolbar"><button data-view="disk">Disk</button><button data-view="outline">Outline</button><button data-focus="">Whole map</button></div><div class="map-wrap"><div class="map-board">'+graphic+'</div><aside class="map-side"><h3>Explore a branch</h3>'+N.filter(n=>n.ring===1).map(n=>'<p><button data-focus="'+n.id+'">'+esc(n.title)+'</button></p>').join('')+'<p>Declared parent tree projected into a disk. Positions, distances and dot size do not measure learned similarity, importance or frequency. Outline names every resource.</p></aside></div>';
  }
  function library(){
    const hits=D.resources.filter(r=>(!state.category||r.category===state.category)&&[r.id,r.title,r.summary].join(' ').toLowerCase().includes(state.query.toLowerCase()));
    return '<h2>Library</h2><p>Reusable operator material, instructions, tools, specialist skills and real examples. Recurring needs come from the workflow; actual resource accesses are not captured.</p><div class="toolbar"><label for="library-search">Find a resource</label><input id="library-search" type="search" value="'+esc(state.query)+'"><select id="category" aria-label="Resource category"><option value="">All categories</option>'+[...new Set(D.resources.map(r=>r.category))].map(c=>'<option '+(c===state.category?'selected':'')+'>'+esc(c)+'</option>').join('')+'</select></div><p>'+hits.length+' resources</p><div class="card-grid">'+hits.map(r=>'<article class="card"><p class="eyebrow">'+esc(r.category)+'</p><h3>'+esc(r.title)+'</h3><p>'+esc(r.summary)+'</p><p class="note">Access frequency unknown</p>'+resource(r.id,'Open resource')+'</article>').join('')+'</div>';
  }
  function process(id){
    const s=P.get(id)||P.get(D.process.entry),out=D.process.edges.filter(e=>e.source===s.id);
    const groups=['Invocation and continuity','Conversation and recorded authority','Writers, depth and dispatch','Background ownership, status and handback','Inspection, feedback and explicit close','Recovery, improvement and stopping'];
    return '<h2>Process map</h2><p class="process-summary">Invocation → continuity and authority → bounded work → inspect the exact output → versioned feedback → explicit human boundary.</p><p class="note">Two source-qualified entry lanes: persistent Anchor cockpit, or an explicitly invoked Node CLI/dialogue API. They are alternatives, not successive mandatory calls. Every branch below opens its precise source.</p><article class="detail" id="step-detail" data-step-id="'+s.id+'"><p class="eyebrow">'+esc(s.kind)+' · '+esc(s.role)+'</p><h2>'+esc(s.title)+'</h2><p>'+esc(s.summary)+'</p><div class="anchor-list">'+s.anchors.map(anchor).join('')+'</div><div class="actions">'+s.resource_ids.map(r=>resource(r)).join(' ')+'</div><h3>Next branches</h3><ul class="transitions branches">'+out.map(e=>'<li><a data-transition="'+e.source+'-'+e.target+'" href="#process/'+e.target+'">'+esc(P.get(e.target).title)+'</a> — '+esc(e.label)+anchor(e.anchor_id)+'</li>').join('')+(out.length?'':'<li>End with the stated qualification. No automatic acceptance is implied.</li>')+'</ul></article>'+groups.map((title,i)=>'<h3>'+(i+1)+'. '+title+'</h3><div class="flow">'+D.process.steps.filter(s=>s.group===i+1).map(s=>'<a class="step '+s.kind+'" data-step="'+s.id+'" href="#process/'+s.id+'" '+(s.id===id?'aria-current="step"':'')+'><span class="type">'+esc(s.kind)+'</span><strong>'+esc(s.title)+'</strong></a>').join('')+'</div>').join('')+'<details class="branch-index"><summary>All '+D.process.edges.length+' source-backed transitions</summary><table><thead><tr><th>From</th><th>To</th><th>Condition</th><th>Precise source</th></tr></thead><tbody>'+D.process.edges.map(e=>'<tr><td><a href="#process/'+e.source+'">'+esc(P.get(e.source).title)+'</a></td><td><a href="#process/'+e.target+'">'+esc(P.get(e.target).title)+'</a></td><td>'+esc(e.label)+'</td><td>'+anchor(e.anchor_id)+'</td></tr>').join('')+'</tbody></table></details><p class="note">'+P.size+' steps. Depth is separate from model quality. No implicit swarm or fixed review-to-convergence loop.</p>';
  }
  function differences(){return '<h2>Instructions ↔ code</h2><p>Current source-qualified mismatches and missing runtime proof. This display changes no engine.</p>'+D.process.disagreements.map(d=>'<details class="difference" data-difference="'+d.id+'"><summary>'+esc(d.title)+'</summary><p>'+esc(d.fact)+'</p><div class="anchor-list">'+d.anchors.map(anchor).join('')+'</div></details>').join('');}
  function evidence(){return '<h2>Use and improvement</h2>'+D.observed_examples.map(e=>'<article class="card"><h3>'+esc(e.id)+'</h3><p>'+esc(e.summary)+'</p><p class="note">Recorded outcome, qualified by its date and scope. Native subscription receipt not inspected here.</p><div class="anchor-list">'+e.anchors.map(anchor).join('')+'</div></article>').join('')+'<h3>What is measured</h3><p>'+D.usage_audit.records+' named machine records were captured and checked for explicit resource IDs. Neither names them. This sample is not an exhaustive inventory, unique-run count, access frequency or learned map.</p><h3>Existing improvement pathway</h3><p>Real outcome and named shortfall → curated entry and machine capture → candidate lesson → existing formal improvement commissioning, approval and checks. Demonstrated current-version use is required before construction. This draft adds no engine wave, training service or automatic lesson promotion.</p>'+resource('improvement')+' '+resource('construction-freeze')+' '+resource('capture');}
  function handoff(){
    const examples=D.sources.filter(s=>s.freshness==='frozen-example');
    return '<h2>Anchor handoff</h2><p><a href="maps.json">maps.json</a> uses foundry-skill-display/v1 with stable role steward-project. Persona changes labels and icons, never role identity.</p>'+
      '<p class="badge">Initial draft · gwl-walk-steward-lamp · source-check repair; held pending landing and integration, independent feedback remains open</p>'+
      '<h3>Required Anchor follow-up</h3>'+D.integration.gaps.map(g=>'<p class="note">'+esc(g)+'</p>').join('')+
      '<p>The current adapter expects steward-project/maps.json. This requested bundle is steward-lamp/maps.json; it deliberately has no duplicate or silent role substitution. Original-source roots also require a contained reader follow-up.</p>'+
      '<h3>Source checks and historical examples</h3><p>Code, instructions and skill guides are copied from authoritative sources and must still match at the final check. Each source page shows its capture time and hash. Those on-disk sources do not prove activation in the running build.</p>'+
      '<p>Campaign state, dialogue, journals and run receipts are frozen historical examples. Later updates to their originals do not change the example; corruption of a delivered copy still fails. Their exact original path, capture time, hash and applicability appear on every source page.</p>'+
      '<details id="historical-sources"><summary>Open the '+examples.length+' captured historical records</summary>'+examples.map(s=>'<p>'+anchor('a-'+s.id)+'<br>'+esc(s.applicability)+'</p>').join('')+'</details>'+
      '<p>researchPrime Refinement 1, Gandalf Initial draft, original v7 and cumulative feedback remain intact. Aladdin keeps stewardship; this code job does not accept or close a slice.</p>'+
      '<p><a href="resources/index.html">Complete Library</a> · <a href="screenshots/desktop-library.png">Desktop Library</a> · <a href="screenshots/phone-process.png">Phone process</a> · <a href="browser-evidence.json">Exact-output browser checks</a> · <a href="handoff-evidence.json">Plan handoff checks</a></p>'+
      '<p class="note">Isolated browser evidence is not live Anchor activation, native seat attestation or human acceptance.</p>';
  }
  function render(){const [view,id]=location.hash.slice(1).split('/'),current=['knowledge','library','process','differences','evidence','handoff'].includes(view)?view:'knowledge';document.querySelectorAll('[data-tab]').forEach(a=>a.dataset.tab===current?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));$('#panel').innerHTML={knowledge,library,process:()=>process(id),differences,evidence,handoff}[current]();}
  function livery(){
    const p=D.personas[state.persona];document.querySelectorAll('[data-persona-label]').forEach(el=>el.textContent=p.title);
    $('#persona-icon').src=p.icon;$('#persona-icon').alt=p.title+' icon';$('#persona-favicon').href=p.icon;
    document.title=p.title+' Library and maps · Initial draft';$('#persona').value=state.persona;
    const names={aladdin:['Aladdin-Cave of Wonders','Aladdin-Star Chart'],jarvis:['Jarvis-Tip of the Hat','Jarvis-Chart Room'],ecgberht:['Ecgberht-High Seat','Ecgberht-Beacon']};
    [$('#cave-name').textContent,$('#chart-name').textContent]=names[state.persona];
  }
  function open(target,title){$('#resource-title').textContent=title;$('#resource-frame').src=target;$('#resource-new-tab').href=target;$('#resource-dialog').showModal();}
  document.addEventListener('click',e=>{const r=e.target.closest('[data-resource]');if(r&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey){e.preventDefault();open(R.get(r.dataset.resource).target,R.get(r.dataset.resource).title);return;}const a=e.target.closest('[data-source]');if(a&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey){e.preventDefault();open(a.getAttribute('href'),'Source · '+A.get(a.dataset.source).source_id);return;}const view=e.target.closest('[data-view]');if(view){state.view=view.dataset.view;render();}const focus=e.target.closest('[data-focus]');if(focus){state.focus=focus.dataset.focus||null;state.view='disk';render();}});
  document.addEventListener('input',e=>{if(e.target.id==='library-search'){const at=e.target.selectionStart;state.query=e.target.value;render();$('#library-search').focus();$('#library-search').setSelectionRange(at,at);}});
  document.addEventListener('change',e=>{if(e.target.id==='category'){state.category=e.target.value;render();}if(e.target.id==='persona'){state.persona=e.target.value;livery();}});
  $('#close-resource').addEventListener('click',()=>$('#resource-dialog').close());$('#resource-dialog').addEventListener('close',()=>$('#resource-frame').removeAttribute('src'));
  window.addEventListener('hashchange',()=>{render();if(location.hash.startsWith('#process/'))$('#step-detail').scrollIntoView({block:'start'});});
  livery();render();
})();
