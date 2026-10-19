"""Copy verified repairs back only when original source bytes still match capture."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
snapshot = json.loads((HERE / 'release-source-snapshot-2026-09-09.json').read_text(encoding='utf-8'))
items = {'anchor': ['model_policy.py', 'tests/test_chatgpt_terminal_2026_09_05.py',
                    'tests/test_healthcheck_model_defaults.py', 'tests/test_model_policy_cache_renewal_2026_09_09.py'],
         'trio': ['drivers/model-policy.mjs', 'drivers/test/model-policy-cache-renewal-2026-09-09.test.mjs']}
record = []
for repo, files in items.items():
    info = snapshot['repositories'][repo]
    hashes = {r['path']:r['sha256'] for r in info['selected']}
    for name in files:
        target = Path(info['source']) / name
        content = (Path(info['worktree']) / name).read_bytes()
        if target.exists() and target.read_bytes() == content:
            record.append({'repo':repo,'path':name,'status':'already_identical'})
            continue
        if target.exists() and (name not in hashes or hashlib.sha256(target.read_bytes()).hexdigest() != hashes[name]):
            raise RuntimeError('Concurrent source edit; do not overwrite '+str(target))
        if not target.exists() and name in hashes:
            raise RuntimeError('Original captured source disappeared')
        target.write_bytes(content)
        record.append({'repo':repo,'path':name,'status':'copied_verified_repair'})
(HERE / 'release-repairs-synced-2026-09-09.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
