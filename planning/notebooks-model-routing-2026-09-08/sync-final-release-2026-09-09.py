"""Copy only this cycle's verified corrections; preserve concurrent source edits/indexes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
snapshot=json.loads((HERE/'release-source-snapshot-2026-09-09.json').read_text())
receipt=HERE/'release-final-canonical-sync-2026-09-09.json'
if receipt.exists(): raise RuntimeError('Final sync already attempted')
paths={'anchor':['tools/setup_notebooks.ps1','tools/install_notebook_startup.ps1','docs/notebook-host-setup.md',
 'tests/test_notebook_setup_preflight_2026_09_09.py','tests/test_notebook_startup_membership_2026_09_09.py',
 'CHANGELOG.md','tools/publish_share_repo.py','distro.py','USER-ONBOARD.md','planning/share-v1.2/AGENTS.md',
 'VERSION','pyproject.toml','share_sources_pin.json','share_freeze_manifest.json'],
 'trio':['foreman/LESSONS.md','foreman/CHANGELOG.md'],
 'foundry':['skills/jumper/LESSONS.md','skills/jumper/CHANGELOG.md','skills/ramanujan/LESSONS.md','skills/ramanujan/CHANGELOG.md'],
 'ecgberht':['LESSONS.md','CHANGELOG.md']}
def sha(data): return hashlib.sha256(data).hexdigest()
record={'at':datetime.now(timezone.utc).isoformat(),'copied':[],'already_current':[],'preserved_concurrent':[]}
for name,files in paths.items():
    meta=snapshot['repositories'][name];canonical=Path(meta['source'])
    selected={p['path']:p['sha256'] for p in meta['selected']}
    for rel in files:
        src=ROOT/name/rel;dst=canonical/rel
        new=src.read_bytes();old=dst.read_bytes() if dst.exists() else None
        if old==new: record['already_current'].append(str(dst));continue
        if rel in selected:
            safe=old is not None and sha(old)==selected[rel]
        else:
            prior=subprocess.run(['git','-C',str(ROOT/name),'show',meta['base_commit']+':'+rel],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            safe=(old is None and prior.returncode!=0) or (old is not None and prior.returncode==0 and old.replace(b'\r\n',b'\n')==prior.stdout.replace(b'\r\n',b'\n'))
        if not safe:
            record['preserved_concurrent'].append(str(dst));continue
        # Re-check immediately before the write. No staging or index operation.
        assert (dst.read_bytes() if dst.exists() else None)==old
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        record['copied'].append({'path':str(dst),'sha256':sha(new)})
sourceJournal=ROOT/'foundry/planning/anchor-notebooks-policy-2026-09-08/journal'
destJournal=Path(snapshot['repositories']['foundry']['source'])/'planning/anchor-notebooks-policy-2026-09-08/journal'
for src in sourceJournal.rglob('*'):
    if not src.is_file(): continue
    dst=destJournal/src.relative_to(sourceJournal)
    if dst.exists(): raise RuntimeError('Canonical maintenance journal already exists')
    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
record['journal']=str(destJournal)
receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps({key:len(record[key]) for key in ('copied','already_current','preserved_concurrent')}))
