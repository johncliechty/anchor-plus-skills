"""Root-owned privacy regression gate and exported-manifest structural check."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
attempt = sys.argv[1] if len(sys.argv) > 1 else '01'
assert attempt in ('01', '02', '03')
receipt = HERE / ('privacy-release-tests-' + attempt + '-2026-09-10.json')
assert not receipt.exists()
record = {'started': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'pid': os.getpid()}
def save(): receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
save()
try:
    command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '--basetemp', str(ROOT / ('pytest-privacy-' + attempt)),
               'tests/test_share_escaped_paths_2026_09_10.py', 'tests/test_vendor_skills.py',
               'tests/test_distro_scan.py', 'tests/test_distro_scan_v7.py', 'tests/test_distro_host_path.py',
               'tests/test_share_governance_w4.py']
    log = HERE / ('privacy-release-tests-' + attempt + '-2026-09-10.log')
    child = subprocess.Popen([sys.executable, 'C:/dev/plans/2026-07-review/pty-launch.py', str(log), subprocess.list2cmdline(command)],
        cwd=ROOT / 'anchor', env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'), creationflags=subprocess.CREATE_NO_WINDOW)
    record['child_pid'] = child.pid; save()
    record['exit_code'] = child.wait(); save()
    assert record['exit_code'] == 0, 'Privacy regression gate failed'
    sys.path.insert(0, str(ROOT / 'anchor'))
    import vendor_skills
    import distro
    exported = ROOT / ('privacy-manifest-' + attempt)
    exported.mkdir()
    path = exported / 'tools.manifest.json'
    shutil.copyfile(ROOT / 'foundry/skills/ramanujan/tools.manifest.json', path)
    vendor_skills._scrub_file(path)
    assert not list(distro._scan_text(path.name, path.read_text(encoding='utf-8')))
    script = "import {loadManifest, validateManifest} from './skills/ramanujan/src/phasef-probe.mjs'; const result=validateManifest(loadManifest(process.argv[1])); console.log(JSON.stringify(result)); if(!result.ok)process.exit(1);"
    result = subprocess.run(['node', '--input-type=module', '-e', script, str(path)], cwd=ROOT / 'foundry', capture_output=True, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    record['manifest'] = {'exit_code': result.returncode, 'output': result.stdout, 'error': result.stderr}
    assert result.returncode == 0, 'Exported manifest validation failed'
    record['status'] = 'passed'
except Exception as exc:
    record.update(status='failed', error=str(exc))
finally:
    record['ended'] = datetime.now(timezone.utc).isoformat(); save()
    with (HERE / 'SETUP-2026-09-09.md').open('a', encoding='utf-8') as h:
        h.write('\n' + record['ended'] + ': Privacy regression and manifest gate ' + record['status'] + '; see ' + receipt.name + '.\n')
