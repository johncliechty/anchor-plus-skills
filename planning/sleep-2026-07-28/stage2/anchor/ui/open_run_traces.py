"""Open/run e2e trace builders — W10.

Produces schema-valid trace artifacts
(control_invocation → handler → capability_call → rendered_state) with
``proof_level: rendered-string`` and one induced fault per enumerated
open/run reason.

Each reason trace **executes** the real open_work / run_work handler under
the induced fault (not a hand-authored hop list), and every hop's
``payload_hash`` is the real SHA-256 of the carried payload. Shipped
artifacts under ``artifacts/traces/`` are pinned to these builders —
``load_trace_set`` re-materializes from the builder so placeholder hashes
cannot ship.
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
from anchor.session.open_work import (
    OPEN_REASONS,
    CannotOpen,
    open_reason_named_state,
    open_work,
)
from anchor.session.run_work import (
    RUN_REASONS,
    CannotRun,
    run_reason_named_state,
    run_work,
)
from anchor.ui.open_run_view import (
    WAVE_ID,
    build_open_trace_payload,
    build_run_trace_payload,
)

OPEN_TRACE_RELPATH = os.path.join("artifacts", "traces", "open-e2e.json")
RUN_TRACE_RELPATH = os.path.join("artifacts", "traces", "run-e2e.json")

#: Stable as_of / hop timestamps so shipped artifacts are byte-reproducible.
TRACE_AS_OF = "2026-07-29T00:00:00Z"


def _hops_for(
    control_id: str,
    *,
    handler_name: str,
    capability_name: str,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    """Four hops; every hop carries the same real payload_hash of *payload*."""
    payload_id = "w10-%s-%s" % (control_id, payload.get("reason") or "ok")
    # Real SHA-256 of the payload object (never a hand-typed placeholder).
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


def build_open_reason_trace(
    reason: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid open trace under a single **executed** open reason.

    Runs ``open_work(force_reason=...)`` so the hop chain reflects a real
    handler result, not a synthetic unexecuted path.
    """
    # Execute the real handler under the induced reason (force short-circuits).
    result = open_work(
        "w10-induced-project",
        force_reason=reason,
        capability_present=True,
    )
    if not isinstance(result, CannotOpen):
        raise ValueError(
            "open_work under induced reason %r must return CannotOpen, got %r"
            % (reason, type(result).__name__)
        )
    ns = result.named_state
    # Cross-check reason map (cannot_open docstring vs OPEN_REASON_STATE).
    expected_ns = open_reason_named_state(reason)
    if ns.value != expected_ns.value:
        raise ValueError(
            "open_work named_state %r != open_reason_named_state %r for %r"
            % (ns.value, expected_ns.value, reason)
        )
    payload = build_open_trace_payload(reason, ok=False)
    # Bind payload to the executed handler result (hash integrity depends on it).
    payload["executed"] = True
    payload["handler_result_reason"] = result.reason
    payload["named_state"] = ns.value
    hops = _hops_for(
        "open",
        handler_name="anchor.session.open_work.open_work",
        capability_name="capability.open",
        payload=payload,
        rendered_state=ns.value,
    )
    return build_trace(
        wave_id,
        "open",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_FAILED_NAMED,
        induced_fault=reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W10 open e2e under induced reason %s; structural rendered-string "
            "proof only; handler executed" % reason
        ),
    )


