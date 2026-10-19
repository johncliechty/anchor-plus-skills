"""Bounded independent review of the observed provider-cache compatibility repair."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/john/AppData/Local/Temp/anchor-release-20260909')
os.environ['ANCHOR_DATA_DIR'] = 'C:/dev/Anchor'
sys.path.insert(0, str(ROOT / 'anchor'))
import anchor_settings
import model_policy
from steward_cockpit.grok_turn_bridge import GrokBroker

receipt = HERE / 'grok-catalog-renewal-2026-09-09.json'
if receipt.exists():
    raise RuntimeError('Review already exists')
sources = []
for path, start, end in [(ROOT/'anchor/model_policy.py','            from datetime import datetime, timezone','        elif family == "claude":'),
                         (ROOT/'trio/drivers/model-policy.mjs','  const version = semver(probe(family','  return normalizeCatalog(family, raw);')]:
    text = path.read_text(encoding='utf-8')
    offset = text.index(start)
    stop = text.index(end, offset)
    snippet = text[offset:stop]
    sources.append({'path':str(path.relative_to(ROOT)), 'source_sha256':hashlib.sha256(text.encode()).hexdigest(), 'snippet':snippet})
selection = model_policy.resolve('grok', settings=anchor_settings.get_launch_settings())
record = dict(started=datetime.now(timezone.utc).isoformat(), status='running', selection=selection,
              sources=sources, cross_model=True, unexpected_tools=[])
def save():
    receipt.write_text(json.dumps(record,indent=2), encoding='utf-8')
def emit(event):
    for block in event.get('message',{}).get('content',[]):
        if isinstance(block,dict) and block.get('type')=='tool_use':
            record['unexpected_tools'].append(block.get('name'))
            save()
prompt='''Independent Grok check of one ChatGPT-authored compatibility repair. Use no tools or subagents; source snippets are complete for this narrow decision. Existing validation outside these snippets normalizes model/effort fields without copying secrets and requires the installed subscription CLI.
Observed production failure: cache fetched_at was11minutes old but renewed_at was1minute old, and both Anchor Python and Trio Node incorrectly used fetched_at alone. Official Grok Build remote_config/cache.rs uses a300secondTTL with renewed_at.unwrap_or(fetched_at): renewed_at records successful unchanged-etag validation, fetched_at remains the content timestamp. Supplied fixes use renewal freshness, reject malformed/future/backwards clocks, and preserve session-auth/origin/CLI-version checks. Constants CAPABILITY_TTL_SECONDS=300 and TTL_MS=300000. Python enclosing try catches RuntimeError,ValueError,OSError,KeyError,TypeError,AttributeError and raises PolicyUnavailable. The Grok CLI is probed before reading the cache. Tests passed58Python/73Node; actual subscription capability probes passed both.
Find at most3 concrete defects introduced or left by this repair. No new architecture, cache mutation, forced refresh loop, API-key route or TTL extension. One dry review ends this loop. Return a small complete JSON object with verdict no_material_findings_in_scope|revise, findings array of {id,problem,repair,acceptance_test}, limits array. No prose preface.\n'''
prompt+='\n'.join('\n---'+s['path']+'---\n'+s['snippet'] for s in sources)
save()
broker=GrokBroker(target=str(HERE), model=selection['model'], effort=selection['effort'],permission_mode='plan',emit=emit,turn_timeout_seconds=600)
try:
    result=broker.turn({'type':'user','message':{'content':[{'type':'text','text':prompt}]}})
    record['result']=result
    try: record['review']=json.loads(result.get('result',''))
    except (ValueError,TypeError): record['review']=None
    record['status']='reviewed' if (not result.get('is_error') and result.get('model_attested')
        and isinstance(record['review'],dict) and isinstance(record['review'].get('findings'),list)
        and not record['unexpected_tools'] and result.get('containment',{}).get('descendants_verified')) else 'incomplete'
finally:
    broker.stop()
    record['ended']=datetime.now(timezone.utc).isoformat()
    save()
    with (HERE/'SETUP-2026-09-09.md').open('a',encoding='utf-8') as handle:
        handle.write('\n'+record['ended']+': Catalog-renewal independent review '+record['status']+'; exact receipt retained.\n')
    print(json.dumps({'status':record['status']}),flush=True)
