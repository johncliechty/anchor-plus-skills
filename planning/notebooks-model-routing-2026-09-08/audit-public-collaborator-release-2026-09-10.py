"""Read-only audit of the public distribution, including all advertised refs."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
MIRROR = ROOT / 'public-privacy-audit-20260910.git'
SOURCE = ROOT / 'anchor'
RECEIPT = HERE / 'public-privacy-audit-2026-09-10.json'
if RECEIPT.exists() or MIRROR.exists():
    raise RuntimeError('Fresh owned audit paths required')
record = dict(started=datetime.now(timezone.utc).isoformat(),status='running',repository='https://github.com/johncliechty/anchor-plus-skills',stages=[])
def save():
    RECEIPT.write_text(json.dumps(record,indent=2),encoding='utf-8')
def git(*args, cwd=MIRROR):
    r = subprocess.run(['git',*args],cwd=cwd,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=300)
    if r.returncode:
        raise RuntimeError('Git audit operation failed: '+args[0])
    return r.stdout
save()
try:
    git('clone','--mirror',record['repository']+'.git',str(MIRROR),cwd=ROOT)
    record['stages'].append('fresh_public_mirror_fetched');save()
    record['refs'] = git('for-each-ref','--format=%(refname) %(objectname)').decode().splitlines()
    record['head'] = git('rev-parse','refs/heads/main').decode().strip()
    record['version'] = git('show','refs/heads/main:VERSION').decode().strip()
    record['commit_count'] = int(git('rev-list','--all','--count'))
    log = git('log','--all','--format=%an <%ae> | %cn <%ce>').decode().splitlines()
    record['public_commit_identities'] = sorted(set(log))
    commits = git('rev-list','--all').decode().splitlines()
    pairs = {}
    current = {}
    all_paths = set()
    binary_suffixes = {'.png','.ico','.jpg','.jpeg','.gif','.pdf','.woff','.woff2','.ttf','.eot','.zip','.7z','.exe','.dll'}
    current_binary = []
    for commit in commits:
        entries = git('ls-tree','-r','-z',commit).split(b'\0')
        for entry in entries:
            if not entry:
                continue
            metadata,path = entry.split(b'\t',1)
            mode,kind,oid = metadata.decode().split()
            path = path.decode('utf-8')
            if kind != 'blob':
                raise RuntimeError('Unexpected non-blob payload')
            pairs[(oid,path)] = True
            all_paths.add(path)
            if commit == record['head']:
                current[path]=oid
                if Path(path).suffix.lower() in binary_suffixes:
                    current_binary.append(path)
    record['current_files'] = len(current)
    record['historical_paths'] = len(all_paths)
    record['blob_path_versions'] = len(pairs)
    record['binary_inventory'] = sorted(current_binary)
    sys.path.insert(0,str(SOURCE))
    import distro
    blobs = {}
    findings = []
    markers = []
    personal_patterns = {
        'private_host_or_tailnet': re.compile(r'gwl-server|tailb49f65',re.I),
        'actual_user_profile': re.compile(r'(?:[a-z]:[\\/]+Users[\\/]+john(?:[\\/]|\b)|/home/john(?:/|\b))',re.I),
        'private_teaching_tree': re.compile(r'[a-z]:[\\/]+dev[\\/]+Teaching(?:[\\/]|\b)',re.I),
        'actual_notebook_account_sid': re.compile(r'S-1-5-21-2519451599-2226736531-398949285-1008'),
    }
    name_hits = Counter()
    nontext = set()
    for oid,path in pairs:
        if oid not in blobs:
            blobs[oid] = git('cat-file','blob',oid)
        content = blobs[oid]
        is_current = current.get(path)==oid
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            nontext.add((oid,path))
            continue
        for _,category,_ in list(distro._scan_text(path,text))+list(distro._scan_registry_artifact(path,text)):
            findings.append(dict(path=path,blob=oid,category=category,current=is_current))
        for category,pattern in personal_patterns.items():
            if pattern.search(text):
                markers.append(dict(path=path,blob=oid,category=category,current=is_current))
        if is_current and re.search(r'\b(?:John|Liechty)\b',text,re.I):
            name_hits[path] += len(re.findall(r'\b(?:John|Liechty)\b',text,re.I))
    record['unique_blobs_scanned'] = len(blobs)
    record['nontext_blob_paths'] = len(nontext)
    record['scanner_findings'] = findings
    record['private_marker_findings'] = markers
    record['author_name_mentions_current'] = dict(name_hits)
    suspicious = re.compile(r'(^|/)(?:\.anchor|\.ecgberht|\.env|planning|journal/runs|logs|session|sessions)(/|$)|(^|/)(?:DASHBOARD\.md|settings\.json|notebook-runtime\.json|registry\.json|tasks\.json)$|\.(?:ipynb|rmd|rdata|rds|sqlite|db|csv|xlsx|docx|pptx)$',re.I)
    record['data_shaped_paths'] = [dict(path=p,current=p in current) for p in sorted(all_paths) if suspicious.search(p)]
    expected = json.loads((HERE/'published-release-v1.3.1-2026-09-09.json').read_text())
    record['matches_last_verified_release'] = record['head']==expected['commit'] and len(current)==expected['files']
    record['status'] = 'requires_finding_review' if findings or markers else 'text_scans_passed_inventory_review_pending'
    record['ended'] = datetime.now(timezone.utc).isoformat();save()
except Exception as e:
    record.update(status='failed',error_type=type(e).__name__,error=str(e),ended=datetime.now(timezone.utc).isoformat());save()
    raise
