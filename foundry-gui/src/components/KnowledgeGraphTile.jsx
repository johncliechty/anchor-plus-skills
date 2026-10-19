import React, { useState, useEffect, useRef, useMemo } from 'react';
import * as d3 from 'd3';

// ---------------------------------------------------------------------------
// Icon logic — replicated from App.jsx (same map + same fallback) so the graph
// nodes carry the identical brand icons as the skill list.
// ---------------------------------------------------------------------------
const SKILL_ICONS = {
  'literature review': '/brand/literature-review-icon.jpg',
  'jumper': '/brand/jumper-icon.jpg',
  'gandalf': '/brand/gandalf-icon-v5.jpg',
  'legal beagle': '/brand/legal-beagle-icon.jpg',
  'crucible': '/brand/crucible-icon.svg',
  'foreman': '/brand/foreman-icon.svg',
  'ramanujan': '/brand/ramanujan-icon.jpg',
  'financial analyst': '/brand/financial-analyst-icon.jpg',
  'financial-analyst': '/brand/financial-analyst-icon.jpg',
  'legal-beagle': '/brand/legal-beagle-icon.jpg',
  'literature-review': '/brand/literature-review-icon.jpg',
  'researchprime': '/brand/research-prime-icon.jpg',
  'research prime': '/brand/research-prime-icon.jpg',
  'research-prime': '/brand/research-prime-icon.jpg',
  'curriculum dev': '/brand/skill-foundry-icon.jpg',
  'tidy idy': '/brand/tidy-idy-icon.jpg',
  'tidy-idy': '/brand/tidy-idy-icon.jpg',
  'zombie hunter': '/brand/zombie-hunter-radar.jpg',
  'zombie-hunter': '/brand/zombie-hunter-radar.jpg'
};

const getSkillIconUrl = (name) => {
  const normalized = (name || '').toLowerCase();
  for (const [key, iconPath] of Object.entries(SKILL_ICONS)) {
    if (normalized.includes(key)) return iconPath;
  }
  return '/brand/skill-foundry-icon.jpg';
};

// ---------------------------------------------------------------------------
// Real-data mappings
// ---------------------------------------------------------------------------
const EDGE_COLORS = {
  compose: '#00F0FF',   // cyan
  import: '#7c9cff',    // violet/blue
  augment: '#ffb020'    // amber
};

// Poincaré radius spread: r = tanh(depth * SPREAD) * R asymptotes to the rim.
const SPREAD = 0.7;

// Node ring color by status (checked most-specific first: "pre-alpha" must not
// match the "alpha" bucket).
const statusRingColor = (status) => {
  const s = (status || '').toLowerCase();
  if (s.includes('pre-alpha') || s.includes('planning')) return '#64748b'; // slate
  if (s.includes('production') || s.includes('stable')) return '#34d399';  // emerald
  if (s.includes('mature')) return '#00F0FF';                              // cyan
  if (s.includes('beta')) return '#fbbf24';                                // amber
  if (s.includes('alpha')) return '#fb923c';                               // orange
  return '#64748b';
};

// Canonical ref for a skill (real data carries `ref` like "skill:crucible";
// the offline SEED fallback lacks it, so derive deterministically from name).
const refOf = (skill) =>
  skill && (skill.ref || ('skill:' + (skill.name || '').toLowerCase().replace(/\s+/g, '-')));

