import React, { useEffect, useState } from 'react';
import Markdown from './components/Markdown';
import SleepTrainingTile from './components/SleepTrainingTile';
import ControlPlaneModal from './components/ControlPlaneModal';
import KnowledgeGraphTile from './components/KnowledgeGraphTile';
import { Library, KnowledgeMap, ProcessMap, Issues } from './components/SkillMaps';

async function read(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function Icon({ skill, large = false }) {
  return skill.icon ? <img className={large ? 'big' : 'ic'} src={skill.icon} alt="" /> :
    <span className={`${large ? 'big' : 'ic'} mono-ic`} aria-label="Art needed">{skill.name.slice(0, 2).toUpperCase()}</span>;
}

function Tile({ title, preview, children, open = false, id }) {
  return <details className="walk-tile" open={open || undefined} id={id}>
    <summary><span>{title}</span><small>{preview}</small></summary><div className="tile-body">{children}</div>
  </details>;
}

export default function App() {
  const [page, setPage] = useState(null);
  const [skillId, setSkillId] = useState(new URLSearchParams(location.search).get('skill') || 'researchprime');
  const [detail, setDetail] = useState(null);
  const [search, setSearch] = useState('');
  const [rail, setRail] = useState(false);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [op, setOp] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [summary, setSummary] = useState('');
  const [relatedSkills, setRelatedSkills] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    read('/api/foundry/page', controller.signal).then(setPage).catch(e => {
      if (e.name !== 'AbortError') setError('Foundry sources could not be loaded. Reload to retry.');
    });
    Promise.allSettled([read('/api/metrics', controller.signal), read('/api/summary', controller.signal), read('/api/skills', controller.signal)])
      .then(([m, s, r]) => { if (m.status === 'fulfilled') setMetrics(m.value); if (s.status === 'fulfilled') setSummary(s.value.summary); if (r.status === 'fulfilled') setRelatedSkills(r.value); });
    const back = () => setSkillId(new URLSearchParams(location.search).get('skill') || 'researchprime');
    const escape = e => { if (e.key === 'Escape') setRail(false); };
    window.addEventListener('popstate', back);
    window.addEventListener('keydown', escape);
    return () => { controller.abort(); window.removeEventListener('popstate', back); window.removeEventListener('keydown', escape); };
  }, []);

  useEffect(() => {
    if (!page || skillId === 'home') { setDetail(null); return; }
    const controller = new AbortController();
    let active = true;
    setDetail(null); setDetailError(''); setSelectedNode(null);
    read(`/api/foundry/skill?skill=${encodeURIComponent(skillId)}`, controller.signal)
      .then(d => { if (active) setDetail(d); })
      .catch(e => { if (active && e.name !== 'AbortError') setDetailError('This skill could not be loaded. Select it again to retry.'); });
    return () => { active = false; controller.abort(); };
  }, [page, skillId]);

  const select = id => {
    history.pushState(null, '', `/foundry?skill=${encodeURIComponent(id)}`);
    setSkillId(id); setRail(false);
  };
  const skills = page?.skills || [];
  const selected = detail?.skill;
  const resources = detail?.resources || [];
  const library = detail?.libraryResources || resources;
  const files = resources.filter(r => !r.anchor && r.path &&
    r.path.replaceAll('\\', '/').startsWith(`${selected?.source.replaceAll('\\', '/')}/`) &&
    /(?:SKILL|HUMAN|NORTH-STAR|VISION)\.md$/.test(r.path));
  const journals = resources.filter(r => r.path && /[/\\]journal[/\\]/.test(r.path));

  return <div className="foundry-walkthrough">
    <header className="masthead">
      <a href="/" aria-label="Anchor"><img className="mark" src="/vendor/brand/anchor-icon-64.png" alt="Anchor" /></a>
      <img className="mark" src="/brand/foundry-edge-skill-foundry.png" alt="" />
      <span className="mh-title">Skill Foundry</span>
      <span className="mh-note">Skill walkthroughs in progress</span>
      <button className="skills-btn" aria-expanded={rail} aria-controls="skill-rail" onClick={() => setRail(!rail)}>Skills A–Z</button>
    </header>
    <div className="shell">
      {rail && <button className="rail-scrim" aria-label="Close skills" onClick={() => setRail(false)} />}
      <nav className={`rail ${rail ? 'show' : ''}`} id="skill-rail" aria-label="Skills A–Z">
        <button className="home-button" onClick={() => select('home')} aria-current={skillId === 'home' ? 'page' : undefined}>Foundry home</button>
        <h2>Skills A–Z · {skills.length}</h2>
        <input className="search" aria-label="Search skills" placeholder="Find a skill…" value={search} onChange={e => setSearch(e.target.value)} />
        {skills.filter(s => `${s.name} ${s.purpose}`.toLowerCase().includes(search.toLowerCase())).map(s =>
          <button className="skill" key={s.id} onClick={() => select(s.id)} aria-current={s.id === skillId ? 'page' : undefined}>
            <Icon skill={s} /><span><span className="nm">{s.name}</span><span className="pp">{s.purpose}</span></span>
          </button>)}
        {!page && <p>{error || 'Loading source catalog…'}</p>}
        <button className="btn create-skill" onClick={() => setOp('scaffold_skill')}>Create new skill</button>
      </nav>
      <main id="skill-main">
        {error && <p role="alert">{error}</p>}
        {skillId === 'home' ? <>
          <h1>Foundry home</h1><Markdown source={page?.northStar} />
          <p className="qualification">Walk through researchPrime first, then Gandalf, the AI cockpit / Lamp, Cave of Wonders and Star Chart. Their names follow the selected persona ({page?.persona || 'loading'}).</p>
          <p>{skills.length} discovered skills and roles · {metrics?.journalEntries ?? '—'} recorded journal entries · {metrics?.sleepRuns ?? '—'} recorded sleep runs</p>
          <button className="btn" onClick={() => select('researchprime')}>Open researchPrime</button>
          <h2>Source discovery</h2><p>New skills appear from their existing instruction files. Map and Library content is read from Foundry; missing content remains unfinished.</p>
          <p className="qualification">Related skills shows the existing Foundry dependency map, separately from each skill’s knowledge Library.</p>
          <KnowledgeGraphTile skills={relatedSkills} onSelectSkill={s => { const row = skills.find(row => row.ref === s.ref); if (row) select(row.id); }} />
        </> : selected ? <>
          <div className="skill-head"><Icon skill={selected} large /><div className="head-body">
            <h1>{selected.name}</h1><p className="purpose">{selected.purpose}</p>
            <div className="actions">{files.map(r => <a className="btn" href={r.href} key={r.id} target="_blank" rel="noreferrer">{r.title === 'SKILL.md' ? 'Skill instructions' : r.title === 'HUMAN.md' ? 'Human guide' : r.title}</a>)}
              <button className="btn" onClick={() => { const el = document.getElementById('files'); el.open = true; el.scrollIntoView({ block: 'start' }); }}>Program files</button>
            </div>
          </div></div>
          <p className="qualification">{detail.knowledgeMap.nodes.length && detail.processMap.steps.length ?
            `${detail.processMap.qualification} · Library and maps awaiting independent human review.` :
            'Walkthrough unfinished · Foundry’s Library and maps are not available here yet.'}
            {!selected.inFoundryMap && ' Not in the Foundry map.'}</p>
          <Tile title="North Star" preview={selected.northStar ? 'Read the declared purpose' : 'No North Star file yet'}>
            {selected.northStar ? <Markdown source={selected.northStar} /> : <p>No North Star is declared. The purpose above comes from the existing skill instructions or human guide.</p>}
            <button className="btn" onClick={() => setOp('edit_north_star')}>Edit North Star</button>
          </Tile>
          <Tile title="How it works" preview="From the skill’s human guide"><Markdown source={detail.howItWorks} /></Tile>
          <Tile title="Poincaré knowledge map" preview={detail.knowledgeMap.status} open id="knowledge-map">
            <KnowledgeMap key={skillId} map={detail.knowledgeMap} resources={resources} steps={detail.processMap.steps} externalSelection={selectedNode} />
          </Tile>
          <Tile title="Library" preview={`${library.length} source resources · use labels require recorded evidence`} id="library">
            <Issues issues={detail.libraryIssues} /><Library resources={library} />
          </Tile>
          <Tile title="Process map" preview={detail.processMap.status} id="process-map">
            <ProcessMap map={detail.processMap} resources={resources} nodes={detail.knowledgeMap.nodes} onExploreNode={id => { setSelectedNode(id); const el = document.getElementById('knowledge-map'); el.open = true; el.scrollIntoView({block:'start'}); }} />
          </Tile>
          <Tile title="Core capabilities" preview="Read the real instruction sections">
            {detail.capabilities.map(c => <details key={c.title}><summary>{c.title}</summary><Markdown source={c.detail} /></details>)}
          </Tile>
          <Tile title="Evolution and journals" preview={`${detail.journalCount} journal entries · source history`}>
            <p>Journal entries and existing lessons/changelog are available in full. A synthesized journal report has not been integrated.</p>
            <Library resources={[...resources.filter(r => /(?:LESSONS|CHANGELOG)\.md$/.test(r.path || '')), ...journals]} />
          </Tile>
          <Tile title="Files" preview="Instructions, human guide and declared programs" id="files"><Library resources={resources.filter(r => r.path && !journals.includes(r))} /></Tile>
          <SleepTrainingTile selectedSkill={{...selected, journalCount: detail.journalCount, timeline: detail.timeline}} summary={summary} metrics={metrics} />
        </> : <p role="status">{detailError || 'Loading skill…'}</p>}
      </main>
    </div>
    <ControlPlaneModal op={op} onClose={() => setOp(null)} />
  </div>;
}
