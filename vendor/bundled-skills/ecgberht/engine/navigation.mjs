/** Presentation metadata only; the roadmap remains the sole live map. */
const id = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$/;
const object = v => v && typeof v === 'object' && !Array.isArray(v);
const text = v => typeof v === 'string' && v.trim().length > 0 && v.length <= 200;
function keys(v, allowed) { return Object.keys(v).every(k => allowed.includes(k)); }
function groupPath(v) {
  return Array.isArray(v) && v.length >= 1 && v.length <= 2 && v.every(g => typeof g==='string' && id.test(g)) && new Set(v).size === v.length;
}
function relative(v) {
  return typeof v === 'string' && v.length > 0 && v.length <= 1000 && !/[\\:\x00-\x1f]/.test(v) && !v.startsWith('/') && !v.split('/').some(p => !p || p === '..' || p === '.');
}
export function validNavigation(v) {
  if (v == null) return true;
  return object(v) && keys(v,['path','groups','role','pin','current','label','items','featured_paths']) && groupPath(v.path) &&
    (v.current===undefined || typeof v.current==='boolean') &&
    (v.featured_paths===undefined||(Array.isArray(v.featured_paths)&&v.featured_paths.length<=30&&v.featured_paths.every(relative))) &&
    (v.groups === undefined || (Array.isArray(v.groups) && v.groups.length<=100 && v.groups.every(g=>object(g)&&keys(g,['id','label','order','parent_id'])&&id.test(g.id)&&text(g.label)&&Number.isInteger(g.order)&&g.order>=0&&g.order<=10000&&(g.parent_id===null||(typeof g.parent_id==='string'&&id.test(g.parent_id)))))) &&
    (v.role === undefined || ['primary','support'].includes(v.role)) &&
    (v.pin === undefined || typeof v.pin === 'boolean') &&
    (v.label === undefined || text(v.label)) &&
    (v.items === undefined || (Array.isArray(v.items) && v.items.length <= 200 && v.items.every(x => object(x) && keys(x,['source_path','path']) && relative(x.source_path) && groupPath(x.path))));
}
export function navigationIssues(steps) {
  const groups = new Map(), sources = new Map(), issues=[];
  for(const s of steps) {
    if(s.navigation==null)continue;
    if(!validNavigation(s.navigation)){issues.push({code:'invalid_navigation',step_id:s.id});continue;}
    for(const g of s.navigation.groups||[]) {
      if(groups.has(g.id))issues.push({code:'navigation_group_conflict',group_id:g.id});
      groups.set(g.id,g);
    }
  }
  if(issues.length)return issues;
  for(const g of groups.values())if(g.parent_id!==null&&(!groups.has(g.parent_id)||groups.get(g.parent_id).parent_id!==null))issues.push({code:'navigation_invalid_parent',group_id:g.id});
  if(steps.filter(s=>s.navigation?.pin).length>1)issues.push({code:'navigation_multiple_pins'});
  for (const s of steps) {
    const n=s.navigation;if(n==null)continue;
    for (const p of [n.path,...(n.items||[]).map(i=>i.path)]) {
      let parent=null;
      for (const gid of p) {
        const g=groups.get(gid);
        if(!g||g.parent_id!==parent)issues.push({code:'navigation_invalid_path',group_id:gid});
        parent=gid;
      }
    }
    for(const i of n.items||[]) {
      const k=i.source_path.toLowerCase(),dest=i.path.join('/');
      if(sources.has(k)&&sources.get(k)!==dest)issues.push({code:'navigation_artifact_conflict',source_path:i.source_path});
      sources.set(k,dest);
    }
  }
  return issues;
}
