"""Pure prompt canaries for authorized work surviving a session/provider pickup."""

import inspect

import pytest

import anchor_settings
from steward_cockpit import steward_engine
from steward_cockpit.conversation_history import append_turn


def test_resume_brief_reads_complete_history_and_uses_shared_continuity():
    brief = steward_engine.RESUME_BRIEF

    assert "complete durable history in .ecgberht/conversation-log.json" in brief
    assert "the tail of .ecgberht/conversation-log.json" not in brief
    assert steward_engine.RESUME_CONTINUITY in brief


def test_session_change_does_not_cancel_outstanding_explicit_authorization():
    continuity = steward_engine.RESUME_CONTINUITY

    assert "explicit, still-current authorization" in continuity
    assert "across session or provider changes" in continuity
    assert "do not require renewed approval solely for the pickup" in continuity
    assert "Existing authorization does not expand scope" in continuity


def test_continuity_preserves_real_gates_without_blocking_independent_work():
    continuity = steward_engine.RESUME_CONTINUITY

    assert "Honor later pauses, unresolved decisions, scope limits, and budgets" in continuity
    assert "permissions, or required inputs that genuinely block the next action" in continuity
    assert "optional later materials do not block independent authorized work" in continuity
    assert "Do not replay completed actions" in continuity
    assert "verify uncertain action outcomes before repeating them" in continuity
    assert "If no outstanding authorized task exists, ask John what to do next" in continuity
    assert "do not invent work or treat the pickup as a new effort" in continuity


def test_both_existing_history_wake_paths_use_the_same_continuity_instruction():
    wake_source = inspect.getsource(steward_engine.Engine._wake_locked)

    assert "seed = history_reference + RESUME_CONTINUITY" in wake_source
    assert "initial_prompt = history_reference + RESUME_CONTINUITY" in wake_source
    assert "Do not begin work until John continues." not in wake_source
    assert "Give a brief pickup, then wait for John." not in wake_source


@pytest.mark.parametrize(
    "obsolete_gate",
    [
        "READ-BACK GATE (campaign journal 0008)",
        "a bare token across a session boundary is never an approval by itself",
        "Do not start any work until he speaks",
    ],
)
def test_resume_brief_has_no_blanket_session_boundary_reapproval_gate(obsolete_gate):
    assert obsolete_gate not in steward_engine.RESUME_BRIEF


def test_real_history_reference_preserves_authorization_and_action_safety(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(
        anchor_settings,
        "load_settings",
        lambda: {
            "default_cli": "chatgpt",
            "coding_family": "chatgpt",
            "review_family": "grok",
            "settings_revision": 1,
            "model_policy": {
                "mode": "latest_supported",
                "effort": "highest_supported",
            },
        },
    )
    instruction = (
        "Continue the agreed synthetic project within its existing budget.\n" * 100
    ) + "Retain this final dictated requirement exactly."
    append_turn(tmp_path, "john", instruction)
    history_path = tmp_path / ".ecgberht" / "conversation-log.json"
    history_before = history_path.read_bytes()
    engine = steward_engine.Engine(str(tmp_path), fake=True, general=False, tid=None)
    engine.fake = False

    reference = engine._history_reference()

    assert ".ecgberht/conversation-log.json" in reference.replace("\\", "/")
    assert "read the complete durable history" in reference.lower()
    assert "Explicit, still-current authorization for outstanding agreed work remains valid" in reference
    assert "across session or provider changes" in reference
    assert "does not create new approval or expand scope" in reference
    assert "Honor later pauses, unresolved decisions, scope limits, and budgets" in reference
    assert "do not replay completed actions" in reference
    assert "verify uncertain action outcomes before repeating them" in reference
    assert "treat historical approvals as new approvals" not in reference
    assert instruction not in reference
    assert history_path.read_bytes() == history_before
