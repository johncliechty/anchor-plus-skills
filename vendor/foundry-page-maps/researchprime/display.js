(function () {
  'use strict';
  const api = globalThis.FoundryDisplay;
  const flow = globalThis.FoundryFlowDiagram;
  const layerLib = globalThis.FoundryLayerLibrary;
  const display = api.createDisplay(globalThis.RESEARCHPRIME_MAPS);
  const D = display.data;
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value).replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const resources = new Map(D.resources.map(r=>[r.id,r]));
  const steps = new Map(D.process.steps.map(s=>[s.id,s]));
  const anchors = new Map(D.anchors.map(a=>[a.id,a]));
  const sources = new Map(D.sources.map(s=>[s.id,s]));
  const nodes = D.knowledge.nodes;
  const positions = api.seededPositions(nodes);
  const layers = layerLib.buildLayers(D.knowledge, D.resources);
  const state = {knowledgeView:matchMedia('(max-width:700px)').matches?'outline':'disk', query:'', focus:null, selected:null, lens:'all',
                 libPath:[layers.root.id], processView:'diagram'};
  const groups = [
    ['1 · Receive, plan and approve',['entry','probe','planning','plan-entry','provider','scope-gate','scope-edit','plan-build','plan-gate','plan-edit','prose-gate']],
    ['2 · Fresh execution and evidence',['isolation','gather','status','degraded']],
    ['3 · Start validation and select seats',['round-entry','budget','route','panel-branch','sidecar','artifact','panel','supervise','supplied']],
    ['4 · Govern reviews and adjudicate',['governor','tally','debate','adjudicate','judge','synth','join','rc6']],
    ['5 · Checkpoint, continue or stop',['checkpoint','stop','correct','honesty','deliver','capture','pending','halt']],
    ['6 · Produce the human outputs',['reports','done']],
  ];
  function resourceLink(id, title, cls='button secondary') {
    return `<a class="${cls}" data-resource="${esc(id)}" href="${esc(display.resourceTarget(id))}">${esc(title || resources.get(id).title)}</a>`;
  }
  function anchorLink(id) {
    const a=anchors.get(id), source=sources.get(a.source_id);
    return `<a class="anchor-link" data-source="${esc(id)}" href="source-pages/${esc(source.id)}.html#L${a.start}">${esc(source.id)} · ${esc(source.kind)} · L${a.start}–${a.end}</a>`;
  }
  function route() {
    const [view, id] = location.hash.slice(1).split('/');
    return {view:['knowledge','library','process','differences','review','handoff'].includes(view)?view:'knowledge', id:steps.has(id)?id:'entry'};
  }
  function filteredNodes() {
    const ids=new Set(display.search(state.query).map(r=>r.id));
    return nodes.filter(n=>ids.has(n.resource_id) && (state.lens==='all' || n.process_ids.length));
  }
  function knowledge() {
    const hits=filteredNodes(), hitIds=new Set(hits.map(n=>n.id));
    const focus=state.focus?positions.get(state.focus):{x:0,y:0};
    const project = n => {const p=api.recenter(positions.get(n.id),focus);return {x:300+p.x*270,y:300+p.y*270};};
    let graphic;
    if (state.knowledgeView==='disk') {
      graphic='<svg class="disk" viewBox="0 0 600 600" role="group" aria-label="Seeded Poincaré knowledge disk">';
      graphic+='<circle class="boundary" cx="300" cy="300" r="276"/>';
      for (const r of [110,198,240]) graphic+=`<circle class="ring" cx="300" cy="300" r="${r}"/>`;
      for (const n of nodes.filter(n=>n.parent_id)) {
        const p=project(nodes.find(k=>k.id===n.parent_id)), q=project(n);
        graphic+=`<line class="edge" x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}"/>`;
      }
      for (const n of nodes) {
        const p=project(n), isRoot=n.parent_id===null, isDomain=n.ring===1;
        const label=isRoot?'A useful answer':n.title;
        graphic+=`<a href="${esc(display.resourceTarget(n.resource_id))}" data-resource="${esc(n.resource_id)}" data-node="${esc(n.id)}" tabindex="0" aria-label="Open ${esc(n.title)}" class="${hitIds.has(n.id)?'':'dim'}"><title>${esc(n.title)} · ${esc(resources.get(n.resource_id).title)}</title><circle cx="${p.x}" cy="${p.y}" r="${isRoot?18:isDomain?13:10}" fill="transparent"/><circle class="dot ${isRoot?'root-dot':isDomain?'domain-dot':''}" cx="${p.x}" cy="${p.y}" r="${isRoot?10:isDomain?7:5}"/>${(isRoot||isDomain) && !state.focus?`<text x="${p.x}" y="${p.y+23}" text-anchor="middle">${esc(label)}</text>`:''}</a>`;
      }
      graphic+='</svg>';
    } else {
      function branch(parent) {
        return '<ul>'+nodes.filter(n=>n.parent_id===parent).map(n=>`<li>${resourceLink(n.resource_id,n.title,'outline-link')}<small>Declared depth ${n.ring} · ${esc(n.facets.join(', '))}</small>${branch(n.id)}</li>`).join('')+'</ul>';
      }
      graphic='<div class="outline">'+branch(null)+'</div>';
    }
    const selected=nodes.find(n=>n.id===state.selected);
    const selectedCard=selected?`<div class="source-card"><h3>${esc(selected.title)}</h3><p>${esc(resources.get(selected.resource_id).summary)}</p>${resourceLink(selected.resource_id)}<p class="count">Process links: ${selected.process_ids.map(id=>`<a href="#process/${id}">${esc(steps.get(id).title)}</a>`).join(' · ')||'none claimed'}</p><button data-focus="${selected.id}">Focus this region</button></div>`:'';
    return `<h2>Knowledge map</h2><p>Start with the research question at the center. Branch outward into planning, evidence, validation and explanation. Every node opens a real Library resource — and the Library tab descends these same layers with a level dial.</p>
      <p class="badge">Seeded hierarchy · no learned coordinates · use frequency unknown</p>
      <div class="toolbar"><label for="map-search">Find knowledge</label><input id="map-search" type="search" placeholder="Try judge, approval or evidence" value="${esc(state.query)}">
      <button data-view="disk" aria-pressed="${state.knowledgeView==='disk'}">Disk</button><button data-view="outline" aria-pressed="${state.knowledgeView==='outline'}">Outline</button>
      <button data-focus="">Reset center</button><select id="lens" aria-label="Knowledge lens"><option value="all">All sources</option><option value="process" ${state.lens==='process'?'selected':''}>Used by process steps</option></select></div>
      <p class="count" aria-live="polite">${hits.length} of ${nodes.length} nodes match. ${state.focus?'Focused on '+esc(nodes.find(n=>n.id===state.focus).title)+'.':''}</p>
      <div class="map-wrap"><div class="map-board">${graphic}</div><aside class="map-side" aria-label="Map reading guide"><div><h3>Explore a branch</h3>
      ${nodes.filter(n=>n.ring===1).map(n=>`<button class="button secondary" data-focus="${n.id}">${esc(n.title)}</button>`).join('')}</div>
      <div><h3>What position means</h3><p>Center = general; rim = specific. Positions come from the declared parent tree, projected into the disk. Refocusing changes the view.</p>
      <p>Importance, frequency and learning are unmeasured here. Instruction, code and reference facets remain separate.</p></div>${selectedCard}</aside></div>
      <p class="note" style="margin-top:16px">The outline uses the same resource ids. Search highlights the disk; the complete outline keeps the hierarchy visible. ${resourceLink('map-concept','Read the geometry qualifications','inline-link')}</p>`;
  }
  function library() {
    return `<h2>Library — the knowledge map, layer by layer</h2>
      <p>The Library is grouped by the knowledge-map layers. Top level is the map itself; descend level by level with the dial or the branch cards. Every layer summarizes the four kinds of material below it — reusable material, references, tools and skills — and resource tiles appear only at the leaf you chose, so the layout holds at any catalog size.</p>
      <div class="toolbar"><label for="library-search">Find a resource</label><input id="library-search" type="search" placeholder="Search leaves across all layers" value="${esc(state.query)}"></div>
      ${layerLib.renderLayerLibrary(D, {path: state.libPath, query: state.query}, {resourceLink})}
      <p class="note" style="margin-top:14px">Catalog counts come from the declared map; use frequency stays unknown until a verified run names a resource id. <a href="resources/index.html" data-resource-index>Complete flat index (every resource)</a> remains available for audits.</p>`;
  }
  function process(id) {
    const s=steps.get(id), outgoing=D.process.edges.filter(e=>e.source===id), incoming=D.process.edges.filter(e=>e.target===id);
    const swarm=s.swarm.enabled?`<p><strong>Swarm:</strong> ${s.swarm.bounded?`${s.swarm.count} roster seats; at most ${s.swarm.concurrency_cap} simultaneous logical roster jobs. ${esc(s.swarm.limitation)}`:esc(s.swarm.limitation)} ${esc(s.swarm.knob)}</p>`:'';
    const reconcileItems=D.process.disagreements.filter(d=>(d.step_ids||[]).includes(id));
    const reconcile=reconcileItems.length?`<div class="reconcile-node"><h3>Instructions ≠ code on this node</h3>${reconcileItems.map(d=>`<details class="difference"><summary>${esc(d.title)}</summary><p><strong>Instruction says:</strong> ${esc(d.instruction_says)}</p><p><strong>Code does:</strong> ${esc(d.code_does)}</p><p><strong>A run follows:</strong> ${esc(d.follows)}</p><div class="anchor-list">${anchorLink(d.instruction_anchor)}${anchorLink(d.code_anchor)}</div><p class="note"><a href="#differences">Open the full reconciliation record →</a></p></details>`).join('')}</div>`:'';
    const graphic = state.processView==='diagram'
      ? flow.style + `<div class="diagram-scroll">${flow.renderFlowDiagram(D.process,{selected:id})}</div>`
      : groups.map(([title,ids])=>`<section class="process-group"><h3>${esc(title)}</h3><div class="flow">${ids.map(sid=>{const n=steps.get(sid), next=D.process.edges.filter(e=>e.source===sid);return `<a class="step ${n.kind}" href="#process/${sid}" data-step="${sid}" ${sid===id?'aria-current="step"':''}><span class="type">${esc(flow.TYPES[n.display_type]||n.display_type)}</span><strong>${esc(n.title)}</strong><span class="next">${next.length?'→ '+next.map(e=>esc(steps.get(e.target).title)).join(' / '):'End with recorded reason'}</span></a>`;}).join('')}</div></section>`).join('');
    return `<h2>Process map</h2><p class="note">Question → plan and approval → fresh evidence → governed review rounds → research reports. Click a node to select it; its full record waits right below the drawing and expands only when you open it. Nodes marked ≠ carry a documented instruction/code disagreement.</p>
      ${graphic}
      <details class="detail" id="step-detail" data-step-id="${s.id}"><summary><span class="eyebrow">${esc(flow.TYPES[s.display_type]||s.display_type)}${s.role?' · '+esc(s.role):''}</span><strong>${esc(s.title)}</strong><span class="note">Expand the full record — summary, source anchors and branches</span></summary>
      <p style="margin-top:14px">${esc(s.summary)}</p>
      <p class="note">${s.code_status==='anchored'?'Actual code anchor available':'Instructions only; no program implementation claimed'}. ${s.instruction_status==='anchored'?'Instruction anchor available.':'No separate instruction anchor.'}</p>${swarm}
      <div class="anchor-list">${s.anchors.map(anchorLink).join('')}</div><div class="actions">${s.resource_ids.map(rid=>resourceLink(rid)).join('')}</div>
      ${reconcile}
      <h3 style="margin-top:18px">Next branches</h3><ul class="transitions">${outgoing.map(e=>`<li><a href="#process/${e.target}">${esc(steps.get(e.target).title)}</a> — ${esc(e.label)} · ${anchorLink(e.anchor_id)}</li>`).join('')||'<li>This route ends with its recorded reason.</li>'}</ul>
      <details><summary>Arrives from ${incoming.length} branch${incoming.length===1?'':'es'}</summary><ul class="transitions">${incoming.map(e=>`<li><a href="#process/${e.source}">${esc(steps.get(e.source).title)}</a> — ${esc(e.label)}</li>`).join('')}</ul></details></details>
      ${state.processView==='diagram'?flow.legend():''}
      <div class="toolbar"><button data-process-view="diagram" aria-pressed="${state.processView==='diagram'}">Flow diagram</button><button data-process-view="list" aria-pressed="${state.processView==='list'}">Compact list</button></div>
      <p class="note">${D.process.steps.length} source-backed steps · ${D.process.edges.length} transitions. Depth, stakes, model effort and round count have separate controls. ${resourceLink('thresholds','Open the default stopping thresholds','inline-link')}</p>`;
  }
  function differences() {
    return `<h2>Instructions ↔ code — the reconciliation record</h2><p>The saved instructions describe intended behavior; the code anchors show what the validation programs actually do. Each disagreement records what the instruction says, what the code does, and which one a run actually follows — with a source anchor on both sides. This effort documents and proposes; John decides. No skill source was edited.</p>
      <p class="count">${D.process.disagreements.length} reconciliation items · each is badged ≠ on its process-map nodes</p>
      ${D.process.disagreements.map(d=>`<details class="difference" data-difference="${d.id}"><summary>${esc(d.title)}</summary><p>${esc(d.fact)}</p>
      <div class="reconcile-grid"><div><h4>What the instruction says</h4><p>${esc(d.instruction_says)}</p>${anchorLink(d.instruction_anchor)}</div>
      <div><h4>What the code does</h4><p>${esc(d.code_does)}</p>${anchorLink(d.code_anchor)}</div>
      <div><h4>Which one a run follows</h4><p>${esc(d.follows)}</p></div></div>
      <p class="count">On the map: ${(d.step_ids||[]).map(id=>`<a href="#process/${id}">${esc(steps.get(id).title)}</a>`).join(' · ')||'—'}</p>
      <div class="anchor-list">${d.anchors.map(anchorLink).join('')}</div>${d.anchors.map(id=>{const a=anchors.get(id);return `<details><summary>${esc(a.source_id)} · lines ${a.start}–${a.end}</summary><pre class="excerpt">${esc(a.quote)}</pre></details>`;}).join('')}</details>`).join('')}`;
  }
  function review() {
    return `<h2>Review record</h2><p>Cumulative human feedback on this product. Each refinement preserves the one before it; John's feedback is what moves the iteration forward.</p>
      ${D.review.cumulative.map(r=>`<article class="card review-entry" data-review="${r.refinement}"><p class="eyebrow">Refinement ${r.refinement} · reviewed ${esc(r.reviewed)} by ${esc(r.reviewer)}</p>
      <h3>Grade: ${esc(r.grade)}</h3><blockquote class="verdict">${esc(r.verdict)}</blockquote>
      <h4>The five points</h4><ol class="review-points">${r.points.map(p=>`<li>${esc(p)}</li>`).join('')}</ol>
      <h4>What Refinement 2 changed</h4><p>${esc(r.response)}</p></article>`).join('')}
      <p class="note">Refinement 1 stays preserved under <a href="refinement-1/maps.json">refinement-1/</a> and mockup v7 under its original path. This record implies no acceptance and closes nothing; those calls are John's.</p>`;
  }
  function handoff() {
    return `<h2>Anchor handoff</h2><p>The Library, knowledge map and process diagram share stable resource, source, anchor, node and step ids. Anchor can mount this data in its actual Foundry page and route resource clicks through its source viewer. Another code job owns Anchor; this list is what its adapter must pick up for Refinement 2.</p>
      <div class="card"><h3>Ready to consume</h3><p><a href="maps.json">maps.json</a> — versioned display data.<br><a href="adapter.mjs">adapter.mjs</a> — pure settings, lookup, search, geometry and route adapter.<br><a href="flow-diagram.js">flow-diagram.js</a> + <a href="layer-library.js">layer-library.js</a> — byte-identical copies of the shared diagram and layered-library components (canonical in <span class="path">shared/</span>).<br><a href="resources/index.html">Library index</a> — all openable resources.</p>
      <p class="note">The adapter receives a resolveTarget callback with an allowlisted resource id, exact source hash and line range. Resource lookups never accept arbitrary filesystem paths. It has no model launch or campaign-write API.</p></div>
      <h3 style="margin-top:24px">What Anchor's adapter still needs to do</h3><ul class="handoff">${D.integration.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul>
      <details><summary>Captured desktop and phone views</summary><ul>${['desktop-knowledge','desktop-focus','desktop-outline','desktop-library','desktop-library-leaf','desktop-process','desktop-source','desktop-differences','desktop-review','phone-knowledge','phone-disk','phone-library','phone-process','phone-process-detail','phone-resource'].map(name=>`<li><a href="screenshots/${name}.png" target="_blank" rel="noopener">${esc(name)}.png</a></li>`).join('')}</ul><p class="note"><a href="browser-evidence.json">browser-evidence.json</a> binds these captures to the exact maps.json bytes.</p></details>
      <details><summary>Settings and evidence contract</summary><p>Preview persona: ${esc(D.settings.steward_type)}. Requested coding family: ${esc(D.settings.coding_family)}; review family: ${esc(D.settings.review_family)}. These are display preferences, not a model-service receipt.</p>
      <p>Settings source: ${esc(D.settings.source)} snapshot; revision ${esc(D.settings.settings_revision)}. Resolve the complete current primary at mount. An existing invalid primary blocks fallback; only an absent primary permits the mirror. Other personas require their selected names and icons from Anchor.</p>
      <p>Use counts require unique runs explicitly naming resource ids, receipt paths and hashes, plus the host’s receipt verifier. Empty evidence means unknown, not zero. Learned geometry needs a separate verified dataset; this adapter admits the seed only.</p>
      <pre class="excerpt">import {createDisplay, resolveDisplaySettings} from './adapter.mjs';
const selected = resolveDisplaySettings({primary, mirror});
const view = createDisplay(dataset, {selectedSettings: selected, resolveTarget});
// view.resourceTarget('approval') opens a host-verified resource route.</pre></details>
      <p class="review-note">Aladdin remains the responsible steward. No product is accepted, no slice is closed, and the Anchor page is not installed by this bundle.</p>`;
  }
  function render() {
    const current=route();
    document.querySelectorAll('[data-tab]').forEach(a=>{if(a.dataset.tab===current.view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#panel').innerHTML={knowledge,library,process:()=>process(current.id),differences,review,handoff}[current.view]();
  }
  function revealSelected(id) {
    // The drawing itself stays in the viewport on Process opening and node
    // selection: pan inside the scroll box to center the selected node, then
    // bring the box — never the step record — to the top of the window.
    const box=$('.diagram-scroll');
    if(!box)return;
    const node=box.querySelector('[data-step="'+id+'"]');
    if(node){
      const b=box.getBoundingClientRect(), n=node.getBoundingClientRect();
      box.scrollLeft+=(n.left+n.width/2)-(b.left+b.width/2);
      box.scrollTop+=(n.top+n.height/2)-(b.top+b.height/2);
    }
    box.scrollIntoView({block:'start'});
  }
  function afterRender() {
    const current=route();
    if(current.view==='process')revealSelected(current.id);
  }
  function openSource(target,title) {
    $('#resource-title').textContent=title;
    $('#resource-frame').src=target;
    $('#resource-new-tab').href=target;
    $('#resource-dialog').showModal();
  }
  function dialTo(level) {
    let path=[...state.libPath];
    let currentLevel=layers.byId.get(path[path.length-1]).ring;
    if (level<currentLevel) path=path.slice(0, level+1);
    else while (currentLevel<level) {
      const kids=layers.childrenOf(path[path.length-1]);
      if (kids.length!==1) break;
      path.push(kids[0].id);
      currentLevel++;
    }
    state.libPath=path;
  }
  $('#walkthrough').innerHTML=api.walkthrough(D.settings).map((w,i)=>`<${w.available?'a':'div'} class="walk" ${w.available?'href="#knowledge" aria-current="page"':''}>${w.icon?`<img src="${esc(w.icon)}" alt="" width="48" height="48">`:'<span class="placeholder">…</span>'}<span><strong>${i+1}. ${esc(w.title)}</strong><small>${w.available?'Library and maps for review':'Later walkthrough · not built here'}</small></span></${w.available?'a':'div'}>`).join('');
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-tab]');
    if(tab && !event.ctrlKey && !event.metaKey && !event.shiftKey){
      // Switching tabs must repaint before this click returns: the browser fires
      // hashchange in a later task, and the phone proof reads #panel immediately.
      event.preventDefault();
      if(location.hash!==tab.getAttribute('href'))location.hash=tab.getAttribute('href');
      render();
      afterRender();
      return;
    }
    const layerNode=event.target.closest('[data-layer-node]');
    if(layerNode){event.preventDefault();state.libPath=layers.pathTo(layerNode.dataset.layerNode);state.query='';render();return;}
    const layerJump=event.target.closest('[data-layer-jump]');
    if(layerJump){event.preventDefault();state.libPath=state.libPath.slice(0,Number(layerJump.dataset.layerJump)+1);render();return;}
    const r=event.target.closest('[data-resource]');
    if(r && !event.ctrlKey && !event.metaKey && !event.shiftKey){
      event.preventDefault();
      const id=r.dataset.resource;
      if(r.dataset.node){state.selected=r.dataset.node;render();}
      openSource(display.resourceTarget(id),resources.get(id).title);return;
    }
    const a=event.target.closest('[data-source]');
    if(a && !event.ctrlKey && !event.metaKey && !event.shiftKey){event.preventDefault();openSource(a.getAttribute('href'),'Source · '+anchors.get(a.dataset.source).source_id);return;}
    const view=event.target.closest('[data-view]');
    if(view){state.knowledgeView=view.dataset.view;render();return;}
    const pview=event.target.closest('[data-process-view]');
    if(pview){state.processView=pview.dataset.processView;render();afterRender();return;}
    const focus=event.target.closest('[data-focus]');
    if(focus){state.focus=focus.dataset.focus||null;render();return;}
  });
  document.addEventListener('input',event=>{
    if(event.target.id==='level-dial'){dialTo(Number(event.target.value));render();const dial=$('#level-dial');if(dial)dial.focus();return;}
    if(['map-search','library-search'].includes(event.target.id)){
      const id=event.target.id, pos=event.target.selectionStart;
      state.query=event.target.value;render();const next=$('#'+id);next.focus();next.setSelectionRange(pos,pos);
    }
  });
  document.addEventListener('change',event=>{if(event.target.id==='lens'){state.lens=event.target.value;render();}});
  $('#close-resource').addEventListener('click',()=>$('#resource-dialog').close());
  $('#resource-dialog').addEventListener('close',()=>$('#resource-frame').removeAttribute('src'));
  window.addEventListener('hashchange',()=>{render();afterRender();});
  render();
  afterRender();
})();
