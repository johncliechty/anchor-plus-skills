"""Two-lane step 1 (2026-10-05, Grok + Opus): words he sees within a minute, the cap in effort mode too, and no
checkpoint of a tree a stopped turn left half-written."""
import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from steward_cockpit import steward_engine as se  # noqa: E402


def _eng(**kw):
    out = []
    e = SimpleNamespace(busy=True, turn_started=100.0, turn_text="", steward="Aladdin", _timing={"first_word": None},
                        _last_submitted="put the borders on", **kw)
    e._emit = out.append
    e._turn_activity = lambda: se.Engine._turn_activity(e)
    return e, out


def test_the_early_receipt_speaks_once_only_while_nothing_was_said():
    e, out = _eng()
    se.Engine._early_receipt(e, 100.0)
    assert out and out[0]["receipt"] is True and out[0]["text"].startswith("Aladdin is on it")
    e2, out2 = _eng(); e2.turn_text = "Done."
    se.Engine._early_receipt(e2, 100.0)
    e3, out3 = _eng(); se.Engine._early_receipt(e3, 99.0)   # another turn by now
    assert out2 == [] and out3 == []


def test_the_cap_is_a_progress_line_in_every_mode_and_never_a_hand_off():
    # 2026-10-07 (execution minimum item 4): the cap no longer ends a turn or names a worker to hand it to; it says
    # one progress line, in small mode and in an effort alike
    src = open(se.__file__, encoding="utf-8").read()
    assert "self._turn_tools == STEP_CAP" in src and "self._turn_tools > STEP_CAP and not self.effort_on()" not in src
    assert "Commission it now" not in src and "Do not finish the work inline" not in src
    assert se.RECEIPT_AFTER_S == float(os.environ.get("STEWARD_RECEIPT_AFTER_S", "20"))


def test_no_checkpoint_after_a_stopped_turn():
    e = SimpleNamespace(_stopped_mid_turn=True, dir=HERE)
    assert se.Engine._commit_if_dirty(e, "x") is None
