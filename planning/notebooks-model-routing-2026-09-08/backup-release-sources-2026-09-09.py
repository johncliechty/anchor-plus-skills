"""Back up private source branches only to the explicitly local E: repositories."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
attempt=sys.argv[1] if len(sys.argv)>1 else '01'
if attempt not in ('01','02','03'): raise RuntimeError('Unknown bounded backup attempt')
receipt=HERE/('release-private-backups'+('' if attempt=='01' else '-'+attempt)+'-2026-09-09.json')
if receipt.exists(): raise RuntimeError('Private backup already attempted')
commits=json.loads((HERE/'release-final-source-commits-2026-09-09.json').read_text())['repositories']
destinations={'anchor':'E:/anchor.git','trio':'E:/trio.git','foundry':'E:/skill-foundry.git','ecgberht':'E:/ecgberht.git'}
record={'started':datetime.now(timezone.utc).isoformat(),'status':'running','backups':[]}
if attempt!='01':
    priorName='release-private-backups'+('' if attempt=='02' else '-02')+'-2026-09-09.json'
    prior=json.loads((HERE/priorName).read_text())
    assert prior['status']=='failed'
    record['backups']=prior['backups']
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
def run(args): return subprocess.run(args,capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
save()
try:
    for name,destination in destinations.items():
        if any(item['repo']==name for item in record['backups']): continue
        target=Path(destination)
        assert target.is_absolute() and target.drive.upper()=='E:' and target.parent==Path('E:/')
        if not target.exists():
            assert name=='trio';run(['git','init','--bare',destination])
        assert run(['git','--git-dir',destination,'rev-parse','--is-bare-repository'])=='true'
        work=ROOT/name
        commit=commits[name].get('freeze_commit',commits[name]['content_commit'])
        assert run(['git','-C',str(work),'rev-parse','HEAD'])==commit
        existing=run(['git','-C',str(work),'tag','-l','v1.3.0'])
        if existing: assert run(['git','-C',str(work),'rev-parse','v1.3.0'])==commit
        else: run(['git','-C',str(work),'tag','v1.3.0',commit])
        trust=['-c','safe.directory='+destination] if name=='trio' else []
        run(['git',*trust,'-C',str(work),'push','--atomic',destination,'HEAD:refs/heads/release/notebooks-share-20260909','refs/tags/v1.3.0:refs/tags/v1.3.0'])
        assert run(['git','--git-dir',destination,'rev-parse','refs/heads/release/notebooks-share-20260909'])==commit
        record['backups'].append({'repo':name,'destination':destination,'commit':commit,'tag':'v1.3.0'});save()
    record['status']='backed_up'
except Exception as exc:
    record['status']='failed';record['error']=str(exc);raise
finally:
    record['ended']=datetime.now(timezone.utc).isoformat();save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h:h.write('\n'+record['ended']+': Private source backup '+record['status']+'; no source history sent to GitHub.\n')
