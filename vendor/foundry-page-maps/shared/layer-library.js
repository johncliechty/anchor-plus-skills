/* Shared Foundry layered-library component (Refinement 2).
   The Library is the knowledge map itself: the reader descends layer by layer
   with a level dial, sees the four kinds of material summarized at every level,
   and meets resource tiles only at the leaf they chose. Pure string renderer —
   no DOM, no fetch — usable from any skill bundle page and from node tests. */
(function (root) {
  'use strict';
  const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const KINDS = ['Reusable material', 'References', 'Tools', 'Other skills'];
  const KIND_LABELS = {'Other skills': 'Skills'};

  function buildLayers(knowledge, resources) {
    const byId = new Map(knowledge.nodes.map(n => [n.id, n]));
    const children = new Map(knowledge.nodes.map(n => [n.id, []]));
    let rootNode = null;
    for (const n of knowledge.nodes) {
      if (n.parent_id === null) rootNode = n;
      else children.get(n.parent_id).push(n);
    }
    if (!rootNode) throw new Error('The layered library needs one declared root');
    const maxDepth = Math.max(...knowledge.nodes.map(n => n.ring));
    const pathTo = id => {
      const path = [];
      for (let n = byId.get(id); n; n = byId.get(n.parent_id)) path.unshift(n.id);
      return path;
    };
    return {root: rootNode, byId, childrenOf: id => children.get(id) || [], pathTo, maxDepth,
            resourceOf: id => resources.find(r => r.id === byId.get(id).resource_id)};
  }

  function summaryLine(node) {
    // All four kinds, always — an explicit zero is information, not clutter.
    const parts = KINDS.map(k => `${esc(KIND_LABELS[k] || k)} ${node.catalog[k] || 0}`);
    return `<span class="ll-kinds">${parts.join(' · ')}</span>`;
  }

  function renderLayerLibrary(data, state, opts) {
    const layers = buildLayers(data.knowledge, data.resources);
    const resourceLink = opts.resourceLink;
    const path = state.path && state.path.length ? state.path : [layers.root.id];
    const current = layers.byId.get(path[path.length - 1]);
    const kids = layers.childrenOf(current.id);
    const level = current.ring;

    const crumbs = path.map((id, i) => {
      const n = layers.byId.get(id);
      const last = i === path.length - 1;
      return last ? `<strong>${esc(n.title)}</strong>`
        : `<a href="#library" data-layer-jump="${i}">${esc(n.title)}</a>`;
    }).join('<span class="ll-sep">›</span>');

    const dial = `<div class="ll-dial"><label for="level-dial">Level dial</label>`
      + `<input id="level-dial" type="range" min="0" max="${layers.maxDepth}" step="1" value="${level}"`
      + ` aria-valuetext="Level ${level} of ${layers.maxDepth}: ${esc(current.title)}">`
      + `<output>Level ${level} of ${layers.maxDepth}</output>`
      + `<span class="note">Slide shallower to climb back; descend by choosing a branch${kids.length === 1 ? ' (or slide deeper)' : ''}.</span></div>`;

    let body;
    const query = (state.query || '').trim().toLowerCase();
    if (query) {
      const hits = data.resources
        .filter(r => [r.title, r.summary, r.category, r.id].join(' ').toLowerCase().includes(query))
        .map(r => data.knowledge.nodes.find(n => n.resource_id === r.id))
        .filter(Boolean);
      body = `<p class="count" aria-live="polite">${hits.length} matching leaves. Each result shows its full layer path.</p>`
        + '<ul class="ll-results">' + hits.map(n => {
          const trail = layers.pathTo(n.id).map(id => esc(layers.byId.get(id).title)).join(' › ');
          return `<li><a href="#library" data-layer-node="${esc(n.id)}">${trail}</a></li>`;
        }).join('') + '</ul>';
    } else {
      const own = resourceLink(current.resource_id, null, 'button secondary');
      const branches = kids.map(k =>
        `<a href="#library" class="ll-branch" data-layer-node="${esc(k.id)}">`
        + `<strong>${esc(k.title)}</strong>`
        + `<span class="ll-roll">${k.catalog_total} item${k.catalog_total === 1 ? '' : 's'} below · ${summaryLine(k)}</span>`
        + `<span class="ll-go">Descend to level ${k.ring} →</span></a>`).join('');
      if (kids.length) {
        body = `<div class="ll-summary"><p>This layer holds <strong>${current.catalog_total}</strong> cataloged items. ${summaryLine(current)}</p>`
          + `<p class="note">Catalog counts from the map — not use frequency, which stays unknown until runs name resource ids.</p></div>`
          + `<div class="ll-branches">${branches}</div>`
          + `<div class="ll-own"><h3>The material at this level</h3><p class="note">One summary card per level; full tiles wait at the leaves.</p>${own}</div>`;
      } else {
        const r = layers.resourceOf(current.id);
        body = `<p class="count">Leaf reached. ${summaryLine(current)}</p><div class="card-grid">`
          + `<article class="card"><p class="eyebrow">${esc(r.category)}</p><h3>${esc(r.title)}</h3><p>${esc(r.summary)}</p>`
          + `<p class="count">Use frequency unknown — no run has named this resource id</p>`
          + resourceLink(r.id, 'Open resource →') + '</article></div>';
      }
    }

    return `${style}<div class="ll-crumbs" aria-label="Layer path">${crumbs}</div>${dial}${body}`;
  }

  const style = `<style data-foundry-layers>
.ll-crumbs{font-size:14px;margin:4px 0 10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ll-sep{color:#5d6778;margin:0 2px}
.ll-dial{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:#161b26;border:1px solid #2b3240;border-radius:10px;padding:10px 14px;margin-bottom:16px}
.ll-dial label{font-size:13px}
.ll-dial input{accent-color:#9ec0ff;width:200px;max-width:60vw}
.ll-dial output{font-size:13px;color:#efe6d6;min-width:84px}
.ll-dial .note{flex-basis:100%;margin:0}
.ll-summary p{margin:0 0 6px}
.ll-branches{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}
.ll-branch{display:block;border:1px solid #303643;border-radius:10px;background:#1a1d27;padding:14px;text-decoration:none;color:#e2e4e9}
.ll-branch:hover,.ll-branch:focus{border-color:#9ec0ff}
.ll-branch strong{display:block;margin-bottom:6px;color:#efe6d6}
.ll-roll{display:block;font-size:12px;color:#a4acba}
.ll-kinds{color:#a4acba}
.ll-go{display:block;margin-top:9px;font-size:12px;color:#9ec0ff}
.ll-own{margin-top:18px}
.ll-results{list-style:none;padding:0}
.ll-results li{border-bottom:1px solid #303643;padding:8px 0;font-size:13px}
@media(max-width:700px){.ll-branches{grid-template-columns:1fr}.ll-dial input{width:130px}}
</style>`;

  root.FoundryLayerLibrary = {buildLayers, renderLayerLibrary, KINDS};
})(globalThis);
