"""The speaking boundaries — Anchor's mirror of the engine's list (Ecgberht ``engine/boundaries.mjs``).

W0 of the steward revision (2026-09-28). The named moments at which the steward may speak unprompted on the High
Seat; a moment not on the list is not a boundary — the steward prepares and waits. Kept identical to the engine's
list by ``tests/test_boundaries_2026_09_28.py`` (which parses the engine file when it is on this host). Nothing
reads it yet except the tests; W2 (the head) and W3 (the after rule) read it.
"""

SPEAKING_BOUNDARIES = (
    "page_open",       # he opens the High Seat
    "card_open",       # he opens a project's card on the High Seat
    "turn_submitted",  # he submits a turn to the steward
    "step_closed",     # a step closes on the record (an acceptance, a done)
    "run_finished",    # a commissioned run he launched has finished
)

SPEAKING_BOUNDARIES_VERSION = 1


def is_speaking_boundary(moment) -> bool:
    """True when ``moment`` is one of the named boundaries (an exact compare)."""
    return isinstance(moment, str) and moment in SPEAKING_BOUNDARIES
