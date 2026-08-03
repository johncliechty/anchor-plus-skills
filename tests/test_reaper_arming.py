"""reaper Wave 8 — arming ladder + tamper-evident receipts (arming behavior).

Locks the safety BEHAVIOR of the log→freeze→kill arming ladder (criteria 10, 12):

  - UNARMED by DEFAULT: with no persisted arm state the effective tier is LOG
    (dry-run) — the daemon touches no process.
  - The ``.anchor/reaper.disarmed`` kill-switch FILE forces dry-run regardless of
    the persisted arm tier (a restart-durable brake).
  - The FREEZE-ONLY tier never kills — it freezes only confirmed-dead-owner +
    no-corroborated-signal candidates and ABSTAINS on any corroborated positive
    signal; every freeze is bounded by an auto-thaw watchdog.
  - Every classify outcome writes a hash-chained owner-evidence RECEIPT with the
    enumerated shape; the chain verifies and an edit breaks it.
  - The arm gate refuses to advance a rung whose numeric bar (consecutive clean
    sweeps, recomputed in-process from the verified chain) is unmet.
  - The consecutive-abstain health banner trips after > K abstain sweeps.

Hermetic: a temp ``ANCHOR_DATA_DIR`` + explicit records + injected fake
probe/freezer/killer spies — never touches the live ``.anchor`` store or any real
process. Stdlib + pytest only.
"""
import importlib

import pytest


NOW = 3_000_000.0


class FakeProbe:
    """A creation-time-only probe. Missing entry ⇒ the PID probes DEAD (gone)."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


class Spy:
    def __init__(self, ret=True):
        self.calls = []
        self.ret = ret

    def __call__(self, pid):
        self.calls.append(pid)
        return self.ret


@pytest.fixture
def arm(tmp_path, monkeypatch):
    """Temp data dir + freshly-reloaded reaper stack (so ANCHOR_DATA_DIR wins)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # No token configured by default → these arming tests exercise the GATE, not
    # auth (the control-plane test file covers auth). Ensure it's off.
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import reaper
    importlib.reload(reaper)
    import freeze_state
    importlib.reload(freeze_state)
    import reaper_arming
    importlib.reload(reaper_arming)
    return reaper_arming


def _rec(session_id, *, pid, ct, created_at, status="running", worktree=""):
    return {
        "session_id": session_id,
        "status": status,
        "pid": pid,
        "proc_create_time": ct,
        "crypt_token": "tok",
        "created_at": created_at,
        "worktree_path": worktree,
    }


def _dead_orphan(sid="orphan", pid=100, ct=50.0):
    """A confirmed-dead-owner candidate, past the boot-grace window."""
    return _rec(sid, pid=pid, ct=ct, created_at=NOW - 10_000)


def _snap(reaper, records, times):
    return reaper.build_snapshot(
        attached_pty_ids=set(), records=records,
        job_active=lambda _s: False, probe=FakeProbe(times), now=NOW)


# ── Unarmed by default ───────────────────────────────────────────────────────

def test_unarmed_by_default(arm):
    """With no persisted state the tier is LOG (dry-run) and nothing is armed."""
    assert arm.persisted_tier() == arm.TIER_LOG
    assert arm.effective_tier() == arm.TIER_LOG
    assert arm.is_disarmed() is False


def test_log_tier_never_touches_a_process(arm):
    """At the default LOG tier a real orphan yields a would-kill marker only —
    no freeze, no kill."""
    import reaper
    rec = _dead_orphan()
    snap = _snap(reaper, [rec], {})  # empty ⇒ owner dead ⇒ REAP_DEAD candidate
    freezer, killer = Spy(), Spy()
    report = arm.armed_sweep([rec], snap, freezer=freezer, killer=killer, now=NOW)
    assert report["tier"] == arm.TIER_LOG
    assert report["would_kill"] == ["orphan"]
    assert report["frozen"] == [] and report["killed"] == []
    assert freezer.calls == [] and killer.calls == []


# ── The kill-switch brake forces dry-run ─────────────────────────────────────

