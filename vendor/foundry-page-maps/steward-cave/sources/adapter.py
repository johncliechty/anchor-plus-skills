"""Read-only Foundry walkthrough projections and contained source viewer.

The page discovers SKILL.md files without registering runners or changing the
Foundry map. Foundry owns content: per-skill LIBRARY.json / FLOW.json and
knowledge/graph.json, or library.json / process-map.json / knowledge-map.json
in FOUNDRY_PAGE_CONTENT_ROOT/<skill>. Nothing here writes to a skill repository.
Missing/invalid maps stay unfinished; geometry and frequency are never learned
or inferred by this display adapter.
"""
import hashlib
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import anchor_settings
import foundry_api as api


CODE_ROOT = Path(__file__).resolve().parent
TEXT_TYPES = frozenset(('.md', '.txt', '.json', '.mjs', '.js', '.jsx', '.py',
                        '.ts', '.tsx', '.yaml', '.yml', '.toml', '.css', '.html'))
ICON_TYPES = frozenset(('.png', '.jpg', '.jpeg', '.svg', '.webp'))
ICON_NAMES = (
    ('researchprime', 'research-prime-icon.jpg'), ('gandalf', 'gandalf-icon-v5.jpg'),
    ('crucible', 'crucible-icon.svg'), ('foreman', 'foreman-icon.svg'),
    ('chekhov', 'chekhov-icon.svg'), ('einstein', 'einstein-icon.png'),
    ('financialanalyst', 'financial-analyst-icon.jpg'), ('jumper', 'jumper-icon.jpg'),
    ('legalbeagle', 'legal-beagle-icon.jpg'), ('literaturereview', 'literature-review-icon.jpg'),
    ('ramanujan', 'ramanujan-icon.jpg'), ('tidyidy', 'tidy-idy-icon.jpg'),
    ('zombiehunter', 'zombie-hunter-radar.jpg'), ('superjump', 'superjump-icon.jpg'))
DISPLAY_NAMES = {'researchprime': 'researchPrime', 'gandalf': 'Gandalf', 'crucible': 'Crucible',
                 'foreman': 'Foreman', 'chekhov': 'Chekhov', 'einstein': 'Einstein',
                 'financialanalyst': 'Financial-Analyst', 'jumper': 'Jumper', 'legalbeagle': 'Legal-Beagle',
                 'literaturereview': 'Literature-Review', 'ramanujan': 'Ramanujan',
                 'tidyidy': 'Tidy-Idy', 'zombiehunter': 'Zombie-Hunter', 'superjump': 'Superjump'}

# Content names are Foundry-owned; role identity and livery remain Anchor-owned.
ROLE_CONTENT = {'steward-project': 'steward-lamp',
                'steward-portfolio': 'steward-cave',
                'steward-starchart': 'steward-star-chart'}
# These are exact public implementation files, not additional serving roots.
ANCHOR_PROVENANCE = ('foundry_page.py', 'anchor_settings.py', 'model_policy.py',
                     'steward_cockpit/steward_engine.py',
                     'steward_cockpit/steward_routes.py',
                     'steward_cockpit/conversation_history.py',
                     'steward_cockpit/code_jobs.py')


def _key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def _text(path):
    try:
        return Path(path).read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        return ''


def discovery_roots():
    """Configured existing sources; no duplicate registry or model settings."""
    foundry = Path(api.FOUNDRY_ROOT)
    trio = Path(os.environ.get('FOUNDRY_TRIO_ROOT') or 'C:/dev/trio')
    steward = Path(os.environ.get('FOUNDRY_STEWARD_ROOT') or
                   'C:/Users/example/.agents/skills/ecgberht')
    return foundry, Path(api.SKILLS_ROOT), trio, steward


def content_root():
    return Path(os.environ.get('FOUNDRY_PAGE_CONTENT_ROOT') or
                (Path(api.FOUNDRY_ROOT) / 'Foundry page and knowledge maps'))


def _inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _allowed(path):
    roots = (*discovery_roots(), content_root())
    return any(_inside(path, root) for root in roots)


def _frontmatter(text, field):
    fm = re.match(r'^---\s*\n([\s\S]*?)\n---', text)
    if not fm:
        return ''
    m = re.search(r'^' + re.escape(field) + r':\s*(.*?)\s*$', fm[1], re.M)
    return m[1].strip('"\'') if m else ''


def _section(text, heading):
    m = re.search(r'^##[ \t]+' + re.escape(heading) + r'(?:[ \t]+[^\n]*)?\n([\s\S]*?)(?=^#{1,2}\s|\Z)',
                  text, re.M | re.I)
    return m[1].strip() if m else ''


