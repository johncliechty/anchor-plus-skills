"""reaper Wave 8 — control-plane integrity (auth + protect-only + tamper-evidence).

Locks the CONTROL-PLANE security properties (criteria 10, 12, 14):

  - arm / advance / disarm require the same shared-secret token as every other
    mutating Anchor endpoint (``paths.auth_ok``). An unauthenticated request is
    refused with NO state change.
  - Protect-only persistence: a persisted ``kill`` tier can NEVER, by itself,
    trigger a kill — every destructive action is re-derived IN-PROCESS from a
    fresh live probe (``reaper.kill_authorized``). An alive owner ⇒ nothing dies;
    only a freshly-probed confirmed-dead owner is killed.
  - The arm gate recomputes IN-PROCESS from the tamper-evident hash chain: a
    forged/edited receipt log FAILS chain-verify, and an inflated *stored
    aggregate* is ignored (the streak is recomputed from the raw chain).

Hermetic: a temp ``ANCHOR_DATA_DIR`` + a configured ``ANCHOR_TOKEN`` + injected
fake probe/killer spies — never touches the live store or any real process.
Stdlib + pytest only.
"""
import importlib

import pytest


NOW = 4_000_000.0
TOKEN = "placeholder"  # distro no-secrets scan: exempt placeholder value (not a real secret)


class FakeProbe:
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
    """Temp data dir + a CONFIGURED token (auth ON) + reloaded reaper stack."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", TOKEN)
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


def _rec(sid, *, pid, ct, created_at=NOW - 10_000, status="running"):
    return {
        "session_id": sid, "status": status, "pid": pid,
        "proc_create_time": ct, "crypt_token": "tok",
        "created_at": created_at, "worktree_path": "",
    }


def _snap(reaper, records, times):
    return reaper.build_snapshot(
        attached_pty_ids=set(), records=records,
        job_active=lambda _s: False, probe=FakeProbe(times), now=NOW)


# ── Authenticated control plane ──────────────────────────────────────────────

def test_unauthed_arm_refused_no_state_change(arm, monkeypatch):
    """arm() with a bad token is refused and changes NOTHING."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    before = arm.persisted_tier()

    out = arm.arm("WRONG-TOKEN", snapshot=good, now=NOW)
    assert out["ok"] is False
    assert out["error"] == "unauthorized"
    assert out["changed"] is False
    assert arm.persisted_tier() == before == arm.TIER_LOG   # no state change


def test_unauthed_advance_refused(arm, monkeypatch):
    """advance() with a bad token is refused with no state change."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    out = arm.advance(None, snapshot=_snap(reaper, [], {}), now=NOW)
    assert out["ok"] is False and out["error"] == "unauthorized"
    assert arm.persisted_tier() == arm.TIER_LOG


def test_unauthed_disarm_refused_no_brake(arm):
    """disarm() with a bad token is refused and drops NO kill-switch file."""
    arm._save_arm_state({"tier": arm.TIER_KILL})
    out = arm.disarm("WRONG")
    assert out["ok"] is False and out["error"] == "unauthorized"
    assert arm.persisted_tier() == arm.TIER_KILL          # unchanged
    assert not arm.disarm_path().exists()                 # no brake engaged


def test_authed_arm_and_disarm(arm, monkeypatch):
    """The correct token arms the freeze rung; disarm drops back to LOG + brakes."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})

    out = arm.arm(TOKEN, snapshot=good, now=NOW)
    assert out["ok"] is True and out["tier"] == arm.TIER_FREEZE
    assert arm.persisted_tier() == arm.TIER_FREEZE

    d = arm.disarm(TOKEN, now=NOW)
    assert d["ok"] is True and d["tier"] == arm.TIER_LOG
    assert arm.persisted_tier() == arm.TIER_LOG
    assert arm.is_disarmed() is True                      # restart-durable brake


# ── Protect-only: a persisted 'kill' tier cannot kill without live re-derivation ─

