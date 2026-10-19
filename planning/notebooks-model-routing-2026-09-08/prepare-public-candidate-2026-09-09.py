"""Prepare the scrubbed public commit locally; this step never pushes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909').resolve()
source=ROOT/'package-candidate-03/clean-ship/B-anchor-plus-skills'
work=ROOT/'collaborator-repo'
receipt=HERE/'public-candidate-2026-09-09.json'
gate=json.loads((HERE/'release-package-candidate-03-2026-09-09.json').read_text(encoding='utf-8'))
if gate['status']!='passed' or receipt.exists() or work.exists() or work.parent.resolve()!=ROOT:
    raise RuntimeError('Passed package gates and a new owned clone are required')
record=dict(started=datetime.now(timezone.utc).isoformat(),status='preparing',source=str(source),work=str(work),push=False)
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
save()
log=HERE/'public-candidate-2026-09-09.log'
command=[sys.executable,'tools/publish_share_repo.py','--source',str(source),'--work',str(work),'--no-push']
env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
child=subprocess.Popen([sys.executable,'C:/dev/plans/2026-07-review/pty-launch.py',str(log),subprocess.list2cmdline(command)],
    cwd=ROOT/'anchor',env=env,creationflags=subprocess.CREATE_NO_WINDOW)
record['child_pid']=child.pid;save()
record['exit_code']=child.wait()
if record['exit_code']==0:
    def git(*args):
        return subprocess.run(['git','-C',str(work),*args],capture_output=True,text=True,check=True,
                              creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    record.update(status='committed_not_pushed',commit=git('rev-parse','HEAD'),
        tag=git('rev-parse','v1.3.0'),files=len(git('ls-files').splitlines()),clean=not git('status','--porcelain'))
else: record['status']='failed'
record['ended']=datetime.now(timezone.utc).isoformat();save()
print(json.dumps({k:record[k] for k in ('status','exit_code')}))