def _icon(directory, text, skill_id):
    edge = CODE_ROOT / 'foundry-gui/public/brand' / ('foundry-edge-' + skill_id + '.png')
    if edge.is_file():
        return '/brand/' + edge.name, None
    icon = _frontmatter(text, 'icon')
    candidates = [directory / icon] if icon else []
    for folder in (directory / 'assets', directory / 'assets/icons'):
        if folder.is_dir():
            candidates.extend(sorted(folder.glob('icon.*')))
    for path in candidates:
        if _allowed(path) and path.is_file() and path.suffix.lower() in ICON_TYPES:
            return '/foundry/icon?' + urlencode({'skill': skill_id}), str(path.resolve())
    for key, name in ICON_NAMES:
        if _key(skill_id) == key and (CODE_ROOT / 'vendor/brand' / name).is_file():
            return '/vendor/brand/' + name, None
    return None, None


def catalog():
    foundry, skills_root, trio, steward = discovery_roots()
    manifest = {str(Path(api._resolve_source(e.get('source'))).resolve()): e
                for e in api._load_manifest() if e.get('source')}
    candidates = list(skills_root.glob('*/SKILL.md'))
    candidates.extend(trio / name / 'SKILL.md' for name in ('crucible', 'foreman', 'researchPrime'))
    candidates.append(steward / 'SKILL.md')
    candidates.extend(Path(p) / 'SKILL.md' for p in manifest)
    rows, seen = [], set()
    for path in candidates:
        directory = path.parent.resolve()
        if str(directory) in seen or not path.is_file() or not _allowed(path):
            continue
        seen.add(str(directory))
        text = _text(path)
        if directory.name.lower() == 'templates' or _frontmatter(text, 'foundry').lower() == 'false':
            continue
        # agy-dispatch and Figure-Designer are explicitly excluded in the design;
        # canonical frontmatter still needs the Foundry-owned follow-up.
        if _key(directory.name) in ('agydispatch', 'figuredesigner'):
            continue
        entry = manifest.get(str(directory), {})
        skill_id = 'ecgberht' if directory == steward.resolve() else _key(directory.name)
        human = api._parse_human_md(_text(directory / 'HUMAN.md'))
        parsed = api._parse_skill_md(text)
        name = _frontmatter(text, 'name') or entry.get('name') or directory.name
        if _key(name) == skill_id:
            name = DISPLAY_NAMES.get(skill_id, name)
        north = (_text(directory / 'NORTH-STAR.md').strip() or _section(text, 'North Star') or
                 _text(directory / 'VISION.md').strip())
        purpose = human['oneSentence'] or parsed['description'] or api._first_paragraph(parsed['body'])
        icon, icon_path = _icon(directory, text, skill_id)
        rows.append({'id': skill_id, 'name': name, 'purpose': purpose,
                     'northStar': north, 'source': str(directory), 'ref': entry.get('ref'),
                     'status': entry.get('status'), 'inFoundryMap': bool(entry),
                     'icon': icon, 'iconPath': icon_path, 'role': None,
                     'walkthrough': 'unfinished'})
    profile = anchor_settings.steward_profile()
    steward_row = next((r for r in rows if r['id'] == 'ecgberht'), None)
    if steward_row:
        rows.remove(steward_row)
        for role, label, art, purpose in (
            ('project', profile['seal_name'], profile['seal'],
             'Keep one effort’s dialogue, decisions and delivery coherent.'),
            ('portfolio', profile['high_seat_name'], profile['high_seat'],
             'Seat and coordinate initiatives across projects.'),
            ('starchart', profile['campaign_name'], profile['campaign_icon'],
             'Explore goals and foresight, then hand approved work to the portfolio steward.')):
            rows.append({**steward_row, 'id': 'steward-' + role,
                         'name': profile['label'] + '-' + label, 'role': role,
                         'purpose': purpose, 'icon': '/brand/foundry-edge-ecgberhtportfolio.png'
                         if role == 'portfolio' and profile['key'] == 'ecgberht' else '/vendor/brand/' + art, 'iconPath': None})
    rows.sort(key=lambda r: r['name'].casefold())
    return {'skills': rows, 'persona': profile['label'],
            'walkthroughOrder': ['researchprime', 'gandalf', 'steward-project',
                                 'steward-portfolio', 'steward-starchart'],
            'contentRoot': str(content_root()), 'northStar': api.load_north_star()}


def find_skill(skill_id):
    return next((r for r in catalog()['skills'] if r['id'] == skill_id), None)


