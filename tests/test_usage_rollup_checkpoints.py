from steward_cockpit import steward_engine, steward_routes


def _recorded_usage(initial_spend, tokens, **extra):
    return {
        "reported_spend": initial_spend,
        "spend": initial_spend,
        "unpriced_turns": 0,
        "cost_complete": True,
        "tokens": tokens,
        "token_status": "reported",
        "secs": 60,
        **extra,
    }


def _estate(monkeypatch, entries):
    monkeypatch.setattr(steward_engine, "_read_all_state", lambda: entries)


def test_chatgpt_unpriced_turns_are_labeled_subscription(monkeypatch, tmp_path):
    """MBA-like ChatGPT seats omit dollars; the line must not look broken."""
    _estate(monkeypatch, {
        str(tmp_path): {
            "cli": "chatgpt",
            "usage": {
                "reported_spend": 11.6975,
                "spend": None,
                "unpriced_turns": 45,
                "cost_complete": False,
                "cost_status": "partial",
                "tokens": 107167250,
                "token_status": "partial",
                "secs": 34357,
                "usage_source": "codex-rollout",
            },
        }
    })
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["reported_spend"] == 11.6975
    assert total["spend"] is None
    assert total["unpriced_turns"] == 45
    assert total["tokens"] == 107167250
    assert total["billing_mode"] == "subscription"
    assert total["billing_family"] == "chatgpt"
    assert total["cost_text"] == (
        "$11.70 previously reported · ChatGPT subscription (45 turns)")
    assert "incomplete" not in total["cost_text"]


def test_grok_unpriced_turns_are_labeled_subscription(monkeypatch, tmp_path):
    _estate(monkeypatch, {
        str(tmp_path): {
            "cli": "grok",
            "usage": {
                "reported_spend": 11.6975,
                "spend": None,
                "unpriced_turns": 64,
                "cost_complete": False,
                "cost_status": "partial",
                "tokens": 146412301,
                "token_status": "partial",
            },
        }
    })
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["billing_mode"] == "subscription"
    assert total["billing_family"] == "grok"
    assert total["cost_text"] == (
        "$11.70 previously reported · Grok subscription (64 turns)")


def test_claude_unpriced_turns_stay_unpriced_not_subscription(monkeypatch, tmp_path):
    _estate(monkeypatch, {
        str(tmp_path): {
            "cli": "claude",
            "usage": {
                "reported_spend": 2.5,
                "unpriced_turns": 3,
                "cost_complete": False,
                "tokens": 100,
            },
        }
    })
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["billing_mode"] is None
    assert "unpriced usage" in total["cost_text"]
    assert "subscription" not in total["cost_text"]


def test_empty_rollup_reports_unavailable_instead_of_zero(monkeypatch, tmp_path):
    _estate(monkeypatch, {})
    rollup = steward_routes._usage_rollup(str(tmp_path))
    for bucket in rollup.values():
        assert bucket["reported_spend"] == 0
        assert bucket["tokens"] == 0
        assert bucket["cost_status"] == "unavailable"
        assert bucket["spend"] is None
        assert bucket["cost_complete"] is False
        assert bucket["token_status"] == "unavailable"
        assert bucket["usage_updated_at"] is None


def test_explicit_reported_zero_remains_a_real_zero(monkeypatch, tmp_path):
    _estate(monkeypatch, {str(tmp_path): {"usage": _recorded_usage(0.0, 0)}})
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["cost_status"] == "reported"
    assert total["cost_complete"] is True
    assert total["spend"] == 0
    assert total["token_status"] == "reported"
    assert total["tokens"] == 0


def test_rollup_groups_nested_sessions_and_excludes_similar_path_prefixes(monkeypatch, tmp_path):
    project = tmp_path / "project"
    _estate(monkeypatch, {
        str(project): {"usage": _recorded_usage(1.25, 100)},
        str(project / "effort") + "||general||terminal": {
            "usage": _recorded_usage(2.75, 200, cache_read_input_tokens=150)
        },
        str(tmp_path / "project-other"): {"usage": _recorded_usage(99, 9900)},
    })
    rollup = steward_routes._usage_rollup(str(project))
    assert rollup["steward"]["reported_spend"] == 1.25
    assert rollup["terms"]["reported_spend"] == 2.75
    assert rollup["total"]["spend"] == 4
    # tokens is already the recorded total; cache categories must not be added again.
    assert rollup["total"]["tokens"] == 300
    assert rollup["total"]["secs"] == 120
    assert rollup["total"]["token_status"] == "reported"


def test_active_checkpoint_makes_prior_priced_usage_partial(monkeypatch, tmp_path):
    usage = _recorded_usage(
        3.25, 1200,
        completed_cost_complete=True,
        unpriced_inflight=1,
        token_status="partial",
        usage_basis="invocation-checkpoints",
        usage_source="claude stream usage",
        usage_updated_at="2026-09-10T19:20:00Z",
        checkpoint_coverage={
            "tracked_invocations": 2,
            "reported_invocations": 2,
            "partial_invocations": 1,
            "unavailable_invocations": 0,
            "finalized_invocations": 1,
        },
    )
    _estate(monkeypatch, {str(tmp_path): {"usage": usage}})
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["reported_spend"] == 3.25
    assert total["spend"] is None
    assert total["cost_complete"] is False
    assert total["cost_status"] == "partial"
    assert total["unpriced_turns"] == 0
    assert total["tokens"] == 1200
    assert total["token_status"] == "partial"
    assert total["checkpoint_coverage"]["tracked_invocations"] == 2
    assert total["checkpoint_coverage"]["finalized_invocations"] == 1


def test_rollup_keeps_freshest_checkpoint_and_aggregates_coverage(monkeypatch, tmp_path):
    earlier = "2026-09-10T19:10:00Z"
    latest = "2026-09-10T19:25:00Z"
    first = _recorded_usage(
        1, 100,
        usage_updated_at=earlier,
        usage_basis="invocation-checkpoints",
        checkpoint_coverage={
            "tracked_invocations": 1, "reported_invocations": 1,
            "partial_invocations": 0, "unavailable_invocations": 0,
            "finalized_invocations": 1,
        },
    )
    second = _recorded_usage(
        0, 0,
        unpriced_turns=1, cost_complete=False, spend=None,
        token_status="unavailable", usage_updated_at=latest,
        checkpoint_coverage={
            "tracked_invocations": 1, "reported_invocations": 0,
            "partial_invocations": 0, "unavailable_invocations": 1,
            "finalized_invocations": 1,
        },
    )
    _estate(monkeypatch, {
        str(tmp_path): {"usage": first},
        str(tmp_path / "effort") + "||general||terminal": {"usage": second},
    })
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["usage_updated_at"] == latest
    assert total["tokens"] == 100
    assert total["reported_spend"] == 1
    assert total["cost_status"] == "partial"
    assert total["token_status"] == "partial"
    assert total["checkpoint_coverage"] == {
        "tracked_invocations": 2,
        "reported_invocations": 1,
        "partial_invocations": 0,
        "unavailable_invocations": 1,
        "finalized_invocations": 2,
    }
