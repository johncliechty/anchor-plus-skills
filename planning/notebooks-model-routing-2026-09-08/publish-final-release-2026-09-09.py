"""Publish only the reviewed scrubbed tree, then verify a fresh remote clone."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909').resolve()
VERSION=sys.argv[1] if len(sys.argv)>1 else '1.3.0'
if VERSION not in ('1.3.0','1.3.1','1.3.2'): raise RuntimeError('Unknown bounded release version')
TAG='v'+VERSION
SUFFIX='' if VERSION=='1.3.0' else '-v'+VERSION
ATTEMPT={'1.3.0':'04','1.3.1':'06','1.3.2':'07'}[VERSION]
SOURCE=ROOT/('package-candidate-'+ATTEMPT+'/clean-ship/B-anchor-plus-skills')
WORK=ROOT/('collaborator-final-repo'+SUFFIX)
CLONE=ROOT/('published-clone-'+TAG)
URL='https://github.com/johncliechty/anchor-plus-skills.git'
receipt=HERE/('published-release'+SUFFIX+'-2026-09-09.json')
if receipt.exists() or CLONE.exists() or WORK.exists(): raise RuntimeError('Publication receipt and owned clones must be new')
gate=json.loads((HERE/('release-package-candidate-'+ATTEMPT+'-2026-09-09.json')).read_text())
assert gate['status']=='passed'
assert SOURCE.resolve().is_relative_to(ROOT) and WORK.resolve().parent==ROOT
record=dict(started=datetime.now(timezone.utc).isoformat(),status='preparing',source=str(SOURCE),url=URL,gates=[])
def save(): receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
def run(args,cwd=None):
    return subprocess.run(args,cwd=cwd,capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
def git(*args,cwd=WORK): return run(['git',*args],cwd)
def phase(name,args,cwd):
    log=HERE/('publication-'+name+SUFFIX+'-2026-09-09.log')
    if log.exists(): raise RuntimeError('Publication phase log already exists')
    item={'name':name,'started':datetime.now(timezone.utc).isoformat(),'log':str(log)}
    record['gates'].append(item);save()
    child=subprocess.Popen([sys.executable,'C:/dev/plans/2026-07-review/pty-launch.py',str(log),subprocess.list2cmdline(args)],cwd=cwd,
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW)
    item['pid']=child.pid;save();item['exit_code']=child.wait();item['ended']=datetime.now(timezone.utc).isoformat();save()
    if item['exit_code']: raise RuntimeError('Publication phase failed: '+name)
save()
try:
    git('clone','--single-branch','--branch','main',URL,str(WORK),cwd=ROOT)
    assert git('remote','get-url','origin')==URL
    assert not git('status','--porcelain')
    assert not git('ls-remote','--tags','origin','refs/tags/'+TAG)
    phase('prepare',[sys.executable,'tools/publish_share_repo.py','--source',str(SOURCE),'--work',str(WORK),'--no-push'],ROOT/'anchor')
    assert not git('status','--porcelain')
    commit=git('rev-parse','HEAD');assert git('rev-parse',TAG)==commit
    tracked=git('ls-files').splitlines()
    sourceFiles={p.relative_to(SOURCE).as_posix():p for p in SOURCE.rglob('*') if p.is_file()}
    assert set(tracked)==set(sourceFiles)
    for name,path in sourceFiles.items(): assert (WORK/name).read_bytes()==path.read_bytes(),name
    assert (SOURCE/'VERSION').read_text().strip()==VERSION
    if VERSION == '1.3.2':
        sys.path.insert(0, str(ROOT/'anchor'))
        import distro
        private_markers = re.compile(r'gwl-server|tailb49f65|john\.liechty|S-1-5-21-2519451599-2226736531-398949285-1008', re.I)
        checked = 0
        for name,path in sourceFiles.items():
            try: text = path.read_bytes().decode('utf-8')
            except UnicodeDecodeError: continue
            assert not list(distro._scan_text(name, text)), 'Privacy scan: ' + name
            assert not list(distro._scan_registry_artifact(name, text)), 'Private state: ' + name
            assert not private_markers.search(text), 'Known private marker: ' + name
            checked += 1
        record['current_release_privacy'] = {'text_files_checked': checked, 'scanner_findings': 0, 'known_private_marker_findings': 0, 'historical_identifiers_remain': True}
    record.update(status='prepared_verified',commit=commit,files=len(tracked));save()
    # Confirm the destination again immediately before the already-authorized push.
    assert not git('ls-remote','--tags','origin','refs/tags/'+TAG)
    git('push','--atomic','origin','HEAD:refs/heads/main','refs/tags/'+TAG+':refs/tags/'+TAG)
    record.update(status='pushed',pushed=datetime.now(timezone.utc).isoformat());save()
    git('clone','--single-branch','--branch','main',URL,str(CLONE),cwd=ROOT)
    assert git('rev-parse','HEAD',cwd=CLONE)==commit
    assert git('rev-parse',TAG,cwd=CLONE)==commit
    cloneFiles=git('ls-files',cwd=CLONE).splitlines();assert set(cloneFiles)==set(tracked)
    for name,path in sourceFiles.items(): assert (CLONE/name).read_bytes().replace(b'\r\n',b'\n')==path.read_bytes().replace(b'\r\n',b'\n'),name
    record['clone']=str(CLONE);record['clone_files']=len(cloneFiles)
    record['skills']=len(list((CLONE/'vendor/bundled-skills').rglob('SKILL.md')));save()
    phase('remote-clone-pull',[sys.executable,'tools/pull_dry_run.py','--package',str(CLONE),'--keep'],ROOT/'anchor')
    record['status']='published_and_clone_verified'
except Exception as exc:
    record['failure']=str(exc);record['status']='pushed_verification_failed' if 'pushed' in record else 'failed_before_push'
    raise
finally:
    record['ended']=datetime.now(timezone.utc).isoformat();save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as h:
        h.write('\n'+record['ended']+': Public collaborator release '+record['status']+'; see '+receipt.name+'.\n')