// ---------------------------------------------------------------------------
// Deterministic Poincaré-disk layout over the REAL dependency graph.
// Nodes = skills. Edges = each skill's typed `edges` (A -> B means A depends
// on B, so B is more foundational and sits closer to the disk center).
// ---------------------------------------------------------------------------
function computeGraph(skills, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const R = Math.min(width, height) / 2 - 36;

  // -- nodes + resolved edges (only edges whose target exists; no self-loops)
  const nodeByRef = new Map();
  skills.forEach((s) => {
    const ref = refOf(s);
    if (ref && !nodeByRef.has(ref)) nodeByRef.set(ref, { ref, skill: s });
  });

  const edges = [];
  skills.forEach((s) => {
    const from = refOf(s);
    (s.edges || []).forEach((e) => {
      if (e && e.to && e.to !== from && nodeByRef.has(e.to)) {
        edges.push({ source: from, target: e.to, type: e.type || 'import', range: e.range });
      }
    });
  });

  const outAdj = new Map(); // ref -> [dependency refs]
  const inDeg = new Map();  // ref -> # of skills depending on it
  edges.forEach((e) => {
    if (!outAdj.has(e.source)) outAdj.set(e.source, []);
    outAdj.get(e.source).push(e.target);
    inDeg.set(e.target, (inDeg.get(e.target) || 0) + 1);
  });

  // -- depth = longest dependency chain down to a root (root = no outgoing
  //    deps). Memoized DFS with a visiting-set cycle guard: a back-edge in a
  //    cycle contributes depth 0 instead of recursing forever. Diamond/shared
  //    deps (researchPrime -> crucible -> foreman AND researchPrime -> foreman)
  //    are handled by the memo — each node gets ONE depth, placed once.
  const depthMemo = new Map();
  const visiting = new Set();
  const depthOf = (ref) => {
    if (depthMemo.has(ref)) return depthMemo.get(ref);
    if (visiting.has(ref)) return 0; // cycle guard
    visiting.add(ref);
    let d = 0;
    (outAdj.get(ref) || []).forEach((dep) => {
      d = Math.max(d, depthOf(dep) + 1);
    });
    visiting.delete(ref);
    depthMemo.set(ref, d);
    return d;
  };

  const allRefs = Array.from(nodeByRef.keys()).sort();
  allRefs.forEach(depthOf);

  // -- partition: connected (participates in >=1 edge) vs independent
  const connected = allRefs.filter((r) => (outAdj.get(r) || []).length > 0 || (inDeg.get(r) || 0) > 0);
  const independents = allRefs.filter((r) => !((outAdj.get(r) || []).length > 0 || (inDeg.get(r) || 0) > 0));

  // -- layout tree over the connected component: each node's layout parent is
  //    its DEEPEST dependency (ties broken lexically), giving a spanning
  //    forest rooted at the depth-0 foundational skills.
  const parentOf = new Map();
  connected.forEach((r) => {
    const deps = (outAdj.get(r) || []).slice().sort();
    if (deps.length === 0) return; // root
    let best = deps[0];
    deps.forEach((d) => { if (depthOf(d) > depthOf(best)) best = d; });
    parentOf.set(r, best);
  });

  const childrenOf = new Map();
  connected.forEach((r) => {
    const p = parentOf.get(r);
    if (p !== undefined) {
      if (!childrenOf.has(p)) childrenOf.set(p, []);
      childrenOf.get(p).push(r);
    }
  });
  childrenOf.forEach((kids) => kids.sort());

  // subtree leaf-weight (for proportional angular wedges)
  const weightMemo = new Map();
  const weightOf = (ref) => {
    if (weightMemo.has(ref)) return weightMemo.get(ref);
    const kids = childrenOf.get(ref) || [];
    const w = kids.length === 0 ? 1 : kids.reduce((acc, k) => acc + weightOf(k), 0);
    weightMemo.set(ref, w);
    return w;
  };

  // -- angular sector division: roots split the full circle; each parent hands
  //    its children sub-wedges of its own wedge, proportional to subtree weight.
  const roots = connected.filter((r) => !parentOf.has(r)).sort();
  const multiRoot = roots.length > 1;
  const angleOf = new Map();

  const place = (ref, a0, a1) => {
    angleOf.set(ref, (a0 + a1) / 2);
    const kids = childrenOf.get(ref) || [];
    const total = kids.reduce((acc, k) => acc + weightOf(k), 0);
    let a = a0;
    kids.forEach((k) => {
      const span = total > 0 ? ((a1 - a0) * weightOf(k)) / total : 0;
      place(k, a, a + span);
      a += span;
    });
  };

  const rootTotal = roots.reduce((acc, r) => acc + weightOf(r), 0);
  let a = -Math.PI / 2; // start at 12 o'clock
  roots.forEach((r) => {
    const span = rootTotal > 0 ? (2 * Math.PI * weightOf(r)) / rootTotal : 0;
    place(r, a, a + span);
    a += span;
  });

  // -- radii: hyperbolic — depth 0 at/near center, each level asymptotes to
  //    the rim, never past it. With multiple roots, spread them on a small
  //    inner ring instead of stacking them all at r=0.
  const maxDepth = connected.reduce((m, r) => Math.max(m, depthOf(r)), 0);
  const radiusOf = (depth) => {
    if (depth === 0) return multiRoot ? 0.15 * R : 0;
    return Math.tanh(depth * SPREAD) * R;
  };

  const nodes = [];
  connected.forEach((r) => {
    const depth = depthOf(r);
    const ang = angleOf.get(r) ?? 0;
    const rr = radiusOf(depth);
    nodes.push(makeNode(nodeByRef.get(r), depth, inDeg.get(r) || 0, cx + rr * Math.cos(ang), cy + rr * Math.sin(ang), false));
  });

  // -- independent (edge-less) skills: their own evenly-spaced outer ring,
  //    one hyperbolic level beyond the deepest tree node — clearly not
  //    children of anything.
  const rIndep = Math.min(0.965 * R, Math.tanh((maxDepth + 1) * SPREAD) * R);
  independents.forEach((r, i) => {
    const ang = -Math.PI / 2 + Math.PI / Math.max(independents.length, 1) + (2 * Math.PI * i) / Math.max(independents.length, 1);
    nodes.push(makeNode(nodeByRef.get(r), maxDepth + 1, 0, cx + rIndep * Math.cos(ang), cy + rIndep * Math.sin(ang), true));
  });

  const nodeIndex = new Map(nodes.map((n) => [n.ref, n]));
  return { nodes, edges, nodeIndex, cx, cy, R, maxDepth };
}