def _load_artifact(skill, names):
    directory = Path(skill['source'])
    role = skill.get('role')
    searches = [(content_root() / skill['id'], names), (directory, names)]
    if role:
        searches = [(content_root() / ROLE_CONTENT[skill['id']], names),
                    (content_root() / skill['id'], names),
                    (directory, tuple(name.replace('.json', '.' + role + '.json') for name in names)),
                    (directory / 'knowledge' / role, names)]
    for base, file_names in searches:
        for name in file_names:
            path = base / name
            if not path.is_file() or not _allowed(path):
                continue
            try:
                data = json.loads(_text(path))
                if not isinstance(data, (dict, list)):
                    raise ValueError('expected an object or array')
                return data, path, None
            except (ValueError, TypeError) as exc:
                return None, path, 'Unreadable content: ' + str(exc)
    return None, None, None


def _path(raw, directory, artifact_dir=None):
    if not raw or not isinstance(raw, str) or '\x00' in raw:
        return None
    raw = raw.replace('\\', '/')
    path = Path(raw)
    if '..' in path.parts:
        return None
    candidates = [path] if path.is_absolute() else [directory / path]
    if not path.is_absolute():
        if artifact_dir:
            candidates.append(artifact_dir / path)
        candidates.extend([Path(api.FOUNDRY_ROOT) / path, discovery_roots()[2] / path])
    return next((p.resolve() for p in candidates if p.is_file() and _allowed(p)
                 and p.suffix.lower() in TEXT_TYPES and not any(
                     part.startswith('.') for part in p.relative_to(p.anchor).parts
                     if part not in ('.agents', '.claude', '.codex'))), None)


def source_url(skill, path, anchor=''):
    return '/foundry/source?' + urlencode({'skill': skill, 'path': str(path), 'anchor': anchor or ''})


def _trusted_origin(raw, skill):
    """A role may cite these exact originals; no user-home/root expansion."""
    if skill['id'] not in ROLE_CONTENT or not isinstance(raw, str):
        return None
    candidate = Path(raw.replace('\\', '/'))
    if not candidate.is_absolute() or '..' in candidate.parts:
        return None
    approved = [(root / rel, root) for root in
                (CODE_ROOT, Path(api.FOUNDRY_ROOT).parent / 'Anchor')
                for rel in ANCHOR_PROVENANCE]
    global_dir = Path.home() / '.claude'
    approved.append((global_dir / 'AGENTS.md', global_dir))
    for exact, root in approved:
        if (candidate == exact and _inside(candidate, root) and candidate.is_file()
                and candidate.resolve() == root.resolve() / exact.relative_to(root)):
            return candidate.resolve()
    return None


def _declared_source(source, skill, base):
    """Resolve only this inventory entry, with frozen examples hash-bound."""
    provenance = {k: source.get(k) for k in
                  ('origin', 'freshness', 'captured_at', 'captured_from', 'applicability', 'sha256')}
    if source.get('freshness') == 'frozen-example':
        snapshot = source.get('snapshot')
        digest = source.get('sha256')
        if (not isinstance(snapshot, str) or not re.fullmatch(r'[a-f0-9]{64}', str(digest or ''))
                or not all(source.get(k) for k in ('captured_at', 'captured_from', 'applicability'))):
            return None, provenance, 'Historical source lacks its capture identity or qualification'
        raw = Path(snapshot.replace('\\', '/'))
        target = base / raw
        if (raw.is_absolute() or '..' in raw.parts or any(p.startswith('.') for p in raw.parts)
                or not _inside(target, base / 'sources') or not _allowed(target)
                or not target.is_file() or target.suffix.lower() not in TEXT_TYPES):
            return None, provenance, 'Historical snapshot missing or outside its bundle sources'
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            return None, provenance, 'Historical snapshot hash mismatch'
        return target.resolve(), provenance, None
    if source.get('freshness') not in (None, 'current-source'):
        return None, provenance, 'Unsupported source freshness'
    target = (_path(source.get('origin'), Path(skill['source']), base)
              or _trusted_origin(source.get('origin'), skill))
    return target, provenance, None if target else 'Missing or outside the declared source inventory'


