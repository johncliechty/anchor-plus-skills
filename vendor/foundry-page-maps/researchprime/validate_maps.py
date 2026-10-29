"""Fail closed on display claims; checks only this bundle, never invokes a skill."""
import hashlib
import re
from pathlib import Path

REQUIRED_COVERAGE = {
    'entry', 'first_program_step', 'mode', 'model_calls', 'plan_entry', 'round_entry',
    'agents', 'bounded_swarm', 'interim_reports', 'human_interaction', 'feedback',
    'adversarial_reviews', 'depth_selection', 'effort_selection', 'round_selection',
    'stakes_selection', 'stopping_rules', 'final_outputs', 'evidence', 'isolation', 'correction',
}
REQUIRED_EDGES = {
    ('entry', 'probe'), ('planning', 'plan-entry'), ('planning', 'prose-gate'),
    ('prose-gate', 'planning'), ('prose-gate', 'isolation'), ('prose-gate', 'halt'),
    ('scope-gate', 'scope-edit'), ('scope-edit', 'scope-gate'), ('scope-gate', 'halt'),
    ('plan-gate', 'plan-edit'), ('plan-edit', 'plan-build'), ('plan-gate', 'halt'),
    ('gather', 'degraded'), ('degraded', 'reports'), ('round-entry', 'halt'), ('budget', 'halt'),
    ('panel-branch', 'sidecar'), ('panel-branch', 'artifact'), ('panel-branch', 'supplied'),
    ('sidecar', 'halt'), ('supervise', 'halt'), ('governor', 'rc6'), ('tally', 'debate'),
    ('adjudicate', 'judge'), ('adjudicate', 'synth'), ('judge', 'join'), ('synth', 'join'),
    ('stop', 'panel-branch'), ('stop', 'honesty'), ('honesty', 'capture'), ('deliver', 'halt'),
    ('capture', 'pending'), ('capture', 'reports'), ('pending', 'correct'), ('correct', 'round-entry'),
    ('reports', 'done'),
}


