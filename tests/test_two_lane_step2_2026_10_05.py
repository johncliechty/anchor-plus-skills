"""Two-lane step 2 (2026-10-05, Opus): a question waits on him only when the reply ends on it."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import steward_engine as se  # noqa: E402


def test_only_a_reply_that_ends_on_a_question_opens_one():
    src = open(se.__file__, encoding="utf-8").read()
    assert 'sentences = [_all[-1]] if (_all and _all[-1].endswith("?")) else []' in src
