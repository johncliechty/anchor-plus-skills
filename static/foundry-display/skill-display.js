/* Anchor Foundry skill-display orchestrator (researchPrime Refinement 2 integration).
   Faithful port of the verified bundle page script from the "Foundry page and
   knowledge maps" handoff (foundry-skill-display/v1): the same canonical
   components (adapter.js, flow-diagram.js, layer-library.js — vendored
   byte-identical in this folder), the same tabs, level dial, flow diagram,
   reconciliation records and review record. Anchor supplies what the isolated
   bundle page could not: window.FOUNDRY_SKILL_DISPLAY carries the raw maps.json,
   server-resolved resource/anchor hrefs (the existing /artifact and
   /foundry/source routes — never an arbitrary filesystem path), the CURRENT
   primary settings (an existing invalid primary refuses and never falls back),
   and the Anchor-owned walkthrough-rail identity (persona names, icons, links
   to the other skills' existing pages). */
(function () {
  'use strict';
  const api = globalThis.FoundryDisplay;
  const flow = globalThis.FoundryFlowDiagram;
  const layerLib = globalThis.FoundryLayerLibrary;
  const payload = globalThis.FOUNDRY_SKILL_DISPLAY;
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value).replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const resourceHrefs = (payload.hrefs && payload.hrefs.resources) || {};
  const anchorHrefs = (payload.hrefs && payload.hrefs.anchors) || {};

  function refuse(message) {
    const extra = payload.settings && payload.settings.error ? `<p>${esc(payload.settings.error)}</p>` : '';
    $('#panel').innerHTML = `<div class="card"><h2>Walkthrough refused</h2><p>${esc(message)}</p>${extra}`
      + `<p class="note">An existing invalid primary never falls back to a mirror. Repair the model settings (or the display data) and reload.</p></div>`;
  }

  let display, selectedSettings;
  try {
    selectedSettings = api.resolveDisplaySettings({primary: payload.settings.primary, mirror: payload.settings.mirror});
    display = api.createDisplay(payload.data, {
      selectedSettings,
      // The designed seam: an allowlisted resource id in, a host-verified route out.
      resolveTarget: ({resourceId}) => {
        const entry = resourceHrefs[resourceId];
        return entry ? (entry.href || entry.sourceHref || null) : null;
      },
    });
  } catch (err) {
    refuse(err && err.message ? err.message : String(err));
    return;
  }

  const D = display.data;
  const resources = new Map(D.resources.map(r => [r.id, r]));
  const steps = new Map(D.process.steps.map(s => [s.id, s]));
  const anchors = new Map(D.anchors.map(a => [a.id, a]));
  const sources = new Map(D.sources.map(s => [s.id, s]));
  const nodes = D.knowledge.nodes;
  const positions = api.seededPositions(nodes);
  const layers = layerLib.buildLayers(D.knowledge, D.resources);
  const entryStep = steps.has(D.process.entry) ? D.process.entry : D.process.steps[0].id;
  const state = {knowledgeView: matchMedia('(max-width:700px)').matches ? 'outline' : 'disk', query: '', focus: null,
                 selected: null, lens: 'all', libPath: [layers.root.id], processView: 'diagram'};

  // Compact-list grouping comes from the DECLARED diagram bands (the bundle
  // page hardcoded researchPrime's groups; the declared layout carries them).
  const diagram = D.process.diagram;
  const groups = (function () {
    const bands = diagram.bands || [];
    const inRows = (a, b) => D.process.steps
      .filter(s => {const p = diagram.nodes[s.id]; return p && p.row >= a && p.row <= b;})
      .sort((x, y) => {const px = diagram.nodes[x.id], py = diagram.nodes[y.id]; return px.row - py.row || px.col - py.col;})
      .map(s => s.id);
    if (!bands.length) return [['All steps', D.process.steps.map(s => s.id)]];
    return bands.map(b => [b.title, inRows(b.from_row, b.to_row)]);
  })();

  function resourceLink(id, title, cls = 'button secondary') {
    const target = display.resourceTarget(id);
    const label = esc(title || resources.get(id).title);
    if (!target) return `<span class="${cls}" aria-disabled="true">${label} · source unavailable</span>`;
    return `<a class="${cls}" data-resource="${esc(id)}" href="${esc(target)}">${label}</a>`;
  }
  function anchorLink(id) {
    const a = anchors.get(id), source = sources.get(a.source_id);
    const label = `${esc(source.id)} · ${esc(source.kind)} · L${a.start}–${a.end}`;
    const entry = anchorHrefs[id] || {};
    if (!entry.href) return `<span class="anchor-link">${label} · ${esc(entry.problem || 'source unavailable')}</span>`;
    return `<a class="anchor-link" data-source="${esc(id)}" href="${esc(entry.href)}">${label}${entry.problem ? ' · ' + esc(entry.problem) : ''}</a>`;
  }
  function route() {
    const [view, id] = location.hash.slice(1).split('/');
    return {view: ['knowledge', 'library', 'process', 'differences', 'review'].includes(view) ? view : 'knowledge',
            id: steps.has(id) ? id : entryStep};
  }
  function filteredNodes() {
    const ids = new Set(display.search(state.query).map(r => r.id));
    return nodes.filter(n => ids.has(n.resource_id) && (state.lens === 'all' || n.process_ids.length));
  }
  function knowledge() {
    const hits = filteredNodes(), hitIds = new Set(hits.map(n => n.id));
    const focus = state.focus ? positions.get(state.focus) : {x: 0, y: 0};
    const project = n => {const p = api.recenter(positions.get(n.id), focus); return {x: 300 + p.x * 270, y: 300 + p.y * 270};};
    let graphic;
    if (state.knowledgeView === 'disk') {
      graphic = '<svg class="disk" viewBox="0 0 600 600" role="group" aria-label="Seeded Poincaré knowledge disk">';
      graphic += '<circle class="boundary" cx="300" cy="300" r="276"/>';
      for (const r of [110, 198, 240]) graphic += `<circle class="ring" cx="300" cy="300" r="${r}"/>`;
      for (const n of nodes.filter(n => n.parent_id)) {
        const p = project(nodes.find(k => k.id === n.parent_id)), q = project(n);
        graphic += `<line class="edge" x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}"/>`;
      }
      for (const n of nodes) {
        const p = project(n), isRoot = n.parent_id === null, isDomain = n.ring === 1;
        const target = display.resourceTarget(n.resource_id);
        graphic += `<a href="${esc(target || '#knowledge')}" data-resource="${esc(n.resource_id)}" data-node="${esc(n.id)}" tabindex="0" aria-label="Open ${esc(n.title)}" class="${hitIds.has(n.id) ? '' : 'dim'}"><title>${esc(n.title)} · ${esc(resources.get(n.resource_id).title)}</title><circle cx="${p.x}" cy="${p.y}" r="${isRoot ? 18 : isDomain ? 13 : 10}" fill="transparent"/><circle class="dot ${isRoot ? 'root-dot' : isDomain ? 'domain-dot' : ''}" cx="${p.x}" cy="${p.y}" r="${isRoot ? 10 : isDomain ? 7 : 5}"/>${(isRoot || isDomain) && !state.focus ? `<text x="${p.x}" y="${p.y + 23}" text-anchor="middle">${esc(n.title)}</text>` : ''}</a>`;
      }
      graphic += '</svg>';
    } else {
      const branch = parent =>
        '<ul>' + nodes.filter(n => n.parent_id === parent).map(n => `<li>${resourceLink(n.resource_id, n.title, 'outline-link')}<small>Declared depth ${n.ring} · ${esc((n.facets || []).join(', '))}</small>${branch(n.id)}</li>`).join('') + '</ul>';
      graphic = '<div class="outline">' + branch(null) + '</div>';
    }
    const selected = nodes.find(n => n.id === state.selected);
    const selectedCard = selected ? `<div class="source-card"><h3>${esc(selected.title)}</h3><p>${esc(resources.get(selected.resource_id).summary)}</p>${resourceLink(selected.resource_id)}<p class="count">Process links: ${selected.process_ids.map(id => `<a href="#process/${id}">${esc(steps.get(id).title)}</a>`).join(' · ') || 'none claimed'}</p><button data-focus="${selected.id}">Focus this region</button></div>` : '';
    return `<h2>Knowledge map</h2><p>Start with the question at the center. Branch outward; every node opens a real Library resource — and the Library tab descends these same layers with a level dial.</p>
      <p class="badge">Seeded hierarchy · no learned coordinates · use frequency unknown</p>
      <div class="toolbar"><label for="map-search">Find knowledge</label><input id="map-search" type="search" placeholder="Search the map" value="${esc(state.query)}">
      <button data-view="disk" aria-pressed="${state.knowledgeView === 'disk'}">Disk</button><button data-view="outline" aria-pressed="${state.knowledgeView === 'outline'}">Outline</button>
      <button data-focus="">Reset center</button><select id="lens" aria-label="Knowledge lens"><option value="all">All sources</option><option value="process" ${state.lens === 'process' ? 'selected' : ''}>Used by process steps</option></select></div>
      <p class="count" aria-live="polite">${hits.length} of ${nodes.length} nodes match. ${state.focus ? 'Focused on ' + esc(nodes.find(n => n.id === state.focus).title) + '.' : ''}</p>
      <div class="map-wrap"><div class="map-board">${graphic}</div><aside class="map-side" aria-label="Map reading guide"><div><h3>Explore a branch</h3>
      ${nodes.filter(n => n.ring === 1).map(n => `<button class="button secondary" data-focus="${n.id}">${esc(n.title)}</button>`).join('')}</div>
      <div><h3>What position means</h3><p>Center = general; rim = specific. Positions come from the declared parent tree, projected into the disk. Refocusing changes the view.</p>
      <p>Importance, frequency and learning are unmeasured here. Instruction, code and reference facets remain separate.</p></div>${selectedCard}</aside></div>
      <p class="note" style="margin-top:16px">The outline uses the same resource ids. Search highlights the disk; the complete outline keeps the hierarchy visible. ${resources.has('map-concept') ? resourceLink('map-concept', 'Read the geometry qualifications', 'inline-link') : ''}</p>`;
  }
  function library() {
    return `<h2>Library — the knowledge map, layer by layer</h2>
      <p>The Library is grouped by the knowledge-map layers. Top level is the map itself; descend level by level with the dial or the branch cards. Every layer summarizes the four kinds of material below it — reusable material, references, tools and skills — and resource tiles appear only at the leaf you chose, so the layout holds at any catalog size.</p>
      <div class="toolbar"><label for="library-search">Find a resource</label><input id="library-search" type="search" placeholder="Search leaves across all layers" value="${esc(state.query)}"></div>
      ${layerLib.renderLayerLibrary(D, {path: state.libPath, query: state.query}, {resourceLink})}
      <p class="note" style="margin-top:14px">Catalog counts come from the declared map; use frequency stays unknown until a verified run names a resource id.</p>`;
  }
  function process(id) {
    const s = steps.get(id), outgoing = D.process.edges.filter(e => e.source === id), incoming = D.process.edges.filter(e => e.target === id);
    const swarm = s.swarm && s.swarm.enabled ? `<p><strong>Swarm:</strong> ${s.swarm.bounded ? `${s.swarm.count} roster seats; at most ${s.swarm.concurrency_cap} simultaneous logical roster jobs. ${esc(s.swarm.limitation)}` : esc(s.swarm.limitation)} ${esc(s.swarm.knob || '')}</p>` : '';
    const reconcileItems = (D.process.disagreements || []).filter(d => (d.step_ids || []).includes(id));
    // Each disagreement's anchor pair sits OUTSIDE its collapsed record: the
    // anchors are clickable as soon as the step record is expanded, without
    // first opening the difference prose.
    const reconcile = reconcileItems.length ? `<div class="reconcile-node"><h3>Instructions ≠ code on this node</h3>${reconcileItems.map(d => `<div class="anchor-list">${anchorLink(d.instruction_anchor)}${anchorLink(d.code_anchor)}</div><details class="difference"><summary>${esc(d.title)}</summary><p><strong>Instruction says:</strong> ${esc(d.instruction_says)}</p><p><strong>Code does:</strong> ${esc(d.code_does)}</p><p><strong>A run follows:</strong> ${esc(d.follows)}</p><p class="note"><a href="#differences">Open the full reconciliation record →</a></p></details>`).join('')}</div>` : '';
    const graphic = state.processView === 'diagram'
      ? flow.style + `<div class="diagram-scroll">${flow.renderFlowDiagram(D.process, {selected: id})}</div>`
      : groups.map(([title, ids]) => `<section class="process-group"><h3>${esc(title)}</h3><div class="flow">${ids.map(sid => {const n = steps.get(sid), next = D.process.edges.filter(e => e.source === sid); return `<a class="step ${n.kind}" href="#process/${sid}" data-step="${sid}" ${sid === id ? 'aria-current="step"' : ''}><span class="type">${esc(flow.TYPES[n.display_type] || n.display_type)}</span><strong>${esc(n.title)}</strong><span class="next">${next.length ? '→ ' + next.map(e => esc(steps.get(e.target).title)).join(' / ') : 'End with recorded reason'}</span></a>`;}).join('')}</div></section>`).join('');
    return `<h2>Process map</h2><p class="note">Click a node to select it; its full record waits right below the drawing and expands only when you open it. Nodes marked ≠ carry a documented instruction/code disagreement. The declared entry is <strong>${esc(steps.get(entryStep).title)}</strong>.</p>
      ${graphic}
      <details class="detail" id="step-detail" data-step-id="${s.id}"><summary><span class="eyebrow">${esc(flow.TYPES[s.display_type] || s.display_type)}${s.role ? ' · ' + esc(s.role) : ''}</span><strong>${esc(s.title)}</strong><span class="note">Expand the full record — summary, source anchors and branches</span></summary>
      <p style="margin-top:14px">${esc(s.summary)}</p>
      <p class="note">${s.code_status === 'anchored' ? 'Actual code anchor available' : 'Instructions only; no program implementation claimed'}. ${s.instruction_status === 'anchored' ? 'Instruction anchor available.' : 'No separate instruction anchor.'}</p>${swarm}
      <div class="anchor-list">${s.anchors.map(anchorLink).join('')}</div><div class="actions">${s.resource_ids.map(rid => resourceLink(rid)).join('')}</div>
      ${reconcile}
      <h3 style="margin-top:18px">Next branches</h3><ul class="transitions">${outgoing.map(e => `<li><a href="#process/${e.target}">${esc(steps.get(e.target).title)}</a> — ${esc(e.label)} · ${anchorLink(e.anchor_id)}</li>`).join('') || '<li>This route ends with its recorded reason.</li>'}</ul>
      <details><summary>Arrives from ${incoming.length} branch${incoming.length === 1 ? '' : 'es'}</summary><ul class="transitions">${incoming.map(e => `<li><a href="#process/${e.source}">${esc(steps.get(e.source).title)}</a> — ${esc(e.label)}</li>`).join('')}</ul></details></details>
      ${state.processView === 'diagram' ? flow.legend() : ''}
      <div class="toolbar"><button data-process-view="diagram" aria-pressed="${state.processView === 'diagram'}">Flow diagram</button><button data-process-view="list" aria-pressed="${state.processView === 'list'}">Compact list</button></div>
      <p class="note">${D.process.steps.length} source-backed steps · ${D.process.edges.length} transitions.${resources.has('thresholds') ? ' ' + resourceLink('thresholds', 'Open the default stopping thresholds', 'inline-link') : ''}</p>`;
  }
  function differences() {
    return `<h2>Instructions ↔ code — the reconciliation record</h2><p>The saved instructions describe intended behavior; the code anchors show what the validation programs actually do. Each disagreement records what the instruction says, what the code does, and which one a run actually follows — with a source anchor on both sides. This effort documents and proposes; John decides. No skill source was edited.</p>
      <p class="count">${(D.process.disagreements || []).length} reconciliation items · each is badged ≠ on its process-map nodes</p>
      ${(D.process.disagreements || []).map(d => `<details class="difference" data-difference="${d.id}"><summary>${esc(d.title)}</summary><p>${esc(d.fact)}</p>
      <div class="reconcile-grid"><div><h4>What the instruction says</h4><p>${esc(d.instruction_says)}</p>${anchorLink(d.instruction_anchor)}</div>
      <div><h4>What the code does</h4><p>${esc(d.code_does)}</p>${anchorLink(d.code_anchor)}</div>
      <div><h4>Which one a run follows</h4><p>${esc(d.follows)}</p></div></div>
      <p class="count">On the map: ${(d.step_ids || []).map(id => `<a href="#process/${id}">${esc(steps.get(id).title)}</a>`).join(' · ') || '—'}</p>
      <div class="anchor-list">${d.anchors.map(anchorLink).join('')}</div>${d.anchors.map(id => {const a = anchors.get(id); return `<details><summary>${esc(a.source_id)} · lines ${a.start}–${a.end}</summary><pre class="excerpt">${esc(a.quote)}</pre></details>`;}).join('')}</details>`).join('')}`;
  }
  function review() {
    const life = D.lifecycle || {};
    return `<h2>Review record</h2><p>Cumulative human feedback on this product. Each refinement preserves the one before it; John's feedback is what moves the iteration forward.</p>
      <p class="badge">Lifecycle: ${esc(life.state || 'unknown')} · accepted: ${life.accepted === true} · closed: ${life.closed === true}</p>
      ${((D.review && D.review.cumulative) || []).map(r => `<article class="card review-entry" data-review="${r.refinement}"><p class="eyebrow">Refinement ${r.refinement} · reviewed ${esc(r.reviewed)} by ${esc(r.reviewer)}</p>
      <h3>Grade: ${esc(r.grade)}</h3><blockquote class="verdict">${esc(r.verdict)}</blockquote>
      <h4>The points</h4><ol class="review-points">${(r.points || []).map(p => `<li>${esc(p)}</li>`).join('')}</ol>
      ${r.response ? `<h4>What the next refinement changed</h4><p>${esc(r.response)}</p>` : ''}</article>`).join('')}
      <p class="note">This record implies no acceptance and closes nothing; those calls are John's.</p>`;
  }
  function render() {
    const current = route();
    document.querySelectorAll('[data-tab]').forEach(a => {if (a.dataset.tab === current.view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');});
    $('#panel').innerHTML = {knowledge, library, process: () => process(current.id), differences, review}[current.view]();
  }
  function revealSelected(id) {
    // The drawing itself stays in the viewport on Process opening and node
    // selection: pan inside the scroll box to center the selected node, then
    // bring the box — never the step record — to the top of the window.
    const box = $('.diagram-scroll');
    if (!box) return;
    const node = box.querySelector('[data-step="' + id + '"]');
    if (node) {
      const b = box.getBoundingClientRect(), n = node.getBoundingClientRect();
      box.scrollLeft += (n.left + n.width / 2) - (b.left + b.width / 2);
      box.scrollTop += (n.top + n.height / 2) - (b.top + b.height / 2);
    }
    box.scrollIntoView({block: 'start'});
  }
  function afterRender() {
    const current = route();
    if (current.view === 'process') revealSelected(current.id);
  }
  // Contained documents (2026-10-07): the dialog iframe is SANDBOXED with no
  // scripts (an opened document's own scripts never run) and no top
  // navigation (it can never replace this live page with the standalone
  // bundle preview). allow-same-origin exists solely so THIS page can reach
  // into the frame: on every frame load, serveTopNav is attached to the
  // framed document, and the registered documents' real `target="_top"`
  // returns (`../index.html#library`, deep links like
  // `../index.html#process/entry`) are served HERE — close the dialog and
  // route the live page to the same hash. Any other top-navigation attempt
  // stays contained; source controls are unchanged.
  function containDocument(text, target) {
    const doc = String(text);
    const base = '<base href="' + esc(new URL(target, location.href).href) + '">';
    const head = doc.match(/<head[^>]*>/i);
    return head ? doc.replace(head[0], head[0] + base) : base + doc;
  }
  function openSource(target, title) {
    const frame = $('#resource-frame');
    $('#resource-title').textContent = title;
    frame.removeAttribute('srcdoc');
    frame.removeAttribute('src');
    if (/^\/artifact\//.test(String(target))) {
      fetch(target, {credentials: 'same-origin'})
        .then(r => r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status)))
        .then(text => {frame.srcdoc = containDocument(text, target);})
        .catch(() => {frame.src = target;});   // sandbox still blocks any escape
    } else if (/^\/foundry\/source\?/.test(String(target))) {
      // THIS frame is sandboxed with no scripts, so ask the viewer for its
      // script-free embed variant (no blocked-inline-script console error);
      // the host load handler below scrolls the cited line. The new-tab link
      // keeps the plain URL, whose own scroll script runs top-level.
      frame.src = target + '&embed=1';
    } else {
      frame.src = target;
    }
    $('#resource-new-tab').href = target;
    $('#resource-dialog').showModal();
  }
  function serveTopNav(event) {
    const a = event.target && event.target.closest ? event.target.closest('a[target="_top"]') : null;
    if (!a) return;
    event.preventDefault();
    event.stopPropagation();
    let url;
    try {url = new URL(String(a.href || ''), location.href);} catch (err) {return;}
    if (url.origin !== location.origin || !/\/index\.html$/.test(url.pathname)) return;
    $('#resource-dialog').close();
    const hash = url.hash || '#library';
    if (location.hash !== hash) location.hash = hash;
    render();
    afterRender();
  }
  $('#resource-frame').addEventListener('load', () => {
    // Same-origin srcdoc/src loads expose their document; an opaque (CSP-
    // sandboxed) load yields null and simply stays contained.
    const frame = $('#resource-frame');
    const doc = frame.contentDocument;
    if (!doc) return;
    doc.addEventListener('click', serveTopNav, true);
    // The sandbox has no allow-scripts, so the source viewer's own
    // scrollIntoView never runs inside the frame. For a /foundry/source load
    // the HOST brings the server-validated anchored line (the #L<n> the
    // viewer marked .hit) into view instead — containment unchanged.
    if (/^\/foundry\/source\?/.test(frame.getAttribute('src') || '')) {
      const hit = doc.querySelector('pre span.hit');
      if (hit) hit.scrollIntoView({block: 'center'});
    }
  });
  function dialTo(level) {
    let path = [...state.libPath];
    let currentLevel = layers.byId.get(path[path.length - 1]).ring;
    if (level < currentLevel) path = path.slice(0, level + 1);
    else while (currentLevel < level) {
      const kids = layers.childrenOf(path[path.length - 1]);
      if (kids.length !== 1) break;
      path.push(kids[0].id);
      currentLevel++;
    }
    state.libPath = path;
  }
  // The walkthrough rail keeps the canonical order and persona gating from the
  // adapter; identity (names, icons, links to the other skills' existing
  // Anchor pages) is Anchor-owned and injected by the server.
  const rail = payload.rail || {};
  $('#walkthrough').innerHTML = api.walkthrough(selectedSettings, payload.persona).map((w, i) => {
    const own = rail[w.id] || {};
    const img = own.icon ? `<img src="${esc(own.icon)}" alt="" width="48" height="48">` : '<span class="placeholder">…</span>';
    const body = `${img}<span><strong>${i + 1}. ${esc(w.title)}</strong><small>${own.current ? 'This walkthrough — for review' : own.href ? 'Open its current walkthrough' : 'Later walkthrough · not built here'}</small></span>`;
    return own.href && !own.current ? `<a class="walk" href="${esc(own.href)}">${body}</a>`
      : `<${own.current ? 'a' : 'div'} class="walk"${own.current ? ' href="#knowledge" aria-current="page"' : ''}>${body}</${own.current ? 'a' : 'div'}>`;
  }).join('');
  document.addEventListener('click', event => {
    const tab = event.target.closest('[data-tab]');
    if (tab && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      // Switching tabs must repaint before this click returns: the browser fires
      // hashchange in a later task, and the phone proof reads #panel immediately.
      event.preventDefault();
      if (location.hash !== tab.getAttribute('href')) location.hash = tab.getAttribute('href');
      render();
      afterRender();
      return;
    }
    const layerNode = event.target.closest('[data-layer-node]');
    if (layerNode) {event.preventDefault(); state.libPath = layers.pathTo(layerNode.dataset.layerNode); state.query = ''; render(); return;}
    const layerJump = event.target.closest('[data-layer-jump]');
    if (layerJump) {event.preventDefault(); state.libPath = state.libPath.slice(0, Number(layerJump.dataset.layerJump) + 1); render(); return;}
    const r = event.target.closest('[data-resource]');
    if (r && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      event.preventDefault();
      const id = r.dataset.resource;
      if (r.dataset.node) {state.selected = r.dataset.node; render();}
      const target = display.resourceTarget(id);
      if (target) openSource(target, resources.get(id).title);
      return;
    }
    const a = event.target.closest('[data-source]');
    if (a && !event.ctrlKey && !event.metaKey && !event.shiftKey) {event.preventDefault(); openSource(a.getAttribute('href'), 'Source · ' + anchors.get(a.dataset.source).source_id); return;}
    const view = event.target.closest('[data-view]');
    if (view) {state.knowledgeView = view.dataset.view; render(); return;}
    const pview = event.target.closest('[data-process-view]');
    if (pview) {state.processView = pview.dataset.processView; render(); afterRender(); return;}
    const focus = event.target.closest('[data-focus]');
    if (focus) {state.focus = focus.dataset.focus || null; render(); return;}
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'level-dial') {dialTo(Number(event.target.value)); render(); const dial = $('#level-dial'); if (dial) dial.focus(); return;}
    if (['map-search', 'library-search'].includes(event.target.id)) {
      const id = event.target.id, pos = event.target.selectionStart;
      state.query = event.target.value; render(); const next = $('#' + id); next.focus(); next.setSelectionRange(pos, pos);
    }
  });
  document.addEventListener('change', event => {if (event.target.id === 'lens') {state.lens = event.target.value; render();}});
  $('#close-resource').addEventListener('click', () => $('#resource-dialog').close());
  $('#resource-dialog').addEventListener('close', () => {
    $('#resource-frame').removeAttribute('src');
    $('#resource-frame').removeAttribute('srcdoc');
  });
  window.addEventListener('hashchange', () => {render(); afterRender();});
  render();
  afterRender();
})();
