"""Consume the exact shared Trio fixture, without adapting incompatible inputs.

The generic fixture is packaged in this repository so collaborator tests do not
depend on a sibling checkout or a personal path. The cross-repository release
gate additionally verifies that the two fixture copies are byte-identical.
"""
import json
from pathlib import Path

import pytest

from model_policy import (
    DEFAULT_POLICY,
    PolicyUnavailable,
    normalize_catalog,
    select_model,
)


_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "model-policy-v1.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_shared_model_policy_fixture_schema_and_policy_are_explicit():
    assert _FIXTURE["schema_version"] == 1
    assert _FIXTURE["contract"] == "anchor-trio-model-policy-v1"
    assert _FIXTURE["policy"] == DEFAULT_POLICY
    assert isinstance(_FIXTURE["cases"], list) and _FIXTURE["cases"]
    identifiers = [item["id"] for item in _FIXTURE["cases"]]
    assert len(set(identifiers)) == len(identifiers)


@pytest.mark.parametrize("item", _FIXTURE["cases"], ids=lambda item: item["id"])
def test_shared_model_policy_contract(item):
    expected = item["expected"]

    def evaluate():
        # Deliberately no Python-specific schema conversion or permissive fallback.
        catalog = normalize_catalog(item["family"], item["raw"])
        assert "synthetic-secret-never-retained" not in json.dumps(catalog)
        return select_model(item["family"], catalog)

    if expected["outcome"] == "unavailable":
        # Incidental TypeError/KeyError must fail this gate, not count as rejection.
        with pytest.raises(PolicyUnavailable) as raised:
            evaluate()
        assert str(raised.value)
        return

    assert expected["outcome"] == "selected"
    actual = evaluate()
    for key in ("model", "effort", "selection_evidence", "model_attested"):
        assert actual[key] == expected[key], f"{item['id']}: {key}"
    if expected.get("warning_required"):
        assert isinstance(actual.get("warning"), str)
        assert actual["warning"].strip(), "A visible capability warning is required"
