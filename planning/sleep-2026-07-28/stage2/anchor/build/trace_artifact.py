"""End-to-end trace artifact schema — W9, Phase 2.

Defines what a surface wave's GREEN may mean: a traced path from control
invocation → handler → capability call → rendered state, asserted at the
**rendered-string** proof level — never a silent claim that a human drove
the real UI.

Binding definition (from IMPLEMENTATION-PLAN header):

* In waves W10–W21, *end-to-end* means a traced path from control
  invocation to handler to capability call to rendered state, under at
  least one induced fault per named failure reason.
* It does **not** mean a human drove the real UI.
* Every build-time trace artifact stamps ``proof_level: rendered-string``.
* The human-path claim is deferred to **S1 (W22)** only.

Hard validator rules:

* Missing ``proof_level`` → reject.
* ``proof_level`` claiming a human-driven user path (or any value other
  than ``rendered-string`` on a build-time artifact) → reject. Only S1
  may claim the user path.
* The four hops are required in order; each hop carries a non-empty
  ``payload_id`` and ``payload_hash``.
* One artifact per surface wave (keyed by ``wave_id`` + ``control_id``).

Paths are relative to the stage2 containment root (or an injected
``root``). No absolute host paths are hard-coded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

#: Binding proof level for every build-time (structural) trace.
PROOF_LEVEL_RENDERED_STRING = "rendered-string"

#: Human-driven user path — S1 only. A build-time artifact carrying this
#: (or any claim that the human path was proven) is rejected.
PROOF_LEVEL_HUMAN_PATH = "human-path"

#: Allowed hop kinds, in required order (control → handler → capability → state).
HOP_CONTROL_INVOCATION = "control_invocation"
HOP_HANDLER = "handler"
HOP_CAPABILITY_CALL = "capability_call"
HOP_RENDERED_STATE = "rendered_state"

REQUIRED_HOP_KINDS: Tuple[str, ...] = (
    HOP_CONTROL_INVOCATION,
    HOP_HANDLER,
    HOP_CAPABILITY_CALL,
    HOP_RENDERED_STATE,
)

#: Legal ``trace_result`` values for a schema-valid artifact.
TRACE_RESULT_COMPLETED = "completed"
TRACE_RESULT_FAILED_NAMED = "failed_with_named_state"
TRACE_RESULT_DEAD = "dead"
TRACE_RESULT_INVALID = "invalid"

LEGAL_TRACE_RESULTS: frozenset = frozenset(
    {
        TRACE_RESULT_COMPLETED,
        TRACE_RESULT_FAILED_NAMED,
        TRACE_RESULT_DEAD,
        TRACE_RESULT_INVALID,
    }
)

#: Relative directory under the containment root for emitted traces.
TRACES_RELDIR = os.path.join("artifacts", "traces")

#: Schema id stamped on every artifact.
TRACE_SCHEMA = "end-to-end-trace/v1"

#: Phrases that mark a human-driven user-path claim (rejected on build traces).
_HUMAN_PATH_CLAIM_MARKERS: Tuple[str, ...] = (
    "human-driven",
    "human driven",
    "human-path",
    "human path",
    "user path",
    "user-path",
    "john drove",
    "live ui session",
    "live user path",
    "north star met",
    "s1 pass",
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_WAVE_ID = re.compile(r"^W\d{1,2}$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class TraceValidationError(Exception):
    """Raised when a trace artifact fails the schema / proof-level rules."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TraceIOError(Exception):
    """Raised when a trace cannot be written or read under containment."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Hop + artifact
# --------------------------------------------------------------------------


class HopKind(str, Enum):
    """The four required hops of an end-to-end trace."""

    CONTROL_INVOCATION = HOP_CONTROL_INVOCATION
    HANDLER = HOP_HANDLER
    CAPABILITY_CALL = HOP_CAPABILITY_CALL
    RENDERED_STATE = HOP_RENDERED_STATE


@dataclass(frozen=True)
class TraceHop:
    """One hop on the control → handler → capability → rendered-state path.

    Every hop records the payload id and the payload hash it carried so a
    later audit can prove the same payload moved through the chain.
    """

    kind: str
    name: str
    payload_id: str
    payload_hash: str
    detail: str = ""
    timestamp: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


@dataclass
class TraceArtifact:
    """One end-to-end trace for one control under one surface wave."""

    wave_id: str
    control_id: str
    hops: List[TraceHop]
    proof_level: str = PROOF_LEVEL_RENDERED_STRING
    trace_result: str = TRACE_RESULT_COMPLETED
    induced_fault: Optional[str] = None
    rendered_state: str = ""
    as_of: str = ""
    schema: str = TRACE_SCHEMA
    notes: str = ""
    #: Explicit face-value disclosure: build traces are structural only.
    proof_disclosure: str = (
        "structural rendered-string proof only; human-driven user path "
        "deferred to S1 (W22); this artifact is not a North Star met claim"
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "wave_id": self.wave_id,
            "control_id": self.control_id,
            "proof_level": self.proof_level,
            "proof_disclosure": self.proof_disclosure,
            "trace_result": self.trace_result,
            "induced_fault": self.induced_fault,
            "rendered_state": self.rendered_state,
            "as_of": self.as_of,
            "notes": self.notes,
            "hops": [h.as_dict() for h in self.hops],
        }


# --------------------------------------------------------------------------
# Payload hashing
# --------------------------------------------------------------------------


def payload_hash(payload: Any) -> str:
    """SHA-256 hex digest of a stable JSON (or utf-8) encoding of *payload*."""
    if payload is None:
        raw = b""
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    return hashlib.sha256(raw).hexdigest()


def make_hop(
    kind: Union[str, HopKind],
    name: str,
    *,
    payload_id: str,
    payload: Any = None,
    payload_hash_value: Optional[str] = None,
    detail: str = "",
    timestamp: Optional[str] = None,
) -> TraceHop:
    """Build one hop; hash *payload* when *payload_hash_value* is omitted."""
    kind_s = kind.value if isinstance(kind, HopKind) else str(kind).strip()
    if not name or not str(name).strip():
        raise TraceValidationError("hop name is required")
    if not payload_id or not str(payload_id).strip():
        raise TraceValidationError("hop payload_id is required")
    ph = payload_hash_value if payload_hash_value is not None else payload_hash(payload)
    if not ph or not str(ph).strip():
        raise TraceValidationError("hop payload_hash is required")
    ts = timestamp if timestamp is not None else _utc_now_iso()
    return TraceHop(
        kind=kind_s,
        name=str(name).strip(),
        payload_id=str(payload_id).strip(),
        payload_hash=str(ph).strip().lower(),
        detail=detail or "",
        timestamp=ts,
    )


# --------------------------------------------------------------------------
# Build / validate
# --------------------------------------------------------------------------


def build_trace(
    wave_id: str,
    control_id: str,
    hops: Sequence[Union[TraceHop, Mapping[str, Any]]],
    *,
    proof_level: str = PROOF_LEVEL_RENDERED_STRING,
    trace_result: str = TRACE_RESULT_COMPLETED,
    induced_fault: Optional[str] = None,
    rendered_state: str = "",
    as_of: Optional[str] = None,
    notes: str = "",
    proof_disclosure: Optional[str] = None,
) -> TraceArtifact:
    """Construct a TraceArtifact and validate it. Raises on schema failure."""
    hop_objs: List[TraceHop] = []
    for h in hops:
        if isinstance(h, TraceHop):
            hop_objs.append(h)
        else:
            hop_objs.append(_hop_from_mapping(h))
    art = TraceArtifact(
        wave_id=str(wave_id).strip(),
        control_id=str(control_id).strip(),
        hops=hop_objs,
        proof_level=str(proof_level).strip() if proof_level is not None else "",
        trace_result=str(trace_result).strip(),
        induced_fault=induced_fault,
        rendered_state=rendered_state or "",
        as_of=as_of if as_of is not None else _utc_now_iso(),
        notes=notes or "",
    )
    if proof_disclosure is not None:
        art.proof_disclosure = proof_disclosure
    return validate_trace(art)


def validate_trace(
    artifact: Union[TraceArtifact, Mapping[str, Any]],
    *,
    allow_human_path: bool = False,
) -> TraceArtifact:
    """Validate a trace artifact against the W9 schema.

    *allow_human_path* is reserved for S1 (W22). Build-time callers leave it
    False; any human-path claim is then a hard reject.
    """
    art = artifact if isinstance(artifact, TraceArtifact) else _artifact_from_mapping(artifact)

    if not art.wave_id:
        raise TraceValidationError("wave_id is required")
    if not _WAVE_ID.match(art.wave_id):
        raise TraceValidationError(
            "wave_id must look like W<n> (e.g. W10); got %r" % (art.wave_id,)
        )
    if not art.control_id:
        raise TraceValidationError("control_id is required")

    # --- proof_level is the binding stamp ---------------------------------
    if art.proof_level is None or str(art.proof_level).strip() == "":
        raise TraceValidationError(
            "proof_level stamp is required — every build-time trace must "
            "stamp proof_level: rendered-string on its face"
        )
    pl = str(art.proof_level).strip().lower()
    if pl != PROOF_LEVEL_RENDERED_STRING:
        if pl in {PROOF_LEVEL_HUMAN_PATH, "human", "user-path", "user_path", "s1"}:
            if not allow_human_path:
                raise TraceValidationError(
                    "human-driven user path claim rejected — only S1 may "
                    "claim the user path; build-time traces must stamp "
                    "proof_level: rendered-string (got %r)" % (art.proof_level,)
                )
        else:
            raise TraceValidationError(
                "proof_level must be %r for build-time traces (got %r)"
                % (PROOF_LEVEL_RENDERED_STRING, art.proof_level)
            )

    # Face-value human-path claim in free text fields is also rejected.
    if not allow_human_path:
        for field_name, text in (
            ("notes", art.notes),
            ("proof_disclosure", art.proof_disclosure),
            ("rendered_state", art.rendered_state),
            ("trace_result", art.trace_result),
        ):
            if _claims_human_path(text):
                raise TraceValidationError(
                    "human-driven user path claim rejected in %s — only S1 "
                    "may claim the user path; every build-time trace must "
                    "say so on its face (proof_level: rendered-string)"
                    % field_name
                )

    if art.trace_result not in LEGAL_TRACE_RESULTS:
        raise TraceValidationError(
            "trace_result must be one of %s (got %r)"
            % (sorted(LEGAL_TRACE_RESULTS), art.trace_result)
        )

    # Dead / invalid results fail the wave gate when used as GO evidence.
    # The schema still accepts them as *valid documents* so a wave can
    # record a failed attempt; surface GO checks refuse dead/invalid.
    if not art.hops:
        raise TraceValidationError(
            "hops are required — control_invocation → handler → "
            "capability_call → rendered_state"
        )

    kinds_seen = [h.kind for h in art.hops]
    for required in REQUIRED_HOP_KINDS:
        if required not in kinds_seen:
            raise TraceValidationError(
                "missing required hop %r — path must be control_invocation "
                "→ handler → capability_call → rendered_state"
                % (required,)
            )

    # Order check: first occurrence of each required kind must be sequential.
    first_idx = {k: kinds_seen.index(k) for k in REQUIRED_HOP_KINDS}
    order = [first_idx[k] for k in REQUIRED_HOP_KINDS]
    if order != sorted(order):
        raise TraceValidationError(
            "hops out of order — required sequence is "
            "control_invocation → handler → capability_call → rendered_state"
        )

    for i, hop in enumerate(art.hops):
        if hop.kind not in REQUIRED_HOP_KINDS and hop.kind not in {
            "setup",
            "teardown",
            "fault_inject",
        }:
            # Unknown hop kinds are allowed as extras but must still carry
            # payload identity fields.
            pass
        if not hop.name or not str(hop.name).strip():
            raise TraceValidationError("hop[%d] name is required" % i)
        if not hop.payload_id or not str(hop.payload_id).strip():
            raise TraceValidationError(
                "hop[%d] (%s) payload_id is required" % (i, hop.kind)
            )
        if not hop.payload_hash or not str(hop.payload_hash).strip():
            raise TraceValidationError(
                "hop[%d] (%s) payload_hash is required" % (i, hop.kind)
            )
        ph = str(hop.payload_hash).strip().lower()
        if not _SHA256_HEX.match(ph):
            raise TraceValidationError(
                "hop[%d] (%s) payload_hash must be a 64-char sha256 hex digest"
                % (i, hop.kind)
            )

    # A null/empty capability call name is the signature of a dead control.
    cap_hops = [h for h in art.hops if h.kind == HOP_CAPABILITY_CALL]
    for ch in cap_hops:
        if not ch.name or ch.name.strip().lower() in {"", "null", "none", "-"}:
            raise TraceValidationError(
                "capability_call hop has no target — a null capability call "
                "is the signature of a dead control"
            )

    return art


def is_go_evidence(artifact: Union[TraceArtifact, Mapping[str, Any]]) -> bool:
    """True when the artifact is schema-valid and eligible as wave GO evidence.

    ``dead`` and ``invalid`` results are never GO evidence.
    """
    try:
        art = validate_trace(artifact)
    except TraceValidationError:
        return False
    return art.trace_result in {TRACE_RESULT_COMPLETED, TRACE_RESULT_FAILED_NAMED}


# --------------------------------------------------------------------------
# Emit / load (containment-relative)
# --------------------------------------------------------------------------


def traces_dir(root: Optional[Path] = None) -> Path:
    return _root(root) / TRACES_RELDIR


def default_trace_relpath(wave_id: str, control_id: str) -> str:
    """Relative path under the containment root for one control's e2e trace."""
    safe_wave = re.sub(r"[^A-Za-z0-9_-]+", "_", wave_id.strip())
    safe_ctrl = re.sub(r"[^A-Za-z0-9_-]+", "_", control_id.strip().lower())
    return os.path.join(TRACES_RELDIR, "%s-%s-e2e.json" % (safe_wave, safe_ctrl))