function makeNode(entry, depth, inDegree, x, y, independent) {
  return {
    ref: entry.ref,
    skill: entry.skill,
    depth,
    inDegree,
    x,
    y,
    independent,
    // size by centrality: foundational (high in-degree) nodes are bigger
    r: 9 + Math.min(inDegree, 4) * 3.5
  };
}

// Quadratic curve whose control point is pulled toward the disk center — an
// approximation of the hyperbolic geodesic.
function geodesicPath(x1, y1, x2, y2, cx, cy) {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const qx = cx + (mx - cx) * 0.55;
  const qy = cy + (my - cy) * 0.55;
  return `M ${x1} ${y1} Q ${qx} ${qy} ${x2} ${y2}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function KnowledgeGraphTile({ selectedSkill, skills = [], onSelectSkill }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [activeModalNode, setActiveModalNode] = useState(null);
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const zoomRef = useRef(null);

  // Honest counts for the caption (nodes = real skills; edges = resolved typed
  // edges from the manifest).
  const { nodeCount, edgeCount } = useMemo(() => {
    const refs = new Set(skills.map(refOf));
    let m = 0;
    skills.forEach((s) => {
      const from = refOf(s);
      (s.edges || []).forEach((e) => {
        if (e && e.to && e.to !== from && refs.has(e.to)) m++;
      });
    });
    return { nodeCount: skills.length, edgeCount: m };
  }, [skills]);

  const resetZoom = () => {
    if (isExpanded && svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .duration(750)
        .call(zoomRef.current.transform, d3.zoomIdentity);
      setActiveModalNode(null);
    }
  };

  useEffect(() => {
    if (!isExpanded || !containerRef.current || skills.length === 0) return;

    // Clear previous render
    d3.select(containerRef.current).selectAll('*').remove();

    const width = containerRef.current.offsetWidth || 800;
    const height = 560;

    const { nodes, edges, nodeIndex, cx, cy, R } = computeGraph(skills, width, height);

    const selectedRef = selectedSkill ? refOf(selectedSkill) : null;
    const neighborRefs = new Set();
    if (selectedRef) {
      edges.forEach((e) => {
        if (e.source === selectedRef) neighborRefs.add(e.target);
        if (e.target === selectedRef) neighborRefs.add(e.source);
      });
    }
    const isFocused = (ref) => !selectedRef || ref === selectedRef || neighborRefs.has(ref);

    const svg = d3.select(containerRef.current)
      .append('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('viewBox', `0 0 ${width} ${height}`);
    svgRef.current = svg.node();

    const g = svg.append('g');

    // Glow filter (selected-node halo)
    const defs = svg.append('defs');
    const filter = defs.append('filter')
      .attr('id', 'kg-glow')
      .attr('x', '-60%').attr('y', '-60%')
      .attr('width', '220%').attr('height', '220%');
    filter.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'blur');
    const merge = filter.append('feMerge');
    merge.append('feMergeNode').attr('in', 'blur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Per-node circular clip paths for the icon images
    nodes.forEach((n, i) => {
      defs.append('clipPath')
        .attr('id', `kg-clip-${i}`)
        .append('circle')
        .attr('r', Math.max(n.r - 2.5, 3))
        .attr('cx', 0)
        .attr('cy', 0);
      n._clipId = `kg-clip-${i}`;
    });

    // Zoom / pan (kept from the previous implementation) + label reveal by depth
    const zoom = d3.zoom()
      .scaleExtent([0.4, 8])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
        const k = event.transform.k;
        g.selectAll('.node-label')
          .style('opacity', (d) => {
            if (k >= 2.2) return 1;
            if (k >= 1.4) return d.depth <= 2 ? 1 : 0.7;
            return d.depth <= 1 ? 0.9 : 0.45;
          });
      });
    zoomRef.current = zoom;
    svg.call(zoom);

    // Bounding Poincaré disk (subtle cyan boundary)
    g.append('circle')
      .attr('cx', cx).attr('cy', cy).attr('r', R)
      .attr('fill', 'rgba(0, 240, 255, 0.012)')
      .attr('stroke', 'rgba(0, 240, 255, 0.14)')
      .attr('stroke-width', 1);
    // faint inner reference ring at the first hyperbolic level
    g.append('circle')
      .attr('cx', cx).attr('cy', cy).attr('r', Math.tanh(SPREAD) * R)
      .attr('fill', 'none')
      .attr('stroke', 'rgba(0, 240, 255, 0.05)')
      .attr('stroke-dasharray', '2 6')
      .attr('stroke-width', 1);

    // Edges — geodesic-approximating arcs, colored by real edge type
    g.append('g')
      .selectAll('path')
      .data(edges)
      .join('path')
      .attr('d', (e) => {
        const s = nodeIndex.get(e.source);
        const t = nodeIndex.get(e.target);
        return geodesicPath(s.x, s.y, t.x, t.y, cx, cy);
      })
      .attr('fill', 'none')
      .attr('stroke', (e) => EDGE_COLORS[e.type] || EDGE_COLORS.import)
      .attr('stroke-width', (e) => (selectedRef && (e.source === selectedRef || e.target === selectedRef)) ? 1.8 : 1.1)
      .attr('opacity', (e) => {
        if (!selectedRef) return 0.4;
        return (e.source === selectedRef || e.target === selectedRef) ? 0.9 : 0.12;
      });

    // Nodes
    const nodeGroup = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node cursor-pointer')
      .attr('transform', (d) => `translate(${d.x},${d.y})`)
      .attr('opacity', (d) => (isFocused(d.ref) ? 1 : 0.28));

    // selected halo
    nodeGroup.filter((d) => d.ref === selectedRef)
      .append('circle')
      .attr('r', (d) => d.r + 5)
      .attr('fill', 'none')
      .attr('stroke', '#00F0FF')
      .attr('stroke-width', 2)
      .style('filter', 'url(#kg-glow)');

    // status ring + dark disc
    nodeGroup.append('circle')
      .attr('r', (d) => d.r)
      .attr('fill', '#0A0A0F')
      .attr('stroke', (d) => statusRingColor(d.skill.status))
      .attr('stroke-width', (d) => (d.ref === selectedRef ? 2.5 : 1.5));

    // skill icon (same brand assets as the skill list), circularly clipped
    nodeGroup.append('image')
      .attr('href', (d) => getSkillIconUrl(d.skill.name))
      .attr('x', (d) => -(d.r - 2.5))
      .attr('y', (d) => -(d.r - 2.5))
      .attr('width', (d) => 2 * (d.r - 2.5))
      .attr('height', (d) => 2 * (d.r - 2.5))
      .attr('clip-path', (d) => `url(#${d._clipId})`)
      .attr('preserveAspectRatio', 'xMidYMid slice');

    // labels beneath nodes — fade with depth, reveal on zoom (handler above)
    nodeGroup.append('text')
      .attr('class', 'node-label text-[10px] font-bold tracking-wide font-display select-none')
      .attr('fill', '#ffffff')
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => d.r + 13)
      .text((d) => d.skill.name)
      .style('opacity', (d) => (d.depth <= 1 ? 0.9 : 0.45));

    // Click: select the real skill in the app + zoom to it + open the detail modal
    nodeGroup.on('click', (event, d) => {
      event.stopPropagation();
      if (onSelectSkill) onSelectSkill(d.skill);
      svg.transition()
        .duration(650)
        .call(
          zoom.transform,
          d3.zoomIdentity.translate(width / 2, height / 2).scale(2.6).translate(-d.x, -d.y)
        )
        .on('end', () => setActiveModalNode(d));
    });

    nodeGroup.append('title').text((d) => `${d.skill.name} — ${d.skill.status || 'status unknown'}`);
  }, [skills, selectedSkill, isExpanded, onSelectSkill]);

  const modalSkill = activeModalNode ? activeModalNode.skill : null;

  return (
    <div className={`panel expandable-tile ${isExpanded ? 'expanded-huge' : ''} shrink-0 relative overflow-hidden transition-all duration-500`} id="tile-kg">
      {/* Tile Header */}
      <div
        className="p-6 flex justify-between items-center cursor-pointer hover:bg-[#0A0A0F]/80 transition-colors h-[80px]"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-[#00F0FF]">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94-3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-[#00F0FF] font-display">4. Knowledge Graph</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">Poincaré disk • skill dependency hierarchy • click a node to open it</p>
          </div>
        </div>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16161A] text-slate-400 hover:text-white transition-all duration-200"
          onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
          aria-label="Toggle Knowledge Graph"
        >
          <svg className={`w-4 h-4 chevron ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Expanded Poincaré view */}
      {isExpanded && (
        <div className="border-t border-[#16161A] relative bg-black">
          <div className="relative h-[560px]">
            {/* Zoom Controls */}
            <div className="absolute top-4 right-4 z-10 flex gap-2">
              <button
                onClick={resetZoom}
                className="bg-[#16161A] text-gray-400 hover:text-white p-2.5 rounded-lg border border-[#333]/40 hover:border-slate-600 transition-colors shadow-lg flex items-center justify-center"
                title="Reset Zoom"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                </svg>
              </button>
            </div>

            {/* Edge-type legend (real edge types from the manifest) */}
            <div className="absolute top-4 left-4 z-10 rounded-lg bg-black/70 border border-[#16161A] px-3 py-2 space-y-1 pointer-events-none">
              {Object.entries(EDGE_COLORS).map(([type, color]) => (
                <div key={type} className="flex items-center gap-2">
                  <span className="inline-block w-4 h-[2px] rounded" style={{ backgroundColor: color }} />
                  <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400">{type}</span>
                </div>
              ))}
            </div>

            {/* D3 canvas */}
            <div ref={containerRef} className="w-full h-full cursor-move" />

            {/* Detail modal — REAL skill fields only */}
            {activeModalNode && modalSkill && (
              <div className="absolute inset-0 bg-black/85 backdrop-blur-sm z-50 flex items-center justify-center p-6">
                <div className="w-full max-w-2xl bg-[#08080a] border border-[#16161A] rounded-2xl shadow-[0_0_80px_rgba(0,240,255,0.15)] overflow-hidden flex flex-col">
                  <div className="h-[2px] w-full bg-gradient-to-r from-transparent via-[#00F0FF] to-transparent" />

                  {/* Header */}
                  <div className="p-6 pb-4 border-b border-[#16161A] flex justify-between items-start">
                    <div className="flex items-center gap-3">
                      <img src={getSkillIconUrl(modalSkill.name)} alt={modalSkill.name} className="w-10 h-10 rounded-lg border border-[#16161A] object-cover select-none" />
                      <div>
                        <div className="text-[9px] font-bold text-[#00F0FF] uppercase tracking-widest mb-1 font-mono">
                          {activeModalNode.ref}
                        </div>
                        <h4 className="text-2xl font-display font-bold text-white tracking-tight">{modalSkill.name}</h4>
                      </div>
                    </div>
                    <button
                      onClick={() => setActiveModalNode(null)}
                      className="text-slate-500 hover:text-white transition-colors h-8 w-8 flex items-center justify-center rounded-lg bg-slate-900 border border-slate-800"
                    >
                      ✕
                    </button>
                  </div>

                  {/* Content */}
                  <div className="p-6 overflow-y-auto max-h-[320px] space-y-4">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="p-3 rounded-xl bg-black border border-[#16161A]">
                        <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">Status</div>
                        <div className="text-xs text-white font-mono flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: statusRingColor(modalSkill.status) }} />
                          {modalSkill.status || '—'}
                        </div>
                      </div>
                      <div className="p-3 rounded-xl bg-black border border-[#16161A]">
                        <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">Tier</div>
                        <div className="text-xs text-white font-mono uppercase">{modalSkill.tier || '—'}</div>
                      </div>
                      <div className="p-3 rounded-xl bg-black border border-[#16161A]">
                        <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">Version</div>
                        <div className="text-xs text-white font-mono">{modalSkill.version || '—'}</div>
                      </div>
                      <div className="p-3 rounded-xl bg-black border border-[#16161A]">
                        <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1">Journal Entries</div>
                        <div className="text-xs text-white font-mono">{modalSkill.journalCount ?? 0}</div>
                      </div>
                    </div>

                    <div className="p-3 rounded-xl bg-black border border-[#16161A]">
                      <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500 mb-1.5">Dependencies</div>
                      {(modalSkill.dependencies && modalSkill.dependencies.length > 0) ? (
                        <div className="flex flex-wrap gap-1.5">
                          {modalSkill.dependencies.map((dep, i) => (
                            <span key={i} className="text-[10px] font-mono text-[#00F0FF] bg-[#00F0FF]/5 border border-[#00F0FF]/20 rounded px-2 py-0.5">
                              {String(dep).replace('foundry://skills/', '')}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[11px] text-slate-500 font-mono">none — independent skill</div>
                      )}
                    </div>

                    <div className="p-3 rounded-xl bg-black border border-[#16161A] font-mono text-[11px] text-slate-500">
                      <span className="text-[#00F0FF]">HIERARCHY_DEPTH:</span> {activeModalNode.depth}{activeModalNode.independent ? ' (independent ring)' : ''} <br />
                      <span className="text-[#00F0FF]">DEPENDED_ON_BY:</span> {activeModalNode.inDegree} skill{activeModalNode.inDegree === 1 ? '' : 's'}
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="p-6 pt-4 border-t border-[#16161A] flex justify-end gap-3">
                    <button
                      onClick={() => { if (onSelectSkill) onSelectSkill(modalSkill); setActiveModalNode(null); }}
                      className="bg-[#00F0FF] text-black px-5 py-2.5 rounded-lg text-xs font-bold uppercase tracking-widest transition-colors hover:bg-white"
                    >
                      Open Skill
                    </button>
                    <button
                      onClick={() => setActiveModalNode(null)}
                      className="bg-[#16161A] hover:bg-[#00F0FF] hover:text-black text-[#00F0FF] px-5 py-2.5 rounded-lg text-xs font-bold uppercase tracking-widest transition-colors shadow-[0_0_15px_rgba(0,240,255,0.05)]"
                    >
                      Close
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Honest caption — computed from the real data */}
          <div className="border-t border-[#16161A] px-6 py-2.5 text-center">
            <span className="text-[10px] text-slate-500 font-mono">
              Poincaré-disk view · {nodeCount} skills · {edgeCount} typed edges from map.json v2 · click a node to open it
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