def test_disarm_file_forces_dry_run(arm):
    """A persisted KILL tier + the .anchor/reaper.disarmed brake ⇒ effective LOG,
    and a real orphan is NOT killed."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_KILL})
    assert arm.persisted_tier() == arm.TIER_KILL
    arm.engage_brake()  # drop the kill-switch file
    assert arm.is_disarmed() is True
    assert arm.effective_tier() == arm.TIER_LOG  # brake WINS

    rec = _dead_orphan()
    snap = _snap(reaper, [rec], {})
    killer = Spy()
    report = arm.armed_sweep([rec], snap, killer=killer, now=NOW)
    assert report["tier"] == arm.TIER_LOG
    assert killer.calls == []             # forced dry-run — nothing killed
    assert report["would_kill"] == ["orphan"]

    # Releasing the brake restores the persisted KILL tier.
    assert arm.release_brake() is True
    assert arm.effective_tier() == arm.TIER_KILL


# ── Freeze-only tier ─────────────────────────────────────────────────────────

def test_freeze_only_freezes_dead_owner_never_kills(arm):
    """The FREEZE tier freezes a confirmed-dead-owner candidate via the injected
    suspend primitive and calls NO killer."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_FREEZE})
    rec = _dead_orphan(pid=100)
    snap = _snap(reaper, [rec], {})
    freezer, killer = Spy(), Spy()
    report = arm.armed_sweep([rec], snap, freezer=freezer, killer=killer, now=NOW)

    assert report["tier"] == arm.TIER_FREEZE
    assert report["frozen"] == ["orphan"]
    assert report["killed"] == []
    assert freezer.calls == [100]         # the per-PID floor freeze, not a kill
    assert killer.calls == []             # freeze-only NEVER kills
    # The freeze is persisted with an auto-thaw watchdog deadline.
    import freeze_state
    entry = freeze_state.get_entry("orphan")
    assert entry is not None and entry.state == freeze_state.STATE_FROZEN
    assert entry.thaw_deadline is not None and entry.thaw_deadline > NOW


def test_freeze_only_abstains_on_corroborated_signal(arm):
    """A live (owner_alive), unowned session carries a CORROBORATED positive
    signal → the freeze-only tier ABSTAINS (never freezes, never kills)."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_FREEZE})
    # owner ALIVE (probe returns the matching create-time), no live owner.
    rec = _dead_orphan(sid="live", pid=200, ct=77.0)
    snap = _snap(reaper, [rec], {200: 77.0})
    sig = snap.positive_liveness.get("live")
    assert reaper.has_corroborated_positive(sig) is True   # owner_alive corroborates

    freezer, killer = Spy(), Spy()
    report = arm.armed_sweep([rec], snap, freezer=freezer, killer=killer, now=NOW)
    assert report["abstained"] == ["live"]
    assert report["frozen"] == [] and report["killed"] == []
    assert freezer.calls == [] and killer.calls == []
    # The receipt records the corroboration that spared it.
    latest = arm._latest_decision_by_session()
    assert latest["live"]["decision"] == arm.DECISION_ABSTAIN
    assert latest["live"]["corroborated_positive"] is True


def test_auto_thaw_watchdog_resumes_an_expired_freeze(arm):
    """A freeze past its watchdog deadline is auto-resumed and dropped."""
    import freeze_state
    freeze_state.freeze_session(_dead_orphan(pid=100), suspend=Spy(), now=NOW,
                                thaw_deadline=NOW + 100)
    assert freeze_state.is_frozen("orphan")
    resume = Spy(ret=True)
    # Not yet due ⇒ no thaw.
    assert arm.auto_thaw_expired(now=NOW + 50, resume=resume) == ()
    assert freeze_state.is_frozen("orphan")
    # Past the deadline ⇒ auto-thawed (resumed + entry dropped).
    thawed = arm.auto_thaw_expired(now=NOW + 200, resume=resume)
    assert thawed == ("orphan",)
    assert resume.calls == [100]
    assert not freeze_state.is_frozen("orphan")


# ── Hash-chained owner-evidence receipts ─────────────────────────────────────

def test_receipt_shape_and_hash_chain(arm):
    """A decision receipt carries every enumerated field and the chain verifies;
    an edit to a stored line breaks the chain."""
    import reaper
    rec = _dead_orphan()
    snap = _snap(reaper, [rec], {})
    body = arm.build_decision_receipt(rec, snap, arm.DECISION_WOULD_KILL, now=NOW)

    # Shape: predicates fired, identity tuple, positive-liveness + corroboration,
    # confirmed-death, age source, decision.
    assert body["kind"] == "decision"
    assert body["session_id"] == "orphan"
    assert body["decision"] == arm.DECISION_WOULD_KILL
    for key in ("has_live_owner", "corroborated_positive", "confirmed_dead",
                "age_protected"):
        assert key in body["predicates"]
    for key in ("pid", "proc_create_time", "live_create_time", "image_path"):
        assert key in body["identity"]
    for key in ("owner_alive", "owner_confirmed_dead", "index_lock",
                "heartbeat_fresh", "socket_owned", "work_mtime_fresh", "cpu_active"):
        assert key in body["positive_liveness"]
    assert body["confirmed_dead"] is True          # dead owner
    assert body["age_source"] == "created_at"

    stored = arm.append_receipt(body)
    assert stored["prev_hash"] == arm.GENESIS_HASH  # first link
    assert stored["hash"]
    ok, bad = arm.verify_chain()
    assert ok is True and bad == -1

    # Tamper: rewrite the decision on disk without re-chaining ⇒ chain breaks.
    p = arm.receipts_path()
    txt = p.read_text(encoding="utf-8").replace(arm.DECISION_WOULD_KILL, "keep")
    p.write_text(txt, encoding="utf-8")
    ok2, bad2 = arm.verify_chain()
    assert ok2 is False and bad2 == 0


def test_receipt_chain_across_multiple_appends(arm):
    """Several appends chain correctly; deleting a middle line breaks it."""
    for i in range(4):
        arm.append_receipt({"kind": "decision", "session_id": f"s{i}",
                            "decision": arm.DECISION_KEEP, "ts": NOW + i})
    ok, _ = arm.verify_chain()
    assert ok is True
    lines = arm.receipts_path().read_text(encoding="utf-8").splitlines()
    # Drop the 2nd line ⇒ the 3rd's prev_hash no longer matches ⇒ break at #1.
    kept = "\n".join(lines[:1] + lines[2:]) + "\n"
    arm.receipts_path().write_text(kept, encoding="utf-8")
    ok2, bad2 = arm.verify_chain()
    assert ok2 is False and bad2 == 1


# ── The arm gate: numeric bar ────────────────────────────────────────────────

def test_under_bar_advance_refused(arm, monkeypatch):
    """Fewer than the required consecutive clean sweeps ⇒ the gate refuses."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "5")
    for _ in range(3):
        arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    gate = arm.evaluate_arm_gate(arm.TIER_FREEZE, snapshot=good)
    assert gate.passed is False
    assert "under bar" in gate.reason
    assert gate.clean_streak == 3 and gate.required == 5

    out = arm.arm("ignored", snapshot=good)  # auth disabled → gate is the gate
    assert out["ok"] is False and out["changed"] is False
    assert arm.persisted_tier() == arm.TIER_LOG    # no state change


