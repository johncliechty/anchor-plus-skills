from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
receipt=HERE/'release-final-source-commits-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Final source freeze already attempted')
gate=json.loads((HERE/'installer-correction-tests-02-2026-09-09.json').read_text())
review=json.loads((HERE/'grok-installer-corrections-2026-09-09.json').read_text())
assert gate['status']=='passed' and review['status']=='reviewed' and review['review']['verdict']=='no_material_findings_in_scope'
for rel,expected in review['sources'].items():
    data=(ROOT/'anchor'/rel).read_bytes()
    if rel=='tools/setup_notebooks.ps1':
        current=b'$basePythonVersion = (Native $basePython @(\'-I\',\'-S\',\'-c\',\'"import json, sys; print(json.dumps(sys.version_info[:2]))"\')) | ConvertFrom-Json'
        prior=b'$basePythonVersion = @((Native $basePython @(\'-I\',\'-S\',\'-c\',\'"import json, sys; print(json.dumps(sys.version_info[:2]))"\')) | ConvertFrom-Json)'
        assert data.count(current)==1
        data=data.replace(current,prior)
    assert hashlib.sha256(data).hexdigest()==expected, rel

def git(repo,*args):
    return subprocess.run(['git','-C',str(ROOT/repo),*args],capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
record={'started':datetime.now(timezone.utc).isoformat(),'status':'committing','repositories':{}}
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
save()
paths={
 'trio':['foreman/LESSONS.md','foreman/CHANGELOG.md'],
 'foundry':['skills/jumper/LESSONS.md','skills/jumper/CHANGELOG.md','skills/ramanujan/LESSONS.md','skills/ramanujan/CHANGELOG.md','planning/anchor-notebooks-policy-2026-09-08/journal'],
 'ecgberht':['LESSONS.md','CHANGELOG.md'],
 'anchor':['tools/setup_notebooks.ps1','tools/install_notebook_startup.ps1','docs/notebook-host-setup.md','tests/test_notebook_setup_preflight_2026_09_09.py','tests/test_notebook_startup_membership_2026_09_09.py']}
for repo,files in paths.items():
    assert git(repo,'branch','--show-current')=='release/notebooks-share-20260909'
    git(repo,'add','--',*files)
    git(repo,'commit','-m','Harden notebook installation and record verified maintenance' if repo=='anchor' else 'Record notebook and model-policy maintenance lessons')
    assert not git(repo,'status','--porcelain'),repo
    record['repositories'][repo]={'content_commit':git(repo,'rev-parse','HEAD'),'worktree':str(ROOT/repo)};save()
pins={k:record['repositories'][v]['content_commit'][:12] for k,v in [('anchor','anchor'),('trio','trio'),('skill-foundry','foundry')]}
source=ROOT/'anchor/share_sources_pin.json'
obj=json.loads(source.read_text())
for pin in obj['pins']: pin['commit']=pins[pin['repo']]
obj['skills_pin']['commit']=pins['skill-foundry']
source.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
manifest=ROOT/'anchor/share_freeze_manifest.json'
obj=json.loads(manifest.read_text());obj['freeze_commits']=pins;obj['skills_pin']['commit']=pins['skill-foundry']
obj['notes']='v1.3.0 source freeze. Anchor pins the content commit immediately before this freeze record. Ecgberht source commit '+record['repositories']['ecgberht']['content_commit'][:12]+'. Notebook activation and per-host acceptance remain explicit setup requirements.'
manifest.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
git('anchor','add','--',source.name,manifest.name);git('anchor','commit','-m','Freeze corrected v1.3.0 collaborator sources')
record['repositories']['anchor']['freeze_commit']=git('anchor','rev-parse','HEAD')
record.update(status='committed_clean',ended=datetime.now(timezone.utc).isoformat());save()
print('Four scoped source branches committed; final package freeze recorded.')
