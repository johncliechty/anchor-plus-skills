"""Record formal maintenance without fabricating separate production skill runs."""
from datetime import datetime, timezone
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
notes={
 'trio/foreman':('Foreman','Require execution readiness and persist and register notebook deliverables at their producing step. Source checks do not prove that a live notebook opens.','Updated readiness, persistence, and notebook work-product instructions.'),
 'foundry/skills/jumper':('Jumper','Produce, persist, and register requested notebooks in the same step so the shared interface has an artifact to open.','Added notebook work-product instructions.'),
 'foundry/skills/ramanujan':('Ramanujan','Read model authority from preferences and carry it through the actual driver and helper. Persist and register notebook work products when produced.','Updated preference-driven driver and helper behavior and notebook work-product instructions.'),
 'ecgberht':('Ecgberht','Read model and effort authority from preferences and carry it through the actual seat invocation. Report the actual provider and model evidence.','Updated preference-driven seat selection and invocation.'),
}
record=[]
for relative,(name,lesson,change) in notes.items():
    for filename,body in [('LESSONS.md',lesson),('CHANGELOG.md',change)]:
        path=ROOT/relative/filename
        marker='## 2026-09-09 — notebook and model-policy maintenance'
        prior=path.read_text(encoding='utf-8') if path.exists() else '# '+filename[:-3].title()+' — '+name+'\n'
        if marker in prior: raise RuntimeError('Maintenance note already present')
        path.write_text(prior.rstrip()+'\n\n'+marker+'\n\n'+body+'\n\nValidation: focused source tests passed. Notebook execution, authenticated opening, and recovery require acceptance on the installation host.\n',encoding='utf-8')
        record.append(str(path))
journal=ROOT/'foundry/planning/anchor-notebooks-policy-2026-09-08/journal'
journal.mkdir(parents=True,exist_ok=True)
numbers=[int(p.name[:4]) for p in journal.glob('*.md') if p.name[:4].isdigit()]
number=max(numbers,default=0)+1
human=journal/(f'{number:04d}-release-maintenance.md')
now=datetime.now(timezone.utc).isoformat()
human.write_text('\n'.join([
 '# Notebook and model-policy release maintenance',
 '**Date:** '+now,
 '**Task:** One authorized maintenance cycle across Anchor, Trio, Foundry, and Ecgberht; no separate production engine invocations.',
 '**Result:** Scoped source and package checks passed; final rebuild/publication and local notebook acceptance remain pending.',
 '**Friction:** Provider-renewed catalog freshness, stale test fixtures, installer portability, and PowerShell JSON array handling.',
 '**Lesson:** Preferences must govern actual dispatch; notebook artifacts must persist and open at their producing step. Source tests do not establish live UI delivery.',
 '**Action:** Publish only the scrubbed clean package. Enable local links only after dedicated-account Python/R and browser acceptance.',
 '**Evidence:** Trio252, Foundry51, Ecgberht8; cache Python58/Node73 and attested Grok dry review; package install10/update7/freeze52. Installer review dry; post-review JSON correction covered by native regression tests.',
 ])+'\n',encoding='utf-8')
(journal/'runs').mkdir(exist_ok=True)
machine=dict(skill='Skill Foundry maintenance cycle',tier='maintenance; externally visible release check',
    started=now,ended=None,input='Authorized Anchor notebook and provider policy improvements, collaborator release.',
    params={'phase':'release record opened after source validation','engine_runs_invented':False},
    output='Scoped release branches, generic skill lessons/changelogs, scrubbed package candidate.',
    result='source_verified; final_rebuild_publication_and_local_notebook_acceptance_pending',cross_model=True,
    models=[{'family':'chatgpt','model_attested':False},{'family':'grok','model_served':'grok-4.6-build','model_attested':True}],
    duration_s=None,journal_ref=human.name)
(journal/'runs/2026-09-10-release-maintenance.json').write_text(json.dumps(machine,indent=2)+'\n',encoding='utf-8')
(HERE/'release-maintenance-notes-2026-09-09.json').write_text(json.dumps({'created':now,'paths':record,'journal':str(journal)},indent=2),encoding='utf-8')
print('Recorded four generic skill notes and one paired maintenance record.')
