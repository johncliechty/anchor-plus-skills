"""Deterministic watchdog tests: no sleeps, providers, or child processes."""

import pytest

from steward_cockpit.codex_turn_bridge import TurnTimeout, TurnWatchdog


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_meaningful_progress_allows_active_turn_beyond_fifteen_minutes():
    clock = FakeClock()
    watchdog = TurnWatchdog(7200, 900, clock=clock)
    for _ in range(6):
        clock.advance(899)
        watchdog.progress()
    assert clock.now - 100 > 900
    assert watchdog.remaining() == pytest.approx(900)


def test_silence_expires_at_exact_idle_boundary_with_clear_details():
    clock = FakeClock()
    watchdog = TurnWatchdog(7200, 900, clock=clock, provider_label="Grok")
    clock.advance(899.5)
    assert watchdog.remaining() == pytest.approx(0.5)
    clock.advance(0.5)
    with pytest.raises(TurnTimeout) as caught:
        watchdog.remaining()
    assert caught.value.kind == "inactivity"
    assert caught.value.elapsed == caught.value.idle == 900
    assert "Grok" in str(caught.value)
    assert "inactivity" in str(caught.value)
    assert "elapsed 900.0s; idle 900.0s" in str(caught.value)


def test_late_progress_cannot_revive_expired_watchdog_even_after_clock_rollback():
    clock = FakeClock()
    watchdog = TurnWatchdog(7200, 900, clock=clock)
    clock.advance(900)
    with pytest.raises(TurnTimeout, match="inactivity"):
        watchdog.progress()
    clock.now = 100.0
    with pytest.raises(TurnTimeout, match="inactivity"):
        watchdog.progress()
    with pytest.raises(TurnTimeout, match="inactivity"):
        watchdog.remaining()


def test_continuous_progress_cannot_extend_absolute_ceiling():
    clock = FakeClock()
    watchdog = TurnWatchdog(7200, 900, clock=clock)
    for _ in range(8):
        clock.advance(800)
        watchdog.progress()
    clock.advance(799.5)
    assert watchdog.remaining() == pytest.approx(0.5)
    clock.advance(0.5)
    with pytest.raises(TurnTimeout) as caught:
        watchdog.progress()
    assert caught.value.kind == "wall_limit"
    assert caught.value.elapsed == 7200
    assert caught.value.idle == 800


def test_explicit_short_wall_limit_wins_over_longer_idle_limit():
    clock = FakeClock()
    watchdog = TurnWatchdog(300, 900, clock=clock)
    assert watchdog.remaining() == 300
    clock.advance(200)
    watchdog.progress()
    assert watchdog.remaining() == 100
    clock.advance(100)
    with pytest.raises(TurnTimeout) as caught:
        watchdog.remaining()
    assert caught.value.kind == "wall_limit"
    assert caught.value.idle == 100


def test_simultaneous_deadlines_report_wall_limit():
    clock = FakeClock()
    watchdog = TurnWatchdog(900, 900, clock=clock)
    clock.advance(900)
    with pytest.raises(TurnTimeout) as caught:
        watchdog.remaining()
    assert caught.value.kind == "wall_limit"


@pytest.mark.parametrize("invalid", [0, -1, 43201, 10**1000, float("nan"), float("inf"), -float("inf"), True, False, "900", None])
@pytest.mark.parametrize("field", ["wall_seconds", "idle_seconds"])
def test_invalid_duration_is_rejected_before_starting_clock(invalid, field):
    arguments = {"wall_seconds": 7200, "idle_seconds": 900}
    arguments[field] = invalid

    def forbidden_clock():
        raise AssertionError("Invalid configuration must not start the clock")

    with pytest.raises(ValueError, match=field):
        TurnWatchdog(**arguments, clock=forbidden_clock)


def test_finite_positive_fraction_and_maximum_are_accepted():
    clock = FakeClock()
    watchdog = TurnWatchdog(43200, 0.25, clock=clock)
    assert watchdog.remaining() == 0.25
    clock.advance(0.125)
    watchdog.progress()
    assert watchdog.remaining() == 0.25
