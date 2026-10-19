"""Bounded correction review in the existing subscription review session."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909/anchor')
os.environ['ANCHOR_DATA_DIR']='C:/dev/Anchor'
sys.path.insert(0,str(ROOT))
import anchor_settings
import model_policy
from steward_cockpit.grok_turn_bridge import GrokBroker

prior=json.loads((HERE/'grok-deployment-resumed-2026-09-09.json').read_text(encoding='utf-8'))
receipt=HERE/'grok-installer-corrections-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Correction review already launched')
paths=['tools/setup_notebooks.ps1','tools/install_notebook_startup.ps1','docs/notebook-host-setup.md']
diff=subprocess.run(['git','-C',str(ROOT),'diff','--',*paths],capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout
selection=model_policy.resolve('grok',settings=anchor_settings.get_launch_settings())
record=dict(started=datetime.now(timezone.utc).isoformat(),status='running',selection=selection,cross_model=True,
            resume=prior['result']['session_id'],sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},tools=[])
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
def emit(event):
    for b in event.get('message',{}).get('content',[]):
        if isinstance(b,dict) and b.get('type')=='tool_use': record['tools'].append(b.get('name'));save()
save()
prompt='''Continue your completed installer review, checking ONLY dispositions D1-D5 and the supplied exact diff. Do not repeat the whole investigation or expand scope. Use Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans. For this correction review use NO tools; all changed code is below. Return one JSON object verdict revise|no_material_findings_in_scope, findings array (only concrete remaining defects), limits array. One dry round ends the review loop.
D1 repaired by requiring standalone Python3.12+ before installation writes. Python official venv docs confirm setuptools is no longer a core dependency starting3.12; active pth rejection remains unchanged.
D3 setup now stamps Net.Dns.GetHostName consistent with startup and Python. Observed this host reports COMPUTERNAME PUTER and DNS Puter; current comparisons ignore case so the existing running setup is unaffected here.
D4 only cold pip install gets15minutes; other native probes retain2minutes. Docs narrowly allow preparation-only recovery after verifying no account/task/runtimeconfig; no user-data deletion/adoption.
D5 direct per-user native group query including indirect memberships; every returned SID must be Users only. Unrelated unresolved members are no longer enumerated. Native Windows API contract documented at https://learn.microsoft.com/en-us/windows/win32/api/lmaccess/nf-lmaccess-netusergetlocalgroups . Separate nested-exit allegation DISPROVEN by invoking actual startup script ActionPlan invalid Account via call operator: child returned exit1 and JSON exact_local_account_required; caller after marker and finally both ran. Setup already parses returned JSON okfalse and throws into own finally.
D2 no established code defect: setup always administrator, creates clean normal inheriting venv descendants then applies inheritable RX ACL to their parent. Microsoft documents SetNamedSecurityInfo/SetSecurityInfo automatic inheritance propagating to EXISTING unprotected descendants: https://learn.microsoft.com/en-us/windows/win32/secauthz/automatic-propagation-of-inheritable-aces . A nonadmin synthetic Set-Acl probe on this host failed SeSecurityPrivilege, so do NOT count that as a passed native ACL test or installer failure. We will require actual dedicated-account service/kernel startup before enabling links; local password input still pending. No ACL safety check was weakened. Assess whether there is a concrete remaining failure given documented Windows behavior, rather than requiring speculative new recursive permission rewrites.
Local Windows regression tests are being run independently; do not claim their results. No actual installation/browser/reboot acceptance is claimed. Diff:
'''+diff
broker=GrokBroker(target=str(ROOT),model=selection['model'],effort=selection['effort'],permission_mode='plan',resume=record['resume'],emit=emit,turn_timeout_seconds=900)
try:
    answer=broker.turn({'type':'user','message':{'content':[{'type':'text','text':prompt}]}})
    record['result']=answer
    try: record['review']=json.loads(answer.get('result',''))
    except (ValueError,TypeError): record['review']=None
    record['status']='reviewed' if (not answer.get('is_error') and answer.get('model_attested') and isinstance(record['review'],dict) and isinstance(record['review'].get('findings'),list) and answer.get('containment',{}).get('descendants_verified')) else 'incomplete'
finally:
    broker.stop();record['ended']=datetime.now(timezone.utc).isoformat();save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h:
        h.write('\n'+record['ended']+': Installer correction review '+record['status']+'; exact receipt retained.\n')
    print(record['status'],flush=True)
