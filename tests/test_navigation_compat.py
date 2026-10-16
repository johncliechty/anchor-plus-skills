"""Pure candidate tests; no campaign files, services, or skill engines involved."""

from copy import deepcopy
import unittest
from steward_cockpit.navigation_compat import with_compat_navigation, resolve_step


def campaign(*steps, name='Existing campaign'):
    return {'name': name, 'steps': list(steps), 'metadata': {'values': [1]}}


def proposal(product=None, **updates):
    event = {
        'kind': 'kickoff_proposal', 'proposal_id': 'proposal-1',
        'proposal_hash': 'hash-1', 'version': 1, 'seq': 1,
        'confirmed': False, 'requires_confirm': True,
        'work_product': product if product is not None else {
            'id': 'known-product', 'name': 'Confirmed product',
            'components': [
                {'id': 'calendar', 'name': 'Reminder calendar'},
                {'id': 'log', 'name': 'Activity log'},
                {'id': 'report', 'name': 'Summary report'},
            ],
        },
    }
    event.update(updates)
    return event


def confirmation(proposed, **updates):
    event = {'kind': 'kickoff_confirm', 'seq': 2,
             **{key: proposed[key] for key in ('proposal_id', 'proposal_hash', 'version')}}
    event.update(updates)
    return event


def roadmap(*events):
    return {'roadmap_events': list(events), 'roadmap_projection': []}


