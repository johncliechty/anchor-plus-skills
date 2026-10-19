"""Conversation turns at high, not maximum, effort (his yes, 2026-10-05); workbench terminals and commissioned work keep
their policy."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import steward_engine as se  # noqa: E402


def test_the_cap_lowers_only_what_is_above_it():
    sel = {"family": "chatgpt", "model": "gpt-6.1-sol", "effort": "ultra"}
    out = se._cap_effort(sel, "high")
    assert out["effort"] == "high" and out["effort_cap"] == "ultra" and sel["effort"] == "ultra", "a copy, the original kept"
    assert se._cap_effort({"effort": "medium"}, "high") == {"effort": "medium"}
    assert se._cap_effort(sel, None) is sel and se._cap_effort(sel, "nonsense") is sel


def test_every_selection_path_is_capped_for_a_steward_and_not_for_a_terminal():
    src = open(se.__file__, encoding="utf-8").read()
    assert src.count("_cap_effort(selection, None if self.general else STEWARD_CONVERSATION_EFFORT)") == 3
    assert 'return family, _cap_effort(selection, None if self.general else STEWARD_CONVERSATION_EFFORT)' in src
    assert se.STEWARD_CONVERSATION_EFFORT == (os.environ.get("ANCHOR_STEWARD_EFFORT") or "high").strip().lower()
