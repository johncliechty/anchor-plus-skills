#!/usr/bin/env python3
"""Receipt-bearing child seam that exercises codex_adapter.main() UTF-8 pipes."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codex_adapter as adapter


def _fake_run(prompt, target, sandbox="read-only", timeout_seconds=0,
              expected_artifact_paths=None, **_kwargs):
    artifact_paths = []
    artifact_hashes = {}
    artifact_evidence = {}
    if sandbox == "workspace-write":
        for rel in expected_artifact_paths or ():
            artifact = Path(target).resolve() / rel
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("FAKE_CODEX_ARTIFACT\n", encoding="utf-8")
            artifact_paths.append(Path(rel).as_posix())
            artifact_hashes[Path(rel).as_posix()] = __import__("hashlib").sha256(
                artifact.read_bytes()
            ).hexdigest()
            artifact_evidence[Path(rel).as_posix()] = \
                adapter._artifact_file_evidence(Path(target).resolve(), Path(rel).as_posix())
    answer = "%s\nFAKE_CODEX_UNICODE → — é ✓ 中\nTARGET=%s" % (
        prompt, Path(target).resolve().name,
    )
    parsed = {
        "thread_id": "fake-codex-thread-unicode",
        "usage": {
            "input_tokens": 21,
            "cached_input_tokens": 8,
            "cache_write_input_tokens": 0,
            "output_tokens": 7,
            "reasoning_output_tokens": 2,
        },
        "event_count": 3,
        "malformed_count": 0,
    }
    executable_path = adapter.resolve_codex_cmd()
    provenance = adapter.inspect_executable(executable_path)
    if provenance.get("ok") is not True:
        raise RuntimeError("fake receipt could not attest installed Codex")
    preflight = {
        "ok": True,
        "status": "ready",
        # Match the same pinned resolver Anchor validates in the parent. The
        # transport itself remains fake; only the receipt contract is under test.
        "executable_path": executable_path,
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
        "cli_version": "codex-cli test-unicode",
        "auth_kind": "chatgpt_subscription",
        "auth_probe_at": "2026-08-30T15:00:00+00:00",
        "subscription_auth": True,
        "model_capability_verified": True,
        "selected_model": _kwargs.get("model"),
        "selected_effort": _kwargs.get("effort"),
        "highest_effort_verified": True,
        "ultra_capability_verified": True,
        "user_config_ignored": True,
        "config_guard_verified": True,
        "codex_home": adapter.subscription_only_env()["CODEX_HOME"],
        "critical_overrides_enforced": True,
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
    if adapter.os.name == "nt":
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
            "windows_job" if adapter.os.name == "nt"
            else "posix_process_group_degraded"),
        preflight_complete_tree_containment=(adapter.os.name == "nt"),
        preflight_no_inference_verified=True,
        preflight_no_network_intent_verified=True,
        preflight_output_limits_verified=True,
        preflight_output_drain_verified=True,
        preflight_root_exit_verified=True,
        preflight_windows_job_policy_verified=(adapter.os.name == "nt"),
        preflight_windows_job_assignment_verified=(adapter.os.name == "nt"),
        preflight_windows_job_membership_verified=(adapter.os.name == "nt"),
        preflight_windows_process_handle_verified=(adapter.os.name == "nt"),
        preflight_windows_primary_thread_verified=(adapter.os.name == "nt"),
        preflight_windows_process_resumed=(adapter.os.name == "nt"),
        preflight_windows_job_empty_verified=(adapter.os.name == "nt"),
        preflight_process_group_kill_verified=None,
    )
    receipt = adapter.build_receipt(
        status="success", prompt=prompt, sandbox=sandbox,
        preflight=preflight, parsed=parsed, exit_code=0, seat_started=True,
        artifact_paths=artifact_paths,
        expected_artifact_paths=list(expected_artifact_paths or ()),
        artifact_hashes=artifact_hashes,
        artifact_evidence=artifact_evidence,
        artifact_contract_verified=True,
        artifact_mutation_verified=(sandbox == "workspace-write"),
        output_drain_verified=True,
        output_limits_verified=True, output_eof_verified=True,
        stdin_write_verified=True, stdin_close_verified=True,
        native_stdout_bytes=256, native_stderr_bytes=0,
    )
    envelope = adapter.normalized_result(answer, receipt, 12, False)
    native = "\n".join((
        json.dumps({"type": "thread.started", "thread_id": parsed["thread_id"]},
                   ensure_ascii=False),
        json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": answer,
        }}, ensure_ascii=False),
        json.dumps({"type": "turn.completed", "usage": parsed["usage"]},
                   ensure_ascii=False),
    ))
    return envelope, 0, native, ""


adapter.run_codex = _fake_run

if __name__ == "__main__":
    raise SystemExit(adapter.main())
