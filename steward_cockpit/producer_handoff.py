"""Record producer completion for review through the existing refinement CLI.

This module captures dispatch context and records an explicit output inventory.
It never discovers files, publishes a deliverable, closes a slice, or invents
missing provenance.  The reducer decides whether captured context is current.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import json
import re

from . import refinement_client


def capture_dispatch(cwd):
    """Capture the exact dispatched campaign, without discovering a parent."""
    try:
        if not cwd or not (Path(cwd) / "roadmap.json").is_file():
            return None
        return capture_context(cwd)
    except Exception as exc:
        return {
            "ok": False,
            "error": "dispatch-context-failed",
            "message": f"Could not capture refinement dispatch context: {exc}",
        }


def record_terminal(rec):
    """Record an observed job terminal state through the shared handoff ledger."""
    try:
        if rec.get("metadata_only") is True:
            # Server-labelled summary jobs retain ordinary job/usage records.
            # They do not produce campaign work for a human to inspect.
            return None
        status = rec.get("status")
        if status not in {"done", "failed", "cancelled", "interrupted"}:
            return None
        campaign_dir = (
            rec.get("refinement_dir")
            or rec.get("effort_dir")
            or rec.get("folder_path")
        )
        if not campaign_dir or not (Path(campaign_dir) / "roadmap.json").is_file():
            return None
        job_id = rec.get("job_id")
        result = record_handoff(
            campaign_dir,
            producer_kind="job",
            producer_id=job_id,
            source_ref=f"Anchor job {job_id}",
            context=rec.get("refinement_context"),
            terminal=status,
        )
        try:
            from . import horizon as _horizon
            # W3 (2026-09-28): the line follows a run's end — produced, or stalled when it failed
            _horizon.refresh(campaign_dir, "produced" if status == "done" else "stalled")
        except Exception:
            pass
        if (
            isinstance(result, dict)
            and result.get("ok")
            and (result.get("skipped") or result.get("managed") is False)
        ):
            return {
                **result,
                "ok": False,
                "error": "campaign-not-managed",
                "skipped": True,
                "message": "No managed campaign ledger handoff was recorded.",
            }
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": "job-handoff-failed",
            "message": f"Could not record the job terminal handoff: {exc}",
        }


_PRODUCERS = frozenset({"job", "conversation", "terminal"})
_CONTEXT_FIELDS = ("round", "requirements", "candidate", "depends_on")


def _failure(message):
    return {"ok": False, "error": "invalid-producer-handoff", "message": message}


def _read(campaign_dir):
    result = refinement_client.read_state(campaign_dir)
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        return {"ok": False, "error": "invalid-refinement-state", "message": "The refinement reader returned an invalid response."}
    if result["ok"] is False:
        return result
    state = result.get("state")
    if not isinstance(state, dict) or type(state.get("managed")) is not bool:
        return {"ok": False, "error": "invalid-refinement-state", "message": "The refinement reader returned an invalid state."}
    if type(result.get("sequence")) is not int or result["sequence"] < 0:
        return {"ok": False, "error": "invalid-refinement-state", "message": "The refinement reader returned an invalid sequence."}
    return result


def capture_context(campaign_dir, step_id=None):
    """Capture one explicitly mapped or sole unfinished slice at dispatch."""
    result = _read(campaign_dir)
    if not result["ok"]:
        return result
    state = result["state"]
    if not state["managed"]:
        return None
    slices = state.get("slices")
    if not isinstance(slices, dict):
        return None
    if step_id is not None:
        if not isinstance(step_id, str) or step_id not in slices:
            return None
        selected = step_id
    else:
        unfinished = [key for key, value in slices.items()
                      if isinstance(key, str) and isinstance(value, dict) and value.get("phase") != "done"]
        if len(unfinished) != 1:
            return None
        selected = unfinished[0]
    slice_state = slices[selected]
    if not isinstance(slice_state, dict):
        return None
    return {"step_id": selected, **{key: deepcopy(slice_state.get(key)) for key in _CONTEXT_FIELDS}}


def _handoff_id(producer_kind, producer_id):
    encoded = json.dumps([producer_kind, producer_id], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "producer-handoff-" + hashlib.sha256(encoded).hexdigest()


def _existing(result, handoff_id):
    handoffs = result["state"].get("producer_handoffs")
    if not isinstance(handoffs, dict) or handoff_id not in handoffs:
        return None
    return {"ok": True, "idempotent": True, "handoff_id": handoff_id,
            "handoff": deepcopy(handoffs[handoff_id]), "sequence": result["sequence"]}


def _error_code(result):
    error = result.get("error") if isinstance(result, dict) else None
    return error.get("code") if isinstance(error, dict) else error


def _capture_warning(context):
    code = _error_code(context)
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", code):
        code = "dispatch-context-unavailable"
    return {"error": code}


def _with_context_warning(result, warning):
    return {**result, "context_warning": dict(warning)} if warning is not None and isinstance(result, dict) else result


def record_handoff(campaign_dir, producer_kind, producer_id, source_ref,
                   context=None, outputs=None, inventory_complete=False, terminal="done"):
    """Record one idempotent handoff; retry a CAS conflict at most once."""
    context_warning = None
    if isinstance(context, dict) and context.get("ok") is False:
        # A dispatch-time read failure does not erase work that subsequently
        # completed. Preserve the diagnostic code, without presenting the
        # failure envelope as a snapshot or copying private diagnostic text.
        context_warning = _capture_warning(context)
        context = None
    if not isinstance(producer_kind, str) or producer_kind not in _PRODUCERS:
        return _failure("The producer kind must be job, conversation, or terminal.")
    if not isinstance(producer_id, str) or not producer_id.strip():
        return _failure("A stable producer ID is required.")
    if context is not None:
        if not isinstance(context, dict) or not isinstance(context.get("step_id"), str) or not context["step_id"]:
            return _failure("Dispatch context must identify its captured step.")
        if any(key not in context for key in _CONTEXT_FIELDS):
            return _failure("Dispatch context must retain its complete captured state.")
    if outputs is not None and not isinstance(outputs, list):
        return _failure("The output inventory must be an explicit list.")
    if type(inventory_complete) is not bool:
        return _failure("Inventory completeness must be explicit.")
    if not isinstance(terminal, str) or not terminal:
        return _failure("The producer terminal state is required.")

    result = _read(campaign_dir)
    if not result["ok"]:
        return _with_context_warning(result, context_warning)
    if not result["state"]["managed"]:
        return _with_context_warning({"ok": True, "skipped": True, "reason": "unmanaged"}, context_warning)
    identifier = _handoff_id(producer_kind, producer_id)
    existing = _existing(result, identifier)
    if existing is not None:
        return _with_context_warning(existing, context_warning)

    operation = {
        "action": "producer_handoff", "version": 1,
        "operation_id": identifier, "handoff_id": identifier,
        "expected_seq": result["sequence"],
        "step_id": context["step_id"] if context is not None else None,
        "producer_kind": producer_kind, "source_ref": deepcopy(source_ref),
        "dispatch_context": deepcopy(context),
        "outputs": deepcopy(outputs) if outputs is not None else [],
        "inventory_complete": inventory_complete, "terminal": terminal,
    }
    if context_warning is not None:
        operation["dispatch_error"] = context_warning["error"]
    outcome = refinement_client.update(campaign_dir, operation)
    conflict = _error_code(outcome)
    if not isinstance(outcome, dict) or outcome.get("ok") is not False or conflict not in {"sequence-conflict", "HANDOFF_EXISTS"}:
        return _with_context_warning(outcome, context_warning)

    # Re-read only to establish whether this exact handoff already committed
    # and obtain a new CAS sequence.  Never refresh its dispatch-time context.
    refreshed = _read(campaign_dir)
    if not refreshed["ok"]:
        return _with_context_warning(refreshed, context_warning)
    if not refreshed["state"]["managed"]:
        return _with_context_warning(outcome, context_warning)
    existing = _existing(refreshed, identifier)
    if existing is not None:
        return _with_context_warning(existing, context_warning)
    if conflict == "HANDOFF_EXISTS":
        return _with_context_warning(outcome, context_warning)
    retried = {**operation, "expected_seq": refreshed["sequence"]}
    return _with_context_warning(refinement_client.update(campaign_dir, retried), context_warning)
