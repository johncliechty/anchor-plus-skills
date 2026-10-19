"""Continue the active read-only review after a wall limit, preserving its session."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909/anchor')
os.environ['ANCHOR_DATA_DIR']='C:/dev/Anchor'
sys.path.insert(0,str(ROOT))
import anchor_settings
import model_policy
from steward_cockpit.grok_turn_bridge import GrokBroker
prior=json.loads((HERE/'grok-deployment-files-2026-09-09.json').read_text(encoding='utf-8'))
result=prior['result']
assert result['error']['code']=='turn_timeout' and result['containment']['descendants_verified']
receipt=HERE/'grok-deployment-resumed-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Resume already attempted')
selection=model_policy.resolve('grok',settings=anchor_settings.get_launch_settings())
record=dict(started=datetime.now(timezone.utc).isoformat(),status='running',
            prior_receipt='grok-deployment-files-2026-09-09.json',resume=result['session_id'],
            source_provenance=prior['provenance'],selection=selection,cross_model=True,tools=[])
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
def emit(event):
    for b in event.get('message',{}).get('content',[]):
        if isinstance(b,dict) and b.get('type')=='tool_use': record['tools'].append(b.get('name')); save()
save()
broker=GrokBroker(target=str(ROOT),model=selection['model'],effort=selection['effort'],
                  permission_mode='plan',resume=result['session_id'],emit=emit,turn_timeout_seconds=900)
try:
    answer=broker.turn({'type':'user','message':{'content':[{'type':'text','text':
      'Continue the same installer review. The host600second wall watchdog interrupted you while progress was still arriving (idle0.9s); source files are unchanged. You already read the two scripts in3Read calls. Finish the review from that evidence; do not repeat the whole investigation. Use Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans. For this review ONLYRead if essential; no edits/subagents/web/shell. Return one complete JSON object with verdict revise|no_material_findings_in_scope, findings array of concrete defects withrepair/acceptance_test, limitsarray. Maximum5materialfindings; one dryreview endsloop. No boilerplate or additional architecture. Actual service/kernel/browser proof remains a later installation gate.'}]}})
    record['result']=answer
    try: record['review']=json.loads(answer.get('result',''))
    except (ValueError,TypeError): record['review']=None
    record['status']='reviewed' if (not answer.get('is_error') and answer.get('model_attested')
        and isinstance(record['review'],dict) and isinstance(record['review'].get('findings'),list)
        and answer.get('containment',{}).get('descendants_verified')) else 'incomplete'
finally:
    broker.stop()
    record['ended']=datetime.now(timezone.utc).isoformat(); save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as handle:
        handle.write('\n'+record['ended']+': Resumed deployment review '+record['status']+'; exactreceipt retained.\n')
    print(json.dumps({'status':record['status']}),flush=True)
