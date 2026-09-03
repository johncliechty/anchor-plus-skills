"""ChatGPT coding-family routing through Anchor's headless research seam."""

import importlib
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
FAKE_CODEX_ADAPTER = (
    Path(__file__).resolve().parent / "fake_codex_adapter_unicode.py"
).as_posix()


@pytest.fixture
def stack(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "%s %s" % (sys.executable, FAKE))
    monkeypatch.delenv("ANCHOR_CODEX_ADAPTER", raising=False)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_CHATGPT_AVAILABLE", "1")
    monkeypatch.setenv("CODING_FAMILY", "gemini")
    monkeypatch.setenv("REVIEW_FAMILY", "grok")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")

    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    anchor_settings.save_settings(
        default_cli="claude", coding_family="chatgpt", review_family="claude",
    )
    import session_registry
    importlib.reload(session_registry)
    import job_runner
    importlib.reload(job_runner)
    monkeypatch.setattr(job_runner, "CODEX_ADAPTER_PATH", FAKE_CODEX_ADAPTER)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    import rnd_terminal
    importlib.reload(rnd_terminal)
    yield {
        "settings": anchor_settings,
        "sessions": session_registry,
        "jobs": job_runner,
        "registry": rnd_registry,
        "lanes": lanes,
        "rnd_terminal": rnd_terminal,
        "tmp": tmp_path,
    }
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            job_runner.cancel(rec["job_id"])
    job_runner._reset_live_table_for_tests()


def _project(stack, name="ChatGPT project"):
    folder = stack["tmp"] / "project"
    folder.mkdir(exist_ok=True)
    return stack["registry"].add_project(name, str(folder))


def _trusted_preflight(jobs, *, subscription_auth=True):
    executable = Path(jobs._codex.resolve_codex_cmd()).resolve()
    provenance = jobs._codex.inspect_executable(str(executable))
    assert provenance.get("ok") is True
    ready = bool(subscription_auth)
    preflight = {
        "transport_actual": "codex-cli",
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
        "executable_handle_guarded_through_spawn": ready,
        "preexecution_child_image_attested": False,
        "cli_version": "codex-cli test",
        "auth_kind": ("chatgpt_subscription" if subscription_auth else None),
        "auth_probe_at": "2026-08-30T15:00:00+00:00",
        "subscription_auth": bool(subscription_auth),
        "model_capability_verified": ready,
        "ultra_capability_verified": ready,
        "codex_home": jobs._codex.subscription_only_env()["CODEX_HOME"],
        "user_config_ignored": ready,
        "critical_overrides_enforced": ready,
        "config_guard_verified": ready,
        "runtime_guard_rechecked": ready,
        "child_env_allowlist_verified": True,
        "rules_ignored": ready,
        "agents_disabled": ready,
        "network_disabled": ready,
        "extra_writable_roots_disabled": ready,
        "hosted_tools_disabled": ready,
        "mcp_servers_disabled": ready,
        "projects_table_replaced": ready,
        "api_key_env_scrubbed": True,
    }
    if ready and jobs.os.name == "nt":
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
    elif ready:
        preflight.update(
            containment_kind="posix_process_group_degraded",
            complete_tree_containment=False,
        )
    preflight.update(
        preflight_probe_count=(3 if ready else 2),
        preflight_containment_kind=(
            "windows_job" if jobs.os.name == "nt"
            else "posix_process_group_degraded"),
        preflight_complete_tree_containment=(jobs.os.name == "nt"),
        preflight_no_inference_verified=True,
        preflight_no_network_intent_verified=True,
        preflight_output_limits_verified=True,
        preflight_output_drain_verified=True,
        preflight_root_exit_verified=True,
        preflight_windows_job_policy_verified=(jobs.os.name == "nt"),
        preflight_windows_job_assignment_verified=(jobs.os.name == "nt"),
        preflight_windows_job_membership_verified=(jobs.os.name == "nt"),
        preflight_windows_process_handle_verified=(jobs.os.name == "nt"),
        preflight_windows_primary_thread_verified=(jobs.os.name == "nt"),
        preflight_windows_process_resumed=(jobs.os.name == "nt"),
        preflight_windows_job_empty_verified=(jobs.os.name == "nt"),
        preflight_process_group_kill_verified=None,
    )
    return preflight


def _valid_envelope(stack, output, prompt="trusted prompt", duration_ms=12):
    artifact = output / "receipt-artifact.md"
    artifact.write_text("trusted\n", encoding="utf-8")
    jobs = stack["jobs"]
    receipt = jobs._codex.build_receipt(
        status="success",
        prompt=prompt,
        sandbox="workspace-write",
        preflight=_trusted_preflight(jobs),
        parsed={
            "thread_id": "trusted-thread",
            "usage": {
                "input_tokens": 12,
                "cached_input_tokens": 5,
                "cache_write_input_tokens": 1,
                "output_tokens": 3,
                "reasoning_output_tokens": 2,
            },
            "event_count": 3,
            "malformed_count": 0,
        },
        exit_code=0,
        seat_started=True,
        artifact_paths=[artifact.name],
        expected_artifact_paths=[artifact.name],
        artifact_hashes={
            artifact.name: __import__("hashlib").sha256(artifact.read_bytes()).hexdigest(),
        },
        artifact_evidence={
            artifact.name: jobs._codex._artifact_file_evidence(
                output.resolve(), artifact.name),
        },
        artifact_contract_verified=True,
        artifact_mutation_verified=True,
        output_drain_verified=True,
        output_limits_verified=True, output_eof_verified=True,
        stdin_write_verified=True, stdin_close_verified=True,
        native_stdout_bytes=256, native_stderr_bytes=0,
    )
    envelope = jobs._codex.normalized_result(
        "trusted answer", receipt, duration_ms, False,
    )
    record = {
        "backend": "chatgpt",
        "relaunch_spec": {
            "prompt": prompt,
            "output_dir": str(output),
            "permission_mode": None,
            "expected_artifacts": [artifact.name],
        },
    }
    return envelope, record


