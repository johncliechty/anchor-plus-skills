"""Commit only owned release files and freeze a fresh ordinary patch release."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
A = ROOT / 'anchor'
F = ROOT / 'foundry'
receipt = HERE / 'privacy-release-source-2026-09-10.json'
assert not receipt.exists()
gate = json.loads((HERE / 'privacy-release-tests-02-2026-09-10.json').read_text())
review = json.loads((HERE / 'grok-privacy-fix-2026-09-10.json').read_text())
assert gate['status'] == 'passed'
assert review['status'] == 'reviewed' and review['review']['verdict'] == 'no_material_findings_in_scope'
def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, encoding='utf-8', check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
for repo in (A, F):
    assert git(repo, 'branch', '--show-current') == 'release/notebooks-share-20260909'
    assert not git(repo, 'diff', '--cached', '--name-only')
    assert not git(repo, 'tag', '--list', 'v1.3.2')
anchor_files = ['VERSION', 'pyproject.toml', 'CHANGELOG.md', 'USER-ONBOARD.md', 'anchor_gui.py',
    'deliverables.py', 'distro.py', 'vendor_skills.py', 'share_governance.py', 'share_ci_ship_gate.py',
    'docs/notebook-host-setup.md', 'tests/test_share_escaped_paths_2026_09_10.py',
    'tests/test_chatgpt_terminal_2026_09_05.py', 'tests/test_share_skills_root_w1.py',
    'tests/test_distro_scan.py', 'tests/test_distro_scan_v7.py', 'share_sources_pin.json', 'share_freeze_manifest.json']
foundry_files = ['skills/ramanujan/tools.manifest.json']
old = {}
for label, repo, names in [('anchor', A, anchor_files), ('foundry', F, foundry_files)]:
    old[label] = {}
    for name in names:
        result = subprocess.run(['git', '-C', str(repo), 'show', 'HEAD:' + name], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        old[label][name] = result.stdout.decode('utf-8') if result.returncode == 0 else None
assert (A / 'VERSION').read_text().strip() == '1.3.1'
(A / 'VERSION').write_text('1.3.2\n', encoding='utf-8')
text = (A / 'pyproject.toml').read_text(encoding='utf-8')
assert text.count('version = "1.3.1"') == 1
(A / 'pyproject.toml').write_text(text.replace('version = "1.3.1"', 'version = "1.3.2"'), encoding='utf-8')
text = (A / 'CHANGELOG.md').read_text(encoding='utf-8')
entry = ('## v1.3.2 — Collaborator privacy and portability correction\n\n'
    'The release scanner and skill exporter now handle JSON-escaped Windows profile paths. '
    'The dashboard uses generic host labels. Optional Ramanujan tools export valid JSON with '
    'explicit example paths that collaborators configure locally.\n\n'
    'Windows notebook startup remains under repair; skip optional notebook-host setup in this release. '
    'The core dashboard and bundled skills install independently. Older public Git history retains '
    'author machine identifiers; this ordinary patch release does not rewrite history.\n\n')
assert text.startswith('# Changelog\n\n')
(A / 'CHANGELOG.md').write_text(text.replace('# Changelog\n\n', '# Changelog\n\n' + entry, 1), encoding='utf-8')
text = (A / 'USER-ONBOARD.md').read_text(encoding='utf-8')
assert '(v1.3.1, Package A / B)' in text
(A / 'USER-ONBOARD.md').write_text(text.replace('(v1.3.1, Package A / B)', '(v1.3.2, Package A / B)', 1), encoding='utf-8')
git(F, 'add', '--', *foundry_files)
git(F, 'commit', '-m', 'Correct subscription tool manifest JSON for portable export', '--', *foundry_files)
foundry_commit = git(F, 'rev-parse', 'HEAD')
git(F, 'tag', 'v1.3.2', foundry_commit)
content_files = [name for name in anchor_files if name not in ('share_sources_pin.json', 'share_freeze_manifest.json')]
git(A, 'add', '--', *content_files)
git(A, 'commit', '-m', 'Remove host identifiers and validate escaped paths in collaborator exports', '--', *content_files)
content = git(A, 'rev-parse', 'HEAD')
pin = json.loads((A / 'share_sources_pin.json').read_text())
for item in pin['pins']:
    if item['repo'] == 'anchor': item.update(tag='v1.3.2', commit=content[:12])
    elif item['repo'] == 'skill-foundry': item.update(tag='v1.3.2', commit=foundry_commit[:12])
pin['skills_pin'] = {'tag': 'v1.3.2', 'commit': foundry_commit[:12]}
pin['package_versions'] = {'A': '1.3.2', 'B': '1.3.2'}
(A / 'share_sources_pin.json').write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
freeze = json.loads((A / 'share_freeze_manifest.json').read_text())
freeze['freeze_commits'].update(anchor=content[:12], **{'skill-foundry': foundry_commit[:12]})
freeze['freeze_tags'].update(anchor='v1.3.2', **{'skill-foundry': 'v1.3.2'})
freeze['skills_pin'] = pin['skills_pin']
freeze['package_matrix_version'] = '1.3.2'
freeze['notes'] = 'Current export privacy correction; optional Windows notebook hosting is not ready. Anchor pins the preceding content commit; unchanged Trio retains its verified source pin.'
(A / 'share_freeze_manifest.json').write_text(json.dumps(freeze, indent=2) + '\n', encoding='utf-8')
git(A, 'add', '--', 'share_sources_pin.json', 'share_freeze_manifest.json')
git(A, 'commit', '-m', 'Freeze v1.3.2 collaborator privacy patch', '--', 'share_sources_pin.json', 'share_freeze_manifest.json')
git(A, 'tag', 'v1.3.2', 'HEAD')
assert not git(A, 'status', '--porcelain') and not git(F, 'status', '--porcelain')
record = {'at': datetime.now(timezone.utc).isoformat(), 'status': 'committed_clean', 'version': '1.3.2',
          'anchor_content': content, 'anchor_freeze': git(A, 'rev-parse', 'HEAD'), 'foundry_commit': foundry_commit, 'canonical_sync': []}
receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
for label, repo, names, canonical in [('anchor', A, anchor_files, Path('C:/dev/Anchor')), ('foundry', F, foundry_files, Path('C:/dev/Skill Foundry'))]:
    for name in names:
        target = canonical / name
        before = old[label][name]
        current = target.read_text(encoding='utf-8') if target.exists() else None
        if current == before:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((repo / name).read_bytes())
            record['canonical_sync'].append({'file': label + '/' + name, 'status': 'synced'})
        elif target.exists() and target.read_bytes() == (repo / name).read_bytes():
            record['canonical_sync'].append({'file': label + '/' + name, 'status': 'already_current'})
        else:
            record['canonical_sync'].append({'file': label + '/' + name, 'status': 'preserved_concurrent_difference'})
receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
print('v1.3.2 source committed and frozen; canonical differences recorded without overwriting.')
