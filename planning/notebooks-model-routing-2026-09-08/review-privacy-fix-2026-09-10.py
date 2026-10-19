"""One bounded independent review of the secure password retry correction."""
from datetime import datetime, timezone
import hashlib
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

receipt=HERE/'grok-privacy-fix-2026-09-10.json'
if receipt.exists(): raise RuntimeError('Privacy review already attempted')
import subprocess
source = subprocess.run(['git', '-C', str(ROOT), 'diff', '--', 'vendor_skills.py', 'distro.py', 'share_ci_ship_gate.py', 'share_governance.py'], capture_output=True, text=True, encoding='utf-8', check=True).stdout
code = source + '\nTESTS:\n' + (ROOT/'tests/test_share_escaped_paths_2026_09_10.py').read_text(encoding='utf-8')
record={'started':datetime.now(timezone.utc).isoformat(),'status':'running','cross_model':True,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
save();broker=None
try:
    settings=anchor_settings.get_launch_settings()
    selection=model_policy.resolve('grok',settings=settings);record['selection']=selection;save()
    broker=GrokBroker(target=str(ROOT),model=selection['model'],effort=selection['effort'],permission_mode='plan',turn_timeout_seconds=600)
    prompt = """Review this bounded privacy patch for concrete introduced defects. Use Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans. Use NO tools; supplied diff/tests suffice. Return one JSON object verdict revise|no_material_findings_in_scope, findings array and limits array. One dry round ends review. Existing scanner missed JSON-escaped Windows profile paths; existing vendor scrubbing also missed them. Preserve intentional example account exemption and required actual path segment. Avoid breaking nested JSON. Optional PhaseF tools.manifest.json exports must be valid JSON and structurally absolute paths (Windows host). Export-only paths are examples with explicit setup note; real author configuration stays in private source. Optional deterministic/local-model lane remains gated by RAMANUJAN_TOOL_TESTS and is never an automatic production subscription fallback. Original source trailing comma fixed separately. No private notebooks, credentials or projects were found by full-history audit; old published commits retain host identifiers, explicitly disclosed; ordinary new-version push only. Check patch:\n""" + code
    answer=broker.turn({'type':'user','message':{'content':[{'type':'text','text':prompt}]}})
    record['result']=answer
    try:
        reply=answer.get('result','').strip()
        if reply.startswith('```json\n') and reply.endswith('\n```'): reply=reply[8:-4]
        record['review']=json.loads(reply)
    except (ValueError,TypeError): record['review']=None
    record['status']='reviewed' if (not answer.get('is_error') and answer.get('model_attested') and isinstance(record['review'],dict) and answer.get('containment',{}).get('descendants_verified')) else 'incomplete'
except Exception as exc:
    record.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
finally:
    if broker: broker.stop()
    record['ended']=datetime.now(timezone.utc).isoformat();save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h:h.write('\n'+record['ended']+': Privacy patch independent review '+record['status']+'.\n')
