import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';

const words = value => typeof value === 'string' ? value : value ? JSON.stringify(value, null, 2) : '';
const groups = [['material', 'Reusable material'], ['references', 'References'], ['skills', 'Other skills'], ['tools', 'Tools']];
export function Issues({ issues = [] }) {
  return issues.length > 0 && <details className="map-issues"><summary>Source checks need attention ({new Set(issues).size})</summary>
    <ul>{[...new Set(issues)].map((issue, i) => <li key={i}>{issue}</li>)}</ul></details>;
}

export function Library({ resources }) {
  const [query, setQuery] = useState('');
  const matches = resources.filter(r => `${r.title} ${r.description || ''}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="library-view">
    <input className="search" aria-label="Search library" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find material, references, skills or tools…" />
    {groups.map(([id, label]) => <section key={id}><h3>{label}</h3>
      {matches.filter(r => r.category === id || (id === 'material' && !groups.some(g => g[0] === r.category))).map((r, i) =>
        <div className="library-resource" key={`${r.id}-${i}`} data-resource-id={r.id}>
          <a href={r.href} target="_blank" rel="noreferrer">{r.title}</a><small>{r.frequency || 'Use not recorded'}</small>
          {r.sourceHref && r.sourceHref !== r.href && <a href={r.sourceHref} target="_blank" rel="noreferrer">Read exact source</a>}
          {r.description && <p>{r.description}</p>}{r.problem && <p className="source-problem">{r.problem}</p>}
        </div>)}
      {!matches.some(r => r.category === id) && <p className="muted">No declared resources in this category yet.</p>}
    </section>)}
  </div>;
}

function SourceLink({ link, label }) {
  return !link ? <span className="muted">{label}: no source declaration</span> : <span className="source-link">
    {link.href ? <a href={link.href} target="_blank" rel="noreferrer">{label}: {link.label}</a> : <span>{label}: {link.label} {link.note}</span>}
    {link.problem && <strong className="source-problem">{link.problem}</strong>}
  </span>;
}

export function ProcessMap({ map, resources, nodes = [], onExploreNode }) {
  const steps = map.steps || [];
  return <div className="process-view">
    <p className="qualification">{map.qualification || 'Process walkthrough unfinished. Foundry must supply checked source anchors.'}</p>
    <Issues issues={map.issues} />
    <div className="legend">Program · AI model call · Human decision · Operator/session · Terminal</div>
    {!steps.length && <p className="empty">No process map yet. Read the real instructions and programs in Files.</p>}
    {steps.map((step, i) => <React.Fragment key={step.id}>
      <article id={`step-${step.id}`} className={`process-step ${step.kind}`}>
        <span className="kind">{step.kind}</span><h3>{step.title}</h3><p>{step.description}</p>
        {step.role && <p className="seat">Agent/seat: {words(step.role)}</p>}
        {step.swarm && <p className="seat">Swarm: {step.swarm.enabled === false ? 'No new swarm on this step.' : words(step.swarm)}</p>}
        {step.differs && <p className="source-problem">Code / instruction disagreement: {words(step.differs)}</p>}
        <div className="step-sources"><SourceLink link={step.codeLink} label="Code" /><SourceLink link={step.instructionLink} label="Instructions" /></div>
        {step.anchorLinks?.filter(link => link !== step.codeLink && link !== step.instructionLink &&
          link.href !== step.codeLink?.href && link.href !== step.instructionLink?.href).map((link, j) =>
          <SourceLink key={j} link={link} label="Source" />)}
        {step.resource_ids?.length > 0 && <div className="step-library">Library: {step.resource_ids.map(id => {
          const r = resources.find(r => r.id === id);
          return r ? <a key={id} href={r.href} target="_blank" rel="noreferrer">{r.title}</a> : <span key={id}>Missing {id}</span>;
        })}</div>}
        {nodes.some(n => (n.process_ids || []).includes(step.id)) && <div className="step-library">Knowledge map: {nodes.filter(n => (n.process_ids || []).includes(step.id)).map(n => <button className="btn" key={n.id} onClick={() => onExploreNode(n.id)}>{n.name}</button>)}</div>}
      </article>
      {(map.edges || []).filter(e => e.from === step.id).map((e, j) => <div className="process-arrow" key={j}>
        <span aria-hidden="true">↓</span> <a href={`#step-${e.to}`}>{e.label || e.condition || 'Continue'} → {steps.find(s => s.id === e.to)?.title || e.to}</a>
        {e.sourceLink?.href && <a className="edge-source" href={e.sourceLink.href} target="_blank" rel="noreferrer">Source</a>}
      </div>)}
    </React.Fragment>)}
    {map.exits?.length > 0 && <div className="exits"><h3>Stopping paths</h3>{map.exits.map((e, i) => <p key={i}>{words(e)}</p>)}</div>}
    {map.deliverable && <div className="exits"><h3>Final outputs</h3><p>{words(map.deliverable)}</p></div>}
    {map.disagreements?.length > 0 && <section className="disagreements"><h3>Code / instruction disagreements</h3>
      {map.disagreements.map((d, i) => <details key={i}><summary>{d.title || words(d)}</summary><p>{d.fact || d.description || words(d)}</p>
        {(d.sourceLinks || []).map((link, j) => <SourceLink key={j} link={link} label="Evidence" />)}</details>)}
    </section>}
    {map.observedExamples?.length > 0 && <section className="observed-examples"><h3>Use and improvement</h3>
      <p>Recorded examples retain their capture dates and scope. They do not establish current deployment, resource access frequency or human acceptance.</p>
      {map.observedExamples.map((example, i) => <details key={i}><summary>{example.id}</summary><p>{example.summary}</p>
        {(example.sourceLinks || []).map((link, j) => <SourceLink key={j} link={link} label="Evidence" />)}</details>)}
      {map.usageAudit && <p>{map.usageAudit.scope} · {map.usageAudit.qualification}</p>}
    </section>}
  </div>;
}

