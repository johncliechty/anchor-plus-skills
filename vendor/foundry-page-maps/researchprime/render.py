"""Build openable library/source pages from the frozen, hashed map catalog."""
from pathlib import Path
import html
import importlib.util
import json
import shutil

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / 'shared'
esc = lambda text: html.escape(str(text), quote=True)

_spec = importlib.util.spec_from_file_location('foundry_markdown', SHARED / 'markdown.py')
_markdown = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_markdown)


def page(title, body, prefix='../'):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)} · researchPrime Library</title>
<link rel="icon" href="{prefix}assets/researchprime.jpg"><link rel="stylesheet" href="{prefix}display.css"></head>
<body class="source-page"><main>{body}</main></body></html>'''


def render():
    data = json.loads((HERE / 'maps.json').read_text(encoding='utf-8'))
    sources = {s['id']: s for s in data['sources']}
    anchors = {a['id']: a for a in data['anchors']}
    for directory in ('resources', 'source-pages'):
        (HERE / directory).mkdir(exist_ok=True)
    for source in sources.values():
        lines = (HERE / source['snapshot']).read_text(encoding='utf-8-sig').splitlines()
        code = '\n'.join(f'<span class="source-line" id="L{i}"><a href="#L{i}" aria-label="Line {i}">{i}</a> {esc(line)}</span>' for i, line in enumerate(lines, 1))
        body = f'''<a href="../index.html#library">← Library</a><h1>{esc(source['id'])}</h1>
<p class="note">Frozen {esc(source['kind'])} source · <span class="path">{esc(source['origin'])}</span></p>
<details><summary>Source identity</summary><p class="path">SHA-256 {source['sha256']}</p></details>
<p><a href="../{esc(source['snapshot'])}" download>Download exact source</a></p><pre class="full-source">{code}</pre>'''
        (HERE / 'source-pages' / (source['id']+'.html')).write_text(page(source['id'], body), encoding='utf-8')
    for resource in data['resources']:
        a = anchors[resource['anchor_id']]
        source = sources[a['source_id']]
        used = [s for s in data['process']['steps'] if resource['id'] in s['resource_ids']]
        step_links = ' · '.join(f'<a target="_top" href="../index.html#process/{esc(s["id"])}">{esc(s["title"])}</a>' for s in used)
        if resource.get('render') == 'markdown':
            # Readable, human-facing Markdown instead of a raw-text dump. The page
            # already carries the resource title as its only <h1>, so the source's
            # own headings nest one level down.
            content = f'<div class="md">{_markdown.to_html(a["quote"], heading_offset=1)}</div>'
            if resource['id'] == 'purpose':
                content += f'''<div class="locus"><h2>Where this lives on disk</h2>
<p>The Original North Star is a <strong>LOCKED</strong> block — lines {a['start']}–{a['end']} of the researchPrime
skill instructions, <span class="path">{esc(source['origin'])}</span> (this page renders the frozen snapshot of that file).</p>
<p>Changing it means editing that block in that file, and the block is locked to <strong>John</strong> by name and date —
only he changes it. This page adds no editing feature; it shows the locked text and says where it lives.</p></div>'''
        else:
            content = f'<pre class="excerpt">{esc(a["quote"])}</pre>'
        body = f'''<article data-resource-id="{esc(resource['id'])}" data-anchor-id="{a['id']}">
<a target="_top" href="../index.html#library">← researchPrime Library</a>
<p class="eyebrow">{esc(resource['category'])}</p><h1>{esc(resource['title'])}</h1>
<p class="intro">{esc(resource['summary'])}</p><p class="badge">Use frequency unknown · no resource-level run evidence</p>
<h2>Actual source</h2><p class="note">{esc(source['kind'])} · <span class="path">{esc(source['origin'])}</span><br>Lines {a['start']}–{a['end']} · frozen source snapshot</p>
{content}
<div class="actions"><a class="button" href="../source-pages/{source['id']}.html#L{a['start']}">Open numbered source at line {a['start']}</a>
<a class="button secondary" href="../{source['snapshot']}" download>Download source</a></div>
<h2>Where the process uses this</h2><p>{step_links or 'Related library material; no automatic call is claimed.'}</p>
<details><summary>Source identity and limits</summary><p>Source SHA-256 <span class="path">{source['sha256']}</span></p>
<p>Excerpt SHA-256 <span class="path">{a['sha256']}</span></p><p>These saved bytes anchor the map. They do not prove that a particular run used this resource, or that an instruction was executed.</p>
<p>Reference inventories retain their original search limits and qualifications; copied literature claims are not a new verification of the papers.</p></details></article>'''
        (HERE / resource['target']).write_text(page(resource['title'], body), encoding='utf-8')
    library = '<h1>researchPrime Library</h1><p>Source-backed reusable material, references, other skills and tools.</p><ul>' + ''.join(
        f'<li><a href="{r["id"]}.html">{esc(r["title"])}</a> — {esc(r["category"])}</li>' for r in data['resources']) + '</ul>'
    (HERE / 'resources/index.html').write_text(page('Library', library), encoding='utf-8')
    # The bundle carries byte-identical copies of the shared components, so the
    # page works standalone and other skills' Refinement 2 reuses the originals.
    for component in ('flow-diagram.js', 'layer-library.js'):
        shutil.copyfile(SHARED / component, HERE / component)
    serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (HERE / 'maps-data.js').write_text('globalThis.RESEARCHPRIME_MAPS = '+serialized+';\n', encoding='utf-8')


if __name__ == '__main__':
    render()