def test_persisted_kill_does_not_kill_a_live_owner(arm):
    """tier=KILL persisted, but the FRESH probe says the owner is ALIVE ⇒ NOTHING
    is killed — the kill decision comes from the live probe, not the flag."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_KILL})
    rec = _rec("live", pid=200, ct=77.0)
    snap = _snap(reaper, [rec], {200: 77.0})             # owner alive
    killer = Spy()
    report = arm.armed_sweep([rec], snap, killer=killer, now=NOW)
    assert report["tier"] == arm.TIER_KILL
    assert killer.calls == []                            # alive owner ⇒ no kill
    assert report["killed"] == []


def test_persisted_kill_kills_only_a_freshly_confirmed_dead_owner(arm):
    """The SAME persisted KILL tier DOES kill when the fresh probe confirms the
    owner dead — proving the authorization is re-derived live each sweep."""
    import reaper
    arm._save_arm_state({"tier": arm.TIER_KILL})
    rec = _rec("dead", pid=300, ct=88.0)
    snap = _snap(reaper, [rec], {})                      # empty ⇒ owner dead
    killer = Spy()
    report = arm.armed_sweep([rec], snap, killer=killer, now=NOW)
    assert killer.calls == [300]
    assert report["killed"] == ["dead"]


def test_persisted_kill_with_degraded_snapshot_kills_nothing(arm):
    """A degraded/None live snapshot ⇒ the armed sweep abstains — uncertainty is
    never license to kill, even at the KILL tier."""
    arm._save_arm_state({"tier": arm.TIER_KILL})
    rec = _rec("dead", pid=300, ct=88.0)
    killer = Spy()
    report = arm.armed_sweep([rec], None, killer=killer, now=NOW)
    assert report["degraded"] is True
    assert killer.calls == []
    assert report["abstained"] == ["dead"]


# ── Tamper-evident arm gate ──────────────────────────────────────────────────

def test_forged_receipt_log_fails_the_gate(arm, monkeypatch):
    """A log that WOULD clear the bar fails once an entry is edited on disk: the
    hash-chain verify rejects the forgery and the gate FAILS."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "2")
    for _ in range(2):
        arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    # Baseline: the honest log clears the bar.
    assert arm.evaluate_arm_gate(arm.TIER_FREEZE, snapshot=good).passed is True

    # Forge: flip a BODY field of the first receipt on disk while KEEPING its
    # stored hash (a real attacker editing the audit log). The recomputed hash no
    # longer matches ⇒ the chain breaks at that link.
    import json
    p = arm.receipts_path()
    lines = p.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[0])
    obj["clean"] = not obj.get("clean", True)      # tamper the body, keep hash
    lines[0] = json.dumps(obj, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, bad = arm.verify_chain()
    assert ok is False and bad == 0
    gate = arm.evaluate_arm_gate(arm.TIER_FREEZE, snapshot=good)
    assert gate.passed is False
    assert "chain" in gate.reason.lower()
    # And arming refuses on the forged numbers.
    out = arm.arm(TOKEN, snapshot=good, now=NOW)
    assert out["ok"] is False
    assert arm.persisted_tier() == arm.TIER_LOG


def test_inflated_stored_aggregate_is_ignored(arm, monkeypatch):
    """A giant 'clean_streak' written into the arm-state file cannot clear the
    bar — the gate recomputes the streak from the verified chain, not the file."""
    import reaper
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "5")
    # Attacker inflates a stored aggregate...
    arm._save_arm_state({"tier": arm.TIER_LOG, "clean_streak": 999,
                         "clean_streak_at_arm": 999})
    # ...but only ONE real clean sweep exists in the chain.
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)

    stats = arm.receipt_stats()
    assert stats.clean_streak == 1                       # recomputed, not 999
    gate = arm.evaluate_arm_gate(arm.TIER_FREEZE, snapshot=_snap(reaper, [], {}))
    assert gate.passed is False and gate.clean_streak == 1
    assert "under bar" in gate.reason


def test_empty_chain_is_valid_but_under_bar(arm):
    """An empty receipt log is a trivially-valid chain that grants zero progress."""
    import reaper
    ok, bad = arm.verify_chain()
    assert ok is True and bad == -1
    gate = arm.evaluate_arm_gate(arm.TIER_FREEZE, snapshot=_snap(reaper, [], {}),
                                 min_sweeps=1)
    assert gate.passed is False and gate.chain_ok is True