def test_over_bar_advance_arms(arm, monkeypatch):
    """Meeting the bar arms the freeze rung and records the passing sweep."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "2")
    for _ in range(2):
        arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    out = arm.arm("tok", snapshot=good, now=NOW)
    assert out["ok"] is True and out["changed"] is True
    assert out["tier"] == arm.TIER_FREEZE
    assert arm.persisted_tier() == arm.TIER_FREEZE
    # The passing sweep was recorded into the tamper-evident chain as an arm event.
    sweeps = [r for r in arm.read_receipts()
              if r.get("kind") == "sweep" and r.get("arm_event")]
    assert len(sweeps) == 1 and sweeps[0]["tier"] == arm.TIER_FREEZE


def test_abstain_sweep_resets_the_clean_streak(arm, monkeypatch):
    """An abstain (degraded) sweep breaks the consecutive-clean run."""
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "3")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    arm.record_sweep(arm.TIER_LOG, clean=False, abstained=True, now=NOW)  # reset
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    stats = arm.receipt_stats()
    assert stats.clean_streak == 1        # only the trailing clean one counts


# ── Health banner ────────────────────────────────────────────────────────────

def test_health_banner_trips_on_abstain_streak(arm, monkeypatch):
    """More than K consecutive abstain sweeps trips the dashboard banner."""
    monkeypatch.setenv("ANCHOR_REAPER_ABSTAIN_BANNER_K", "2")
    assert arm.health_banner() is None                 # nothing recorded yet
    for _ in range(3):                                 # 3 > K(2)
        arm.record_sweep(arm.TIER_LOG, clean=False, abstained=True, now=NOW)
    banner = arm.health_banner()
    assert banner is not None and banner["tripped"] is True
    assert banner["kind"] == "abstain-streak"
    assert banner["streak"] == 3 and banner["threshold"] == 2


def test_health_banner_clears_after_a_clean_sweep(arm, monkeypatch):
    """A clean sweep resets the abstain streak and clears the banner."""
    monkeypatch.setenv("ANCHOR_REAPER_ABSTAIN_BANNER_K", "2")
    for _ in range(3):
        arm.record_sweep(arm.TIER_LOG, clean=False, abstained=True, now=NOW)
    assert arm.health_banner() is not None
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    assert arm.health_banner() is None


def test_explain_dump_is_read_only_and_shaped(arm):
    """explain() returns the inspection dump without acting on anything."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_FREEZE})
    rec = _dead_orphan()
    snap = _snap(reaper, [rec], {})
    dump = arm.explain([rec], snapshot=snap)
    assert dump["persisted_tier"] == arm.TIER_FREEZE
    assert dump["effective_tier"] == arm.TIER_FREEZE
    assert dump["arm"]["next_tier"] == arm.TIER_KILL
    assert dump["arm"]["required"] >= 1
    assert len(dump["sessions"]) == 1
    assert dump["sessions"][0]["session_id"] == "orphan"
    # A text render exists for the CLI.
    assert "REAPER STATUS" in arm.format_explain(dump)
