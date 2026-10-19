"""Real route/resource contracts and built-browser Foundry walkthrough checks.

Hermetic source roots and an ephemeral Anchor HTTP server; no model calls,
cockpit event reads, sleep POSTs or production session activation.
"""
import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import foundry_page as page


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content) if not isinstance(content, str) else content, encoding='utf-8')
    return path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    foundry = tmp_path / 'foundry'
    skills = foundry / 'skills'
    trio = tmp_path / 'trio'
    steward = tmp_path / 'steward'
    content = foundry / 'Foundry page and knowledge maps'
    instruction = write(trio / 'researchPrime/SKILL.md', '---\nname: researchPrime\ndescription: Research a question.\n---\n## North Star\nFind a supported answer.\n## Entry\nStart here.\n<unsafe>\n')
    program = write(trio / 'researchPrime/bin/run.mjs', 'export function runRounds() {\n  return "checked";\n}\n')
    write(trio / 'researchPrime/HUMAN.md', '# researchPrime\n**One sentence:** Research a question.\n## How it works\nScope, research and review.\n')
    write(skills / 'gandalf/SKILL.md', '---\nname: Gandalf\n---\n## North Star\nInspect the artifact.\n')
    write(skills / 'hidden/SKILL.md', '---\nfoundry: false\n---\nNot listed.\n')
    write(skills / 'templates/SKILL.md', '# Template')
    write(steward / 'SKILL.md', '---\nname: ecgberht\n---\n## North Star\nSteward an effort.\n')
    monkeypatch.setattr(page.api, 'FOUNDRY_ROOT', str(foundry))
    monkeypatch.setattr(page.api, 'SKILLS_ROOT', str(skills))
    monkeypatch.setattr(page.api, '_load_manifest', lambda: [])
    monkeypatch.setattr(page.api, 'load_north_star', lambda: 'Foundry North Star')
    monkeypatch.setenv('FOUNDRY_TRIO_ROOT', str(trio))
    monkeypatch.setenv('FOUNDRY_STEWARD_ROOT', str(steward))
    monkeypatch.setenv('FOUNDRY_PAGE_CONTENT_ROOT', str(content))
    original_profile = page.anchor_settings.steward_profile
    monkeypatch.setattr(page.anchor_settings, 'steward_profile', lambda: original_profile({'steward_type': 'aladdin'}))
    monkeypatch.setenv('ANCHOR_DATA_DIR', str(tmp_path / 'anchor-data'))
    monkeypatch.setenv('TEMP', str(tmp_path))
    monkeypatch.setenv('TMP', str(tmp_path))
    monkeypatch.setenv('ANCHOR_PROACTIVE_SUMMARY', '0')
    monkeypatch.delenv('ANCHOR_TOKEN', raising=False)
    return dict(root=tmp_path, content=content, instruction=instruction, program=program, skills=skills,
                profile=original_profile)


def legacy(rig):
    base = rig['content'] / 'researchprime'
    write(base / 'library.json', {'resources': [
        {'id': 'guide', 'title': 'Research guide', 'category': 'material', 'path': str(rig['instruction'])},
        {'id': 'gandalf', 'title': 'Gandalf', 'skill': 'gandalf'},
        {'id': 'paper', 'title': 'Paper reference', 'category': 'references', 'url': 'https://example.org/paper'},
    ]})
    write(base / 'process-map.json', {'steps': [
        {'id': 'entry', 'title': 'First program', 'kind': 'program', 'code': {'path': str(rig['program']), 'symbol': 'runRounds'}, 'instructions': {'path': str(rig['instruction']), 'heading': '## Entry'}},
        {'id': 'review', 'title': 'Human feedback', 'kind': 'human', 'code': {'type': 'no-code'}, 'instructions': {'path': str(rig['instruction']), 'heading': '## Entry'}},
    ], 'edges': [{'from': 'entry', 'to': 'review', 'label': 'Review ready'}], 'exits': ['Human review']})
    write(base / 'knowledge-map.json', {'nodes': [
        {'id': 'root', 'name': 'Supported answer', 'resource_id': 'guide', 'ring': 0},
        {'id': 'scope', 'name': 'Scope question', 'resource_id': 'guide', 'parent_ids': ['root'], 'ring': 1},
    ]})
    return base


