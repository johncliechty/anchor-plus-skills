"""Root-owned targeted recheck after recorded fixture repairs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909/anchor')
PTY = Path('C:/dev/plans/2026-07-review/pty-launch.py')
receipt = HERE / 'release-recheck-2026-09-09.json'
log = HERE / 'release-recheck-2026-09-09.log'
if receipt.exists() or log.exists():
    raise RuntimeError('Named recheck already exists')
tests = ['test_chatgpt_terminal_2026_09_05.py', 'test_distro_scan_v12.py',
         'test_foundry_runner_skills_w4.py', 'test_healthcheck_model_defaults.py',
         'test_share_roster_scrub_w2.py', 'test_stub_model_policy_2026_09_08.py']
command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '--basetemp',
           str(ROOT.parent / 'pytest-recheck02'), *['tests/' + p for p in tests]]
environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
for name in ('ANCHOR_TRIO_DIR', 'ANCHOR_FOUNDRY_DIR', 'ANCHOR_GANDALF_DIR', 'ANCHOR_ECGBERHT_DIR'):
    environment.pop(name, None)
record = dict(started=datetime.now(timezone.utc).isoformat(), status='running',
              cwd=str(ROOT), command=command, supervisor_pid=os.getpid())
receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
child = subprocess.Popen([sys.executable, str(PTY), str(log), subprocess.list2cmdline(command)],
                         cwd=ROOT, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
record['child_pid'] = child.pid
receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
record['exit_code'] = child.wait()
record.update(status='passed' if record['exit_code'] == 0 else 'failed',
              ended=datetime.now(timezone.utc).isoformat())
receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
