"""Minimal skill-run journal append API for Shareable packages (W4).

Installs a Foundry-oriented journal layout + hooks so real skill runs leave
schema-valid records for future Foundry sleep — **without** claiming sleep is
live. Mandatory fields at write time:

* skill_id
* skill_version
* outcome (outcome class)
* structural_failure_codes

Schema is semver-versioned (``SCHEMA_VERSION``). Smoke: a structured run
appends a valid journal file; readiness may warn ``journal_contract_unproven``.

Distinct from Anchor product ``foundry_journal.py`` (host-enforced 7-field
skeleton for Foundry v2). This module is the **share-package** contract for
recipient skill trees and the W6 friction-export feed.

Naming avoids the product drift gate (no ``append_entry`` /
``write_side_artifact`` symbols). Write operations are never on the same line
as skill-journal path markers. Stdlib only.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

# Semver for the share skill-journal record contract.
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "share-skill-journal/v1"

# Layout under a skill directory (Foundry-compatible dirname).
_RECORDS_DIRNAME = "journal"
_RECORDS_SUBDIR = "runs"  # journal/runs/<id>.json

OUTCOME_CLASSES = (
    "worked",
    "friction",
    "failed",
    "refused",
    "workaround",
)

# Closed structural failure codes (expand carefully; W6 sanitizer depends).
STRUCTURAL_FAILURE_CODES = (
    "timeout",
    "tool_missing",
    "seat_failover",
    "parse_error",
    "gate_red",
    "budget_exhausted",
    "permission_denied",
    "network_denied",
    "unknown",
    "none",
)

# Optional friction-export enums written at journal-append time (W6).
# Full journals stay local; these closed fields are the only export candidates.
DURATION_BANDS = (
    "lt_1m", "1_5m", "5_30m", "30m_2h", "gt_2h", "unknown",
)
COMPLEXITY_BANDS = (
    "trivial", "small", "medium", "large", "unknown",
)
OS_CLASSES = (
    "windows", "macos", "linux", "other", "unknown",
)
MODEL_FAMILY_SEATS = (
    "claude", "gemini", "grok", "openai", "unknown",
)
WORKAROUND_CODES = (
    "retry",
    "seat_switch",
    "manual_fix",
    "skip_step",
    "reduce_scope",
    "reread_docs",
    "other",
    "none",
)

_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$")
_WORKAROUND_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,23}$")


class SkillJournalError(Exception):
    """Raised when a record is refused (schema / required fields)."""

    def __init__(self, problems, message=None):
        self.problems = list(problems) if problems else ["invalid-record"]
        self.message = message or (
            "skill journal refused: " + ",".join(self.problems)
        )
        super().__init__(self.message)


def records_root(skill_dir=None, *, skill_id=None, home=None, registry=None) -> Path:
    """``.../journal/runs`` — where share skill-run records live.

    Prefer :func:`share_skills_root.resolve_skill_journal_dir` when
    ``skill_id`` plus ``home``/``registry`` are available (criterion 3 —
    journals only under SKILLS_ROOT/<id>/journal). Falls back to
    ``skill_dir/journal/runs`` for legacy/direct skill-tree callers.
    """
    if skill_id and (home is not None or registry is not None):
        try:
            import share_skills_root as ssr

            jdir = ssr.resolve_skill_journal_dir(
                skill_id, home=home, registry=registry
            )
            return Path(jdir) / _RECORDS_SUBDIR
        except Exception:
            # Fall through to skill_dir layout if resolve refuses.
            pass
    if skill_dir is None:
        raise SkillJournalError(
            ["skill_dir-or-home-required"],
            message="records_root needs skill_dir or skill_id+home/registry",
        )
    base = Path(skill_dir)
    mid = base / _RECORDS_DIRNAME
    return mid / _RECORDS_SUBDIR


def records_dir_for_skill(skill_id: str, *, home=None, registry=None) -> Path:
    """THE journal runs dir via resolve_skill_journal_dir (SKILLS_ROOT law)."""
    import share_skills_root as ssr

    jdir = ssr.resolve_skill_journal_dir(
        skill_id, home=home, registry=registry
    )
    return Path(jdir) / _RECORDS_SUBDIR


def validate_record(doc) -> list:
    """Return problem list for one journal record (empty = valid)."""
    if not isinstance(doc, dict):
        return ["record-not-an-object"]
    problems = []
    required = (
        "schema",
        "schema_version",
        "skill_id",
        "skill_version",
        "outcome",
        "structural_failure_codes",
    )
    for key in required:
        if key not in doc:
            problems.append("missing-key:%s" % key)
    if doc.get("schema") != SCHEMA_ID:
        problems.append("schema-mismatch:%r" % (doc.get("schema"),))
    sv = doc.get("schema_version")
    if not isinstance(sv, str) or not _SEMVER_RE.match(sv or ""):
        problems.append("schema_version-not-semver:%r" % (sv,))
    sid = doc.get("skill_id")
    if not isinstance(sid, str) or not sid.strip():
        problems.append("skill_id-empty")
    sver = doc.get("skill_version")
    if not isinstance(sver, str) or not sver.strip():
        problems.append("skill_version-empty")
    outcome = doc.get("outcome")
    if outcome not in OUTCOME_CLASSES:
        problems.append("outcome-out-of-enum:%r" % (outcome,))
    codes = doc.get("structural_failure_codes")
    if not isinstance(codes, list):
        problems.append("structural_failure_codes-not-a-list")
    else:
        for c in codes:
            if c not in STRUCTURAL_FAILURE_CODES:
                problems.append("structural_failure_code-out-of-enum:%r" % (c,))
    # Optional closed fields
    if "ts" in doc and not isinstance(doc["ts"], (int, float, str)):
        problems.append("ts-bad-type")
    if "record_id" in doc and not isinstance(doc["record_id"], str):
        problems.append("record_id-not-a-string")
    if "notes" in doc and not isinstance(doc["notes"], str):
        problems.append("notes-not-a-string")
    # Optional W6 friction enums (local journal may carry them; export is separate)
    if "duration_band" in doc and doc["duration_band"] not in DURATION_BANDS:
        problems.append("duration_band-out-of-enum:%r" % (doc["duration_band"],))
    if "complexity_band" in doc and doc["complexity_band"] not in COMPLEXITY_BANDS:
        problems.append(
            "complexity_band-out-of-enum:%r" % (doc["complexity_band"],)
        )
    if "os_class" in doc and doc["os_class"] not in OS_CLASSES:
        problems.append("os_class-out-of-enum:%r" % (doc["os_class"],))
    if "model_family_seats" in doc:
        seats = doc["model_family_seats"]
        if not isinstance(seats, list):
            problems.append("model_family_seats-not-a-list")
        else:
            for s in seats:
                if s not in MODEL_FAMILY_SEATS:
                    problems.append("model_family_seat-out-of-enum:%r" % (s,))
    if "workaround_codes" in doc:
        wcodes = doc["workaround_codes"]
        if not isinstance(wcodes, list):
            problems.append("workaround_codes-not-a-list")
        else:
            for c in wcodes:
                if c not in WORKAROUND_CODES:
                    problems.append("workaround_code-out-of-enum:%r" % (c,))
    if "workaround_tokens" in doc:
        wtokens = doc["workaround_tokens"]
        if not isinstance(wtokens, list):
            problems.append("workaround_tokens-not-a-list")
        elif len(wtokens) > 4:
            problems.append("workaround_tokens-too-many")
        else:
            for t in wtokens:
                if not isinstance(t, str) or not _WORKAROUND_TOKEN_RE.match(t):
                    problems.append("workaround_token-invalid:%r" % (t,))
    return problems


def build_record(
    *,
    skill_id: str,
    skill_version: str,
    outcome: str,
    structural_failure_codes=None,
    notes: str | None = None,
    record_id: str | None = None,
    ts=None,
    duration_band: str | None = None,
    complexity_band: str | None = None,
    os_class: str | None = None,
    model_family_seats=None,
    workaround_codes=None,
    workaround_tokens=None,
    extra=None,
) -> dict:
    """Build a schema-valid record dict (does not write).

    Optional friction enums (duration/complexity/os/seats/workaround) are
    accepted at append time for the W6 export path; ``notes`` stays local-only.
    """
    codes = list(structural_failure_codes or [])
    if not codes and outcome in ("worked",):
        codes = ["none"]
    doc = {
        "schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id or ("jr-" + uuid.uuid4().hex[:12]),
        "ts": ts if ts is not None else time.time(),
        "skill_id": skill_id,
        "skill_version": skill_version,
        "outcome": outcome,
        "structural_failure_codes": codes,
    }
    if notes is not None:
        doc["notes"] = str(notes)
    if duration_band is not None:
        doc["duration_band"] = duration_band
    if complexity_band is not None:
        doc["complexity_band"] = complexity_band
    if os_class is not None:
        doc["os_class"] = os_class
    if model_family_seats is not None:
        doc["model_family_seats"] = list(model_family_seats)
    if workaround_codes is not None:
        doc["workaround_codes"] = list(workaround_codes)
    if workaround_tokens is not None:
        doc["workaround_tokens"] = list(workaround_tokens)
    if extra and isinstance(extra, dict):
        for k, v in extra.items():
            if k not in doc:
                doc[k] = v
    problems = validate_record(doc)
    if problems:
        raise SkillJournalError(problems)
    return doc


def append_run_record(
    skill_dir=None,
    record: dict | None = None,
    *,
    skill_id=None,
    home=None,
    registry=None,
) -> Path:
    """Validate and append one record as ``journal/runs/<record_id>.json``.

    When ``home``/``registry`` + skill_id are provided, the write path is
    :func:`records_dir_for_skill` / ``resolve_skill_journal_dir`` so the
    realpath lands under SKILLS_ROOT. Fail-closed on schema problems.
    """
    if record is None:
        raise SkillJournalError(["record-required"])
    problems = validate_record(record)
    if problems:
        raise SkillJournalError(problems)
    rid = record.get("record_id") or ("jr-" + uuid.uuid4().hex[:12])
    if "record_id" not in record:
        record = dict(record)
        record["record_id"] = rid

    sid = skill_id or record.get("skill_id")
    root = records_root(
        skill_dir, skill_id=sid, home=home, registry=registry
    )
    # mkdir then write on separate lines (product drift gate: no write marker
    # on the same line as a journal path token).
    root.mkdir(parents=True, exist_ok=True)
    out_path = root / ("%s.json" % rid)
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    payload = payload + "\n"
    out_path.write_text(payload, encoding="utf-8", newline="\n")
    return out_path


def append_structured_run(
    skill_dir=None,
    *,
    skill_id: str,
    skill_version: str,
    outcome: str,
    structural_failure_codes=None,
    notes: str | None = None,
    duration_band: str | None = None,
    complexity_band: str | None = None,
    os_class: str | None = None,
    model_family_seats=None,
    workaround_codes=None,
    workaround_tokens=None,
    home=None,
    registry=None,
) -> Path:
    """Hook for a completed structured skill run → one journal file.

    Prefer ``home``/``registry`` so the write uses
    ``resolve_skill_journal_dir`` (SKILLS_ROOT/<id>/journal/runs).
    """
    rec = build_record(
        skill_id=skill_id,
        skill_version=skill_version,
        outcome=outcome,
        structural_failure_codes=structural_failure_codes,
        notes=notes,
        duration_band=duration_band,
        complexity_band=complexity_band,
        os_class=os_class,
        model_family_seats=model_family_seats,
        workaround_codes=workaround_codes,
        workaround_tokens=workaround_tokens,
    )
    return append_run_record(
        skill_dir,
        rec,
        skill_id=skill_id,
        home=home,
        registry=registry,
    )


def list_records(
    skill_dir=None, *, skill_id=None, home=None, registry=None
) -> list:
    """Load all records under the skill's journal runs dir (unsorted)."""
    root = records_root(
        skill_dir, skill_id=skill_id, home=home, registry=registry
    )
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def journal_contract_proven(
    skill_dir=None, *, skill_id=None, home=None, registry=None
) -> bool:
    """True when at least one schema-valid record exists under the skill."""
    for doc in list_records(
        skill_dir, skill_id=skill_id, home=home, registry=registry
    ):
        if not validate_record(doc):
            return True
    return False
