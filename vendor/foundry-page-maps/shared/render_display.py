"""Render any source-backed display catalog without launching a skill."""
import html
import json
from pathlib import Path

esc = lambda value: html.escape(str(value), quote=True)


def render(root, data):
    root = Path(root)
    sources = {s["id"]: s for s in data["sources"]}
    anchors = {a["id"]: a for a in data["anchors"]}
    for folder in ("resources", "source-pages"):
        (root / folder).mkdir(exist_ok=True)

    def page(title, body):
        return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · {esc(data['title'])}</title>
<link rel="stylesheet" href="../../shared/maps.css"></head><body class="source-page"><main>{body}</main></body></html>'''

    for source in sources.values():
        rows = (root / source["snapshot"]).read_text(encoding="utf-8-sig").splitlines()
        numbered = "\n".join(f'<span class="source-line" id="L{i}"><a href="#L{i}">{i}</a> {esc(line)}</span>' for i, line in enumerate(rows, 1))
        body = f'''<a href="../index.html#library">← {esc(data['title'])} Library</a><h1>{esc(source['id'])}</h1>
<p>{esc(source['kind'])} · frozen exact bytes</p><p class="path">Original: {esc(source['origin'])}</p>
<details><summary>Source identity</summary><p class="path">SHA-256 {source['sha256']}</p></details>
<pre class="full-source">{numbered}</pre>'''
        (root / "source-pages" / (source["id"] + ".html")).write_text(page(source["id"], body), encoding="utf-8")
    for resource in data["resources"]:
        a = anchors[resource["anchor_id"]]
        source = sources[a["source_id"]]
        used = [s for s in data["process"]["steps"] if resource["id"] in s["resource_ids"]]
        links = " · ".join(f'<a target="_top" href="../index.html#process/{s["id"]}">{esc(s["title"])}</a>' for s in used)
        body = f'''<article data-resource-id="{resource['id']}" data-anchor-id="{a['id']}">
<a target="_top" href="../index.html#library">← {esc(data['title'])} Library</a>
<p class="eyebrow">{esc(resource['category'])}</p><h1>{esc(resource['title'])}</h1>
<p class="intro">{esc(resource['summary'])}</p><p class="badge">Resource access frequency unknown</p>
<p>{esc(resource.get('recurrence', ''))}</p><h2>Actual source</h2>
<p class="path">{esc(source['origin'])} · lines {a['start']}–{a['end']}</p><pre>{esc(a['quote'])}</pre>
<p><a class="button" href="../source-pages/{source['id']}.html#L{a['start']}">Open numbered source</a>
<a href="../{source['snapshot']}" download>Download exact source</a></p>
<h2>Process connections</h2><p>{links or 'Related Library material; no automatic call is claimed.'}</p>
<details><summary>Evidence limits and identity</summary><p>Saved bytes anchor the explanation. They do not prove that a run opened this resource, followed an instruction, used a particular model, or verified factual claims.</p>
<p>Original/source hash: <span class="path">{source['sha256']}</span></p><p>Excerpt hash: <span class="path">{a['sha256']}</span></p></details></article>'''
        (root / resource["target"]).write_text(page(resource["title"], body), encoding="utf-8")
    body = f'<h1>{esc(data["title"])} Library</h1><p>{esc(data["refinement"])}</p><ul>' + "".join(
        f'<li><a href="{r["id"]}.html">{esc(r["title"])}</a> — {esc(r["category"])}</li>' for r in data["resources"]) + '</ul><a href="../index.html">Open maps</a>'
    (root / "resources/index.html").write_text(page("Library", body), encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (root / "maps-data.js").write_text("globalThis.FOUNDRY_MAPS = " + payload + ";\n", encoding="utf-8")
