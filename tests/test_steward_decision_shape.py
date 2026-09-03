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

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def test_go_does_not_clear_a_real_question(self):
        """2026-08-25: Go armed drive AND wiped a question he had not answered."""
        self.e.open_question = "Ship now, or hold?"
        result = self.e.say("go")
        self.assertTrue(self.e.drive)
        self.assertEqual(self.e.open_question, "Ship now, or hold?")
        self.assertTrue(result["control_only"])
        self.assertEqual(self.sent, [], "bare Go reached model stdin as approval")

    def test_go_answers_a_drive_offer(self):
        self.e.open_question = "Shall I drive?"
        self.e.say("go")
        self.assertTrue(self.e.drive)
        self.assertEqual(self.e.open_question, "")
        self.assertEqual(self.sent, ["go"])

    def test_pause_does_not_answer_a_real_question(self):
        self.e.drive = True
        self.e.open_question = "Ship now, or hold?"
        result = self.e.say("pause")
        self.assertFalse(self.e.drive)
        self.assertEqual(self.e.open_question, "Ship now, or hold?")
        self.assertTrue(result["control_only"])
        self.assertEqual(self.sent, [])

    def test_control_prefixes_are_substantive_answers(self):
        self.e.open_question = "Which option should we use?"
        self.e.say("go with option B")
        self.assertFalse(self.e.drive)
        self.assertEqual(self.e.open_question, "")
        self.assertEqual(self.sent, ["go with option B"])

        self.e.open_question = "Should we stop?"
        self.e.say("hold on")
        self.assertEqual(self.e.open_question, "")
        self.assertEqual(self.sent[-1], "hold on")

    def test_continue_words_do_not_turn_a_decision_into_drive_offer(self):
        self.e.open_question = "Should we continue without asking legal review?"
        result = self.e.say("go")
        self.assertTrue(result["control_only"])
        self.assertEqual(
            self.e.open_question,
            "Should we continue without asking legal review?",
        )
        self.assertEqual(self.sent, [])

    def test_pickup_is_always_four_orientation_lines(self):
        self.e.open_question = "Ship now, or hold?"
        seen = []
        self.e._emit = lambda ev: seen.append(ev.get("text", ""))
        self.e._emit_resume_pickup({"last_text": "The register is half done.",
                                    "last_used": "2026-08-25 12:00"})
        joined = " | ".join(seen)
        self.assertIn("Last time:", joined)
        self.assertIn("Plan:", joined)
        self.assertIn("Goal:", joined)
        self.assertIn("Open: waiting on you: Ship now, or hold?", joined)

    def test_persisted_last_outcome_keeps_the_conclusion(self):
        self._turn("BEGIN " + ("middle " * 80) + "UNIQUE CONCLUSION")
        entry = eng._read_state_entry(self.e.skey())
        self.assertNotIn("BEGIN", entry["last_text"])
        self.assertTrue(entry["last_text"].endswith("UNIQUE CONCLUSION"))

    def test_missing_attention_file_is_quiet_not_unknown(self):
        from steward_cockpit import steward_campaign as campaign
        m = campaign.read_map(self.tmp)
        self.assertEqual(m["attention"]["state"], "quiet")
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertEqual(status["plan"]["attention"], "quiet")
        self.assertNotIn("unknown", status["plan"]["attention"])

    def test_malformed_attention_is_unknown_not_quiet(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        (hidden / "attention.json").write_text("{bad json", encoding="utf-8")
        m = campaign.read_map(self.tmp)
        self.assertEqual(m["attention"]["state"], "unknown")
        self.assertIn("unreadable", m["attention"]["reason"])

    def test_old_working_attention_without_live_owner_expires(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        flag = hidden / "attention.json"
        flag.write_text('{"state":"working","reason":"background"}',
                        encoding="utf-8")
        old = time.time() - campaign.ATTENTION_WORKING_GRACE_SECONDS - 5
        os.utime(flag, (old, old))
        m = campaign.read_map(self.tmp)
        self.assertEqual(m["attention"]["state"], "stale")
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertIn("attention stale", " ".join(status["now"]))

    def test_fresh_swarm_owner_keeps_old_working_edge_live(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        flag = hidden / "attention.json"
        flag.write_text('{"state":"working","reason":"background"}',
                        encoding="utf-8")
        old = time.time() - campaign.ATTENTION_WORKING_GRACE_SECONDS - 5
        os.utime(flag, (old, old))
        Path(self.tmp, "heartbeat-r1-Builder.json").write_text(json.dumps({
            "doing": "building", "why": "gate", "next": "test",
            "load_bearing": True, "rabbit": False,
            "ts": time.time() * 1000,
        }), encoding="utf-8")
        m = campaign.read_map(self.tmp)
        self.assertEqual(m["attention"]["state"], "working")
        self.assertTrue(m["attention"]["fresh_owner"])

    def test_typed_attention_states_are_not_flattened_to_quiet(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        flag = hidden / "attention.json"
        for state in ("idle", "blocked", "deliverable_ready", "needs_you"):
            flag.write_text(json.dumps({"schema": "ecgberht-attention-cell-v0",
                                        "state": state, "reason": "fixture"}),
                            encoding="utf-8")
            self.assertEqual(campaign.read_map(self.tmp)["attention"]["state"],
                             state)

    def test_status_ids_and_map_stamps_are_monotonic_at_subsecond_speed(self):
        from steward_cockpit import steward_campaign as campaign
        first = campaign.compose_status(self.tmp, {"busy": False})
        second = campaign.compose_status(self.tmp, {"busy": False})
        self.assertLess(first["status_id"], second["status_id"])

        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir(exist_ok=True)
        flag = hidden / "attention.json"
        flag.write_text('{"state":"quiet"}', encoding="utf-8")
        base_ns = time.time_ns()
        os.utime(flag, ns=(base_ns, base_ns))
        stamp1 = campaign.map_stamp(self.tmp)
        os.utime(flag, ns=(base_ns + 1_000_000, base_ns + 1_000_000))
        stamp2 = campaign.map_stamp(self.tmp)
        self.assertNotEqual(stamp1, stamp2)

    def test_idle_engine_with_held_words_names_them_in_status(self):
        from steward_cockpit import steward_campaign as campaign
        status = campaign.compose_status(
            self.tmp, {"busy": False, "queued": 2})
        self.assertIn("2 held message(s)", " ".join(status["now"]))

    def test_concurrent_status_writers_leave_one_valid_newest_record(self):
        threads = [threading.Thread(target=self.e._status_update)
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        path = Path(self.tmp, ".ecgberht", "status-summary.json")
        persisted = json.loads(path.read_text(encoding="utf-8"))
        ids = [event["status"]["status_id"] for event in self.e.events
               if event.get("t") == "status"]
        self.assertEqual(len(ids), 8)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(persisted["status_id"], ids[-1])
        self.assertEqual(list(path.parent.glob("status-summary.json.*.tmp")), [])

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


class TurnArbiterRaceTest(unittest.TestCase):
    """Human ingress cannot be overtaken at a result boundary."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-arbiter-")
        self._old_state = eng.STATE_FILE
        eng.STATE_FILE = Path(self.tmp) / "state.json"
        self.e = eng.Engine(self.tmp, fake=True)
        self.proc = _FakeProc()
        self.e.proc = self.proc
        self.sent = []

        def send(text):
            self.sent.append(text)
            self.e.busy = True
            self.e.turn_text = ""
            return True

        self.e._send_locked = send

    def tearDown(self):
        eng.STATE_FILE = self._old_state

    def _race_at_status(self, completed_text, human_text):
        entered = threading.Event()
        release = threading.Event()

        def blocked_status(emit=False):
            entered.set()
            self.assertTrue(release.wait(2), "test barrier was not released")

        self.e._status_update = blocked_status
        self.e.turn_text = completed_text
        result = {"type": "result", "total_cost_usd": 0.0,
                  "duration_ms": 1000, "usage": {}}
        result_thread = threading.Thread(
            target=self.e._handle, args=(result, self.proc))
        result_thread.start()
        self.assertTrue(entered.wait(2), "result never reached status barrier")

        human_thread = threading.Thread(target=self.e.say, args=(human_text,))
        human_thread.start()
        human_thread.join(1)
        release.set()
        result_thread.join(2)
        human_thread.join(2)
        self.assertFalse(result_thread.is_alive())
        self.assertFalse(human_thread.is_alive())

    def test_human_cannot_land_then_be_followed_by_drive(self):
        self.e.busy = True
        self.e.drive = True
        self._race_at_status("Finished the current step.", "human answer")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("(drive - not John)", self.sent[0])
        self.assertEqual(self.e.queue, ["human answer"])

    def test_human_cannot_land_then_be_followed_by_answer_nudge(self):
        self.e.busy = True
        self.e._human_asked = True
        self._race_at_status("", "human follow-up")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("ended without answering", self.sent[0])
        self.assertEqual(self.e.queue, ["human follow-up"])

    def test_decision_nudge_emit_and_send_are_one_transaction(self):
        self.e.busy = True
        entered = threading.Event()
        release = threading.Event()
        original_emit = self.e._emit

        def blocked_emit(event):
            if "decision shape:" in event.get("text", ""):
                entered.set()
                self.assertTrue(release.wait(2), "test barrier was not released")
            original_emit(event)

        self.e._emit = blocked_emit
        self.e._status_update = lambda emit=False: None
        self.e.turn_text = "Half checked. Should we ship?"
        result = {"type": "result", "total_cost_usd": 0.0,
                  "duration_ms": 1000, "usage": {}}
        result_thread = threading.Thread(
            target=self.e._handle, args=(result, self.proc))
        result_thread.start()
        self.assertTrue(entered.wait(2), "result never reached nudge barrier")

        human_thread = threading.Thread(
            target=self.e.say, args=("hold for now",))
        human_thread.start()
        human_thread.join(0.1)
        self.assertTrue(human_thread.is_alive(),
                        "human ingress slipped inside machine arbitration")
        self.assertEqual(self.sent, [])
        release.set()
        result_thread.join(2)
        human_thread.join(2)

        self.assertEqual(len(self.sent), 1)
        self.assertIn("without a recommendation", self.sent[0])
        self.assertEqual(self.e.queue, ["hold for now"])


class NeverLoseQueueTest(unittest.TestCase):
    """Park/crash must not drop words he already typed (2026-08-27)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-queue-")
        self._old_state = eng.STATE_FILE
        eng.STATE_FILE = Path(self.tmp) / "state.json"
        self.e = eng.Engine(self.tmp, fake=True)
        self.e.proc = _FakeProc()
        self.e.busy = True

    def tearDown(self):
        eng.STATE_FILE = self._old_state

    def _finish_turn(self, text="Turn complete."):
        self.e.turn_text = text
        self.e.in_tick = False
        self.e._handle({"type": "result", "total_cost_usd": 0.0,
                        "duration_ms": 1000, "usage": {}}, self.e.proc)

    def test_queued_words_survive_stop_and_a_new_engine(self):
        self.e.say("do not lose this", human=True)
        self.assertEqual(self.e.queue, ["do not lose this"])
        with self.e._lock:
            self.e._hold_queue("session closed")
        entry = eng._read_state_entry(self.e.skey())
        self.assertEqual(entry.get("pending_queue"), ["do not lose this"])
        # a reconstructed engine (server restart) picks them up
        e2 = eng.Engine(self.tmp, fake=True)
        self.assertEqual(e2.queue, ["do not lose this"])

    def test_delivered_words_leave_the_durable_queue(self):
        self.e.queue = ["one", "two"]
        with self.e._lock:
            self.e._persist_queue()
        sent = []
        self.e._send_locked = lambda text: (sent.append(text), True)[1]
        self._finish_turn()
        self.assertEqual(sent, ["one"])
        self.assertEqual(self.e.queue, ["two"])
        entry = eng._read_state_entry(self.e.skey())
        self.assertEqual(entry.get("pending_queue"), ["two"])

    def test_failed_delivery_stays_in_memory_and_durable_queue(self):
        self.e.queue = ["do not lose this", "then this"]
        with self.e._lock:
            self.e._persist_queue()
        self.e._send_locked = lambda _text: False
        self._finish_turn()
        self.assertEqual(self.e.queue, ["do not lose this", "then this"])
        entry = eng._read_state_entry(self.e.skey())
        self.assertEqual(entry.get("pending_queue"),
                         ["do not lose this", "then this"])

    def test_queue_api_fails_if_the_words_cannot_be_made_durable(self):
        with mock.patch.object(eng, "_update_state", return_value=False):
            result = self.e.say("do not pretend this was queued", human=True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.e.queue, [])
        self.assertTrue(self.e.broken)
        event_text = " | ".join(event.get("text", "")
                                for event in self.e.events)
        self.assertIn("queue persistence failed", event_text)

    def test_state_writer_fails_closed_instead_of_direct_partial_write(self):
        state = {"session": {"pending_queue": ["words"]}}
        with mock.patch.object(eng.os, "replace", side_effect=PermissionError), \
             mock.patch.object(eng.time, "sleep", return_value=None):
            self.assertFalse(eng._save_state(state))
        self.assertFalse(eng.STATE_FILE.exists())
        self.assertEqual(list(eng.STATE_FILE.parent.glob(
            eng.STATE_FILE.name + ".*.tmp")), [])

    def test_open_poll_wakes_pending_queue_even_without_session_id(self):
        from steward_cockpit import steward_routes as routes
        self.e.proc = None
        self.e.busy = False
        self.e.queue = ["held words"]
        with self.e._lock:
            self.assertTrue(self.e._persist_queue())
        self.e.events_since = lambda _since, timeout=8: ([], 0, False)
        self.e.wake = mock.Mock(return_value=(True, "awake"))
        routes.ENGINES[self.tmp] = self.e
        try:
            _body, code = routes.events(self.tmp, {"since": "0"})
        finally:
            routes.ENGINES.pop(self.tmp, None)
        self.assertEqual(code, 200)
        self.e.wake.assert_called_once_with()


class SwarmStatusTest(unittest.TestCase):
    """Supervised swarm heartbeats show in the status pane (2026-08-27)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-swarm-")
        Path(self.tmp, "ECGBERHT.md").write_text("# face\n", encoding="utf-8")

    def test_heartbeat_files_appear_in_now_and_swarm(self):
        from steward_cockpit import steward_campaign as campaign
        hb = Path(self.tmp) / "heartbeat-r1-Skeptic.json"
        hb.write_text(
            '{"doing":"pressing claim c1","why":"axis","next":"write",'
            '"load_bearing":true,"rabbit":false,'
            '"ts":"2026-08-29T14:00:00-06:00"}',
            encoding="utf-8")
        trails = campaign.read_swarm_trails(self.tmp)
        self.assertEqual(len(trails), 1)
        self.assertEqual(trails[0]["doing"], "pressing claim c1")
        self.assertEqual(trails[0]["state"], "fresh")
        status = campaign.compose_status(self.tmp, {"busy": False})
        joined = " | ".join(status["now"])
        self.assertIn("pressing claim c1", joined)
        self.assertIn("on path", joined)
        self.assertEqual(status["swarm"][0]["doing"], "pressing claim c1")

    def test_stale_heartbeat_is_evidence_not_live_work(self):
        from steward_cockpit import steward_campaign as campaign
        hb = Path(self.tmp) / "heartbeat-r2-Builder.json"
        hb.write_text(
            '{"doing":"building","why":"gate","next":"test",'
            '"load_bearing":true,"rabbit":false,"ts":1}',
            encoding="utf-8")
        old = time.time() - campaign.SWARM_HEARTBEAT_LEASE_SECONDS - 5
        os.utime(hb, (old, old))
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertEqual(status["swarm"][0]["state"], "stale")
        joined = " | ".join(status["now"])
        self.assertIn("nothing running", joined)
        self.assertIn("stale heartbeat", joined)
        self.assertNotIn("on path", joined)

    def test_malformed_heartbeat_is_unknown_not_live(self):
        from steward_cockpit import steward_campaign as campaign
        Path(self.tmp, "heartbeat-r3-Reviewer.json").write_text(
            '{"doing":"reviewing"}', encoding="utf-8")
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertEqual(status["swarm"][0]["state"], "unknown")
        joined = " | ".join(status["now"])
        self.assertIn("heartbeat unknown", joined)
        self.assertNotIn("on path", joined)

    def test_unscoped_base_heartbeat_is_not_a_swarm_seat(self):
        from steward_cockpit import steward_campaign as campaign
        Path(self.tmp, "heartbeat.json").write_text(
            '{"doing":"old","why":"","next":"",'
            '"load_bearing":true,"rabbit":false,"ts":1}',
            encoding="utf-8")
        self.assertEqual(campaign.read_swarm_trails(self.tmp), [])

    def test_missing_heartbeats_are_quiet_not_unknown(self):
        from steward_cockpit import steward_campaign as campaign
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertEqual(status["swarm"], [])
        self.assertNotIn("unknown", " ".join(status["now"]).lower())

    def test_duplicate_seat_is_one_row_and_newest_valid_payload_wins(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        old = Path(self.tmp, "heartbeat-r1-Seat.json")
        new = hidden / "heartbeat-r2-Seat.json"
        base = {
            "why": "gate", "next": "test",
            "load_bearing": True, "rabbit": False,
        }
        old.write_text(json.dumps({**base, "doing": "old copy",
                                  "ts": (time.time() - 60) * 1000}),
                       encoding="utf-8")
        new.write_text(json.dumps({**base, "doing": "new copy",
                                  "ts": time.time() * 1000}),
                       encoding="utf-8")
        trails = campaign.read_swarm_trails(self.tmp)
        self.assertEqual(len(trails), 1)
        self.assertEqual(trails[0]["doing"], "new copy")
        self.assertEqual(trails[0]["duplicate_sources"], 2)

    def test_touching_old_numeric_payload_does_not_resurrect_it(self):
        from steward_cockpit import steward_campaign as campaign
        hb = Path(self.tmp, "heartbeat-r4-Old.json")
        hb.write_text(json.dumps({
            "doing": "old", "why": "gate", "next": "stop",
            "load_bearing": True, "rabbit": False,
            "ts": (time.time() - campaign.SWARM_HEARTBEAT_LEASE_SECONDS - 5)
                  * 1000,
        }), encoding="utf-8")
        os.utime(hb, None)
        trail = campaign.read_swarm_trails(self.tmp)[0]
        self.assertEqual(trail["clock_source"], "payload")
        self.assertEqual(trail["state"], "stale")

    def test_valid_older_copy_beats_newer_malformed_duplicate(self):
        from steward_cockpit import steward_campaign as campaign
        hidden = Path(self.tmp, ".ecgberht")
        hidden.mkdir()
        valid = Path(self.tmp, "heartbeat-r1-Builder.json")
        invalid = hidden / "heartbeat-r2-Builder.json"
        valid.write_text(json.dumps({
            "doing": "building", "why": "gate", "next": "test",
            "load_bearing": True, "rabbit": False,
            "ts": time.time() * 1000,
        }), encoding="utf-8")
        invalid.write_text("{not json", encoding="utf-8")
        trails = campaign.read_swarm_trails(self.tmp)
        self.assertEqual(len(trails), 1)
        self.assertEqual(trails[0]["doing"], "building")
        self.assertEqual(trails[0]["duplicate_sources"], 2)

    def test_future_clock_skew_is_exposed(self):
        from steward_cockpit import steward_campaign as campaign
        hb = Path(self.tmp, "heartbeat-r5-Skewed.json")
        hb.write_text(json.dumps({
            "doing": "checking clock", "why": "gate", "next": "sync",
            "load_bearing": True, "rabbit": False,
            "ts": (time.time() + 120) * 1000,
        }), encoding="utf-8")
        trail = campaign.read_swarm_trails(self.tmp)[0]
        self.assertEqual(trail["state"], "fresh")
        self.assertGreater(trail["clock_skew_seconds"], 100)


class ProductMapTest(unittest.TestCase):
    """Tagged steps ARE the product map (2026-08-28)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-map-")
        Path(self.tmp, "ECGBERHT.md").write_text(
            "## North star\n\nBuild the model-space prior.\n", encoding="utf-8")

    def test_tagged_steps_derive_the_map_and_flag_a_stale_goal(self):
        from steward_cockpit import steward_campaign as campaign
        Path(self.tmp, "roadmap.json").write_text(json.dumps({
            "schema": "ecgberht-roadmap-v0",
            "roadmap_events": [
                {"kind": "step_create", "step_id": "m1", "name": "Audit the math",
                 "status": "done", "part": "research",
                 "gate": "python audit/prior_certify.py"},
                {"kind": "status_flip", "step_id": "m1", "from": "planned",
                 "to": "done", "receipt": {"who": "steward", "why": "landed"}},
            ],
            "roadmap_projection": [
                {"id": "m1", "name": "Audit the math", "status": "done",
                 "part": "research", "gate": "python audit/prior_certify.py"},
            ],
        }), encoding="utf-8")
        m = campaign.read_map(self.tmp)
        self.assertEqual(m["map"][0].startswith("research: Audit the math"), True)
        self.assertFalse(m["goal_reread"], "close without goal_flip must flag")
        status = campaign.compose_status(self.tmp, {"busy": False})
        self.assertIn("goal not re-read since last close", " ".join(status["now"]))
        self.assertEqual(status["map"], m["map"])

    def test_goal_flip_clears_the_stale_flag(self):
        from steward_cockpit import steward_campaign as campaign
        Path(self.tmp, "roadmap.json").write_text(json.dumps({
            "schema": "ecgberht-roadmap-v0",
            "roadmap_events": [
                {"kind": "status_flip", "step_id": "m1", "to": "done",
                 "receipt": {"who": "steward", "why": "landed"}},
                {"kind": "goal_flip", "step_id": "m1", "verdict": "rewritten",
                 "goal_to": "Build the prior",
                 "receipt": {"who": "steward", "why": "audit falsified JASA-now"}},
            ],
            "roadmap_projection": [
                {"id": "m1", "name": "Audit", "status": "done", "part": "research"},
            ],
        }), encoding="utf-8")
        m = campaign.read_map(self.tmp)
        self.assertTrue(m["goal_reread"])

    def test_work_map_groups_the_deliverable_backbone(self):
        from steward_cockpit import steward_campaign as campaign
        Path(self.tmp, "roadmap.json").write_text(json.dumps({
            "schema": "ecgberht-roadmap-v0",
            "roadmap_events": [],
            "roadmap_projection": [
                {"id": "a", "name": "Audit", "status": "done", "part": "research"},
                {"id": "b", "name": "The prior", "status": "active", "part": "slice",
                 "gate": "python audit/prior_certify.py"},
                {"id": "c", "name": "JASA draft", "status": "proposed", "part": "harden"},
            ],
        }), encoding="utf-8")
        wm = campaign.read_map(self.tmp)["work_map"]
        self.assertEqual([g["tag"] for g in wm], ["research", "slice", "harden"])
        self.assertEqual(wm[0]["label"], "Background")
        self.assertEqual(wm[1]["steps"][0]["name"], "The prior")

    def test_standup_proposes_a_work_product_map_from_ordinary_talk(self):
        self.assertNotIn("BRAIN DUMP", eng.STAND_UP_NEW)
        self.assertIn("ordinary conversation", eng.STAND_UP_NEW)
        self.assertIn("WORK-PRODUCT MAP", eng.STAND_UP_NEW)
        self.assertIn("data-wptile",
                      (REPO / "steward_cockpit" / "static" / "v1.html")
                      .read_text(encoding="utf-8"))


class CockpitSurfaceCutTest(unittest.TestCase):
    """Default cockpit is the product. High Seat / old chamber are not on it.
    Phone ping is not a cockpit feature (steward works for him)."""

    def test_effort_window_survives_a_map_failure(self):
        js = (REPO / "steward_cockpit" / "static" / "shared.js").read_text(
            encoding="utf-8")
        self.assertIn("try { await loadMap(); }", js)

    def test_plan_window_has_a_work_product_tile(self):
        html = (REPO / "steward_cockpit" / "static" / "v1.html").read_text(
            encoding="utf-8")
        self.assertIn("data-wptile", html)
        self.assertIn("data-wpmap", html)
        self.assertIn("Work product", html)
        self.assertNotIn("Same parts as the plan", html)
        self.assertIn("plate.js", html)

    def test_cockpit_has_work_product_tile_and_plate(self):
        html = (REPO / "steward_cockpit" / "static" / "cockpit.html").read_text(
            encoding="utf-8")
        self.assertIn("data-wptile", html)
        self.assertIn("plate.js", html)
        self.assertIn("data-wpbody", html)

    def test_plate_prototype_page_exists(self):
        html = (REPO / "steward_cockpit" / "static" / "plate-prototype.html"
                ).read_text(encoding="utf-8")
        self.assertIn("DeliverablePlate.paintPlate", html)
        self.assertIn("Collapse of Marketing", html)
        self.assertNotIn("write Methods", html)

    def test_collapse_marketing_has_authored_plates(self):
        from steward_cockpit import steward_campaign as camp
        paper = REPO.parent / "Collapse of Marketing" / "Emperical Paper JCR"
        if not paper.is_dir():
            self.skipTest("Collapse of Marketing not on this host")
        pl = camp.read_plate(str(paper))
        self.assertIsNotNone(pl)
        self.assertEqual(pl["kind"], "paper")
        labels = [p["label"] for p in pl["parts"]]
        self.assertIn("Contribution", labels)
        self.assertIn("Method", labels)
        self.assertNotIn("write Methods", labels)

    def test_cockpit_doc_is_not_high_seat_or_chamber(self):
        from steward_cockpit import steward_routes as routes
        html = routes.serve_cockpit_doc("demo")
        self.assertIsInstance(html, str)
        self.assertNotIn("high-seat.js", html)
        self.assertNotIn("chamber-ui.js", html)
        self.assertNotIn("chamber-page.js", html)
        self.assertIn("Dashboard", html)
        self.assertNotIn("High Seat", html)
        self.assertNotIn("phone ping", html.lower())


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
