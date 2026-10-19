"""Machine-readable readiness stamp compute + write (W4).

``ready`` requires:

* governance installed **and** at least one coding-family seat probe OK
  **OR**
* explicit user-accepted degraded

Skills refuse green ``ready`` otherwise. Reason codes are the closed W1 enum.
``journal_contract_unproven`` may appear as a **warning** alongside ready when
hooks exist but no proven journal write has been observed yet.

Consumes :mod:`share_contracts` validation (false-green guard). Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

from share_contracts import (
    PACKAGE_IDS,
    READINESS_REASON_CODES,
    READINESS_STATUSES,
    validate_readiness_doc,
)

READINESS_FILENAME = "readiness.json"
READINESS_SCHEMA = "share-readiness/v1"
READINESS_SCHEMA_VERSION = 1


class ReadinessError(Exception):
    """Raised when a stamp would be false-green or schema-invalid."""

    def __init__(self, problems, message=None):
        self.problems = list(problems) if problems else ["readiness-invalid"]
        self.message = message or (
            "readiness refused: " + ",".join(self.problems)
        )
        super().__init__(self.message)


def _uniq_codes(codes) -> list:
    out = []
    seen = set()
    for c in codes or []:
        if c in READINESS_REASON_CODES and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def compute_readiness(
    *,
    package_id: str = "A",
    governance_installed: bool = False,
    coding_seat_ok: bool = False,
    user_accepted_degraded: bool = False,
    skill_tree_forked: bool = False,
    journal_proven: bool = False,
    skills_pin_mismatch: bool = False,
    seat_probe_failed: bool = False,
    feedback_opt_in: bool = False,
    extra_reason_codes=None,
    notes: str | None = None,
    force_status: str | None = None,
) -> dict:
    """Compute a readiness stamp dict (does not write).

    Never returns ``status=ready`` without (governance + seat) or
    ``user_accepted_degraded``. Feedback opt-in is recorded but is **not** a
    readiness gate (default false).
    """
    if package_id not in PACKAGE_IDS:
        raise ReadinessError(["package_id-out-of-enum:%r" % (package_id,)])

    codes = []

    if not governance_installed:
        codes.append("governance_missing")
    if not coding_seat_ok:
        codes.append("no_coding_seat")
        if seat_probe_failed:
            codes.append("seat_probe_failed")
    if skill_tree_forked:
        codes.append("skill_tree_forked")
    if skills_pin_mismatch:
        codes.append("skills_pin_mismatch")
    if not journal_proven:
        # Soft warning — may coexist with ready.
        codes.append("journal_contract_unproven")
    if user_accepted_degraded:
        codes.append("user_accepted_degraded")
    if extra_reason_codes:
        codes.extend(extra_reason_codes)

    codes = _uniq_codes(codes)

    # Green ready predicate (NS / schema false-green guard).
    green_ok = (
        (governance_installed and coding_seat_ok)
        or bool(user_accepted_degraded)
    )

    if force_status is not None:
        if force_status not in READINESS_STATUSES:
            raise ReadinessError(
                ["status-out-of-enum:%r" % (force_status,)]
            )
        status = force_status
        if status == "ready" and not green_ok:
            raise ReadinessError(
                ["ready-without-governance-seat-or-accepted-degraded"]
            )
    elif green_ok:
        status = "ready"
    elif not coding_seat_ok and not user_accepted_degraded:
        # Zero coding seats → not-ready (exit non-zero on CLI); skills may
        # still be on disk. Distinct from degraded (seat present, other issues).
        status = "not-ready"
    else:
        status = "degraded"

    # When forked, never claim pure green ready unless user explicitly accepted
    # degraded (fork is a degradation condition).
    if skill_tree_forked and status == "ready" and not user_accepted_degraded:
        status = "degraded"
        if "skill_tree_forked" not in codes:
            codes.append("skill_tree_forked")

    doc = {
        "schema": READINESS_SCHEMA,
        "schema_version": READINESS_SCHEMA_VERSION,
        "status": status,
        "reason_codes": codes,
        "package_id": package_id,
        "governance_installed": bool(governance_installed),
        "coding_seat_ok": bool(coding_seat_ok),
        "user_accepted_degraded": bool(user_accepted_degraded),
        "feedback_opt_in": bool(feedback_opt_in),
    }
    if notes is not None:
        doc["notes"] = str(notes)

    problems = validate_readiness_doc(doc)
    if problems:
        raise ReadinessError(problems)
    return doc


def refuse_false_green(doc) -> list:
    """Return problems if ``doc`` claims ready without required conditions."""
    return validate_readiness_doc(doc)


def write_readiness_stamp(dest_dir, doc) -> Path:
    """Write ``readiness.json`` after validation; return path."""
    problems = validate_readiness_doc(doc)
    if problems:
        raise ReadinessError(problems)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / READINESS_FILENAME
    out.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return out


def load_readiness_stamp(path) -> dict:
    p = Path(path)
    if p.is_dir():
        p = p / READINESS_FILENAME
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ReadinessError(["readiness-not-an-object"])
    problems = validate_readiness_doc(doc)
    if problems:
        raise ReadinessError(problems)
    return doc


def is_green_ready(doc) -> bool:
    """True only for validated ready stamps (never false-green)."""
    if not isinstance(doc, dict):
        return False
    if validate_readiness_doc(doc):
        return False
    return doc.get("status") == "ready"