def _failure_envelope(stack, output, status, *, seat_started,
                      timed_out=False, aborted=False,
                      tree_kill_verified=None, prompt="failure prompt"):
    jobs = stack["jobs"]
    authenticated = bool(seat_started or status == "containment_assignment_failed")
    preflight = _trusted_preflight(jobs, subscription_auth=authenticated)
    if status == "preflight_command_refused":
        preflight.update(
            preflight_probe_count=0, preflight_containment_kind=None,
            preflight_complete_tree_containment=False,
            preflight_no_inference_verified=False,
            preflight_no_network_intent_verified=False,
            preflight_output_limits_verified=False,
            preflight_output_drain_verified=False,
            preflight_root_exit_verified=False,
            preflight_windows_job_policy_verified=False,
            preflight_windows_job_assignment_verified=False,
            preflight_windows_job_membership_verified=False,
            preflight_windows_process_handle_verified=False,
            preflight_windows_primary_thread_verified=False,
            preflight_windows_process_resumed=False,
            preflight_windows_job_empty_verified=False,
            preflight_process_group_kill_verified=None,
        )
    elif status.startswith("preflight_"):
        is_windows = jobs.os.name == "nt"
        lifecycle_complete = status in (
            "preflight_output_limit_exceeded", "preflight_timeout",
            "preflight_aborted", "preflight_process_tree_straggler")
        preflight.update(
            preflight_probe_count=1,
            preflight_containment_kind=(
                "windows_job" if is_windows else "posix_process_group_degraded"),
            preflight_complete_tree_containment=(
                is_windows and lifecycle_complete),
            preflight_no_inference_verified=True,
            preflight_no_network_intent_verified=True,
            preflight_output_limits_verified=(
                status != "preflight_output_limit_exceeded" and
                status not in ("preflight_containment_failed",
                               "preflight_spawn_error",
                               "preflight_cleanup_failed")),
            preflight_output_drain_verified=(
                status not in ("preflight_containment_failed",
                               "preflight_spawn_error",
                               "preflight_cleanup_failed")),
            preflight_root_exit_verified=(
                status not in ("preflight_containment_failed",
                               "preflight_spawn_error",
                               "preflight_cleanup_failed")),
            preflight_windows_job_policy_verified=is_windows,
            preflight_windows_job_assignment_verified=(
                is_windows and lifecycle_complete),
            preflight_windows_job_membership_verified=(
                is_windows and lifecycle_complete),
            preflight_windows_process_handle_verified=(
                is_windows and lifecycle_complete),
            preflight_windows_primary_thread_verified=(
                is_windows and lifecycle_complete),
            preflight_windows_process_resumed=(
                is_windows and lifecycle_complete),
            preflight_windows_job_empty_verified=(
                is_windows and lifecycle_complete),
            preflight_process_group_kill_verified=(
                True if not is_windows and status in (
                    "preflight_timeout", "preflight_aborted") else None),
        )
    if status == "containment_assignment_failed" and not seat_started:
        preflight.update(
            containment_kind=("windows_job" if jobs.os.name == "nt" else None),
            complete_tree_containment=False,
            windows_job_policy_verified=(jobs.os.name == "nt"),
            windows_job_assignment_verified=False,
            windows_job_membership_verified=False,
            windows_process_handle_verified=False,
            windows_primary_thread_verified=False,
            windows_process_resumed=False,
            windows_execution_possible=False,
            windows_job_empty_verified=False,
            root_exit_verified=False,
        )
    parsed = ({
        "thread_id": "failed-thread",
        "usage": {
            "input_tokens": 9,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 0,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
        },
        "event_count": 3,
        "malformed_count": 0,
    } if seat_started else {})
    io_proof = {
        "output_limits_verified": (True if seat_started else None),
        "output_eof_verified": (True if seat_started else None),
        "stdin_write_verified": (True if seat_started else None),
        "stdin_close_verified": (True if seat_started else None),
        "output_overflow_kind": None,
        "native_stdout_bytes": (64 if seat_started else 0),
        "native_stderr_bytes": (32 if seat_started else 0),
    }
    if status == "output_limit_exceeded":
        io_proof.update(
            output_limits_verified=False, output_overflow_kind="stdout",
            native_stdout_bytes=jobs._codex.MAX_NATIVE_STDOUT_BYTES + 1)
    elif status == "output_drain_failed":
        io_proof.update(output_eof_verified=False)
    elif status == "stdin_write_failed":
        io_proof.update(stdin_write_verified=False)
    receipt = jobs._codex.build_receipt(
        status=status,
        prompt=prompt,
        sandbox="workspace-write",
        preflight=preflight,
        parsed=parsed,
        exit_code=(1 if seat_started else None),
        error="safe adapter failure: " + status,
        timed_out=timed_out,
        aborted=aborted,
        seat_started=seat_started,
        tree_kill_verified=tree_kill_verified,
        output_drain_verified=(
            (status not in ("kill_failed", "output_drain_failed"))
            if seat_started else None
        ),
        **io_proof,
        expected_artifact_paths=["report.md"],
    )
    envelope = jobs._codex.normalized_result("", receipt, 14, True)
    record = {
        "backend": "chatgpt",
        "relaunch_spec": {
            "prompt": prompt,
            "output_dir": str(output),
            "permission_mode": None,
            "expected_artifacts": ["report.md"],
        },
    }
    return envelope, record


def _simulate_posix_parent(jobs, monkeypatch):
    """Exercise POSIX receipt rules without mutating process-global ``os.name``."""
    real_os = jobs.os

    class PosixView:
        name = "posix"
        path = real_os.path
        fstat = staticmethod(real_os.fstat)

    monkeypatch.setattr(jobs, "os", PosixView)
    # This Windows host can only inspect the installed Windows signer shape.
    # Provenance itself is covered by native-platform tests; these cases isolate
    # the parent lifecycle rules for an otherwise trusted POSIX receipt.
    monkeypatch.setattr(
        jobs, "_valid_current_chatgpt_provenance", lambda _receipt: True)


def test_omitted_backend_uses_saved_chatgpt_coding_family_not_stale_env(stack):
    project = _project(stack)
    rec = stack["lanes"].launch_lane(
        project["id"], "research",
    )
    assert rec["backend"] == "chatgpt"
    done = stack["jobs"].wait(rec["job_id"], timeout=30)
    assert done["status"] == stack["jobs"].STATUS_DONE
    assert done["backend"] == "chatgpt"

    launch_record = json.loads(
        (Path(rec["output_dir"]) / stack["lanes"].LAUNCH_RECORD_NAME)
        .read_text(encoding="utf-8")
    )
    assert launch_record["backend"] == "chatgpt"

    session = stack["sessions"].get_session(rec["job_id"])
    assert session is not None
    assert session["backend"] == "chatgpt"
    assert done["model_receipt"]["subscription_auth"] is True
    assert done["model_receipt"]["seat_started"] is True
    assert done["cost"]["total_cost_usd"] is None
    assert "FAKE_CODEX_UNICODE → — é ✓ 中" in "\n".join(
        stack["jobs"].extract_assistant_text(
            stack["jobs"].all_lines(rec["job_id"])
        )
    )


def test_preference_aware_plan_reports_actual_driver_and_review_family(stack):
    plan = stack["lanes"].select_engine_plan(
        "research",
        profile={"claude": True, "gemini": True, "grok": True, "chatgpt": True},
        preferred_backend="chatgpt",
        review_family="claude",
    )
    assert plan["status"] == stack["lanes"].ENGINE_STATUS_OK
    assert plan["preferred_driver"] == "chatgpt"
    assert plan["actual_driver"] == "chatgpt"
    assert plan["driver"] == "chatgpt"
    assert plan["review_family"] == "claude"
    assert plan["cross_model"] is True
    assert plan["spawns_chatgpt"] is True
    assert plan["degraded"] is True


def test_chatgpt_general_is_bridge_pending_until_resumable_cockpit_exists(stack):
    plan = stack["lanes"].select_engine_plan(
        "general",
        profile={"claude": True, "gemini": True, "grok": True, "chatgpt": True},
        preferred_backend="chatgpt",
        review_family="claude",
    )
    assert plan["status"] == stack["lanes"].ENGINE_STATUS_BRIDGE_PENDING
    assert plan["spawns_chatgpt"] is False
    assert "chatgpt-gated-bridge-pending" in plan["reason"]


def test_chatgpt_ignores_generic_and_adapter_env_overrides_and_owns_target(
        stack, monkeypatch):
    output = stack["tmp"] / "bounded-output"
    output.mkdir()
    prompt = "private prompt must remain on stdin"
    monkeypatch.setenv("ANCHOR_CODEX_ADAPTER", FAKE)
    argv = stack["jobs"].resolve_runner_cmd(
        backend="chatgpt", prompt=prompt, output_dir=output,
        expected_artifacts=["report.md"],
    )
    assert FAKE_CODEX_ADAPTER in argv
    assert FAKE not in argv
    assert prompt not in argv
    assert argv[argv.index("--target") + 1] == str(output.resolve())
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--expected-artifact") + 1] == "report.md"