def _anchor_link(anchor, skill, artifact_dir, resources, *, declared_path=None, provenance=None):
    if isinstance(anchor, str):
        anchor = {'path': anchor}
    if not isinstance(anchor, dict):
        return None
    if anchor.get('type') in ('no-code', 'no-instruction'):
        return {'label': anchor.get('type'), 'note': anchor.get('reason') or 'Not implemented on this path.'}
    path = declared_path or _path(anchor.get('path') or anchor.get('file'), Path(skill['source']), artifact_dir)
    if not path:
        return {'label': 'Source unavailable', 'problem': 'Missing or outside the declared source roots'}
    at = str(anchor.get('symbol') or anchor.get('heading') or anchor.get('anchor') or anchor.get('line') or '')
    content = _text(path)
    problem = None
    if at.isdigit() and not 1 <= int(at) <= len(content.splitlines()):
        problem = 'Source changed: line no longer present'
    elif at and not at.isdigit() and at not in content:
        problem = 'Source changed: anchor no longer present'
    expected = anchor.get('sha256') or anchor.get('hash')
    if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        problem = 'Source changed since this map was checked'
    resource = _resource(skill, path, 'tools', path.name, anchor=at)
    if provenance:
        resource['provenance'] = provenance
    if not any(r['id'] == resource['id'] for r in resources):
        resources.append(resource)
    return {'label': path.name + (' · ' + at if at else ''), 'href': resource['href'],
            'resourceId': resource['id'], 'problem': problem}


def _resource(skill, path, category, title, anchor='', resource_id=None):
    return {'id': resource_id or hashlib.sha256((str(path) + '#' + anchor).encode()).hexdigest()[:16],
            'title': title, 'category': category, 'path': str(path), 'anchor': anchor,
            'href': source_url(skill['id'], path, anchor), 'frequency': 'Use not recorded'}


def _review_project_id():
    """Use only the existing, unambiguous project registration; never create one."""
    import rnd_registry
    rows = [r for r in rnd_registry.list_projects(with_effective_state=False)
            if r.get('folder_path') and Path(r['folder_path']).resolve() == Path(api.FOUNDRY_ROOT).resolve()]
    return rows[0]['id'] if len(rows) == 1 else None


def _library_target(raw, base, project_id):
    if not project_id or not isinstance(raw, str):
        return None
    rel = Path(raw.replace('\\', '/'))
    target = base / rel
    if (rel.is_absolute() or '..' in rel.parts or any(p.startswith('.') for p in rel.parts)
            or not _inside(target, base / 'resources') or not _inside(target, Path(api.FOUNDRY_ROOT))
            or not target.is_file() or target.suffix.lower() != '.html'):
        return None
    relative = target.resolve().relative_to(Path(api.FOUNDRY_ROOT).resolve()).as_posix()
    return '/artifact/' + quote(str(project_id), safe='') + '/' + quote(relative, safe='/')


def _frequency(record, skill, artifact_dir):
    """Only counts backed by distinct existing run records get a use label."""
    evidence = record.get('useEvidence') or record.get('usage_evidence') or []
    if not isinstance(evidence, list):
        return 'Use not recorded'
    paths = {_path(p.get('path') if isinstance(p, dict) else p,
                   Path(skill['source']), artifact_dir) for p in evidence}
    paths.discard(None)
    run_ids = set()
    for path in paths:
        if path.suffix != '.json' or not any(p in ('journal', 'runs') for p in path.parts):
            continue
        try:
            data = json.loads(_text(path))
            # A journal file existing is not proof that this resource was used.
            if (isinstance(data, dict) and data.get('run_id') and
                    record.get('id') in data.get('resource_ids', [])):
                run_ids.add(str(data['run_id']))
        except (ValueError, TypeError):
            pass
    return f'{len(run_ids)} recorded ' + ('use' if len(run_ids) == 1 else 'uses') if run_ids else 'Use not recorded'