def emit_trace(
    artifact: Union[TraceArtifact, Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    relpath: Optional[str] = None,
    allow_human_path: bool = False,
) -> Path:
    """Validate and write a trace artifact under ``artifacts/traces/``.

    Returns the absolute path written. Relpath (when given) must resolve
    under the containment root.
    """
    art = validate_trace(artifact, allow_human_path=allow_human_path)
    base = _root(root)
    if relpath is None:
        relpath = default_trace_relpath(art.wave_id, art.control_id)
    relpath = str(relpath).replace("\\", "/").lstrip("/")
    # Refuse path escape.
    if ".." in Path(relpath).parts:
        raise TraceIOError("trace relpath may not contain '..': %s" % relpath)
    out = (base / relpath).resolve()
    try:
        out.relative_to(base.resolve())
    except ValueError:
        raise TraceIOError(
            "trace path escapes containment root: %s" % relpath
        ) from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(art.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def load_trace(
    path: Union[str, Path],
    *,
    root: Optional[Path] = None,
    allow_human_path: bool = False,
) -> TraceArtifact:
    """Load and validate a trace JSON file (absolute or containment-relative)."""
    p = Path(path)
    if not p.is_absolute():
        p = _root(root) / p
    if not p.is_file():
        raise TraceIOError("trace file not found: %s" % p.name)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TraceIOError("trace file unreadable: %s" % exc) from exc
    if not isinstance(data, dict):
        raise TraceValidationError("trace root must be a JSON object")
    return validate_trace(data, allow_human_path=allow_human_path)


def find_trace_for_wave(
    wave_id: str,
    *,
    root: Optional[Path] = None,
    control_id: Optional[str] = None,
) -> Optional[Path]:
    """Locate a schema-looking trace file for *wave_id* under artifacts/traces/.

    Returns the first matching path, or None when absent. Does not validate
    contents — callers that need GO evidence must :func:`load_trace`.
    """
    d = traces_dir(root)
    if not d.is_dir():
        return None
    wave_l = wave_id.strip().lower()
    ctrl_l = control_id.strip().lower() if control_id else None
    candidates: List[Path] = []
    for p in sorted(d.glob("*.json")):
        name = p.name.lower()
        if wave_l not in name and not name.startswith(wave_l + "-"):
            # Also accept files whose content wave_id matches (cheap open).
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            if str(raw.get("wave_id", "")).strip().lower() != wave_l:
                continue
            if ctrl_l and str(raw.get("control_id", "")).strip().lower() != ctrl_l:
                continue
            candidates.append(p)
            continue
        if ctrl_l and ctrl_l not in name:
            continue
        candidates.append(p)
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _claims_human_path(text: Optional[str]) -> bool:
    if not text:
        return False
    low = str(text).lower()
    # The standard disclosure sentence mentions "human-driven user path
    # deferred to S1" — that is disclosure, not a claim. Strip the
    # deferred/not/only-S1 framing before marker scan.
    if "deferred to s1" in low or "not a north star" in low:
        return False
    if "only s1" in low and "user path" in low:
        return False
    return any(m in low for m in _HUMAN_PATH_CLAIM_MARKERS)


def _hop_from_mapping(m: Mapping[str, Any]) -> TraceHop:
    kind = str(m.get("kind", "")).strip()
    name = str(m.get("name", "")).strip()
    payload_id = str(m.get("payload_id", "")).strip()
    ph = m.get("payload_hash")
    if ph is None and "payload" in m:
        ph = payload_hash(m.get("payload"))
    return TraceHop(
        kind=kind,
        name=name,
        payload_id=payload_id,
        payload_hash=str(ph or "").strip().lower(),
        detail=str(m.get("detail", "") or ""),
        timestamp=str(m.get("timestamp", "") or ""),
    )


def _artifact_from_mapping(m: Mapping[str, Any]) -> TraceArtifact:
    hops_raw = m.get("hops") or []
    if not isinstance(hops_raw, list):
        raise TraceValidationError("hops must be a list")
    hops = [_hop_from_mapping(h) for h in hops_raw]
    # proof_level: distinguish missing key from empty string.
    if "proof_level" not in m:
        pl = ""  # missing → validator rejects as no stamp
    else:
        pl = m.get("proof_level")
        pl = "" if pl is None else str(pl)
    return TraceArtifact(
        wave_id=str(m.get("wave_id", "") or "").strip(),
        control_id=str(m.get("control_id", "") or "").strip(),
        hops=hops,
        proof_level=pl,
        trace_result=str(m.get("trace_result", TRACE_RESULT_COMPLETED) or "").strip(),
        induced_fault=m.get("induced_fault"),
        rendered_state=str(m.get("rendered_state", "") or ""),
        as_of=str(m.get("as_of", "") or ""),
        schema=str(m.get("schema", TRACE_SCHEMA) or TRACE_SCHEMA),
        notes=str(m.get("notes", "") or ""),
        proof_disclosure=str(
            m.get(
                "proof_disclosure",
                TraceArtifact.__dataclass_fields__["proof_disclosure"].default,
            )
            or ""
        ),
    )


def _root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    # tools/ is a sibling of anchor/; containment root is stage2.
    return Path(__file__).resolve().parents[2]


__all__ = [
    "PROOF_LEVEL_RENDERED_STRING",
    "PROOF_LEVEL_HUMAN_PATH",
    "HOP_CONTROL_INVOCATION",
    "HOP_HANDLER",
    "HOP_CAPABILITY_CALL",
    "HOP_RENDERED_STATE",
    "REQUIRED_HOP_KINDS",
    "TRACE_RESULT_COMPLETED",
    "TRACE_RESULT_FAILED_NAMED",
    "TRACE_RESULT_DEAD",
    "TRACE_RESULT_INVALID",
    "LEGAL_TRACE_RESULTS",
    "TRACES_RELDIR",
    "TRACE_SCHEMA",
    "TraceValidationError",
    "TraceIOError",
    "HopKind",
    "TraceHop",
    "TraceArtifact",
    "payload_hash",
    "make_hop",
    "build_trace",
    "validate_trace",
    "is_go_evidence",
    "traces_dir",
    "default_trace_relpath",
    "emit_trace",
    "load_trace",
    "find_trace_for_wave",
]