def combined(rig):
    def source(path, sid, kind):
        return dict(id=sid, origin=str(path), kind=kind, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def anchor(path, aid, sid, line):
        quote = path.read_text(encoding='utf-8').splitlines()[line - 1]
        return dict(id=aid, source_id=sid, start=line, end=line, quote=quote, sha256=hashlib.sha256(quote.encode()).hexdigest())
    doc = dict(schema='foundry-skill-display/v1', skill_id='researchprime',
               sources=[source(rig['instruction'], 'instructions', 'instructions'), source(rig['program'], 'code', 'code')],
               anchors=[anchor(rig['instruction'], 'a1', 'instructions', 7), anchor(rig['program'], 'a2', 'code', 1)],
               resources=[dict(id='plan', title='Reusable research plan', category='Reusable material', anchor_id='a1', usage={'count': 999, 'status': 'frequent'})],
               knowledge={'nodes': [dict(id='answer', title='Supported answer', resource_id='plan', parent_id=None, ring=0, facets=['instructions'], process_ids=['entry'])]},
               process={'steps': [dict(id='entry', title='Entry program', kind='program', anchors=['a2', 'a1'], code_status='anchored', instruction_status='anchored', summary='Build the plan.'), dict(id='done', title='Human review', kind='human', anchors=['a1'], code_status='instructions-only', instruction_status='anchored')],
                        'edges': [dict(source='entry', target='done', label='Ready for feedback', anchor_id='a1')], 'terminals': ['done'],
                        'disagreements': [dict(title='Reports are session work', fact='Program and instructions differ.', anchors=['a1', 'a2'])]})
    path = write(rig['content'] / 'researchprime/maps.json', doc)
    return path, doc


def test_disk_discovery_and_three_persona_roles(rig):
    catalog = page.catalog()
    names = [r['name'] for r in catalog['skills']]
    assert names == sorted(names, key=str.casefold)
    assert not {'hidden', 'templates'} & {r['id'] for r in catalog['skills']}
    roles = [r for r in catalog['skills'] if r['role']]
    assert [r['name'] for r in roles] == ['Aladdin-Cave of Wonders', 'Aladdin-Lamp', 'Aladdin-Star Chart']
    assert len({r['source'] for r in roles}) == 1
    assert len({r['icon'] for r in roles}) == 3
    assert catalog['walkthroughOrder'] == ['researchprime', 'gandalf', 'steward-project', 'steward-portfolio', 'steward-starchart']
    write(rig['skills'] / 'new/SKILL.md', '---\nname: A new skill\n---\nDiscovered from disk.')
    assert page.catalog()['skills'][0]['name'] == 'A new skill'


def test_missing_maps_stay_unfinished(rig):
    detail = page.skill_detail('gandalf')
    assert detail['processMap']['status'] == detail['knowledgeMap']['status'] == 'unfinished'
    assert detail['resources'] and not detail['knowledgeMap']['nodes']


def test_steward_roles_read_distinct_files_without_sharing_a_map(rig):
    steward = Path(page.find_skill('steward-project')['source'])
    write(steward / 'FLOW.project.json', {'steps': [
        {'id': 'lamp', 'title': 'Lamp dialogue', 'code': {'type': 'no-code'},
         'instructions': {'path': str(steward / 'SKILL.md'), 'heading': '## North Star'}}
    ]})
    assert page.skill_detail('steward-project')['processMap']['steps'][0]['id'] == 'lamp'
    assert page.skill_detail('steward-portfolio')['processMap']['status'] == 'unfinished'
    assert page.skill_detail('steward-starchart')['processMap']['status'] == 'unfinished'


def test_legacy_library_and_maps_open_real_resources(rig):
    legacy(rig)
    detail = page.skill_detail('researchprime')
    assert detail['processMap']['status'] == 'source-anchored draft'
    assert detail['knowledgeMap']['status'] == 'seeded draft'
    assert 'not calibrated or learned' in detail['knowledgeMap']['qualification']
    for node in detail['knowledgeMap']['nodes']:
        assert node['href'] == next(r['href'] for r in detail['resources'] if r['id'] == node['resourceId'])
    for step in detail['processMap']['steps']:
        assert step['instructionLink']['href'].startswith('/foundry/source?')
    assert next(r for r in detail['resources'] if r['id'] == 'gandalf')['href'] == '/foundry?skill=gandalf'


def test_combined_foundry_handoff_hashes_branches_and_disagreements(rig):
    combined(rig)
    detail = page.skill_detail('researchprime')
    assert not detail['libraryIssues'] and not detail['processMap']['issues']
    assert detail['processMap']['edges'][0]['to'] == 'done'
    assert len(detail['processMap']['disagreements'][0]['sourceLinks']) == 2
    assert detail['knowledgeMap']['nodes'][0]['resourceId'] == 'plan'
    assert next(r for r in detail['resources'] if r['id'] == 'plan')['frequency'] == 'Use not recorded'
    rig['program'].write_text('// source changed\n', encoding='utf-8')
    assert any('Source changed' in i for i in page.skill_detail('researchprime')['processMap']['issues'])


def test_frequency_requires_distinct_resource_use_records(rig):
    base = legacy(rig)
    record = {'id': 'guide', 'path': str(rig['instruction']), 'useEvidence': []}
    for name, doc in [('one', {'run_id': 'r1', 'resource_ids': ['guide']}), ('duplicate', {'run_id': 'r1', 'resource_ids': ['guide']}), ('unrelated', {'run_id': 'r2', 'resource_ids': ['other']})]:
        record['useEvidence'].append(str(write(base / f'journal/runs/{name}.json', doc)))
    record['useEvidence'].append(str(write(base / 'journal/entry.md', 'An ordinary journal entry.')))
    assert page._frequency(record, page.find_skill('researchprime'), base) == '1 recorded use'


def test_bad_hierarchy_edges_and_missing_targets_are_visible(rig):
    base = legacy(rig)
    write(base / 'knowledge-map.json', {'nodes': [{'id': 'loop', 'name': 'Broken', 'parent_ids': ['loop'], 'ring': 9, 'resource_id': 'missing'}]})
    detail = page.skill_detail('researchprime')
    assert detail['knowledgeMap']['status'] == 'needs checking'
    assert any('cyclic' in i for i in detail['knowledgeMap']['issues'])
    assert any('No real Library target' in i for i in detail['knowledgeMap']['issues'])
    assert any('Ring disagrees' in i for i in detail['knowledgeMap']['issues'])
    write(base / 'process-map.json', {'steps': [], 'edges': [{'from': 'missing', 'to': 'other'}]})
    assert 'Process edge has a missing step' in page.skill_detail('researchprime')['processMap']['issues']


@pytest.mark.parametrize('name,content', [('library.json', {'resources': 42}), ('process-map.json', {'steps': 42}), ('knowledge-map.json', {'nodes': 42}), ('maps.json', {'schema': 'foundry-skill-display/v1', 'skill_id': 'another'})])
def test_malformed_content_is_qualified_not_a_server_error(rig, name, content):
    write(rig['content'] / 'researchprime' / name, content)
    detail = page.skill_detail('researchprime')
    assert detail is not None
    assert detail['libraryIssues'] or detail['knowledgeMap']['issues'] or detail['processMap']['issues']


def test_source_reader_is_skill_scoped_contained_and_escaped(rig):
    legacy(rig)
    markup = page.source_page('researchprime', str(rig['instruction']), '## Entry')
    assert '&lt;unsafe&gt;' in markup and '<unsafe>' not in markup
    assert 'class="hit"' in markup
    assert page.source_page('gandalf', str(rig['instruction'])) is None
    assert page.source_page('researchprime', str(write(rig['root'] / 'outside.md', 'private'))) is None
    assert page.source_page('researchprime', str(rig['content'] / '../../outside.md')) is None


@pytest.fixture
def server(rig):
    import anchor_gui
    srv = anchor_gui.make_server('127.0.0.1', 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{srv.server_address[1]}'
    finally:
        srv.shutdown(); srv.server_close(); thread.join(timeout=5)


def test_actual_anchor_routes_and_built_assets(rig, server):
    combined(rig)
    with urlopen(server + '/api/foundry/page') as response:
        assert json.load(response)['walkthroughOrder'][0] == 'researchprime'
    with urlopen(server + '/api/foundry/skill?skill=researchprime') as response:
        detail = json.load(response)
    source = detail['knowledgeMap']['nodes'][0]['href']
    with urlopen(server + source) as response:
        assert 'class="hit"' in response.read().decode()
    with urlopen(server + '/foundry?skill=researchprime') as response:
        markup = response.read().decode()
    import re
    asset = re.search(r'src="(/assets/[^\"]+\.js)"', markup)[1]
    with urlopen(server + asset) as response:
        assert b'/api/foundry/page' in response.read()
    with pytest.raises(HTTPError) as err:
        urlopen(server + '/api/foundry/skill?skill=unknown')
    assert err.value.code == 404
    with pytest.raises(HTTPError) as err:
        urlopen(server + page.source_url('gandalf', rig['instruction']))
    assert err.value.code == 404


@pytest.mark.parametrize('verb', ['propose', 'apply', 'rollback'])
def test_existing_sleep_routes_still_dispatch_to_the_kernel(rig, server, monkeypatch, verb):
    seen = []
    def stub(body):
        seen.append(body)
        return {'ok': True, 'checked': verb}, 200
    monkeypatch.setattr(page.api, 'sleep_' + verb, stub)
    body = {'skill': 'gandalf', 'confirm': True}
    request = Request(server + '/api/foundry/sleep_session/' + verb,
                      data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request) as response:
        assert json.load(response)['checked'] == verb
    assert seen == [body]


def test_built_desktop_and_phone_navigation_and_source_clicks(rig, server):
    playwright = pytest.importorskip('playwright.sync_api')
    combined(rig)
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                errors, writes = [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                tab.goto(server + '/foundry?skill=researchprime')
                tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()
                tab.get_by_role('button', name='Concept: Supported answer', exact=True).click()
                with tab.expect_popup() as popup:
                    tab.get_by_role('link', name='Open Library resource', exact=True).click()
                popup.value.wait_for_load_state()
                assert popup.value.locator('.hit').count() == 1
                popup.value.close()
                tab.get_by_role('button', name='Outline', exact=True).click()
                assert tab.locator('.map-outline').is_visible()
                tab.locator('#process-map > summary').click()
                assert tab.get_by_role('link', name='Ready for feedback → Human review').is_visible()
                assert tab.get_by_role('link', name='Code: run.mjs · 1').is_visible()
                assert tab.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                if width < 780:
                    tab.get_by_role('button', name='Skills A–Z', exact=True).click()
                tab.locator('#skill-rail').get_by_role('button', name='Gandalf', exact=False).click()
                tab.get_by_role('heading', name='Gandalf', exact=True).wait_for()
                assert tab.get_by_text('Knowledge map unfinished.', exact=False).is_visible()
                assert not errors and not writes
                context.close()
        finally:
            browser.close()


def role_bundle(rig, role='steward-project'):
    _, doc = combined(rig)
    doc['skill_id'] = role
    base = rig['content'] / page.ROLE_CONTENT[role]
    write(base / 'maps.json', doc)
    return base, doc


@pytest.mark.parametrize('persona', ['aladdin', 'jarvis', 'ecgberht'])
@pytest.mark.parametrize('role', list(page.ROLE_CONTENT))
def test_trusted_role_directories_keep_identity_and_selected_persona(rig, monkeypatch, persona, role):
    resolver = rig['profile']
    monkeypatch.setattr(page.anchor_settings, 'steward_profile', lambda: resolver({'steward_type': persona}))
    base, doc = role_bundle(rig, role)
    detail = page.skill_detail(role)
    assert detail['skill']['id'] == role
    profile = resolver({'steward_type': persona})
    field = {'steward-project': 'seal_name', 'steward-portfolio': 'high_seat_name', 'steward-starchart': 'campaign_name'}[role]
    assert detail['skill']['name'] == profile['label'] + '-' + profile[field]
    assert detail['librarySource'] == str(base / 'maps.json')
    assert detail['processMap']['status'] == 'source-anchored draft'
    assert detail['knowledgeMap']['nodes'][0]['href'] == detail['libraryResources'][0]['href']
    for other in page.ROLE_CONTENT.keys() - {role}:
        assert page.skill_detail(other)['processMap']['status'] == 'unfinished'
    doc['skill_id'] = next(r for r in page.ROLE_CONTENT if r != role)
    write(base / 'maps.json', doc)
    assert 'different-skill' in ' '.join(page.skill_detail(role)['libraryIssues'])


def provenance_bundle(rig, source):
    base, doc = role_bundle(rig)
    doc['sources'] = [dict(id='instructions', **source), doc['sources'][1]]
    doc['anchors'][0].update(start=1, end=1, sha256=hashlib.sha256(b'Captured example').hexdigest())
    write(base / 'maps.json', doc)
    return base, doc


def test_exact_engine_and_global_inventory_does_not_broaden_roots(rig, monkeypatch):
    engine = write(rig['root'] / 'Anchor/steward_cockpit/steward_engine.py', 'Captured example\n')
    global_rules = write(rig['root'] / 'home/.claude/AGENTS.md', 'Captured example\n')
    monkeypatch.setattr(Path, 'home', lambda: rig['root'] / 'home')
    for origin in (engine, global_rules):
        base, doc = provenance_bundle(rig, dict(origin=str(origin), freshness='current-source',
            sha256=hashlib.sha256(origin.read_bytes()).hexdigest(), captured_at='2026-10-05T23:40:00+00:00',
            captured_from=str(origin), applicability='On-disk code is not activation proof.'))
        detail = page.skill_detail('steward-project')
        assert not detail['libraryIssues']
        markup = page.source_page('steward-project', str(origin), '1')
        assert 'On-disk code is not activation proof.' in markup
        assert page.source_page('steward-portfolio', str(origin)) is None
        assert not page._allowed(origin)
        origin.write_text('Later source\n', encoding='utf-8')
        assert 'Source changed' in ' '.join(page.skill_detail('steward-project')['libraryIssues'])
        assert 'Source changed since capture' in page.source_page('steward-project', str(origin))
    for outside in (rig['root'] / 'Anchor/private.py', rig['root'] / 'home/.claude/private.md',
                    rig['root'] / 'home/notes.md'):
        write(outside, 'Captured example\n')
        provenance_bundle(rig, dict(origin=str(outside)))
        assert page.source_page('steward-project', str(outside)) is None
        assert page.skill_detail('steward-project')['libraryIssues']


def test_historical_reader_uses_only_qualified_immutable_snapshot(rig):
    base = rig['content'] / 'steward-lamp'
    snapshot = write(base / 'sources/example.md', 'Captured example\n')
    original = write(rig['root'] / 'home/private.md', 'Changed live state\n')
    source = dict(origin=str(original), snapshot='sources/example.md', freshness='frozen-example',
                  sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  captured_at='2026-10-05T23:34:00+00:00', captured_from=str(original),
                  applicability='Historical record; not current campaign state.')
    base, doc = provenance_bundle(rig, source)
    markup = page.source_page('steward-project', str(snapshot), '1')
    assert 'Captured example' in markup and 'Historical record; not current campaign state.' in markup
    assert '2026-10-05T23:34:00+00:00' in markup and source['sha256'] in markup
    assert 'Changed live state' not in markup
    assert page.source_page('steward-project', str(original)) is None
    original.write_text('A newer decision\n', encoding='utf-8')
    assert not page.skill_detail('steward-project')['libraryIssues']
    snapshot.write_text('Corrupted snapshot\n', encoding='utf-8')
    assert 'snapshot hash mismatch' in ' '.join(page.skill_detail('steward-project')['libraryIssues'])
    assert page.source_page('steward-project', str(snapshot)) is None


@pytest.mark.parametrize('snapshot', ['../outside.md', '/outside.md', 'sources/../../outside.md', '.ecgberht/history.json'])
def test_snapshot_and_request_traversal_fail_closed(rig, snapshot):
    outside = write(rig['root'] / 'outside.md', 'Captured example\n')
    provenance_bundle(rig, dict(origin=str(outside), snapshot=snapshot, freshness='frozen-example',
        sha256=hashlib.sha256(outside.read_bytes()).hexdigest(), captured_at='2026-10-05',
        captured_from=str(outside), applicability='Historical.'))
    assert page.source_page('steward-project', str(outside)) is None
    assert page.skill_detail('steward-project')['libraryIssues']
    combined(rig)
    assert page.source_page('researchprime', str(rig['program'].parent / '../bin/run.mjs')) is None


def test_declared_symlink_to_outside_is_rejected(rig):
    outside = write(rig['root'] / 'outside.md', 'Captured example\n')
    base = rig['content'] / 'steward-lamp'
    link = base / 'sources/example.md'
    link.parent.mkdir(parents=True)
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip('symlink creation unavailable')
    provenance_bundle(rig, dict(origin=str(outside), snapshot='sources/example.md', freshness='frozen-example',
        sha256=hashlib.sha256(outside.read_bytes()).hexdigest(), captured_at='2026-10-05',
        captured_from=str(outside), applicability='Historical.'))
    assert page.source_page('steward-project', str(link)) is None
    assert page.skill_detail('steward-project')['libraryIssues']


def captured_bundle(rig):
    """A REAL-handoff-shaped source inventory: origin + contained snapshot +
    SNAPSHOT-bound sha256 and NO freshness metadata — exactly the registered
    researchPrime records (nothing manufactures frozen-example fields)."""
    base = rig['content'] / 'researchprime'
    snapshot = write(base / 'sources/skill.md', rig['instruction'].read_text(encoding='utf-8'))
    _, doc = combined(rig)
    doc['sources'][0] = dict(id='instructions', kind='instructions', origin=str(rig['instruction']),
                             snapshot='sources/skill.md',
                             sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest())
    write(base / 'maps.json', doc)
    return base, doc, snapshot


def source_viewer_path(href):
    return Path(parse_qs(urlsplit(href).query)['path'][0]).resolve()


def test_captured_snapshot_binding_survives_real_origin_drift(rig):
    base, doc, snapshot = captured_bundle(rig)
    detail = page.skill_detail('researchprime')
    assert not detail['libraryIssues'] and not detail['processMap']['issues']
    # The anchor binds to the CONTAINED declared snapshot — never the origin.
    assert source_viewer_path(detail['processMap']['anchorLinks']['a1']['href']) == snapshot.resolve()
    # A REAL origin drift: the live origin moves on; the captured file is valid.
    rig['instruction'].write_text('---\nname: researchPrime\n---\n## Entry\nRewritten after capture.\n',
                                  encoding='utf-8')
    detail = page.skill_detail('researchprime')
    assert not any('Source changed' in i for i in detail['processMap']['issues'])
    assert not any('Invalid source range' in i for i in detail['processMap']['issues'])
    # The served page shows the captured bytes, with accurate captured-source
    # provenance and the origin listed SEPARATELY — never the drifted content.
    markup = page.source_page('researchprime', str(snapshot), '7')
    assert markup and 'captured-snapshot' in markup
    assert str(rig['instruction']) in markup and doc['sources'][0]['sha256'] in markup
    assert 'Rewritten after capture' not in markup


def test_captured_snapshot_rejects_mismatch_traversal_and_undeclared(rig):
    base, doc, snapshot = captured_bundle(rig)
    # Corrupted snapshot: honest issue, never served.
    snapshot.write_text('tampered\n', encoding='utf-8')
    issues = page.skill_detail('researchprime')['processMap']['issues']
    assert any('Captured snapshot hash mismatch' in i for i in issues)
    assert page.source_page('researchprime', str(snapshot)) is None
    # Traversal / absolute / dot-dir snapshot declarations fail closed.
    outside = write(rig['root'] / 'outside.md', 'Captured example\n')
    for bad in ('../outside.md', str(outside), 'sources/../../outside.md', '.hidden/snap.md'):
        doc['sources'][0]['snapshot'] = bad
        doc['sources'][0]['sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
        write(base / 'maps.json', doc)
        issues = page.skill_detail('researchprime')['processMap']['issues']
        assert any('Captured snapshot' in i for i in issues)
        assert page.source_page('researchprime', str(outside)) is None
    # A file under sources/ that NO inventory entry declares stays unreachable.
    undeclared = write(base / 'sources/undeclared.md', 'PRIVATE')
    assert page.source_page('researchprime', str(undeclared)) is None


def test_captured_snapshot_resolves_when_origin_is_outside_all_roots(rig):
    """The registered anchor-api shape: origin outside every discovery root,
    snapshot contained — the declared capture resolves without broadening roots."""
    base, doc, snapshot = captured_bundle(rig)
    outside_origin = write(rig['root'] / 'Anchor-origin/foundry_api.py',
                           snapshot.read_text(encoding='utf-8'))
    doc['sources'][0]['origin'] = str(outside_origin)
    write(base / 'maps.json', doc)
    assert not page._allowed(outside_origin)
    detail = page.skill_detail('researchprime')
    assert not detail['libraryIssues'] and not detail['processMap']['issues']
    assert source_viewer_path(detail['processMap']['anchorLinks']['a1']['href']) == snapshot.resolve()
    markup = page.source_page('researchprime', str(snapshot), '1')
    assert markup and str(outside_origin) in markup
    # The out-of-roots origin itself is still never served.
    assert page.source_page('researchprime', str(outside_origin)) is None


@pytest.fixture
def opening(rig, monkeypatch):
    import anchor_gui
    pid = 'fixture-foundry'
    monkeypatch.setattr(anchor_gui._rnd, 'get_project', lambda p: {'id': pid, 'folder_path': str(rig['content'].parent)} if p == pid else None)
    monkeypatch.setattr(page, '_review_project_id', lambda: pid)
    base, doc = role_bundle(rig)
    write(base / 'index.html', '''<!doctype html><html><head><link rel="stylesheet" href="../shared/maps.css">
<script defer src="display.js"></script></head><body><img src="assets/lamp.svg"><div id="panel"></div></body></html>''')
    write(base / 'display.js', "document.querySelector('#panel').innerHTML='<h1>Lamp Library</h1><a href=\"resources/plan.html\">Open resource</a>';")
    write(rig['content'] / 'shared/maps.css', 'body{background:rgb(20, 30, 40);color:white}')
    write(base / 'assets/lamp.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="gold"/></svg>')
    write(base / 'resources/plan.html', '<!doctype html><link rel="stylesheet" href="../../shared/maps.css"><h1>Reusable research plan</h1><a href="../sources/example.md">Exact captured source</a>')
    write(base / 'sources/example.md', 'An exact captured source.\n')
    doc['resources'][0]['target'] = 'resources/plan.html'
    write(base / 'maps.json', doc)
    rel = base.relative_to(rig['content'].parent).as_posix() + '/index.html'
    return '/artifact/' + pid + '?path=' + quote(rel, safe=''), base


def test_real_artifact_opening_redirect_assets_and_containment(rig, server, opening):
    route, base = opening
    with urlopen(server + route) as response:
        assert '/steward-lamp/index.html' in response.url
        assert 'sandbox' in response.headers['Content-Security-Policy']
        assert 'allow-same-origin' not in response.headers['Content-Security-Policy']
    with urlopen(server + route.replace('fixture-foundry?', 'fixture-foundry/?') + '&persona=jarvis') as response:
        assert response.url.endswith('/index.html?persona=jarvis')
    from steward_cockpit.steward_campaign import classify_route
    # This is the owner-applied Where-cell correction: keep the existing
    # query grammar, which now redirects to the contained document directory.
    assert classify_route(route) == route
    assert classify_route(route + '#handoff') == route + '#handoff'
    prefix = '/artifact/fixture-foundry/' + quote(base.relative_to(rig['content'].parent).as_posix(), safe='/')
    for relative, ctype in [('display.js', 'application/javascript'), ('../shared/maps.css', 'text/css'), ('assets/lamp.svg', 'image/svg+xml')]:
        # Browser URL resolution removes ordinary relative segments before GET.
        from urllib.parse import urljoin
        with urlopen(urljoin(server + prefix + '/index.html', relative)) as response:
            assert response.headers['Content-Type'].startswith(ctype)
    detail = page.skill_detail('steward-project')
    assert detail['libraryResources'][0]['href'].endswith('/resources/plan.html')
    assert detail['libraryResources'][0]['sourceHref'].startswith('/foundry/source?')
    write(rig['content'].parent / '.git/config', 'SECRET')
    for path in ('../../outside.md', '.git/config', str(rig['root'] / 'outside.md')):
        with pytest.raises(HTTPError) as err:
            urlopen(server + '/artifact/fixture-foundry?path=' + quote(path, safe=''))
        assert err.value.code in (400, 404)
    with pytest.raises(HTTPError) as err:
        urlopen(server + '/artifact/fixture-foundry/.git/config')
    assert err.value.code == 404


def test_authenticated_desktop_phone_library_loads_relative_assets(rig, server, opening, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('ANCHOR_TOKEN', 'foundry-test-cookie')
    route, _ = opening
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                # Use the normal local-page login, while guarding all Doctor
                # follow-up reads so no other effort can soft-wake.
                tab.route('**/*', lambda r: r.continue_() if r.request.is_navigation_request() and '/doctor' in r.request.url else r.abort())
                tab.goto(server + '/doctor')
                assert any(c['name'] == 'anchor_auth' and c['httpOnly'] for c in context.cookies())
                tab.unroute('**/*')
                errors, failed, writes = [], [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('requestfailed', lambda r: failed.append(r.url))
                tab.on('response', lambda r: failed.append(r.url) if r.status >= 400 else None)
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                tab.goto(server + route)
                tab.get_by_role('heading', name='Lamp Library').wait_for()
                assert tab.locator('img').evaluate('(el) => el.complete && el.naturalWidth > 0')
                assert tab.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(20, 30, 40)'
                tab.get_by_role('link', name='Open resource', exact=True).click()
                tab.get_by_role('heading', name='Reusable research plan').wait_for()
                tab.get_by_role('link', name='Exact captured source').click()
                assert 'An exact captured source.' in tab.locator('body').inner_text()
                assert not errors and not failed and not writes
                context.close()
        finally:
            browser.close()


def test_windows_journal_does_not_break_real_foundry_loading(rig, server, monkeypatch):
    journal = rig['skills'] / 'gandalf/journal/0001-legacy.md'
    journal.parent.mkdir(parents=True)
    journal.write_bytes('# Review — a historical entry\nRetained “quoted” context.'.encode('cp1252'))
    monkeypatch.setattr(page.api, '_load_manifest', lambda: [
        {'name': 'Gandalf', 'ref': 'gandalf', 'source': str(rig['skills'] / 'gandalf')}])
    events = page.api._journal_events(str(journal.parent.parent))
    assert events[0]['event'] == 'Review — a historical entry'
    assert events[0]['sourceEncoding'] == 'windows-1252'
    assert '“quoted”' in events[0]['details']
    for route in ('/api/skills', '/api/metrics'):
        with urlopen(server + route) as response:
            assert response.status == 200
            assert json.load(response)
    assert journal.read_bytes() == '# Review — a historical entry\nRetained “quoted” context.'.encode('cp1252')


def test_exact_inventory_and_resource_target_rejections(rig, opening):
    _, base = opening
    unknown = write(base / 'sources/undeclared.md', 'PRIVATE')
    assert page.source_page('steward-project', str(unknown)) is None
    assert page.source_page('steward-project', str(write(rig['root'] / 'Anchor/model_policy.py', 'PRIVATE'))) is None
    for target in ('../sources/undeclared.md', 'resources/../../outside.html', str(unknown), '.anchor/private.html'):
        assert page._library_target(target, base, 'fixture-foundry') is None


# ── researchPrime Refinement 2 — the ported foundry-skill-display page ────────
# These tests FAIL on the old display: the level-dial Library, the typed flow
# diagram with a declared layout, per-step reconciliation records, cumulative
# review data and primary-settings resolution did not exist on the React page.


def rendered_doc(title, extra=''):
    # The Back link is the REAL registered documents' markup (human-guide.html /
    # purpose.html line 5): a `target="_top"` return to the standalone bundle
    # index that must be served INSIDE the live page, never by replacing it.
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<style>body{font:15px system-ui}</style></head><body><div class="md">'
            '<a target="_top" href="../index.html#library">← researchPrime Library</a>'
            '<h1>%s</h1><h2>When to use it</h2><p>A readable rendered document, not raw markup.</p>%s'
            '</div></body></html>' % (title, extra))


def refinement2(rig):
    """The Refinement-2-shaped foundry-skill-display/v1 handoff fixture:
    declared diagram layout + typed steps, instruction/code reconciliation
    records with both anchors and a follows verdict, layered knowledge catalog
    (four kinds, explicit zeros), cumulative grade-B review, an explicitly open
    lifecycle, a qualified settings mirror snapshot — and the prerendered
    Markdown documents the Library opens."""
    base = rig['content'] / 'researchprime'
    ins, prog = rig['instruction'], rig['program']
    # Real cited controls sit DEEP in a long source (the registered a108 is
    # skill.md line 208): pad the instruction source well past a screenful so
    # the browser checks only pass when the anchored line is actually brought
    # into view inside the sandboxed (script-less) frame — never the file top.
    ins.write_text(ins.read_text(encoding='utf-8')
                   + ''.join('Deep clause %d of the governed procedure.\n' % i for i in range(1, 140))
                   + '- **G-deep** the cited governance control.\n'
                   + 'Closing clause A.\nClosing clause B.\n', encoding='utf-8')
    deep = len(ins.read_text(encoding='utf-8').splitlines()) - 2

    def source(path, sid, kind):
        return dict(id=sid, kind=kind, origin=str(path),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def anchor(path, aid, sid, line):
        quote = path.read_text(encoding='utf-8').splitlines()[line - 1]
        return dict(id=aid, source_id=sid, start=line, end=line, quote=quote,
                    sha256=hashlib.sha256(quote.encode()).hexdigest())

    def resource(rid, title, target, anchor_id, category='Reusable material'):
        return dict(id=rid, title=title, category=category, summary='Summary of ' + title + '.',
                    anchor_id=anchor_id, target=target, render='markdown',
                    usage={'status': 'unknown', 'count': None, 'run_ids': [], 'method': None})

    def catalog(material, total):
        return {'Reusable material': material, 'References': 0, 'Tools': 0, 'Other skills': 0}, total

    write(base / 'resources/human-guide.html', rendered_doc('researchPrime — human guide'))
    write(base / 'resources/purpose.html', rendered_doc(
        'Original North Star',
        '<p class="locus"><strong>LOCKED</strong> — this North Star lives at '
        '<code>researchPrime/SKILL.md · ## North Star</code> and is changed only by John.</p>'
        # The real purpose.html also deep-links the standalone process view.
        '<a target="_top" href="../index.html#process/entry">A question arrives</a>'))
    write(base / 'resources/plan.html', rendered_doc('Reusable research plan'))

    def node(nid, title, parent, ring, rid, process_ids, material, total):
        cat, tot = catalog(material, total)
        return dict(id=nid, title=title, parent_id=parent, ring=ring, resource_id=rid,
                    facets=['instructions'], process_ids=process_ids, catalog=cat, catalog_total=tot)

    def step(sid, title, display_type, kind, anchors, resource_ids, code_status, instruction_status, summary):
        return dict(id=sid, title=title, kind=kind, display_type=display_type, summary=summary,
                    anchors=anchors, code_status=code_status, instruction_status=instruction_status,
                    resource_ids=resource_ids)

    doc = dict(
        schema='foundry-skill-display/v1', skill_id='researchprime',
        refinement='researchPrime Library and maps — Refinement 2, after the grade-B review (2026-10-06)',
        lifecycle={'state': 'for-review', 'accepted': False, 'closed': False},
        review={'cumulative': [dict(
            refinement=1, reviewed='2026-10-06', reviewer='John', grade='B',
            verdict='The material is there, but it is not quick and intuitive.',
            points=['Group the Library by the knowledge-map layers.',
                    'Draw the process as a tight typed flow diagram.'],
            response='Refinement 2 descends the Library with a level dial and draws the typed flow diagram.')]},
        settings={'coding_family': 'chatgpt', 'review_family': 'grok', 'default_cli': 'chatgpt',
                  'steward_type': 'aladdin',
                  'model_policy': {'mode': 'latest_supported', 'effort': 'highest_supported'},
                  'settings_revision': 23},
        sources=[source(ins, 'skill', 'instructions'), source(prog, 'runner', 'code')],
        anchors=[anchor(ins, 'a_ins', 'skill', deep), anchor(ins, 'a_ins2', 'skill', 6),
                 anchor(prog, 'a_code', 'runner', 1), anchor(prog, 'a_code2', 'runner', 2)],
        resources=[resource('purpose', 'Original North Star', 'resources/purpose.html', 'a_ins2'),
                   resource('human-guide', 'Human guide', 'resources/human-guide.html', 'a_ins'),
                   resource('plan', 'Reusable research plan', 'resources/plan.html', 'a_code')],
        knowledge={'geometry': 'seeded-declared-tree', 'learned': False, 'layout_source': 'parent_id',
                   'run_evidence': [],
                   'frequency_policy': 'Unknown until unique recorded runs explicitly name resource ids.',
                   'nodes': [node('answer', 'Supported answer', None, 0, 'purpose', ['entry'], 3, 3),
                             node('method', 'Method and guide', 'answer', 1, 'human-guide', [], 2, 2),
                             node('plan-leaf', 'Research plan', 'method', 2, 'plan', ['entry'], 1, 1)]},
        process={'entry': 'entry', 'terminals': ['done'],
                 'steps': [step('entry', 'Entry program', 'program', 'program', ['a_code'], ['plan'],
                                'anchored', 'anchored', 'Build the plan.'),
                           step('approve', 'Human approval', 'human-gate', 'gate', ['a_ins'], ['human-guide'],
                                'instructions-only', 'anchored', 'John approves the plan.'),
                           step('review', 'Adversarial review', 'adversarial-review', 'review',
                                ['a_ins2', 'a_code2'], [], 'anchored', 'anchored',
                                'Fresh reviewers check the claims.'),
                           step('modelcall', 'Model synthesis', 'model-call', 'model', ['a_code2'], [],
                                'anchored', 'anchored', 'Synthesize the surviving findings.'),
                           step('done', 'Deliver and stop', 'program', 'terminal', ['a_code'], ['purpose'],
                                'anchored', 'anchored', 'Hand back the answer.')],
                 'edges': [dict(source='entry', target='approve', label='Plan ready', anchor_id='a_code'),
                           dict(source='approve', target='review', label='APPROVE', anchor_id='a_ins'),
                           dict(source='review', target='modelcall', label='Findings in', anchor_id='a_ins2'),
                           dict(source='modelcall', target='done', label='Converged', anchor_id='a_code2')],
                 'disagreements': [dict(
                     id='d1', title='Reports are session work',
                     fact='Program and instructions differ on who writes the reports.',
                     instruction_says='The skill text says the engine writes the final report.',
                     code_does='The engine stops at validated findings; the session writes reports.',
                     follows='The code path — reports are session work.',
                     instruction_anchor='a_ins', code_anchor='a_code',
                     anchors=['a_ins', 'a_code'], step_ids=['review'], state='documented')],
                 'diagram': {'col_width': 196, 'row_height': 78, 'node_width': 150, 'node_height': 46,
                             'nodes': {'entry': {'col': 0, 'row': 0}, 'approve': {'col': 0, 'row': 1},
                                       'review': {'col': 0, 'row': 2}, 'modelcall': {'col': 1, 'row': 2},
                                       'done': {'col': 0, 'row': 3}},
                             'bands': [{'title': '1 · Plan and approve', 'from_row': 0, 'to_row': 1},
                                       {'title': '2 · Validate and deliver', 'from_row': 2, 'to_row': 3}]}},
        walkthrough=['researchprime', 'gandalf', 'steward-lamp', 'steward-cave',
                     'steward-star-chart', 'remaining-skills'],
        integration={'owner': 'Anchor code job', 'installed': False, 'gaps': []})
    write(base / 'maps.json', doc)
    return base


def primary_settings(**overrides):
    values = dict(default_cli='claude', coding_family='claude', review_family='gemini',
                  steward_type='aladdin',
                  model_policy={'mode': 'latest_supported', 'effort': 'highest_supported'},
                  settings_revision=5, updated_at='2026-10-07T00:00:00+00:00')
    values.update(overrides)
    return write(page.anchor_settings.settings_path(), values)


def visible_height(box, viewport_height):
    """How many pixels of a bounding box actually intersect the viewport."""
    if not box:
        return 0
    return min(box['y'] + box['height'], viewport_height) - max(box['y'], 0)


def cited_line_in_view(tab, viewport_height, timeout_ms=5000):
    """After a source-anchor click, the cited ``.hit`` line must ACTUALLY
    intersect the visible iframe AND the screen viewport — not merely exist
    attached somewhere in the frame's full pre text (Playwright counts
    off-screen boxes, and ``inner_text`` includes off-screen lines). The frame
    sandbox runs no scripts, so only the host-side scroll can satisfy this.
    Returns ``(hit_box, frame_box)`` in page coordinates, or fails."""
    frame = tab.frame_locator('#resource-frame')
    frame.locator('.hit').wait_for()
    hit_box = frame_box = None
    for _ in range(max(1, timeout_ms // 100)):
        hit_box = frame.locator('.hit').bounding_box()
        frame_box = tab.locator('#resource-frame').bounding_box()
        if (hit_box and frame_box
                and hit_box['y'] >= frame_box['y'] - 1
                and hit_box['y'] + hit_box['height'] <= frame_box['y'] + frame_box['height'] + 1
                and hit_box['x'] >= frame_box['x'] - 1
                and hit_box['x'] < frame_box['x'] + frame_box['width']
                and visible_height(hit_box, viewport_height) >= hit_box['height'] - 1):
            return hit_box, frame_box
        tab.wait_for_timeout(100)
    raise AssertionError('cited source line never intersected the visible iframe '
                         'and viewport: hit=%r frame=%r' % (hit_box, frame_box))


@pytest.fixture
def display_project(rig, monkeypatch):
    import anchor_gui
    pid = 'fixture-foundry'
    monkeypatch.setattr(anchor_gui._rnd, 'get_project',
                        lambda p: {'id': pid, 'folder_path': str(rig['content'].parent)} if p == pid else None)
    monkeypatch.setattr(page, '_review_project_id', lambda: pid)
    return pid


def test_refinement2_payload_primary_settings_hrefs_and_preserved_review(rig, display_project):
    refinement2(rig)
    primary_settings()
    payload = page.display_payload('researchprime')
    assert payload is not None
    # The CURRENT primary settings resolve — the bundle's mirror snapshot stays
    # a mirror and never overrides an existing primary.
    assert payload['settings']['primary'] == {'exists': True, 'value': {
        'coding_family': 'claude', 'review_family': 'gemini', 'default_cli': 'claude',
        'steward_type': 'aladdin',
        'model_policy': {'mode': 'latest_supported', 'effort': 'highest_supported'},
        'settings_revision': 5}}
    assert payload['settings']['mirror']['coding_family'] == 'chatgpt'
    assert payload['settings']['error'] is None
    # Every declared resource opens CONTAINED: the rendered document through
    # /artifact, with the hash-checked source viewer kept as sourceHref.
    hrefs = payload['hrefs']['resources']
    assert set(hrefs) == {'purpose', 'human-guide', 'plan'}
    assert hrefs['human-guide']['href'].startswith('/artifact/fixture-foundry/')
    assert hrefs['human-guide']['href'].endswith('/resources/human-guide.html')
    assert hrefs['human-guide']['sourceHref'].startswith('/foundry/source?')
    anchors = payload['hrefs']['anchors']
    assert set(anchors) == {'a_ins', 'a_ins2', 'a_code', 'a_code2'}
    assert all(link['href'].startswith('/foundry/source?') for link in anchors.values())
    assert payload['issues'] == []
    # Grade-B feedback and the open lifecycle ride through unchanged.
    review = payload['data']['review']['cumulative'][0]
    assert review['grade'] == 'B' and review['reviewer'] == 'John'
    assert payload['data']['lifecycle'] == {'state': 'for-review', 'accepted': False, 'closed': False}
    # Frequency and geometry stay explicitly seeded/unknown in the shipped data.
    assert payload['data']['knowledge']['geometry'] == 'seeded-declared-tree'
    assert payload['data']['knowledge']['learned'] is False
    assert all(r['usage'] == {'status': 'unknown', 'count': None, 'run_ids': [], 'method': None}
               for r in payload['data']['resources'])
    # The walkthrough rail links the other skills' EXISTING pages.
    assert payload['rail']['gandalf'] == {'href': '/foundry?skill=gandalf',
                                          'icon': page.find_skill('gandalf')['icon'], 'current': False}
    assert payload['rail']['researchprime']['current'] is True
    assert payload['persona']['lamp']['title'] == 'Steward · the Lamp'


def test_refinement2_existing_invalid_primary_refuses_never_falls_back(rig, display_project):
    refinement2(rig)
    write(page.anchor_settings.settings_path(), 'not a settings object {')
    payload = page.display_payload('researchprime')
    assert payload['settings']['primary'] == {'exists': True, 'value': None}
    assert 'invalid' in payload['settings']['error'].lower()
    # The mirror snapshot is NOT promoted into the primary slot; the canonical
    # adapter refuses an existing invalid primary client-side.
    assert payload['settings']['mirror']['coding_family'] == 'chatgpt'
    assert page.display_page('researchprime') is not None


def test_refinement2_marker_required_old_display_keeps_serving(rig):
    combined(rig)   # the pre-Refinement-2 handoff carries no declared diagram
    assert page.display_payload('researchprime') is None
    assert page.display_page('researchprime') is None
    base = refinement2(rig)
    doc = json.loads((base / 'maps.json').read_text(encoding='utf-8'))
    del doc['process']['diagram']['nodes']['done']   # layout no longer covers every step
    write(base / 'maps.json', doc)
    assert page.display_page('researchprime') is None   # honest fallback, never a 500


def test_foundry_route_serves_refinement2_and_keeps_other_skills(rig, server, display_project):
    import re
    refinement2(rig)
    primary_settings()
    with urlopen(server + '/foundry?skill=researchprime') as response:
        markup = response.read().decode('utf-8')
    assert 'FOUNDRY_SKILL_DISPLAY' in markup
    for asset in ('display.css', 'adapter.js', 'flow-diagram.js', 'layer-library.js', 'skill-display.js'):
        assert '/static/foundry-display/' + asset in markup
        with urlopen(server + '/static/foundry-display/' + asset) as served:
            assert served.status == 200 and served.read()
    assert 'accepted: false' in markup and 'closed: false' in markup
    # The canonical adapter ships with the designed seams this integration
    # mounts (settings resolution + allowlisted target routing); its one Anchor
    # amendment is the persona contract (anchor_settings.VALID_STEWARDS).
    with urlopen(server + '/static/foundry-display/adapter.js') as served:
        adapter = served.read().decode('utf-8')
    assert 'resolveDisplaySettings' in adapter and 'resolveTarget' in adapter
    assert 'renderFlowDiagram' in urlopen(server + '/static/foundry-display/flow-diagram.js').read().decode('utf-8')
    assert 'renderLayerLibrary' in urlopen(server + '/static/foundry-display/layer-library.js').read().decode('utf-8')
    # Other skills keep the existing React walkthrough, unchanged.
    with urlopen(server + '/foundry?skill=gandalf') as response:
        other = response.read().decode('utf-8')
    assert re.search(r'src="(/assets/[^"]+\.js)"', other) and 'FOUNDRY_SKILL_DISPLAY' not in other


def test_refinement2_desktop_phone_diagram_dial_sources_guide_and_review(rig, server, display_project):
    playwright = pytest.importorskip('playwright.sync_api')
    refinement2(rig)
    primary_settings()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                errors, failed, writes = [], [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('response', lambda r: failed.append(r.url) if r.status >= 400 else None)
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                tab.goto(server + '/foundry?skill=researchprime')
                tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()

                # Process: typed flow diagram, accurate legend, declared entry,
                # ≠ badges; node selection + explicit record expansion keep the
                # drawing visible on this viewport.
                tab.get_by_role('link', name='Process map', exact=True).click()
                tab.locator('.flow-diagram').wait_for()
                assert tab.locator('.flow-diagram a.fd-node').count() == 5
                assert tab.locator('.fd-legend .fd-key.human-gate').is_visible()
                assert 'gate' in tab.locator('.fd-gate-note').inner_text()
                assert tab.locator('.flow-diagram .fd-flag').count() == 1
                assert 'declared entry' in tab.locator('#panel > .note').first.inner_text()
                tab.locator('.flow-diagram a.fd-node[data-step="review"]').click()
                detail = tab.locator('#step-detail[data-step-id="review"]')
                detail.wait_for()
                assert visible_height(tab.locator('.diagram-scroll').bounding_box(), height) >= 120
                node_box = tab.locator('.flow-diagram a.fd-node.selected').bounding_box()
                assert node_box and 0 <= node_box['x'] + node_box['width'] / 2 <= width
                assert detail.get_attribute('open') is None     # expansion is explicit
                detail.locator('> summary').click()
                assert 'Instructions ≠ code on this node' in detail.inner_text()
                # ACTUAL viewport intersection after the explicit expansion —
                # a readable band of the drawing, not merely box bottom > 0.
                assert visible_height(tab.locator('.diagram-scroll').bounding_box(), height) >= 120
                assert tab.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                # The embedded reconciliation record carries both anchors and
                # what implementation a run follows.
                assert detail.locator('.reconcile-node .anchor-list a[data-source]').count() == 2
                detail.locator('.reconcile-node details.difference > summary').click()
                assert 'The code path — reports are session work.' in detail.inner_text()

                # Source anchors open through the EXISTING hash-checked viewer,
                # and the DEEP cited line — not the file top — actually
                # intersects the visible iframe and the screen viewport: the
                # sandboxed frame runs no scripts, so only the host scroll
                # can land there.
                detail.locator('.reconcile-node .anchor-list a[data-source]').first.click()
                cited_line_in_view(tab, height)
                deep = len(rig['instruction'].read_text(encoding='utf-8').splitlines()) - 2
                hit = tab.frame_locator('#resource-frame').locator('.hit')
                assert hit.get_attribute('id') == 'L%d' % deep
                assert 'the cited governance control' in hit.inner_text()
                assert '/foundry/source?' in tab.locator('#resource-frame').get_attribute('src')
                tab.locator('#close-resource').click()

                # Differences tab: both anchors and what implementation follows.
                tab.get_by_role('link', name='Instructions ↔ code', exact=True).click()
                diff = tab.locator('details.difference[data-difference="d1"]')
                diff.locator('> summary').click()
                assert diff.locator('.reconcile-grid a.anchor-link').count() == 2
                assert 'Which one a run follows' in diff.inner_text()

                # Library: level dial, all four kinds with explicit zeros,
                # tiles only at the chosen leaf, leaf opens the ACTUAL document.
                tab.get_by_role('link', name='Library', exact=True).click()
                tab.locator('#level-dial').wait_for()
                assert 'Level 0 of 2' in tab.locator('.ll-dial output').inner_text()
                summary = tab.locator('.ll-summary').inner_text()
                assert 'References 0' in summary and 'Tools 0' in summary and 'Skills 0' in summary
                tab.locator('.ll-branch').click()
                tab.locator('.ll-branch').click()
                assert 'Level 2 of 2' in tab.locator('.ll-dial output').inner_text()
                assert 'Leaf reached' in tab.locator('#panel').inner_text()
                tab.get_by_role('link', name='Open resource →', exact=True).click()
                plan = tab.frame_locator('#resource-frame')
                plan.get_by_role('heading', name='Reusable research plan', exact=True).wait_for()
                tab.locator('#close-resource').click()
                tab.locator('#level-dial').evaluate(
                    "el => { el.value = '0'; el.dispatchEvent(new Event('input', {bubbles: true})); }")
                assert 'Level 0 of 2' in tab.locator('.ll-dial output').inner_text()

                # Human Guide and North Star render as READABLE documents; the
                # canonical LOCKED North Star location and authority is stated.
                tab.locator('.head .actions').get_by_role('link', name='Human guide', exact=True).click()
                guide = tab.frame_locator('#resource-frame')
                guide.get_by_role('heading', name='researchPrime — human guide', exact=True).wait_for()
                assert guide.get_by_role('heading', name='When to use it', exact=True).is_visible()
                # The document's real `target="_top"` Back link is served on
                # THIS live page: dialog closed, Library tab open — the host is
                # never replaced by the standalone bundle preview.
                guide.get_by_role('link', name='← researchPrime Library', exact=True).click()
                tab.locator('#level-dial').wait_for()
                assert not tab.locator('#resource-dialog').is_visible()
                assert '/foundry?skill=researchprime' in tab.url
                tab.locator('.head .actions').get_by_role('link', name='Original North Star', exact=True).click()
                star = tab.frame_locator('#resource-frame')
                star.get_by_role('heading', name='Original North Star', exact=True).wait_for()
                star_text = star.locator('body').inner_text()
                assert 'LOCKED' in star_text and 'changed only by John' in star_text
                # Its real `_top` deep link routes the LIVE process map.
                star.get_by_role('link', name='A question arrives', exact=True).click()
                tab.locator('.flow-diagram').wait_for()
                assert not tab.locator('#resource-dialog').is_visible()
                assert '/foundry?skill=researchprime' in tab.url

                # Review record: cumulative grade-B feedback + open lifecycle.
                tab.get_by_role('link', name='Review record', exact=True).click()
                review_text = tab.locator('#panel').inner_text()
                assert 'Grade: B' in review_text
                assert 'not quick and intuitive' in review_text
                assert 'accepted: false' in review_text and 'closed: false' in review_text

                assert not errors and not failed and not writes
                if width >= 780:
                    # The rail keeps the other skills' EXISTING pages reachable.
                    tab.locator('#walkthrough a.walk', has_text='Gandalf').click()
                    tab.get_by_role('heading', name='Gandalf', exact=True).wait_for()
                context.close()
        finally:
            browser.close()


@pytest.mark.parametrize('persona,lamp_title', [
    ('aladdin', 'Steward · the Lamp'),
    ('jarvis', 'Steward · the Server'),
    ('ecgberht', 'Steward · the Seal'),
])
def test_refinement2_every_valid_persona_mounts_dial_diagram_documents(
        rig, server, display_project, monkeypatch, persona, lamp_title):
    """The ACTUAL Anchor persona contract: every anchor_settings.VALID_STEWARDS
    primary — including Ecgberht, the code default the bundle adapter refused —
    mounts the dial, the diagram and the documents with its own persona names."""
    playwright = pytest.importorskip('playwright.sync_api')
    refinement2(rig)
    primary_settings(steward_type=persona)
    monkeypatch.setattr(page.anchor_settings, 'steward_profile',
                        lambda: rig['profile'](page.anchor_settings.load_settings()))
    assert persona in page.anchor_settings.VALID_STEWARDS
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            tab = context.new_page()
            errors = []
            tab.on('pageerror', lambda e: errors.append(str(e)))
            tab.goto(server + '/foundry?skill=researchprime')
            tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()
            rail = tab.locator('#walkthrough')
            rail.locator('.walk').first.wait_for()
            # Persona names come from the CURRENT primary — never the bundle's
            # qualified aladdin mirror snapshot, and never a refusal.
            assert lamp_title in rail.inner_text()
            # The walkthrough MOUNTS: the typed diagram...
            tab.get_by_role('link', name='Process map', exact=True).click()
            tab.locator('.flow-diagram').wait_for()
            assert tab.locator('.flow-diagram a.fd-node').count() == 5
            # ...the Library level dial...
            tab.get_by_role('link', name='Library', exact=True).click()
            tab.locator('#level-dial').wait_for()
            # ...and the documents.
            tab.locator('.head .actions').get_by_role('link', name='Human guide', exact=True).click()
            guide = tab.frame_locator('#resource-frame')
            guide.get_by_role('heading', name='researchPrime — human guide', exact=True).wait_for()
            assert not errors
            context.close()
        finally:
            browser.close()


def test_refinement2_existing_invalid_primary_refuses_in_browser(rig, server, display_project):
    playwright = pytest.importorskip('playwright.sync_api')
    refinement2(rig)
    # An EXISTING invalid primary refuses; it never falls back to a mirror.
    write(page.anchor_settings.settings_path(), 'not valid settings {')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            tab = context.new_page()
            tab.goto(server + '/foundry?skill=researchprime')
            tab.get_by_role('heading', name='Walkthrough refused', exact=True).wait_for()
            assert 'never falls back' in tab.locator('#panel').inner_text()
            context.close()
        finally:
            browser.close()


# ── The REAL registered handoff — read-only, through existing discovery ──────
# The surrogate fixtures above stay for hermetic shape coverage; these tests
# resolve the ACTUAL registered researchPrime bundle (42 steps / 32 resources /
# differently-titled documents) through the real content-discovery roots,
# strictly read-only, and skip honestly on a host without it. The source
# bundle commit verified by its own 55-test gate: 1e4aef8b1231d0096abfcfdf4c1bbcb9d4bebc13.

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_MAPS_REL = 'Foundry page and knowledge maps/researchprime/maps.json'
SOURCE_BUNDLE_COMMIT = '1e4aef8b1231d0096abfcfdf4c1bbcb9d4bebc13'
PROOF_DIR = REPO_ROOT / '.proof' / 'foundry-refinement2'
DISPLAY_ASSETS = ('adapter.js', 'flow-diagram.js', 'layer-library.js',
                  'display.css', 'skill-display.js')


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def real_handoff(tmp_path, monkeypatch):
    for var in ('FOUNDRY_TRIO_ROOT', 'FOUNDRY_STEWARD_ROOT', 'FOUNDRY_PAGE_CONTENT_ROOT'):
        monkeypatch.delenv(var, raising=False)
    root = Path(page.api.FOUNDRY_ROOT)
    maps_path = root / REAL_MAPS_REL
    if not maps_path.is_file():
        pytest.skip('registered researchPrime handoff bundle not present on this host')
    monkeypatch.setenv('ANCHOR_DATA_DIR', str(tmp_path / 'anchor-data'))
    monkeypatch.setenv('TEMP', str(tmp_path))
    monkeypatch.setenv('TMP', str(tmp_path))
    monkeypatch.setenv('ANCHOR_PROACTIVE_SUMMARY', '0')
    monkeypatch.delenv('ANCHOR_TOKEN', raising=False)
    import anchor_gui
    pid = 'real-foundry'
    monkeypatch.setattr(anchor_gui._rnd, 'get_project',
                        lambda p: {'id': pid, 'folder_path': str(root)} if p == pid else None)
    monkeypatch.setattr(page, '_review_project_id', lambda: pid)
    if page.find_skill('researchprime') is None:
        pytest.skip('researchPrime is not discoverable through the real roots on this host')
    data = json.loads(maps_path.read_text(encoding='utf-8-sig'))
    return dict(root=root, maps_path=maps_path, data=data, pid=pid)


@pytest.fixture
def real_server(real_handoff):
    import anchor_gui
    srv = anchor_gui.make_server('127.0.0.1', 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{srv.server_address[1]}'
    finally:
        srv.shutdown(); srv.server_close(); thread.join(timeout=5)


def test_real_registered_handoff_payload_binds_declared_snapshots(real_handoff):
    data = real_handoff['data']
    bundle = real_handoff['maps_path'].parent
    sources_dir = (bundle / 'sources').resolve()
    primary_settings(steward_type='ecgberht')
    payload = page.display_payload('researchprime')
    assert payload is not None
    # The ACTUAL declared inventory — the registered handoff, not a surrogate.
    assert len(payload['data']['process']['steps']) == len(data['process']['steps']) >= 40
    assert len(payload['data']['resources']) == len(data['resources']) >= 30
    assert ({str(r['id']) for r in payload['data']['resources']}
            == {str(r['id']) for r in data['resources']})
    # Every real source declares origin + contained snapshot + SNAPSHOT-bound
    # sha256 with NO freshness field; nothing may manufacture frozen-example
    # metadata to force the historical branch.
    assert all(s.get('snapshot') and s.get('origin') and s.get('freshness') is None
               for s in data['sources'])
    # Every anchor link binds to the declared snapshot under sources/ — never
    # the origin — so live-origin drift cannot flag a valid captured file.
    anchors = payload['hrefs']['anchors']
    assert set(anchors) == {str(a['id']) for a in data['anchors']}
    for link in anchors.values():
        assert link['href'] and link['problem'] is None
        assert source_viewer_path(link['href']).parent == sources_dir
    assert payload['issues'] == []
    # The CURRENT primary (a valid Ecgberht — Anchor's default steward) is
    # forwarded as the primary; the bundle snapshot stays a mirror.
    assert payload['settings']['primary']['value']['steward_type'] == 'ecgberht'
    assert payload['settings']['error'] is None
    # Guide and North Star resolve to the REAL registered documents, whose
    # actual titles differ from the old surrogate fixtures.
    hrefs = payload['hrefs']['resources']
    assert hrefs['human-guide']['href'].endswith('/resources/human-guide.html')
    assert hrefs['purpose']['href'].endswith('/resources/purpose.html')
    guide_doc = (bundle / 'resources/human-guide.html').read_text(encoding='utf-8')
    purpose_doc = (bundle / 'resources/purpose.html').read_text(encoding='utf-8')
    assert '<h1>Human guide</h1>' in guide_doc
    assert '<h1>What researchPrime is for</h1>' in purpose_doc
    # The documents' REAL Back links are `target="_top"` standalone-index
    # returns — what the live page must serve in-surface (browser test below).
    assert '<a target="_top" href="../index.html#library">' in guide_doc
    # The anchor-api record: origin outside every discovery root; its declared
    # contained snapshot still resolves, with captured provenance.
    skill = page.find_skill('researchprime')
    api_source = next(s for s in data['sources'] if s['id'] == 'anchor-api')
    assert not page._allowed(Path(str(api_source['origin']).replace('\\', '/')))
    target, provenance, error = page._declared_source(api_source, skill, bundle)
    assert error is None and target == sources_dir / 'anchor-api.py'
    assert provenance['freshness'] == 'captured-snapshot'
    # The cumulative grade-B review record rides through unchanged.
    assert payload['data']['review']['cumulative'][0]['grade'] == 'B'
    assert payload['data']['lifecycle']['accepted'] is False


def test_real_handoff_browser_walkthrough_with_bound_proof(real_handoff, real_server, monkeypatch):
    """Real desktop/phone clicks over the REGISTERED handoff reach the level
    dial, the typed diagram, a real disagreement's anchors and source text, the
    actual guide and North Star (their real `_top` returns served in-surface),
    and the cumulative grade-B record. Screenshots and served bytes are bound
    to the exact handoff in .proof/foundry-refinement2/proof.json."""
    playwright = pytest.importorskip('playwright.sync_api')
    server = real_server
    data = real_handoff['data']
    bundle = real_handoff['maps_path'].parent
    sources_dir = (bundle / 'sources').resolve()
    primary_settings(steward_type='ecgberht')
    steps = data['process']['steps']
    disagreement = data['process']['disagreements'][0]
    target_step = str(disagreement['step_ids'][0])
    instruction_anchor = next(a for a in data['anchors']
                              if a['id'] == disagreement['instruction_anchor'])
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    proof = {'handoff': {'file': REAL_MAPS_REL,
                         'sha256': _sha256(real_handoff['maps_path'].read_bytes()),
                         'source_bundle_commit': SOURCE_BUNDLE_COMMIT,
                         'steps': len(steps), 'resources': len(data['resources']),
                         'disagreement': disagreement['id']},
             'served_assets': {}, 'documents': {}, 'downloads': {}, 'screenshots': {},
             'other_request_failures': []}
    # The served display assets are byte-identical to the shipped files.
    for asset in DISPLAY_ASSETS:
        with urlopen(server + '/static/foundry-display/' + asset) as response:
            served = response.read()
        assert served == (REPO_ROOT / 'static/foundry-display' / asset).read_bytes()
        proof['served_assets'][asset] = _sha256(served)
    # The served guide/North Star ARE the registered documents' exact bytes.
    payload = page.display_payload('researchprime')
    for rid, rel in (('human-guide', 'resources/human-guide.html'),
                     ('purpose', 'resources/purpose.html')):
        with urlopen(server + payload['hrefs']['resources'][rid]['href']) as response:
            served = response.read()
        assert served == (bundle / rel).read_bytes()
        proof['documents'][rel] = _sha256(served)
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                errors, failed, writes = [], [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('response', lambda r: failed.append(r.url) if r.status >= 400 else None)
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)

                def shot(name):
                    path = PROOF_DIR / ('%dx%d-%s.png' % (width, height, name))
                    tab.screenshot(path=str(path))
                    proof['screenshots'][path.name] = _sha256(path.read_bytes())

                tab.goto(server + '/foundry?skill=researchprime')
                tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()

                # The level dial over the real layered catalog.
                tab.get_by_role('link', name='Library', exact=True).click()
                tab.locator('#level-dial').wait_for()
                shot('library-dial')

                # The typed diagram draws EVERY real step; a real disagreement
                # node expands explicitly and the drawing stays readably in
                # the viewport (actual intersection, not box bottom > 0).
                tab.get_by_role('link', name='Process map', exact=True).click()
                tab.locator('.flow-diagram').wait_for()
                assert tab.locator('.flow-diagram a.fd-node').count() == len(steps)
                tab.locator('.flow-diagram a.fd-node[data-step="%s"]' % target_step).click()
                detail = tab.locator('#step-detail[data-step-id="%s"]' % target_step)
                detail.wait_for()
                assert detail.get_attribute('open') is None
                detail.locator('> summary').click()
                assert 'Instructions ≠ code on this node' in detail.inner_text()
                assert visible_height(tab.locator('.diagram-scroll').bounding_box(), height) >= 120
                shot('process-expanded')

                # The real disagreement's anchors open the REAL captured
                # source text through the hash-checked viewer. (A node carries
                # one anchor pair per documented disagreement on it.)
                on_node = sum(1 for d in data['process']['disagreements']
                              if target_step in (d.get('step_ids') or []))
                assert (detail.locator('.reconcile-node .anchor-list a[data-source]').count()
                        == 2 * on_node)
                detail.locator('.reconcile-node .anchor-list a[data-source]').first.click()
                frame = tab.frame_locator('#resource-frame')
                # The CITED line (a108 → skill.md line 208) — not the file top —
                # must intersect the visible iframe AND the screen viewport: the
                # sandboxed frame runs no scripts, so the host does the scroll.
                cited_line_in_view(tab, height)
                hit = frame.locator('.hit')
                assert hit.get_attribute('id') == 'L%d' % instruction_anchor['start']
                assert instruction_anchor['quote'].splitlines()[0].strip() in hit.inner_text()
                viewer_src = tab.locator('#resource-frame').get_attribute('src')
                assert '/foundry/source?' in viewer_src
                assert source_viewer_path(viewer_src).parent == sources_dir
                assert (instruction_anchor['quote'].splitlines()[0].strip()
                        in frame.locator('pre').inner_text())
                shot('disagreement-source')
                tab.locator('#close-resource').click()

                # The ACTUAL guide document; its REAL `target="_top"` Back link
                # is served on the live page — dialog closed, Library open, the
                # host never replaced by the standalone bundle preview.
                tab.locator('.head .actions').get_by_role('link', name='Human guide', exact=True).click()
                frame.get_by_role('heading', name='Human guide', exact=True).wait_for()
                shot('human-guide')
                # The REAL document's Download source button hands over the
                # exact declared source bytes through the contained viewer
                # (sandbox allow-downloads; scripts stay blocked) — an actual
                # captured browser download, not a surrogate or simulation.
                with tab.expect_download() as guide_dl:
                    frame.get_by_role('link', name='Download source', exact=True).click()
                guide_download = guide_dl.value
                assert guide_download.suggested_filename == 'human.md'
                guide_bytes = Path(guide_download.path()).read_bytes()
                assert guide_bytes == (bundle / 'sources/human.md').read_bytes()
                proof['downloads']['human.md'] = _sha256(guide_bytes)
                frame.get_by_role('link', name='← researchPrime Library', exact=True).click()
                tab.locator('#level-dial').wait_for()
                assert not tab.locator('#resource-dialog').is_visible()
                assert '/foundry?skill=researchprime' in tab.url

                # The ACTUAL North Star with its LOCKED authority text; its
                # real `_top` deep link routes the LIVE process map.
                tab.locator('.head .actions').get_by_role('link', name='Original North Star', exact=True).click()
                frame.get_by_role('heading', name='What researchPrime is for', exact=True).wait_for()
                assert 'LOCKED' in frame.locator('body').inner_text()
                shot('north-star')
                # Its real Download source button: the declared skill.md bytes.
                with tab.expect_download() as star_dl:
                    frame.get_by_role('link', name='Download source', exact=True).click()
                star_download = star_dl.value
                assert star_download.suggested_filename == 'skill.md'
                star_bytes = Path(star_download.path()).read_bytes()
                assert star_bytes == (bundle / 'sources/skill.md').read_bytes()
                proof['downloads']['skill.md'] = _sha256(star_bytes)
                frame.get_by_role('link', name='A question arrives', exact=True).click()
                tab.locator('.flow-diagram').wait_for()
                assert not tab.locator('#resource-dialog').is_visible()
                assert '/foundry?skill=researchprime' in tab.url

                # The cumulative grade-B review record.
                tab.get_by_role('link', name='Review record', exact=True).click()
                review_text = tab.locator('#panel').inner_text()
                assert 'Grade: B' in review_text
                assert 'accepted: false' in review_text
                shot('review-record')

                assert not errors and not writes
                blocking = [u for u in failed if any(k in u for k in (
                    '/static/foundry-display/', '/foundry/source', '/artifact/', '/foundry?skill='))]
                assert not blocking
                proof['other_request_failures'].extend(sorted(set(failed)))
                context.close()
        finally:
            browser.close()
    write(PROOF_DIR / 'proof.json', json.dumps(proof, indent=2))


# ── Source viewing corrected after live verification ─────────────────────────
# The durable live packet (19 passes / 3 failures at 1440x1000 and
# touch-enabled 390x844) plus the bounded Gandalf inspection diagnosed two
# PRODUCT defects in the source viewer: (1) the source pre did not wrap, so
# the cited sentence was horizontally clipped on the phone-width view (a108 /
# skill.md line 208 ended around "Judg" — highlighting a line does not prove
# the text is readable); (2) the viewer appended an inline scroll script even
# when embedded in the sandboxed (script-less) dialog frame — a real
# blocked-inline-script console error on every embedded source open. The
# fix: per-line spans wrap (anchors/highlight preserved), and the sandboxed
# dialog requests an explicit script-free `embed=1` variant while plain
# top-level URLs keep the viewer's own scroll script. These tests pin both
# fixes and demonstrably FAIL on the old behavior.


def embed_href(href):
    """The script-free variant the SANDBOXED dialog requests — exactly what
    skill-display.js appends for its no-scripts frame."""
    return href + '&embed=1'


def classify_console_record(record):
    """Attribute ONE captured console message honestly, by frame URL plus the
    harness action active when it fired.

    'product' — fails the walkthrough: any blocked-script message outside the
    demonstrated harness shape (the OLD defect: the viewer's own inline scroll
    script blocked at /foundry/source load time), or any other console error.
    'harness' — the qualified Chromium/Playwright probe observation: a
    blocked-script message in a script-free sandboxed about:srcdoc document
    that fired while the automation itself was acting INSIDE that frame.
    Retained as evidence, never silently dropped — and never excused outside
    a demonstrated in-frame automation window (no blind filtering).
    """
    where = record['frame_url'] + ' ' + record['text']
    if 'Blocked script execution' in record['text']:
        if 'about:srcdoc' in where and record['action'].startswith('in-frame:'):
            return 'harness'
        return 'product'
    if record['type'] == 'error':
        return 'product'
    return 'benign'


def test_console_classifier_rejects_the_old_defect_and_keeps_probe_evidence():
    # The OLD defect's exact shape — the viewer's inline script blocked inside
    # the sandboxed frame at load time — is a PRODUCT error, not harness noise.
    old_defect = dict(
        type='error',
        text="Blocked script execution in 'http://127.0.0.1:43210/foundry/source?"
             "skill=researchprime&path=skill.md&anchor=208' because the document's frame "
             "is sandboxed and the 'allow-scripts' permission is not set.",
        frame_url='http://127.0.0.1:43210/foundry/source?skill=researchprime&path=skill.md&anchor=208',
        action='host:open-citation-embedded')
    assert classify_console_record(old_defect) == 'product'
    # The demonstrated harness shape — about:srcdoc while the automation acts
    # inside that frame — is retained evidence…
    probe = dict(type='error',
                 text="Blocked script execution in 'about:srcdoc' because the document's "
                      "frame is sandboxed and the 'allow-scripts' permission is not set.",
                 frame_url='about:srcdoc', action='in-frame:probe-tap-inside-srcdoc')
    assert classify_console_record(probe) == 'harness'
    # …but the SAME message outside a demonstrated in-frame automation window
    # is NOT excused, and ordinary page errors always count.
    assert classify_console_record(dict(probe, action='host:open-human-guide')) == 'product'
    assert classify_console_record(dict(type='error', text='TypeError: boom',
                                        frame_url='', action='host:initial')) == 'product'
    assert classify_console_record(dict(type='log', text='chatter',
                                        frame_url='', action='host:initial')) == 'benign'


def test_source_page_embedded_variant_drops_only_the_scroll_script(rig):
    import re
    legacy(rig)
    top = page.source_page('researchprime', str(rig['instruction']), '## Entry')
    embedded = page.source_page('researchprime', str(rig['instruction']), '## Entry',
                                embedded=True)
    # Top-level keeps its own scroll script (a real document may run it)…
    script = re.search(r'<script>.*?</script>', top, re.S).group(0)
    assert 'scrollIntoView' in script and top.count('<script>') == 1
    # …the embedded variant ships NO script at all (the old blocked-script
    # console error came from exactly this script inside the sandboxed
    # frame), and is otherwise BYTE-IDENTICAL: same #L<n> line anchors, same
    # .hit highlight, same literal escaped source.
    assert '<script' not in embedded
    assert embedded == top.replace(script, '')
    assert 'class="hit"' in embedded and 'id="L1"' in embedded
    assert '&lt;unsafe&gt;' in embedded and '<unsafe>' not in embedded
    # The phone-clipping fix rides in both variants: per-line spans wrap, so
    # a long cited sentence is never horizontally cut (geometry is proven in
    # the real-browser regression below).
    assert 'white-space:pre-wrap' in embedded and 'overflow-wrap:anywhere' in embedded
    # No hit → no script in either variant: the flag changes nothing else.
    assert (page.source_page('researchprime', str(rig['instruction']), embedded=True)
            == page.source_page('researchprime', str(rig['instruction'])))


def test_source_route_embed_flag_serves_script_free_markup(rig, server):
    import re
    combined(rig)
    with urlopen(server + '/api/foundry/skill?skill=researchprime') as response:
        href = json.load(response)['knowledgeMap']['nodes'][0]['href']
    with urlopen(server + href) as response:
        top = response.read().decode('utf-8')
    # A plain top-level request — and any client that sends no flag — keeps
    # the viewer's own scroll script (real top-level navigation still lands).
    assert 'class="hit"' in top and 'scrollIntoView' in top
    # The sandboxed dialog's embed=1 request gets the script-free variant,
    # byte-identical but for the omitted script. On the old route this very
    # request returned the script — the blocked-script console error.
    with urlopen(server + embed_href(href)) as response:
        embedded = response.read().decode('utf-8')
    assert '<script' not in embedded and 'class="hit"' in embedded
    script = re.search(r'<script>.*?</script>', top, re.S).group(0)
    assert embedded == top.replace(script, '')


def test_real_handoff_source_wraps_and_embeds_clean_desktop_and_touch(real_handoff, real_server):
    """Live-packet regressions over the REGISTERED handoff at 1440x1000 and
    touch-enabled 390x844 (Chromium touch EMULATION — not a hardware phone):

    * the FULL cited sentence is readable — the source view wraps, so nothing
      is horizontally clipped (the live failure: a108 / skill.md line 208
      rendered only up to about "Judg");
    * embedded citation navigation lands on the cited text with NO product
      console or page errors (the old viewer shipped an inline scroll script
      the sandboxed frame blocked);
    * top-level navigation still lands on the cited line, a real heading and
      a real code symbol — the plain URL keeps its own scroll script;
    * each check demonstrably REJECTS the old defect (re-applying the old
      non-wrapping rendering overflows the phone-width frame again; the
      classifier flags the old blocked-script shape);
    * console messages are attributed with frame URL + the active harness
      action, and bounded about:srcdoc probe evidence is retained in
      .proof/foundry-refinement2/console-attribution.json — demonstrated
      harness noise is distinguished from product errors, never filtered
      blindly. Only what this run observed is claimed.
    """
    playwright = pytest.importorskip('playwright.sync_api')
    server = real_server
    data = real_handoff['data']
    primary_settings(steward_type='ecgberht')
    disagreement = data['process']['disagreements'][0]
    target_step = str(disagreement['step_ids'][0])
    instruction_anchor = next(a for a in data['anchors']
                              if a['id'] == disagreement['instruction_anchor'])
    payload = page.display_payload('researchprime')
    cited_href = payload['hrefs']['anchors'][str(instruction_anchor['id'])]['href']
    skill_snapshot = source_viewer_path(cited_href)
    skill_lines = skill_snapshot.read_text(encoding='utf-8').splitlines()
    cited_quote = instruction_anchor['quote'].splitlines()[0].strip()

    # Deterministic product guarantee before any browser runs: the dialog's
    # embed variant carries NO script (a script that does not exist cannot be
    # blocked), while the plain top-level URL keeps the scroll script.
    with urlopen(server + embed_href(cited_href)) as response:
        assert '<script' not in response.read().decode('utf-8')
    with urlopen(server + cited_href) as response:
        assert 'scrollIntoView' in response.read().decode('utf-8')

    # Real top-level navigation targets, data-driven from the registered
    # snapshots: the cited LINE, a deep HEADING (fallback: the cited sentence
    # text itself), and a code SYMBOL when the handoff declares a code
    # snapshot — "as applicable", nothing fabricated.
    targets = [(str(instruction_anchor['start']), int(instruction_anchor['start']),
                skill_snapshot)]
    heading = None
    for i in range(len(skill_lines), 0, -1):
        text = skill_lines[i - 1]
        if text.startswith('## ') and len(text.strip()) > 3:
            first = next(j for j, l in enumerate(skill_lines, 1) if text in l)
            if first > 40:
                heading = (text, first, skill_snapshot)
                break
    targets.append(heading or (cited_quote,
                               next(j for j, l in enumerate(skill_lines, 1)
                                    if cited_quote in l),
                               skill_snapshot))
    for a in data['anchors']:
        src = next((s for s in data['sources'] if str(s['id']) == str(a['source_id'])), None)
        if src and str(src.get('snapshot', '')).endswith(('.py', '.mjs', '.js')):
            code_path = source_viewer_path(payload['hrefs']['anchors'][str(a['id'])]['href'])
            code_lines = code_path.read_text(encoding='utf-8').splitlines()
            symbol = next((l.strip() for n, l in enumerate(code_lines, 1) if n > 3
                           and l.strip().startswith(('def ', 'class ', 'function ',
                                                     'const ', 'export '))), None)
            if symbol:
                targets.append((symbol,
                                next(j for j, l in enumerate(code_lines, 1) if symbol in l),
                                code_path))
                break

    evidence = {
        'qualification': 'Touch viewport is Chromium emulation at 390x844 — not a hardware '
                         'phone. about:srcdoc attribution is a probe observation on THIS '
                         'harness run, recorded with frame URL + active automation action; '
                         'nothing beyond what this run observed is claimed.',
        'chromium': None, 'playwright': None, 'viewports': []}
    try:
        from importlib.metadata import version as dist_version
        evidence['playwright'] = dist_version('playwright')
    except Exception:
        evidence['playwright'] = 'unknown'
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        evidence['chromium'] = browser.version
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                touch = width < 780
                context = browser.new_context(viewport={'width': width, 'height': height},
                                              has_touch=touch)
                tab = context.new_page()
                action = ['host:initial']
                records, page_errors = [], []
                tab.on('pageerror', lambda e, _p=page_errors: _p.append(str(e)))
                tab.on('console', lambda m, _r=records, _a=action: _r.append(
                    {'type': m.type, 'text': m.text[:240],
                     'frame_url': (m.location or {}).get('url', ''),
                     'action': _a[0]}) if len(_r) < 400 else None)

                def act(label, locator, _touch=touch, _action=action):
                    _action[0] = label
                    (locator.tap if _touch else locator.click)()

                tab.goto(server + '/foundry?skill=researchprime')
                tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()
                act('host:open-process', tab.get_by_role('link', name='Process map', exact=True))
                tab.locator('.flow-diagram').wait_for()
                act('host:select-step',
                    tab.locator('.flow-diagram a.fd-node[data-step="%s"]' % target_step))
                detail = tab.locator('#step-detail[data-step-id="%s"]' % target_step)
                detail.wait_for()
                act('host:expand-record', detail.locator('> summary'))

                # EMBEDDED navigation lands on the cited text: the frame is
                # script-free (embed=1) and the HOST scrolls the .hit line.
                act('host:open-citation-embedded',
                    detail.locator('.reconcile-node .anchor-list a[data-source]').first)
                cited_line_in_view(tab, height)
                frame = tab.frame_locator('#resource-frame')
                hit = frame.locator('.hit')
                assert hit.get_attribute('id') == 'L%d' % instruction_anchor['start']
                assert cited_quote in hit.inner_text()
                viewer_src = tab.locator('#resource-frame').get_attribute('src')
                assert '/foundry/source?' in viewer_src and 'embed=1' in viewer_src
                # The open-in-new-tab link keeps the PLAIN top-level URL whose
                # own scroll script may legitimately run.
                assert 'embed=' not in tab.locator('#resource-new-tab').get_attribute('href')

                # The FULL cited sentence is readable: no horizontal clipping
                # of the pre, the cited line, or its right edge — combined
                # with cited_line_in_view's whole-box visibility this proves
                # the sentence END (the live packet lost "…DECIDES") is on
                # screen, not merely attached off-viewport.
                assert frame.locator('pre').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                assert hit.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                assert hit.evaluate('el => el.getBoundingClientRect().right'
                                    ' <= document.documentElement.clientWidth + 1')
                if touch:
                    # Demonstrate the SAME check rejects the old defect:
                    # re-applying the old non-wrapping rendering makes the
                    # registered source physically overflow the 390px frame…
                    action[0] = 'in-frame:old-defect-css-probe'
                    assert frame.locator('pre').evaluate(
                        "el => {const s = document.createElement('style');"
                        " s.id = 'old-defect';"
                        " s.textContent = 'pre span{white-space:pre !important}';"
                        " document.head.appendChild(s);"
                        " return el.scrollWidth > el.clientWidth; }")
                    # …and the shipped wrap restores readability.
                    assert frame.locator('pre').evaluate(
                        "el => {document.getElementById('old-defect').remove();"
                        " return el.scrollWidth <= el.clientWidth + 1; }")
                act('host:close-citation', tab.locator('#close-resource'))

                # about:srcdoc PROBE (the qualified harness observation):
                # open a rendered srcdoc document, then deliberately automate
                # a click INSIDE it and record what the harness itself
                # induces in a script-free sandboxed document.
                act('host:open-human-guide',
                    tab.locator('.head .actions').get_by_role('link', name='Human guide',
                                                              exact=True))
                guide_heading = frame.get_by_role('heading', name='Human guide', exact=True)
                guide_heading.wait_for()
                srcdoc_blocked = lambda: sum(
                    1 for r in records if 'Blocked script execution' in r['text']
                    and 'about:srcdoc' in (r['frame_url'] + ' ' + r['text']))
                before = srcdoc_blocked()
                act('in-frame:probe-tap-inside-srcdoc', guide_heading)
                action[0] = 'in-frame:probe-settle'
                tab.wait_for_timeout(400)
                after = srcdoc_blocked()
                act('host:close-guide', tab.locator('#close-resource'))

                # TOP-LEVEL navigation still lands: line, heading and symbol
                # targets scroll via the viewer's own retained script.
                for anchor_text, expected_line, path_ in targets:
                    action[0] = 'host:goto-source-top-level'
                    tab.goto(server + page.source_url('researchprime', path_, anchor_text))
                    tab.wait_for_function(
                        "() => {const h = document.querySelector('.hit');"
                        " if (!h) return false; const r = h.getBoundingClientRect();"
                        " return r.top >= -1 && r.bottom <= window.innerHeight + 1"
                        " && r.right <= document.documentElement.clientWidth + 1;}")
                    assert tab.locator('.hit').get_attribute('id') == 'L%d' % expected_line
                    assert tab.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    if expected_line > 60:
                        assert tab.evaluate('window.scrollY') > 0   # it actually travelled

                product = [r for r in records if classify_console_record(r) == 'product']
                harness = [r for r in records if classify_console_record(r) == 'harness']
                evidence['viewports'].append({
                    'viewport': '%dx%d' % (width, height), 'touch_emulation': touch,
                    'console_messages_total': len(records),
                    'srcdoc_blocked_before_probe': before,
                    'srcdoc_blocked_after_probe': after,
                    'probe_reproduced_harness_messages': after > before,
                    'harness_attributed': harness[:24],
                    'product_attributed': product[:24]})
                assert not page_errors, page_errors
                # NO product console errors anywhere in the walkthrough — in
                # particular no blocked-script attributed to /foundry/source
                # (the old defect's exact signature).
                assert not product, product
                context.close()
        finally:
            browser.close()
            # Retain the bounded attribution evidence even on a red run.
            PROOF_DIR.mkdir(parents=True, exist_ok=True)
            write(PROOF_DIR / 'console-attribution.json', json.dumps(evidence, indent=2))