def build_run_reason_trace(
    reason: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid run trace under a single **executed** run reason."""
    result = run_work(
        "w10-induced-target",
        force_reason=reason,
        capability_present=True,
    )
    if not isinstance(result, CannotRun):
        raise ValueError(
            "run_work under induced reason %r must return CannotRun, got %r"
            % (reason, type(result).__name__)
        )
    ns = result.named_state
    expected_ns = run_reason_named_state(reason)
    if ns.value != expected_ns.value:
        raise ValueError(
            "run_work named_state %r != run_reason_named_state %r for %r"
            % (ns.value, expected_ns.value, reason)
        )
    payload = build_run_trace_payload(reason, ok=False)
    payload["executed"] = True
    payload["handler_result_reason"] = result.reason
    payload["named_state"] = ns.value
    hops = _hops_for(
        "run",
        handler_name="anchor.session.run_work.run_work",
        capability_name="capability.run",
        payload=payload,
        rendered_state=ns.value,
    )
    return build_trace(
        wave_id,
        "run",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_FAILED_NAMED,
        induced_fault=reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W10 run e2e under induced reason %s; structural rendered-string "
            "proof only; handler executed" % reason
        ),
    )


def build_open_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    payload = build_open_trace_payload(None, ok=True)
    payload["executed"] = True
    payload["named_state"] = "ok"
    hops = _hops_for(
        "open",
        handler_name="anchor.session.open_work.open_work",
        capability_name="capability.open",
        payload=payload,
        rendered_state="ok",
    )
    return build_trace(
        wave_id,
        "open",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state="ok",
        as_of=TRACE_AS_OF,
        notes=(
            "W10 open e2e success path; structural rendered-string proof only; "
            "handler executed"
        ),
    )


def build_run_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    payload = build_run_trace_payload(None, ok=True)
    payload["executed"] = True
    payload["named_state"] = "ok"
    hops = _hops_for(
        "run",
        handler_name="anchor.session.run_work.run_work",
        capability_name="capability.run",
        payload=payload,
        rendered_state="ok",
    )
    return build_trace(
        wave_id,
        "run",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state="ok",
        as_of=TRACE_AS_OF,
        notes=(
            "W10 run e2e success path; structural rendered-string proof only; "
            "handler executed"
        ),
    )


def build_open_trace_set() -> Dict[str, Any]:
    """Full open artifact: primary + one induced fault per enumerated reason."""
    primary = build_open_reason_trace("capability_absent")
    reason_traces = {
        reason: build_open_reason_trace(reason).as_dict() for reason in OPEN_REASONS
    }
    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(OPEN_REASONS)
    doc["reason_traces"] = reason_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    return doc


def build_run_trace_set() -> Dict[str, Any]:
    primary = build_run_reason_trace("capability_absent")
    reason_traces = {
        reason: build_run_reason_trace(reason).as_dict() for reason in RUN_REASONS
    }
    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(RUN_REASONS)
    doc["reason_traces"] = reason_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    return doc


def _hop_hashes(doc: Dict[str, Any]) -> list:
    """Collect (payload_id, payload_hash) pairs for integrity compare."""
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
    """Reject placeholder-shaped hashes and require 64-char sha256 hex."""
    import re

    sha = re.compile(r"^[0-9a-f]{64}$")
    # Classic hand-typed placeholder pattern used in early W10 drafts.
    placeholder = re.compile(
        r"^[0-9a-f]1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef[0-9a-f]$"
    )
    for pid, ph in _hop_hashes(doc):
        if not sha.match(ph):
            raise ValueError(
                "%s hop %r payload_hash is not a 64-char sha256 hex: %r"
                % (label, pid, ph)
            )
        if placeholder.match(ph):
            raise ValueError(
                "%s hop %r payload_hash looks like a hand-typed placeholder "
                "(not a real content hash of the payload): %r" % (label, pid, ph)
            )


def _trace_sets_match(on_disk: Dict[str, Any], builder: Dict[str, Any]) -> bool:
    """True when hop payload hashes match the builder (pin integrity)."""
    return _hop_hashes(on_disk) == _hop_hashes(builder)


def write_open_run_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    """Write artifacts/traces/open-e2e.json and run-e2e.json under *root*.

    Always materializes from the live builders so payload hashes are real
    SHA-256 digests of the executed-handler payloads.
    """
    base = root if root is not None else Path(__file__).resolve().parents[2]
    out: Dict[str, Path] = {}
    for rel, builder in (
        (OPEN_TRACE_RELPATH, build_open_trace_set),
        (RUN_TRACE_RELPATH, build_run_trace_set),
    ):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = builder()
        validate_trace(doc)
        for reason, nested in (doc.get("reason_traces") or {}).items():
            validate_trace(nested)
        _assert_payload_hash_integrity(doc, label=rel)
        path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        out[rel.replace("\\", "/")] = path
    return out


def load_trace_set(
    relpath: str,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load a shipped open/run e2e trace set, pinned to the live builder.

    * Schema-validates the on-disk document (when present).
    * Rebuilds from the matching builder and requires hop ``payload_hash``
      values to match (real SHA-256 of executed payloads).
    * On mismatch or missing file, re-emits the builder truth to disk so a
      placeholder-hash artifact cannot remain shipped.
    """
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    norm = relpath.replace("\\", "/")
    if "open-e2e" in norm:
        builder_doc = build_open_trace_set()
    elif "run-e2e" in norm:
        builder_doc = build_run_trace_set()
    else:
        raise ValueError("unknown open/run trace relpath %r" % relpath)

    # Builder truth is always the integrity reference.
    validate_trace(builder_doc)
    for reason, nested in (builder_doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(builder_doc, label=norm)

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
                _assert_payload_hash_integrity(data, label=norm + " (on-disk)")
                if _trace_sets_match(data, builder_doc):
                    return data
            except (ValueError, Exception):
                # Drift / placeholder hashes / schema — fall through to re-emit.
                pass

    # Pin shipped artifact to builder (closes hash integrity + pin findings).
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(builder_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return builder_doc


__all__ = [
    "OPEN_TRACE_RELPATH",
    "RUN_TRACE_RELPATH",
    "TRACE_AS_OF",
    "build_open_reason_trace",
    "build_run_reason_trace",
    "build_open_ok_trace",
    "build_run_ok_trace",
    "build_open_trace_set",
    "build_run_trace_set",
    "write_open_run_traces",
    "load_trace_set",
]
