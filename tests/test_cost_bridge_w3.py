"""Wave 3 gate — bridge job cost onto the effort record.

crucible-improve-followup (2026-07-01), Wave 3.

Per-project / per-effort rollups read a `cost` block off the effort
pointer-record. The ONLY writer of that block (`finalize_effort` ->
`attach_cost`) had no production caller, so the runner captured cost onto the
JOB record but never bridged it to the EFFORT record — hence all-zero rollups.
`job_runner._finalize` now bridges the captured cost onto the effort record for
launch_lane jobs (those carrying project_id + folder_path) that captured a
result envelope.
"""
import importlib
from pathlib import Path

import pytest

ENVELOPE = {
    "type": "result",
    "total_cost_usd": 0.42,
    "duration_ms": 5000,
    "usage": {"input_tokens": 100, "output_tokens": 200},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "session_registry",
                "sessions", "effort_history", "summarizer", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Cost", str(folder), scaffold=False)["id"]
    return {"pid": pid, "folder": str(folder)}


def _job_rec(jid, **over):
    rec = {"job_id": jid, "lane": "research", "status": "running",
           "started_at": 1.0, "exit_code": None, "session_id": None,
           "backend": "claude", "cost": None}
    rec.update(over)
    return rec


def test_finalize_bridges_cost_onto_effort_record(env):
    """The direct fix: a finished launch_lane job stamps its captured cost onto
    the effort pointer-record (previously never written)."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-cost-1"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0, result_envelope=ENVELOPE)

    eff = eh.load_effort(folder, pid, "research", jid)
    assert eff is not None, "bridge must create/update the effort record"
    cost = eff.get("cost") or {}
    assert cost.get("total_cost_usd") == 0.42
    assert cost.get("duration_ms") == 5000
    assert (cost.get("total_tokens") or 0) > 0, "tokens must be bridged"


def test_no_project_identity_skips_bridge_without_error(env):
    """A job with no project_id/folder_path (a bare launch()) finalizes exactly
    as before: no bridge, no effort record, no error."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-nobridge"
    jr._write_record(_job_rec(jid))  # no project_id / folder_path
    jr._finalize(jid, 0, result_envelope=ENVELOPE)  # must not raise
    assert eh.load_effort(folder, pid, "research", jid) is None


def test_no_cost_envelope_writes_no_effort(env):
    """No result envelope (no captured cost) -> the bridge does not fire (guard
    on rec['cost']); a launch job with no cost is not fabricated as zero-cost."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-nocost"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0)  # no envelope -> rec['cost'] stays falsy
    assert eh.load_effort(folder, pid, "research", jid) is None


def test_rollup_nonzero_after_bridge(env):
    """End-to-end, faithful to production: `launch_guarded` stamps
    project_id/folder_path on the job record, then `_finalize` bridges cost onto
    a fresh effort record. That record is RUN-provenance (no source=discovered),
    so `project_effort_rollup` — the real reader — reports non-zero (was always
    0). No pre-seeded effort: the bridge ALONE lights up the rollup."""
    import effort_history as eh
    import job_runner as jr
    pid, folder = env["pid"], env["folder"]
    jid = "job-cost-2"
    jr._write_record(_job_rec(jid, project_id=pid, folder_path=folder))
    jr._finalize(jid, 0, result_envelope=ENVELOPE)

    roll = eh.project_effort_rollup(pid)
    assert roll["tokens"] > 0 and roll["cost_usd"] > 0.0, \
        f"rollup still zero after bridge alone: {roll}"


def test_chatgpt_subscription_null_and_labels_survive_job_to_effort_and_rollup(env):
    import anchor_gui
    import codex_adapter as ca
    import effort_history as eh
    import job_runner as jr

    pid, folder = env["pid"], env["folder"]
    jid = "job-chatgpt-subscription"
    prompt = "subscription cost must remain unknown"
    parsed = {
        "thread_id": "thread-subscription",
        "usage": {"input_tokens": 90, "cached_input_tokens": 40,
                  "output_tokens": 10},
        "event_count": 3,
        "malformed_count": 0,
    }
    executable = Path(ca.resolve_codex_cmd()).resolve()
    provenance = ca.inspect_executable(str(executable))
    assert provenance.get("ok") is True
    preflight = {
        "executable_path": str(executable),
        "executable_fingerprint": provenance["executable_fingerprint"],
        "executable_provenance_verified": True,
        "executable_provenance_kind": provenance["executable_provenance_kind"],
        "executable_signer_subject": provenance.get("executable_signer_subject"),
        "executable_signer_certificate_sha256": provenance.get(
            "executable_signer_certificate_sha256"),
        "signer_image_binding_verified": bool(
            provenance.get("signer_image_binding_verified")),
        "signature_revocation_freshness": provenance[
            "signature_revocation_freshness"],
        "executable_handle_guarded_through_spawn": True,
        "preexecution_child_image_attested": False,
        "transport_actual": "codex-cli",
        "cli_version": "codex-cli test",
        "auth_kind": "chatgpt_subscription",
        "auth_probe_at": "2026-08-30T15:00:00+00:00",
        "subscription_auth": True,
        "model_capability_verified": True,
        "ultra_capability_verified": True,
        "codex_home": ca.subscription_only_env()["CODEX_HOME"],
        "user_config_ignored": True,
        "critical_overrides_enforced": True,
        "config_guard_verified": True,
        "runtime_guard_rechecked": True,
        "child_env_allowlist_verified": True,
        "rules_ignored": True,
        "agents_disabled": True,
        "network_disabled": True,
        "extra_writable_roots_disabled": True,
        "hosted_tools_disabled": True,
        "mcp_servers_disabled": True,
        "projects_table_replaced": True,
        "api_key_env_scrubbed": True,
    }
    if ca.os.name == "nt":
        preflight.update(
            containment_kind="windows_job", complete_tree_containment=True,
            windows_job_policy_verified=True,
            windows_job_assignment_verified=True,
            windows_job_membership_verified=True,
            windows_process_handle_verified=True,
            windows_primary_thread_verified=True,
            windows_process_resumed=True,
            windows_execution_possible=True,
            windows_job_empty_verified=True,
            root_exit_verified=True,
        )
    else:
        preflight.update(
            containment_kind="posix_process_group_degraded",
            complete_tree_containment=False,
        )
    preflight.update(
        preflight_probe_count=3,
        preflight_containment_kind=(
            "windows_job" if ca.os.name == "nt"
            else "posix_process_group_degraded"),
        preflight_complete_tree_containment=(ca.os.name == "nt"),
        preflight_no_inference_verified=True,
        preflight_no_network_intent_verified=True,
        preflight_output_limits_verified=True,
        preflight_output_drain_verified=True,
        preflight_root_exit_verified=True,
        preflight_windows_job_policy_verified=(ca.os.name == "nt"),
        preflight_windows_job_assignment_verified=(ca.os.name == "nt"),
        preflight_windows_job_membership_verified=(ca.os.name == "nt"),
        preflight_windows_process_handle_verified=(ca.os.name == "nt"),
        preflight_windows_primary_thread_verified=(ca.os.name == "nt"),
        preflight_windows_process_resumed=(ca.os.name == "nt"),
        preflight_windows_job_empty_verified=(ca.os.name == "nt"),
        preflight_process_group_kill_verified=None,
    )
    receipt = ca.build_receipt(
        status="success", prompt=prompt, sandbox="read-only",
        preflight=preflight, parsed=parsed, exit_code=0, seat_started=True,
        expected_artifact_paths=[], artifact_hashes={},
        artifact_contract_verified=True, output_drain_verified=True,
        output_limits_verified=True, output_eof_verified=True,
        stdin_write_verified=True, stdin_close_verified=True,
        native_stdout_bytes=64, native_stderr_bytes=0,
    )
    envelope = ca.normalized_result("ok", receipt, 1234, False)
    jr._write_record(_job_rec(
        jid, backend="chatgpt", project_id=pid, folder_path=folder,
        relaunch_spec={
            "prompt": prompt, "permission_mode": "plan",
            "output_dir": folder,
            "expected_artifacts": [],
        },
    ))
    jr._finalize(jid, 0, result_envelope=envelope)

    job = jr.load_record(jid)
    assert job["status"] == jr.STATUS_DONE
    assert job["cost"]["total_cost_usd"] is None
    assert job["cost"]["billing_mode"] == "subscription"
    assert job["cost"]["cost_state"] == "subscription_covered"

    effort = eh.load_effort(folder, pid, "research", jid)
    cost = effort["cost"]
    assert cost["total_cost_usd"] is None
    assert cost["billing_mode"] == "subscription"
    assert cost["cost_state"] == "subscription_covered"
    assert cost["cached_input_tokens"] == 40

    roll = eh.project_effort_rollup(pid, folder_path=folder)
    assert roll["cost_usd"] is None
    assert roll["cost_states"] == ["subscription_covered"]
    assert roll["unpriced_subscription_count"] == 1
    rendered = anchor_gui._fmt_rollup_line(roll)
    assert "(subscription)" in rendered
    assert "$0.00" not in rendered
