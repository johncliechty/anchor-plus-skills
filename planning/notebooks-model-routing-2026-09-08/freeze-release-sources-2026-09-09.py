"""Commit only the authorized product snapshot; never alter source indexes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
snapshot = json.loads((HERE / 'release-source-snapshot-2026-09-09.json').read_text(encoding='utf-8'))
ROOT = Path(snapshot['destination']).resolve()
record_path = HERE / 'release-source-commits-2026-09-09.json'
if record_path.exists():
    raise RuntimeError('Source freeze exists; inspect before any recovery')
repos = snapshot['repositories']
extra = {
    'anchor': ['VERSION', 'CHANGELOG.md', 'tools/publish_share_repo.py',
               'tests/test_distro_scan_v12.py', 'tests/test_share_roster_scrub_w2.py',
               'tests/test_model_policy_cache_renewal_2026_09_09.py'],
    'trio': ['drivers/test/model-policy-cache-renewal-2026-09-09.test.mjs'],
    'foundry': [], 'ecgberht': [],
}
excluded = {'foundry_skills.py', 'steward_cockpit/static/skill-icons.js'}

def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=120,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Git ' + args[0] + ' failed: ' + result.stderr[-1800:])
    return result.stdout.strip()

record = {'started': datetime.now(timezone.utc).isoformat(), 'status':'freezing', 'repositories':{}}
def save():
    record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
save()
for name in ('trio', 'foundry', 'ecgberht', 'anchor'):
    info = repos[name]
    root = Path(info['worktree']).resolve()
    if root.parent != ROOT or not (root / '.git').is_file():
        raise RuntimeError('Worktree containment not proven')
    if git(root, 'rev-parse', 'HEAD') != info['base_commit']:
        raise RuntimeError('Snapshot HEAD changed before freeze: ' + name)
    selected = {r['path'] for r in info['selected']} | set(extra[name])
    if name == 'anchor':
        selected -= excluded
    missing = [p for p in selected if not (root / p).is_file()]
    if missing:
        raise RuntimeError('Missing source selection: ' + str(missing))
    git(root, 'add', '--', *sorted(selected))
    staged = git(root, 'diff', '--cached', '--name-only').splitlines()
    if not set(staged).issubset(selected):
        raise RuntimeError('Unexpected staged paths in isolated release')
    git(root, 'commit', '-m', 'Prepare v1.3.0 model policy and notebook work products')
    sha = git(root, 'rev-parse', 'HEAD')
    record['repositories'][name] = {'content_commit':sha, 'worktree':str(root),
        'branch':git(root, 'branch', '--show-current'), 'changed_paths':staged}
    save()

# The Anchor content pin precedes the freeze-record commit, avoiding a self-reference.
anchor = Path(repos['anchor']['worktree'])
names = {'anchor':'anchor', 'trio':'trio', 'skill-foundry':'foundry'}
commits = {key:record['repositories'][value]['content_commit'] for key,value in names.items()}
source = json.loads((anchor / 'share_sources_pin.json').read_text(encoding='utf-8'))
source.update(ship_allowed=True,
              ship_allowed_stamp_text='Publication authorized for the scrubbed v1.3.0 collaborator release on 2026-09-09; distribution gates remain required.',
              skills_pin={'tag':'v1.3.0','commit':commits['skill-foundry']},
              pins=[{'repo':key,'tag':'v1.3.0','commit':value} for key,value in commits.items()],
              package_versions={'A':'1.3.0','B':'1.3.0'})
freeze = json.loads((anchor / 'share_freeze_manifest.json').read_text(encoding='utf-8'))
freeze.update(ship_allowed=True, freeze_commits=commits,
              freeze_tags={key:'v1.3.0' for key in commits}, skills_pin=source['skills_pin'],
              package_matrix_version='1.3.0',
              notes='v1.3.0 source freeze. Anchor pins the content commit immediately before this freeze record. Ecgberht source commit '+record['repositories']['ecgberht']['content_commit']+'. Notebook activation and per-host acceptance remain explicit setup requirements.')
for filename, value in [('share_sources_pin.json',source),('share_freeze_manifest.json',freeze)]:
    (anchor / filename).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
git(anchor,'add','--','share_sources_pin.json','share_freeze_manifest.json')
git(anchor,'commit','-m','Freeze v1.3.0 source pins for collaborator export')
record['repositories']['anchor']['freeze_commit'] = git(anchor,'rev-parse','HEAD')
for name, info in record['repositories'].items():
    root = Path(info['worktree'])
    if git(root,'status','--porcelain'):
        raise RuntimeError('Snapshot is not clean after freeze: '+name)
record.update(status='committed_clean', ended=datetime.now(timezone.utc).isoformat())
save()
print(json.dumps({name:info.get('freeze_commit',info['content_commit']) for name,info in record['repositories'].items()}))
