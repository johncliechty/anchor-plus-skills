"""foundry-v2 Wave 11 — Phase 8: safety before scale.

Proves the Wave-11 done-when:
  (a) the reaper is ARMED TO FREEZE within its safety envelope — the arm goes
      through the receipt-gated ladder (chain-verify + clean-sweep bar +
      fresh live probe), targets the FREEZE rung ONLY (this path can never
      arm KILL), and armed-at-FREEZE never kills on uncertainty: a
      degraded/None snapshot abstains everything and a confirmed-dead-owner
      orphan is FROZEN (reversibly), never killed;
  (b) the 2026-07-05 fail-deadly finding is RETIRED or explicitly bounded —
      ``recheck_fail_deadly`` passes on the live tree, re-opens on an
      injected regression, and an OPEN finding refuses the arm with no state
      change;
  (c) the per-host concurrent-skill-run budget is enforced IN the generic
      runner: an over-budget fan-out is refused honestly (and journaled) and
      a budget refusal never burns a single-use mutate confirm token;
  (d) zombie-hunter stays a NATIVE built-in — never a manifest-registered
      skill action (the runner refuses such a manifest; the boot wiring and
      in-process modules stay).

Hermetic: temp ``ANCHOR_DATA_DIR`` + injected probes/spies/executors — never
a real kill/freeze/process, never the live ``.anchor`` store, never ``:8777``.
Stdlib + pytest only.
"""
import importlib
import threading
from pathlib import Path

import pytest

import foundry_decisions as _fd
import foundry_journal as _fj


NOW = 4_000_000.0


