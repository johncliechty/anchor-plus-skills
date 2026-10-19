"""Banner → Doctor issue-payload handoff — W14.

The health banner computes an issue payload (issue id, source, observed
symptom) and hands it to the Doctor entry point. "Not re-derived from
scratch" is defined mechanically:

* The payload id and the hash of ``(issue_id, source, observed_symptom)``
  computed at the banner are **byte-identical** to those the Doctor entry
  point receives and records in the trace.
* Doctor re-running its own detection to reconstruct the issue is a
  **test failure** (``RedetectionForbidden``).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


class RedetectionForbidden(AssertionError):
    """Raised when Doctor attempts to re-detect / reconstruct the banner issue.

    The banner payload is the source of truth for issue identity. Doctor may
    run a diagnosis over live readings, but it may not invent a new issue id
    or recompute the issue triple from system state.
    """


def issue_payload_hash(
    issue_id: str,
    source: str,
    observed_symptom: str,
) -> str:
    """SHA-256 hex digest of the canonical (issue_id, source, observed_symptom) triple."""
    payload = {
        "issue_id": str(issue_id),
        "source": str(source),
        "observed_symptom": str(observed_symptom),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class IssuePayload:
    """Typed banner→Doctor handoff payload.

    Fields are fixed at the banner. ``payload_hash`` is computed once at the
    banner and must travel unchanged into Doctor and the e2e trace.
    """

    issue_id: str
    source: str
    observed_symptom: str
    payload_hash: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "source": self.source,
            "observed_symptom": self.observed_symptom,
            "payload_hash": self.payload_hash,
        }

    def triple(self) -> Tuple[str, str, str]:
        return (self.issue_id, self.source, self.observed_symptom)


def banner_issue_payload(
    issue_id: str,
    source: str,
    observed_symptom: str,
) -> IssuePayload:
    """Build the issue payload at the banner (hash computed here, once)."""
    iid = str(issue_id).strip()
    src = str(source).strip()
    symptom = str(observed_symptom).strip()
    if not iid:
        raise ValueError("issue_id is required")
    if not src:
        raise ValueError("source is required")
    if not symptom:
        raise ValueError("observed_symptom is required")
    ph = issue_payload_hash(iid, src, symptom)
    return IssuePayload(
        issue_id=iid,
        source=src,
        observed_symptom=symptom,
        payload_hash=ph,
    )


@dataclass
class DoctorEntryRecord:
    """What Doctor recorded on entry from the banner payload.

    The record stores the banner's id and hash verbatim. It never invents a
    new issue identity. ``redetect_attempted`` is always False on the honest
    path; a True value is a contract violation (tests fail).
    """

    issue_id: str
    source: str
    observed_symptom: str
    payload_hash: str
    redetect_attempted: bool = False
    trace_payload_id: str = ""
    trace_payload_hash: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "source": self.source,
            "observed_symptom": self.observed_symptom,
            "payload_hash": self.payload_hash,
            "redetect_attempted": self.redetect_attempted,
            "trace_payload_id": self.trace_payload_id,
            "trace_payload_hash": self.trace_payload_hash,
        }


def doctor_entry(
    payload: IssuePayload,
    *,
    redetect: bool = False,
    system_snapshot: Optional[Mapping[str, Any]] = None,
) -> DoctorEntryRecord:
    """Doctor entry point: accept the banner payload; never re-detect.

    * ``payload`` — the IssuePayload computed at the banner.
    * ``redetect`` — if True, Doctor would reconstruct the issue from
      ``system_snapshot``; that path is **forbidden** and raises
      :class:`RedetectionForbidden` (the mechanical definition of the
      "not re-derived from scratch" test failure).
    * ``system_snapshot`` — unused on the honest path; present only so a
      redetect attempt has something to "look at" before being refused.
    """
    if redetect:
        # Explicitly refuse re-detection / reconstruction of issue identity.
        _ = system_snapshot  # deliberately unused — reconstruction is banned
        raise RedetectionForbidden(
            "Doctor must not re-detect or reconstruct the banner issue; "
            "payload id and hash must arrive byte-identical from the banner "
            "(issue_id=%r)" % (payload.issue_id,)
        )

    # Byte-identical acceptance: recompute hash only to verify integrity of
    # the triple as received — never invent a new id or symptom.
    expected = issue_payload_hash(
        payload.issue_id, payload.source, payload.observed_symptom
    )
    if expected != payload.payload_hash:
        raise ValueError(
            "banner payload hash mismatch — expected %s got %s"
            % (expected, payload.payload_hash)
        )

    return DoctorEntryRecord(
        issue_id=payload.issue_id,
        source=payload.source,
        observed_symptom=payload.observed_symptom,
        payload_hash=payload.payload_hash,
        redetect_attempted=False,
        trace_payload_id=payload.issue_id,
        trace_payload_hash=payload.payload_hash,
    )


__all__ = [
    "RedetectionForbidden",
    "IssuePayload",
    "DoctorEntryRecord",
    "issue_payload_hash",
    "banner_issue_payload",
    "doctor_entry",
]