def validate(data, root):
    root = Path(root).resolve()
    errors = []

    def require(ok, message):
        if not ok:
            errors.append(message)

    def indexed(items, label):
        result = {x['id']: x for x in items}
        require(len(result) == len(items), 'duplicate ' + label)
        return result

    def target(relative):
        # Only explicit bundle-owned paths, not absolute paths, URLs or encoded traversal.
        if not isinstance(relative, str) or not re.fullmatch(r'[a-zA-Z0-9_./-]+', relative):
            return None
        if relative.startswith('/') or '..' in relative.split('/') or '\\' in relative:
            return None
        p = (root / relative).resolve()
        return p if p.is_relative_to(root) else None

    sources = indexed(data['sources'], 'source')
    anchors = indexed(data['anchors'], 'anchor')
    resources = indexed(data['resources'], 'resource')
    nodes = indexed(data['knowledge']['nodes'], 'knowledge node')
    steps = indexed(data['process']['steps'], 'process step')
    source_lines = {}
    for sid, source in sources.items():
        p = target(source['snapshot'])
        require(p is not None and p.is_file(), 'missing source ' + sid)
        if p is not None and p.is_file():
            raw = p.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == source['sha256'], 'changed source ' + sid)
            source_lines[sid] = raw.decode('utf-8-sig').splitlines()
    for aid, a in anchors.items():
        rows = source_lines.get(a['source_id'], [])
        start, end = a['start'], a['end']
        require(isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(rows), 'bad anchor range ' + aid)
        excerpt = '\n'.join(rows[max(start - 1, 0):end])
        require(bool(excerpt) and excerpt == a['quote'], 'ungrounded quote ' + aid)
        require(hashlib.sha256(excerpt.encode()).hexdigest() == a['sha256'], 'changed anchor ' + aid)
        if a.get('symbol'):
            require(bool(re.search(r'\bfunction\s+' + re.escape(a['symbol']) + r'\b', excerpt)), 'missing callable ' + aid)
        require(a['source_id'] in sources, 'unknown anchor source ' + aid)
    for rid, r in resources.items():
        p = target(r['target'])
        require(p is not None and p.is_file(), 'missing resource target ' + rid)
        require(r['anchor_id'] in anchors, 'resource without anchor ' + rid)
        if p and p.is_file():
            rendered = p.read_text(encoding='utf-8')
            require(f'data-resource-id="{rid}"' in rendered and f'data-anchor-id="{r["anchor_id"]}"' in rendered,
                    'resource target identity mismatch ' + rid)
        # This snapshot has no explicit resource-use receipts. Unknown is not a measured zero.
        require(r['usage'] == {'status': 'unknown', 'count': None, 'run_ids': [], 'method': None}, 'unsupported use frequency ' + rid)
    require(not data['knowledge']['run_evidence'], 'unvalidated run evidence in seed snapshot')
    require(data['knowledge']['learned'] is False and data['knowledge']['geometry'] == 'seeded-declared-tree', 'unsupported learned geometry')
    require(data['knowledge']['layout_source'] == 'parent_id', 'invented layout weights')
    for nid, n in nodes.items():
        require(n['resource_id'] in resources, 'knowledge target missing ' + nid)
        require(all(sid in steps for sid in n['process_ids']), 'unknown knowledge process link ' + nid)
        parent = n['parent_id']
        require(parent is None or parent in nodes, 'unknown knowledge parent ' + nid)
        require(n['ring'] == (0 if parent is None else nodes.get(parent, {}).get('ring', -2) + 1), 'invalid declared depth ' + nid)
        seen = {nid}
        while parent in nodes:
            if parent in seen:
                errors.append('knowledge cycle ' + nid)
                break
            seen.add(parent)
            parent = nodes[parent]['parent_id']
    require({n['resource_id'] for n in nodes.values()} == set(resources), 'library resources absent from knowledge map')
    coverage = set()
    for sid, s in steps.items():
        require(bool(s['anchors']) and all(a in anchors for a in s['anchors']), 'ungrounded process step ' + sid)
        require(all(r in resources for r in s['resource_ids']), 'unknown process resource ' + sid)
        coverage.update(s['covers'])
        if s['code_status'] == 'anchored':
            require(any(sources.get(anchors.get(a, {}).get('source_id'), {}).get('kind') == 'code' for a in s['anchors']), 'program claim without code ' + sid)
    require(REQUIRED_COVERAGE <= coverage, 'incomplete control-flow coverage: ' + ', '.join(sorted(REQUIRED_COVERAGE - coverage)))
    edges = data['process']['edges']
    pairs = {(e['source'], e['target']) for e in edges}
    require(REQUIRED_EDGES <= pairs, 'missing control-flow branch: ' + repr(REQUIRED_EDGES - pairs))
    for e in edges:
        require(e['source'] in steps and e['target'] in steps and e['anchor_id'] in anchors and bool(e['label']), 'ungrounded transition ' + repr(e))
    reached = {data['process']['entry']}
    while True:
        expanded = reached | {b for a, b in pairs if a in reached}
        if expanded == reached:
            break
        reached = expanded
    require(reached == set(steps), 'unreachable process steps')
    require(set(data['process']['terminals']) == {'done', 'pending', 'halt'}, 'missing honest terminal')
    can_stop = set(data['process']['terminals'])
    while True:
        expanded = can_stop | {a for a, b in pairs if b in can_stop}
        if expanded == can_stop:
            break
        can_stop = expanded
    require(set(steps) <= can_stop, 'process path with no stopping route')
    panel = steps.get('panel', {}).get('swarm', {})
    require(panel.get('bounded') is True and panel.get('count') == panel.get('concurrency_cap') == 3, 'invented reviewer bound')
    require(panel.get('count_anchor') in anchors and panel.get('limit_anchor') in anchors, 'reviewer bound without evidence')
    require(panel.get('bound_scope') == 'logical roster jobs' and panel.get('process_cap') is None and bool(panel.get('limitation')), 'invented physical-process bound')
    debate = steps.get('debate', {}).get('swarm', {})
    require(debate.get('bounded') is False and debate.get('concurrency_cap') is None and bool(debate.get('limitation')), 'concealed debate fan-out')
    for d in data['process']['disagreements']:
        require(len(d['anchors']) >= 2 and all(a in anchors for a in d['anchors']), 'ungrounded disagreement ' + d['id'])
    require(data['lifecycle'] == {'state': 'for-review', 'accepted': False, 'closed': False}, 'invented acceptance')
    require(data['integration']['installed'] is False, 'invented Anchor integration')

    # Refinement 2 — the review record is cumulative and honest.
    require(str(data.get('refinement', '')).startswith('researchPrime Library and maps — Refinement 2'), 'wrong refinement record')
    cumulative = (data.get('review') or {}).get('cumulative') or []
    first = cumulative[0] if cumulative else {}
    require(first.get('refinement') == 1 and first.get('grade') == 'B' and len(first.get('points') or []) == 5
            and bool(first.get('verdict')) and bool(first.get('response')), 'missing cumulative review record')

    # Refinement 2 — every process node is visibly typed and placed in the diagram.
    display_types = {'program', 'model-call', 'instruction', 'human-gate', 'adversarial-review'}
    for sid, s in steps.items():
        require(s.get('display_type') in display_types, 'untyped process node ' + sid)
    require({s.get('display_type') for s in steps.values()} >= display_types, 'missing display-type coverage')
    diagram = data['process'].get('diagram') or {}
    placed = diagram.get('nodes') or {}
    require(set(placed) == set(steps), 'diagram layout does not cover the process')
    seen_cells = set()
    for sid, cell in placed.items():
        ok = isinstance(cell.get('col'), int) and isinstance(cell.get('row'), int) and cell['col'] >= 0 and cell['row'] >= 0
        require(ok, 'invalid diagram cell ' + sid)
        if ok:
            require((cell['col'], cell['row']) not in seen_cells, 'overlapping diagram cells ' + sid)
            seen_cells.add((cell['col'], cell['row']))
    bands = diagram.get('bands') or []
    require(bool(bands), 'diagram without phase bands')
    for sid, cell in placed.items():
        require(any(b['from_row'] <= cell.get('row', -1) <= b['to_row'] for b in bands), 'diagram node outside phase bands ' + sid)
    for key in ('col_width', 'row_height', 'node_width', 'node_height'):
        require(isinstance(diagram.get(key), int) and diagram.get(key, 0) > 0, 'missing diagram geometry ' + key)

    # Refinement 2 — every reconciliation item carries both sides and sits on map nodes.
    for d in data['process']['disagreements']:
        ia, ca = d.get('instruction_anchor'), d.get('code_anchor')
        require(ia in anchors and sources.get(anchors.get(ia, {}).get('source_id'), {}).get('kind') == 'instructions',
                'reconciliation without instruction anchor ' + d['id'])
        require(ca in anchors and sources.get(anchors.get(ca, {}).get('source_id'), {}).get('kind') == 'code',
                'reconciliation without code anchor ' + d['id'])
        require(ia in (d.get('anchors') or []) and ca in (d.get('anchors') or []), 'reconciliation anchors detached ' + d['id'])
        require(bool(d.get('instruction_says')) and bool(d.get('code_does')) and bool(d.get('follows')),
                'reconciliation missing says/does/follows ' + d['id'])
        require(bool(d.get('step_ids')) and all(sid in steps for sid in d.get('step_ids') or []),
                'reconciliation not documented on a map node ' + d['id'])

    # Refinement 2 — layered library rollups are recomputed, never asserted.
    child_ids = {}
    for nid, n in nodes.items():
        child_ids.setdefault(n['parent_id'], []).append(nid)
    for nid, n in nodes.items():
        subtree, stack = {nid}, [nid]
        while stack:
            for child in child_ids.get(stack.pop(), []):
                if child not in subtree:
                    subtree.add(child)
                    stack.append(child)
        held = {nodes[i]['resource_id'] for i in subtree}
        counts = {}
        for rid in held:
            category = resources.get(rid, {}).get('category')
            if category is not None:
                counts[category] = counts.get(category, 0) + 1
        catalog_ok = dict(n.get('catalog') or {}) == counts and n.get('catalog_total') == len(held)
        require(catalog_ok and len(held & set(resources)) == len(held), 'invented layer rollup ' + nid)

    # Refinement 2 — Human Guide and North Star render as HTML from Markdown,
    # and the North Star states its on-disk home and LOCKED status.
    for rid in ('purpose', 'human-guide'):
        require(resources.get(rid, {}).get('render') == 'markdown', 'raw-text guide resource ' + rid)
    for rid, r in resources.items():
        require(r.get('render') in (None, 'markdown'), 'unknown render mode ' + rid)
        if r.get('render') == 'markdown':
            p = target(r['target'])
            if p is not None and p.is_file():
                rendered = p.read_text(encoding='utf-8')
                require('<div class="md">' in rendered and '<h2>' in rendered, 'markdown not rendered as HTML ' + rid)
    purpose = resources.get('purpose')
    if purpose:
        p = target(purpose['target'])
        if p is not None and p.is_file():
            rendered = p.read_text(encoding='utf-8')
            origin = sources.get('skill', {}).get('origin', '')
            require(bool(origin) and origin in rendered and 'LOCKED' in rendered and 'John' in rendered,
                    'North Star location and LOCKED status not stated')

    for p in ('index.html', 'maps-data.js', 'adapter.js', 'adapter.mjs', 'display.js', 'display.css',
              'flow-diagram.js', 'layer-library.js'):
        require((root / p).is_file(), 'missing display seam ' + p)
    shared = root.parent / 'shared'
    for component in ('flow-diagram.js', 'layer-library.js'):
        canonical, copy = shared / component, root / component
        require(canonical.is_file() and copy.is_file() and canonical.read_bytes() == copy.read_bytes(),
                'bundle component diverges from shared ' + component)
    return errors


if __name__ == '__main__':
    import json
    root = Path(__file__).resolve().parent
    errors = validate(json.loads((root / 'maps.json').read_text(encoding='utf-8')), root)
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Display targets, source anchors, frequency honesty and full control flow pass.')
