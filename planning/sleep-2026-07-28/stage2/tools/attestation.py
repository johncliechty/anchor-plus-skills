"""Host-computed attestation — W9, Phase 2.

The orchestrator (not a sub-agent) runs the suite and writes the pass count,
file paths, and test names into the EXECUTION-LOG. Any number an agent
produced is stamped as a **claim**, not evidence.

Rules (frozen plan):

* Host-computed attestations count.
* Orchestrator-written attestations count (the host path for this build).
* A sub-agent-authored attestation is **rejected** and does **not** count
  — reported as non-evidence.
* Agent / model self-reports are non-evidence.

Paths stay relative; no absolute host paths are hard-coded.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SOURCE_HOST = "host"
SOURCE_ORCHESTRATOR = "orchestrator"
SOURCE_SUB_AGENT = "sub-agent"
SOURCE_AGENT = "agent"
SOURCE_MODEL = "model"
SOURCE_UNKNOWN = "unknown"

#: Sources that produce countable evidence.
EVIDENCE_SOURCES: frozenset = frozenset({SOURCE_HOST, SOURCE_ORCHESTRATOR})

#: Sources that are non-evidence (count zero).
NON_EVIDENCE_SOURCES: frozenset = frozenset(
    {
        SOURCE_SUB_AGENT,
        SOURCE_AGENT,
        SOURCE_MODEL,
        "subagent",
        "sub_agent",
        "execute-agent",
        "execute_agent",
        "review-agent",
        "review_agent",
        "worker",
        "llm",
    }
)

KIND_EVIDENCE = "evidence"
KIND_NON_EVIDENCE = "non-evidence"
KIND_CLAIM = "claim"

SUB_AGENT_NON_EVIDENCE_MESSAGE = (
    "sub-agent-authored claim as non-evidence"
)

HOST_ATTESTATION_SCHEMA = "host-attestation/v1"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class AttestationError(Exception):
    """Raised when an attestation cannot be built or classified."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


class AttestationSource(str, Enum):
    HOST = SOURCE_HOST
    ORCHESTRATOR = SOURCE_ORCHESTRATOR
    SUB_AGENT = SOURCE_SUB_AGENT
    AGENT = SOURCE_AGENT
    MODEL = SOURCE_MODEL
    UNKNOWN = SOURCE_UNKNOWN


def normalize_source(source: Union[str, AttestationSource, None]) -> str:
    """Map free-text / enum source onto a canonical token."""
    if source is None:
        return SOURCE_UNKNOWN
    if isinstance(source, AttestationSource):
        return source.value
    raw = str(source).strip().lower().replace(" ", "-").replace("_", "-")
    aliases = {
        "host": SOURCE_HOST,
        "host-computed": SOURCE_HOST,
        "hostcomputed": SOURCE_HOST,
        "orchestrator": SOURCE_ORCHESTRATOR,
        "orchestrator-written": SOURCE_ORCHESTRATOR,
        "orchestratorwritten": SOURCE_ORCHESTRATOR,
        "foreman": SOURCE_ORCHESTRATOR,
        "foreman-orchestrator": SOURCE_ORCHESTRATOR,
        "sub-agent": SOURCE_SUB_AGENT,
        "subagent": SOURCE_SUB_AGENT,
        "execute-agent": SOURCE_SUB_AGENT,
        "executeagent": SOURCE_SUB_AGENT,
        "review-agent": SOURCE_SUB_AGENT,
        "reviewagent": SOURCE_SUB_AGENT,
        "worker": SOURCE_SUB_AGENT,
        "agent": SOURCE_AGENT,
        "model": SOURCE_MODEL,
        "llm": SOURCE_MODEL,
        "claude": SOURCE_MODEL,
        "gemini": SOURCE_MODEL,
        "grok": SOURCE_MODEL,
    }
    return aliases.get(raw, SOURCE_UNKNOWN if raw in {"", "none"} else raw)


def is_evidence_source(source: Union[str, AttestationSource, None]) -> bool:
    return normalize_source(source) in EVIDENCE_SOURCES


def is_non_evidence_source(source: Union[str, AttestationSource, None]) -> bool:
    token = normalize_source(source)
    if token in EVIDENCE_SOURCES:
        return False
    if token in NON_EVIDENCE_SOURCES or token in {
        SOURCE_SUB_AGENT,
        SOURCE_AGENT,
        SOURCE_MODEL,
    }:
        return True
    # Unknown free-text that looks like a sub-agent claim.
    if "sub-agent" in token or "subagent" in token or token.endswith("-agent"):
        return True
    return token not in EVIDENCE_SOURCES


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Attestation:
    """One host-computed attestation record (evidence when source is host)."""

    source: str
    wave_id: str
    gate_command: str
    pass_count: int
    fail_count: int
    test_names: Tuple[str, ...] = ()
    files_touched: Tuple[str, ...] = ()
    commit_sha: str = ""
    computed_at: str = ""
    content_hash: str = ""
    schema: str = HOST_ATTESTATION_SCHEMA
    kind: str = KIND_EVIDENCE
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "kind": self.kind,
            "wave_id": self.wave_id,
            "gate_command": self.gate_command,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "test_names": list(self.test_names),
            "files_touched": list(self.files_touched),
            "commit_sha": self.commit_sha,
            "computed_at": self.computed_at,
            "content_hash": self.content_hash,
            "note": self.note,
        }