def _combined_display(skill, resources):
    """Foundry-owned foundry-skill-display/v1 handoff; canonical sources stay live.

    Anchors use the controlled reader. Historical examples use only their exact
    immutable snapshots; current sources retain visible freshness checks.
    """
    data, path, error = _load_artifact(skill, ('maps.json',))
    if data is None:
        return None, [error] if error else []
    if not isinstance(data, dict) or data.get('schema') != 'foundry-skill-display/v1' or data.get('skill_id') != skill['id']:
        return None, ['Unsupported or different-skill maps.json handoff']
    for field in ('sources', 'anchors', 'resources'):
        if not isinstance(data.get(field), list):
            return None, [field + ' must be an array in maps.json']
    for field, child in (('knowledge', 'nodes'), ('process', 'steps'), ('process', 'edges')):
        if not isinstance(data.get(field), dict) or not isinstance(data[field].get(child), list):
            return None, [field + '.' + child + ' must be an array in maps.json']
    issues, links = [], {}
    sources = {s.get('id'): s for s in data.get('sources', []) if isinstance(s, dict)}
    declared = {sid: _declared_source(source, skill, path.parent) for sid, source in sources.items()}
    for anchor in data.get('anchors', []):
        if not isinstance(anchor, dict):
            issues.append('Invalid source anchor')
            continue
        source = sources.get(anchor.get('source_id'), {})
        target, provenance, source_error = declared.get(anchor.get('source_id'),
                                                       (None, {}, 'Undeclared source'))
        spec = {'path': source.get('origin'), 'line': anchor.get('start'), 'sha256': source.get('sha256')}
        link = (_anchor_link(spec, skill, path.parent, resources, declared_path=target, provenance=provenance)
                if target else {'label': 'Source unavailable', 'problem': source_error})
        if link and link.get('href'):
            start, end = anchor.get('start'), anchor.get('end')
            if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(_text(target).splitlines()):
                excerpt = '\n'.join(_text(target).splitlines()[start - 1:end])
                if anchor.get('sha256') and hashlib.sha256(excerpt.encode()).hexdigest() != anchor['sha256']:
                    link['problem'] = 'Source changed: anchored excerpt differs'
            else:
                link['problem'] = 'Invalid source range'
        if not link:
            link = {'label': 'Source unavailable', 'problem': 'Missing original source'}
        if link.get('problem'):
            issues.append(link['problem'] + ' · ' + str(anchor.get('source_id')) + ' / ' + str(anchor.get('id')))
        links[anchor.get('id')] = link
    categories = {'Reusable material': 'material', 'References': 'references', 'Other skills': 'skills', 'Tools': 'tools'}
    project_id = _review_project_id() if any(r.get('target') for r in data['resources'] if isinstance(r, dict)) else None
    for row in data.get('resources', []):
        if not isinstance(row, dict):
            issues.append('Invalid Library resource')
            continue
        link = links.get(row.get('anchor_id'), {})
        if not link.get('href'):
            issues.append('Library target missing: ' + str(row.get('id')))
            continue
        backing = next((r for r in resources if r['id'] == link.get('resourceId')), {})
        resources.append({**backing, 'id': row.get('id'), 'title': row.get('title'),
                          'category': categories.get(row.get('category'), 'material'),
                          'description': row.get('summary', ''), 'problem': link.get('problem'),
                          'href': _library_target(row.get('target'), path.parent, project_id) or backing['href'],
                          'sourceHref': backing['href'],
                          'frequency': _frequency(row, skill, path.parent), 'library': True})
    flow = data.get('process') if isinstance(data.get('process'), dict) else {}
    steps = []
    for row in flow.get('steps', []):
        if not isinstance(row, dict):
            issues.append('Invalid process step')
            continue
        aa = [links[a] for a in row.get('anchors', []) if a in links]
        steps.append({**row, 'description': row.get('summary'), 'anchorLinks': aa,
                      'codeLink': aa[0] if row.get('code_status') == 'anchored' and aa else
                          {'label': 'instructions-only', 'note': 'Session work; no code on this path.'},
                      'instructionLink': aa[-1] if row.get('instruction_status') == 'anchored' and aa else
                          {'label': 'no-separate-instruction', 'note': 'See the program source.'}})
        if not aa:
            issues.append('No process sources: ' + str(row.get('id')))
    knowledge = data.get('knowledge') if isinstance(data.get('knowledge'), dict) else {}
    nodes = [{**n, 'name': n.get('title'), 'parent': n.get('parent_id')}
             for n in knowledge.get('nodes', []) if isinstance(n, dict)]
    disagreements = [{**d, 'sourceLinks': [links[a] for a in d.get('anchors', []) if a in links]}
                     for d in flow.get('disagreements', []) if isinstance(d, dict)]
    return {'source': str(path), 'qualification': data.get('refinement') or 'Walkthrough awaiting human review.',
            'steps': steps, 'edges': [{**e, 'from': e.get('source'), 'to': e.get('target'),
                                      'sourceLink': links.get(e.get('anchor_id'))}
                                     for e in flow.get('edges', []) if isinstance(e, dict)],
            'exits': flow.get('terminals', []),
            'disagreements': disagreements, 'nodes': nodes, 'issues': issues,
            'observedExamples': [{**e, 'sourceLinks': [links[a] for a in e.get('anchors', []) if a in links]}
                                 for e in data.get('observed_examples', []) if isinstance(e, dict)],
            'usageAudit': data.get('usage_audit')}, issues