def test_chatgpt_real_child_round_trips_unicode_and_requires_receipt(stack):
    output = stack["tmp"] / "unicode-output"
    output.mkdir()
    prompt = "Café naïve → ✓ 中"
    rec = stack["jobs"].launch(
        "research", cwd=stack["tmp"], backend="chatgpt", prompt=prompt,
        output_dir=output, expected_artifacts=["fake-codex-artifact.md"],
    )
    done = stack["jobs"].wait(rec["job_id"], timeout=30)
    assert done["status"] == stack["jobs"].STATUS_DONE
    text = "\n".join(stack["jobs"].extract_assistant_text(
        stack["jobs"].all_lines(rec["job_id"])))
    assert prompt in text
    assert "FAKE_CODEX_UNICODE → — é ✓ 中" in text
    assert "TARGET=unicode-output" in text
    assert (output / "fake-codex-artifact.md").is_file()
    assert done["model_receipt"]["artifact_write_observed"] is True


def test_chatgpt_zero_exit_without_subscription_receipt_fails_closed(
        stack, monkeypatch):
    output = stack["tmp"] / "receipt-required"
    output.mkdir()
    monkeypatch.setattr(stack["jobs"], "CODEX_ADAPTER_PATH", FAKE)
    rec = stack["jobs"].launch(
        "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
        output_dir=output, expected_artifacts=["required.md"],
    )
    done = stack["jobs"].wait(rec["job_id"], timeout=30)
    assert done["status"] == stack["jobs"].STATUS_FAILED
    assert done["failure_reason"] == "chatgpt-valid-receipt-required"
    assert "model_receipt" not in done


def test_chatgpt_workspace_write_requires_exact_artifact_contract_before_side_effect(
        stack, monkeypatch):
    jobs = stack["jobs"]
    output = stack["tmp"] / "contract-required"
    output.mkdir()
    job_id = "chatgpt-artifact-contract-must-not-spawn"

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("a missing artifact contract must not spawn")

    monkeypatch.setattr(jobs.subprocess, "Popen", forbidden_spawn)
    before = len(jobs.list_records())
    with pytest.raises(ValueError, match="chatgpt-artifact-contract-required"):
        jobs.launch(
            "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=output, job_id=job_id,
        )
    assert len(jobs.list_records()) == before
    assert jobs.load_record(job_id) is None
    assert not jobs.log_path_for(job_id).exists()


@pytest.mark.parametrize("lane", ("general", "plan", "build", "unknown"))
def test_direct_nonresearch_chatgpt_launch_refuses_before_side_effect(stack, lane):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("no-direct-" + lane)
    output.mkdir()
    job_id = "chatgpt-no-direct-" + lane
    before = len(jobs.list_records())
    jobs_path_existed = jobs.jobs_dir().exists()
    with pytest.raises(ValueError, match="chatgpt-gated-bridge-pending"):
        jobs.launch(
            lane, cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=output, job_id=job_id,
            expected_artifacts=["report.md"],
        )
    assert len(jobs.list_records()) == before
    assert jobs.jobs_dir().exists() is jobs_path_existed
    assert jobs.load_record(job_id) is None
    assert not jobs.log_path_for(job_id).exists()


@pytest.mark.parametrize(
    "backend", ("", False, 0, [], {}, ["chatgpt"], {"backend": "chatgpt"}),
)
def test_invalid_backend_types_never_default_or_create_job_side_effects(
        stack, backend):
    jobs = stack["jobs"]
    output = stack["tmp"] / "invalid-backend"
    output.mkdir(exist_ok=True)
    job_id = "invalid-backend-must-not-persist"
    before = len(jobs.list_records())
    with pytest.raises(ValueError, match="unknown backend"):
        jobs.launch(
            "research", cwd=stack["tmp"], backend=backend, prompt="work",
            output_dir=output, job_id=job_id,
        )
    assert len(jobs.list_records()) == before
    assert jobs.load_record(job_id) is None
    assert not jobs.log_path_for(job_id).exists()


def test_legacy_interactive_research_terminal_refuses_chatgpt_before_scaffold(stack):
    project = _project(stack, "Legacy terminal")
    output = stack["lanes"].lane_output_dir(
        project["folder_path"], project["id"], "research",
    )
    before = {p.relative_to(output).as_posix() for p in output.rglob("*")}
    with pytest.raises(
        stack["lanes"].EngineNotAllowedError,
        match="chatgpt-gated-bridge-pending",
    ):
        stack["rnd_terminal"].start_terminal(
            project["id"], "research", backend="chatgpt",
        )
    after = {p.relative_to(output).as_posix() for p in output.rglob("*")}
    assert after == before


@pytest.mark.parametrize("bad", (
    "../escape.md", "C:/escape.md", "report.md/../x", "report.md:stream",
    "CON.txt", "report?.md", "dir\\file.md", "e\u0301.md", "dir//file.md",
    "report.md.", "x{y}.md", "bad\x7fname.md", "a" * 513,
))
def test_chatgpt_artifact_contract_rejects_unsafe_paths_before_side_effect(
        stack, bad):
    jobs = stack["jobs"]
    output = stack["tmp"] / "contract-invalid"
    output.mkdir(exist_ok=True)
    before = len(jobs.list_records())
    with pytest.raises(ValueError, match="chatgpt-artifact-contract-invalid"):
        jobs.launch(
            "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=output, expected_artifacts=[bad],
        )
    assert len(jobs.list_records()) == before


