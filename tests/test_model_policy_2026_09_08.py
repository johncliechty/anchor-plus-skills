"""Capability-driven policy: synthetic identities deliberately change over time."""
import pytest
import model_policy as policy


def codex_raw(model="future-frontier", effort="ultra"):
    return {"models": [
        {"slug": "zz-older", "priority": 8, "visibility": "list",
         "supported_reasoning_levels": [{"effort": "high"}]},
        {"slug": model, "priority": 1, "visibility": "list",
         "supported_reasoning_levels": [{"effort": "low"}, {"effort": effort}]},
        {"slug": "hidden-internal", "priority": 0, "visibility": "hide",
         "supported_reasoning_levels": [{"effort": "ultra"}]},
    ]}


@pytest.mark.parametrize("name", ["future-frontier", "another-generation", "a-model-with-no-number"])
def test_catalog_priority_not_product_name(name):
    selection = policy.select_model("chatgpt", policy.normalize_catalog("chatgpt", codex_raw(name)))
    assert selection["model"] == name
    assert selection["effort"] == "ultra"
    assert not selection["model_attested"]


def test_explicit_upgrade_and_missing_target():
    rows = policy.normalize_catalog("chatgpt", codex_raw())
    rows[0]["upgrade"] = "future-frontier"
    assert policy.select_model("chatgpt", rows)["model"] == "future-frontier"
    rows[1]["upgrade"] = "unavailable"
    with pytest.raises(policy.PolicyUnavailable, match="upgrade is unavailable"):
        policy.select_model("chatgpt", rows)


def test_grok_uses_provider_order_and_own_highest_effort():
    raw = {"models": {
        "new": {"info": {"model": "new-name", "reasoning_efforts": [{"value": "xhigh"}, {"value": "high"}], "extra_headers": {"secret": "placeholder"}}},
        "old": {"info": {"model": "z-old", "reasoning_efforts": [{"value": "high"}]}}
    }}
    rows = policy.normalize_catalog("grok", raw)
    selected = policy.select_model("grok", rows)
    assert (selected["model"], selected["effort"]) == ("new-name", "xhigh")
    assert selected["warning"]
    assert "secret" not in str(rows)


def test_claude_uses_moving_frontier_alias_and_max():
    chosen = policy.select_model("claude", policy.normalize_catalog("claude", {"efforts": ["low", "high", "xhigh", "max"]}))
    assert policy.launch_args(chosen) == ["--model", "best", "--effort", "max"]


@pytest.mark.parametrize("levels", [[], ["new-unknown-level"], ["high", "unrecognized"]])
def test_unknown_effort_cannot_silently_downgrade(levels):
    with pytest.raises(ValueError):
        policy.highest_effort(levels)


def test_stale_pins_removed_without_broadening_permissions():
    env = policy.policy_environment({"ANTHROPIC_DEFAULT_OPUS_MODEL": "old", "GROK_DEFAULT_MODEL": "old",
                                     "CODEX_MODEL": "old", "SECRET_TOKEN": "keep", "SANDBOX": "read-only"})
    assert env == {"SECRET_TOKEN": "keep", "SANDBOX": "read-only"}


def test_cache_refresh_changes_identity_without_code_update(monkeypatch):
    monkeypatch.setattr(policy, "_MEMORY", {})
    calls = []
    def discoverer(family, env):
        name = "catalog-one" if not calls else "catalog-two"
        calls.append(name)
        return policy.normalize_catalog(family, codex_raw(name)), "subscription-cli"
    one = policy.resolve("chatgpt", env={}, discoverer=discoverer)
    assert policy.resolve("chatgpt", env={}, discoverer=discoverer)["model"] == one["model"]
    assert policy.resolve("chatgpt", env={}, force=True, discoverer=discoverer)["model"] == "catalog-two"
    assert len(calls) == 2


def test_invalid_settings_blocks_launch_without_discovery():
    with pytest.raises(policy.PolicyUnavailable, match="settings are invalid"):
        policy.resolve("chatgpt", settings={"settings_error": "corrupt"})


def test_subagent_model_and_effort_are_explicit():
    chosen = policy.select_model("chatgpt", policy.normalize_catalog("chatgpt", codex_raw()))
    args = policy.launch_args(chosen)
    assert 'agents.default_subagent_model="future-frontier"' in args
    assert 'agents.default_subagent_reasoning_effort="ultra"' in args
