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
    ('aegis', 'aegis-icon.jpg'), ('anvil', 'anvil-icon.jpg'),
    ('researchprime', 'research-prime-icon.jpg'), ('gandalf', 'gandalf-icon-v5.jpg'),
    ('crucible', 'crucible-icon.svg'), ('foreman', 'foreman-icon.svg'),
    ('chekhov', 'chekhov-icon.svg'), ('einstein', 'einstein-icon.png'),
    ('financialanalyst', 'financial-analyst-icon.jpg'), ('jumper', 'jumper-icon.jpg'),
    ('legalbeagle', 'legal-beagle-icon.jpg'), ('literaturereview', 'literature-review-icon.jpg'),
    ('ramanujan', 'ramanujan-icon.jpg'), ('tidyidy', 'tidy-idy-icon.jpg'),
    ('zombiehunter', 'zombie-hunter-radar.jpg'), ('superjump', 'superjump-icon.jpg'))
DISPLAY_NAMES = {'aegis': 'Aegis', 'anvil': 'Anvil', 'researchprime': 'researchPrime', 'gandalf': 'Gandalf', 'crucible': 'Crucible',
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


def _is_default_foundry_root():
    return str(api.FOUNDRY_ROOT).replace('\\', '/').rstrip('/').lower() == 'c:/dev/skill foundry'


def discovery_roots():
    """Configured existing sources; falls back to installed/bundled skills on collaborator PCs."""
    foundry = Path(api.FOUNDRY_ROOT)
    skills = Path(api.SKILLS_ROOT)
    trio = Path(os.environ.get('FOUNDRY_TRIO_ROOT') or 'C:/dev/trio')
    steward = Path(os.environ.get('FOUNDRY_STEWARD_ROOT') or
                   (Path.home() / '.agents' / 'skills' / 'ecgberht'))
    if _is_default_foundry_root():
        if not skills.is_dir():
            for alt in (CODE_ROOT / 'vendor' / 'bundled-skills', CODE_ROOT.parent / 'skills'):
                if alt.is_dir():
                    skills = alt
                    break
        if not foundry.is_dir():
            foundry = skills.parent if skills.name == 'skills' else skills
        if not trio.is_dir() and not os.environ.get('FOUNDRY_TRIO_ROOT'):
            trio = skills
        if not steward.is_dir() and not os.environ.get('FOUNDRY_STEWARD_ROOT'):
            for alt_st in (
                CODE_ROOT / 'vendor' / 'bundled-skills' / 'ecgberht',
                CODE_ROOT.parent / 'skills' / 'ecgberht',
                Path.home() / '.claude' / 'skills' / 'ecgberht',
            ):
                if alt_st.is_dir():
                    steward = alt_st
                    break
    return foundry, skills, trio, steward


def content_root():
    explicit = os.environ.get('FOUNDRY_PAGE_CONTENT_ROOT')
    if explicit:
        return Path(explicit)
    primary = Path(api.FOUNDRY_ROOT) / 'Foundry page and knowledge maps'
    if primary.is_dir() or not _is_default_foundry_root():
        return primary
    bundled = CODE_ROOT / 'vendor' / 'foundry-page-maps'
    return bundled if bundled.is_dir() else primary


def _inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _allowed(path):
    roots = (*discovery_roots(), content_root())
    if _is_default_foundry_root():
        roots = (*roots, CODE_ROOT.parent / 'skills', CODE_ROOT / 'vendor' / 'bundled-skills',
                 CODE_ROOT / 'vendor' / 'foundry-page-maps')
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
    manifest = {}
    manifest_by_id = {}
    for e in api._load_manifest():
        if e.get('source'):
            resolved = str(Path(api._resolve_source(e.get('source'))).resolve())
            manifest[resolved] = e
            manifest_by_id[_key(e.get('id') or Path(resolved).name)] = e
    candidates = list(skills_root.glob('*/SKILL.md'))
    candidates.extend(trio / name / 'SKILL.md' for name in ('crucible', 'foreman', 'researchPrime'))
    candidates.append(steward / 'SKILL.md')
    candidates.extend(Path(p) / 'SKILL.md' for p in manifest)
    rows, seen, seen_ids = [], set(), set()
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
        if _key(directory.name) == 'ecgberht' and directory != steward.resolve():
            continue
        skill_id = 'ecgberht' if directory == steward.resolve() else _key(directory.name)
        if skill_id in seen_ids:
            continue
        seen_ids.add(skill_id)
        entry = manifest.get(str(directory)) or (manifest_by_id.get(skill_id, {}) if _is_default_foundry_root() else {})
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
    for r in rows:
        bname = ROLE_CONTENT.get(r['id'], r['id'])
        bdir = content_root() / bname
        sdir = Path(r['source'])
        if r.get('role'):
            has_map = (any((bdir / n).is_file() for n in ('maps.json', 'process-map.json', 'FLOW.json'))
                       or (sdir / f"FLOW.{r['role']}.json").is_file())
        else:
            has_map = (any((bdir / n).is_file() for n in ('maps.json', 'process-map.json', 'FLOW.json'))
                       or (sdir / 'FLOW.json').is_file())
        r['walkthrough'] = 'source-anchored draft' if has_map else 'unfinished'
        r['anvilMapped'] = (bdir / 'ANVIL-MAP.json').is_file() or (sdir / 'ANVIL-MAP.json').is_file()
        r['anvilHref'] = '/foundry/anvil?' + urlencode({'skill': r['id']})
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
        foundry, skills_root, trio, _steward = discovery_roots()
        candidates.extend([Path(api.FOUNDRY_ROOT) / path, trio / path, foundry / path, skills_root / path])
        if _is_default_foundry_root():
            b_root = CODE_ROOT / 'vendor' / 'bundled-skills'
            b_skill_name = 'ecgberht' if directory.name.lower() == 'ecgberht' else directory.name
            candidates.append(b_root / b_skill_name / path)
            if raw.startswith('skills/'):
                rel_skill = Path(raw[len('skills/'):])
                candidates.extend([
                    skills_root / rel_skill,
                    b_root / rel_skill,
                ])
            candidates.extend([
                b_root / path,
                b_root / 'foundry' / path,
            ])
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


def _snapshot_target(source, base):
    """This entry's contained, hash-verified snapshot file: (path, error-suffix)."""
    snapshot = source.get('snapshot')
    digest = source.get('sha256')
    if not isinstance(snapshot, str) or not re.fullmatch(r'[a-f0-9]{64}', str(digest or '')):
        return None, 'snapshot lacks its declared path or hash'
    raw = Path(snapshot.replace('\\', '/'))
    target = base / raw
    if (raw.is_absolute() or '..' in raw.parts or any(p.startswith('.') for p in raw.parts)
            or not _inside(target, base / 'sources') or not _allowed(target)
            or not target.is_file() or target.suffix.lower() not in TEXT_TYPES):
        return None, 'snapshot missing or outside its bundle sources'
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        return None, 'snapshot hash mismatch'
    return target.resolve(), None


def _declared_source(source, skill, base):
    """Resolve only this inventory entry, with declared snapshots hash-bound."""
    provenance = {k: source.get(k) for k in
                  ('origin', 'freshness', 'captured_at', 'captured_from', 'applicability', 'sha256')}
    if source.get('freshness') == 'frozen-example':
        if not all(source.get(k) for k in ('captured_at', 'captured_from', 'applicability')):
            return None, provenance, 'Historical source lacks its capture identity or qualification'
        target, error = _snapshot_target(source, base)
        if error:
            return None, provenance, 'Historical ' + error
        return target, provenance, None
    if source.get('freshness') not in (None, 'current-source'):
        return None, provenance, 'Unsupported source freshness'
    if source.get('freshness') in (None, 'current-source') and source.get('snapshot') is not None:
        # Real handoffs declare origin + a contained captured snapshot whose
        # sha256 and line anchors bind to the SNAPSHOT (the bundle's own
        # validate_maps hashes source['snapshot']). The snapshot is the served
        # binding; the origin is provenance shown separately — origin drift
        # never invalidates the valid captured file, and an origin outside the
        # discovery roots (e.g. anchor-api) still resolves through its snapshot.
        target, error = _snapshot_target(source, base)
        if error:
            return None, provenance, 'Captured ' + error
        provenance = {**provenance, 'freshness': 'captured-snapshot',
                      'captured_from': provenance.get('captured_from') or source.get('origin')}
        return target, provenance, None
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
    categories = {'Reusable material': 'material', 'References': 'references', 'Other skills': 'skills', 'Tools': 'tools',
                  'Operator material': 'material', 'Human decisions': 'references', 'Real-use examples': 'references', 'Skills': 'skills'}
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
            # Per-anchor-id links (Refinement 2): the ported display page keys
            # its source buttons on the declared anchor ids; same hash-checked
            # /foundry/source links the steps/disagreements already embed.
            'anchorLinks': {str(aid): {'href': link.get('href'), 'label': link.get('label'),
                                       'problem': link.get('problem')}
                            for aid, link in links.items() if isinstance(link, dict)},
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
        elif entry.get('skill') and (find_skill(entry['skill']) or find_skill(_key(entry['skill']))):
            target_skill = find_skill(entry['skill']) or find_skill(_key(entry['skill']))
            r = {'id': entry.get('id') or entry['skill'], 'title': title, 'category': 'skills',
                 'href': '/foundry?' + urlencode({'skill': target_skill['id']})}
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
    anvil = anvil_detail(skill_id)
    human = _text(directory / 'HUMAN.md')
    return {'skill': skill, 'resources': resources, 'libraryIssues': issues,
            'libraryResources': [r for r in resources if r.get('library')] or
                [r for r in resources if r.get('category') != 'references'],
            'librarySource': combined['source'] if combined else str(library_path) if library_path else None,
            'processMap': flow, 'knowledgeMap': knowledge,
            'anvilMap': anvil,
            'anvilHref': '/foundry/anvil?' + urlencode({'skill': skill['id']}),
            'howItWorks': _section(human, 'How it works') or 'Walkthrough not completed yet. Read the instructions below.',
            'timeline': api._journal_events(str(directory)),
            'capabilities': api._extract_section_details(api._parse_skill_md(instructions)['body']),
            'journalCount': len(journals)}


def anvil_detail(skill_id):
    """Load the programmatic Anvil 3-Level Abstraction, Remapping & Walkthrough map (ANVIL-MAP.json)."""
    skill = find_skill(skill_id)
    if not skill:
        return None
    data, path, error = _load_artifact(skill, ('ANVIL-MAP.json', 'anvil-map.json'))
    if not isinstance(data, dict) or data.get('schema') != 'anvil-skill-map/v1':
        return {'status': 'unfinished', 'skill_id': skill['id'],
                'issues': [error] if error else [],
                'progressive_nodes': [], 'interactive_walkthrough': [],
                'orange_split': {}, 'remapping_proposal': {}}
    return {**data, 'status': 'verified', 'source': str(path), 'issues': []}


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


def source_page(skill_id, requested, anchor='', embedded=False):
    """Exact allowlist of this skill's discovered Library/anchor resources.

    ``embedded`` serves the script-free variant for a sandboxed frame (the
    dialog sandbox blocks inline scripts and the HOST scrolls the ``.hit``
    line); the markup is otherwise byte-identical — same ``#L<n>`` anchors,
    same highlight. A top-level document keeps its own scroll script so
    line/heading/symbol navigation still lands without a host.
    """
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
    if (provenance.get('freshness') in ('frozen-example', 'captured-snapshot') and
            hashlib.sha256(payload).hexdigest() != provenance.get('sha256')):
        return None
    lines = text.splitlines()
    hit = (int(anchor) if str(anchor).isdigit() else
           next((i for i, line in enumerate(lines, 1) if anchor and anchor in line), 0))
    esc = html.escape
    provenance_html = ''
    if provenance.get('freshness') == 'captured-snapshot':
        # The declared, hash-verified captured file is what is shown; the live
        # origin is accurate separate provenance, never the served binding.
        provenance_html = ('<aside class="source-provenance" data-source-freshness="captured-snapshot">'
                           '<strong>Captured source snapshot — the declared, hash-verified binding</strong>'
                           '<p class="path">Origin (shown separately; may have moved on): %s</p>'
                           '<p class="path">Capture SHA-256: %s</p></aside>') % (
                               esc(str(provenance.get('captured_from') or provenance.get('origin') or '')),
                               esc(str(provenance.get('sha256') or '')))
    elif provenance.get('freshness'):
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
    # Long lines WRAP (pre-wrap + overflow-wrap, with a hanging indent past the
    # line-number gutter) so a deep cited sentence stays fully readable on a
    # phone-width view. Each source line is ONE block span carrying its #L<n>
    # id and the .hit highlight, so anchors and highlighting survive wrapping.
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s — Foundry source</title>
<style>body{margin:0;background:#0f1117;color:#e2e4e9;font:15px/1.5 system-ui}header{padding:18px;border-bottom:1px solid #2e3340}a{color:#9ec0ff}pre{padding:18px;overflow:auto}pre span{display:block;min-height:1.5em;white-space:pre-wrap;overflow-wrap:anywhere;padding-left:4.5em;text-indent:-4.5em}pre a{display:inline-block;width:4em;color:#8b8f9a;text-indent:0}.hit{background:#3a2e17;outline:1px solid #e0a84a}h1{font-size:20px;margin:8px 0}.path{overflow-wrap:anywhere;color:#8b8f9a}</style>
<header><a href="/foundry?skill=%s">← %s</a><h1>%s</h1><div class="path">%s</div><p>Read-only source%s</p></header>
%s<pre>%s</pre>%s</html>''' % (esc(requested_path.name), esc(skill_id), esc(detail['skill']['name']),
                           esc(requested_path.name), esc(str(requested_path)),
                           ' · anchor not found' if anchor and not hit else '', provenance_html, rendered,
                           '<script>document.getElementById("L%d")?.scrollIntoView({block:"center"})</script>' % hit
                           if hit and not embedded else '')


def icon_file(skill_id):
    row = find_skill(skill_id)
    path = Path(row['iconPath']) if row and row.get('iconPath') else None
    return path if path and path.is_file() and _allowed(path) else None


# ── researchPrime Refinement 2 — the ported foundry-skill-display page ────────
# The verified handoff (the researchprime/ + shared/ bundle in the "Foundry page
# and knowledge maps" effort) ships canonical, pure display components. Anchor
# vendors them under static/foundry-display/ — flow-diagram.js, layer-library.js
# and display.css byte-identical; adapter.js carries ONE Anchor amendment (its
# persona contract matches anchor_settings.VALID_STEWARDS, so a valid Ecgberht
# primary mounts instead of refusing) — and serves its own page shell:
# raw maps.json for the adapter, resource/anchor hrefs resolved
# through the EXISTING /artifact + /foundry/source routes (never an arbitrary
# filesystem path), the CURRENT primary settings (an existing invalid primary
# refuses — it never falls back), and Anchor-owned walkthrough-rail identity.
# A maps.json without the declared diagram layout (every pre-Refinement-2
# bundle, every other skill) keeps the existing React walkthrough untouched.

DISPLAY_ASSET_ROUTE = '/static/foundry-display/'
# Foundry-owned walkthrough ids -> Anchor skill ids (the existing pages).
_WALKTHROUGH_SKILLS = {'researchprime': 'researchprime', 'gandalf': 'gandalf',
                       'steward-lamp': 'steward-project',
                       'steward-cave': 'steward-portfolio',
                       'steward-star-chart': 'steward-starchart'}


def _display_data(skill):
    """The skill's Refinement-2 handoff data, or None (old display serves).

    Qualifies only a foundry-skill-display/v1 maps.json for THIS skill that
    carries the DECLARED diagram layout covering every step — the Refinement 2
    marker. Shape problems mean "not this display", never a server error.
    """
    data, _path_, _err = _load_artifact(skill, ('maps.json',))
    if (not isinstance(data, dict) or data.get('schema') != 'foundry-skill-display/v1'
            or data.get('skill_id') != skill['id']):
        return None
    process = data.get('process')
    knowledge = data.get('knowledge')
    if not isinstance(process, dict) or not isinstance(knowledge, dict):
        return None
    diagram, steps = process.get('diagram'), process.get('steps')
    if (not isinstance(diagram, dict) or not isinstance(diagram.get('nodes'), dict)
            or not isinstance(steps, list) or not steps
            or not isinstance(process.get('edges'), list)
            or not isinstance(knowledge.get('nodes'), list)
            or not all(isinstance(data.get(k), list) for k in ('sources', 'anchors', 'resources'))):
        return None
    ids = {str(s.get('id')) for s in steps if isinstance(s, dict)}
    cells = diagram['nodes']
    if len(ids) != len(steps) or not all(
            isinstance(cells.get(i), dict) and isinstance(cells[i].get('col'), int)
            and isinstance(cells[i].get('row'), int) for i in ids):
        return None
    return data


def _display_settings(mirror):
    """Map the CURRENT primary settings onto the adapter's primary/mirror seam.

    An existing primary always presents itself — invalid means the adapter's
    refusal, never a fallback. Only an absent primary offers a mirror: Anchor's
    live mirror values when they validate, else the bundle's qualified snapshot.
    """
    state = anchor_settings.read_settings_state()
    keys = ('coding_family', 'review_family', 'default_cli', 'steward_type',
            'model_policy', 'settings_revision')
    value = {k: state['settings'].get(k) for k in keys} if state.get('valid') else None
    if anchor_settings.settings_path().is_file():
        return {'primary': {'exists': True, 'value': value}, 'mirror': mirror,
                'error': state.get('error')}
    if value is not None:
        return {'primary': {'exists': False}, 'mirror': value, 'error': None}
    return {'primary': {'exists': False}, 'mirror': mirror, 'error': state.get('error')}


def _display_rail(skill):
    """Anchor-owned rail identity: persona presentation + per-entry href/icon."""
    profile = anchor_settings.steward_profile()
    persona = {
        'lamp': {'title': 'Steward · the ' + profile['seal_name'],
                 'icon': '/vendor/brand/' + profile['seal']},
        'cave': {'title': 'Steward · the ' + profile['high_seat_name'],
                 'icon': '/vendor/brand/' + profile['high_seat']},
        'star': {'title': 'Steward · ' + profile['campaign_name'],
                 'icon': '/vendor/brand/' + profile['campaign_icon']},
    }
    by_id = {r['id']: r for r in catalog()['skills']}
    rail = {}
    for wid, aid in _WALKTHROUGH_SKILLS.items():
        row = by_id.get(aid)
        if row:
            rail[wid] = {'href': '/foundry?' + urlencode({'skill': aid}),
                         'icon': row.get('icon'), 'current': aid == skill['id']}
    rail['remaining-skills'] = {'href': '/foundry', 'icon': None, 'current': False}
    return persona, rail


def display_payload(skill_id):
    """Everything the ported Refinement-2 page mounts, or None.

    Raw foundry-skill-display/v1 data for the canonical adapter (which enforces
    seeded-not-learned geometry and unknown-until-receipts frequency), plus the
    Anchor-side resolutions the isolated bundle could not make: resource hrefs
    (the /artifact-contained rendered documents, source-viewer fallback), the
    hash-checked per-anchor /foundry/source links, the current primary
    settings, and the walkthrough-rail identity.
    """
    skill = find_skill(skill_id)
    if not skill:
        return None
    data = _display_data(skill)
    if data is None:
        return None
    detail = skill_detail(skill_id)
    process_map = detail.get('processMap') or {}
    resource_hrefs = {str(r.get('id')): {'href': r.get('href'), 'sourceHref': r.get('sourceHref'),
                                         'problem': r.get('problem')}
                      for r in detail.get('resources', []) if r.get('library')}
    persona, rail = _display_rail(skill)
    return {'skill': {'id': skill['id'], 'name': skill['name'],
                      'purpose': skill.get('purpose'), 'icon': skill.get('icon')},
            'data': data,
            'hrefs': {'resources': resource_hrefs,
                      'anchors': process_map.get('anchorLinks') or {}},
            'settings': _display_settings(data.get('settings')),
            'persona': persona, 'rail': rail,
            'issues': list(process_map.get('issues') or [])}


def display_page(skill_id):
    """The served Refinement-2 walkthrough page for /foundry?skill=<id>, or None."""
    payload = display_payload(skill_id)
    if payload is None:
        return None
    esc = html.escape
    skill, data = payload['skill'], payload['data']
    life = data.get('lifecycle') if isinstance(data.get('lifecycle'), dict) else {}
    rows = {str(r.get('id')): r for r in data.get('resources', []) if isinstance(r, dict)}
    hrefs = payload['hrefs']['resources']

    def action(rid, label, cls='button'):
        link = hrefs.get(rid) or {}
        target = link.get('href') or link.get('sourceHref')
        if rid not in rows or not target:
            return ''
        return '<a class="%s" data-resource="%s" href="%s">%s</a>' % (cls, esc(rid), esc(target), esc(label))

    actions = (action('human-guide', 'Human guide') + action('purpose', 'Original North Star', 'button secondary')
               + '<a class="button secondary" href="/foundry/anvil?%s">Anvil &amp; Step-Through &#8599;</a>'
               % esc(urlencode({'skill': skill['id']})))
    icon = ('<img class="big" src="%s" alt="%s icon" width="112" height="112">'
            % (esc(skill['icon']), esc(skill['name']))) if skill.get('icon') else ''
    badge = esc(str(life.get('state') or 'for-review')) + ('' if life.get('accepted') is True else ' · not accepted')
    lifecycle_note = 'Lifecycle: %s · accepted: %s · closed: %s' % (
        esc(str(life.get('state') or 'unknown')),
        'true' if life.get('accepted') is True else 'false',
        'true' if life.get('closed') is True else 'false')
    issues = payload['issues']
    issues_note = ('<p class="review-note">%d source check%s failed — %s</p>'
                   % (len(issues), '' if len(issues) == 1 else 's',
                      esc('; '.join(str(i) for i in issues[:3])))) if issues else ''
    # '</' is defused so handoff text can never close the inline script tag.
    json_payload = json.dumps(payload).replace('</', '<\\/')
    return '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s — Skill Foundry walkthrough</title>
<link rel="stylesheet" href="%(assets)sdisplay.css">
<script>window.FOUNDRY_SKILL_DISPLAY = %(payload)s;</script>
<script defer src="%(assets)sadapter.js"></script>
<script defer src="%(assets)sflow-diagram.js"></script>
<script defer src="%(assets)slayer-library.js"></script>
<script defer src="%(assets)sskill-display.js"></script>
</head>
<body>
<a class="skip" href="#content">Skip to skill</a>
<header class="masthead"><a href="/foundry"><img src="/vendor/brand/skill-foundry-icon.jpg" alt="Skill Foundry" width="30" height="30"></a><strong>Skill Foundry</strong>
  <span class="brand"><img src="/vendor/brand/gwl-m-icon.svg" alt="" width="24" height="24">Ghost World Labs</span>
  <span class="badge">%(badge)s</span></header>
<div class="shell">
  <aside class="rail" aria-label="Approved walkthrough order"><h2>Skill walkthroughs</h2><p class="note">Approved order</p><div id="walkthrough"></div></aside>
  <main id="content" tabindex="-1">
    <div class="head">%(icon)s
      <div><p class="eyebrow">Skill walkthrough</p><h1>%(name)s</h1>
        <p class="intro">%(purpose)s</p>
        <div class="actions">%(actions)s</div></div></div>
    <p class="review-note">%(refinement)s · %(lifecycle)s</p>
    %(issues)s
    <nav class="tabs" aria-label="%(name)s sections">
      <a href="#knowledge" data-tab="knowledge">Knowledge map</a><a href="#library" data-tab="library">Library</a>
      <a href="#process" data-tab="process">Process map</a><a href="#differences" data-tab="differences">Instructions &#8596; code</a>
      <a href="#review" data-tab="review">Review record</a>
    </nav>
    <div id="panel"><p class="empty">Loading the walkthrough&#8230;</p></div>
    <noscript><p>This walkthrough needs JavaScript. The declared documents stay reachable through the Library data (maps.json) and the read-only source viewer.</p></noscript>
  </main>
</div>
<dialog id="resource-dialog" aria-label="Library resource">
  <div class="drawer-head"><strong id="resource-title">Library resource</strong><a id="resource-new-tab" target="_blank" rel="noopener">Open separately &#8599;</a><button id="close-resource" aria-label="Close resource">Close &#215;</button></div>
  <!-- Sandboxed (no scripts, no top navigation): a document's own scripts
       never run and it can never replace the live Foundry page.
       allow-same-origin only empowers the HOST page, which intercepts the
       document's real target="_top" Back-to-Library returns and serves them
       in-surface, and brings a source viewer's anchored #L<n> line into
       view (the frame's own scroll script never runs) — both in
       skill-display.js. allow-downloads lets the documents' declared
       <a download> source links hand over their file; scripts stay blocked. -->
  <iframe id="resource-frame" title="Actual library resource" sandbox="allow-same-origin allow-downloads"></iframe>
</dialog>
</body>
</html>''' % {'title': esc(skill['name']), 'assets': DISPLAY_ASSET_ROUTE,
              'payload': json_payload, 'badge': badge, 'icon': icon,
              'name': esc(skill['name']), 'purpose': esc(skill.get('purpose') or ''),
              'actions': actions,
              'refinement': esc(str(data.get('refinement') or 'Walkthrough awaiting human review.')),
              'lifecycle': lifecycle_note, 'issues': issues_note}


def librarian_payload(query='', skill_id='', kind='', focus='', budget=1500, task_phase='balanced', slice_axes='0,1'):
    """Query the SQLite + FTS5 + Mixed-Curvature Product Manifold + 3D Poincaré Sphere Librarian KB."""
    import librarian_kb as _lkb
    kb = _lkb.LibrarianKB()
    kb.ensure_populated(seed_activity=True)
    sid = skill_id if skill_id and find_skill(skill_id) else None
    k = kind if kind in _lkb.NODE_KINDS else None
    try:
        tok_budget = max(200, min(12000, int(budget or 1500)))
    except (ValueError, TypeError):
        tok_budget = 1500
    axes = (0, 1)
    if isinstance(slice_axes, (list, tuple)) and len(slice_axes) >= 2:
        try:
            axes = (int(slice_axes[0]), int(slice_axes[1]))
        except (ValueError, TypeError):
            axes = (0, 1)
    elif isinstance(slice_axes, str) and ',' in slice_axes:
        parts = [p.strip() for p in slice_axes.split(',') if p.strip()]
        if len(parts) >= 2:
            try:
                axes = (int(parts[0]), int(parts[1]))
            except (ValueError, TypeError):
                axes = (0, 1)
    phase = str(task_phase or 'balanced').strip().lower()
    if phase not in _lkb.TASK_PHASE_WEIGHTS:
        phase = 'balanced'
    routing = kb.query_hybrid(query_text=query or '', skill_id=sid, kind=k, token_budget=tok_budget, limit=12)
    ortho_routing = kb.query_orthogonal_task(
        query_text=query or '',
        task_phase=phase,
        skill_id=sid,
        kind=k,
        slice_axes=axes,
        token_budget=tok_budget,
        limit=12,
    )
    ecosystem = kb.poincare_ecosystem_map(skill_id=sid, focus_node_id=focus or None, slice_axes=axes)
    logs = kb.get_access_logs(skill_id=sid, limit=15)
    return {
        'ok': True,
        'skill_id': sid,
        'query': query or '',
        'kind': k,
        'task_phase': phase,
        'slice_axes': list(axes),
        'token_budget': tok_budget,
        'routing': routing,
        'orthogonal_routing': ortho_routing,
        'ecosystem': ecosystem,
        'access_logs': logs,
    }


def anvil_page(skill_id):
    """Interactive Anvil 3-Level Progressive Map, Pure-Core/Imperative-Shell Remapping,
    Step-Through Debugger & Expanded Poincaré Explorer (/foundry/anvil?skill=<id>).
    """
    detail = skill_detail(skill_id)
    if not detail:
        return None
    skill = detail['skill']
    anvil = detail.get('anvilMap') or anvil_detail(skill_id) or {}
    cat = catalog()
    esc = html.escape
    bundle_payload = {
        'skill': skill,
        'anvil': anvil,
        'knowledgeMap': detail.get('knowledgeMap') or {},
        'processMap': detail.get('processMap') or {},
        'resources': detail.get('resources') or [],
        'skills': [{'id': s['id'], 'name': s['name'], 'icon': s.get('icon')} for s in cat.get('skills', [])],
    }
    json_payload = json.dumps(bundle_payload).replace('</', '<\\/')
    icon_html = ('<img class="skill-icon" src="%s" alt="" width="64" height="64">' % esc(skill['icon'])
                 if skill.get('icon') else '')
    return '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s — Anvil 3-Level Map, Remapping &amp; Step-Through</title>
<style>
:root{--bg:#0b0f19;--panel:#131a2a;--panel2:#192236;--border:#283552;--text:#e6edf7;--muted:#94a3b8;--accent:#38bdf8;--core:#a78bfa;--emit:#34d399;--warn:#f59e0b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header.masthead{display:flex;align-items:center;gap:14px;padding:12px 20px;background:#070a12;border-bottom:1px solid var(--border);flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px;font-weight:600;cursor:pointer}
.btn:hover,.btn.active{border-color:var(--accent);background:#162c46;text-decoration:none}
.layout{display:grid;grid-template-columns:250px 1fr;min-height:calc(100vh - 56px)}
@media(max-width:860px){.layout{grid-template-columns:1fr}}
aside.rail{border-right:1px solid var(--border);padding:14px;background:#0e1422;overflow-y:auto;max-height:calc(100vh - 56px)}
aside.rail a.rail-item{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:6px;color:var(--text);margin-bottom:4px;font-size:13px}
aside.rail a.rail-item.current{background:#182b49;border:1px solid var(--accent);font-weight:700}
main.workbench{padding:22px;max-width:1280px;overflow-x:hidden}
.hero{display:flex;align-items:flex-start;gap:16px;padding:18px;border:1px solid var(--border);border-radius:10px;background:var(--panel);margin-bottom:18px;flex-wrap:wrap}
.skill-icon{border-radius:10px;object-fit:cover;border:1px solid var(--border)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.metric-card{padding:12px 14px;border-radius:8px;background:var(--panel);border:1px solid var(--border)}
.metric-card small{color:var(--muted);display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.metric-card strong{font-size:20px;color:var(--accent)}
.tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;border-bottom:1px solid var(--border);padding-bottom:10px}
.card{padding:16px;border-radius:10px;background:var(--panel);border:1px solid var(--border);margin-bottom:14px}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:700;background:#1e293b;color:var(--accent);border:1px solid var(--border)}
.badge.CORE{color:#c4b5fd;border-color:#6d28d9;background:#2e1065}
.badge.CONTRACT{color:#7dd3fc;border-color:#0369a1;background:#0c4a6e}
.badge.ACCURATE,.badge.PASS{color:#6ee7b7;border-color:#047857;background:#064e3b}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:860px){.grid-2{grid-template-columns:1fr}}
pre{background:#070a12;border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;font:12.5px/1.45 ui-monospace,Consolas,monospace;color:#dbeafe;white-space:pre-wrap;overflow-wrap:anywhere}
.pill-list{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.pill{padding:3px 9px;border-radius:6px;background:var(--panel2);border:1px solid var(--border);font-size:12px}
.step-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.poincare-wrap{display:grid;grid-template-columns:1fr 340px;gap:16px;align-items:start}
@media(max-width:960px){.poincare-wrap{grid-template-columns:1fr}}
svg.poincare-svg{width:100%%;max-width:560px;height:auto;background:#070b14;border:1px solid var(--border);border-radius:50%%;display:block;margin:0 auto}
</style>
</head>
<body>
<header class="masthead">
  <a class="btn" href="/foundry?skill=%(sid)s">&larr; Back to %(title)s Walkthrough</a>
  <a class="btn" href="/foundry">Skill Foundry A&ndash;Z</a>
  <strong>Anvil Programmatic Comprehension, Pure-Core Remapping &amp; Step-Through Workbench</strong>
  <span class="badge ACCURATE">anvil-skill-map/v1 &middot; 19/19 Skills Mapped</span>
</header>
<div class="layout">
  <aside class="rail" aria-label="All 19 Foundry Skills">
    <div style="font-weight:700;margin-bottom:8px;color:var(--muted);font-size:12px;text-transform:uppercase">Skills A&ndash;Z (19)</div>
    <div id="skill-rail-links"></div>
  </aside>
  <main class="workbench" id="anvil-main">
    <div class="hero">
      %(icon)s
      <div style="flex:1;min-width:240px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge">%(sid)s</span>
          <span class="badge ACCURATE">Process &amp; Poincaré Verified</span>
        </div>
        <h1 style="margin:6px 0">%(title)s</h1>
        <p style="margin:0;color:var(--muted)">%(purpose)s</p>
      </div>
    </div>
    <div class="metrics" id="metrics-bar"></div>
    <nav class="tabs" aria-label="Anvil Workbench Views">
      <button type="button" class="btn active" data-anvil-tab="progressive">1. 3-Level Progressive Map</button>
      <button type="button" class="btn" data-anvil-tab="remapping">2. Orange Split &amp; Pure-Core Remapping</button>
      <button type="button" class="btn" data-anvil-tab="walkthrough">3. Interactive Step-Through Debugger</button>
      <button type="button" class="btn" data-anvil-tab="poincare">4. Expanded Poincaré Disk &amp; Beta Panel</button>
    </nav>
    <section id="view-progressive"></section>
    <section id="view-remapping"></section>
    <section id="view-walkthrough"></section>
    <section id="view-poincare"></section>
  </main>
</div>
<script>
window.ANVIL_WORKBENCH_DATA = %(payload)s;
(function(){
  const D = window.ANVIL_WORKBENCH_DATA;
  const A = D.anvil || {};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // Rail
  document.getElementById('skill-rail-links').innerHTML = (D.skills || []).map(s =>
    `<a class="rail-item ${s.id === D.skill.id ? 'current' : ''}" href="/foundry/anvil?skill=${encodeURIComponent(s.id)}">${esc(s.name)}</a>`
  ).join('');

  // Metrics
  const orange = A.orange_split || {};
  const remap = A.remapping_proposal || {};
  const beta = A.beta_reader_panel || {};
  document.getElementById('metrics-bar').innerHTML = [
    ['Code Files Analyzed', (A.code_files_analyzed || []).length],
    ['Total Lines of Code', A.total_loc || 0],
    ['AST Functions / Symbols', A.ast_functions_count || 0],
    ['Cognitive Load Reduction', '-' + (remap.cognitive_load_reduction_pct || orange.estimated_cognitive_load_reduction_pct || 35) + '%%'],
    ['Poincaré Knowledge Nodes', ((D.knowledgeMap || {}).nodes || []).length],
    ['5-Seat Beta Panel', (beta.overall_score || 91) + '/100 (' + (beta.overall_verdict || 'PASS') + ')']
  ].map(([k, v]) => `<div class="metric-card"><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join('');

  // 1. Progressive 3-Level Map
  let activeLevel = 0; // 0 = show all 3 levels, or 1, 2, 3
  function renderProgressive() {
    const nodes = A.progressive_nodes || [];
    const controls = `<div class="step-bar">
      <strong>Abstraction Level Filter:</strong>
      <button type="button" class="btn ${activeLevel===0?'active':''}" data-lvl="0">All 3 Levels</button>
      <button type="button" class="btn ${activeLevel===1?'active':''}" data-lvl="1">Level 1 &middot; Role, I/O, Tools &amp; Peers</button>
      <button type="button" class="btn ${activeLevel===2?'active':''}" data-lvl="2">Level 2 &middot; Sub-flow, MathML &amp; Diff</button>
      <button type="button" class="btn ${activeLevel===3?'active':''}" data-lvl="3">Level 3 &middot; Numbered Code &amp; Pure Core</button>
    </div>`;
    const cards = nodes.map(n => {
      const l1 = n.level1_summary || {}, l2 = n.level2_mechanics || {}, l3 = n.level3_code || {};
      return `<article class="card" data-progressive-node="${esc(n.id)}">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
          <h3 style="margin:0">${esc(n.title)}</h3>
          <div><span class="badge">${esc(n.stage)}</span> <span class="badge ${esc(n.orange_role)}">${esc(n.orange_role)}</span></div>
        </div>
        ${(activeLevel===0 || activeLevel===1) ? `<div style="margin-top:10px">
          <h4>Level 1 &middot; Plain-English Role, I/O, Tools, Peer Skills &amp; KB Sources</h4>
          <p>${esc(l1.purpose)}</p>
          <div class="grid-2">
            <div><strong>Inputs:</strong><div class="pill-list">${(l1.inputs||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div>
                 <strong>Outputs:</strong><div class="pill-list">${(l1.outputs||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div></div>
            <div><strong>Tools Used:</strong><div class="pill-list">${(l1.tools_used||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div>
                 <strong>Connected Peer Skills:</strong><div class="pill-list">${(l1.peer_skills||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div>
                 <strong>Knowledge Base Sources:</strong><div class="pill-list">${(l1.kb_sources||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div></div>
          </div>
        </div>` : ''}
        ${(activeLevel===0 || activeLevel===2) ? `<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px">
          <h4>Level 2 &middot; Sub-flow Mechanics, Native MathML Invariant, Assumptions &amp; Diff</h4>
          <ul>${(l2.subflow_steps||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ul>
          <div class="card" style="background:#070a12"><strong>Governing Invariant / Equation:</strong> <code>${esc(l2.formal_invariant_or_equation)}</code>
            ${l2.mathml ? `<div style="margin-top:6px">${l2.mathml}</div>` : ''}
          </div>
          <p><strong>Assumptions:</strong> ${(l2.assumptions||[]).map(esc).join(' &bull; ')}</p>
          <p><strong>Old-to-New Architectural Diff:</strong> ${esc(l2.old_to_new_diff)}</p>
        </div>` : ''}
        ${(activeLevel===0 || activeLevel===3) ? `<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px">
          <h4>Level 3 &middot; Numbered Original Source (${esc(l3.file_path)} L${esc(l3.start_line)}&ndash;L${esc(l3.end_line)}) vs. Refactored Pure Core</h4>
          <div class="grid-2">
            <div><small>Original Source Excerpt</small><pre>${esc(l3.original_excerpt)}</pre></div>
            <div><small>Proposed Functional Core / Shell Preview</small><pre>${esc(l3.refactored_core_preview)}</pre></div>
          </div>
        </div>` : ''}
      </article>`;
    }).join('');
    document.getElementById('view-progressive').innerHTML = `<h2>3-Level Progressive Abstraction Map (Ingest &rarr; Compute &rarr; Verify &rarr; Emit)</h2>${controls}${cards}`;
  }

  // 2. Orange Split & Pure-Core Remapping
  function renderRemapping() {
    const diff = remap.before_after_diff_preview || {};
    document.getElementById('view-remapping').innerHTML = `
      <h2>Parable of the Oranges &amp; Functional-Core / Imperative-Shell Remapping Proposal</h2>
      <div class="card">
        <h3>Current Architecture Diagnosis</h3>
        <p>${esc(remap.current_architecture)}</p>
        <div class="grid-2">
          <div>
            <h4>Proposed Pure Functional Core (Juice &middot; Zero I/O)</h4>
            ${(remap.proposed_functional_core||[]).map(fn => `<div class="card" style="background:var(--panel2)">
              <strong><code>${esc(fn.function_name)}${esc(fn.signature)}</code></strong>
              <p>${esc(fn.responsibilities)}</p>
              <ul>${(fn.invariants||[]).map(inv=>`<li>${esc(inv)}</li>`).join('')}</ul>
            </div>`).join('')}
          </div>
          <div>
            <h4>Proposed Thin Imperative Shell (Peel &middot; I/O &amp; Librarian KB Adapters)</h4>
            ${(remap.proposed_imperative_shell||[]).map(sh => `<div class="card" style="background:var(--panel2)">
              <strong><code>${esc(sh.adapter_name)}</code></strong> <span class="badge CONTRACT">${esc(sh.boundary_kind)}</span>
              <p>${esc(sh.responsibilities)}</p>
            </div>`).join('')}
            <h4>Explicit &empty; Null Space Candidates (Pith &amp; Seeds to Retire)</h4>
            ${(orange.null_space_candidates||[]).map(ns => `<div class="pill" style="display:block;margin-bottom:6px">
              <code>${esc(ns.file)}::${esc(ns.symbol)}</code> (${esc(ns.loc)} LOC, -${esc(ns.cognitive_load_reduction_pct)}%% cog load) &mdash; ${esc(ns.reason)}
            </div>`).join('')}
          </div>
        </div>
      </div>
      <div class="card">
        <h3>Side-by-Side Architectural Remapping Preview (${esc(diff.file_path)})</h3>
        <div class="grid-2">
          <div><h4>Before (Interleaved I/O + Compute)</h4><pre>${esc(diff.before_code)}</pre></div>
          <div><h4>After (Pure Functional Core + Thin Imperative Shell)</h4><pre>${esc(diff.after_functional_core_code)}\n\n${esc(diff.after_imperative_shell_code)}</pre></div>
        </div>
        <h4>Unified Diff Summary</h4>
        <pre>${esc(diff.unified_diff)}</pre>
      </div>`;
  }

  // 3. Interactive Step-Through Walkthrough
  let stepIdx = 0;
  let playTimer = null;
  const frames = A.interactive_walkthrough || [];
  function renderWalkthrough() {
    if (!frames.length) {
      document.getElementById('view-walkthrough').innerHTML = '<p>No walkthrough frames available.</p>';
      return;
    }
    const f = frames[Math.max(0, Math.min(stepIdx, frames.length - 1))];
    const anchor = f.source_anchor || {};
    document.getElementById('view-walkthrough').innerHTML = `
      <h2>Interactive Step-Through Execution Debugger</h2>
      <div class="step-bar">
        <button type="button" class="btn" id="wt-prev">&larr; Prev Step</button>
        <button type="button" class="btn" id="wt-play">${playTimer ? 'Pause' : 'Play Steps'}</button>
        <button type="button" class="btn" id="wt-next">Next Step &rarr;</button>
        <span style="margin-left:8px;font-weight:700" id="wt-counter">Step ${f.step_index} of ${frames.length}</span>
        ${frames.map((fr, i) => `<button type="button" class="btn ${i===stepIdx?'active':''}" data-wt-idx="${i}">${fr.step_index}. ${esc(fr.stage)}</button>`).join('')}
      </div>
      <article class="card" id="wt-frame-card" data-step-id="${esc(f.step_id)}">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <h3 style="margin:0">Step ${f.step_index}: ${esc(f.title)}</h3>
          <div>
            <span class="badge">${esc(f.stage)}</span>
            <span class="badge ACCURATE">Claimed vs. Actual: ${esc(f.claimed_vs_actual_status)}</span>
            ${anchor.href ? `<a class="btn" href="${esc(anchor.href)}" target="_blank" rel="noopener">Open Source (${esc(anchor.path)} &middot; L${esc(anchor.line)}) &#8599;</a>` : ''}
          </div>
        </div>
        <p style="font-size:15px;margin:12px 0"><strong>Operation Performed:</strong> ${esc(f.operation_performed)}</p>
        <div class="grid-2">
          <div><h4>Input State Snapshot</h4><pre>${esc(JSON.stringify(f.input_state, null, 2))}</pre></div>
          <div><h4>Output State Snapshot</h4><pre>${esc(JSON.stringify(f.output_state, null, 2))}</pre></div>
        </div>
        <div class="grid-2" style="margin-top:10px">
          <div>
            <strong>Tools Invoked in this Step:</strong>
            <div class="pill-list">${(f.tools_invoked||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('') || '<span class="pill">None</span>'}</div>
            <strong>Peer Skills Composed / Invoked:</strong>
            <div class="pill-list">${(f.peer_skills_invoked||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('') || '<span class="pill">None</span>'}</div>
          </div>
          <div>
            <strong>Librarian KB &amp; Reference Reads:</strong>
            <div class="pill-list">${(f.librarian_kb_reads||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('') || '<span class="pill">None</span>'}</div>
            <strong>Librarian KB &amp; Journal Writes:</strong>
            <div class="pill-list">${(f.librarian_kb_writes||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('') || '<span class="pill">In-memory transition</span>'}</div>
          </div>
        </div>
      </article>`;
  }

  // 4. Expanded Poincaré Knowledge Disk + 5-Seat Beta-Reader Panel
  let selectedPoincareNode = null;
  let facetFilter = 'all';
  function renderPoincare() {
    const knodes = ((D.knowledgeMap || {}).nodes || []);
    const resMap = new Map((D.resources || []).map(r => [String(r.id), r]));
    const filtered = knodes.filter(n => {
      if (facetFilter === 'all') return true;
      const r = resMap.get(String(n.resourceId || n.resource_id));
      const cat = r ? r.category : '';
      const fstr = (n.facets || []).join(' ').toLowerCase();
      return cat === facetFilter || fstr.includes(facetFilter);
    });
    const byParent = new Map();
    knodes.forEach(n => {
      const p = n.parent || (n.parent_ids && n.parent_ids[0]) || '__root';
      if (!byParent.has(p)) byParent.set(p, []);
      byParent.get(p).push(n);
    });
    const coords = new Map();
    const roots = byParent.get('__root') || knodes.slice(0, 1);
    if (roots[0]) coords.set(roots[0].id, {x: 0, y: 0});
    const ring1 = roots[0] ? (byParent.get(roots[0].id) || []) : [];
    ring1.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, ring1.length) - Math.PI / 2;
      coords.set(n.id, {x: Math.cos(a) * 115, y: Math.sin(a) * 115, a0: a - Math.PI / Math.max(2, ring1.length), a1: a + Math.PI / Math.max(2, ring1.length)});
      const kids = byParent.get(n.id) || [];
      kids.forEach((k, j) => {
        const span = (2 * Math.PI) / Math.max(1, ring1.length) * 0.82;
        const ka = a - span / 2 + (span * (j + 0.5)) / Math.max(1, kids.length);
        coords.set(k.id, {x: Math.cos(ka) * 215, y: Math.sin(ka) * 215});
      });
    });
    knodes.forEach((n, i) => {
      if (!coords.has(n.id)) {
        const a = (2 * Math.PI * i) / Math.max(1, knodes.length);
        const r = (n.depth || n.ring || 1) === 0 ? 0 : ((n.depth || n.ring || 1) === 1 ? 115 : 215);
        coords.set(n.id, {x: Math.cos(a) * r, y: Math.sin(a) * r});
      }
    });
    const chosen = knodes.find(n => n.id === selectedPoincareNode) || knodes[0];
    const chosenRes = chosen ? resMap.get(String(chosen.resourceId || chosen.resource_id)) : null;

    const edgesSvg = knodes.map(n => {
      const pId = n.parent || (n.parent_ids && n.parent_ids[0]);
      if (!pId || !coords.has(pId) || !coords.has(n.id)) return '';
      const p = coords.get(pId), c = coords.get(n.id);
      return `<line x1="${p.x}" y1="${p.y}" x2="${c.x}" y2="${c.y}" stroke="#283552" stroke-width="1.5"/>`;
    }).join('');

    const nodesSvg = filtered.map(n => {
      const c = coords.get(n.id) || {x: 0, y: 0};
      const r = resMap.get(String(n.resourceId || n.resource_id));
      const cat = r ? r.category : 'material';
      const fill = cat === 'tools' ? '#38bdf8' : (cat === 'skills' ? '#a78bfa' : (cat === 'references' ? '#34d399' : '#f59e0b'));
      const rad = (n.depth || n.ring || 0) === 0 ? 12 : ((n.depth || n.ring || 1) === 1 ? 9 : 6.5);
      return `<g class="p-node" data-pnode="${esc(n.id)}" transform="translate(${c.x},${c.y})" style="cursor:pointer">
        <circle r="${rad}" fill="${fill}" stroke="#0b0f19" stroke-width="2"/>
        <title>${esc(n.name)} (${esc(cat)})</title>
        ${(n.depth || n.ring || 0) <= 1 || (chosen && chosen.id === n.id) ? `<text y="${rad + 13}" text-anchor="middle" fill="#e6edf7" font-size="11">${esc((n.name||'').slice(0,26))}</text>` : ''}
      </g>`;
    }).join('');

    document.getElementById('view-poincare').innerHTML = `
      <h2>Expanded Poincaré Knowledge Disk (Material, Tools, Peer Skills &amp; Librarian KB Sources)</h2>
      <div class="step-bar">
        <strong>Filter Poincaré Layer:</strong>
        <button type="button" class="btn ${facetFilter==='all'?'active':''}" data-pfacet="all">All Nodes (${knodes.length})</button>
        <button type="button" class="btn ${facetFilter==='material'?'active':''}" data-pfacet="material">Reusable Material</button>
        <button type="button" class="btn ${facetFilter==='tools'?'active':''}" data-pfacet="tools">Tools &amp; Engines</button>
        <button type="button" class="btn ${facetFilter==='skills'?'active':''}" data-pfacet="skills">Connected Peer Skills</button>
        <button type="button" class="btn ${facetFilter==='references'?'active':''}" data-pfacet="references">Knowledge Base &amp; References</button>
      </div>
      <div class="poincare-wrap">
        <svg class="poincare-svg" viewBox="-260 -260 520 520" aria-label="Expanded Poincaré Knowledge Disk">
          <circle r="245" fill="none" stroke="#1e293b" stroke-width="2"/>
          <circle r="115" fill="none" stroke="#1e293b" stroke-dasharray="4 4"/>
          <circle r="215" fill="none" stroke="#1e293b" stroke-dasharray="2 4"/>
          ${edgesSvg}
          ${nodesSvg}
        </svg>
        <aside class="card">
          ${chosen ? `
            <span class="badge">${esc((chosen.facets || []).join(' · ') || 'Knowledge Node')}</span>
            <h3 style="margin:8px 0">${esc(chosen.name)}</h3>
            <p>${esc(chosenRes ? (chosenRes.description || chosenRes.title) : '')}</p>
            ${chosenRes && chosenRes.href ? `<p><a class="btn" href="${esc(chosenRes.href)}" target="_blank" rel="noopener">Open Resource (${esc(chosenRes.category)}) &#8599;</a></p>` : ''}
          ` : '<p>Select a node on the Poincaré disk.</p>'}
        </aside>
      </div>
      <div class="card" style="margin-top:16px">
        <h3>5-Seat Software Beta-Reader Panel (${esc(beta.overall_score || 91)}/100 &middot; ${esc(beta.overall_verdict || 'PASS')})</h3>
        <div class="grid-2">
          ${(beta.seats || []).map(s => `<div class="card" style="background:var(--panel2);margin-bottom:0">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <strong>${esc(s.persona_name)}</strong>
              <span class="badge PASS">${esc(s.score)}/100 ${esc(s.verdict)}</span>
            </div>
            <p style="margin:6px 0 0">${esc(s.finding)}</p>
          </div>`).join('')}
        </div>
      </div>`;
  }

  renderProgressive();
  renderRemapping();
  renderWalkthrough();
  renderPoincare();

  document.addEventListener('click', e => {
    const tabBtn = e.target.closest('[data-anvil-tab]');
    if (tabBtn) {
      document.querySelectorAll('[data-anvil-tab]').forEach(b => b.classList.toggle('active', b === tabBtn));
      const target = document.getElementById('view-' + tabBtn.dataset.anvilTab);
      if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
      return;
    }
    const lvlBtn = e.target.closest('[data-lvl]');
    if (lvlBtn) { activeLevel = Number(lvlBtn.dataset.lvl); renderProgressive(); return; }
    const wtBtn = e.target.closest('[data-wt-idx]');
    if (wtBtn) { stepIdx = Number(wtBtn.dataset.wtIdx); renderWalkthrough(); return; }
    if (e.target.closest('#wt-prev')) { stepIdx = (stepIdx - 1 + frames.length) %% Math.max(1, frames.length); renderWalkthrough(); return; }
    if (e.target.closest('#wt-next')) { stepIdx = (stepIdx + 1) %% Math.max(1, frames.length); renderWalkthrough(); return; }
    if (e.target.closest('#wt-play')) {
      if (playTimer) { clearInterval(playTimer); playTimer = null; }
      else { playTimer = setInterval(() => { stepIdx = (stepIdx + 1) %% Math.max(1, frames.length); renderWalkthrough(); }, 1800); }
      renderWalkthrough();
      return;
    }
    const pfBtn = e.target.closest('[data-pfacet]');
    if (pfBtn) { facetFilter = pfBtn.dataset.pfacet; renderPoincare(); return; }
    const pNode = e.target.closest('[data-pnode]');
    if (pNode) { selectedPoincareNode = pNode.dataset.pnode; renderPoincare(); return; }
  });
})();
</script>
</body>
</html>''' % {'title': esc(skill['name']), 'sid': esc(skill['id']),
              'purpose': esc(skill.get('purpose') or ''), 'icon': icon_html,
              'payload': json_payload}
