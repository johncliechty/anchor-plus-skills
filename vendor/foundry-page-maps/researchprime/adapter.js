/* Pure Foundry display seam. No filesystem, network, model, or campaign writes. */
(function (root) {
  'use strict';
  const families = new Set(['claude', 'gemini', 'grok', 'chatgpt']);
  const safePath = path => typeof path === 'string' && /^[a-zA-Z0-9_./-]+$/.test(path)
    && !path.startsWith('/') && !path.split('/').includes('..');
  function settings(value) {
    if (!value || !families.has(value.coding_family) || !families.has(value.review_family)
        || !families.has(value.default_cli) || !['aladdin', 'jarvis'].includes(value.steward_type)
        || value.model_policy?.mode !== 'latest_supported' || value.model_policy?.effort !== 'highest_supported'
        || !Number.isInteger(value.settings_revision) || value.settings_revision < 0) {
      throw new Error('Selected display settings are invalid; an invalid primary cannot fall back.');
    }
    return structuredClone(value);
  }
  function resolveDisplaySettings({primary, mirror}) {
    if (primary?.exists) return {...settings(primary.value), source: 'primary'};
    return {...settings(mirror), source: 'mirror'};
  }
  function unique(items, label) {
    const result = new Map(items.map(x => [x.id, x]));
    if (result.size !== items.length) throw new Error('Duplicate ' + label);
    return result;
  }
  function createDisplay(input, {selectedSettings, resolveTarget} = {}) {
    const data = structuredClone(input);
    if (data.schema !== 'foundry-skill-display/v1') throw new Error('Unsupported display schema');
    data.settings = settings(selectedSettings || data.settings);
    const resources = unique(data.resources, 'resource');
    const anchors = unique(data.anchors, 'anchor');
    const sources = unique(data.sources, 'source');
    const steps = unique(data.process.steps, 'step');
    const nodes = unique(data.knowledge.nodes, 'node');
    for (const a of anchors.values()) {
      if (!sources.has(a.source_id) || !Number.isInteger(a.start) || a.start < 1 || a.end < a.start
          || !a.quote || !/^[a-f0-9]{64}$/.test(a.sha256)) throw new Error('Invalid source anchor ' + a.id);
    }
    for (const r of resources.values()) {
      if (!anchors.has(r.anchor_id) || !safePath(r.target)) throw new Error('Invalid resource target ' + r.id);
      // Dataset use labels must be evidence-free until verified receipts are bound separately.
      if (r.usage.status !== 'unknown' || r.usage.count !== null || r.usage.run_ids.length || r.usage.method !== null) {
        throw new Error('Unverified frequency in dataset ' + r.id);
      }
    }
    if (data.knowledge.learned || data.knowledge.geometry !== 'seeded-declared-tree' || data.knowledge.run_evidence.length) {
      throw new Error('This adapter accepts a declared seed, not an unverified learned map.');
    }
    for (const n of nodes.values()) {
      if (!resources.has(n.resource_id) || (n.parent_id && !nodes.has(n.parent_id))
          || n.process_ids.some(id => !steps.has(id))) throw new Error('Invalid knowledge link ' + n.id);
      const seen = new Set([n.id]);
      let parent = n.parent_id;
      while (parent) {
        if (seen.has(parent)) throw new Error('Cyclic knowledge hierarchy');
        seen.add(parent);
        parent = nodes.get(parent).parent_id;
      }
    }
    for (const s of steps.values()) {
      if (!s.anchors.length || s.anchors.some(id => !anchors.has(id)) || s.resource_ids.some(id => !resources.has(id))) {
        throw new Error('Invalid process link ' + s.id);
      }
    }
    for (const e of data.process.edges) {
      if (!steps.has(e.source) || !steps.has(e.target) || !anchors.has(e.anchor_id)) throw new Error('Invalid process edge');
    }
    function resource(id) {
      if (!resources.has(id)) throw new Error('Unknown resource id: ' + id);
      return structuredClone(resources.get(id));
    }
    function resourceTarget(id) {
      const r = resource(id);
      const a = anchors.get(r.anchor_id);
      // The host receives an allowlisted resource and source identity, not an arbitrary disk path.
      return resolveTarget ? resolveTarget({resourceId: id, target: r.target, sourceId: a.source_id,
        start: a.start, end: a.end, sourceHash: sources.get(a.source_id).sha256}) : r.target;
    }
    function search(query = '', category = '') {
      const q = query.toLowerCase().trim();
      return data.resources.filter(r => (!category || r.category === category)
        && [r.title, r.summary, r.category, r.id].join(' ').toLowerCase().includes(q)).map(r => structuredClone(r));
    }
    return {data, resource, resourceTarget, search};
  }
  function seededPositions(nodes) {
    const children = id => nodes.filter(n => n.parent_id === id);
    const roots = nodes.filter(n => n.parent_id === null);
    if (roots.length !== 1) throw new Error('A seed needs one declared root');
    const positions = new Map();
    function place(n, lo, hi, depth) {
      const theta = (lo + hi) / 2;
      const radius = Math.tanh(depth * .47);
      positions.set(n.id, {x: radius * Math.cos(theta), y: radius * Math.sin(theta), depth});
      const kids = children(n.id);
      kids.forEach((kid, i) => place(kid, lo + (hi-lo)*i/kids.length, lo + (hi-lo)*(i+1)/kids.length, depth+1));
    }
    place(roots[0], -Math.PI/2, 3*Math.PI/2, 0);
    if (positions.size !== nodes.length) throw new Error('Unreachable seed node');
    return positions;
  }
  function recenter(point, focus) {
    // Disk automorphism (z-a)/(1-conj(a)z); display projection, no learned coordinates.
    const nx = point.x-focus.x, ny = point.y-focus.y;
    const dx = 1-focus.x*point.x-focus.y*point.y, dy = focus.y*point.x-focus.x*point.y;
    const d = dx*dx+dy*dy;
    return {x: (nx*dx+ny*dy)/d, y: (ny*dx-nx*dy)/d};
  }
  function summarizeUse(resourceIds, receipts, verifyReceipt) {
    if (typeof verifyReceipt !== 'function') throw new Error('Recorded use requires a host receipt verifier');
    const counts = new Map(resourceIds.map(id => [id, new Set()]));
    const seen = new Map();
    for (const r of receipts) {
      if (!r.run_id || !Array.isArray(r.resource_ids) || !r.receipt_target || !/^[a-f0-9]{64}$/.test(r.sha256 || '')
          || r.resource_ids.some(id => !counts.has(id)) || verifyReceipt(r) !== true) throw new Error('Unverified resource use receipt');
      const key = JSON.stringify([...new Set(r.resource_ids)].sort());
      if (seen.has(r.run_id) && seen.get(r.run_id) !== key) throw new Error('Conflicting receipt for the same run');
      seen.set(r.run_id, key);
      for (const id of r.resource_ids) counts.get(id).add(r.run_id);
    }
    return Object.fromEntries([...counts].map(([id, ids]) => [id, {status: ids.size ? 'recorded' : 'unknown',
      count: ids.size || null, run_ids: [...ids].sort(), method: ids.size ? 'unique-explicit-resource-runs' : null}]));
  }
  function walkthrough(selected, personaPresentation) {
    const s = settings(selected);
    // Other selected personas supply their names/icons from Anchor rather than borrowing Aladdin's.
    const persona = s.steward_type === 'aladdin' ? {
      lamp: {title: 'Steward · the Lamp', icon: 'assets/steward-lamp.jpg'},
      cave: {title: 'Steward · the Cave of Wonders', icon: 'assets/steward-cave.jpg'},
      star: {title: 'Steward · Star Chart', icon: 'assets/ecgberht-portfolio.png'},
    } : personaPresentation;
    if (!persona?.lamp || !persona?.cave || !persona?.star) throw new Error('Selected persona needs Anchor names and icons');
    return [
      {id: 'researchprime', title: 'researchPrime', icon: 'assets/researchprime.jpg', available: true},
      {id: 'gandalf', title: 'Gandalf', icon: 'assets/gandalf.jpg'},
      {id: 'steward-lamp', ...persona.lamp}, {id: 'steward-cave', ...persona.cave},
      {id: 'steward-star-chart', ...persona.star}, {id: 'remaining-skills', title: 'Remaining skills'},
    ];
  }
  root.FoundryDisplay = {createDisplay, resolveDisplaySettings, seededPositions, recenter, summarizeUse, walkthrough};
})(globalThis);
