"""Prepare a patch release for the verified password confirmation correction."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909/anchor')
receipt=HERE/'password-patch-source-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Patch release already prepared')
gate=json.loads((HERE/'installer-correction-tests-04-2026-09-09.json').read_text())
review=json.loads((HERE/'grok-password-fix-2026-09-09.json').read_text())
assert gate['status']=='passed' and review['status']=='reviewed' and review['review']['verdict']=='no_material_findings_in_scope'
assert hashlib.sha256((ROOT/'tools/setup_notebooks.ps1').read_text(encoding='utf-8-sig').encode()).hexdigest()==review['source_sha256']
def git(*args): return subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
assert git('branch','--show-current')=='release/notebooks-share-20260909'
old={}
for name in ('VERSION','pyproject.toml','CHANGELOG.md','USER-ONBOARD.md','share_sources_pin.json','share_freeze_manifest.json'):
    old[name]=(ROOT/name).read_text(encoding='utf-8')
assert old['VERSION'].strip()=='1.3.0'
(ROOT/'VERSION').write_text('1.3.1\n',encoding='utf-8')
assert old['pyproject.toml'].count('version = "1.3.0"')==1
(ROOT/'pyproject.toml').write_text(old['pyproject.toml'].replace('version = "1.3.0"','version = "1.3.1"'),encoding='utf-8')
entry='## v1.3.1 — Retry notebook password confirmation\n\nThe Windows notebook installer now explains the minimum password length and lets the user retry short or mismatched entries without restarting dependency preparation. Secure input is disposed after every attempt; dependency failures still stop setup.\n\nRemaining limits: Installation and authenticated Python/R, browser, and recovery acceptance are required on each host before notebook links are enabled.\n\n'
assert old['CHANGELOG.md'].startswith('# Changelog\n\n')
(ROOT/'CHANGELOG.md').write_text(old['CHANGELOG.md'].replace('# Changelog\n\n','# Changelog\n\n'+entry,1),encoding='utf-8')
(ROOT/'USER-ONBOARD.md').write_text(old['USER-ONBOARD.md'].replace('(v1.3.0, Package A / B)','(v1.3.1, Package A / B)',1),encoding='utf-8')
git('add','--','VERSION','pyproject.toml','CHANGELOG.md','USER-ONBOARD.md','tools/setup_notebooks.ps1','tests/test_notebook_password_retry_2026_09_09.py')
git('commit','-m','Let notebook password confirmation retry without restarting setup')
content=git('rev-parse','HEAD')
pin=json.loads(old['share_sources_pin.json'])
for item in pin['pins']:
    if item['repo']=='anchor': item.update(tag='v1.3.1',commit=content[:12])
pin['package_versions']={'A':'1.3.1','B':'1.3.1'}
pin['ship_allowed_stamp_text']='Publication authorized for the scrubbed notebook maintenance release; distribution gates remain required.'
(ROOT/'share_sources_pin.json').write_text(json.dumps(pin,indent=2)+'\n',encoding='utf-8')
freeze=json.loads(old['share_freeze_manifest.json'])
freeze['freeze_commits']['anchor']=content[:12];freeze['freeze_tags']['anchor']='v1.3.1';freeze['package_matrix_version']='1.3.1'
freeze['notes']='v1.3.1 password-confirmation correction. Anchor pins the preceding content commit. Bundled skills retain their verified v1.3.0 source commits; per-host notebook activation remains required.'
(ROOT/'share_freeze_manifest.json').write_text(json.dumps(freeze,indent=2)+'\n',encoding='utf-8')
git('add','--','share_sources_pin.json','share_freeze_manifest.json');git('commit','-m','Freeze v1.3.1 notebook installer patch')
assert not git('status','--porcelain')
record={'at':datetime.now(timezone.utc).isoformat(),'version':'1.3.1','content_commit':content,'freeze_commit':git('rev-parse','HEAD'),'status':'committed_clean'}
receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
# Canonical version/guide files have not been edited since the preceding freeze.
for name,prior in old.items():
    canonical=Path('C:/dev/Anchor')/name
    assert canonical.read_text(encoding='utf-8')==prior,name
    canonical.write_bytes((ROOT/name).read_bytes())
print('v1.3.1 source committed; unchanged skill pins preserved.')
