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

receipt=HERE/'grok-password-fix-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Password review already attempted')
source=(ROOT/'tools/setup_notebooks.ps1').read_text(encoding='utf-8-sig')
start=source.index('function Read-JupyterPasswordHash(')
stop=source.index('function WriteJsonNew(',start)
code=source[start:stop]
record={'started':datetime.now(timezone.utc).isoformat(),'status':'running','cross_model':True,'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
save();broker=None
try:
    settings=anchor_settings.get_launch_settings()
    selection=model_policy.resolve('grok',settings=settings);record['selection']=selection;save()
    broker=GrokBroker(target=str(ROOT),model=selection['model'],effort=selection['effort'],permission_mode='plan',turn_timeout_seconds=600)
    prompt='''Review ONLY this secure password prompt retry function for concrete defects introduced by the change. Use Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans. For this review use NO tools; supplied code suffices. Return a single JSON object verdict revise|no_material_findings_in_scope, findings array and limits array. One dry round ends review. Context: old inline password confirmation aborted a prepared Windows installer on typing errors. This helper runs after venv preparation and before account creation, retries only short/mismatching input, and returns hash to existing argon2-prefix guard. Existing Native sends InputText through UTF8 stdin, never argv; it propagates operational failures. Real Windows tests16passed include short/mismatching/case input then success, interrupted confirmation, Native failure, and actual SecureString.Copy() throwing ObjectDisposedException after each attempt. AST checks BSTR zero-free in finally. No actual user password was used in tests. Immutable managed plaintext strings are released, not falsely claimed zeroized. Scope excludes existing Native implementation, password policy changes, and service architecture. Function:
'''+code
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
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h:h.write('\n'+record['ended']+': Password prompt independent review '+record['status']+'.\n')