@dataclass(frozen=True)
class AttestationClaim:
    """A free-form claim found in a report (may be evidence or non-evidence)."""

    source: str
    text: str = ""
    pass_count: Optional[int] = None
    test_names: Tuple[str, ...] = ()
    wave_id: str = ""
    origin: str = ""  # e.g. "sub-agent report", "EXECUTION-LOG"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "text": self.text,
            "pass_count": self.pass_count,
            "test_names": list(self.test_names),
            "wave_id": self.wave_id,
            "origin": self.origin,
        }


@dataclass
class Classification:
    """Result of classifying one claim."""

    source: str
    kind: str  # evidence | non-evidence | claim
    counts: bool
    message: str = ""
    claim: Optional[AttestationClaim] = None

    @property
    def is_evidence(self) -> bool:
        return self.kind == KIND_EVIDENCE and self.counts

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "counts": self.counts,
            "message": self.message,
        }


@dataclass
class CountResult:
    """Aggregate of countable attestations vs non-evidence claims."""

    evidence_count: int
    non_evidence_count: int
    claims: List[Classification] = field(default_factory=list)
    non_evidence_messages: List[str] = field(default_factory=list)

    @property
    def total_claims(self) -> int:
        return len(self.claims)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "evidence_count": self.evidence_count,
            "non_evidence_count": self.non_evidence_count,
            "total_claims": self.total_claims,
            "non_evidence_messages": list(self.non_evidence_messages),
            "claims": [c.as_dict() for c in self.claims],
        }


# --------------------------------------------------------------------------
# Host compute
# --------------------------------------------------------------------------