def skill_detail(skill_id):
    skill = find_skill(skill_id)
    if not skill:
        return None
    directory = Path(skill['source'])
    resources = []
    for name in ('SKILL.md', 'HUMAN.md', 'NORTH-STAR.md', 'VISION.md', 'CHANGELOG.md', 'LESSONS.md'):
        path = _path(name, directory)
        if path:
            resources.append(_resource(skill, path, 'material', name))
    journals = sorted((directory / 'journal').glob('*.md'), reverse=True)
    for path in journals:
        if _path(str(path), directory):
            resources.append(_resource(skill, path.resolve(), 'references', path.stem))
    # Commands and links already declared by the skill open their actual files.
    instructions = _text(directory / 'SKILL.md')
    pattern = r'(?:[A-Za-z]:[/\\][^\s`"<>|)]+|(?:[\w.-]+[/\\])+[\w.-]+)\.(?:md|mjs|js|py|json|ts)'
    for raw in dict.fromkeys(re.findall(pattern, instructions)):
        path = _path(raw.rstrip('.,;'), directory)
        if path and not any(r['path'] == str(path) for r in resources):
            resources.append(_resource(skill, path, 'tools', path.name))
    library, library_path, library_error = _load_artifact(skill, ('library.json', 'LIBRARY.json'))
    artifact_dir = library_path.parent if library_path else directory
    entries = library if isinstance(library, list) else (library or {}).get('resources', [])
    issues = [library_error] if library_error else []
    if not isinstance(entries, list):
        entries = []
        issues.append('Library resources must be an array')
    for entry in entries:
        if not isinstance(entry, dict):
            issues.append('Invalid Library resource')
            continue
        category = entry.get('category') or entry.get('kind') or 'material'
        title = entry.get('title') or entry.get('name') or entry.get('id') or 'Resource'
        anchor = entry.get('anchor')
        target = entry.get('path') or entry.get('file') or (anchor.get('path') if isinstance(anchor, dict) else None)
        path = _path(target, directory, artifact_dir)
        url = entry.get('url') or entry.get('href')
        at = (anchor.get('symbol') or anchor.get('heading') or '') if isinstance(anchor, dict) else (anchor or '')
        if path:
            r = _resource(skill, path, category, title, str(at), entry.get('id'))
        elif url and urlsplit(url).scheme in ('https', 'http') and urlsplit(url).netloc:
            r = {'id': entry.get('id') or url, 'title': title, 'category': category,
                 'href': url, 'external': True}
        elif entry.get('skill') and find_skill(_key(entry['skill'])):
            r = {'id': entry.get('id') or entry['skill'], 'title': title, 'category': 'skills',
                 'href': '/foundry?' + urlencode({'skill': _key(entry['skill'])})}
        else:
            issues.append('Library target missing: ' + str(title))
            continue
        r['frequency'] = _frequency(entry, skill, artifact_dir)
        r['library'] = True
        r['description'] = entry.get('description') or entry.get('purpose') or ''
        resources = [old for old in resources if old['id'] != r['id']]
        resources.append(r)
    # Composition is displayed from the existing map, never guessed from names.
    manifest = next((e for e in api._load_manifest() if e.get('ref') == skill.get('ref')), {})
    for edge in manifest.get('edges', []):
        other = next((r for r in catalog()['skills'] if r.get('ref') == edge.get('to')), None)
        if other:
            resources.append({'id': 'skill-' + other['id'], 'title': other['name'], 'category': 'skills',
                              'href': '/foundry?' + urlencode({'skill': other['id']}),
                              'description': edge.get('type'), 'frequency': 'Use not recorded'})
    combined, combined_issues = _combined_display(skill, resources)
    issues.extend(combined_issues)
    flow = _process_map(skill, resources, combined)
    knowledge = _knowledge_map(skill, resources, combined)
    human = _text(directory / 'HUMAN.md')
    return {'skill': skill, 'resources': resources, 'libraryIssues': issues,
            'libraryResources': [r for r in resources if r.get('library')] or
                [r for r in resources if r.get('category') != 'references'],
            'librarySource': combined['source'] if combined else str(library_path) if library_path else None,
            'processMap': flow, 'knowledgeMap': knowledge,
            'howItWorks': _section(human, 'How it works') or 'Walkthrough not completed yet. Read the instructions below.',
            'timeline': api._journal_events(str(directory)),
            'capabilities': api._extract_section_details(api._parse_skill_md(instructions)['body']),
            'journalCount': len(journals)}