def test_chatgpt_artifact_contract_rejects_case_equivalent_duplicates(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "duplicate-contract"
    output.mkdir()
    before = len(jobs.list_records())
    with pytest.raises(ValueError, match="chatgpt-artifact-contract-invalid"):
        jobs.launch(
            "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=output,
            expected_artifacts=["Report.md", "report.md"],
        )
    assert len(jobs.list_records()) == before


def test_legacy_chatgpt_write_relaunch_without_contract_returns_typed_refusal(stack):
    jobs = stack["jobs"]
    project_root = stack["tmp"] / "legacy-relaunch-project"
    output = project_root / "research"
    output.mkdir(parents=True)
    old_id = "legacy-chatgpt-no-artifact-contract"
    record = {
        "job_id": old_id,
        "lane": "research",
        "pid": None,
        "status": jobs.STATUS_INTERRUPTED,
        "backend": "chatgpt",
        "relaunch_spec": {
            "lane": "research",
            "cwd": str(project_root),
            "prompt": "legacy prompt",
            "output_dir": str(output),
            "gated": False,
            "permission_mode": None,
            "backend": "chatgpt",
            "env_keys": {},
            "project_id": "legacy-project",
            "folder_path": str(project_root),
        },
    }
    jobs._write_record(record)
    result = jobs.relaunch(old_id)
    assert result["ok"] is False
    assert result["reason"] == "chatgpt-relaunch-spec-incomplete"
    assert jobs.load_record(old_id).get("relaunched_as") is None


def test_legacy_top_level_chatgpt_never_defaults_relaunch_to_claude(stack):
    jobs = stack["jobs"]
    project_root = stack["tmp"] / "legacy-provider-project"
    output = project_root / "research"
    output.mkdir(parents=True)
    old_id = "legacy-top-level-chatgpt"
    jobs._write_record({
        "job_id": old_id,
        "lane": "research",
        "pid": None,
        "status": jobs.STATUS_INTERRUPTED,
        "backend": "chatgpt",
        "relaunch_spec": {
            "lane": "research",
            "cwd": str(project_root),
            "prompt": "legacy prompt",
            "output_dir": str(output),
            "gated": False,
            "permission_mode": None,
            "env_keys": {},
            "project_id": "legacy-project",
            "folder_path": str(project_root),
        },
    })
    result = jobs.relaunch(old_id)
    assert result == {"ok": False, "reason": "chatgpt-relaunch-spec-incomplete"}
    assert jobs.load_record(old_id).get("relaunched_as") is None


def test_relaunch_rejects_conflicting_record_and_spec_backends(stack):
    jobs = stack["jobs"]
    project_root = stack["tmp"] / "conflicting-provider-project"
    output = project_root / "research"
    output.mkdir(parents=True)
    old_id = "conflicting-relaunch-provider"
    jobs._write_record({
        "job_id": old_id,
        "lane": "research",
        "pid": None,
        "status": jobs.STATUS_INTERRUPTED,
        "backend": "chatgpt",
        "relaunch_spec": {
            "lane": "research",
            "cwd": str(project_root),
            "prompt": "legacy prompt",
            "output_dir": str(output),
            "gated": False,
            "permission_mode": None,
            "backend": "claude",
            "expected_artifacts": [],
            "env_keys": {},
            "project_id": "legacy-project",
            "folder_path": str(project_root),
        },
    })
    result = jobs.relaunch(old_id)
    assert result == {"ok": False, "reason": "relaunch-backend-conflict"}
    assert jobs.load_record(old_id).get("relaunched_as") is None


def test_receipt_only_chatgpt_identity_cannot_relaunch_as_claude(stack):
    jobs = stack["jobs"]
    project_root = stack["tmp"] / "receipt-provider-project"
    output = project_root / "research"
    output.mkdir(parents=True)
    old_id = "receipt-only-chatgpt-provider"
    jobs._write_record({
        "job_id": old_id,
        "lane": "research",
        "pid": None,
        "status": jobs.STATUS_INTERRUPTED,
        "model_receipt": {
            "backend_requested": "chatgpt",
            "family_requested": "chatgpt",
        },
        "relaunch_spec": {
            "lane": "research", "cwd": str(project_root),
            "prompt": "legacy prompt", "output_dir": str(output),
            "gated": False, "permission_mode": None, "env_keys": {},
            "project_id": "legacy-project", "folder_path": str(project_root),
        },
    })
    result = jobs.relaunch(old_id)
    assert result == {"ok": False, "reason": "chatgpt-relaunch-spec-incomplete"}
    assert jobs.load_record(old_id).get("relaunched_as") is None


@pytest.mark.parametrize("bad_backend", ([], {}, ["chatgpt"], {"x": 1}))
def test_relaunch_unhashable_backend_returns_typed_refusal(stack, bad_backend):
    jobs = stack["jobs"]
    old_id = "bad-relaunch-backend-" + str(len(jobs.list_records()))
    jobs._write_record({
        "job_id": old_id, "status": jobs.STATUS_INTERRUPTED,
        "backend": "claude",
        "relaunch_spec": {"lane": "research", "backend": bad_backend},
    })
    result = jobs.relaunch(old_id)
    assert result["ok"] is False
    assert result["reason"].startswith("relaunch-unknown-spec:")


def test_chatgpt_minimal_forged_receipt_is_rejected(stack):
    prompt = "receipt must be complete"
    output = stack["tmp"] / "forged-receipt"
    output.mkdir()
    minimal = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "claimed success", "session_id": "forged-thread",
        "billing_mode": "subscription", "cost_state": "subscription_covered",
        "model_receipt": {
            "backend_requested": "chatgpt", "transport_actual": "codex-cli",
            "auth_kind": "chatgpt_subscription", "subscription_auth": True,
            "requested_model": "gpt-5.6-sol", "requested_effort": "ultra",
            "status": "success", "seat_started": True,
            "billing_mode": "subscription", "cost_state": "subscription_covered",
            "thread_id": "forged-thread",
            "prompt_sha256": __import__("hashlib").sha256(
                prompt.encode("utf-8")).hexdigest(),
        },
    }
    record = {"relaunch_spec": {
        "prompt": prompt, "output_dir": str(output), "permission_mode": None,
    }}
    assert stack["jobs"]._valid_chatgpt_success_envelope(
        minimal, record, adapter_exit_code=0,
    ) is False


def test_chatgpt_extra_args_refuse_before_job_side_effect(stack):
    output = stack["tmp"] / "no-extra-args"
    output.mkdir()
    before = len(stack["jobs"].list_records())
    with pytest.raises(ValueError, match="chatgpt-extra-args-refused"):
        stack["jobs"].launch(
            "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=output, extra_args=["--sandbox", "danger-full-access"],
        )
    assert len(stack["jobs"].list_records()) == before


def test_chatgpt_explicit_command_refuses_before_job_side_effect(stack):
    jobs = stack["jobs"]
    job_id = "chatgpt-command-must-not-persist"
    before = len(jobs.list_records())
    jobs_path_existed = jobs.jobs_dir().exists()
    with pytest.raises(ValueError, match="chatgpt-command-override-refused"):
        jobs.launch(
            "research", backend="chatgpt", job_id=job_id,
            command=[sys.executable, FAKE, "--lines", "1"],
        )
    assert len(jobs.list_records()) == before
    assert jobs.jobs_dir().exists() is jobs_path_existed
    assert jobs.load_record(job_id) is None
    assert not jobs.log_path_for(job_id).exists()


def test_chatgpt_caller_environment_refuses_before_spawn_or_side_effect(
        stack, monkeypatch):
    jobs = stack["jobs"]
    job_id = "chatgpt-env-must-not-spawn"
    fake_base = stack["tmp"] / "attacker-local-app-data"
    fake_base.mkdir()

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("caller-selected Codex path must never spawn")

    monkeypatch.setattr(jobs.subprocess, "Popen", forbidden_spawn)
    before = len(jobs.list_records())
    with pytest.raises(ValueError, match="chatgpt-env-overlay-refused"):
        jobs.launch(
            "research", cwd=stack["tmp"], backend="chatgpt", prompt="work",
            output_dir=stack["tmp"], job_id=job_id,
            env={"LOCALAPPDATA": str(fake_base), "CODEX_HOME": str(fake_base)},
        )
    assert len(jobs.list_records()) == before
    assert jobs.load_record(job_id) is None
    assert not jobs.log_path_for(job_id).exists()


@pytest.mark.parametrize(
    "kwargs,error",
    (
        ({"env": {"LOCALAPPDATA": "attacker"}}, "chatgpt-env-overlay-refused"),
        ({"extra_args": ["--dangerous"]}, "chatgpt-extra-args-refused"),
    ),
)
def test_launch_lane_refuses_chatgpt_overrides_before_scaffolding(
        stack, kwargs, error):
    folder = stack["tmp"] / ("legacy-" + error)
    folder.mkdir()
    project = stack["registry"].add_project(
        "Legacy", str(folder), scaffold=False,
    )
    assert not (folder / ".anchor").exists()
    with pytest.raises(ValueError, match=error):
        stack["lanes"].launch_lane(
            project["id"], "research", backend="chatgpt", **kwargs,
        )
    assert not (folder / ".anchor").exists()


def test_saved_family_load_failure_never_silently_falls_back_to_claude(
        stack, monkeypatch):
    project = _project(stack, "Settings failure")
    import anchor_settings

    monkeypatch.setattr(
        anchor_settings, "get_coding_family",
        lambda: (_ for _ in ()).throw(RuntimeError("settings unavailable")),
    )
    before = len(stack["jobs"].list_records())
    with pytest.raises(
        stack["lanes"].EngineNotAllowedError,
        match="coding-family-unavailable",
    ):
        stack["lanes"].launch_lane(project["id"], "research")
    assert len(stack["jobs"].list_records()) == before


def test_chatgpt_target_must_be_inside_project_before_job_side_effect(stack):
    project_root = stack["tmp"] / "contained-project"
    project_root.mkdir()
    outside = stack["tmp"] / "outside-target"
    outside.mkdir()
    before = len(stack["jobs"].list_records())
    with pytest.raises(ValueError, match="chatgpt-target-outside-project"):
        stack["jobs"].launch(
            "research", cwd=project_root, backend="chatgpt", prompt="work",
            output_dir=outside,
        )
    assert len(stack["jobs"].list_records()) == before


