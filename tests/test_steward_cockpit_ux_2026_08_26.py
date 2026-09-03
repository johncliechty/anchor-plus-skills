"""Cockpit UX round 3 (John's screen review, 2026-08-26).

Five findings, five pins:

1. FILES LOST — the engine persisted ``files`` durably but constructed with an
   empty list, so every restart blanked the pane while the record still held
   them ("you've lost a lot of files").
2. DECISION SHAPE — a decision put to John with no recommendation gets ONE
   engine nudge to re-ask it with context + recommendation + alternatives
   ("that seems to have been lost"). Convention -> mechanism.
3. The nudge is ONE SHOT per question (never a loop) and never fires on tick
   turns, workbench terminals, or turns that DID recommend.
4. The runtime CONTRACT carries the decision shape explicitly — the law lived
   only in SKILL.md, which is not what the live session is handed.
5. The client contract the plan/dialog rely on (single activity line, sticky
   deliverables, two-stage step disclosure) is asserted against the shipped
   static assets so a refactor can't silently drop it.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402


class DecisionShapeTest(unittest.TestCase):
    def test_recommendation_detector(self):
        for txt in ("I recommend we ship it. Spin or ride?",
                    "My recommendation is to wait a day. Go?",
                    "I'd recommend the hotfix now. Yes?",
                    "I suggest we hold. Hold?",
                    "I lean toward the smaller cut. Which?",
                    "Recommendation: publish. Publish?"):
            self.assertTrue(eng._has_recommendation(txt), txt)
        for txt in ("Option A or option B?",
                    "Should I proceed?",
                    "Do you want me to run it now?",
                    ""):
            self.assertFalse(eng._has_recommendation(txt), txt)

    def test_contract_carries_the_attention_flag_rule(self):
        # it lived only in RESUME_BRIEF, so a fresh effort — the DEFAULT path
        # for a new campaign — was never told to stamp the flag, and its
        # background runs read as "waiting on you"
        self.assertIn("ATTENTION FLAG", eng.CONTRACT)
        self.assertIn("attention.json", eng.CONTRACT)

    def test_contract_carries_the_decision_shape(self):
        c = eng.CONTRACT
        self.assertIn("DECISION SHAPE", c)
        for word in ("CONTEXT", "RECOMMEND", "ALTERNATIVES", "QUESTION"):
            self.assertIn(word, c, "the live contract must name " + word)
        # ordering is the point: context before recommendation before question
        self.assertLess(c.index("CONTEXT"), c.index("RECOMMEND"))
        self.assertLess(c.index("RECOMMEND"), c.index("ALTERNATIVES"))
        self.assertLess(c.index("ALTERNATIVES"), c.index("QUESTION"))

    def test_nudge_text_asks_for_the_whole_shape(self):
        src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(
            encoding="utf-8")
        m = re.search(r"You put a decision to John(.{0,900}?)\"\)", src, re.S)
        self.assertIsNotNone(m, "the decision nudge must exist")
        nudge = m.group(0).lower()
        for word in ("context", "recommend", "alternativ", "last line"):
            self.assertIn(word, nudge)

    # The one-shot/loop/false-fire behaviour is pinned BEHAVIOURALLY in
    # tests/test_steward_decision_shape.py — it drives a real Engine through
    # real result events. Grepping the guard expression could not see the
    # loop that two reviewers found, so that assertion is retired rather than
    # updated: a test that cannot fail on the bug is not a test.


class FilesRestoredTest(unittest.TestCase):
    def test_engine_reloads_files_from_the_durable_record(self):
        src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(
            encoding="utf-8")
        self.assertIn('self.files = list(stored_entry.get("files") or [])', src,
                      "files must be RELOADED on construction, not reset to []")
        self.assertNotIn("self.files = []             # files", src)

    def test_state_exposes_the_full_durable_window(self):
        src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(
            encoding="utf-8")
        self.assertIn('"files": self.files[-40:],', src,
                      "the pane gets the durable window, not a 12-line peek")


class ClientContractTest(unittest.TestCase):
    """The plan/dialog rules live in shipped statics — pin them there."""

    def setUp(self):
        self.js = (REPO / "steward_cockpit" / "static" / "shared.js").read_text(
            encoding="utf-8")
        self.css = (REPO / "steward_cockpit" / "static" / "shared.css").read_text(
            encoding="utf-8")

    def test_tool_chatter_is_one_folding_activity_line(self):
        # the old behaviour: a conversation line per tool call
        self.assertNotIn('addLine("tool"', self.js,
                         "per-tool lines must not go back into the dialog")
        self.assertIn("function activity(ev)", self.js)
        self.assertIn("function endActivity(ev)", self.js)
        # it doubles as the running indicator: step count + elapsed
        self.assertIn("working — ", self.js)
        self.assertIn(".blk.act", self.css)
        self.assertIn(".blk.act .actbody { display: none;", self.css)

    def test_activity_timer_is_cleared_on_turn_end(self):
        self.assertIn("clearInterval(actTimer)", self.js,
                      "a live timer must never outlive the turn")

    def test_plan_steps_do_not_auto_open(self):
        self.assertNotIn('if (st.status === "active") li.classList.add("open")',
                         self.js, "the plan must stay scannable; no auto-open")

    def test_step_deliverable_is_one_sentence_then_two_stage(self):
        self.assertIn("function stepDelivLine(it)", self.js)
        self.assertIn("sdone", self.js)      # the one blue sentence
        self.assertIn("sddetail", self.js)   # click 1 -> detail
        # click 2 (the link inside the detail) -> the report itself
        self.assertIn("detail.appendChild(delivRow(it))", self.js)
        # a deliverable click must not also toggle its step
        self.assertIn("ev.stopPropagation()", self.js)
        self.assertIn('ev.target.closest(".sdeliv")', self.js)
        self.assertIn(".sdone { color: var(--steward)", self.css)

    def test_deliverables_have_their_own_slot_above_the_scrollport(self):
        # sticky kept them visible but painted over the status blocks; the
        # tile now lives in its own non-scrolling mount
        v1 = (REPO / "steward_cockpit" / "static" / "v1.html").read_text(
            encoding="utf-8")
        self.assertIn("data-delivmount", v1)
        self.assertIn('$("[data-delivmount]") || paneEl()', self.js)
        self.assertIn(".pdeliv", self.css)

    def test_status_pane_opens_by_default(self):
        # pinning the tile achieved nothing while the whole pane started shut
        v1 = (REPO / "steward_cockpit" / "static" / "v1.html").read_text(
            encoding="utf-8")
        self.assertIn('classList.add("statusopen")', v1)
        self.assertIn("steward_status_pane", v1, "his choice must persist")

    def test_activity_line_survives_its_own_lifecycle(self):
        # the fold click must bind the ELEMENT, not the module slot that
        # endActivity nulls (else a finished line throws or toggles another)
        self.assertIn("head.onclick = () => box.classList.toggle", self.js)
        # a session that ends without turn_end must not leak the timer
        self.assertIn("function resetActivity()", self.js)
        self.assertIn("session ended|asleep", self.js)
        # an epoch reconnect detaches the line with the transcript
        self.assertIn("resetActivity();   // the live line was just detached",
                      self.js)

    def test_plan_keeps_what_the_user_opened(self):
        # paintStepsList rebuilds on every map stamp; without this a click
        # collapsed again within seconds
        self.assertIn("_openSteps", self.js)
        self.assertIn("_openDelivs", self.js)

    def test_no_filler_detail_line(self):
        self.assertNotIn("details to be added", self.js)

    def test_status_is_the_dominant_region(self):
        # 2026-08-27: deliverables + files were uncollapsible blocks that
        # squeezed the status to a sliver. Only the status grows — and it must
        # still be ABLE to shrink, or the bottom section clips out of reach.
        self.assertIn(".rightcol .pscroll { flex: 1 1 auto; min-height: 0;",
                      self.css)
        # a hard floor would push the files section past the bottom of an
        # overflow:hidden column, where it cannot be scrolled to
        self.assertNotIn("min-height: 42vh", self.css)
        self.assertIn(".pfiles.psect { flex: none;", self.css)
        self.assertIn(".pdeliv { flex: none;", self.css)

    def test_both_side_sections_collapse_on_click(self):
        v1 = (REPO / "steward_cockpit" / "static" / "v1.html").read_text(
            encoding="utf-8")
        self.assertIn("data-filestoggle", v1)
        self.assertIn("psect folded", v1, "files start CLOSED")
        self.assertIn(".pfiles.psect.folded .flist { display: none; }", self.css)
        self.assertIn(".pdeliv .blk.deliv.folded .body { max-height: 0;", self.css)
        # each remembers his choice
        self.assertIn("steward_files_open", self.js)
        self.assertIn("steward_deliv_open", self.js)

    def test_folded_deliverables_still_summarise(self):
        self.assertIn("newest: ", self.js,
                      "a closed tile must still say what is in it")

    def test_old_status_replay_cannot_replace_fresh_status(self):
        self.assertIn('const statusId = String(stat.status_id || "")', self.js)
        self.assertIn("statusId <= latestStatusId", self.js)
        self.assertIn("latestStatusId = statusId", self.js)
        guard = self.js.index("statusId <= latestStatusId")
        append = self.js.index("s.appendChild(b)", guard)
        self.assertLess(guard, append)

    def test_held_messages_are_visible_while_the_steward_is_asleep(self):
        self.assertIn('st.queued + " held"', self.js)
        self.assertIn('" held message(s) — waking the steward for delivery"',
                      self.js)


if __name__ == "__main__":
    unittest.main()
