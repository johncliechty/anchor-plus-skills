from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909/anchor')
CANONICAL=Path('C:/dev/Anchor')
receipt=HERE/'password-fix-deployed-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Password fix deployment already recorded')
gate=json.loads((HERE/'installer-correction-tests-04-2026-09-09.json').read_text())
assert gate['status']=='passed'
rel='tools/setup_notebooks.ps1'
prior=subprocess.run(['git','-C',str(ROOT),'show','HEAD:'+rel],capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout
assert (CANONICAL/rel).read_bytes().replace(b'\r\n',b'\n')==prior.replace(b'\r\n',b'\n')
test='tests/test_notebook_password_retry_2026_09_09.py'
assert not (CANONICAL/test).exists()
for path in (rel,test): shutil.copyfile(ROOT/path,CANONICAL/path)
record={'at':datetime.now(timezone.utc).isoformat(),'gate':'16 passed','source_sha256':hashlib.sha256((CANONICAL/rel).read_bytes()).hexdigest(),'public_release_status':'v1.3.0 unchanged; password correction not yet published'}
receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
print('Verified password prompt correction deployed locally.')
