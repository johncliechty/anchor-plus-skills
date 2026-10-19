"""Bounded client for Ecgberht's single-writer refinement CLI.

The CLI owns events, locking, reduction and document projection.  This module
only checks the protocol and transports requests; it never rewrites campaign
files or retries a mutation whose outcome is uncertain.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


PROTOCOL_SCHEMA = "ecgberht-refinement-v1"
DEFAULT_TIMEOUT = 20
CLI_ENV = "ECGBERHT_REFINEMENT_CLI"
SKILLS_ROOT_ENV = "ANCHOR_SKILLS_ROOT"
_NON_EVENT_ACTIONS = frozenset({"capabilities", "read", "operation_status", "repair"})


def _failure(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message, **details}


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _default_cli_candidates() -> list[Path]:
    candidates = [
        Path(__file__).resolve().parents[1] / "vendor" / "bundled-skills" / "ecgberht" / "bin" / "ecgberht.mjs",
        Path(__file__).resolve().parents[2] / "Ecgberht" / "bin" / "ecgberht.mjs",
        Path.home() / ".agents" / "skills" / "ecgberht" / "bin" / "ecgberht.mjs",
        Path.home() / ".claude" / "skills" / "ecgberht" / "bin" / "ecgberht.mjs",
    ]
    return candidates


def _resolve_dependencies(
    cli_path: str | os.PathLike[str] | None,
    node_executable: str | None,
) -> tuple[str, str] | dict[str, Any]:
    """An explicitly configured missing CLI is a failure, never a fallback."""
    explicit_cli = cli_path is not None or CLI_ENV in os.environ
    configured = cli_path if cli_path is not None else os.environ.get(CLI_ENV)
    if explicit_cli:
        if not configured:
            return _failure("dependency-missing", "The configured refinement CLI is empty.", component="cli")
        candidates = [Path(configured).expanduser()]
    elif SKILLS_ROOT_ENV in os.environ:
        explicit_cli = True
        configured_root = os.environ.get(SKILLS_ROOT_ENV)
        if not configured_root:
            return _failure("dependency-missing", "The configured skills root is empty.", component="cli", configured=True)
        candidates = [Path(configured_root).expanduser() / "ecgberht" / "bin" / "ecgberht.mjs"]
    else:
        candidates = _default_cli_candidates()

    try:
        selected = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    except (OSError, ValueError):
        selected = None
    if selected is None:
        return _failure("dependency-missing", "The refinement CLI is unavailable.", component="cli", configured=explicit_cli)

    node = shutil.which(node_executable if node_executable is not None else "node")
    if not node:
        return _failure("dependency-missing", "The Node executable is unavailable.", component="node")
    return node, str(selected)


def _valid_error(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())) or (
        isinstance(value, dict)
        and isinstance(value.get("code"), str)
        and bool(value["code"].strip())
    )


def _valid_state_envelope(result: dict[str, Any]) -> bool:
    state = result.get("state")
    projection = result.get("projection_status")
    return (
        isinstance(state, dict)
        and type(state.get("managed")) is bool
        and _integer(result.get("sequence"))
        and isinstance(projection, dict)
        and type(projection.get("consistent")) is bool
        and (result.get('finished_projection') is None or
             isinstance(result['finished_projection'], dict) and type(result['finished_projection'].get('consistent')) is bool)
    )


def _consistent(result: dict[str, Any]) -> bool:
    return result['projection_status']['consistent'] and (
        result.get('finished_projection') is None or result['finished_projection']['consistent'])


def _validate_envelope(result: Any, payload: dict[str, Any], returncode: int) -> dict[str, Any]:
    invalid = _failure("dependency-returns-garbage", "The refinement CLI returned an invalid protocol response.")
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        return invalid
    if result["ok"] is False:
        # A meaningful CLI failure is authoritative, including on nonzero exit.
        return result if _valid_error(result.get("error")) else invalid
    if returncode != 0:
        return invalid

    action = payload["action"]
    if action == "capabilities":
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict):
            return invalid
        if capabilities.get("schema") != PROTOCOL_SCHEMA or type(capabilities.get("version")) is not int or capabilities["version"] != 1:
            return _failure("dependency-incompatible", "The refinement CLI does not support the required protocol.")
        return result
    if not _valid_state_envelope(result):
        return invalid
    if action == "repair" and "consistent" in result:
        if type(result["consistent"]) is not bool or result["consistent"] != _consistent(result):
            return invalid
    if action == "operation_status":
        if result.get("operation_id") != payload["operation_id"] or type(result.get("committed")) is not bool:
            return invalid
    elif action not in {"read", "repair"}:
        if result.get("committed") is not True or type(result.get("consistent")) is not bool:
            return invalid
        if result["consistent"] != _consistent(result):
            return invalid
        if "operation_id" in result and result["operation_id"] != payload["operation_id"]:
            return invalid
    return result


def _run(
    dependencies: tuple[str, str],
    campaign_dir: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    node, cli = dependencies
    try:
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n"
    except (TypeError, ValueError):
        return _failure("invalid-request", "The refinement request must contain valid JSON values.")
    try:
        completed = subprocess.run(
            [node, cli, "refinement-update", "--project", campaign_dir],
            input=serialized,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for the owned child before raising.
        return _failure("dependency-slow-or-killed", "The refinement CLI exceeded its time limit.", reason="timeout", interrupted=True)
    except FileNotFoundError:
        return _failure("dependency-missing", "The refinement executable disappeared before launch.")
    except UnicodeError:
        return _failure("dependency-returns-garbage", "The refinement CLI returned invalid UTF-8.")
    except OSError:
        return _failure("dependency-unavailable", "The refinement CLI could not be launched.")

    if not completed.stdout or not completed.stdout.strip():
        if completed.returncode != 0:
            return _failure("dependency-slow-or-killed", "The refinement CLI exited without a protocol response.", reason="exit-without-response", interrupted=True, exit_code=completed.returncode)
        return _failure("dependency-returns-garbage", "The refinement CLI returned an empty protocol response.")
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError):
        return _failure("dependency-returns-garbage", "The refinement CLI returned invalid JSON.")
    return _validate_envelope(result, payload, completed.returncode)


def _reconcile(
    dependencies: tuple[str, str],
    campaign_dir: str,
    payload: dict[str, Any],
    timeout: float,
    interrupted: dict[str, Any],
) -> dict[str, Any]:
    operation_id = payload["operation_id"]
    status = _run(dependencies, campaign_dir, {"action": "operation_status", "operation_id": operation_id}, timeout)
    if not status["ok"]:
        return {**interrupted, "operation_id": operation_id, "commit_status": "unknown", "reconciliation": status}
    if not status["committed"]:
        return {**interrupted, "operation_id": operation_id, "commit_status": "not-observed", "sequence": status["sequence"]}

    # Operation identity and persisted state, rather than process exit, establish
    # the commit.  A committed operation is not proof that projections repaired.
    if not _consistent(status):
        return _failure(
            "committed-needs-repair",
            "The operation committed, but its document projections need repair.",
            operation_id=operation_id,
            committed=True,
            consistent=False,
            interrupted=True,
            state=status["state"],
            sequence=status["sequence"],
            projection_status=status["projection_status"],
            finished_projection=status.get('finished_projection'),
        )
    return {
        "ok": True,
        "operation_id": operation_id,
        "committed": True,
        "consistent": True,
        "state": status["state"],
        "sequence": status["sequence"],
        "projection_status": status["projection_status"],
        "reconciled_after_interruption": True,
    }


def _error_code(result: dict[str, Any]) -> str | None:
    error = result.get("error")
    return error.get("code") if isinstance(error, dict) else error


def _repairable(result: dict[str, Any]) -> bool:
    # These codes identify a known lagging projection.  In particular, a
    # managed-content-conflict or malformed/missing fence is never repairable
    # merely because an event committed before that conflict was detected.
    return _error_code(result) in {"projection-lag", "committed-needs-repair"} or (
        result.get("ok") is True
        and result.get("committed") is True
        and result.get("consistent") is False
    )


def _recovery_failure(
    failure: dict[str, Any],
    original: dict[str, Any],
    operation_id: str,
    stage: str,
) -> dict[str, Any]:
    result = {
        **failure,
        "operation_id": operation_id,
        "recovery": {"attempted": "repair", "stage": stage, "original_error": _error_code(original)},
    }
    if original.get("committed") is True:
        result["committed"] = True
        for key in ('state','sequence','projection_status','finished_projection'):
            if key in original:result.setdefault(key,original[key])
    return result


def _recover_projection(
    dependencies: tuple[str, str],
    campaign_dir: str,
    payload: dict[str, Any],
    timeout: float,
    original: dict[str, Any],
) -> dict[str, Any]:
    """Repair known derived-document lag once, then inspect this operation.

    Repair does not create a roadmap event.  The CLI owns its lock and decides
    whether the projection is repairable; this client never edits a document.
    """
    operation_id = payload["operation_id"]
    repaired = _run(dependencies, campaign_dir, {"action": "repair"}, timeout)
    if not repaired["ok"]:
        return _recovery_failure(repaired, original, operation_id, "repair")
    if not _consistent(repaired):
        failure = _failure("projection-lag", "A derived document or Finished collection remains inconsistent after repair.", consistent=False,
                           finished_projection=repaired.get('finished_projection'))
        return _recovery_failure(failure, original, operation_id, "repair")

    status = _run(dependencies, campaign_dir, {"action": "operation_status", "operation_id": operation_id}, timeout)
    if not status["ok"]:
        return _recovery_failure(status, original, operation_id, "operation_status")
    if status["committed"]:
        if not _consistent(status):
            failure = _failure(
                "committed-needs-repair",
                "The operation committed, but its document projections remain inconsistent.",
                committed=True,
                consistent=False,
                state=status["state"],
                sequence=status["sequence"],
                projection_status=status["projection_status"],
            )
            return _recovery_failure(failure, original, operation_id, "operation_status")
        return {
            "ok": True,
            "operation_id": operation_id,
            "committed": True,
            "consistent": True,
            "state": status["state"],
            "sequence": status["sequence"],
            "projection_status": status["projection_status"],
            "recovered_after_projection_repair": True,
        }

    # A contradictory or lagging status cannot justify a fresh submission.
    if original.get("committed") is True:
        failure = _failure("dependency-returns-garbage", "Operation reconciliation contradicted the confirmed commit.")
        return _recovery_failure(failure, original, operation_id, "operation_status")
    if not _consistent(status):
        failure = _failure("projection-lag", "Document projections changed after repair.", consistent=False)
        return _recovery_failure(failure, original, operation_id, "operation_status")

    # Only a confirmed absent operation can be attempted again.  Preserve the
    # exact operation ID, payload and expected sequence; a stale CAS stays a
    # conflict.  Do not recurse into another repair if this attempt also fails.
    retried = _run(dependencies, campaign_dir, payload, timeout)
    if retried.get("interrupted") is True and _error_code(retried) == "dependency-slow-or-killed":
        return _reconcile(dependencies, campaign_dir, payload, timeout, retried)
    return retried


def invoke(
    campaign_dir: str | os.PathLike[str],
    payload: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
    *,
    cli_path: str | os.PathLike[str] | None = None,
    node_executable: str | None = None,
) -> dict[str, Any]:
    """Call the CLI with a bounded capability check and optional reconciliation.

    Each child has its own ``timeout`` budget (20 seconds by default).  An
    interrupted mutation is reconciled by ID.  Known document lag permits one
    CLI repair and another status read; only a confirmed absent operation can
    be submitted once more, with the exact same payload and expected sequence.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str) or not payload["action"].strip():
        return _failure("invalid-request", "A refinement action is required.")
    action = payload["action"]
    mutation = action not in _NON_EVENT_ACTIONS
    if action == "operation_status" or mutation:
        if not isinstance(payload.get("operation_id"), str) or not payload["operation_id"].strip():
            return _failure("invalid-request", "A stable operation_id is required.")
    if mutation and not _integer(payload.get("expected_seq")):
        return _failure("invalid-request", "A nonnegative expected_seq is required.")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        return _failure("invalid-request", "The CLI timeout must be a positive finite number.")
    try:
        project = os.fspath(campaign_dir)
    except TypeError:
        return _failure("invalid-request", "A campaign directory is required.")
    if not isinstance(project, str) or not project.strip():
        return _failure("invalid-request", "A campaign directory is required.")

    dependencies = _resolve_dependencies(cli_path, node_executable)
    if isinstance(dependencies, dict):
        return dependencies
    if action != "capabilities":
        capabilities = _run(dependencies, project, {"action": "capabilities"}, timeout)
        if not capabilities["ok"]:
            return capabilities
        if action in {"producer_handoff", "resolve_handoff"} and action not in capabilities.get("capabilities", {}).get("actions", []):
            return _failure("dependency-incompatible", "The installed refinement CLI lacks producer handoffs; update the bundled or explicitly selected skill.")
    result = _run(dependencies, project, payload, timeout)
    if mutation and result.get("interrupted") is True and result.get("error") == "dependency-slow-or-killed":
        result = _reconcile(dependencies, project, payload, timeout, result)
    if mutation and _repairable(result):
        return _recover_projection(dependencies, project, payload, timeout, result)
    return result


def read_state(campaign_dir: str | os.PathLike[str], **kwargs: Any) -> dict[str, Any]:
    """Read managed or explicitly unmanaged state without creating a store."""
    return invoke(campaign_dir, {"action": "read"}, **kwargs)


def update(campaign_dir: str | os.PathLike[str], operation: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Submit one logical operation, recovering known document lag at most once."""
    if not isinstance(operation, dict) or operation.get("action") in _NON_EVENT_ACTIONS:
        return _failure("invalid-request", "update requires a mutating refinement operation.")
    try:   # before the write, so the write itself is announced (never taken as the effort's baseline)
        import deliverables_register
        deliverables_register.receipt_baseline(campaign_dir)
    except Exception:
        pass
    result = invoke(campaign_dir, operation, **kwargs)
    if isinstance(result, dict) and result.get("ok"):
        try:   # the managed writer: a new version is announced in the steward's dialogue (execution minimum item 2)
            import deliverables_register
            deliverables_register.notify_receipt(campaign_dir)
        except Exception:
            pass
    return result
