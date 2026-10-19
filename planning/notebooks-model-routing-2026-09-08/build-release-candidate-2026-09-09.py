"""Root-owned gated build and collaborator checks from clean committed snapshots."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909').resolve()
ANCHOR = ROOT / 'anchor'
attempt = sys.argv[1] if len(sys.argv) > 1 else '01'
if attempt not in ('01', '02', '03', '04', '05', '06', '07', '08'):
    raise RuntimeError('Unknown bounded candidate attempt')
OUT = ROOT / ('package-candidate-' + attempt)
PTY = Path('C:/dev/plans/2026-07-review/pty-launch.py')
suffix = '' if attempt == '01' else '-' + attempt
receipt = HERE / ('release-package-candidate' + suffix + '-2026-09-09.json')
if OUT.exists() or receipt.exists() or OUT.parent.resolve() != ROOT:
    raise RuntimeError('Fresh owned output path required')
environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
    PYTHONDONTWRITEBYTECODE='1', ANCHOR_SHIP_OUT=str(OUT),
    ANCHOR_TRIO_DIR=str(ROOT / 'trio'), ANCHOR_FOUNDRY_DIR=str(ROOT / 'foundry'),
    ANCHOR_GANDALF_DIR=str(ROOT / 'foundry'), ANCHOR_ECGBERHT_DIR=str(ROOT / 'ecgberht'))
environment.pop('ANCHOR_DATA_DIR', None)
package = OUT / 'clean-ship' / 'B-anchor-plus-skills'
jobs = [
    ('build', [sys.executable, 'planning/share-anchor-skills-2026-07/_build_clean_ship.py']),
    ('freeze-check', [sys.executable, '-m', 'pytest', '-q', '--tb=short',
         '--basetemp', str(ROOT / ('pytest-freeze-' + attempt)), 'tests/test_share_sources_publish_w3.py',
         'tests/test_share_package_a_w4.py', 'tests/test_share_package_b_w5.py']),
    ('stranger', [sys.executable, 'tools/share_sandbox.py', '--scratch', str(ROOT / ('stranger-' + attempt)), '--keep']),
    ('pull', [sys.executable, 'tools/pull_dry_run.py', '--package', str(package), '--keep']),
]
record = dict(started=datetime.now(timezone.utc).isoformat(), status='running',
              supervisor_pid=os.getpid(), output=str(OUT), package=str(package), gates=[])
def save():
    receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
save()
for name, command in jobs:
    log = HERE / ('release-package-' + name + suffix + '-2026-09-09.log')
    if log.exists():
        raise RuntimeError('Gate log already exists')
    gate = dict(name=name, cwd=str(ANCHOR), command=command, log=str(log),
                started=datetime.now(timezone.utc).isoformat())
    record['gates'].append(gate)
    child = subprocess.Popen([sys.executable, str(PTY), str(log), subprocess.list2cmdline(command)],
                             cwd=ANCHOR, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    gate['child_pid'] = child.pid
    save()
    gate.update(exit_code=child.wait(), ended=datetime.now(timezone.utc).isoformat())
    save()
    if gate['exit_code']:
        with (HERE / 'SETUP-2026-09-09.md').open('a', encoding='utf-8') as handle:
            handle.write('\n' + datetime.now(timezone.utc).isoformat() + ': Package gate '+name+' failed; source/publication remain held; inspect '+log.name+'.\n')
        break
record.update(status='passed' if len(record['gates']) == len(jobs) and all(g['exit_code']==0 for g in record['gates']) else 'failed',
              ended=datetime.now(timezone.utc).isoformat())
save()
