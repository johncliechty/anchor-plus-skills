"""W5 of the active set - one conversation (John, 2026-10-01 13:3x: "is there some type of reset for the steward
conversation in Cave of Wonders and Campaign? That should not be the case"; his call at 18:5x: both - stay awake AND wake
silently).

What read as a reset: the Campaign's steward parked itself after thirty quiet minutes; the wake (his next message, or any
restart) put six system lines into the dialogue ("steward awake - resuming the last session", "Last time: ...", "Plan:",
"Goal:", "Open:") and the resume brief asked the model for a pickup - a recap as its first words. Now the Campaign's own
steward holds one conversation: it takes its idle checkpoint and stays awake; its wake emits nothing and asks for no
pickup. Every other cockpit keeps its sleep and its wake summary (his word of 2026-08-25)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import campaign_say  # noqa: E402
from steward_cockpit import steward_engine as eng_mod  # noqa: E402
from steward_cockpit import steward_routes as routes  # noqa: E402

GREETING = ("resuming the last session", "Last time:", "Plan:", "Goal:", "Open:")


class OneConversationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-w5-")
        self.camp = os.path.join(self.tmp, "Campaign")
        self.other = os.path.join(self.tmp, "effort")
        for d in (self.camp, self.other):
            os.makedirs(d)
            Path(d, "ECGBERHT.md").write_text("# face", encoding="utf-8")
        self._old = (eng_mod.STATE_FILE, routes.CONFIG.get("fake"), campaign_say.campaign_dir, eng_mod.IDLE_SLEEP_SECONDS)
        eng_mod.STATE_FILE = Path(self.tmp) / "state.json"
        routes.CONFIG["fake"] = True
        campaign_say.campaign_dir = lambda: Path(self.camp).resolve()
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            try:
                e.stop()
            except Exception:
                pass
        eng_mod.STATE_FILE, routes.CONFIG["fake"], campaign_say.campaign_dir, eng_mod.IDLE_SLEEP_SECONDS = self._old

    def _parked(self, cdir):
        eng_mod._update_state(cdir, {"session_id": "fake-parked-1", "last_text": "the trusts meeting is set", "last_used": "2026-10-01 12:28"})
        e = eng_mod.Engine(cdir, fake=True)
        self.engines.append(e)
        return e

    def test_only_the_campaign_s_own_steward_holds_one_conversation(self):
        self.assertTrue(eng_mod.Engine(self.camp, fake=True).one_conversation)
        self.assertFalse(eng_mod.Engine(self.other, fake=True).one_conversation)
        self.assertFalse(eng_mod.Engine(self.camp, fake=True, general=True, tid=1).one_conversation, "a workbench terminal in the Campaign folder is not the steward")

    def test_its_wake_puts_no_greeting_in_the_dialogue_and_asks_for_no_pickup(self):
        e = self._parked(self.camp)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        said = " | ".join(str(ev.get("text", "")) for ev in e.events)
        for line in GREETING:
            self.assertNotIn(line, said)
        self.assertEqual(e._resume_prefix, eng_mod.RESUME_QUIET)

    def test_a_question_that_waits_on_him_stays_on_the_page_and_nothing_else_is_said(self):
        """Grok W5: Last time / Plan / Goal and the awake line are the reset; Open is his unanswered question."""
        eng_mod._update_state(self.camp, {"open_question": "Which date works for the attorney?"})
        e = self._parked(self.camp)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        said = [str(ev.get("text", "")) for ev in e.events if ev.get("t") == "sys"]
        self.assertIn("Open: waiting on you: Which date works for the attorney?", said)
        for line in ("resuming the last session", "Last time:", "Plan:", "Goal:"):
            self.assertNotIn(line, " | ".join(said))

    def test_what_reaches_the_model_with_his_first_words_after_a_wake(self):
        """Grok W5: the joiner sat closer to his words than the brief and still ordered a pickup. The bytes written to
        the steward's stdin are the pin, for the Campaign and for a cockpit."""
        import json

        class Pipe:
            def __init__(self):
                self.lines = []

            def write(self, s):
                self.lines.append(s)

            def flush(self):
                pass

            def close(self):
                pass

        for cdir, quiet in ((self.camp, True), (self.other, False)):
            e = self._parked(cdir)
            ok, why = e.wake()
            self.assertTrue(ok, why)
            real, pipe = e.proc.stdin, Pipe()
            e.proc.stdin = pipe
            try:
                with e._lock:
                    self.assertTrue(e._send_locked("what is next on the trusts?", origin="human"))
            finally:
                e.proc.stdin = real
            text = json.loads(pipe.lines[0])["message"]["content"][0]["text"]
            self.assertIn("what is next on the trusts?", text)
            if quiet:
                self.assertTrue(text.startswith(eng_mod.RESUME_QUIET + eng_mod.JOIN_QUIET))
                self.assertIn("JOHN SAYS (answer this as the next turn of the conversation):", text)
                for ask in ("give the short pickup first", "give John a SHORT pickup", "give a brief pickup", "restate it as the LAST line"):
                    self.assertNotIn(ask, text)
            else:
                self.assertTrue(text.startswith(eng_mod.RESUME_BRIEF + eng_mod.JOIN_PICKUP))
            self.assertIsNone(e._resume_prefix, "said once")

    def test_another_cockpit_keeps_its_wake_summary(self):
        e = self._parked(self.other)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        said = " | ".join(str(ev.get("text", "")) for ev in e.events)
        for line in GREETING:
            self.assertIn(line, said)
        self.assertTrue(str(e._resume_prefix).startswith(eng_mod.RESUME_BRIEF))

    def test_the_quiet_brief_rereads_the_record_and_answers_as_the_next_turn(self):
        q, b = eng_mod.RESUME_QUIET, eng_mod.RESUME_BRIEF
        self.assertIn("give John a SHORT pickup", b)
        self.assertNotIn("give John a SHORT pickup", q)
        self.assertNotIn("give a brief pickup", q)
        self.assertNotIn("LAST line", q)
        self.assertIn("no pickup, no recap, no re-introduction, and never re-ask what the record answers. Continue agreed work", q)
        self.assertEqual(b, "(engine resume - not John) You are Ecgberht, waking from a parked session. " + eng_mod._RESUME_REREAD + eng_mod._RESUME_PICKUP_ASK + eng_mod.RESUME_CONTINUITY + eng_mod._RESUME_ATTENTION)
        for kept in ("Silently re-read ECGBERHT.md, roadmap.json, strip.json", ".ecgberht/conversation-log.json", "Continue agreed work under explicit, still-current authorization", "ATTENTION FLAG"):
            self.assertIn(kept, q)

    def test_a_quiet_half_hour_parks_a_cockpit_and_not_the_campaign(self):
        eng_mod.IDLE_SLEEP_SECONDS = 60
        for cdir, parks in ((self.other, True), (self.camp, False)):
            e = self._parked(cdir)
            ok, why = e.wake()
            self.assertTrue(ok, why)
            commits = []
            e._commit_if_dirty = lambda msg, _c=commits: _c.append(msg)
            leaves = []
            from steward_cockpit import presence as _pres
            _old_leave, _pres.leave_if_still_here = _pres.leave_if_still_here, lambda d, fn, _l=leaves: _l.append(d)
            self.addCleanup(setattr, _pres, "leave_if_still_here", _old_leave)
            now = e.woke_at + 30
            self.assertFalse(e._idle_tick(now), "not quiet long enough")
            self.assertTrue(e.alive() and not commits)
            now = e.woke_at + 61
            self.assertEqual(e._idle_tick(now), parks)
            self.assertEqual(e.alive(), not parks)
            if parks:
                self.assertEqual(commits[0], "steward auto-sleep checkpoint")
                self.assertEqual(leaves, [cdir], "a cockpit that parks records the fallback leave")
                self.assertIn("steward asleep after 1 quiet minutes", " | ".join(str(ev.get("text", "")) for ev in e.events))
                continue
            self.assertEqual(commits, ["steward idle checkpoint"])
            self.assertEqual(leaves, [], "a steward that stays up records no leave against an open conversation (Grok W5)")
            self.assertFalse(e._idle_tick(now + 300) or e._idle_tick(now + 3000))
            self.assertEqual(len(commits), 1, "once per quiet spell")
            e.last_say = now + 3000                       # he speaks; a new quiet spell begins
            self.assertFalse(e._idle_tick(now + 3030))
            self.assertFalse(e._idle_tick(now + 3100))
            self.assertEqual(len(commits), 2)
            self.assertNotIn("steward asleep", " | ".join(str(ev.get("text", "")) for ev in e.events))
            self.assertTrue(e.alive())

    def test_work_in_hand_is_never_an_idle_spell(self):
        eng_mod.IDLE_SLEEP_SECONDS = 60
        e = self._parked(self.other)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        e.busy = True
        self.assertFalse(e._idle_tick(e.woke_at + 600))
        e.busy = False
        e._working_bg = lambda: True
        self.assertFalse(e._idle_tick(e.woke_at + 600))
        self.assertTrue(e.alive())


if __name__ == "__main__":
    unittest.main()