class NavigationCompatTests(unittest.TestCase):
    def test_deep_immutability_including_returned_navigation_and_ownership(self):
        source = campaign({'id': 'stable', 'name': 'Existing label', 'status': 'pending',
                           'component_ids': ['calendar'],
                           'navigation': {'current': False, 'custom': {'values': [2]}}})
        proposed = proposal()
        proposed['work_product']['components'][0]['notes'] = {'tags': []}
        history = roadmap(proposed, confirmation(proposed))
        original_source, original_history = deepcopy(source), deepcopy(history)
        output = with_compat_navigation(source, history)
        self.assertEqual(source, original_source)
        self.assertEqual(history, original_history)
        output['metadata']['values'].append(3)
        output['steps'][0]['component_ids'].append('log')
        output['steps'][0]['navigation']['path'].append('new')
        output['steps'][0]['navigation']['custom']['values'].append(4)
        output['steps'][0]['navigation']['groups'][0]['label'] = 'Changed output only'
        output['navigation_fallback']['components'][0]['notes']['tags'].append('output')
        self.assertEqual(source, original_source)
        self.assertEqual(history, original_history)

    def test_any_explicit_path_including_empty_preserves_complete_navigation(self):
        for path in ([], ['authored-root', 'authored-group']):
            with self.subTest(path=path):
                source = campaign(
                    {'id': 'a', 'name': 'A', 'navigation': {
                        'path': path, 'role': 'support', 'current': False,
                        'groups': [{'id': 'authored-root', 'label': 'Author label'}],
                        'acceptance': {'approved': False}}},
                    {'legacy': 'A malformed neighbor stays untouched'}, name='')
                expected = deepcopy(source)
                expected['navigation_mode'] = 'explicit'
                output = with_compat_navigation(source, roadmap(proposal(confirmed=True)))
                self.assertEqual(output, expected)
                self.assertNotIn('navigation_fallback', output)
                self.assertIsNot(output['steps'][0]['navigation'], source['steps'][0]['navigation'])

    def test_only_an_earlier_matching_confirmation_establishes_the_product(self):
        source = campaign({'id': 'a', 'name': 'A'})
        proposed = proposal()
        cases = [
            roadmap(proposed),
            roadmap(proposal(confirmed=True)),
            roadmap(confirmation(proposed), proposed),
            {'roadmap_events': [], 'roadmap_projection': [proposed, confirmation(proposed)]},
        ]
        for history in cases:
            with self.subTest(history=history):
                output = with_compat_navigation(source, history)
                self.assertEqual(output['navigation_fallback']['label'], source['name'])
        output = with_compat_navigation(source, roadmap(proposed, confirmation(proposed)))
        self.assertEqual(output['navigation_fallback']['id'], 'known-product')
        self.assertEqual(output['navigation_fallback']['label'], 'Confirmed product')

    def test_latest_unmatched_or_malformed_confirmation_clears_older_candidate(self):
        proposed = proposal()
        source = campaign({'id': 'a', 'name': 'A'})
        bad_confirmations = [
            confirmation(proposed, proposal_id='different'),
            confirmation(proposed, proposal_hash='different'),
            confirmation(proposed, version=2),
            confirmation(proposed, version=True),
            {'kind': 'kickoff_confirm'},
        ]
        for bad in bad_confirmations:
            with self.subTest(bad=bad):
                history = roadmap(proposed, confirmation(proposed), bad)
                output = with_compat_navigation(source, history)
                self.assertEqual(output['navigation_fallback']['label'], source['name'])

    def test_conflicting_proposal_identity_is_not_resolved_by_guessing(self):
        first = proposal()
        conflicting = deepcopy(first)
        conflicting['work_product']['name'] = 'Conflicting label'
        source = campaign({'id': 'a', 'name': 'A'})
        output = with_compat_navigation(source, roadmap(first, conflicting, confirmation(first)))
        self.assertEqual(output['navigation_fallback']['label'], source['name'])
        poisoned_after_selection = with_compat_navigation(
            source, roadmap(first, confirmation(first), conflicting))
        self.assertEqual(poisoned_after_selection['navigation_fallback']['label'], source['name'])
        reconfirmed_poisoned_key = with_compat_navigation(
            source, roadmap(first, confirmation(first), conflicting, deepcopy(first), confirmation(first)))
        self.assertEqual(reconfirmed_poisoned_key['navigation_fallback']['label'], source['name'])
        duplicate = with_compat_navigation(source, roadmap(first, deepcopy(first), confirmation(first)))
        self.assertEqual(duplicate['navigation_fallback']['label'], 'Confirmed product')

    def test_component_groups_keep_one_canonical_step_and_declared_references(self):
        proposed = proposal()
        source = campaign(
            {'id': 'single', 'name': 'Single owner', 'component_ids': ['calendar']},
            {'id': 'multi', 'name': 'Shared artifact', 'component_ids': ['log', 'calendar', 'log']},
            {'id': 'zero', 'name': 'No declared owner', 'component_ids': []},
            {'id': 'orphan', 'name': 'Unknown owner', 'component_ids': ['missing']},
            {'id': 'mixed', 'name': 'One known owner', 'component_ids': ['missing', 'log']},
        )
        output = with_compat_navigation(source, roadmap(proposed, confirmation(proposed)))
        steps = {step['id']: step for step in output['steps']}
        self.assertEqual(len(output['steps']), len(source['steps']))
        self.assertEqual(steps['single']['navigation']['path'], ['known-product', 'calendar'])
        self.assertEqual(steps['multi']['navigation']['path'], ['known-product'])
        self.assertEqual(steps['multi']['navigation']['related_paths'],
                         [['known-product', 'log'], ['known-product', 'calendar']])
        for identity in ('zero', 'orphan'):
            self.assertEqual(steps[identity]['navigation']['path'], ['known-product'])
            self.assertNotIn('related_paths', steps[identity]['navigation'])
        self.assertEqual(steps['mixed']['navigation']['path'], ['known-product', 'log'])
        self.assertEqual(steps['single']['navigation']['include_paths'], [
            ['known-product', 'calendar'], ['known-product', 'log'], ['known-product', 'report']])
        self.assertEqual([step['component_ids'] for step in output['steps']],
                         [step['component_ids'] for step in source['steps']])

    def test_existing_support_role_current_false_and_metadata_are_preserved(self):
        source = campaign({'id': 'support', 'name': 'Existing supporting evidence',
                           'navigation': {'role': 'support', 'current': False,
                                          'support': {'owner': 'existing'},
                                          'acceptance': {'approved': False}}})
        output = with_compat_navigation(source)
        navigation = output['steps'][0]['navigation']
        self.assertEqual(navigation['role'], 'support')
        self.assertIs(navigation['current'], False)
        self.assertEqual(navigation['support'], {'owner': 'existing'})
        self.assertEqual(navigation['acceptance'], {'approved': False})
        self.assertNotIn('featured', navigation)

    def test_missing_duplicate_and_nameless_legacy_steps_remain_unclassified(self):
        source = campaign(
            {'name': 'Missing ID', 'status': 'pending'},
            {'id': 'nameless'},
            {'id': 'duplicate', 'name': 'First duplicate'},
            {'id': 'DUPLICATE', 'name': 'Second duplicate'},
            {},
            {'id': 'stable', 'name': 'Valid existing step', 'status': 'done'},
        )
        original = deepcopy(source)
        output = with_compat_navigation(source)
        self.assertEqual(source, original)
        self.assertEqual(len(output['steps']), len(source['steps']))
        for old, new in zip(source['steps'][:-1], output['steps'][:-1]):
            self.assertEqual(new['navigation']['path'], [])
            self.assertEqual({key: value for key, value in new.items() if key != 'navigation'}, old)
        self.assertEqual(output['steps'][-1]['navigation']['path'],
                         ['compat-root', 'compat-step:stable'])
        self.assertEqual(output['steps'][0]['navigation']['groups'], [
            {'id': 'compat-root', 'label': source['name']},
            {'id': 'compat-step:stable', 'label': 'Valid existing step'},
        ])

    def test_blank_and_empty_campaigns_have_an_honest_root_without_new_steps(self):
        source = campaign(name='   ')
        output = with_compat_navigation(source)
        self.assertEqual(output['steps'], [])
        self.assertEqual(output['name'], '   ')
        self.assertEqual(output['navigation_fallback']['label'], 'Project work')
        proposed = proposal()
        confirmed = with_compat_navigation(source, roadmap(proposed, confirmation(proposed)))
        self.assertEqual(confirmed['steps'], [])
        self.assertEqual(confirmed['navigation_fallback']['label'], 'Confirmed product')
        self.assertEqual(len(confirmed['navigation_fallback']['components']), 3)

    def test_step_group_identity_survives_reordering_and_preserves_actual_labels(self):
        first = {'id': 'stable-A', 'name': 'Actual first label', 'status': 'done'}
        second = {'id': 'stable-B', 'name': 'Actual second label', 'status': 'pending'}
        forward = with_compat_navigation(campaign(first, second))
        reverse = with_compat_navigation(campaign(second, first))
        self.assertEqual({step['id']: step['navigation']['path'] for step in forward['steps']},
                         {step['id']: step['navigation']['path'] for step in reverse['steps']})
        self.assertEqual([step['name'] for step in forward['steps']], [first['name'], second['name']])
        self.assertEqual([step['status'] for step in forward['steps']], ['done', 'pending'])
        self.assertTrue(all('current' not in step['navigation'] for step in forward['steps']))

    def test_numeric_stable_id_precedes_legacy_ordinal(self):
        steps = [{'id': 'alpha', 'name': 'First'}, {'id': '1', 'name': 'Numeric stable ID'},
                 {'id': 'gamma', 'name': 'Unique topic'}]
        self.assertIs(resolve_step(steps, '1'), steps[1])
        self.assertIs(resolve_step(steps, 1), steps[1])
        self.assertIs(resolve_step(steps, '2'), steps[1])
        self.assertIs(resolve_step(steps, 'ALPHA'), steps[0])
        self.assertIs(resolve_step(steps, 'TOPIC'), steps[2])
        self.assertIsNone(resolve_step(steps, '9' * 10000))
        self.assertIsNone(resolve_step(steps, True))

    def test_ambiguous_ids_and_fragments_do_not_choose_a_step(self):
        duplicate_ids = [{'id': 'same', 'name': 'A'}, {'id': 'SAME', 'name': 'B'}]
        self.assertIsNone(resolve_step(duplicate_ids, 'same'))
        steps = [{'id': 'a', 'name': 'Build report'}, {'id': 'b', 'name': 'Build calendar'}]
        self.assertIsNone(resolve_step(steps, 'build'))
        self.assertIsNone(resolve_step(steps, ''))
        self.assertIsNone(resolve_step([], '1'))
        self.assertIsNone(resolve_step([{}, {'name': 'Orphan'}], 'missing'))


if __name__ == '__main__':
    unittest.main()
