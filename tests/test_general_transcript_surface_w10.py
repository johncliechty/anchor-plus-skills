# W10 delta-coverage stub gate — the general-lane session TRANSCRIPT
# persistence surface, re-named in THIS wave's delta.
#
# AUTH-ON: not-a-surface
#
# Same standing situation as the W8/W9 stub gates: the LIVE Anchor service
# keeps appending to its Doctor session's persisted transcript
# (general/dbc27481dbd0-transcript.md) while the build runs, so the churning
# file rides each wave's delta as a flagged persistence surface that is not
# wave work, and delta-coverage credits only IN-WAVE changed tests (Ecgberht
# journal 0070). This wave's gate re-asserts the shape contract.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_general_transcript_surface_w8 import (  # noqa: E402
    OBSERVED_TRANSCRIPT,
    test_general_transcripts_keep_the_persisted_shape_contract,
    test_the_observed_w8_transcript_instance_is_shape_true,
)


def test_w10_delta_names_the_transcript_surface():
    # general/dbc27481dbd0-transcript.md — the observed churning instance.
    assert OBSERVED_TRANSCRIPT == "general/dbc27481dbd0-transcript.md"
    test_general_transcripts_keep_the_persisted_shape_contract()
    test_the_observed_w8_transcript_instance_is_shape_true()
