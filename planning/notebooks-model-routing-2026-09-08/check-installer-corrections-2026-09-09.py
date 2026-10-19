from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
attempt=sys.argv[1] if len(sys.argv)>1 else '01'
if attempt not in ('01','02','03','04','05','06','07','08','09'): raise RuntimeError('Unknown bounded gate attempt')
suffix='' if attempt=='01' else '-'+attempt
receipt=HERE/('installer-correction-tests'+suffix+'-2026-09-09.json')
if receipt.exists(): raise RuntimeError('Gate already launched')
command=[sys.executable,'-m','pytest','-q','--tb=short','--basetemp',str(ROOT/('pytest-installer-corrections'+suffix)),
         'tests/test_notebook_startup_plan_2026_09_09.py',
         'tests/test_notebook_startup_membership_2026_09_09.py',
         'tests/test_notebook_setup_preflight_2026_09_09.py']
if attempt in ('03','04','05','06'): command.append('tests/test_notebook_password_retry_2026_09_09.py')
if attempt == '06': command.append('tests/test_notebook_account_description_2026_09_10.py')
if attempt == '07': command=command[:7]+['tests/test_notebook_account_description_2026_09_10.py']
if attempt == '08': command.append('tests/test_notebook_startup_validate_2026_09_10.py')
if attempt == '09': command.extend(['tests/test_notebook_startup_validate_2026_09_10.py','tests/test_notebook_startup_scan_budget_2026_09_10.py'])
record=dict(started=datetime.now(timezone.utc).isoformat(),status='running',command=command)
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
save()
child=subprocess.Popen([sys.executable,'C:/dev/plans/2026-07-review/pty-launch.py',str(HERE/('installer-correction-tests'+suffix+'-2026-09-09.log')),subprocess.list2cmdline(command)],cwd=ROOT/'anchor',env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW)
record['child_pid']=child.pid;save()
record['exit_code']=child.wait();record['status']='passed' if record['exit_code']==0 else 'failed';record['ended']=datetime.now(timezone.utc).isoformat();save()
with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h: h.write('\n'+record['ended']+': Installer correction Windows gate '+record['status']+'.\n')
