# W11 — E7: mid-flight re-brief per the AUDITED mode (live channel,
# acknowledgment receipt on the step, NO relaunch) + the co-landed
# re-brief-during-sweep contention refusal (steward-chamber W11, C7).
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive these tests:
#   * "Mid-flight re-brief per the audited mode: live channel with
#     acknowledgment receipt on the step … (E7 test, no relaunch)"
#   * "a re-brief landing DURING an active sweep is refused or queued behind
#     the sweep's card binding with a named finding, never interleaved"
#   * V2: boundary mode only on a John-signed no-live-channel outcome — the
#     committed audit record says the live channel EXISTS.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_gates as cg  # noqa: E402
import chamber_rebrief as crb  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]


def _project(tmp_path):
    folder = tmp_path / "proj"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    return folder


class _Channel:
    """A recording delivery seam standing in for the live paced-PTY write."""

    def __init__(self):
        self.writes = []

    def __call__(self, session_id, data):
        self.writes.append((session_id, data))


# ── the audited mode: the committed machine record fixes the design ─────────

def test_channel_audit_record_is_committed_versioned_and_live_mode():
    doc = crb.load_channel_audit()
    assert doc["schema_version"] == crb.CHANNEL_AUDIT_SCHEMA_VERSION
    assert doc["owner_file"] == "chamber_rebrief.py"
    assert doc["mode"] == crb.MODE_LIVE
    # The channel is named by module + symbol (a role-only description was
    # the W2 FAIL condition).
    ch = doc["audit"]["channel"]
    assert ch["file"] == "pty_manager.py"
    assert "write" in ch["symbol"]
    assert doc["audit"]["no_relaunch"] is True
    # No absolute host paths in the shipped record.
    raw = json.dumps(doc)
    assert "C:\\\\Users" not in raw and "/Users/" not in raw


def test_rebrief_module_delivers_on_the_wired_paced_pty_channel():
    src = (ANCHOR / "chamber_rebrief.py").read_text(encoding="utf-8")
    assert "pty_manager.write" in src, (
        "the default delivery seam must be the WIRED paced-PTY path "
        "(wire-homing row paced_pty)")
    # NO RELAUNCH, structurally: the module never touches session start.
    assert "start_session" not in src
    assert "terminal_session" not in src


# ── E7: live delivery + acknowledgment receipt on the step, no relaunch ─────

def test_rebrief_reaches_the_running_commission_with_receipt_no_relaunch(tmp_path):
    folder = _project(tmp_path)
    chan = _Channel()
    out = crb.rebrief(folder, "sess-42", "focus week 1 on orals only",
                      step_id="step-syllabus", deliver=chan)
    assert out["ok"], out
    assert out["mode"] == crb.MODE_LIVE
    # Exactly ONE write onto the LIVE session's stdin — no kill, no respawn.
    assert len(chan.writes) == 1
    sid, payload = chan.writes[0]
    assert sid == "sess-42"
    assert payload.startswith(crb.REBRIEF_FRAME)
    assert "focus week 1 on orals only" in payload
    # The acknowledgment receipt surfaces ON THE STEP (E7).
    receipts = crb.receipts_for_step(folder, "step-syllabus")
    assert len(receipts) == 1
    assert receipts[0]["mode"] == crb.MODE_LIVE
    assert receipts[0]["session_id"] == "sess-42"
    assert crb.receipts_for_session(folder, "sess-42")


def test_dead_session_is_an_honest_named_refusal_never_a_relaunch(tmp_path):
    folder = _project(tmp_path)
    # No deliver seam injected → liveness gates on the real PTY table, where
    # nothing is live in this test process.
    out = crb.rebrief(folder, "no-such-session", "hello", step_id="s1")
    assert not out["ok"]
    assert out["error"] == crb.ERROR_SESSION_NOT_LIVE
    assert crb.receipts_for_session(folder, "no-such-session") == []


def test_empty_text_and_failed_delivery_mint_no_receipt(tmp_path):
    folder = _project(tmp_path)
    assert crb.rebrief(folder, "s", "  ", deliver=_Channel())["error"] \
        == crb.ERROR_EMPTY_TEXT

    def broken(sid, data):
        raise OSError("pipe gone")

    out = crb.rebrief(folder, "sess-9", "text", step_id="st", deliver=broken)
    assert out["error"] == crb.ERROR_DELIVERY_FAILED
    assert crb.receipts_for_step(folder, "st") == []


# ── the co-landed contention law: refused-and-queued behind the sweep ───────

def test_rebrief_during_active_sweep_is_queued_with_named_finding(tmp_path):
    folder = _project(tmp_path)
    # A run dies → the sweep owns the decision window (E2 holding).
    cg.on_run_death(folder, {"session_id": "dead-1", "outcome": "died",
                             "step_id": "s1", "skill": "foreman"})
    chan = _Channel()
    out = crb.rebrief(folder, "sess-42", "mid-sweep re-brief",
                      step_id="s1", deliver=chan)
    assert not out["ok"]
    assert out["queued"] is True
    assert out["finding"] == crb.FINDING_REBRIEF_DURING_SWEEP
    # NEVER interleaved: nothing was written to the live session.
    assert chan.writes == []
    queued = crb.queued_rebriefs(folder)
    assert len(queued) == 1 and queued[0]["text"] == "mid-sweep re-brief"
    # Still contended AFTER the card binds but BEFORE it resolves: the sweep
    # card holds the queue head.
    swept = cg.run_sweep(folder, {"session_id": "dead-1", "outcome": "died",
                                  "step_id": "s1", "skill": "foreman"})
    bound = cg.bind_sweep_card(folder, swept, session_id="dead-1",
                               commit=False)
    assert bound["ok"]
    flush = crb.flush_queued(folder, deliver=chan)
    assert flush.get("still_contended") is True
    assert chan.writes == []
    # The sweep card resolves → the window clears → the queue flushes.
    head = cg.queue_state(folder)["head"]
    assert cg.resolve_gate(folder, head["gate_id"], commit=False)["ok"]
    flush2 = crb.flush_queued(folder, deliver=chan)
    assert flush2["ok"] and flush2["delivered"] == 1
    assert len(chan.writes) == 1
    assert crb.queued_rebriefs(folder) == []
    # The receipt now exists on the step — delivered AFTER the sweep, never
    # interleaved into it.
    assert crb.receipts_for_step(folder, "s1")


def test_contention_check_fails_closed_on_unreadable_gates_store(tmp_path):
    folder = _project(tmp_path)
    cg.gates_path(folder).parent.mkdir(parents=True, exist_ok=True)
    cg.gates_path(folder).write_text("{broken", encoding="utf-8")
    chan = _Channel()
    out = crb.rebrief(folder, "sess-1", "text", deliver=chan)
    assert not out["ok"]
    assert out.get("finding") == crb.FINDING_REBRIEF_DURING_SWEEP
    assert chan.writes == []
