"""Read-only bounded census of this installation's accessible runtime trees."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
receipt = HERE / 'notebook-runtime-tree-counts-2026-09-10.json'
if receipt.exists():
    raise RuntimeError('Census already has a receipt')
base = Path('C:/Users/john/AppData/Local/Programs/Python/Python313')
roots = [base/'Lib', base/'DLLs', Path('C:/Users/john/AppData/Local/Programs/R'), Path('C:/Users/john/AppData/Local/R/win-library/4.6')]
record = dict(at=datetime.now(timezone.utc).isoformat(), status='running', roots=[])
def save():
    receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
save()
for root in roots:
    item = dict(path=str(root), files=0, directories=0, skipped_reparse=0, errors=0, complete=True)
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            info = directory.stat(follow_symlinks=False)
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                item['skipped_reparse'] += 1
                continue
            item['directories'] += 1
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if path == base/'Lib/site-packages':
                        continue
                    if entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        item['skipped_reparse'] += 1
                    elif entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    else:
                        item['files'] += 1
        except OSError:
            item['errors'] += 1
        if item['files'] + item['directories'] > 200000:
            item['complete'] = False
            break
    record['roots'].append(item)
    save()
record['status'] = 'counted_accessible_trees_only'
record['protected_venv'] = 'not_inspected_nonadmin'
record['ended'] = datetime.now(timezone.utc).isoformat()
save()
