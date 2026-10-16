# W9 delta-coverage stub gate — the general-lane session TRANSCRIPT
# persistence surface, re-named in THIS wave's delta.
#
# AUTH-ON: not-a-surface
#
# The LIVE Anchor service keeps appending to its Doctor session's persisted
# transcript (general/dbc27481dbd0-transcript.md) while the steward-chamber
# build runs, so the file rides EVERY wave's delta as a churning persistence
# surface that is not wave work (see the W8 stub gate + Ecgberht journal
# 0070's credit-scope lesson: delta-coverage only credits IN-WAVE changed
# tests, so the surface must be re-named per wave while the churn lasts).
# This wave's stub gate re-asserts the same shape contract via the W8 suite.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_general_transcript_surface_w8 import (  # noqa: E402
    OBSERVED_TRANSCRIPT,
    test_general_transcripts_keep_the_persisted_shape_contract,
    test_the_observed_w8_transcript_instance_is_shape_true,
)


def test_w9_delta_names_the_transcript_surface():
    # general/dbc27481dbd0-transcript.md — the observed churning instance.
    assert OBSERVED_TRANSCRIPT == "general/dbc27481dbd0-transcript.md"
    test_general_transcripts_keep_the_persisted_shape_contract()
    test_the_observed_w8_transcript_instance_is_shape_true()
