"""John 2026-10-12: plans and reports open in plain words, and the finish stays light (Book 1 v2, calc history plan)."""
from steward_cockpit import steward_engine as se


def test_every_duty_tells_the_steward_to_write_for_john():
    for duty in (se.SMALL_DUTY, se.EFFORT_DUTY):
        assert "WRITE FOR JOHN" in duty and "plain sentences a non-programmer follows" in duty
    assert "Show John the plan in plain words" in se.SIZE_OR_HOLD


def test_every_duty_says_to_end_the_turn_once_a_job_is_started():
    for duty in (se.SMALL_DUTY, se.EFFORT_DUTY):
        assert "ONCE A JOB OR SKILL IS STARTED, END YOUR TURN" in duty and "Never sleep, poll or watch" in duty


def test_the_finish_is_kept_light():
    # round 4 (2026-10-12): only receipts that repeat what Anchor already records are dropped
    assert "never require receipt, hash, manifest, provenance or delivery-check files" in se.WRITE_FOR_JOHN
    assert "keep evidence the work itself or John's rules" in se.WRITE_FOR_JOHN
