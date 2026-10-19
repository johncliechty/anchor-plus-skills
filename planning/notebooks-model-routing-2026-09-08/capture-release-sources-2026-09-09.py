"""Private release snapshot: explicit product paths, no source/index mutations."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
DEST = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'anchor-release-20260909'
ROOTS = {'anchor': Path('C:/dev/Anchor'), 'trio': Path('C:/dev/trio'),
         'foundry': Path('C:/dev/Skill Foundry'), 'ecgberht': Path('C:/dev/Ecgberht')}

def git(root, *args):
    result = subprocess.run(['git', '-c', 'core.safecrlf=false', '-C', str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    return result.stdout.decode('utf-8')

def product(repo, name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid git path')
    if repo == 'anchor':
        if name in {'pyproject.toml', 'dist_manifest.txt', 'docs/notebook-host-setup.md',
                    'docs/notebook-work-products.md', 'tools/setup_notebooks.ps1',
                    'tools/install_notebook_startup.ps1'}:
            return True
        if len(path.parts) == 1 and path.suffix == '.py':
            return True
        return (path.parts[0] in {'static', 'steward_cockpit', 'tests'}
                and path.suffix in {'.py', '.js', '.css', '.html', '.json'})
    if repo == 'trio':
        return ((path.parts[0] == 'drivers' or name.startswith('foreman/bin/')
                 or name.startswith('foreman/test/'))
                and path.suffix in {'.mjs', '.js', '.json'}) or name == 'foreman/SKILL.md'
    if repo == 'foundry':
        return name in {'AGENTS.md', 'skills/jumper/SKILL.md', 'skills/ramanujan/SKILL.md',
                        'skills/ramanujan/tools.manifest.json'} or (
            name.startswith(('skills/ramanujan/src/', 'skills/ramanujan/test/'))
            and path.suffix == '.mjs')
    return name == 'SKILL.md' or (path.parts[0] in {'engine', 'scripts', 'test'}
                                  and path.suffix == '.mjs')

def main():
    if DEST.exists():
        raise RuntimeError('Snapshot destination already exists; inspect before reuse')
    DEST.mkdir(parents=True)
    manifest = {'destination': str(DEST), 'repositories': {}}
    for name, source in ROOTS.items():
        if Path(git(source, 'rev-parse', '--show-toplevel').strip()).resolve() != source.resolve():
            raise RuntimeError('Unexpected repository root')
        head = git(source, 'rev-parse', 'HEAD').strip()
        staged_before = git(source, 'diff', '--cached', '--name-only', '-z')
        changed = set(git(source, 'diff', 'HEAD', '--name-only', '-z').split('\0'))
        changed.update(git(source, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
        selected = sorted(p for p in changed if p and product(name, p))
        target = DEST / name
        git(source, 'worktree', 'add', '-b', 'release/notebooks-share-20260909', str(target), head)
        copied = []
        for relative in selected:
            origin, destination = source / relative, target / relative
            if not origin.is_file() or origin.is_symlink():
                raise RuntimeError('Selected source is absent or linked; inspect explicitly')
            before = hashlib.sha256(origin.read_bytes()).hexdigest()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
            after = hashlib.sha256(origin.read_bytes()).hexdigest()
            if before != after or hashlib.sha256(destination.read_bytes()).hexdigest() != before:
                raise RuntimeError('Source changed during capture')
            copied.append({'path': relative, 'sha256': before})
        if staged_before != git(source, 'diff', '--cached', '--name-only', '-z'):
            raise RuntimeError('Source index changed during capture; reconcile ownership')
        manifest['repositories'][name] = {'source': str(source), 'worktree': str(target),
            'base_commit': head, 'selected': copied, 'source_staged_paths': staged_before.split('\0')}
        (HERE / 'release-source-snapshot-2026-09-09.json').write_text(
            json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps({'repository': name, 'copied_product_files': len(copied),
                          'source_index_preserved': True}), flush=True)
    print('Product snapshots prepared; no source files committed or pushed.', flush=True)

if __name__ == '__main__':
    main()