@pytest.mark.parametrize("lane", ("plan", "build"))
def test_gated_chatgpt_lane_refuses_before_scaffolding_or_spawn(stack, lane):
    project = _project(stack, lane)
    expected = stack["lanes"].lane_output_dir(
        project["folder_path"], project["id"], lane,
    )
    before_entries = {
        path.relative_to(expected).as_posix()
        for path in expected.rglob("*")
    }
    before = len(stack["jobs"].list_records())
    with pytest.raises(
        stack["lanes"].EngineNotAllowedError,
        match="chatgpt-gated-bridge-pending",
    ):
        stack["lanes"].launch_lane(project["id"], lane)
    assert len(stack["jobs"].list_records()) == before
    after_entries = {
        path.relative_to(expected).as_posix()
        for path in expected.rglob("*")
    }
    assert after_entries == before_entries
    assert not (expected / stack["lanes"].LAUNCH_RECORD_NAME).exists()


def test_model_receipt_is_whitelisted_and_subscription_cost_is_labelled(stack):
    raw = {
        "type": "result",
        "result": "ok",
        "billing_mode": "subscription",
        "cost_state": "subscription_covered",
        "usage": {
            "input_tokens": 12, "cached_input_tokens": 5, "output_tokens": 3,
        },
        "model_receipt": {
            "requested_model": "gpt-5.6-sol",
            "requested_effort": "ultra",
            "model_served": None,
            "model_attested": False,
            "degraded": True,
            "billing_mode": "subscription",
            "cost_state": "subscription_covered",
            "prompt_sha256": "abc123",
            "usage": {"input_tokens": 12, "cached_input_tokens": 5, "output_tokens": 3},
            "secret_untrusted_child_field": "must not persist",
        },
    }
    receipt = stack["jobs"]._model_receipt_from_envelope(raw)
    assert receipt["requested_model"] == "gpt-5.6-sol"
    assert receipt["model_served"] is None
    assert receipt["model_attested"] is False
    assert "secret_untrusted_child_field" not in receipt
    cost = stack["jobs"]._cost_from_envelope(raw)
    assert cost["billing_mode"] == "subscription"
    assert cost["cost_state"] == "subscription_covered"
    assert cost["total_cost_usd"] is None
    assert cost["cached_input_tokens"] == 5


@pytest.mark.parametrize(
    "tamper",
    (
        "executable", "usage", "duration", "cost", "config-guard",
        "network", "writable-roots", "hosted-tools", "mcp", "tree-kill",
        "executable-hash", "provenance", "launch-handle", "image-attestation",
        "runtime-guard", "environment", "projects-table", "drain",
        "expected-contract", "artifact-path", "artifact-hash",
        "artifact-contract", "artifact-mutation", "artifact-evidence-hash",
        "artifact-evidence-identity", "signer-subject", "signer-certificate",
        "signer-binding", "config-loaded", "config-ignored",
        "containment-kind", "complete-containment", "job-policy",
        "job-assignment", "job-membership", "process-handle",
        "primary-thread", "process-resumed", "execution-possible",
        "job-empty", "root-exit", "process-group",
        "output-limits", "output-eof", "stdin-write", "stdin-close",
        "output-overflow", "stdout-bytes", "stderr-bytes",
        "preflight-count", "preflight-kind", "preflight-complete",
        "preflight-no-inference", "preflight-no-network",
        "preflight-limits", "preflight-drain", "preflight-root",
        "preflight-job-policy", "preflight-job-assignment",
        "preflight-job-membership", "preflight-process-handle",
        "preflight-primary-thread", "preflight-process-resumed",
        "preflight-job-empty", "preflight-process-group",
    ),
)
def test_chatgpt_success_receipt_rejects_conflicting_or_untrusted_telemetry(
        stack, tamper):
    output = stack["tmp"] / ("tamper-" + tamper)
    output.mkdir()
    envelope, record = _valid_envelope(stack, output)
    assert stack["jobs"]._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0,
    ) is True

    if tamper == "executable":
        envelope["model_receipt"]["executable_path"] = str(output / "codex.exe")
    elif tamper == "usage":
        envelope["usage"]["input_tokens"] += 1
    elif tamper == "duration":
        envelope["duration_ms"] = -5
    elif tamper == "cost":
        envelope["total_cost_usd"] = 777.0
    elif tamper == "config-guard":
        envelope["model_receipt"]["config_guard_verified"] = False
    elif tamper == "network":
        envelope["model_receipt"]["network_disabled"] = False
    elif tamper == "writable-roots":
        envelope["model_receipt"]["extra_writable_roots_disabled"] = False
    elif tamper == "hosted-tools":
        envelope["model_receipt"]["hosted_tools_disabled"] = False
    elif tamper == "mcp":
        envelope["model_receipt"]["mcp_servers_disabled"] = False
    elif tamper == "tree-kill":
        envelope["model_receipt"]["tree_kill_verified"] = False
    elif tamper == "executable-hash":
        envelope["model_receipt"]["executable_sha256"] = "0" * 64
    elif tamper == "provenance":
        envelope["model_receipt"]["executable_provenance_verified"] = False
    elif tamper == "launch-handle":
        envelope["model_receipt"]["executable_handle_guarded_through_spawn"] = False
    elif tamper == "image-attestation":
        envelope["model_receipt"]["preexecution_child_image_attested"] = True
    elif tamper == "runtime-guard":
        envelope["model_receipt"]["runtime_guard_rechecked"] = False
    elif tamper == "environment":
        envelope["model_receipt"]["child_env_allowlist_verified"] = False
    elif tamper == "projects-table":
        envelope["model_receipt"]["projects_table_replaced"] = False
    elif tamper == "drain":
        envelope["model_receipt"]["output_drain_verified"] = False
    elif tamper == "expected-contract":
        envelope["model_receipt"]["expected_artifact_paths"] = ["other.md"]
    elif tamper == "artifact-path":
        envelope["model_receipt"]["artifact_paths"] = ["other.md"]
    elif tamper == "artifact-hash":
        key = record["relaunch_spec"]["expected_artifacts"][0]
        envelope["model_receipt"]["artifact_hashes"][key] = "0" * 64
    elif tamper == "artifact-contract":
        envelope["model_receipt"]["artifact_contract_verified"] = False
    elif tamper == "artifact-mutation":
        envelope["model_receipt"]["artifact_mutation_verified"] = False
    elif tamper == "artifact-evidence-hash":
        key = record["relaunch_spec"]["expected_artifacts"][0]
        envelope["model_receipt"]["artifact_evidence"][key]["sha256"] = "0" * 64
    elif tamper == "artifact-evidence-identity":
        key = record["relaunch_spec"]["expected_artifacts"][0]
        envelope["model_receipt"]["artifact_evidence"][key]["inode"] += 1
    elif tamper == "signer-subject":
        envelope["model_receipt"]["executable_signer_subject"] = "CN=Other"
    elif tamper == "signer-certificate":
        envelope["model_receipt"]["executable_signer_certificate_sha256"] = "0" * 64
    elif tamper == "signer-binding":
        envelope["model_receipt"]["signer_image_binding_verified"] = not (
            envelope["model_receipt"]["signer_image_binding_verified"])
    elif tamper == "config-loaded":
        envelope["model_receipt"]["user_config_loaded"] = True
    elif tamper == "config-ignored":
        envelope["model_receipt"]["user_config_ignored"] = False
    elif tamper == "containment-kind":
        envelope["model_receipt"]["containment_kind"] = "none"
    elif tamper == "complete-containment":
        envelope["model_receipt"]["complete_tree_containment"] = not (
            envelope["model_receipt"]["complete_tree_containment"])
    elif tamper == "process-group":
        envelope["model_receipt"]["process_group_kill_verified"] = False
    elif tamper in ("output-limits", "output-eof", "stdin-write", "stdin-close"):
        field = {
            "output-limits": "output_limits_verified",
            "output-eof": "output_eof_verified",
            "stdin-write": "stdin_write_verified",
            "stdin-close": "stdin_close_verified",
        }[tamper]
        envelope["model_receipt"][field] = False
    elif tamper == "output-overflow":
        envelope["model_receipt"]["output_overflow_kind"] = "stdout"
    elif tamper == "stdout-bytes":
        envelope["model_receipt"]["native_stdout_bytes"] = (
            stack["jobs"]._codex.MAX_NATIVE_STDOUT_BYTES + 1)
    elif tamper == "stderr-bytes":
        envelope["model_receipt"]["native_stderr_bytes"] = (
            stack["jobs"]._codex.MAX_NATIVE_STDERR_BYTES + 1)
    elif tamper == "preflight-count":
        envelope["model_receipt"]["preflight_probe_count"] = 2
    elif tamper == "preflight-kind":
        envelope["model_receipt"]["preflight_containment_kind"] = "none"
    elif tamper == "preflight-complete":
        envelope["model_receipt"]["preflight_complete_tree_containment"] = not (
            envelope["model_receipt"]["preflight_complete_tree_containment"])
    elif tamper == "preflight-process-group":
        envelope["model_receipt"]["preflight_process_group_kill_verified"] = False
    elif tamper.startswith("preflight-"):
        field = {
            "preflight-no-inference": "preflight_no_inference_verified",
            "preflight-no-network": "preflight_no_network_intent_verified",
            "preflight-limits": "preflight_output_limits_verified",
            "preflight-drain": "preflight_output_drain_verified",
            "preflight-root": "preflight_root_exit_verified",
            "preflight-job-policy": "preflight_windows_job_policy_verified",
            "preflight-job-assignment": "preflight_windows_job_assignment_verified",
            "preflight-job-membership": "preflight_windows_job_membership_verified",
            "preflight-process-handle": "preflight_windows_process_handle_verified",
            "preflight-primary-thread": "preflight_windows_primary_thread_verified",
            "preflight-process-resumed": "preflight_windows_process_resumed",
            "preflight-job-empty": "preflight_windows_job_empty_verified",
        }[tamper]
        envelope["model_receipt"][field] = not envelope["model_receipt"][field]
    else:
        field = {
            "job-policy": "windows_job_policy_verified",
            "job-assignment": "windows_job_assignment_verified",
            "job-membership": "windows_job_membership_verified",
            "process-handle": "windows_process_handle_verified",
            "primary-thread": "windows_primary_thread_verified",
            "process-resumed": "windows_process_resumed",
            "execution-possible": "windows_execution_possible",
            "job-empty": "windows_job_empty_verified",
            "root-exit": "root_exit_verified",
        }[tamper]
        envelope["model_receipt"][field] = not envelope["model_receipt"][field]

    assert stack["jobs"]._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0,
    ) is False