export function KnowledgeMap({ map, resources, steps, externalSelection }) {
  const [query, setQuery] = useState('');
  const [outline, setOutline] = useState(false);
  const [selected, setSelected] = useState(null);
  const [focus, setFocus] = useState(null);
  const [lens, setLens] = useState('all');
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef(null);
  useEffect(() => { if (externalSelection) setSelected(externalSelection); }, [externalSelection]);
  const nodes = map.nodes || [];
  const byId = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes]);
  const below = (n, root) => {
    const seen = new Set();
    while (n && !seen.has(n.id)) { if (n.id === root) return true; seen.add(n.id); n = byId.get(n.parent); }
    return false;
  };
  const visible = focus ? nodes.filter(n => below(n, focus)) : nodes;
  // d3 hierarchy partitions only the declared tree. Artifact positions/weights
  // are deliberately ignored: this is seeded geometry, never learned use.
  const layout = useMemo(() => {
    const permitted = new Set(visible.map(n => n.id));
    const children = new Map();
    visible.forEach(n => { const p = permitted.has(n.parent) ? n.parent : '__root'; if (!children.has(p)) children.set(p, []); children.get(p).push(n); });
    const build = (node, seen = new Set()) => ({ ...node, children: seen.has(node.id) ? [] : (children.get(node.id) || []).filter(n => !seen.has(n.id)).map(n => build(n, new Set([...seen, node.id]))) });
    const tree = d3.hierarchy(build({ id: '__root' })).sum(n => n.children?.length ? 0 : 1);
    d3.partition().size([2 * Math.PI, 1])(tree);
    const maxDepth = Math.max(1, tree.height - 1);
    return tree.descendants().filter(n => n.depth > 0).map(n => {
      const angle = (n.x0 + n.x1) / 2 - Math.PI / 2;
      const radius = n.depth === 1 && children.get('__root')?.length === 1 ? 0 : 35 + 205 * Math.tanh((n.depth - 1) / maxDepth * 1.7);
      return { ...n.data, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
    });
  }, [nodes, focus]);
  const matches = n => n.name.toLowerCase().includes(query.toLowerCase()) && (lens === 'all' || (n.facets || []).includes(lens));
  const chosen = byId.get(selected);
  const resource = chosen && resources.find(r => r.id === chosen.resourceId);
  const choose = id => setSelected(id);
  const zoom = delta => setView(v => ({ ...v, k: Math.max(0.6, Math.min(4, v.k * delta)) }));
  return <div className="knowledge-view">
    <p className="qualification">{map.qualification}</p><Issues issues={map.issues} />
    {!nodes.length ? <p className="empty">Knowledge map unfinished. The Library already opens the skill’s real files; Foundry supplies the declared tree.</p> : <>
      <div className="map-toolbar">
        <input className="search" aria-label="Search knowledge map" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a concept…" />
        <select aria-label="Map facet" value={lens} onChange={e => setLens(e.target.value)}><option value="all">All facets</option>{[...new Set(nodes.flatMap(n => n.facets || []))].map(f => <option key={f}>{f}</option>)}</select>
        <button className="btn" aria-pressed={outline} onClick={() => setOutline(!outline)}>Outline</button>
        <button className="btn" aria-label="Zoom in" onClick={() => zoom(1.25)}>+</button><button className="btn" aria-label="Zoom out" onClick={() => zoom(0.8)}>−</button>
        <button className="btn" onClick={() => { setFocus(null); setView({ x: 0, y: 0, k: 1 }); }}>Whole map</button>
      </div>
      {focus && <p className="breadcrumbs"><button onClick={() => setFocus(null)}>Whole map</button> › {byId.get(focus)?.name}</p>}
      <div className="map-and-card">
        {outline ? <div className="map-outline">{visible.filter(matches).map(n => <button key={n.id} aria-pressed={selected === n.id} style={{ marginInlineStart: Math.min(n.depth, 4) * 12 }} onClick={() => choose(n.id)}>{n.name}</button>)}</div> :
          <svg className="knowledge-disk" viewBox="-300 -300 600 600" aria-label="Seeded knowledge hierarchy" onWheel={e => zoom(e.deltaY < 0 ? 1.1 : 0.9)}
            onPointerDown={e => { if (e.target === e.currentTarget || e.target.classList.contains('map-disk')) { drag.current = { startX: e.clientX, startY: e.clientY, x: view.x, y: view.y }; e.currentTarget.setPointerCapture(e.pointerId); } }}
            onPointerMove={e => { if (drag.current) { const scale = 600 / e.currentTarget.getBoundingClientRect().width; setView(v => ({ ...v, x: drag.current.x + (e.clientX - drag.current.startX) * scale, y: drag.current.y + (e.clientY - drag.current.startY) * scale })); } }}
            onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
            <circle className="map-disk" r="270" />{[80, 150, 210].map(r => <circle className="map-ring" key={r} r={r} />)}
            <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
              {layout.filter(n => byId.has(n.parent)).map(n => { const p = layout.find(p => p.id === n.parent); return p && <line className="map-edge" key={`edge-${n.id}`} x1={p.x} y1={p.y} x2={n.x} y2={n.y} />; })}
              {layout.map(n => <g key={n.id} role="button" tabIndex="0" aria-label={`Concept: ${n.name}`} className={`map-node ${matches(n) ? '' : 'dim'} ${selected === n.id ? 'selected' : ''}`}
                transform={`translate(${n.x},${n.y})`} onClick={() => choose(n.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(n.id); } }}>
                <circle r="8" /><title>{n.name}</title>{(n.depth <= 1 || selected === n.id || (focus && n.depth <= byId.get(focus).depth + 1) || query || view.k >= 1.5) && <text textAnchor="middle" y="22">{n.name.length > 24 ? n.name.slice(0, 22) + '…' : n.name}</text>}
              </g>)}
            </g>
          </svg>}
        <aside className="source-card" aria-label="Concept source card">{chosen ? <>
          <small>Library › depth {chosen.depth} › {chosen.name}</small><h3>{chosen.name}</h3>
          {resource ? <><p>{resource.description || resource.title}</p><p className="muted">{resource.frequency}</p><a className="btn" href={resource.href} target="_blank" rel="noreferrer">Open Library resource</a>{resource.problem && <p className="source-problem">{resource.problem}</p>}</> : <p className="source-problem">No real Library target declared.</p>}
          {nodes.some(n => n.parent === chosen.id) && <button className="btn" onClick={() => { setFocus(chosen.id); setView({ x: 0, y: 0, k: 1 }); }}>Explore this branch</button>}
          {chosen.process_ids?.length > 0 && <><h4>Used by process steps</h4>{chosen.process_ids.map(id => <a className="process-ref" href={`#step-${id}`} key={id} onClick={() => document.getElementById('process-map').open = true}>{steps.find(s => s.id === id)?.title || id}</a>)}</>}
        </> : <p>Select a concept to open its real Library resource. Explore a branch, search, or switch to Outline.</p>}</aside>
      </div>
      {(query || lens !== 'all') && <div className="map-search-results">{visible.filter(matches).map(n => <button className="btn" key={n.id} onClick={() => choose(n.id)}>{n.name}</button>)}</div>}
    </>}
  </div>;
}