def _process_map(skill, resources, combined=None):
    if combined:
        issues = list(combined['issues'])
        issues.extend(_edge_issues(combined['steps'], combined['edges']))
        return {**combined, 'status': 'needs checking' if issues else 'source-anchored draft', 'issues': issues}
    data, path, error = _load_artifact(skill, ('process-map.json', 'FLOW.json'))
    if not isinstance(data, dict):
        return {'status': 'unfinished', 'issues': [error] if error else [], 'steps': [], 'exits': []}
    steps = data.get('steps') or []
    if not isinstance(steps, list):
        return {'status': 'needs checking', 'issues': ['Process steps must be an array'], 'steps': [], 'exits': []}
    if not steps:
        for stage in data.get('stages', []):
            for row in stage.get('steps', stage.get('rows', [])):
                steps.extend(row if isinstance(row, list) else row.get('boxes', [row]))
    projected, issues = [], []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            issues.append('Invalid process step')
            continue
        anchors = step.get('anchors') if isinstance(step.get('anchors'), dict) else {}
        code = _anchor_link(step.get('code') or anchors.get('code'), skill, path.parent, resources)
        ins = _anchor_link(step.get('instructions') or step.get('instruction') or anchors.get('instructions'), skill, path.parent, resources)
        if not code or not ins:
            issues.append('Missing code/instruction declaration: ' + str(step.get('id', index)))
        issues.extend(a['problem'] for a in (code, ins) if a and a.get('problem'))
        projected.append({**step, 'id': step.get('id') or str(index),
                          'title': step.get('title') or step.get('name') or step.get('t'),
                          'kind': step.get('kind') or step.get('k') or 'program',
                          'description': step.get('description') or step.get('summary') or step.get('d'),
                          'codeLink': code, 'instructionLink': ins})
    issues.extend(_edge_issues(projected, data.get('edges', [])))
    return {'status': 'source-anchored draft' if not issues else 'needs checking',
            'source': str(path), 'qualification': data.get('qualification') or 'Walkthrough awaiting human review.',
            'steps': projected, 'edges': data.get('edges', []), 'exits': data.get('exits', []),
            'swarm': data.get('swarm'), 'issues': issues,
            'disagreements': data.get('disagreements', []), 'deliverable': data.get('deliverable') or data.get('outputs')}


def _edge_issues(steps, edges):
    ids = [s.get('id') for s in steps]
    issues = ['Duplicate process step IDs'] if len(ids) != len(set(ids)) else []
    if not isinstance(edges, list):
        return issues + ['Process edges must be an array']
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in ids or edge.get('to') not in ids:
            issues.append('Process edge has a missing step')
    return issues


def _knowledge_map(skill, resources, combined=None):
    data, path, error = ({'nodes': combined['nodes']}, Path(combined['source']), None) if combined else _load_artifact(skill, ('knowledge-map.json', 'knowledge/graph.json', 'graph.json'))
    if not isinstance(data, dict):
        return {'status': 'unfinished', 'issues': [error] if error else [], 'nodes': [],
                'qualification': 'Not drawn yet. No learned geometry or use frequency is available.'}
    nodes = data.get('nodes') or []
    if not isinstance(nodes, list):
        return {'status': 'needs checking', 'issues': ['Knowledge nodes must be an array'], 'nodes': []}
    projected, issues = [], []
    by_id = {str(n.get('id')): n for n in nodes if isinstance(n, dict)}
    if len(by_id) != len(nodes):
        issues.append('Duplicate or invalid knowledge node IDs')
    for node in nodes:
        if not isinstance(node, dict):
            issues.append('Invalid knowledge node')
            continue
        node_id = str(node.get('id'))
        parents = node.get('parent_ids') or ([node['parent']] if node.get('parent') else [])
        if not isinstance(parents, list):
            parents = []
            issues.append('Parent IDs must be an array: ' + node_id)
        depth, seen, parent = 0, {node_id}, (parents[0] if parents else None)
        if len(parents) > 1:
            issues.append('Multiple parents: ' + node_id)
        while parent:
            if str(parent) in seen or str(parent) not in by_id:
                issues.append('Broken or cyclic hierarchy: ' + node_id)
                break
            seen.add(str(parent))
            depth += 1
            ancestor = by_id[str(parent)]
            pp = ancestor.get('parent_ids') or ([ancestor['parent']] if ancestor.get('parent') else [])
            parent = pp[0] if pp else None
        if node.get('ring') is not None and node['ring'] != depth:
            issues.append('Ring disagrees with tree depth: ' + node_id)
        resource_id = node.get('resourceId') or node.get('resource_id') or node.get('resource')
        resource = next((r for r in resources if str(r['id']) == str(resource_id)), None)
        link = None if resource else _anchor_link(node.get('anchor'), skill, path.parent, resources)
        if link:
            resource = next((r for r in resources if r['id'] == link.get('resourceId')), None)
            if link.get('problem'):
                issues.append(link['problem'])
        if not resource:
            issues.append('No real Library target: ' + node_id)
        elif resource.get('problem'):
            issues.append(resource['problem'])
        projected.append({**node, 'id': node_id, 'name': node.get('name') or node.get('title') or node_id,
                          'parent': parents[0] if parents else None, 'depth': depth,
                          'resourceId': resource['id'] if resource else None,
                          'href': resource.get('href') if resource else None})
    return {'status': 'seeded draft' if not issues else 'needs checking', 'source': str(path),
            'qualification': 'Seeded declared hierarchy — not calibrated or learned geometry. Size does not represent use frequency.',
            'nodes': projected, 'issues': issues}