def test_valid_chatgpt_success_receipt_requires_zero_wrapper_exit(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "wrapper-exit-mismatch"
    output.mkdir()
    envelope, record = _valid_envelope(stack, output, prompt="wrapper exit")
    assert jobs._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=7,
    ) is False

    record.update({
        "job_id": "wrapper-exit-mismatch-job",
        "status": jobs.STATUS_RUNNING,
        "project_id": None,
        "folder_path": None,
    })
    jobs._write_record(record)
    jobs._finalize(record["job_id"], 7, envelope)
    done = jobs.load_record(record["job_id"])
    assert done["status"] == jobs.STATUS_FAILED
    assert done["failure_reason"] == "chatgpt-valid-receipt-required"
    assert "cost" not in done
    assert "model_receipt" not in done
    assert "session_id" not in done


@pytest.mark.parametrize("field,alias", (
    ("subscription_auth", 1),
    ("model_capability_verified", 1),
    ("ultra_capability_verified", 1),
    ("seat_started", 1),
    ("exit_code", False),
    ("timed_out", 0),
    ("aborted", 0),
    ("model_attested", 0),
    ("degraded", 1),
    ("artifact_scan_complete", 1),
))
def test_success_receipt_rejects_bool_int_aliases(stack, field, alias):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("scalar-alias-" + field)
    output.mkdir()
    envelope, record = _valid_envelope(stack, output)
    envelope["model_receipt"][field] = alias
    assert jobs._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0) is False


def test_copied_success_omits_absent_error_and_keeps_compound_fields(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "copy-success-receipt"
    output.mkdir()
    envelope, _record = _valid_envelope(stack, output)
    assert "error" not in envelope["model_receipt"]
    copied = jobs._model_receipt_from_envelope(envelope)
    assert "error" not in copied
    assert copied["usage"] == envelope["model_receipt"]["usage"]
    assert copied["artifact_paths"] == envelope["model_receipt"]["artifact_paths"]


def test_read_only_success_uses_false_mutation_aliases_and_empty_evidence(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "read-only-mutation-semantics"
    output.mkdir()
    prompt = "read only receipt"
    receipt = jobs._codex.build_receipt(
        status="success", prompt=prompt, sandbox="read-only",
        preflight=_trusted_preflight(jobs),
        parsed={
            "thread_id": "read-only-thread",
            "usage": {
                "input_tokens": 1, "cached_input_tokens": 0,
                "cache_write_input_tokens": 0, "output_tokens": 1,
                "reasoning_output_tokens": 0,
            },
            "event_count": 3, "malformed_count": 0,
        },
        exit_code=0, seat_started=True, expected_artifact_paths=[],
        artifact_hashes={}, artifact_evidence={},
        artifact_mutation_verified=False, output_drain_verified=True,
        output_limits_verified=True, output_eof_verified=True,
        stdin_write_verified=True, stdin_close_verified=True,
        native_stdout_bytes=64, native_stderr_bytes=0,
    )
    envelope = jobs._codex.normalized_result("ok", receipt, 5, False)
    record = {
        "backend": "chatgpt",
        "relaunch_spec": {
            "prompt": prompt, "output_dir": str(output),
            "permission_mode": "plan", "expected_artifacts": [],
        },
    }
    assert receipt["artifact_contract_verified"] is False
    assert receipt["artifact_mutation_verified"] is False
    assert receipt["artifact_evidence"] == {}
    assert jobs._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0) is True
    envelope["model_receipt"]["artifact_contract_verified"] = True
    assert jobs._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0) is False


def test_parent_artifact_recheck_fails_closed_when_root_guard_close_fails(
        stack, monkeypatch):
    jobs = stack["jobs"]
    output = stack["tmp"] / "root-guard-close"
    output.mkdir()

    class Guard:
        def close(self):
            raise OSError("synthetic guard close failure")

    monkeypatch.setattr(jobs._codex, "_open_guarded_directory", lambda _root: Guard())
    monkeypatch.setattr(
        jobs._codex, "_guarded_directory_identity", lambda _guard, _root: (1, 2))
    monkeypatch.setattr(
        jobs._codex, "_expected_artifact_snapshot",
        lambda _root, _paths, _identity: ({}, True))
    monkeypatch.setattr(
        jobs._codex, "_workspace_root_matches", lambda _root, _identity: True)
    assert jobs._current_artifact_snapshot(output, ()) is None


@pytest.mark.parametrize("kind", ("success", "failure"))
def test_chatgpt_receipt_rejects_unbounded_integer_telemetry(stack, kind):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("huge-telemetry-" + kind)
    output.mkdir()
    if kind == "success":
        envelope, record = _valid_envelope(stack, output)
        exit_code = 0
        validator = lambda: jobs._valid_chatgpt_success_envelope(
            envelope, record, adapter_exit_code=exit_code,
        )
    else:
        envelope, record = _failure_envelope(
            stack, output, "usage_limit", seat_started=True,
        )
        exit_code = 1
        validator = lambda: jobs._valid_chatgpt_failure_envelope(
            envelope, record, adapter_exit_code=exit_code,
        )
    envelope["usage"]["input_tokens"] = 10 ** 100
    envelope["model_receipt"]["usage"]["input_tokens"] = 10 ** 100
    assert validator() is False


