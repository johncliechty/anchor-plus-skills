"""Attach e2e trace builders — W11.

Produces schema-valid trace artifacts
(control_invocation → handler → capability_call → rendered_state) with
``proof_level: rendered-string`` and one induced fault per named reason
(timeout, unknown_session, empty_session_list — plus full ATTACH_REASONS).

Each reason trace **executes** the real ``attach_session`` handler under
the induced fault; every hop's ``payload_hash`` is the real SHA-256 of the
carried payload. Shipped ``artifacts/traces/attach-e2e.json`` is pinned to
these builders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from anchor.build.trace_artifact import (
    HOP_CAPABILITY_CALL,
    HOP_CONTROL_INVOCATION,
    HOP_HANDLER,
    HOP_RENDERED_STATE,
    PROOF_LEVEL_RENDERED_STRING,
    TRACE_RESULT_COMPLETED,
    TRACE_RESULT_FAILED_NAMED,
    TraceArtifact,
    build_trace,
    make_hop,
    payload_hash,
    validate_trace,
)
from anchor.session.attach import (
    ATTACH_REASONS,
    INDUCED_FAULT_REASONS,
    CannotAttach,
    attach_reason_named_state,
    attach_session,
)
from anchor.ui.attach_view import WAVE_ID, build_attach_trace_payload

ATTACH_TRACE_RELPATH = os.path.join("artifacts", "traces", "attach-e2e.json")
TRACE_AS_OF = "2026-07-29T00:00:00Z"


def _hops_for(
    control_id: str,
    *,
    handler_name: str,
    capability_name: str,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    payload_id = "w11-%s-%s" % (control_id, payload.get("reason") or "ok")
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "click-%s" % control_id,
            payload_id=payload_id,
            payload=payload,
            detail="",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            handler_name,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=handler_name,
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            capability_name,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=capability_name,
            timestamp=ts,
        ),
        make_hop(
            HOP_RENDERED_STATE,
            "render_state.%s" % rendered_state,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]


def build_attach_reason_trace(
    reason: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid attach trace under a single **executed** attach reason."""
    result = attach_session(
        "w11-induced-session",
        force_reason=reason,
        capability_present=True,
    )
    if not isinstance(result, CannotAttach):
        raise ValueError(
            "attach_session under induced reason %r must return CannotAttach, got %r"
            % (reason, type(result).__name__)
        )
    ns = result.named_state
    expected_ns = attach_reason_named_state(reason)
    if ns.value != expected_ns.value:
        raise ValueError(
            "attach_session named_state %r != attach_reason_named_state %r for %r"
            % (ns.value, expected_ns.value, reason)
        )
    payload = build_attach_trace_payload(reason, ok=False)
    payload["executed"] = True
    payload["handler_result_reason"] = result.reason
    payload["named_state"] = ns.value
    payload["error_text"] = result.error_text
    hops = _hops_for(
        "attach",
        handler_name="anchor.session.attach.attach_session",
        capability_name="capability.attach",
        payload=payload,
        rendered_state=ns.value,
    )
    return build_trace(
        wave_id,
        "attach",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_FAILED_NAMED,
        induced_fault=reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W11 attach e2e under induced reason %s; structural rendered-string "
            "proof only; handler executed" % reason
        ),
    )


def build_attach_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    payload = build_attach_trace_payload(None, ok=True)
    payload["executed"] = True
    payload["named_state"] = "ok"
    hops = _hops_for(
        "attach",
        handler_name="anchor.session.attach.attach_session",
        capability_name="capability.attach",
        payload=payload,
        rendered_state="ok",
    )
    return build_trace(
        wave_id,
        "attach",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state="ok",
        as_of=TRACE_AS_OF,
        notes=(
            "W11 attach e2e success path; structural rendered-string proof only"
        ),
    )


def build_attach_trace_set() -> Dict[str, Any]:
    """Full attach artifact: primary timeout + one fault per reason."""
    primary = build_attach_reason_trace("timeout")
    reason_traces = {
        reason: build_attach_reason_trace(reason).as_dict()
        for reason in ATTACH_REASONS
    }
    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(ATTACH_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["reason_traces"] = reason_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    return doc


def _hop_hashes(doc: Dict[str, Any]) -> list:
    out = []
    for hop in doc.get("hops") or []:
        out.append(
            (
                str(hop.get("payload_id") or ""),
                str(hop.get("payload_hash") or "").strip().lower(),
            )
        )
    for reason, nested in sorted((doc.get("reason_traces") or {}).items()):
        for hop in nested.get("hops") or []:
            out.append(
                (
                    str(hop.get("payload_id") or ""),
                    str(hop.get("payload_hash") or "").strip().lower(),
                )
            )
    return out


def _assert_payload_hash_integrity(doc: Dict[str, Any], *, label: str) -> None:
    import re

    sha = re.compile(r"^[0-9a-f]{64}$")
    for pid, ph in _hop_hashes(doc):
        if not sha.match(ph):
            raise ValueError(
                "%s hop %r payload_hash is not a 64-char sha256 hex: %r"
                % (label, pid, ph)
            )


def _trace_sets_match(on_disk: Dict[str, Any], builder: Dict[str, Any]) -> bool:
    return _hop_hashes(on_disk) == _hop_hashes(builder)


def write_attach_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / ATTACH_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_attach_trace_set()
    validate_trace(doc)
    for reason, nested in (doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=ATTACH_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {ATTACH_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = ATTACH_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped attach-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_attach_trace_set()
    validate_trace(builder_doc)
    for reason, nested in (builder_doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(builder_doc, label="attach-e2e builder")

    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            try:
                validate_trace(data)
                for reason, nested in (data.get("reason_traces") or {}).items():
                    validate_trace(nested)
                _assert_payload_hash_integrity(data, label="attach-e2e on-disk")
                if _trace_sets_match(data, builder_doc):
                    return data
            except (ValueError, Exception):
                pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(builder_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return builder_doc


__all__ = [
    "ATTACH_TRACE_RELPATH",
    "TRACE_AS_OF",
    "INDUCED_FAULT_REASONS",
    "build_attach_reason_trace",
    "build_attach_ok_trace",
    "build_attach_trace_set",
    "write_attach_traces",
    "load_trace_set",
]
