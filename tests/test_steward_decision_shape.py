"""Decision-shape nudge — BEHAVIORAL pins (2026-08-26).

The first version of these tests grepped the source for guard strings. Two
independent reviewers pointed out that a grep cannot see a loop: the nudge
keyed on the question STRING, and since the nudge's own re-ask rewords the
question, it could fire turn after turn — each one billed and invisible.
These tests drive a real Engine through real ``result`` events instead.

Pinned behaviour:
  * a decision turn with no recommendation is nudged EXACTLY once;
  * the re-ask does NOT nudge again, however it is worded (the loop);
  * a human message opens a new decision cycle;
  * a turn that DID recommend is never nudged;
  * a leftover pin (restored on boot / after a plain answer) never nudges —
    only a question THIS turn asked;
  * a queued human message suppresses the nudge (his words supersede);
  * tick turns and workbench terminals never nudge.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402


class _FakeProc:
    """Stands in for the CLI subprocess: alive, and records what was sent."""

    def __init__(self):
        self.sent = []

    def poll(self):
        return None


class DecisionNudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-decision-")
        self._old_state = eng.STATE_FILE
        eng.STATE_FILE = Path(self.tmp) / "state.json"
        self.e = eng.Engine(self.tmp, fake=True)
        self.proc = _FakeProc()
        self.e.proc = self.proc
        self.sent = []
        # capture machine sends without touching a real stdin
        self.e._send_locked = lambda text: (self.sent.append(text), True)[1]

    def tearDown(self):
        eng.STATE_FILE = self._old_state

    def _turn(self, text, tick=False):
        """Drive one model turn through the engine's own result handler."""
        self.e.turn_text = text
        self.e.in_tick = tick
        self.e._handle({"type": "result", "total_cost_usd": 0.0,
                        "duration_ms": 1000, "usage": {}}, self.proc)

    def _nudges(self):
        return [s for s in self.sent if "without a recommendation" in s]

    # ── the core one-shot ────────────────────────────────────────────────
    def test_decision_without_recommendation_is_nudged_once(self):
        self._turn("The register is half checked. Should we ship?")
        self.assertEqual(len(self._nudges()), 1)

    def test_reask_does_not_nudge_again_however_worded(self):
        """THE LOOP: the nudge tells the model to re-ask, which rewords the
        question. Keyed on the question string, that re-armed the guard."""
        self._turn("The register is half checked. Should we ship?")
        self.assertEqual(len(self._nudges()), 1)
        # the re-ask: different wording, still no recommendation phrase
        self._turn("Ship now, or hold until the rows are confirmed?")
        self.assertEqual(len(self._nudges()), 1, "nudged twice — this loops")
        self._turn("So: ship, or wait?")
        self.assertEqual(len(self._nudges()), 1, "nudged again — this loops")

    def test_human_message_opens_a_new_decision_cycle(self):
        self._turn("Half checked. Should we ship?")
        self.assertEqual(len(self._nudges()), 1)
        self.e.say("hold for now", human=True)
        self._turn("New question, still bare. Publish it?")
        self.assertEqual(len(self._nudges()), 2)

    # ── the false-fire guards ────────────────────────────────────────────
    def test_turn_with_a_recommendation_is_never_nudged(self):
        self._turn("Two rows are unconfirmed. I recommend we ship and fix "
                   "them next week; the alternative is a day's delay. Ship?")
        self.assertEqual(self._nudges(), [])

    def test_leftover_pin_after_a_plain_answer_does_not_nudge(self):
        """open_question survives a boot and a prose answer. Keying on it
        nudged the steward for a decision it had just answered."""
        self.e.open_question = "Should we ship?"      # as if restored on boot
        self._turn("Yes — the numbers hold and the run finished cleanly.")
        self.assertEqual(self._nudges(), [],
                         "a turn that asked nothing must not be nudged")

    def test_queued_human_message_suppresses_the_nudge(self):
        """John already spoke; his words supersede the decision. Nudging here
        also jumped the queue — his reply waited behind a machine retry."""
        self.e.queue.append("go ahead and ship it")
        self._turn("Half checked. Should we ship?")
        self.assertEqual(self._nudges(), [])

    def test_tick_turns_never_nudge(self):
        self._turn("HOLD. Anything else?", tick=True)
        self.assertEqual(self._nudges(), [])

    def test_workbench_terminal_never_nudges(self):
        self.e.general = True
        self._turn("Which file did you mean?")
        self.assertEqual(self._nudges(), [])

    # ── the nudge is visible, not a silent billed turn ───────────────────
    def test_nudge_emits_a_visible_line(self):
        self._turn("Half checked. Should we ship?")
        texts = " | ".join(e.get("text", "") for e in self.e.events)
        self.assertIn("decision shape", texts,
                      "a billed machine turn must be visible, like drive")


class DeliveryReceiptTest(unittest.TestCase):
    """The receipt path raised NameError on every call for a full release —
    swallowed by the callers' except-blocks, so it reported success while
    writing nothing. Pin the write, not just the return value."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-receipt-")

    def test_status_ack_actually_writes_the_receipt(self):
        e = eng.Engine.__new__(eng.Engine)
        e.dir = self.tmp
        res = e.record_status_ack("2026-08-26 10:00")
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(res.get("channel_verified_first_time"))
        import json
        f = Path(self.tmp) / ".ecgberht" / "delivery.json"
        self.assertTrue(f.is_file(), "delivery.json was never written")
        d = json.loads(f.read_text(encoding="utf-8"))
        self.assertTrue(d["channel_verified"])
        self.assertEqual(d["render_acks"], 1)
        # second ack increments and does not re-flip the first-time marker
        res2 = e.record_status_ack("2026-08-26 10:10")
        self.assertFalse(res2["channel_verified_first_time"])
        d2 = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(d2["render_acks"], 2)


class RecommendationDetectorTest(unittest.TestCase):
    def test_real_recommendations(self):
        for t in ("I recommend we ship it. Go?",
                  "My recommendation is to wait. Go?",
                  "I'd recommend the hotfix. Yes?",
                  "I suggest we hold. Hold?",
                  "I lean toward the smaller cut. Which?"):
            self.assertTrue(eng._has_recommendation(t), t)

    def test_false_positives_that_would_disable_the_check(self):
        """A false POSITIVE silently turns the check off — the expensive
        direction. These all read as recommendations to a loose regex."""
        for t in ("That is not my call — it is yours. Which do you want?",
                  "We did it as recommended by the plan. Ship?",
                  "I lean on the existing tests for this. Ship?",
                  "The recommended flow failed twice. Revert?"):
            self.assertFalse(eng._has_recommendation(t), t)

    def test_only_the_tail_counts(self):
        """A recommendation buried in a long working narrative is not a
        recommendation about the question asked at the end."""
        buried = "I recommend the blue one. " + ("working. " * 400) + "Now what?"
        self.assertFalse(eng._has_recommendation(buried))


if __name__ == "__main__":
    unittest.main()