class FakeProbe:
    """A creation-time-only probe. Missing entry ⇒ the PID probes DEAD."""

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
def rig(tmp_path, monkeypatch):
    """Temp data dir + freshly-reloaded reaper stack + foundry_safety."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # No token configured → auth is disabled and the GATE is what is tested
    # (the reaper control-plane test file covers auth itself).
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
    import foundry_safety
    importlib.reload(foundry_safety)
    return foundry_safety


def _rec(session_id, *, pid, ct, created_at, status="running"):
    return {
        "session_id": session_id,
        "status": status,
        "pid": pid,
        "proc_create_time": ct,
        "crypt_token": "tok",
        "created_at": created_at,
        "worktree_path": "",
    }


def _dead_orphan(sid="orphan", pid=100, ct=50.0):
    """A confirmed-dead-owner candidate, past the boot-grace window."""
    return _rec(sid, pid=pid, ct=ct, created_at=NOW - 10_000)


def _snap(reaper, records, times):
    return reaper.build_snapshot(
        attached_pty_ids=set(), records=records,
        job_active=lambda _s: False, probe=FakeProbe(times), now=NOW)


# ═════════════════════════════════════════════════════════════════════════════
# (a) The reaper armed to FREEZE within its safety envelope
# ═════════════════════════════════════════════════════════════════════════════

def test_arm_reaper_to_freeze_arms_through_the_gate(rig, monkeypatch):
    """arm_reaper_to_freeze reaches FREEZE only via the receipt-gated ladder,
    and reports the fail-deadly re-check that preceded the arm."""
    import reaper
    import reaper_arming as arm
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "2")
    for _ in range(2):
        arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    out = rig.arm_reaper_to_freeze("tok", snapshot=good, now=NOW)
    assert out["ok"] is True and out["changed"] is True
    assert out["tier"] == arm.TIER_FREEZE
    assert out["target_tier"] == arm.TIER_FREEZE
    assert out["fail_deadly"]["retired"] is True
    assert arm.persisted_tier() == arm.TIER_FREEZE
    assert arm.effective_tier() == arm.TIER_FREEZE


def test_arm_refused_under_bar_with_no_state_change(rig, monkeypatch):
    """The safety envelope is not weakened: an under-bar arm is refused and
    the tier stays LOG."""
    import reaper
    import reaper_arming as arm
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "5")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    out = rig.arm_reaper_to_freeze("tok", snapshot=good, now=NOW)
    assert out["ok"] is False and out["changed"] is False
    assert arm.persisted_tier() == arm.TIER_LOG


def test_arm_path_can_never_reach_the_kill_rung(rig, monkeypatch):
    """arm_reaper_to_freeze targets FREEZE only: re-arming once armed never
    creeps up the ladder — the persisted tier can never become KILL here."""
    import reaper
    import reaper_arming as arm
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    first = rig.arm_reaper_to_freeze("tok", snapshot=good, now=NOW)
    assert first["ok"] is True
    assert arm.persisted_tier() == arm.TIER_FREEZE
    again = rig.arm_reaper_to_freeze("tok", snapshot=good, now=NOW)
    assert again["ok"] is True
    assert again["tier"] == arm.TIER_FREEZE
    assert arm.persisted_tier() == arm.TIER_FREEZE   # still FREEZE, never KILL


def test_armed_freeze_never_kills_on_uncertainty(rig):
    """Armed at FREEZE, an uncertain (None-snapshot) sweep ABSTAINS everything
    — no freeze, no kill, no process touched."""
    import reaper_arming as arm
    arm._save_arm_state({"tier": arm.TIER_FREEZE})
    rec = _dead_orphan()
    freezer, killer = Spy(), Spy()
    report = arm.armed_sweep([rec], None, freezer=freezer, killer=killer,
                             now=NOW)
    assert report["degraded"] is True
    assert report["abstained"] == ["orphan"]
    assert report["frozen"] == [] and report["killed"] == []
    assert freezer.calls == [] and killer.calls == []


def test_armed_freeze_freezes_a_dead_owner_orphan_never_kills(rig):
    """Armed at FREEZE, a confirmed-dead-owner orphan is FROZEN (reversible,
    watchdog-bounded) — the killer is NEVER called at this rung."""
    import reaper
    import reaper_arming as arm
    import freeze_state
    arm._save_arm_state({"tier": arm.TIER_FREEZE})
    rec = _dead_orphan(pid=100)
    snap = _snap(reaper, [rec], {})     # empty probe ⇒ owner confirmed dead
    freezer, killer = Spy(), Spy()
    report = arm.armed_sweep([rec], snap, freezer=freezer, killer=killer,
                             now=NOW)
    assert report["tier"] == arm.TIER_FREEZE
    assert report["frozen"] == ["orphan"]
    assert report["killed"] == []
    assert freezer.calls == [100] and killer.calls == []
    entry = freeze_state.get_entry("orphan")
    assert entry is not None and entry.thaw_deadline is not None


# ═════════════════════════════════════════════════════════════════════════════
# (b) The 2026-07-05 fail-deadly finding — retired or explicitly bounded
# ═════════════════════════════════════════════════════════════════════════════

def test_recheck_fail_deadly_is_retired_on_the_live_tree(rig):
    """The re-check passes against the real call-site source + the live
    behavioral probe: the finding is RETIRED."""
    check = rig.recheck_fail_deadly()
    assert check["retired"] is True
    assert check["problems"] == []
    assert "2026-07-05" in check["finding"]
    assert list(check["checked_patterns"]) == list(rig.RETIRED_PATTERNS)


def test_recheck_reopens_on_an_injected_regression(rig):
    """A retired fallback pattern re-appearing in the call-site source
    RE-OPENS the finding."""
    bad_src = (
        'verdict = "kill" if sid not in live_ids else "alive"\n'
        "reaper.owner_ids_or_abstain(snap, running)\n"
        "reaper.live_pid_ids(pids)\n"
    )
    check = rig.recheck_fail_deadly(source=bad_src)
    assert check["retired"] is False
    assert any("re-appeared" in p for p in check["problems"])


def test_recheck_flags_a_missing_abstain_safe_replacement(rig):
    """Losing the abstain-safe provider ALSO re-opens the finding — retirement
    means the safe replacement stays, not merely that the bad pattern left."""
    check = rig.recheck_fail_deadly(source="# nothing here\n")
    assert check["retired"] is False
    assert any("abstain-safe replacement missing" in p
               for p in check["problems"])


def test_live_arm_endpoint_routes_through_the_wave11_path():
    """Consumption-path gate: the live ``/api/rnd/reaper_arm`` endpoint arms
    through ``foundry_safety.arm_reaper_to_freeze`` (fail-deadly re-check
    FIRST), never through a bare ``reaper_arming.arm`` call."""
    src = (Path(__file__).resolve().parents[1] / "anchor_gui.py").read_text(
        encoding="utf-8")
    assert "_fsafety.arm_reaper_to_freeze(provided)" in src, \
        "the arm endpoint must route through the Wave-11 sanctioned path"
    assert "out = _arm.arm(provided)" not in src, \
        "the arm endpoint bypasses the Wave-11 fail-deadly re-check"


def test_an_open_finding_refuses_the_arm(rig, monkeypatch):
    """With the fail-deadly finding OPEN the arm is refused outright — even
    when the ladder's own gate would pass — with NO state change."""
    import reaper
    import reaper_arming as arm
    monkeypatch.setenv("ANCHOR_REAPER_ARM_MIN_SWEEPS", "1")
    arm.record_sweep(arm.TIER_LOG, clean=True, abstained=False, now=NOW)
    good = _snap(reaper, [], {})
    open_finding = {"retired": False, "problems": ["injected regression"]}
    out = rig.arm_reaper_to_freeze("tok", snapshot=good, now=NOW,
                                   recheck=open_finding)
    assert out["ok"] is False and out["changed"] is False
    assert "fail-deadly" in out["error"]
    assert out["fail_deadly"] is open_finding
    assert arm.persisted_tier() == arm.TIER_LOG      # no state change


