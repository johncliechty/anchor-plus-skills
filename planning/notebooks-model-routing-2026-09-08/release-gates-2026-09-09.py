"""Private bounded source gates, launched by root under the existing ConPTY helper."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PTY = Path('C:/dev/plans/2026-07-review/pty-launch.py')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('group', choices=['anchor', 'skills'])
    args = parser.parse_args()
    snapshot = json.loads((HERE / 'release-source-snapshot-2026-09-09.json').read_text(encoding='utf-8'))
    jobs = []
    repos = snapshot['repositories']
    if args.group == 'anchor':
        root = Path(repos['anchor']['worktree'])
        tests = {r['path'] for r in repos['anchor']['selected'] if r['path'].startswith('tests/test_') and r['path'].endswith('.py')}
        tests.update(['tests/test_distro_startup_gate_2026_07_26.py', 'tests/test_distro_host_path.py',
            'tests/test_distro_scan_v12.py', 'tests/test_share_sources_publish_w3.py',
            'tests/test_share_package_a_w4.py', 'tests/test_share_package_b_w5.py',
            'tests/test_share_roster_scrub_w2.py', 'tests/test_share_feedback_w6.py',
            'tests/test_doctor_resolve_all_2026_09_03.py'])
        temporary = Path(snapshot['destination']) / 'pytest-gate01'
        jobs.append(('anchor', root, [sys.executable, '-m', 'pytest', '-q', '--tb=short',
                    '--basetemp', str(temporary), *sorted(tests)]))
    else:
        for name in ('trio', 'foundry', 'ecgberht'):
            root = Path(repos[name]['worktree'])
            tests = [r['path'] for r in repos[name]['selected'] if r['path'].endswith('.test.mjs')]
            if tests:
                jobs.append((name, root, ['node', '--test', '--test-concurrency=2', *tests]))
    receipt = {'started': datetime.now(timezone.utc).isoformat(), 'status': 'running',
               'supervisor_pid': os.getpid(), 'group': args.group, 'gates': []}
    result_path = HERE / ('release-gate-' + args.group + '-2026-09-09.json')
    def save():
        result_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    save()
    for name, cwd, command in jobs:
        log = HERE / ('release-gate-' + name + '-2026-09-09.log')
        if log.exists():
            raise RuntimeError('Gate log exists; use a named recovery gate, never overwrite')
        entry = {'repository': name, 'cwd': str(cwd), 'log': str(log), 'command': command,
                 'started': datetime.now(timezone.utc).isoformat()}
        receipt['gates'].append(entry)
        save()
        environment = dict(os.environ)
        environment['PYTHONUTF8'] = '1'
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['ANCHOR_TRIO_DIR'] = repos['trio']['worktree']
        environment['ANCHOR_FOUNDRY_DIR'] = repos['foundry']['worktree']
        environment['ANCHOR_GANDALF_DIR'] = repos['foundry']['worktree']
        environment['ANCHOR_ECGBERHT_DIR'] = repos['ecgberht']['worktree']
        child = subprocess.Popen([sys.executable, str(PTY), str(log), subprocess.list2cmdline(command)],
            cwd=cwd, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        entry['pty_pid'] = child.pid
        save()
        entry['exit_code'] = child.wait()
        entry['ended'] = datetime.now(timezone.utc).isoformat()
        save()
    receipt['status'] = 'passed' if all(g.get('exit_code') == 0 for g in receipt['gates']) else 'failed'
    receipt['ended'] = datetime.now(timezone.utc).isoformat()
    save()
    return 0 if receipt['status'] == 'passed' else 1

if __name__ == '__main__':
    raise SystemExit(main())