def source_page(skill_id, requested, anchor=''):
    """Exact allowlist of this skill's discovered Library/anchor resources."""
    detail = skill_detail(skill_id)
    if not detail:
        return None
    try:
        raw = Path(requested.replace('\\', '/'))
        if '..' in raw.parts:
            return None
        requested_path = raw.resolve()
    except (OSError, ValueError):
        return None
    targets = [r for r in detail['resources'] if r.get('path') and Path(r['path']).resolve() == requested_path]
    if not targets or not (_path(requested, Path(detail['skill']['source']))
                           or _trusted_origin(requested, detail['skill'])):
        return None
    provenance = next((r['provenance'] for r in targets if r.get('provenance')), {})
    try:
        payload = requested_path.read_bytes()
        text = payload.decode('utf-8-sig')
    except (OSError, UnicodeError):
        return None
    if (provenance.get('freshness') == 'frozen-example' and
            hashlib.sha256(payload).hexdigest() != provenance.get('sha256')):
        return None
    lines = text.splitlines()
    hit = (int(anchor) if str(anchor).isdigit() else
           next((i for i, line in enumerate(lines, 1) if anchor and anchor in line), 0))
    esc = html.escape
    provenance_html = ''
    if provenance.get('freshness'):
        provenance_html = ('<aside class="source-provenance" data-source-freshness="%s">'
                           '<strong>%s</strong><p>Captured: %s</p><p class="path">Captured from: %s</p>'
                           '<p>%s</p><p class="path">Capture SHA-256: %s</p></aside>') % tuple(esc(str(v or '')) for v in (
                               provenance['freshness'],
                               'Frozen historical example — not current state' if provenance['freshness'] == 'frozen-example'
                               else 'Current source — on-disk bytes do not prove live activation',
                               provenance.get('captured_at'), provenance.get('captured_from') or provenance.get('origin'),
                               provenance.get('applicability'), provenance.get('sha256')))
        if (provenance.get('freshness') == 'current-source' and provenance.get('sha256') and
                hashlib.sha256(payload).hexdigest() != provenance['sha256']):
            provenance_html += '<p>Source changed since capture; the current file is shown below.</p>'
    rendered = '\n'.join('<span id="L%d" class="%s"><a href="#L%d">%d</a> %s</span>' %
                         (i, 'hit' if i == hit else '', i, i, esc(line))
                         for i, line in enumerate(lines, 1))
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s — Foundry source</title>
<style>body{margin:0;background:#0f1117;color:#e2e4e9;font:15px/1.5 system-ui}header{padding:18px;border-bottom:1px solid #2e3340}a{color:#9ec0ff}pre{padding:18px;overflow:auto}pre span{display:block;min-height:1.5em}pre a{display:inline-block;width:4em;color:#8b8f9a}.hit{background:#3a2e17;outline:1px solid #e0a84a}h1{font-size:20px;margin:8px 0}.path{overflow-wrap:anywhere;color:#8b8f9a}</style>
<header><a href="/foundry?skill=%s">← %s</a><h1>%s</h1><div class="path">%s</div><p>Read-only source%s</p></header>
%s<pre>%s</pre>%s</html>''' % (esc(requested_path.name), esc(skill_id), esc(detail['skill']['name']),
                           esc(requested_path.name), esc(str(requested_path)),
                           ' · anchor not found' if anchor and not hit else '', provenance_html, rendered,
                           '<script>document.getElementById("L%d")?.scrollIntoView({block:"center"})</script>' % hit if hit else '')


def icon_file(skill_id):
    row = find_skill(skill_id)
    path = Path(row['iconPath']) if row and row.get('iconPath') else None
    return path if path and path.is_file() and _allowed(path) else None