@pytest.mark.parametrize("thread_id", ("\x00thread", "thread\tname", "bad\x7fid"))
def test_chatgpt_receipt_rejects_control_bearing_thread_ids(stack, thread_id):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("bad-thread-" + str(ord(thread_id[0])))
    output.mkdir(exist_ok=True)
    envelope, record = _valid_envelope(stack, output)
    envelope["session_id"] = thread_id
    envelope["model_receipt"]["thread_id"] = thread_id
    assert jobs._valid_chatgpt_success_envelope(
        envelope, record, adapter_exit_code=0,
    ) is False


def test_invalid_chatgpt_envelope_never_persists_forged_telemetry(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "forged-finalize"
    output.mkdir()
    envelope, record = _valid_envelope(stack, output, prompt="finalize trust")
    envelope["duration_ms"] = -5
    envelope["usage"]["input_tokens"] = 1_888_000_000
    envelope["total_cost_usd"] = 777.0
    record.update({
        "job_id": "forged-finalize-job",
        "status": jobs.STATUS_RUNNING,
        "project_id": None,
        "folder_path": None,
    })
    jobs._write_record(record)

    jobs._finalize(record["job_id"], 0, envelope)
    done = jobs.load_record(record["job_id"])

    assert done["status"] == jobs.STATUS_FAILED
    assert done["failure_reason"] == "chatgpt-valid-receipt-required"
    assert "cost" not in done
    assert "model_receipt" not in done
    assert "session_id" not in done


@pytest.mark.parametrize(
    "status,seat_started,timed_out,aborted,tree_verified,adapter_exit",
    (
        ("subscription_auth_required", False, False, False, None, 2),
        ("usage_limit", True, False, False, None, 1),
        ("auth_error", True, False, False, None, 1),
        ("timeout", True, True, False, True, 1),
        ("kill_failed", True, True, False, False, 1),
        ("containment_assignment_failed", False, False, False, None, 2),
        ("containment_assignment_failed", True, False, False, True, 1),
        ("process_tree_straggler", True, False, False, True, 1),
        ("output_limit_exceeded", True, False, False, True, 1),
        ("protocol_limit_exceeded", True, False, False, None, 1),
        ("output_drain_failed", True, False, False, False, 1),
        ("stdin_write_failed", True, False, False, None, 1),
        ("preflight_command_refused", False, False, False, None, 2),
        ("preflight_containment_failed", False, False, False, None, 2),
        ("preflight_spawn_error", False, False, False, None, 2),
        ("preflight_cleanup_failed", False, False, False, None, 2),
        ("preflight_output_limit_exceeded", False, False, False, None, 2),
        ("preflight_aborted", False, False, False, None, 2),
        ("preflight_process_tree_straggler", False, False, False, None, 2),
    ),
)
def test_valid_chatgpt_failure_receipt_is_persisted_honestly(
        stack, status, seat_started, timed_out, aborted, tree_verified,
        adapter_exit):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("failure-" + status)
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, status, seat_started=seat_started,
        timed_out=timed_out, aborted=aborted,
        tree_kill_verified=tree_verified,
    )
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=adapter_exit,
    ) is True
    record.update({
        "job_id": "failure-job-" + status,
        "status": jobs.STATUS_RUNNING,
        "project_id": None,
        "folder_path": None,
    })
    jobs._write_record(record)

    jobs._finalize(record["job_id"], adapter_exit, envelope)
    done = jobs.load_record(record["job_id"])

    assert done["status"] == jobs.STATUS_FAILED
    assert done["failure_reason"] == status
    assert done["adapter_failure_status"] == status
    assert done["failure_detail"] == "safe adapter failure: " + status
    assert done["model_receipt"]["status"] == status
    assert done["cost"]["total_cost_usd"] is None
    assert done["cost"]["cost_state"] == (
        "subscription_covered" if seat_started else "no_seat_started"
    )


def test_preflight_cleanup_failure_accepts_complete_job_evidence(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "preflight-job-close-failure"
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "preflight_cleanup_failed", seat_started=False)
    receipt = envelope["model_receipt"]
    receipt.update(
        preflight_complete_tree_containment=True,
        preflight_output_limits_verified=True,
        preflight_output_drain_verified=True,
        preflight_root_exit_verified=True,
        preflight_windows_job_policy_verified=True,
        preflight_windows_job_assignment_verified=True,
        preflight_windows_job_membership_verified=True,
        preflight_windows_process_handle_verified=True,
        preflight_windows_primary_thread_verified=True,
        preflight_windows_process_resumed=True,
        preflight_windows_job_empty_verified=True,
    )
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=2) is True
    receipt["preflight_containment_kind"] = "posix_process_group_degraded"
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=2) is False


def test_stdin_write_failure_accepts_forced_tree_cleanup(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "stdin-forced-cleanup"
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "stdin_write_failed", seat_started=True,
        tree_kill_verified=True)
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1) is True
    envelope["model_receipt"]["tree_kill_verified"] = False
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1) is False


@pytest.mark.parametrize("field,alias", (
    ("model_attested", 0),
    ("degraded", 1),
))
def test_failure_receipt_rejects_bool_int_aliases(stack, field, alias):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("failure-scalar-alias-" + field)
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "usage_limit", seat_started=True)
    envelope["model_receipt"][field] = alias
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1) is False


def test_posix_overflow_accepts_group_proof_without_tree_claim(
        stack, monkeypatch):
    jobs = stack["jobs"]
    _simulate_posix_parent(jobs, monkeypatch)
    output = stack["tmp"] / "posix-overflow"
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "output_limit_exceeded", seat_started=True,
        tree_kill_verified=False)
    receipt = envelope["model_receipt"]
    receipt["signer_image_binding_verified"] = False
    receipt["process_group_kill_verified"] = True
    assert receipt["complete_tree_containment"] is False
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1) is True
    receipt["process_group_kill_verified"] = False
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1) is False


def test_posix_pre_spawn_failure_retains_degraded_boundary_without_seat(
        stack, monkeypatch):
    jobs = stack["jobs"]
    _simulate_posix_parent(jobs, monkeypatch)
    output = stack["tmp"] / "posix-pre-spawn"
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "spawn_error", seat_started=False)
    receipt = envelope["model_receipt"]
    receipt["signer_image_binding_verified"] = False
    receipt["containment_kind"] = "posix_process_group_degraded"
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=2) is True
    receipt["containment_kind"] = "windows_job"
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=2) is False


@pytest.mark.parametrize("interrupted", (False, True))
def test_genuine_preseat_artifact_scan_failure_round_trips(
        stack, monkeypatch, interrupted):
    jobs = stack["jobs"]
    output = stack["tmp"] / "preseat-artifact-scan"
    output.mkdir()
    prompt = "scan report before starting a seat"
    preflight = _trusted_preflight(jobs)
    preflight.update(ok=True, status="ready")
    preflight["executable_handle_guarded_through_spawn"] = False
    preflight["runtime_guard_rechecked"] = False
    preflight.pop("containment_kind", None)
    for key in jobs._CHATGPT_CONTAINMENT_BOOL_FIELDS:
        preflight.pop(key, None)
    def incomplete_scan(*_args, **_kwargs):
        if interrupted:
            raise KeyboardInterrupt
        return {}, False

    monkeypatch.setattr(
        jobs._codex, "_expected_artifact_snapshot", incomplete_scan)

    def no_spawn(*_args, **_kwargs):
        pytest.fail("artifact pre-scan failure must not spawn a seat")

    envelope, adapter_exit, _native_out, _native_err = jobs._codex.run_codex(
        prompt, output, sandbox="workspace-write",
        preflight_fn=lambda *_args: preflight,
        resolve_fn=lambda _env: preflight["executable_path"],
        popen_impl=no_spawn, expected_artifact_paths=["report.md"])
    receipt = envelope["model_receipt"]
    record = {
        "backend": "chatgpt",
        "relaunch_spec": {
            "prompt": prompt,
            "output_dir": str(output),
            "permission_mode": None,
            "expected_artifacts": ["report.md"],
        },
    }
    assert adapter_exit == (130 if interrupted else 2)
    assert receipt["status"] == "artifact_scan_incomplete"
    assert receipt["seat_started"] is False
    assert receipt["aborted"] is interrupted
    assert receipt["artifact_scan_complete"] is False
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=adapter_exit) is True


