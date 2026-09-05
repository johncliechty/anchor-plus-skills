"""(John, 2026-09-04) "if a session limit is hit by one of the models, then Anchor
needs to inform the user, not just stop."

A commissioned run's stop (its own status log) is said as STOPPED with the
reason — a model session limit first — in the status pane's Doing/Blocker rows,
the top bar and the dashboard row; a flag still saying "working" is flipped to
needs_you so the High Seat says "need you"; the steward's own error result is
said in the pane and raises the flag when it is a limit."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402
from steward_cockpit import steward_engine as engine  # noqa: E402

LIMIT_LOG = """[18:11:15] [18:11] Foreman build · literature-review · final
---------------------------------
Effort   IMPLEMENTATION-PLAN.md (5 waves)
Doing    wave 1 · fix (iter 0) · wave 1 at fix
Status   0/5 waves · elapsed 4m
Tests    last verdict HALT
Blocker  [taxonomy:agent-died] execute for wave 1 died: You've hit your usage limit · resets at 7pm (America/Denver)
Procs    agent_calls 1 · est $3.41 (subscription equiv)
---------------------------------
ETA      estimating (no completed wave yet)
To do    waves 1..5
[18:11:15] === DONE === status=HALT · waves=1:HALT
[18:11:15] HALT/STOP reason: [taxonomy:agent-died] HALT: the execute agent died: You've hit your usage limit · resets at 7pm (America/Denver)
"""

PLAIN_HALT_LOG = LIMIT_LOG.replace("You've hit your usage limit · resets at 7pm (America/Denver)",
                                   "class error-result after 19 tool calls")


def _campaign(td, log_text, attention="working"):
    root = Path(td)
    (root / "ECGBERHT.md").write_text("# E\n\n## North Star\nA thing.\n", encoding="utf-8")
    (root / "roadmap.json").write_text(json.dumps({"roadmap_projection": [
        {"id": "s1", "name": "Build it", "status": "active", "part": "slice",
         "commissioned_as": "Foreman", "done_when": "green"}]}), encoding="utf-8")
    (root / "strip.json").write_text(json.dumps({"human_wait": "", "next_recommended": "carry on"}),
                                     encoding="utf-8")
    (root / ".ecgberht").mkdir()
    (root / ".ecgberht" / "attention.json").write_text(
        json.dumps({"state": attention, "reason": "Foreman building wave 1"}), encoding="utf-8")
    (root / "_foreman-status.log").write_text(log_text, encoding="utf-8")
    return root


class LimitIsToldTest(unittest.TestCase):
    def test_classify_model_limit(self):
        self.assertTrue(campaign.classify_model_limit("You've hit your usage limit. Resets at 7pm"))
        self.assertTrue(campaign.classify_model_limit("HTTP 429 too many requests"))
        self.assertTrue(campaign.classify_model_limit("rate-limited by the API"))
        self.assertEqual(campaign.classify_model_limit("class error-result after 19 tools"), "")

    def test_a_halted_run_with_a_limit_is_said_as_stopped_and_waiting_on_him(self):
        td = tempfile.mkdtemp(prefix="stw-limit-")
        _campaign(td, LIMIT_LOG)
        st = campaign.compose_status(td, {"busy": False})
        self.assertEqual(st["running"]["kind"], "halted")
        self.assertIn("STOPPED", st["running"]["label"])
        self.assertIn("model session limit", st["running"]["label"])
        self.assertEqual(st["now"][0], st["running"]["label"])
        self.assertTrue(st["halt"]["limit"])
        self.assertIn("usage limit", st["halt"]["reason"])
        self.assertIn("model session limit", st["plan"]["waiting_on_you"])
        self.assertIn("resets at 7pm", st["plan"]["waiting_on_you"])

    def test_a_plain_halt_is_said_as_stopped_with_its_reason(self):
        td = tempfile.mkdtemp(prefix="stw-halt-")
        _campaign(td, PLAIN_HALT_LOG)
        st = campaign.compose_status(td, {"busy": False})
        self.assertEqual(st["running"]["kind"], "halted")
        self.assertEqual(st["halt"]["limit"], "")
        self.assertIn("Foreman build stopped:", st["plan"]["waiting_on_you"])
        self.assertIn("error-result", st["plan"]["waiting_on_you"])

    def test_the_engine_flips_a_working_flag_to_needs_you(self):
        td = tempfile.mkdtemp(prefix="stw-flag-")
        _campaign(td, LIMIT_LOG, attention="working")
        st = campaign.compose_status(td, {"busy": False})
        flipped = campaign.raise_halt_attention(td, st)
        self.assertEqual(flipped["state"], "needs_you")
        self.assertEqual(flipped["failure_code"], "MODEL_LIMIT")
        self.assertIn("usage limit", flipped["reason"])
        again = json.loads((Path(td) / ".ecgberht" / "attention.json").read_text(encoding="utf-8"))
        self.assertEqual(again["state"], "needs_you")
        # already off "working" → nothing to flip; no halt → nothing to flip
        self.assertIsNone(campaign.raise_halt_attention(td, st))
        td2 = tempfile.mkdtemp(prefix="stw-noflag-")
        _campaign(td2, "", attention="working")
        self.assertIsNone(campaign.raise_halt_attention(td2, campaign.compose_status(td2, {})))
        self.assertEqual(campaign.read_map(td2)["attention"]["state"], "working")

    def test_the_stewards_own_error_result_is_said(self):
        ev = {"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": "You've hit your usage limit. Your limit resets at 7pm (America/Denver)."}
        txt = engine.result_error_text(ev)
        self.assertIn("usage limit", txt)
        self.assertTrue(campaign.classify_model_limit(txt))
        self.assertEqual(engine.result_error_text({"type": "result", "is_error": False,
                                                   "result": "fine"}), "")
        self.assertEqual(engine.result_error_text({"type": "result", "subtype": "error_max_turns"}),
                         "error_max_turns")
        src = (Path(__file__).resolve().parent.parent / "steward_cockpit" / "steward_engine.py"
               ).read_text(encoding="utf-8")
        self.assertIn('"MODEL LIMIT: "', src)
        self.assertIn('failure_code="MODEL_LIMIT"', src)
        self.assertIn("campaign.raise_halt_attention(self.dir, status)", src)
        self.assertIn('"STOPPED: " + flipped["reason"]', src)


if __name__ == "__main__":
    unittest.main()
