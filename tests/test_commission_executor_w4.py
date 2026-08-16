"""Wave 4 — Anchor reference commission executor (host contract only).

Covers: refuse unconfirmed, auth at launch, launch-intent before spawn,
kill_on_job_close=False, (pid, proc_create_time) identity, durable handback
pair (S6), boot reconcile adopt/fail-by-name, no-token-in-child, substrate
busy surfaces, DEGRADED one-run-at-a-time.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import commission_executor as ce


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "comm-store"
    root.mkdir()
    return root


@pytest.fixture
def worktree(tmp_path):
    wt = tmp_path / "run-wt"
    wt.mkdir()
    return wt


def _confirmed(cid="comm-1", **extra):
    d = {
        "commission_id": cid,
        "confirmed": True,
        "who": {"claimed": "john", "provenance": "claimed_unauthenticated"},
        "skill": "researchPrime",
        "depth": "LITE",
        "step_id": "step-1",
    }
    d.update(extra)
    return d


def test_failure_state_table_complete():
    required = [
        ce.EXEC_SUBSTRATE_MISSING,
        ce.EXEC_REFUSED_UNCONFIRMED,
        ce.EXEC_SUBSTRATE_BUSY,
        ce.EXEC_RUN_DIED,
        ce.EXEC_HANDBACK_MISSING,
        ce.EXEC_RUN_ADOPTED,
        ce.EXEC_AUTH_REFUSED,
        ce.EXEC_DOSSIER_UNREADABLE,
        ce.EXEC_NO_RUNS,
        ce.EXEC_LIVENESS_UNKNOWN,
        ce.LAUNCH_INTENT_STRANDED,
    ]
    for code in required:
        assert code in ce.FAILURE_STATES
        assert ce.FAILURE_STATES[code]["status_code"] == code
        assert ce.FAILURE_STATES[code]["user_text"]


def test_refuse_unconfirmed(store, worktree):
    r = ce.execute_confirmed_commission(
        {"commission_id": "x", "confirmed": False},
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=lambda **k: (_ for _ in ()).throw(AssertionError("must not launch")),
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_REFUSED_UNCONFIRMED
    assert r["pid"] is None


def test_auth_refused_revoked_zero_pid(store, worktree):
    r = ce.execute_confirmed_commission(
        _confirmed(),
        store_root=store,
        worktree=worktree,
        auth_ctx={"token": "secret", "revoked": True},
        expected_token="secret",
        enforce_auth=True,
        launch_fn=lambda **k: (_ for _ in ()).throw(AssertionError("no launch")),
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_AUTH_REFUSED
    assert r["pid"] is None


def test_auth_refused_expired_zero_pid(store, worktree):
    r = ce.execute_confirmed_commission(
        _confirmed(),
        store_root=store,
        worktree=worktree,
        auth_ctx={"token": "secret", "expires_at": 1.0},
        expected_token="secret",
        enforce_auth=True,
        launch_fn=lambda **k: (_ for _ in ()).throw(AssertionError("no launch")),
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_AUTH_REFUSED
    assert r["pid"] is None


def test_auth_refused_wrong_token(store, worktree):
    r = ce.execute_confirmed_commission(
        _confirmed(),
        store_root=store,
        worktree=worktree,
        auth_ctx={"token": "nope"},
        expected_token="secret",
        enforce_auth=True,
        launch_fn=lambda **k: (_ for _ in ()).throw(AssertionError("no launch")),
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_AUTH_REFUSED


def test_launch_intent_before_spawn(store, worktree):
    seen = {}

    def launch_fn(**kwargs):
        # Intent must already exist when spawn runs
        intents = ce.list_launch_intents(store)
        assert len(intents) == 1
        assert intents[0]["status"] == "intent_recorded"
        seen["kill_on_job_close"] = kwargs.get("kill_on_job_close")
        seen["env"] = kwargs.get("env")
        return {
            "job_id": "job-1",
            "pid": 4242,
            "proc_create_time": 1700000000.5,
            "cmdline": ["node", "researchPrime-lite.mjs"],
            "command": ["node", "researchPrime-lite.mjs"],
        }

    r = ce.execute_confirmed_commission(
        _confirmed(),
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=launch_fn,
        command=["node", "researchPrime-lite.mjs"],
    )
    assert r["ok"] is True
    assert r["pid"] == 4242
    assert r["proc_create_time"] == 1700000000.5
    assert seen["kill_on_job_close"] is False
    assert r["kill_on_job_close"] is False
    assert ce.COMMISSION_KILL_ON_JOB_CLOSE is False

    intent = ce.list_launch_intents(store)[0]
    assert intent["status"] == "launched"
    assert intent["pid"] == 4242
    assert intent["kill_on_job_close"] is False


def test_no_token_in_child_env(store, worktree):
    os.environ["ANCHOR_TOKEN"] = "super-secret-token"
    try:
        captured = {}

        def launch_fn(**kwargs):
            captured["env"] = kwargs["env"]
            return {
                "job_id": "j2",
                "pid": 7,
                "proc_create_time": 1.0,
                "command": ["researchPrime"],
            }

        r = ce.execute_confirmed_commission(
            _confirmed("comm-tok"),
            store_root=store,
            worktree=worktree,
            enforce_auth=False,
            launch_fn=launch_fn,
        )
        assert r["ok"] is True
        assert "ANCHOR_TOKEN" not in captured["env"]
        assert ce.assert_no_token_in_env(captured["env"]) is True
    finally:
        os.environ.pop("ANCHOR_TOKEN", None)
        ce.release_one_run_slot("comm-tok")


def test_handback_pair_s6_and_ingestable(worktree):
    body = {
        "schema": "ecgberht-receipt-v0",
        "kind": "handback",
        "as_of": "2026-08-02",
        "active_effort": "t",
        "why_next": "n",
        "grasscatch_why": None,
        "tool_depth_why": "LITE",
        "human_wait": "none",
        "uncertainty_flags": [],
        "client_event_id": "ce-py-1",
        "handback_id": "hb-py-1",
    }
    r = ce.write_handback_pair(worktree, body)
    assert r["ok"] is True
    assert ce.is_ingestable(worktree)
    assert ce.handback_json_path(worktree).is_file()
    assert ce.terminal_marker_path(worktree).is_file()


def test_kill_mid_write_not_ingestable(worktree):
    # Handback only — no marker
    ce._atomic_write_text(
        ce.handback_json_path(worktree),
        json.dumps({"schema": "ecgberht-receipt-v0", "kind": "handback"}) + "\n",
    )
    assert ce.is_ingestable(worktree) is False


def test_boot_reconcile_adopts_complete_pair_once(store, worktree):
    ce.write_launch_intent(
        store,
        commission_id="c-adopt",
        who="john",
        worktree=worktree,
        confirmed=True,
    )
    ce.update_launch_intent(
        store, "c-adopt", status="launched", pid=1, proc_create_time=1.0
    )
    ce.write_handback_pair(
        worktree,
        {
            "schema": "ecgberht-receipt-v0",
            "kind": "handback",
            "as_of": "2026-08-02",
            "active_effort": "a",
            "why_next": "b",
            "grasscatch_why": None,
            "tool_depth_why": "LITE",
            "human_wait": "none",
            "uncertainty_flags": [],
            "client_event_id": "ce-adopt-1",
            "handback_id": "hb-adopt-1",
        },
    )
    r1 = ce.boot_reconcile(store)
    adopted = [x for x in r1["results"] if x["status_code"] == ce.EXEC_RUN_ADOPTED]
    assert len(adopted) == 1
    assert adopted[0]["duplicate"] is False

    r2 = ce.boot_reconcile(store)
    adopted2 = [x for x in r2["results"] if x["status_code"] == ce.EXEC_RUN_ADOPTED]
    assert len(adopted2) == 1
    assert adopted2[0]["duplicate"] is True


def test_boot_reconcile_names_dead_and_missing(store, worktree):
    ce.write_launch_intent(
        store,
        commission_id="c-dead",
        who="john",
        worktree=worktree,
        confirmed=True,
    )
    ce.update_launch_intent(
        store,
        "c-dead",
        status="launched",
        pid=999999,  # almost certainly dead
        proc_create_time=1.0,
    )
    r = ce.boot_reconcile(store)
    codes = {x["status_code"] for x in r["results"]}
    assert ce.EXEC_RUN_DIED in codes or ce.EXEC_HANDBACK_MISSING in codes
    assert ce.EXEC_RUN_ADOPTED not in codes or all(
        x.get("duplicate") for x in r["results"] if x["status_code"] == ce.EXEC_RUN_ADOPTED
    )


def test_boot_reconcile_stranded_intent(store, worktree):
    ce.write_launch_intent(
        store,
        commission_id="c-strand",
        who="john",
        worktree=worktree,
        confirmed=True,
    )
    # status remains intent_recorded, no pid
    r = ce.boot_reconcile(store)
    assert any(x["status_code"] == ce.LAUNCH_INTENT_STRANDED for x in r["results"])


def test_substrate_busy_lane_busy_error(store, worktree):
    class LaneBusyError(RuntimeError):
        def __init__(self, reason, holder=None):
            super().__init__(reason)
            self.reason = reason
            self.holder = holder

    def launch_fn(**kwargs):
        raise LaneBusyError("folder-build-lock", holder="other-job")

    # release any leftover slot from prior tests in this process
    ce.release_one_run_slot("c-busy")
    ce._active_commission_id = None

    r = ce.execute_confirmed_commission(
        _confirmed("c-busy"),
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=launch_fn,
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_SUBSTRATE_BUSY
    assert "folder-build-lock" in str(r.get("reason"))


def test_attach_handback_to_dossier(store, worktree):
    ce.write_handback_pair(
        worktree,
        {
            "schema": "ecgberht-receipt-v0",
            "kind": "handback",
            "as_of": "2026-08-02",
            "active_effort": "a",
            "why_next": "b",
            "grasscatch_why": None,
            "tool_depth_why": "LITE",
            "human_wait": "none",
            "uncertainty_flags": [],
            "client_event_id": "ce-d",
        },
    )
    dossier = store / "dossier" / "c1"
    r = ce.attach_handback_to_dossier(dossier, worktree, commission_id="c1")
    assert r["ok"] is True
    assert Path(r["dossier_handback_path"]).is_file()


def test_process_identity_never_pid_alone():
    # pid with no create_time while "alive" probe may vary — without create_time → unknown
    # Use a definitely-dead pid
    status = ce.process_identity_alive(999999991, 1.0)
    assert status in ("dead", "unknown")


def test_contract_version_pinned():
    assert ce.CONTRACT_VERSION == "1.0.0"
    assert ce.HANDBACK_JSON_NAME == "handback.json"
    assert ce.TERMINAL_MARKER_NAME == "TERMINAL.marker"


def test_evidence_never_sets_commissionable(store, worktree):
    def launch_fn(**kwargs):
        return {
            "job_id": "j3",
            "pid": 3,
            "proc_create_time": 3.0,
            "command": ["researchPrime"],
        }

    ce.release_one_run_slot("c-ev")
    ce._active_commission_id = None
    r = ce.execute_confirmed_commission(
        _confirmed("c-ev"),
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=launch_fn,
    )
    assert r["ok"] is True
    assert "commissionable" not in r["evidence"]


def test_spawn_cap_and_lane_busy_named(store, worktree):
    """Substrate refusals surface by name (LaneBusyError / spawn-cap / folder-build-lock)."""

    class LaneBusyError(RuntimeError):
        def __init__(self, reason, holder=None):
            super().__init__(reason)
            self.reason = reason
            self.holder = holder

    ce.release_one_run_slot("c-cap")
    ce._active_commission_id = None

    def launch_spawn_cap(**kwargs):
        raise LaneBusyError("spawn-cap-reached", holder=None)

    r = ce.execute_confirmed_commission(
        _confirmed("c-cap"),
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=launch_spawn_cap,
    )
    assert r["ok"] is False
    assert r["status_code"] == ce.EXEC_SUBSTRATE_BUSY
    assert "spawn-cap" in str(r.get("reason"))


def test_kill_on_job_close_false_is_recorded_decision():
    assert ce.COMMISSION_KILL_ON_JOB_CLOSE is False
    assert "outlive" in ce.COMMISSION_KILL_ON_JOB_CLOSE_REASON.lower()


def test_child_env_strips_capability_keys():
    env = ce.child_env(
        {
            "PATH": "/usr/bin",
            "ANCHOR_TOKEN": "secret",
            "ANCHOR_CAPABILITY": "cap",
            "OTHER": "ok",
        }
    )
    assert "ANCHOR_TOKEN" not in env
    assert "ANCHOR_CAPABILITY" not in env
    assert env["OTHER"] == "ok"
    assert ce.assert_no_token_in_env(env) is True


def test_restart_survival_kill_on_job_close_false_recorded_on_intent(store, worktree):
    """Commission intents permanently record kill_on_job_close=False so a
    service restart does not re-arm Job-Object kill for in-flight runs.

    This is stronger than a prose claim: the durable intent file is what boot
    reconcile reads after nssm restart.
    """
    seen = {}

    def launch_fn(**kwargs):
        seen["kill_on_job_close"] = kwargs.get("kill_on_job_close")
        return {
            "job_id": "job-restart",
            "pid": 55555,
            "proc_create_time": 1700000100.0,
            "command": ["node", "researchPrime", "--lite"],
        }

    r = ce.execute_confirmed_commission(
        _confirmed("c-restart"),
        store_root=store,
        worktree=worktree,
        enforce_auth=False,
        launch_fn=launch_fn,
        command=["node", "researchPrime", "--lite"],
    )
    assert r["ok"] is True
    assert seen["kill_on_job_close"] is False
    assert r["kill_on_job_close"] is False

    intent = ce.list_launch_intents(store)[0]
    assert intent["kill_on_job_close"] is False
    assert intent["status"] == "launched"
    # Durable on disk — boot after restart can prove the recorded decision
    on_disk = json.loads(ce.launch_intent_path(store, "c-restart").read_text(encoding="utf-8"))
    assert on_disk["kill_on_job_close"] is False
    assert "outlive" in (on_disk.get("kill_on_job_close_reason") or "").lower()


def test_boot_reconcile_after_restart_adopts_complete_handback(store, worktree):
    """Simulated service restart: intent had kill_on_job_close=False, run
    finished with a complete handback pair → ADOPT exactly once; a second
    boot is idempotent (duplicate), never silent absorb.
    """
    ce.write_launch_intent(
        store,
        commission_id="c-survived",
        who={"claimed": "john", "provenance": "claimed_unauthenticated"},
        worktree=worktree,
        confirmed=True,
    )
    ce.update_launch_intent(
        store,
        "c-survived",
        status="launched",
        pid=424242,
        proc_create_time=1700000200.0,
        kill_on_job_close=False,
        kill_on_job_close_reason=ce.COMMISSION_KILL_ON_JOB_CLOSE_REASON,
    )
    ce.write_handback_pair(
        worktree,
        {
            "schema": "ecgberht-receipt-v0",
            "kind": "handback",
            "as_of": "2026-08-02",
            "active_effort": "restart-survival",
            "why_next": "adopt after service restart",
            "grasscatch_why": None,
            "tool_depth_why": "LITE",
            "human_wait": "none",
            "uncertainty_flags": [],
            "client_event_id": "ce-survived-1",
            "handback_id": "hb-survived-1",
        },
    )

    # First boot after "restart"
    r1 = ce.boot_reconcile(store)
    adopted = [x for x in r1["results"] if x["status_code"] == ce.EXEC_RUN_ADOPTED]
    assert len(adopted) == 1
    assert adopted[0]["duplicate"] is False
    assert adopted[0]["client_event_id"] == "ce-survived-1"

    # Second boot — idempotent
    r2 = ce.boot_reconcile(store)
    adopted2 = [x for x in r2["results"] if x["status_code"] == ce.EXEC_RUN_ADOPTED]
    assert len(adopted2) == 1
    assert adopted2[0]["duplicate"] is True


def test_boot_reconcile_names_dead_run_after_restart_not_absorbed(store, worktree):
    """Restart-adjacent death with no handback is NAMED (EXEC_RUN_DIED /
    EXEC_HANDBACK_MISSING) — never silently dropped from results.
    """
    ce.write_launch_intent(
        store,
        commission_id="c-died-restart",
        who="john",
        worktree=worktree,
        confirmed=True,
    )
    ce.update_launch_intent(
        store,
        "c-died-restart",
        status="launched",
        pid=999999991,  # not a live process
        proc_create_time=1.0,
        kill_on_job_close=False,
    )
    r = ce.boot_reconcile(store)
    assert r["results"], "must not silently absorb"
    codes = {x["status_code"] for x in r["results"]}
    assert ce.EXEC_RUN_DIED in codes or ce.EXEC_HANDBACK_MISSING in codes
    # never adopted without a pair
    assert all(
        x.get("duplicate") or x["status_code"] != ce.EXEC_RUN_ADOPTED
        for x in r["results"]
    )