def compute_host_attestation(
    *,
    wave_id: str,
    gate_command: str,
    pass_count: int,
    fail_count: int = 0,
    test_names: Optional[Sequence[str]] = None,
    files_touched: Optional[Sequence[str]] = None,
    commit_sha: str = "",
    source: str = SOURCE_HOST,
    computed_at: Optional[str] = None,
    note: str = "",
) -> Attestation:
    """Build a host-computed attestation. *source* must be an evidence source."""
    src = normalize_source(source)
    if src not in EVIDENCE_SOURCES:
        raise AttestationError(
            "compute_host_attestation requires source in %s (got %r)"
            % (sorted(EVIDENCE_SOURCES), source)
        )
    if not wave_id or not str(wave_id).strip():
        raise AttestationError("wave_id is required for host attestation")
    if not gate_command or not str(gate_command).strip():
        raise AttestationError("gate_command is required for host attestation")
    if pass_count is None or int(pass_count) < 0:
        raise AttestationError("pass_count must be a non-negative integer")
    if fail_count is None or int(fail_count) < 0:
        raise AttestationError("fail_count must be a non-negative integer")

    names = tuple(str(t) for t in (test_names or ()))
    files = tuple(str(f) for f in (files_touched or ()))
    ts = computed_at if computed_at is not None else _utc_now_iso()
    body = {
        "wave_id": str(wave_id).strip(),
        "gate_command": str(gate_command).strip(),
        "pass_count": int(pass_count),
        "fail_count": int(fail_count),
        "test_names": list(names),
        "files_touched": list(files),
        "commit_sha": str(commit_sha or "").strip(),
        "computed_at": ts,
        "source": src,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return Attestation(
        source=src,
        wave_id=body["wave_id"],
        gate_command=body["gate_command"],
        pass_count=int(pass_count),
        fail_count=int(fail_count),
        test_names=names,
        files_touched=files,
        commit_sha=body["commit_sha"],
        computed_at=ts,
        content_hash=digest,
        kind=KIND_EVIDENCE,
        note=note or "",
    )


# --------------------------------------------------------------------------
# Classify + count
# --------------------------------------------------------------------------


def classify_attestation(
    claim: Union[AttestationClaim, Attestation, Mapping[str, Any], str],
    *,
    source: Optional[str] = None,
) -> Classification:
    """Classify one claim as evidence or non-evidence.

    A sub-agent-authored string/report counts as non-evidence and carries
    the verbatim message required by the wave GWT.
    """
    if isinstance(claim, Attestation):
        src = normalize_source(source or claim.source)
        if src in EVIDENCE_SOURCES and claim.kind == KIND_EVIDENCE:
            return Classification(
                source=src,
                kind=KIND_EVIDENCE,
                counts=True,
                message="host-computed attestation",
            )
        return Classification(
            source=src,
            kind=KIND_NON_EVIDENCE,
            counts=False,
            message=_non_evidence_message(src),
        )

    if isinstance(claim, str):
        # Bare string — treat as a claim; source must be supplied or inferred.
        src = normalize_source(source or _infer_source_from_text(claim))
        c = AttestationClaim(source=src, text=claim)
    elif isinstance(claim, AttestationClaim):
        src = normalize_source(source or claim.source)
        c = claim
    elif isinstance(claim, Mapping):
        src = normalize_source(source or claim.get("source"))
        c = AttestationClaim(
            source=src,
            text=str(claim.get("text", "") or ""),
            pass_count=claim.get("pass_count"),
            test_names=tuple(claim.get("test_names") or ()),
            wave_id=str(claim.get("wave_id", "") or ""),
            origin=str(claim.get("origin", "") or ""),
        )
    else:
        raise AttestationError("unsupported claim type: %r" % type(claim))

    if is_evidence_source(src):
        return Classification(
            source=src,
            kind=KIND_EVIDENCE,
            counts=True,
            message="host-computed attestation",
            claim=c,
        )

    # Sub-agent / agent / model / unknown non-host → non-evidence.
    msg = _non_evidence_message(src)
    return Classification(
        source=src,
        kind=KIND_NON_EVIDENCE,
        counts=False,
        message=msg,
        claim=c,
    )


def count_attestations(
    claims: Sequence[Union[AttestationClaim, Attestation, Mapping[str, Any], str]],
) -> CountResult:
    """Count only host/orchestrator evidence; sub-agent claims count zero.

    Given an attestation string written by a sub-agent into its report,
    this returns ``evidence_count == 0`` and reports the claim as
    non-evidence (wave GWT).
    """
    result = CountResult(evidence_count=0, non_evidence_count=0)
    for raw in claims:
        cls = classify_attestation(raw)
        result.claims.append(cls)
        if cls.counts and cls.kind == KIND_EVIDENCE:
            result.evidence_count += 1
        else:
            result.non_evidence_count += 1
            if cls.message:
                result.non_evidence_messages.append(cls.message)
    return result


def reject_sub_agent_attestation(
    claim: Union[AttestationClaim, Mapping[str, Any], str],
) -> Classification:
    """Explicit reject path for sub-agent-authored attestations."""
    cls = classify_attestation(claim, source=SOURCE_SUB_AGENT)
    # Force non-evidence even if the claim text tried to look host-like.
    if cls.counts:
        return Classification(
            source=SOURCE_SUB_AGENT,
            kind=KIND_NON_EVIDENCE,
            counts=False,
            message=SUB_AGENT_NON_EVIDENCE_MESSAGE,
            claim=cls.claim,
        )
    if not cls.message:
        cls.message = SUB_AGENT_NON_EVIDENCE_MESSAGE
    return cls


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _non_evidence_message(source: str) -> str:
    src = normalize_source(source)
    if src in {SOURCE_SUB_AGENT} or "sub-agent" in src or "subagent" in src:
        return SUB_AGENT_NON_EVIDENCE_MESSAGE
    if src in {SOURCE_AGENT, SOURCE_MODEL}:
        return "%s-authored claim as non-evidence" % src
    return "non-host claim as non-evidence (source=%s)" % src


def _infer_source_from_text(text: str) -> str:
    low = (text or "").lower()
    if "sub-agent" in low or "subagent" in low or "execute agent" in low:
        return SOURCE_SUB_AGENT
    if "orchestrator" in low:
        return SOURCE_ORCHESTRATOR
    if "host-computed" in low or "host computed" in low:
        return SOURCE_HOST
    if re.search(r"\b(claude|gemini|grok|model|llm)\b", low):
        return SOURCE_MODEL
    return SOURCE_UNKNOWN


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "SOURCE_HOST",
    "SOURCE_ORCHESTRATOR",
    "SOURCE_SUB_AGENT",
    "SOURCE_AGENT",
    "SOURCE_MODEL",
    "SOURCE_UNKNOWN",
    "EVIDENCE_SOURCES",
    "NON_EVIDENCE_SOURCES",
    "KIND_EVIDENCE",
    "KIND_NON_EVIDENCE",
    "KIND_CLAIM",
    "SUB_AGENT_NON_EVIDENCE_MESSAGE",
    "HOST_ATTESTATION_SCHEMA",
    "AttestationError",
    "AttestationSource",
    "Attestation",
    "AttestationClaim",
    "Classification",
    "CountResult",
    "normalize_source",
    "is_evidence_source",
    "is_non_evidence_source",
    "compute_host_attestation",
    "classify_attestation",
    "count_attestations",
    "reject_sub_agent_attestation",
]