def test_genuine_adapter_no_seat_envelope_round_trips_failure_contract(stack):
    jobs = stack["jobs"]
    output = stack["tmp"] / "genuine-no-seat"
    output.mkdir()
    prompt = "genuine no-seat receipt"

    def no_subscription(cmd, _model, _effort, _env):
        return {
            "ok": False,
            "status": "subscription_auth_required",
            "error": "Codex CLI is not logged in using ChatGPT",
            "executable_path": cmd,
            "transport_actual": "codex-cli",
            "cli_version": "codex-cli test",
            "auth_kind": None,
            "auth_probe_at": "2026-08-30T15:00:00+00:00",
            "subscription_auth": False,
            "model_capability_verified": False,
            "ultra_capability_verified": False,
            "config_guard_verified": True,
        }

    envelope, adapter_exit, _native_out, _native_err = jobs._codex.run_codex(
        prompt, output, sandbox="workspace-write",
        preflight_fn=no_subscription,
        expected_artifact_paths=["report.md"],
    )
    record = {
        "backend": "chatgpt",
        "relaunch_spec": {
            "prompt": prompt,
            "output_dir": str(output),
            "permission_mode": None,
            "expected_artifacts": ["report.md"],
        },
    }
    assert adapter_exit == 2
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=adapter_exit,
    ) is True


@pytest.mark.parametrize(
    "tamper", (
        "cost", "usage", "duration", "executable", "drain",
        "signer", "config-ignored", "containment", "execution-possible",
        "job-empty", "root-exit", "mutation-alias",
    ),
)
def test_forged_chatgpt_failure_telemetry_is_not_persisted(stack, tamper):
    jobs = stack["jobs"]
    output = stack["tmp"] / ("forged-failure-" + tamper)
    output.mkdir()
    envelope, record = _failure_envelope(
        stack, output, "usage_limit", seat_started=True,
    )
    if tamper == "cost":
        envelope["total_cost_usd"] = 99.0
    elif tamper == "usage":
        envelope["usage"]["input_tokens"] += 1
    elif tamper == "duration":
        envelope["duration_ms"] = -1
    elif tamper == "executable":
        envelope["model_receipt"]["executable_path"] = str(output / "codex.exe")
    elif tamper == "drain":
        envelope["model_receipt"]["output_drain_verified"] = False
    elif tamper == "signer":
        envelope["model_receipt"]["executable_signer_subject"] = "CN=Other"
    elif tamper == "config-ignored":
        envelope["model_receipt"]["user_config_ignored"] = False
    elif tamper == "containment":
        envelope["model_receipt"]["containment_kind"] = "none"
    elif tamper == "execution-possible":
        envelope["model_receipt"]["windows_execution_possible"] = not (
            envelope["model_receipt"]["windows_execution_possible"])
    elif tamper == "job-empty":
        envelope["model_receipt"]["windows_job_empty_verified"] = not (
            envelope["model_receipt"]["windows_job_empty_verified"])
    elif tamper == "root-exit":
        envelope["model_receipt"]["root_exit_verified"] = not (
            envelope["model_receipt"]["root_exit_verified"])
    elif tamper == "mutation-alias":
        envelope["model_receipt"]["artifact_mutation_verified"] = True
    assert jobs._valid_chatgpt_failure_envelope(
        envelope, record, adapter_exit_code=1,
    ) is False

    record.update({
        "job_id": "forged-failure-job-" + tamper,
        "status": jobs.STATUS_RUNNING,
        "project_id": None,
        "folder_path": None,
    })
    jobs._write_record(record)
    jobs._finalize(record["job_id"], 1, envelope)
    done = jobs.load_record(record["job_id"])
    assert done["failure_reason"] == "chatgpt-valid-receipt-required"
    assert "cost" not in done
    assert "model_receipt" not in done


def test_unconfigured_checkout_ignores_mirror_primary_redirect(tmp_path, monkeypatch):
    primary_dir = tmp_path / "canonical-anchor-data"
    primary_dir.mkdir()
    primary = primary_dir / "settings.json"
    primary.write_text(json.dumps({
        "default_cli": "claude",
        "coding_family": "chatgpt",
        "review_family": "claude",
        "steward_type": "jarvis",
    }), encoding="utf-8")
    home = tmp_path / "mirror-home"
    mirror_dir = home / ".anchor"
    mirror_dir.mkdir(parents=True)
    (mirror_dir / "model_prefs.json").write_text(json.dumps({
        "source": "anchor",
        "default_cli": "claude",
        "coding_family": "grok",
        "review_family": "gemini",
        "primary_path": str(primary),
    }), encoding="utf-8")

    monkeypatch.delenv("ANCHOR_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    assert anchor_settings.settings_path() == paths.data_dir() / "settings.json"
    assert anchor_settings.settings_path() != primary
    assert anchor_settings.get_coding_family() == "grok"
    assert anchor_settings.get_review_family() == "gemini"


def test_explicit_data_dir_ignores_divergent_mirror_primary(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit-data"
    explicit.mkdir()
    (explicit / "settings.json").write_text(json.dumps({
        "coding_family": "claude", "review_family": "grok",
    }), encoding="utf-8")
    other = tmp_path / "other-anchor"
    other.mkdir()
    (other / "settings.json").write_text(json.dumps({
        "coding_family": "chatgpt", "review_family": "claude",
    }), encoding="utf-8")
    home = tmp_path / "divergent-home"
    mirror_dir = home / ".anchor"
    mirror_dir.mkdir(parents=True)
    (mirror_dir / "model_prefs.json").write_text(json.dumps({
        "source": "anchor",
        "coding_family": "chatgpt", "review_family": "claude",
        "primary_path": str(other / "settings.json"),
    }), encoding="utf-8")

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(explicit))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    assert anchor_settings.settings_path() == explicit / "settings.json"
    assert anchor_settings.get_coding_family() == "claude"
    assert anchor_settings.get_review_family() == "grok"


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_dashboard_http_omission_uses_saved_chatgpt_and_explicit_override(stack):
    import gate_adapter
    importlib.reload(gate_adapter)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    server = gui.make_server("127.0.0.1", 0)
    assert server.server_address[1] != 8777
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        chatgpt_project = _project(stack, "HTTP ChatGPT")
        code, body = _post(base + "/api/rnd/launch_lane", {
            "project_id": chatgpt_project["id"], "lane": "research",
        })
        assert code == 200 and body["backend"] == "chatgpt"
        chatgpt_done = stack["jobs"].wait(body["job_id"], timeout=30)
        assert chatgpt_done["status"] == stack["jobs"].STATUS_DONE

        folder = stack["tmp"] / "explicit-gemini-project"
        folder.mkdir()
        gemini_project = stack["registry"].add_project("HTTP Gemini", str(folder))
        code, body = _post(base + "/api/rnd/launch_lane", {
            "project_id": gemini_project["id"], "lane": "research",
            "backend": "gemini",
        })
        assert code == 200 and body["backend"] == "gemini"
        gemini_done = stack["jobs"].wait(body["job_id"], timeout=30)
        assert gemini_done["status"] == stack["jobs"].STATUS_DONE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