# ═════════════════════════════════════════════════════════════════════════════
# (c) The per-host concurrent-skill-run budget, enforced IN the generic runner
# ═════════════════════════════════════════════════════════════════════════════

def _skill_dir(tmp_path, name="demo"):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text("# %s protocol\n" % name, encoding="utf-8")
    return d


def _manifest(skill, skill_dir, **over):
    m = {
        "skill": skill,
        "skill_dir": str(skill_dir),
        "op_kind": "run",
        # Never spawned: every test injects an executor.
        "host_cmd": "never-spawned-host --stub",
        "output_contract": {"format": "json",
                            "required_keys": ["schema", "verdict"]},
        "panel": {"title": "W11 %s" % skill},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    m.update(over)
    return m


_OK_OUTPUT = {"schema": "stub-v1", "verdict": "ok"}


@pytest.fixture
def runner():
    """skill_runner with the in-flight budget counter reset around the test."""
    import skill_runner as sr
    with sr._INFLIGHT_LOCK:
        sr._INFLIGHT["count"] = 0
    yield sr
    with sr._INFLIGHT_LOCK:
        sr._INFLIGHT["count"] = 0


def test_concurrency_budget_default_and_override(runner, monkeypatch):
    monkeypatch.delenv(runner.MAX_CONCURRENT_ENV, raising=False)
    assert runner.concurrency_budget() == runner.DEFAULT_MAX_CONCURRENT
    monkeypatch.setenv(runner.MAX_CONCURRENT_ENV, "7")
    assert runner.concurrency_budget() == 7
    # Non-positive / junk values fall back to the default (floor 1).
    monkeypatch.setenv(runner.MAX_CONCURRENT_ENV, "0")
    assert runner.concurrency_budget() == runner.DEFAULT_MAX_CONCURRENT
    monkeypatch.setenv(runner.MAX_CONCURRENT_ENV, "junk")
    assert runner.concurrency_budget() == runner.DEFAULT_MAX_CONCURRENT


def test_over_budget_fanout_refused_and_journaled(runner, tmp_path,
                                                  monkeypatch):
    """With the budget saturated, one more dispatch is REFUSED honestly
    (never queued), the refusal is journaled, and the slots drain back."""
    monkeypatch.setenv(runner.MAX_CONCURRENT_ENV, "2")
    d = _skill_dir(tmp_path)
    dispatch = runner.build_dispatch([_manifest("demo", d)])

    release = threading.Event()
    running = threading.Semaphore(0)

    def blocking_executor(entry, payload):
        running.release()                 # prove this op holds a slot
        assert release.wait(timeout=30)
        return dict(_OK_OUTPUT)

    results = {}

    def _run(key):
        results[key] = runner.run_op(dispatch, "demo",
                                     executor=blocking_executor)

    t1 = threading.Thread(target=_run, args=("a",))
    t2 = threading.Thread(target=_run, args=("b",))
    t1.start()
    t2.start()
    assert running.acquire(timeout=30) and running.acquire(timeout=30)
    assert runner.inflight_runs() == 2    # the budget is saturated

    refused = runner.run_op(dispatch, "demo",
                            executor=lambda e, p: dict(_OK_OUTPUT))
    assert refused["ok"] is False
    assert refused["outcome"] == "refused" and refused["refused"] is True
    assert str(refused["reason"]).startswith("concurrency-budget-exceeded")

    release.set()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert results["a"]["ok"] is True and results["b"]["ok"] is True
    assert runner.inflight_runs() == 0    # every slot released

    # The refusal journaled like every other op: 3 dispatches ⇒ 3 entries,
    # one of them the budget refusal.
    entries = sorted((d / "journal").glob("*.md"))
    assert len(entries) == 3
    reasons = []
    for p in entries:
        parsed = _fj.parse_entry(p.read_text(encoding="utf-8"))
        assert _fj.validate_entry(parsed) == []
        reasons.append(str(parsed["outcome_linkage"].get("reason") or ""))
    assert any(r.startswith("concurrency-budget-exceeded") for r in reasons)


def test_budget_refusal_never_burns_a_confirm_token(runner, tmp_path,
                                                    monkeypatch):
    """The budget is checked BEFORE the mutate gate: an over-budget mutate is
    refused for BUDGET (not token) and its single-use confirm token survives
    to authorize the retry."""
    monkeypatch.setenv(runner.MAX_CONCURRENT_ENV, "1")
    d_run = _skill_dir(tmp_path, "blocker")
    d_mut = _skill_dir(tmp_path, "mut")
    dispatch = runner.build_dispatch([
        _manifest("blocker", d_run),
        _manifest("mut", d_mut, op_kind="mutate", write_scope=[str(d_mut)]),
    ])
    token = runner.issue_confirm_token("mut")

    release = threading.Event()
    running = threading.Semaphore(0)

    def blocking_executor(entry, payload):
        running.release()
        assert release.wait(timeout=30)
        return dict(_OK_OUTPUT)

    holder = {}

    def _hold():
        holder["res"] = runner.run_op(dispatch, "blocker",
                                      executor=blocking_executor)

    t = threading.Thread(target=_hold)
    t.start()
    assert running.acquire(timeout=30)
    assert runner.inflight_runs() == 1    # the single slot is held

    refused = runner.run_op(
        dispatch, "mut", confirm_token=token,
        write_targets=[str(d_mut / "out.txt")],
        executor=lambda e, p: dict(_OK_OUTPUT))
    assert refused["outcome"] == "refused"
    assert str(refused["reason"]).startswith("concurrency-budget-exceeded")

    release.set()
    t.join(timeout=30)
    assert holder["res"]["ok"] is True

    # The token was NOT burned by the budget refusal — it still authorizes.
    ok = runner.run_op(
        dispatch, "mut", confirm_token=token,
        write_targets=[str(d_mut / "out.txt")],
        executor=lambda e, p: dict(_OK_OUTPUT))
    assert ok["ok"] is True and ok["outcome"] == "done"


# ═════════════════════════════════════════════════════════════════════════════
# (d) Zombie-hunter stays a NATIVE built-in — never a manifest skill action
# ═════════════════════════════════════════════════════════════════════════════

def test_native_builtins_declared_in_the_decision_module():
    assert "zombie_hunter" in _fd.NATIVE_BUILTINS
    assert "reaper" in _fd.NATIVE_BUILTINS
    assert "reaper_arming" in _fd.NATIVE_BUILTINS
    assert _fd.NATIVE_BUILTINS_TRACE == (_fd.NS_SAFETY_ENVELOPE,)


def test_runner_refuses_a_manifest_registered_reaper(runner, tmp_path):
    """A manifest that tries to register the reaper family as a skill action
    is refused at declare time — name-normalized (case + '-'/'_')."""
    d = _skill_dir(tmp_path, "zh")
    for name in ("zombie_hunter", "zombie-hunter", "Zombie-Hunter", "reaper"):
        problems = runner.validate_manifest(_manifest(name, d))
        assert any("native built-in" in p for p in problems), name
        with pytest.raises(ValueError):
            runner.build_dispatch([_manifest(name, d)])


def test_reaper_is_native_builtin_report(rig):
    """The honest native-built-in report: modules import, the boot daemon
    starts the hunter natively, and the runner refuses the manifest names."""
    report = rig.reaper_is_native_builtin()
    assert report["native"] is True
    assert report["problems"] == []
