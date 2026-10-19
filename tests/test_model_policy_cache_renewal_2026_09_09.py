"""A provider-validated unchanged catalog remains usable; invalid clocks refuse."""
from datetime import datetime, timedelta, timezone
import json

import pytest
import model_policy as policy


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / '.grok'
    root.mkdir()
    filename = root / 'models_cache.json'
    now = datetime.now(timezone.utc)
    stamp = lambda seconds: (now + timedelta(seconds=seconds)).isoformat()
    raw = {'fetched_at': stamp(-900), 'renewed_at': stamp(-5),
           'grok_version': '1.0.25', 'auth_method': 'session',
           'origin': 'https://cli-chat-proxy.grok.com/v1/models',
           'models': {'frontier': {'info': {'model': 'future-catalog',
                       'reasoning_efforts': [{'value': 'xhigh'}]}}}}
    monkeypatch.setattr(policy.shutil, 'which', lambda *args, **kwargs: 'fixture-grok')
    calls = []
    def runner(argv, env):
        calls.append(argv[1:])
        return 'grok 1.0.25' if argv[1:] == ['--version'] else 'models'
    def discover(**changes):
        filename.write_text(json.dumps(dict(raw, **changes)), encoding='utf-8')
        return policy.discover('grok', env={'USERPROFILE': str(tmp_path)}, runner=runner)
    return discover, stamp, calls


def test_unchanged_catalog_with_fresh_provider_renewal(catalog):
    discover, _, calls = catalog
    rows, command = discover()
    assert policy.select_model('grok', rows)['model'] == 'future-catalog'
    assert command == 'fixture-grok'
    assert calls == [['--version'], ['models']]


def test_fresh_legacy_catalog_without_renewal(catalog):
    discover, stamp, _ = catalog
    assert discover(fetched_at=stamp(-10), renewed_at=None)[0]


@pytest.mark.parametrize('case', ['absent', 'stale', 'future', 'malformed', 'numeric', 'backwards', 'future_fetch'])
def test_invalid_freshness_is_not_a_model_selection(catalog, case):
    discover, stamp, _ = catalog
    changes = {
        'absent': {'renewed_at': None},
        'stale': {'renewed_at': stamp(-400)},
        'future': {'renewed_at': stamp(60)},
        'malformed': {'renewed_at': 'invalid'},
        'numeric': {'renewed_at': 123},
        'backwards': {'renewed_at': stamp(-1000)},
        'future_fetch': {'fetched_at': stamp(60)},
    }[case]
    with pytest.raises(policy.PolicyUnavailable):
        discover(**changes)


@pytest.mark.parametrize('changes', [{'auth_method': 'api_key'}, {'origin': 'https://example.test/models'}, {'grok_version': '0.0.0'}])
def test_renewal_does_not_replace_subscription_provenance(catalog, changes):
    discover, _, _ = catalog
    with pytest.raises(policy.PolicyUnavailable):
        discover(**changes)
