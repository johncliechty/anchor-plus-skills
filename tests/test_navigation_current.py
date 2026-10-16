from steward_cockpit.steward_campaign import current_review_items, work_stream_model
from steward_cockpit.navigation_compat import with_compat_navigation


def test_current_designation_ownership_and_history():
    steps = [
        {'id': '2', 'name': 'Tracker draft', 'status': 'active'},
        {'id': 'other', 'name': 'Other draft', 'status': 'active'},
        {'id': 'done', 'name': 'Complete', 'status': 'done'},
        {'id': 'support', 'name': 'Evidence', 'status': 'active', 'navigation': {'role': 'support'}},
        {'id': 'hidden', 'name': 'Hidden', 'status': 'active', 'navigation': {'current': False}},
    ]
    rows = [
        {'step': '2', 'what': 'START HERE — Tracker', 'path': 'current.html'},
        {'step': 'TRACKER', 'what': 'CURRENT: Reading copy', 'path': 'copy.html'},
        {'step': 'draft', 'what': 'START HERE: ambiguous', 'path': 'ambiguous.html'},
        {'step': 'other', 'what': 'Notes about current review', 'path': 'notes.html'},
        {'step': 'done', 'what': 'START HERE: Complete', 'path': 'done.html'},
        {'step': 'support', 'what': 'START HERE: Evidence', 'path': 'support.html'},
        {'step': 'hidden', 'what': 'START HERE: Hidden', 'path': 'hidden.html'},
        {'step': '2', 'what': 'START HERE: Approved', 'path': 'approved.html', 'accepted_current': True},
    ]
    m = with_compat_navigation({'name': 'Project', 'steps': steps})
    assert [r['path'] for r in current_review_items(m, rows)] == ['current.html', 'copy.html']


def test_featured_and_managed_revision_remain_current_without_inferred_acceptance():
    m = {'steps': [{'id': 'story', 'name': 'Story', 'status': 'active',
                   'navigation': {'path': ['book'], 'featured_paths': ['boards/current.html']}},
                  {'id': 'revision', 'name': 'Guide', 'status': 'done'}]}
    rows = [{'step': 'STORY', 'path': 'boards\\current.html'},
            {'step': 'story', 'path': 'old.html', 'what': 'Earlier work'},
            {'step': 'revision', 'managed': True, 'phase': 'revising'},
            {'step': 'revision', 'managed': True, 'phase': 'done'},
            {'step': 'revision', 'managed': True, 'phase': 'revising', 'accepted_current': True}]
    assert current_review_items(m, rows) == rows[:1] + rows[2:3]


def test_empty_and_orphan_artifacts_share_navigation_shell():
    m = with_compat_navigation({'name': 'Empty project', 'steps': []})
    row = {'what': 'Unassigned file', 'path': 'file.html', 'step': 'unknown'}
    model = work_stream_model(m, [row])
    assert [g['label'] for g in model['roots']] == ['Empty project']
    assert model['roots'][0]['children'][0]['label'] == 'Other work — needs organization'
    assert model['roots'][0]['children'][0]['items'] == [row]
    assert current_review_items(m, [row]) == []


def test_ordinal_or_name_cannot_turn_duplicate_id_into_canonical_owner(monkeypatch):
    from steward_cockpit import steward_campaign as c
    from steward_cockpit.navigation_compat import resolve_step
    steps = [{'id': 'collision', 'name': 'First', 'status': 'done'},
             {'id': 'COLLISION', 'name': 'Second', 'status': 'active'}]
    assert resolve_step(steps, '2') is None
    assert resolve_step(steps, 'Second') is None
    row = {'step': '2', 'what': 'START HERE: ambiguous ownership', 'path': 'second.html'}
    map_ = with_compat_navigation({'name': 'Project', 'steps': steps})
    monkeypatch.setattr(c, 'read_map', lambda _: map_)
    monkeypatch.setattr(c, '_read_deliverables', lambda _: {'items': [row]})
    decorated = c.read_deliverables('unused')['items'][0]
    assert decorated['owner_step_id'] is None
    assert decorated['is_current'] is False
    assert current_review_items(map_, [{**row, 'managed': True, 'phase': 'revising'}]) == []
    model = work_stream_model(map_, [decorated])
    assert model['roots'][0]['children'][0]['items'] == [decorated]
